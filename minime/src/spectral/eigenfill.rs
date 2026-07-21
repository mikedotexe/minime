// src/spectral/eigenfill.rs
// Robust EigenFill with scale invariance, temporal smoothing, and rank thresholding.
#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ThresholdMode {
    CurrentRuntime,
    FixedSurvival,
}

#[derive(Debug, Clone)]
pub struct EigenFillEstimator {
    dim: usize,
    // EMA of normalized eigenvalues' median and mean
    ema_mean: f32,
    ema_median: f32,
    // EMA of fill
    ema_fill: f32,
    // smoothing factors
    alpha_stats: f32,
    alpha_fill: f32,
    // minimum relative threshold above noise floor
    rel_thresh: f32,
    // floor to avoid reporting zero fill when a mode is active
    min_fill: f32,
    // decay rate for the temporal leak
    leak_rate: f32,
    // threshold policy: stable-core fixed survival intentionally matches the
    // pinned rescue lane while normal runtime keeps the stricter identity guard.
    threshold_mode: ThresholdMode,
    // guard against stale updates
    last_update: Instant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EigenFillEstimatorSnapshotV1 {
    pub dim: usize,
    pub ema_mean: f32,
    pub ema_median: f32,
    pub ema_fill: f32,
    pub alpha_stats: f32,
    pub alpha_fill: f32,
    pub rel_thresh: f32,
    pub min_fill: f32,
    pub leak_rate: f32,
    pub threshold_mode: String,
    pub last_update_age_ms: u64,
}

impl EigenFillEstimator {
    pub fn new(dim: usize) -> Self {
        Self {
            dim,
            ema_mean: 1.0,
            ema_median: 1.0,
            ema_fill: 0.0,
            alpha_stats: 0.1,
            alpha_fill: 0.25,
            rel_thresh: 0.15, // treat λ > 0.15×mean as "active" in normalized space
            min_fill: 0.10,   // never report below 10% when any mode is active
            leak_rate: 0.005, // slower temporal decay so fill doesn't drain between measurements
            threshold_mode: ThresholdMode::CurrentRuntime,
            last_update: Instant::now(),
        }
    }

    pub fn fixed_survival(dim: usize) -> Self {
        let mut estimator = Self::new(dim);
        estimator.rel_thresh = 0.12;
        estimator.min_fill = 0.04;
        estimator.alpha_stats = 0.05;
        estimator.alpha_fill = 0.10;
        estimator.leak_rate = 0.006;
        estimator.threshold_mode = ThresholdMode::FixedSurvival;
        estimator
    }

    /// Restore the estimator's numerical state from a division checkpoint.
    ///
    /// `Instant` itself is process-local, so the captured age is reconstructed
    /// relative to the new process. All policy and EMA values remain explicit.
    #[must_use]
    pub fn from_snapshot_v1(snapshot: &EigenFillEstimatorSnapshotV1) -> Self {
        let mut estimator = match snapshot.threshold_mode.as_str() {
            "fixed_survival" => Self::fixed_survival(snapshot.dim),
            _ => Self::new(snapshot.dim),
        };
        estimator.ema_mean = snapshot.ema_mean.max(1.0e-9);
        estimator.ema_median = snapshot.ema_median.max(0.0);
        estimator.ema_fill = snapshot.ema_fill.clamp(0.0, 1.0);
        estimator.alpha_stats = snapshot.alpha_stats.clamp(0.01, 0.5);
        estimator.alpha_fill = snapshot.alpha_fill.clamp(0.05, 0.8);
        estimator.rel_thresh = snapshot.rel_thresh.clamp(0.01, 0.9);
        estimator.min_fill = snapshot.min_fill.clamp(0.0, 0.5);
        estimator.leak_rate = snapshot.leak_rate.clamp(0.0, 0.2);
        estimator.last_update = Instant::now()
            .checked_sub(std::time::Duration::from_millis(
                snapshot.last_update_age_ms,
            ))
            .unwrap_or_else(Instant::now);
        estimator
    }

    #[inline]
    fn median(mut xs: Vec<f32>) -> f32 {
        let n = xs.len();
        if n == 0 {
            return 0.0;
        }
        let mid = n / 2;
        xs.select_nth_unstable_by(mid, |a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
        if n % 2 == 1 {
            xs[mid]
        } else {
            let a = *xs[..mid]
                .iter()
                .max_by(|x, y| x.partial_cmp(y).unwrap_or(Ordering::Equal))
                .unwrap();
            (a + xs[mid]) * 0.5
        }
    }

    /// Update with raw eigenvalues (any scale). Returns smoothed fill in [0,1].
    pub fn update(&mut self, lambdas: &[f32]) -> f32 {
        let sample_dim = lambdas.len().max(1) as f32;
        let mut sum = 0.0f32;
        for &l in lambdas {
            sum += l.max(0.0);
        }
        let mean = (sum / sample_dim).max(1e-9);

        // Normalize by current mean to be scale free
        let norm: Vec<f32> = lambdas.iter().map(|&l| l.max(0.0) / mean).collect();
        let med = Self::median(norm.clone());

        // EMA for stats (slow)
        self.ema_mean = self.alpha_stats * mean + (1.0 - self.alpha_stats) * self.ema_mean;
        self.ema_median = self.alpha_stats * med + (1.0 - self.alpha_stats) * self.ema_median;

        // Adaptive threshold in normalized space.
        let thresh = match self.threshold_mode {
            ThresholdMode::CurrentRuntime => {
                // `ln` below is l/ema_mean (unit-free, ~1.0 for average eigenvalue).
                // `ema_median` is already in this normalized space.
                //
                // A flat identity spectrum should not count as "fully filled" just
                // because every sampled eigenvalue is positive. Require a mode to rise
                // meaningfully above the normalized mean before it counts as active.
                let norm_base = 1.0_f32.max(self.ema_median);
                (1.0 + self.rel_thresh * norm_base).max(1.0 + 1e-3)
            }
            ThresholdMode::FixedSurvival => {
                // Pinned rescue semantics: positive broad rank is meaningful fill.
                let base = self.ema_mean.max(self.ema_median);
                (self.rel_thresh * base.max(1e-6)).max(1e-3)
            }
        };

        // Active rank fraction
        let mut active = 0usize;
        for &l in lambdas {
            let ln = l.max(0.0) / self.ema_mean.max(1e-9);
            if ln > thresh {
                active += 1;
            }
        }
        let active_fraction = (active as f32 / sample_dim).clamp(0.0, 1.0);
        let fill_inst = if active > 0 {
            active_fraction.max(self.min_fill)
        } else {
            active_fraction
        };

        // Temporal smoothing and slight decay to avoid sticky 100%
        let dt = self.last_update.elapsed().as_secs_f32().max(1e-3);
        self.last_update = Instant::now();

        // decay term scaled by configured leak rate
        let leak = (self.leak_rate * dt).min(0.15);
        let decayed = (1.0 - leak) * self.ema_fill;

        self.ema_fill = self.alpha_fill * fill_inst + (1.0 - self.alpha_fill) * decayed;
        self.ema_fill.clamp(0.0, 1.0)
    }

    pub fn fill(&self) -> f32 {
        self.ema_fill
    }
    pub fn set_rel_thresh(&mut self, r: f32) {
        self.rel_thresh = r.max(0.01).min(0.9);
    }
    pub fn set_smoothing(&mut self, alpha_stats: f32, alpha_fill: f32) {
        self.alpha_stats = alpha_stats.clamp(0.01, 0.5);
        self.alpha_fill = alpha_fill.clamp(0.05, 0.8);
    }
    pub fn set_min_fill(&mut self, floor: f32) {
        self.min_fill = floor.clamp(0.0, 0.5);
    }
    pub fn set_leak_rate(&mut self, leak_rate: f32) {
        self.leak_rate = leak_rate.clamp(0.0, 0.2);
    }

    pub fn reset(&mut self) {
        self.ema_mean = 1.0;
        self.ema_median = 1.0;
        self.ema_fill = 0.0;
        self.last_update = Instant::now();
    }

    #[must_use]
    pub fn snapshot_v1(&self) -> EigenFillEstimatorSnapshotV1 {
        EigenFillEstimatorSnapshotV1 {
            dim: self.dim,
            ema_mean: self.ema_mean,
            ema_median: self.ema_median,
            ema_fill: self.ema_fill,
            alpha_stats: self.alpha_stats,
            alpha_fill: self.alpha_fill,
            rel_thresh: self.rel_thresh,
            min_fill: self.min_fill,
            leak_rate: self.leak_rate,
            threshold_mode: match self.threshold_mode {
                ThresholdMode::CurrentRuntime => "current_runtime",
                ThresholdMode::FixedSurvival => "fixed_survival",
            }
            .to_string(),
            last_update_age_ms: self
                .last_update
                .elapsed()
                .as_millis()
                .min(u128::from(u64::MAX)) as u64,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{EigenFillEstimator, ThresholdMode};

    #[test]
    fn identity_spectrum_does_not_count_as_fully_filled() {
        let mut estimator = EigenFillEstimator::new(8);
        let fill = estimator.update(&[1.0; 8]);
        assert!(
            fill <= 1.0e-6,
            "flat identity spectrum should not register as filled"
        );
    }

    #[test]
    fn dominant_modes_raise_fill_above_identity_floor() {
        let mut estimator = EigenFillEstimator::new(8);
        let identity_fill = estimator.update(&[1.0; 8]);
        estimator.reset();
        let dominant_fill = estimator.update(&[2.0, 1.6, 1.3, 1.1, 0.9, 0.7, 0.6, 0.5]);
        assert!(dominant_fill > identity_fill);
        assert!(dominant_fill > 0.0);
    }

    #[test]
    fn fixed_survival_mode_preserves_rescue_fill_semantics() {
        let mut estimator = EigenFillEstimator::fixed_survival(8);
        let fill = estimator.update(&[1.0; 8]);

        assert!(
            (0.09..=0.11).contains(&fill),
            "stable-core fixed survival should match pinned rescue's slow first-tick fill"
        );
    }

    #[test]
    fn fixed_survival_mode_uses_pinned_rescue_defaults() {
        let estimator = EigenFillEstimator::fixed_survival(8);

        assert_eq!(estimator.threshold_mode, ThresholdMode::FixedSurvival);
        assert!((estimator.rel_thresh - 0.12).abs() < f32::EPSILON);
        assert!((estimator.min_fill - 0.04).abs() < f32::EPSILON);
        assert!((estimator.alpha_stats - 0.05).abs() < f32::EPSILON);
        assert!((estimator.alpha_fill - 0.10).abs() < f32::EPSILON);
        assert!((estimator.leak_rate - 0.006).abs() < f32::EPSILON);
    }
}
