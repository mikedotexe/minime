//! Spectral Monitor GPU Kernels
//!
//! Metal shaders for EigenFill% computation via Chebyshev + SLQ:
//! - spectral_matvec: Mat-vec product y = A*v for Chebyshev recurrence
//!
//! Uses unified memory (StorageModeShared) for zero-copy CPU↔GPU handoff.

#include <metal_stdlib>
using namespace metal;

/// Matrix-vector product: y = A * v
/// A is row-major N×N, v and y are N-dim vectors
///
/// Same pattern as ESN's cov_matvec kernel
kernel void spectral_matvec(
    device const float *mat  [[buffer(0)]],  // N×N matrix (row-major)
    device const float *v    [[buffer(1)]],  // N-dim input vector
    device float *y          [[buffer(2)]],  // N-dim output vector
    device const uint *dim   [[buffer(3)]],  // Scalar: dimension N
    uint row                 [[thread_position_in_grid]]
) {
    const uint N = *dim;

    if (row >= N) return;

    // Compute dot product of row with v
    float sum = 0.0f;
    device const float *mat_row = mat + row * N;

    for (uint j = 0; j < N; ++j) {
        sum += mat_row[j] * v[j];
    }

    y[row] = sum;
}
