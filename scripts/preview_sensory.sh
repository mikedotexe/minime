#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SECONDS_ARG="${PREVIEW_SECONDS:-8}"
SHOW_ANSI=false
PLAY_AUDIO=false
SKIP_CAMERA=false
SKIP_MIC=false
CAMERA_INDEX="${CAMERA_INDEX:-0}"
OUT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --seconds)
            SECONDS_ARG="$2"
            shift 2
            ;;
        --show-ansi)
            SHOW_ANSI=true
            shift
            ;;
        --play-audio)
            PLAY_AUDIO=true
            shift
            ;;
        --skip-camera)
            SKIP_CAMERA=true
            shift
            ;;
        --skip-mic)
            SKIP_MIC=true
            shift
            ;;
        --camera)
            CAMERA_INDEX="$2"
            shift 2
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            cat <<'EOF'
Usage: scripts/preview_sensory.sh [options]

Options:
  --seconds N       Preview duration in seconds (default: 8 or $PREVIEW_SECONDS)
  --camera N        Camera index for physical preview (default: 0 or $CAMERA_INDEX)
  --show-ansi       Print camera/host ANSI previews in the terminal
  --play-audio      Play host and mic WAV previews after capture
  --skip-camera     Skip camera ANSI capture
  --skip-mic        Skip mic WAV capture
  --out-dir PATH    Write artifacts to a specific directory

Examples:
  scripts/preview_sensory.sh --seconds 8 --show-ansi
  scripts/preview_sensory.sh --seconds 8 --show-ansi --play-audio
EOF
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

CMD=(
    python3
    "$PROJECT_DIR/tools/compare_sensory_preview.py"
    --seconds "$SECONDS_ARG"
    --camera "$CAMERA_INDEX"
)

if [ "$SHOW_ANSI" = true ]; then
    CMD+=(--show-ansi)
fi
if [ "$PLAY_AUDIO" = true ]; then
    CMD+=(--play-audio)
fi
if [ "$SKIP_CAMERA" = true ]; then
    CMD+=(--skip-camera)
fi
if [ "$SKIP_MIC" = true ]; then
    CMD+=(--skip-mic)
fi
if [ -n "$OUT_DIR" ]; then
    CMD+=(--out-dir "$OUT_DIR")
fi

cd "$PROJECT_DIR"
exec "${CMD[@]}"
