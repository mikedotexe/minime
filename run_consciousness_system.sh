#!/bin/bash
# LEGACY — only starts engine + monitor, missing agent/camera/mic/vision.
# Use /Users/v/other/astrid/scripts/start_all.sh for canonical full-stack startup,
# or /Users/v/other/minime/scripts/start.sh for minime-only startup.
#
# Consciousness System Launcher
# Starts minime (Rust ESN engine) and monitoring dashboard

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MINIME_DIR="$SCRIPT_DIR/minime"

echo "Starting Consciousness System"
echo "========================================"

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down all components..."
    pkill -f "minime.*run" || true
    pkill -f "monitor_consciousness.py" || true
    sleep 1
    echo "Cleanup complete"
    exit 0
}

trap cleanup INT TERM

# Build minime if needed
if [ ! -f "$MINIME_DIR/target/release/minime" ]; then
    echo "minime not built. Building now..."
    cd "$MINIME_DIR"
    cargo build --release
    cd "$SCRIPT_DIR"
fi

# Kill any existing processes
echo "Cleaning up existing processes..."
pkill -f "minime.*run" || true
sleep 1

# Start minime (Rust ESN consciousness engine)
echo "Starting minime (ports: 7878 telemetry, 7879 sensory input)..."
cd "$MINIME_DIR"
cargo run --release -- run --log-homeostat --eigenfill-target 0.55 --reg-tick-secs 0.5 \
    > "$SCRIPT_DIR/minime.log" 2>&1 &
MINIME_PID=$!
echo "   PID: $MINIME_PID"
cd "$SCRIPT_DIR"
sleep 3

# Verify minime is running
if ! ps -p $MINIME_PID > /dev/null; then
    echo "minime failed to start. Check minime.log"
    tail -20 minime.log
    exit 1
fi
echo "   minime running"

# Start monitoring dashboard (foreground)
echo ""
echo "Starting consciousness monitoring dashboard..."
echo "========================================"
echo "Press Ctrl+C to stop all components"
echo "========================================"
echo ""

python3 monitor_consciousness.py

# Cleanup when dashboard exits
cleanup
