"""Synthetic worker outcomes; no live services or real model requests."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import job_outcome
from minime_autonomy.llm_access import LlmJobStore


class Finalizer:
    @job_outcome.finalizer
    def finish(self, event, status, outcome_summary, post_state, artifacts=None):
        return {**event, "status": status, "outcome_summary": outcome_summary, "artifacts": artifacts or []}


def worker(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)
    agent = object.__new__(aa.AutonomousAgent)
    store = LlmJobStore(tmp_path)
    job = store.submit(action_id="act_owned", thread_id="thread_owned", action_text="DAYDREAM", call_kind="recess_daydream")
    event = {"action_id": "act_owned", "thread_id": "thread_owned"}
    agent._llm_job_store = lambda: store
    return agent, store, job, event


@pytest.mark.parametrize("status", ["failed", "blocked", "handled"])
def test_worker_uses_its_owned_finalizer_not_shared_last_event(tmp_path, monkeypatch, status):
    agent, store, job, event = worker(tmp_path, monkeypatch)

    def action(*args, **kwargs):
        Finalizer().finish(event, status, "Owned action outcome", {})
        agent._last_action_continuity_event = {"action_id": "act_someone_else", "status": "handled"}

    agent._execute_action = action
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    finished = store.read_job(job["job_id"])
    assert finished["status"] == ("completed" if status == "handled" else status)
    assert finished["summary"] == "Owned action outcome"
    assert not agent._llm_job_worker_active
    timing = json.loads((store.jobs_dir / job["job_id"] / "phase_timings.json").read_text())
    assert timing["job_id"] == job["job_id"]


def test_canceled_queued_worker_does_not_dispatch(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    store.request_cancel(job["job_id"])
    agent._execute_action = Mock()
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    agent._execute_action.assert_not_called()
    assert store.read_job(job["job_id"])["status"] == "canceled"


def test_late_worker_retains_journal_and_finishes_timing_checkpoint(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    journal = tmp_path / "late-journal.txt"

    @job_outcome.journal_write
    def register(self, entry_type, content, state, file_path):
        pass

    def action(*args, **kwargs):
        running = store.read_job(job["job_id"])
        running["started_at"] = "2000-01-01T00:00:00Z"
        store._write_job(running)
        store.expire_timed_out_jobs()
        assert store.active_primary_job()["job_id"] == job["job_id"]
        journal.write_text("Late fixture writing")
        register(None, "daydream", "Late fixture writing", {}, str(journal))
        Finalizer().finish(event, "handled", "Writing saved", {})

    agent._execute_action = action
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    finished = store.read_job(job["job_id"])
    assert finished["status"] == "timeout"
    assert finished["worker_status"] == "completed"
    assert Path(finished["retained_result_path"]).read_text() == "Writing saved"
    assert any(a["path_or_uri"] == str(journal) for a in finished["artifact_refs"])
    checkpoint = json.loads((store.jobs_dir / job["job_id"] / "phase_timings.json").read_text())
    assert checkpoint["state"] == "complete"
    assert any(s["phase"] == "worker.finalization" and s["status"] == "ok" for s in checkpoint["spans"])
    assert store.active_primary_job() is None


def test_worker_retries_identical_outcome_after_projection_failure(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    agent._execute_action = lambda *args, **kwargs: Finalizer().finish(event, "handled", "Saved", {})
    original = store._append_event
    failed_once = False

    def append(job_id, payload):
        nonlocal failed_once
        if payload["event"] == "completed" and not failed_once:
            failed_once = True
            raise OSError("synthetic event-write interruption")
        return original(job_id, payload)

    monkeypatch.setattr(store, "_append_event", append)
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    assert store.read_job(job["job_id"])["status"] == "completed"
    events = [json.loads(line) for line in (store.jobs_dir / job["job_id"] / "events.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "completed" for e in events) == 1


def test_worker_does_not_complete_without_action_evidence(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    agent._execute_action = Mock()
    agent._last_action_continuity_event = {**event, "status": "handled"}
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    assert store.read_job(job["job_id"])["error"] == "action_finalization_unconfirmed"


def test_failed_continuity_cannot_erase_action_failure(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)

    def action(*args, **kwargs):
        job_outcome.fail_action("fixture_failure", "Fixture action failed")
        Finalizer().finish(event, "handled", "Misleading later finalizer", {})

    agent._execute_action = action
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    assert store.read_job(job["job_id"])["status"] == "failed"
    assert store.read_job(job["job_id"])["error"] == "fixture_failure"


def test_raw_query_failure_with_normal_action_return_is_failed(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    agent._query_ollama = Mock(return_value=None)

    def action(*args, **kwargs):
        assert agent._query_llm_raw("fixture", "fixture", 16) is None
        Finalizer().finish(event, "handled", "Executed autonomous action", {})

    agent._execute_action = action
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    assert store.read_job(job["job_id"])["error"] == "no_model_output"


def test_empty_primary_successful_fallback_is_completed(tmp_path, monkeypatch):
    agent, store, job, event = worker(tmp_path, monkeypatch)
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama", "ollama_fast"])
    agent._query_ollama = Mock(return_value=None)
    agent._query_ollama_fast_fallback = Mock(return_value="Usable fixture output")

    def action(*args, **kwargs):
        assert agent._query_llm_raw("fixture", "fixture", 16) == "Usable fixture output"
        Finalizer().finish(event, "handled", "Saved output", {})

    agent._execute_action = action
    agent._run_llm_action_job(job["job_id"], "recess_daydream", {}, {}, event)
    assert store.read_job(job["job_id"])["status"] == "completed"


def test_journal_evidence_survives_a_failed_registration_hook(tmp_path):
    journal = tmp_path / "journal.txt"
    journal.write_text("Already saved fixture output")

    @job_outcome.journal_write
    def broken_hook(self, entry_type, content, state, file_path, **kwargs):
        raise RuntimeError("registration failure")

    with job_outcome.capture("act_owned") as outcome:
        with pytest.raises(RuntimeError, match="registration failure"):
            broken_hook(None, "daydream", "fixture", {}, str(journal), private_canvas=True)
        job_outcome.fail_action("hook_failed", "Registration failed")
    status, _, _, artifacts = outcome.finish()
    assert status == "failed"
    assert any(Path(a["path_or_uri"]) == journal for a in artifacts)


def test_nested_outcome_scope_and_unrelated_finalizers_do_not_leak():
    with job_outcome.capture("outer") as outer:
        Finalizer().finish({"action_id": "someone_else"}, "handled", "Unrelated", {})
        with job_outcome.capture("inner") as inner:
            Finalizer().finish({"action_id": "inner"}, "failed", "Inner failure", {})
        assert job_outcome.current() is outer
    assert job_outcome.current() is None
    assert outer.event is None
    assert inner.finish()[0] == "failed"


@pytest.mark.parametrize("raise_error", [False, True])
def test_real_action_dispatch_finalizes_owned_outcome(tmp_path, monkeypatch, raise_error):
    agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
    state = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68, "spread": 3.0, "cov_lambda1": 8.0, "geom_rel": 1.0}
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda *_: {
        "active": False, "fill_ratio": 0.68, "target_fill_ratio": 0.68, "spread_relief": 0.0})
    event = agent._continuity_store().begin_action("DAYDREAM", "DAYDREAM", "recess_daydream", "recess_daydream", state)
    jobs = agent._llm_job_store()
    job = jobs.submit(action_id=event["action_id"], thread_id=event["thread_id"],
                      action_text="DAYDREAM", call_kind="recess_daydream")

    def body(*args):
        if raise_error:
            raise RuntimeError("synthetic action failure")
        agent._current_action_outcome_summary = "Synthetic action completed"

    monkeypatch.setattr(agent, "_recess_daydream", body)
    agent._run_llm_action_job(job["job_id"], "recess_daydream", state, {}, event)
    finished = jobs.read_job(job["job_id"])
    assert finished["status"] == ("failed" if raise_error else "completed")
    if raise_error:
        assert finished["error"] == "synthetic action failure"
    else:
        assert finished["summary"] == "Synthetic action completed"
