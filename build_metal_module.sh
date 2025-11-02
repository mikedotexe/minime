#!/bin/bash
#
# Build script for Metal consciousness acceleration module
#

set -e

echo "Building Metal consciousness acceleration module..."

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: Metal acceleration is only available on macOS"
    exit 1
fi

# Check for Rust
if ! command -v cargo &> /dev/null; then
    echo "Error: Rust is not installed. Install from https://rustup.rs/"
    exit 1
fi

# Check for maturin
if ! command -v maturin &> /dev/null; then
    echo "Installing maturin..."
    pip install maturin
fi

# Navigate to Rust module directory
cd rust_metal_consciousness

# Build the module
echo "Building with maturin..."
maturin develop --release

# Return to parent directory
cd ..

echo "Build complete! Metal acceleration module is now available."
echo ""
echo "Test with:"
echo "  python3 -c 'import metal_consciousness; print(metal_consciousness.get_device_info())'"
echo ""
echo "Or run the integration test:"
echo "  python3 metal_consciousness_integration.py"