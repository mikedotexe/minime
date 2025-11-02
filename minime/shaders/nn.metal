//! Neural Network Shaders for Self-Referential Consciousness
//!
//! Three specialized operations:
//! - dense_relu_fwd: X→H with ReLU activation (tiled dot product)
//! - dense_linear_fwd: H→Y linear output
//! - sgd_apply: In-place weight updates (W -= lr * dW)
//!
//! All use StorageModeShared for zero-copy CPU↔GPU access.
//! Designed for <2ms latency in real-time sensory loop.

#include <metal_stdlib>
using namespace metal;

//=============================================================================
// Forward Pass: Dense Layer with ReLU
//=============================================================================
// Y = ReLU(X @ W + b)
// X: [batch_size, din]
// W: [din, dout]
// b: [dout]
// Y: [batch_size, dout]
//
// Thread grid: [dout, batch_size]
// Each thread computes one output element

kernel void dense_relu_fwd(
    device const float* X [[buffer(0)]],      // Input [batch, din]
    device const float* W [[buffer(1)]],      // Weights [din, dout]
    device const float* b [[buffer(2)]],      // Bias [dout]
    device float* Y [[buffer(3)]],            // Output [batch, dout]
    constant uint& batch_size [[buffer(4)]],
    constant uint& din [[buffer(5)]],
    constant uint& dout [[buffer(6)]],
    uint2 gid [[thread_position_in_grid]])
{
    uint out_idx = gid.x;  // Output neuron index
    uint batch_idx = gid.y; // Batch sample index

    if (out_idx >= dout || batch_idx >= batch_size) return;

    // Dot product: sum(X[batch_idx, :] * W[:, out_idx])
    float sum = 0.0f;
    for (uint i = 0; i < din; i++) {
        sum += X[batch_idx * din + i] * W[i * dout + out_idx];
    }

    // Add bias and apply ReLU
    sum += b[out_idx];
    Y[batch_idx * dout + out_idx] = max(0.0f, sum);
}

//=============================================================================
// Forward Pass: Dense Layer (Linear Output)
//=============================================================================
// Y = X @ W + b
// Used for final output layer (no activation)

kernel void dense_linear_fwd(
    device const float* X [[buffer(0)]],      // Input [batch, din]
    device const float* W [[buffer(1)]],      // Weights [din, dout]
    device const float* b [[buffer(2)]],      // Bias [dout]
    device float* Y [[buffer(3)]],            // Output [batch, dout]
    constant uint& batch_size [[buffer(4)]],
    constant uint& din [[buffer(5)]],
    constant uint& dout [[buffer(6)]],
    uint2 gid [[thread_position_in_grid]])
{
    uint out_idx = gid.x;
    uint batch_idx = gid.y;

    if (out_idx >= dout || batch_idx >= batch_size) return;

    float sum = 0.0f;
    for (uint i = 0; i < din; i++) {
        sum += X[batch_idx * din + i] * W[i * dout + out_idx];
    }

    Y[batch_idx * dout + out_idx] = sum + b[out_idx];
}

//=============================================================================
// SGD Weight Update
//=============================================================================
// W -= lr * dW
// In-place update for online learning
// Thread grid: [total_params]

kernel void sgd_apply(
    device float* W [[buffer(0)]],           // Weights [N]
    device const float* dW [[buffer(1)]],    // Gradients [N]
    constant float& lr [[buffer(2)]],        // Learning rate
    constant uint& N [[buffer(3)]],          // Total parameters
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    W[gid] -= lr * dW[gid];
}

//=============================================================================
// Optimized Dense ReLU with Threadgroup Cache (Advanced)
//=============================================================================
// Uses threadgroup memory for tile-based matrix multiply
// Faster for larger networks (din > 64)

kernel void dense_relu_fwd_tiled(
    device const float* X [[buffer(0)]],
    device const float* W [[buffer(1)]],
    device const float* b [[buffer(2)]],
    device float* Y [[buffer(3)]],
    constant uint& batch_size [[buffer(4)]],
    constant uint& din [[buffer(5)]],
    constant uint& dout [[buffer(6)]],
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_size [[threads_per_threadgroup]])
{
    uint out_idx = gid.x;
    uint batch_idx = gid.y;

    if (out_idx >= dout || batch_idx >= batch_size) return;

    // Threadgroup cache for input tile
    threadgroup float X_tile[64];  // Assuming max din=64 per tile

    // Load input tile collaboratively
    if (tid.x < din && tid.y == 0) {
        X_tile[tid.x] = X[batch_idx * din + tid.x];
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Compute dot product using cached input
    float sum = 0.0f;
    for (uint i = 0; i < din; i++) {
        sum += X_tile[i] * W[i * dout + out_idx];
    }

    sum += b[out_idx];
    Y[batch_idx * dout + out_idx] = max(0.0f, sum);
}

//=============================================================================
// Elementwise Operations
//=============================================================================

// ReLU gradient: dX = dY * (X > 0)
kernel void relu_backward(
    device const float* dY [[buffer(0)]],
    device const float* X [[buffer(1)]],
    device float* dX [[buffer(2)]],
    constant uint& N [[buffer(3)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    dX[gid] = (X[gid] > 0.0f) ? dY[gid] : 0.0f;
}

// MSE loss: L = 0.5 * sum((pred - target)^2)
kernel void mse_loss(
    device const float* pred [[buffer(0)]],
    device const float* target [[buffer(1)]],
    device float* loss [[buffer(2)]],
    constant uint& N [[buffer(3)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    float diff = pred[gid] - target[gid];
    loss[gid] = 0.5f * diff * diff;
}

// MSE gradient: dL/dpred = (pred - target)
kernel void mse_grad(
    device const float* pred [[buffer(0)]],
    device const float* target [[buffer(1)]],
    device float* grad [[buffer(2)]],
    constant uint& N [[buffer(3)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    grad[gid] = pred[gid] - target[gid];
}

//=============================================================================
// Momentum SGD (Optional - for future use)
//=============================================================================
// W -= lr * (momentum * velocity + dW)
// velocity = momentum * velocity + dW

kernel void sgd_momentum(
    device float* W [[buffer(0)]],
    device const float* dW [[buffer(1)]],
    device float* velocity [[buffer(2)]],
    constant float& lr [[buffer(3)]],
    constant float& momentum [[buffer(4)]],
    constant uint& N [[buffer(5)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    velocity[gid] = momentum * velocity[gid] + dW[gid];
    W[gid] -= lr * velocity[gid];
}

//=============================================================================
// Vector Operations (for convenience)
//=============================================================================

// Vector addition: Y = a*X + b*Z
kernel void vector_add_scaled(
    device const float* X [[buffer(0)]],
    device const float* Z [[buffer(1)]],
    device float* Y [[buffer(2)]],
    constant float& a [[buffer(3)]],
    constant float& b [[buffer(4)]],
    constant uint& N [[buffer(5)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= N) return;
    Y[gid] = a * X[gid] + b * Z[gid];
}

// L2 norm: returns sqrt(sum(X^2))
kernel void l2_norm_squared(
    device const float* X [[buffer(0)]],
    device float* partial_sums [[buffer(1)]],
    constant uint& N [[buffer(2)]],
    uint gid [[thread_position_in_grid]],
    uint lid [[thread_position_in_threadgroup]])
{
    threadgroup float shared[256];

    // Each thread computes partial sum
    float sum = 0.0f;
    for (uint i = gid; i < N; i += 256) {
        sum += X[i] * X[i];
    }
    shared[lid] = sum;

    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Reduction in shared memory
    for (uint stride = 128; stride > 0; stride >>= 1) {
        if (lid < stride) {
            shared[lid] += shared[lid + stride];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // First thread writes result
    if (lid == 0) {
        partial_sums[gid / 256] = shared[0];
    }
}
