//! Offline regression tests for the controller review findings.
//! These qualify policy boundaries, not coupled-engine stability or deployment.
use minime::{
    fill_timing::{FillRate, FillRateTracker},
    rescue_overfill::{select_stage, stage_guard_for_state, OverfillStage},
    rescue_scaffold::{
        stable_core_scaffold_retirement_candidate_reason, StabilityPiState, StableCoreRestartGate,
    },
    stable_core::{StableCoreRuntime, FULL_PRESENCE_PROFILE},
};
use std::time::Duration;

fn rate(from: f32, to: f32, milliseconds: u64) -> FillRate {
    let mut clock = FillRateTracker::default();
    clock.observe(Duration::ZERO, from);
    clock.observe(Duration::from_millis(milliseconds), to)
}

#[test]
fn recovery_reset_breaks_both_endpoint_pairs() {
    let mut measured = FillRateTracker::default();
    let mut regulation = FillRateTracker::default();
    measured.observe(Duration::ZERO, 34.0);
    regulation.observe(Duration::ZERO, 34.0);
    let without_reset = rate(34.0, 68.0, 3000);
    assert!(without_reset.controller_value() > 11.0);
    measured.reset();
    regulation.reset();
    for clock in [&mut measured, &mut regulation] {
        let fresh = clock.observe(Duration::from_secs(3), 68.0);
        assert_eq!(fresh.reason, "first_observation");
        assert!(fresh.rate_pct_per_sec.is_none());
        let next = clock.observe(Duration::from_secs(6), 70.0);
        assert!((next.controller_value() - 2.0 / 3.0).abs() < 1e-6);
    }
}

fn runtime(full_presence: bool) -> StableCoreRuntime {
    StableCoreRuntime::from_lookup(|key| {
        match key {
            "MINIME_STABLE_CORE" => Some("1"),
            "MINIME_RESCUE_LIVE_AUDIO_DIVISOR" => Some("7"),
            "MINIME_RESCUE_LIVE_VIDEO_DIVISOR" => Some("11"),
            "MINIME_RESCUE_LIVE_INTAKE_STAGES" => Some("hold,elevated,recovery"),
            "MINIME_STABLE_CORE_SENSORY_PROFILE" if full_presence => Some(FULL_PRESENCE_PROFILE),
            _ => None,
        }
        .map(str::to_owned)
    })
}

fn record_settle(
    gate: &mut StableCoreRestartGate,
    time: u64,
    fill: f32,
    slope: impl Into<Option<f32>>,
) {
    gate.record_measured_fill(
        time,
        fill,
        slope,
        OverfillStage::Hold,
        false,
        true,
        false,
        false,
    );
}

#[test]
fn first_unobserved_rate_does_not_permit_ordinary_activation_or_intake() {
    let initial = FillRateTracker::default().observe(Duration::ZERO, 68.0);
    assert_eq!(initial.rate_pct_per_sec, None);
    let activation = StableCoreRestartGate::new(0).evaluate_activation(
        OverfillStage::Hold,
        68.0,
        initial.rate_pct_per_sec,
        false,
        0,
        0,
    );
    assert!(!activation.activate);
    assert_eq!(activation.reason, "rate_unavailable");
    for full_presence in [false, true] {
        let decision = runtime(full_presence).live_intake_decision_for_stage(
            "hold",
            true,
            false,
            68.0,
            initial.rate_pct_per_sec,
        );
        assert_eq!(decision.divisors(), (0, 0));
        assert_eq!(decision.reason, "rate_unavailable");
    }
}

#[test]
fn unobserved_samples_cannot_supply_settle_or_retirement_proof() {
    let mut gate = StableCoreRestartGate::new(0);
    gate.record_scaffold_activated(0, 68.0, "synthetic_review");
    let mut clock = FillRateTracker::default();
    for time in [1000, 2000, 3000] {
        clock.reset();
        let observation = clock.observe(Duration::from_millis(time), 68.0);
        assert!(observation.rate_pct_per_sec.is_none());
        record_settle(&mut gate, time, 68.0, observation.rate_pct_per_sec);
    }
    assert!(!gate.is_settled());
    for time in [4000, 5000, 6000] {
        record_settle(&mut gate, time, 68.0, Some(0.0));
    }
    assert!(gate.is_settled());
    assert!(stable_core_scaffold_retirement_candidate_reason(
        gate.is_settled(),
        68.0,
        None,
        OverfillStage::Hold,
        false,
        true,
        false,
        false,
        false,
        0.0,
    )
    .is_none());
}

#[test]
fn missing_rate_cannot_release_recovery_on_slope_evidence() {
    let mut pi = StabilityPiState::default();
    assert!(
        pi.step(40.0, 0.0, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    let unknown = FillRateTracker::default().observe(Duration::ZERO, 60.0);
    assert!(unknown.rate_pct_per_sec.is_none());
    for _ in 0..100 {
        let output = pi.step(60.0, unknown.rate_pct_per_sec, OverfillStage::Hold, true);
        assert!(output.recovery_impulse_active);
        assert!(!output.fill_slope_available);
    }
    // The independent strong-fill release remains available without slope.
    assert!(
        pi.step(62.0, None, OverfillStage::Hold, true)
            .reentry_active
    );
}

#[test]
fn missing_and_invalid_rates_preserve_absolute_high_fill_drains() {
    for fill in [74.0, 78.0, 82.0, 95.0] {
        let stage = select_stage(fill, OverfillStage::Hold);
        let finite = StabilityPiState::default().step(fill, 0.0, stage, true);
        let nan = StabilityPiState::default().step(fill, f32::NAN, stage, true);
        assert!(finite.drain_weight >= 0.24);
        assert_eq!(nan.drain_weight, finite.drain_weight);
        assert!(!nan.fill_slope_available);
        let absent = StabilityPiState::default().step(fill, None, stage, true);
        assert_eq!(absent.drain_weight, finite.drain_weight);
        let mut gate = StableCoreRestartGate::new(0);
        gate.record_scaffold_activated(0, fill, "synthetic_review");
        assert!(gate.drain_floor(fill, 0.0).is_some());
        assert_eq!(
            gate.drain_floor(fill, f32::NAN),
            gate.drain_floor(fill, 0.0)
        );
        assert_eq!(gate.drain_floor(fill, None), gate.drain_floor(fill, 0.0));
    }
}

#[test]
fn delayed_ticks_change_intake_only_in_the_slope_gated_profile() {
    let observed = rate(66.0, 68.0, 3000).controller_value();
    let nominal = (68.0 - 66.0) / 0.5;
    let bounded = runtime(false);
    assert_eq!(
        bounded
            .live_intake_decision_for_stage("hold", true, false, 68.0, nominal,)
            .reason,
        "fast_rising_suppressed"
    );
    assert_eq!(
        bounded
            .live_intake_decision_for_stage("hold", true, false, 68.0, observed,)
            .reason,
        "admitted"
    );
    let full = runtime(true);
    assert_eq!(
        full.live_intake_decision_for_stage("hold", true, false, 68.0, nominal),
        full.live_intake_decision_for_stage("hold", true, false, 68.0, observed)
    );
}

#[test]
fn delayed_ticks_change_scaffold_activation_and_restart_settling() {
    let slope = rate(60.0, 62.0, 3000).controller_value();
    let old = StableCoreRestartGate::new(0).evaluate_activation(
        OverfillStage::Hold,
        62.0,
        4.0,
        false,
        0,
        0,
    );
    let new = StableCoreRestartGate::new(0).evaluate_activation(
        OverfillStage::Hold,
        62.0,
        slope,
        false,
        0,
        0,
    );
    assert!(!old.activate);
    assert!(new.activate);
    let mut old_gate = StableCoreRestartGate::new(0);
    let mut new_gate = StableCoreRestartGate::new(0);
    for (index, fill) in [63.0, 66.0, 69.0].into_iter().enumerate() {
        let observed = rate(fill - 3.0, fill, 3000).controller_value();
        record_settle(&mut old_gate, (index as u64 + 1) * 3000, fill, 6.0);
        record_settle(&mut new_gate, (index as u64 + 1) * 3000, fill, observed);
    }
    assert!(!old_gate.is_settled());
    assert!(new_gate.is_settled());
}

#[test]
fn delayed_ticks_change_fast_rise_reentry_exit_but_not_absolute_low_fill_exit() {
    let mut reentry = StabilityPiState::default();
    assert!(
        reentry
            .step(40.0, -1.0, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    assert!(
        reentry
            .step(62.0, 1.0, OverfillStage::Hold, true)
            .reentry_active
    );
    let mut nominal = reentry;
    let observed = rate(69.0, 71.0, 3000).controller_value();
    assert!(
        !nominal
            .step(71.0, 4.0, OverfillStage::Hold, true)
            .reentry_active
    );
    assert!(
        reentry
            .step(71.0, observed, OverfillStage::Hold, true)
            .reentry_active
    );
    for slope in [-10.0, 0.0, 10.0] {
        let mut pi = reentry;
        assert!(
            pi.step(40.0, slope, OverfillStage::Recovery, true)
                .recovery_impulse_active
        );
    }
}

#[test]
fn restart_semantic_and_recovery_blocks_remain_effective_with_observed_rates() {
    for (semantic, scaffold, reentry, recovery) in [
        (true, true, false, false),
        (false, false, false, false),
        (false, true, true, false),
        (false, true, false, true),
    ] {
        let mut gate = StableCoreRestartGate::new(0);
        for time in 1..=10 {
            gate.record_measured_fill(
                time * 3000,
                68.0,
                0.1,
                OverfillStage::Hold,
                semantic,
                scaffold,
                reentry,
                recovery,
            );
        }
        assert!(!gate.is_settled());
    }
}

#[test]
fn measured_rate_sweep_preserves_absolute_rails_and_bounded_outputs() {
    let mut cases = 0;
    for fill in (0..=100).map(|x| x as f32) {
        for delta in [-8.0, -2.0, -0.1, 0.0, 0.1, 2.0, 8.0] {
            for dt_ms in [50, 500, 2370, 3000, 10000] {
                let measured = rate(fill - delta, fill, dt_ms);
                let slope = measured.rate_pct_per_sec.unwrap();
                let stage = select_stage(fill, OverfillStage::Hold);
                let output = StabilityPiState::default().step(fill, slope, stage, true);
                assert!(output.pi_output.is_finite());
                assert!((0.0..=0.120).contains(&output.pi_output));
                assert!((0.0..=1.0).contains(&output.drain_weight));
                if fill < 42.0 {
                    assert!(output.recovery_impulse_active);
                }
                if fill >= 74.0 {
                    assert!(output.drain_weight >= 0.24);
                }
                if fill >= 82.0 {
                    assert!(output.drain_weight >= 0.70);
                }
                for full in [false, true] {
                    if fill >= 74.0 {
                        assert_eq!(
                            runtime(full)
                                .live_intake_decision_for_stage(
                                    "hold",
                                    true,
                                    output.high_fill_drain_active,
                                    fill,
                                    slope,
                                )
                                .divisors(),
                            (0, 0)
                        );
                    }
                }
                cases += 1;
            }
        }
    }
    assert_eq!(cases, 3535);
}

#[test]
fn finite_rate_magnitude_does_not_change_fill_only_stage_guard() {
    for fill in [34.0, 44.0, 58.0, 68.0, 72.0, 74.0, 78.0, 90.0] {
        let stage = select_stage(fill, OverfillStage::Hold);
        let negative = stage_guard_for_state(stage, fill, -8.0);
        let positive = stage_guard_for_state(stage, fill, 8.0);
        assert_eq!(negative.gate_min, positive.gate_min);
        assert_eq!(negative.gate_max, positive.gate_max);
        assert_eq!(negative.cov_keep_max, positive.cov_keep_max);
        assert_eq!(negative.trace_target_scale, positive.trace_target_scale);
    }
}

#[test]
fn boundary_equality_and_elapsed_units_remain_explicit() {
    let at_trigger = rate(46.0, 44.0, 1000);
    assert_eq!(at_trigger.controller_value(), -2.0);
    assert!(
        !StabilityPiState::default()
            .step(
                44.0,
                at_trigger.controller_value(),
                OverfillStage::Hold,
                true,
            )
            .recovery_impulse_active
    );
    assert!(
        StabilityPiState::default()
            .step(
                44.0,
                rate(46.0, 44.0, 999).controller_value(),
                OverfillStage::Hold,
                true,
            )
            .recovery_impulse_active
    );
    assert_eq!(
        runtime(false)
            .live_intake_decision_for_stage("hold", true, false, 68.0, 1.0,)
            .reason,
        "admitted"
    );
    assert_eq!(
        runtime(false)
            .live_intake_decision_for_stage("hold", true, false, 68.0, 1.0001,)
            .reason,
        "fast_rising_suppressed"
    );
}

#[test]
fn preview_does_not_advance_recovery_or_reentry_state() {
    let mut pi = StabilityPiState::default();
    assert!(
        pi.step(40.0, -1.0, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    let before = format!("{pi:?}");
    for _ in 0..100 {
        let preview = pi.preview(62.0, 1.0, OverfillStage::Hold, true);
        assert!(preview.reentry_active);
    }
    assert_eq!(format!("{pi:?}"), before);
}

#[test]
fn skipped_regulation_does_not_mix_an_old_fill_with_a_new_rate() {
    let mut measured = FillRateTracker::default();
    let mut regulation = FillRateTracker::default();
    measured.observe(Duration::ZERO, 60.0);
    regulation.observe(Duration::ZERO, 60.0);
    measured.observe(Duration::from_millis(200), 73.0);
    let paired = measured.latest().unwrap();
    assert_eq!(paired.fill_pct, 73.0);
    assert_eq!(paired.rate.rate_pct_per_sec, Some(65.0));
    assert_eq!(paired.observed_at, Duration::from_millis(200));
    assert_eq!(regulation.latest().unwrap().fill_pct, 60.0);
    let output = StabilityPiState::default().step(
        paired.fill_pct,
        paired.rate.rate_pct_per_sec,
        OverfillStage::Elevated,
        true,
    );
    assert_eq!(output.error_pct, 5.0);
    assert_eq!(output.drain_weight, 0.04);
    let regulation_rate = regulation.observe(Duration::from_millis(500), 74.0);
    assert_eq!(regulation_rate.rate_pct_per_sec, Some(28.0));
    assert_eq!(measured.latest().unwrap().fill_pct, 73.0);
}

#[test]
fn invalid_sample_between_regulation_ticks_breaks_both_histories() {
    let mut measured = FillRateTracker::default();
    let mut regulation = FillRateTracker::default();
    measured.observe(Duration::ZERO, 60.0);
    regulation.observe(Duration::ZERO, 60.0);
    measured.observe(Duration::from_secs(1), 62.0);
    regulation.observe(Duration::from_secs(1), 62.0);
    assert_eq!(
        regulation.latest().unwrap().rate.rate_pct_per_sec,
        Some(2.0)
    );

    // Orchestration invalidates regulation here even without a regulation job.
    regulation.reset();
    measured.observe(Duration::from_millis(1500), f32::NAN);
    assert!(measured.latest().is_none());
    assert!(regulation.latest().is_none());
    let measured_rate = measured.observe(Duration::from_secs(2), 68.0);
    let regulation_rate = regulation.observe(Duration::from_secs(2), 68.0);
    assert_eq!(measured_rate.reason, "first_observation");
    assert_eq!(regulation_rate.reason, "first_observation");
    assert_eq!(regulation_rate.phase(), "unavailable");
    assert_eq!(
        regulation
            .observe(Duration::from_secs(3), 69.0)
            .rate_pct_per_sec,
        Some(1.0)
    );
}

#[test]
fn reset_invalid_fill_and_clock_fault_discard_stale_evidence() {
    let mut clock = FillRateTracker::default();
    assert!(clock.latest().is_none());
    clock.observe(Duration::from_secs(1), 68.0);
    clock.observe(Duration::from_secs(2), 69.0);
    let previous = clock.latest().unwrap();
    assert_eq!(previous.rate.rate_pct_per_sec, Some(1.0));
    clock.reset();
    assert!(clock.latest().is_none());
    clock.observe(Duration::from_secs(3), 60.0);
    let restarted = clock.latest().unwrap();
    assert!(restarted.reset_generation > previous.reset_generation);
    assert!(restarted.rate.rate_pct_per_sec.is_none());
    assert_eq!(previous.fill_pct, 69.0);
    clock.observe(Duration::from_secs(4), f32::NAN);
    assert!(clock.latest().is_none());
    let recovered = clock.observe(Duration::from_secs(5), 68.0);
    assert_eq!(recovered.phase(), "unavailable");
    let generation = clock.latest().unwrap().reset_generation;
    let backward = clock.observe(Duration::from_secs(4), 65.0);
    assert_eq!(backward.reason, "nonincreasing_clock");
    assert!(clock.latest().unwrap().reset_generation > generation);
    assert!(backward.rate_pct_per_sec.is_none());
    let serialized = serde_json::to_value(clock.latest().unwrap()).unwrap();
    assert!(serialized["rate"]["rate_pct_per_sec"].is_null());
}

#[test]
fn missing_fill_freezes_pi_history_without_emitting_an_action() {
    let mut pi = StabilityPiState::default();
    assert!(
        pi.step(40.0, None, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    let before = format!("{pi:?}");
    let missing = pi.step(f32::NAN, None, OverfillStage::Hold, true);
    assert!(!missing.active);
    assert_eq!(missing.drain_weight, 0.0);
    assert_eq!(format!("{pi:?}"), before);
    assert!(
        pi.step(40.0, None, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
}

#[test]
fn missing_rate_preserves_low_fill_activation_and_breaks_settle_streaks() {
    let low = StableCoreRestartGate::new(0).evaluate_activation(
        OverfillStage::Bootstrap,
        34.0,
        None,
        true,
        7,
        11,
    );
    assert!(low.activate);
    assert_eq!(low.reason, "protective_low_fill_activated");
    let mut gate = StableCoreRestartGate::new(0);
    record_settle(&mut gate, 1000, 68.0, Some(0.0));
    record_settle(&mut gate, 2000, 68.0, Some(0.0));
    record_settle(&mut gate, 3000, 68.0, None);
    record_settle(&mut gate, 4000, 68.0, Some(0.0));
    record_settle(&mut gate, 5000, 68.0, Some(0.0));
    assert!(!gate.is_settled());
    record_settle(&mut gate, 6000, 68.0, Some(0.0));
    assert!(gate.is_settled());
}

#[test]
fn missing_rate_is_not_a_plateau_or_an_accumulated_release_streak() {
    assert_eq!(FillRate::unavailable("startup").phase(), "unavailable");
    assert_eq!(rate(68.0, 68.0, 500).phase(), "plateau");
    assert_eq!(rate(68.0, 70.0, 500).phase(), "expanding");
    assert_eq!(rate(68.0, 66.0, 500).phase(), "contracting");
    let mut pi = StabilityPiState::default();
    assert!(
        pi.step(40.0, None, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    assert!(
        pi.step(60.0, Some(0.0), OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    assert!(
        pi.step(60.0, None, OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    assert!(
        pi.step(60.0, Some(0.0), OverfillStage::Hold, true)
            .recovery_impulse_active
    );
    assert!(
        pi.step(60.0, Some(0.0), OverfillStage::Hold, true)
            .reentry_active
    );
}
