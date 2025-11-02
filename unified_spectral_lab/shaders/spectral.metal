#include <metal_stdlib>
using namespace metal;

// Set these to taste. TILE=32 is usually sweet on Apple GPUs.
constant uint TILE = 32;
constant uint KMAX = 16;   // Maximum block size supported by the kernel

// y = A * x   (row-major A, length-N x)
kernel void matvec_tiled(
    device const float* A     [[buffer(0)]],
    device const float* x_in  [[buffer(1)]],
    device float*       y_out [[buffer(2)]],
    constant uint&      N     [[buffer(3)]],
    uint row [[thread_position_in_grid]],
    uint tid [[thread_index_in_threadgroup]]
){
    if (row >= N) return;
    threadgroup float xtile[TILE + 1]; // +1 pad helps bank conflicts (cheap prime-ish trick)

    float sum = 0.0f;
    const uint tiles = (N + TILE - 1) / TILE;

    for (uint t = 0; t < tiles; ++t) {
        uint c = t*TILE + tid;
        xtile[tid] = (c < N) ? x_in[c] : 0.0f;
        threadgroup_barrier(mem_flags::mem_threadgroup);

        uint here = min(uint(TILE), uint(N - t*TILE));
        const device float* arow = A + row * (uint)N + t*TILE;

        #pragma unroll
        for (uint j = 0; j < here; ++j) {
            sum += arow[j] * xtile[j];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    y_out[row] = sum;
}

// Y = A * X   (X,Y are column-major: leading dimension = N; K <= KMAX)
kernel void block_matvec_tiled(
    device const float* A     [[buffer(0)]],
    device const float* X_in  [[buffer(1)]],
    device float*       Y_out [[buffer(2)]],
    constant uint&      N     [[buffer(3)]],
    constant uint&      K     [[buffer(4)]],
    uint row [[thread_position_in_grid]],
    uint tid [[thread_index_in_threadgroup]]
){
    if (row >= N) return;

    threadgroup float xtile[TILE * KMAX];
    float acc[KMAX];
    for (uint c=0; c<KMAX; ++c) acc[c] = 0.0f;

    const uint tiles = (N + TILE - 1) / TILE;

    for (uint t = 0; t < tiles; ++t) {
        // Load a TILE-chunk for each column into threadgroup memory
        uint colidx = t*TILE + tid;
        if (tid < TILE) {
            #pragma unroll
            for (uint c=0; c<KMAX; ++c) {
                if (c < K) {
                    float v = (colidx < N) ? X_in[c*(uint)N + colidx] : 0.0f;
                    xtile[c*TILE + tid] = v;
                }
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        uint here = min(uint(TILE), uint(N - t*TILE));
        const device float* arow = A + row*(uint)N + t*TILE;

        #pragma unroll
        for (uint j = 0; j < here; ++j) {
            float a = arow[j];
            #pragma unroll
            for (uint c=0; c<KMAX; ++c) {
                if (c < K) acc[c] += a * xtile[c*TILE + j];
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    #pragma unroll
    for (uint c=0; c<KMAX; ++c) {
        if (c < K) Y_out[c*(uint)N + row] = acc[c];
    }
}
