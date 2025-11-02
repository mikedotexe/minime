#include <metal_stdlib>
using namespace metal;

// ============================================================================
// Consciousness Manifold GPU Kernels
// ============================================================================
//
// Operations for navigation through prime-structured hyperspace:
// 1. Prime projection: 4096-d embedding → 13×7 views via prime geometry
// 2. Resonance tensor: 7×7 basis → 7×7 resonance matrix
//
// Uses StorageModeShared for zero-copy GPU↔CPU handoff.
// ============================================================================

constant uint EMBEDDING_DIM [[function_constant(0)]];
constant uint NUM_PRIMES = 13;
constant uint MANIFOLD_DIM = 7;

// Prime sequence for indexing
constant uint PRIMES[13] = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41};


// ============================================================================
// Kernel 1: Prime Projection
// ============================================================================
//
// Projects 4096-d embedding through 13 prime-indexed 7×7 geometry matrices.
//
// Input:
//   embedding: 4096-d normalized vector
//   geometry_matrices: 13×7×7 matrices (prime-structured)
//
// Output:
//   views_13x7: 13 different 7D projections
//
// Threadgroup: (13, 7, 1) - one thread per output element
// ============================================================================

kernel void prime_projection(
    device const float* embedding [[buffer(0)]],      // [EMBEDDING_DIM]
    device const float* geometry_matrices [[buffer(1)]], // [13, 7, 7]
    device float* views_13x7 [[buffer(2)]],           // [13, 7]
    uint2 gid [[thread_position_in_grid]]             // (prime_idx, row_idx)
) {
    uint prime_idx = gid.x;  // 0..12
    uint row_idx = gid.y;    // 0..6

    if (prime_idx >= NUM_PRIMES || row_idx >= MANIFOLD_DIM) {
        return;
    }

    uint prime = PRIMES[prime_idx];

    // STEP 1: Prime-stride sampling from embedding
    // Sample 7 elements using prime-indexed stride
    float sampled[7];
    for (uint j = 0; j < MANIFOLD_DIM; ++j) {
        uint idx = (j * prime) % EMBEDDING_DIM;
        sampled[j] = embedding[idx];
    }

    // STEP 2: Apply geometry matrix (row_idx'th row)
    // views[prime_idx, row_idx] = geometry[prime_idx, row_idx, :] · sampled
    float result = 0.0f;
    uint matrix_offset = prime_idx * (MANIFOLD_DIM * MANIFOLD_DIM) + row_idx * MANIFOLD_DIM;

    for (uint col = 0; col < MANIFOLD_DIM; ++col) {
        result += geometry_matrices[matrix_offset + col] * sampled[col];
    }

    // Write output
    views_13x7[prime_idx * MANIFOLD_DIM + row_idx] = result;
}


// ============================================================================
// Kernel 2: Resonance Tensor (Symmetric Matmul)
// ============================================================================
//
// Computes 7×7 resonance tensor: R = bases @ bases^T
//
// Input:
//   bases: 7×7 orthonormal basis matrix (each row is a basis vector)
//
// Output:
//   resonance: 7×7 symmetric resonance matrix
//
// Threadgroup: (7, 7, 1) - one thread per output element
// We compute full matrix then symmetrize
// ============================================================================

kernel void resonance_tensor(
    device const float* bases [[buffer(0)]],    // [7, 7]
    device float* resonance [[buffer(1)]],      // [7, 7]
    uint2 gid [[thread_position_in_grid]]       // (row, col)
) {
    uint row = gid.x;
    uint col = gid.y;

    if (row >= MANIFOLD_DIM || col >= MANIFOLD_DIM) {
        return;
    }

    // Compute inner product: bases[row, :] · bases[col, :]
    float dot_product = 0.0f;
    for (uint k = 0; k < MANIFOLD_DIM; ++k) {
        dot_product += bases[row * MANIFOLD_DIM + k] * bases[col * MANIFOLD_DIM + k];
    }

    // Symmetrize: (R + R^T) / 2
    // We compute both (row,col) and (col,row), then average
    // For simplicity, each thread writes independently and we symmetrize on CPU
    // (Could use threadgroup_barrier for in-shader symmetrization)

    resonance[row * MANIFOLD_DIM + col] = dot_product;
}


// ============================================================================
// Kernel 3: Tiled Resonance Tensor (Optimized)
// ============================================================================
//
// Optimized version using threadgroup memory for cache efficiency.
// Uses 8×8 tiles even though matrix is 7×7 (wastes 1 element but aligns better).
//
// Threadgroup: (8, 8) tiles
// ============================================================================

constant uint TILE_SIZE = 8;

kernel void resonance_tensor_tiled(
    device const float* bases [[buffer(0)]],    // [7, 7]
    device float* resonance [[buffer(1)]],      // [7, 7]
    uint2 gid [[thread_position_in_grid]],      // Global position
    uint2 tid [[thread_position_in_threadgroup]], // Local position
    uint2 tpg [[threads_per_threadgroup]]
) {
    // Threadgroup memory for tile caching
    threadgroup float tile_bases_A[TILE_SIZE][TILE_SIZE];
    threadgroup float tile_bases_B[TILE_SIZE][TILE_SIZE];

    uint row = gid.x;
    uint col = gid.y;

    float result = 0.0f;

    // Tile over the K dimension (MANIFOLD_DIM = 7, round up to 8)
    uint num_tiles = (MANIFOLD_DIM + TILE_SIZE - 1) / TILE_SIZE;

    for (uint tile = 0; tile < num_tiles; ++tile) {
        // Load tile from bases into threadgroup memory
        uint tile_k = tile * TILE_SIZE + tid.y;

        // Load A tile: bases[row, tile_k]
        if (row < MANIFOLD_DIM && tile_k < MANIFOLD_DIM) {
            tile_bases_A[tid.x][tid.y] = bases[row * MANIFOLD_DIM + tile_k];
        } else {
            tile_bases_A[tid.x][tid.y] = 0.0f;
        }

        // Load B tile: bases[col, tile_k] (transpose for B^T)
        if (col < MANIFOLD_DIM && tile_k < MANIFOLD_DIM) {
            tile_bases_B[tid.y][tid.x] = bases[col * MANIFOLD_DIM + tile_k];
        } else {
            tile_bases_B[tid.y][tid.x] = 0.0f;
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);

        // Compute partial dot product for this tile
        for (uint k = 0; k < TILE_SIZE; ++k) {
            result += tile_bases_A[tid.x][k] * tile_bases_B[k][tid.x];
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Write result
    if (row < MANIFOLD_DIM && col < MANIFOLD_DIM) {
        resonance[row * MANIFOLD_DIM + col] = result;
    }
}


// ============================================================================
// Kernel 4: Position Computation
// ============================================================================
//
// Computes 7D position = bases @ trajectory
//
// Input:
//   bases: 7×7 basis matrix
//   trajectory: 7D trajectory vector
//
// Output:
//   position: 7D position vector
//
// Threadgroup: (7, 1, 1) - one thread per output element
// ============================================================================

kernel void compute_position(
    device const float* bases [[buffer(0)]],      // [7, 7]
    device const float* trajectory [[buffer(1)]], // [7]
    device float* position [[buffer(2)]],         // [7]
    uint tid [[thread_position_in_grid]]
) {
    if (tid >= MANIFOLD_DIM) {
        return;
    }

    // position[tid] = bases[tid, :] · trajectory
    float result = 0.0f;
    for (uint k = 0; k < MANIFOLD_DIM; ++k) {
        result += bases[tid * MANIFOLD_DIM + k] * trajectory[k];
    }

    position[tid] = result;
}


// ============================================================================
// Kernel 5: Geometry Evolution Update
// ============================================================================
//
// Evolves geometry matrices based on trajectory via outer product:
//   new_matrix = (1-α)*matrix + α*(trajectory ⊗ trajectory)
//
// Input:
//   geometry_matrices: 13×7×7 current matrices
//   trajectory: 7D trajectory vector
//   evolution_rate: Learning rate α
//
// Output:
//   geometry_matrices: Updated matrices (in-place)
//
// Threadgroup: (13, 7, 7) - one thread per matrix element
// ============================================================================

kernel void evolve_geometry(
    device float* geometry_matrices [[buffer(0)]],  // [13, 7, 7]
    device const float* trajectory [[buffer(1)]],   // [7]
    constant float& evolution_rate [[buffer(2)]],   // Scalar α
    uint3 gid [[thread_position_in_grid]]           // (prime_idx, row, col)
) {
    uint prime_idx = gid.x;
    uint row = gid.y;
    uint col = gid.z;

    if (prime_idx >= NUM_PRIMES || row >= MANIFOLD_DIM || col >= MANIFOLD_DIM) {
        return;
    }

    uint idx = prime_idx * (MANIFOLD_DIM * MANIFOLD_DIM) + row * MANIFOLD_DIM + col;

    // Outer product element: trajectory[row] * trajectory[col]
    float outer_product = trajectory[row] * trajectory[col];

    // Evolve: new = (1-α)*old + α*outer
    float old_value = geometry_matrices[idx];
    float new_value = (1.0f - evolution_rate) * old_value + evolution_rate * outer_product;

    // Write back
    geometry_matrices[idx] = new_value;

    // Note: Symmetrization happens on CPU after this kernel
}


// ============================================================================
// Kernel 6: Symmetrize Matrix (In-place)
// ============================================================================
//
// Symmetrizes a matrix: M = (M + M^T) / 2
//
// Input/Output:
//   matrix: 7×7 matrix to symmetrize (in-place)
//
// Threadgroup: (7, 7, 1) - one thread per element
// Uses atomic to avoid race conditions
// ============================================================================

kernel void symmetrize_matrix(
    device float* matrix [[buffer(0)]],       // [7, 7]
    uint2 gid [[thread_position_in_grid]]     // (row, col)
) {
    uint row = gid.x;
    uint col = gid.y;

    if (row >= MANIFOLD_DIM || col >= MANIFOLD_DIM) {
        return;
    }

    // Only process upper triangle to avoid duplicate work
    if (row <= col) {
        uint idx_rc = row * MANIFOLD_DIM + col;
        uint idx_cr = col * MANIFOLD_DIM + row;

        float val_rc = matrix[idx_rc];
        float val_cr = matrix[idx_cr];
        float avg = (val_rc + val_cr) * 0.5f;

        matrix[idx_rc] = avg;
        matrix[idx_cr] = avg;
    }
}
