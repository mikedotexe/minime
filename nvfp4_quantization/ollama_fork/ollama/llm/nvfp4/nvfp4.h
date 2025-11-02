#ifndef NVFP4_H
#define NVFP4_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// NVFP4 format constants
#define NVFP4_TILE_SIZE 16
#define NVFP4_E2M1_MAGNITUDES {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f}

// NVFP4 block structure (for 16x16 tile)
typedef struct {
    float global_scale;      // Per-tensor scale
    uint8_t tile_scales[1];  // E4M3 scales (variable length)
    uint8_t fp4_data[1];     // Packed FP4 nibbles (variable length)
} nvfp4_block_t;

// Quantization functions
void quantize_row_q4_nv2d(const float* x, void* y, int k);
void dequantize_row_q4_nv2d(const void* x, float* y, int k);

// Dot product functions
float vec_dot_q4_nv2d_q8_0(const void* vx, const void* vy, int k);

// Utility functions
size_t nvfp4_get_block_size(int rows, int cols);
void nvfp4_init_codebook(float* codebook);

#ifdef __cplusplus
}
#endif

#endif // NVFP4_H
