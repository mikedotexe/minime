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
