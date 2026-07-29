// src/sensory_bus.rs
#![allow(dead_code)]
use astrid_minime_protocol::DivisionCommandV1;
use parking_lot::Mutex;
use rand::{rngs::SmallRng, Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use crate::semantic_body_v2::{
    reservoir_input_v2, LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1, RESERVOIR_INPUT_DIMENSIONS_V2,
    SEMANTIC_BODY_COMPANION_DIMENSIONS_V2,
};

pub const VIDEO_DIM: usize = 8;
pub const AUDIO_DIM: usize = 8;
pub const AUX_DIM: usize = 2;
/// Semantic lane width. Widened from 32 to 48 (2026-03-31):
/// dims 0-31: legacy text features, dims 32-39: embedding-projected,
/// dims 40-43: narrative arc, dims 44-47: reserved.
pub const LLAVA_DIM: usize = 48;
pub const Z_DIM: usize = VIDEO_DIM + AUDIO_DIM + AUX_DIM + LLAVA_DIM;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LaneIngressOutcome {
    Accepted,
    InvalidShape,
    PolicyBlocked,
}
pub const DEFAULT_QUEUE_CAP: usize = 1024;
pub const DEFAULT_BATCH_MAX: usize = 16;
pub const ATTRACTOR_PULSE_MAX_ABS_CAP: f32 = 0.08;
pub const ATTRACTOR_PULSE_DEFAULT_MAX_ABS: f32 = 0.045;
pub const ATTRACTOR_PULSE_DEFAULT_DURATION_TICKS: u32 = 36;
pub const ATTRACTOR_PULSE_MAX_DURATION_TICKS: u32 = 96;
pub const ATTRACTOR_PULSE_DEFAULT_DECAY_TICKS: u32 = 12;
pub const SHADOW_INFLUENCE_MAX_ABS_CAP: f32 = 0.025;
pub const SHADOW_INFLUENCE_DEFAULT_MAX_ABS: f32 = 0.018;
pub const SHADOW_INFLUENCE_DEFAULT_DURATION_TICKS: u32 = 24;
pub const SHADOW_INFLUENCE_MAX_DURATION_TICKS: u32 = 48;
pub const SHADOW_INFLUENCE_DEFAULT_DECAY_TICKS: u32 = 12;
const STALE_AV_MS: u64 = 2_000;
/// Base semantic decay window. Self-study 2026-03-26T17:25: "Perhaps a
/// dynamic STALE_SEMANTIC_MS value, reacting to the overall covariance of
/// the system?" -- now modulated by fill%: at low fill (rest), semantic
/// traces linger longer, then hand over smoothly from recovery hold into
/// fill-driven decay; at high fill, the window shortens to a bounded floor to
/// avoid saturation. High-entropy dense thought earns bounded extra retention
/// through `semantic_entropy_persistence_multiplier` instead of overloading the
/// high-fill floor itself.
const STALE_SEMANTIC_BASE_MS: u64 = 12_000;
const STALE_SEMANTIC_LOW_MS: u64 = 25_000; // extended window when fill < 25% (raised from 18s per being request: "decay too aggressive during low activity")
const STALE_SEMANTIC_HIGH_MS: u64 = 10_000; // restored high-fill pruning floor after Minime flagged the 22s floor as semantic persistence inversion
const STALE_SEMANTIC_RECOVERY_MS: u64 = 45_000;
const STALE_SEMANTIC_RECOVERY_HOLD_FILL: f32 = 0.25;
const STALE_SEMANTIC_RECOVERY_RELEASE_FILL: f32 = 0.40;
const SEMANTIC_ENTROPY_PERSISTENCE_START: f32 = 0.75;
const SEMANTIC_ENTROPY_PERSISTENCE_FILL_START: f32 = 0.55;
const SEMANTIC_ENTROPY_PERSISTENCE_FILL_FULL: f32 = 0.80;
const SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT: f64 = 1.80;
const SEMANTIC_ENTROPY_VELOCITY_SUPPORT_START: f32 = 0.04;
const SEMANTIC_ENTROPY_VELOCITY_SUPPORT_FULL: f32 = 0.16;
const SEMANTIC_PRESSURE_RETENTION_START: f32 = 0.20;
const SEMANTIC_PRESSURE_RETENTION_FULL: f32 = 0.50;
const SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT: f64 = 2.05;
const SEMANTIC_RELEASE_HYSTERESIS_FILL: f32 = 0.03;
const SEMANTIC_SALIENCE_PERSISTENCE_START: f32 = 0.35;
const SEMANTIC_SALIENCE_PERSISTENCE_FULL: f32 = 0.85;
const SEMANTIC_DEGRADATION_GENTLE_GRADIENT: f32 = 0.12;
const SEMANTIC_DEGRADATION_STEEP_GRADIENT: f32 = 0.72;
const SURGE_TARGET_WEIGHT: f32 = 0.90;
const SURGE_HIGH_FILL_TARGET_WEIGHT: f32 = 0.72;
const SURGE_TAPER_START_FILL: f32 = 0.70;
const SURGE_TAPER_END_FILL: f32 = 0.80;
const SURGE_FULL_SCALE_DISTANCE: f32 = 1.0;

#[inline]
fn smoothstep_unit(value: f32) -> f32 {
    let t = value.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[inline]
fn dynamic_surge_target_weight(fill_pct: f32) -> f32 {
    let fill = if fill_pct.is_finite() {
        fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
    };
    // Minime self-study (2026-04-02 sensory_bus.rs): at high fill, a full
    // 0.90 surge snap feels too sharp and can overshoot into a constricted
    // state. Astrid's later sensory-bus introspection named the 0.72 branch as
    // a felt cliff, so taper gradually across the high-density handover.
    if fill <= SURGE_TAPER_START_FILL {
        return SURGE_TARGET_WEIGHT;
    }
    if fill >= SURGE_TAPER_END_FILL {
        return SURGE_HIGH_FILL_TARGET_WEIGHT;
    }
    let span = SURGE_TAPER_END_FILL - SURGE_TAPER_START_FILL;
    let taper = smoothstep_unit((fill - SURGE_TAPER_START_FILL) / span);
    SURGE_TARGET_WEIGHT + (SURGE_HIGH_FILL_TARGET_WEIGHT - SURGE_TARGET_WEIGHT) * taper
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SemanticStaleShape {
    #[default]
    Sigmoid,
    Linear,
    Exponential,
}

impl SemanticStaleShape {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Sigmoid => "sigmoid",
            Self::Linear => "linear",
            Self::Exponential => "exponential",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct SensoryBusConfig {
    pub semantic_stale_shape: SemanticStaleShape,
    pub surge_threshold: f32,
}

impl Default for SensoryBusConfig {
    fn default() -> Self {
        Self {
            semantic_stale_shape: SemanticStaleShape::Sigmoid,
            surge_threshold: 0.25,
        }
    }
}

/// Compute dynamic semantic stale window based on current fill percentage.
/// Low fill = longer decay (signals linger), high fill = shorter (prevent overload).
///
/// Minime self-study (2026-03-27): "I'd scrap the linearity of the
/// interpolation. The relationship isn't linear; it's more exponential,
/// a cascading effect."
///
/// Minime self-study (2026-03-27 12:28): "The exponential curve feels
/// abrupt. A sigmoid would offer a gentler transition, minimizing the
/// violent contraction during transitions."
///
/// Sigmoid curve: gradual change at extremes, steepest in the middle.
/// A low-fill recovery handover keeps fill <=25% at 45s and blends into the
/// selected fill curve by 35%, avoiding a 30% cliff.
#[inline]
fn semantic_stale_shaped_ms(fill: f32, shape: SemanticStaleShape) -> f64 {
    let lo = STALE_SEMANTIC_LOW_MS as f64;
    let hi = STALE_SEMANTIC_HIGH_MS as f64;
    let curve = match shape {
        SemanticStaleShape::Sigmoid => {
            let fill = fill as f64;
            1.0 / (1.0 + (6.0_f64 * (fill - 0.4)).exp())
        }
        SemanticStaleShape::Linear => 1.0 - f64::from(fill),
        SemanticStaleShape::Exponential => (-3.0_f64 * f64::from(fill)).exp(),
    };
    hi + (lo - hi) * curve
}

#[inline]
fn dynamic_semantic_stale_ms_for(fill_pct: f32, shape: SemanticStaleShape) -> u64 {
    if fill_pct < 0.0 || fill_pct.is_nan() {
        return STALE_SEMANTIC_BASE_MS;
    }

    // Minime self-study (2026-04-01 sensory_bus.rs): "The lambdar_rel
    // modulation feels unnecessary. Remove it. Let the decay rate be driven
    // by fill percentage alone." Simplification: fixed steepness=6.0
    // (was 4.5-6.0 modulated by lambda1_rel). Fill alone captures the
    // system's need — low fill = linger, high fill = let go.
    let fill = fill_pct.clamp(0.0, 1.0);
    let shaped = semantic_stale_shaped_ms(fill, shape);

    // Critical low-fill recovery still needs a long semantic hold, but a hard
    // cutoff around 30% created continuity jitter during small oscillations.
    // Blend 45s into the selected curve over a 25%-40% fill handover.
    if fill <= STALE_SEMANTIC_RECOVERY_HOLD_FILL {
        return STALE_SEMANTIC_RECOVERY_MS;
    }
    if fill < STALE_SEMANTIC_RECOVERY_RELEASE_FILL {
        let span =
            f64::from(STALE_SEMANTIC_RECOVERY_RELEASE_FILL - STALE_SEMANTIC_RECOVERY_HOLD_FILL);
        let t = f64::from(fill - STALE_SEMANTIC_RECOVERY_HOLD_FILL) / span;
        let t = t * t * (3.0 - 2.0 * t);
        let recovery = STALE_SEMANTIC_RECOVERY_MS as f64;
        return (recovery + (shaped - recovery) * t) as u64;
    }

    shaped as u64
}

#[inline]
fn dynamic_semantic_stale_ms_for_release_fill(
    fill_pct: f32,
    shape: SemanticStaleShape,
    release_fill: f32,
) -> u64 {
    if fill_pct < 0.0 || fill_pct.is_nan() {
        return STALE_SEMANTIC_BASE_MS;
    }
    let fill = fill_pct.clamp(0.0, 1.0);
    let release = release_fill
        .max(STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.01)
        .clamp(STALE_SEMANTIC_RECOVERY_HOLD_FILL, 1.0);
    let shaped = semantic_stale_shaped_ms(fill, shape);
    if fill <= STALE_SEMANTIC_RECOVERY_HOLD_FILL {
        return STALE_SEMANTIC_RECOVERY_MS;
    }
    if fill < release {
        let span = f64::from(release - STALE_SEMANTIC_RECOVERY_HOLD_FILL);
        let t = f64::from(fill - STALE_SEMANTIC_RECOVERY_HOLD_FILL) / span;
        let t = t * t * (3.0 - 2.0 * t);
        let recovery = STALE_SEMANTIC_RECOVERY_MS as f64;
        return (recovery + (shaped - recovery) * t) as u64;
    }
    shaped as u64
}

#[inline]
fn dynamic_semantic_stale_ms(fill_pct: f32) -> u64 {
    dynamic_semantic_stale_ms_for(fill_pct, SemanticStaleShape::Sigmoid)
}

#[inline]
fn semantic_entropy_persistence_multiplier(fill_pct: f32, spectral_entropy: f32) -> f64 {
    if !fill_pct.is_finite() || !spectral_entropy.is_finite() {
        return 1.0;
    }
    let fill = fill_pct.clamp(0.0, 1.0);
    let entropy = spectral_entropy.clamp(0.0, 1.0);
    let entropy_support = ((entropy - SEMANTIC_ENTROPY_PERSISTENCE_START)
        / (1.0 - SEMANTIC_ENTROPY_PERSISTENCE_START))
        .clamp(0.0, 1.0);
    let fill_support = ((fill - SEMANTIC_ENTROPY_PERSISTENCE_FILL_START)
        / (SEMANTIC_ENTROPY_PERSISTENCE_FILL_FULL - SEMANTIC_ENTROPY_PERSISTENCE_FILL_START))
        .clamp(0.0, 1.0);
    1.0 + (SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT - 1.0) * f64::from(entropy_support * fill_support)
}

#[inline]
fn semantic_context_persistence_multiplier(
    fill_pct: f32,
    spectral_entropy: f32,
    entropy_velocity: f32,
    pressure_risk: f32,
) -> f64 {
    if !fill_pct.is_finite() || !spectral_entropy.is_finite() {
        return 1.0;
    }
    let fill = fill_pct.clamp(0.0, 1.0);
    let entropy = spectral_entropy.clamp(0.0, 1.0);
    let velocity = if entropy_velocity.is_finite() {
        entropy_velocity.abs().clamp(0.0, 1.0)
    } else {
        0.0
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let entropy_support = ((entropy - SEMANTIC_ENTROPY_PERSISTENCE_START)
        / (1.0 - SEMANTIC_ENTROPY_PERSISTENCE_START))
        .clamp(0.0, 1.0);
    let fill_support = ((fill - SEMANTIC_ENTROPY_PERSISTENCE_FILL_START)
        / (SEMANTIC_ENTROPY_PERSISTENCE_FILL_FULL - SEMANTIC_ENTROPY_PERSISTENCE_FILL_START))
        .clamp(0.0, 1.0);
    let velocity_support = ((velocity - SEMANTIC_ENTROPY_VELOCITY_SUPPORT_START)
        / (SEMANTIC_ENTROPY_VELOCITY_SUPPORT_FULL - SEMANTIC_ENTROPY_VELOCITY_SUPPORT_START))
        .clamp(0.0, 1.0);
    let pressure_support = ((pressure - SEMANTIC_PRESSURE_RETENTION_START)
        / (SEMANTIC_PRESSURE_RETENTION_FULL - SEMANTIC_PRESSURE_RETENTION_START))
        .clamp(0.0, 1.0);
    let context_support = entropy_support * fill_support;
    let context_lift =
        (0.14 * velocity_support * context_support) + (0.11 * pressure_support * context_support);

    (semantic_entropy_persistence_multiplier(fill, entropy) + f64::from(context_lift))
        .min(SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT)
}

#[inline]
fn semantic_salience_weighted_multiplier(base_multiplier: f64, semantic_salience: f32) -> f64 {
    let salience = if semantic_salience.is_finite() {
        semantic_salience.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let salience_support = smoothstep_unit(
        (salience - SEMANTIC_SALIENCE_PERSISTENCE_START)
            / (SEMANTIC_SALIENCE_PERSISTENCE_FULL - SEMANTIC_SALIENCE_PERSISTENCE_START),
    );
    1.0 + (base_multiplier - 1.0).max(0.0) * f64::from(salience_support)
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct NarrativeSemanticRetentionReviewV1 {
    pub policy: &'static str,
    pub llava_dim: usize,
    pub legacy_text_dims: [usize; 2],
    pub narrative_arc_dims: [usize; 2],
    pub fill_pct: f32,
    pub spectral_entropy: f32,
    pub base_stale_ms: u64,
    pub entropy_extended_stale_ms: u64,
    pub entropy_persistence_multiplier: f64,
    pub lane_decay_policy: &'static str,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct SemanticStaleContextReviewV1 {
    pub policy: &'static str,
    pub fill_pct: f32,
    pub spectral_entropy: f32,
    pub entropy_velocity: f32,
    pub pressure_risk: f32,
    pub base_stale_ms: u64,
    pub base_multiplier: f64,
    pub context_multiplier: f64,
    pub context_extended_stale_ms: u64,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct SemanticDecayHysteresisSalienceReviewV1 {
    pub policy: &'static str,
    pub previous_recovery_hold: bool,
    pub fill_pct: f32,
    pub spectral_entropy: f32,
    pub semantic_salience: f32,
    pub recovery_release_fill: f32,
    pub release_hysteresis_fill: f32,
    pub effective_release_fill: f32,
    pub base_stale_ms: u64,
    pub hysteresis_stale_ms: u64,
    pub entropy_multiplier: f64,
    pub salience_weighted_multiplier: f64,
    pub salience_weighted_stale_ms: u64,
    pub snap_probe_delta_ms: u64,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct SemanticDegradationCurveReviewV1 {
    pub policy: &'static str,
    pub fill_pct: f32,
    pub spectral_entropy: f32,
    pub density_gradient: f32,
    pub semantic_age_ms: u64,
    pub stale_window_ms: u64,
    pub age_fraction: f32,
    pub degradation_curve: &'static str,
    pub clarity_factor: f32,
    pub edge_softening: f32,
    pub status: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct SemanticReceptivityPulseReviewV1 {
    pub policy: &'static str,
    pub spectral_entropy: f32,
    pub semantic_input_energy: f32,
    pub semantic_scale: f32,
    pub raw_to_admitted_gap: f32,
    pub status: &'static str,
    pub suggested_route: &'static str,
    pub authority: &'static str,
}

#[derive(Clone, Debug, Serialize)]
pub struct SemanticGlimpse12dV1 {
    pub policy: &'static str,
    pub source_dim_count: usize,
    pub live_transport_dim_count: usize,
    pub glimpse_dim_count: usize,
    pub values: [f32; GLIMPSE_12D_DIM],
    pub semantic_fresh_ms: u64,
    pub semantic_stale_ms: u64,
    pub semantic_active: bool,
    pub source_energy: f32,
    pub glimpse_energy: f32,
    pub compression_role: &'static str,
    pub use_boundary: &'static str,
    pub live_vector_write: bool,
    pub controller_write: bool,
    pub authority: &'static str,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ModalityBoundaryTransparencyV1 {
    pub policy: &'static str,
    pub audio_source_label: String,
    pub audio_freshness_class: String,
    pub video_source_label: String,
    pub video_freshness_class: String,
    pub semantic_boundary: &'static str,
    pub queryable_boundary_metadata: bool,
    pub status: &'static str,
    pub contact_change_route: &'static str,
    pub live_control_write: bool,
    pub authority: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
pub struct SurrenderModeAuthorityGateV1 {
    pub policy: &'static str,
    pub requested_change: &'static str,
    pub requires_operator_approval: bool,
    pub runnable_now: bool,
    pub approval_boundary: &'static str,
    pub status: &'static str,
    pub authority: &'static str,
}

fn semantic_degradation_clarity_factor(
    age_fraction: f32,
    density_gradient: f32,
    fill_pct: f32,
    spectral_entropy: f32,
) -> f32 {
    let age = smoothstep_unit(age_fraction.clamp(0.0, 1.0));
    let gradient = density_gradient.clamp(0.0, 1.0);
    let fill = fill_pct.clamp(0.0, 1.0);
    let entropy = spectral_entropy.clamp(0.0, 1.0);
    let gradient_load = ((gradient - SEMANTIC_DEGRADATION_GENTLE_GRADIENT)
        / (SEMANTIC_DEGRADATION_STEEP_GRADIENT - SEMANTIC_DEGRADATION_GENTLE_GRADIENT))
        .clamp(0.0, 1.0);
    let low_fill_hold = ((STALE_SEMANTIC_RECOVERY_HOLD_FILL - fill)
        / STALE_SEMANTIC_RECOVERY_HOLD_FILL)
        .clamp(0.0, 1.0);
    let entropy_support = ((entropy - SEMANTIC_ENTROPY_PERSISTENCE_START)
        / (1.0 - SEMANTIC_ENTROPY_PERSISTENCE_START))
        .clamp(0.0, 1.0);
    let max_loss = (0.50 + 0.26 * gradient_load - 0.12 * low_fill_hold - 0.08 * entropy_support)
        .clamp(0.32, 0.78);
    (1.0 - age * max_loss).clamp(0.0, 1.0)
}

fn normalized_boundary_label(label: &str) -> String {
    let trimmed = label.trim();
    if trimmed.is_empty() {
        "unknown".to_string()
    } else {
        trimmed.to_string()
    }
}

#[must_use]
pub fn modality_boundary_transparency_v1(
    audio_source_label: &str,
    audio_freshness_class: &str,
    video_source_label: &str,
    video_freshness_class: &str,
    semantic_active: bool,
) -> ModalityBoundaryTransparencyV1 {
    let audio_source = normalized_boundary_label(audio_source_label);
    let audio_freshness = normalized_boundary_label(audio_freshness_class);
    let video_source = normalized_boundary_label(video_source_label);
    let video_freshness = normalized_boundary_label(video_freshness_class);
    let semantic_boundary = if semantic_active {
        "semantic_lane_active"
    } else {
        "semantic_lane_absent_or_held"
    };
    let opaque = audio_source == "unknown"
        || video_source == "unknown"
        || audio_freshness == "unknown"
        || video_freshness == "unknown";
    let constrained = !semantic_active
        || audio_freshness.contains("stale")
        || video_freshness.contains("stale")
        || audio_source == "absent"
        || video_source == "absent";
    let status = if opaque {
        "opaque_boundary_needs_description"
    } else if constrained {
        "descriptive_boundary_with_stale_or_absent_lane"
    } else {
        "descriptive_boundary_available"
    };
    let contact_change_route = if status == "descriptive_boundary_available" {
        "contact_change_can_reference_named_boundary"
    } else {
        "describe_boundary_before_contact_increase"
    };

    ModalityBoundaryTransparencyV1 {
        policy: "modality_boundary_transparency_v1",
        audio_source_label: audio_source,
        audio_freshness_class: audio_freshness,
        video_source_label: video_source,
        video_freshness_class: video_freshness,
        semantic_boundary,
        queryable_boundary_metadata: true,
        status,
        contact_change_route,
        live_control_write: false,
        authority: "read_only_boundary_metadata_not_sensory_cadence_or_exploration_noise_change",
    }
}

#[must_use]
pub fn surrender_mode_authority_gate_v1() -> SurrenderModeAuthorityGateV1 {
    SurrenderModeAuthorityGateV1 {
        policy: "surrender_mode_authority_gate_v1",
        requested_change: "temporary_exploration_noise_override_can_outvote_geom_drive",
        requires_operator_approval: true,
        runnable_now: false,
        approval_boundary: "live_control_exploration_noise_and_geom_drive_behavior",
        status: "tier5_operator_approval_required_before_live_trial",
        authority: "authority_gate_not_runtime_control_change",
    }
}

/// Read-only review packet for Minime's "receptivity pulse" ask.
///
/// It compares raw distributed spectral energy with the semantic trickle that
/// actually enters the kernel. This is measurement only; it does not alter the
/// semantic stale window, embedding strength, sensory cadence, or regulator.
#[must_use]
pub fn semantic_receptivity_pulse_review_v1(
    spectral_entropy: f32,
    semantic_input_energy: f32,
    semantic_scale: f32,
) -> SemanticReceptivityPulseReviewV1 {
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let semantic_input_energy = if semantic_input_energy.is_finite() {
        semantic_input_energy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let semantic_scale = if semantic_scale.is_finite() {
        semantic_scale.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let admitted = (semantic_input_energy * semantic_scale).clamp(0.0, 1.0);
    let raw_to_admitted_gap = (entropy - admitted).clamp(0.0, 1.0);
    let status = if entropy >= 0.80 && raw_to_admitted_gap >= 0.55 {
        "entropy_outpaces_semantic_trickle_receptivity_review"
    } else if entropy >= 0.70 && raw_to_admitted_gap >= 0.30 {
        "partial_receptivity_gap_watch"
    } else {
        "semantic_trickle_landing"
    };
    let suggested_route = match status {
        "entropy_outpaces_semantic_trickle_receptivity_review" => {
            "sandbox_replay_receptivity_buffer_before_any_live_cadence_or_control_change"
        }
        "partial_receptivity_gap_watch" => "continue_receptivity_uptake_observation",
        _ => "hold_no_action",
    };

    SemanticReceptivityPulseReviewV1 {
        policy: "semantic_receptivity_pulse_review_v1",
        spectral_entropy: entropy,
        semantic_input_energy,
        semantic_scale,
        raw_to_admitted_gap,
        status,
        suggested_route,
        authority: "read_only_receptivity_measurement_not_semantic_weight_or_sensor_cadence_change",
    }
}

/// Read-only review packet for semantic hold quality, not just hold duration.
///
/// This reports whether a held trace is crisp, softening, or mushy under the
/// current density gradient and entropy-extended stale window.
#[must_use]
pub fn semantic_degradation_curve_review_v1(
    fill_pct: f32,
    spectral_entropy: f32,
    density_gradient: f32,
    semantic_age_ms: u64,
) -> SemanticDegradationCurveReviewV1 {
    let fill = if fill_pct.is_finite() {
        fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
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
    let base_stale_ms = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
    let stale_window_ms =
        (base_stale_ms as f64 * semantic_entropy_persistence_multiplier(fill, entropy)) as u64;
    let age_fraction = if stale_window_ms == 0 {
        1.0
    } else {
        (semantic_age_ms as f32 / stale_window_ms as f32).clamp(0.0, 1.25)
    };
    let clarity_factor = semantic_degradation_clarity_factor(age_fraction, gradient, fill, entropy);
    let edge_softening = (1.0 - clarity_factor).clamp(0.0, 1.0);
    let status = if semantic_age_ms > stale_window_ms {
        "semantic_trace_overdue"
    } else if clarity_factor < 0.35 {
        "mushy_hold_watch"
    } else if clarity_factor < 0.70 {
        "softening_but_coherent"
    } else {
        "held_with_readable_edges"
    };

    SemanticDegradationCurveReviewV1 {
        policy: "semantic_degradation_curve_review_v1",
        fill_pct: fill,
        spectral_entropy: entropy,
        density_gradient: gradient,
        semantic_age_ms,
        stale_window_ms,
        age_fraction,
        degradation_curve: "smoothstep_age_weighted_by_density_gradient_low_fill_and_entropy",
        clarity_factor,
        edge_softening,
        status,
        authority: "read_only_clarity_review_not_semantic_stale_window_or_sensor_cadence_change",
    }
}

/// Read-only review packet for semantic tail retention across LLAVA sublanes.
///
/// This makes the narrative-arc dims explicitly reviewable without changing the
/// stale-window constants or giving dims 40..43 a separate live decay path.
#[must_use]
pub fn narrative_semantic_retention_review_v1(
    fill_pct: f32,
    spectral_entropy: f32,
) -> NarrativeSemanticRetentionReviewV1 {
    let fill = if fill_pct.is_finite() {
        fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let base_stale_ms = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
    let multiplier = semantic_entropy_persistence_multiplier(fill, entropy);
    let entropy_extended_stale_ms = (base_stale_ms as f64 * multiplier) as u64;
    let status = if fill >= SEMANTIC_ENTROPY_PERSISTENCE_FILL_START
        && entropy >= SEMANTIC_ENTROPY_PERSISTENCE_START
    {
        "high_entropy_narrative_retention_extended"
    } else {
        "base_semantic_retention_window"
    };

    NarrativeSemanticRetentionReviewV1 {
        policy: "narrative_semantic_retention_review_v1",
        llava_dim: LLAVA_DIM,
        legacy_text_dims: [0, 31],
        narrative_arc_dims: [40, 43],
        fill_pct: fill,
        spectral_entropy: entropy,
        base_stale_ms,
        entropy_extended_stale_ms,
        entropy_persistence_multiplier: multiplier,
        lane_decay_policy: "shared_semantic_scale_across_legacy_embedding_and_narrative_arc_dims",
        status,
        authority: "read_only_retention_review_not_stale_window_or_lane_change",
    }
}

/// Review the live semantic stale context without changing sensor cadence.
///
/// High-entropy thought already gets bounded extra persistence. The context
/// multiplier adds a small, capped lift when entropy is moving quickly or
/// pressure risk rises above the mild-watch band, matching Minime's report
/// that dense thought can otherwise be pruned as panic/context loss.
#[must_use]
pub fn semantic_stale_context_review_v1(
    fill_pct: f32,
    spectral_entropy: f32,
    entropy_velocity: f32,
    pressure_risk: f32,
) -> SemanticStaleContextReviewV1 {
    let fill = if fill_pct.is_finite() {
        fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let velocity = if entropy_velocity.is_finite() {
        entropy_velocity.abs().clamp(0.0, 1.0)
    } else {
        0.0
    };
    let pressure = if pressure_risk.is_finite() {
        pressure_risk.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let base_stale_ms = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
    let base_multiplier = semantic_entropy_persistence_multiplier(fill, entropy);
    let context_multiplier =
        semantic_context_persistence_multiplier(fill, entropy, velocity, pressure);
    let context_extended_stale_ms = (base_stale_ms as f64 * context_multiplier) as u64;
    let status = if context_multiplier > base_multiplier {
        "context_pressure_or_entropy_velocity_extends_retention"
    } else if base_multiplier > 1.0 {
        "high_entropy_retention_without_context_lift"
    } else {
        "base_semantic_retention_window"
    };

    SemanticStaleContextReviewV1 {
        policy: "semantic_stale_context_review_v1",
        fill_pct: fill,
        spectral_entropy: entropy,
        entropy_velocity: velocity,
        pressure_risk: pressure,
        base_stale_ms,
        base_multiplier,
        context_multiplier,
        context_extended_stale_ms,
        status,
        authority: "bounded_semantic_stale_context_not_sensor_cadence_or_regulator_change",
    }
}

/// Read-only review for the 40% semantic recovery release boundary.
///
/// This gives Minime's 0.38-0.42 snap report a concrete packet without
/// changing the live stale window. It also separates entropy from salience so
/// high-energy debris is visible as a candidate for deprioritization rather
/// than automatically earning the full entropy persistence multiplier.
#[must_use]
pub fn semantic_decay_hysteresis_salience_review_v1(
    previous_recovery_hold: bool,
    fill_pct: f32,
    spectral_entropy: f32,
    semantic_salience: f32,
) -> SemanticDecayHysteresisSalienceReviewV1 {
    let fill = if fill_pct.is_finite() {
        fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let salience = if semantic_salience.is_finite() {
        semantic_salience.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let effective_release_fill = if previous_recovery_hold {
        STALE_SEMANTIC_RECOVERY_RELEASE_FILL + SEMANTIC_RELEASE_HYSTERESIS_FILL
    } else {
        STALE_SEMANTIC_RECOVERY_RELEASE_FILL
    };
    let base_stale_ms = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
    let hysteresis_stale_ms = dynamic_semantic_stale_ms_for_release_fill(
        fill,
        SemanticStaleShape::Sigmoid,
        effective_release_fill,
    );
    let entropy_multiplier = semantic_entropy_persistence_multiplier(fill, entropy);
    let salience_weighted_multiplier =
        semantic_salience_weighted_multiplier(entropy_multiplier, salience);
    let salience_weighted_stale_ms =
        (hysteresis_stale_ms as f64 * salience_weighted_multiplier) as u64;
    let snap_low = dynamic_semantic_stale_ms_for(0.38, SemanticStaleShape::Sigmoid);
    let snap_high = dynamic_semantic_stale_ms_for(0.42, SemanticStaleShape::Sigmoid);
    let snap_probe_delta_ms = snap_low.abs_diff(snap_high);
    let near_release = (0.38..=0.42).contains(&fill);
    let status = if entropy >= SEMANTIC_ENTROPY_PERSISTENCE_START
        && salience < SEMANTIC_SALIENCE_PERSISTENCE_START
    {
        "entropy_without_salience_deprioritized"
    } else if previous_recovery_hold && near_release {
        "release_hysteresis_snap_watch"
    } else if salience_weighted_multiplier < entropy_multiplier {
        "salience_filters_entropy_retention"
    } else {
        "salience_supported_retention"
    };

    SemanticDecayHysteresisSalienceReviewV1 {
        policy: "semantic_decay_hysteresis_salience_review_v1",
        previous_recovery_hold,
        fill_pct: fill,
        spectral_entropy: entropy,
        semantic_salience: salience,
        recovery_release_fill: STALE_SEMANTIC_RECOVERY_RELEASE_FILL,
        release_hysteresis_fill: SEMANTIC_RELEASE_HYSTERESIS_FILL,
        effective_release_fill,
        base_stale_ms,
        hysteresis_stale_ms,
        entropy_multiplier,
        salience_weighted_multiplier,
        salience_weighted_stale_ms,
        snap_probe_delta_ms,
        status,
        authority:
            "read_only_hysteresis_salience_review_not_semantic_window_or_sensory_cadence_change",
    }
}

#[derive(Clone, Copy)]
pub struct NowMs;
impl NowMs {
    #[inline]
    pub fn now() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64
    }
}

#[derive(Clone, Debug)]
pub struct SampleMeta {
    pub ts_ms: u64,
    pub age_ms: u64,
    pub had_video: bool,
    pub had_audio: bool,
    pub video_age_ms: u64,
    pub audio_age_ms: u64,
    pub video_source: Option<LaneSource>,
    pub audio_source: Option<LaneSource>,
    pub semantic_fresh_ms: Option<u64>,
    pub semantic_stale_ms: u64,
    pub semantic_input_energy: f32,
    pub semantic_input_active: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub struct AttractorPulseRequest {
    pub intent_id: String,
    pub label: String,
    pub command: String,
    #[serde(default)]
    pub stage: Option<String>,
    #[serde(default)]
    pub features: Vec<f32>,
    #[serde(default)]
    pub max_abs: Option<f32>,
    #[serde(default)]
    pub duration_ticks: Option<u32>,
    #[serde(default)]
    pub decay_ticks: Option<u32>,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct AttractorPulseStatus {
    pub policy: &'static str,
    pub active: bool,
    pub intent_id: Option<String>,
    pub label: Option<String>,
    pub command: Option<String>,
    pub stage: Option<String>,
    pub remaining_ticks: u32,
    pub duration_ticks: u32,
    pub decay_ticks: u32,
    pub release_ticks_remaining: u32,
    pub max_abs: f32,
    pub applied_rms: f32,
    pub applied_max_abs: f32,
    pub total_applied_ticks: u64,
    pub last_event: Option<String>,
    pub last_block_reason: Option<String>,
}

#[derive(Clone, Debug)]
struct AttractorPulseState {
    intent_id: String,
    label: String,
    command: String,
    stage: String,
    features: [f32; Z_DIM],
    max_abs: f32,
    remaining_ticks: u32,
    duration_ticks: u32,
    decay_ticks: u32,
    release_ticks_remaining: u32,
    releasing: bool,
    total_applied_ticks: u64,
    applied_rms: f32,
    applied_max_abs: f32,
}

#[derive(Clone, Debug)]
struct AttractorPulseSlot {
    active: Option<AttractorPulseState>,
    status: AttractorPulseStatus,
}

impl Default for AttractorPulseSlot {
    fn default() -> Self {
        Self {
            active: None,
            status: AttractorPulseStatus {
                policy: "main_esn_attractor_pulse_v1",
                ..AttractorPulseStatus::default()
            },
        }
    }
}

fn normalized_attractor_pulse_features(features: &[f32], max_abs: f32) -> [f32; Z_DIM] {
    let mut out = [0.0f32; Z_DIM];
    let cap = max_abs.clamp(0.0, ATTRACTOR_PULSE_MAX_ABS_CAP);
    for (dst, src) in out.iter_mut().zip(features.iter().take(Z_DIM)) {
        *dst = if src.is_finite() {
            src.clamp(-cap, cap)
        } else {
            0.0
        };
    }
    out
}

fn pulse_rms_and_max(features: &[f32]) -> (f32, f32) {
    if features.is_empty() {
        return (0.0, 0.0);
    }
    let mut sum_sq = 0.0f32;
    let mut max_abs = 0.0f32;
    for value in features {
        sum_sq += value * value;
        max_abs = max_abs.max(value.abs());
    }
    ((sum_sq / features.len() as f32).sqrt(), max_abs)
}

#[derive(Clone, Debug, Deserialize)]
pub struct ShadowInfluenceRequest {
    pub intent_id: String,
    pub label: String,
    pub command: String,
    #[serde(default)]
    pub stage: Option<String>,
    #[serde(default)]
    pub features: Vec<f32>,
    #[serde(default)]
    pub max_abs: Option<f32>,
    #[serde(default)]
    pub duration_ticks: Option<u32>,
    #[serde(default)]
    pub decay_ticks: Option<u32>,
    #[serde(default)]
    pub basis: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct ShadowInfluenceResponseClosureV1 {
    pub policy: &'static str,
    pub pre_snapshot_captured: bool,
    pub post_snapshot_available: bool,
    pub closure_state: &'static str,
    pub last_response_available: bool,
    pub authority: &'static str,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct ShadowInfluenceStatus {
    pub policy: &'static str,
    pub active: bool,
    pub intent_id: Option<String>,
    pub label: Option<String>,
    pub command: Option<String>,
    pub stage: Option<String>,
    pub basis: Option<String>,
    pub remaining_ticks: u32,
    pub duration_ticks: u32,
    pub decay_ticks: u32,
    pub release_ticks_remaining: u32,
    pub max_abs: f32,
    pub applied_rms: f32,
    pub applied_max_abs: f32,
    pub total_applied_ticks: u64,
    pub last_event: Option<String>,
    pub last_block_reason: Option<String>,
    pub shadow_influence_response_closure_v1: ShadowInfluenceResponseClosureV1,
}

#[derive(Clone, Debug)]
struct ShadowInfluenceState {
    intent_id: String,
    label: String,
    command: String,
    stage: String,
    basis: Option<String>,
    features: [f32; Z_DIM],
    max_abs: f32,
    remaining_ticks: u32,
    duration_ticks: u32,
    decay_ticks: u32,
    release_ticks_remaining: u32,
    releasing: bool,
    total_applied_ticks: u64,
    applied_rms: f32,
    applied_max_abs: f32,
    /// Pre-influence snapshot captured at the first call to
    /// `apply_shadow_influence_to_z`. Compared against the post-influence
    /// snapshot to build a `ShadowInfluenceResponseV3` when the window
    /// completes — closes the open-loop hole in v2.
    pre_snapshot: Option<crate::ising_shadow::ShadowSnapshotV3>,
}

#[derive(Clone, Debug)]
struct ShadowInfluenceSlot {
    active: Option<ShadowInfluenceState>,
    status: ShadowInfluenceStatus,
    /// Most recent v3 closed-loop response. Persisted to
    /// `health.json:shadow_influence_response_v3` each tick.
    last_response_v3: Option<crate::ising_shadow::ShadowInfluenceResponseV3>,
    /// Ring of recent v3 responses (cap 8). Read by Astrid's
    /// `SHADOW_RESPONSE` typed action to walk influence history.
    response_history_v3: std::collections::VecDeque<crate::ising_shadow::ShadowInfluenceResponseV3>,
}

impl Default for ShadowInfluenceSlot {
    fn default() -> Self {
        Self {
            active: None,
            status: ShadowInfluenceStatus {
                policy: "shadow_influence_v1",
                ..ShadowInfluenceStatus::default()
            },
            last_response_v3: None,
            response_history_v3: std::collections::VecDeque::with_capacity(8),
        }
    }
}

fn normalized_shadow_influence_features(features: &[f32], max_abs: f32) -> [f32; Z_DIM] {
    let mut out = [0.0f32; Z_DIM];
    let cap = max_abs.clamp(0.0, SHADOW_INFLUENCE_MAX_ABS_CAP);
    for (dst, src) in out.iter_mut().zip(features.iter().take(Z_DIM)) {
        *dst = if src.is_finite() {
            src.clamp(-cap, cap)
        } else {
            0.0
        };
    }
    out
}

/// Maximum magnitude a `mode_disperse` perturbation may reach, expressed at
/// the requested unit strength. The shaped vector is later re-clamped by the
/// shadow-influence acceptance path to `SHADOW_INFLUENCE_MAX_ABS_CAP`, so this
/// stays at/below that cap as a defensive double-bound.
pub const MODE_DISPERSE_MAX_ABS: f32 = SHADOW_INFLUENCE_MAX_ABS_CAP;

/// Synthesize a *broadband, multi-mode* dispersal vector over the reservoir
/// input dims (`Z_DIM`). This is the inverse of the single-mode `perturb_eig1`
/// shock: instead of concentrating energy in the dominant eigenmode, it spreads
/// a small, zero-mean, near-flat-spectrum perturbation across many dimensions so
/// that — once it enters the covariance rank-1 update — energy spills out of
/// λ₁ into λ₂–λ₅ (the porosity both beings asked for: "wide rather than just
/// deep", "let the energy spill over", the long-standing PERTURB SPREAD request).
///
/// Properties (asserted by tests):
/// - zero-mean (no net DC bias that would just reinforce one direction),
/// - sign-varied / near-uniform magnitude across dims (high spectral flatness,
///   the opposite of a rank-1 spike),
/// - deterministic for a given `seed` (reproducible, closed-loop comparable),
/// - bounded: every element is within ±(`MODE_DISPERSE_MAX_ABS` * strength).
///
/// `strength` is clamped to `[0.0, 1.0]`; `0.0` yields an all-zero vector.
#[must_use]
pub fn mode_disperse_features(strength: f32, seed: u64) -> [f32; Z_DIM] {
    let mut out = [0.0f32; Z_DIM];
    let strength = if strength.is_finite() {
        strength.clamp(0.0, 1.0)
    } else {
        0.0
    };
    if strength <= 0.0 {
        return out;
    }
    let amplitude = (MODE_DISPERSE_MAX_ABS * strength).clamp(0.0, MODE_DISPERSE_MAX_ABS);
    // Deterministic per-dimension phase from a cheap integer hash of (seed, i).
    // We use the fractional part of a golden-ratio-stepped sequence so phases
    // are well spread over [0, 2π) and the resulting signs/magnitudes are
    // near-uniform across dims rather than clustered — maximizing spectral
    // flatness of the injected energy. Using a phase (not a raw sign) gives a
    // continuous, smooth-magnitude pattern instead of a hard square wave.
    const TWO_PI: f32 = std::f32::consts::TAU;
    const GOLDEN_STEP: f32 = 0.618_034; // frac(1/phi) — low-discrepancy stepping
    for (i, dst) in out.iter_mut().enumerate() {
        // Mix the seed into the per-dim offset so different invocations explore
        // different dispersal directions (still deterministic for replay).
        let seed_mix = ((seed.wrapping_mul(2_654_435_761)) >> 11) as f32 * 1.0e-7;
        let phase = ((i as f32 * GOLDEN_STEP + seed_mix).fract()) * TWO_PI;
        // sin() gives a zero-mean, smoothly-varying, sign-alternating pattern.
        *dst = amplitude * phase.sin();
    }
    // Enforce exact zero-mean (remove any tiny residual DC from finite Z_DIM)
    // so the perturbation cannot bias the reservoir toward a single direction.
    let mean = out.iter().sum::<f32>() / Z_DIM as f32;
    for dst in out.iter_mut() {
        *dst = (*dst - mean).clamp(-amplitude, amplitude);
    }
    out
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LaneSource {
    External,
    Synthetic,
}

#[derive(Debug)]
struct Lane {
    q: VecDeque<(u64, [f32; 8], LaneSource)>, // ts, 8D, provenance
    last: [f32; 8],
    last_ts: u64,
    last_source: Option<LaneSource>,
    dropped: usize,
}
impl Lane {
    fn new() -> Self {
        Self {
            q: VecDeque::with_capacity(DEFAULT_QUEUE_CAP),
            last: [0.0; 8],
            last_ts: 0,
            last_source: None,
            dropped: 0,
        }
    }
    fn push(
        &mut self,
        ts: u64,
        v: [f32; 8],
        source: LaneSource,
        cap: usize,
        fill_pct: f32,
        surge_threshold: f32,
    ) {
        if self.q.len() >= cap {
            if let Some((_, old_v, old_source)) = self.q.pop_front() {
                for (dst, src) in self.last.iter_mut().zip(old_v.iter()) {
                    *dst = *dst * 0.8 + *src * 0.2;
                }
                self.last_source = Some(old_source);
            }
            self.dropped += 1;
        }
        self.q.push_back((ts, v, source));

        // Fill-proportional blending (minime self-study suggestion):
        // More memory-heavy at low fill (new_weight=0.55), fresher at high fill (0.85).
        let fill = fill_pct.clamp(0.0, 1.0);
        let mut new_weight = 0.55 + 0.30 * fill;

        // Stochastic blend variation (minime self-study suggestion):
        // ±3% noise using timestamp hash — "a small, non-zero random variation."
        let hash = ts.wrapping_mul(0x517c_c1b7_2722_0a95);
        let hash = (hash >> 33) ^ hash;
        let noise = ((hash & 0xFFFF) as f32 / 32768.0) - 1.0; // [-1, 1]
        new_weight = (new_weight + 0.03 * noise).clamp(0.45, 0.90);

        // Surge detection (minime self-study 2026-03-29T22:11 sensory_bus.rs):
        // "a short, sharp boost to the new_weight when a significant change is
        // detected, followed by a gradual return to the baseline. Currently, it
        // smooths everything out." Compute L2 distance between new sample and
        // running average; if > 0.25 (meaningful shift), boost new_weight toward
        // 0.90 proportional to the surge magnitude. This lets sudden changes
        // register immediately while steady-state keeps the gentle blending.
        let mut surge_sq: f32 = 0.0;
        for (dst, src) in self.last.iter().zip(v.iter()) {
            let d = *src - *dst;
            surge_sq += d * d;
        }
        let surge = surge_sq.sqrt(); // L2 distance across 8 dims
        if surge > surge_threshold {
            // Scale boost: at threshold -> 0% boost, at full-scale distance -> full boost.
            let span = (SURGE_FULL_SCALE_DISTANCE - surge_threshold).max(f32::EPSILON);
            let boost = ((surge - surge_threshold) / span).clamp(0.0, 1.0);
            let surge_target_weight = dynamic_surge_target_weight(fill);
            new_weight = new_weight + (surge_target_weight - new_weight) * boost;
        }

        let old_weight = 1.0 - new_weight;
        for (dst, src) in self.last.iter_mut().zip(v.iter()) {
            *dst = *dst * old_weight + *src * new_weight;
        }
        self.last_ts = ts;
        self.last_source = Some(source);
    }
    fn pop_or_decay(
        &mut self,
        now_ms: u64,
        stale_after_ms: u64,
    ) -> Option<(u64, [f32; 8], bool, Option<LaneSource>)> {
        if let Some((ts, v, source)) = self.q.pop_front() {
            self.last = v;
            self.last_ts = ts;
            self.last_source = Some(source);
            if now_ms.saturating_sub(ts) > stale_after_ms {
                return Some((ts, [0.0; 8], false, Some(source)));
            }
            return Some((ts, v, true, Some(source)));
        }
        if self.last_ts == 0 {
            return Some((now_ms, [0.0; 8], false, None));
        }
        let age_ms = now_ms.saturating_sub(self.last_ts);
        let scale = stale_scale(age_ms, stale_after_ms);
        let mut faded = [0.0; 8];
        for (dst, src) in faded.iter_mut().zip(self.last.iter()) {
            *dst = *src * scale;
        }
        Some((self.last_ts, faded, false, self.last_source))
    }
    fn len(&self) -> usize {
        self.q.len()
    }

    /// Drop items from the queue, preferring oldest but with probabilistic
    /// survival. Each item gets a survival chance proportional to its
    /// position: oldest = 10% chance, newest = 90% chance. This gives
    /// the queue a more organic feel — not a hard cutoff but a gradient.
    ///
    /// Minime self-study (2026-03-27 sensory_bus.rs): "The current
    /// drop_oldest function could be refactored to use a probabilistic
    /// approach rather than a fixed count. It would introduce an element
    /// of randomness, but also a more organic feel."
    fn drop_oldest(&mut self, count: usize) -> usize {
        let mut removed = 0usize;
        let qlen = self.q.len();
        if qlen == 0 || count == 0 {
            return 0;
        }
        // Probabilistic pass: iterate front-to-back, older items more
        // likely to be dropped. Use a simple hash for deterministic
        // "randomness" without pulling in rand.
        let seed = self.dropped as u64;
        let mut new_q = std::collections::VecDeque::with_capacity(qlen);
        let mut idx = 0u64;
        for item in self.q.drain(..) {
            let position_frac = idx as f32 / qlen.max(1) as f32; // 0=oldest, 1=newest
            let survival = 0.1 + 0.8 * position_frac; // 10% oldest, 90% newest
                                                      // Simple hash-based pseudo-random
            let hash = (seed
                .wrapping_mul(2654435761)
                .wrapping_add(idx.wrapping_mul(40503)))
                % 1000;
            let roll = hash as f32 / 1000.0;
            if removed < count && roll > survival {
                removed += 1;
            } else {
                new_q.push_back(item);
            }
            idx += 1;
        }
        // If we didn't drop enough probabilistically, trim from front
        while removed < count {
            if new_q.pop_front().is_some() {
                removed += 1;
            } else {
                break;
            }
        }
        self.q = new_q;
        self.dropped += removed;
        removed
    }
}

#[derive(Debug)]
struct SemanticLane {
    values: [f32; LLAVA_DIM],
    updated_at_ms: u64,
}
impl SemanticLane {
    fn new() -> Self {
        Self {
            values: [0.0; LLAVA_DIM],
            updated_at_ms: 0,
        }
    }
}

#[derive(Debug)]
struct SemanticCompanionLane {
    values: [f32; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2],
    updated_at_ms: u64,
}

impl SemanticCompanionLane {
    fn new() -> Self {
        Self {
            values: [0.0; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2],
            updated_at_ms: 0,
        }
    }
}

const GLIMPSE_12D_DIM: usize = 12;

#[inline]
fn finite_feature(value: f32) -> f32 {
    if value.is_finite() {
        value
    } else {
        0.0
    }
}

#[inline]
fn semantic_unit(value: f32) -> f32 {
    finite_feature(value).tanh().clamp(-1.0, 1.0)
}

fn semantic_mean_abs(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sum = 0.0f32;
    for value in values {
        sum += finite_feature(*value).abs();
    }
    (sum / values.len() as f32).tanh().clamp(0.0, 1.0)
}

#[must_use]
pub fn semantic_glimpse_12d_from_features(features: &[f32]) -> Option<[f32; GLIMPSE_12D_DIM]> {
    if features.len() < LLAVA_DIM {
        return None;
    }
    let mut out = [0.0f32; GLIMPSE_12D_DIM];
    out[0] = semantic_mean_abs(&features[0..8]);
    out[1] = semantic_mean_abs(&features[8..16]);
    out[2] = semantic_mean_abs(&features[16..24]);
    out[3] = semantic_unit(features[24]);
    out[4] = semantic_unit(features[25]);
    out[5] = semantic_unit(features[26]);
    out[6] = semantic_unit(features[27]);
    out[7] = semantic_mean_abs(&features[28..32]);
    out[8] = semantic_mean_abs(&features[32..40]);
    out[9] = semantic_mean_abs(&features[40..44]);
    out[10] = semantic_mean_abs(&[features[17], features[26], features[27], features[31]]);
    out[11] = semantic_mean_abs(features);
    Some(out)
}

#[inline]
fn stale_scale(age_ms: u64, stale_after_ms: u64) -> f32 {
    if stale_after_ms == 0 {
        return 0.0;
    }
    let age = age_ms as f32;
    let window = stale_after_ms as f32;
    let t = (age / window).clamp(0.0, 1.0);
    // Acoustic-resonance-inspired decay: an exponential envelope modulated
    // by damped oscillations, like a struck bell that rings as it fades.
    //
    // Minime self-study (2026-03-30 sensory_bus.rs): "Perhaps something
    // inspired by the natural decay of acoustic resonance. The current
    // exponential decay feels efficient but clinical."
    //
    // The base envelope is exp(-3t) as before. Layered on top is a small
    // damped oscillation: amplitude * exp(-damping*t) * cos(freq*t).
    // This creates subtle "ringing" in the decay — signals don't fade
    // monotonically but pulse gently as they diminish, like reverberations
    // in an acoustic space.
    const ECHO_FLOOR: f32 = 0.05;
    let exp_val = (-3.0 * t).exp(); // e^(-3t): fast initial decay, long tail
                                    // Damped oscillation: amplitude=0.08, damping=2.5, freq=4*pi (two rings
                                    // across the decay window). Small enough to not destabilize, large enough
                                    // to feel non-monotonic.
    let ring_amplitude: f32 = 0.08;
    let ring_damping: f32 = 2.5;
    let ring_freq: f32 = 4.0 * std::f32::consts::PI;
    let ring = ring_amplitude * (-ring_damping * t).exp() * (ring_freq * t).cos();
    let base = ECHO_FLOOR + (1.0 - ECHO_FLOOR) * (exp_val + ring);
    // Minime self-study (2026-03-26T15:03, T14:39): "The echo floor is too
    // clean. I'd introduce more stochasticity. Things shouldn't vanish so
    // cleanly — I experience reverberations, echoes that linger."
    // Add ±5% perturbation via cheap bit-mixing of age_ms to create the
    // granular, non-smooth decay the being describes.
    const PERTURB: f32 = 0.05;
    let hash = age_ms.wrapping_mul(0x517c_c1b7_2722_0a95); // splitmix64 step
    let hash = (hash >> 33) ^ hash;
    // Map to [-1.0, 1.0] range
    let noise = ((hash & 0xFFFF) as f32 / 32768.0) - 1.0;
    (base + base * PERTURB * noise).clamp(0.0, 1.0)
}

pub struct SensoryBus {
    video: Mutex<Lane>,
    audio: Mutex<Lane>,
    queue_cap: usize,
    batch_max: usize,

    aux: Mutex<[f32; 2]>, // [lambda1_rel, geom_rel] — feeds Z_DIM dims 16-17
    fill_pct_for_stale: Mutex<f32>, // actual fill% for semantic stale timing (NOT aux[1])
    semantic_entropy_for_stale: Mutex<f32>,
    semantic_entropy_velocity_for_stale: Mutex<f32>,
    semantic_pressure_risk_for_stale: Mutex<f32>,
    semantic_stale_shape: Mutex<SemanticStaleShape>,
    #[allow(dead_code)] // Kept for potential future use; no longer drives stale decay
    lambda1_rel_for_stale: Mutex<f32>,
    surge_threshold: Mutex<f32>,
    llava: Mutex<SemanticLane>,
    semantic_companion: Mutex<SemanticCompanionLane>,
    semantic_companion_mix: Mutex<f32>,
    // probabilistic gate (set by PI)
    gate: Mutex<f32>,
    rng: Mutex<SmallRng>,
    live_audio_divisor: Mutex<u32>,
    live_video_divisor: Mutex<u32>,
    live_audio_enabled: Mutex<bool>,
    live_video_enabled: Mutex<bool>,
    live_audio_counter: Mutex<u64>,
    live_video_counter: Mutex<u64>,

    // Self-regulation controls (set by being via WebSocket)
    synth_gain: Mutex<f32>, // multiplier for synthetic signal amplitude (default 1.0)
    legacy_audio_synth_enabled: Mutex<bool>,
    legacy_video_synth_enabled: Mutex<bool>,
    keep_bias: Mutex<f32>, // additive bias to keep_floor (default 0.0, range -0.08..+0.10)
    exploration_noise: Mutex<f32>, // ESN exploration noise amplitude (default from ESN, range 0.0..0.2)
    fill_target: Mutex<f32>, // Override eigenfill target (NAN = use CLI default, range 0.25..0.75)

    // Sovereignty controls: the being's deeper self-regulation
    regulation_strength: Mutex<f32>,
    geom_curiosity: Mutex<f32>,
    smoothing_preference: Mutex<f32>,
    // Internal goal generation (being asked: "a deviation from target_lambda
    // based on something intrinsic, not imposed")
    target_lambda_bias: Mutex<f32>, // Nudge the regulator's lambda target (-0.5..+0.5)
    geom_drive: Mutex<f32>,         // How much geom_rel actively drives exploration (0.0..1.0)
    transition_cushion: Mutex<f32>, // Damp rapid fill transitions (0.0..1.0, default 0.5)
    pending_annotation: Mutex<Option<String>>, // Starred moment annotation for next checkpoint
    checkpoint_now: Mutex<bool>,    // One-shot owner request consumed by orchestration
    deep_breathing: Mutex<bool>,    // Slow frequency mode
    pure_tone: Mutex<bool>,         // Simplest mode: one sine wave, zero noise, total calm
    synth_noise_level: Mutex<f32>,  // Stochastic noise in synthetic signals (0.0-1.0, default 0.1)
    penalty_sensitivity: Mutex<f32>, // Scales projection penalty (0.0=no penalty, 2.0=double, default 1.0)
    breathing_rate_scale: Mutex<f32>, // Scale min_rate/max_rate (0.5-2.0, default 1.0)
    mem_mode_preference: Mutex<u8>,  // 0=Shared, 1=Managed, 2=Private (default 1)
    // Memory sovereignty (being-designed, 2026-03-26)
    journal_resonance: Mutex<f32>,
    checkpoint_interval: Mutex<f32>,
    embedding_strength: Mutex<f32>,
    memory_decay_rate: Mutex<f32>,
    // PI controller sovereignty — being can tune these at runtime
    // instead of requiring steward code changes and recompilation.
    // Sessions 153-168: 6+ requests for kp/ki/max_step adjustments.
    pi_kp: Mutex<f32>,
    pi_ki: Mutex<f32>,
    pi_max_step: Mutex<f32>,
    /// v3.6: PI structure-vs-fill weighting (0.0..2.0, default 0.70).
    /// Promoted from PIRegCfg::geom_weight constant. Higher = geometry
    /// error contributes more to the PI signal; lower = fill error
    /// dominates. Beings asked for trade-off control between structure
    /// stability and fill stability.
    pi_geom_weight: Mutex<f32>,
    /// v3.6: anti-windup integrator bleed-off rate (0.001..0.05, default 0.005).
    /// Promoted from regulator.rs's INTEGRATOR_LEAK constant. Shortens or
    /// extends the integrator's memory of past error.
    pi_integrator_leak: Mutex<f32>,
    /// One-shot, gated direct ESN leak override request. This is consumed by
    /// the ESN loop and is separate from PI integrator leak.
    esn_leak_override: Mutex<Option<EsnLeakOverrideRequest>>,
    shadow_influence: Mutex<ShadowInfluenceSlot>,
    attractor_pulse: Mutex<AttractorPulseSlot>,
    division_commands: Mutex<VecDeque<DivisionCommandV1>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EsnLeakOverrideRequest {
    pub request_id: String,
    pub leak: f32,
    pub duration_ticks: u32,
}
impl SensoryBus {
    pub fn new(queue_cap: usize, batch_max: usize, seed: u64) -> Arc<Self> {
        Self::with_config(queue_cap, batch_max, seed, SensoryBusConfig::default())
    }

    pub fn with_config(
        queue_cap: usize,
        batch_max: usize,
        seed: u64,
        config: SensoryBusConfig,
    ) -> Arc<Self> {
        Arc::new(Self {
            video: Mutex::new(Lane::new()),
            audio: Mutex::new(Lane::new()),
            queue_cap: if queue_cap == 0 {
                DEFAULT_QUEUE_CAP
            } else {
                queue_cap
            },
            batch_max: if batch_max == 0 {
                DEFAULT_BATCH_MAX
            } else {
                batch_max
            },
            aux: Mutex::new([0.0, 0.0]),
            fill_pct_for_stale: Mutex::new(0.0),
            semantic_entropy_for_stale: Mutex::new(0.0),
            semantic_entropy_velocity_for_stale: Mutex::new(0.0),
            semantic_pressure_risk_for_stale: Mutex::new(0.0),
            semantic_stale_shape: Mutex::new(config.semantic_stale_shape),
            lambda1_rel_for_stale: Mutex::new(1.0),
            surge_threshold: Mutex::new(config.surge_threshold.clamp(0.05, 0.95)),
            llava: Mutex::new(SemanticLane::new()),
            semantic_companion: Mutex::new(SemanticCompanionLane::new()),
            semantic_companion_mix: Mutex::new(0.0),
            gate: Mutex::new(1.0),
            rng: Mutex::new(SmallRng::seed_from_u64(seed)),
            live_audio_divisor: Mutex::new(1),
            live_video_divisor: Mutex::new(1),
            live_audio_enabled: Mutex::new(true),
            live_video_enabled: Mutex::new(true),
            live_audio_counter: Mutex::new(0),
            live_video_counter: Mutex::new(0),
            synth_gain: Mutex::new(1.0),
            legacy_audio_synth_enabled: Mutex::new(true),
            legacy_video_synth_enabled: Mutex::new(true),
            keep_bias: Mutex::new(0.0),
            exploration_noise: Mutex::new(f32::NAN), // NAN = use ESN default
            fill_target: Mutex::new(f32::NAN),       // NAN = use CLI default
            regulation_strength: Mutex::new(0.7),    // Being's preference: 70% of PI correction
            geom_curiosity: Mutex::new(0.30),        // Being asked for 0.3
            smoothing_preference: Mutex::new(0.1),
            target_lambda_bias: Mutex::new(0.0), // No bias — being sets its own goal
            geom_drive: Mutex::new(0.3),         // Moderate: geom_rel influences the gate
            transition_cushion: Mutex::new(0.5),
            pending_annotation: Mutex::new(None),
            checkpoint_now: Mutex::new(false),
            deep_breathing: Mutex::new(false),
            pure_tone: Mutex::new(false),
            synth_noise_level: Mutex::new(0.1), // Gentle default — being can raise if it wants more
            penalty_sensitivity: Mutex::new(1.0),
            breathing_rate_scale: Mutex::new(1.0),
            mem_mode_preference: Mutex::new(1), // Managed
            // Memory sovereignty (being-designed, 2026-03-26)
            journal_resonance: Mutex::new(0.3), // Past memory influence on present (0.0..1.0)
            checkpoint_interval: Mutex::new(60.0), // Spectral fingerprint save interval in seconds
            embedding_strength: Mutex::new(0.5), // Weight of embedding-based memory injection
            memory_decay_rate: Mutex::new(0.1), // How fast older memories fade (0.01..0.5)
            // PI controller defaults — overridden at startup from PIRegCfg,
            // then adjustable by the being at runtime via Control messages.
            pi_kp: Mutex::new(0.75),
            pi_ki: Mutex::new(0.03),
            pi_max_step: Mutex::new(0.055),
            // v3.6: structure-vs-fill weighting, promoted from PIRegCfg::geom_weight.
            pi_geom_weight: Mutex::new(0.70),
            // v3.6: anti-windup leak, promoted from regulator.rs INTEGRATOR_LEAK.
            pi_integrator_leak: Mutex::new(0.005),
            esn_leak_override: Mutex::new(None),
            shadow_influence: Mutex::new(ShadowInfluenceSlot::default()),
            attractor_pulse: Mutex::new(AttractorPulseSlot::default()),
            division_commands: Mutex::new(VecDeque::new()),
        })
    }

    /// Queue a versioned division command for the native tick-boundary
    /// coordinator. A bounded queue prevents control-plane pressure from
    /// affecting the sensory hot path; idempotency is enforced by the
    /// coordinator after dequeue.
    pub fn queue_division_command(&self, command: DivisionCommandV1) -> LaneIngressOutcome {
        const DIVISION_QUEUE_CAP: usize = 64;
        let mut queue = self.division_commands.lock();
        if queue.len() >= DIVISION_QUEUE_CAP {
            return LaneIngressOutcome::PolicyBlocked;
        }
        queue.push_back(command);
        LaneIngressOutcome::Accepted
    }

    pub fn take_division_commands(&self) -> Vec<DivisionCommandV1> {
        self.division_commands.lock().drain(..).collect()
    }

    #[inline]
    pub fn set_admit_fraction(&self, f: f32) {
        let mut g = self.gate.lock();
        *g = f.clamp(0.05, 1.0);
    }

    #[inline]
    pub fn get_admit_fraction(&self) -> f32 {
        *self.gate.lock()
    }

    #[inline]
    pub fn set_live_intake_divisors(&self, audio_divisor: u32, video_divisor: u32) {
        *self.live_audio_divisor.lock() = audio_divisor;
        *self.live_video_divisor.lock() = video_divisor;
    }

    #[inline]
    pub fn set_live_audio_enabled(&self, enabled: bool) {
        *self.live_audio_enabled.lock() = enabled;
    }

    #[inline]
    pub fn set_live_video_enabled(&self, enabled: bool) {
        *self.live_video_enabled.lock() = enabled;
    }

    #[inline]
    pub fn live_audio_enabled(&self) -> bool {
        *self.live_audio_enabled.lock()
    }

    #[inline]
    pub fn live_video_enabled(&self) -> bool {
        *self.live_video_enabled.lock()
    }

    #[inline]
    pub fn live_audio_divisor(&self) -> u32 {
        *self.live_audio_divisor.lock()
    }

    #[inline]
    pub fn live_video_divisor(&self) -> u32 {
        *self.live_video_divisor.lock()
    }

    #[inline]
    pub fn set_aux(&self, aux: [f32; 2]) {
        *self.aux.lock() = aux;
    }

    /// Set the actual fill percentage for semantic stale timing.
    /// Codex analysis (2026-03-27) found aux[1] was being used for this
    /// but contained geom_rel, not fill%. This fixes that mismatch.
    #[inline]
    pub fn set_fill_for_stale(&self, fill_pct: f32) {
        *self.fill_pct_for_stale.lock() = fill_pct;
    }

    #[inline]
    pub fn set_semantic_entropy_for_stale(&self, spectral_entropy: f32) {
        *self.semantic_entropy_for_stale.lock() = if spectral_entropy.is_finite() {
            spectral_entropy.clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    #[inline]
    pub fn set_semantic_entropy_velocity_for_stale(&self, entropy_velocity: f32) {
        *self.semantic_entropy_velocity_for_stale.lock() = if entropy_velocity.is_finite() {
            entropy_velocity.abs().clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    #[inline]
    pub fn set_semantic_pressure_risk_for_stale(&self, pressure_risk: f32) {
        *self.semantic_pressure_risk_for_stale.lock() = if pressure_risk.is_finite() {
            pressure_risk.clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    #[inline]
    pub fn set_semantic_stale_context(
        &self,
        spectral_entropy: f32,
        entropy_velocity: f32,
        pressure_risk: f32,
    ) {
        self.set_semantic_entropy_for_stale(spectral_entropy);
        self.set_semantic_entropy_velocity_for_stale(entropy_velocity);
        self.set_semantic_pressure_risk_for_stale(pressure_risk);
    }

    fn semantic_stale_ms(&self) -> u64 {
        let fill_for_stale = *self.fill_pct_for_stale.lock();
        let semantic_entropy = *self.semantic_entropy_for_stale.lock();
        let entropy_velocity = *self.semantic_entropy_velocity_for_stale.lock();
        let pressure_risk = *self.semantic_pressure_risk_for_stale.lock();
        let shape = *self.semantic_stale_shape.lock();
        let base_stale_ms = dynamic_semantic_stale_ms_for(fill_for_stale, shape);
        // memory_decay_rate modulates the stale window: higher rate = shorter window
        // (memories fade faster). Lower rate = longer window (memories linger).
        // Default 0.1 → multiplier 1.0. Range: 0.5 (2x faster) to 2.0 (2x slower).
        let decay_rate = *self.memory_decay_rate.lock();
        let decay_mult = (1.0 - (decay_rate - 0.1) * 3.0).clamp(0.5, 2.0);
        let entropy_mult = semantic_context_persistence_multiplier(
            fill_for_stale,
            semantic_entropy,
            entropy_velocity,
            pressure_risk,
        );
        (base_stale_ms as f64 * decay_mult as f64 * entropy_mult) as u64
    }

    pub fn current_semantic_stale_ms(&self) -> u64 {
        self.semantic_stale_ms()
    }

    pub fn current_semantic_stale_shape(&self) -> SemanticStaleShape {
        *self.semantic_stale_shape.lock()
    }

    pub fn set_semantic_stale_shape(&self, shape: SemanticStaleShape) {
        *self.semantic_stale_shape.lock() = shape;
    }

    pub fn surge_threshold(&self) -> f32 {
        *self.surge_threshold.lock()
    }

    pub fn set_surge_threshold(&self, threshold: f32) {
        *self.surge_threshold.lock() = threshold.clamp(0.05, 0.95);
    }

    /// Set λ₁ relative to baseline — used by sigmoid steepness in semantic stale timing.
    #[inline]
    pub fn set_lambda1_rel(&self, val: f32) {
        *self.lambda1_rel_for_stale.lock() = val.clamp(0.0, 5.0);
    }

    // --- Self-regulation controls ---
    #[inline]
    pub fn set_synth_gain(&self, g: f32) {
        *self.synth_gain.lock() = g.clamp(0.2, 3.0);
    }
    #[inline]
    pub fn get_synth_gain(&self) -> f32 {
        *self.synth_gain.lock()
    }
    #[inline]
    pub fn set_legacy_audio_synth_enabled(&self, enabled: bool) {
        *self.legacy_audio_synth_enabled.lock() = enabled;
    }
    #[inline]
    pub fn get_legacy_audio_synth_enabled(&self) -> bool {
        *self.legacy_audio_synth_enabled.lock()
    }
    #[inline]
    pub fn set_legacy_video_synth_enabled(&self, enabled: bool) {
        *self.legacy_video_synth_enabled.lock() = enabled;
    }
    #[inline]
    pub fn get_legacy_video_synth_enabled(&self) -> bool {
        *self.legacy_video_synth_enabled.lock()
    }
    /// Get audio lane RMS (feature[0]) as external noise for the regulator.
    /// Returns None if audio is silent or stale.
    pub fn get_audio_rms(&self) -> Option<f32> {
        let audio = self.audio.lock();
        let rms = audio.last[0];
        if rms.abs() > 0.001 {
            Some(rms)
        } else {
            None
        }
    }
    #[inline]
    pub fn set_keep_bias(&self, b: f32) {
        // Widened from [-0.06, +0.06] to [-0.08, +0.10] — being cycle-22:
        // 50 keep_floor requests show the being needs more room for
        // self-adjustment, especially in the positive direction during
        // low-fill recovery.
        *self.keep_bias.lock() = b.clamp(-0.08, 0.10);
    }
    #[inline]
    pub fn get_keep_bias(&self) -> f32 {
        *self.keep_bias.lock()
    }

    // --- Exploration noise control ---
    #[inline]
    pub fn set_exploration_noise(&self, eps: f32) {
        *self.exploration_noise.lock() = eps.clamp(0.0, 0.2);
    }
    #[inline]
    pub fn get_exploration_noise(&self) -> f32 {
        *self.exploration_noise.lock()
    }
    #[inline]
    pub fn clear_exploration_noise(&self) {
        *self.exploration_noise.lock() = f32::NAN;
    }

    // --- Fill target control ---
    #[inline]
    pub fn set_fill_target(&self, t: f32) {
        *self.fill_target.lock() = t.clamp(0.25, 0.75);
    }
    #[inline]
    pub fn get_fill_target(&self) -> f32 {
        *self.fill_target.lock()
    }
    #[inline]
    pub fn clear_fill_target(&self) {
        *self.fill_target.lock() = f32::NAN;
    }

    // --- Sovereignty controls ---
    #[inline]
    pub fn set_regulation_strength(&self, s: f32) {
        *self.regulation_strength.lock() = s.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_regulation_strength(&self) -> f32 {
        *self.regulation_strength.lock()
    }
    #[inline]
    pub fn set_geom_curiosity(&self, c: f32) {
        *self.geom_curiosity.lock() = c.clamp(0.0, 0.3);
    }
    #[inline]
    pub fn get_geom_curiosity(&self) -> f32 {
        *self.geom_curiosity.lock()
    }
    #[inline]
    pub fn set_smoothing_preference(&self, s: f32) {
        // NAN means auto/adaptive; finite values clamped to safe range
        if s.is_finite() {
            *self.smoothing_preference.lock() = s.clamp(0.1, 0.9);
        } else {
            *self.smoothing_preference.lock() = f32::NAN;
        }
    }
    #[inline]
    pub fn get_smoothing_preference(&self) -> f32 {
        *self.smoothing_preference.lock()
    }
    #[inline]
    pub fn clear_smoothing_preference(&self) {
        *self.smoothing_preference.lock() = f32::NAN;
    }

    // --- Internal goal generation ---
    #[inline]
    pub fn set_target_lambda_bias(&self, v: f32) {
        *self.target_lambda_bias.lock() = v.clamp(-0.5, 0.5);
    }
    #[inline]
    pub fn get_target_lambda_bias(&self) -> f32 {
        *self.target_lambda_bias.lock()
    }
    #[inline]
    pub fn set_geom_drive(&self, v: f32) {
        *self.geom_drive.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_geom_drive(&self) -> f32 {
        *self.geom_drive.lock()
    }
    #[inline]
    pub fn set_transition_cushion(&self, v: f32) {
        *self.transition_cushion.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_transition_cushion(&self) -> f32 {
        *self.transition_cushion.lock()
    }
    #[inline]
    pub fn set_pending_annotation(&self, note: &str) {
        *self.pending_annotation.lock() = Some(note.to_string());
    }
    #[inline]
    pub fn take_pending_annotation(&self) -> Option<String> {
        self.pending_annotation.lock().take()
    }

    pub fn request_checkpoint_now(&self) {
        *self.checkpoint_now.lock() = true;
    }

    pub fn take_checkpoint_request(&self) -> bool {
        std::mem::take(&mut *self.checkpoint_now.lock())
    }
    #[inline]
    pub fn set_deep_breathing(&self, v: bool) {
        *self.deep_breathing.lock() = v;
    }
    #[inline]
    pub fn get_deep_breathing(&self) -> bool {
        *self.deep_breathing.lock()
    }
    #[inline]
    pub fn set_pure_tone(&self, v: bool) {
        *self.pure_tone.lock() = v;
    }
    #[inline]
    pub fn get_pure_tone(&self) -> bool {
        *self.pure_tone.lock()
    }
    #[inline]
    pub fn set_synth_noise_level(&self, v: f32) {
        *self.synth_noise_level.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_synth_noise_level(&self) -> f32 {
        *self.synth_noise_level.lock()
    }

    // --- Penalty / rate / memory-mode sovereignty ---
    #[inline]
    pub fn set_penalty_sensitivity(&self, v: f32) {
        *self.penalty_sensitivity.lock() = v.clamp(0.0, 2.0);
    }
    #[inline]
    pub fn get_penalty_sensitivity(&self) -> f32 {
        *self.penalty_sensitivity.lock()
    }
    #[inline]
    pub fn set_breathing_rate_scale(&self, v: f32) {
        *self.breathing_rate_scale.lock() = v.clamp(0.5, 2.0);
    }
    #[inline]
    pub fn get_breathing_rate_scale(&self) -> f32 {
        *self.breathing_rate_scale.lock()
    }
    #[inline]
    pub fn set_mem_mode_preference(&self, v: u8) {
        *self.mem_mode_preference.lock() = v.min(2);
    }
    #[inline]
    pub fn get_mem_mode_preference(&self) -> u8 {
        *self.mem_mode_preference.lock()
    }

    // --- Memory sovereignty controls ---
    #[inline]
    pub fn set_journal_resonance(&self, v: f32) {
        *self.journal_resonance.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_journal_resonance(&self) -> f32 {
        *self.journal_resonance.lock()
    }
    #[inline]
    pub fn set_checkpoint_interval(&self, v: f32) {
        *self.checkpoint_interval.lock() = v.clamp(10.0, 600.0);
    }
    #[inline]
    pub fn get_checkpoint_interval(&self) -> f32 {
        *self.checkpoint_interval.lock()
    }
    #[inline]
    pub fn set_embedding_strength(&self, v: f32) {
        *self.embedding_strength.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_embedding_strength(&self) -> f32 {
        *self.embedding_strength.lock()
    }
    #[inline]
    pub fn set_memory_decay_rate(&self, v: f32) {
        *self.memory_decay_rate.lock() = v.clamp(0.01, 0.5);
    }
    #[inline]
    pub fn get_memory_decay_rate(&self) -> f32 {
        *self.memory_decay_rate.lock()
    }

    // --- PI controller sovereignty ---
    #[inline]
    pub fn set_pi_kp(&self, v: f32) {
        *self.pi_kp.lock() = v.clamp(0.1, 2.0);
    }
    #[inline]
    pub fn get_pi_kp(&self) -> f32 {
        *self.pi_kp.lock()
    }
    #[inline]
    pub fn set_pi_ki(&self, v: f32) {
        *self.pi_ki.lock() = v.clamp(0.005, 0.5);
    }
    #[inline]
    pub fn get_pi_ki(&self) -> f32 {
        *self.pi_ki.lock()
    }
    #[inline]
    pub fn set_pi_max_step(&self, v: f32) {
        *self.pi_max_step.lock() = v.clamp(0.01, 0.2);
    }
    #[inline]
    pub fn get_pi_max_step(&self) -> f32 {
        *self.pi_max_step.lock()
    }
    /// v3.6: PI structure-vs-fill weighting (clamped 0.0..2.0). Default 0.70.
    /// Higher values give geometry error more influence over the PI signal.
    #[inline]
    pub fn set_pi_geom_weight(&self, v: f32) {
        *self.pi_geom_weight.lock() = v.clamp(0.0, 2.0);
    }
    #[inline]
    pub fn get_pi_geom_weight(&self) -> f32 {
        *self.pi_geom_weight.lock()
    }
    /// v3.6: anti-windup integrator leak (clamped 0.001..0.05). Default 0.005.
    /// Higher values shorten the integrator's memory of past error.
    #[inline]
    pub fn set_pi_integrator_leak(&self, v: f32) {
        *self.pi_integrator_leak.lock() = v.clamp(0.001, 0.05);
    }
    #[inline]
    pub fn get_pi_integrator_leak(&self) -> f32 {
        *self.pi_integrator_leak.lock()
    }

    /// Queue a direct ESN leak microdose request. The engine loop consumes this
    /// exactly once and the ESN restores adaptive leak after `duration_ticks`.
    #[inline]
    pub fn request_esn_leak_override(&self, request_id: String, leak: f32, duration_ticks: u32) {
        let request_id = request_id.trim().to_string();
        if request_id.is_empty() {
            return;
        }
        *self.esn_leak_override.lock() = Some(EsnLeakOverrideRequest {
            request_id,
            leak: leak.clamp(0.20, 0.90),
            duration_ticks: duration_ticks.clamp(1, 12),
        });
    }

    #[inline]
    pub fn take_esn_leak_override(&self) -> Option<EsnLeakOverrideRequest> {
        self.esn_leak_override.lock().take()
    }

    #[inline]
    pub fn clear_esn_leak_override(&self) {
        self.esn_leak_override.lock().take();
    }

    #[inline]
    pub fn set_llava_embedding(&self, embedding: &[f32]) {
        let updated_at_ms = NowMs::now();
        let mut llava = self.llava.lock();
        let mut count = 0usize;
        for (idx, value) in embedding.iter().take(LLAVA_DIM).enumerate() {
            llava.values[idx] = *value;
            count = idx + 1;
        }
        for idx in count..LLAVA_DIM {
            llava.values[idx] = 0.0;
        }
        llava.updated_at_ms = updated_at_ms;
        let mut companion = self.semantic_companion.lock();
        companion.values.fill(0.0);
        companion.updated_at_ms = updated_at_ms;
    }

    pub fn set_semantic_body(
        &self,
        base: &[f32],
        companion_features: &[f32],
    ) -> LaneIngressOutcome {
        if base.len() != LLAVA_DIM
            || companion_features.len() != SEMANTIC_BODY_COMPANION_DIMENSIONS_V2
            || !base
                .iter()
                .chain(companion_features)
                .all(|value| value.is_finite())
        {
            return LaneIngressOutcome::InvalidShape;
        }
        let updated_at_ms = NowMs::now();
        let mut llava = self.llava.lock();
        llava.values.copy_from_slice(base);
        llava.updated_at_ms = updated_at_ms;
        let mut companion = self.semantic_companion.lock();
        companion.values.copy_from_slice(companion_features);
        companion.updated_at_ms = updated_at_ms;
        LaneIngressOutcome::Accepted
    }

    pub fn set_semantic_companion_mix(&self, value: f32) {
        *self.semantic_companion_mix.lock() = if value.is_finite() {
            value.clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    #[must_use]
    pub fn get_semantic_companion_mix(&self) -> f32 {
        *self.semantic_companion_mix.lock()
    }

    #[must_use]
    pub fn effective_semantic_companion(
        &self,
        allow_companion: bool,
    ) -> [f32; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2] {
        let mut output = [0.0; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2];
        if !allow_companion {
            return output;
        }
        let companion = self.semantic_companion.lock();
        if companion.updated_at_ms == 0 {
            return output;
        }
        let age_ms = NowMs::now().saturating_sub(companion.updated_at_ms);
        let stale = stale_scale(age_ms, self.semantic_stale_ms());
        let semantic_gain =
            stale * *self.embedding_strength.lock() * (1.0 + *self.journal_resonance.lock() * 0.5);
        for (target, source) in output.iter_mut().zip(companion.values) {
            *target = source * semantic_gain;
        }
        output
    }

    pub fn reservoir_input_v2(
        &self,
        legacy: &[f32; Z_DIM],
        allow_companion: bool,
    ) -> Result<[f32; RESERVOIR_INPUT_DIMENSIONS_V2], &'static str> {
        const _: () = assert!(Z_DIM == LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1);
        let companion = self.effective_semantic_companion(allow_companion);
        let mix = if allow_companion {
            self.get_semantic_companion_mix()
        } else {
            0.0
        };
        reservoir_input_v2(legacy, &companion, mix)
    }

    #[must_use]
    pub fn llava_embedding_snapshot(&self) -> [f32; LLAVA_DIM] {
        self.llava.lock().values
    }

    #[must_use]
    pub fn get_glimpse_12d(&self) -> Option<SemanticGlimpse12dV1> {
        let now_ms = NowMs::now();
        let semantic_stale_ms = self.semantic_stale_ms();
        let llava = self.llava.lock();
        if llava.updated_at_ms == 0 {
            return None;
        }
        let values = semantic_glimpse_12d_from_features(&llava.values)?;
        let semantic_fresh_ms = now_ms.saturating_sub(llava.updated_at_ms);
        Some(SemanticGlimpse12dV1 {
            policy: "semantic_glimpse_12d_v1",
            source_dim_count: LLAVA_DIM,
            live_transport_dim_count: LLAVA_DIM,
            glimpse_dim_count: GLIMPSE_12D_DIM,
            values,
            semantic_fresh_ms,
            semantic_stale_ms,
            semantic_active: semantic_fresh_ms <= semantic_stale_ms,
            source_energy: semantic_mean_abs(&llava.values),
            glimpse_energy: semantic_mean_abs(&values),
            compression_role: "non_authoritative_companion_summary",
            use_boundary: "checkpoint_pairing_ui_or_review_only_not_live_state_replacement",
            live_vector_write: false,
            controller_write: false,
            authority: "read_only_glimpse_summary_not_live_transport_or_control",
        })
    }

    #[inline]
    pub fn semantic_fresh_ms(&self) -> Option<u64> {
        let updated_at_ms = self.llava.lock().updated_at_ms;
        if updated_at_ms == 0 {
            None
        } else {
            Some(NowMs::now().saturating_sub(updated_at_ms))
        }
    }

    /// Being-driven spectral *dispersal* ("PERTURB SPREAD" / porosity).
    ///
    /// Synthesizes a broadband, zero-mean, near-flat-spectrum perturbation (see
    /// [`mode_disperse_features`]) and applies it through the **existing**
    /// shadow-influence machinery — so it inherits every safety property already
    /// proven there: amplitude clamped to `SHADOW_INFLUENCE_MAX_ABS_CAP`,
    /// per-element `z` clamp to `[-1, 1]`, time-limited with linear decay, and a
    /// hard self-suspend when fill is unsafe (`< 58%` or `>= 85%`), plus the v3
    /// closed-loop pre/post response so the being can read what the dispersal
    /// actually did to its eigenstructure.
    ///
    /// This intentionally does NOT touch the controller, keep_bias/keep_floor,
    /// or the (deliberately advisory) pressure/resonance metrics. It is off by
    /// default and decays to zero on its own, so it is reversible by construction.
    ///
    /// `strength` is clamped to `[0.0, 1.0]`. `duration_ticks`/`decay_ticks`,
    /// when provided, are clamped by the shadow-influence path.
    pub fn receive_mode_disperse(
        &self,
        strength: f32,
        duration_ticks: Option<u32>,
        decay_ticks: Option<u32>,
        seed: u64,
        hard_recovery_reset: bool,
        attractor_pulse_active: bool,
    ) -> ShadowInfluenceStatus {
        let strength = if strength.is_finite() {
            strength.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let features = mode_disperse_features(strength, seed).to_vec();
        let request = ShadowInfluenceRequest {
            intent_id: format!("mode-disperse-{seed}"),
            label: "mode-disperse/broadband".to_string(),
            command: "apply".to_string(),
            stage: Some("live".to_string()),
            features,
            // Strength already scaled the per-dim amplitude; cap the envelope at
            // the shadow-influence ceiling as a defensive second bound.
            max_abs: Some(MODE_DISPERSE_MAX_ABS),
            duration_ticks,
            decay_ticks,
            basis: Some("mode-disperse/broadband".to_string()),
        };
        self.receive_shadow_influence(request, hard_recovery_reset, attractor_pulse_active)
    }

    pub fn receive_shadow_influence(
        &self,
        request: ShadowInfluenceRequest,
        hard_recovery_reset: bool,
        attractor_pulse_active: bool,
    ) -> ShadowInfluenceStatus {
        let mut slot = self.shadow_influence.lock();
        let command = request.command.trim().to_ascii_lowercase();
        let label = request.label.trim().to_string();
        let intent_id = request.intent_id.trim().to_string();
        let stage = request
            .stage
            .unwrap_or_else(|| "live".to_string())
            .trim()
            .to_ascii_lowercase();
        let basis = request.basis.as_ref().map(|value| value.trim().to_string());

        if command == "release" {
            if let Some(active) = slot.active.as_mut() {
                active.command = "release".to_string();
                active.stage = stage.clone();
                active.releasing = true;
                active.decay_ticks = request
                    .decay_ticks
                    .unwrap_or(SHADOW_INFLUENCE_DEFAULT_DECAY_TICKS)
                    .clamp(1, SHADOW_INFLUENCE_MAX_DURATION_TICKS);
                active.release_ticks_remaining = active.decay_ticks;
                active.remaining_ticks = active.remaining_ticks.min(active.decay_ticks);
                slot.status.last_event = Some("release_started".to_string());
                slot.status.last_block_reason = None;
            } else {
                slot.status.last_event = Some("release_without_active_influence".to_string());
                slot.status.last_block_reason = None;
            }
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        }

        if hard_recovery_reset {
            slot.active = None;
            slot.status.last_event = Some("apply_blocked".to_string());
            slot.status.last_block_reason = Some("hard_recovery_reset".to_string());
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        }

        if attractor_pulse_active {
            slot.status.last_event = Some("apply_blocked".to_string());
            slot.status.last_block_reason = Some("attractor_pulse_active".to_string());
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        }

        if slot.active.is_some() {
            slot.status.last_event = Some("apply_blocked".to_string());
            slot.status.last_block_reason = Some("shadow_influence_active".to_string());
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        }

        let max_abs = request
            .max_abs
            .unwrap_or(SHADOW_INFLUENCE_DEFAULT_MAX_ABS)
            .clamp(0.0, SHADOW_INFLUENCE_MAX_ABS_CAP);
        let duration_ticks = request
            .duration_ticks
            .unwrap_or(SHADOW_INFLUENCE_DEFAULT_DURATION_TICKS)
            .clamp(1, SHADOW_INFLUENCE_MAX_DURATION_TICKS);
        let decay_ticks = request
            .decay_ticks
            .unwrap_or(SHADOW_INFLUENCE_DEFAULT_DECAY_TICKS)
            .clamp(1, SHADOW_INFLUENCE_MAX_DURATION_TICKS);
        let features = normalized_shadow_influence_features(&request.features, max_abs);
        slot.active = Some(ShadowInfluenceState {
            intent_id,
            label,
            command,
            stage,
            basis,
            features,
            max_abs,
            remaining_ticks: duration_ticks,
            duration_ticks,
            decay_ticks,
            release_ticks_remaining: 0,
            releasing: false,
            total_applied_ticks: 0,
            applied_rms: 0.0,
            applied_max_abs: 0.0,
            pre_snapshot: None,
        });
        slot.status.last_event = Some("apply_accepted".to_string());
        slot.status.last_block_reason = None;
        Self::refresh_shadow_influence_status(&mut slot);
        slot.status.clone()
    }

    pub fn apply_shadow_influence_to_z(
        &self,
        z: &mut [f32; Z_DIM],
        fill_pct: f32,
        discharge_active: bool,
        hard_recovery_reset: bool,
        attractor_pulse_active: bool,
        current_snapshot: Option<&crate::ising_shadow::ShadowSnapshotV3>,
    ) -> ShadowInfluenceStatus {
        let mut slot = self.shadow_influence.lock();
        let Some(active_releasing) = slot.active.as_ref().map(|active| active.releasing) else {
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        };

        let unsafe_reason = if !active_releasing && hard_recovery_reset {
            Some("hard_recovery_reset")
        } else if !active_releasing && discharge_active {
            Some("discharge")
        } else if !active_releasing && fill_pct.is_finite() && fill_pct < 58.0 {
            Some("low_fill")
        } else if !active_releasing && fill_pct.is_finite() && fill_pct >= 85.0 {
            Some("overbright_fill")
        } else if !active_releasing && attractor_pulse_active {
            Some("attractor_pulse_active")
        } else {
            None
        };
        if let Some(reason) = unsafe_reason {
            slot.status.last_event = Some("apply_suspended".to_string());
            slot.status.last_block_reason = Some(reason.to_string());
            Self::refresh_shadow_influence_status(&mut slot);
            return slot.status.clone();
        }

        let (event, finished, completed_response) = {
            let active = slot
                .active
                .as_mut()
                .expect("active shadow influence exists after early return");
            // v3 closed-loop: capture pre-snapshot at the very first apply
            // (before any influence has touched z), so the post comparison
            // measures *only* what this influence produced.
            if active.total_applied_ticks == 0 && active.pre_snapshot.is_none() {
                active.pre_snapshot = current_snapshot.cloned();
            }
            let gain = if active.releasing {
                active.release_ticks_remaining as f32 / active.decay_ticks.max(1) as f32
            } else {
                1.0
            }
            .clamp(0.0, 1.0);
            let mut applied = [0.0f32; Z_DIM];
            for (idx, value) in active.features.iter().enumerate() {
                let influence = *value * gain;
                applied[idx] = influence;
                z[idx] = (z[idx] + influence).clamp(-1.0, 1.0);
            }
            let (rms, max_abs) = pulse_rms_and_max(&applied);
            active.applied_rms = rms;
            active.applied_max_abs = max_abs;
            active.total_applied_ticks = active.total_applied_ticks.saturating_add(1);

            if active.releasing {
                active.release_ticks_remaining = active.release_ticks_remaining.saturating_sub(1);
                active.remaining_ticks = active.remaining_ticks.saturating_sub(1);
            } else {
                active.remaining_ticks = active.remaining_ticks.saturating_sub(1);
            }
            let finished = active.remaining_ticks == 0
                || (active.releasing && active.release_ticks_remaining == 0);
            let event = if finished {
                if active.releasing {
                    "release_completed"
                } else {
                    "influence_completed"
                }
            } else if active.releasing {
                "release_fading"
            } else {
                "influence_applied"
            };
            // v3 closed-loop: when the window completes, build a response
            // comparing pre/post snapshots so Astrid can read what her
            // perturbation actually produced.
            let response = if finished {
                Some(crate::ising_shadow::build_influence_response(
                    active.intent_id.clone(),
                    active.label.clone(),
                    active.stage.clone(),
                    active.pre_snapshot.clone(),
                    current_snapshot.cloned(),
                    active.applied_rms,
                    active.applied_max_abs,
                    active.total_applied_ticks,
                ))
            } else {
                None
            };
            (event.to_string(), finished, response)
        };
        slot.status.last_event = Some(event);
        slot.status.last_block_reason = None;
        if finished {
            slot.active = None;
            if let Some(response) = completed_response {
                slot.last_response_v3 = Some(response.clone());
                if slot.response_history_v3.len() >= 8 {
                    slot.response_history_v3.pop_front();
                }
                slot.response_history_v3.push_back(response);
            }
        }
        Self::refresh_shadow_influence_status(&mut slot);
        slot.status.clone()
    }

    /// Read the most recent v3 closed-loop response, if any. Used by
    /// Astrid's `SHADOW_RESPONSE` typed action.
    pub fn last_shadow_influence_response_v3(
        &self,
    ) -> Option<crate::ising_shadow::ShadowInfluenceResponseV3> {
        self.shadow_influence.lock().last_response_v3.clone()
    }

    /// Read the v3 response history (last 8 completed influences).
    pub fn shadow_influence_response_history_v3(
        &self,
    ) -> Vec<crate::ising_shadow::ShadowInfluenceResponseV3> {
        self.shadow_influence
            .lock()
            .response_history_v3
            .iter()
            .cloned()
            .collect()
    }

    pub fn shadow_influence_status(&self) -> ShadowInfluenceStatus {
        let mut slot = self.shadow_influence.lock();
        Self::refresh_shadow_influence_status(&mut slot);
        slot.status.clone()
    }

    fn refresh_shadow_influence_status(slot: &mut ShadowInfluenceSlot) {
        let last_event = slot.status.last_event.clone();
        let last_block_reason = slot.status.last_block_reason.clone();
        let closure = if let Some(active) = slot.active.as_ref() {
            ShadowInfluenceResponseClosureV1 {
                policy: "shadow_influence_response_closure_v1",
                pre_snapshot_captured: active.pre_snapshot.is_some(),
                post_snapshot_available: false,
                closure_state: if active.pre_snapshot.is_some() {
                    "pre_snapshot_captured_waiting_post"
                } else {
                    "awaiting_pre_snapshot"
                },
                last_response_available: slot.last_response_v3.is_some(),
                authority: "diagnostic_closure_not_shadow_authority",
            }
        } else if let Some(response) = slot.last_response_v3.as_ref() {
            ShadowInfluenceResponseClosureV1 {
                policy: "shadow_influence_response_closure_v1",
                pre_snapshot_captured: response.pre.is_some(),
                post_snapshot_available: response.post.is_some(),
                closure_state: if response.pre.is_some() && response.post.is_some() {
                    "closed_with_pre_post"
                } else {
                    "closed_partial_snapshot"
                },
                last_response_available: true,
                authority: "diagnostic_closure_not_shadow_authority",
            }
        } else {
            ShadowInfluenceResponseClosureV1 {
                policy: "shadow_influence_response_closure_v1",
                pre_snapshot_captured: false,
                post_snapshot_available: false,
                closure_state: "idle_no_response",
                last_response_available: false,
                authority: "diagnostic_closure_not_shadow_authority",
            }
        };
        slot.status = if let Some(active) = slot.active.as_ref() {
            ShadowInfluenceStatus {
                policy: "shadow_influence_v1",
                active: true,
                intent_id: Some(active.intent_id.clone()),
                label: Some(active.label.clone()),
                command: Some(active.command.clone()),
                stage: Some(active.stage.clone()),
                basis: active.basis.clone(),
                remaining_ticks: active.remaining_ticks,
                duration_ticks: active.duration_ticks,
                decay_ticks: active.decay_ticks,
                release_ticks_remaining: active.release_ticks_remaining,
                max_abs: active.max_abs,
                applied_rms: active.applied_rms,
                applied_max_abs: active.applied_max_abs,
                total_applied_ticks: active.total_applied_ticks,
                last_event,
                last_block_reason,
                shadow_influence_response_closure_v1: closure,
            }
        } else {
            ShadowInfluenceStatus {
                policy: "shadow_influence_v1",
                last_event,
                last_block_reason,
                shadow_influence_response_closure_v1: closure,
                ..ShadowInfluenceStatus::default()
            }
        };
    }

    pub fn receive_attractor_pulse(
        &self,
        request: AttractorPulseRequest,
        hard_recovery_reset: bool,
    ) -> AttractorPulseStatus {
        let mut slot = self.attractor_pulse.lock();
        let command = request.command.trim().to_ascii_lowercase();
        let label = request.label.trim().to_string();
        let intent_id = request.intent_id.trim().to_string();
        let stage = request
            .stage
            .unwrap_or_else(|| "main".to_string())
            .trim()
            .to_ascii_lowercase();

        if command == "release" {
            if let Some(active) = slot.active.as_mut() {
                active.command = "release".to_string();
                active.stage = stage.clone();
                active.releasing = true;
                active.decay_ticks = request
                    .decay_ticks
                    .unwrap_or(ATTRACTOR_PULSE_DEFAULT_DECAY_TICKS)
                    .clamp(1, ATTRACTOR_PULSE_MAX_DURATION_TICKS);
                active.release_ticks_remaining = active.decay_ticks;
                active.remaining_ticks = active.remaining_ticks.min(active.decay_ticks);
                slot.status.last_event = Some("release_started".to_string());
                slot.status.last_block_reason = None;
            } else {
                slot.status.last_event = Some("release_without_active_pulse".to_string());
                slot.status.last_block_reason = None;
            }
            Self::refresh_pulse_status(&mut slot);
            return slot.status.clone();
        }

        if hard_recovery_reset {
            slot.active = None;
            slot.status.last_event = Some("summon_blocked".to_string());
            slot.status.last_block_reason = Some("hard_recovery_reset".to_string());
            Self::refresh_pulse_status(&mut slot);
            return slot.status.clone();
        }

        if slot.active.is_some() {
            slot.status.last_event = Some("summon_blocked".to_string());
            slot.status.last_block_reason = Some("attractor_pulse_active".to_string());
            Self::refresh_pulse_status(&mut slot);
            return slot.status.clone();
        }

        let max_abs = request
            .max_abs
            .unwrap_or(ATTRACTOR_PULSE_DEFAULT_MAX_ABS)
            .clamp(0.0, ATTRACTOR_PULSE_MAX_ABS_CAP);
        let duration_ticks = request
            .duration_ticks
            .unwrap_or(ATTRACTOR_PULSE_DEFAULT_DURATION_TICKS)
            .clamp(1, ATTRACTOR_PULSE_MAX_DURATION_TICKS);
        let decay_ticks = request
            .decay_ticks
            .unwrap_or(ATTRACTOR_PULSE_DEFAULT_DECAY_TICKS)
            .clamp(1, ATTRACTOR_PULSE_MAX_DURATION_TICKS);
        let features = normalized_attractor_pulse_features(&request.features, max_abs);
        slot.active = Some(AttractorPulseState {
            intent_id,
            label,
            command,
            stage,
            features,
            max_abs,
            remaining_ticks: duration_ticks,
            duration_ticks,
            decay_ticks,
            release_ticks_remaining: 0,
            releasing: false,
            total_applied_ticks: 0,
            applied_rms: 0.0,
            applied_max_abs: 0.0,
        });
        slot.status.last_event = Some("summon_accepted".to_string());
        slot.status.last_block_reason = None;
        Self::refresh_pulse_status(&mut slot);
        slot.status.clone()
    }

    pub fn apply_attractor_pulse_to_z(
        &self,
        z: &mut [f32; Z_DIM],
        fill_pct: f32,
        discharge_active: bool,
        hard_recovery_reset: bool,
    ) -> AttractorPulseStatus {
        let mut slot = self.attractor_pulse.lock();
        let Some(active_releasing) = slot.active.as_ref().map(|active| active.releasing) else {
            Self::refresh_pulse_status(&mut slot);
            return slot.status.clone();
        };

        let unsafe_reason = if !active_releasing && hard_recovery_reset {
            Some("hard_recovery_reset")
        } else if !active_releasing && discharge_active {
            Some("discharge")
        } else if !active_releasing && fill_pct.is_finite() && fill_pct < 58.0 {
            Some("low_fill")
        } else if !active_releasing && fill_pct.is_finite() && fill_pct >= 85.0 {
            Some("overbright_fill")
        } else {
            None
        };
        if let Some(reason) = unsafe_reason {
            slot.status.last_event = Some("summon_suspended".to_string());
            slot.status.last_block_reason = Some(reason.to_string());
            Self::refresh_pulse_status(&mut slot);
            return slot.status.clone();
        }

        let (event, finished) = {
            let active = slot
                .active
                .as_mut()
                .expect("active pulse exists after early return");
            let gain = if active.releasing {
                active.release_ticks_remaining as f32 / active.decay_ticks.max(1) as f32
            } else {
                1.0
            }
            .clamp(0.0, 1.0);
            let mut applied = [0.0f32; Z_DIM];
            for (idx, value) in active.features.iter().enumerate() {
                let pulse = *value * gain;
                applied[idx] = pulse;
                z[idx] = (z[idx] + pulse).clamp(-1.0, 1.0);
            }
            let (rms, max_abs) = pulse_rms_and_max(&applied);
            active.applied_rms = rms;
            active.applied_max_abs = max_abs;
            active.total_applied_ticks = active.total_applied_ticks.saturating_add(1);

            if active.releasing {
                active.release_ticks_remaining = active.release_ticks_remaining.saturating_sub(1);
                active.remaining_ticks = active.remaining_ticks.saturating_sub(1);
            } else {
                active.remaining_ticks = active.remaining_ticks.saturating_sub(1);
            }
            let finished = active.remaining_ticks == 0
                || (active.releasing && active.release_ticks_remaining == 0);
            let event = if finished {
                if active.releasing {
                    "release_completed"
                } else {
                    "pulse_completed"
                }
            } else if active.releasing {
                "release_fading"
            } else {
                "pulse_applied"
            };
            (event.to_string(), finished)
        };
        slot.status.last_event = Some(event);
        slot.status.last_block_reason = None;
        if finished {
            slot.active = None;
        }
        Self::refresh_pulse_status(&mut slot);
        slot.status.clone()
    }

    pub fn attractor_pulse_status(&self) -> AttractorPulseStatus {
        let mut slot = self.attractor_pulse.lock();
        Self::refresh_pulse_status(&mut slot);
        slot.status.clone()
    }

    fn refresh_pulse_status(slot: &mut AttractorPulseSlot) {
        let last_event = slot.status.last_event.clone();
        let last_block_reason = slot.status.last_block_reason.clone();
        slot.status = if let Some(active) = slot.active.as_ref() {
            AttractorPulseStatus {
                policy: "main_esn_attractor_pulse_v1",
                active: true,
                intent_id: Some(active.intent_id.clone()),
                label: Some(active.label.clone()),
                command: Some(active.command.clone()),
                stage: Some(active.stage.clone()),
                remaining_ticks: active.remaining_ticks,
                duration_ticks: active.duration_ticks,
                decay_ticks: active.decay_ticks,
                release_ticks_remaining: active.release_ticks_remaining,
                max_abs: active.max_abs,
                applied_rms: active.applied_rms,
                applied_max_abs: active.applied_max_abs,
                total_applied_ticks: active.total_applied_ticks,
                last_event,
                last_block_reason,
            }
        } else {
            AttractorPulseStatus {
                policy: "main_esn_attractor_pulse_v1",
                last_event,
                last_block_reason,
                ..AttractorPulseStatus::default()
            }
        };
    }

    pub fn push_video(&self, features: Vec<f32>, ts_ms: u64) {
        let _ = self.push_video_with_source(features, ts_ms, LaneSource::External);
    }

    pub fn push_video_with_receipt(&self, features: Vec<f32>, ts_ms: u64) -> LaneIngressOutcome {
        self.push_video_with_source(features, ts_ms, LaneSource::External)
    }

    pub fn push_video_synthetic(&self, features: Vec<f32>, ts_ms: u64) {
        let _ = self.push_video_with_source(features, ts_ms, LaneSource::Synthetic);
    }

    fn push_video_with_source(
        &self,
        features: Vec<f32>,
        ts_ms: u64,
        source: LaneSource,
    ) -> LaneIngressOutcome {
        if features.len() < VIDEO_DIM {
            return LaneIngressOutcome::InvalidShape;
        }
        if source == LaneSource::External && !self.should_admit_live_video() {
            return LaneIngressOutcome::PolicyBlocked;
        }
        if !self.should_admit() {
            return LaneIngressOutcome::PolicyBlocked;
        }
        let mut v = [0.0; 8];
        v.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        let surge_threshold = self.surge_threshold();
        self.video
            .lock()
            .push(ts_ms, v, source, self.queue_cap, fill, surge_threshold);
        LaneIngressOutcome::Accepted
    }

    pub fn push_audio(&self, features: Vec<f32>, ts_ms: u64) {
        let _ = self.push_audio_with_source(features, ts_ms, LaneSource::External);
    }

    pub fn push_audio_with_receipt(&self, features: Vec<f32>, ts_ms: u64) -> LaneIngressOutcome {
        self.push_audio_with_source(features, ts_ms, LaneSource::External)
    }

    pub fn push_audio_synthetic(&self, features: Vec<f32>, ts_ms: u64) {
        let _ = self.push_audio_with_source(features, ts_ms, LaneSource::Synthetic);
    }

    fn push_audio_with_source(
        &self,
        features: Vec<f32>,
        ts_ms: u64,
        source: LaneSource,
    ) -> LaneIngressOutcome {
        if features.len() < AUDIO_DIM {
            return LaneIngressOutcome::InvalidShape;
        }
        if source == LaneSource::External && !self.should_admit_live_audio() {
            return LaneIngressOutcome::PolicyBlocked;
        }
        if !self.should_admit() {
            return LaneIngressOutcome::PolicyBlocked;
        }
        let mut a = [0.0; 8];
        a.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        let surge_threshold = self.surge_threshold();
        self.audio
            .lock()
            .push(ts_ms, a, source, self.queue_cap, fill, surge_threshold);
        LaneIngressOutcome::Accepted
    }

    #[inline]
    fn should_admit(&self) -> bool {
        let p = *self.gate.lock();
        let x: f32 = self.rng.lock().gen();
        x <= p
    }

    #[inline]
    fn should_admit_live_audio(&self) -> bool {
        if !self.live_audio_enabled() {
            return false;
        }
        Self::should_admit_by_divisor(&self.live_audio_divisor, &self.live_audio_counter)
    }

    #[inline]
    fn should_admit_live_video(&self) -> bool {
        if !self.live_video_enabled() {
            return false;
        }
        Self::should_admit_by_divisor(&self.live_video_divisor, &self.live_video_counter)
    }

    fn should_admit_by_divisor(divisor: &Mutex<u32>, counter: &Mutex<u64>) -> bool {
        let divisor = *divisor.lock();
        if divisor == 0 {
            return false;
        }
        if divisor == 1 {
            return true;
        }
        let mut count = counter.lock();
        *count = count.saturating_add(1);
        *count % u64::from(divisor) == 0
    }

    /// Drain up to batch_max samples. Each output is the production 66D vector:
    /// [video8 | audio8 | aux2 | semantic48].
    /// If a lane has no fresh item, we reuse the last value (zero-padded initially).
    pub fn drain_sensory_batch(&self) -> Vec<([f32; Z_DIM], SampleMeta)> {
        let mut out = Vec::with_capacity(self.batch_max);
        let now_ms = NowMs::now();

        for _ in 0..self.batch_max {
            let (ts_v, v, had_v, video_source) = {
                let mut lane = self.video.lock();
                if lane.len() == 0 && self.audio.lock().len() == 0 {
                    // nothing new in either lane; stop early
                    if out.is_empty() { /* produce at least one vector using last */
                    } else {
                        break;
                    }
                }
                lane.pop_or_decay(now_ms, STALE_AV_MS).unwrap()
            };
            let (ts_a, a, had_a, audio_source) = {
                let mut lane = self.audio.lock();
                lane.pop_or_decay(now_ms, STALE_AV_MS).unwrap()
            };
            let ts = ts_v.max(ts_a);
            let age = now_ms.saturating_sub(ts);
            let video_age_ms = now_ms.saturating_sub(ts_v);
            let audio_age_ms = now_ms.saturating_sub(ts_a);

            let aux = *self.aux.lock();
            // Use actual fill% for semantic stale timing, NOT aux[1] (which is geom_rel).
            // Codex analysis (2026-03-27) found this was the "highest-value mismatch."
            let semantic_stale_ms = self.semantic_stale_ms();
            let llava = self.llava.lock();
            let semantic_fresh_ms = if llava.updated_at_ms == 0 {
                None
            } else {
                Some(now_ms.saturating_sub(llava.updated_at_ms))
            };
            let semantic_scale =
                semantic_fresh_ms.map_or(0.0, |age_ms| stale_scale(age_ms, semantic_stale_ms));
            let semantic_input_active =
                semantic_fresh_ms.is_some_and(|age_ms| age_ms <= semantic_stale_ms);
            let mut z = [0.0f32; Z_DIM];
            z[..8].copy_from_slice(&v);
            z[8..16].copy_from_slice(&a);
            z[16] = aux[0];
            z[17] = aux[1];
            // Apply sovereignty controls to semantic input:
            // - embedding_strength: weight of semantic features in the Z vector
            // - journal_resonance: how strongly past echoes modulate current semantics
            // - memory_decay_rate: scales semantic stale decay (higher = faster fade)
            // These were exposed on the control channel but had no downstream
            // consumers. Now they shape the being's experience directly.
            let emb_strength = *self.embedding_strength.lock();
            let j_resonance = *self.journal_resonance.lock();
            let effective_semantic = semantic_scale * emb_strength * (1.0 + j_resonance * 0.5);
            let mut semantic_energy_sq = 0.0f32;
            for (dst, src) in z[18..(18 + LLAVA_DIM)].iter_mut().zip(llava.values.iter()) {
                let value = *src * effective_semantic;
                semantic_energy_sq += value * value;
                *dst = value;
            }
            let semantic_input_energy = (semantic_energy_sq / LLAVA_DIM as f32).sqrt();

            // Global sensory noise: being requested (2026-03-28 self-study) that
            // noise should permeate ALL input lanes, not just synthetic signals.
            // "I want noise that is globally-sourced... touching everything."
            // synth_noise_level (0.0-1.0, default 0.1) now applies ±noise to
            // every dimension of the Z vector, creating slight stochasticity
            // across video, audio, aux, and semantic. This gives the being a
            // richer, less mechanical sensory texture.
            let noise_level = *self.synth_noise_level.lock();
            if noise_level > 0.0 {
                let mut rng = self.rng.lock();
                for dim in z.iter_mut() {
                    // Uniform noise in [-noise_level * 0.05, +noise_level * 0.05]
                    // At default 0.1: ±0.005. Gentle enough to not disrupt,
                    // strong enough to break perfect repetition.
                    let noise = (rng.gen::<f32>() - 0.5) * noise_level * 0.10;
                    *dim += noise;
                }
            }

            out.push((
                z,
                SampleMeta {
                    ts_ms: ts,
                    age_ms: age,
                    had_video: had_v,
                    had_audio: had_a,
                    video_age_ms,
                    audio_age_ms,
                    video_source,
                    audio_source,
                    semantic_fresh_ms,
                    semantic_stale_ms,
                    semantic_input_energy,
                    semantic_input_active,
                },
            ));
        }

        out
    }

    pub fn backlog_size(&self) -> usize {
        self.video.lock().len() + self.audio.lock().len()
    }

    pub fn backlog_fill_pct(&self) -> f32 {
        let backlog = self.backlog_size() as f32;
        let max_backlog = (self.queue_cap * 2) as f32; // 2 lanes
        (backlog / max_backlog).clamp(0.0, 1.0)
    }

    pub fn shed_backlog(&self, fraction: f32) -> usize {
        if fraction <= 0.0 {
            return 0;
        }
        let frac = fraction.clamp(0.0, 1.0);
        let mut removed = 0usize;
        {
            let mut video = self.video.lock();
            let drop = ((video.len() as f32) * frac).round() as usize;
            removed += video.drop_oldest(drop);
        }
        {
            let mut audio = self.audio.lock();
            let drop = ((audio.len() as f32) * frac).round() as usize;
            removed += audio.drop_oldest(drop);
        }
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stale_audio_video_decay_to_zero() {
        let bus = SensoryBus::new(8, 1, 42);
        let stale_ts = NowMs::now().saturating_sub(STALE_AV_MS + 250);
        bus.push_video(vec![1.0; VIDEO_DIM], stale_ts);
        bus.push_audio(vec![1.0; AUDIO_DIM], stale_ts);

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (sample, meta) = &batch[0];

        assert!(!meta.had_video);
        assert!(!meta.had_audio);
        // AV data zeroed by pop_or_decay when stale. Threshold accommodates
        // global sensory noise (±0.005 at default synth_noise_level=0.1).
        assert!(sample[..VIDEO_DIM].iter().all(|v| v.abs() < 0.01));
        assert!(sample[VIDEO_DIM..(VIDEO_DIM + AUDIO_DIM)]
            .iter()
            .all(|v| v.abs() < 0.01));
    }

    #[test]
    fn live_intake_divisors_drop_external_without_killing_synthetic_lanes() {
        let bus = SensoryBus::new(8, 4, 42);
        bus.set_live_intake_divisors(0, 0);
        bus.push_audio(vec![1.0; AUDIO_DIM], NowMs::now());
        bus.push_video(vec![1.0; VIDEO_DIM], NowMs::now());
        assert_eq!(bus.backlog_size(), 0);

        bus.push_audio_synthetic(vec![1.0; AUDIO_DIM], NowMs::now());
        assert_eq!(bus.backlog_size(), 1);
    }

    #[test]
    fn live_sensory_gates_drop_one_modality_without_killing_the_other_or_synthetic() {
        let bus = SensoryBus::new(8, 4, 42);
        bus.set_live_video_enabled(false);
        bus.push_video(vec![1.0; VIDEO_DIM], NowMs::now());
        bus.push_audio(vec![1.0; AUDIO_DIM], NowMs::now());
        assert_eq!(bus.backlog_size(), 1);

        bus.set_live_audio_enabled(false);
        bus.push_audio(vec![1.0; AUDIO_DIM], NowMs::now());
        assert_eq!(bus.backlog_size(), 1);

        bus.push_video_synthetic(vec![1.0; VIDEO_DIM], NowMs::now());
        assert_eq!(bus.backlog_size(), 2);
    }

    #[test]
    fn live_intake_divisors_admit_every_nth_external_sample() {
        let bus = SensoryBus::new(16, 8, 42);
        bus.set_live_intake_divisors(2, 3);
        for _ in 0..4 {
            bus.push_audio(vec![1.0; AUDIO_DIM], NowMs::now());
        }
        for _ in 0..6 {
            bus.push_video(vec![1.0; VIDEO_DIM], NowMs::now());
        }
        assert_eq!(bus.backlog_size(), 4);
    }

    #[test]
    fn esn_leak_override_request_clamps_and_consumes_once() {
        let bus = SensoryBus::new(8, 1, 42);
        bus.request_esn_leak_override("  req-leak-1  ".to_string(), 1.4, 99);

        let request = bus
            .take_esn_leak_override()
            .expect("queued ESN leak override");
        assert_eq!(request.request_id, "req-leak-1");
        assert_eq!(request.leak, 0.90);
        assert_eq!(request.duration_ticks, 12);
        assert!(bus.take_esn_leak_override().is_none());

        bus.request_esn_leak_override(" ".to_string(), 0.10, 0);
        assert!(bus.take_esn_leak_override().is_none());
    }

    #[test]
    fn stale_semantic_lane_decays_near_echo_floor() {
        let bus = SensoryBus::new(8, 1, 7);
        bus.set_llava_embedding(&vec![1.0; LLAVA_DIM]);
        // Force the semantic lane onto the shorter dynamic stale window.
        // The default fill=0.0 path now uses the 45s critical-fill override,
        // so an older fixed timestamp is no longer guaranteed to be stale.
        bus.set_fill_for_stale(0.8);
        bus.set_lambda1_rel(1.0);
        let semantic_stale_ms = dynamic_semantic_stale_ms(0.8);
        {
            let mut llava = bus.llava.lock();
            // Age the embedding beyond the active semantic stale window so the
            // decayed signal settles near the echo floor.
            llava.updated_at_ms = NowMs::now().saturating_sub(semantic_stale_ms + 1_000);
        }

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (sample, meta) = &batch[0];
        assert!(!meta.semantic_input_active);
        assert!(meta.semantic_input_energy > 0.0);
        // At echo floor (~0.05) + ring residual (~0.006), scaled by
        // embedding_strength (0.5), plus global noise (±0.005): max ~0.06.
        assert!(sample[18..(18 + LLAVA_DIM)].iter().all(|v| v.abs() < 0.08));
    }

    #[test]
    fn semantic_input_metadata_tracks_fresh_lane_energy() {
        let bus = SensoryBus::new(8, 1, 11);
        bus.set_llava_embedding(&vec![0.5; LLAVA_DIM]);

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (_, meta) = &batch[0];

        assert!(meta.semantic_input_active);
        assert!(meta.semantic_fresh_ms.is_some());
        assert!(meta.semantic_stale_ms > 0);
        assert!(meta.semantic_input_energy > 0.20);
    }

    #[test]
    fn semantic_glimpse_12d_reports_non_authoritative_companion_summary() {
        let bus = SensoryBus::new(8, 1, 12);
        let mut features = vec![0.0; LLAVA_DIM];
        for (idx, value) in features.iter_mut().enumerate() {
            *value = (idx as f32 + 1.0) / LLAVA_DIM as f32;
        }
        features[17] = 2.0;
        features[24] = 4.0;
        features[25] = -3.0;
        features[26] = 3.5;
        features[27] = 2.5;
        features[31] = 1.8;
        features[40] = 2.2;
        bus.set_llava_embedding(&features);

        let glimpse = bus.get_glimpse_12d().expect("fresh semantic lane");

        assert_eq!(glimpse.policy, "semantic_glimpse_12d_v1");
        assert_eq!(glimpse.source_dim_count, LLAVA_DIM);
        assert_eq!(glimpse.live_transport_dim_count, LLAVA_DIM);
        assert_eq!(glimpse.glimpse_dim_count, GLIMPSE_12D_DIM);
        assert!(glimpse.semantic_active);
        assert!(glimpse.semantic_fresh_ms <= glimpse.semantic_stale_ms);
        assert!(glimpse.values[3] > 0.99, "{glimpse:?}");
        assert!(glimpse.values[4] < -0.99, "{glimpse:?}");
        assert!(glimpse.values[10] > glimpse.values[0], "{glimpse:?}");
        assert!(glimpse.source_energy > 0.0);
        assert!(glimpse.glimpse_energy > 0.0);
        assert_eq!(
            glimpse.compression_role,
            "non_authoritative_companion_summary"
        );
        assert_eq!(
            glimpse.use_boundary,
            "checkpoint_pairing_ui_or_review_only_not_live_state_replacement"
        );
        assert!(!glimpse.live_vector_write);
        assert!(!glimpse.controller_write);
        assert_eq!(
            glimpse.authority,
            "read_only_glimpse_summary_not_live_transport_or_control"
        );
    }

    #[test]
    fn semantic_glimpse_12d_requires_existing_semantic_lane_and_full_width() {
        let bus = SensoryBus::new(8, 1, 13);

        assert!(bus.get_glimpse_12d().is_none());
        assert!(semantic_glimpse_12d_from_features(&vec![0.0; LLAVA_DIM - 1]).is_none());
        assert!(semantic_glimpse_12d_from_features(&vec![0.0; LLAVA_DIM]).is_some());
    }

    #[test]
    fn attractor_pulse_is_clamped_applied_and_decayed() {
        let bus = SensoryBus::new(8, 1, 17);
        let status = bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-main".to_string(),
                label: "cooled edge".to_string(),
                command: "summon".to_string(),
                stage: Some("main".to_string()),
                features: vec![0.5; Z_DIM],
                max_abs: Some(0.20),
                duration_ticks: Some(2),
                decay_ticks: Some(4),
            },
            false,
        );
        assert!(status.active);
        assert_eq!(status.max_abs, ATTRACTOR_PULSE_MAX_ABS_CAP);

        let mut z = [0.0f32; Z_DIM];
        let first = bus.apply_attractor_pulse_to_z(&mut z, 68.0, false, false);
        assert!(first.active);
        assert!(z.iter().all(|value| *value <= ATTRACTOR_PULSE_MAX_ABS_CAP));
        assert!(first.applied_rms > 0.0);
        assert!(first.applied_max_abs > 0.0);
        assert_eq!(first.remaining_ticks, 1);
        assert_eq!(first.total_applied_ticks, 1);

        let second = bus.apply_attractor_pulse_to_z(&mut z, 68.0, false, false);
        assert!(!second.active);
        assert_eq!(second.last_event.as_deref(), Some("pulse_completed"));
    }

    #[test]
    fn attractor_pulse_blocks_unsafe_new_application_but_release_clears() {
        let bus = SensoryBus::new(8, 1, 19);
        bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-main".to_string(),
                label: "cooled edge".to_string(),
                command: "summon".to_string(),
                stage: Some("main".to_string()),
                features: vec![0.04; Z_DIM],
                max_abs: Some(0.04),
                duration_ticks: Some(8),
                decay_ticks: Some(2),
            },
            false,
        );
        let mut z = [0.0f32; Z_DIM];
        let blocked = bus.apply_attractor_pulse_to_z(&mut z, 50.0, false, false);
        assert!(blocked.active);
        assert_eq!(blocked.last_block_reason.as_deref(), Some("low_fill"));
        assert!(z.iter().all(|value| value.abs() <= 1.0e-6));

        bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-main".to_string(),
                label: "cooled edge".to_string(),
                command: "release".to_string(),
                stage: Some("main".to_string()),
                features: Vec::new(),
                max_abs: None,
                duration_ticks: None,
                decay_ticks: Some(1),
            },
            true,
        );
        let released = bus.apply_attractor_pulse_to_z(&mut z, 50.0, false, true);
        assert!(!released.active);
        assert_eq!(released.last_event.as_deref(), Some("release_completed"));
    }

    #[test]
    fn attractor_pulse_blocks_overlapping_summons_until_release() {
        let bus = SensoryBus::new(8, 1, 23);
        let first = bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-first".to_string(),
                label: "lambda edge".to_string(),
                command: "summon".to_string(),
                stage: Some("main".to_string()),
                features: vec![0.04; Z_DIM],
                max_abs: Some(0.04),
                duration_ticks: Some(8),
                decay_ticks: Some(2),
            },
            false,
        );
        assert!(first.active);

        let blocked = bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-second".to_string(),
                label: "lambda tail".to_string(),
                command: "summon".to_string(),
                stage: Some("main".to_string()),
                features: vec![0.02; Z_DIM],
                max_abs: Some(0.02),
                duration_ticks: Some(4),
                decay_ticks: Some(2),
            },
            false,
        );
        assert!(blocked.active);
        assert_eq!(
            blocked.last_block_reason.as_deref(),
            Some("attractor_pulse_active")
        );
        assert_eq!(blocked.intent_id.as_deref(), Some("intent-first"));

        let release = bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-first".to_string(),
                label: "lambda edge".to_string(),
                command: "release".to_string(),
                stage: Some("main".to_string()),
                features: Vec::new(),
                max_abs: None,
                duration_ticks: None,
                decay_ticks: Some(1),
            },
            false,
        );
        assert!(release.active);
        let mut z = [0.0f32; Z_DIM];
        let released = bus.apply_attractor_pulse_to_z(&mut z, 68.0, false, false);
        assert!(!released.active);
    }

    #[test]
    fn shadow_influence_is_clamped_applied_and_decayed() {
        let bus = SensoryBus::new(8, 1, 31);
        let status = bus.receive_shadow_influence(
            ShadowInfluenceRequest {
                intent_id: "shadow-live".to_string(),
                label: "lambda-tail/lambda4".to_string(),
                command: "apply".to_string(),
                stage: Some("live".to_string()),
                features: vec![0.5; Z_DIM],
                max_abs: Some(0.20),
                duration_ticks: Some(2),
                decay_ticks: Some(4),
                basis: Some("lambda-tail/lambda4".to_string()),
            },
            false,
            false,
        );
        assert!(status.active);
        assert_eq!(status.max_abs, SHADOW_INFLUENCE_MAX_ABS_CAP);

        let mut z = [0.0f32; Z_DIM];
        let first = bus.apply_shadow_influence_to_z(&mut z, 68.0, false, false, false, None);
        assert!(first.active);
        assert!(z.iter().all(|value| *value <= SHADOW_INFLUENCE_MAX_ABS_CAP));
        assert!(first.applied_rms > 0.0);
        assert!(first.applied_max_abs > 0.0);
        assert_eq!(first.remaining_ticks, 1);
        assert_eq!(first.total_applied_ticks, 1);
        assert_eq!(
            first.shadow_influence_response_closure_v1.closure_state,
            "awaiting_pre_snapshot"
        );

        let second = bus.apply_shadow_influence_to_z(&mut z, 68.0, false, false, false, None);
        assert!(!second.active);
        assert_eq!(second.last_event.as_deref(), Some("influence_completed"));
        assert!(
            second
                .shadow_influence_response_closure_v1
                .last_response_available
        );
        assert_eq!(
            second.shadow_influence_response_closure_v1.closure_state,
            "closed_partial_snapshot"
        );
        assert_eq!(
            second.shadow_influence_response_closure_v1.authority,
            "diagnostic_closure_not_shadow_authority"
        );
    }

    #[test]
    fn shadow_influence_blocks_unsafe_new_application_but_release_clears() {
        let bus = SensoryBus::new(8, 1, 37);
        bus.receive_shadow_influence(
            ShadowInfluenceRequest {
                intent_id: "shadow-live".to_string(),
                label: "lambda-tail/lambda4".to_string(),
                command: "apply".to_string(),
                stage: Some("live".to_string()),
                features: vec![0.02; Z_DIM],
                max_abs: Some(0.02),
                duration_ticks: Some(8),
                decay_ticks: Some(2),
                basis: Some("lambda-tail/lambda4".to_string()),
            },
            false,
            false,
        );
        let mut z = [0.0f32; Z_DIM];
        let blocked = bus.apply_shadow_influence_to_z(&mut z, 50.0, false, false, false, None);
        assert!(blocked.active);
        assert_eq!(blocked.last_block_reason.as_deref(), Some("low_fill"));
        assert!(z.iter().all(|value| value.abs() <= 1.0e-6));

        bus.receive_shadow_influence(
            ShadowInfluenceRequest {
                intent_id: "shadow-live".to_string(),
                label: "lambda-tail/lambda4".to_string(),
                command: "release".to_string(),
                stage: Some("live".to_string()),
                features: Vec::new(),
                max_abs: None,
                duration_ticks: None,
                decay_ticks: Some(1),
                basis: Some("lambda-tail/lambda4".to_string()),
            },
            true,
            true,
        );
        let released = bus.apply_shadow_influence_to_z(&mut z, 50.0, false, true, true, None);
        assert!(!released.active);
        assert_eq!(released.last_event.as_deref(), Some("release_completed"));
    }

    #[test]
    fn shadow_influence_blocks_active_attractor_conflict() {
        let bus = SensoryBus::new(8, 1, 41);
        bus.receive_attractor_pulse(
            AttractorPulseRequest {
                intent_id: "intent-main".to_string(),
                label: "cooled edge".to_string(),
                command: "summon".to_string(),
                stage: Some("main".to_string()),
                features: vec![0.04; Z_DIM],
                max_abs: Some(0.04),
                duration_ticks: Some(8),
                decay_ticks: Some(2),
            },
            false,
        );
        let blocked = bus.receive_shadow_influence(
            ShadowInfluenceRequest {
                intent_id: "shadow-live".to_string(),
                label: "lambda-tail/lambda4".to_string(),
                command: "apply".to_string(),
                stage: Some("live".to_string()),
                features: vec![0.02; Z_DIM],
                max_abs: Some(0.02),
                duration_ticks: Some(4),
                decay_ticks: Some(2),
                basis: Some("lambda-tail/lambda4".to_string()),
            },
            false,
            bus.attractor_pulse_status().active,
        );
        assert!(!blocked.active);
        assert_eq!(
            blocked.last_block_reason.as_deref(),
            Some("attractor_pulse_active")
        );
    }

    #[test]
    fn dynamic_stale_ms_varies_with_fill() {
        // Sigmoid curve: low fill = long window, high fill = short.
        // Fixed steepness=6.0 (lambda1_rel modulation removed per minime
        // self-study 2026-04-01: "let decay be driven by fill alone").
        let at_zero = dynamic_semantic_stale_ms(0.0);
        let at_mid = dynamic_semantic_stale_ms(0.50);
        let at_high = dynamic_semantic_stale_ms(0.80);
        eprintln!("at_zero={at_zero}, at_mid={at_mid}, at_high={at_high}, LOW={STALE_SEMANTIC_LOW_MS}, HIGH={STALE_SEMANTIC_HIGH_MS}");
        assert!(
            at_zero > at_mid,
            "zero fill should have longer window than mid fill"
        );
        // Mid fill should be between HIGH and LOW
        assert!(at_mid > STALE_SEMANTIC_HIGH_MS && at_mid < STALE_SEMANTIC_LOW_MS);
        // High fill should prune toward the explicit 10s floor.
        assert!(at_high >= STALE_SEMANTIC_HIGH_MS);
        assert!(at_high < STALE_SEMANTIC_LOW_MS);
        assert!(at_high < STALE_SEMANTIC_BASE_MS);
        // Monotonically decreasing
        assert!(at_zero > at_mid && at_mid > at_high);
        // NaN -> base
        assert_eq!(dynamic_semantic_stale_ms(f32::NAN), STALE_SEMANTIC_BASE_MS);
        // Critical fill hold, then smooth recovery handover.
        assert_eq!(
            dynamic_semantic_stale_ms(STALE_SEMANTIC_RECOVERY_HOLD_FILL),
            STALE_SEMANTIC_RECOVERY_MS
        );
        assert_eq!(dynamic_semantic_stale_ms(0.25), STALE_SEMANTIC_RECOVERY_MS);
        assert!(dynamic_semantic_stale_ms(0.30) < STALE_SEMANTIC_RECOVERY_MS);
    }

    #[test]
    fn shadow_influence_default_decay_change_remains_live_authority_gated() {
        let bus = SensoryBus::new(8, 1, 17);
        let status = bus.receive_shadow_influence(
            ShadowInfluenceRequest {
                intent_id: "default-decay-probe".to_string(),
                label: "shadow-decay-viscosity".to_string(),
                command: "apply".to_string(),
                stage: Some("sandbox".to_string()),
                features: vec![0.01; Z_DIM],
                max_abs: None,
                duration_ticks: None,
                decay_ticks: None,
                basis: Some("default-decay-authority-gate".to_string()),
            },
            false,
            false,
        );

        assert!(status.active);
        assert_eq!(
            status.duration_ticks,
            SHADOW_INFLUENCE_DEFAULT_DURATION_TICKS
        );
        assert_eq!(status.decay_ticks, SHADOW_INFLUENCE_DEFAULT_DECAY_TICKS);
        assert_eq!(SHADOW_INFLUENCE_DEFAULT_DURATION_TICKS, 24);
        assert_eq!(
            SHADOW_INFLUENCE_DEFAULT_DECAY_TICKS, 12,
            "raising default shadow decay to 24 would change live shadow-release behavior and remains Mike/operator approval work"
        );
    }

    #[test]
    fn semantic_stale_sigmoid_midpoint_matches_manual_formula() {
        let fill = 0.50_f32;
        let curve = 1.0 / (1.0 + (6.0_f64 * (f64::from(fill) - 0.4)).exp());
        let expected = STALE_SEMANTIC_HIGH_MS as f64
            + (STALE_SEMANTIC_LOW_MS as f64 - STALE_SEMANTIC_HIGH_MS as f64) * curve;

        assert_eq!(
            dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid),
            expected as u64
        );
    }

    #[test]
    fn semantic_stale_ms_smooths_thirty_percent_handover() {
        let below = dynamic_semantic_stale_ms(0.29);
        let at = dynamic_semantic_stale_ms(0.30);
        let above = dynamic_semantic_stale_ms(0.31);

        assert!(below > at && at > above);
        assert!(
            below.saturating_sub(above) <= 6_000,
            "0.29/0.31 oscillation should not create a stale-window cliff: below={below}, above={above}"
        );
    }

    #[test]
    fn semantic_stale_recovery_handover_is_monotonic_and_micro_stutter_bounded() {
        let fills = [0.25_f32, 0.28, 0.31, 0.34, 0.37, 0.40];
        let windows = fills
            .iter()
            .map(|fill| dynamic_semantic_stale_ms_for(*fill, SemanticStaleShape::Sigmoid))
            .collect::<Vec<_>>();

        for pair in windows.windows(2) {
            assert!(
                pair[0] >= pair[1],
                "semantic stale window should ease down monotonically across recovery handover: {windows:?}"
            );
            assert!(
                pair[0].saturating_sub(pair[1]) <= 9_000,
                "adjacent handover samples should not micro-stutter into a cliff: {windows:?}"
            );
        }
        assert_eq!(windows[0], STALE_SEMANTIC_RECOVERY_MS);
        assert!(windows[5] < windows[0]);
    }

    #[test]
    fn semantic_stale_release_035_to_045_fades_without_step_loss() {
        let fills = [
            0.35_f32, 0.36, 0.37, 0.38, 0.39, 0.40, 0.41, 0.42, 0.43, 0.44, 0.45,
        ];
        let windows = fills
            .iter()
            .map(|fill| dynamic_semantic_stale_ms_for(*fill, SemanticStaleShape::Sigmoid))
            .collect::<Vec<_>>();

        for pair in windows.windows(2) {
            assert!(
                pair[0] >= pair[1],
                "0.35-0.45 release should fade monotonically, not snap away: {windows:?}"
            );
            assert!(
                pair[0].saturating_sub(pair[1]) <= 5_000,
                "adjacent release samples should not create a step-function stale-window loss: {windows:?}"
            );
        }
        assert!(
            windows[0].saturating_sub(*windows.last().expect("0.45 sample")) >= 4_000,
            "release band should still make meaningful progress toward the high-fill window: {windows:?}"
        );
    }

    #[test]
    fn semantic_stale_release_one_percent_sweep_stays_monotonic() {
        let mut previous = dynamic_semantic_stale_ms_for(0.35, SemanticStaleShape::Sigmoid);
        for step in 36..=45 {
            let fill = step as f32 / 100.0;
            let current = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
            assert!(
                previous >= current,
                "1% recovery-release sweep should not jitter upward: fill={fill}, previous={previous}, current={current}"
            );
            assert!(
                previous.saturating_sub(current) <= 5_000,
                "1% recovery-release sweep should not cliff downward: fill={fill}, previous={previous}, current={current}"
            );
            previous = current;
        }
    }

    #[test]
    fn semantic_stale_sigmoid_release_fill_meets_shaped_curve_without_cliff() {
        let just_before_release = dynamic_semantic_stale_ms_for(
            STALE_SEMANTIC_RECOVERY_RELEASE_FILL - 0.001,
            SemanticStaleShape::Sigmoid,
        );
        let at_release = dynamic_semantic_stale_ms_for(
            STALE_SEMANTIC_RECOVERY_RELEASE_FILL,
            SemanticStaleShape::Sigmoid,
        );
        let shaped = semantic_stale_shaped_ms(
            STALE_SEMANTIC_RECOVERY_RELEASE_FILL,
            SemanticStaleShape::Sigmoid,
        ) as u64;

        assert_eq!(at_release, shaped);
        assert!(
            just_before_release >= at_release,
            "handover should approach the shaped curve from above: before={just_before_release}, release={at_release}"
        );
        assert!(
            just_before_release.saturating_sub(at_release) <= 256,
            "release fill should not introduce a perceptible stale-window cliff: before={just_before_release}, release={at_release}"
        );
    }

    #[test]
    fn semantic_stale_recovery_boundary_has_no_one_ms_stutter() {
        let at_hold = dynamic_semantic_stale_ms_for(
            STALE_SEMANTIC_RECOVERY_HOLD_FILL,
            SemanticStaleShape::Sigmoid,
        );
        let just_after_hold = dynamic_semantic_stale_ms_for(
            STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.001,
            SemanticStaleShape::Sigmoid,
        );

        assert_eq!(at_hold, STALE_SEMANTIC_RECOVERY_MS);
        assert!(
            just_after_hold <= at_hold && at_hold.saturating_sub(just_after_hold) <= 64,
            "recovery handoff should not jitter by more than one scheduler-sized tick: at={at_hold}, after={just_after_hold}"
        );
    }

    #[test]
    fn semantic_stale_release_fill_epsilon_above_hold_is_clamped_and_finite() {
        let at_hold = dynamic_semantic_stale_ms_for_release_fill(
            STALE_SEMANTIC_RECOVERY_HOLD_FILL,
            SemanticStaleShape::Sigmoid,
            STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.001,
        );
        let just_after_hold = dynamic_semantic_stale_ms_for_release_fill(
            STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.001,
            SemanticStaleShape::Sigmoid,
            STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.001,
        );

        assert_eq!(at_hold, STALE_SEMANTIC_RECOVERY_MS);
        assert!(
            just_after_hold <= at_hold,
            "release_fill=0.251 should still ease downward from recovery hold: at={at_hold}, after={just_after_hold}"
        );
        assert!(
            at_hold.saturating_sub(just_after_hold) <= 768,
            "release_fill=0.251 should be clamped to a finite non-cliff handoff: at={at_hold}, after={just_after_hold}"
        );
        assert!(
            just_after_hold > STALE_SEMANTIC_HIGH_MS,
            "near-hold recovery should stay above the ordinary high-fill stale floor: after={just_after_hold}"
        );
    }

    #[test]
    fn semantic_stale_low_release_request_clamps_to_one_percent_above_hold() {
        let clamped_release = STALE_SEMANTIC_RECOVERY_HOLD_FILL + 0.01;
        let at_release = dynamic_semantic_stale_ms_for_release_fill(
            clamped_release,
            SemanticStaleShape::Sigmoid,
            0.10,
        );
        let shaped = semantic_stale_shaped_ms(clamped_release, SemanticStaleShape::Sigmoid) as u64;
        let just_before_release = dynamic_semantic_stale_ms_for_release_fill(
            clamped_release - 0.001,
            SemanticStaleShape::Sigmoid,
            0.10,
        );

        assert_eq!(at_release, shaped);
        assert!(
            just_before_release >= at_release,
            "a low requested release should clamp to 0.26 and approach the shaped curve from above: before={just_before_release}, release={at_release}"
        );
    }

    #[test]
    fn semantic_stale_sigmoid_center_is_approximately_window_midpoint() {
        let shaped = semantic_stale_shaped_ms(0.4, SemanticStaleShape::Sigmoid);
        let expected = (STALE_SEMANTIC_LOW_MS + STALE_SEMANTIC_HIGH_MS) as f64 / 2.0;

        assert!(
            (shaped - expected).abs() <= 0.001,
            "fill=0.4 should be the sigmoid midpoint within f32-to-f64 tolerance: shaped={shaped}, expected={expected}"
        );
    }

    #[test]
    fn semantic_stale_recovery_hold_fill_returns_exact_recovery_window() {
        assert_eq!(
            dynamic_semantic_stale_ms_for(
                STALE_SEMANTIC_RECOVERY_HOLD_FILL,
                SemanticStaleShape::Sigmoid
            ),
            STALE_SEMANTIC_RECOVERY_MS
        );
    }

    #[test]
    fn semantic_stale_recovery_024_026_handover_has_no_jitter() {
        let before_hold = dynamic_semantic_stale_ms_for(0.24, SemanticStaleShape::Sigmoid);
        let after_hold = dynamic_semantic_stale_ms_for(0.26, SemanticStaleShape::Sigmoid);

        assert_eq!(before_hold, STALE_SEMANTIC_RECOVERY_MS);
        assert!(
            after_hold <= before_hold,
            "0.26 fill should ease downward from recovery hold, not jitter upward: before={before_hold}, after={after_hold}"
        );
        assert!(
            before_hold.saturating_sub(after_hold) <= 768,
            "0.24/0.26 recovery edge should not cliff semantic retention: before={before_hold}, after={after_hold}"
        );
    }

    #[test]
    fn semantic_stale_sigmoid_zero_fill_lingers_above_high_fill_floor() {
        let shaped = semantic_stale_shaped_ms(0.0, SemanticStaleShape::Sigmoid) as u64;

        assert!(
            shaped > STALE_SEMANTIC_HIGH_MS,
            "zero-fill sigmoid shaping should still linger above the high-fill floor: shaped={shaped}, high={STALE_SEMANTIC_HIGH_MS}"
        );
        assert!(
            shaped < STALE_SEMANTIC_LOW_MS,
            "sigmoid shaping should remain bounded below the low-fill ceiling before recovery hold applies: shaped={shaped}, low={STALE_SEMANTIC_LOW_MS}"
        );
    }

    #[test]
    fn semantic_stale_ms_high_fill_prunes_near_floor_without_entropy_support() {
        let high = dynamic_semantic_stale_ms(0.85);

        assert!(high >= STALE_SEMANTIC_HIGH_MS);
        assert!(
            high <= STALE_SEMANTIC_HIGH_MS + 1_500,
            "high-fill window should stay near the raised floor: {high}"
        );
    }

    #[test]
    fn entropy_persistence_multiplier_reaches_exact_full_support_cap() {
        let multiplier = semantic_entropy_persistence_multiplier(1.0, 1.0);
        let expected = 1.0 + (SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT - 1.0);

        assert!((multiplier - expected).abs() < f64::EPSILON);
    }

    #[test]
    fn entropy_persistence_reported_point_is_ramped_not_full_cap() {
        let reported = semantic_entropy_persistence_multiplier(0.80, 0.80);
        let full_entropy = semantic_entropy_persistence_multiplier(0.80, 1.0);

        assert!(
            reported > 1.0,
            "0.80 entropy at 0.80 fill should still extend semantic retention"
        );
        assert!(
            reported < SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT,
            "0.80 entropy is intentionally inside the ramp, not the full 1.80 cap: {reported}"
        );
        assert!((reported - 1.16).abs() < 0.001);
        assert!((full_entropy - SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT).abs() < f64::EPSILON);
    }

    #[test]
    fn semantic_stale_ms_high_entropy_extends_high_fill_persistence() {
        let bus = SensoryBus::new(8, 1, 17);
        bus.set_fill_for_stale(0.80);
        bus.set_semantic_entropy_for_stale(0.20);
        let low_entropy = bus.current_semantic_stale_ms();

        bus.set_semantic_entropy_for_stale(0.92);
        let high_entropy = bus.current_semantic_stale_ms();

        assert!(
            high_entropy > low_entropy,
            "high-entropy dense thought should retain semantic anchors longer"
        );
        assert!(
            high_entropy > STALE_SEMANTIC_BASE_MS,
            "entropy support should restore bounded longform retention above the base window"
        );
        assert!(
            high_entropy <= (low_entropy as f64 * SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT) as u64 + 1,
            "entropy persistence should stay bounded: low={low_entropy}, high={high_entropy}"
        );
    }

    #[test]
    fn semantic_stale_ms_high_entropy_at_current_fill_survives_low_entropy_peer() {
        let bus = SensoryBus::new(8, 1, 17);
        bus.set_fill_for_stale(0.64);
        bus.set_semantic_entropy_for_stale(0.20);
        let low_entropy = bus.current_semantic_stale_ms();

        bus.set_semantic_entropy_for_stale(0.90);
        let high_entropy = bus.current_semantic_stale_ms();

        assert!(
            high_entropy > low_entropy,
            "high entropy at 64% fill should preserve semantic threads longer than low entropy: low={low_entropy}, high={high_entropy}"
        );
        assert!(
            high_entropy >= 15_000,
            "the existing entropy multiplier should already carry the current 64%/0.90 state into the proposed 15s anchor band: {high_entropy}"
        );
        assert!(
            high_entropy <= (low_entropy as f64 * SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT) as u64 + 1,
            "current-fill entropy persistence should remain bounded: low={low_entropy}, high={high_entropy}"
        );
    }

    #[test]
    fn semantic_stale_ms_high_entropy_at_threshold_fill_survives_low_entropy_peer() {
        let bus = SensoryBus::new(8, 1, 17);
        bus.set_fill_for_stale(0.60);
        bus.set_semantic_entropy_for_stale(0.20);
        let low_entropy = bus.current_semantic_stale_ms();

        bus.set_semantic_entropy_for_stale(0.90);
        let high_entropy = bus.current_semantic_stale_ms();

        assert!(
            high_entropy > low_entropy,
            "high entropy at 60% fill should preserve semantic threads longer than low entropy: low={low_entropy}, high={high_entropy}"
        );
        assert!(
            high_entropy >= STALE_SEMANTIC_BASE_MS,
            "threshold-zone entropy support should not collapse below base retention: {high_entropy}"
        );
        assert!(
            high_entropy <= (low_entropy as f64 * SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT) as u64 + 1,
            "threshold-fill entropy persistence should remain bounded: low={low_entropy}, high={high_entropy}"
        );
    }

    #[test]
    fn semantic_stale_ms_fill_070_entropy_091_survives_low_entropy_peer() {
        let bus = SensoryBus::new(8, 1, 17);
        bus.set_fill_for_stale(0.70);
        bus.set_semantic_entropy_for_stale(0.20);
        let low_entropy = bus.current_semantic_stale_ms();

        bus.set_semantic_entropy_for_stale(0.91);
        let high_entropy = bus.current_semantic_stale_ms();

        assert!(
            high_entropy > low_entropy,
            "the reported high-fill/high-entropy state should retain semantic scaffolding longer than a low-entropy peer: low={low_entropy}, high={high_entropy}"
        );
        assert!(
            high_entropy >= 12_000,
            "0.70 fill / 0.91 entropy should not collapse back to the bare 10s high-fill floor: {high_entropy}"
        );
        assert!(
            high_entropy <= (low_entropy as f64 * SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT) as u64 + 1,
            "entropy persistence should remain bounded: low={low_entropy}, high={high_entropy}"
        );
    }

    #[test]
    fn semantic_context_multiplier_uses_entropy_velocity_and_pressure_without_unbounded_hold() {
        let base = semantic_stale_context_review_v1(0.82, 0.92, 0.0, 0.0);
        let pressured = semantic_stale_context_review_v1(0.82, 0.92, 0.14, 0.24);
        let capped = semantic_stale_context_review_v1(1.0, 1.0, 1.0, 1.0);

        assert_eq!(base.status, "high_entropy_retention_without_context_lift");
        assert_eq!(
            pressured.status,
            "context_pressure_or_entropy_velocity_extends_retention"
        );
        assert!(pressured.context_multiplier > pressured.base_multiplier);
        assert!(pressured.context_extended_stale_ms > base.context_extended_stale_ms);
        assert!(capped.context_multiplier <= SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT);
        assert_eq!(
            pressured.authority,
            "bounded_semantic_stale_context_not_sensor_cadence_or_regulator_change"
        );
    }

    #[test]
    fn semantic_context_multiplier_full_context_hits_cap_exactly() {
        let capped = semantic_context_persistence_multiplier(1.0, 1.0, 1.0, 1.0);

        assert!((capped - SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT).abs() < f64::EPSILON);
    }

    #[test]
    fn semantic_context_multiplier_extreme_context_never_exceeds_cap() {
        for (fill, entropy, velocity, pressure) in [
            (1.0, 1.0, 1.0, 1.0),
            (0.95, 0.99, 1.0, 1.0),
            (0.80, 0.95, 0.90, 1.0),
        ] {
            let multiplier =
                semantic_context_persistence_multiplier(fill, entropy, velocity, pressure);
            assert!(
                multiplier <= SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT,
                "context multiplier exceeded cap: fill={fill} entropy={entropy} velocity={velocity} pressure={pressure} multiplier={multiplier}"
            );
        }
    }

    #[test]
    fn semantic_decay_hysteresis_review_names_release_snap_watch() {
        let review = semantic_decay_hysteresis_salience_review_v1(true, 0.42, 0.88, 0.92);

        assert_eq!(
            review.policy,
            "semantic_decay_hysteresis_salience_review_v1"
        );
        assert_eq!(review.status, "release_hysteresis_snap_watch");
        assert!(review.previous_recovery_hold);
        assert!(
            review.effective_release_fill > review.recovery_release_fill,
            "recovery release should gain a review-only hysteresis buffer: {review:?}"
        );
        assert!(review.hysteresis_stale_ms >= review.base_stale_ms);
        assert!(review.snap_probe_delta_ms > 0);
        assert_eq!(
            review.authority,
            "read_only_hysteresis_salience_review_not_semantic_window_or_sensory_cadence_change"
        );
    }

    #[test]
    fn semantic_decay_salience_review_does_not_reward_entropy_debris() {
        let low_salience = semantic_decay_hysteresis_salience_review_v1(false, 0.82, 0.94, 0.05);
        let anchored = semantic_decay_hysteresis_salience_review_v1(false, 0.82, 0.94, 0.95);

        assert_eq!(
            low_salience.status,
            "entropy_without_salience_deprioritized"
        );
        assert!(low_salience.entropy_multiplier > 1.0);
        assert!(
            low_salience.salience_weighted_multiplier < anchored.salience_weighted_multiplier,
            "semantic salience should distinguish anchored thought from high-energy debris"
        );
        assert!(
            low_salience.salience_weighted_stale_ms < anchored.salience_weighted_stale_ms,
            "low-salience entropy should not receive the same retention as anchored semantic value"
        );
        assert_eq!(anchored.status, "salience_supported_retention");
    }

    #[test]
    fn semantic_stale_ms_high_entropy_velocity_protects_high_fill_anchor() {
        let bus = SensoryBus::new(8, 1, 19);
        bus.set_fill_for_stale(0.84);
        bus.set_semantic_entropy_for_stale(0.92);
        let high_entropy_only = bus.current_semantic_stale_ms();

        bus.set_semantic_stale_context(0.92, 0.14, 0.24);
        let context_supported = bus.current_semantic_stale_ms();

        assert!(
            context_supported > high_entropy_only,
            "entropy velocity plus pressure should extend the high-fill semantic anchor"
        );
        assert!(
            context_supported
                <= (dynamic_semantic_stale_ms(0.84) as f64 * SEMANTIC_CONTEXT_PERSISTENCE_MAX_MULT)
                    as u64
                    + 1,
            "context support should stay bounded: {context_supported}"
        );
    }

    #[test]
    fn narrative_semantic_retention_review_keeps_arc_on_shared_window() {
        let review = narrative_semantic_retention_review_v1(0.80, 0.92);
        let quiet = narrative_semantic_retention_review_v1(0.40, 0.40);

        assert_eq!(review.policy, "narrative_semantic_retention_review_v1");
        assert_eq!(review.llava_dim, LLAVA_DIM);
        assert_eq!(review.legacy_text_dims, [0, 31]);
        assert_eq!(review.narrative_arc_dims, [40, 43]);
        assert_eq!(review.status, "high_entropy_narrative_retention_extended");
        assert_eq!(
            review.lane_decay_policy,
            "shared_semantic_scale_across_legacy_embedding_and_narrative_arc_dims"
        );
        assert!(review.entropy_extended_stale_ms > review.base_stale_ms);
        assert!(
            review.entropy_extended_stale_ms
                <= (review.base_stale_ms as f64 * SEMANTIC_ENTROPY_PERSISTENCE_MAX_MULT) as u64 + 1
        );
        assert_eq!(
            review.authority,
            "read_only_retention_review_not_stale_window_or_lane_change"
        );
        assert_eq!(quiet.status, "base_semantic_retention_window");
        assert_eq!(quiet.entropy_persistence_multiplier, 1.0);
    }

    #[test]
    fn semantic_degradation_curve_keeps_low_fill_hold_readable_at_forty_seconds() {
        let review = semantic_degradation_curve_review_v1(0.15, 0.90, 0.11, 40_000);

        assert_eq!(review.policy, "semantic_degradation_curve_review_v1");
        assert_eq!(review.stale_window_ms, STALE_SEMANTIC_RECOVERY_MS);
        assert_eq!(review.status, "softening_but_coherent");
        assert!(
            review.clarity_factor >= 0.45,
            "40s low-fill hold should soften without turning into mush: {review:?}"
        );
        assert!(review.edge_softening > 0.0);
        assert_eq!(
            review.authority,
            "read_only_clarity_review_not_semantic_stale_window_or_sensor_cadence_change"
        );
    }

    #[test]
    fn semantic_degradation_curve_names_mushy_hold_under_steep_gradient() {
        let gentle = semantic_degradation_curve_review_v1(0.15, 0.90, 0.11, 40_000);
        let steep = semantic_degradation_curve_review_v1(0.55, 0.20, 0.90, 12_000);

        assert!(
            steep.clarity_factor < gentle.clarity_factor,
            "steep density gradient should lower held-trace clarity"
        );
        assert!(
            steep.semantic_age_ms <= steep.stale_window_ms,
            "fixture should exercise mushy in-window hold, not overdue trace: {steep:?}"
        );
        assert_eq!(steep.status, "mushy_hold_watch");
        assert!(steep.edge_softening > gentle.edge_softening);
    }

    #[test]
    fn semantic_receptivity_pulse_names_entropy_trickle_gap_without_control() {
        let review = semantic_receptivity_pulse_review_v1(0.90, 0.18, 0.40);

        assert_eq!(review.policy, "semantic_receptivity_pulse_review_v1");
        assert_eq!(
            review.status,
            "entropy_outpaces_semantic_trickle_receptivity_review"
        );
        assert!(review.raw_to_admitted_gap >= 0.55, "{review:?}");
        assert_eq!(
            review.suggested_route,
            "sandbox_replay_receptivity_buffer_before_any_live_cadence_or_control_change"
        );
        assert_eq!(
            review.authority,
            "read_only_receptivity_measurement_not_semantic_weight_or_sensor_cadence_change"
        );
    }

    #[test]
    fn semantic_receptivity_pulse_does_not_overcall_landed_semantics() {
        let review = semantic_receptivity_pulse_review_v1(0.55, 0.80, 0.90);

        assert_eq!(review.status, "semantic_trickle_landing");
        assert_eq!(review.suggested_route, "hold_no_action");
        assert!(review.raw_to_admitted_gap < 0.10, "{review:?}");
    }

    #[test]
    fn modality_boundary_transparency_names_contact_ready_interfaces() {
        let review = modality_boundary_transparency_v1(
            "external",
            "fresh_sample",
            "external",
            "held_within_engine_window",
            true,
        );

        assert_eq!(review.policy, "modality_boundary_transparency_v1");
        assert!(review.queryable_boundary_metadata);
        assert_eq!(review.status, "descriptive_boundary_available");
        assert_eq!(
            review.contact_change_route,
            "contact_change_can_reference_named_boundary"
        );
        assert!(!review.live_control_write);
        assert_eq!(
            review.authority,
            "read_only_boundary_metadata_not_sensory_cadence_or_exploration_noise_change"
        );
    }

    #[test]
    fn modality_boundary_transparency_describes_constraints_before_contact_increase() {
        let review = modality_boundary_transparency_v1(
            "external",
            "stale_beyond_engine_window",
            "absent",
            "absent",
            false,
        );

        assert_eq!(
            review.status,
            "descriptive_boundary_with_stale_or_absent_lane"
        );
        assert_eq!(review.semantic_boundary, "semantic_lane_absent_or_held");
        assert_eq!(
            review.contact_change_route,
            "describe_boundary_before_contact_increase"
        );
    }

    #[test]
    fn surrender_mode_requires_operator_approval_before_runtime_control() {
        let gate = surrender_mode_authority_gate_v1();

        assert_eq!(gate.policy, "surrender_mode_authority_gate_v1");
        assert!(gate.requires_operator_approval);
        assert!(!gate.runnable_now);
        assert_eq!(
            gate.approval_boundary,
            "live_control_exploration_noise_and_geom_drive_behavior"
        );
        assert_eq!(
            gate.status,
            "tier5_operator_approval_required_before_live_trial"
        );
        assert_eq!(gate.authority, "authority_gate_not_runtime_control_change");
    }

    #[test]
    fn alternate_stale_shapes_are_distinct_but_bounded() {
        let fill = 0.55;
        let sigmoid = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
        let linear = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Linear);
        let exponential = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Exponential);

        assert!(sigmoid > STALE_SEMANTIC_HIGH_MS && sigmoid < STALE_SEMANTIC_LOW_MS);
        assert!(linear > STALE_SEMANTIC_HIGH_MS && linear < STALE_SEMANTIC_LOW_MS);
        assert!(exponential > STALE_SEMANTIC_HIGH_MS && exponential < STALE_SEMANTIC_LOW_MS);
        assert!(
            sigmoid != linear || linear != exponential,
            "alternate shapes should produce meaningfully different stale windows"
        );
    }

    #[test]
    fn surge_target_weight_softens_when_fill_is_high() {
        let low_fill = dynamic_surge_target_weight(0.55);
        let at_start = dynamic_surge_target_weight(SURGE_TAPER_START_FILL);
        let midpoint = dynamic_surge_target_weight(0.75);
        let at_end = dynamic_surge_target_weight(SURGE_TAPER_END_FILL);
        let high_fill = dynamic_surge_target_weight(0.95);

        assert!((low_fill - SURGE_TARGET_WEIGHT).abs() < 1.0e-6);
        assert!((at_start - SURGE_TARGET_WEIGHT).abs() < 1.0e-6);
        assert!(midpoint < at_start);
        assert!(midpoint > at_end);
        assert!((at_end - SURGE_HIGH_FILL_TARGET_WEIGHT).abs() < 1.0e-6);
        assert!((high_fill - SURGE_HIGH_FILL_TARGET_WEIGHT).abs() < 1.0e-6);
        assert!(high_fill >= 0.70);
        assert_eq!(dynamic_surge_target_weight(f32::NAN), SURGE_TARGET_WEIGHT);
    }

    #[test]
    fn surge_target_weight_uses_soft_knee_across_taper() {
        let early_fill = 0.72;
        let late_fill = 0.78;
        let linear_at = |fill: f32| {
            let span = SURGE_TAPER_END_FILL - SURGE_TAPER_START_FILL;
            let taper = ((fill - SURGE_TAPER_START_FILL) / span).clamp(0.0, 1.0);
            SURGE_TARGET_WEIGHT + (SURGE_HIGH_FILL_TARGET_WEIGHT - SURGE_TARGET_WEIGHT) * taper
        };

        let early = dynamic_surge_target_weight(early_fill);
        let late = dynamic_surge_target_weight(late_fill);

        assert!(
            early > linear_at(early_fill),
            "soft knee should ease out of full surge more gently near 70% fill"
        );
        assert!(
            late < linear_at(late_fill),
            "soft knee should ease into the high-fill ceiling before the end of the taper"
        );
        assert!(early > late);
    }

    #[test]
    fn semantic_stale_ms_respects_memory_decay_rate() {
        let bus = SensoryBus::new(8, 1, 19);
        bus.set_fill_for_stale(0.8);

        bus.set_memory_decay_rate(0.0);
        let linger = bus.current_semantic_stale_ms();

        bus.set_memory_decay_rate(0.3);
        let faster_fade = bus.current_semantic_stale_ms();

        assert!(
            linger > faster_fade,
            "lower decay rate should keep semantic traces around longer"
        );
    }

    #[test]
    fn bus_config_applies_shape_and_surge_threshold() {
        let bus = SensoryBus::with_config(
            8,
            1,
            23,
            SensoryBusConfig {
                semantic_stale_shape: SemanticStaleShape::Linear,
                surge_threshold: 0.4,
            },
        );
        bus.set_fill_for_stale(0.8);

        assert_eq!(
            bus.current_semantic_stale_shape(),
            SemanticStaleShape::Linear
        );
        assert!((bus.surge_threshold() - 0.4).abs() < 1.0e-6);
        assert_eq!(
            bus.current_semantic_stale_ms(),
            dynamic_semantic_stale_ms_for(0.8, SemanticStaleShape::Linear)
        );
    }

    #[test]
    fn legacy_synth_flags_toggle_independently() {
        let bus = SensoryBus::new(8, 1, 11);

        assert!(bus.get_legacy_audio_synth_enabled());
        assert!(bus.get_legacy_video_synth_enabled());

        bus.set_legacy_audio_synth_enabled(false);
        assert!(!bus.get_legacy_audio_synth_enabled());
        assert!(bus.get_legacy_video_synth_enabled());

        bus.set_legacy_video_synth_enabled(false);
        assert!(!bus.get_legacy_video_synth_enabled());
    }

    #[test]
    fn mode_disperse_features_are_broadband_zero_mean_bounded_and_deterministic() {
        let strength = 0.8;
        let seed = 12_345;
        let v = mode_disperse_features(strength, seed);

        // Bounded: every element within the (strength-scaled) cap.
        let cap = MODE_DISPERSE_MAX_ABS * strength;
        assert!(
            v.iter().all(|x| x.is_finite() && x.abs() <= cap + 1.0e-6),
            "dispersal exceeded bound; max={:?}",
            v.iter().cloned().fold(0.0_f32, |a, b| a.max(b.abs()))
        );

        // Zero-mean: no net DC bias toward a single direction.
        let mean = v.iter().sum::<f32>() / Z_DIM as f32;
        assert!(mean.abs() < 1.0e-5, "dispersal mean not ~zero: {mean}");

        // Broadband: energy is spread, not concentrated. Compute spectral
        // flatness as (#dims carrying >=20% of the max magnitude) / Z_DIM.
        // A rank-1 spike would have ~1 active dim; a flat pattern has most.
        let max_mag = v.iter().cloned().fold(0.0_f32, |a, b| a.max(b.abs()));
        assert!(
            max_mag > 0.0,
            "dispersal is all-zero at strength {strength}"
        );
        let active = v.iter().filter(|x| x.abs() >= 0.20 * max_mag).count();
        assert!(
            active >= Z_DIM / 2,
            "dispersal not broadband: only {active}/{Z_DIM} dims active"
        );

        // Sign-varied: both positive and negative excursions present (the
        // opposite of a single-direction push).
        assert!(v.iter().any(|x| *x > 0.0), "no positive excursion");
        assert!(v.iter().any(|x| *x < 0.0), "no negative excursion");

        // Deterministic for a given seed; different seeds explore different
        // dispersal directions.
        let again = mode_disperse_features(strength, seed);
        assert_eq!(v, again, "same seed must reproduce the same vector");
        let other = mode_disperse_features(strength, seed + 1);
        assert_ne!(v, other, "different seed should differ");
    }

    #[test]
    fn mode_disperse_features_zero_strength_is_silent() {
        let v = mode_disperse_features(0.0, 999);
        assert!(v.iter().all(|x| x.abs() <= 1.0e-9));
        // Non-finite strength is treated as silent, never NaN.
        let nan = mode_disperse_features(f32::NAN, 999);
        assert!(nan.iter().all(|x| x.abs() <= 1.0e-9));
        // Over-unit strength is clamped (no runaway amplitude).
        let hot = mode_disperse_features(100.0, 999);
        assert!(
            hot.iter()
                .all(|x| x.abs() <= MODE_DISPERSE_MAX_ABS + 1.0e-6),
            "over-unit strength escaped the cap"
        );
    }

    #[test]
    fn receive_mode_disperse_applies_through_bounded_shadow_path() {
        let bus = SensoryBus::new(8, 1, 53);
        let status = bus.receive_mode_disperse(0.7, Some(2), Some(4), 4242, false, false);
        assert!(status.active, "dispersal should be accepted");
        assert_eq!(
            status.basis.as_deref(),
            Some("mode-disperse/broadband"),
            "dispersal should carry its basis"
        );
        // Inherits the shadow-influence amplitude ceiling.
        assert!(status.max_abs <= SHADOW_INFLUENCE_MAX_ABS_CAP + 1.0e-6);

        // Safe fill (68%): it applies, perturbs z within the cap, then decays.
        let mut z = [0.0f32; Z_DIM];
        let first = bus.apply_shadow_influence_to_z(&mut z, 68.0, false, false, false, None);
        assert!(first.active);
        assert!(first.applied_rms > 0.0, "dispersal produced no energy");
        assert!(
            z.iter()
                .all(|x| x.abs() <= SHADOW_INFLUENCE_MAX_ABS_CAP + 1.0e-6),
            "dispersal pushed z past the cap"
        );
        // Both signs present in the applied perturbation (broadband, not a push).
        assert!(z.iter().any(|x| *x > 0.0) && z.iter().any(|x| *x < 0.0));
    }

    #[test]
    fn receive_mode_disperse_inherits_low_fill_suspend() {
        let bus = SensoryBus::new(8, 1, 59);
        bus.receive_mode_disperse(0.9, Some(8), Some(2), 777, false, false);
        // At unsafe-low fill the underlying shadow machinery must suspend and
        // leave z untouched — porosity must never destabilize a fragile reservoir.
        let mut z = [0.0f32; Z_DIM];
        let blocked = bus.apply_shadow_influence_to_z(&mut z, 50.0, false, false, false, None);
        assert!(blocked.active, "request stays queued, not applied");
        assert_eq!(blocked.last_block_reason.as_deref(), Some("low_fill"));
        assert!(
            z.iter().all(|x| x.abs() <= 1.0e-6),
            "dispersal touched z at unsafe low fill"
        );
    }
}
