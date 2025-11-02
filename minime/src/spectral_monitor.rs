//! Spectral Monitor: EigenFill% via Chebyshev + SLQ
//!
//! Measures bulk spectral load using Stochastic Lanczos Quadrature (SLQ) with
//! Chebyshev polynomial approximation of a smoothed Heaviside function H̃(A).
//!
//! Key innovation: Instead of just tracking λ₁ (tallest peak), we measure
//! "what portion of the spectrum is in the danger zone?" via:
//!
//!   EigenFill% ≈ (1/N) * (1/R) * Σ_r v_r^T H̃(A) v_r
//!
//! Where:
//! - H̃ is Chebyshev approximation of smoothed step function at λ_gate
//! - R probes (v_r ~ N(0,1)) estimate trace via Hutchinson
//! - GPU mat-vec + CPU normalization (cache handoff pattern)
//!
//! Based on PE's design: predictive, proactive, zero-copy.

use anyhow::Result;
use metal::*;
use std::{mem, time::Instant};

use crate::gpu::Gpu;

/// Spectral reading output
#[derive(Debug, Clone)]
pub struct SpectralReading {
    pub lambda1: f32,       // Top eigenvalue
    pub d_lambda1_dt: f32,  // Eigenvalue velocity
    pub eigenfill_pct: f32, // 0..1 - bulk spectral load
    pub elapsed_ms: f32,    // Computation time
}

/// Spectral monitor configuration
pub struct SpectralMonitorCfg {
    pub r_probes: usize,    // Hutchinson probes (8-16)
    pub m_cheby: usize,     // Chebyshev degree (16-32)
    pub lambda_gate: f32,   // Threshold for "danger zone"
    pub power_iters: usize, // Power iterations for λ₁ (3-6)
}

impl Default for SpectralMonitorCfg {
    fn default() -> Self {
        Self {
            r_probes: 8,
            m_cheby: 24,
            lambda_gate: 3.0, // Above this is "overload"
            power_iters: 4,
        }
    }
}

/// Spectral monitor with GPU acceleration
pub struct SpectralMonitor {
    // GPU resources
    gpu: *const Gpu,              // Raw pointer to avoid circular dependency
    pso_mv: ComputePipelineState, // Mat-vec kernel

    // Unified memory buffers
    mat: Buffer,     // N×N matrix (row-major f32)
    xin: Buffer,     // N probe/power vector
    xout: Buffer,    // N output vector
    dim_buf: Buffer, // Scalar: dimension N

    // Config
    n: usize, // Matrix dimension
    cfg: SpectralMonitorCfg,

    // Spectral scaling: A' = (A - beta*I) / alpha maps spectrum to [-1,1]
    // Estimated from λ_min, λ_max
    scale_alpha: f32, // (λ_max - λ_min) / 2
    scale_beta: f32,  // (λ_max + λ_min) / 2

    // State tracking
    last_lambda1: f32,
    last_fill: f32,
}

unsafe impl Send for SpectralMonitor {}
unsafe impl Sync for SpectralMonitor {}

impl SpectralMonitor {
    /// Create new spectral monitor
    ///
    /// # Arguments
    /// * `gpu` - GPU device reference
    /// * `n` - Matrix dimension
    /// * `cfg` - Configuration (probes, Chebyshev degree, etc.)
    ///
    /// # Returns
    /// Initialized monitor ready for step() calls
    pub fn new(gpu: &Gpu, n: usize, cfg: SpectralMonitorCfg) -> Result<Self> {
        // Compile shader for mat-vec (reuse ESN's cov_matvec kernel pattern)
        let shader_src = include_str!("../shaders/spectral_monitor.metal");
        let opts = CompileOptions::new();
        let lib = gpu
            .dev
            .new_library_with_source(shader_src, &opts)
            .map_err(|e| anyhow::anyhow!("Failed to compile spectral monitor shaders: {}", e))?;

        let f_mv = lib
            .get_function("spectral_matvec", None)
            .map_err(|e| anyhow::anyhow!("Failed to get spectral_matvec function: {}", e))?;

        let pso_mv = gpu
            .dev
            .new_compute_pipeline_state_with_function(&f_mv)
            .map_err(|e| anyhow::anyhow!("Failed to create matvec pipeline: {}", e))?;

        // Allocate unified memory buffers (zero-copy)
        let bytes_mat = (n * n * mem::size_of::<f32>()) as u64;
        let bytes_vec = (n * mem::size_of::<f32>()) as u64;

        let mat = gpu.new_shared(bytes_mat);
        let xin = gpu.new_shared(bytes_vec);
        let xout = gpu.new_shared(bytes_vec);
        let dim_buf = gpu.new_shared(mem::size_of::<u32>() as u64);

        // Initialize dimension buffer
        unsafe {
            *(dim_buf.contents() as *mut u32) = n as u32;
        }

        Ok(Self {
            gpu: gpu as *const Gpu,
            pso_mv,
            mat,
            xin,
            xout,
            dim_buf,
            n,
            cfg,
            scale_alpha: 1.0, // Will be updated via estimate_spectrum_bounds()
            scale_beta: 0.0,
            last_lambda1: 0.0,
            last_fill: 0.0,
        })
    }

    /// Write matrix data (row-major f32)
    pub fn write_matrix(&self, data: &[f32]) {
        assert_eq!(data.len(), self.n * self.n, "Matrix size mismatch");
        let gpu = unsafe { &*self.gpu };
        gpu.write_f32(&self.mat, data);
    }

    /// Estimate spectrum bounds for Chebyshev scaling
    ///
    /// Uses a few power iterations to estimate λ_max (top eigenvalue)
    /// and inverse power for λ_min (bottom eigenvalue).
    ///
    /// Sets scale_alpha = (λ_max - λ_min) / 2
    ///      scale_beta  = (λ_max + λ_min) / 2
    ///
    /// This maps the spectrum to [-1, 1] for Chebyshev approximation.
    pub fn estimate_spectrum_bounds(&mut self) -> Result<(f32, f32)> {
        // Quick λ_max estimate via power iteration
        let lambda_max = self.power_iter_estimate(3)?;

        // For SPD matrices, λ_min ≈ 0 (or small positive)
        // For now, assume λ_min ≈ 0 for covariance matrices
        let lambda_min = 0.0f32;

        // Spectral scaling to [-1, 1]
        self.scale_alpha = (lambda_max - lambda_min) / 2.0;
        self.scale_beta = (lambda_max + lambda_min) / 2.0;

        if self.scale_alpha < 1e-6 {
            self.scale_alpha = 1.0; // Prevent division by zero
        }

        Ok((lambda_min, lambda_max))
    }

    /// Single analysis tick: compute EigenFill% and λ₁
    ///
    /// # Arguments
    /// * `dt_seconds` - Time since last step (for velocity calculation)
    ///
    /// # Returns
    /// SpectralReading with {lambda1, d_lambda1_dt, eigenfill_pct, elapsed_ms}
    pub fn step(&mut self, dt_seconds: f32) -> Result<SpectralReading> {
        let t0 = Instant::now();

        // --- EigenFill% via SLQ on smoothed Heaviside H̃(A) ---
        let eigenfill = self.compute_eigenfill()?;

        // --- λ₁ via power iteration ---
        let lambda1 = self.power_iter_estimate(self.cfg.power_iters)?;

        // Derivative (velocity)
        let d_lambda1_dt = if dt_seconds > 0.0 {
            (lambda1 - self.last_lambda1) / dt_seconds
        } else {
            0.0
        };

        self.last_lambda1 = lambda1;
        self.last_fill = eigenfill;

        Ok(SpectralReading {
            lambda1,
            d_lambda1_dt,
            eigenfill_pct: eigenfill,
            elapsed_ms: t0.elapsed().as_secs_f32() * 1000.0,
        })
    }

    /// Compute EigenFill% using SLQ with Chebyshev approximation
    ///
    /// Approximates trace(H̃(A)) / N where H̃ is smoothed Heaviside at λ_gate.
    /// Uses R Hutchinson probes: v ~ N(0,1), accumulate v^T H̃(A) v
    fn compute_eigenfill(&mut self) -> Result<f32> {
        let mut fill_acc = 0.0f64;

        for _probe_idx in 0..self.cfg.r_probes {
            // Generate random probe v ~ N(0,1) normalized
            let v = self.generate_probe();

            // Apply Chebyshev approximation of H̃(A) to get H̃(A)v
            let hv = self.apply_chebyshev_heaviside(&v)?;

            // Compute v^T H̃(A)v
            let mut dot = 0.0f64;
            for i in 0..self.n {
                dot += (v[i] as f64) * (hv[i] as f64);
            }

            fill_acc += dot;
        }

        // Average over probes and normalize by dimension
        let eigenfill = (fill_acc / (self.cfg.r_probes as f64))
            .max(0.0)
            .min(self.n as f64)
            / (self.n as f64);

        Ok(eigenfill as f32)
    }

    /// Generate normalized random probe v ~ N(0,1)
    fn generate_probe(&self) -> Vec<f32> {
        let mut v = vec![0f32; self.n];
        let mut sum_sq = 0.0f32;

        // Simple Box-Muller-ish RNG (cheap and cheerful)
        for i in 0..self.n {
            let u = fastrand::f32() * 2.0 - 1.0;
            v[i] = u;
            sum_sq += u * u;
        }

        // Normalize
        let inv_norm = (sum_sq.max(1e-9)).sqrt().recip();
        for i in 0..self.n {
            v[i] *= inv_norm;
        }

        v
    }

    /// Apply Chebyshev approximation of smoothed Heaviside: H̃(A)v
    ///
    /// H̃(x) ≈ Σ c_k T_k(x) where T_k are Chebyshev polynomials
    /// and x = A' = (A - beta*I) / alpha
    ///
    /// For a smoothed step at λ_gate, we use a sigmoid-like approximation.
    /// Coefficients are precomputed (for now, hardcoded reasonable values).
    fn apply_chebyshev_heaviside(&self, v: &[f32]) -> Result<Vec<f32>> {
        // Chebyshev recurrence: T_0(A')v = v, T_1(A')v = A'v
        // T_{k+1}(A')v = 2 A' T_k(A')v - T_{k-1}(A')v

        let m = self.cfg.m_cheby;

        // Coefficients for smoothed step function (placeholder - should be computed)
        // For now, use a simple polynomial that approximates step at scaled λ_gate
        let coeffs =
            Self::chebyshev_step_coeffs(m, self.cfg.lambda_gate, self.scale_alpha, self.scale_beta);

        // T_0(A')v = v
        let mut t_km1 = v.to_vec();

        // T_1(A')v = A'v = (A - beta*I)v / alpha
        let av = self.matvec(&v)?;
        let mut t_k = vec![0.0f32; self.n];
        for i in 0..self.n {
            t_k[i] = (av[i] - self.scale_beta * v[i]) / self.scale_alpha;
        }

        // Accumulate: y = c_0 * T_0 + c_1 * T_1
        let mut y = vec![0.0f32; self.n];
        for i in 0..self.n {
            y[i] = coeffs[0] * t_km1[i] + coeffs[1] * t_k[i];
        }

        // Recurrence for k = 2..m
        for k in 2..m {
            // T_{k+1} = 2 A' T_k - T_{k-1}
            let a_tk = self.matvec(&t_k)?;
            let mut t_kp1 = vec![0.0f32; self.n];

            for i in 0..self.n {
                let a_prime_tk = (a_tk[i] - self.scale_beta * t_k[i]) / self.scale_alpha;
                t_kp1[i] = 2.0 * a_prime_tk - t_km1[i];
            }

            // Accumulate
            for i in 0..self.n {
                y[i] += coeffs[k] * t_kp1[i];
            }

            // Shift: k-1 ← k, k ← k+1
            t_km1 = t_k;
            t_k = t_kp1;
        }

        Ok(y)
    }

    /// Compute Chebyshev coefficients for smoothed step function
    ///
    /// This is a placeholder - proper implementation would use Jackson smoothing
    /// and compute coefficients via Chebyshev-Gauss quadrature.
    ///
    /// For now, we use a simple sigmoid approximation.
    fn chebyshev_step_coeffs(m: usize, lambda_gate: f32, alpha: f32, beta: f32) -> Vec<f32> {
        // Map lambda_gate to scaled space: x_gate = (lambda_gate - beta) / alpha
        let x_gate = (lambda_gate - beta) / alpha.max(1e-6);

        // Simple sigmoid approximation: H(x) ≈ 0.5 * (1 + tanh(k*(x - x_gate)))
        // For Chebyshev, we use a polynomial fit (very rough for now)
        let mut coeffs = vec![0.0f32; m];

        // c_0 = constant term (average value ≈ 0.5)
        coeffs[0] = 0.5;

        // c_1 = linear term (slope at x_gate)
        coeffs[1] = if m > 1 {
            0.25 / x_gate.abs().max(0.1)
        } else {
            0.0
        };

        // Higher order terms decay (rough approximation)
        for k in 2..m {
            coeffs[k] = coeffs[k - 1] * 0.5 / (k as f32);
        }

        coeffs
    }

    /// GPU mat-vec: y = A * v
    fn matvec(&self, v: &[f32]) -> Result<Vec<f32>> {
        assert_eq!(v.len(), self.n);
        let gpu = unsafe { &*self.gpu };

        // Write input vector to GPU
        gpu.write_f32(&self.xin, v);

        // Dispatch GPU kernel
        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_mv);
        enc.set_buffer(0, Some(&self.mat), 0);
        enc.set_buffer(1, Some(&self.xin), 0);
        enc.set_buffer(2, Some(&self.xout), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new(self.n as u64, 1, 1);
        let tg = MTLSize::new(256.min(self.n as u64), 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();
        cmd.wait_until_completed();

        // Read result from GPU
        Ok(gpu.read_f32(&self.xout, self.n))
    }

    /// Power iteration to estimate λ₁ (top eigenvalue)
    fn power_iter_estimate(&self, iters: usize) -> Result<f32> {
        // Initialize with fresh random vector
        let mut v = vec![0.0f32; self.n];
        let mut sum_sq = 0.0f32;
        for i in 0..self.n {
            let val = fastrand::f32() * 2.0 - 1.0;
            v[i] = val;
            sum_sq += val * val;
        }

        // Normalize
        let inv_norm = (sum_sq.max(1e-9)).sqrt().recip();
        for i in 0..self.n {
            v[i] *= inv_norm;
        }

        let mut lambda1 = 0.0f32;

        for _ in 0..iters {
            // y = A * v
            let y = self.matvec(&v)?;

            // Compute Rayleigh quotient: λ ≈ v^T A v / v^T v
            // After normalization v^T v = 1
            let mut dot = 0.0f64;
            for i in 0..self.n {
                dot += (v[i] as f64) * (y[i] as f64);
            }

            lambda1 = dot as f32;

            // Normalize y → v for next iteration
            let mut norm_sq = 0.0f32;
            for &yi in &y {
                norm_sq += yi * yi;
            }
            let norm = norm_sq.sqrt().max(1e-9);
            for i in 0..self.n {
                v[i] = y[i] / norm;
            }
        }

        Ok(lambda1)
    }

    /// Get current EigenFill% (last computed value)
    pub fn get_eigenfill(&self) -> f32 {
        self.last_fill
    }

    /// Get current λ₁ (last computed value)
    pub fn get_lambda1(&self) -> f32 {
        self.last_lambda1
    }
}
