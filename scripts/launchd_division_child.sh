#!/bin/bash
set -euo pipefail

ROOT="/Users/v/other/minime"
ENGINE="$ROOT/minime/target/release/minime"
BEING="${1:?being required}"

case "$BEING" in
    minime) WORKSPACE="$ROOT/workspace/reservoir/minime" ;;
    astrid) WORKSPACE="/Users/v/other/astrid/capsules/spectral-bridge/workspace/reservoir/astrid" ;;
    *) echo "invalid daughter being: $BEING" >&2; exit 64 ;;
esac

BUNDLE="$WORKSPACE/seed-bundle.json"
test -x "$ENGINE"
test -f "$BUNDLE"
exec "$ENGINE" division child --being "$BEING" --bundle "$BUNDLE" --workspace "$WORKSPACE"
