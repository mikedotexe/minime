#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"
CAMERA_INDEX="${CAMERA_INDEX:-0}"
LOOK_SOURCE="${LOOK_SOURCE:-active}"

cd "$PROJECT_DIR"

exec "$PYTHON_BIN" "$PROJECT_DIR/visual_frame_service.py" \
    --camera "$CAMERA_INDEX" \
    --interval 5 \
    --source "$LOOK_SOURCE"
