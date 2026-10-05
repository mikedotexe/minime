"""Independent synthetic NEXT receipt durability and corruption boundaries."""

import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from minime_autonomy import maintenance_next as maintenance


def agent(root, action=None):
    return SimpleNamespace(
        _agent_boot_id=uuid4().hex,
        _agent_pid=os.getpid(),
        _agent_started_at="2026-10-05T12:00:00",
        _agent_inputs_at_start={"runtime.py": "a" * 64},
        _pending_next_action=action,
        _pending_next_selection_id="selection-A" if action else None,
        _pending_choice_envelope_v1={"source": "synthetic", "nested": [1, "\u00e9"]} if action else None,
        _sovereignty_state_path=lambda: str(root / "sovereignty_state.json"),
    )


def checkpoint(value):
    state = {"session_id": 1, "pending_next_action": value._pending_next_action}
    if value._pending_next_action:
        state.update(
            pending_next_selection_id=value._pending_next_selection_id,
            choice_envelope_v1=value._pending_choice_envelope_v1,
            pending_next_action_status="pending",
            pending_next_action_updated_at="2020-01-01T00:00:00",
            pending_next_action_update_reason="synthetic authored choice",
        )
    path = Path(value._sovereignty_state_path())
    maintenance.write_state(path, state)
    return path


def acknowledged(root):
    old = agent(root, "WRITE CONTINUE")
    path = checkpoint(old)
    maintenance.seal(old)
    maintenance.restore(agent(root))
    return old, path


@pytest.mark.parametrize("operation", ["seal", "restore"])
@pytest.mark.parametrize("boundary", ["file", "directory"])
def test_visible_receipt_retry_requires_successful_file_and_parent_sync(
    tmp_path, monkeypatch, operation, boundary,
):
    old = agent(tmp_path, "WRITE CONTINUE")
    path = checkpoint(old)
    state_before = path.read_bytes()
    target = old
    if operation == "restore":
        maintenance.seal(old)
        target = agent(tmp_path)
    action = getattr(maintenance, operation)
    history_path = maintenance.stream_path(path)
    original_fsync = os.fsync
    failed_calls = []

    def kind(fd):
        return "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"

    def fail_sync(fd):
        current = kind(fd)
        failed_calls.append(current)
        receipt_directory = current == "directory" and os.fstat(fd).st_ino == history_path.parent.stat().st_ino
        if current == boundary and (boundary == "file" or receipt_directory):
            raise OSError("synthetic receipt sync failure")
        return original_fsync(fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(maintenance.os, "fsync", fail_sync)
        with pytest.raises(OSError, match="synthetic receipt sync failure"):
            action(target)
        visible = history_path.read_bytes()
        rows, _ = maintenance.history(path)
        assert len(rows) == (1 if operation == "seal" else 2)
        assert visible.endswith(b"\n")
        if operation == "restore":
            assert target._pending_next_action == old._pending_next_action
            assert target._pending_next_selection_id == old._pending_next_selection_id
            assert target._pending_choice_envelope_v1 == old._pending_choice_envelope_v1
        for _ in range(3):
            failed_calls.clear()
            with pytest.raises(OSError, match="synthetic receipt sync failure"):
                action(target)
            assert boundary in failed_calls
            assert history_path.read_bytes() == visible
            assert path.read_bytes() == state_before

    successful_calls = []

    def observe_sync(fd):
        successful_calls.append(kind(fd))
        return original_fsync(fd)

    monkeypatch.setattr(maintenance.os, "fsync", observe_sync)
    receipt = action(target)
    assert successful_calls == ["file", "directory"] + (["directory"] if operation == "seal" else [])
    assert receipt["record_sha256"] == rows[-1]["sha256"]
    assert history_path.read_bytes() == visible
    assert path.read_bytes() == state_before


@pytest.mark.parametrize("raw", [
    b'{"pending_next_action":',
    b'[]',
    b'{"pending_next_action":"REST","pending_next_action":"WRITE CONTINUE"}',
    b'{"foreign_future_field":NaN}',
    b'{"pending_next_action":7}',
    b'{"pending_next_action":"REST","choice_envelope_v1":[]}',
    b'{"pending_next_action":"REST","pending_next_action_status":"cleared"}',
])
def test_acknowledged_changed_state_is_validated_before_legacy_fallback(tmp_path, raw):
    _, path = acknowledged(tmp_path)
    history_path = maintenance.stream_path(path)
    history_before = history_path.read_bytes()
    path.write_bytes(raw)
    new = agent(tmp_path)

    with pytest.raises(maintenance.HandoffError):
        maintenance.restore(new)

    assert new._pending_next_action is None
    assert new._pending_next_selection_id is None
    assert new._pending_choice_envelope_v1 is None
    assert path.read_bytes() == raw
    assert history_path.read_bytes() == history_before


@pytest.mark.parametrize("operation", ["seal", "restore"])
@pytest.mark.parametrize("tail", [b'{', b'{}\n', b'{"body":{},"body":{}}\n'])
def test_corrupt_tail_after_valid_ack_is_neither_replayed_nor_truncated(tmp_path, operation, tail):
    old, path = acknowledged(tmp_path)
    state_before = path.read_bytes()
    history_path = maintenance.stream_path(path)
    damaged = history_path.read_bytes() + tail
    history_path.write_bytes(damaged)

    with pytest.raises(maintenance.HandoffError):
        getattr(maintenance, operation)(old if operation == "seal" else agent(tmp_path))

    assert history_path.read_bytes() == damaged
    assert path.read_bytes() == state_before


@pytest.mark.parametrize("damage", ["digest", "seal_reference"])
@pytest.mark.parametrize("changed_state", [False, True])
def test_corrupt_ack_blocks_restore_including_changed_state_fallback(tmp_path, damage, changed_state):
    _, path = acknowledged(tmp_path)
    history_path = maintenance.stream_path(path)
    lines = history_path.read_bytes().splitlines(keepends=True)
    ack = json.loads(lines[-1])
    if damage == "digest":
        ack["sha256"] = "0" * 64
    else:
        ack["body"]["seal_sha256"] = "0" * 64
    damaged = b"".join(lines[:-1]) + maintenance.canonical(ack) + b"\n"
    history_path.write_bytes(damaged)
    if changed_state:
        maintenance.write_state(path, {"pending_next_action_status": "cleared"})
    state_before = path.read_bytes()
    new = agent(tmp_path)

    with pytest.raises(maintenance.HandoffError, match="handoff_history_changed"):
        maintenance.restore(new)

    assert new._pending_next_action is None
    assert new._pending_next_selection_id is None
    assert new._pending_choice_envelope_v1 is None
    assert history_path.read_bytes() == damaged
    assert path.read_bytes() == state_before


@pytest.mark.parametrize("field,value", [
    ("pending_next_selection_id", "orphan-selection"),
    ("choice_envelope_v1", {"source": "orphan-envelope"}),
])
@pytest.mark.parametrize("location", ["disk", "memory"])
def test_empty_queue_rejects_orphan_metadata_before_sealing(tmp_path, field, value, location):
    old = agent(tmp_path)
    path = checkpoint(old)
    if location == "disk":
        state = maintenance.parse(path.read_bytes())
        state[field] = value
        maintenance.write_state(path, state)
    else:
        setattr(old, "_pending_choice_envelope_v1" if field == "choice_envelope_v1" else "_" + field, value)
    before = path.read_bytes()

    with pytest.raises(maintenance.HandoffError, match="orphan"):
        maintenance.seal(old)

    assert path.read_bytes() == before
    assert not maintenance.stream_path(path).exists()


@pytest.mark.parametrize("field,value", [
    ("pending_next_selection_id", "orphan-selection"),
    ("choice_envelope_v1", {"source": "orphan-envelope"}),
])
def test_acknowledged_changed_state_rejects_orphan_metadata(tmp_path, field, value):
    _, path = acknowledged(tmp_path)
    maintenance.write_state(path, {"pending_next_action": None, field: value})
    before = path.read_bytes()
    history_path = maintenance.stream_path(path)
    history_before = history_path.read_bytes()

    with pytest.raises(maintenance.HandoffError, match="orphan"):
        maintenance.restore(agent(tmp_path))

    assert path.read_bytes() == before
    assert history_path.read_bytes() == history_before


@pytest.mark.parametrize("field,value", [
    ("pending_next_selection_id", ""),
    ("choice_envelope_v1", {}),
])
@pytest.mark.parametrize("location", ["disk", "memory"])
def test_empty_queue_does_not_treat_falsey_metadata_as_exactly_none(tmp_path, field, value, location):
    old = agent(tmp_path)
    path = checkpoint(old)
    if location == "disk":
        state = maintenance.parse(path.read_bytes())
        state[field] = value
        maintenance.write_state(path, state)
    else:
        setattr(old, "_pending_choice_envelope_v1" if field == "choice_envelope_v1" else "_" + field, value)
    before = path.read_bytes()

    with pytest.raises(maintenance.HandoffError):
        maintenance.seal(old)

    assert path.read_bytes() == before
    assert not maintenance.stream_path(path).exists()


def test_real_sigterm_finalizer_seals_then_fresh_process_restores_before_scheduling(tmp_path):
    code = r'''
import json, os, signal, sys, threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

# The child does not inherit pytest's audit hook or path monkeypatches.
import tests.conftest
def deny_network(event, args):
    if event == "socket.connect":
        raise RuntimeError("synthetic handoff subprocess cannot access the network")
sys.addaudithook(deny_network)
import autonomous_agent as aa
from minime_autonomy import maintenance_next as m

root, mode = Path(sys.argv[1]), sys.argv[2]
aa.BASE_DIR = root
aa.WORKSPACE_DIR = root
aa.RUNTIME_DIR = root / "runtime"
aa.DB_PATH = root / "synthetic.db"
aa.StudyFeedback = Mock()
value = object.__new__(aa.AutonomousAgent)
value._agent_boot_id = uuid4().hex
value._agent_pid = os.getpid()
value._agent_started_at = datetime.now(timezone.utc).isoformat()
value._agent_inputs_at_start = {"synthetic_runtime.py": "a" * 64}
value._sovereignty_state_path = lambda: str(root / "sovereignty_state.json")
value._stop_event = threading.Event()
value._shutdown_requested = False
value._llm_job_threads = []
value._pending_next_action = None
value._pending_next_selection_id = None
value._pending_choice_envelope_v1 = None
value._recent_next_actions = []
value.session_id = 1 if mode == "drain" else 900
value.cycle_count = 0
value._hard_recovery_reset = True
value._stable_core_reflective_only = lambda: True
value.running = mode == "drain"
events, signals, errors = [], [], []
drain_started, finalized = threading.Event(), threading.Event()
path = Path(value._sovereignty_state_path())

def status(reason):
    events.append(reason)
    if reason == "draining":
        drain_started.set()
value._write_source_status = status

if mode == "drain":
    m.write_state(path, {"session_id": 1, "pending_next_action": None})
    def stop(signum, frame):
        signals.append(signum)
        value.stop()
    signal.signal(signal.SIGTERM, stop)

    def work():
        try:
            print("accepted", flush=True)
            try:
                assert value._stop_event.wait(10), "SIGTERM did not reach the worker"
            finally:
                assert drain_started.wait(10), "worker finalizer ran before drain"
                value._pending_next_action = 'WRITE REVISE "NEXT: REST" synthetic \u00e9'
                value._pending_choice_envelope_v1 = {"source": "synthetic finalizer", "nested": ["exact", 7]}
                value._persist_pending_next_action(value._pending_next_action, reason="synthetic finalizer choice")
                events.append("finalizer_persisted")
                finalized.set()
        except Exception as error:
            errors.append(repr(error))

    worker = threading.Thread(target=work, daemon=False)
    value._llm_job_threads.append(worker)
    original_seal = m.seal
    def seal_after_join(owner):
        assert not errors, errors
        assert finalized.is_set() and not worker.is_alive(), "seal preceded worker finalization/join"
        events.append("seal_after_join")
        return original_seal(owner)
    m.seal = seal_after_join
    worker.start()
    assert value._stop_event.wait(10), "SIGTERM did not request shutdown"
    value.wait_for_llm_jobs()
    receipt = value._next_handoff_seal
    assert value._lifecycle_phase == "exited"
else:
    before = path.read_bytes()
    value.check_interval = 0
    value._check_source_reload_required = lambda *args: None
    value._apply_pending_next_override_if_present = lambda *args: None
    value._refresh_session_context = lambda: None
    def forbidden(*args, **kwargs):
        raise AssertionError("competing boot reflection or inference")
    value._recover_activity_choice = forbidden
    value._query_llm = forbidden
    value._query_llm_with_next = forbidden
    def scheduling_probe():
        receipt = value._next_handoff_restore
        assert receipt["process"]["boot_id"] == value._agent_boot_id
        assert m.history(path)[0][-1]["sha256"] == receipt["record_sha256"]
        assert receipt["kind"] == "restored"
        events.append("scheduler_after_ack")
        value.stop()
        return None
    value._get_latest_spectral_state = scheduling_probe
    value.start()
    assert events == ["scheduler_after_ack"], events
    assert path.read_bytes() == before, "restore rewrote the exact queue"
    receipt = value._next_handoff_restore

print(json.dumps({
    "pid": os.getpid(), "boot_id": value._agent_boot_id, "receipt": receipt,
    "events": events, "signals": signals,
    "action": value._pending_next_action,
    "selection": value._pending_next_selection_id,
    "envelope": value._pending_choice_envelope_v1,
}), flush=True)
'''
    command = [sys.executable, "-B", "-c", code, str(tmp_path)]
    repo = Path(__file__).resolve().parents[1]
    old = subprocess.Popen(command + ["drain"], cwd=repo, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(old.stdout, selectors.EVENT_READ)
            assert ready.select(15), "synthetic child did not accept its worker"
            assert old.stdout.readline().strip() == "accepted"
        old.send_signal(signal.SIGTERM)
        out, err = old.communicate(timeout=20)
        assert old.returncode == 0, err
        sealed = json.loads(out)
    finally:
        if old.poll() is None:
            old.terminate()
            old.communicate(timeout=15)
    assert sealed["pid"] == old.pid
    assert sealed["signals"] == [signal.SIGTERM]
    assert sealed["events"] == ["draining", "finalizer_persisted", "seal_after_join", "drained"]
    path = tmp_path / "sovereignty_state.json"
    before = path.read_bytes()
    state = maintenance.parse(before)
    assert state["pending_next_action"] == sealed["action"]
    assert state["pending_next_selection_id"] == sealed["selection"]
    assert state["choice_envelope_v1"] == sealed["envelope"]
    assert sealed["receipt"]["state_sha256"] == maintenance.digest(before)
    assert sealed["receipt"]["process"]["pid"] == old.pid

    new = subprocess.Popen(command + ["restore"], cwd=repo, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    try:
        out, err = new.communicate(timeout=20)
        assert new.returncode == 0, err
        restored = json.loads(out)
    finally:
        if new.poll() is None:
            new.terminate()
            new.communicate(timeout=15)
    assert restored["pid"] == new.pid
    assert restored["boot_id"] != sealed["boot_id"]
    for key in ("action", "selection", "envelope"):
        assert restored[key] == sealed[key]
    assert restored["receipt"]["seal_sha256"] == sealed["receipt"]["record_sha256"]
    assert restored["receipt"]["process"]["pid"] == new.pid
    assert restored["receipt"]["process"]["boot_id"] == restored["boot_id"]
    assert restored["receipt"]["scheduling_authorized"] is False
    assert restored["events"] == ["scheduler_after_ack"]
    assert path.read_bytes() == before
    rows, raw = maintenance.history(path)
    assert [row["body"]["kind"] for row in rows] == ["sealed", "restored"]
    assert state["pending_next_action"].encode() not in raw
    assert b"synthetic finalizer" not in raw


@pytest.fixture
def routing_agent(tmp_path, monkeypatch):
    import autonomous_agent as aa

    value = object.__new__(aa.AutonomousAgent)
    value.__dict__.update(vars(agent(tmp_path, "QUESTION q1")))
    value.session_id = 1
    value.running = True
    value._llm_job_threads = []
    value._stop_event = threading.Event()
    value._write_source_status = Mock()
    value._recent_next_actions = []
    value._pending_action_continuity_context = None
    value._self_regulation_reconcile_active_lease = Mock()
    value._publish_self_need = Mock()
    value._apply_pending_next_override_if_present = Mock()
    value._recover_activity_choice = Mock()
    value._attention_protected = Mock(return_value=False)
    value._mark_pending_next_override_consumed = Mock()
    value._continuity_store = Mock(return_value=SimpleNamespace(
        charter_required_guard_assessment=Mock(),
    ))
    monkeypatch.setattr(aa, "StudyFeedback", Mock())
    checkpoint(value)
    return value


@pytest.mark.parametrize("change", ["action", "selection", "missing"])
def test_real_admission_mismatch_keeps_disk_tuple_and_blocks_dispatch(routing_agent, change):
    value = routing_agent
    path = Path(value._sovereignty_state_path())
    state = maintenance.parse(path.read_bytes())
    if change == "action":
        state["pending_next_action"] = "QUESTION q2"
    elif change == "selection":
        state["pending_next_selection_id"] = "newer-selection"
    else:
        state = {"pending_next_action_status": "cleared"}
        value._pending_next_selection_id = None
    maintenance.write_state(path, state)
    before = path.read_bytes()

    with pytest.raises(maintenance.HandoffError, match="pending_.*_changed"):
        value._decide_action({})

    assert path.read_bytes() == before
    assert value._pending_next_action == "QUESTION q1"
    assert value._next_handoff_failed
    value._mark_pending_next_override_consumed.assert_not_called()
    with pytest.raises(maintenance.HandoffError, match="recovery_blocked"):
        value._execute_action("self_study", {})
    value.stop()
    with pytest.raises(maintenance.HandoffError, match="recovery_blocked"):
        value.wait_for_llm_jobs()
    assert path.read_bytes() == before
    assert not maintenance.stream_path(path).exists()


def test_protocol_cannot_requeue_text_without_proven_checkpoint(routing_agent):
    value = routing_agent
    path = Path(value._sovereignty_state_path())
    before = path.read_bytes()
    value._pending_next_action = None
    value._pending_action_continuity_context = {"raw_next": "QUESTION stale"}
    value.stop()

    with pytest.raises(maintenance.HandoffError, match="unproven_unadmitted_choice"):
        value._execute_action("self_study", {})

    assert value._next_handoff_failed
    assert path.read_bytes() == before


def test_real_post_clear_decision_exception_restores_exact_tuple_before_drain(routing_agent):
    value = routing_agent
    value._pending_next_action = "JOURNAL"
    path = checkpoint(value)
    original = maintenance.pending(maintenance.parse(path.read_bytes()))
    value._continuity_store().charter_required_guard_assessment.side_effect = RuntimeError("decoder failed")

    with pytest.raises(RuntimeError, match="decoder failed"):
        value._decide_action({})

    assert maintenance.pending(maintenance.parse(path.read_bytes())) == original
    assert value._pending_next_action == original["pending_next_action"]
    assert value._pending_next_selection_id == original["pending_next_selection_id"]
    assert value._pending_choice_envelope_v1 == original["choice_envelope_v1"]
    assert value._unadmitted_next_checkpoint is None
    assert not getattr(value, "_next_handoff_failed", False)
    value.stop()  # The main loop can receive SIGTERM during its exception backoff.
    value.wait_for_llm_jobs()
    assert value._next_handoff_seal["pending_present"]


@pytest.mark.parametrize("failure", ["write", "changed_clear", "newer_choice"])
def test_decision_exception_recovery_cannot_erase_newer_state(routing_agent, monkeypatch, failure):
    value = routing_agent
    value._pending_next_action = "JOURNAL"
    path = checkpoint(value)
    observed = []

    def fail_after_clear(_):
        if failure == "write":
            monkeypatch.setattr(maintenance, "write_state", Mock(side_effect=OSError("recovery failed")))
        else:
            replacement = {"pending_next_action_status": "cleared", "foreign_update": True}
            if failure == "newer_choice":
                replacement.update(pending_next_action="REST", pending_next_selection_id="new-selection",
                                   pending_next_action_status="pending", choice_envelope_v1={"new": True},
                                   pending_next_action_updated_at="2026-10-05T13:00:00")
            maintenance.write_state(path, replacement)
        observed.append(path.read_bytes())
        raise RuntimeError("decoder failed")

    value._continuity_store().charter_required_guard_assessment.side_effect = fail_after_clear
    with pytest.raises((RuntimeError, OSError)):
        value._decide_action({})
    assert path.read_bytes() == observed[0]
    value.stop()
    if failure == "newer_choice":
        assert value._pending_next_action == "REST"
        assert value._pending_next_selection_id == "new-selection"
        value.wait_for_llm_jobs()
        assert value._next_handoff_seal["pending_present"]
    else:
        assert value._next_handoff_failed
        assert value._unadmitted_next_checkpoint is not None
        with pytest.raises(maintenance.HandoffError, match="recovery_blocked"):
            value.wait_for_llm_jobs()
        assert not maintenance.stream_path(path).exists()


def test_seal_and_wait_reject_unresolved_real_admission_checkpoint(routing_agent):
    value = routing_agent
    assert value._decide_action({}) == "self_study"
    path = Path(value._sovereignty_state_path())
    before = path.read_bytes()
    assert value._pending_next_action is None
    assert value._pending_choice_envelope_v1 is None
    assert value._unadmitted_next_checkpoint is not None

    with pytest.raises(maintenance.HandoffError, match="unresolved_unadmitted_checkpoint"):
        maintenance.seal(value)
    value.stop()
    with pytest.raises(maintenance.HandoffError, match="unresolved_unadmitted_checkpoint"):
        value.wait_for_llm_jobs()
    assert path.read_bytes() == before
    assert not maintenance.stream_path(path).exists()


def compound_routes(value, *, route_hook=None, execute_hook=None):
    """Use the real outer dispatcher and admission bookkeeping, with inert actions."""
    original = value._decide_action
    routed, executed = [], []

    def decide(state, **kwargs):
        derived = kwargs.get("_derived_action")
        if derived is None:
            return original(state, **kwargs)
        routed.append(derived)
        value._set_action_continuity_context(derived, "SYNTHETIC", consume_pending=False)
        if route_hook:
            route_hook(len(routed))
        return "synthetic"

    def execute(route, state):
        context = value._consume_action_continuity_context(route)
        maintenance.admitted(value, context)
        executed.append(context["raw_next"])
        if execute_hook:
            execute_hook(len(executed))

    value._decide_action = decide
    value._execute_action = execute
    value._pending_next_action = "REST AND ACTION_STATUS latest"
    checkpoint(value)
    return routed, executed


def test_compound_consumes_outer_once_and_never_overwrites_newer_choice(routing_agent):
    value = routing_agent
    path = Path(value._sovereignty_state_path())
    newer = []

    def publish(count):
        if count == 1:
            value._pending_next_action = "QUESTION newer"
            value._pending_choice_envelope_v1 = {"newer": ["exact", 1]}
            value._persist_pending_next_action(value._pending_next_action, reason="newer authored choice")
            newer.append(path.read_bytes())

    routed, executed = compound_routes(value, execute_hook=publish)
    route = value._decide_action({})
    assert route == "synthetic"
    assert len(executed) == 1 and len(routed) == 2
    assert path.read_bytes() == newer[0]
    value._execute_action(route, {})
    assert len(executed) == 2
    assert value._next_compound_inflight is None
    assert maintenance.admission_path(path).exists()
    value.stop()
    value.wait_for_llm_jobs()
    assert path.read_bytes() == newer[0]
    assert not maintenance.admission_path(path).exists()
    new = agent(path.parent)
    assert maintenance.restore(new)["pending_present"]
    assert new._pending_next_action == "QUESTION newer"
    assert new._pending_choice_envelope_v1 == {"newer": ["exact", 1]}


def test_legacy_composite_routing_is_unchanged_without_protocol(routing_agent):
    value = routing_agent
    del value._agent_boot_id
    value._pending_next_action = "REST AND ACTION_STATUS latest"
    value._dispatch_multi_action_minime = Mock(return_value="action_status")
    assert value._decide_action({}) == "action_status"
    value._dispatch_multi_action_minime.assert_called_once_with(["REST", "ACTION_STATUS latest"], {})


@pytest.mark.parametrize("boundary", ["before_first", "after_first", "last_route_error", "last_admission"])
@pytest.mark.parametrize("prior_ack", [False, True])
def test_compound_interruption_is_exact_before_admission_or_durably_unknown(routing_agent, boundary, prior_ack):
    value = routing_agent
    path = Path(value._sovereignty_state_path())
    if prior_ack:
        acknowledged(path.parent)

    def route_hook(count):
        if boundary == "before_first" and count == 1:
            value.stop()
        if boundary == "last_route_error" and count == 2:
            raise RuntimeError("derived decoder failed")

    def execute_hook(count):
        if boundary == "after_first" and count == 1:
            value.stop()

    _, executed = compound_routes(value, route_hook=route_hook, execute_hook=execute_hook)
    original = maintenance.pending(maintenance.parse(path.read_bytes()))
    if boundary == "before_first":
        assert value._decide_action({}) is None
        assert not executed
        assert maintenance.pending(maintenance.parse(path.read_bytes())) == original
        value.wait_for_llm_jobs()
        assert not maintenance.admission_path(path).exists()
        assert maintenance.restore(agent(path.parent))["pending_present"]
        return
    if boundary == "last_admission":
        assert value._decide_action({}) == "synthetic"
        value.stop()
        with pytest.raises(maintenance.HandoffError, match="partial_compound_admission_unknown"):
            value._retain_unadmitted_choice()
    else:
        with pytest.raises(maintenance.HandoffError, match="partial_compound_admission_unknown"):
            value._decide_action({})
    assert len(executed) == 1
    assert maintenance.pending(maintenance.parse(path.read_bytes())) == {}
    marker = maintenance.admission_path(path)
    before = marker.read_bytes()
    maintenance.validate_admission(maintenance.parse(before))
    assert b"REST" not in before and b"ACTION_STATUS" not in before
    value.stop()
    with pytest.raises(maintenance.HandoffError, match="recovery_blocked"):
        value.wait_for_llm_jobs()
    with pytest.raises(maintenance.HandoffError, match="unsealed_admission_requires_recovery"):
        maintenance.restore(agent(path.parent))
    assert marker.read_bytes() == before


def test_outer_executor_propagates_nested_handoff_failure_after_recording_failure(routing_agent):
    value = routing_agent
    value._hard_recovery_reset = False
    value._low_fill_guard_status = Mock(return_value={"active": False})
    value._stable_core_action_allowed = Mock(return_value=(True, "synthetic"))
    value._study_action_outcome = Mock()
    value._experiment_bind = Mock(side_effect=maintenance.HandoffError("nested admission failed"))
    store = value._continuity_store()
    store.finish_action = Mock(return_value={"status": "failed"})
    event = {"action_id": "synthetic-action"}

    with pytest.raises(maintenance.HandoffError, match="nested admission failed"):
        value._execute_action("experiment_bind", {}, _from_llm_job=True,
                              _precreated_continuity_context={"raw_next": "EXPERIMENT_BIND current :: REST"},
                              _precreated_continuity_event=event)

    value._experiment_bind.assert_called_once()
    assert value._next_handoff_failed
    assert store.finish_action.call_args.args[1] == "failed"
    value.stop()
    with pytest.raises(maintenance.HandoffError, match="recovery_blocked"):
        value.wait_for_llm_jobs()


@pytest.mark.parametrize("blocked", [False, True])
def test_baseline_experiment_bind_derived_route_preserves_newer_durable_choice(routing_agent, blocked):
    value = routing_agent
    inner = "JOURNAL" if blocked else "QUESTION q2"
    store = value._continuity_store()
    store._strip_action_arg = Mock(return_value=f"current :: {inner}")
    store._parse_selector_payload = Mock(return_value=("current", inner))
    store._peer_experiment_ref = Mock(return_value=None)
    store.base_action = Mock(return_value=inner.split()[0])
    store._live_control_binding_key = Mock(return_value=None)
    store.record_experiment_bind_run = Mock(return_value={"run_id": "synthetic", "status": "handled"})
    store.record_charter_required_guard_block = Mock(return_value={"status": "blocked"})
    store.charter_required_guard_assessment.return_value = {"suggested_next": "REST", "reason": "synthetic"}
    value._current_action_continuity_context = {"raw_next": f"EXPERIMENT_BIND current :: {inner}"}
    value._execute_action = Mock()
    path = checkpoint(value)
    before = path.read_bytes()
    expected = maintenance.pending(maintenance.parse(before))

    value._experiment_bind({})

    assert path.read_bytes() == before
    assert value._pending_next_action == expected["pending_next_action"]
    assert value._pending_next_selection_id == expected["pending_next_selection_id"]
    assert value._pending_choice_envelope_v1 == expected["choice_envelope_v1"]
    assert not maintenance.admission_path(path).exists()
    if blocked:
        store.charter_required_guard_assessment.assert_called_once_with(inner)
        value._execute_action.assert_not_called()
        assert store.record_experiment_bind_run.call_args.args[3] == "skipped"
    else:
        value._execute_action.assert_called_once_with("self_study", {})
        assert store.record_experiment_bind_run.call_args.args[1] == inner


@pytest.mark.parametrize("queued", [False, True])
def test_native_activity_recovery_persists_choice_but_preserves_newer_queue(routing_agent, queued):
    import autonomous_agent as aa

    value = routing_agent
    path = Path(value._sovereignty_state_path())
    if not queued:
        maintenance.write_state(path, {})
    before = path.read_bytes()
    value._pending_next_action = None
    value._activity_checkpoint_exists = Mock(return_value=True)
    value._activity_focus = Mock(return_value=SimpleNamespace(next=lambda: {"next_action": "WRITE CONTINUE"}))
    aa.AutonomousAgent._recover_activity_choice(value)
    state = maintenance.parse(path.read_bytes())
    if queued:
        assert path.read_bytes() == before
        assert value._pending_next_action == "QUESTION q1"
    else:
        assert value._pending_next_action == "WRITE CONTINUE"
        assert state["pending_next_selection_id"] == value._pending_next_selection_id
        assert state["pending_next_action"] == "WRITE CONTINUE"
    value.stop()
    value.wait_for_llm_jobs()
    assert value._next_handoff_seal["pending_present"]


@pytest.mark.parametrize("damage", ["contract", "kind", "version", "process", "pid", "hash", "extra"])
@pytest.mark.parametrize("operation", ["begin_admission", "seal"])
def test_corrupt_compound_witness_is_never_reused_or_deleted(tmp_path, damage, operation):
    value = agent(tmp_path, "REST")
    path = checkpoint(value)
    maintenance.begin_admission(value)
    marker = maintenance.admission_path(path)
    body = maintenance.parse(marker.read_bytes())
    if damage in {"contract", "kind"}:
        body[damage] = "wrong"
    elif damage == "version":
        body["version"] = True
    elif damage == "process":
        body["process"]["extra"] = "wrong"
    elif damage == "pid":
        body["process"]["pid"] = True
    elif damage == "hash":
        body["pending_sha256"] = "invalid"
    else:
        body["extra"] = "wrong"
    marker.write_bytes(maintenance.canonical(body) + b"\n")
    before, state_before = marker.read_bytes(), path.read_bytes()
    with pytest.raises(maintenance.HandoffError):
        getattr(maintenance, operation)(value)
    assert marker.read_bytes() == before
    assert path.read_bytes() == state_before
    assert not maintenance.stream_path(path).exists()


def test_receipt_directory_creation_sync_is_retried_before_any_append(tmp_path, monkeypatch):
    value = agent(tmp_path, "REST")
    path = checkpoint(value)
    receipt = maintenance.stream_path(path)
    sync = maintenance.sync_parent
    failed = []

    def fail_workspace_sync(target):
        if target == receipt.parent:
            failed.append(target)
            raise OSError("workspace directory sync failed")
        sync(target)

    with monkeypatch.context() as patcher:
        patcher.setattr(maintenance, "sync_parent", fail_workspace_sync)
        for _ in range(2):
            with pytest.raises(OSError, match="workspace directory sync failed"):
                maintenance.seal(value)
            assert not receipt.exists()
    assert len(failed) == 2
    assert maintenance.seal(value)["pending_present"]


def test_marker_unlink_sync_failure_is_retried_even_after_marker_disappears(tmp_path, monkeypatch):
    value = agent(tmp_path, "REST")
    path = checkpoint(value)
    maintenance.begin_admission(value)
    marker = maintenance.admission_path(path)
    sync = maintenance.sync_parent
    failed = []

    def fail_retirement_sync(target):
        if target == marker:
            failed.append(target)
            raise OSError("marker retirement sync failed")
        sync(target)

    with monkeypatch.context() as patcher:
        patcher.setattr(maintenance, "sync_parent", fail_retirement_sync)
        for _ in range(3):
            with pytest.raises(OSError, match="marker retirement sync failed"):
                maintenance.seal(value)
            assert not marker.exists()
            assert len(maintenance.history(path)[0]) == 1
    assert len(failed) == 3
    assert maintenance.seal(value)["pending_present"]
    assert len(maintenance.history(path)[0]) == 1


def test_compound_creation_cannot_hide_corrupt_history(tmp_path):
    value = agent(tmp_path, "REST")
    path = checkpoint(value)
    maintenance.seal(value)
    stream = maintenance.stream_path(path)
    damaged = stream.read_bytes() + b"{"
    stream.write_bytes(damaged)
    with pytest.raises(maintenance.HandoffError):
        maintenance.begin_admission(value)
    assert stream.read_bytes() == damaged
    assert not maintenance.admission_path(path).exists()
