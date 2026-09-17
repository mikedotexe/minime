"""Verified private choices reach the real queue/dispatcher, using isolated state."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.source_study import SourceStudyPrompt, StudyClient


STATE = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68, "spread": 3.0, "cov_lambda1": 8.0}


@pytest.fixture
def writing_agent(monkeypatch, tmp_path):
    agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda state: {"active": False, "fill_ratio": .68})
    monkeypatch.setattr(agent, "_write_journal_entry", Mock())
    monkeypatch.setattr(agent, "_log_decision", Mock())
    monkeypatch.setattr(agent, "_state_for_live_surfaces", lambda state, **kw: dict(state))
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    client = StudyClient(aa.BASE_DIR, aa.WORKSPACE_DIR, astrid_root=astrid,
                        executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    return agent, client


def deliver(prompt, text, *, finish_reason="stop"):
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    response = Mock(status_code=200, text=json.dumps({
        "message": {"content": text}, "done": True, "done_reason": finish_reason,
    }))
    prompt.post(Mock(return_value=response), "fake", {"messages": messages}, 1)
    prompt.accepted()


@pytest.mark.parametrize("choice", ["CONTINUE", "continue", "WRITE CONTINUE"])
def test_private_choice_reaches_queue_dispatch_and_same_draft(writing_agent, monkeypatch, choice):
    agent, client = writing_agent
    offers = []

    def completed(prompt, **kwargs):
        assert isinstance(prompt, SourceStudyPrompt)
        offers.append(prompt)
        text = f"First passage.\nNEXT: {choice}" if len(offers) == 1 else "Second passage.\nNEXT: REST"
        deliver(prompt, text)
        return text

    monkeypatch.setattr(agent, "_query_llm", completed)
    agent._pending_next_action = "WRITE START A developing account"
    assert agent._decide_action(dict(STATE)) == "self_study"
    agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    assert len(offers) == 1
    feedback = offers[0].receipt["choice_feedback"]
    assert feedback["selected_next"] == choice
    assert feedback.get("normalized_next") == (None if choice == "WRITE CONTINUE" else "WRITE CONTINUE")
    assert agent._last_llm_response.endswith(f"NEXT: {choice}")
    assert agent._pending_next_action == "WRITE CONTINUE"
    envelope = agent._pending_choice_envelope_v1
    if choice != "WRITE CONTINUE":
        assert envelope["raw_next"] == choice
        assert envelope["executable_next"] == "WRITE CONTINUE"
        normalization = envelope["private_writing_normalization"]
        assert normalization["authored_next"] == choice
        assert normalization["input_id"] == offers[0].receipt["page_id"]
        assert normalization["request_sha256"] == offers[0].receipt["request_sha256"]
        assert normalization["response_sha256"] == offers[0].receipt["response_sha256"]
        saved = json.loads(Path(agent._sovereignty_state_path()).read_text())
        assert saved["choice_envelope_v1"] == envelope
        agent._pending_next_action = None
        agent._pending_choice_envelope_v1 = None
        monkeypatch.setattr(agent, "_stable_core_reflective_only", lambda: False)
        monkeypatch.setattr(agent, "_hard_recovery_reset", True)
        agent._restore_sovereignty_state()
        assert agent._pending_next_action == "WRITE CONTINUE"
        assert agent._pending_choice_envelope_v1 == envelope
    assert agent._decide_action(dict(STATE)) == "self_study"
    assert agent._pending_action_continuity_context["source_study_action"] == "WRITE CONTINUE"
    if envelope:
        assert agent._pending_action_continuity_context["choice_envelope_v1"] == envelope
    agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    assert len(offers) == 2
    if envelope:
        assert agent._last_action_continuity_event["choice_envelope_v1"] == envelope
    assert "chosen action: WRITE CONTINUE" in offers[1]
    assert "Draft d1, revision 1" in offers[1]
    assert "First passage." in offers[1]
    state = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v1.json").read_text())
    assert state["drafts"]["d1"]["parts"] == ["First passage.", "Second passage."]
    assert list(state["drafts"]) == ["d1"]


@pytest.mark.parametrize("finish_reason, text", [
    ("length", "Partial passage.\nNEXT: CONTINUE"),
    ("length", "Partial passage.\nNEXT: WRITE CONTINUE"),
    ("stop", ""),
])
def test_failed_private_delivery_never_queues_or_advances(writing_agent, monkeypatch, finish_reason, text):
    agent, client = writing_agent
    offers = []

    def failed(prompt, **kwargs):
        offers.append(prompt)
        deliver(prompt, text, finish_reason=finish_reason)
        return text

    monkeypatch.setattr(agent, "_query_llm", failed)
    agent._pending_next_action = "REST"
    agent._run_shared_source_study(dict(STATE), "WRITE START A pending thought")
    assert offers[0].receipt is None
    assert agent._pending_next_action == "REST"
    assert client.prepare("WRITE CONTINUE").output == offers[0].output
    state = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v1.json").read_text())
    assert state["drafts"]["d1"]["revision"] == 0
    assert state["drafts"]["d1"]["parts"] == []


@pytest.mark.parametrize("text", [
    "I will continue this draft.", "CONTINUE", "> NEXT: CONTINUE",
    "```\nNEXT: CONTINUE\n```", "<think>\nNEXT: CONTINUE\n</think>\nA thought.",
])
def test_prose_or_quoted_continuation_never_queues(writing_agent, monkeypatch, text):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A thought")
    deliver(prompt, text)
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, None)
    assert agent._pending_next_action == "REST"


def test_unverified_shorthand_does_not_use_stateless_or_previous_feedback(writing_agent, monkeypatch):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A pending thought")
    text = "A passage.\nNEXT: CONTINUE"
    assert client.analyze_response(text, private_writing=True)["normalized_next"] == "WRITE CONTINUE"
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, None)
    assert agent._pending_next_action == "REST"


def test_previous_same_verb_receipt_cannot_authorize_a_new_private_turn(writing_agent, monkeypatch):
    agent, client = writing_agent
    first = client.prepare("WRITE START First turn")
    old_text = "Old passage.\nNEXT: CONTINUE"
    deliver(first, old_text)
    current = client.prepare("WRITE CONTINUE")
    current_text = "Different passage.\nNEXT: CONTINUE"
    deliver(current, current_text)
    assert current.verified_choice_feedback(current_text)["normalized_next"] == "WRITE CONTINUE"
    # Both responses selected the same verb; only their current identities differ.
    current.receipt = first.receipt
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=current_text))
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(current, context_mode="source_study") == (current_text, None)
    assert agent._pending_next_action == "REST"
    current._wire = first._wire
    assert current.verified_choice_feedback(old_text) == {}


@pytest.mark.parametrize("field", ["page_id", "request_sha256", "response_sha256", "returned_text"])
def test_mismatched_same_verb_delivery_evidence_cannot_queue(writing_agent, monkeypatch, field):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A thought")
    text = "Current passage.\nNEXT: CONTINUE"
    deliver(prompt, text)
    if field == "returned_text":
        text = "Unrelated substituted passage.\nNEXT: CONTINUE"
    else:
        prompt.receipt[field] = "not-this-delivery"
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, None)
    assert agent._pending_next_action == "REST"


@pytest.mark.parametrize("failure", ["preflight", "transport", "http", "delivery"])
def test_reposting_clears_previous_verified_authorization(writing_agent, monkeypatch, failure):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A thought")
    text = "Original passage.\nNEXT: CONTINUE"
    deliver(prompt, text)
    assert prompt.verified_choice_feedback(text)
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    if failure == "preflight":
        with pytest.raises(ValueError):
            prompt.post(Mock(), "fake", {"messages": []}, 1)
    elif failure == "transport":
        with pytest.raises(OSError):
            prompt.post(Mock(side_effect=OSError("isolated failure")), "fake", {"messages": messages}, 1)
    elif failure == "http":
        prompt.post(Mock(return_value=Mock(status_code=503, text="unavailable")), "fake", {"messages": messages}, 1)
    else:
        with pytest.raises(RuntimeError):
            deliver(prompt, text, finish_reason="length")
    assert prompt.receipt is None
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    agent._pending_next_action = "REST"
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, None)
    assert agent._pending_next_action == "REST"


def test_current_wire_cleanup_chain_still_authorizes_exact_visible_response(writing_agent, monkeypatch):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A thought")
    raw = "  <think>Hidden processing.</think>\nVisible passage.\nNEXT: CONTINUE  "
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    response = Mock(status_code=200, text=json.dumps({
        "message": {"content": raw}, "done": True, "done_reason": "stop",
    }))
    prompt.post(Mock(return_value=response), "fake", {"messages": messages}, 1)
    visible = prompt.clean_content(agent._clean_llm_content, raw.strip())
    visible = prompt.clean_content(agent._strip_model_artifacts, visible)
    prompt.accepted()
    assert raw != visible
    assert prompt.verified_choice_feedback(visible)["normalized_next"] == "WRITE CONTINUE"
    assert prompt.verified_choice_feedback(raw) == {}
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=visible))
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (visible, "WRITE CONTINUE")
    assert agent._pending_next_action == "WRITE CONTINUE"


def test_private_normalization_updates_existing_metadata_envelope(writing_agent, monkeypatch):
    agent, client = writing_agent
    prompt = client.prepare("WRITE START A thought")
    text = "Primary NEXT: CONTINUE\nAlternate NEXT: REST\nWhy this path: Keep developing.\nNEXT: CONTINUE"
    deliver(prompt, text)
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, "WRITE CONTINUE")
    envelope = agent._pending_choice_envelope_v1
    assert envelope["primary_next"] == "CONTINUE"
    assert envelope["raw_next"] == "CONTINUE"
    assert envelope["executable_next"] == "WRITE CONTINUE"
    assert envelope["alternate_nexts"] == ["REST"]
    assert envelope["why_this_path"] == "Keep developing."
    assert envelope["private_writing_normalization"]["input_id"] == prompt.output["navigation_id"]


def test_global_continue_is_not_a_private_writing_alias(writing_agent, monkeypatch, caplog):
    agent, client = writing_agent
    text = "NEXT: CONTINUE"
    prompt = client.prepare("SELF_STUDY MAP")
    deliver(prompt, text)
    assert prompt.receipt["choice_feedback"].get("normalized_next") is None
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    assert agent._query_llm_with_next(prompt, context_mode="source_study") == (text, "CONTINUE")
    assert agent._pending_next_action == "CONTINUE"
    with caplog.at_level("INFO"):
        agent._decide_action(dict(STATE))
    assert "Unknown NEXT: 'CONTINUE'" in caplog.text
    assert agent._pending_source_study_action is None
