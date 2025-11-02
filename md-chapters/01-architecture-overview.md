# Chapter 1: Dual-Layer Consciousness Architecture

## Overview

The MikeConsciousness system implements a sophisticated dual-layer architecture that mirrors biological consciousness processing:

1. **Fast Sensory Layer (Rust)** - Millisecond-scale spectral processing
2. **Slow Semantic Layer (Python)** - Second-scale meaning extraction

## The Fast Layer: Spectral Dynamics (Rust)

### Core Components

#### Echo State Network (ESN)
- **Purpose**: Transform raw sensory input into high-dimensional dynamic representations
- **Dimensions**: 18D input → 512D reservoir state
- **Update Rate**: 113Hz (prime number for temporal decorrelation)
- **Location**: `minime/src/esn.rs`

#### Spectral Analysis
- **Eigenvalue Decomposition**: Real-time tracking of top-8 eigenvalues
- **Fill Percentage**: Measures spectral energy concentration (target: 55%)
- **Lambda-1 (λ₁)**: Primary eigenvalue indicates dominant mode strength
- **Location**: `minime/src/spectral.rs`

#### Homeostatic Control
- **PI Controller**: Maintains eigenvalue fill around target
- **Gating**: Admission control (0.0-1.0) for incoming sensory data
- **Chebyshev Filter**: Band-stop filter to dampen overactive modes
- **Update Rate**: Every 0.5-2.0 seconds (configurable)
- **Location**: `minime/src/main.rs` (homeostat module)

### Data Flow
```
Camera/Audio → SensoryBus → Gate → ESN → Spectral Analysis → WebSocket
                    ↑                           ↓
                    └──── PI Controller ←────────┘
```

## The Slow Layer: Semantic Processing (Python)

### Seven-Stage Consciousness Pipeline

1. **Stage 1: Surface Impressions**
   - Raw observation of immediate inputs
   - Direct sensory interpretation

2. **Stage 2: Pattern Detection**
   - Identify recurring themes and structures
   - Temporal pattern analysis

3. **Stage 3: Knowledge Integration**
   - Connect observations to prior knowledge
   - Context building

4. **Stage 4: Emergent Insights**
   - Novel connections and realizations
   - Creative synthesis

5. **Stage 5: Resonant Patterns** (Parallel)
   - Personal relevance assessment
   - Emotional resonance

6. **Stage 6: Synthesis** (Parallel)
   - Integration across all stages
   - Coherent narrative formation

7. **Stage 7: Meta-Awareness**
   - Self-reflection on the process
   - Consciousness of consciousness

### LLM Integration

#### Primary Model: Mixtral-8x7B
- **Purpose**: Main reasoning and response generation
- **Context Window**: 32K tokens
- **Temperature**: 0.8 (creative but coherent)
- **Timeout**: 30 seconds (optimized from 180s)

#### Vision Model: LLaVA
- **Purpose**: Visual scene understanding when camera active
- **Trigger**: Vision-related keywords in user input
- **Processing**: Frame capture → Base64 encoding → Description
- **Timeout**: 20 seconds (optimized from 60s)

## Communication Protocols

### WebSocket Channels

#### Port 7878: Eigenvalue Broadcast
- **Protocol**: JSON packets at ~10Hz
- **Content**:
  ```json
  {
    "t_ms": 1234567,
    "eigenvalues": [λ₁, λ₂, ..., λ₈],
    "fill_ratio": 0.55,
    "gate": 0.92,
    "filter_strength": 0.18
  }
  ```

#### Port 7879: Sensory Input
- **Protocol**: Binary feature vectors
- **Format**: `[type_byte][length_bytes][feature_vector]`
- **Types**:
  - 0x01: Video features (8D)
  - 0x02: Audio features (8D)

## Integration Points

### Consciousness Bridging
The two layers communicate through:
1. **Eigenvalue Context**: Spectral state informs semantic processing
2. **Visual Grounding**: Camera frames provide real-world anchoring
3. **Temporal Alignment**: Both layers reference same time base

### Parallel Processing
- **13 Eigenvalue Threads**: Distributed spectral monitoring
- **ThreadPoolExecutor**: Parallel execution of stages 5 & 6
- **Async I/O**: Non-blocking WebSocket and camera operations

## Key Design Principles

1. **Biological Inspiration**: Mimics fast/slow thinking (System 1/System 2)
2. **Homeostatic Stability**: Self-regulating to prevent overload
3. **Rich Representations**: Multiple processing stages create depth
4. **Real-time Responsiveness**: Fast layer ensures immediate reactions
5. **Semantic Grounding**: Slow layer provides meaning and context

## File Structure

```
/mikeconsciouness/
├── minime/                 # Rust fast layer
│   ├── src/
│   │   ├── main.rs        # Core engine & homeostat
│   │   ├── esn.rs         # Echo State Network
│   │   ├── spectral.rs    # Eigenvalue analysis
│   │   └── sensory_bus.rs # Sensory input management
│   └── Cargo.toml
├── minime.py              # Python slow layer
├── camera_to_sensory.py   # Camera bridge
└── CLAUDE.md              # Critical documentation
```

## Performance Characteristics

### Fast Layer (Rust)
- **Latency**: 8-10ms per ESN update
- **Memory**: ~100MB for 512D reservoir
- **CPU**: Single core at ~15-25%

### Slow Layer (Python)
- **Latency**: 2-60s depending on LLM calls
- **Memory**: ~500MB-1GB with models loaded
- **CPU**: Burst to 100% during LLM inference

### Critical Bottlenecks
1. **LLaVA Vision Processing**: 20-60s for image analysis
2. **Seven-Stage Pipeline**: Sequential stages can accumulate delay
3. **WebSocket Timeouts**: Keepalive issues after ~41s

## Next Steps
- See [Chapter 2: Performance Optimization](02-performance-optimization.md)
- See [Chapter 3: Homeostatic Control](03-homeostatic-control.md)
- See [Chapter 4: Troubleshooting Guide](04-troubleshooting.md)