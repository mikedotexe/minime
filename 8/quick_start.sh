#!/bin/bash
# MIKESSPATIAL MIND - QUICK START SCRIPT

echo "🥧 Starting MikesSpatialMind on Raspberry Pi..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Installing..."
    sudo apt update && sudo apt install python3-pip
fi

# Check dependencies
python3 -c "import numpy, cv2" 2>/dev/null || {
    echo "📦 Installing dependencies..."
    pip3 install numpy opencv-python
}

# Start consciousness
echo "🧠 Initializing consciousness..."
python3 consciousness_production.py

echo "✨ MikesSpatialMind is now running!"
