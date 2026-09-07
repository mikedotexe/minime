"""Keep default autonomy fixtures off the live workspace and engine endpoints."""
import os
import fcntl
from pathlib import Path
import sys

import pytest


LIVE_ROOTS = tuple(Path(p) for p in (
    "/Users/v/other/minime", "/Users/v/other/astrid",
    "/Users/v/other/neural-triple-reservoir", "/Users/v/other/shared",
    "/Users/v/other/research", "/Users/v/other/autoresearch",
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
        for path, fd in paths:
            if _live_path(path, fd):
                raise RuntimeError(f"test attempted live filesystem mutation: {event}: {path}")
    elif event == "sqlite3.connect" and _live_path(args[0]):
        raise RuntimeError("test attempted live database connection")
    elif event == "socket.connect":
        address = args[1]
        if (isinstance(address, tuple) and len(address) >= 2
                and address[0] in {"localhost", "127.0.0.1", "::1"}
                and address[1] in {3040, 7878, 7879, 7880, 7881, 8090, 11434}):
            raise RuntimeError("test attempted live runtime connection")
    elif event == "subprocess.Popen":
        executable, command, cwd, _ = args
        arguments = command if isinstance(command, (list, tuple)) else [command]
        if _live_path(cwd) or any(_live_path(value) for value in [executable, *arguments]):
            raise RuntimeError("test attempted subprocess against live checkout")


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
    # Continuity projections also discover peer experiments and shared ledgers.
    # Their defaults must be private even when a test supplies its own local store.
    for name in ("ASTRID_BRIDGE_INBOX_DIR", "ASTRID_BRIDGE_INBOX_PATH",
                 "ASTRID_SELF_STUDY_REVIEW_DIR", "SHARED_INVESTIGATION_DIR",
                 "CORRESPONDENCE_LEDGER_PATH", "PHASE_TRANSITIONS_LEDGER_PATH",
                 "MIKE_RESEARCH_ROOT", "AUTORESEARCH_ROOT"):
        original = getattr(aa, name)
        root = next(root for root in LIVE_ROOTS if original.is_relative_to(root))
        monkeypatch.setattr(aa, name, base / "external" / root.name / original.relative_to(root))
    monkeypatch.setattr(aa.AutonomousAgent, "SHARED_COLLAB_DIR",
                        base / "external" / "shared" / "collaborations")
    for name in ("ASTRID_INBOX_DIR", "BRIDGE_INBOX"):
        monkeypatch.setattr(aa.AutonomousAgent, name, aa.ASTRID_BRIDGE_INBOX_DIR)
    # Definition-time defaults retain the original Path despite alias redirection.
    monkeypatch.setattr(aa._latest_lived_term_review_path, "__defaults__",
                        (aa.ASTRID_SELF_STUDY_REVIEW_DIR,))
    for helper in (aa.render_lived_term_bridge_action, aa.render_regulator_map_bridge_action):
        monkeypatch.setattr(helper, "__kwdefaults__",
                            {**helper.__kwdefaults__, "review_root": aa.ASTRID_SELF_STUDY_REVIEW_DIR})
    # Exercise registry consumers against the checked-in seed, never live grants.
    from minime_autonomy import envelope_registry as er
    registry_path = workspace / "self_regulation" / "envelope_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_bytes(Path(er.__file__).with_name("envelope_registry_seed.json").read_bytes())
    monkeypatch.setattr(er, "DEFAULT_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(er.load_registry, "__defaults__", (registry_path,))
    for helper in (er.envelope_for, er.channel_range_for):
        monkeypatch.setattr(helper, "__kwdefaults__",
                            {**helper.__kwdefaults__, "path": registry_path})
    import native_comm
    import visual_frame_service
    for module in (native_comm, visual_frame_service):
        for name, value in list(vars(module).items()):
            if isinstance(value, Path) and value.is_relative_to(LIVE_ROOTS[0]):
                monkeypatch.setattr(module, name, base / value.relative_to(LIVE_ROOTS[0]))
