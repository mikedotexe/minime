// src/sensory_ws.rs
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{net::TcpListener, select, time};
use tokio_tungstenite::{accept_async, tungstenite::protocol::Message};

use crate::sensory_bus::{NowMs, SensoryBus};

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
                        let mut ping_int = time::interval(Duration::from_secs(10));

                        loop {
                            select! {
                                // periodic server ping (keeps NATs happy and gives client a chance to reply)
                                _ = ping_int.tick() => {
                                    if let Err(e) = ws.send(Message::Ping(Vec::new())).await {
                                        eprintln!("WS send ping failed: {e}");
                                        break;
                                    }
                                }
                                // incoming frames
                                msg = ws.next() => {
                                    let Some(msg) = msg else { break };
                                    match msg {
                                        Ok(Message::Text(s)) => {
                                            if let Ok(m) = serde_json::from_str::<SensoryMsg>(&s) {
                                                route_msg(&bus, m);
                                            }
                                        }
                                        Ok(Message::Binary(b)) => {
                                            if let Ok(s) = std::str::from_utf8(&b) {
                                                if let Ok(m) = serde_json::from_str::<SensoryMsg>(s) {
                                                    route_msg(&bus, m);
                                                }
                                            }
                                        }
                                        Ok(Message::Ping(p)) => {
                                            // reply to client keepalive
                                            let _ = ws.send(Message::Pong(p)).await;
                                        }
                                        Ok(Message::Pong(_)) => {
                                            // fine; no-op
                                        }
                                        Ok(Message::Close(_)) => break,
                                        Ok(Message::Frame(_)) => {
                                            // Raw frame - ignore (shouldn't happen in normal protocol)
                                        }
                                        Err(e) => { eprintln!("WS recv error: {e}"); break; }
                                    }
                                }
                            }
                        }

                        println!("❌ Sensory client disconnected: {}", peer);
                    }
                    Err(e) => eprintln!("WS handshake error from {peer}: {e}"),
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
        SensoryMsg::Semantic { features, ts_ms: _ } => {
            bus.set_llava_embedding(&features);
        }
    }
}
