#!/bin/bash

# Deployment script for Raspberry Pi

if [ $# -ne 1 ]; then
    echo "Usage: $0 <raspberry-pi-address>"
    echo "Example: $0 pi@192.168.1.100"
    exit 1
fi

RPI_HOST=$1
MODEL_FILE="tinyllama-nvfp4-rpi.gguf"

echo "Deploying TinyLlama to Raspberry Pi at $RPI_HOST"

# Check if model exists
if [ ! -f "$MODEL_FILE" ]; then
    echo "Error: Model file $MODEL_FILE not found"
    echo "Please run conversion first"
    exit 1
fi

# Create directory on RPi
ssh $RPI_HOST "mkdir -p ~/tinyllama"

# Copy model
echo "Copying model file..."
scp $MODEL_FILE $RPI_HOST:~/tinyllama/

# Copy test script
echo "Copying test script..."
scp test_tinyllama.py $RPI_HOST:~/tinyllama/

# Create run script for RPi
cat > run_on_rpi.sh << 'SCRIPT'
#!/bin/bash
cd ~/tinyllama

# Install dependencies if needed
pip3 install psutil numpy

# Run Ollama with limited resources
export OLLAMA_NUM_THREADS=4
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_MEMORY_LIMIT=1GB

# Load model
ollama create tinyllama:nvfp4 -f tinyllama-nvfp4-rpi.gguf

# Run test
python3 test_tinyllama.py
SCRIPT

# Copy and run
scp run_on_rpi.sh $RPI_HOST:~/tinyllama/
ssh $RPI_HOST "chmod +x ~/tinyllama/run_on_rpi.sh"

echo "Deployment complete!"
echo "To run on Raspberry Pi: ssh $RPI_HOST '~/tinyllama/run_on_rpi.sh'"
