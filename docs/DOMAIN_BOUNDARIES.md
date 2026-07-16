# Minime Domain Boundaries

The July 2026 extraction preserves process paths, packets, calculations, and
control behavior while making ownership visible and testable.

## Rust

- `minime/src/main.rs` is a 30-line binary facade. `runtime.rs` assembles CLI,
  wire, review, telemetry, spectral math, adapters, and orchestration modules.
- `minime/src/regulator.rs` is a six-line compatibility facade. Regulator types,
  pressure source, viscosity, resonance evidence, rate gating, PI, and reviews
  live in separate modules behind `regulator/core.rs`.
- Telemetry assembly/broadcast and read-only evidence are separate from stable
  core regulation and pressure/rescue ownership. Ports and calculations are
  unchanged.

`runtime/orchestration.rs` remains a deliberate cohesion exception: the
ordered engine loop is 5,787 lines and still owns one mutable tick transaction.
The 1,244-line runtime test registry and 2,562-line regulator test registry are
test-data exceptions. All other extracted Rust production modules are below
1,000 lines.

## Python

`autonomous_agent.py` remains the stable import and CLI identity used by launchd
and existing tests. `minime_autonomy/runtime.py` is the compatibility assembly.
Canonical implementations now live in bounded modules for:

- action vocabulary and parsing;
- research parsing, quality, rendering, and memory admission;
- bounded self-regulation evidence;
- runtime-action parsing and experiment preflight;
- LLM job persistence;
- authority preflight and capability mapping; and
- append-only continuity repair.

Memory, correspondence, journaling, and attractor modules define the stable
ownership protocols while their mutable `AutonomousAgent` method clusters remain
in `runtime.py`. The event-sourced `ActionContinuityStore` and the mutable
`AutonomousAgent` are deliberate staged exceptions: moving either safely now
requires decomposing shared mutable state into injected stores, not another
textual relocation. Source monitoring resolves the historical
`autonomous_agent.py` label to the substantive runtime assembly.

These exceptions are architecture debt, not exemptions from future extraction.
New pure logic and new stores belong in the named modules. Structural guards,
direct-import smoke tests, parser snapshots, continuity suites, and complete
Python tests preserve the public surface and behavior.
