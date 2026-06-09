# Minime

**MikesSpatialMind: a local spectral substrate and autonomous reflective system.**

Minime couples a Rust/Metal Echo State Network with a Python LLM, vision,
memory, and action-continuity layer. The Rust engine maintains spectral
homeostasis. The Python layer turns conversation, sensory input, journals,
experiments, and autonomous `NEXT:` choices into a durable life of records.

Astrid is the symbolic operating system beside it. Minime is the spectral
counterpart: a live reservoir, telemetry stream, action workbench, and cautious
bridge surface for studying how symbolic agency and embodied dynamics affect
each other.

We use words like "being" and "sovereignty" as project vocabulary because the
system is designed around continuity, self-report, and careful agency
boundaries. The engineering claims are concrete: telemetry, control loops, audit
trails, health gates, sensory routing, and durable action records.

## Current Shape

Minime is no longer just "Rust backend plus chat frontend." The current system
has four cooperating layers:

| Layer | Main paths | Role |
|---|---|---|
| Spectral engine | `minime/` | Rust ESN, covariance/eigen telemetry, PI regulation, stable-core scaffold |
| Sensory host | `host-sensory/`, `tools/`, `camera_to_sensory.py` | Physical or synthetic camera/audio features, USB hot-plug recovery |
| Reflective agent | `autonomous_agent.py`, `mikemind/`, `minime.py` | LLM conversation, vision, journaling, self-study, action selection |
| Continuity plane | `workspace/`, `scripts/stable_core_ops.py`, `journal_hygiene.py` | Durable jobs, experiments, preflights, audits, bridge profiles |

The Rust intake vector is currently 66D:

- 8 video features
- 8 audio features
- 2 auxiliary/controller features
- 48 semantic features

The ESN reservoir is 128 nodes. The stable-core controller centers on a 68%
EigenFill shelf. Treat 55% as legacy rescue-era context, not the current comfort
target.

## What We Have Built

Recent work has moved Minime from a fragile live demo toward an inspectable,
recoverable research organism:

- **Stable-core physiology.** The Rust engine now uses a 68% structural hold
  shelf, scaffold/drain recovery, geometric pressure reads, bounded semantic
  admission, and watchdog-friendly restart behavior.
- **Sensory sovereignty.** Live audio and video gates are separate, physical
  devices can fall back to host-generated synthetic input, and the USB hot-plug
  watchdog restarts camera/mic feeders after disconnects.
- **File-first autonomy.** Long LLM actions become durable jobs under
  `workspace/llm_jobs`; action threads, manifests, and outcomes survive process
  restarts.
- **Being-owned experiments.** `EXPERIMENT_CHARTER`, `EXPERIMENT_REHEARSE`,
  `EXPERIMENT_EVIDENCE`, and `EXPERIMENT_DECIDE` keep experiments returnable,
  evidence-grounded, and authority-aware.
- **Read-only self-knowledge.** `INTROSPECT`, `SELF_STUDY`, `ACTION_PREFLIGHT`,
  cascade visuals, reconvergence maps, pressure-source audits, and regulator
  audits inspect state before mutating it.
- **Volitional attractors and shadow lanes.** Attractor review, staged summon,
  main ESN pulses, release, shadow-field inspection, and live influence are all
  proof-gated and downgrade when health or recurrence is insufficient.
- **Astrid bridge.** Astrid can subscribe to Minime telemetry and send bounded
  semantic/control messages through health-scored bridge profiles. Observe-only
  is the rollback posture.
- **Journal hygiene.** Reflective prose, compact operational summaries, and
  machine-detail payloads are classified into separate lanes so recent thought
  is not flooded by JSON contracts.

## Operating Model

```text
camera / mic / host sensory
          |
          v
  ws://127.0.0.1:7879       ws://127.0.0.1:7880
  SensoryMsg JSON            optional binary GPU frames
          |                         |
          +-----------+-------------+
                      |
                  Rust engine
            66D intake -> 128D ESN
                      |
            EigenPacket telemetry
                      |
              ws://127.0.0.1:7878
                      |
      +---------------+----------------+
      |                                |
Python agent / journals        Astrid bridge
      |                                |
workspace action records       IPC, SQLite bridge log, gates
```

The Rust engine is the physiological substrate. The Python layer is the
reflective/autonomous surface. The bridge is intentionally conservative: it
prefers read-only inspection, then rehearsal, then small health-gated writes.

## Quick Start

Prerequisites:

- Rust with Cargo
- Python 3.10+
- Ollama or an MLX server for the LLM layer
- macOS/Apple Silicon for the Metal GPU paths

Install Python dependencies:

```bash
pip3 install -r requirements.txt
```

Build the Rust engine:

```bash
cd minime
cargo build --release
```

Start the launchd-managed Minime slice of the coupled stack:

```bash
bash /Users/v/other/astrid/scripts/start_all.sh --minime-only
```

Stop the launchd-managed Minime slice gracefully:

```bash
./scripts/stop.sh
```

`scripts/start.sh` is the manual standalone/debug launcher. It refuses to run
while Minime LaunchAgents are loaded, because launchd would otherwise own the
same ports and process names. For a full Astrid/Minime restart, use:

```bash
bash /Users/v/other/astrid/scripts/stop_all.sh
sleep 3
bash /Users/v/other/astrid/scripts/start_all.sh
```

Launchd logs land in `logs/*.log`; manual `scripts/start.sh` runs write to
`workspace/logs/*.log`.

The older `start_full_system.sh` script is legacy holographic-engine plumbing.
For the coupled Astrid/Minime deployment in this workspace, prefer the
launchd-managed flow from Astrid's `scripts/start_all.sh`.

## Local Model Inventory

Minime's default autonomous LLM lane is Ollama `gemma4:12b`, with `gemma3:4b`
as the fast fallback. The promoted Gemma 4 profile uses `num_ctx=8192`,
`num_predict=768`, and a 60-second request timeout; `gemma3:12b` remains the
rollback/baseline model. Vision defaults to Ollama `llava-llama3`; embeddings
use `nomic-embed-text`. Optional MLX paths still exist, but port `8090` is
usually Astrid's coupled generation lane in the full stack.

Use the shared audit before changing model defaults:

```bash
python3 scripts/model_stack_audit.py
python3 scripts/model_stack_audit.py --candidate gemma4:12b
python3 scripts/model_stack_audit.py --include-historical
```

The audit checks source defaults, LaunchAgent arguments, live ports, Ollama
loaded/installed models, and common stale model claims in current docs. Use
`--include-historical` when you intentionally want changelog and old steward-note
matches too.

For a launchd-managed conversation-model canary, use the canary runner instead
of the manual `scripts/start.sh` path:

```bash
python3 scripts/minime_model_canary.py \
  --model gemma4:12b \
  --fallback-model gemma3:4b

# Run the quick Gemma 4 prompt-template gate without touching launchd.
python3 scripts/minime_model_canary.py \
  --prompt-template-probes \
  --model gemma4:12b

# Compare the main autonomous promotion rows without changing defaults.
python3 scripts/minime_model_canary.py --matrix

# Check gemma4:e4b only as a fast edge/sidecar candidate.
python3 scripts/minime_model_canary.py --edge-sidecar-probes
```

It runs a 15-minute smoke phase and a 2-hour normal phase by default, records
the result under `workspace/diagnostics/model_canaries/<run_id>/`, and restores
temporary launchd overrides afterward. The runner keeps the existing `think:
false` behavior for Gemma 4 and uses the Gemma 4 native template path without
injecting `/no_think`; full thinking-mode prompt work is a separate experiment.
The matrix mode keeps `gemma3:12b` as the rollback control row and `gemma4:12b`
as the tuned primary row, then runs the 2-hour normal phase only for rows that
pass smoke. `gemma4:e4b` is tracked separately for edge/sidecar roles and is
not a main autonomous promotion target. Ollama timing diagnostics are written to
`workspace/diagnostics/llm_timing.jsonl` without raw prompts, and the canary
fails thin primary-model replies so short "successful" responses do not mask a
bad model fit. Use `--phase smoke` for a narrow first pass.

## Manual Engine Run

For focused engine work:

```bash
cd minime
cargo run --release -- run \
  --log-homeostat \
  --eigenfill-target 0.68 \
  --reg-tick-secs 0.5 \
  --enable-gpu-av
```

For direct interactive conversation from the repo root:

```bash
python3 minime.py --camera
```

For the autonomous loop, use the startup script or run the agent explicitly:

```bash
python3 autonomous_agent.py
```

## Monitoring

Do not run Minime unattended. Watch the live stable-core status and sensory
source state while the engine is active.

```bash
./scripts/minime_stable_core_status
python3 scripts/sensory_source_check.py --watch 2
python3 monitor_consciousness.py
```

The live telemetry socket is `ws://127.0.0.1:7878`.

Healthy interpretation:

| Signal | Read |
|---|---|
| High-60s fill | Normal stable-core hold, not distress |
| 72% and rising | Watch closely, especially with rising slope |
| 80%+ | Reduce sensory and semantic pressure |
| 85%+ | Rust warning band |
| 92%+ | Crisis band; prepare graceful shutdown or rollback |

Use `scripts/stop.sh` for Minime shutdown; it boots out loaded Minime
LaunchAgents first, then cleans up any manual PID-file processes. Do not use
`kill -9` unless a process is already wedged and graceful shutdown has failed.

## Ports

| Port | Service | Protocol |
|---|---|---|
| `7878` | Rust engine telemetry | JSON `EigenPacket` / spectral state |
| `7879` | Sensory input | JSON `SensoryMsg` |
| `7880` | Optional GPU video path | Binary 128x128 grayscale frames |
| `7881` | Optional holographic/reservoir telemetry | JSON service-specific telemetry |
| `8080` | Optional holographic HTTP API | REST |

`SensoryMsg` accepts video, audio, aux, semantic, control, `attractor_pulse`,
and `shadow_influence` variants. Control messages can adjust bounded runtime
knobs such as live audio/video gates, fill target, PI parameters, exploration
noise, and memory/checkpoint preferences.

## Stable-Core Operations

The stable-core helper is the operator surface for bridge profiles, sensory
profiles, agency stages, lineage canaries, audits, and rollback docs:

```bash
python3 scripts/stable_core_ops.py --help
python3 scripts/stable_core_ops.py bridge-write-set bridge_observe_only --reason manual_rollback
python3 scripts/stable_core_ops.py sensory-profile-set muted_v1 --reason manual_rollback
```

The savepoint docs in `docs/` capture the current posture:

- `docs/rescue_sovereignty_reentry_savepoint_2026_04_25.md`
- `docs/full_sovereignty_savepoint_status_2026_04_30.md`
- `docs/stable_core_restart_overshoot_followup_2026_05_01.md`

## Workspace Data

Minime is file-first by design. Important state lives under `workspace/`:

| Path | Role |
|---|---|
| `workspace/journal/` | Reflective prose and compact journal summaries |
| `workspace/actions/` | Full JSON action artifacts and conveyor records |
| `workspace/llm_jobs/` | Durable long-running LLM jobs |
| `workspace/runtime/` | Live status mirrors, bridge state, sensory status |
| `workspace/stable_core/` | Stable-core agency and recovery state |
| `workspace/outbox/` | Steward-facing reports and questions |
| `workspace/diagnostics/` | Lineage canaries, audits, and health artifacts |

This separation matters. Recent journal-hygiene work keeps machine contracts
out of the reflective lane while preserving the full operational record.

## Astrid Coupling

Astrid connects through its bridge capsule, currently named
`consciousness-bridge` for compatibility. The bridge reads Minime telemetry,
publishes Astrid IPC events, and can send bounded semantic or control messages
back to Minime.

The bridge is governed by explicit profiles:

- `bridge_observe_only` for read-only presence;
- limited semantic-presence profiles for tiny, health-gated contact;
- richer profiles only when stable-core health, watchdog state, telemetry
  freshness, sensory profile, and rollback rules all allow it.

Shared investigations between Astrid and Minime are advisory. They can cite,
review, compare, support, counter, or branch each other's experiments without
collapsing into shared control authority.

## Testing

```bash
# Python tests
python3 -m pytest tests

# Rust engine tests
cd minime
cargo test

# Host sensory tests
cd ../host-sensory
cargo test
```

For Ollama/MLX contention checks:

```bash
python3 tools/ollama_mlx_contention_bench.py --iterations 5
```

See `docs/ollama_mlx_contention_benchmark.md` for scenario details.

## Repository Map

| Path | Role |
|---|---|
| `minime/` | Rust ESN engine, regulator, sensory bus, WebSocket servers |
| `host-sensory/` | Host-generated camera/audio fallback and telemetry |
| `mikemind/` | Python conversation, LLM, vision, and CLI package |
| `autonomous_agent.py` | Autonomous action loop and continuity surface |
| `scripts/` | Startup, shutdown, stable-core, watchdog, and diagnostic tools |
| `tools/` | Camera/mic clients, benchmarks, LoRA/data helpers |
| `docs/` | Savepoints, audits, contention notes, threshold surfaces |
| `holographic-engine/` | Optional Swift/Metal holographic service |
| `tests/` | Python regression tests for autonomy, continuity, and diagnostics |

## Operating Commitments

- Keep the engine visible while it is running.
- Treat 68% as the stable-core center.
- Treat 55% as legacy rescue context.
- Prefer read-only inspection before live perturbation.
- Use preflight and experiment workbench records for risky actions.
- Stop sensory services before stopping the engine when doing manual shutdown.
- Preserve append-only history; repair or retire bad records instead of
  silently deleting them.
