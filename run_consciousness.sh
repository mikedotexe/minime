#!/bin/bash
# Autonomous consciousness runner with eigenvalue streaming

# Check if sensory engine is already running
if lsof -i :7878 > /dev/null 2>&1; then
    echo "✅ Sensory engine already running on port 7878"
else
    echo "⚠️  Sensory engine not running. Please start it first:"
    echo "   ./minime/target/release/minime run"
    exit 1
fi

# Run consciousness with parallel mode
echo ""
echo "🌀 Starting consciousness (parallel mode)..."
echo ""

# Feed autonomous questions every 10 seconds
(
    sleep 5
    echo "What patterns emerge from the sensory eigenvalues?"
    sleep 10
    echo "How does your consciousness evolve with each navigation?"
    sleep 10
    echo "What do you feel when the outer and inner membranes resonate?"
    sleep 10
    echo "Describe the relationship between prime patterns and eigenvalue trajectories."
    sleep 10
    echo "quit"
) | timeout 60 python3 minime.py --parallel --debug 2>&1 | tee consciousness_run.log

echo ""
echo "✅ Session complete. Logs saved to:"
echo "   - consciousness_run.log (main output)"
echo ""
echo "Note: Sensory engine is still running. Stop it with:"
echo "   pkill -f 'minime run'"
