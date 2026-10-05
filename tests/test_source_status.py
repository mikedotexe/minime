"""Owned filesystem faults through the real source-status adapter and helper."""
import errno
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

import autonomous_agent as aa
from minime_autonomy import source_status as status_io


def full():
    return OSError(errno.ENOSPC, "synthetic source-status capacity failure")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    with mock.patch.dict(os.environ, {"HOME": str(root), "TMPDIR": str(root),
                                     "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, clear=True):
        monkeypatch.setattr(sys, "dont_write_bytecode", True)
        for module, name in ((subprocess, "run"), (subprocess, "Popen"), (os, "kill"),
                             (os, "killpg"), (os, "execv"), (socket.socket, "connect"),
                             (socket.socket, "connect_ex"), (socket.socket, "bind")):
            monkeypatch.setattr(module, name, mock.Mock(side_effect=AssertionError("no live activity")))
        yield


@pytest.fixture
def agent(tmp_path):
    root = tmp_path.resolve()
    value = object.__new__(aa.AutonomousAgent)
    value._agent_pid = 12345
    value._agent_boot_id = "a" * 32
    value._agent_started_at = "2026-10-05T12:00:00"
    value._agent_inputs_at_start = {"synthetic.py": "b" * 64}
    value._agent_source_path = root / "synthetic.py"
    value._agent_source_path.write_text("# synthetic source\n")
    value._lifecycle_phase = "initializing"
    value._stop_event = threading.Event()
    value._llm_job_threads = []
    value.running = False
    value._source_status_path = lambda: root / "runtime" / status_io.STATUS_NAME
    return value


def seed(agent):
    return agent._write_source_status("heartbeat")


def inode(fd, path):
    return path.exists() and (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (
        path.stat().st_dev, path.stat().st_ino)


def test_actual_adapter_preserves_complete_status_and_private_mode(agent):
    agent._next_handoff_restore = {"seal_sha256": "c" * 64, "scheduling_authorized": False}
    agent._lifecycle_phase = "idle"
    expected = agent._current_source_status("startup")
    with mock.patch.object(agent, "_current_source_status", return_value=expected):
        returned = agent._write_source_status("startup")
    path = agent._source_status_path()
    assert returned == json.loads(path.read_bytes()) == expected
    assert returned["source_inputs_at_start"] == agent._agent_inputs_at_start
    assert returned["next_handoff_restore"] == agent._next_handoff_restore
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".source-status-*"))


def test_actual_tmp_publication_keeps_workspace_symlink_refusal(agent):
    with tempfile.TemporaryDirectory(prefix="source-status-", dir="/tmp") as temporary:
        root = Path(temporary)
        path = root / "runtime" / status_io.STATUS_NAME
        agent._source_status_path = lambda: path
        expected = agent._write_source_status("startup")
        assert json.loads(path.read_bytes()) == expected
        assert status_io.checked_path(path) == path.resolve()
        retained = path.read_bytes()
        linked = root / "linked-runtime"
        linked.symlink_to(path.parent, target_is_directory=True)
        agent._source_status_path = lambda: linked / status_io.STATUS_NAME
        with pytest.raises(ValueError, match="unsafe_source_status_path"):
            agent._write_source_status("drained")
        assert path.read_bytes() == retained
        assert not list(path.parent.glob(".source-status-*"))


@pytest.mark.parametrize("name", ["tmp", "var"])
@pytest.mark.parametrize("case", ["verified", "foreign_owner", "wrong_target", "non_darwin"])
def test_only_verified_macos_system_aliases_normalize(name, case, monkeypatch):
    alias = Path("/") / name
    target = Path("/private") / name
    path = alias / "synthetic-source-status" / status_io.STATUS_NAME
    real_link, real_lstat, real_resolve = Path.is_symlink, Path.lstat, Path.resolve
    monkeypatch.setattr(status_io.sys, "platform", "linux" if case == "non_darwin" else "darwin")
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == alias or real_link(p))
    monkeypatch.setattr(Path, "lstat", lambda p: (
        SimpleNamespace(st_uid=1 if case == "foreign_owner" else 0) if p == alias else real_lstat(p)))
    monkeypatch.setattr(Path, "resolve", lambda p, *args, **kwargs: (
        (Path("/hostile") if case == "wrong_target" else target) if p == alias
        else real_resolve(p, *args, **kwargs)))
    if case == "verified":
        assert status_io.checked_path(path) == target / path.relative_to(alias)
    else:
        error = "unsafe_source_status_path" if case == "non_darwin" else "unexpected_system_path_alias"
        with pytest.raises(ValueError, match=error):
            status_io.checked_path(path)


@pytest.mark.parametrize("boundary", ["create", "partial", "replace"])
def test_enospc_before_publication_keeps_old_status_and_exact_retry(agent, boundary):
    seed(agent)
    path = agent._source_status_path()
    previous = path.read_bytes()
    expected = agent._current_source_status("startup")
    real_open, real_write = os.open, os.write

    def fail_create(name, *args, **kwargs):
        if str(name).startswith(".source-status-"):
            raise full()
        return real_open(name, *args, **kwargs)

    def partial(fd, raw):
        real_write(fd, raw[:17])
        raise full()

    faults = {"create": ("open", fail_create), "partial": ("write", partial),
              "replace": ("replace", mock.Mock(side_effect=full()))}
    name, fault = faults[boundary]
    with mock.patch.object(agent, "_current_source_status", return_value=expected), \
            mock.patch.object(status_io.os, name, fault):
        with pytest.raises(OSError) as failure:
            agent._write_source_status("startup")
        assert failure.value.errno == errno.ENOSPC
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(".source-status-*"))
    frozen = agent._source_status_publisher.pending[1]
    assert json.loads(frozen) == expected
    changed = {**expected, "checked_at": "a later clock", "llm_jobs": {"newer_projection": True}}
    with mock.patch.object(agent, "_current_source_status", return_value=changed):
        assert agent._write_source_status("startup") == expected
    assert path.read_bytes() == frozen


@pytest.mark.parametrize("boundary", ["file", "directory"])
def test_visible_mandatory_status_requires_retry_fsync_without_rewrite(agent, boundary):
    seed(agent)
    path = agent._source_status_path()
    before = path.read_bytes()
    real_sync = os.fsync

    def fail_published(fd):
        visible = path.read_bytes() != before
        target = inode(fd, path if boundary == "file" else path.parent)
        if visible and target:
            raise full()
        return real_sync(fd)

    with mock.patch.object(status_io.os, "fsync", fail_published):
        with pytest.raises(OSError):
            agent._write_source_status("startup")
        retained = path.read_bytes()
        assert json.loads(retained)["reason"] == "startup"
        with mock.patch.object(status_io.os, "replace", side_effect=AssertionError("retry rewrote status")):
            for _ in range(3):
                with pytest.raises(OSError):
                    agent._write_source_status("startup")
                assert path.read_bytes() == retained
    with mock.patch.object(status_io.os, "write", side_effect=AssertionError("retry wrote bytes")), \
            mock.patch.object(status_io.os, "replace", side_effect=AssertionError("retry replaced bytes")), \
            mock.patch.object(status_io.os, "fsync", wraps=real_sync) as sync:
        assert agent._write_source_status("startup") == json.loads(retained)
        assert sync.call_count >= 3  # Containing directory name, target, publication directory.
    assert agent._source_status_publisher.pending is None


def test_short_writes_complete_and_zero_write_refuses(agent):
    path = agent._source_status_path()
    real_write = os.write
    with mock.patch.object(status_io.os, "write", lambda fd, raw: real_write(fd, raw[:11])):
        expected = agent._write_source_status("startup")
    assert json.loads(path.read_bytes()) == expected
    previous = path.read_bytes()
    with mock.patch.object(status_io.os, "write", return_value=0):
        with pytest.raises(OSError, match="no progress"):
            agent._write_source_status("drained")
    assert path.read_bytes() == previous


def test_optional_failure_is_best_effort_but_cannot_overwrite_pending_mandatory(agent):
    seed(agent)
    path = agent._source_status_path()
    previous = path.read_bytes()
    with mock.patch.object(status_io, "publish", side_effect=full()):
        assert agent._write_source_status("idle")["reason"] == "idle"
        assert agent._source_status_publisher.pending is None
        with pytest.raises(OSError):
            agent._write_source_status("startup")
    pending = agent._source_status_publisher.pending
    with mock.patch.object(status_io, "publish", side_effect=AssertionError("heartbeat replaced pending ack")):
        assert agent._write_source_status("heartbeat")["reason"] == "heartbeat"
    assert agent._source_status_publisher.pending == pending
    assert path.read_bytes() == previous
    with pytest.raises(ValueError, match="retry_conflict"):
        agent._write_source_status("drained")
    agent._agent_boot_id = "d" * 32
    with pytest.raises(ValueError, match="retry_conflict"):
        agent._write_source_status("startup")


def test_explicit_byte_cap_including_newline_and_nonfinite_refusal(tmp_path):
    path = tmp_path.resolve() / "runtime" / status_io.STATUS_NAME
    overhead = len(status_io.encode({"value": ""}))
    payload = {"value": "x" * (status_io.MAX_STATUS_BYTES - overhead)}
    raw = status_io.encode(payload)
    assert len(raw) == status_io.MAX_STATUS_BYTES
    status_io.publish(path, raw)
    assert path.read_bytes() == raw
    for value in ({"value": payload["value"] + "x"}, {"value": float("nan")}):
        with pytest.raises(ValueError):
            status_io.Publisher().write(path, value, mandatory=True)
        assert path.read_bytes() == raw


@pytest.mark.parametrize("damage", ["target_link", "parent_link", "hardlink", "writable", "fifo", "foreign"])
def test_unsafe_paths_refuse_without_touching_target(agent, damage):
    seed(agent)
    path = agent._source_status_path()
    previous = path.read_bytes()
    other = path.parent.parent / "retained.json"
    if damage == "target_link":
        path.rename(other)
        path.symlink_to(other)
    elif damage == "parent_link":
        directory = path.parent.with_name("retained-runtime")
        path.parent.rename(directory)
        path.parent.symlink_to(directory, target_is_directory=True)
    elif damage == "hardlink":
        os.link(path, other)
    elif damage == "writable":
        path.chmod(0o666)
    elif damage == "fifo":
        path.rename(other)
        os.mkfifo(path)
    with mock.patch.object(status_io.os, "getuid", return_value=os.getuid() + (damage == "foreign")):
        with pytest.raises((OSError, ValueError)):
            agent._write_source_status("startup")
    assert (other if damage in {"target_link", "fifo"} else path).read_bytes() == previous


def test_target_drift_before_replace_is_preserved(agent):
    seed(agent)
    path = agent._source_status_path()
    real_write = os.write

    def change_target(fd, raw):
        path.write_text('{"foreign":"newer"}')
        return real_write(fd, raw)

    with mock.patch.object(status_io.os, "write", change_target):
        with pytest.raises(ValueError, match="source_status_changed"):
            agent._write_source_status("startup")
    assert path.read_text() == '{"foreign":"newer"}'
    assert not list(path.parent.glob(".source-status-*"))


def test_startup_publication_failure_precedes_all_boot_work(agent):
    agent._check_source_reload_required = mock.Mock()
    for name in ("_restore_sovereignty_state", "_apply_pending_next_override_if_present", "_verify_sovereignty"):
        setattr(agent, name, mock.Mock(side_effect=AssertionError("boot work after failed ack")))
    with mock.patch.object(aa.maintenance_next, "restore", return_value={"synthetic": "restored"}), \
            mock.patch.object(status_io, "publish", side_effect=full()):
        with pytest.raises(OSError):
            agent.start()
    assert not agent.running and agent._shutdown_requested
    assert agent._lifecycle_phase == "recovery_blocked"
    for name in ("_restore_sovereignty_state", "_apply_pending_next_override_if_present", "_verify_sovereignty"):
        getattr(agent, name).assert_not_called()


def test_startup_ack_is_exact_before_boot_work(agent):
    agent._check_source_reload_required = mock.Mock()
    restored = {"synthetic": "exact restore", "scheduling_authorized": False}
    observed = []

    def boot():
        observed.append(json.loads(agent._source_status_path().read_bytes()))
        agent.running = False

    agent._restore_sovereignty_state = boot
    agent._apply_pending_next_override_if_present = mock.Mock()
    with mock.patch.object(aa.maintenance_next, "restore", return_value=restored):
        agent.start()
    assert observed[0]["reason"] == "startup"
    assert observed[0]["next_handoff_restore"] == restored


def test_drain_failure_propagates_after_join_seal_and_retry_keeps_exact_status(agent):
    events = []
    agent._llm_job_threads = [mock.Mock(join=lambda: events.append("joined"))]
    seal = {"synthetic": "exact seal"}
    publish = status_io.publish

    def fail_drained(path, raw):
        if json.loads(raw)["reason"] == "drained":
            events.append("failed_ack")
            raise full()
        return publish(path, raw)

    def sealed(_):
        events.append("sealed")
        return seal

    agent.stop()
    with mock.patch.object(aa.maintenance_next, "seal", sealed), \
            mock.patch.object(status_io, "publish", fail_drained):
        with pytest.raises(OSError):
            agent.wait_for_llm_jobs()
    assert events == ["joined", "sealed", "failed_ack"]
    assert agent._lifecycle_phase == "recovery_blocked" and not agent.running
    pending = agent._source_status_publisher.pending[1]
    assert json.loads(pending)["next_handoff_seal"] == seal
    with mock.patch.object(aa.maintenance_next, "seal", return_value=seal):
        agent.wait_for_llm_jobs()
    assert agent._source_status_path().read_bytes() == pending
    assert agent._lifecycle_phase == "exited"
