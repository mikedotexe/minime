"""Reflection invocation boundaries in synthetic stores; no live provider calls."""
import json
import sqlite3
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import autonomous_agent as aa
from minime_autonomy import reflection_publication as publication
from minime_autonomy.mailbox_fs import Directory
from minime_autonomy.source_study import SourceStudyPrompt
from tests.test_private_writing_continuation import STATE, deliver, writing_agent
from tests.test_reflection_integrity_audit import stub_response, evidence_snapshot


INPUT = "a" * 64
TEXT = "A synthetic reflection.\nNEXT: INTROSPECT"
FILENAME = "introspect_2026-10-25T20-01-02.123456.txt"


def retained_delivery(workspace, input_id=INPUT):
    request = json.dumps({"messages": [{"role": "user", "content": "Synthetic input"}]})
    response = json.dumps({"message": {"content": TEXT}, "done": True})
    raw = publication._bytes({"schema": "source_study_navigation_delivery_v1",
                              "output": {"input_kind": "reflection", "navigation_id": input_id},
                              "request_json": request, "response_json": response})
    digest = publication._sha(raw)
    directory = workspace.joinpath(*publication.NAVIGATION, input_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + ".json")
    path.write_bytes(raw)
    return {"page_id": input_id, "artifact_sha256": digest,
            "request_sha256": publication._sha(request.encode()),
            "response_sha256": publication._sha(response.encode())}, path


def complete(workspace):
    operation = publication.ReflectionPublication.begin(workspace, "act_fixture", INPUT)
    receipt, artifact = retained_delivery(workspace)
    result = operation.finalize(receipt, filename=FILENAME, text=TEXT, content=TEXT,
                                metadata=metadata(workspace))
    path = Path(result.path)
    return operation, path, artifact


def metadata(workspace):
    database = workspace / "test.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS sovereignty_journal "
                   "(session_id INTEGER,timestamp REAL,entry_type TEXT,content TEXT,spectral_context TEXT,file_path TEXT)")
    return dict(database=str(database), session_id=1, timestamp=100.0, entry_type="introspect",
                spectral_context="{}", implementation_sha256="c" * 64)


def guard_files(workspace):
    return {p.name: p.read_bytes() for p in (workspace / "runtime/reflection_publications").glob("*.json")}


def test_completed_restart_is_read_only_and_receipts_are_content_free(tmp_path):
    operation, path, _ = complete(tmp_path)
    before = guard_files(tmp_path)
    reopened = publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT, database=tmp_path / "test.db")
    assert reopened.completed and path.read_text() == TEXT
    assert guard_files(tmp_path) == before
    assert all(TEXT.encode() not in raw and b"NEXT:" not in raw for name, raw in before.items() if not name.startswith("intent-"))
    assert len([n for n in before if n.startswith(("action-", "input-"))]) == 2
    assert operation.completed


@pytest.mark.parametrize("stage", ["reserved", "accepted"])
def test_interrupted_stage_never_implicitly_restarts(tmp_path, stage):
    operation = publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    if stage != "reserved":
        retained_delivery(tmp_path)
    before = guard_files(tmp_path)
    with pytest.raises(publication.RecoveryRequired, match="reserved"):
        publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    assert guard_files(tmp_path) == before


def test_action_and_input_cannot_be_rebound(tmp_path):
    publication.ReflectionPublication.begin(tmp_path, "act_first", INPUT)
    before = guard_files(tmp_path)
    with pytest.raises(ValueError, match="identity conflict"):
        publication.ReflectionPublication.begin(tmp_path, "act_first", "b" * 64)
    with pytest.raises(publication.RecoveryRequired, match="already_reserved"):
        publication.ReflectionPublication.begin(tmp_path, "act_other", INPUT)
    assert guard_files(tmp_path) == before


@pytest.mark.parametrize("target", ["receipt", "journal", "delivery", "newer_schema"])
def test_tamper_or_newer_schema_is_not_overwritten(tmp_path, target):
    operation, path, artifact = complete(tmp_path)
    record_path = tmp_path / "runtime/reflection_publications" / operation.name
    if target == "receipt":
        record_path.write_bytes(record_path.read_bytes().replace(b'"published"', b'"reserved"'))
    elif target == "newer_schema":
        record = publication._record(record_path.read_bytes())
        record["schema"] = "minime_reflection_publication_v99"
        record_path.write_bytes(publication._envelope(record))
    else:
        selected = path if target == "journal" else artifact
        selected.write_bytes(selected.read_bytes() + b"changed")
    before = guard_files(tmp_path), path.read_bytes(), artifact.read_bytes()
    with pytest.raises(ValueError):
        publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT, database=tmp_path / "test.db")
    assert (guard_files(tmp_path), path.read_bytes(), artifact.read_bytes()) == before


def test_partial_claim_fails_closed_and_preserves_receipt(tmp_path, monkeypatch):
    atomic = Directory.atomic

    def interrupt(directory, name, raw, **kwargs):
        if name.startswith("input-"):
            raise OSError("synthetic interruption before input index")
        return atomic(directory, name, raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt)
        with pytest.raises(OSError):
            publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    before = guard_files(tmp_path)
    with pytest.raises(OSError):
        publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    assert guard_files(tmp_path) == before


def test_post_link_failure_retains_public_file_and_no_replay(tmp_path, monkeypatch):
    operation = publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    receipt, _ = retained_delivery(tmp_path)
    atomic = Directory.atomic

    def interrupt(directory, name, raw, **kwargs):
        result = atomic(directory, name, raw, **kwargs)
        if name == FILENAME:
            raise OSError("synthetic loss of publication acknowledgement")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt)
        result = operation.finalize(receipt, filename=FILENAME, text=TEXT, content=TEXT, metadata=metadata(tmp_path))
    assert result.publication == "published"
    assert (tmp_path / "journal" / FILENAME).read_text() == TEXT
    reopened = publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT, database=tmp_path / "test.db")
    assert reopened.result.indexing == "indexed"


def test_filename_collision_is_not_ownership_evidence(tmp_path):
    operation = publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    receipt, _ = retained_delivery(tmp_path)
    (tmp_path / "journal").mkdir()
    path = tmp_path / "journal" / FILENAME
    path.write_text(TEXT)
    with pytest.raises(ValueError, match="already exists"):
        operation.finalize(receipt, filename=FILENAME, text=TEXT, content=TEXT, metadata=metadata(tmp_path))
    assert path.read_text() == TEXT


def test_symlink_cannot_redirect_receipt_storage(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "runtime").symlink_to(elsewhere)
    with pytest.raises(OSError):
        publication.ReflectionPublication.begin(tmp_path, "act_fixture", INPUT)
    assert not list(elsewhere.iterdir())


def test_first_claim_exclusively_establishes_lock_before_locking(tmp_path, monkeypatch):
    original = publication.os.open
    observed = []

    def checked_open(path, flags, mode=0o777, *, dir_fd=None):
        if path == ".transaction.lock":
            assert flags & publication.os.O_NOFOLLOW
            assert dir_fd is not None
            if flags & publication.os.O_EXCL:
                observed.append("exclusive-create")
            else:
                info = publication.os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
                assert info.st_size == 0
                observed.append("existing-lock")
        return original(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(publication.os, "open", checked_open)
    publication.ReflectionPublication.begin(tmp_path, "act_initial_lock", INPUT)
    assert observed == ["exclusive-create", "existing-lock"]


@pytest.mark.parametrize("same_action", [False, True])
@pytest.mark.parametrize("released_failure", [False, True])
def test_cross_process_admission_has_one_owner(tmp_path, released_failure, same_action):
    if released_failure:
        operation = publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
        operation.failed_unaccepted()
    # Import only the production guard in each process, not the test module and
    # its runtime fixture dependencies. The stdin barrier precedes acquisition.
    program = """
import sys
from minime_autonomy.reflection_publication import ReflectionPublication, RecoveryRequired
sys.stdin.readline()
try:
    ReflectionPublication.begin(sys.argv[1], sys.argv[2], sys.argv[3])
    print('reserved')
except RecoveryRequired:
    print('refused')
"""
    workers = [subprocess.Popen([sys.executable, "-B", "-c", program, str(tmp_path),
               f"act_race_{0 if same_action else i}", INPUT],
               cwd=Path(publication.__file__).resolve().parents[1], stdin=subprocess.PIPE,
               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
    try:
        for worker in workers:
            worker.stdin.write("start\n")
            worker.stdin.flush()
        results = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=20)
            assert worker.returncode == 0, stderr
            results.append(stdout.strip())
        assert sorted(results) == ["refused", "reserved"]
        with pytest.raises(publication.RecoveryRequired, match="already_reserved"):
            publication.ReflectionPublication.begin(tmp_path, "act_another", INPUT)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
            worker.communicate(timeout=5)


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_exclusive_lock_creation_does_not_adopt_unsafe_existing_path(tmp_path, kind):
    directory = tmp_path / "runtime/reflection_publications"
    directory.mkdir(parents=True)
    target = tmp_path / "foreign.txt"
    target.write_text("unchanged")
    lock = directory / ".transaction.lock"
    if kind == "symlink":
        lock.symlink_to(target)
    else:
        lock.mkdir()
    with pytest.raises((OSError, ValueError)):
        publication.ReflectionPublication.begin(tmp_path, "act_unsafe_lock", INPUT)
    assert target.read_text() == "unchanged"
    assert not list(directory.glob("action-*.json"))


def test_returned_unaccepted_failure_allows_only_new_deliberate_action(tmp_path):
    failed = publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
    failed.failed_unaccepted()
    before = guard_files(tmp_path)
    with pytest.raises(publication.RecoveryRequired, match="failed_unaccepted"):
        publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
    assert guard_files(tmp_path) == before
    retry = publication.ReflectionPublication.begin(tmp_path, "act_deliberate", INPUT)
    assert not retry.completed
    with pytest.raises(publication.RecoveryRequired, match="failed_unaccepted"):
        publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
    receipt, _ = retained_delivery(tmp_path)
    retry.finalize(receipt, filename=FILENAME, text=TEXT, content=TEXT, metadata=metadata(tmp_path))
    with pytest.raises(publication.RecoveryRequired, match="already_reserved"):
        publication.ReflectionPublication.begin(tmp_path, "act_third", INPUT)


def test_failure_acknowledgement_must_be_durable_before_new_action(tmp_path, monkeypatch):
    failed = publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
    before = guard_files(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(failed, "_save", Mock(side_effect=OSError("synthetic failure receipt write error")))
        with pytest.raises(OSError):
            failed.failed_unaccepted()
    with pytest.raises(publication.RecoveryRequired, match="already_reserved"):
        publication.ReflectionPublication.begin(tmp_path, "act_deliberate", INPUT)
    assert guard_files(tmp_path) == before


@pytest.mark.parametrize("delivery_before_failure", [False, True])
def test_native_delivery_prevents_failed_input_release_or_later_retry(tmp_path, delivery_before_failure):
    failed = publication.ReflectionPublication.begin(tmp_path, "act_failed", INPUT)
    if not delivery_before_failure:
        failed.failed_unaccepted()
    retained_delivery(tmp_path)
    before = guard_files(tmp_path)
    if delivery_before_failure:
        with pytest.raises(publication.RecoveryRequired, match="not verified unaccepted"):
            failed.failed_unaccepted()
    with pytest.raises(publication.RecoveryRequired):
        publication.ReflectionPublication.begin(tmp_path, "act_deliberate", INPUT)
    assert guard_files(tmp_path) == before


def test_adapter_returned_transport_failure_allows_new_action_for_exact_pending_input(writing_agent, monkeypatch):
    agent, client = writing_agent
    pending = client.prepare("INTROSPECT", request_id="prepare-act_failed")
    # Exercise the real native pending offer and delivery, explicitly reselected
    # under a new host action. Never generate a substitute input for the retry.
    monkeypatch.setattr(client, "prepare", lambda *args, **kwargs: SourceStudyPrompt(client, pending.output))
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(side_effect=[aa.requests.ConnectionError("synthetic disconnected request"), stub_response(TEXT)])
    monkeypatch.setattr(aa.requests, "post", post)
    agent._current_action_continuity_event = {"action_id": "act_failed"}
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert post.call_count == 1 and not evidence_snapshot(client)
    assert not list((client.workspace / "journal").glob("introspect_*.txt"))
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert post.call_count == 1
    agent._current_action_continuity_event = {"action_id": "act_deliberate"}
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert post.call_count == 2
    assert len(evidence_snapshot(client)) == 1
    assert len(list((client.workspace / "journal").glob("introspect_*.txt"))) == 1
    assert agent._pending_next_action == "INTROSPECT"
    agent._current_action_continuity_event = {"action_id": "act_republish"}
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert post.call_count == 2 and agent._pending_next_action == "INTROSPECT"


def test_completed_adapter_retry_never_asks_for_differing_response(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_retry"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(side_effect=[stub_response(TEXT), stub_response("Different output.\nNEXT: REST")])
    monkeypatch.setattr(aa.requests, "post", post)
    record_choice = Mock(wraps=agent._record_llm_next_action_choice)
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", record_choice)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    first_receipts = evidence_snapshot(client)
    agent._pending_next_action = "REST"  # A later authored choice must survive the duplicate.
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    post.assert_called_once()
    record_choice.assert_called_once()
    assert agent._pending_next_action == "REST"
    assert evidence_snapshot(client) == first_receipts
    assert len(list((client.workspace / "journal").glob("introspect_*.txt"))) == 1
    assert "already completed" in agent._current_action_outcome_summary


def test_new_explicit_action_still_generates_and_lock_is_not_held_across_provider(writing_agent, monkeypatch):
    agent, client = writing_agent
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    prepare, offers = client.prepare, []

    def prepared(*args, **kwargs):
        prompt = prepare(*args, **kwargs)
        offers.append(prompt)
        return prompt

    monkeypatch.setattr(client, "prepare", prepared)

    def provider(*args, **kwargs):
        with Directory(client.workspace / "runtime/reflection_publications") as directory:
            with directory.lock(".transaction.lock", nonblocking=True):
                pass
        return stub_response(TEXT)

    post = Mock(side_effect=provider)
    monkeypatch.setattr(aa.requests, "post", post)
    for ident in ("act_fresh_one", "act_fresh_two"):
        agent._current_action_continuity_event = {"action_id": ident}
        agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert post.call_count == 2
    assert len(offers) == 2
    assert offers[0].output["navigation_id"] != offers[1].output["navigation_id"]
    assert (str(offers[0]).replace(offers[0].output["navigation_id"], "INPUT_ID")
            == str(offers[1]).replace(offers[1].output["navigation_id"], "INPUT_ID"))
    assert len(list((client.workspace / "journal").glob("introspect_*.txt"))) == 2
    assert len(evidence_snapshot(client)) == 2


def test_crash_after_delivery_preserves_next_and_does_not_regenerate(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_crash"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(return_value=stub_response(TEXT))
    monkeypatch.setattr(aa.requests, "post", post)
    with monkeypatch.context() as patch:
        patch.setattr(publication.ReflectionPublication, "finalize", Mock(side_effect=KeyboardInterrupt))
        with pytest.raises(KeyboardInterrupt):
            agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    before = evidence_snapshot(client)
    assert before and agent._pending_next_action == "INTROSPECT"
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    post.assert_called_once()
    assert evidence_snapshot(client) == before
    assert agent._pending_next_action == "INTROSPECT"
    pending = client.prepare("INTROSPECT", request_id="prepare-act_crash")
    monkeypatch.setattr(client, "prepare", lambda *args, **kwargs: SourceStudyPrompt(client, pending.output))
    agent._current_action_continuity_event = {"action_id": "act_after_crash"}
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    post.assert_called_once()
    assert evidence_snapshot(client) == before and agent._pending_next_action == "INTROSPECT"
    notices = list((client.workspace / "diagnostics/source_study/notices").glob("runtime_notice_*.txt"))
    assert any("reflection_publication_recovery_required:reserved" in p.read_text() for p in notices)


def test_legacy_delivered_input_is_not_resubmitted(writing_agent, monkeypatch):
    agent, client = writing_agent
    prompt = client.prepare("INTROSPECT", request_id="prepare-act_legacy")
    deliver(prompt, TEXT)
    agent._current_action_continuity_event = {"action_id": "act_legacy"}
    provider = Mock(side_effect=AssertionError("legacy accepted input must not resubmit"))
    monkeypatch.setattr(agent, "_query_llm", provider)
    before = evidence_snapshot(client)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    provider.assert_not_called()
    assert evidence_snapshot(client) == before
    assert "legacy_delivery" in agent._current_action_outcome_summary
