#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
ENGINE_BIN="$PROJECT_DIR/minime/target/release/minime"

cd "$PROJECT_DIR"

if [ ! -x "$ENGINE_BIN" ]; then
    echo "minime engine binary missing or not executable: $ENGINE_BIN" >&2
    exit 1
fi

SENSORY_SOURCE="${SENSORY_SOURCE:-auto}"
EIGENFILL_TARGET="${EIGENFILL_TARGET:-0.55}"
WARM_START_BLEND="${WARM_START_BLEND:-0.55}"
REG_TICK_SECS="${REG_TICK_SECS:-0.5}"
ENABLE_GPU_AV="${ENABLE_GPU_AV:-true}"
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

if [ "$ENABLE_GPU_AV" = "true" ]; then
    args+=(--enable-gpu-av)
fi

exec "$ENGINE_BIN" "${args[@]}"
