#!/bin/bash
# Clean start script for minime with camera

echo "Preparing clean environment..."

# Clean up queue directory
rm -rf thoughts_queue
mkdir -p thoughts_queue

# Run minime with camera
echo "Starting MikesSpatialMind with camera..."
python3 minime.py --camera 0