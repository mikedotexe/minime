#!/usr/bin/env python3
import sys
import json
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.convert_model import NVFP4Quantizer, ModelConverter
import torch
from safetensors import safe_open
import numpy as np

def convert_for_target(profile_path, output_name):
    """Convert TinyLlama with target-specific optimizations."""

    # Load profile
    with open(profile_path) as f:
        profile = json.load(f)

    print(f"\n=== Converting with profile: {profile['name']} ===")
    print(f"Description: {profile['description']}")

    # Create quantizer with profile settings
    quant_config = profile['quantization']
    quantizer = NVFP4Quantizer(
        tile_size=quant_config['tile_size'],
        stochastic=False  # Deterministic for reproducibility
    )

    # Create converter
    converter = ModelConverter(
        quantizer,
        keep_fp16_percent=quant_config['keep_fp16_percent']
    )

    # Override layer selection for aggressive mode
    if quant_config.get('aggressive_mode', False):
        print("Using aggressive quantization for maximum compression")
        converter.KEEP_FP16_PATTERNS = quant_config['keep_fp16_layers']

    # Load model
    model_path = Path("./tinyllama_hf/model.safetensors")

    print(f"\nLoading model from {model_path}")
    tensors = {}
    metadata = {
        "format": "nvfp4",
        "version": "1.0",
        "profile": profile['name'],
        "tile_size": str(quant_config['tile_size'])
    }

    with safe_open(model_path, framework="np") as f:
        # Calculate statistics
        total_params = 0
        quantized_params = 0
        layer_stats = {}

        for name in f.keys():
            tensor = f.get_tensor(name)
            shape = tensor.shape
            params = np.prod(shape)
            total_params += params

            # Decide quantization
            should_quantize = (
                len(shape) == 2 and
                name not in quant_config['keep_fp16_layers'] and
                converter.should_quantize(name)
            )

            if should_quantize:
                print(f"  Quantizing {name}: {shape}")
                quantized = quantizer.quantize_tensor(tensor, name)
                tensors[name] = quantized
                quantized_params += params
                layer_stats[name] = "nvfp4"
            else:
                tensors[name] = tensor
                layer_stats[name] = "fp16"

        # Print statistics
        print(f"\n=== Quantization Statistics ===")
        print(f"Total parameters: {total_params/1e6:.1f}M")
        print(f"Quantized parameters: {quantized_params/1e6:.1f}M ({quantized_params/total_params*100:.1f}%)")
        print(f"Kept in FP16: {(total_params-quantized_params)/1e6:.1f}M ({(total_params-quantized_params)/total_params*100:.1f}%)")

        # Estimate sizes
        fp16_size_mb = (total_params * 2) / (1024 * 1024)
        nvfp4_params_size = (quantized_params * 4.25 / 8) / (1024 * 1024)
        fp16_params_size = ((total_params - quantized_params) * 2) / (1024 * 1024)
        total_size_mb = nvfp4_params_size + fp16_params_size

        print(f"\n=== Size Estimates ===")
        print(f"Original (FP16): {fp16_size_mb:.1f} MB")
        print(f"Quantized (NVFP4): {total_size_mb:.1f} MB")
        print(f"Compression ratio: {fp16_size_mb/total_size_mb:.2f}x")
        print(f"Savings: {fp16_size_mb - total_size_mb:.1f} MB ({(fp16_size_mb - total_size_mb)/fp16_size_mb*100:.1f}%)")

    # Save quantized model
    output_path = Path(output_name)
    converter._save_gguf(output_path, tensors, metadata)

    # Save layer statistics
    stats_path = output_path.with_suffix('.stats.json')
    with open(stats_path, 'w') as f:
        json.dump({
            'layer_types': layer_stats,
            'total_params': total_params,
            'quantized_params': quantized_params,
            'size_mb': total_size_mb,
            'profile': profile
        }, f, indent=2)

    print(f"\nSaved statistics to {stats_path}")
    return output_path

if __name__ == "__main__":
    # Convert for M4 Max
    m4_model = convert_for_target(
        "quant_profile_m4max.json",
        "tinyllama-nvfp4-m4max.gguf"
    )

    # Convert for Raspberry Pi
    rpi_model = convert_for_target(
        "quant_profile_rpi.json",
        "tinyllama-nvfp4-rpi.gguf"
    )

    print("\n=== Conversion Complete ===")
    print(f"M4 Max model: {m4_model}")
    print(f"Raspberry Pi model: {rpi_model}")
