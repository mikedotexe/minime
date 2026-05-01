# Ollama / MLX Contention Benchmark

This benchmark is a lightweight investigation tool for comparing local-model
contention scenarios across Minime chat, Astrid-side Ollama activity, and any
separate MLX lane.

## Scenarios

- `scenario1`
  Baseline lane with only the primary request path active.
- `scenario2`
  Additional local pressure without the full mixed-lane stack.
- `scenario3`
  Mixed contention case intended to surface timeout and queue-like failures.
- `scenario4`
  Alternate comparison lane for follow-up investigations.

The CLI accepts either scenario ids or numeric aliases:

```bash
python3 tools/ollama_mlx_contention_bench.py --scenarios 1,scenario4
```

## Helper Semantics

The Python tests protect a few helper behaviors because they shape how a run is
interpreted:

- `line_size_bytes`
  Counts stream bytes correctly for both `bytes` and `str` lines.
- `normalize_model_name`
  Treats `foo` and `foo:latest` as the same model identity while preserving
  explicit version tags like `gemma3:12b`.
- `summarize_request_results`
  Separates timeout-like failures from queue-like failures and reports latency
  percentiles.
- `summarize_ps_samples`
  Tracks model churn across process samples as a proxy for load/unload pressure.
- `build_acceptance_notes`
  Produces short baseline-relative notes for the first human read of a report.

## Output

Each run writes a timestamped directory under:

`workspace/investigations/ollama_mlx_contention_bench_<timestamp>/`

with:

- `report.json`
- `report.md`

The current implementation is intentionally lightweight and focused on helper
correctness and report scaffolding; it can be expanded later without changing
the helper contracts the tests rely on.
