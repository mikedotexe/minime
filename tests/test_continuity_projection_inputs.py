"""One fresh diagnostic observation per projection; no cross-operation cache."""
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import job_history


def fixture(tmp_path):
    store = aa.ActionContinuityStore(tmp_path)
    thread = store.create_thread("Synthetic diagnostic observation")
    path = store._thread_dir(thread["thread_id"]) / "events.jsonl"
    rows = [{"action_id": f"act_{i}", "canonical_action": "SELF_STUDY",
             "status": "llm_running", "started_at": "2020-01-01T00:00:00Z"}
            for i in range(2)]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    job = tmp_path / "llm_jobs" / "jobs" / "job_fixture" / "job.json"
    job.parent.mkdir(parents=True)
    job.write_text(json.dumps({"job_id": "job_fixture", "action_id": "act_1",
                               "status": "timeout", "worker_status": "running"}))
    return store, thread, job


def test_one_job_observation_shared_by_both_diagnostics(tmp_path, monkeypatch):
    store, thread, job = fixture(tmp_path)
    original = job_history.metadata_snapshot
    snapshots = Mock(wraps=original)
    monkeypatch.setattr(job_history, "metadata_snapshot", snapshots)
    first = store._thread_projection(thread)
    assert snapshots.call_count == 1
    assert first["stale_running_count"] == 2
    assert first["repeated_action_cadence_v1"]["active_inflight_repeated_action_count"] == 1
    job.write_text(json.dumps({"job_id": "job_fixture", "action_id": "act_1",
                               "status": "timeout", "worker_status": "completed",
                               "outcome": {"status": "completed"}}))
    second = store._thread_projection(thread)
    assert snapshots.call_count == 2
    assert second["stale_running_count"] == 1
    row = next(r for r in second["stale_running_diagnostics"] if r["action_id"] == "act_1")
    assert row["terminal_outcome_status"] == "completed"
    assert row["terminal_job_status"] == "timeout"


def test_concurrent_completion_not_mixed_with_earlier_diagnostic_observation(tmp_path, monkeypatch):
    store, thread, job = fixture(tmp_path)
    original = store._repeated_action_cadence_v1

    def complete_between_diagnostics(*args, **kwargs):
        result = original(*args, **kwargs)
        job.write_text(json.dumps({"job_id": "job_fixture", "action_id": "act_1",
                                   "status": "completed", "worker_status": "completed"}))
        return result

    monkeypatch.setattr(store, "_repeated_action_cadence_v1", complete_between_diagnostics)
    first = store._thread_projection(thread)
    assert first["stale_running_count"] == 2
    second = store._thread_projection(thread)
    assert second["stale_running_count"] == 1


@pytest.mark.parametrize("change", ["replace", "rewrite", "delete", "corrupt", "append_event"])
def test_next_projection_observes_external_changes(tmp_path, change):
    store, thread, job = fixture(tmp_path)
    initial = store._thread_projection(thread)
    assert initial["stale_running_count"] == 2
    script = """
import json, os, pathlib, sys
job, events, change = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
before = job.stat()
if change == 'delete':
    job.unlink()
elif change == 'corrupt':
    job.write_text('{broken')
elif change == 'append_event':
    with events.open('a') as handle:
        handle.write(json.dumps({'action_id':'act_1', 'status':'handled', 'canonical_action':'SELF_STUDY'}) + '\\n')
else:
    target = job.with_suffix('.new') if change == 'replace' else job
    target.write_text(json.dumps({'job_id':'job_fixture','action_id':'act_1','status':'completed','worker_status':'completed'}))
    os.utime(target, ns=(before.st_atime_ns,before.st_mtime_ns))
    if change == 'replace':
        os.replace(target, job)
"""
    subprocess.run([sys.executable, "-B", "-c", script, str(job),
                    str(store._thread_dir(thread["thread_id"]) / "events.jsonl"), change], check=True)
    changed = store._thread_projection(thread)
    assert changed["stale_running_count"] == (2 if change in {"delete", "corrupt"} else 1)


def test_single_bounded_event_window_and_fresh_subsequent_read(tmp_path, monkeypatch):
    store, thread, _ = fixture(tmp_path)
    original = store._recent_display_events
    windows = Mock(wraps=original)
    monkeypatch.setattr(store, "_recent_display_events", windows)
    first = store._thread_projection(thread)
    windows.assert_called_once_with(thread["thread_id"], 200)
    assert len(first["recent_events"]) == 2
    store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl",
                        {"action_id": "new", "canonical_action": "REST", "status": "handled"})
    second = store._thread_projection(thread)
    assert windows.call_count == 2
    assert second["recent_events"][-1]["canonical_action"] == "REST"


def test_explicit_empty_inputs_do_not_trigger_a_second_read(tmp_path, monkeypatch):
    store, thread, _ = fixture(tmp_path)
    monkeypatch.setattr(store, "_terminal_jobs_by_action_id", Mock(side_effect=AssertionError("extra scan")))
    monkeypatch.setattr(store, "_recent_display_events", Mock(side_effect=AssertionError("extra read")))
    assert store._repeated_action_cadence_v1(thread["thread_id"], [], terminal_jobs={})["repeated_actions"] == []
    assert len(store._stale_running_action_diagnostics(thread["thread_id"], terminal_jobs={})) == 2
    assert store._proposal_diagnostics(thread["thread_id"], recent_events=[]) == []


def test_failure_is_not_cached_or_misrepresented_as_empty(tmp_path, monkeypatch):
    store, thread, _ = fixture(tmp_path)
    original = job_history.metadata_snapshot
    with monkeypatch.context() as patcher:
        patcher.setattr(job_history, "metadata_snapshot", Mock(side_effect=job_history.JobHistoryChanged("fixture")))
        with pytest.raises(job_history.JobHistoryChanged):
            store._thread_projection(thread)
    assert store._thread_projection(thread)["stale_running_count"] == 2
    assert original(tmp_path / "llm_jobs" / "jobs")


def test_projection_does_not_mutate_supplied_thread(tmp_path):
    store, thread, _ = fixture(tmp_path)
    before = json.dumps(thread, sort_keys=True)
    store._thread_projection(thread)
    assert json.dumps(thread, sort_keys=True) == before


def test_journal_fingerprint_preserves_selection_and_reobserves_changes(tmp_path):
    store, thread, _ = fixture(tmp_path)
    journal = tmp_path / "journal"
    journal.mkdir(exist_ok=True)
    (journal / "one.txt").write_text("Synthetic first entry.")
    (journal / "two.txt").write_text("Synthetic second entry.")
    (journal / "ignored.json").write_text("{}")
    (journal / "directory.txt").mkdir()
    (journal / "link.txt").symlink_to(journal / "one.txt")
    (journal / "missing.txt").symlink_to(journal / "absent")

    def legacy():
        stats = [p.stat() for p in journal.glob("*.txt") if p.is_file()]
        return {"mtime_ns": max((s.st_mtime_ns for s in stats), default=0),
                "size": sum(s.st_size for s in stats)}

    assert store._projection_source_fingerprints_v1(thread["thread_id"])["journal/*.txt"] == legacy()
    (journal / "one.txt").write_text("A changed synthetic entry with a different size.")
    (journal / "two.txt").unlink()
    (journal / "three.txt").write_text("New synthetic evidence.")
    assert store._projection_source_fingerprints_v1(thread["thread_id"])["journal/*.txt"] == legacy()


def test_bounded_display_slices_preserve_duplicate_ordering(tmp_path):
    store, thread, _ = fixture(tmp_path)
    events = store._thread_dir(thread["thread_id"]) / "events.jsonl"
    for i in range(300):
        for status in ("llm_running", "handled"):
            store._append_jsonl(events, {"action_id": f"tail_{i}", "status": status,
                                        "canonical_action": "SELF_STUDY"})
    window = store._recent_display_events(thread["thread_id"], 200)
    for limit in (8, 32, 96, 200):
        assert window[-limit:] == store._recent_display_events(thread["thread_id"], limit)
    assert all(row["status"] == "handled" for row in window)
