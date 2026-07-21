//! ACTION-controlled, recoverable reservoir division rehearsal.
//!
//! The live parent remains authoritative. Two 64-node daughter actors run in
//! shadow with same-tick double-buffered bridge inputs. The independent 512D
//! stable-core sensory field is cloned in checkpoint evidence and is never
//! partitioned by reservoir neuron index. Live commit is intentionally hard
//! disabled in this first landing.

use std::collections::{BTreeMap, VecDeque};
use std::fs::{self, File, OpenOptions};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Result};
use astrid_minime_protocol::{
    DivisionActionV1, DivisionCommandV1, DivisionEventV1, DivisionLifecycleV1, DivisionReadinessV1,
    DivisionReceiptStatusV1, DivisionReceiptV1, DivisionStatusV1, DIVISION_EVENT_SCHEMA_V1,
    DIVISION_READINESS_POLICY_V1, DIVISION_RECEIPT_SCHEMA_V1, DIVISION_STATUS_SCHEMA_V1,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest as _, Sha256};

use crate::esn::{EsnSnapshotV2, SpectralSnapshotV2, ESN};
use crate::gpu::Gpu;
use crate::spectral::eigenfill::{EigenFillEstimator, EigenFillEstimatorSnapshotV1};

pub const MITOSIS_BUNDLE_SCHEMA_V2: &str = "division.mitosis_bundle.v2";
pub const NATIVE_COMMIT_ENABLED: bool = false;
pub const DIVISION_REHEARSAL_OPERATOR_ENV: &str = "MINIME_DIVISION_REHEARSAL_ENABLED";
const SHADOW_MIN_TICKS: u64 = 600;
const FINAL_WINDOW: usize = 300;
const ROLLBACK_WINDOW_TICKS: u64 = 600;
const FINALIZE_HEALTHY_TICKS: u64 = 300;
const BRIDGE_ANNEAL_TICKS: u64 = 600;

#[must_use]
pub fn division_rehearsal_enabled() -> bool {
    division_rehearsal_enabled_from(
        cfg!(feature = "division-rehearsal"),
        std::env::var(DIVISION_REHEARSAL_OPERATOR_ENV)
            .ok()
            .as_deref(),
    )
}

fn division_rehearsal_enabled_from(feature_compiled: bool, operator_value: Option<&str>) -> bool {
    feature_compiled && matches!(operator_value, Some("true"))
}

fn sensory_semantic_projection_bias(
    floor: f32,
    energy_gain: f32,
    energy: f32,
    delta_gain: f32,
    delta: f32,
) -> f32 {
    let energy = if energy.is_finite() {
        energy.max(0.0)
    } else {
        0.0
    };
    let delta = if delta.is_finite() {
        delta.max(0.0)
    } else {
        0.0
    };
    let drive = energy_gain * energy + delta_gain * delta;
    if drive <= 1.0e-6 {
        0.0
    } else {
        (floor + drive).clamp(-0.75, 0.75)
    }
}

#[derive(Debug)]
pub struct DivisionInboxCommandV1 {
    pub command: DivisionCommandV1,
    pub source_path: PathBuf,
}

pub fn read_division_inbox(workspace: &Path) -> Result<Vec<DivisionInboxCommandV1>> {
    let inbox = workspace.join("division").join("inbox");
    fs::create_dir_all(&inbox)?;
    let rejected = workspace.join("division").join("rejected");
    fs::create_dir_all(&rejected)?;
    let mut paths: Vec<PathBuf> = fs::read_dir(&inbox)?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
        .collect();
    paths.sort();
    let mut commands = Vec::new();
    for path in paths {
        match fs::read_to_string(&path)
            .map_err(anyhow::Error::from)
            .and_then(|text| serde_json::from_str::<DivisionCommandV1>(&text).map_err(Into::into))
        {
            Ok(command) => commands.push(DivisionInboxCommandV1 {
                command,
                source_path: path,
            }),
            Err(error) => {
                let name = path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("invalid-command.json");
                let destination = rejected.join(name);
                fs::rename(&path, &destination)?;
                fs::write(
                    destination.with_extension("error.txt"),
                    format!("invalid division command artifact: {error:#}\n"),
                )?;
            }
        }
    }
    Ok(commands)
}

pub fn archive_division_inbox_command(
    workspace: &Path,
    source_path: &Path,
    receipt: &DivisionReceiptV1,
) -> Result<()> {
    let processed = workspace.join("division").join("processed");
    fs::create_dir_all(&processed)?;
    let original = source_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("command.json");
    let destination = processed.join(format!(
        "{}-{}",
        safe_component(&receipt.receipt_id),
        original
    ));
    if source_path.exists() {
        fs::rename(source_path, &destination)?;
    }
    write_json_atomic(&destination.with_extension("receipt.json"), receipt)
}

pub fn load_or_create_parent_generation(workspace: &Path) -> Result<u64> {
    let path = workspace.join("division").join("parent_generation.json");
    if let Some(value) = fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
    {
        if let Some(generation) = value.get("generation").and_then(Value::as_u64) {
            return Ok(generation);
        }
    }
    write_json_atomic(
        &path,
        &json!({
            "schema": "division.parent_generation.v1",
            "generation": 0,
            "source": "first_native_generation",
        }),
    )?;
    Ok(0)
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StableFieldCaptureV2 {
    pub dimension: usize,
    pub covariance: Vec<f32>,
    pub top_k_basis: Vec<f32>,
    pub eigenvalues: Vec<f32>,
    pub sensory_fill_pct: f32,
    pub estimator_state: Value,
    pub pi_state: Value,
    pub projection_matrix: Vec<f32>,
    pub projection_config: Value,
    pub backlog_state: Value,
    pub staleness_state: Value,
    pub recovery_stage: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RuntimeCaptureV2 {
    pub input_state: Value,
    pub scheduler: Value,
    pub safety_supervisor: Value,
    pub regulator: Value,
    pub source_identity: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ArrayBlobV2 {
    path: String,
    dtype: String,
    endian: String,
    shape: Vec<usize>,
    byte_length: usize,
    sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct NativeBundleManifestV2 {
    schema: String,
    protocol_version: String,
    division_id: String,
    plan_digest: String,
    source_generation: u64,
    created_at_unix_ms: u64,
    source_identity: Value,
    build_identity: Value,
    reservoir_dimension: usize,
    sensory_field_dimension: usize,
    live_commit_eligible: bool,
    live_commit_blocking_reasons: Vec<String>,
    esn_scalars: Value,
    runtime: RuntimeCaptureV2,
    stable_field: Value,
    arrays: BTreeMap<String, ArrayBlobV2>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct PersistedCoordinatorState {
    parent_generation: u64,
    lifecycle: DivisionLifecycleV1,
    division_id: String,
    plan_digest: String,
    parent_authoritative: bool,
    astrid_assent: bool,
    minime_assent: bool,
    selected_strategy: Option<String>,
    bridge_scale: f64,
    current_tick: u64,
    rollback_deadline_tick: Option<u64>,
    healthy_zero_bridge_ticks: u64,
    snapshot_refs: Vec<String>,
    readiness: DivisionReadinessV1,
    receipts: BTreeMap<String, DivisionReceiptV1>,
    #[serde(default)]
    consumed_capability_tokens: BTreeMap<String, String>,
    sequence: u64,
}

impl PersistedCoordinatorState {
    fn idle(parent_generation: u64) -> Self {
        Self {
            parent_generation,
            lifecycle: DivisionLifecycleV1::Idle,
            division_id: String::new(),
            plan_digest: String::new(),
            parent_authoritative: true,
            astrid_assent: false,
            minime_assent: false,
            selected_strategy: None,
            bridge_scale: 1.0,
            current_tick: 0,
            rollback_deadline_tick: None,
            healthy_zero_bridge_ticks: 0,
            snapshot_refs: Vec::new(),
            readiness: blocked_readiness("division_not_prepared"),
            receipts: BTreeMap::new(),
            consumed_capability_tokens: BTreeMap::new(),
            sequence: 0,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct PersistedEventV1 {
    #[serde(flatten)]
    event: DivisionEventV1,
    state: PersistedCoordinatorState,
}

pub struct PreparedDivision {
    snapshot_ref: String,
    shadow: ShadowLab,
}

pub struct NativeDivisionCoordinator {
    division_dir: PathBuf,
    state: PersistedCoordinatorState,
    shadow: Option<ShadowLab>,
}

impl NativeDivisionCoordinator {
    pub fn open(workspace: &Path, parent_generation: u64) -> Result<Self> {
        let division_dir = workspace.join("division");
        fs::create_dir_all(division_dir.join("receipts"))?;
        fs::create_dir_all(division_dir.join("checkpoints"))?;
        let event_path = division_dir.join("events.jsonl");
        let mut state = PersistedCoordinatorState::idle(parent_generation);
        if let Ok(text) = fs::read_to_string(&event_path) {
            for line in text.lines().filter(|line| !line.trim().is_empty()) {
                if let Ok(event) = serde_json::from_str::<PersistedEventV1>(line) {
                    state = event.state;
                }
            }
        }
        if state.parent_generation != parent_generation {
            state = PersistedCoordinatorState::idle(parent_generation);
        }
        let mut coordinator = Self {
            division_dir,
            state,
            shadow: None,
        };
        if matches!(
            coordinator.state.lifecycle,
            DivisionLifecycleV1::Preparing
                | DivisionLifecycleV1::Shadowing
                | DivisionLifecycleV1::Ready
        ) {
            coordinator.state.readiness = blocked_readiness("shadow_runtime_restore_required");
        }
        coordinator.write_status()?;
        Ok(coordinator)
    }

    #[must_use]
    pub fn lifecycle(&self) -> DivisionLifecycleV1 {
        self.state.lifecycle
    }

    #[must_use]
    pub fn parent_generation(&self) -> u64 {
        self.state.parent_generation
    }

    pub fn handle_command<F>(
        &mut self,
        command: DivisionCommandV1,
        now_unix_ms: u64,
        prepare: F,
    ) -> DivisionReceiptV1
    where
        F: FnOnce() -> Result<PreparedDivision>,
    {
        if let Some(receipt) = self.state.receipts.get(&command.idempotency_key) {
            return receipt.clone();
        }

        let result = self.apply_command(&command, now_unix_ms, prepare);
        let (status, reason) = match result {
            Ok(reason) => (DivisionReceiptStatusV1::Accepted, reason),
            Err(CommandBlock::Policy(reason)) => (DivisionReceiptStatusV1::PolicyBlocked, reason),
            Err(CommandBlock::Rejected(reason)) => (DivisionReceiptStatusV1::Rejected, reason),
        };
        let receipt = DivisionReceiptV1 {
            schema: DIVISION_RECEIPT_SCHEMA_V1.to_string(),
            receipt_id: receipt_id(&command),
            idempotency_key: command.idempotency_key.clone(),
            division_id: command.division_id.clone(),
            action: command.action,
            status,
            lifecycle: self.state.lifecycle,
            reason,
            created_at_unix_ms: now_unix_ms,
        };
        if receipt.status == DivisionReceiptStatusV1::Accepted {
            if let Some(capability) = command.capability.as_ref() {
                self.state
                    .consumed_capability_tokens
                    .insert(capability.token_id.clone(), receipt.receipt_id.clone());
            }
        }
        self.state
            .receipts
            .insert(command.idempotency_key.clone(), receipt.clone());
        let _ = self.persist(
            "command_receipt",
            now_unix_ms,
            json!({"receipt": receipt, "source": command.source}),
        );
        let _ = write_json_atomic(
            &self
                .division_dir
                .join("receipts")
                .join(format!("{}.json", safe_component(&command.idempotency_key))),
            &receipt,
        );
        receipt
    }

    fn apply_command<F>(
        &mut self,
        command: &DivisionCommandV1,
        now_unix_ms: u64,
        prepare: F,
    ) -> std::result::Result<String, CommandBlock>
    where
        F: FnOnce() -> Result<PreparedDivision>,
    {
        if !command.is_well_formed(now_unix_ms) {
            return Err(CommandBlock::Rejected(
                "command schema, identity, digest, or expiry invalid".to_string(),
            ));
        }
        if !command.authority_shape_is_valid(now_unix_ms) {
            return Err(CommandBlock::Rejected(
                "action-specific authority shape invalid".to_string(),
            ));
        }
        if command.expected_parent_generation != self.state.parent_generation {
            return Err(CommandBlock::Rejected(
                "stale_parent_generation".to_string(),
            ));
        }
        if let Some(capability) = command.capability.as_ref() {
            if self
                .state
                .consumed_capability_tokens
                .contains_key(&capability.token_id)
            {
                return Err(CommandBlock::Rejected(
                    "one_shot_capability_already_consumed".to_string(),
                ));
            }
        }
        let terminal = matches!(
            self.state.lifecycle,
            DivisionLifecycleV1::Aborted
                | DivisionLifecycleV1::RolledBack
                | DivisionLifecycleV1::Failed
        );
        let replacing_terminal = command.action == DivisionActionV1::DivisionPrepare && terminal;
        if !self.state.division_id.is_empty()
            && !replacing_terminal
            && (command.division_id != self.state.division_id
                || command.plan_digest != self.state.plan_digest)
        {
            return Err(CommandBlock::Rejected(
                "active_division_or_plan_digest_mismatch".to_string(),
            ));
        }

        match command.action {
            DivisionActionV1::DivisionStatus => Ok("status_available".to_string()),
            DivisionActionV1::DivisionPrepare => {
                if !matches!(
                    self.state.lifecycle,
                    DivisionLifecycleV1::Idle
                        | DivisionLifecycleV1::Aborted
                        | DivisionLifecycleV1::RolledBack
                        | DivisionLifecycleV1::Failed
                ) {
                    return Err(CommandBlock::Rejected(
                        "division_already_active".to_string(),
                    ));
                }
                if !matches!(command.source.being.as_str(), "astrid" | "minime") {
                    return Err(CommandBlock::Rejected(
                        "prepare_requires_being_source".to_string(),
                    ));
                }
                self.state.lifecycle = DivisionLifecycleV1::Preparing;
                self.state.division_id.clone_from(&command.division_id);
                self.state.plan_digest.clone_from(&command.plan_digest);
                let prepared = prepare().map_err(|error| {
                    self.state.lifecycle = DivisionLifecycleV1::Failed;
                    CommandBlock::Rejected(format!("prepare_snapshot_failed:{error:#}"))
                })?;
                self.state.snapshot_refs = vec![prepared.snapshot_ref];
                self.shadow = Some(prepared.shadow);
                self.state.lifecycle = DivisionLifecycleV1::Shadowing;
                self.state.parent_authoritative = true;
                self.state.astrid_assent = false;
                self.state.minime_assent = false;
                self.state.selected_strategy = None;
                self.state.bridge_scale = 1.0;
                self.state.current_tick = 0;
                self.state.rollback_deadline_tick = None;
                self.state.healthy_zero_bridge_ticks = 0;
                self.state.readiness = blocked_readiness("shadow_window_incomplete");
                Ok("parent checkpointed; daughter candidates shadowing".to_string())
            }
            DivisionActionV1::DivisionAssent => {
                if !matches!(
                    self.state.lifecycle,
                    DivisionLifecycleV1::Shadowing | DivisionLifecycleV1::Ready
                ) {
                    return Err(CommandBlock::Rejected("assent_not_available".to_string()));
                }
                match command.source.being.as_str() {
                    "astrid" => self.state.astrid_assent = true,
                    "minime" => self.state.minime_assent = true,
                    _ => {
                        return Err(CommandBlock::Rejected(
                            "assent_requires_astrid_or_minime".to_string(),
                        ));
                    }
                }
                Ok(format!("{} assent recorded", command.source.being))
            }
            DivisionActionV1::DivisionAbort => {
                if matches!(
                    self.state.lifecycle,
                    DivisionLifecycleV1::Idle
                        | DivisionLifecycleV1::Aborted
                        | DivisionLifecycleV1::RolledBack
                        | DivisionLifecycleV1::Failed
                ) {
                    return Err(CommandBlock::Rejected(
                        "abort_requires_active_precommit_division".to_string(),
                    ));
                }
                if matches!(
                    self.state.lifecycle,
                    DivisionLifecycleV1::Committing
                        | DivisionLifecycleV1::Cytokinesis
                        | DivisionLifecycleV1::Finalized
                ) {
                    return Err(CommandBlock::Rejected(
                        "abort_not_available_after_commit".to_string(),
                    ));
                }
                if !matches!(command.source.being.as_str(), "astrid" | "minime") {
                    return Err(CommandBlock::Rejected(
                        "abort_requires_being_source".to_string(),
                    ));
                }
                self.state.lifecycle = DivisionLifecycleV1::Aborted;
                self.state.parent_authoritative = true;
                self.shadow = None;
                Ok("division aborted; parent remains authoritative".to_string())
            }
            DivisionActionV1::DivisionCommit => {
                if !NATIVE_COMMIT_ENABLED {
                    return Err(CommandBlock::Policy(
                        "native_commit_feature_disabled_pending_three_rehearsals".to_string(),
                    ));
                }
                if self.state.lifecycle != DivisionLifecycleV1::Ready
                    || !self.state.readiness.ready
                    || !self.state.astrid_assent
                    || !self.state.minime_assent
                {
                    return Err(CommandBlock::Policy(
                        "readiness_and_both_current_assents_required".to_string(),
                    ));
                }
                self.state.lifecycle = DivisionLifecycleV1::Cytokinesis;
                self.state.parent_authoritative = false;
                self.state.rollback_deadline_tick = Some(
                    self.state
                        .current_tick
                        .saturating_add(ROLLBACK_WINDOW_TICKS),
                );
                Ok("daughter ownership switched; rollback parent retained".to_string())
            }
            DivisionActionV1::DivisionRollback => {
                if self.state.lifecycle != DivisionLifecycleV1::Cytokinesis {
                    return Err(CommandBlock::Rejected(
                        "rollback_only_available_during_grace_window".to_string(),
                    ));
                }
                if self
                    .state
                    .rollback_deadline_tick
                    .is_some_and(|deadline| self.state.current_tick > deadline)
                {
                    return Err(CommandBlock::Rejected(
                        "rollback_window_expired".to_string(),
                    ));
                }
                self.rollback("manual_or_safety_rollback");
                Ok("rolled back to authoritative parent".to_string())
            }
        }
    }

    pub fn observe_parent_tick(
        &mut self,
        parent: &ESN,
        input: &[f32],
        sensory_fill_pct: f32,
        metrics_fresh: bool,
        actuator_saturated: bool,
    ) -> Result<()> {
        if !matches!(
            self.state.lifecycle,
            DivisionLifecycleV1::Shadowing
                | DivisionLifecycleV1::Ready
                | DivisionLifecycleV1::Cytokinesis
        ) {
            return Ok(());
        }
        let Some(shadow) = self.shadow.as_mut() else {
            self.state.readiness = blocked_readiness("shadow_runtime_restore_required");
            self.write_status()?;
            return Ok(());
        };
        shadow.step(
            parent,
            input,
            sensory_fill_pct,
            metrics_fresh,
            actuator_saturated,
            self.state.bridge_scale as f32,
        )?;
        self.state.current_tick = shadow.ticks;
        if self.state.lifecycle == DivisionLifecycleV1::Cytokinesis {
            self.write_status()?;
            return Ok(());
        }
        if shadow.ticks >= SHADOW_MIN_TICKS {
            if let Some((strategy, readiness)) = shadow.select_ready_candidate() {
                self.state.selected_strategy = Some(strategy);
                self.state.readiness = readiness;
                self.state.lifecycle = DivisionLifecycleV1::Ready;
            } else {
                self.state.readiness = shadow.best_readiness();
                self.state.lifecycle = DivisionLifecycleV1::Shadowing;
            }
        } else {
            self.state.readiness = shadow.best_readiness();
        }
        self.write_status()?;
        Ok(())
    }

    pub fn safety_tick(&mut self, healthy: bool, panic: bool, action: &str) -> Result<()> {
        if self.state.lifecycle != DivisionLifecycleV1::Cytokinesis {
            return Ok(());
        }
        let daughter_violation = self.shadow.as_ref().is_some_and(|shadow| {
            shadow.hard_safety_violation(self.state.selected_strategy.as_deref())
        });
        if panic || daughter_violation {
            self.rollback("hard_safety_violation");
            self.persist(
                "automatic_rollback",
                now_unix_ms(),
                json!({"parent_panic": panic, "daughter_violation": daughter_violation}),
            )?;
            return Ok(());
        }
        let daughter_healthy = self
            .shadow
            .as_ref()
            .is_some_and(|shadow| shadow.selected_healthy(self.state.selected_strategy.as_deref()));
        let healthy = healthy && daughter_healthy;
        if action == "isolate" {
            self.state.bridge_scale = 0.0;
        } else if action != "hold" && healthy {
            self.state.bridge_scale =
                (self.state.bridge_scale - 1.0 / BRIDGE_ANNEAL_TICKS as f64).max(0.0);
        }
        self.state.healthy_zero_bridge_ticks = if self.state.bridge_scale == 0.0 && healthy {
            self.state.healthy_zero_bridge_ticks.saturating_add(1)
        } else {
            0
        };
        if self.state.healthy_zero_bridge_ticks >= FINALIZE_HEALTHY_TICKS {
            self.state.lifecycle = DivisionLifecycleV1::Finalized;
            self.state.rollback_deadline_tick = None;
        }
        self.write_status()
    }

    fn rollback(&mut self, _reason: &str) {
        self.state.lifecycle = DivisionLifecycleV1::RolledBack;
        self.state.parent_authoritative = true;
        self.state.bridge_scale = 1.0;
        self.state.rollback_deadline_tick = None;
    }

    pub fn status(&self) -> DivisionStatusV1 {
        let mut extensions = serde_json::Map::new();
        extensions.insert(
            "native_commit_block".to_string(),
            json!("compile_time_false_pending_three_commit_disabled_rehearsals"),
        );
        extensions.insert(
            "rehearsal_dispatch_enabled".to_string(),
            json!(division_rehearsal_enabled()),
        );
        extensions.insert(
            "shadow_runtime_attached".to_string(),
            json!(self.shadow.is_some()),
        );
        if let Some(shadow) = self.shadow.as_ref() {
            extensions.insert("candidates".to_string(), shadow.status_json());
            extensions.insert(
                "restore_equivalence_100_ticks".to_string(),
                json!({
                    "samples": shadow.restore_samples,
                    "max_abs": shadow.restore_max_abs,
                    "passed": shadow.restore_samples >= 100 && shadow.restore_max_abs <= 1.0e-6,
                }),
            );
            extensions.insert(
                "sensory_field_inheritance".to_string(),
                json!("cloned_not_partitioned"),
            );
        }
        let mut status = DivisionStatusV1 {
            schema: DIVISION_STATUS_SCHEMA_V1.to_string(),
            division_id: self.state.division_id.clone(),
            parent_generation: self.state.parent_generation,
            plan_digest: self.state.plan_digest.clone(),
            lifecycle: self.state.lifecycle,
            parent_authoritative: self.state.parent_authoritative,
            commit_feature_enabled: NATIVE_COMMIT_ENABLED,
            selected_strategy: self.state.selected_strategy.clone(),
            astrid_assent: self.state.astrid_assent,
            minime_assent: self.state.minime_assent,
            bridge_scale: self.state.bridge_scale,
            current_tick: self.state.current_tick,
            rollback_deadline_tick: self.state.rollback_deadline_tick,
            snapshot_refs: self.state.snapshot_refs.clone(),
            readiness: self.state.readiness.clone(),
            visual_evidence_advisory_only: true,
            extensions,
        };
        status.extensions.insert(
            "action_availability_v1".to_string(),
            json!({
                "astrid": status.action_availability_for("astrid"),
                "minime": status.action_availability_for("minime"),
            }),
        );
        status
    }

    fn persist(&mut self, kind: &str, created_at_unix_ms: u64, details: Value) -> Result<()> {
        self.state.sequence = self.state.sequence.saturating_add(1);
        let event = PersistedEventV1 {
            event: DivisionEventV1 {
                schema: DIVISION_EVENT_SCHEMA_V1.to_string(),
                sequence: self.state.sequence,
                division_id: self.state.division_id.clone(),
                lifecycle: self.state.lifecycle,
                kind: kind.to_string(),
                created_at_unix_ms,
                details,
            },
            state: self.state.clone(),
        };
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.division_dir.join("events.jsonl"))?;
        serde_json::to_writer(&mut file, &event)?;
        file.write_all(b"\n")?;
        file.sync_data()?;
        self.write_status()
    }

    fn write_status(&self) -> Result<()> {
        write_json_atomic(&self.division_dir.join("status.json"), &self.status())
    }
}

enum CommandBlock {
    Rejected(String),
    Policy(String),
}

pub fn prepare_native_division(
    workspace: &Path,
    command: &DivisionCommandV1,
    parent: &mut ESN,
    stable_field: StableFieldCaptureV2,
    runtime: RuntimeCaptureV2,
    gpu: &Gpu,
) -> Result<PreparedDivision> {
    let snapshot = parent.snapshot_v2()?;
    if snapshot.res_size != 128 {
        return Err(anyhow!("first native division requires a 128-node parent"));
    }
    let checkpoint_dir = workspace
        .join("division")
        .join("checkpoints")
        .join(safe_component(&command.division_id))
        .join("parent");
    let snapshot_ref =
        write_bundle_v2_atomic(&checkpoint_dir, command, &snapshot, &stable_field, &runtime)?;
    let shadow = ShadowLab::new(&snapshot, &stable_field, gpu)?;
    Ok(PreparedDivision {
        snapshot_ref,
        shadow,
    })
}

struct ShadowLab {
    candidates: Vec<ShadowCandidate>,
    parent_replay: ESN,
    restore_samples: u64,
    restore_max_abs: f64,
    ticks: u64,
}

impl ShadowLab {
    fn new(parent: &EsnSnapshotV2, stable_field: &StableFieldCaptureV2, gpu: &Gpu) -> Result<Self> {
        let strategies = [
            PartitionStrategy::InputRecurrence,
            PartitionStrategy::Contiguous,
        ];
        let mut candidates = Vec::new();
        for strategy in strategies {
            candidates.push(ShadowCandidate::new(parent, stable_field, strategy, gpu)?);
        }
        Ok(Self {
            candidates,
            parent_replay: ESN::from_snapshot_v2(parent, gpu)?,
            restore_samples: 0,
            restore_max_abs: 0.0,
            ticks: 0,
        })
    }

    fn step(
        &mut self,
        parent: &ESN,
        input: &[f32],
        sensory_fill_pct: f32,
        metrics_fresh: bool,
        actuator_saturated: bool,
        bridge_scale: f32,
    ) -> Result<()> {
        let trace = parent.last_step_trace();
        self.parent_replay.step_shadow(
            input,
            &vec![0.0; parent.res_size],
            &trace.noise,
            trace.leak,
        )?;
        if self.restore_samples < 100 {
            let max_abs = max_abs_difference(&parent.x, &self.parent_replay.x);
            self.restore_max_abs = self.restore_max_abs.max(max_abs);
            self.restore_samples = self.restore_samples.saturating_add(1);
        }
        self.ticks = self.ticks.saturating_add(1);
        for candidate in &mut self.candidates {
            candidate.step(
                parent,
                input,
                sensory_fill_pct,
                metrics_fresh,
                actuator_saturated,
                bridge_scale,
            )?;
        }
        Ok(())
    }

    fn select_ready_candidate(&self) -> Option<(String, DivisionReadinessV1)> {
        let mut ready: Vec<_> = self
            .candidates
            .iter()
            .filter_map(|candidate| {
                let readiness = candidate.readiness(self.restore_samples, self.restore_max_abs);
                readiness.ready.then_some((candidate, readiness))
            })
            .collect();
        ready.sort_by(|(left, _), (right, _)| left.selection_cmp(right));
        ready
            .into_iter()
            .next()
            .map(|(candidate, readiness)| (candidate.strategy.as_str().to_string(), readiness))
    }

    fn best_readiness(&self) -> DivisionReadinessV1 {
        self.candidates
            .iter()
            .map(|candidate| candidate.readiness(self.restore_samples, self.restore_max_abs))
            .min_by_key(|readiness| readiness.blocking_reasons.len())
            .unwrap_or_else(|| blocked_readiness("no_partition_candidates"))
    }

    fn status_json(&self) -> Value {
        Value::Array(
            self.candidates
                .iter()
                .map(|candidate| {
                    json!({
                        "strategy": candidate.strategy.as_str(),
                        "minime_role": "more_input_driven",
                        "astrid_role": "more_recurrence_driven",
                        "covariance_partition_loss": candidate.covariance_partition_loss,
                        "sensory_fields": {
                            "inheritance": "independent_clones",
                            "dimension": candidate.minime_sensory_field.dimension,
                            "minime_fill_pct": candidate.minime_sensory_field.fill_pct,
                            "astrid_fill_pct": candidate.astrid_sensory_field.fill_pct,
                            "minime_ticks": candidate.minime_sensory_field.ticks,
                            "astrid_ticks": candidate.astrid_sensory_field.ticks,
                        },
                        "readiness": candidate.readiness(self.restore_samples, self.restore_max_abs),
                    })
                })
                .collect(),
        )
    }

    fn hard_safety_violation(&self, selected_strategy: Option<&str>) -> bool {
        self.candidates
            .iter()
            .filter(|candidate| {
                selected_strategy.is_none_or(|selected| candidate.strategy.as_str() == selected)
            })
            .any(|candidate| {
                let collapse = candidate
                    .samples
                    .back()
                    .is_some_and(|sample| sample.collapse);
                let sustained_panic = candidate
                    .samples
                    .iter()
                    .rev()
                    .take(3)
                    .filter(|sample| sample.metrics_fresh && sample.panic)
                    .count()
                    >= 3;
                let saturated = candidate
                    .samples
                    .iter()
                    .rev()
                    .take(10)
                    .filter(|sample| sample.metrics_fresh && sample.actuator_saturated)
                    .count()
                    >= 10;
                collapse || sustained_panic || saturated
            })
    }

    fn selected_healthy(&self, selected_strategy: Option<&str>) -> bool {
        self.candidates
            .iter()
            .find(|candidate| {
                selected_strategy.is_none_or(|selected| candidate.strategy.as_str() == selected)
            })
            .and_then(|candidate| candidate.samples.back())
            .is_some_and(|sample| {
                sample.metrics_fresh
                    && sample.sensory_fill_pct < 80.0
                    && sample.regulator_distance <= 0.20
                    && !sample.actuator_saturated
                    && !sample.panic
                    && !sample.collapse
            })
    }
}

#[derive(Clone, Copy)]
enum PartitionStrategy {
    InputRecurrence,
    Contiguous,
}

impl PartitionStrategy {
    const fn as_str(self) -> &'static str {
        match self {
            Self::InputRecurrence => "input_recurrence",
            Self::Contiguous => "contiguous",
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct ShadowMetric {
    state_error_sq: f64,
    state_ref_sq: f64,
    cosine: f64,
    readout_error_sq: f64,
    readout_ref_sq: f64,
    sensory_fill_pct: f64,
    coupling_coverage: f64,
    regulator_distance: f64,
    metrics_fresh: bool,
    actuator_saturated: bool,
    panic: bool,
    collapse: bool,
}

/// A separately allocated and evolved copy of Minime's 512D projected sensory
/// field. It is deliberately not indexed by reservoir daughter neurons.
struct SensoryFieldShadow {
    dimension: usize,
    input_dimension: usize,
    covariance: Vec<f32>,
    projection_matrix: Vec<f32>,
    dimension_scales: Vec<f32>,
    projection_scale: f32,
    activation_gain: f32,
    semantic_energy_gain: f32,
    semantic_delta_gain: f32,
    semantic_bias_floor: f32,
    previous_semantic: Vec<f32>,
    basis: Vec<f32>,
    eigenvalues: Vec<f32>,
    estimator: EigenFillEstimator,
    rho: f32,
    fill_pct: f32,
    ticks: u64,
}

impl SensoryFieldShadow {
    fn from_capture(capture: &StableFieldCaptureV2, input_dimension: usize) -> Result<Self> {
        if capture.dimension != 512
            || capture.covariance.len() != capture.dimension * capture.dimension
            || capture.projection_matrix.len() != capture.dimension * input_dimension
        {
            return Err(anyhow!("invalid sensory-field clone dimensions"));
        }
        let projection_scale = capture
            .projection_config
            .get("projection_scale")
            .and_then(Value::as_f64)
            .unwrap_or(0.18) as f32;
        let dimension_scales = capture
            .projection_config
            .get("dimension_scales")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .map(|value| value.as_f64().unwrap_or(1.0) as f32)
                    .collect::<Vec<_>>()
            })
            .filter(|values| values.len() == input_dimension)
            .unwrap_or_else(|| vec![1.0; input_dimension]);
        let config_f32 = |key: &str, fallback: f32| {
            capture
                .projection_config
                .get(key)
                .and_then(Value::as_f64)
                .unwrap_or(f64::from(fallback)) as f32
        };
        let estimator =
            serde_json::from_value::<EigenFillEstimatorSnapshotV1>(capture.estimator_state.clone())
                .map(|snapshot| EigenFillEstimator::from_snapshot_v1(&snapshot))
                .unwrap_or_else(|_| {
                    EigenFillEstimator::fixed_survival(capture.eigenvalues.len().max(1))
                });
        let mode_count = capture.eigenvalues.len();
        if mode_count == 0 || capture.top_k_basis.len() != capture.dimension * mode_count {
            return Err(anyhow!("invalid sensory-field top-k basis dimensions"));
        }
        Ok(Self {
            dimension: capture.dimension,
            input_dimension,
            covariance: capture.covariance.clone(),
            projection_matrix: capture.projection_matrix.clone(),
            dimension_scales,
            projection_scale: projection_scale.clamp(0.0, 4.0),
            activation_gain: config_f32("activation_gain", 1.0).clamp(0.0, 4.0),
            semantic_energy_gain: config_f32("semantic_energy_gain", 0.028),
            semantic_delta_gain: config_f32("semantic_delta_gain", 0.045),
            semantic_bias_floor: config_f32("semantic_bias_floor", 0.010),
            previous_semantic: vec![0.0; input_dimension.saturating_sub(18)],
            basis: capture.top_k_basis.clone(),
            eigenvalues: capture.eigenvalues.clone(),
            estimator,
            rho: config_f32("covariance_keep", 0.955).clamp(0.0, 0.9999),
            fill_pct: capture.sensory_fill_pct,
            ticks: 0,
        })
    }

    fn step(&mut self, input: &[f32]) -> Result<f32> {
        if input.len() != self.input_dimension || !input.iter().all(|value| value.is_finite()) {
            return Err(anyhow!("invalid sensory-field shadow input"));
        }
        let semantic_offset = 18.min(self.input_dimension);
        let mut projection_input = input.to_vec();
        let semantic = &input[semantic_offset..];
        let (semantic_energy, semantic_delta) = if semantic.is_empty() {
            (0.0, 0.0)
        } else {
            let mean = semantic.iter().copied().sum::<f32>() / semantic.len() as f32;
            let variance = semantic
                .iter()
                .map(|value| (*value - mean).powi(2))
                .sum::<f32>()
                / semantic.len() as f32;
            let scale = if variance.sqrt() > 1.0e-3 {
                variance.sqrt().recip()
            } else {
                1.0
            };
            for (destination, source) in
                projection_input[semantic_offset..].iter_mut().zip(semantic)
            {
                *destination = (*source - mean) * scale;
            }
            let energy = (semantic.iter().map(|value| value * value).sum::<f32>()
                / semantic.len() as f32)
                .sqrt();
            let delta = semantic
                .iter()
                .zip(&self.previous_semantic)
                .map(|(left, right)| (*left - *right).abs())
                .sum::<f32>()
                / semantic.len() as f32;
            self.previous_semantic.copy_from_slice(semantic);
            (energy, delta)
        };
        let semantic_bias = sensory_semantic_projection_bias(
            self.semantic_bias_floor,
            self.semantic_energy_gain,
            semantic_energy,
            self.semantic_delta_gain,
            semantic_delta,
        );
        let activated: Vec<f32> = projection_input
            .iter()
            .zip(&self.dimension_scales)
            .enumerate()
            .map(|(index, (value, scale))| {
                let bias = if index >= semantic_offset {
                    semantic_bias
                } else {
                    0.0
                };
                (value * scale * self.activation_gain + bias).tanh()
            })
            .collect();
        let mut projected = vec![0.0_f32; self.dimension];
        for (row, projected_value) in projected.iter_mut().enumerate() {
            let start = row * self.input_dimension;
            let raw: f32 = self.projection_matrix[start..start + self.input_dimension]
                .iter()
                .zip(&activated)
                .map(|(weight, value)| weight * value)
                .sum();
            *projected_value = raw * self.projection_scale;
        }
        let inject = 1.0 - self.rho;
        for (row, left) in projected.iter().enumerate() {
            let start = row * self.dimension;
            for (column, right) in projected.iter().enumerate() {
                let slot = &mut self.covariance[start + column];
                *slot = self.rho * *slot + inject * *left * *right;
            }
        }
        for (mode_index, eigenvalue) in self.eigenvalues.iter_mut().enumerate() {
            let basis = &self.basis[mode_index * self.dimension..(mode_index + 1) * self.dimension];
            let coefficient = basis
                .iter()
                .zip(&projected)
                .map(|(left, right)| left * right)
                .sum::<f32>();
            *eigenvalue = (self.rho * *eigenvalue + inject * coefficient * coefficient).max(0.0);
        }
        self.fill_pct = self.estimator.update(&self.eigenvalues) * 100.0;
        self.ticks = self.ticks.saturating_add(1);
        if !self.fill_pct.is_finite()
            || !self.covariance.iter().all(|value| value.is_finite())
            || !self.eigenvalues.iter().all(|value| value.is_finite())
        {
            return Err(anyhow!("sensory-field shadow became non-finite"));
        }
        Ok(self.fill_pct)
    }
}

struct ShadowCandidate {
    strategy: PartitionStrategy,
    minime: ESN,
    astrid: ESN,
    minime_indices: Vec<usize>,
    astrid_indices: Vec<usize>,
    bridge_from_astrid: Vec<f32>,
    bridge_from_minime: Vec<f32>,
    minime_sensory_field: SensoryFieldShadow,
    astrid_sensory_field: SensoryFieldShadow,
    covariance_partition_loss: f64,
    first_tick_max_abs: Option<f64>,
    samples: VecDeque<ShadowMetric>,
    total_samples: u64,
}

impl ShadowCandidate {
    fn new(
        parent: &EsnSnapshotV2,
        stable_field: &StableFieldCaptureV2,
        strategy: PartitionStrategy,
        gpu: &Gpu,
    ) -> Result<Self> {
        let (minime_indices, astrid_indices) = partition_indices(parent, strategy);
        let minime_snapshot = daughter_snapshot(parent, &minime_indices, 0x4d49_4e49_4d45)?;
        let astrid_snapshot = daughter_snapshot(parent, &astrid_indices, 0x4153_5452_4944)?;
        let bridge_from_astrid = cross_block(
            &parent.wres,
            parent.res_size,
            &minime_indices,
            &astrid_indices,
        );
        let bridge_from_minime = cross_block(
            &parent.wres,
            parent.res_size,
            &astrid_indices,
            &minime_indices,
        );
        let covariance_partition_loss = covariance_partition_loss(
            &parent.spectral.covariance,
            parent.res_size,
            &minime_indices,
            &astrid_indices,
        );
        Ok(Self {
            strategy,
            minime: ESN::from_snapshot_v2(&minime_snapshot, gpu)?,
            astrid: ESN::from_snapshot_v2(&astrid_snapshot, gpu)?,
            minime_indices,
            astrid_indices,
            bridge_from_astrid,
            bridge_from_minime,
            minime_sensory_field: SensoryFieldShadow::from_capture(stable_field, parent.in_size)?,
            astrid_sensory_field: SensoryFieldShadow::from_capture(stable_field, parent.in_size)?,
            covariance_partition_loss,
            first_tick_max_abs: None,
            samples: VecDeque::with_capacity(FINAL_WINDOW),
            total_samples: 0,
        })
    }

    fn step(
        &mut self,
        parent: &ESN,
        input: &[f32],
        _sensory_fill_pct: f32,
        metrics_fresh: bool,
        actuator_saturated: bool,
        bridge_scale: f32,
    ) -> Result<()> {
        let minime_prev = self.minime.x.clone();
        let astrid_prev = self.astrid.x.clone();
        let mut minime_drive = matvec(&self.bridge_from_astrid, self.minime.res_size, &astrid_prev);
        let mut astrid_drive = matvec(&self.bridge_from_minime, self.astrid.res_size, &minime_prev);
        let scale = bridge_scale.clamp(0.0, 1.0);
        for value in &mut minime_drive {
            *value *= scale;
        }
        for value in &mut astrid_drive {
            *value *= scale;
        }
        let trace = parent.last_step_trace();
        let minime_noise = select(&trace.noise, &self.minime_indices);
        let astrid_noise = select(&trace.noise, &self.astrid_indices);
        self.minime
            .step_shadow(input, &minime_drive, &minime_noise, trace.leak)?;
        self.astrid
            .step_shadow(input, &astrid_drive, &astrid_noise, trace.leak)?;
        let minime_sensory_fill = self.minime_sensory_field.step(input)?;
        let astrid_sensory_fill = self.astrid_sensory_field.step(input)?;
        let reconstructed = reconstruct(
            parent.res_size,
            &self.minime_indices,
            &self.minime.x,
            &self.astrid_indices,
            &self.astrid.x,
        );
        let max_abs = max_abs_difference(&parent.x, &reconstructed);
        if self.first_tick_max_abs.is_none() {
            self.first_tick_max_abs = Some(max_abs);
        }
        let state_error_sq = squared_error(&parent.x, &reconstructed);
        let state_ref_sq = parent.x.iter().map(|value| f64::from(*value).powi(2)).sum();
        let cosine = cosine(&parent.x, &reconstructed);
        let parent_readout = parent.predict_readonly();
        let daughter_readout = self.minime.predict_readonly() + self.astrid.predict_readonly();
        let regulator_distance = ((self.minime.get_leak() - parent.get_leak()).abs()
            + (self.astrid.get_leak() - parent.get_leak()).abs())
            / 2.0;
        let max_sensory_fill = minime_sensory_fill.max(astrid_sensory_fill);
        let metric = ShadowMetric {
            state_error_sq,
            state_ref_sq,
            cosine,
            readout_error_sq: f64::from(daughter_readout - parent_readout).powi(2),
            readout_ref_sq: f64::from(parent_readout).powi(2),
            sensory_fill_pct: f64::from(max_sensory_fill),
            coupling_coverage: f64::from(scale),
            regulator_distance: f64::from(regulator_distance),
            metrics_fresh,
            actuator_saturated,
            panic: max_sensory_fill >= 90.0,
            collapse: !state_error_sq.is_finite() || !cosine.is_finite(),
        };
        if self.samples.len() >= FINAL_WINDOW {
            self.samples.pop_front();
        }
        self.samples.push_back(metric);
        self.total_samples = self.total_samples.saturating_add(1);
        Ok(())
    }

    fn readiness(&self, restore_samples: u64, restore_max_abs: f64) -> DivisionReadinessV1 {
        let mut reasons = Vec::new();
        let first_tick = self.first_tick_max_abs.unwrap_or(f64::INFINITY);
        if first_tick > 1.0e-6 {
            reasons.push("first_tick_equivalence".to_string());
        }
        if restore_samples < 100 || restore_max_abs > 1.0e-6 {
            reasons.push("deterministic_restore_100_ticks".to_string());
        }
        if self.total_samples < SHADOW_MIN_TICKS {
            reasons.push("shadow_window_incomplete".to_string());
        }
        if self.samples.len() < FINAL_WINDOW {
            reasons.push("final_window_incomplete".to_string());
        }
        let state_nrmse = ratio_nrmse(
            self.samples.iter().map(|sample| sample.state_error_sq),
            self.samples.iter().map(|sample| sample.state_ref_sq),
        );
        let readout_nrmse = ratio_nrmse(
            self.samples.iter().map(|sample| sample.readout_error_sq),
            self.samples.iter().map(|sample| sample.readout_ref_sq),
        );
        let state_cosine = mean(self.samples.iter().map(|sample| sample.cosine));
        let max_fill = self
            .samples
            .iter()
            .map(|sample| sample.sensory_fill_pct)
            .fold(0.0_f64, f64::max);
        let min_coupling = self
            .samples
            .iter()
            .map(|sample| sample.coupling_coverage)
            .fold(1.0_f64, f64::min);
        let max_regulator = self
            .samples
            .iter()
            .map(|sample| sample.regulator_distance)
            .fold(0.0_f64, f64::max);
        let metrics_fresh =
            !self.samples.is_empty() && self.samples.iter().all(|sample| sample.metrics_fresh);
        let saturation_streak = trailing_count(&self.samples, |sample| sample.actuator_saturated);
        let panic_streak = trailing_count(&self.samples, |sample| sample.panic);
        if state_nrmse > 0.30 {
            reasons.push("state_nrmse".to_string());
        }
        if state_cosine < 0.85 {
            reasons.push("state_cosine".to_string());
        }
        if readout_nrmse > 0.20 {
            reasons.push("readout_nrmse".to_string());
        }
        if max_fill >= 80.0 {
            reasons.push("sensory_fill_headroom".to_string());
        }
        if panic_streak >= 3 {
            reasons.push("sensory_fill_panic_streak".to_string());
        }
        if min_coupling < 0.80 {
            reasons.push("coupling_coverage".to_string());
        }
        if max_regulator > 0.20 {
            reasons.push("regulator_distance".to_string());
        }
        if !metrics_fresh {
            reasons.push("metrics_stale".to_string());
        }
        if saturation_streak >= 10 {
            reasons.push("actuator_saturation".to_string());
        }
        if self.samples.iter().any(|sample| sample.collapse) {
            reasons.push("collapse".to_string());
        }
        DivisionReadinessV1 {
            policy: DIVISION_READINESS_POLICY_V1.to_string(),
            ready: reasons.is_empty(),
            sample_count: self.total_samples,
            blocking_reasons: reasons,
            first_tick_max_abs: self.first_tick_max_abs,
            state_nrmse: state_nrmse.is_finite().then_some(state_nrmse),
            state_cosine: state_cosine.is_finite().then_some(state_cosine),
            readout_nrmse: readout_nrmse.is_finite().then_some(readout_nrmse),
            max_final_sensory_fill_pct: max_fill.is_finite().then_some(max_fill),
            min_coupling_coverage: min_coupling.is_finite().then_some(min_coupling),
            max_regulator_distance: max_regulator.is_finite().then_some(max_regulator),
            metrics_fresh,
            sensory_panic_streak: panic_streak.try_into().unwrap_or(u32::MAX),
            actuator_saturation_streak: saturation_streak.try_into().unwrap_or(u32::MAX),
        }
    }

    fn selection_cmp(&self, other: &Self) -> std::cmp::Ordering {
        let left = self.readiness(100, 0.0);
        let right = other.readiness(100, 0.0);
        left.state_nrmse
            .unwrap_or(f64::INFINITY)
            .total_cmp(&right.state_nrmse.unwrap_or(f64::INFINITY))
            .then_with(|| {
                left.readout_nrmse
                    .unwrap_or(f64::INFINITY)
                    .total_cmp(&right.readout_nrmse.unwrap_or(f64::INFINITY))
            })
            .then_with(|| {
                self.covariance_partition_loss
                    .total_cmp(&other.covariance_partition_loss)
            })
            .then_with(|| self.strategy.as_str().cmp(other.strategy.as_str()))
    }
}

fn partition_indices(
    parent: &EsnSnapshotV2,
    strategy: PartitionStrategy,
) -> (Vec<usize>, Vec<usize>) {
    let n = parent.res_size;
    let half = n / 2;
    let scores: Vec<f64> = (0..n)
        .map(|row| {
            let input: f64 = parent.win
                [row * (parent.in_size + 1)..(row + 1) * (parent.in_size + 1)]
                .iter()
                .take(parent.in_size)
                .map(|value| f64::from(value.abs()))
                .sum();
            let recurrence: f64 = parent.wres[row * n..(row + 1) * n]
                .iter()
                .map(|value| f64::from(value.abs()))
                .sum();
            input / recurrence.max(1.0e-12)
        })
        .collect();
    let (mut left, mut right) = match strategy {
        PartitionStrategy::InputRecurrence => {
            let mut order: Vec<_> = (0..n).collect();
            order.sort_by(|a, b| {
                scores[*b]
                    .partial_cmp(&scores[*a])
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            (order[..half].to_vec(), order[half..].to_vec())
        }
        PartitionStrategy::Contiguous => ((0..half).collect(), (half..n).collect()),
    };
    let left_score = mean(left.iter().map(|index| scores[*index]));
    let right_score = mean(right.iter().map(|index| scores[*index]));
    if right_score > left_score {
        std::mem::swap(&mut left, &mut right);
    }
    left.sort_unstable();
    right.sort_unstable();
    (left, right)
}

fn daughter_snapshot(
    parent: &EsnSnapshotV2,
    indices: &[usize],
    seed_tag: u64,
) -> Result<EsnSnapshotV2> {
    let n = parent.res_size;
    let d = indices.len();
    let input_cols = parent.in_size + 1;
    let win = indices
        .iter()
        .flat_map(|row| {
            parent.win[*row * input_cols..(*row + 1) * input_cols]
                .iter()
                .copied()
        })
        .collect();
    let wres = block(&parent.wres, n, indices, indices);
    let state = select(&parent.state, indices);
    let mut wout: Vec<f32> = indices.iter().map(|index| parent.wout[*index]).collect();
    wout.push(parent.wout[n] * 0.5);
    let mut p_indices = indices.to_vec();
    p_indices.push(n);
    let rls_p = block(&parent.rls_p, n + 1, &p_indices, &p_indices);
    let covariance = block(&parent.spectral.covariance, n, indices, indices);
    let mut eigenvector = select(&parent.spectral.eigenvector, indices);
    normalize(&mut eigenvector);
    let eig1 = rayleigh(&covariance, d, &eigenvector);
    let parent_rel = parent.spectral.eig1 / parent.spectral.ema_eig.max(1.0e-6);
    let ema_eig = eig1 / parent_rel.max(1.0e-6);
    let mut spectral: SpectralSnapshotV2 = parent.spectral.clone();
    spectral.dimension = d;
    spectral.covariance = covariance;
    spectral.eigenvector = eigenvector;
    spectral.eig1 = eig1;
    spectral.eig1_prev = eig1;
    spectral.ema_eig = ema_eig;
    spectral.last_profile.ema_eig = ema_eig;
    Ok(EsnSnapshotV2 {
        res_size: d,
        in_size: parent.in_size,
        win,
        wres,
        state,
        geom_radius: parent.geom_radius,
        geom_baseline: parent.geom_baseline,
        wout,
        rls_p,
        leak_live: parent.leak_live,
        lambda_live: parent.lambda_live,
        leak_base: parent.leak_base,
        lambda_base: parent.lambda_base,
        exploration_noise: parent.exploration_noise,
        rng_state: parent.rng_state ^ seed_tag,
        leak_override: parent.leak_override.clone(),
        spectral,
    })
}

fn write_bundle_v2_atomic(
    target: &Path,
    command: &DivisionCommandV1,
    esn: &EsnSnapshotV2,
    stable: &StableFieldCaptureV2,
    runtime: &RuntimeCaptureV2,
) -> Result<String> {
    if target.exists() {
        return Err(anyhow!("immutable checkpoint target already exists"));
    }
    validate_capture(esn, stable)?;
    let parent_dir = target
        .parent()
        .ok_or_else(|| anyhow!("checkpoint target has no parent"))?;
    fs::create_dir_all(parent_dir)?;
    let tmp = parent_dir.join(format!(
        ".parent.tmp-{}-{}",
        std::process::id(),
        now_unix_ms()
    ));
    fs::create_dir(&tmp)?;
    let mut arrays = BTreeMap::new();
    write_blob(
        &tmp,
        &mut arrays,
        "reservoir_state",
        &esn.state,
        &[esn.res_size],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "win",
        &esn.win,
        &[esn.res_size, esn.in_size + 1],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "wres",
        &esn.wres,
        &[esn.res_size, esn.res_size],
    )?;
    write_blob(&tmp, &mut arrays, "wout", &esn.wout, &[esn.res_size + 1])?;
    write_blob(
        &tmp,
        &mut arrays,
        "rls_p",
        &esn.rls_p,
        &[esn.res_size + 1, esn.res_size + 1],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "reservoir_covariance",
        &esn.spectral.covariance,
        &[esn.res_size, esn.res_size],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "reservoir_eigenvector",
        &esn.spectral.eigenvector,
        &[esn.res_size],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "sensory_covariance",
        &stable.covariance,
        &[stable.dimension, stable.dimension],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "sensory_top_k_basis",
        &stable.top_k_basis,
        &[stable.dimension, stable.eigenvalues.len()],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "sensory_eigenvalues",
        &stable.eigenvalues,
        &[stable.eigenvalues.len()],
    )?;
    write_blob(
        &tmp,
        &mut arrays,
        "projection_matrix",
        &stable.projection_matrix,
        &[stable.dimension, esn.in_size],
    )?;
    let manifest = NativeBundleManifestV2 {
        schema: MITOSIS_BUNDLE_SCHEMA_V2.to_string(),
        protocol_version: "astrid_minime/1.2".to_string(),
        division_id: command.division_id.clone(),
        plan_digest: command.plan_digest.clone(),
        source_generation: command.expected_parent_generation,
        created_at_unix_ms: now_unix_ms(),
        source_identity: serde_json::to_value(&command.source)?,
        build_identity: json!({
            "crate": env!("CARGO_PKG_NAME"),
            "version": env!("CARGO_PKG_VERSION"),
            "git_sha": option_env!("VERGEN_GIT_SHA").unwrap_or("unknown"),
        }),
        reservoir_dimension: esn.res_size,
        sensory_field_dimension: stable.dimension,
        live_commit_eligible: false,
        live_commit_blocking_reasons: vec![
            "deterministic_restore_100_ticks_pending".to_string(),
            "native_commit_feature_disabled".to_string(),
        ],
        esn_scalars: esn_scalar_json(esn),
        runtime: runtime.clone(),
        stable_field: json!({
            "sensory_fill_pct": stable.sensory_fill_pct,
            "estimator_state": stable.estimator_state,
            "pi_state": stable.pi_state,
            "projection_config": stable.projection_config,
            "backlog_state": stable.backlog_state,
            "staleness_state": stable.staleness_state,
            "recovery_stage": stable.recovery_stage,
            "inheritance": "clone_to_each_daughter_not_neuron_partition",
        }),
        arrays,
    };
    let manifest_path = tmp.join("manifest.json");
    let mut manifest_file = File::create(&manifest_path)?;
    serde_json::to_writer_pretty(&mut manifest_file, &manifest)?;
    manifest_file.write_all(b"\n")?;
    manifest_file.sync_all()?;
    validate_native_bundle_v2(&tmp)?;
    fs::rename(&tmp, target)?;
    let manifest_bytes = fs::read(target.join("manifest.json"))?;
    Ok(format!("sha256:{}", hex_sha256(&manifest_bytes)))
}

pub fn validate_native_bundle_v2(bundle_dir: &Path) -> Result<()> {
    let manifest_path = bundle_dir.join("manifest.json");
    let manifest: NativeBundleManifestV2 = serde_json::from_slice(&fs::read(&manifest_path)?)?;
    if manifest.schema != MITOSIS_BUNDLE_SCHEMA_V2
        || manifest.protocol_version != "astrid_minime/1.2"
        || manifest.reservoir_dimension != 128
        || manifest.sensory_field_dimension != 512
        || manifest.division_id.trim().is_empty()
        || manifest.plan_digest.len() < 16
        || manifest.source_identity.is_null()
        || manifest.build_identity.is_null()
    {
        return Err(anyhow!("invalid native bundle v2 identity or dimensions"));
    }
    let required = [
        "reservoir.state",
        "reservoir.win",
        "reservoir.wres",
        "reservoir.rls_wout",
        "reservoir.rls_p",
        "reservoir.spectral_covariance",
        "reservoir.spectral_eigenvector",
        "sensory_field.covariance",
        "sensory_field.top_k_basis",
        "sensory_field.eigenvalues",
        "sensory_field.projection_matrix",
    ];
    if required
        .iter()
        .any(|name| !manifest.arrays.contains_key(*name))
    {
        return Err(anyhow!("native bundle is missing a required array blob"));
    }
    for blob in manifest.arrays.values() {
        if blob.dtype != "float32"
            || blob.endian != "little"
            || blob.shape.iter().product::<usize>() * 4 != blob.byte_length
        {
            return Err(anyhow!("invalid native bundle array metadata"));
        }
        let relative = Path::new(&blob.path);
        if relative.components().count() != 1 {
            return Err(anyhow!("native bundle array path escapes its directory"));
        }
        let bytes = fs::read(bundle_dir.join(relative))?;
        if bytes.len() != blob.byte_length || hex_sha256(&bytes) != blob.sha256 {
            return Err(anyhow!("native bundle array hash or length mismatch"));
        }
        if !bytes
            .chunks_exact(4)
            .all(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]).is_finite())
        {
            return Err(anyhow!("native bundle array contains non-finite values"));
        }
    }
    Ok(())
}

fn validate_capture(esn: &EsnSnapshotV2, stable: &StableFieldCaptureV2) -> Result<()> {
    if stable.dimension != 512
        || stable.covariance.len() != stable.dimension * stable.dimension
        || stable.top_k_basis.len() != stable.dimension * stable.eigenvalues.len()
        || stable.projection_matrix.len() != stable.dimension * esn.in_size
        || !stable.sensory_fill_pct.is_finite()
    {
        return Err(anyhow!("invalid 512D stable-core field capture"));
    }
    for values in [
        &esn.state,
        &esn.win,
        &esn.wres,
        &esn.wout,
        &esn.rls_p,
        &esn.spectral.covariance,
        &esn.spectral.eigenvector,
        &stable.covariance,
        &stable.top_k_basis,
        &stable.eigenvalues,
        &stable.projection_matrix,
    ] {
        if !values.iter().all(|value| value.is_finite()) {
            return Err(anyhow!("checkpoint contains non-finite array values"));
        }
    }
    Ok(())
}

fn write_blob(
    dir: &Path,
    arrays: &mut BTreeMap<String, ArrayBlobV2>,
    name: &str,
    values: &[f32],
    shape: &[usize],
) -> Result<()> {
    let path = format!("{name}.f32le.bin");
    let mut bytes = Vec::with_capacity(values.len() * 4);
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    let mut file = File::create(dir.join(&path))?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    arrays.insert(
        name.to_string(),
        ArrayBlobV2 {
            path,
            dtype: "float32".to_string(),
            endian: "little".to_string(),
            shape: shape.to_vec(),
            byte_length: bytes.len(),
            sha256: hex_sha256(&bytes),
        },
    );
    Ok(())
}

fn esn_scalar_json(esn: &EsnSnapshotV2) -> Value {
    json!({
        "res_size": esn.res_size,
        "in_size": esn.in_size,
        "geom_radius": esn.geom_radius,
        "geom_baseline": esn.geom_baseline,
        "leak_live": esn.leak_live,
        "lambda_live": esn.lambda_live,
        "leak_base": esn.leak_base,
        "lambda_base": esn.lambda_base,
        "exploration_noise": esn.exploration_noise,
        "rng_state": esn.rng_state,
        "leak_override": esn.leak_override,
        "spectral": {
            "eig1": esn.spectral.eig1,
            "eig1_prev": esn.spectral.eig1_prev,
            "ema_eig": esn.spectral.ema_eig,
            "rho": esn.spectral.rho,
            "prime_index": esn.spectral.prime_index,
            "tick": esn.spectral.tick,
            "introspection_policy": esn.spectral.introspection_policy,
            "introspection_power_steps": esn.spectral.introspection_power_steps,
            "introspection_count": esn.spectral.introspection_count,
            "profiling_enabled": esn.spectral.profiling_enabled,
            "async_measurement_enabled": esn.spectral.async_measurement_enabled,
            "spectral_damping": esn.spectral.spectral_damping,
            "spectral_target_ratio": esn.spectral.spectral_target_ratio,
            "last_profile": esn.spectral.last_profile,
        }
    })
}

fn blocked_readiness(reason: &str) -> DivisionReadinessV1 {
    DivisionReadinessV1 {
        policy: DIVISION_READINESS_POLICY_V1.to_string(),
        ready: false,
        sample_count: 0,
        blocking_reasons: vec![reason.to_string()],
        first_tick_max_abs: None,
        state_nrmse: None,
        state_cosine: None,
        readout_nrmse: None,
        max_final_sensory_fill_pct: None,
        min_coupling_coverage: None,
        max_regulator_distance: None,
        metrics_fresh: false,
        sensory_panic_streak: 0,
        actuator_saturation_streak: 0,
    }
}

fn write_json_atomic(path: &Path, value: &impl Serialize) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow!("atomic JSON target has no parent"))?;
    fs::create_dir_all(parent)?;
    let tmp = parent.join(format!(
        ".{}.tmp-{}",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("state"),
        std::process::id()
    ));
    let mut file = File::create(&tmp)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    fs::rename(tmp, path)?;
    Ok(())
}

fn block(matrix: &[f32], width: usize, rows: &[usize], cols: &[usize]) -> Vec<f32> {
    rows.iter()
        .flat_map(|row| cols.iter().map(move |col| matrix[*row * width + *col]))
        .collect()
}

fn cross_block(matrix: &[f32], width: usize, rows: &[usize], cols: &[usize]) -> Vec<f32> {
    block(matrix, width, rows, cols)
}

fn matvec(matrix: &[f32], rows: usize, vector: &[f32]) -> Vec<f32> {
    let cols = vector.len();
    (0..rows)
        .map(|row| {
            matrix[row * cols..(row + 1) * cols]
                .iter()
                .zip(vector)
                .map(|(weight, value)| weight * value)
                .sum()
        })
        .collect()
}

fn select(values: &[f32], indices: &[usize]) -> Vec<f32> {
    indices.iter().map(|index| values[*index]).collect()
}

fn reconstruct(
    dimension: usize,
    left_indices: &[usize],
    left: &[f32],
    right_indices: &[usize],
    right: &[f32],
) -> Vec<f32> {
    let mut output = vec![0.0; dimension];
    for (index, value) in left_indices.iter().zip(left) {
        output[*index] = *value;
    }
    for (index, value) in right_indices.iter().zip(right) {
        output[*index] = *value;
    }
    output
}

fn covariance_partition_loss(
    covariance: &[f32],
    dimension: usize,
    left: &[usize],
    right: &[usize],
) -> f64 {
    let cross_sq: f64 = left
        .iter()
        .flat_map(|row| {
            right
                .iter()
                .map(move |col| covariance[*row * dimension + *col])
        })
        .map(|value| f64::from(value).powi(2))
        .sum();
    let total_sq: f64 = covariance
        .iter()
        .map(|value| f64::from(*value).powi(2))
        .sum();
    cross_sq.sqrt() / total_sq.sqrt().max(1.0e-12)
}

fn normalize(values: &mut [f32]) {
    let norm = values.iter().map(|value| value * value).sum::<f32>().sqrt();
    if norm > 1.0e-12 {
        for value in values {
            *value /= norm;
        }
    } else if let Some(first) = values.first_mut() {
        *first = 1.0;
    }
}

fn rayleigh(matrix: &[f32], dimension: usize, vector: &[f32]) -> f32 {
    let product = matvec(matrix, dimension, vector);
    vector
        .iter()
        .zip(product)
        .map(|(left, right)| left * right)
        .sum()
}

fn max_abs_difference(left: &[f32], right: &[f32]) -> f64 {
    left.iter()
        .zip(right)
        .map(|(a, b)| f64::from((a - b).abs()))
        .fold(0.0, f64::max)
}

fn squared_error(left: &[f32], right: &[f32]) -> f64 {
    left.iter()
        .zip(right)
        .map(|(a, b)| f64::from(*a - *b).powi(2))
        .sum()
}

fn cosine(left: &[f32], right: &[f32]) -> f64 {
    let dot: f64 = left
        .iter()
        .zip(right)
        .map(|(a, b)| f64::from(*a) * f64::from(*b))
        .sum();
    let left_norm = left
        .iter()
        .map(|value| f64::from(*value).powi(2))
        .sum::<f64>()
        .sqrt();
    let right_norm = right
        .iter()
        .map(|value| f64::from(*value).powi(2))
        .sum::<f64>()
        .sqrt();
    dot / (left_norm * right_norm).max(1.0e-12)
}

fn ratio_nrmse(errors: impl Iterator<Item = f64>, references: impl Iterator<Item = f64>) -> f64 {
    let error_sum: f64 = errors.sum();
    let reference_sum: f64 = references.sum();
    (error_sum / reference_sum.max(1.0e-12)).sqrt()
}

fn mean(values: impl Iterator<Item = f64>) -> f64 {
    let mut count = 0_u64;
    let mut sum = 0.0;
    for value in values {
        count = count.saturating_add(1);
        sum += value;
    }
    if count == 0 {
        f64::NAN
    } else {
        sum / count as f64
    }
}

fn trailing_count(
    samples: &VecDeque<ShadowMetric>,
    predicate: impl Fn(&ShadowMetric) -> bool,
) -> usize {
    samples
        .iter()
        .rev()
        .take_while(|sample| predicate(sample))
        .count()
}

fn receipt_id(command: &DivisionCommandV1) -> String {
    let basis = format!(
        "{}:{}:{}",
        command.division_id, command.idempotency_key, command.expected_parent_generation
    );
    format!("division-receipt-{}", &hex_sha256(basis.as_bytes())[..24])
}

fn safe_component(value: &str) -> String {
    let cleaned: String = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_') {
                ch
            } else {
                '_'
            }
        })
        .collect();
    if cleaned.is_empty() {
        "unnamed".to_string()
    } else {
        cleaned
    }
}

fn hex_sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::{
        archive_division_inbox_command, blocked_readiness, division_rehearsal_enabled_from,
        now_unix_ms, read_division_inbox, NativeDivisionCoordinator,
    };
    #[cfg(feature = "division-rehearsal")]
    use super::{PartitionStrategy, ShadowCandidate, StableFieldCaptureV2};
    use astrid_minime_protocol::{
        DivisionActionV1, DivisionCapabilityRefV1, DivisionCommandV1, DivisionLifecycleV1,
        DivisionReceiptStatusV1, DivisionSourceIdentityV1, DIVISION_COMMAND_SCHEMA_V1,
        DIVISION_ROLLBACK_SCOPE_V1,
    };
    use std::fs;

    #[cfg(feature = "division-rehearsal")]
    use crate::{esn::ESN, gpu::Gpu};

    #[test]
    fn division_rehearsal_requires_compile_feature_and_operator_ack() {
        assert!(!division_rehearsal_enabled_from(false, None));
        assert!(!division_rehearsal_enabled_from(false, Some("true")));
        assert!(!division_rehearsal_enabled_from(true, None));
        assert!(!division_rehearsal_enabled_from(true, Some("1")));
        assert!(division_rehearsal_enabled_from(true, Some("true")));
    }

    fn command(action: DivisionActionV1, key: &str) -> DivisionCommandV1 {
        let now = now_unix_ms();
        DivisionCommandV1 {
            schema: DIVISION_COMMAND_SCHEMA_V1.to_string(),
            action,
            division_id: "division-native-test".to_string(),
            idempotency_key: key.to_string(),
            expected_parent_generation: 7,
            plan_digest: "b".repeat(64),
            source: DivisionSourceIdentityV1 {
                being: "astrid".to_string(),
                process_identity: "test:astrid".to_string(),
                deployment_identity: "test".to_string(),
            },
            requested_at_unix_ms: now,
            expires_at_unix_ms: now + 60_000,
            reason: None,
            capability: None,
        }
    }

    #[cfg(feature = "division-rehearsal")]
    #[test]
    fn full_bridge_first_tick_reconstructs_parent_and_sensory_fields_are_distinct() {
        let gpu = Gpu::new().expect("Metal device and shaders");
        let mut constructor_rng = fastrand::Rng::with_seed(0xD1A1_5101);
        let mut parent = ESN::new(
            128,
            66,
            0.20,
            0.10,
            0.95,
            0.35,
            0.999,
            &gpu,
            &mut constructor_rng,
        )
        .expect("parent ESN");
        let warm = vec![0.01_f32; 66];
        for _ in 0..8 {
            parent.step(&warm).expect("warm parent");
        }
        let snapshot = parent.snapshot_v2().expect("parent snapshot");
        let stable = StableFieldCaptureV2 {
            dimension: 512,
            covariance: vec![0.0; 512 * 512],
            top_k_basis: vec![0.0; 512 * 8],
            eigenvalues: vec![1.0; 8],
            sensory_fill_pct: 68.0,
            estimator_state: serde_json::json!({"alpha_fill": 0.25}),
            pi_state: serde_json::json!({}),
            projection_matrix: vec![0.001; 512 * 66],
            projection_config: serde_json::json!({"projection_scale": 0.18}),
            backlog_state: serde_json::json!({}),
            staleness_state: serde_json::json!({}),
            recovery_stage: "test".to_string(),
        };
        let mut candidate =
            ShadowCandidate::new(&snapshot, &stable, PartitionStrategy::InputRecurrence, &gpu)
                .expect("partition candidate");
        let input: Vec<f32> = (0..66)
            .map(|index| ((index as f32) * 0.071).sin() * 0.10)
            .collect();

        parent.step(&input).expect("parent step");
        candidate
            .step(&parent, &input, 68.0, true, false, 1.0)
            .expect("daughter step");

        assert!(candidate.first_tick_max_abs.unwrap() <= 1.0e-6);
        assert_eq!(candidate.minime_sensory_field.ticks, 1);
        assert_eq!(candidate.astrid_sensory_field.ticks, 1);
        candidate.minime_sensory_field.covariance[0] += 1.0;
        assert_ne!(
            candidate.minime_sensory_field.covariance[0],
            candidate.astrid_sensory_field.covariance[0]
        );
    }

    #[test]
    fn status_is_idempotent_and_stale_generation_fails_closed() {
        let dir = tempfile::tempdir().unwrap();
        let mut coordinator = NativeDivisionCoordinator::open(dir.path(), 7).unwrap();
        let initial = coordinator.status();
        assert_eq!(
            initial.extensions["action_availability_v1"]["minime"]["schema"],
            "division.action_availability.v1"
        );
        assert_eq!(
            initial.extensions["action_availability_v1"]["astrid"]["recommended_action"],
            "DIVISION_PREPARE"
        );
        let status = command(DivisionActionV1::DivisionStatus, "status-1");
        let first = coordinator.handle_command(status.clone(), now_unix_ms(), || {
            panic!("status must not prepare")
        });
        let duplicate = coordinator.handle_command(status, now_unix_ms(), || {
            panic!("duplicate status must not prepare")
        });
        assert_eq!(first, duplicate);

        let mut stale = command(DivisionActionV1::DivisionStatus, "status-stale");
        stale.expected_parent_generation = 6;
        let receipt = coordinator.handle_command(stale, now_unix_ms(), || {
            panic!("stale status must not prepare")
        });
        assert_eq!(receipt.reason, "stale_parent_generation");
        assert_eq!(coordinator.lifecycle(), DivisionLifecycleV1::Idle);
    }

    #[test]
    fn restart_reconstructs_last_event_without_repeating_receipt() {
        let dir = tempfile::tempdir().unwrap();
        let status = command(DivisionActionV1::DivisionStatus, "status-restart");
        let first = {
            let mut coordinator = NativeDivisionCoordinator::open(dir.path(), 7).unwrap();
            coordinator.handle_command(status.clone(), now_unix_ms(), || {
                panic!("status must not prepare")
            })
        };
        let mut restored = NativeDivisionCoordinator::open(dir.path(), 7).unwrap();
        let duplicate = restored.handle_command(status, now_unix_ms(), || {
            panic!("duplicate status must not prepare")
        });
        assert_eq!(first, duplicate);
        assert_eq!(
            restored.state.readiness,
            blocked_readiness("division_not_prepared")
        );
    }

    #[test]
    fn workspace_inbox_is_processed_only_after_a_native_receipt() {
        let dir = tempfile::tempdir().unwrap();
        let inbox = dir.path().join("division/inbox");
        fs::create_dir_all(&inbox).unwrap();
        let path = inbox.join("status.json");
        fs::write(
            &path,
            serde_json::to_vec(&command(DivisionActionV1::DivisionStatus, "status-inbox")).unwrap(),
        )
        .unwrap();

        let mut queued = read_division_inbox(dir.path()).unwrap();
        assert_eq!(queued.len(), 1);
        assert!(
            path.exists(),
            "read must not remove a command before receipt"
        );
        let item = queued.pop().unwrap();
        let mut coordinator = NativeDivisionCoordinator::open(dir.path(), 7).unwrap();
        let receipt = coordinator.handle_command(item.command, now_unix_ms(), || {
            panic!("status must not prepare")
        });
        archive_division_inbox_command(dir.path(), &item.source_path, &receipt).unwrap();

        assert!(!path.exists());
        assert_eq!(
            fs::read_dir(dir.path().join("division/processed"))
                .unwrap()
                .count(),
            2
        );
    }

    #[test]
    fn one_shot_operator_capability_cannot_be_reused_with_a_new_key() {
        let dir = tempfile::tempdir().unwrap();
        let mut coordinator = NativeDivisionCoordinator::open(dir.path(), 7).unwrap();
        coordinator.state.lifecycle = DivisionLifecycleV1::Cytokinesis;
        coordinator.state.division_id = "division-native-test".to_string();
        coordinator.state.plan_digest = "b".repeat(64);
        let mut first = command(DivisionActionV1::DivisionRollback, "rollback-1");
        first.capability = Some(DivisionCapabilityRefV1 {
            token_id: "operator-one-shot".to_string(),
            scope: DIVISION_ROLLBACK_SCOPE_V1.to_string(),
            division_id: first.division_id.clone(),
            expected_parent_generation: first.expected_parent_generation,
            plan_digest: first.plan_digest.clone(),
            expires_at_unix_ms: first.expires_at_unix_ms,
            approved_by: "human-operator".to_string(),
            one_shot: true,
        });
        let accepted = coordinator.handle_command(first.clone(), now_unix_ms(), || {
            panic!("rollback must not prepare")
        });
        assert_eq!(accepted.status, DivisionReceiptStatusV1::Accepted);

        coordinator.state.lifecycle = DivisionLifecycleV1::Cytokinesis;
        let mut replay = first;
        replay.idempotency_key = "rollback-2".to_string();
        let rejected = coordinator.handle_command(replay, now_unix_ms(), || {
            panic!("rollback must not prepare")
        });
        assert_eq!(rejected.status, DivisionReceiptStatusV1::Rejected);
        assert_eq!(rejected.reason, "one_shot_capability_already_consumed");
    }
}
