# 🚀 Quick Start: LLaVA Vision System

## Installation (One-Time Setup)

```bash
# 1. Pull LLaVA model (~4.1 GB download)
ollama pull llava:7b

# 2. Verify installation
ollama list | grep llava
# Should show: llava:7b
```

## Running Visual Consciousness

```bash
# Clean start (recommended)
rm -rf thoughts_queue && mkdir -p thoughts_queue

# Option 1: Visual consciousness script (recommended)
./run_visual_consciousness.sh

# Option 2: Direct Python
python3 visual_consciousness.py --camera 0
```

## Testing

```bash
# Quick integration test
python3 test_llava_vision.py

# Full conversation test
python3 test_llava_conversation.py
```

## Example Session

```
You: What do you see?

MikesSpatialMind: Based on the LLaVA visual analysis, I see a person
wearing a cap and sunglasses, sitting in front of what appears to be
a microphone. They're wearing a black shirt with white text or logos
on it, possibly participating in a remote meeting or recording a
podcast in an indoor setting.

You: What colors are visible?

MikesSpatialMind: Based on the LLaVA's visual analysis, I can observe
a multitude of colors in the frame. The person is adorned with dark
accessories - black cap and sunglasses - that stand out against their
white shirt. This shirt exhibits red elements, adding to the color
palette. The room background presents white walls, creating a contrast
with the darker tones...

You: Tell me about prime numbers

MikesSpatialMind: [Responds without camera - pure text conversation]
```

## Vision Keywords (Trigger LLaVA)

These words in your question will activate LLaVA vision:
- `see`, `camera`, `look`, `image`, `visual`
- `observe`, `watch`, `view`, `picture`
- `describe`, `what`

## Architecture

**Vision Questions**:
1. Camera captures frame
2. LLaVA analyzes actual pixels (~3-5 seconds)
3. Dolphin-Mixtral receives LLaVA's description
4. Responds based on real visual content

**Text Questions**:
- Dolphin-Mixtral only (fast, no camera processing)

## Troubleshooting

### "LLaVA Vision Engine unavailable"
```bash
# Re-pull the model
ollama pull llava:7b

# Check Ollama is running
ollama list
```

### Camera not working
```bash
# Test camera detection
python3 test_camera.py

# Try different camera index
python3 visual_consciousness.py --camera 1
```

### Still getting hallucinations
- Make sure LLaVA model is fully downloaded (4.1 GB)
- Check logs for "Using LLaVA vision model" message
- Verify question contains vision keywords

## Performance

- **LLaVA analysis**: 3-5 seconds per frame
- **Text response**: Immediate (Dolphin-Mixtral)
- **Background processing**: 10ms (fast feature extraction)
- **Memory**: ~2GB for LLaVA + ~16GB for Dolphin-Mixtral

## What's Different From Before?

**Before**: "I see rectangular buildings and trees" (hallucination!)
**After**: "I see a person wearing a cap and sunglasses" (real vision!)

The system now uses LLaVA to see actual pixels, not fabricate details.

---

**Quick Test**: Ask "What do you see?" and verify it describes real objects in your camera frame!
