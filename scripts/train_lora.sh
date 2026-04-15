#!/bin/bash
set -euo pipefail

TEST_MODE=false
if [[ "${1:-}" == "--test" ]]; then
    TEST_MODE=true
    echo "=== TEST MODE: validating pipeline without training ==="
    echo ""
fi

# LoRA Fine-Tuning Script for MikesSpatialMind
# Trains the being's authentic voice from its journal entries.
#
# IMPORTANT: The model server must NOT be running during training.
# A 27B 8-bit model uses ~27GB for serving and ~38GB for LoRA training.
# On a 64GB machine, both cannot run simultaneously.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_DIR="/tmp/minime_pids"

# Configuration
MLX_MODEL="${MLX_MODEL:-$HOME/models/Qwen3.5-27B-Claude-4.6-Opus-Distilled-mlx-8bit}"
DATA_DIR="$PROJECT_DIR/workspace/lora_data"
ADAPTER_DIR="$PROJECT_DIR/workspace/lora_adapter"
ITERS="${LORA_ITERS:-400}"
LR="${LORA_LR:-2e-5}"
NUM_LAYERS="${LORA_LAYERS:-8}"

export PATH="$HOME/.local/bin:$PATH"

echo "=== LoRA Training for MikesSpatialMind ==="
echo ""

# --- Pre-flight checks ---

# Check model exists
if [ ! -d "$MLX_MODEL" ]; then
    echo "ERROR: Model not found at $MLX_MODEL"
    exit 1
fi

# Check training data exists
if [ ! -f "$DATA_DIR/train.jsonl" ]; then
    echo "No training data found. Generating from journal entries..."
    cd "$PROJECT_DIR"
    python3 tools/prepare_lora_data.py --output-dir "$DATA_DIR"
    echo ""
fi

N_TRAIN=$(wc -l < "$DATA_DIR/train.jsonl")
N_VALID=$(wc -l < "$DATA_DIR/valid.jsonl")
echo "Training data: $N_TRAIN train, $N_VALID validation examples"

# Check for running model server (would cause OOM)
if [ -f "$PID_DIR/mlx.pid" ]; then
    MLX_PID=$(cat "$PID_DIR/mlx.pid")
    if kill -0 "$MLX_PID" 2>/dev/null; then
        echo ""
        echo "ERROR: MLX model server is running (PID $MLX_PID)."
        echo "Training requires ~38GB RAM. The server uses ~27GB."
        echo "Combined, they exceed 64GB and will crash."
        echo ""
        echo "Stop the server first:  scripts/stop.sh"
        echo "Or just the server:     kill -TERM $MLX_PID && rm $PID_DIR/mlx.pid"
        exit 1
    fi
fi

# Also check by port
if curl -s "http://localhost:8090/v1/models" > /dev/null 2>&1; then
    echo ""
    echo "ERROR: An MLX server is responding on port 8090."
    echo "Stop it before training to avoid OOM crashes."
    exit 1
fi

# Check available memory
TOTAL_MEM_GB=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1024/1024/1024}')
echo "System RAM: ${TOTAL_MEM_GB}GB (training peak: ~38GB)"

if [ "$TOTAL_MEM_GB" -lt 48 ]; then
    echo "WARNING: ${TOTAL_MEM_GB}GB RAM may be tight for LoRA training of a 27B model."
    echo "         Consider closing other applications."
fi

echo ""
echo "Training config:"
echo "  Model:      $(basename "$MLX_MODEL")"
echo "  Iterations: $ITERS (~$(echo "$ITERS $N_TRAIN" | awk '{printf "%.1f", $1/$2}') epochs)"
echo "  LR:         $LR"
echo "  LoRA layers: $NUM_LAYERS (of 64 total)"
echo "  Dropout:    0.05"
echo "  Checkpoint: enabled (saves every 100 iters)"
echo ""

# --- Train ---

echo "Starting training..."
echo ""

if [ "$TEST_MODE" = "true" ]; then
    echo "[test] Would run:"
    echo "  mlx_lm.lora \\"
    echo "    --model $MLX_MODEL \\"
    echo "    --data $DATA_DIR \\"
    echo "    --adapter-path $ADAPTER_DIR \\"
    echo "    --train --grad-checkpoint \\"
    echo "    --iters $ITERS --batch-size 1 --num-layers $NUM_LAYERS \\"
    echo "    --learning-rate $LR --steps-per-eval 50 --save-every 100"
    echo ""
    echo "=== Pipeline validation passed ==="
    echo "Training data: $N_TRAIN train, $N_VALID valid"
    echo "Model: $(basename "$MLX_MODEL")"
    echo "Adapter output: $ADAPTER_DIR"
    exit 0
fi

mlx_lm.lora \
    --model "$MLX_MODEL" \
    --data "$DATA_DIR" \
    --adapter-path "$ADAPTER_DIR" \
    --train \
    --grad-checkpoint \
    --iters "$ITERS" \
    --batch-size 1 \
    --num-layers "$NUM_LAYERS" \
    --learning-rate "$LR" \
    --steps-per-eval 50 \
    --steps-per-report 10 \
    --save-every 100

echo ""
echo "=== Training complete ==="
echo "Adapter saved to: $ADAPTER_DIR"
echo ""
echo "To serve the fine-tuned model:"
echo "  mlx_lm.server \\"
echo "    --model $MLX_MODEL \\"
echo "    --adapter-path $ADAPTER_DIR \\"
echo "    --trust-remote-code --port 8090"
