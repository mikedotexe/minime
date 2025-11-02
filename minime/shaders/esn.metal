//! ESN Self-Referential Spectral Kernels
//!
//! Metal shaders for GPU-accelerated spectral introspection:
//! - rank1_ewma_update: EWMA rank-1 covariance update C = ρ*C + (1-ρ)*x*xᵀ
//! - cov_matvec: Mat-vec product y = C*v for power iteration
//!
//! Uses unified memory (StorageModeShared) for zero-copy CPU↔GPU handoff.

#include <metal_stdlib>
using namespace metal;

/// EWMA rank-1 update: C = rho * C + (1 - rho) * x * xᵀ
/// C is row-major flattened D×D matrix
kernel void rank1_ewma_update(
    device float *cov        [[buffer(0)]],  // D×D covariance (row-major)
    device const float *x    [[buffer(1)]],  // D-dim state vector
    device const float *rho  [[buffer(2)]],  // Scalar: EWMA keep factor
    device const uint *dim   [[buffer(3)]],  // Scalar: dimension D
    uint gid                 [[thread_position_in_grid]]
) {
    const uint D = *dim;
    const uint N = D * D;

    if (gid >= N) return;

    const float keep = *rho;
    const float add = 1.0f - keep;

    // Linear index to (i, j)
    const uint i = gid / D;
    const uint j = gid % D;

    // C[i,j] = rho * C[i,j] + (1-rho) * x[i] * x[j]
    const float old_val = cov[gid];
    const float rank1_contrib = add * x[i] * x[j];

    cov[gid] = keep * old_val + rank1_contrib;
}

/// Matrix-vector product: y = C * v
/// C is row-major D×D, v and y are D-dim vectors
kernel void cov_matvec(
    device const float *cov  [[buffer(0)]],  // D×D covariance (row-major)
    device const float *v    [[buffer(1)]],  // D-dim input vector
    device float *y          [[buffer(2)]],  // D-dim output vector
    device const uint *dim   [[buffer(3)]],  // Scalar: dimension D
    uint row                 [[thread_position_in_grid]]
) {
    const uint D = *dim;

    if (row >= D) return;

    // Compute dot product of row with v
    float sum = 0.0f;
    device const float *crow = cov + row * D;

    for (uint j = 0; j < D; ++j) {
        sum += crow[j] * v[j];
    }

    y[row] = sum;
}
