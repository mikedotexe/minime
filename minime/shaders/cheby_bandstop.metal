// Chebyshev band-stop polynomial application: y = P_M(A) x
//
// Implements Clenshaw recurrence for evaluating Chebyshev polynomial of matrix A.
// A is symmetric PSD (covariance/graph adjacency).
// We evaluate with A_norm = (A - beta*I)/alpha mapping eigenvalues to [-1,1].
//
// Tiled mat-vec to reduce global memory bandwidth (TILE must divide threadgroup size).

#include <metal_stdlib>
using namespace metal;

constant uint TILE = 32;

struct ChebyParams {
    uint  dim;      // N (matrix dimension)
    uint  order;    // M (Chebyshev polynomial order)
    float alpha;    // normalization scale
    float beta;     // normalization offset
};

// Normalized matrix-vector product for single row: y_i = (1/alpha) * ((A*v)_i - beta * v_i)
// Uses tiled reduction over columns to minimize bandwidth
inline float matvec_normed_row(
    device const float* A,
    device const float* v,
    uint N,
    uint row,
    float alpha,
    float beta,
    uint lane,
    threadgroup float* vTile)
{
    float sum = 0.0f;

    // Tile over columns
    for (uint c0 = 0; c0 < N; c0 += TILE) {
        // Load tile of v into threadgroup memory
        uint c = c0 + lane;
        if (c < N) {
            vTile[lane] = v[c];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        uint cols_here = min(TILE, N - c0);

        // Accumulate row · vTile
        // A is row-major: A[row*N + col]
        for (uint j = 0; j < cols_here; ++j) {
            sum += A[row * N + (c0 + j)] * vTile[j];
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Apply normalization: (A*v - beta*v) / alpha
    return (sum - beta * v[row]) / alpha;
}

// Main kernel: Apply Chebyshev polynomial P_M(A) to vector x_in
// Uses Clenshaw three-term recurrence: b_{k+1} = 2*A_norm*b_k - b_{k-1}
// y = sum_{k=0}^M c_k * T_k(A_norm) x_in
kernel void cheby_bandstop_apply(
    device const float* A             [[buffer(0)]],   // N x N matrix
    device const float* x_in          [[buffer(1)]],   // N input vector
    device float*       x_out         [[buffer(2)]],   // N output vector (result)
    device const float* coeffs        [[buffer(3)]],   // M+1 Chebyshev coefficients c_0..c_M
    constant ChebyParams& P           [[buffer(4)]],   // parameters
    device float*       b_work0       [[buffer(5)]],   // N workspace for b_{k-1}
    device float*       b_work1       [[buffer(6)]],   // N workspace for b_k
    uint gid                           [[thread_position_in_grid]],
    uint tg_lane                       [[thread_position_in_threadgroup]]
)
{
    const uint N = P.dim;
    const uint M = P.order;

    if (gid >= N) return;

    threadgroup float vTile[TILE];

    // Initialize b_0 = x_in
    b_work0[gid] = x_in[gid];

    // y = 0.5 * c_0 * b_0  (factor 0.5 from Chebyshev series convention)
    float y_i = 0.5f * coeffs[0] * b_work0[gid];

    // Special case: if order is 0, we're done
    if (M == 0) {
        x_out[gid] = y_i;
        return;
    }

    // Compute b_1 = A_norm * b_0
    {
        float ax = matvec_normed_row(A, b_work0, N, gid, P.alpha, P.beta, tg_lane, vTile);
        b_work1[gid] = ax;
    }

    // y += c_1 * b_1
    y_i += coeffs[1] * b_work1[gid];

    // Clenshaw recurrence: b_{k+1} = 2*A_norm*b_k - b_{k-1}
    // Ping-pong between b_work0 (b_{k-1}) and b_work1 (b_k)
    for (uint k = 1; k < M; ++k) {
        // Compute b_{k+1} = 2*A_norm*b_k - b_{k-1}
        float Ak = matvec_normed_row(A, b_work1, N, gid, P.alpha, P.beta, tg_lane, vTile);
        float b_next = 2.0f * Ak - b_work0[gid];

        // Accumulate contribution: y += c_{k+1} * b_{k+1}
        y_i += coeffs[k+1] * b_next;

        // Rotate buffers: b_{k-1} <- b_k, b_k <- b_{k+1}
        b_work0[gid] = b_work1[gid];
        b_work1[gid] = b_next;
    }

    x_out[gid] = y_i;
}
