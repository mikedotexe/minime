#!/bin/bash
# LEGACY — targets minime.py which is no longer the control surface.
# Use /Users/v/other/astrid/scripts/stop_all.sh for canonical shutdown,
# or /Users/v/other/minime/scripts/stop.sh for minime-only shutdown.
#
# Graceful shutdown of legacy Minime-related processes
# Following CLAUDE.md shutdown protocol

echo "=== Minime Process Cleanup ==="
echo ""

# Check what's running first
echo "Current running processes:"
ps aux | grep -E "(minime|camera_to_sensory|camera_client)" | grep -v grep | awk '{print $2, $11, $12, $13}'
echo ""

# Count processes
PROCESS_COUNT=$(ps aux | grep -E "(minime|camera_to_sensory|camera_client)" | grep -v grep | wc -l)
if [ "$PROCESS_COUNT" -eq 0 ]; then
    echo "No Minime processes running. System is clean."
    exit 0
fi

echo "Found $PROCESS_COUNT process(es) to stop."
echo ""

# Step 1: Stop camera services first
echo "[1/4] Stopping camera services..."
pkill -TERM -f camera_to_sensory.py
pkill -TERM -f camera_client.py

# Step 2: Wait for queues to drain
echo "[2/4] Waiting 5 seconds for queues to drain..."
sleep 5

# Step 3: Stop legacy Python frontend
echo "[3/4] Stopping legacy Python frontend..."
pkill -TERM -f "minime.py"

# Step 4: Stop Rust minime backend
echo "[4/4] Stopping Rust minime backend..."
pkill -TERM minime

# Final wait
echo ""
echo "Waiting 3 seconds for graceful shutdown..."
sleep 3

# Verify
echo ""
echo "Verifying cleanup..."
REMAINING=$(ps aux | grep -E "(minime|camera_to_sensory|camera_client)" | grep -v grep | wc -l)

if [ "$REMAINING" -eq 0 ]; then
    echo "SUCCESS: All processes stopped gracefully."
else
    echo "WARNING: $REMAINING process(es) still running:"
    ps aux | grep -E "(minime|camera_to_sensory|camera_client)" | grep -v grep | awk '{print $2, $11, $12, $13}'
    echo ""
    echo "You may need to use 'kill -9' for stubborn processes."
fi

echo ""
echo "Cleanup complete!"
