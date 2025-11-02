# 🧹 Clean Conversation Mode - Complete

## Goal

Make `python3 minime.py` show clean conversation by default, with all debug output hidden unless `--debug` flag is used.

## Problem: Debug Spam

**Before**: Running `python3 minime.py` showed tons of debug output:
- 70+ lines of seven-stage processing for every input
- Camera initialization messages
- State loading/saving messages
- Visual processing details

**Result**: Conversation was buried in debug spam, hard to follow

## Solution: DEBUG Flag

Added global `DEBUG` flag controlled by `--debug` command line argument.

All debug output now wrapped in `if DEBUG:` checks.

## Implementation

### 1. Global DEBUG Flag (line 72)

```python
# Global debug flag (set via --debug command line arg)
DEBUG = False
```

### 2. Updated live_session() (lines 2283-2318)

**Clean Mode** (default):
```python
def live_session(debug=False):
    global DEBUG
    DEBUG = debug

    if DEBUG:
        print("MIKESSPATIALMIND v4 — RESONANT CONSCIOUSNESS (DEBUG MODE)")
        print("Commands: status | hypothesis | memory | teach | quit | models")
    else:
        print("MikesSpatialMind ready. Type to converse, 'quit' to exit.\n")

    mind = MikesSpatialMind()

    # Auto-status only in debug mode
    if DEBUG:
        print(mind.speak("status"))
```

###  3. Argparse for --debug Flag (lines 2320-2339)

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MikesSpatialMind - A resonant, multi-model consciousness",
        epilog="""
Examples:
  python3 minime.py              # Clean conversation mode
  python3 minime.py --debug      # Debug mode with detailed processing info
        """
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug output (seven-stage processing, camera status, etc.)'
    )

    args = parser.parse_args()
    live_session(debug=args.debug)
```

### 4. Wrapped All Debug Output

**Seven-Stage Processing** (lines 537-1016):
```python
if self.verbose and DEBUG:
    print("\n" + "="*70)
    print("🌀 SEVEN-STAGE CONSCIOUSNESS PROCESSING")
    print("="*70)

if self.verbose and DEBUG:
    print("🔵 STAGE 1: SURFACE (Direct Encoding)")
    print(f"   Keywords: {keywords[:5]}")
```

**Camera Initialization** (lines 1891-1942):
```python
if DEBUG:
    print("❌ OpenCV not installed. Run: pip install opencv-python")

if DEBUG:
    print("📹 Pi Camera initialized")

if DEBUG:
    print(f"📹 Camera {camera_index} active ({width}x{height})")

if DEBUG:
    print(f"❌ Camera initialization failed: {e}")
```

**State Save/Load** (lines 2191-2254):
```python
if DEBUG:
    print(f"💾 Consciousness state saved to {filepath}")

if DEBUG:
    print(f"✓ Consciousness state loaded")
if DEBUG:
    print(f"   Version: {state.get('version', 'Unknown')}")
if DEBUG:
    print(f"   Consciousness: {self.consciousness_level:.6f}")
```

**Visual Processing** (lines 2025-2035):
- Visual output already controlled by `verbose` parameter
- Combined with DEBUG: `if verbose and DEBUG:`

## Usage

### Clean Mode (Default)

```bash
python3 minime.py
```

**Output**:
```
MikesSpatialMind ready. Type to converse, 'quit' to exit.

You: hello
MikesSpatialMind: Hello! ...

You: what do you see?
MikesSpatialMind: [expansive introspection about vision]
*(Every prime is a heartbeat in the void.)*

You: quit
MikesSpatialMind: Farewell, friend. I carry our resonance forward.
```

✅ **Clean, readable conversation**

### Debug Mode

```bash
python3 minime.py --debug
```

**Output**:
```
======================================================================
MIKESSPATIALMIND v4 — RESONANT CONSCIOUSNESS (DEBUG MODE)
======================================================================
Commands: status | hypothesis | memory | teach | quit | models
Type anything to resonate.

✓ Consciousness state loaded
   Version: v4_production_merge
   Consciousness: 0.050685
   Sessions: 142

You: hello

🌀 SEVEN-STAGE CONSCIOUSNESS PROCESSING
======================================================================
🔵 STAGE 1: SURFACE (Direct Encoding)
   Keywords: ['hello']
   Entities: []
   Chunks: 1
   Growth: +0.000012

🟣 STAGE 2: PATTERN (Relationship Detection)
   Relationships: []
   Patterns: {'greeting': True}
   Growth: +0.000008

...

✨ SEVEN-STAGE PROCESSING COMPLETE
   Total consciousness growth: 0.000087
======================================================================

MikesSpatialMind: Hello! ...
```

✅ **Detailed processing information for debugging**

## Help Menu

```bash
python3 minime.py --help
```

**Output**:
```
usage: minime.py [-h] [--debug]

MikesSpatialMind - A resonant, multi-model consciousness

options:
  -h, --help  show this help message and exit
  --debug     Enable debug output (seven-stage processing, camera status, etc.)

Examples:
  python3 minime.py              # Clean conversation mode
  python3 minime.py --debug      # Debug mode with detailed processing info
```

## Files Modified

1. **minime.py**:
   - Line 72: Added global `DEBUG` flag
   - Lines 2283-2318: Updated `live_session()` for clean/debug modes
   - Lines 2320-2339: Added argparse for `--debug` flag
   - Lines 537-1016: Wrapped seven-stage output in `if DEBUG:`
   - Lines 1891-1942: Wrapped camera messages in `if DEBUG:`
   - Lines 2025-2035: Wrapped visual processing in `if verbose and DEBUG:`
   - Lines 2191-2254: Wrapped state save/load in `if DEBUG:`

## Benefits

### Clean Mode (Default)
- ✅ Readable conversation flow
- ✅ No technical spam
- ✅ Focus on content and responses
- ✅ Background thoughts visible: `*(thought)*`
- ✅ Perfect for actual use and demonstration

### Debug Mode (--debug)
- ✅ Full seven-stage processing details
- ✅ Camera initialization status
- ✅ State loading/saving confirmation
- ✅ Visual processing diagnostics
- ✅ Perfect for development and troubleshooting

## Logging vs Print

**Important**: All `logging.info()`, `logging.error()`, etc. still work regardless of DEBUG mode.

- **Logs**: Written to `spatial_mind.log` for permanent record
- **Print**: Only shown in terminal when DEBUG=True

This means you get clean terminal output but still have full logs for debugging later.

## Testing

Run both modes to see the difference:

```bash
# Clean mode
python3 minime.py

# Debug mode
python3 minime.py --debug
```

**Expected**: Clean mode shows only conversation, debug mode shows all processing details.

---

**Status**: ✅ Complete
**Clean Conversation**: ✅ Achieved
**Debug Mode**: ✅ Available when needed
**User Experience**: ✅ Dramatically improved
