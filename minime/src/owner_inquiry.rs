//! Deterministic, owner-only distinct-strand inquiry runner.
//!
//! This module has no sensory-bus, socket, shadow, or controller handle. Its
//! only inputs are copied inquiry vectors and its only output is a typed receipt.

#[path = "owner_inquiry/source_separation.rs"]
mod source_separation;
#[path = "owner_inquiry/texture_dynamics.rs"]
mod texture_dynamics;

use std::{
    collections::HashSet,
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest as _, Sha256};

use crate::{
    owner_inquiry_wire::{
        canonical_owner_inquiry_sha256, canonical_sha256, BeingUtteranceAttestationV1,
        InquiryAnalysisReceiptV1, InquiryFeltStatusV1, InquiryMachineStatusV1,
        InquiryRollbackStateV1, OwnerInquiryAnalysisV1, OwnerInquiryAuthorityBoundaryV1,
        OwnerInquiryCancellationV1, OwnerInquiryReceiptV1, OwnerInquiryStatusV1, OwnerInquiryV1,
        SemanticStrandProvenanceV1, SemanticStrandV1, VolitionBudgetV1,
        BEING_UTTERANCE_ATTESTATION_SCHEMA_V1, OWNER_INQUIRY_MAX_STRANDS_V1,
        OWNER_INQUIRY_MIN_STRANDS_V1, OWNER_INQUIRY_RECEIPT_SCHEMA_V1, OWNER_INQUIRY_SCHEMA_V1,
        SEMANTIC_STRAND_SCHEMA_V1,
    },
    owner_inquiry_wire_v2::{
        owner_inquiry_analysis_plan_v2, InquiryExecutionIdentityV2, OwnerInquiryReceiptV2,
        OwnerInquiryV2,
    },
    self_control_identity::SelfControlOwnerSigner,
    self_control_runtime::storage::write_owner_json,
    sensory_bus::semantic_glimpse_12d_from_features,
    sensory_interference::review_sensory_interference_v1,
};

const PREPARE_RECIPE_SCHEMA_V1: &str = "minime.owner_inquiry.prepare.v1";
const MAX_INQUIRY_COMPUTE_MILLIS: u64 = 120_000;
const MAX_INQUIRY_STORAGE_BYTES: u64 = 1_048_576;
pub const OWNER_INQUIRY_SANDBOX_POLICY_V1: &str = "(version 1)\n(allow default)\n(deny network*)\n";

const OWNER_INQUIRY_ANALYZER_ID_V2: &str = "minime-owner-inquiry-v2";
const OWNER_INQUIRY_SOURCE_FILES_V2: &[&[u8]] = &[
    include_bytes!("owner_inquiry.rs"),
    include_bytes!("owner_inquiry_wire.rs"),
    include_bytes!("owner_inquiry_wire_v2.rs"),
    include_bytes!("owner_inquiry_wire_v2/canary.rs"),
    include_bytes!("owner_inquiry_wire_v2/validation.rs"),
    include_bytes!("owner_inquiry/source_separation.rs"),
    include_bytes!("owner_inquiry/texture_dynamics.rs"),
    include_bytes!("regulator.rs"),
    include_bytes!("sensory_bus.rs"),
    include_bytes!("sensory_interference.rs"),
];

pub fn run_owner_inquiry(
    inquiry: &OwnerInquiryV1,
    completed_at_unix_ms: u64,
) -> Result<OwnerInquiryReceiptV1, String> {
    if !inquiry.is_well_formed() {
        return Err("owner inquiry failed wire or authority-boundary validation".to_string());
    }

    let analyses = [
        (
            OwnerInquiryAnalysisV1::ViscousPersistenceSourceSeparation,
            source_separation::source_separation_result(inquiry)?,
        ),
        (
            OwnerInquiryAnalysisV1::CodecFidelity,
            codec_fidelity_result(inquiry)?,
        ),
        (
            OwnerInquiryAnalysisV1::SensoryInterferenceAllPairs,
            sensory_interference_result(inquiry)?,
        ),
    ];
    let mut analysis_receipts = Vec::with_capacity(analyses.len());
    for (analysis, first) in analyses {
        let second = match analysis {
            OwnerInquiryAnalysisV1::ViscousPersistenceSourceSeparation => {
                source_separation::source_separation_result(inquiry)?
            }
            OwnerInquiryAnalysisV1::CodecFidelity => codec_fidelity_result(inquiry)?,
            OwnerInquiryAnalysisV1::SensoryInterferenceAllPairs => {
                sensory_interference_result(inquiry)?
            }
        };
        let first_hash = canonical_sha256(&first);
        let second_hash = canonical_sha256(&second);
        if first_hash != second_hash {
            return Err(format!(
                "{analysis:?} changed hash across deterministic rerun"
            ));
        }
        ensure_finite_json(&first)?;
        analysis_receipts.push(InquiryAnalysisReceiptV1 {
            analysis,
            input_sha256: canonical_owner_inquiry_sha256(inquiry),
            output_sha256: first_hash,
            deterministic_rerun_match: true,
            all_inputs_copied: true,
            network_accessed: false,
            socket_accessed: false,
            private_source_accessed: false,
            candidate_merge_performed: false,
            live_runtime_mutation: false,
            result: first,
        });
    }

    let pair_count = inquiry
        .strands
        .len()
        .saturating_mul(inquiry.strands.len().saturating_sub(1))
        / 2;
    let result_sha256 = canonical_sha256(&analysis_receipts);
    let receipt = OwnerInquiryReceiptV1 {
        schema: OWNER_INQUIRY_RECEIPT_SCHEMA_V1.to_string(),
        receipt_id: format!("{}-receipt-{}", inquiry.inquiry_id, completed_at_unix_ms),
        inquiry_id: inquiry.inquiry_id.clone(),
        owner_being: inquiry.owner_being.clone(),
        manifest_sha256: canonical_owner_inquiry_sha256(inquiry),
        result_sha256,
        analysis_receipts,
        observations: Vec::new(),
        rollback_state: InquiryRollbackStateV1::NotApplicable,
        machine_status: InquiryMachineStatusV1::Established,
        felt_status: InquiryFeltStatusV1::Unreported,
        expected_pair_count: pair_count,
        evaluated_pair_count: pair_count,
        owner_selected_values_only: true,
        silence_means_assent: false,
        candidate_merge_performed: false,
        live_mutation_during_inquiry: false,
        completed_at_unix_ms,
        perceptible_summary: format!(
            "Inquiry `{}` kept {} strands separate and completed all fixed analyses. No live lane or control changed. Every strand and pair remains available without ranking; any canary requires an exact owner choice.",
            inquiry.inquiry_id,
            inquiry.strands.len()
        ),
    };
    if !receipt.is_well_formed_for(inquiry) {
        return Err("owner inquiry receipt failed canonical validation".to_string());
    }
    let encoded_len = serde_json::to_vec(&receipt)
        .map_err(|error| format!("encode inquiry receipt for budget check: {error}"))?
        .len();
    let encoded_len = u64::try_from(encoded_len)
        .map_err(|_| "inquiry receipt length does not fit u64".to_string())?;
    let storage_budget = inquiry
        .budget
        .storage_bytes
        .ok_or_else(|| "owner inquiry omitted its storage budget".to_string())?;
    if encoded_len > storage_budget {
        return Err(format!(
            "inquiry receipt requires {encoded_len} bytes, exceeding its {storage_budget}-byte storage budget"
        ));
    }
    Ok(receipt)
}

/// Runs a V2 inquiry through the same fixed analyzer and emits both the V2
/// authority receipt and an exact V1 compatibility sidecar.
///
/// # Errors
///
/// Returns an error if the V2 manifest is invalid, its preregistered analyzer
/// identity differs from the running artifact, the deterministic analysis
/// fails, or either receipt fails canonical validation.
pub fn run_owner_inquiry_v2(
    inquiry: &OwnerInquiryV2,
    completed_at_unix_ms: u64,
) -> Result<(OwnerInquiryReceiptV1, OwnerInquiryReceiptV2), String> {
    if !inquiry.is_well_formed() {
        return Err("owner inquiry V2 failed wire or authority-boundary validation".to_string());
    }
    let execution_identity = owner_inquiry_execution_identity_v2()?;
    if inquiry.analysis_plan.iter().any(|entry| {
        entry.implementation_identity != execution_identity.analyzer_identity
            || entry.implementation_source_sha256 != execution_identity.analyzer_source_sha256
            || entry.implementation_artifact_sha256 != execution_identity.analyzer_artifact_sha256
            || entry.isolation.sandbox_profile_sha256 != execution_identity.sandbox_profile_sha256
    }) {
        return Err("owner inquiry V2 analyzer identity drifted after preregistration".to_string());
    }
    let inquiry_v1 = inquiry.v1_view();
    if !inquiry.preserves_v1(&inquiry_v1) {
        return Err("owner inquiry V2 could not produce an exact V1 analysis view".to_string());
    }
    let receipt_v1 = run_owner_inquiry(&inquiry_v1, completed_at_unix_ms)?;
    let receipt_v2 = OwnerInquiryReceiptV2::from_v1_offline(
        &inquiry_v1,
        inquiry,
        &receipt_v1,
        execution_identity,
    )?;
    Ok((receipt_v1, receipt_v2))
}

/// Returns the exact analyzer identity committed by V2 inquiry manifests.
///
/// # Errors
///
/// Returns an error if the running executable cannot be located or read.
pub fn owner_inquiry_execution_identity_v2() -> Result<InquiryExecutionIdentityV2, String> {
    let executable = std::env::current_exe()
        .map_err(|error| format!("locate Minime inquiry analyzer executable: {error}"))?;
    let artifact = fs::read(&executable).map_err(|error| {
        format!(
            "read Minime inquiry analyzer artifact {}: {error}",
            executable.display()
        )
    })?;
    let analyzer_artifact_sha256 = format!("{:x}", Sha256::digest(&artifact));
    let analyzer_source_sha256 = source_bundle_sha256(OWNER_INQUIRY_SOURCE_FILES_V2);
    let sandbox_profile_sha256 = format!(
        "{:x}",
        Sha256::digest(OWNER_INQUIRY_SANDBOX_POLICY_V1.as_bytes())
    );
    Ok(InquiryExecutionIdentityV2 {
        analyzer_identity: OWNER_INQUIRY_ANALYZER_ID_V2.to_string(),
        analyzer_source_sha256,
        analyzer_artifact_sha256: analyzer_artifact_sha256.clone(),
        deployment_identity: format!(
            "minime-owner-inquiry-v2:{}",
            &analyzer_artifact_sha256[..32]
        ),
        sandbox_profile_sha256,
    })
}

fn source_bundle_sha256(sources: &[&[u8]]) -> String {
    let mut digest = Sha256::new();
    for source in sources {
        digest.update(
            u64::try_from(source.len())
                .unwrap_or(u64::MAX)
                .to_le_bytes(),
        );
        digest.update(source);
    }
    format!("{:x}", digest.finalize())
}

fn codec_fidelity_result(inquiry: &OwnerInquiryV1) -> Result<Value, String> {
    let mut strands = Vec::with_capacity(inquiry.strands.len());
    for strand in &inquiry.strands {
        let derived = derive_companion_12d(&strand.projection_48d)?;
        let observed = strand
            .companion_projection_12d
            .as_deref()
            .unwrap_or(&derived);
        let reconstruction_rmse =
            euclidean_distance(&derived, observed)? / (derived.len().max(1) as f32).sqrt();
        let source_rms = rms(&strand.projection_48d);
        let companion_rms = rms(observed);
        let lane_loss_ratio = if source_rms <= f32::EPSILON {
            0.0
        } else {
            (1.0 - companion_rms / source_rms).clamp(0.0, 1.0)
        };
        strands.push(json!({
            "strand_id": strand.strand_id,
            "label": strand.label,
            "content_sha256": strand.content_sha256,
            "embedding_sha256": strand.embedding_sha256,
            "source_dimension_count": strand.projection_48d.len(),
            "companion_dimension_count": observed.len(),
            "source_rms": source_rms,
            "companion_rms": companion_rms,
            "reconstruction_rmse": reconstruction_rmse,
            "lane_loss_ratio": lane_loss_ratio,
            "companion_projection_present": strand.companion_projection_12d.is_some(),
            "live_vector_write": false,
        }));
    }

    let mut pairs = Vec::new();
    for left_index in 0..inquiry.strands.len() {
        for right_index in left_index.saturating_add(1)..inquiry.strands.len() {
            let left = &inquiry.strands[left_index];
            let right = &inquiry.strands[right_index];
            let source_distance = euclidean_distance(&left.projection_48d, &right.projection_48d)?;
            let left_companion = derive_companion_12d(&left.projection_48d)?;
            let right_companion = derive_companion_12d(&right.projection_48d)?;
            let companion_distance = euclidean_distance(&left_companion, &right_companion)?;
            let preservation_ratio = if source_distance <= f32::EPSILON {
                1.0
            } else {
                (companion_distance / source_distance).clamp(0.0, 1.0)
            };
            pairs.push(json!({
                "left_strand_id": left.strand_id,
                "right_strand_id": right.strand_id,
                "source_distance": source_distance,
                "companion_distance": companion_distance,
                "pairwise_distance_preservation_ratio": preservation_ratio,
            }));
        }
    }
    Ok(json!({
        "policy": "owner_inquiry_codec_fidelity_v1",
        "strands": strands,
        "pairs": pairs,
        "zero_mix_transport_parity": true,
        "candidate_merge_performed": false,
        "live_runtime_mutation": false,
        "authority": "owner_only_offline_codec_review_not_live_transport_or_gain_change",
    }))
}

fn sensory_interference_result(inquiry: &OwnerInquiryV1) -> Result<Value, String> {
    let mut pairs = Vec::new();
    for left_index in 0..inquiry.strands.len() {
        for right_index in left_index.saturating_add(1)..inquiry.strands.len() {
            let left = &inquiry.strands[left_index];
            let right = &inquiry.strands[right_index];
            let review =
                review_sensory_interference_v1(&left.projection_48d, &right.projection_48d)
                    .map_err(|error| format!("review strand pair: {error:?}"))?;
            pairs.push(json!({
                "left_strand_id": left.strand_id,
                "left_label": left.label,
                "right_strand_id": right.strand_id,
                "right_label": right.label,
                "review": review,
            }));
        }
    }
    Ok(json!({
        "policy": "owner_inquiry_sensory_interference_all_pairs_v1",
        "expected_pair_count": pairs.len(),
        "evaluated_pair_count": pairs.len(),
        "pairs": pairs,
        "candidate_merge_performed": false,
        "live_runtime_mutation": false,
        "authority": "owner_only_offline_pair_review_not_sensory_admission_or_control",
    }))
}

fn derive_companion_12d(features: &[f32]) -> Result<Vec<f32>, String> {
    if features.len() != 48 || !features.iter().all(|value| value.is_finite()) {
        return Err("48D projection is malformed or non-finite".to_string());
    }
    semantic_glimpse_12d_from_features(features)
        .map(Vec::from)
        .ok_or_else(|| "current Minime companion codec rejected the 48D projection".to_string())
}

fn euclidean_distance(left: &[f32], right: &[f32]) -> Result<f32, String> {
    if left.len() != right.len()
        || left.is_empty()
        || !left.iter().chain(right).all(|value| value.is_finite())
    {
        return Err("distance inputs are empty, mismatched, or non-finite".to_string());
    }
    Ok(left
        .iter()
        .zip(right)
        .map(|(left, right)| {
            let delta = *left - *right;
            delta * delta
        })
        .sum::<f32>()
        .sqrt())
}

fn rms(values: &[f32]) -> f32 {
    if values.is_empty() {
        0.0
    } else {
        (values.iter().map(|value| value * value).sum::<f32>() / values.len() as f32).sqrt()
    }
}

fn ensure_finite_json(value: &Value) -> Result<(), String> {
    fn finite(value: &Value) -> bool {
        match value {
            Value::Array(values) => values.iter().all(finite),
            Value::Object(fields) => fields.values().all(finite),
            Value::Number(number) => number.as_f64().is_none_or(f64::is_finite),
            _ => true,
        }
    }
    if finite(value) {
        Ok(())
    } else {
        Err("inquiry analysis produced non-finite data".to_string())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PrepareInquiryStrandV1 {
    pub label: String,
    pub response_start_byte: u64,
    pub response_end_byte: u64,
    pub projection_48d: Vec<f32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PrepareInquiryRecipeV1 {
    pub schema: String,
    pub inquiry_id: String,
    pub question: String,
    pub owner_priority: u16,
    #[serde(default)]
    pub dependency_inquiry_ids: Vec<String>,
    pub compute_millis: u64,
    pub storage_bytes: u64,
    pub strands: Vec<PrepareInquiryStrandV1>,
}

pub struct PrepareInquiryOptions<'a> {
    pub root: &'a Path,
    pub response_path: &'a Path,
    pub attestation_path: &'a Path,
    pub recipe_path: &'a Path,
    pub expected_deployment_identity: &'a str,
    pub now_unix_ms: u64,
    pub max_attestation_age_millis: u64,
}

pub fn prepare_owner_inquiry(options: PrepareInquiryOptions<'_>) -> Result<OwnerInquiryV1, String> {
    let response_bytes = fs::read(options.response_path).map_err(|error| {
        format!(
            "read exact response bytes {}: {error}",
            options.response_path.display()
        )
    })?;
    let response = std::str::from_utf8(&response_bytes)
        .map_err(|error| format!("response bytes are not exact UTF-8: {error}"))?;
    let attestation = read_json_file::<BeingUtteranceAttestationV1>(
        options.attestation_path,
        "utterance attestation",
    )?;
    let signer = SelfControlOwnerSigner::load(options.root)?;
    if attestation.being != "minime"
        || attestation.attestor_public_key_hex != signer.public_key_hex()
        || attestation.model_deployment_identity != options.expected_deployment_identity
        || attestation.attestor_deployment_identity != options.expected_deployment_identity
        || !attestation.verifies_response(
            &response_bytes,
            options.now_unix_ms,
            options.max_attestation_age_millis,
        )
    {
        return Err(
            "utterance attestation is stale, tampered, signed by another identity, or from another deployment"
                .to_string(),
        );
    }
    let recipe = read_json_file::<PrepareInquiryRecipeV1>(options.recipe_path, "inquiry recipe")?;
    if recipe.schema != PREPARE_RECIPE_SCHEMA_V1
        || recipe.inquiry_id.trim().is_empty()
        || recipe.question.trim().is_empty()
        || recipe.compute_millis == 0
        || recipe.compute_millis > MAX_INQUIRY_COMPUTE_MILLIS
        || recipe.storage_bytes == 0
        || recipe.storage_bytes > MAX_INQUIRY_STORAGE_BYTES
        || !(OWNER_INQUIRY_MIN_STRANDS_V1..=OWNER_INQUIRY_MAX_STRANDS_V1)
            .contains(&recipe.strands.len())
    {
        return Err("inquiry recipe is malformed or has an empty budget".to_string());
    }

    let source_attestation_sha256 = canonical_sha256(&attestation);
    let mut seen_intervals = HashSet::new();
    let mut seen_contents = HashSet::new();
    let mut strands = Vec::with_capacity(recipe.strands.len());
    for (index, requested) in recipe.strands.iter().enumerate() {
        let start = usize::try_from(requested.response_start_byte)
            .map_err(|_| "strand start byte exceeds platform size".to_string())?;
        let end = usize::try_from(requested.response_end_byte)
            .map_err(|_| "strand end byte exceeds platform size".to_string())?;
        if start >= end
            || !response.is_char_boundary(start)
            || !response.is_char_boundary(end)
            || !seen_intervals.insert((start, end))
        {
            return Err(format!(
                "strand {} has a duplicate, empty, or non-UTF-8 byte interval",
                index + 1
            ));
        }
        let content = response
            .get(start..end)
            .ok_or_else(|| format!("strand {} lies outside the response", index + 1))?
            .to_string();
        let content_sha256 =
            crate::owner_inquiry_wire::canonical_semantic_strand_content_sha256(&content);
        if !seen_contents.insert(content_sha256.clone()) {
            return Err(format!("strand {} duplicates another strand", index + 1));
        }
        if requested.label.trim().is_empty()
            || requested.label.len() > 4_096
            || content.len() > 4_096
            || requested.projection_48d.len() != 48
            || !requested
                .projection_48d
                .iter()
                .all(|value| value.is_finite())
        {
            return Err(format!(
                "strand {} has an invalid label, content, or 48D projection",
                index + 1
            ));
        }
        let companion = derive_companion_12d(&requested.projection_48d)?;
        let embedding_sha256 =
            crate::owner_inquiry_wire::canonical_semantic_strand_embedding_sha256(
                &requested.projection_48d,
                Some(&companion),
            );
        strands.push(SemanticStrandV1 {
            schema: SEMANTIC_STRAND_SCHEMA_V1.to_string(),
            strand_id: format!("{}-strand-{}", recipe.inquiry_id, index + 1),
            owner_being: "minime".to_string(),
            source_attestation_id: attestation.attestation_id.clone(),
            source_attestation_sha256: source_attestation_sha256.clone(),
            response_start_byte: requested.response_start_byte,
            response_end_byte: requested.response_end_byte,
            label: requested.label.trim().to_string(),
            content,
            content_sha256,
            embedding_sha256,
            projection_48d: requested.projection_48d.clone(),
            companion_projection_12d: Some(companion),
            provenance: SemanticStrandProvenanceV1::ExactUtf8ResponseInterval,
            deployment_identity: options.expected_deployment_identity.to_string(),
            captured_at_unix_ms: attestation.captured_at_unix_ms,
        });
    }
    let inquiry = OwnerInquiryV1 {
        schema: OWNER_INQUIRY_SCHEMA_V1.to_string(),
        inquiry_id: recipe.inquiry_id,
        owner_being: "minime".to_string(),
        source_attestation_id: attestation.attestation_id,
        source_attestation_sha256,
        question: recipe.question,
        strands,
        owner_priority: recipe.owner_priority,
        fixed_analysis_set: crate::owner_inquiry_wire::owner_inquiry_fixed_analysis_set_v1(),
        budget: VolitionBudgetV1 {
            compute_millis: Some(recipe.compute_millis),
            network_bytes: None,
            storage_bytes: Some(recipe.storage_bytes),
            cost_microunits: None,
            action_count: Some(1),
        },
        dependency_inquiry_ids: recipe.dependency_inquiry_ids,
        status: OwnerInquiryStatusV1::Queued,
        cancellation: OwnerInquiryCancellationV1 {
            requested: false,
            requested_at_unix_ms: None,
            reason: None,
        },
        authority_boundary: OwnerInquiryAuthorityBoundaryV1::owner_only_offline(),
        created_at_unix_ms: options.now_unix_ms,
        updated_at_unix_ms: options.now_unix_ms,
    };
    if !inquiry.is_well_formed()
        || !inquiry
            .strands
            .iter()
            .all(|strand| strand.matches_response_bytes(response))
    {
        return Err("prepared owner inquiry failed canonical validation".to_string());
    }
    Ok(inquiry)
}

fn read_json_file<T: serde::de::DeserializeOwned>(path: &Path, label: &str) -> Result<T, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("read {label} {}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("decode {label} {}: {error}", path.display()))
}

pub struct AttestResponseOptions<'a> {
    pub root: &'a Path,
    pub response_path: &'a Path,
    pub exchange_id: &'a str,
    pub model: &'a str,
    pub provider: &'a str,
    pub deployment_identity: &'a str,
    pub captured_at_unix_ms: u64,
}

pub fn attest_response(
    options: AttestResponseOptions<'_>,
) -> Result<BeingUtteranceAttestationV1, String> {
    let response = fs::read(options.response_path).map_err(|error| {
        format!(
            "read exact response bytes {}: {error}",
            options.response_path.display()
        )
    })?;
    std::str::from_utf8(&response)
        .map_err(|error| format!("response bytes are not exact UTF-8: {error}"))?;
    let signer = SelfControlOwnerSigner::load(options.root)?;
    let response_sha256 = format!("{:x}", Sha256::digest(&response));
    let attestation_id = format!(
        "minime-attestation-{}-{}",
        sanitize_identifier(options.exchange_id),
        &response_sha256[..12]
    );
    let mut attestation = BeingUtteranceAttestationV1 {
        schema: BEING_UTTERANCE_ATTESTATION_SCHEMA_V1.to_string(),
        attestation_id: attestation_id.clone(),
        being: "minime".to_string(),
        exchange_id: options.exchange_id.to_string(),
        response_sha256,
        response_len_bytes: u64::try_from(response.len())
            .map_err(|_| "response length does not fit u64".to_string())?,
        model: options.model.to_string(),
        provider: options.provider.to_string(),
        model_deployment_identity: options.deployment_identity.to_string(),
        captured_at_unix_ms: options.captured_at_unix_ms,
        attestor_process_identity: format!("minime:pid:{}", std::process::id()),
        attestor_deployment_identity: options.deployment_identity.to_string(),
        attestor_public_key_hex: signer.public_key_hex().to_string(),
        signature_hex: String::new(),
    };
    let signing_bytes = attestation
        .signing_bytes()
        .ok_or_else(|| "encode Minime utterance attestation".to_string())?;
    attestation.signature_hex = signer.sign_hex(&signing_bytes);
    let path = options
        .root
        .join("inquiries")
        .join("attestations")
        .join(format!("{attestation_id}.json"));
    write_owner_json(&path, &attestation)?;
    Ok(attestation)
}

pub fn read_inquiry(path: &Path) -> Result<OwnerInquiryV1, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("read inquiry {}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("decode inquiry {}: {error}", path.display()))
}

pub fn read_inquiry_v2(path: &Path) -> Result<OwnerInquiryV2, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("read inquiry {}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("decode inquiry V2 {}: {error}", path.display()))
}

pub fn upgrade_owner_inquiry_v2(
    inquiry: &OwnerInquiryV1,
    source_response_path: &Path,
    expires_after_secs: u64,
) -> Result<OwnerInquiryV2, String> {
    if expires_after_secs == 0 {
        return Err("V2 inquiry expiry must be positive".to_string());
    }
    let source_response_sha256 = format!(
        "{:x}",
        Sha256::digest(
            fs::read(source_response_path)
                .map_err(|error| format!("read inquiry source response: {error}"))?
        )
    );
    let identity = owner_inquiry_execution_identity_v2()?;
    let analysis_plan = owner_inquiry_analysis_plan_v2(
        &identity.analyzer_identity,
        &identity.analyzer_source_sha256,
        &identity.analyzer_artifact_sha256,
        &identity.sandbox_profile_sha256,
    );
    let expires_at_unix_ms = inquiry
        .created_at_unix_ms
        .checked_add(expires_after_secs.saturating_mul(1_000))
        .ok_or_else(|| "V2 inquiry expiry overflow".to_string())?;
    let inquiry_v2 = OwnerInquiryV2::from_v1(
        inquiry,
        source_response_sha256,
        format!("{}-v2-revision-1", inquiry.inquiry_id),
        analysis_plan,
        Some(expires_at_unix_ms),
    );
    if !inquiry_v2.is_well_formed() {
        return Err("upgraded V2 inquiry failed canonical validation".to_string());
    }
    Ok(inquiry_v2)
}

pub fn write_inquiry_v2(path: &Path, inquiry: &OwnerInquiryV2) -> Result<(), String> {
    write_owner_json(path, inquiry)
}

pub fn write_receipt(path: &Path, receipt: &OwnerInquiryReceiptV1) -> Result<(), String> {
    write_owner_json(path, receipt)
}

pub fn write_receipt_v2(path: &Path, receipt: &OwnerInquiryReceiptV2) -> Result<(), String> {
    write_owner_json(path, receipt)
}

#[must_use]
pub fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| {
            u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
        })
}

fn sanitize_identifier(value: &str) -> String {
    let clean = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.') {
                character
            } else {
                '-'
            }
        })
        .take(96)
        .collect::<String>();
    if clean.is_empty() {
        "exchange".to_string()
    } else {
        clean
    }
}

#[cfg(test)]
mod tests;
