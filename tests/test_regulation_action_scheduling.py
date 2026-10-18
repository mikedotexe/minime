"""Synthetic requests through the production review, queue and decision paths."""
import hashlib
import json
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy import action_scheduling as scheduling, maintenance_next
from tests.test_journal_context import runtime
from tests.test_maintenance_next import agent as handoff_agent
from tests.test_source_study_follow_through import study_agent


STATE = {"fill_ratio": .71, "eig1": 18.67, "deig": .024, "deig_norm": .1,
         "geom_rel": .98, "cov_lambda1": 8.6, "spread": 2.63, "leak": .9}


@pytest.fixture
def ready(runtime, monkeypatch):
    agent, workspace, _ = runtime
    agent._hard_recovery_reset = False
    agent._sovereignty_counter = 4
    for name in ("_stable_core_reflective_only", "_attention_protected"):
        monkeypatch.setattr(agent, name, lambda: False)
    monkeypatch.setattr(agent, "_attractor_fatigue_memory_decay_rate", lambda state: None)
    monkeypatch.setattr(agent, "_send_regulation", Mock())
    import websocket
    monkeypatch.setattr(websocket, "create_connection", Mock(return_value=Mock()))
    monkeypatch.setattr(agent, "_self_regulation_reconcile_active_lease", Mock())
    monkeypatch.setattr(agent, "_publish_self_need", Mock())
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda state: {"active": False})
    return agent, workspace


def review(agent, monkeypatch, response):
    provider = Mock(return_value=response)
    monkeypatch.setattr(agent, "_query_llm_raw", provider)
    agent._self_regulate(dict(STATE))
    return provider


def queue_state(workspace):
    return json.loads((workspace / "sovereignty_state.json").read_text())


def test_fresh_request_survives_idle_gap_and_uses_normal_reflection_admission(ready, monkeypatch):
    agent, workspace = ready
    assert agent._decide_action(dict(STATE)) is None
    assert scheduling.snapshot(agent)["last_observation"]["reason"] == "no_next_no_threshold_action"
    response = '{"action":"introspect","reason":"synthetic request"}'
    provider = review(agent, monkeypatch, response)
    provider.assert_called_once()
    state = queue_state(workspace)
    assert state["pending_next_action"] == agent._pending_next_action == "INTROSPECT"
    origin = state["choice_envelope_v1"]["regulation_request_v1"]
    assert origin == {
        "requested_action": "introspect", "canonical_action": "INTROSPECT",
        "response_sha256": hashlib.sha256(response.encode()).hexdigest(), "authored_next_line": False,
    }
    assert agent._regulation_action_receipt["status"] == "queued_not_executed"
    assert not list((workspace / "journal").glob("*.txt"))
    assert agent._decide_action(dict(STATE)) == "self_study"
    assert agent._pending_source_study_action == "INTROSPECT"
    assert agent._pending_action_continuity_context["choice_envelope_v1"]["regulation_request_v1"] == origin
    assert agent._pending_next_action is None
    assert queue_state(workspace)["pending_next_action_status"] == "cleared"
    assert agent._decide_action(dict(STATE)) is None  # No replay from the old regulation field.


@pytest.mark.parametrize("requested,command", list(scheduling.REGULATION_ACTIONS.items()))
def test_only_existing_canonical_commands_are_queued(ready, monkeypatch, requested, command):
    agent, workspace = ready
    review(agent, monkeypatch, json.dumps({"action": requested}))
    assert queue_state(workspace)["pending_next_action"] == command
    assert agent._pending_next_action == command


@pytest.mark.parametrize("requested", [None, "", [], {}, 7, "INTROSPECT", "introspect AND JOURNAL", "unknown"])
def test_missing_or_unsupported_request_does_not_invent_work(ready, monkeypatch, requested):
    agent, workspace = ready
    review(agent, monkeypatch, json.dumps({"action": requested}))
    assert agent._pending_next_action is None
    if (workspace / "sovereignty_state.json").exists():
        state = queue_state(workspace)
        assert not state.get("pending_next_action")
        assert not state.get("choice_envelope_v1")
    assert agent._decide_action(dict(STATE)) is None


@pytest.mark.parametrize("choice", ["REST", "WRITE CONTINUE", "JOURNAL", "PARK_ACTIVITY WRITE d1"])
def test_existing_next_defers_regulation_generation(ready, monkeypatch, choice):
    agent, workspace = ready
    agent._persist_pending_next_action(choice, reason="synthetic choice", only_if_unqueued=True)
    before = (workspace / "sovereignty_state.json").read_bytes()
    provider = review(agent, monkeypatch, '{"action":"introspect"}')
    provider.assert_not_called()
    assert agent._pending_next_action == choice
    assert (workspace / "sovereignty_state.json").read_bytes() == before


@pytest.mark.parametrize("choice", ["REST", "JOURNAL", "WRITE CONTINUE", "PARK_ACTIVITY WRITE d1"])
def test_final_next_from_same_response_wins_over_json_request(ready, monkeypatch, choice):
    agent, workspace = ready
    review(agent, monkeypatch, '{"action":"introspect"}\nNEXT: ' + choice)
    assert agent._pending_next_action == queue_state(workspace)["pending_next_action"] == choice
    assert agent._regulation_action_receipt["status"] == "deferred_explicit_choice"
    if choice == "REST":
        assert agent._decide_action(dict(STATE)) is None
        assert scheduling.snapshot(agent)["last_observation"]["reason"] == "explicit_rest"
        assert agent._pending_next_action is None


@pytest.mark.parametrize("condition,reason", [
    ("protected", "deferred_protected_work"),
    ("shutdown", "deferred_shutdown_or_recovery"),
    ("recovery", "deferred_shutdown_or_recovery"),
    ("unadmitted", "deferred_unadmitted_choice"),
])
def test_request_is_not_replayed_after_incompatible_state(ready, monkeypatch, condition, reason):
    agent, workspace = ready
    if condition == "protected":
        monkeypatch.setattr(agent, "_attention_protected", lambda: True)
    elif condition == "shutdown":
        agent._shutdown_requested = True
    elif condition == "recovery":
        agent._next_handoff_failed = True
    else:
        agent._unadmitted_next_checkpoint = {"token": "retained"}
    scheduling.queue_regulation_request(agent, "introspect", response="synthetic")
    assert agent._regulation_action_receipt["status"] == reason
    assert agent._pending_next_action is None
    assert not (workspace / "sovereignty_state.json").exists()
    assert not hasattr(agent, "_sovereignty_requested_action")


@pytest.mark.parametrize("choice", ["REST", "INTROSPECT", "WRITE CONTINUE"])
def test_durable_concurrent_choice_wins_even_with_same_command(ready, monkeypatch, choice):
    agent, workspace = ready
    agent._persist_pending_next_action(choice, reason="concurrent choice", only_if_unqueued=True)
    previous = (workspace / "sovereignty_state.json").read_bytes()
    agent._pending_next_action = None  # The other writer is ahead of this process.
    scheduling.queue_regulation_request(agent, "introspect", response="synthetic")
    assert agent._pending_next_action == choice
    assert (workspace / "sovereignty_state.json").read_bytes() == previous
    assert agent._regulation_action_receipt["status"] == "deferred_existing_durable_choice"


def test_persistence_failure_is_visible_and_cannot_dispatch(ready, monkeypatch):
    agent, _ = ready
    agent._agent_boot_id = "a" * 32
    monkeypatch.setattr(maintenance_next, "write_state", Mock(side_effect=OSError("synthetic full disk")))
    with pytest.raises(OSError, match="synthetic full disk"):
        scheduling.queue_regulation_request(agent, "introspect", response="synthetic")
    assert agent._regulation_action_receipt["status"] == "persistence_failed"
    assert agent._next_handoff_failed
    with pytest.raises(maintenance_next.HandoffError, match="next_handoff_recovery_blocked"):
        agent._decide_action(dict(STATE))
    assert scheduling.snapshot(agent)["last_observation"]["reason"] == "decision_failed"


def test_guard_refusal_still_blocks_regulation_experiment(ready, monkeypatch):
    agent, _ = ready
    review(agent, monkeypatch, '{"action":"self_experiment"}')
    store = agent._continuity_store()
    guard = Mock(return_value={"reason": "synthetic authority refusal", "suggested_next": "REST"})
    monkeypatch.setattr(store, "live_control_guard_assessment", guard)
    assert agent._decide_action(dict(STATE)) is None
    guard.assert_called_once_with("SELF_EXPERIMENT")
    assert agent._scheduler_observation["reason"] == "live_control_admission_blocked"
    assert agent._pending_next_action is None


def test_status_is_content_free_and_reports_protected_wait(ready, monkeypatch):
    agent, _ = ready
    monkeypatch.setattr(agent, "_attention_protected", lambda: True)
    assert agent._decide_action(dict(STATE)) is None
    assert scheduling.snapshot(agent)["last_observation"]["reason"] == "protected_work_waiting_for_choice_or_completion"
    agent._pending_next_action = "WRITE START private topic never in status"
    status = agent._current_source_status("idle")["action_scheduler_v1"]
    assert status["pending_choice_present"]
    assert "private topic" not in json.dumps(status)
    scheduling.queue_regulation_request(agent, {"private": "untrusted text"})
    assert "untrusted text" not in json.dumps(scheduling.snapshot(agent))


def test_exact_request_and_origin_survive_graceful_handoff(ready):
    agent, workspace = ready
    scheduling.queue_regulation_request(agent, "introspect", response="synthetic request")
    state = queue_state(workspace)
    old = handoff_agent(workspace)
    old._pending_next_action = state["pending_next_action"]
    old._pending_next_selection_id = state["pending_next_selection_id"]
    old._pending_choice_envelope_v1 = state["choice_envelope_v1"]
    maintenance_next.seal(old)
    new = handoff_agent(workspace)
    ack = maintenance_next.restore(new)
    assert ack["pending_present"] and not ack["scheduling_authorized"]
    assert new._pending_next_action == "INTROSPECT"
    assert new._pending_choice_envelope_v1 == state["choice_envelope_v1"]
    assert queue_state(workspace) == state


def test_corrupt_queue_is_preserved_and_request_refuses(ready):
    agent, workspace = ready
    agent._agent_boot_id = "b" * 32
    path = workspace / "sovereignty_state.json"
    raw = b'{"pending_next_action":'
    path.write_bytes(raw)
    with pytest.raises(maintenance_next.HandoffError):
        scheduling.queue_regulation_request(agent, "introspect", response="synthetic")
    assert path.read_bytes() == raw
    assert agent._regulation_action_receipt["status"] == "persistence_failed"
    assert agent._next_handoff_failed


def test_regulation_request_reaches_verified_reflection_under_retained_experiment(study_agent, monkeypatch):
    agent, store, client, offers = study_agent
    monkeypatch.setattr(agent, "_attention_protected", lambda: False)
    store.start_experiment("Unrelated active experiment", "Synthetic retained question")
    scheduling.queue_regulation_request(agent, "introspect", response='{"action":"introspect"}')
    assert agent._decide_action(dict(STATE)) == "self_study"
    context = dict(agent._pending_action_continuity_context)
    assert context["source_study_action"] == "INTROSPECT"
    event = store.begin_action("INTROSPECT", "INTROSPECT", "self_study", "self_study", dict(STATE), source="next")
    with aa.job_outcome.capture(event["action_id"]) as outcome:
        agent._execute_action("self_study", dict(STATE), _from_llm_job=True,
                              _precreated_continuity_context=context,
                              _precreated_continuity_event=event)
    assert outcome.finish()[0] == "completed", outcome.finish()
    assert len(offers) == 1 and offers[0].receipt
    assert offers[0].output["input_kind"] == "reflection"
    assert offers[0].output["page"] is None
    state = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json").read_text())
    assert not state["bookmarks"] and not state["notebook"]["question"]
    assert len(list((aa.WORKSPACE_DIR / "journal").glob("introspect_*.txt"))) == 1
    assert agent._pending_next_action == "SELF_STUDY MAP minime"
    assert agent._decide_action(dict(STATE)) == "self_study"
    assert agent._pending_source_study_action == "SELF_STUDY MAP minime"


@pytest.mark.parametrize("case,expected", [
    ("idle", "no_next_no_threshold_action"),
    ("missing_telemetry", "telemetry_unavailable"),
    ("cooldown", "next_waiting_for_action_slot"),
    ("active_job", "primary_job_active"),
    ("queued_job", "primary_job_active"),
    ("rest", "explicit_rest"),
    ("dispatch", "action_dispatched_completion_separate"),
    ("error", "loop_error"),
])
def test_real_loop_exposes_specific_reason_without_private_payload(ready, monkeypatch, case, expected):
    agent, _ = ready
    for name in ("_check_source_reload_required", "_restore_sovereignty_state",
                 "_apply_pending_next_override_if_present", "_refresh_session_context",
                 "_update_hard_recovery_clamp", "_reconcile_stable_core_health_status",
                 "_self_regulate", "_auto_defer_stale_pending_astrid", "_check_visual_responses",
                 "_check_moment_markers", "_write_source_status", "_verify_sovereignty"):
        monkeypatch.setattr(agent, name, Mock())
    monkeypatch.setattr(agent, "_get_latest_spectral_state",
                        Mock(side_effect=ValueError("synthetic telemetry failure")) if case == "error"
                        else lambda: None if case == "missing_telemetry" else dict(STATE))
    jobs = Mock()
    jobs.active_primary_job.return_value = (
        {"job_id": "synthetic", "status": "running" if case == "active_job" else "queued"}
        if case in ("active_job", "queued_job") else None
    )
    monkeypatch.setattr(agent, "_llm_job_store", lambda: jobs)
    monkeypatch.setattr(agent, "_can_act", lambda: case != "cooldown")
    execute = Mock()
    monkeypatch.setattr(agent, "_execute_action", execute)
    if case in ("rest", "dispatch", "cooldown"):
        command = {"rest": "REST", "dispatch": "JOURNAL", "cooldown": "WRITE START private title sentinel"}[case]
        agent._persist_pending_next_action(command, reason="synthetic loop choice", only_if_unqueued=True)
    seen = []

    def one_cycle(_):
        seen.append(agent._current_source_status("idle")["action_scheduler_v1"])
        agent.running = False

    monkeypatch.setattr(agent, "_sleep_or_stop", one_cycle)
    agent.start()
    assert len(seen) == 1 and seen[0]["last_observation"]["reason"] == expected
    assert "private title sentinel" not in json.dumps(seen)
    if case == "dispatch":
        execute.assert_called_once()
    else:
        execute.assert_not_called()
    if case == "cooldown":
        assert agent._pending_next_action == command
