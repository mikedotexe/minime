use super::*;

fn fixture(fill: f32, rate: Option<f32>, semantic: bool) -> MeasurementInput {
    MeasurementInput {
        now_unix_ms: 3_000,
        fill_pct: fill,
        rate,
        stage: OverfillStage::Hold,
        semantic_active: semantic,
        scaffold_available: true,
        live_audio_divisor: 12,
        live_video_divisor: 12,
        reentry_active: false,
        recovery_active: false,
        high_fill_drain_active: false,
        applied_drain_weight: 0.0,
    }
}

fn initial() -> (ScaffoldLifecycle, StableCoreRestartGate) {
    let mut gate = StableCoreRestartGate::new(0);
    gate.record_scaffold_activated(1_000, 60.0, "fixture");
    (
        ScaffoldLifecycle {
            active: true,
            retirement_ticks: 0,
            retirement_reason: "fixture",
        },
        gate,
    )
}

#[test]
fn continuous_admitted_trickle_prevents_current_settle_even_with_stable_fill() {
    let semantic = minime::controller_recovery::stable_core_semantic_retirement_active(
        Some(800),
        15_000,
        0.000217,
        true,
    );
    assert!(semantic);
    let (mut lifecycle, mut gate) = initial();
    for tick in 0..100 {
        let input = MeasurementInput {
            now_unix_ms: 3_000 + tick * 2_370,
            ..fixture(68.0, Some(0.0), semantic)
        };
        record_with_policy(&mut lifecycle, &mut gate, input, SettlePolicy::Current);
        assert!(gate.active());
        assert!(!gate.is_settled());
        assert!(lifecycle.active);
        assert_eq!(
            gate.status(input.now_unix_ms, false, false, "fixture", 0.0, 0.0, 0.0)
                .settle_candidate_reason,
            "semantic_active"
        );
    }
}

#[test]
fn restart_only_candidate_does_not_authorize_scaffold_retirement_under_load() {
    let (mut lifecycle, mut gate) = initial();
    for _ in 0..12 {
        record_with_policy(
            &mut lifecycle,
            &mut gate,
            fixture(68.0, Some(0.0), true),
            SettlePolicy::RestartOnlyUnderLoad,
        );
    }
    assert!(gate.is_settled());
    assert!(lifecycle.active);
    assert_eq!(lifecycle.retirement_reason, "semantic_active");
    assert_eq!(lifecycle.retirement_ticks, 0);
}

#[test]
fn blanket_semantic_bypass_retires_scaffold_not_just_a_status_label() {
    let (mut lifecycle, mut gate) = initial();
    for _ in 0..5 {
        record_with_policy(
            &mut lifecycle,
            &mut gate,
            fixture(68.0, Some(0.0), true),
            SettlePolicy::IgnoreSemanticEverywhere,
        );
    }
    assert!(gate.is_settled());
    assert!(!lifecycle.active);
    assert_eq!(
        lifecycle.retirement_reason,
        "retired_after_restart_gate_settle"
    );
}

#[test]
fn all_policies_agree_when_semantic_input_is_quiet() {
    for policy in [
        SettlePolicy::IgnoreSemanticEverywhere,
        SettlePolicy::RestartOnlyUnderLoad,
    ] {
        let (mut expected_lifecycle, mut expected_gate) = initial();
        let (mut actual_lifecycle, mut actual_gate) = initial();
        for fill in [68.0, 69.0, 70.0, 71.0, 70.0, 68.0] {
            let input = fixture(fill, Some(0.2), false);
            record_with_policy(
                &mut expected_lifecycle,
                &mut expected_gate,
                input,
                SettlePolicy::Current,
            );
            record_with_policy(&mut actual_lifecycle, &mut actual_gate, input, policy);
            assert_eq!(expected_gate, actual_gate);
            assert_eq!(expected_lifecycle.active, actual_lifecycle.active);
            assert_eq!(
                expected_lifecycle.retirement_ticks,
                actual_lifecycle.retirement_ticks
            );
            assert_eq!(
                expected_lifecycle.retirement_reason,
                actual_lifecycle.retirement_reason
            );
        }
    }
}

#[test]
fn candidate_preserves_nonsemantic_rejections_and_recovery_relapse() {
    for input in [
        fixture(74.0, Some(0.0), true),
        fixture(68.0, None, true),
        fixture(f32::NAN, Some(0.0), true),
        fixture(68.0, Some(f32::NAN), true),
        MeasurementInput {
            reentry_active: true,
            ..fixture(68.0, Some(0.0), true)
        },
        MeasurementInput {
            recovery_active: true,
            ..fixture(68.0, Some(0.0), true)
        },
    ] {
        let (mut lifecycle, mut gate) = initial();
        for _ in 0..5 {
            record_with_policy(
                &mut lifecycle,
                &mut gate,
                input,
                SettlePolicy::RestartOnlyUnderLoad,
            );
        }
        assert!(!gate.is_settled());
    }
    let (mut lifecycle, mut gate) = initial();
    for _ in 0..3 {
        record_with_policy(
            &mut lifecycle,
            &mut gate,
            fixture(68.0, Some(0.0), true),
            SettlePolicy::RestartOnlyUnderLoad,
        );
    }
    assert!(gate.is_settled());
    record_with_policy(
        &mut lifecycle,
        &mut gate,
        MeasurementInput {
            recovery_active: true,
            ..fixture(20.0, Some(-2.0), true)
        },
        SettlePolicy::RestartOnlyUnderLoad,
    );
    assert!(!gate.is_settled());
    assert!(gate.active());
}

#[test]
fn quiet_recovery_still_requires_fresh_consecutive_candidates() {
    let (mut lifecycle, mut gate) = initial();
    for semantic in [false, false, true, false, false] {
        record_with_policy(
            &mut lifecycle,
            &mut gate,
            fixture(68.0, Some(0.0), semantic),
            SettlePolicy::Current,
        );
        assert!(!gate.is_settled());
    }
    record_with_policy(
        &mut lifecycle,
        &mut gate,
        fixture(68.0, Some(0.0), false),
        SettlePolicy::Current,
    );
    assert!(gate.is_settled());
}

#[test]
fn observing_the_measurement_does_not_change_real_gate_or_lifecycle() {
    let (mut expected_lifecycle, mut expected_gate) = initial();
    let (mut actual_lifecycle, mut actual_gate) = initial();
    let mut observation = stable_covariance::RestartSettleObservationV1::default();
    for tick in 1..100_u64 {
        let input = MeasurementInput {
            now_unix_ms: tick * 2_370,
            ..fixture(60.0 + (tick % 18) as f32, Some(1.0), tick % 13 < 10)
        };
        stable_covariance::record_measurement(&mut expected_lifecycle, &mut expected_gate, input);
        observation.record(input, actual_lifecycle.active);
        stable_covariance::record_measurement(&mut actual_lifecycle, &mut actual_gate, input);
        assert_eq!(actual_gate, expected_gate);
        assert_eq!(actual_lifecycle.active, expected_lifecycle.active);
        assert_eq!(
            actual_lifecycle.retirement_ticks,
            expected_lifecycle.retirement_ticks
        );
        assert_eq!(
            actual_lifecycle.retirement_reason,
            expected_lifecycle.retirement_reason
        );
    }
}
