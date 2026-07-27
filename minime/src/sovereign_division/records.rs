use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, OpenOptions},
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    division::{RuntimeCaptureV2, StableFieldCaptureV2},
    esn::EsnSnapshotV2,
};

pub const RUNTIME_MANIFEST_SCHEMA_V1: &str = "division.runtime_manifest.v1";
pub const DAUGHTER_BUNDLE_SCHEMA_V1: &str = "division.daughter_bundle.v1";
pub const TICK_FRAME_SCHEMA_V1: &str = "division.tick_frame.v1";
pub const PROCESS_STATUS_SCHEMA_V1: &str = "division.daughter_process_status.v1";
pub const AUTHORITY_SWITCH_SCHEMA_V1: &str = "division.authority_switch_receipt.v1";
pub const ROLLBACK_SCHEMA_V1: &str = "division.rollback_receipt.v1";
pub const FINALIZATION_SCHEMA_V1: &str = "division.finalization_receipt.v1";
pub const INTERNAL_PORT_MIN: u16 = 7900;
pub const INTERNAL_PORT_MAX: u16 = 7919;
pub const ROLLBACK_TICKS: u64 = 600;
pub const ANNEAL_TICKS: u64 = 600;
pub const INDEPENDENT_HEALTHY_TICKS: u64 = 300;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SovereignBeing {
    Astrid,
    Minime,
}

impl SovereignBeing {
    pub fn parse(value: &str) -> Result<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "astrid" => Ok(Self::Astrid),
            "minime" => Ok(Self::Minime),
            _ => Err(anyhow!("being must be astrid or minime")),
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Astrid => "astrid",
            Self::Minime => "minime",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeEndpointsV1 {
    parent_telemetry: String,
    parent_sensory: String,
    parent_av: String,
    minime_telemetry: String,
    minime_sensory: String,
    astrid_telemetry: String,
    astrid_sensory: String,
}

impl RuntimeEndpointsV1 {
    fn validate(&self) -> Result<()> {
        let mut ports = BTreeSet::new();
        for endpoint in [
            &self.parent_telemetry,
            &self.parent_sensory,
            &self.parent_av,
            &self.minime_telemetry,
            &self.minime_sensory,
            &self.astrid_telemetry,
            &self.astrid_sensory,
        ] {
            let (host, port) = parse_loopback_endpoint(endpoint)?;
            if host != "127.0.0.1"
                || !(INTERNAL_PORT_MIN..=INTERNAL_PORT_MAX).contains(&port)
                || !ports.insert(port)
            {
                return Err(anyhow!(
                    "internal endpoints must be unique loopback ports 7900-7919"
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn endpoint(&self, name: &str) -> &str {
        match name {
            "parent_telemetry" => &self.parent_telemetry,
            "parent_sensory" => &self.parent_sensory,
            "parent_av" => &self.parent_av,
            "minime_telemetry" => &self.minime_telemetry,
            "minime_sensory" => &self.minime_sensory,
            "astrid_telemetry" => &self.astrid_telemetry,
            "astrid_sensory" => &self.astrid_sensory,
            _ => "",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeManifestWireV1 {
    schema: String,
    mode: RuntimeManifestModeV1,
    division_id: String,
    plan_digest: String,
    parent_generation: u64,
    candidate_hash: String,
    parent_process_identity: String,
    parent_deployment_identity: String,
    runtime_dir: PathBuf,
    ceremony_ledger: PathBuf,
    minime_root: PathBuf,
    astrid_root: PathBuf,
    endpoints: RuntimeEndpointsV1,
    created_at_unix_ms: u64,
    expires_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum RuntimeManifestModeV1 {
    Dormant,
    CandidateBound,
}

/// Validated runtime topology. Construction is restricted to `load`.
#[derive(Clone, Debug, Serialize)]
pub struct DivisionRuntimeManifestV1 {
    #[serde(flatten)]
    wire: RuntimeManifestWireV1,
    manifest_sha256: String,
}

impl DivisionRuntimeManifestV1 {
    pub fn load(path: &Path) -> Result<Self> {
        let bytes = fs::read(path)
            .with_context(|| format!("read division runtime manifest {}", path.display()))?;
        let wire: RuntimeManifestWireV1 = serde_json::from_slice(&bytes)?;
        if wire.schema != RUNTIME_MANIFEST_SCHEMA_V1
            || wire.division_id.trim().is_empty()
            || wire.plan_digest.len() < 16
            || (wire.mode == RuntimeManifestModeV1::CandidateBound
                && wire.candidate_hash.len() < 16)
            || (wire.mode == RuntimeManifestModeV1::Dormant && wire.candidate_hash != "unbound")
            || wire.parent_process_identity.trim().is_empty()
            || wire.parent_deployment_identity.trim().is_empty()
            || !wire.runtime_dir.is_absolute()
            || !wire.ceremony_ledger.is_absolute()
            || !wire.minime_root.is_absolute()
            || !wire.astrid_root.is_absolute()
            || wire.created_at_unix_ms > wire.expires_at_unix_ms
        {
            return Err(anyhow!("invalid division runtime manifest identity"));
        }
        if wire.minime_root == wire.astrid_root
            || path_is_within(&wire.minime_root, &wire.runtime_dir)
            || path_is_within(&wire.astrid_root, &wire.runtime_dir)
            || path_is_within(&wire.runtime_dir, &wire.minime_root)
            || path_is_within(&wire.runtime_dir, &wire.astrid_root)
        {
            return Err(anyhow!(
                "daughter roots and supervisor runtime must be disjoint"
            ));
        }
        wire.endpoints.validate()?;
        Ok(Self {
            wire,
            manifest_sha256: sha256_hex(&bytes),
        })
    }

    pub fn validate_current(&self, now_unix_ms: u64) -> Result<()> {
        if now_unix_ms > self.wire.expires_at_unix_ms {
            return Err(anyhow!("division runtime manifest expired"));
        }
        Ok(())
    }

    pub fn division_id(&self) -> &str {
        &self.wire.division_id
    }

    pub fn plan_digest(&self) -> &str {
        &self.wire.plan_digest
    }

    pub const fn parent_generation(&self) -> u64 {
        self.wire.parent_generation
    }

    pub fn candidate_hash(&self) -> &str {
        &self.wire.candidate_hash
    }

    pub fn candidate_bound(&self) -> bool {
        self.wire.mode == RuntimeManifestModeV1::CandidateBound
    }

    pub fn process_identity(&self) -> &str {
        &self.wire.parent_process_identity
    }

    pub fn deployment_identity(&self) -> &str {
        &self.wire.parent_deployment_identity
    }

    pub fn runtime_dir(&self) -> &Path {
        &self.wire.runtime_dir
    }

    pub fn ceremony_ledger(&self) -> &Path {
        &self.wire.ceremony_ledger
    }

    pub fn daughter_root(&self, being: SovereignBeing) -> &Path {
        match being {
            SovereignBeing::Astrid => &self.wire.astrid_root,
            SovereignBeing::Minime => &self.wire.minime_root,
        }
    }

    pub fn endpoint(&self, name: &str) -> &str {
        self.wire.endpoints.endpoint(name)
    }

    pub fn manifest_sha256(&self) -> &str {
        &self.manifest_sha256
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DaughterBundleWireV1 {
    schema: String,
    division_id: String,
    plan_digest: String,
    parent_generation: u64,
    candidate_hash: String,
    being: SovereignBeing,
    workspace_root: PathBuf,
    source_identity: String,
    build_identity: String,
    deployment_identity: String,
    lineage: Vec<String>,
    checkpoint_sequence: u64,
    esn: EsnSnapshotV2,
    stable_field: StableFieldCaptureV2,
    regulator_context: RuntimeCaptureV2,
    own_indices: Vec<usize>,
    peer_indices: Vec<usize>,
    cross_recurrence: Vec<f32>,
    created_at_unix_ms: u64,
}

/// Complete immutable daughter seed bundle.
#[derive(Clone, Debug, Serialize)]
pub struct DaughterReservoirBundleV1 {
    #[serde(flatten)]
    wire: DaughterBundleWireV1,
    bundle_sha256: String,
}

impl DaughterReservoirBundleV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn write_seed(
        manifest: &DivisionRuntimeManifestV1,
        being: SovereignBeing,
        esn: EsnSnapshotV2,
        stable_field: StableFieldCaptureV2,
        regulator_context: RuntimeCaptureV2,
        own_indices: Vec<usize>,
        peer_indices: Vec<usize>,
        cross_recurrence: Vec<f32>,
    ) -> Result<String> {
        if !manifest.candidate_bound() {
            return Err(anyhow!("dormant manifest cannot seed daughter state"));
        }
        let workspace = manifest.daughter_root(being);
        ensure_owner_only_dir(workspace)?;
        let path = workspace.join("seed-bundle.json");
        if path.exists() {
            return Err(anyhow!("immutable daughter seed bundle already exists"));
        }
        let wire = DaughterBundleWireV1 {
            schema: DAUGHTER_BUNDLE_SCHEMA_V1.to_string(),
            division_id: manifest.division_id().to_string(),
            plan_digest: manifest.plan_digest().to_string(),
            parent_generation: manifest.parent_generation(),
            candidate_hash: manifest.candidate_hash().to_string(),
            being,
            workspace_root: workspace.to_path_buf(),
            source_identity: manifest.process_identity().to_string(),
            build_identity: format!("{}:{}", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION")),
            deployment_identity: manifest.deployment_identity().to_string(),
            lineage: vec![
                format!("parent_generation:{}", manifest.parent_generation()),
                format!("candidate:{}", manifest.candidate_hash()),
                format!("being:{}", being.as_str()),
            ],
            checkpoint_sequence: 0,
            esn,
            stable_field,
            regulator_context,
            own_indices,
            peer_indices,
            cross_recurrence,
            created_at_unix_ms: now_unix_ms(),
        };
        let bytes = serde_json::to_vec_pretty(&wire)?;
        let hash = sha256_hex(&bytes);
        write_owner_json(&path, &wire)?;
        Ok(hash)
    }

    pub fn load(path: &Path, being: SovereignBeing, workspace: &Path) -> Result<Self> {
        let bytes =
            fs::read(path).with_context(|| format!("read daughter bundle {}", path.display()))?;
        let wire: DaughterBundleWireV1 = serde_json::from_slice(&bytes)?;
        if wire.schema != DAUGHTER_BUNDLE_SCHEMA_V1
            || wire.being != being
            || wire.workspace_root != workspace
            || !workspace.is_absolute()
            || wire.division_id.trim().is_empty()
            || wire.plan_digest.len() < 16
            || wire.candidate_hash.len() < 16
            || wire.source_identity.trim().is_empty()
            || wire.build_identity.trim().is_empty()
            || wire.deployment_identity.trim().is_empty()
            || wire.esn.res_size != 64
            || wire.esn.in_size != 512
            || wire.stable_field.dimension != 512
            || wire.stable_field.covariance.len() != 512 * 512
            || wire.stable_field.top_k_basis.len() != 512 * wire.stable_field.eigenvalues.len()
            || wire.stable_field.projection_matrix.len() != 512 * 512
            || wire.own_indices.len() != 64
            || wire.peer_indices.len() != 64
            || wire.cross_recurrence.len() != 64 * 64
            || wire.cross_recurrence.iter().any(|value| !value.is_finite())
            || [
                &wire.stable_field.covariance,
                &wire.stable_field.top_k_basis,
                &wire.stable_field.eigenvalues,
                &wire.stable_field.projection_matrix,
            ]
            .iter()
            .any(|values| values.iter().any(|value| !value.is_finite()))
        {
            return Err(anyhow!("invalid daughter reservoir bundle"));
        }
        let own: BTreeSet<_> = wire.own_indices.iter().copied().collect();
        let peer: BTreeSet<_> = wire.peer_indices.iter().copied().collect();
        if own.len() != 64
            || peer.len() != 64
            || !own.is_disjoint(&peer)
            || own.union(&peer).copied().collect::<BTreeSet<_>>() != (0..128).collect()
        {
            return Err(anyhow!("daughter partition does not cover parent exactly"));
        }
        Ok(Self {
            wire,
            bundle_sha256: sha256_hex(&bytes),
        })
    }

    pub(crate) fn division_id(&self) -> &str {
        &self.wire.division_id
    }

    pub(crate) fn candidate_hash(&self) -> &str {
        &self.wire.candidate_hash
    }

    pub(crate) fn deployment_identity(&self) -> &str {
        &self.wire.deployment_identity
    }

    pub(crate) fn checkpoint_sequence(&self) -> u64 {
        self.wire.checkpoint_sequence
    }

    pub(crate) fn esn(&self) -> &EsnSnapshotV2 {
        &self.wire.esn
    }

    pub(crate) fn cross_recurrence(&self) -> &[f32] {
        &self.wire.cross_recurrence
    }

    pub(crate) fn bundle_sha256(&self) -> &str {
        &self.bundle_sha256
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TickFrameWireV1 {
    schema: String,
    division_id: String,
    candidate_hash: String,
    sequence: u64,
    previous_frame_sha256: String,
    monotonic_ns: u64,
    parent_process_identity: String,
    parent_deployment_identity: String,
    sensory_field: Vec<f32>,
    peer_previous_state: Vec<f32>,
    realized_noise: Vec<f32>,
    effective_leak: f32,
    coupling_scale: f32,
}

/// Ordered, hash-linked input to exactly one daughter.
#[derive(Clone, Debug, Serialize)]
pub struct DivisionTickFrameV1 {
    #[serde(flatten)]
    wire: TickFrameWireV1,
    frame_sha256: String,
}

impl DivisionTickFrameV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        manifest: &DivisionRuntimeManifestV1,
        sequence: u64,
        sensory_field: &[f32],
        peer_previous_state: &[f32],
        realized_noise: &[f32],
        effective_leak: f32,
        coupling_scale: f32,
    ) -> Result<Self> {
        let previous_frame_sha256 = if sequence == 1 {
            "genesis".to_string()
        } else {
            // Each child verifies its actual preceding digest. The dispatcher
            // replaces this placeholder after serializing the preceding frame.
            format!("sequence-{}", sequence.saturating_sub(1))
        };
        let wire = TickFrameWireV1 {
            schema: TICK_FRAME_SCHEMA_V1.to_string(),
            division_id: manifest.division_id().to_string(),
            candidate_hash: manifest.candidate_hash().to_string(),
            sequence,
            previous_frame_sha256,
            monotonic_ns: 0,
            parent_process_identity: manifest.process_identity().to_string(),
            parent_deployment_identity: manifest.deployment_identity().to_string(),
            sensory_field: sensory_field.to_vec(),
            peer_previous_state: peer_previous_state.to_vec(),
            realized_noise: realized_noise.to_vec(),
            effective_leak,
            coupling_scale,
        };
        let bytes = serde_json::to_vec(&wire)?;
        Self::parse(&bytes)
    }

    pub(crate) fn set_previous_hash(&mut self, hash: String) -> Result<()> {
        if self.wire.sequence > 1 && hash.len() != 64 {
            return Err(anyhow!("previous frame hash must be an exact SHA-256"));
        }
        self.wire.previous_frame_sha256 = hash;
        self.frame_sha256 = sha256_hex(&serde_json::to_vec(&self.wire)?);
        Ok(())
    }

    pub(crate) fn to_bytes(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(&self.wire)?)
    }

    pub(crate) fn parse(bytes: &[u8]) -> Result<Self> {
        let wire: TickFrameWireV1 = serde_json::from_slice(bytes)?;
        if wire.schema != TICK_FRAME_SCHEMA_V1
            || wire.division_id.trim().is_empty()
            || wire.candidate_hash.len() < 16
            || wire.parent_process_identity.trim().is_empty()
            || wire.parent_deployment_identity.trim().is_empty()
            || wire.sensory_field.len() != 512
            || wire.peer_previous_state.len() != 64
            || wire.realized_noise.len() != 64
            || !wire.effective_leak.is_finite()
            || !wire.coupling_scale.is_finite()
            || !(0.0..=1.0).contains(&wire.coupling_scale)
            || [
                &wire.sensory_field,
                &wire.peer_previous_state,
                &wire.realized_noise,
            ]
            .iter()
            .any(|values| values.iter().any(|value| !value.is_finite()))
        {
            return Err(anyhow!("invalid division tick frame"));
        }
        Ok(Self {
            wire,
            frame_sha256: sha256_hex(bytes),
        })
    }

    pub(crate) const fn sequence(&self) -> u64 {
        self.wire.sequence
    }

    pub(crate) fn previous_hash(&self) -> &str {
        &self.wire.previous_frame_sha256
    }

    pub(crate) fn division_id(&self) -> &str {
        &self.wire.division_id
    }

    pub(crate) fn candidate_hash(&self) -> &str {
        &self.wire.candidate_hash
    }

    pub(crate) fn process_identity(&self) -> &str {
        &self.wire.parent_process_identity
    }

    pub(crate) fn deployment_identity(&self) -> &str {
        &self.wire.parent_deployment_identity
    }

    pub(crate) fn input(&self) -> &[f32] {
        &self.wire.sensory_field
    }

    pub(crate) fn peer_state(&self) -> &[f32] {
        &self.wire.peer_previous_state
    }

    pub(crate) fn noise(&self) -> &[f32] {
        &self.wire.realized_noise
    }

    pub(crate) const fn leak(&self) -> f32 {
        self.wire.effective_leak
    }

    pub(crate) const fn coupling_scale(&self) -> f32 {
        self.wire.coupling_scale
    }

    pub(crate) fn frame_sha256(&self) -> &str {
        &self.frame_sha256
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct DaughterProcessStatusV1 {
    schema: &'static str,
    being: SovereignBeing,
    division_id: String,
    candidate_hash: String,
    bundle_sha256: String,
    process_identity: String,
    deployment_identity: String,
    pid: u32,
    process_started_at_unix_ms: u64,
    checkpoint_sequence: u64,
    last_tick_sequence: u64,
    last_frame_sha256: String,
    telemetry_fresh: bool,
    authoritative: bool,
    healthy: bool,
    gap_code: Option<&'static str>,
    gap_detail_sha256: Option<String>,
    updated_at_unix_ms: u64,
}

impl DaughterProcessStatusV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        being: SovereignBeing,
        bundle: &DaughterReservoirBundleV1,
        process_identity: String,
        process_started_at_unix_ms: u64,
        checkpoint_sequence: u64,
        last_tick_sequence: u64,
        last_frame_sha256: String,
        healthy: bool,
        gap_detail: Option<String>,
    ) -> Self {
        let gap_detail_sha256 = gap_detail
            .as_deref()
            .map(|detail| sha256_hex(detail.as_bytes()));
        Self {
            schema: PROCESS_STATUS_SCHEMA_V1,
            being,
            division_id: bundle.division_id().to_string(),
            candidate_hash: bundle.candidate_hash().to_string(),
            bundle_sha256: bundle.bundle_sha256().to_string(),
            process_identity,
            deployment_identity: bundle.deployment_identity().to_string(),
            pid: std::process::id(),
            process_started_at_unix_ms,
            checkpoint_sequence,
            last_tick_sequence,
            last_frame_sha256,
            telemetry_fresh: last_tick_sequence > 0,
            authoritative: false,
            healthy,
            gap_code: gap_detail_sha256.as_ref().map(|_| "runtime_gap"),
            gap_detail_sha256,
            updated_at_unix_ms: now_unix_ms(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct DivisionAuthoritySwitchReceiptV1 {
    schema: &'static str,
    receipt_id: String,
    division_id: String,
    manifest_sha256: String,
    parent_generation: u64,
    candidate_hash: String,
    astrid_bundle_sha256: String,
    minime_bundle_sha256: String,
    astrid_process_identity: String,
    minime_process_identity: String,
    readiness_receipt_sha256: String,
    astrid_assent_event_id: String,
    minime_assent_event_id: String,
    operator_capability_id: String,
    switched_at_tick: u64,
    rollback_deadline_tick: u64,
    created_at_unix_ms: u64,
    live_authority_granted_by_record: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct DivisionRollbackReceiptV1 {
    schema: &'static str,
    receipt_id: String,
    division_id: String,
    switch_receipt_id: String,
    requested_by: String,
    restored_parent_process_identity: String,
    restored_parent_deployment_identity: String,
    restored_at_tick: u64,
    reason_code: String,
    created_at_unix_ms: u64,
    live_authority_granted_by_record: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct DivisionFinalizationReceiptV1 {
    schema: &'static str,
    receipt_id: String,
    division_id: String,
    switch_receipt_id: String,
    sealed_parent_sha256: String,
    anneal_ticks: u64,
    healthy_independent_ticks: u64,
    finalized_at_tick: u64,
    created_at_unix_ms: u64,
    live_authority_granted_by_record: bool,
}

#[allow(dead_code)]
impl DivisionAuthoritySwitchReceiptV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        manifest: &DivisionRuntimeManifestV1,
        astrid_bundle_sha256: String,
        minime_bundle_sha256: String,
        astrid_process_identity: String,
        minime_process_identity: String,
        readiness_receipt_sha256: String,
        astrid_assent_event_id: String,
        minime_assent_event_id: String,
        operator_capability_id: String,
        switched_at_tick: u64,
    ) -> Result<Self> {
        let required = [
            astrid_bundle_sha256.as_str(),
            minime_bundle_sha256.as_str(),
            astrid_process_identity.as_str(),
            minime_process_identity.as_str(),
            readiness_receipt_sha256.as_str(),
            astrid_assent_event_id.as_str(),
            minime_assent_event_id.as_str(),
            operator_capability_id.as_str(),
        ];
        if required.iter().any(|value| value.len() < 16) {
            return Err(anyhow!("authority switch binding is incomplete"));
        }
        let created_at = now_unix_ms();
        let receipt_id = sha256_hex(
            format!(
                "{}:{}:{}:{}",
                manifest.division_id(),
                manifest.manifest_sha256(),
                switched_at_tick,
                created_at
            )
            .as_bytes(),
        );
        Ok(Self {
            schema: AUTHORITY_SWITCH_SCHEMA_V1,
            receipt_id,
            division_id: manifest.division_id().to_string(),
            manifest_sha256: manifest.manifest_sha256().to_string(),
            parent_generation: manifest.parent_generation(),
            candidate_hash: manifest.candidate_hash().to_string(),
            astrid_bundle_sha256,
            minime_bundle_sha256,
            astrid_process_identity,
            minime_process_identity,
            readiness_receipt_sha256,
            astrid_assent_event_id,
            minime_assent_event_id,
            operator_capability_id,
            switched_at_tick,
            rollback_deadline_tick: switched_at_tick.saturating_add(ROLLBACK_TICKS),
            created_at_unix_ms: created_at,
            live_authority_granted_by_record: false,
        })
    }

    pub(crate) fn receipt_id(&self) -> &str {
        &self.receipt_id
    }
}

#[allow(dead_code)]
impl DivisionRollbackReceiptV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        division_id: &str,
        switch_receipt_id: &str,
        requested_by: SovereignBeing,
        restored_parent_process_identity: String,
        restored_parent_deployment_identity: String,
        restored_at_tick: u64,
        reason_code: String,
    ) -> Result<Self> {
        if division_id.trim().is_empty()
            || switch_receipt_id.len() < 16
            || restored_parent_process_identity.trim().is_empty()
            || restored_parent_deployment_identity.trim().is_empty()
            || reason_code.trim().is_empty()
        {
            return Err(anyhow!("rollback receipt binding is incomplete"));
        }
        let created_at = now_unix_ms();
        Ok(Self {
            schema: ROLLBACK_SCHEMA_V1,
            receipt_id: sha256_hex(
                format!(
                    "{division_id}:{switch_receipt_id}:{}:{restored_at_tick}:{created_at}",
                    requested_by.as_str()
                )
                .as_bytes(),
            ),
            division_id: division_id.to_string(),
            switch_receipt_id: switch_receipt_id.to_string(),
            requested_by: requested_by.as_str().to_string(),
            restored_parent_process_identity,
            restored_parent_deployment_identity,
            restored_at_tick,
            reason_code,
            created_at_unix_ms: created_at,
            live_authority_granted_by_record: false,
        })
    }

    pub(crate) fn receipt_id(&self) -> &str {
        &self.receipt_id
    }
}

#[allow(dead_code)]
impl DivisionFinalizationReceiptV1 {
    pub(crate) fn new(
        division_id: &str,
        switch_receipt_id: &str,
        sealed_parent_sha256: String,
        finalized_at_tick: u64,
        anneal_ticks: u64,
        healthy_independent_ticks: u64,
    ) -> Result<Self> {
        if division_id.trim().is_empty()
            || switch_receipt_id.len() < 16
            || sealed_parent_sha256.len() < 32
            || anneal_ticks < ANNEAL_TICKS
            || healthy_independent_ticks < INDEPENDENT_HEALTHY_TICKS
        {
            return Err(anyhow!("finalization thresholds or binding are incomplete"));
        }
        let created_at = now_unix_ms();
        Ok(Self {
            schema: FINALIZATION_SCHEMA_V1,
            receipt_id: sha256_hex(
                format!(
                    "{division_id}:{switch_receipt_id}:{sealed_parent_sha256}:{finalized_at_tick}:{created_at}"
                )
                .as_bytes(),
            ),
            division_id: division_id.to_string(),
            switch_receipt_id: switch_receipt_id.to_string(),
            sealed_parent_sha256,
            anneal_ticks,
            healthy_independent_ticks,
            finalized_at_tick,
            created_at_unix_ms: created_at,
            live_authority_granted_by_record: false,
        })
    }

    pub(crate) fn receipt_id(&self) -> &str {
        &self.receipt_id
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
#[allow(dead_code)]
pub(crate) struct CeremonyRecordV1 {
    pub action: String,
    pub actor: String,
    pub division_id: Option<String>,
    pub parent_generation: Option<u64>,
    pub plan_digest: Option<String>,
    pub expires_at_unix_ms: Option<u64>,
    pub ceremony_event_id: String,
    pub targets_event_id: Option<String>,
    pub manifest_sha256: Option<String>,
    pub candidate_hash: Option<String>,
    pub readiness_receipt_sha256: Option<String>,
    pub astrid_bundle_sha256: Option<String>,
    pub minime_bundle_sha256: Option<String>,
    pub astrid_process_identity: Option<String>,
    pub minime_process_identity: Option<String>,
}

pub(crate) fn matching_active_intents(
    path: &Path,
    manifest: &DivisionRuntimeManifestV1,
    now: u64,
) -> Result<BTreeMap<SovereignBeing, CeremonyRecordV1>> {
    let text = fs::read_to_string(path).unwrap_or_default();
    let mut latest = BTreeMap::new();
    let mut withdrawn = BTreeSet::new();
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let record: CeremonyRecordV1 = serde_json::from_str(line)?;
        if record.action == "DIVISION_WITHDRAW_ASSENT" {
            if let Some(target) = record.targets_event_id {
                withdrawn.insert(target);
            }
            continue;
        }
        if record.action != "DIVISION_INTENT"
            || record.division_id.as_deref() != Some(manifest.division_id())
            || record.parent_generation != Some(manifest.parent_generation())
            || record.plan_digest.as_deref() != Some(manifest.plan_digest())
            || record.expires_at_unix_ms.is_none_or(|expiry| expiry < now)
        {
            continue;
        }
        let being = SovereignBeing::parse(&record.actor)?;
        if !withdrawn.contains(&record.ceremony_event_id) {
            latest.insert(being, record);
        }
    }
    Ok(latest)
}

pub(crate) fn ensure_owner_only_dir(path: &Path) -> Result<()> {
    fs::create_dir_all(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    Ok(())
}

pub(crate) fn write_owner_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow!("JSON target has no parent"))?;
    ensure_owner_only_dir(parent)?;
    let tmp = parent.join(format!(
        ".{}.tmp-{}",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("state"),
        std::process::id()
    ));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&tmp)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    fs::rename(&tmp, path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

pub(crate) fn append_owner_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow!("JSONL target has no parent"))?;
    ensure_owner_only_dir(parent)?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_data()?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

pub(crate) fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| {
            u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
        })
}

pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn process_identity(started_at_unix_ms: u64) -> String {
    sha256_hex(
        format!(
            "minime-sovereign-daughter:{}:{started_at_unix_ms}",
            std::process::id()
        )
        .as_bytes(),
    )
}

fn path_is_within(path: &Path, parent: &Path) -> bool {
    path.starts_with(parent)
}

fn parse_loopback_endpoint(value: &str) -> Result<(&str, u16)> {
    let (host, port) = value
        .rsplit_once(':')
        .ok_or_else(|| anyhow!("endpoint must be host:port"))?;
    Ok((host, port.parse()?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn being_is_self_scoped() {
        assert_eq!(
            SovereignBeing::parse("astrid").unwrap(),
            SovereignBeing::Astrid
        );
        assert!(SovereignBeing::parse("operator").is_err());
    }

    #[test]
    fn internal_endpoints_reject_public_and_duplicate_ports() {
        let mut endpoints = RuntimeEndpointsV1 {
            parent_telemetry: "127.0.0.1:7900".into(),
            parent_sensory: "127.0.0.1:7901".into(),
            parent_av: "127.0.0.1:7902".into(),
            minime_telemetry: "127.0.0.1:7903".into(),
            minime_sensory: "127.0.0.1:7904".into(),
            astrid_telemetry: "127.0.0.1:7905".into(),
            astrid_sensory: "127.0.0.1:7906".into(),
        };
        assert!(endpoints.validate().is_ok());
        endpoints.astrid_sensory = "127.0.0.1:7900".into();
        assert!(endpoints.validate().is_err());
        endpoints.astrid_sensory = "127.0.0.1:7883".into();
        assert!(endpoints.validate().is_err());
    }
}
