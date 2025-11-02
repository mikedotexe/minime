#ifndef NVFP4_FORMAT_H
#define NVFP4_FORMAT_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// NVFP4 Format Constants
// ============================================================================

#define NVFP4_TILE_SIZE 16
#define NVFP4_TILE_ELEMENTS (NVFP4_TILE_SIZE * NVFP4_TILE_SIZE)

// FP4 E2M1 representable magnitudes
static const float NVFP4_E2M1_MAGNITUDES[8] = {
    0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f
};

// E4M3 constants (max value 448)
#define NVFP4_E4M3_MAX_VALUE 448.0f
#define NVFP4_E4M3_EXP_BIAS 7
#define NVFP4_E4M3_MAX_EXP 8
#define NVFP4_E4M3_MIN_EXP -7

// ============================================================================
// Type Definitions
// ============================================================================

// GGUF/GGML type identifier for NVFP4
typedef enum {
    GGML_TYPE_Q4_NV2D = 32,  // Next available after existing types
} ggml_type_nvfp4_t;

// NVFP4 tensor header (stored at beginning of quantized data)
typedef struct __attribute__((packed)) {
    float global_scale;      // Global decode scale (s_dec)
    uint32_t rows;           // Original tensor rows
    uint32_t cols;           // Original tensor cols
    uint16_t tile_size;      // Tile dimension (16)
    uint16_t flags;          // Reserved flags
} nvfp4_tensor_header_t;

// Block structure for GGML compatibility
typedef struct {
    nvfp4_tensor_header_t header;
    // Variable length arrays follow:
    // uint8_t tile_scales[n_tiles];     // E4M3 scales
    // uint8_t fp4_data[n_elements/2];   // Packed FP4 nibbles
} nvfp4_block_t;

// Quantization parameters
typedef struct {
    bool use_stochastic_rounding;  // For gradients
    float importance_scale;        // For weighted quantization
    int keep_fp16_layers;          // Number of layers to keep in FP16
    uint64_t random_seed;          // For stochastic rounding
} nvfp4_quant_params_t;

// ============================================================================
// Core Functions
// ============================================================================

// Size calculations
size_t nvfp4_tensor_size(int rows, int cols);
size_t nvfp4_get_n_tiles(int rows, int cols);
void nvfp4_get_tile_coords(int element_idx, int cols, int* tile_r, int* tile_c, int* in_tile_idx);

// Quantization/Dequantization (main API for GGML integration)
void quantize_row_q4_nv2d(const float* x, void* y, int k);
void quantize_row_q4_nv2d_reference(const float* x, nvfp4_block_t* y, int k);
void dequantize_row_q4_nv2d(const void* x, float* y, int k);

// Dot product operations
float vec_dot_q4_nv2d_q8_0(const void* vx, const void* vy, int k);
float vec_dot_q4_nv2d_f32(const void* vx, const float* fy, int k);

// Matrix multiplication
void ggml_gemm_q4_nv2d_f32(const void* vx, const float* vy, float* dst,
                           int m, int n, int k);

// ============================================================================
// E4M3 Scale Functions
// ============================================================================

uint8_t nvfp4_f32_to_e4m3(float x);
float nvfp4_e4m3_to_f32(uint8_t e4m3);
void nvfp4_quantize_scales(const float* scales, uint8_t* e4m3_scales, int n);
void nvfp4_dequantize_scales(const uint8_t* e4m3_scales, float* scales, int n);

// ============================================================================
// FP4 E2M1 Functions
// ============================================================================

uint8_t nvfp4_quantize_fp4(float x);
float nvfp4_dequantize_fp4(uint8_t nibble);
void nvfp4_pack_fp4_values(const float* values, uint8_t* packed, int n);
void nvfp4_unpack_fp4_values(const uint8_t* packed, float* values, int n);

// ============================================================================
// Tile Operations
// ============================================================================

typedef struct {
    float values[NVFP4_TILE_ELEMENTS];
    float amax;
    float scale_enc;
    float scale_dec;
    uint8_t scale_e4m3;
} nvfp4_tile_t;

void nvfp4_extract_tile(const float* matrix, int rows, int cols,
                        int tile_r, int tile_c, nvfp4_tile_t* tile);
void nvfp4_quantize_tile(nvfp4_tile_t* tile, float global_scale_enc,
                        uint8_t* fp4_out, bool stochastic);
void nvfp4_dequantize_tile(const uint8_t* fp4_data, uint8_t scale_e4m3,
                          float global_scale_dec, float* tile_out);

// ============================================================================
// SIMD Optimizations (Apple Silicon NEON)
// ============================================================================

#ifdef __ARM_NEON
#include <arm_neon.h>

void nvfp4_dequantize_row_neon(const nvfp4_block_t* x, float* y, int k);
float nvfp4_vec_dot_neon(const void* vx, const float* vy, int k);
void nvfp4_gemm_neon(const void* vx, const float* vy, float* dst,
                     int m, int n, int k);
#endif

// ============================================================================
// Metal GPU Support (Apple Silicon)
// ============================================================================

#ifdef GGML_USE_METAL
typedef struct {
    void* pipeline_dequant;
    void* pipeline_gemm;
    void* pipeline_gemv;
} nvfp4_metal_context_t;

bool nvfp4_metal_init(nvfp4_metal_context_t* ctx);
void nvfp4_metal_free(nvfp4_metal_context_t* ctx);
void nvfp4_metal_dequantize(nvfp4_metal_context_t* ctx,
                           const void* src, float* dst, int k);
void nvfp4_metal_gemm(nvfp4_metal_context_t* ctx,
                     const void* a, const float* b, float* c,
                     int m, int n, int k);
#endif

// ============================================================================
// Debugging and Validation
// ============================================================================

void nvfp4_print_tensor_info(const nvfp4_block_t* tensor);
void nvfp4_validate_tensor(const nvfp4_block_t* tensor);
float nvfp4_compute_error(const float* original, const float* dequantized, int n);
void nvfp4_dump_tile(const nvfp4_block_t* tensor, int tile_idx);

// ============================================================================
// Model Conversion Support
// ============================================================================

typedef enum {
    NVFP4_LAYER_TYPE_ATTENTION_Q = 0,
    NVFP4_LAYER_TYPE_ATTENTION_K,
    NVFP4_LAYER_TYPE_ATTENTION_V,
    NVFP4_LAYER_TYPE_ATTENTION_O,
    NVFP4_LAYER_TYPE_FFN_GATE,
    NVFP4_LAYER_TYPE_FFN_UP,
    NVFP4_LAYER_TYPE_FFN_DOWN,
    NVFP4_LAYER_TYPE_OTHER
} nvfp4_layer_type_t;

typedef struct {
    const char* name;
    nvfp4_layer_type_t type;
    bool keep_fp16;  // Don't quantize this layer
    float importance_weight;
} nvfp4_layer_config_t;

bool nvfp4_should_quantize_layer(const char* layer_name,
                                const nvfp4_layer_config_t* config,
                                int n_configs);

#ifdef __cplusplus
}
#endif

#endif // NVFP4_FORMAT_H