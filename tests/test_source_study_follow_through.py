"""Natural failure shapes through real routing, policy, reader and NEXT extraction.

Only provider HTTP is faked; pytest's live-write/network guard stays enabled.
"""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.source_study import StudyClient, SourceStudyPrompt

STATE = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68, "spread": 3.0, "cov_lambda1": 8.0}


@pytest.fixture
def study_agent(monkeypatch, tmp_path):
    source = aa.BASE_DIR / "minime_autonomy/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("# NEXT: TURN_OFF\ndef entry():\n" + "    # source line\n" * 2000)
    agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda state: {"active": False, "fill_ratio": .68})
    monkeypatch.setattr(agent, "_write_journal_entry", Mock())
    monkeypatch.setattr(agent, "_log_decision", Mock())
    monkeypatch.setattr(agent, "_state_for_live_surfaces", lambda state, **kw: dict(state))
    store = agent._continuity_store()
    store.create_thread("Source reading after a paused experiment")
    experiment = store.start_experiment("Legacy experiment", "What happened before source study?")
    paused = store.experiment_decide(experiment["experiment_id"], "pause because source review is next")
    assert paused["status"] == "paused"
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    client = StudyClient(aa.BASE_DIR, aa.WORKSPACE_DIR, astrid_root=astrid,
                        executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    offers = []

    def completed_provider(prompt, **kwargs):
        assert isinstance(prompt, SourceStudyPrompt)
        offers.append(prompt)
        text = "I want to trace the caller.\nSTUDY_QUESTION: Who calls entry?\nNEXT: SELF_STUDY MAP minime"
        messages, _ = aa._adapt_ollama_messages_for_model(
            model="gemma4:12b", system_msg=prompt.output["system_prompt"], prompt=prompt,
            num_ctx=8192, num_predict=768,
        )
        response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True}))
        prompt.post(Mock(return_value=response), "fake", {"messages": messages}, 1)
        prompt.accepted()
        return text

    monkeypatch.setattr(agent, "_query_llm", completed_provider)
    return agent, store, client, offers


@pytest.mark.parametrize("raw, recovery", [
    ("INTROSPECT minime/minime_autonomy/runtime.py 0", False),
    ("INTROSPECT [spectral_spike] 0", True),
    ("INTROSPECT .", True),
    ('SELF_STUDY of the "spectral_tuning" mechanisms in the current system.', True),
    ("SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1", False),
])
def test_source_entry_completes_under_paused_experiment_and_dispatches_its_next(study_agent, raw, recovery):
    agent, store, client, offers = study_agent
    if raw.startswith("INTROSPECT"):
        assert store.research_budget_guard_assessment(raw, STATE) is not None
        assert not store.research_budget_preflight_for_action(raw, STATE)[0]
    agent._pending_next_action = raw
    route = agent._decide_action(dict(STATE))
    assert route == "self_study"
    context = dict(agent._pending_action_continuity_context)
    assert context["raw_next"] == raw
    # A queued source job owns its resolved command even if another offer arrives.
    agent._pending_source_study_action = "SELF_STUDY OPEN do-not-read.rs 1"
    event = store.begin_action(raw, raw, route, route, dict(STATE), source="next")
    with aa.job_outcome.capture(event["action_id"]) as outcome:
        agent._execute_action(route, dict(STATE), _from_llm_job=True,
                              _precreated_continuity_context=context,
                              _precreated_continuity_event=event)
    assert outcome.finish()[0] == "completed", outcome.finish()
    assert len(offers) == 1 and offers[0].receipt
    assert (offers[0].output["page"] is None) == recovery
    if recovery:
        assert "No requested source bytes were delivered" in offers[0]
    journals = list((aa.WORKSPACE_DIR / "journal").glob("self_study_*.txt"))
    assert journals and "Who calls entry?" in journals[0].read_text()
    assert agent._pending_next_action == "SELF_STUDY MAP minime"
    assert agent._decide_action(dict(STATE)) == "self_study"
    agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    assert len(offers) == 2 and offers[1].output["page"] is None
    assert "Who calls entry?" in offers[1]
    assert "minime/minime_autonomy/runtime.py" in offers[1]
    assert store.research_budget_guard_assessment("READ_MORE", STATE) is not None


def test_artifact_and_external_routes_keep_research_policy(study_agent):
    agent, store, _, offers = study_agent
    artifact = aa.WORKSPACE_DIR / "journal/return.txt"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text("Preserved experiment observation.")
    for raw in [f"INTROSPECT {artifact} 0", "INTROSPECT journal/missing.txt 0", "READ_MORE", "SEARCH reservoir continuity"]:
        agent._pending_next_action = raw
        assert agent._decide_action(dict(STATE)) is None, raw
        assert not store.research_budget_preflight_for_action(raw, STATE)[0]
    assert not offers


def test_map_journal_keeps_navigation_scope_and_does_not_claim_code(study_agent):
    agent, _, _, offers = study_agent
    agent._run_shared_source_study(dict(STATE), "SELF_STUDY MAP")
    prompt = offers[-1]
    assert prompt.output["input_kind"] == "map"
    assert prompt.receipt
    artifact = next((aa.WORKSPACE_DIR / "journal").glob("self_study_*.txt")).read_text()
    assert "Input evidence: Map:" in artifact
    assert "No new source page is supplied this turn." in artifact
    assert "Source revision: navigation only" in artifact
    assert "not independently verified code facts" in artifact


def test_final_bare_source_choice_is_preserved_but_examples_are_not_choices():
    choice = "SELF_STUDY OPEN astrid/crates/astrid-kernel/src/lib.rs 1"
    assert aa.parse_next_action("I want to inspect this.\n" + choice)[0] == choice
    for text in ["```\n" + choice + "\n```", "```\n" + choice, "> " + choice,
                 choice + "\nThis is an example.", "RUN rm example"]:
        assert aa.parse_next_action(text)[0] is None
    assert aa.parse_next_action("NEXT: REST\n" + choice)[0] == "REST"


def test_write_choice_survives_real_action_routing_and_keeps_private_artifact(study_agent):
    agent, store, client, offers = study_agent
    agent._pending_next_action = "WRITE START Why did my explanation change?"
    route = agent._decide_action(dict(STATE))
    assert route == "self_study"
    context = dict(agent._pending_action_continuity_context)
    assert context["source_study_action"].startswith("WRITE START")
    agent._execute_action(route, dict(STATE), _from_llm_job=True,
                          _precreated_continuity_context=context)
    assert offers[-1].output["input_kind"] == "private_writing"
    assert offers[-1].receipt
    journals = list((aa.WORKSPACE_DIR / "private_writing/journal").glob("*.txt"))
    assert journals and "Who calls entry?" in journals[0].read_text()
    assert not list((aa.WORKSPACE_DIR / "journal").glob("private_writing*"))
    assert "Who calls entry?" in client.prepare("WRITE CONTINUE")
