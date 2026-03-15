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

        // Update slow baseline
        self.ema_eig = 0.995 * self.ema_eig + 0.005 * self.eig1;

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

        // CRITICAL FIX: Use absolute thresholds to prevent runaway eigenvalues
        // Target eigenvalue at golden ratio φ ≈ 1.618
        let target_eig = 1.618;

        // Strong response when eigenvalue exceeds safe range
        let eig_error = (eig1 - target_eig).max(0.0);

        // Leak: aggressive increase when eig1 > 2.5 (φ * 1.54) to dissipate energy
        let mut leak = if eig1 > 2.5 {
            // Emergency response - high leak to quickly reduce eigenvalues
            0.7 + 0.2 * ((eig1 - 2.5) / 0.5).min(1.0) // 0.7 to 0.9 range
        } else if eig1 > target_eig {
            // Preventive response - moderate leak increase
            self.leak_base + 0.3 * eig_error
        } else {
            // Normal operation - use baseline-relative adaptation
            let k_leak = 0.5;
            self.leak_base * (1.0 + k_leak * (eig1 - self.sr.baseline()).max(0.0))
        };

        leak = leak.clamp(0.05, 0.95);

        // Light prime modulation (reduced influence during emergency)
        let phase = self.sr.phase01();
        let cosw = (2.0 * PI * phase).cos();
        let modulation_strength = if eig1 > 2.5 { 0.02 } else { 0.1 };
        leak = (0.9 * leak + 0.1 * (leak * (1.0 + modulation_strength * cosw))).clamp(0.05, 0.95);

        // RLS forgetting: tighten when dynamics accelerate or eigenvalues high
        let k_forget = 0.2;
        let pressure_factor = if eig1 > 2.5 { 0.3 } else { 0.0 }; // Extra forgetting under pressure
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

        // Spectral self-reference on previous state
        self.sr.rank1_ewma(&self.x)?;
        self.sr.maybe_introspect()?;
        self.adapt_hyperparams(0.0);

        // Leaky integration with adaptive leak
        let a = self.leak_live;
        for i in 0..self.res_size {
            self.x[i] = (1.0 - a) * self.x[i] + a * self.pre[i];
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
