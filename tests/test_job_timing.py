"""Content-free timing and runtime seams, using synthetic work only."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import job_timing as timing


def checkpoint(root, job_id="job_fixture"):
    return root / "llm_jobs" / "jobs" / job_id / "phase_timings.json"


def test_nested_durations_do_not_double_count_and_final_checkpoint_is_complete(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])
    with timing.job_scope(tmp_path, job_id="job_fixture", action_id="act_fixture", thread_id="thread_fixture") as record:
        clock[0] = 1
        with timing.phase("action.execute"):
            clock[0] = 3
            with timing.phase("provider.attempt"):
                clock[0] = 7
            clock[0] = 10
        intermediate = record.summary()
        clock[0] = 12
    saved = json.loads(checkpoint(tmp_path).read_text())
    assert [(s["inclusive_s"], s["exclusive_s"]) for s in saved["spans"]] == [(9, 5), (4, 4)]
    assert saved["elapsed_s"] == 12
    assert saved["unattributed_s"] == 3
    assert saved["snapshot_complete"] is True
    assert saved["state"] == "complete"
    assert intermediate["snapshot_complete"] is False
    assert intermediate["checkpoint_file"] == "phase_timings.json"
    assert saved["action_id"] == "act_fixture"
    assert saved["thread_id"] == "thread_fixture"
    assert stat.S_IMODE(checkpoint(tmp_path).stat().st_mode) == 0o600
    assert not list(checkpoint(tmp_path).parent.glob("*.tmp"))


def test_preparation_marker_keeps_provider_time_separate(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])

    @timing.measured("query", preparation="context.assembly")
    def query():
        clock[0] = 5
        timing.finish_preparation()
        with timing.provider_attempt(backend="ollama", model="fixture:small") as attempt:
            clock[0] = 15
            attempt.record_result("Synthetic body")
        clock[0] = 17
        return "unchanged"

    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        assert query() == "unchanged"
    spans = {s["phase"]: s for s in record.summary()["spans"]}
    assert spans["context.assembly"]["inclusive_s"] == 5
    assert spans["provider.attempt"]["inclusive_s"] == 10
    assert spans["query"]["exclusive_s"] == 2


def test_provider_facts_are_content_free_and_work_without_generation_recording(tmp_path):
    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        generation_id = timing.correlate_generation()
        with timing.phase("safe.phase", prompt="SECRET_PROMPT", body="SECRET_BODY"):
            with timing.provider_attempt(backend="ollama", model="fixture:small") as attempt:
                attempt.record_result("SECRET_BODY")
            with timing.provider_attempt(backend="ollama") as attempt:
                attempt.record_result("  \n")
            with pytest.raises(RuntimeError):
                with timing.provider_attempt(backend="ollama"):
                    raise RuntimeError("SECRET_ERROR")
    saved = record.summary()
    assert saved["attempt_counts"] == {"ok": 1, "empty": 1, "error": 1}
    assert saved["generation_ids"] == [generation_id]
    assert generation_id.startswith("timing-")
    assert all(a["generation_id"] == generation_id for a in saved["attempts"])
    assert saved["attempts"][-1]["error_type"] == "RuntimeError"
    serialized = checkpoint(tmp_path).read_text()
    assert not any(secret in serialized for secret in ("SECRET_PROMPT", "SECRET_BODY", "SECRET_ERROR"))


def test_threads_and_copied_context_cannot_contaminate_other_job(tmp_path):
    barrier = threading.Barrier(2)

    def run(name):
        with timing.job_scope(tmp_path, job_id="job_" + name) as record:
            timing.correlate_generation(SimpleNamespace(generation_id="gen_" + name))
            barrier.wait(timeout=5)
            with timing.provider_attempt(backend="ollama") as attempt:
                attempt.record_result(name)
        return record.summary()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, name) for name in ("one", "two")]
        records = [future.result(timeout=10) for future in futures]
    for name, record in zip(("one", "two"), records):
        assert record["generation_ids"] == ["gen_" + name]
        assert record["attempt_counts"] == {"ok": 1, "empty": 0, "error": 0}

    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(copied.run, timing.correlate_generation).result() is None
        assert record.summary()["generation_ids"] == []


def test_nested_scope_restores_parent_and_no_scope_creates_no_files(tmp_path):
    with timing.phase("ignored"):
        assert timing.correlate_generation() is None
    with timing.job_scope(tmp_path, job_id="job_outer") as outer:
        with timing.job_scope(tmp_path, job_id="job_inner") as inner:
            timing.correlate_generation(SimpleNamespace(generation_id="gen_inner"))
        timing.correlate_generation(SimpleNamespace(generation_id="gen_outer"))
    assert outer.summary()["generation_ids"] == ["gen_outer"]
    assert inner.summary()["generation_ids"] == ["gen_inner"]
    assert timing.correlate_generation() is None


def test_errors_and_checkpoint_failure_never_replace_action_result(tmp_path, monkeypatch):
    @timing.measured("action.execute")
    def action(raise_error=False):
        if raise_error:
            raise ValueError("action error")
        return 42

    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        initial = checkpoint(tmp_path).read_text()
        monkeypatch.setattr(timing.os, "replace", Mock(side_effect=OSError("disk unavailable")))
        assert action() == 42
        with pytest.raises(ValueError, match="action error"):
            action(raise_error=True)
        assert record.summary()["persistence_errors"] > 0
    assert checkpoint(tmp_path).read_text() == initial


def test_invalid_job_and_failed_instrumentation_leave_work_unchanged(tmp_path, monkeypatch):
    with timing.job_scope(tmp_path, job_id="../escaped") as record:
        assert record.summary() == {}
    assert not (tmp_path / "llm_jobs").exists()
    with timing.job_scope(tmp_path, job_id="job_fixture"):
        monkeypatch.setattr(timing.Recorder, "begin", Mock(side_effect=RuntimeError("timing fault")))
        with timing.provider_attempt() as attempt:
            attempt.record_result("still usable")
        with timing.phase("action.execute"):
            pass


def test_exception_checkpoint_is_closed_without_serializing_exception_message(tmp_path):
    with pytest.raises(ValueError, match="private detail"):
        with timing.job_scope(tmp_path, job_id="job_fixture"):
            with timing.phase("action.execute"):
                raise ValueError("private detail")
    saved = json.loads(checkpoint(tmp_path).read_text())
    assert saved["state"] == "error"
    assert saved["spans"][0]["status"] == "error"
    assert saved["spans"][0]["error_type"] == "ValueError"
    assert "private detail" not in checkpoint(tmp_path).read_text()


def test_records_remain_bounded_but_total_attempt_counts_survive(tmp_path):
    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        for i in range(150):
            timing.correlate_generation(SimpleNamespace(generation_id=f"gen_{i}"))
            with timing.provider_attempt(backend="ollama") as attempt:
                attempt.record_result("synthetic")
    saved = record.summary()
    assert len(saved["spans"]) == timing.MAX_SPANS
    assert len(saved["attempts"]) == timing.MAX_ATTEMPTS
    assert len(saved["generation_ids"]) == timing.MAX_GENERATIONS
    assert saved["attempt_counts"]["ok"] == 150
    assert saved["dropped_spans"] == 150 - timing.MAX_SPANS
    assert saved["dropped_attempts"] == 150 - timing.MAX_ATTEMPTS
    assert len(checkpoint(tmp_path).read_bytes()) < 100_000


def test_abrupt_worker_exit_leaves_an_active_provider_checkpoint(tmp_path):
    script = f'''
import os
from minime_autonomy import job_timing as timing
with timing.job_scope({str(tmp_path)!r}, job_id="job_fixture"):
    timing.correlate_generation()
    with timing.provider_attempt(backend="ollama"):
        os._exit(0)
'''
    subprocess.run([sys.executable, "-c", script], check=True, timeout=15)
    saved = json.loads(checkpoint(tmp_path).read_text())
    assert saved["state"] == "running"
    assert saved["snapshot_complete"] is False
    assert saved["spans"][-1]["phase"] == "provider.attempt"
    assert saved["spans"][-1]["status"] == "active"
    assert len(saved["generation_ids"]) == 1


@pytest.mark.parametrize("compact", [False, True])
def test_runtime_attempts_correlate_fallbacks_without_generation_recording(tmp_path, monkeypatch, compact):
    agent = object.__new__(aa.AutonomousAgent)
    monkeypatch.setattr(aa.generation_record, "begin", lambda *a, **kw: None)
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *a: ["ollama", "ollama_fast"])
    prefix = "_query_ollama_compact" if compact else "_query_ollama"
    monkeypatch.setattr(agent, prefix, Mock(side_effect=RuntimeError("private provider detail")))
    monkeypatch.setattr(agent, prefix + "_fast_fallback", Mock(return_value="Synthetic fallback response"))
    query = agent._query_llm_compact_raw if compact else agent._query_llm_raw
    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        assert query("Private prompt", "Private system", 16, 0.9) == "Synthetic fallback response"
    saved = record.summary()
    assert saved["attempt_counts"] == {"ok": 1, "empty": 0, "error": 1}
    assert len(saved["generation_ids"]) == 1
    assert all(a["generation_id"] == saved["generation_ids"][0] for a in saved["attempts"])
    assert [s["phase"] for s in saved["spans"]] == ["generation.dispatch", "provider.attempt", "provider.attempt"]
    assert "private" not in checkpoint(tmp_path).read_text().lower()


def test_existing_generation_id_is_reused_by_runtime(tmp_path, monkeypatch):
    agent = object.__new__(aa.AutonomousAgent)
    monkeypatch.setattr(aa.generation_record, "begin", lambda *a, **kw: SimpleNamespace(generation_id="gen_existing"))
    monkeypatch.setattr(aa.generation_record, "record_attempt", lambda *a, **kw: None)
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *a: ["ollama"])
    monkeypatch.setattr(agent, "_query_ollama", Mock(return_value="Synthetic output"))
    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        agent._query_llm_raw("fixture", "fixture", 16)
    assert record.summary()["generation_ids"] == ["gen_existing"]


@pytest.mark.parametrize("database_fails", [False, True])
def test_journal_database_and_archive_timing_preserve_best_effort_save_behavior(tmp_path, monkeypatch, database_fails):
    agent = object.__new__(aa.AutonomousAgent)
    agent.session_id = "session_fixture"
    connection = Mock()
    if database_fails:
        connection.cursor.return_value.execute.side_effect = RuntimeError("private database detail")
    monkeypatch.setattr(aa.sqlite3, "connect", Mock(return_value=connection))
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)
    archive = Mock()
    monkeypatch.setattr(aa, "compact_managed_directory", archive)
    monkeypatch.setattr(aa.generation_record, "link_artifact", Mock())
    journal_file = str(tmp_path / "journal" / "fixture.txt")
    with timing.job_scope(tmp_path, job_id="job_fixture") as record:
        assert agent._write_journal_entry(
            "daydream", "private journal body", {}, journal_file, private_canvas=True,
        ) is None
    saved = record.summary()
    assert [s["phase"] for s in saved["spans"]] == ["journal.hooks", "journal.database", "journal.archive"]
    assert saved["spans"][1]["status"] == ("error" if database_fails else "ok")
    assert connection.cursor.return_value.execute.call_args.args[1][3] == "private journal body"
    assert connection.commit.call_count == (0 if database_fails else 1)
    archive.assert_called_once_with(tmp_path / "journal", ".txt")
    assert "private" not in checkpoint(tmp_path).read_text().lower()
