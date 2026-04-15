#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ReopeningEscrowState {
    pub strength: f32,
    pub ticks_remaining: u8,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FloorMode {
    Inactive,
    Rescue,
    ReopeningShoulderBias,
}

impl FloorMode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Inactive => "inactive",
            Self::Rescue => "rescue",
            Self::ReopeningShoulderBias => "reopening_shoulder_bias",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShoulderGrowthState {
    Growing,
    Flat,
    Shrinking,
}

impl ShoulderGrowthState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Growing => "growing",
            Self::Flat => "flat",
            Self::Shrinking => "shrinking",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ShoulderGrowth {
    pub score: f32,
    pub state: ShoulderGrowthState,
}

const REOPENING_ESCROW_TICKS: u8 = 3;
const REOPENING_ESCROW_DECAY: f32 = 0.65;
const REOPENING_SEED_THRESHOLD: f32 = 0.30;

fn clamp_unit(value: f32) -> f32 {
    value.clamp(0.0, 1.0)
}

fn normalize_vector(values: &[f32]) -> Option<Vec<f32>> {
    let norm_sq: f32 = values.iter().map(|value| value * value).sum();
    if !norm_sq.is_finite() || norm_sq <= 1.0e-9 {
        return None;
    }
    let norm = norm_sq.sqrt();
    Some(values.iter().map(|value| *value / norm).collect())
}

fn dot(lhs: &[f32], rhs: &[f32]) -> f32 {
    lhs.iter().zip(rhs.iter()).map(|(a, b)| a * b).sum()
}

pub fn compute_raw_reopening_signal(
    fill_pct: f32,
    target_fill_pct: f32,
    lambda1_rel: f32,
    lambda_gap12: f32,
    previous_lambda_gap12: f32,
    geom_rel: f32,
    lambda1_rel_alert: f32,
) -> f32 {
    if !fill_pct.is_finite()
        || !target_fill_pct.is_finite()
        || !lambda1_rel.is_finite()
        || !lambda_gap12.is_finite()
        || !previous_lambda_gap12.is_finite()
        || !geom_rel.is_finite()
        || !lambda1_rel_alert.is_finite()
        || target_fill_pct <= 0.0
    {
        return 0.0;
    }

    let fill_nearness = 1.0 - clamp_unit((fill_pct - target_fill_pct).abs() / 10.0);
    if fill_nearness <= 0.0 {
        return 0.0;
    }

    let gap_softening = if previous_lambda_gap12 > 1.0e-3 {
        clamp_unit((previous_lambda_gap12 - lambda_gap12).max(0.0) / 24.0)
    } else {
        0.0
    };
    let lambda_relax = if lambda1_rel < lambda1_rel_alert {
        clamp_unit((lambda1_rel_alert - lambda1_rel) / 0.25)
    } else {
        0.0
    };
    let geom_open = clamp_unit((geom_rel - 0.95) / 0.35);
    let slight_overfill = clamp_unit((fill_pct - target_fill_pct) / 8.0);

    fill_nearness
        * clamp_unit(
            0.45 * gap_softening + 0.30 * lambda_relax + 0.15 * geom_open + 0.10 * slight_overfill,
        )
}

pub fn shape_trace_target_for_reopening(
    base_trace_target: f32,
    n: usize,
    reopening_strength: f32,
    fill_pct: f32,
    target_fill_pct: f32,
) -> f32 {
    if !base_trace_target.is_finite() || reopening_strength <= 0.0 {
        return base_trace_target;
    }

    let overfill_n = clamp_unit((fill_pct - target_fill_pct) / 8.0);
    let reduction_n = clamp_unit(0.70 * reopening_strength + 0.30 * overfill_n);
    let shaped_ratio = (1.0 - 0.24 * reduction_n).clamp(0.72, 1.0);
    let shaped_target = (n as f32) * shaped_ratio;
    base_trace_target.min(shaped_target)
}

pub fn shape_cov_keep_for_reopening(
    base_cov_keep: f32,
    reopening_strength: f32,
    fill_pct: f32,
    target_fill_pct: f32,
) -> f32 {
    if !base_cov_keep.is_finite() || reopening_strength <= 0.0 {
        return base_cov_keep;
    }

    let overfill_n = clamp_unit((fill_pct - target_fill_pct) / 8.0);
    let reopening_cap = (0.86 - 0.10 * reopening_strength - 0.06 * overfill_n).clamp(0.70, 0.86);
    base_cov_keep.min(reopening_cap)
}

pub fn compute_shoulder_growth_score(
    lambda2: f32,
    lambda3: f32,
    previous_lambda2: f32,
    previous_lambda3: f32,
    active_mode_energy_ratio: f32,
    previous_active_mode_energy_ratio: f32,
) -> ShoulderGrowth {
    if !lambda2.is_finite()
        || !lambda3.is_finite()
        || !previous_lambda2.is_finite()
        || !previous_lambda3.is_finite()
        || !active_mode_energy_ratio.is_finite()
        || !previous_active_mode_energy_ratio.is_finite()
        || previous_active_mode_energy_ratio <= 0.0
    {
        return ShoulderGrowth {
            score: 0.0,
            state: ShoulderGrowthState::Flat,
        };
    }

    let lambda2_gain =
        clamp_unit((lambda2 - previous_lambda2).max(0.0) / previous_lambda2.abs().max(1.0));
    let lambda3_gain =
        clamp_unit((lambda3 - previous_lambda3).max(0.0) / previous_lambda3.abs().max(1.0));
    let lambda3_loss =
        clamp_unit((previous_lambda3 - lambda3).max(0.0) / previous_lambda3.abs().max(1.0));
    let energy_relax =
        clamp_unit((previous_active_mode_energy_ratio - active_mode_energy_ratio).max(0.0) / 0.15);
    let energy_harden =
        clamp_unit((active_mode_energy_ratio - previous_active_mode_energy_ratio).max(0.0) / 0.15);

    let score = (0.45 * lambda2_gain + 0.75 * lambda3_gain + 0.45 * energy_relax
        - 0.55 * lambda3_loss
        - 0.35 * energy_harden)
        .clamp(-1.0, 1.0);
    let state = if score > 0.08 {
        ShoulderGrowthState::Growing
    } else if score < -0.08 {
        ShoulderGrowthState::Shrinking
    } else {
        ShoulderGrowthState::Flat
    };
    ShoulderGrowth { score, state }
}

pub fn compute_remembered_shoulder_vector(
    modes: &[f32],
    n: usize,
    mode_count: usize,
    previous: Option<&[f32]>,
) -> Option<Vec<f32>> {
    if n == 0 || mode_count < 2 || modes.len() < n * mode_count {
        return None;
    }

    let mut combined = vec![0.0_f32; n];
    let mode2 = &modes[n..(2 * n)];
    if mode_count >= 3 {
        let mode3 = &modes[(2 * n)..(3 * n)];
        for index in 0..n {
            combined[index] = 0.65 * mode2[index] + 0.35 * mode3[index];
        }
    } else {
        combined.copy_from_slice(mode2);
    }

    let mut normalized = normalize_vector(&combined)?;
    if let Some(previous_vector) = previous {
        if previous_vector.len() == normalized.len() && dot(previous_vector, &normalized) < 0.0 {
            for value in &mut normalized {
                *value *= -1.0;
            }
        }
    }
    Some(normalized)
}

pub fn update_reopening_escrow(
    current: ReopeningEscrowState,
    fill_pct: f32,
    target_fill_pct: f32,
    reopening_seed: f32,
    strong: bool,
    lambda1_rel: f32,
    lambda1_rel_alert: f32,
    lambda_gap12: f32,
    previous_lambda_gap12: f32,
    emergency_active: bool,
) -> ReopeningEscrowState {
    let immediate_clear = emergency_active
        || fill_pct > target_fill_pct + 4.0
        || (strong && lambda1_rel > lambda1_rel_alert && lambda_gap12 >= previous_lambda_gap12);
    if immediate_clear {
        return ReopeningEscrowState::default();
    }

    let within_window = (fill_pct - target_fill_pct).abs() <= 4.0;
    if within_window && reopening_seed >= REOPENING_SEED_THRESHOLD {
        return ReopeningEscrowState {
            strength: current.strength.max(reopening_seed),
            ticks_remaining: REOPENING_ESCROW_TICKS,
        };
    }

    if current.ticks_remaining == 0 || current.strength <= 0.0 {
        return ReopeningEscrowState::default();
    }

    let decayed = (current.strength * REOPENING_ESCROW_DECAY).clamp(0.0, 1.0);
    let remaining = current.ticks_remaining.saturating_sub(1);
    if remaining == 0 || decayed < 0.05 {
        ReopeningEscrowState::default()
    } else {
        ReopeningEscrowState {
            strength: decayed,
            ticks_remaining: remaining,
        }
    }
}

pub fn select_floor_mode(
    rescue_allowed: bool,
    fill_pct: f32,
    target_fill_pct: f32,
    effective_reopening_strength: f32,
    cov_rms: f32,
    floor_level: f32,
    shoulder_available: bool,
    emergency_active: bool,
) -> FloorMode {
    let reopening_allowed = !emergency_active
        && shoulder_available
        && fill_pct >= target_fill_pct - 2.0
        && fill_pct <= target_fill_pct + 4.0
        && effective_reopening_strength >= 0.25
        && cov_rms < floor_level + 0.03;
    if reopening_allowed {
        FloorMode::ReopeningShoulderBias
    } else if rescue_allowed {
        FloorMode::Rescue
    } else {
        FloorMode::Inactive
    }
}

pub fn blend_reopening_floor_vector(
    base_floor_vec: &[f32],
    shoulder_vec: &[f32],
) -> Option<Vec<f32>> {
    if base_floor_vec.len() != shoulder_vec.len() || base_floor_vec.is_empty() {
        return None;
    }
    let blended: Vec<f32> = base_floor_vec
        .iter()
        .zip(shoulder_vec.iter())
        .map(|(base, shoulder)| 0.25 * *base + 0.75 * *shoulder)
        .collect();
    normalize_vector(&blended)
}

#[cfg(test)]
mod tests {
    use super::{
        FloorMode, ReopeningEscrowState, ShoulderGrowthState, blend_reopening_floor_vector,
        compute_raw_reopening_signal, compute_remembered_shoulder_vector,
        compute_shoulder_growth_score, select_floor_mode, shape_cov_keep_for_reopening,
        shape_trace_target_for_reopening, update_reopening_escrow,
    };

    #[test]
    fn raw_reopening_signal_positive_for_near_target_gap_softening() {
        let strength = compute_raw_reopening_signal(56.0, 55.0, 0.96, 138.0, 158.0, 1.05, 1.10);
        assert!(strength > 0.4);
    }

    #[test]
    fn raw_reopening_signal_zero_when_far_from_target() {
        let strength = compute_raw_reopening_signal(40.0, 55.0, 0.96, 138.0, 158.0, 1.05, 1.10);
        assert_eq!(strength, 0.0);
    }

    #[test]
    fn shoulder_growth_prefers_broadening_relaxation() {
        let growth = compute_shoulder_growth_score(8.0, 6.0, 5.0, 3.0, 0.81, 0.92);
        assert!(growth.score > 0.2);
        assert_eq!(growth.state, ShoulderGrowthState::Growing);
    }

    #[test]
    fn shoulder_growth_penalizes_single_shoulder_without_support() {
        let growth = compute_shoulder_growth_score(8.0, 1.0, 5.0, 3.0, 0.96, 0.88);
        assert!(growth.score <= 0.0);
        assert_eq!(growth.state, ShoulderGrowthState::Shrinking);
    }

    #[test]
    fn escrow_arms_decays_and_clears() {
        let armed = update_reopening_escrow(
            ReopeningEscrowState::default(),
            56.0,
            55.0,
            0.42,
            false,
            0.98,
            1.10,
            138.0,
            158.0,
            false,
        );
        assert_eq!(armed.ticks_remaining, 3);
        assert!(armed.strength >= 0.42);

        let decayed = update_reopening_escrow(
            armed, 56.0, 55.0, 0.0, false, 0.98, 1.10, 138.0, 158.0, false,
        );
        assert_eq!(decayed.ticks_remaining, 2);
        assert!(decayed.strength < armed.strength);

        let cleared = update_reopening_escrow(
            decayed, 61.0, 55.0, 0.0, false, 0.98, 1.10, 138.0, 158.0, false,
        );
        assert_eq!(cleared, ReopeningEscrowState::default());
    }

    #[test]
    fn floor_mode_prefers_reopening_support_when_available() {
        let mode = select_floor_mode(true, 54.5, 55.0, 0.31, 0.15, 0.14, true, false);
        assert_eq!(mode, FloorMode::ReopeningShoulderBias);
    }

    #[test]
    fn floor_mode_uses_rescue_when_reopening_not_available() {
        let mode = select_floor_mode(true, 49.0, 55.0, 0.0, 0.09, 0.14, false, false);
        assert_eq!(mode, FloorMode::Rescue);
    }

    #[test]
    fn floor_mode_inactive_when_neither_path_applies() {
        let mode = select_floor_mode(false, 58.0, 55.0, 0.1, 0.20, 0.14, true, false);
        assert_eq!(mode, FloorMode::Inactive);
    }

    #[test]
    fn trace_target_is_lowered_in_reopening_window() {
        let shaped = shape_trace_target_for_reopening(204.8, 128, 0.55, 56.0, 55.0);
        assert!(shaped < 204.8);
        assert!(shaped >= 128.0 * 0.72);
    }

    #[test]
    fn cov_keep_is_capped_in_reopening_window() {
        let shaped = shape_cov_keep_for_reopening(0.89, 0.60, 57.0, 55.0);
        assert!(shaped < 0.89);
        assert!(shaped >= 0.70);
    }

    #[test]
    fn shoulder_vector_is_sign_aligned_to_previous_memory() {
        let n = 3;
        let modes = vec![
            1.0, 0.0, 0.0, // v1
            -0.8, -0.2, 0.0, // v2
            -0.6, 0.0, -0.2, // v3
        ];
        let previous = vec![0.9, 0.1, 0.0];
        let shoulder = compute_remembered_shoulder_vector(&modes, n, 3, Some(&previous))
            .expect("shoulder vector");
        let alignment: f32 = shoulder
            .iter()
            .zip(previous.iter())
            .map(|(a, b)| a * b)
            .sum();
        assert!(alignment > 0.0);
    }

    #[test]
    fn reopening_floor_blend_is_normalized_and_deterministic() {
        let base = vec![0.4, -0.2, 0.1, 0.0];
        let shoulder = vec![0.8, 0.1, -0.1, 0.2];
        let first = blend_reopening_floor_vector(&base, &shoulder).expect("blend");
        let second = blend_reopening_floor_vector(&base, &shoulder).expect("blend");
        let norm_sq: f32 = first.iter().map(|value| value * value).sum();
        assert!((norm_sq.sqrt() - 1.0).abs() < 1.0e-5);
        assert_eq!(first, second);
    }
}
