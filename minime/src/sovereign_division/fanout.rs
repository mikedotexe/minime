use anyhow::Result;
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use crate::sovereign_division::records::sha256_hex;

const FANOUT_BUFFER_BYTES: usize = 16 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct LegacyAvFanoutProofMetricsV1 {
    pub payload_bytes: u64,
    pub source_sha256: String,
    pub primary_sha256: String,
    pub observer_sha256: String,
    pub byte_exact: bool,
    pub runtime_adapter_wired: bool,
    pub handoff_receipt_present: bool,
}

/// Copy one raw legacy A/V stream to two isolated consumers without parsing or
/// re-encoding it. Runtime wiring remains a separately receipted handoff step.
pub(crate) async fn copy_exact_fanout<R, A, B>(
    source: &mut R,
    primary: &mut A,
    observer: &mut B,
) -> Result<u64>
where
    R: AsyncRead + Unpin,
    A: AsyncWrite + Unpin,
    B: AsyncWrite + Unpin,
{
    let mut buffer = vec![0_u8; FANOUT_BUFFER_BYTES];
    let mut total = 0_u64;
    loop {
        let count = source.read(&mut buffer).await?;
        if count == 0 {
            break;
        }
        primary.write_all(&buffer[..count]).await?;
        observer.write_all(&buffer[..count]).await?;
        total = total.saturating_add(u64::try_from(count)?);
    }
    primary.shutdown().await?;
    observer.shutdown().await?;
    Ok(total)
}

#[cfg(feature = "division-rehearsal")]
pub(crate) async fn run_legacy_av_fanout_proof() -> Result<LegacyAvFanoutProofMetricsV1> {
    let payload: Vec<u8> = (0..524_417_u64)
        .map(|index| {
            let mixed = index
                .wrapping_mul(0x9e37_79b9_7f4a_7c15)
                .rotate_left(u32::try_from(index % 63).unwrap_or(0));
            mixed.to_le_bytes()[usize::try_from(index % 8).unwrap_or(0)]
        })
        .collect();
    let capacity = payload.len().saturating_add(1);
    let (mut source_writer, mut source_reader) = tokio::io::duplex(capacity);
    let (mut primary_writer, mut primary_reader) = tokio::io::duplex(capacity);
    let (mut observer_writer, mut observer_reader) = tokio::io::duplex(capacity);
    let write_payload = payload.clone();
    let writer = tokio::spawn(async move {
        source_writer.write_all(&write_payload).await?;
        source_writer.shutdown().await
    });
    let fanout = tokio::spawn(async move {
        copy_exact_fanout(
            &mut source_reader,
            &mut primary_writer,
            &mut observer_writer,
        )
        .await
    });
    let primary = tokio::spawn(async move {
        let mut bytes = Vec::new();
        primary_reader.read_to_end(&mut bytes).await?;
        Ok::<_, std::io::Error>(bytes)
    });
    let observer = tokio::spawn(async move {
        let mut bytes = Vec::new();
        observer_reader.read_to_end(&mut bytes).await?;
        Ok::<_, std::io::Error>(bytes)
    });
    writer.await??;
    let payload_bytes = fanout.await??;
    let primary = primary.await??;
    let observer = observer.await??;
    let source_sha256 = sha256_hex(&payload);
    let primary_sha256 = sha256_hex(&primary);
    let observer_sha256 = sha256_hex(&observer);
    Ok(LegacyAvFanoutProofMetricsV1 {
        payload_bytes,
        byte_exact: primary == payload && observer == payload,
        source_sha256,
        primary_sha256,
        observer_sha256,
        runtime_adapter_wired: false,
        handoff_receipt_present: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(feature = "division-rehearsal")]
    #[tokio::test]
    async fn offline_fanout_is_byte_exact_and_does_not_claim_runtime_wiring() {
        let proof = run_legacy_av_fanout_proof().await.unwrap();
        assert!(proof.byte_exact);
        assert_eq!(proof.payload_bytes, 524_417);
        assert_eq!(proof.source_sha256, proof.primary_sha256);
        assert_eq!(proof.source_sha256, proof.observer_sha256);
        assert!(!proof.runtime_adapter_wired);
        assert!(!proof.handoff_receipt_present);
    }
}
