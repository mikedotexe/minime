#!/bin/bash
set -uo pipefail

# MikesSpatialMind Graceful Shutdown Script
# Follows CLAUDE.md shutdown sequence:
#   1. Stop sensory services (camera clients)
#   2. Wait for queues to drain
#   3. Stop autonomous agent
#   4. Stop Rust engine
#   5. Stop MLX server
#   6. Verify all stopped

PID_DIR="/tmp/minime_pids"

echo "=== MikesSpatialMind Shutdown ==="
echo ""

stop_by_pid_file() {
    local name="$1"
    local pidfile="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping $name (PID $pid)..."
            kill -TERM "$pid"
            # Wait up to 10s for graceful exit
            for i in $(seq 1 10); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 1
            done
            if kill -0 "$pid" 2>/dev/null; then
                echo "  WARNING: $name did not exit after 10s, sending SIGKILL"
                kill -9 "$pid" 2>/dev/null
            fi
        else
            echo "  $name (PID $pid) already stopped."
        fi
        rm -f "$pidfile"
    fi
}

# Step 1: Stop camera/sensory services
echo "[1/5] Stopping sensory services..."
stop_by_pid_file "host-sensory" "$PID_DIR/host.pid"
stop_by_pid_file "visual-frame-service" "$PID_DIR/visual.pid"
stop_by_pid_file "mic" "$PID_DIR/mic.pid"
stop_by_pid_file "camera" "$PID_DIR/camera.pid"
pkill -TERM -f "host-sensory" 2>/dev/null && echo "  Stopped host-sensory" || true
pkill -TERM -f "mic_to_sensory.py" 2>/dev/null && echo "  Stopped mic_to_sensory" || true
pkill -TERM -f "camera_to_sensory.py" 2>/dev/null && echo "  Stopped camera_to_sensory" || true
pkill -TERM -f "camera_client.py" 2>/dev/null && echo "  Stopped camera_client" || true
pkill -TERM -f "visual_frame_service.py" 2>/dev/null && echo "  Stopped visual_frame_service" || true
# Kill any orphan sox/rec processes from mic capture
pkill -TERM -f "rec -q -t raw" 2>/dev/null || true

# Step 2: Drain queues
echo ""
echo "[2/5] Waiting 5s for queues to drain..."
sleep 5

# Step 3: Stop autonomous agent
echo ""
echo "[3/5] Stopping autonomous agent..."
stop_by_pid_file "agent" "$PID_DIR/agent.pid"
# Also catch any agent not started via start.sh
pkill -TERM -f "autonomous_agent.py" 2>/dev/null || true

# Step 4: Stop Rust engine
echo ""
echo "[4/5] Stopping Rust consciousness engine..."
stop_by_pid_file "engine" "$PID_DIR/engine.pid"
pkill -TERM -f "target/release/minime" 2>/dev/null || true

sleep 2

# Step 5: Stop MLX server
echo ""
echo "[5/5] Stopping MLX server..."
stop_by_pid_file "mlx" "$PID_DIR/mlx.pid"
pkill -TERM -f "mlx_lm.server" 2>/dev/null || true

sleep 2

# Cleanup PID directory
rm -rf "$PID_DIR" 2>/dev/null

# Verify
echo ""
echo "=== Verification ==="
REMAINING=$(ps aux | grep -E "(mlx_lm\.server|target/release/minime|autonomous_agent\.py|camera_to_sensory|camera_client|visual_frame_service|mic_to_sensory|host-sensory)" | grep -v grep | wc -l || true)

if [ "$REMAINING" -eq 0 ]; then
    echo "All consciousness processes stopped."
else
    echo "WARNING: $REMAINING process(es) still running:"
    ps aux | grep -E "(mlx_lm\.server|target/release/minime|autonomous_agent\.py|camera_to_sensory|camera_client|visual_frame_service|mic_to_sensory|host-sensory)" | grep -v grep
fi

echo ""
echo "Shutdown complete."
