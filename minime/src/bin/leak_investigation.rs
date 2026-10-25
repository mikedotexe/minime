//! Bounded synthetic, open-loop study of the production ESN. No runtime handles.
use anyhow::{ensure, Context, Result};
use clap::Parser;
use minime::{
    esn::{EsnSnapshotV2, ESN},
    gpu::Gpu,
    semantic_body_v2::{
        LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1 as LEGACY, RESERVOIR_INPUT_DIMENSIONS_V2 as INPUTS,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

const POLICY: &str = "production-esn-leak-study-v1";
const SEEDS: [u64; 4] = [7, 17, 29, 43];
const LEAKS: [f32; 3] = [0.45, 0.65, 0.85];
const WARMUP: usize = 128;
const STEPS: usize = 512;
const NODES: usize = 128;

#[derive(Parser)]
struct Args {
    /// New directory only; evidence is never overwritten or read from live stores.
    #[arg(long)]
    output: PathBuf,
}

#[derive(Clone, Serialize, Deserialize)]
struct Trace {
    states: Vec<Vec<f32>>,
    effective_leaks: Vec<f32>,
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn save(root: &Path, name: &str, value: &impl Serialize) -> Result<String> {
    let bytes = serde_json::to_vec_pretty(value)?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(hash(&bytes))
}

fn inputs(kind: &str, seed: u64, count: usize) -> Vec<Vec<f32>> {
    let mut rng = fastrand::Rng::with_seed(seed ^ 0x1EA5);
    (0..count)
        .map(|tick| {
            let mut row = vec![0.0; INPUTS];
            for (index, value) in row[..LEGACY].iter_mut().enumerate() {
                let sign = if index % 2 == 0 { 1.0 } else { -1.0 };
                *value = match kind {
                    "impulse" if tick == 32 => 0.2 * sign,
                    "step_reversal" if (32..160).contains(&tick) => 0.2 * sign,
                    "step_reversal" if (160..288).contains(&tick) => -0.2 * sign,
                    "broadband" | "warmup" => (rng.f32() * 2.0 - 1.0) * 0.2,
                    _ => 0.0,
                };
            }
            row
        })
        .collect()
}

fn run(
    snapshot: &EsnSnapshotV2,
    input: &[Vec<f32>],
    gpu: &Gpu,
    restart_at: Option<usize>,
) -> Result<Trace> {
    let mut esn = ESN::from_snapshot_v2(snapshot, gpu)?;
    let mut trace = Trace {
        states: Vec::new(),
        effective_leaks: Vec::new(),
    };
    for (tick, row) in input.iter().enumerate() {
        if restart_at == Some(tick) {
            esn = ESN::from_snapshot_v2(&esn.snapshot_v2()?, gpu)?;
        }
        esn.step(row)?;
        ensure!(
            esn.x.len() == NODES && esn.x.iter().all(|x| x.is_finite()),
            "invalid state at {tick}"
        );
        ensure!(
            esn.last_step_trace().leak.is_finite(),
            "invalid leak at {tick}"
        );
        trace.states.push(esn.x.clone());
        trace.effective_leaks.push(esn.last_step_trace().leak);
    }
    Ok(trace)
}

fn rms(values: impl Iterator<Item = f64>, count: usize) -> f64 {
    (values.map(|x| x * x).sum::<f64>() / count as f64).sqrt()
}

fn distances(left: &Trace, right: &Trace) -> Result<Vec<f64>> {
    ensure!(
        left.states.len() == right.states.len(),
        "trajectory length mismatch"
    );
    left.states
        .iter()
        .zip(&right.states)
        .map(|(a, b)| {
            ensure!(
                a.len() == NODES && b.len() == NODES,
                "trajectory width mismatch"
            );
            Ok(rms(
                a.iter().zip(b).map(|(a, b)| f64::from(*a) - f64::from(*b)),
                NODES,
            ))
        })
        .collect()
}

fn autocorrelation(states: &[Vec<f32>], lag: usize) -> Option<f64> {
    if lag == 0 || lag >= states.len() {
        return None;
    }
    // Center each node over this recording, then pool the lagged inner products.
    let means: Vec<f64> = (0..NODES)
        .map(|node| {
            states.iter().map(|row| f64::from(row[node])).sum::<f64>() / states.len() as f64
        })
        .collect();
    let (mut cross, mut left, mut right) = (0.0, 0.0, 0.0);
    for (a, b) in states.iter().zip(states.iter().skip(lag)) {
        for ((a, b), mean) in a.iter().zip(b).zip(&means) {
            let x = f64::from(*a) - mean;
            let y = f64::from(*b) - mean;
            cross += x * y;
            left += x * x;
            right += y * y;
        }
    }
    if left <= 1e-12 || right <= 1e-12 {
        None
    } else {
        Some(cross / (left * right).sqrt())
    }
}

fn metrics(trace: &Trace) -> Value {
    let activations: Vec<f64> = trace
        .states
        .iter()
        .map(|row| rms(row.iter().copied().map(f64::from), NODES))
        .collect();
    let saturation: Vec<f64> = trace
        .states
        .iter()
        .map(|row| row.iter().filter(|x| x.abs() >= 0.99).count() as f64 / NODES as f64)
        .collect();
    let correlations: Vec<Value> = [1, 2, 4, 8, 16, 32, 64]
        .into_iter()
        .map(|lag| {
            let value = autocorrelation(&trace.states, lag);
            json!({"lag_updates":lag, "value":value, "degenerate":value.is_none()})
        })
        .collect();
    json!({"activation_rms":activations, "saturation_fraction_abs_ge_0_99":saturation,
        "lagged_node_centered_autocorrelation":correlations,
        "effective_leak_min":trace.effective_leaks.iter().copied().reduce(f32::min),
        "effective_leak_max":trace.effective_leaks.iter().copied().reduce(f32::max)})
}

fn control(name: &str, left: &Trace, right: &Trace) -> Result<Value> {
    let maximum = distances(left, right)?.into_iter().fold(0.0, f64::max);
    let leak_delta = left
        .effective_leaks
        .iter()
        .zip(&right.effective_leaks)
        .map(|(a, b)| f64::from((a - b).abs()))
        .fold(0.0, f64::max);
    Ok(
        json!({"name":name, "max_state_rms_delta":maximum, "max_leak_delta":leak_delta,
        "tolerance":1e-6, "passed":maximum<=1e-6 && leak_delta<=1e-6}),
    )
}

fn override_control(snapshot: &EsnSnapshotV2, gpu: &Gpu) -> Result<Value> {
    let mut esn = ESN::from_snapshot_v2(snapshot, gpu)?;
    esn.set_leak_override(0.3, 3, "offline-expiry".into());
    let mut leaks = Vec::new();
    let zero = vec![0.0; INPUTS];
    for tick in 0..5 {
        if tick == 1 {
            esn = ESN::from_snapshot_v2(&esn.snapshot_v2()?, gpu)?;
        }
        esn.step(&zero)?;
        leaks.push(esn.last_step_trace().leak);
    }
    let final_snapshot = esn.snapshot_v2()?;
    Ok(
        json!({"name":"bounded_override_restart_expiry", "effective_leaks":leaks,
        "passed":leaks[..3].iter().all(|x| (*x-0.3).abs()<=1e-6) && final_snapshot.leak_override.is_none(),
        "scope":"Direct ESN only; stable-core clears direct overrides in live orchestration."}),
    )
}

fn study(root: &Path) -> Result<()> {
    let sources = [
        ("runner", include_str!("leak_investigation.rs")),
        ("esn.rs", include_str!("../esn.rs")),
        ("gpu.rs", include_str!("../gpu.rs")),
        ("prime.rs", include_str!("../prime.rs")),
        ("esn.metal", include_str!("../../shaders/esn.metal")),
        (
            "semantic_body_v2.rs",
            include_str!("../semantic_body_v2.rs"),
        ),
        ("Cargo.lock", include_str!("../../Cargo.lock")),
    ];
    let source_ids: Vec<Value> = sources
        .iter()
        .map(|(name, content)| json!({"path":name,"sha256":hash(content.as_bytes())}))
        .collect();
    let manifest = json!({"policy":POLICY,"seeds":SEEDS,"base_leaks":LEAKS,"warmup_updates":WARMUP,"measured_updates":STEPS,
        "nodes":NODES,"input_dimensions":INPUTS,"legacy_dimensions":LEGACY,"companion_lane":"all zero",
        "constructor":{"input_scale":0.5,"density":0.1,"target_radius":0.9,"warmup_leak_base":0.65,"lambda_base":0.995},
        "measurement_mode":"production synchronous spectral rank-one path (profiling enabled)",
        "synthetic":true,"sources":source_ids,"binary_sha256":hash(&fs::read(std::env::current_exe()?)?),
        "controls":["identical replay", "midpoint snapshot/restart", "matched zero input", "zero noise", "bounded override expiry across restart"],
        "units":"ESN updates, not elapsed time. Zero input still updates state.",
        "limits":"Open-loop production ESN only; not the separate engine covariance/structural controller, published fill, model output or experience. Adaptive leak remains enabled. No live leak change authorized."});
    save(root, "manifest.json", &manifest)?;
    let gpu = Gpu::new()?;
    let mut results = Vec::new();
    let mut controls = Vec::new();
    for seed in SEEDS {
        let mut rng = fastrand::Rng::with_seed(seed);
        let mut esn = ESN::new(NODES, LEGACY, 0.5, 0.1, 0.9, 0.65, 0.995, &gpu, &mut rng)?;
        esn.expand_input_zero_compatible(INPUTS, 0.5)?;
        esn.set_profiling_enabled(true);
        let warmup = inputs("warmup", seed, WARMUP);
        let construction = esn.snapshot_v2()?;
        save(
            root,
            &format!("seed-{seed}-construction.json"),
            &construction,
        )?;
        save(root, &format!("seed-{seed}-warmup.json"), &warmup)?;
        for row in &warmup {
            esn.step(row)?;
        }
        let snapshot = esn.snapshot_v2()?;
        let snapshot_hash = save(root, &format!("seed-{seed}-initial.json"), &snapshot)?;
        controls.push(override_control(&snapshot, &gpu)?);
        for kind in ["impulse", "step_reversal", "broadband", "zero"] {
            let input = inputs(kind, seed, STEPS);
            let input_hash = save(root, &format!("seed-{seed}-{kind}-input.json"), &input)?;
            for zero_noise in [false, true] {
                let mut trajectories = Vec::new();
                for leak in LEAKS {
                    let mut paired = snapshot.clone();
                    paired.leak_base = leak;
                    if zero_noise {
                        paired.exploration_noise = 0.0;
                    }
                    let trace = run(&paired, &input, &gpu, None)?;
                    let name = format!("seed-{seed}-{kind}-leak-{leak}-zero-noise-{zero_noise}");
                    let trace_hash = save(root, &format!("{name}.json"), &trace)?;
                    results.push(json!({"id":name,"seed":seed,"fixture":kind,"base_leak":leak,"zero_noise":zero_noise,
                        "initial_snapshot_sha256":snapshot_hash,"input_sha256":input_hash,"trace_sha256":trace_hash,"metrics":metrics(&trace)}));
                    if leak == 0.65 && kind == "broadband" && !zero_noise {
                        let replay = run(&paired, &input, &gpu, None)?;
                        save(root, &format!("{name}-replay.json"), &replay)?;
                        controls.push(control(
                            &format!("seed-{seed}-identical-replay"),
                            &trace,
                            &replay,
                        )?);
                        let restart = run(&paired, &input, &gpu, Some(256))?;
                        save(root, &format!("{name}-restart.json"), &restart)?;
                        controls.push(control(
                            &format!("seed-{seed}-snapshot-restart"),
                            &trace,
                            &restart,
                        )?);
                    }
                    trajectories.push(trace);
                }
                for pair in [(0, 1), (1, 2), (0, 2)] {
                    results.push(json!({"seed":seed,"fixture":kind,"zero_noise":zero_noise,"leak_pair":[LEAKS[pair.0],LEAKS[pair.1]],
                        "paired_trajectory_rms_by_update":distances(&trajectories[pair.0],&trajectories[pair.1])?}));
                }
            }
        }
    }
    // Matched zero trajectories separate response/recovery from autonomous noise.
    for seed in SEEDS {
        for leak in LEAKS {
            for zero_noise in [false, true] {
                let zero: Trace = serde_json::from_slice(&fs::read(root.join(format!(
                    "seed-{seed}-zero-leak-{leak}-zero-noise-{zero_noise}.json"
                )))?)?;
                for kind in ["impulse", "step_reversal", "broadband"] {
                    let trace: Trace = serde_json::from_slice(&fs::read(root.join(format!(
                        "seed-{seed}-{kind}-leak-{leak}-zero-noise-{zero_noise}.json"
                    )))?)?;
                    results.push(
                        json!({"seed":seed,"fixture":kind,"base_leak":leak,"zero_noise":zero_noise,
                        "response_recovery_rms_from_matched_zero_input":distances(&trace,&zero)?}),
                    );
                }
            }
        }
    }
    let passed = controls.iter().all(|row| row["passed"] == true);
    save(
        root,
        "report.json",
        &json!({"policy":POLICY,"controls_passed":passed,"controls":controls,"results":results,
        "interpretation":"Descriptive paired sensitivity only. Constant/degenerate autocorrelations are null; no persistence threshold or language-effect verdict is inferred."}),
    )?;
    ensure!(passed, "one or more controls failed; all results retained");
    Ok(())
}

fn main() -> Result<()> {
    let args = Args::parse();
    ensure!(!args.output.exists(), "output directory already exists");
    fs::create_dir(&args.output).context("create fresh evidence directory")?;
    if let Err(error) = study(&args.output) {
        save(
            &args.output,
            "failure.json",
            &json!({"policy":POLICY,"error":format!("{error:#}"),"partial_results_retained":true}),
        )?;
        return Err(error);
    }
    println!("{} complete: {}", POLICY, args.output.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixtures_are_bounded_repeatable_and_companion_free() {
        for kind in ["warmup", "impulse", "step_reversal", "broadband", "zero"] {
            let rows = inputs(kind, 7, STEPS);
            assert_eq!(rows, inputs(kind, 7, STEPS));
            assert!(rows.iter().all(|row| row.len() == INPUTS
                && row.iter().all(|v| v.abs() <= 0.2)
                && row[LEGACY..].iter().all(|v| *v == 0.0)));
        }
    }
    #[test]
    fn covariance_is_not_used_as_temporal_persistence() {
        let constant = vec![vec![0.2; NODES]; STEPS];
        assert_eq!(autocorrelation(&constant, 1), None);
        let alternating: Vec<Vec<f32>> = (0..STEPS)
            .map(|i| vec![if i % 2 == 0 { 0.2 } else { -0.2 }; NODES])
            .collect();
        assert!((autocorrelation(&alternating, 1).unwrap() + 1.0).abs() < 1e-12);
        assert!((autocorrelation(&alternating, 2).unwrap() - 1.0).abs() < 1e-12);
        assert_eq!(autocorrelation(&alternating, STEPS), None);
    }
    #[test]
    fn distance_has_independent_constant_oracle() {
        let a = Trace {
            states: vec![vec![0.2; NODES]; 4],
            effective_leaks: vec![0.5; 4],
        };
        let b = Trace {
            states: vec![vec![-0.2; NODES]; 4],
            effective_leaks: vec![0.5; 4],
        };
        assert!(distances(&a, &b)
            .unwrap()
            .iter()
            .all(|d| (*d - 0.4).abs() < 1e-7));
        assert_eq!(control("identical", &a, &a).unwrap()["passed"], true);
        assert_eq!(control("different", &a, &b).unwrap()["passed"], false);
    }
}
