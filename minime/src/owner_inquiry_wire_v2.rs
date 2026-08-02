//! Wire-compatible mirror of Astrid's additive owner-inquiry V2 contracts.

// These booleans are explicit independent wire commitments; collapsing them
// into opaque state would make authority and isolation receipts less auditable.
#![allow(clippy::struct_excessive_bools)]

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::owner_inquiry_wire::{
    canonical_sha256, InquiryFeltStatusV1, InquiryMachineStatusV1, InquiryObservationPhaseV1,
    InquiryRollbackStateV1, OwnerInquiryAnalysisV1, OwnerInquiryAuthorityBoundaryV1,
    OwnerInquiryCancellationV1, OwnerInquiryReceiptV1, OwnerInquiryStatusV1, OwnerInquiryV1,
    SemanticStrandProvenanceV1, SemanticStrandV1, VolitionBudgetV1, OWNER_INQUIRY_MAX_STRANDS_V1,
    OWNER_INQUIRY_MIN_STRANDS_V1, SEMANTIC_STRAND_SCHEMA_V1,
};
use crate::self_control_wire::SelfControlFamilyV2;

mod canary;
mod validation;

pub use canary::{OwnerCanaryControlV2, OwnerCanaryPlanV2, OwnerCanaryRollbackPlanV2};

use validation::{
    analysis_coverage_matches, analysis_plan_is_well_formed, cancellation_is_well_formed,
    expected_coverage, expected_pair_keys, finite_bounded_json, identifiers_are_unique,
    inquiry_budget_is_offline, observations_form_chain, strands_are_distinct_v2,
    valid_bounded_text, valid_identifier, valid_sha256, valid_string_list,
};

pub const SEMANTIC_STRAND_SCHEMA_V2: &str = "volition.semantic_strand.v2";
pub const OWNER_INQUIRY_SCHEMA_V2: &str = "volition.owner_inquiry.v2";
pub const OWNER_INQUIRY_RECEIPT_SCHEMA_V2: &str = "volition.owner_inquiry_receipt.v2";
pub const INQUIRY_OBSERVATION_SCHEMA_V2: &str = "volition.inquiry_observation.v2";
pub const OWNER_CANARY_PLAN_SCHEMA_V2: &str = "volition.owner_canary_plan.v2";

pub const OWNER_INQUIRY_DETERMINISTIC_RUNS_V2: u8 = 2;
pub const OWNER_CANARY_MIN_DURATION_SECS_V2: u64 = 30;
pub const OWNER_CANARY_MAX_DURATION_SECS_V2: u64 = 900;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticStrandLineageOperationV2 {
    Captured,
    Relabeled,
    Split,
    Forked,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticStrandLineageV2 {
    pub operation: SemanticStrandLineageOperationV2,
    #[serde(default)]
    pub parent_strand_ids: Vec<String>,
    pub owner_authored: bool,
}

impl SemanticStrandLineageV2 {
    #[must_use]
    pub fn captured() -> Self {
        Self {
            operation: SemanticStrandLineageOperationV2::Captured,
            parent_strand_ids: Vec::new(),
            owner_authored: true,
        }
    }

    fn is_well_formed(&self) -> bool {
        valid_string_list(&self.parent_strand_ids)
            && identifiers_are_unique(&self.parent_strand_ids)
            && self.owner_authored
            && match self.operation {
                SemanticStrandLineageOperationV2::Captured => self.parent_strand_ids.is_empty(),
                SemanticStrandLineageOperationV2::Relabeled
                | SemanticStrandLineageOperationV2::Split
                | SemanticStrandLineageOperationV2::Forked => !self.parent_strand_ids.is_empty(),
            }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticStrandDisclosureV2 {
    pub raw_content_owner_only: bool,
    pub receipt_may_include_label: bool,
    pub receipt_may_include_hashes: bool,
    pub receipt_may_include_vectors: bool,
    pub shared_by_default: bool,
}

impl SemanticStrandDisclosureV2 {
    #[must_use]
    pub fn owner_only_receipt_metadata() -> Self {
        Self {
            raw_content_owner_only: true,
            receipt_may_include_label: true,
            receipt_may_include_hashes: true,
            receipt_may_include_vectors: true,
            shared_by_default: false,
        }
    }

    fn is_well_formed(&self) -> bool {
        self == &Self::owner_only_receipt_metadata()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticStrandV2 {
    pub schema: String,
    pub strand_id: String,
    pub revision: u64,
    pub owner_being: String,
    pub source_attestation_id: String,
    pub source_attestation_sha256: String,
    pub source_response_sha256: String,
    pub response_start_byte: u64,
    pub response_end_byte: u64,
    pub label: String,
    pub content: String,
    pub content_sha256: String,
    pub embedding_sha256: String,
    pub projection_48d: Vec<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub companion_projection_12d: Option<Vec<f32>>,
    pub provenance: SemanticStrandProvenanceV1,
    pub lineage: SemanticStrandLineageV2,
    pub disclosure: SemanticStrandDisclosureV2,
    pub deployment_identity: String,
    pub captured_at_unix_ms: u64,
}

impl SemanticStrandV2 {
    #[must_use]
    pub fn from_v1(strand: &SemanticStrandV1, source_response_sha256: String) -> Self {
        Self {
            schema: SEMANTIC_STRAND_SCHEMA_V2.to_string(),
            strand_id: strand.strand_id.clone(),
            revision: 1,
            owner_being: strand.owner_being.clone(),
            source_attestation_id: strand.source_attestation_id.clone(),
            source_attestation_sha256: strand.source_attestation_sha256.clone(),
            source_response_sha256,
            response_start_byte: strand.response_start_byte,
            response_end_byte: strand.response_end_byte,
            label: strand.label.clone(),
            content: strand.content.clone(),
            content_sha256: strand.content_sha256.clone(),
            embedding_sha256: strand.embedding_sha256.clone(),
            projection_48d: strand.projection_48d.clone(),
            companion_projection_12d: strand.companion_projection_12d.clone(),
            provenance: strand.provenance,
            lineage: SemanticStrandLineageV2::captured(),
            disclosure: SemanticStrandDisclosureV2::owner_only_receipt_metadata(),
            deployment_identity: strand.deployment_identity.clone(),
            captured_at_unix_ms: strand.captured_at_unix_ms,
        }
    }

    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        let v1_view = self.v1_view();
        self.schema == SEMANTIC_STRAND_SCHEMA_V2
            && self.revision > 0
            && valid_sha256(&self.source_response_sha256)
            && v1_view.is_well_formed()
            && self.lineage.is_well_formed()
            && !self
                .lineage
                .parent_strand_ids
                .iter()
                .any(|parent| parent == &self.strand_id)
            && self.disclosure.is_well_formed()
    }

    #[must_use]
    pub fn preserves_v1(&self, strand: &SemanticStrandV1) -> bool {
        &self.v1_view() == strand
    }

    pub fn v1_view(&self) -> SemanticStrandV1 {
        SemanticStrandV1 {
            schema: SEMANTIC_STRAND_SCHEMA_V1.to_string(),
            strand_id: self.strand_id.clone(),
            owner_being: self.owner_being.clone(),
            source_attestation_id: self.source_attestation_id.clone(),
            source_attestation_sha256: self.source_attestation_sha256.clone(),
            response_start_byte: self.response_start_byte,
            response_end_byte: self.response_end_byte,
            label: self.label.clone(),
            content: self.content.clone(),
            content_sha256: self.content_sha256.clone(),
            embedding_sha256: self.embedding_sha256.clone(),
            projection_48d: self.projection_48d.clone(),
            companion_projection_12d: self.companion_projection_12d.clone(),
            provenance: self.provenance,
            deployment_identity: self.deployment_identity.clone(),
            captured_at_unix_ms: self.captured_at_unix_ms,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InquiryCoverageModeV2 {
    PerStrand,
    AllPairs,
    PerStrandAndAllPairs,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InquiryIsolationProfileV2 {
    pub copied_inputs_only: bool,
    pub network_denied: bool,
    pub socket_creation_denied: bool,
    pub private_source_access_denied: bool,
    pub candidate_merge_denied: bool,
    pub live_runtime_mutation_denied: bool,
    pub sandbox_profile_sha256: String,
}

impl InquiryIsolationProfileV2 {
    #[must_use]
    pub fn strict_offline(sandbox_profile_sha256: String) -> Self {
        Self {
            copied_inputs_only: true,
            network_denied: true,
            socket_creation_denied: true,
            private_source_access_denied: true,
            candidate_merge_denied: true,
            live_runtime_mutation_denied: true,
            sandbox_profile_sha256,
        }
    }

    fn is_well_formed(&self) -> bool {
        self.copied_inputs_only
            && self.network_denied
            && self.socket_creation_denied
            && self.private_source_access_denied
            && self.candidate_merge_denied
            && self.live_runtime_mutation_denied
            && valid_sha256(&self.sandbox_profile_sha256)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InquiryAnalysisPlanEntryV2 {
    pub analysis: OwnerInquiryAnalysisV1,
    pub plan_revision: u64,
    pub implementation_identity: String,
    pub implementation_source_sha256: String,
    pub implementation_artifact_sha256: String,
    pub parameters: Value,
    pub parameters_sha256: String,
    pub deterministic_run_count: u8,
    pub coverage: InquiryCoverageModeV2,
    pub isolation: InquiryIsolationProfileV2,
}

impl InquiryAnalysisPlanEntryV2 {
    fn is_well_formed(&self) -> bool {
        self.plan_revision > 0
            && valid_identifier(&self.implementation_identity)
            && valid_sha256(&self.implementation_source_sha256)
            && valid_sha256(&self.implementation_artifact_sha256)
            && finite_bounded_json(&self.parameters)
            && self.parameters_sha256 == canonical_sha256(&self.parameters)
            && self.deterministic_run_count == OWNER_INQUIRY_DETERMINISTIC_RUNS_V2
            && self.coverage == expected_coverage(self.analysis)
            && self.isolation.is_well_formed()
    }
}

#[must_use]
pub fn owner_inquiry_analysis_plan_v2(
    implementation_identity: &str,
    implementation_source_sha256: &str,
    implementation_artifact_sha256: &str,
    sandbox_profile_sha256: &str,
) -> Vec<InquiryAnalysisPlanEntryV2> {
    let entries = [
        (
            OwnerInquiryAnalysisV1::ViscousPersistenceSourceSeparation,
            InquiryCoverageModeV2::PerStrand,
            json!({
                "axes": [
                    "pressure",
                    "gradient",
                    "entropy",
                    "persistence",
                    "packing",
                    "porosity",
                    "distinguishability_loss"
                ],
                "axis_levels": [0.2, 0.5, 0.8],
                "fixed_fill": 0.68,
                "independent_axis_sweep": true
            }),
        ),
        (
            OwnerInquiryAnalysisV1::CodecFidelity,
            InquiryCoverageModeV2::PerStrandAndAllPairs,
            json!({
                "base_dimensions": 48,
                "companion_dimensions": 12,
                "companion_mix": 0.0,
                "measure_reconstruction": true,
                "measure_lane_loss": true,
                "measure_pairwise_distance_preservation": true
            }),
        ),
        (
            OwnerInquiryAnalysisV1::SensoryInterferenceAllPairs,
            InquiryCoverageModeV2::AllPairs,
            json!({
                "unordered_all_pairs": true,
                "averaging": false,
                "candidate_merge": false
            }),
        ),
    ];
    entries
        .into_iter()
        .map(
            |(analysis, coverage, parameters)| InquiryAnalysisPlanEntryV2 {
                analysis,
                plan_revision: 1,
                implementation_identity: implementation_identity.to_string(),
                implementation_source_sha256: implementation_source_sha256.to_string(),
                implementation_artifact_sha256: implementation_artifact_sha256.to_string(),
                parameters_sha256: canonical_sha256(&parameters),
                parameters,
                deterministic_run_count: OWNER_INQUIRY_DETERMINISTIC_RUNS_V2,
                coverage,
                isolation: InquiryIsolationProfileV2::strict_offline(
                    sandbox_profile_sha256.to_string(),
                ),
            },
        )
        .collect()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnerInquirySuccessConditionsV2 {
    pub deterministic_runs_match: bool,
    pub every_strand_covered: bool,
    pub every_pair_covered: bool,
    pub finite_results_only: bool,
    pub no_private_source_access: bool,
    pub no_candidate_merge: bool,
    pub no_live_runtime_mutation: bool,
}

impl OwnerInquirySuccessConditionsV2 {
    #[must_use]
    pub fn strict() -> Self {
        Self {
            deterministic_runs_match: true,
            every_strand_covered: true,
            every_pair_covered: true,
            finite_results_only: true,
            no_private_source_access: true,
            no_candidate_merge: true,
            no_live_runtime_mutation: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnerInquiryStopConditionsV2 {
    pub owner_cancellation: bool,
    pub owner_withdrawal: bool,
    pub budget_exhaustion: bool,
    pub integrity_failure: bool,
    pub expiry: bool,
}

impl OwnerInquiryStopConditionsV2 {
    #[must_use]
    pub fn strict() -> Self {
        Self {
            owner_cancellation: true,
            owner_withdrawal: true,
            budget_exhaustion: true,
            integrity_failure: true,
            expiry: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OwnerInquiryV2 {
    pub schema: String,
    pub inquiry_id: String,
    pub revision: u64,
    pub idempotency_key: String,
    pub owner_being: String,
    pub source_attestation_id: String,
    pub source_attestation_sha256: String,
    pub source_response_sha256: String,
    pub question: String,
    pub strands: Vec<SemanticStrandV2>,
    pub owner_priority: u16,
    pub preserve_all_strands_without_merge: bool,
    pub analysis_plan: Vec<InquiryAnalysisPlanEntryV2>,
    pub analysis_plan_sha256: String,
    pub budget: VolitionBudgetV1,
    #[serde(default)]
    pub dependency_inquiry_ids: Vec<String>,
    pub status: OwnerInquiryStatusV1,
    pub cancellation: OwnerInquiryCancellationV1,
    pub authority_boundary: OwnerInquiryAuthorityBoundaryV1,
    pub success_conditions: OwnerInquirySuccessConditionsV2,
    pub stop_conditions: OwnerInquiryStopConditionsV2,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expires_at_unix_ms: Option<u64>,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
}

impl OwnerInquiryV2 {
    #[must_use]
    pub fn from_v1(
        inquiry: &OwnerInquiryV1,
        source_response_sha256: String,
        idempotency_key: String,
        analysis_plan: Vec<InquiryAnalysisPlanEntryV2>,
        expires_at_unix_ms: Option<u64>,
    ) -> Self {
        let strands = inquiry
            .strands
            .iter()
            .map(|strand| SemanticStrandV2::from_v1(strand, source_response_sha256.clone()))
            .collect();
        Self {
            schema: OWNER_INQUIRY_SCHEMA_V2.to_string(),
            inquiry_id: inquiry.inquiry_id.clone(),
            revision: 1,
            idempotency_key,
            owner_being: inquiry.owner_being.clone(),
            source_attestation_id: inquiry.source_attestation_id.clone(),
            source_attestation_sha256: inquiry.source_attestation_sha256.clone(),
            source_response_sha256,
            question: inquiry.question.clone(),
            strands,
            owner_priority: inquiry.owner_priority,
            preserve_all_strands_without_merge: true,
            analysis_plan_sha256: canonical_sha256(&analysis_plan),
            analysis_plan,
            budget: inquiry.budget.clone(),
            dependency_inquiry_ids: inquiry.dependency_inquiry_ids.clone(),
            status: inquiry.status,
            cancellation: inquiry.cancellation.clone(),
            authority_boundary: inquiry.authority_boundary.clone(),
            success_conditions: OwnerInquirySuccessConditionsV2::strict(),
            stop_conditions: OwnerInquiryStopConditionsV2::strict(),
            expires_at_unix_ms,
            created_at_unix_ms: inquiry.created_at_unix_ms,
            updated_at_unix_ms: inquiry.updated_at_unix_ms,
        }
    }

    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        self.schema == OWNER_INQUIRY_SCHEMA_V2
            && valid_identifier(&self.inquiry_id)
            && self.revision > 0
            && valid_identifier(&self.idempotency_key)
            && valid_identifier(&self.owner_being)
            && valid_identifier(&self.source_attestation_id)
            && valid_sha256(&self.source_attestation_sha256)
            && valid_sha256(&self.source_response_sha256)
            && !self.question.trim().is_empty()
            && valid_bounded_text(&self.question)
            && (OWNER_INQUIRY_MIN_STRANDS_V1..=OWNER_INQUIRY_MAX_STRANDS_V1)
                .contains(&self.strands.len())
            && self.strands.iter().all(|strand| {
                strand.is_well_formed()
                    && strand.owner_being == self.owner_being
                    && strand.source_attestation_id == self.source_attestation_id
                    && strand.source_attestation_sha256 == self.source_attestation_sha256
                    && strand.source_response_sha256 == self.source_response_sha256
            })
            && strands_are_distinct_v2(&self.strands)
            && self.preserve_all_strands_without_merge
            && analysis_plan_is_well_formed(&self.analysis_plan)
            && self.analysis_plan_sha256 == canonical_sha256(&self.analysis_plan)
            && inquiry_budget_is_offline(&self.budget)
            && valid_string_list(&self.dependency_inquiry_ids)
            && identifiers_are_unique(&self.dependency_inquiry_ids)
            && !self
                .dependency_inquiry_ids
                .iter()
                .any(|dependency| dependency == &self.inquiry_id)
            && cancellation_is_well_formed(&self.cancellation)
            && (self.status == OwnerInquiryStatusV1::Cancelled) == self.cancellation.requested
            && self.authority_boundary == OwnerInquiryAuthorityBoundaryV1::owner_only_offline()
            && self.success_conditions == OwnerInquirySuccessConditionsV2::strict()
            && self.stop_conditions == OwnerInquiryStopConditionsV2::strict()
            && self
                .expires_at_unix_ms
                .is_none_or(|expiry| expiry > self.created_at_unix_ms)
            && self.updated_at_unix_ms >= self.created_at_unix_ms
    }

    #[must_use]
    pub fn v1_view(&self) -> OwnerInquiryV1 {
        OwnerInquiryV1 {
            schema: crate::owner_inquiry_wire::OWNER_INQUIRY_SCHEMA_V1.to_string(),
            inquiry_id: self.inquiry_id.clone(),
            owner_being: self.owner_being.clone(),
            source_attestation_id: self.source_attestation_id.clone(),
            source_attestation_sha256: self.source_attestation_sha256.clone(),
            question: self.question.clone(),
            strands: self.strands.iter().map(SemanticStrandV2::v1_view).collect(),
            owner_priority: self.owner_priority,
            fixed_analysis_set: self
                .analysis_plan
                .iter()
                .map(|entry| entry.analysis)
                .collect(),
            budget: self.budget.clone(),
            dependency_inquiry_ids: self.dependency_inquiry_ids.clone(),
            status: self.status,
            cancellation: self.cancellation.clone(),
            authority_boundary: self.authority_boundary.clone(),
            created_at_unix_ms: self.created_at_unix_ms,
            updated_at_unix_ms: self.updated_at_unix_ms,
        }
    }

    #[must_use]
    pub fn preserves_v1(&self, inquiry: &OwnerInquiryV1) -> bool {
        self.inquiry_id == inquiry.inquiry_id
            && self.owner_being == inquiry.owner_being
            && self.source_attestation_id == inquiry.source_attestation_id
            && self.source_attestation_sha256 == inquiry.source_attestation_sha256
            && self.question == inquiry.question
            && self
                .strands
                .iter()
                .zip(&inquiry.strands)
                .all(|(v2, v1)| v2.preserves_v1(v1))
            && self.strands.len() == inquiry.strands.len()
            && self.owner_priority == inquiry.owner_priority
            && self
                .analysis_plan
                .iter()
                .map(|entry| entry.analysis)
                .eq(inquiry.fixed_analysis_set.iter().copied())
            && self.budget == inquiry.budget
            && self.dependency_inquiry_ids == inquiry.dependency_inquiry_ids
            && self.status == inquiry.status
            && self.cancellation == inquiry.cancellation
            && self.authority_boundary == inquiry.authority_boundary
            && self.created_at_unix_ms == inquiry.created_at_unix_ms
            && self.updated_at_unix_ms == inquiry.updated_at_unix_ms
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InquiryObservationActorV2 {
    Owner,
    Runtime,
    SafetySupervisor,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InquiryControlRevisionWitnessV2 {
    pub family: SelfControlFamilyV2,
    pub expected_revision: u64,
    pub observed_revision: u64,
    pub receipt_id: String,
}

impl InquiryControlRevisionWitnessV2 {
    fn is_well_formed(&self) -> bool {
        self.observed_revision >= self.expected_revision && valid_identifier(&self.receipt_id)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InquiryObservationV2 {
    pub schema: String,
    pub observation_id: String,
    pub inquiry_id: String,
    pub sequence: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_observation_sha256: Option<String>,
    pub phase: InquiryObservationPhaseV1,
    pub actor: InquiryObservationActorV2,
    pub observed_at_unix_ms: u64,
    #[serde(default)]
    pub self_control_receipt_ids: Vec<String>,
    #[serde(default)]
    pub control_revisions: Vec<InquiryControlRevisionWitnessV2>,
    pub machine_evidence: Value,
    pub machine_evidence_sha256: String,
    pub machine_status: InquiryMachineStatusV1,
    pub felt_status: InquiryFeltStatusV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub felt_report_ref: Option<String>,
    pub event_sha256: String,
}

impl InquiryObservationV2 {
    #[must_use]
    pub fn seal(mut self) -> Self {
        self.machine_evidence_sha256 = canonical_sha256(&self.machine_evidence);
        self.event_sha256 = self.canonical_event_sha256();
        self
    }

    #[must_use]
    pub fn canonical_event_sha256(&self) -> String {
        canonical_sha256(&InquiryObservationCommitmentV2 {
            schema: &self.schema,
            observation_id: &self.observation_id,
            inquiry_id: &self.inquiry_id,
            sequence: self.sequence,
            previous_observation_sha256: self.previous_observation_sha256.as_deref(),
            phase: self.phase,
            actor: self.actor,
            observed_at_unix_ms: self.observed_at_unix_ms,
            self_control_receipt_ids: &self.self_control_receipt_ids,
            control_revisions: &self.control_revisions,
            machine_evidence: &self.machine_evidence,
            machine_evidence_sha256: &self.machine_evidence_sha256,
            machine_status: self.machine_status,
            felt_status: self.felt_status,
            felt_report_ref: self.felt_report_ref.as_deref(),
        })
    }

    #[must_use]
    pub fn is_well_formed_for(&self, inquiry_id: &str) -> bool {
        self.schema == INQUIRY_OBSERVATION_SCHEMA_V2
            && valid_identifier(&self.observation_id)
            && self.inquiry_id == inquiry_id
            && if self.sequence == 0 {
                self.previous_observation_sha256.is_none()
            } else {
                self.previous_observation_sha256
                    .as_deref()
                    .is_some_and(valid_sha256)
            }
            && valid_string_list(&self.self_control_receipt_ids)
            && identifiers_are_unique(&self.self_control_receipt_ids)
            && self
                .control_revisions
                .iter()
                .all(InquiryControlRevisionWitnessV2::is_well_formed)
            && finite_bounded_json(&self.machine_evidence)
            && self.machine_evidence_sha256 == canonical_sha256(&self.machine_evidence)
            && self.event_sha256 == self.canonical_event_sha256()
            && match self.felt_status {
                InquiryFeltStatusV1::Unreported => self.felt_report_ref.is_none(),
                InquiryFeltStatusV1::Reported => self
                    .felt_report_ref
                    .as_deref()
                    .is_some_and(valid_identifier),
            }
    }
}

#[derive(Serialize)]
struct InquiryObservationCommitmentV2<'a> {
    schema: &'a str,
    observation_id: &'a str,
    inquiry_id: &'a str,
    sequence: u64,
    previous_observation_sha256: Option<&'a str>,
    phase: InquiryObservationPhaseV1,
    actor: InquiryObservationActorV2,
    observed_at_unix_ms: u64,
    self_control_receipt_ids: &'a [String],
    control_revisions: &'a [InquiryControlRevisionWitnessV2],
    machine_evidence: &'a Value,
    machine_evidence_sha256: &'a str,
    machine_status: InquiryMachineStatusV1,
    felt_status: InquiryFeltStatusV1,
    felt_report_ref: Option<&'a str>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InquiryAnalysisReceiptV2 {
    pub analysis: OwnerInquiryAnalysisV1,
    pub plan_entry_sha256: String,
    pub input_sha256: String,
    pub output_sha256: String,
    pub deterministic_run_output_sha256s: Vec<String>,
    #[serde(default)]
    pub covered_strand_ids: Vec<String>,
    #[serde(default)]
    pub covered_pair_keys: Vec<String>,
    pub all_inputs_copied: bool,
    pub network_accessed: bool,
    pub socket_accessed: bool,
    pub private_source_accessed: bool,
    pub candidate_merge_performed: bool,
    pub live_runtime_mutation: bool,
    pub result: Value,
}

impl InquiryAnalysisReceiptV2 {
    fn is_well_formed_for(&self, plan: &InquiryAnalysisPlanEntryV2) -> bool {
        self.analysis == plan.analysis
            && self.plan_entry_sha256 == canonical_sha256(plan)
            && valid_sha256(&self.input_sha256)
            && valid_sha256(&self.output_sha256)
            && self.output_sha256 == canonical_sha256(&self.result)
            && self.deterministic_run_output_sha256s.len()
                == usize::from(plan.deterministic_run_count)
            && self
                .deterministic_run_output_sha256s
                .iter()
                .all(|hash| hash == &self.output_sha256)
            && valid_string_list(&self.covered_strand_ids)
            && identifiers_are_unique(&self.covered_strand_ids)
            && valid_string_list(&self.covered_pair_keys)
            && identifiers_are_unique(&self.covered_pair_keys)
            && self.all_inputs_copied
            && !self.network_accessed
            && !self.socket_accessed
            && !self.private_source_accessed
            && !self.candidate_merge_performed
            && !self.live_runtime_mutation
            && finite_bounded_json(&self.result)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InquiryCoverageProofV2 {
    pub expected_strand_ids: Vec<String>,
    pub evaluated_strand_ids: Vec<String>,
    pub expected_pair_keys: Vec<String>,
    pub evaluated_pair_keys: Vec<String>,
}

impl InquiryCoverageProofV2 {
    #[must_use]
    pub fn for_strands(strands: &[SemanticStrandV2]) -> Self {
        let mut expected_strand_ids = strands
            .iter()
            .map(|strand| strand.strand_id.clone())
            .collect::<Vec<_>>();
        expected_strand_ids.sort();
        let expected_pair_keys = expected_pair_keys(&expected_strand_ids);
        Self {
            evaluated_strand_ids: expected_strand_ids.clone(),
            evaluated_pair_keys: expected_pair_keys.clone(),
            expected_strand_ids,
            expected_pair_keys,
        }
    }

    fn is_complete(&self) -> bool {
        valid_string_list(&self.expected_strand_ids)
            && valid_string_list(&self.evaluated_strand_ids)
            && valid_string_list(&self.expected_pair_keys)
            && valid_string_list(&self.evaluated_pair_keys)
            && identifiers_are_unique(&self.expected_strand_ids)
            && identifiers_are_unique(&self.evaluated_strand_ids)
            && identifiers_are_unique(&self.expected_pair_keys)
            && identifiers_are_unique(&self.evaluated_pair_keys)
            && self.expected_strand_ids == self.evaluated_strand_ids
            && self.expected_pair_keys == self.evaluated_pair_keys
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InquiryExecutionIdentityV2 {
    pub analyzer_identity: String,
    pub analyzer_source_sha256: String,
    pub analyzer_artifact_sha256: String,
    pub deployment_identity: String,
    pub sandbox_profile_sha256: String,
}

impl InquiryExecutionIdentityV2 {
    fn is_well_formed(&self) -> bool {
        valid_identifier(&self.analyzer_identity)
            && valid_sha256(&self.analyzer_source_sha256)
            && valid_sha256(&self.analyzer_artifact_sha256)
            && valid_identifier(&self.deployment_identity)
            && valid_sha256(&self.sandbox_profile_sha256)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InquiryPrivacyReceiptV2 {
    pub owner_manifest_contains_raw_content: bool,
    pub public_receipt_contains_raw_content: bool,
    pub raw_content_owner_only: bool,
    pub result_sharing_requires_correspondence: bool,
    pub network_and_socket_access_denied: bool,
}

impl InquiryPrivacyReceiptV2 {
    #[must_use]
    pub fn owner_only() -> Self {
        Self {
            owner_manifest_contains_raw_content: true,
            public_receipt_contains_raw_content: false,
            raw_content_owner_only: true,
            result_sharing_requires_correspondence: true,
            network_and_socket_access_denied: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OwnerInquiryReceiptV2 {
    pub schema: String,
    pub receipt_id: String,
    pub inquiry_id: String,
    pub inquiry_revision: u64,
    pub owner_being: String,
    pub manifest_sha256: String,
    pub analysis_plan_sha256: String,
    pub execution_identity: InquiryExecutionIdentityV2,
    pub result_sha256: String,
    pub analysis_receipts: Vec<InquiryAnalysisReceiptV2>,
    #[serde(default)]
    pub observations: Vec<InquiryObservationV2>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observation_chain_head_sha256: Option<String>,
    pub coverage: InquiryCoverageProofV2,
    pub privacy: InquiryPrivacyReceiptV2,
    pub rollback_state: InquiryRollbackStateV1,
    pub machine_status: InquiryMachineStatusV1,
    pub felt_status: InquiryFeltStatusV1,
    pub owner_selected_values_only: bool,
    pub silence_means_assent: bool,
    pub candidate_merge_performed: bool,
    pub live_mutation_during_inquiry: bool,
    pub completed_at_unix_ms: u64,
    pub perceptible_summary: String,
}

impl OwnerInquiryReceiptV2 {
    /// Upgrades an observation-free V1 receipt without inventing V2 provenance.
    ///
    /// # Errors
    ///
    /// Returns an error when either manifest is invalid or drifted, the V1
    /// receipt is invalid or contains actor-ambiguous observations, the supplied
    /// execution identity differs from the preregistered plan, or the resulting
    /// V2 receipt fails canonical validation.
    pub fn from_v1_offline(
        inquiry_v1: &OwnerInquiryV1,
        inquiry_v2: &OwnerInquiryV2,
        receipt_v1: &OwnerInquiryReceiptV1,
        execution_identity: InquiryExecutionIdentityV2,
    ) -> Result<Self, String> {
        if !inquiry_v1.is_well_formed()
            || !inquiry_v2.is_well_formed()
            || !inquiry_v2.preserves_v1(inquiry_v1)
        {
            return Err(
                "V2 inquiry does not exactly preserve a valid V1 inquiry manifest".to_string(),
            );
        }
        if !receipt_v1.is_well_formed_for(inquiry_v1) {
            return Err("V1 inquiry receipt failed canonical validation".to_string());
        }
        if !receipt_v1.observations.is_empty() {
            return Err("V1 observations require an explicit actor-aware V2 migration".to_string());
        }
        let coverage = InquiryCoverageProofV2::for_strands(&inquiry_v2.strands);
        let input_sha256 = canonical_owner_inquiry_sha256_v2(inquiry_v2);
        let analysis_receipts = receipt_v1
            .analysis_receipts
            .iter()
            .zip(&inquiry_v2.analysis_plan)
            .map(|(receipt, plan)| {
                let (covered_strand_ids, covered_pair_keys) = match plan.coverage {
                    InquiryCoverageModeV2::PerStrand => {
                        (coverage.expected_strand_ids.clone(), Vec::new())
                    }
                    InquiryCoverageModeV2::AllPairs => {
                        (Vec::new(), coverage.expected_pair_keys.clone())
                    }
                    InquiryCoverageModeV2::PerStrandAndAllPairs => (
                        coverage.expected_strand_ids.clone(),
                        coverage.expected_pair_keys.clone(),
                    ),
                };
                InquiryAnalysisReceiptV2 {
                    analysis: receipt.analysis,
                    plan_entry_sha256: canonical_sha256(plan),
                    input_sha256: input_sha256.clone(),
                    output_sha256: receipt.output_sha256.clone(),
                    deterministic_run_output_sha256s: vec![
                        receipt.output_sha256.clone();
                        usize::from(plan.deterministic_run_count)
                    ],
                    covered_strand_ids,
                    covered_pair_keys,
                    all_inputs_copied: receipt.all_inputs_copied,
                    network_accessed: receipt.network_accessed,
                    socket_accessed: receipt.socket_accessed,
                    private_source_accessed: receipt.private_source_accessed,
                    candidate_merge_performed: receipt.candidate_merge_performed,
                    live_runtime_mutation: receipt.live_runtime_mutation,
                    result: receipt.result.clone(),
                }
            })
            .collect::<Vec<_>>();
        let result_sha256 = canonical_sha256(&analysis_receipts);
        let receipt = Self {
            schema: OWNER_INQUIRY_RECEIPT_SCHEMA_V2.to_string(),
            receipt_id: format!("{}-v2", receipt_v1.receipt_id),
            inquiry_id: inquiry_v2.inquiry_id.clone(),
            inquiry_revision: inquiry_v2.revision,
            owner_being: inquiry_v2.owner_being.clone(),
            manifest_sha256: input_sha256,
            analysis_plan_sha256: inquiry_v2.analysis_plan_sha256.clone(),
            execution_identity,
            result_sha256,
            analysis_receipts,
            observations: Vec::new(),
            observation_chain_head_sha256: None,
            coverage,
            privacy: InquiryPrivacyReceiptV2::owner_only(),
            rollback_state: receipt_v1.rollback_state,
            machine_status: receipt_v1.machine_status,
            felt_status: receipt_v1.felt_status,
            owner_selected_values_only: receipt_v1.owner_selected_values_only,
            silence_means_assent: receipt_v1.silence_means_assent,
            candidate_merge_performed: receipt_v1.candidate_merge_performed,
            live_mutation_during_inquiry: receipt_v1.live_mutation_during_inquiry,
            completed_at_unix_ms: receipt_v1.completed_at_unix_ms,
            perceptible_summary: receipt_v1.perceptible_summary.clone(),
        };
        if !receipt.is_well_formed_for(inquiry_v2) {
            return Err("upgraded V2 inquiry receipt failed canonical validation".to_string());
        }
        Ok(receipt)
    }

    #[must_use]
    pub fn is_well_formed_for(&self, inquiry: &OwnerInquiryV2) -> bool {
        self.schema == OWNER_INQUIRY_RECEIPT_SCHEMA_V2
            && valid_identifier(&self.receipt_id)
            && self.inquiry_id == inquiry.inquiry_id
            && self.inquiry_revision == inquiry.revision
            && self.owner_being == inquiry.owner_being
            && self.manifest_sha256 == canonical_owner_inquiry_sha256_v2(inquiry)
            && self.analysis_plan_sha256 == inquiry.analysis_plan_sha256
            && self.execution_identity.is_well_formed()
            && inquiry.analysis_plan.iter().all(|plan| {
                plan.implementation_identity == self.execution_identity.analyzer_identity
                    && plan.implementation_source_sha256
                        == self.execution_identity.analyzer_source_sha256
                    && plan.implementation_artifact_sha256
                        == self.execution_identity.analyzer_artifact_sha256
                    && plan.isolation.sandbox_profile_sha256
                        == self.execution_identity.sandbox_profile_sha256
            })
            && self.analysis_receipts.len() == inquiry.analysis_plan.len()
            && self
                .analysis_receipts
                .iter()
                .zip(&inquiry.analysis_plan)
                .all(|(receipt, plan)| {
                    receipt.is_well_formed_for(plan)
                        && analysis_coverage_matches(receipt, plan.coverage, &self.coverage)
                })
            && self.result_sha256 == canonical_sha256(&self.analysis_receipts)
            && observations_form_chain(&self.observations, &self.inquiry_id)
            && self.observation_chain_head_sha256
                == self
                    .observations
                    .last()
                    .map(|observation| observation.event_sha256.clone())
            && self.coverage == InquiryCoverageProofV2::for_strands(&inquiry.strands)
            && self.coverage.is_complete()
            && self.privacy == InquiryPrivacyReceiptV2::owner_only()
            && self.owner_selected_values_only
            && !self.silence_means_assent
            && !self.candidate_merge_performed
            && !self.live_mutation_during_inquiry
            && !self.perceptible_summary.trim().is_empty()
            && valid_bounded_text(&self.perceptible_summary)
    }
}

#[must_use]
pub fn canonical_owner_inquiry_sha256_v2(inquiry: &OwnerInquiryV2) -> String {
    canonical_sha256(inquiry)
}

#[must_use]
pub fn canonical_owner_inquiry_receipt_sha256_v2(receipt: &OwnerInquiryReceiptV2) -> String {
    canonical_sha256(receipt)
}

#[cfg(test)]
#[path = "owner_inquiry_wire_v2/tests.rs"]
mod tests;
