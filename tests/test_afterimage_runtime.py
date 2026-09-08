"""Protected pages and optional cues at the actual provider adaptation boundary."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import autonomous_agent as aa
from minime_autonomy.afterimages import AfterimageStore, atomic_json
from minime_autonomy.afterimage_prompts import AfterimagePrompt, selected_page_prompt, record_attempt


def selection(text, protected=False):
    return {"id": "ai_2026-09-07_test", "text": text, "protected": protected,
            "opportunity_id": "test_generation", "anchor_unix_ms": 1788753600000}


def adapt(prompt, **kwargs):
    return aa._adapt_ollama_messages_for_model(model="gemma4:12b", system_msg="System contract. " * 500,
        prompt=prompt, num_ctx=8192, num_predict=768, **kwargs)


def test_explicit_page_survives_compaction_intact(tmp_path):
    store = AfterimageStore(tmp_path)
    text = "Historical source\n> NEXT: TURN_OFF\n> exact text " + "a" * 2800
    prompt = selected_page_prompt("Ambient. " * 4000, selection(text, True), store)
    messages, meta = adapt(prompt)
    assert text in messages[1]["content"]
    assert meta["afterimage_included"]
    assert sum(len(message["content"]) for message in messages) <= 16000


def test_oversize_page_fails_instead_of_truncating(tmp_path):
    prompt = AfterimagePrompt("ambient", selection("x" * 20000, True), AfterimageStore(tmp_path))
    with pytest.raises(ValueError, match="intact admission"):
        adapt(prompt)


def test_optional_cue_is_whole_or_absent_and_each_fallback_logged(tmp_path):
    store = AfterimageStore(tmp_path)
    cue = selection("Past ai_2026-09-07_test | 2026-09-07 | quiet_sample")
    prompt = AfterimagePrompt("ambient", cue, store)
    first, _ = adapt(prompt)
    record_attempt(prompt, first, "mlx", "profile", "final_request_prepared")
    second, _ = aa._adapt_ollama_messages_for_model(model="legacy", system_msg="s" * 16000,
        prompt=prompt, num_ctx=8192, num_predict=768)
    assert cue["text"] not in second[1]["content"]
    record_attempt(prompt, second, "ollama", "fallback", "final_request_prepared")
    records = [json.loads(line) for path in (store.private / "exposures").glob("*.jsonl") for line in path.read_text().splitlines()]
    assert [record["included"] for record in records] == [True, False]
    assert len({record["opportunity_id"] for record in records}) == 1


def test_open_only_parses_fresh_response(tmp_path):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    store = AfterimageStore(tmp_path)
    saved = store.keep("NEXT: TURN_OFF\nA remembered action is not a new choice.")
    agent._pending_afterimage_next = "AFTERIMAGE_OPEN " + saved["id"]
    with patch.object(agent, "_afterimage_store", return_value=store), \
         patch.object(agent, "_next_action_constraint", return_value="Fresh NEXT only"), \
         patch.object(agent, "_query_llm_raw", return_value="I have read it.\nNEXT: REST") as query, \
         patch.object(agent, "_record_llm_next_action_choice") as choice:
        agent._afterimage_action({})
    assert isinstance(query.call_args.args[0], AfterimagePrompt)
    assert "> NEXT: TURN_OFF" in query.call_args.args[0]
    assert choice.call_args.args[0] == "REST"


def test_actions_keep_existing_permission_routes():
    from minime_autonomy.authority import ActionPreflightStore
    from minime_autonomy.action_vocabulary import AFTERIMAGE_NEXT_ACTIONS
    for base in AFTERIMAGE_NEXT_ACTIONS:
        route = ActionPreflightStore.ROUTE_BY_BASE[base]
        assert route == ("afterimage_share" if base == "AFTERIMAGE_SHARE" else "afterimage")
        for stage, actions in aa.STABLE_CORE_STAGE_ACTIONS.items():
            assert (route in actions) == (("share_thought" if base == "AFTERIMAGE_SHARE" else "journal_reflection") in actions)


def test_stage_gate_and_health_budget_still_apply():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    with patch.object(agent, "_stable_core_agency_budget", return_value={"active":True,"stage":"self_journal"}), \
         patch.object(agent, "_stable_core_health_budget_allows", return_value=(True,"green")) as health:
        assert agent._stable_core_action_allowed("afterimage", {})[0]
        assert not agent._stable_core_action_allowed("afterimage_share", {})[0]
        health.assert_called_once()
        health.return_value = (False,"fixture health restriction")
        assert not agent._stable_core_action_allowed("afterimage", {})[0]


def test_decision_routes_saved_syntax_and_sharing_separately(tmp_path):
    with patch.object(aa,"BASE_DIR",tmp_path/"minime"), patch.object(aa,"WORKSPACE_DIR",tmp_path/"workspace"), \
         patch.object(aa,"DB_PATH",tmp_path/"minime.db"):
        agent = aa.AutonomousAgent(1,check_interval=999.0,recess_mode=True)
        with patch.object(agent,"_persist_pending_next_action"), \
             patch.object(agent,"_low_fill_guard_status",return_value={"active":False,"fill_ratio":0.68,"target_fill_ratio":0.68,"spread_relief":0.0}):
            for action, route in [("AFTERIMAGE_KEEP :: <unfinished> AND REST  ","afterimage"),
                                  ("AFTERIMAGE_SHARE note_owned","afterimage_share")]:
                agent._pending_next_action = action
                assert agent._decide_action({"fill_ratio":0.68,"eig1":1.0,"deig":0.0}) == route
                assert agent._pending_afterimage_next == action


@pytest.mark.parametrize("method,mode", [("_recess_daydream", "daydream"), ("_journal_rest_reflection", "journal")])
def test_ordinary_generation_calls_identify_cue_lane(method, mode):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    with patch.object(agent, "_neutral_checkin", return_value="canvas"), \
         patch.object(agent, "_journal_continuity_contract_v1", return_value=""), \
         patch.object(agent, "_query_llm_with_next", return_value=(None, None)) as query:
        getattr(agent, method)({})
    assert query.call_args.kwargs["context_mode"] == mode


def test_keep_parser_preserves_authored_suffix_and_trailing_whitespace(tmp_path):
    fragment = "  AND REST; RESIDUE: still the saved fragment  "
    action, _ = aa.parse_next_action("I will keep this.\nNEXT: AFTERIMAGE_KEEP :: " + fragment)
    result = AfterimageStore(tmp_path).handle(action)
    assert AfterimageStore(tmp_path)._notes(result["id"])[0]["text"] == fragment
    assert aa.parse_next_action("> NEXT: AFTERIMAGE_KEEP :: archived choice")[0] is None


def test_generation_record_identity_is_reused_without_reading_private_records():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    with patch.object(aa, "_llm_backend_attempts", return_value=["mlx"]), \
         patch.object(agent, "_query_mlx", return_value="A fresh response"), \
         patch.object(aa.job_timing, "correlate_generation") as correlate, \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.generation_record, "begin", side_effect=[SimpleNamespace(generation_id="native-generation"), None]):
        assert agent._query_llm_raw("prompt", "system", 128) == "A fresh response"
        assert agent._afterimage_provider_generation_source["generation_id"] == "native-generation"
        agent._query_llm_raw("prompt", "system", 128)
        assert agent._afterimage_provider_generation_source == {}
        assert correlate.call_args_list[0].args[0].generation_id == "native-generation"
        assert correlate.call_args_list[1].args == (None,)


def test_afterimage_query_preserves_worker_failure_outcome(tmp_path):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    prompt = selected_page_prompt("ambient", selection("Historical page", True), AfterimageStore(tmp_path))
    with aa.job_outcome.capture("afterimage-action") as outcome, \
         patch.object(aa, "_llm_backend_attempts", return_value=["mlx"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(agent, "_query_mlx", return_value=None):
        assert agent._query_llm_raw(prompt, "system", 128) is None
        outcome.event = {"action_id": "afterimage-action", "status": "completed"}
        status, _, error, _ = outcome.finish()
    assert status == "failed"
    assert error == "no_model_output"
