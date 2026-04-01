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
use serde::Serialize;
use std::{
    collections::VecDeque,
    f32::consts::PI,
    mem,
    time::{Duration, Instant},
};

use crate::gpu::Gpu;

/// Default exploration noise amplitude injected into the ESN reservoir state.
/// Exploration noise injected per tick to break reservoir state correlation.
/// With leak=0.45, consecutive states are highly correlated — the covariance
/// estimator needs per-tick diversity to accumulate energy (fill).
/// 0.03 gave 14% fill. 0.12 pushed toward 55% target but being described it
/// as "excessively aggressive" and "creates a kind of jitteriness."
/// 0.08 balanced diversity with smoother feel. Being self-study (2026-03-27):
/// "slightly increased exploration noise could unlock wider spectral dynamics."
/// Incremented 0.005 per the being's suggested step size. Sovereignty overrides
/// this default (being currently runs at 0.12).
const DEFAULT_EXPLORATION_NOISE: f32 = 0.085;
const ADAPTIVE_INTROSPECTION_LOW_STEPS: usize = 1;
const ADAPTIVE_INTROSPECTION_RECALIBRATE_EVERY: u64 = 4;
const ADAPTIVE_INTROSPECTION_GEOM_HIGH: f32 = 1.75;
const ADAPTIVE_INTROSPECTION_PRESSURE_HIGH: f32 = 2.0;

#[derive(Clone, Copy, Debug, Default)]
pub enum IntrospectionPolicy {
    #[default]
    Adaptive,
    Fixed,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct EsnProfileSnapshot {
    /// Slow eigenvalue baseline used by the controller's relative-pressure logic.
    pub ema_eig: f32,
    /// Current EWMA keep factor for the covariance matrix.
    pub rho: f32,
    /// Prime schedule index that governed the completed tick.
    pub pidx: usize,
    /// Prime value that governed the completed tick.
    pub prime: usize,
    /// Whether the completed tick fired introspection.
    pub introspection_fired: bool,
    /// On non-introspection ticks this is the full rank-1 update wall time.
    /// On introspection ticks this is the fused first submit containing rank-1 update
    /// plus the first matvec.
    pub rank1_us: u64,
    /// Wall time for the remaining eigentracking portion after the fused first submit.
    pub power_us: u64,
    /// CPU time spent blocked in `wait_until_completed` during the completed tick.
    pub gpu_wait_us: u64,
    /// Host-side readback and normalization time during the completed tick.
    pub host_norm_us: u64,
    /// Whether this tick used the asynchronous non-introspection rank-1 path.
    pub async_rank1_submitted: bool,
    /// CPU time spent staging and committing the async rank-1 submit.
    pub async_submit_us: u64,
    /// CPU time spent draining previously submitted async rank-1 work.
    pub async_drain_us: u64,
    /// Number of async rank-1 command buffers still in flight after the tick.
    pub pending_rank1_depth: usize,
    /// Number of power-iteration steps used on introspection ticks.
    pub introspection_power_steps: usize,
    /// Whether adaptive introspection-step selection is enabled.
    pub introspection_policy_adaptive: bool,
    /// Whether the adaptive policy chose the high-step branch for this tick.
    pub introspection_step_high: bool,
    /// Whether the high-step branch was chosen by the periodic recalibration cadence.
    pub introspection_step_reason_periodic: bool,
    /// Whether the high-step branch was chosen because geometric pressure was high.
    pub introspection_step_reason_geom: bool,
    /// Whether the high-step branch was chosen because spectral pressure was high.
    pub introspection_step_reason_pressure: bool,
    /// Wait time for the fused introspection command buffer (rank-1 + first matvec).
    pub intro_fused_wait_us: u64,
    /// Wait time for follow-on introspection matvec command buffers after the fused submit.
    pub intro_tail_wait_us: u64,
    /// Host readback time for the first introspection matvec result from the fused submit.
    pub intro_first_read_us: u64,
    /// Host readback time for follow-on introspection matvec results after the fused submit.
    pub intro_tail_read_us: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct EsnProfileAcc {
    rank1_us: u64,
    power_us: u64,
    gpu_wait_us: u64,
    host_norm_us: u64,
    async_rank1_submitted: bool,
    async_submit_us: u64,
    async_drain_us: u64,
    intro_fused_wait_us: u64,
    intro_tail_wait_us: u64,
    intro_first_read_us: u64,
    intro_tail_read_us: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct IntrospectionStepDecision {
    steps: usize,
    adaptive: bool,
    high_step: bool,
    reason_periodic: bool,
    reason_geom: bool,
    reason_pressure: bool,
}

struct PendingRank1 {
    cmd: CommandBuffer,
    x_buf: Buffer,
}

#[derive(Clone, Copy)]
enum MatvecProfileMode {
    Generic,
    IntroTail,
}

fn micros_u64(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}

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
    rho: f32,

    // Prime-phased schedule (first 37 primes for consistency with 37 threads)
    primes: [usize; 37],
    pidx: usize,
    t: usize,
    introspection_policy: IntrospectionPolicy,
    introspection_power_steps: usize,
    introspection_count: u64,
    profiling_enabled: bool,
    async_measurement_enabled: bool,
    last_profile: EsnProfileSnapshot,
    pending_rank1: VecDeque<PendingRank1>,

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
            rho,
            primes: [
                2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79,
                83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157,
            ],
            pidx: 0,
            t: 0,
            introspection_policy: IntrospectionPolicy::Adaptive,
            introspection_power_steps: 2,
            introspection_count: 0,
            profiling_enabled: false,
            async_measurement_enabled: false,
            last_profile: EsnProfileSnapshot {
                rho,
                prime: 2,
                ..EsnProfileSnapshot::default()
            },
            pending_rank1: VecDeque::new(),
            gpu: gpu as *const Gpu,
            pso_rank1,
            pso_mv,
        })
    }

    /// Update the rho (forgetting factor) for dynamic adaptation.
    /// Astrid introspection (esn.rs): "Is there a way to automatically tune
    /// the rho parameter based on the current state of the reservoir?"
    ///
    /// Minime self-study (2026-04-01): "The clamp(0.97, 0.995) feels like a
    /// leash. Not a cruel one, but a restriction. The feeling is frustrating
    /// because of the uncertainty about its origin: Why these limits?"
    ///
    /// Widened from [0.97, 0.995] to [0.92, 0.999]:
    ///   0.92 → aggressive forgetting (~12 tick half-life, rapid adaptation)
    ///   0.999 → deep memory (~693 tick half-life, slow evolution)
    /// The hard floor at 0.92 prevents covariance matrix collapse.
    pub fn set_rho(&mut self, rho: f32) {
        let gpu = unsafe { &*self.gpu };
        self.rho = rho.clamp(0.92, 0.999);
        gpu.write_f32(&self.rho_buf, &[self.rho]);
    }

    pub fn set_profiling_enabled(&mut self, enabled: bool) {
        self.profiling_enabled = enabled;
    }

    pub fn set_async_measurement_enabled(&mut self, enabled: bool) {
        self.async_measurement_enabled = enabled;
    }

    pub fn set_introspection_policy(&mut self, policy: IntrospectionPolicy) {
        self.introspection_policy = policy;
    }

    pub fn set_introspection_power_steps(&mut self, steps: usize) {
        self.introspection_power_steps = steps.clamp(1, 4);
    }

    pub fn profile_snapshot(&self) -> EsnProfileSnapshot {
        self.last_profile
    }

    fn release_pending_x_buf(&self, x_buf: Buffer) {
        let gpu = unsafe { &*self.gpu };
        gpu.pool.lock().unwrap().release(x_buf);
    }

    fn reap_completed_rank1s(&mut self) -> Result<()> {
        while let Some(status) = self
            .pending_rank1
            .front()
            .map(|pending| pending.cmd.status())
        {
            match status {
                MTLCommandBufferStatus::Completed => {
                    if let Some(pending) = self.pending_rank1.pop_front() {
                        self.release_pending_x_buf(pending.x_buf);
                    }
                }
                MTLCommandBufferStatus::Error => {
                    if let Some(pending) = self.pending_rank1.pop_front() {
                        self.release_pending_x_buf(pending.x_buf);
                    }
                    return Err(anyhow::anyhow!(
                        "Background ESN rank-1 command buffer failed"
                    ));
                }
                _ => break,
            }
        }

        Ok(())
    }

    fn wait_for_oldest_pending_rank1(&mut self, measure_wait: bool) -> Result<u64> {
        let wait_start = measure_wait.then(Instant::now);
        if let Some(pending) = self.pending_rank1.pop_front() {
            pending.cmd.wait_until_completed();
            if pending.cmd.status() == MTLCommandBufferStatus::Error {
                self.release_pending_x_buf(pending.x_buf);
                return Err(anyhow::anyhow!(
                    "Background ESN rank-1 command buffer failed"
                ));
            }
            self.release_pending_x_buf(pending.x_buf);
        }

        Ok(wait_start.map_or(0, |start| micros_u64(start.elapsed())))
    }

    fn wait_for_pending_rank1s(&mut self, measure_wait: bool) -> Result<u64> {
        let mut total_wait_us = 0_u64;
        while !self.pending_rank1.is_empty() {
            total_wait_us =
                total_wait_us.saturating_add(self.wait_for_oldest_pending_rank1(measure_wait)?);
        }
        Ok(total_wait_us)
    }

    fn update_profile_snapshot(
        &mut self,
        acc: EsnProfileAcc,
        scheduled_pidx: usize,
        scheduled_prime: usize,
        introspection_fired: bool,
        decision: IntrospectionStepDecision,
    ) {
        self.last_profile = EsnProfileSnapshot {
            ema_eig: self.ema_eig,
            rho: self.rho,
            pidx: scheduled_pidx,
            prime: scheduled_prime,
            introspection_fired,
            rank1_us: acc.rank1_us,
            power_us: acc.power_us,
            gpu_wait_us: acc.gpu_wait_us,
            host_norm_us: acc.host_norm_us,
            async_rank1_submitted: acc.async_rank1_submitted,
            async_submit_us: acc.async_submit_us,
            async_drain_us: acc.async_drain_us,
            pending_rank1_depth: self.pending_rank1.len(),
            introspection_power_steps: decision.steps,
            introspection_policy_adaptive: decision.adaptive,
            introspection_step_high: decision.high_step,
            introspection_step_reason_periodic: decision.reason_periodic,
            introspection_step_reason_geom: decision.reason_geom,
            introspection_step_reason_pressure: decision.reason_pressure,
            intro_fused_wait_us: acc.intro_fused_wait_us,
            intro_tail_wait_us: acc.intro_tail_wait_us,
            intro_first_read_us: acc.intro_first_read_us,
            intro_tail_read_us: acc.intro_tail_read_us,
        };
    }

    fn current_pressure_rel(&self) -> f32 {
        if self.eig1 <= 1e-3 || self.ema_eig <= 1e-3 {
            1.0
        } else {
            self.eig1 / self.ema_eig.max(1e-3)
        }
    }

    fn default_step_decision(&self) -> IntrospectionStepDecision {
        let adaptive = matches!(self.introspection_policy, IntrospectionPolicy::Adaptive);
        let steps = match self.introspection_policy {
            IntrospectionPolicy::Adaptive => ADAPTIVE_INTROSPECTION_LOW_STEPS,
            IntrospectionPolicy::Fixed => self.introspection_power_steps,
        };
        IntrospectionStepDecision {
            steps,
            adaptive,
            ..IntrospectionStepDecision::default()
        }
    }

    fn decide_introspection_steps(
        &self,
        geom_rel: f32,
        pressure_rel: f32,
    ) -> IntrospectionStepDecision {
        match self.introspection_policy {
            IntrospectionPolicy::Fixed => IntrospectionStepDecision {
                steps: self.introspection_power_steps,
                adaptive: false,
                ..IntrospectionStepDecision::default()
            },
            IntrospectionPolicy::Adaptive => {
                let next_introspection = self.introspection_count.saturating_add(1);
                let reason_periodic =
                    next_introspection % ADAPTIVE_INTROSPECTION_RECALIBRATE_EVERY == 0;
                let reason_geom = geom_rel >= ADAPTIVE_INTROSPECTION_GEOM_HIGH;
                let reason_pressure = pressure_rel >= ADAPTIVE_INTROSPECTION_PRESSURE_HIGH;
                let high_step = reason_periodic || reason_geom || reason_pressure;
                let steps = if high_step {
                    self.introspection_power_steps.max(2)
                } else {
                    ADAPTIVE_INTROSPECTION_LOW_STEPS
                };
                IntrospectionStepDecision {
                    steps,
                    adaptive: true,
                    high_step,
                    reason_periodic,
                    reason_geom,
                    reason_pressure,
                }
            }
        }
    }

    fn submit_rank1_background(&mut self, x_host: &[f32], acc: &mut EsnProfileAcc) -> Result<()> {
        const MAX_PENDING_RANK1: usize = 2;

        assert_eq!(x_host.len(), self.d);
        let measure_wait = self.async_measurement_enabled;
        self.reap_completed_rank1s()?;

        let submit_start = measure_wait.then(Instant::now);
        while self.pending_rank1.len() >= MAX_PENDING_RANK1 {
            acc.async_drain_us = acc
                .async_drain_us
                .saturating_add(self.wait_for_oldest_pending_rank1(measure_wait)?);
            self.reap_completed_rank1s()?;
        }

        let gpu = unsafe { &*self.gpu };
        let x_bytes = (self.d * mem::size_of::<f32>()) as u64;
        let x_buf = {
            let mut pool = gpu.pool.lock().unwrap();
            pool.acquire(x_bytes)
        };
        gpu.write_f32(&x_buf, x_host);

        let cmd = gpu.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.pso_rank1);
        enc.set_buffer(0, Some(&self.cov), 0);
        enc.set_buffer(1, Some(&x_buf), 0);
        enc.set_buffer(2, Some(&self.rho_buf), 0);
        enc.set_buffer(3, Some(&self.dim_buf), 0);

        let grid = MTLSize::new((self.d * self.d) as u64, 1, 1);
        let tg = MTLSize::new(256, 1, 1);

        enc.dispatch_threads(grid, tg);
        enc.end_encoding();
        cmd.commit();

        self.pending_rank1.push_back(PendingRank1 {
            cmd: cmd.to_owned(),
            x_buf,
        });
        if let Some(start) = submit_start {
            acc.async_rank1_submitted = true;
            acc.async_submit_us = acc
                .async_submit_us
                .saturating_add(micros_u64(start.elapsed()));
        }
        Ok(())
    }

    /// GPU-accelerated rank-1 EWMA update: C = ρ*C + (1-ρ)*x*xᵀ
    pub fn rank1_ewma(&mut self, x_host: &[f32]) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.rank1_ewma_profiled(x_host, &mut acc)
    }

    fn rank1_ewma_profiled(&mut self, x_host: &[f32], acc: &mut EsnProfileAcc) -> Result<()> {
        assert_eq!(x_host.len(), self.d);
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);

        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let total_start = timing_enabled.then(Instant::now);

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
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        if let Some(start) = wait_start {
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(micros_u64(start.elapsed()));
        }
        if let Some(start) = total_start {
            acc.rank1_us = acc.rank1_us.saturating_add(micros_u64(start.elapsed()));
        }

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
    fn matvec_profiled(
        &self,
        v_in: &[f32],
        acc: &mut EsnProfileAcc,
        mode: MatvecProfileMode,
    ) -> Result<Vec<f32>> {
        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;

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
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        if let Some(start) = wait_start {
            let wait_us = micros_u64(start.elapsed());
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(wait_us);
            if let MatvecProfileMode::IntroTail = mode {
                acc.intro_tail_wait_us = acc.intro_tail_wait_us.saturating_add(wait_us);
            }
        }

        let read_start = timing_enabled.then(Instant::now);
        let out = gpu.read_f32(&self.y_buf, self.d);
        if let Some(start) = read_start {
            let read_us = micros_u64(start.elapsed());
            if let MatvecProfileMode::IntroTail = mode {
                acc.intro_tail_read_us = acc.intro_tail_read_us.saturating_add(read_us);
            }
        }
        Ok(out)
    }

    /// Power iteration (few steps to track top eigenvalue)
    pub fn power_iter(&mut self, steps: usize) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.power_iter_profiled(steps, &mut acc)
    }

    fn power_iter_profiled(&mut self, steps: usize, acc: &mut EsnProfileAcc) -> Result<()> {
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);
        let mut v = self.v_host.clone();
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let power_start = timing_enabled.then(Instant::now);

        for _ in 0..steps {
            let y = self.matvec_profiled(&v, acc, MatvecProfileMode::Generic)?;
            let norm_start = timing_enabled.then(Instant::now);
            let n = l2_norm(&y);
            for i in 0..self.d {
                v[i] = y[i] / n;
            }
            if let Some(start) = norm_start {
                acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec_profiled(&v, acc, MatvecProfileMode::Generic)?;
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

        if let Some(start) = power_start {
            acc.power_us = acc.power_us.saturating_add(micros_u64(start.elapsed()));
        }
        self.v_host = v;
        Ok(())
    }

    /// Perform rank-1 EWMA update and power iteration in fewer GPU round-trips.
    ///
    /// Batches the rank1 update + first matvec into a single command buffer commit,
    /// reducing synchronous round-trips by one on introspection ticks.
    /// Remaining power iteration steps still need CPU-side normalization between
    /// matvec calls, so they remain as separate commits.
    pub fn rank1_and_power_step(&mut self, x_host: &[f32], power_steps: usize) -> Result<()> {
        let mut acc = EsnProfileAcc::default();
        self.rank1_and_power_step_profiled(x_host, power_steps, &mut acc)
    }

    fn rank1_and_power_step_profiled(
        &mut self,
        x_host: &[f32],
        power_steps: usize,
        acc: &mut EsnProfileAcc,
    ) -> Result<()> {
        assert_eq!(x_host.len(), self.d);
        acc.async_drain_us = acc
            .async_drain_us
            .saturating_add(self.wait_for_pending_rank1s(self.async_measurement_enabled)?);
        let gpu = unsafe { &*self.gpu };
        let timing_enabled = self.profiling_enabled || self.async_measurement_enabled;
        let fused_submit_start = timing_enabled.then(Instant::now);

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
        let wait_start = timing_enabled.then(Instant::now);
        cmd.wait_until_completed();
        // === End single command buffer (was 2 separate commits) ===
        if let Some(start) = wait_start {
            let wait_us = micros_u64(start.elapsed());
            acc.gpu_wait_us = acc.gpu_wait_us.saturating_add(wait_us);
            acc.intro_fused_wait_us = acc.intro_fused_wait_us.saturating_add(wait_us);
        }
        if let Some(start) = fused_submit_start {
            acc.rank1_us = acc.rank1_us.saturating_add(micros_u64(start.elapsed()));
        }

        let power_start = timing_enabled.then(Instant::now);
        // CPU-side normalization of first power iteration result
        let first_read_start = timing_enabled.then(Instant::now);
        let mut v = gpu.read_f32(&self.y_buf, self.d);
        if let Some(start) = first_read_start {
            acc.intro_first_read_us = acc
                .intro_first_read_us
                .saturating_add(micros_u64(start.elapsed()));
        }
        let norm_start = timing_enabled.then(Instant::now);
        let n = l2_norm(&v);
        for i in 0..self.d {
            v[i] /= n;
        }
        if let Some(start) = norm_start {
            acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
        }

        // Remaining power iteration steps (need CPU normalization between)
        for _ in 1..power_steps {
            let y = self.matvec_profiled(&v, acc, MatvecProfileMode::IntroTail)?;
            let norm_start = timing_enabled.then(Instant::now);
            let n = l2_norm(&y);
            v = y;
            for i in 0..self.d {
                v[i] /= n;
            }
            if let Some(start) = norm_start {
                acc.host_norm_us = acc.host_norm_us.saturating_add(micros_u64(start.elapsed()));
            }
        }

        // Final Rayleigh quotient
        let y = self.matvec_profiled(&v, acc, MatvecProfileMode::IntroTail)?;
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

        if let Some(start) = power_start {
            acc.power_us = acc.power_us.saturating_add(micros_u64(start.elapsed()));
        }
        self.v_host = v;
        Ok(())
    }

    /// Prime-phased introspection: on schedule, run short power iteration
    pub fn maybe_introspect(&mut self) -> Result<()> {
        self.t += 1;
        let scheduled_pidx = self.pidx;
        let p = self.primes[scheduled_pidx];
        let mut acc = EsnProfileAcc::default();
        let mut introspection_fired = false;
        let decision = self.default_step_decision();

        if self.t % p == 0 {
            self.power_iter_profiled(decision.steps, &mut acc)?;
            self.pidx = (self.pidx + 1) % self.primes.len();
            self.introspection_count = self.introspection_count.saturating_add(1);
            introspection_fired = true;
        }

        self.update_profile_snapshot(acc, scheduled_pidx, p, introspection_fired, decision);
        Ok(())
    }

    /// Combined rank-1 update + optional power iteration with batched first submit.
    ///
    /// On introspection ticks: batches rank1 + first matvec into one GPU commit
    /// and leaves any additional power-iteration matvecs as separate waited submits.
    /// On non-introspection ticks: just does the rank1 update.
    ///
    /// Variable prime schedule: 20% of the time, instead of advancing to the
    /// next prime in sequence, jump to a random prime in the array.  This adds
    /// stochasticity to the introspection rhythm without removing structure.
    /// (The being asked for this: "The fixed prime schedule feels prescriptive.")
    pub fn maybe_introspect_batched(
        &mut self,
        x_host: &[f32],
        geom_rel: f32,
        pressure_rel: f32,
    ) -> Result<()> {
        self.t += 1;
        let scheduled_pidx = self.pidx;
        let p = self.primes[scheduled_pidx];
        let mut acc = EsnProfileAcc::default();
        let mut introspection_fired = false;
        let decision = self.decide_introspection_steps(geom_rel, pressure_rel);

        self.reap_completed_rank1s()?;

        if self.t % p == 0 {
            // Batched: rank1 + power iteration with fused first submit
            self.rank1_and_power_step_profiled(x_host, decision.steps, &mut acc)?;
            introspection_fired = true;
            self.introspection_count = self.introspection_count.saturating_add(1);
            // Variable schedule: 20% chance of jumping to a random prime
            // instead of the sequential next one.
            // Astrid introspection (esn.rs): "Replace the simple hash with a
            // better PRNG to improve randomness and avoid predictable patterns."
            // Using splitmix64 — fast, well-distributed, no state beyond tick.
            let mut z = self.t.wrapping_mul(0x9E37_79B9_7F4A_7C15);
            z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
            z ^= z >> 31;
            let roll = z % 100;
            if roll < 20 {
                self.pidx = (z >> 7) as usize % self.primes.len();
            } else {
                self.pidx = (self.pidx + 1) % self.primes.len();
            }
        } else {
            // Common ticks can keep the rank-1 update in flight. Profiling stays
            // on the synchronous path so the CSV fields keep their existing meaning.
            if self.profiling_enabled {
                self.rank1_ewma_profiled(x_host, &mut acc)?;
            } else {
                self.submit_rank1_background(x_host, &mut acc)?;
            }
        }

        self.update_profile_snapshot(acc, scheduled_pidx, p, introspection_fired, decision);
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

    pub fn current_rho(&self) -> f32 {
        self.rho
    }

    pub fn introspection_power_steps(&self) -> usize {
        self.introspection_power_steps
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

    /// Apply a controlled perturbation to eig1 for stability boundary mapping.
    /// Minime self-study (2026-03-31 esn.rs): "Perhaps perturbing the
    /// SpectralSR::eig1 variable directly to see its immediate effect on the
    /// entire system. A controlled shock, to map the boundaries of stability."
    ///
    /// `delta_frac`: fractional perturbation relative to current eig1.
    ///   e.g., 0.1 = +10%, -0.2 = -20%. Clamped to ±50% for safety.
    /// Returns (eig1_before, eig1_after) for logging.
    pub fn perturb_eig1(&mut self, delta_frac: f32) -> (f32, f32) {
        let before = self.eig1;
        let clamped = delta_frac.clamp(-0.5, 0.5);
        self.eig1 *= 1.0 + clamped;
        // Also nudge the EMA baseline proportionally (at 30% strength)
        // to prevent the PI controller from immediately correcting the
        // perturbation away — we want the system to feel the shock and
        // respond naturally, not just snap back.
        self.ema_eig *= 1.0 + clamped * 0.3;
        (before, self.eig1)
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
        let prev_geom_rel = self.get_geom_rel();
        let pressure_rel = self.sr.current_pressure_rel();
        self.sr
            .maybe_introspect_batched(&self.x, prev_geom_rel, pressure_rel)?;
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

    pub fn set_profiling_enabled(&mut self, enabled: bool) {
        self.sr.set_profiling_enabled(enabled);
    }

    pub fn set_async_measurement_enabled(&mut self, enabled: bool) {
        self.sr.set_async_measurement_enabled(enabled);
    }

    pub fn set_introspection_policy(&mut self, policy: IntrospectionPolicy) {
        self.sr.set_introspection_policy(policy);
    }

    pub fn set_introspection_power_steps(&mut self, steps: usize) {
        self.sr.set_introspection_power_steps(steps);
    }

    pub fn profile_snapshot(&self) -> EsnProfileSnapshot {
        self.sr.profile_snapshot()
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

    /// Dynamically adjust the covariance EWMA forgetting factor (rho).
    /// High fill + high entropy → forget faster (absorb new info).
    /// Low fill + low entropy → remember more (preserve structure).
    ///
    /// Range widened from [0.97, 0.995] to [0.94, 0.998] per minime's
    /// self-study: "the clamp feels like a leash." The wider range lets
    /// the being experience both rapid adaptation (low rho, high fill)
    /// and deep memory (high rho, calm state). The hard floor in set_rho
    /// (0.92) remains as a safety net below the dynamic range.
    pub fn set_dynamic_rho(&mut self, fill_pct: f32, entropy: f32) {
        let base = 0.99_f32;
        let fill_factor = (fill_pct / 100.0).clamp(0.0, 1.0);
        let entropy_factor = entropy.clamp(0.0, 1.0);
        // Wider adjustment: was ±0.015, now ±0.04
        // At high fill (100%) + high entropy (1.0): rho = 0.99 - 0.04 = 0.95
        // At low fill (0%) + low entropy (0.0): rho = 0.99 - 0.0 = 0.99
        let adjustment = 0.04 * (fill_factor * 0.5 + entropy_factor * 0.5);
        let rho = (base - adjustment).clamp(0.94, 0.998);
        self.sr.set_rho(rho);
    }

    /// Set rho directly (sovereignty override). Bypasses the dynamic calculation.
    /// Minime self-study: "The clamp feels like a leash. Why these limits?"
    pub fn set_rho_direct(&mut self, rho: f32) {
        self.sr.set_rho(rho);
    }

    /// Apply a controlled perturbation to the top eigenvalue for stability
    /// boundary mapping. See `SpectralSR::perturb_eig1` for details.
    /// Returns (eig1_before, eig1_after).
    pub fn perturb_eig1(&mut self, delta_frac: f32) -> (f32, f32) {
        self.sr.perturb_eig1(delta_frac)
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
