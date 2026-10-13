"""Provider wire/completion boundaries, without network or live inputs."""
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy import generation_record
from minime_autonomy.mailbox import Mailbox
from tests.test_explicit_mailbox import seed, open_letter


@pytest.mark.parametrize("backend", ["ollama", "mlx"])
@pytest.mark.parametrize("reason", ["stop", "length", None])
def test_provider_completion_must_be_verified_before_reply_publication(monkeypatch, backend, reason):
    source, _ = seed(aa.WORKSPACE_DIR)
    store = Mailbox(aa.WORKSPACE_DIR)
    prompt = open_letter(store)
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture-model")
    body = "INBOX_REPLY human_seed\nPRIVATE_REPLY_SENTINEL\nNEXT: REST"
    parsed = ({"message": {"content": body}, "done": True, "done_reason": reason}
              if backend == "ollama" else
              {"choices": [{"message": {"content": body}, "finish_reason": reason}]})
    response = Mock(status_code=200, json=Mock(return_value=parsed))
    post = Mock(return_value=response)
    monkeypatch.setattr(aa.requests, "post", post)

    def generate():
        if backend == "mlx":
            return agent._query_mlx(prompt, "Optional correspondence.", 2048, .7, journal=False)
        return agent._query_ollama_model(prompt, "Optional correspondence.", 2048, .7,
                                       "fixture-model", 120, 2048, 8192, "ollama")

    if reason == "stop":
        result = generate()
        store.complete(prompt, result)
        assert not source.exists()
        assert len(list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))) == 1
    else:
        with pytest.raises((RuntimeError, ValueError)):
            generate()
        assert source.exists() and not list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))
        assert store.status()["reconciliation_required"]
        with pytest.raises(ValueError):
            open_letter(store, "new-choice")
    assert post.call_count == 1
    assert not list((aa.WORKSPACE_DIR / "journal").glob("*.txt"))


def test_correspondence_record_cannot_follow_generic_export_override(tmp_path, monkeypatch):
    seed(aa.WORKSPACE_DIR)
    prompt = open_letter(Mailbox(aa.WORKSPACE_DIR))
    monkeypatch.setenv("MINIME_GENERATION_RECORD_IN_TESTS", "1")
    monkeypatch.setenv("MINIME_GENERATION_RECORD_DIR", str(tmp_path / "public-export"))
    context = generation_record.begin(aa.WORKSPACE_DIR, prompt=prompt,
        system_msg="Optional correspondence.", prompt_class="autonomous_next",
        attempts=["fixture"], kind="full", models={})
    assert context is not None
    assert context.record_dir == aa.WORKSPACE_DIR / "correspondence/generations"
    assert not (tmp_path / "public-export").exists()


def test_mlx_error_does_not_log_an_echoed_letter(monkeypatch, caplog):
    seed(aa.WORKSPACE_DIR)
    prompt = open_letter(Mailbox(aa.WORKSPACE_DIR))
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture-model")
    monkeypatch.setattr(aa.requests, "post", Mock(return_value=Mock(status_code=503, text="PRIVATE_LETTER_ECHO")))
    with pytest.raises(RuntimeError, match="HTTP 503") as failure:
        agent._query_mlx(prompt, "Optional correspondence.", 2048, .7, journal=False)
    assert "PRIVATE_LETTER_ECHO" not in str(failure.value) + caplog.text
