// src/net/ws_server.rs
// Tokio Tungstenite server with heartbeat, bounded channels, and drop-old backpressure.

use std::net::SocketAddr;
use std::time::{Duration, Instant};

use anyhow::Result;
use futures_util::{FutureExt, SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::TcpListener;
use tokio::sync::{broadcast, mpsc};
use tokio::time::interval;
use tokio_tungstenite::tungstenite::protocol::{frame::coding::CloseCode, Message};
use tokio_tungstenite::{accept_async, tungstenite};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpectralMsg {
    pub t_ms: u64,
    pub lambdas: Vec<f32>, // optional: allow empty if only λ1 provided
    pub lambda1: Option<f32>,
}

#[derive(Clone)]
pub struct WsHub {
    tx: broadcast::Sender<SpectralMsg>,
}

impl WsHub {
    pub fn new(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        Self { tx }
    }
    pub fn broadcast(&self, msg: SpectralMsg) {
        // Ignore errors (no listeners / lagging receivers)
        let _ = self.tx.send(msg);
    }
    pub fn subscribe(&self) -> broadcast::Receiver<SpectralMsg> {
        self.tx.subscribe()
    }
}

pub async fn run_ws(addr: SocketAddr, hub: WsHub) -> Result<()> {
    let listener = TcpListener::bind(addr).await?;
    println!("📡 WebSocket server listening on {}", addr);

    loop {
        let (stream, peer) = listener.accept().await?;
        tokio::spawn(handle_client(stream, peer, hub.clone()).map(|r| {
            if let Err(e) = r {
                eprintln!("client task error: {e:?}");
            }
        }));
    }
}

async fn handle_client(stream: tokio::net::TcpStream, peer: SocketAddr, hub: WsHub) -> Result<()> {
    // TCP opts: keepalive + nodelay
    stream.set_nodelay(true)?;

    // Note: set_keepalive is platform-specific, using simpler approach

    let ws_stream = accept_async(stream).await?;
    println!("🔗 Client connected: {}", peer);
    let (mut ws_tx, mut ws_rx) = ws_stream.split();

    // Per-client bounded queue; drop-old if slow
    let (tx, mut rx) = mpsc::channel::<Message>(256);

    // Fan-out from hub to this client
    let mut sub = hub.subscribe();
    let tx_clone = tx.clone();
    let writer = async move {
        let mut beat = interval(Duration::from_secs(10));
        loop {
            tokio::select! {
                _ = beat.tick() => {
                    // heartbeat ping
                    if tx_clone.is_closed() { break; }
                    let _ = tx_clone.try_send(Message::Ping(Vec::new()));
                }
                msg = sub.recv() => {
                    match msg {
                        Ok(s) => {
                            let json = serde_json::to_vec(&s).unwrap();
                            let _ = tx_clone.try_send(Message::Binary(json));
                        }
                        Err(_) => break,
                    }
                }
                else => break,
            }
        }
        Result::<()>::Ok(())
    };

    // Writer pump to socket
    let socket_writer = async move {
        while let Some(msg) = rx.recv().await {
            if ws_tx.send(msg).await.is_err() {
                break;
            }
        }
        Result::<()>::Ok(())
    };

    // Reader: respond to Pong / close / client messages
    let socket_reader = async move {
        let mut last_pong = Instant::now();
        let mut watchdog = interval(Duration::from_secs(15));
        loop {
            tokio::select! {
                _ = watchdog.tick() => {
                    if last_pong.elapsed() > Duration::from_secs(45) {
                        // idle: close
                        let _ = tx.try_send(Message::Close(Some(tungstenite::protocol::CloseFrame{
                            code: CloseCode::Away, reason: "heartbeat timeout".into()
                        })));
                        break;
                    }
                }
                msg = ws_rx.next() => {
                    match msg {
                        Some(Ok(Message::Pong(_))) => { last_pong = Instant::now(); }
                        Some(Ok(Message::Ping(v))) => {
                            // reply
                            let _ = tx.try_send(Message::Pong(v));
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        Some(Ok(_)) => { /* ignore */ }
                        Some(Err(_e)) => break,
                    }
                }
            }
        }
        println!("❌ Client disconnected: {}", peer);
        Ok(())
    };

    tokio::try_join!(writer, socket_writer, socket_reader)?;
    Ok(())
}
