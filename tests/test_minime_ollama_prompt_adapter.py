"""Tests for Minime's Ollama prompt adapter."""

from __future__ import annotations

import os

import autonomous_agent as aa


def test_gemma4_adapter_uses_native_think_false_without_no_think():
    messages, adapter = aa._adapt_ollama_messages_for_model(
        model="gemma4:12b",
        system_msg="system",
        prompt="Write a short entry.",
        num_ctx=8192,
        num_predict=768,
    )

    assert adapter["prompt_template_mode"] == "gemma4_think_false_native"
    assert adapter["user_prefix"] == ""
    assert not messages[1]["content"].startswith("/no_think")


def test_gemma4_adapter_compacts_oversized_prompt():
    long_system = "System contract.\n" + ("Allowed NEXT: REST.\n" * 1200)
    long_prompt = "Current state.\n" + ("Telemetry and journal context.\n" * 1200)

    messages, adapter = aa._adapt_ollama_messages_for_model(
        model="gemma4:12b",
        system_msg=long_system,
        prompt=long_prompt,
        num_ctx=8192,
        num_predict=768,
    )

    assert adapter["prompt_compacted"]
    assert adapter["prompt_compaction"]["adapted_total_chars"] < len(long_system) + len(long_prompt)
    assert adapter["prompt_compaction"]["adapted_total_chars"] <= 16_000
    assert "Gemma 4 Ollama canary context budget" in messages[0]["content"]
    assert "Gemma 4 Ollama canary context budget" in messages[1]["content"]


def test_legacy_adapter_keeps_no_think_prefix():
    messages, adapter = aa._adapt_ollama_messages_for_model(
        model="gemma3:12b",
        system_msg="system",
        prompt="Write a short entry.",
        num_ctx=12288,
        num_predict=1024,
    )

    assert adapter["prompt_template_mode"] == "legacy_no_think_user_prefix"
    assert adapter["user_prefix"] == "/no_think"
    assert messages[1]["content"].startswith("/no_think\n")


def test_ollama_primary_failover_skips_mlx_middle_lane():
    assert aa._llm_backend_attempts("ollama", "gemma4:12b", "gemma3:4b") == [
        "ollama",
        "ollama_fast",
    ]


def test_mlx_primary_can_fail_over_to_ollama_then_fast_lane():
    assert aa._llm_backend_attempts("mlx", "gemma4:12b", "gemma3:4b") == [
        "mlx",
        "ollama",
        "ollama_fast",
    ]


def test_qualia_lanes_get_higher_ollama_cap_and_timeout():
    # Private-qualia lanes (minime's felt voice) get more token room AND
    # proportionally more wall-clock, so her qualia isn't truncated.
    for prompt_class in ("moment_capture", "private_journal"):
        assert aa._ollama_lane_limits(prompt_class) == (
            aa.LLM_QUALIA_TIMEOUT_S,
            aa.OLLAMA_QUALIA_NUM_PREDICT_CAP,
        )
    assert aa.OLLAMA_QUALIA_NUM_PREDICT_CAP > aa.OLLAMA_NUM_PREDICT_CAP
    assert aa.LLM_QUALIA_TIMEOUT_S > aa.LLM_TIMEOUT_S
    assert aa.OLLAMA_QUALIA_NUM_PREDICT_CAP == 2048
    assert aa.LLM_QUALIA_TIMEOUT_S == 160
    # The qualia pair preserves the proven 768/60s tokens-per-second budget ratio,
    # so Gemma-4 timeout exposure is unchanged despite the larger cap.
    assert abs(
        aa.OLLAMA_QUALIA_NUM_PREDICT_CAP / aa.LLM_QUALIA_TIMEOUT_S
        - aa.OLLAMA_NUM_PREDICT_CAP / aa.LLM_TIMEOUT_S
    ) < 0.5


def test_non_qualia_lanes_keep_global_ollama_cap_and_timeout():
    # inbox_reply and strict_review have their own dedicated lanes (see below);
    # everything else keeps the global cap/timeout.
    for prompt_class in ("autonomous_next", "sovereignty_check", "compact"):
        assert aa._ollama_lane_limits(prompt_class) == (
            aa.LLM_TIMEOUT_S,
            aa.OLLAMA_NUM_PREDICT_CAP,
        )


def test_inbox_reply_lane_gets_extended_timeout_and_cap():
    # Her replies to inbox/steward messages must have room to complete; on the global
    # 60s lane they timed out and were silently dropped.
    assert aa._ollama_lane_limits("inbox_reply") == (
        float(os.environ.get("MINIME_INBOX_REPLY_TIMEOUT_S", "160")),
        int(os.environ.get("MINIME_INBOX_REPLY_NUM_PREDICT_CAP", "1536")),
    )


def test_strict_review_lane_gets_extended_timeout_global_cap():
    # INTROSPECT / self-study lane (minime's highest-signal feedback surface). The
    # sectioned review takes 50-78s on the gemma4 primary; at the 60s global timeout
    # ~half timed out and fell to a 3-char gemma3:4b stub, collapsing her self-study
    # to a "thin output notice". It gets the same 160s headroom as the other
    # voice-bearing lanes, keeping the global token cap (the review fits in 768), so
    # timeout exposure is strictly reduced, not traded for extra token budget.
    assert aa._ollama_lane_limits("strict_review") == (
        aa.LLM_STRICT_REVIEW_TIMEOUT_S,
        aa.OLLAMA_NUM_PREDICT_CAP,
    )
    assert aa.LLM_STRICT_REVIEW_TIMEOUT_S > aa.LLM_TIMEOUT_S
