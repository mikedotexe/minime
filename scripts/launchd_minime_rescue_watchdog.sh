#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"

cd "$PROJECT_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "python binary missing or not executable: $PYTHON_BIN" >&2
    exit 1
fi

exec "$PYTHON_BIN" -u "$PROJECT_DIR/scripts/minime_rescue_watchdog.py"
