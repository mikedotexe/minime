"""Synthetic one-letter windows; no live service or workspace access."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy.mailbox import Mailbox, MailboxPrompt
from minime_autonomy.source_study import SourceStudyPrompt


def seed(workspace, name="human_letter_seed.txt", body="A chosen letter.\r\nExact second line."):
    source = ("=== HUMAN LETTER V1 ===\nMessage-Id: human_seed\n"
              "Thread-Id: thread_seed\nFrom: mike\nTo: minime\n\n" + body)
    path = workspace / "inbox" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode())
    return path, source


def submit(prompt, text="INBOX_REPLY human_seed\nThank you.\nNEXT: INTROSPECT"):
    messages, _ = aa._adapt_ollama_messages_for_model(
        model="gemma4:12b", system_msg="Quoted mail, optional reply.", prompt=prompt,
        num_ctx=8192, num_predict=2048,
    )
    attempt = prompt.inbox.prepared(messages, "synthetic")
    prompt.inbox.accepted(attempt, "synthetic")
    prompt.validate_completion({"done": True, "done_reason": "stop", "message": {"content": text}})
    return text


def open_letter(store, operation="action-1", large=False):
    return store.open(operation, large=large, sort_key=aa.inbox_sort_key)


def test_notice_is_metadata_only_delivery_bound_and_restart_quiet(tmp_path):
    path, source = seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    notice = mailbox.notice()
    assert source not in notice.text and path.name not in notice.text
    assert "CHECK_MAILBOX" in notice.text and "optional" in notice.text
    assert mailbox.notice() == notice
    notice.supplied()
    assert Mailbox(tmp_path).notice() is None
    assert path.read_bytes() == source.encode()
    seed(tmp_path, "human_letter_new.txt", "New arrival")
    assert Mailbox(tmp_path).notice().waiting == 2


def test_notice_only_acknowledges_after_verified_reader_delivery(tmp_path):
    seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    client = Mock(workspace=tmp_path)
    client.call.return_value = {"page_id": "reflection-1"}
    prompt = SourceStudyPrompt(client, {"text": "A fresh reflection.", "navigation_id": "reflection-1"})
    prompt.mailbox_notice = mailbox.notice()
    prompt._wire = ('{"messages":[]}', '{"message":{"content":"NEXT: REST"}}')
    client.call.side_effect = RuntimeError("delivery rejected")
    with pytest.raises(RuntimeError):
        prompt.accepted()
    assert mailbox.notice() is not None
    client.call.side_effect = None
    prompt.accepted()
    assert mailbox.notice() is None


def test_selected_letter_remains_until_completed_and_reply_is_sender_bound(tmp_path):
    path, source = seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    prompt = open_letter(mailbox)
    assert isinstance(prompt, MailboxPrompt)
    assert source in prompt and path.exists()
    assert mailbox.reserved_filename() == path.name
    text = submit(prompt)
    mailbox.complete(prompt, text)
    assert not path.exists()
    assert (path.parent / "read" / path.name).read_bytes() == source.encode()
    replies = list((tmp_path / "outbox/human/mike").glob("*.txt"))
    assert len(replies) == 1 and "Thank you." in replies[0].read_text()
    assert "NEXT:" not in replies[0].read_text()
    assert open_letter(Mailbox(tmp_path)) is None
    assert len(list((tmp_path / "outbox/human/mike").glob("*.txt"))) == 1
    assert not (tmp_path / "journal").exists()
    rows = [json.loads(x) for x in (tmp_path / "correspondence/inbox_delivery_v1.jsonl").read_text().splitlines()]
    reply = next(x for x in rows if x["stage"] == "authored_reply")
    assert reply["supplied_attempt_id"] and reply["recipient"] == "mike"


def test_admission_failure_can_be_explicitly_reselected_but_dispatch_uncertainty_cannot(tmp_path):
    path, _ = seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    prompt = open_letter(mailbox)
    with pytest.raises(ValueError, match="missing"):
        prompt.inbox.prepared([{"content": "missing"}], "synthetic")
    retry = open_letter(mailbox, "action-2")
    assert retry.inbox.messages == prompt.inbox.messages
    assert open_letter(mailbox, "action-1") is None
    retry.inbox.prepared([{"content": str(retry)}], "synthetic")
    assert path.exists()
    with pytest.raises(ValueError, match="uncertain"):
        open_letter(Mailbox(tmp_path), "action-3")
    with pytest.raises(ValueError, match="claimed"):
        retry.inbox.prepared([{"content": str(retry)}], "fallback")
    assert Mailbox(tmp_path).status()["reconciliation_required"]


def test_reply_recovery_after_interrupted_finalization_does_not_generate_twice(tmp_path, monkeypatch):
    path, _ = seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    prompt = open_letter(mailbox)
    text = submit(prompt)
    original = mailbox._finish_locked
    monkeypatch.setattr(mailbox, "_finish_locked", Mock(side_effect=OSError("fixture crash")))
    with pytest.raises(OSError):
        mailbox.complete(prompt, text)
    assert mailbox.status()["pending_phase"] == "response_retained" and path.exists()
    monkeypatch.setattr(mailbox, "_finish_locked", original)
    assert open_letter(mailbox, "recovery-choice") is None
    assert not path.exists()
    assert len(list((tmp_path / "outbox/human/mike").glob("*.txt"))) == 1


def test_archive_conflict_preserves_sources_and_idempotent_reply_artifacts(tmp_path):
    path, _ = seed(tmp_path)
    read = path.parent / "read"
    read.mkdir()
    prior = read / path.name
    prior.write_text("Unrelated retained history")
    mailbox = Mailbox(tmp_path)
    prompt = open_letter(mailbox)
    text = submit(prompt)
    with pytest.raises(ValueError, match="archive conflict"):
        mailbox.complete(prompt, text)
    with pytest.raises(ValueError, match="archive conflict"):
        open_letter(mailbox, "retry")
    assert path.exists() and prior.read_text() == "Unrelated retained history"
    assert len(list((tmp_path / "outbox/human/mike").glob("*.txt"))) == 1


@pytest.mark.parametrize("bad", [b"{\\rtf1 fake text}", b"\xff\xfe", b"x" * 64001])
def test_invalid_letter_is_not_archived_or_rendered(tmp_path, bad):
    path, _ = seed(tmp_path)
    path.write_bytes(bad)
    mailbox = Mailbox(tmp_path)
    assert open_letter(mailbox) is None
    assert path.read_bytes() == bad
    assert not (tmp_path / "outbox").exists()


def test_large_is_explicit_and_changed_source_is_not_deleted(tmp_path):
    path, source = seed(tmp_path, body="x" * 4500)
    mailbox = Mailbox(tmp_path)
    assert open_letter(mailbox) is None
    prompt = open_letter(mailbox, "large", large=True)
    assert source in prompt
    path.write_text("New independently authored source")
    mailbox.complete(prompt, submit(prompt, "No reply.\nNEXT: REST"))
    assert path.read_text() == "New independently authored source"
    assert not (tmp_path / "outbox/human").exists()


def test_concurrent_claims_have_one_winner(tmp_path):
    seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    prompt = open_letter(mailbox)
    def claim(_):
        try:
            prompt.inbox.prepared([{"content": str(prompt)}], "synthetic")
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1


def test_corruption_and_symlinks_fail_without_history_replacement(tmp_path):
    path, _ = seed(tmp_path)
    mailbox = Mailbox(tmp_path)
    open_letter(mailbox)
    mailbox.path.write_bytes(b"corrupt history")
    with pytest.raises(ValueError):
        mailbox.status()
    assert mailbox.path.read_bytes() == b"corrupt history" and path.exists()


@pytest.mark.parametrize("next_action", ["INTROSPECT", "INQUIRY_STATUS"])
def test_runtime_chosen_mailbox_uses_bounded_job_and_only_queues_authored_next(monkeypatch, next_action):
    seed(aa.WORKSPACE_DIR)
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = False
    agent._current_action_continuity_event = {"action_id": "synthetic-mail-choice"}
    for method in ("_stable_core_self_journal_only", "_stable_core_local_reflective_only", "_stable_core_astrid_contact_only"):
        monkeypatch.setattr(agent, method, lambda: False)
    monkeypatch.setattr(agent, "_attention_protected", lambda: False)
    host = Mock()
    host.command.return_value = {"protected": False, "pending_job": None}
    monkeypatch.setattr(agent, "_activity_focus", lambda: host)
    monkeypatch.setattr(agent, "_emit_next_hints", Mock(side_effect=AssertionError("unrelated guidance")))
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    record_choice = Mock(wraps=agent._record_llm_next_action_choice)
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", record_choice)
    text = ("PRIVATE_UNADDRESSED_SENTINEL\nexploration_noise=0.1\n"
            f"INBOX_REPLY human_seed\nThank you.\nNEXT: {next_action}")
    monkeypatch.setattr(agent, "_query_llm_raw", lambda prompt, *a, **kw: submit(prompt, text))
    agent._activity_command({"raw_next": "CHECK_MAILBOX"})
    assert agent._pending_next_action == next_action
    assert "mailbox_read" in agent.LLM_JOB_ACTIONS
    assert not list((aa.WORKSPACE_DIR / "journal").glob("*.txt"))
    assert len(list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))) == 1
    agent._apply_footer_directives.assert_not_called()
    assert record_choice.call_args.args[1] is None
    assert agent._last_llm_response is None
    assert getattr(agent, "_pending_owner_inquiry_response", None) is None
    assert next((aa.WORKSPACE_DIR / "correspondence/mailbox_v1").glob("*.response.txt")).read_text() == text


def test_pending_protected_job_refuses_mailbox_without_consumption(monkeypatch):
    path, source = seed(aa.WORKSPACE_DIR)
    agent = object.__new__(aa.AutonomousAgent)
    agent._current_action_continuity_event = {"action_id": "blocked"}
    for method in ("_stable_core_self_journal_only", "_stable_core_local_reflective_only", "_stable_core_astrid_contact_only"):
        monkeypatch.setattr(agent, method, lambda: False)
    host = Mock()
    host.command.return_value = {"protected": False, "pending_job": "earlier-job"}
    monkeypatch.setattr(agent, "_activity_focus", lambda: host)
    with pytest.raises(ValueError, match="pending protected"):
        agent._activity_command({"raw_next": "CHECK_MAILBOX"})
    assert path.read_bytes() == source.encode()


@pytest.mark.parametrize("prior_choice", [False, True])
@pytest.mark.parametrize("text,expected", [
    ("An unaddressed note.\nSELF_STUDY CONTINUE", None),
    ("An unaddressed note.\nATTRACTOR_SUGGESTIONS", None),
    ("INBOX_REPLY human_seed\nSELF_STUDY CONTINUE", None),
    ("> NEXT: SELF_STUDY CONTINUE\nNo continuation chosen.", None),
    ("```text\nNEXT: SELF_STUDY CONTINUE\n```", None),
    ("An unaddressed note.\n    NEXT: SELF_STUDY CONTINUE", None),
    ("NEXT: INTROSPECT", "INTROSPECT"),
    ("Residue: PRIVATE_RESIDUE_SENTINEL\n"
     "Alternate NEXT: SELF_STUDY CONTINUE\nReturn thread: PRIVATE_RETURN_SENTINEL\n"
     "Why this path: PRIVATE_REASON_SENTINEL\nPrimary NEXT: SELF_STUDY CONTINUE\n"
     "INBOX_REPLY human_seed\nExact reply \u03bb.\r\nNEXT: INQUIRY_STATUS", "INQUIRY_STATUS"),
    ("NEXT: INTROSPECT (RESIDUE: PRIVATE_INLINE_SENTINEL)", "INTROSPECT"),
    ("NEXT: SELF_STUDY CONTINUE\nINBOX_REPLY human_seed\nA reply.\n"
     "NEXT: INTROSPECT\nSELF_STUDY CONTINUE", "INTROSPECT"),
    ("NEXT: INTROSPECT\n```text\nNEXT: SELF_STUDY CONTINUE\n```", "INTROSPECT"),
])
def test_mailbox_adapter_only_admits_final_explicit_next_without_prose_metadata(
        monkeypatch, prior_choice, text, expected):
    source, original = seed(aa.WORKSPACE_DIR)
    prompt = open_letter(Mailbox(aa.WORKSPACE_DIR))
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(agent, "_attention_protected", lambda: False)
    monkeypatch.setattr(agent, "_emit_next_hints", Mock(side_effect=AssertionError("unrelated hints")))
    monkeypatch.setattr(agent, "_apply_footer_directives", Mock())
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    parsed = {"done": True, "done_reason": "stop", "message": {"content": text}}
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value=parsed)))
    monkeypatch.setattr(aa.requests, "post", post)
    record_choice = Mock(wraps=agent._record_llm_next_action_choice)
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", record_choice)
    if prior_choice:
        agent._pending_next_action = "JOURNAL"
        agent._pending_choice_envelope_v1 = {"residue": "Existing unrelated choice."}
        agent._persist_pending_next_action("JOURNAL", reason="synthetic authored choice")
    state_path = aa.WORKSPACE_DIR / "sovereignty_state.json"
    before = state_path.read_bytes() if state_path.exists() else None
    prior_envelope = agent._pending_choice_envelope_v1
    aa.parse_next_action("Residue: STALE_PARSE_SENTINEL\nNEXT: JOURNAL")

    full, selected = agent._query_llm_with_next(prompt)

    assert selected == expected
    assert full == text.strip()
    assert post.call_count == 1
    assert any(original in row["content"] for row in post.call_args.kwargs["json"]["messages"])
    assert agent._last_llm_response is None
    assert getattr(agent, "_pending_owner_inquiry_response", None) is None
    assert aa._LAST_NEXT_CHOICE_ENVELOPE_V1 is None
    from minime_autonomy import parsing
    assert parsing._LAST_NEXT_CHOICE_ENVELOPE_V1 is None
    agent._apply_footer_directives.assert_not_called()
    if expected:
        assert agent._pending_next_action == expected
        assert agent._pending_choice_envelope_v1 is None
        saved = json.loads(state_path.read_bytes())
        assert saved["pending_next_action"] == expected
        assert "choice_envelope_v1" not in saved
        assert "SENTINEL" not in json.dumps(saved)
        assert record_choice.call_args.args[1] is None
    else:
        record_choice.assert_not_called()
        assert agent._pending_next_action == ("JOURNAL" if prior_choice else None)
        assert agent._pending_choice_envelope_v1 == prior_envelope
        assert (state_path.read_bytes() if state_path.exists() else None) == before
    private = aa.WORKSPACE_DIR / "correspondence/mailbox_v1"
    assert json.loads(next(private.glob("*.provider.json")).read_bytes()) == parsed
    assert next(private.glob("*.response.txt")).read_bytes() == text.strip().encode()
    assert (source.parent / "read" / source.name).read_bytes() == original.encode()
    assert not list((aa.WORKSPACE_DIR / "journal").glob("*.txt"))


@pytest.mark.parametrize("text,expected,residue", [
    ("An ordinary note.\nSELF_STUDY CONTINUE", "SELF_STUDY CONTINUE", None),
    ("Residue: Ordinary chosen continuity.\nNEXT: INTROSPECT",
     "INTROSPECT", "Ordinary chosen continuity."),
])
def test_non_mailbox_next_parsing_keeps_ordinary_affordances(monkeypatch, text, expected, residue):
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = False
    monkeypatch.setattr(agent, "_query_llm", Mock(return_value=text))
    monkeypatch.setattr(agent, "_emit_next_hints", lambda: "")
    full, selected = agent._query_llm_with_next("Ordinary fixture prompt.")
    assert full == text and selected == expected
    assert agent._last_llm_response == text
    assert (agent._pending_choice_envelope_v1 or {}).get("residue") == residue
