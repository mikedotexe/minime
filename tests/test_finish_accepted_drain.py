"""Synthetic qualification of real queue, action finalizers and NEXT handoff.

Only model delivery, ambient runtime hooks and source-status publication are
stubbed. The Rust reader receives temporary source/workspace roots. No live
service, Git command or existing private writing is part of these tests.
"""

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

import autonomous_agent as aa
from minime_autonomy import maintenance_next as handoff
from minime_autonomy.source_study import SourceStudyPrompt, StudyClient


STATE = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68,
         "spread": 3.0, "cov_lambda1": 8.0, "geom_rel": 1.0}
CHOICE = "SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1"
NEXT = "SELF_STUDY OPEN minime/minime_autonomy/runtime.py 17"
RESPONSE = "Synthetic source observation.\nExact second line; keep punctuation.\nNEXT: " + NEXT
LIVE_ROOTS = tuple(Path("/Users/v/other") / name for name in (
    "minime", "astrid", "shared", "research", "autoresearch", "neural-triple-reservoir"))
REPO = Path(__file__).resolve().parents[1]


@contextmanager
def _no_live_io():
    # Audit hooks cannot be removed, so disable this scope before pytest teardown.
    active = True
    violations = []

    def audit(event, args):
        if not active:
            return
        reason = None
        if event in {"open", "os.listdir", "os.scandir", "sqlite3.connect"}:
            value = args[0]
            if isinstance(value, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(value)).resolve()
                if (any(path.is_relative_to(root) for root in LIVE_ROOTS)
                        or path.is_relative_to(REPO / "workspace")
                        or path == Path("/tmp/bridge.log").resolve()):
                    reason = f"forbidden live/private path: {path}"
        elif event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            reason = "network access is outside synthetic drain qualification"
        elif event == "subprocess.Popen":
            executable, command, _, _ = args
            reader = os.environ.get("ASTRID_SOURCE_STUDY_BIN")
            is_reader = reader and str(executable) == reader and list(command) == [reader]
            is_child = (str(executable) == sys.executable and isinstance(command, list)
                        and len(command) == 5 and command[1:3] == ["-B", "-c"]
                        and command[3].startswith("from tests.test_finish_accepted_drain import _sigterm_child;"))
            if not (is_reader or is_child):
                reason = "unexpected subprocess (including Git)"
        if reason:
            violations.append(reason)
            raise RuntimeError(reason)

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False
        assert not violations, violations


def _isolate(monkeypatch, root):
    base = root / "source" / "minime"
    workspace = base / "workspace"
    runtime = workspace / "runtime"
    runtime.mkdir(parents=True)
    astrid = root / "source" / "astrid"
    astrid.mkdir()
    source = base / "minime_autonomy" / "runtime.py"
    source.parent.mkdir()
    source.write_text("def entry():\n" + "    # synthetic source line\n" * 2000)
    for name, value in list(vars(aa).items()):
        if isinstance(value, Path) and any(value.is_relative_to(p) for p in (*LIVE_ROOTS, REPO / "workspace")):
            monkeypatch.setattr(aa, name, root / "external" / name.lower())
    for name, value in {"BASE_DIR": base, "WORKSPACE_DIR": workspace,
                        "RUNTIME_DIR": runtime, "DB_PATH": root / "test.db"}.items():
        monkeypatch.setattr(aa, name, value)
    monkeypatch.setenv("ASTRID_SOURCE_ROOT", str(astrid))
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr(aa, "_load_sensory_gate_state", lambda: {})
    monkeypatch.setattr(aa.AutonomousAgent, "SHARED_COLLAB_DIR", root / "external/collaborations")
    client = StudyClient(base, workspace, astrid_root=astrid,
                         executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    return workspace


class DrainHarness:
    def __init__(self, monkeypatch, root, *, phase="provider", failure=False):
        self.workspace = _isolate(monkeypatch, root)
        self.agent = aa.AutonomousAgent(901, check_interval=60, recess_mode=True)
        self.agent.running = True
        self.entered = threading.Event()
        self.release = threading.Event()
        self.draining = threading.Event()
        self.done = threading.Event()
        self.errors = []
        self.offers = []
        self.drain_thread = None
        self.statuses = []
        agent = self.agent
        monkeypatch.setattr(agent, "_low_fill_guard_status", lambda *_: {
            "active": False, "fill_ratio": 0.68})
        # These are ambient sensing/publication hooks, not dispatch/finalization.
        for name in ("_write_journal_entry", "_log_decision", "_publish_self_need",
                     "_self_regulation_reconcile_active_lease", "_record_stable_core_agent_success"):
            monkeypatch.setattr(agent, name, Mock())
        monkeypatch.setattr(agent, "_state_for_live_surfaces", lambda state, **kw: dict(state))
        monkeypatch.setattr(agent, "_write_source_status", self.source_status)
        self.jobs = agent._llm_job_store()
        self.continuity = agent._continuity_store()

        def barrier():
            self.entered.set()
            if not self.release.wait(15):
                raise RuntimeError("synthetic test barrier was not released")

        def provider(prompt, **kwargs):
            assert isinstance(prompt, SourceStudyPrompt)
            assert prompt.client.workspace == self.workspace
            assert prompt.output["input_kind"] == "source_page"
            self.offers.append(prompt)
            if phase == "provider":
                barrier()
            if failure:
                raise RuntimeError("synthetic provider failure after stop")
            wire = json.dumps({"message": {"content": RESPONSE}, "done": True, "done_reason": "stop"})
            prompt.post(Mock(return_value=SimpleNamespace(status_code=200, text=wire)),
                        "fixture://no-network", {"messages": [
                            {"role": "system", "content": prompt.output["system_prompt"]},
                            {"role": "user", "content": str(prompt)}]}, 1)
            prompt.accepted()
            return RESPONSE

        monkeypatch.setattr(agent, "_query_llm", provider)
        if phase in {"continuity_finalizer", "job_finalizer"}:
            owner = self.continuity if phase == "continuity_finalizer" else self.jobs
            name = "finish_action" if phase == "continuity_finalizer" else "finish"
            original = getattr(owner, name)

            def finalize(*args, **kwargs):
                barrier()
                return original(*args, **kwargs)

            monkeypatch.setattr(owner, name, finalize)

    @property
    def state_path(self):
        return Path(self.agent._sovereignty_state_path())

    def source_status(self, reason):
        self.statuses.append((reason, self.agent._lifecycle_phase))
        if reason == "draining":
            self.draining.set()

    def select(self):
        self.agent._pending_next_action = CHOICE
        self.agent._pending_choice_envelope_v1 = {"fixture": "exact selection", "primary_next": CHOICE}
        self.agent._persist_pending_next_action(CHOICE, reason="synthetic authored choice")
        return handoff.pending(handoff.parse(self.state_path.read_bytes()))

    def queue(self):
        self.select()
        assert self.agent._decide_action(dict(STATE)) == "self_study"
        self.agent._execute_action("self_study", dict(STATE))
        assert self.entered.wait(10), "real worker did not reach the requested barrier"
        assert len(self.agent._llm_job_threads) == 1
        assert self.agent._llm_job_threads[0].daemon is False
        job = self.jobs.active_primary_job()
        assert job and job["worker_status"] == "running"
        return job["job_id"]

    def drain(self):
        self.agent.stop()

        def run():
            try:
                self.agent.wait_for_llm_jobs()
            except BaseException as exc:
                self.errors.append(exc)
            finally:
                self.done.set()

        self.drain_thread = threading.Thread(target=run, name="synthetic-drain")
        self.drain_thread.start()
        assert self.draining.wait(2)
        assert not self.done.wait(0.05), "drain returned before the real finalizer"
        assert not handoff.stream_path(self.state_path).exists()
        assert ("drained", "exited") not in self.statuses

    def finish(self):
        self.release.set()
        for thread in self.agent._llm_job_threads:
            thread.join(10)
            assert not thread.is_alive(), "real worker leaked past test cleanup"
        if self.drain_thread is not None:
            self.drain_thread.join(10)
            assert not self.drain_thread.is_alive(), "drain leaked past test cleanup"
        assert not self.errors, self.errors

    def restored(self):
        # Construction is unnecessary for a passive restore receipt; no scheduling.
        new = object.__new__(aa.AutonomousAgent)
        new._agent_boot_id = uuid4().hex
        new._agent_pid = os.getpid()
        new._agent_started_at = "2026-10-12T00:00:00"
        new._agent_inputs_at_start = dict(self.agent._agent_inputs_at_start)
        before = self.state_path.read_bytes()
        receipt = handoff.restore(new)
        assert self.state_path.read_bytes() == before
        assert receipt["seal_sha256"] == self.agent._next_handoff_seal["record_sha256"]
        assert receipt["scheduling_authorized"] is False
        for name in ("_pending_next_action", "_pending_next_selection_id", "_pending_choice_envelope_v1"):
            assert getattr(new, name) == getattr(self.agent, name)
        assert handoff.restore(new) == receipt
        return new, receipt


@pytest.fixture
def harness(tmp_path, monkeypatch):
    instances = []
    with _no_live_io():
        def create(**kwargs):
            instance = DrainHarness(monkeypatch, tmp_path, **kwargs)
            instances.append(instance)
            return instance

        yield create
        for instance in instances:
            instance.finish()


def _assert_completed(h, job_id, *, timed_out=False):
    job = h.jobs.read_job(job_id)
    assert job["status"] == ("timeout" if timed_out else "completed"), job
    assert job["worker_status"] == "completed"
    assert job["outcome"]["status"] == "completed"
    assert job["outcome"]["error"] is None
    assert h.jobs.active_primary_job() is None
    assert not h.agent._llm_job_worker_active
    assert len(h.offers) == 1 and h.offers[0].receipt
    journals = list((h.workspace / "journal").glob("self_study_*.txt"))
    assert len(journals) == 1
    assert journals[0].read_text().split("\n\n", 1)[1] == RESPONSE + "\n"
    assert any(a["path_or_uri"] == str(journals[0]) for a in job["artifact_refs"])
    assert h.agent._write_journal_entry.call_args.args[1] == RESPONSE
    assert h.agent._pending_next_action == NEXT
    state = handoff.parse(h.state_path.read_bytes())
    assert state["pending_next_action"] == NEXT
    assert state["pending_next_selection_id"] == h.agent._pending_next_selection_id
    assert state.get("choice_envelope_v1") == h.agent._pending_choice_envelope_v1
    assert state["pending_next_action_update_reason"] == "llm next choice"
    timing = json.loads((h.jobs.jobs_dir / job_id / "phase_timings.json").read_text())
    assert timing["state"] == "complete"
    assert any(s["phase"] == "worker.finalization" and s["status"] == "ok" for s in timing["spans"])
    return job


@pytest.mark.parametrize("phase", ["provider", "continuity_finalizer", "job_finalizer"])
def test_accepted_self_study_drains_exact_output_and_next_before_seal(harness, phase):
    h = harness(phase=phase)
    job_id = h.queue()
    h.drain()
    h.agent._execute_action("self_study", dict(STATE))
    h.agent.start()
    assert len(h.agent._llm_job_threads) == 1
    h.finish()
    _assert_completed(h, job_id)
    before = h.state_path.read_bytes()
    h.agent._execute_action("self_study", dict(STATE))
    assert h.state_path.read_bytes() == before
    assert len(list(h.jobs.jobs_dir.glob("*/job.json"))) == 1
    assert h.agent._lifecycle_phase == "exited"
    assert h.statuses[-1] == ("drained", "exited")
    assert not handoff.admission_path(h.state_path).exists()
    h.restored()


@pytest.mark.parametrize("boundary", ["decision_clear", "context_consumption"])
def test_stop_during_decision_or_pre_admission_restores_exact_tuple(harness, monkeypatch, boundary):
    h = harness()
    original = h.select()
    if boundary == "decision_clear":
        persist = h.agent._persist_pending_next_action

        def stop_after_clear(*args, **kwargs):
            result = persist(*args, **kwargs)
            if kwargs.get("reason") == "selected_for_admission":
                h.agent.stop()
            return result

        monkeypatch.setattr(h.agent, "_persist_pending_next_action", stop_after_clear)
        assert h.agent._decide_action(dict(STATE)) is None
    else:
        assert h.agent._decide_action(dict(STATE)) == "self_study"
        consume = h.agent._consume_action_continuity_context

        def stop_after_consumption(action):
            context = consume(action)
            h.agent.stop()
            return context

        monkeypatch.setattr(h.agent, "_consume_action_continuity_context", stop_after_consumption)
    h.agent._execute_action("self_study", dict(STATE))
    assert not h.agent._llm_job_threads
    assert not list(h.jobs.jobs_dir.glob("*/job.json"))
    assert h.offers == []
    assert handoff.pending(handoff.parse(h.state_path.read_bytes())) == original
    h.agent.wait_for_llm_jobs()
    h.restored()


def test_stop_after_durable_submit_before_worker_claim_still_finishes(harness, monkeypatch):
    h = harness()
    submit = h.jobs.submit

    def stop_after_submit(**kwargs):
        job = submit(**kwargs)
        assert job["status"] == "queued"
        h.agent.stop()
        return job

    monkeypatch.setattr(h.jobs, "submit", stop_after_submit)
    job_id = h.queue()
    assert h.agent._shutdown_requested
    h.drain()
    h.finish()
    _assert_completed(h, job_id)
    h.restored()


def test_stop_before_durable_submit_does_not_admit_new_work(harness, monkeypatch):
    h = harness()
    original = h.select()
    assert h.agent._decide_action(dict(STATE)) == "self_study"
    begin = h.continuity.begin_action

    def stop_before_begin(*args, **kwargs):
        h.agent.stop()
        return begin(*args, **kwargs)

    monkeypatch.setattr(h.continuity, "begin_action", stop_before_begin)
    h.agent._execute_action("self_study", dict(STATE))
    assert not list(h.jobs.jobs_dir.glob("*/job.json")), "job submitted after stop during queue preparation"
    assert not h.agent._llm_job_threads
    assert h.offers == []
    assert handoff.pending(handoff.parse(h.state_path.read_bytes())) == original
    h.agent.wait_for_llm_jobs()
    h.restored()


@pytest.mark.parametrize("failure", [False, True], ids=["late_success", "late_failure"])
def test_timed_out_worker_remains_owned_until_truthful_terminal_outcome(harness, failure):
    h = harness(failure=failure)
    job_id = h.queue()
    running = h.jobs.read_job(job_id)
    running["started_at"] = "2000-01-01T00:00:00Z"
    h.jobs._write_job(running)
    h.jobs.expire_timed_out_jobs()
    active = h.jobs.active_primary_job()
    assert active["job_id"] == job_id
    assert active["status"] == "timeout" and active["worker_status"] == "running"
    h.drain()
    h.finish()
    if failure:
        job = h.jobs.read_job(job_id)
        assert job["status"] == "timeout"
        assert job["worker_status"] == "failed"
        assert job["outcome"]["error"] == "source_study_unavailable"
        assert "synthetic provider failure after stop" in job["outcome"]["summary"]
        assert h.agent._pending_next_action is None
        assert not list((h.workspace / "journal").glob("self_study_*.txt"))
    else:
        job = _assert_completed(h, job_id, timed_out=True)
    assert job["deadline_exceeded_at"]
    assert Path(job["retained_result_path"]).read_text() == job["outcome"]["summary"]
    assert h.jobs.active_primary_job() is None
    assert h.agent._lifecycle_phase == "exited"
    h.restored()


def test_provider_failure_after_stop_is_failed_not_completed(harness):
    h = harness(failure=True)
    job_id = h.queue()
    h.drain()
    h.finish()
    job = h.jobs.read_job(job_id)
    assert job["status"] == job["worker_status"] == "failed"
    assert job["error"] == "source_study_unavailable"
    assert "synthetic provider failure after stop" in job["summary"]
    assert h.jobs.active_primary_job() is None
    assert h.agent._pending_next_action is None
    assert not list((h.workspace / "journal").glob("self_study_*.txt"))
    assert h.agent._next_handoff_seal["pending_present"] is False
    h.restored()


def test_wrapper_refuses_timed_out_worker_when_finish_cannot_persist(harness, monkeypatch):
    scripts = Path(os.environ.get(
        "ASTRID_DRAIN_WRAPPER_ROOT",
        str(REPO.parent / "astrid"),
    )) / "scripts"
    wrapper_path = scripts / "finish_minime_work.py"
    if not wrapper_path.is_file():
        pytest.skip("set ASTRID_DRAIN_WRAPPER_ROOT to the isolated finish-work wrapper checkout")

    class SourceOnlyImportPath(list):
        def insert(self, index, path):
            # The deployment module adds its live default checkout to sys.path.
            # Keep imports on checked-out source; never inspect that live tree.
            if not any(Path(path).is_relative_to(root) for root in LIVE_ROOTS):
                super().insert(index, path)

    with monkeypatch.context() as imports:
        imports.setattr(sys, "path", SourceOnlyImportPath([str(scripts), *sys.path]))
        spec = importlib.util.spec_from_file_location("synthetic_finish_minime_work", wrapper_path)
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        from restart_minime_agent import job_receipt

    h = harness()
    job_id = h.queue()
    running = h.jobs.read_job(job_id)
    running["started_at"] = "2000-01-01T00:00:00Z"
    h.jobs._write_job(running)
    h.jobs.expire_timed_out_jobs()
    before = (h.jobs.jobs_dir / job_id / "job.json").read_bytes()
    write_job = h.jobs._write_job
    failed_writes = []

    def fail_outcome_persistence(job):
        if job.get("outcome") is not None:
            failed_writes.append(job["worker_status"])
            raise OSError("synthetic durable job outcome write failure")
        return write_job(job)

    monkeypatch.setattr(h.jobs, "_write_job", fail_outcome_persistence)
    h.agent.stop()
    h.finish()
    assert failed_writes == ["completed", "completed", "failed"]
    job = h.jobs.read_job(job_id)
    assert job["status"] == "timeout" and job["worker_status"] == "running"
    assert job.get("outcome") is None
    assert (h.jobs.jobs_dir / job_id / "job.json").read_bytes() == before
    assert h.jobs.active_primary_job()["job_id"] == job_id
    journals = list((h.workspace / "journal").glob("self_study_*.txt"))
    assert len(journals) == 1
    assert journals[0].read_text().split("\n\n", 1)[1] == RESPONSE + "\n"
    assert h.agent._pending_next_action == NEXT

    # Older runtimes can seal after all threads return despite this unresolved
    # worker receipt. Exercise the wrapper against that exact bad boundary even
    # if the current runtime subsequently adds its own persistence-failure gate.
    seal = handoff.seal(h.agent)
    identity = handoff.identity(h.agent)
    stopped = False
    signals, events, acknowledgements = [], [], []

    def terminate(pid):
        nonlocal stopped
        signals.append(pid)
        stopped = True

    def drain_identity(pid, inputs, *, stopped=False):
        if stopped:
            acknowledgements.append({"lifecycle_phase": "exited", "reason": "drained"})
        return identity

    inputs = dict(h.agent._agent_inputs_at_start)
    backend = SimpleNamespace(
        validate=lambda: None, inputs=lambda: inputs, config=lambda: {}, protected=lambda: {},
        identity=lambda pid: None if stopped else "synthetic-process-start",
        pid=lambda: None if stopped else 901,
        drain_identity=drain_identity, maintenance=lambda: None, terminate=terminate,
        jobs=lambda: job_receipt(h.workspace.parent, full=True),
        verify_next_seal=lambda process: {"seal_sha256": seal["record_sha256"]},
    )
    hold = SimpleNamespace(begin=Mock(), assert_hold=Mock(), transition=Mock(
        side_effect=AssertionError("wrapper released replacement with worker_status=running")))
    with pytest.raises(wrapper.DrainRefusal, match="unfinished|worker|terminal"):
        wrapper.finish_accepted_work(
            backend, 901, running_inputs=inputs, expected_inputs=inputs, handoff=hold,
            timeout_s=30, now=lambda: 0, sleep=lambda _: None, emit=events.append)
    hold.transition.assert_not_called()
    assert signals == [901]
    assert acknowledgements == [{"lifecycle_phase": "exited", "reason": "drained"}]
    assert not any(event.get("phase") == "accepted_work_drained" for event in events)
    assert (h.jobs.jobs_dir / job_id / "job.json").read_bytes() == before


def test_seal_flush_failure_retains_completed_work_and_blocks_restore(harness, monkeypatch):
    h = harness()
    job_id = h.queue()
    h.agent.stop()
    h.finish()
    _assert_completed(h, job_id)
    before = h.state_path.read_bytes()
    witness = handoff.admission_path(h.state_path).read_bytes()
    stream = handoff.stream_path(h.state_path)
    sync_parent = handoff.sync_parent

    def fail_seal_flush(path):
        if Path(path) == stream:
            raise OSError("synthetic seal directory flush failure")
        return sync_parent(path)

    with monkeypatch.context() as scoped:
        scoped.setattr(handoff, "sync_parent", fail_seal_flush)
        with pytest.raises(OSError, match="seal directory flush failure"):
            h.agent.wait_for_llm_jobs()
    assert h.agent._lifecycle_phase == "recovery_blocked"
    assert not getattr(h.agent, "_next_handoff_seal", None)
    assert ("drained", "exited") not in h.statuses
    assert h.state_path.read_bytes() == before
    assert handoff.admission_path(h.state_path).read_bytes() == witness
    with pytest.raises(handoff.HandoffError, match="unsealed_admission_requires_recovery"):
        handoff.restore(object.__new__(aa.AutonomousAgent))
    # The original owner can confirm the existing append once I/O recovers.
    saved_receipt = stream.read_bytes()
    h.agent.wait_for_llm_jobs()
    assert stream.read_bytes() == saved_receipt
    assert h.state_path.read_bytes() == before
    _assert_completed(h, job_id)
    h.restored()


def _sigterm_child(root):
    """Run the production CLI signal handler/start/finally path in a child."""
    with _no_live_io(), pytest.MonkeyPatch.context() as patch:
        h = DrainHarness(patch, Path(root))
        agent = h.agent
        h.select()
        handoff.seal(agent)
        agent._agent_boot_id = uuid4().hex
        # A previous synthetic boot sealed the exact choice. main/start must
        # acknowledge it before the real decision and worker queue can run.
        for name in ("_check_source_reload_required", "_restore_sovereignty_state",
                     "_apply_pending_next_override_if_present", "_refresh_session_context",
                     "_update_hard_recovery_clamp", "_reconcile_stable_core_health_status",
                     "_self_regulate", "_auto_defer_stale_pending_astrid", "_check_visual_responses"):
            patch.setattr(agent, name, Mock())
        patch.setattr(agent, "_get_latest_spectral_state", lambda: dict(STATE))
        patch.setattr(agent, "_can_act", lambda: True)
        patch.setattr(aa, "AutonomousAgent", lambda *args, **kwargs: agent)
        patch.delenv("MINIME_ALLOW_MULTIPLE_AUTONOMOUS_AGENTS", raising=False)
        with sqlite3.connect(aa.DB_PATH) as connection:
            connection.execute("CREATE TABLE sessions (session_id INTEGER, start_time REAL)")
            connection.execute("INSERT INTO sessions VALUES (901, 1)")

        def coordinate():
            try:
                assert h.entered.wait(10), "child never accepted self-study"
                print("drain-fixture:accepted", flush=True)
                assert agent._stop_event.wait(10), "child never received SIGTERM"
                assert h.draining.wait(2), "main finally did not enter drain"
                print("drain-fixture:stopped", flush=True)
                assert sys.stdin.readline().strip() == "release"
            except BaseException as exc:
                h.errors.append(exc)
                agent.stop()
            finally:
                h.release.set()

        coordinator = threading.Thread(target=coordinate, name="synthetic-signal-coordinator")
        coordinator.start()
        try:
            assert aa.main(["--interval", "60"]) == 0
            coordinator.join(10)
            assert not coordinator.is_alive()
            h.finish()
            jobs = list(h.jobs.jobs_dir.glob("*/job.json"))
            assert len(jobs) == 1
            _assert_completed(h, jobs[0].parent.name)
            assert agent._shutdown_requested and agent._lifecycle_phase == "exited"
            assert h.statuses[-1] == ("drained", "exited")
        finally:
            h.release.set()
            agent.stop()
            h.finish()


def _wait_child_marker(process, marker):
    deadline = time.monotonic() + 20
    output = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while marker.encode() not in output:
            remaining = deadline - time.monotonic()
            assert remaining > 0 and selector.select(remaining), (marker, output)
            chunk = os.read(process.stdout.fileno(), 65536)
            assert chunk, (process.poll(), marker, output)
            output += chunk


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX SIGTERM and flock")
def test_real_sigterm_cli_child_drains_real_queue_and_seals_exact_next(tmp_path):
    code = "from tests.test_finish_accepted_drain import _sigterm_child; import sys; _sigterm_child(sys.argv[1])"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=str(tmp_path),
               ASTRID_SOURCE_ROOT=str(tmp_path / "source/astrid"))
    with _no_live_io():
        process = subprocess.Popen([sys.executable, "-B", "-c", code, str(tmp_path)],
                                   cwd=REPO, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _wait_child_marker(process, "drain-fixture:accepted")
            process.send_signal(signal.SIGTERM)
            _wait_child_marker(process, "drain-fixture:stopped")
            assert process.poll() is None
            workspace = tmp_path / "source/minime/workspace"
            path = workspace / "sovereignty_state.json"
            rows, _ = handoff.history(path)
            assert [r["body"]["kind"] for r in rows] == ["sealed", "restored"]
            assert not list((workspace / "journal").glob("self_study_*.txt"))
            out, err = process.communicate(input=b"release\n", timeout=20)
            assert process.returncode == 0, (out.decode(), err.decode())
            rows, _ = handoff.history(path)
            assert [r["body"]["kind"] for r in rows] == ["sealed", "restored", "sealed"]
            state_before = path.read_bytes()
            state = handoff.parse(state_before)
            assert state["pending_next_action"] == NEXT
            assert rows[-1]["body"]["state_sha256"] == handoff.digest(state_before)
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(aa, "WORKSPACE_DIR", workspace)
                replacement = object.__new__(aa.AutonomousAgent)
                replacement._agent_boot_id = uuid4().hex
                replacement._agent_pid = os.getpid()
                replacement._agent_started_at = "2026-10-12T00:00:00"
                replacement._agent_inputs_at_start = aa.source_inputs(tmp_path / "source/minime")
                receipt = handoff.restore(replacement)
                assert receipt["scheduling_authorized"] is False
                assert receipt["seal_sha256"] == rows[-1]["sha256"]
                assert replacement._pending_next_action == NEXT
                assert replacement._pending_next_selection_id == state["pending_next_selection_id"]
                assert replacement._pending_choice_envelope_v1 == state.get("choice_envelope_v1")
                assert path.read_bytes() == state_before
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.communicate(input=b"release\n", timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()  # Only this test-owned synthetic child.
                    process.communicate(timeout=5)
