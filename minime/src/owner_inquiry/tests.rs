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
fn texture_dynamics_is_typed_complete_finite_and_source_exact() {
    let mut inquiry = inquiry();
    let mut third = inquiry.strands[0].clone();
    third.strand_id = "middle".to_string();
    third.label = "middle".to_string();
    third.content = "middle".to_string();
    third.content_sha256 = canonical_semantic_strand_content_sha256(&third.content);
    third.response_start_byte = 10;
    third.response_end_byte = 16;
    third.projection_48d = (0..48)
        .map(|index| ((index as f32 + 1.0) / 31.0).sin() * 0.5)
        .collect();
    third.companion_projection_12d = Some(derive_companion_12d(&third.projection_48d).unwrap());
    third.embedding_sha256 = canonical_semantic_strand_embedding_sha256(
        &third.projection_48d,
        third.companion_projection_12d.as_deref(),
    );
    inquiry.strands.push(third);

    let typed = texture_dynamics::texture_dynamics_snapshot_v1(&inquiry).unwrap();
    let typed_json = serde_json::to_value(&typed).unwrap();
    ensure_finite_json(&typed_json).unwrap();
    assert_eq!(typed_json["strand_count"], 3);
    assert_eq!(typed_json["unordered_pair_count"], 3);
    assert_eq!(typed_json["strands"].as_array().unwrap().len(), 3);
    assert_eq!(typed_json["pairs"].as_array().unwrap().len(), 3);
    assert_eq!(
        typed_json["felt_status"]["author_domain"],
        "owner_authored_only"
    );
    assert_eq!(
        typed_json["felt_status"]["machine_may_set_felt_status"],
        false
    );

    let expected_metrics = [
        "projected_density_gradient",
        "projected_packing",
        "distinguishability",
        "pressure_proxy",
        "semantic_viscosity",
        "temporal_drag",
        "persistence",
        "structural_stagnation_proxy",
        "raw_reservoir_mode_packing",
        "shadow_dispersal",
    ];
    for strand in typed_json["strands"].as_array().unwrap() {
        let source = &strand["source"];
        assert_eq!(source["deployment_identity"], "deploy-1");
        assert_eq!(source["sampled_at_unix_ms"], 10);
        assert_eq!(source["source_attestation_id"], "attestation-1");
        assert_eq!(source["source_attestation_sha256"], "a".repeat(64));
        assert!(source["source_response_interval_sha256"].as_str().is_some());
        assert!(source["source_evidence_sha256"].as_str().is_some());
        let metrics = strand["metrics"].as_object().unwrap();
        assert_eq!(metrics.len(), expected_metrics.len());
        for metric_name in expected_metrics {
            let metric = &metrics[metric_name];
            assert_eq!(metric["metric"], metric_name);
            assert_eq!(
                metric["producer"],
                "minime.owner_inquiry.texture_dynamics_v1"
            );
            assert_eq!(metric["sampled_at_unix_ms"], 10);
            assert_eq!(metric["raw_spectral_telemetry_used"], false);
            assert_eq!(metric["source_evidence_ids"].as_array().unwrap().len(), 1);
            assert_eq!(
                metric["source_evidence_sha256s"].as_array().unwrap().len(),
                1
            );
        }
        assert_eq!(
            metrics["raw_reservoir_mode_packing"]["availability"]["state"],
            "missing"
        );
        assert!(metrics["raw_reservoir_mode_packing"]["value"].is_null());
        assert_eq!(
            metrics["shadow_dispersal"]["availability"]["state"],
            "missing"
        );
        assert!(metrics["shadow_dispersal"]["value"].is_null());
    }
    for pair in typed_json["pairs"].as_array().unwrap() {
        assert_eq!(pair["source_evidence_ids"].as_array().unwrap().len(), 2);
        assert_eq!(pair["pair_averaged"], false);
        assert_eq!(pair["pair_ranked"], false);
        assert_eq!(pair["preferred_strand_selected"], false);
        assert_eq!(pair["candidate_merge_performed"], false);
        assert_eq!(
            pair["codec_fidelity_evidence_ref"]["analysis"],
            "codec_fidelity"
        );
        assert_eq!(
            pair["sensory_interference_evidence_ref"]["analysis"],
            "sensory_interference_all_pairs"
        );
        assert_eq!(
            pair["codec_fidelity_evidence_ref"]["timestamp_proximity_match_allowed"],
            false
        );
        for metric_name in &expected_metrics[..8] {
            let value = pair["absolute_metric_deltas"][metric_name]["value"]
                .as_f64()
                .unwrap();
            assert!(value.is_finite() && value >= 0.0);
        }
    }

    let source_separation = source_separation::source_separation_result(&inquiry).unwrap();
    assert_eq!(
        source_separation["texture_dynamics_snapshot_v1"],
        typed_json
    );
    assert_eq!(owner_inquiry_fixed_analysis_set_v1().len(), 3);
}

#[test]
fn texture_dynamics_contract_matches_astrid_protocol_fixture() {
    const FIXTURE_SHA256: &str = "00048207c164c07aa2ccf67cfa7119dca2246c87d4495118703fe7061d6815f9";
    let fixture_bytes = include_bytes!("../../tests/fixtures/texture_dynamics_contract_v1.json");
    assert_eq!(
        format!("{:x}", Sha256::digest(fixture_bytes)),
        FIXTURE_SHA256
    );
    let fixture: Value = serde_json::from_slice(fixture_bytes).unwrap();
    let snapshot =
        serde_json::to_value(texture_dynamics::texture_dynamics_snapshot_v1(&inquiry()).unwrap())
            .unwrap();
    let metric_keys = fixture["strand_metric_keys"].as_array().unwrap();
    let actual_metrics = snapshot["strands"][0]["metrics"].as_object().unwrap();
    assert!(metric_keys
        .iter()
        .all(|metric| actual_metrics.contains_key(metric.as_str().unwrap())));
    let actual_contract = json!({
        "schema": "texture_dynamics_contract_fixture_v1",
        "nested_in_analysis": "viscous_persistence_source_separation",
        "fixed_analysis_set": owner_inquiry_fixed_analysis_set_v1(),
        "strand_metric_keys": metric_keys,
        "pair_metric_semantics": "absolute_deltas_without_average_rank_merge_or_selection",
        "required_pair_evidence_refs": ["codec_fidelity", "sensory_interference_all_pairs"],
        "raw_reservoir_mode_packing": snapshot["raw_reservoir_mode_packing_state"],
        "shadow_dispersal": snapshot["shadow_dispersal_state"],
        "felt_status_author_domain": snapshot["felt_status"]["author_domain"],
        "semantic_projection_not_raw_spectral_telemetry": snapshot["semantic_projection_not_raw_spectral_telemetry"],
        "live_control_authority": snapshot["live_control_authority"],
    });
    assert_eq!(actual_contract, fixture);
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
