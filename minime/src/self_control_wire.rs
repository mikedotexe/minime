use std::collections::BTreeMap;

use ed25519_dalek::{Signature, Verifier as _, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};

pub const SELF_CONTROL_INTENT_SCHEMA_V2: &str = "self_control.intent.v2";
pub const SELF_CONTROL_COMMAND_SCHEMA_V2: &str = "self_control.command.v2";
pub const SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1: &str = "self_control.authority_proof.v1";
pub const SELF_CONTROL_RECEIPT_SCHEMA_V2: &str = "self_control.receipt.v2";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelfControlActionV2 {
    Set,
    Withdraw,
    Hold,
    Revert,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelfControlDurabilityV2 {
    Standing,
    Lease,
    OneShot,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelfControlFamilyV2 {
    Conversation,
    SemanticContinuity,
    SemanticEmission,
    Memory,
    SensoryIntake,
    ReservoirRegulation,
    ReservoirGeometry,
    PiController,
    LocalTopology,
    SharedCoupling,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelfControlAuthorityClassV2 {
    SelfOwned,
    Mutual,
    SafetySupervisor,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SelfControlSourceIdentityV1 {
    pub being: String,
    pub process_identity: String,
    pub deployment_identity: String,
}

impl SelfControlSourceIdentityV1 {
    #[must_use]
    pub fn is_complete(&self) -> bool {
        valid_identifier(&self.being)
            && valid_identifier(&self.process_identity)
            && valid_identifier(&self.deployment_identity)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SelfControlValuesV2 {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub conversation_temperature: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub response_token_limit: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub aperture: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub continuity_readout: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub semantic_strand_retention_turns: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vibrancy_aperture: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub semantic_emission_gain: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub semantic_companion_mix: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generation_noise: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub codec_dimension_weights: Option<BTreeMap<String, f32>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub warmth_intensity: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hebbian_learning_rate_scale: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub semantic_intake_gain: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub peer_journal_visible: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub peer_breathing_coupled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receptivity: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub porosity: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_sensory_admission: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub synth_gain: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub keep_bias: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub exploration_noise: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fill_target: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub regulation_strength: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub smoothing_preference: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub geom_curiosity: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_lambda_bias: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub geom_drive: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub penalty_sensitivity: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub breathing_rate_scale: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_mode: Option<u8>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub journal_resonance: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_interval: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embedding_strength: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_decay_rate: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transition_cushion: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_annotation: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_now: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deep_breathing: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub synth_noise_level: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pure_tone: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub legacy_audio_synth: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub legacy_video_synth: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub live_audio_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub live_video_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pi_kp: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pi_ki: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pi_max_step: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pi_geom_weight: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pi_integrator_leak: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub esn_leak_override: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub esn_leak_override_ticks: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mode_disperse: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mode_disperse_duration_ticks: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mode_disperse_decay_ticks: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shared_sensory_admission: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shadow_influence_gain: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cross_being_semantic_gain: Option<f32>,
}

impl SelfControlValuesV2 {
    #[must_use]
    pub fn field_count(&self) -> usize {
        let Ok(Value::Object(fields)) = serde_json::to_value(self) else {
            return 0;
        };
        fields.values().filter(|value| !value.is_null()).count()
    }

    #[must_use]
    pub fn field_names(&self) -> Vec<String> {
        let Ok(Value::Object(fields)) = serde_json::to_value(self) else {
            return Vec::new();
        };
        fields
            .into_iter()
            .filter_map(|(name, value)| (!value.is_null()).then_some(name))
            .collect()
    }

    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        let Ok(Value::Object(fields)) = serde_json::to_value(self) else {
            return false;
        };
        fields.values().all(value_is_finite)
            && self
                .checkpoint_annotation
                .as_deref()
                .is_none_or(valid_bounded_text)
            && self.codec_dimension_weights.as_ref().is_none_or(|weights| {
                !weights.is_empty()
                    && weights.len() <= 64
                    && weights
                        .iter()
                        .all(|(name, value)| valid_identifier(name) && value.is_finite())
            })
    }

    #[must_use]
    pub fn requires_one_shot(&self) -> bool {
        self.porosity.is_some()
            || self.esn_leak_override.is_some()
            || self.esn_leak_override_ticks.is_some()
            || self.mode_disperse.is_some()
            || self.mode_disperse_duration_ticks.is_some()
            || self.mode_disperse_decay_ticks.is_some()
            || self.checkpoint_now == Some(true)
    }

    #[must_use]
    pub fn includes_shared_coupling(&self) -> bool {
        self.shared_sensory_admission.is_some()
            || self.shadow_influence_gain.is_some()
            || self.cross_being_semantic_gain.is_some()
            || self.peer_breathing_coupled == Some(true)
    }

    #[must_use]
    pub fn matches_family(&self, family: SelfControlFamilyV2) -> bool {
        let fields = self.field_names();
        !fields.is_empty()
            && fields
                .iter()
                .all(|field| self_control_field_allowed(family, field))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelfControlIntentV2 {
    pub schema: String,
    pub intent_id: String,
    pub actor: SelfControlSourceIdentityV1,
    pub target_being: String,
    pub target_deployment_identity: String,
    pub family: SelfControlFamilyV2,
    pub action: SelfControlActionV2,
    pub durability: SelfControlDurabilityV2,
    pub authority_class: SelfControlAuthorityClassV2,
    pub authority_scope: String,
    pub revision: u64,
    pub expected_revision: u64,
    pub issued_at_unix_ms: u64,
    pub command_expires_at_unix_ms: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub control_expires_at_unix_ms: Option<u64>,
    pub idempotency_key: String,
    pub values: SelfControlValuesV2,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub related_intent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub related_receipt_id: Option<String>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    #[serde(default)]
    pub success_conditions: Vec<String>,
    #[serde(default)]
    pub stop_conditions: Vec<String>,
}

impl SelfControlIntentV2 {
    #[must_use]
    pub fn is_well_formed(&self, now_unix_ms: u64) -> bool {
        let action_shape_valid = match self.action {
            SelfControlActionV2::Set => {
                self.values.field_count() > 0
                    && self.related_intent_id.is_none()
                    && self.related_receipt_id.is_none()
            }
            SelfControlActionV2::Withdraw | SelfControlActionV2::Hold => {
                self.values.field_count() == 0
                    && self
                        .related_intent_id
                        .as_deref()
                        .is_some_and(valid_identifier)
                    && self.durability == SelfControlDurabilityV2::OneShot
            }
            SelfControlActionV2::Revert => {
                self.values.field_count() == 0
                    && self
                        .related_receipt_id
                        .as_deref()
                        .is_some_and(valid_identifier)
                    && self.durability == SelfControlDurabilityV2::OneShot
            }
        };
        let durability_shape_valid = match self.durability {
            SelfControlDurabilityV2::Standing | SelfControlDurabilityV2::OneShot => {
                self.control_expires_at_unix_ms.is_none()
            }
            SelfControlDurabilityV2::Lease => self
                .control_expires_at_unix_ms
                .is_some_and(|expiry| expiry > now_unix_ms),
        };
        self.schema == SELF_CONTROL_INTENT_SCHEMA_V2
            && self.actor.is_complete()
            && valid_identifier(&self.intent_id)
            && valid_identifier(&self.target_being)
            && valid_identifier(&self.target_deployment_identity)
            && valid_identifier(&self.authority_scope)
            && valid_identifier(&self.idempotency_key)
            && self.revision > 0
            && self.issued_at_unix_ms <= self.command_expires_at_unix_ms
            && now_unix_ms <= self.command_expires_at_unix_ms
            && self.values.is_well_formed()
            && action_shape_valid
            && durability_shape_valid
            && (!self.values.requires_one_shot()
                || self.durability == SelfControlDurabilityV2::OneShot)
            && (self.action != SelfControlActionV2::Set || self.values.matches_family(self.family))
            && (self.action != SelfControlActionV2::Set
                || (self.family == SelfControlFamilyV2::SharedCoupling)
                    == self.values.includes_shared_coupling())
            && list_is_bounded(&self.evidence_refs)
            && list_is_bounded(&self.success_conditions)
            && list_is_bounded(&self.stop_conditions)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SelfControlAuthorityProofV1 {
    pub schema: String,
    pub authority_class: SelfControlAuthorityClassV2,
    pub signer_being: String,
    pub scope: String,
    pub nonce: String,
    pub signer_public_key_hex: String,
    pub signature_hex: String,
    pub intent_sha256: String,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl SelfControlAuthorityProofV1 {
    #[must_use]
    pub fn signing_bytes(&self, intent: &SelfControlIntentV2) -> Option<Vec<u8>> {
        let statement = SelfControlSigningStatementV1 {
            schema: &self.schema,
            authority_class: self.authority_class,
            signer_being: &self.signer_being,
            scope: &self.scope,
            nonce: &self.nonce,
            signer_public_key_hex: &self.signer_public_key_hex,
            intent_sha256: canonical_self_control_intent_sha256(intent),
            issued_at_unix_ms: self.issued_at_unix_ms,
            expires_at_unix_ms: self.expires_at_unix_ms,
        };
        canonical_json_bytes(&statement)
    }

    #[must_use]
    pub fn verifies(&self, intent: &SelfControlIntentV2, now_unix_ms: u64) -> bool {
        if self.schema != SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1
            || self.authority_class != intent.authority_class
            || self.scope != intent.authority_scope
            || !valid_identifier(&self.signer_being)
            || !valid_identifier(&self.nonce)
            || self.issued_at_unix_ms > self.expires_at_unix_ms
            || self.issued_at_unix_ms < intent.issued_at_unix_ms
            || now_unix_ms > self.expires_at_unix_ms
            || self.expires_at_unix_ms > intent.command_expires_at_unix_ms
            || self.intent_sha256 != canonical_self_control_intent_sha256(intent)
        {
            return false;
        }
        let Ok(public_key): Result<[u8; 32], _> = hex::decode(&self.signer_public_key_hex)
            .and_then(|bytes| {
                bytes
                    .try_into()
                    .map_err(|_| hex::FromHexError::InvalidStringLength)
            })
        else {
            return false;
        };
        let Ok(signature): Result<[u8; 64], _> =
            hex::decode(&self.signature_hex).and_then(|bytes| {
                bytes
                    .try_into()
                    .map_err(|_| hex::FromHexError::InvalidStringLength)
            })
        else {
            return false;
        };
        let Ok(verifying_key) = VerifyingKey::from_bytes(&public_key) else {
            return false;
        };
        let Some(signing_bytes) = self.signing_bytes(intent) else {
            return false;
        };
        verifying_key
            .verify(&signing_bytes, &Signature::from_bytes(&signature))
            .is_ok()
    }
}

#[derive(Serialize)]
struct SelfControlSigningStatementV1<'a> {
    schema: &'a str,
    authority_class: SelfControlAuthorityClassV2,
    signer_being: &'a str,
    scope: &'a str,
    nonce: &'a str,
    signer_public_key_hex: &'a str,
    intent_sha256: String,
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelfControlCommandV2 {
    pub schema: String,
    pub command_id: String,
    pub intent: SelfControlIntentV2,
    pub authority_proofs: Vec<SelfControlAuthorityProofV1>,
}

impl SelfControlCommandV2 {
    #[must_use]
    pub fn is_well_formed(&self, now_unix_ms: u64) -> bool {
        self.schema == SELF_CONTROL_COMMAND_SCHEMA_V2
            && valid_identifier(&self.command_id)
            && self.intent.is_well_formed(now_unix_ms)
            && self.authority_shape_is_valid(now_unix_ms)
    }

    #[must_use]
    pub fn authority_shape_is_valid(&self, now_unix_ms: u64) -> bool {
        if !self
            .authority_proofs
            .iter()
            .all(|proof| proof.verifies(&self.intent, now_unix_ms))
        {
            return false;
        }
        match self.intent.authority_class {
            SelfControlAuthorityClassV2::SelfOwned => {
                self.intent.actor.being == self.intent.target_being
                    && self.intent.family != SelfControlFamilyV2::SharedCoupling
                    && !matches!(
                        self.intent.action,
                        SelfControlActionV2::Hold | SelfControlActionV2::Revert
                    )
                    && self.authority_proofs.len() == 1
                    && self.authority_proofs[0].signer_being == self.intent.actor.being
            }
            SelfControlAuthorityClassV2::Mutual => {
                self.intent.family == SelfControlFamilyV2::SharedCoupling
                    && self.authority_proofs.len() == 2
                    && self.has_exact_signers([
                        self.intent.actor.being.as_str(),
                        self.intent.target_being.as_str(),
                    ])
            }
            SelfControlAuthorityClassV2::SafetySupervisor => {
                self.intent.actor.being == "safety_supervisor"
                    && matches!(
                        self.intent.action,
                        SelfControlActionV2::Hold | SelfControlActionV2::Revert
                    )
                    && self.authority_proofs.len() == 1
                    && self.authority_proofs[0].signer_being == "safety_supervisor"
            }
        }
    }

    fn has_exact_signers(&self, required: [&str; 2]) -> bool {
        required.iter().all(|required_signer| {
            self.authority_proofs
                .iter()
                .any(|proof| proof.signer_being == *required_signer)
        }) && self.authority_proofs[0].signer_being != self.authority_proofs[1].signer_being
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelfControlReceiptStatusV2 {
    Applied,
    Duplicate,
    Rejected,
    RevisionConflict,
    Expired,
    Withdrawn,
    SafetyHeld,
    RolledBack,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelfControlReceiptV2 {
    pub schema: String,
    pub receipt_id: String,
    pub command_id: String,
    pub intent_id: String,
    pub idempotency_key: String,
    pub status: SelfControlReceiptStatusV2,
    pub requested_revision: u64,
    pub resulting_revision: u64,
    pub target_being: String,
    pub target_deployment_identity: String,
    pub requested_values: SelfControlValuesV2,
    pub clamped_values: SelfControlValuesV2,
    pub applied_values: SelfControlValuesV2,
    pub previous_values: SelfControlValuesV2,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub previous_automatic_fields: Vec<String>,
    pub received_at_unix_ms: u64,
    pub completed_at_unix_ms: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub control_expires_at_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rollback_receipt_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    pub server_process_identity: String,
    pub server_deployment_identity: String,
    pub felt_effect_established: bool,
}

impl SelfControlReceiptV2 {
    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        self.schema == SELF_CONTROL_RECEIPT_SCHEMA_V2
            && valid_identifier(&self.receipt_id)
            && valid_identifier(&self.command_id)
            && valid_identifier(&self.intent_id)
            && valid_identifier(&self.idempotency_key)
            && valid_identifier(&self.target_being)
            && valid_identifier(&self.target_deployment_identity)
            && valid_identifier(&self.server_process_identity)
            && valid_identifier(&self.server_deployment_identity)
            && self.completed_at_unix_ms >= self.received_at_unix_ms
            && self.requested_values.is_well_formed()
            && self.clamped_values.is_well_formed()
            && self.applied_values.is_well_formed()
            && self.previous_values.is_well_formed()
            && list_is_bounded(&self.previous_automatic_fields)
            && !self.felt_effect_established
    }
}

#[must_use]
pub fn canonical_self_control_intent_sha256(intent: &SelfControlIntentV2) -> String {
    let bytes = canonical_json_bytes(intent).unwrap_or_default();
    format!("{:x}", Sha256::digest(bytes))
}

#[must_use]
pub fn canonical_self_control_command_sha256(command: &SelfControlCommandV2) -> String {
    let bytes = canonical_json_bytes(command).unwrap_or_default();
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn canonical_json_value_sha256(value: &Value) -> String {
    let mut value = value.clone();
    canonicalize_json(&mut value);
    let bytes = serde_json::to_vec(&value).unwrap_or_default();
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn canonical_json_bytes<T: Serialize>(value: &T) -> Option<Vec<u8>> {
    let mut value = serde_json::to_value(value).ok()?;
    canonicalize_json(&mut value);
    serde_json::to_vec(&value).ok()
}

fn canonicalize_json(value: &mut Value) {
    match value {
        Value::Object(fields) => {
            let mut ordered = fields
                .iter_mut()
                .map(|(key, child)| {
                    canonicalize_json(child);
                    (key.clone(), child.take())
                })
                .collect::<Vec<_>>();
            ordered.sort_by(|left, right| left.0.cmp(&right.0));
            fields.clear();
            fields.extend(ordered);
        }
        Value::Array(values) => {
            for child in values {
                canonicalize_json(child);
            }
        }
        _ => {}
    }
}

fn value_is_finite(value: &Value) -> bool {
    match value {
        Value::Number(number) => number.as_f64().is_some_and(f64::is_finite),
        Value::Array(values) => values.iter().all(value_is_finite),
        Value::Object(fields) => fields.values().all(value_is_finite),
        _ => true,
    }
}

fn self_control_field_allowed(family: SelfControlFamilyV2, field: &str) -> bool {
    match family {
        SelfControlFamilyV2::Conversation => matches!(
            field,
            "conversation_temperature"
                | "response_token_limit"
                | "aperture"
                | "continuity_readout"
                | "generation_noise"
        ),
        SelfControlFamilyV2::SemanticContinuity => field == "semantic_strand_retention_turns",
        SelfControlFamilyV2::SemanticEmission => matches!(
            field,
            "semantic_emission_gain"
                | "vibrancy_aperture"
                | "codec_dimension_weights"
                | "warmth_intensity"
                | "hebbian_learning_rate_scale"
        ),
        SelfControlFamilyV2::Memory => matches!(
            field,
            "memory_mode"
                | "journal_resonance"
                | "checkpoint_interval"
                | "embedding_strength"
                | "memory_decay_rate"
                | "transition_cushion"
                | "checkpoint_annotation"
                | "checkpoint_now"
        ),
        SelfControlFamilyV2::SensoryIntake => matches!(
            field,
            "semantic_companion_mix"
                | "semantic_intake_gain"
                | "peer_journal_visible"
                | "peer_breathing_coupled"
                | "receptivity"
                | "local_sensory_admission"
                | "live_audio_enabled"
                | "live_video_enabled"
        ),
        SelfControlFamilyV2::ReservoirRegulation => matches!(
            field,
            "synth_gain"
                | "keep_bias"
                | "exploration_noise"
                | "fill_target"
                | "regulation_strength"
                | "smoothing_preference"
                | "penalty_sensitivity"
                | "breathing_rate_scale"
                | "deep_breathing"
                | "synth_noise_level"
                | "pure_tone"
                | "legacy_audio_synth"
                | "legacy_video_synth"
        ),
        SelfControlFamilyV2::ReservoirGeometry => {
            matches!(
                field,
                "geom_curiosity" | "target_lambda_bias" | "geom_drive"
            )
        }
        SelfControlFamilyV2::PiController => matches!(
            field,
            "pi_kp" | "pi_ki" | "pi_max_step" | "pi_geom_weight" | "pi_integrator_leak"
        ),
        SelfControlFamilyV2::LocalTopology => matches!(
            field,
            "porosity"
                | "esn_leak_override"
                | "esn_leak_override_ticks"
                | "mode_disperse"
                | "mode_disperse_duration_ticks"
                | "mode_disperse_decay_ticks"
        ),
        SelfControlFamilyV2::SharedCoupling => matches!(
            field,
            "peer_breathing_coupled"
                | "shared_sensory_admission"
                | "shadow_influence_gain"
                | "cross_being_semantic_gain"
        ),
    }
}

fn valid_identifier(value: &str) -> bool {
    let value = value.trim();
    !value.is_empty() && value.len() <= 256
}

fn valid_bounded_text(value: &str) -> bool {
    value.len() <= 2_048
}

fn list_is_bounded(values: &[String]) -> bool {
    values.len() <= 64 && values.iter().all(|value| valid_bounded_text(value))
}
