use super::*;
use serde_json::json;
use std::{
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
};

pub fn atomic_json(path: &Path, value: &impl Serialize) -> io::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("missing parent"))?;
    fs::create_dir_all(parent)?;
    let temporary = path.with_extension("json.tmp");
    let mut file = fs::File::create(&temporary)?;
    serde_json::to_writer(&mut file, value)?;
    file.flush()?;
    file.sync_all()?;
    fs::rename(&temporary, path)?;
    fs::File::open(parent)?.sync_all()?;
    Ok(())
}

pub struct Store {
    pub root: PathBuf,
    recent: Vec<Value>,
    _lock: fs::File,
}

impl Store {
    pub fn open(workspace: &Path) -> io::Result<Self> {
        let root = workspace.join("transition_afterimages");
        fs::create_dir_all(root.join("pending"))?;
        fs::create_dir_all(root.join("requests"))?;
        let lock = fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(root.join("observer.lock"))?;
        lock.try_lock().map_err(|error| {
            io::Error::other(format!(
                "archive already owned or lock unavailable: {error}"
            ))
        })?;
        let recent = fs::read(root.join("recent.json"))
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Vec<Value>>(&bytes).ok())
            .unwrap_or_default();
        let mut store = Self {
            root,
            recent,
            _lock: lock,
        };
        store.recover()?;
        Ok(store)
    }

    pub fn artifact_path(&self, artifact: &Artifact) -> io::Result<PathBuf> {
        let date = date_partition(artifact.anchor_unix_ms)
            .ok_or_else(|| io::Error::other("invalid date"))?;
        Ok(self.root.join(date).join(format!("{}.json", artifact.id)))
    }

    pub fn checkpoint(&self, artifact: &Artifact) -> io::Result<()> {
        atomic_json(
            &self
                .root
                .join("pending")
                .join(format!("{}.json", artifact.id)),
            artifact,
        )
    }

    pub fn complete(&mut self, artifact: &Artifact) -> io::Result<()> {
        let path = self.artifact_path(artifact)?;
        let persisted;
        let artifact = if path.exists() {
            persisted = serde_json::from_slice::<Artifact>(&fs::read(&path)?)?;
            &persisted
        } else {
            // Retain a recovery journal until the final file AND its index are synced.
            self.checkpoint(artifact)?;
            atomic_json(&path, artifact)?;
            artifact
        };
        // The index is replaceable; the finalized artifact is the authoritative record.
        self.recent
            .retain(|r| r["id"].as_str() != Some(artifact.id.as_str()));
        self.recent.push(artifact.summary());
        self.recent
            .sort_by_key(|r| std::cmp::Reverse(r["anchor_unix_ms"].as_u64().unwrap_or(0)));
        self.recent.truncate(RECENT_LIMIT);
        atomic_json(&self.root.join("recent.json"), &self.recent)?;
        for request_id in &artifact.request_ids {
            self.receipt(request_id, &artifact.id, &artifact.status, None)?;
        }
        match fs::remove_file(
            self.root
                .join("pending")
                .join(format!("{}.json", artifact.id)),
        ) {
            Ok(()) => (),
            Err(error) if error.kind() == io::ErrorKind::NotFound => (),
            Err(error) => return Err(error),
        }
        Ok(())
    }

    pub fn receipt(
        &self,
        request: &str,
        artifact: &str,
        status: &str,
        reason: Option<&str>,
    ) -> io::Result<()> {
        if !valid_id(request) {
            return Err(io::Error::other("invalid request id"));
        }
        atomic_json(
            &self.root.join("receipts").join(format!("{request}.json")),
            &json!({
                "request_id": request, "afterimage_id": artifact, "status": status,
                "reason": reason, "recorded_at_unix_ms": unix_ms(),
            }),
        )
    }

    fn recover(&mut self) -> io::Result<()> {
        for entry in fs::read_dir(self.root.join("pending"))? {
            let path = entry?.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let mut artifact: Artifact = match serde_json::from_slice(&fs::read(&path)?) {
                Ok(artifact) => artifact,
                Err(error) => {
                    eprintln!("afterimage_corrupt_checkpoint {}: {error}", path.display());
                    fs::rename(&path, path.with_extension("json.corrupt"))?;
                    continue;
                }
            };
            if let Ok(bytes) = fs::read(self.artifact_path(&artifact)?) {
                artifact = serde_json::from_slice(&bytes)?;
            } else {
                Recorder::finalize(&mut artifact, Some("interrupted_capture"));
            }
            self.complete(&artifact)?;
        }
        Ok(())
    }

    pub fn enrich(&self, event: &Event) -> io::Result<()> {
        for row in &self.recent {
            if row["session_id"].as_str() != Some(event.session_id.as_str()) {
                continue;
            }
            if !row["event_sequences"].as_array().is_some_and(|sequences| {
                sequences
                    .iter()
                    .any(|sequence| sequence.as_u64() == Some(event.sequence))
            }) {
                continue;
            }
            let Some(id) = row["id"].as_str().filter(|id| valid_id(id)) else {
                continue;
            };
            let Some(date) = row["anchor_unix_ms"].as_u64().and_then(date_partition) else {
                continue;
            };
            let path = self.root.join(date).join(format!("{id}.json"));
            let artifact: Artifact = serde_json::from_slice(&fs::read(path)?)?;
            if !artifact
                .events
                .iter()
                .any(|e| e.sequence == event.sequence && e.event != event.event)
            {
                continue;
            }
            let bytes = serde_json::to_vec(event)?;
            use sha2::{Digest, Sha256};
            let update = self
                .root
                .join("event_updates")
                .join(id)
                .join(format!("{:x}.json", Sha256::digest(bytes)));
            if !update.exists() {
                atomic_json(
                    &update,
                    &json!({"event":event, "recorded_at_unix_ms":unix_ms()}),
                )?;
            }
        }
        Ok(())
    }
}
