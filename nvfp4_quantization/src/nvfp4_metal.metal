#include <metal_stdlib>
using namespace metal;

// ============================================================================
// NVFP4 Metal Kernels for Apple Silicon (M3-optimized)
// ============================================================================

// Constants matching CPU implementation
constant float FP4_MAGNITUDES[8] = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f};
constant uint TILE_SIZE = 16;
constant uint TILE_ELEMENTS = 256;  // 16x16

// ============================================================================
// Helper Functions
// ============================================================================

// Decode E4M3 scale (448 max range)
inline float decode_e4m3(uchar e4m3_byte) {
    if (e4m3_byte == 0) return 0.0f;

    float sign = (e4m3_byte & 0x80) ? -1.0f : 1.0f;
    int exp_biased = (e4m3_byte >> 3) & 0x0F;
    int mantissa = e4m3_byte & 0x07;

    int exponent = exp_biased - 7;
    float significand = 1.0f + float(mantissa) / 8.0f;

    return sign * significand * exp2(float(exponent));
}

// Decode FP4 E2M1 nibble to float
inline float decode_fp4(uchar nibble) {
    float sign = (nibble & 0x08) ? -1.0f : 1.0f;
    uint idx = nibble & 0x07;
    return sign * FP4_MAGNITUDES[idx];
}

// Extract nibble from packed byte array
inline uchar get_nibble(device const uchar* data, uint idx) {
    uint byte_idx = idx / 2;
    uchar byte = data[byte_idx];
    return (idx & 1) ? (byte >> 4) : (byte & 0x0F);
}

// ============================================================================
// Kernel: NVFP4 Dequantization
// ============================================================================

kernel void nvfp4_dequantize(
    device const float* header [[buffer(0)]],      // Global scale + dimensions
    device const uchar* tile_scales [[buffer(1)]], // E4M3 tile scales
    device const uchar* fp4_data [[buffer(2)]],    // Packed FP4 data
    device float* output [[buffer(3)]],            // Dequantized output
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_size [[threads_per_threadgroup]]
) {
    // Parse header
    float global_scale = header[0];
    uint rows = as_type<uint>(header[1]);
    uint cols = as_type<uint>(header[2]);

    uint row = gid.y;
    uint col = gid.x;

    if (row >= rows || col >= cols) return;

    // Determine tile coordinates
    uint tile_r = row / TILE_SIZE;
    uint tile_c = col / TILE_SIZE;
    uint tiles_per_row = (cols + TILE_SIZE - 1) / TILE_SIZE;
    uint tile_idx = tile_r * tiles_per_row + tile_c;

    // Load tile scale
    float tile_scale = decode_e4m3(tile_scales[tile_idx]) * global_scale;

    // Get FP4 value
    uint element_idx = row * cols + col;
    uchar nibble = get_nibble(fp4_data, element_idx);
    float fp4_value = decode_fp4(nibble);

    // Store dequantized value
    output[element_idx] = fp4_value * tile_scale;
}

// ============================================================================
// Kernel: NVFP4 Matrix-Vector Multiplication (GEMV)
// ============================================================================

kernel void nvfp4_gemv(
    device const float* header [[buffer(0)]],      // Global scale + dimensions
    device const uchar* tile_scales [[buffer(1)]], // E4M3 tile scales
    device const uchar* fp4_data [[buffer(2)]],    // Packed FP4 data
    device const float* input_vector [[buffer(3)]], // Input vector
    device float* output_vector [[buffer(4)]],     // Output vector
    device float* partial_sums [[buffer(5)]],      // Workspace for reductions
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_size [[threads_per_threadgroup]],
    uint2 tg_id [[threadgroup_position_in_grid]]
) {
    // Parse header
    float global_scale = header[0];
    uint rows = as_type<uint>(header[1]);
    uint cols = as_type<uint>(header[2]);

    uint row = tg_id.y;  // Each threadgroup handles one output row
    uint local_id = tid.x;
    uint group_size = tg_size.x;

    if (row >= rows) return;

    // Shared memory for tile processing
    threadgroup float tile_cache[TILE_ELEMENTS];
    threadgroup float input_cache[TILE_SIZE];
    threadgroup float reduction_buffer[256];  // Max threadgroup size

    float local_sum = 0.0f;
    uint tiles_per_row = (cols + TILE_SIZE - 1) / TILE_SIZE;

    // Process tiles in this row
    for (uint tile_c = 0; tile_c < tiles_per_row; tile_c++) {
        uint tile_idx = row * tiles_per_row + tile_c;
        float tile_scale = decode_e4m3(tile_scales[tile_idx]) * global_scale;

        uint col_start = tile_c * TILE_SIZE;
        uint col_end = min(col_start + TILE_SIZE, cols);
        uint tile_width = col_end - col_start;

        // Cooperatively load input vector for this tile
        if (local_id < tile_width) {
            input_cache[local_id] = input_vector[col_start + local_id];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        // Each thread processes multiple elements in the tile
        uint elems_per_thread = (tile_width + group_size - 1) / group_size;
        for (uint i = 0; i < elems_per_thread; i++) {
            uint col_idx = local_id + i * group_size;
            if (col_idx < tile_width) {
                uint global_col = col_start + col_idx;
                uint element_idx = row * cols + global_col;

                // Decode FP4 value
                uchar nibble = get_nibble(fp4_data, element_idx);
                float fp4_value = decode_fp4(nibble);

                // Multiply and accumulate
                local_sum += fp4_value * tile_scale * input_cache[col_idx];
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Reduce across threadgroup
    reduction_buffer[local_id] = local_sum;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Tree reduction
    for (uint stride = group_size / 2; stride > 0; stride /= 2) {
        if (local_id < stride) {
            reduction_buffer[local_id] += reduction_buffer[local_id + stride];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Write final result
    if (local_id == 0) {
        output_vector[row] = reduction_buffer[0];
    }
}

// ============================================================================
// Kernel: NVFP4 Matrix-Matrix Multiplication (GEMM) - M3 Optimized
// ============================================================================

kernel void nvfp4_gemm_tiled(
    device const float* A_header [[buffer(0)]],     // Matrix A header
    device const uchar* A_scales [[buffer(1)]],     // Matrix A tile scales
    device const uchar* A_data [[buffer(2)]],       // Matrix A FP4 data
    device const float* B [[buffer(3)]],            // Matrix B (FP32)
    device float* C [[buffer(4)]],                  // Output matrix C
    constant uint3& dimensions [[buffer(5)]],       // M, N, K dimensions
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_id [[threadgroup_position_in_grid]]
) {
    uint M = dimensions.x;  // A rows, C rows
    uint N = dimensions.y;  // B cols, C cols
    uint K = dimensions.z;  // A cols, B rows

    // M3's larger threadgroup memory allows bigger tiles
    const uint TG_M = 32;  // Threadgroup tile height
    const uint TG_N = 32;  // Threadgroup tile width
    const uint TG_K = 16;  // Threadgroup tile depth

    threadgroup float A_tile[TG_M * TG_K];
    threadgroup float B_tile[TG_K * TG_N];

    // Calculate global position
    uint global_row = tg_id.y * TG_M + tid.y;
    uint global_col = tg_id.x * TG_N + tid.x;

    // Initialize accumulator
    float sum = 0.0f;

    float A_global_scale = A_header[0];
    uint A_tiles_per_row = (K + TILE_SIZE - 1) / TILE_SIZE;

    // Loop over K dimension in chunks of TG_K
    for (uint k_base = 0; k_base < K; k_base += TG_K) {
        // Cooperatively load and dequantize A tile
        if (tid.x < TG_K && global_row < M) {
            uint k = k_base + tid.x;
            if (k < K) {
                // Determine which NVFP4 tile this element belongs to
                uint nvfp4_tile_c = k / TILE_SIZE;
                uint nvfp4_tile_idx = global_row * A_tiles_per_row + nvfp4_tile_c;

                float tile_scale = decode_e4m3(A_scales[nvfp4_tile_idx]) * A_global_scale;

                uint element_idx = global_row * K + k;
                uchar nibble = get_nibble(A_data, element_idx);
                float value = decode_fp4(nibble) * tile_scale;

                A_tile[tid.y * TG_K + tid.x] = value;
            } else {
                A_tile[tid.y * TG_K + tid.x] = 0.0f;
            }
        }

        // Load B tile
        if (tid.y < TG_K && global_col < N) {
            uint k = k_base + tid.y;
            if (k < K) {
                B_tile[tid.y * TG_N + tid.x] = B[k * N + global_col];
            } else {
                B_tile[tid.y * TG_N + tid.x] = 0.0f;
            }
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);

        // Compute partial dot product
        for (uint k = 0; k < TG_K; k++) {
            sum += A_tile[tid.y * TG_K + k] * B_tile[k * TG_N + tid.x];
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Write result
    if (global_row < M && global_col < N) {
        C[global_row * N + global_col] = sum;
    }
}

// ============================================================================
// Kernel: Fused NVFP4 Dequantize + GEMM (Single Pass)
// ============================================================================

kernel void nvfp4_fused_gemm(
    device const float* A_header [[buffer(0)]],
    device const uchar* A_scales [[buffer(1)]],
    device const uchar* A_data [[buffer(2)]],
    device const float* B [[buffer(3)]],
    device float* C [[buffer(4)]],
    constant uint3& dimensions [[buffer(5)]],
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_id [[threadgroup_position_in_grid]],
    uint2 tg_size [[threads_per_threadgroup]]
) {
    uint M = dimensions.x;
    uint N = dimensions.y;
    uint K = dimensions.z;

    uint row = gid.y;
    uint col = gid.x;

    if (row >= M || col >= N) return;

    float A_global_scale = A_header[0];
    uint A_tiles_per_row = (K + TILE_SIZE - 1) / TILE_SIZE;

    float sum = 0.0f;

    // Process in NVFP4 tile-aligned chunks for better cache usage
    for (uint tile_k = 0; tile_k < A_tiles_per_row; tile_k++) {
        uint k_start = tile_k * TILE_SIZE;
        uint k_end = min(k_start + TILE_SIZE, K);

        // Get tile scale for this chunk
        uint nvfp4_tile_idx = row * A_tiles_per_row + tile_k;
        float tile_scale = decode_e4m3(A_scales[nvfp4_tile_idx]) * A_global_scale;

        // Process elements in this tile
        for (uint k = k_start; k < k_end; k++) {
            // Decode A[row, k]
            uint element_idx = row * K + k;
            uchar nibble = get_nibble(A_data, element_idx);
            float a_value = decode_fp4(nibble) * tile_scale;

            // Multiply with B[k, col]
            float b_value = B[k * N + col];
            sum += a_value * b_value;
        }
    }

    C[row * N + col] = sum;
}

// ============================================================================
// Kernel: Convert FP32 to NVFP4 (for model conversion)
// ============================================================================

kernel void nvfp4_quantize(
    device const float* input [[buffer(0)]],
    device float* header [[buffer(1)]],
    device uchar* tile_scales [[buffer(2)]],
    device uchar* fp4_data [[buffer(3)]],
    constant uint2& dimensions [[buffer(4)]],  // rows, cols
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]],
    uint2 tg_id [[threadgroup_position_in_grid]]
) {
    uint rows = dimensions.x;
    uint cols = dimensions.y;

    // Each threadgroup processes one tile
    uint tile_r = tg_id.y;
    uint tile_c = tg_id.x;
    uint tiles_per_row = (cols + TILE_SIZE - 1) / TILE_SIZE;

    if (tile_r * TILE_SIZE >= rows || tile_c * TILE_SIZE >= cols) return;

    uint tile_idx = tile_r * tiles_per_row + tile_c;

    // Shared memory for tile processing
    threadgroup float tile_values[TILE_ELEMENTS];
    threadgroup float max_values[256];  // For reduction

    // Load tile values and find max
    uint local_idx = tid.y * TILE_SIZE + tid.x;
    float local_max = 0.0f;

    if (local_idx < TILE_ELEMENTS) {
        uint row = tile_r * TILE_SIZE + tid.y;
        uint col = tile_c * TILE_SIZE + tid.x;

        if (row < rows && col < cols) {
            float value = input[row * cols + col];
            tile_values[local_idx] = value;
            local_max = abs(value);
        } else {
            tile_values[local_idx] = 0.0f;
        }
    }

    // Find tile maximum via reduction
    max_values[local_idx] = local_max;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Tree reduction to find max
    for (uint stride = 128; stride > 0; stride /= 2) {
        if (local_idx < stride && local_idx + stride < TILE_ELEMENTS) {
            max_values[local_idx] = max(max_values[local_idx], max_values[local_idx + stride]);
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Thread 0 computes and writes tile scale
    if (local_idx == 0) {
        float tile_max = max_values[0];
        float scale_dec = (tile_max > 0.0f) ? tile_max / 6.0f : 0.0f;

        // Assume global scale is precomputed and stored in header[0]
        float global_scale_enc = 1.0f / header[0];
        float scale_for_e4m3 = scale_dec * global_scale_enc;

        // Simplified E4M3 encoding (full implementation would match CPU)
        uchar e4m3_byte = 0;
        if (scale_for_e4m3 > 0.0f && scale_for_e4m3 < 448.0f) {
            int exp = int(log2(scale_for_e4m3));
            float sig = scale_for_e4m3 / exp2(float(exp));
            int exp_biased = clamp(exp + 7, 0, 14);
            int mant = int((sig - 1.0f) * 8.0f + 0.5f);
            e4m3_byte = (exp_biased << 3) | (mant & 0x07);
        }

        tile_scales[tile_idx] = e4m3_byte;
    }

    threadgroup_barrier(mem_flags::mem_device);

    // All threads quantize their values
    if (local_idx < TILE_ELEMENTS) {
        uint row = tile_r * TILE_SIZE + tid.y;
        uint col = tile_c * TILE_SIZE + tid.x;

        if (row < rows && col < cols) {
            float value = tile_values[local_idx];
            float tile_scale_enc = (max_values[0] > 0.0f) ? 6.0f / max_values[0] : 0.0f;
            float scaled = value * tile_scale_enc;

            // Quantize to FP4
            float abs_scaled = abs(scaled);
            uint best_idx = 0;
            float best_error = abs_scaled;

            for (uint i = 1; i < 8; i++) {
                float error = abs(abs_scaled - FP4_MAGNITUDES[i]);
                if (error < best_error) {
                    best_error = error;
                    best_idx = i;
                }
            }

            uchar nibble = (scaled < 0.0f ? 0x08 : 0x00) | best_idx;

            // Pack nibble
            uint element_idx = row * cols + col;
            uint byte_idx = element_idx / 2;

            // Use atomic operations to handle concurrent writes to same byte
            if (element_idx & 1) {
                atomic_fetch_or((device atomic_uint*)&fp4_data[byte_idx], uint(nibble) << 4);
            } else {
                atomic_fetch_or((device atomic_uint*)&fp4_data[byte_idx], uint(nibble));
            }
        }
    }
}