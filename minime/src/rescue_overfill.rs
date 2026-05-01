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
pub const ELEVATED_RELEASE_THRESHOLD: f32 = 70.0;
pub const DISCHARGE_ENTRY_THRESHOLD: f32 = 78.0;
pub const DISCHARGE_RELEASE_THRESHOLD: f32 = 72.0;
pub const CRISIS_WARNING_THRESHOLD: f32 = DISCHARGE_ENTRY_THRESHOLD;
pub const CRISIS_FILL_THRESHOLD: f32 = 87.0;
pub const CRISIS_SUSTAIN_TICKS: u32 = 30;

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
            gate_min: Some(0.04),
            gate_max: Some(0.04),
            filt_max: Some(0.96),
            filt_min: Some(0.96),
            cov_keep_min: Some(0.35),
            cov_keep_max: Some(0.35),
            target_keep: Some(0.30),
            keep_floor: Some(0.35),
            keep_ceil: Some(0.35),
            trace_target_scale: Some(0.30),
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
        assert!(elevated_active(ELEVATED_RELEASE_THRESHOLD + 0.5, true));
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
        assert_eq!(elevated.gate_min, Some(0.04));
        assert_eq!(elevated.gate_max, Some(0.04));
        assert_eq!(elevated.filt_max, Some(0.96));
        assert_eq!(elevated.filt_min, Some(0.96));
        assert_eq!(elevated.cov_keep_min, Some(0.35));
        assert_eq!(elevated.cov_keep_max, Some(0.35));
        assert_eq!(elevated.target_keep, Some(0.30));
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
            select_stage(70.5, OverfillStage::Elevated),
            OverfillStage::Elevated
        );
        assert_eq!(
            select_stage(70.0, OverfillStage::Elevated),
            OverfillStage::Hold
        );
        assert_eq!(
            select_stage(83.0, OverfillStage::Elevated),
            OverfillStage::Discharge
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
