use astrid_minime_protocol::{
    DeliveryEnvelopeV1, SensoryDeliveryReceiptV1, SensoryDeliveryStatusV1, SensoryMsg,
    SensoryPacketV1, SensoryServerHelloV1,
};
use futures_util::{SinkExt, StreamExt};
use tokio::time::{timeout, Duration};
use tokio_tungstenite::{connect_async, tungstenite::Message};

use super::spawn_sensory_ws_server;
use crate::sensory_bus::SensoryBus;

#[tokio::test(flavor = "multi_thread")]
async fn server_negotiates_and_receipts_twenty_packets_on_same_connection() {
    let probe = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = probe.local_addr().unwrap();
    drop(probe);
    let server = spawn_sensory_ws_server(SensoryBus::new(32, 4, 7), addr).await;

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
