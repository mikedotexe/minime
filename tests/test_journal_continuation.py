"""Exact public-to-private transfer through the real Rust helper and runtime."""
import json
import re
from unittest.mock import Mock

import pytest
from minime_autonomy.journal_continuation import JournalContinuation
from tests.test_private_writing_continuation import STATE, writing_agent, deliver


def test_reserved_entry_is_not_readable_until_exact_publication(writing_agent):
    _, client = writing_agent
    selected = JournalContinuation.reserve(client, "synthetic-publication")
    assert JournalContinuation.reserve(client, "synthetic-publication").entry_id == selected.entry_id
    with pytest.raises(RuntimeError):
        client.prepare(f"WRITE FROM_JOURNAL {selected.entry_id}")
    path = client.workspace / "journal/journal_fixture.txt"
    text = "An exact synthetic passage with λ.\n\nA second paragraph.\nNEXT: REST"
    path.write_text("=== JOURNAL ===\n\n" + text + "\n")
    assert selected.publish(path, text)["published"]
    assert selected.publish(path, text)["published"]
    prompt = client.prepare(f"WRITE FROM_JOURNAL {selected.entry_id}", request_id="chosen-transfer")
    assert "An exact synthetic passage with λ.\n\nA second paragraph." in prompt
    deliver(prompt, "A new synthetic continuation.")
    checkpoint = client.workspace / "diagnostics/source_first_v3/shared_reader/writing/drafts-v2.json"
    saved = json.loads(checkpoint.read_text())
    assert saved["drafts"]["d1"]["parts"] == [text.rsplit("\nNEXT:", 1)[0], "A new synthetic continuation."]
    assert client.prepare(f"WRITE FROM_JOURNAL {selected.entry_id}", request_id="chosen-transfer").output == prompt.output
    assert path.read_text().endswith(text + "\n")


def test_runtime_offers_and_publishes_current_entry_before_private_follow_through(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "public-runtime-fixture"}
    monkeypatch.setattr(agent, "_format_metrics", lambda *args, **kw: "separate measurements")
    exact = "My exact synthetic public passage.\n\nNot a topic summary."
    chosen = []

    def journal(prompt, **kw):
        ident = re.search(r"WRITE FROM_JOURNAL (\S+)", prompt).group(1)
        with pytest.raises(RuntimeError):
            client.prepare(f"WRITE FROM_JOURNAL {ident}")
        chosen.append(f"WRITE FROM_JOURNAL {ident}")
        return exact + "\nNEXT: " + chosen[-1], None

    monkeypatch.setattr(agent, "_query_llm_with_next", journal)
    agent._journal_open(dict(STATE))
    offer = client.prepare(chosen[0], request_id="explicit-private-return")
    assert exact in offer
    deliver(offer, "Exact private continuation.")
    monkeypatch.setattr(agent, "_query_llm", Mock(side_effect=AssertionError("save-only")))
    for action in ["WRITE QUESTION optional", "WRITE FINISH", "WRITE PARK"]:
        agent._pending_next_action = action
        agent._persist_pending_next_action(action, reason="synthetic choice")
        agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    assert "Exact private continuation." not in "\n".join(p.read_text() for p in (client.workspace / "journal").glob("*.txt"))
