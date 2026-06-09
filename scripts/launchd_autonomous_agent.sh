#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/v/other/minime"
PYTHON_BIN="${MINIME_PYTHON_BIN:-/opt/homebrew/bin/python3}"
INVESTIGATION_SCRIPT="$PROJECT_DIR/scripts/minime_rescue_investigation.py"
AGENT_INTERVAL="${AGENT_INTERVAL:-60}"
FOCUSED_MODE="${FOCUSED_MODE:-false}"

cd "$PROJECT_DIR"

launchctl_env() {
    local key="$1"
    local value
    value="$(/bin/launchctl getenv "$key" 2>/dev/null || true)"
    if [ -n "$value" ]; then
        export "$key=$value"
    fi
}

for key in \
    MINIME_MODEL \
    MINIME_FALLBACK_MODEL \
    MINIME_LLM_BACKEND \
    MINIME_LLM_TIMEOUT_S \
    MINIME_LLM_FALLBACK_TIMEOUT_S \
    MINIME_LLM_COMPACT_TIMEOUT_S \
    MINIME_LLM_COMPACT_FALLBACK_TIMEOUT_S \
    MINIME_OLLAMA_NUM_CTX \
    MINIME_OLLAMA_NUM_PREDICT_CAP \
    MINIME_OLLAMA_FALLBACK_NUM_CTX \
    MINIME_OLLAMA_FALLBACK_NUM_PREDICT_CAP \
    AGENT_INTERVAL \
    FOCUSED_MODE
do
    launchctl_env "$key"
done

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

MINIME_HARD_RECOVERY_RESET="${MINIME_HARD_RECOVERY_RESET:-1}"
export MINIME_HARD_RECOVERY_RESET

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
