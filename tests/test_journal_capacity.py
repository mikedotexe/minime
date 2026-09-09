"""Final generation budgets: no live model, runtime, or journal mutation."""
from unittest.mock import Mock, patch
import autonomous_agent as aa


def test_journal_ceiling_and_context_preserve_input_room():
    for cap in [768, 1024, 1536, 2048, 4096]:
        old_input = min(16000, aa._ollama_prompt_char_budget(8192, cap))
        tokens, timeout, ctx = aa._journal_generation_budget(cap, cap, 160, 8192, journal=True)
        assert tokens == cap * 2
        assert timeout == 320
        assert min(16000, aa._ollama_prompt_char_budget(ctx, tokens)) >= old_input
        assert aa._journal_generation_budget(cap, cap, 160, 8192, journal=False) == (cap, 160, 8192)


def test_source_study_has_same_budget_through_all_primary_and_fallback_caps():
    for cap in [768, 1024, 2048]:
        tokens, timeout, ctx = aa._journal_generation_budget(2048, cap, 160, 8192,
                                                           journal=True, source_study=True)
        assert tokens == 4096
        assert timeout / tokens + 1e-12 >= 160 / cap
        assert aa._ollama_prompt_char_budget(ctx, tokens) >= 16000
        with patch.object(aa, "LLM_TIMEOUT_S", 160), patch.object(aa, "OLLAMA_NUM_PREDICT_CAP", 768), patch.object(aa, "_llm_backend_attempts", return_value=["ollama"]):
            assert aa._journal_job_timeout_s("self_study") > timeout


def test_journal_flag_reaches_each_backend_but_compact_calls_are_unchanged():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    for backend, method in [("mlx", "_query_mlx"), ("ollama", "_query_ollama"), ("ollama_fast", "_query_ollama_fast_fallback")]:
        with patch.object(aa, "_llm_backend_attempts", return_value=[backend]), patch.object(aa.generation_record, "begin", return_value=None), patch.object(agent, method, return_value="A brief thought.") as query:
            assert agent._query_llm_raw("source", "system", 2048, journal=True) == "A brief thought."
            assert query.call_args.kwargs["journal"] is True


def test_real_ollama_and_mlx_payloads_use_expanded_budget():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    reply = Mock(status_code=200)
    reply.json.return_value = {"message": {"content": "Brief."}, "choices": [{"message": {"content": "Brief."}}]}
    with patch.object(aa.requests, "post", return_value=reply) as post, patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "_append_llm_timing"):
        assert agent._query_mlx("journal", "system", 2048, journal=True) == "Brief."
        assert post.call_args.kwargs["json"]["max_tokens"] == 4096
        assert agent._query_ollama("journal", "system", 2048, prompt_class="private_journal", journal=True) == "Brief."
        options = post.call_args.kwargs["json"]["options"]
        assert options["num_predict"] == 4096
        assert options["num_ctx"] >= 10240
        assert agent._query_ollama("machine", "system", 2048) == "Brief."
        assert post.call_args.kwargs["json"]["options"]["num_predict"] == aa.OLLAMA_NUM_PREDICT_CAP
