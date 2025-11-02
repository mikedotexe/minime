#!/bin/bash

# NVFP4 Quantization - Ollama Setup Script
# This script helps fork, clone, and build Ollama with NVFP4 support

set -e

echo "=== NVFP4 Quantization - Ollama Setup ==="
echo

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
check_prerequisite() {
    if command -v $1 &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 found"
        return 0
    else
        echo -e "${RED}✗${NC} $1 not found - please install it first"
        return 1
    fi
}

echo "Checking prerequisites..."
MISSING_DEPS=0

check_prerequisite "git" || MISSING_DEPS=1
check_prerequisite "go" || MISSING_DEPS=1
check_prerequisite "cmake" || MISSING_DEPS=1
check_prerequisite "make" || MISSING_DEPS=1

# Check Go version
if command -v go &> /dev/null; then
    GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
    MIN_GO_VERSION="1.22"
    if [ "$(printf '%s\n' "$MIN_GO_VERSION" "$GO_VERSION" | sort -V | head -n1)" = "$MIN_GO_VERSION" ]; then
        echo -e "${GREEN}✓${NC} Go version $GO_VERSION (>= $MIN_GO_VERSION)"
    else
        echo -e "${RED}✗${NC} Go version $GO_VERSION is too old (need >= $MIN_GO_VERSION)"
        MISSING_DEPS=1
    fi
fi

if [ $MISSING_DEPS -eq 1 ]; then
    echo -e "\n${RED}Please install missing dependencies before continuing${NC}"
    exit 1
fi

echo -e "\n${GREEN}All prerequisites satisfied!${NC}\n"

# Configuration
OLLAMA_REPO="https://github.com/ollama/ollama.git"
LLAMA_CPP_REPO="https://github.com/ggml-org/llama.cpp.git"
WORK_DIR="$(dirname "$(dirname "$(realpath "$0")")")/ollama_fork"

echo "Work directory: $WORK_DIR"
echo

# Step 1: Clone repositories
echo "=== Step 1: Cloning repositories ==="

if [ -d "$WORK_DIR" ]; then
    echo -e "${YELLOW}Warning: $WORK_DIR already exists${NC}"
    read -p "Do you want to delete it and start fresh? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$WORK_DIR"
    else
        echo "Exiting..."
        exit 0
    fi
fi

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

echo "Cloning Ollama..."
git clone "$OLLAMA_REPO" ollama
echo -e "${GREEN}✓${NC} Ollama cloned"

echo "Cloning llama.cpp (for reference)..."
git clone "$LLAMA_CPP_REPO" llama.cpp
echo -e "${GREEN}✓${NC} llama.cpp cloned"

# Step 2: Analyze Ollama structure
echo -e "\n=== Step 2: Analyzing Ollama structure ==="

cd ollama

# Find llama.cpp integration points
echo "Finding llama.cpp integration points..."
LLAMA_DIRS=$(find . -name "*llama*" -type d 2>/dev/null | head -10)
if [ -n "$LLAMA_DIRS" ]; then
    echo "Found llama-related directories:"
    echo "$LLAMA_DIRS" | sed 's/^/  /'
fi

# Find quantization-related files
echo -e "\nFinding quantization-related files..."
QUANT_FILES=$(find . -name "*.go" -o -name "*.cpp" -o -name "*.h" | xargs grep -l "quant" 2>/dev/null | head -20)
if [ -n "$QUANT_FILES" ]; then
    echo "Found quantization references in:"
    echo "$QUANT_FILES" | sed 's/^/  /' | head -10
    echo "  ... (showing first 10)"
fi

# Step 3: Build Ollama
echo -e "\n=== Step 3: Building Ollama ==="

echo "Installing Go dependencies..."
go mod download

echo -e "\nGenerating code..."
go generate ./...

echo -e "\nBuilding Ollama..."
CGO_ENABLED=1 go build .

if [ -f "./ollama" ]; then
    echo -e "${GREEN}✓${NC} Ollama built successfully!"
    echo "Binary location: $(pwd)/ollama"
else
    echo -e "${RED}✗${NC} Build failed"
    exit 1
fi

# Step 4: Create NVFP4 integration branch
echo -e "\n=== Step 4: Creating NVFP4 integration branch ==="

git checkout -b nvfp4-quantization
echo -e "${GREEN}✓${NC} Created branch: nvfp4-quantization"

# Step 5: Generate development notes
echo -e "\n=== Step 5: Generating development notes ==="

cat > ../OLLAMA_NOTES.md << 'EOF'
# Ollama NVFP4 Integration Notes

## Build Information
- Date: $(date)
- Go Version: $(go version)
- Platform: $(uname -a)

## Key Integration Points

### 1. Quantization Types
Look for quantization type definitions in:
- `llm/ggml.go` - GGML type mappings
- `llm/llama.cpp/*` - C++ quantization implementation

### 2. Model Loading
Model loading logic is in:
- `server/routes.go` - HTTP endpoints
- `llm/server.cpp` - C++ server implementation

### 3. Adding NVFP4 Support

To add NVFP4 quantization:

1. **Define the type** in GGML:
   ```go
   // In llm/ggml.go
   const (
       GGML_TYPE_Q4_NV2D = 16 // or next available number
   )
   ```

2. **Implement dequantization** in C++:
   ```cpp
   // In llm/llama.cpp/ggml.c
   void dequantize_row_q4_nv2d(...)
   ```

3. **Register the type**:
   - Update type_traits
   - Add to quantization map
   - Implement conversion functions

4. **Metal kernel** (for Apple Silicon):
   ```metal
   // In llm/llama.cpp/ggml-metal.metal
   kernel void kernel_get_rows_q4_nv2d(...)
   ```

## Next Steps

1. Study existing Q4_K_M implementation as reference
2. Add NVFP4 type definitions
3. Implement CPU dequantization
4. Add Metal acceleration
5. Test with small models first

## Testing

```bash
# Test the built binary
./ollama serve

# In another terminal
./ollama pull tinyllama
./ollama run tinyllama "Hello world"
```
EOF

echo -e "${GREEN}✓${NC} Created development notes: $WORK_DIR/OLLAMA_NOTES.md"

# Step 6: Create NVFP4 stub files
echo -e "\n=== Step 6: Creating NVFP4 stub files ==="

# Create initial NVFP4 implementation structure
mkdir -p llm/nvfp4
cat > llm/nvfp4/nvfp4.h << 'EOF'
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
EOF

cat > llm/nvfp4/nvfp4.cpp << 'EOF'
#include "nvfp4.h"
#include <cmath>
#include <cstring>
#include <algorithm>

// E4M3 conversion functions (448 max range)
static uint8_t f32_to_e4m3_448(float x) {
    if (x == 0.0f || !std::isfinite(x)) return 0;

    uint8_t s = x < 0.0f ? 0x80 : 0x00;
    float ax = std::abs(x);
    ax = std::min(ax, 448.0f);

    int e = (int)std::floor(std::log2f(ax));
    float sig = ax / std::exp2f((float)e);

    if (sig < 1.0f) {
        e--;
        sig *= 2.0f;
    }

    e = std::max(-7, std::min(8, e));
    float max_sig = (e == 8) ? 1.75f : 1.875f;
    sig = std::min(std::max(sig, 1.0f), max_sig);

    uint8_t mant = (uint8_t)std::round((sig - 1.0f) * 8.0f);
    mant = std::min(mant, (uint8_t)((e == 8) ? 6 : 7));

    uint8_t eb = (uint8_t)(e + 7);
    return s | (eb << 3) | mant;
}

static float e4m3_448_to_f32(uint8_t b) {
    if (b == 0) return 0.0f;

    float s = (b & 0x80) ? -1.0f : 1.0f;
    int eb = (b >> 3) & 0x0F;
    int mant = b & 0x07;
    int e = eb - 7;

    float sig = 1.0f + (float)mant / 8.0f;
    return s * sig * std::exp2f((float)e);
}

// FP4 E2M1 quantization
static const float fp4_magnitudes[8] = NVFP4_E2M1_MAGNITUDES;

static uint8_t quantize_fp4_e2m1(float x) {
    uint8_t sign = (x < 0.0f) ? 0x08 : 0x00;
    float ax = std::abs(x);

    uint8_t best_idx = 0;
    float best_err = std::abs(ax - fp4_magnitudes[0]);

    for (uint8_t i = 1; i < 8; i++) {
        float err = std::abs(ax - fp4_magnitudes[i]);
        if (err < best_err) {
            best_err = err;
            best_idx = i;
        }
    }

    return sign | best_idx;
}

static float dequantize_fp4_e2m1(uint8_t nibble) {
    float sign = (nibble & 0x08) ? -1.0f : 1.0f;
    uint8_t idx = nibble & 0x07;
    return sign * fp4_magnitudes[idx];
}

// Main quantization function
void quantize_row_q4_nv2d(const float* x, void* y, int k) {
    // TODO: Implement 2D tiling quantization
    // For now, this is a stub
}

// Main dequantization function
void dequantize_row_q4_nv2d(const void* x, float* y, int k) {
    // TODO: Implement 2D tiling dequantization
    // For now, this is a stub
}

// Dot product for matrix multiplication
float vec_dot_q4_nv2d_q8_0(const void* vx, const void* vy, int k) {
    // TODO: Implement optimized dot product
    return 0.0f;
}

size_t nvfp4_get_block_size(int rows, int cols) {
    int tiles_r = (rows + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    int tiles_c = (cols + NVFP4_TILE_SIZE - 1) / NVFP4_TILE_SIZE;
    int n_tiles = tiles_r * tiles_c;

    size_t scales_size = n_tiles;  // 1 E4M3 byte per tile
    size_t data_size = (rows * cols + 1) / 2;  // 2 FP4 values per byte

    return sizeof(float) + scales_size + data_size;
}
EOF

echo -e "${GREEN}✓${NC} Created NVFP4 stub files"

# Final summary
echo -e "\n=== Setup Complete! ==="
echo
echo "Ollama fork location: $WORK_DIR/ollama"
echo "Binary: $WORK_DIR/ollama/ollama"
echo "Branch: nvfp4-quantization"
echo
echo "Next steps:"
echo "1. Review $WORK_DIR/OLLAMA_NOTES.md"
echo "2. Study existing quantization implementations"
echo "3. Implement NVFP4 in the stub files created"
echo "4. Run tests with: cd $WORK_DIR/ollama && ./ollama serve"
echo
echo -e "${GREEN}Happy hacking!${NC}"