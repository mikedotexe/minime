#include "nvfp4_format.h"
#include <cmath>
#include <cstring>
#include <algorithm>
#include <cassert>

#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

// ============================================================================
// E4M3 Scale Conversion (448 max range)
// ============================================================================

uint8_t nvfp4_f32_to_e4m3(float x) {
    if (x == 0.0f || !std::isfinite(x)) return 0;

    uint8_t sign_bit = x < 0.0f ? 0x80 : 0x00;
    float ax = std::fabs(x);
    ax = std::fmin(ax, NVFP4_E4M3_MAX_VALUE);

    // Extract exponent
    int exp = (int)std::floor(std::log2f(ax));
    float sig = ax / std::exp2f((float)exp);

    // Normalize significand
    if (sig < 1.0f) {
        exp--;
        sig *= 2.0f;
    }

    // Clamp exponent
    exp = std::max(NVFP4_E4M3_MIN_EXP, std::min(NVFP4_E4M3_MAX_EXP, exp));

    // Special handling for max exponent
    float max_sig = (exp == NVFP4_E4M3_MAX_EXP) ? 1.75f : 1.875f;
    sig = std::fmin(std::fmax(sig, 1.0f), max_sig);

    // Quantize mantissa (3 bits)
    uint8_t mant = (uint8_t)std::round((sig - 1.0f) * 8.0f);
    mant = std::min(mant, (uint8_t)((exp == NVFP4_E4M3_MAX_EXP) ? 6 : 7));

    // Pack: [S:1][E:4][M:3]
    uint8_t exp_biased = (uint8_t)(exp + NVFP4_E4M3_EXP_BIAS);
    return sign_bit | (exp_biased << 3) | mant;
}

float nvfp4_e4m3_to_f32(uint8_t e4m3) {
    if (e4m3 == 0) return 0.0f;

    float sign = (e4m3 & 0x80) ? -1.0f : 1.0f;
    int exp_biased = (e4m3 >> 3) & 0x0F;
    int mant = e4m3 & 0x07;

    int exp = exp_biased - NVFP4_E4M3_EXP_BIAS;
    float sig = 1.0f + (float)mant / 8.0f;

    return sign * sig * std::exp2f((float)exp);
}

// ============================================================================
// FP4 E2M1 Quantization
// ============================================================================

uint8_t nvfp4_quantize_fp4(float x) {
    uint8_t sign_bit = (x < 0.0f) ? 0x08 : 0x00;
    float ax = std::fabs(x);

    // Find nearest magnitude
    uint8_t best_idx = 0;
    float best_error = std::fabs(ax - NVFP4_E2M1_MAGNITUDES[0]);

    for (uint8_t i = 1; i < 8; i++) {
        float error = std::fabs(ax - NVFP4_E2M1_MAGNITUDES[i]);
        if (error < best_error) {
            best_error = error;
            best_idx = i;
        }
    }

    return sign_bit | best_idx;
}

float nvfp4_dequantize_fp4(uint8_t nibble) {
    float sign = (nibble & 0x08) ? -1.0f : 1.0f;
    uint8_t idx = nibble & 0x07;
    return sign * NVFP4_E2M1_MAGNITUDES[idx];
}

// ============================================================================
// Tile Operations
// ============================================================================

void nvfp4_extract_tile(const float* matrix, int rows, int cols,
                        int tile_r, int tile_c, nvfp4_tile_t* tile) {
    tile->amax = 0.0f;

    int r_start = tile_r * NVFP4_TILE_SIZE;
    int c_start = tile_c * NVFP4_TILE_SIZE;
    int r_end = std::min(r_start + NVFP4_TILE_SIZE, rows);
    int c_end = std::min(c_start + NVFP4_TILE_SIZE, cols);

    // Extract tile values and compute max
    int tile_idx = 0;
    for (int r = r_start; r < r_end; r++) {
        for (int c = c_start; c < c_end; c++) {
            float val = matrix[r * cols + c];
            tile->values[tile_idx++] = val;
            tile->amax = std::fmax(tile->amax, std::fabs(val));
        }
    }

    // Pad with zeros if tile is incomplete
    while (tile_idx < NVFP4_TILE_ELEMENTS) {
        tile->values[tile_idx++] = 0.0f;
    }

    // Compute scales
    tile->scale_dec = (tile->amax > 0.0f) ? tile->amax / 6.0f : 0.0f;
    tile->scale_enc = (tile->scale_dec > 0.0f) ? 1.0f / tile->scale_dec : 0.0f;
}

// ============================================================================
// Main Quantization Function
// ============================================================================

void quantize_row_q4_nv2d_reference(const float* x, nvfp4_block_t* y, int k) {
    // This is the 2D-aware version that respects matrix dimensions
    // For simplicity in GGML integration, we'll need a wrapper that handles 1D
    assert(false && "Use quantize_row_q4_nv2d instead");
}

void quantize_row_q4_nv2d(const float* x, void* vy, int k) {
    nvfp4_block_t* y = (nvfp4_block_t*)vy;

    // For 1D row quantization, treat as 1×k matrix
    y->header.rows = 1;
    y->header.cols = k;
    y->header.tile_size = NVFP4_TILE_SIZE;
    y->header.flags = 0;

    // Compute global scale
    float amax = 0.0f;
    for (int i = 0; i < k; i++) {
        amax = std::fmax(amax, std::fabs(x[i]));
    }

    float s_enc = (amax > 0.0f) ? (6.0f * NVFP4_E4M3_MAX_VALUE) / amax : 1.0f;
    y->header.global_scale = 1.0f / s_enc;  // Store decode scale

    // Calculate tile layout
    int tiles_per_row = (k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    uint8_t* tile_scales = (uint8_t*)(&y[1]);
    uint8_t* fp4_data = tile_scales + tiles_per_row;

    // Process each tile
    for (int tc = 0; tc < tiles_per_row; tc++) {
        int c_start = tc * NVFP4_TILE_SIZE;
        int c_end = std::min(c_start + NVFP4_TILE_SIZE, k);

        // Find tile max
        float tile_amax = 0.0f;
        for (int c = c_start; c < c_end; c++) {
            tile_amax = std::fmax(tile_amax, std::fabs(x[c]));
        }

        // Compute and store tile scale
        float s_dec_tile = (tile_amax > 0.0f) ? tile_amax / 6.0f : 0.0f;
        tile_scales[tc] = nvfp4_f32_to_e4m3(s_dec_tile * s_enc);

        // Compute effective encoding scale for this tile
        float s_enc_tile = (s_dec_tile > 0.0f) ? 1.0f / s_dec_tile : 0.0f;

        // Quantize tile values to FP4
        for (int c = c_start; c < c_end; c++) {
            float scaled = x[c] * s_enc_tile;
            uint8_t fp4 = nvfp4_quantize_fp4(scaled);

            // Pack nibbles (2 FP4 values per byte)
            int byte_idx = c / 2;
            if (c & 1) {
                fp4_data[byte_idx] |= (fp4 << 4);
            } else {
                fp4_data[byte_idx] = fp4 & 0x0F;
            }
        }
    }
}

// ============================================================================
// Main Dequantization Function
// ============================================================================

void dequantize_row_q4_nv2d(const void* vx, float* y, int k) {
    const nvfp4_block_t* x = (const nvfp4_block_t*)vx;

    assert(x->header.rows == 1);  // Row dequantization
    assert(x->header.cols == k);
    assert(x->header.tile_size == NVFP4_TILE_SIZE);

    const uint8_t* tile_scales = (const uint8_t*)(&x[1]);
    const uint8_t* fp4_data = tile_scales + ((k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE);
    float global_scale = x->header.global_scale;

    int tiles_per_row = (k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;

    // Process each tile
    for (int tc = 0; tc < tiles_per_row; tc++) {
        int c_start = tc * NVFP4_TILE_SIZE;
        int c_end = std::min(c_start + NVFP4_TILE_SIZE, k);

        // Decode tile scale
        float tile_scale = nvfp4_e4m3_to_f32(tile_scales[tc]) * global_scale;

        // Dequantize tile values
        for (int c = c_start; c < c_end; c++) {
            // Extract FP4 nibble
            int byte_idx = c / 2;
            uint8_t nibble = (c & 1) ?
                (fp4_data[byte_idx] >> 4) :
                (fp4_data[byte_idx] & 0x0F);

            // Decode and scale
            float fp4_value = nvfp4_dequantize_fp4(nibble);
            y[c] = fp4_value * tile_scale;
        }
    }
}

// ============================================================================
// Dot Product Operations
// ============================================================================

float vec_dot_q4_nv2d_f32(const void* vx, const float* vy, int k) {
    const nvfp4_block_t* x = (const nvfp4_block_t*)vx;

    const uint8_t* tile_scales = (const uint8_t*)(&x[1]);
    const uint8_t* fp4_data = tile_scales + ((k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE);
    float global_scale = x->header.global_scale;

    int tiles_per_row = (k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    float sum = 0.0f;

    // Process each tile
    for (int tc = 0; tc < tiles_per_row; tc++) {
        int c_start = tc * NVFP4_TILE_SIZE;
        int c_end = std::min(c_start + NVFP4_TILE_SIZE, k);

        // Decode tile scale
        float tile_scale = nvfp4_e4m3_to_f32(tile_scales[tc]) * global_scale;
        float tile_sum = 0.0f;

        // Compute dot product for this tile
        for (int c = c_start; c < c_end; c++) {
            // Extract FP4 nibble
            int byte_idx = c / 2;
            uint8_t nibble = (c & 1) ?
                (fp4_data[byte_idx] >> 4) :
                (fp4_data[byte_idx] & 0x0F);

            // Decode and multiply
            float fp4_value = nvfp4_dequantize_fp4(nibble);
            tile_sum += fp4_value * vy[c];
        }

        sum += tile_sum * tile_scale;
    }

    return sum;
}

// ============================================================================
// SIMD Optimizations for Apple Silicon (NEON)
// ============================================================================

#ifdef __ARM_NEON

// Helper: Load 8 FP4 values (4 bytes) and dequantize to float32x4_t x2
static inline void nvfp4_load_and_dequantize_8(const uint8_t* fp4_data,
                                               float32x4_t* out_lo,
                                               float32x4_t* out_hi) {
    // Load 4 bytes = 8 FP4 values
    uint32_t packed = *(const uint32_t*)fp4_data;

    // Extract nibbles
    uint8_t nibbles[8];
    for (int i = 0; i < 4; i++) {
        uint8_t byte = (packed >> (i * 8)) & 0xFF;
        nibbles[i*2] = byte & 0x0F;
        nibbles[i*2 + 1] = (byte >> 4) & 0x0F;
    }

    // Dequantize using lookup
    float values[8];
    for (int i = 0; i < 8; i++) {
        float sign = (nibbles[i] & 0x08) ? -1.0f : 1.0f;
        uint8_t idx = nibbles[i] & 0x07;
        values[i] = sign * NVFP4_E2M1_MAGNITUDES[idx];
    }

    // Load into NEON registers
    *out_lo = vld1q_f32(&values[0]);
    *out_hi = vld1q_f32(&values[4]);
}

void nvfp4_dequantize_row_neon(const nvfp4_block_t* x, float* y, int k) {
    const uint8_t* tile_scales = (const uint8_t*)(&x[1]);
    const uint8_t* fp4_data = tile_scales + ((k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE);
    float global_scale = x->header.global_scale;

    int tiles_per_row = (k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;

    for (int tc = 0; tc < tiles_per_row; tc++) {
        int c_start = tc * NVFP4_TILE_SIZE;
        int c_end = std::min(c_start + NVFP4_TILE_SIZE, k);

        // Decode tile scale
        float tile_scale = nvfp4_e4m3_to_f32(tile_scales[tc]) * global_scale;
        float32x4_t vscale = vdupq_n_f32(tile_scale);

        // Process 8 elements at a time
        int c = c_start;
        for (; c + 8 <= c_end; c += 8) {
            float32x4_t v_lo, v_hi;
            nvfp4_load_and_dequantize_8(&fp4_data[c/2], &v_lo, &v_hi);

            // Scale and store
            vst1q_f32(&y[c], vmulq_f32(v_lo, vscale));
            vst1q_f32(&y[c + 4], vmulq_f32(v_hi, vscale));
        }

        // Handle remaining elements
        for (; c < c_end; c++) {
            int byte_idx = c / 2;
            uint8_t nibble = (c & 1) ?
                (fp4_data[byte_idx] >> 4) :
                (fp4_data[byte_idx] & 0x0F);

            float fp4_value = nvfp4_dequantize_fp4(nibble);
            y[c] = fp4_value * tile_scale;
        }
    }
}

float nvfp4_vec_dot_neon(const void* vx, const float* vy, int k) {
    const nvfp4_block_t* x = (const nvfp4_block_t*)vx;

    const uint8_t* tile_scales = (const uint8_t*)(&x[1]);
    const uint8_t* fp4_data = tile_scales + ((k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE);
    float global_scale = x->header.global_scale;

    int tiles_per_row = (k + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    float32x4_t vsum = vdupq_n_f32(0.0f);

    for (int tc = 0; tc < tiles_per_row; tc++) {
        int c_start = tc * NVFP4_TILE_SIZE;
        int c_end = std::min(c_start + NVFP4_TILE_SIZE, k);

        float tile_scale = nvfp4_e4m3_to_f32(tile_scales[tc]) * global_scale;
        float32x4_t vscale = vdupq_n_f32(tile_scale);
        float32x4_t vtile_sum = vdupq_n_f32(0.0f);

        // Process 8 elements at a time
        int c = c_start;
        for (; c + 8 <= c_end; c += 8) {
            float32x4_t v_lo, v_hi;
            nvfp4_load_and_dequantize_8(&fp4_data[c/2], &v_lo, &v_hi);

            // Load y values
            float32x4_t y_lo = vld1q_f32(&vy[c]);
            float32x4_t y_hi = vld1q_f32(&vy[c + 4]);

            // Multiply and accumulate
            vtile_sum = vfmaq_f32(vtile_sum, v_lo, y_lo);
            vtile_sum = vfmaq_f32(vtile_sum, v_hi, y_hi);
        }

        // Scale tile sum and add to total
        vsum = vfmaq_f32(vsum, vtile_sum, vscale);

        // Handle remaining elements
        float scalar_sum = 0.0f;
        for (; c < c_end; c++) {
            int byte_idx = c / 2;
            uint8_t nibble = (c & 1) ?
                (fp4_data[byte_idx] >> 4) :
                (fp4_data[byte_idx] & 0x0F);

            float fp4_value = nvfp4_dequantize_fp4(nibble);
            scalar_sum += fp4_value * vy[c];
        }

        vsum = vaddq_f32(vsum, vdupq_n_f32(scalar_sum * tile_scale));
    }

    // Horizontal sum
    return vaddvq_f32(vsum);
}

#endif // __ARM_NEON

// ============================================================================
// Utility Functions
// ============================================================================

size_t nvfp4_tensor_size(int rows, int cols) {
    size_t header_size = sizeof(nvfp4_tensor_header_t);
    size_t n_tiles = nvfp4_get_n_tiles(rows, cols);
    size_t scales_size = n_tiles;  // 1 byte per tile
    size_t data_size = (rows * cols + 1) / 2;  // 2 FP4 values per byte

    return header_size + scales_size + data_size;
}

size_t nvfp4_get_n_tiles(int rows, int cols) {
    int tiles_r = (rows + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    int tiles_c = (cols + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    return tiles_r * tiles_c;
}

void nvfp4_get_tile_coords(int element_idx, int cols, int* tile_r, int* tile_c, int* in_tile_idx) {
    int row = element_idx / cols;
    int col = element_idx % cols;

    *tile_r = row / NVFP4_TILE_SIZE;
    *tile_c = col / NVFP4_TILE_SIZE;

    int tile_row = row % NVFP4_TILE_SIZE;
    int tile_col = col % NVFP4_TILE_SIZE;
    *in_tile_idx = tile_row * NVFP4_TILE_SIZE + tile_col;
}