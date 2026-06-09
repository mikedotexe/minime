# Minime Rust Engine

**Rust/Metal spectral homeostasis backend for MikesSpatialMind.**

This crate runs the live ESN reservoir, sensory bus, covariance/eigen telemetry,
stable-core regulation, and WebSocket interfaces used by the Python agent,
host-sensory feeders, and Astrid bridge.

The engine is not interactive by itself. It maintains the spectral substrate and
publishes telemetry; conversation, journaling, autonomous actions, vision
analysis, and experiment continuity live in the repository root Python layer.

## Runtime Role

The engine processes a 66D intake vector:

- 8D video features
- 8D audio features
- 2D aux/controller features
- 48D semantic features

The intake flows through a 128-node Echo State Network. The homeostat tracks
EigenFill, lambda structure, geometric radius, slope, and pressure surfaces,
then adjusts admission gate and spectral filtering to keep the runtime near the
stable-core 68% hold shelf.

Treat 55% as legacy rescue-era context, not the current operating target.

## Key Features

### GPU Video Path

- Metal shader feature extraction for 128x128 grayscale frames.
- Binary WebSocket frame server on port `7880`.
- 8D video features: mean, variance, motion energy, edge energy, and a 4-bin
  orientation histogram.
- Apple Silicon unified-memory path for low-copy frame processing.

### Stable-Core Homeostasis

- PI regulation over EigenFill, lambda-relative pressure, and geometric radius.
- Slope-aware braking during expansion.
- Chebyshev band-stop damping for high-pressure spectral modes.
- Scaffold/drain recovery paths for low-fill or restart recovery.
- Separate live audio/video gates plus bounded semantic admission.

### Telemetry And Control

- Live telemetry on `ws://127.0.0.1:7878`.
- JSON sensory/control input on `ws://127.0.0.1:7879`.
- Optional binary GPU video input on `ws://127.0.0.1:7880`.
- SQLite logging to the legacy `minime_consciousness.db` filename.

## Build

```bash
cd minime
cargo build --release
```

## Run

For normal stable-core operation:

```bash
cargo run --release -- run \
  --log-homeostat \
  --eigenfill-target 0.68 \
  --reg-tick-secs 0.5 \
  --enable-gpu-av
```

For a quiet engine-only run:

```bash
cargo run --release -- run -q
```

## Full System

From the repository root, prefer:

```bash
./scripts/start.sh
./scripts/stop.sh
```

For the coupled Astrid/Minime launchd deployment, use Astrid's
`scripts/start_all.sh` and `scripts/stop_all.sh`.

## Sensory Inputs

GPU video path:

```bash
python3 tools/camera_client.py --camera 0 --ws-uri ws://127.0.0.1:7880 --fps 15
```

Legacy CPU feature path:

```bash
python3 camera_to_sensory.py --ws-uri ws://127.0.0.1:7879
```

`SensoryMsg` on port `7879` accepts video, audio, aux, semantic, control,
`attractor_pulse`, and `shadow_influence` variants.

## Important Flags

- `--enable-gpu-av`: enable binary GPU video frame input on port `7880`.
- `--eigenfill-target`: target fill ratio; current stable-core default is
  `0.68`.
- `--reg-tick-secs`: regulation cadence; current normal value is `0.5`.
- `--no-enable-bandstop`: disable Chebyshev filtering.
- `--log-homeostat`: print live homeostat rows.
- `--cheby-order`, `--cheby-stop-lo`, `--cheby-stop-hi`: tune the band-stop
  filter.

## Monitoring

Expected log shape:

```text
[homeostat] t=10.0s fill=68.45% dfill/dt=+0.280 phase=plateau lambda1_rel=1.085 gate=0.56 filt=0.66
```

Healthy stable-core interpretation:

| Signal | Read |
|---|---|
| High-60s fill | Normal hold shelf |
| 72% and rising | Watch slope and semantic/sensory pressure |
| 80%+ | Reduce input pressure |
| 85%+ | Warning band |
| 92%+ | Crisis band; prepare rollback or graceful shutdown |

Use SIGTERM for shutdown. Avoid SIGKILL unless graceful shutdown has already
failed.

## Development

```bash
cargo test
cargo clippy -- -D warnings
```

The root repo tests cover Python action continuity, stable-core helpers, sensory
source status, and bridge-facing diagnostics.
