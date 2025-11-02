#include <metal_stdlib>
using namespace metal;

constant uint TILE_SIZE = 32;
constant uint KMAX = 16;

// Block matrix-vector: Y = A * X (A: D×D row-major, X/Y: D×K col-major)
kernel void block_matvec_tiled_f32(
    device const float* A     [[buffer(0)]],
    device const float* X_in  [[buffer(1)]],
    device float*       Y_out [[buffer(2)]],
    constant uint&      D     [[buffer(3)]],
    constant uint&      K     [[buffer(4)]],
    uint row [[thread_position_in_grid]],
    uint tid [[thread_index_in_threadgroup]]
){
    if (row >= D) return;

    threadgroup float xtile[TILE_SIZE * KMAX + 1];
    float acc[KMAX];

    #pragma unroll
    for (uint c = 0; c < KMAX; ++c) acc[c] = 0.0f;

    uint tiles = (D + TILE_SIZE - 1) / TILE_SIZE;

    for (uint t = 0; t < tiles; ++t) {
        uint cidx = t * TILE_SIZE + tid;
        if (tid < TILE_SIZE) {
            #pragma unroll
            for (uint c = 0; c < KMAX; ++c) {
                if (c < K) {
                    float v = (cidx < D) ? X_in[c * D + cidx] : 0.0f;
                    xtile[c * TILE_SIZE + tid] = v;
                }
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        const device float* arow = A + row * D + t * TILE_SIZE;
        uint here = min(uint(TILE_SIZE), D - t * TILE_SIZE);

        #pragma unroll
        for (uint j = 0; j < here; ++j) {
            float a = arow[j];
            #pragma unroll
            for (uint c = 0; c < KMAX; ++c) {
                if (c < K) acc[c] += a * xtile[c * TILE_SIZE + j];
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    #pragma unroll
    for (uint c = 0; c < KMAX; ++c) {
        if (c < K) Y_out[c * D + row] = acc[c];
    }
}
