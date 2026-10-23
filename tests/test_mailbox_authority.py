"""Mailbox routing describes the same bounded action that dispatch executes."""
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.authority import ActionPreflightStore, CapabilitySelfMap
from tests.test_source_study_follow_through import STATE, study_agent, select_choice


@pytest.mark.parametrize("command,route,stage", [
    ("CHECK_MAILBOX", "mailbox_read", "language_only"),
    ("CHECK_MAILBOX LARGE", "mailbox_read", "language_only"),
    ("MAILBOX_STATUS", "mailbox_status", "read_only"),
    ("MAILBOX_STATUS 2", "mailbox_status", "read_only"),
])
def test_preflight_capability_dispatch_and_visibility_agree(study_agent, command, route, stage):
    agent, store, _, _ = study_agent
    report = ActionPreflightStore(agent).report(command, STATE)
    assert report["effective_route"] == route and report["stage"] == stage
    assert report["visibility"] == "protected_summary"
    spec = next(x for x in CapabilitySelfMap(store).snapshot()["actions"]
                if x["base"] == command.split()[0])
    assert spec["route"] == route and spec["stage"] == stage
    select_choice(agent, command)
    assert agent._decide_action(dict(STATE)) == route


@pytest.mark.parametrize("stage", aa.STABLE_CORE_STAGE_ACTIONS)
def test_mailbox_admission_preserves_existing_stage_and_health_gates(study_agent, monkeypatch, stage):
    agent, _, _, _ = study_agent
    monkeypatch.setattr(agent, "_stable_core_agency_budget", lambda: {"active": True, "stage": stage})
    health = Mock(return_value=(True, "fixture health"))
    monkeypatch.setattr(agent, "_stable_core_health_budget_allows", health)
    allowed = stage in {"read_only_research", "research_actions", "bounded_actions", "experiments", "full_sovereignty"}
    report = ActionPreflightStore(agent).report("CHECK_MAILBOX", STATE)
    assert report["stable_core_gate"]["allowed"] == allowed
    assert agent._stable_core_action_allowed("mailbox_read", STATE)[0] == allowed
    if allowed:
        health.return_value = (False, "fixture health hold")
        assert not ActionPreflightStore(agent).report("CHECK_MAILBOX", STATE)["stable_core_gate"]["allowed"]


def test_status_does_not_release_focus_or_invoke_provider(study_agent, monkeypatch):
    agent, _, _, _ = study_agent
    monkeypatch.setattr(agent, "_activity_focus", Mock(side_effect=AssertionError("status cannot release focus")))
    monkeypatch.setattr(agent, "_query_llm", Mock(side_effect=AssertionError("metadata cannot generate")))
    agent._current_action_continuity_event = {"action_id": "status-fixture"}
    agent._activity_command({"raw_next": "MAILBOX_STATUS"})
    assert "waiting_files" in agent._pending_mailbox_feedback
    bad = ActionPreflightStore(agent).report("CHECK_MAILBOX all", STATE)
    assert bad["stage"] == "blocked" and not bad["stable_core_gate"]["allowed"]


@pytest.mark.parametrize("command", ["MAILBOX_STATUS 0", "MAILBOX_STATUS -1",
                                    "MAILBOX_STATUS +1", "MAILBOX_STATUS all",
                                    "MAILBOX_STATUS 1 2", "MAILBOX_STATUS 18446744073709551616"])
def test_status_preflight_rejects_same_invalid_pages_as_dispatch(study_agent, command):
    from minime_autonomy.mailbox import status_page
    agent, _, _, _ = study_agent
    with pytest.raises(ValueError):
        status_page(command)
    report = ActionPreflightStore(agent).report(command, STATE)
    assert report["stage"] == "blocked" and not report["stable_core_gate"]["allowed"]
