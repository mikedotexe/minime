"""One-time operator-observed legacy queue import, not a runtime drain seal.

Only a stopped-state transition tool creates the import. Startup acknowledges
the exact unchanged queue before scheduling. Neither receipt contains prose.
"""
import os
from pathlib import Path
import re

from minime_autonomy import maintenance_next as core

LEGACY_HANDOFF_VERSION = 1
IMPORT_SCHEMA = "minime_next_legacy_import_v1"
ACK_SCHEMA = "minime_next_legacy_restored_v1"
MAX_RECEIPT = 65536


def paths(state_path):
    root = core.checked(Path(state_path).parent / "runtime")
    return root / "next-legacy-import-v1.json", root / "next-legacy-restored-v1.json"


def validate_import(body):
    fields = {"schema", "version", "owner", "old_process", "old_status_sha256",
              "expected_source_sha256", "state_sha256", "pending_sha256", "pending_present",
              "runtime_seal_available", "execution_confirmed"}
    core.require(set(body) == fields and body["schema"] == IMPORT_SCHEMA
                 and type(body["version"]) is int and body["version"] == LEGACY_HANDOFF_VERSION
                 and isinstance(body["owner"], str) and re.fullmatch(r"[0-9a-f]{32}", body["owner"])
                 and type(body["pending_present"]) is bool
                 and body["runtime_seal_available"] is False and body["execution_confirmed"] is False,
                 "invalid_legacy_import")
    old = body["old_process"]
    core.require(isinstance(old, dict) and set(old) == {"pid", "started_at", "source_sha256"}
                 and type(old["pid"]) is int and old["pid"] > 1
                 and isinstance(old["started_at"], str) and 0 < len(old["started_at"]) < 128,
                 "invalid_legacy_process")
    for value in (old["source_sha256"], *(body[k] for k in (
            "old_status_sha256", "expected_source_sha256", "state_sha256", "pending_sha256"))):
        core.require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
                     "invalid_legacy_hash")


def immutable(path, body):
    """No replacement, truncation, or silent repair after an interrupted write."""
    raw = core.canonical(body) + b"\n"
    core.require(len(raw) <= MAX_RECEIPT, "legacy_receipt_capacity")
    path = core.checked(path)
    if os.path.lexists(path):
        core.require(core.read(path, MAX_RECEIPT) == raw, "conflicting_legacy_receipt")
        core.confirm_file(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    core.sync_parent(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    core.sync_parent(path)


def read_import(state_path):
    path, _ = paths(state_path)
    raw = core.read(path, MAX_RECEIPT)
    body = core.parse(raw)
    validate_import(body)
    return body, core.digest(raw)


def restore_locked(agent):
    """Called under the ordinary queue lock when no native seal stream exists."""
    state_path = Path(agent._sovereignty_state_path())
    path, ack_path = paths(state_path)
    if not os.path.lexists(path):
        core.require(not os.path.lexists(ack_path), "orphan_legacy_acknowledgement")
        return None
    imported, import_hash = read_import(state_path)
    process = core.identity(agent)
    core.require(process["source_sha256"] == imported["expected_source_sha256"]
                 and process["pid"] != imported["old_process"]["pid"], "legacy_replacement_identity_changed")
    raw = core.read(state_path, core.MAX_STATE)
    state = core.parse(raw)
    choice = core.pending(state)
    core.require(core.digest(raw) == imported["state_sha256"]
                 and core.digest(core.canonical(choice)) == imported["pending_sha256"]
                 and bool(choice) == imported["pending_present"], "legacy_checkpoint_changed")
    receipt = {"schema": ACK_SCHEMA, "version": LEGACY_HANDOFF_VERSION,
               "kind": "legacy_restored", "import_sha256": import_hash, "process": process,
               "state_sha256": imported["state_sha256"], "pending_sha256": imported["pending_sha256"],
               "pending_present": bool(choice), "runtime_seal_available": False,
               "scheduling_authorized": False, "execution_confirmed": False}
    # Identical retry in the same boot is durable; another boot requires a
    # normal graceful seal or explicit recovery, never an automatic legacy replay.
    if os.path.lexists(ack_path):
        core.require(core.parse(core.read(ack_path, MAX_RECEIPT)) == receipt,
                     "legacy_acknowledged_restart_requires_recovery")
    agent._pending_next_action = state.get("pending_next_action")
    agent._pending_next_selection_id = state.get("pending_next_selection_id") if choice else None
    agent._pending_choice_envelope_v1 = state.get("choice_envelope_v1") if choice else None
    immutable(ack_path, receipt)
    return receipt
