"""Synthetic filesystem fault tests; can run with --noconftest, without runtime."""

import json
import os
import stat

import pytest

from minime_autonomy import mailbox as mb
from minime_autonomy.mailbox_fs import Directory


RESPONSE = "INBOX_REPLY seed\nA private synthetic reply.\r\nNEXT: REST"


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path.resolve() / "workspace"
    root.mkdir()
    return root


def seed(workspace, body=b"Authored\r\nexact bytes.\r\n", name="human_letter_seed.txt"):
    source = workspace / "inbox" / name
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b"=== HUMAN LETTER V1 ===\nMessage-Id: seed\nThread-Id: thread\n"
                       b"From: mike\nTo: minime\n\n" + body)
    return source


def select(store, operation="op"):
    return store.open(operation, sort_key=lambda name: name)


def accepted(prompt, *, validate=True):
    attempt = prompt.inbox.prepared([{"content": str(prompt)}], "synthetic")
    prompt.inbox.accepted(attempt, "synthetic")
    if validate:
        prompt.validate_completion({"done": True, "done_reason": "stop",
                                    "message": {"content": RESPONSE}})


def prepare(workspace):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt)
    return store, prompt, source


def state(store):
    return json.loads(store.path.read_bytes())


@pytest.mark.parametrize("phase", ["selected", "started", "supplied", "response_retained", "completed"])
def test_missing_manifest_with_history_never_reinitializes(workspace, monkeypatch, phase):
    source = seed(workspace)
    original = source.read_bytes()
    store = mb.Mailbox(workspace)
    prompt = select(store)
    if phase == "started":
        prompt.inbox.prepared([{"content": str(prompt)}], "synthetic")
    elif phase in {"supplied", "response_retained", "completed"}:
        accepted(prompt)
    if phase == "response_retained":
        monkeypatch.setattr(store, "_finish_locked", lambda *args: None)
        store.complete(prompt, RESPONSE)
    elif phase == "completed":
        store.complete(prompt, RESPONSE)
    store.path.unlink()
    for operation in (store.status, store.reserved_filename, lambda: select(store, "new-op")):
        with pytest.raises(ValueError, match="manifest missing"):
            operation()
    assert not store.path.exists()
    if phase != "completed":
        assert source.read_bytes() == original


def test_orphan_staging_artifact_is_not_pristine_history(workspace):
    seed(workspace)
    store = mb.Mailbox(workspace)
    store.directory.mkdir(parents=True)
    (store.directory / ".old-stage.tmp").write_bytes(b"partial")
    with pytest.raises(ValueError, match="manifest missing"):
        select(store)


def test_no_eligible_status_contains_only_historical_reason_counts(workspace):
    inbox = workspace / "inbox"
    inbox.mkdir()
    bodies = [b"{\\rtf1 SECRET}", b"\xef\xbb\xbf \r\n{\\RTF1 SECRET}",
              b"\xff", b"\xef\xbb\xbf \r\n", b"x" * 5000, b"x" * 64001]
    for index, body in enumerate(bodies):
        (inbox / f"private-filename-{index}.txt").write_bytes(body)
    store = mb.Mailbox(workspace)
    assert select(store) is None
    result = store.status()
    assert result["waiting_files"] == 6
    assert result["last_selection"] == {
        "outcome": "no_eligible", "inspected": 6, "character_limit": 4000,
        "rejection_counts": {"rtf": 2, "invalid_utf8": 1, "empty": 1,
                             "oversize": 2, "unreadable": 0},
    }
    assert result["last_selection_is_historical"]
    assert "SECRET" not in json.dumps(result) and "private-filename" not in json.dumps(result)
    for path in inbox.glob("*.txt"):
        path.unlink()
    assert store.status()["last_selection"] == result["last_selection"]
    assert store.status()["waiting_files"] == 0


@pytest.mark.parametrize("component", ["workspace", "inbox", "correspondence", "mailbox_v1"])
def test_mailbox_rejects_symlinked_ancestry(workspace, component):
    outside = workspace.parent / "outside"
    outside.mkdir()
    store = mb.Mailbox(workspace)
    if component == "workspace":
        alias = workspace.parent / "alias"
        alias.symlink_to(workspace, target_is_directory=True)
        store = mb.Mailbox(alias)
    else:
        link = {"inbox": store.inbox, "correspondence": workspace / "correspondence",
                "mailbox_v1": store.directory}[component]
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        store.status()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("parts", [("outbox",), ("outbox", "human"),
                                  ("outbox", "human", "mike"), ("outbox", "unaddressed")])
def test_reply_destinations_reject_symlinked_ancestry(workspace, parts):
    store, prompt, source = prepare(workspace)
    original = source.read_bytes()
    outside = workspace.parent / "outside"
    outside.mkdir()
    link = workspace.joinpath(*parts)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        store.complete(prompt, RESPONSE)
    assert source.read_bytes() == original
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("when", ["before", "after", "in_place"])
def test_replacement_source_is_never_unlinked(workspace, monkeypatch, when):
    store, prompt, source = prepare(workspace)
    original = source.read_bytes()
    replacement = b"A newer independently authored letter.\r\n"
    real_rename = os.rename
    held_fd = os.open(source, os.O_WRONLY) if when == "in_place" else None

    def replace_source(src, dst, **kwargs):
        assert src == source.name and dst == "source"
        if when == "before":
            source.unlink()
            source.write_bytes(replacement)
        result = real_rename(src, dst, **kwargs)
        if when == "after":
            source.write_bytes(replacement)
        elif when == "in_place":
            os.ftruncate(held_fd, 0)
            os.write(held_fd, replacement)
        return result

    monkeypatch.setattr(mb.os, "rename", replace_source)
    try:
        if when == "after":
            store.complete(prompt, RESPONSE)
            assert source.read_bytes() == replacement
        else:
            with pytest.raises(ValueError, match="changed source retained"):
                store.complete(prompt, RESPONSE)
            retired = list(store.directory.glob("retired-*/source"))
            assert len(retired) == 1 and retired[0].read_bytes() == replacement
            assert store.status()["retirement_debt"] == "changed_source_retained"
            assert store.status()["reconciliation_required"]
            with pytest.raises(ValueError, match="reconciliation required"):
                select(store, "retry")
        assert (workspace / "inbox/read" / source.name).read_bytes() == original
        assert (store.directory / (mb._sha(original) + ".txt")).read_bytes() == original
    finally:
        if held_fd is not None:
            os.close(held_fd)


def test_reply_consumed_before_archive_recovery_is_not_republished(workspace):
    store, prompt, source = prepare(workspace)
    archive = source.parent / "read" / source.name
    archive.parent.mkdir()
    archive.write_bytes(b"Conflicting old archive")
    with pytest.raises(ValueError, match="archive conflict"):
        store.complete(prompt, RESPONSE)
    reply = next((workspace / "outbox/human/mike").glob("*.txt"))
    reply.unlink()  # A synthetic recipient consumed it.
    with pytest.raises(ValueError, match="archive conflict"):
        select(store, "retry")
    assert not reply.exists()
    archive.unlink()
    assert select(store, "finish") is None
    assert not reply.exists() and not source.exists()


@pytest.mark.parametrize("failure", ["intent", "published"])
def test_uncertainty_before_publication_marker_never_blindly_republishes(workspace, monkeypatch, failure):
    store, prompt, source = prepare(workspace)
    real_atomic = Directory.atomic

    def fail_marker(directory, name, content, **kwargs):
        if name == failure + ".json":
            raise OSError("synthetic publication interruption")
        return real_atomic(directory, name, content, **kwargs)

    monkeypatch.setattr(Directory, "atomic", fail_marker)
    with pytest.raises(OSError):
        store.complete(prompt, RESPONSE)
    monkeypatch.setattr(Directory, "atomic", real_atomic)
    # Remove any artifact a recipient could already have consumed.
    for path in (workspace / "outbox").rglob("*.txt"):
        path.unlink()
    with pytest.raises(ValueError, match="publication.*(incomplete|uncertain)"):
        select(store, "retry")
    assert source.exists()
    assert not list((workspace / "outbox").rglob("*.txt"))
    assert store.status()["reconciliation_required"]


def test_intent_with_matching_visible_bytes_can_confirm_without_rewriting(workspace, monkeypatch):
    store, prompt, _ = prepare(workspace)
    real_atomic = Directory.atomic

    def fail_marker(directory, name, content, **kwargs):
        if name == "published.json":
            raise OSError("synthetic interruption")
        return real_atomic(directory, name, content, **kwargs)

    monkeypatch.setattr(Directory, "atomic", fail_marker)
    with pytest.raises(OSError):
        store.complete(prompt, RESPONSE)
    existing = next((workspace / "outbox/unaddressed").glob("*.txt"))
    before = existing.stat()
    monkeypatch.setattr(Directory, "atomic", real_atomic)
    assert select(store, "recovery") is None
    assert existing.stat().st_ino == before.st_ino
    assert existing.stat().st_mtime_ns == before.st_mtime_ns


def test_corrupt_publication_receipt_fails_closed(workspace):
    store, prompt, source = prepare(workspace)
    archive = source.parent / "read" / source.name
    archive.parent.mkdir()
    archive.write_bytes(b"conflict")
    with pytest.raises(ValueError):
        store.complete(prompt, RESPONSE)
    receipt = next((workspace / "correspondence/inbox_publications_v1").glob("*/published.json"))
    receipt.write_bytes(b"corrupt")
    before = {path: path.read_bytes() for path in (workspace / "outbox").rglob("*.txt")}
    with pytest.raises(ValueError, match="corrupt publication receipt"):
        select(store, "retry")
    assert before == {path: path.read_bytes() for path in before}


def test_atomic_publication_is_complete_and_fsynced_before_visibility(workspace, monkeypatch):
    real_write, real_link, real_fsync = os.write, os.link, os.fsync
    content = b"private exact bytes\r\n" * 100
    file_synced = False

    def short_write(fd, data):
        assert not (workspace / "visible.txt").exists()
        return real_write(fd, data[:7])

    def fsync(fd):
        nonlocal file_synced
        if stat.S_ISREG(os.fstat(fd).st_mode):
            file_synced = True
        return real_fsync(fd)

    def link(src, dst, **kwargs):
        assert file_synced
        assert (workspace / src).read_bytes() == content
        assert not (workspace / dst).exists()
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "write", short_write)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "link", link)
    with Directory(workspace) as directory:
        directory.atomic("visible.txt", content)
    assert (workspace / "visible.txt").read_bytes() == content
    assert sorted(path.name for path in workspace.iterdir()) == ["visible.txt"]


@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_failed_staging_leaves_no_visible_or_poisoned_artifact(workspace, monkeypatch, failure):
    real_fsync = os.fsync

    def fail(*args):
        raise OSError("synthetic write failure")

    def fsync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            fail()
        return real_fsync(fd)

    monkeypatch.setattr(os, failure, fail if failure == "write" else fsync)
    with Directory(workspace) as directory:
        with pytest.raises(OSError):
            directory.atomic("visible.txt", b"secret")
    assert list(workspace.iterdir()) == []


def test_parent_swap_cannot_redirect_atomic_write(workspace, monkeypatch):
    target = workspace / "target"
    target.mkdir()
    outside = workspace / "outside"
    outside.mkdir()
    real_link = os.link

    def replace_parent(src, dst, **kwargs):
        target.rename(workspace / "retained-target")
        target.symlink_to(outside, target_is_directory=True)
        return real_link(src, dst, **kwargs)

    with Directory(target) as directory:
        monkeypatch.setattr(os, "link", replace_parent)
        with pytest.raises(ValueError, match="directory changed"):
            directory.atomic("visible.txt", b"exact")
    assert list(outside.iterdir()) == []
    assert (workspace / "retained-target/visible.txt").read_bytes() == b"exact"


def test_validation_is_required_before_complete(workspace):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt, validate=False)
    assert prompt.private_correspondence
    with pytest.raises(ValueError, match="not validated"):
        store.complete(prompt, RESPONSE)
    assert source.exists() and not (workspace / "outbox").exists()


@pytest.mark.parametrize("parsed", [
    {"done": False, "done_reason": "stop"}, {"done": True, "done_reason": "length"},
    {"done": True}, {"choices": [{"finish_reason": "length"}]},
    {"choices": [{"finish_reason": None}]}, {"choices": []}, {}, None,
])
def test_rejected_completion_retains_full_private_receipt_and_reservation(workspace, parsed):
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt, validate=False)
    if isinstance(parsed, dict):
        parsed = {**parsed, "private_test_content": "PRIVATE synthetic body\r\n"}
    with pytest.raises(ValueError, match="incomplete or unknown") as error:
        prompt.validate_completion(parsed)
    assert "PRIVATE" not in str(error.value)
    receipt = next(store.directory.glob("*.provider.json"))
    assert json.loads(receipt.read_bytes()) == parsed
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="not validated"):
        store.complete(prompt, RESPONSE)
    assert store.status()["pending_phase"] == "supplied"
    assert source.exists() and not (workspace / "outbox").exists()
    with pytest.raises(ValueError, match="uncertain"):
        select(store, "retry")


@pytest.mark.parametrize("parsed", [
    {"done": True, "done_reason": "stop", "message": {"content": RESPONSE}},
    {"choices": [{"finish_reason": "stop", "message": {"content": RESPONSE}}]},
])
def test_explicit_stop_receipt_allows_completion(workspace, parsed):
    seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt, validate=False)
    prompt.validate_completion(parsed)
    store.complete(prompt, RESPONSE)
    assert store.status()["pending_phase"] is None


def test_receipt_corruption_blocks_routing(workspace):
    store, prompt, source = prepare(workspace)
    next(store.directory.glob("*.provider.json")).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="receipt changed"):
        store.complete(prompt, RESPONSE)
    assert source.exists() and not (workspace / "outbox").exists()


@pytest.mark.parametrize("content", ["x" * 200, "\u00e9" * 90])
def test_oversized_provider_receipt_is_not_persisted(workspace, monkeypatch, content):
    assert mb.MAX_PROVIDER_BYTES == 8_000_000
    monkeypatch.setattr(mb, "MAX_PROVIDER_BYTES", 200)
    source = seed(workspace)
    store = mb.Mailbox(workspace)
    prompt = select(store)
    accepted(prompt, validate=False)
    parsed = {"done": True, "done_reason": "stop", "message": {"content": content}}
    assert len(json.dumps(parsed, ensure_ascii=False).encode()) > 200
    with pytest.raises(ValueError, match="retention byte limit") as error:
        prompt.validate_completion(parsed)
    assert content not in str(error.value)
    assert not list(store.directory.glob("*.provider.json"))
    assert state(store)["pending"]["phase"] == "supplied"
    assert not state(store)["pending"].get("completion_validated")
    assert source.exists() and not (workspace / "outbox").exists()
