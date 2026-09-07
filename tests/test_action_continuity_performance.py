"""Synthetic continuity performance and record parity fixtures."""
import cProfile
import json
import os
from pathlib import Path
import pstats
import sqlite3
import time

import autonomous_agent as aa
from minime_autonomy import continuity_history
from minime_autonomy import job_timing


STATE = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68, "spread": 3.0,
         "cov_lambda1": 8.0, "geom_rel": 1.0}


def populated_store(root, rows=2000, padding=4096):
    store = aa.ActionContinuityStore(root, db_path=root / "continuity.sqlite3")
    thread = store.create_thread("Synthetic continuity performance")
    event = store.begin_action("ASPIRE", "ASPIRE", "recess_aspiration", "recess_aspiration", STATE)
    path = store._thread_dir(thread["thread_id"]) / "events.jsonl"
    with path.open("w") as handle:
        for i in range(rows):
            record = {**event, "action_id": f"act_fixture_{i}", "status": "handled",
                      "outcome_summary": "Synthetic history " + "x" * padding}
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return store, event


def _legacy_ids(path):
    ids = set()
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            value = row.get("action_id") if isinstance(row, dict) else None
            if isinstance(value, str) and value:
                ids.add(value)
    return ids


def test_profile_finish_action_fixture(tmp_path, monkeypatch):
    fixture_rows = int(os.environ.get("MINIME_CONTINUITY_PROFILE_ROWS", "2000"))
    legacy = os.environ.get("MINIME_CONTINUITY_PROFILE_LEGACY") == "1"
    if legacy:
        monkeypatch.setattr(continuity_history, "reverse_lines", lambda path: iter(reversed(path.read_text().splitlines())))
        monkeypatch.setattr(continuity_history, "action_ids", _legacy_ids)
    store, event = populated_store(tmp_path, rows=fixture_rows)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    result = profiler.runcall(store.finish_action, event, "handled", "Synthetic output saved", STATE)
    elapsed = time.perf_counter() - start
    assert result["status"] == "handled"
    destination = os.environ.get("MINIME_CONTINUITY_PROFILE_OUT")
    if destination:
        stats = pstats.Stats(profiler)
        rows = [{"file": Path(key[0]).name, "line": key[1], "name": key[2],
                 "primitive_calls": value[0], "calls": value[1],
                 "exclusive_s": value[2], "inclusive_s": value[3]}
                for key, value in stats.stats.items()]
        Path(destination).write_text(json.dumps({
            "elapsed_s": elapsed, "synthetic_rows": fixture_rows, "padding_bytes_per_row": 4096,
            "legacy_history_readers": legacy,
            "top_cumulative": sorted(rows, key=lambda row: row["inclusive_s"], reverse=True)[:40],
            "top_exclusive": sorted(rows, key=lambda row: row["exclusive_s"], reverse=True)[:20],
        }, indent=2) + "\n")


def _normalized(value, root):
    if isinstance(value, dict):
        return {key: _normalized(item, root) for key, item in value.items()
                if key not in {"mtime_ns", "ctime_ns", "device", "inode", "signature_digest", "latest_source_mtime_ns"}}
    if isinstance(value, list):
        return [_normalized(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "<fixture>")
    return value


def _snapshot(root):
    files = {}
    for path in sorted((root / "action_threads").rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text()
        if path.suffix == ".json":
            value = json.loads(text)
        elif path.suffix == ".jsonl":
            value = [json.loads(line) for line in text.splitlines() if line]
        else:
            value = text
        files[str(path.relative_to(root))] = _normalized(value, root)
    with sqlite3.connect(root / "continuity.sqlite3") as conn:
        for table in ("action_threads", "action_events", "observation_windows", "artifact_links"):
            cursor = conn.execute(f"SELECT * FROM {table} ORDER BY 1")
            columns = [item[0] for item in cursor.description]
            rows = []
            for values in cursor.fetchall():
                row = dict(zip(columns, values))
                row.pop("timestamp", None)
                row.pop("updated_at", None)
                row["payload"] = json.loads(row["payload"])
                rows.append(_normalized(row, root))
            files[f"db:{table}"] = rows
    return files


def test_finish_preserves_all_file_records_and_database_mirrors(tmp_path, monkeypatch):
    monkeypatch.setattr(aa.ActionContinuityStore, "_now", lambda self: "2026-09-07T18:00:00Z")
    monkeypatch.setattr(aa.ActionContinuityStore, "_unique_thread_id", lambda self, title: "th_fixture")
    monkeypatch.setattr(aa.ActionContinuityStore, "_unique_action_id", lambda self, base: "act_finish_fixture")
    snapshots = []
    results = []
    for legacy, name in ((True, "before"), (False, "after_")):
        root = tmp_path / name
        root.mkdir()
        with monkeypatch.context() as patcher:
            if legacy:
                patcher.setattr(continuity_history, "reverse_lines", lambda path: iter(reversed(path.read_text().splitlines())))
                patcher.setattr(continuity_history, "action_ids", _legacy_ids)
            store, event = populated_store(root, rows=120, padding=32)
            artifact = {"artifact_id": "art_fixture", "action_id": event["action_id"],
                        "kind": "journal", "path_or_uri": str(root / "journal" / "fixture.txt"),
                        "summary": "Synthetic retained journal"}
            result = store.finish_action(event, "handled", "Synthetic output saved", STATE, [artifact])
            results.append(_normalized(result, root))
            snapshots.append(_snapshot(root))
    assert results[0] == results[1]
    assert snapshots[0] == snapshots[1]


def test_continuity_subphases_fit_bounded_worker_timing(tmp_path):
    store, event = populated_store(tmp_path, rows=120, padding=32)
    with job_timing.job_scope(tmp_path, job_id="job_fixture", action_id=event["action_id"]) as timing:
        store.finish_action(event, "handled", "Synthetic output saved", STATE)
        with job_timing.phase("worker.finalization"):
            pass
    summary = timing.summary()
    assert summary["dropped_spans"] == 0
    assert summary["snapshot_complete"] is True
    assert any(span["phase"] == "continuity.projection" for span in summary["spans"])
    assert any(span["phase"] == "continuity.source_fingerprints" for span in summary["spans"])
    assert summary["spans"][-1]["phase"] == "worker.finalization"
    assert all(span["status"] != "active" for span in summary["spans"])
    # Leave space for the existing preparation/query/journal and manifest spans.
    assert len(summary["spans"]) < job_timing.MAX_SPANS - 32
