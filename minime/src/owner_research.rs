//! Canonical Owner Research lifecycle signing through Minime's owner key.

use std::path::Path;

use ed25519_dalek::{Signature, Verifier as _, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};

use crate::{
    self_control_identity::SelfControlOwnerSigner,
    self_control_wire::{canonical_json_bytes, canonical_json_value_sha256},
};

const RECEIPT_SCHEMA: &str = "volition.signed_owner_research_receipt.v1";
const OWNER_BEING: &str = "minime";
const PAYLOAD_KINDS: &[&str] = &[
    "session",
    "evidence_graph",
    "decision_plan",
    "capability_manifest",
    "lifecycle_event",
    "action_outcome",
];

pub struct SignOwnerResearchOptions<'a> {
    pub root: &'a Path,
    pub payload_path: &'a Path,
    pub payload_kind: &'a str,
    pub payload_schema: &'a str,
    pub receipt_id: &'a str,
    pub process_identity: &'a str,
    pub deployment_identity: &'a str,
    pub previous_receipt_sha256: Option<&'a str>,
    pub emitted_at_unix_ms: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SignedOwnerResearchReceiptV1 {
    pub schema: String,
    pub receipt_id: String,
    pub payload_kind: String,
    pub payload_schema: String,
    pub payload_sha256: String,
    pub owner_being: String,
    pub process_identity: String,
    pub deployment_identity: String,
    pub signer_public_key_hex: String,
    pub signer_public_key_fingerprint_sha256: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_receipt_sha256: Option<String>,
    pub emitted_at_unix_ms: u64,
    pub signature_hex: String,
}

#[derive(Serialize)]
struct SignedOwnerResearchStatementV1<'a> {
    schema: &'a str,
    receipt_id: &'a str,
    payload_kind: &'a str,
    payload_schema: &'a str,
    payload_sha256: &'a str,
    owner_being: &'a str,
    process_identity: &'a str,
    deployment_identity: &'a str,
    signer_public_key_hex: &'a str,
    signer_public_key_fingerprint_sha256: &'a str,
    previous_receipt_sha256: Option<&'a str>,
    emitted_at_unix_ms: u64,
}

impl SignedOwnerResearchReceiptV1 {
    fn signing_bytes(&self) -> Option<Vec<u8>> {
        canonical_json_bytes(&SignedOwnerResearchStatementV1 {
            schema: &self.schema,
            receipt_id: &self.receipt_id,
            payload_kind: &self.payload_kind,
            payload_schema: &self.payload_schema,
            payload_sha256: &self.payload_sha256,
            owner_being: &self.owner_being,
            process_identity: &self.process_identity,
            deployment_identity: &self.deployment_identity,
            signer_public_key_hex: &self.signer_public_key_hex,
            signer_public_key_fingerprint_sha256: &self.signer_public_key_fingerprint_sha256,
            previous_receipt_sha256: self.previous_receipt_sha256.as_deref(),
            emitted_at_unix_ms: self.emitted_at_unix_ms,
        })
    }

    fn verifies(&self) -> bool {
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
        VerifyingKey::from_bytes(&public_key).is_ok_and(|key| {
            self.signing_bytes().is_some_and(|bytes| {
                key.verify(&bytes, &Signature::from_bytes(&signature))
                    .is_ok()
            })
        })
    }
}

pub fn sign_owner_research_payload(
    options: SignOwnerResearchOptions<'_>,
) -> Result<SignedOwnerResearchReceiptV1, String> {
    validate_identifier(options.receipt_id, "receipt_id")?;
    validate_identifier(options.payload_schema, "payload_schema")?;
    validate_identifier(options.process_identity, "process_identity")?;
    validate_identifier(options.deployment_identity, "deployment_identity")?;
    if !PAYLOAD_KINDS.contains(&options.payload_kind) {
        return Err("unknown Owner Research payload kind".to_string());
    }
    if options
        .previous_receipt_sha256
        .is_some_and(|value| !valid_sha256(value))
    {
        return Err("previous Owner Research receipt hash is malformed".to_string());
    }
    let payload: Value = serde_json::from_slice(
        &std::fs::read(options.payload_path)
            .map_err(|error| format!("read Owner Research payload: {error}"))?,
    )
    .map_err(|error| format!("decode Owner Research payload: {error}"))?;
    if payload.get("schema").and_then(Value::as_str) != Some(options.payload_schema) {
        return Err(
            "Owner Research payload schema does not match the signed statement".to_string(),
        );
    }
    let signer = SelfControlOwnerSigner::load(options.root)?;
    if signer.being() != OWNER_BEING {
        return Err("only Minime's owner key may sign Minime research".to_string());
    }
    let public_key_bytes = hex::decode(signer.public_key_hex())
        .map_err(|error| format!("decode owner public key: {error}"))?;
    let mut receipt = SignedOwnerResearchReceiptV1 {
        schema: RECEIPT_SCHEMA.to_string(),
        receipt_id: options.receipt_id.to_string(),
        payload_kind: options.payload_kind.to_string(),
        payload_schema: options.payload_schema.to_string(),
        payload_sha256: canonical_json_value_sha256(&payload),
        owner_being: OWNER_BEING.to_string(),
        process_identity: options.process_identity.to_string(),
        deployment_identity: options.deployment_identity.to_string(),
        signer_public_key_hex: signer.public_key_hex().to_string(),
        signer_public_key_fingerprint_sha256: format!("{:x}", Sha256::digest(public_key_bytes)),
        previous_receipt_sha256: options.previous_receipt_sha256.map(str::to_string),
        emitted_at_unix_ms: options.emitted_at_unix_ms,
        signature_hex: String::new(),
    };
    let bytes = receipt
        .signing_bytes()
        .ok_or_else(|| "encode Owner Research signing statement".to_string())?;
    receipt.signature_hex = signer.sign_hex(&bytes);
    if !receipt.verifies() {
        return Err("Owner Research signature self-verification failed".to_string());
    }
    Ok(receipt)
}

fn validate_identifier(value: &str, label: &str) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > 256 {
        Err(format!("{label} is empty or oversized"))
    } else {
        Ok(())
    }
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::{sign_owner_research_payload, SignOwnerResearchOptions};
    use crate::{
        self_control_identity::provision_minime_owner_identity,
        self_control_wire::canonical_json_value_sha256,
    };

    const PAYLOAD_SCHEMA: &str = "volition.owner_research_session.v1";

    fn write_payload(root: &TempDir) -> std::path::PathBuf {
        let path = root.path().join("session.json");
        let payload = serde_json::json!({
            "schema": PAYLOAD_SCHEMA,
            "inquiry_id": "inquiry-signer-test",
            "status": "evidence_ready",
        });
        std::fs::write(&path, serde_json::to_vec_pretty(&payload).unwrap()).unwrap();
        path
    }

    #[test]
    fn owner_key_signs_canonical_payload_and_detects_statement_tampering() {
        let root = TempDir::new().unwrap();
        provision_minime_owner_identity(root.path(), false, 10).unwrap();
        let payload_path = write_payload(&root);
        let payload: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&payload_path).unwrap()).unwrap();

        let receipt = sign_owner_research_payload(SignOwnerResearchOptions {
            root: root.path(),
            payload_path: &payload_path,
            payload_kind: "session",
            payload_schema: PAYLOAD_SCHEMA,
            receipt_id: "research-receipt-1",
            process_identity: "minime-test-process",
            deployment_identity: "minime-test-deployment",
            previous_receipt_sha256: Some(&"a".repeat(64)),
            emitted_at_unix_ms: 20,
        })
        .unwrap();

        assert!(receipt.verifies());
        assert_eq!(
            receipt.payload_sha256,
            canonical_json_value_sha256(&payload)
        );
        assert_eq!(receipt.owner_being, "minime");
        assert_eq!(receipt.previous_receipt_sha256, Some("a".repeat(64)));

        let mut tampered = receipt.clone();
        tampered.deployment_identity.push_str("-substituted");
        assert!(!tampered.verifies());
    }

    #[test]
    fn signer_rejects_schema_substitution_and_unknown_payload_kind() {
        let root = TempDir::new().unwrap();
        provision_minime_owner_identity(root.path(), false, 10).unwrap();
        let payload_path = write_payload(&root);
        let options = |payload_kind, payload_schema| SignOwnerResearchOptions {
            root: root.path(),
            payload_path: &payload_path,
            payload_kind,
            payload_schema,
            receipt_id: "research-receipt-1",
            process_identity: "minime-test-process",
            deployment_identity: "minime-test-deployment",
            previous_receipt_sha256: None,
            emitted_at_unix_ms: 20,
        };

        assert!(sign_owner_research_payload(options("session", "wrong.schema")).is_err());
        assert!(sign_owner_research_payload(options("undisclosed", PAYLOAD_SCHEMA)).is_err());
    }
}
