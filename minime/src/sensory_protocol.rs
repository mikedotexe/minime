use std::{
    collections::{HashSet, VecDeque},
    process,
};

use astrid_minime_protocol::{
    DeliveryEnvelopeV1, SensoryDeliveryReceiptV1, SensoryDeliveryStatusV1, SensoryMsg,
    SensoryPacketV1, SensoryServerHelloV1,
};

pub const DELIVERY_DEDUP_CAPACITY: usize = 4_096;
pub const DELIVERY_DEDUP_TTL_MS: u64 = 2 * 60 * 60 * 1_000;

#[derive(Clone, Debug)]
pub struct SensoryServerIdentity {
    pub process_identity: String,
    pub deployment_identity: String,
}

impl SensoryServerIdentity {
    #[must_use]
    pub fn current(process_started_at_ms: u64) -> Self {
        let source_commit = option_env!("MINIME_SOURCE_COMMIT").unwrap_or("unknown");
        let deployment_identity = std::env::var("MINIME_DEPLOYMENT_IDENTITY")
            .unwrap_or_else(|_| format!("minime-source:{source_commit}"));
        Self {
            process_identity: format!(
                "pid:{}:started_at_unix_ms:{process_started_at_ms}",
                process::id()
            ),
            deployment_identity,
        }
    }

    #[must_use]
    pub fn hello(&self) -> SensoryServerHelloV1 {
        SensoryServerHelloV1::new(
            self.process_identity.clone(),
            self.deployment_identity.clone(),
        )
    }
}

#[derive(Clone, Debug)]
struct DedupEntry {
    delivery_id: String,
    observed_at_ms: u64,
}

#[derive(Debug)]
pub struct DeliveryDedupCache {
    entries: VecDeque<DedupEntry>,
    ids: HashSet<String>,
    capacity: usize,
    ttl_ms: u64,
}

impl Default for DeliveryDedupCache {
    fn default() -> Self {
        Self::new(DELIVERY_DEDUP_CAPACITY, DELIVERY_DEDUP_TTL_MS)
    }
}

impl DeliveryDedupCache {
    #[must_use]
    pub fn new(capacity: usize, ttl_ms: u64) -> Self {
        Self {
            entries: VecDeque::new(),
            ids: HashSet::new(),
            capacity: capacity.max(1),
            ttl_ms: ttl_ms.max(1),
        }
    }

    pub fn observe(&mut self, delivery_id: &str, now_ms: u64) -> bool {
        self.prune(now_ms);
        if self.ids.contains(delivery_id) {
            return true;
        }

        let delivery_id = delivery_id.to_string();
        self.ids.insert(delivery_id.clone());
        self.entries.push_back(DedupEntry {
            delivery_id,
            observed_at_ms: now_ms,
        });
        while self.entries.len() > self.capacity {
            if let Some(expired) = self.entries.pop_front() {
                self.ids.remove(&expired.delivery_id);
            }
        }
        false
    }

    fn prune(&mut self, now_ms: u64) {
        while self
            .entries
            .front()
            .is_some_and(|entry| now_ms.saturating_sub(entry.observed_at_ms) >= self.ttl_ms)
        {
            if let Some(expired) = self.entries.pop_front() {
                self.ids.remove(&expired.delivery_id);
            }
        }
    }
}

#[derive(Debug)]
pub struct ReceiptContext {
    delivery: DeliveryEnvelopeV1,
    mutual_address_id: Option<String>,
    received_at_ms: u64,
    identity: SensoryServerIdentity,
}

impl ReceiptContext {
    #[must_use]
    pub fn finish(
        self,
        status: SensoryDeliveryStatusV1,
        reason: Option<String>,
        routed_at_ms: Option<u64>,
    ) -> SensoryDeliveryReceiptV1 {
        receipt(
            &self.identity,
            &self.delivery,
            status,
            self.received_at_ms,
            routed_at_ms,
            self.mutual_address_id,
            reason,
        )
    }
}

#[derive(Debug)]
pub enum PreparedSensoryPacket {
    Route {
        message: Box<SensoryMsg>,
        receipt: Option<ReceiptContext>,
    },
    Reply(SensoryDeliveryReceiptV1),
}

pub fn prepare_sensory_packet(
    raw: &str,
    dedup: &mut DeliveryDedupCache,
    identity: &SensoryServerIdentity,
    now_ms: u64,
) -> Result<PreparedSensoryPacket, String> {
    let packet: SensoryPacketV1 =
        serde_json::from_str(raw).map_err(|error| format!("invalid sensory packet: {error}"))?;
    let compatibility = packet.compatibility();
    if !compatibility.is_compatible() {
        return rejected_or_error(
            packet,
            identity,
            now_ms,
            format!("unsupported sensory protocol: {compatibility:?}"),
        );
    }

    let Some(delivery) = packet.delivery_v1 else {
        if packet
            .protocol
            .as_ref()
            .is_some_and(|protocol| protocol.major == 1 && protocol.minor >= 1)
        {
            return Err("protocol 1.1 sensory packet omitted delivery_v1".to_string());
        }
        return Ok(PreparedSensoryPacket::Route {
            message: Box::new(packet.message),
            receipt: None,
        });
    };

    let invalid_sender = delivery.sender_process_identity.trim().is_empty()
        || delivery.sender_deployment_identity.trim().is_empty();
    if invalid_sender || !delivery.payload_matches(&packet.message) {
        return Ok(PreparedSensoryPacket::Reply(receipt(
            identity,
            &delivery,
            SensoryDeliveryStatusV1::Rejected,
            now_ms,
            None,
            packet
                .mutual_address_v1
                .as_ref()
                .map(|address| address.address_id.clone()),
            Some(if invalid_sender {
                "invalid_sender_identity".to_string()
            } else {
                "payload_sha256_mismatch".to_string()
            }),
        )));
    }

    if packet
        .mutual_address_v1
        .as_ref()
        .is_some_and(|address| !address.is_exact_lineage())
    {
        return Ok(PreparedSensoryPacket::Reply(receipt(
            identity,
            &delivery,
            SensoryDeliveryStatusV1::Rejected,
            now_ms,
            None,
            packet
                .mutual_address_v1
                .as_ref()
                .map(|address| address.address_id.clone()),
            Some("invalid_mutual_address_lineage".to_string()),
        )));
    }

    let mutual_address_id = packet.mutual_address_v1.map(|address| address.address_id);
    if dedup.observe(&delivery.delivery_id, now_ms) {
        return Ok(PreparedSensoryPacket::Reply(receipt(
            identity,
            &delivery,
            SensoryDeliveryStatusV1::Duplicate,
            now_ms,
            None,
            mutual_address_id,
            Some("deduplication_window".to_string()),
        )));
    }

    Ok(PreparedSensoryPacket::Route {
        message: Box::new(packet.message),
        receipt: Some(ReceiptContext {
            delivery,
            mutual_address_id,
            received_at_ms: now_ms,
            identity: identity.clone(),
        }),
    })
}

fn rejected_or_error(
    packet: SensoryPacketV1,
    identity: &SensoryServerIdentity,
    now_ms: u64,
    reason: String,
) -> Result<PreparedSensoryPacket, String> {
    let Some(delivery) = packet.delivery_v1 else {
        return Err(reason);
    };
    Ok(PreparedSensoryPacket::Reply(receipt(
        identity,
        &delivery,
        SensoryDeliveryStatusV1::Rejected,
        now_ms,
        None,
        packet.mutual_address_v1.map(|address| address.address_id),
        Some(reason),
    )))
}

#[allow(clippy::too_many_arguments)]
fn receipt(
    identity: &SensoryServerIdentity,
    delivery: &DeliveryEnvelopeV1,
    status: SensoryDeliveryStatusV1,
    received_at_ms: u64,
    routed_at_ms: Option<u64>,
    mutual_address_id: Option<String>,
    reason: Option<String>,
) -> SensoryDeliveryReceiptV1 {
    SensoryDeliveryReceiptV1::new(
        format!("receipt:{}:{received_at_ms}", delivery.delivery_id),
        delivery.delivery_id.clone(),
        delivery.payload_sha256.clone(),
        status,
        received_at_ms,
        routed_at_ms,
        mutual_address_id,
        reason,
        identity.process_identity.clone(),
        identity.deployment_identity.clone(),
    )
}

#[cfg(test)]
mod tests {
    use astrid_minime_protocol::{
        DeliveryEnvelopeV1, SensoryDeliveryStatusV1, SensoryMsg, SensoryPacketV1,
    };

    use super::{
        prepare_sensory_packet, DeliveryDedupCache, PreparedSensoryPacket, SensoryServerIdentity,
    };

    fn identity() -> SensoryServerIdentity {
        SensoryServerIdentity {
            process_identity: "pid:10".to_string(),
            deployment_identity: "source:abc".to_string(),
        }
    }

    fn packet(delivery_id: &str, features: Vec<f32>) -> String {
        let message = SensoryMsg::Semantic {
            features,
            ts_ms: Some(42),
        };
        let delivery = DeliveryEnvelopeV1::new(
            delivery_id.to_string(),
            &message,
            10,
            "pid:9".to_string(),
            "source:def".to_string(),
        );
        serde_json::to_string(&SensoryPacketV1::with_envelopes(message, delivery, None)).unwrap()
    }

    #[test]
    fn deduplication_is_bounded_and_expires() {
        let mut dedup = DeliveryDedupCache::new(2, 100);
        assert!(!dedup.observe("one", 0));
        assert!(dedup.observe("one", 1));
        assert!(!dedup.observe("two", 2));
        assert!(!dedup.observe("three", 3));
        assert!(!dedup.observe("one", 4), "capacity evicts oldest");
        assert!(!dedup.observe("two", 104), "ttl expires retained entry");
    }

    #[test]
    fn duplicate_delivery_gets_receipt_without_route() {
        let raw = packet("delivery-1", vec![0.1; 48]);
        let mut dedup = DeliveryDedupCache::default();
        assert!(matches!(
            prepare_sensory_packet(&raw, &mut dedup, &identity(), 100).unwrap(),
            PreparedSensoryPacket::Route { .. }
        ));
        let PreparedSensoryPacket::Reply(receipt) =
            prepare_sensory_packet(&raw, &mut dedup, &identity(), 101).unwrap()
        else {
            panic!("duplicate must not route");
        };
        assert_eq!(receipt.status, SensoryDeliveryStatusV1::Duplicate);
        assert!(!receipt.spectral_causation_established);
    }

    #[test]
    fn hash_mismatch_is_rejected_without_route() {
        let mut value: serde_json::Value =
            serde_json::from_str(&packet("delivery-2", vec![0.1; 48])).unwrap();
        value["features"][0] = serde_json::json!(0.2);
        let raw = serde_json::to_string(&value).unwrap();
        let PreparedSensoryPacket::Reply(receipt) =
            prepare_sensory_packet(&raw, &mut DeliveryDedupCache::default(), &identity(), 100)
                .unwrap()
        else {
            panic!("tampered packet must not route");
        };
        assert_eq!(receipt.status, SensoryDeliveryStatusV1::Rejected);
        assert_eq!(receipt.reason.as_deref(), Some("payload_sha256_mismatch"));
    }

    #[test]
    fn unversioned_and_v1_0_packets_route_without_receipts() {
        for raw in [
            r#"{"kind":"semantic","features":[0.1],"ts_ms":42}"#,
            r#"{"protocol":{"name":"astrid_minime","major":1,"minor":0},"kind":"semantic","features":[0.1],"ts_ms":42}"#,
        ] {
            assert!(matches!(
                prepare_sensory_packet(raw, &mut DeliveryDedupCache::default(), &identity(), 100)
                    .unwrap(),
                PreparedSensoryPacket::Route { receipt: None, .. }
            ));
        }
    }

    #[test]
    fn v1_1_requires_technical_delivery_identity() {
        let error = prepare_sensory_packet(
            r#"{"protocol":{"name":"astrid_minime","major":1,"minor":1},"kind":"semantic","features":[0.1],"ts_ms":42}"#,
            &mut DeliveryDedupCache::default(),
            &identity(),
            100,
        )
        .unwrap_err();
        assert!(error.contains("omitted delivery_v1"));
    }
}
