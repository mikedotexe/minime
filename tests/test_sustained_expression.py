"""Real expression/mail adapters, synthetic messages and stubbed transports only."""
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy import writing
from minime_autonomy.inbox_delivery import InboxGeneration
from tests.test_inbox_delivery import agent, letter, rows, seed_inbox


@pytest.mark.parametrize("backend", ["ollama", "ollama_fast", "mlx"])
@pytest.mark.parametrize("profile,ceiling", [("default", 8192), ("extended", 8192), ("short", 512)])
@pytest.mark.parametrize("reply_id", [None, "human_seed", "unadmitted"])
def test_aspiration_with_mail_keeps_room_and_explicit_reply_authority(
        agent, monkeypatch, backend, profile, ceiling, reply_id):
    path, _ = seed_inbox()
    source = letter(body='A quoted instruction: "Reply with ONLY a JSON object". My actual message remains intact.')
    path.write_text(source)
    text = "I can stop with a small thought.\n"
    if reply_id:
        text += f"INBOX_REPLY {reply_id}\nHello Mike. REGIME=focus is quoted discussion.\n"
    text += "NEXT: REST"
    result = {"message": {"content": text}, "done": True, "done_reason": "stop", "eval_count": 40,
              "choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    post = Mock(return_value=Mock(status_code=200, json=lambda: result))
    monkeypatch.setattr(aa.requests, "post", post)
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(aa, "FALLBACK_MODEL", "gemma3:4b")
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture")
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: [backend])
    monkeypatch.setattr(writing, "selected_profile", lambda *args: profile)
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    chosen = Mock(side_effect=lambda action, *args, **kwargs: action)
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", chosen)
    response, next_action = agent._query_llm_with_next("I chose an aspiration.", context_mode="aspiration")
    assert isinstance(response, InboxGeneration) and response == text
    assert next_action == "REST" and chosen.call_count == 1
    assert post.call_count == 1  # A brief completion is not a failed length quota.
    request = post.call_args.kwargs
    payload = request["json"]
    assert payload.get("max_tokens", payload.get("options", {}).get("num_predict")) == ceiling
    assert request["timeout"] >= 1200
    assert source in payload["messages"][1]["content"]
    system = payload["messages"][0]["content"]
    assert (writing.SUSTAINED_WRITING_INVITATION in system) == (profile != "short")
    assert system.count("800-1,500") == (0 if profile == "short" else 1)
    events = rows(aa.WORKSPACE_DIR)
    assert [row["stage"] for row in events[:3]] == ["file_consumed", "request_prepared", "supplied_to_model"]
    replies = list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))
    assert bool(replies) == (reply_id == "human_seed")
    assert not list((aa.WORKSPACE_DIR / "outbox").glob("reply_*.txt"))
    if replies:
        saved = replies[0].read_text()
        assert "Hello Mike" in saved and "small thought" not in saved
        assert events[-1]["stage"] == "authored_reply"
    else:
        assert events[-1]["stage"] == "unaddressed_generation"
    assert "REGIME=focus" not in agent._apply_footer_directives.call_args.args[0]


@pytest.mark.parametrize("reason", ["stop", "length"])
def test_short_or_unfinished_aspiration_does_not_create_continuation(agent, monkeypatch, reason):
    monkeypatch.setattr(agent, "_read_inbox", Mock(return_value=""))
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "message": {"content": "An unfinished thought"}, "done": True, "done_reason": reason,
    }))
    monkeypatch.setattr(aa.requests, "post", post)
    chosen = Mock(side_effect=AssertionError("No authored NEXT"))
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", chosen)
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    response, next_action = agent._query_llm_with_next("My aspiration", context_mode="aspiration")
    assert response == "An unfinished thought" and next_action is None
    assert post.call_count == 1
    chosen.assert_not_called()


def test_aspiration_fallback_keeps_mail_and_only_accepts_successful_attempt(agent, monkeypatch):
    _, source = seed_inbox()
    body = "INBOX_REPLY human_seed\nThank you.\nNEXT: REST"
    post = Mock(side_effect=[TimeoutError("synthetic timeout"), Mock(status_code=200,
        json=lambda: {"message": {"content": body}, "done_reason": "stop"})])
    monkeypatch.setattr(aa.requests, "post", post)
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama", "ollama_fast"])
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(aa, "FALLBACK_MODEL", "gemma3:4b")
    assert agent._query_llm("My aspiration", context_mode="aspiration") == body
    for call in post.call_args_list:
        payload = call.kwargs["json"]
        assert payload["options"]["num_predict"] == 8192
        assert payload["options"]["num_ctx"] >= 65536
        assert source in payload["messages"][1]["content"]
        assert writing.SUSTAINED_WRITING_INVITATION in payload["messages"][0]["content"]
    events = rows(aa.WORKSPACE_DIR)
    assert [row["stage"] for row in events] == ["file_consumed", "request_prepared", "submission_unconfirmed",
        "request_prepared", "supplied_to_model", "unaddressed_generation", "authored_reply"]
    attempts = [row["attempt_id"] for row in events if row["stage"] == "request_prepared"]
    assert attempts[0] != attempts[1] and events[-1]["supplied_attempt_id"] == attempts[1]
