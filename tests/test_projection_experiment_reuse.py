"""Local experiment render qualification; synthetic stores only."""

from unittest.mock import Mock
import json

import pytest

import autonomous_agent as aa
from minime_autonomy import job_timing
from minime_autonomy import projection_snapshot as ps
from tests.test_projection_render_reuse import fixture, persist, prepare
from tests.test_projection_render_reuse import test_actual_runtime_file_db_parity_and_reduced_calls as run_parity


def populate(store, thread, status="active"):
    record = {
        "schema_version": 1, "experiment_id": "exp_minime_legacy_synthetic",
        "thread_id": thread["thread_id"], "title": "Synthetic legacy experiment",
        "question": "Synthetic question", "status": status,
        "authority_envelope": "read_only", "created_at": store._now(),
        "updated_at": store._now(), "planned_next": "SELF_STUDY MAP",
        "peer_review_refs": [], "branch_refs": [],
    }
    store._append_jsonl(store._experiments_path(thread["thread_id"]), record)
    store._append_jsonl(store._experiment_runs_path(thread["thread_id"]), {
        "experiment_id": record["experiment_id"], "run_id": "run_synthetic",
        "action_text": "SELF_STUDY MAP", "stage": "read", "status": "handled",
        "result_summary": "Synthetic retained account", "artifacts": [],
    })
    (store.workspace_dir / "runtime").mkdir(exist_ok=True)
    thread["active_experiment_id"] = record["experiment_id"] if status == "active" else None
    thread["experiment_summary"] = store._experiment_summary(record)
    persist(store, thread)
    return record


@pytest.mark.parametrize("status", ["active", "paused", "held", "complete"])
def test_local_experiment_reuses_exact_postmutation_projection(fixture, monkeypatch, status):
    store, thread, _ = fixture
    populate(store, thread, status)
    # Qualify a stable return view. A changed saved NEXT during the intentional
    # thread write must still fall back (covered independently below).
    store._apply_current_next_projection_v1(thread, store._thread_projection(thread))
    persist(store, thread)
    counter = Mock(wraps=store._thread_projection)
    monkeypatch.setattr(store, "_thread_projection", counter)
    with ps.ProjectionReadScope(store, thread) as scope:
        expected = prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        actual = ps.projection_for_next_md(store, thread, scope)
        assert counter.call_count == 2, scope.observation.failures
        assert actual == expected == store._thread_projection(thread)


def test_changed_return_receipt_after_intentional_write_falls_back(fixture):
    store, thread, _ = fixture
    populate(store, thread, "paused")
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None
        assert "return_support_changed" in scope.observation.failures


@pytest.mark.parametrize("operation", ["write", "read", "finish"])
def test_populated_legacy_experiment_full_file_and_database_parity(fixture, tmp_path, monkeypatch, operation):
    store, thread, _ = fixture
    populate(store, thread)
    run_parity(fixture, tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("change", ["experiment", "run", "dossier", "authority", "decompose", "shared", "shared_child"])
def test_experiment_dependencies_changed_after_projection_force_fresh(fixture, change):
    store, thread, _ = fixture
    populate(store, thread)
    shared = store._shared_investigation_root()
    shared.mkdir()
    (shared / "empty").mkdir()
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        paths = {
            "experiment": store._experiments_path(thread["thread_id"]),
            "run": store._experiment_runs_path(thread["thread_id"]),
            "dossier": store._research_dossier_path(thread["thread_id"]),
            "authority": store._authority_gate_path(thread["thread_id"]),
            "decompose": store.workspace_dir / "runtime/decompose_snapshots.jsonl",
            "shared_child": shared / "empty/investigation.json",
        }
        if change == "shared":
            (shared / "new").mkdir()
        else:
            with paths[change].open("a") as handle:
                handle.write('{}\n')
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("kind", ["populated", "malformed", "scalar"])
def test_shared_discovery_is_not_reused_when_populated_or_unreadable(fixture, kind):
    store, thread, _ = fixture
    populate(store, thread)
    path = store._shared_investigation_root() / "synthetic/investigation.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"id":"si_synthetic"}' if kind == "populated" else '{broken' if kind == "malformed" else '[]')
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None


@pytest.mark.parametrize("kind", ["experiment", "run", "authority", "decompose"])
def test_corrupt_local_tail_preserved_and_not_reused(fixture, kind):
    store, thread, _ = fixture
    populate(store, thread)
    path = {
        "experiment": store._experiments_path(thread["thread_id"]),
        "run": store._experiment_runs_path(thread["thread_id"]),
        "authority": store._authority_gate_path(thread["thread_id"]),
        "decompose": store.workspace_dir / "runtime/decompose_snapshots.jsonl",
    }[kind]
    with path.open("a") as handle:
        handle.write('{broken\n')
    original = path.read_bytes()
    with ps.ProjectionReadScope(store, thread) as scope:
        try:
            prepare(store, thread, scope)
        except ValueError:
            pass  # Existing strict transaction reader may refuse the corrupt ledger.
        persist(store, thread)
        assert scope.take(store, thread) is None
    assert path.read_bytes() == original


@pytest.mark.parametrize("shift,reusable", [(0.5, True), (1, False), (2, False), (-1, False), (float("nan"), False)])
def test_expiry_and_clock_reversal_invalidate_only_render(fixture, monkeypatch, shift, reusable):
    store, thread, _ = fixture
    record = populate(store, thread)
    now = [1792324800.0]
    monkeypatch.setattr(aa.time, "time", lambda: now[0])
    store._append_jsonl(store._authority_gate_path(thread["thread_id"]), {
        "record_schema": "research_budget_v1", "record_type": "research_budget_approval",
        "experiment_id": record["experiment_id"], "budget_id": "budget_synthetic",
        "scope": "read_only_research", "max_actions": 4, "status": "active",
        "expires_at_unix_s": now[0] + 1,
    })
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        now[0] += shift
        assert (scope.take(store, thread) is not None) == reusable
        if shift == shift:
            active = store._active_research_budget(thread["thread_id"], record["experiment_id"])
            assert bool(active) == (shift < 1)


def test_reason_counts_are_bounded_and_content_free(tmp_path):
    with job_timing.job_scope(tmp_path, job_id="job_synthetic") as timing:
        job_timing.render_reuse(True)
        job_timing.render_reuse(False, ["source_changed", "PRIVATE title and prose"])
    counts = timing.summary()["render_reuse_counts"]
    assert counts == {"reused": 1, "fallback": 1, "source_changed": 1, "other": 1}
    assert "PRIVATE" not in (tmp_path / "llm_jobs/jobs/job_synthetic/phase_timings.json").read_text()


def test_dependency_path_rebinding_invalidates_render(fixture, monkeypatch):
    store, thread, _ = fixture
    populate(store, thread)
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        assert scope.payload is not None, scope.observation.failures
        persist(store, thread)
        monkeypatch.setattr(aa, "SHARED_INVESTIGATION_DIR", store.workspace_dir / "other-shared")
        assert scope.take(store, thread) is None
        assert "source_changed" in scope.observation.failures


@pytest.mark.parametrize("populated", [False, True])
def test_peer_reader_still_forces_fresh_computation(fixture, populated):
    store, thread, _ = fixture
    record = populate(store, thread)
    record["question"] = "Synthetic gap spectral tail geometry"
    store._append_jsonl(store._experiments_path(thread["thread_id"]), record)
    thread["experiment_summary"] = store._experiment_summary(record)
    persist(store, thread)
    if populated:
        root = aa.ASTRID_BRIDGE_INBOX_DIR.parent / "action_threads"
        directory = root / "threads/th_peer_synthetic"
        directory.mkdir(parents=True)
        (root / "index.json").write_text(json.dumps({"active_thread_id": "th_peer_synthetic"}))
        (directory / "thread.json").write_text(json.dumps({"active_experiment_id": "exp_peer_synthetic"}))
        (directory / "experiments.jsonl").write_text(json.dumps(
            record | {"experiment_id": "exp_peer_synthetic"}) + "\n")
    with ps.ProjectionReadScope(store, thread) as scope:
        prepare(store, thread, scope)
        persist(store, thread)
        assert scope.take(store, thread) is None
        assert "peer_sources_not_qualified" in scope.observation.failures


def test_failed_thread_persistence_does_not_render_or_retain_scope(fixture, monkeypatch):
    store, thread, _ = fixture
    populate(store, thread)
    path = store._thread_dir(thread["thread_id"]) / "thread.json"
    before = path.read_bytes()
    writer = store._write_json
    render = Mock(wraps=store._write_next_md)

    def fail_thread(target, value):
        if target == path:
            raise OSError("synthetic failed thread persistence")
        return writer(target, value)

    with monkeypatch.context() as patch:
        patch.setattr(store, "_write_json", fail_thread)
        patch.setattr(store, "_write_next_md", render)
        with pytest.raises(OSError, match="synthetic failed"):
            store._write_thread(thread)
    render.assert_not_called()
    assert path.read_bytes() == before
    assert ps._CURRENT.get() is None
    store._write_thread(thread)


def test_expiry_consumer_clock_reversal_inside_projection_is_not_reused(fixture, monkeypatch):
    store, thread, _ = fixture
    now = [100.0]
    monkeypatch.setattr(aa.time, "time", lambda: now[0])
    rows = [{"request_id": "synthetic", "record_type": "steward_approval",
             "token_status": "active", "token_id": "synthetic_token", "expires_at_unix_s": 101.0}]
    observation = ps._Observation(store, thread)
    token = ps._CURRENT.set(observation)
    try:
        ps.observe_expiries(rows, lambda: now[0], observed=now[0])
        now[0] = 102.0
        assert store._authority_token_status(rows, "synthetic") == "expired"
    finally:
        ps._CURRENT.reset(token)
    now[0] = 100.5
    assert not observation.verify()
    assert "temporal_validity_changed" in observation.failures
    assert store._authority_token_status(rows, "synthetic") == "active"
