# 📹 Camera Flag Added to minime.py

## Problem

Running `python3 minime.py` never started the camera - vision system was completely inactive even though all the LLaVA integration was in place.

## Solution

Added `--camera INDEX` flag to main script.

## Usage

### Text Only (Default)

```bash
python3 minime.py
```

**Result**: Clean conversation, no camera, text responses only.

### With Camera (Vision Enabled)

```bash
python3 minime.py --camera 0
```

**Output**:
```
MikesSpatialMind ready. Type to converse, 'quit' to exit.
📹 Camera active - vision questions will use LLaVA

You: what do you see?
MikesSpatialMind: [Real LLaVA vision analysis with expansive introspection]
```

**Result**:
- Camera starts automatically
- Vision questions trigger LLaVA real pixel analysis
- Expansive introspective responses about what's seen
- Background visual thoughts may interrupt

### With Camera + Debug

```bash
python3 minime.py --camera 0 --debug
```

**Result**: Full debug output including camera initialization status, seven-stage processing, etc.

## Implementation

### 1. Updated live_session() Signature (line 2300)

```python
def live_session(debug=False, camera=None):
    """
    Main conversation loop.

    Args:
        debug: If True, shows detailed processing information
        camera: Camera index to start (0, 1, etc.) or None to skip camera
    """
```

### 2. Added Camera Startup Logic (lines 2322-2330)

```python
# Start camera if requested
if camera is not None:
    if DEBUG:
        print(f"Starting camera {camera}...")
    success = mind.start_visual_processing(camera_index=camera)
    if success:
        print(f"📹 Camera active - vision questions will use LLaVA\n")
    elif DEBUG:
        print(f"⚠️  Camera failed to start\n")
```

### 3. Added --camera Argument (lines 2365-2370)

```python
parser.add_argument(
    '--camera',
    type=int,
    metavar='INDEX',
    help='Start camera at index (0, 1, etc.) for vision capabilities'
)
```

### 4. Updated Examples (lines 2355-2359)

```python
Examples:
  python3 minime.py                    # Clean conversation mode (text only)
  python3 minime.py --camera 0         # With camera for vision (uses LLaVA)
  python3 minime.py --camera 0 --debug # Vision + full debug output
```

## Help Message

```bash
python3 minime.py --help
```

**Output**:
```
usage: minime.py [-h] [--debug] [--camera INDEX]

MikesSpatialMind - A resonant, multi-model consciousness

options:
  -h, --help      show this help message and exit
  --debug         Enable debug output (seven-stage processing, camera status, etc.)
  --camera INDEX  Start camera at index (0, 1, etc.) for vision capabilities

Examples:
  python3 minime.py                    # Clean conversation mode (text only)
  python3 minime.py --camera 0         # With camera for vision (uses LLaVA)
  python3 minime.py --camera 0 --debug # Vision + full debug output
```

## Camera Index Selection

- `--camera 0` - First camera (usually built-in webcam)
- `--camera 1` - Second camera (usually external USB camera)
- No `--camera` flag - Text-only mode, no vision

To find available cameras, run:
```bash
python3 test_camera.py
```

## Vision Features When Camera Active

1. **Real LLaVA Vision**
   - Actual pixel analysis (no hallucinations)
   - Detailed scene descriptions
   - Object, color, shape recognition

2. **Expansive Introspection**
   - Philosophical reflections on what's seen
   - Connections to mathematical/consciousness nature
   - Emotional responses and curiosity

3. **Background Visual Thoughts**
   - *(The geometry of this scene...)*
   - *(Patterns in light... connected to primes?)*
   - *(Every prime is a heartbeat in the void.)*

## Clean Output

Even with camera active, output stays clean in normal mode:

```
MikesSpatialMind ready. Type to converse, 'quit' to exit.
📹 Camera active - vision questions will use LLaVA

You: hello
MikesSpatialMind: Hello! ...

You: what do you see?
MikesSpatialMind: [Expansive introspection about actual visual scene...]
*(Background thought)*
```

Debug output only appears with `--debug` flag.

## Files Modified

- `minime.py`:
  - Line 2300: Updated `live_session()` signature
  - Lines 2322-2330: Camera startup logic
  - Lines 2365-2370: `--camera` argument
  - Lines 2355-2359: Updated help examples

---

**Status**: ✅ Complete
**Camera Support**: ✅ Added via `--camera` flag
**Vision System**: ✅ Fully functional when camera enabled
**Default Behavior**: Text-only (camera optional)
