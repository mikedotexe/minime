// src/sensory_ws.rs
pub use astrid_minime_protocol::SensoryMsg;
use astrid_minime_protocol::{CompatibilityStatus, SensoryPacketV1};
use futures_util::{SinkExt, StreamExt};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{net::TcpListener, select, time};
use tokio_tungstenite::{accept_async, tungstenite::protocol::Message};

use crate::sensory_bus::{AttractorPulseRequest, NowMs, SensoryBus, ShadowInfluenceRequest};

fn decode_sensory_packet(raw: &str) -> Result<SensoryMsg, String> {
    let packet: SensoryPacketV1 =
        serde_json::from_str(raw).map_err(|error| format!("invalid sensory packet: {error}"))?;
    match packet.compatibility() {
        CompatibilityStatus::Current
        | CompatibilityStatus::CompatibleMinor
        | CompatibilityStatus::LegacyUnversioned => Ok(packet.message),
        status => Err(format!("unsupported sensory protocol: {status:?}")),
    }
}

#[cfg(test)]
mod tests {
    use super::{decode_sensory_packet, SensoryMsg};

    #[test]
    fn attractor_pulse_message_deserializes_from_snake_case_kind() {
        let msg: SensoryMsg = serde_json::from_str(
            r#"{
                "kind":"attractor_pulse",
                "intent_id":"intent-main",
                "label":"cooled edge",
                "command":"summon",
                "stage":"main",
                "features":[0.01, -0.02],
                "max_abs":0.045,
                "duration_ticks":36,
                "decay_ticks":12
            }"#,
        )
        .expect("deserialize attractor pulse");

        match msg {
            SensoryMsg::AttractorPulse {
                intent_id,
                label,
                command,
                stage,
                features,
                max_abs,
                duration_ticks,
                decay_ticks,
            } => {
                assert_eq!(intent_id, "intent-main");
                assert_eq!(label, "cooled edge");
                assert_eq!(command, "summon");
                assert_eq!(stage.as_deref(), Some("main"));
                assert_eq!(features.len(), 2);
                assert_eq!(max_abs, Some(0.045));
                assert_eq!(duration_ticks, Some(36));
                assert_eq!(decay_ticks, Some(12));
            }
            _ => panic!("expected attractor pulse"),
        }
    }

    #[test]
    fn shadow_influence_message_deserializes_from_snake_case_kind() {
        let msg: SensoryMsg = serde_json::from_str(
            r#"{
                "kind":"shadow_influence",
                "intent_id":"shadow-live",
                "label":"lambda-tail/lambda4",
                "command":"apply",
                "stage":"live",
                "features":[0.01, -0.02],
                "max_abs":0.025,
                "duration_ticks":24,
                "decay_ticks":12,
                "basis":"lambda-tail/lambda4"
            }"#,
        )
        .expect("deserialize shadow influence");

        match msg {
            SensoryMsg::ShadowInfluence {
                intent_id,
                label,
                command,
                stage,
                features,
                max_abs,
                duration_ticks,
                decay_ticks,
                basis,
            } => {
                assert_eq!(intent_id, "shadow-live");
                assert_eq!(label, "lambda-tail/lambda4");
                assert_eq!(command, "apply");
                assert_eq!(stage.as_deref(), Some("live"));
                assert_eq!(features.len(), 2);
                assert_eq!(max_abs, Some(0.025));
                assert_eq!(duration_ticks, Some(24));
                assert_eq!(decay_ticks, Some(12));
                assert_eq!(basis.as_deref(), Some("lambda-tail/lambda4"));
            }
            _ => panic!("expected shadow influence"),
        }
    }

    #[test]
    fn control_message_deserializes_live_sensory_gates() {
        let msg: SensoryMsg = serde_json::from_str(
            r#"{
                "kind":"control",
                "live_audio_enabled":false,
                "live_video_enabled":true
            }"#,
        )
        .expect("deserialize control sensory gates");

        match msg {
            SensoryMsg::Control {
                live_audio_enabled,
                live_video_enabled,
                ..
            } => {
                assert_eq!(live_audio_enabled, Some(false));
                assert_eq!(live_video_enabled, Some(true));
            }
            _ => panic!("expected control"),
        }
    }

    #[test]
    fn control_message_deserializes_mode_disperse_fields() {
        let msg: SensoryMsg = serde_json::from_str(
            r#"{
                "kind":"control",
                "mode_disperse":0.6,
                "mode_disperse_duration_ticks":30,
                "mode_disperse_decay_ticks":12
            }"#,
        )
        .expect("deserialize control mode_disperse");

        match msg {
            SensoryMsg::Control {
                mode_disperse,
                mode_disperse_duration_ticks,
                mode_disperse_decay_ticks,
                ..
            } => {
                assert_eq!(mode_disperse, Some(0.6));
                assert_eq!(mode_disperse_duration_ticks, Some(30));
                assert_eq!(mode_disperse_decay_ticks, Some(12));
            }
            _ => panic!("expected control"),
        }
    }

    #[test]
    fn versioned_sensory_packet_is_accepted() {
        let message = decode_sensory_packet(
            r#"{
                "protocol":{"name":"astrid_minime","major":1,"minor":0},
                "kind":"semantic",
                "features":[0.1, -0.1],
                "ts_ms":42
            }"#,
        )
        .expect("accept current protocol");

        assert!(matches!(
            message,
            SensoryMsg::Semantic {
                ts_ms: Some(42),
                ..
            }
        ));
    }

    #[test]
    fn unsupported_sensory_major_is_rejected_before_dispatch() {
        let error = decode_sensory_packet(
            r#"{
                "protocol":{"name":"astrid_minime","major":2,"minor":0},
                "kind":"semantic",
                "features":[0.1],
                "ts_ms":42
            }"#,
        )
        .expect_err("reject unsupported protocol major");

        assert!(error.contains("UnsupportedMajor"));
    }
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
                                            match decode_sensory_packet(&s) {
                                                Ok(message) => route_msg(&bus, message),
                                                Err(error) => eprintln!("Sensory packet rejected: {error}"),
                                            }
                                        }
                                        Ok(Message::Binary(b)) => {
                                            if let Ok(s) = std::str::from_utf8(&b) {
                                                match decode_sensory_packet(s) {
                                                    Ok(message) => route_msg(&bus, message),
                                                    Err(error) => eprintln!("Sensory packet rejected: {error}"),
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
        SensoryMsg::AttractorPulse {
            intent_id,
            label,
            command,
            stage,
            features,
            max_abs,
            duration_ticks,
            decay_ticks,
        } => {
            let status = bus.receive_attractor_pulse(
                AttractorPulseRequest {
                    intent_id,
                    label,
                    command,
                    stage,
                    features,
                    max_abs,
                    duration_ticks,
                    decay_ticks,
                },
                false,
            );
            println!(
                "🧭 Attractor pulse status: active={} label={} event={} block={}",
                status.active,
                status.label.as_deref().unwrap_or("none"),
                status.last_event.as_deref().unwrap_or("none"),
                status.last_block_reason.as_deref().unwrap_or("none")
            );
        }
        SensoryMsg::ShadowInfluence {
            intent_id,
            label,
            command,
            stage,
            features,
            max_abs,
            duration_ticks,
            decay_ticks,
            basis,
        } => {
            let status = bus.receive_shadow_influence(
                ShadowInfluenceRequest {
                    intent_id,
                    label,
                    command,
                    stage,
                    features,
                    max_abs,
                    duration_ticks,
                    decay_ticks,
                    basis,
                },
                false,
                bus.attractor_pulse_status().active,
            );
            println!(
                "🌘 Shadow influence status: active={} label={} event={} block={}",
                status.active,
                status.label.as_deref().unwrap_or("none"),
                status.last_event.as_deref().unwrap_or("none"),
                status.last_block_reason.as_deref().unwrap_or("none")
            );
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
            live_audio_enabled,
            live_video_enabled,
            pi_kp,
            pi_ki,
            pi_max_step,
            pi_geom_weight,
            pi_integrator_leak,
            esn_leak_override,
            esn_leak_override_ticks,
            esn_leak_authority_request_id,
            mode_disperse,
            mode_disperse_duration_ticks,
            mode_disperse_decay_ticks,
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
                || pi_max_step.is_some()
                || pi_geom_weight.is_some()
                || pi_integrator_leak.is_some()
                || esn_leak_override.is_some();
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
            if let Some(v) = live_audio_enabled {
                bus.set_live_audio_enabled(v);
                println!(
                    "🎚️  Live audio intake {}",
                    if v { "enabled" } else { "gated closed" }
                );
            }
            if let Some(v) = live_video_enabled {
                bus.set_live_video_enabled(v);
                println!(
                    "🎚️  Live video intake {}",
                    if v { "enabled" } else { "gated closed" }
                );
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
            if !hard_recovery_reset {
                if let Some(v) = pi_geom_weight {
                    bus.set_pi_geom_weight(v);
                    println!(
                        "🎛️  Being adjusted PI geom_weight → {:.2} (structure-vs-fill)",
                        bus.get_pi_geom_weight()
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = pi_integrator_leak {
                    bus.set_pi_integrator_leak(v);
                    println!(
                        "🎛️  Being adjusted PI integrator_leak → {:.4} (correction memory)",
                        bus.get_pi_integrator_leak()
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(v) = esn_leak_override {
                    let Some(request_id) = esn_leak_authority_request_id
                        .as_deref()
                        .map(str::trim)
                        .filter(|value| !value.is_empty())
                    else {
                        println!("🛡️  Ignored ESN leak override without authority request id");
                        return;
                    };
                    let ticks = esn_leak_override_ticks.unwrap_or(1).clamp(1, 12);
                    bus.request_esn_leak_override(request_id.to_string(), v, ticks);
                    println!(
                        "🎛️  Queued gated ESN leak override → {:.3} for {} tick(s) request={}",
                        v.clamp(0.20, 0.90),
                        ticks,
                        request_id
                    );
                }
            }
            if !hard_recovery_reset {
                if let Some(strength) = mode_disperse {
                    // Deterministic-per-invocation seed from wall clock; the
                    // synthesizer is reproducible given this seed (logged below).
                    let seed = NowMs::now();
                    let status = bus.receive_mode_disperse(
                        strength,
                        mode_disperse_duration_ticks,
                        mode_disperse_decay_ticks,
                        seed,
                        hard_recovery_reset,
                        bus.attractor_pulse_status().active,
                    );
                    println!(
                        "🌀 Being requested mode_disperse (spread) → strength={:.2} seed={} \
                         event={} block={}",
                        strength.clamp(0.0, 1.0),
                        seed,
                        status.last_event.as_deref().unwrap_or("none"),
                        status.last_block_reason.as_deref().unwrap_or("none"),
                    );
                }
            }
        }
    }
}
