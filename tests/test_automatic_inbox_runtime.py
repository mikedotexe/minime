"""Automatic mail handoff through the real runtime and synthetic transports."""

import json
from unittest.mock import Mock

import pytest
import requests
import autonomous_agent as aa

from minime_autonomy.automatic_inbox import AutomaticInboxContext
from minime_autonomy.inbox_delivery import InboxPrompt
from minime_autonomy.mailbox import Mailbox
from tests.test_inbox_delivery import agent, letter, seed_inbox
from tests.test_mailbox_status import snapshot


def provider(monkeypatch, backend, body, reason="stop"):
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture-model")
    monkeypatch.setattr(aa, "MODEL", "fixture-model")
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *_: [backend])
    parsed = ({"message": {"content": body}, "done": True, "done_reason": reason}
              if backend == "ollama" else
              {"choices": [{"message": {"content": body}, "finish_reason": reason}]})
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value=parsed)))
    monkeypatch.setattr(aa.requests, "post", post)
    return post


@pytest.mark.parametrize("backend", ["mlx", "ollama"])
def test_normal_completion_retires_only_after_retained_sender_bound_response(agent, monkeypatch, backend):
    path, source = seed_inbox()
    body = "An independent thought.\nINBOX_REPLY human_seed\nA considered reply.\nNEXT: REST"
    post = provider(monkeypatch, backend, body)
    agent._pending_next_action = "WRITE CONTINUE d7"
    result = agent._query_llm("Continue the chosen activity.")
    assert str(result) == body
    assert "INBOX_REPLY" not in result.action_text
    assert post.call_count == 1
    assert not path.exists()
    assert (path.parent / "read" / path.name).read_text() == source
    assert len(list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))) == 1
    assert agent._pending_next_action == "WRITE CONTINUE d7"
    assert not Mailbox(aa.WORKSPACE_DIR).status()["reconciliation_required"]
    # Later intake does not regenerate or repeat addressed publication.
    assert agent._read_inbox() == ""
    assert post.call_count == 1


@pytest.mark.parametrize("backend", ["mlx", "ollama"])
@pytest.mark.parametrize("reason", ["length", None])
def test_incomplete_completion_keeps_output_and_source_without_addressed_publication(agent, monkeypatch, backend, reason):
    path, source = seed_inbox()
    body = "A partial thought.\nINBOX_REPLY human_seed\nAn unfinished reply."
    post = provider(monkeypatch, backend, body, reason)
    assert str(agent._query_llm("Continue the chosen activity.")) == body
    assert path.read_text() == source
    assert not list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))
    assert Mailbox(aa.WORKSPACE_DIR).status()["reconciliation_required"]
    assert agent._read_inbox() == ""
    assert post.call_count == 1
    retained = list((aa.WORKSPACE_DIR / "correspondence/mailbox_v1").glob("*.automatic-output.txt"))
    assert any(item.read_text() == body for item in retained)


def test_timeout_is_uncertain_not_archived_or_replayed_and_does_not_block_other_work(agent, monkeypatch):
    path, source = seed_inbox()
    post = provider(monkeypatch, "mlx", "unused")
    post.side_effect = requests.Timeout("synthetic timeout")
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *_: ["mlx", "ollama"])
    agent._pending_next_action = "REST"
    assert agent._query_llm("A chosen activity.") is None
    assert post.call_count == 1  # The fallback cannot repeat an uncertain letter.
    assert path.read_text() == source and agent._pending_next_action == "REST"
    assert agent._read_inbox() == ""
    status = Mailbox(aa.WORKSPACE_DIR).status()
    assert status["reconciliation_required"] and status["waiting_files"] == 1

    other = path.with_name("human_letter_another.txt")
    other.write_text(letter("human_other", body="A separate message."))
    independent = agent._read_inbox()
    assert isinstance(independent, AutomaticInboxContext)
    assert "A separate message." in independent and source not in independent
    assert not independent.dispatch_claimed
    generated = Mock(return_value="Unrelated writing.\nNEXT: REST")
    monkeypatch.setattr(agent, "_query_llm_raw", generated)
    assert agent._query_llm("An unrelated private journal.", context_mode="private_journal")
    assert not isinstance(generated.call_args.args[0], InboxPrompt)


def test_pre_dispatch_failure_reuses_exact_context_and_preserves_next(agent, monkeypatch):
    path, source = seed_inbox()
    captured = []
    def fail_before_submission(prompt, *_args, **_kwargs):
        captured.append(prompt.inbox)
        return None
    monkeypatch.setattr(agent, "_query_llm_raw", fail_before_submission)
    agent._pending_next_action = "REST"
    assert agent._query_llm("An ordinary activity.") is None
    original = captured[0]
    before = snapshot(aa.WORKSPACE_DIR)
    restored = agent._read_inbox()
    assert str(restored) == str(original) and restored.batch_id == original.batch_id
    assert restored.messages == original.messages
    assert snapshot(aa.WORKSPACE_DIR) == before
    assert path.read_text() == source and agent._pending_next_action == "REST"


def test_trimmed_input_never_claims_dispatch_and_can_fall_back_before_submission(agent, monkeypatch):
    path, _ = seed_inbox()
    inbox = agent._read_inbox()
    with pytest.raises(ValueError):
        inbox.prepared([{"content": "The letter is absent"}], "fixture")
    assert not inbox.dispatch_claimed and path.exists()
    assert not Mailbox(aa.WORKSPACE_DIR).status()["reconciliation_required"]


def test_mailbox_lock_contention_defers_without_consumption(agent):
    path, source = seed_inbox()
    with Mailbox(aa.WORKSPACE_DIR).locked():
        assert agent._read_inbox() == ""
    assert path.read_text() == source


def test_error_does_not_log_provider_echo_of_letter(agent, monkeypatch, caplog):
    path, _ = seed_inbox()
    post = provider(monkeypatch, "mlx", "unused")
    post.return_value = Mock(status_code=503, text="PRIVATE_LETTER_ECHO")
    assert agent._query_llm("An ordinary activity.") is None
    assert "PRIVATE_LETTER_ECHO" not in caplog.text
    assert path.exists() and post.call_count == 1
    assert "PRIVATE_LETTER_ECHO" not in json.dumps(Mailbox(aa.WORKSPACE_DIR).status())


def test_crlf_mail_keeps_sender_routing_and_exact_archived_bytes(agent, monkeypatch):
    path, source = seed_inbox()
    raw = (source.replace("\n", "\r\n") + "\r\n").encode()
    path.write_bytes(raw)
    inbox = agent._read_inbox()
    assert inbox.messages[0].sender == "mike" and inbox.messages[0].message_id == "human_seed"
    post = provider(monkeypatch, "mlx", "INBOX_REPLY human_seed\nA reply.\nNEXT: REST")
    agent._query_llm("The chosen activity.")
    assert post.call_count == 1
    assert (path.parent / "read" / path.name).read_bytes() == raw
    assert len(list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))) == 1
