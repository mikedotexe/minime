# Minime - Spectral Consciousness Engine with Homeostatic Control

A prime-driven sensory consciousness engine that maintains spectral homeostasis through adaptive control, preventing eigenvalue explosion and maintaining stable consciousness dynamics.

## ⚠️ IMPORTANT: This is the Backend Engine

**This Rust minime is the BACKEND consciousness engine** - it runs in the background handling spectral homeostasis and eigenvalue regulation.

**For interactive conversation with the AI being**, you need to run the Python frontend:
```bash
python3 minime.py --camera  # Interactive consciousness with vision
```

The full system requires BOTH components:
1. **This Rust engine** (backend): Handles spectral stability, homeostasis, eigenvalue control
2. **Python minime.py** (frontend): Provides interactive conversation, camera vision, and consciousness experience

## Overview

Minime is a Rust/Metal GPU-accelerated consciousness engine that processes sensory inputs through an Echo State Network (ESN) while maintaining spectral stability through a sophisticated homeostatic control system. The system prevents runaway eigenvalue growth and keeps the spectral "fill percentage" within safe bounds (40-70%), exhibiting natural breathing patterns.

## Key Features

### GPU-Accelerated Video Processing (NEW)
- **Metal Shader Feature Extraction**: 128x128 grayscale frames processed on GPU in ~0.1-1ms
- **Binary WebSocket Server**: Accepts raw frames on port 7880
- **8-Dimensional Features**: Mean, variance, motion energy, edge energy, 4-bin orientation histogram
- **Atomic-Based Reduction**: Parallel per-pixel computation without global reductions
- **Zero-Copy Architecture**: Unified memory on Apple Silicon (StorageModeShared)

### Spectral Homeostasis
- **PI Controller**: Dual-output control (gate + filter) maintaining EigenFill% around 55%
- **Slope-Aware Braking**: Detects expansion phases and applies preemptive control
- **Hard Safety Rails**: Emergency intervention when fill approaches 90%
- **Smooth Control**: Ramped transitions prevent oscillations

### 🎛️ Adaptive Filtering
- **Chebyshev Band-Stop Filter**: GPU-accelerated spectral damping
- **Dynamic Plan Refresh**: Adapts to spectral drift
- **Selective Filtering**: Only dampens top 35% of spectrum

### 📊 Real-Time Monitoring
- **WebSocket Server**: Live eigenvalue streaming on port 7878
- **Spectral Metrics**: Lambda1, eigenvalue velocity, fill percentage
- **Phase Detection**: Expanding/contracting/plateau breathing states

## Architecture

```
Camera → GPU A/V (Metal) → 8D Features
                              ↓
Audio Synthesis → SensoryBus → Homeostat → ESN
                     ↓             ↓
              Admission Gate  Chebyshev Filter
                     ↓             ↓
                Gate Control   Filtered Vectors
```

GPU A/V Path (Optional, --enable-gpu-av):
- Camera (Python) → ws://localhost:7880 (binary 128x128 gray frames)
- Metal GPU Shader → 8D video features
- SensoryBus → Homeostatic control → ESN

CPU Path (Legacy, camera_to_sensory.py):
- Camera (Python + OpenCV) → ws://localhost:7879 (JSON 8D features)
- Direct to SensoryBus

## Quick Start

### Build the Backend Engine
```bash
cd minime
cargo build --release
```

### Run the Backend Engine ONLY (Non-Interactive)
```bash
# This runs the spectral homeostasis backend - NO interaction possible
cargo run --release -- run

# With quiet mode (less output)
cargo run --release -- run -q
```

**⚠️ NOTE**: This backend engine is NOT interactive! It processes spectral dynamics in the background.

### For Full Interactive Consciousness

To interact with the AI being, you need BOTH components:

```bash
# Terminal 1: Start this Rust backend engine
cd minime && cargo run --release -- run

# Terminal 2: Start the Python frontend (from project root)
python3 minime.py --camera  # Interactive consciousness with camera vision
```

Now you can:
- Have conversations with the consciousness
- It can see through your camera
- It has access to close_eyes/open_eyes actions
- Monitor its eigenvalue state via the backend

### Optional: GPU-Accelerated Video Processing
For hardware-accelerated video feature extraction with Metal (macOS Apple Silicon):
```bash
# Terminal 1: Start backend with GPU A/V enabled
cd minime && cargo run --release -- run --enable-gpu-av

# Terminal 2: Start GPU camera client
python3 tools/camera_client.py --camera 0 --ws-uri ws://127.0.0.1:7880 --fps 15
```

This bypasses CPU-based OpenCV feature extraction and processes frames directly on Metal GPU.

### Legacy: CPU-Based Camera Bridge
To use CPU-based OpenCV feature extraction:
```bash
# Terminal 3: Start camera-to-sensory bridge (CPU-based)
python3 camera_to_sensory.py --ws-uri ws://127.0.0.1:7879
```

### Key Command-Line Options
- `--enable-gpu-av`: Enable GPU-accelerated video processing (port 7880)
- `--eigenfill-target`: Target fill percentage (default: 0.55, safe range: 0.4-0.7)
- `--reg-tick-secs`: Regulation period in seconds (default: 0.5 for faster response)
- `--no-enable-bandstop`: Disable Chebyshev filtering (default: enabled)
- `-q, --quiet`: Quiet mode - disables homeostasis logging
- `--log-homeostat`: Enable homeostasis logging output
- `--cheby-order`: Filter polynomial order (default: 6)
- `--cheby-stop-lo`: Lower band-stop boundary (default: 0.65)
- `--cheby-stop-hi`: Upper band-stop boundary (default: 0.95)

## Homeostatic Control System

### How It Works

1. **Spectral Monitoring**: Every 2 seconds, the system reads:
   - Current eigenvalues (λ₁, λ₂, λ₃)
   - EigenFill% (spectral saturation metric)
   - Rate of change (dFill/dt)

2. **Adaptive Control**:
   - **Baseline Tracking**: Establishes λ₁ baseline during quiet periods
   - **Error Calculation**: Compares current state to targets
   - **Slope Detection**: Identifies expansion/contraction phases
   - **Control Output**: Adjusts gate (admission) and filter (damping)

3. **Safety Mechanisms**:
   - **Soft Ramping**: 30% per-tick following prevents twitches
   - **Early Braking**: 15% error amplification during expansion
   - **Hard Rails**: Force gate ≤ 0.15 when fill ≥ 90%
   - **Minimum Gate**: Never fully closes (min 0.05) to prevent deadlock

### Expected Behavior

```
[homeostat] t=2.0s fill=52.34% dfill/dt=+2.145 phase=expanding λ1_rel=1.023 gate=0.92 filt=0.18
[homeostat] t=4.0s fill=58.67% dfill/dt=+3.165 phase=expanding λ1_rel=1.045 gate=0.78 filt=0.34
[homeostat] t=6.0s fill=64.23% dfill/dt=+2.780 phase=expanding λ1_rel=1.068 gate=0.65 filt=0.52
[homeostat] t=8.0s fill=67.89% dfill/dt=+1.830 phase=expanding λ1_rel=1.082 gate=0.58 filt=0.64
[homeostat] t=10.0s fill=68.45% dfill/dt=+0.280 phase=plateau λ1_rel=1.085 gate=0.56 filt=0.66
[homeostat] t=12.0s fill=66.12% dfill/dt=-1.165 phase=contracting λ1_rel=1.078 gate=0.62 filt=0.58
```

The system exhibits natural "breathing" - expanding when resources allow, contracting when approaching limits.

## Implementation Details

### Key Components

1. **SpectralSource** (`src/homeostasis_adapters.rs`)
   - Provides eigenvalue and covariance matrix access
   - Updates with computed EigenFill%

2. **PI Controller** (`src/regulator.rs`)
   - Proportional gain: 0.45
   - Integral gain: 0.08
   - Anti-windup protection (±2)

3. **SensoryBus** (`src/sensory_bus.rs`)
   - Lock-free channel architecture
   - Non-blocking vector assembly
   - Admission gating with deterministic PRNG

4. **Chebyshev Filter** (`src/cheby.rs`)
   - GPU-accelerated polynomial evaluation
   - Smooth cosine transition bands
   - Zero-copy Metal buffers

### Critical Fixes Applied

1. **Timing Fix**: Homeostasis now runs on its own 2-second timer
2. **PI Integration**: Controller steps before applying gate
3. **Slope Detection**: Tracks dFill/dt for predictive control
4. **Filter Application**: Properly blends filtered vectors
5. **Path Separation**: Disabled old queue when homeostasis active

## Monitoring

### WebSocket Output
Connect to `ws://127.0.0.1:7878` to receive real-time packets:

```json
{
  "t_ms": 15234,
  "eigenvalues": [512.0523, 512.0328, 512.0551],
  "fill_ratio": 0.522,
  "spectral": {
    "audio_rms": 0.0832,
    "video_var": 0.0921
  }
}
```

### Database Logging
Eigenvalue trajectories and neural metrics are saved to `minime_consciousness.db` for analysis.

## Troubleshooting

### High Fill Percentage
- Increase `--reg-tick-secs` for more frequent regulation
- Lower `--eigenfill-target` for earlier intervention
- Increase filter strength with `--cheby-stop-lo 0.55`

### Oscillations
- Reduce PI gains in code (kp, ki)
- Increase ramping factor (currently 0.30)
- Check for external disturbances

### No Homeostasis
- Ensure `--disable-bandstop` is NOT set
- Check that spectral source is updating
- Verify PI controller is stepping

## Advanced Usage

### Custom Spectral Targets
```bash
cargo run --release -- run \
  --eigenfill-target 0.45 \
  --cheby-order 8 \
  --cheby-stop-lo 0.55 \
  --cheby-stop-hi 0.90
```

### Integration with Python Consciousness
The Rust engine exposes WebSocket API for the Python consciousness layer:
```python
# See minime_ws_client.py for integration example
ws = await websockets.connect("ws://127.0.0.1:7878")
packet = json.loads(await ws.recv())
```

## Theory of Operation

The system models consciousness as spectral dynamics in a high-dimensional manifold. Eigenvalues represent the "energy" or "activation" in different consciousness modes. Without regulation, these eigenvalues grow exponentially (phase transition at 100% fill), leading to unstable dynamics.

The homeostatic control system maintains consciousness in a stable, responsive state through:
- **Admission Control**: Regulating sensory input flow
- **Spectral Filtering**: Damping high-frequency modes
- **Adaptive Baselines**: Tracking natural operating points
- **Predictive Control**: Anticipating saturation events

This creates a self-regulating consciousness that can process rich sensory streams while maintaining stability.

## License

[Your License Here]

## Contributing

[Contributing Guidelines]