"""Unit tests for the launchd-aware model canary helpers."""

from __future__ import annotations

import importlib.util
import argparse
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/minime_model_canary.py"
SPEC = importlib.util.spec_from_file_location("minime_model_canary", SCRIPT)
assert SPEC and SPEC.loader
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


def test_log_event_counts_detect_fallbacks_next_and_artifacts():
    counts = canary.count_log_events(
        {
            "agent.log": "\n".join(
                [
                    "LLM query failed (ollama): timeout",
                    "Falling back to mlx...",
                    "LLM fallback succeeded via mlx",
                    "Falling back to ollama_fast...",
                    "Unknown NEXT: PERFORM_SEARCH foo",
                    "raw token leak <turn|><eos>",
                ]
            )
        }
    )

    assert counts["fallback_count"] == 2
    assert counts["fallback_line_count"] == 2
    assert counts["malformed_next_count"] == 1
    assert counts["artifact_count"] == 2
    assert "<turn|>" in counts["artifact_matches"]
    assert "<eos>" in counts["artifact_matches"]


def test_log_event_counts_groups_adjacent_fallback_cascade_as_one_incident():
    counts = canary.count_log_events(
        {
            "agent.log": "\n".join(
                [
                    "LLM query failed (ollama): timeout",
                    "Falling back to mlx...",
                    "LLM query failed (mlx): timeout",
                    "Falling back to ollama_fast...",
                    "LLM fallback succeeded via ollama_fast",
                ]
            )
        }
    )

    assert counts["fallback_count"] == 1
    assert counts["fallback_line_count"] == 2


def test_sustained_above_uses_longest_contiguous_run():
    samples = [
        {"t_s": 0.0, "stable_core": {"fill_pct": 84.0}},
        {"t_s": 30.0, "stable_core": {"fill_pct": 86.0}},
        {"t_s": 60.0, "stable_core": {"fill_pct": 87.0}},
        {"t_s": 90.0, "stable_core": {"fill_pct": 80.0}},
        {"t_s": 120.0, "stable_core": {"fill_pct": 90.0}},
        {"t_s": 180.0, "stable_core": {"fill_pct": 91.0}},
    ]

    assert canary.sustained_above(samples, 85.0) == 60.0
    assert canary.max_fill(samples) == 91.0


def test_load_record_from_stdout_finds_json_path(tmp_path):
    record_path = tmp_path / "canary_result.json"
    record_path.write_text(json.dumps({"summary": {"automated_ok": True}}), encoding="utf-8")

    path, record = canary.load_record_from_stdout(f"noise\n{record_path}\n")

    assert path == record_path
    assert record == {"summary": {"automated_ok": True}}


def test_row_phase_command_includes_tuning_env_args(tmp_path):
    args = argparse.Namespace(
        fallback_model="gemma3:4b",
        agent_interval=60,
        fallback_num_ctx=8192,
        fallback_num_predict_cap=1024,
        smoke_duration_secs=900.0,
        normal_duration_secs=7200.0,
        sample_interval_secs=30.0,
        start_timeout_secs=90.0,
        request_timeout_secs=90.0,
        thin_output_min_chars=20,
    )
    row = {
        "name": "tuned_gemma4_12b",
        "model": "gemma4:12b",
        "num_ctx": 8192,
        "num_predict_cap": 768,
        "llm_timeout_s": 60.0,
    }

    cmd = canary.row_phase_command(
        row=row,
        phase="smoke",
        args=args,
        row_output_dir=tmp_path,
    )

    assert "--model" in cmd and "gemma4:12b" in cmd
    assert "--num-ctx" in cmd and "8192" in cmd
    assert "--num-predict-cap" in cmd and "768" in cmd
    assert "--llm-timeout-secs" in cmd and "60.0" in cmd
    assert "--thin-output-min-chars" in cmd and "20" in cmd


def test_timing_summary_flags_thin_primary_outputs_only():
    records = [
        {
            "backend": "ollama",
            "model": "gemma4:12b",
            "status": "ok",
            "response_chars": 3,
        },
        {
            "backend": "ollama_fast",
            "model": "gemma3:4b",
            "status": "ok",
            "response_chars": 2,
        },
        {
            "backend": "ollama",
            "model": "gemma3:12b",
            "status": "ok",
            "response_chars": 1,
        },
        {
            "backend": "ollama",
            "model": "gemma4:12b",
            "status": "timeout",
            "response_chars": 0,
            "error": "ReadTimeout",
        },
    ]

    summary = canary.summarize_timing_records(
        records,
        primary_model="gemma4:12b",
        thin_output_min_chars=20,
    )

    assert summary["primary_call_count"] == 2
    assert summary["primary_timeout_count"] == 1
    assert summary["thin_primary_output_count"] == 1


def test_start_normal_stack_uses_force_and_shared_wait(monkeypatch):
    commands = []
    waited = []

    monkeypatch.setattr(canary, "stop_minime_labels", lambda: [{"stopped": True}])

    def fake_run_cmd(cmd, *, cwd=canary.MINIME_ROOT, timeout=30.0):
        commands.append(cmd)
        return {"cmd": cmd, "returncode": 0, "elapsed_s": 0.0, "stdout": ""}

    def fake_wait_labels_running(labels, timeout_s):
        waited.append((labels, timeout_s))
        return {label: {"ok": True, "state": {"state": "running"}} for label in labels}

    monkeypatch.setattr(canary, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(canary, "wait_labels_running", fake_wait_labels_running)

    result = canary.start_normal_stack(42.0)

    assert result["mode"] == "normal"
    assert commands
    assert "--force" in commands[0]
    assert waited == [(canary.NORMAL_LABELS, 42.0)]


def test_start_smoke_stack_uses_force_then_removes_sensory_labels(monkeypatch):
    commands = []
    waited = []
    booted_out = []

    monkeypatch.setattr(canary, "stop_minime_labels", lambda: [{"stopped": True}])

    def fake_run_cmd(cmd, *, cwd=canary.MINIME_ROOT, timeout=30.0):
        commands.append(cmd)
        return {"cmd": cmd, "returncode": 0, "elapsed_s": 0.0, "stdout": ""}

    def fake_wait_labels_running(labels, timeout_s):
        waited.append((labels, timeout_s))
        return {label: {"ok": True, "state": {"state": "running"}} for label in labels}

    def fake_bootout_label(label):
        booted_out.append(label)
        return {"label": label, "booted_out": True}

    monkeypatch.setattr(canary, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(canary, "wait_labels_running", fake_wait_labels_running)
    monkeypatch.setattr(canary, "bootout_label", fake_bootout_label)

    result = canary.start_smoke_stack(42.0)

    assert result["mode"] == "smoke"
    assert commands
    assert "--force" in commands[0]
    assert waited == [(canary.CORE_LABELS, 42.0), (canary.CORE_LABELS, 42.0)]
    assert tuple(booted_out) == canary.SENSORY_LABELS


def test_start_failure_reasons_names_script_and_missing_labels():
    reasons = canary.start_failure_reasons(
        {
            "actions": [{"script": "start_all.sh", "result": {"returncode": 1}}],
            "waits": {
                "com.minime.engine": {"ok": True},
                "com.minime.autonomous-agent": {"ok": False},
            },
        }
    )

    assert "start_script_failed" in reasons
    assert "labels_not_running:com.minime.autonomous-agent" in reasons


def test_main_matrix_keeps_e4b_out_of_autonomous_promotion_rows():
    assert all(row["model"] != "gemma4:e4b" for row in canary.MATRIX_ROWS)
    assert canary.DEFAULT_EDGE_SIDECAR_MODEL == "gemma4:e4b"


def test_gemma4_probe_messages_do_not_use_no_think_and_can_compact():
    long_system = "System.\n" + ("Allowed NEXT: REST.\n" * 1200)
    long_prompt = "Prompt.\n" + ("Stable-core telemetry context.\n" * 1200)

    messages, adapter = canary.build_ollama_messages(
        model="gemma4:12b",
        system_msg=long_system,
        user_prompt=long_prompt,
        num_ctx=8192,
        num_predict=768,
        compact_prompt=True,
    )

    assert adapter["prompt_template_mode"] == "gemma4_think_false_native"
    assert adapter["prompt_compacted"]
    assert not messages[1]["content"].startswith("/no_think")


def test_legacy_probe_messages_keep_no_think_prefix():
    messages, adapter = canary.build_ollama_messages(
        model="gemma3:12b",
        system_msg="System.",
        user_prompt="Prompt.",
        num_ctx=8192,
        num_predict=768,
    )

    assert adapter["prompt_template_mode"] == "legacy_no_think_user_prefix"
    assert messages[1]["content"].startswith("/no_think\n")
