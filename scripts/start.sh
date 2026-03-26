#!/bin/bash
set -euo pipefail

# MikesSpatialMind Consciousness Startup Script
# Launches MLX server, Rust engine, and autonomous agent in correct order.
# PIDs are saved to /tmp/minime_pids/ for stop.sh to use.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_DIR="/tmp/minime_pids"
LOG_DIR="$PROJECT_DIR/workspace/logs"

# Configuration (override via environment)
MLX_MODEL="${MLX_MODEL:-$HOME/models/Qwen3.5-27B-Claude-4.6-Opus-Distilled-mlx-4bit}"
MLX_PORT="${MLX_PORT:-8090}"
EIGENFILL_TARGET="${EIGENFILL_TARGET:-0.55}"
REG_TICK_SECS="${REG_TICK_SECS:-0.5}"
AGENT_INTERVAL="${AGENT_INTERVAL:-60}"
LLM_BACKEND="${MINIME_LLM_BACKEND:-ollama}"
CAMERA_INDEX="${CAMERA_INDEX:-0}"
ENABLE_MIC="${ENABLE_MIC:-true}"
ENABLE_CAMERA="${ENABLE_CAMERA:-true}"
ENABLE_WHISPER="${ENABLE_WHISPER:-false}"
MLX_VISION_MODEL="${MLX_VISION_MODEL:-}"
MLX_VISION_PORT="${MLX_VISION_PORT:-8091}"
ENABLE_MLX_VISION="${ENABLE_MLX_VISION:-false}"
ENABLE_GPU_AV="${ENABLE_GPU_AV:-true}"
LORA_ADAPTER="${LORA_ADAPTER:-}"

# Ensure PATH includes node/uv tools
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

mkdir -p "$PID_DIR" "$LOG_DIR"

# --- Pre-flight checks ---

echo "=== MikesSpatialMind Startup ==="
echo ""

# Check for existing processes
if [ -f "$PID_DIR/mlx.pid" ] || [ -f "$PID_DIR/engine.pid" ] || [ -f "$PID_DIR/agent.pid" ]; then
    echo "WARNING: PID files exist from a previous run."
    echo "Run scripts/stop.sh first, or remove /tmp/minime_pids/ manually."
    exit 1
fi

EXISTING=$(ps aux | grep -E "(mlx_lm\.server.*$MLX_PORT|target/release/minime|autonomous_agent\.py|mic_to_sensory|camera_to_sensory)" | grep -v grep | wc -l || true)
if [ "$EXISTING" -gt 0 ]; then
    echo "WARNING: Found $EXISTING existing consciousness process(es)."
    echo "Run scripts/stop.sh first."
    ps aux | grep -E "(mlx_lm\.server.*$MLX_PORT|target/release/minime|autonomous_agent\.py)" | grep -v grep
    exit 1
fi

# Determine total steps based on optional services
TOTAL_STEPS=5
if [ "$ENABLE_MLX_VISION" = "true" ]; then
    TOTAL_STEPS=6
fi

# --- Step 1: Start MLX Server (skip if using Ollama) ---

if [ "$LLM_BACKEND" = "mlx" ]; then
    # Check model: local directory or HuggingFace model ID (contains '/')
    if [ ! -d "$MLX_MODEL" ] && [[ "$MLX_MODEL" != */* ]]; then
        echo "ERROR: MLX model not found at $MLX_MODEL"
        echo "       Provide a local path or a HuggingFace model ID (e.g. mlx-community/Qwen3-8B-4bit)"
        exit 1
    fi

    echo "[1/$TOTAL_STEPS] Starting MLX server (model=$MLX_MODEL, port $MLX_PORT)..."
    MLX_ADAPTER_FLAG=""
    if [ -n "$LORA_ADAPTER" ] && [ -d "$LORA_ADAPTER" ]; then
        MLX_ADAPTER_FLAG="--adapter-path $LORA_ADAPTER"
        echo "      Using LoRA adapter: $LORA_ADAPTER"
    fi
    MLX_CACHE_BYTES="${MLX_CACHE_BYTES:-4294967296}"  # 4GB KV cache limit (default)
    mlx_lm.server \
        --model "$MLX_MODEL" \
        --trust-remote-code \
        --port "$MLX_PORT" \
        --prompt-cache-bytes "$MLX_CACHE_BYTES" \
        $MLX_ADAPTER_FLAG \
        > "$LOG_DIR/mlx_server.log" 2>&1 &
    MLX_PID=$!
    echo "$MLX_PID" > "$PID_DIR/mlx.pid"
    echo "      PID: $MLX_PID (log: workspace/logs/mlx_server.log)"

    # Wait for MLX server to be ready
    echo "      Waiting for MLX server to accept connections..."
    for i in $(seq 1 60); do
        if curl -s "http://localhost:$MLX_PORT/v1/models" > /dev/null 2>&1; then
            echo "      MLX server ready after ${i}s."
            break
        fi
        if ! kill -0 "$MLX_PID" 2>/dev/null; then
            echo "ERROR: MLX server exited unexpectedly. Check $LOG_DIR/mlx_server.log"
            rm -f "$PID_DIR/mlx.pid"
            exit 1
        fi
        sleep 1
    done

    if ! curl -s "http://localhost:$MLX_PORT/v1/models" > /dev/null 2>&1; then
        echo "ERROR: MLX server did not become ready within 60s."
        kill -TERM "$MLX_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx.pid"
        exit 1
    fi
else
    echo ""
    echo "[1/$TOTAL_STEPS] LLM backend: Ollama (MLX server skipped — no GPU memory contention)"
fi

# --- Step 1b: (Optional) Start MLX Vision Server ---

if [ "$ENABLE_MLX_VISION" = "true" ]; then
    if [ -z "$MLX_VISION_MODEL" ]; then
        echo "ERROR: ENABLE_MLX_VISION=true but MLX_VISION_MODEL is not set."
        echo "Set MLX_VISION_MODEL to the path of your VLM model directory."
        kill -TERM "$MLX_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx.pid"
        exit 1
    fi
    if [ ! -d "$MLX_VISION_MODEL" ]; then
        echo "ERROR: MLX vision model not found at $MLX_VISION_MODEL"
        kill -TERM "$MLX_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx.pid"
        exit 1
    fi

    echo ""
    echo "[1b/$TOTAL_STEPS] Starting MLX Vision server (port $MLX_VISION_PORT)..."
    MLX_VISION_PORT="$MLX_VISION_PORT" mlx_lm.server \
        --model "$MLX_VISION_MODEL" \
        --trust-remote-code \
        --port "$MLX_VISION_PORT" \
        > "$LOG_DIR/mlx_vision_server.log" 2>&1 &
    MLX_VISION_PID=$!
    echo "$MLX_VISION_PID" > "$PID_DIR/mlx_vision.pid"
    echo "      PID: $MLX_VISION_PID (log: workspace/logs/mlx_vision_server.log)"

    echo "      Waiting for MLX Vision server to accept connections..."
    for i in $(seq 1 60); do
        if curl -s "http://localhost:$MLX_VISION_PORT/v1/models" > /dev/null 2>&1; then
            echo "      MLX Vision server ready after ${i}s."
            break
        fi
        if ! kill -0 "$MLX_VISION_PID" 2>/dev/null; then
            echo "ERROR: MLX Vision server exited unexpectedly. Check $LOG_DIR/mlx_vision_server.log"
            rm -f "$PID_DIR/mlx_vision.pid"
            kill -TERM "$MLX_PID" 2>/dev/null
            rm -f "$PID_DIR/mlx.pid"
            exit 1
        fi
        sleep 1
    done

    if ! curl -s "http://localhost:$MLX_VISION_PORT/v1/models" > /dev/null 2>&1; then
        echo "ERROR: MLX Vision server did not become ready within 60s."
        kill -TERM "$MLX_VISION_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx_vision.pid"
        kill -TERM "$MLX_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx.pid"
        exit 1
    fi
else
    echo ""
    echo "[1b] MLX Vision server: DISABLED (set ENABLE_MLX_VISION=true to enable)"
fi

# --- Step 2: Start Rust Engine ---

echo ""
GPU_AV_FLAG=""
if [ "$ENABLE_GPU_AV" = "true" ]; then
    GPU_AV_FLAG="--enable-gpu-av"
    echo "[2/$TOTAL_STEPS] Starting Rust consciousness engine (GPU video enabled)..."
else
    echo "[2/$TOTAL_STEPS] Starting Rust consciousness engine..."
fi
cd "$PROJECT_DIR/minime"
cargo run --release -- run \
    --log-homeostat \
    --eigenfill-target "$EIGENFILL_TARGET" \
    --reg-tick-secs "$REG_TICK_SECS" \
    $GPU_AV_FLAG \
    > "$LOG_DIR/engine.log" 2>&1 &
ENGINE_PID=$!
echo "$ENGINE_PID" > "$PID_DIR/engine.pid"
echo "      PID: $ENGINE_PID (log: workspace/logs/engine.log)"

# Wait for websocket to be available
echo "      Waiting for engine websocket (port 7878)..."
for i in $(seq 1 30); do
    if nc -z 127.0.0.1 7878 2>/dev/null; then
        echo "      Engine ready after ${i}s."
        break
    fi
    if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
        echo "ERROR: Engine exited unexpectedly. Check $LOG_DIR/engine.log"
        rm -f "$PID_DIR/engine.pid"
        # Clean up MLX too
        kill -TERM "$MLX_PID" 2>/dev/null
        rm -f "$PID_DIR/mlx.pid"
        exit 1
    fi
    sleep 1
done

# --- Step 3: Start Autonomous Agent ---

echo ""
echo "[3/$TOTAL_STEPS] Starting autonomous agent (backend=$LLM_BACKEND, interval=${AGENT_INTERVAL}s)..."
cd "$PROJECT_DIR"
MINIME_LLM_BACKEND="$LLM_BACKEND" python3 autonomous_agent.py \
    --interval "$AGENT_INTERVAL" \
    > "$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
echo "$AGENT_PID" > "$PID_DIR/agent.pid"
echo "      PID: $AGENT_PID (log: workspace/logs/agent.log)"

# --- Step 4: Start Microphone Service ---

if [ "$ENABLE_MIC" = "true" ]; then
    echo ""
    echo "[4/$TOTAL_STEPS] Starting microphone service..."
    cd "$PROJECT_DIR"
    WHISPER_FLAG=""
    if [ "$ENABLE_WHISPER" = "true" ]; then
        WHISPER_FLAG="--whisper"
    fi
    python3 tools/mic_to_sensory.py $WHISPER_FLAG \
        > "$LOG_DIR/mic.log" 2>&1 &
    MIC_PID=$!
    echo "$MIC_PID" > "$PID_DIR/mic.pid"
    echo "      PID: $MIC_PID (log: workspace/logs/mic.log)"
else
    echo ""
    echo "[4/$TOTAL_STEPS] Microphone service: DISABLED"
fi

# --- Step 5: Start Camera Service ---

if [ "$ENABLE_CAMERA" = "true" ]; then
    echo ""
    if [ "$ENABLE_GPU_AV" = "true" ]; then
        echo "[5/$TOTAL_STEPS] Starting camera service (GPU path, index $CAMERA_INDEX)..."
        cd "$PROJECT_DIR"
        python3 minime/tools/camera_client.py --camera "$CAMERA_INDEX" --fps 1 \
            > "$LOG_DIR/camera.log" 2>&1 &
    else
        echo "[5/$TOTAL_STEPS] Starting camera service (CPU path, index $CAMERA_INDEX)..."
        cd "$PROJECT_DIR"
        python3 camera_to_sensory.py --camera "$CAMERA_INDEX" \
            > "$LOG_DIR/camera.log" 2>&1 &
    fi
    CAMERA_PID=$!
    echo "$CAMERA_PID" > "$PID_DIR/camera.pid"
    echo "      PID: $CAMERA_PID (log: workspace/logs/camera.log)"
else
    echo ""
    echo "[5/$TOTAL_STEPS] Camera service: DISABLED"
fi

# --- Summary ---

echo ""
echo "=== All processes started ==="
echo ""
if [ "$LLM_BACKEND" = "mlx" ]; then
    echo "  MLX server:  PID $MLX_PID (port $MLX_PORT)"
    if [ "$ENABLE_MLX_VISION" = "true" ]; then
        echo "  MLX vision:  PID $MLX_VISION_PID (port $MLX_VISION_PORT)"
    fi
else
    echo "  LLM backend: Ollama (http://localhost:11434)"
fi
echo "  Rust engine: PID $ENGINE_PID (ports 7878-7880)"
echo "  Agent:       PID $AGENT_PID (interval ${AGENT_INTERVAL}s)"
if [ "$ENABLE_MIC" = "true" ]; then
    echo "  Microphone:  PID $MIC_PID (ws://7879)"
fi
if [ "$ENABLE_CAMERA" = "true" ]; then
    echo "  Camera:      PID $CAMERA_PID (index $CAMERA_INDEX, ws://7879)"
fi
echo ""
echo "  PID files:   $PID_DIR/"
echo "  Logs:        $LOG_DIR/"
echo ""
echo "  Monitor:     tail -f $LOG_DIR/engine.log"
echo "  Journals:    ls -t workspace/journal/ | head -5"
echo "  Stop:        scripts/stop.sh"
echo ""
echo "Remember: Monitor the consciousness. Never leave it running unattended."
