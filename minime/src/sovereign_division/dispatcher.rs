use std::{
    io::{Read, Write},
    os::unix::net::UnixStream,
    sync::mpsc::{self, SyncSender, TrySendError},
    thread,
    time::Duration,
};

use anyhow::{anyhow, Result};

use crate::{
    esn::ESN,
    sovereign_division::records::{
        append_owner_json, now_unix_ms, DivisionRuntimeManifestV1, DivisionTickFrameV1,
        SovereignBeing,
    },
};

const DISPATCH_QUEUE_CAPACITY: usize = 64;
const MAX_STATUS_BYTES: usize = 64 * 1024;

pub(crate) struct DaughterFrameDispatcher {
    tx: SyncSender<FramePair>,
    parent_previous_state: Vec<f32>,
    minime_indices: Vec<usize>,
    astrid_indices: Vec<usize>,
    sequence: u64,
    minime_previous_hash: String,
    astrid_previous_hash: String,
    runtime_dir: std::path::PathBuf,
}

struct FramePair {
    minime: Vec<u8>,
    astrid: Vec<u8>,
}

impl DaughterFrameDispatcher {
    pub(crate) fn start(
        manifest: &DivisionRuntimeManifestV1,
        parent_state: Vec<f32>,
        minime_indices: Vec<usize>,
        astrid_indices: Vec<usize>,
    ) -> Result<Self> {
        if parent_state.len() != 128 || minime_indices.len() != 64 || astrid_indices.len() != 64 {
            return Err(anyhow!("dispatcher partition dimensions are invalid"));
        }
        let minime_socket = manifest
            .daughter_root(SovereignBeing::Minime)
            .join("runtime/control.sock");
        let astrid_socket = manifest
            .daughter_root(SovereignBeing::Astrid)
            .join("runtime/control.sock");
        let runtime_dir = manifest.runtime_dir().to_path_buf();
        let worker_runtime = runtime_dir.clone();
        let (tx, rx) = mpsc::sync_channel::<FramePair>(DISPATCH_QUEUE_CAPACITY);
        thread::Builder::new()
            .name("division-frame-dispatch".to_string())
            .spawn(move || {
                while let Ok(pair) = rx.recv() {
                    if let Err(error) = send_frame(&minime_socket, &pair.minime).and_then(|()| {
                        send_frame(&astrid_socket, &pair.astrid)
                    }) {
                        let _ = append_owner_json(
                            &worker_runtime.join("capture-gaps.jsonl"),
                            &serde_json::json!({
                                "schema": "division.tick_capture_gap.v1",
                                "reason_code": "daughter_delivery_failed",
                                "error_sha256": crate::sovereign_division::records::sha256_hex(error.to_string().as_bytes()),
                                "created_at_unix_ms": now_unix_ms(),
                                "rehearsal_sufficient": false,
                                "live_authority_granted_by_record": false,
                            }),
                        );
                    }
                }
            })?;
        Ok(Self {
            tx,
            parent_previous_state: parent_state,
            minime_indices,
            astrid_indices,
            sequence: 0,
            minime_previous_hash: "genesis".to_string(),
            astrid_previous_hash: "genesis".to_string(),
            runtime_dir,
        })
    }

    pub(crate) fn emit(
        &mut self,
        manifest: &DivisionRuntimeManifestV1,
        parent: &ESN,
        input: &[f32],
        coupling_scale: f32,
    ) -> Result<()> {
        self.sequence = self.sequence.saturating_add(1);
        let trace = parent.last_step_trace();
        let minime_peer = select(&self.parent_previous_state, &self.astrid_indices);
        let astrid_peer = select(&self.parent_previous_state, &self.minime_indices);
        let minime_noise = select(&trace.noise, &self.minime_indices);
        let astrid_noise = select(&trace.noise, &self.astrid_indices);
        let mut minime = DivisionTickFrameV1::new(
            manifest,
            self.sequence,
            input,
            &minime_peer,
            &minime_noise,
            trace.leak,
            coupling_scale,
        )?;
        let mut astrid = DivisionTickFrameV1::new(
            manifest,
            self.sequence,
            input,
            &astrid_peer,
            &astrid_noise,
            trace.leak,
            coupling_scale,
        )?;
        minime.set_previous_hash(self.minime_previous_hash.clone())?;
        astrid.set_previous_hash(self.astrid_previous_hash.clone())?;
        self.minime_previous_hash = minime.frame_sha256().to_string();
        self.astrid_previous_hash = astrid.frame_sha256().to_string();
        self.parent_previous_state.clone_from(&parent.x);
        match self.tx.try_send(FramePair {
            minime: minime.to_bytes()?,
            astrid: astrid.to_bytes()?,
        }) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => {
                append_owner_json(
                    &self.runtime_dir.join("capture-gaps.jsonl"),
                    &serde_json::json!({
                        "schema": "division.tick_capture_gap.v1",
                        "reason_code": "dispatcher_queue_saturated",
                        "sequence": self.sequence,
                        "created_at_unix_ms": now_unix_ms(),
                        "rehearsal_sufficient": false,
                        "live_authority_granted_by_record": false,
                    }),
                )?;
                Err(anyhow!("daughter frame queue saturated"))
            }
            Err(TrySendError::Disconnected(_)) => Err(anyhow!("daughter frame dispatcher stopped")),
        }
    }
}

fn send_frame(path: &std::path::Path, bytes: &[u8]) -> Result<()> {
    let mut stream = connect_with_retry(path)?;
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    stream.write_all(&u32::try_from(bytes.len())?.to_be_bytes())?;
    stream.write_all(bytes)?;
    stream.flush()?;
    let mut length = [0_u8; 4];
    stream.read_exact(&mut length)?;
    let length = usize::try_from(u32::from_be_bytes(length))?;
    if length == 0 || length > MAX_STATUS_BYTES {
        return Err(anyhow!("daughter status exceeded transport bound"));
    }
    let mut status = vec![0; length];
    stream.read_exact(&mut status)?;
    let _: serde_json::Value = serde_json::from_slice(&status)?;
    Ok(())
}

fn connect_with_retry(path: &std::path::Path) -> Result<UnixStream> {
    let mut last = None;
    for _ in 0..200 {
        match UnixStream::connect(path) {
            Ok(stream) => return Ok(stream),
            Err(error) => {
                last = Some(error);
                thread::sleep(Duration::from_millis(25));
            }
        }
    }
    Err(last.map_or_else(
        || anyhow!("daughter socket unavailable"),
        anyhow::Error::from,
    ))
}

fn select(values: &[f32], indices: &[usize]) -> Vec<f32> {
    indices
        .iter()
        .filter_map(|index| values.get(*index).copied())
        .collect()
}
