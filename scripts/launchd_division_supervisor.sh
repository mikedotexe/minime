#!/bin/bash
set -euo pipefail

ROOT="/Users/v/other/minime"
ENGINE="$ROOT/minime/target/release/minime"
MANIFEST="$ROOT/workspace/division/runtime-manifest.json"

HOLD="$ROOT/workspace/runtime/engine-release-holds/com.minime.division-supervisor.json"
while [ -e "$HOLD" ] || [ -L "$HOLD" ]; do sleep 1; done

test -x "$ENGINE"
test -f "$MANIFEST"
exec "$ENGINE" division supervisor --manifest "$MANIFEST"
