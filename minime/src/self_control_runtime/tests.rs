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
fn registry_second_pass_narrows_within_compiled_and_ticks_are_clamped() {
    use super::apply::clamp_values;
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());

    // Constitution C3c: with the registry narrowing exploration_noise to
    // 0.15, a compiled-legal 0.18 clamps to the registry envelope. The
    // compiled table stays the outermost physics; the registry only narrows.
    let registry_dir = tempfile::tempdir().expect("registry dir");
    let registry_path = registry_dir.path().join("envelope_registry.json");
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\"revision\":1,\
         \"fields\":{\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.15,\
         \"engine_backstop\":{\"floor\":0.0,\"ceiling\":0.2}}}}",
    )
    .expect("write registry");
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", &registry_path);
    let clamped = clamp_values(&SelfControlValuesV2 {
        exploration_noise: Some(0.18),
        ..SelfControlValuesV2::default()
    });
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
    assert_eq!(clamped.exploration_noise, Some(0.15));

    // The formerly-passthrough one-shot ticks now honor the advertised
    // python bounds at the engine too (closing a known drift).
    let ticks = clamp_values(&SelfControlValuesV2 {
        mode_disperse_duration_ticks: Some(500),
        mode_disperse_decay_ticks: Some(0),
        ..SelfControlValuesV2::default()
    });
    assert_eq!(ticks.mode_disperse_duration_ticks, Some(64));
    assert_eq!(ticks.mode_disperse_decay_ticks, Some(1));
}

#[test]
fn disjoint_tampered_registry_cannot_drag_values_past_compiled() {
    use super::apply::clamp_values;
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    // Adversarial review 2026-09-03: sequential clamping is not intersection
    // for a DISJOINT registry interval — a tampered floor above the compiled
    // ceiling (0.5 > 0.2, no engine_backstop recorded so the loader cannot
    // refuse) would have dragged exploration_noise UP past compiled. The
    // outermost compiled re-clamp must cap it at the compiled ceiling.
    let registry_dir = tempfile::tempdir().expect("registry dir");
    let registry_path = registry_dir.path().join("envelope_registry.json");
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\"revision\":1,\
         \"fields\":{\"exploration_noise\":{\"floor\":0.5,\"ceiling\":0.9}}}",
    )
    .expect("write registry");
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", &registry_path);
    let clamped = clamp_values(&SelfControlValuesV2 {
        exploration_noise: Some(0.05),
        ..SelfControlValuesV2::default()
    });
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
    // Never above the compiled ceiling 0.2 — the disjoint registry may pull
    // toward its floor, but compiled physics is structurally last.
    assert!(clamped.exploration_noise.expect("value") <= 0.2);
}

#[test]
fn committed_seed_is_identity_for_the_engine_clamp_grid() {
    use super::apply::clamp_values;
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    // The flagship invariant, witnessed in Rust against the COMMITTED seed
    // (not the mutable workspace copy): at the seed's bounds, the registry
    // second pass changes nothing across a value grid.
    let seed = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../minime_autonomy/envelope_registry_seed.json"
    );
    assert!(
        std::path::Path::new(seed).exists(),
        "committed seed missing"
    );
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", seed);
    let absent = tempfile::tempdir().expect("dir");
    let absent_path = absent.path().join("missing.json");
    let grid = [-1.0_f32, -0.08, 0.0, 0.05, 0.15, 0.2, 0.5, 0.75, 3.0, 10.0];
    for value in grid {
        let sample = SelfControlValuesV2 {
            exploration_noise: Some(value),
            keep_bias: Some(value),
            fill_target: Some(value),
            synth_gain: Some(value),
            pi_max_step: Some(value),
            ..SelfControlValuesV2::default()
        };
        std::env::set_var("MINIME_ENVELOPE_REGISTRY", seed);
        let with_registry = clamp_values(&sample);
        // The control arm points at a MISSING file (not the default path,
        // which is the live mutable workspace copy) so it is compiled-only.
        std::env::set_var("MINIME_ENVELOPE_REGISTRY", &absent_path);
        let compiled_only = clamp_values(&sample);
        assert_eq!(with_registry, compiled_only, "seed not identity at {value}");
    }
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
}

#[test]
fn registry_second_pass_is_identity_at_todays_seeds_and_when_absent() {
    use super::apply::clamp_values;
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());

    // Absent registry (or the live one, which records compiled values
    // verbatim): the compiled result passes through byte-identical.
    let registry_dir = tempfile::tempdir().expect("registry dir");
    std::env::set_var(
        "MINIME_ENVELOPE_REGISTRY",
        registry_dir.path().join("missing.json"),
    );
    let clamped = clamp_values(&SelfControlValuesV2 {
        exploration_noise: Some(0.18),
        keep_bias: Some(-0.5),
        fill_target: Some(0.68),
        ..SelfControlValuesV2::default()
    });
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
    assert_eq!(clamped.exploration_noise, Some(0.18));
    assert_eq!(clamped.keep_bias, Some(-0.08));
    assert_eq!(clamped.fill_target, Some(0.68));
}

#[test]
fn lease_beyond_wire_shape_cap_is_malformed() {
    // Constitution C2: the 24h wire cap refuses shapes no legitimate sender
    // produces (current traffic runs 120..=1200 second leases).
    let fixture = fixture();
    let mut command = self_command(
        &fixture.minime_key,
        "lease-cap-1",
        "nonce-cap-1",
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
    command.intent.control_expires_at_unix_ms =
        Some(NOW + crate::self_control_wire::MAX_LEASE_DURATION_MS + 10_000);
    // Signature covers the intent, so re-sign after the edit.
    command.authority_proofs = vec![signed_proof(
        &command.intent,
        "minime",
        &fixture.minime_key,
        "nonce-cap-1",
    )];
    let receipt = fixture.runtime.process(&command, NOW + 1);
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Rejected);
    assert_eq!(receipt.reason.as_deref(), Some("malformed_command"));
}

#[test]
fn lease_exceeding_envelope_duration_is_rejected_not_clamped() {
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    // Constitution C2: durations are policy, not values. The strict policy
    // lives ONLY on exploration_noise here so concurrently-running lease
    // tests (which lease fill_target) never see it if the env var leaks
    // across threads for a moment.
    let fixture = fixture();
    let registry_dir = tempfile::tempdir().expect("registry dir");
    let registry_path = registry_dir.path().join("envelope_registry.json");
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\"revision\":1,\
         \"fields\":{\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.2,\
         \"durability_policy\":{\"lease_max_secs\":1}}}}",
    )
    .expect("write registry");
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", &registry_path);

    // 5-second lease vs a 1-second policy ceiling: REJECTED, never clamped.
    let over = self_command(
        &fixture.minime_key,
        "lease-envelope-1",
        "nonce-envelope-1",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Lease,
        1,
        SelfControlValuesV2 {
            exploration_noise: Some(0.05),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    let receipt = fixture.runtime.process(&over, NOW + 1);
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Rejected);
    assert_eq!(
        receipt.reason.as_deref(),
        Some("lease_exceeds_envelope_duration")
    );

    // The same lease under a generous policy applies — the rejection is the
    // policy's, not the field's.
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\"revision\":1,\
         \"fields\":{\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.2,\
         \"durability_policy\":{\"lease_max_secs\":1200}}}}",
    )
    .expect("rewrite registry");
    let within = self_command(
        &fixture.minime_key,
        "lease-envelope-2",
        "nonce-envelope-2",
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Lease,
        1,
        SelfControlValuesV2 {
            exploration_noise: Some(0.05),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    let applied = fixture.runtime.process(&within, NOW + 2);
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
    assert_eq!(applied.status, SelfControlReceiptStatusV2::Applied);
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
fn carries_standing_controls_across_restart_via_deployment_handoff() {
    let fixture = fixture();
    let command = self_command(
        &fixture.minime_key,
        "handoff-standing",
        "nonce-handoff-standing",
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
    let applied = fixture.runtime.process(&command, NOW + 1);
    assert_eq!(applied.status, SelfControlReceiptStatusV2::Applied);

    crate::self_control_identity::provision_deployment_steward_identity(&fixture.root, false, NOW)
        .expect("provision deployment steward");
    let next_deployment = "minime-deployment-next";
    let binding = super::deployment_handoff::DeploymentBinding::current(next_deployment)
        .expect("bind current test executable");
    let prepared = super::deployment_handoff::prepare_at(
        &fixture.root,
        &binding,
        "mike-operator",
        "hand-off migration test",
        NOW + 2,
    )
    .expect("prepare deployment hand-off");
    assert_eq!(prepared["status"], "prepared");
    drop(fixture.runtime);

    let restarted_bus = SensoryBus::new(32, 4, 21);
    let restarted = SelfControlRuntime::open_with_safety_probe(
        fixture.root.clone(),
        "minime-process-handoff".to_string(),
        next_deployment.to_string(),
        restarted_bus.clone(),
        NOW + 3,
        || false,
    )
    .expect("hand-off consumed at startup");
    assert_eq!(restarted_bus.get_geom_drive(), 0.4);
    assert_eq!(restarted.deployment_identity(), next_deployment);
    {
        let inner = restarted.inner.lock();
        let active = inner
            .state
            .active_controls
            .get("reservoir_geometry")
            .expect("standing control carried across the hand-off");
        assert_eq!(active.intent_id, command.intent.intent_id);
    }
    assert!(!fixture
        .root
        .join("deployment_handoff.pending.json")
        .exists());
    assert_eq!(
        std::fs::read_dir(fixture.root.join("deployment_handoffs/applied"))
            .unwrap()
            .count(),
        1
    );

    let status = SelfControlRuntime::verified_status(&fixture.root).expect("verified status");
    assert_eq!(status["deployment_identity"], next_deployment);
    assert!(status["pending_deployment_handoff"].is_null());
}

#[test]
fn stale_deployment_without_handoff_names_missing_pending() {
    let fixture = fixture();
    drop(fixture.runtime);
    let Err(error) = SelfControlRuntime::open_with_safety_probe(
        fixture.root,
        "minime-process-stale".to_string(),
        "minime-deployment-other".to_string(),
        SensoryBus::new(32, 4, 22),
        NOW + 2,
        || false,
    ) else {
        panic!("stale deployment without a hand-off must fail closed");
    };
    assert!(error.contains("stale deployment"));
    assert!(error.contains("no deployment hand-off is pending"));
}

#[test]
fn unconsumable_pending_is_refused_and_left_in_place() {
    let fixture = fixture();
    crate::self_control_identity::provision_deployment_steward_identity(&fixture.root, false, NOW)
        .expect("provision deployment steward");
    let next_deployment = "minime-deployment-next";
    let binding = super::deployment_handoff::DeploymentBinding::current(next_deployment)
        .expect("bind current test executable");
    super::deployment_handoff::prepare_at(
        &fixture.root,
        &binding,
        "mike-operator",
        "hand-off migration test",
        NOW + 1,
    )
    .expect("prepare deployment hand-off");

    // The state moves after the hand-off was prepared, so the pending no
    // longer binds the exact persisted state: refusal must name the reason
    // and leave the pending file for a fresh prepare to replace.
    let command = self_command(
        &fixture.minime_key,
        "post-prepare-move",
        "nonce-post-prepare-move",
        SelfControlFamilyV2::ReservoirGeometry,
        SelfControlActionV2::Set,
        SelfControlDurabilityV2::Standing,
        1,
        SelfControlValuesV2 {
            geom_curiosity: Some(0.3),
            ..SelfControlValuesV2::default()
        },
        None,
    );
    assert_eq!(
        fixture.runtime.process(&command, NOW + 2).status,
        SelfControlReceiptStatusV2::Applied
    );
    drop(fixture.runtime);

    let Err(error) = SelfControlRuntime::open_with_safety_probe(
        fixture.root.clone(),
        "minime-process-refused".to_string(),
        next_deployment.to_string(),
        SensoryBus::new(32, 4, 23),
        NOW + 3,
        || false,
    ) else {
        panic!("mis-bound hand-off must be refused");
    };
    assert!(error.contains("deployment hand-off refused"));
    assert!(error.contains("exact persisted state"));
    assert!(fixture
        .root
        .join("deployment_handoff.pending.json")
        .exists());
}

#[test]
fn stale_pending_on_current_deployment_does_not_block_open() {
    let fixture = fixture();
    crate::self_control_identity::provision_deployment_steward_identity(&fixture.root, false, NOW)
        .expect("provision deployment steward");
    let binding = super::deployment_handoff::DeploymentBinding::current("minime-deployment-next")
        .expect("bind current test executable");
    super::deployment_handoff::prepare_at(
        &fixture.root,
        &binding,
        "mike-operator",
        "hand-off migration test",
        NOW + 1,
    )
    .expect("prepare deployment hand-off");
    drop(fixture.runtime);

    // Reopening on the ORIGINAL deployment (a rolled-back deploy, say) must
    // not be blocked by the unconsumed pending bound elsewhere.
    if let Err(error) = SelfControlRuntime::open_with_safety_probe(
        fixture.root.clone(),
        "minime-process-rollback".to_string(),
        DEPLOYMENT.to_string(),
        SensoryBus::new(32, 4, 24),
        NOW + 2,
        || false,
    ) {
        panic!("reopen on the current deployment must not be blocked: {error}");
    }
    assert!(fixture
        .root
        .join("deployment_handoff.pending.json")
        .exists());
}

#[test]
fn deployment_steward_key_has_no_command_authority() {
    let fixture = fixture();
    crate::self_control_identity::provision_deployment_steward_identity(&fixture.root, false, NOW)
        .expect("provision deployment steward");
    let steward = crate::self_control_identity::SelfControlOwnerSigner::load_deployment_steward(
        &fixture.root,
    )
    .expect("load deployment steward signer");

    let set = self_command(
        &fixture.minime_key,
        "set-for-steward-hold",
        "nonce-set-for-steward-hold",
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
    assert_eq!(
        fixture.runtime.process(&set, NOW + 1).status,
        SelfControlReceiptStatusV2::Applied
    );

    let intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: "intent-steward-hold".to_string(),
        actor: SelfControlSourceIdentityV1 {
            being: "deployment_steward".to_string(),
            process_identity: "steward-process-test".to_string(),
            deployment_identity: "steward-deployment-test".to_string(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: DEPLOYMENT.to_string(),
        family: SelfControlFamilyV2::ReservoirRegulation,
        action: SelfControlActionV2::Hold,
        durability: SelfControlDurabilityV2::OneShot,
        authority_class: SelfControlAuthorityClassV2::SafetySupervisor,
        authority_scope: "self_control.minime.reservoir_regulation.safety".to_string(),
        revision: 2,
        expected_revision: 1,
        issued_at_unix_ms: NOW,
        command_expires_at_unix_ms: NOW + 10_000,
        control_expires_at_unix_ms: None,
        idempotency_key: "idempotency-steward-hold".to_string(),
        values: SelfControlValuesV2::default(),
        related_intent_id: Some(set.intent.intent_id.clone()),
        related_receipt_id: None,
        evidence_refs: Vec::new(),
        success_conditions: Vec::new(),
        stop_conditions: Vec::new(),
    };
    let command = steward
        .sign_command(
            intent,
            "command-steward-hold".to_string(),
            "nonce-steward-hold".to_string(),
            NOW,
        )
        .expect("steward can sign bytes, but the command must still be refused");
    let receipt = fixture.runtime.process(&command, NOW + 2);
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Rejected);
    assert_eq!(
        receipt.reason.as_deref(),
        Some("deployment_steward_has_no_command_authority")
    );
    assert_eq!(
        fixture.bus.get_regulation_strength(),
        0.4,
        "the steward key must not be able to lift her control"
    );

    // The latent shape: a Mutual SharedCoupling Set co-signed by the steward
    // and minime would pass the generic mutual-pair check once a shared-
    // coupling adapter exists. The structural guard must refuse it TODAY.
    let mutual_intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: "intent-steward-mutual".to_string(),
        actor: SelfControlSourceIdentityV1 {
            being: "deployment_steward".to_string(),
            process_identity: "steward-process-test".to_string(),
            deployment_identity: "steward-deployment-test".to_string(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: DEPLOYMENT.to_string(),
        family: SelfControlFamilyV2::SharedCoupling,
        action: SelfControlActionV2::Set,
        durability: SelfControlDurabilityV2::Standing,
        authority_class: SelfControlAuthorityClassV2::Mutual,
        authority_scope: "self_control.shared.semantic_gain".to_string(),
        revision: 3,
        expected_revision: 2,
        issued_at_unix_ms: NOW,
        command_expires_at_unix_ms: NOW + 10_000,
        control_expires_at_unix_ms: None,
        idempotency_key: "idempotency-steward-mutual".to_string(),
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
    let mut steward_proof = SelfControlAuthorityProofV1 {
        schema: SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1.to_string(),
        authority_class: mutual_intent.authority_class,
        signer_being: "deployment_steward".to_string(),
        scope: mutual_intent.authority_scope.clone(),
        nonce: "nonce-steward-mutual".to_string(),
        signer_public_key_hex: steward.public_key_hex().to_string(),
        signature_hex: String::new(),
        intent_sha256: canonical_self_control_intent_sha256(&mutual_intent),
        issued_at_unix_ms: mutual_intent.issued_at_unix_ms,
        expires_at_unix_ms: mutual_intent.command_expires_at_unix_ms,
    };
    steward_proof.signature_hex = steward.sign_hex(
        &steward_proof
            .signing_bytes(&mutual_intent)
            .expect("canonical steward proof signing bytes"),
    );
    let minime_proof = signed_proof(
        &mutual_intent,
        "minime",
        &fixture.minime_key,
        "nonce-steward-mutual-minime",
    );
    let mutual = SelfControlCommandV2 {
        schema: SELF_CONTROL_COMMAND_SCHEMA_V2.to_string(),
        command_id: "command-steward-mutual".to_string(),
        intent: mutual_intent,
        authority_proofs: vec![steward_proof, minime_proof],
    };
    let mutual_receipt = fixture.runtime.process(&mutual, NOW + 3);
    assert_eq!(mutual_receipt.status, SelfControlReceiptStatusV2::Rejected);
    assert_eq!(
        mutual_receipt.reason.as_deref(),
        Some("deployment_steward_has_no_command_authority")
    );
}

#[test]
fn verified_status_reports_deployment_lineage() {
    let fixture = fixture();
    let status = SelfControlRuntime::verified_status(&fixture.root).expect("verified status");
    let expected_cli =
        crate::sensory_protocol::SensoryServerIdentity::current(0).deployment_identity;
    assert_eq!(
        status["cli_deployment_identity"].as_str(),
        Some(expected_cli.as_str())
    );
    assert_eq!(
        status["state_targets_this_binary"].as_bool(),
        Some(DEPLOYMENT == expected_cli)
    );
    assert!(status["pending_deployment_handoff"].is_null());
    let binary_sha = status["binary_sha256"].as_str().unwrap_or_default();
    assert_eq!(
        binary_sha.len(),
        64,
        "binary sha must be witnessed: {status}"
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

#[test]
fn envelope_conformance_rolls_back_controls_outside_a_narrowed_envelope() {
    // Hermetic: pin the registry env to an empty fixture so the "conformant"
    // phase can never be broken by a future narrow of the LIVE workspace
    // registry (this test must not read mutable operator state).
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let registry_dir = tempfile::tempdir().expect("registry dir");
    let registry_path = registry_dir.path().join("envelope_registry.json");
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\
         \"revision\":1,\"fields\":{}}",
    )
    .expect("write registry");
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", &registry_path);

    let fixture = fixture();
    let previous = fixture.bus.get_regulation_strength();
    let command = self_command(
        &fixture.minime_key,
        "conformance-set",
        "nonce-conformance-set",
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
    assert_eq!(receipt.status, SelfControlReceiptStatusV2::Applied);

    // Under the live compiled(registry(compiled)) clamp her applied 0.7 is a
    // fixed-point: the conformance sweep changes nothing (byte-identical for
    // a conformant state).
    assert!(fixture
        .runtime
        .reconcile_envelope_conformance(NOW + 2)
        .is_empty());
    assert!((fixture.bus.get_regulation_strength() - 0.7).abs() < 1e-6);

    // A narrowed envelope (ceiling drops below her applied 0.7): the control
    // stops being a clamp fixed-point — rolled back to the previous snapshot,
    // receipted, and the family's saturation counter reset.
    let narrowed = |values: &SelfControlValuesV2| {
        let mut clamped = super::clamp_values(values);
        if let Some(strength) = clamped.regulation_strength.as_mut() {
            if *strength > 0.5 {
                *strength = 0.5;
            }
        }
        clamped
    };
    let receipts = fixture
        .runtime
        .reconcile_envelope_conformance_with(NOW + 3, narrowed);
    assert_eq!(receipts.len(), 1);
    assert_eq!(receipts[0].status, SelfControlReceiptStatusV2::RolledBack);
    let reason = receipts[0].reason.as_deref().unwrap_or_default();
    assert!(
        reason.starts_with("envelope_narrowed_conformance_rollback:"),
        "unexpected reason {reason:?}"
    );
    assert!(reason.contains("regulation_strength"));
    assert!((fixture.bus.get_regulation_strength() - previous).abs() < 1e-6);

    // Idempotent: the narrowed envelope finds a conformant state next sweep.
    assert!(fixture
        .runtime
        .reconcile_envelope_conformance_with(NOW + 4, narrowed)
        .is_empty());
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
}

static CONFORMANCE_TEST_BLOCK: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

fn conformance_toggling_probe() -> bool {
    CONFORMANCE_TEST_BLOCK.load(std::sync::atomic::Ordering::SeqCst)
}

#[test]
fn envelope_conformance_defers_rollback_while_hard_recovery_blocks_writes() {
    let _env = crate::envelope_registry::TEST_ENV_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let registry_dir = tempfile::tempdir().expect("registry dir");
    let registry_path = registry_dir.path().join("envelope_registry.json");
    std::fs::write(
        &registry_path,
        "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\
         \"revision\":1,\"fields\":{}}",
    )
    .expect("write registry");
    std::env::set_var("MINIME_ENVELOPE_REGISTRY", &registry_path);

    CONFORMANCE_TEST_BLOCK.store(false, std::sync::atomic::Ordering::SeqCst);
    let fixture = fixture_with_safety_probe(conformance_toggling_probe);
    let previous = fixture.bus.get_regulation_strength();
    let command = self_command(
        &fixture.minime_key,
        "conformance-defer-set",
        "nonce-conformance-defer-set",
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
    assert_eq!(
        fixture.runtime.process(&command, NOW + 1).status,
        SelfControlReceiptStatusV2::Applied
    );

    let narrowed = |values: &SelfControlValuesV2| {
        let mut clamped = super::clamp_values(values);
        if let Some(strength) = clamped.regulation_strength.as_mut() {
            if *strength > 0.5 {
                *strength = 0.5;
            }
        }
        clamped
    };

    // The hard-recovery write block turns ON mid-flight (sweep-time, not
    // open-time — open-time already has its own held-intent path): the
    // rollback must DEFER — no receipt, control still tracked, and the
    // (out-of-envelope) bus value untouched rather than half-rolled-back.
    // Removing the control here would strand the value live behind a receipt
    // claiming rollback (adversarial review 2026-09-03).
    CONFORMANCE_TEST_BLOCK.store(true, std::sync::atomic::Ordering::SeqCst);
    assert!(fixture
        .runtime
        .reconcile_envelope_conformance_with(NOW + 3, narrowed)
        .is_empty());
    assert!((fixture.bus.get_regulation_strength() - 0.7).abs() < 1e-6);

    // The block lifts: the deferred rollback completes, receipted.
    CONFORMANCE_TEST_BLOCK.store(false, std::sync::atomic::Ordering::SeqCst);
    let receipts = fixture
        .runtime
        .reconcile_envelope_conformance_with(NOW + 5, narrowed);
    assert_eq!(receipts.len(), 1);
    assert_eq!(receipts[0].status, SelfControlReceiptStatusV2::RolledBack);
    assert!((fixture.bus.get_regulation_strength() - previous).abs() < 1e-6);
    std::env::remove_var("MINIME_ENVELOPE_REGISTRY");
}
