use super::{
    storage::{atomic_json, Store},
    *,
};
use serde_json::json;
use std::{
    collections::VecDeque,
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc::{self, Receiver, SyncSender, TrySendError},
        Arc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

enum Message {
    Sample(Sample),
    Event(Event, u64),
}

pub struct AfterimageObserver {
    sender: SyncSender<Message>,
    dropped: Arc<AtomicU64>,
    worker: Option<JoinHandle<()>>,
}

impl AfterimageObserver {
    pub fn from_env(workspace: &Path, session_id: &str) -> Option<Self> {
        if std::env::var("MINIME_AFTERIMAGE_CAPTURE").ok().as_deref() != Some("1") {
            return None;
        }
        Some(Self::start(workspace.to_path_buf(), session_id.to_string()))
    }

    pub fn start(workspace: PathBuf, session_id: String) -> Self {
        let (sender, receiver) = mpsc::sync_channel(256);
        let dropped = Arc::new(AtomicU64::new(0));
        let worker_dropped = Arc::clone(&dropped);
        let worker = thread::spawn(move || run(workspace, session_id, receiver, worker_dropped));
        Self {
            sender,
            dropped,
            worker: Some(worker),
        }
    }

    pub fn observe(&self, sample: Sample) {
        self.send(Message::Sample(sample));
    }

    pub fn event(&self, session_id: &str, event: &Value) {
        let Some(sequence) = event.get("sequence").and_then(Value::as_u64) else {
            return;
        };
        let Some(seconds) = event.get("engine_t_s").and_then(Value::as_f64) else {
            return;
        };
        if !seconds.is_finite() || seconds < 0.0 {
            return;
        }
        self.send(Message::Event(
            Event {
                session_id: session_id.to_string(),
                sequence,
                engine_t_ms: (seconds * 1_000.0) as u64,
                event: event.clone(),
            },
            unix_ms(),
        ));
    }

    fn send(&self, message: Message) {
        if let Err(TrySendError::Full(_) | TrySendError::Disconnected(_)) =
            self.sender.try_send(message)
        {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn dropped_observations(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }

    /// Explicit joining is for offline tests and orderly callers, never the regulation tick.
    pub fn finish(mut self) {
        drop(self.sender);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn run(
    workspace: PathBuf,
    session_id: String,
    receiver: Receiver<Message>,
    dropped: Arc<AtomicU64>,
) {
    let mut store = match Store::open(&workspace) {
        Ok(store) => store,
        Err(error) => {
            eprintln!("afterimage_archive_unavailable: {error}");
            return;
        }
    };
    let mut recorder = Recorder::new(&session_id);
    let budget_path = store.root.join("automatic_budget.json");
    match fs::read(&budget_path) {
        Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
            Ok(budget) => recorder.restore_budget(&budget),
            Err(error) => {
                eprintln!("afterimage_budget_unavailable: {error}");
                return;
            }
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            eprintln!("afterimage_budget_unavailable: {error}");
            return;
        }
    }
    let mut persisted_budget = recorder.budget();
    let mut pending: VecDeque<Artifact> = VecDeque::new();
    let mut checkpoint = Instant::now();
    let mut last_sample = Instant::now();
    let mut last_error: Option<String> = None;
    let mut last_drop_count = 0;
    loop {
        recorder.automatic_admission = pending.len() < MAX_PENDING_WRITES;
        let disconnected = match receiver.recv_timeout(Duration::from_millis(250)) {
            Ok(Message::Sample(sample)) => {
                last_sample = Instant::now();
                enqueue(
                    recorder.observe(sample),
                    &mut pending,
                    &mut store,
                    &mut last_error,
                );
                false
            }
            Ok(Message::Event(event, wall_ms)) => {
                if let Err(error) = store.enrich(&event) {
                    last_error = Some(error.to_string());
                }
                recorder.event(event, wall_ms);
                false
            }
            Err(mpsc::RecvTimeoutError::Timeout) => false,
            Err(mpsc::RecvTimeoutError::Disconnected) => true,
        };
        let drop_count = dropped.load(Ordering::Relaxed);
        let budget = recorder.budget();
        if budget != persisted_budget {
            match atomic_json(&budget_path, &budget) {
                Ok(()) => persisted_budget = budget,
                Err(error) => {
                    last_error = Some(error.to_string());
                }
            }
        }
        if drop_count > last_drop_count {
            for artifact in &mut recorder.collecting {
                if !artifact
                    .reasons
                    .iter()
                    .any(|r| r == "observation_queue_overflow")
                {
                    artifact.reasons.push("observation_queue_overflow".into());
                }
            }
            last_drop_count = drop_count;
        }
        if disconnected || last_sample.elapsed() > Duration::from_secs(10) {
            let reason = if disconnected {
                "observer_shutdown"
            } else {
                "producer_stalled"
            };
            enqueue(
                recorder.interrupt(reason),
                &mut pending,
                &mut store,
                &mut last_error,
            );
        }
        if pending.len() < MAX_PENDING_WRITES {
            if let Err(error) = requests(&mut recorder, &mut store, &mut pending) {
                last_error = Some(error.to_string());
            }
        }
        if let Some(artifact) = pending.front() {
            match store.complete(artifact) {
                Ok(()) => {
                    pending.pop_front();
                }
                Err(error) => {
                    last_error = Some(error.to_string());
                }
            }
        }
        if checkpoint.elapsed() >= Duration::from_secs(5) || disconnected {
            for artifact in &mut recorder.collecting {
                artifact.refresh();
                if let Err(error) = store.checkpoint(artifact) {
                    last_error = Some(error.to_string());
                }
            }
            for artifact in &pending {
                if let Err(error) = store.checkpoint(artifact) {
                    last_error = Some(error.to_string());
                }
            }
            let status = json!({"policy": POLICY, "enabled": !disconnected,
                "session_id": session_id, "engine_t_ms": recorder.last_engine_t_ms,
                "source_wall_clock_unix_ms": recorder.last_wall_ms, "updated_at_unix_ms": unix_ms(),
                "collecting": recorder.collecting.len(), "pending_writes": pending.len(),
                "dropped_observations": drop_count, "last_error": last_error});
            if let Err(error) = atomic_json(&store.root.join("status.json"), &status) {
                eprintln!("afterimage_status_unavailable: {error}");
            }
            checkpoint = Instant::now();
        }
        if disconnected {
            while let Some(artifact) = pending.pop_front() {
                if let Err(error) = store.complete(&artifact) {
                    eprintln!("afterimage_write_failed {}: {error}", artifact.id);
                    let _ = store.checkpoint(&artifact);
                }
            }
            break;
        }
    }
}

fn enqueue(
    items: Vec<Artifact>,
    pending: &mut VecDeque<Artifact>,
    store: &mut Store,
    error: &mut Option<String>,
) {
    for mut artifact in items {
        if pending.len() < MAX_PENDING_WRITES {
            pending.push_back(artifact);
        } else {
            artifact.status = "incomplete".into();
            artifact.reasons.push("completed_write_queue_full".into());
            *error = Some("completed_write_queue_full".into());
            let _ = store.checkpoint(&artifact);
            for request in &artifact.request_ids {
                let _ = store.receipt(
                    request,
                    &artifact.id,
                    "failed",
                    Some("completed_write_queue_full"),
                );
            }
        }
    }
}

fn requests(
    recorder: &mut Recorder,
    store: &mut Store,
    pending: &mut VecDeque<Artifact>,
) -> std::io::Result<()> {
    for entry in fs::read_dir(store.root.join("requests"))?.take(8) {
        let path = entry?.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let name = path.file_stem().and_then(|v| v.to_str()).unwrap_or("");
        if !valid_id(name) {
            continue;
        }
        if fs::symlink_metadata(&path)?.file_type().is_symlink()
            || fs::metadata(&path)?.len() > 4096
        {
            store.receipt(name, "", "failed", Some("invalid_request_file"))?;
            fs::remove_file(path)?;
            continue;
        }
        let request: CaptureRequest = match serde_json::from_slice(&fs::read(&path)?) {
            Ok(request) => request,
            Err(_) => {
                store.receipt(name, "", "failed", Some("invalid_request_json"))?;
                fs::remove_file(path)?;
                continue;
            }
        };
        if request.request_id != name {
            store.receipt(name, "", "failed", Some("request_identity_mismatch"))?;
            fs::remove_file(path)?;
            continue;
        }
        let receipt_path = store.root.join("receipts").join(format!("{name}.json"));
        if let Ok(bytes) = fs::read(&receipt_path) {
            if let Ok(receipt) = serde_json::from_slice::<Value>(&bytes) {
                if matches!(
                    receipt["status"].as_str(),
                    Some("completed" | "incomplete" | "failed")
                ) {
                    fs::remove_file(path)?;
                    continue;
                }
            }
        }
        let id = request.afterimage_id.clone();
        if date_partition(request.anchor_unix_ms)
            .is_some_and(|date| store.root.join(date).join(format!("{id}.json")).exists())
        {
            store.receipt(
                name,
                &id,
                "failed",
                Some("artifact_identity_already_finalized"),
            )?;
            fs::remove_file(path)?;
            continue;
        }
        let outcome = recorder.request(request);
        match outcome {
            Ok(Some(artifact)) => {
                store.checkpoint(&artifact)?;
                pending.push_back(artifact);
                store.receipt(name, &id, "pending", None)?;
            }
            Ok(None) => {
                if let Some(artifact) = recorder.collecting.iter().find(|a| a.id == id) {
                    store.checkpoint(artifact)?;
                }
                store.receipt(name, &id, "pending", None)?;
            }
            Err(reason) => {
                store.receipt(name, &id, "failed", Some(&reason))?;
            }
        }
        fs::remove_file(path)?;
        if pending.len() >= MAX_PENDING_WRITES {
            break;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transition_afterimage_full_observation_queue_never_blocks_producer() {
        let (sender, _receiver) = mpsc::sync_channel(1);
        let observer = AfterimageObserver {
            sender,
            dropped: Arc::new(AtomicU64::new(0)),
            worker: None,
        };
        let sample = Sample::new("body", 1000, json!({"fill_pct":68.0}), 1000);
        observer.observe(sample.clone());
        for _ in 0..1000 {
            observer.observe(sample.clone());
        }
        assert_eq!(observer.dropped_observations(), 1000);
    }

    #[test]
    fn transition_afterimage_full_write_queue_is_bounded_and_receipted() {
        let root = tempfile::tempdir().unwrap();
        let mut store = Store::open(root.path()).unwrap();
        let mut recorder = Recorder::new("capacity");
        recorder.observe(Sample::new("body", 30_000, json!({"fill_pct":68.0}), 1000));
        let request = CaptureRequest {
            request_id: "queue_request".into(),
            afterimage_id: "ai_2026-09-07_queue".into(),
            session_id: None,
            anchor_engine_t_ms: Some(30_000),
            anchor_unix_ms: recorder.last_wall_ms,
            requested_at_unix_ms: recorder.last_wall_ms,
        };
        recorder.request(request).unwrap();
        let artifact = recorder.interrupt("test_shutdown").remove(0);
        let mut pending = VecDeque::from(vec![artifact.clone(); MAX_PENDING_WRITES]);
        let mut error = None;
        enqueue(vec![artifact], &mut pending, &mut store, &mut error);
        assert_eq!(pending.len(), MAX_PENDING_WRITES);
        assert_eq!(error.as_deref(), Some("completed_write_queue_full"));
        let receipt: Value = serde_json::from_slice(
            &fs::read(store.root.join("receipts/queue_request.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(receipt["status"], "failed");
    }

    #[test]
    fn transition_afterimage_disk_failure_is_not_reported_complete() {
        let root = tempfile::tempdir().unwrap();
        let store = Store::open(root.path()).unwrap();
        fs::write(store.root.join("receipts"), b"not a directory").unwrap();
        assert!(store
            .receipt("request", "artifact", "completed", None)
            .is_err());
    }
}
