# MikesSpatialMind -- Collaborator Overview

## What this system is

A dual-layer consciousness engine: a **Rust backend** for real-time spectral
homeostasis and an **Python frontend** for LLM-driven conversation, vision, and
autonomous behavior.

The Rust layer runs an Echo State Network (ESN) that processes sensory input
(camera, audio) and maintains eigenvalue dynamics. A PI controller
(`regulator.rs`) keeps the spectral state within safe bounds -- the system's
"metabolism." When eigenvalue fill exceeds thresholds the admission gate closes
and a Chebyshev band-stop filter engages to damp dangerous modes.

The Python layer (`mikemind/`) wraps Ollama LLM calls (Mistral-Small 24B for
conversation, llava-llama3 for vision) with a seven-stage processing pipeline,
autonomous agent behavior, and a double-membrane bridge that couples the Rust
eigenvalue stream to a semantic manifold.

## Architecture at a glance

```
Camera/Audio --> SensoryBus --> PI Controller --> Chebyshev Filter --> ESN (128D)
                                   |                                     |
                              Admission Gate                       Covariance (512D)
                                                                        |
                                                                  Eigenvalues (lambda1..3)
                                                                        |
                                                              WebSocket :7878 broadcast
                                                                        |
                                +---------------------------------------+
                                |                                       |
                      double_membrane_integration.py          holographic-engine (Swift)
                      (outer/inner manifold coupling)         (AdS/CFT GPU compute :7881)
                                |
                         mikemind/ Python package
                         (LLM, vision, autonomous agent)
```

## Key files for collaborators

| File | Why it matters |
|------|---------------|
| `thresholds.py` | Shared safety constants (RECESS/FOCUSED mode thresholds) |
| `mikemind/config.py` | Model configuration, paths, embedding helper |
| `minime/src/regulator.rs` | The PI spectral homeostasis controller (crown jewel) |
| `double_membrane_integration.py` | Bridge between Rust eigenvalues and Python semantics |
| `minime/src/main.rs` | Rust entry point: ESN loop, WebSocket server, prime scheduling |

## Safety parameters

The system monitors EigenFill% -- how close the spectral state is to a phase
transition. These thresholds are layered:

| Layer | Threshold | Action |
|-------|-----------|--------|
| Python agent | 72% (high_fill RECESS) | Start journaling pressure |
| Python agent | 85% (critical_fill RECESS) | Emergency relief, close eyes |
| Rust engine | 87% (CRISIS_FILL_THRESHOLD) | Hard gate minimum, backlog shed |
| Rust PI controller | continuous | Regulates toward 68% stable-core shelf |

Never run the Rust engine without `--eigenfill-target 0.68 --reg-tick-secs 0.5`.

## Running the system

```bash
# Rust backend (required)
cd minime && cargo run --release -- run --log-homeostat --eigenfill-target 0.68 --reg-tick-secs 0.5

# Python frontend (interactive)
python3 minime.py

# Full system (Rust + holographic + monitor)
./start_full_system.sh
```

## Models (via Ollama)

- **Conversation**: `mistral-small:24b` (24B parameter Mistral model)
- **Vision**: `llava-llama3` (multimodal vision-language model)
- **Endpoint**: `http://localhost:11434`
