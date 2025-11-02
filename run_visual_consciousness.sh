#!/bin/bash
# run_visual_consciousness.sh - Start MikesSpatialMind with visual consciousness
# Auto-detects USB camera and processes at 1 FPS (contemplative mode)

# Clean queue before starting
echo "🧹 Cleaning thoughts queue..."
rm -rf thoughts_queue
mkdir -p thoughts_queue
echo ""

# Start visual consciousness using standalone Python script
# Use --camera 0 for first camera (1280x720 Microsoft LifeCam)
# Use --camera 1 for second camera (1920x1080 FaceTime HD)
python3 visual_consciousness.py --fps 1.0 --mode research --camera 0
