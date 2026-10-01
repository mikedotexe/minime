//! One production structural-controller/covariance step. No clocks, I/O or GPU handles.

use crate::covariance_math::{
    decay_covariance_inplace_matrix, rank1_update_inplace_matrix, reset_covariance_inplace,
    CovarianceUpdateOutcome,
};
use crate::rescue_overfill::{OverfillGuard, OverfillStage};
use crate::rescue_scaffold::{
    self, RescueScaffold, StabilityPiOutput, StabilityPiState, StableCoreRestartGate,
};

mod settle_observation;
pub use settle_observation::RestartSettleObservationV1;

pub struct StepInput<'a> {
    pub dim: usize,
    pub fill_pct: f32,
    pub rate: Option<f32>,
    pub stage: OverfillStage,
    pub guard: OverfillGuard,
    pub scaffold_active: bool,
    pub scaffold: Option<&'a RescueScaffold>,
    pub keep: f32,
    pub pressure_bias: f32,
    pub now_unix_ms: u64,
}

#[derive(Debug)]
pub struct StepOutput {
    pub pi: StabilityPiOutput,
    pub mode: &'static str,
    pub modified: bool,
    pub rank1_skipped: bool,
    pub covariance_reset: bool,
    pub clear_input: bool,
    pub scaffold_blend: f32,
    pub pressure_bias: f32,
    pub pressure_live_delta: f32,
    pub pressure_drain_delta: f32,
    pub restart_active: bool,
    pub restart_applied: bool,
    pub restart_reason: &'static str,
    pub restart_floor: f32,
    pub live_weight: f32,
    pub drain_weight: f32,
}

pub fn step(
    matrix: &mut [f32],
    stimulus: &[f32],
    pi: &mut StabilityPiState,
    restart: &mut StableCoreRestartGate,
    input: StepInput<'_>,
) -> StepOutput {
    assert_eq!(matrix.len(), input.dim * input.dim);
    assert_eq!(stimulus.len(), input.dim);
    let was_escape_active = pi.low_fill_escape_active;
    let pi_output = pi.step(
        input.fill_pct,
        input.rate,
        input.stage,
        input.scaffold_active,
    );
    let mut out = StepOutput {
        pi: pi_output,
        mode: "free_rebuild",
        modified: false,
        rank1_skipped: false,
        covariance_reset: false,
        clear_input: false,
        scaffold_blend: 0.0,
        pressure_bias: 0.0,
        pressure_live_delta: 0.0,
        pressure_drain_delta: 0.0,
        restart_active: restart.active(),
        restart_applied: false,
        restart_reason: if restart.active() {
            "restart_gate_recovery_latch"
        } else {
            "inactive"
        },
        restart_floor: 0.0,
        live_weight: 0.0,
        drain_weight: 0.0,
    };
    let trace_target = input.dim as f32 * input.guard.trace_target_scale.unwrap_or(1.0);
    if !input.scaffold_active {
        if input.guard.decay_only {
            if !decay_covariance_inplace_matrix(matrix, input.dim, input.keep, trace_target) {
                reset_covariance_inplace(matrix, input.dim);
                out.covariance_reset = true;
            }
            out.modified = true;
        } else {
            apply_rank1(
                matrix,
                stimulus,
                input.dim,
                input.keep,
                trace_target,
                &mut out,
            );
        }
        return out;
    }
    let Some(scaffold) = input.scaffold else {
        return out;
    };
    if pi_output.reentry_active {
        out.live_weight = pi_output.reentry_live_weight;
        if apply_blend(matrix, scaffold, out.live_weight, 0.0) {
            out.modified = true;
            out.scaffold_blend = 1.0 - out.live_weight;
            out.mode = "scaffold_reentry";
        }
    } else if pi_output.low_fill_escape_active {
        if pi_output.recovery_impulse_active {
            out.mode = "free_rebuild_recovery_impulse";
            let keep =
                restart.recovery_impulse_keep(input.now_unix_ms, pi_output.recovery_impulse_keep);
            if keep < pi_output.recovery_impulse_keep {
                out.mode = "free_rebuild_restart_reset_impulse";
            }
            let reset = pi_output.recovery_identity_reset_requested
                || restart.should_request_recovery_identity_reset(input.fill_pct, true);
            if reset {
                restart.record_low_fill_reset(input.now_unix_ms, input.fill_pct);
                pi.recovery_identity_reset_done = true;
                reset_covariance_inplace(matrix, input.dim);
                out.covariance_reset = true;
                out.modified = true;
                out.clear_input = true;
            }
            apply_rank1(
                matrix,
                stimulus,
                input.dim,
                keep,
                input.dim as f32 * pi_output.recovery_impulse_trace_scale,
                &mut out,
            );
            let weight = rescue_scaffold::STABLE_CORE_RECOVERY_IMPULSE_SCAFFOLD_LIVE_WEIGHT;
            if apply_blend(matrix, scaffold, weight, 0.0) {
                out.modified = true;
                out.live_weight = weight;
                out.scaffold_blend = 1.0 - weight;
                out.mode = "scaffold_recovery_impulse";
            }
        } else {
            out.mode = "free_rebuild_low_fill_escape";
            if !was_escape_active && input.fill_pct < 35.0 {
                reset_covariance_inplace(matrix, input.dim);
                out.covariance_reset = true;
                out.modified = true;
                out.clear_input = true;
            }
            apply_rank1(
                matrix,
                stimulus,
                input.dim,
                input.keep,
                trace_target,
                &mut out,
            );
        }
    } else {
        out.pressure_bias = input.pressure_bias.clamp(-0.10, 0.10);
        out.pressure_live_delta = (-out.pressure_bias).max(0.0) * 0.50;
        out.pressure_drain_delta =
            out.pressure_bias.max(0.0) * 0.020 - (-out.pressure_bias).max(0.0) * 0.030;
        out.live_weight = (rescue_scaffold::scaffold_live_weight(input.stage)
            + out.pressure_live_delta)
            .clamp(0.0, 0.25);
        out.drain_weight =
            (pi_output.drain_weight + out.pressure_drain_delta).clamp(0.0, 1.0 - out.live_weight);
        if let Some((floor, reason)) = restart.drain_floor(input.fill_pct, input.rate) {
            out.restart_floor = floor;
            out.restart_reason = reason;
            if out.drain_weight < floor {
                out.drain_weight = floor.clamp(0.0, 1.0 - out.live_weight);
                out.restart_applied = true;
            }
        } else if out.restart_active {
            out.restart_reason = if restart
                .scaffold_activation_age_secs(input.now_unix_ms)
                .is_some_and(|age| age > rescue_scaffold::STABLE_CORE_RESTART_GATE_SECS)
            {
                "restart_gate_awaiting_settle_proof"
            } else {
                "restart_gate_monitoring"
            };
        }
        if out.drain_weight > 0.0 && input.fill_pct.is_finite() {
            restart.record_drain_applied(input.now_unix_ms, input.fill_pct);
        }
        if apply_blend(matrix, scaffold, out.live_weight, out.drain_weight) {
            out.modified = true;
            out.scaffold_blend = 1.0 - out.live_weight;
            out.mode = if out.restart_applied {
                "scaffold_restart_gate_drain"
            } else if out.drain_weight > 0.0 {
                "scaffold_hold_with_drain"
            } else {
                "scaffold_hold"
            };
        }
    }
    out
}

fn apply_rank1(
    matrix: &mut [f32],
    stimulus: &[f32],
    dim: usize,
    keep: f32,
    trace_target: f32,
    out: &mut StepOutput,
) {
    match rank1_update_inplace_matrix(matrix, stimulus, dim, keep, trace_target) {
        CovarianceUpdateOutcome::Skipped => out.rank1_skipped = true,
        CovarianceUpdateOutcome::Modified => out.modified = true,
        CovarianceUpdateOutcome::ResetRequired => {
            reset_covariance_inplace(matrix, dim);
            out.modified = true;
            out.covariance_reset = true;
        }
    }
}

fn apply_blend(matrix: &mut [f32], scaffold: &RescueScaffold, live: f32, drain: f32) -> bool {
    if let Some(blended) =
        rescue_scaffold::blend_toward_scaffold_with_drain(matrix, scaffold, live, drain)
    {
        matrix.copy_from_slice(&blended);
        true
    } else {
        false
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ScaffoldLifecycle {
    pub active: bool,
    pub retirement_ticks: u32,
    pub retirement_reason: &'static str,
}

#[derive(Clone, Copy)]
pub struct MeasurementInput {
    pub now_unix_ms: u64,
    pub fill_pct: f32,
    pub rate: Option<f32>,
    pub stage: OverfillStage,
    pub semantic_active: bool,
    pub scaffold_available: bool,
    pub live_audio_divisor: u32,
    pub live_video_divisor: u32,
    pub reentry_active: bool,
    pub recovery_active: bool,
    pub high_fill_drain_active: bool,
    pub applied_drain_weight: f32,
}

/// Post-measurement lifecycle; also used by the isolated coupled harness.
pub fn record_measurement(
    lifecycle: &mut ScaffoldLifecycle,
    restart: &mut StableCoreRestartGate,
    input: MeasurementInput,
) {
    restart.record_measured_fill(
        input.now_unix_ms,
        input.fill_pct,
        input.rate,
        input.stage,
        input.semantic_active,
        lifecycle.active,
        input.reentry_active,
        input.recovery_active,
    );
    record_scaffold_measurement(lifecycle, restart, input);
}

/// Scaffold lifecycle after the restart gate has consumed this measurement.
/// Kept separate for isolated policy comparisons; production uses `record_measurement`.
pub fn record_scaffold_measurement(
    lifecycle: &mut ScaffoldLifecycle,
    restart: &mut StableCoreRestartGate,
    input: MeasurementInput,
) {
    let mut retired_this_tick = false;
    if lifecycle.active {
        let candidate = rescue_scaffold::stable_core_scaffold_retirement_candidate_reason(
            restart.is_settled(),
            input.fill_pct,
            input.rate,
            input.stage,
            input.semantic_active,
            lifecycle.active,
            input.reentry_active,
            input.recovery_active,
            input.high_fill_drain_active,
            input.applied_drain_weight,
        );
        if let Some(reason) = candidate {
            lifecycle.retirement_ticks = lifecycle.retirement_ticks.saturating_add(1);
            lifecycle.retirement_reason = reason;
            if lifecycle.retirement_ticks
                >= rescue_scaffold::STABLE_CORE_SCAFFOLD_RETIRE_REQUIRED_TICKS
            {
                lifecycle.active = false;
                retired_this_tick = true;
                lifecycle.retirement_ticks = 0;
                lifecycle.retirement_reason = "retired_after_restart_gate_settle";
            }
        } else {
            lifecycle.retirement_ticks = 0;
            lifecycle.retirement_reason =
                rescue_scaffold::stable_core_scaffold_retirement_block_reason(
                    restart.is_settled(),
                    input.fill_pct,
                    input.rate,
                    input.semantic_active,
                    lifecycle.active,
                    input.reentry_active,
                    input.recovery_active,
                    input.high_fill_drain_active,
                    input.applied_drain_weight,
                );
        }
    } else {
        lifecycle.retirement_ticks = 0;
        if lifecycle.retirement_reason != "retired_after_restart_gate_settle" {
            lifecycle.retirement_reason = "scaffold_inactive";
        }
    }
    if lifecycle.active {
        restart.mark_scaffold_active();
    } else if input.scaffold_available && !retired_this_tick {
        let activation = restart.evaluate_activation(
            input.stage,
            input.fill_pct,
            input.rate,
            input.semantic_active,
            input.live_audio_divisor,
            input.live_video_divisor,
        );
        if activation.activate {
            lifecycle.active = true;
            restart.record_scaffold_activated(input.now_unix_ms, input.fill_pct, activation.reason);
        }
    } else {
        restart.mark_scaffold_unavailable();
    }
}
