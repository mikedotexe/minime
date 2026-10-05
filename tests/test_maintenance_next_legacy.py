"""The first legacy transition preserves provenance and exact queued work."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from minime_autonomy import maintenance_next as m, maintenance_next_legacy as legacy
from minime_autonomy.deployment import source_inputs
from tests.test_maintenance_next import agent, checkpoint, start_once


def test_deployment_inventory_binds_both_maintenance_modules():
    root = Path(__file__).resolve().parents[1]
    inventory = source_inputs(root)
    for name in ("maintenance_next.py", "maintenance_next_legacy.py"):
        relative = f"minime_autonomy/{name}"
        assert inventory[relative] == m.digest((root / relative).read_bytes())


def prepare(root, choice='WRITE CONTINUE d1 "private synthetic NEXT: REST"'):
    new = agent(root, choice)
    checkpoint(new)
    path = Path(new._sovereignty_state_path())
    raw = path.read_bytes()
    state = m.parse(raw)
    imported = {"schema": legacy.IMPORT_SCHEMA, "version": 1, "owner": "b" * 32,
                "old_process": {"pid": 2, "started_at": "legacy start", "source_sha256": "c" * 64},
                "old_status_sha256": "d" * 64,
                "expected_source_sha256": m.identity(new)["source_sha256"],
                "state_sha256": m.digest(raw), "pending_sha256": m.digest(m.canonical(m.pending(state))),
                "pending_present": bool(choice), "runtime_seal_available": False,
                "execution_confirmed": False}
    legacy.immutable(legacy.paths(path)[0], imported)
    new._pending_next_action = None
    new._pending_next_selection_id = None
    new._pending_choice_envelope_v1 = None
    return new, imported, raw


def test_real_start_preserves_old_choice_before_profile_restore_and_boot_reflection(tmp_path):
    new, imported, raw = prepare(tmp_path)
    new._recover_activity_choice = Mock(side_effect=AssertionError("competing reflection"))
    start_once(new)
    assert new._pending_next_action == json.loads(raw)["pending_next_action"]
    assert new._pending_next_selection_id == json.loads(raw)["pending_next_selection_id"]
    assert Path(new._sovereignty_state_path()).read_bytes() == raw
    ack = new._next_handoff_restore
    assert ack["kind"] == "legacy_restored"
    assert ack["runtime_seal_available"] is False
    assert ack["scheduling_authorized"] is False
    assert ack["execution_confirmed"] is False
    assert not m.stream_path(new._sovereignty_state_path()).exists()
    assert "private synthetic" not in legacy.paths(new._sovereignty_state_path())[1].read_text()


def test_same_boot_retry_then_normal_graceful_seal(tmp_path):
    new, _, _ = prepare(tmp_path)
    first = m.restore(new)
    assert m.restore(new) == first
    m.seal(new)
    replacement = agent(tmp_path)
    assert m.restore(replacement)["kind"] == "restored"
    assert replacement._pending_next_action == new._pending_next_action


@pytest.mark.parametrize("change", ["source", "state", "other_boot", "admission", "corrupt_ack"])
def test_changed_or_uncertain_legacy_transition_refuses_without_rewriting(tmp_path, change):
    new, _, _ = prepare(tmp_path)
    state = Path(new._sovereignty_state_path())
    if change == "source":
        new._agent_inputs_at_start = {"runtime.py": "e" * 64}
    elif change == "state":
        m.write_state(state, {"pending_next_action": "REST"})
    elif change == "other_boot":
        m.restore(new)
        new = agent(tmp_path)
    elif change == "admission":
        m.begin_admission(new)
    else:
        legacy.paths(state)[1].write_bytes(b'{"schema":')
    before = state.read_bytes()
    with pytest.raises(m.HandoffError):
        m.restore(new)
    assert state.read_bytes() == before


def test_ack_disk_failure_blocks_actual_start(tmp_path):
    new, _, raw = prepare(tmp_path)
    with patch.object(legacy.os, "fsync", side_effect=OSError("synthetic ENOSPC")):
        with pytest.raises(OSError):
            start_once(new)
    assert new._lifecycle_phase == "recovery_blocked"
    assert Path(new._sovereignty_state_path()).read_bytes() == raw


def test_no_pending_choice_acknowledged_without_inventing_one(tmp_path):
    new, _, _ = prepare(tmp_path, None)
    assert m.restore(new)["pending_present"] is False
    assert new._pending_next_action is None


def test_orphan_acknowledgement_is_not_ignored(tmp_path):
    new, _, _ = prepare(tmp_path)
    m.restore(new)
    legacy.paths(new._sovereignty_state_path())[0].unlink()
    with pytest.raises(m.HandoffError, match="orphan_legacy"):
        m.restore(new)
