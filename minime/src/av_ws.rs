// src/av_ws.rs
// Binary WebSocket server for GPU-first video feature extraction.
//
// Accepts raw 128×128 grayscale frames over WebSocket, processes via Metal GPU,
// and forwards 8-D features to the sensory bus.
//
// Protocol:
//   Client → Server: Binary frame (W×H bytes, R8 grayscale)
//   Server → Client: Pong replies to Ping frames (keepalive)
//
// Usage:
//   spawn_av_gpu_server(video_tx, AvServerCfg::default()).await?;

use anyhow::{anyhow, Result};
use futures_util::{SinkExt, StreamExt};
use std::{path::PathBuf, time::Instant};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc as tokio_mpsc;
use tokio_tungstenite::{accept_async, tungstenite::Message};

const AV_SHADER_RELATIVE_PATH: &str = "shaders/av_features.metal";
const KEEPALIVE_PING_INTERVAL_SECS: u64 = 20;
const KEEPALIVE_TIMEOUT_SECS: u64 = 60;

fn connection_timed_out(last_rx: Instant, last_pong: Instant, now: Instant) -> bool {
    now.duration_since(last_rx) > std::time::Duration::from_secs(KEEPALIVE_TIMEOUT_SECS)
        && now.duration_since(last_pong) > std::time::Duration::from_secs(KEEPALIVE_TIMEOUT_SECS)
}

fn resolve_av_shader_path() -> Result<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join(AV_SHADER_RELATIVE_PATH));
        candidates.push(cwd.join("minime").join(AV_SHADER_RELATIVE_PATH));
    }

    if let Ok(exe) = std::env::current_exe() {
        let crate_root = exe
            .parent()
            .and_then(|path| path.parent())
            .and_then(|path| path.parent());
        if let Some(crate_root) = crate_root {
            candidates.push(crate_root.join(AV_SHADER_RELATIVE_PATH));
        }
    }

    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(AV_SHADER_RELATIVE_PATH));

    candidates
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| anyhow!("could not locate {}", AV_SHADER_RELATIVE_PATH))
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct AvServerCfg {
    pub bind: String,
    pub width: usize,
    pub height: usize,
}

impl Default for AvServerCfg {
    fn default() -> Self {
        Self {
            bind: "127.0.0.1:7880".to_string(),
            width: 128,
            height: 128,
        }
    }
}

/// Spawns both the GPU processing task and WebSocket server
/* DEPRECATED: Use spawn_av_gpu_server_v2 instead
pub async fn spawn_av_gpu_server(
    video_tx: mpsc::Sender<sensory_bus::VideoFeat>,
    cfg: AvServerCfg,
) -> Result<()> {
    // Channel for raw frames to GPU processor
    let (frame_tx, mut frame_rx) = tokio_mpsc::channel::<Vec<u8>>(16);

    // Spawn GPU processing task (single AvGpu instance, sequential processing)
    let video_tx_clone = video_tx.clone();
    let cfg_clone = cfg.clone();
    tokio::spawn(async move {
        // Initialize GPU once
        let mut av = match crate::av_gpu::AvGpu::new(
            "shaders/av_features.metal",
            crate::av_gpu::MemMode::Shared
        ) {
            Ok(mut gpu) => {
                if let Err(e) = gpu.set_frame_size(cfg_clone.width, cfg_clone.height) {
                    eprintln!("❌ Failed to set GPU frame size: {}", e);
                    return;
                }
                gpu
            }
            Err(e) => {
                eprintln!("❌ Failed to initialize GPU: {}", e);
                return;
            }
        };

        println!("✅ GPU initialized (Metal unified memory)");

        let mut frame_count = 0u64;
        while let Some(frame_bytes) = frame_rx.recv().await {
            // Process frame on GPU
            match av.process_frame_gray8(&frame_bytes) {
                Ok(features) => {
                    // Send to sensory bus
                    let video_feat = sensory_bus::VideoFeat {
                        ts: Instant::now(),
                        v: features.to_vec(),
                    };

                    if let Err(e) = video_tx_clone.send(video_feat) {
                        eprintln!("❌ Failed to forward GPU features: {}", e);
                        break;
                    }

                    frame_count += 1;
                    if frame_count % 30 == 0 {
                        println!(
                            "🎨 Processed {} GPU frames | Latest: [mean={:.3}, var={:.3}, motion={:.3}, edge={:.3}]",
                            frame_count, features[0], features[1], features[2], features[3]
                        );
                    }
                }
                Err(e) => {
                    eprintln!("❌ GPU processing error: {}", e);
                }
            }
        }

        println!("🛑 GPU processing task stopped");
    });

    // Spawn WebSocket server
    let listener = TcpListener::bind(&cfg.bind).await?;
    println!("🎥 GPU A/V WebSocket server listening on ws://{}", cfg.bind);

    let expected_bytes = cfg.width * cfg.height;

    tokio::spawn(async move {
        loop {
            match listener.accept().await {
                Ok((stream, addr)) => {
                    println!("📹 GPU A/V client connected from {}", addr);
                    let frame_tx_clone = frame_tx.clone();
                    tokio::spawn(async move {
                        if let Err(e) = handle_av_client(stream, frame_tx_clone, expected_bytes).await {
                            eprintln!("❌ GPU A/V client error: {}", e);
                        }
                    });
                }
                Err(e) => {
                    eprintln!("❌ Accept error: {}", e);
                }
            }
        }
    });

    Ok(())
}
*/

async fn handle_av_client(
    stream: TcpStream,
    frame_tx: tokio_mpsc::Sender<Vec<u8>>,
    expected_bytes: usize,
) -> Result<()> {
    let mut ws = accept_async(stream).await?;
    let mut frame_count = 0u64;

    let mut ping_timer =
        tokio::time::interval(std::time::Duration::from_secs(KEEPALIVE_PING_INTERVAL_SECS));
    let mut last_pong = Instant::now();
    let mut last_rx = last_pong;
    let mut disconnect_reason = "stream_ended";

    loop {
        tokio::select! {
            _ = ping_timer.tick() => {
                if ws.send(Message::Ping(Vec::new())).await.is_err() {
                    disconnect_reason = "send_ping_failed";
                    break;
                }
                if connection_timed_out(last_rx, last_pong, Instant::now()) {
                    disconnect_reason = "inactivity_timeout";
                    break;
                }
            }
            msg_result = ws.next() => {
                let Some(msg_result) = msg_result else {
                    disconnect_reason = "stream_ended";
                    break;
                };
                match msg_result {
                    Ok(msg) => match msg {
                        Message::Binary(data) => {
                            last_rx = Instant::now();
                            if data.len() != expected_bytes {
                                eprintln!(
                                    "⚠️  Frame size mismatch: got {} bytes, want {}",
                                    data.len(), expected_bytes
                                );
                                continue;
                            }

                            // Forward frame to GPU processor
                            if let Err(_) = frame_tx.send(data).await {
                                eprintln!("⚠️  GPU processor channel closed");
                                break;
                            }

                            frame_count += 1;
                        }
                        Message::Ping(payload) => {
                            last_rx = Instant::now();
                            if let Err(e) = ws.send(Message::Pong(payload)).await {
                                eprintln!("❌ Pong send error: {}", e);
                                disconnect_reason = "pong_send_failed";
                                break;
                            }
                        }
                        Message::Pong(_) => {
                            let now = Instant::now();
                            last_rx = now;
                            last_pong = now;
                        }
                        Message::Close(_) => {
                            disconnect_reason = "close_frame";
                            break;
                        }
                        _ => {
                            last_rx = Instant::now();
                        }
                    },
                    Err(e) => {
                        eprintln!("❌ WebSocket error: {}", e);
                        disconnect_reason = "receive_error";
                        break;
                    }
                }
            }
        }
    }

    println!(
        "📹 GPU A/V client handler finished ({} frames received, reason={})",
        frame_count, disconnect_reason
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connection_timeout_requires_stale_receive_and_stale_pong() {
        let now = Instant::now();
        let stale = now - std::time::Duration::from_secs(KEEPALIVE_TIMEOUT_SECS + 1);
        let fresh = now - std::time::Duration::from_secs(5);

        assert!(connection_timed_out(stale, stale, now));
        assert!(!connection_timed_out(fresh, stale, now));
    }
}

/// V2: GPU server that pushes directly to the new SensoryBus (fix pack architecture)
pub async fn spawn_av_gpu_server_v2(
    bind_addr: std::net::SocketAddr,
    sensory_bus: std::sync::Arc<crate::sensory_bus::SensoryBus>,
) -> Result<()> {
    use crate::sensory_bus::NowMs;
    let shader_path = resolve_av_shader_path()?;

    // Channel for raw frames to GPU processor
    let (frame_tx, mut frame_rx) = tokio_mpsc::channel::<Vec<u8>>(16);

    // Spawn GPU processing task
    let bus_clone = sensory_bus.clone();
    tokio::spawn(async move {
        // Initialize GPU once
        let mut av = match crate::av_gpu::AvGpu::new(
            shader_path
                .to_str()
                .expect("resolved shader path is valid UTF-8"),
            crate::av_gpu::MemMode::Shared,
        ) {
            Ok(mut gpu) => {
                if let Err(e) = gpu.set_frame_size(128, 128) {
                    eprintln!("❌ Failed to set GPU frame size: {}", e);
                    return;
                }
                gpu
            }
            Err(e) => {
                eprintln!("❌ Failed to initialize GPU: {}", e);
                return;
            }
        };

        println!(
            "✅ GPU initialized (Metal unified memory) using {}",
            shader_path.display()
        );

        let mut frame_count = 0u64;
        while let Some(frame_bytes) = frame_rx.recv().await {
            // Process frame on GPU
            match av.process_frame_gray8(&frame_bytes) {
                Ok(features) => {
                    // Push directly to sensory bus
                    bus_clone.push_video(features.to_vec(), NowMs::now());

                    frame_count += 1;
                    if frame_count % 30 == 0 {
                        println!(
                            "🎨 Processed {} GPU frames | Latest: [mean={:.3}, var={:.3}, motion={:.3}, edge={:.3}]",
                            frame_count, features[0], features[1], features[2], features[3]
                        );
                    }
                }
                Err(e) => {
                    eprintln!("❌ GPU processing error: {}", e);
                }
            }
        }

        println!("🛑 GPU processing task stopped");
    });

    // Spawn WebSocket server
    let listener = TcpListener::bind(bind_addr).await?;
    println!(
        "🎥 GPU A/V WebSocket server listening on ws://{}",
        bind_addr
    );

    let expected_bytes = 128 * 128;

    tokio::spawn(async move {
        loop {
            match listener.accept().await {
                Ok((stream, addr)) => {
                    println!("📹 GPU A/V client connected from {}", addr);
                    let frame_tx_clone = frame_tx.clone();
                    tokio::spawn(async move {
                        if let Err(e) =
                            handle_av_client(stream, frame_tx_clone, expected_bytes).await
                        {
                            eprintln!("❌ GPU A/V client error: {}", e);
                        }
                    });
                }
                Err(e) => {
                    eprintln!("❌ Accept error: {}", e);
                }
            }
        }
    });

    Ok(())
}
