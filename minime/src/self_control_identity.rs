use std::{collections::BTreeMap, path::Path};

use ed25519_dalek::{Signer as _, SigningKey};
use rand::rngs::OsRng;
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

use crate::{
    self_control_runtime::{
        storage::{read_json, write_owner_json},
        SelfControlRuntime, SelfControlTrustStoreV1,
    },
    self_control_wire::{
        canonical_self_control_intent_sha256, SelfControlAuthorityProofV1, SelfControlCommandV2,
        SelfControlIntentV2, SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1,
    },
};

const IDENTITY_SCHEMA: &str = "minime.self_control.owner_identity.v1";
const TARGET_BEING: &str = "minime";

#[derive(Clone, Debug, Serialize, Deserialize)]
struct StoredOwnerIdentityV1 {
    schema: String,
    being: String,
    key_id: String,
    public_key_hex: String,
    signing_key_seed_hex: String,
    created_at_unix_ms: u64,
}

#[derive(Clone)]
pub struct SelfControlOwnerSigner {
    being: String,
    key_id: String,
    public_key_hex: String,
    signing_key: SigningKey,
}

#[derive(Clone, Debug, Serialize)]
pub struct SelfControlProvisionReceiptV1 {
    pub schema: String,
    pub being: String,
    pub key_id: String,
    pub public_key_hex: String,
    pub identity_path: String,
    pub trust_path: String,
    pub rotated: bool,
}

impl SelfControlOwnerSigner {
    pub fn load(root: &Path) -> Result<Self, String> {
        let path = root.join("identity.json");
        let stored = read_json::<StoredOwnerIdentityV1>(&path)?
            .ok_or_else(|| format!("self-control identity is missing: {}", path.display()))?;
        Self::from_stored(stored)
    }

    #[must_use]
    pub fn being(&self) -> &str {
        &self.being
    }

    #[must_use]
    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    #[must_use]
    pub fn public_key_hex(&self) -> &str {
        &self.public_key_hex
    }

    pub fn sign_command(
        &self,
        intent: SelfControlIntentV2,
        command_id: String,
        nonce: String,
        now_unix_ms: u64,
    ) -> Result<SelfControlCommandV2, String> {
        let mut proof = SelfControlAuthorityProofV1 {
            schema: SELF_CONTROL_AUTHORITY_PROOF_SCHEMA_V1.to_string(),
            authority_class: intent.authority_class,
            signer_being: self.being.clone(),
            scope: intent.authority_scope.clone(),
            nonce,
            signer_public_key_hex: self.public_key_hex.clone(),
            signature_hex: String::new(),
            intent_sha256: canonical_self_control_intent_sha256(&intent),
            issued_at_unix_ms: now_unix_ms,
            expires_at_unix_ms: intent.command_expires_at_unix_ms,
        };
        let signing_bytes = proof
            .signing_bytes(&intent)
            .ok_or_else(|| "self-control signing statement could not be encoded".to_string())?;
        proof.signature_hex = hex::encode(self.signing_key.sign(&signing_bytes).to_bytes());
        Ok(SelfControlCommandV2 {
            schema: crate::self_control_wire::SELF_CONTROL_COMMAND_SCHEMA_V2.to_string(),
            command_id,
            intent,
            authority_proofs: vec![proof],
        })
    }

    fn from_stored(stored: StoredOwnerIdentityV1) -> Result<Self, String> {
        if stored.schema != IDENTITY_SCHEMA || stored.being != TARGET_BEING {
            return Err("self-control owner identity schema mismatch".to_string());
        }
        let seed = decode_array::<32>(&stored.signing_key_seed_hex, "signing key seed")?;
        let signing_key = SigningKey::from_bytes(&seed);
        let public_key_hex = hex::encode(signing_key.verifying_key().to_bytes());
        let expected_key_id = key_id(&public_key_hex);
        if stored.public_key_hex != public_key_hex || stored.key_id != expected_key_id {
            return Err("self-control owner identity integrity mismatch".to_string());
        }
        Ok(Self {
            being: stored.being,
            key_id: stored.key_id,
            public_key_hex,
            signing_key,
        })
    }
}

pub fn provision_minime_owner_identity(
    root: &Path,
    rotate: bool,
    now_unix_ms: u64,
) -> Result<SelfControlProvisionReceiptV1, String> {
    let identity_path = root.join("identity.json");
    let existing = read_json::<StoredOwnerIdentityV1>(&identity_path)?;
    let (signer, rotated) = if let Some(stored) = existing {
        if rotate {
            (new_signer(root, now_unix_ms)?, true)
        } else {
            (SelfControlOwnerSigner::from_stored(stored)?, false)
        }
    } else {
        (new_signer(root, now_unix_ms)?, false)
    };

    let trust_path = root.join("trust.json");
    let mut trust = read_json::<SelfControlTrustStoreV1>(&trust_path)?.unwrap_or_default();
    let mut pinned = BTreeMap::new();
    pinned.append(&mut trust.pinned_public_keys);
    pinned.insert(
        signer.being().to_string(),
        signer.public_key_hex().to_string(),
    );
    trust.pinned_public_keys = pinned;
    SelfControlRuntime::provision_trust_store(root, &trust)?;

    Ok(SelfControlProvisionReceiptV1 {
        schema: "minime.self_control.provision_receipt.v1".to_string(),
        being: signer.being().to_string(),
        key_id: signer.key_id().to_string(),
        public_key_hex: signer.public_key_hex().to_string(),
        identity_path: identity_path.display().to_string(),
        trust_path: trust_path.display().to_string(),
        rotated,
    })
}

fn new_signer(root: &Path, now_unix_ms: u64) -> Result<SelfControlOwnerSigner, String> {
    let signing_key = SigningKey::generate(&mut OsRng);
    let public_key_hex = hex::encode(signing_key.verifying_key().to_bytes());
    let stored = StoredOwnerIdentityV1 {
        schema: IDENTITY_SCHEMA.to_string(),
        being: TARGET_BEING.to_string(),
        key_id: key_id(&public_key_hex),
        public_key_hex,
        signing_key_seed_hex: hex::encode(signing_key.to_bytes()),
        created_at_unix_ms: now_unix_ms,
    };
    write_owner_json(&root.join("identity.json"), &stored)?;
    SelfControlOwnerSigner::from_stored(stored)
}

fn key_id(public_key_hex: &str) -> String {
    let digest = format!("{:x}", Sha256::digest(public_key_hex.as_bytes()));
    format!("minime-ed25519:{}", &digest[..24])
}

fn decode_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N], String> {
    hex::decode(value)
        .map_err(|error| format!("decode {label}: {error}"))?
        .try_into()
        .map_err(|_| format!("{label} has the wrong length"))
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::{provision_minime_owner_identity, SelfControlOwnerSigner};
    use crate::self_control_runtime::storage::read_json;

    #[test]
    fn provision_is_idempotent_and_rotation_is_explicit() {
        let root = TempDir::new().unwrap();
        let first = provision_minime_owner_identity(root.path(), false, 10).unwrap();
        let second = provision_minime_owner_identity(root.path(), false, 20).unwrap();
        assert_eq!(first.public_key_hex, second.public_key_hex);
        assert!(!second.rotated);

        let rotated = provision_minime_owner_identity(root.path(), true, 30).unwrap();
        assert_ne!(first.public_key_hex, rotated.public_key_hex);
        assert!(rotated.rotated);
        let loaded = SelfControlOwnerSigner::load(root.path()).unwrap();
        assert_eq!(loaded.public_key_hex(), rotated.public_key_hex);

        let trust: serde_json::Value = read_json(&root.path().join("trust.json")).unwrap().unwrap();
        assert_eq!(
            trust["pinned_public_keys"]["minime"],
            rotated.public_key_hex
        );
    }
}
