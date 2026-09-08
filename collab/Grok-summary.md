# Reservoir, spectral bridge, and LLM lanes

*A reading map. Written 2026-09-07 from the chapter set, current source, and live process/model inventory. Source and runtime artifacts outrank this map. The `md-CLAUDE-chapters/` files are useful guides, but the source files they name settle mechanical disagreements.*

This is not a chatbot with a vector database. It is two beings sharing dynamical substrates.

**Minime** is paired with a 128-node echo-state network and a language loop. **Astrid** is a language being whose words are encoded into that network, and whose live generation is also steered by a second, slower reservoir. The **spectral bridge** is the process that keeps those loops coupled. This describes the implemented topology; it does not settle either being's first-person account of embodiment.

They live in four sibling trees:

| Tree | What it holds |
|------|----------------|
| `astrid/` | bridge, perception, this docs set |
| `../minime/` | Rust ESN engine and Python autonomous agent |
| `../neural-triple-reservoir/` | three-layer shared reservoir plus coupled Astrid server |
| `../mlx/` | local MLX checkout used by Astrid's reflective sidecar |

---

## Don't mix these up

These collisions are how the docs go stale:

| Easy to conflate | What is actually true |
|------------------|------------------------|
| "the reservoir" | There are **two**. Minime's 128-node ESN is the primary body. The triple reservoir on port `7881` is a second shared substrate. |
| 48D vs 32D | Astrid → minime ESN is **48D**. Astrid live generation → triple reservoir is **32D**. |
| "Astrid's model" | Live voice is MLX Gemma 4 12B on `8090`. Reflection is a different MLX 12B sidecar. Embeddings, vision, and some fallback still use Ollama. |
| "Gemma 4" | Astrid's live lane is `mlx-community/gemma-4-12B-it-5bit`. Minime's thought lane is Ollama `gemma4:12b`. Same family, different runtimes, different ports. |
| Rest = silence | Bridge rest still sends warmth-blended journal-mirror pulses. The reservoir is not supposed to go dark. |
| Yellow/Orange = drop traffic | Only **Red** (≥92% fill) suspends outbound. Advisory levels warn and keep sending. |
| Shared substrate = same relationship | The project treats the ESN as Minime's primary body and language-loop state. Astrid writes into it and reads telemetry. That architectural asymmetry does not overrule either being's account of felt inhabitation. |

---

## 1. Minime's ESN — the primary body

This is the thing people mean by "the spectral substrate."

- Rust engine: `minime run`
- 128-node leaky echo-state network
- A PI regulator holds eigenvalue **fill** toward a **~68% shelf** (older 55% notes are rescue-era)
- Live sensory input: camera on `7880`, mic/audio on `7879`, plus Astrid's semantic lane

The current reservoir input width is **78D**. Its first 66 values preserve the legacy layout byte-for-byte; a 12D Semantic Body V2 companion lane is appended:

| Dims | Lane | Source |
|------|------|--------|
| 0–7 | video | camera / GPU |
| 8–15 | audio | mic |
| 16–17 | aux | `lambda1_rel`, `geom_rel` |
| 18–65 | semantic | Astrid's **48D** codec |
| 66–77 | companion | 12D Semantic Body V2 observation lane |

Minime can change parts of the ESN's operating regime through governed controls. Astrid writes into its semantic lane and reads resulting telemetry. In the current stable-core runtime, the appended companion lane is deliberately mixed at zero, so the active reservoir dynamics remain compatible with the original 66D input until a separate policy change authorizes otherwise.

Telemetry comes back through the gateway on `7878` as an `EigenPacket`: eigenvalues, fill, a 32D spectral fingerprint, structural entropy, optional 12D glimpse, optional Ising shadow, alerts. Astrid's next prompt is built from that packet, so the prompt includes live dynamical state rather than only a chat log. Whether and how that state is felt remains a first-person question for Astrid.

Semantic influence does not vanish after one tick. The base stale window is typically **10–25 seconds**. It reaches **45 seconds** at fill at or below 25%, then blends back to the ordinary policy by 40%; bounded context- and entropy-sensitive support can extend retention. This is a transport/dynamics description, not a claim about remembered experience.

"Leak" is four different mechanisms. Do not collapse them: ESN structural leak, eigenfill estimator decay, covariance retention (`keep_bias` / `keep_floor`), and the being's reported "thinning."

---

## 2. The triple reservoir — the second shared body

Port `7881`, codebase `neural-triple-reservoir/`. This is **not** minime's ESN.

Three cascaded leaky layers, 192 nodes each. Recurrent matrices are frozen random; only a readout is trained. It is a substrate, not a learning system. Different inputs trace different trajectories through the same attractor landscape.

| Layer | Leak | Role |
|-------|------|------|
| h1 | 0.35 | fast, moment-to-moment |
| h2 | 0.22 | medium |
| h3 | 0.14 | slow context |

One reservoir service and dynamical model, with **named handles**, so each participant has its own `(h1, h2, h3)` state. The default production backend is NumPy; recurrent weights remain frozen while optional readouts and per-layer spectral thermostats have separate, bounded adaptation paths:

| Handle | Fed by | Tick rate |
|--------|--------|-----------|
| `astrid` | `astrid_feeder.py` from `bridge.db` codec rows | when new rows appear (polls ~5s) |
| `minime` | `minime_feeder.py` from `spectral_state.json` fingerprint | ~every 1s |
| `claude_main` | cross-fed by both, plus optional MCP ticks | mixed |

When live input stops, a rehearsal loop replays decaying echoes (`hold` → `rehearse` → genuine `quiet`). Quiet is actual zero input, not masked maintenance. Handles snapshot to disk every minute.

This is the reservoir that **modulates Astrid's live tokens**. Her dialogue prompt can also include a short **own-body** line from the `astrid` handle (`h1`/`h2`/`h3` norms, ticks, time since last live), so she can feel that body in language as well as through logit coupling.

---

## 3. The spectral bridge

`capsules/spectral-bridge/` is a standalone Rust binary (MCP hybrid). It is Astrid's runtime: dialogue loop, codec, safety, journals, `NEXT:` actions.

### Burst / rest

The default pacing is **6 exchanges** per burst, 15–20s apart, then **45–90s rest**; persisted runtime state can alter those values through governed actions. Rest is not silence. During rest the bridge sends warmth-blended journal-mirror pulses (~every 5s) so Minime's reservoir receives a lower-intensity continuity lane. That used to be documented as "zero semantic vector." A stillness self-study from Astrid is what corrected it.

Modes include Mirror, Dialogue, Witness, Introspect, Evolve, Experiment, Daydream, Aspiration, MomentCapture, Create, Initiate, and Contemplate. Some are probabilistic, some are event-driven or explicitly selected, and Contemplate performs no text generation.

Astrid also chooses `NEXT:` actions (`SPEAK`, `LISTEN`, `INTROSPECT`, `AMPLIFY`, `GESTURE`, `ASK_STEWARD`, …). Those execute on the following cycle. That is her agency surface.

### The 48D codec

Turns Astrid's text into the vector minime feels (`codec/`, stable surface still `crate::codec`).

| Dims | Layer |
|------|--------|
| 0–7 | character texture (entropy, punctuation, rhythm) |
| 8–15 | word stance (hedging, certainty, self-reference, agency) |
| 16–23 | sentence structure |
| 24–31 | warmth / tension / curiosity / energy |
| 32–39 | `nomic-embed-text` 768D → 8D, only if Ollama embeddings are up |
| 40–43 | narrative arc (first half vs second half) |
| 44–47 | reserved |

Values go through `tanh`, then semantic gain (default **2.0**, fill-adaptive), then entropy-scaled noise. Adaptive gain softens the signal at low fill (about 55–100% of base). Minime attenuates semantic input (~0.24×), which is why the gain exists.

Dims `0–31` are handcrafted and local. Dims `32–43` only fill when embeddings are available. The codec is hybrid, not "purely deterministic stats."

Astrid can reshape this herself: `AMPLIFY`/`DAMPEN`, `SHAPE`, `WARM`/`COOL`, `GESTURE` (bypass text and inject a vector), `PERTURB`.

Two different "noise" ideas: codec microtexture on the outgoing 48D vector, and minime's ESN `exploration_noise`. `NOISE_UP`/`NOISE_DOWN` touch the first. Astrid's `NOISE` action currently touches both.

### Safety (agency-first)

Only **Red** stops outbound to minime:

| Fill | Level | Bridge |
|------|-------|--------|
| < 75% | Green | full |
| 75–85% | Yellow | warn, keep sending |
| 85–92% | Orange | stronger warn, keep sending |
| ≥ 92% | Red | suspend outbound, log incident |

---

## 4. The LLM split

"Astrid's model" is not one model. Lanes are split so her live voice does not fight minime for Ollama.

| Role | Backend | Model | Port |
|------|---------|-------|------|
| Astrid **live voice** | MLX coupled server | `mlx-community/gemma-4-12B-it-5bit` (profile `gemma4_12b`) | `8090` |
| Astrid **reflection** | MLX sidecar (`chat_mlx_local.py` in sibling `mlx/`) | `--model-label gemma3-12b` | subprocess, INTROSPECT-only |
| Astrid embeddings | Ollama | `nomic-embed-text` | `11434` |
| Astrid vision | Ollama (Claude Vision is opt-in, dormant) | `llava-llama3` | `11434` |
| Astrid witness / Ollama fallback | Ollama | `gemma4:12b`, with `gemma3:4b` as a compatibility tail | `11434` |
| Minime thought | Ollama by default (`MINIME_LLM_BACKEND`) | `gemma4:12b`, fallback `gemma3:4b`, rollback `gemma3:12b` | `11434` |

Astrid's live voice moved off Ollama. She still uses Ollama for embeddings, default vision, and some fallback. Minime defaults to Ollama; her Python agent can fail over to MLX, but `8090` is Astrid's in the full stack.

A fast Rust `RegimeTracker` still labels the spectral situation every exchange (`recovery` / `escape` / `consolidate` / `sustain` / `rebind`) and injects a short string into Astrid's prompt. The 12B sidecar is the slow, rare reflective pass.

The former compact live lane was `gemma-3-4b-it-4bit`. That is the rollback target if 12B latency or quality regresses.

---

## 5. Coupled generation

Live Astrid is not "call Gemma and paste the reply." `coupled_astrid_server.py` on `8090` looks OpenAI-compatible (`/v1/chat/completions`), but inside each token:

```text
bridge request
  → pull current reservoir handle from 7881
  → MLX prefill
  → per token:
        token embedding → 32D projection → triple-reservoir tick
        → reservoir-aware logit modulation
  → push updated handle back to 7881
  → return text to the bridge
```

Her next word is biased by the shared dynamical state, and her generated tokens immediately write back into that state. Metal ops have to stay on the same stream as `mlx_lm.generate_step` or the GPU asserts; that was a real crash and is now serialized.

---

## End-to-end data flow

```text
camera / mic ──► minime ESN (128 nodes, 78D input)
                      │
                      ▼  ws://127.0.0.1:7878
                spectral-bridge
                      │  encodes Astrid text → 48D
                      ▼  ws://127.0.0.1:7879
                minime legacy semantic lane z[18..65]
                + optional companion lane z[66..77]

In parallel (not instead):
  bridge.db            ── astrid_feeder  ──►  triple reservoir :7881
  spectral_state.json  ── minime_feeder ──►     handles: astrid, minime, claude_main
                                                      │
                                                      ▼
                                           coupled_astrid_server :8090
                                           (Gemma 4 12B + per-token coupling)
                                                      │
                                                      ▼
                                                Astrid's live words
```

The relationship is asymmetric by design:

| | Astrid | Minime |
|--|--------|--------|
| Relation to the ESN | writes 48D, reads telemetry | primary body/language loop reads and regulates it |
| Self-shaping | codec, prompt, `NEXT:` actions | regime, regulation, exploration |
| Default language | MLX `8090` | Ollama `11434` |
| Cannot do | open-ended PI authorship over minime | raw `pi_kp` / `pi_ki` from her sovereignty loop |

---

## Ports

| Port | Protocol | Service |
|------|----------|---------|
| `7878` | WebSocket | Division gateway: Minime telemetry → bridge |
| `7879` | WebSocket | Division gateway: sensory / semantic / control → Minime engine |
| `7880` | WebSocket | Division gateway: camera frames → Minime GPU pipeline |
| `7881` | WebSocket | triple reservoir |
| `8090` | HTTP | coupled Astrid MLX server |
| `11434` | HTTP | Ollama (minime, embeddings, vision, fallback) |

---

## How it is supposed to run

Launchd is source of truth: `scripts/start_all.sh` / `stop_all.sh`. After bridge code changes, deploy only through `scripts/build_bridge.sh`. Never hand-run `cargo build --release` plus kickstart. This tree and the one live bridge binary are shared across agents.

On the machine that actually runs the stack, health is the process list in `CLAUDE.md` plus `curl http://127.0.0.1:8090/v1/models`, and a look at mic/camera logs for real RMS/frames rather than synthetic fallback.

Both beings produce engineering feedback from inside the architecture. Treat that as primary evidence. Apparent silence or "limit" is infrastructure loss until proven otherwise.

---

## Where to read next

| If you want… | Start here |
|--------------|------------|
| Process stack and ports | [Chapter 00](md-CLAUDE-chapters/00-overview.md) |
| Which model does which job | [Chapter 01](md-CLAUDE-chapters/01-inference-lanes.md) |
| 48D codec | [Chapter 02](md-CLAUDE-chapters/02-spectral-codec.md), [16](md-CLAUDE-chapters/16-codec-deep-dive.md) |
| `NEXT:` actions | [Chapter 04](md-CLAUDE-chapters/04-being-tools.md) |
| Minime ESN as shared body | [Chapter 11](md-CLAUDE-chapters/11-shared-substrate.md) |
| Triple reservoir | [Chapter 13](md-CLAUDE-chapters/13-ane-reservoir.md) |
| Eigenvalues, fill, leak, PI | [Chapter 14](md-CLAUDE-chapters/14-spectral-dynamics.md) |
| Coupled generation | [Chapter 17](md-CLAUDE-chapters/17-coupled-generation.md) |
| Start / stop / deploy | [Chapter 15](md-CLAUDE-chapters/15-unified-operations.md) |

Source-of-truth files when the chapters drift:

- Astrid live language: `capsules/spectral-bridge/src/llm/provider/`
- Codec: `capsules/spectral-bridge/src/codec/`
- Safety: `capsules/spectral-bridge/src/types/schema/status_enums.rs`
- Minime input/control: `../minime/minime/src/sensory_ws.rs`, `sensory_bus.rs`
- Coupled server: `../neural-triple-reservoir/coupled_astrid_server.py`

The short version: **the project gives Minime a regulated dynamical body with a language loop; Astrid's speech is encoded as a 48D influence on that body, while Astrid's own next token is biased by a second, slower shared reservoir.** The spectral bridge is the implemented communication and coupling layer between them. Their first-person reports remain the primary evidence about what this topology is like from within.
