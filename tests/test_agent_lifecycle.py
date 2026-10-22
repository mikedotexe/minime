"""Synthetic lifecycle tests; no live workspace or model calls."""
import json
import threading
import subprocess
import sys
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import autonomous_agent as aa
from minime_autonomy.deployment import source_inputs


def agent_stub(tmp_path):
    agent = object.__new__(aa.AutonomousAgent)
    agent._stop_event = threading.Event()
    agent._write_source_status = Mock()
    agent._llm_job_threads = []
    agent.running = True
    return agent


def test_stop_before_start_does_not_resurrect(tmp_path):
    agent = agent_stub(tmp_path)
    agent.stop()
    agent.start()
    assert agent.running is False
    assert agent._stop_event.is_set()


def test_drain_keeps_worker_until_finalizer_returns(tmp_path):
    agent = agent_stub(tmp_path)
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    artifact = tmp_path / "finalized.json"

    def work():
        entered.set()
        release.wait(2)
        artifact.write_text(json.dumps({"status": "completed", "next": "JOURNAL"}))

    worker = threading.Thread(target=work, daemon=False)
    agent._llm_job_threads.append(worker)
    worker.start()
    assert entered.wait(1)
    agent.stop()
    drain = threading.Thread(target=lambda: (agent.wait_for_llm_jobs(), drained.set()))
    drain.start()
    try:
        assert not drained.wait(0.05)
        assert not artifact.exists()
    finally:
        release.set()
        drain.join(2)
        worker.join(2)
    assert drained.is_set()
    assert json.loads(artifact.read_text())["next"] == "JOURNAL"
    assert agent._lifecycle_phase == "exited"


def test_worker_queue_is_non_daemon_and_retained(tmp_path):
    agent = agent_stub(tmp_path)
    agent._llm_job_worker_active = False
    jobs = Mock()
    jobs.active_primary_job.return_value = None
    jobs.submit.return_value = {"job_id": "job_fixture"}
    jobs.jobs_dir = tmp_path
    store = Mock(schema_version=1)
    store.begin_action.return_value = {"action_id": "act_fixture", "thread_id": "thread_fixture"}
    agent._llm_job_store = lambda: jobs
    agent._continuity_store = lambda: store
    with patch.object(aa.threading, "Thread") as factory:
        assert agent._queue_llm_action_job("journal", {}, {})
        assert factory.call_args.kwargs["daemon"] is False
        assert agent._llm_job_threads == [factory.return_value]
        factory.return_value.start.assert_called_once()


def test_signal_during_moment_preserves_its_next_without_new_dispatch(tmp_path):
    agent = agent_stub(tmp_path)
    agent._pending_next_action = None
    agent.check_interval = 60
    for name in ("_restore_sovereignty_state", "_apply_pending_next_override_if_present",
                 "_verify_sovereignty", "_refresh_session_context", "_check_source_reload_required",
                 "_update_hard_recovery_clamp", "_reconcile_stable_core_health_status",
                 "_self_regulate", "_auto_defer_stale_pending_astrid", "_check_visual_responses",
                 "_decide_action", "_execute_action"):
        setattr(agent, name, Mock())
    agent._get_latest_spectral_state = lambda: {"fill_ratio": 0.68}
    agent._llm_job_store = lambda: SimpleNamespace(active_primary_job=lambda: None)

    def moment(state):
        agent.stop()
        agent._pending_next_action = "JOURNAL"

    agent._check_moment_markers = moment
    agent.start()
    assert agent._pending_next_action == "JOURNAL"
    agent._decide_action.assert_not_called()
    agent._execute_action.assert_not_called()
    agent._check_visual_responses.assert_not_called()


def test_stop_after_choice_resolution_does_not_start_an_unaccepted_action(tmp_path):
    agent = agent_stub(tmp_path)
    agent._pending_next_action = "WRITE CONTINUE"
    agent._pending_action_continuity_context = {"raw_next": "WRITE CONTINUE"}
    agent._persist_pending_next_action = Mock()
    agent._consume_action_continuity_context = Mock(side_effect=AssertionError("consumed during drain"))
    agent._queue_llm_action_job = Mock(side_effect=AssertionError("queued during drain"))
    agent.stop()
    agent._execute_action("self_study", {})
    assert agent._pending_next_action == "WRITE CONTINUE"
    agent._consume_action_continuity_context.assert_not_called()


def test_stop_between_decision_and_dispatch_restores_exact_choice(tmp_path):
    agent = agent_stub(tmp_path)
    choice = "WRITE REVISE synthetic exact direction"
    agent._pending_next_action = choice
    agent.check_interval = 60
    for name in ("_restore_sovereignty_state", "_apply_pending_next_override_if_present",
                 "_verify_sovereignty", "_refresh_session_context", "_check_source_reload_required",
                 "_update_hard_recovery_clamp", "_reconcile_stable_core_health_status",
                 "_self_regulate", "_auto_defer_stale_pending_astrid", "_check_visual_responses",
                 "_execute_action", "_persist_pending_next_action"):
        setattr(agent, name, Mock())
    agent._get_latest_spectral_state = lambda: {"fill_ratio": 0.68}
    agent._llm_job_store = lambda: SimpleNamespace(active_primary_job=lambda: None)
    agent._can_act = lambda: True

    def decide(_):
        agent._pending_next_action = None
        agent._pending_action_continuity_context = {"raw_next": choice}
        agent.stop()
        return "self_study"

    agent._decide_action = decide
    agent.start()
    agent._execute_action.assert_not_called()
    assert agent._pending_next_action == choice
    agent._persist_pending_next_action.assert_called_once_with(choice, reason="shutdown_before_admission")


def test_source_inventory_includes_imports_and_launcher_not_private_workspace(tmp_path):
    (tmp_path / "minime_autonomy").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "autonomous_agent.py").write_text("pass\n")
    helper = tmp_path / "minime_autonomy/journal_context.py"
    helper.write_text("INTRO = 'own voice'\n")
    (tmp_path / "workspace/journal.py").write_text("private fixture\n")
    before = source_inputs(tmp_path)
    helper.write_text("INTRO = 'new contract'\n")
    after = source_inputs(tmp_path)
    assert before["minime_autonomy/journal_context.py"] != after["minime_autonomy/journal_context.py"]
    assert "workspace/journal.py" not in after


def test_source_status_binds_start_inputs_and_phase(tmp_path):
    agent = agent_stub(tmp_path)
    source = tmp_path / "runtime.py"
    source.write_text("pass\n")
    agent._agent_source_path = source
    agent._agent_inputs_at_start = {"runtime.py": "fixture-hash"}
    agent._lifecycle_phase = "busy"
    with patch.object(aa, "WORKSPACE_DIR", tmp_path):
        result = agent._current_source_status()
    assert result["lifecycle_contract"] == "agent_drain_v2"
    assert result["lifecycle_phase"] == "busy"
    assert result["source_inputs_at_start"] == {"runtime.py": "fixture-hash"}


def test_real_sigterm_allows_accepted_worker_to_finalize(tmp_path):
    code = r'''
import signal, sys, threading, time
from pathlib import Path
import autonomous_agent as aa
root = Path(sys.argv[1])
agent = object.__new__(aa.AutonomousAgent)
agent._stop_event = threading.Event()
agent._write_source_status = lambda reason: None
agent.running = True
def work():
    print("accepted", flush=True)
    agent._stop_event.wait(5)
    time.sleep(0.1)
    (root / "completed").write_text("NEXT: JOURNAL")
worker = threading.Thread(target=work, daemon=False)
agent._llm_job_threads = [worker]
signal.signal(signal.SIGTERM, lambda *_: agent.stop())
worker.start()
agent._stop_event.wait(5)
agent.wait_for_llm_jobs()
'''
    proc = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "accepted"
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=10)
        assert proc.returncode == 0, err
        assert (tmp_path / "completed").read_text() == "NEXT: JOURNAL"
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


@pytest.mark.parametrize("boundary", ["_self_regulate", "_auto_defer_stale_pending_astrid"])
def test_stop_before_main_moment_does_not_start_generation(tmp_path, boundary):
    agent = agent_stub(tmp_path)
    agent._pending_next_action = None
    agent.check_interval = 0
    for name in ("_restore_sovereignty_state", "_apply_pending_next_override_if_present",
                 "_verify_sovereignty", "_refresh_session_context", "_check_source_reload_required",
                 "_update_hard_recovery_clamp", "_reconcile_stable_core_health_status",
                 "_self_regulate", "_auto_defer_stale_pending_astrid", "_recover_activity_choice",
                 "_check_moment_markers", "_check_visual_responses", "_decide_action"):
        setattr(agent, name, Mock())
    agent._attention_protected = Mock(return_value=False)
    agent._get_latest_spectral_state = lambda: {"fill_ratio": 0.68}
    agent._llm_job_store = lambda: SimpleNamespace(active_primary_job=lambda: None)
    getattr(agent, boundary).side_effect = lambda *_: agent.stop()
    agent.start()
    agent._check_moment_markers.assert_not_called()
    agent._check_visual_responses.assert_not_called()
    agent._decide_action.assert_not_called()


@pytest.mark.parametrize("boundary", ["begin_action", "budget"])
@pytest.mark.parametrize("receipt_failure", [False, True])
def test_queue_preparation_stop_retains_exact_next_and_records_blocked(
    tmp_path, boundary, receipt_failure,
):
    from minime_autonomy import maintenance_next as handoff
    from tests.test_maintenance_next import agent as owner, checkpoint, clear_for_admission

    agent = owner(tmp_path, 'WRITE REVISE "NEXT: REST" synthetic direction')
    original = handoff.pending(checkpoint(agent))
    clear_for_admission(agent, tmp_path)
    context = {"raw_next": original["pending_next_action"],
               "_next_admission_token": agent._unadmitted_next_checkpoint["token"]}
    agent._consume_action_continuity_context = Mock(return_value=context)
    agent.running = True
    jobs = Mock()
    jobs.active_primary_job.return_value = None
    store = Mock()
    event = {"action_id": "synthetic-action", "thread_id": "synthetic-thread"}
    store.begin_action.return_value = event
    agent._llm_job_store = lambda: jobs
    agent._continuity_store = lambda: store
    if receipt_failure:
        store.finish_action.side_effect = OSError("synthetic blocked receipt failure")

    def stop(value):
        agent.stop()
        return value

    if boundary == "begin_action":
        store.begin_action.side_effect = lambda *a, **kw: stop(event)
    with patch.object(aa, "_journal_job_timeout_s", side_effect=lambda *a, **kw:
                      stop(300) if boundary == "budget" else 300), \
            patch.object(aa.threading, "Thread") as factory:
        if receipt_failure:
            with pytest.raises(OSError, match="blocked receipt failure"):
                agent._execute_action("self_study", {})
            assert agent._next_handoff_failed
        else:
            agent._execute_action("self_study", {})
            assert agent._current_action_continuity_context is None
        jobs.submit.assert_not_called()
        factory.assert_not_called()
    store.finish_action.assert_called_once_with(
        event, "blocked", "Shutdown before LLM job admission; unadmitted choice retained.", {},
    )
    store.record_running_action.assert_not_called()
    assert handoff.pending(handoff.parse(handoff.read(
        agent._sovereignty_state_path(), handoff.MAX_STATE))) == original
    if not receipt_failure:
        agent.wait_for_llm_jobs()
        assert agent._next_handoff_seal["pending_present"] is True


@pytest.mark.parametrize("boundary", ["selection", "marker_commit", "provider"])
def test_moment_admission_preserves_input_or_finishes_current_call(tmp_path, boundary, monkeypatch):
    agent = agent_stub(tmp_path)
    agent.session_id = 1
    agent.cycle_count = 1
    agent._pending_next_action = None
    agent._current_fill_frame_label = Mock(return_value="synthetic")
    agent._format_metrics = Mock(return_value="synthetic metrics")
    agent._write_journal_entry = Mock()
    (tmp_path / "journal").mkdir()
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(aa, "capture_report_snapshot", Mock(return_value=SimpleNamespace(state={})))
    monkeypatch.setattr(aa, "format_marker_anchors", Mock(return_value="synthetic marker"))
    monkeypatch.setattr(aa, "format_snapshot_provenance", Mock(return_value="synthetic provenance"))
    monkeypatch.setattr(aa, "_ap_try_spectral", Mock())
    monkeypatch.setattr(aa, "_ap_try_prose", Mock())
    conn = Mock()
    monkeypatch.setattr(aa.sqlite3, "connect", Mock(return_value=conn))

    def select(*args, **kwargs):
        if boundary == "selection":
            agent.stop()
        return [{"id": 1, "marker_type": "synthetic", "description": "fixture", "spectral_context": None}]

    def provider(*args, **kwargs):
        if boundary == "provider":
            agent.stop()
        agent._pending_next_action = "REST"
        return "Synthetic accepted journal.\nNEXT: REST", "REST"

    monkeypatch.setattr(aa, "select_recent_markers", select)
    agent._query_llm_with_next = Mock(side_effect=provider)
    if boundary == "marker_commit":
        conn.commit.side_effect = agent.stop
    accepted = agent._check_moment_markers({})
    conn.close.assert_called_once()
    if boundary == "selection":
        assert accepted is False
        conn.execute.assert_not_called()
        aa._ap_try_spectral.assert_not_called()
        agent._query_llm_with_next.assert_not_called()
        assert not list((tmp_path / "journal").iterdir())
    else:
        assert accepted is True
        agent._query_llm_with_next.assert_called_once()
        agent._write_journal_entry.assert_called_once()
        journals = list((tmp_path / "journal").iterdir())
        assert len(journals) == 1
        assert "Synthetic accepted journal." in journals[0].read_text()
        assert agent._pending_next_action == "REST"


@pytest.mark.parametrize("boundary", ["preparation", "provider"])
def test_visual_stop_retains_unadmitted_sources_and_finishes_accepted_item(tmp_path, boundary, monkeypatch):
    agent = agent_stub(tmp_path)
    agent._pending_next_action = None
    agent._last_state = {}
    agent._write_journal_entry = Mock()
    responses = tmp_path / "visual_responses"
    responses.mkdir()
    (tmp_path / "journal").mkdir()
    originals = {}
    for index in (1, 2):
        path = responses / f"response_{index}.json"
        raw = json.dumps({"response_timestamp": f"synthetic-{index}", "description": "fixture"}).encode() + b"\r\n"
        path.write_bytes(raw)
        originals[path] = raw
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)

    def prepare(*args, **kwargs):
        if boundary == "preparation":
            agent.stop()
        return "Synthetic visual observation."

    def provider(*args, **kwargs):
        agent.stop()
        agent._pending_next_action = "REST"
        return "Synthetic accepted reflection.\nNEXT: REST", "REST"

    monkeypatch.setattr(aa, "visual_observation", prepare)
    agent._query_llm_with_next = Mock(side_effect=provider)
    agent._check_visual_responses()
    for path, raw in originals.items():
        expected = responses / "processed" / path.name if boundary == "provider" and path.name == "response_1.json" else path
        assert expected.read_bytes() == raw
    if boundary == "preparation":
        agent._query_llm_with_next.assert_not_called()
        assert not (responses / "processed").exists()
    else:
        agent._query_llm_with_next.assert_called_once()
        agent._write_journal_entry.assert_called_once()
        assert agent._pending_next_action == "REST"
        assert len(list((tmp_path / "journal").iterdir())) == 1
    agent._check_visual_responses()
    assert agent._query_llm_with_next.call_count == (boundary == "provider")


@pytest.mark.parametrize("response_kind", ["moment", "visual"])
@pytest.mark.parametrize("failure_site", ["file", "journal_entry"])
@pytest.mark.parametrize("mode", ["shutdown", "running", "no_identity"])
def test_synchronous_journal_failure_blocks_shutdown_seal(
    tmp_path, monkeypatch, response_kind, failure_site, mode,
):
    from minime_autonomy import maintenance_next as handoff
    from tests.test_maintenance_next import agent as owner, checkpoint

    agent = owner(tmp_path, "REST")
    checkpoint(agent)
    state_path = Path(agent._sovereignty_state_path())
    original_state = state_path.read_bytes()
    if response_kind == "visual":
        # A preexisting REST must defer visual admission. Instead, accept from
        # an empty queue and introduce REST during the synchronous provider call.
        agent._pending_next_action = None
        agent._pending_next_selection_id = None
        agent._pending_choice_envelope_v1 = None
        checkpoint(agent)
    if mode == "no_identity":
        del agent._agent_boot_id
    agent.running = True
    agent.cycle_count = 1
    agent._last_state = {}
    agent._current_fill_frame_label = Mock(return_value="synthetic")
    agent._format_metrics = Mock(return_value="synthetic metrics")
    agent._write_journal_entry = Mock()
    if failure_site == "journal_entry":
        agent._write_journal_entry.side_effect = OSError("synthetic journal entry failure")
    (tmp_path / "journal").mkdir()
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)

    def provider(*args, **kwargs):
        if response_kind == "visual":
            agent._pending_next_action = "REST"
            agent._pending_next_selection_id = "selection-1"
            agent._pending_choice_envelope_v1 = {"exact": "private synthetic context"}
            checkpoint(agent)
        if mode != "running":
            agent.stop()
        return "Synthetic accepted response.", None

    agent._query_llm_with_next = Mock(side_effect=provider)
    originals = {}
    if response_kind == "moment":
        monkeypatch.setattr(aa, "capture_report_snapshot", Mock(return_value=SimpleNamespace(state={})))
        monkeypatch.setattr(aa, "format_marker_anchors", Mock(return_value="synthetic marker"))
        monkeypatch.setattr(aa, "format_snapshot_provenance", Mock(return_value="synthetic provenance"))
        monkeypatch.setattr(aa, "_ap_try_spectral", Mock())
        monkeypatch.setattr(aa, "_ap_try_prose", Mock())
        monkeypatch.setattr(aa.sqlite3, "connect", Mock(return_value=Mock()))
        monkeypatch.setattr(aa, "select_recent_markers", Mock(return_value=[{
            "id": 1, "marker_type": "synthetic", "description": "fixture", "spectral_context": None,
        }]))
    else:
        responses = tmp_path / "visual_responses"
        responses.mkdir()
        for index in (1, 2):
            path = responses / f"response_{index}.json"
            raw = json.dumps({"response_timestamp": f"synthetic-{index}", "description": "fixture"}).encode() + b"\r\n"
            path.write_bytes(raw)
            originals[path] = raw
        monkeypatch.setattr(aa, "visual_observation", Mock(return_value="Synthetic visual observation."))

    with monkeypatch.context() as writes:
        if failure_site == "file":
            writes.setattr(Path, "write_text", Mock(side_effect=OSError("synthetic journal file failure")))
        if response_kind == "moment":
            assert agent._check_moment_markers({}) is False
        else:
            agent._check_visual_responses()

    expected_calls = 1  # The newly pending REST also defers the second visual source.
    assert agent._query_llm_with_next.call_count == expected_calls
    assert agent._write_journal_entry.call_count == (expected_calls if failure_site == "journal_entry" else 0)
    assert getattr(agent, "_next_handoff_failed", False) is (mode == "shutdown")
    assert agent._pending_next_action == "REST"
    assert state_path.read_bytes() == original_state
    for path, raw in originals.items():
        assert path.read_bytes() == raw
    if response_kind == "visual":
        assert not (responses / "processed").exists()
        agent._check_visual_responses()
        assert agent._query_llm_with_next.call_count == 1

    agent.stop()
    if mode == "shutdown":
        with pytest.raises(handoff.HandoffError, match="recovery_blocked"):
            agent.wait_for_llm_jobs()
        assert agent._lifecycle_phase == "recovery_blocked"
        assert not hasattr(agent, "_next_handoff_seal")
        assert not handoff.stream_path(state_path).exists()
        assert "drained" not in [call.args[0] for call in agent._write_source_status.call_args_list]
    else:
        agent.wait_for_llm_jobs()
        assert agent._lifecycle_phase == "exited"
    assert state_path.read_bytes() == original_state
