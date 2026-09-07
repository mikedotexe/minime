"""Synthetic lifecycle tests; no live workspace or model calls."""
import json
import threading
import subprocess
import sys
import signal
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    assert result["lifecycle_contract"] == "agent_drain_v1"
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
