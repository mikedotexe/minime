"""Voluntary unfinished work through the real adapter; all prose/providers synthetic."""
import json

from tests.test_private_writing_continuation import STATE, deliver, writing_agent


def test_branch_park_return_and_finish_without_forced_closure(writing_agent, monkeypatch):
    agent, client = writing_agent
    responses = iter([
        ("WRITE START synthetic open question", "Original synthetic question, still open.\nNEXT: WRITE BRANCH an alternative"),
        ("WRITE BRANCH an alternative", "An alternative that remains unfinished.\nNEXT: WRITE PARK"),
        ("WRITE START unrelated work", "Something unrelated.\nNEXT: REST"),
        ("WRITE RESUME d2", "Returning changes the earlier explanation.\nNEXT: WRITE CONTINUE"),
        ("WRITE CONTINUE", "One more possibility, not a verdict."),
        ("WRITE RESUME d2", "Brief stopping is also available.\nNEXT: WRITE FINISH"),
    ])
    offers = []

    def provider(prompt, **kwargs):
        action, text = next(responses)
        assert f"chosen action: {action}" in prompt
        assert "Write only a new passage" in prompt.output["system_prompt"]
        assert "A passage ending does not finish the draft" in prompt.output["system_prompt"]
        assert "WRITE PROFILE EXTENDED applies" not in prompt
        assert "WRITE OBSERVE typed JSON" not in prompt
        if action == "WRITE BRANCH an alternative" or action == "WRITE RESUME d2":
            assert "Return to parent draft: WRITE RESUME d1" in prompt
            assert "Original synthetic question, still open." in prompt
        if action == "WRITE START unrelated work":
            assert "Original synthetic question" not in prompt
            assert "An alternative" not in prompt
        if action == "WRITE RESUME d2":
            assert "An alternative that remains unfinished." in prompt
            assert "Something unrelated." not in prompt
        offers.append(prompt)
        deliver(prompt, text)
        return text

    monkeypatch.setattr(agent, "_query_llm", provider)

    def choose(action):
        agent._pending_next_action = action
        agent._persist_pending_next_action(action, reason="synthetic explicit choice")
        assert agent._decide_action(dict(STATE)) == "self_study"
        agent._execute_action("self_study", dict(STATE), _from_llm_job=True)

    choose("WRITE START synthetic open question")
    assert agent._pending_next_action == "WRITE BRANCH an alternative"
    choose(agent._pending_next_action)
    assert agent._pending_next_action == "WRITE PARK"
    choose(agent._pending_next_action)
    assert len(offers) == 2 and agent._pending_next_action is None
    path = client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v2.json"
    parked = json.loads(path.read_text())
    assert parked["active"] is None and not parked["drafts"]["d2"]["finished"]
    choose("WRITE START unrelated work")
    assert agent._pending_next_action == "REST"
    choose("WRITE RESUME d2")
    assert agent._pending_next_action == "WRITE CONTINUE"
    choose(agent._pending_next_action)
    assert agent._pending_next_action is None
    open_state = json.loads(path.read_text())
    assert not open_state["drafts"]["d2"]["finished"]
    assert open_state["pending"] is None
    choose("WRITE RESUME d2")
    assert agent._pending_next_action == "WRITE FINISH"
    choose(agent._pending_next_action)
    assert len(offers) == 6 and agent._pending_next_action is None
    state = json.loads(path.read_text())
    assert state["drafts"]["d2"]["finished"] is True
    assert state["drafts"]["d1"]["parts"] == ["Original synthetic question, still open."]
    assert state["drafts"]["d2"]["parts"] == [
        "Original synthetic question, still open.",
        "An alternative that remains unfinished.",
        "Returning changes the earlier explanation.",
        "One more possibility, not a verdict.",
        "Brief stopping is also available.",
    ]
    assert not list((client.workspace / "journal").glob("private_writing*"))
    assert all(call.kwargs.get("private_canvas") for call in agent._write_journal_entry.call_args_list)
