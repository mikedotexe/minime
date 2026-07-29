// src/sensory_ws.rs
use astrid_minime_protocol::SensoryDeliveryStatusV1;
pub use astrid_minime_protocol::SensoryMsg;
use futures_util::{SinkExt, StreamExt};
use parking_lot::Mutex;
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{net::TcpListener, select, sync::broadcast, time};
use tokio_tungstenite::{accept_async, tungstenite::protocol::Message};

use crate::{
    self_control_runtime::SelfControlRuntime,
    self_control_wire::{SelfControlReceiptStatusV2, SelfControlReceiptV2},
    sensory_bus::{
        AttractorPulseRequest, LaneIngressOutcome, NowMs, SensoryBus, ShadowInfluenceRequest,
        LLAVA_DIM,
    },
    sensory_protocol::{
        prepare_sensory_packet, DeliveryDedupCache, InboundSensoryMessage, PreparedSensoryPacket,
        SensoryServerIdentity,
    },
};

#[cfg(test)]
fn decode_sensory_packet(raw: &str) -> Result<SensoryMsg, String> {
    let packet: astrid_minime_protocol::SensoryPacketV1 =
        serde_json::from_str(raw).map_err(|error| format!("invalid sensory packet: {error}"))?;
    let status = packet.compatibility();
    if status.is_compatible() {
        Ok(packet.message)
    } else {
        Err(format!("unsupported sensory protocol: {status:?}"))
    }
}

#[cfg(test)]
mod tests {
    use astrid_minime_protocol::{
        DeliveryEnvelopeV1, SensoryDeliveryReceiptV1, SensoryDeliveryStatusV1, SensoryPacketV1,
    };
    use parking_lot::Mutex;

    use super::{decode_sensory_packet, process_sensory_packet, SensoryMsg};
    use crate::{
        self_control_runtime::SelfControlRuntime,
        self_control_wire::canonical_json_value_sha256,
        semantic_body_v2::{
            SemanticBodyFidelityV2, SemanticBodyProvenanceV2, SemanticBodyV2, SemanticLaneRoleV2,
            SEMANTIC_BODY_SCHEMA_V2,
        },
        sensory_bus::SensoryBus,
        sensory_protocol::{DeliveryDedupCache, SensoryServerIdentity},
    };

    fn disabled_runtime(
        bus: std::sync::Arc<SensoryBus>,
        identity: &SensoryServerIdentity,
    ) -> SelfControlRuntime {
        SelfControlRuntime::disabled(
            identity.process_identity.clone(),
            identity.deployment_identity.clone(),
            bus,
            "test_runtime_disabled".to_string(),
        )
    }

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

    #[test]
    fn routed_delivery_is_receipted_once_and_duplicate_is_not_rerouted() {
        let bus = SensoryBus::new(8, 2, 7);
        let dedup = Mutex::new(DeliveryDedupCache::default());
        let identity = SensoryServerIdentity {
            process_identity: "pid:10".to_string(),
            deployment_identity: "source:abc".to_string(),
        };
        let message = SensoryMsg::Semantic {
            features: vec![0.1; 48],
            ts_ms: Some(42),
        };
        let delivery = DeliveryEnvelopeV1::new(
            "delivery-test".to_string(),
            &message,
            10,
            "pid:9".to_string(),
            "source:def".to_string(),
        );
        let raw = serde_json::to_string(&SensoryPacketV1::with_envelopes(message, delivery, None))
            .unwrap();
        let runtime = disabled_runtime(bus.clone(), &identity);

        let first: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(&bus, &dedup, &identity, &runtime, &raw)
                .unwrap()
                .first()
                .expect("first receipt"),
        )
        .unwrap();
        assert_eq!(first.status, SensoryDeliveryStatusV1::Accepted);

        let duplicate: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(&bus, &dedup, &identity, &runtime, &raw)
                .unwrap()
                .first()
                .expect("duplicate receipt"),
        )
        .unwrap();
        assert_eq!(duplicate.status, SensoryDeliveryStatusV1::Duplicate);
    }

    #[test]
    fn semantic_dimension_normalization_is_explicitly_partial() {
        let bus = SensoryBus::new(8, 2, 7);
        let dedup = Mutex::new(DeliveryDedupCache::default());
        let identity = SensoryServerIdentity {
            process_identity: "pid:10".to_string(),
            deployment_identity: "source:abc".to_string(),
        };
        let message = SensoryMsg::Semantic {
            features: vec![0.1; 12],
            ts_ms: Some(42),
        };
        let delivery = DeliveryEnvelopeV1::new(
            "delivery-partial".to_string(),
            &message,
            10,
            "pid:9".to_string(),
            "source:def".to_string(),
        );
        let raw = serde_json::to_string(&SensoryPacketV1::with_envelopes(message, delivery, None))
            .unwrap();
        let runtime = disabled_runtime(bus.clone(), &identity);

        let receipt: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(&bus, &dedup, &identity, &runtime, &raw)
                .unwrap()
                .first()
                .expect("partial receipt"),
        )
        .unwrap();
        assert_eq!(receipt.status, SensoryDeliveryStatusV1::PartiallyApplied);
        assert_eq!(receipt.reason.as_deref(), Some("dimension_normalized"));
    }

    fn semantic_body(companion_mix: f32) -> SemanticBodyV2 {
        SemanticBodyV2 {
            schema: SEMANTIC_BODY_SCHEMA_V2.to_string(),
            body_id: "semantic-body-test".to_string(),
            base_features_48: (0..48).map(|index| index as f32 / 100.0).collect(),
            companion_features_12: vec![0.0; 12],
            lane_role: SemanticLaneRoleV2::LegacyCompatible,
            projection_basis_sha256: "a".repeat(64),
            provenance: SemanticBodyProvenanceV2 {
                source: "gateway-test".to_string(),
                source_sha256: "b".repeat(64),
                producer_process_identity: "test-producer".to_string(),
                producer_deployment_identity: "test-deployment".to_string(),
                introspection_id: None,
            },
            timestamp_unix_ms: 42,
            fidelity: SemanticBodyFidelityV2 {
                codec: "semantic-body-zero-mix".to_string(),
                companion_mix,
                base_transport_exact: true,
                reconstruction_error: Some(0.0),
                fidelity_note: None,
            },
        }
    }

    fn semantic_body_packet(delivery_id: &str, body: &SemanticBodyV2) -> String {
        let payload: serde_json::Value = serde_json::from_slice(
            &serde_json::to_vec(&serde_json::json!({
                "kind": "semantic_body",
                "body": body
            }))
            .unwrap(),
        )
        .unwrap();
        let payload_sha256 = canonical_json_value_sha256(&payload);
        let mut packet = payload;
        let packet_fields = packet.as_object_mut().unwrap();
        packet_fields.insert(
            "protocol".to_string(),
            serde_json::json!({"name": "astrid_minime", "major": 1, "minor": 3}),
        );
        packet_fields.insert(
            "delivery_v1".to_string(),
            serde_json::json!({
                "schema_version": 1,
                "delivery_id": delivery_id,
                "payload_sha256": payload_sha256,
                "sent_at_unix_ms": 42,
                "sender_process_identity": "test-producer",
                "sender_deployment_identity": "test-deployment",
            }),
        );
        let raw = packet.to_string();
        let mut reparsed: serde_json::Value = serde_json::from_str(&raw).unwrap();
        let reparsed_fields = reparsed.as_object_mut().unwrap();
        reparsed_fields.remove("protocol");
        reparsed_fields.remove("delivery_v1");
        reparsed_fields.remove("mutual_address_v1");
        assert_eq!(
            canonical_json_value_sha256(&reparsed),
            payload_sha256,
            "test packet helper must hash exact transmitted extension bytes"
        );
        raw
    }

    #[test]
    fn semantic_body_transport_is_exact_and_sender_mix_cannot_author_effect() {
        let bus = SensoryBus::new(8, 2, 7);
        let dedup = Mutex::new(DeliveryDedupCache::default());
        let identity = SensoryServerIdentity {
            process_identity: "pid:10".to_string(),
            deployment_identity: "source:abc".to_string(),
        };
        let runtime = disabled_runtime(bus.clone(), &identity);
        let body = semantic_body(0.0);
        let exact: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(
                &bus,
                &dedup,
                &identity,
                &runtime,
                &semantic_body_packet("semantic-exact", &body),
            )
            .unwrap()
            .first()
            .expect("exact receipt"),
        )
        .unwrap();
        assert_eq!(
            exact.status,
            SensoryDeliveryStatusV1::Accepted,
            "zero-mix SemanticBody rejected: {:?}",
            exact.reason
        );
        assert_eq!(
            bus.llava_embedding_snapshot().as_slice(),
            body.base_features_48.as_slice()
        );

        let mut nonzero = semantic_body(0.1);
        nonzero.companion_features_12.fill(0.5);
        let accepted: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(
                &bus,
                &dedup,
                &identity,
                &runtime,
                &semantic_body_packet("semantic-nonzero", &nonzero),
            )
            .unwrap()
            .first()
            .expect("nonzero receipt"),
        )
        .unwrap();
        assert_eq!(accepted.status, SensoryDeliveryStatusV1::Accepted);
        let reservoir = bus
            .reservoir_input_v2(
                &[0.0; crate::semantic_body_v2::LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1],
                true,
            )
            .expect("reservoir input");
        assert_eq!(
            reservoir[crate::semantic_body_v2::LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1..],
            [0.0; crate::semantic_body_v2::SEMANTIC_BODY_COMPANION_DIMENSIONS_V2],
            "producer-declared mix is metadata; only owner self-control may author effect"
        );

        let mut malformed = semantic_body(0.0);
        malformed.base_features_48.pop();
        let rejected: SensoryDeliveryReceiptV1 = serde_json::from_str(
            process_sensory_packet(
                &bus,
                &dedup,
                &identity,
                &runtime,
                &semantic_body_packet("semantic-malformed", &malformed),
            )
            .unwrap()
            .first()
            .expect("malformed receipt"),
        )
        .unwrap();
        assert_eq!(rejected.status, SensoryDeliveryStatusV1::Rejected);

        let mut non_finite = semantic_body(0.0);
        non_finite.base_features_48[0] = f32::INFINITY;
        assert!(!non_finite.is_well_formed());
    }
}

#[cfg(test)]
#[path = "sensory_ws/socket_tests.rs"]
mod socket_tests;

pub async fn spawn_sensory_ws_server(
    bus: Arc<SensoryBus>,
    addr: SocketAddr,
) -> tokio::task::JoinHandle<()> {
    spawn_sensory_ws_server_with_runtime(bus, addr, None).await
}

async fn spawn_sensory_ws_server_with_runtime(
    bus: Arc<SensoryBus>,
    addr: SocketAddr,
    runtime_override: Option<Arc<SelfControlRuntime>>,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let listener = TcpListener::bind(addr)
            .await
            .expect("bind ws sensory server");
        println!("🎥 Sensory input server listening on ws://{}", addr);
        let process_started_at_ms = NowMs::now();
        let initial_identity = SensoryServerIdentity::current(process_started_at_ms);
        let dedup = Arc::new(Mutex::new(DeliveryDedupCache::default()));
        let runtime = runtime_override.unwrap_or_else(|| {
            Arc::new(
                SelfControlRuntime::open_default(
                    initial_identity.process_identity.clone(),
                    initial_identity.deployment_identity.clone(),
                    bus.clone(),
                    process_started_at_ms,
                )
                .unwrap_or_else(|reason| {
                    eprintln!("Self-control V2 unavailable: {reason}");
                    SelfControlRuntime::disabled(
                        initial_identity.process_identity.clone(),
                        initial_identity.deployment_identity.clone(),
                        bus.clone(),
                        reason,
                    )
                }),
            )
        });
        let identity = SensoryServerIdentity {
            process_identity: runtime.process_identity().to_string(),
            deployment_identity: runtime.deployment_identity().to_string(),
        };
        let (self_control_receipts, _) = broadcast::channel::<String>(256);
        {
            let runtime = runtime.clone();
            let self_control_receipts = self_control_receipts.clone();
            tokio::spawn(async move {
                let mut sweep = time::interval(Duration::from_millis(250));
                loop {
                    sweep.tick().await;
                    for receipt in runtime.sweep_expired(NowMs::now()) {
                        match serialize_receipt(&receipt) {
                            Ok(serialized) => {
                                let _ = self_control_receipts.send(serialized);
                            }
                            Err(error) => {
                                eprintln!(
                                    "Self-control expiry receipt serialization failed: {error}"
                                );
                            }
                        }
                    }
                }
            });
        }

        loop {
            let (stream, peer) = match listener.accept().await {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("WS accept error: {e}");
                    continue;
                }
            };
            let bus = bus.clone();
            let identity = identity.clone();
            let dedup = dedup.clone();
            let runtime = runtime.clone();
            let mut self_control_receipts = self_control_receipts.subscribe();

            tokio::spawn(async move {
                match accept_async(stream).await {
                    Ok(mut ws) => {
                        println!("🔗 Sensory client connected: {}", peer);
                        let mut ping_int = time::interval(Duration::from_secs(10));
                        let hello = serde_json::to_string(&identity.hello_v1_3(runtime.is_ready()))
                            .expect("sensory server hello serializes");
                        if let Err(error) = ws.send(Message::Text(hello)).await {
                            eprintln!("Sensory hello send failed: {error}");
                            return;
                        }

                        loop {
                            select! {
                                // periodic server ping (keeps NATs happy and gives client a chance to reply)
                                _ = ping_int.tick() => {
                                    if let Err(e) = ws.send(Message::Ping(Vec::new())).await {
                                        eprintln!("WS send ping failed: {e}");
                                        break;
                                    }
                                }
                                receipt = self_control_receipts.recv() => {
                                    match receipt {
                                        Ok(receipt) => {
                                            if let Err(error) = ws.send(Message::Text(receipt)).await {
                                                eprintln!("Self-control expiry receipt send failed: {error}");
                                                break;
                                            }
                                        }
                                        Err(broadcast::error::RecvError::Lagged(skipped)) => {
                                            eprintln!("Self-control receipt client lagged by {skipped} messages");
                                        }
                                        Err(broadcast::error::RecvError::Closed) => break,
                                    }
                                }
                                // incoming frames
                                msg = ws.next() => {
                                    let Some(msg) = msg else { break };
                                    match msg {
                                        Ok(Message::Text(s)) => {
                                            match process_sensory_packet(&bus, &dedup, &identity, &runtime, &s) {
                                                Ok(receipts) => for receipt in receipts {
                                                    if let Err(error) = ws.send(Message::Text(receipt)).await {
                                                        eprintln!("Sensory receipt send failed: {error}");
                                                        break;
                                                    }
                                                },
                                                Err(error) => eprintln!("Sensory packet rejected: {error}"),
                                            }
                                        }
                                        Ok(Message::Binary(b)) => {
                                            if let Ok(s) = std::str::from_utf8(&b) {
                                                match process_sensory_packet(&bus, &dedup, &identity, &runtime, s) {
                                                    Ok(receipts) => for receipt in receipts {
                                                        if let Err(error) = ws.send(Message::Text(receipt)).await {
                                                            eprintln!("Sensory receipt send failed: {error}");
                                                            break;
                                                        }
                                                    },
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

fn process_sensory_packet(
    bus: &SensoryBus,
    dedup: &Mutex<DeliveryDedupCache>,
    identity: &SensoryServerIdentity,
    runtime: &SelfControlRuntime,
    raw: &str,
) -> Result<Vec<String>, String> {
    let now_ms = NowMs::now();
    let prepared = prepare_sensory_packet(raw, &mut dedup.lock(), identity, now_ms)?;
    let mut replies = Vec::new();
    match prepared {
        PreparedSensoryPacket::Route { message, receipt } => {
            let dispatch = route_inbound(bus, runtime, *message, now_ms)?;
            if let Some(receipt) = receipt {
                replies.push(serialize_receipt(&receipt.finish(
                    dispatch.outcome.status,
                    dispatch.outcome.reason.map(str::to_string),
                    Some(NowMs::now()),
                ))?);
            }
            replies.extend(dispatch.additional_receipts);
        }
        PreparedSensoryPacket::Reply(receipt) => {
            replies.push(serialize_receipt(&receipt)?);
        }
    }
    Ok(replies)
}

fn serialize_receipt<T: serde::Serialize>(receipt: &T) -> Result<String, String> {
    serde_json::to_string(receipt)
        .map_err(|error| format!("sensory receipt serialization failed: {error}"))
}

struct InboundDispatch {
    outcome: RouteOutcome,
    additional_receipts: Vec<String>,
}

fn route_inbound(
    bus: &SensoryBus,
    runtime: &SelfControlRuntime,
    message: InboundSensoryMessage,
    now_ms: u64,
) -> Result<InboundDispatch, String> {
    match message {
        InboundSensoryMessage::Legacy(message) => Ok(InboundDispatch {
            outcome: route_msg(
                bus,
                *message,
                runtime.semantic_controls().effective_base_gain(),
            ),
            additional_receipts: Vec::new(),
        }),
        InboundSensoryMessage::SemanticBody(body) => Ok(InboundDispatch {
            outcome: route_semantic_body(bus, runtime, &body),
            additional_receipts: Vec::new(),
        }),
        InboundSensoryMessage::SelfControl(command) => {
            let receipt = runtime.process(&command, now_ms);
            let outcome = self_control_route_outcome(&receipt);
            Ok(InboundDispatch {
                outcome,
                additional_receipts: vec![serialize_receipt(&receipt)?],
            })
        }
    }
}

fn route_semantic_body(
    bus: &SensoryBus,
    runtime: &SelfControlRuntime,
    body: &crate::semantic_body_v2::SemanticBodyV2,
) -> RouteOutcome {
    if !body.is_well_formed() {
        return RouteOutcome::rejected("malformed_semantic_body_v2");
    }
    if !body.fidelity.base_transport_exact {
        return RouteOutcome::policy_blocked("semantic_body_base_transport_not_exact");
    }
    let controls = runtime.semantic_controls();
    let gain = controls.effective_base_gain();
    let outcome = if gain == 1.0 {
        bus.set_semantic_body(&body.base_features_48, &body.companion_features_12)
    } else {
        let scaled_base = body
            .base_features_48
            .iter()
            .map(|value| value * gain)
            .collect::<Vec<_>>();
        let scaled_companion = body
            .companion_features_12
            .iter()
            .map(|value| value * gain)
            .collect::<Vec<_>>();
        bus.set_semantic_body(&scaled_base, &scaled_companion)
    };
    bus.set_semantic_companion_mix(controls.companion_mix);
    lane_route_outcome(outcome)
}

fn self_control_route_outcome(receipt: &SelfControlReceiptV2) -> RouteOutcome {
    match receipt.status {
        SelfControlReceiptStatusV2::Applied
        | SelfControlReceiptStatusV2::Withdrawn
        | SelfControlReceiptStatusV2::SafetyHeld
        | SelfControlReceiptStatusV2::RolledBack => RouteOutcome::ACCEPTED,
        SelfControlReceiptStatusV2::Duplicate => RouteOutcome {
            status: SensoryDeliveryStatusV1::Duplicate,
            reason: Some("self_control_idempotent_replay"),
        },
        SelfControlReceiptStatusV2::RevisionConflict => {
            RouteOutcome::rejected("self_control_revision_conflict")
        }
        SelfControlReceiptStatusV2::Expired => RouteOutcome::rejected("self_control_expired"),
        SelfControlReceiptStatusV2::Rejected => {
            RouteOutcome::policy_blocked("self_control_rejected")
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct RouteOutcome {
    status: SensoryDeliveryStatusV1,
    reason: Option<&'static str>,
}

impl RouteOutcome {
    const ACCEPTED: Self = Self {
        status: SensoryDeliveryStatusV1::Accepted,
        reason: None,
    };
    const PARTIAL_DIMENSION: Self = Self {
        status: SensoryDeliveryStatusV1::PartiallyApplied,
        reason: Some("dimension_normalized"),
    };

    const fn rejected(reason: &'static str) -> Self {
        Self {
            status: SensoryDeliveryStatusV1::Rejected,
            reason: Some(reason),
        }
    }

    const fn policy_blocked(reason: &'static str) -> Self {
        Self {
            status: SensoryDeliveryStatusV1::PolicyBlocked,
            reason: Some(reason),
        }
    }

    const fn partially_applied(reason: &'static str) -> Self {
        Self {
            status: SensoryDeliveryStatusV1::PartiallyApplied,
            reason: Some(reason),
        }
    }
}

fn lane_route_outcome(outcome: LaneIngressOutcome) -> RouteOutcome {
    match outcome {
        LaneIngressOutcome::Accepted => RouteOutcome::ACCEPTED,
        LaneIngressOutcome::InvalidShape => RouteOutcome::rejected("invalid_lane_dimensions"),
        LaneIngressOutcome::PolicyBlocked => RouteOutcome::policy_blocked("sensory_admission_gate"),
    }
}

fn route_msg(bus: &SensoryBus, m: SensoryMsg, semantic_base_gain: f32) -> RouteOutcome {
    match m {
        SensoryMsg::Division { command } => {
            if crate::division::division_rehearsal_enabled() {
                lane_route_outcome(bus.queue_division_command(command))
            } else {
                let _ = command;
                lane_route_outcome(LaneIngressOutcome::PolicyBlocked)
            }
        }
        SensoryMsg::Video { features, ts_ms } => lane_route_outcome(
            bus.push_video_with_receipt(features, ts_ms.unwrap_or_else(NowMs::now)),
        ),
        SensoryMsg::Audio { features, ts_ms } => lane_route_outcome(
            bus.push_audio_with_receipt(features, ts_ms.unwrap_or_else(NowMs::now)),
        ),
        SensoryMsg::Aux { features, ts_ms: _ } => {
            // Allows external aux but normally aux is fed internally
            if features.len() >= 2 {
                bus.set_aux([features[0], features[1]]);
                if features.len() == 2 {
                    RouteOutcome::ACCEPTED
                } else {
                    RouteOutcome::PARTIAL_DIMENSION
                }
            } else {
                RouteOutcome::rejected("invalid_lane_dimensions")
            }
        }
        SensoryMsg::Semantic { features, ts_ms: _ } => {
            let exact_dimensions = features.len() == LLAVA_DIM;
            if semantic_base_gain == 1.0 {
                bus.set_llava_embedding(&features);
            } else {
                let scaled = features
                    .iter()
                    .map(|value| value * semantic_base_gain)
                    .collect::<Vec<_>>();
                bus.set_llava_embedding(&scaled);
            }
            if exact_dimensions {
                RouteOutcome::ACCEPTED
            } else {
                RouteOutcome::PARTIAL_DIMENSION
            }
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
            if status.last_block_reason.is_some() {
                RouteOutcome::policy_blocked("attractor_pulse_policy")
            } else {
                RouteOutcome::ACCEPTED
            }
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
            if status.last_block_reason.is_some() {
                RouteOutcome::policy_blocked("shadow_influence_policy")
            } else {
                RouteOutcome::ACCEPTED
            }
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
            let other_homeostatic_controls_present = synth_gain.is_some()
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
                || pi_integrator_leak.is_some();
            let always_applied_controls_present = mem_mode.is_some()
                || journal_resonance.is_some()
                || checkpoint_interval.is_some()
                || embedding_strength.is_some()
                || memory_decay_rate.is_some()
                || transition_cushion.is_some()
                || checkpoint_annotation.is_some()
                || live_audio_enabled.is_some()
                || live_video_enabled.is_some();
            let mut receipt_outcome = if hard_recovery_reset
                && (homeostatic_controls_present || mode_disperse.is_some())
            {
                if always_applied_controls_present {
                    RouteOutcome::partially_applied("hard_recovery_reset_partial")
                } else {
                    RouteOutcome::policy_blocked("hard_recovery_reset")
                }
            } else {
                RouteOutcome::ACCEPTED
            };
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
                        return if other_homeostatic_controls_present
                            || always_applied_controls_present
                        {
                            RouteOutcome::partially_applied("esn_leak_override_missing_authority")
                        } else {
                            RouteOutcome::rejected("esn_leak_override_missing_authority")
                        };
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
                    if status.last_block_reason.is_some() {
                        receipt_outcome = if other_homeostatic_controls_present
                            || always_applied_controls_present
                        {
                            RouteOutcome::partially_applied("mode_disperse_policy")
                        } else {
                            RouteOutcome::policy_blocked("mode_disperse_policy")
                        };
                    }
                }
            }
            receipt_outcome
        }
    }
}
