"""Synthetic receipt capacity and failed-sync retries; no provider activity."""
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from minime_autonomy import maintenance_next as handoff
from minime_autonomy.llm_access import LlmJobStore


def owner(root, boot):
    return SimpleNamespace(
        _agent_boot_id=boot * 32, _agent_pid=123, _agent_started_at="synthetic",
        _agent_inputs_at_start={"fixture.py": "a" * 64},
        _pending_next_action="REST", _pending_next_selection_id="selection",
        _pending_choice_envelope_v1=None,
        _sovereignty_state_path=lambda: root / "sovereignty_state.json")


def prepare(root):
    old = owner(root, "a")
    handoff.write_state(old._sovereignty_state_path(), {
        "pending_next_action": "REST", "pending_next_selection_id": "selection"})
    return old


@pytest.mark.parametrize("bound,value", [("MAX_RECORDS", 1), ("MAX_HISTORY", 2048)])
def test_seal_refuses_before_spending_replacement_capacity(tmp_path, bound, value):
    old = prepare(tmp_path)
    before = old._sovereignty_state_path().read_bytes()
    with patch.object(handoff, bound, value):
        with pytest.raises(handoff.HandoffError, match="capacity_for_restore"):
            handoff.seal(old)
    assert not handoff.stream_path(old._sovereignty_state_path()).exists()
    assert old._sovereignty_state_path().read_bytes() == before


def test_exact_two_record_capacity_allows_seal_and_restore(tmp_path):
    old = prepare(tmp_path)
    with patch.object(handoff, "MAX_RECORDS", 2):
        sealed = handoff.seal(old)
        restored = handoff.restore(owner(tmp_path, "b"))
        assert restored["seal_sha256"] == sealed["record_sha256"]
        assert handoff.seal(old) == sealed
    assert len(handoff.history(old._sovereignty_state_path())[0]) == 2


def test_legacy_unacknowledged_seal_retry_rechecks_headroom(tmp_path):
    old = prepare(tmp_path)
    handoff.seal(old)
    path = handoff.stream_path(old._sovereignty_state_path())
    before = path.read_bytes()
    with patch.object(handoff, "MAX_HISTORY", len(before) + 1):
        with pytest.raises(handoff.HandoffError, match="capacity_for_restore"):
            handoff.seal(old)
    assert path.read_bytes() == before


def running(root):
    store = LlmJobStore(root)
    job = store.submit(action_id="synthetic-action", thread_id="synthetic-thread",
                       action_text="JOURNAL", call_kind="journal")
    store.claim_running(job["job_id"])
    return store, job["job_id"]


def inode(fd, path):
    info = os.fstat(fd)
    actual = path.stat()
    return (info.st_dev, info.st_ino) == (actual.st_dev, actual.st_ino)


@pytest.mark.parametrize("target", ["event", "directory"])
def test_visible_outcome_retry_must_resync_exact_retained_bytes(tmp_path, target):
    store, job_id = running(tmp_path)
    directory = store.jobs_dir / job_id
    path = directory / "events.jsonl"
    original = os.fsync

    def fail(fd):
        if b'"outcome_sha256"' in path.read_bytes() and inode(fd, path if target == "event" else directory):
            raise OSError(errno.ENOSPC, "synthetic sync failure")
        return original(fd)

    with patch.object(os, "fsync", fail):
        with pytest.raises(OSError):
            store.finish(job_id, "completed", result="Authored fixture", summary="Saved")
        before = path.read_bytes()
        for _ in range(2):
            with pytest.raises(OSError):
                store.finish(job_id, "completed", result="Authored fixture", summary="Saved")
            assert path.read_bytes() == before
    store.finish(job_id, "completed", result="Authored fixture", summary="Saved")
    assert path.read_bytes() == before
    assert sum("outcome_sha256" in json.loads(line) for line in before.splitlines()) == 1
    assert (directory / "result.txt").read_text() == "Authored fixture"


@pytest.mark.parametrize("tail", [b'{"outcome_sha256":', b'not-json\n', b'[]\n'])
def test_corrupt_event_history_is_preserved_and_refuses_completion(tmp_path, tail):
    store, job_id = running(tmp_path)
    path = store.jobs_dir / job_id / "events.jsonl"
    with path.open("ab") as handle:
        handle.write(tail)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.finish(job_id, "completed", result="Retain despite receipt failure")
    assert path.read_bytes() == before
    assert (path.parent / "result.txt").read_text() == "Retain despite receipt failure"


def test_duplicate_outcome_hash_with_changed_payload_is_not_acknowledged(tmp_path):
    store, job_id = running(tmp_path)
    store.finish(job_id, "completed", result="Fixture", summary="Saved")
    path = store.jobs_dir / job_id / "events.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[-1]["summary"] = "Not the saved outcome"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Conflicting LLM outcome"):
        store.finish(job_id, "completed", result="Fixture", summary="Saved")
    assert path.read_bytes() == before
