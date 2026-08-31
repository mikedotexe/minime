//! Signed deployment hand-off: carries Minime's persisted self-control state
//! across a rebuild without ever loosening the fail-closed stale-deployment
//! refusal. Ported from Astrid's bridge (self_control_v2/deployment_handoff.rs)
//! with minime-shaped bindings: no build manifest exists here, so the receipt
//! binds the target deployment identity, the canonical executable path, and
//! the executable's sha256 directly.
//!
//! The signer is the dedicated `deployment_steward` being. Its pinned key can
//! sign NOTHING but hand-offs: the runtime structurally rejects any live
//! command whose actor or proof signer is `deployment_steward`
//! ("deployment_steward_has_no_command_authority" in `process`), so state
//! lineage authority never leaks into Hold/Revert/Set — or future
//! shared-coupling — authority.

use std::fs;
use std::path::{Path, PathBuf};

use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};

use crate::self_control_identity::{key_id, SelfControlOwnerSigner, DEPLOYMENT_STEWARD_BEING};
use crate::self_control_wire::canonical_json_bytes;

use super::{storage, RuntimeStateEnvelopeV1, RuntimeStateV2, TARGET_BEING};

const HANDOFF_SCHEMA: &str = "minime.self_control.deployment_handoff.v1";
const APPLIED_SCHEMA: &str = "minime.self_control.deployment_handoff_applied.v1";
const PREPARE_RESULT_SCHEMA: &str = "minime.self_control.deployment_handoff_prepare_result.v1";
const HANDOFF_AUTHORITY: &str = "state_lineage_only_no_control_authority";
const HANDOFF_ID_PREFIX: &str = "minime-self-control-handoff:";
const HANDOFF_TTL_MS: u64 = 900_000;
const PENDING_FILENAME: &str = "deployment_handoff.pending.json";

#[derive(Clone, Debug, Deserialize, Serialize)]
struct SignedDeploymentHandoffV1 {
    schema: String,
    handoff_id: String,
    target_being: String,
    from_deployment_identity: String,
    to_deployment_identity: String,
    from_state_sha256: String,
    target_executable_path: String,
    target_binary_sha256: String,
    operator_actor: String,
    operator_ack_sha256: String,
    prepared_at_unix_ms: u64,
    expires_at_unix_ms: u64,
    signer_being: String,
    signer_key_id: String,
    signer_public_key_hex: String,
    authority: String,
    signature_hex: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct AppliedDeploymentHandoffV1 {
    schema: String,
    handoff: SignedDeploymentHandoffV1,
    result_state_sha256: String,
    consumed_at_unix_ms: u64,
    recovered_after_state_persist: bool,
    state_fields_preserved_except_deployment_identity: bool,
    authority: String,
}

/// What this running binary IS: the deployment identity it was opened with,
/// plus the canonicalized executable path and its sha256.
#[derive(Clone, Debug)]
pub(super) struct DeploymentBinding {
    pub(super) identity: String,
    pub(super) executable_path: String,
    pub(super) binary_sha256: String,
}

impl DeploymentBinding {
    pub(super) fn current(deployment_identity: &str) -> Result<Self, String> {
        let executable = std::env::current_exe()
            .map_err(|error| format!("resolve current minime executable: {error}"))?;
        Self::for_executable(deployment_identity, &executable)
    }

    fn for_executable(deployment_identity: &str, executable: &Path) -> Result<Self, String> {
        if deployment_identity.trim().is_empty() {
            return Err("deployment identity is empty".to_string());
        }
        let executable = executable.canonicalize().map_err(|error| {
            format!(
                "resolve minime executable {}: {error}",
                executable.display()
            )
        })?;
        let bytes = fs::read(&executable)
            .map_err(|error| format!("read {}: {error}", executable.display()))?;
        Ok(Self {
            identity: deployment_identity.to_string(),
            executable_path: executable.display().to_string(),
            binary_sha256: sha256_bytes(&bytes),
        })
    }
}

impl SignedDeploymentHandoffV1 {
    /// Canonical-JSON signing bytes (signature cleared), so the statement is
    /// stable across struct field order.
    fn signing_bytes(&self) -> Result<Vec<u8>, String> {
        let mut unsigned = self.clone();
        unsigned.signature_hex.clear();
        canonical_json_bytes(&unsigned)
            .ok_or_else(|| "encode deployment hand-off signing statement".to_string())
    }

    fn expected_id(&self) -> Result<String, String> {
        let preimage = serde_json::json!({
            "from_deployment_identity": self.from_deployment_identity,
            "to_deployment_identity": self.to_deployment_identity,
            "from_state_sha256": self.from_state_sha256,
            "target_executable_path": self.target_executable_path,
            "target_binary_sha256": self.target_binary_sha256,
            "operator_actor": self.operator_actor,
            "operator_ack_sha256": self.operator_ack_sha256,
            "prepared_at_unix_ms": self.prepared_at_unix_ms,
        });
        let bytes = canonical_json_bytes(&preimage)
            .ok_or_else(|| "encode deployment hand-off identity".to_string())?;
        let digest = sha256_bytes(&bytes);
        Ok(format!("{HANDOFF_ID_PREFIX}{}", &digest[..32]))
    }
}

/// Prepare (or idempotently return) the signed hand-off carrying the persisted
/// state to `binding`. Returns structured JSON: `status` is one of
/// `prepared | already_current | not_needed`; a pending hand-off that can no
/// longer be consumed (expired, rebound binary, changed state, undecodable) is
/// quarantined to a `deployment_handoff.refused.<ts>.json` evidence file and
/// replaced, named in `replaced_pending_reason` — never a deadlocked deploy.
pub(super) fn prepare_at(
    root: &Path,
    binding: &DeploymentBinding,
    operator_actor: &str,
    operator_ack: &str,
    now: u64,
) -> Result<Value, String> {
    validate_operator_text(operator_actor, "operator actor", 128)?;
    validate_operator_text(operator_ack, "operator acknowledgement", 1_024)?;
    let Some(envelope) = storage::read_json::<RuntimeStateEnvelopeV1>(&root.join("state.json"))?
    else {
        return Ok(prepare_result("not_needed", false, None, Value::Null));
    };
    let state = super::verify_state_envelope_integrity(envelope)?;
    if state.deployment_identity == binding.identity {
        return Ok(prepare_result("already_current", false, None, Value::Null));
    }
    let from_state_sha256 = super::state_sha256(&state)?;
    let operator_ack_sha256 = sha256_bytes(operator_ack.as_bytes());
    let pending_path = root.join(PENDING_FILENAME);
    let mut replaced_pending_reason = None;
    let existing = match storage::read_json::<SignedDeploymentHandoffV1>(&pending_path) {
        Ok(existing) => existing,
        Err(reason) => {
            // An undecodable pending is the most-broken kind of unconsumable:
            // preserve the bytes as evidence, then let prepare heal the lane.
            quarantine_pending(root, &format!("undecodable: {reason}"), now)?;
            replaced_pending_reason = Some(format!("undecodable pending quarantined: {reason}"));
            None
        }
    };
    if let Some(existing) = existing {
        match pending_is_consumable(root, &existing, binding, &state, &from_state_sha256, now) {
            Ok(()) => {
                if existing.operator_actor == operator_actor
                    && existing.operator_ack_sha256 == operator_ack_sha256
                {
                    let handoff = serde_json::to_value(existing)
                        .map_err(|error| format!("encode existing deployment hand-off: {error}"))?;
                    return Ok(prepare_result("prepared", true, None, handoff));
                }
                return Err("a different consumable deployment hand-off already exists".to_string());
            }
            Err(reason) => {
                quarantine_pending(root, &reason, now)?;
                replaced_pending_reason = Some(reason);
            }
        }
    }

    let signer = load_pinned_steward_signer(root)?;
    let mut handoff = SignedDeploymentHandoffV1 {
        schema: HANDOFF_SCHEMA.to_string(),
        handoff_id: String::new(),
        target_being: TARGET_BEING.to_string(),
        from_deployment_identity: state.deployment_identity.clone(),
        to_deployment_identity: binding.identity.clone(),
        from_state_sha256,
        target_executable_path: binding.executable_path.clone(),
        target_binary_sha256: binding.binary_sha256.clone(),
        operator_actor: operator_actor.to_string(),
        operator_ack_sha256,
        prepared_at_unix_ms: now,
        expires_at_unix_ms: now
            .checked_add(HANDOFF_TTL_MS)
            .ok_or_else(|| "deployment hand-off expiry overflow".to_string())?,
        signer_being: DEPLOYMENT_STEWARD_BEING.to_string(),
        signer_key_id: signer.key_id().to_string(),
        signer_public_key_hex: signer.public_key_hex().to_string(),
        authority: HANDOFF_AUTHORITY.to_string(),
        signature_hex: String::new(),
    };
    handoff.handoff_id = handoff.expected_id()?;
    handoff.signature_hex = signer.sign_hex(&handoff.signing_bytes()?);
    verify_handoff(root, &handoff, binding, now, true)?;
    storage::write_owner_json(&pending_path, &handoff)?;
    let handoff = serde_json::to_value(handoff)
        .map_err(|error| format!("encode prepared deployment hand-off: {error}"))?;
    Ok(prepare_result(
        "prepared",
        false,
        replaced_pending_reason,
        handoff,
    ))
}

/// Consume a pending hand-off at startup: verify it binds THIS binary and the
/// EXACT persisted state, then rewrite only the deployment identity.
pub(super) fn consume_pending_at(
    root: &Path,
    binding: &DeploymentBinding,
    state: &mut RuntimeStateV2,
    now: u64,
) -> Result<bool, String> {
    let Some(handoff) =
        storage::read_json::<SignedDeploymentHandoffV1>(&root.join(PENDING_FILENAME))?
    else {
        return Ok(false);
    };
    verify_handoff(root, &handoff, binding, now, true)?;
    if handoff.from_deployment_identity != state.deployment_identity
        || handoff.to_deployment_identity != binding.identity
        || handoff.from_state_sha256 != super::state_sha256(state)?
    {
        return Err(
            "deployment hand-off does not bind the exact persisted state transition".to_string(),
        );
    }
    state.deployment_identity.clone_from(&binding.identity);
    super::persist_state_at(root, state)?;
    write_applied(root, state, handoff, now, false)?;
    Ok(true)
}

/// Already-current startup path: a leftover pending hand-off is either the
/// evidence tail of a crash between consume-persist and receipt-write (turn it
/// into an applied receipt), an already-finalized duplicate (remove it),
/// mis-bound noise (leave it; `prepare` replaces unconsumable pendings), or a
/// verified pending whose state-preservation re-hash no longer holds — which a
/// benignly orphaned pending can reach once the state moves, so it is
/// quarantined loudly as evidence rather than treated as fatal tamper. The
/// state file protects itself (envelope hash + deployment check); nothing on
/// this path may cost the being her self-control availability.
pub(super) fn finalize_completed_for_current(
    root: &Path,
    state: &RuntimeStateV2,
    deployment_identity: &str,
    now: u64,
) -> Result<(), String> {
    let handoff =
        match storage::read_json::<SignedDeploymentHandoffV1>(&root.join(PENDING_FILENAME)) {
            Ok(Some(handoff)) => handoff,
            Ok(None) => return Ok(()),
            Err(note) => {
                eprintln!(
                    "self-control: unreadable pending deployment hand-off left in place: {note}"
                );
                return Ok(());
            }
        };
    let binding = match DeploymentBinding::current(deployment_identity) {
        Ok(binding) => binding,
        Err(note) => {
            eprintln!(
                "self-control: cannot bind current executable to finalize deployment hand-off: {note}"
            );
            return Ok(());
        }
    };
    finalize_completed_at(root, &binding, state, now, handoff)
}

fn finalize_completed_at(
    root: &Path,
    binding: &DeploymentBinding,
    state: &RuntimeStateV2,
    now: u64,
    handoff: SignedDeploymentHandoffV1,
) -> Result<(), String> {
    if verify_handoff(root, &handoff, binding, now, false).is_err()
        || handoff.to_deployment_identity != binding.identity
        || state.deployment_identity != binding.identity
    {
        eprintln!(
            "self-control: pending deployment hand-off is bound to different evidence; \
             leaving it for prepare to replace"
        );
        return Ok(());
    }
    if let Ok(Some(existing)) =
        storage::read_json::<AppliedDeploymentHandoffV1>(&applied_receipt_path(root, &handoff)?)
    {
        if existing.handoff.handoff_id == handoff.handoff_id {
            // Crash landed between receipt-write and pending-removal, and the
            // state may have legitimately moved since; the receipt already
            // proves the hand-off. Just clear the stale pending.
            return storage::remove_owner_file(&root.join(PENDING_FILENAME));
        }
    }
    let mut prior = state.clone();
    prior
        .deployment_identity
        .clone_from(&handoff.from_deployment_identity);
    if super::state_sha256(&prior)? != handoff.from_state_sha256 {
        // A crash-orphaned pending whose state has since legitimately moved
        // lands here (no applied receipt was ever written). Failing closed
        // would disable her self-control over leftover evidence; quarantine
        // the file loudly instead — the state envelope protects itself.
        return quarantine_pending(
            root,
            "verified pending cannot re-prove state preservation after restart \
             (orphaned by a crash boundary, or tampered)",
            now,
        );
    }
    write_applied(root, state, handoff, now, true)
}

/// Move a no-longer-consumable pending aside as evidence instead of deleting
/// or overwriting it, and say so loudly.
fn quarantine_pending(root: &Path, reason: &str, now: u64) -> Result<(), String> {
    let pending = root.join(PENDING_FILENAME);
    let refused = root.join(format!("deployment_handoff.refused.{now}.json"));
    match fs::rename(&pending, &refused) {
        Ok(()) => {
            storage::sync_parent(root)?;
            eprintln!(
                "self-control: quarantined pending deployment hand-off to {}: {reason}",
                refused.display()
            );
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!(
            "quarantine pending deployment hand-off {}: {error}",
            pending.display()
        )),
    }
}

/// Read-only view of any pending hand-off for `verified_status`.
pub(super) fn pending_summary(root: &Path) -> Value {
    match storage::read_json::<SignedDeploymentHandoffV1>(&root.join(PENDING_FILENAME)) {
        Ok(Some(handoff)) => serde_json::json!({
            "handoff_id": handoff.handoff_id,
            "from_deployment_identity": handoff.from_deployment_identity,
            "to_deployment_identity": handoff.to_deployment_identity,
            "target_binary_sha256": handoff.target_binary_sha256,
            "prepared_at_unix_ms": handoff.prepared_at_unix_ms,
            "expires_at_unix_ms": handoff.expires_at_unix_ms,
            "operator_actor": handoff.operator_actor,
        }),
        Ok(None) => Value::Null,
        Err(error) => serde_json::json!({ "unreadable": error }),
    }
}

fn pending_is_consumable(
    root: &Path,
    handoff: &SignedDeploymentHandoffV1,
    binding: &DeploymentBinding,
    state: &RuntimeStateV2,
    from_state_sha256: &str,
    now: u64,
) -> Result<(), String> {
    verify_handoff(root, handoff, binding, now, true)?;
    if handoff.from_deployment_identity != state.deployment_identity
        || handoff.to_deployment_identity != binding.identity
        || handoff.from_state_sha256 != from_state_sha256
    {
        return Err("pending hand-off does not bind the current persisted state".to_string());
    }
    Ok(())
}

fn write_applied(
    root: &Path,
    state: &RuntimeStateV2,
    handoff: SignedDeploymentHandoffV1,
    now: u64,
    recovered_after_state_persist: bool,
) -> Result<(), String> {
    let applied_path = applied_receipt_path(root, &handoff)?;
    let applied = AppliedDeploymentHandoffV1 {
        schema: APPLIED_SCHEMA.to_string(),
        handoff,
        result_state_sha256: super::state_sha256(state)?,
        consumed_at_unix_ms: now,
        recovered_after_state_persist,
        state_fields_preserved_except_deployment_identity: true,
        authority: HANDOFF_AUTHORITY.to_string(),
    };
    match storage::read_json::<AppliedDeploymentHandoffV1>(&applied_path)? {
        Some(existing)
            if existing.handoff.handoff_id != applied.handoff.handoff_id
                || existing.result_state_sha256 != applied.result_state_sha256 =>
        {
            return Err(
                "applied deployment hand-off receipt conflicts with existing evidence".to_string(),
            );
        }
        Some(_) => {}
        None => storage::write_owner_json(&applied_path, &applied)?,
    }
    storage::remove_owner_file(&root.join(PENDING_FILENAME))
}

fn applied_receipt_path(
    root: &Path,
    handoff: &SignedDeploymentHandoffV1,
) -> Result<PathBuf, String> {
    let suffix = handoff
        .handoff_id
        .strip_prefix(HANDOFF_ID_PREFIX)
        .ok_or_else(|| "deployment hand-off id is malformed".to_string())?;
    Ok(root
        .join("deployment_handoffs/applied")
        .join(format!("{suffix}.json")))
}

fn verify_handoff(
    root: &Path,
    handoff: &SignedDeploymentHandoffV1,
    binding: &DeploymentBinding,
    now: u64,
    enforce_expiry: bool,
) -> Result<(), String> {
    if handoff.schema != HANDOFF_SCHEMA
        || handoff.target_being != TARGET_BEING
        || handoff.signer_being != DEPLOYMENT_STEWARD_BEING
        || handoff.authority != HANDOFF_AUTHORITY
        || handoff.from_deployment_identity == handoff.to_deployment_identity
        || handoff.to_deployment_identity != binding.identity
        || handoff.target_executable_path != binding.executable_path
        || handoff.target_binary_sha256 != binding.binary_sha256
        || handoff.handoff_id != handoff.expected_id()?
        || handoff.expires_at_unix_ms
            != handoff
                .prepared_at_unix_ms
                .checked_add(HANDOFF_TTL_MS)
                .ok_or_else(|| "deployment hand-off expiry overflow".to_string())?
        || !is_sha256(&handoff.from_state_sha256)
        || !is_sha256(&handoff.operator_ack_sha256)
        || handoff.operator_actor.is_empty()
    {
        return Err("deployment hand-off is malformed or bound to different evidence".to_string());
    }
    if handoff.prepared_at_unix_ms > now || (enforce_expiry && now > handoff.expires_at_unix_ms) {
        return Err("deployment hand-off is not current".to_string());
    }

    let trust = super::load_trust_at(root)?;
    let pinned = trust
        .pinned_public_keys
        .get(DEPLOYMENT_STEWARD_BEING)
        .ok_or_else(|| "deployment steward hand-off key is not pinned".to_string())?;
    if handoff.signer_public_key_hex != *pinned
        || handoff.signer_key_id != key_id(&handoff.signer_public_key_hex)
    {
        return Err("deployment hand-off signer key is not trusted".to_string());
    }
    let public_key: [u8; 32] = hex::decode(&handoff.signer_public_key_hex)
        .map_err(|error| format!("decode deployment hand-off public key: {error}"))?
        .try_into()
        .map_err(|_| "deployment hand-off public key has the wrong length".to_string())?;
    let signature: [u8; 64] = hex::decode(&handoff.signature_hex)
        .map_err(|error| format!("decode deployment hand-off signature: {error}"))?
        .try_into()
        .map_err(|_| "deployment hand-off signature has the wrong length".to_string())?;
    VerifyingKey::from_bytes(&public_key)
        .map_err(|error| format!("parse deployment hand-off public key: {error}"))?
        .verify_strict(
            &handoff.signing_bytes()?,
            &Signature::from_bytes(&signature),
        )
        .map_err(|_| "deployment hand-off signature is invalid".to_string())
}

fn load_pinned_steward_signer(root: &Path) -> Result<SelfControlOwnerSigner, String> {
    let signer = SelfControlOwnerSigner::load_deployment_steward(root).map_err(|error| {
        format!(
            "deployment steward identity is unavailable; provision it with \
             `minime self-control provision --deployment-steward` ({error})"
        )
    })?;
    let trust = super::load_trust_at(root)?;
    if trust
        .pinned_public_keys
        .get(DEPLOYMENT_STEWARD_BEING)
        .map(String::as_str)
        != Some(signer.public_key_hex())
    {
        return Err("deployment steward hand-off key is not pinned".to_string());
    }
    Ok(signer)
}

fn prepare_result(
    status: &str,
    idempotent: bool,
    replaced_pending_reason: Option<String>,
    handoff: Value,
) -> Value {
    serde_json::json!({
        "schema": PREPARE_RESULT_SCHEMA,
        "status": status,
        "idempotent": idempotent,
        "replaced_pending_reason": replaced_pending_reason,
        "handoff": handoff,
        "authority": HANDOFF_AUTHORITY,
    })
}

fn validate_operator_text(value: &str, label: &str, max_len: usize) -> Result<(), String> {
    if value.trim() != value
        || value.is_empty()
        || value.len() > max_len
        || value.chars().any(char::is_control)
    {
        return Err(format!("deployment hand-off {label} is empty or malformed"));
    }
    Ok(())
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::TempDir;

    use super::*;
    use crate::self_control_identity::{
        provision_deployment_steward_identity, provision_minime_owner_identity,
    };
    use crate::self_control_wire::SelfControlValuesV2;

    const NOW: u64 = 100_000;
    const FROM: &str = "minime-source:prior0000";
    const TO: &str = "minime-source:next00000";

    fn fixture() -> (TempDir, DeploymentBinding, RuntimeStateV2) {
        let temp = TempDir::new().unwrap();
        let root = temp.path().to_path_buf();
        provision_minime_owner_identity(&root, false, NOW).unwrap();
        provision_deployment_steward_identity(&root, false, NOW).unwrap();
        let binary = root.join("minime-fixture-binary");
        fs::write(&binary, b"fixture minime engine binary").unwrap();
        let binding = DeploymentBinding::for_executable(TO, &binary).unwrap();
        let mut state = RuntimeStateV2::new(FROM.to_string());
        state.preferences = SelfControlValuesV2 {
            geom_drive: Some(0.4),
            exploration_noise: Some(0.12),
            ..SelfControlValuesV2::default()
        };
        state
            .revision_by_family
            .insert("reservoir_geometry".to_string(), 3);
        super::super::persist_state_at(&root, &state).unwrap();
        (temp, binding, state)
    }

    fn prepare_fixture(root: &std::path::Path, binding: &DeploymentBinding) -> Value {
        prepare_at(
            root,
            binding,
            "mike-operator",
            "approved exact deployment-lineage hand-off",
            NOW,
        )
        .unwrap()
    }

    #[test]
    fn signed_handoff_preserves_exact_state_except_deployment_identity() {
        let (temp, binding, mut state) = fixture();
        let root = temp.path();
        let before = state.clone();
        let result = prepare_fixture(root, &binding);
        assert_eq!(result["status"], "prepared");
        assert_eq!(result["idempotent"], false);

        assert!(consume_pending_at(root, &binding, &mut state, NOW + 1).unwrap());
        assert_eq!(state.deployment_identity, binding.identity);
        let mut restored = state.clone();
        restored
            .deployment_identity
            .clone_from(&before.deployment_identity);
        assert_eq!(
            super::super::state_sha256(&restored).unwrap(),
            super::super::state_sha256(&before).unwrap()
        );
        assert!(!root.join(PENDING_FILENAME).exists());
        let applied_dir = root.join("deployment_handoffs/applied");
        assert_eq!(fs::read_dir(&applied_dir).unwrap().count(), 1);
        let applied_path = fs::read_dir(&applied_dir).unwrap().next().unwrap().unwrap();
        let applied: AppliedDeploymentHandoffV1 =
            storage::read_json(&applied_path.path()).unwrap().unwrap();
        assert!(!applied.recovered_after_state_persist);
        assert!(applied.state_fields_preserved_except_deployment_identity);
    }

    #[test]
    fn handoff_rejects_state_or_signature_tampering() {
        let (temp, binding, mut state) = fixture();
        let root = temp.path();
        prepare_fixture(root, &binding);

        state.preferences.geom_drive = Some(0.9);
        assert!(consume_pending_at(root, &binding, &mut state, NOW + 1)
            .unwrap_err()
            .contains("exact persisted state"));

        let mut handoff: SignedDeploymentHandoffV1 =
            storage::read_json(&root.join(PENDING_FILENAME))
                .unwrap()
                .unwrap();
        let tampered = if handoff.signature_hex.starts_with("00") {
            "11"
        } else {
            "00"
        };
        handoff.signature_hex.replace_range(0..2, tampered);
        assert!(verify_handoff(root, &handoff, &binding, NOW + 1, true)
            .unwrap_err()
            .contains("signature"));
    }

    #[test]
    fn undecodable_pending_is_quarantined_and_prepare_heals() {
        let (temp, binding, _state) = fixture();
        let root = temp.path();
        fs::write(root.join(PENDING_FILENAME), b"{ truncated garbage").unwrap();

        let healed = prepare_fixture(root, &binding);
        assert_eq!(healed["status"], "prepared");
        assert!(healed["replaced_pending_reason"]
            .as_str()
            .unwrap()
            .contains("undecodable"));
        let quarantined = fs::read_dir(root)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("deployment_handoff.refused.")
            })
            .count();
        assert_eq!(
            quarantined, 1,
            "the broken pending must survive as evidence"
        );
        let fresh: SignedDeploymentHandoffV1 = storage::read_json(&root.join(PENDING_FILENAME))
            .unwrap()
            .unwrap();
        assert_eq!(fresh.to_deployment_identity, binding.identity);
    }

    #[test]
    fn orphaned_pending_with_moved_state_is_quarantined_not_fatal() {
        let (temp, binding, mut state) = fixture();
        let root = temp.path();
        prepare_fixture(root, &binding);
        let handoff: SignedDeploymentHandoffV1 = storage::read_json(&root.join(PENDING_FILENAME))
            .unwrap()
            .unwrap();
        // Crash boundary: consume persisted the new identity but never wrote
        // the applied receipt — and the state then legitimately moved.
        state.deployment_identity.clone_from(&binding.identity);
        state.preferences.exploration_noise = Some(0.2);
        super::super::persist_state_at(root, &state).unwrap();

        finalize_completed_at(root, &binding, &state, NOW + 2, handoff)
            .expect("a stale orphan must never cost her self-control availability");
        assert!(!root.join(PENDING_FILENAME).exists());
        let quarantined = fs::read_dir(root)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("deployment_handoff.refused.")
            })
            .count();
        assert_eq!(quarantined, 1, "the orphan must survive as evidence");
    }

    #[test]
    fn handoff_rejects_expiry_and_rebound_binary() {
        let (temp, binding, mut state) = fixture();
        let root = temp.path();
        prepare_fixture(root, &binding);
        let handoff: SignedDeploymentHandoffV1 = storage::read_json(&root.join(PENDING_FILENAME))
            .unwrap()
            .unwrap();
        assert!(
            verify_handoff(root, &handoff, &binding, NOW + HANDOFF_TTL_MS + 1, true)
                .unwrap_err()
                .contains("not current")
        );

        let binary = root.join("minime-fixture-binary");
        fs::write(&binary, b"a different rebuilt binary").unwrap();
        let rebound = DeploymentBinding::for_executable(TO, &binary).unwrap();
        assert!(consume_pending_at(root, &rebound, &mut state, NOW + 1)
            .unwrap_err()
            .contains("bound to different evidence"));
    }

    #[test]
    fn preparation_is_idempotent_and_replaces_only_unconsumable_pending() {
        let (temp, binding, _state) = fixture();
        let root = temp.path();
        let first = prepare_fixture(root, &binding);
        let retry = prepare_at(
            root,
            &binding,
            "mike-operator",
            "approved exact deployment-lineage hand-off",
            NOW + 1,
        )
        .unwrap();
        assert_eq!(retry["status"], "prepared");
        assert_eq!(retry["idempotent"], true);
        assert_eq!(
            retry["handoff"]["handoff_id"],
            first["handoff"]["handoff_id"]
        );

        assert!(prepare_at(
            root,
            &binding,
            "mike-operator",
            "a different acknowledgement",
            NOW + 1,
        )
        .unwrap_err()
        .contains("different consumable"));

        let late = NOW + HANDOFF_TTL_MS + 10;
        let replaced = prepare_at(
            root,
            &binding,
            "mike-operator",
            "approved exact deployment-lineage hand-off",
            late,
        )
        .unwrap();
        assert_eq!(replaced["status"], "prepared");
        assert_eq!(replaced["idempotent"], false);
        assert!(replaced["replaced_pending_reason"]
            .as_str()
            .unwrap()
            .contains("not current"));
        assert_ne!(
            replaced["handoff"]["handoff_id"],
            first["handoff"]["handoff_id"]
        );
    }

    #[test]
    fn completed_state_can_finalize_receipt_after_a_crash_boundary() {
        let (temp, binding, mut state) = fixture();
        let root = temp.path();
        prepare_fixture(root, &binding);
        let handoff: SignedDeploymentHandoffV1 = storage::read_json(&root.join(PENDING_FILENAME))
            .unwrap()
            .unwrap();
        state.deployment_identity.clone_from(&binding.identity);
        super::super::persist_state_at(root, &state).unwrap();

        finalize_completed_at(root, &binding, &state, NOW + HANDOFF_TTL_MS + 1, handoff).unwrap();
        assert!(!root.join(PENDING_FILENAME).exists());
        let applied_path = fs::read_dir(root.join("deployment_handoffs/applied"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path();
        let applied: AppliedDeploymentHandoffV1 =
            storage::read_json(&applied_path).unwrap().unwrap();
        assert!(applied.recovered_after_state_persist);
        assert!(applied.state_fields_preserved_except_deployment_identity);
    }

    #[test]
    fn preparation_requires_explicit_bounded_operator_evidence() {
        let (temp, binding, _state) = fixture();
        let root = temp.path();
        assert!(prepare_at(root, &binding, "", "approved", NOW)
            .unwrap_err()
            .contains("operator actor"));
        assert!(prepare_at(root, &binding, "mike", "", NOW)
            .unwrap_err()
            .contains("operator acknowledgement"));
    }

    #[test]
    fn prepare_reports_not_needed_and_already_current() {
        let (temp, binding, state) = fixture();
        let root = temp.path();

        let mut current = state.clone();
        current.deployment_identity.clone_from(&binding.identity);
        super::super::persist_state_at(root, &current).unwrap();
        let already = prepare_fixture(root, &binding);
        assert_eq!(already["status"], "already_current");

        fs::remove_file(root.join("state.json")).unwrap();
        let missing = prepare_fixture(root, &binding);
        assert_eq!(missing["status"], "not_needed");
    }

    #[test]
    fn prepare_refuses_without_pinned_steward_key() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().to_path_buf();
        provision_minime_owner_identity(&root, false, NOW).unwrap();
        let binary = root.join("minime-fixture-binary");
        fs::write(&binary, b"fixture minime engine binary").unwrap();
        let binding = DeploymentBinding::for_executable(TO, &binary).unwrap();
        let state = RuntimeStateV2::new(FROM.to_string());
        super::super::persist_state_at(&root, &state).unwrap();

        assert!(
            prepare_at(&root, &binding, "mike-operator", "approved", NOW)
                .unwrap_err()
                .contains("deployment steward")
        );
    }
}
