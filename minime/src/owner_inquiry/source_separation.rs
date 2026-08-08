use serde_json::{json, Value};

use super::texture_dynamics::texture_dynamics_snapshot_v1;
use crate::{
    owner_inquiry_wire::OwnerInquiryV1,
    regulator::{
        resonance_viscosity_index_with_entropy, temporal_drag_coefficient,
        viscosity_persistence_coefficient, PressureSourceComponents, PressureSourceContext,
        PressureSourceV1,
    },
    sensory_bus::{semantic_degradation_curve_review_v1, semantic_stale_context_review_v1},
};

const AXIS_LEVELS: [f32; 3] = [0.2, 0.5, 0.8];
pub(super) const FIXED_FILL: f32 = 0.68;

#[derive(Debug, Clone)]
pub(super) struct SourceAxes {
    pub(super) pressure: f32,
    pub(super) gradient: f32,
    pub(super) entropy: f32,
    pub(super) persistence: f32,
    pub(super) packing: f32,
    pub(super) porosity: f32,
    pub(super) distinguishability_loss: f32,
}

#[derive(Debug, Clone, Copy)]
enum SourceAxis {
    Pressure,
    Gradient,
    Entropy,
    Persistence,
    Packing,
    Porosity,
    DistinguishabilityLoss,
}

impl SourceAxis {
    const ALL: [Self; 7] = [
        Self::Pressure,
        Self::Gradient,
        Self::Entropy,
        Self::Persistence,
        Self::Packing,
        Self::Porosity,
        Self::DistinguishabilityLoss,
    ];

    const fn name(self) -> &'static str {
        match self {
            Self::Pressure => "pressure",
            Self::Gradient => "gradient",
            Self::Entropy => "entropy",
            Self::Persistence => "persistence",
            Self::Packing => "packing",
            Self::Porosity => "porosity",
            Self::DistinguishabilityLoss => "distinguishability_loss",
        }
    }

    fn set(self, axes: &mut SourceAxes, value: f32) {
        match self {
            Self::Pressure => axes.pressure = value,
            Self::Gradient => axes.gradient = value,
            Self::Entropy => axes.entropy = value,
            Self::Persistence => axes.persistence = value,
            Self::Packing => axes.packing = value,
            Self::Porosity => axes.porosity = value,
            Self::DistinguishabilityLoss => axes.distinguishability_loss = value,
        }
    }
}

pub(super) fn source_separation_result(inquiry: &OwnerInquiryV1) -> Result<Value, String> {
    let mut strands = Vec::with_capacity(inquiry.strands.len());
    for strand in &inquiry.strands {
        let baseline = derive_axes(&strand.projection_48d);
        let baseline_value = axes_json(&baseline);
        let mut sweeps = Vec::with_capacity(SourceAxis::ALL.len());
        for axis in SourceAxis::ALL {
            let mut rows = Vec::with_capacity(AXIS_LEVELS.len());
            for level in AXIS_LEVELS {
                let mut copied = baseline.clone();
                axis.set(&mut copied, level);
                let unchanged_axes = unchanged_axis_count(&baseline, &copied, axis);
                if unchanged_axes != 6 {
                    return Err(format!(
                        "source-separation sweep for {} changed {unchanged_axes} copied axes",
                        axis.name()
                    ));
                }
                rows.push(source_row(axis.name(), level, &copied));
            }
            sweeps.push(json!({
                "axis": axis.name(),
                "levels": rows,
                "independent_against_copied_inputs": true,
            }));
        }
        strands.push(json!({
            "strand_id": strand.strand_id,
            "label": strand.label,
            "content_sha256": strand.content_sha256,
            "embedding_sha256": strand.embedding_sha256,
            "baseline": baseline_value,
            "sweeps": sweeps,
        }));
    }
    let texture_dynamics_snapshot_v1 = texture_dynamics_snapshot_v1(inquiry)?;
    Ok(json!({
        "policy": "viscous_persistence_source_separation_matrix_v1",
        "fixed_axes": [
            "pressure",
            "gradient",
            "entropy",
            "persistence",
            "packing",
            "porosity",
            "distinguishability_loss"
        ],
        "fixed_levels": AXIS_LEVELS,
        "fixed_fill": FIXED_FILL,
        "strands": strands,
        "texture_dynamics_snapshot_v1": texture_dynamics_snapshot_v1,
        "candidate_merge_performed": false,
        "live_runtime_mutation": false,
        "authority": "owner_only_offline_evidence_not_regulator_or_control_authority",
    }))
}

fn source_row(axis: &str, level: f32, axes: &SourceAxes) -> Value {
    let viscosity_index = resonance_viscosity_index_with_entropy(
        axes.packing,
        axes.persistence,
        1.0 - axes.distinguishability_loss,
        axes.pressure,
        axes.entropy,
    );
    let persistence = viscosity_persistence_coefficient(
        viscosity_index,
        axes.persistence,
        axes.pressure,
        axes.packing,
    );
    let temporal_drag = temporal_drag_coefficient(persistence, axes.persistence, axes.pressure);
    let pressure = pressure_source_for_axes(axes);
    let stale =
        semantic_stale_context_review_v1(FIXED_FILL, axes.entropy, axes.gradient, axes.pressure);
    let age_ms = (axes.persistence.clamp(0.0, 1.0) * 60_000.0).round() as u64;
    let degradation =
        semantic_degradation_curve_review_v1(FIXED_FILL, axes.entropy, axes.gradient, age_ms);
    json!({
        "swept_axis": axis,
        "swept_value": level,
        "axes": axes_json(axes),
        "viscosity_index": viscosity_index,
        "viscosity_persistence_coefficient": persistence,
        "temporal_drag_coefficient": temporal_drag,
        "pressure_score": pressure.pressure_score,
        "derived_porosity_score": pressure.porosity_score,
        "pressure_porosity_gradient": pressure.pressure_porosity_gradient,
        "semantic_viscosity_coefficient": pressure.semantic_viscosity_coefficient_v1.coefficient,
        "silt_granularity_index": pressure.silt_granularity_v1.granularity_index,
        "stale_context_multiplier": stale.context_multiplier,
        "stale_context_window_ms": stale.context_extended_stale_ms,
        "degradation_clarity_factor": degradation.clarity_factor,
        "degradation_edge_softening": degradation.edge_softening,
        "live_control_changed": false,
    })
}

pub(super) fn pressure_source_for_axes(axes: &SourceAxes) -> PressureSourceV1 {
    PressureSourceV1::from_parts(
        PressureSourceComponents {
            lambda_monopoly: axes.packing,
            mode_packing: axes.packing,
            controller_pressure: axes.pressure,
            semantic_trickle: 1.0 - axes.porosity,
            semantic_friction: axes.distinguishability_loss,
            structural_plurality_loss: axes.packing,
            distinguishability_loss: axes.distinguishability_loss,
            temporal_lock_in: axes.persistence,
            sensory_scarcity: 1.0 - axes.porosity,
        },
        PressureSourceContext {
            mean_orientation_delta: Some(axes.gradient),
            ..PressureSourceContext::default()
        },
    )
}

pub(super) fn derive_axes(values: &[f32]) -> SourceAxes {
    let count = values.len().max(1) as f32;
    let abs_sum = values.iter().map(|value| value.abs()).sum::<f32>();
    let rms = (values.iter().map(|value| value * value).sum::<f32>() / count).sqrt();
    let max_abs = values
        .iter()
        .map(|value| value.abs())
        .fold(0.0_f32, f32::max);
    let gradient = if values.len() < 2 {
        0.0
    } else {
        values
            .windows(2)
            .map(|window| (window[1] - window[0]).abs())
            .sum::<f32>()
            / values.len().saturating_sub(1) as f32
    };
    let entropy = normalized_magnitude_entropy(values);
    let active = values.iter().filter(|value| value.abs() > 0.05).count() as f32 / count;
    let packing = if abs_sum <= f32::EPSILON {
        0.0
    } else {
        (max_abs / (abs_sum / count).max(f32::EPSILON) / count.sqrt()).clamp(0.0, 1.0)
    };
    let mean = values.iter().copied().sum::<f32>() / count;
    let variance = values
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta
        })
        .sum::<f32>()
        / count;
    SourceAxes {
        pressure: rms.clamp(0.0, 1.0),
        gradient: gradient.clamp(0.0, 1.0),
        entropy,
        persistence: (0.6 * rms + 0.4 * (1.0 - gradient.clamp(0.0, 1.0))).clamp(0.0, 1.0),
        packing,
        porosity: (1.0 - active).clamp(0.0, 1.0),
        distinguishability_loss: (1.0 - variance.sqrt().clamp(0.0, 1.0)).clamp(0.0, 1.0),
    }
}

fn axes_json(axes: &SourceAxes) -> Value {
    json!({
        "pressure": axes.pressure,
        "gradient": axes.gradient,
        "entropy": axes.entropy,
        "persistence": axes.persistence,
        "packing": axes.packing,
        "porosity": axes.porosity,
        "distinguishability_loss": axes.distinguishability_loss,
    })
}

fn unchanged_axis_count(before: &SourceAxes, after: &SourceAxes, changed: SourceAxis) -> usize {
    let pairs = [
        (SourceAxis::Pressure, before.pressure, after.pressure),
        (SourceAxis::Gradient, before.gradient, after.gradient),
        (SourceAxis::Entropy, before.entropy, after.entropy),
        (
            SourceAxis::Persistence,
            before.persistence,
            after.persistence,
        ),
        (SourceAxis::Packing, before.packing, after.packing),
        (SourceAxis::Porosity, before.porosity, after.porosity),
        (
            SourceAxis::DistinguishabilityLoss,
            before.distinguishability_loss,
            after.distinguishability_loss,
        ),
    ];
    pairs
        .iter()
        .filter(|(axis, left, right)| {
            axis.name() != changed.name() && left.to_bits() == right.to_bits()
        })
        .count()
}

fn normalized_magnitude_entropy(values: &[f32]) -> f32 {
    let total = values.iter().map(|value| value.abs()).sum::<f32>();
    if total <= f32::EPSILON || values.len() < 2 {
        return 0.0;
    }
    let entropy = values
        .iter()
        .map(|value| value.abs() / total)
        .filter(|probability| *probability > f32::EPSILON)
        .map(|probability| -probability * probability.ln())
        .sum::<f32>();
    (entropy / (values.len() as f32).ln()).clamp(0.0, 1.0)
}
