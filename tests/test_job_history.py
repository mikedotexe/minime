import json
import os
from pathlib import Path

import pytest

from minime_autonomy import job_history as history
from minime_autonomy.llm_access import LlmJobStore


def write_job(root, name, **changes):
    path = root / name / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    job = dict(job_id=name, action_id=f"action-{name}", created_at=name,
               status="completed", worker_status="completed", priority="primary",
               outcome={"status": "completed"}, summary="retained")
    job.update(changes)
    path.write_text(json.dumps(job))
    return path


def test_warm_metadata_only_decodes_changes_and_selected_jobs(tmp_path, monkeypatch):
    for i in range(40):
        write_job(tmp_path, f"job-{i:03}", phase_timings={"large": "x" * 10000})
    original = history._stable_read
    reads = []

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(history, "_stable_read", read)
    records = history.metadata_snapshot(tmp_path)
    assert len(reads) == 40
    reads.clear()
    history.metadata_snapshot(tmp_path)
    assert reads == []
    result = history.recent_jobs(tmp_path, 3)
    assert [job["job_id"] for job in result] == ["job-037", "job-038", "job-039"]
    assert len(reads) == 3
    assert result[-1]["phase_timings"]["large"] == "x" * 10000
    assert "phase_timings" not in records[-1].metadata()
    reads.clear()
    write_job(tmp_path, "job-000", status="failed")
    history.metadata_snapshot(tmp_path)
    assert reads == [tmp_path / "job-000" / "job.json"]


def test_replacement_same_size_and_restored_mtime_invalidates_metadata_and_fingerprint(tmp_path):
    path = write_job(tmp_path, "one", status="running", worker_status="running")
    old_stat = path.stat()
    before = history.fingerprint_for_actions(tmp_path, {"action-one"})
    replacement = path.with_suffix(".tmp")
    replacement.write_text(path.read_text().replace('"running"', '"timeout"'))
    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_size == old_stat.st_size
    after = history.fingerprint_for_actions(tmp_path, {"action-one"})
    assert before["size"] == after["size"]
    assert before["mtime_ns"] == after["mtime_ns"]
    assert before["signature_digest"] != after["signature_digest"]
    assert history.metadata_snapshot(tmp_path)[0].metadata()["status"] == "timeout"
    # Also catch an in-place rewrite with mtime restored (ctime changes).
    path.write_text(path.read_text().replace('"timeout"', '"running"'))
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert history.fingerprint_for_actions(tmp_path, {"action-one"}) != after


def test_add_delete_corruption_and_repair(tmp_path):
    first = write_job(tmp_path, "one")
    bad = write_job(tmp_path, "bad")
    bad.write_text("{")
    assert len(history.metadata_snapshot(tmp_path)) == 1
    first.unlink()
    write_job(tmp_path, "two")
    write_job(tmp_path, "bad")
    assert {record.metadata()["job_id"] for record in history.metadata_snapshot(tmp_path)} == {"two", "bad"}


def test_metadata_is_detached_and_full_reads_use_actual_directory(tmp_path):
    write_job(tmp_path, "real", job_id="../elsewhere", outcome={"status": "completed", "payload": [1]})
    record = history.metadata_snapshot(tmp_path)[0]
    metadata = record.metadata()
    metadata["status"] = "running"
    metadata["outcome"]["status"] = "failed"
    assert history.metadata_snapshot(tmp_path)[0].metadata()["status"] == "completed"
    assert record.metadata()["outcome"]["status"] == "completed"
    assert history.recent_jobs(tmp_path, 1)[0]["outcome"]["payload"] == [1]


@pytest.mark.parametrize("limit", [0, 1, 2, 20, -1])
def test_list_contract_matches_full_parse_including_ties(tmp_path, limit):
    store = LlmJobStore(tmp_path)
    for name, created in [("z", "same"), ("a", "first"), ("m", "same")]:
        write_job(store.jobs_dir, name, created_at=created)
    expected = [json.loads(path.read_text()) for path in store.jobs_dir.glob("*/job.json")]
    expected.sort(key=lambda job: job.get("created_at") or "")
    assert store.list_jobs(limit) == expected[-limit:]


def test_selected_file_change_retries_selection(tmp_path, monkeypatch):
    path = write_job(tmp_path, "one")
    history.metadata_snapshot(tmp_path)
    original = history._stable_read
    changed = False

    def read(selected):
        nonlocal changed
        if not changed:
            changed = True
            write_job(tmp_path, "one", status="failed")
        return original(selected)

    monkeypatch.setattr(history, "_stable_read", read)
    assert history.recent_jobs(tmp_path, 1)[0]["status"] == "failed"


def test_unstable_history_cannot_report_idle(tmp_path, monkeypatch):
    store = LlmJobStore(tmp_path)
    write_job(store.jobs_dir, "one", status="running", worker_status="running")

    def unstable(path):
        raise history.JobHistoryChanged("concurrent replacement")

    monkeypatch.setattr(history, "_stable_read", unstable)
    with pytest.raises(history.JobHistoryChanged):
        store.active_primary_job()


def test_unreadable_history_cannot_report_idle(tmp_path, monkeypatch):
    store = LlmJobStore(tmp_path)
    write_job(store.jobs_dir, "one", status="running", worker_status="running")
    original = os.scandir

    def scan(path):
        if Path(path) == store.jobs_dir:
            raise PermissionError("unreadable job history")
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    with pytest.raises(PermissionError):
        store.active_primary_job()


def test_empty_thread_fingerprint_does_not_read_unrelated_jobs(tmp_path, monkeypatch):
    def unexpected(_):
        raise AssertionError("Unrelated history was read")

    monkeypatch.setattr(history, "metadata_snapshot", unexpected)
    assert history.fingerprint_for_actions(tmp_path, set())["size"] == 0


def test_stable_reader_rejects_repeated_replacement(tmp_path, monkeypatch):
    path = write_job(tmp_path, "one")
    original = Path.stat

    def stat(selected, *args, **kwargs):
        if selected == path:
            replacement = selected.with_suffix(".next")
            replacement.write_bytes(selected.read_bytes())
            replacement.replace(selected)
            return original(selected, *args, **kwargs)
        return original(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(history.JobHistoryChanged):
        history._stable_read(path)


def test_cache_bounds_do_not_truncate_results(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_MAX_ROOTS", 2)
    monkeypatch.setattr(history, "_MAX_ENTRIES", 1)
    monkeypatch.setattr(history, "_MAX_BYTES", 2000)
    for index in range(3):
        root = tmp_path / str(index)
        write_job(root, "one")
        write_job(root, "two", summary="x" * 10000)
        assert len(history.metadata_snapshot(root)) == 2
    assert len(history._CATALOGS) <= 2
    assert all(len(entries) <= 1 for entries in history._CATALOGS.values())
    assert all(sum(item[2] for item in entries.values()) <= 2000 for entries in history._CATALOGS.values())


def test_shared_budget_evicts_old_roots_without_partial_new_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_MAX_TOTAL_BYTES", 2500)
    roots = [tmp_path / str(index) for index in range(3)]
    for root in roots:
        write_job(root, "one")
        assert history.recent_jobs(root, 20)[0]["job_id"] == "one"
    assert roots[0] not in history._CATALOGS
    assert roots[-1] in history._CATALOGS
    assert sum(item[2] for entries in history._CATALOGS.values() for item in entries.values()) <= 2500
    # Returning to an evicted root still yields its authoritative full record.
    assert history.recent_jobs(roots[0], 20)[0]["summary"] == "retained"


def test_fitting_working_history_is_not_reparsed_after_warmup(tmp_path, monkeypatch):
    # Exceed the old 16 MiB estimate with only 12 files, staying below 64 MiB.
    # This catches repeated warm decodes without a 24k-file fixture on every run.
    # Full-count benchmarks separately cover the observed live history size.
    for index in range(12):
        write_job(tmp_path, str(index), summary="x" * 400_000)
    original = history._stable_read
    reads = []

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(history, "_stable_read", read)
    history.metadata_snapshot(tmp_path)
    assert len(reads) == 12
    reads.clear()
    assert len(history.metadata_snapshot(tmp_path)) == 12
    assert reads == []
