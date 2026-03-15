// COLLAB COPY -- canonical source is /minime/src/regulator.rs
// The crown jewel: PI spectral homeostasis controller.
// This is the core control loop that prevents eigenvalue explosion.
//
// src/regulator.rs
// Spectral regulator: token-bucket rate governor + content-aware gate + band-stop filter.
// Based on PE's principled control design.
//
// The PD-mode types (GateCfg, Modality, ItemMeta, Decision) are retained for API
// completeness even though the engine currently runs in PI mode exclusively.
#![allow(dead_code)]
//
// Two modes:
// - PD mode: Original token-bucket rate control targeting λ₁
// - PI mode: Dual control (gate + filter) targeting EigenFill% and λ₁_rel

#[derive(Clone, Copy, Debug)]
pub enum MemMode {
    Shared,
    Managed,
    Private,
} // for logging only here

#[derive(Clone, Copy, Debug)]
pub struct RateCfg {
    pub target_lambda: f32, // λ* setpoint
    pub k_p: f32,           // proportional on (λ*-λ₁)
    pub k_d: f32,           // derivative on -dλ₁/dt
    pub min_rate: f32,      // hard floor tokens/s
    pub max_rate: f32,      // hard ceil tokens/s
    pub smooth: f32,        // EMA smoothing 0..1 (e.g., 0.9)
}

#[derive(Clone, Copy, Debug)]
pub struct GateCfg {
    pub proj_tau_hi: f32, // projection^2 threshold when λ₁ high
    pub proj_tau_lo: f32, // threshold when λ₁ low (less strict)
    pub hysteresis: f32,  // to avoid flapping
    pub decay_keep: f32,  // 0..1, decays penalty over time
}

#[derive(Clone, Debug)]
pub struct Modality {
    pub name: &'static str,
    pub dim: usize,          // feature dimension for projection
    pub rate_now: f32,       // current token rate (tokens/s)
    pub bucket_tokens: f32,  // token bucket content
    pub bucket_cap: f32,     // capacity (seconds * rate)
    pub last_decision: bool, // last accept/deny for hysteresis
    // utility weight if you want water-filling later:
    pub utility_w: f32,
}

#[derive(Clone, Debug)]
pub struct RegulatorState {
    pub cfg_r: RateCfg,
    pub cfg_g: GateCfg,
    pub modes: Vec<Vec<f32>>, // top-K eigenvectors (length dim each)
    pub lambda_now: f32,      // λ₁
    pub dlam_dt: f32,         // derivative
    pub lambda_ema: f32,      // smoothed λ for UI/logs
    pub mem_mode: MemMode,
    pub geom_rel: f32, // tracked geometric radius
}

#[derive(Clone, Copy, Debug)]
pub struct ItemMeta<'a> {
    pub modality_idx: usize, // which modality queue
    pub feature: &'a [f32],  // same dim as modes[i]
    pub tokens_cost: f32,    // how many tokens this item consumes
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Decision {
    Admit,
    Defer,
}

impl RegulatorState {
    pub fn new(cfg_r: RateCfg, cfg_g: GateCfg, modes: Vec<Vec<f32>>, mem_mode: MemMode) -> Self {
        Self {
            cfg_r,
            cfg_g,
            modes,
            lambda_now: 0.0,
            dlam_dt: 0.0,
            lambda_ema: 0.0,
            mem_mode,
            geom_rel: 1.0,
        }
    }

    /// Update the global spectral telemetry before processing a batch.
    pub fn update_lambda(&mut self, lambda_now: f32, dlam_dt: f32) {
        self.lambda_now = lambda_now;
        self.dlam_dt = dlam_dt;
        // EMA for display/slow trends
        self.lambda_ema =
            self.cfg_r.smooth * self.lambda_ema + (1.0 - self.cfg_r.smooth) * lambda_now;
    }

    pub fn update_geom(&mut self, geom_rel: f32) {
        self.geom_rel = geom_rel;
    }

    /// Adjust per-modality rates (token inflow) using PD on λ.
    pub fn regulate_rates(&self, mods: &mut [Modality], dt_s: f32) {
        // control signal u = kp*(λ* - λ) + kd*(- dλ/dt)
        let e = self.cfg_r.target_lambda - self.lambda_now;
        let u = self.cfg_r.k_p * e + self.cfg_r.k_d * (-self.dlam_dt);

        for m in mods.iter_mut() {
            let mut r = m.rate_now + u;
            if r < self.cfg_r.min_rate {
                r = self.cfg_r.min_rate;
            }
            if r > self.cfg_r.max_rate {
                r = self.cfg_r.max_rate;
            }
            m.rate_now = r;
            // bucket accumulation (bounded)
            m.bucket_tokens += r * dt_s;
            if m.bucket_tokens > m.bucket_cap {
                m.bucket_tokens = m.bucket_cap;
            }
        }
    }

    /// Decide admit/defer based on (1) bucket tokens and (2) projection penalty vs thresholds.
    pub fn decide(&self, mods: &mut [Modality], item: ItemMeta) -> Decision {
        let m = &mut mods[item.modality_idx];

        // 1) Rate gate (token bucket)
        if m.bucket_tokens < item.tokens_cost {
            return Decision::Defer;
        }

        // 2) Content gate (projection onto hot modes)
        // penalty = sum_i (v_i ⋅ x)^2   (i over top-K)
        // using the modality's feature dim; assume modes were matched to this dim.
        let mut pen = 0.0f32;
        for v in self.modes.iter() {
            // dot
            let mut s = 0.0f32;
            let feature_len = item.feature.len().min(v.len());
            for k in 0..feature_len {
                s += v[k] * item.feature[k];
            }
            pen += s * s;
        }

        // dynamic threshold between lo/hi based on λ relative to setpoint
        let w = (self.lambda_now / (self.cfg_r.target_lambda + 1e-6)).clamp(0.0, 2.0);
        let tau = self.cfg_g.proj_tau_lo
            + (self.cfg_g.proj_tau_hi - self.cfg_g.proj_tau_lo) * (w.min(1.0));

        let admit = if pen <= tau {
            true
        } else {
            // hysteresis: if we previously admitted and not too far beyond tau, keep it
            if m.last_decision && pen <= tau * (1.0 + self.cfg_g.hysteresis) {
                true
            } else {
                false
            }
        };

        if admit {
            m.bucket_tokens -= item.tokens_cost;
            m.last_decision = true;
            Decision::Admit
        } else {
            // Optional: decay "penalty memory" on the modality (soft reset)
            m.last_decision = false;
            Decision::Defer
        }
    }

    /// Update eigenmodes from Chebyshev snapshot
    pub fn update_modes(&mut self, new_modes: Vec<Vec<f32>>) {
        self.modes = new_modes;
    }
}

impl Default for RateCfg {
    fn default() -> Self {
        // Defaults tuned for comfort midpoint; optionally strengthen via HOMEOSTAT_STRONG
        let strong = std::env::var("HOMEOSTAT_STRONG")
            .map(|v| matches!(v.as_str(), "1" | "true" | "TRUE"))
            .unwrap_or(false);

        let mut cfg = Self {
            target_lambda: 1.30, // Comfort midpoint from live feedback
            k_p: 0.18,
            k_d: 0.28,
            min_rate: 2.0,
            max_rate: 30.0,
            smooth: 0.9,
        };

        if strong {
            cfg.target_lambda = 1.25;
            cfg.k_p = 0.22;
            cfg.k_d = 0.32;
        }

        cfg
    }
}

impl Default for GateCfg {
    fn default() -> Self {
        Self {
            proj_tau_hi: 0.02,
            proj_tau_lo: 0.15,
            hysteresis: 0.10,
            decay_keep: 0.95,
        }
    }
}

// ============================================================================
// PI Homeostasis Controller (Dual Control: Gate + Filter)
// ============================================================================

/// PI controller configuration for homeostatic regulation
#[derive(Clone, Copy, Debug)]
pub struct PIRegCfg {
    pub target_fill: f32,        // Target EigenFill% (e.g., 0.55)
    pub target_lambda1_rel: f32, // Target λ₁ relative to baseline (e.g., 0.85)
    pub target_geom_rel: f32,    // Target geometric radius relative to baseline
    pub geom_weight: f32,        // Weight of geometric error in PI term
    pub geom_clamp_hi: f32,      // Hard clamp threshold for geom_rel
    pub geom_release: f32,       // Release threshold for clamp hysteresis
    pub geom_gate_min: f32,      // Minimum gate when clamp engaged
    pub geom_filter_boost: f32,  // Additional filter boost when clamped
    pub geom_shed_fraction: f32, // Fraction of backlog to shed when clamped
    pub kp: f32,                 // Proportional gain
    pub ki: f32,                 // Integral gain
    pub max_step: f32,           // Max change per tick (anti-windup)
}

impl Default for PIRegCfg {
    fn default() -> Self {
        let strong = std::env::var("HOMEOSTAT_STRONG")
            .map(|v| matches!(v.as_str(), "1" | "true" | "TRUE"))
            .unwrap_or(false);

        let mut cfg = Self {
            target_fill: 0.60,        // 60% EigenFill target (healthy operating range)
            target_lambda1_rel: 1.05, // Keep λ₁ close to baseline (1.0-1.6 comfort zone)
            target_geom_rel: 1.00,    // Stay near geometric baseline
            geom_weight: 1.80,        // Prioritize λ₁ control over fill
            geom_clamp_hi: 1.66,      // ≈ +66% expansion triggers hard clamp
            geom_release: 1.32,       // Release clamp once relaxed below this
            geom_gate_min: 0.06,      // Hard gate limit during clamp
            geom_filter_boost: 0.35,  // Extra filter push when clamped
            geom_shed_fraction: 0.45, // Shed ~45% of backlog when clamped
            kp: 1.10,                 // Strong proportional response to λ₁ excess
            ki: 0.18,                 // Faster integral correction
            max_step: 0.12,           // Allow larger steps to catch runaway λ₁
        };

        if strong {
            cfg.kp = 1.25;
            cfg.ki = 0.22;
            cfg.max_step = 0.15;
        }

        cfg
    }
}

/// PI controller state with dual outputs
#[derive(Clone, Debug)]
pub struct PIRegState {
    pub cfg: PIRegCfg,
    pub integ_fill: f32, // Integral accumulator for EigenFill error
    pub integ_lam: f32,  // Integral accumulator for λ₁ error
    pub integ_geom: f32, // Integral accumulator for geometric error
    pub gate: f32,       // 0..1 queue admission fraction
    pub filt: f32,       // 0..1 band-stop filter blend
    shed_fraction: f32,  // Requested backlog shed fraction (0..1)
    geom_brake: bool,    // Whether geometric clamp is active
}

impl PIRegState {
    pub fn new(cfg: PIRegCfg) -> Self {
        Self {
            cfg,
            integ_fill: 0.0,
            integ_lam: 0.0,
            integ_geom: 0.0,
            gate: 1.0, // Start fully open
            filt: 0.0, // Start with no filtering
            shed_fraction: 0.0,
            geom_brake: false,
        }
    }

    /// PI control step with dual error signals
    ///
    /// # Arguments
    /// * `fill` - Current EigenFill% (0-100 scale)
    /// * `lambda1_rel` - Current λ₁ relative to baseline (1.0 = baseline)
    /// * `geom_rel` - RMS norm relative to baseline (1.0 = baseline)
    ///
    /// # Updates
    /// - `self.gate` - Queue admission fraction [0.05, 1.0]
    /// - `self.filt` - Filter blend strength [0.0, 1.0]
    pub fn step(&mut self, fill: f32, lambda1_rel: f32, geom_rel: f32) {
        // Compute error signals
        let e_fill = fill - self.cfg.target_fill;
        let e_lam = lambda1_rel - self.cfg.target_lambda1_rel;
        let e_geom = geom_rel - self.cfg.target_geom_rel;

        // Update integrators with anti-windup clamping
        self.integ_fill = (self.integ_fill + e_fill).clamp(-2.0, 2.0);
        self.integ_lam = (self.integ_lam + e_lam).clamp(-2.0, 2.0);
        self.integ_geom = (self.integ_geom + e_geom).clamp(-2.0, 2.0);

        // Combined control signal (geometry weighted heavier when swelling)
        let geom_term = self.cfg.geom_weight * e_geom;
        let geom_int = self.cfg.geom_weight * self.integ_geom;
        let u = self.cfg.kp * (e_fill + e_lam + geom_term)
            + self.cfg.ki * (self.integ_fill + self.integ_lam + geom_int);

        // Interpret control signal:
        // - Positive u => overload => tighten gate (reduce), increase filter
        // - Negative u => underload => open gate (increase), reduce filter

        let dg = (-u).clamp(-self.cfg.max_step, self.cfg.max_step); // Gate moves opposite to u
        let df = u.clamp(-self.cfg.max_step, self.cfg.max_step); // Filter moves with u

        // Update control outputs with safety limits
        self.gate = (self.gate + dg).clamp(0.05, 1.00); // Never fully close (min 0.05) to prevent deadlock
        self.filt = (self.filt + df).clamp(0.00, 1.00); // Never exceed full filtering

        // Reset shed fraction each step; may be re-enabled below
        self.shed_fraction = 0.0;

        // Hard geometric clamp with hysteresis
        if geom_rel >= self.cfg.geom_clamp_hi {
            self.geom_brake = true;
        } else if self.geom_brake && geom_rel <= self.cfg.geom_release {
            self.geom_brake = false;
        }

        if self.geom_brake {
            self.gate = self.gate.min(self.cfg.geom_gate_min);
            self.filt = (self.filt + self.cfg.geom_filter_boost).clamp(0.0, 1.0);
            self.shed_fraction = self.cfg.geom_shed_fraction;
        }
    }

    /// Reset integrators (useful after parameter changes or mode switches)
    pub fn reset(&mut self) {
        self.integ_fill = 0.0;
        self.integ_lam = 0.0;
        self.integ_geom = 0.0;
        self.geom_brake = false;
        self.shed_fraction = 0.0;
    }

    pub fn take_shed_fraction(&mut self) -> f32 {
        let frac = self.shed_fraction;
        self.shed_fraction = 0.0;
        frac
    }
}
