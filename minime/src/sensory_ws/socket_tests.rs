use astrid_minime_protocol::{
    DeliveryEnvelopeV1, SensoryDeliveryReceiptV1, SensoryDeliveryStatusV1, SensoryMsg,
    SensoryPacketV1, SensoryServerHelloV1,
};
use futures_util::{SinkExt, StreamExt};
use tokio::time::{timeout, Duration};
use tokio_tungstenite::{connect_async, tungstenite::Message};

use super::spawn_sensory_ws_server_with_runtime;
use crate::{
    self_control_cli::{issue, provision, SelfControlIssueOptions},
    self_control_runtime::SelfControlRuntime,
    self_control_wire::{
        SelfControlDurabilityV2, SelfControlFamilyV2, SelfControlReceiptStatusV2,
        SelfControlValuesV2,
    },
    sensory_bus::SensoryBus,
};

#[tokio::test(flavor = "multi_thread")]
async fn server_negotiates_and_receipts_twenty_packets_on_same_connection() {
    let probe = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = probe.local_addr().unwrap();
    drop(probe);
    let bus = SensoryBus::new(32, 4, 7);
    let runtime = SelfControlRuntime::disabled(
        "test-process".to_string(),
        "test-deployment".to_string(),
        bus.clone(),
        "socket_test_runtime_disabled".to_string(),
    );
    let server =
        spawn_sensory_ws_server_with_runtime(bus, addr, Some(std::sync::Arc::new(runtime))).await;

    let mut client = None;
    for _ in 0..20 {
        match connect_async(format!("ws://{addr}")).await {
            Ok((socket, _)) => {
                client = Some(socket);
                break;
            }
            Err(_) => tokio::time::sleep(Duration::from_millis(10)).await,
        }
    }
    let mut client = client.expect("sensory server accepts websocket");
    let hello_text = timeout(Duration::from_secs(2), async {
        loop {
            if let Some(Ok(Message::Text(text))) = client.next().await {
                break text;
            }
        }
    })
    .await
    .expect("server hello timeout");
    let hello: SensoryServerHelloV1 = serde_json::from_str(&hello_text).unwrap();
    assert!(hello.supports_receipts());
    assert!(!hello.spectral_causation_established);

    for index in 0..20 {
        let message = SensoryMsg::Semantic {
            features: vec![index as f32 / 100.0; 48],
            ts_ms: Some(42 + index),
        };
        let delivery_id = format!("delivery-socket-{index}");
        let delivery = DeliveryEnvelopeV1::new(
            delivery_id.clone(),
            &message,
            10 + index,
            "pid:9".to_string(),
            "source:def".to_string(),
        );
        let expected_hash = delivery.payload_sha256.clone();
        let raw = serde_json::to_string(&SensoryPacketV1::with_envelopes(message, delivery, None))
            .unwrap();
        client.send(Message::Text(raw)).await.unwrap();

        let receipt_text = timeout(Duration::from_secs(2), async {
            loop {
                match client.next().await {
                    Some(Ok(Message::Text(text))) => break text,
                    Some(Ok(Message::Ping(payload))) => {
                        client.send(Message::Pong(payload)).await.unwrap();
                    }
                    Some(Ok(_)) => {}
                    Some(Err(error)) => panic!("websocket receive failed: {error}"),
                    None => panic!("websocket closed before receipt"),
                }
            }
        })
        .await
        .expect("delivery receipt timeout");
        let receipt: SensoryDeliveryReceiptV1 = serde_json::from_str(&receipt_text).unwrap();
        assert_eq!(receipt.delivery_id, delivery_id);
        assert_eq!(receipt.payload_sha256, expected_hash);
        assert_eq!(receipt.status, SensoryDeliveryStatusV1::Accepted);
        assert!(!receipt.spectral_causation_established);
    }

    server.abort();
}

#[tokio::test(flavor = "multi_thread")]
async fn provisioned_owner_issues_a_live_receipted_lease_over_the_gateway() {
    let probe = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = probe.local_addr().unwrap();
    drop(probe);
    let root = tempfile::tempdir().unwrap();
    provision(Some(root.path()), false, false).unwrap();
    let bus = SensoryBus::new(32, 4, 7);
    let previous_regulation_strength = bus.get_regulation_strength();
    let runtime = SelfControlRuntime::open_with_safety_probe(
        root.path().to_path_buf(),
        "test-process".to_string(),
        "test-deployment".to_string(),
        bus.clone(),
        1,
        || false,
    )
    .unwrap();
    let server =
        spawn_sensory_ws_server_with_runtime(bus.clone(), addr, Some(std::sync::Arc::new(runtime)))
            .await;

    let mut options = SelfControlIssueOptions::set(
        SelfControlFamilyV2::ReservoirRegulation,
        SelfControlDurabilityV2::Lease,
        SelfControlValuesV2 {
            regulation_strength: Some(0.63),
            ..SelfControlValuesV2::default()
        },
    );
    options.root = Some(root.path().to_path_buf());
    options.sensory_url = format!("ws://{addr}");
    options.lease_secs = 1;
    let mut result = None;
    for _ in 0..20 {
        match issue(options.clone()).await {
            Ok(value) => {
                result = Some(value);
                break;
            }
            Err(error) if error.contains("connect self-control sensory socket") => {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            Err(error) => panic!("self-control issue failed: {error}"),
        }
    }
    let result = result.expect("sensory server accepts owner command");
    let receipt: crate::self_control_wire::SelfControlReceiptV2 = serde_json::from_value(
        result["attempts"]
            .as_array()
            .and_then(|attempts| attempts.last())
            .and_then(|attempt| attempt.get("self_control_receipt"))
            .cloned()
            .expect("typed receipt"),
    )
    .unwrap();
    assert_eq!(
        receipt.status,
        SelfControlReceiptStatusV2::Applied,
        "live owner lease rejected: {:?}",
        receipt.reason
    );
    assert_eq!(receipt.server_deployment_identity, "test-deployment");
    assert_eq!(bus.get_regulation_strength(), 0.63);
    assert!(!receipt.felt_effect_established);
    tokio::time::sleep(Duration::from_millis(1_500)).await;
    assert_eq!(
        bus.get_regulation_strength(),
        previous_regulation_strength,
        "server-owned lease clock must roll back without a connected client"
    );

    server.abort();
}
