use serde::Serialize;
use serde_json::json;

use super::source_separation::{derive_axes, pressure_source_for_axes};
use crate::{
    owner_inquiry_wire::{canonical_sha256, OwnerInquiryV1, SemanticStrandV1},
    regulator::{
        resonance_viscosity_index_with_entropy, temporal_drag_coefficient,
        viscosity_persistence_coefficient,
    },
};

const TEXTURE_PRODUCER_V1: &str = "minime.owner_inquiry.texture_dynamics_v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(super) struct TextureMetricAvailabilityV1 {
    state: &'static str,
    exact_source_present: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    missing_reason: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    required_source: Option<&'static str>,
}

impl TextureMetricAvailabilityV1 {
    const fn present() -> Self {
        Self {
            state: "present",
            exact_source_present: true,
            missing_reason: None,
            required_source: None,
        }
    }

    const fn missing(reason: &'static str, required_source: &'static str) -> Self {
        Self {
            state: "missing",
            exact_source_present: false,
            missing_reason: Some(reason),
            required_source: Some(required_source),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct TextureMetricEvidenceV1 {
    metric: &'static str,
    value: Option<f32>,
    basis: &'static str,
    measurement_domain: &'static str,
    source_evidence_ids: Vec<String>,
    source_evidence_sha256s: Vec<String>,
    sampled_at_unix_ms: u64,
    producer: &'static str,
    availability: TextureMetricAvailabilityV1,
    semantic_projection_not_raw_spectral_telemetry: bool,
    raw_spectral_telemetry_used: bool,
}

impl TextureMetricEvidenceV1 {
    fn present(
        metric: &'static str,
        value: f32,
        basis: &'static str,
        sources: &[TextureEvidenceSourceV1],
    ) -> Self {
        Self {
            metric,
            value: Some(value),
            basis,
            measurement_domain: "semantic_projection_48d",
            source_evidence_ids: sources
                .iter()
                .map(|source| source.source_evidence_id.clone())
                .collect(),
            source_evidence_sha256s: sources
                .iter()
                .map(|source| source.source_evidence_sha256.clone())
                .collect(),
            sampled_at_unix_ms: sources
                .iter()
                .map(|source| source.sampled_at_unix_ms)
                .max()
                .unwrap_or(0),
            producer: TEXTURE_PRODUCER_V1,
            availability: TextureMetricAvailabilityV1::present(),
            semantic_projection_not_raw_spectral_telemetry: true,
            raw_spectral_telemetry_used: false,
        }
    }

    fn missing(
        metric: &'static str,
        basis: &'static str,
        reason: &'static str,
        required_source: &'static str,
        sources: &[TextureEvidenceSourceV1],
    ) -> Self {
        Self {
            metric,
            value: None,
            basis,
            measurement_domain: required_source,
            source_evidence_ids: sources
                .iter()
                .map(|source| source.source_evidence_id.clone())
                .collect(),
            source_evidence_sha256s: sources
                .iter()
                .map(|source| source.source_evidence_sha256.clone())
                .collect(),
            sampled_at_unix_ms: sources
                .iter()
                .map(|source| source.sampled_at_unix_ms)
                .max()
                .unwrap_or(0),
            producer: TEXTURE_PRODUCER_V1,
            availability: TextureMetricAvailabilityV1::missing(reason, required_source),
            semantic_projection_not_raw_spectral_telemetry: true,
            raw_spectral_telemetry_used: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(super) struct TextureEvidenceSourceV1 {
    source_evidence_id: String,
    strand_id: String,
    source_response_interval_sha256: String,
    embedding_sha256: String,
    source_attestation_id: String,
    source_attestation_sha256: String,
    deployment_identity: String,
    sampled_at_unix_ms: u64,
    producer: &'static str,
    provenance: &'static str,
    source_evidence_sha256: String,
}

impl TextureEvidenceSourceV1 {
    fn from_strand(strand: &SemanticStrandV1) -> Self {
        let core = json!({
            "strand_id": strand.strand_id,
            "source_response_interval_sha256": strand.content_sha256,
            "embedding_sha256": strand.embedding_sha256,
            "source_attestation_id": strand.source_attestation_id,
            "source_attestation_sha256": strand.source_attestation_sha256,
            "deployment_identity": strand.deployment_identity,
            "sampled_at_unix_ms": strand.captured_at_unix_ms,
            "producer": TEXTURE_PRODUCER_V1,
            "provenance": "exact_utf8_response_interval_with_semantic_projection_48d",
        });
        let source_evidence_sha256 = canonical_sha256(&core);
        Self {
            source_evidence_id: format!("texture-source-{}", &source_evidence_sha256[..24]),
            strand_id: strand.strand_id.clone(),
            source_response_interval_sha256: strand.content_sha256.clone(),
            embedding_sha256: strand.embedding_sha256.clone(),
            source_attestation_id: strand.source_attestation_id.clone(),
            source_attestation_sha256: strand.source_attestation_sha256.clone(),
            deployment_identity: strand.deployment_identity.clone(),
            sampled_at_unix_ms: strand.captured_at_unix_ms,
            producer: TEXTURE_PRODUCER_V1,
            provenance: "exact_utf8_response_interval_with_semantic_projection_48d",
            source_evidence_sha256,
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct TextureValuesV1 {
    projected_density_gradient: f32,
    projected_packing: f32,
    distinguishability: f32,
    pressure_proxy: f32,
    semantic_viscosity: f32,
    temporal_drag: f32,
    persistence: f32,
    structural_stagnation_proxy: f32,
}

impl TextureValuesV1 {
    fn from_strand(strand: &SemanticStrandV1) -> Self {
        let axes = derive_axes(&strand.projection_48d);
        let pressure = pressure_source_for_axes(&axes);
        let distinguishability = (1.0 - axes.distinguishability_loss).clamp(0.0, 1.0);
        let viscosity_index = resonance_viscosity_index_with_entropy(
            axes.packing,
            axes.persistence,
            distinguishability,
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
        let structural_stagnation_proxy =
            (0.40 * axes.packing + 0.35 * persistence + 0.25 * axes.distinguishability_loss)
                .clamp(0.0, 1.0);
        Self {
            projected_density_gradient: axes.gradient,
            projected_packing: axes.packing,
            distinguishability,
            pressure_proxy: pressure.pressure_score,
            semantic_viscosity: pressure.semantic_viscosity_coefficient_v1.coefficient,
            temporal_drag,
            persistence,
            structural_stagnation_proxy,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct TextureMetricSetV1 {
    projected_density_gradient: TextureMetricEvidenceV1,
    projected_packing: TextureMetricEvidenceV1,
    distinguishability: TextureMetricEvidenceV1,
    pressure_proxy: TextureMetricEvidenceV1,
    semantic_viscosity: TextureMetricEvidenceV1,
    temporal_drag: TextureMetricEvidenceV1,
    persistence: TextureMetricEvidenceV1,
    structural_stagnation_proxy: TextureMetricEvidenceV1,
    raw_reservoir_mode_packing: TextureMetricEvidenceV1,
    shadow_dispersal: TextureMetricEvidenceV1,
}

impl TextureMetricSetV1 {
    fn strand(values: TextureValuesV1, source: &TextureEvidenceSourceV1) -> Self {
        Self::from_values(
            values,
            std::slice::from_ref(source),
            "semantic_projection_48d",
        )
    }

    fn absolute_delta(
        left: TextureValuesV1,
        right: TextureValuesV1,
        sources: &[TextureEvidenceSourceV1],
    ) -> Self {
        let values = TextureValuesV1 {
            projected_density_gradient: (left.projected_density_gradient
                - right.projected_density_gradient)
                .abs(),
            projected_packing: (left.projected_packing - right.projected_packing).abs(),
            distinguishability: (left.distinguishability - right.distinguishability).abs(),
            pressure_proxy: (left.pressure_proxy - right.pressure_proxy).abs(),
            semantic_viscosity: (left.semantic_viscosity - right.semantic_viscosity).abs(),
            temporal_drag: (left.temporal_drag - right.temporal_drag).abs(),
            persistence: (left.persistence - right.persistence).abs(),
            structural_stagnation_proxy: (left.structural_stagnation_proxy
                - right.structural_stagnation_proxy)
                .abs(),
        };
        Self::from_values(
            values,
            sources,
            "absolute_delta_between_semantic_projection_metrics",
        )
    }

    fn from_values(
        values: TextureValuesV1,
        sources: &[TextureEvidenceSourceV1],
        basis_prefix: &'static str,
    ) -> Self {
        Self {
            projected_density_gradient: TextureMetricEvidenceV1::present(
                "projected_density_gradient",
                values.projected_density_gradient,
                basis_prefix,
                sources,
            ),
            projected_packing: TextureMetricEvidenceV1::present(
                "projected_packing",
                values.projected_packing,
                basis_prefix,
                sources,
            ),
            distinguishability: TextureMetricEvidenceV1::present(
                "distinguishability",
                values.distinguishability,
                basis_prefix,
                sources,
            ),
            pressure_proxy: TextureMetricEvidenceV1::present(
                "pressure_proxy",
                values.pressure_proxy,
                basis_prefix,
                sources,
            ),
            semantic_viscosity: TextureMetricEvidenceV1::present(
                "semantic_viscosity",
                values.semantic_viscosity,
                basis_prefix,
                sources,
            ),
            temporal_drag: TextureMetricEvidenceV1::present(
                "temporal_drag",
                values.temporal_drag,
                basis_prefix,
                sources,
            ),
            persistence: TextureMetricEvidenceV1::present(
                "persistence",
                values.persistence,
                basis_prefix,
                sources,
            ),
            structural_stagnation_proxy: TextureMetricEvidenceV1::present(
                "structural_stagnation_proxy",
                values.structural_stagnation_proxy,
                "0.40_projected_packing_plus_0.35_persistence_plus_0.25_distinguishability_loss",
                sources,
            ),
            raw_reservoir_mode_packing: TextureMetricEvidenceV1::missing(
                "raw_reservoir_mode_packing",
                "not_computed_from_semantic_projection",
                "exact_raw_reservoir_mode_evidence_not_present_in_owner_inquiry",
                "raw_reservoir_spectral_telemetry",
                sources,
            ),
            shadow_dispersal: TextureMetricEvidenceV1::missing(
                "shadow_dispersal",
                "not_computed_from_semantic_projection",
                "exact_shadow_history_evidence_not_present_in_owner_inquiry",
                "exact_shadow_history_artifact",
                sources,
            ),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct TextureStrandRowV1 {
    strand_id: String,
    source: TextureEvidenceSourceV1,
    metrics: TextureMetricSetV1,
    independently_sourced: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(super) struct TextureAnalysisPairRefV1 {
    analysis: &'static str,
    left_strand_id: String,
    right_strand_id: String,
    exact_pair_key_sha256: String,
    result_selector: String,
    exact_id_match_required: bool,
    timestamp_proximity_match_allowed: bool,
}

impl TextureAnalysisPairRefV1 {
    fn new(analysis: &'static str, left: &str, right: &str) -> Self {
        let exact_pair_key_sha256 = canonical_sha256(&json!({
            "analysis": analysis,
            "left_strand_id": left,
            "right_strand_id": right,
        }));
        Self {
            analysis,
            left_strand_id: left.to_string(),
            right_strand_id: right.to_string(),
            exact_pair_key_sha256,
            result_selector: format!(
                "analysis_receipts[analysis={analysis}].result.pairs[left_strand_id={left};right_strand_id={right}]"
            ),
            exact_id_match_required: true,
            timestamp_proximity_match_allowed: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct TexturePairRowV1 {
    pair_id: String,
    left_strand_id: String,
    right_strand_id: String,
    source_evidence_ids: Vec<String>,
    absolute_metric_deltas: TextureMetricSetV1,
    codec_fidelity_evidence_ref: TextureAnalysisPairRefV1,
    sensory_interference_evidence_ref: TextureAnalysisPairRefV1,
    pair_averaged: bool,
    pair_ranked: bool,
    preferred_strand_selected: bool,
    candidate_merge_performed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(super) struct TextureFeltStatusBoundaryV1 {
    state: &'static str,
    author_domain: &'static str,
    machine_may_set_felt_status: bool,
    silence_means_uptake: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(super) struct TextureDynamicsSnapshotV1 {
    schema: &'static str,
    schema_version: u8,
    inquiry_id: String,
    producer: &'static str,
    source_attestation_id: String,
    source_attestation_sha256: String,
    semantic_projection_dimensions: usize,
    semantic_projection_not_raw_spectral_telemetry: bool,
    strand_count: usize,
    unordered_pair_count: usize,
    strands: Vec<TextureStrandRowV1>,
    pairs: Vec<TexturePairRowV1>,
    structural_stagnation_proxy_disclosure: &'static str,
    raw_reservoir_mode_packing_state: &'static str,
    shadow_dispersal_state: &'static str,
    felt_status: TextureFeltStatusBoundaryV1,
    candidate_merge_performed: bool,
    preferred_strand_selected: bool,
    live_runtime_mutation: bool,
    live_control_authority: bool,
}

pub(super) fn texture_dynamics_snapshot_v1(
    inquiry: &OwnerInquiryV1,
) -> Result<TextureDynamicsSnapshotV1, String> {
    let derived = inquiry
        .strands
        .iter()
        .map(|strand| {
            let source = TextureEvidenceSourceV1::from_strand(strand);
            let values = TextureValuesV1::from_strand(strand);
            if ![
                values.projected_density_gradient,
                values.projected_packing,
                values.distinguishability,
                values.pressure_proxy,
                values.semantic_viscosity,
                values.temporal_drag,
                values.persistence,
                values.structural_stagnation_proxy,
            ]
            .into_iter()
            .all(f32::is_finite)
            {
                return Err(format!(
                    "texture dynamics produced non-finite metrics for {}",
                    strand.strand_id
                ));
            }
            Ok((source, values))
        })
        .collect::<Result<Vec<_>, String>>()?;

    let strands = derived
        .iter()
        .map(|(source, values)| TextureStrandRowV1 {
            strand_id: source.strand_id.clone(),
            source: source.clone(),
            metrics: TextureMetricSetV1::strand(*values, source),
            independently_sourced: true,
        })
        .collect::<Vec<_>>();
    let mut pairs = Vec::new();
    for left_index in 0..derived.len() {
        for right_index in left_index.saturating_add(1)..derived.len() {
            let (left_source, left_values) = &derived[left_index];
            let (right_source, right_values) = &derived[right_index];
            let sources = vec![left_source.clone(), right_source.clone()];
            let pair_key = json!({
                "left_strand_id": left_source.strand_id,
                "right_strand_id": right_source.strand_id,
            });
            pairs.push(TexturePairRowV1 {
                pair_id: format!("texture-pair-{}", &canonical_sha256(&pair_key)[..24]),
                left_strand_id: left_source.strand_id.clone(),
                right_strand_id: right_source.strand_id.clone(),
                source_evidence_ids: sources
                    .iter()
                    .map(|source| source.source_evidence_id.clone())
                    .collect(),
                absolute_metric_deltas: TextureMetricSetV1::absolute_delta(
                    *left_values,
                    *right_values,
                    &sources,
                ),
                codec_fidelity_evidence_ref: TextureAnalysisPairRefV1::new(
                    "codec_fidelity",
                    &left_source.strand_id,
                    &right_source.strand_id,
                ),
                sensory_interference_evidence_ref: TextureAnalysisPairRefV1::new(
                    "sensory_interference_all_pairs",
                    &left_source.strand_id,
                    &right_source.strand_id,
                ),
                pair_averaged: false,
                pair_ranked: false,
                preferred_strand_selected: false,
                candidate_merge_performed: false,
            });
        }
    }
    Ok(TextureDynamicsSnapshotV1 {
        schema: "texture_dynamics_snapshot_v1",
        schema_version: 1,
        inquiry_id: inquiry.inquiry_id.clone(),
        producer: TEXTURE_PRODUCER_V1,
        source_attestation_id: inquiry.source_attestation_id.clone(),
        source_attestation_sha256: inquiry.source_attestation_sha256.clone(),
        semantic_projection_dimensions: 48,
        semantic_projection_not_raw_spectral_telemetry: true,
        strand_count: strands.len(),
        unordered_pair_count: pairs.len(),
        strands,
        pairs,
        structural_stagnation_proxy_disclosure:
            "0.40*projected_packing + 0.35*persistence + 0.25*distinguishability_loss; semantic-projection structural proxy only",
        raw_reservoir_mode_packing_state: "missing_no_exact_raw_reservoir_source",
        shadow_dispersal_state: "missing_no_exact_shadow_history_source",
        felt_status: TextureFeltStatusBoundaryV1 {
            state: "unreported",
            author_domain: "owner_authored_only",
            machine_may_set_felt_status: false,
            silence_means_uptake: false,
        },
        candidate_merge_performed: false,
        preferred_strand_selected: false,
        live_runtime_mutation: false,
        live_control_authority: false,
    })
}
