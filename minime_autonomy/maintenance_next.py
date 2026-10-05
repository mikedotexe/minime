"""Exact graceful NEXT continuation receipts, never action authorization.

The sovereignty file remains the queue. This bounded append-only stream records
drain seals and process-bound restoration; it contains hashes, never command text.
An interrupted append is preserved and refuses recovery, not silently truncated.
"""
from contextlib import contextmanager
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

CONTRACT = "minime_next_handoff_v1"
HANDOFF_VERSION = 1
MAX_STATE = 4 * 1024 * 1024
MAX_HISTORY = 8 * 1024 * 1024
MAX_RECORDS = 8192
# Logical headroom for one replacement acknowledgement, not a disk allocation.
MAX_RESTORE_RECORD_BYTES = 8192
PENDING_KEYS = ("pending_next_action", "pending_next_selection_id", "choice_envelope_v1",
                "pending_next_action_status", "pending_next_action_updated_at",
                "pending_next_action_update_reason")


class HandoffError(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise HandoffError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_handoff_key")
        result[key] = value
    return result


def parse(raw):
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "nonfinite_handoff_value"))
    except (ValueError, UnicodeError) as exc:
        raise HandoffError("invalid_handoff_json") from exc
    require(isinstance(value, dict), "invalid_handoff_object")
    return value


def checked(path):
    path = Path(path).absolute()
    # macOS exposes its root-owned temporary directories through these aliases.
    # Canonicalize only the OS aliases; workspace/file symlinks still refuse.
    if sys.platform == "darwin":
        for alias in (Path("/var"), Path("/tmp")):
            if path.is_relative_to(alias) and alias.is_symlink():
                target = Path("/private") / alias.name
                require(alias.lstat().st_uid == 0 and alias.resolve() == target,
                        "unexpected_system_path_alias")
                path = target / path.relative_to(alias)
                break
    require(not any(p.is_symlink() for p in (path, *path.parents)), "linked_handoff_path")
    return path


def read(path, maximum, *, missing=None):
    path = checked(path)
    if not path.exists() and missing is not None:
        return missing
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and info.st_size <= maximum,
                "invalid_handoff_file")
        raw = handle.read(maximum + 1)
        require(len(raw) <= maximum, "handoff_file_limit")
        return raw


def sync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def transaction(state_path):
    path = checked(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = checked(path.with_name(".sovereignty-state.lock"))
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1, "invalid_handoff_lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        require((lock.stat().st_dev, lock.stat().st_ino) == (info.st_dev, info.st_ino),
                "handoff_lock_changed")
        yield
    finally:
        os.close(fd)


def state_writer(method):
    @wraps(method)
    def call(agent, *args, **kwargs):
        if method.__name__ == "_persist_pending_next_action" and not hasattr(agent, "session_id"):
            return None
        with transaction(agent._sovereignty_state_path()):
            # Validate existing bytes before a legacy writer can rebuild them.
            parse(read(agent._sovereignty_state_path(), MAX_STATE, missing=b"{}"))
            return method(agent, *args, **kwargs)
    return call


def decision(method):
    @wraps(method)
    def call(agent, *args, **kwargs):
        protocol = hasattr(agent, "_agent_boot_id")
        derived = kwargs.get("_derived_action") is not None
        try:
            if protocol:
                require(not getattr(agent, "_next_handoff_failed", False),
                        "next_handoff_recovery_blocked")
            result = method(agent, *args, **kwargs)
            if derived:
                return result
            if getattr(agent, "_shutdown_requested", False):
                retain_unadmitted(agent)
                return None
            if result is None:
                # REST and guarded refusals are decisions, not deferred executions.
                agent._unadmitted_next_checkpoint = None
            return result
        except Exception as exc:
            if protocol:
                if isinstance(exc, HandoffError):
                    agent._next_handoff_failed = True
                if derived:
                    raise
                try:
                    if not retain_unadmitted(agent):
                        agent._next_handoff_failed = True
                except Exception:
                    agent._next_handoff_failed = True
                    raise
            raise
    return call


def admitted(agent, context):
    """Only the dispatch owning this token can retire its admission checkpoint."""
    saved = getattr(agent, "_unadmitted_next_checkpoint", None)
    if (saved is not None and context.get("_next_admission_token") is not None
            and context["_next_admission_token"] == saved.get("token")):
        agent._unadmitted_next_checkpoint = None
    chain = getattr(agent, "_next_compound_inflight", None)
    if chain is not None and context.get("_next_compound_token") == chain["token"]:
        chain["started"] = True
        if context.get("_next_compound_last"):
            agent._next_compound_inflight = chain["parent"]


def admission_path(state_path):
    return checked(Path(state_path).parent / "runtime/next-admission-unsealed-v1.json")


def validate_admission(body):
    require(set(body) == {"contract", "version", "kind", "process", "state_sha256", "pending_sha256"}
            and body["contract"] == CONTRACT and type(body["version"]) is int
            and body["version"] == HANDOFF_VERSION and body["kind"] == "unsealed_admission",
            "invalid_admission_witness")
    validate_process(body["process"])
    for key in ("state_sha256", "pending_sha256"):
        require(isinstance(body[key], str) and re.fullmatch(r"[0-9a-f]{64}", body[key]),
                "invalid_admission_witness_hash")


def begin_admission(agent):
    """An unsealed admission cannot fall back to an older acknowledged seal."""
    state_path = Path(agent._sovereignty_state_path())
    with transaction(state_path):
        begin_admission_locked(agent)


def begin_admission_locked(agent):
    """Caller holds the sovereignty transaction across this and queue mutation."""
    state_path = Path(agent._sovereignty_state_path())
    history(state_path)
    path = admission_path(state_path)
    process = identity(agent)
    if os.path.lexists(path):
        body = parse(read(path, MAX_STATE))
        validate_admission(body)
        require(body["process"] == process, "unsealed_admission_requires_recovery")
        sync_parent(path.parent)
        confirm_file(path)
        return
    raw = read(state_path, MAX_STATE, missing=b"{}")
    choice = pending(parse(raw))
    path.parent.mkdir(parents=True, exist_ok=True)
    sync_parent(path.parent)
    write_state(path, {"contract": CONTRACT, "version": HANDOFF_VERSION, "kind": "unsealed_admission",
                       "process": process, "state_sha256": digest(raw),
                       "pending_sha256": digest(canonical(choice))})


def write_state(path, value):
    path = checked(path)
    raw = canonical(value) + b"\n"
    require(len(raw) <= MAX_STATE, "sovereignty_state_limit")
    temporary = path.with_name("." + uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_parent(path)
    finally:
        temporary.unlink(missing_ok=True)


def identity(agent):
    row = {"boot_id": agent._agent_boot_id, "pid": agent._agent_pid,
           "started_at": agent._agent_started_at,
           "source_sha256": digest(canonical(agent._agent_inputs_at_start))}
    require(isinstance(row["boot_id"], str) and re.fullmatch(r"[0-9a-f]{32}", row["boot_id"])
            and type(row["pid"]) is int and row["pid"] > 0
            and isinstance(row["started_at"], str) and 0 < len(row["started_at"]) < 128,
            "invalid_handoff_process_identity")
    return row


def pending(state):
    action = state.get("pending_next_action")
    require(action is None or isinstance(action, str) and bool(action), "invalid_pending_choice")
    require(not action or state.get("pending_next_action_status", "pending") == "pending",
            "pending_choice_not_pending")
    require(state.get("choice_envelope_v1") is None or isinstance(state["choice_envelope_v1"], dict),
            "invalid_pending_envelope")
    require(bool(action) or (state.get("pending_next_selection_id") is None
                            and state.get("choice_envelope_v1") is None),
            "orphan_pending_metadata")
    selection = state.get("pending_next_selection_id")
    require(selection is None or isinstance(selection, str) and 0 < len(selection) <= 128,
            "invalid_pending_selection")
    return {key: state[key] for key in PENDING_KEYS if key in state} if action else {}


def stream_path(state_path):
    return checked(Path(state_path).parent / "runtime/next-handoff-v1.jsonl")


def history(state_path):
    raw = read(stream_path(state_path), MAX_HISTORY, missing=b"")
    require(not raw or raw.endswith(b"\n"), "incomplete_handoff_history")
    rows, head = [], None
    for line in raw.splitlines():
        require(len(rows) < MAX_RECORDS, "handoff_record_limit")
        row = parse(line)
        require(set(row) == {"body", "sha256"} and isinstance(row["body"], dict),
                "invalid_handoff_record")
        body = row["body"]
        require(body.get("contract") == CONTRACT and type(body.get("version")) is int
                and body.get("version") == HANDOFF_VERSION
                and body.get("previous") == head
                and type(body.get("sequence")) is int and body.get("sequence") == len(rows) + 1
                and digest(canonical(body)) == row["sha256"], "handoff_history_changed")
        require(body.get("kind") in {"sealed", "restored"}, "unsupported_handoff_record")
        validate_record(body, rows)
        head = row["sha256"]
        rows.append(row)
    return rows, raw


def validate_record(body, rows):
    fields = {"contract", "version", "sequence", "previous", "kind", "process",
              "state_sha256", "pending_sha256", "pending_present"}
    if body["kind"] == "restored":
        fields |= {"seal_sha256", "scheduling_authorized"}
    process = body.get("process")
    require(set(body) == fields,
            "invalid_handoff_record_fields")
    validate_process(process)
    require(type(body["pending_present"]) is bool, "invalid_handoff_record_identity")
    for value in (body["state_sha256"], body["pending_sha256"]):
        require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
                "invalid_handoff_record_hash")
    if body["kind"] == "restored":
        sealed = next((row["body"] for row in rows if row["sha256"] == body["seal_sha256"]), {})
        require(sealed.get("kind") == "sealed" and body["scheduling_authorized"] is False
                and sealed["process"]["boot_id"] != process["boot_id"]
                and all(body[key] == sealed[key] for key in
                        ("state_sha256", "pending_sha256", "pending_present")),
                "invalid_handoff_acknowledgement")


def validate_process(process):
    require(isinstance(process, dict)
            and set(process) == {"boot_id", "pid", "started_at", "source_sha256"},
            "invalid_handoff_record_fields")
    require(type(process["pid"]) is int and process["pid"] > 0
            and isinstance(process["boot_id"], str) and re.fullmatch(r"[0-9a-f]{32}", process["boot_id"])
            and isinstance(process["started_at"], str) and 0 < len(process["started_at"]) < 128,
            "invalid_handoff_record_identity")
    require(isinstance(process["source_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", process["source_sha256"]), "invalid_handoff_record_hash")


def append(state_path, rows, raw, body):
    body = dict(body, contract=CONTRACT, version=HANDOFF_VERSION, sequence=len(rows) + 1,
                previous=rows[-1]["sha256"] if rows else None)
    validate_record(body, rows)
    row = {"body": body, "sha256": digest(canonical(body))}
    line = canonical(row) + b"\n"
    require(len(rows) < MAX_RECORDS and len(raw) + len(line) <= MAX_HISTORY, "handoff_capacity")
    if body["kind"] == "sealed":
        require_restore_capacity(len(rows) + 1, len(raw) + len(line))
    else:
        require(len(line) <= MAX_RESTORE_RECORD_BYTES, "handoff_restore_record_limit")
    path = stream_path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The receipt directory's name must be durable before any receipt can be.
    sync_parent(path.parent)
    require(read(path, MAX_HISTORY, missing=b"") == raw, "handoff_history_changed")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    sync_parent(path)
    return row


def require_restore_capacity(records, byte_count):
    require(records < MAX_RECORDS and byte_count + MAX_RESTORE_RECORD_BYTES <= MAX_HISTORY,
            "handoff_capacity_for_restore")


def public(row):
    return dict(row["body"], record_sha256=row["sha256"])


def confirm_durable(state_path):
    confirm_file(stream_path(state_path))


def confirm_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_parent(path)


def seal(agent):
    require(not getattr(agent, "_next_handoff_failed", False), "next_handoff_recovery_blocked")
    require(getattr(agent, "_unadmitted_next_checkpoint", None) is None,
            "unresolved_unadmitted_checkpoint")
    require(getattr(agent, "_next_compound_inflight", None) is None,
            "unresolved_compound_admission")
    path = Path(agent._sovereignty_state_path())
    with transaction(path):
        witness = admission_path(path)
        if os.path.lexists(witness):
            marker = parse(read(witness, MAX_STATE))
            validate_admission(marker)
            require(marker["process"] == identity(agent),
                    "unsealed_admission_requires_recovery")
        rows, raw = history(path)
        state_raw = read(path, MAX_STATE, missing=b"{}")
        state = parse(state_raw)
        choice = pending(state)
        require(state.get("pending_next_action") == getattr(agent, "_pending_next_action", None)
                and (not choice or (
                    state.get("pending_next_selection_id") == getattr(agent, "_pending_next_selection_id", None)
                    and state.get("choice_envelope_v1") == getattr(agent, "_pending_choice_envelope_v1", None))),
                "pending_memory_checkpoint_mismatch")
        require(bool(choice) or (getattr(agent, "_pending_next_selection_id", None) is None
                                and getattr(agent, "_pending_choice_envelope_v1", None) is None),
                "orphan_memory_pending_metadata")
        body = dict(kind="sealed", process=identity(agent), state_sha256=digest(state_raw),
                    pending_sha256=digest(canonical(choice)), pending_present=bool(choice))
        previous = next((r for r in reversed(rows) if r["body"].get("kind") == "sealed"
                         and r["body"].get("process", {}).get("boot_id") == agent._agent_boot_id), None)
        if previous:
            require(all(previous["body"].get(k) == v for k, v in body.items()), "conflicting_drain_retry")
            if not any(r["body"].get("seal_sha256") == previous["sha256"] for r in rows):
                require_restore_capacity(len(rows), len(raw))
            confirm_durable(path)
            receipt = public(previous)
        else:
            receipt = public(append(path, rows, raw, body))
        if os.path.lexists(witness):
            witness.unlink()
        sync_parent(witness)
        return receipt


def restore(agent):
    """Assign the exact queue before durable acknowledgement; no state rewrite."""
    path = Path(agent._sovereignty_state_path())
    with transaction(path):
        require(not os.path.lexists(admission_path(path)), "unsealed_admission_requires_recovery")
        if not os.path.lexists(stream_path(path)):
            from minime_autonomy.maintenance_next_legacy import restore_locked
            return restore_locked(agent)
        rows, raw = history(path)
        sealed = next((r for r in reversed(rows) if r["body"]["kind"] == "sealed"), None)
        require(sealed is not None, "missing_drain_seal")
        old = sealed["body"]
        acknowledgements = [r for r in rows if r["body"].get("kind") == "restored"
                            and r["body"].get("seal_sha256") == sealed["sha256"]]
        state_raw = read(path, MAX_STATE, missing=b"{}")
        state = parse(state_raw)
        choice = pending(state)
        if digest(state_raw) != old.get("state_sha256"):
            require(bool(acknowledgements), "unacknowledged_checkpoint_changed")
            return None  # Newer queue state is authoritative; never replay the old seal.
        require(digest(canonical(choice)) == old.get("pending_sha256")
                and bool(choice) == old.get("pending_present"), "pending_seal_mismatch")
        process = identity(agent)
        require(process["boot_id"] != old.get("process", {}).get("boot_id"), "same_process_restore")
        agent._pending_next_action = state.get("pending_next_action")
        agent._pending_next_selection_id = state.get("pending_next_selection_id") if choice else None
        agent._pending_choice_envelope_v1 = state.get("choice_envelope_v1") if choice else None
        body = dict(kind="restored", process=process, seal_sha256=sealed["sha256"],
                    state_sha256=digest(state_raw), pending_sha256=digest(canonical(choice)),
                    pending_present=bool(choice), scheduling_authorized=False)
        previous = next((r for r in acknowledgements if r["body"].get("process") == process), None)
        if previous:
            confirm_durable(path)
        receipt = previous or append(path, rows, raw, body)
        return public(receipt)


def retain_unadmitted(agent):
    """CAS the exact pre-admission tuple, never replace a newer authored choice."""
    chain = getattr(agent, "_next_compound_inflight", None)
    require(chain is None or not chain["started"], "partial_compound_admission_unknown")
    saved = getattr(agent, "_unadmitted_next_checkpoint", None)
    if saved is None:
        return False
    require(not saved.get("unproven"), "unproven_unadmitted_choice")
    path = Path(agent._sovereignty_state_path())
    with transaction(path):
        raw = read(path, MAX_STATE)
        state = parse(raw)
        if not state.get("pending_next_action"):
            require(digest(raw) == saved["cleared_sha256"], "unadmitted_checkpoint_changed")
            for key in PENDING_KEYS:
                state.pop(key, None)
            state.update(saved["pending"])
            write_state(path, state)
        choice = pending(state)
        agent._pending_next_action = state.get("pending_next_action")
        agent._pending_next_selection_id = state.get("pending_next_selection_id") if choice else None
        agent._pending_choice_envelope_v1 = state.get("choice_envelope_v1") if choice else None
        agent._unadmitted_next_checkpoint = None
        if chain is not None:
            agent._next_compound_inflight = chain["parent"]
        return True
