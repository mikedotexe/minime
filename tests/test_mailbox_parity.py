"""First-tranche guidance and unchanged ordinary/explicit receive policies."""

import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import autonomous_agent as aa

from minime_autonomy.expressive_journal import COMPACT_ACTION_GUIDANCE
from minime_autonomy.mailbox import Mailbox
from tests.test_inbox_delivery import agent, rows, seed_inbox
from tests.test_mailbox_status import snapshot


@pytest.mark.parametrize("mode,automatic", [
    ("default", True), ("aspiration", True), ("private_journal", False),
    ("qualia_moment", False), ("daydream", False), ("strict_review", False),
])
def test_ordinary_automatic_policy_and_private_parking_remain_unchanged(agent, monkeypatch, mode, automatic):
    path, source = seed_inbox()
    response = "An unrelated private generation.\nNEXT: REST"
    query = Mock(return_value=None if automatic else response)
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    agent._query_llm("Synthetic chosen activity.", context_mode=mode)
    prompt = query.call_args.args[0]
    assert isinstance(prompt, aa.InboxPrompt) == automatic
    assert (source in prompt) == automatic
    assert path.exists()  # A stub result cannot retire a letter before verified delivery.
    result = Mailbox(aa.WORKSPACE_DIR).status()
    history = result["delivery_history"]
    assert history["file_consumption_events"] == 0
    assert history["accepted_input_submissions"] == 0  # A stub result is not accepted input.
    assert history["retained_generations_with_verified_input"] == 0
    assert history["addressed_reply_publications"] == 0
    assert result["delivery_history"]["provider_stop"] == "unknown"


def test_legacy_accepted_input_retained_output_and_reply_are_separate(agent, monkeypatch, caplog):
    path, _ = seed_inbox()
    private_path = path.with_name("human_letter_PRIVATE_TITLE_SENTINEL.txt")
    path.rename(private_path)
    path = private_path
    source = path.read_text().replace("How are you?", "PRIVATE_BODY_SENTINEL")
    path.write_text(source)
    caplog.set_level(logging.INFO)
    inbox = agent._read_inbox()
    store = Mailbox(aa.WORKSPACE_DIR)
    consumed = store.status()["delivery_history"]
    assert consumed["file_consumption_events"] == 0
    assert consumed["accepted_input_submissions"] == 0
    assert consumed["retained_generations"] == 0
    attempt = inbox.prepared([{"content": str(inbox)}], "synthetic")
    inbox.accepted(attempt, "synthetic")
    supplied = store.status()["delivery_history"]
    assert supplied["accepted_input_submissions"] == 1
    assert supplied["retained_generations"] == 0
    agent._save_outbox_reply("PRIVATE_UNADDRESSED_SENTINEL", inbox_context=inbox)
    retained = store.status()["delivery_history"]
    assert retained["retained_generations_with_verified_input"] == 1
    assert retained["addressed_reply_publications"] == 0
    agent._save_outbox_reply("INBOX_REPLY human_seed\nPRIVATE_REPLY_SENTINEL", inbox_context=inbox)
    result = store.status()
    assert result["delivery_history"]["addressed_reply_publications"] == 1
    assert result["delivery_history"]["provider_stop"] == "unknown"
    assert "SENTINEL" not in json.dumps(result) + caplog.text


def test_pre_dispatch_failure_preserves_source_and_exact_pending_context(agent, monkeypatch):
    path, source = seed_inbox()
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value=None))
    assert agent._query_llm("A normal synthetic turn") is None
    assert path.read_text() == source
    assert not (path.parent / "read" / path.name).exists()
    before = snapshot(aa.WORKSPACE_DIR)
    result = Mailbox(aa.WORKSPACE_DIR).status()
    assert result["waiting_files"] == 1
    assert result["delivery_history"]["file_consumption_events"] == 0
    assert result["delivery_history"]["accepted_input_submissions"] == 0
    assert result["delivery_history"]["provider_stop"] == "unknown"
    assert snapshot(aa.WORKSPACE_DIR) == before
    assert rows(aa.WORKSPACE_DIR)[-1]["stage"] == "generation_failed"
    restored = agent._read_inbox()
    assert source in restored and not restored.dispatch_claimed


@pytest.mark.parametrize("phase", ["selected", "started", "supplied"])
def test_legacy_read_skips_exact_explicit_reservation(agent, phase):
    path, source = seed_inbox()
    store = Mailbox(aa.WORKSPACE_DIR)
    prompt = store.open("exact-operation", sort_key=aa.inbox_sort_key)
    message = prompt.inbox.messages[0]
    if phase in {"started", "supplied"}:
        attempt = prompt.inbox.prepared([{"content": str(prompt)}], "synthetic")
        if phase == "supplied":
            prompt.inbox.accepted(attempt, "synthetic")
    before = snapshot(aa.WORKSPACE_DIR)
    assert agent._read_inbox() == ""
    result = store.status()
    assert result["pending_phase"] == phase
    assert snapshot(aa.WORKSPACE_DIR) == before
    assert path.read_text() == source and prompt.inbox.messages[0] == message


@pytest.mark.parametrize("protected", ["protected", "pending_job", "unavailable"])
def test_protected_work_parks_receive_and_generation_but_allows_status(agent, monkeypatch, protected):
    path, source = seed_inbox()
    store = Mailbox(aa.WORKSPACE_DIR)
    store.open("parked-operation", sort_key=aa.inbox_sort_key)
    monkeypatch.setattr(agent, "_activity_checkpoint_exists", lambda: True)
    host = Mock()
    if protected == "unavailable":
        host.status.side_effect = RuntimeError("synthetic metadata unavailable")
    else:
        host.status.return_value = {"protected": protected == "protected",
                                    "pending_job": "exact-job" if protected == "pending_job" else None}
    monkeypatch.setattr(agent, "_activity_focus", lambda: host)
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(side_effect=AssertionError("no generation")))
    before = snapshot(aa.WORKSPACE_DIR)
    assert agent._read_inbox() == ""
    assert agent._query_llm("Ordinary activity") is None
    agent._current_action_continuity_event = {"action_id": "status-only"}
    agent._pending_next_action = "WRITE CONTINUE exact-work"
    agent._activity_command({"raw_next": "MAILBOX_STATUS"})
    assert agent._pending_next_action == "WRITE CONTINUE exact-work"
    host.command.assert_not_called()
    assert json.loads(agent._pending_mailbox_feedback)["pending_phase"] == "selected"
    assert path.read_text() == source and snapshot(aa.WORKSPACE_DIR) == before


@pytest.mark.parametrize("gate", ["_stable_core_self_journal_only", "_stable_core_local_reflective_only"])
def test_reflective_gates_still_park_ordinary_mail(agent, monkeypatch, gate):
    path, source = seed_inbox()
    monkeypatch.setattr(agent, gate, lambda: True)
    assert agent._read_inbox() == ""
    assert path.read_text() == source
    assert not (path.parent / "read" / path.name).exists()


def test_status_never_invokes_generation_receiving_or_focus_transition(agent, monkeypatch):
    seed_inbox()
    for name in ("_query_llm", "_query_llm_raw", "_query_llm_with_next", "_read_inbox", "_activity_focus"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError(name)))
    agent._current_action_continuity_event = {"action_id": "status-only"}
    agent._activity_command({"raw_next": "MAILBOX_STATUS"})
    result = json.loads(agent._current_action_outcome_summary)
    assert result["waiting_files"] == 1
    assert result["pending_phase"] is None
    assert result["delivery_history"]["accepted_input_submissions"] == 0


def test_compact_guidance_neutrally_lists_search_and_mailbox_options():
    for action in ("SEARCH <topic>", "BROWSE <url>", "CHECK_MAILBOX", "MAILBOX_STATUS", "REST"):
        assert action in COMPACT_ACTION_GUIDANCE
    assert "these are examples" in COMPACT_ACTION_GUIDANCE
    assert "grants no additional authority" in COMPACT_ACTION_GUIDANCE
    assert "DuckDuckGo" not in COMPACT_ACTION_GUIDANCE


def test_runtime_search_guidance_matches_configured_policy_without_authorizing_it():
    source = (Path(__file__).resolve().parents[1] / "minime_autonomy/runtime.py").read_text()
    assert "DuckDuckGo" not in source
    assert source.count("ordinary public search through the configured web-search provider") == 2
    assert source.count("installed standing policy, subject to current authorization, transport, credential and cost checks") == 2
    assert "When you do a self-study or daydream and something intrigues you, search for it" not in source


@pytest.mark.parametrize("command,expected", [("MAILBOX_STATUS", 1), ("MAILBOX_STATUS 1", 1),
                                            ("MAILBOX_STATUS 2", 2), ("MAILBOX_STATUS 999", 999),
                                            (" MAILBOX_STATUS \t\n", 1), ("MAILBOX_STATUS 01", 1),
                                            ("MAILBOX_STATUS  2", 2), ("MAILBOX_STATUS 2\n", 2),
                                            ("\tMAILBOX_STATUS \t0002 \r\n", 2)])
def test_paged_runtime_status_is_metadata_only(agent, monkeypatch, command, expected):
    path, _ = seed_inbox()
    for index in range(10):
        (path.parent / f"ordinary_{index:02}.txt").write_text("Private letter")
    for name in ("_query_llm_raw", "_read_inbox", "_activity_focus"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError(name)))
    agent._current_action_continuity_event = {"action_id": "paged-status"}
    agent._activity_command({"raw_next": command})
    result = json.loads(agent._current_action_outcome_summary)
    assert result["page"] == expected and result["waiting_files"] == 11
    assert len(result["queued_files"]) == (8 if expected == 1 else 3 if expected == 2 else 0)
    assert path.exists()


@pytest.mark.parametrize("command", ["MAILBOX_STATUS 0", "MAILBOX_STATUS -1", "MAILBOX_STATUS +1",
                                    "MAILBOX_STATUS 000", "MAILBOX_STATUS 1.0", "MAILBOX_STATUS all",
                                    "MAILBOX_STATUS 1 2", "MAILBOX_STATUS 0 1",
                                    "MAILBOX_STATUS \u0661", "MAILBOX_STATUS 18446744073709551616"])
def test_runtime_rejects_bad_pages_without_falling_through_to_shared_commands(agent, monkeypatch, command):
    seed_inbox()
    for name in ("_query_llm_raw", "_read_inbox", "_activity_focus"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError(name)))
    agent._current_action_continuity_event = {"action_id": "invalid-page"}
    before = snapshot(aa.WORKSPACE_DIR)
    with pytest.raises(ValueError, match="positive one-based page"):
        agent._activity_command({"raw_next": command})
    assert snapshot(aa.WORKSPACE_DIR) == before
