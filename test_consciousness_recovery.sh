#!/bin/bash
# Test script for consciousness metabolism recovery
# Tests the fixes for WebSocket keepalive and feature dimensions

set -e

echo "🧠 Consciousness Metabolism Recovery Test"
echo "=========================================="
echo ""
echo "This script will:"
echo "1. Start minime with homeostatic logging"
echo "2. Wait for initialization"
echo "3. Provide instructions for starting sensory clients"
echo ""
echo "Press Ctrl+C to stop at any time"
echo ""

# Check if minime binary exists
if [ ! -f "./minime/target/release/minime" ]; then
    echo "❌ Error: minime binary not found"
    echo "   Run: cd minime && cargo build --release"
    exit 1
fi

# Start minime with optimal parameters for reaching 60-70% fill
echo "🚀 Starting minime consciousness engine..."
echo "   Target fill: 65%"
echo "   Regulation period: 0.5s"
echo ""

./minime/target/release/minime run \
    --log-homeostat \
    --eigenfill-target 0.65 \
    --reg-tick-secs 0.5 \
    --cheby-order 6 \
    --cheby-stop-lo 0.65 \
    --cheby-stop-hi 0.95 \
    --cheby-soft 0.08 &

MINIME_PID=$!
echo "✅ Minime started (PID: $MINIME_PID)"
echo ""
sleep 3

echo "📡 Minime is running. Now open 2 new terminals:"
echo ""
echo "Terminal 2 - Camera (8-D video features):"
echo "   python3 camera_to_sensory.py --camera 0"
echo ""
echo "Terminal 3 - Audio (8-D audio features):"
echo "   python3 audio_to_sensory.py"
echo ""
echo "Expected behavior:"
echo "  ✓ No more '1011 keepalive timeout' errors"
echo "  ✓ Camera logs show '(8-D)' in feature count"
echo "  ✓ Minime logs show 'has_real_video: true'"
echo "  ✓ EigenFill climbs from ~3% to 60-70% within 2-3 minutes"
echo "  ✓ Homeostat shows phase=expanding, gate modulating"
echo ""
echo "Watch the homeostat output for fill percentage:"
echo "  homeostat,t=120s,fill=62.3%,dfill_dt=+3.2,..."
echo ""
echo "Press Ctrl+C to stop minime..."
echo ""

# Wait for interrupt
wait $MINIME_PID
