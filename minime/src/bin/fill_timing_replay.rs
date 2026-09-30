//! Read-only open-loop comparison over a frozen afterimage. Never starts an engine.
use anyhow::{ensure, Context, Result};
use clap::Parser;
use minime::{
    fill_timing::FillRateTracker,
    rescue_overfill::OverfillStage,
    rescue_scaffold::{StabilityPiOutput, StabilityPiState},
    transition_afterimage::{Artifact, POLICY},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::PathBuf, time::Duration};

const MAX_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Parser)]
struct Args {
    #[arg(long)]
    archive: PathBuf,
    #[arg(long, default_value_t = 0.5)]
    nominal_seconds: f64,
}

fn decision(output: StabilityPiOutput) -> Value {
    json!({
        "active": output.active, "integral": output.integral,
        "pi_output": output.pi_output, "drain_weight": output.drain_weight,
        "drain_gate_reason": output.drain_gate_reason,
        "recovery_impulse_active": output.recovery_impulse_active,
        "recovery_identity_reset_requested": output.recovery_identity_reset_requested,
        "reentry_active": output.reentry_active, "reentry_live_weight": output.reentry_live_weight,
    })
}

fn replay(artifact: &Artifact, nominal_seconds: f64) -> Result<Value> {
    ensure!(
        artifact.policy == POLICY && artifact.schema_version == 1,
        "unsupported archive schema"
    );
    ensure!(
        nominal_seconds.is_finite() && nominal_seconds > 0.0,
        "positive finite nominal interval required"
    );
    ensure!(artifact.samples.len() <= 4096, "sample limit exceeded");
    let mut clock = FillRateTracker::default();
    let mut previous = None;
    let mut nominal_pi = StabilityPiState::default();
    let mut observed_pi = StabilityPiState::default();
    let mut differences = 0;
    let mut rows = Vec::new();
    for sample in artifact.samples.iter().filter(|s| s.channel == "body") {
        let fill = sample
            .number("/fill_pct")
            .context("body fill missing or invalid")? as f32;
        ensure!(fill.is_finite(), "fill outside f32 range");
        if let Some((last_time, _)) = previous {
            ensure!(
                sample.engine_t_ms > last_time,
                "body timestamps must increase; no sorting or interpolation"
            );
        }
        let observed = clock.observe(Duration::from_millis(sample.engine_t_ms), fill);
        let nominal = previous
            .map(|(_, last_fill)| (f64::from(fill) - f64::from(last_fill)) / nominal_seconds);
        // Both states start at default. This is a policy sensitivity comparison,
        // not reconstruction of the live controller's state or update schedule.
        let (old, corrected) = if let Some(rate) = nominal {
            ensure!((rate as f32).is_finite(), "nominal rate outside f32 range");
            let old = decision(nominal_pi.step(fill, rate as f32, OverfillStage::Hold, true));
            let corrected = decision(observed_pi.step(
                fill,
                observed.controller_value(),
                OverfillStage::Hold,
                true,
            ));
            differences += usize::from(old != corrected);
            (Some(old), Some(corrected))
        } else {
            (None, None)
        };
        rows.push(json!({
            "engine_t_ms": sample.engine_t_ms, "fill_pct": fill,
            "recorded_rate_pct_per_sec": sample.number("/dfill_dt"),
            "nominal_rate_pct_per_sec": nominal, "observed": observed,
            "nominal_pi_decision": old, "observed_pi_decision": corrected,
        }));
        previous = Some((sample.engine_t_ms, fill));
    }
    ensure!(rows.len() >= 2, "at least two body samples required");
    Ok(json!({
        "policy": "fill-timing-open-loop-v1", "artifact_id": artifact.id,
        "nominal_seconds": nominal_seconds, "body_samples": rows.len(),
        "decision_differences": differences, "rows": rows,
        "assumptions": "Fixed Hold stage, scaffold active, default PI states, one step per successive body sample; first sample primes timing only.",
        "limits": "Sampled endpoints only; no interpolation. Not a closed-loop simulation, live controller reconstruction, cadence repair, or evidence of felt improvement. Other gates and tick-based timers are not qualified here.",
        "live_activation_authorized": false,
    }))
}

fn main() -> Result<()> {
    let args = Args::parse();
    let file = File::open(&args.archive)?;
    ensure!(file.metadata()?.is_file(), "archive must be a regular file");
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() as u64 <= MAX_BYTES, "archive exceeds 8 MiB");
    let artifact: Artifact = serde_json::from_slice(&bytes)?;
    let mut result = replay(&artifact, args.nominal_seconds)?;
    result["source_sha256"] = json!(format!("{:x}", Sha256::digest(&bytes)));
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Artifact {
        serde_json::from_str(include_str!(
            "../../../tests/fixtures/transition_afterimage_v1.json"
        ))
        .unwrap()
    }

    #[test]
    fn compares_actual_production_policy_without_claiming_live_reconstruction() {
        let mut artifact = fixture();
        for (sample, (time, fill)) in
            artifact
                .samples
                .iter_mut()
                .zip([(0, 46.0), (3000, 44.0), (6000, 43.0)])
        {
            sample.engine_t_ms = time;
            sample.values["fill_pct"] = json!(fill);
        }
        let result = replay(&artifact, 0.5).unwrap();
        assert_eq!(result["decision_differences"], 2);
        assert!(result["rows"][0]["observed"]["rate_pct_per_sec"].is_null());
        assert_eq!(result["live_activation_authorized"], false);
    }

    #[test]
    fn rejects_bad_evidence_without_reordering_or_inventing_samples() {
        let mut artifact = fixture();
        assert!(replay(&artifact, 0.0).is_err());
        artifact.samples[1].engine_t_ms = artifact.samples[0].engine_t_ms;
        assert!(replay(&artifact, 0.5).is_err());
        artifact = fixture();
        artifact.samples[1].values["fill_pct"] = Value::Null;
        assert!(replay(&artifact, 0.5).is_err());
        artifact = fixture();
        artifact.schema_version = 2;
        assert!(replay(&artifact, 0.5).is_err());
    }
}
