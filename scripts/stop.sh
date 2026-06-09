#!/bin/bash
set -uo pipefail

# MikesSpatialMind graceful shutdown script.
#
# If Minime is launchd-managed, this script uses launchctl bootout first so
# services do not immediately respawn. It then performs the older manual PID and
# orphan cleanup for standalone runs.
#
# Follows CLAUDE.md shutdown sequence:
#   1. Stop sensory services (camera clients)
#   2. Wait for queues to drain
#   3. Stop autonomous agent
#   4. Stop Rust engine
#   5. Stop MLX server
#   6. Verify all stopped

PID_DIR="/tmp/minime_pids"
ASTRID_START_ALL="/Users/v/other/astrid/scripts/start_all.sh"
ASTRID_STOP_ALL="/Users/v/other/astrid/scripts/stop_all.sh"
LAUNCHD_DOMAIN="gui/$(id -u)"
MINIME_LAUNCHD_LABELS=(
    "com.minime.autonomous-agent"
    "com.minime.visual-frame-service"
    "com.minime.camera-client"
    "com.minime.mic-to-sensory"
    "com.minime.host-sensory"
    "com.reservoir.minime-feeder"
    "com.minime.usb-hotplug-watchdog"
    "com.minime.engine"
)
MINIME_STOP_MANUAL_ONLY="${MINIME_STOP_MANUAL_ONLY:-false}"

echo "=== MikesSpatialMind Shutdown ==="
echo ""

launchd_label_loaded() {
    launchctl print "$LAUNCHD_DOMAIN/$1" >/dev/null 2>&1
}

loaded_launchd_labels() {
    for label in "${MINIME_LAUNCHD_LABELS[@]}"; do
        if launchd_label_loaded "$label"; then
            echo "$label"
        fi
    done
    return 0
}

bootout_label() {
    local label="$1"
    local plist="$HOME/Library/LaunchAgents/$label.plist"
    if launchd_label_loaded "$label"; then
        echo "  Booting out $label..."
        launchctl bootout "$LAUNCHD_DOMAIN/$label" 2>/dev/null || \
            launchctl bootout "$LAUNCHD_DOMAIN" "$plist" 2>/dev/null || true
    fi
}

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

remaining_minime_processes() {
    local parent_pid="${PPID:-}"
    ps -axo pid=,ppid=,command= | awk \
        -v self="$$" \
        -v parent="$parent_pid" '
        {
            pid = $1
            ppid = $2
            $1 = ""
            $2 = ""
            sub(/^ +/, "")
            cmd = $0
            if (pid == self || pid == parent) {
                next
            }
            if (cmd ~ /awk[[:space:]]+-v[[:space:]]+self=/) {
                next
            }
            if (cmd ~ /mlx_lm\.server|target\/release\/minime|autonomous_agent\.py|camera_to_sensory|camera_client|visual_frame_service|mic_to_sensory|host-sensory/) {
                print pid " " cmd
            }
        }'
}

terminate_matching_processes() {
    local name="$1"
    local pattern="$2"
    local pids
    pids="$(remaining_minime_processes | awk -v pattern="$pattern" '$0 ~ pattern {print $1}' | sort -u | tr '\n' ' ')"
    if [ -n "$pids" ]; then
        kill -TERM $pids 2>/dev/null && echo "  Stopped $name" || true
    fi
}

LOADED_LABELS="$(loaded_launchd_labels)"
if [ -n "$LOADED_LABELS" ] && [ "$MINIME_STOP_MANUAL_ONLY" != "1" ] && [ "$MINIME_STOP_MANUAL_ONLY" != "true" ]; then
    echo "Launchd-managed Minime labels detected; stopping through launchctl bootout."
    echo "$LOADED_LABELS" | sed 's/^/  - /'
    echo ""
    echo "Use this to restore the launchd-managed Minime stack:"
    echo "  bash $ASTRID_START_ALL --minime-only"
    echo "Use this for a full coupled-stack shutdown:"
    echo "  bash $ASTRID_STOP_ALL"
    echo ""
    for label in "${MINIME_LAUNCHD_LABELS[@]}"; do
        bootout_label "$label"
    done
    echo ""
fi

# Step 1: Stop camera/sensory services
echo "[1/5] Stopping sensory services..."
stop_by_pid_file "host-sensory" "$PID_DIR/host.pid"
stop_by_pid_file "visual-frame-service" "$PID_DIR/visual.pid"
stop_by_pid_file "mic" "$PID_DIR/mic.pid"
stop_by_pid_file "camera" "$PID_DIR/camera.pid"
terminate_matching_processes "host-sensory" "host-sensory"
terminate_matching_processes "mic_to_sensory" "mic_to_sensory.py"
terminate_matching_processes "camera_to_sensory" "camera_to_sensory.py"
terminate_matching_processes "camera_client" "camera_client.py"
terminate_matching_processes "visual_frame_service" "visual_frame_service.py"
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
terminate_matching_processes "autonomous_agent" "autonomous_agent.py"

# Step 4: Stop Rust engine
echo ""
echo "[4/5] Stopping Rust spectral engine..."
stop_by_pid_file "engine" "$PID_DIR/engine.pid"
terminate_matching_processes "Rust spectral engine" "target/release/minime"

sleep 2

# Step 5: Stop MLX server
echo ""
echo "[5/5] Stopping MLX server..."
stop_by_pid_file "mlx" "$PID_DIR/mlx.pid"
terminate_matching_processes "MLX server" "mlx_lm.server"

sleep 2

# Cleanup PID directory
rm -rf "$PID_DIR" 2>/dev/null

# Verify
echo ""
echo "=== Verification ==="
REMAINING_LINES="$(remaining_minime_processes || true)"
REMAINING=$(printf '%s\n' "$REMAINING_LINES" | awk 'NF' | wc -l | tr -d ' ')

if [ "$REMAINING" -eq 0 ]; then
    echo "All Minime processes stopped."
else
    echo "WARNING: $REMAINING process(es) still running:"
    printf '%s\n' "$REMAINING_LINES" | sed 's/^/  /'
fi

echo ""
echo "Shutdown complete."
