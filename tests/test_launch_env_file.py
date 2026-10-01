"""The agent's LLM budget must survive a reboot (2026-10-01): launchd/autonomous-agent.env
is sourced by the launch wrapper before the `launchctl getenv` import loop."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env_values() -> dict:
    values = {}
    for line in (ROOT / "launchd/autonomous-agent.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_durable_env_restores_the_pre_reboot_budget():
    values = _env_values()
    assert values["MINIME_LLM_TIMEOUT_S"] == "160"
    assert values["MINIME_LLM_FALLBACK_TIMEOUT_S"] == "160"
    assert values["MINIME_FALLBACK_MODEL"] == "gemma4:12b"


def test_launch_wrapper_sources_durable_env_before_launchctl():
    script = (ROOT / "scripts/launchd_autonomous_agent.sh").read_text()
    source_at = script.index('. "$ENV_FILE"')
    getenv_at = script.index("launchctl_env() {")
    assert source_at < getenv_at, "env file must be sourced before launchctl getenv overrides"
    assert re.search(r'ENV_FILE="\$PROJECT_DIR/launchd/autonomous-agent\.env"', script)
    assert "set -a" in script[:source_at]


def test_fallback_equal_to_primary_drops_the_small_model():
    import autonomous_agent as aa
    assert aa._llm_backend_attempts("ollama", "gemma4:12b", "gemma4:12b") == ["ollama"]
    assert aa._llm_backend_attempts("ollama", "gemma4:12b", "gemma3:4b") == ["ollama", "ollama_fast"]


def test_env_file_is_part_of_the_verified_launch_inventory():
    from minime_autonomy.deployment import source_inputs
    assert "launchd/autonomous-agent.env" in source_inputs(ROOT)
