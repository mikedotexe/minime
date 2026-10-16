"""Comparison is a bounded inspection, not selection, execution, or peer authorship."""

import json
from pathlib import Path

import pytest

from minime_autonomy import runtime
from minime_autonomy import continuity_snapshot as snapshots
from minime_autonomy.deliberate_comparison import read_comparison_side, render_comparison
from tests.test_truthful_return_support import experiment, write_jsonl


def run_record(identity, index):
    return {
        "schema_version": 1, "experiment_id": identity, "run_id": f"run_{index}",
        "action_text": f"READ_MORE synthetic-{index}", "stage": "read", "status": "success",
        "result_summary": f"recorded receipt {index}", "interpretation": f"authored meaning {index}",
        "created_at": f"time-{index}", "updated_at": f"time-{index}",
        "artifacts": [{"artifact_id": f"artifact_{index}", "kind": "source",
                       "path_or_uri": f"/synthetic-unopened/{index}"}],
    }


def fixture_workspace(workspace, owner="minime", *, runs=6, dossier=True):
    root = workspace / "action_threads"
    identity, thread_id = f"exp_{owner}_test", f"thread_{owner}_test"
    directory = root / "threads" / thread_id
    record = experiment(thread_id=thread_id, experiment_id=identity)
    write_jsonl(directory / "experiments.jsonl", [record])
    write_jsonl(directory / "experiment_runs.jsonl", [run_record(identity, idx) for idx in range(runs)])
    if dossier:
        write_jsonl(directory / "research_dossier.jsonl", [{
            "schema_version": 1, "record_schema": "research_dossier_v1", "record_type": "claim",
            "record_id": f"claim_{owner}_test", "claim_id": f"claim_{owner}_test", "being": owner,
            "thread_id": thread_id, "experiment_id": identity,
        }])
    (directory / "thread.json").write_text(json.dumps({
        "thread_id": thread_id, "active_experiment_id": identity, "system_origin": owner,
        "schema_version": 1, "title": "Synthetic thread", "status": "active",
        "created_at": "2026-10-16T01:00:00+00:00", "updated_at": "2026-10-16T02:00:00+00:00",
    }))
    (root / "index.json").write_text(json.dumps({"active_thread_id": thread_id}))
    return root, directory, identity


def tree_state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_each_side_is_separate_bounded_and_no_files_change(tmp_path, monkeypatch):
    root, directory, identity = fixture_workspace(tmp_path / "local")
    peer_root, peer_directory, peer_id = fixture_workspace(tmp_path / "peer", "astrid")
    monkeypatch.setattr(runtime, "ASTRID_BRIDGE_INBOX_DIR", peer_root.parent / "bridge_inbox")
    store = runtime.ActionContinuityStore(root.parent)
    for name in ("ensure_active_thread", "current_thread", "_read_thread", "_resolve_experiment",
                 "record_peer_experiment_reference", "_write_thread", "_mirror_thread"):
        def forbidden(*args, **kwargs):
            raise AssertionError("comparison used a mutating or refresh-capable helper")
        monkeypatch.setattr(store, name, forbidden)
    before = tree_state(tmp_path)
    result = store.experiment_compare(f"current WITH {peer_id}")
    assert tree_state(tmp_path) == before
    assert f"Left: owner=minime id={identity}" in result
    assert f"Right: owner=astrid id={peer_id}" in result
    assert result.count("Digest: sha256:") == 2
    assert result.count("Timestamps:") == 2
    assert result.count("Authored interpretation (not an execution receipt)") == 2
    assert result.count("Execution receipts (at most 4 retained runs") == 2
    assert result.count("Artifact references (unverified; files not opened)") == 2
    assert "run_0" not in result and "run_1" not in result
    assert "run_2" in result and "run_5" in result
    assert f"DOSSIER_EVIDENCE {identity} :: claim_id: claim_minime_test" in result
    assert f"DOSSIER_EVIDENCE {peer_id}" not in result
    assert "claim_id: latest" not in result
    assert "returnability=" not in result
    assert "automatic equivalence conclusion" in result
    side = read_comparison_side(root, "minime", "current")
    assert len(side["runs"]) == 4
    assert side["digest"].startswith("sha256:")
    assert side["timestamps"] == {"created_at": experiment()["created_at"], "updated_at": experiment()["updated_at"]}


def test_uninitialized_comparison_does_not_create_directories(tmp_path, monkeypatch):
    workspace = tmp_path / "not-created"
    monkeypatch.setattr(runtime, "ASTRID_BRIDGE_INBOX_DIR", tmp_path / "peer-not-created" / "bridge_inbox")
    store = runtime.ActionContinuityStore(workspace)
    before = tree_state(tmp_path)
    result = store.experiment_compare("current WITH exp_astrid_missing")
    assert "Availability: unavailable" in result
    assert "Right: owner=astrid id=exp_astrid_missing" in result
    assert not workspace.exists()
    assert not (tmp_path / "peer-not-created").exists()
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize("command", ["experiment_status", "experiment_review"])
def test_inspection_never_initializes_or_refreshes_selection(tmp_path, monkeypatch, command):
    workspace = tmp_path / "not-created"
    store = runtime.ActionContinuityStore(workspace)
    assert "unavailable" in getattr(store, command)("current")
    assert not workspace.exists()
    thread = store.create_thread("Synthetic inspect")
    exp = store.start_experiment("Synthetic inspect", "What is retained?")
    path = store._thread_dir(thread["thread_id"]) / "thread.json"
    saved = json.loads(path.read_text())
    saved["projection_freshness_v1"] = {"schema_version": -1}
    saved["updated_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(saved))
    before = tree_state(tmp_path)
    for name in ("ensure_active_thread", "current_thread", "_read_thread", "_write_thread", "_mirror_thread"):
        def forbidden(*args, **kwargs):
            raise AssertionError("read-only inspection used a refreshing helper")
        monkeypatch.setattr(store, name, forbidden)
    text = getattr(store, command)("current")
    assert exp["experiment_id"] in text
    assert "Lifecycle:" in text
    assert "Continuity return:" in text
    assert tree_state(tmp_path) == before
    saved["active_experiment_id"] = None
    path.write_text(json.dumps(saved))
    before = tree_state(tmp_path)
    text = getattr(store, command)("current")
    assert "no active experiment" in text.lower()
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize("command", ["experiment_status", "experiment_review"])
def test_peer_inspection_never_records_reference_work(tmp_path, monkeypatch, command):
    peer_root, peer_directory, peer_id = fixture_workspace(tmp_path / "peer", "astrid")
    monkeypatch.setattr(runtime, "ASTRID_BRIDGE_INBOX_DIR", peer_root.parent / "bridge_inbox")
    workspace = tmp_path / "not-created"
    store = runtime.ActionContinuityStore(workspace)
    def forbidden(*args, **kwargs):
        raise AssertionError("peer inspection recorded reference work")
    monkeypatch.setattr(store, "record_peer_experiment_reference", forbidden)
    before = tree_state(tmp_path)
    text = getattr(store, command)(peer_id)
    assert peer_id in text and "verified_readable" in text
    assert "no selection" in text.lower()
    assert not workspace.exists()
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize("command", ["experiment_status", "experiment_review"])
def test_inspection_owner_mismatch_or_dangling_reference_is_unavailable(tmp_path, command):
    root, directory, identity = fixture_workspace(tmp_path)
    store = runtime.ActionContinuityStore(tmp_path)
    path = directory / "thread.json"
    saved = json.loads(path.read_text())
    for changes in ({"system_origin": "astrid"}, {"active_experiment_id": "exp_minime_missing"}):
        path.write_text(json.dumps({**saved, **changes}))
        before = tree_state(tmp_path)
        text = getattr(store, command)("current")
        assert "unavailable" in text
        assert "No thread or experiment was selected or revised" in text
        assert tree_state(tmp_path) == before


def test_no_active_reference_does_not_select_historical_experiment(tmp_path):
    root, directory, identity = fixture_workspace(tmp_path)
    path = directory / "thread.json"
    saved = json.loads(path.read_text())
    saved["active_experiment_id"] = None
    path.write_text(json.dumps(saved))
    before = tree_state(tmp_path)
    result = read_comparison_side(root, "minime", "current")
    assert result["availability"] == "unavailable"
    assert "historical fallback is disabled" in result["reason"]
    assert tree_state(tmp_path) == before
    assert read_comparison_side(root, "minime", identity)["availability"] == "verified_readable"


def test_comparison_does_not_refresh_stale_projection(tmp_path):
    store = runtime.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic stale projection")
    exp = store.start_experiment("Synthetic experiment", "What was retained?")
    path = store._thread_dir(thread["thread_id"]) / "thread.json"
    saved = json.loads(path.read_text())
    saved["projection_freshness_v1"] = {"schema_version": -1}
    path.write_text(json.dumps(saved))
    before = tree_state(tmp_path)
    text = store.experiment_compare(f"current WITH {exp['experiment_id']}")
    assert text.count("Availability: verified_readable") == 2
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize("filename,bad", [
    ("experiments.jsonl", "{bad\n"), ("experiments.jsonl", "null\n"),
    ("experiments.jsonl", "42\n"), ("experiments.jsonl", "[]\n"),
    ("experiments.jsonl", '{"experiment_id":"exp_minime_test"}\n'),
    ("experiment_runs.jsonl", "[]\n"), ("experiment_runs.jsonl", "false\n"),
    ("experiment_runs.jsonl", '{"experiment_id":"exp_minime_test"}\n'),
    ("thread.json", "null"), ("index.json", "[]"),
])
def test_corrupt_snapshot_is_unavailable(tmp_path, filename, bad):
    root, directory, identity = fixture_workspace(tmp_path)
    path = root / filename if filename == "index.json" else directory / filename
    path.write_text(bad)
    before = tree_state(tmp_path)
    result = read_comparison_side(root, "minime", "current")
    assert result["availability"] == "unavailable"
    assert result["digest"] is None
    assert "record" not in result
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize("filename", ["experiments.jsonl", "experiment_runs.jsonl", "thread.json", "index.json"])
def test_missing_evidence_is_unavailable(tmp_path, filename):
    root, directory, identity = fixture_workspace(tmp_path)
    (root / filename if filename == "index.json" else directory / filename).unlink()
    result = read_comparison_side(root, "minime", "current")
    assert result["availability"] == "unavailable"


def test_missing_or_empty_dossier_has_no_note_suggestion(tmp_path):
    root, directory, identity = fixture_workspace(tmp_path, dossier=False)
    for dossier in (None, "", '{"experiment_id":"exp_minime_test","record_schema":7}\n'):
        if dossier is not None:
            (directory / "research_dossier.jsonl").write_text(dossier)
        side = read_comparison_side(root, "minime", "current")
        assert side["availability"] == "verified_readable"
        result = render_comparison(side, side, "minime")
        assert "DOSSIER_EVIDENCE" not in result
        if dossier != "":
            assert "Existing dossier: unavailable" in result


def test_only_exact_owned_dossier_claim_is_suggested(tmp_path):
    root, directory, identity = fixture_workspace(tmp_path)
    path = directory / "research_dossier.jsonl"
    rows = [json.loads(path.read_text())]
    rows.append({**rows[0], "claim_id": "claim_wrong_exp", "record_id": "claim_wrong_exp", "experiment_id": "exp_minime_other"})
    rows.append({**rows[0], "claim_id": "claim_wrong_owner", "record_id": "claim_wrong_owner", "being": "astrid"})
    write_jsonl(path, rows)
    side = read_comparison_side(root, "minime", "current")
    assert side["dossier_claim_id"] == "claim_minime_test"


def test_changing_evidence_is_unavailable_not_partial(tmp_path, monkeypatch):
    root, directory, identity = fixture_workspace(tmp_path)
    original = snapshots.StableSnapshot.verify
    def change_then_verify(snapshot):
        path = directory / "experiments.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
        original(snapshot)
    monkeypatch.setattr(snapshots.StableSnapshot, "verify", change_then_verify)
    side = read_comparison_side(root, "minime", "current")
    assert side["availability"] == "unavailable"
    assert "changing" in side["reason"]
    assert "record" not in side


def test_snapshot_rereads_bytes_and_rejects_same_metadata_change(tmp_path, monkeypatch):
    path = tmp_path / "evidence.json"
    path.write_text('{"value":1}')
    snapshot = snapshots.StableSnapshot()
    assert snapshot.json(path) == {"value": 1}
    fingerprint = snapshot.sources[path]
    monkeypatch.setattr(snapshots, "_fingerprint", lambda info: fingerprint)
    path.write_text('{"value":2}')
    with pytest.raises(snapshots.EvidenceUnavailable, match="changing evidence"):
        snapshot.verify()


def test_snapshot_rejects_unreadable_and_non_regular_files(tmp_path, monkeypatch):
    path = tmp_path / "evidence.json"
    path.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(snapshots.EvidenceUnavailable, match="not a regular"):
        snapshots.StableSnapshot().read(link)
    with monkeypatch.context() as patcher:
        def deny(*args, **kwargs):
            raise PermissionError("synthetic denial")
        patcher.setattr(snapshots.os, "open", deny)
        with pytest.raises(snapshots.EvidenceUnavailable, match="unreadable"):
            snapshots.StableSnapshot().read(path)


def test_bounded_bytes_rows_and_directories(tmp_path, monkeypatch):
    root, directory, identity = fixture_workspace(tmp_path)
    for constant, limit in (("MAX_FILE_BYTES", 10), ("MAX_TOTAL_BYTES", 10), ("MAX_ROWS", 2), ("MAX_THREADS", 0)):
        with monkeypatch.context() as patcher:
            patcher.setattr(snapshots, constant, limit)
            result = read_comparison_side(root, "minime", identity)
            assert result["availability"] == "unavailable"
            assert "bounded" in result["reason"]


def test_duplicate_json_keys_and_nonfinite_numbers_fail_closed(tmp_path):
    for data in ('{"value":1,"value":2}', '{"value":NaN}', '{"value":Infinity}'):
        path = tmp_path / "evidence.json"
        path.write_text(data)
        with pytest.raises(snapshots.EvidenceUnavailable):
            snapshots.StableSnapshot().json(path)


def test_ambiguous_exact_peer_identity_is_unavailable(tmp_path):
    root, directory, identity = fixture_workspace(tmp_path, "astrid")
    other = root / "threads" / "thread_astrid_duplicate"
    write_jsonl(other / "experiments.jsonl", [experiment(thread_id=other.name, experiment_id=identity)])
    side = read_comparison_side(root, "astrid", identity)
    assert side["availability"] == "unavailable"
    assert "ambiguous" in side["reason"]
