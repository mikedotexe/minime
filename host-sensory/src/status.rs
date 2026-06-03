use std::{
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::telemetry::TelemetrySnapshot;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SensoryMode {
    Physical,
    Host,
    Auto,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceKind {
    Physical,
    Host,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct MicStatus {
    pub ts_ms: u64,
    pub rms: f32,
    pub silence_streak: u32,
    pub good_streak: u32,
    pub chunk_count: u64,
    pub healthy: bool,
    #[serde(default)]
    pub chunk_health_grace_secs: Option<f32>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CameraStatus {
    pub ts_ms: u64,
    pub frame_count: u64,
    pub healthy: bool,
    #[serde(default)]
    pub frame_health_grace_secs: Option<f32>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ModalitySourceState {
    pub source: SourceKind,
    pub physical_healthy: bool,
    pub reason: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SensorySourceState {
    pub mode: SensoryMode,
    pub updated_at_ms: u64,
    pub audio: ModalitySourceState,
    pub video: ModalitySourceState,
    pub host_frame_path: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct HostTelemetryState {
    pub updated_at_ms: u64,
    pub snapshot: TelemetrySnapshot,
    pub entropy: f32,
    pub motion: f32,
    pub brightness: f32,
    pub contrast: f32,
    pub edge_bias: f32,
    pub root_seed: u64,
}

#[derive(Clone, Debug)]
pub struct RuntimePaths {
    pub runtime_dir: PathBuf,
    pub mic_status_path: PathBuf,
    pub camera_status_path: PathBuf,
    pub sensory_source_path: PathBuf,
    pub host_frame_path: PathBuf,
    pub host_telemetry_path: PathBuf,
}

impl RuntimePaths {
    #[must_use]
    pub fn new(workspace: &Path) -> Self {
        let runtime_dir = workspace.join("runtime");
        Self {
            mic_status_path: runtime_dir.join("mic_status.json"),
            camera_status_path: runtime_dir.join("camera_status.json"),
            sensory_source_path: runtime_dir.join("sensory_source.json"),
            host_frame_path: runtime_dir.join("host_frame.jpg"),
            host_telemetry_path: runtime_dir.join("host_telemetry.json"),
            runtime_dir,
        }
    }

    pub fn ensure(&self) -> Result<()> {
        fs::create_dir_all(&self.runtime_dir).with_context(|| {
            format!(
                "failed to create runtime directory {}",
                self.runtime_dir.display()
            )
        })
    }
}

#[must_use]
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

pub fn read_json<T>(path: &Path) -> Option<T>
where
    T: for<'de> Deserialize<'de>,
{
    let data = fs::read(path).ok()?;
    serde_json::from_slice(&data).ok()
}

pub fn write_json_atomic<T>(path: &Path, value: &T) -> Result<()>
where
    T: Serialize,
{
    let parent = path
        .parent()
        .with_context(|| format!("path {} has no parent", path.display()))?;
    fs::create_dir_all(parent)
        .with_context(|| format!("failed to create parent dir {}", parent.display()))?;
    let temp_path = path.with_extension("tmp");
    let bytes = serde_json::to_vec_pretty(value).context("failed to serialize status json")?;
    fs::write(&temp_path, bytes)
        .with_context(|| format!("failed to write temp file {}", temp_path.display()))?;
    fs::rename(&temp_path, path).with_context(|| {
        format!(
            "failed to rename {} to {}",
            temp_path.display(),
            path.display()
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_paths_use_workspace_runtime_dir() {
        let paths = RuntimePaths::new(Path::new("/tmp/minime-workspace"));
        assert_eq!(
            paths.runtime_dir,
            PathBuf::from("/tmp/minime-workspace/runtime")
        );
        assert_eq!(
            paths.host_frame_path,
            PathBuf::from("/tmp/minime-workspace/runtime/host_frame.jpg")
        );
        assert_eq!(
            paths.host_telemetry_path,
            PathBuf::from("/tmp/minime-workspace/runtime/host_telemetry.json")
        );
    }
}
