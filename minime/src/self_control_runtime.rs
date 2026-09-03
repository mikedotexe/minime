use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    sync::Arc,
};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use crate::{
    self_control_wire::{
        canonical_json_value_sha256, canonical_self_control_command_sha256, SelfControlActionV2,
        SelfControlAuthorityClassV2, SelfControlCommandV2, SelfControlDurabilityV2,
        SelfControlFamilyV2, SelfControlReceiptStatusV2, SelfControlReceiptV2, SelfControlValuesV2,
        SELF_CONTROL_RECEIPT_SCHEMA_V2,
    },
    sensory_bus::SensoryBus,
};

mod apply;
mod deployment_handoff;
pub(crate) mod storage;

use apply::{
    apply_values, clamp_values, replace_requested_preferences, snapshot_values, unsupported_fields,
    ControlSnapshot,
};

const STATE_SCHEMA: &str = "minime.self_control.runtime_state.v2";
const STATE_ENVELOPE_SCHEMA: &str = "minime.self_control.runtime_state_envelope.v1";
const TRUST_SCHEMA: &str = "minime.self_control.trust_store.v1";
const TARGET_BEING: &str = "minime";
const FUTURE_ISSUE_SKEW_MS: u64 = 30_000;
const MAX_RECEIPTS: usize = 4_096;
const MAX_IDEMPOTENCY: usize = 4_096;
const MAX_NONCES: usize = 8_192;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SelfControlTrustStoreV1 {
    pub schema: String,
    pub target_being: String,
    #[serde(default)]
    pub pinned_public_keys: BTreeMap<String, String>,
}

impl Default for SelfControlTrustStoreV1 {
    fn default() -> Self {
        Self {
            schema: TRUST_SCHEMA.to_string(),
            target_being: TARGET_BEING.to_string(),
            pinned_public_keys: BTreeMap::new(),
        }
    }
}

impl SelfControlTrustStoreV1 {
    fn is_well_formed(&self) -> bool {
        self.schema == TRUST_SCHEMA
            && self.target_being == TARGET_BEING
            && self
                .pinned_public_keys
                .iter()
                .all(|(being, key)| !being.trim().is_empty() && valid_public_key(key))
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticControlSnapshotV2 {
    pub companion_mix: f32,
    pub intake_gain: f32,
    pub receptivity: f32,
}

impl SemanticControlSnapshotV2 {
    #[must_use]
    pub fn effective_base_gain(&self) -> f32 {
        (self.intake_gain * self.receptivity).clamp(0.0, 2.0)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ActiveControlV2 {
    family: SelfControlFamilyV2,
    intent_id: String,
    command_id: String,
    idempotency_key: String,
    receipt_id: String,
    revision: u64,
    durability: SelfControlDurabilityV2,
    control_expires_at_unix_ms: Option<u64>,
    requested_fields: Vec<String>,
    applied_values: SelfControlValuesV2,
    previous_values: SelfControlValuesV2,
    previous_automatic_fields: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct IdempotencyRecordV2 {
    command_sha256: String,
    observed_at_unix_ms: u64,
    receipt: SelfControlReceiptV2,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct RuntimeStateV2 {
    schema: String,
    target_being: String,
    deployment_identity: String,
    #[serde(default)]
    revision_by_family: BTreeMap<String, u64>,
    #[serde(default)]
    preferences: SelfControlValuesV2,
    #[serde(default)]
    active_controls: BTreeMap<String, ActiveControlV2>,
    #[serde(default)]
    held_intents: BTreeSet<String>,
    #[serde(default)]
    seen_nonces: BTreeMap<String, u64>,
    #[serde(default)]
    idempotency: BTreeMap<String, IdempotencyRecordV2>,
    #[serde(default)]
    receipts: Vec<SelfControlReceiptV2>,
    #[serde(default)]
    clamp_saturation_by_family: BTreeMap<String, u8>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pending_command_sha256: Option<String>,
}

impl RuntimeStateV2 {
    fn new(deployment_identity: String) -> Self {
        Self {
            schema: STATE_SCHEMA.to_string(),
            target_being: TARGET_BEING.to_string(),
            deployment_identity,
            revision_by_family: BTreeMap::new(),
            preferences: SelfControlValuesV2::default(),
            active_controls: BTreeMap::new(),
            held_intents: BTreeSet::new(),
            seen_nonces: BTreeMap::new(),
            idempotency: BTreeMap::new(),
            receipts: Vec::new(),
            clamp_saturation_by_family: BTreeMap::new(),
            pending_command_sha256: None,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct RuntimeStateEnvelopeV1 {
    schema: String,
    state_sha256: String,
    state: RuntimeStateV2,
}

#[derive(Debug)]
struct RuntimeInner {
    state: RuntimeStateV2,
    integrity_blocked: Option<String>,
}

pub struct SelfControlRuntime {
    root: Option<PathBuf>,
    process_identity: String,
    deployment_identity: String,
    bus: Arc<SensoryBus>,
    hard_recovery_reset_probe: fn() -> bool,
    disabled_reason: Option<String>,
    inner: Mutex<RuntimeInner>,
}

impl SelfControlRuntime {
    pub fn open_default(
        process_identity: String,
        deployment_identity: String,
        bus: Arc<SensoryBus>,
        now_unix_ms: u64,
    ) -> Result<Self, String> {
        Self::open(
            default_self_control_root(),
            process_identity,
            deployment_identity,
            bus,
            now_unix_ms,
        )
    }

    pub fn open(
        root: PathBuf,
        process_identity: String,
        deployment_identity: String,
        bus: Arc<SensoryBus>,
        now_unix_ms: u64,
    ) -> Result<Self, String> {
        Self::open_with_safety_probe(
            root,
            process_identity,
            deployment_identity,
            bus,
            now_unix_ms,
            crate::hard_reset::hard_recovery_reset_enabled,
        )
    }

    pub(crate) fn open_with_safety_probe(
        root: PathBuf,
        process_identity: String,
        deployment_identity: String,
        bus: Arc<SensoryBus>,
        now_unix_ms: u64,
        hard_recovery_reset_probe: fn() -> bool,
    ) -> Result<Self, String> {
        storage::ensure_owner_dir(&root)?;
        let trust_path = root.join("trust.json");
        let trust = match storage::read_json::<SelfControlTrustStoreV1>(&trust_path)? {
            Some(trust) => trust,
            None => {
                let trust = SelfControlTrustStoreV1::default();
                storage::write_owner_json(&trust_path, &trust)?;
                trust
            }
        };
        if !trust.is_well_formed() {
            return Err("self-control trust store is malformed".to_string());
        }

        let state_path = root.join("state.json");
        let state = match storage::read_json::<RuntimeStateEnvelopeV1>(&state_path)? {
            Some(envelope) => {
                let mut state = verify_state_envelope_integrity(envelope)?;
                if state.deployment_identity == deployment_identity {
                    // A crash between consume-persist and receipt-write leaves a
                    // pending hand-off behind on the now-current deployment;
                    // finalize turns it into an applied receipt (or reports
                    // tampering). A mis-bound pending is non-fatal here.
                    deployment_handoff::finalize_completed_for_current(
                        &root,
                        &state,
                        &deployment_identity,
                        now_unix_ms,
                    )?;
                    state
                } else {
                    let binding =
                        deployment_handoff::DeploymentBinding::current(&deployment_identity)?;
                    match deployment_handoff::consume_pending_at(
                        &root,
                        &binding,
                        &mut state,
                        now_unix_ms,
                    ) {
                        Ok(true) => state,
                        Ok(false) => {
                            return Err(format!(
                                "self-control state belongs to a stale deployment ({}); \
                                 no deployment hand-off is pending — prepare one with \
                                 `minime self-control prepare-deployment-handoff`",
                                state.deployment_identity
                            ));
                        }
                        Err(reason) => {
                            return Err(format!(
                                "self-control state belongs to a stale deployment ({}); \
                                 deployment hand-off refused: {reason}",
                                state.deployment_identity
                            ));
                        }
                    }
                }
            }
            None => RuntimeStateV2::new(deployment_identity.clone()),
        };
        let runtime = Self {
            root: Some(root),
            process_identity,
            deployment_identity,
            bus,
            hard_recovery_reset_probe,
            disabled_reason: None,
            inner: Mutex::new(RuntimeInner {
                state,
                integrity_blocked: None,
            }),
        };
        runtime.recover_at_startup(now_unix_ms)?;
        Ok(runtime)
    }

    #[must_use]
    pub fn disabled(
        process_identity: String,
        deployment_identity: String,
        bus: Arc<SensoryBus>,
        reason: String,
    ) -> Self {
        Self {
            root: None,
            process_identity,
            deployment_identity: deployment_identity.clone(),
            bus,
            hard_recovery_reset_probe: crate::hard_reset::hard_recovery_reset_enabled,
            disabled_reason: Some(reason),
            inner: Mutex::new(RuntimeInner {
                state: RuntimeStateV2::new(deployment_identity),
                integrity_blocked: None,
            }),
        }
    }

    pub fn provision_trust_store(
        root: &Path,
        trust: &SelfControlTrustStoreV1,
    ) -> Result<(), String> {
        if !trust.is_well_formed() {
            return Err("refusing malformed self-control trust store".to_string());
        }
        storage::write_owner_json(&root.join("trust.json"), trust)
    }

    pub fn verified_status(root: &Path) -> Result<serde_json::Value, String> {
        let envelope = storage::read_json::<RuntimeStateEnvelopeV1>(&root.join("state.json"))?
            .ok_or_else(|| "self-control runtime state is missing".to_string())?;
        let state_sha256 = envelope.state_sha256.clone();
        let deployment_identity = envelope.state.deployment_identity.clone();
        let state = validate_state_envelope(envelope, &deployment_identity)?;
        let active_controls = state
            .active_controls
            .iter()
            .map(|(family, active)| {
                (
                    family.clone(),
                    serde_json::json!({
                        "intent_id": active.intent_id,
                        "command_id": active.command_id,
                        "receipt_id": active.receipt_id,
                        "revision": active.revision,
                        "durability": active.durability,
                        "control_expires_at_unix_ms": active.control_expires_at_unix_ms,
                        "requested_fields": active.requested_fields,
                        "applied_values": active.applied_values,
                    }),
                )
            })
            .collect::<serde_json::Map<_, _>>();
        let receipt_start = state.receipts.len().saturating_sub(64);
        // Lineage view: what THIS binary would call itself, whether the
        // persisted state targets it, and any pending deployment hand-off.
        let cli_deployment_identity =
            crate::sensory_protocol::SensoryServerIdentity::current(0).deployment_identity;
        let binary_sha256 =
            deployment_handoff::DeploymentBinding::current(&cli_deployment_identity)
                .map(|binding| serde_json::Value::String(binding.binary_sha256))
                .unwrap_or(serde_json::Value::Null);
        Ok(serde_json::json!({
            "schema": "minime.self_control.status.v2",
            "target_being": state.target_being,
            "deployment_identity": state.deployment_identity,
            "cli_deployment_identity": cli_deployment_identity,
            "state_targets_this_binary": state.deployment_identity == cli_deployment_identity,
            "binary_sha256": binary_sha256,
            "pending_deployment_handoff": deployment_handoff::pending_summary(root),
            "state_sha256": state_sha256,
            "revision_by_family": state.revision_by_family,
            "preferences": state.preferences,
            "active_controls": active_controls,
            "held_intents": state.held_intents,
            "recent_receipts": state.receipts[receipt_start..],
            "pending_transition": state.pending_command_sha256.is_some(),
            "integrity_verified": true,
            "felt_effect_established": false,
        }))
    }

    #[must_use]
    pub fn is_ready(&self) -> bool {
        self.disabled_reason.is_none()
            && self.load_current_trust().is_ok_and(|trust| {
                trust
                    .pinned_public_keys
                    .get(TARGET_BEING)
                    .is_some_and(|key| valid_public_key(key))
            })
    }

    #[must_use]
    pub fn semantic_controls(&self) -> SemanticControlSnapshotV2 {
        let preferences = &self.inner.lock().state.preferences;
        SemanticControlSnapshotV2 {
            companion_mix: preferences.semantic_companion_mix.unwrap_or(0.0),
            intake_gain: preferences.semantic_intake_gain.unwrap_or(1.0),
            receptivity: preferences.receptivity.unwrap_or(1.0),
        }
    }

    #[must_use]
    pub fn process_identity(&self) -> &str {
        &self.process_identity
    }

    #[must_use]
    pub fn deployment_identity(&self) -> &str {
        &self.deployment_identity
    }

    pub fn process(
        &self,
        command: &SelfControlCommandV2,
        now_unix_ms: u64,
    ) -> SelfControlReceiptV2 {
        let command_sha256 = canonical_self_control_command_sha256(command);
        let family = family_key(command.intent.family);
        let mut inner = self.inner.lock();
        let current_revision = current_revision(&inner.state, family);

        if let Some(reason) = self.disabled_reason.as_deref() {
            return self.receipt(
                command,
                SelfControlReceiptStatusV2::Rejected,
                current_revision,
                now_unix_ms,
                SelfControlValuesV2::default(),
                SelfControlValuesV2::default(),
                ControlSnapshot::default(),
                Some(format!("self_control_runtime_unavailable:{reason}")),
                None,
            );
        }
        if let Some(reason) = inner.integrity_blocked.as_deref() {
            return self.receipt(
                command,
                SelfControlReceiptStatusV2::Rejected,
                current_revision,
                now_unix_ms,
                SelfControlValuesV2::default(),
                SelfControlValuesV2::default(),
                ControlSnapshot::default(),
                Some(format!("self_control_integrity_block:{reason}")),
                None,
            );
        }
        // Structural: the deployment-lineage signer has NO live command
        // authority — not as an actor, not as a co-signer. Without this, its
        // trust pin would make it an eligible Mutual co-signer the day a
        // SharedCoupling adapter is implemented.
        if command.intent.actor.being == crate::self_control_identity::DEPLOYMENT_STEWARD_BEING
            || command.authority_proofs.iter().any(|proof| {
                proof.signer_being == crate::self_control_identity::DEPLOYMENT_STEWARD_BEING
            })
        {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "deployment_steward_has_no_command_authority",
            );
        }
        if command.intent.target_being != TARGET_BEING {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "target_being_mismatch",
            );
        }
        if command.intent.target_deployment_identity != self.deployment_identity {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "stale_target_deployment",
            );
        }
        if command.intent.command_expires_at_unix_ms < now_unix_ms {
            return self.receipt(
                command,
                SelfControlReceiptStatusV2::Expired,
                current_revision,
                now_unix_ms,
                SelfControlValuesV2::default(),
                SelfControlValuesV2::default(),
                ControlSnapshot::default(),
                Some("command_expired".to_string()),
                None,
            );
        }
        if command.intent.issued_at_unix_ms > now_unix_ms.saturating_add(FUTURE_ISSUE_SKEW_MS) {
            return self.rejected(command, current_revision, now_unix_ms, "issued_in_future");
        }
        if !command.is_well_formed(now_unix_ms) {
            return self.rejected(command, current_revision, now_unix_ms, "malformed_command");
        }
        // Constitution C2: a lease may not outlast the strictest
        // durability_policy.lease_max_secs across its fields in the envelope
        // registry. Durations are policy, not values — exceeding is REJECTED
        // (never clamped), so no receipt-equality clause is disturbed. With
        // no registry or no policy, only the wire-shape cap applies.
        let lease_exceeds_envelope = match (
            command.intent.durability,
            command.intent.control_expires_at_unix_ms,
        ) {
            (SelfControlDurabilityV2::Lease, Some(expiry)) => {
                crate::envelope_registry::load_registry()
                    .and_then(|registry| {
                        registry.strictest_lease_max_secs(command.intent.values.field_names())
                    })
                    .is_some_and(|max_secs| {
                        expiry.saturating_sub(command.intent.issued_at_unix_ms)
                            > max_secs.saturating_mul(1_000)
                    })
            }
            _ => false,
        };
        if lease_exceeds_envelope {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "lease_exceeds_envelope_duration",
            );
        }
        if !self.authority_is_pinned(command) {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "authority_key_not_pinned",
            );
        }

        if let Some(cached) = inner.state.idempotency.get(&command.intent.idempotency_key) {
            if cached.command_sha256 != command_sha256 {
                return self.rejected(
                    command,
                    current_revision,
                    now_unix_ms,
                    "idempotency_key_conflict",
                );
            }
            let mut duplicate = cached.receipt.clone();
            duplicate.status = SelfControlReceiptStatusV2::Duplicate;
            duplicate.receipt_id = receipt_id(&command_sha256, "duplicate", now_unix_ms);
            duplicate.received_at_unix_ms = now_unix_ms;
            duplicate.completed_at_unix_ms = now_unix_ms;
            duplicate.reason = Some("idempotent_replay".to_string());
            inner.state.receipts.push(duplicate.clone());
            prune_state(&mut inner.state, now_unix_ms);
            let _ = self.persist(&inner.state);
            return duplicate;
        }
        if command.authority_proofs.iter().any(|proof| {
            inner
                .state
                .seen_nonces
                .contains_key(&nonce_key(&proof.signer_being, &proof.nonce))
        }) {
            return self.rejected(
                command,
                current_revision,
                now_unix_ms,
                "authority_nonce_replay",
            );
        }

        let next_revision = current_revision.checked_add(1);
        if command.intent.expected_revision != current_revision
            || next_revision != Some(command.intent.revision)
        {
            let receipt = self.receipt(
                command,
                SelfControlReceiptStatusV2::RevisionConflict,
                current_revision,
                now_unix_ms,
                SelfControlValuesV2::default(),
                SelfControlValuesV2::default(),
                ControlSnapshot::default(),
                Some("revision_conflict".to_string()),
                None,
            );
            return self.cache_authenticated(
                &mut inner,
                command,
                &command_sha256,
                receipt,
                now_unix_ms,
            );
        }

        match command.intent.action {
            SelfControlActionV2::Set => {
                self.apply_set(&mut inner, command, &command_sha256, family, now_unix_ms)
            }
            SelfControlActionV2::Withdraw => self.apply_withdraw_or_hold(
                &mut inner,
                command,
                &command_sha256,
                family,
                now_unix_ms,
                false,
            ),
            SelfControlActionV2::Hold => self.apply_withdraw_or_hold(
                &mut inner,
                command,
                &command_sha256,
                family,
                now_unix_ms,
                true,
            ),
            SelfControlActionV2::Revert => {
                self.apply_revert(&mut inner, command, &command_sha256, family, now_unix_ms)
            }
        }
    }

    pub fn sweep_expired(&self, now_unix_ms: u64) -> Vec<SelfControlReceiptV2> {
        let mut inner = self.inner.lock();
        let expired = inner
            .state
            .active_controls
            .iter()
            .filter_map(|(family, active)| {
                active
                    .control_expires_at_unix_ms
                    .filter(|expiry| *expiry <= now_unix_ms)
                    .map(|_| family.clone())
            })
            .collect::<Vec<_>>();
        let mut receipts = Vec::new();
        for family in expired {
            let Some(active) = inner.state.active_controls.remove(&family) else {
                continue;
            };
            let snapshot = ControlSnapshot {
                values: active.previous_values.clone(),
                automatic_fields: active.previous_automatic_fields.clone(),
            };
            let _ = apply_values(
                &self.bus,
                &snapshot.values,
                &snapshot.automatic_fields,
                &active.intent_id,
                (self.hard_recovery_reset_probe)(),
            );
            inner.state.preferences = replace_requested_preferences(
                &inner.state.preferences,
                &active.requested_fields,
                &active.previous_values,
            )
            .unwrap_or_else(|_| SelfControlValuesV2::default());
            let receipt = expired_receipt(
                &active,
                &self.process_identity,
                &self.deployment_identity,
                now_unix_ms,
            );
            inner.state.receipts.push(receipt.clone());
            receipts.push(receipt);
        }
        if !receipts.is_empty() {
            prune_state(&mut inner.state, now_unix_ms);
            let _ = self.persist(&inner.state);
        }
        receipts
    }

    fn apply_set(
        &self,
        inner: &mut RuntimeInner,
        command: &SelfControlCommandV2,
        command_sha256: &str,
        family: &str,
        now_unix_ms: u64,
    ) -> SelfControlReceiptV2 {
        if command.intent.authority_class == SelfControlAuthorityClassV2::Mutual
            || command.intent.family == SelfControlFamilyV2::SharedCoupling
        {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                "shared_coupling_adapter_not_implemented",
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }
        let unsupported = unsupported_fields(command.intent.family, &command.intent.values);
        if !unsupported.is_empty() {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                &format!("unsupported_fields:{}", unsupported.join(",")),
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }
        let clamped = clamp_values(&command.intent.values);
        let was_clamped = clamped != command.intent.values;
        let saturation = inner
            .state
            .clamp_saturation_by_family
            .entry(family.to_string())
            .or_default();
        *saturation = if was_clamped {
            saturation.saturating_add(1)
        } else {
            0
        };
        if *saturation >= 3 {
            let rolled_back = self.rollback_active_family(inner, family);
            inner
                .state
                .revision_by_family
                .insert(family.to_string(), command.intent.revision);
            let receipt = self.receipt(
                command,
                if rolled_back {
                    SelfControlReceiptStatusV2::RolledBack
                } else {
                    SelfControlReceiptStatusV2::Rejected
                },
                command.intent.revision,
                now_unix_ms,
                clamped,
                SelfControlValuesV2::default(),
                ControlSnapshot::default(),
                Some("repeated_clamp_saturation".to_string()),
                None,
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }

        let snapshot = snapshot_values(&self.bus, &clamped, &inner.state.preferences);
        let requested_fields = clamped.field_names();
        let prior_active = inner.state.active_controls.get(family).cloned();
        let rollback_snapshot = prior_active.as_ref().map_or_else(
            || snapshot.clone(),
            |active| {
                let newly_requested = requested_fields
                    .iter()
                    .filter(|field| !active.requested_fields.contains(field))
                    .cloned()
                    .collect::<Vec<_>>();
                let values = replace_requested_preferences(
                    &active.previous_values,
                    &newly_requested,
                    &snapshot.values,
                )
                .unwrap_or_else(|_| active.previous_values.clone());
                let mut automatic_fields = active.previous_automatic_fields.clone();
                for field in &snapshot.automatic_fields {
                    if newly_requested.contains(field) && !automatic_fields.contains(field) {
                        automatic_fields.push(field.clone());
                    }
                }
                automatic_fields.sort();
                ControlSnapshot {
                    values,
                    automatic_fields,
                }
            },
        );
        let mut active_requested_fields = prior_active
            .as_ref()
            .map(|active| active.requested_fields.clone())
            .unwrap_or_default();
        for field in &requested_fields {
            if !active_requested_fields.contains(field) {
                active_requested_fields.push(field.clone());
            }
        }
        active_requested_fields.sort();
        let active_applied_values = prior_active.as_ref().map_or_else(
            || clamped.clone(),
            |active| {
                replace_requested_preferences(&active.applied_values, &requested_fields, &clamped)
                    .unwrap_or_else(|_| clamped.clone())
            },
        );
        if let Err(error) = self.prepare_transition(inner, command_sha256) {
            return self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                &format!("state_prepare_failed:{error}"),
            );
        }
        if let Err(reason) = apply_values(
            &self.bus,
            &clamped,
            &[],
            &command.intent.intent_id,
            (self.hard_recovery_reset_probe)(),
        ) {
            inner.state.pending_command_sha256 = None;
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                &format!("safety_hold:{reason}"),
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }

        if command.intent.durability != SelfControlDurabilityV2::OneShot {
            inner.state.preferences = replace_requested_preferences(
                &inner.state.preferences,
                &requested_fields,
                &clamped,
            )
            .unwrap_or_else(|_| inner.state.preferences.clone());
        }
        inner
            .state
            .revision_by_family
            .insert(family.to_string(), command.intent.revision);
        let receipt = self.receipt(
            command,
            SelfControlReceiptStatusV2::Applied,
            command.intent.revision,
            now_unix_ms,
            clamped.clone(),
            clamped.clone(),
            snapshot.clone(),
            was_clamped.then_some("receiver_clamped_values".to_string()),
            None,
        );
        if command.intent.durability != SelfControlDurabilityV2::OneShot {
            inner.state.active_controls.insert(
                family.to_string(),
                ActiveControlV2 {
                    family: command.intent.family,
                    intent_id: command.intent.intent_id.clone(),
                    command_id: command.command_id.clone(),
                    idempotency_key: command.intent.idempotency_key.clone(),
                    receipt_id: receipt.receipt_id.clone(),
                    revision: command.intent.revision,
                    durability: command.intent.durability,
                    control_expires_at_unix_ms: command.intent.control_expires_at_unix_ms,
                    requested_fields: active_requested_fields,
                    applied_values: active_applied_values,
                    previous_values: rollback_snapshot.values,
                    previous_automatic_fields: rollback_snapshot.automatic_fields,
                },
            );
        }
        let completed =
            self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        if completed.status == SelfControlReceiptStatusV2::Rejected {
            let _ = apply_values(
                &self.bus,
                &snapshot.values,
                &snapshot.automatic_fields,
                &command.intent.intent_id,
                (self.hard_recovery_reset_probe)(),
            );
            if command.intent.durability == SelfControlDurabilityV2::OneShot {
                self.rollback_one_shot(&command.intent.values);
            }
        }
        completed
    }

    #[allow(clippy::too_many_arguments)]
    fn apply_withdraw_or_hold(
        &self,
        inner: &mut RuntimeInner,
        command: &SelfControlCommandV2,
        command_sha256: &str,
        family: &str,
        now_unix_ms: u64,
        safety_hold: bool,
    ) -> SelfControlReceiptV2 {
        let related_intent = command.intent.related_intent_id.as_deref().unwrap_or("");
        let Some(active) = inner.state.active_controls.get(family).cloned() else {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                "active_control_not_found",
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        };
        if active.intent_id != related_intent {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                "related_intent_mismatch",
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }
        if let Err(error) = self.prepare_transition(inner, command_sha256) {
            return self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                &format!("state_prepare_failed:{error}"),
            );
        }
        let restored = ControlSnapshot {
            values: active.previous_values.clone(),
            automatic_fields: active.previous_automatic_fields.clone(),
        };
        if let Err(reason) = apply_values(
            &self.bus,
            &restored.values,
            &restored.automatic_fields,
            &active.intent_id,
            (self.hard_recovery_reset_probe)(),
        ) {
            inner.state.pending_command_sha256 = None;
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                &format!("rollback_failed:{reason}"),
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }
        inner.state.preferences = replace_requested_preferences(
            &inner.state.preferences,
            &active.requested_fields,
            &active.previous_values,
        )
        .unwrap_or_else(|_| inner.state.preferences.clone());
        inner.state.active_controls.remove(family);
        if safety_hold {
            inner.state.held_intents.insert(active.intent_id.clone());
        }
        inner
            .state
            .revision_by_family
            .insert(family.to_string(), command.intent.revision);
        let receipt = self.receipt(
            command,
            if safety_hold {
                SelfControlReceiptStatusV2::SafetyHeld
            } else {
                SelfControlReceiptStatusV2::Withdrawn
            },
            command.intent.revision,
            now_unix_ms,
            active.previous_values.clone(),
            active.previous_values.clone(),
            ControlSnapshot {
                values: active.applied_values.clone(),
                automatic_fields: Vec::new(),
            },
            Some(if safety_hold {
                "safety_supervisor_hold_reverted_active_control".to_string()
            } else {
                "being_withdrew_active_control".to_string()
            }),
            Some(active.receipt_id.clone()),
        );
        let completed =
            self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        if completed.status == SelfControlReceiptStatusV2::Rejected {
            let _ = apply_values(
                &self.bus,
                &active.applied_values,
                &[],
                &active.intent_id,
                (self.hard_recovery_reset_probe)(),
            );
        }
        completed
    }

    fn apply_revert(
        &self,
        inner: &mut RuntimeInner,
        command: &SelfControlCommandV2,
        command_sha256: &str,
        family: &str,
        now_unix_ms: u64,
    ) -> SelfControlReceiptV2 {
        let related_receipt = command.intent.related_receipt_id.as_deref().unwrap_or("");
        let Some(active) = inner.state.active_controls.get(family).cloned() else {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                "revert_target_not_active",
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        };
        if active.receipt_id != related_receipt {
            let receipt = self.rejected(
                command,
                current_revision(&inner.state, family),
                now_unix_ms,
                "related_receipt_mismatch",
            );
            return self.cache_authenticated(inner, command, command_sha256, receipt, now_unix_ms);
        }
        let mut routed = command.clone();
        routed.intent.related_intent_id = Some(active.intent_id);
        self.apply_withdraw_or_hold(inner, &routed, command_sha256, family, now_unix_ms, true)
    }

    fn authority_is_pinned(&self, command: &SelfControlCommandV2) -> bool {
        if command.intent.authority_class == SelfControlAuthorityClassV2::SelfOwned
            && command.intent.actor.deployment_identity != self.deployment_identity
        {
            return false;
        }
        let Ok(trust) = self.load_current_trust() else {
            return false;
        };
        command.authority_proofs.iter().all(|proof| {
            trust
                .pinned_public_keys
                .get(&proof.signer_being)
                .is_some_and(|key| constant_time_text_eq(key, &proof.signer_public_key_hex))
        })
    }

    fn load_current_trust(&self) -> Result<SelfControlTrustStoreV1, String> {
        let root = self
            .root
            .as_deref()
            .ok_or_else(|| "self-control runtime has no persistence root".to_string())?;
        load_trust_at(root)
    }

    fn recover_at_startup(&self, now_unix_ms: u64) -> Result<(), String> {
        let mut inner = self.inner.lock();
        inner.state.pending_command_sha256 = None;
        let active = inner.state.active_controls.clone();
        for (family, control) in active {
            let expired = control
                .control_expires_at_unix_ms
                .is_some_and(|expiry| expiry <= now_unix_ms);
            if expired {
                let snapshot = ControlSnapshot {
                    values: control.previous_values.clone(),
                    automatic_fields: control.previous_automatic_fields.clone(),
                };
                let _ = apply_values(
                    &self.bus,
                    &snapshot.values,
                    &snapshot.automatic_fields,
                    &control.intent_id,
                    (self.hard_recovery_reset_probe)(),
                );
                inner.state.preferences = replace_requested_preferences(
                    &inner.state.preferences,
                    &control.requested_fields,
                    &control.previous_values,
                )?;
                inner.state.active_controls.remove(&family);
                inner.state.receipts.push(expired_receipt(
                    &control,
                    &self.process_identity,
                    &self.deployment_identity,
                    now_unix_ms,
                ));
            } else if let Err(reason) = apply_values(
                &self.bus,
                &control.applied_values,
                &[],
                &control.intent_id,
                (self.hard_recovery_reset_probe)(),
            ) {
                inner.state.active_controls.remove(&family);
                inner.state.held_intents.insert(control.intent_id.clone());
                inner.state.preferences = replace_requested_preferences(
                    &inner.state.preferences,
                    &control.requested_fields,
                    &control.previous_values,
                )?;
                let mut receipt = expired_receipt(
                    &control,
                    &self.process_identity,
                    &self.deployment_identity,
                    now_unix_ms,
                );
                receipt.status = SelfControlReceiptStatusV2::SafetyHeld;
                receipt.reason = Some(format!("restart_recovery_safety_hold:{reason}"));
                inner.state.receipts.push(receipt);
            }
        }
        prune_state(&mut inner.state, now_unix_ms);
        self.persist(&inner.state)
    }

    fn prepare_transition(
        &self,
        inner: &mut RuntimeInner,
        command_sha256: &str,
    ) -> Result<(), String> {
        inner.state.pending_command_sha256 = Some(command_sha256.to_string());
        if let Err(error) = self.persist(&inner.state) {
            inner.state.pending_command_sha256 = None;
            return Err(error);
        }
        Ok(())
    }

    fn cache_authenticated(
        &self,
        inner: &mut RuntimeInner,
        command: &SelfControlCommandV2,
        command_sha256: &str,
        mut receipt: SelfControlReceiptV2,
        now_unix_ms: u64,
    ) -> SelfControlReceiptV2 {
        inner.state.pending_command_sha256 = None;
        for proof in &command.authority_proofs {
            inner.state.seen_nonces.insert(
                nonce_key(&proof.signer_being, &proof.nonce),
                proof.expires_at_unix_ms,
            );
        }
        inner.state.idempotency.insert(
            command.intent.idempotency_key.clone(),
            IdempotencyRecordV2 {
                command_sha256: command_sha256.to_string(),
                observed_at_unix_ms: now_unix_ms,
                receipt: receipt.clone(),
            },
        );
        inner.state.receipts.push(receipt.clone());
        prune_state(&mut inner.state, now_unix_ms);
        if let Err(error) = self.persist(&inner.state) {
            receipt.status = SelfControlReceiptStatusV2::Rejected;
            match self.reload_durable_state() {
                Ok(state) => {
                    inner.state = state;
                    receipt.reason = Some(format!("state_commit_failed:{error}"));
                }
                Err(recovery_error) => {
                    inner.integrity_blocked = Some(recovery_error.clone());
                    receipt.reason = Some(format!(
                        "state_commit_failed:{error};integrity_recovery_failed:{recovery_error}"
                    ));
                }
            }
        }
        receipt
    }

    fn reload_durable_state(&self) -> Result<RuntimeStateV2, String> {
        let Some(root) = self.root.as_deref() else {
            return Err("self-control runtime has no persistence root".to_string());
        };
        let envelope = storage::read_json::<RuntimeStateEnvelopeV1>(&root.join("state.json"))?
            .ok_or_else(|| "self-control durable state disappeared".to_string())?;
        let mut state = validate_state_envelope(envelope, &self.deployment_identity)?;
        state.pending_command_sha256 = None;
        self.persist(&state)?;
        Ok(state)
    }

    fn rollback_active_family(&self, inner: &mut RuntimeInner, family: &str) -> bool {
        let Some(active) = inner.state.active_controls.remove(family) else {
            return false;
        };
        let _ = apply_values(
            &self.bus,
            &active.previous_values,
            &active.previous_automatic_fields,
            &active.intent_id,
            (self.hard_recovery_reset_probe)(),
        );
        inner.state.preferences = replace_requested_preferences(
            &inner.state.preferences,
            &active.requested_fields,
            &active.previous_values,
        )
        .unwrap_or_else(|_| inner.state.preferences.clone());
        true
    }

    fn rollback_one_shot(&self, requested: &SelfControlValuesV2) {
        if requested.esn_leak_override.is_some() {
            self.bus.clear_esn_leak_override();
        }
        if requested.mode_disperse.is_some() || requested.porosity.is_some() {
            let status = self.bus.shadow_influence_status();
            if status
                .basis
                .as_deref()
                .is_some_and(|basis| basis == "mode-disperse/broadband")
            {
                let _ = self.bus.receive_shadow_influence(
                    crate::sensory_bus::ShadowInfluenceRequest {
                        intent_id: status
                            .intent_id
                            .unwrap_or_else(|| "mode-disperse".to_string()),
                        label: "mode-disperse/broadband".to_string(),
                        command: "release".to_string(),
                        stage: Some("rollback".to_string()),
                        features: Vec::new(),
                        max_abs: None,
                        duration_ticks: None,
                        decay_ticks: Some(1),
                        basis: Some("mode-disperse/broadband".to_string()),
                    },
                    false,
                    false,
                );
            }
        }
    }

    fn persist(&self, state: &RuntimeStateV2) -> Result<(), String> {
        let Some(root) = self.root.as_deref() else {
            return Err("self-control runtime has no persistence root".to_string());
        };
        persist_state_at(root, state)
    }

    fn rejected(
        &self,
        command: &SelfControlCommandV2,
        resulting_revision: u64,
        now_unix_ms: u64,
        reason: &str,
    ) -> SelfControlReceiptV2 {
        self.receipt(
            command,
            SelfControlReceiptStatusV2::Rejected,
            resulting_revision,
            now_unix_ms,
            SelfControlValuesV2::default(),
            SelfControlValuesV2::default(),
            ControlSnapshot::default(),
            Some(reason.to_string()),
            None,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn receipt(
        &self,
        command: &SelfControlCommandV2,
        status: SelfControlReceiptStatusV2,
        resulting_revision: u64,
        now_unix_ms: u64,
        clamped_values: SelfControlValuesV2,
        applied_values: SelfControlValuesV2,
        previous: ControlSnapshot,
        reason: Option<String>,
        rollback_receipt_id: Option<String>,
    ) -> SelfControlReceiptV2 {
        let command_sha256 = canonical_self_control_command_sha256(command);
        SelfControlReceiptV2 {
            schema: SELF_CONTROL_RECEIPT_SCHEMA_V2.to_string(),
            receipt_id: receipt_id(&command_sha256, status_name(status), now_unix_ms),
            command_id: bounded_id(&command.command_id, "invalid-command"),
            intent_id: bounded_id(&command.intent.intent_id, "invalid-intent"),
            idempotency_key: bounded_id(
                &command.intent.idempotency_key,
                &format!("invalid-idempotency-{}", &command_sha256[..16]),
            ),
            status,
            requested_revision: command.intent.revision,
            resulting_revision,
            target_being: bounded_id(&command.intent.target_being, TARGET_BEING),
            target_deployment_identity: bounded_id(
                &command.intent.target_deployment_identity,
                &self.deployment_identity,
            ),
            requested_values: command.intent.values.clone(),
            clamped_values,
            applied_values,
            previous_values: previous.values,
            previous_automatic_fields: previous.automatic_fields,
            received_at_unix_ms: now_unix_ms,
            completed_at_unix_ms: now_unix_ms,
            control_expires_at_unix_ms: command.intent.control_expires_at_unix_ms,
            rollback_receipt_id,
            reason,
            server_process_identity: self.process_identity.clone(),
            server_deployment_identity: self.deployment_identity.clone(),
            felt_effect_established: false,
        }
    }
}

fn validate_state_envelope(
    envelope: RuntimeStateEnvelopeV1,
    deployment_identity: &str,
) -> Result<RuntimeStateV2, String> {
    let state = verify_state_envelope_integrity(envelope)?;
    if state.deployment_identity != deployment_identity {
        return Err("self-control state belongs to a stale deployment".to_string());
    }
    Ok(state)
}

/// Schema + canonical-hash verification only; the caller decides what a
/// deployment-identity mismatch means (fail closed vs. hand-off consumption).
fn verify_state_envelope_integrity(
    envelope: RuntimeStateEnvelopeV1,
) -> Result<RuntimeStateV2, String> {
    if envelope.schema != STATE_ENVELOPE_SCHEMA
        || envelope.state.schema != STATE_SCHEMA
        || envelope.state.target_being != TARGET_BEING
    {
        return Err("self-control state schema mismatch".to_string());
    }
    if envelope.state_sha256 != state_sha256(&envelope.state)? {
        return Err("self-control state integrity mismatch".to_string());
    }
    Ok(envelope.state)
}

/// The ONE state hash used by persist, envelope verification, and the
/// deployment hand-off (prepare, consume, finalize). Canonical JSON keeps it
/// stable across struct field order.
fn state_sha256(state: &RuntimeStateV2) -> Result<String, String> {
    let value =
        serde_json::to_value(state).map_err(|error| format!("encode runtime state: {error}"))?;
    Ok(canonical_json_value_sha256(&value))
}

fn persist_state_at(root: &Path, state: &RuntimeStateV2) -> Result<(), String> {
    let envelope = RuntimeStateEnvelopeV1 {
        schema: STATE_ENVELOPE_SCHEMA.to_string(),
        state_sha256: state_sha256(state)?,
        state: state.clone(),
    };
    storage::write_owner_json(&root.join("state.json"), &envelope)
}

fn load_trust_at(root: &Path) -> Result<SelfControlTrustStoreV1, String> {
    let trust = storage::read_json::<SelfControlTrustStoreV1>(&root.join("trust.json"))?
        .ok_or_else(|| "self-control trust store is missing".to_string())?;
    if !trust.is_well_formed() {
        return Err("self-control trust store is malformed".to_string());
    }
    Ok(trust)
}

/// Prepare a signed deployment hand-off carrying the persisted self-control
/// state to THIS binary's deployment identity. Explicit CLI/operator act only.
pub fn prepare_deployment_handoff(
    root: &Path,
    operator_actor: &str,
    operator_ack: &str,
    now_unix_ms: u64,
) -> Result<serde_json::Value, String> {
    let identity = crate::sensory_protocol::SensoryServerIdentity::current(0).deployment_identity;
    let binding = deployment_handoff::DeploymentBinding::current(&identity)?;
    deployment_handoff::prepare_at(root, &binding, operator_actor, operator_ack, now_unix_ms)
}

fn expired_receipt(
    active: &ActiveControlV2,
    process_identity: &str,
    deployment_identity: &str,
    now_unix_ms: u64,
) -> SelfControlReceiptV2 {
    let identity = format!("{}:{}:{now_unix_ms}", active.receipt_id, active.intent_id);
    let hash = canonical_json_value_sha256(&serde_json::json!(identity));
    SelfControlReceiptV2 {
        schema: SELF_CONTROL_RECEIPT_SCHEMA_V2.to_string(),
        receipt_id: format!("self-control-expiry:{}", &hash[..24]),
        command_id: active.command_id.clone(),
        intent_id: active.intent_id.clone(),
        idempotency_key: active.idempotency_key.clone(),
        status: SelfControlReceiptStatusV2::Expired,
        requested_revision: active.revision,
        resulting_revision: active.revision,
        target_being: TARGET_BEING.to_string(),
        target_deployment_identity: deployment_identity.to_string(),
        requested_values: active.applied_values.clone(),
        clamped_values: active.applied_values.clone(),
        applied_values: active.previous_values.clone(),
        previous_values: active.applied_values.clone(),
        previous_automatic_fields: active.previous_automatic_fields.clone(),
        received_at_unix_ms: now_unix_ms,
        completed_at_unix_ms: now_unix_ms,
        control_expires_at_unix_ms: active.control_expires_at_unix_ms,
        rollback_receipt_id: Some(active.receipt_id.clone()),
        reason: Some("lease_expired_automatic_rollback".to_string()),
        server_process_identity: process_identity.to_string(),
        server_deployment_identity: deployment_identity.to_string(),
        felt_effect_established: false,
    }
}

fn current_revision(state: &RuntimeStateV2, family: &str) -> u64 {
    state.revision_by_family.get(family).copied().unwrap_or(0)
}

fn family_key(family: SelfControlFamilyV2) -> &'static str {
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

fn nonce_key(signer: &str, nonce: &str) -> String {
    format!("{signer}:{nonce}")
}

fn prune_state(state: &mut RuntimeStateV2, now_unix_ms: u64) {
    state.seen_nonces.retain(|_, expiry| *expiry >= now_unix_ms);
    while state.seen_nonces.len() > MAX_NONCES {
        if let Some(key) = state.seen_nonces.keys().next().cloned() {
            state.seen_nonces.remove(&key);
        }
    }
    while state.idempotency.len() > MAX_IDEMPOTENCY {
        let oldest = state
            .idempotency
            .iter()
            .min_by_key(|(_, record)| record.observed_at_unix_ms)
            .map(|(key, _)| key.clone());
        let Some(oldest) = oldest else {
            break;
        };
        state.idempotency.remove(&oldest);
    }
    if state.receipts.len() > MAX_RECEIPTS {
        let drain = state.receipts.len() - MAX_RECEIPTS;
        state.receipts.drain(..drain);
    }
}

fn valid_public_key(value: &str) -> bool {
    hex::decode(value)
        .ok()
        .is_some_and(|bytes| bytes.len() == 32)
}

fn constant_time_text_eq(left: &str, right: &str) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.bytes()
        .zip(right.bytes())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn bounded_id(value: &str, fallback: &str) -> String {
    let value = value.trim();
    if value.is_empty() || value.len() > 256 {
        fallback.to_string()
    } else {
        value.to_string()
    }
}

fn receipt_id(command_sha256: &str, status: &str, now_unix_ms: u64) -> String {
    let material = serde_json::json!({
        "command_sha256": command_sha256,
        "status": status,
        "completed_at_unix_ms": now_unix_ms,
    });
    let hash = canonical_json_value_sha256(&material);
    format!("self-control-receipt:{}", &hash[..24])
}

const fn status_name(status: SelfControlReceiptStatusV2) -> &'static str {
    match status {
        SelfControlReceiptStatusV2::Applied => "applied",
        SelfControlReceiptStatusV2::Duplicate => "duplicate",
        SelfControlReceiptStatusV2::Rejected => "rejected",
        SelfControlReceiptStatusV2::RevisionConflict => "revision_conflict",
        SelfControlReceiptStatusV2::Expired => "expired",
        SelfControlReceiptStatusV2::Withdrawn => "withdrawn",
        SelfControlReceiptStatusV2::SafetyHeld => "safety_held",
        SelfControlReceiptStatusV2::RolledBack => "rolled_back",
    }
}

#[must_use]
pub fn default_self_control_root() -> PathBuf {
    if let Some(root) = std::env::var_os("MINIME_SELF_CONTROL_ROOT") {
        return PathBuf::from(root);
    }
    std::env::var_os("HOME").map_or_else(
        || PathBuf::from("workspace/self-control-v2"),
        |home| PathBuf::from(home).join(".minime/self-control-v2"),
    )
}

#[cfg(test)]
mod tests;
