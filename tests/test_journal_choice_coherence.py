"""Choice feedback uses actual shared delivery; no live requests or state writes."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.source_study import SourceStudyPrompt, StudyClient


@pytest.mark.parametrize("container", [
    "```\n{choice}", "~~~python\n{choice}", "````\n{choice}\n```",
    "~~~\n{choice}\n```", "    {choice}", "\t{choice}", "> {choice}",
    '"{choice}"', "‘{choice}’", "`{choice}`",
])
@pytest.mark.parametrize("choice", ["NEXT: FINISH", "NEXT: SELF_STUDY CONTINUE", "SELF_STUDY MAP"])
def test_non_actions_stay_data(container, choice):
    assert aa.parse_next_action(container.format(choice=choice))[0] is None


@pytest.mark.parametrize("text, expected", [
    ("SELF_STUDY OPEN astrid/example.rs 27\nNEXT: SELF_STUDY CONTINUE", "SELF_STUDY CONTINUE"),
    ("NEXT: REST\nSELF_STUDY OPEN astrid/example.rs 27", "REST"),
    ("FIND astrid/example.rs", None),
    ("~~~py\nNEXT: FINISH\n~~~\nNEXT: WRITE CONTINUE", "WRITE CONTINUE"),
    ("```\nNEXT: TURN_OFF\n```\nNEXT: SELF_STUDY MAP", "SELF_STUDY MAP"),
    ("NEXT: REST\n~~~\nNEXT: TURN_OFF", "REST"),
])
def test_final_explicit_choice_and_existing_source_affordance(text, expected):
    assert aa.parse_next_action(text)[0] == expected


def client_for(tmp_path):
    astrid = tmp_path / "astrid"
    minime = tmp_path / "minime"
    astrid.mkdir()
    minime.mkdir()
    return StudyClient(minime, tmp_path / "workspace", astrid_root=astrid,
                       executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))


def deliver(prompt, text):
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True}))
    prompt.post(Mock(return_value=response), "fake", {"messages": messages}, 1)
    prompt.accepted()


@pytest.mark.parametrize("choice", ["FINISH", "finish"])
def test_verified_private_finish_retains_raw_choice_without_queueing_unknown(tmp_path, monkeypatch, choice):
    client = client_for(tmp_path)
    prompt = client.prepare("WRITE START A quiet thought")
    text = f"I have enough for this draft.\nNEXT: {choice}"
    deliver(prompt, text)
    assert prompt.receipt["choice_feedback"]["selected_next"] == choice
    assert prompt.receipt["choice_feedback"]["recovery_commands"] == ["WRITE FINISH"]
    explanation = prompt.receipt["choice_feedback"]["explanation"]
    assert "not recognized" in explanation
    agent = object.__new__(aa.AutonomousAgent)
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", Mock())
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, None)
    agent._record_llm_next_action_choice.assert_not_called()
    assert agent._pending_next_action == "REST"
    state = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v1.json").read_text())
    assert state["drafts"]["d1"]["finished"] is False
    continued = client.prepare("WRITE CONTINUE")
    assert explanation in continued
    assert "I have enough for this draft." in continued
    retained = json.loads(Path(prompt.receipt["artifact_path"]).read_text())
    assert json.loads(retained["response_json"])["message"]["content"] == text


def test_stateless_feedback_is_shared_and_does_not_prepare_state(tmp_path):
    client = client_for(tmp_path)
    text = "SELF_STUDY OPEN astrid/example.rs 27\nNEXT: SELF_STUDY CONTINUE"
    result = client.analyze_response(text)
    assert result["selected_next"] == "SELF_STUDY CONTINUE"
    assert result["earlier_source_command"] == "SELF_STUDY OPEN astrid/example.rs 27"
    assert not client.workspace.exists()
    recovery = client.analyze_response("FIND astrid/example.rs")
    assert recovery["selected_next"] is None
    assert "SELF_STUDY FIND astrid/example.rs" in recovery["recovery_commands"]


def test_private_finish_feedback_is_separate_from_authored_journal(tmp_path, monkeypatch):
    client = client_for(tmp_path)
    monkeypatch.setattr(aa, "WORKSPACE_DIR", client.workspace)
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    agent = object.__new__(aa.AutonomousAgent)
    text = "This can stand as written.\nNEXT: FINISH"

    def completed(prompt, **kwargs):
        deliver(prompt, text)
        return text

    monkeypatch.setattr(agent, "_query_llm", completed)
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    monkeypatch.setattr(agent, "_write_journal_entry", Mock())
    monkeypatch.setattr(agent, "_state_for_live_surfaces", lambda state, **kwargs: state)
    monkeypatch.setattr(agent, "_record_current_action_artifact", Mock())
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", Mock())
    agent._run_shared_source_study({}, "WRITE START An independent thought")
    agent._record_llm_next_action_choice.assert_not_called()
    journal = next((client.workspace / "private_writing/journal").glob("private_writing_*.txt")).read_text()
    assert journal.endswith(text + "\n")
    notice = next((client.workspace / "private_writing/journal").glob("notice_*.txt")).read_text()
    assert "not queued" in notice and "NEXT: WRITE FINISH" in notice
    calls = agent._record_current_action_artifact.call_args_list
    assert all(call.kwargs["visibility"] == "protected" for call in calls)
    assert agent._write_journal_entry.call_args.args[1] == text
    assert agent._write_journal_entry.call_args.kwargs["private_canvas"] is True


def test_empty_private_generation_only_offers_writing_retry(tmp_path, monkeypatch):
    client = client_for(tmp_path)
    monkeypatch.setattr(aa, "WORKSPACE_DIR", client.workspace)
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    agent = object.__new__(aa.AutonomousAgent)
    monkeypatch.setattr(agent, "_query_llm_with_next", Mock(return_value=(None, None)))
    monkeypatch.setattr(agent, "_record_current_action_artifact", Mock())
    agent._run_shared_source_study({}, "WRITE START An unfinished thought")
    notice = next((client.workspace / "private_writing/journal").glob("notice_*.txt")).read_text()
    assert "WRITE CONTINUE" in notice
    assert "SELF_STUDY CONTINUE" not in notice


@pytest.mark.parametrize("action", ["write START private-topic", "WRITE: START private-topic", "SELF_STUDY REPLACE WRITE: START private-topic"])
def test_malformed_private_request_keeps_failure_and_retry_protected(tmp_path, monkeypatch, action):
    client = client_for(tmp_path)
    monkeypatch.setattr(aa, "WORKSPACE_DIR", client.workspace)
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    agent = object.__new__(aa.AutonomousAgent)
    monkeypatch.setattr(agent, "_record_current_action_artifact", Mock())
    monkeypatch.setattr(agent, "_record_introspect_notice", Mock())
    monkeypatch.setattr(agent, "_query_llm_with_next", Mock(side_effect=AssertionError("private syntax must fail before source recovery/generation")))
    agent._run_shared_source_study({}, action)
    agent._record_introspect_notice.assert_not_called()
    agent._query_llm_with_next.assert_not_called()
    assert not (client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json").exists()
    notice = next((client.workspace / "private_writing/journal").glob("notice_*.txt")).read_text()
    assert "WRITE CONTINUE" in notice
    assert "SELF_STUDY CONTINUE" not in notice
    assert agent._record_current_action_artifact.call_args.kwargs["visibility"] == "protected"


def test_both_hosts_share_choice_scanner_and_feedback_fixtures(tmp_path):
    from minime_autonomy.parsing import eligible_choice_line_indices
    fixture_path = Path(os.environ.get(
        "ASTRID_CHOICE_FIXTURES",
        str(Path(__file__).resolve().parents[2] / "astrid/crates/astrid-source-study/tests/fixtures/response_choice_cases.json"),
    ))
    fixtures = json.loads(fixture_path.read_text())
    client = client_for(tmp_path)
    for fixture in fixtures:
        text = fixture["text"]
        assert eligible_choice_line_indices(text.split("\n")) == fixture["eligible_indices"], fixture["name"]
        assert aa.parse_next_action(text)[0] == fixture["selected_next"], fixture["name"]
        observed = client.analyze_response(text, private_writing=fixture["private_writing"])
        for field in ("selected_next", "selection_kind", "earlier_source_command", "recovery_commands"):
            assert observed[field] == fixture[field], (fixture["name"], field)
    assert not client.workspace.exists()
