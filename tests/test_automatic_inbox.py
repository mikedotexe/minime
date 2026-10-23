"""Synthetic durable automatic inbox tests; no runtime, provider or live state."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import os
from threading import Barrier

import pytest

from minime_autonomy import automatic_inbox as automatic
from minime_autonomy.automatic_inbox import AutomaticInbox, validate_automatic
from minime_autonomy.inbox_delivery import InboxMessage
from minime_autonomy.mailbox import LEGACY_SCHEMA, MAX_SEEN, SCHEMA, Mailbox, _sha
from minime_autonomy.mailbox_fs import Directory


@pytest.fixture
def store(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "inbox").mkdir(parents=True)
    return Mailbox(workspace)


def seed(store, name="human_letter_private_title.txt", mid="human_seed", raw=None):
    if raw is None:
        raw = (f"=== HUMAN LETTER V1 ===\nFrom: mike\nTo: minime\n"
               f"Message-Id: {mid}\nThread-Id: thread_exact\n\nPRIVATE_BODY\n").encode()
    (store.inbox / name).write_bytes(raw)
    source = raw.decode().replace("\r\n", "\n").replace("\r", "\n").strip()
    message = InboxMessage.from_source(name, source, source)
    return message, raw


def prepare(store, records=None):
    records = records or [seed(store)]
    messages = [message for message, _ in records]
    text = "  Frozen prefix\n" + "\n\n".join(m.rendered_text for m in messages) + "\nExact suffix  "
    with store.locked() as files:
        return AutomaticInbox(store).prepare_locked(
            text, messages, {m.filename: raw for m, raw in records}, files)


def state(store):
    with store._observed() as files:
        return store._load(files.data)


def batch(store, context):
    return state(store)["automatic"][context.artifact_id]


def dispatch(context, *, accepted=True):
    attempt = context.prepared([{"role": "user", "content": "Ambient\n" + str(context)}], "synthetic")
    if accepted:
        context.accepted(attempt, "synthetic")
    return attempt


def complete(context, text="An independent thought.\nNEXT: REST", parsed=None):
    if parsed is None:
        parsed = {"done": True, "done_reason": "stop", "message": {"content": text}}
    context.provider_completed(parsed, text)
    return text


def recover(store):
    with store.locked() as files:
        return AutomaticInbox(store).pending_context_locked(files)


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_v1_read_only_projection_and_v2_write_keep_namespace_marker(store):
    store.directory.mkdir(parents=True)
    old = {"schema": LEGACY_SCHEMA, "seen": [], "completed": {}, "pending": None}
    store.path.write_text(json.dumps(old, indent=2))
    marker = store.directory / "initialized"
    marker.write_bytes(LEGACY_SCHEMA.encode())
    before = snapshot(store.workspace)
    assert state(store)["automatic"] == {}
    assert store.status()["automatic_batches"]["completed"] == 0
    assert snapshot(store.workspace) == before
    context = prepare(store)
    assert context.messages[0].message_id == "human_seed"
    assert state(store)["schema"] == SCHEMA
    assert marker.read_bytes() == LEGACY_SCHEMA.encode()
    assert marker.stat().st_mtime_ns == before["correspondence/mailbox_v1/initialized"][1]


@pytest.mark.parametrize("phase", ["before_upgrade", "after_upgrade", "context_written", "reserved"])
def test_interrupted_migration_preserves_source_and_never_dispatches(store, monkeypatch, phase):
    message, raw = seed(store)
    original = Directory.atomic
    upgraded = False

    def interrupt(directory, name, content, **kwargs):
        nonlocal upgraded
        if name == "state.json" and not upgraded:
            if phase == "before_upgrade":
                raise OSError("synthetic interruption")
            result = original(directory, name, content, **kwargs)
            upgraded = True
            if phase == "after_upgrade":
                raise OSError("synthetic interruption")
            return result
        result = original(directory, name, content, **kwargs)
        if ((phase == "context_written" and name.endswith(".automatic-context.json"))
                or (phase == "reserved" and name == "state.json")):
            raise OSError("synthetic interruption")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt)
        with pytest.raises(OSError, match="synthetic"):
            prepare(store, [(message, raw)])
    assert (store.inbox / message.filename).read_bytes() == raw
    assert not (store.workspace / "correspondence/inbox_delivery_v1.jsonl").exists()
    if phase == "before_upgrade":
        with pytest.raises(ValueError, match="manifest missing"):
            state(store)
    else:
        loaded = state(store)
        assert loaded["schema"] == SCHEMA
        restored = recover(store)
        assert bool(restored) == (phase == "reserved")
        if restored:
            assert not restored.dispatch_claimed
        else:
            assert prepare(store, [(message, raw)]).messages == (message,)


def test_raw_crlf_snapshot_and_rendered_identity_are_distinct_and_frozen(store):
    message, raw = seed(store)
    raw = b" \r\n" + raw.replace(b"\n", b"\r\n") + b" \r\n"
    message, raw = seed(store, raw=raw)
    context = prepare(store, [(message, raw)])
    selected = batch(store, context)
    assert selected["sources"][0]["source_sha256"] == _sha(raw)
    assert message.source_sha256 != _sha(raw)
    assert (store.directory / (_sha(raw) + ".txt")).read_bytes() == raw
    before = snapshot(store.workspace)
    restored = recover(store)
    assert str(restored) == str(context)
    assert restored.messages == context.messages
    assert restored.batch_id == context.batch_id and not restored.dispatch_claimed
    assert snapshot(store.workspace) == before


def test_missing_or_mutated_context_does_not_claim_attempt(store):
    context = prepare(store)
    with pytest.raises(ValueError, match="missing"):
        context.prepared([{"content": "No selected material"}], "synthetic")
    assert not context.dispatch_claimed
    original = context.messages
    context.messages = (replace(original[0], message_id="different"),)
    with pytest.raises(ValueError, match="differs"):
        dispatch(context)
    assert not context.dispatch_claimed
    context.messages = original
    dispatch(context)
    assert context.dispatch_claimed
    with pytest.raises(ValueError, match="claimed"):
        dispatch(context)
    assert recover(store) is None


def test_concurrent_contexts_claim_exactly_one_attempt(store):
    first = prepare(store)
    second = recover(store)
    barrier = Barrier(2)

    def claim(context):
        barrier.wait(timeout=5)
        try:
            return dispatch(context, accepted=False)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (first, second)))
    assert sum(item is not None for item in results) == 1
    assert batch(store, first)["attempt_id"] in results
    assert first.dispatch_claimed and second.dispatch_claimed
    assert recover(store) is None


def test_wrong_acceptance_cannot_link_delivery(store):
    context = prepare(store)
    attempt = dispatch(context, accepted=False)
    before = snapshot(store.workspace)
    with pytest.raises(ValueError, match="identity mismatch"):
        context.accepted("submission_" + "0" * 32, "synthetic")
    assert snapshot(store.workspace) == before
    context.accepted(attempt, "synthetic")
    before = snapshot(store.workspace)
    context.accepted(attempt, "synthetic")
    assert snapshot(store.workspace) == before
    assert batch(store, context)["supplied_attempt"] == attempt


@pytest.mark.parametrize("parsed", [
    {"done": True, "done_reason": "stop"},
    {"choices": [{"finish_reason": "stop"}]},
])
def test_verified_completion_retains_output_and_retires_exact_source(store, parsed):
    message, raw = seed(store)
    context = prepare(store, [(message, raw)])
    dispatch(context)
    output = complete(context, "A thought.\nINBOX_REPLY human_seed\nPrivate reply.\nNEXT: REST", parsed)
    assert (store.inbox / message.filename).exists()
    assert batch(store, context)["phase"] == "response_retained"
    assert context.finish(output) is True
    assert not (store.inbox / message.filename).exists()
    assert (store.inbox / "read" / message.filename).read_bytes() == raw
    assert (store.directory / (_sha(output.encode()) + ".automatic-output.txt")).read_text() == output
    replies = list((store.workspace / "outbox/human/mike").glob("*.txt"))
    assert len(replies) == 1
    assert "Reply-To: human_seed\nThread-Id: thread_exact\n" in replies[0].read_text()
    assert "Private reply." in replies[0].read_text() and "NEXT: REST" not in replies[0].read_text()
    assert batch(store, context)["phase"] == "completed"
    before = snapshot(store.workspace)
    assert context.finish(output) is True and recover(store) is None
    assert snapshot(store.workspace) == before


@pytest.mark.parametrize("parsed", [
    {}, {"done": True}, {"done": True, "done_reason": "length"},
    {"choices": [{"finish_reason": None}]}, {"choices": []}, None,
    {"unserializable": object()},
])
def test_unknown_partial_or_unserializable_completion_retains_private_output(store, parsed):
    message, raw = seed(store)
    context = prepare(store, [(message, raw)])
    dispatch(context)
    output = "INBOX_REPLY human_seed\nPartial authored reply."
    context.provider_completed(parsed, output)
    assert context.finish(output) is False
    assert batch(store, context)["phase"] == "incomplete"
    assert (store.inbox / message.filename).read_bytes() == raw
    assert not (store.inbox / "read").exists()
    assert not (store.workspace / "outbox/human").exists()
    private = list((store.workspace / "outbox/unaddressed").glob("*.txt"))
    assert len(private) == 1 and output in private[0].read_text()
    before = snapshot(store.workspace)
    assert recover(store) is None and context.dispatch_claimed
    assert snapshot(store.workspace) == before


@pytest.mark.parametrize("accepted,hook,text", [
    (False, True, "Unconfirmed output"),
    (True, False, "Output without a completion hook"),
    (True, True, ""),
])
def test_unconfirmed_missing_hook_or_empty_output_never_retires(store, accepted, hook, text):
    context = prepare(store)
    dispatch(context, accepted=accepted)
    if hook:
        complete(context, text)
    assert context.finish(text) is False
    assert batch(store, context)["phase"] == "incomplete"
    assert (store.inbox / context.messages[0].filename).exists()
    assert recover(store) is None


def test_cleaned_output_mismatch_preserves_both_variants_without_retirement(store):
    context = prepare(store)
    dispatch(context)
    first = complete(context, "First cleaned output")
    second = "Different final output"
    assert context.finish(second) is False
    assert batch(store, context)["incomplete_reason"] == "cleaned_output_mismatch"
    assert set(batch(store, context)["outputs"]) == {_sha(first.encode()), _sha(second.encode())}
    assert recover(store) is None
    assert (store.inbox / context.messages[0].filename).exists()
    assert len(list((store.workspace / "outbox/unaddressed").glob("*.txt"))) == 2


def test_changed_provider_completion_remains_incomplete(store):
    context = prepare(store)
    dispatch(context)
    complete(context, "Original")
    complete(context, "Changed")
    assert context.finish("Changed") is False
    assert batch(store, context)["incomplete_reason"] == "completion_changed"
    assert recover(store) is None


def test_recovery_publishes_and_retires_without_inference_or_next(store, monkeypatch):
    context = prepare(store)
    dispatch(context)
    complete(context, "INBOX_REPLY human_seed\nReply.\nNEXT: SEARCH never execute this")

    def forbidden(*args, **kwargs):
        pytest.fail("recovery must not prepare another provider attempt")

    monkeypatch.setattr(automatic.AutomaticInboxContext, "prepared", forbidden)
    assert recover(store) is None
    assert batch(store, context)["phase"] == "completed"
    reply = next((store.workspace / "outbox/human/mike").glob("*.txt"))
    reply.unlink()  # Synthetic recipient consumed its publication.
    before = snapshot(store.workspace)
    assert recover(store) is None
    assert snapshot(store.workspace) == before and not reply.exists()


def test_archive_conflict_retains_batch_but_other_mail_is_independent(store):
    context = prepare(store)
    dispatch(context)
    output = complete(context)
    archive = store.inbox / "read"
    archive.mkdir()
    (archive / context.messages[0].filename).write_bytes(b"Previous archived letter")
    with pytest.raises(ValueError, match="archive conflict"):
        context.finish(output)
    assert recover(store) is None
    assert batch(store, context)["phase"] == "response_retained"
    assert (store.inbox / context.messages[0].filename).exists()
    assert store.notice() is None
    other = seed(store, "human_letter_other.txt", "other")
    notice = store.notice()
    assert notice.waiting == 1 and len(notice.identities) == 1
    prompt = store.open("explicit-other", sort_key=str)
    assert prompt.inbox.messages[0].message_id == "other"
    assert str(context) not in str(prompt)
    third = seed(store, "human_letter_third.txt", "third")
    new = prepare(store, [third])
    assert not new.dispatch_claimed and new.messages[0].message_id == "third"
    assert (store.inbox / other[0].filename).exists()


def test_consumed_publication_is_not_recreated_during_retirement_retry(store, monkeypatch):
    context = prepare(store)
    dispatch(context)
    output = complete(context, "INBOX_REPLY human_seed\nA reply.")
    original = store._retire_source

    def fail(*args, **kwargs):
        raise OSError("synthetic retirement interruption")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_retire_source", fail)
        with pytest.raises(OSError):
            context.finish(output)
    reply = next((store.workspace / "outbox/human/mike").glob("*.txt"))
    reply.unlink()
    assert store._retire_source == original
    assert recover(store) is None
    assert batch(store, context)["phase"] == "completed" and not reply.exists()


def test_source_replaced_before_retirement_is_left_available_as_new_mail(store):
    context = prepare(store)
    dispatch(context)
    output = complete(context)
    name = context.messages[0].filename
    replacement = b"Different incoming source"
    (store.inbox / name).write_bytes(replacement)
    assert context.finish(output) is True
    assert (store.inbox / name).read_bytes() == replacement
    assert store.notice().waiting == 1
    assert not (store.inbox / "read" / name).exists()


def test_source_replacement_race_retains_inode_as_explicit_debt(store, monkeypatch):
    context = prepare(store)
    dispatch(context)
    output = complete(context)
    name = context.messages[0].filename
    original = os.rename
    replacement = b"Racing replacement bytes"

    def raced(src, dst, **kwargs):
        if src == name and dst == "source":
            (store.inbox / name).write_bytes(replacement)
        return original(src, dst, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "rename", raced)
        with pytest.raises(ValueError, match="changed source retained"):
            context.finish(output)
    selected = batch(store, context)
    source = selected["sources"][0]
    assert selected["phase"] == "response_retained"
    assert source["retirement_debt"] == "changed_source_retained"
    assert (store.directory / ("retired-" + source["artifact_id"]) / "source").read_bytes() == replacement
    before = snapshot(store.workspace)
    assert recover(store) is None
    assert (store.directory / ("retired-" + source["artifact_id"]) / "source").read_bytes() == replacement
    assert state(store)["automatic"][context.artifact_id]["phase"] != "completed"
    assert set(snapshot(store.workspace)) == set(before)


@pytest.mark.parametrize("phase", ["selected", "started", "supplied", "incomplete", "response_retained", "completed"])
def test_status_is_read_only_private_and_not_a_fresh_notice_for_reserved_mail(store, phase):
    context = prepare(store)
    if phase != "selected":
        dispatch(context, accepted=phase != "started")
    if phase in {"response_retained", "completed"}:
        output = complete(context)
        if phase == "completed":
            assert context.finish(output)
    elif phase == "incomplete":
        assert context.finish("Private incomplete output") is False
    before = snapshot(store.workspace)
    result = store.status()
    assert result["automatic_batches"][phase] == 1
    serialized = json.dumps(result)
    for secret in ("PRIVATE_BODY", "private_title", "human_seed", "thread_exact", "Private incomplete output"):
        assert secret not in serialized
    assert "not read/understood" in result["semantics"]
    assert snapshot(store.workspace) == before
    assert store.notice() is None
    assert snapshot(store.workspace) == before
    seed(store, "human_letter_unrelated.txt", "unrelated")
    assert store.notice().waiting == 1


@pytest.mark.parametrize("field,value", [
    ("phase", "invented"), ("phase", []), ("context_sha256", "not-a-hash"),
    ("outputs", ["0" * 64] * 9), ("published_outputs", ["0" * 64]),
    ("attempt_id", "submission_invalid"), ("unknown", "field"),
    ("sources", []), ("sources", [{"filename": "../escape"}]),
])
def test_corrupt_manifest_is_rejected_without_changes(store, field, value):
    context = prepare(store)
    corrupted = state(store)
    corrupted["automatic"][context.artifact_id][field] = value
    store.path.write_text(json.dumps(corrupted))
    before = snapshot(store.workspace)
    with pytest.raises(ValueError):
        store.status()
    assert context.dispatch_claimed  # Unknown history is not permission to retry.
    assert snapshot(store.workspace) == before


@pytest.mark.parametrize("artifact", ["context", "source", "completion", "output"])
def test_corrupt_frozen_artifacts_hold_exact_work_without_inference(store, artifact, caplog):
    context = prepare(store)
    selected = batch(store, context)
    if artifact in {"completion", "output"}:
        dispatch(context)
        text = complete(context)
        name = (context.artifact_id + ".automatic-completion.json" if artifact == "completion"
                else _sha(text.encode()) + ".automatic-output.txt")
    else:
        name = (context.artifact_id + ".automatic-context.json" if artifact == "context"
                else selected["sources"][0]["source_sha256"] + ".txt")
    (store.directory / name).write_bytes(b"corrupt retained artifact")
    before = snapshot(store.workspace)
    assert recover(store) is None
    assert "Automatic inbox" in caplog.text
    assert "PRIVATE_BODY" not in caplog.text and "private_title" not in caplog.text
    assert snapshot(store.workspace) == before
    assert (store.inbox / context.messages[0].filename).exists()
    if artifact in {"context", "source"}:
        with pytest.raises(ValueError):
            dispatch(context)


def test_artifact_symlink_and_foreign_filesystem_owner_fail_closed(store, tmp_path):
    context = prepare(store)
    frozen = store.directory / (context.artifact_id + ".automatic-context.json")
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(frozen.read_bytes())
    frozen.unlink()
    frozen.symlink_to(foreign)
    with pytest.raises((OSError, ValueError)):
        dispatch(context)
    assert not context.dispatch_claimed
    other = Mailbox(tmp_path / "other")
    with other.locked() as files:
        with pytest.raises(ValueError, match="owner mismatch"):
            AutomaticInbox(store).pending_context_locked(files)


def test_explicit_and_automatic_reservations_never_overlap(store):
    first = seed(store)
    prompt = store.open("existing-explicit", sort_key=str)
    with pytest.raises(ValueError, match="reserved"):
        prepare(store, [first])
    second = seed(store, "human_letter_second.txt", "second")
    context = prepare(store, [second])
    assert context.messages[0].message_id == "second"
    assert store.open("same-explicit", sort_key=str).inbox.messages == prompt.inbox.messages
    corrupted = state(store)
    corrupted["pending"]["filename"] = context.messages[0].filename
    store.path.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError, match="overlapping"):
        state(store)


def test_nonblocking_lock_contention_and_default_lock_release(store):
    with store.locked():
        with pytest.raises(BlockingIOError):
            with store.locked(nonblocking=True):
                pytest.fail("contended lock acquired")
    with store.locked(nonblocking=True) as files:
        assert files.inbox.path == store.inbox


def test_bounds_share_native_capacity_and_preserve_existing_history(store, monkeypatch):
    assert automatic.MAX_BATCHES == MAX_SEEN == 65_536
    first = prepare(store)
    second = seed(store, "human_letter_second.txt", "second")
    before = snapshot(store.workspace)
    monkeypatch.setattr(automatic, "MAX_BATCHES", 1)
    with pytest.raises(ValueError, match="history full"):
        prepare(store, [second])
    assert snapshot(store.workspace) == before
    assert recover(store).artifact_id == first.artifact_id


def test_native_manifest_byte_bound_fails_visibly_without_overwriting(store):
    prepare(store)
    before = snapshot(store.workspace)
    with store.locked() as files:
        value = store._load(files.data)
        value["test_padding"] = "x" * 8_000_000
        with pytest.raises(ValueError, match="history byte limit"):
            store._save(value, files)
    assert snapshot(store.workspace) == before


def test_empty_administrative_context_is_not_a_durable_batch(store):
    with store.locked() as files:
        with pytest.raises(ValueError, match="admitted raw sources"):
            AutomaticInbox(store).prepare_locked("Cadence summary", [], {}, files)
    assert not store.path.exists()


def test_validation_is_pure_and_rejects_duplicate_active_names(store):
    context = prepare(store)
    value = state(store)["automatic"]
    before = deepcopy(value)
    validate_automatic(value)
    assert value == before
    extra = "a" * 64
    copied = deepcopy(value[context.artifact_id])
    copied["sources"][0]["artifact_id"] = automatic._source_id(extra, copied["sources"][0]["filename"])
    value[extra] = copied
    with pytest.raises(ValueError):
        validate_automatic(value)


def test_v1_cannot_smuggle_automatic_history_and_v2_requires_mapping(store):
    prepare(store)
    value = state(store)
    value["schema"] = LEGACY_SCHEMA
    store.path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="requires mailbox v2"):
        state(store)
    value["schema"] = SCHEMA
    del value["automatic"]
    store.path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        state(store)
