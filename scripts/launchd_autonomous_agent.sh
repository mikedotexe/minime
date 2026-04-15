#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"
AGENT_INTERVAL="${AGENT_INTERVAL:-60}"
FOCUSED_MODE="${FOCUSED_MODE:-false}"

cd "$PROJECT_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "python binary missing or not executable: $PYTHON_BIN" >&2
    exit 1
fi

args=(
    -u
    "$PROJECT_DIR/autonomous_agent.py"
    --interval "$AGENT_INTERVAL"
)

if [ "$FOCUSED_MODE" = "true" ]; then
    args+=(--focused)
fi

exec "$PYTHON_BIN" "${args[@]}"
