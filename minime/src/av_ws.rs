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
use std::path::PathBuf;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc as tokio_mpsc;
use tokio_tungstenite::{accept_async, tungstenite::Message};

const AV_SHADER_RELATIVE_PATH: &str = "shaders/av_features.metal";

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

// Spawns both the GPU processing task and WebSocket server.
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

    // Keepalive: periodic ping and pong timeout watchdog
    let mut ping_timer = tokio::time::interval(std::time::Duration::from_secs(10));
    let mut last_pong = std::time::Instant::now();

    loop {
        tokio::select! {
            // Periodic server ping (keeps connection alive, detects dead clients)
            _ = ping_timer.tick() => {
                if ws.send(Message::Ping(Vec::new())).await.is_err() {
                    eprintln!("Failed to send ping to GPU client, closing");
                    break;
                }
                // Check pong timeout (30 seconds without response = dead connection)
                if last_pong.elapsed() > std::time::Duration::from_secs(30) {
                    eprintln!("Pong timeout from GPU client, closing");
                    break;
                }
            }
            // Handle incoming messages
            msg_result = ws.next() => {
                let Some(msg_result) = msg_result else { break };
                match msg_result {
                    Ok(msg) => match msg {
                        Message::Binary(data) => {
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
                            // Reply to client ping with pong
                            if let Err(e) = ws.send(Message::Pong(payload)).await {
                                eprintln!("❌ Pong send error: {}", e);
                                break;
                            }
                        }
                        Message::Pong(_) => {
                            // Client replied to our ping, update watchdog
                            last_pong = std::time::Instant::now();
                        }
                        Message::Close(_) => {
                            println!("🛑 GPU A/V client disconnected (close frame)");
                            break;
                        }
                        _ => {
                            // Ignore text, etc.
                        }
                    },
                    Err(e) => {
                        eprintln!("❌ WebSocket error: {}", e);
                        break;
                    }
                }
            }
        }
    }

    println!(
        "📹 GPU A/V client handler finished ({} frames received)",
        frame_count
    );
    Ok(())
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
