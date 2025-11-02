# NVFP4 Architecture and Format Specification

## Overview

NVFP4 (NVIDIA FP4) is a 4-bit floating-point quantization format designed to maintain quality while reducing memory footprint. This document describes the format and its implementation for Ollama.

## Format Specification

### FP4 E2M1 Format

The FP4 format uses 4 bits per value:
- **1 bit**: Sign (S)
- **2 bits**: Exponent (E)
- **1 bit**: Mantissa (M)

This gives us 8 representable magnitude values:

| Binary | Sign | Exp | Mant | Value |
|--------|------|-----|------|-------|
| 0000   | 0    | 00  | 0    | 0.0   |
| 0001   | 0    | 00  | 1    | 0.5   |
| 0010   | 0    | 01  | 0    | 1.0   |
| 0011   | 0    | 01  | 1    | 1.5   |
| 0100   | 0    | 10  | 0    | 2.0   |
| 0101   | 0    | 10  | 1    | 3.0   |
| 0110   | 0    | 11  | 0    | 4.0   |
| 0111   | 0    | 11  | 1    | 6.0   |

With the sign bit, we have 15 unique values (-6.0 to +6.0) plus zero.

### 2D Tiling Structure

Unlike traditional 1D block quantization, NVFP4 uses 2D tiles:

```
Traditional 1D blocks (e.g., Q4_K_M):
[block_0: 32 values][block_1: 32 values][block_2: 32 values]...

NVFP4 2D tiles (16×16):
┌─────────┬─────────┬─────────┐
│ Tile    │ Tile    │ Tile    │
│ (0,0)   │ (0,1)   │ (0,2)   │
├─────────┼─────────┼─────────┤
│ Tile    │ Tile    │ Tile    │
│ (1,0)   │ (1,1)   │ (1,2)   │
└─────────┴─────────┴─────────┘
```

Each 16×16 tile contains:
- 256 FP4 values (128 bytes when packed)
- 1 E4M3 scale value (1 byte)

### E4M3 Block Scales

Each tile has an 8-bit E4M3 scale with max value 448:
- **1 bit**: Sign (S)
- **4 bits**: Exponent (E) with bias 7
- **3 bits**: Mantissa (M)

This provides better dynamic range than power-of-2 scales:
- Exponent range: -7 to 8
- Effective range: ~0.001 to 448

### Memory Layout

For a weight matrix W of shape [M, N]:

```c
struct NVFP4_Tensor {
    float global_scale;           // 4 bytes
    uint32_t rows;                // 4 bytes
    uint32_t cols;                // 4 bytes
    uint16_t tile_size;           // 2 bytes (always 16)
    uint16_t reserved;            // 2 bytes (alignment)

    // Variable length data follows:
    uint8_t tile_scales[];        // (M/16) * (N/16) bytes
    uint8_t fp4_data[];           // (M * N) / 2 bytes
};
```

## Quantization Process

### Forward Quantization

1. **Compute global scale**:
   ```
   s_enc = (6.0 * 448.0) / max(abs(W))
   s_dec = 1.0 / s_enc
   ```

2. **For each 16×16 tile**:
   - Find tile maximum: `amax_tile = max(abs(W_tile))`
   - Compute tile scale: `s_dec_tile = amax_tile / 6.0`
   - Quantize to E4M3: `scale_e4m3 = quantize_e4m3(s_dec_tile * s_enc)`
   - Store scale in `tile_scales[]`

3. **Quantize values**:
   - Scale: `w_scaled = w * s_enc_tile`
   - Quantize to FP4: `w_fp4 = quantize_fp4(w_scaled)`
   - Pack two FP4 values per byte

### Dequantization

To reconstruct weight `w` at position `(i, j)`:

1. **Determine tile**:
   ```
   tile_r = i / 16
   tile_c = j / 16
   tile_idx = tile_r * tiles_per_row + tile_c
   ```

2. **Get scales**:
   ```
   tile_scale = decode_e4m3(tile_scales[tile_idx])
   total_scale = tile_scale * global_scale
   ```

3. **Decode FP4**:
   ```
   byte_idx = (i * cols + j) / 2
   nibble = (byte_idx & 1) ? (data[byte_idx] >> 4) : (data[byte_idx] & 0x0F)
   fp4_value = decode_fp4(nibble)
   ```

4. **Reconstruct**:
   ```
   w = fp4_value * total_scale
   ```

## Comparison with Existing Formats

| Format | Bits | Block Size | Scale Type | Dynamic Range |
|--------|------|-----------|------------|---------------|
| Q4_0   | 4    | 32 (1D)   | FP16       | Power-of-2    |
| Q4_K_M | 4    | 256 (1D)  | FP16       | Power-of-2    |
| Q4_1   | 4.5  | 32 (1D)   | FP16+FP16  | Affine        |
| NVFP4  | 4.25 | 256 (2D)  | E4M3+FP32  | 0.001-448     |

## Advantages

1. **2D Locality**: Better preserves spatial structure in weight matrices
2. **E4M3 Scales**: ~3x better dynamic range than FP16
3. **Consistent Forward/Backward**: 2D tiling reduces gradient mismatch
4. **Hardware Friendly**: 16×16 tiles align with GPU threadblock sizes

## Implementation Considerations

### CPU Optimization

- Use NEON on Apple Silicon for FP4 unpacking
- Process tiles in Z-order for cache locality
- Vectorize E4M3 scale application

### GPU Optimization (Metal)

```metal
kernel void nvfp4_dequant_matmul(
    constant uint8_t* scales [[buffer(0)]],
    constant uint8_t* data [[buffer(1)]],
    constant float& global_scale [[buffer(2)]],
    constant float* input [[buffer(3)]],
    device float* output [[buffer(4)]],
    uint2 gid [[thread_position_in_grid]],
    uint2 tid [[thread_position_in_threadgroup]]
) {
    // Each threadgroup handles one 16x16 tile
    // Shared memory for tile data
    threadgroup float tile_cache[256];

    // ... dequantization and matmul
}
```

### Memory Bandwidth

For Mixtral 8x7B:
- Original FP16: ~93GB
- Q4_K_M: ~26GB
- NVFP4: ~26.5GB (2% overhead from 2D metadata)

The slight overhead is offset by better quality preservation.