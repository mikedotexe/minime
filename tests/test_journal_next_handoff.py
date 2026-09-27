"""The explicit journal choice owns dispatch; reflective prose is not a command."""
from unittest.mock import Mock
from pathlib import Path

import pytest
import autonomous_agent as aa
from tests.test_source_study_follow_through import STATE, study_agent
from tests.test_study_exit import execute_choice


@pytest.mark.parametrize("choice", ["SELF_STUDY", "REST"])
def test_private_journal_choice_reaches_dispatch_without_reinterpreting_its_prose(
    study_agent, monkeypatch, choice,
):
    agent, _, client, offers = study_agent
    (client.minime_root / "minime_autonomy/runtime.py").write_text("def entry(): pass\n")
    execute_choice(agent, "SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1")
    provider = agent._query_llm
    body = "I would like to remain with one simple image and leave explanations aside."
    response = body + "\nNEXT: " + choice
    hints = Mock(side_effect=AssertionError("private journal received routine action hints"))
    monkeypatch.setattr(agent, "_emit_next_hints", hints)
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=response))
    result, selected = agent._query_llm_with_next("Private journal fixture", context_mode="private_journal")
    assert result == response and selected == choice
    assert agent._pending_next_action == choice
    hints.assert_not_called()
    route = agent._decide_action(dict(STATE))
    assert agent._pending_next_action is None
    if choice == "REST":
        assert route is None
        return
    assert route == "self_study"
    assert agent._pending_action_continuity_context["raw_next"] == "SELF_STUDY"
    monkeypatch.setattr(agent, "_query_llm", provider)
    agent._execute_action(route, dict(STATE), _from_llm_job=True)
    assert offers[-1].output["input_kind"] == "end_of_file"
    assert "REST skips one action" in offers[-1]
    assert body not in offers[-1]


@pytest.mark.parametrize("pending", ["SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1", "REST", "WRITE CONTINUE", None])
def test_scheduled_regulation_reflection_cannot_replace_pending_choice(study_agent, monkeypatch, pending):
    agent, _, _, _ = study_agent
    agent._hard_recovery_reset = False
    agent._sovereignty_counter = 4
    monkeypatch.setattr(agent, "_stable_core_reflective_only", lambda: False)
    monkeypatch.setattr(agent, "_attractor_fatigue_memory_decay_rate", lambda state: None)
    monkeypatch.setattr(agent, "_emit_next_hints", lambda: "")
    provider = Mock(return_value="I will maintain my current path.\nNEXT: CONTINUE")
    monkeypatch.setattr(agent, "_query_llm", provider)
    regulate = Mock()
    monkeypatch.setattr(agent, "_send_regulation", regulate)
    if pending:
        agent._record_llm_next_action_choice(pending, "", reason="synthetic queued choice")
    checkpoint = Path(agent._sovereignty_state_path())
    before = checkpoint.read_bytes() if pending else None
    agent._self_regulate(dict(STATE))
    regulate.assert_called_once()
    if pending:
        provider.assert_not_called()
        assert agent._pending_next_action == pending
        assert checkpoint.read_bytes() == before
    else:
        provider.assert_called_once()
        assert agent._pending_next_action == "CONTINUE"
