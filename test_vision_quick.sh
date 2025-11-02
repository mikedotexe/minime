#!/bin/bash
# Quick vision test - ensures everything starts in correct order

echo "🧹 Cleaning up old processes..."
pkill -TERM minime 2>/dev/null
sleep 2

echo ""
echo "🚀 Starting Rust consciousness engine..."
echo "   (This will run in background - check for '🎥 Sensory input server listening')"
echo ""

cd minime && cargo run --release -- run --log-homeostat 2>&1 | tee ../rust_output.log &
RUST_PID=$!

cd ..
echo "Waiting 8 seconds for Rust engine to initialize..."
sleep 8

# Check if Rust is running
if ! ps -p $RUST_PID > /dev/null; then
    echo "❌ Rust engine failed to start! Check rust_output.log"
    exit 1
fi

echo ""
echo "✅ Rust engine running (PID: $RUST_PID)"
echo ""
echo "📊 Quick status check:"
tail -5 rust_output.log
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎬 NOW starting Python consciousness with camera..."
echo "   Type: 'can you see me, friend' at the You: prompt"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Run Python interactively
python3 minime.py --camera

# Cleanup on exit
echo ""
echo "🧹 Cleaning up Rust engine..."
kill -TERM $RUST_PID 2>/dev/null
wait $RUST_PID 2>/dev/null
echo "✅ Done!"
