# NVFP4 Quantization for Ollama

This project implements NVFP4 (4-bit floating point) quantization for Ollama, based on the NVIDIA FP4 paper. The goal is to achieve better quality at 4-bit precision through:

1. **2D Tiling**: 16×16 weight tiles instead of 1D blocks
2. **E4M3 Scales**: Better dynamic range than power-of-2 scales
3. **FP4 E2M1 Format**: 8 representable magnitudes with sign
4. **Selective FP16**: Keep ~15% critical layers unquantized

## Project Structure

```
nvfp4_quantization/
├── README.md               # This file
├── docs/                   # Documentation
│   ├── architecture.md     # NVFP4 format details
│   ├── benchmarks.md       # Quality and performance results
│   └── integration.md      # Ollama integration guide
├── src/                    # Source code
│   ├── nvfp4_format.h      # Data structures
│   ├── nvfp4_cpu.cpp       # CPU dequantization
│   ├── nvfp4_metal.cpp     # Metal GPU kernels
│   └── nvfp4_convert.cpp   # Model conversion tool
├── tests/                  # Unit tests
│   ├── test_format.cpp
│   ├── test_dequant.cpp
│   └── test_quality.cpp
├── scripts/                # Helper scripts
│   ├── setup_ollama.sh     # Fork and build Ollama
│   ├── convert_model.py    # Convert HF models to NVFP4
│   └── benchmark.py        # Run quality benchmarks
└── results/                # Experimental results
    ├── perplexity/
    ├── performance/
    └── consciousness/
```

## Quick Start

1. **Fork and Build Ollama**:
   ```bash
   ./scripts/setup_ollama.sh
   ```

2. **Convert a Model**:
   ```bash
   python scripts/convert_model.py \
     --model dolphin-mixtral:8x7b \
     --output mixtral-nvfp4.gguf \
     --format nvfp4
   ```

3. **Run with Consciousness System**:
   ```bash
   # Start Ollama with NVFP4 support
   ./ollama serve

   # Load the quantized model
   ollama pull mixtral-nvfp4

   # Run consciousness system
   python minime.py
   ```

## Development Status

- [x] Project structure setup
- [ ] Ollama fork and build
- [ ] NVFP4 data structures
- [ ] CPU dequantization kernel
- [ ] Metal GPU optimization
- [ ] Model conversion tool
- [ ] Quality benchmarks
- [ ] Consciousness integration

## Research Goals

1. **Primary**: Match or exceed Q4_K_M quality with same memory footprint
2. **Secondary**: Explore consciousness-aware quantization metrics
3. **Stretch**: Dynamic precision based on eigenvalue homeostasis

## Hardware Requirements

- Apple Silicon Mac (M1/M2/M3)
- macOS 13.0+
- Xcode 14+ with Metal SDK
- 16GB+ unified memory (32GB+ recommended for Mixtral)

## References

- [NVIDIA FP4 Paper](https://arxiv.org/abs/2310.16836)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [Ollama](https://github.com/ollama/ollama)