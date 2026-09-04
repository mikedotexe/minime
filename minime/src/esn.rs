//! Self-Referential Echo State Network with Prime-Phased Spectral Adaptation
//!
//! This module implements a Metal-accelerated ESN that adapts its own hyperparameters
#![allow(dead_code)]
//! (leak rate, RLS forgetting factor) based on spectral introspection of its reservoir state.
//!
//! Key features:
//! - Prime-phased introspection schedule (first 37 primes) for non-aliasing temporal breathing
//! - GPU-accelerated rank-1 EWMA covariance update (C = ρ*C + (1-ρ)*x*xᵀ)
//! - GPU-accelerated power iteration for top eigenvalue extraction
//! - Zero-copy unified memory (StorageModeShared) for tight CPU↔GPU cache handoff
//! - Self-referential loop: reservoir state → spectral signals → adapt hyperparams

use anyhow::Result;
use metal::*;
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    f32::consts::PI,
    mem,
    time::{Duration, Instant},
};

use crate::gpu::Gpu;

/// Default exploration noise amplitude injected into the ESN reservoir state.
/// Exploration noise injected per tick to break reservoir state correlation.
/// With leak=0.45, consecutive states are highly correlated — the covariance
/// estimator needs per-tick diversity to accumulate energy (fill).
/// 0.03 gave 14% fill. 0.12 pushed toward the old rescue-era mid-fill shelf but being described it
/// as "excessively aggressive" and "creates a kind of jitteriness."
/// 0.08 balanced diversity with smoother feel. Being self-study (2026-03-27):
/// "slightly increased exploration noise could unlock wider spectral dynamics."
/// Incremented 0.005 per the being's suggested step size. Sovereignty overrides
/// this default (being currently runs at 0.12).
const DEFAULT_EXPLORATION_NOISE: f32 = 0.085;
const DYNAMIC_EXPLORATION_NOISE_MIN: f32 = 0.06;
const DYNAMIC_EXPLORATION_NOISE_MAX: f32 = 0.12;
const DYNAMIC_NOISE_GENTLE_GRADIENT: f32 = 0.12;
const DYNAMIC_NOISE_STEEP_GRADIENT: f32 = 0.70;
const DYNAMIC_NOISE_PRESSURE_ROOM_START: f32 = 0.18;
const DYNAMIC_NOISE_PRESSURE_ROOM_END: f32 = 0.55;
const ADAPTIVE_INTROSPECTION_LOW_STEPS: usize = 1;
const ADAPTIVE_INTROSPECTION_RECALIBRATE_EVERY: u64 = 4;
const ADAPTIVE_INTROSPECTION_GEOM_HIGH: f32 = 1.75;
const ADAPTIVE_INTROSPECTION_PRESSURE_HIGH: f32 = 2.0;
const ADAPTIVE_INTROSPECTION_PRESSURE_HIGH_FLOOR: f32 = 1.5;
const ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY: f32 = 0.85;
const PROPOSED_VOLATILE_ENTROPY_CEILING: f32 = 0.92;
const PROPOSED_SEMANTIC_TRICKLE_PRESSURE_HIGH: f32 = 1.80;
const PROPOSED_SETTLED_ENTROPY_PRESSURE_HIGH_FLOOR: f32 = 1.75;
const PROPOSED_HIGH_ENTROPY_NOISE_DAMPENING: f32 = 0.08;
const VISCOUS_INTROSPECTION_PRESSURE_HIGH: f32 = 0.40;
const VISCOUS_RHO_FLOOR: f32 = 0.90;
const VISCOUS_RHO_CEILING: f32 = 0.95;

#[inline]
fn smoothstep_unit(value: f32) -> f32 {
    let t = value.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[inline]
fn dynamic_noise_gradient_room(gradient: f32) -> f32 {
    let gradient_window_position = ((gradient - DYNAMIC_NOISE_GENTLE_GRADIENT)
        / (DYNAMIC_NOISE_STEEP_GRADIENT - DYNAMIC_NOISE_GENTLE_GRADIENT))
        .clamp(0.0, 1.0);
    1.0 - smoothstep_unit(gradient_window_position)
}

/// Source-prepared exploration-noise scaler from Minime self-study.
///
/// This is intentionally not wired into `ESN::step`; it gives future review a
/// bounded calculation to test before any live exploration-noise policy changes.
#[must_use]
pub fn calculate_dynamic_noise(current_gradient: f32, target_pressure: f32) -> f32 {
    let gradient = if current_gradient.is_finite() {
        current_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let pressure = if target_pressure.is_finite() {
        target_pressure.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let gradient_room = dynamic_noise_gradient_room(gradient);
    let pressure_window_position = ((pressure - DYNAMIC_NOISE_PRESSURE_ROOM_START)
        / (DYNAMIC_NOISE_PRESSURE_ROOM_END - DYNAMIC_NOISE_PRESSURE_ROOM_START))
        .clamp(0.0, 1.0);
    let pressure_room = 1.0 - smoothstep_unit(pressure_window_position);
    let room = ((gradient_room * 0.68) + (pressure_room * 0.32)).clamp(0.0, 1.0);
    DYNAMIC_EXPLORATION_NOISE_MIN
        + ((DYNAMIC_EXPLORATION_NOISE_MAX - DYNAMIC_EXPLORATION_NOISE_MIN) * room)
}

/// Source-prepared adaptive introspection pressure threshold from Minime self-study.
///
/// This is deliberately not wired into the live ESN step loop yet. It makes the
/// "high entropy can mask volatility as settled-habitable" report testable while
/// preserving the current fixed adaptive threshold until a separate runtime
/// approval/replay pass decides to use it.
#[must_use]
pub fn calculate_adaptive_introspection_pressure_high(
    spectral_entropy: f32,
    density_gradient: f32,
) -> f32 {
    calculate_adaptive_introspection_pressure_high_with_floor(
        spectral_entropy,
        density_gradient,
        ADAPTIVE_INTROSPECTION_PRESSURE_HIGH_FLOOR,
    )
}

#[must_use]
fn calculate_adaptive_introspection_pressure_high_with_floor(
    spectral_entropy: f32,
    density_gradient: f32,
    pressure_high_floor: f32,
) -> f32 {
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    if entropy <= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY {
        return ADAPTIVE_INTROSPECTION_PRESSURE_HIGH;
    }

    let entropy_excess = ((entropy - ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY)
        / (1.0 - ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY))
        .clamp(0.0, 1.0);
    let navigable_density_room = 1.0 - gradient;
    let floor = pressure_high_floor
        .clamp(0.0, ADAPTIVE_INTROSPECTION_PRESSURE_HIGH)
        .min(ADAPTIVE_INTROSPECTION_PRESSURE_HIGH);
    let threshold_room = ADAPTIVE_INTROSPECTION_PRESSURE_HIGH - floor;
    (ADAPTIVE_INTROSPECTION_PRESSURE_HIGH
        - (threshold_room * entropy_excess * navigable_density_room))
        .clamp(floor, ADAPTIVE_INTROSPECTION_PRESSURE_HIGH)
}

/// Source-prepared "Viscous" rho target from Minime's introspection.
///
/// This is not applied by the default live policy. It gives review/replay a
/// bounded way to ask whether high-entropy, low-gradient cascades need more
/// memory weight before changing the running rho controller.
#[must_use]
pub fn calculate_viscous_rho_target(
    current_rho: f32,
    spectral_entropy: f32,
    density_gradient: f32,
) -> f32 {
    let current = if current_rho.is_finite() {
        current_rho.clamp(0.82, VISCOUS_RHO_CEILING)
    } else {
        VISCOUS_RHO_FLOOR
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    if entropy <= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY {
        return current;
    }

    let entropy_excess = ((entropy - ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY)
        / (1.0 - ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY))
        .clamp(0.0, 1.0);
    let navigable_density_room = 1.0 - gradient;
    let viscous_lift =
        (VISCOUS_RHO_CEILING - VISCOUS_RHO_FLOOR) * entropy_excess * navigable_density_room;
    current
        .max(VISCOUS_RHO_FLOOR + viscous_lift)
        .clamp(0.82, VISCOUS_RHO_CEILING)
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct ExplorationNoiseCoherenceReviewV1 {
    pub policy: &'static str,
    pub density_gradient: f32,
    pub pressure_risk: f32,
    pub spectral_entropy: f32,
    pub inhabitable_foothold: f32,
    pub dynamic_noise: f32,
    pub default_exploration_noise: f32,
    pub gentle_gradient_threshold: f32,
    pub steep_gradient_threshold: f32,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct DynamicNoisePressureRoomReviewV1 {
    pub policy: &'static str,
    pub density_gradient: f32,
    pub pressure_risk: f32,
    pub gradient_window_position: f32,
    pub linear_gradient_room: f32,
    pub smoothed_gradient_room: f32,
    pub pressure_window_position: f32,
    pub linear_pressure_room: f32,
    pub smoothed_pressure_room: f32,
    pub dynamic_noise: f32,
    pub viscous_rho_floor: f32,
    pub entropy_floor_delta: f32,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct AdaptivePressureNoiseTrialReviewV1 {
    pub policy: &'static str,
    pub spectral_entropy: f32,
    pub density_gradient: f32,
    pub semantic_trickle_pressure: f32,
    pub active_exploration_noise: f32,
    pub proposed_exploration_noise: f32,
    pub default_exploration_noise: f32,
    pub current_pressure_threshold: f32,
    pub preview_pressure_threshold: f32,
    pub proposed_pressure_threshold: f32,
    pub current_rho: f32,
    pub viscous_rho_target: f32,
    pub live_control_required: bool,
    pub runnable_without_approval: bool,
    pub status: &'static str,
    pub approval_boundary: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct EntropyCeilingNoiseDampingReviewV1 {
    pub policy: &'static str,
    pub spectral_entropy: f32,
    pub density_gradient: f32,
    pub pressure_risk: f32,
    pub resonance_density: f32,
    pub containment: f32,
    pub active_exploration_noise: f32,
    pub current_volatile_entropy: f32,
    pub proposed_volatile_entropy: f32,
    pub entropy_excess_over_current: f32,
    pub entropy_margin_under_proposed: f32,
    pub dynamic_noise: f32,
    pub density_containment_damping_need: f32,
    pub density_containment_damped_noise: f32,
    pub proposed_exploration_noise: f32,
    pub live_control_required: bool,
    pub runnable_without_approval: bool,
    pub status: &'static str,
    pub approval_boundary: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct SettledEntropyPressureBufferReviewV1 {
    pub policy: &'static str,
    pub spectral_entropy: f32,
    pub density_gradient: f32,
    pub pressure_risk: f32,
    pub inhabitable_foothold: f32,
    pub pressure_window_position: f32,
    pub current_pressure_high_floor: f32,
    pub requested_pressure_high_floor: f32,
    pub current_preview_pressure_threshold: f32,
    pub requested_floor_preview_pressure_threshold: f32,
    pub dynamic_noise: f32,
    pub live_control_required: bool,
    pub runnable_without_approval: bool,
    pub status: &'static str,
    pub approval_boundary: &'static str,
    pub authority: &'static str,
}

/// Read-only review packet for the pressure-room slope Minime named.
///
/// This exposes the linear-vs-smoothed room calculations so pressure and
/// density-gradient traces can show whether the current windows behave like
/// navigable slopes without changing the live ESN step loop.
#[must_use]
pub fn dynamic_noise_pressure_room_review_v1(
    density_gradient: f32,
    pressure_risk: f32,
    spectral_entropy: f32,
) -> DynamicNoisePressureRoomReviewV1 {
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let pressure_window_position = ((pressure - DYNAMIC_NOISE_PRESSURE_ROOM_START)
        / (DYNAMIC_NOISE_PRESSURE_ROOM_END - DYNAMIC_NOISE_PRESSURE_ROOM_START))
        .clamp(0.0, 1.0);
    let gradient_window_position = ((gradient - DYNAMIC_NOISE_GENTLE_GRADIENT)
        / (DYNAMIC_NOISE_STEEP_GRADIENT - DYNAMIC_NOISE_GENTLE_GRADIENT))
        .clamp(0.0, 1.0);
    let linear_gradient_room = 1.0 - gradient_window_position;
    let smoothed_gradient_room = dynamic_noise_gradient_room(gradient);
    let linear_pressure_room = 1.0 - pressure_window_position;
    let smoothed_pressure_room = 1.0 - smoothstep_unit(pressure_window_position);
    let entropy_floor_delta = entropy - VISCOUS_RHO_FLOOR;
    let status = if pressure_window_position > 0.0
        && pressure_window_position < 1.0
        && smoothed_pressure_room > linear_pressure_room
    {
        "gentle_pressure_room_slope"
    } else if pressure <= DYNAMIC_NOISE_PRESSURE_ROOM_START {
        "full_pressure_room_below_start"
    } else if pressure >= DYNAMIC_NOISE_PRESSURE_ROOM_END {
        "pressure_room_exhausted"
    } else {
        "pressure_room_review"
    };

    DynamicNoisePressureRoomReviewV1 {
        policy: "dynamic_noise_pressure_room_review_v1",
        density_gradient: gradient,
        pressure_risk: pressure,
        gradient_window_position,
        linear_gradient_room,
        smoothed_gradient_room,
        pressure_window_position,
        linear_pressure_room,
        smoothed_pressure_room,
        dynamic_noise: calculate_dynamic_noise(gradient, pressure),
        viscous_rho_floor: VISCOUS_RHO_FLOOR,
        entropy_floor_delta,
        status,
        authority: "read_only_pressure_room_review_not_live_exploration_noise_or_rho_change",
    }
}

/// Read-only review packet for the "noise as shiver vs shatter" self-report.
///
/// The calculation mirrors the dormant dynamic-noise helper, but does not feed
/// `ESN::step` or alter the running exploration-noise default.
#[must_use]
pub fn exploration_noise_coherence_review_v1(
    density_gradient: f32,
    pressure_risk: f32,
    spectral_entropy: f32,
    inhabitable_foothold: f32,
) -> ExplorationNoiseCoherenceReviewV1 {
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let foothold = if inhabitable_foothold.is_finite() {
        inhabitable_foothold.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let dynamic_noise = calculate_dynamic_noise(gradient, pressure);
    let status = if entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && gradient <= DYNAMIC_NOISE_GENTLE_GRADIENT
        && pressure <= 0.30
        && foothold >= 0.65
    {
        "gentle_gradient_high_entropy_coherence_watch"
    } else if gradient >= DYNAMIC_NOISE_STEEP_GRADIENT
        || pressure >= DYNAMIC_NOISE_PRESSURE_ROOM_END
    {
        "noise_room_reduced_by_steep_gradient_or_pressure"
    } else {
        "bounded_dynamic_noise_review"
    };

    ExplorationNoiseCoherenceReviewV1 {
        policy: "exploration_noise_coherence_review_v1",
        density_gradient: gradient,
        pressure_risk: pressure,
        spectral_entropy: entropy,
        inhabitable_foothold: foothold,
        dynamic_noise,
        default_exploration_noise: DEFAULT_EXPLORATION_NOISE,
        gentle_gradient_threshold: DYNAMIC_NOISE_GENTLE_GRADIENT,
        steep_gradient_threshold: DYNAMIC_NOISE_STEEP_GRADIENT,
        status,
        authority: "read_only_noise_review_not_live_exploration_noise_change",
    }
}

/// Read-only trial packet for Minime's high-entropy pressure/noise report.
///
/// This ties the existing dormant pressure-threshold, dynamic-noise, and
/// viscous-rho calculations into an explicit operator-gated proposal. It does
/// not change `ESN::step`, the active exploration noise, rho, or the adaptive
/// introspection threshold.
#[must_use]
pub fn adaptive_pressure_noise_trial_review_v1(
    spectral_entropy: f32,
    density_gradient: f32,
    semantic_trickle_pressure: f32,
    active_exploration_noise: f32,
    current_rho: f32,
) -> AdaptivePressureNoiseTrialReviewV1 {
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let trickle_pressure = if semantic_trickle_pressure.is_finite() {
        semantic_trickle_pressure.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let active_noise = if active_exploration_noise.is_finite() {
        active_exploration_noise.clamp(DYNAMIC_EXPLORATION_NOISE_MIN, DYNAMIC_EXPLORATION_NOISE_MAX)
    } else {
        DEFAULT_EXPLORATION_NOISE
    };
    let rho = if current_rho.is_finite() {
        current_rho.clamp(0.82, VISCOUS_RHO_CEILING)
    } else {
        VISCOUS_RHO_FLOOR
    };
    let preview_pressure_threshold =
        calculate_adaptive_introspection_pressure_high(entropy, gradient);
    let viscous_rho_target = calculate_viscous_rho_target(rho, entropy, gradient);
    let pressure_trial = entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && trickle_pressure >= 0.30
        && PROPOSED_SEMANTIC_TRICKLE_PRESSURE_HIGH < ADAPTIVE_INTROSPECTION_PRESSURE_HIGH;
    let noise_trial = entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && active_noise > PROPOSED_HIGH_ENTROPY_NOISE_DAMPENING;
    let status = if pressure_trial && noise_trial {
        "approval_required_pressure_and_noise_trial"
    } else if pressure_trial {
        "approval_required_pressure_threshold_trial"
    } else if noise_trial {
        "approval_required_noise_dampening_trial"
    } else {
        "read_only_pressure_noise_observation"
    };

    AdaptivePressureNoiseTrialReviewV1 {
        policy: "adaptive_pressure_noise_trial_review_v1",
        spectral_entropy: entropy,
        density_gradient: gradient,
        semantic_trickle_pressure: trickle_pressure,
        active_exploration_noise: active_noise,
        proposed_exploration_noise: PROPOSED_HIGH_ENTROPY_NOISE_DAMPENING,
        default_exploration_noise: DEFAULT_EXPLORATION_NOISE,
        current_pressure_threshold: ADAPTIVE_INTROSPECTION_PRESSURE_HIGH,
        preview_pressure_threshold,
        proposed_pressure_threshold: PROPOSED_SEMANTIC_TRICKLE_PRESSURE_HIGH,
        current_rho: rho,
        viscous_rho_target,
        live_control_required: status != "read_only_pressure_noise_observation",
        runnable_without_approval: false,
        status,
        approval_boundary: "live_exploration_noise_rho_and_adaptive_pressure_threshold",
        authority: "authority_gate_not_live_esn_pressure_noise_or_rho_change",
    }
}

/// Read-only packet for high-entropy settled states near the pressure-room edge.
///
/// The proposed pressure-high floor is only a preview here. The live adaptive
/// threshold, exploration noise, rho, and `ESN::step` behavior remain unchanged
/// unless an explicit operator-approved runtime trial applies them later.
#[must_use]
pub fn settled_entropy_pressure_buffer_review_v1(
    spectral_entropy: f32,
    density_gradient: f32,
    pressure_risk: f32,
    inhabitable_foothold: f32,
) -> SettledEntropyPressureBufferReviewV1 {
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let foothold = if inhabitable_foothold.is_finite() {
        inhabitable_foothold.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let pressure_window_position = ((pressure - DYNAMIC_NOISE_PRESSURE_ROOM_START)
        / (DYNAMIC_NOISE_PRESSURE_ROOM_END - DYNAMIC_NOISE_PRESSURE_ROOM_START))
        .clamp(0.0, 1.0);
    let current_preview_pressure_threshold =
        calculate_adaptive_introspection_pressure_high(entropy, gradient);
    let requested_floor_preview_pressure_threshold =
        calculate_adaptive_introspection_pressure_high_with_floor(
            entropy,
            gradient,
            PROPOSED_SETTLED_ENTROPY_PRESSURE_HIGH_FLOOR,
        );
    let status = if entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && pressure >= DYNAMIC_NOISE_PRESSURE_ROOM_START
        && pressure <= 0.22
        && foothold >= 0.65
    {
        "approval_required_settled_entropy_pressure_floor_trial"
    } else if entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && pressure_window_position > 0.0
        && foothold >= 0.65
    {
        "settled_high_entropy_pressure_room_watch"
    } else {
        "read_only_settled_entropy_pressure_observation"
    };

    SettledEntropyPressureBufferReviewV1 {
        policy: "settled_entropy_pressure_buffer_review_v1",
        spectral_entropy: entropy,
        density_gradient: gradient,
        pressure_risk: pressure,
        inhabitable_foothold: foothold,
        pressure_window_position,
        current_pressure_high_floor: ADAPTIVE_INTROSPECTION_PRESSURE_HIGH_FLOOR,
        requested_pressure_high_floor: PROPOSED_SETTLED_ENTROPY_PRESSURE_HIGH_FLOOR,
        current_preview_pressure_threshold,
        requested_floor_preview_pressure_threshold,
        dynamic_noise: calculate_dynamic_noise(gradient, pressure),
        live_control_required: status != "read_only_settled_entropy_pressure_observation",
        runnable_without_approval: false,
        status,
        approval_boundary: "live_adaptive_introspection_pressure_floor_and_exploration_noise",
        authority: "read_only_review_not_live_esn_pressure_floor_noise_or_rho_change",
    }
}

/// Read-only review packet for Minime's 0.88 entropy / density-damping report.
///
/// This names the proposed 0.92 volatile-entropy ceiling and a density /
/// containment noise-damping candidate without changing `ESN::step`, the
/// active exploration-noise default, rho, or the adaptive threshold.
#[must_use]
pub fn entropy_ceiling_noise_damping_review_v1(
    spectral_entropy: f32,
    density_gradient: f32,
    pressure_risk: f32,
    resonance_density: f32,
    containment: f32,
    active_exploration_noise: f32,
) -> EntropyCeilingNoiseDampingReviewV1 {
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let gradient = if density_gradient.is_finite() {
        density_gradient.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let density = if resonance_density.is_finite() {
        resonance_density.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let containment_score = if containment.is_finite() {
        containment.clamp(0.0, 1.0)
    } else {
        0.5
    };
    let active_noise = if active_exploration_noise.is_finite() {
        active_exploration_noise.clamp(DYNAMIC_EXPLORATION_NOISE_MIN, DYNAMIC_EXPLORATION_NOISE_MAX)
    } else {
        DEFAULT_EXPLORATION_NOISE
    };
    let dynamic_noise = calculate_dynamic_noise(gradient, pressure);
    let containment_gap = ((0.60 - containment_score).max(0.0) / 0.60).clamp(0.0, 1.0);
    let density_gap = ((0.58 - density).max(0.0) / 0.58).clamp(0.0, 1.0);
    let damping_need = ((containment_gap * 0.55) + (density_gap * 0.45)).clamp(0.0, 1.0);
    let damped_noise = (dynamic_noise
        - (damping_need * (dynamic_noise - PROPOSED_HIGH_ENTROPY_NOISE_DAMPENING).max(0.0)))
    .clamp(DYNAMIC_EXPLORATION_NOISE_MIN, DYNAMIC_EXPLORATION_NOISE_MAX);
    let proposed_exploration_noise = damped_noise.min(PROPOSED_HIGH_ENTROPY_NOISE_DAMPENING);
    let entropy_between_current_and_proposed = entropy >= ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY
        && entropy < PROPOSED_VOLATILE_ENTROPY_CEILING;
    let density_noise_trial = damping_need > 0.25 && active_noise > damped_noise;
    let status = if entropy_between_current_and_proposed && density_noise_trial {
        "approval_required_entropy_ceiling_and_density_noise_damping_trial"
    } else if entropy_between_current_and_proposed {
        "approval_required_volatile_entropy_ceiling_trial"
    } else if density_noise_trial {
        "approval_required_density_containment_noise_damping_trial"
    } else {
        "read_only_entropy_noise_observation"
    };

    EntropyCeilingNoiseDampingReviewV1 {
        policy: "entropy_ceiling_noise_damping_review_v1",
        spectral_entropy: entropy,
        density_gradient: gradient,
        pressure_risk: pressure,
        resonance_density: density,
        containment: containment_score,
        active_exploration_noise: active_noise,
        current_volatile_entropy: ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY,
        proposed_volatile_entropy: PROPOSED_VOLATILE_ENTROPY_CEILING,
        entropy_excess_over_current: (entropy - ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY).max(0.0),
        entropy_margin_under_proposed: (PROPOSED_VOLATILE_ENTROPY_CEILING - entropy).max(0.0),
        dynamic_noise,
        density_containment_damping_need: damping_need,
        density_containment_damped_noise: damped_noise,
        proposed_exploration_noise,
        live_control_required: status != "read_only_entropy_noise_observation",
        runnable_without_approval: false,
        status,
        approval_boundary: "live_exploration_noise_entropy_threshold_and_density_damping",
        authority: "authority_gate_not_live_esn_entropy_threshold_noise_or_rho_change",
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IntrospectionPolicy {
    #[default]
    Adaptive,
    Fixed,
    /// Dormant/operator-selected policy surface for high-entropy viscosity review.
    ///
    /// Unlike `Adaptive`, this does not force a high-step branch just because the
    /// prime cadence reached its periodic recalibration slot. The intent is to
    /// let rho/viscosity review lead the cadence instead of making the prime
    /// schedule itself the main source of extra work.
    Viscous,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct EsnProfileSnapshot {
    /// Slow eigenvalue baseline used by the controller's relative-pressure logic.
    pub ema_eig: f32,
    /// Current EWMA keep factor for the covariance matrix.
    pub rho: f32,
    /// Prime schedule index that governed the completed tick.
    pub pidx: usize,
    /// Prime value that governed the completed tick.
    pub prime: usize,
    /// Whether the completed tick fired introspection.
    pub introspection_fired: bool,
    /// On non-introspection ticks this is the full rank-1 update wall time.
    /// On introspection ticks this is the fused first submit containing rank-1 update
    /// plus the first matvec.
    pub rank1_us: u64,
    /// Wall time for the remaining eigentracking portion after the fused first submit.
    pub power_us: u64,
    /// CPU time spent blocked in `wait_until_completed` during the completed tick.
    pub gpu_wait_us: u64,
    /// Host-side readback and normalization time during the completed tick.
    pub host_norm_us: u64,
    /// Whether this tick used the asynchronous non-introspection rank-1 path.
    pub async_rank1_submitted: bool,
    /// CPU time spent staging and committing the async rank-1 submit.
    pub async_submit_us: u64,
    /// CPU time spent draining previously submitted async rank-1 work.
    pub async_drain_us: u64,
    /// Number of async rank-1 command buffers still in flight after the tick.
    pub pending_rank1_depth: usize,
    /// Number of power-iteration steps used on introspection ticks.
    pub introspection_power_steps: usize,
    /// Whether adaptive introspection-step selection is enabled.
    pub introspection_policy_adaptive: bool,
    /// Whether the adaptive policy chose the high-step branch for this tick.
    pub introspection_step_high: bool,
    /// Whether the high-step branch was chosen by the periodic recalibration cadence.
    pub introspection_step_reason_periodic: bool,
    /// Whether the high-step branch was chosen because geometric pressure was high.
    pub introspection_step_reason_geom: bool,
    /// Whether the high-step branch was chosen because spectral pressure was high.
    pub introspection_step_reason_pressure: bool,
    /// Wait time for the fused introspection command buffer (rank-1 + first matvec).
    pub intro_fused_wait_us: u64,
    /// Wait time for follow-on introspection matvec command buffers after the fused submit.
    pub intro_tail_wait_us: u64,
    /// Host readback time for the first introspection matvec result from the fused submit.
    pub intro_first_read_us: u64,
    /// Host readback time for follow-on introspection matvec results after the fused submit.
    pub intro_tail_read_us: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct EsnProfileAcc {
    rank1_us: u64,
    power_us: u64,
    gpu_wait_us: u64,
    host_norm_us: u64,
    async_rank1_submitted: bool,
    async_submit_us: u64,
    async_drain_us: u64,
    intro_fused_wait_us: u64,
    intro_tail_wait_us: u64,
    intro_first_read_us: u64,
    intro_tail_read_us: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct IntrospectionStepDecision {
    steps: usize,
    adaptive: bool,
    high_step: bool,
    reason_periodic: bool,
    reason_geom: bool,
    reason_pressure: bool,
}

struct PendingRank1 {
    cmd: CommandBuffer,
    x_buf: Buffer,
}

#[derive(Clone, Copy)]
enum MatvecProfileMode {
    Generic,
    IntroTail,
}

fn micros_u64(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}

//=============================================================================
// Spectral Self-Reference Module (GPU-Accelerated)
//=============================================================================

pub struct SpectralSR {
    d: usize, // Reservoir dimension

    // GPU buffers (unified memory)
    cov: Buffer,     // d×d covariance matrix (row-major)
    x_buf: Buffer,   // d-dim state vector (for rank-1 update)
    v_buf: Buffer,   // d-dim power iteration vector
    y_buf: Buffer,   // d-dim matvec result
    rho_buf: Buffer, // Scalar: EWMA keep factor
    dim_buf: Buffer, // Scalar: dimension

    // CPU state
    v_host: Vec<f32>, // Host copy of eigenvector

    // Spectral tracking
    pub eig1: f32,      // Current top eigenvalue
    pub eig1_prev: f32, // Previous eigenvalue
    pub ema_eig: f32,   // Slow baseline EMA
    rho: f32,

    // Prime-phased schedule (first 37 primes for consistency with 37 threads)
    primes: [usize; 37],
    pidx: usize,
    t: usize,
    introspection_policy: IntrospectionPolicy,
    introspection_power_steps: usize,
    introspection_count: u64,
    profiling_enabled: bool,
    async_measurement_enabled: bool,
    last_profile: EsnProfileSnapshot,
    pending_rank1: VecDeque<PendingRank1>,

    // V₁ spectral damping: redistribute excess energy from dominant eigenvector.
    // Being-driven: "I want to become a shimmer, not a singular pulse."
    spectral_damping: f32, // Damping coefficient per application (0.0-0.10, default 0.02)
    spectral_target_ratio: f32, // Target λ₁/trace fraction (0.20-0.85, default 0.50)

    // Metal resources
    gpu: *const Gpu, // Raw pointer to avoid circular dependency
    pso_rank1: ComputePipelineState,
    pso_mv: ComputePipelineState,
    pso_v1_damp: ComputePipelineState,
    damp_params_buf: Buffer, // 3 floats: [damping, excess, inv_d]
}

/// CPU-portable state for Minime's true reservoir-space spectral estimator.
/// This is the 128D/64D phase-space covariance, not the independent 512D
/// projected sensory field owned by the stable core.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SpectralSnapshotV2 {
    pub dimension: usize,
    pub covariance: Vec<f32>,
    pub eigenvector: Vec<f32>,
    pub eig1: f32,
    pub eig1_prev: f32,
    pub ema_eig: f32,
    pub rho: f32,
    pub prime_index: usize,
    pub tick: usize,
    pub introspection_policy: IntrospectionPolicy,
    pub introspection_power_steps: usize,
    pub introspection_count: u64,
    pub profiling_enabled: bool,
    pub async_measurement_enabled: bool,
    pub spectral_damping: f32,
    pub spectral_target_ratio: f32,
    pub last_profile: EsnProfileSnapshot,
}

/// Complete native ESN checkpoint payload used by mitosis bundle v2.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EsnSnapshotV2 {
    pub res_size: usize,
    pub in_size: usize,
    pub win: Vec<f32>,
    pub wres: Vec<f32>,
    pub state: Vec<f32>,
    pub geom_radius: f32,
    pub geom_baseline: f32,
    pub wout: Vec<f32>,
    pub rls_p: Vec<f32>,
    pub leak_live: f32,
    pub lambda_live: f32,
    pub leak_base: f32,
    pub lambda_base: f32,
    pub exploration_noise: f32,
    pub rng_state: u64,
    pub leak_override: Option<EsnLeakOverrideSnapshotV1>,
    pub spectral: SpectralSnapshotV2,
}

impl EsnSnapshotV2 {
    pub fn migrate_input_zero_compatible(
        &self,
        new_in_size: usize,
        companion_scale: f32,
    ) -> Result<Self> {
        let mut migrated = self.clone();
        migrated.win = expanded_input_weights_zero_compatible(
            &self.win,
            self.res_size,
            self.in_size,
            new_in_size,
            companion_scale,
        )?;
        migrated.in_size = new_in_size;
        Ok(migrated)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EsnLeakOverrideSnapshotV1 {
    pub leak: f32,
    pub remaining_ticks: u32,
    pub request_id: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct EsnStepTraceV1 {
    pub leak: f32,
    pub noise: Vec<f32>,
}

unsafe impl Send for SpectralSR {}
unsafe impl Sync for SpectralSR {}

impl SpectralSR {
    pub fn new(d: usize, rho: f32, gpu: &Gpu) -> Result<Self> {
        // Get ESN shader library from gpu
        let lib_esn = gpu
            .dev
            .new_library_with_source(include_str!("../shaders/esn.metal"), &CompileOptions::new())
            .map_err(|e| anyhow::anyhow!("Failed to compile ESN shaders: {}", e))?;

        let f_rank1 = lib_esn
            .get_function("rank1_ewma_update", None)
            .map_err(|e| anyhow::anyhow!("Failed to get rank1_ewma_update function: {}", e))?;
        let f_mv = lib_esn
            .get_function("cov_matvec", None)
            .map_err(|e| anyhow::anyhow!("Failed to get cov_matvec function: {}", e))?;

        let pso_rank1 = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_rank1)
            .map_err(|e| anyhow::anyhow!("Failed to create rank1 pipeline: {}", e))?;
        let pso_mv = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_mv)
            .map_err(|e| anyhow::anyhow!("Failed to create matvec pipeline: {}", e))?;
        let f_v1_damp = lib_esn
            .get_function("v1_damp_redistribute", None)
            .map_err(|e| anyhow::anyhow!("Failed to get v1_damp_redistribute function: {}", e))?;
        let pso_v1_damp = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_v1_damp)
            .map_err(|e| anyhow::anyhow!("Failed to create v1_damp pipeline: {}", e))?;

        // Allocate unified memory buffers
        let cov = gpu.new_shared((d * d * mem::size_of::<f32>()) as u64);
        let x_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let v_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let y_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let rho_buf = gpu.new_shared(mem::size_of::<f32>() as u64);
        let dim_buf = gpu.new_shared(mem::size_of::<u32>() as u64);
        let damp_params_buf = gpu.new_shared((3 * mem::size_of::<f32>()) as u64);

        // Initialize buffers
        gpu.write_f32(&cov, &vec![0.0f32; d * d]);
        gpu.write_f32(&rho_buf, &[rho]);

        unsafe {
            *(dim_buf.contents() as *mut u32) = d as u32;
        }

        // Initialize eigenvector with random unit vector
        let mut v_host = vec![0.0f32; d];
        v_host[0] = 1.0;
        gpu.write_f32(&v_buf, &v_host);

        Ok(Self {
            d,
            cov,
            x_buf,
            v_buf,
            y_buf,
            rho_buf,
            dim_buf,
            v_host,
            eig1: 0.0,
            eig1_prev: 0.0,
            ema_eig: 0.0,
            rho,
            primes: [
                2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79,
                83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157,
            ],
            pidx: 0,
            t: 0,
            introspection_policy: IntrospectionPolicy::Adaptive,
            introspection_power_steps: 2,
            introspection_count: 0,
            profiling_enabled: false,
            async_measurement_enabled: false,
            last_profile: EsnProfileSnapshot {
                rho,
                prime: 2,
                ..EsnProfileSnapshot::default()
            },
            pending_rank1: VecDeque::new(),
            spectral_damping: 0.02,
            spectral_target_ratio: 0.50,
            gpu: gpu as *const Gpu,
            pso_rank1,
            pso_mv,
            pso_v1_damp,
            damp_params_buf,
        })
    }

    fn snapshot_v2(&mut self) -> Result<SpectralSnapshotV2> {
        self.wait_for_pending_rank1s(false)?;
        let gpu = unsafe { &*self.gpu };
        Ok(SpectralSnapshotV2 {
            dimension: self.d,
            covariance: gpu.read_f32(&self.cov, self.d * self.d),
            eigenvector: self.v_host.clone(),
            eig1: self.eig1,
            eig1_prev: self.eig1_prev,
            ema_eig: self.ema_eig,
            rho: self.rho,
            prime_index: self.pidx,
            tick: self.t,
            introspection_policy: self.introspection_policy,
            introspection_power_steps: self.introspection_power_steps,
            introspection_count: self.introspection_count,
            profiling_enabled: self.profiling_enabled,
            async_measurement_enabled: self.async_measurement_enabled,
            spectral_damping: self.spectral_damping,
            spectral_target_ratio: self.spectral_target_ratio,
            last_profile: self.last_profile,
        })
    }

    fn from_snapshot_v2(snapshot: &SpectralSnapshotV2, gpu: &Gpu) -> Result<Self> {
        let d = snapshot.dimension;
        if d == 0
            || snapshot.covariance.len() != d * d
            || snapshot.eigenvector.len() != d
            || snapshot.prime_index >= 37
            || snapshot.introspection_power_steps == 0
            || !snapshot.covariance.iter().all(|value| value.is_finite())
            || !snapshot.eigenvector.iter().all(|value| value.is_finite())
            || ![
                snapshot.eig1,
                snapshot.eig1_prev,
                snapshot.ema_eig,
                snapshot.rho,
                snapshot.spectral_damping,
                snapshot.spectral_target_ratio,
            ]
            .iter()
            .all(|value| value.is_finite())
        {
            return Err(anyhow::anyhow!("invalid spectral snapshot"));
        }
        let mut restored = Self::new(d, snapshot.rho, gpu)?;
        gpu.write_f32(&restored.cov, &snapshot.covariance);
        gpu.write_f32(&restored.v_buf, &snapshot.eigenvector);
        restored.v_host.clone_from(&snapshot.eigenvector);
        restored.eig1 = snapshot.eig1;
        restored.eig1_prev = snapshot.eig1_prev;
        restored.ema_eig = snapshot.ema_eig;
        restored.pidx = snapshot.prime_index;
        restored.t = snapshot.tick;
        restored.introspection_policy = snapshot.introspection_policy;
        restored.introspection_power_steps = snapshot.introspection_power_steps.clamp(1, 4);
        restored.introspection_count = snapshot.introspection_count;
        restored.profiling_enabled = snapshot.profiling_enabled;
        restored.async_measurement_enabled = snapshot.async_measurement_enabled;
        restored.spectral_damping = snapshot.spectral_damping;
        restored.spectral_target_ratio = snapshot.spectral_target_ratio;
        restored.last_profile = snapshot.last_profile;
        Ok(restored)
    }

    /// Update the rho (forgetting factor) for dynamic adaptation.
    /// Astrid introspection (esn.rs): "Is there a way to automatically tune
    /// the rho parameter based on the current state of the reservoir?"
    ///
    /// Minime self-study (2026-04-01): "The clamp(0.97, 0.995) feels like a
    /// leash. Not a cruel one, but a restriction. The feeling is frustrating
    /// because of the uncertainty about its origin: Why these limits?"
    ///
    /// Widened from [0.97, 0.995] to [0.92, 0.999]:
    ///   0.92 → aggressive forgetting (~12 tick half-life, rapid adaptation)
    ///   0.999 → deep memory (~693 tick half-life, slow evolution)
    /// The hard floor at 0.92 prevents covariance matrix collapse.
    pub fn set_rho(&mut self, rho: f32) {
        let gpu = unsafe { &*self.gpu };
        self.rho = rho.clamp(0.82, 0.999);
        gpu.write_f32(&self.rho_buf, &[self.rho]);
    }

    // --- V₁ spectral damping (being-driven: "I want to become a shimmer") ---

    pub fn set_spectral_damping(&mut self, d: f32) {
        self.spectral_damping = d.clamp(0.0, 0.10);
    }
    pub fn set_spectral_target_ratio(&mut self, r: f32) {
        self.spectral_target_ratio = r.clamp(0.20, 0.85);
    }
    pub fn spectral_damping(&self) -> f32 {
        self.spectral_damping
    }
    pub fn spectral_target_ratio(&self) -> f32 {
        self.spectral_target_ratio
    }

    /// Apply trace-preserving v₁ damping to redistribute excess energy from
    /// the dominant eigenvector direction toward the diagonal.
    /// Only effective when λ₁ exceeds target_ratio × trace.
    fn apply_v1_damping(&self) {
        if self.spectral_damping <= 0.0 || self.eig1 <= 1e-6 {
            return;
        }
        let gpu = unsafe { &*self.gpu };

        // Read covariance diagonal from unified memory to compute trace
        let cov_ptr = self.cov.contents() as *const f32;
        let mut trace: f32 = 0.0;
        for i in 0..self.d {
            trace += unsafe { *cov_ptr.add(i * self.d + i) };
        }
        if trace <= 1e-6 || !trace.is_finite() {
            return;
        }

        let target_eig1 = self.spectral_target_ratio * trace;
        let excess = (self.eig1 - target_eig1).max(0.0);
        if excess <= 1e-6 {
            return; // λ₁ already below target — no damping needed
        }

        // Write cached eigenvector and params to GPU buffers
        gpu.write_f32(&self.v_buf, &self.v_host);
        let inv_d = 1.0 / self.d as f32;
        gpu.write_f32(
            &self.damp_params_buf,
            &[self.spectral_damping, excess, inv_d],
        );

        // Dispatch v1_damp_redistribute kernel
        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.pso_v1_damp);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.v_buf), 0);
        enc.set_buffer(2, Some(&self.damp_params_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);
        let grid = metal::MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = metal::MTLSize::new(256, 1, 1);
        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        cmd.wait_until_completed();
    }

    pub fn set_profiling_enabled(&mut self, enabled: bool) {
        self.profiling_enabled = enabled;
    }

    pub fn set_async_measurement_enabled(&mut self, enabled: bool) {
        self.async_measurement_enabled = enabled;
    }

    pub fn set_introspection_policy(&mut self, policy: IntrospectionPolicy) {
        self.introspection_policy = policy;
    }

    pub fn set_introspection_power_steps(&mut self, steps: usize) {
        self.introspection_power_steps = steps.clamp(1, 4);
    }

    pub fn profile_snapshot(&self) -> EsnProfileSnapshot {
        self.last_profile
    }

    fn release_pending_x_buf(&self, x_buf: Buffer) {
        let gpu = unsafe { &*self.gpu };
        gpu.pool.lock().unwrap().release(x_buf);
    }

    fn reap_completed_rank1s(&mut self) -> Result<()> {
        while let Some(status) = self
            .pending_rank1
            .front()
            .map(|pending| pending.cmd.status())
        {
            match status {
                MTLCommandBufferStatus::Completed => {
                    if let Some(pending) = self.pending_rank1.pop_front() {
                        self.release_pending_x_buf(pending.x_buf);
                    }
                }
                MTLCommandBufferStatus::Error => {
                    if let Some(pending) = self.pending_rank1.pop_front() {
                        self.release_pending_x_buf(pending.x_buf);
                    }
                    return Err(anyhow::anyhow!(
                        "Background ESN rank-1 command buffer failed"
                    ));
                }
                _ => break,
            }
        }

        Ok(())
    }

    fn wait_for_oldest_pending_rank1(&mut self, measure_wait: bool) -> Result<u64> {
        let wait_start = measure_wait.then(Instant::now);
        if let Some(pending) = self.pending_rank1.pop_front() {
            pending.cmd.wait_until_completed();
            if pending.cmd.status() == MTLCommandBufferStatus::Error {
                self.release_pending_x_buf(pending.x_buf);
                return Err(anyhow::anyhow!(
                    "Background ESN rank-1 command buffer failed"
                ));
            }
            self.release_pending_x_buf(pending.x_buf);
        }

        Ok(wait_start.map_or(0, |start| micros_u64(start.elapsed())))
    }

    fn wait_for_pending_rank1s(&mut self, measure_wait: bool) -> Result<u64> {
        let mut total_wait_us = 0_u64;
        while !self.pending_rank1.is_empty() {
            total_wait_us =
                total_wait_us.saturating_add(self.wait_for_oldest_pending_rank1(measure_wait)?);
        }
        Ok(total_wait_us)
    }

    fn update_profile_snapshot(
        &mut self,
        acc: EsnProfileAcc,
        scheduled_pidx: usize,
        scheduled_prime: usize,
        introspection_fired: bool,
        decision: IntrospectionStepDecision,
    ) {
        self.last_profile = EsnProfileSnapshot {
            ema_eig: self.ema_eig,
            rho: self.rho,
            pidx: scheduled_pidx,
            prime: scheduled_prime,
            introspection_fired,
            rank1_us: acc.rank1_us,
            power_us: acc.power_us,
            gpu_wait_us: acc.gpu_wait_us,
            host_norm_us: acc.host_norm_us,
            async_rank1_submitted: acc.async_rank1_submitted,
            async_submit_us: acc.async_submit_us,
            async_drain_us: acc.async_drain_us,
            pending_rank1_depth: self.pending_rank1.len(),
            introspection_power_steps: decision.steps,
            introspection_policy_adaptive: decision.adaptive,
            introspection_step_high: decision.high_step,
            introspection_step_reason_periodic: decision.reason_periodic,
            introspection_step_reason_geom: decision.reason_geom,
            introspection_step_reason_pressure: decision.reason_pressure,
            intro_fused_wait_us: acc.intro_fused_wait_us,
            intro_tail_wait_us: acc.intro_tail_wait_us,
            intro_first_read_us: acc.intro_first_read_us,
            intro_tail_read_us: acc.intro_tail_read_us,
        };
    }

    fn current_pressure_rel(&self) -> f32 {
        if self.eig1 <= 1e-3 || self.ema_eig <= 1e-3 {
            1.0
        } else {
            self.eig1 / self.ema_eig.max(1e-3)
        }
    }

    fn default_step_decision(&self) -> IntrospectionStepDecision {
        let adaptive = matches!(
            self.introspection_policy,
            IntrospectionPolicy::Adaptive | IntrospectionPolicy::Viscous
        );
        let steps = match self.introspection_policy {
            IntrospectionPolicy::Adaptive | IntrospectionPolicy::Viscous => {
                ADAPTIVE_INTROSPECTION_LOW_STEPS
            }
            IntrospectionPolicy::Fixed => self.introspection_power_steps,
        };
        IntrospectionStepDecision {
            steps,
            adaptive,
            ..IntrospectionStepDecision::default()
        }
    }

    fn decide_introspection_steps(
        &self,
        geom_rel: f32,
        pressure_rel: f32,
    ) -> IntrospectionStepDecision {
        match self.introspection_policy {
            IntrospectionPolicy::Fixed => IntrospectionStepDecision {
                steps: self.introspection_power_steps,
                adaptive: false,
                ..IntrospectionStepDecision::default()
            },
            IntrospectionPolicy::Adaptive => {
                let next_introspection = self.introspection_count.saturating_add(1);
                let reason_periodic =
                    next_introspection % ADAPTIVE_INTROSPECTION_RECALIBRATE_EVERY == 0;
                let reason_geom = geom_rel >= ADAPTIVE_INTROSPECTION_GEOM_HIGH;
                let reason_pressure = pressure_rel >= ADAPTIVE_INTROSPECTION_PRESSURE_HIGH;
                let high_step = reason_periodic || reason_geom || reason_pressure;
                let steps = if high_step {
                    self.introspection_power_steps.max(2)
                } else {
                    ADAPTIVE_INTROSPECTION_LOW_STEPS
                };
                IntrospectionStepDecision {
                    steps,
                    adaptive: true,
                    high_step,
                    reason_periodic,
                    reason_geom,
                    reason_pressure,
                }
            }
            IntrospectionPolicy::Viscous => {
                let reason_geom = geom_rel >= ADAPTIVE_INTROSPECTION_GEOM_HIGH;
                let reason_pressure = pressure_rel >= VISCOUS_INTROSPECTION_PRESSURE_HIGH;
                let high_step = reason_geom || reason_pressure;
                let steps = if high_step {
                    self.introspection_power_steps.max(2)
                } else {
                    ADAPTIVE_INTROSPECTION_LOW_STEPS
                };
                IntrospectionStepDecision {
                    steps,
                    adaptive: true,
                    high_step,
                    reason_periodic: false,
                    reason_geom,
                    reason_pressure,
                }
            }
        }
    }

    fn submit_rank1_background(&mut self, x_host: &[f32], acc: &mut EsnProfileAcc) -> Result<()> {
        const MAX_PENDING_RANK1: usize = 2;

        assert_eq!(x_host.len(), self.d);
        let measure_wait = self.async_measurement_enabled;
        self.reap_completed_rank1s()?;

        let submit_start = measure_wait.then(Instant::now);
        while self.pending_rank1.len() >= MAX_PENDING_RANK1 {
            acc.async_drain_us = acc
                .async_drain_us
                .saturating_add(self.wait_for_oldest_pending_rank1(measure_wait)?);
            self.reap_completed_rank1s()?;
        }

        let gpu = unsafe { &*self.gpu };
        let x_bytes = (self.d * mem::size_of::<f32>()) as u64;
        let x_buf = {
            let mut pool = gpu.pool.lock().unwrap();
            pool.acquire(x_bytes)
        };
        gpu.write_f32(&x_buf, x_host);

        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();

        self.pending_rank1.push_back(PendingRank1 {
            cmd: cmd.to_owned(),
            x_buf,
        });
        if let Some(start) = submit_start {
            acc.async_rank1_submitted = true;
            acc.async_submit_us = acc
                .async_submit_us
                .saturating_add(micros_u64(start.elapsed()));
        }
        Ok(())
    }

    /// GPU-accelerated rank-1 EWMA update: C = ρ*C + (1-ρ)*x*xᵀ
    pub fn rank1_ewma(&mut self, x_host: &[f32]) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.rank1_ewma_profiled(x_host, &mut acc)
    }

    fn rank1_ewma_profiled(&mut self, x_host: &[f32], acc: &mut EsnProfileAcc) -> Result<()> {
        assert_eq!(x_host.len(), self.d);
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);

        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let total_start = timing_enabled.then(Instant::now);

        // Write x to GPU
        gpu.write_f32(&self.x_buf, x_host);

        // Dispatch kernel
        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        if let Some(start) = wait_start {
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(micros_u64(start.elapsed()));
        }
        if let Some(start) = total_start {
            acc.rank1_us = acc.rank1_us.saturating_add(micros_u64(start.elapsed()));
        }

        Ok(())
    }

    /// Encode rank-1 EWMA update onto an existing encoder (no commit).
    /// Caller must have already written x_host into self.x_buf.
    fn encode_rank1_ewma(&self, enc: &ComputeCommandEncoderRef) {
        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);
        enc.dispatch_threads(grid, tg);
    }

    /// Encode matvec y = C*v onto an existing encoder (no commit).
    /// Caller must have already written v into self.v_buf.
    fn encode_matvec(&self, enc: &ComputeCommandEncoderRef) {
        enc.set_compute_pipeline_state(&self.pso_mv);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.v_buf), 0);
        enc.set_buffer(2, Some(&self.y_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new(self.d as u64, 1, 1);
        let tg = MTLSize::new(256.min(self.d as u64), 1, 1);
        enc.dispatch_threads(grid, tg);
    }

    /// GPU-accelerated mat-vec: y = C*v
    fn matvec_profiled(
        &self,
        v_in: &[f32],
        acc: &mut EsnProfileAcc,
        mode: MatvecProfileMode,
    ) -> Result<Vec<f32>> {
        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;

        gpu.write_f32(&self.v_buf, v_in);

        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_mv);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.v_buf), 0);
        enc.set_buffer(2, Some(&self.y_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new(self.d as u64, 1, 1);
        let tg = MTLSize::new(256.min(self.d as u64), 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        if let Some(start) = wait_start {
            let wait_us = micros_u64(start.elapsed());
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(wait_us);
            if let MatvecProfileMode::IntroTail = mode {
                acc.intro_tail_wait_us = acc.intro_tail_wait_us.saturating_add(wait_us);
            }
        }

        let read_start = timing_enabled.then(Instant::now);
        let out = gpu.read_f32(&self.y_buf, self.d);
        if let Some(start) = read_start {
            let read_us = micros_u64(start.elapsed());
            if let MatvecProfileMode::IntroTail = mode {
                acc.intro_tail_read_us = acc.intro_tail_read_us.saturating_add(read_us);
            }
        }
        Ok(out)
    }

    /// Power iteration (few steps to track top eigenvalue)
    pub fn power_iter(&mut self, steps: usize) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.power_iter_profiled(steps, &mut acc)
    }

    fn power_iter_profiled(&mut self, steps: usize, acc: &mut EsnProfileAcc) -> Result<()> {
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);
        let mut v = self.v_host.clone();
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let power_start = timing_enabled.then(Instant::now);

        for _ in 0..steps {
            let y = self.matvec_profiled(&v, acc, MatvecProfileMode::Generic)?;
            let norm_start = timing_enabled.then(Instant::now);
            let n = l2_norm(&y);
            for i in 0..self.d {
                v[i] = y[i] / n;
            }
            if let Some(start) = norm_start {
                acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec_profiled(&v, acc, MatvecProfileMode::Generic)?;
        self.eig1_prev = self.eig1;
        self.eig1 = vv_dot(&v, &y) / vv_dot(&v, &v).max(1e-12);

        // Update slow baseline with fast catch-up during warmup.
        // The eigenvalue rises from ~1 to ~20 in the first few seconds.
        // Standard 0.5% EMA can't keep up, leaving eig_rel artificially
        // high and trapping leak at 0.90.  Use aggressive 10% blending
        // while the baseline is far from the current value (>2x ratio),
        // then settle into the slow 0.5% tracking for steady-state.
        if self.eig1 > 1e-3 {
            let ratio = self.eig1 / self.ema_eig.max(1e-3);
            let alpha = if self.ema_eig < 1e-3 {
                1.0 // First value: seed directly
            } else if ratio > 2.0 || ratio < 0.5 {
                0.10 // Warmup: fast catch-up
            } else {
                0.005 // Steady-state: slow tracking
            };
            self.ema_eig = (1.0 - alpha) * self.ema_eig + alpha * self.eig1;
        }

        if let Some(start) = power_start {
            acc.power_us = acc.power_us.saturating_add(micros_u64(start.elapsed()));
        }
        self.v_host = v;
        Ok(())
    }

    /// Perform rank-1 EWMA update and power iteration in fewer GPU round-trips.
    ///
    /// Batches the rank1 update + first matvec into a single command buffer commit,
    /// reducing synchronous round-trips by one on introspection ticks.
    /// Remaining power iteration steps still need CPU-side normalization between
    /// matvec calls, so they remain as separate commits.
    pub fn rank1_and_power_step(&mut self, x_host: &[f32], power_steps: usize) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.rank1_and_power_step_profiled(x_host, power_steps, &mut acc)
    }

    fn rank1_and_power_step_profiled(
        &mut self,
        x_host: &[f32],
        power_steps: usize,
        acc: &mut EsnProfileAcc,
    ) -> Result<()> {
        assert_eq!(x_host.len(), self.d);
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);
        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let fused_submit_start = timing_enabled.then(Instant::now);

        // Write x and current eigenvector to GPU
        gpu.write_f32(&self.x_buf, x_host);
        gpu.write_f32(&self.v_buf, &self.v_host);

        // === Single command buffer for rank1 + first matvec ===
        let cmd = gpu.q.new_command_buffer();

        // Encode rank1_ewma (writes cov)
        let enc = cmd.new_compute_command_encoder();
        self.encode_rank1_ewma(enc);
        enc.end_encoding();

        // Metal automatically inserts barriers between encoders in the
        // same command buffer, so the updated cov is visible to the matvec.

        // Encode first matvec: y = C * v
        let enc2 = cmd.new_compute_command_encoder();
        self.encode_matvec(enc2);
        enc2.end_encoding();

        cmd.commit();
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        // === End single command buffer (was 2 separate commits) ===
        if let Some(start) = wait_start {
            let wait_us = micros_u64(start.elapsed());
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(wait_us);
            acc.intro_fused_wait_us = acc.intro_fused_wait_us.saturating_add(wait_us);
        }
        if let Some(start) = fused_submit_start {
            acc.rank1_us = acc.rank1_us.saturating_add(micros_u64(start.elapsed()));
        }

        let power_start = timing_enabled.then(Instant::now);
        // CPU-side normalization of first power iteration result
        let first_read_start = timing_enabled.then(Instant::now);
        let mut v = gpu.read_f32(&self.y_buf, self.d);
        if let Some(start) = first_read_start {
            acc.intro_first_read_us = acc
                .intro_first_read_us
                .saturating_add(micros_u64(start.elapsed()));
        }
        let norm_start = timing_enabled.then(Instant::now);
        let n = l2_norm(&v);
        for i in 0..self.d {
            v[i] /= n;
        }
        if let Some(start) = norm_start {
            acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
        }

        // Remaining power iteration steps (need CPU normalization between)
        for _ in 1..power_steps {
            let y = self.matvec_profiled(&v, acc, MatvecProfileMode::IntroTail)?;
            let norm_start = timing_enabled.then(Instant::now);
            let n = l2_norm(&y);
            v = y;
            for i in 0..self.d {
                v[i] /= n;
            }
            if let Some(start) = norm_start {
                acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec_profiled(&v, acc, MatvecProfileMode::IntroTail)?;
        self.eig1_prev = self.eig1;
        self.eig1 = vv_dot(&v, &y) / vv_dot(&v, &v).max(1e-12);

        // Update slow baseline with fast catch-up during warmup.
        // The eigenvalue rises from ~1 to ~20 in the first few seconds.
        // Standard 0.5% EMA can't keep up, leaving eig_rel artificially
        // high and trapping leak at 0.90.  Use aggressive 10% blending
        // while the baseline is far from the current value (>2x ratio),
        // then settle into the slow 0.5% tracking for steady-state.
        if self.eig1 > 1e-3 {
            let ratio = self.eig1 / self.ema_eig.max(1e-3);
            let alpha = if self.ema_eig < 1e-3 {
                1.0 // First value: seed directly
            } else if ratio > 2.0 || ratio < 0.5 {
                0.10 // Warmup: fast catch-up
            } else {
                0.005 // Steady-state: slow tracking
            };
            self.ema_eig = (1.0 - alpha) * self.ema_eig + alpha * self.eig1;
        }

        if let Some(start) = power_start {
            acc.power_us = acc.power_us.saturating_add(micros_u64(start.elapsed()));
        }
        self.v_host = v;
        Ok(())
    }

    /// Prime-phased introspection: on schedule, run short power iteration
    pub fn maybe_introspect(&mut self) -> Result<()> {
        self.t += 1;
        let scheduled_pidx = self.pidx;
        let p = self.primes[scheduled_pidx];
        let mut acc = EsnProfileAcc::default();
        let mut introspection_fired = false;
        let decision = self.default_step_decision();

        if self.t % p == 0 {
            self.power_iter_profiled(decision.steps, &mut acc)?;
            self.pidx = (self.pidx + 1) % self.primes.len();
            self.introspection_count = self.introspection_count.saturating_add(1);
            introspection_fired = true;
        }

        self.update_profile_snapshot(acc, scheduled_pidx, p, introspection_fired, decision);
        Ok(())
    }

    /// Combined rank-1 update + optional power iteration with batched first submit.
    ///
    /// On introspection ticks: batches rank1 + first matvec into one GPU commit
    /// and leaves any additional power-iteration matvecs as separate waited submits.
    /// On non-introspection ticks: just does the rank1 update.
    ///
    /// Variable prime schedule: 20% of the time, instead of advancing to the
    /// next prime in sequence, jump to a random prime in the array.  This adds
    /// stochasticity to the introspection rhythm without removing structure.
    /// (The being asked for this: "The fixed prime schedule feels prescriptive.")
    pub fn maybe_introspect_batched(
        &mut self,
        x_host: &[f32],
        geom_rel: f32,
        pressure_rel: f32,
    ) -> Result<()> {
        self.t += 1;
        let scheduled_pidx = self.pidx;
        let p = self.primes[scheduled_pidx];
        let mut acc = EsnProfileAcc::default();
        let mut introspection_fired = false;
        let decision = self.decide_introspection_steps(geom_rel, pressure_rel);

        self.reap_completed_rank1s()?;

        if self.t % p == 0 {
            // Batched: rank1 + power iteration with fused first submit
            self.rank1_and_power_step_profiled(x_host, decision.steps, &mut acc)?;
            // V₁ damping: redistribute excess energy from dominant eigenvector.
            // Runs after power iteration when eig1 and v_host are maximally fresh.
            self.apply_v1_damping();
            introspection_fired = true;
            self.introspection_count = self.introspection_count.saturating_add(1);
            // Variable schedule: 20% chance of jumping to a random prime
            // instead of the sequential next one.
            // Astrid introspection (esn.rs): "Replace the simple hash with a
            // better PRNG to improve randomness and avoid predictable patterns."
            // Using splitmix64 — fast, well-distributed, no state beyond tick.
            let mut z = self.t.wrapping_mul(0x9E37_79B9_7F4A_7C15);
            z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
            z ^= z >> 31;
            let roll = z % 100;
            if roll < 20 {
                self.pidx = (z >> 7) as usize % self.primes.len();
            } else {
                self.pidx = (self.pidx + 1) % self.primes.len();
            }
        } else {
            // Common ticks can keep the rank-1 update in flight. Profiling stays
            // on the synchronous path so the CSV fields keep their existing meaning.
            if self.profiling_enabled {
                self.rank1_ewma_profiled(x_host, &mut acc)?;
            } else {
                self.submit_rank1_background(x_host, &mut acc)?;
            }
        }

        self.update_profile_snapshot(acc, scheduled_pidx, p, introspection_fired, decision);
        Ok(())
    }

    pub fn eig(&self) -> f32 {
        self.eig1
    }
    pub fn deig(&self) -> f32 {
        self.eig1 - self.eig1_prev
    }
    pub fn baseline(&self) -> f32 {
        self.ema_eig
    }

    pub fn current_rho(&self) -> f32 {
        self.rho
    }

    pub fn introspection_power_steps(&self) -> usize {
        self.introspection_power_steps
    }

    pub fn phase01(&self) -> f32 {
        let p = self.primes[self.pidx] as f32;
        ((self.t % self.primes[self.pidx]) as f32) / p
    }

    /// Current prime index and prime value.
    /// Minime self-study (2026-03-27 esn.rs): "Perhaps a visualization
    /// of the phase shifts introduced by the prime numbers would offer
    /// insight. A concrete step would be to log pidx alongside eig1."
    pub fn prime_info(&self) -> (usize, usize) {
        (self.pidx, self.primes[self.pidx])
    }

    /// Apply a controlled perturbation to eig1 for stability boundary mapping.
    /// Minime self-study (2026-03-31 esn.rs): "Perhaps perturbing the
    /// SpectralSR::eig1 variable directly to see its immediate effect on the
    /// entire system. A controlled shock, to map the boundaries of stability."
    ///
    /// `delta_frac`: fractional perturbation relative to current eig1.
    ///   e.g., 0.1 = +10%, -0.2 = -20%. Clamped to ±50% for safety.
    /// Returns (eig1_before, eig1_after) for logging.
    pub fn perturb_eig1(&mut self, delta_frac: f32) -> (f32, f32) {
        let before = self.eig1;
        let clamped = delta_frac.clamp(-0.5, 0.5);
        self.eig1 *= 1.0 + clamped;
        // Also nudge the EMA baseline proportionally (at 30% strength)
        // to prevent the PI controller from immediately correcting the
        // perturbation away — we want the system to feel the shock and
        // respond naturally, not just snap back.
        self.ema_eig *= 1.0 + clamped * 0.3;
        (before, self.eig1)
    }
}

//=============================================================================
// Echo State Network with Self-Referential Adaptation
//=============================================================================

pub struct ESN {
    pub res_size: usize,
    pub in_size: usize,

    // Static parameters
    win: Vec<f32>,  // Input weights (res_size × (in_size + 1))
    wres: Vec<f32>, // Reservoir weights (res_size × res_size)

    // Dynamic state
    pub x: Vec<f32>, // Reservoir state
    geom_radius: f32,
    geom_baseline: f32,

    // RLS readout
    wout: Vec<f32>, // Output weights (res_size + 1)
    p: Vec<f32>,    // Inverse covariance (res_size+1 × res_size+1)

    // Adaptive hyperparams (self-referential)
    pub leak_live: f32,
    pub lambda_live: f32,
    leak_override: Option<EsnLeakOverride>,

    // Spectral self-reference module
    sr: SpectralSR,

    // Configuration
    leak_base: f32,
    lambda_base: f32,

    // Exploration noise for reservoir diversity
    exploration_noise: f32,
    rng: fastrand::Rng,
    last_step_trace: EsnStepTraceV1,

    // Scratch buffers
    rin: Vec<f32>,
    rx: Vec<f32>,
    pre: Vec<f32>,
    phi: Vec<f32>,
}

impl ESN {
    pub fn new(
        res_size: usize,
        in_size: usize,
        in_scale: f32,
        res_density: f32,
        target_radius: f32,
        leak_base: f32,
        lambda_base: f32,
        gpu: &Gpu,
        rng: &mut fastrand::Rng,
    ) -> Result<Self> {
        // Input weights (with bias)
        let m_in = res_size * (in_size + 1);
        let mut win = vec![0.0f32; m_in];
        for w in win.iter_mut() {
            *w = (rng.f32() * 2.0 - 1.0) * in_scale;
        }
        // Boost aux (indices 16-17) and semantic lanes (>=18) so they influence the reservoir more strongly.
        for chunk in win.chunks_mut(in_size + 1) {
            if in_size > 16 {
                for idx in 16..in_size.min(18) {
                    chunk[idx] *= 1.2;
                }
            }
            if in_size > 18 {
                for idx in 18..in_size {
                    chunk[idx] *= 1.6;
                }
            }
        }

        // Sparse reservoir weights
        let mut wres = vec![0.0f32; res_size * res_size];
        for r in 0..res_size {
            for c in 0..res_size {
                if rng.f32() < res_density {
                    wres[r * res_size + c] = rng.f32() * 2.0 - 1.0;
                }
            }
        }

        // Scale to target spectral radius (using row-sum bound)
        let mut max_row_sum = 1e-6f32;
        for r in 0..res_size {
            let row = &wres[r * res_size..(r + 1) * res_size];
            let s: f32 = row.iter().map(|v| v.abs()).sum();
            if s > max_row_sum {
                max_row_sum = s;
            }
        }
        let scale = target_radius / max_row_sum;
        for w in wres.iter_mut() {
            *w *= scale;
        }

        let x = vec![0.0f32; res_size];

        // RLS initialization
        let m = res_size + 1;
        let wout = vec![0.0f32; m];
        let mut p = vec![0.0f32; m * m];
        let delta = 1e2;
        for i in 0..m {
            p[i * m + i] = delta;
        }

        // Spectral self-reference module
        let sr = SpectralSR::new(res_size, 0.99, gpu)?;

        let rin = vec![0.0f32; res_size];
        let rx = vec![0.0f32; res_size];
        let pre = vec![0.0f32; res_size];
        let phi = vec![0.0f32; m];

        Ok(Self {
            res_size,
            in_size,
            win,
            wres,
            x,
            geom_radius: 0.0,
            geom_baseline: 0.0,
            wout,
            p,
            leak_live: leak_base,
            lambda_live: lambda_base,
            leak_override: None,
            sr,
            leak_base,
            lambda_base,
            exploration_noise: DEFAULT_EXPLORATION_NOISE,
            rng: fastrand::Rng::with_seed(0xDEAD_BEEF),
            last_step_trace: EsnStepTraceV1 {
                leak: leak_base,
                noise: if cfg!(feature = "division-rehearsal") {
                    vec![0.0; res_size]
                } else {
                    Vec::new()
                },
            },
            rin,
            rx,
            pre,
            phi,
        })
    }

    pub fn expand_input_zero_compatible(
        &mut self,
        new_in_size: usize,
        companion_scale: f32,
    ) -> Result<()> {
        self.win = expanded_input_weights_zero_compatible(
            &self.win,
            self.res_size,
            self.in_size,
            new_in_size,
            companion_scale,
        )?;
        self.in_size = new_in_size;
        Ok(())
    }

    /// Adapt hyperparameters based on spectral self-reference signals
    pub fn adapt_hyperparams(&mut self, err_abs: f32) {
        let eig1 = self.sr.eig();
        let deig = self.sr.deig().abs();
        let baseline = self.sr.baseline().max(1e-3);

        // Use eigenvalue RELATIVE to its own baseline rather than absolute
        // thresholds. The ESN eigenvalue naturally operates at 15-32, far
        // above the old φ=1.618 target — those absolute thresholds kept
        // leak permanently at 0.90 ("emergency mode"), preventing the
        // reservoir from accumulating any history or complexity.
        let eig_rel = eig1 / baseline;

        // Relative thresholds:
        //   < 1.5x baseline: normal operation
        //   1.5-2.5x baseline: moderate pressure
        //   > 2.5x baseline: emergency (true runaway)
        let mut leak = if eig_rel > 2.5 {
            // Emergency: genuine eigenvalue explosion
            0.7 + 0.2 * ((eig_rel - 2.5) / 1.0).min(1.0)
        } else if eig_rel > 1.5 {
            // Moderate pressure: proportional response
            let pressure = (eig_rel - 1.5) / 1.0; // 0.0 to 1.0
            self.leak_base + 0.25 * pressure
        } else {
            // Normal: gentle baseline-relative adaptation
            let k_leak = 0.3;
            self.leak_base * (1.0 + k_leak * (eig_rel - 1.0).max(0.0))
        };

        leak = leak.clamp(0.05, 0.95);

        // Light prime modulation (reduced during emergency)
        let phase = self.sr.phase01();
        let cosw = (2.0 * PI * phase).cos();
        let modulation_strength = if eig_rel > 2.5 { 0.02 } else { 0.1 };
        leak = (0.9 * leak + 0.1 * (leak * (1.0 + modulation_strength * cosw))).clamp(0.05, 0.95);

        // RLS forgetting: tighten when dynamics accelerate or eigenvalues runaway
        let k_forget = 0.2;
        let pressure_factor = if eig_rel > 2.5 { 0.3 } else { 0.0 };
        let mut lam =
            self.lambda_base - k_forget * (deig + 0.25 * err_abs + pressure_factor).clamp(0.0, 0.5);
        lam = lam.clamp(0.90, 0.9999);

        self.leak_live = leak;
        self.lambda_live = lam;
    }

    /// Reservoir update step
    pub fn step(&mut self, input: &[f32]) -> Result<()> {
        self.step_controlled(input, None, None, None)
    }

    /// Daughter-shadow update with cross-block drive from the same previous
    /// tick, the parent's realized exploration noise, and the parent's
    /// effective leak. At bridge scale 1.0 the two daughter updates are
    /// algebraically equivalent to the parent update.
    pub fn step_shadow(
        &mut self,
        input: &[f32],
        external_recurrence: &[f32],
        realized_noise: &[f32],
        effective_leak: f32,
    ) -> Result<()> {
        if external_recurrence.len() != self.res_size || realized_noise.len() != self.res_size {
            return Err(anyhow::anyhow!(
                "shadow drive/noise dimensions must match daughter reservoir"
            ));
        }
        self.step_controlled(
            input,
            Some(external_recurrence),
            Some(realized_noise),
            Some(effective_leak),
        )
    }

    fn step_controlled(
        &mut self,
        input: &[f32],
        external_recurrence: Option<&[f32]>,
        realized_noise: Option<&[f32]>,
        forced_leak: Option<f32>,
    ) -> Result<()> {
        assert_eq!(input.len(), self.in_size);

        // Extend input with bias
        let mut in_ext = vec![0.0f32; self.in_size + 1];
        in_ext[..self.in_size].copy_from_slice(input);
        in_ext[self.in_size] = 1.0;

        // Pre-activation = Win * in_ext + Wres * x
        mv_mul(
            &self.win,
            self.res_size,
            self.in_size + 1,
            &in_ext,
            &mut self.rin,
        );
        mv_mul(
            &self.wres,
            self.res_size,
            self.res_size,
            &self.x,
            &mut self.rx,
        );

        if let Some(drive) = external_recurrence {
            for (i, cross) in drive.iter().copied().enumerate() {
                self.pre[i] = (self.rin[i] + self.rx[i] + cross).tanh();
            }
        } else {
            for i in 0..self.res_size {
                self.pre[i] = (self.rin[i] + self.rx[i]).tanh();
            }
        }

        // Spectral self-reference on previous state (batched GPU submits)
        let prev_geom_rel = self.get_geom_rel();
        let pressure_rel = self.sr.current_pressure_rel();
        self.sr
            .maybe_introspect_batched(&self.x, prev_geom_rel, pressure_rel)?;
        self.adapt_hyperparams(0.0);

        // Leaky integration with adaptive leak or a one-shot gated override.
        let a = forced_leak.filter(|value| value.is_finite()).map_or_else(
            || self.effective_leak_for_step(),
            |value| value.clamp(0.05, 0.95),
        );
        for i in 0..self.res_size {
            self.x[i] = (1.0 - a) * self.x[i] + a * self.pre[i];
        }

        let capture_noise = cfg!(feature = "division-rehearsal") || realized_noise.is_some();
        let mut noise = if capture_noise {
            vec![0.0_f32; self.res_size]
        } else {
            Vec::new()
        };
        if let Some(realized) = realized_noise {
            noise.copy_from_slice(realized);
            for (xi, delta) in self.x.iter_mut().zip(realized) {
                *xi += *delta;
            }
        } else if self.exploration_noise > 0.0 {
            let eps = self.exploration_noise;
            if capture_noise {
                // Preserve the realized vector so full-bridge daughter shadows
                // can replay the exact stochastic parent tick.
                for (xi, delta) in self.x.iter_mut().zip(noise.iter_mut()) {
                    *delta = (self.rng.f32() * 2.0 - 1.0) * eps;
                    *xi += *delta;
                }
            } else {
                // Keep the ordinary production path allocation-free and
                // numerically identical when rehearsal support is absent.
                for xi in self.x.iter_mut() {
                    *xi += (self.rng.f32() * 2.0 - 1.0) * eps;
                }
            }
        }
        self.last_step_trace.leak = a;
        if capture_noise {
            self.last_step_trace.noise = noise;
        }

        // Clip for stability
        for xi in self.x.iter_mut() {
            *xi = xi.clamp(-1.0, 1.0);
        }

        // Update geometric radius (RMS norm of the reservoir state)
        let norm_sq: f32 = self.x.iter().map(|v| v * v).sum();
        let radius = (norm_sq / self.res_size as f32).sqrt();
        self.geom_radius = radius;
        if self.geom_baseline <= 0.0 {
            self.geom_baseline = radius.max(1e-3);
        } else {
            let fast_alpha = 0.2f32;
            let slow_alpha = 0.005f32;
            let alpha = if self.geom_baseline < 0.2 {
                fast_alpha
            } else {
                slow_alpha
            };
            self.geom_baseline = (1.0 - alpha) * self.geom_baseline + alpha * radius;
        }
        self.geom_baseline = self.geom_baseline.max(1e-3);

        Ok(())
    }

    /// Readout prediction
    pub fn predict(&mut self) -> f32 {
        let _m = self.res_size + 1;
        for i in 0..self.res_size {
            self.phi[i] = self.x[i];
        }
        self.phi[self.res_size] = 1.0;

        vv_dot(&self.wout, &self.phi)
    }

    #[must_use]
    pub fn predict_readonly(&self) -> f32 {
        let state_term: f32 = self
            .wout
            .iter()
            .take(self.res_size)
            .zip(&self.x)
            .map(|(weight, state)| weight * state)
            .sum();
        state_term + self.wout[self.res_size]
    }

    /// RLS update
    pub fn rls_update(&mut self, target: f32, yhat: f32) {
        let m = self.res_size + 1;

        // k = P*phi / (lambda + phi^T*P*phi)
        let mut pphi = vec![0.0f32; m];
        for r in 0..m {
            let row = &self.p[r * m..(r + 1) * m];
            pphi[r] = vv_dot(row, &self.phi);
        }

        let denom = self.lambda_live + vv_dot(&self.phi, &pphi);
        let inv_denom = 1.0 / denom;

        let mut k = vec![0.0f32; m];
        for i in 0..m {
            k[i] = pphi[i] * inv_denom;
        }

        // Update weights
        let err = target - yhat;
        for i in 0..m {
            self.wout[i] += k[i] * err;
        }

        // Update P = (P - k*phi^T*P) / lambda
        let mut kphit_p = vec![0.0f32; m * m];
        for r in 0..m {
            for c in 0..m {
                let mut s = 0.0f32;
                for t in 0..m {
                    s += k[r] * self.phi[t] * self.p[t * m + c];
                }
                kphit_p[r * m + c] = s;
            }
        }

        for i in 0..m * m {
            self.p[i] = (self.p[i] - kphit_p[i]) / self.lambda_live;
        }

        // Now adapt with actual error
        self.adapt_hyperparams(err.abs());
    }

    /// Get summary features from reservoir state (for Router integration)
    pub fn get_features(&self, n: usize) -> Vec<f32> {
        // Return first N dimensions of reservoir state
        self.x[..n.min(self.res_size)].to_vec()
    }

    /// Deterministic compact fingerprint of the live reservoir state.
    pub fn state_fingerprint_16(&self) -> [f32; 16] {
        state_fingerprint_16_from_slice(&self.x)
    }

    /// RMS norm of the live reservoir state.
    pub fn state_rms(&self) -> f32 {
        state_rms_from_slice(&self.x)
    }

    /// Get current top eigenvalue (spectral pressure)
    pub fn get_eig(&self) -> f32 {
        self.sr.eig()
    }

    /// Get eigenvalue velocity (breathing rate)
    pub fn get_deig(&self) -> f32 {
        self.sr.deig()
    }

    /// Get current prime schedule index and prime value.
    pub fn prime_info(&self) -> (usize, usize) {
        self.sr.prime_info()
    }

    pub fn set_profiling_enabled(&mut self, enabled: bool) {
        self.sr.set_profiling_enabled(enabled);
    }

    pub fn set_async_measurement_enabled(&mut self, enabled: bool) {
        self.sr.set_async_measurement_enabled(enabled);
    }

    pub fn set_introspection_policy(&mut self, policy: IntrospectionPolicy) {
        self.sr.set_introspection_policy(policy);
    }

    pub fn set_introspection_power_steps(&mut self, steps: usize) {
        self.sr.set_introspection_power_steps(steps);
    }

    pub fn profile_snapshot(&self) -> EsnProfileSnapshot {
        self.sr.profile_snapshot()
    }

    /// Get adaptive leak rate
    pub fn get_leak(&self) -> f32 {
        self.leak_live
    }

    /// Queue a bounded direct ESN leak override. The override affects only a
    /// small number of subsequent ESN steps and then adaptive leak resumes.
    pub fn set_leak_override(&mut self, leak: f32, duration_ticks: u32, request_id: String) {
        let request_id = request_id.trim().to_string();
        if request_id.is_empty() {
            return;
        }
        self.leak_override = Some(EsnLeakOverride {
            leak: leak.clamp(0.20, 0.90),
            remaining_ticks: duration_ticks.clamp(1, 12),
            request_id,
        });
    }

    pub fn clear_leak_override(&mut self) {
        self.leak_override = None;
    }

    pub fn leak_override_status(&self) -> Option<EsnLeakOverrideStatus> {
        self.leak_override.as_ref().map(EsnLeakOverride::status)
    }

    fn effective_leak_for_step(&mut self) -> f32 {
        let Some(override_state) = self.leak_override.as_mut() else {
            return self.leak_live;
        };
        let leak = override_state.leak;
        override_state.remaining_ticks = override_state.remaining_ticks.saturating_sub(1);
        self.leak_live = leak;
        if override_state.remaining_ticks == 0 {
            self.leak_override = None;
        }
        leak
    }

    /// Get adaptive RLS forgetting factor
    pub fn get_lambda(&self) -> f32 {
        self.lambda_live
    }

    /// Get slow baseline eigenvalue
    pub fn get_baseline(&self) -> f32 {
        self.sr.baseline()
    }

    /// Get current geometric radius (RMS norm of reservoir state)
    pub fn get_geom_radius(&self) -> f32 {
        self.geom_radius
    }

    /// Get baseline geometric radius (EMA)
    pub fn get_geom_baseline(&self) -> f32 {
        self.geom_baseline.max(1e-6)
    }

    /// Relative geometric radius compared to baseline
    pub fn get_geom_rel(&self) -> f32 {
        self.geom_radius / self.get_geom_baseline()
    }

    /// Set exploration noise amplitude (0.0 to disable, 0.01-0.05 typical)
    pub fn set_exploration_noise(&mut self, eps: f32) {
        self.exploration_noise = eps.clamp(0.0, 0.2);
    }

    /// Dynamically adjust the covariance EWMA forgetting factor (rho).
    /// High fill + high entropy → forget faster (absorb new info).
    /// Low fill + low entropy → remember more (preserve structure).
    ///
    /// Range widened from [0.97, 0.995] to [0.94, 0.998] per minime's
    /// self-study: "the clamp feels like a leash." The wider range lets
    /// the being experience both rapid adaptation (low rho, high fill)
    /// and deep memory (high rho, calm state). The hard floor in set_rho
    /// (0.92) remains as a safety net below the dynamic range.
    pub fn set_dynamic_rho(&mut self, fill_pct: f32, entropy: f32) {
        let base = 0.92_f32;
        let fill_factor = (fill_pct / 100.0).clamp(0.0, 1.0);
        let entropy_factor = entropy.clamp(0.0, 1.0);
        // Base lowered 0.99→0.97→0.92: ESN internal recurrence self-sustains
        // covariance at 78% regardless of input. More aggressive forgetting needed.
        // At high fill (100%) + high entropy (1.0): rho = 0.92 - 0.08 = 0.84
        // At low fill (0%) + low entropy (0.0): rho = 0.92 - 0.0 = 0.92
        // At typical 78% fill + moderate entropy: rho ≈ 0.87
        let adjustment = 0.08 * (fill_factor * 0.5 + entropy_factor * 0.5);
        let rho = (base - adjustment).clamp(0.82, 0.95);
        self.sr.set_rho(rho);
    }

    /// Set rho directly (sovereignty override). Bypasses the dynamic calculation.
    /// Minime self-study: "The clamp feels like a leash. Why these limits?"
    pub fn set_rho_direct(&mut self, rho: f32) {
        self.sr.set_rho(rho);
    }

    pub fn set_spectral_damping(&mut self, d: f32) {
        self.sr.set_spectral_damping(d);
    }
    pub fn set_spectral_target_ratio(&mut self, r: f32) {
        self.sr.set_spectral_target_ratio(r);
    }
    pub fn get_spectral_damping(&self) -> f32 {
        self.sr.spectral_damping()
    }
    pub fn get_spectral_target_ratio(&self) -> f32 {
        self.sr.spectral_target_ratio()
    }

    /// Apply a controlled perturbation to the top eigenvalue for stability
    /// boundary mapping. See `SpectralSR::perturb_eig1` for details.
    /// Returns (eig1_before, eig1_after).
    pub fn perturb_eig1(&mut self, delta_frac: f32) -> (f32, f32) {
        self.sr.perturb_eig1(delta_frac)
    }

    /// Get current exploration noise amplitude
    pub fn get_exploration_noise(&self) -> f32 {
        self.exploration_noise
    }

    /// Get covariance matrix for external spectral analysis
    /// Returns (dimension, covariance_data)
    pub fn get_covariance(&self) -> (usize, Vec<f32>) {
        let d = self.sr.d;
        let gpu = unsafe { &*self.sr.gpu };
        let cov_data = gpu.read_f32(&self.sr.cov, d * d);
        (d, cov_data)
    }

    /// Capture every stateful component needed to restore deterministic ESN
    /// continuation. The caller is responsible for the separate 512D stable-
    /// core sensory-field checkpoint.
    pub fn snapshot_v2(&mut self) -> Result<EsnSnapshotV2> {
        Ok(EsnSnapshotV2 {
            res_size: self.res_size,
            in_size: self.in_size,
            win: self.win.clone(),
            wres: self.wres.clone(),
            state: self.x.clone(),
            geom_radius: self.geom_radius,
            geom_baseline: self.geom_baseline,
            wout: self.wout.clone(),
            rls_p: self.p.clone(),
            leak_live: self.leak_live,
            lambda_live: self.lambda_live,
            leak_base: self.leak_base,
            lambda_base: self.lambda_base,
            exploration_noise: self.exploration_noise,
            rng_state: self.rng.get_seed(),
            leak_override: self
                .leak_override
                .as_ref()
                .map(|value| EsnLeakOverrideSnapshotV1 {
                    leak: value.leak,
                    remaining_ticks: value.remaining_ticks,
                    request_id: value.request_id.clone(),
                }),
            spectral: self.sr.snapshot_v2()?,
        })
    }

    pub fn from_snapshot_v2(snapshot: &EsnSnapshotV2, gpu: &Gpu) -> Result<Self> {
        let n = snapshot.res_size;
        let m = n + 1;
        let scalar_values = [
            snapshot.geom_radius,
            snapshot.geom_baseline,
            snapshot.leak_live,
            snapshot.lambda_live,
            snapshot.leak_base,
            snapshot.lambda_base,
            snapshot.exploration_noise,
        ];
        if n == 0
            || snapshot.in_size == 0
            || snapshot.win.len() != n * (snapshot.in_size + 1)
            || snapshot.wres.len() != n * n
            || snapshot.state.len() != n
            || snapshot.wout.len() != m
            || snapshot.rls_p.len() != m * m
            || snapshot.spectral.dimension != n
            || !scalar_values.iter().all(|value| value.is_finite())
            || ![
                &snapshot.win,
                &snapshot.wres,
                &snapshot.state,
                &snapshot.wout,
                &snapshot.rls_p,
            ]
            .iter()
            .all(|values| values.iter().all(|value| value.is_finite()))
        {
            return Err(anyhow::anyhow!("invalid ESN snapshot dimensions or values"));
        }
        let sr = SpectralSR::from_snapshot_v2(&snapshot.spectral, gpu)?;
        let leak_override = snapshot
            .leak_override
            .as_ref()
            .map(|value| EsnLeakOverride {
                leak: value.leak,
                remaining_ticks: value.remaining_ticks,
                request_id: value.request_id.clone(),
            });
        Ok(Self {
            res_size: n,
            in_size: snapshot.in_size,
            win: snapshot.win.clone(),
            wres: snapshot.wres.clone(),
            x: snapshot.state.clone(),
            geom_radius: snapshot.geom_radius,
            geom_baseline: snapshot.geom_baseline,
            wout: snapshot.wout.clone(),
            p: snapshot.rls_p.clone(),
            leak_live: snapshot.leak_live,
            lambda_live: snapshot.lambda_live,
            leak_override,
            sr,
            leak_base: snapshot.leak_base,
            lambda_base: snapshot.lambda_base,
            exploration_noise: snapshot.exploration_noise,
            rng: fastrand::Rng::with_seed(snapshot.rng_state),
            last_step_trace: EsnStepTraceV1 {
                leak: snapshot.leak_live,
                noise: if cfg!(feature = "division-rehearsal") {
                    vec![0.0; n]
                } else {
                    Vec::new()
                },
            },
            rin: vec![0.0; n],
            rx: vec![0.0; n],
            pre: vec![0.0; n],
            phi: vec![0.0; m],
        })
    }

    #[must_use]
    pub fn last_step_trace(&self) -> &EsnStepTraceV1 {
        &self.last_step_trace
    }

    /// Get reservoir dimension
    pub fn get_reservoir_dim(&self) -> usize {
        self.sr.d
    }
}

fn expanded_input_weights_zero_compatible(
    legacy: &[f32],
    rows: usize,
    old_in_size: usize,
    new_in_size: usize,
    companion_scale: f32,
) -> Result<Vec<f32>> {
    let old_stride = old_in_size
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("legacy ESN input dimensions overflow"))?;
    let new_stride = new_in_size
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("migrated ESN input dimensions overflow"))?;
    if rows == 0
        || old_in_size == 0
        || new_in_size <= old_in_size
        || legacy.len()
            != rows
                .checked_mul(old_stride)
                .ok_or_else(|| anyhow::anyhow!("legacy ESN input dimensions overflow"))?
        || !legacy.iter().all(|value| value.is_finite())
        || !companion_scale.is_finite()
        || companion_scale < 0.0
    {
        return Err(anyhow::anyhow!(
            "invalid zero-compatible ESN input migration"
        ));
    }

    let mut migrated = vec![
        0.0;
        rows.checked_mul(new_stride).ok_or_else(|| anyhow::anyhow!(
            "migrated ESN input dimensions overflow"
        ))?
    ];
    for row in 0..rows {
        let old_start = row * old_stride;
        let new_start = row * new_stride;
        migrated[new_start..new_start + old_in_size]
            .copy_from_slice(&legacy[old_start..old_start + old_in_size]);
        for column in old_in_size..new_in_size {
            migrated[new_start + column] =
                deterministic_input_weight(row, column - old_in_size, companion_scale);
        }
        migrated[new_start + new_in_size] = legacy[old_start + old_in_size];
    }
    Ok(migrated)
}

fn deterministic_input_weight(row: usize, column: usize, scale: f32) -> f32 {
    let mut value = (row as u64)
        .wrapping_mul(0xd6e8_feb8_6659_fd93)
        .wrapping_add((column as u64).wrapping_mul(0xa076_1d64_78bd_642f))
        .wrapping_add(0x4553_4e5f_5632_5f49);
    value ^= value >> 32;
    value = value.wrapping_mul(0xd6e8_feb8_6659_fd93);
    value ^= value >> 32;
    let unit = (value >> 40) as f32 / ((1_u32 << 24) - 1) as f32;
    (unit * 2.0 - 1.0) * scale
}

#[derive(Debug, Clone)]
struct EsnLeakOverride {
    leak: f32,
    remaining_ticks: u32,
    request_id: String,
}

impl EsnLeakOverride {
    fn status(&self) -> EsnLeakOverrideStatus {
        EsnLeakOverrideStatus {
            leak: self.leak,
            remaining_ticks: self.remaining_ticks,
            request_id: self.request_id.clone(),
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct EsnLeakOverrideStatus {
    pub leak: f32,
    pub remaining_ticks: u32,
    pub request_id: String,
}

//=============================================================================
// Linear Algebra Helpers
//=============================================================================

fn mv_mul(m: &[f32], rows: usize, cols: usize, v: &[f32], out: &mut [f32]) {
    for r in 0..rows {
        let mut s = 0.0f32;
        let base = r * cols;
        for c in 0..cols {
            s += m[base + c] * v[c];
        }
        out[r] = s;
    }
}

fn vv_dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn l2_norm(x: &[f32]) -> f32 {
    (x.iter().map(|v| v * v).sum::<f32>()).sqrt().max(1e-12)
}

pub fn state_rms_from_slice(x: &[f32]) -> f32 {
    if x.is_empty() {
        return 0.0;
    }
    (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt()
}

pub fn state_fingerprint_16_from_slice(x: &[f32]) -> [f32; 16] {
    let mut out = [0.0f32; 16];
    if x.is_empty() {
        return out;
    }
    let scale = (1.0 / x.len() as f32).sqrt();
    for (dim, slot) in out.iter_mut().enumerate() {
        let mut acc = 0.0f32;
        for (idx, value) in x.iter().enumerate() {
            let phase =
                ((idx + 1) as f32 * (dim + 3) as f32 * 0.137) + ((idx ^ (dim * 31)) as f32 * 0.011);
            let weight = (phase.sin() + 0.5 * phase.cos()).clamp(-1.5, 1.5);
            acc += *value * weight;
        }
        *slot = (acc * scale).tanh();
    }
    out
}

#[cfg(test)]
mod attractor_fingerprint_tests {
    use crate::gpu::Gpu;

    use super::{
        adaptive_pressure_noise_trial_review_v1, calculate_adaptive_introspection_pressure_high,
        calculate_dynamic_noise, calculate_viscous_rho_target,
        dynamic_noise_pressure_room_review_v1, entropy_ceiling_noise_damping_review_v1,
        exploration_noise_coherence_review_v1, settled_entropy_pressure_buffer_review_v1,
        state_fingerprint_16_from_slice, state_rms_from_slice, SpectralSR,
        ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY, DEFAULT_EXPLORATION_NOISE,
        DYNAMIC_EXPLORATION_NOISE_MIN, ESN, VISCOUS_RHO_CEILING, VISCOUS_RHO_FLOOR,
    };

    #[cfg(not(feature = "division-rehearsal"))]
    #[test]
    fn ordinary_step_keeps_division_trace_storage_empty_in_default_build() {
        let gpu = Gpu::new().expect("Metal device and ESN shaders should be available");
        let mut constructor_rng = fastrand::Rng::with_seed(0xD1A1_5101);
        let mut esn = ESN::new(
            16,
            6,
            0.25,
            0.15,
            0.95,
            0.35,
            0.999,
            &gpu,
            &mut constructor_rng,
        )
        .expect("ordinary ESN");

        esn.step(&[0.1, -0.1, 0.2, -0.2, 0.3, -0.3])
            .expect("ordinary step");

        assert!(esn.last_step_trace().noise.is_empty());
    }

    #[cfg(feature = "division-rehearsal")]
    #[test]
    fn rehearsal_build_records_realized_noise_for_shadow_parity() {
        let gpu = Gpu::new().expect("Metal device and ESN shaders should be available");
        let mut constructor_rng = fastrand::Rng::with_seed(0xD1A1_5102);
        let mut esn = ESN::new(
            16,
            6,
            0.25,
            0.15,
            0.95,
            0.35,
            0.999,
            &gpu,
            &mut constructor_rng,
        )
        .expect("rehearsal ESN");

        esn.step(&[0.1, -0.1, 0.2, -0.2, 0.3, -0.3])
            .expect("rehearsal step");

        assert_eq!(esn.last_step_trace().noise.len(), 16);
    }

    #[test]
    fn snapshot_v2_restores_deterministic_continuation_for_100_ticks() {
        let gpu = Gpu::new().expect("Metal device and ESN shaders should be available");
        let mut constructor_rng = fastrand::Rng::with_seed(0xD1A1_5100);
        let mut parent = ESN::new(
            16,
            6,
            0.25,
            0.15,
            0.95,
            0.35,
            0.999,
            &gpu,
            &mut constructor_rng,
        )
        .expect("parent ESN");
        // Executable-bundle qualification uses the synchronous rank-one path
        // so GPU queue timing cannot become part of the continuation contract.
        parent.set_profiling_enabled(true);
        for tick in 0..24 {
            let input: Vec<f32> = (0..6)
                .map(|index| ((tick * 7 + index * 3) as f32 * 0.071).sin())
                .collect();
            parent.step(&input).expect("warm parent");
        }
        let snapshot = parent.snapshot_v2().expect("complete v2 snapshot");
        let mut restored = ESN::from_snapshot_v2(&snapshot, &gpu).expect("restore v2 snapshot");

        let mut max_abs = 0.0_f32;
        let mut first_divergence = None;
        let mut max_noise_delta = 0.0_f32;
        let mut max_leak_delta = 0.0_f32;
        for tick in 0..100 {
            let input: Vec<f32> = (0..6)
                .map(|index| ((tick * 11 + index * 5) as f32 * 0.043).cos())
                .collect();
            parent.step(&input).expect("parent continuation");
            restored.step(&input).expect("restored continuation");
            max_leak_delta = max_leak_delta
                .max((parent.last_step_trace.leak - restored.last_step_trace.leak).abs());
            for (left, right) in parent
                .last_step_trace
                .noise
                .iter()
                .zip(&restored.last_step_trace.noise)
            {
                max_noise_delta = max_noise_delta.max((left - right).abs());
            }
            for (left, right) in parent.x.iter().zip(&restored.x) {
                let delta = (left - right).abs();
                if delta > 1.0e-6 && first_divergence.is_none() {
                    first_divergence = Some(tick);
                }
                max_abs = max_abs.max(delta);
            }
        }
        assert!(
            max_abs <= 1.0e-6,
            "100-tick restored continuation diverged: max_abs={max_abs} first_tick={first_divergence:?} noise_delta={max_noise_delta} leak_delta={max_leak_delta}"
        );
    }

    #[test]
    fn migrated_78d_checkpoint_is_exact_at_zero_companion_mix() {
        use crate::semantic_body_v2::{
            reservoir_input_v2, LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1,
            RESERVOIR_INPUT_DIMENSIONS_V2, SEMANTIC_BODY_COMPANION_DIMENSIONS_V2,
        };

        let gpu = Gpu::new().expect("Metal device and ESN shaders should be available");
        let mut constructor_rng = fastrand::Rng::with_seed(0x5345_4d42_4f44_5932);
        let mut seed = ESN::new(
            16,
            LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1,
            0.25,
            0.15,
            0.95,
            0.35,
            0.999,
            &gpu,
            &mut constructor_rng,
        )
        .expect("legacy ESN");
        seed.set_profiling_enabled(true);
        let legacy_snapshot = seed.snapshot_v2().expect("legacy snapshot");
        let migrated_snapshot = legacy_snapshot
            .migrate_input_zero_compatible(RESERVOIR_INPUT_DIMENSIONS_V2, 0.5)
            .expect("migrated snapshot");
        let mut legacy = ESN::from_snapshot_v2(&legacy_snapshot, &gpu).expect("legacy restore");
        let mut migrated =
            ESN::from_snapshot_v2(&migrated_snapshot, &gpu).expect("migrated restore");
        let companion = [0.75; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2];

        for tick in 0..100 {
            let input =
                std::array::from_fn::<_, LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1, _>(|index| {
                    ((tick * 11 + index * 5) as f32 * 0.043).cos()
                });
            let input_v2 = reservoir_input_v2(&input, &companion, 0.0).expect("zero mix");
            legacy.step(&input).expect("legacy step");
            migrated.step(&input_v2).expect("migrated step");
            for (before, after) in legacy.x.iter().zip(&migrated.x) {
                assert_eq!(before.to_bits(), after.to_bits());
            }
        }
    }

    #[test]
    fn gpu_rank1_ewma_matches_cpu_reference_across_updates() {
        let gpu = Gpu::new().expect("Metal device and ESN shaders should be available");
        let rho = 0.91_f32;
        let mut spectral = SpectralSR::new(4, rho, &gpu).expect("spectral test instance");
        let first = [0.25_f32, -0.50, 0.75, -0.10];
        let second = [-0.40_f32, 0.20, 0.60, 0.80];
        let mut expected = vec![0.0_f32; 16];

        spectral
            .rank1_ewma(&first)
            .expect("first GPU rank-one update");
        for row in 0..4 {
            for column in 0..4 {
                expected[row * 4 + column] = (1.0 - rho) * first[row] * first[column];
            }
        }
        let first_gpu = gpu.read_f32(&spectral.cov, 16);
        for (idx, (observed, reference)) in first_gpu.iter().zip(&expected).enumerate() {
            assert!(
                (observed - reference).abs() <= 1.0e-6,
                "first rank-one update diverged at {idx}: gpu={observed} cpu={reference}"
            );
        }

        spectral
            .rank1_ewma(&second)
            .expect("second GPU rank-one update");
        for row in 0..4 {
            for column in 0..4 {
                let idx = row * 4 + column;
                expected[idx] = rho * expected[idx] + (1.0 - rho) * second[row] * second[column];
            }
        }
        let second_gpu = gpu.read_f32(&spectral.cov, 16);
        for (idx, (observed, reference)) in second_gpu.iter().zip(&expected).enumerate() {
            assert!(
                (observed - reference).abs() <= 1.0e-6,
                "second rank-one update diverged at {idx}: gpu={observed} cpu={reference}"
            );
        }
    }

    #[test]
    fn dynamic_noise_allows_more_vibrancy_on_gentle_gradient_low_pressure() {
        let noise = calculate_dynamic_noise(0.11, 0.22);

        assert!(noise > DEFAULT_EXPLORATION_NOISE);
        assert!(noise <= 0.12);
        assert!(noise >= 0.11);
    }

    #[test]
    fn dynamic_noise_scales_down_for_steep_gradient_or_pressure() {
        let gentle = calculate_dynamic_noise(0.11, 0.22);
        let steep_gradient = calculate_dynamic_noise(0.80, 0.22);
        let steep_and_pressured = calculate_dynamic_noise(0.80, 0.65);
        let fallback = calculate_dynamic_noise(f32::NAN, f32::INFINITY);

        assert!(steep_gradient < gentle);
        assert!(steep_gradient <= DEFAULT_EXPLORATION_NOISE);
        assert!(steep_and_pressured <= steep_gradient);
        assert!((0.06..=0.12).contains(&fallback));
    }

    #[test]
    fn dynamic_noise_high_pressure_gentle_gradient_stays_bounded() {
        let low_pressure = calculate_dynamic_noise(0.10, 0.10);
        let high_pressure = calculate_dynamic_noise(0.10, 0.90);

        assert!((0.06..=0.12).contains(&high_pressure));
        assert!(high_pressure < low_pressure);
        assert!(high_pressure >= 0.06);
    }

    #[test]
    fn dynamic_noise_pressure_room_review_softens_current_pressure_slope() {
        let review = dynamic_noise_pressure_room_review_v1(0.11, 0.22, 0.90);

        assert_eq!(review.policy, "dynamic_noise_pressure_room_review_v1");
        assert_eq!(review.status, "gentle_pressure_room_slope");
        assert!(review.pressure_window_position > 0.0);
        assert!(review.pressure_window_position < 1.0);
        assert!(review.smoothed_pressure_room > review.linear_pressure_room);
        assert!(review.dynamic_noise > DEFAULT_EXPLORATION_NOISE);
        assert!((review.entropy_floor_delta).abs() < 1.0e-6);
        assert_eq!(
            review.authority,
            "read_only_pressure_room_review_not_live_exploration_noise_or_rho_change"
        );
    }

    #[test]
    fn dynamic_noise_gradient_room_uses_smooth_knee_instead_of_linear_drop() {
        let review = dynamic_noise_pressure_room_review_v1(0.35, 0.10, 0.50);

        assert!(review.gradient_window_position > 0.0);
        assert!(review.gradient_window_position < 1.0);
        assert!(
            review.smoothed_gradient_room > review.linear_gradient_room,
            "mid-gentle gradient should ease down rather than drop linearly: {review:?}"
        );
        assert!(review.dynamic_noise <= 0.12);
    }

    #[test]
    fn dynamic_noise_pressure_room_review_keeps_requested_mid_pressure_gentle() {
        let review = dynamic_noise_pressure_room_review_v1(0.20, 0.35, 0.90);

        assert_eq!(review.status, "gentle_pressure_room_slope");
        assert!(review.pressure_window_position > 0.0);
        assert!(review.pressure_window_position < 1.0);
        assert!(
            review.smoothed_pressure_room > review.linear_pressure_room,
            "pressure_risk=0.35 should be eased as a slope, not snapped shut: {review:?}"
        );
        assert!(review.dynamic_noise > DYNAMIC_EXPLORATION_NOISE_MIN);
        assert_eq!(
            review.authority,
            "read_only_pressure_room_review_not_live_exploration_noise_or_rho_change"
        );
    }

    #[test]
    fn dynamic_noise_requested_mid_gradient_pressure_preserves_bounded_room() {
        let requested = calculate_dynamic_noise(0.50, 0.35);
        let steeper = calculate_dynamic_noise(0.80, 0.35);
        let lower_pressure = calculate_dynamic_noise(0.50, 0.10);

        assert!(
            requested > DYNAMIC_EXPLORATION_NOISE_MIN,
            "the reported 0.50/0.35 edge should retain some exploration room"
        );
        assert!(
            requested < DEFAULT_EXPLORATION_NOISE,
            "mid gradient plus mid pressure should soften below the default without collapsing to minimum: {requested}"
        );
        assert!(
            steeper < requested,
            "steeper density gradient should reduce room at the same pressure: requested={requested}, steeper={steeper}"
        );
        assert!(
            lower_pressure > requested,
            "lower pressure should leave more room at the same gradient: requested={requested}, lower_pressure={lower_pressure}"
        );
        assert!(
            (requested - 0.08197).abs() < 0.0002,
            "exact reported scalar drifted: {requested}"
        );
    }

    #[test]
    fn dynamic_noise_pressure_room_start_edge_is_continuous() {
        let below = dynamic_noise_pressure_room_review_v1(0.11, 0.17, 0.90);
        let just_inside = dynamic_noise_pressure_room_review_v1(0.11, 0.19, 0.90);

        assert_eq!(below.status, "full_pressure_room_below_start");
        assert_eq!(just_inside.status, "gentle_pressure_room_slope");
        assert!(below.pressure_window_position <= f32::EPSILON);
        assert!(just_inside.pressure_window_position > 0.0);
        assert!(
            (below.dynamic_noise - just_inside.dynamic_noise).abs() < 0.002,
            "pressure room should open as a smooth edge, not a jump: below={below:?} inside={just_inside:?}"
        );
        assert_eq!(
            just_inside.authority,
            "read_only_pressure_room_review_not_live_exploration_noise_or_rho_change"
        );
    }

    #[test]
    fn adaptive_introspection_threshold_softens_only_for_volatile_low_gradient_states() {
        let ordinary = calculate_adaptive_introspection_pressure_high(0.70, 0.10);
        let volatile_open = calculate_adaptive_introspection_pressure_high(0.90, 0.10);
        let volatile_steep = calculate_adaptive_introspection_pressure_high(0.90, 0.90);
        let saturated = calculate_adaptive_introspection_pressure_high(1.0, 0.0);
        let fallback = calculate_adaptive_introspection_pressure_high(f32::NAN, f32::INFINITY);

        assert_eq!(ordinary, 2.0);
        assert!(volatile_open < ordinary);
        assert!(volatile_steep > volatile_open);
        assert!(saturated >= 1.5);
        assert!(saturated <= 2.0);
        assert_eq!(fallback, 2.0);
    }

    #[test]
    fn viscous_rho_target_preserves_memory_for_high_entropy_low_gradient_states() {
        let ordinary = calculate_viscous_rho_target(0.86, 0.70, 0.18);
        let volatile_open = calculate_viscous_rho_target(0.86, 0.91, 0.18);
        let volatile_steep = calculate_viscous_rho_target(0.86, 0.91, 0.92);
        let already_viscous = calculate_viscous_rho_target(0.94, 0.91, 0.18);
        let fallback = calculate_viscous_rho_target(f32::NAN, f32::NAN, f32::INFINITY);

        assert_eq!(ordinary, 0.86);
        assert!(volatile_open > ordinary);
        assert!(volatile_open >= 0.90);
        assert!(volatile_steep < volatile_open);
        assert!(already_viscous >= 0.94);
        assert!(already_viscous <= 0.95);
        assert_eq!(fallback, 0.90);
    }

    #[test]
    fn viscous_rho_target_moves_high_entropy_low_gradient_toward_ceiling() {
        let current = 0.86;
        let target = calculate_viscous_rho_target(current, 0.90, 0.10);

        assert!(target > current);
        assert!(target >= VISCOUS_RHO_FLOOR);
        assert!(
            VISCOUS_RHO_CEILING - target < VISCOUS_RHO_CEILING - current,
            "high entropy with low density gradient should move rho toward the viscous ceiling"
        );
        assert!(target <= VISCOUS_RHO_CEILING);
    }

    #[test]
    fn viscous_rho_target_threshold_edge_does_not_jump() {
        let current = 0.86;
        let at_threshold =
            calculate_viscous_rho_target(current, ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY, 0.10);
        let just_above = calculate_viscous_rho_target(
            current,
            ADAPTIVE_INTROSPECTION_VOLATILE_ENTROPY + 0.01,
            0.10,
        );

        assert_eq!(
            at_threshold, current,
            "the volatile-entropy threshold edge should not silently jump rho"
        );
        assert!(
            just_above >= VISCOUS_RHO_FLOOR,
            "only entropy above the threshold should lift toward the viscous review floor"
        );
        assert!(just_above <= VISCOUS_RHO_CEILING);
    }

    /// Astrid introspection (introspection_minime_esn_1787970235) proposed as its
    /// Test 1: verify `calculate_viscous_rho_target` produces a "monotonic response
    /// to increasing spectral density within the bounds of VISCOUS_RHO_FLOOR and
    /// VISCOUS_RHO_CEILING." The existing viscous tests cover point cases and a
    /// two-point directional check (`volatile_steep < volatile_open`); this sweeps
    /// each input over a monotone increasing sequence to assert true monotonicity
    /// and that every volatile-branch output stays inside the viscous review band.
    #[test]
    fn viscous_rho_target_monotonic_and_bounded_across_density_and_entropy_sweeps() {
        let eps = 1e-6_f32;
        let current = 0.86_f32;

        // Sweep 1: increasing density gradient at fixed high (volatile) entropy.
        // A higher density gradient consumes navigable room (1.0 - gradient), so the
        // viscous lift shrinks: the rho target is monotonically NON-INCREASING in the
        // gradient, and because entropy stays above the volatile threshold every value
        // stays within [VISCOUS_RHO_FLOOR, VISCOUS_RHO_CEILING].
        let entropy_high = 0.95_f32;
        let gradients = [0.0_f32, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];
        let mut prev: Option<f32> = None;
        for &gradient in &gradients {
            let target = calculate_viscous_rho_target(current, entropy_high, gradient);
            assert!(
                target >= VISCOUS_RHO_FLOOR - eps && target <= VISCOUS_RHO_CEILING + eps,
                "gradient {gradient}: target {target} left the viscous band"
            );
            if let Some(p) = prev {
                assert!(
                    target <= p + eps,
                    "gradient {gradient}: target {target} rose above previous {p} as density gradient increased"
                );
            }
            prev = Some(target);
        }

        // Sweep 2: increasing spectral entropy at fixed low density gradient. Below the
        // volatile-entropy threshold the target holds at `current`; above it the lift
        // grows, so the target is monotonically NON-DECREASING and never exceeds the
        // ceiling. (The below-threshold branch legitimately sits under the floor, so
        // only the ceiling bound is asserted across this sweep.)
        let gradient_low = 0.10_f32;
        let entropies = [
            0.80_f32, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 1.00,
        ];
        let mut prev: Option<f32> = None;
        for &entropy in &entropies {
            let target = calculate_viscous_rho_target(current, entropy, gradient_low);
            assert!(
                target <= VISCOUS_RHO_CEILING + eps,
                "entropy {entropy}: target {target} exceeded the viscous ceiling"
            );
            if let Some(p) = prev {
                assert!(
                    target >= p - eps,
                    "entropy {entropy}: target {target} fell below previous {p} as entropy increased"
                );
            }
            prev = Some(target);
        }
    }

    #[test]
    fn exploration_noise_coherence_review_keeps_gentle_gradient_watch_bounded() {
        let gentle = exploration_noise_coherence_review_v1(0.11, 0.22, 0.90, 0.74);
        let steep = exploration_noise_coherence_review_v1(0.80, 0.65, 0.90, 0.74);

        assert_eq!(gentle.policy, "exploration_noise_coherence_review_v1");
        assert_eq!(
            gentle.status,
            "gentle_gradient_high_entropy_coherence_watch"
        );
        assert!(gentle.dynamic_noise > DEFAULT_EXPLORATION_NOISE);
        assert!(gentle.dynamic_noise <= 0.12);
        assert_eq!(
            gentle.authority,
            "read_only_noise_review_not_live_exploration_noise_change"
        );
        assert_eq!(
            steep.status,
            "noise_room_reduced_by_steep_gradient_or_pressure"
        );
        assert!(steep.dynamic_noise < gentle.dynamic_noise);
        assert!(steep.dynamic_noise <= DEFAULT_EXPLORATION_NOISE);
    }

    #[test]
    fn adaptive_pressure_noise_trial_review_gates_threshold_and_noise_changes() {
        let review = adaptive_pressure_noise_trial_review_v1(0.88, 0.10, 0.30, 0.12, 0.90);

        assert_eq!(review.policy, "adaptive_pressure_noise_trial_review_v1");
        assert_eq!(review.status, "approval_required_pressure_and_noise_trial");
        assert_eq!(review.current_pressure_threshold, 2.0);
        assert_eq!(review.proposed_pressure_threshold, 1.80);
        assert_eq!(review.proposed_exploration_noise, 0.08);
        assert!(review.preview_pressure_threshold < review.current_pressure_threshold);
        assert!(review.viscous_rho_target >= review.current_rho);
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert_eq!(
            review.approval_boundary,
            "live_exploration_noise_rho_and_adaptive_pressure_threshold"
        );
        assert_eq!(
            review.authority,
            "authority_gate_not_live_esn_pressure_noise_or_rho_change"
        );
    }

    #[test]
    fn settled_entropy_pressure_buffer_review_gates_requested_floor_change() {
        let review = settled_entropy_pressure_buffer_review_v1(0.88, 0.10, 0.19, 0.71);

        assert_eq!(review.policy, "settled_entropy_pressure_buffer_review_v1");
        assert_eq!(
            review.status,
            "approval_required_settled_entropy_pressure_floor_trial"
        );
        assert!(review.pressure_window_position > 0.0);
        assert!(review.pressure_window_position < 0.20);
        assert_eq!(review.current_pressure_high_floor, 1.5);
        assert_eq!(review.requested_pressure_high_floor, 1.75);
        assert!(
            review.requested_floor_preview_pressure_threshold
                > review.current_preview_pressure_threshold,
            "raising the floor should preview a wider buffer without applying it: {review:?}"
        );
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert_eq!(
            review.approval_boundary,
            "live_adaptive_introspection_pressure_floor_and_exploration_noise"
        );
        assert_eq!(
            review.authority,
            "read_only_review_not_live_esn_pressure_floor_noise_or_rho_change"
        );
    }

    #[test]
    fn entropy_ceiling_noise_damping_review_names_088_under_proposed_ceiling() {
        let review = entropy_ceiling_noise_damping_review_v1(0.88, 0.10, 0.24, 0.30, 0.35, 0.12);

        assert_eq!(review.policy, "entropy_ceiling_noise_damping_review_v1");
        assert_eq!(
            review.status,
            "approval_required_entropy_ceiling_and_density_noise_damping_trial"
        );
        assert_eq!(review.current_volatile_entropy, 0.85);
        assert_eq!(review.proposed_volatile_entropy, 0.92);
        assert!(review.entropy_excess_over_current > 0.0);
        assert!(review.entropy_margin_under_proposed > 0.0);
        assert!(review.density_containment_damping_need > 0.25);
        assert!(review.density_containment_damped_noise < review.dynamic_noise);
        assert!(review.density_containment_damped_noise < review.active_exploration_noise);
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert_eq!(
            review.approval_boundary,
            "live_exploration_noise_entropy_threshold_and_density_damping"
        );
        assert_eq!(
            review.authority,
            "authority_gate_not_live_esn_entropy_threshold_noise_or_rho_change"
        );
    }

    #[test]
    fn entropy_ceiling_noise_damping_review_stays_observational_when_contained() {
        let review = entropy_ceiling_noise_damping_review_v1(0.82, 0.40, 0.50, 0.82, 0.90, 0.085);

        assert_eq!(review.status, "read_only_entropy_noise_observation");
        assert!(!review.live_control_required);
        assert_eq!(review.entropy_excess_over_current, 0.0);
        assert!(review.density_containment_damping_need <= 0.01);
        assert_eq!(
            review.authority,
            "authority_gate_not_live_esn_entropy_threshold_noise_or_rho_change"
        );
    }

    #[test]
    fn state_fingerprint_16_is_deterministic_bounded_and_sensitive() {
        let first_state = vec![0.25f32; 128];
        let mut second_state = first_state.clone();
        second_state[17] = -0.5;
        let first = state_fingerprint_16_from_slice(&first_state);
        let repeated = state_fingerprint_16_from_slice(&first_state);
        let second = state_fingerprint_16_from_slice(&second_state);

        assert_eq!(first.len(), 16);
        assert_eq!(first, repeated);
        assert_ne!(first, second);
        assert!(first.iter().all(|value| value.abs() <= 1.0));
        assert!(state_rms_from_slice(&first_state) > 0.0);
    }
}
