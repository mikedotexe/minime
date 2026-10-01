//! Bounded stdin-only review of frozen numerical health samples. No runtime entrypoint.
use anyhow::{bail, ensure, Context, Result};
use minime::{
    rescue_overfill::OverfillStage,
    stable_covariance::{MeasurementInput, RestartSettleObservationV1},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read};

fn number(value: &Value, path: &str) -> Result<f64> {
    value
        .pointer(path)
        .and_then(Value::as_f64)
        .filter(|v| v.is_finite())
        .with_context(|| format!("missing or invalid number {path}"))
}

fn boolean(value: &Value, path: &str) -> Result<bool> {
    value
        .pointer(path)
        .and_then(Value::as_bool)
        .with_context(|| format!("missing boolean {path}"))
}

fn review(bytes: &[u8]) -> Result<Value> {
    let receipt: Value = serde_json::from_slice(bytes)?;
    ensure!(
        receipt["schema"] == "read_only_semantic_settle_observation_v1",
        "unknown observation schema"
    );
    ensure!(
        receipt["errors"].as_array().is_some_and(Vec::is_empty),
        "observation has errors"
    );
    let samples = receipt["samples"].as_array().context("missing samples")?;
    ensure!(
        !samples.is_empty() && samples.len() <= 512,
        "sample limit is 1..512"
    );
    let mut previous_t = -1.0;
    let mut rows = Vec::new();
    let mut reasons = BTreeMap::<String, usize>::new();
    for sample in samples {
        let t = number(sample, "/t_s")?;
        ensure!(t > previous_t, "nonadvancing engine time or mixed boot");
        previous_t = t;
        let core = &sample["stable_core"];
        let stage = match core["stage"].as_str() {
            Some("bootstrap") => OverfillStage::Bootstrap,
            Some("recovery") => OverfillStage::Recovery,
            Some("hold") => OverfillStage::Hold,
            Some("elevated") => OverfillStage::Elevated,
            Some("discharge") => OverfillStage::Discharge,
            _ => bail!("missing/unknown stage"),
        };
        let rate_value = sample
            .pointer("/fill_rate_v1/rate_pct_per_sec")
            .context("missing rate")?;
        let rate = if rate_value.is_null() {
            None
        } else {
            Some(number(sample, "/fill_rate_v1/rate_pct_per_sec")? as f32)
        };
        let fill = if boolean(sample, "/fill_measurement_valid")? {
            number(sample, "/fill_pct")? as f32
        } else {
            f32::NAN
        };
        let input = MeasurementInput {
            now_unix_ms: 1,
            fill_pct: fill,
            rate,
            stage,
            semantic_active: boolean(sample, "/semantic/kernel_active")?,
            scaffold_available: true,
            live_audio_divisor: 0,
            live_video_divisor: 0,
            reentry_active: boolean(core, "/structural_pi/reentry_active")?,
            recovery_active: boolean(core, "/structural_pi/recovery_impulse_active")?
                || boolean(core, "/structural_pi/low_fill_escape_active")?,
            high_fill_drain_active: boolean(core, "/structural_pi/high_fill_drain_active")?,
            applied_drain_weight: number(core, "/structural_pi/applied_drain_weight")? as f32,
        };
        // Evaluate each sampled proxy independently. Missing engine ticks and
        // different telemetry clocks cannot establish a consecutive settle proof.
        let mut observation = RestartSettleObservationV1::default();
        observation.record(input, boolean(core, "/scaffold_active")?);
        let eligible = observation.consecutive_numerical_candidates == 1;
        *reasons
            .entry(observation.numerical_reason.into())
            .or_default() += 1;
        rows.push(json!({"t_s":t,"health_sha256":sample["health_sha256"],
            "reported_gate_reason":core["restart_gate"]["settle_candidate_reason"],
            "reported_kernel_active":input.semantic_active,
            "numerically_eligible_sample_proxy":eligible,
            "numerical_reason":observation.numerical_reason}));
    }
    Ok(json!({"schema":"restart_settle_sample_review_v1",
        "authority":"offline_sample_proxy_not_live_settlement_or_retirement",
        "input_sha256":format!("{:x}",Sha256::digest(bytes)),
        "source_sha256":{
            "restart_settle_replay":format!("{:x}",Sha256::digest(include_bytes!("restart_settle_replay.rs"))),
            "settle_observation":format!("{:x}",Sha256::digest(include_bytes!("../stable_covariance/settle_observation.rs"))),
            "rescue_scaffold":format!("{:x}",Sha256::digest(include_bytes!("../rescue_scaffold.rs")))},
        "sample_count":rows.len(),"numerical_reason_counts":reasons,
        "eligible_sample_count":rows.iter().filter(|r|r["numerically_eligible_sample_proxy"]==true).count(),
        "limitations":"coarse health samples; controller inputs may precede rendered telemetry; each sample evaluated independently, no consecutive proof inferred",
        "rows":rows}))
}

fn main() -> Result<()> {
    ensure!(
        std::env::args().len() == 1,
        "accepts bounded frozen JSON on stdin only"
    );
    let mut bytes = Vec::new();
    std::io::stdin().take(2_097_153).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 2_097_152, "input exceeds 2 MiB");
    println!("{}", serde_json::to_string_pretty(&review(&bytes)?)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Value {
        json!({"t_s":1.0,"fill_pct":68.0,"fill_measurement_valid":true,
            "fill_rate_v1":{"rate_pct_per_sec":0.0},"semantic":{"kernel_active":true},
            "stable_core":{"stage":"hold","scaffold_active":true,
                "restart_gate":{"settle_candidate_reason":"semantic_active"},
                "structural_pi":{"reentry_active":false,"recovery_impulse_active":false,
                    "low_fill_escape_active":false,"high_fill_drain_active":false,"applied_drain_weight":0.0}}})
    }

    fn receipt(samples: Value) -> Vec<u8> {
        serde_json::to_vec(&json!({"schema":"read_only_semantic_settle_observation_v1","errors":[],"samples":samples})).unwrap()
    }

    #[test]
    fn numerical_sample_eligibility_is_not_a_live_settle_proof() {
        let result = review(&receipt(json!([sample()]))).unwrap();
        assert_eq!(result["eligible_sample_count"], 1);
        assert_eq!(result["rows"][0]["reported_gate_reason"], "semantic_active");
        assert!(result.get("settled").is_none());
    }

    #[test]
    fn missing_invalid_and_duplicate_observations_do_not_become_evidence() {
        assert!(review(&receipt(json!([]))).is_err());
        assert!(review(&receipt(json!([sample(), sample()]))).is_err());
        let mut missing = sample();
        missing["stable_core"]["structural_pi"]["reentry_active"] = Value::Null;
        assert!(review(&receipt(json!([missing]))).is_err());
        for value in [Value::Null, json!(1e300)] {
            let mut unavailable = sample();
            unavailable["fill_rate_v1"]["rate_pct_per_sec"] = value;
            assert_eq!(
                review(&receipt(json!([unavailable]))).unwrap()["eligible_sample_count"],
                0
            );
        }
    }
}
