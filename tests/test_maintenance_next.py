"""Synthetic graceful continuation, including the real runtime boundaries."""
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
import autonomous_agent as aa
from minime_autonomy import maintenance_next as m


def agent(root, choice=None):
    value = object.__new__(aa.AutonomousAgent)
    value._agent_boot_id = uuid4().hex
    value._agent_pid = os.getpid()
    value._agent_started_at = "2026-10-05T12:00:00"
    value._agent_inputs_at_start = {"runtime.py": "a" * 64}
    value._pending_next_action = choice
    value._pending_next_selection_id = "selection-1" if choice else None
    value._pending_choice_envelope_v1 = {"exact": "private synthetic context"} if choice else None
    value._sovereignty_state_path = lambda: str(root / "sovereignty_state.json")
    value._llm_job_threads = []
    value._stop_event = threading.Event()
    value._write_source_status = Mock()
    value.session_id = 900
    value.running = False
    value._hard_recovery_reset = True
    value._recent_next_actions = []
    value._stable_core_reflective_only = lambda: True
    return value


def checkpoint(value):
    state = {"session_id": 1, "pending_next_action": value._pending_next_action}
    if value._pending_next_action:
        state.update(pending_next_selection_id=value._pending_next_selection_id,
                     choice_envelope_v1=value._pending_choice_envelope_v1,
                     pending_next_action_status="pending",
                     pending_next_action_updated_at="2020-01-01T00:00:00",
                     pending_next_action_update_reason="authored choice")
    m.write_state(Path(value._sovereignty_state_path()), state)
    return state


def start_once(value):
    value.check_interval = 0
    value._check_source_reload_required = Mock()
    value._apply_pending_next_override_if_present = Mock()
    value._refresh_session_context = Mock()
    value._get_latest_spectral_state = lambda: value.stop()
    value.start()


def test_worker_finalizer_next_restores_before_profile_gate_without_timestamp_refresh(tmp_path):
    old = agent(tmp_path)
    checkpoint(old)
    release = threading.Event()

    def finalize():
        release.wait(2)
        old._pending_next_action = 'WRITE REVISE "NEXT: REST" synthetic \u00e9'
        old._pending_next_selection_id = "finalizer-choice"
        old._pending_choice_envelope_v1 = {"from": "finalizer", "exact": "private text"}
        checkpoint(old)

    thread = threading.Thread(target=finalize)
    old._llm_job_threads.append(thread)
    thread.start()
    old.stop()
    release.set()
    old.wait_for_llm_jobs()
    before = Path(old._sovereignty_state_path()).read_bytes()
    new = agent(tmp_path)
    new._recover_activity_choice = Mock(side_effect=AssertionError("competing boot work"))
    start_once(new)
    assert new._pending_next_action == old._pending_next_action
    assert new._pending_next_selection_id == old._pending_next_selection_id
    assert new._pending_choice_envelope_v1 == old._pending_choice_envelope_v1
    assert Path(old._sovereignty_state_path()).read_bytes() == before
    receipt = new._next_handoff_restore
    assert receipt["seal_sha256"] == old._next_handoff_seal["record_sha256"]
    assert receipt["process"]["boot_id"] == new._agent_boot_id
    assert receipt["scheduling_authorized"] is False
    assert "private text" not in m.stream_path(old._sovereignty_state_path()).read_text()


def test_boot_ack_before_generation_and_no_inference_from_storage(tmp_path):
    old = agent(tmp_path, "REST")
    checkpoint(old)
    old.wait_for_llm_jobs()
    new = agent(tmp_path)
    events = []
    original = new._restore_sovereignty_state

    def restored():
        assert m.history(new._sovereignty_state_path())[0][-1]["body"]["kind"] == "restored"
        events.append("acknowledged")
        original()

    new._restore_sovereignty_state = restored
    new._query_llm = Mock(side_effect=AssertionError("unrequested inference"))
    start_once(new)
    assert events == ["acknowledged"]
    assert new._pending_next_action == "REST"


@pytest.mark.parametrize("stage", ["seal", "restore"])
def test_fsync_failure_never_publishes_drained_or_starts_scheduling(tmp_path, stage):
    old = agent(tmp_path, "JOURNAL")
    checkpoint(old)
    target = old
    if stage == "restore":
        old.wait_for_llm_jobs()
        target = agent(tmp_path)
        target._verify_sovereignty = Mock(side_effect=AssertionError("admitted after failure"))
    with patch.object(m.os, "fsync", side_effect=OSError("synthetic disk failure")):
        with pytest.raises(OSError):
            target.wait_for_llm_jobs() if stage == "seal" else start_once(target)
    assert target._lifecycle_phase == "recovery_blocked"
    assert not any(call.args == ("drained",) for call in target._write_source_status.call_args_list)


def test_ack_retry_and_crash_before_admission_preserve_exact_choice(tmp_path):
    old = agent(tmp_path, "SELF_STUDY CONTINUE")
    checkpoint(old)
    sealed = m.seal(old)
    assert m.seal(old) == sealed
    new = agent(tmp_path)
    first = m.restore(new)
    assert m.restore(new) == first
    restarted = agent(tmp_path)
    next_ack = m.restore(restarted)
    assert next_ack["seal_sha256"] == first["seal_sha256"]
    assert next_ack["process"] != first["process"]
    assert restarted._pending_next_action == old._pending_next_action


def test_consumed_choice_never_replayed_from_acknowledged_old_checkpoint(tmp_path):
    old = agent(tmp_path, "JOURNAL")
    checkpoint(old)
    m.seal(old)
    m.restore(agent(tmp_path))
    m.write_state(Path(old._sovereignty_state_path()), {"pending_next_action_status": "cleared"})
    new = agent(tmp_path)
    assert m.restore(new) is None
    assert new._pending_next_action is None


def test_changed_unacknowledged_state_is_preserved_and_blocks_start(tmp_path):
    old = agent(tmp_path, "JOURNAL")
    checkpoint(old)
    m.seal(old)
    changed = b'{"pending_next_action":"REST"}\n'
    Path(old._sovereignty_state_path()).write_bytes(changed)
    new = agent(tmp_path)
    with pytest.raises(m.HandoffError, match="unacknowledged_checkpoint_changed"):
        start_once(new)
    assert Path(old._sovereignty_state_path()).read_bytes() == changed
    with pytest.raises(m.HandoffError):
        new.wait_for_llm_jobs()
    assert len(m.history(new._sovereignty_state_path())[0]) == 1


@pytest.mark.parametrize("raw", [b'{', b'{}\n', b'{"body":{},"body":{}}\n'])
def test_corrupt_history_preserved(tmp_path, raw):
    old = agent(tmp_path, "REST")
    checkpoint(old)
    path = m.stream_path(old._sovereignty_state_path())
    path.parent.mkdir()
    path.write_bytes(raw)
    with pytest.raises(m.HandoffError):
        m.restore(agent(tmp_path))
    assert path.read_bytes() == raw


def test_memory_disk_conflict_cannot_claim_successful_drain(tmp_path):
    old = agent(tmp_path, "JOURNAL")
    checkpoint(old)
    old._pending_next_action = "REST"
    with pytest.raises(m.HandoffError, match="pending_memory_checkpoint_mismatch"):
        old.wait_for_llm_jobs()
    assert old._lifecycle_phase == "recovery_blocked"
    assert not m.stream_path(old._sovereignty_state_path()).exists()


def test_capacity_limit_refuses_without_rewriting_history(tmp_path, monkeypatch):
    old = agent(tmp_path, "REST")
    checkpoint(old)
    m.seal(old)
    path = m.stream_path(old._sovereignty_state_path())
    before = path.read_bytes()
    monkeypatch.setattr(m, "MAX_RECORDS", 1)
    with pytest.raises(m.HandoffError, match="handoff_capacity"):
        m.restore(agent(tmp_path))
    assert path.read_bytes() == before


def test_foreign_or_linked_state_is_not_rewritten(tmp_path):
    old = agent(tmp_path, "REST")
    checkpoint(old)
    path = Path(old._sovereignty_state_path())
    other = tmp_path / "foreign"
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(m.HandoffError, match="linked"):
        m.seal(old)


def test_control_save_preserves_original_pending_timestamp_and_selection(tmp_path):
    old = agent(tmp_path, "JOURNAL")
    before = checkpoint(old)
    old.cycle_count = 12
    old._save_sovereignty_state({"kind": "control"}, "synthetic control mirror")
    state = json.loads(Path(old._sovereignty_state_path()).read_bytes())
    for key in m.PENDING_KEYS:
        assert state.get(key) == before.get(key)


def test_state_writer_rejects_corruption_without_truncation(tmp_path):
    old = agent(tmp_path, "REST")
    path = Path(old._sovereignty_state_path())
    path.write_bytes(b'{"pending_next_action":')
    with pytest.raises(m.HandoffError):
        old._persist_pending_next_action("JOURNAL", "new choice")
    assert path.read_bytes() == b'{"pending_next_action":'


def test_same_owner_writers_serialize_threads(tmp_path):
    path = tmp_path / "sovereignty_state.json"
    m.write_state(path, {"count": 0})
    errors = []

    def update():
        try:
            for _ in range(15):
                with m.transaction(path):
                    state = m.parse(m.read(path, m.MAX_STATE))
                    state["count"] += 1
                    m.write_state(path, state)
        except Exception as error:
            errors.append(error)

    workers = [threading.Thread(target=update) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert not worker.is_alive()
    assert not errors
    assert m.parse(m.read(path, m.MAX_STATE))["count"] == 60


def clear_for_admission(value, root):
    action = value._pending_next_action
    selection = value._pending_next_selection_id
    value._pending_next_action = None
    with patch.object(aa, "WORKSPACE_DIR", root):
        value._persist_pending_next_action(None, reason="selected_for_admission",
                                          expected_action=action, expected_selection_id=selection)


def test_stop_after_queue_clear_preserves_complete_original_tuple(tmp_path):
    value = agent(tmp_path, 'WRITE REVISE "NEXT: REST"')
    original = checkpoint(value)
    clear_for_admission(value, tmp_path)
    value.stop()
    value._execute_action("self_study", {})
    value.wait_for_llm_jobs()
    restored = m.parse(m.read(value._sovereignty_state_path(), m.MAX_STATE))
    assert m.pending(restored) == m.pending(original)
    new = agent(tmp_path)
    assert m.restore(new)["pending_present"]
    assert new._pending_choice_envelope_v1 == value._pending_choice_envelope_v1


def test_stop_during_context_consumption_cannot_fall_through_to_execution(tmp_path):
    value = agent(tmp_path, "SELF_STUDY CONTINUE")
    original = checkpoint(value)
    clear_for_admission(value, tmp_path)
    value.running = True

    def consume(action):
        value.stop()
        return {"raw_next": "SELF_STUDY CONTINUE"}

    value._consume_action_continuity_context = consume
    value._queue_llm_action_job = Mock(side_effect=AssertionError("queued after stop"))
    value._low_fill_guard_status = Mock(side_effect=AssertionError("executed after stop"))
    value._execute_action("self_study", {})
    assert m.pending(m.parse(m.read(value._sovereignty_state_path(), m.MAX_STATE))) == m.pending(original)


def test_same_text_new_selection_cannot_be_cleared_by_stale_decision(tmp_path):
    value = agent(tmp_path, "JOURNAL")
    state = checkpoint(value)
    state["pending_next_selection_id"] = "newer-authored-selection"
    m.write_state(Path(value._sovereignty_state_path()), state)
    before = Path(value._sovereignty_state_path()).read_bytes()
    with pytest.raises(m.HandoffError, match="pending_selection_changed"):
        clear_for_admission(value, tmp_path)
    assert Path(value._sovereignty_state_path()).read_bytes() == before
    with pytest.raises(m.HandoffError, match="recovery_blocked"):
        value.wait_for_llm_jobs()


def test_unadmitted_recovery_does_not_overwrite_newer_choice(tmp_path):
    value = agent(tmp_path, "JOURNAL")
    checkpoint(value)
    clear_for_admission(value, tmp_path)
    other = agent(tmp_path, "REST")
    checkpoint(other)
    before = Path(value._sovereignty_state_path()).read_bytes()
    value._retain_unadmitted_choice()
    assert value._pending_next_action == "REST"
    assert Path(value._sovereignty_state_path()).read_bytes() == before


def test_honored_rest_is_not_requeued_by_later_shutdown(tmp_path):
    value = agent(tmp_path, "REST")
    checkpoint(value)

    @m.decision
    def decide(agent):
        clear_for_admission(agent, tmp_path)
        agent._pending_choice_envelope_v1 = None
        return None

    assert decide(value) is None
    assert value._unadmitted_next_checkpoint is None
    value.stop()
    value.wait_for_llm_jobs()
    assert not value._next_handoff_seal["pending_present"]


@pytest.mark.parametrize("prior_ack", [False, True])
def test_failed_queue_flush_cannot_bootstrap_via_an_old_seal_or_legacy_fallback(tmp_path, prior_ack):
    value = agent(tmp_path, "JOURNAL")
    original = checkpoint(value)
    if prior_ack:
        m.seal(value)
        value = agent(tmp_path)
        m.restore(value)
    path = Path(value._sovereignty_state_path())
    sync_parent = m.sync_parent

    def fail_queue_flush(target):
        if Path(target).name == path.name:
            raise OSError("synthetic queue directory flush failure")
        sync_parent(target)

    with patch.object(m, "sync_parent", side_effect=fail_queue_flush):
        with pytest.raises(OSError, match="queue directory flush"):
            clear_for_admission(value, tmp_path)
    assert value._next_handoff_failed
    assert value._unadmitted_next_checkpoint["pending"] == m.pending(original)
    marker = m.admission_path(path)
    before = marker.read_bytes()
    with pytest.raises(m.HandoffError, match="unsealed_admission_requires_recovery"):
        m.restore(agent(tmp_path))
    assert marker.read_bytes() == before
    # Once I/O succeeds, the original process can preserve its exact tuple;
    # this is not permission for a new process to guess whether work ran.
    assert m.retain_unadmitted(value)
    assert m.pending(m.parse(path.read_bytes())) == m.pending(original)
    with pytest.raises(m.HandoffError, match="recovery_blocked"):
        m.seal(value)


def test_admission_witness_failure_precedes_any_queue_replacement(tmp_path):
    value = agent(tmp_path, "JOURNAL")
    checkpoint(value)
    path = Path(value._sovereignty_state_path())
    before = path.read_bytes()
    write_state = m.write_state

    def fail_marker(target, state):
        if Path(target).name == m.admission_path(path).name:
            raise OSError("synthetic admission witness failure")
        return write_state(target, state)

    with patch.object(m, "write_state", side_effect=fail_marker):
        with pytest.raises(OSError, match="admission witness"):
            clear_for_admission(value, tmp_path)
    assert path.read_bytes() == before
    assert not m.admission_path(path).exists()


def test_regular_admission_needs_a_clean_seal_before_new_process_startup(tmp_path):
    value = agent(tmp_path, "JOURNAL")
    checkpoint(value)
    clear_for_admission(value, tmp_path)
    m.admitted(value, {"_next_admission_token": value._unadmitted_next_checkpoint["token"]})
    with pytest.raises(m.HandoffError, match="unsealed_admission_requires_recovery"):
        m.restore(agent(tmp_path))
    value._pending_choice_envelope_v1 = None
    value.wait_for_llm_jobs()
    assert not m.admission_path(value._sovereignty_state_path()).exists()
    assert m.restore(agent(tmp_path))["pending_present"] is False


def test_shutdown_decision_retains_choice_before_return(tmp_path):
    value = agent(tmp_path, "JOURNAL")
    original = checkpoint(value)

    @m.decision
    def decide(agent):
        clear_for_admission(agent, tmp_path)
        agent.stop()
        return "journal_pressure"

    assert decide(value) is None
    assert m.pending(m.parse(m.read(value._sovereignty_state_path(), m.MAX_STATE))) == m.pending(original)


def test_paired_restart_verifier_accepts_real_runtime_receipts(tmp_path):
    import importlib.util
    astrid = Path(os.environ.get("ASTRID_SOURCE_ROOT", str(Path(__file__).resolve().parents[2] / "astrid")))
    spec = importlib.util.spec_from_file_location("paired_next_proof", astrid / "scripts/minime_next_handoff.py")
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    old = agent(tmp_path, "WRITE CONTINUE")
    checkpoint(old)
    old.wait_for_llm_jobs()
    sealed = proof.verify_seal(tmp_path, m.identity(old), dict(
        next_handoff_contract=m.CONTRACT, boot_id=old._agent_boot_id, pid=old._agent_pid,
        started_at=old._agent_started_at, source_inputs_at_start=old._agent_inputs_at_start,
        next_handoff_seal=old._next_handoff_seal))
    assert sealed["pending_present"] is True
    new = agent(tmp_path)
    start_once(new)
    status = dict(next_handoff_contract=m.CONTRACT, boot_id=new._agent_boot_id,
                  pid=new._agent_pid, started_at=new._agent_started_at,
                  source_inputs_at_start=new._agent_inputs_at_start,
                  next_handoff_restore=new._next_handoff_restore)
    verified = proof.verify_restore(tmp_path, m.identity(old), status, new._agent_inputs_at_start)
    assert verified["pending_present"] is True
    assert verified["execution_confirmed"] is False
