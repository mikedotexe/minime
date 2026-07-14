use serde::Serialize;

pub const SPECTRAL_FINGERPRINT_POLICY: &str = "spectral_fingerprint_v1";
pub const SPECTRAL_FINGERPRINT_SCHEMA_VERSION: u8 = 1;
pub const LEGACY_FINGERPRINT_LEN: usize = 32;
pub const SPECTRAL_DENOMINATOR_POLICY: &str = "spectral_denominator_v1";
pub const SPECTRAL_DENOMINATOR_SCHEMA_VERSION: u8 = 1;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SpectralFingerprintV1 {
    pub policy: &'static str,
    pub schema_version: u8,
    pub eigenvalues: [f32; 8],
    pub eigenvector_concentration_top4: [f32; 8],
    pub inter_mode_cosine_top_abs: [f32; 8],
    pub spectral_entropy: f32,
    pub lambda1_lambda2_gap: f32,
    pub v1_rotation_similarity: f32,
    pub v1_rotation_delta: f32,
    pub geom_rel: f32,
    pub adjacent_gap_ratios: [f32; 4],
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub struct SpectralDenominatorV1 {
    pub policy: &'static str,
    pub schema_version: u8,
    pub effective_dimensionality: f32,
    pub active_mode_capacity: usize,
    pub distinguishability_loss: f32,
    pub lambda1_energy_share: f32,
    pub spectral_entropy: f32,
}

impl SpectralFingerprintV1 {
    #[must_use]
    pub fn from_legacy_slots(slots: &[f32]) -> Option<Self> {
        if slots.len() < LEGACY_FINGERPRINT_LEN {
            return None;
        }

        let eigenvalues = array_from_slice::<8>(&slots[0..8]);
        let eigenvector_concentration_top4 = array_from_slice::<8>(&slots[8..16]);
        let inter_mode_cosine_top_abs = array_from_slice::<8>(&slots[16..24]);
        let spectral_entropy = finite(slots[24]);
        let lambda1_lambda2_gap = finite(slots[25]);
        let v1_rotation_similarity = finite(slots[26]);
        let geom_rel = finite(slots[27]);
        let adjacent_gap_ratios = array_from_slice::<4>(&slots[28..32]);

        Some(Self {
            policy: SPECTRAL_FINGERPRINT_POLICY,
            schema_version: SPECTRAL_FINGERPRINT_SCHEMA_VERSION,
            eigenvalues,
            eigenvector_concentration_top4,
            inter_mode_cosine_top_abs,
            spectral_entropy,
            lambda1_lambda2_gap,
            v1_rotation_similarity,
            v1_rotation_delta: (1.0 - v1_rotation_similarity).clamp(0.0, 2.0),
            geom_rel,
            adjacent_gap_ratios,
        })
    }

    #[must_use]
    pub fn to_legacy_slots(&self) -> Vec<f32> {
        let mut slots = Vec::with_capacity(LEGACY_FINGERPRINT_LEN);
        slots.extend_from_slice(&self.eigenvalues);
        slots.extend_from_slice(&self.eigenvector_concentration_top4);
        slots.extend_from_slice(&self.inter_mode_cosine_top_abs);
        slots.push(self.spectral_entropy);
        slots.push(self.lambda1_lambda2_gap);
        slots.push(self.v1_rotation_similarity);
        slots.push(self.geom_rel);
        slots.extend_from_slice(&self.adjacent_gap_ratios);
        slots
    }

    #[must_use]
    pub fn effective_dimensionality(&self) -> f32 {
        effective_dimensionality(&self.eigenvalues)
    }

    #[must_use]
    pub fn denominator_metrics(&self) -> SpectralDenominatorV1 {
        let active_mode_capacity = self
            .eigenvalues
            .iter()
            .filter(|value| finite(**value).abs() > 1.0e-6)
            .count()
            .max(1);
        let effective_dimensionality = self.effective_dimensionality();
        let normalized = effective_dimensionality / active_mode_capacity as f32;
        let distinguishability_loss = (1.0 - normalized).clamp(0.0, 1.0);
        let total = self
            .eigenvalues
            .iter()
            .map(|value| finite(*value).abs())
            .sum::<f32>();
        let lambda1_energy_share = if total > 1.0e-6 {
            finite(self.eigenvalues[0]).abs() / total
        } else {
            0.0
        };

        SpectralDenominatorV1 {
            policy: SPECTRAL_DENOMINATOR_POLICY,
            schema_version: SPECTRAL_DENOMINATOR_SCHEMA_VERSION,
            effective_dimensionality,
            active_mode_capacity,
            distinguishability_loss,
            lambda1_energy_share,
            spectral_entropy: self.spectral_entropy,
        }
    }
}

fn finite(value: f32) -> f32 {
    if value.is_finite() {
        value
    } else {
        0.0
    }
}

fn array_from_slice<const N: usize>(values: &[f32]) -> [f32; N] {
    std::array::from_fn(|index| values.get(index).copied().map_or(0.0, finite))
}

fn effective_dimensionality(values: &[f32]) -> f32 {
    let mut sum = 0.0;
    let mut sum_sq = 0.0;
    for value in values.iter().copied().map(finite).map(f32::abs) {
        sum += value;
        sum_sq += value * value;
    }
    if sum_sq > 1.0e-12 {
        (sum * sum / sum_sq).max(0.0)
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_slots_map_to_named_schema() {
        let slots = (0..LEGACY_FINGERPRINT_LEN)
            .map(|value| value as f32)
            .collect::<Vec<_>>();

        let typed = SpectralFingerprintV1::from_legacy_slots(&slots).unwrap();

        assert_eq!(typed.policy, SPECTRAL_FINGERPRINT_POLICY);
        assert_eq!(typed.schema_version, SPECTRAL_FINGERPRINT_SCHEMA_VERSION);
        assert_eq!(typed.eigenvalues[7], 7.0);
        assert_eq!(typed.eigenvector_concentration_top4[0], 8.0);
        assert_eq!(typed.inter_mode_cosine_top_abs[7], 23.0);
        assert_eq!(typed.spectral_entropy, 24.0);
        assert_eq!(typed.lambda1_lambda2_gap, 25.0);
        assert_eq!(typed.v1_rotation_similarity, 26.0);
        assert_eq!(typed.geom_rel, 27.0);
        assert_eq!(typed.adjacent_gap_ratios, [28.0, 29.0, 30.0, 31.0]);
        assert_eq!(typed.to_legacy_slots(), slots);
    }

    #[test]
    fn denominator_metrics_capture_effective_dimensionality() {
        let typed = SpectralFingerprintV1 {
            policy: SPECTRAL_FINGERPRINT_POLICY,
            schema_version: SPECTRAL_FINGERPRINT_SCHEMA_VERSION,
            eigenvalues: [4.0, 3.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
            eigenvector_concentration_top4: [0.0; 8],
            inter_mode_cosine_top_abs: [0.0; 8],
            spectral_entropy: 0.8,
            lambda1_lambda2_gap: 1.33,
            v1_rotation_similarity: 1.0,
            v1_rotation_delta: 0.0,
            geom_rel: 1.0,
            adjacent_gap_ratios: [1.33, 3.0, 1.0, 1.0],
        };

        let metrics = typed.denominator_metrics();

        assert_eq!(metrics.policy, SPECTRAL_DENOMINATOR_POLICY);
        assert_eq!(metrics.active_mode_capacity, 5);
        assert!((metrics.effective_dimensionality - (100.0 / 28.0)).abs() < 1.0e-6);
        assert!(metrics.distinguishability_loss > 0.0);
        assert!(metrics.distinguishability_loss < 1.0);
    }

    #[test]
    fn denominator_metrics_handles_zero_and_non_finite_slots_without_nan() {
        let mut slots = vec![0.0; LEGACY_FINGERPRINT_LEN];
        slots[0] = f32::NAN;
        slots[1] = f32::INFINITY;
        slots[24] = 0.88;

        let typed = SpectralFingerprintV1::from_legacy_slots(&slots).unwrap();
        let metrics = typed.denominator_metrics();

        assert_eq!(typed.eigenvalues, [0.0; 8]);
        assert_eq!(metrics.policy, SPECTRAL_DENOMINATOR_POLICY);
        assert_eq!(metrics.active_mode_capacity, 1);
        assert_eq!(metrics.effective_dimensionality, 0.0);
        assert_eq!(metrics.distinguishability_loss, 1.0);
        assert_eq!(metrics.lambda1_energy_share, 0.0);
        assert!(metrics.spectral_entropy.is_finite());
    }
}
