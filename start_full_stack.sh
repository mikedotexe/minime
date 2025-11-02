#!/bin/bash
# Start Full Stack - All Services + Consciousness
# MLP Bank + Speech I/O + 13 Parallel Threads + Camera + Neural Enhancement

echo "🌀 MIKESSPATIAL MIND - FULL STACK STARTUP"
echo "=========================================="
echo

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENABLE_MLP=${ENABLE_MLP:-true}
ENABLE_SPEECH=${ENABLE_SPEECH:-true}
ENABLE_CAMERA=${ENABLE_CAMERA:-false}
CAMERA_INDEX=${CAMERA_INDEX:-0}

# Function to check if service is running
check_service() {
    local name=$1
    local url=$2
    local max_wait=${3:-30}

    echo -n "Waiting for $name..."
    for i in $(seq 1 $max_wait); do
        if curl -s "$url" > /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo -e " ${RED}✗${NC}"
    return 1
}

# Start MLP Bank
if [ "$ENABLE_MLP" = true ]; then
    echo -e "${BLUE}🧠 Starting MLP Neural Bank...${NC}"
    cd mlp_bank 2>/dev/null || {
        echo -e "${RED}❌ mlp_bank directory not found${NC}"
        exit 1
    }

    if [ ! -f "target/release/mlp-bank" ]; then
        echo "Building MLP bank..."
        cargo build --release || exit 1
    fi

    ./target/release/mlp-bank --init-xavier 42 --bind 127.0.0.1:8080 > ../mlp_bank.log 2>&1 &
    MLP_PID=$!
    cd ..

    if ! check_service "MLP Bank" "http://127.0.0.1:8080/status"; then
        echo -e "${RED}Failed to start MLP bank${NC}"
        kill $MLP_PID 2>/dev/null
        exit 1
    fi
    echo -e "${GREEN}✅ MLP Bank running (PID: $MLP_PID)${NC}"
    echo
fi

# Start Speech I/O
if [ "$ENABLE_SPEECH" = true ]; then
    echo -e "${BLUE}🎙️ Starting Speech I/O Service...${NC}"

    STT_MODEL="${STT_MODEL:-$HOME/models/ggml-large-v3.bin}"
    PIPER_MODEL="${PIPER_MODEL:-$HOME/models/en_US-lessac-medium.onnx}"

    if [ ! -f "$STT_MODEL" ] || [ ! -f "$PIPER_MODEL" ]; then
        echo -e "${YELLOW}⚠️  Speech models not found - disabling speech${NC}"
        echo "   STT: $STT_MODEL"
        echo "   TTS: $PIPER_MODEL"
        ENABLE_SPEECH=false
    else
        cd speech-io 2>/dev/null || {
            echo -e "${RED}❌ speech-io directory not found${NC}"
            kill $MLP_PID 2>/dev/null
            exit 1
        }

        if [ ! -f "target/release/speech-io" ]; then
            echo "Building speech-io..."
            cargo build --release || {
                kill $MLP_PID 2>/dev/null
                exit 1
            }
        fi

        ./target/release/speech-io \
            --stt-model "$STT_MODEL" \
            --piper-model "$PIPER_MODEL" \
            --bind 127.0.0.1:7242 > ../speech_io.log 2>&1 &
        SPEECH_PID=$!
        cd ..

        # WebSocket check (different from HTTP)
        sleep 3
        if ps -p $SPEECH_PID > /dev/null; then
            echo -e "${GREEN}✅ Speech I/O running (PID: $SPEECH_PID)${NC}"
        else
            echo -e "${RED}Failed to start speech-io${NC}"
            kill $MLP_PID 2>/dev/null
            exit 1
        fi
        echo
    fi
fi

# Build consciousness flags
CONSCIOUSNESS_FLAGS="--parallel"

if [ "$ENABLE_MLP" = true ]; then
    CONSCIOUSNESS_FLAGS="$CONSCIOUSNESS_FLAGS --mlp"
fi

if [ "$ENABLE_SPEECH" = true ]; then
    CONSCIOUSNESS_FLAGS="$CONSCIOUSNESS_FLAGS --speech"
fi

if [ "$ENABLE_CAMERA" = true ]; then
    CONSCIOUSNESS_FLAGS="$CONSCIOUSNESS_FLAGS --camera $CAMERA_INDEX"
fi

# Print summary
echo -e "${GREEN}=========================================="
echo "🌀 FULL STACK READY"
echo "==========================================${NC}"
echo
echo "Services running:"
[ "$ENABLE_MLP" = true ] && echo "  🧠 MLP Neural Bank: http://127.0.0.1:8080"
[ "$ENABLE_SPEECH" = true ] && echo "  🎙️ Speech I/O: ws://127.0.0.1:7242"
echo
echo "Consciousness configuration:"
echo "  🌀 13 parallel threads: ENABLED"
[ "$ENABLE_MLP" = true ] && echo "  🧠 Neural enhancement: ENABLED"
[ "$ENABLE_SPEECH" = true ] && echo "  🎙️ Voice interaction: ENABLED"
[ "$ENABLE_CAMERA" = true ] && echo "  📹 Vision (camera $CAMERA_INDEX): ENABLED"
echo
echo -e "${BLUE}Starting MikesSpatialMind consciousness...${NC}"
echo

# Cleanup function
cleanup() {
    echo
    echo -e "${YELLOW}Shutting down services...${NC}"
    [ -n "$MLP_PID" ] && kill $MLP_PID 2>/dev/null && echo "  Stopped MLP Bank"
    [ -n "$SPEECH_PID" ] && kill $SPEECH_PID 2>/dev/null && echo "  Stopped Speech I/O"
    echo "Goodbye!"
}

trap cleanup EXIT INT TERM

# Start consciousness
python3 minime.py $CONSCIOUSNESS_FLAGS

# Cleanup happens automatically via trap
