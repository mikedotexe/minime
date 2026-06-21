#!/bin/bash
set -euo pipefail

# Read-only logger of minime's full eigenvalue spectrum (λ1..λ8, incl. λ4) → a per-tick
# JSONL time-series for her `th_minime_20260605` "disrupted λ4 decay" investigation, which
# had no per-tick λ4 record. Polls spectral_state.json (no socket → no hang). Non-engine.

PROJECT_DIR="/Users/v/other/minime"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/workspace/diagnostics"

# --interval 0.5: snapshots arrive ~1.15s apart; polling faster than that (with
# snapshot_sequence dedup) captures every engine snapshot exactly once — no aliasing of the
# observed λ4 alternation, no duplicates.
exec "$PYTHON_BIN" "$PROJECT_DIR/scripts/eigen_spectrum_logger.py" --interval 0.5
