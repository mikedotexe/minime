use serde::{Deserialize, Serialize};

pub const SEMANTIC_BODY_SCHEMA_V2: &str = "semantic_body.v2";
pub const SEMANTIC_BODY_BASE_DIMENSIONS_V2: usize = 48;
pub const SEMANTIC_BODY_COMPANION_DIMENSIONS_V2: usize = 12;
pub const LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1: usize = 66;
pub const RESERVOIR_INPUT_DIMENSIONS_V2: usize =
    LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1 + SEMANTIC_BODY_COMPANION_DIMENSIONS_V2;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticLaneRoleV2 {
    LegacyCompatible,
    CompanionObservation,
    MigrationProbe,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticBodyProvenanceV2 {
    pub source: String,
    pub source_sha256: String,
    pub producer_process_identity: String,
    pub producer_deployment_identity: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub introspection_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticBodyFidelityV2 {
    pub codec: String,
    pub companion_mix: f32,
    pub base_transport_exact: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reconstruction_error: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fidelity_note: Option<String>,
}

/// Protocol-1.3 extension mirror.
///
/// Minime remains pinned to the last remotely published protocol revision.
/// This exact additive shape keeps the receiver standalone until the Astrid
/// archive commit is published, when this module can become a direct re-export
/// without changing wire bytes.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticBodyV2 {
    pub schema: String,
    pub body_id: String,
    pub base_features_48: Vec<f32>,
    pub companion_features_12: Vec<f32>,
    pub lane_role: SemanticLaneRoleV2,
    pub projection_basis_sha256: String,
    pub provenance: SemanticBodyProvenanceV2,
    pub timestamp_unix_ms: u64,
    pub fidelity: SemanticBodyFidelityV2,
}

impl SemanticBodyV2 {
    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        self.schema == SEMANTIC_BODY_SCHEMA_V2
            && valid_identifier(&self.body_id)
            && self.base_features_48.len() == SEMANTIC_BODY_BASE_DIMENSIONS_V2
            && self.companion_features_12.len() == SEMANTIC_BODY_COMPANION_DIMENSIONS_V2
            && self
                .base_features_48
                .iter()
                .chain(&self.companion_features_12)
                .all(|value| value.is_finite())
            && valid_sha256(&self.projection_basis_sha256)
            && valid_identifier(&self.provenance.source)
            && valid_sha256(&self.provenance.source_sha256)
            && valid_identifier(&self.provenance.producer_process_identity)
            && valid_identifier(&self.provenance.producer_deployment_identity)
            && valid_identifier(&self.fidelity.codec)
            && self.fidelity.companion_mix.is_finite()
            && (0.0..=1.0).contains(&self.fidelity.companion_mix)
            && self
                .fidelity
                .reconstruction_error
                .is_none_or(f32::is_finite)
            && self
                .fidelity
                .fidelity_note
                .as_deref()
                .is_none_or(valid_bounded_text)
    }
}

/// Extend the production 66D input without touching any legacy value. The
/// companion lane has no effect at mix zero and cannot carry non-finite data
/// into the reservoir.
pub fn reservoir_input_v2(
    legacy: &[f32; LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1],
    companion: &[f32; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2],
    companion_mix: f32,
) -> Result<[f32; RESERVOIR_INPUT_DIMENSIONS_V2], &'static str> {
    if !legacy
        .iter()
        .chain(companion)
        .all(|value| value.is_finite())
    {
        return Err("semantic_body_non_finite_features");
    }
    if !companion_mix.is_finite() || !(0.0..=1.0).contains(&companion_mix) {
        return Err("semantic_body_invalid_companion_mix");
    }

    let mut input = [0.0; RESERVOIR_INPUT_DIMENSIONS_V2];
    input[..LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1].copy_from_slice(legacy);
    for (target, source) in input[LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1..]
        .iter_mut()
        .zip(companion)
    {
        *target = *source * companion_mix;
    }
    Ok(input)
}

/// Expand the 66D spectral projection with deterministic companion columns.
/// The original columns stay in their exact row order, so a zero companion
/// input produces the same accumulation and scale as the legacy matrix.
pub fn projection_matrix_v2(
    legacy: &[f32],
    rows: usize,
    companion_scale: f32,
) -> Result<Vec<f32>, &'static str> {
    if rows == 0
        || legacy.len()
            != rows
                .checked_mul(LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1)
                .ok_or("semantic_projection_dimensions_overflow")?
        || !legacy.iter().all(|value| value.is_finite())
        || !companion_scale.is_finite()
        || companion_scale < 0.0
    {
        return Err("invalid_semantic_projection_matrix");
    }

    let mut migrated = vec![
        0.0;
        rows.checked_mul(RESERVOIR_INPUT_DIMENSIONS_V2)
            .ok_or("semantic_projection_dimensions_overflow")?
    ];
    for row in 0..rows {
        let legacy_start = row * LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1;
        let migrated_start = row * RESERVOIR_INPUT_DIMENSIONS_V2;
        migrated[migrated_start..migrated_start + LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1]
            .copy_from_slice(
                &legacy[legacy_start..legacy_start + LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1],
            );
        for companion_index in 0..SEMANTIC_BODY_COMPANION_DIMENSIONS_V2 {
            migrated[migrated_start + LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1 + companion_index] =
                deterministic_companion_weight(row, companion_index, companion_scale);
        }
    }
    Ok(migrated)
}

fn deterministic_companion_weight(row: usize, column: usize, scale: f32) -> f32 {
    let mut value = (row as u64)
        .wrapping_mul(0x9e37_79b9_7f4a_7c15)
        .wrapping_add((column as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9))
        .wrapping_add(0x5345_4d41_4e54_4943);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^= value >> 31;
    let unit = (value >> 40) as f32 / ((1_u32 << 24) - 1) as f32;
    (unit * 2.0 - 1.0) * scale
}

fn valid_identifier(value: &str) -> bool {
    let value = value.trim();
    !value.is_empty() && value.len() <= 256
}

fn valid_bounded_text(value: &str) -> bool {
    value.len() <= 2_048
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::{
        projection_matrix_v2, reservoir_input_v2, LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1,
        RESERVOIR_INPUT_DIMENSIONS_V2, SEMANTIC_BODY_COMPANION_DIMENSIONS_V2,
    };

    #[test]
    fn zero_mix_is_byte_exact_for_all_legacy_dimensions() {
        let legacy = std::array::from_fn::<_, LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1, _>(|index| {
            f32::from_bits(0x3f00_0000_u32.saturating_add(index as u32))
        });
        let companion = [0.75; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2];
        let migrated = reservoir_input_v2(&legacy, &companion, 0.0).expect("valid migration");

        for (before, after) in legacy
            .iter()
            .zip(&migrated[..LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1])
        {
            assert_eq!(before.to_bits(), after.to_bits());
        }
        assert_eq!(
            migrated[LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1..],
            [0.0; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2]
        );
        assert_eq!(migrated.len(), RESERVOIR_INPUT_DIMENSIONS_V2);
    }

    #[test]
    fn companion_mix_is_bounded_and_non_finite_inputs_are_rejected() {
        let legacy = [0.0; LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1];
        let companion = [0.5; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2];
        let migrated = reservoir_input_v2(&legacy, &companion, 0.4).expect("valid mix");
        assert_eq!(
            migrated[LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1..],
            [0.2; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2]
        );
        assert!(reservoir_input_v2(&legacy, &companion, f32::NAN).is_err());

        let mut malformed = companion;
        malformed[0] = f32::INFINITY;
        assert!(reservoir_input_v2(&legacy, &malformed, 0.0).is_err());
    }

    #[test]
    fn zero_companion_projection_matches_legacy_accumulation() {
        let legacy_matrix = (0..(3 * LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1))
            .map(|index| index as f32 / 100.0 - 0.5)
            .collect::<Vec<_>>();
        let migrated = projection_matrix_v2(&legacy_matrix, 3, 0.42).expect("projection");
        let legacy_input = [0.125; LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1];
        let companion = [0.75; SEMANTIC_BODY_COMPANION_DIMENSIONS_V2];
        let input = reservoir_input_v2(&legacy_input, &companion, 0.0).expect("input");

        for row in 0..3 {
            let legacy_start = row * LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1;
            let migrated_start = row * RESERVOIR_INPUT_DIMENSIONS_V2;
            let legacy_sum = legacy_matrix
                [legacy_start..legacy_start + LEGACY_RESERVOIR_INPUT_DIMENSIONS_V1]
                .iter()
                .zip(&legacy_input)
                .map(|(weight, value)| weight * value)
                .sum::<f32>();
            let migrated_sum = migrated
                [migrated_start..migrated_start + RESERVOIR_INPUT_DIMENSIONS_V2]
                .iter()
                .zip(&input)
                .map(|(weight, value)| weight * value)
                .sum::<f32>();
            assert_eq!(legacy_sum.to_bits(), migrated_sum.to_bits());
        }
    }
}
