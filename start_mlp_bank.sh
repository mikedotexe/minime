#!/bin/bash
# Start MLP Neural Bank Service
# 13 x 7-layer perceptrons for consciousness thread enhancement

echo "🧠 Starting MLP Neural Bank Service..."
echo

cd mlp_bank || {
    echo "❌ mlp_bank directory not found"
    echo "   Run from mikeconsciousness/ root directory"
    exit 1
}

# Check if built
if [ ! -f "target/release/mlp-bank" ]; then
    echo "Building MLP bank (release mode)..."
    cargo build --release || {
        echo "❌ Build failed"
        exit 1
    }
fi

echo "Starting MLP bank on http://127.0.0.1:8080"
echo "  - 13 neural networks (one per consciousness thread)"
echo "  - 24-dimensional prime features"
echo "  - Xavier initialization (seed=42)"
echo

# Start with Xavier initialization
./target/release/mlp-bank --init-xavier 42 --bind 127.0.0.1:8080

# Note: Add --weights and --save-weights options when you have trained models
# Example: ./target/release/mlp-bank --weights trained_weights.bin
