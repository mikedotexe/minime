"""Return support uses retained facts, not a heuristic score or execution promise."""

import json
from pathlib import Path

import pytest

from minime_autonomy import runtime
from minime_autonomy.continuity_snapshot import EvidenceUnavailable, StableSnapshot
from minime_autonomy.return_support import project_return_support, read_return_support


def experiment(thread_id="thread_minime_test", experiment_id="exp_minime_test", **changes):
    return {
        "schema_version": 1, "thread_id": thread_id, "experiment_id": experiment_id,
        "title": "Synthetic inquiry", "question": "What is retained?", "status": "active",
        "authority_envelope": "existing gates only", "planned_next": "REST",
        "hypothesis": None, "success_observation": None, "peer_review_refs": [],
        "created_at": "2026-10-16T01:00:00+00:00", "updated_at": "2026-10-16T02:00:00+00:00",
        **changes,
    }


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in records))


def support(thread, path, reference=None):
    return read_return_support(thread, path, reference, runtime.ActionContinuityStore._paused_primary_return_v1)


def test_shared_fixture_parity():
    data = (Path(__file__).parent / "fixtures" / "return_support_v1.json").read_bytes()
    for case in json.loads(data):
        assert project_return_support(case["reference"], case["thread_next"], case["record"],
                                      case["guarded_return_kind"]) == case["expected"], case["name"]


def test_no_reference_does_not_read_or_fall_back(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("no reference must not inspect historical records")
    monkeypatch.setattr(StableSnapshot, "read", forbidden)
    result = support({"current_next": "REST", "experiment_summary": {"experiment_id": "exp_minime_old"}},
                     tmp_path / "experiments.jsonl")
    assert result["record_status"] == "absent"
    assert result["experiment_reference"] is None
    assert result["saved_next_action"] == "present"
    assert result["saved_next_action_scope"] == "thread"


@pytest.mark.parametrize("planned,expected", [(None, "absent"), (" ", "absent"), ("REST", "present")])
def test_readable_experiment_uses_its_own_next(tmp_path, planned, expected):
    path = tmp_path / "thread_minime_test" / "experiments.jsonl"
    write_jsonl(path, [experiment(planned_next=planned)])
    result = support({"active_experiment_id": "exp_minime_test", "current_next": "THREAD_STATUS current"}, path)
    assert result["record_status"] == "verified_readable"
    assert result["saved_next_action"] == expected
    assert result["saved_next_action_scope"] == "experiment"
    assert result["guarded_return_kind"] is None
    assert result["execution_eligibility"] == "not_evaluated"


def test_explicit_reference_wins_and_is_exact(tmp_path):
    path = tmp_path / "thread_minime_test" / "experiments.jsonl"
    write_jsonl(path, [experiment(), experiment(experiment_id="exp_minime_other", planned_next=None)])
    thread = {"active_experiment_id": "exp_minime_test", "current_next": "REST"}
    assert support(thread, path, "exp_minime_other")["saved_next_action"] == "absent"
    for reference in ("exp_minime", "Synthetic inquiry", "missing"):
        result = support(thread, path, reference)
        assert result["record_status"] == "unavailable"
        assert result["saved_next_action"] == "unknown"
        assert result["saved_next_action_scope"] == "unavailable"


@pytest.mark.parametrize("planned,kind", [
    ("THREAD_STATUS current", "hold"), ("EXPERIMENT_CHARTER exp_minime_test", "charter_repair"),
    ("EXPERIMENT_RESUME exp_minime_test", "resume"), ("EXPERIMENT_DECIDE exp_minime_test", "decision"),
    ("EXPERIMENT_REHEARSE exp_minime_test", "rehearsal_ready"),
    ("EXPERIMENT_ADVANCE exp_minime_test", "conveyor_preview"),
])
def test_paused_kind_uses_existing_guard(tmp_path, planned, kind):
    path = tmp_path / "thread_minime_test" / "experiments.jsonl"
    write_jsonl(path, [experiment(status="paused", planned_next=planned)])
    assert support({}, path, "exp_minime_test")["guarded_return_kind"] == kind


@pytest.mark.parametrize("bad", [
    "{not-json\n", "[]\n", '{"experiment_id":"exp_minime_test"}\n',
    json.dumps(experiment(planned_next=[])), json.dumps(experiment(thread_id="wrong")),
    json.dumps(experiment(schema_version=True)), json.dumps(experiment(peer_review_refs="bad")),
])
def test_malformed_record_fails_closed_even_after_readable_history(tmp_path, bad):
    path = tmp_path / "thread_minime_test" / "experiments.jsonl"
    write_jsonl(path, [experiment()])
    path.write_text(path.read_text() + bad)
    result = support({"current_next": "REST"}, path, "exp_minime_test")
    assert result["record_status"] == "unavailable"
    assert result["saved_next_action"] == "unknown"
    assert result["guarded_return_kind"] is None


def test_missing_unreadable_and_changing_are_unavailable(tmp_path, monkeypatch):
    path = tmp_path / "thread_minime_test" / "experiments.jsonl"
    assert support({}, path, "exp_minime_test")["record_status"] == "unavailable"
    write_jsonl(path, [experiment()])
    for reason in ("unreadable", "changing"):
        with monkeypatch.context() as patcher:
            def fail(*args):
                raise EvidenceUnavailable(reason)
            patcher.setattr(StableSnapshot, "verify", fail)
            assert support({}, path, "exp_minime_test")["record_status"] == "unavailable"


@pytest.mark.parametrize("bad", [None, "[]", "null", "false", "{}", "{bad", '{"thread_id": []}'])
def test_missing_or_malformed_thread_is_not_absent(tmp_path, bad):
    store = runtime.ActionContinuityStore(tmp_path)
    path = store._thread_dir("thread_minime_test") / "thread.json"
    if bad is not None:
        path.parent.mkdir(parents=True)
        path.write_text(bad)
    result = store._motif_allowance_snapshot("thread_minime_test")["return_support_v1"]
    assert result["record_status"] == "unavailable"
    assert result["saved_next_action"] == "unknown"
    assert result["saved_next_action_scope"] == "unavailable"


def test_legacy_cue_suppressed_even_when_supplied_directly():
    legacy = {"native_return_cue": "state spectral condition, felt texture, and artifact grounding"}
    assert runtime.ActionContinuityStore._native_return_cue_line(legacy) == ""
    assert runtime.ActionContinuityStore._native_return_cue_line({"native_continuity_v1": legacy}) == ""


def test_projection_tracks_selection_and_pause_without_historical_fallback(tmp_path):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic transitions")
    assert store._thread_projection(thread)["return_support_v1"]["record_status"] == "absent"
    exp = store.start_experiment("Synthetic experiment", "Can it be retained?")
    selected = store.current_thread()
    facts = store._thread_projection(selected)["return_support_v1"]
    assert facts["experiment_reference"] == exp["experiment_id"]
    assert facts["record_status"] == "verified_readable"
    store.close_experiment("current", "pause synthetic inquiry")
    paused = store.current_thread()
    assert paused["active_experiment_id"] is None
    facts = store._thread_projection(paused)["return_support_v1"]
    assert facts["experiment_reference"] is None
    assert facts["record_status"] == "absent"
    assert facts["saved_next_action_scope"] == "thread"
    explicit = store._return_support_v1(paused, exp["experiment_id"])
    assert explicit["record_status"] == "verified_readable"
    assert explicit["guarded_return_kind"] == "hold"


@pytest.mark.parametrize("field,value", [("system_origin", "astrid"), ("thread_id", "wrong"),
                                         ("current_next", []), ("active_experiment_id", 7)])
def test_saved_thread_owner_identity_and_field_types_are_validated(tmp_path, field, value):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic validation")
    path = store._thread_dir(thread["thread_id"]) / "thread.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    facts = store._return_support_v1(thread)
    assert facts["record_status"] == "unavailable"
    assert facts["saved_next_action"] == "unknown"


def test_runtime_snapshots_render_facts_and_preserve_legacy_storage(tmp_path):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic return")
    exp = store.start_experiment("Synthetic experiment", "What is retained?")
    thread_path = store._thread_dir(thread["thread_id"]) / "thread.json"
    saved = json.loads(thread_path.read_text())
    saved["motif_allowance_v1"]["returnability"] = 0.78
    saved["thread_resonance_density_v1"] = {"aggregate": 0.45, "density_ema": 0.78}
    thread_path.write_text(json.dumps(saved))
    exp["motif_allowance_v1"] = {"returnability": 0.45}
    store._append_jsonl(store._experiments_path(thread["thread_id"]), exp)
    history = store._experiments_path(thread["thread_id"]).read_bytes()
    fresh = store._motif_allowance_snapshot(thread["thread_id"], exp["experiment_id"])
    assert "returnability" not in fresh
    assert fresh["return_support_v1"]["record_status"] == "verified_readable"
    assert store._experiments_path(thread["thread_id"]).read_bytes() == history
    assert json.loads(thread_path.read_text())["motif_allowance_v1"]["returnability"] == 0.78
    for rendered in (store.prompt_summary(), store._format_thread_status(saved),
                     store._format_experiment_status(saved, exp)):
        assert "returnability=" not in rendered
        assert "Return support (return_support_v1)" in rendered
        assert "Native return:" not in rendered
        assert "Snapshot facts at capture, not live eligibility or recovered understanding" in rendered
    status = store._format_thread_status(saved)
    assert "retired heuristic" in status
    assert "aggregate=0.45" in status
    store._write_next_md(saved)
    next_text = (thread_path.parent / "next.md").read_text()
    assert "returnability=" not in next_text
    assert "Native return:" not in next_text
    assert "note whether returnability improves" not in store.experiment_alt_paths("current")


def test_historical_run_heuristic_is_marked_but_value_not_rendered(tmp_path):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic history")
    exp = store.start_experiment("Synthetic experiment", "What was retained?")
    run = {"experiment_id": exp["experiment_id"], "action_text": "REST", "stage": "observe",
           "status": "success", "result_summary": "synthetic receipt", "interpretation": "",
           "motif_allowance_v1": {"returnability": 0.7812345}}
    store._append_jsonl(store._experiment_runs_path(thread["thread_id"]), run)
    for text in (store.experiment_status(exp["experiment_id"]), store.experiment_review(exp["experiment_id"])):
        assert "retired heuristic" in text
        assert "0.7812345" not in text
    assert "0.7812345" in store._experiment_runs_path(thread["thread_id"]).read_text()


def test_resume_receipt_selects_context_without_a_run(tmp_path):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic resume")
    exp = store.start_experiment("Synthetic experiment", "Can it be selected?")
    before = store._experiment_runs_path(thread["thread_id"]).read_bytes()
    receipt = store.experiment_resume(exp["experiment_id"])
    assert "Context selected; saved next action was not executed" in receipt
    assert "Existing execution gates still apply" in receipt
    assert store._experiment_runs_path(thread["thread_id"]).read_bytes() == before
    exp.update(status="paused", planned_next="THREAD_STATUS current")
    store._append_jsonl(store._experiments_path(thread["thread_id"]), exp)
    receipt = store.experiment_resume(exp["experiment_id"])
    assert "guarded by hold; not reactivated" in receipt
    assert store._experiment_runs_path(thread["thread_id"]).read_bytes() == before
