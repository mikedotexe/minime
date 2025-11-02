#!/bin/bash
# Start Speech I/O Service
# Whisper STT + Piper TTS with barge-in detection

echo "🎙️ Starting Speech I/O Service..."
echo

cd speech-io || {
    echo "❌ speech-io directory not found"
    echo "   Run from mikeconsciousness/ root directory"
    exit 1
}

# Check if built
if [ ! -f "target/release/speech-io" ]; then
    echo "Building speech-io (release mode)..."
    cargo build --release || {
        echo "❌ Build failed"
        exit 1
    }
fi

# Model paths (update these to your actual model locations)
STT_MODEL="${STT_MODEL:-$HOME/models/ggml-large-v3.bin}"
PIPER_MODEL="${PIPER_MODEL:-$HOME/models/en_US-lessac-medium.onnx}"

# Check if models exist
if [ ! -f "$STT_MODEL" ]; then
    echo "⚠️  Whisper model not found: $STT_MODEL"
    echo "   Download from: https://huggingface.co/ggerganov/whisper.cpp"
    echo "   Or set STT_MODEL environment variable"
    exit 1
fi

if [ ! -f "$PIPER_MODEL" ]; then
    echo "⚠️  Piper model not found: $PIPER_MODEL"
    echo "   Download from: https://github.com/rhasspy/piper/releases"
    echo "   Or set PIPER_MODEL environment variable"
    exit 1
fi

echo "Starting speech-io on ws://127.0.0.1:7242"
echo "  - STT: $STT_MODEL"
echo "  - TTS: $PIPER_MODEL"
echo "  - Barge-in detection enabled"
echo

# Start service
./target/release/speech-io \
    --stt-model "$STT_MODEL" \
    --piper-model "$PIPER_MODEL" \
    --bind 127.0.0.1:7242

# Optional parameters:
#   --vad-threshold 0.02      # Voice activity detection threshold
#   --min-voice-ms 180        # Minimum voice duration
#   --end-silence-ms 600      # Silence duration to end segment
#   --max-segment-s 30.0      # Maximum segment duration
#   --lang en                 # Language code
