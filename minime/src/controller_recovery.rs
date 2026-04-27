//! Focused controller tuning helpers for recovery windows.

/// The adaptive target floor should never exceed the operator-requested target.
///
/// Golden-reset logic historically clamped the adaptive target to a hard 40% floor,
/// which made a deliberate lower recovery target impossible. Keep a safety floor, but
/// honor lower operator targets when they are explicitly requested.
#[must_use]
pub fn adaptive_target_floor(cli_target_pct: f32) -> f32 {
    cli_target_pct.clamp(25.0, 40.0)
}

/// Fill zone where extra covariance protection is still appropriate.
///
/// The historical recovery band was fixed at 50%, which over-protected low-target
/// recovery runs and kept retention too high well above the requested setpoint.
#[must_use]
pub fn recovery_fill_threshold(target_fill_pct: f32) -> f32 {
    ((target_fill_pct / 100.0) + 0.10).clamp(0.35, 0.50)
}

/// Extra covariance retention while fill is still below the active recovery band.
#[must_use]
pub fn recovery_fill_boost(fill_ratio: f32, target_fill_pct: f32) -> f32 {
    (recovery_fill_threshold(target_fill_pct) - fill_ratio).max(0.0) * 0.50
}

/// Base covariance keep floor before dominance and fill adjustments.
///
/// Golden-reset defaults were tuned around a mid-50s operating point. If the
/// operator explicitly requests a lower fill target for recovery, the keep floor
/// needs to relax accordingly or the controller keeps over-retaining covariance.
#[must_use]
pub fn recovery_keep_floor_base(target_fill_pct: f32) -> f32 {
    let relief = ((50.0 - target_fill_pct).max(0.0) / 15.0).clamp(0.0, 1.0);
    0.93 - 0.06 * relief
}

/// Ceiling on covariance retention while the system is still below the recovery band.
#[must_use]
pub fn recovery_keep_ceiling(fill_ratio: f32, target_fill_pct: f32) -> f32 {
    let threshold = recovery_fill_threshold(target_fill_pct);
    if fill_ratio >= threshold {
        0.97
    } else {
        let t = (fill_ratio / threshold.max(1.0e-6)).clamp(0.0, 1.0);
        0.998 - t * (0.998 - 0.97)
    }
}

/// Minimum synthetic sensory drive to preserve during hard recovery reset.
///
/// Hard recovery already reopens gate/filter aggressively. If synthetic drive
/// is allowed to collapse to the global floor at the same time, the reopened
/// controller has very little actual energy to work with. Keep a stronger
/// drive floor while fill is fragile, then taper it back down once recovery
/// has real headroom.
#[must_use]
pub fn hard_reset_synth_gain_floor(fill_ratio: f32) -> f32 {
    if !fill_ratio.is_finite() {
        return 0.85;
    }

    if fill_ratio < 0.20 {
        1.00
    } else if fill_ratio < 0.35 {
        0.85
    } else if fill_ratio < 0.45 {
        0.65
    } else {
        0.45
    }
}

/// Slightly relax covariance retention when an underfilled recovery window is
/// already showing real shoulder/entropy support.
///
/// This does not try to create widening out of nothing. It only protects the
/// first signs of distribution so the controller is less likely to immediately
/// reconcentrate back into the same dominant mode.
#[must_use]
pub fn underfill_spread_relief(
    fill_ratio: f32,
    target_fill_pct: f32,
    spectral_entropy: f32,
    lambda1_share: f32,
    geom_rel: f32,
) -> f32 {
    if !fill_ratio.is_finite()
        || !spectral_entropy.is_finite()
        || !lambda1_share.is_finite()
        || !geom_rel.is_finite()
    {
        return 0.0;
    }

    let threshold = recovery_fill_threshold(target_fill_pct);
    if fill_ratio >= threshold {
        return 0.0;
    }

    let entropy_support = ((spectral_entropy - 0.30) / 0.08).clamp(0.0, 1.0);
    let shoulder_support = ((0.88 - lambda1_share) / 0.10).clamp(0.0, 1.0);
    let support = entropy_support.max(shoulder_support);
    if support <= 0.0 {
        return 0.0;
    }

    let underfill_support = (0.40
        + ((threshold - fill_ratio) / threshold.max(1.0e-6)).clamp(0.0, 1.0) * 0.60)
        .clamp(0.40, 1.0);
    let geom_support = ((geom_rel - 0.85) / 0.35).clamp(0.0, 1.0);
    let geom_factor = (0.35 + 0.65 * geom_support).clamp(0.35, 1.0);

    (0.06 * support * underfill_support * geom_factor).clamp(0.0, 0.06)
}

/// Semantic projection bias should only add a floor when there is actual semantic activity.
///
/// In silent engine-only runs, an unconditional positive floor on the semantic
/// projection dims creates self-sustaining covariance input even when the semantic
/// lane is completely empty. Keep the gentle floor for real semantic traces, but
/// return zero when both energy and delta are effectively absent.
#[must_use]
pub fn semantic_projection_bias(
    semantic_bias_floor: f32,
    semantic_energy_gain: f32,
    semantic_energy: f32,
    semantic_delta_gain: f32,
    semantic_delta: f32,
) -> f32 {
    let energy = if semantic_energy.is_finite() {
        semantic_energy.max(0.0)
    } else {
        0.0
    };
    let delta = if semantic_delta.is_finite() {
        semantic_delta.max(0.0)
    } else {
        0.0
    };
    let semantic_drive = semantic_energy_gain * energy + semantic_delta_gain * delta;

    if semantic_drive <= 1.0e-6 {
        0.0
    } else {
        (semantic_bias_floor + semantic_drive).clamp(-0.75, 0.75)
    }
}

/// Treat the semantic lane as inactive unless there is fresh semantic state
/// still within the active stale window.
#[must_use]
pub fn semantic_lane_is_active(semantic_fresh_ms: Option<u64>, semantic_stale_ms: u64) -> bool {
    semantic_fresh_ms.is_some_and(|age_ms| age_ms <= semantic_stale_ms)
}

/// A projection tick is only meaningfully "fed" when at least one external or
/// decayed sensory lane still has signal, or when the semantic lane is active.
#[must_use]
pub fn projection_has_signal(
    had_video: bool,
    had_audio: bool,
    video_source_present: bool,
    audio_source_present: bool,
    semantic_lane_active: bool,
) -> bool {
    had_video || had_audio || video_source_present || audio_source_present || semantic_lane_active
}

#[cfg(test)]
mod tests {
    use super::{
        adaptive_target_floor, hard_reset_synth_gain_floor, projection_has_signal,
        recovery_fill_boost, recovery_fill_threshold, recovery_keep_ceiling,
        recovery_keep_floor_base, semantic_lane_is_active, semantic_projection_bias,
        underfill_spread_relief,
    };

    #[test]
    fn adaptive_target_floor_honors_lower_operator_target() {
        assert!((adaptive_target_floor(35.0) - 35.0).abs() < 1.0e-6);
        assert!((adaptive_target_floor(40.0) - 40.0).abs() < 1.0e-6);
        assert!((adaptive_target_floor(55.0) - 40.0).abs() < 1.0e-6);
    }

    #[test]
    fn recovery_threshold_shrinks_for_low_target_runs() {
        assert!((recovery_fill_threshold(55.0) - 0.50).abs() < 1.0e-6);
        assert!((recovery_fill_threshold(35.0) - 0.45).abs() < 1.0e-6);
    }

    #[test]
    fn recovery_fill_boost_turns_off_after_threshold() {
        assert!(recovery_fill_boost(0.40, 35.0) > 0.0);
        assert!((recovery_fill_boost(0.46, 35.0) - 0.0).abs() < 1.0e-6);
        assert!((recovery_fill_boost(0.51, 55.0) - 0.0).abs() < 1.0e-6);
    }

    #[test]
    fn recovery_keep_ceiling_relaxes_once_above_recovery_band() {
        assert!(recovery_keep_ceiling(0.30, 35.0) > 0.97);
        assert!((recovery_keep_ceiling(0.46, 35.0) - 0.97).abs() < 1.0e-6);
        assert!((recovery_keep_ceiling(0.55, 55.0) - 0.97).abs() < 1.0e-6);
    }

    #[test]
    fn recovery_keep_floor_base_relaxes_for_lower_targets() {
        assert!((recovery_keep_floor_base(55.0) - 0.93).abs() < 1.0e-6);
        assert!(recovery_keep_floor_base(35.0) < recovery_keep_floor_base(55.0));
        assert!((recovery_keep_floor_base(35.0) - 0.87).abs() < 1.0e-6);
    }

    #[test]
    fn hard_reset_synth_gain_floor_stays_strong_when_fill_is_fragile() {
        assert!((hard_reset_synth_gain_floor(0.15) - 1.00).abs() < 1.0e-6);
        assert!((hard_reset_synth_gain_floor(0.30) - 0.85).abs() < 1.0e-6);
        assert!((hard_reset_synth_gain_floor(0.40) - 0.65).abs() < 1.0e-6);
        assert!((hard_reset_synth_gain_floor(0.60) - 0.45).abs() < 1.0e-6);
    }

    #[test]
    fn underfill_spread_relief_stays_off_without_distribution_support() {
        let relief = underfill_spread_relief(0.18, 40.0, 0.29, 0.90, 0.80);
        assert!((relief - 0.0).abs() < 1.0e-6);
    }

    #[test]
    fn underfill_spread_relief_turns_on_for_entropy_and_shoulder_growth() {
        let relief = underfill_spread_relief(0.20, 40.0, 0.34, 0.84, 1.08);
        assert!(relief > 0.0);
        assert!(relief < 0.06);
    }

    #[test]
    fn underfill_spread_relief_is_stronger_for_clearer_reopening_shape() {
        let modest = underfill_spread_relief(0.20, 40.0, 0.32, 0.86, 0.95);
        let stronger = underfill_spread_relief(0.20, 40.0, 0.38, 0.80, 1.18);
        assert!(stronger > modest);
    }

    #[test]
    fn semantic_projection_bias_turns_off_when_semantic_lane_is_silent() {
        assert_eq!(semantic_projection_bias(0.010, 0.028, 0.0, 0.045, 0.0), 0.0);
        assert_eq!(
            semantic_projection_bias(0.010, 0.028, f32::NAN, 0.045, f32::NAN),
            0.0
        );
    }

    #[test]
    fn semantic_projection_bias_preserves_floor_for_real_semantic_activity() {
        let bias = semantic_projection_bias(0.010, 0.028, 0.25, 0.045, 0.10);
        assert!(bias > 0.010);
        assert!(bias <= 0.75);
    }

    #[test]
    fn semantic_lane_requires_fresh_semantic_state() {
        assert!(!semantic_lane_is_active(None, 30_000));
        assert!(semantic_lane_is_active(Some(15_000), 30_000));
        assert!(!semantic_lane_is_active(Some(45_000), 30_000));
    }

    #[test]
    fn projection_requires_actual_lane_activity() {
        assert!(!projection_has_signal(false, false, false, false, false));
        assert!(projection_has_signal(false, false, true, false, false));
        assert!(projection_has_signal(false, false, false, false, true));
    }
}
