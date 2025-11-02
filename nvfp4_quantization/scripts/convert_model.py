#!/usr/bin/env python3
"""
NVFP4 Model Conversion Tool

Converts HuggingFace or GGUF models to NVFP4 quantized format.
"""

import argparse
import json
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from tqdm import tqdm

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("Warning: PyTorch not available, some features disabled")

try:
    from safetensors import safe_open
    SAFETENSORS_AVAILABLE = True
except ImportError:
    SAFETENSORS_AVAILABLE = False
    print("Warning: safetensors not available")

# ============================================================================
# NVFP4 Format Implementation
# ============================================================================

# FP4 E2M1 magnitude table
FP4_MAGNITUDES = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0], dtype=np.float32)

def f32_to_e4m3_448(x: float) -> int:
    """Convert float32 to E4M3 format with max value 448."""
    if x == 0.0 or not np.isfinite(x):
        return 0

    sign = 0x80 if x < 0 else 0x00
    ax = abs(x)
    ax = min(ax, 448.0)

    exp = int(np.floor(np.log2(ax)))
    sig = ax / (2.0 ** exp)

    if sig < 1.0:
        exp -= 1
        sig *= 2.0

    exp = max(-7, min(8, exp))
    max_sig = 1.75 if exp == 8 else 1.875
    sig = min(max(sig, 1.0), max_sig)

    mant = int(round((sig - 1.0) * 8.0))
    mant = min(mant, 6 if exp == 8 else 7)

    exp_biased = exp + 7
    return sign | (exp_biased << 3) | mant

def e4m3_448_to_f32(b: int) -> float:
    """Convert E4M3 byte to float32."""
    if b == 0:
        return 0.0

    sign = -1.0 if (b & 0x80) else 1.0
    exp_biased = (b >> 3) & 0x0F
    mant = b & 0x07

    exp = exp_biased - 7
    sig = 1.0 + mant / 8.0

    return sign * sig * (2.0 ** exp)

def quantize_fp4(x: float) -> int:
    """Quantize float to FP4 E2M1 (returns nibble)."""
    sign = 0x08 if x < 0 else 0x00
    ax = abs(x)

    # Find nearest magnitude
    errors = np.abs(FP4_MAGNITUDES - ax)
    best_idx = np.argmin(errors)

    return sign | best_idx

def dequantize_fp4(nibble: int) -> float:
    """Dequantize FP4 nibble to float."""
    sign = -1.0 if (nibble & 0x08) else 1.0
    idx = nibble & 0x07
    return sign * FP4_MAGNITUDES[idx]

@dataclass
class NVFP4TensorHeader:
    """NVFP4 tensor header structure."""
    global_scale: float
    rows: int
    cols: int
    tile_size: int = 16
    flags: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack('<fIIHH', self.global_scale, self.rows,
                          self.cols, self.tile_size, self.flags)

class NVFP4Quantizer:
    """NVFP4 quantization implementation."""

    def __init__(self, tile_size: int = 16, stochastic: bool = False):
        self.tile_size = tile_size
        self.stochastic = stochastic
        self.rng = np.random.RandomState(1234) if stochastic else None

    def quantize_tensor(self, tensor: np.ndarray, name: str = "") -> bytes:
        """Quantize a 2D tensor to NVFP4 format."""
        if len(tensor.shape) != 2:
            raise ValueError(f"Expected 2D tensor, got shape {tensor.shape}")

        rows, cols = tensor.shape

        # Compute global scale
        amax = np.abs(tensor).max()
        s_enc = (6.0 * 448.0) / amax if amax > 0 else 1.0
        s_dec = 1.0 / s_enc

        # Create header
        header = NVFP4TensorHeader(
            global_scale=s_dec,
            rows=rows,
            cols=cols,
            tile_size=self.tile_size
        )

        # Calculate tile layout
        tiles_r = (rows + self.tile_size - 1) // self.tile_size
        tiles_c = (cols + self.tile_size - 1) // self.tile_size
        n_tiles = tiles_r * tiles_c

        # Allocate buffers
        tile_scales = np.zeros(n_tiles, dtype=np.uint8)
        fp4_data = np.zeros((rows * cols + 1) // 2, dtype=np.uint8)

        # Process each tile
        tile_idx = 0
        for tr in range(tiles_r):
            for tc in range(tiles_c):
                r0 = tr * self.tile_size
                c0 = tc * self.tile_size
                r1 = min(r0 + self.tile_size, rows)
                c1 = min(c0 + self.tile_size, cols)

                # Extract tile and find max
                tile = tensor[r0:r1, c0:c1]
                tile_amax = np.abs(tile).max()

                # Compute tile scale
                s_dec_tile = tile_amax / 6.0 if tile_amax > 0 else 0.0
                tile_scales[tile_idx] = f32_to_e4m3_448(s_dec_tile * s_enc)

                # Quantize tile values
                s_enc_tile = 1.0 / s_dec_tile if s_dec_tile > 0 else 0.0

                for i in range(r0, r1):
                    for j in range(c0, c1):
                        val = tensor[i, j]
                        scaled = val * s_enc_tile

                        if self.stochastic:
                            # Stochastic rounding
                            nibble = self._stochastic_round_fp4(scaled)
                        else:
                            nibble = quantize_fp4(scaled)

                        # Pack nibbles
                        idx = i * cols + j
                        byte_idx = idx // 2
                        if idx & 1:
                            fp4_data[byte_idx] |= (nibble << 4)
                        else:
                            fp4_data[byte_idx] = nibble

                tile_idx += 1

        # Combine into final buffer
        result = bytearray()
        result.extend(header.to_bytes())
        result.extend(tile_scales.tobytes())
        result.extend(fp4_data.tobytes())

        return bytes(result)

    def _stochastic_round_fp4(self, x: float) -> int:
        """Stochastic rounding for FP4."""
        sign = 0x08 if x < 0 else 0x00
        ax = abs(x)

        # Find two nearest magnitudes
        errors = ax - FP4_MAGNITUDES
        pos_errors = np.where(errors >= 0, errors, np.inf)
        neg_errors = np.where(errors < 0, -errors, np.inf)

        lo_idx = np.argmin(neg_errors) if np.any(errors < 0) else 0
        hi_idx = np.argmin(pos_errors) if np.any(errors >= 0) else 7

        if lo_idx == hi_idx:
            return sign | lo_idx

        # Compute probability
        lo_val = FP4_MAGNITUDES[lo_idx]
        hi_val = FP4_MAGNITUDES[hi_idx]
        p_hi = (ax - lo_val) / (hi_val - lo_val)

        # Random selection
        chosen_idx = hi_idx if self.rng.random() < p_hi else lo_idx
        return sign | chosen_idx

    def dequantize_tensor(self, data: bytes) -> Tuple[np.ndarray, str]:
        """Dequantize NVFP4 data back to float32."""
        offset = 0

        # Parse header
        header_fmt = '<fIIHH'
        header_size = struct.calcsize(header_fmt)
        global_scale, rows, cols, tile_size, flags = struct.unpack_from(header_fmt, data, offset)
        offset += header_size

        # Calculate sizes
        tiles_r = (rows + tile_size - 1) // tile_size
        tiles_c = (cols + tile_size - 1) // tile_size
        n_tiles = tiles_r * tiles_c

        # Extract scale and data arrays
        tile_scales = np.frombuffer(data, dtype=np.uint8, count=n_tiles, offset=offset)
        offset += n_tiles

        fp4_data = np.frombuffer(data, dtype=np.uint8, offset=offset)

        # Reconstruct tensor
        result = np.zeros((rows, cols), dtype=np.float32)

        for tr in range(tiles_r):
            for tc in range(tiles_c):
                tile_idx = tr * tiles_c + tc
                tile_scale = e4m3_448_to_f32(tile_scales[tile_idx]) * global_scale

                r0 = tr * tile_size
                c0 = tc * tile_size
                r1 = min(r0 + tile_size, rows)
                c1 = min(c0 + tile_size, cols)

                for i in range(r0, r1):
                    for j in range(c0, c1):
                        idx = i * cols + j
                        byte_idx = idx // 2

                        nibble = fp4_data[byte_idx]
                        if idx & 1:
                            nibble = (nibble >> 4) & 0x0F
                        else:
                            nibble = nibble & 0x0F

                        value = dequantize_fp4(nibble)
                        result[i, j] = value * tile_scale

        return result, f"NVFP4 {rows}x{cols}"

# ============================================================================
# Model Conversion
# ============================================================================

class ModelConverter:
    """Convert models to NVFP4 format."""

    # Layers to keep in FP16 (critical for quality)
    KEEP_FP16_PATTERNS = [
        "embed_tokens",
        "lm_head",
        "norm",
        "layernorm",
        "ln_",
        "output.weight",
        "head.weight"
    ]

    # Patterns to quantize
    QUANTIZE_PATTERNS = [
        "self_attn.q_proj",
        "self_attn.k_proj",
        "self_attn.v_proj",
        "self_attn.o_proj",
        "block_sparse_moe.gate",
        "block_sparse_moe.experts",
        "mlp.gate_proj",
        "mlp.up_proj",
        "mlp.down_proj",
        "feed_forward.w1",
        "feed_forward.w2",
        "feed_forward.w3"
    ]

    def __init__(self, quantizer: NVFP4Quantizer, keep_fp16_percent: float = 0.15):
        self.quantizer = quantizer
        self.keep_fp16_percent = keep_fp16_percent

    def should_quantize(self, name: str) -> bool:
        """Check if a tensor should be quantized."""
        # Keep critical layers in FP16
        for pattern in self.KEEP_FP16_PATTERNS:
            if pattern in name.lower():
                return False

        # Check if it matches quantization patterns
        for pattern in self.QUANTIZE_PATTERNS:
            if pattern in name.lower():
                return True

        return False  # Default to not quantizing

    def convert_safetensors(self, input_path: Path, output_path: Path):
        """Convert a safetensors model to NVFP4 format."""
        if not SAFETENSORS_AVAILABLE:
            raise ImportError("safetensors package required for conversion")

        print(f"Loading model from {input_path}")

        metadata = {"format": "nvfp4", "version": "1.0"}
        tensors = {}

        with safe_open(input_path, framework="np") as f:
            total_params = 0
            quantized_params = 0

            for name in tqdm(f.keys(), desc="Converting tensors"):
                tensor = f.get_tensor(name)

                if len(tensor.shape) == 2 and self.should_quantize(name):
                    # Quantize 2D weight tensors
                    print(f"  Quantizing {name}: {tensor.shape}")
                    quantized = self.quantizer.quantize_tensor(tensor, name)
                    tensors[name] = quantized
                    quantized_params += tensor.shape[0] * tensor.shape[1]
                else:
                    # Keep as-is
                    tensors[name] = tensor

                total_params += tensor.size

        print(f"\nQuantized {quantized_params/total_params*100:.1f}% of parameters")

        # Save in GGUF-compatible format
        self._save_gguf(output_path, tensors, metadata)

    def _save_gguf(self, path: Path, tensors: Dict[str, Union[bytes, np.ndarray]],
                   metadata: Dict[str, str]):
        """Save tensors in GGUF format with NVFP4 support."""
        # This is a simplified version - real GGUF has more complex structure
        with open(path, 'wb') as f:
            # GGUF magic
            f.write(b'GGUF')
            f.write(struct.pack('<I', 3))  # Version

            # Write metadata
            f.write(struct.pack('<Q', len(metadata)))
            for key, value in metadata.items():
                key_bytes = key.encode('utf-8')
                f.write(struct.pack('<Q', len(key_bytes)))
                f.write(key_bytes)

                value_bytes = value.encode('utf-8')
                f.write(struct.pack('<Q', len(value_bytes)))
                f.write(value_bytes)

            # Write tensor count
            f.write(struct.pack('<Q', len(tensors)))

            # Write tensor info
            tensor_data_offset = f.tell() + sum(
                8 + len(name.encode('utf-8')) + 32
                for name in tensors.keys()
            )

            data_blobs = []
            for name, data in tensors.items():
                name_bytes = name.encode('utf-8')
                f.write(struct.pack('<Q', len(name_bytes)))
                f.write(name_bytes)

                if isinstance(data, bytes):
                    # NVFP4 quantized tensor
                    f.write(struct.pack('<I', 32))  # GGML_TYPE_Q4_NV2D
                    f.write(struct.pack('<Q', len(data)))
                    f.write(struct.pack('<Q', tensor_data_offset))
                    tensor_data_offset += len(data)
                    data_blobs.append(data)
                else:
                    # Regular tensor
                    dtype_map = {
                        np.float32: 0,
                        np.float16: 1,
                        np.int32: 4,
                        np.int64: 5
                    }
                    f.write(struct.pack('<I', dtype_map.get(data.dtype.type, 0)))
                    f.write(struct.pack('<Q', data.nbytes))
                    f.write(struct.pack('<Q', tensor_data_offset))
                    tensor_data_offset += data.nbytes
                    data_blobs.append(data.tobytes())

            # Write tensor data
            for blob in data_blobs:
                f.write(blob)

        print(f"Saved NVFP4 model to {path}")

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Convert models to NVFP4 format")
    parser.add_argument("--input", type=Path, required=True,
                        help="Input model path (safetensors or GGUF)")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output NVFP4 model path")
    parser.add_argument("--tile-size", type=int, default=16,
                        help="Tile size for 2D quantization (default: 16)")
    parser.add_argument("--stochastic", action="store_true",
                        help="Use stochastic rounding")
    parser.add_argument("--keep-fp16-percent", type=float, default=0.15,
                        help="Percentage of layers to keep in FP16 (default: 15%)")
    parser.add_argument("--test", action="store_true",
                        help="Run quantization test on random data")

    args = parser.parse_args()

    if args.test:
        # Test quantization round-trip
        print("Running NVFP4 quantization test...")
        quantizer = NVFP4Quantizer(tile_size=args.tile_size, stochastic=args.stochastic)

        # Create test tensor
        np.random.seed(42)
        test_tensor = np.random.randn(64, 128).astype(np.float32) * 2.0

        # Quantize and dequantize
        print(f"Original tensor: {test_tensor.shape}, range: [{test_tensor.min():.3f}, {test_tensor.max():.3f}]")

        start = time.time()
        quantized = quantizer.quantize_tensor(test_tensor, "test")
        quant_time = time.time() - start

        start = time.time()
        dequantized, info = quantizer.dequantize_tensor(quantized)
        dequant_time = time.time() - start

        # Compute error
        mse = np.mean((test_tensor - dequantized) ** 2)
        rmse = np.sqrt(mse)
        rel_error = rmse / np.std(test_tensor)

        print(f"\nResults:")
        print(f"  Quantized size: {len(quantized)} bytes ({len(quantized)/test_tensor.nbytes:.1%} of original)")
        print(f"  Quantization time: {quant_time*1000:.2f} ms")
        print(f"  Dequantization time: {dequant_time*1000:.2f} ms")
        print(f"  RMSE: {rmse:.6f}")
        print(f"  Relative error: {rel_error:.3%}")

        # Show sample values
        print(f"\nSample values (first 5):")
        for i in range(min(5, test_tensor.size)):
            orig = test_tensor.flat[i]
            deq = dequantized.flat[i]
            print(f"  [{i}] Original: {orig:8.4f}, Dequantized: {deq:8.4f}, Error: {orig-deq:8.4f}")

        return

    # Normal model conversion
    quantizer = NVFP4Quantizer(tile_size=args.tile_size, stochastic=args.stochastic)
    converter = ModelConverter(quantizer, keep_fp16_percent=args.keep_fp16_percent)

    if args.input.suffix == ".safetensors":
        converter.convert_safetensors(args.input, args.output)
    else:
        print(f"Unsupported input format: {args.input.suffix}")
        sys.exit(1)

if __name__ == "__main__":
    main()