use std::{collections::BTreeMap, sync::Arc};

use ed25519_dalek::{Signer as _, SigningKey};
use tempfile::TempDir;

use super::{SelfControlRuntime, SelfControlTrustStoreV1};
use crate::{
    self_control_wire::{
        canonical_self_control_intent_sha256, SelfControlActionV2, SelfControlAuthorityClassV2,
        SelfControlAuthorityProofV1, SelfControlCommandV2, SelfControlDurabilityV2,
        SelfControlFamilyV2, SelfControlIntentV2, SelfControlReceiptStatusV2,
        SelfControlSourceIdentityV1, SelfControlValuesV2, SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1,
        SELF_CONTROL_COMMAND_SCHEMA_V2, SELF_CONTROL_INTENT_SCHEMA_V2,
    },
    sensory_bus::SensoryBus,
};

const DEPLOYMENT: &str = "minime-deployment-test";
const PROCESS: &str = "minime-process-test";
const NOW: u64 = 1_000_000;

struct Fixture {
    _temp: TempDir,
    root: std::path::PathBuf,
    bus: Arc<SensoryBus>,
    runtime: SelfControlRuntime,
    minime_key: SigningKey,
    safety_key: SigningKey,
    astrid_key: SigningKey,
}

fn fixture() -> Fixture {
    fixture_with_safety_probe(|| false)
}

fn fixture_with_safety_probe(probe: fn() -> bool) -> Fixture {
    let temp = tempfile::tempdir().expect("temporary self-control root");
    let root = temp.path().join("self-control");
    let bus = SensoryBus::new(32, 4, 7);
    let minime_key = SigningKey::from_bytes(&[7_u8; 32]);
    let safety_key = SigningKey::from_bytes(&[8_u8; 32]);
    let astrid_key = SigningKey::from_bytes(&[9_u8; 32]);
    let trust = SelfControlTrustStoreV1 {
        schema: "minime.self_control.trust_store.v1".to_string(),
        target_being: "minime".to_string(),
        pinned_public_keys: BTreeMap::from([
            (
                "minime".to_string(),
                hex::encode(minime_key.verifying_key().to_bytes()),
            ),
            (
                "safety_supervisor".to_string(),
                hex::encode(safety_key.verifying_key().to_bytes()),
            ),
            (
                "astrid".to_string(),
                hex::encode(astrid_key.verifying_key().to_bytes()),
            ),
        ]),
    };
    SelfControlRuntime::provision_trust_store(&root, &trust).expect("provision trust");
    let runtime = SelfControlRuntime::open_with_safety_probe(
        root.clone(),
        PROCESS.to_string(),
        DEPLOYMENT.to_string(),
        bus.clone(),
        NOW,
        probe,
    )
    .expect("open runtime");
    Fixture {
        _temp: temp,
        root,
        bus,
        runtime,
        minime_key,
        safety_key,
        astrid_key,
    }
}

#[test]
fn hard_recovery_reset_can_hold_but_cannot_author_a_target() {
    let fixture = fixture_with_safety_probe(|| true);
    let previous = fixture.bus.get_regulation_strength();
    let command = self_command(
        &fixture.minime_key,
        "hard-reset-hold",
        "nonce-hard-reset-hold",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Lease,
        1,
        SelfControlValuesV2 {
            regulation_strength: Some(0.7),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    let receipt = fixture.runtime.process(&command, NOW + 1);
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Rejected);
    assert_eq!(
        receipt.reason.as_deref(),
        Some("safety_hold:hard_recovery_reset")
    );
    assert_eq!(fixture.bus.get_regulation_strength(), previous);
}

fn signed_proof(
    intent: &SelfControlIntentV2,
    signer_being: &str,
    key: &SigningKey,
    nonce: &str,
) -> SelfControlAuthorityProofV1 {
    let mut proof = SelfControlAuthorityProofV1 {
        schema: SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1.to_string(),
        authority_class: intent.authority_class,
        signer_being: signer_being.to_string(),
        scope: intent.authority_scope.clone(),
        nonce: nonce.to_string(),
        signer_public_key_hex: hex::encode(key.verifying_key().to_bytes()),
        signature_hex: String::new(),
        intent_sha256: canonical_self_control_intent_sha256(intent),
        issued_at_unix_ms: intent.issued_at_unix_ms,
        expires_at_unix_ms: intent.command_expires_at_unix_ms,
    };
    proof.signature_hex = hex::encode(
        key.sign(
            &proof
                .signing_bytes(intent)
                .expect("canonical proof signing bytes"),
        )
        .to_bytes(),
    );
    proof
}

#[allow(clippy::too_many_arguments)]
fn self_command(
    key: &SigningKey,
    command_id: &str,
    nonce: &str,
    family: SelfControlFamilyV2,
    action: SelfControlActionV2,
    durability: SelfControlDurabilityV2,
    revision: u64,
    values: SelfControlValuesV2,
    related_intent_id: Option<String>,
) -> SelfControlCommandV2 {
    let intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: format!("intent-{command_id}"),
        actor: SelfControlSourceIdentityV1 {
            being: "minime".to_string(),
            process_identity: "minime-autonomy-test".to_string(),
            deployment_identity: DEPLOYMENT.to_string(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: DEPLOYMENT.to_string(),
        family,
        action,
        durability,
        authority_class: SelfControlAuthorityClassV2::SelfOwned,
        authority_scope: format!("self_control.minime.{}", family_name(family)),
        revision,
        expected_revision: revision.saturating_sub(1),
        issued_at_unix_ms: NOW,
        command_expires_at_unix_ms: NOW + 10_000,
        control_expires_at_unix_ms: (durability == SelfControlDurabilityV2::Lease)
            .then_some(NOW + 5_000),
        idempotency_key: format!("idempotency-{command_id}"),
        values,
        related_intent_id,
        related_receipt_id: None,
        evidence_refs: vec!["felt-contract:test".to_string()],
        success_conditions: vec!["machine_receipt_applied".to_string()],
        stop_conditions: vec!["being_hold".to_string()],
    };
    let proof = signed_proof(&intent, "minime", key, nonce);
    SelfControlCommandV2 {
        schema: SELF_CONTROL_COMMAND_SCHEMA_V2.to_string(),
        command_id: command_id.to_string(),
        intent,
        authority_proofs: vec![proof],
    }
}

fn safety_command(
    key: &SigningKey,
    command_id: &str,
    action: SelfControlActionV2,
    revision: u64,
    related_intent_id: Option<String>,
    related_receipt_id: Option<String>,
) -> SelfControlCommandV2 {
    let intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: format!("intent-{command_id}"),
        actor: SelfControlSourceIdentityV1 {
            being: "safety_supervisor".to_string(),
            process_identity: "safety-process-test".to_string(),
            deployment_identity: "safety-deployment-test".to_string(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: DEPLOYMENT.to_string(),
        family: SelfControlFamilyV2::ReservoirRegulation,
        action,
        durability: SelfControlDurabilityV2::OneShot,
        authority_class: SelfControlAuthorityClassV2::SafetySupervisor,
        authority_scope: "self_control.minime.reservoir_regulation.safety".to_string(),
        revision,
        expected_revision: revision.saturating_sub(1),
        issued_at_unix_ms: NOW,
        command_expires_at_unix_ms: NOW + 10_000,
        control_expires_at_unix_ms: None,
        idempotency_key: format!("idempotency-{command_id}"),
        values: SelfControlValuesV2::default(),
        related_intent_id,
        related_receipt_id,
        evidence_refs: vec!["safety:machine-red".to_string()],
        success_conditions: vec!["prior_state_restored".to_string()],
        stop_conditions: Vec::new(),
    };
    let proof = signed_proof(&intent, "safety_supervisor", key, command_id);
    SelfControlCommandV2 {
        schema: SELF_CONTROL_COMMAND_SCHEMA_V2.to_string(),
        command_id: command_id.to_string(),
        intent,
        authority_proofs: vec![proof],
    }
}

const fn family_name(family: SelfControlFamilyV2) -> &'static str {
    match family {
        SelfControlFamilyV2::Conversation => "conversation",
        SelfControlFamilyV2::SemanticContinuity => "semantic_continuity",
        SelfControlFamilyV2::SemanticEmission => "semantic_emission",
        SelfControlFamilyV2::Memory => "memory",
        SelfControlFamilyV2::SensoryIntake => "sensory_intake",
        SelfControlFamilyV2::ReservoirRegulation => "reservoir_regulation",
        SelfControlFamilyV2::ReservoirGeometry => "reservoir_geometry",
        SelfControlFamilyV2::PiController => "pi_controller",
        SelfControlFamilyV2::LocalTopology => "local_topology",
        SelfControlFamilyV2::SharedCoupling => "shared_coupling",
    }
}

#[test]
fn lease_applies_idempotently_and_expiry_restores_automatic_state() {
    let fixture = fixture();
    assert!(fixture.runtime.is_ready());
    assert!(fixture.bus.get_fill_target().is_nan());
    let command = self_command(
        &fixture.minime_key,
        "lease-fill-1",
        "nonce-fill-1",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Lease,
        1,
        SelfControlValuesV2 {
            fill_target: Some(0.68),
            ..SelfControlValuesV2::default()
        },
        None,
    );

    let applied = fixture.runtime.process(&command, NOW + 1);
    assert_eq!(applied.status, SelfControlReceiptStatusV2::Applied);
    assert!(applied
        .previous_automatic_fields
        .contains(&"fill_target".to_string()));
    assert_eq!(fixture.bus.get_fill_target(), 0.68);
    let duplicate = fixture.runtime.process(&command, NOW + 2);
    assert_eq!(duplicate.status, SelfControlReceiptStatusV2::Duplicate);

    let expiry = fixture.runtime.sweep_expired(NOW + 5_000);
    assert_eq!(expiry.len(), 1);
    assert_eq!(expiry[0].status, SelfControlReceiptStatusV2::Expired);
    assert!(fixture.bus.get_fill_target().is_nan());

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        assert_eq!(
            std::fs::metadata(fixture.root.join("state.json"))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
        assert_eq!(
            std::fs::metadata(&fixture.root)
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o700
        );
    }
}

#[test]
fn rejects_revision_conflict_bad_signature_stale_target_and_nonce_replay() {
    let fixture = fixture();
    let mut wrong_revision = self_command(
        &fixture.minime_key,
        "wrong-revision",
        "nonce-wrong-revision",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        2,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.2),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    wrong_revision.intent.expected_revision = 0;
    wrong_revision.authority_proofs = vec![signed_proof(
        &wrong_revision.intent,
        "minime",
        &fixture.minime_key,
        "nonce-wrong-revision",
    )];
    assert_eq!(
        fixture.runtime.process(&wrong_revision, NOW + 1).status,
        SelfControlReceiptStatusV2::RevisionConflict
    );

    let mut bad_signature = self_command(
        &fixture.minime_key,
        "bad-signature",
        "nonce-bad-signature",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.2),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    bad_signature.authority_proofs[0].signature_hex = "00".repeat(64);
    assert_eq!(
        fixture.runtime.process(&bad_signature, NOW + 1).status,
        SelfControlReceiptStatusV2::Rejected
    );

    let mut stale = self_command(
        &fixture.minime_key,
        "stale-target",
        "nonce-stale",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.2),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    stale.intent.target_deployment_identity = "stale-deployment".to_string();
    stale.authority_proofs = vec![signed_proof(
        &stale.intent,
        "minime",
        &fixture.minime_key,
        "nonce-stale",
    )];
    assert_eq!(
        fixture.runtime.process(&stale, NOW + 1).reason.as_deref(),
        Some("stale_target_deployment")
    );

    let first = self_command(
        &fixture.minime_key,
        "nonce-first",
        "nonce-reused",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.15),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    assert_eq!(
        fixture.runtime.process(&first, NOW + 1).status,
        SelfControlReceiptStatusV2::Applied
    );
    let replay = self_command(
        &fixture.minime_key,
        "nonce-replay",
        "nonce-reused",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        2,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.16),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    assert_eq!(
        fixture.runtime.process(&replay, NOW + 2).reason.as_deref(),
        Some("authority_nonce_replay")
    );
}

#[test]
fn standing_revision_accumulates_fields_and_withdraw_restores_full_baseline() {
    let fixture = fixture();
    let first = self_command(
        &fixture.minime_key,
        "standing-fill",
        "nonce-standing-fill",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            fill_target: Some(0.60),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    fixture.runtime.process(&first, NOW + 1);
    let original_regulation = fixture.bus.get_regulation_strength();
    let second = self_command(
        &fixture.minime_key,
        "standing-regulation",
        "nonce-standing-regulation",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        2,
        SelfControlValuesV2 {
            regulation_strength: Some(0.45),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    fixture.runtime.process(&second, NOW + 2);
    assert_eq!(fixture.bus.get_fill_target(), 0.60);
    assert_eq!(fixture.bus.get_regulation_strength(), 0.45);

    let withdraw = self_command(
        &fixture.minime_key,
        "withdraw-regulation",
        "nonce-withdraw-regulation",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Withdraw,
        SelfControlDurabilityV2::OneShot,
        3,
        SelfControlValuesV2::default(),
        Some(second.intent.intent_id.clone()),
    );
    assert_eq!(
        fixture.runtime.process(&withdraw, NOW + 3).status,
        SelfControlReceiptStatusV2::Withdrawn
    );
    assert!(fixture.bus.get_fill_target().is_nan());
    assert_eq!(fixture.bus.get_regulation_strength(), original_regulation);
}

#[test]
fn safety_supervisor_can_hold_or_revert_but_cannot_author_a_target() {
    let fixture = fixture();
    let set = self_command(
        &fixture.minime_key,
        "set-for-hold",
        "nonce-set-for-hold",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            regulation_strength: Some(0.4),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    let applied = fixture.runtime.process(&set, NOW + 1);
    let hold = safety_command(
        &fixture.safety_key,
        "safety-hold",
        SelfControlActionV2::Hold,
        2,
        Some(set.intent.intent_id.clone()),
        None,
    );
    assert_eq!(
        fixture.runtime.process(&hold, NOW + 2).status,
        SelfControlReceiptStatusV2::SafetyHeld
    );

    let set_again = self_command(
        &fixture.minime_key,
        "set-for-revert",
        "nonce-set-for-revert",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        3,
        SelfControlValuesV2 {
            regulation_strength: Some(0.5),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    let applied_again = fixture.runtime.process(&set_again, NOW + 3);
    let revert = safety_command(
        &fixture.safety_key,
        "safety-revert",
        SelfControlActionV2::Revert,
        4,
        None,
        Some(applied_again.receipt_id),
    );
    assert_eq!(
        fixture.runtime.process(&revert, NOW + 4).status,
        SelfControlReceiptStatusV2::SafetyHeld
    );

    let mut supervisor_set = safety_command(
        &fixture.safety_key,
        "supervisor-set",
        SelfControlActionV2::Hold,
        5,
        Some(set_again.intent.intent_id),
        None,
    );
    supervisor_set.intent.action = SelfControlActionV2::Set;
    supervisor_set.intent.values.regulation_strength = Some(0.9);
    supervisor_set.authority_proofs = vec![signed_proof(
        &supervisor_set.intent,
        "safety_supervisor",
        &fixture.safety_key,
        "supervisor-set",
    )];
    assert_eq!(
        fixture.runtime.process(&supervisor_set, NOW + 5).status,
        SelfControlReceiptStatusV2::Rejected
    );
    assert!(applied.is_well_formed());
}

#[test]
fn repeated_clamp_saturation_rolls_back_instead_of_becoming_a_target() {
    let fixture = fixture();
    for revision in 1..=3 {
        let command = self_command(
            &fixture.minime_key,
            &format!("clamp-{revision}"),
            &format!("nonce-clamp-{revision}"),
            SelfControlFamilyV2::ReservoirRegulation,
            SelfControlActionV2::Set,
            SelfControlDurabilityV2::Standing,
            revision,
            SelfControlValuesV2 {
                fill_target: Some(9.0),
                ..SelfControlValuesV2::default()
            },
            None,
        );
        let receipt = fixture.runtime.process(&command, NOW + revision);
        if revision < 3 {
            assert_eq!(receipt.status, SelfControlReceiptStatusV2::Applied);
            assert_eq!(fixture.bus.get_fill_target(), 0.75);
            let inner = fixture.runtime.inner.lock();
            let active = inner
                .state
                .active_controls
                .get("reservoir_regulation")
                .expect("standing clamp remains active");
            assert!(
                active
                    .previous_automatic_fields
                    .contains(&"fill_target".to_string()),
                "rollback baseline must retain automatic fill"
            );
        } else {
            assert_eq!(receipt.status, SelfControlReceiptStatusV2::RolledBack);
            assert_eq!(receipt.reason.as_deref(), Some("repeated_clamp_saturation"));
        }
    }
    assert!(
        fixture.bus.get_fill_target().is_nan(),
        "third saturation must restore automatic fill, got {}",
        fixture.bus.get_fill_target()
    );
}

#[test]
fn standing_control_recovers_after_restart_and_corrupt_state_fails_closed() {
    let fixture = fixture();
    let command = self_command(
        &fixture.minime_key,
        "restart-standing",
        "nonce-restart-standing",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            geom_drive: Some(0.4),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    fixture.runtime.process(&command, NOW + 1);
    let restarted_bus = SensoryBus::new(32, 4, 8);
    let restarted = SelfControlRuntime::open_with_safety_probe(
        fixture.root.clone(),
        "minime-process-restarted".to_string(),
        DEPLOYMENT.to_string(),
        restarted_bus.clone(),
        NOW + 2,
        || false,
    )
    .expect("hash-verified restart");
    assert_eq!(restarted_bus.get_geom_drive(), 0.4);
    drop(restarted);

    let state_path = fixture.root.join("state.json");
    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&state_path).unwrap()).unwrap();
    state["state_sha256"] = serde_json::Value::String("0".repeat(64));
    std::fs::write(&state_path, serde_json::to_vec_pretty(&state).unwrap()).unwrap();
    let corrupt_result = SelfControlRuntime::open_with_safety_probe(
        fixture.root,
        "minime-process-corrupt".to_string(),
        DEPLOYMENT.to_string(),
        SensoryBus::new(32, 4, 9),
        NOW + 3,
        || false,
    );
    let Err(error) = corrupt_result else {
        panic!("corrupt state must fail closed");
    };
    assert!(error.contains("integrity mismatch"));
}

#[test]
fn one_shot_checkpoint_request_is_consumed_without_becoming_a_preference() {
    let fixture = fixture();
    let command = self_command(
        &fixture.minime_key,
        "checkpoint-now",
        "nonce-checkpoint-now",
        SelfControlFamilyV2::Memory,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::OneShot,
        1,
        SelfControlValuesV2 {
            checkpoint_now: Some(true),
            ..SelfControlValuesV2::default()
        },
        None,
    );

    let receipt = fixture.runtime.process(&command, NOW + 1);
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Applied);
    assert!(fixture.bus.take_checkpoint_request());
    assert!(!fixture.bus.take_checkpoint_request());

    let status = SelfControlRuntime::verified_status(&fixture.root).expect("verified status");
    assert!(
        status["preferences"].get("checkpoint_now").is_none(),
        "one-shot requests must not become standing preferences: {status}"
    );
    assert!(
        status["active_controls"].get("memory").is_none(),
        "one-shot requests must not survive as active controls: {status}"
    );
}

#[test]
fn companion_mix_is_owner_controlled_and_shared_coupling_remains_proof_gated() {
    let fixture = fixture();
    let companion = self_command(
        &fixture.minime_key,
        "companion-nonzero",
        "nonce-companion-nonzero",
        SelfControlFamilyV2::SensoryIntake,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            semantic_companion_mix: Some(0.2),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    assert_eq!(
        fixture.runtime.process(&companion, NOW + 1).status,
        SelfControlReceiptStatusV2::Applied
    );
    assert_eq!(fixture.bus.get_semantic_companion_mix(), 0.2);

    let intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: "intent-shared".to_string(),
        actor: SelfControlSourceIdentityV1 {
            being: "astrid".to_string(),
            process_identity: "astrid-process".to_string(),
            deployment_identity: "astrid-deployment".to_string(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: DEPLOYMENT.to_string(),
        family: SelfControlFamilyV2::SharedCoupling,
        action: SelfControlActionV2::Set,
        durability: SelfControlDurabilityV2::Standing,
        authority_class: SelfControlAuthorityClassV2::Mutual,
        authority_scope: "self_control.shared.semantic_gain".to_string(),
        revision: 1,
        expected_revision: 0,
        issued_at_unix_ms: NOW,
        command_expires_at_unix_ms: NOW + 10_000,
        control_expires_at_unix_ms: None,
        idempotency_key: "shared-idempotency".to_string(),
        values: SelfControlValuesV2 {
            cross_being_semantic_gain: Some(0.4),
            ..SelfControlValuesV2::default()
        },
        related_intent_id: None,
        related_receipt_id: None,
        evidence_refs: Vec::new(),
        success_conditions: Vec::new(),
        stop_conditions: Vec::new(),
    };
    let shared = SelfControlCommandV2 {
        schema: SELF_CONTROL_COMMAND_SCHEMA_V2.to_string(),
        command_id: "command-shared".to_string(),
        authority_proofs: vec![
            signed_proof(
                &intent,
                "astrid",
                &fixture.astrid_key,
                "nonce-shared-astrid",
            ),
            signed_proof(
                &intent,
                "minime",
                &fixture.minime_key,
                "nonce-shared-minime",
            ),
        ],
        intent,
    };
    assert_eq!(
        fixture.runtime.process(&shared, NOW + 2).reason.as_deref(),
        Some("shared_coupling_adapter_not_implemented")
    );
}
