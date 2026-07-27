#!/bin/bash
set -euo pipefail

ROOT="/Users/v/other/minime"
ENGINE="$ROOT/minime/target/release/minime"
MANIFEST="$ROOT/workspace/division/runtime-manifest.json"

test -x "$ENGINE"
test -f "$MANIFEST"
exec "$ENGINE" division gateway --manifest "$MANIFEST"
