"""Keep regulation input intact and incomplete charters visibly incomplete."""

import json
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy import generation_record
from minime_autonomy.session_contract import ContinuityReply
from tests.test_journal_context import runtime


STATE = {"fill_ratio": .68, "eig1": 4.7, "cov_lambda1": 8., "spread": 3., "leak": .9}


@pytest.mark.parametrize("model,context,cap", [
    ("gemma4:12b", 10240, 1536), ("gemma3:4b", 8192, 768),
])
def test_scheduled_review_keeps_json_contract_through_actual_adapter(
    runtime, monkeypatch, model, context, cap,
):
    agent, workspace, _ = runtime
    agent._hard_recovery_reset = False
    agent._sovereignty_counter = 4
    monkeypatch.setattr(agent, "_stable_core_reflective_only", lambda: False)
    monkeypatch.setattr(agent, "_attractor_fatigue_memory_decay_rate", lambda state: None)
    for name in ("_emit_next_hints", "_action_continuity_prompt_summary",
                 "_owner_inquiry_prompt_summary", "_get_relevant_research",
                 "_read_inbox", "_read_whisper_context", "_division_prompt_guidance"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError(name)))
    calls = []

    def provider(prompt, system, max_tokens, **kwargs):
        calls.append((prompt, system, max_tokens, kwargs))
        messages, report = aa._adapt_ollama_messages_for_model(
            model=model, system_msg=system, prompt=prompt,
            num_ctx=context, num_predict=cap, compact=True,
        )
        assert not report["prompt_compacted"]
        assert prompt in messages[-1]["content"]
        assert 'Reply with ONLY a JSON object' in messages[-1]["content"]
        assert '"regime": "<explore|recover|breathe|focus|calm>"' in messages[-1]["content"]
        assert "Workbench charter:" not in messages[-1]["content"]
        assert "NEXT: options:" not in system
        assert "At the end of your response" not in system
        # No controls or choices are synthesized from an unavailable response.
        return None

    monkeypatch.setattr(agent, "_query_llm_raw", provider)
    regulate = Mock()
    monkeypatch.setattr(agent, "_send_regulation", regulate)
    agent._self_regulate(dict(STATE))
    assert len(calls) == 1
    assert calls[0][2:] == (4096, {"prompt_class": "strict_review", "journal": True})
    regulate.assert_called_once()
    assert agent._pending_next_action is None
    assert not list((workspace / "journal").glob("*.txt"))


def test_protected_attention_defers_scoped_review(runtime, monkeypatch):
    agent, _, _ = runtime
    monkeypatch.setattr(agent, "_attention_protected", lambda: True)
    query = Mock(side_effect=AssertionError("unrelated generation during protected work"))
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    assert agent._query_llm("JSON contract", context_mode="regulation_review") is None
    query.assert_not_called()


@pytest.mark.parametrize("choice", ["REST", "JOURNAL", "EXPERIMENT_CHARTER current :: hypothesis: a new claim; proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; evidence_targets: artifact"])
def test_scoped_review_preserves_an_explicit_authored_choice(runtime, monkeypatch, choice):
    agent, _, _ = runtime
    response = "An exact returned account.\nNEXT: " + choice
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value=response))
    monkeypatch.setattr(agent, "_emit_next_hints", Mock(side_effect=AssertionError("ambient hints")))
    output, selected = agent._query_llm_with_next("JSON contract", context_mode="regulation_review")
    assert output == response and selected == choice
    assert agent._pending_next_action == choice


@pytest.mark.parametrize("command", [
    "EXPERIMENT_CHARTER", "EXPERIMENT_CHARTER current", "EXPERIMENT_CHARTER current :: hypothesis: ...",
])
def test_incomplete_charter_is_needs_input_without_authored_state_mutation(runtime, command):
    agent, _, _ = runtime
    store = agent._continuity_store()
    thread = store.create_thread("Synthetic inquiry")
    experiment = store.start_experiment("Synthetic plan", "What does this test establish?")
    before = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
    response = store.handle_thread_action(command, dict(STATE))
    assert isinstance(response, ContinuityReply)
    assert response.receipt == {
        "schema": "continuity_action_result_v1", "status": "needs_input",
        "persisted": False, "record_ref": None, "authority_change": False,
    }
    assert "no charter was recorded" in response
    assert store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"]) == before
    assert agent._pending_next_action is None


def test_explicit_complete_charter_still_records_without_execution(runtime):
    agent, _, _ = runtime
    store = agent._continuity_store()
    thread = store.create_thread("Synthetic inquiry")
    experiment = store.start_experiment("Synthetic plan", "A saved question")
    message = store.handle_thread_action(
        "EXPERIMENT_CHARTER current :: hypothesis: an authored fixture claim; "
        "proposed_next_action: ACTION_PREFLIGHT DECOMPOSE; evidence_targets: artifact; "
        "stop_criteria: end of fixture", dict(STATE),
    )
    assert "Experiment charter recorded" in message
    latest = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
    assert latest["charter_v1"]["hypothesis"] == "an authored fixture claim"
    assert agent._pending_next_action is None


def test_charter_needs_input_survives_real_execution_and_manifest(runtime, monkeypatch):
    agent, workspace, _ = runtime
    agent.running = False
    agent._hard_recovery_reset = False
    store = agent._continuity_store()
    store.create_thread("Synthetic inquiry")
    experiment = store.start_experiment("Synthetic plan", "A saved question")
    before = store._find_experiment_by_id(store.current_thread()["thread_id"], experiment["experiment_id"])
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda state: {"active": False})
    monkeypatch.setattr(agent, "_log_decision", Mock())
    success = Mock()
    monkeypatch.setattr(agent, "_record_stable_core_agent_success", success)
    context = {"raw_next": "EXPERIMENT_CHARTER", "canonical_action": "EXPERIMENT_CHARTER",
               "source": "next"}
    agent._execute_action("thread_action", dict(STATE), _from_llm_job=True,
                          _precreated_continuity_context=context)
    event = agent._last_action_continuity_event
    assert event["status"] == "needs_input"
    assert event["stage"] == "needs_input"
    assert "no charter was recorded" in event["outcome_summary"]
    assert "Executed autonomous action" not in event["outcome_summary"]
    manifest = json.loads(next((workspace / "actions").glob("*_thread_action.json")).read_text())
    assert manifest["action_continuity"]["outcome_summary"] == event["outcome_summary"]
    assert store._find_experiment_by_id(store.current_thread()["thread_id"], experiment["experiment_id"]) == before
    success.assert_not_called()
    assert agent._pending_next_action is None


def test_scheduled_regulation_is_an_identified_diagnostic_lane():
    def _self_regulate():
        return generation_record.infer_lane()
    metadata = _self_regulate()
    assert metadata["lane"] == "self_regulate"
    assert metadata["lane_source"] == "frame"
