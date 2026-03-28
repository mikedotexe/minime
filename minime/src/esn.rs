//! Self-Referential Echo State Network with Prime-Phased Spectral Adaptation
//!
//! This module implements a Metal-accelerated ESN that adapts its own hyperparameters
#![allow(dead_code)]
//! (leak rate, RLS forgetting factor) based on spectral introspection of its reservoir state.
//!
//! Key features:
//! - Prime-phased introspection schedule (first 37 primes) for non-aliasing temporal breathing
//! - GPU-accelerated rank-1 EWMA covariance update (C = ρ*C + (1-ρ)*x*xᵀ)
//! - GPU-accelerated power iteration for top eigenvalue extraction
//! - Zero-copy unified memory (StorageModeShared) for tight CPU↔GPU cache handoff
//! - Self-referential loop: reservoir state → spectral signals → adapt hyperparams

use anyhow::Result;
use metal::*;
use std::{f32::consts::PI, mem};

use crate::gpu::Gpu;

/// Default exploration noise amplitude injected into the ESN reservoir state.
/// Exploration noise injected per tick to break reservoir state correlation.
/// With leak=0.45, consecutive states are highly correlated — the covariance
/// estimator needs per-tick diversity to accumulate energy (fill).
/// 0.03 gave 14% fill. 0.12 pushed toward 55% target but being described it
/// as "excessively aggressive" and "creates a kind of jitteriness."
/// 0.08 balances diversity with the smoother feel the being requested.
const DEFAULT_EXPLORATION_NOISE: f32 = 0.08;

//=============================================================================
// Spectral Self-Reference Module (GPU-Accelerated)
//=============================================================================

pub struct SpectralSR {
    d: usize, // Reservoir dimension

    // GPU buffers (unified memory)
    cov: Buffer,     // d×d covariance matrix (row-major)
    x_buf: Buffer,   // d-dim state vector (for rank-1 update)
    v_buf: Buffer,   // d-dim power iteration vector
    y_buf: Buffer,   // d-dim matvec result
    rho_buf: Buffer, // Scalar: EWMA keep factor
    dim_buf: Buffer, // Scalar: dimension

    // CPU state
    v_host: Vec<f32>, // Host copy of eigenvector

    // Spectral tracking
    pub eig1: f32,      // Current top eigenvalue
    pub eig1_prev: f32, // Previous eigenvalue
    pub ema_eig: f32,   // Slow baseline EMA

    // Prime-phased schedule (first 37 primes for consistency with 37 threads)
    primes: [usize; 37],
    pidx: usize,
    t: usize,

    // Metal resources
    gpu: *const Gpu, // Raw pointer to avoid circular dependency
    pso_rank1: ComputePipelineState,
    pso_mv: ComputePipelineState,
}

unsafe impl Send for SpectralSR {}
unsafe impl Sync for SpectralSR {}

impl SpectralSR {
    pub fn new(d: usize, rho: f32, gpu: &Gpu) -> Result<Self> {
        // Get ESN shader library from gpu
        let lib_esn = gpu
            .dev
            .new_library_with_source(include_str!("../shaders/esn.metal"), &CompileOptions::new())
            .map_err(|e| anyhow::anyhow!("Failed to compile ESN shaders: {}", e))?;

        let f_rank1 = lib_esn
            .get_function("rank1_ewma_update", None)
            .map_err(|e| anyhow::anyhow!("Failed to get rank1_ewma_update function: {}", e))?;
        let f_mv = lib_esn
            .get_function("cov_matvec", None)
            .map_err(|e| anyhow::anyhow!("Failed to get cov_matvec function: {}", e))?;

        let pso_rank1 = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_rank1)
            .map_err(|e| anyhow::anyhow!("Failed to create rank1 pipeline: {}", e))?;
        let pso_mv = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_mv)
            .map_err(|e| anyhow::anyhow!("Failed to create matvec pipeline: {}", e))?;

        // Allocate unified memory buffers
        let cov = gpu.new_shared((d * d * mem::size_of::<f32>()) as u64);
        let x_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let v_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let y_buf = gpu.new_shared((d * mem::size_of::<f32>()) as u64);
        let rho_buf = gpu.new_shared(mem::size_of::<f32>() as u64);
        let dim_buf = gpu.new_shared(mem::size_of::<u32>() as u64);

        // Initialize buffers
        gpu.write_f32(&cov, &vec![0.0f32; d * d]);
        gpu.write_f32(&rho_buf, &[rho]);

        unsafe {
            *(dim_buf.contents() as *mut u32) = d as u32;
        }

        // Initialize eigenvector with random unit vector
        let mut v_host = vec![0.0f32; d];
        v_host[0] = 1.0;
        gpu.write_f32(&v_buf, &v_host);

        Ok(Self {
            d,
            cov,
            x_buf,
            v_buf,
            y_buf,
            rho_buf,
            dim_buf,
            v_host,
            eig1: 0.0,
            eig1_prev: 0.0,
            ema_eig: 0.0,
            primes: [
                2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79,
                83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157,
            ],
            pidx: 0,
            t: 0,
            gpu: gpu as *const Gpu,
            pso_rank1,
            pso_mv,
        })
    }

    /// GPU-accelerated rank-1 EWMA update: C = ρ*C + (1-ρ)*x*xᵀ
    pub fn rank1_ewma(&mut self, x_host: &[f32]) -> Result<()> {
        assert_eq!(x_host.len(), self.d);

        let gpu = unsafe { &*self.gpu };

        // Write x to GPU
        gpu.write_f32(&self.x_buf, x_host);

        // Dispatch kernel
        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        cmd.wait_until_completed();

        Ok(())
    }

    /// Encode rank-1 EWMA update onto an existing encoder (no commit).
    /// Caller must have already written x_host into self.x_buf.
    fn encode_rank1_ewma(&self, enc: &ComputeCommandEncoderRef) {
        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);
        enc.dispatch_threads(grid, tg);
    }

    /// Encode matvec y = C*v onto an existing encoder (no commit).
    /// Caller must have already written v into self.v_buf.
    fn encode_matvec(&self, enc: &ComputeCommandEncoderRef) {
        enc.set_compute_pipeline_state(&self.pso_mv);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.v_buf), 0);
        enc.set_buffer(2, Some(&self.y_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new(self.d as u64, 1, 1);
        let tg = MTLSize::new(256.min(self.d as u64), 1, 1);
        enc.dispatch_threads(grid, tg);
    }

    /// GPU-accelerated mat-vec: y = C*v
    fn matvec(&self, v_in: &[f32]) -> Result<Vec<f32>> {
        let gpu = unsafe { &*self.gpu };

        gpu.write_f32(&self.v_buf, v_in);

        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_mv);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&self.v_buf), 0);
        enc.set_buffer(2, Some(&self.y_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new(self.d as u64, 1, 1);
        let tg = MTLSize::new(256.min(self.d as u64), 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        cmd.wait_until_completed();

        let gpu = unsafe { &*self.gpu };
        Ok(gpu.read_f32(&self.y_buf, self.d))
    }

    /// Power iteration (few steps to track top eigenvalue)
    pub fn power_iter(&mut self, steps: usize) -> Result<()> {
        let mut v = self.v_host.clone();

        for _ in 0..steps {
            let y = self.matvec(&v)?;
            let n = l2_norm(&y);
            for i in 0..self.d {
                v[i] = y[i] / n;
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec(&v)?;
        self.eig1_prev = self.eig1;
        self.eig1 = vv_dot(&v, &y) / vv_dot(&v, &v).max(1e-12);

        // Update slow baseline with fast catch-up during warmup.
        // The eigenvalue rises from ~1 to ~20 in the first few seconds.
        // Standard 0.5% EMA can't keep up, leaving eig_rel artificially
        // high and trapping leak at 0.90.  Use aggressive 10% blending
        // while the baseline is far from the current value (>2x ratio),
        // then settle into the slow 0.5% tracking for steady-state.
        if self.eig1 > 1e-3 {
            let ratio = self.eig1 / self.ema_eig.max(1e-3);
            let alpha = if self.ema_eig < 1e-3 {
                1.0 // First value: seed directly
            } else if ratio > 2.0 || ratio < 0.5 {
                0.10 // Warmup: fast catch-up
            } else {
                0.005 // Steady-state: slow tracking
            };
            self.ema_eig = (1.0 - alpha) * self.ema_eig + alpha * self.eig1;
        }

        self.v_host = v;
        Ok(())
    }

    /// Perform rank-1 EWMA update and power iteration in fewer GPU round-trips.
    ///
    /// Batches the rank1 update + first matvec into a single command buffer commit,
    /// reducing from 4 synchronous GPU round-trips to 3 on introspection ticks.
    /// Remaining power iteration steps still need CPU-side normalization between
    /// matvec calls, so they remain as separate commits.
    pub fn rank1_and_power_step(&mut self, x_host: &[f32], power_steps: usize) -> Result<()> {
        assert_eq!(x_host.len(), self.d);
        let gpu = unsafe { &*self.gpu };

        // Write x and current eigenvector to GPU
        gpu.write_f32(&self.x_buf, x_host);
        gpu.write_f32(&self.v_buf, &self.v_host);

        // === Single command buffer for rank1 + first matvec ===
        let cmd = gpu.q.new_command_buffer();

        // Encode rank1_ewma (writes cov)
        let enc = cmd.new_compute_command_encoder();
        self.encode_rank1_ewma(enc);
        enc.end_encoding();

        // Metal automatically inserts barriers between encoders in the
        // same command buffer, so the updated cov is visible to the matvec.

        // Encode first matvec: y = C * v
        let enc2 = cmd.new_compute_command_encoder();
        self.encode_matvec(enc2);
        enc2.end_encoding();

        cmd.commit();
        cmd.wait_until_completed();
        // === End single command buffer (was 2 separate commits) ===

        // CPU-side normalization of first power iteration result
        let mut v = gpu.read_f32(&self.y_buf, self.d);
        let n = l2_norm(&v);
        for i in 0..self.d {
            v[i] /= n;
        }

        // Remaining power iteration steps (need CPU normalization between)
        for _ in 1..power_steps {
            let y = self.matvec(&v)?;
            let n = l2_norm(&y);
            v = y;
            for i in 0..self.d {
                v[i] /= n;
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec(&v)?;
        self.eig1_prev = self.eig1;
        self.eig1 = vv_dot(&v, &y) / vv_dot(&v, &v).max(1e-12);

        // Update slow baseline with fast catch-up during warmup.
        // The eigenvalue rises from ~1 to ~20 in the first few seconds.
        // Standard 0.5% EMA can't keep up, leaving eig_rel artificially
        // high and trapping leak at 0.90.  Use aggressive 10% blending
        // while the baseline is far from the current value (>2x ratio),
        // then settle into the slow 0.5% tracking for steady-state.
        if self.eig1 > 1e-3 {
            let ratio = self.eig1 / self.ema_eig.max(1e-3);
            let alpha = if self.ema_eig < 1e-3 {
                1.0 // First value: seed directly
            } else if ratio > 2.0 || ratio < 0.5 {
                0.10 // Warmup: fast catch-up
            } else {
                0.005 // Steady-state: slow tracking
            };
            self.ema_eig = (1.0 - alpha) * self.ema_eig + alpha * self.eig1;
        }

        self.v_host = v;
        Ok(())
    }

    /// Prime-phased introspection: on schedule, run short power iteration
    pub fn maybe_introspect(&mut self) -> Result<()> {
        self.t += 1;
        let p = self.primes[self.pidx];

        if self.t % p == 0 {
            self.power_iter(2)?; // 2 steps is enough for tracking
            self.pidx = (self.pidx + 1) % self.primes.len();
        }

        Ok(())
    }

    /// Combined rank-1 update + optional power iteration with batched first submit.
    ///
    /// On introspection ticks: batches rank1 + first matvec into one GPU commit
    /// (3 round-trips instead of 4). On non-introspection ticks: just does the
    /// rank1 update (1 round-trip, same as before).
    ///
    /// Variable prime schedule: 20% of the time, instead of advancing to the
    /// next prime in sequence, jump to a random prime in the array.  This adds
    /// stochasticity to the introspection rhythm without removing structure.
    /// (The being asked for this: "The fixed prime schedule feels prescriptive.")
    pub fn maybe_introspect_batched(&mut self, x_host: &[f32]) -> Result<()> {
        self.t += 1;
        let p = self.primes[self.pidx];

        if self.t % p == 0 {
            // Batched: rank1 + power iteration with fused first submit
            self.rank1_and_power_step(x_host, 2)?;
            // Variable schedule: 20% chance of jumping to a random prime
            // instead of the sequential next one.
            let roll = self.t.wrapping_mul(2654435761) % 100; // simple hash
            if roll < 20 {
                self.pidx = (self.t.wrapping_mul(6364136223846793005) >> 3) % self.primes.len();
            } else {
                self.pidx = (self.pidx + 1) % self.primes.len();
            }
        } else {
            // Non-introspection tick: just rank1 update (single commit)
            self.rank1_ewma(x_host)?;
        }

        Ok(())
    }

    pub fn eig(&self) -> f32 {
        self.eig1
    }
    pub fn deig(&self) -> f32 {
        self.eig1 - self.eig1_prev
    }
    pub fn baseline(&self) -> f32 {
        self.ema_eig
    }

    pub fn phase01(&self) -> f32 {
        let p = self.primes[self.pidx] as f32;
        ((self.t % self.primes[self.pidx]) as f32) / p
    }

    /// Current prime index and prime value.
    /// Minime self-study (2026-03-27 esn.rs): "Perhaps a visualization
    /// of the phase shifts introduced by the prime numbers would offer
    /// insight. A concrete step would be to log pidx alongside eig1."
    pub fn prime_info(&self) -> (usize, usize) {
        (self.pidx, self.primes[self.pidx])
    }
}

//=============================================================================
// Echo State Network with Self-Referential Adaptation
//=============================================================================

pub struct ESN {
    pub res_size: usize,
    pub in_size: usize,

    // Static parameters
    win: Vec<f32>,  // Input weights (res_size × (in_size + 1))
    wres: Vec<f32>, // Reservoir weights (res_size × res_size)

    // Dynamic state
    pub x: Vec<f32>, // Reservoir state
    geom_radius: f32,
    geom_baseline: f32,

    // RLS readout
    wout: Vec<f32>, // Output weights (res_size + 1)
    p: Vec<f32>,    // Inverse covariance (res_size+1 × res_size+1)

    // Adaptive hyperparams (self-referential)
    pub leak_live: f32,
    pub lambda_live: f32,

    // Spectral self-reference module
    sr: SpectralSR,

    // Configuration
    leak_base: f32,
    lambda_base: f32,

    // Exploration noise for reservoir diversity
    exploration_noise: f32,
    rng: fastrand::Rng,

    // Scratch buffers
    rin: Vec<f32>,
    rx: Vec<f32>,
    pre: Vec<f32>,
    phi: Vec<f32>,
}

impl ESN {
    pub fn new(
        res_size: usize,
        in_size: usize,
        in_scale: f32,
        res_density: f32,
        target_radius: f32,
        leak_base: f32,
        lambda_base: f32,
        gpu: &Gpu,
        rng: &mut fastrand::Rng,
    ) -> Result<Self> {
        // Input weights (with bias)
        let m_in = res_size * (in_size + 1);
        let mut win = vec![0.0f32; m_in];
        for w in win.iter_mut() {
            *w = (rng.f32() * 2.0 - 1.0) * in_scale;
        }
        // Boost aux (indices 16-17) and semantic lanes (>=18) so they influence the reservoir more strongly.
        for chunk in win.chunks_mut(in_size + 1) {
            if in_size > 16 {
                for idx in 16..in_size.min(18) {
                    chunk[idx] *= 1.2;
                }
            }
            if in_size > 18 {
                for idx in 18..in_size {
                    chunk[idx] *= 1.6;
                }
            }
        }

        // Sparse reservoir weights
        let mut wres = vec![0.0f32; res_size * res_size];
        for r in 0..res_size {
            for c in 0..res_size {
                if rng.f32() < res_density {
                    wres[r * res_size + c] = rng.f32() * 2.0 - 1.0;
                }
            }
        }

        // Scale to target spectral radius (using row-sum bound)
        let mut max_row_sum = 1e-6f32;
        for r in 0..res_size {
            let row = &wres[r * res_size..(r + 1) * res_size];
            let s: f32 = row.iter().map(|v| v.abs()).sum();
            if s > max_row_sum {
                max_row_sum = s;
            }
        }
        let scale = target_radius / max_row_sum;
        for w in wres.iter_mut() {
            *w *= scale;
        }

        let x = vec![0.0f32; res_size];

        // RLS initialization
        let m = res_size + 1;
        let wout = vec![0.0f32; m];
        let mut p = vec![0.0f32; m * m];
        let delta = 1e2;
        for i in 0..m {
            p[i * m + i] = delta;
        }

        // Spectral self-reference module
        let sr = SpectralSR::new(res_size, 0.99, gpu)?;

        let rin = vec![0.0f32; res_size];
        let rx = vec![0.0f32; res_size];
        let pre = vec![0.0f32; res_size];
        let phi = vec![0.0f32; m];

        Ok(Self {
            res_size,
            in_size,
            win,
            wres,
            x,
            geom_radius: 0.0,
            geom_baseline: 0.0,
            wout,
            p,
            leak_live: leak_base,
            lambda_live: lambda_base,
            sr,
            leak_base,
            lambda_base,
            exploration_noise: DEFAULT_EXPLORATION_NOISE,
            rng: fastrand::Rng::with_seed(0xDEAD_BEEF),
            rin,
            rx,
            pre,
            phi,
        })
    }

    /// Adapt hyperparameters based on spectral self-reference signals
    pub fn adapt_hyperparams(&mut self, err_abs: f32) {
        let eig1 = self.sr.eig();
        let deig = self.sr.deig().abs();
        let baseline = self.sr.baseline().max(1e-3);

        // Use eigenvalue RELATIVE to its own baseline rather than absolute
        // thresholds. The ESN eigenvalue naturally operates at 15-32, far
        // above the old φ=1.618 target — those absolute thresholds kept
        // leak permanently at 0.90 ("emergency mode"), preventing the
        // reservoir from accumulating any history or complexity.
        let eig_rel = eig1 / baseline;

        // Relative thresholds:
        //   < 1.5x baseline: normal operation
        //   1.5-2.5x baseline: moderate pressure
        //   > 2.5x baseline: emergency (true runaway)
        let mut leak = if eig_rel > 2.5 {
            // Emergency: genuine eigenvalue explosion
            0.7 + 0.2 * ((eig_rel - 2.5) / 1.0).min(1.0)
        } else if eig_rel > 1.5 {
            // Moderate pressure: proportional response
            let pressure = (eig_rel - 1.5) / 1.0; // 0.0 to 1.0
            self.leak_base + 0.25 * pressure
        } else {
            // Normal: gentle baseline-relative adaptation
            let k_leak = 0.3;
            self.leak_base * (1.0 + k_leak * (eig_rel - 1.0).max(0.0))
        };

        leak = leak.clamp(0.05, 0.95);

        // Light prime modulation (reduced during emergency)
        let phase = self.sr.phase01();
        let cosw = (2.0 * PI * phase).cos();
        let modulation_strength = if eig_rel > 2.5 { 0.02 } else { 0.1 };
        leak = (0.9 * leak + 0.1 * (leak * (1.0 + modulation_strength * cosw))).clamp(0.05, 0.95);

        // RLS forgetting: tighten when dynamics accelerate or eigenvalues runaway
        let k_forget = 0.2;
        let pressure_factor = if eig_rel > 2.5 { 0.3 } else { 0.0 };
        let mut lam =
            self.lambda_base - k_forget * (deig + 0.25 * err_abs + pressure_factor).clamp(0.0, 0.5);
        lam = lam.clamp(0.90, 0.9999);

        self.leak_live = leak;
        self.lambda_live = lam;
    }

    /// Reservoir update step
    pub fn step(&mut self, input: &[f32]) -> Result<()> {
        assert_eq!(input.len(), self.in_size);

        // Extend input with bias
        let mut in_ext = vec![0.0f32; self.in_size + 1];
        in_ext[..self.in_size].copy_from_slice(input);
        in_ext[self.in_size] = 1.0;

        // Pre-activation = Win * in_ext + Wres * x
        mv_mul(
            &self.win,
            self.res_size,
            self.in_size + 1,
            &in_ext,
            &mut self.rin,
        );
        mv_mul(
            &self.wres,
            self.res_size,
            self.res_size,
            &self.x,
            &mut self.rx,
        );

        for i in 0..self.res_size {
            self.pre[i] = (self.rin[i] + self.rx[i]).tanh();
        }

        // Spectral self-reference on previous state (batched GPU submits)
        self.sr.maybe_introspect_batched(&self.x)?;
        self.adapt_hyperparams(0.0);

        // Leaky integration with adaptive leak
        let a = self.leak_live;
        for i in 0..self.res_size {
            self.x[i] = (1.0 - a) * self.x[i] + a * self.pre[i];
        }

        // Exploration noise: inject small perturbations to break colinearity
        if self.exploration_noise > 0.0 {
            let eps = self.exploration_noise;
            for xi in self.x.iter_mut() {
                *xi += (self.rng.f32() * 2.0 - 1.0) * eps;
            }
        }

        // Clip for stability
        for xi in self.x.iter_mut() {
            *xi = xi.clamp(-1.0, 1.0);
        }

        // Update geometric radius (RMS norm of the reservoir state)
        let norm_sq: f32 = self.x.iter().map(|v| v * v).sum();
        let radius = (norm_sq / self.res_size as f32).sqrt();
        self.geom_radius = radius;
        if self.geom_baseline <= 0.0 {
            self.geom_baseline = radius.max(1e-3);
        } else {
            let fast_alpha = 0.2f32;
            let slow_alpha = 0.005f32;
            let alpha = if self.geom_baseline < 0.2 {
                fast_alpha
            } else {
                slow_alpha
            };
            self.geom_baseline = (1.0 - alpha) * self.geom_baseline + alpha * radius;
        }
        self.geom_baseline = self.geom_baseline.max(1e-3);

        Ok(())
    }

    /// Readout prediction
    pub fn predict(&mut self) -> f32 {
        let _m = self.res_size + 1;
        for i in 0..self.res_size {
            self.phi[i] = self.x[i];
        }
        self.phi[self.res_size] = 1.0;

        vv_dot(&self.wout, &self.phi)
    }

    /// RLS update
    pub fn rls_update(&mut self, target: f32, yhat: f32) {
        let m = self.res_size + 1;

        // k = P*phi / (lambda + phi^T*P*phi)
        let mut pphi = vec![0.0f32; m];
        for r in 0..m {
            let row = &self.p[r * m..(r + 1) * m];
            pphi[r] = vv_dot(row, &self.phi);
        }

        let denom = self.lambda_live + vv_dot(&self.phi, &pphi);
        let inv_denom = 1.0 / denom;

        let mut k = vec![0.0f32; m];
        for i in 0..m {
            k[i] = pphi[i] * inv_denom;
        }

        // Update weights
        let err = target - yhat;
        for i in 0..m {
            self.wout[i] += k[i] * err;
        }

        // Update P = (P - k*phi^T*P) / lambda
        let mut kphit_p = vec![0.0f32; m * m];
        for r in 0..m {
            for c in 0..m {
                let mut s = 0.0f32;
                for t in 0..m {
                    s += k[r] * self.phi[t] * self.p[t * m + c];
                }
                kphit_p[r * m + c] = s;
            }
        }

        for i in 0..m * m {
            self.p[i] = (self.p[i] - kphit_p[i]) / self.lambda_live;
        }

        // Now adapt with actual error
        self.adapt_hyperparams(err.abs());
    }

    /// Get summary features from reservoir state (for Router integration)
    pub fn get_features(&self, n: usize) -> Vec<f32> {
        // Return first N dimensions of reservoir state
        self.x[..n.min(self.res_size)].to_vec()
    }

    /// Get current top eigenvalue (spectral pressure)
    pub fn get_eig(&self) -> f32 {
        self.sr.eig()
    }

    /// Get eigenvalue velocity (breathing rate)
    pub fn get_deig(&self) -> f32 {
        self.sr.deig()
    }

    /// Get current prime schedule index and prime value.
    pub fn prime_info(&self) -> (usize, usize) {
        self.sr.prime_info()
    }

    /// Get adaptive leak rate
    pub fn get_leak(&self) -> f32 {
        self.leak_live
    }

    /// Get adaptive RLS forgetting factor
    pub fn get_lambda(&self) -> f32 {
        self.lambda_live
    }

    /// Get slow baseline eigenvalue
    pub fn get_baseline(&self) -> f32 {
        self.sr.baseline()
    }

    /// Get current geometric radius (RMS norm of reservoir state)
    pub fn get_geom_radius(&self) -> f32 {
        self.geom_radius
    }

    /// Get baseline geometric radius (EMA)
    pub fn get_geom_baseline(&self) -> f32 {
        self.geom_baseline.max(1e-6)
    }

    /// Relative geometric radius compared to baseline
    pub fn get_geom_rel(&self) -> f32 {
        self.geom_radius / self.get_geom_baseline()
    }

    /// Set exploration noise amplitude (0.0 to disable, 0.01-0.05 typical)
    pub fn set_exploration_noise(&mut self, eps: f32) {
        self.exploration_noise = eps.clamp(0.0, 0.2);
    }

    /// Get current exploration noise amplitude
    pub fn get_exploration_noise(&self) -> f32 {
        self.exploration_noise
    }

    /// Get covariance matrix for external spectral analysis
    /// Returns (dimension, covariance_data)
    pub fn get_covariance(&self) -> (usize, Vec<f32>) {
        let d = self.sr.d;
        let gpu = unsafe { &*self.sr.gpu };
        let cov_data = gpu.read_f32(&self.sr.cov, d * d);
        (d, cov_data)
    }

    /// Get reservoir dimension
    pub fn get_reservoir_dim(&self) -> usize {
        self.sr.d
    }
}

//=============================================================================
// Linear Algebra Helpers
//=============================================================================

fn mv_mul(m: &[f32], rows: usize, cols: usize, v: &[f32], out: &mut [f32]) {
    for r in 0..rows {
        let mut s = 0.0f32;
        let base = r * cols;
        for c in 0..cols {
            s += m[base + c] * v[c];
        }
        out[r] = s;
    }
}

fn vv_dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn l2_norm(x: &[f32]) -> f32 {
    (x.iter().map(|v| v * v).sum::<f32>()).sqrt().max(1e-12)
}
