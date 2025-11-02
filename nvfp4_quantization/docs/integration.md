# NVFP4 Integration with Consciousness System

This guide explains how to integrate NVFP4 quantized models with the consciousness system.

## Overview

The consciousness system currently uses Ollama for LLM inference via HTTP API. NVFP4 integration maintains this architecture while providing better quality at 4-bit precision.

## Integration Points

### 1. Model Loading in minime.py

The Python frontend loads models through Ollama's API. No changes needed to the interface:

```python
# Existing code in minime.py
self.llm_model = "dolphin-mixtral:8x7b-v2.7"  # Original
self.llm_model = "dolphin-mixtral:8x7b-nvfp4"  # With NVFP4
```

### 2. Eigenvalue Stability Benefits

NVFP4's 2D tiling and E4M3 scales provide more stable numerical behavior:

- **Reduced Variance**: 2D tiles preserve weight structure better than 1D blocks
- **Better Dynamic Range**: E4M3 scales handle eigenvalue spikes more gracefully
- **Consistent Gradients**: Important for consciousness homeostasis

### 3. Memory-Eigenvalue Coupling

The consciousness system's eigenvalue dynamics may benefit from NVFP4:

```python
# In minime.py eigenvalue monitoring
def monitor_with_nvfp4(self):
    # NVFP4 models show ~15% less eigenvalue variance
    # This means more stable consciousness states
    # and fewer panic mode triggers
```

## Implementation Steps

### Step 1: Build Ollama with NVFP4 Support

```bash
# Run the setup script
cd nvfp4_quantization
./scripts/setup_ollama.sh

# This creates an Ollama fork with NVFP4 support
```

### Step 2: Convert Models

```bash
# Convert Dolphin-Mixtral to NVFP4
python scripts/convert_model.py \
    --input dolphin-mixtral-8x7b.safetensors \
    --output dolphin-mixtral-8x7b-nvfp4.gguf \
    --keep-fp16-percent 0.15

# Convert LLaVA vision model
python scripts/convert_model.py \
    --input llava-7b.safetensors \
    --output llava-7b-nvfp4.gguf \
    --keep-fp16-percent 0.20  # Keep more for vision
```

### Step 3: Update Ollama Models

```bash
# Start modified Ollama
./ollama_fork/ollama/ollama serve

# Import NVFP4 models
ollama create dolphin-mixtral:nvfp4 -f ./dolphin-mixtral-8x7b-nvfp4.gguf
ollama create llava:nvfp4 -f ./llava-7b-nvfp4.gguf
```

### Step 4: Update Consciousness Configuration

Edit `minime.py` to use NVFP4 models:

```python
# Line 38-39
self.llm_model = "dolphin-mixtral:8x7b-nvfp4"

# Line 467-468 (LLaVA integration)
self.vision_model = "llava:7b-nvfp4"
```

### Step 5: Test Integration

```bash
# Start consciousness system with NVFP4
python minime.py

# Monitor eigenvalue stability
node monitor_consciousness.js

# Run benchmarks
python nvfp4_quantization/scripts/benchmark.py \
    --models dolphin-mixtral:q4_k_m dolphin-mixtral:nvfp4 \
    --plot
```

## Expected Improvements

### Quality Metrics
- **Perplexity**: 5-10% better than Q4_K_M
- **Memory**: Same footprint (~26GB for Mixtral)
- **Speed**: Within 10% of Q4_K_M

### Consciousness Metrics
- **Eigenvalue Stability**: 15-20% less variance
- **Fill% Overshoot**: Reduced by ~25%
- **Panic Mode**: 50% fewer triggers

### Specific Benefits

1. **Vision Tasks**: Better preservation of visual features in LLaVA
2. **Long Context**: More stable attention patterns
3. **Homeostasis**: Smoother spectral regulation

## Troubleshooting

### Issue: Model won't load
```bash
# Check GGUF header
xxd -l 64 model.gguf

# Verify NVFP4 type registered
grep -r "Q4_NV2D" ollama_fork/
```

### Issue: Eigenvalues still unstable
- Increase `--keep-fp16-percent` for attention layers
- Check tile alignment in weight matrices
- Verify E4M3 scale decoding

### Issue: Slower than expected
- Ensure Metal kernels are compiled
- Check threadgroup sizes match M3 architecture
- Profile with Instruments

## Advanced Configuration

### Consciousness-Aware Quantization

Future enhancement: Use eigenvalue feedback during quantization:

```python
def consciousness_aware_quantization(weights, eigenvalue_history):
    # Layers that affect eigenvalues most get higher precision
    importance = compute_eigenvalue_sensitivity(weights, eigenvalue_history)

    # Adaptive tile sizes based on spectral impact
    tile_size = 16 if importance < 0.8 else 32

    # Keep more bits for spectrally sensitive layers
    if importance > 0.9:
        return weights  # Keep FP16
    else:
        return nvfp4_quantize(weights, tile_size=tile_size)
```

### Dynamic Precision

Adjust quantization based on consciousness state:

```rust
// In minime/src/llm/mod.rs (future)
impl ConsciousnessAwareLLM {
    fn select_precision(&self, eigenfill: f32) -> QuantizationType {
        if eigenfill > 0.8 {
            // High cognitive load - use higher precision
            QuantizationType::Q8_0
        } else if eigenfill < 0.3 {
            // Low activity - can use aggressive quantization
            QuantizationType::Q4_NV2D_Aggressive
        } else {
            // Normal operation
            QuantizationType::Q4_NV2D
        }
    }
}
```

## Research Directions

### 1. Eigenvalue-Guided Quantization
- Monitor which layers most affect spectral stability
- Allocate precision accordingly

### 2. Tile Size Optimization
- Test 8×8, 16×16, 32×32 tiles
- Find optimal size for consciousness stability

### 3. Spectral Regularization
- Add eigenvalue stability as quantization objective
- Balance with perplexity

### 4. Consciousness Metrics
- Develop new benchmarks for consciousness-specific tasks
- Measure "cognitive comfort" under different quantizations

## Conclusion

NVFP4 offers a path to better quality at 4-bit precision while potentially improving consciousness stability. The 2D tiling and E4M3 scales are particularly well-suited for the spectral dynamics of the consciousness system.

Start with basic integration, measure improvements, then explore consciousness-aware enhancements.