"""Synthetic, populated-state qualification of operation-local render reuse."""

from copy import deepcopy
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import projection_snapshot as ps
from tests.test_action_continuity_performance import STATE, _normalized, _snapshot, populated_store


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(aa.ActionContinuityStore, "_now", lambda self: "2026-10-18T12:00:00Z")
    monkeypatch.setattr(aa.ActionContinuityStore, "_unique_thread_id", lambda self, title: "th_synthetic")
    monkeypatch.setattr(aa.ActionContinuityStore, "_unique_action_id", lambda self, base: "act_synthetic")
    root = tmp_path.resolve() / "populated"
    root.mkdir()
    monkeypatch.setattr(aa, "SHARED_INVESTIGATION_DIR", root / "shared")
    large = os.environ.get("MINIME_RENDER_REUSE_PROFILE_OUT")
    store, event = populated_store(root, rows=2000 if large else 128, padding=4096 if large else 64)
    for index in range(2000 if large else 12):
        job = root / "llm_jobs" / "jobs" / f"job_{index}" / "job.json"
        job.parent.mkdir(parents=True)
        job.write_text(json.dumps({"job_id": f"job_{index}", "action_id": f"act_fixture_{index}",
                                   "status": "completed", "worker_status": "completed"}))
        journal = root / "journal" / f"synthetic_{index}.txt"
        journal.parent.mkdir(exist_ok=True)
        journal.write_text("Synthetic public observation.\n")
    thread = json.loads((store._thread_dir(event["thread_id"]) / "thread.json").read_text())
    return store, thread, event


def prepare(store, thread, scope):
    return store._refresh_projection_freshness_v1(thread, source="synthetic", render_snapshot=scope)


def persist(store, thread):
    store._write_json(store._thread_dir(thread["thread_id"]) / "thread.json", thread)


def test_populated_clean_journals_and_jobs_reuse_full_postrefresh_output(fixture, monkeypatch):
    store, thread, _ = fixture
    compute = Mock(wraps=store._thread_projection)
    monkeypatch.setattr(store, "_thread_projection", compute)
    with ps.ProjectionReadScope(store, thread) as scope:
        expected = prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        actual = ps.projection_for_next_md(store, thread, scope)
        assert compute.call_count == 2  # original pre AND post projections
        assert actual == expected == store._thread_projection(thread)
        assert actual is not expected
        store._write_next_md(thread)
        path = store._thread_dir(thread["thread_id"]) / "next.md"
        normal = path.read_bytes()
        with monkeypatch.context() as patcher:
            patcher.setattr(store, "_thread_projection", lambda _: actual)
            store._write_next_md(thread)
        assert path.read_bytes() == normal


@pytest.mark.parametrize("operation", ["write", "read", "finish"])
def test_actual_runtime_file_db_parity_and_reduced_calls(fixture, tmp_path, monkeypatch, operation):
    import shutil
    template, original_thread, event = fixture
    results, files, counts, elapsed = [], [], [], []
    for reuse, name in ((False, "baseline"), (True, "reuse___")):
        root = tmp_path.resolve() / name
        shutil.copytree(template.workspace_dir, root)
        store = aa.ActionContinuityStore(root, db_path=root / "continuity.sqlite3")
        thread = deepcopy(original_thread)
        counter = Mock(wraps=store._thread_projection)
        with monkeypatch.context() as patcher:
            patcher.setattr(store, "_thread_projection", counter)
            if not reuse:
                patcher.setattr(ps.ProjectionReadScope, "project", lambda self: self.store._thread_projection(self.thread))
            started = time.perf_counter()
            if operation == "write":
                store._write_thread(thread)
                store._mirror_thread(thread)
                result = thread
            elif operation == "read":
                result = store._read_thread(thread["thread_id"])
            else:
                result = store.finish_action(deepcopy(event), "handled", "Synthetic output saved", STATE)
            elapsed.append(time.perf_counter() - started)
        results.append(_normalized(result, root))
        files.append(_snapshot(root))
        counts.append(counter.call_count)
    assert results[0] == results[1]
    assert files[0] == files[1]
    assert counts[1] < counts[0], counts
    if operation in {"write", "read"}:
        assert counts == [3, 2]
    else:
        assert counts == [21, 14 if original_thread.get("active_experiment_id") else 15]
    destination = os.environ.get("MINIME_RENDER_REUSE_PROFILE_OUT")
    if destination:
        Path(destination).write_text(json.dumps({
            "operation": operation, "rows": 2000, "padding": 4096, "jobs_and_journals": 2000,
            "baseline_s": elapsed[0], "reuse_s": elapsed[1], "projections": counts,
            "normalized_full_file_db_result_parity": True,
            "normalization": "fixture roots, filesystem identity fields, DB timestamps",
        }, indent=2) + "\n")


@pytest.mark.parametrize("change", ["job", "journal", "event", "proposal", "new_job", "new_journal", "missing_ledger"])
def test_dependency_and_discovery_changes_force_fresh(fixture, change):
    store, thread, _ = fixture
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        if change == "job":
            (store.workspace_dir / "llm_jobs/jobs/job_0/job.json").write_text('{"status":"running"}')
        elif change == "journal":
            (store.workspace_dir / "journal/synthetic_0.txt").write_text("Changed synthetic observation.\n")
        elif change == "event":
            store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl", {"status": "handled"})
        elif change == "proposal":
            store._append_jsonl(store.proposals_path, {"action": "PASS"})
        elif change == "new_job":
            (store.workspace_dir / "llm_jobs/jobs/new_job").mkdir()
        elif change == "new_journal":
            (store.workspace_dir / "journal/new.txt").write_text("Synthetic new file.\n")
        else:
            store._being_memory_path(thread["thread_id"]).touch()
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("change", ["rewrite", "replace", "delete"])
def test_external_same_size_mtime_source_changes_are_rejected(fixture, change):
    store, thread, _ = fixture
    path = store.workspace_dir / "journal/synthetic_0.txt"
    path.write_text("Synthetic A\n")
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        script = """
import os, pathlib, sys
path, change = pathlib.Path(sys.argv[1]), sys.argv[2]
before = path.stat()
if change == 'delete':
    path.unlink()
else:
    target = path.with_suffix('.new') if change == 'replace' else path
    target.write_text('Synthetic B\\n')
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    if change == 'replace':
        os.replace(target, path)
"""
        subprocess.run([sys.executable, "-B", "-c", script, str(path), change], check=True)
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("which", ["thread", "projection", "disk", "receipt", "config"])
def test_mutation_and_saved_receipt_checks(fixture, monkeypatch, which):
    store, thread, _ = fixture
    with ps.ProjectionReadScope(store, thread) as scope:
        projection = prepare(store, thread, scope)
        persist(store, thread)
        if which == "thread":
            thread["compression_flags"].append("synthetic")
        elif which == "projection":
            projection["current_next"] = "PASS"
        elif which == "disk":
            value = deepcopy(thread)
            value["current_next"] = "PASS"
            persist(store, value)
        elif which == "receipt":
            thread["projection_freshness_v1"]["source"] = "changed"
        else:
            monkeypatch.setattr(store, "memory_draft_active_window_hours", 24)
        assert scope.take(store, thread) is None


def test_failed_read_is_not_hidden_by_unchanged_stats(fixture, monkeypatch):
    store, thread, _ = fixture
    source = store.workspace_dir / "journal/synthetic_0.txt"
    normal = Path.read_text

    def fail_once(path, *args, **kwargs):
        if path == source:
            raise OSError("synthetic temporary read error")
        return normal(path, *args, **kwargs)

    with ps.ProjectionReadScope(store, thread) as scope:
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "read_text", fail_once)
            prepare(store, thread, scope)
        persist(store, thread)
        assert "read_failed" in scope.observation.failures
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("kind", ["malformed", "missing"])
def test_missing_or_malformed_job_read_disables_reuse(fixture, kind):
    store, thread, _ = fixture
    path = store.workspace_dir / "llm_jobs/jobs/job_0/job.json"
    path.write_text("{broken") if kind == "malformed" else path.unlink()
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None


def test_hygiene_writes_still_execute_and_disable_reuse(fixture):
    store, thread, _ = fixture
    (store.workspace_dir / "journal/action_thread_machine.txt").write_text(
        '=== ACTION THREAD ===\nconveyor_v1:\n{"policy":"experiment_conveyor_v1"}\n'
    )
    path = store.workspace_dir / "runtime/journal_hygiene_status.json"
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert "attempted_hygiene_write" in scope.observation.failures
        before = json.loads(path.read_text())["source_scanner_skips"]
        ps.projection_for_next_md(store, thread, scope)
        assert json.loads(path.read_text())["source_scanner_skips"] == before + 2


def clock(monkeypatch, initial):
    state = [initial]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state[0].astimezone(tz) if tz else state[0].replace(tzinfo=None)

    monkeypatch.setattr(aa, "datetime", Clock)
    return state


@pytest.mark.parametrize("shift, reusable", [(1, True), (120, False), (-1, False)])
def test_running_age_predicate_and_clock_reversal(fixture, monkeypatch, shift, reusable):
    store, thread, _ = fixture
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    current = clock(monkeypatch, now)
    store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl", {
        "action_id": "act_running", "status": "llm_running", "canonical_action": "REST",
        "started_at": (now - timedelta(minutes=44)).isoformat(),
    })
    with ps.ProjectionReadScope(store, thread) as scope:
        prior = prepare(store, thread, scope)
        persist(store, thread)
        assert prior["stale_running_count"] == 0
        current[0] += timedelta(seconds=shift)
        result = scope.take(store, thread)
        assert (result is not None) == reusable
        if shift == 120:
            assert store._thread_projection(thread)["stale_running_count"] == 1


@pytest.mark.parametrize("kind", ["experiment", "draft"])
def test_unqualified_branches_remain_fresh(fixture, kind):
    store, thread, _ = fixture
    if kind == "experiment":
        thread["experiment_summary"] = {"experiment_id": "exp_minime_synthetic", "status": "paused"}
    else:
        store._append_jsonl(store._being_memory_path(thread["thread_id"]), {
            "record_schema": "being_memory_v1", "record_type": "draft", "created_at": store._now(),
        })
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None


def test_context_restores_and_snapshot_is_single_use(fixture):
    store, thread, _ = fixture
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        assert ps._CURRENT.get() is None
        persist(store, thread)
        assert scope.take(store, thread) is not None
        assert scope.take(store, thread) is None
    assert scope.take(store, thread) is None
    assert ps._CURRENT.get() is None


def test_projection_exception_restores_context(fixture, monkeypatch):
    store, thread, _ = fixture
    monkeypatch.setattr(store, "_thread_projection", Mock(side_effect=OSError("synthetic")))
    with ps.ProjectionReadScope(store, thread) as scope:
        with pytest.raises(OSError):
            scope.project()
        assert ps._CURRENT.get() is None


def test_source_changes_during_observed_projection_recompute(fixture, monkeypatch):
    store, thread, _ = fixture
    source = store.workspace_dir / "journal/synthetic_0.txt"
    normal = store._recent_constraint_release_trajectory_sources

    def reader(*args, **kwargs):
        result = normal(*args, **kwargs)
        if ps._CURRENT.get() is not None:
            source.write_text("Concurrent synthetic replacement.\n")
        return result

    monkeypatch.setattr(store, "_recent_constraint_release_trajectory_sources", reader)
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None
        assert "discovery_changed" in scope.observation.failures


def test_snapshot_cannot_cross_execution_threads(fixture):
    store, thread, _ = fixture
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(scope.take, store, thread).result() is None
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("kind", ["symlink", "bound", "malformed_event", "missing_proposals"])
def test_uncertain_inputs_and_observation_bound_recompute(fixture, monkeypatch, kind):
    store, thread, _ = fixture
    if kind == "symlink":
        (store.workspace_dir / "journal/link.txt").symlink_to("synthetic_0.txt")
    elif kind == "bound":
        monkeypatch.setattr(ps, "MAX_IDENTITIES", 4)
    elif kind == "malformed_event":
        with (store._thread_dir(thread["thread_id"]) / "events.jsonl").open("a") as stream:
            stream.write("{broken\n")
    else:
        store.proposals_path.unlink()
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.observation.failures
        assert scope.take(store, thread) is None


def test_projection_io_closure_requires_explicit_observation_or_fallback():
    """A new direct reader/clock in the closure requires a dependency audit."""
    source = Path(aa.ActionContinuityStore._thread_projection.__wrapped__.__code__.co_filename).read_text()
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "ActionContinuityStore")
    methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    pending, reachable = ["_thread_projection"], set()
    while pending:
        name = pending.pop()
        if name in reachable or name not in methods:
            continue
        reachable.add(name)
        for call in ast.walk(methods[name]):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in {"self", "cls", "ActionContinuityStore"}):
                pending.append(call.func.attr)
    io_attributes = {"read_text", "read_bytes", "open", "glob", "rglob", "iterdir", "exists",
                     "stat", "lstat", "now", "time", "write_text", "write_bytes",
                     "_write_json", "reverse_lines", "metadata_snapshot"}
    io_methods = {
        name for name in reachable
        if any(isinstance(call, ast.Call) and (
            isinstance(call.func, ast.Attribute) and call.func.attr in io_attributes
            or isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "research_transactions" and call.func.attr in {"rows", "active_budget"}
            or isinstance(call.func, ast.Name) and call.func.id in {"open", "saved_return_support"}
        ) for call in ast.walk(methods[name]))
    }
    observed = {
        "_active_memory_draft_triage_rows", "_authority_gate_rows", "_being_memory_rows",
        "_continuity_session_draft_rows", "_continuity_session_rows", "_latest_research_dossier_records",
        "_legacy_memory_retention_rows", "_proposal_diagnostics", "_read_experiments",
        "_recent_constraint_release_trajectory_sources", "_recent_display_events", "_recent_events",
        "_recent_interpretation_risk_sources", "_repeated_action_cadence_rows", "_return_support_v1",
        "_terminal_jobs_by_action_id", "_stale_running_action_diagnostics",
        "_research_budget_rows",
        "_recent_experiment_runs", "_list_shared_investigations",
        "_latest_decompose_snapshot_for_experiment",
    }
    rejected = {
        "_being_memory_draft_triage_v1", "_now", "_peer_active_experiment",
        "_record_journal_hygiene_skip",
    }
    # Observe actual decision timestamps, not merely the preceding ledger read.
    authority_clocks = {
        "_active_authority_budget", "_active_research_budget", "_authority_budget_status_v1",
        "_authority_token_status", "_latest_sovereign_loop", "_research_budget_status_v1",
    }
    assert io_methods == observed | rejected | authority_clocks
    for name in observed | rejected | authority_clocks:
        node = methods[name]
        start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
        assert "projection_reads." in "\n".join(source.splitlines()[start - 1:node.end_lineno]), name
