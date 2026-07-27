use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{UnixListener, UnixStream},
};

use crate::{
    esn::ESN,
    gpu::Gpu,
    sovereign_division::records::{
        append_owner_json, ensure_owner_only_dir, now_unix_ms, process_identity, write_owner_json,
        DaughterProcessStatusV1, DaughterReservoirBundleV1, DivisionTickFrameV1, SovereignBeing,
    },
};

const MAX_FRAME_BYTES: usize = 32 * 1024;
const CHECKPOINT_INTERVAL: u64 = 60;

#[derive(Serialize)]
struct DaughterCheckpointV1<'a> {
    schema: &'static str,
    being: SovereignBeing,
    division_id: &'a str,
    candidate_hash: &'a str,
    checkpoint_sequence: u64,
    last_tick_sequence: u64,
    last_frame_sha256: &'a str,
    process_identity: &'a str,
    deployment_identity: &'a str,
    created_at_unix_ms: u64,
    esn: crate::esn::EsnSnapshotV2,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DaughterCheckpointWireV1 {
    schema: String,
    being: SovereignBeing,
    division_id: String,
    candidate_hash: String,
    checkpoint_sequence: u64,
    last_tick_sequence: u64,
    last_frame_sha256: String,
    process_identity: String,
    deployment_identity: String,
    created_at_unix_ms: u64,
    esn: crate::esn::EsnSnapshotV2,
}

pub async fn run_child(being: &str, bundle_path: &Path, workspace: &Path) -> Result<()> {
    let being = SovereignBeing::parse(being)?;
    let bundle = DaughterReservoirBundleV1::load(bundle_path, being, workspace)?;
    ensure_owner_only_dir(workspace)?;
    let socket_dir = workspace.join("runtime");
    ensure_owner_only_dir(&socket_dir)?;
    let socket_path = socket_dir.join("control.sock");
    if socket_path.exists() {
        fs::remove_file(&socket_path)?;
    }
    let listener = UnixListener::bind(&socket_path)?;
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;

    let gpu = Gpu::new()?;
    let restored = load_latest_checkpoint(workspace, being, &bundle)?;
    let (snapshot, last_sequence, last_frame_sha256, checkpoint_sequence, prior_identity) =
        if let Some(checkpoint) = restored {
            (
                checkpoint.esn,
                checkpoint.last_tick_sequence,
                checkpoint.last_frame_sha256,
                checkpoint.checkpoint_sequence,
                Some(checkpoint.process_identity),
            )
        } else {
            (
                bundle.esn().clone(),
                0,
                "genesis".to_string(),
                bundle.checkpoint_sequence(),
                None,
            )
        };
    let esn = ESN::from_snapshot_v2(&snapshot, &gpu)?;
    let started_at = now_unix_ms();
    let identity = process_identity(started_at);
    let mut runtime = ChildRuntime {
        being,
        bundle,
        workspace: workspace.to_path_buf(),
        esn,
        process_identity: identity,
        process_started_at_unix_ms: started_at,
        last_sequence,
        last_frame_sha256,
        checkpoint_sequence,
    };
    append_owner_json(
        &workspace.join("restart_receipts.jsonl"),
        &serde_json::json!({
            "schema": "division.daughter_restart_receipt.v1",
            "being": being,
            "division_id": runtime.bundle.division_id(),
            "candidate_hash": runtime.bundle.candidate_hash(),
            "previous_process_identity": prior_identity,
            "process_identity": &runtime.process_identity,
            "deployment_identity": runtime.bundle.deployment_identity(),
            "restored_checkpoint_sequence": runtime.checkpoint_sequence,
            "restored_tick_sequence": runtime.last_sequence,
            "created_at_unix_ms": now_unix_ms(),
            "live_authority_granted_by_record": false,
        }),
    )?;
    runtime.persist_status(true, None)?;

    loop {
        let (stream, _) = listener.accept().await?;
        if let Err(error) = runtime.serve_connection(stream).await {
            runtime.persist_status(false, Some(error.to_string()))?;
        }
    }
}

struct ChildRuntime {
    being: SovereignBeing,
    bundle: DaughterReservoirBundleV1,
    workspace: PathBuf,
    esn: ESN,
    process_identity: String,
    process_started_at_unix_ms: u64,
    last_sequence: u64,
    last_frame_sha256: String,
    checkpoint_sequence: u64,
}

impl ChildRuntime {
    async fn serve_connection(&mut self, mut stream: UnixStream) -> Result<()> {
        loop {
            let length = match stream.read_u32().await {
                Ok(length) => usize::try_from(length)?,
                Err(error) if error.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(()),
                Err(error) => return Err(error.into()),
            };
            if length == 0 || length > MAX_FRAME_BYTES {
                return Err(anyhow!("tick frame exceeds bounded transport size"));
            }
            let mut bytes = vec![0; length];
            stream.read_exact(&mut bytes).await?;
            let status = self.apply_frame(&bytes)?;
            let reply = serde_json::to_vec(&status)?;
            stream.write_u32(u32::try_from(reply.len())?).await?;
            stream.write_all(&reply).await?;
            stream.flush().await?;
        }
    }

    fn apply_frame(&mut self, bytes: &[u8]) -> Result<DaughterProcessStatusV1> {
        let frame = DivisionTickFrameV1::parse(bytes)?;
        let expected_sequence = self.last_sequence.saturating_add(1);
        if frame.sequence() != expected_sequence {
            return Err(anyhow!(
                "tick ordering gap: expected {expected_sequence}, got {}",
                frame.sequence()
            ));
        }
        if frame.previous_hash() != self.last_frame_sha256
            || frame.division_id() != self.bundle.division_id()
            || frame.candidate_hash() != self.bundle.candidate_hash()
            || frame.process_identity().trim().is_empty()
            || frame.deployment_identity().trim().is_empty()
        {
            return Err(anyhow!("tick frame lineage or candidate mismatch"));
        }
        let mut cross_drive = matvec_64(self.bundle.cross_recurrence(), frame.peer_state())?;
        for value in &mut cross_drive {
            *value *= frame.coupling_scale();
        }
        self.esn
            .step_shadow(frame.input(), &cross_drive, frame.noise(), frame.leak())?;
        self.last_sequence = frame.sequence();
        self.last_frame_sha256 = frame.frame_sha256().to_string();
        if self.last_sequence.is_multiple_of(CHECKPOINT_INTERVAL) {
            self.persist_checkpoint()?;
        }
        self.persist_status(true, None)
    }

    fn persist_checkpoint(&mut self) -> Result<()> {
        self.checkpoint_sequence = self.checkpoint_sequence.saturating_add(1);
        let checkpoint = DaughterCheckpointV1 {
            schema: "division.daughter_checkpoint.v1",
            being: self.being,
            division_id: self.bundle.division_id(),
            candidate_hash: self.bundle.candidate_hash(),
            checkpoint_sequence: self.checkpoint_sequence,
            last_tick_sequence: self.last_sequence,
            last_frame_sha256: &self.last_frame_sha256,
            process_identity: &self.process_identity,
            deployment_identity: self.bundle.deployment_identity(),
            created_at_unix_ms: now_unix_ms(),
            esn: self.esn.snapshot_v2()?,
        };
        let checkpoint_dir = self.workspace.join("checkpoints");
        ensure_owner_only_dir(&checkpoint_dir)?;
        let immutable =
            checkpoint_dir.join(format!("checkpoint-{:020}.json", self.checkpoint_sequence));
        if immutable.exists() {
            return Err(anyhow!("immutable daughter checkpoint already exists"));
        }
        write_owner_json(&immutable, &checkpoint)?;
        write_owner_json(&self.workspace.join("checkpoint-latest.json"), &checkpoint)?;
        append_owner_json(
            &self.workspace.join("checkpoint_receipts.jsonl"),
            &serde_json::json!({
                "schema": "division.daughter_checkpoint_receipt.v1",
                "being": self.being,
                "process_identity": self.process_identity,
                "deployment_identity": self.bundle.deployment_identity(),
                "checkpoint_sequence": self.checkpoint_sequence,
                "last_tick_sequence": self.last_sequence,
                "created_at_unix_ms": now_unix_ms(),
                "live_authority_granted_by_record": false,
            }),
        )?;
        Ok(())
    }

    fn persist_status(
        &self,
        healthy: bool,
        gap_reason: Option<String>,
    ) -> Result<DaughterProcessStatusV1> {
        let status = DaughterProcessStatusV1::new(
            self.being,
            &self.bundle,
            self.process_identity.clone(),
            self.process_started_at_unix_ms,
            self.checkpoint_sequence
                .max(self.bundle.checkpoint_sequence()),
            self.last_sequence,
            self.last_frame_sha256.clone(),
            healthy,
            gap_reason,
        );
        write_owner_json(&self.workspace.join("status.json"), &status)?;
        Ok(status)
    }
}

fn load_latest_checkpoint(
    workspace: &Path,
    being: SovereignBeing,
    bundle: &DaughterReservoirBundleV1,
) -> Result<Option<DaughterCheckpointWireV1>> {
    let path = workspace.join("checkpoint-latest.json");
    if !path.is_file() {
        return Ok(None);
    }
    let checkpoint: DaughterCheckpointWireV1 = serde_json::from_slice(&fs::read(&path)?)?;
    if checkpoint.schema != "division.daughter_checkpoint.v1"
        || checkpoint.being != being
        || checkpoint.division_id != bundle.division_id()
        || checkpoint.candidate_hash != bundle.candidate_hash()
        || checkpoint.checkpoint_sequence == 0
        || checkpoint.last_tick_sequence == 0
        || checkpoint.last_frame_sha256.len() != 64
        || checkpoint.process_identity.trim().is_empty()
        || checkpoint.deployment_identity != bundle.deployment_identity()
        || checkpoint.created_at_unix_ms == 0
        || checkpoint.esn.res_size != 64
        || checkpoint.esn.in_size != 512
    {
        return Err(anyhow!("latest daughter checkpoint failed validation"));
    }
    Ok(Some(checkpoint))
}

fn matvec_64(matrix: &[f32], vector: &[f32]) -> Result<Vec<f32>> {
    if matrix.len() != 64 * 64 || vector.len() != 64 {
        return Err(anyhow!("cross-recurrence dimensions must be 64x64 by 64"));
    }
    Ok((0..64)
        .map(|row| {
            matrix[row * 64..(row + 1) * 64]
                .iter()
                .zip(vector)
                .map(|(weight, value)| weight * value)
                .sum()
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cross_recurrence_is_bounded_and_dimension_checked() {
        let matrix = vec![1.0; 64 * 64];
        let vector = vec![0.5; 64];
        let result = matvec_64(&matrix, &vector).unwrap();
        assert_eq!(result.len(), 64);
        assert!(result
            .iter()
            .all(|value| (*value - 32.0).abs() < f32::EPSILON));
        assert!(matvec_64(&matrix[..10], &vector).is_err());
    }

    #[test]
    fn checkpoint_loader_rejects_cross_being_state() {
        let value = serde_json::json!({
            "schema": "division.daughter_checkpoint.v1",
            "being": "astrid",
            "division_id": "division-test",
            "candidate_hash": "a".repeat(64),
            "checkpoint_sequence": 1,
            "last_tick_sequence": 60,
            "last_frame_sha256": "b".repeat(64),
            "process_identity": "old-process",
            "deployment_identity": "deployment",
            "created_at_unix_ms": 1,
            "esn": null
        });
        let parsed = serde_json::from_value::<DaughterCheckpointWireV1>(value);
        assert!(parsed.is_err());
    }
}
