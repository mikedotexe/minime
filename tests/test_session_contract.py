"""Fixture-only tests for authored bookmarks and quiet session parking."""

import json
from unittest.mock import patch

import pytest

import autonomous_agent as aa
import continuity_control_plane as ccp
from minime_autonomy.session_contract import ContinuityReply


@pytest.fixture
def store(tmp_path):
    result = aa.ActionContinuityStore(tmp_path / "workspace", session_id=7)
    result.create_thread("Returnable inquiry")
    return result


def latest(store):
    thread = store.current_thread()
    return store._resolve_continuity_session(thread, "latest")


@pytest.mark.parametrize("action", ["CONTINUITY_SESSION_CAPTURE", "CONTINUE_SESSION_CAPTURE"])
def test_missing_session_is_typed_and_does_not_accept_a_draft(store, action):
    thread = store.current_thread()
    store._append_continuity_session_draft(thread, None, "fixture", "study this", "not accepted")
    path = store._continuity_sessions_path(thread["thread_id"])
    before = path.read_bytes()
    reply = store.handle_thread_action(action, {})
    assert isinstance(reply, ContinuityReply)
    assert reply.receipt["status"] == "needs_input"
    assert reply.receipt["persisted"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("payload", ["", "summary: ...", "next: INTROSPECT regulator 400", "source_refs: regulator.rs"])
def test_capture_needs_an_authored_note(store, payload):
    store.continuity_session_start("current :: title: A question")
    before = latest(store)
    reply = store.continuity_session_capture(f"latest :: {payload}")
    assert reply.receipt["status"] == "needs_input"
    assert latest(store) == before


def test_bookmark_survives_summary_parking_interruptions_and_reopen(store):
    store.continuity_session_start("current :: title: Gain question; focus: what changes with a constant shift?")
    captured = store.continuity_session_capture(
        "latest :: summary: Need the next source section; question: Is the operation shift invariant?; "
        "source_refs: regulator.rs@sha256:fixture; artifact_refs: replay.json; next: INTROSPECT regulator 400"
    )
    assert captured.receipt["persisted"] is True
    source = latest(store)
    session_id = source["session_id"]
    store.continuity_session_summarize(f"{session_id} :: summary: Compare the two formulas next")
    store.continuity_session_finalize(f"{session_id} :: outcome: park; return_cue: when I choose this question again")
    parked = latest(store)
    for key in ("focus", "open_questions", "source_refs", "artifact_refs", "suggested_next"):
        assert parked[key] == source[key]
    assert parked["automatic_return"] is False
    assert parked["return_cue"] == "when I choose this question again"
    thread = store.current_thread()
    summary = store._continuity_session_summary_v1(thread)
    assert summary["active_session"] is None
    assert store._continuity_session_line(thread, None) == ""
    control = ccp.build_continuity_control_plane_v1({"continuity_session_v1": summary})
    assert not any(row["source"] == "continuity_session_v1" for row in control["route_stack"])
    memory = store._being_memory_summary_v1(thread)
    assert memory["latest_card"] is not None
    assert memory["latest_prompt_card"] is None
    assert "Need the next source section" not in store._being_memory_line({"being_memory_v1": memory}, compact=True)
    assert "Need the next source section" in store.memory_recall("latest")
    for index in range(10):
        store.handle_thread_action(f"THREAD_NOTE unrelated activity {index}", {})
    assert latest(store) == parked
    reopened = store.continuity_session_resume(session_id)
    assert "INTROSPECT regulator 400" in reopened
    assert "regulator.rs@sha256:fixture" in reopened
    assert latest(store)["status"] == "active"
    assert latest(store)["open_questions"] == source["open_questions"]
    assert latest(store)["source_refs"] == source["source_refs"]
    assert store._being_memory_summary_v1(store.current_thread())["latest_prompt_card"] is not None


def test_parking_latest_session_keeps_a_different_active_session_visible(store):
    store.continuity_session_start("current :: title: First inquiry")
    first_id = latest(store)["session_id"]
    store.continuity_session_start("current :: title: Second inquiry")
    store.continuity_session_finalize("latest :: outcome: park")
    thread = store.current_thread()
    assert store._continuity_session_summary_v1(thread)["active_session"]["session_id"] == first_id
    assert "First inquiry" in store._continuity_session_line(thread, None)
    assert "Second inquiry" not in store._continuity_session_line(thread, None)


@pytest.mark.parametrize("outcome", ["park", "hold", "complete"])
def test_capture_cannot_silently_reopen_a_quiet_session(store, outcome):
    store.continuity_session_start("current :: title: Deliberately aside")
    store.continuity_session_finalize(f"latest :: outcome: {outcome}")
    before = latest(store)
    assert store.continuity_session_capture("latest :: summary: accidental capture").receipt["status"] == "needs_input"
    assert store.continuity_session_summarize("latest :: summary: accidental summary").receipt["status"] == "needs_input"
    assert latest(store) == before


def test_invalid_outcome_does_not_silently_park(store):
    store.continuity_session_start("current :: title: Still active")
    before = latest(store)
    assert store.continuity_session_finalize("latest :: outcome: parkk").receipt["status"] == "needs_input"
    assert latest(store) == before


def test_explicit_bookmark_remains_reachable_beyond_recent_window(store):
    store.continuity_session_start("current :: title: Older inquiry")
    store.continuity_session_capture("latest :: summary: My stopping point; next: INTROSPECT regulator 800")
    store.continuity_session_finalize("latest :: outcome: park")
    bookmark = latest(store)
    thread = store.current_thread()
    for index in range(260):
        store._append_jsonl(store._continuity_sessions_path(thread["thread_id"]), {
            "record_schema": "continuity_session_v1", "record_type": "session_start",
            "session_id": f"fixture_{index}", "status": "complete",
        })
    memory = store._being_memory_summary_v1(thread)
    assert memory["latest_card"] is not None
    assert memory["latest_prompt_card"] is None
    reply = store.continuity_session_resume(bookmark["session_id"])
    assert "My stopping point" in reply
    assert "INTROSPECT regulator 800" in reply


def test_historical_record_reference_uses_latest_session_state(store):
    store.continuity_session_start("current :: title: Versioned bookmark")
    old_record = latest(store)["record_id"]
    store.continuity_session_capture("latest :: summary: Later stopping point; next: INTROSPECT regulator 900")
    store.continuity_session_finalize("latest :: outcome: park")
    parked = latest(store)
    reply = store.continuity_session_capture(f"{old_record} :: summary: stale reference")
    assert reply.receipt["status"] == "needs_input"
    assert latest(store) == parked
    resumed = store.continuity_session_resume(old_record)
    assert "Later stopping point" in resumed
    assert "INTROSPECT regulator 900" in resumed


def test_runtime_records_missing_input_instead_of_handled(tmp_path):
    workspace = tmp_path / "workspace"
    db = tmp_path / "agent.db"
    with patch.object(aa, "WORKSPACE_DIR", workspace), patch.object(aa, "DB_PATH", db):
        agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
        agent._pending_action_continuity_context = {
            "raw_next": "CONTINUITY_SESSION_CAPTURE",
            "canonical_action": "CONTINUITY_SESSION_CAPTURE",
            "source": "next",
        }
        with (
            patch.object(agent, "_stable_core_action_allowed", return_value=(True, "fixture")),
            patch.object(agent, "_stable_core_conservative_thread_action_allowed", return_value=(True, "fixture")),
            patch.object(agent, "_log_decision"),
            patch.object(agent, "_record_stable_core_agent_success") as success,
            patch.object(agent, "_write_journal_entry"),
        ):
            agent._execute_action("thread_action", {"eig1": 4.7, "fill_ratio": .68})
        event = agent._last_action_continuity_event
        assert event["raw_next"] == "CONTINUITY_SESSION_CAPTURE"
        assert event["status"] == "needs_input"
        assert event["continuity_action_result_v1"]["persisted"] is False
        assert "needs an existing session" in event["outcome_summary"]
        success.assert_not_called()
        manifests = list((workspace / "actions").glob("*_thread_action.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text())
        assert manifest["action_continuity"]["status"] == "needs_input"
