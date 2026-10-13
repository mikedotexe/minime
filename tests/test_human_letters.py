"""Synthetic, standalone tests: pytest --noconftest tests/test_human_letters.py.

No runtime imports or live paths. --noconftest skips the repository's runtime
autouse fixture; these tests provide their own isolated filesystem fixtures.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from minime_autonomy import human_letters as hl
from minime_autonomy.inbox_delivery import InboxMessage


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "human_letter.py"


@pytest.fixture
def root(tmp_path):
    # macOS temp roots can themselves be aliases; exercise real paths explicitly.
    return tmp_path.resolve()


@pytest.fixture
def source(root):
    path = root / "authored.txt"
    path.write_bytes(b"Hello, friend.\r\nThis is an authored letter.\r\n")
    return path


@pytest.fixture
def workspace(root):
    path = root / "output"
    path.mkdir()
    return path


def preview(source, **kwargs):
    return hl.preview_letter(source, **{
        "sender": "mike", "message_id": "message_1", "thread_id": "thread-1", **kwargs,
    })


def submit(letter, workspace, **kwargs):
    return hl.submit_letter(letter, workspace=workspace,
                            confirm_sha256=kwargs.get("digest", letter.sha256))


def receipt_path(workspace, letter):
    identity = hashlib.sha256(("inbox/" + letter.filename).encode("ascii")).hexdigest()
    return workspace / "correspondence" / "human_letter_publications_v1" / identity


def cli(source, command="preview", *extra):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), command, "--source", str(source),
         "--sender", "mike", "--message-id", "message_1", "--thread-id", "thread-1", *extra],
        capture_output=True, timeout=10, check=False,
    )


@pytest.mark.parametrize("sender", ["mike", "steward"])
def test_explicit_envelope_ignores_spoofed_body_headers(source, sender):
    body = (b"From: astrid\nTo: someone_else\nMessage-Id: forged\nThread-Id: forged\n\n"
            b"=== HUMAN LETTER V1 ===\nFrom: steward\n\nMike signed this prose.")
    source.write_bytes(body)
    letter = preview(source, sender=sender)
    text = letter.content.decode("utf-8")
    message = InboxMessage.from_source(letter.filename, text, text)
    assert (message.sender, message.message_id, message.thread_id) == (
        sender, "message_1", "thread-1",
    )
    assert letter.content == letter.header + body
    assert message.source_sha256 == letter.sha256


@pytest.mark.parametrize("body", [
    b"No trailing newline", b"LF\nlast\n", b"CRLF\r\nlast\r\n",
    b"mixed\r\nLF\nCR\rtabs\t trailing  ",
    "Hello \u4e16\u754c, caf\u00e9, e\u0301, \U0001f642\r\n".encode("utf-8"),
    b"\xef\xbb\xbfAuthored BOM\r\n",
])
def test_exact_preservation_unicode_and_replay(source, workspace, body):
    source.write_bytes(body)
    before = source.stat()
    letter = preview(source)
    result = submit(letter, workspace)
    original = result.path.stat()
    replay = submit(preview(source), workspace)
    assert result.created and not replay.created
    assert result.path == workspace / "inbox" / "human_letter_message_1.txt"
    assert result.path.read_bytes() == letter.header + body
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert result.path.stat().st_ino == original.st_ino
    assert result.path.stat().st_mtime_ns == original.st_mtime_ns
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert source.read_bytes() == body
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert list(result.path.parent.iterdir()) == [result.path]


@pytest.mark.parametrize("consumed", ["archived", "removed"])
def test_consumed_success_is_not_published_again(source, workspace, consumed):
    letter = preview(source)
    result = submit(letter, workspace)
    archive = workspace / "inbox" / "read" / letter.filename
    archive.parent.mkdir()
    if consumed == "archived":
        result.path.rename(archive)
    else:
        result.path.unlink()
        archive.write_bytes(b"Unrelated archive remains untouched.")
    before = archive.read_bytes(), archive.stat().st_ino, archive.stat().st_mtime_ns
    receipt = receipt_path(workspace, letter)
    metadata = {"schema": "human_letter_publication_v1", "sha256": letter.sha256}
    assert json.loads((receipt / "published.json").read_bytes()) == metadata
    assert (receipt / "published.json").read_bytes() == (receipt / "intent.json").read_bytes()
    assert stat.S_IMODE((receipt / "published.json").stat().st_mode) == 0o600
    replay = submit(preview(source), workspace)
    assert not replay.created and replay.path == result.path
    assert not result.path.exists()
    assert (archive.read_bytes(), archive.stat().st_ino, archive.stat().st_mtime_ns) == before
    assert source.read_bytes() == letter.body


def test_consumed_message_identity_cannot_be_reused_for_new_bytes(source, workspace):
    letter = preview(source)
    result = submit(letter, workspace)
    result.path.unlink()
    changed = hl.HumanLetter("mike", letter.message_id, letter.thread_id, b"Different letter")
    with pytest.raises(hl.HumanLetterError, match="Destination conflict"):
        submit(changed, workspace)
    assert not result.path.exists()


@pytest.mark.parametrize("interruption", ["intent", "output", "receipt"])
def test_interrupted_publication_missing_output_fails_closed(
        source, workspace, monkeypatch, interruption):
    letter = preview(source)
    destination = workspace / "inbox" / letter.filename
    real_link = os.link
    failing_name = {"intent": "intent.json", "output": letter.filename,
                    "receipt": "published.json"}[interruption]

    def interrupted_link(src, dst, **kwargs):
        if dst == failing_name:
            raise OSError(5, "Synthetic publication interruption")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(hl.os, "link", interrupted_link)
    with pytest.raises(hl.HumanLetterError, match="Submission not confirmed"):
        submit(letter, workspace)
    receipt = receipt_path(workspace, letter)
    assert receipt.is_dir() and not (receipt / "published.json").exists()
    archive = workspace / "inbox" / "read" / letter.filename
    if interruption == "receipt":
        assert destination.read_bytes() == letter.content
        archive.parent.mkdir()
        destination.rename(archive)
    assert not destination.exists()
    monkeypatch.setattr(hl.os, "link", real_link)
    for _ in range(2):
        with pytest.raises(hl.HumanLetterError, match="reconcile without republishing"):
            submit(preview(source), workspace)
        assert not destination.exists()
        assert not (receipt / "published.json").exists()
    if archive.exists():
        assert archive.read_bytes() == letter.content
    assert source.read_bytes() == letter.body


def test_interrupted_receipt_can_confirm_exact_visible_output(source, workspace, monkeypatch):
    letter = preview(source)
    real_atomic = hl.Directory.atomic

    def interrupted_receipt(directory, name, data, **kwargs):
        if name == "published.json":
            raise OSError(5, "Synthetic receipt interruption")
        return real_atomic(directory, name, data, **kwargs)

    monkeypatch.setattr(hl.Directory, "atomic", interrupted_receipt)
    with pytest.raises(hl.HumanLetterError):
        submit(letter, workspace)
    destination = workspace / "inbox" / letter.filename
    original = destination.stat()
    monkeypatch.setattr(hl.Directory, "atomic", real_atomic)
    assert not submit(preview(source), workspace).created
    assert destination.read_bytes() == letter.content
    assert (destination.stat().st_ino, destination.stat().st_mtime_ns) == (
        original.st_ino, original.st_mtime_ns)
    assert (receipt_path(workspace, letter) / "published.json").is_file()
    destination.unlink()
    assert not submit(preview(source), workspace).created
    assert not destination.exists()


@pytest.mark.parametrize("marker", ["intent.json", "published.json"])
def test_corrupt_receipt_does_not_republish_or_overwrite(source, workspace, marker):
    letter = preview(source)
    result = submit(letter, workspace)
    result.path.unlink()
    receipt = receipt_path(workspace, letter) / marker
    receipt.write_bytes(b"Foreign metadata")
    with pytest.raises(hl.HumanLetterError, match="conflict"):
        submit(preview(source), workspace)
    assert not result.path.exists()
    assert receipt.read_bytes() == b"Foreign metadata"


def test_retry_syncs_visible_receipt_after_late_fsync_failure(source, workspace, monkeypatch):
    letter = preview(source)
    receipt = receipt_path(workspace, letter)
    real_sync = hl.Directory.sync

    def interrupted_sync(directory):
        if directory.path == receipt and (receipt / "published.json").exists():
            raise OSError(5, "Synthetic receipt directory fsync failure")
        return real_sync(directory)

    monkeypatch.setattr(hl.Directory, "sync", interrupted_sync)
    with pytest.raises(hl.HumanLetterError, match="Submission not confirmed"):
        submit(letter, workspace)
    destination = workspace / "inbox" / letter.filename
    assert destination.read_bytes() == letter.content
    destination.unlink()
    synced = []

    def record_sync(directory):
        synced.append(directory.path)
        return real_sync(directory)

    monkeypatch.setattr(hl.Directory, "sync", record_sync)
    assert not submit(preview(source), workspace).created
    assert receipt in synced
    assert not destination.exists()


@pytest.mark.parametrize("position", ["correspondence", "store", "receipt"])
def test_receipt_ancestry_symlinks_are_rejected(source, workspace, root, position):
    letter = preview(source)
    receipt = receipt_path(workspace, letter)
    target = root / "foreign-receipts"
    target.mkdir()
    sentinel = target / "keep"
    sentinel.write_bytes(b"Foreign data")
    link = {"correspondence": receipt.parent.parent, "store": receipt.parent,
            "receipt": receipt}[position]
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(hl.HumanLetterError, match="symlink"):
        submit(letter, workspace)
    assert not (workspace / "inbox" / letter.filename).exists()
    assert list(target.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"Foreign data"


def test_preview_cli_is_exact_and_has_no_mutation(source, workspace, root):
    before = sorted(root.rglob("*"))
    original = source.read_bytes()
    result = cli(source)
    letter = preview(source)
    assert result.returncode == 0, result.stderr
    assert result.stdout == letter.content
    assert result.stderr == f"SHA-256: {letter.sha256}\nBytes: {len(letter.content)}\n".encode()
    assert sorted(root.rglob("*")) == before
    assert source.read_bytes() == original
    assert not (workspace / "inbox").exists()


def test_cli_preview_preserves_unicode_and_mixed_line_endings(source):
    body = "\u4e16\u754c\r\n\U0001f642\rCafe\u0301\nno final newline".encode()
    source.write_bytes(body)
    result = cli(source)
    assert result.returncode == 0
    assert result.stdout == preview(source).header + body
    assert hashlib.sha256(result.stdout).hexdigest().encode() in result.stderr


def test_default_representation_does_not_include_private_body(source):
    assert "authored letter" not in repr(preview(source))


def test_cli_write_and_replay_do_not_echo_body(source, workspace):
    letter = preview(source)
    args = ("--workspace", str(workspace), "--confirm-sha256", letter.sha256)
    first = cli(source, "write", *args)
    second = cli(source, "write", *args)
    assert first.returncode == second.returncode == 0
    assert b"Created:" in first.stdout
    assert b"Previously published (not republished; consumption unknown)" in second.stdout
    assert letter.body not in first.stdout + first.stderr + second.stdout + second.stderr
    assert (workspace / "inbox" / letter.filename).read_bytes() == letter.content
    (workspace / "inbox" / letter.filename).unlink()
    consumed = cli(source, "write", *args)
    assert consumed.returncode == 0
    assert b"Previously published (not republished; consumption unknown)" in consumed.stdout
    assert not (workspace / "inbox" / letter.filename).exists()
    assert letter.body not in consumed.stdout + consumed.stderr


@pytest.mark.parametrize("digest", ["", "0" * 64, "a" * 63, None, "Z" * 64])
def test_wrong_confirmation_never_creates_inbox(source, workspace, digest):
    with pytest.raises(hl.HumanLetterError, match="Confirmation SHA-256"):
        submit(preview(source), workspace, digest=digest)
    assert list(workspace.iterdir()) == []


def test_changed_source_or_envelope_invalidates_confirmation(source, workspace):
    letter = preview(source)
    source.write_bytes(letter.body + b"Changed.")
    result = cli(source, "write", "--workspace", str(workspace),
                 "--confirm-sha256", letter.sha256)
    assert result.returncode == 2 and b"Confirmation SHA-256" in result.stderr
    for changed in (preview(source), preview(source, sender="steward"),
                    preview(source, thread_id="other"), preview(source, message_id="other")):
        with pytest.raises(hl.HumanLetterError, match="Confirmation SHA-256"):
            submit(changed, workspace, digest=letter.sha256)
    assert not (workspace / "inbox").exists()


@pytest.mark.parametrize("args", [(), ("--workspace", "unused"), ("--confirm-sha256", "0" * 64)])
def test_cli_write_requires_workspace_and_digest(source, args):
    result = cli(source, "write", *args)
    assert result.returncode == 2
    assert b"required" in result.stderr
    assert source.read_bytes() not in result.stderr


@pytest.mark.parametrize("field,value", [
    ("sender", "astrid"), ("sender", "Mike"), ("sender", ""),
    ("sender", "mike\nTo: attacker"),
    ("message_id", "../escape"), ("message_id", "/absolute"),
    ("message_id", "x.txt"), ("message_id", "x\\y"),
    ("message_id", "\u00e9"), ("message_id", "x\nFrom: mike"),
    ("message_id", ""), ("message_id", "a" * 121),
    ("thread_id", "../escape"), ("thread_id", "a" * 121), ("thread_id", ""),
])
def test_invalid_explicit_addresses_are_rejected(source, field, value):
    with pytest.raises(hl.HumanLetterError):
        preview(source, **{field: value})


def test_maximum_ids_match_existing_contract(source):
    letter = preview(source, message_id="A" * 120, thread_id="z" * 120)
    message = InboxMessage.from_source(letter.filename, letter.content.decode(), "")
    assert message.sender == "mike"
    assert message.message_id == "A" * 120


def test_bound_includes_envelope_and_counts_unicode_characters(source):
    overhead = len(preview(source).header)
    body = "\U0001f642" * (hl.MAX_LETTER_CHARS - overhead)
    source.write_bytes(body.encode())
    letter = preview(source)
    assert len(letter.content.decode()) == 12_000
    source.write_bytes((body + "x").encode())
    with pytest.raises(hl.HumanLetterError, match="12,000 characters including the envelope"):
        preview(source)


@pytest.mark.parametrize("body,error", [
    (b"x" * 12_000, "including the envelope"),
    (b"x" * (hl.MAX_SOURCE_BYTES + 1), "bounded UTF-8"),
    (b"bad\xff", "not valid UTF-8"), (b"\xff\xfeR\x00", "not valid UTF-8"),
    (b"{\\rtf1\\ansi private content}", "Source is RTF"),
    (b"\xef\xbb\xbf \r\n{\\RTF1 private content}", "Source is RTF"),
    (b"binary\x00", "control characters"), (b"\x1b[2J", "control characters"),
    (b"", "nonempty"), (b" \r\n\t", "nonempty"),
])
def test_bad_source_fails_without_mutation_or_content_in_errors(source, workspace, body, error):
    source.write_bytes(body)
    with pytest.raises(hl.HumanLetterError, match=error):
        preview(source)
    result = cli(source)
    assert result.returncode == 2 and result.stdout == b""
    assert error.encode() in result.stderr
    assert b"private content" not in result.stderr
    assert source.read_bytes() == body
    assert list(workspace.iterdir()) == []


def test_conflicts_never_overwrite(source, workspace):
    original = preview(source)
    path = submit(original, workspace).path
    for changed in (hl.HumanLetter("mike", "message_1", "thread-1", b"Different"),
                    preview(source, sender="steward"), preview(source, thread_id="other")):
        with pytest.raises(hl.HumanLetterError, match="Destination conflict"):
            submit(changed, workspace)
        assert path.read_bytes() == original.content
    assert list(path.parent.iterdir()) == [path]


def test_missing_workspace_is_not_created(source, root):
    missing = root / "not-created"
    with pytest.raises(hl.HumanLetterError, match="workspace must exist"):
        submit(preview(source), missing)
    assert not missing.exists()


@pytest.mark.parametrize("path", [None, "", b"not-a-text-path", "invalid\0path"])
def test_invalid_paths_are_rejected(source, path):
    with pytest.raises(hl.HumanLetterError):
        preview(path)
    with pytest.raises(hl.HumanLetterError):
        submit(preview(source), path)


def test_path_traversal_is_rejected_before_mutation(source, workspace, root):
    with pytest.raises(hl.HumanLetterError, match="must not contain"):
        preview(str(root / "child" / ".." / source.name))
    with pytest.raises(hl.HumanLetterError, match="must not contain"):
        submit(preview(source), str(workspace / ".." / workspace.name))
    assert list(workspace.iterdir()) == []


def test_relative_paths_are_supported(source, workspace, root, monkeypatch):
    monkeypatch.chdir(root)
    letter = preview(source.name)
    assert submit(letter, workspace.name).path.read_bytes() == letter.content


@pytest.mark.parametrize("position", ["source", "source-parent", "workspace", "inbox", "destination"])
def test_symlinks_are_rejected_even_for_identical_bytes(source, workspace, root, position):
    letter = preview(source)
    outside = root / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_bytes(letter.content)
    if position == "source":
        link = root / "source-link.txt"
        link.symlink_to(source)
        with pytest.raises(hl.HumanLetterError, match="symlink"):
            preview(link)
    elif position == "source-parent":
        link = root / "parent-link"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(hl.HumanLetterError, match="symlink"):
            preview(link / target.name)
    else:
        if position == "workspace":
            link = root / "workspace-link"
            link.symlink_to(workspace, target_is_directory=True)
            workspace = link
        elif position == "inbox":
            (workspace / "inbox").symlink_to(outside, target_is_directory=True)
        else:
            (workspace / "inbox").mkdir()
            (workspace / "inbox" / letter.filename).symlink_to(target)
        with pytest.raises(hl.HumanLetterError, match="symlink"):
            submit(letter, workspace)
    assert target.read_bytes() == letter.content
    assert list(outside.iterdir()) == [target]
    assert source.read_bytes() == letter.body


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_special_files_fail_without_blocking(root, kind):
    path = root / "not-regular"
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    with pytest.raises(hl.HumanLetterError, match="regular files"):
        preview(path)


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_special_destinations_fail_without_blocking(source, workspace, kind):
    letter = preview(source)
    inbox = workspace / "inbox"
    inbox.mkdir()
    path = inbox / letter.filename
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    with pytest.raises(hl.HumanLetterError, match="regular files"):
        submit(letter, workspace)
    assert list(inbox.iterdir()) == [path]


def test_source_at_destination_is_never_overwritten_or_deleted(workspace):
    inbox = workspace / "inbox"
    inbox.mkdir()
    source = inbox / "human_letter_message_1.txt"
    source.write_bytes(b"Authored source at the proposed destination.")
    letter = preview(source)
    with pytest.raises(hl.HumanLetterError, match="Destination conflict"):
        submit(letter, workspace)
    assert source.read_bytes() == letter.body


@pytest.mark.parametrize("race", ["different", "same", "symlink"])
def test_atomic_destination_race_never_overwrites(source, workspace, root, monkeypatch, race):
    letter = preview(source)
    outside = root / "untouched.txt"
    outside.write_bytes(b"Untouched")
    real_link = os.link

    def racing_link(src, dst, **kwargs):
        if dst != letter.filename:
            return real_link(src, dst, **kwargs)
        path = workspace / "inbox" / dst
        if race == "symlink":
            path.symlink_to(outside)
        else:
            path.write_bytes(letter.content if race == "same" else b"Other writer")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(hl.os, "link", racing_link)
    if race == "same":
        assert not submit(letter, workspace).created
    else:
        with pytest.raises(hl.HumanLetterError):
            submit(letter, workspace)
    path = workspace / "inbox" / letter.filename
    assert path.read_bytes() == {"same": letter.content, "different": b"Other writer",
                                 "symlink": b"Untouched"}[race]
    assert outside.read_bytes() == b"Untouched"
    assert list(path.parent.iterdir()) == [path]


def test_replaced_inbox_cannot_redirect_publication(source, workspace, root, monkeypatch):
    letter = preview(source)
    outside = root / "outside"
    outside.mkdir()
    real_link = os.link

    def racing_link(src, dst, **kwargs):
        if dst != letter.filename:
            return real_link(src, dst, **kwargs)
        (workspace / "inbox").rename(workspace / "old-inbox")
        (workspace / "inbox").symlink_to(outside, target_is_directory=True)
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(hl.os, "link", racing_link)
    with pytest.raises(hl.HumanLetterError, match="entry changed"):
        submit(letter, workspace)
    assert list(outside.iterdir()) == []
    assert (workspace / "old-inbox" / letter.filename).read_bytes() == letter.content
    assert not list((workspace / "old-inbox").glob("*.tmp"))


def test_changed_source_during_read_is_rejected(source, monkeypatch):
    real_read = os.read
    changed = False

    def racing_read(fd, size):
        nonlocal changed
        chunk = real_read(fd, size)
        if not changed:
            changed = True
            source.write_bytes(b"Changed while reading")
        return chunk

    monkeypatch.setattr(hl.os, "read", racing_read)
    with pytest.raises(hl.HumanLetterError, match="changed while reading"):
        preview(source)


def test_same_inode_content_change_after_publication_is_rejected(source, workspace, monkeypatch):
    letter = preview(source)
    real_link = os.link

    def tampering_link(src, dst, **kwargs):
        result = real_link(src, dst, **kwargs)
        if dst == letter.filename:
            (workspace / "inbox" / dst).write_bytes(b"x" * len(letter.content))
        return result

    monkeypatch.setattr(hl.os, "link", tampering_link)
    with pytest.raises(hl.HumanLetterError, match="Destination conflict"):
        submit(letter, workspace)
    assert source.read_bytes() == letter.body


def test_short_writes_publish_only_complete_bytes(source, workspace, monkeypatch):
    letter = preview(source)
    real_write, real_link = os.write, os.link

    def short_write(fd, data):
        return real_write(fd, data[:3])

    def link(src, dst, **kwargs):
        if dst == letter.filename:
            assert not (workspace / "inbox" / dst).exists()
            assert (workspace / "inbox" / src).read_bytes() == letter.content
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(hl.os, "write", short_write)
    monkeypatch.setattr(hl.os, "link", link)
    assert submit(letter, workspace).path.read_bytes() == letter.content


@pytest.mark.parametrize("failure", ["zero", "error"])
def test_failed_writes_remove_only_staging_file(source, workspace, monkeypatch, failure):
    letter = preview(source)

    def fail_write(_fd, _data):
        if failure == "error":
            raise OSError(28, "Synthetic disk full")
        return 0

    monkeypatch.setattr(hl.os, "write", fail_write)
    with pytest.raises(hl.HumanLetterError):
        submit(letter, workspace)
    assert list((workspace / "inbox").iterdir()) == []
    assert source.read_bytes() == letter.body


def test_fsync_precedes_publication_and_covers_directories_and_replay(source, workspace, monkeypatch):
    letter = preview(source)
    events = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd):
        events.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        return real_fsync(fd)

    def link(src, dst, **kwargs):
        assert events[-1] == "file"
        events.append({"intent.json": "intent", "published.json": "receipt",
                       letter.filename: "publish"}[dst])
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(hl.os, "fsync", fsync)
    monkeypatch.setattr(hl.os, "link", link)
    submit(letter, workspace)
    assert events[0] == "directory"
    assert events[-1] == "directory"
    assert events.index("intent") < events.index("publish") < events.index("receipt")
    assert "directory" in events[events.index("intent") + 1:events.index("publish")]
    assert "directory" in events[events.index("publish") + 1:events.index("receipt")]
    events.clear()
    submit(letter, workspace)
    assert events == ["file", "directory"]


def test_failed_fsync_never_publishes_partial_bytes(source, workspace, monkeypatch):
    letter = preview(source)
    real_fsync = os.fsync

    def fail_file_fsync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(5, "Synthetic I/O error")
        return real_fsync(fd)

    monkeypatch.setattr(hl.os, "fsync", fail_file_fsync)
    with pytest.raises(hl.HumanLetterError, match="Submission not confirmed"):
        submit(letter, workspace)
    assert list((workspace / "inbox").iterdir()) == []


def test_late_directory_fsync_failure_is_not_success_and_can_replay(source, workspace, monkeypatch):
    letter = preview(source)
    real_fsync = os.fsync

    def fail_after_publish(fd):
        if (stat.S_ISDIR(os.fstat(fd).st_mode)
                and (workspace / "inbox" / letter.filename).exists()):
            raise OSError(5, "Synthetic directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(hl.os, "fsync", fail_after_publish)
    with pytest.raises(hl.HumanLetterError, match="Submission not confirmed"):
        submit(letter, workspace)
    assert (workspace / "inbox" / letter.filename).read_bytes() == letter.content
    monkeypatch.setattr(hl.os, "fsync", real_fsync)
    assert not submit(letter, workspace).created


def test_helper_import_does_not_import_runtime():
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import sys; import minime_autonomy.human_letters; "
         "assert 'minime_autonomy.runtime' not in sys.modules; "
         "assert 'autonomous_agent' not in sys.modules"],
        cwd=SCRIPT.parents[1], capture_output=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
