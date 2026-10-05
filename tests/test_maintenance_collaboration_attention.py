"""Collaboration checkpoint merges share the exact NEXT queue transaction."""

import json
import threading
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import pytest

import autonomous_agent as aa
from minime_autonomy import collaboration_attention as collab
from minime_autonomy import maintenance_next as maintenance


def choice_state():
    return {
        "session_id": 42,
        "pending_next_action": "WRITE CONTINUE",
        "pending_next_selection_id": "selection-A",
        "choice_envelope_v1": {"source": "A", "nested": ["exact", {"x": 1}]},
        "pending_next_action_status": "pending",
        "pending_next_action_updated_at": "2020-01-01T00:00:00",
        "pending_next_action_update_reason": "authored choice A",
        "foreign_future_field": {"preserve": [1, None, "\u00e9"]},
    }


def checkpoint():
    value = collab.empty_checkpoint()
    value["migration_complete"] = True
    value["satisfied_revisions"]["coll_test"] = "sha256:" + "a" * 64
    return value


@pytest.mark.parametrize("new_action", ["WRITE CONTINUE", "WRITE REVISE synthetic direction"])
def test_merge_read_a_cannot_overwrite_newer_runtime_selection(tmp_path, monkeypatch, new_action):
    path = tmp_path / "sovereignty_state.json"
    before = choice_state()
    maintenance.write_state(path, before)
    update = checkpoint()
    merge_read, release_merge = threading.Event(), threading.Event()
    selection_attempted, selection_finished = threading.Event(), threading.Event()
    errors, selected = [], {}

    agent = object.__new__(aa.AutonomousAgent)
    agent._agent_boot_id = uuid4().hex
    agent.session_id = 42
    agent.cycle_count = 7
    agent._pending_next_action = new_action
    agent._pending_next_selection_id = None
    agent._pending_choice_envelope_v1 = {"source": "B", "nested": ["exact B", {"x": 2}]}
    agent._recent_next_actions = []
    agent._sovereignty_state_path = lambda: str(path)
    monkeypatch.setattr(aa, "StudyFeedback", Mock())

    original_checkpoint = collab.checkpoint_from_state
    original_transaction = maintenance.transaction

    def pause_after_read(state):
        if threading.current_thread() is merge_worker:
            merge_read.set()
            assert release_merge.wait(5), "merge barrier was not released"
        return original_checkpoint(state)

    @contextmanager
    def observe_transaction(state_path):
        if threading.current_thread() is selection_worker:
            selection_attempted.set()
        with original_transaction(state_path):
            yield

    def merge():
        try:
            collab.merge_checkpoint_file(path, update)
        except Exception as error:
            errors.append(error)

    def select():
        try:
            agent._persist_pending_next_action(new_action, reason="synthetic authored choice B")
            selected.update(json.loads(path.read_bytes()))
        except Exception as error:
            errors.append(error)
        finally:
            selection_finished.set()

    merge_worker = threading.Thread(target=merge)
    selection_worker = threading.Thread(target=select)
    monkeypatch.setattr(collab, "checkpoint_from_state", pause_after_read)
    monkeypatch.setattr(maintenance, "transaction", observe_transaction)
    merge_worker.start()
    try:
        assert merge_read.wait(5), "merge did not reach its post-read barrier"
        selection_worker.start()
        assert selection_attempted.wait(5), "runtime selection did not attempt the shared lock"
        finished_while_merge_paused = selection_finished.wait(0.1)
    finally:
        release_merge.set()
        merge_worker.join(5)
        if selection_worker.ident is not None:
            selection_worker.join(5)
    assert not merge_worker.is_alive() and not selection_worker.is_alive()
    assert not errors
    assert not finished_while_merge_paused
    assert selected["pending_next_selection_id"] != before["pending_next_selection_id"]
    assert selected["pending_next_action"] == new_action
    assert selected["choice_envelope_v1"] == agent._pending_choice_envelope_v1
    final = json.loads(path.read_bytes())
    for key in maintenance.PENDING_KEYS:
        assert final.get(key) == selected.get(key)
    assert final[collab.STATE_KEY] == update
    assert final["foreign_future_field"] == before["foreign_future_field"]


def test_merge_changes_only_collaboration_checkpoint(tmp_path):
    path = tmp_path / "sovereignty_state.json"
    before = choice_state()
    before[collab.STATE_KEY] = collab.empty_checkpoint()
    maintenance.write_state(path, before)
    update = checkpoint()

    collab.merge_checkpoint_file(path, update)

    assert json.loads(path.read_bytes()) == {**before, collab.STATE_KEY: update}


def test_merge_creates_missing_state_in_missing_parent(tmp_path):
    path = tmp_path / "new-owner" / "sovereignty_state.json"
    update = checkpoint()

    collab.merge_checkpoint_file(path, update)

    assert json.loads(path.read_bytes()) == {collab.STATE_KEY: update}


@pytest.mark.parametrize("raw", [
    b'{"pending_next_action":',
    b'[]',
    b'{"pending_next_action":"REST","pending_next_action":"WRITE CONTINUE"}',
    b'{"foreign_future_field":NaN}',
])
def test_merge_rejects_invalid_state_without_rewriting_bytes(tmp_path, raw):
    path = tmp_path / "sovereignty_state.json"
    path.write_bytes(raw)

    with pytest.raises(maintenance.HandoffError):
        collab.merge_checkpoint_file(path, checkpoint())

    assert path.read_bytes() == raw


@pytest.mark.parametrize("stage", ["read", "replace"])
def test_merge_io_failure_preserves_existing_state(tmp_path, monkeypatch, stage):
    path = tmp_path / "sovereignty_state.json"
    maintenance.write_state(path, choice_state())
    before = path.read_bytes()
    failure = Mock(side_effect=OSError("synthetic merge failure"))
    if stage == "read":
        monkeypatch.setattr(maintenance, "read", failure)
    else:
        monkeypatch.setattr(maintenance.os, "replace", failure)

    with pytest.raises(OSError, match="synthetic merge failure"):
        collab.merge_checkpoint_file(path, checkpoint())

    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))
