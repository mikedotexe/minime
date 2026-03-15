// src/cheby.rs
// Host-side Chebyshev band-stop filter for unified memory + Metal GPU.
//
#![allow(dead_code)]
// Implements:
// - DCT-I based coefficient generation for smooth band-stop response
// - Safe bounds estimation for PSD matrices (covariance, graph adjacency)
// - GPU dispatch with zero-copy unified memory (StorageModeShared)
//
// Theory:
// - Chebyshev polynomials T_k(x) provide near-optimal approximation on [-1,1]
// - We map eigenvalues [λ_min, λ_max] → [-1,1] via x = (λ - β)/α
// - Band-stop: H(λ) ≈ 1 outside [λ_lo, λ_hi], ≈ 0 inside, with smooth edges

use metal::*;
use std::{mem, time::Instant};

// ============================================================================
// Public API
// ============================================================================

/// Chebyshev filter plan containing coefficients and normalization parameters
#[derive(Clone, Debug)]
pub struct ChebyPlan {
    pub order: usize,     // Polynomial order M
    pub coeffs: Vec<f32>, // Coefficients c_0..c_M
    pub alpha: f32,       // Normalization scale
    pub beta: f32,        // Normalization offset
    pub lambda_min: f32,  // Estimated minimum eigenvalue
    pub lambda_max: f32,  // Estimated maximum eigenvalue
}

/// Build Chebyshev band-stop filter plan
///
/// # Arguments
/// * `a_host` - N×N symmetric PSD matrix (row-major)
/// * `n` - Matrix dimension
/// * `order` - Chebyshev polynomial order (6-8 typical)
/// * `stop_lo_frac` - Lower stopband edge in [0,1] relative to spectrum
/// * `stop_hi_frac` - Upper stopband edge in [0,1] relative to spectrum
/// * `edge_softness` - Edge smoothing (0.05-0.12 recommended)
///
/// # Returns
/// Plan with coefficients and normalization ready for GPU dispatch
pub fn make_bandstop_plan(
    a_host: &[f32],
    n: usize,
    order: usize,
    stop_lo_frac: f32,
    stop_hi_frac: f32,
    edge_softness: f32,
) -> ChebyPlan {
    // Estimate spectrum bounds (safe for PSD)
    let (lam_min, lam_max) = estimate_bounds_psd(a_host, n);

    // Compute normalization to map [lam_min, lam_max] → [-1, 1]
    let (alpha, beta) = map_ab(lam_min, lam_max);

    // Map stopband from lambda-space to normalized x-space
    let lam_lo = lam_min + stop_lo_frac * (lam_max - lam_min);
    let lam_hi = lam_min + stop_hi_frac * (lam_max - lam_min);
    let x_lo = (lam_lo - beta) / alpha;
    let x_hi = (lam_hi - beta) / alpha;

    // Generate Chebyshev coefficients via DCT-I
    let coeffs = cheby_coeffs_bandstop(order, x_lo, x_hi, edge_softness);

    ChebyPlan {
        order,
        coeffs,
        alpha,
        beta,
        lambda_min: lam_min,
        lambda_max: lam_max,
    }
}

/// Apply Chebyshev polynomial y = P_M(A) x on GPU with unified memory
///
/// # Arguments
/// * `device` - Metal device
/// * `queue` - Metal command queue
/// * `pso` - Compiled pipeline state for "cheby_bandstop_apply" kernel
/// * `matrix_buf` - N×N matrix buffer (StorageModeShared)
/// * `x_in_buf` - N input vector buffer
/// * `x_out_buf` - N output vector buffer
/// * `work0_buf` - N scratch buffer
/// * `work1_buf` - N scratch buffer
/// * `n` - Vector dimension
/// * `plan` - Chebyshev plan with coefficients
///
/// # Returns
/// Elapsed time in milliseconds
pub fn cheby_apply_gpu(
    device: &Device,
    queue: &CommandQueue,
    pso: &ComputePipelineState,
    matrix_buf: &Buffer,
    x_in_buf: &Buffer,
    x_out_buf: &Buffer,
    work0_buf: &Buffer,
    work1_buf: &Buffer,
    n: usize,
    plan: &ChebyPlan,
) -> f32 {
    // Create coefficient buffer (shared mode for zero-copy)
    let coeff_bytes = ((plan.order + 1) * mem::size_of::<f32>()) as u64;
    let coeff_buf = device.new_buffer(coeff_bytes, MTLResourceOptions::StorageModeShared);
    unsafe {
        std::ptr::copy_nonoverlapping(
            plan.coeffs.as_ptr() as *const u8,
            coeff_buf.contents() as *mut u8,
            coeff_bytes as usize,
        );
    }

    // Create parameter buffer
    #[repr(C)]
    struct Params {
        dim: u32,
        order: u32,
        alpha: f32,
        beta: f32,
    }

    let params = Params {
        dim: n as u32,
        order: plan.order as u32,
        alpha: plan.alpha,
        beta: plan.beta,
    };

    let params_buf = device.new_buffer(
        mem::size_of::<Params>() as u64,
        MTLResourceOptions::StorageModeShared,
    );
    unsafe {
        std::ptr::copy_nonoverlapping(
            &params as *const Params as *const u8,
            params_buf.contents() as *mut u8,
            mem::size_of::<Params>(),
        );
    }

    // Dispatch GPU kernel
    let grid = MTLSize::new(n as u64, 1, 1);
    let tg = MTLSize::new(32, 1, 1); // TILE=32

    let t0 = Instant::now();
    let cmd = queue.new_command_buffer();
    let enc = cmd.new_compute_command_encoder();

    enc.set_compute_pipeline_state(pso);
    enc.set_buffer(0, Some(matrix_buf), 0);
    enc.set_buffer(1, Some(x_in_buf), 0);
    enc.set_buffer(2, Some(x_out_buf), 0);
    enc.set_buffer(3, Some(&coeff_buf), 0);
    enc.set_buffer(4, Some(&params_buf), 0);
    enc.set_buffer(5, Some(work0_buf), 0);
    enc.set_buffer(6, Some(work1_buf), 0);

    enc.dispatch_thread_groups(grid, tg);
    enc.end_encoding();

    cmd.commit();
    cmd.wait_until_completed();

    let elapsed_ms = t0.elapsed().as_secs_f64() as f32 * 1000.0;
    elapsed_ms
}

// ============================================================================
// Bounds Estimation and Normalization
// ============================================================================

/// Estimate [λ_min, λ_max] for symmetric PSD matrix using Gershgorin discs
///
/// For PSD matrices: λ_min ≥ 0, λ_max ≤ max row sum
/// We add 5% margin for safety as spectrum can drift over time.
pub fn estimate_bounds_psd(a: &[f32], n: usize) -> (f32, f32) {
    let mut lam_max = 0.0f32;

    // Gershgorin: each eigenvalue lies within at least one disc
    // For row i: |λ - a_ii| ≤ Σ_{j≠i} |a_ij|
    // Upper bound: λ ≤ a_ii + Σ_{j≠i} |a_ij| = Σ_j |a_ij| (row sum)
    for r in 0..n {
        let mut row_sum = 0.0f32;
        let base = r * n;
        for c in 0..n {
            row_sum += a[base + c].abs();
        }
        if row_sum > lam_max {
            lam_max = row_sum;
        }
    }

    // Add 5% headroom for spectral drift
    let lam_max = lam_max * 1.05f32;

    // For PSD: λ_min = 0 (semi-definite)
    (0.0f32, lam_max.max(1e-6)) // Ensure non-degenerate
}

/// Compute normalization parameters to map [λ_min, λ_max] → [-1, 1]
///
/// Mapping: x = (λ - β)/α
/// Solving: -1 = (λ_min - β)/α, 1 = (λ_max - β)/α
/// Result: α = (λ_max - λ_min)/2, β = (λ_max + λ_min)/2
#[inline]
pub fn map_ab(lam_min: f32, lam_max: f32) -> (f32, f32) {
    let alpha = 0.5f32 * (lam_max - lam_min).max(1e-6);
    let beta = 0.5f32 * (lam_max + lam_min);
    (alpha, beta)
}

// ============================================================================
// Chebyshev Coefficient Generation (DCT-I)
// ============================================================================

/// Generate Chebyshev coefficients for smooth band-stop filter
///
/// Target response H(x) on [-1, 1]:
/// - H(x) ≈ 1 outside [x_lo, x_hi] (passband)
/// - H(x) ≈ 0 inside [x_lo, x_hi] (stopband)
/// - Smooth cosine skirts at edges (width = soft)
///
/// Uses DCT-I (Discrete Cosine Transform Type I) for coefficient extraction.
pub fn cheby_coeffs_bandstop(order: usize, x_lo: f32, x_hi: f32, soft: f32) -> Vec<f32> {
    let m = order;
    let ns = (4 * order + 8).max(16); // Sampling points (oversampled for accuracy)
    let mut coeffs = vec![0.0f32; m + 1];

    // Clamp edge softness to prevent over-smoothing
    let edge = soft.clamp(0.0, 0.4);

    // Helper: cubic smoothstep for smooth transitions
    fn sstep01(t: f32) -> f32 {
        let tt = t.clamp(0.0, 1.0);
        tt * tt * (3.0 - 2.0 * tt)
    }

    // Compute DCT-I coefficients
    for k in 0..=m {
        let mut sum = 0.0f64;

        // Sample at Chebyshev nodes: x_j = cos(πj/(ns-1))
        for j in 0..ns {
            let theta = std::f64::consts::PI * (j as f64) / ((ns - 1) as f64);
            let x = theta.cos() as f32;

            // Compute target response H(x) with smooth edges
            let in_band = (x >= x_lo) && (x <= x_hi);
            let h = if in_band {
                // Inside stopband: ramp down to 0 near edges
                if edge > 0.0 {
                    let t_lo = (x - x_lo) / edge;
                    let t_hi = (x_hi - x) / edge;

                    if x < (x_lo + edge) {
                        1.0 - sstep01(t_lo)
                    } else if x > (x_hi - edge) {
                        1.0 - sstep01(t_hi)
                    } else {
                        0.0
                    }
                } else {
                    0.0
                }
            } else {
                // Outside stopband: ramp up from edges
                if edge > 0.0 {
                    if x > x_hi && x < (x_hi + edge) {
                        sstep01((x - x_hi) / edge)
                    } else if x < x_lo && x > (x_lo - edge) {
                        sstep01((x_lo - x) / edge)
                    } else {
                        1.0
                    }
                } else {
                    1.0
                }
            };

            // DCT-I kernel: cos(kθ)
            let term = (h as f64) * ((k as f64) * theta).cos();

            // DCT-I weights: endpoints are half-weighted
            let w = if j == 0 || j == (ns - 1) { 0.5 } else { 1.0 };

            sum += w * term;
        }

        // DCT-I normalization
        let scale = 2.0 / ((ns - 1) as f64);
        let mut ck = (scale * sum) as f32;

        // Special handling for c_0 (doubled in Clenshaw convention)
        if k == 0 {
            ck *= 0.5;
        }

        coeffs[k] = ck;
    }

    coeffs
}

// ============================================================================
// Utility Functions
// ============================================================================

/// Write slice to Metal buffer (unified memory helper)
#[allow(dead_code)]
pub fn write_slice(buf: &Buffer, data: &[f32]) {
    let byte_len = data.len() * mem::size_of::<f32>();
    unsafe {
        std::ptr::copy_nonoverlapping(
            data.as_ptr() as *const u8,
            buf.contents() as *mut u8,
            byte_len,
        );
    }
}

/// Read slice from Metal buffer (unified memory helper)
#[allow(dead_code)]
pub fn read_slice(buf: &Buffer, len: usize) -> Vec<f32> {
    unsafe { std::slice::from_raw_parts(buf.contents() as *const f32, len).to_vec() }
}
