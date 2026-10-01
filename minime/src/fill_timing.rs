//! Process-local observation timing. No restored value is a timed observation.

use serde::Serialize;
use std::time::Duration;

#[derive(Clone, Copy, Debug, Serialize)]
pub struct FillRate {
    pub policy: &'static str,
    pub rate_pct_per_sec: Option<f32>,
    pub elapsed_s: Option<f64>,
    pub reason: &'static str,
}

impl FillRate {
    pub fn unavailable(reason: &'static str) -> Self {
        Self {
            policy: "observed_fill_rate_v1",
            rate_pct_per_sec: None,
            elapsed_s: None,
            reason,
        }
    }

    /// Legacy scalar fallback, not a measurement or proof of stability.
    /// Consumers must retain availability: zero can satisfy control gates.
    pub fn controller_value(self) -> f32 {
        self.rate_pct_per_sec.unwrap_or(0.0)
    }

    pub fn phase(self) -> &'static str {
        match self.rate_pct_per_sec.filter(|rate| rate.is_finite()) {
            Some(rate) if rate > 1.0 => "expanding",
            Some(rate) if rate < -1.0 => "contracting",
            Some(_) => "plateau",
            None => "unavailable",
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct FillObservation {
    pub fill_pct: f32,
    pub observed_at: Duration,
    pub reset_generation: u64,
    pub rate: FillRate,
}

#[derive(Default)]
pub struct FillRateTracker {
    previous: Option<(Duration, f32)>,
    latest: Option<FillObservation>,
    reset_generation: u64,
}

impl FillRateTracker {
    pub fn reset(&mut self) {
        self.previous = None;
        self.latest = None;
        self.reset_generation = self.reset_generation.saturating_add(1);
    }

    pub fn latest(&self) -> Option<FillObservation> {
        self.latest
    }

    pub fn observe(&mut self, time: Duration, fill_pct: f32) -> FillRate {
        let rate = self.observe_rate(time, fill_pct);
        self.latest = fill_pct.is_finite().then_some(FillObservation {
            fill_pct,
            observed_at: time,
            reset_generation: self.reset_generation,
            rate,
        });
        rate
    }

    fn observe_rate(&mut self, time: Duration, fill_pct: f32) -> FillRate {
        if !fill_pct.is_finite() {
            self.reset();
            return FillRate::unavailable("invalid_fill");
        }
        let previous = self.previous.replace((time, fill_pct));
        let Some((previous_time, previous_fill)) = previous else {
            return FillRate::unavailable("first_observation");
        };
        let Some(elapsed) = time.checked_sub(previous_time).filter(|dt| !dt.is_zero()) else {
            self.reset();
            self.previous = Some((time, fill_pct));
            return FillRate::unavailable("nonincreasing_clock");
        };
        let elapsed_s = elapsed.as_secs_f64();
        let rate = ((f64::from(fill_pct) - f64::from(previous_fill)) / elapsed_s) as f32;
        FillRate {
            policy: "observed_fill_rate_v1",
            rate_pct_per_sec: rate.is_finite().then_some(rate),
            elapsed_s: Some(elapsed_s),
            reason: if rate.is_finite() {
                "observed"
            } else {
                "invalid_rate"
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delayed_tick_reproduces_the_archived_rate_error() {
        let mut tracker = FillRateTracker::default();
        assert_eq!(
            tracker
                .observe(Duration::from_millis(302_182), 74.254_105)
                .rate_pct_per_sec,
            None
        );
        let rate = tracker.observe(Duration::from_millis(304_552), 72.127_94);
        assert_eq!(rate.elapsed_s, Some(2.37));
        assert!((rate.controller_value() + 0.897_117).abs() < 1e-5);
        assert!(((-4.252_334_6_f32) / rate.controller_value() - 4.74).abs() < 1e-5);
    }

    #[test]
    fn nominal_ticks_and_long_delays_use_their_own_intervals() {
        let mut tracker = FillRateTracker::default();
        tracker.observe(Duration::ZERO, 60.0);
        assert_eq!(
            tracker
                .observe(Duration::from_millis(500), 61.0)
                .controller_value(),
            2.0
        );
        assert_eq!(
            tracker
                .observe(Duration::from_millis(10_500), 66.0)
                .controller_value(),
            0.5
        );
    }

    #[test]
    fn restart_reset_and_bad_observations_never_invent_a_slope() {
        let mut tracker = FillRateTracker::default();
        for fill in [68.0, f32::NAN, 70.0, f32::INFINITY, 65.0] {
            assert_eq!(
                tracker
                    .observe(Duration::from_secs(10), fill)
                    .rate_pct_per_sec,
                None
            );
        }
        assert_eq!(
            tracker.observe(Duration::from_secs(9), 66.0).reason,
            "nonincreasing_clock"
        );
        assert_eq!(
            tracker
                .observe(Duration::from_secs(10), 67.0)
                .controller_value(),
            1.0
        );
        tracker.reset();
        assert_eq!(
            tracker.observe(Duration::from_secs(50), 90.0).reason,
            "first_observation"
        );
        let mut restarted = FillRateTracker::default();
        assert_eq!(
            restarted
                .observe(Duration::from_secs(1), 40.0)
                .controller_value(),
            0.0
        );
    }

    #[test]
    fn measurement_and_regulation_rates_keep_independent_endpoints() {
        let mut measured = FillRateTracker::default();
        let mut regulated = FillRateTracker::default();
        measured.observe(Duration::ZERO, 60.0);
        regulated.observe(Duration::ZERO, 60.0);
        measured.observe(Duration::from_millis(200), 64.0);
        assert!(
            (measured
                .observe(Duration::from_millis(500), 65.0)
                .controller_value()
                - 1.0 / 0.3)
                .abs()
                < 1e-5
        );
        assert_eq!(
            regulated
                .observe(Duration::from_millis(500), 65.0)
                .controller_value(),
            10.0
        );
    }

    #[test]
    fn unavailable_rate_is_explicit_and_extreme_values_do_not_overflow() {
        let mut tracker = FillRateTracker::default();
        let initial = tracker.observe(Duration::ZERO, f32::MAX);
        let serialized = serde_json::to_value(initial).unwrap();
        assert!(serialized["rate_pct_per_sec"].is_null());
        assert_eq!(serialized["reason"], "first_observation");
        let overflow = tracker.observe(Duration::from_nanos(1), -f32::MAX);
        assert_eq!(overflow.reason, "invalid_rate");
        assert_eq!(overflow.controller_value(), 0.0);
    }

    #[test]
    fn delayed_slope_changes_production_recovery_decision_without_retuning() {
        use crate::{rescue_overfill::OverfillStage, rescue_scaffold::StabilityPiState};
        let mut tracker = FillRateTracker::default();
        tracker.observe(Duration::ZERO, 46.0);
        let observed = tracker
            .observe(Duration::from_secs(3), 44.0)
            .controller_value();
        let nominal = (44.0 - 46.0) / 0.5;
        let old = StabilityPiState::default().step(44.0, nominal, OverfillStage::Hold, true);
        let corrected = StabilityPiState::default().step(44.0, observed, OverfillStage::Hold, true);
        assert!(old.recovery_impulse_active);
        assert!(!corrected.recovery_impulse_active);
        // A genuine low-fill trigger still works; slope repair is not a bypass.
        assert!(
            StabilityPiState::default()
                .step(40.0, observed, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
    }
}
