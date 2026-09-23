"""Exercise real adapters with stub providers, without live inference or private prose."""
from unittest.mock import Mock, patch

import autonomous_agent as aa
from minime_autonomy import writing


def test_expressive_primary_and_fallback_payloads_and_selected_short(tmp_path):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    reply = Mock(status_code=200)
    reply.json.return_value = {
        "done": True, "done_reason": "length", "eval_count": 8192,
        "message": {"content": "An unfinished but retained thought."},
        "choices": [{"finish_reason": "length", "message": {"content": "An unfinished but retained thought."}}],
        "usage": {"completion_tokens": 8192},
    }
    with patch.object(aa, "WORKSPACE_DIR", tmp_path), patch.object(aa.requests, "post", return_value=reply) as post, patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "MODEL", "primary"), patch.object(aa, "FALLBACK_MODEL", "fallback"), patch.object(aa, "_append_llm_timing") as timing:
        for profile, expected in [("default", 8192), ("short", 512), ("extended", 8192)]:
            with patch.object(writing, "selected_profile", return_value=profile):
                for label in sorted(writing.EXPRESSIVE_CLASSES):
                    for method in [agent._query_mlx, agent._query_ollama, agent._query_ollama_fast_fallback]:
                        assert method("Synthetic prose", "Open writing.", 2048, prompt_class=label, journal=True) == "An unfinished but retained thought."
                        request = post.call_args.kwargs
                        payload = request["json"]
                        assert payload.get("max_tokens", payload.get("options", {}).get("num_predict")) == expected
                        assert request["timeout"] >= 1200
                        if "options" in payload:
                            assert payload["options"]["num_ctx"] >= 65536
                            assert timing.call_args.args[0]["native_finish"] == "length"
        assert aa._journal_job_timeout_s("self_study", private_writing=True) > 1200 * len(aa._llm_backend_attempts(aa.LLM_BACKEND, aa.MODEL, aa.FALLBACK_MODEL))


def test_default_invitation_is_optional_and_short_wins(tmp_path):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    with patch.object(aa, "WORKSPACE_DIR", tmp_path), patch.object(aa, "_llm_backend_attempts", return_value=["mlx"]), patch.object(aa.generation_record, "begin", return_value=None), patch.object(agent, "_query_mlx", return_value="Brief.") as query:
        for profile in ["default", "short"]:
            with patch.object(writing, "selected_profile", return_value=profile):
                assert agent._query_llm_raw("Synthetic", "Open writing.", 2048, prompt_class="aspiration", journal=True) == "Brief."
                system = query.call_args.args[1]
                assert query.call_args.kwargs["prompt_class"] == "aspiration"
                assert (writing.EXPRESSION_ROOM in system) == (profile == "default")
                assert "You selected extended" not in system
    assert aa._infer_llm_prompt_class("Short invitation", context_mode="aspiration") == "aspiration"
    assert aa._infer_llm_prompt_class("Mail", context_mode="aspiration", inbox_present=True) == "inbox_reply"


def test_completion_metadata_is_bounded_and_unknown_is_not_a_natural_stop():
    assert writing.completion_metadata({})["native_finish"] is None
    assert writing.completion_metadata({"done_reason": "stop"})["native_finish"] == "stop"
    result = writing.completion_metadata({"done_reason": "private prose", "message": {"content": "private prose"}, "eval_count": -1})
    assert result["native_finish"] == "other_reported"
    assert result["provider_eval_count"] is None
    assert "private prose" not in str(result)
    assert writing.completion_metadata({"choices": [], "usage": None})["native_finish"] is None
