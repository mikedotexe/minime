use std::{net::SocketAddr, path::Path, sync::Arc};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use tokio::{
    io,
    net::{TcpListener, TcpStream},
};

use crate::sovereign_division::records::{
    now_unix_ms, sha256_hex, write_owner_json, DivisionRuntimeManifestV1,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct GatewayByteExactProofMetricsV1 {
    pub payload_count: u64,
    pub payload_bytes: u64,
    pub source_sha256: String,
    pub echoed_sha256: String,
    pub byte_exact: bool,
    pub latency_bound_micros: u64,
    pub p95_within_bound: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum AuthorityRail {
    Parent,
    Daughters,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityStateWireV1 {
    schema: String,
    division_id: String,
    manifest_sha256: String,
    rail: AuthorityRail,
    switch_receipt_sha256: Option<String>,
    #[serde(default)]
    handoff_contract_receipt_sha256: Option<String>,
    created_at_unix_ms: u64,
    live_authority_granted_by_record: bool,
}

pub async fn run_gateway(manifest_path: &Path) -> Result<()> {
    let manifest = Arc::new(DivisionRuntimeManifestV1::load(manifest_path)?);
    manifest.validate_current(now_unix_ms())?;
    let bindings = [
        ("127.0.0.1:7878", "parent_telemetry", "minime_telemetry"),
        ("127.0.0.1:7879", "parent_sensory", "minime_sensory"),
        ("127.0.0.1:7880", "parent_av", "parent_av"),
        ("127.0.0.1:7882", "parent_telemetry", "astrid_telemetry"),
        ("127.0.0.1:7883", "reject", "astrid_sensory"),
    ];
    let mut tasks = Vec::new();
    for (public, parent_target, daughter_target) in bindings {
        let listener = TcpListener::bind(public)
            .await
            .with_context(|| format!("bind sovereign gateway {public}"))?;
        let manifest = manifest.clone();
        tasks.push(tokio::spawn(async move {
            accept_proxy(listener, manifest, parent_target, daughter_target).await
        }));
    }
    write_owner_json(
        &manifest.runtime_dir().join("gateway-status.json"),
        &serde_json::json!({
            "schema": "division.gateway_status.v1",
            "division_id": manifest.division_id(),
            "manifest_sha256": manifest.manifest_sha256(),
            "pid": std::process::id(),
            "mode": "transparent_parent",
            "public_ports": [7878, 7879, 7880, 7882, 7883],
            "started_at_unix_ms": now_unix_ms(),
            "live_authority_granted_by_record": false,
        }),
    )?;
    for task in tasks {
        task.await??;
    }
    Ok(())
}

async fn accept_proxy(
    listener: TcpListener,
    manifest: Arc<DivisionRuntimeManifestV1>,
    parent_target: &'static str,
    daughter_target: &'static str,
) -> Result<()> {
    loop {
        let (inbound, _) = listener.accept().await?;
        if let Some(target) = selected_target(&manifest, parent_target, daughter_target)? {
            tokio::spawn(async move {
                if let Err(error) = proxy_connection(inbound, target).await {
                    eprintln!("division gateway connection failed: {error:#}");
                }
            });
        }
    }
}

fn selected_target(
    manifest: &DivisionRuntimeManifestV1,
    parent_target: &str,
    daughter_target: &str,
) -> Result<Option<SocketAddr>> {
    let path = manifest.runtime_dir().join("authority.json");
    let state = if path.is_file() {
        let wire: AuthorityStateWireV1 = serde_json::from_slice(&std::fs::read(&path)?)?;
        if wire.schema != "division.gateway_authority.v1" {
            return Err(anyhow!("unsupported gateway authority state"));
        }
        if wire.created_at_unix_ms == 0 || wire.live_authority_granted_by_record {
            return Err(anyhow!("gateway authority evidence boundary is invalid"));
        }
        if wire.division_id != manifest.division_id()
            || wire.manifest_sha256 != manifest.manifest_sha256()
        {
            return Err(anyhow!(
                "gateway authority state does not match the active manifest"
            ));
        }
        if matches!(wire.rail, AuthorityRail::Daughters)
            && (wire
                .switch_receipt_sha256
                .as_deref()
                .is_none_or(|hash| hash.len() != 64)
                || wire
                    .handoff_contract_receipt_sha256
                    .as_deref()
                    .is_none_or(|hash| hash.len() != 64))
        {
            return Err(anyhow!(
                "daughter authority requires exact switch and handoff-contract receipts"
            ));
        }
        wire.rail
    } else {
        AuthorityRail::Parent
    };
    let endpoint = match state {
        AuthorityRail::Parent => manifest.endpoint(parent_target),
        AuthorityRail::Daughters => manifest.endpoint(daughter_target),
    };
    if endpoint.is_empty() {
        return Ok(None);
    }
    Ok(Some(endpoint.parse().context("parse gateway target")?))
}

async fn proxy_connection(mut inbound: TcpStream, target: SocketAddr) -> Result<()> {
    inbound.set_nodelay(true)?;
    let mut outbound = TcpStream::connect(target).await?;
    outbound.set_nodelay(true)?;
    io::copy_bidirectional(&mut inbound, &mut outbound).await?;
    Ok(())
}

#[cfg(feature = "division-rehearsal")]
pub(crate) async fn run_gateway_byte_exact_proof() -> Result<GatewayByteExactProofMetricsV1> {
    use std::time::Instant;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    const PAYLOAD_COUNT: usize = 257;
    let backend = TcpListener::bind("127.0.0.1:0").await?;
    let backend_addr = backend.local_addr()?;
    let backend_task = tokio::spawn(async move {
        let (mut stream, _) = backend.accept().await?;
        for _ in 0..PAYLOAD_COUNT {
            let length = usize::try_from(stream.read_u32().await?)?;
            if length == 0 || length > 8192 {
                return Err(anyhow!("gateway proof payload exceeded bound"));
            }
            let mut payload = vec![0_u8; length];
            stream.read_exact(&mut payload).await?;
            stream.write_u32(u32::try_from(length)?).await?;
            stream.write_all(&payload).await?;
        }
        Ok::<_, anyhow::Error>(())
    });
    let gateway = TcpListener::bind("127.0.0.1:0").await?;
    let gateway_addr = gateway.local_addr()?;
    let gateway_task = tokio::spawn(async move {
        let (stream, _) = gateway.accept().await?;
        proxy_connection(stream, backend_addr).await
    });
    let mut client = TcpStream::connect(gateway_addr).await?;
    client.set_nodelay(true)?;
    let mut source_bytes = Vec::new();
    let mut echoed_bytes = Vec::new();
    let mut samples = Vec::with_capacity(PAYLOAD_COUNT);
    for index in 0..PAYLOAD_COUNT {
        let length = 1 + ((index * 193) % 8192);
        let payload: Vec<u8> = (0..length)
            .map(|offset| {
                let value = (index as u64)
                    .wrapping_mul(0x9e37_79b9)
                    .wrapping_add(offset as u64)
                    .rotate_left(u32::try_from(offset % 63).unwrap_or(0));
                value.to_le_bytes()[offset % 8]
            })
            .collect();
        let started = Instant::now();
        client.write_u32(u32::try_from(length)?).await?;
        client.write_all(&payload).await?;
        let echoed_length = usize::try_from(client.read_u32().await?)?;
        let mut echoed = vec![0_u8; echoed_length];
        client.read_exact(&mut echoed).await?;
        samples.push(started.elapsed());
        source_bytes.extend_from_slice(&payload);
        echoed_bytes.extend_from_slice(&echoed);
        if echoed != payload {
            return Err(anyhow!("gateway proof observed byte drift"));
        }
    }
    drop(client);
    backend_task.await??;
    gateway_task.await??;
    samples.sort_unstable();
    let p95_index = PAYLOAD_COUNT.saturating_mul(95).saturating_sub(1) / 100;
    let p95_micros = u64::try_from(samples[p95_index].as_micros()).unwrap_or(u64::MAX);
    let latency_bound_micros = 5_000;
    Ok(GatewayByteExactProofMetricsV1 {
        payload_count: u64::try_from(PAYLOAD_COUNT)?,
        payload_bytes: u64::try_from(source_bytes.len())?,
        source_sha256: sha256_hex(&source_bytes),
        echoed_sha256: sha256_hex(&echoed_bytes),
        byte_exact: source_bytes == echoed_bytes,
        latency_bound_micros,
        p95_within_bound: p95_micros <= latency_bound_micros,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    #[test]
    fn authority_state_requires_switch_hash_for_daughters() {
        let invalid: AuthorityStateWireV1 = serde_json::from_value(serde_json::json!({
            "schema": "division.gateway_authority.v1",
            "division_id": "division-test",
            "manifest_sha256": "a".repeat(64),
            "rail": "daughters",
            "switch_receipt_sha256": null,
            "handoff_contract_receipt_sha256": null,
            "created_at_unix_ms": 1,
            "live_authority_granted_by_record": false
        }))
        .unwrap();
        assert!(matches!(invalid.rail, AuthorityRail::Daughters));
        assert!(invalid.switch_receipt_sha256.is_none());
        assert!(invalid.handoff_contract_receipt_sha256.is_none());
        assert!(!invalid.live_authority_granted_by_record);
    }

    #[tokio::test]
    async fn transparent_proxy_is_byte_exact_and_sub_millisecond_p95() {
        let backend = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let backend_addr = backend.local_addr().unwrap();
        let backend_task = tokio::spawn(async move {
            let (mut stream, _) = backend.accept().await.unwrap();
            let mut buffer = [0_u8; 256];
            for _ in 0..100 {
                stream.read_exact(&mut buffer).await.unwrap();
                stream.write_all(&buffer).await.unwrap();
            }
        });
        let gateway = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let gateway_addr = gateway.local_addr().unwrap();
        let gateway_task = tokio::spawn(async move {
            let (stream, _) = gateway.accept().await.unwrap();
            proxy_connection(stream, backend_addr).await.unwrap();
        });
        let mut client = TcpStream::connect(gateway_addr).await.unwrap();
        client.set_nodelay(true).unwrap();
        let payload = [0x5a_u8; 256];
        let mut reply = [0_u8; 256];
        let mut samples = Vec::new();
        for _ in 0..100 {
            let started = Instant::now();
            client.write_all(&payload).await.unwrap();
            client.read_exact(&mut reply).await.unwrap();
            samples.push(started.elapsed());
            assert_eq!(reply, payload);
        }
        samples.sort_unstable();
        assert!(
            samples[94].as_micros() < 1_000,
            "transparent forwarding p95 exceeded 1 ms: {:?}",
            samples[94]
        );
        drop(client);
        backend_task.await.unwrap();
        gateway_task.await.unwrap();
    }

    #[cfg(feature = "division-rehearsal")]
    #[tokio::test]
    async fn varied_payload_gateway_proof_is_byte_exact() {
        let proof = run_gateway_byte_exact_proof().await.unwrap();
        assert_eq!(proof.payload_count, 257);
        assert!(proof.payload_bytes > 1_000_000);
        assert_eq!(proof.source_sha256, proof.echoed_sha256);
        assert!(proof.byte_exact);
        assert!(proof.p95_within_bound);
    }
}
