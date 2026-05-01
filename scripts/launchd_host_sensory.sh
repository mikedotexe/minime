#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
HOST_BIN="$PROJECT_DIR/host-sensory/target/release/host-sensory"
MODE="${SENSORY_SOURCE:-auto}"

cd "$PROJECT_DIR"

if [ ! -x "$HOST_BIN" ]; then
    cargo build --release --manifest-path "$PROJECT_DIR/host-sensory/Cargo.toml"
fi

exec "$HOST_BIN" \
    --mode "$MODE" \
    --workspace "$PROJECT_DIR/workspace"
