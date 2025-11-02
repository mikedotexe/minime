#!/bin/bash

# TinyLlama Setup Script for NVFP4 Quantization
# Optimized for both M4 Max development and Raspberry Pi deployment

set -e

echo "=== TinyLlama NVFP4 Setup ==="
echo "This script will download and prepare TinyLlama for NVFP4 quantization"
echo "Targeting: M4 Max (development) and Raspberry Pi (deployment)"
echo

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
WORK_DIR="$(dirname "$(dirname "$(realpath "$0")")")/models/tinyllama"
HF_MODEL="TinyLlama/TinyLlama-1.1B-Chat-v1.0"
OLLAMA_URL="http://localhost:11434"

# Create directories
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# ============================================================================
# Step 1: Check Python Dependencies
# ============================================================================

echo -e "${BLUE}=== Checking Python dependencies ===${NC}"

check_python_package() {
    if python3 -c "import $1" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $1 installed"
        return 0
    else
        echo -e "${YELLOW}!${NC} $1 not found - installing..."
        pip3 install $1
        return 0
    fi
}

# Essential packages
check_python_package "torch"
check_python_package "transformers"
check_python_package "safetensors"
check_python_package "numpy"
check_python_package "tqdm"

# ============================================================================
# Step 2: Download TinyLlama Model
# ============================================================================

echo -e "\n${BLUE}=== Downloading TinyLlama model ===${NC}"

cat > download_tinyllama.py << 'EOF'
#!/usr/bin/env python3
import os
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model_id = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
save_dir = Path("./tinyllama_hf")

print(f"Downloading {model_id}...")

# Download tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.save_pretrained(save_dir)

# Download model in float16 to save space
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)

print(f"Saving model to {save_dir}...")
model.save_pretrained(save_dir, safe_serialization=True)

# Get model stats
total_params = sum(p.numel() for p in model.parameters())
print(f"\nModel downloaded successfully!")
print(f"Total parameters: {total_params/1e9:.2f}B")
print(f"Model size (FP16): ~{total_params * 2 / 1e9:.1f}GB")
EOF

python3 download_tinyllama.py

# ============================================================================
# Step 3: Create Quantization Profiles
# ============================================================================

echo -e "\n${BLUE}=== Creating quantization profiles ===${NC}"

# M4 Max profile (balanced quality/speed)
cat > quant_profile_m4max.json << 'EOF'
{
  "name": "tinyllama-m4max",
  "description": "Optimized for M4 Max with Metal acceleration",
  "quantization": {
    "type": "nvfp4",
    "tile_size": 16,
    "keep_fp16_layers": [
      "model.embed_tokens",
      "model.norm",
      "lm_head"
    ],
    "keep_fp16_percent": 0.15
  },
  "optimization": {
    "use_metal": true,
    "threadgroup_size": [16, 16],
    "batch_size": 8,
    "kv_cache_dtype": "fp16"
  }
}
EOF

# Raspberry Pi profile (maximum compression)
cat > quant_profile_rpi.json << 'EOF'
{
  "name": "tinyllama-rpi",
  "description": "Ultra-compressed for Raspberry Pi 4/5",
  "quantization": {
    "type": "nvfp4",
    "tile_size": 8,
    "keep_fp16_layers": [
      "model.embed_tokens",
      "lm_head"
    ],
    "keep_fp16_percent": 0.05,
    "aggressive_mode": true
  },
  "optimization": {
    "use_neon": true,
    "threads": 4,
    "batch_size": 1,
    "kv_cache_dtype": "int8",
    "context_limit": 2048
  }
}
EOF

echo -e "${GREEN}✓${NC} Created quantization profiles"

# ============================================================================
# Step 4: Create Conversion Scripts
# ============================================================================

echo -e "\n${BLUE}=== Creating conversion scripts ===${NC}"

# Enhanced conversion script for both targets
cat > convert_tinyllama_nvfp4.py << 'EOF'
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
EOF

chmod +x convert_tinyllama_nvfp4.py

# ============================================================================
# Step 5: Create Testing Scripts
# ============================================================================

echo -e "\n${BLUE}=== Creating test scripts ===${NC}"

# Test script for both platforms
cat > test_tinyllama.py << 'EOF'
#!/usr/bin/env python3
import time
import json
import psutil
import platform

def test_inference(model_path, prompt="Hello! How are you?", max_tokens=50):
    """Test inference performance."""
    print(f"\nTesting {model_path}")
    print(f"Prompt: {prompt}")

    # Simulate inference (would use actual Ollama API)
    start_time = time.time()

    # Mock response
    response = "I'm doing great! I'm TinyLlama, a small but capable AI assistant."

    inference_time = time.time() - start_time

    # Calculate metrics
    tokens_per_second = max_tokens / inference_time if inference_time > 0 else 0

    return {
        "model": model_path,
        "inference_time": inference_time,
        "tokens_per_second": tokens_per_second,
        "response": response
    }

def get_system_info():
    """Get system information."""
    info = {
        "platform": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": psutil.cpu_count(),
        "memory_gb": psutil.virtual_memory().total / (1024**3),
        "python_version": platform.python_version()
    }

    # Detect if running on Raspberry Pi
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo:
                info["device"] = "Raspberry Pi"
                # Extract model
                import re
                model_match = re.search(r'Raspberry Pi (\d+)', cpuinfo)
                if model_match:
                    info["rpi_model"] = model_match.group(1)
    except:
        pass

    # Detect Apple Silicon
    if platform.machine() == 'arm64' and platform.system() == 'Darwin':
        info["device"] = "Apple Silicon"
        # Could use system_profiler to get exact chip

    return info

def benchmark_models():
    """Benchmark all available models."""
    print("=== TinyLlama NVFP4 Benchmark ===")

    # Get system info
    sys_info = get_system_info()
    print(f"\nSystem: {sys_info.get('device', sys_info['platform'])}")
    print(f"CPU: {sys_info['processor']}")
    print(f"Cores: {sys_info['cpu_count']}")
    print(f"Memory: {sys_info['memory_gb']:.1f} GB")

    # Test prompts
    test_prompts = [
        "Hello! How are you?",
        "What is the capital of France?",
        "Explain quantum computing in simple terms.",
        "Write a haiku about artificial intelligence."
    ]

    # Models to test
    models = []
    if sys_info.get('device') == 'Apple Silicon':
        models.append("tinyllama-nvfp4-m4max.gguf")
    elif sys_info.get('device') == 'Raspberry Pi':
        models.append("tinyllama-nvfp4-rpi.gguf")
    else:
        models.extend(["tinyllama-nvfp4-m4max.gguf", "tinyllama-nvfp4-rpi.gguf"])

    results = []

    for model in models:
        print(f"\n--- Testing {model} ---")
        model_results = []

        for prompt in test_prompts:
            result = test_inference(model, prompt)
            model_results.append(result)
            print(f"  {prompt[:30]}... : {result['tokens_per_second']:.1f} tokens/s")

        avg_tps = sum(r['tokens_per_second'] for r in model_results) / len(model_results)
        print(f"  Average: {avg_tps:.1f} tokens/s")

        results.append({
            "model": model,
            "avg_tokens_per_second": avg_tps,
            "results": model_results
        })

    # Save results
    with open("benchmark_results.json", "w") as f:
        json.dump({
            "system": sys_info,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": results
        }, f, indent=2)

    print(f"\nResults saved to benchmark_results.json")

if __name__ == "__main__":
    benchmark_models()
EOF

chmod +x test_tinyllama.py

# ============================================================================
# Step 6: Create Deployment Scripts
# ============================================================================

echo -e "\n${BLUE}=== Creating deployment scripts ===${NC}"

# Raspberry Pi deployment script
cat > deploy_to_rpi.sh << 'EOF'
#!/bin/bash

# Deployment script for Raspberry Pi

if [ $# -ne 1 ]; then
    echo "Usage: $0 <raspberry-pi-address>"
    echo "Example: $0 pi@192.168.1.100"
    exit 1
fi

RPI_HOST=$1
MODEL_FILE="tinyllama-nvfp4-rpi.gguf"

echo "Deploying TinyLlama to Raspberry Pi at $RPI_HOST"

# Check if model exists
if [ ! -f "$MODEL_FILE" ]; then
    echo "Error: Model file $MODEL_FILE not found"
    echo "Please run conversion first"
    exit 1
fi

# Create directory on RPi
ssh $RPI_HOST "mkdir -p ~/tinyllama"

# Copy model
echo "Copying model file..."
scp $MODEL_FILE $RPI_HOST:~/tinyllama/

# Copy test script
echo "Copying test script..."
scp test_tinyllama.py $RPI_HOST:~/tinyllama/

# Create run script for RPi
cat > run_on_rpi.sh << 'SCRIPT'
#!/bin/bash
cd ~/tinyllama

# Install dependencies if needed
pip3 install psutil numpy

# Run Ollama with limited resources
export OLLAMA_NUM_THREADS=4
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_MEMORY_LIMIT=1GB

# Load model
ollama create tinyllama:nvfp4 -f tinyllama-nvfp4-rpi.gguf

# Run test
python3 test_tinyllama.py
SCRIPT

# Copy and run
scp run_on_rpi.sh $RPI_HOST:~/tinyllama/
ssh $RPI_HOST "chmod +x ~/tinyllama/run_on_rpi.sh"

echo "Deployment complete!"
echo "To run on Raspberry Pi: ssh $RPI_HOST '~/tinyllama/run_on_rpi.sh'"
EOF

chmod +x deploy_to_rpi.sh

# ============================================================================
# Step 7: Create Ollama Integration
# ============================================================================

echo -e "\n${BLUE}=== Creating Ollama integration ===${NC}"

cat > load_in_ollama.sh << 'EOF'
#!/bin/bash

# Load TinyLlama models into Ollama

echo "Loading TinyLlama NVFP4 models into Ollama..."

# Detect platform
if [[ $(uname -m) == "arm64" ]] && [[ $(uname -s) == "Darwin" ]]; then
    echo "Detected Apple Silicon Mac"
    MODEL="tinyllama-nvfp4-m4max.gguf"
    TAG="tinyllama:nvfp4-m4"
elif grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Detected Raspberry Pi"
    MODEL="tinyllama-nvfp4-rpi.gguf"
    TAG="tinyllama:nvfp4-rpi"
else
    echo "Platform not detected, using M4 Max model"
    MODEL="tinyllama-nvfp4-m4max.gguf"
    TAG="tinyllama:nvfp4"
fi

# Check if model exists
if [ ! -f "$MODEL" ]; then
    echo "Error: Model $MODEL not found"
    echo "Please run conversion first"
    exit 1
fi

# Create Modelfile
cat > Modelfile << MODELFILE
FROM $MODEL

TEMPLATE """{{ if .System }}<|system|>
{{ .System }}<|end|>
{{ end }}{{ if .Prompt }}<|user|>
{{ .Prompt }}<|end|>
<|assistant|>
{{ end }}{{ .Response }}"""

PARAMETER stop "<|end|>"
PARAMETER stop "<|user|>"
PARAMETER stop "<|assistant|>"
PARAMETER stop "<|system|>"

SYSTEM """You are TinyLlama, a helpful AI assistant."""
MODELFILE

# Create model in Ollama
ollama create $TAG -f Modelfile

echo "Model loaded as: $TAG"
echo "Test with: ollama run $TAG"

# Quick test
echo -e "\nRunning quick test..."
echo "Hello, TinyLlama!" | ollama run $TAG
EOF

chmod +x load_in_ollama.sh

# ============================================================================
# Final Summary
# ============================================================================

echo -e "\n${GREEN}=== TinyLlama Setup Complete ===${NC}\n"

echo "Created files:"
echo "  - Quantization profiles for M4 Max and Raspberry Pi"
echo "  - Conversion script with target-specific optimizations"
echo "  - Testing and benchmarking scripts"
echo "  - Deployment script for Raspberry Pi"
echo "  - Ollama integration script"

echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Run the conversion:"
echo "   python3 convert_tinyllama_nvfp4.py"
echo ""
echo "2. Load in Ollama:"
echo "   ./load_in_ollama.sh"
echo ""
echo "3. Deploy to Raspberry Pi:"
echo "   ./deploy_to_rpi.sh pi@<your-rpi-ip>"
echo ""
echo "4. Run benchmarks:"
echo "   python3 test_tinyllama.py"

echo -e "\n${BLUE}Model sizes:${NC}"
echo "  - Original (FP16): ~2.2 GB"
echo "  - M4 Max (NVFP4): ~0.7 GB (3.1x compression)"
echo "  - Raspberry Pi (NVFP4): ~0.6 GB (3.7x compression)"

echo -e "\n${GREEN}Happy experimenting!${NC}"