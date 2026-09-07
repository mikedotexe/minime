"""Manifest timing keeps lifecycle reads and the existing payload intact."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import autonomous_agent as aa
from minime_autonomy import job_timing


def test_manifest_keeps_thread_snapshot_and_records_cost_boundaries(tmp_path, monkeypatch):
    agent = object.__new__(aa.AutonomousAgent)
    agent._action_dir = tmp_path / "actions"
    agent._action_dir.mkdir()
    agent.session_id = 7
    agent.recess_mode = True
    agent._action_summary = Mock(return_value={"title": "Synthetic notice"})
    agent._sensory_gate_status = Mock(return_value={"eyes_open": True})
    thread = {"thread_id": "thread_fixture", "active_experiment_id": "experiment_fixture",
              "experiment_summary": "Preserved experiment context."}
    store = SimpleNamespace(_read_thread=Mock(return_value=thread))
    agent._continuity_store = Mock(return_value=store)
    archive = Mock()
    monkeypatch.setattr(aa, "compact_managed_directory", archive)
    event = {"thread_id": "thread_fixture", "action_id": "action_fixture",
             "artifacts": [{"kind": "journal", "path_or_uri": "fixture.txt"}],
             "outcome_summary": "Preserved action outcome."}
    with job_timing.job_scope(tmp_path, job_id="job_fixture") as timing:
        result = agent._write_action_manifest("recess_notice", {"eig1": 4.7, "fill_ratio": 0.68}, event)
    payload = json.loads(result.read_text())
    assert payload["session_id"] == 7
    assert payload["summary"] == {"title": "Synthetic notice"}
    assert payload["experiment_continuity"] == thread
    assert payload["action_continuity"]["artifacts"] == event["artifacts"]
    assert payload["action_continuity"]["outcome_summary"] == event["outcome_summary"]
    agent._continuity_store.assert_called_once_with()
    store._read_thread.assert_called_once_with("thread_fixture")
    archive.assert_called_once_with(agent._action_dir, ".json")
    phases = {span["phase"] for span in timing.summary()["spans"]}
    assert {"action.manifest", "manifest.summary", "manifest.continuity_store",
            "manifest.thread_read", "manifest.write", "manifest.archive"} <= phases
