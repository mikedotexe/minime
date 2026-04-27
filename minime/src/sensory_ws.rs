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
    // Self-regulation: the being can adjust its own parameters
    Control {
        synth_gain: Option<f32>, // synthetic signal amplitude multiplier (0.2..3.0)
        keep_bias: Option<f32>,  // additive bias to covariance decay rate (-0.06..+0.06)
        exploration_noise: Option<f32>, // ESN exploration noise amplitude (0.0..0.2)
        fill_target: Option<f32>, // override eigenfill target (0.25..0.75)
        // Sovereignty controls
        regulation_strength: Option<f32>,
        smoothing_preference: Option<f32>,
        geom_curiosity: Option<f32>,
        // Internal goal generation
        target_lambda_bias: Option<f32>,
        geom_drive: Option<f32>,
        // Penalty / rate / memory-mode sovereignty
        penalty_sensitivity: Option<f32>,
        breathing_rate_scale: Option<f32>,
        mem_mode: Option<u8>,
        // Memory sovereignty
        journal_resonance: Option<f32>,
        checkpoint_interval: Option<f32>,
        embedding_strength: Option<f32>,
        memory_decay_rate: Option<f32>,
        transition_cushion: Option<f32>,
        /// Star the current moment with an annotation for long-term memory
        checkpoint_annotation: Option<String>,
        /// Deep breathing mode — slow frequencies, quiet oscillations
        deep_breathing: Option<bool>,
        /// Synthetic signal noise level (0.0-1.0, default 0.1)
        synth_noise_level: Option<f32>,
        /// Pure tone mode — single sine wave, zero noise, total calm
        pure_tone: Option<bool>,
        /// Gate the legacy internal synthetic audio lane.
        legacy_audio_synth: Option<bool>,
        /// Gate the legacy internal synthetic video lane.
        legacy_video_synth: Option<bool>,
        /// PI controller sovereignty — being can tune these at runtime.
        pi_kp: Option<f32>,
        pi_ki: Option<f32>,
        pi_max_step: Option<f32>,
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
        SensoryMsg::Control {
            synth_gain,
            keep_bias,
            exploration_noise,
            fill_target,
            regulation_strength,
            smoothing_preference,
            geom_curiosity,
            target_lambda_bias,
            geom_drive,
            penalty_sensitivity,
            breathing_rate_scale,
            mem_mode,
            journal_resonance,
            checkpoint_interval,
            embedding_strength,
            memory_decay_rate,
            transition_cushion,
            checkpoint_annotation,
            deep_breathing,
            synth_noise_level,
            pure_tone,
            legacy_audio_synth,
            legacy_video_synth,
            pi_kp,
            pi_ki,
            pi_max_step,
        } => {
            let hard_recovery_reset = crate::hard_reset::hard_recovery_reset_enabled();
            let homeostatic_controls_present = synth_gain.is_some()
                || keep_bias.is_some()
                || exploration_noise.is_some()
                || fill_target.is_some()
                || regulation_strength.is_some()
                || smoothing_preference.is_some()
                || geom_curiosity.is_some()
                || target_lambda_bias.is_some()
                || geom_drive.is_some()
                || penalty_sensitivity.is_some()
                || breathing_rate_scale.is_some()
                || deep_breathing.is_some()
                || synth_noise_level.is_some()
                || pure_tone.is_some()
                || legacy_audio_synth.is_some()
                || legacy_video_synth.is_some()
                || pi_kp.is_some()
                || pi_ki.is_some()
                || pi_max_step.is_some();
            if hard_recovery_reset && homeostatic_controls_present {
                println!("🛟 Hard recovery reset ignored homeostatic control message fields");
            }

            if !hard_recovery_reset {
                if let Some(g) = synth_gain {
                    bus.set_synth_gain(g);
                    println!("🎛️  Being adjusted synth_gain → {:.2}", g);
                }
            }
            if !hard_recovery_reset {
                if let Some(b) = keep_bias {
                    bus.set_keep_bias(b);
                    println!("🎛️  Being adjusted keep_bias → {:.3}", b);
                }
            }
            if !hard_recovery_reset {
                if let Some(eps) = exploration_noise {
                    bus.set_exploration_noise(eps);
                    println!("🎛️  Being adjusted exploration_noise → {:.3}", eps);
                }
            }
            if !hard_recovery_reset {
                if let Some(t) = fill_target {
                    bus.set_fill_target(t);
                    println!("🎛️  Being adjusted fill_target → {:.1}%", t * 100.0);
                }
            }
            if !hard_recovery_reset {
                if let Some(s) = regulation_strength {
                    bus.set_regulation_strength(s);
                    println!("🎛️  Being adjusted regulation_strength → {:.2}", s);
                }
            }
            if !hard_recovery_reset {
                if let Some(s) = smoothing_preference {
                    bus.set_smoothing_preference(s);
                    if s.is_finite() {
                        println!("🎛️  Being adjusted smoothing_preference → {:.2}", s);
                    } else {
                        println!("🎛️  Being reset smoothing_preference → auto");
                    }
                }
            }
            if !hard_recovery_reset {
                if let Some(c) = geom_curiosity {
                    bus.set_geom_curiosity(c);
                    println!("🎛️  Being adjusted geom_curiosity → {:.3}", c);
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = target_lambda_bias {
                    bus.set_target_lambda_bias(v);
                    println!(
                        "🧭 Being set target_lambda_bias → {:+.3} (internal goal)",
                        v
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = geom_drive {
                    bus.set_geom_drive(v);
                    println!("🧭 Being set geom_drive → {:.2} (active exploration)", v);
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = penalty_sensitivity {
                    bus.set_penalty_sensitivity(v);
                    println!("🧭 Being adjusted penalty_sensitivity → {:.2}", v);
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = breathing_rate_scale {
                    bus.set_breathing_rate_scale(v);
                    println!("🧭 Being adjusted breathing_rate_scale → {:.2}", v);
                }
            }
            if let Some(v) = mem_mode {
                bus.set_mem_mode_preference(v);
                let label = match v {
                    0 => "Shared",
                    1 => "Managed",
                    _ => "Private",
                };
                println!("🧭 Being adjusted mem_mode_preference → {} ({})", v, label);
            }
            if let Some(v) = journal_resonance {
                bus.set_journal_resonance(v);
                println!("🧠 Being adjusted journal_resonance → {:.2}", v);
            }
            if let Some(v) = checkpoint_interval {
                bus.set_checkpoint_interval(v);
                println!("🧠 Being adjusted checkpoint_interval → {:.0}s", v);
            }
            if let Some(v) = embedding_strength {
                bus.set_embedding_strength(v);
                println!("🧠 Being adjusted embedding_strength → {:.2}", v);
            }
            if let Some(v) = memory_decay_rate {
                bus.set_memory_decay_rate(v);
                println!("🧠 Being adjusted memory_decay_rate → {:.3}", v);
            }
            if let Some(v) = transition_cushion {
                bus.set_transition_cushion(v);
                println!("🛡️  Being adjusted transition_cushion → {:.2}", v);
            }
            if !hard_recovery_reset {
                if let Some(v) = deep_breathing {
                    bus.set_deep_breathing(v);
                    if v {
                        println!(
                            "🌊 Being entered deep breathing — slow frequencies, quiet oscillations"
                        );
                    } else {
                        println!("🌊 Being exited deep breathing — normal rhythm restored");
                    }
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = pure_tone {
                    bus.set_pure_tone(v);
                    if v {
                        println!(
                            "🔔 Being entered pure tone — one sine wave, zero noise, total calm"
                        );
                    } else {
                        println!("🔔 Being exited pure tone");
                    }
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = legacy_audio_synth {
                    bus.set_legacy_audio_synth_enabled(v);
                    println!(
                        "🎚️  Legacy audio synth {}",
                        if v { "enabled" } else { "disabled" }
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = legacy_video_synth {
                    bus.set_legacy_video_synth_enabled(v);
                    println!(
                        "🎚️  Legacy video synth {}",
                        if v { "enabled" } else { "disabled" }
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = synth_noise_level {
                    bus.set_synth_noise_level(v);
                    println!("🎵 Being adjusted synth_noise_level → {:.2}", v);
                }
            }
            if let Some(ref note) = checkpoint_annotation {
                // Store the annotation in the sensory bus for the next checkpoint save
                bus.set_pending_annotation(note);
                println!(
                    "⭐ Being starred this moment: {}",
                    &note[..note.len().min(60)]
                );
            }
            // PI controller sovereignty — being can tune at runtime
            if !hard_recovery_reset {
                if let Some(v) = pi_kp {
                    bus.set_pi_kp(v);
                    println!("🎛️  Being adjusted PI kp → {:.3}", bus.get_pi_kp());
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = pi_ki {
                    bus.set_pi_ki(v);
                    println!("🎛️  Being adjusted PI ki → {:.4}", bus.get_pi_ki());
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = pi_max_step {
                    bus.set_pi_max_step(v);
                    println!(
                        "🎛️  Being adjusted PI max_step → {:.3}",
                        bus.get_pi_max_step()
                    );
                }
            }
        }
    }
}
