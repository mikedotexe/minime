// src/spectral/eigenfill.rs
// Robust EigenFill with scale invariance, temporal smoothing, and rank thresholding.
#![allow(dead_code)]

use std::cmp::Ordering;
use std::time::Instant;

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
    // guard against stale updates
    last_update: Instant,
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
            rel_thresh: 0.06, // treat λ > 0.06×mean as "active" (lowered to count more eigenvalues)
            min_fill: 0.10,   // never report below 10% when any mode is active
            leak_rate: 0.005, // slower temporal decay so fill doesn't drain between measurements
            last_update: Instant::now(),
        }
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

        // Adaptive threshold tied to EMA(mean/median)
        let base = self.ema_mean.max(self.ema_median);
        let thresh = (self.rel_thresh * base.max(1e-6)).max(1e-3);

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
}
