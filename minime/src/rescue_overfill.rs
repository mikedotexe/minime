#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverfillStage {
    Bootstrap,
    Recovery,
    Hold,
    Elevated,
    Discharge,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OverfillGuard {
    pub stage: OverfillStage,
    pub suppress_semantic_amplification: bool,
    pub gate_min: Option<f32>,
    pub gate_max: Option<f32>,
    pub filt_max: Option<f32>,
    pub filt_min: Option<f32>,
    pub cov_keep_min: Option<f32>,
    pub cov_keep_max: Option<f32>,
    pub target_keep: Option<f32>,
    pub keep_floor: Option<f32>,
    pub keep_ceil: Option<f32>,
    pub trace_target_scale: Option<f32>,
    pub decay_only: bool,
    pub reset_pi: bool,
    pub freeze_pi: bool,
    pub integrator_decay: Option<f32>,
    pub shed_fraction: f32,
    pub live_intake_divisor: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CrisisState {
    pub ticks: u32,
    pub warning_started: bool,
    pub triggered: bool,
    pub recovered: bool,
}

pub const BOOTSTRAP_ENTRY_THRESHOLD: f32 = 35.0;
pub const BOOTSTRAP_RELEASE_THRESHOLD: f32 = 42.0;
pub const HOLD_ENTRY_THRESHOLD: f32 = 60.0;
pub const HOLD_RELEASE_THRESHOLD: f32 = 58.0;
pub const ELEVATED_ENTRY_THRESHOLD: f32 = 72.0;
pub const ELEVATED_RELEASE_THRESHOLD: f32 = 71.5;
pub const FORCE_RAIL_THRESHOLD: f32 = 78.0;
pub const DISCHARGE_ENTRY_THRESHOLD: f32 = 82.0;
pub const DISCHARGE_RELEASE_THRESHOLD: f32 = 76.0;
pub const CRISIS_WARNING_THRESHOLD: f32 = FORCE_RAIL_THRESHOLD;
pub const CRISIS_FILL_THRESHOLD: f32 = 87.0;
pub const CRISIS_SUSTAIN_TICKS: u32 = 30;
pub const ELEVATED_STRONG_RAIL_THRESHOLD: f32 = 74.0;
pub const HOLD_ELEVATED_BLEND_START_PCT: f32 = ELEVATED_RELEASE_THRESHOLD;
pub const HOLD_ELEVATED_BLEND_END_PCT: f32 = ELEVATED_STRONG_RAIL_THRESHOLD;
pub const HOLD_ELEVATED_SLEW_START_PCT: f32 = 70.0;
pub const STABLE_CORE_GATE_SLEW_PER_TICK: f32 = 0.02;
pub const STABLE_CORE_FILT_SLEW_PER_TICK: f32 = 0.04;
pub const STABLE_CORE_COV_KEEP_SLEW_PER_TICK: f32 = 0.04;

#[must_use]
pub fn bootstrap_active(fill_pct: f32, currently_active: bool) -> bool {
    if currently_active {
        fill_pct < BOOTSTRAP_RELEASE_THRESHOLD
    } else {
        fill_pct < BOOTSTRAP_ENTRY_THRESHOLD
    }
}

#[must_use]
pub fn hold_active(fill_pct: f32, currently_active: bool) -> bool {
    if currently_active {
        fill_pct > HOLD_RELEASE_THRESHOLD
    } else {
        fill_pct >= HOLD_ENTRY_THRESHOLD
    }
}

#[must_use]
pub fn elevated_active(fill_pct: f32, currently_active: bool) -> bool {
    if currently_active {
        fill_pct > ELEVATED_RELEASE_THRESHOLD
    } else {
        fill_pct >= ELEVATED_ENTRY_THRESHOLD
    }
}

#[must_use]
pub fn discharge_active(fill_pct: f32, currently_active: bool) -> bool {
    if currently_active {
        fill_pct > DISCHARGE_RELEASE_THRESHOLD
    } else {
        fill_pct >= DISCHARGE_ENTRY_THRESHOLD
    }
}

#[must_use]
pub fn select_stage(fill_pct: f32, current_stage: OverfillStage) -> OverfillStage {
    if discharge_active(fill_pct, matches!(current_stage, OverfillStage::Discharge)) {
        OverfillStage::Discharge
    } else if elevated_active(
        fill_pct,
        matches!(
            current_stage,
            OverfillStage::Elevated | OverfillStage::Discharge
        ),
    ) {
        OverfillStage::Elevated
    } else if hold_active(
        fill_pct,
        matches!(
            current_stage,
            OverfillStage::Hold | OverfillStage::Elevated | OverfillStage::Discharge
        ),
    ) {
        OverfillStage::Hold
    } else if bootstrap_active(fill_pct, matches!(current_stage, OverfillStage::Bootstrap)) {
        OverfillStage::Bootstrap
    } else {
        OverfillStage::Recovery
    }
}

#[must_use]
pub fn stage_guard(stage: OverfillStage) -> OverfillGuard {
    match stage {
        OverfillStage::Bootstrap => OverfillGuard {
            stage,
            suppress_semantic_amplification: true,
            gate_min: Some(0.34),
            gate_max: Some(0.34),
            filt_max: Some(0.20),
            filt_min: Some(0.20),
            cov_keep_min: Some(0.94),
            cov_keep_max: Some(0.94),
            target_keep: Some(0.94),
            keep_floor: Some(0.94),
            keep_ceil: Some(0.94),
            trace_target_scale: Some(1.00),
            decay_only: false,
            reset_pi: true,
            freeze_pi: true,
            integrator_decay: None,
            shed_fraction: 0.0,
            live_intake_divisor: 0,
        },
        OverfillStage::Recovery => OverfillGuard {
            stage,
            suppress_semantic_amplification: true,
            gate_min: Some(0.28),
            gate_max: Some(0.28),
            filt_max: Some(0.32),
            filt_min: Some(0.32),
            cov_keep_min: Some(0.90),
            cov_keep_max: Some(0.90),
            target_keep: Some(0.90),
            keep_floor: Some(0.90),
            keep_ceil: Some(0.90),
            trace_target_scale: Some(0.92),
            decay_only: false,
            reset_pi: true,
            freeze_pi: true,
            integrator_decay: None,
            shed_fraction: 0.0,
            live_intake_divisor: 0,
        },
        OverfillStage::Hold => OverfillGuard {
            stage,
            suppress_semantic_amplification: true,
            gate_min: Some(0.12),
            gate_max: Some(0.12),
            filt_max: Some(0.72),
            filt_min: Some(0.72),
            cov_keep_min: Some(0.72),
            cov_keep_max: Some(0.72),
            target_keep: Some(0.72),
            keep_floor: Some(0.72),
            keep_ceil: Some(0.72),
            trace_target_scale: Some(0.60),
            decay_only: false,
            reset_pi: true,
            freeze_pi: true,
            integrator_decay: None,
            shed_fraction: 0.0,
            live_intake_divisor: 0,
        },
        OverfillStage::Elevated => OverfillGuard {
            stage,
            suppress_semantic_amplification: true,
            gate_min: Some(0.08),
            gate_max: Some(0.08),
            filt_max: Some(0.84),
            filt_min: Some(0.84),
            cov_keep_min: Some(0.55),
            cov_keep_max: Some(0.55),
            target_keep: Some(0.55),
            keep_floor: Some(0.55),
            keep_ceil: Some(0.55),
            trace_target_scale: Some(0.45),
            decay_only: false,
            reset_pi: true,
            freeze_pi: true,
            integrator_decay: None,
            shed_fraction: 0.0,
            live_intake_divisor: 0,
        },
        OverfillStage::Discharge => OverfillGuard {
            stage,
            suppress_semantic_amplification: true,
            gate_min: Some(0.01),
            gate_max: Some(0.01),
            filt_max: Some(1.0),
            filt_min: Some(1.0),
            cov_keep_min: Some(0.05),
            cov_keep_max: Some(0.05),
            target_keep: Some(0.04),
            keep_floor: Some(0.05),
            keep_ceil: Some(0.05),
            trace_target_scale: Some(0.05),
            decay_only: true,
            reset_pi: true,
            freeze_pi: true,
            integrator_decay: Some(0.0),
            shed_fraction: 0.0,
            live_intake_divisor: 0,
        },
    }
}

#[must_use]
pub fn stage_guard_for_state(
    stage: OverfillStage,
    fill_pct: f32,
    fill_slope_pct_per_sec: f32,
) -> OverfillGuard {
    let mut guard = stage_guard(stage);
    if matches!(stage, OverfillStage::Hold | OverfillStage::Elevated) {
        if let Some(t) = hold_elevated_blend_t(fill_pct) {
            let hold = stage_guard(OverfillStage::Hold);
            let elevated = elevated_soft_guard();
            guard.gate_min = blend_options(hold.gate_min, elevated.gate_min, t);
            guard.gate_max = blend_options(hold.gate_max, elevated.gate_max, t);
            guard.filt_min = blend_options(hold.filt_min, elevated.filt_min, t);
            guard.filt_max = blend_options(hold.filt_max, elevated.filt_max, t);
            guard.cov_keep_min = blend_options(hold.cov_keep_min, elevated.cov_keep_min, t);
            guard.cov_keep_max = blend_options(hold.cov_keep_max, elevated.cov_keep_max, t);
            guard.target_keep = blend_options(hold.target_keep, elevated.target_keep, t);
            guard.keep_floor = blend_options(hold.keep_floor, elevated.keep_floor, t);
            guard.keep_ceil = blend_options(hold.keep_ceil, elevated.keep_ceil, t);
            guard.trace_target_scale =
                blend_options(hold.trace_target_scale, elevated.trace_target_scale, t);
            return guard;
        }
    }
    if matches!(stage, OverfillStage::Elevated)
        && fill_pct.is_finite()
        && fill_slope_pct_per_sec.is_finite()
    {
        if fill_pct < ELEVATED_STRONG_RAIL_THRESHOLD {
            guard.gate_min = Some(0.10);
            guard.gate_max = Some(0.10);
            guard.filt_max = Some(0.78);
            guard.filt_min = Some(0.78);
            guard.cov_keep_min = Some(0.66);
            guard.cov_keep_max = Some(0.66);
            guard.target_keep = Some(0.66);
            guard.keep_floor = Some(0.66);
            guard.keep_ceil = Some(0.66);
            guard.trace_target_scale = Some(0.55);
        } else if fill_pct < DISCHARGE_ENTRY_THRESHOLD {
            guard.gate_min = Some(0.09);
            guard.gate_max = Some(0.09);
            guard.filt_max = Some(0.80);
            guard.filt_min = Some(0.80);
            guard.cov_keep_min = Some(0.66);
            guard.cov_keep_max = Some(0.66);
            guard.target_keep = Some(0.66);
            guard.keep_floor = Some(0.66);
            guard.keep_ceil = Some(0.66);
            guard.trace_target_scale = Some(0.55);
        }
    }
    guard
}

#[must_use]
pub fn stable_core_command_slew_active(stage: OverfillStage, fill_pct: f32) -> bool {
    matches!(stage, OverfillStage::Hold | OverfillStage::Elevated)
        && fill_pct.is_finite()
        && fill_pct >= HOLD_ELEVATED_SLEW_START_PCT
        && fill_pct < ELEVATED_STRONG_RAIL_THRESHOLD
}

#[must_use]
pub fn slew_value(current: f32, target: f32, max_delta: f32) -> f32 {
    if !current.is_finite() || !target.is_finite() {
        return target;
    }
    let max_delta = max_delta.abs();
    current + (target - current).clamp(-max_delta, max_delta)
}

#[must_use]
pub fn slew_guard_commands(
    mut guard: OverfillGuard,
    previous_gate: f32,
    previous_filt: f32,
    previous_cov_keep: f32,
) -> OverfillGuard {
    if let Some(target) = guard.gate_max.or(guard.gate_min) {
        let value = slew_value(previous_gate, target, STABLE_CORE_GATE_SLEW_PER_TICK);
        guard.gate_min = Some(value);
        guard.gate_max = Some(value);
    }
    if let Some(target) = guard.filt_min.or(guard.filt_max) {
        let value = slew_value(previous_filt, target, STABLE_CORE_FILT_SLEW_PER_TICK);
        guard.filt_min = Some(value);
        guard.filt_max = Some(value);
    }
    if let Some(target) = guard.cov_keep_max.or(guard.cov_keep_min) {
        let value = slew_value(
            previous_cov_keep,
            target,
            STABLE_CORE_COV_KEEP_SLEW_PER_TICK,
        );
        guard.cov_keep_min = Some(value);
        guard.cov_keep_max = Some(value);
        guard.target_keep = Some(value);
        guard.keep_floor = Some(value);
        guard.keep_ceil = Some(value);
    }
    guard
}

fn hold_elevated_blend_t(fill_pct: f32) -> Option<f32> {
    if fill_pct.is_finite()
        && (HOLD_ELEVATED_BLEND_START_PCT..HOLD_ELEVATED_BLEND_END_PCT).contains(&fill_pct)
    {
        Some(
            (fill_pct - HOLD_ELEVATED_BLEND_START_PCT)
                / (HOLD_ELEVATED_BLEND_END_PCT - HOLD_ELEVATED_BLEND_START_PCT),
        )
    } else {
        None
    }
}

fn elevated_soft_guard() -> OverfillGuard {
    let mut guard = stage_guard(OverfillStage::Elevated);
    guard.gate_min = Some(0.10);
    guard.gate_max = Some(0.10);
    guard.filt_max = Some(0.78);
    guard.filt_min = Some(0.78);
    guard.cov_keep_min = Some(0.66);
    guard.cov_keep_max = Some(0.66);
    guard.target_keep = Some(0.66);
    guard.keep_floor = Some(0.66);
    guard.keep_ceil = Some(0.66);
    guard.trace_target_scale = Some(0.55);
    guard
}

fn blend_options(a: Option<f32>, b: Option<f32>, t: f32) -> Option<f32> {
    match (a, b) {
        (Some(a), Some(b)) => Some(lerp(a, b, t)),
        (Some(a), None) => Some(a),
        (None, Some(b)) => Some(b),
        (None, None) => None,
    }
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    a + (b - a) * t
}

#[must_use]
pub fn advance_crisis_state(fill_pct: f32, current_ticks: u32) -> CrisisState {
    if fill_pct < CRISIS_FILL_THRESHOLD {
        return CrisisState {
            ticks: 0,
            warning_started: false,
            triggered: false,
            recovered: current_ticks > 0,
        };
    }

    let ticks = current_ticks.saturating_add(1);
    CrisisState {
        ticks,
        warning_started: ticks == 1,
        triggered: ticks >= CRISIS_SUSTAIN_TICKS,
        recovered: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bootstrap_uses_hysteresis() {
        assert!(bootstrap_active(BOOTSTRAP_ENTRY_THRESHOLD - 0.1, false));
        assert!(bootstrap_active(BOOTSTRAP_RELEASE_THRESHOLD - 0.5, true));
        assert!(!bootstrap_active(BOOTSTRAP_RELEASE_THRESHOLD, true));
    }

    #[test]
    fn hold_uses_hysteresis() {
        assert!(hold_active(HOLD_ENTRY_THRESHOLD, false));
        assert!(hold_active(HOLD_RELEASE_THRESHOLD + 0.5, true));
        assert!(!hold_active(HOLD_RELEASE_THRESHOLD, true));
    }

    #[test]
    fn elevated_and_discharge_use_release_bands() {
        assert!(elevated_active(ELEVATED_ENTRY_THRESHOLD, false));
        assert!(elevated_active(ELEVATED_RELEASE_THRESHOLD + 0.25, true));
        assert!(!elevated_active(ELEVATED_RELEASE_THRESHOLD, true));

        assert!(discharge_active(DISCHARGE_ENTRY_THRESHOLD, false));
        assert!(discharge_active(DISCHARGE_RELEASE_THRESHOLD + 0.5, true));
        assert!(!discharge_active(DISCHARGE_RELEASE_THRESHOLD, true));
    }

    #[test]
    fn stage_guard_applies_expected_fixed_stage_limits() {
        let bootstrap = stage_guard(OverfillStage::Bootstrap);
        assert_eq!(bootstrap.gate_min, Some(0.34));
        assert_eq!(bootstrap.gate_max, Some(0.34));
        assert_eq!(bootstrap.filt_min, Some(0.20));
        assert_eq!(bootstrap.cov_keep_min, Some(0.94));
        assert_eq!(bootstrap.cov_keep_max, Some(0.94));
        assert_eq!(bootstrap.target_keep, Some(0.94));
        assert_eq!(bootstrap.live_intake_divisor, 0);

        let recovery = stage_guard(OverfillStage::Recovery);
        assert_eq!(recovery.gate_min, Some(0.28));
        assert_eq!(recovery.gate_max, Some(0.28));
        assert_eq!(recovery.filt_min, Some(0.32));
        assert_eq!(recovery.cov_keep_min, Some(0.90));
        assert_eq!(recovery.cov_keep_max, Some(0.90));
        assert_eq!(recovery.target_keep, Some(0.90));
        assert!(recovery.freeze_pi);
        assert_eq!(recovery.live_intake_divisor, 0);

        let hold = stage_guard(OverfillStage::Hold);
        assert_eq!(hold.gate_min, Some(0.12));
        assert_eq!(hold.gate_max, Some(0.12));
        assert_eq!(hold.filt_max, Some(0.72));
        assert_eq!(hold.filt_min, Some(0.72));
        assert_eq!(hold.cov_keep_min, Some(0.72));
        assert_eq!(hold.cov_keep_max, Some(0.72));
        assert!(hold.freeze_pi);
        assert_eq!(hold.live_intake_divisor, 0);

        let elevated = stage_guard(OverfillStage::Elevated);
        assert_eq!(elevated.gate_min, Some(0.08));
        assert_eq!(elevated.gate_max, Some(0.08));
        assert_eq!(elevated.filt_max, Some(0.84));
        assert_eq!(elevated.filt_min, Some(0.84));
        assert_eq!(elevated.cov_keep_min, Some(0.55));
        assert_eq!(elevated.cov_keep_max, Some(0.55));
        assert_eq!(elevated.target_keep, Some(0.55));
        assert!(elevated.freeze_pi);
        assert_eq!(elevated.live_intake_divisor, 0);

        let discharge = stage_guard(OverfillStage::Discharge);
        assert_eq!(discharge.gate_min, Some(0.01));
        assert_eq!(discharge.gate_max, Some(0.01));
        assert_eq!(discharge.filt_max, Some(1.0));
        assert_eq!(discharge.filt_min, Some(1.0));
        assert_eq!(discharge.cov_keep_min, Some(0.05));
        assert_eq!(discharge.cov_keep_max, Some(0.05));
        assert_eq!(discharge.target_keep, Some(0.04));
        assert!(discharge.decay_only);
        assert!(discharge.freeze_pi);
        assert_eq!(discharge.live_intake_divisor, 0);
    }

    #[test]
    fn elevated_guard_uses_soft_transition_below_strong_rail() {
        let soft = stage_guard_for_state(OverfillStage::Elevated, 73.0, 3.0);
        assert_close(soft.gate_min.unwrap(), 0.108);
        assert_close(soft.filt_max.unwrap(), 0.756);
        assert_close(soft.cov_keep_min.unwrap(), 0.684);
        assert_close(soft.target_keep.unwrap(), 0.684);
        assert_close(soft.trace_target_scale.unwrap(), 0.57);

        let strong = stage_guard_for_state(OverfillStage::Elevated, 74.0, 0.2);
        assert_eq!(strong.gate_min, Some(0.09));
        assert_eq!(strong.filt_max, Some(0.80));
        assert_eq!(strong.cov_keep_min, Some(0.66));
        assert_eq!(strong.target_keep, Some(0.66));
        assert_eq!(strong.trace_target_scale, Some(0.55));

        let force_landing = stage_guard_for_state(OverfillStage::Elevated, 78.0, -0.2);
        assert_eq!(force_landing.gate_min, Some(0.09));
        assert_eq!(force_landing.filt_max, Some(0.80));
        assert_eq!(force_landing.cov_keep_min, Some(0.66));
        assert_eq!(force_landing.target_keep, Some(0.66));
        assert_eq!(force_landing.trace_target_scale, Some(0.55));

        let default_elevated = stage_guard(OverfillStage::Elevated);
        assert_eq!(default_elevated.gate_min, Some(0.08));
        assert_eq!(default_elevated.filt_max, Some(0.84));
        assert_eq!(default_elevated.cov_keep_min, Some(0.55));
        assert_eq!(default_elevated.target_keep, Some(0.55));
        assert_eq!(default_elevated.trace_target_scale, Some(0.45));

        let hold = stage_guard_for_state(OverfillStage::Hold, 71.0, 3.0);
        assert_eq!(hold, stage_guard(OverfillStage::Hold));
    }

    #[test]
    fn hold_elevated_boundary_blends_commands_before_strong_rail() {
        let boundary = stage_guard_for_state(OverfillStage::Hold, 71.75, -0.5);
        assert_close(boundary.gate_min.unwrap(), 0.118);
        assert_close(boundary.filt_min.unwrap(), 0.726);
        assert_close(boundary.cov_keep_min.unwrap(), 0.714);
        assert_close(boundary.target_keep.unwrap(), 0.714);

        let elevated = stage_guard_for_state(OverfillStage::Elevated, 73.75, 1.0);
        assert_close(elevated.gate_min.unwrap(), 0.102);
        assert_close(elevated.filt_min.unwrap(), 0.774);
        assert_close(elevated.cov_keep_min.unwrap(), 0.666);
        assert_close(elevated.target_keep.unwrap(), 0.666);
    }

    #[test]
    fn stable_core_command_slew_limits_boundary_output_steps() {
        let raw = stage_guard_for_state(OverfillStage::Elevated, 73.0, 3.0);
        let slewed = slew_guard_commands(raw, 0.12, 0.72, 0.72);

        assert_close(slewed.gate_min.unwrap(), 0.108);
        assert_close(slewed.filt_min.unwrap(), 0.756);
        assert_close(slewed.cov_keep_min.unwrap(), 0.684);

        let strong = stage_guard_for_state(OverfillStage::Elevated, 73.75, 3.0);
        let slewed = slew_guard_commands(strong, 0.12, 0.72, 0.72);
        assert_close(slewed.gate_min.unwrap(), 0.102);
        assert_close(slewed.filt_min.unwrap(), 0.76);
        assert_close(slewed.cov_keep_min.unwrap(), 0.68);
        assert_close(slewed.target_keep.unwrap(), 0.68);
    }

    #[test]
    fn stable_core_command_slew_stays_near_upper_hold_boundary() {
        assert!(!stable_core_command_slew_active(OverfillStage::Hold, 64.0));
        assert!(!stable_core_command_slew_active(
            OverfillStage::Recovery,
            71.0
        ));
        assert!(stable_core_command_slew_active(OverfillStage::Hold, 70.0));
        assert!(stable_core_command_slew_active(
            OverfillStage::Elevated,
            73.99
        ));
        assert!(!stable_core_command_slew_active(
            OverfillStage::Elevated,
            74.0
        ));
    }

    #[test]
    fn elevated_guard_default_remains_cold_for_force_band() {
        let strong = stage_guard(OverfillStage::Elevated);
        assert_eq!(strong.gate_min, Some(0.08));
        assert_eq!(strong.filt_max, Some(0.84));
        assert_eq!(strong.cov_keep_min, Some(0.55));
        assert_eq!(strong.target_keep, Some(0.55));
        assert_eq!(strong.trace_target_scale, Some(0.45));
    }

    fn assert_close(actual: f32, expected: f32) {
        assert!(
            (actual - expected).abs() < 1.0e-4,
            "actual {actual} != expected {expected}",
        );
    }

    #[test]
    fn select_stage_uses_expected_hysteresis_ladder() {
        assert_eq!(
            select_stage(20.0, OverfillStage::Recovery),
            OverfillStage::Bootstrap
        );
        assert_eq!(
            select_stage(41.5, OverfillStage::Bootstrap),
            OverfillStage::Bootstrap
        );
        assert_eq!(
            select_stage(43.0, OverfillStage::Bootstrap),
            OverfillStage::Recovery
        );
        assert_eq!(
            select_stage(59.0, OverfillStage::Recovery),
            OverfillStage::Recovery
        );
        assert_eq!(
            select_stage(60.0, OverfillStage::Recovery),
            OverfillStage::Hold
        );
        assert_eq!(select_stage(59.0, OverfillStage::Hold), OverfillStage::Hold);
        assert_eq!(
            select_stage(57.5, OverfillStage::Hold),
            OverfillStage::Recovery
        );
        assert_eq!(select_stage(71.5, OverfillStage::Hold), OverfillStage::Hold);
        assert_eq!(
            select_stage(72.0, OverfillStage::Hold),
            OverfillStage::Elevated
        );
        assert_eq!(
            select_stage(71.75, OverfillStage::Elevated),
            OverfillStage::Elevated
        );
        assert_eq!(
            select_stage(71.5, OverfillStage::Elevated),
            OverfillStage::Hold
        );
        assert_eq!(
            select_stage(70.5, OverfillStage::Elevated),
            OverfillStage::Hold
        );
        assert_eq!(
            select_stage(78.5, OverfillStage::Elevated),
            OverfillStage::Elevated
        );
        assert_eq!(
            select_stage(83.0, OverfillStage::Elevated),
            OverfillStage::Discharge
        );
        assert_eq!(
            select_stage(75.5, OverfillStage::Discharge),
            OverfillStage::Elevated
        );
    }

    #[test]
    fn warning_starts_on_first_breach_without_triggering_abort() {
        let state = advance_crisis_state(CRISIS_FILL_THRESHOLD, 0);
        assert_eq!(state.ticks, 1);
        assert!(state.warning_started);
        assert!(!state.triggered);
        assert!(!state.recovered);
    }

    #[test]
    fn abort_requires_sustained_breach() {
        let before = advance_crisis_state(CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS - 2);
        assert_eq!(before.ticks, CRISIS_SUSTAIN_TICKS - 1);
        assert!(!before.triggered);

        let final_tick = advance_crisis_state(CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS - 1);
        assert_eq!(final_tick.ticks, CRISIS_SUSTAIN_TICKS);
        assert!(final_tick.triggered);
    }

    #[test]
    fn dropping_below_threshold_resets_crisis_ticks() {
        let state = advance_crisis_state(CRISIS_FILL_THRESHOLD - 0.1, 7);
        assert_eq!(state.ticks, 0);
        assert!(!state.warning_started);
        assert!(!state.triggered);
        assert!(state.recovered);
    }
}
