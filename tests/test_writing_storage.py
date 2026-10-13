"""Storage commands complete without scheduling a provider, using the real shared helper."""
import json
from unittest.mock import Mock

from tests.test_private_writing_continuation import STATE, deliver, writing_agent


def test_save_only_commands_skip_the_live_job_queue(writing_agent, monkeypatch):
    agent, client = writing_agent
    deliver(client.prepare("WRITE START synthetic work"), "Exact synthetic prose.")
    queue = Mock(side_effect=AssertionError("save-only operation must not queue a generation"))
    provider = Mock(side_effect=AssertionError("save-only operation must not call provider"))
    monkeypatch.setattr(agent, "_queue_llm_action_job", queue)
    monkeypatch.setattr(agent, "_query_llm", provider)
    agent.running = True
    for action in ["WRITE QUESTION What follows?", "WRITE EVIDENCE fixture", "WRITE STOPPING_POINT here",
                   "WRITE PROFILE SHORT", "WRITE FINISH", "WRITE PARK"]:
        agent._pending_next_action = action
        agent._persist_pending_next_action(action, reason="synthetic choice")
        assert agent._decide_action(dict(STATE)) == "self_study"
        agent._execute_action("self_study", dict(STATE))
        assert not agent._pending_next_action
    queue.assert_not_called()
    provider.assert_not_called()
    checkpoint = client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v2.json"
    state = json.loads(checkpoint.read_text())
    assert state["drafts"]["d1"]["parts"] == ["Exact synthetic prose."]
    assert state["drafts"]["d1"]["finished"] is True
    assert state["active"] is None
    assert not list((client.workspace / "journal").glob("private_writing*"))


def test_finished_recovery_does_not_recommend_impossible_continue(writing_agent, monkeypatch):
    agent, client = writing_agent
    deliver(client.prepare("WRITE START synthetic work"), "Exact synthetic prose.")
    client.prepare("WRITE FINISH")
    monkeypatch.setattr(agent, "_query_llm", Mock(side_effect=AssertionError("finished draft")))
    agent._pending_next_action = "WRITE CONTINUE"
    agent._persist_pending_next_action("WRITE CONTINUE", reason="synthetic choice")
    assert agent._decide_action(dict(STATE)) == "self_study"
    agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    notices = list((client.workspace / "private_writing/journal").glob("notice_*.txt"))
    text = notices[-1].read_text()
    assert "draft_finished" in text and "WRITE RESUME d1" in text
    assert "WRITE CONTINUE retries" not in text
