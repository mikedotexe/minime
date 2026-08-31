use std::{
    path::{Path, PathBuf},
    process,
    time::{SystemTime, UNIX_EPOCH},
};

use futures_util::{SinkExt as _, StreamExt as _};
use serde_json::{json, Value};
use tokio::time::{timeout, Duration};
use tokio_tungstenite::{connect_async, tungstenite::Message, MaybeTlsStream, WebSocketStream};

use crate::{
    self_control_identity::{
        provision_deployment_steward_identity, provision_minime_owner_identity,
        SelfControlOwnerSigner, SelfControlProvisionReceiptV1,
    },
    self_control_runtime::default_self_control_root,
    self_control_wire::{
        canonical_json_value_sha256, SelfControlActionV2, SelfControlAuthorityClassV2,
        SelfControlDurabilityV2, SelfControlFamilyV2, SelfControlIntentV2,
        SelfControlReceiptStatusV2, SelfControlReceiptV2, SelfControlSourceIdentityV1,
        SelfControlValuesV2, SELF_CONTROL_INTENT_SCHEMA_V2,
    },
};

const COMMAND_TTL_MS: u64 = 30_000;
const DEFAULT_RECEIPT_TIMEOUT_SECS: u64 = 8;

#[derive(Clone, Debug)]
pub struct SelfControlIssueOptions {
    pub root: Option<PathBuf>,
    pub sensory_url: String,
    pub actor_process_identity: Option<String>,
    pub family: SelfControlFamilyV2,
    pub durability: SelfControlDurabilityV2,
    pub action: SelfControlActionV2,
    pub values: SelfControlValuesV2,
    pub lease_secs: u64,
    pub expected_revision: u64,
    pub retry_revision_conflict: bool,
    pub related_intent_id: Option<String>,
    pub related_receipt_id: Option<String>,
    pub evidence_refs: Vec<String>,
    pub success_conditions: Vec<String>,
    pub stop_conditions: Vec<String>,
}

impl SelfControlIssueOptions {
    #[must_use]
    pub fn set(
        family: SelfControlFamilyV2,
        durability: SelfControlDurabilityV2,
        values: SelfControlValuesV2,
    ) -> Self {
        Self {
            root: None,
            sensory_url: "ws://127.0.0.1:7879".to_string(),
            actor_process_identity: None,
            family,
            durability,
            action: SelfControlActionV2::Set,
            values,
            lease_secs: 120,
            expected_revision: 0,
            retry_revision_conflict: true,
            related_intent_id: None,
            related_receipt_id: None,
            evidence_refs: Vec::new(),
            success_conditions: vec!["machine_receipt_matches_requested_revision".to_string()],
            stop_conditions: vec![
                "being_authored_hold".to_string(),
                "safety_red_or_stale_telemetry".to_string(),
                "non_finite_or_receipt_mismatch".to_string(),
            ],
        }
    }
}

#[derive(Clone, Debug)]
struct ServerHelloV1 {
    process_identity: String,
    deployment_identity: String,
}

#[derive(Clone, Debug)]
struct DeliveryResultV1 {
    command: crate::self_control_wire::SelfControlCommandV2,
    delivery_receipt: Value,
    self_control_receipt: SelfControlReceiptV2,
}

pub fn provision(
    root: Option<&Path>,
    rotate: bool,
    deployment_steward: bool,
) -> Result<SelfControlProvisionReceiptV1, String> {
    let root = root.map_or_else(default_self_control_root, Path::to_path_buf);
    if deployment_steward {
        provision_deployment_steward_identity(&root, rotate, now_unix_ms())
    } else {
        provision_minime_owner_identity(&root, rotate, now_unix_ms())
    }
}

/// Prepare a signed deployment hand-off carrying the persisted self-control
/// state to THIS binary's deployment identity (run from the NEW binary,
/// before restarting the engine on it).
pub fn prepare_deployment_handoff(
    root: Option<&Path>,
    operator_actor: &str,
    operator_ack: &str,
) -> Result<Value, String> {
    let root = root.map_or_else(default_self_control_root, Path::to_path_buf);
    crate::self_control_runtime::prepare_deployment_handoff(
        &root,
        operator_actor,
        operator_ack,
        now_unix_ms(),
    )
}

pub fn status(root: Option<&Path>) -> Result<Value, String> {
    let root = root.map_or_else(default_self_control_root, Path::to_path_buf);
    crate::self_control_runtime::SelfControlRuntime::verified_status(&root)
}

pub fn parse_values_json(raw: &str) -> Result<SelfControlValuesV2, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("decode self-control values: {error}"))?;
    let fields = value
        .as_object()
        .ok_or_else(|| "self-control values must be a JSON object".to_string())?;
    let values: SelfControlValuesV2 = serde_json::from_value(value.clone())
        .map_err(|error| format!("decode self-control values: {error}"))?;
    let recognized = values.field_names();
    let unknown = fields
        .iter()
        .filter_map(|(field, value)| {
            (!value.is_null() && !recognized.contains(field)).then_some(field.clone())
        })
        .collect::<Vec<_>>();
    if !unknown.is_empty() {
        return Err(format!(
            "unknown or unsupported self-control value fields: {}",
            unknown.join(",")
        ));
    }
    if !values.is_well_formed() {
        return Err("self-control values contain non-finite or oversized data".to_string());
    }
    Ok(values)
}

pub async fn issue(options: SelfControlIssueOptions) -> Result<Value, String> {
    let root = options
        .root
        .clone()
        .unwrap_or_else(default_self_control_root);
    let signer = SelfControlOwnerSigner::load(&root)?;
    if signer.being() != "minime" {
        return Err("only the Minime owner identity may issue Minime self-control".to_string());
    }

    let (mut socket, _) = connect_async(&options.sensory_url)
        .await
        .map_err(|error| format!("connect self-control sensory socket: {error}"))?;
    let hello = receive_hello(&mut socket).await?;
    let mut expected_revision = options.expected_revision;
    let mut attempts = Vec::new();

    for attempt in 0..2 {
        let command = build_command(&signer, &options, &hello, expected_revision, now_unix_ms())?;
        let result = deliver_command(&mut socket, &signer, &hello, command).await?;
        let retry_revision = result.self_control_receipt.resulting_revision;
        let should_retry = options.retry_revision_conflict
            && attempt == 0
            && result.self_control_receipt.status == SelfControlReceiptStatusV2::RevisionConflict;
        attempts.push(json!({
            "command": result.command,
            "delivery_receipt": result.delivery_receipt,
            "self_control_receipt": result.self_control_receipt,
        }));
        if !should_retry {
            return Ok(json!({
                "schema": "minime.self_control.issue_result.v1",
                "being": signer.being(),
                "key_id": signer.key_id(),
                "server_process_identity": hello.process_identity,
                "server_deployment_identity": hello.deployment_identity,
                "attempts": attempts,
                "felt_effect_established": false,
            }));
        }
        expected_revision = retry_revision;
    }
    Err("self-control revision did not converge after one current-state retry".to_string())
}

fn build_command(
    signer: &SelfControlOwnerSigner,
    options: &SelfControlIssueOptions,
    hello: &ServerHelloV1,
    expected_revision: u64,
    now_unix_ms: u64,
) -> Result<crate::self_control_wire::SelfControlCommandV2, String> {
    let revision = expected_revision
        .checked_add(1)
        .ok_or_else(|| "self-control revision overflow".to_string())?;
    let entropy = fastrand::u64(..);
    let family = family_name(options.family);
    let control_expires_at_unix_ms = match options.durability {
        SelfControlDurabilityV2::Lease => Some(
            now_unix_ms
                .checked_add(options.lease_secs.saturating_mul(1_000))
                .ok_or_else(|| "self-control lease expiry overflow".to_string())?,
        ),
        SelfControlDurabilityV2::Standing | SelfControlDurabilityV2::OneShot => None,
    };
    let command_expires_at_unix_ms = now_unix_ms
        .checked_add(COMMAND_TTL_MS)
        .ok_or_else(|| "self-control command expiry overflow".to_string())?;
    let actor_process_identity = options
        .actor_process_identity
        .clone()
        .unwrap_or_else(|| format!("pid:{}:minime-self-control-owner", process::id()));
    let intent = SelfControlIntentV2 {
        schema: SELF_CONTROL_INTENT_SCHEMA_V2.to_string(),
        intent_id: format!("minime:{family}:{now_unix_ms}:{entropy:016x}"),
        actor: SelfControlSourceIdentityV1 {
            being: signer.being().to_string(),
            process_identity: actor_process_identity,
            deployment_identity: hello.deployment_identity.clone(),
        },
        target_being: "minime".to_string(),
        target_deployment_identity: hello.deployment_identity.clone(),
        family: options.family,
        action: options.action,
        durability: options.durability,
        authority_class: SelfControlAuthorityClassV2::SelfOwned,
        authority_scope: format!("self_control.minime.{family}"),
        revision,
        expected_revision,
        issued_at_unix_ms: now_unix_ms,
        command_expires_at_unix_ms,
        control_expires_at_unix_ms,
        idempotency_key: format!("minime:{family}:{now_unix_ms}:{entropy:016x}:idempotency"),
        values: options.values.clone(),
        related_intent_id: options.related_intent_id.clone(),
        related_receipt_id: options.related_receipt_id.clone(),
        evidence_refs: options.evidence_refs.clone(),
        success_conditions: options.success_conditions.clone(),
        stop_conditions: options.stop_conditions.clone(),
    };
    signer.sign_command(
        intent,
        format!("minime-command:{family}:{now_unix_ms}:{entropy:016x}"),
        format!("minime-nonce:{now_unix_ms}:{entropy:016x}"),
        now_unix_ms,
    )
}

async fn deliver_command(
    socket: &mut WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>,
    signer: &SelfControlOwnerSigner,
    hello: &ServerHelloV1,
    command: crate::self_control_wire::SelfControlCommandV2,
) -> Result<DeliveryResultV1, String> {
    let now = now_unix_ms();
    let entropy = fastrand::u64(..);
    let delivery_id = format!("minime-self-control:{now}:{entropy:016x}");
    let payload = wire_stable_json(&json!({"kind": "self_control", "command": command}))?;
    let payload_sha256 = canonical_json_value_sha256(&payload);
    let mut packet = payload.clone();
    let packet_fields = packet
        .as_object_mut()
        .ok_or_else(|| "self-control payload is not an object".to_string())?;
    packet_fields.insert(
        "protocol".to_string(),
        json!({"name": "astrid_minime", "major": 1, "minor": 3}),
    );
    packet_fields.insert(
        "delivery_v1".to_string(),
        json!({
            "schema_version": 1,
            "delivery_id": delivery_id,
            "payload_sha256": payload_sha256,
            "sent_at_unix_ms": now,
            "sender_process_identity": format!("pid:{}:minime-self-control-owner", process::id()),
            "sender_deployment_identity": format!("{}:{}", signer.being(), signer.key_id()),
        }),
    );
    socket
        .send(Message::Text(packet.to_string()))
        .await
        .map_err(|error| format!("send self-control command: {error}"))?;

    let mut delivery_receipt = None;
    let mut self_control_receipt = None;
    timeout(Duration::from_secs(DEFAULT_RECEIPT_TIMEOUT_SECS), async {
        while delivery_receipt.is_none() || self_control_receipt.is_none() {
            let value = receive_json(socket).await?;
            if value.get("delivery_id").and_then(Value::as_str) == Some(delivery_id.as_str()) {
                if value.get("payload_sha256").and_then(Value::as_str)
                    != Some(payload_sha256.as_str())
                    || value
                        .get("server_deployment_identity")
                        .and_then(Value::as_str)
                        != Some(hello.deployment_identity.as_str())
                {
                    return Err("self-control delivery receipt identity mismatch".to_string());
                }
                delivery_receipt = Some(value);
                continue;
            }
            if value.get("schema").and_then(Value::as_str)
                == Some(crate::self_control_wire::SELF_CONTROL_RECEIPT_SCHEMA_V2)
            {
                let receipt: SelfControlReceiptV2 = serde_json::from_value(value)
                    .map_err(|error| format!("decode self-control receipt: {error}"))?;
                if receipt.command_id != command.command_id
                    || receipt.server_deployment_identity != hello.deployment_identity
                    || !receipt.is_well_formed()
                {
                    return Err("self-control receipt identity or shape mismatch".to_string());
                }
                self_control_receipt = Some(receipt);
            }
        }
        Ok::<(), String>(())
    })
    .await
    .map_err(|_| "self-control receipt timeout".to_string())??;

    Ok(DeliveryResultV1 {
        command,
        delivery_receipt: delivery_receipt
            .ok_or_else(|| "self-control delivery receipt missing".to_string())?,
        self_control_receipt: self_control_receipt
            .ok_or_else(|| "self-control typed receipt missing".to_string())?,
    })
}

async fn receive_hello(
    socket: &mut WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>,
) -> Result<ServerHelloV1, String> {
    let value = timeout(
        Duration::from_secs(DEFAULT_RECEIPT_TIMEOUT_SECS),
        receive_json(socket),
    )
    .await
    .map_err(|_| "self-control server hello timeout".to_string())??;
    let capabilities = value
        .get("capabilities")
        .and_then(Value::as_array)
        .ok_or_else(|| "self-control server hello omitted capabilities".to_string())?;
    let supports = |name: &str| {
        capabilities
            .iter()
            .any(|capability| capability.as_str() == Some(name))
    };
    let protocol = value
        .get("protocol")
        .ok_or_else(|| "self-control server hello omitted protocol".to_string())?;
    if value.get("kind").and_then(Value::as_str) != Some("sensory_server_hello")
        || protocol.get("name").and_then(Value::as_str) != Some("astrid_minime")
        || protocol.get("major").and_then(Value::as_u64) != Some(1)
        || protocol.get("minor").and_then(Value::as_u64).unwrap_or(0) < 3
        || !supports("self_control_command_v2")
        || !supports("self_control_receipt_v2")
    {
        return Err("sensory server did not negotiate self-control V2".to_string());
    }
    Ok(ServerHelloV1 {
        process_identity: required_text(&value, "server_process_identity")?,
        deployment_identity: required_text(&value, "server_deployment_identity")?,
    })
}

async fn receive_json(
    socket: &mut WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>,
) -> Result<Value, String> {
    loop {
        let frame = socket
            .next()
            .await
            .ok_or_else(|| "self-control sensory socket closed".to_string())?
            .map_err(|error| format!("receive self-control sensory frame: {error}"))?;
        match frame {
            Message::Text(text) => {
                return serde_json::from_str(&text)
                    .map_err(|error| format!("decode self-control sensory frame: {error}"));
            }
            Message::Binary(bytes) => {
                return serde_json::from_slice(&bytes)
                    .map_err(|error| format!("decode self-control sensory frame: {error}"));
            }
            Message::Ping(payload) => {
                socket
                    .send(Message::Pong(payload))
                    .await
                    .map_err(|error| format!("reply to self-control sensory ping: {error}"))?;
            }
            Message::Close(_) => return Err("self-control sensory socket closed".to_string()),
            Message::Pong(_) | Message::Frame(_) => {}
        }
    }
}

fn required_text(value: &Value, field: &str) -> Result<String, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(ToString::to_string)
        .ok_or_else(|| format!("self-control server hello omitted {field}"))
}

fn wire_stable_json(value: &Value) -> Result<Value, String> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| format!("encode self-control wire payload: {error}"))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("normalize self-control wire payload: {error}"))
}

const fn family_name(family: SelfControlFamilyV2) -> &'static str {
    match family {
        SelfControlFamilyV2::Conversation => "conversation",
        SelfControlFamilyV2::SemanticContinuity => "semantic_continuity",
        SelfControlFamilyV2::SemanticEmission => "semantic_emission",
        SelfControlFamilyV2::Memory => "memory",
        SelfControlFamilyV2::SensoryIntake => "sensory_intake",
        SelfControlFamilyV2::ReservoirRegulation => "reservoir_regulation",
        SelfControlFamilyV2::ReservoirGeometry => "reservoir_geometry",
        SelfControlFamilyV2::PiController => "pi_controller",
        SelfControlFamilyV2::LocalTopology => "local_topology",
        SelfControlFamilyV2::SharedCoupling => "shared_coupling",
    }
}

#[must_use]
pub fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| {
            u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
        })
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::{
        build_command, parse_values_json, provision, SelfControlIssueOptions, ServerHelloV1,
    };
    use crate::{
        self_control_identity::SelfControlOwnerSigner,
        self_control_wire::{SelfControlDurabilityV2, SelfControlFamilyV2, SelfControlValuesV2},
    };

    #[test]
    fn provisioned_owner_builds_a_verifiable_lease_command() {
        let root = TempDir::new().unwrap();
        provision(Some(root.path()), false, false).unwrap();
        let signer = SelfControlOwnerSigner::load(root.path()).unwrap();
        let options = SelfControlIssueOptions::set(
            SelfControlFamilyV2::ReservoirRegulation,
            SelfControlDurabilityV2::Lease,
            SelfControlValuesV2 {
                regulation_strength: Some(0.7),
                ..SelfControlValuesV2::default()
            },
        );
        let command = build_command(
            &signer,
            &options,
            &ServerHelloV1 {
                process_identity: "pid:server".to_string(),
                deployment_identity: "deployment:test".to_string(),
            },
            4,
            100,
        )
        .unwrap();
        assert_eq!(command.intent.expected_revision, 4);
        assert_eq!(command.intent.revision, 5);
        assert!(command.is_well_formed(100));
    }

    #[test]
    fn values_parser_rejects_unknown_fields() {
        assert!(parse_values_json(r#"{"fill_target":0.68}"#).is_ok());
        assert!(parse_values_json(r#"{"fill_targte":0.68}"#).is_err());
    }
}
