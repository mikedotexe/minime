//! Read-only evaluation. No reference to the running gate, PI or covariance is accepted.
use super::MeasurementInput;
use crate::rescue_scaffold::{StableCoreRestartGate, STABLE_CORE_RESTART_SETTLE_REQUIRED_TICKS};
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct RestartSettleObservationV1 {
    pub schema: &'static str,
    pub authority: &'static str,
    pub scope: &'static str,
    pub observed_at_unix_ms: Option<u64>,
    pub observed_semantic_active: Option<bool>,
    pub consecutive_numerical_candidates: u32,
    pub existing_required_measurements: u32,
    pub numerical_count_met: bool,
    pub numerical_reason: &'static str,
}

impl Default for RestartSettleObservationV1 {
    fn default() -> Self {
        Self {
            schema: "restart_settle_observation_v1",
            authority: "observation_only_not_gate_settlement_or_scaffold_retirement",
            scope: "existing_fill_rate_stage_scaffold_reentry_recovery_conditions_without_semantic_quiet",
            observed_at_unix_ms: None,
            observed_semantic_active: None,
            consecutive_numerical_candidates: 0,
            existing_required_measurements: STABLE_CORE_RESTART_SETTLE_REQUIRED_TICKS,
            numerical_count_met: false,
            numerical_reason: "not_observed",
        }
    }
}

impl RestartSettleObservationV1 {
    pub fn record(&mut self, input: MeasurementInput, scaffold_active: bool) {
        if self
            .observed_at_unix_ms
            .is_some_and(|prior| input.now_unix_ms <= prior)
        {
            self.consecutive_numerical_candidates = 0;
            self.numerical_count_met = false;
            self.numerical_reason = "nonadvancing_observation_time";
            return;
        }
        self.observed_at_unix_ms = Some(input.now_unix_ms);
        self.observed_semantic_active = Some(input.semantic_active);
        // A fresh disposable gate evaluates one measurement using production rules.
        // Its state never escapes this probe; the real restart gate is untouched.
        let mut probe = StableCoreRestartGate::new(input.now_unix_ms);
        probe.record_measured_fill(
            input.now_unix_ms,
            input.fill_pct,
            input.rate,
            input.stage,
            false,
            scaffold_active,
            input.reentry_active,
            input.recovery_active,
        );
        let status = probe.status(
            input.now_unix_ms,
            false,
            false,
            "observation_only",
            0.0,
            0.0,
            0.0,
        );
        self.numerical_reason = status.settle_candidate_reason;
        self.consecutive_numerical_candidates = if status.settle_candidate_ticks > 0 {
            self.consecutive_numerical_candidates.saturating_add(1)
        } else {
            0
        };
        self.numerical_count_met =
            self.consecutive_numerical_candidates >= self.existing_required_measurements;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rescue_overfill::OverfillStage;

    fn input(now: u64) -> MeasurementInput {
        MeasurementInput {
            now_unix_ms: now,
            fill_pct: 68.0,
            rate: Some(0.0),
            stage: OverfillStage::Hold,
            semantic_active: true,
            scaffold_available: true,
            live_audio_divisor: 12,
            live_video_divisor: 12,
            reentry_active: false,
            recovery_active: false,
            high_fill_drain_active: false,
            applied_drain_weight: 0.0,
        }
    }

    #[test]
    fn semantic_quiet_is_distinct_from_numerical_eligibility() {
        let mut observation = RestartSettleObservationV1::default();
        assert!(!observation.numerical_count_met);
        assert_eq!(observation.observed_semantic_active, None);
        let mut actual = StableCoreRestartGate::new(0);
        actual.record_scaffold_activated(1, 68.0, "fixture");
        for now in [2_370, 4_740, 7_110] {
            observation.record(input(now), true);
            actual.record_measured_fill(
                now,
                68.0,
                Some(0.0),
                OverfillStage::Hold,
                true,
                true,
                false,
                false,
            );
        }
        assert!(observation.numerical_count_met);
        assert_eq!(observation.observed_semantic_active, Some(true));
        assert!(!actual.is_settled());
        assert!(actual.active());
        let rendered = serde_json::to_value(&observation).unwrap();
        assert_eq!(
            rendered["authority"],
            "observation_only_not_gate_settlement_or_scaffold_retirement"
        );
    }

    #[test]
    fn gaps_are_not_interpolated_and_bad_or_nonadvancing_measurements_clear_count() {
        for bad in [
            MeasurementInput {
                rate: None,
                ..input(100_000)
            },
            MeasurementInput {
                rate: Some(f32::NAN),
                ..input(100_000)
            },
            MeasurementInput {
                fill_pct: f32::NAN,
                ..input(100_000)
            },
            MeasurementInput {
                fill_pct: 74.0,
                ..input(100_000)
            },
            MeasurementInput {
                reentry_active: true,
                ..input(100_000)
            },
            MeasurementInput {
                recovery_active: true,
                ..input(100_000)
            },
            input(2),
            input(1),
        ] {
            let mut observation = RestartSettleObservationV1::default();
            observation.record(input(1), true);
            observation.record(input(2), true);
            observation.record(bad, true);
            assert_eq!(observation.consecutive_numerical_candidates, 0);
            assert!(!observation.numerical_count_met);
        }
        let mut observation = RestartSettleObservationV1::default();
        observation.record(input(1), true);
        observation.record(input(100_000), true);
        assert_eq!(observation.consecutive_numerical_candidates, 2);
        assert!(!observation.numerical_count_met);
        observation.record(input(100_001), false);
        assert_eq!(observation.numerical_reason, "scaffold_inactive");
        assert_eq!(observation.consecutive_numerical_candidates, 0);
    }
}
