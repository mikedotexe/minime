async fn run_ws_server(addr: &str, tx: broadcast::Sender<EigenPacket>) -> Result<()> {
    let listener = TcpListener::bind(addr).await?;
    println!("📡 WebSocket server listening on {}", addr);

    while let Ok((stream, peer)) = listener.accept().await {
        let tx = tx.clone();
        tokio::spawn(handle_client(stream, peer, tx));
    }

    Ok(())
}

async fn handle_client(stream: TcpStream, peer: SocketAddr, tx: broadcast::Sender<EigenPacket>) {
    println!("🔗 Client connected: {}", peer);

    let ws_stream = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            eprintln!("WebSocket handshake failed: {}", e);
            return;
        }
    };

    let (mut ws_tx, mut ws_rx) = ws_stream.split();
    let mut rx = tx.subscribe();

    // Keepalive: periodic ping and pong timeout watchdog
    let mut ping_timer = tokio::time::interval(std::time::Duration::from_secs(10));
    let mut last_pong = std::time::Instant::now();

    loop {
        tokio::select! {
            // Periodic server ping (keeps connection alive, detects dead clients)
            _ = ping_timer.tick() => {
                if ws_tx.send(Message::Ping(Vec::new())).await.is_err() {
                    eprintln!("Failed to send ping to {}, closing", peer);
                    break;
                }
                // Check pong timeout (45 seconds without response = dead connection)
                if last_pong.elapsed() > std::time::Duration::from_secs(45) {
                    eprintln!("Pong timeout from {}, closing", peer);
                    break;
                }
            }
            // Send eigenvalue packets
            Ok(packet) = rx.recv() => {
                let json = match encode_eigenpacket_v1(&packet) {
                    Ok(j) => j,
                    Err(error) => {
                        eprintln!("Failed to encode canonical EigenPacketV1: {error}");
                        continue;
                    }
                };
                if ws_tx.send(Message::Text(json)).await.is_err() {
                    break;
                }
            }
            // Handle incoming messages
            Some(msg) = ws_rx.next() => {
                match msg {
                    Ok(Message::Ping(p)) => {
                        // Client sent ping, reply with pong
                        let _ = ws_tx.send(Message::Pong(p)).await;
                    }
                    Ok(Message::Pong(_)) => {
                        // Client replied to our ping, update watchdog
                        last_pong = std::time::Instant::now();
                    }
                    Ok(Message::Close(_)) | Err(_) => break,
                    _ => {}
                }
            }
        }
    }

    println!("❌ Client disconnected: {}", peer);
}

fn encode_eigenpacket_v1(packet: &EigenPacket) -> serde_json::Result<String> {
    #[derive(Serialize)]
    struct VersionedEigenPacket<'a> {
        protocol: ProtocolHeaderV1,
        #[serde(flatten)]
        packet: &'a EigenPacket,
    }

    let encoded = serde_json::to_string(&VersionedEigenPacket {
        protocol: current_protocol(),
        packet,
    })?;
    let _: EigenPacketV1 = serde_json::from_str(&encoded)?;
    Ok(encoded)
}

// Helper: Rank-1 update A += z * z^T
fn rank1_update(
    gpu: &Gpu,
    a_buf: &metal::Buffer,
    z: &[f32],
    n: usize,
    keep: f32,
    trace_target: f32,
) {
    let outcome = {
        let a = gpu.as_f32_slice_mut(a_buf, n * n);
        rank1_update_inplace_matrix(a, z, n, keep, trace_target)
    };

    match outcome {
        CovarianceUpdateOutcome::Skipped => {
            eprintln!("[cov] skipped rank1 update due to non-finite input");
        }
        CovarianceUpdateOutcome::Modified => {
            gpu.mark_modified_f32(a_buf, n * n);
        }
        CovarianceUpdateOutcome::ResetRequired => {
            reset_covariance(gpu, a_buf, n);
        }
    }
}

#[allow(dead_code)]
fn decay_covariance(gpu: &Gpu, a_buf: &metal::Buffer, n: usize, keep: f32, trace_target: f32) {
    let should_reset = {
        let a = gpu.as_f32_slice_mut(a_buf, n * n);
        !decay_covariance_inplace_matrix(a, n, keep, trace_target)
    };
    if should_reset {
        reset_covariance(gpu, a_buf, n);
    } else {
        gpu.mark_modified_f32(a_buf, n * n);
    }
}

fn reset_covariance(gpu: &Gpu, a_buf: &metal::Buffer, n: usize) {
    eprintln!("[cov] covariance reset to identity");
    {
        let a = gpu.as_f32_slice_mut(a_buf, n * n);
        reset_covariance_inplace(a, n);
    }
    gpu.mark_modified_f32(a_buf, n * n);
}
