// src/homeostat.rs
// PI(D) gate with anti-windup, rate limiting, and high-water feedback from lanes.

use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct Homeostat {
    target: f32,      // target fill in [0,1]
    kp: f32, ki: f32, kd: f32,
    integ: f32,
    prev_err: f32,
    prev_t: Instant,
    gate: f32,        // current gate in [0,1]
    slew: f32,        // max gate change per second
    hw_bias: f32,     // extra clamp when queues overrun
}

impl Homeostat {
    pub fn new(target: f32, kp: f32, ki: f32, kd: f32) -> Self {
        Self {
            target: target.clamp(0.0, 1.0),
            kp, ki, kd,
            integ: 0.0,
            prev_err: 0.0,
            prev_t: Instant::now(),
            gate: 1.0,
            slew: 0.8,   // gate can change by at most 0.8 / s
            hw_bias: 0.0,
        }
    }

    pub fn set_slew(&mut self, per_sec: f32) { self.slew = per_sec.max(0.05).min(3.0); }

    /// Provide high-water information (0 = empty, 1 = > high watermark).
    pub fn set_highwater_bias(&mut self, q_frac: f32) {
        // Penalize gate if queues are near capacity independent of eigenfill
        self.hw_bias = (q_frac - 0.7).max(0.0) * 1.5; // strong clamp near full
    }

    /// Step the controller with current fill. Returns gate in [0,1].
    pub fn step(&mut self, fill: f32) -> f32 {
        let now = Instant::now();
        let dt = now.duration_since(self.prev_t).as_secs_f32().max(1e-3);
        self.prev_t = now;

        let err = (self.target - fill).clamp(-1.0, 1.0);

        // PI(D)
        self.integ += err * dt;
        // anti-windup: clamp integral by expected gate range / ki
        let integ_cap = 1.0f32 / (self.ki.abs().max(1e-6));
        self.integ = self.integ.clamp(-integ_cap, integ_cap);

        let deriv = (err - self.prev_err) / dt;
        self.prev_err = err;

        let raw = self.kp * err + self.ki * self.integ + self.kd * deriv;

        // Map to [0,1] with sigmoid-ish soft clip, then apply high-water bias
        let mut g = 0.5 + 0.5 * (raw.tanh());
        g = (g - self.hw_bias).clamp(0.0, 1.0);

        // Slew-rate limit for stability
        let max_delta = self.slew * dt;
        let delta = (g - self.gate).clamp(-max_delta, max_delta);
        self.gate = (self.gate + delta).clamp(0.0, 1.0);

        self.gate
    }

    pub fn gate(&self) -> f32 { self.gate }
}