// src/sensory_ws.rs
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::{
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{net::TcpListener, select, time};
use tokio_tungstenite::{accept_async, tungstenite::protocol::Message};

use crate::sensory_bus::{NowMs, SensoryBus};

const KEEPALIVE_PING_INTERVAL_SECS: u64 = 20;
const KEEPALIVE_TIMEOUT_SECS: u64 = 60;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum SensoryMsg {
    // video/audio: features length 8 expected by your intake
    Video {
        features: Vec<f32>,
        ts_ms: Option<u64>,
    },
    Audio {
        features: Vec<f32>,
        ts_ms: Option<u64>,
    },
    // optional: aux from external producers (λ1, fill)
    Aux {
        features: Vec<f32>,
        ts_ms: Option<u64>,
    },
    Semantic {
        features: Vec<f32>,
        ts_ms: Option<u64>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DisconnectReason {
    StreamEnded,
    SendPingFailed,
    InactivityTimeout,
    CloseFrame,
    ReceiveError,
    HandshakeError,
}

impl DisconnectReason {
    fn as_str(self) -> &'static str {
        match self {
            Self::StreamEnded => "stream_ended",
            Self::SendPingFailed => "send_ping_failed",
            Self::InactivityTimeout => "inactivity_timeout",
            Self::CloseFrame => "close_frame",
            Self::ReceiveError => "receive_error",
            Self::HandshakeError => "handshake_error",
        }
    }
}

fn connection_timed_out(last_rx: Instant, last_pong: Instant, now: Instant) -> bool {
    now.duration_since(last_rx) > Duration::from_secs(KEEPALIVE_TIMEOUT_SECS)
        && now.duration_since(last_pong) > Duration::from_secs(KEEPALIVE_TIMEOUT_SECS)
}

pub async fn spawn_sensory_ws_server(
    bus: Arc<SensoryBus>,
    addr: SocketAddr,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let listener = TcpListener::bind(addr)
            .await
            .expect("bind ws sensory server");
        println!("🎥 Sensory input server listening on ws://{}", addr);

        loop {
            let (stream, peer) = match listener.accept().await {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("WS accept error: {e}");
                    continue;
                }
            };
            let bus = bus.clone();

            tokio::spawn(async move {
                match accept_async(stream).await {
                    Ok(mut ws) => {
                        println!("🔗 Sensory client connected: {}", peer);
                        let mut ping_int =
                            time::interval(Duration::from_secs(KEEPALIVE_PING_INTERVAL_SECS));
                        let mut last_rx = Instant::now();
                        let mut last_pong = last_rx;
                        let disconnect_reason = loop {
                            select! {
                                _ = ping_int.tick() => {
                                    if let Err(e) = ws.send(Message::Ping(Vec::new())).await {
                                        eprintln!("WS send ping failed: {e}");
                                        break DisconnectReason::SendPingFailed;
                                    }
                                    if connection_timed_out(last_rx, last_pong, Instant::now()) {
                                        break DisconnectReason::InactivityTimeout;
                                    }
                                }
                                msg = ws.next() => {
                                    let Some(msg) = msg else {
                                        break DisconnectReason::StreamEnded;
                                    };
                                    match msg {
                                        Ok(Message::Text(s)) => {
                                            last_rx = Instant::now();
                                            if let Ok(m) = serde_json::from_str::<SensoryMsg>(&s) {
                                                route_msg(&bus, m);
                                            }
                                        }
                                        Ok(Message::Binary(b)) => {
                                            last_rx = Instant::now();
                                            if let Ok(s) = std::str::from_utf8(&b) {
                                                if let Ok(m) = serde_json::from_str::<SensoryMsg>(s) {
                                                    route_msg(&bus, m);
                                                }
                                            }
                                        }
                                        Ok(Message::Ping(p)) => {
                                            last_rx = Instant::now();
                                            let _ = ws.send(Message::Pong(p)).await;
                                        }
                                        Ok(Message::Pong(_)) => {
                                            let now = Instant::now();
                                            last_rx = now;
                                            last_pong = now;
                                        }
                                        Ok(Message::Close(_)) => {
                                            break DisconnectReason::CloseFrame;
                                        }
                                        Ok(Message::Frame(_)) => {
                                            last_rx = Instant::now();
                                        }
                                        Err(e) => {
                                            eprintln!("WS recv error: {e}");
                                            break DisconnectReason::ReceiveError;
                                        }
                                    }
                                }
                            }
                        };

                        println!(
                            "❌ Sensory client disconnected: {} ({})",
                            peer,
                            disconnect_reason.as_str()
                        );
                    }
                    Err(e) => eprintln!(
                        "WS handshake error from {peer}: {e} ({})",
                        DisconnectReason::HandshakeError.as_str()
                    ),
                }
            });
        }
    })
}

fn route_msg(bus: &SensoryBus, m: SensoryMsg) {
    match m {
        SensoryMsg::Video { features, ts_ms } => {
            bus.push_video(features, ts_ms.unwrap_or_else(NowMs::now));
        }
        SensoryMsg::Audio { features, ts_ms } => {
            bus.push_audio(features, ts_ms.unwrap_or_else(NowMs::now));
        }
        SensoryMsg::Aux { features, ts_ms: _ } => {
            // Allows external aux but normally aux is fed internally
            if features.len() >= 2 {
                bus.set_aux([features[0], features[1]]);
            }
        }
        SensoryMsg::Semantic { features, ts_ms } => {
            bus.set_llava_embedding(&features, ts_ms.unwrap_or_else(NowMs::now));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connection_timeout_requires_stale_pong_and_stale_receive() {
        let now = Instant::now();
        let stale_rx = now - Duration::from_secs(KEEPALIVE_TIMEOUT_SECS + 1);
        let stale_pong = now - Duration::from_secs(KEEPALIVE_TIMEOUT_SECS + 1);
        let fresh_rx = now - Duration::from_secs(5);

        assert!(connection_timed_out(stale_rx, stale_pong, now));
        assert!(!connection_timed_out(fresh_rx, stale_pong, now));
    }
}
