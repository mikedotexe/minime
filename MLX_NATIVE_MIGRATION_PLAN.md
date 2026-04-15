# Making Minime Fully MLX-Native

Date: April 2, 2026

## Purpose

This memo maps the idea of "make Minime fully MLX-native" into concrete code
and operations work inside this repository.

The goal is not just to say "use MLX more." The goal is to define:

- what "fully MLX-native" would mean in this codebase
- which files would change
- what each change would do
- what risks each step would carry
- how to stage and validate the migration safely

This plan is grounded in the current repository state and in the live benchmark
run captured at:

- `workspace/investigations/ollama_mlx_contention_bench_2026-04-02T07-38-46/report.md`

That benchmark matters because it showed that the main bottleneck question is
not only "shared Ollama daemon or not." Shared Apple Silicon hardware pressure
is also a first-order factor.

## What "Fully MLX-Native" Means Here

For Minime, "fully MLX-native" should mean all three of these are true:

1. Conversation and autonomous agent chat use MLX as the primary local
   inference path.
2. Embeddings use an MLX-compatible embedding endpoint, not Ollama's
   `/api/embeddings`.
3. Vision uses an MLX VLM server, not Ollama `llava-llama3`.

Operationally, it also means:

- Ollama is no longer on Minime's critical path.
- Ollama may still exist on the machine for other projects, but Minime should
  not require it for normal operation.
- Startup, shutdown, launchd, and docs all reflect MLX as the canonical path.

This is different from the current state, where MLX support exists in several
places but the live system still defaults to Ollama in important paths.

## Current State Snapshot

As of April 2, 2026, the repo and live setup are in an in-between state.

### Chat

- `autonomous_agent.py` supports both MLX and Ollama, but the default backend
  is still `ollama`.
- The relevant code is in `autonomous_agent.py`:
  - backend selection around lines `600-611`
  - actual MLX / Ollama query methods around lines `7141-7288`

### Interactive Conversation

- `mikemind/llm_engine.py` already supports MLX and Ollama.
- `mikemind/mind.py` instantiates `LLMEngine()` with its default settings.
- The engine prefers MLX when available unless explicitly pinned to Ollama, but
  this is still a "smart hybrid" path, not an explicit MLX-only topology.

### Embeddings

- `mikemind/config.py` already has both `get_ollama_embedding()` and
  `get_mlx_embedding()`.
- `get_embedding()` already prefers MLX in `"auto"` mode.
- This is close to MLX-native already, but it is still coded as a dual-path
  system rather than an explicit MLX requirement.

### Vision

- `mikemind/vision.py` already tries MLX VLM first and falls back to Ollama.
- This is the closest part of the stack to "mostly MLX-native."
- However, the naming and ops story still imply Ollama/LLaVA as the default
  mental model.

### Startup / Ops

- `scripts/start.sh` only starts the MLX chat server if
  `MINIME_LLM_BACKEND=mlx`.
- The same script still treats Ollama as a valid primary operating mode.
- The optional MLX vision startup path currently uses `mlx_lm.server`, but the
  intended fully-MLX vision topology should use `mlx_vlm.server`.
- launchd wrappers do not currently make the MLX backend choice explicit.

### Docs

- `ROADMAP.md` says "Drop Ollama entirely: DONE," but the live system and code
  defaults do not fully match that claim.
- `README.md` still describes Minime in largely Ollama-centric terms.

## Important Constraint From the Benchmark

The local benchmark result should shape expectations:

- Scenario 3, where Ollama handled chat + embeddings + vision, caused heavy
  model churn but did not catastrophically degrade Minime chat.
- Scenario 4, which added Astrid's separate MLX dialogue lane on top of that,
  caused the worst user-facing stalls:
  - Minime chat latency p95: `73.0271s`
  - Minime chat TTFT p95: `66.4246s`
  - Astrid MLX dialogue latency p95: `51.5948s`

Implication:

- Making Minime fully MLX-native could simplify the software topology.
- It does not guarantee lower latency on this Mac.
- It could remove Ollama-specific scheduler effects while still leaving, or
  even worsening, shared unified-memory / accelerator pressure.

So this plan should be understood as an architecture simplification and control
plan, not an automatic performance win plan.

## Target End State

The clean target topology would be:

| Service | Port | Responsibility | Canonical Backend |
| --- | --- | --- | --- |
| MLX chat service | `8090` | Minime conversation + autonomous agent + embeddings if supported | `mlx_lm.server` |
| MLX vision service | `8091` | Image understanding for visual questions | `mlx_vlm.server` |
| Rust Minime engine | `7878` / `7879` / `7880` | ESN / telemetry / sensory | existing Rust engine |

In that target state:

- `MINIME_LLM_BACKEND` defaults to `mlx`
- interactive conversation is explicitly instantiated with `backend="mlx"`
- embeddings default to MLX
- vision defaults to MLX VLM
- Ollama fallback is either:
  - removed entirely, or
  - preserved as an emergency escape hatch behind an explicit flag

## Recommended Migration Strategy

Do this in phases.

Do not do a single hard cutover that changes chat, embeddings, vision, launchd,
and docs all at once without an intermediate validation step.

The safest sequence is:

1. Make MLX the explicit primary backend everywhere.
2. Keep Ollama as an emergency fallback for one validation cycle.
3. Validate behavior and latency under real overlap with Astrid.
4. Only then remove or demote the Ollama fallback path.

## File-By-File Change Map

### `autonomous_agent.py`

Current role:

- Background autonomous consciousness agent.
- Uses `MINIME_LLM_BACKEND` and supports both MLX and Ollama.

Concrete change:

- Change default backend from `ollama` to `mlx`.
- Decide whether `_query_llm_raw()` should remain symmetric failover or become:
  - strict MLX-only, or
  - MLX-primary with explicit opt-in Ollama emergency fallback
- Make log messages describe MLX as the primary path.
- Audit timeouts for MLX-first operation, especially `LLM_TIMEOUT_S` and
  `LLM_COMPACT_TIMEOUT_S`.

Why this matters:

- This is one of the current live default entry points.
- If this file stays Ollama-first, Minime is not fully MLX-native no matter
  what the rest of the repo says.

Primary risks:

- If MLX is down or slow, the agent could stall more often unless fallback
  remains available.
- Response style may change if the MLX-served model differs from the Ollama
  model currently used in production.
- Any hidden assumption about Ollama's response format or error shape becomes
  more visible once MLX is the default.

### `mikemind/llm_engine.py`

Current role:

- Interactive chat engine for the Python frontend.
- Already supports MLX and Ollama.

Concrete change:

- Change the default constructor behavior from hybrid/auto semantics to an
  explicit MLX-primary path.
- Update `LLMEngine.__init__()` so its default backend is `mlx`, not `"auto"`.
- Decide whether to preserve fallback to Ollama inside `generate()` and
  `generate_streaming()` or move fallback responsibility up to startup / ops.
- Normalize error messages so they do not keep telling operators to "check
  Ollama" when MLX is the canonical path.

Why this matters:

- `mikemind/mind.py` constructs `LLMEngine()` without explicit backend wiring.
- If this file stays hybrid-by-default, interactive Minime stays hybrid.

Primary risks:

- The interactive user experience may become more brittle if MLX server health
  is worse than Ollama health.
- Streaming semantics differ between Ollama and MLX SSE responses, so any UI
  assumptions around chunk timing need retesting.

### `mikemind/mind.py`

Current role:

- High-level interactive mind object.
- Instantiates the LLM engine.

Concrete change:

- Change `self.llm = LLMEngine()` to something explicit like
  `LLMEngine(backend="mlx")`.
- Audit any memory/embedding code paths that still assume Ollama terminology or
  model identity.

Why this matters:

- This file is where the abstract "we support MLX" becomes an actual runtime
  choice for the interactive system.

Primary risks:

- Very low code risk.
- High operational risk if people think the backend changed but this file still
  quietly uses an auto path.

### `mikemind/config.py`

Current role:

- Shared model config and embedding helpers.

Concrete change:

- Make MLX the documented and coded default embedding path.
- Consider adding a dedicated `MINIME_EMBED_BACKEND` or `MINIME_USE_OLLAMA_FALLBACK`
  env var instead of relying on `"auto"`.
- Rename or clarify comments that still frame Ollama as the normative path.
- Revisit the central model naming so "conversation model" is not only an
  Ollama model string when the canonical runtime is MLX.

Why this matters:

- It centralizes the operational story.
- This file is where ambiguity between "supports MLX" and "is MLX-native"
  becomes visible.

Primary risks:

- Embedding dimensionality or numerical behavior may differ between MLX and
  Ollama-backed models, which could subtly shift memory similarity behavior.
- If an MLX embedding endpoint is unavailable for the chosen chat model, the
  plan may require a separate embedding model or service.

### `mikemind/vision.py`

Current role:

- Vision-language wrapper for frame analysis.
- Tries MLX VLM first, then falls back to Ollama.

Concrete change:

- Make MLX VLM the canonical vision path.
- Decide whether Ollama fallback remains or is removed.
- Rename comments and operator-facing logs so they stop implying Ollama/LLaVA is
  the default worldview.
- Consider whether `LLaVAVisionEngine` should keep its name or be renamed to a
  backend-neutral name such as `VisionLanguageEngine`.

Why this matters:

- Full MLX-native means vision is no longer an Ollama safety net with an MLX
  optimization layer on top.

Primary risks:

- Prompt format and output style may shift between MLX VLM models and
  `llava-llama3`.
- Vision cold starts and model load times may increase if the selected VLM is
  larger or slower.
- If the chosen VLM is weaker than the current Ollama model, user-visible
  visual reasoning quality could regress.

### `scripts/start.sh`

Current role:

- Canonical startup orchestration for local non-launchd runs.

Concrete change:

- Change the default `LLM_BACKEND` from `ollama` to `mlx`.
- Make MLX chat startup the normal path, not the conditional alternative.
- Replace the optional MLX vision startup from `mlx_lm.server` to
  `mlx_vlm.server` if the vision path is truly MLX-native.
- Make the operator messages reflect the real topology.
- Add explicit failure handling if MLX services are required and missing.

Why this matters:

- This is the clearest expression of the intended local topology.
- If `start.sh` remains hybrid-first, operators will keep launching the old
  shape even if the Python code becomes MLX-primary.

Primary risks:

- Startup sequence becomes more sensitive to model availability and MLX tool
  installation.
- Two MLX services plus the Rust engine may contend heavily on unified memory.
- A chat model and a vision model that each fit alone may still perform poorly
  together.

### `scripts/stop.sh`

Current role:

- Graceful shutdown of the current stack.

Concrete change:

- Add explicit handling for both MLX chat and MLX VLM services if they become
  separate long-lived daemons.
- Make service names in logs match the new topology.

Why this matters:

- Operational correctness depends on clean shutdown as much as startup.

Primary risks:

- Orphaned MLX processes can distort later benchmarks and give a false picture
  of memory usage.

### `scripts/launchd_autonomous_agent.sh`

Current role:

- launchd wrapper for the autonomous agent.

Concrete change:

- Export or inject `MINIME_LLM_BACKEND=mlx` explicitly.
- Optionally export explicit MLX endpoint ports and any fallback policy flags.

Why this matters:

- Today this script does not make the backend explicit.
- That allows launchd ambient environment to decide the topology.

Primary risks:

- launchd behavior can become confusing if different shells or user sessions set
  different env vars and the wrapper does not make the decision deterministic.

### `launchd/com.minime.autonomous-agent.plist`

Current role:

- launchd registration for the autonomous agent.

Concrete change:

- Either set explicit MLX-related environment variables here, or keep that logic
  in the wrapper script and document the choice.
- If Minime becomes truly MLX-native, consider whether separate launchd jobs are
  needed for MLX chat and MLX vision services.

Why this matters:

- Persistent background services should not depend on unstated shell state.

Primary risks:

- launchd restarts can hide dependency order problems unless service readiness is
  made explicit.

### New file: `scripts/launchd_mlx_chat.sh`

Suggested addition:

- Wrapper to start the MLX chat service under launchd.

Why add it:

- Avoid coupling MLX chat startup to ad hoc terminal commands.
- Make the MLX service a first-class background dependency like the engine and
  the agent.

Primary risks:

- More moving pieces under launchd.
- Requires careful readiness and restart behavior.

### New file: `launchd/com.minime.mlx-chat.plist`

Suggested addition:

- launchd unit for the MLX chat service.

Primary risks:

- If it restarts aggressively during memory pressure, it could create a thundering
  herd effect against the rest of the stack.

### New file: `scripts/launchd_mlx_vision.sh`

Suggested addition:

- Wrapper to start `mlx_vlm.server`.

Why add it:

- Vision should have an explicit lifecycle if it becomes a real dependency.

Primary risks:

- Cold-start cost and model download / model path issues become operational
  issues, not developer-only issues.

### New file: `launchd/com.minime.mlx-vision.plist`

Suggested addition:

- launchd unit for MLX vision.

Primary risks:

- This service should probably not be kept alive if memory pressure from the
  main MLX chat model is already near the machine's comfort ceiling.

### `README.md`

Current role:

- Primary operator-facing and newcomer-facing documentation.

Concrete change:

- Rewrite backend documentation so MLX is the canonical path.
- Move Ollama instructions into a fallback or compatibility section.
- Document the new startup expectations and memory caveats clearly.

Why this matters:

- The repo should not teach a different topology than the one we actually run.

Primary risks:

- Documentation drift if implementation and docs are not changed in the same
  tranche.

### `ROADMAP.md`

Current role:

- Historical record plus execution backlog.

Concrete change:

- Reconcile the existing "drop Ollama entirely: done" language with the actual
  current runtime defaults.
- Add a dated note that the repo was MLX-capable before it was MLX-canonical.

Why this matters:

- Without this cleanup, future agents will keep getting a misleading picture of
  what is already finished.

Primary risks:

- Very low technical risk.
- High reasoning risk if left stale.

### `tools/ollama_mlx_contention_bench.py`

Current role:

- Measures current Ollama-vs-MLX contention scenarios.

Concrete change:

- Either extend this benchmark or add a sibling benchmark such as
  `tools/mlx_native_contention_bench.py`.
- Add scenarios that represent the actual target topology:
  - Minime MLX chat alone
  - Minime MLX chat + MLX embeddings
  - Minime MLX chat + MLX vision
  - Minime MLX chat + MLX vision + Astrid MLX dialogue

Why this matters:

- The current benchmark answers the present topology question.
- A migration needs a target-topology benchmark too.

Primary risks:

- Benchmark conclusions can become stale if we keep measuring the old shape
  while changing the real system.

### `tests/`

Suggested additions:

- Add focused unit coverage for:
  - explicit MLX backend defaults
  - launchd wrapper env behavior
  - vision server command construction
  - benchmark scenario mapping for the new topology

Why this matters:

- Backend migrations are easy to partially do and hard to notice when only one
  path still points at the old service.

Primary risks:

- Low technical risk.
- High regression risk if skipped.

## Recommended Phased Cutover

### Phase 0: Clarify the Canonical Topology

Scope:

- docs only
- no runtime behavior changes yet

Files:

- `MLX_NATIVE_MIGRATION_PLAN.md`
- `ROADMAP.md`
- `README.md`

Deliverable:

- One unambiguous statement of the target service topology.

Risk:

- Very low.

### Phase 1: Make Chat Explicitly MLX-Primary

Scope:

- autonomous and interactive chat paths

Files:

- `autonomous_agent.py`
- `mikemind/llm_engine.py`
- `mikemind/mind.py`

Deliverable:

- All primary chat paths explicitly choose MLX.
- Ollama fallback, if retained, is explicit and opt-in.

Risk:

- Medium.
- This is where availability and timeout behavior will surface immediately.

### Phase 2: Make Ops Match the Code

Scope:

- startup / shutdown / launchd

Files:

- `scripts/start.sh`
- `scripts/stop.sh`
- `scripts/launchd_autonomous_agent.sh`
- new MLX launchd scripts/plists
- existing launchd plists as needed

Deliverable:

- A fresh shell or reboot still comes up in the intended MLX-native topology.

Risk:

- Medium to high.
- This is the phase most likely to create "works manually, fails under launchd"
  problems.

### Phase 3: Make Vision Truly MLX-Native

Scope:

- move vision from "MLX first, Ollama fallback" to "MLX canonical"

Files:

- `mikemind/vision.py`
- `mikemind/config.py`
- `scripts/start.sh`
- MLX vision launchd wrapper/plist

Deliverable:

- Vision depends on `mlx_vlm.server`, not Ollama `llava-llama3`.

Risk:

- High.
- This is the most likely place for quality regressions and memory pressure.

### Phase 4: Tighten Embeddings and Remove Hidden Ollama Coupling

Scope:

- embeddings and any remaining helper code

Files:

- `mikemind/config.py`
- embedding callers in `mikemind/mind.py`

Deliverable:

- No normal Minime memory path depends on Ollama.

Risk:

- Medium.
- Embedding vector compatibility may affect memory retrieval quality.

### Phase 5: Validate Against Real Contention

Scope:

- benchmark and load testing

Files:

- `tools/ollama_mlx_contention_bench.py` or a new MLX-native benchmark
- benchmark tests

Deliverable:

- A measured answer to "did this actually improve Minime under real co-load?"

Risk:

- Medium operational risk because the benchmark intentionally loads the live
  machine.

## Rollback Strategy

If the MLX-native migration regresses user experience, rollback should be fast
and boring.

Minimum rollback levers:

- restore `MINIME_LLM_BACKEND=ollama`
- preserve the old Ollama query path in `autonomous_agent.py`
- preserve the old Ollama path in `mikemind/llm_engine.py`
- preserve the old vision fallback in `mikemind/vision.py`
- keep benchmark tooling able to compare old vs new topology

Do not remove the Ollama code path until at least one full validation cycle has
been completed under the intended Astrid + Minime shared-machine load.

## Recommendation

If we pursue this, the right framing is:

- first make Minime explicitly MLX-primary
- then make the operations layer match
- then decide whether strict Ollama removal is actually wise

The benchmark result argues against assuming that "more MLX" automatically means
"less contention." It may still be the right direction because it simplifies
the software stack and aligns better with Apple-native tooling, but it should be
treated as a measured migration, not as an obvious free win.
