"""Real dispatcher/reader regression for the observed exit loop; synthetic provider only."""
import json
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.study_feedback import StudyFeedback
from tests.test_source_study_follow_through import study_agent, STATE


def execute_choice(agent, raw):
    agent._record_llm_next_action_choice(raw, "", reason="test choice")
    route = agent._decide_action(dict(STATE))
    assert route == "self_study"
    agent._execute_action(route, dict(STATE), _from_llm_job=True)


@pytest.mark.parametrize("raw", [
    "QUESTION RESOLVE " + "f" * 64,
    "SELF_STUDY QUESTION RESOLVE " + "f" * 64,
    "SELF_STUDY QUESTION RESOLVE q1",
])
def test_invalid_closure_reaches_recovery_and_next_input_contains_outcome(study_agent, raw):
    agent, _, client, offers = study_agent
    execute_choice(agent, raw)
    assert offers[-1].output["input_kind"] == "recovery"
    assert "No numbered inquiry is selected" in offers[-1]
    saved = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json").read_text())
    assert saved["questions"]["entries"] == {}
    records = StudyFeedback(aa.WORKSPACE_DIR).load()["records"]
    attempt = next(r for r in records if r["action"] == raw)
    assert attempt["reader_outcome"]["status"] == "rejected"
    assert attempt["reader_outcome"]["input_id"] == offers[-1].output["navigation_id"]
    next_input = client.prepare("SELF_STUDY MAP")
    assert '"status":"rejected"' in next_input
    assert "HOST STUDY ACTION OUTCOMES" in next_input
    proposals = list((aa.WORKSPACE_DIR / "action_threads").glob("proposals.jsonl"))
    assert not proposals or "Unknown NEXT fell back" not in proposals[0].read_text()


def test_named_closure_records_reader_effect_separately_from_generation(study_agent):
    agent, _, client, _ = study_agent
    client.prepare("SELF_STUDY QUESTION NEW Where is the gate?")
    raw = "SELF_STUDY QUESTION RESOLVE q1 Location remains uncertain."
    execute_choice(agent, raw)
    records = StudyFeedback(aa.WORKSPACE_DIR).load()["records"]
    attempt = next(r for r in records if r["action"] == raw)
    assert attempt["reader_outcome"]["status"] == "applied"
    assert attempt["status"] == "completed"
    saved = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json").read_text())
    assert saved["questions"]["entries"]["q1"]["status"] == "resolved by you"


def test_rest_then_later_study_uses_eof_decision_and_dispatch_provenance(study_agent, monkeypatch):
    agent, _, client, offers = study_agent
    (client.minime_root / "minime_autonomy/runtime.py").write_text("def entry(): pass\n")

    def provider(prompt, **kwargs):
        offers.append(prompt)
        text = "STUDY_QUESTION: The gate remains unverified.\nNEXT: REST"
        response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True}))
        prompt.post(Mock(return_value=response), "fake", {"messages": [
            {"role": "system", "content": prompt.output["system_prompt"]},
            {"role": "user", "content": str(prompt)}]}, 1)
        prompt.accepted()
        return text

    monkeypatch.setattr(agent, "_query_llm", provider)
    execute_choice(agent, "SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1")
    receipt = offers[-1].receipt
    assert agent._pending_next_action == "REST"
    assert agent._decide_action(dict(STATE)) is None
    records = StudyFeedback(aa.WORKSPACE_DIR).load()["records"]
    rest = next(r for r in records if r["action"] == "REST")
    assert rest["status"] == "skipped"
    assert rest["origin"]["response_sha256"] == receipt["response_sha256"]
    execute_choice(agent, "SELF_STUDY")
    assert offers[-1].output["input_kind"] == "end_of_file"
    assert "continuation decision" in offers[-1].output["system_prompt"]
    assert "RECALLED ACCOUNT" not in offers[-1]
    assert '"status":"skipped"' in offers[-1]
    assert len(list((aa.WORKSPACE_DIR / "journal").glob("study_decision_*.txt"))) == 1
    assert agent._write_journal_entry.call_args.kwargs["verified_source_study"] is False


def test_later_choice_reports_rest_superseded_before_dispatch(study_agent, monkeypatch):
    agent, _, client, offers = study_agent
    def provider(prompt, **kwargs):
        offers.append(prompt)
        text = "NEXT: REST"
        response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True}))
        prompt.post(Mock(return_value=response), "fake", {"messages": [
            {"role": "user", "content": str(prompt)}]}, 1)
        prompt.accepted()
        return text
    monkeypatch.setattr(agent, "_query_llm", provider)
    execute_choice(agent, "SELF_STUDY MAP")
    origin = offers[-1].receipt
    assert agent._pending_next_action == "REST"
    agent._record_llm_next_action_choice("REGIME focus", "", reason="test choice")
    receipt = next(r for r in StudyFeedback(aa.WORKSPACE_DIR).load()["records"] if r["action"] == "REST")
    assert receipt["status"] == "superseded"
    assert receipt["origin"]["response_sha256"] == origin["response_sha256"]
    assert agent._pending_next_action == "REGIME focus"
    assert '"status":"superseded"' in client.prepare("SELF_STUDY MAP")
