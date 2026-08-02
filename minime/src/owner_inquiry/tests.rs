use super::*;
use crate::owner_inquiry_wire::{
    canonical_json_bytes, canonical_semantic_strand_content_sha256,
    canonical_semantic_strand_embedding_sha256, owner_inquiry_fixed_analysis_set_v1,
    OwnerInquiryAuthorityBoundaryV1, OwnerInquiryCancellationV1, OwnerInquiryStatusV1,
    SemanticStrandProvenanceV1, SemanticStrandV1, VolitionBudgetV1, OWNER_INQUIRY_SCHEMA_V1,
    SEMANTIC_STRAND_SCHEMA_V1,
};
use crate::self_control_identity::provision_minime_owner_identity;
use std::fs;
use tempfile::TempDir;

fn inquiry() -> OwnerInquiryV1 {
    let make_strand = |id: &str, content: &str, start: u64, sign: f32| {
        let projection_48d = (0..48)
            .map(|index| sign * (index as f32 + 1.0) / 64.0)
            .collect::<Vec<_>>();
        let companion_projection_12d = Some(derive_companion_12d(&projection_48d).unwrap());
        SemanticStrandV1 {
            schema: SEMANTIC_STRAND_SCHEMA_V1.to_string(),
            strand_id: id.to_string(),
            owner_being: "minime".to_string(),
            source_attestation_id: "attestation-1".to_string(),
            source_attestation_sha256: "a".repeat(64),
            response_start_byte: start,
            response_end_byte: start + content.len() as u64,
            label: id.to_string(),
            content: content.to_string(),
            content_sha256: canonical_semantic_strand_content_sha256(content),
            embedding_sha256: canonical_semantic_strand_embedding_sha256(
                &projection_48d,
                companion_projection_12d.as_deref(),
            ),
            projection_48d,
            companion_projection_12d,
            provenance: SemanticStrandProvenanceV1::ExactUtf8ResponseInterval,
            deployment_identity: "deploy-1".to_string(),
            captured_at_unix_ms: 10,
        }
    };
    OwnerInquiryV1 {
        schema: OWNER_INQUIRY_SCHEMA_V1.to_string(),
        inquiry_id: "inquiry-1".to_string(),
        owner_being: "minime".to_string(),
        source_attestation_id: "attestation-1".to_string(),
        source_attestation_sha256: "a".repeat(64),
        question: "How do these strands differ?".to_string(),
        strands: vec![
            make_strand("left", "left", 0, 1.0),
            make_strand("right", "right", 5, -1.0),
        ],
        owner_priority: 10,
        fixed_analysis_set: owner_inquiry_fixed_analysis_set_v1(),
        budget: VolitionBudgetV1 {
            compute_millis: Some(5_000),
            storage_bytes: Some(65_536),
            ..VolitionBudgetV1::default()
        },
        dependency_inquiry_ids: Vec::new(),
        status: OwnerInquiryStatusV1::Queued,
        cancellation: OwnerInquiryCancellationV1 {
            requested: false,
            requested_at_unix_ms: None,
            reason: None,
        },
        authority_boundary: OwnerInquiryAuthorityBoundaryV1::owner_only_offline(),
        created_at_unix_ms: 10,
        updated_at_unix_ms: 10,
    }
}

#[test]
fn runner_is_deterministic_all_pairs_and_non_mutating() {
    let inquiry = inquiry();
    let before = inquiry.clone();
    let first = run_owner_inquiry(&inquiry, 20).unwrap();
    let second = run_owner_inquiry(&inquiry, 20).unwrap();
    assert_eq!(first, second);
    assert_eq!(inquiry, before);
    assert_eq!(first.expected_pair_count, 1);
    assert_eq!(first.evaluated_pair_count, 1);
    assert!(first
        .analysis_receipts
        .iter()
        .all(|receipt| receipt.deterministic_rerun_match
            && !receipt.network_accessed
            && !receipt.socket_accessed
            && !receipt.candidate_merge_performed
            && !receipt.live_runtime_mutation));
}

#[test]
fn malformed_vectors_fail_closed() {
    let mut inquiry = inquiry();
    inquiry.strands[0].projection_48d[3] = f32::NAN;
    assert!(run_owner_inquiry(&inquiry, 20).is_err());
}

#[test]
fn output_never_contains_raw_strand_content() {
    let inquiry = inquiry();
    let receipt = run_owner_inquiry(&inquiry, 20).unwrap();
    let encoded = String::from_utf8(canonical_json_bytes(&receipt).unwrap()).unwrap();
    assert!(!encoded.contains("\"content\":\"left\""));
    assert!(!encoded.contains("\"content\":\"right\""));
}

#[test]
fn receipt_fails_closed_when_storage_budget_is_too_small() {
    let mut inquiry = inquiry();
    inquiry.budget.storage_bytes = Some(1);
    assert!(run_owner_inquiry(&inquiry, 20)
        .expect_err("one byte cannot hold the receipt")
        .contains("storage budget"));
}

#[test]
fn prepare_binds_exact_response_spans_signature_and_deployment() {
    let root = TempDir::new().unwrap();
    provision_minime_owner_identity(root.path(), false, 5).unwrap();
    let response = "α strand | beta strand";
    let response_path = root.path().join("response.txt");
    fs::write(&response_path, response).unwrap();
    let attestation = attest_response(AttestResponseOptions {
        root: root.path(),
        response_path: &response_path,
        exchange_id: "exchange-1",
        model: "model-1",
        provider: "test",
        deployment_identity: "deployment-1",
        captured_at_unix_ms: 10,
    })
    .unwrap();
    let attestation_path = root.path().join("attestation.json");
    write_owner_json(&attestation_path, &attestation).unwrap();
    let beta_start = response.find("beta").unwrap();
    let recipe = PrepareInquiryRecipeV1 {
        schema: PREPARE_RECIPE_SCHEMA_V1.to_string(),
        inquiry_id: "inquiry-prepare-1".to_string(),
        question: "Keep these strands distinct?".to_string(),
        owner_priority: 9,
        dependency_inquiry_ids: Vec::new(),
        compute_millis: 5_000,
        storage_bytes: 65_536,
        strands: vec![
            PrepareInquiryStrandV1 {
                label: "alpha".to_string(),
                response_start_byte: 0,
                response_end_byte: "α strand".len() as u64,
                projection_48d: vec![0.25; 48],
            },
            PrepareInquiryStrandV1 {
                label: "beta".to_string(),
                response_start_byte: beta_start as u64,
                response_end_byte: response.len() as u64,
                projection_48d: vec![-0.25; 48],
            },
        ],
    };
    let recipe_path = root.path().join("recipe.json");
    write_owner_json(&recipe_path, &recipe).unwrap();
    let prepared = prepare_owner_inquiry(PrepareInquiryOptions {
        root: root.path(),
        response_path: &response_path,
        attestation_path: &attestation_path,
        recipe_path: &recipe_path,
        expected_deployment_identity: "deployment-1",
        now_unix_ms: 20,
        max_attestation_age_millis: 1_000,
    })
    .unwrap();
    assert_eq!(prepared.strands.len(), 2);
    assert!(prepared.strands[0].matches_response_bytes(response));
    assert_eq!(prepared.strands[0].projection_48d.len(), 48);
    assert_eq!(
        prepared.strands[0]
            .companion_projection_12d
            .as_ref()
            .unwrap()
            .len(),
        12
    );

    assert!(prepare_owner_inquiry(PrepareInquiryOptions {
        root: root.path(),
        response_path: &response_path,
        attestation_path: &attestation_path,
        recipe_path: &recipe_path,
        expected_deployment_identity: "deployment-2",
        now_unix_ms: 20,
        max_attestation_age_millis: 1_000,
    })
    .is_err());
    fs::write(&response_path, "tampered").unwrap();
    assert!(prepare_owner_inquiry(PrepareInquiryOptions {
        root: root.path(),
        response_path: &response_path,
        attestation_path: &attestation_path,
        recipe_path: &recipe_path,
        expected_deployment_identity: "deployment-1",
        now_unix_ms: 20,
        max_attestation_age_millis: 1_000,
    })
    .is_err());
}
