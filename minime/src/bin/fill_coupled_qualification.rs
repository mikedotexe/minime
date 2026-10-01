//! Bounded synthetic qualification. No runtime entrypoint, sockets or checkpoint paths.
use anyhow::{ensure, Result};
use minime::{
    covariance_math::reset_covariance_inplace,
    fill_timing::FillRateTracker,
    gpu::{gs_orthonormalize_colmajor, rayleigh_quotient, Gpu},
    measurement_basis::BasisReport,
    rescue_overfill::{self, OverfillStage},
    rescue_scaffold::{RescueScaffold, StabilityPiState, StableCoreRestartGate},
    spectral::EigenFillEstimator,
    stable_core::StableCoreRuntime,
    stable_covariance::{self, MeasurementInput, ScaffoldLifecycle, StepInput},
};
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::time::{Duration, Instant};

const K: usize = 8;
const STEPS: usize = 48;
const SEED: u64 = 0x3009_2026;

#[derive(Clone, Copy, Debug)]
enum Scenario {
    Cold,
    Restored,
    LowRank,
    LowRankExtended,
    SkippedRegulation,
    InvalidObservation,
    MatrixFault,
    Restart,
    Semantic,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Timing {
    Observed,
    Nominal,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Schedule {
    Nominal500,
    Delayed2370,
    MixedGaps,
}

impl Schedule {
    fn elapsed_ms(self, tick: usize) -> u64 {
        match self {
            Self::Nominal500 => 500,
            Self::Delayed2370 => 2370,
            Self::MixedGaps => [500, 2370, 3000, 50, 10000][tick % 5],
        }
    }
}

#[derive(Serialize, Debug, PartialEq)]
struct Row {
    tick: usize,
    time_ms: u64,
    fill_pct: Option<f32>,
    eigenvalues: Vec<f32>,
    basis: BasisReport,
    estimator_ema_mean: f32,
    matrix_trace: f32,
    rate: Option<f32>,
    control_fill_pct: Option<f32>,
    control_rate: Option<f32>,
    regulation_rate: Option<f32>,
    stage: String,
    mode: String,
    drain: f32,
    recovery: bool,
    reentry: bool,
    reset: bool,
    generation: Option<u64>,
    scaffold: bool,
    settled: bool,
    intake_reason: String,
    matrix_hash: String,
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn matrix_hash(matrix: &[f32]) -> String {
    let mut digest = Sha256::new();
    for value in matrix {
        digest.update(value.to_le_bytes());
    }
    format!("{:x}", digest.finalize())
}

fn scaffold(dim: usize) -> RescueScaffold {
    let mut matrix = vec![0.0; dim * dim];
    reset_covariance_inplace(&mut matrix, dim);
    RescueScaffold {
        matrix,
        dim,
        trace: dim as f32,
        source: "synthetic_identity_fixture".into(),
        loaded_at_unix_ms: 0,
        profile_version: None,
        captured_at_unix_ms: None,
        captured_fill_pct: None,
        captured_geom_rel: None,
        captured_stage: None,
        derived_from: None,
        cold_profile: None,
        activation_policy: None,
        mode_cap: None,
        stable_weight: None,
        diagonal_weight: None,
        activation_fill_band: None,
    }
}

fn intake_runtime() -> StableCoreRuntime {
    StableCoreRuntime::from_lookup(|key| match key {
        "MINIME_STABLE_CORE" => Some("1".into()),
        "MINIME_RESCUE_LIVE_AUDIO_DIVISOR" => Some("7".into()),
        "MINIME_RESCUE_LIVE_VIDEO_DIVISOR" => Some("11".into()),
        "MINIME_RESCUE_LIVE_INTAKE_STAGES" => Some("hold,elevated,recovery".into()),
        _ => None,
    })
}

// Mirror the runtime's measurement operator using its exact GPU and CPU primitives.
fn measure(
    gpu: &Gpu,
    matrix: &metal::Buffer,
    basis: &metal::Buffer,
    product: &metal::Buffer,
    dim: usize,
) -> Result<(Vec<f32>, BasisReport)> {
    gpu.block_matvec(matrix, basis, product, dim as u32, K as u32)?;
    let report = gs_orthonormalize_colmajor(gpu.as_f32_slice_mut(product, dim * K), dim, K);
    ensure!(report.input_finite(), "nonfinite measurement-basis input");
    let y = gpu.as_f32_slice(product, dim * K);
    gpu.as_f32_slice_mut(basis, dim * K).copy_from_slice(y);
    gpu.mark_modified_f32(basis, dim * K);
    let a = gpu.as_f32_slice(matrix, dim * dim);
    Ok((
        (0..K)
            .map(|i| rayleigh_quotient(a, &y[i * dim..(i + 1) * dim], dim))
            .collect(),
        report,
    ))
}

fn select_guard(
    fill: f32,
    stage: &mut OverfillStage,
    pi: &mut StabilityPiState,
    gate: f32,
    filter: f32,
    keep: f32,
) -> rescue_overfill::OverfillGuard {
    if fill.is_finite() {
        let next = rescue_overfill::select_stage(fill, *stage);
        if next != *stage {
            pi.integral = 0.0;
        }
        *stage = next;
    }
    let mut guard = rescue_overfill::stage_guard_for_state(*stage, fill, 0.0);
    if rescue_overfill::stable_core_command_slew_active(*stage, fill) {
        guard = rescue_overfill::slew_guard_commands(guard, gate, filter, keep);
    }
    guard
}

fn run(
    gpu: &Gpu,
    dim: usize,
    scenario: Scenario,
    timing: Timing,
    schedule: Schedule,
    seed: u64,
) -> Result<Vec<Row>> {
    ensure!(
        (K..=512).contains(&dim),
        "dimension outside qualification bound"
    );
    let deadline = Instant::now() + Duration::from_secs(120);
    let fixture = scaffold(dim);
    let mut matrix = fixture.matrix.clone();
    if matches!(scenario, Scenario::LowRank | Scenario::LowRankExtended) {
        matrix.fill(0.0);
        matrix[0] = dim as f32;
    }
    let mut rng = fastrand::Rng::with_seed(seed);
    let mut basis = (0..dim * K).map(|_| rng.f32() - 0.5).collect::<Vec<_>>();
    let _ = gs_orthonormalize_colmajor(&mut basis, dim, K);
    let a = gpu.new_shared((matrix.len() * 4) as u64);
    let x = gpu.new_shared((basis.len() * 4) as u64);
    let y = gpu.new_shared((basis.len() * 4) as u64);
    gpu.write_f32(&a, &matrix);
    gpu.write_f32(&x, &basis);
    let mut estimator = EigenFillEstimator::fixed_survival(K);
    let restored = !matches!(scenario, Scenario::Cold);
    if restored {
        // A synthetic measured prehistory, not an assigned desired fill.
        for _ in 0..40 {
            let (spectrum, _) = measure(gpu, &a, &x, &y, dim)?;
            estimator.update_with_elapsed(&spectrum, Duration::from_millis(500));
        }
        estimator = EigenFillEstimator::from_snapshot_v1(&estimator.snapshot_v1());
    }
    let mut measured = FillRateTracker::default();
    let mut regulated = FillRateTracker::default();
    let mut pi = StabilityPiState::default();
    let mut restart = StableCoreRestartGate::new(0);
    let mut lifecycle = ScaffoldLifecycle {
        active: restored,
        retirement_ticks: 0,
        retirement_reason: "synthetic_initial_state",
    };
    if restored {
        restart.record_scaffold_activated(0, estimator.fill() * 100.0, "synthetic_restoration");
    }
    let mut stage = OverfillStage::Bootstrap;
    let mut keep = 0.955;
    let mut gate = 0.0;
    let mut filter = 0.0;
    let mut live_audio = 0;
    let mut live_video = 0;
    let runtime = intake_runtime();
    let mut time_ms: u64 = 0;
    let mut previous_nominal = None;
    let mut control_rate = None;
    let mut rows = Vec::new();
    let steps = if matches!(scenario, Scenario::LowRankExtended) {
        144
    } else {
        STEPS
    };
    for tick in 0..steps {
        ensure!(
            Instant::now() < deadline,
            "qualification wall-clock limit exceeded"
        );
        let elapsed_ms = schedule.elapsed_ms(tick);
        time_ms += elapsed_ms;
        if matches!(scenario, Scenario::Restart) && tick == 20 {
            estimator = EigenFillEstimator::from_snapshot_v1(&estimator.snapshot_v1());
            measured = FillRateTracker::default();
            regulated = FillRateTracker::default();
            previous_nominal = None;
            control_rate = None;
            pi = StabilityPiState::default();
            restart = StableCoreRestartGate::new(time_ms);
        }
        let previous = measured.latest();
        let input_rate = control_rate;
        let control_fill = previous.map_or(f32::NAN, |value| value.fill_pct);
        let guard = select_guard(control_fill, &mut stage, &mut pi, gate, filter, keep);
        keep = guard.cov_keep_max.unwrap_or(keep);
        // Inputs are supplied at the projected-vector boundary, not from live senses.
        let stimulus: Vec<f32> = (0..dim)
            .map(|node| {
                let phase = (node as f32 + tick as f32 * 0.7) * 0.13;
                phase.sin() * if (12..24).contains(&tick) { 2.0 } else { 0.4 }
            })
            .collect();
        if matches!(scenario, Scenario::MatrixFault) && tick == 20 {
            lifecycle.active = false;
            gpu.as_f32_slice_mut(&a, dim * dim)[0] = f32::NAN;
        }
        let result = stable_covariance::step(
            gpu.as_f32_slice_mut(&a, dim * dim),
            &stimulus,
            &mut pi,
            &mut restart,
            StepInput {
                dim,
                fill_pct: control_fill,
                rate: input_rate,
                stage,
                guard,
                scaffold_active: lifecycle.active,
                scaffold: Some(&fixture),
                keep,
                pressure_bias: 0.0,
                now_unix_ms: time_ms,
            },
        );
        if result.modified {
            gpu.mark_modified_f32(&a, dim * dim);
        }
        if result.covariance_reset {
            measured.reset();
            regulated.reset();
            previous_nominal = None;
        }
        let (spectrum, basis_report) = measure(gpu, &a, &x, &y, dim)?;
        ensure!(
            spectrum.iter().all(|value| value.is_finite()),
            "nonfinite spectrum"
        );
        let actual_fill =
            estimator.update_with_elapsed(&spectrum, Duration::from_millis(elapsed_ms)) * 100.0;
        let invalid = matches!(scenario, Scenario::InvalidObservation) && (20..23).contains(&tick);
        let observed_fill = if invalid { f32::NAN } else { actual_fill };
        if invalid {
            regulated.reset();
            previous_nominal = None;
        }
        let rate = measured.observe(Duration::from_millis(time_ms), observed_fill);
        let nominal = previous_nominal
            .map(|fill: f32| (observed_fill - fill) / 0.5)
            .filter(|value| value.is_finite());
        previous_nominal = observed_fill.is_finite().then_some(observed_fill);
        control_rate = if timing == Timing::Observed {
            rate.rate_pct_per_sec
        } else {
            nominal
        };
        let guard = select_guard(observed_fill, &mut stage, &mut pi, gate, filter, keep);
        keep = guard.cov_keep_max.unwrap_or(keep);
        let semantic = matches!(scenario, Scenario::Semantic) && (12..28).contains(&tick);
        stable_covariance::record_measurement(
            &mut lifecycle,
            &mut restart,
            MeasurementInput {
                now_unix_ms: time_ms,
                fill_pct: observed_fill,
                rate: control_rate,
                stage,
                semantic_active: semantic,
                scaffold_available: true,
                live_audio_divisor: live_audio,
                live_video_divisor: live_video,
                reentry_active: result.pi.reentry_active,
                recovery_active: result.pi.recovery_impulse_active
                    || result.pi.low_fill_escape_active,
                high_fill_drain_active: result.pi.high_fill_drain_active,
                applied_drain_weight: result.drain_weight,
            },
        );
        let preview = pi.preview(observed_fill, control_rate, stage, lifecycle.active);
        let intake = runtime.live_intake_decision_for_stage(
            &format!("{stage:?}").to_ascii_lowercase(),
            lifecycle.active,
            preview.high_fill_drain_active,
            observed_fill,
            control_rate,
        );
        (live_audio, live_video) = intake.divisors();
        let regulation_rate = if !matches!(scenario, Scenario::SkippedRegulation) || tick % 3 == 0 {
            gate = guard.gate_max.or(guard.gate_min).unwrap_or(gate);
            filter = guard.filt_min.or(guard.filt_max).unwrap_or(filter);
            Some(regulated.observe(Duration::from_millis(time_ms), observed_fill))
        } else {
            None
        };
        let matrix = gpu.as_f32_slice(&a, dim * dim);
        ensure!(
            matrix.iter().all(|value| value.is_finite()),
            "nonfinite covariance"
        );
        ensure!(
            (0.0..=100.0).contains(&actual_fill),
            "fill outside estimator bounds"
        );
        ensure!(
            (0.0..=1.0).contains(&result.drain_weight),
            "unbounded drain"
        );
        rows.push(Row {
            tick,
            time_ms,
            fill_pct: observed_fill.is_finite().then_some(observed_fill),
            eigenvalues: spectrum,
            basis: basis_report,
            estimator_ema_mean: estimator.snapshot_v1().ema_mean,
            matrix_trace: (0..dim).map(|i| matrix[i * dim + i]).sum(),
            rate: control_rate,
            control_fill_pct: previous.map(|value| value.fill_pct),
            control_rate: input_rate,
            regulation_rate: regulation_rate.and_then(|value| value.rate_pct_per_sec),
            stage: format!("{stage:?}"),
            mode: result.mode.into(),
            drain: result.drain_weight,
            recovery: result.pi.recovery_impulse_active,
            reentry: result.pi.reentry_active,
            reset: result.covariance_reset,
            generation: measured.latest().map(|value| value.reset_generation),
            scaffold: lifecycle.active,
            settled: restart.is_settled(),
            intake_reason: intake.reason.into(),
            matrix_hash: matrix_hash(matrix),
        });
    }
    Ok(rows)
}

fn summary(rows: &[Row]) -> Value {
    let fills: Vec<f32> = rows.iter().filter_map(|row| row.fill_pct).collect();
    json!({"min_fill": fills.iter().copied().fold(f32::INFINITY, f32::min),
        "max_fill": fills.iter().copied().fold(f32::NEG_INFINITY, f32::max),
        "last_fill": fills.last(), "high_fill_samples_ge_90": fills.iter().filter(|v| **v >= 90.0).count(),
        "recovery_steps": rows.iter().filter(|r| r.recovery).count(),
        "resets": rows.iter().filter(|r| r.reset).count(),
        "missing_rate_steps": rows.iter().filter(|r| r.rate.is_none()).count(),
        "drain_steps": rows.iter().filter(|r| r.drain > 0.0).count(),
        "max_drain": rows.iter().map(|r| r.drain).fold(0.0_f32, f32::max)})
}

fn collapsed_basis_probe(gpu: &Gpu, dim: usize) -> Result<Value> {
    let mut matrix = vec![0.0; dim * dim];
    matrix[0] = dim as f32;
    let mut rng = fastrand::Rng::with_seed(SEED);
    let mut fresh = (0..dim * K).map(|_| rng.f32() - 0.5).collect::<Vec<_>>();
    let _ = gs_orthonormalize_colmajor(&mut fresh, dim, K);
    let a = gpu.new_shared((matrix.len() * 4) as u64);
    let x = gpu.new_shared((fresh.len() * 4) as u64);
    let y = gpu.new_shared((fresh.len() * 4) as u64);
    gpu.write_f32(&a, &matrix);
    gpu.write_f32(&x, &fresh);
    let mut rank_one_spectrum = Vec::new();
    for _ in 0..5 {
        (rank_one_spectrum, _) = measure(gpu, &a, &x, &y, dim)?;
    }
    // Identity has known eigenvalues: this isolates basis loss from estimator history.
    reset_covariance_inplace(&mut matrix, dim);
    gpu.write_f32(&a, &matrix);
    let (retained_basis, _) = measure(gpu, &a, &x, &y, dim)?;
    gpu.write_f32(&x, &fresh);
    let (fresh_basis, _) = measure(gpu, &a, &x, &y, dim)?;
    ensure!(
        fresh_basis.iter().all(|v| (*v - 1.0).abs() < 1e-5),
        "fresh-basis identity oracle failed"
    );
    Ok(json!({"fixture": "rank_one_then_identity", "dim": dim,
        "expected_identity_eigenvalues": vec![1.0; K],
        "rank_one_eigenvalues": rank_one_spectrum,
        "retained_basis_eigenvalues": retained_basis,
        "fresh_basis_eigenvalues": fresh_basis,
        "scope": "measurement_basis_only_no_estimator_or_controller_retuning"}))
}

fn estimator_history_probe() -> Value {
    let mut retained = EigenFillEstimator::fixed_survival(K);
    let mut rank_one = [0.0; K];
    rank_one[0] = 512.0;
    for _ in 0..40 {
        retained.update_with_elapsed(&rank_one, Duration::from_millis(500));
    }
    let mut fresh = EigenFillEstimator::fixed_survival(K);
    let initial_ema = retained.snapshot_v1().ema_mean;
    let rows = (0..144)
        .map(|tick| {
            let elapsed = Duration::from_millis(2370);
            json!({"tick": tick, "time_ms": (tick + 1) * 2370,
            "retained_fill": retained.update_with_elapsed(&[1.0; K], elapsed) * 100.0,
            "fresh_fill": fresh.update_with_elapsed(&[1.0; K], elapsed) * 100.0,
            "retained_ema_mean": retained.snapshot_v1().ema_mean})
        })
        .collect::<Vec<_>>();
    json!({"fixture": "rank_one_history_then_constant_identity_spectrum",
        "initial_ema_mean": initial_ema, "rows": rows,
        "scope": "production_estimator_only_no_covariance_control_or_history_reset"})
}

fn main() -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(180);
    ensure!(
        std::env::args().len() == 1,
        "qualification accepts no paths, commands or endpoints"
    );
    let gpu = Gpu::new()?;
    let scenarios = [
        Scenario::Cold,
        Scenario::Restored,
        Scenario::LowRank,
        Scenario::SkippedRegulation,
        Scenario::InvalidObservation,
        Scenario::MatrixFault,
        Scenario::Restart,
        Scenario::Semantic,
    ];
    let mut results = Vec::new();
    for scenario in scenarios {
        for schedule in [
            Schedule::Nominal500,
            Schedule::Delayed2370,
            Schedule::MixedGaps,
        ] {
            ensure!(
                Instant::now() < deadline,
                "qualification overall time limit exceeded"
            );
            let observed = run(&gpu, 512, scenario, Timing::Observed, schedule, SEED)?;
            let nominal = run(&gpu, 512, scenario, Timing::Nominal, schedule, SEED)?;
            let changed_matrix_steps = observed
                .iter()
                .zip(&nominal)
                .filter(|(a, b)| a.matrix_hash != b.matrix_hash)
                .count();
            let changed_action_steps = observed
                .iter()
                .zip(&nominal)
                .filter(|(a, b)| a.mode != b.mode || a.drain != b.drain)
                .count();
            if schedule == Schedule::Nominal500 {
                ensure!(
                    observed == nominal,
                    "nominal-interval negative control differs: {scenario:?}"
                );
            }
            results.push(json!({"scenario": format!("{scenario:?}"), "schedule": format!("{schedule:?}"),
                "observed_summary": summary(&observed), "nominal_summary": summary(&nominal),
                "changed_matrix_steps": changed_matrix_steps, "changed_action_steps": changed_action_steps,
                "observed": observed, "nominal": nominal}));
        }
    }
    let extended = run(
        &gpu,
        512,
        Scenario::LowRankExtended,
        Timing::Observed,
        Schedule::Delayed2370,
        SEED,
    )?;
    let sources = [
        (
            "measurement_basis.rs",
            include_bytes!("../measurement_basis.rs").as_slice(),
        ),
        (
            "covariance_math.rs",
            include_bytes!("../covariance_math.rs").as_slice(),
        ),
        (
            "stable_covariance.rs",
            include_bytes!("../stable_covariance.rs").as_slice(),
        ),
        (
            "rescue_scaffold.rs",
            include_bytes!("../rescue_scaffold.rs").as_slice(),
        ),
        (
            "rescue_overfill.rs",
            include_bytes!("../rescue_overfill.rs").as_slice(),
        ),
        (
            "fill_timing.rs",
            include_bytes!("../fill_timing.rs").as_slice(),
        ),
        (
            "spectral/eigenfill.rs",
            include_bytes!("../spectral/eigenfill.rs").as_slice(),
        ),
        ("gpu.rs", include_bytes!("../gpu.rs").as_slice()),
        (
            "stable_core.rs",
            include_bytes!("../stable_core.rs").as_slice(),
        ),
        (
            "spectral.metal",
            include_bytes!("../../shaders/spectral.metal").as_slice(),
        ),
        ("Cargo.lock", include_bytes!("../../Cargo.lock").as_slice()),
        (
            "fill_coupled_qualification.rs",
            include_bytes!("fill_coupled_qualification.rs").as_slice(),
        ),
    ];
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema": "isolated_fill_coupling_qualification_v2", "dim": 512, "modes": K,
            "steps_per_run": STEPS, "seed": SEED, "backend": "production_metal_matvec_gs_rayleigh",
            "device": gpu.dev.name(), "architecture": std::env::consts::ARCH,
            "clock_contrast": "observed_intervals_vs_nominal_500ms_with_same_validity_policy",
            "scope": "production_structural_controller_covariance_measurement_feedback",
            "exclusions": ["live checkpoints", "ESN/router/input projection", "sensory admission application",
                "dynamic preferences", "full process restart", "subjective or deployment verdict"],
            "fixture": "synthetic_identity_scaffold_and_seeded_basis_no_live_state",
            "basis_reset_probe": collapsed_basis_probe(&gpu, 512)?,
            "estimator_history_probe": estimator_history_probe(),
            "extended_low_rank": {"schedule": "Delayed2370", "timing": "Observed",
                "steps": 144, "summary": summary(&extended), "rows": extended},
            "sources": sources.iter().map(|(path, bytes)| json!({"path": path, "sha256": hash_bytes(bytes)})).collect::<Vec<_>>(),
            "results": results,
        }))?
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_estimator_history_delays_but_does_not_permanently_lose_identity() {
        let probe = estimator_history_probe();
        let rows = probe["rows"].as_array().unwrap();
        assert!(rows[20]["retained_fill"].as_f64().unwrap() < 10.0);
        assert!(rows[20]["fresh_fill"].as_f64().unwrap() > 70.0);
        assert!(rows.last().unwrap()["retained_fill"].as_f64().unwrap() > 80.0);
    }

    #[test]
    fn repaired_basis_measures_rank_one_then_full_identity_without_inventing_rank() -> Result<()> {
        let probe = collapsed_basis_probe(&Gpu::new()?, 32)?;
        let retained = probe["retained_basis_eigenvalues"].as_array().unwrap();
        assert!(retained
            .iter()
            .all(|v| (v.as_f64().unwrap() - 1.0).abs() < 1e-5));
        let rank_one = probe["rank_one_eigenvalues"].as_array().unwrap();
        assert!((rank_one[0].as_f64().unwrap() - 32.0).abs() < 1e-5);
        assert!(rank_one[1..]
            .iter()
            .all(|v| v.as_f64().unwrap().abs() < 1e-5));
        Ok(())
    }

    #[test]
    fn deterministic_coupled_runs_and_nominal_negative_control() -> Result<()> {
        let gpu = Gpu::new()?;
        let first = run(
            &gpu,
            32,
            Scenario::Cold,
            Timing::Observed,
            Schedule::Nominal500,
            SEED,
        )?;
        assert_eq!(
            first,
            run(
                &gpu,
                32,
                Scenario::Cold,
                Timing::Observed,
                Schedule::Nominal500,
                SEED
            )?
        );
        assert_eq!(
            first,
            run(
                &gpu,
                32,
                Scenario::Cold,
                Timing::Nominal,
                Schedule::Nominal500,
                SEED
            )?
        );
        Ok(())
    }

    #[test]
    fn invalid_measurement_and_restart_cannot_reuse_a_rate() -> Result<()> {
        let gpu = Gpu::new()?;
        let invalid = run(
            &gpu,
            32,
            Scenario::InvalidObservation,
            Timing::Observed,
            Schedule::MixedGaps,
            SEED,
        )?;
        for row in &invalid[20..24] {
            assert!(row.rate.is_none());
        }
        for row in &invalid[20..23] {
            assert!(row.fill_pct.is_none());
        }
        let restart = run(
            &gpu,
            32,
            Scenario::Restart,
            Timing::Observed,
            Schedule::MixedGaps,
            SEED,
        )?;
        assert!(restart[20].rate.is_none());
        assert!(restart[20].control_fill_pct.is_none());
        Ok(())
    }

    #[test]
    fn internal_matrix_reset_invalidates_feedback_pair() -> Result<()> {
        let gpu = Gpu::new()?;
        let rows = run(
            &gpu,
            32,
            Scenario::MatrixFault,
            Timing::Observed,
            Schedule::MixedGaps,
            SEED,
        )?;
        assert!(rows[20].reset);
        assert!(rows[20].rate.is_none());
        Ok(())
    }

    #[test]
    fn skipped_input_and_internal_resets_are_reported_by_production_step() {
        for stage in [OverfillStage::Hold, OverfillStage::Discharge] {
            let mut matrix = vec![f32::NAN; 16];
            let mut pi = StabilityPiState::default();
            let mut restart = StableCoreRestartGate::new(0);
            let result = stable_covariance::step(
                &mut matrix,
                &[0.0; 4],
                &mut pi,
                &mut restart,
                StepInput {
                    dim: 4,
                    fill_pct: 80.0,
                    rate: Some(0.0),
                    stage,
                    guard: rescue_overfill::stage_guard(stage),
                    scaffold_active: false,
                    scaffold: None,
                    keep: 0.8,
                    pressure_bias: 0.0,
                    now_unix_ms: 0,
                },
            );
            assert!(result.covariance_reset);
            assert!(result.modified);
            for (i, value) in matrix.iter().enumerate() {
                assert_eq!(*value, if i / 4 == i % 4 { 1.0 } else { 0.0 });
            }
        }
        let mut matrix = scaffold(4).matrix;
        let before = matrix.clone();
        let result = stable_covariance::step(
            &mut matrix,
            &[f32::NAN; 4],
            &mut StabilityPiState::default(),
            &mut StableCoreRestartGate::new(0),
            StepInput {
                dim: 4,
                fill_pct: 68.0,
                rate: None,
                stage: OverfillStage::Hold,
                guard: rescue_overfill::stage_guard(OverfillStage::Hold),
                scaffold_active: false,
                scaffold: None,
                keep: 0.8,
                pressure_bias: 0.0,
                now_unix_ms: 0,
            },
        );
        assert!(result.rank1_skipped);
        assert!(!result.modified);
        assert!(!result.covariance_reset);
        assert_eq!(matrix, before);
    }

    #[test]
    fn delayed_coupling_remains_repeatable_for_another_seed() -> Result<()> {
        let gpu = Gpu::new()?;
        for scenario in [
            Scenario::LowRank,
            Scenario::Semantic,
            Scenario::SkippedRegulation,
        ] {
            let first = run(
                &gpu,
                32,
                scenario,
                Timing::Observed,
                Schedule::MixedGaps,
                SEED + 1,
            )?;
            assert_eq!(
                first,
                run(
                    &gpu,
                    32,
                    scenario,
                    Timing::Observed,
                    Schedule::MixedGaps,
                    SEED + 1
                )?
            );
        }
        Ok(())
    }
}
