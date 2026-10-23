"""Content-free mailbox evidence, entirely within synthetic directories."""

import json
import os
from unittest.mock import Mock

import pytest

from minime_autonomy import mailbox as mb
from minime_autonomy.inbox_delivery import append_event
from minime_autonomy.mailbox_fs import Directory
from tests.test_mailbox_filesystem import RESPONSE, accepted, seed, select, workspace


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_inventory_is_not_eligibility_or_delivery_and_does_not_open_letters(workspace, monkeypatch):
    source = seed(workspace, name="human_letter_PRIVATE_TITLE.txt")
    (source.parent / "too_large.txt").write_bytes(b"PRIVATE_BODY" * 6000)
    (source.parent / "receipt_admin.txt").write_text("Administrative receipt")
    (source.parent / "ping_admin.txt").write_text("Administrative ping")
    (source.parent / "alias.txt").symlink_to(source)
    store = mb.Mailbox(workspace)
    notice = store.notice()
    before = snapshot(workspace)
    read = Directory.read

    def metadata_only(directory, name, limit):
        assert not name.endswith(".txt"), "status must not inspect private bodies"
        return read(directory, name, limit)

    monkeypatch.setattr(Directory, "read", metadata_only)
    result = store.status()
    assert result["waiting_files"] == 2
    assert result["pending_phase"] is None and result["pending_delivery"] is None
    assert "last_completion" not in result
    assert result["delivery_history"]["state"] == "no_receipts"
    assert "eligibility not checked" in result["inventory_semantics"]
    assert "file consumption is not delivery" in result["semantics"]
    assert "not read/understood" in result["semantics"]
    assert "PRIVATE" not in json.dumps(result)
    assert store.notice() == notice  # Inspection does not acknowledge availability.
    assert snapshot(workspace) == before


@pytest.mark.parametrize("phase", ["selected", "started", "supplied", "response_retained", "completed"])
@pytest.mark.parametrize("reply", [False, True])
def test_status_distinguishes_reservation_delivery_completion_and_optional_reply(
        workspace, monkeypatch, phase, reply):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store, "PRIVATE_OPERATION")
    original_message = prompt.inbox.messages[0]
    text = RESPONSE if reply else "PRIVATE_UNADDRESSED_BODY\nNEXT: REST"
    if phase == "started":
        prompt.inbox.prepared([{"content": str(prompt)}], "synthetic")
    elif phase in {"supplied", "response_retained", "completed"}:
        accepted(prompt, validate=False)
    if phase in {"response_retained", "completed"}:
        prompt.validate_completion({"done": True, "done_reason": "stop",
                                    "message": {"content": text}})
        if phase == "response_retained":
            monkeypatch.setattr(store, "_finish_locked", Mock())
        store.complete(prompt, text)
    before = snapshot(workspace)
    result = mb.Mailbox(workspace).status()
    assert snapshot(workspace) == before
    assert "PRIVATE" not in json.dumps(result)
    assert source.name not in json.dumps(result)
    assert "last_completion" not in result
    assert "last_completion" not in json.loads(store.path.read_bytes())
    assert result["delivery_history"]["provider_stop"] == "unknown"
    if phase == "completed":
        assert result["pending_phase"] is None and result["pending_delivery"] is None
        assert result["waiting_files"] == 0 and not result["reserved_name_present"]
        history = result["delivery_history"]
        assert history["accepted_input_submissions"] == 1
        assert history["retained_generations"] == 1  # Mixed reply output is still one generation.
        assert history["retained_generations_with_verified_input"] == 1
        assert history["addressed_reply_publications"] == int(reply)
    else:
        assert result["pending_phase"] == phase
        assert result["waiting_files"] == 1 and result["reserved_name_present"]
        assert result["pending_delivery"] == {
            "input_delivery_verified": phase in {"supplied", "response_retained"},
            "provider_stop_verified": phase == "response_retained",
            "response_retained": phase == "response_retained",
        }
        assert prompt.inbox.messages[0] == original_message
        assert store.reserved_filename() == source.name


def test_reselection_history_is_not_completion_and_status_preserves_exact_pending(workspace):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    first = select(store, "first")
    second = select(store, "second")
    pending = json.loads(store.path.read_bytes())["pending"]
    assert first.inbox.messages == second.inbox.messages
    assert json.loads(store.path.read_bytes())["completed"]
    result = store.status()
    assert "last_completion" not in result
    assert result["delivery_history"]["accepted_input_submissions"] == 0
    assert json.loads(store.path.read_bytes())["pending"] == pending
    assert pending["operation"] == "second"
    assert pending["source_sha256"] == mb._sha(source.read_bytes())


def test_existing_receipts_survive_next_selection_without_a_new_completion_contract(workspace):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    store.complete(prompt, RESPONSE)
    finished = store.status()["delivery_history"]
    assert finished["retained_generations_with_verified_input"] == 1
    assert finished["provider_stop"] == "unknown"
    assert set(json.loads(store.path.read_bytes())) == {
        "schema", "seen", "completed", "pending", "last_selection", "automatic",
    }
    seed(workspace, name="human_letter_next.txt")
    select(store, "next")
    before = snapshot(workspace)
    result = store.status()
    assert result["delivery_history"] == finished
    assert not result["pending_delivery"]["input_delivery_verified"]
    assert "last_completion" not in result
    assert snapshot(workspace) == before
    assert not source.exists()


def test_interrupted_finalization_counts_reply_once_without_completing_from_status(workspace):
    source = seed(workspace)
    archive = source.parent / "read" / source.name
    archive.parent.mkdir()
    archive.write_text("Conflicting retained source")
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    with pytest.raises(ValueError, match="archive conflict"):
        store.complete(prompt, RESPONSE)
    with pytest.raises(ValueError, match="archive conflict"):
        select(store, "retry")
    before = snapshot(workspace)
    result = store.status()
    assert snapshot(workspace) == before
    assert "last_completion" not in result
    assert result["pending_delivery"]["response_retained"]
    assert result["reconciliation_required"]
    assert result["delivery_history"]["retained_generations"] == 1
    assert result["delivery_history"]["addressed_reply_publications"] == 1


@pytest.mark.parametrize("field", ["message_id", "thread_id", "filename", "source_text_sha256",
                                  "rendered_text_sha256", "sender"])
def test_history_never_conflates_different_exact_identities(workspace, field):
    seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    receipt = prompt.inbox.messages[0].receipt()
    receipt[field] = "f" * 64 if field.endswith("sha256") else "different_identity"
    append_event(workspace, "unaddressed_generation", batch_id=prompt.inbox.batch_id,
                 messages=[receipt], supplied_attempt_id=prompt.inbox.last_supplied_attempt,
                 raw_generation_sha256=mb._sha(b"Private retained generation"))
    history = store.status()["delivery_history"]
    assert history["accepted_input_submissions"] == 1
    assert history["retained_generations"] == 1
    assert history["retained_generations_with_verified_input"] == 0
    assert history["addressed_reply_publications"] == 0


@pytest.mark.parametrize("fault", ["partial", "oversize", "symlink", "invalid_identity"])
def test_unavailable_evidence_is_not_reported_as_zero_delivery(workspace, monkeypatch, fault):
    seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    ledger = workspace / "correspondence/inbox_delivery_v1.jsonl"
    if fault == "partial":
        with ledger.open("ab") as handle:
            handle.write(b'{"PRIVATE_TITLE":')
    elif fault == "oversize":
        monkeypatch.setattr(mb, "MAX_HISTORY_BYTES", 10)
    elif fault == "symlink":
        saved = ledger.with_suffix(".retained")
        ledger.rename(saved)
        ledger.symlink_to(saved)
    else:
        append_event(workspace, "supplied_to_model", messages=[{"title": "PRIVATE_TITLE"}])
    before = snapshot(workspace)
    result = store.status()
    assert result["pending_phase"] == "supplied"
    assert result["pending_delivery"]["input_delivery_verified"]
    assert result["delivery_history"]["state"] == "unavailable"
    assert result["delivery_history"]["accepted_input_submissions"] is None
    assert "PRIVATE" not in json.dumps(result)
    assert snapshot(workspace) == before


@pytest.mark.parametrize("when", ["during_read", "after_read", "during_projection"])
@pytest.mark.parametrize("mutation", ["append", "replace", "same_length_rewrite"])
def test_history_snapshot_rechecks_concurrent_updates(workspace, monkeypatch, when, mutation):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    ledger = workspace / "correspondence/inbox_delivery_v1.jsonl"
    before = snapshot(workspace)
    original = ledger.read_bytes()
    info = ledger.stat()
    changed = False

    def update_history():
        nonlocal changed
        if changed:
            return
        changed = True
        if mutation == "append":
            append_event(workspace, "file_consumed", filename="PRIVATE_TITLE_SENTINEL")
        elif mutation == "replace":
            replacement = ledger.with_suffix(".replacement")
            replacement.write_bytes(original)
            replacement.replace(ledger)
        else:
            rewritten = original.replace(b"synthetic", b"SYNTHETIC")
            assert len(rewritten) == len(original) and rewritten != original
            ledger.write_bytes(rewritten)
            # An unchanged length/mtime must not hide a ctime change.
            os.utime(ledger, ns=(info.st_atime_ns, info.st_mtime_ns))

    if when == "during_read":
        read = os.read

        def changing_read(fd, size):
            chunk = read(fd, size)
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
                update_history()
            return chunk

        monkeypatch.setattr(os, "read", changing_read)
    elif when == "after_read":
        read = Directory.read

        def changing_read(directory, name, limit):
            raw = read(directory, name, limit)
            if name == ledger.name:
                update_history()
            return raw

        monkeypatch.setattr(Directory, "read", changing_read)
    else:
        loads = json.loads

        def changing_loads(raw, *args, **kwargs):
            row = loads(raw, *args, **kwargs)
            if isinstance(row, dict) and row.get("schema") == "inbox_delivery_v1":
                update_history()
            return row

        monkeypatch.setattr(json, "loads", changing_loads)

    result = store.status()
    assert changed
    assert result["delivery_history"]["state"] == "unavailable"
    assert result["delivery_history"]["accepted_input_submissions"] is None
    assert result["delivery_history"]["provider_stop"] == "unknown"
    assert result["pending_phase"] == "supplied"
    assert result["pending_delivery"]["input_delivery_verified"]
    assert "PRIVATE" not in json.dumps(result)
    after = snapshot(workspace)
    relative = str(ledger.relative_to(workspace))
    assert {name: value for name, value in after.items() if name != relative} == {
        name: value for name, value in before.items() if name != relative
    }
    assert source.exists()


def test_pages_cover_every_inventory_reference_once_without_titles_or_body_reads(workspace, monkeypatch):
    for index in range(19):
        seed(workspace, name=f"human_letter_PRIVATE_TITLE_{index:02}.txt",
             body=b"PRIVATE_BODY" + str(index).encode())
    store = mb.Mailbox(workspace)
    store.open("exact-reservation", sort_key=lambda name: -int(name[-6:-4]))
    before = snapshot(workspace)
    read = Directory.read

    def metadata_only(directory, name, limit):
        assert not name.endswith(".txt"), "status must not read letter bodies"
        return read(directory, name, limit)

    monkeypatch.setattr(Directory, "read", metadata_only)
    pages = [store.status(page) for page in (1, 2, 3, 4)]
    assert [len(page["queued_files"]) for page in pages] == [8, 8, 3, 0]
    assert [page["next_page"] for page in pages] == [2, 3, None, None]
    assert [page["next_page_command"] for page in pages] == ["MAILBOX_STATUS 2", "MAILBOX_STATUS 3", None, None]
    assert {page["total_pages"] for page in pages} == {3}
    assert {page["waiting_files"] for page in pages} == {19}
    assert len({page["inventory_revision"] for page in pages}) == 1
    entries = [entry for page in pages for entry in page["queued_files"]]
    assert len({entry["inventory_id"] for entry in entries}) == 19
    assert sum(entry["reservation_phase"] == "selected" for entry in entries) == 1
    assert all(entry["bytes"] > 0 and mb._hash(entry["inventory_id"]) for entry in entries)
    assert "PRIVATE" not in json.dumps(pages)
    assert "not sender Message-Id" in pages[0]["inventory_identity_semantics"]
    assert snapshot(workspace) == before


def test_empty_out_of_range_and_changed_inventory_pages_are_explicit(workspace):
    store = mb.Mailbox(workspace)
    empty = store.status()
    assert list(workspace.iterdir()) == []
    assert empty["total_pages"] == 1 and empty["queued_files"] == []
    assert empty["next_page"] is None
    source = seed(workspace)
    first = store.status()
    assert first["inventory_revision"] != empty["inventory_revision"]
    assert store.status(2)["queued_files"] == []
    source.write_bytes(source.read_bytes() + b"Changed")
    changed = store.status()
    assert changed["inventory_revision"] != first["inventory_revision"]
    assert changed["queued_files"][0]["inventory_id"] != first["queued_files"][0]["inventory_id"]


def test_status_before_any_mailbox_operation_creates_no_lock_or_history(workspace):
    source = seed(workspace)
    before = snapshot(workspace)
    result = mb.Mailbox(workspace).status()
    assert result["waiting_files"] == 1
    assert snapshot(workspace) == before
    assert not (workspace / "correspondence").exists()
    assert not (source.parent / ".delivery.lock").exists()


@pytest.mark.parametrize("page", [0, -1, True, 1.0, "1", None, mb.MAX_STATUS_PAGE + 1])
def test_invalid_page_does_not_create_or_mutate_mailbox(workspace, page):
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="positive one-based page"):
        mb.Mailbox(workspace).status(page)
    assert snapshot(workspace) == before
    assert not (workspace / "inbox").exists()


@pytest.mark.parametrize("action,expected", [
    ("MAILBOX_STATUS", 1), ("MAILBOX_STATUS \t\r\n", 1),
    ("MAILBOX_STATUS 0000002", 2), ("MAILBOX_STATUS\t2", 2),
    (" MAILBOX_STATUS\n\t2 \r\n", 2),
    ("MAILBOX_STATUS 18446744073709551615", mb.MAX_STATUS_PAGE),
    ("MAILBOX_STATUS " + "0" * 5000 + "1", 1),
])
def test_page_parser_matches_trimmed_ascii_positive_usize64(action, expected):
    assert mb.status_page(action) == expected


@pytest.mark.parametrize("action", [
    "MAILBOX_STATUS 0", "MAILBOX_STATUS 000", "MAILBOX_STATUS -1", "MAILBOX_STATUS +1",
    "MAILBOX_STATUS 1 2", "MAILBOX_STATUS 1\t2", "MAILBOX_STATUS 1.0",
    "MAILBOX_STATUS \u0661", "MAILBOX_STATUS 18446744073709551616",
    "MAILBOX_STATUS " + "1" * 5000, "CHECK_MAILBOX 1", "MAILBOX_STATUS2", "",
])
def test_page_parser_rejects_nonpositive_nonascii_or_overflow(action):
    with pytest.raises(ValueError, match="positive one-based page"):
        mb.status_page(action)
