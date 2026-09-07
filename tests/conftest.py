"""Keep default autonomy fixtures off the live workspace and engine endpoints."""
import os
import fcntl
from pathlib import Path
import sys

import pytest


LIVE_ROOTS = tuple(Path(p) for p in (
    "/Users/v/other/minime", "/Users/v/other/astrid",
    "/Users/v/other/neural-triple-reservoir",
))


def _live_path(value, dir_fd=None):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return False
    path = Path(os.fsdecode(value))
    if not path.is_absolute() and dir_fd is not None and dir_fd >= 0:
        if sys.platform == "darwin":
            parent = fcntl.fcntl(dir_fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0]
        else:
            parent = os.readlink(f"/proc/self/fd/{dir_fd}")
        path = Path(os.fsdecode(parent)) / path
    path = path.resolve()
    return (not {"__pycache__", ".pytest_cache"}.intersection(path.parts)
            and any(path.is_relative_to(root) for root in LIVE_ROOTS))


def _deny_live_writes(event, args):
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+"))
        writing = writing or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing and _live_path(path):
            raise RuntimeError(f"test attempted live write: {path}")
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename"}:
        if event == "os.rename":
            paths = ((args[0], args[2]), (args[1], args[3]))
        else:
            paths = ((args[0], args[2] if event == "os.mkdir" else args[1]),)
        if any(_live_path(p, fd) for p, fd in paths):
            raise RuntimeError(f"test attempted live filesystem mutation: {event}")
    elif event == "sqlite3.connect" and _live_path(args[0]):
        raise RuntimeError("test attempted live database connection")
    elif event == "socket.connect":
        address = args[1]
        if (isinstance(address, tuple) and len(address) >= 2
                and address[0] in {"localhost", "127.0.0.1", "::1"}
                and address[1] in {7878, 7879, 7880, 8090, 11434}):
            raise RuntimeError("test attempted live runtime connection")


sys.addaudithook(_deny_live_writes)


@pytest.fixture(autouse=True)
def isolated_default_autonomy_paths(tmp_path, monkeypatch, request):
    import autonomous_agent as aa
    # These four read-only layout tests deliberately inspect production defaults.
    # The process-wide mutation guard still applies to them.
    if request.node.path.name == "test_minime_autonomy_boundaries.py":
        return
    base = tmp_path / "default-agent"
    workspace = base / "workspace"
    runtime = workspace / "runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(aa, "BASE_DIR", base)
    monkeypatch.setattr(aa, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(aa, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(aa, "DB_PATH", base / "test.db")
    import native_comm
    import visual_frame_service
    for module in (native_comm, visual_frame_service):
        for name, value in list(vars(module).items()):
            if isinstance(value, Path) and value.is_relative_to(LIVE_ROOTS[0]):
                monkeypatch.setattr(module, name, base / value.relative_to(LIVE_ROOTS[0]))
