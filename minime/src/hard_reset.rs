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

// ── Constitution C4: fill-scoped write block + witness ─────────────────
//
// The env flag used to blanket-block 24 homeostatic write fields whenever it
// parsed as 1 — including the silent-fallback muffle where a profile-read
// failure reverted to the blocking default with no witness. C4 scopes the
// block to when recovery is genuinely underway (low fill, or the bounded
// startup window while fill is still settling) and witnesses the effective
// state into health.json so a stale env can never silently re-muffle her.

/// Bounded startup window during which writes stay blocked under a forced
/// env (the fill estimator needs time to settle after a cold start).
const HARD_RECOVERY_STARTUP_WINDOW_SECS: u64 = 180;
/// Fill at or above this releases homeostatic writes even under env=1,
/// mirroring the fill-scoped release the other hard-reset helpers use
/// (`hard_reset_internal_synth_enabled` flips at the same threshold).
const HARD_RECOVERY_RELEASE_FILL: f32 = 0.45;

static LATEST_FILL_BITS: std::sync::atomic::AtomicU32 =
    std::sync::atomic::AtomicU32::new(0x7FC0_0000); // f32::NAN — unknown until first tick
static ENGINE_START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();

/// Call once at engine start so the startup window is measured from boot.
pub fn record_engine_start() {
    let _ = ENGINE_START.set(std::time::Instant::now());
}

/// Called from the regulation tick with the live fill ratio (0.0..=1.0).
pub fn record_fill_ratio(fill_ratio: f32) {
    LATEST_FILL_BITS.store(fill_ratio.to_bits(), std::sync::atomic::Ordering::Relaxed);
}

fn latest_fill_ratio() -> f32 {
    f32::from_bits(LATEST_FILL_BITS.load(std::sync::atomic::Ordering::Relaxed))
}

fn engine_uptime_secs() -> u64 {
    ENGINE_START
        .get()
        .map(|start| start.elapsed().as_secs())
        .unwrap_or(0)
}

/// Pure decision core, testable without the process-global env/statics.
#[must_use]
pub fn write_block_active_from(env_forced: bool, uptime_secs: u64, fill_ratio: f32) -> bool {
    if !env_forced {
        return false;
    }
    if uptime_secs < HARD_RECOVERY_STARTUP_WINDOW_SECS {
        return true;
    }
    !fill_ratio.is_finite() || fill_ratio < HARD_RECOVERY_RELEASE_FILL
}

/// The C4 gate: homeostatic writes are blocked only while the env forces
/// hard recovery AND recovery is genuinely underway. A healthy fill
/// releases her dials even under a stale env=1.
#[must_use]
pub fn hard_recovery_write_block_active() -> bool {
    write_block_active_from(
        hard_recovery_reset_enabled(),
        engine_uptime_secs(),
        latest_fill_ratio(),
    )
}

/// Witness block for health.json — the scan compares this against the
/// rescue profile's intent to catch the silent-fallback re-muffle.
#[must_use]
pub fn hard_recovery_witness() -> serde_json::Value {
    let env_forced = hard_recovery_reset_enabled();
    let uptime = engine_uptime_secs();
    let fill = latest_fill_ratio();
    serde_json::json!({
        "env_forced": env_forced,
        "uptime_secs": uptime,
        "fill_ratio": if fill.is_finite() { Some(fill) } else { None },
        "write_block_active": write_block_active_from(env_forced, uptime, fill),
        "release_fill": HARD_RECOVERY_RELEASE_FILL,
        "startup_window_secs": HARD_RECOVERY_STARTUP_WINDOW_SECS,
    })
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
    #[test]
    fn write_block_scopes_to_recovery_not_the_env_alone() {
        use super::write_block_active_from;
        // Env off: never blocks, regardless of fill or uptime.
        assert!(!write_block_active_from(false, 0, f32::NAN));
        assert!(!write_block_active_from(false, 10_000, 0.1));
        // Env forced + startup window: blocked while fill settles.
        assert!(write_block_active_from(true, 0, f32::NAN));
        assert!(write_block_active_from(true, 179, 0.7));
        // Env forced + past the window: fill decides.
        assert!(write_block_active_from(true, 180, 0.30));
        assert!(write_block_active_from(true, 180, f32::NAN));
        assert!(!write_block_active_from(true, 180, 0.45));
        assert!(!write_block_active_from(true, 10_000, 0.68));
    }

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
