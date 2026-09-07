"""Deadline observations must not reconcile an action whose worker still runs."""

import json
from pathlib import Path

import autonomous_agent as aa
import pytest


def _continuity_fixture(tmp_path: Path, job: dict):
    store = aa.ActionContinuityStore.__new__(aa.ActionContinuityStore)
    store.workspace_dir = tmp_path
    path = tmp_path / "llm_jobs" / "jobs" / "job_minime_timeout" / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(job))
    store._recent_events = lambda _thread, _limit: [{
        "action_id": "act_minime_timeout",
        "status": "llm_running",
        "started_at": "2020-01-01T00:00:00Z",
        "canonical_action": "SELF_STUDY",
    }]
    return store, path


def test_deadline_does_not_shadow_action_until_worker_returns(tmp_path):
    job = {
        "job_id": "job_minime_timeout",
        "action_id": "act_minime_timeout",
        "status": "timeout",
        "worker_status": "running",
    }
    store, path = _continuity_fixture(tmp_path, job)
    pending = store._stale_running_action_diagnostics("th_minime_test")
    assert pending[0]["reconciliation_state"] == "unreconciled"
    assert pending[0]["terminal_job_id"] is None

    job["worker_status"] = "completed"
    path.write_text(json.dumps(job))
    finished = store._stale_running_action_diagnostics("th_minime_test")
    assert finished[0]["reconciliation_state"] == "shadowed_by_terminal_job"
    assert finished[0]["terminal_job_id"] == "job_minime_timeout"
    assert finished[0]["terminal_job_status"] == "timeout"
    assert finished[0]["terminal_worker_status"] == "completed"


def test_legacy_terminal_job_keeps_existing_reconciliation(tmp_path):
    store, _path = _continuity_fixture(tmp_path, {
        "job_id": "job_minime_timeout",
        "action_id": "act_minime_timeout",
        "status": "timeout",
    })
    diagnostics = store._stale_running_action_diagnostics("th_minime_test")
    assert diagnostics[0]["reconciliation_state"] == "shadowed_by_terminal_job"
    assert diagnostics[0]["terminal_worker_status"] is None


@pytest.mark.parametrize("worker_status", ["completed", "failed", "thin_output", "blocked"])
def test_cadence_uses_actual_late_outcome_without_erasing_deadline(tmp_path, worker_status):
    job = {
        "job_id": "job_minime_timeout",
        "action_id": "act_minime_timeout",
        "status": "timeout",
        "worker_status": worker_status,
        "outcome": {"status": worker_status},
        "deadline_exceeded_at": "2020-01-01T00:02:30Z",
    }
    store, _path = _continuity_fixture(tmp_path, job)
    event = store._recent_events("th_minime_test", 1)[0]
    status, evidence = store._reconciled_cadence_status(event, store._terminal_jobs_by_action_id())
    assert status == f"llm_job_{worker_status}"
    assert evidence["status"] == "timeout"
    assert evidence["deadline_exceeded_at"] == "2020-01-01T00:02:30Z"
    diagnostics = store._stale_running_action_diagnostics("th_minime_test")
    assert diagnostics[0]["terminal_outcome_status"] == worker_status

    event["status"] = "handled"
    assert store._reconciled_cadence_status(event, store._terminal_jobs_by_action_id()) == ("handled", None)


def test_cadence_retains_legacy_timeout_without_outcome(tmp_path):
    store, _path = _continuity_fixture(tmp_path, {
        "job_id": "job_minime_timeout",
        "action_id": "act_minime_timeout",
        "status": "timeout",
    })
    event = store._recent_events("th_minime_test", 1)[0]
    status, _job = store._reconciled_cadence_status(event, store._terminal_jobs_by_action_id())
    assert status == "llm_job_timeout"
