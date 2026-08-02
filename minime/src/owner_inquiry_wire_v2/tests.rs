use super::*;
use crate::owner_inquiry_wire::{
    canonical_semantic_strand_content_sha256, canonical_semantic_strand_embedding_sha256,
    owner_inquiry_fixed_analysis_set_v1, InquiryAnalysisReceiptV1, InquiryObservationV1,
    INQUIRY_OBSERVATION_SCHEMA_V1, OWNER_INQUIRY_RECEIPT_SCHEMA_V1, OWNER_INQUIRY_SCHEMA_V1,
    SEMANTIC_STRAND_BASE_DIMENSIONS_V1, SEMANTIC_STRAND_COMPANION_DIMENSIONS_V1,
    SEMANTIC_STRAND_SCHEMA_V1,
};
use crate::self_control_wire::{SelfControlFamilyV2, SelfControlValuesV2};
use sha2::{Digest as _, Sha256};

fn strand(id: &str, content: &str, start: u64) -> SemanticStrandV1 {
    let projection_48d = vec![0.25; SEMANTIC_STRAND_BASE_DIMENSIONS_V1];
    let companion = Some(vec![0.125; SEMANTIC_STRAND_COMPANION_DIMENSIONS_V1]);
    SemanticStrandV1 {
        schema: SEMANTIC_STRAND_SCHEMA_V1.to_string(),
        strand_id: id.to_string(),
        owner_being: "astrid".to_string(),
        source_attestation_id: "attestation-1".to_string(),
        source_attestation_sha256: "a".repeat(64),
        response_start_byte: start,
        response_end_byte: start.saturating_add(u64::try_from(content.len()).unwrap()),
        label: id.to_string(),
        content: content.to_string(),
        content_sha256: canonical_semantic_strand_content_sha256(content),
        embedding_sha256: canonical_semantic_strand_embedding_sha256(
            &projection_48d,
            companion.as_deref(),
        ),
        projection_48d,
        companion_projection_12d: companion,
        provenance: SemanticStrandProvenanceV1::ExactUtf8ResponseInterval,
        deployment_identity: "deploy-1".to_string(),
        captured_at_unix_ms: 10,
    }
}

fn inquiry_v1() -> OwnerInquiryV1 {
    OwnerInquiryV1 {
        schema: OWNER_INQUIRY_SCHEMA_V1.to_string(),
        inquiry_id: "inquiry-v2".to_string(),
        owner_being: "astrid".to_string(),
        source_attestation_id: "attestation-1".to_string(),
        source_attestation_sha256: "a".repeat(64),
        question: "How do these strands remain distinct?".to_string(),
        strands: vec![strand("left", "left", 0), strand("right", "right", 5)],
        owner_priority: 10,
        fixed_analysis_set: owner_inquiry_fixed_analysis_set_v1(),
        budget: VolitionBudgetV1 {
            compute_millis: Some(5_000),
            storage_bytes: Some(65_536),
            action_count: Some(1),
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

fn analysis_plan() -> Vec<InquiryAnalysisPlanEntryV2> {
    owner_inquiry_analysis_plan_v2(
        "minime-owner-inquiry",
        &"b".repeat(64),
        &"c".repeat(64),
        &"d".repeat(64),
    )
}

fn receipt_v1(inquiry: &OwnerInquiryV1) -> OwnerInquiryReceiptV1 {
    let analysis_receipts = inquiry
        .fixed_analysis_set
        .iter()
        .copied()
        .map(|analysis| {
            let result = json!({"analysis": format!("{analysis:?}")});
            InquiryAnalysisReceiptV1 {
                analysis,
                input_sha256: crate::owner_inquiry_wire::canonical_owner_inquiry_sha256(inquiry),
                output_sha256: canonical_sha256(&result),
                deterministic_rerun_match: true,
                all_inputs_copied: true,
                network_accessed: false,
                socket_accessed: false,
                private_source_accessed: false,
                candidate_merge_performed: false,
                live_runtime_mutation: false,
                result,
            }
        })
        .collect::<Vec<_>>();
    let pair_count = inquiry
        .strands
        .len()
        .saturating_mul(inquiry.strands.len().saturating_sub(1))
        / 2;
    OwnerInquiryReceiptV1 {
        schema: OWNER_INQUIRY_RECEIPT_SCHEMA_V1.to_string(),
        receipt_id: "receipt-v1".to_string(),
        inquiry_id: inquiry.inquiry_id.clone(),
        owner_being: inquiry.owner_being.clone(),
        manifest_sha256: crate::owner_inquiry_wire::canonical_owner_inquiry_sha256(inquiry),
        result_sha256: canonical_sha256(&analysis_receipts),
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
        completed_at_unix_ms: 15,
        perceptible_summary: "Every strand and pair remained separate.".to_string(),
    }
}

fn execution_identity() -> InquiryExecutionIdentityV2 {
    InquiryExecutionIdentityV2 {
        analyzer_identity: "minime-owner-inquiry".to_string(),
        analyzer_source_sha256: "b".repeat(64),
        analyzer_artifact_sha256: "c".repeat(64),
        deployment_identity: "minime-deployment".to_string(),
        sandbox_profile_sha256: "d".repeat(64),
    }
}

#[test]
fn v1_upgrade_requires_new_source_and_execution_commitments() {
    let v1 = inquiry_v1();
    assert!(v1.is_well_formed());
    let mut v2 = OwnerInquiryV2::from_v1(
        &v1,
        "d".repeat(64),
        "idempotency-v2".to_string(),
        analysis_plan(),
        Some(20),
    );
    assert!(v2.is_well_formed());
    assert_eq!(v2.strands[0].lineage, SemanticStrandLineageV2::captured());
    assert_eq!(v2.strands[0].content, v1.strands[0].content);

    v2.analysis_plan[0].parameters["independent_axis_sweep"] = Value::Bool(false);
    assert!(!v2.is_well_formed());
}

#[test]
fn observation_chain_rejects_reorder_and_tamper() {
    let first = InquiryObservationV2 {
        schema: INQUIRY_OBSERVATION_SCHEMA_V2.to_string(),
        observation_id: "observation-0".to_string(),
        inquiry_id: "inquiry-v2".to_string(),
        sequence: 0,
        previous_observation_sha256: None,
        phase: InquiryObservationPhaseV1::Baseline,
        actor: InquiryObservationActorV2::Runtime,
        observed_at_unix_ms: 10,
        self_control_receipt_ids: Vec::new(),
        control_revisions: Vec::new(),
        machine_evidence: json!({"healthy": true}),
        machine_evidence_sha256: String::new(),
        machine_status: InquiryMachineStatusV1::Established,
        felt_status: InquiryFeltStatusV1::Unreported,
        felt_report_ref: None,
        event_sha256: String::new(),
    }
    .seal();
    let second = InquiryObservationV2 {
        schema: INQUIRY_OBSERVATION_SCHEMA_V2.to_string(),
        observation_id: "observation-1".to_string(),
        inquiry_id: "inquiry-v2".to_string(),
        sequence: 1,
        previous_observation_sha256: Some(first.event_sha256.clone()),
        phase: InquiryObservationPhaseV1::DuringSampleOne,
        actor: InquiryObservationActorV2::Runtime,
        observed_at_unix_ms: 11,
        self_control_receipt_ids: Vec::new(),
        control_revisions: Vec::new(),
        machine_evidence: json!({"healthy": true}),
        machine_evidence_sha256: String::new(),
        machine_status: InquiryMachineStatusV1::Established,
        felt_status: InquiryFeltStatusV1::Unreported,
        felt_report_ref: None,
        event_sha256: String::new(),
    }
    .seal();
    assert!(observations_form_chain(
        &[first.clone(), second.clone()],
        "inquiry-v2"
    ));
    assert!(!observations_form_chain(&[second, first], "inquiry-v2"));
}

#[test]
fn reversible_canary_plan_rejects_shared_and_one_shot_values() {
    let valid = OwnerCanaryControlV2::new(
        SelfControlFamilyV2::SemanticContinuity,
        SelfControlValuesV2 {
            semantic_strand_retention_turns: Some(4),
            ..SelfControlValuesV2::default()
        },
        3,
    );
    assert!(valid.is_well_formed());

    let mismatched = OwnerCanaryControlV2::new(
        SelfControlFamilyV2::Conversation,
        SelfControlValuesV2 {
            semantic_strand_retention_turns: Some(4),
            ..SelfControlValuesV2::default()
        },
        3,
    );
    assert!(!mismatched.is_well_formed());

    let shared = OwnerCanaryControlV2::new(
        SelfControlFamilyV2::SharedCoupling,
        SelfControlValuesV2 {
            shared_sensory_admission: Some(0.2),
            ..SelfControlValuesV2::default()
        },
        0,
    );
    assert!(!shared.is_well_formed());

    let one_shot = OwnerCanaryControlV2::new(
        SelfControlFamilyV2::LocalTopology,
        SelfControlValuesV2 {
            mode_disperse: Some(0.5),
            ..SelfControlValuesV2::default()
        },
        0,
    );
    assert!(!one_shot.is_well_formed());
}

#[test]
fn coverage_proof_enumerates_every_unordered_pair() {
    let v2 = OwnerInquiryV2::from_v1(
        &inquiry_v1(),
        "d".repeat(64),
        "idempotency-v2".to_string(),
        analysis_plan(),
        Some(20),
    );
    let coverage = InquiryCoverageProofV2::for_strands(&v2.strands);
    assert_eq!(coverage.expected_strand_ids, vec!["left", "right"]);
    assert_eq!(coverage.expected_pair_keys, vec!["left::right"]);
    assert!(coverage.is_complete());
}

#[test]
fn semantic_content_hash_remains_exact_bytes() {
    assert_eq!(
        canonical_semantic_strand_content_sha256("λ"),
        format!("{:x}", Sha256::digest("λ".as_bytes()))
    );
}

#[test]
fn v1_receipt_upgrade_requires_exact_manifest_and_explicit_execution_identity() {
    let v1 = inquiry_v1();
    let v2 = OwnerInquiryV2::from_v1(
        &v1,
        "d".repeat(64),
        "idempotency-v2".to_string(),
        analysis_plan(),
        Some(20),
    );
    assert!(v2.preserves_v1(&v1));

    let upgraded =
        OwnerInquiryReceiptV2::from_v1_offline(&v1, &v2, &receipt_v1(&v1), execution_identity())
            .unwrap();
    assert!(upgraded.is_well_formed_for(&v2));
    assert_eq!(
        upgraded.analysis_receipts[0].covered_strand_ids,
        vec!["left", "right"]
    );
    assert_eq!(
        upgraded.analysis_receipts[2].covered_pair_keys,
        vec!["left::right"]
    );
    let mut mismatched_execution = execution_identity();
    mismatched_execution.analyzer_artifact_sha256 = "e".repeat(64);
    assert!(OwnerInquiryReceiptV2::from_v1_offline(
        &v1,
        &v2,
        &receipt_v1(&v1),
        mismatched_execution
    )
    .is_err());

    let mut drifted = v2.clone();
    drifted.question.push_str(" changed");
    assert!(!drifted.preserves_v1(&v1));
    assert!(OwnerInquiryReceiptV2::from_v1_offline(
        &v1,
        &drifted,
        &receipt_v1(&v1),
        execution_identity()
    )
    .is_err());

    let mut observed = receipt_v1(&v1);
    let machine_evidence = json!({"healthy": true});
    observed.observations.push(InquiryObservationV1 {
        schema: INQUIRY_OBSERVATION_SCHEMA_V1.to_string(),
        observation_id: "legacy-observation".to_string(),
        inquiry_id: v1.inquiry_id.clone(),
        phase: InquiryObservationPhaseV1::Baseline,
        observed_at_unix_ms: 14,
        self_control_receipt_ids: Vec::new(),
        machine_evidence_sha256: canonical_sha256(&machine_evidence),
        machine_evidence,
        machine_status: InquiryMachineStatusV1::Established,
        felt_status: InquiryFeltStatusV1::Unreported,
        felt_report_ref: None,
    });
    assert!(observed.is_well_formed_for(&v1));
    assert!(
        OwnerInquiryReceiptV2::from_v1_offline(&v1, &v2, &observed, execution_identity())
            .unwrap_err()
            .contains("actor-aware")
    );
}
