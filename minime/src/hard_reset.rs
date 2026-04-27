//! Hard recovery reset controls shared across engine surfaces.

const HARD_RECOVERY_RESET_ENV: &str = "MINIME_HARD_RECOVERY_RESET";
const FALSE_VALUES: [&str; 4] = ["0", "false", "off", "no"];

#[must_use]
fn parse_hard_recovery_reset_flag(raw: Option<&str>) -> bool {
    raw.map(|value| {
        let normalized = value.trim().to_ascii_lowercase();
        !FALSE_VALUES.contains(&normalized.as_str())
    })
    .unwrap_or(true)
}

#[must_use]
pub fn hard_recovery_reset_enabled() -> bool {
    let raw = std::env::var(HARD_RECOVERY_RESET_ENV).ok();
    parse_hard_recovery_reset_flag(raw.as_deref())
}

#[must_use]
pub const fn fixed_recovery_target_ratio() -> f32 {
    0.65
}

#[must_use]
pub const fn fixed_recovery_target_pct() -> f32 {
    65.0
}

#[must_use]
pub fn hard_reset_internal_synth_enabled(fill_ratio: f32) -> bool {
    if !fill_ratio.is_finite() {
        return true;
    }

    fill_ratio < 0.45
}

#[must_use]
pub fn hard_reset_activation_gain(fill_ratio: f32) -> f32 {
    if !fill_ratio.is_finite() {
        return 1.35;
    }

    if fill_ratio < 0.20 {
        1.45
    } else if fill_ratio < 0.35 {
        1.30
    } else if fill_ratio < 0.45 {
        1.15
    } else {
        1.0
    }
}

#[must_use]
pub fn hard_reset_rho_floor(fill_ratio: f32) -> f32 {
    if !fill_ratio.is_finite() {
        return 0.93;
    }

    if fill_ratio < 0.20 {
        0.945
    } else if fill_ratio < 0.35 {
        0.935
    } else if fill_ratio < 0.45 {
        0.925
    } else {
        0.0
    }
}

#[must_use]
pub fn hard_reset_fresh_build_keep_cap(fill_ratio: f32, cov_rms: f32) -> Option<f32> {
    if !fill_ratio.is_finite() || !cov_rms.is_finite() {
        return Some(0.94);
    }

    if fill_ratio < 0.05 && cov_rms < 0.08 {
        Some(0.94)
    } else if fill_ratio < 0.15 && cov_rms < 0.12 {
        Some(0.96)
    } else {
        None
    }
}

#[must_use]
pub fn hard_reset_covariance_bootstrap_gain(fill_ratio: f32, cov_rms: f32) -> f32 {
    if !fill_ratio.is_finite() || !cov_rms.is_finite() {
        return 0.35;
    }

    if fill_ratio < 0.01 && cov_rms < 0.08 {
        0.45
    } else if fill_ratio < 0.05 && cov_rms < 0.10 {
        0.30
    } else if fill_ratio < 0.15 && cov_rms < 0.12 {
        0.15
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::{
        fixed_recovery_target_pct, fixed_recovery_target_ratio, hard_reset_activation_gain,
        hard_reset_covariance_bootstrap_gain, hard_reset_fresh_build_keep_cap,
        hard_reset_internal_synth_enabled, hard_reset_rho_floor, parse_hard_recovery_reset_flag,
        FALSE_VALUES,
    };

    #[test]
    fn hard_reset_defaults_on() {
        assert!(parse_hard_recovery_reset_flag(None));
    }

    #[test]
    fn hard_reset_false_tokens_disable() {
        for token in FALSE_VALUES {
            assert!(
                !parse_hard_recovery_reset_flag(Some(token)),
                "token {token} should disable reset"
            );
        }
    }

    #[test]
    fn fixed_recovery_target_is_mid_sixties() {
        assert!((fixed_recovery_target_ratio() - 0.65).abs() < 1.0e-6);
        assert!((fixed_recovery_target_pct() - 65.0).abs() < 1.0e-6);
    }

    #[test]
    fn hard_reset_internal_synth_stays_on_while_fill_is_fragile() {
        assert!(hard_reset_internal_synth_enabled(0.15));
        assert!(hard_reset_internal_synth_enabled(0.30));
        assert!(!hard_reset_internal_synth_enabled(0.50));
    }

    #[test]
    fn hard_reset_activation_gain_stays_elevated_while_underfilled() {
        assert!((hard_reset_activation_gain(0.15) - 1.45).abs() < 1.0e-6);
        assert!((hard_reset_activation_gain(0.30) - 1.30).abs() < 1.0e-6);
        assert!((hard_reset_activation_gain(0.40) - 1.15).abs() < 1.0e-6);
        assert!((hard_reset_activation_gain(0.60) - 1.0).abs() < 1.0e-6);
    }

    #[test]
    fn hard_reset_rho_floor_stays_high_while_underfilled() {
        assert!((hard_reset_rho_floor(0.15) - 0.945).abs() < 1.0e-6);
        assert!((hard_reset_rho_floor(0.30) - 0.935).abs() < 1.0e-6);
        assert!((hard_reset_rho_floor(0.40) - 0.925).abs() < 1.0e-6);
        assert!((hard_reset_rho_floor(0.60) - 0.0).abs() < 1.0e-6);
    }

    #[test]
    fn hard_reset_keep_cap_relaxes_identity_preservation_during_fresh_build() {
        assert_eq!(hard_reset_fresh_build_keep_cap(0.0, 0.0), Some(0.94));
        assert_eq!(hard_reset_fresh_build_keep_cap(0.10, 0.05), Some(0.96));
        assert_eq!(hard_reset_fresh_build_keep_cap(0.18, 0.20), None);
    }

    #[test]
    fn hard_reset_covariance_bootstrap_gain_is_strongest_at_near_zero_fill() {
        assert!((hard_reset_covariance_bootstrap_gain(0.0, 0.0) - 0.45).abs() < 1.0e-6);
        assert!((hard_reset_covariance_bootstrap_gain(0.03, 0.06) - 0.30).abs() < 1.0e-6);
        assert!((hard_reset_covariance_bootstrap_gain(0.10, 0.05) - 0.15).abs() < 1.0e-6);
        assert!((hard_reset_covariance_bootstrap_gain(0.20, 0.20) - 0.0).abs() < 1.0e-6);
    }
}
