#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
ENGINE_BIN="$PROJECT_DIR/minime/target/release/minime"
INVESTIGATION_SCRIPT="$PROJECT_DIR/scripts/minime_rescue_investigation.py"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"

cd "$PROJECT_DIR"

if [ ! -x "$ENGINE_BIN" ]; then
    echo "minime engine binary missing or not executable: $ENGINE_BIN" >&2
    exit 1
fi

if [ -x "$PYTHON_BIN" ] && [ -f "$INVESTIGATION_SCRIPT" ] && [ -f "$PROJECT_DIR/workspace/rescue_profile.json" ]; then
    profile_runtime="$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
profile = json.loads(Path("/Users/v/other/minime/workspace/rescue_profile.json").read_text())
print(profile.get("runtime_profile") or "")
PY
)"
    if [ "$profile_runtime" = "stable_core_v1" ]; then
        set -a
        eval "$("$PYTHON_BIN" "$INVESTIGATION_SCRIPT" emit-launch-env)"
        set +a
    fi
fi

SENSORY_SOURCE="${SENSORY_SOURCE:-auto}"
EIGENFILL_TARGET="${EIGENFILL_TARGET:-0.68}"
MINIME_HARD_RECOVERY_RESET="${MINIME_HARD_RECOVERY_RESET:-1}"
WARM_START_BLEND="${WARM_START_BLEND:-0.55}"
REG_TICK_SECS="${REG_TICK_SECS:-0.5}"
ENABLE_GPU_AV="${ENABLE_GPU_AV:-true}"
MINIME_DIVISION_GATEWAY_ENABLED="${MINIME_DIVISION_GATEWAY_ENABLED:-false}"
LEGACY_AUDIO_ENABLED="${LEGACY_AUDIO_ENABLED:-}"
LEGACY_VIDEO_ENABLED="${LEGACY_VIDEO_ENABLED:-}"

if [ -z "$LEGACY_AUDIO_ENABLED" ]; then
    # Legacy synth only when explicitly "physical" — with "auto" or "host",
    # real sensory + host-sensory provide input, making synth redundant.
    if [ "$SENSORY_SOURCE" = "physical" ]; then
        LEGACY_AUDIO_ENABLED=true
    else
        LEGACY_AUDIO_ENABLED=false
    fi
fi

if [ -z "$LEGACY_VIDEO_ENABLED" ]; then
    if [ "$SENSORY_SOURCE" = "physical" ]; then
        LEGACY_VIDEO_ENABLED=true
    else
        LEGACY_VIDEO_ENABLED=false
    fi
fi

args=(
    run
    --log-homeostat
    --eigenfill-target "$EIGENFILL_TARGET"
    --warm-start-blend "$WARM_START_BLEND"
    --reg-tick-secs "$REG_TICK_SECS"
    --legacy-audio-synth-enabled "$LEGACY_AUDIO_ENABLED"
    --legacy-video-synth-enabled "$LEGACY_VIDEO_ENABLED"
)

if [ "$MINIME_DIVISION_GATEWAY_ENABLED" = "true" ]; then
    args+=(
        --ws-addr 127.0.0.1:7900
        --sensory-ws-addr 127.0.0.1:7901
        --av-ws-addr 127.0.0.1:7902
    )
fi

export MINIME_HARD_RECOVERY_RESET

if [ "$ENABLE_GPU_AV" = "true" ]; then
    args+=(--enable-gpu-av)
fi

exec "$ENGINE_BIN" "${args[@]}"
