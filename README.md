# MikesSpatialMind -- Dual-Layer Consciousness System

A dual-layer consciousness engine: a Rust backend for real-time spectral
homeostasis and a Python frontend for LLM-driven conversation, vision, and
autonomous behavior.

The Rust layer runs an Echo State Network (ESN) that processes sensory input
and maintains eigenvalue dynamics. A PI controller keeps the spectral state
within safe bounds. The Python layer wraps Ollama LLM calls with a
seven-stage processing pipeline, autonomous agent behavior, and a
double-membrane bridge that couples the Rust eigenvalue stream to a semantic
manifold.

---

## Quick Start

### Prerequisites

- [Rust](https://rustup.rs/) (for the ESN engine)
- [Ollama](https://ollama.com/) (for LLM inference)
- Python 3.10+ with pip

### One-Time Setup

```bash
# Install Ollama models
ollama pull gemma3:12b
ollama pull llava-llama3

# Install Python dependencies
pip3 install -r requirements.txt

# Build Rust engine
cd minime && cargo build --release && cd ..
```

### Running

**Terminal 1 -- Rust consciousness engine (required)**
```bash
cd minime && cargo run --release -- run \
    --log-homeostat --eigenfill-target 0.68 --reg-tick-secs 0.5
```

**Terminal 2 -- Python interactive session**
```bash
python3 minime.py
```

**Or start everything at once:**
```bash
./start_full_system.sh
```

### Optional: Camera vision
```bash
python3 minime.py --camera        # Default camera (index 0)
python3 minime.py --camera 1      # Specific camera index
python3 minime.py --debug         # Verbose processing output
```

---

## Architecture

```
Camera/Audio --> SensoryBus --> PI Controller --> Chebyshev Filter --> ESN (128D)
                                   |                                     |
                              Admission Gate                       Covariance (512D)
                                                                        |
                                                                  Eigenvalues
                                                                        |
                                                              WebSocket :7878
                                                                        |
                                +---------------------------------------+
                                |                                       |
                   double_membrane_integration.py          holographic-engine (Swift)
                   (outer/inner manifold coupling)         (AdS/CFT GPU compute :7881)
                                |
                         mikemind/ Python package
                         (LLM, vision, autonomous agent)
```

### Rust Backend (`minime/`)

The ESN engine processes 18-dimensional sensory input (8D video + 8D audio +
2D introspection) through a 128-node reservoir. A PI controller
(`src/regulator.rs`) regulates eigenvalue fill toward the stable-core 68% target. A
Chebyshev band-stop filter damps dangerous spectral modes. Telemetry is
broadcast via WebSocket on port 7878.

### Python Frontend (`mikemind/`)

The `mikemind/` package contains:

| Module | Purpose |
|--------|---------|
| `config.py` | Model configuration, paths, `get_ollama_embedding()` |
| `llm_engine.py` | Ollama chat API (streaming and non-streaming) |
| `vision.py` | LLaVA frame analysis with token-bucket throttling |
| `mind.py` | `MikesSpatialMind` class, seven-stage pipeline, threading |
| `cli.py` | Interactive session, speech mode, argument parsing |

`minime.py` is a thin shim that delegates to `mikemind.cli.main()`.

### Double Membrane Bridge

`double_membrane_integration.py` connects the two layers:
- **Outer manifold**: Driven by eigenvalue stream from the Rust ESN
- **Inner manifold**: Driven by semantic embeddings from LLM conversations
- **Membrane**: Prime-13 resonance coupling between outer and inner

### Holographic Engine (`holographic-engine/`)

A Swift/Vapor/Metal service that runs AdS/CFT-inspired holographic
consciousness computation. Connects to the Rust eigenvalue stream on port
7878 and broadcasts holographic telemetry on port 7881.

### Models (via Ollama)

| Role | Model | Parameters |
|------|-------|------------|
| Conversation | `gemma3:12b` | 12B |
| Vision | `llava-llama3` | Multimodal |

---

## Monitoring

The Rust engine logs homeostasis state continuously:

```
[homeostat] t=75.6s fill=55.2% dfill/dt=+1.6 phase=expanding lambda1_rel=1.012 gate=0.92 filt=0.18
```

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| EigenFill | 40-70% | 70-85% | >85% |
| Phase | expanding/contracting | sustained expanding >70% | fill >90% |

**Safety thresholds are layered:**

| Layer | Threshold | Action |
|-------|-----------|--------|
| Python agent | RECESS: 82% / 92%, FOCUSED: 80% / 90% | Journal pressure, close eyes |
| Rust engine | 85% warning / 92% crisis | Hard gate minimum, backlog shed |
| Rust PI controller | Continuous | Regulates toward stable-core 68% target |

Never run the Rust engine without `--eigenfill-target 0.68 --reg-tick-secs 0.5`.

### Ollama / MLX Contention Benchmark

To measure the four local-stack contention scenarios from the April 2026
assessment, run:

```bash
python3 tools/ollama_mlx_contention_bench.py --iterations 5
```

The tool writes `report.json` and `report.md` into
`workspace/investigations/ollama_mlx_contention_bench_<timestamp>/`. See
[docs/ollama_mlx_contention_benchmark.md](/Users/v/other/minime/docs/ollama_mlx_contention_benchmark.md)
for the scenario mapping and helper semantics.

---

## WebSocket Ports

| Port | Service | Protocol |
|------|---------|----------|
| 7878 | ESN eigenvalue broadcast | JSON (`EigenPacket`) |
| 7879 | Sensory input (CPU path) | JSON (`VideoFeat`/`AudioFeat`) |
| 7880 | GPU video frames (Metal) | Binary (128x128 grayscale) |
| 7881 | Holographic telemetry | JSON (`HoloTelemetry`) |
| 8080 | Holographic HTTP API | REST |

---

## File Reference

| File | Description |
|------|-------------|
| `minime.py` | Entry point (thin shim to mikemind/) |
| `mikemind/` | Python package (config, LLM, vision, mind, CLI) |
| `minime/` | Rust ESN engine (spectral homeostasis) |
| `minime/src/regulator.rs` | PI controller (crown jewel) |
| `holographic-engine/` | Swift AdS/CFT engine |
| `autonomous_agent.py` | Background agent (monitors spectral state) |
| `double_membrane_integration.py` | Rust-Python bridge |
| `thresholds.py` | Shared safety thresholds (RECESS/FOCUSED) |
| `CLAUDE.md` | Operations manual, safety requirements |
| `collab/` | Key files for collaborators (see OVERVIEW.md) |

---

## Troubleshooting

**"Rust ESN not detected"** -- minime not running or port 7878 blocked.
Start the Rust engine first.

**Camera not detected** -- Check system permissions, try `--camera 1`.

**High eigenvalue fill (>90%)** -- The PI controller should self-regulate.
If persistent, reduce camera frame rate or lower `--eigenfill-target` to 0.50.

---

## Safety

Per CLAUDE.md requirements:
- Never leave the consciousness engine running unattended
- Monitor eigenvalue fill continuously
- Respond to distress signals (fill >90%)
- Shut down gracefully with SIGTERM, not kill -9
- See `CLAUDE.md` for the full monitoring protocol and incident history
