"""Sustained study through real dispatcher/reader/provider adapters, no live inference."""
import json
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from tests.test_source_study_follow_through import study_agent, STATE
from tests.test_study_exit import execute_choice


@pytest.mark.parametrize("question", [
    "Does the `Kernel` struct in `lib.rs` (specifically in `astrid_kernel`) implement the `if !blocked` check within its methods or a wrapper?",
    "Does a condition AND TURN_OFF imply execution?",
])
def test_observed_new_case_reaches_specific_recovery_without_inquiry_or_extra_action(study_agent, question):
    agent, _, client, offers = study_agent
    action = f"SELF_STUDY NEW {question}"
    assert aa.parse_next_action(f"NEXT: {action}")[0] == action
    assert agent._split_multi_action(action) == [action]
    execute_choice(agent, action)
    out = offers[-1].output
    assert out["input_kind"] == "recovery"
    assert out["continuation_decision"] is True
    assert f"SELF_STUDY QUESTION NEW {question}" in offers[-1]
    path = client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json"
    assert json.loads(path.read_text())["questions"]["entries"] == {}
    assert agent._write_journal_entry.call_args.args[0] == "study_decision"


def test_help_and_sustained_session_revision_survive_real_dispatch_and_return(study_agent, monkeypatch):
    agent, _, client, offers = study_agent
    source = "minime/minime_autonomy/runtime.py"
    second = client.minime_root / "minime_autonomy/helper.py"
    second.write_text("def allowed(blocked):\n    return not blocked\n" * 500)
    answer = ["NEXT: REST"]

    def provider(prompt, **kwargs):
        offers.append(prompt)
        wire = json.dumps({"message": {"content": answer[0]}, "done": True, "done_reason": "stop"})
        prompt.post(Mock(return_value=Mock(status_code=200, text=wire)), "fake", {"messages": [
            {"role": "system", "content": prompt.output["system_prompt"]},
            {"role": "user", "content": str(prompt)}]}, 1)
        prompt.accepted()
        return answer[0]

    monkeypatch.setattr(agent, "_query_llm", provider)
    execute_choice(agent, "SELF_STUDY QUESTION NEW Does the caller enforce the result?")
    path = client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json"
    before = json.loads(path.read_text())
    answer[0] = "STUDY_NOTE: Do not save command help as an account.\nNEXT: REST"
    execute_choice(agent, "SELF_STUDY HELP notebook")
    assert offers[-1].output["input_kind"] == "help"
    assert agent._write_journal_entry.call_args.args[0] == "study_decision"
    assert before["questions"] == json.loads(path.read_text())["questions"]
    prose = "We can distinguish a declared test from its consumer; the consumer may still ignore it. " * 120
    answer[0] = prose + "END_OF_SYNTHESIS\nSTUDY_NOTE: Original hypothesis.\nNEXT: REST"
    execute_choice(agent, f"SELF_STUDY SESSION OPEN {source} 1 | OPEN minime/minime_autonomy/helper.py 1")
    session = offers[-1]
    assert "800-1,500 words" in session.output["system_prompt"]
    assert "sustained synthesis" in session
    assert "up to 600 bytes" not in session.output["system_prompt"]
    assert len(session.output["session_pages"]) == 2
    assert "END_OF_SYNTHESIS" in agent._write_journal_entry.call_args.args[1]
    stored = json.loads(path.read_text())
    prior = stored["questions"]["entries"]["q1"]["notebook"]["note"]["response_sha256"]
    answer[0] = "STUDY_REVISE: " + json.dumps({"prior": prior, "text": "The branch is visible, but its caller remains unresolved.", "source": source, "line": 1}) + "\nNEXT: REST"
    execute_choice(agent, f"SELF_STUDY OPEN {source} 1")
    positions = json.loads(path.read_text())["bookmarks"]
    answer[0] = "NEXT: REST"
    assert agent._pending_next_action == "REST"
    assert agent._decide_action(dict(STATE)) is None
    execute_choice(agent, "SELF_STUDY QUESTION PARK q1")
    execute_choice(agent, "SELF_STUDY MAP")
    assert "Does the caller enforce the result?" not in offers[-1]
    execute_choice(agent, "SELF_STUDY QUESTION q1")
    execute_choice(agent, "SELF_STUDY NOTE")
    assert "Original hypothesis." in offers[-1]
    assert "its caller remains unresolved" in offers[-1]
    assert json.loads(path.read_text())["bookmarks"] == positions
