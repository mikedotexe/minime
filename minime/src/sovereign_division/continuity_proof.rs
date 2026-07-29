use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::{
    division::{run_offline_division_parity_proof, DivisionParityProofMetricsV1},
    sovereign_division::{
        fanout::LegacyAvFanoutProofMetricsV1,
        gateway::GatewayByteExactProofMetricsV1,
        records::{
            ensure_owner_only_dir, run_rollback_receipt_contract_proof, sha256_hex,
            validate_runtime_roots, validate_tick_lineage, write_owner_json, DivisionTickFrameV1,
            RollbackReceiptProofMetricsV1,
        },
        run_gateway_byte_exact_proof, run_legacy_av_fanout_proof,
    },
};

pub const CONTINUITY_PROOF_SCHEMA_V1: &str = "division.continuity_proof.v1";
const PROOF_SEED: &str = "division-continuity-proof-v1:2026-07-29";
const PARITY_TICKS: u64 = 10_000;
const COLD_RESTORE_TRIALS: u64 = 32;
const PARITY_MAX_ABS: f64 = 1.0e-5;
const RESTORE_MAX_ABS: f64 = 1.0e-6;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LineageFailureProofV1 {
    accepted_ordered_frame: bool,
    duplicate_rejected: bool,
    dropped_sequence_rejected: bool,
    reordered_hash_rejected: bool,
    candidate_mismatch_rejected: bool,
    live_input_dispatched: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RootIsolationProofV1 {
    runtime_root: String,
    minime_root: String,
    astrid_root: String,
    disjoint_roots_accepted: bool,
    nested_root_rejected: bool,
    owner_only: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HandoffAdapterProofV1 {
    legacy_sensory_adapter_wired: bool,
    direct_telemetry_adapter_wired: bool,
    legacy_av_fanout_runtime_wired: bool,
    legacy_av_fanout_receipt_present: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProofAuthorityBoundaryV1 {
    state: String,
    parent_authoritative: bool,
    matching_current_intent_inferred: bool,
    mutual_assent_inferred: bool,
    operator_capability_consumed: bool,
    rehearsal_launched: bool,
    daughters_launched: bool,
    handoff_dispatched: bool,
    live_authority_granted_by_record: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DivisionContinuityProofV1 {
    schema: String,
    proof_id: String,
    proof_seed: String,
    source_hashes: BTreeMap<String, String>,
    parity: DivisionParityProofMetricsV1,
    lineage_failure_injection: LineageFailureProofV1,
    randomized_cold_restore_count: u64,
    gateway: GatewayByteExactProofMetricsV1,
    fanout: LegacyAvFanoutProofMetricsV1,
    root_isolation: RootIsolationProofV1,
    rollback_receipt: RollbackReceiptProofMetricsV1,
    handoff_adapters: HandoffAdapterProofV1,
    continuity_core_complete: bool,
    handoff_proof_complete: bool,
    handoff_blockers: Vec<String>,
    offline_ephemeral_loopback_only: bool,
    live_ports_touched: bool,
    live_runtime_state_changed: bool,
    authority: ProofAuthorityBoundaryV1,
}

impl DivisionContinuityProofV1 {
    fn recompute_id(&self) -> Result<String> {
        let mut identity = Vec::new();
        append_identity_text(&mut identity, &self.schema)?;
        append_identity_text(&mut identity, &self.proof_seed)?;
        for (path, hash) in &self.source_hashes {
            append_identity_text(&mut identity, path)?;
            append_identity_text(&mut identity, hash)?;
        }
        identity.extend_from_slice(&self.parity.ticks.to_le_bytes());
        append_identity_text(&mut identity, &format!("{:.12e}", self.parity.max_abs))?;
        identity.extend_from_slice(&self.parity.restore_trials.to_le_bytes());
        append_identity_text(
            &mut identity,
            &format!("{:.12e}", self.parity.restore_max_abs),
        )?;
        append_identity_text(&mut identity, &self.parity.final_state_sha256)?;
        for value in [
            self.lineage_failure_injection.accepted_ordered_frame,
            self.lineage_failure_injection.duplicate_rejected,
            self.lineage_failure_injection.dropped_sequence_rejected,
            self.lineage_failure_injection.reordered_hash_rejected,
            self.lineage_failure_injection.candidate_mismatch_rejected,
            self.lineage_failure_injection.live_input_dispatched,
        ] {
            identity.push(u8::from(value));
        }
        identity.extend_from_slice(&self.randomized_cold_restore_count.to_le_bytes());
        identity.extend_from_slice(&self.gateway.payload_count.to_le_bytes());
        identity.extend_from_slice(&self.gateway.payload_bytes.to_le_bytes());
        append_identity_text(&mut identity, &self.gateway.source_sha256)?;
        append_identity_text(&mut identity, &self.gateway.echoed_sha256)?;
        identity.push(u8::from(self.gateway.byte_exact));
        identity.extend_from_slice(&self.gateway.latency_bound_micros.to_le_bytes());
        identity.push(u8::from(self.gateway.p95_within_bound));
        identity.extend_from_slice(&self.fanout.payload_bytes.to_le_bytes());
        append_identity_text(&mut identity, &self.fanout.source_sha256)?;
        append_identity_text(&mut identity, &self.fanout.primary_sha256)?;
        append_identity_text(&mut identity, &self.fanout.observer_sha256)?;
        for value in [
            self.fanout.byte_exact,
            self.fanout.runtime_adapter_wired,
            self.fanout.handoff_receipt_present,
        ] {
            identity.push(u8::from(value));
        }
        for value in [
            &self.root_isolation.runtime_root,
            &self.root_isolation.minime_root,
            &self.root_isolation.astrid_root,
        ] {
            append_identity_text(&mut identity, value)?;
        }
        for value in [
            self.root_isolation.disjoint_roots_accepted,
            self.root_isolation.nested_root_rejected,
            self.root_isolation.owner_only,
        ] {
            identity.push(u8::from(value));
        }
        append_identity_text(&mut identity, &self.rollback_receipt.schema)?;
        for value in [
            self.rollback_receipt.receipt_id_bound,
            self.rollback_receipt.parent_identity_bound,
            self.rollback_receipt.reason_bound,
            self.rollback_receipt.owner_only,
            self.rollback_receipt.live_authority_granted_by_record,
            self.handoff_adapters.legacy_sensory_adapter_wired,
            self.handoff_adapters.direct_telemetry_adapter_wired,
            self.handoff_adapters.legacy_av_fanout_runtime_wired,
            self.handoff_adapters.legacy_av_fanout_receipt_present,
            self.continuity_core_complete,
            self.handoff_proof_complete,
            self.offline_ephemeral_loopback_only,
            self.live_ports_touched,
            self.live_runtime_state_changed,
        ] {
            identity.push(u8::from(value));
        }
        for blocker in &self.handoff_blockers {
            append_identity_text(&mut identity, blocker)?;
        }
        append_identity_text(&mut identity, &self.authority.state)?;
        for value in [
            self.authority.parent_authoritative,
            self.authority.matching_current_intent_inferred,
            self.authority.mutual_assent_inferred,
            self.authority.operator_capability_consumed,
            self.authority.rehearsal_launched,
            self.authority.daughters_launched,
            self.authority.handoff_dispatched,
            self.authority.live_authority_granted_by_record,
        ] {
            identity.push(u8::from(value));
        }
        Ok(format!(
            "division_continuity_proof_{}",
            &sha256_hex(&identity)[..24]
        ))
    }

    fn validate(&self) -> Result<()> {
        if self.schema != CONTINUITY_PROOF_SCHEMA_V1 || self.proof_seed != PROOF_SEED {
            return Err(anyhow!(
                "Division continuity proof schema or seed is invalid"
            ));
        }
        let expected_proof_id = self.recompute_id()?;
        if self.proof_id != expected_proof_id {
            return Err(anyhow!(
                "Division continuity proof deterministic identity is invalid: recorded={}, computed={expected_proof_id}",
                self.proof_id
            ));
        }
        if self.source_hashes.len() != proof_source_paths().len() {
            return Err(anyhow!(
                "Division continuity proof source set is incomplete"
            ));
        }
        let lineage = &self.lineage_failure_injection;
        let root = &self.root_isolation;
        let rollback = &self.rollback_receipt;
        let core_complete = self.parity.ticks >= PARITY_TICKS
            && self.parity.max_abs <= PARITY_MAX_ABS
            && self.parity.restore_trials >= COLD_RESTORE_TRIALS
            && self.parity.restore_max_abs <= RESTORE_MAX_ABS
            && self.randomized_cold_restore_count == self.parity.restore_trials
            && lineage.accepted_ordered_frame
            && lineage.duplicate_rejected
            && lineage.dropped_sequence_rejected
            && lineage.reordered_hash_rejected
            && lineage.candidate_mismatch_rejected
            && !lineage.live_input_dispatched
            && self.gateway.byte_exact
            && self.gateway.source_sha256 == self.gateway.echoed_sha256
            && self.gateway.p95_within_bound
            && self.fanout.byte_exact
            && self.fanout.source_sha256 == self.fanout.primary_sha256
            && self.fanout.source_sha256 == self.fanout.observer_sha256
            && root.disjoint_roots_accepted
            && root.nested_root_rejected
            && root.owner_only
            && rollback.receipt_id_bound
            && rollback.parent_identity_bound
            && rollback.reason_bound
            && rollback.owner_only
            && !rollback.live_authority_granted_by_record;
        let expected_handoff_complete = core_complete
            && self.handoff_adapters.legacy_sensory_adapter_wired
            && self.handoff_adapters.direct_telemetry_adapter_wired
            && self.handoff_adapters.legacy_av_fanout_runtime_wired
            && self.handoff_adapters.legacy_av_fanout_receipt_present;
        let authority = &self.authority;
        if self.continuity_core_complete != core_complete {
            return Err(anyhow!(
                "Division continuity core result disagrees with component evidence: recorded={}, computed={}, parity_max_abs={}, restore_max_abs={}",
                self.continuity_core_complete,
                core_complete,
                self.parity.max_abs,
                self.parity.restore_max_abs
            ));
        }
        if self.handoff_proof_complete != expected_handoff_complete {
            return Err(anyhow!(
                "Division handoff result disagrees with adapter evidence"
            ));
        }
        if !self.offline_ephemeral_loopback_only
            || self.live_ports_touched
            || self.live_runtime_state_changed
        {
            return Err(anyhow!(
                "Division continuity proof offline execution boundary is invalid"
            ));
        }
        if authority.state != "evidence_only"
            || !authority.parent_authoritative
            || authority.matching_current_intent_inferred
            || authority.mutual_assent_inferred
            || authority.operator_capability_consumed
            || authority.rehearsal_launched
            || authority.daughters_launched
            || authority.handoff_dispatched
            || authority.live_authority_granted_by_record
        {
            return Err(anyhow!(
                "Division continuity proof authority boundary is invalid"
            ));
        }
        Ok(())
    }
}

fn append_identity_text(target: &mut Vec<u8>, value: &str) -> Result<()> {
    target.extend_from_slice(&u64::try_from(value.len())?.to_le_bytes());
    target.extend_from_slice(value.as_bytes());
    Ok(())
}

pub async fn run_continuity_proof(output: &Path) -> Result<DivisionContinuityProofV1> {
    let scratch = proof_scratch_root();
    if scratch.exists() {
        fs::remove_dir_all(&scratch)?;
    }
    ensure_owner_only_dir(&scratch)?;
    let result = build_continuity_proof(&scratch).await;
    let cleanup = fs::remove_dir_all(&scratch);
    let mut proof = result?;
    cleanup?;
    let first_id = proof.recompute_id()?;
    let repeated_id = proof.recompute_id()?;
    if first_id != repeated_id {
        return Err(anyhow!(
            "Division continuity proof identity material is nondeterministic before assignment: first={first_id}, repeated={repeated_id}"
        ));
    }
    proof.proof_id = first_id;
    let assigned_id = proof.recompute_id()?;
    if proof.proof_id != assigned_id {
        return Err(anyhow!(
            "Division continuity proof identity material changed after assignment: recorded={}, computed={assigned_id}",
            proof.proof_id
        ));
    }
    proof.validate()?;
    write_owner_json(output, &proof)?;
    if output.metadata()?.permissions().mode() & 0o077 != 0 {
        return Err(anyhow!("Division continuity proof is not owner-only"));
    }
    verify_continuity_proof(output)?;
    Ok(proof)
}

pub fn verify_continuity_proof(path: &Path) -> Result<DivisionContinuityProofV1> {
    let proof: DivisionContinuityProofV1 = serde_json::from_slice(
        &fs::read(path).with_context(|| format!("read continuity proof {}", path.display()))?,
    )?;
    if path.metadata()?.permissions().mode() & 0o077 != 0 {
        return Err(anyhow!("Division continuity proof is not owner-only"));
    }
    proof.validate()?;
    let current = source_hashes()?;
    if proof.source_hashes != current {
        return Err(anyhow!("Division continuity proof source hashes are stale"));
    }
    Ok(proof)
}

async fn build_continuity_proof(scratch: &Path) -> Result<DivisionContinuityProofV1> {
    let parity = run_offline_division_parity_proof(PARITY_TICKS, COLD_RESTORE_TRIALS)?;
    let lineage_failure_injection = run_lineage_failure_injection()?;
    let gateway = run_gateway_byte_exact_proof().await?;
    let fanout = run_legacy_av_fanout_proof().await?;
    let root_isolation = run_root_isolation_proof(scratch)?;
    let rollback_receipt = run_rollback_receipt_contract_proof(scratch)?;
    let handoff_adapters = HandoffAdapterProofV1 {
        legacy_sensory_adapter_wired: false,
        direct_telemetry_adapter_wired: false,
        legacy_av_fanout_runtime_wired: fanout.runtime_adapter_wired,
        legacy_av_fanout_receipt_present: fanout.handoff_receipt_present,
    };
    let continuity_core_complete = parity.ticks >= PARITY_TICKS
        && parity.max_abs <= PARITY_MAX_ABS
        && parity.restore_trials >= COLD_RESTORE_TRIALS
        && parity.restore_max_abs <= RESTORE_MAX_ABS
        && lineage_failure_injection.accepted_ordered_frame
        && lineage_failure_injection.duplicate_rejected
        && lineage_failure_injection.dropped_sequence_rejected
        && lineage_failure_injection.reordered_hash_rejected
        && lineage_failure_injection.candidate_mismatch_rejected
        && gateway.byte_exact
        && gateway.p95_within_bound
        && fanout.byte_exact
        && root_isolation.disjoint_roots_accepted
        && root_isolation.nested_root_rejected
        && root_isolation.owner_only
        && rollback_receipt.owner_only;
    Ok(DivisionContinuityProofV1 {
        schema: CONTINUITY_PROOF_SCHEMA_V1.to_string(),
        proof_id: String::new(),
        proof_seed: PROOF_SEED.to_string(),
        source_hashes: source_hashes()?,
        randomized_cold_restore_count: parity.restore_trials,
        parity,
        lineage_failure_injection,
        gateway,
        fanout,
        root_isolation,
        rollback_receipt,
        handoff_adapters,
        continuity_core_complete,
        handoff_proof_complete: false,
        handoff_blockers: vec![
            "daughter_legacy_sensory_adapter_required".to_string(),
            "daughter_direct_telemetry_adapter_required".to_string(),
            "legacy_av_fanout_receipt_required".to_string(),
            "exact_operator_capability_required".to_string(),
        ],
        offline_ephemeral_loopback_only: true,
        live_ports_touched: false,
        live_runtime_state_changed: false,
        authority: ProofAuthorityBoundaryV1 {
            state: "evidence_only".to_string(),
            parent_authoritative: true,
            matching_current_intent_inferred: false,
            mutual_assent_inferred: false,
            operator_capability_consumed: false,
            rehearsal_launched: false,
            daughters_launched: false,
            handoff_dispatched: false,
            live_authority_granted_by_record: false,
        },
    })
}

fn run_lineage_failure_injection() -> Result<LineageFailureProofV1> {
    let candidate = "c".repeat(64);
    let ordered = tick_frame(1, "genesis", &candidate)?;
    let duplicate = tick_frame(1, "genesis", &candidate)?;
    let dropped = tick_frame(3, &"a".repeat(64), &candidate)?;
    let reordered = tick_frame(2, &"b".repeat(64), &candidate)?;
    let wrong_candidate = tick_frame(2, &"a".repeat(64), &"d".repeat(64))?;
    Ok(LineageFailureProofV1 {
        accepted_ordered_frame: validate_tick_lineage(
            &ordered,
            1,
            "genesis",
            "division-continuity-proof",
            &candidate,
        )
        .is_ok(),
        duplicate_rejected: validate_tick_lineage(
            &duplicate,
            2,
            &"a".repeat(64),
            "division-continuity-proof",
            &candidate,
        )
        .is_err(),
        dropped_sequence_rejected: validate_tick_lineage(
            &dropped,
            2,
            &"a".repeat(64),
            "division-continuity-proof",
            &candidate,
        )
        .is_err(),
        reordered_hash_rejected: validate_tick_lineage(
            &reordered,
            2,
            &"a".repeat(64),
            "division-continuity-proof",
            &candidate,
        )
        .is_err(),
        candidate_mismatch_rejected: validate_tick_lineage(
            &wrong_candidate,
            2,
            &"a".repeat(64),
            "division-continuity-proof",
            &candidate,
        )
        .is_err(),
        live_input_dispatched: false,
    })
}

fn tick_frame(
    sequence: u64,
    previous_frame_sha256: &str,
    candidate_hash: &str,
) -> Result<DivisionTickFrameV1> {
    DivisionTickFrameV1::parse(&serde_json::to_vec(&serde_json::json!({
        "schema": "division.tick_frame.v1",
        "division_id": "division-continuity-proof",
        "candidate_hash": candidate_hash,
        "sequence": sequence,
        "previous_frame_sha256": previous_frame_sha256,
        "monotonic_ns": sequence,
        "parent_process_identity": "offline-parent-process",
        "parent_deployment_identity": "offline-parent-deployment",
        "sensory_field": vec![0.0_f32; 512],
        "peer_previous_state": vec![0.0_f32; 64],
        "realized_noise": vec![0.0_f32; 64],
        "effective_leak": 0.35,
        "coupling_scale": 1.0
    }))?)
}

fn run_root_isolation_proof(scratch: &Path) -> Result<RootIsolationProofV1> {
    let runtime = scratch.join("runtime");
    let minime = scratch.join("minime");
    let astrid = scratch.join("astrid");
    let disjoint_roots_accepted = validate_runtime_roots(&runtime, &minime, &astrid).is_ok();
    for path in [&runtime, &minime, &astrid] {
        ensure_owner_only_dir(path)?;
    }
    let owner_only = [&runtime, &minime, &astrid].iter().all(|path| {
        path.metadata()
            .is_ok_and(|metadata| metadata.permissions().mode() & 0o077 == 0)
    });
    let nested_root_rejected =
        validate_runtime_roots(&runtime, &minime, &runtime.join("astrid")).is_err();
    Ok(RootIsolationProofV1 {
        runtime_root: "isolated/runtime".to_string(),
        minime_root: "isolated/minime".to_string(),
        astrid_root: "isolated/astrid".to_string(),
        disjoint_roots_accepted,
        nested_root_rejected,
        owner_only,
    })
}

fn source_hashes() -> Result<BTreeMap<String, String>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    proof_source_paths()
        .into_iter()
        .map(|relative| {
            let bytes = fs::read(root.join(&relative))
                .with_context(|| format!("read Division proof source {relative}"))?;
            Ok((relative, sha256_hex(&bytes)))
        })
        .collect()
}

fn proof_source_paths() -> Vec<String> {
    [
        "src/division.rs",
        "src/sovereign_division/child.rs",
        "src/sovereign_division/continuity_proof.rs",
        "src/sovereign_division/fanout.rs",
        "src/sovereign_division/gateway.rs",
        "src/sovereign_division/records.rs",
    ]
    .into_iter()
    .map(str::to_string)
    .collect()
}

fn proof_scratch_root() -> PathBuf {
    std::env::temp_dir().join(format!(
        "minime-division-continuity-proof-{}",
        std::process::id()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lineage_failure_injection_rejects_duplicate_drop_and_reorder() {
        let proof = run_lineage_failure_injection().unwrap();
        assert!(proof.accepted_ordered_frame);
        assert!(proof.duplicate_rejected);
        assert!(proof.dropped_sequence_rejected);
        assert!(proof.reordered_hash_rejected);
        assert!(proof.candidate_mismatch_rejected);
        assert!(!proof.live_input_dispatched);
    }

    #[test]
    fn root_isolation_rejects_nested_daughter_storage() {
        let scratch = proof_scratch_root().join("root-test");
        if scratch.exists() {
            fs::remove_dir_all(&scratch).unwrap();
        }
        ensure_owner_only_dir(&scratch).unwrap();
        let proof = run_root_isolation_proof(&scratch).unwrap();
        assert!(proof.disjoint_roots_accepted);
        assert!(proof.nested_root_rejected);
        assert!(proof.owner_only);
        fs::remove_dir_all(scratch).unwrap();
    }
}
