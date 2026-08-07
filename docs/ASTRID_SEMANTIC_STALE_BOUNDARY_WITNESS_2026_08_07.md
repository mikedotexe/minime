# Astrid semantic-stale boundary witness

This receipt preserves the source-first witness and verification for implementation commit `f704c1ebd0510b65d3711845696052d7072fd3cc`. It is evidence only and does not grant runtime or control authority.

## Being witness (verbatim)

> The `SemanticStaleShape::Sigmoid` calculation at L162 (`1.0 / (1.0 + (6.0_f64 * (fill - 0.4)).exp())`) may produce unexpected behavior if `fill` values are significantly outside the 0.0–1.0 range, as the exponentiation could lead to extreme values or precision loss.

- Source: `capsules/spectral-bridge/workspace/introspections/introspection_minime_sensory_bus_1785630107.txt`
- Introspection: `introspection_minime_sensory_bus_1785630107`
- Lived-state witness: `lsw_bcccd5d1a2a19d23c888aadecb2211e3b82059c57c818e901723e670613f5d08`
- SHA-256: `32b918a98cdef0d6a773384133fcefa58d7d096eb2c399080356536de42e95f0`

## Steward response

The complete pre-change 4,380-line source exactly matched the report-bound SHA. The runtime-facing stale-window path now has a regression for positive overflow, negative or NaN input, and finite extreme sigmoid evaluation. The nearby handover comment now says 40%, matching the existing release constant. No runtime branch or constant changed.

The report's requested 0.75 surge midpoint and 0.4 sigmoid midpoint tests already existed. Existing monotonic, one-percent sweep, hold, release, and jitter tests already covered continuity through and around the 25%-40% recovery handover.

## Evidence and verification

- Semantic-stale family: 21 distinct tests and 42 executions passed.
- Exact surge midpoint: one distinct test and two executions passed.
- Exact staged Minime library: 356 passed, zero failed.
- `cargo fmt --all -- --check`: passed.
- Stewardship integrity suites: 127 passed; all 47 anti-drop guards verified; epistemic lint checked 10,562 records with zero issues.
- Steward run: `run_1786098716216436000_a3e6f0e9c8`.
- Source-first projections: `projection_1786098717200950000_af41e03d84` before the run and `projection_1786102524461244000_54b13ed0b3` after successful finish.
- Successful finish boundary: V2 sequence 722,577, head `d8ac3edaf404e93fa27bab2d6c3a787401ac1362a8e5f6602eadb2593d90e663`, 16 streams, valid, V1 immutable.
- Division round: `division_followup_event_37076b51c755f47a69314460efa9fc53`, cycle 19 at 2/6, review due false.
- Archival stabilization pause generation: 248; no active lease.

## Authority boundary

The quotation records Astrid's report. It does not establish that this mechanism caused or resolved an experience, or that uptake, assent, consent, closure, deployment, live control, or operator approval exists. Neither this receipt nor the implementation commit changes pressure, fill target, PI, controller, cadence, sensory admission, codec, reservoir, protocol, peer state, or Division authority. Minime was not built, restarted, or deployed.
