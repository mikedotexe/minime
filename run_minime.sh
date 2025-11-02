#!/bin/bash

# run_minime.sh - Continuous runner for MikesSpatialMind
# This script will run minime.py in a loop, restarting it automatically
# Press Ctrl+C to stop

echo "========================================"
echo "MikesSpatialMind Continuous Runner"
echo "========================================"
echo "Press Ctrl+C to stop"
echo ""

# Trap Ctrl+C to exit gracefully
trap 'echo -e "\n\nShutting down runner. The patterns rest.\n"; exit 0' INT

# Counter for tracking runs
RUN_COUNT=0

while true; do
    RUN_COUNT=$((RUN_COUNT + 1))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting run #${RUN_COUNT}..."
    echo "----------------------------------------"

    # Clean queue before each run to prevent corruption
    echo "Cleaning thoughts queue..."
    rm -rf thoughts_queue
    mkdir -p thoughts_queue

    # Run the Python script
    python3 minime.py

    # Capture exit code
    EXIT_CODE=$?

    echo ""
    echo "----------------------------------------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Run #${RUN_COUNT} ended (exit code: ${EXIT_CODE})"

    # If it crashed immediately, add a longer delay to prevent runaway loops
    if [ "$EXIT_CODE" -ne 0 ]; then
        echo "⚠️  Non-zero exit detected. Waiting 5 seconds before restart..."
        sleep 5
    else
        echo "Restarting in 2 seconds..."
        sleep 2
    fi

    echo ""
done
