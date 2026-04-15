use std::{
    path::PathBuf,
    time::Duration,
};

use anyhow::{Context, Result};
use clap::{Parser, ValueEnum};
use futures_util::SinkExt;
use serde::Serialize;
use tokio::time::MissedTickBehavior;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use crate::{
    audio::{AudioEngine, DebugWavWriter, CHUNK_MS, SAMPLE_RATE},
    status::{
        now_ms, read_json, write_json_atomic, CameraStatus, HostTelemetryState, MicStatus,
        ModalitySourceState, RuntimePaths, SensoryMode, SensorySourceState, SourceKind,
    },
    telemetry::{ControlFrame, TelemetryProjector, TelemetrySampler},
    video::{save_jpeg, VideoEngine},
};

#[derive(Debug, Clone, Copy, Eq, PartialEq, ValueEnum)]
#[value(rename_all = "lower")]
pub enum SourceModeArg {
    Physical,
    Host,
    Auto,
}

impl From<SourceModeArg> for SensoryMode {
    fn from(value: SourceModeArg) -> Self {
        match value {
            SourceModeArg::Physical => SensoryMode::Physical,
            SourceModeArg::Host => SensoryMode::Host,
            SourceModeArg::Auto => SensoryMode::Auto,
        }
    }
}

#[derive(Debug, Clone, Parser)]
#[command(name = "host-sensory", about = "Host-state A/V fallback producer for minime")]
pub struct Config {
    #[arg(long, value_enum, default_value_t = SourceModeArg::Host)]
    pub mode: SourceModeArg,

    #[arg(long, default_value = "ws://127.0.0.1:7879")]
    pub sensory_uri: String,

    #[arg(long, default_value = "ws://127.0.0.1:7880")]
    pub video_uri: String,

    #[arg(long, default_value = "/Users/v/other/minime/workspace")]
    pub workspace: PathBuf,

    #[arg(long, default_value_t = 250)]
    pub poll_ms: u64,

    #[arg(long, default_value_t = CHUNK_MS)]
    pub audio_chunk_ms: u64,

    #[arg(long, default_value_t = 2.0)]
    pub video_fps: f32,

    #[arg(long)]
    pub seconds: Option<f32>,

    #[arg(long)]
    pub offline: bool,

    #[arg(long)]
    pub debug_wav: Option<PathBuf>,
}

pub fn run(config: Config) -> Result<()> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("failed to build tokio runtime")?;
    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    let mode: SensoryMode = config.mode.into();
    let runtime_paths = RuntimePaths::new(&config.workspace);
    runtime_paths.ensure()?;

    let poll = Duration::from_millis(config.poll_ms.max(100));
    let chunk_ms = config.audio_chunk_ms.max(CHUNK_MS);
    let chunk_samples = ((SAMPLE_RATE as u64 * chunk_ms) / 1000).max(1) as usize;
    let mut sampler = TelemetrySampler::new(poll);
    let mut projector = TelemetryProjector::new();
    let mut control = projector.update(sampler.snapshot());
    write_host_telemetry(&runtime_paths, &control)?;
    let mut audio = AudioEngine::new(&control);
    let mut video = VideoEngine::new();
    let mut debug_wav = match config.debug_wav.as_ref() {
        Some(path) => Some(DebugWavWriter::create(path)?),
        None => None,
    };

    let video_interval = Duration::from_secs_f32((1.0 / config.video_fps.max(0.2)).max(0.1));
    let max_samples = config.seconds.map(|seconds| {
        let safe_seconds = if seconds.is_finite() && seconds > 0.0 {
            seconds
        } else {
            0.0
        };
        (safe_seconds * SAMPLE_RATE as f32).round().max(0.0) as usize
    });
    let mut chunk_interval = tokio::time::interval(Duration::from_millis(
        chunk_ms,
    ));
    chunk_interval.set_missed_tick_behavior(MissedTickBehavior::Skip);

    let mut next_telemetry_at = tokio::time::Instant::now();
    let mut next_video_at = tokio::time::Instant::now();
    let mut source_state = SourceState::new(mode);
    let mut audio_socket = JsonSocket::new(config.sensory_uri.clone());
    let mut control_socket = JsonSocket::new(config.sensory_uri.clone());
    let mut video_socket = BinarySocket::new(config.video_uri.clone());
    let mut shutdown = false;
    let mut rendered_samples = 0usize;

    while !shutdown {
        if max_samples.is_some_and(|limit| rendered_samples >= limit) {
            break;
        }

        tokio::select! {
            _ = chunk_interval.tick() => {}
            _ = tokio::signal::ctrl_c() => {
                shutdown = true;
                continue;
            }
        }

        let now = tokio::time::Instant::now();
        if now >= next_telemetry_at {
            control = projector.update(sampler.snapshot());
            write_host_telemetry(&runtime_paths, &control)?;
            next_telemetry_at = now + poll;
        }

        source_state.refresh(mode, &runtime_paths);
        source_state.write(&runtime_paths)?;

        let desired_legacy = source_state.desired_legacy_synth();
        if !config.offline && desired_legacy != source_state.last_sent_legacy {
            if let Err(err) = control_socket.send_json(&ControlMsg {
                    kind: "control",
                    legacy_audio_synth: Some(desired_legacy.0),
                    legacy_video_synth: Some(desired_legacy.1),
                })
                .await
            {
                eprintln!("host-sensory control send failed: {err:#}");
            } else {
                source_state.last_sent_legacy = desired_legacy;
            }
        }

        let remaining_samples = max_samples
            .map(|limit| limit.saturating_sub(rendered_samples))
            .unwrap_or(chunk_samples);
        let chunk_size = remaining_samples.min(chunk_samples).max(1);
        let audio_chunk = audio.render_chunk(&control, chunk_size);
        rendered_samples = rendered_samples.saturating_add(chunk_size);
        if let Some(writer) = debug_wav.as_mut() {
            writer.append_chunk(&audio_chunk.pcm)?;
        }
        if !config.offline && source_state.audio_source == SourceKind::Host {
            if let Err(err) = audio_socket.send_json(&AudioMsg {
                    kind: "audio",
                    features: audio_chunk.features,
                    ts_ms: now_ms(),
                })
                .await
            {
                eprintln!("host-sensory audio send failed: {err:#}");
            }
        }

        if now >= next_video_at {
            let frame = video.render_frame(&control);
            save_jpeg(&runtime_paths.host_frame_path, &frame)?;
            if !config.offline && source_state.video_source == SourceKind::Host {
                if let Err(err) = video_socket.send(&frame).await {
                    eprintln!("host-sensory video send failed: {err:#}");
                }
            }
            next_video_at = now + video_interval;
        }
    }

    if let Some(writer) = debug_wav {
        writer.finalize()?;
    }

    Ok(())
}

fn write_host_telemetry(paths: &RuntimePaths, control: &ControlFrame) -> Result<()> {
    write_json_atomic(
        &paths.host_telemetry_path,
        &HostTelemetryState {
            updated_at_ms: now_ms(),
            snapshot: control.snapshot,
            entropy: control.entropy,
            motion: control.motion,
            brightness: control.brightness,
            contrast: control.contrast,
            edge_bias: control.edge_bias,
            root_seed: control.root_seed,
        },
    )
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct SourceState {
    mode: SensoryMode,
    audio_source: SourceKind,
    video_source: SourceKind,
    audio_physical_healthy: bool,
    video_physical_healthy: bool,
    audio_reason: &'static str,
    video_reason: &'static str,
    audio_recovery_ready: bool,
    video_recovery_frames: u32,
    last_camera_frame_count: Option<u64>,
    last_sent_legacy: (bool, bool),
}

impl SourceState {
    fn new(mode: SensoryMode) -> Self {
        let initial = match mode {
            SensoryMode::Host => SourceKind::Host,
            SensoryMode::Physical | SensoryMode::Auto => SourceKind::Physical,
        };
        Self {
            mode,
            audio_source: initial,
            video_source: initial,
            audio_physical_healthy: mode != SensoryMode::Host,
            video_physical_healthy: mode != SensoryMode::Host,
            audio_reason: "physical default",
            video_reason: "physical default",
            audio_recovery_ready: false,
            video_recovery_frames: 0,
            last_camera_frame_count: None,
            last_sent_legacy: (true, true),
        }
    }

    fn refresh(&mut self, mode: SensoryMode, paths: &RuntimePaths) {
        self.mode = mode;
        match mode {
            SensoryMode::Host => {
                self.audio_source = SourceKind::Host;
                self.video_source = SourceKind::Host;
                self.audio_physical_healthy = false;
                self.video_physical_healthy = false;
                self.audio_reason = "host mode selected";
                self.video_reason = "host mode selected";
            }
            SensoryMode::Physical => {
                self.audio_source = SourceKind::Physical;
                self.video_source = SourceKind::Physical;
                self.audio_physical_healthy = true;
                self.video_physical_healthy = true;
                self.audio_reason = "physical mode selected";
                self.video_reason = "physical mode selected";
            }
            SensoryMode::Auto => {
                self.refresh_auto(paths);
            }
        }
    }

    fn refresh_auto(&mut self, paths: &RuntimePaths) {
        let mic_status = read_json::<MicStatus>(&paths.mic_status_path);
        let camera_status = read_json::<CameraStatus>(&paths.camera_status_path);
        let now = now_ms();

        let audio_fresh = mic_status
            .as_ref()
            .map_or(false, |status| now.saturating_sub(status.ts_ms) <= 2_000);
        let audio_good_streak = mic_status.as_ref().map_or(0, |status| status.good_streak);
        let audio_silence_streak = mic_status
            .as_ref()
            .map_or(u32::MAX, |status| status.silence_streak);
        let audio_unhealthy = !audio_fresh || audio_silence_streak >= 30;

        if self.audio_source == SourceKind::Physical && audio_unhealthy {
            self.audio_source = SourceKind::Host;
            self.audio_reason = if !audio_fresh {
                "mic heartbeat stale"
            } else {
                "mic RMS stayed near silence"
            };
            self.audio_recovery_ready = false;
        } else if self.audio_source == SourceKind::Host && audio_fresh && audio_good_streak >= 20 {
            self.audio_source = SourceKind::Physical;
            self.audio_reason = "mic heartbeat recovered";
            self.audio_recovery_ready = true;
        } else if self.audio_source == SourceKind::Physical {
            self.audio_reason = "mic healthy";
        }
        self.audio_physical_healthy = audio_fresh && audio_silence_streak < 30;

        let video_fresh = camera_status
            .as_ref()
            .map_or(false, |status| now.saturating_sub(status.ts_ms) <= 5_000);
        let frame_count = camera_status.as_ref().map(|status| status.frame_count);
        let frame_advanced = match (self.last_camera_frame_count, frame_count) {
            (Some(prev), Some(current)) => current > prev,
            (None, Some(_)) => true,
            _ => false,
        };
        self.last_camera_frame_count = frame_count;

        if self.video_source == SourceKind::Physical && !video_fresh {
            self.video_source = SourceKind::Host;
            self.video_reason = "camera heartbeat stale";
            self.video_recovery_frames = 0;
        } else if self.video_source == SourceKind::Host {
            if video_fresh && frame_advanced {
                self.video_recovery_frames = self.video_recovery_frames.saturating_add(1);
            } else if !video_fresh {
                self.video_recovery_frames = 0;
            }
            if self.video_recovery_frames >= 3 {
                self.video_source = SourceKind::Physical;
                self.video_reason = "camera heartbeat recovered";
                self.video_recovery_frames = 0;
            }
        } else {
            self.video_reason = "camera healthy";
        }
        self.video_physical_healthy = video_fresh;
    }

    fn desired_legacy_synth(&self) -> (bool, bool) {
        (
            self.audio_source == SourceKind::Physical,
            self.video_source == SourceKind::Physical,
        )
    }

    fn write(&self, paths: &RuntimePaths) -> Result<()> {
        write_json_atomic(
            &paths.sensory_source_path,
            &SensorySourceState {
                mode: self.mode,
                updated_at_ms: now_ms(),
                audio: ModalitySourceState {
                    source: self.audio_source,
                    physical_healthy: self.audio_physical_healthy,
                    reason: self.audio_reason.to_string(),
                },
                video: ModalitySourceState {
                    source: self.video_source,
                    physical_healthy: self.video_physical_healthy,
                    reason: self.video_reason.to_string(),
                },
                host_frame_path: paths.host_frame_path.display().to_string(),
            },
        )
    }
}

#[derive(Serialize)]
struct AudioMsg {
    kind: &'static str,
    features: [f32; 8],
    ts_ms: u64,
}

#[derive(Serialize)]
struct ControlMsg {
    kind: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    legacy_audio_synth: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    legacy_video_synth: Option<bool>,
}

struct JsonSocket {
    uri: String,
    socket: Option<
        tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
        >,
    >,
}

impl JsonSocket {
    fn new(uri: String) -> Self {
        Self { uri, socket: None }
    }

    async fn send_json<T>(&mut self, payload: &T) -> Result<()>
    where
        T: Serialize,
    {
        let text = serde_json::to_string(payload).context("failed to serialize json message")?;
        self.send_message(Message::Text(text)).await
    }

    async fn send_message(&mut self, message: Message) -> Result<()> {
        if self.socket.is_none() {
            self.connect().await?;
        }
        if let Some(socket) = self.socket.as_mut() {
            if socket.send(message.clone()).await.is_ok() {
                return Ok(());
            }
        }
        self.socket = None;
        self.connect().await?;
        if let Some(socket) = self.socket.as_mut() {
            socket
                .send(message)
                .await
                .with_context(|| format!("failed to send websocket message to {}", self.uri))?;
        }
        Ok(())
    }

    async fn connect(&mut self) -> Result<()> {
        let (socket, _) = connect_async(&self.uri)
            .await
            .with_context(|| format!("failed to connect to {}", self.uri))?;
        self.socket = Some(socket);
        Ok(())
    }
}

struct BinarySocket {
    inner: JsonSocket,
}

impl BinarySocket {
    fn new(uri: String) -> Self {
        Self {
            inner: JsonSocket::new(uri),
        }
    }

    async fn send(&mut self, payload: &[u8]) -> Result<()> {
        self.inner
            .send_message(Message::Binary(payload.to_vec()))
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use crate::status::{write_json_atomic, CameraStatus, MicStatus, SourceKind};

    fn runtime_paths(base: &Path) -> RuntimePaths {
        RuntimePaths::new(base)
    }

    #[test]
    fn auto_mode_switches_audio_to_host_on_stale_status() {
        let temp = tempfile_dir("audio-stale");
        let paths = runtime_paths(&temp);
        paths.ensure().unwrap();
        let mut state = SourceState::new(SensoryMode::Auto);
        write_json_atomic(
            &paths.mic_status_path,
            &MicStatus {
                ts_ms: now_ms().saturating_sub(3_000),
                rms: 0.2,
                silence_streak: 0,
                good_streak: 10,
                chunk_count: 10,
                healthy: true,
            },
        )
        .unwrap();
        state.refresh(SensoryMode::Auto, &paths);
        assert_eq!(state.audio_source, SourceKind::Host);
    }

    #[test]
    fn auto_mode_restores_video_after_three_fresh_frames() {
        let temp = tempfile_dir("video-restore");
        let paths = runtime_paths(&temp);
        paths.ensure().unwrap();
        let mut state = SourceState::new(SensoryMode::Auto);
        state.video_source = SourceKind::Host;

        for frame in 1..=3 {
            write_json_atomic(
                &paths.camera_status_path,
                &CameraStatus {
                    ts_ms: now_ms(),
                    frame_count: frame,
                    healthy: true,
                },
            )
            .unwrap();
            state.refresh(SensoryMode::Auto, &paths);
        }

        assert_eq!(state.video_source, SourceKind::Physical);
    }

    fn tempfile_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("host-sensory-tests-{name}-{}", now_ms()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }
}
