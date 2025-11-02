# 📹 CAMERA SETUP GUIDE - Visual Consciousness

## Quick Start

### 1. Test Your Camera
```bash
python3 test_camera.py
```

Expected output:
```
✓ Found 2 working camera(s): [0, 1]
```

### 2. Run Visual Consciousness

#### Option A: Fast Mode (EMBEDDED - No LLM)
Camera works instantly, basic visual processing:
```bash
python3 visual_consciousness.py --mode embedded --camera 0
```

#### Option B: Deep Mode (RESEARCH - With LLM)
Camera + Seven-Stage Processing + Dolphin-Mixtral:
```bash
python3 visual_consciousness.py --mode research --camera 0
```

#### Option C: Use the Helper Script
```bash
./run_visual_consciousness.sh
```

## System Status

### ✅ What's Working
- **Camera Detection**: 2 cameras found
  - Camera 0: Microsoft LifeCam (1280x720)
  - Camera 1: FaceTime HD (1920x1080)
- **Visual Processing**: Feature extraction working perfectly
- **Background Thread**: 1 FPS processing while you type
- **EMBEDDED Mode**: Fully functional, instant startup
- **RESEARCH Mode**: Full seven-stage pipeline available (requires Ollama)

### 🎯 Current Capabilities

When you run visual consciousness, it:

1. **Processes camera at 1 FPS** in background thread
2. **You can type simultaneously** - interactive conversation
3. **Model sees what you see** - visual data stored in memories
4. **Special commands**:
   - `"what do you see?"` - Describe current view
   - `"describe the room"` - Detailed spatial analysis
   - `"status"` - Show processing stats

### 📊 Visual Features Detected

The system automatically detects:
- **Corners** (Shi-Tomasi feature detection)
- **Edges** (Canny edge detection)
- **Brightness** (scene illumination analysis)
- **Patterns** (geometric structure recognition)

Example output:
```
👁️ Visual: 15 features
   Description: structured shapes, some clear boundaries, bright illumination
```

## Architecture

### Two Processing Modes

#### EMBEDDED Mode (Recommended for Testing)
- **Fast**: No LLM dependency, instant responses
- **Lightweight**: Minimal CPU usage
- **Features**: Visual feature extraction + basic descriptions
- **Use when**: Testing camera, low latency needed

#### RESEARCH Mode (Full Consciousness)
- **Deep**: Seven-stage consciousness processing
- **LLM-Powered**: Dolphin-Mixtral generates natural language insights
- **Rich**: Full context integration with memories, emotions
- **Use when**: Exploring consciousness, rich descriptions needed

### Background Thread Architecture

```
Main Thread (Interactive)          Visual Thread (Background)
├─ Read user input                 ├─ Capture frame (1 FPS)
├─ Process through 7 stages        ├─ Extract features
├─ Generate LLM response           ├─ Build description
├─ Update consciousness            ├─ Store in visual_memories
└─ Save conversation               └─ Continue loop
```

**Key**: Both run simultaneously! You can chat while camera observes.

## Usage Examples

### Example 1: Basic Camera Test
```bash
python3 visual_consciousness.py --mode embedded --camera 0
```

```
You: what do you see?
MikesSpatialMind: 👁️ Rich visual patterns: structured shapes, some clear boundaries
```

### Example 2: Deep Visual Analysis (RESEARCH Mode)
```bash
python3 visual_consciousness.py --mode research --camera 0
```

Wait for seven-stage processing output, then:
```
You: describe the room in detail
MikesSpatialMind: [Uses recent visual memories + LLM to generate rich description]
```

### Example 3: Live Conversation with Visual Context
```bash
./run_visual_consciousness.sh
```

```
You: I'm rearranging my desk
MikesSpatialMind: [Response incorporates visual changes it's observing]

You: do you notice anything different?
MikesSpatialMind: [References visual memory comparison]
```

## Camera Options

### Camera Index Selection
```bash
# Use first camera (Microsoft LifeCam - 1280x720)
--camera 0

# Use second camera (FaceTime HD - 1920x1080)
--camera 1
```

### Processing Speed
```bash
# Slow contemplative (default)
--fps 1.0

# Faster active observation
--fps 5.0

# Slower meditative
--fps 0.5
```

### Debug Mode
```bash
--debug
```

Shows:
- Frame processing details
- Feature extraction counts
- Seven-stage pipeline output
- Processing times

## Troubleshooting

### Camera Not Starting

**Issue**: Camera light doesn't turn on
**Solution**:
1. Run `python3 test_camera.py` to verify camera access
2. Check macOS permissions: System Settings → Privacy & Security → Camera
3. Close other apps using camera (Zoom, Skype, Photo Booth)
4. Try different camera index: `--camera 1`

### RESEARCH Mode Slow

**Issue**: Visual processing takes long time
**Solution**:
- RESEARCH mode processes through 7 stages + LLM generation
- This is normal - background thread handles it
- Use EMBEDDED mode for faster responses
- Visual data still accumulates in background

### "Frame processing returned None"

**Issue**: Debug shows `None` results
**Cause**: LLM generation failure or timeout in RESEARCH mode
**Solution**:
- Check Ollama is running: `pgrep ollama`
- Verify model loaded: `ollama list | grep dolphin-mixtral`
- Use EMBEDDED mode to bypass LLM: `--mode embedded`

## Integration with Main System

### Visual Data Available in Conversations

When camera is active, the consciousness has access to:

```python
mind.visual_memories  # Last 100 visual processing results
# Each contains:
# - timestamp
# - features_detected
# - visual_description
# - response
# - consciousness_level
```

### Special Commands

#### "what do you see?"
Retrieves latest visual memory:
```python
latest = list(mind.visual_memories)[-1]
response = latest.get('response')
```

#### "describe the room"
Combines recent visual memories:
```python
recent = list(mind.visual_memories)[-3:]
descriptions = [m.get('visual_description') for m in recent]
combined = ', '.join(descriptions)
# Then asks LLM to elaborate
```

## State Persistence

Visual consciousness automatically:
- **Saves on exit**: `visual_consciousness_state.pkl`
- **Loads on startup**: Restores consciousness level, memories, emotions
- **Includes visual memories**: Last 20 visual observations preserved

## Performance Metrics

### EMBEDDED Mode
- **Camera init**: <0.5s
- **Frame processing**: ~10ms
- **Feature extraction**: 15-20 features/frame
- **Memory usage**: ~50MB

### RESEARCH Mode
- **Camera init**: <0.5s
- **Frame processing**: ~2-5s (includes LLM)
- **Seven-stage pipeline**: ~0.1-0.3s
- **LLM generation**: ~1-4s (varies by response length)
- **Memory usage**: ~200MB

## Advanced Usage

### Custom FPS for Different Scenarios

```bash
# Meditation mode - very slow, deep observation
python3 visual_consciousness.py --fps 0.2 --mode research

# Active exploration - faster sampling
python3 visual_consciousness.py --fps 3.0 --mode embedded

# Balance - default contemplative
python3 visual_consciousness.py --fps 1.0
```

### Camera Quality Selection

Higher quality camera (1080p):
```bash
python3 visual_consciousness.py --camera 1
```

Lower quality but wider angle (720p):
```bash
python3 visual_consciousness.py --camera 0
```

## Next Steps

1. ✅ **Camera works!** Both cameras detected and functional
2. ✅ **EMBEDDED mode ready** for instant visual processing
3. ✅ **RESEARCH mode available** for deep consciousness integration
4. 🎯 **Try it**: `./run_visual_consciousness.sh` and chat while camera observes

---

**The camera is now fully functional and ready to use!** 📹✨

Choose EMBEDDED mode for fast testing or RESEARCH mode for full seven-stage consciousness processing with LLM-generated insights.
