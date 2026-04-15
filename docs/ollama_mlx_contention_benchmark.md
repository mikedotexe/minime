# Ollama / MLX Contention Benchmark

This benchmark codifies the four local-stack scenarios from the April 2, 2026
assessment of Minime, Astrid, Ollama `0.19.x`, and the dedicated Astrid MLX
lane on the M4 Mac mini.

## What it measures

- Scenario 1: Minime chat alone on Ollama
- Scenario 2: Minime chat plus Astrid embedding traffic on Ollama
- Scenario 3: Scenario 2 plus LLaVA / perception traffic on Ollama
- Scenario 4: Scenario 3 plus Astrid live MLX dialogue on port `8090`

For each scenario the tool records:

- Minime chat latency and TTFT
- Auxiliary request latency for embeddings, LLaVA, and Astrid MLX chat
- Timeout and queue-like error counts
- Ollama `/api/ps` residency transitions, including model load/unload churn
- Launchd scheduler settings such as `OLLAMA_MAX_LOADED_MODELS`

## Usage

From `/Users/v/other/minime`:

```bash
python3 tools/ollama_mlx_contention_bench.py --iterations 5
```

Useful flags:

```bash
python3 tools/ollama_mlx_contention_bench.py --scenarios 1,3,4
python3 tools/ollama_mlx_contention_bench.py --iterations 3 --cleanup-nonbaseline-models
python3 tools/ollama_mlx_contention_bench.py --output-dir workspace/investigations/manual_ollama_probe
```

Artifacts are written to:

```text
workspace/investigations/ollama_mlx_contention_bench_<timestamp>/
```

The directory contains:

- `report.json` for raw and summarized measurements
- `report.md` for a quick human-readable readout

## Interpretation

- A better Ollama engine does not create a second scheduler. If Scenarios 2-3
  regress relative to Scenario 1, the shared `11434` lane is still the likely
  pressure point.
- If Scenario 4 regresses relative to Scenario 3 without extra Ollama churn,
  the likely pressure point is shared unified-memory / accelerator contention
  across Ollama, Astrid MLX, and Minime's Rust/Metal workload.
- `--cleanup-nonbaseline-models` is useful when you want to probe LLaVA load
  pressure without leaving the vision model resident afterward.
