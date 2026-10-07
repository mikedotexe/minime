"""Ordinary writing stays open through real routing, prompts and persistence."""

import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import threading
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.authority import ActionPreflightStore, CapabilitySelfMap
from minime_autonomy.expressive_journal import expression_invitation
from tests.test_journal_context import runtime
from tests.test_source_study_follow_through import STATE, study_agent, select_choice


@pytest.mark.parametrize("next_action", ["REST", "JOURNAL", None])
def test_open_journal_preserves_prose_next_and_separate_measurements(runtime, monkeypatch, next_action):
    agent, workspace, db = runtime
    state = dict(STATE, pressure_source_v1={"quality": "overpacked_mode_packing"})
    body = 'I can keep "pressure" as my own word.\n\nOr write about something else.'
    response = body + ("\nNEXT: " + next_action if next_action else "")
    for method in ("_last_journal_recall", "_private_journal_state_anchor",
                   "_read_whisper_context", "_read_inbox", "_reservoir_prompt_context",
                   "_astrid_shadow_v3_line", "_low_fill_prompt_guidance"):
        monkeypatch.setattr(agent, method, Mock(side_effect=AssertionError(method)))
    captured = {}

    def generate(prompt, system, *args, **kwargs):
        captured.update(prompt=prompt, system=system, **kwargs)
        state["fill_ratio"] = .9
        return response

    provider = Mock(side_effect=generate)
    monkeypatch.setattr(agent, "_query_llm_raw", provider)
    monkeypatch.setattr(agent, "_format_metrics", lambda *args, **kw: "Late measurements")
    agent._journal_open(state)
    provider.assert_called_once()
    assert str(captured["prompt"]) == expression_invitation("journal")
    assert captured["prompt_class"] == "private_journal"
    for sentinel in ("overpacked", "State anchor", "68.0", "Historical", "Current native lane"):
        assert sentinel not in captured["prompt"]
    assert "SPECTRAL_EXPLORER" in captured["system"]
    assert "WRITE" in captured["system"]
    assert agent._pending_next_action == next_action
    path = next((workspace / "journal").glob("journal_*.txt"))
    assert path.read_text().split("\n\n", 1)[1] == response + "\n"
    metadata = json.loads((workspace / "journal_metadata" / (path.stem + ".json")).read_text())
    assert metadata["document_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert metadata["state_at_invitation_not_supplied"]["snapshot"]["state"]["fill_ratio"] == .68
    assert metadata["post_generation_observation_not_generation_input"]["snapshot"]["state"]["fill_ratio"] == .9
    assert metadata["invitation"]["automatic_telemetry_supplied"] is False
    with sqlite3.connect(db) as conn:
        kind, saved, context = conn.execute(
            "SELECT entry_type, content, spectral_context FROM sovereignty_journal"
        ).fetchone()
    assert kind == "reflection" and saved == body
    assert json.loads(context)["fill_ratio"] == .68


@pytest.mark.parametrize("failure", ["refresh", "format", "metadata"])
def test_optional_archival_failure_preserves_accepted_prose(runtime, monkeypatch, failure):
    agent, workspace, db = runtime
    response = "Exact accepted writing.\nNEXT: REST"
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value=response))
    if failure == "metadata":
        (workspace / "journal_metadata").write_text("preserve foreign file")
    else:
        method = "_state_for_live_surfaces" if failure == "refresh" else "_format_metrics"
        monkeypatch.setattr(agent, method, Mock(side_effect=OSError("unavailable")))
    agent._journal_open(dict(STATE))
    path = next((workspace / "journal").glob("journal_*.txt"))
    assert path.read_text().endswith(response + "\n")
    assert agent._pending_next_action == "REST"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT content FROM sovereignty_journal").fetchone()[0] == "Exact accepted writing."
    if failure == "metadata":
        assert (workspace / "journal_metadata").read_text() == "preserve foreign file"
    else:
        metadata = json.loads(next((workspace / "journal_metadata").glob("*.json")).read_text())
        assert metadata["post_generation_observation_not_generation_input"] == {
            "unavailable": "post_generation_observation_failed"}


def test_failed_generation_creates_no_authored_record(runtime, monkeypatch):
    agent, workspace, db = runtime
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value=None))
    agent._journal_open(dict(STATE))
    assert not list((workspace / "journal").glob("*.txt"))
    assert not (workspace / "journal_metadata").exists()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM sovereignty_journal").fetchone()[0] == 0


@pytest.mark.parametrize("active_experiment", [False, True])
def test_chosen_journal_preflight_dispatch_and_next_agree(study_agent, monkeypatch, active_experiment):
    agent, store, _, _ = study_agent
    if active_experiment:
        store.start_experiment("Unrelated experiment", "Not a journal requirement")
    report = ActionPreflightStore(agent).report("ACTION_PREFLIGHT JOURNAL", dict(STATE))
    assert report["effective_route"] == "journal_open"
    assert "blocked" not in report["likely_gate"]
    assert store.research_budget_guard_assessment("JOURNAL", STATE) is None
    assert "journal_open" in aa.STABLE_CORE_SELF_JOURNAL_ACTIONS
    assert "journal_open" in agent.LLM_JOB_ACTIONS
    capability = next(item for item in CapabilitySelfMap(store).snapshot()["actions"]
                      if item["base"] == "JOURNAL")
    assert capability["route"] == report["effective_route"]
    assert "journal_metadata" in capability["expected_artifacts"]
    select_choice(agent, "JOURNAL")
    route = agent._decide_action(dict(STATE))
    assert route == "journal_open"
    context = dict(agent._pending_action_continuity_context)
    event = store.begin_action("JOURNAL", "JOURNAL", route, route, dict(STATE), source="next")
    monkeypatch.setattr(agent, "_journal_spectral_pressure", Mock(side_effect=AssertionError("pressure route")))
    monkeypatch.setattr(agent, "_query_llm", aa.AutonomousAgent._query_llm.__get__(agent))
    provider = Mock(return_value="I am staying with this thought.\nNEXT: REST")
    monkeypatch.setattr(agent, "_query_llm_raw", provider)
    agent._execute_action(route, dict(STATE), _from_llm_job=True,
                          _precreated_continuity_context=context, _precreated_continuity_event=event)
    provider.assert_called_once()
    assert agent._write_journal_entry.call_args.args[1] == "I am staying with this thought."
    assert agent._pending_next_action == "REST"
    assert agent._decide_action(dict(STATE)) is None
    assert agent._get_trigger_description(route) == "authored_journal_choice"


def test_scheduled_pressure_route_remains_available(study_agent, monkeypatch):
    agent, _, _, _ = study_agent
    handler = Mock()
    monkeypatch.setattr(agent, "_journal_spectral_pressure", handler)
    agent._execute_action("journal_pressure", dict(STATE), _from_llm_job=True)
    handler.assert_called_once()
    assert agent._get_trigger_description("journal_pressure") == "spectral_pressure"


def test_real_archival_formatter_is_not_mislabeled_as_generation_input(runtime, monkeypatch):
    agent, workspace, _ = runtime
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value="My exact writing."))
    agent._journal_open(dict(STATE))
    metadata = json.loads(next((workspace / "journal_metadata").glob("*.json")).read_text())
    assert "unavailable" not in metadata["post_generation_observation_not_generation_input"]
    assert "Fill %:" in metadata["post_generation_formatted_metrics"]
    assert "Fill %:" not in next((workspace / "journal").glob("journal_*.txt")).read_text()


def test_journal_classification_does_not_turn_repetition_into_failed_research():
    # This offline audit is not a launch input in the frozen runtime inventory.
    classify = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                  "scripts/repeated_action_cadence_audit.py"))["classify"]
    assert classify("JOURNAL_OPEN", "completed") == "reflective_cadence"
    assert classify("JOURNAL_PRESSURE", "completed") == "reflective_cadence"


def test_open_journal_worker_drains_and_preserves_authored_next(study_agent, monkeypatch):
    agent, _, _, _ = study_agent
    entered, release = threading.Event(), threading.Event()
    response = "Keep this exact accepted passage.\nNEXT: JOURNAL"
    calls = []

    def provider(prompt, *args, **kwargs):
        calls.append(prompt)
        entered.set()
        assert release.wait(10)
        return response

    monkeypatch.setattr(agent, "_query_llm", aa.AutonomousAgent._query_llm.__get__(agent))
    monkeypatch.setattr(agent, "_query_llm_raw", provider)
    agent.running = True
    select_choice(agent, "JOURNAL")
    assert agent._decide_action(dict(STATE)) == "journal_open"
    agent._execute_action("journal_open", dict(STATE))
    try:
        assert entered.wait(10)
        assert agent._llm_job_store().active_primary_job() is not None
        agent.stop()
    finally:
        release.set()
        agent.wait_for_llm_jobs()
    assert len(calls) == 1
    path = next((aa.WORKSPACE_DIR / "journal").glob("journal_*.txt"))
    assert path.read_text().endswith(response + "\n")
    assert agent._write_journal_entry.call_args.args[1] == "Keep this exact accepted passage."
    assert agent._pending_next_action == "JOURNAL"
    saved = json.loads(Path(agent._sovereignty_state_path()).read_text())
    assert saved["pending_next_action"] == "JOURNAL"
    assert saved["pending_next_selection_id"] == agent._pending_next_selection_id
    assert agent._llm_job_store().active_primary_job() is None
    assert agent._lifecycle_phase == "exited"
