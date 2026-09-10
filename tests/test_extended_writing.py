"""Shared draft and actual provider-adapter checks; no live model or messages."""
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch
import autonomous_agent as aa
from minime_autonomy import writing
from minime_autonomy.source_study import StudyClient, SourceStudyPrompt


def test_explicit_profiles_survive_all_provider_clamps_and_job_deadlines(tmp_path):
    agent = object.__new__(aa.AutonomousAgent)
    pref = tmp_path / "diagnostics/source_first_v3/shared_reader/writing/profile.json"
    pref.parent.mkdir(parents=True)
    body = {"message": {"content": "A brief thought is enough."}, "done": True,
            "choices": [{"message": {"content": "A brief thought is enough."}, "finish_reason": "stop"}]}
    reply = Mock(status_code=200, text=json.dumps(body)); reply.json.return_value = body
    with patch.object(aa, "WORKSPACE_DIR", tmp_path), patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "FALLBACK_MODEL", "fixture-fallback"), patch.object(aa.requests, "post", return_value=reply) as post, patch.object(aa, "_append_llm_timing"), patch.object(aa.generation_record, "stash_attempt"):
        for preference, tokens in [("extended",8192),("short",512)]:
            pref.write_text(json.dumps(preference))
            for lane in ["source_study", "private_journal", "private_writing", "moment_capture", "autonomous_next"]:
                for backend in ["mlx","ollama","ollama_fast"]:
                    if backend == "mlx": agent._query_mlx("A writing prompt", "You may write at any length.", 768, journal=True)
                    elif backend == "ollama": agent._query_ollama("A writing prompt", "system", 768, prompt_class=lane, journal=True)
                    else: agent._query_ollama_fast_fallback("A writing prompt", "system", 768, prompt_class=lane, journal=True)
                    payload=post.call_args.kwargs["json"]
                    assert payload.get("max_tokens",payload.get("options",{}).get("num_predict")) == tokens
                    if preference == "extended":
                        assert post.call_args.kwargs["timeout"] >= 1200
                        if backend != "mlx": assert payload["options"]["num_ctx"] >= 65536
            if preference == "extended":
                assert aa._journal_job_timeout_s("self_study") >= 1200 * len(aa._llm_backend_attempts(aa.LLM_BACKEND,aa.MODEL,aa.FALLBACK_MODEL))
        assert aa._journal_generation_budget(128,768,60,8192,journal=False)==(128,60,8192)
        pref.write_text('"default"')
        assert writing.selected_profile(tmp_path)=="default"


def test_private_draft_is_intact_at_wire_and_survives_reconstructed_client(tmp_path):
    root=tmp_path/"minime"; root.mkdir(); astrid=tmp_path/"astrid"; astrid.mkdir()
    workspace=tmp_path/"workspace"
    client=StudyClient(root,workspace,astrid_root=astrid,executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    prompt=client.prepare("WRITE START where did my inference change?")
    text="Opening.\n" + "A developing account. "*1000 + "\nCONCLUSION_AT_END\nNEXT: WRITE CONTINUE"
    reply=Mock(status_code=200,text=json.dumps({"message":{"content":text},"done":True}))
    messages,_=prompt.messages(prompt.output["system_prompt"],prompt.input_budget_bytes)
    prompt.post(Mock(return_value=reply),"fixture",{"messages":messages},1); prompt.accepted()
    client=StudyClient(root,workspace,astrid_root=astrid,executable=client.executable)
    next_prompt=client.prepare("WRITE CONTINUE")
    assert "CONCLUSION_AT_END" in next_prompt
    assert ("A developing account. "*1000) in next_prompt
    assert next_prompt.output["input_kind"]=="private_writing"
    assert next_prompt.output["context_tokens"]==65536
    assert not (workspace/"journal").exists()


def test_private_writing_saves_outside_peer_journal_scan_and_skips_compression(tmp_path):
    agent=object.__new__(aa.AutonomousAgent)
    agent._state_for_live_surfaces=lambda state,**kw: state
    agent._write_journal_entry=Mock();agent._record_current_action_artifact=Mock();agent._record_introspect_notice=Mock()
    prompt=SourceStudyPrompt(Mock(),{"text":"draft", "system_prompt":"freeform", "input_kind":"private_writing", "evidence_scope":"Authored draft", "page":None})
    prompt.receipt={"verified":True}
    agent._query_llm_with_next=Mock(return_value=("Complete private passage.\nNEXT: WRITE CONTINUE", "WRITE CONTINUE"))
    with patch.object(aa,"WORKSPACE_DIR",tmp_path),patch.object(aa,"StudyClient") as client:
        client.return_value.prepare.return_value=prompt
        agent._run_shared_source_study({"fill_ratio":.68},"WRITE CONTINUE")
    assert not (tmp_path/"journal").exists()
    assert "Complete private passage." in next((tmp_path/"private_writing/journal").glob("*.txt")).read_text()
    assert agent._write_journal_entry.call_args.kwargs["private_canvas"] is True
    assert agent._record_current_action_artifact.call_args.kwargs["visibility"]=="protected"
    agent._record_introspect_notice.assert_not_called()
