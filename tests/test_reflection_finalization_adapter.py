"""Real native reflection delivery with synthetic providers and local fault stores."""

import ast
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy.mailbox_fs import Directory
from scripts import reconcile_reflection as cli
from tests.test_private_writing_continuation import STATE, writing_agent
from tests.test_reflection_finalization_recovery import ProcessInterrupted, snapshot
from tests.test_reflection_integrity_audit import evidence_snapshot, stub_response


FROZEN_HELPER = Path(
    "/Users/v/other/worktrees/lighter-reflection-20261025/bridge-stage-02/helpers/astrid-source-study"
)
PARENT_REVISION = "e86801d98c5aa4a2b1725fba99356049f647d674"
ACTION = "act_adapter_finalization"
BODY = "A synthetic caf\u00e9 reflection.\nQuoted `NEXT: REST` remains prose.\nNEXT: INTROSPECT"
FAULTS = ["intent-ack", "file-before", "file-after", "db-before", "db-after"]
CHOICE_SCOPE = "at_publication_intent_not_current_queue"


@pytest.fixture
def frozen_helper(monkeypatch):
    helper = Path(os.environ.get("ASTRID_SOURCE_STUDY_BIN", str(FROZEN_HELPER)))
    assert helper.is_file(), "This qualification requires an existing native helper"
    if "ASTRID_SOURCE_STUDY_BIN" not in os.environ:
        monkeypatch.setenv("ASTRID_SOURCE_STUDY_BIN", str(helper))


@pytest.mark.parametrize("configured", [False, True], ids=["fallback", "environment-override"])
def test_helper_fixture_preserves_qualification_override(tmp_path, monkeypatch, configured):
    helper = tmp_path / "synthetic-helper-marker"
    helper.write_bytes(b"fixture path only; never executed")
    monkeypatch.setattr(sys.modules[__name__], "FROZEN_HELPER",
                        tmp_path / "unavailable-default" if configured else helper)
    if configured:
        monkeypatch.setenv("ASTRID_SOURCE_STUDY_BIN", str(helper))
    else:
        monkeypatch.delenv("ASTRID_SOURCE_STUDY_BIN", raising=False)
    frozen_helper.__wrapped__(monkeypatch)
    assert os.environ["ASTRID_SOURCE_STUDY_BIN"] == str(helper)


@pytest.fixture
def adapter(frozen_helper, writing_agent, monkeypatch):
    agent, client = writing_agent
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(return_value=stub_response(BODY))
    monkeypatch.setattr(aa.requests, "post", post)
    spies = {}
    for name in ("_query_llm_with_next", "_record_llm_next_action_choice",
                 "_journal_before_index", "_journal_after_index"):
        spies[name] = Mock(wraps=getattr(agent, name))
        monkeypatch.setattr(agent, name, spies[name])
    prepare = Mock(wraps=client.prepare)
    monkeypatch.setattr(client, "prepare", prepare)
    agent._current_action_continuity_event = {"action_id": ACTION, "llm_job_id": "job_adapter_fixture"}
    return SimpleNamespace(
        agent=agent, client=client, database=Path(aa.DB_PATH), post=post,
        query=spies["_query_llm_with_next"], choice=spies["_record_llm_next_action_choice"],
        before=spies["_journal_before_index"], after=spies["_journal_after_index"], prepare=prepare,
    )


def journal_rows(adapter):
    with sqlite3.connect(adapter.database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM sovereignty_journal ORDER BY id")]


def run_reflection(adapter):
    adapter.agent._run_shared_source_study(dict(STATE), "INTROSPECT")


def queue_snapshot(adapter):
    agent = adapter.agent
    return (
        (adapter.client.workspace / "sovereignty_state.json").read_bytes(),
        deepcopy((agent._pending_next_action, agent._pending_next_selection_id,
                  getattr(agent, "_pending_choice_envelope_v1", None))),
    )


def select_later_queue(adapter, pending):
    agent = adapter.agent
    if pending != "INTROSPECT":
        agent._pending_next_action = pending
        agent._persist_pending_next_action(pending, reason="synthetic later choice",
                                          expected_action="INTROSPECT")
    assert agent._pending_next_action == pending
    stored = json.loads((adapter.client.workspace / "sovereignty_state.json").read_bytes())
    assert stored.get("pending_next_action") == pending


def seed_protected_history(adapter):
    private = adapter.client.workspace / "private_writing"
    (private / "journal").mkdir(parents=True, exist_ok=True)
    (private / "journal/retained-draft.txt").write_text("Synthetic private writing stays private.\n")
    (private / "parked-state.json").write_text('{"parked":true,"synthetic":true}')
    job = adapter.client.workspace / "llm_jobs/jobs/job_adapter_fixture/job.json"
    job.parent.mkdir(parents=True, exist_ok=True)
    job.write_text('{"status":"failed","historical":true,"job_id":"job_adapter_fixture"}')
    return private, job


def forbid_replay(adapter):
    spies = (adapter.post, adapter.query, adapter.choice, adapter.agent._apply_footer_directives,
             adapter.before, adapter.after, adapter.agent._write_journal_entry)
    before = tuple(spy.call_count for spy in spies)
    for spy in spies:
        spy.side_effect = AssertionError("recovery must not replay model, response effects, or hooks")
    return lambda: tuple(spy.call_count for spy in spies) == before


def assert_published_and_indexed(adapter):
    paths = list((adapter.client.workspace / "journal").glob("introspect_*.txt"))
    assert len(paths) == 1
    assert paths[0].read_bytes().endswith((BODY + "\n").encode("utf-8"))
    rows = journal_rows(adapter)
    assert len(rows) == 1
    assert rows[0]["content"] == BODY and rows[0]["entry_type"] == "introspect"
    assert rows[0]["session_id"] == adapter.agent.session_id
    assert rows[0]["file_path"] == str(paths[0])
    assert rows[0]["publication_id"]
    return paths[0], rows[0]


@contextmanager
def injected_fault(adapter, monkeypatch, boundary):
    atomic, connect = Directory.atomic, sqlite3.connect
    reached = []

    def interrupt_write(directory, name, raw, **kwargs):
        intent = name.startswith("intent-") and name.endswith(".json")
        public = directory.path == adapter.client.workspace / "journal" and name.startswith("introspect_")
        selected = ((intent and boundary in {"intent-before", "intent-ack"})
                    or (public and boundary in {"file-before", "file-after"}))
        if selected:
            reached.append(boundary)
            if boundary in {"intent-ack", "file-after"}:
                atomic(directory, name, raw, **kwargs)
            raise OSError("synthetic durable-write interruption")
        return atomic(directory, name, raw, **kwargs)

    class FaultConnection(sqlite3.Connection):
        def commit(self):
            columns = {row[1] for row in self.execute("PRAGMA table_info(sovereignty_journal)")}
            selected = (boundary.startswith("db-") and self.in_transaction
                        and "publication_id" in columns
                        and self.execute("SELECT COUNT(*) FROM sovereignty_journal "
                                         "WHERE publication_id IS NOT NULL").fetchone()[0])
            if selected:
                reached.append(boundary)
                if boundary == "db-after":
                    super().commit()
                raise sqlite3.OperationalError("synthetic reflection commit acknowledgement loss")
            return super().commit()

    def connection(*args, **kwargs):
        kwargs["factory"] = FaultConnection
        return connect(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Directory, "atomic", interrupt_write)
        patch.setattr(sqlite3, "connect", connection)
        yield reached
    assert reached == [boundary]


def assert_first_fault_status(adapter, boundary):
    adapter.post.assert_called_once()
    adapter.query.assert_called_once()
    adapter.choice.assert_called_once()
    adapter.agent._write_journal_entry.assert_not_called()
    assert adapter.agent._pending_next_action == "INTROSPECT"
    assert len(evidence_snapshot(adapter.client)) == 1
    expected_rows = 1 if boundary == "db-after" else 0
    assert len(journal_rows(adapter)) == expected_rows
    if boundary.startswith("intent-"):
        assert not getattr(adapter.agent, "_last_reflection_finalization", None)
    else:
        result = adapter.agent._last_reflection_finalization
        assert result["accepted"] is True and result["choice"] == "recorded"
        assert result["choice_scope"] == CHOICE_SCOPE
        assert result["publication"] == ("prepared" if boundary == "file-before" else "published")
        assert result["indexing"] == ("indexed" if boundary == "db-after" else "pending")
        assert result["reason"] == "local_finalization_incomplete"
        assert f"publication={result['publication']}" in adapter.agent._current_action_outcome_summary
        assert f"indexing={result['indexing']}" in adapter.agent._current_action_outcome_summary
        assert "choice_at_freeze=recorded" in adapter.agent._current_action_outcome_summary
    assert adapter.before.call_count == int(boundary.startswith("db-"))
    adapter.after.assert_not_called()


@pytest.mark.parametrize("boundary", FAULTS)
@pytest.mark.parametrize("pending", ["INTROSPECT", "REST", None], ids=["pending", "superseded", "consumed"])
def test_runtime_reentry_recovers_without_replaying_native_choice_or_callbacks(adapter, monkeypatch, boundary, pending):
    with injected_fault(adapter, monkeypatch, boundary):
        run_reflection(adapter)
    assert_first_fault_status(adapter, boundary)
    select_later_queue(adapter, pending)
    private, job = seed_protected_history(adapter)
    before = queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)
    unchanged_calls = forbid_replay(adapter)
    for _ in range(2):
        run_reflection(adapter)
        assert_published_and_indexed(adapter)
        status = adapter.agent._last_reflection_finalization
        assert status["publication"] == "published" and status["indexing"] == "indexed"
        assert status["choice"] == "recorded"
        assert status["choice_scope"] == CHOICE_SCOPE
        assert "choice_at_freeze=recorded" in adapter.agent._current_action_outcome_summary
        assert "No provider call or NEXT replay" in adapter.agent._current_action_outcome_summary
    assert unchanged_calls()
    assert (queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)) == before


@pytest.mark.parametrize("boundary", FAULTS)
@pytest.mark.parametrize("pending", ["REST", None], ids=["superseded", "consumed"])
def test_startup_recovery_only_repairs_publication_and_index(adapter, monkeypatch, boundary, pending):
    with injected_fault(adapter, monkeypatch, boundary):
        run_reflection(adapter)
    assert_first_fault_status(adapter, boundary)
    select_later_queue(adapter, pending)
    private, job = seed_protected_history(adapter)
    before = queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)
    unchanged_calls = forbid_replay(adapter)
    prepares = adapter.prepare.call_count
    adapter.agent._current_action_continuity_event = None
    adapter.agent._recover_reflection_publications()
    assert adapter.agent._reflection_recovery_status == {
        "examined": 1, "published": 1, "indexed": 1, "unresolved": 0}
    assert_published_and_indexed(adapter)
    adapter.agent._recover_reflection_publications()
    assert adapter.agent._reflection_recovery_status == {
        "examined": 0, "published": 0, "indexed": 0, "unresolved": 0}
    assert adapter.prepare.call_count == prepares and unchanged_calls()
    assert (queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)) == before


def test_adapter_failure_before_seal_preserves_native_acceptance_but_never_regenerates(adapter, monkeypatch):
    with injected_fault(adapter, monkeypatch, "intent-before"):
        run_reflection(adapter)
    assert_first_fault_status(adapter, "intent-before")
    before = queue_snapshot(adapter), evidence_snapshot(adapter.client)
    unchanged_calls = forbid_replay(adapter)
    run_reflection(adapter)
    adapter.agent._recover_reflection_publications()
    assert adapter.agent._reflection_recovery_status["unresolved"] == 1
    assert not list((adapter.client.workspace / "journal").glob("introspect_*.txt"))
    assert journal_rows(adapter) == []
    assert unchanged_calls()
    assert (queue_snapshot(adapter), evidence_snapshot(adapter.client)) == before


def test_reflection_uses_first_run_callbacks_once_not_generic_journal_writer(adapter):
    run_reflection(adapter)
    path, row = assert_published_and_indexed(adapter)
    adapter.before.assert_called_once_with("introspect", BODY, STATE, str(path))
    adapter.after.assert_called_once_with("introspect", BODY, str(path))
    adapter.agent._write_journal_entry.assert_not_called()
    status = adapter.agent._last_reflection_finalization
    assert status["diagnostics"] == "completed"
    assert status["choice_scope"] == CHOICE_SCOPE
    assert status["publication_id"] == row["publication_id"]
    assert BODY not in json.dumps(status)
    unchanged_calls = forbid_replay(adapter)
    run_reflection(adapter)
    assert unchanged_calls()


@pytest.mark.parametrize("hook", ["before", "after"])
@pytest.mark.parametrize("hard_crash", [False, True], ids=["returned-error", "interrupted-process"])
def test_callback_failures_do_not_erase_writing_or_authorize_callback_replay(adapter, hook, hard_crash):
    selected = getattr(adapter, hook)
    selected.side_effect = ProcessInterrupted("synthetic callback interruption") if hard_crash else RuntimeError("synthetic callback failure")
    if hard_crash:
        with pytest.raises(ProcessInterrupted):
            run_reflection(adapter)
    else:
        run_reflection(adapter)
        assert adapter.agent._last_reflection_finalization["diagnostics"] == "incomplete"
        assert_published_and_indexed(adapter)
    selected.assert_called_once()
    before = queue_snapshot(adapter), evidence_snapshot(adapter.client)
    unchanged_calls = forbid_replay(adapter)
    run_reflection(adapter)
    assert_published_and_indexed(adapter)
    assert adapter.agent._last_reflection_finalization["diagnostics"] == "incomplete"
    assert unchanged_calls()
    assert (queue_snapshot(adapter), evidence_snapshot(adapter.client)) == before


@pytest.mark.parametrize("action,entry_type", [
    ("SELF_STUDY MAP", "study_navigation"),
    ("WRITE START synthetic adapter draft", "private_writing"),
])
def test_nonreflection_routes_still_use_generic_writer(adapter, action, entry_type):
    adapter.post.return_value = stub_response("Synthetic nonreflection response.\nNEXT: REST")
    adapter.agent._run_shared_source_study(dict(STATE), action)
    adapter.post.assert_called_once()
    adapter.agent._write_journal_entry.assert_called_once()
    assert adapter.agent._write_journal_entry.call_args.args[0] == entry_type
    adapter.before.assert_not_called()
    adapter.after.assert_not_called()
    assert not list((adapter.client.workspace / "runtime/reflection_publications").glob("intent-*.json"))


def test_generic_journal_writer_retains_callback_database_contract(adapter):
    path = adapter.client.workspace / "journal/daydream_synthetic.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BODY)
    aa.AutonomousAgent._write_journal_entry(adapter.agent, "daydream", BODY, dict(STATE), str(path))
    adapter.before.assert_called_once_with("daydream", BODY, STATE, str(path),
                                          private_canvas=False, verified_source_study=False)
    adapter.after.assert_called_once_with("daydream", BODY, str(path))
    rows = journal_rows(adapter)
    assert len(rows) == 1 and rows[0]["content"] == BODY and rows[0]["entry_type"] == "daydream"
    assert rows[0]["file_path"] == str(path)
    assert "publication_id" not in rows[0]
    adapter.post.assert_not_called()


def parent_header_expression(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    source = subprocess.run(["git", "show", f"{PARENT_REVISION}:minime_autonomy/runtime.py"],
                            cwd=repository, check=True, capture_output=True, text=True).stdout
    tree = ast.parse(source)
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AutonomousAgent")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_run_shared_source_study")
    expression = next(node.value for node in ast.walk(method) if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "record_text" for target in node.targets))
    assert isinstance(expression, ast.JoinedStr)
    assert all(isinstance(node, (ast.JoinedStr, ast.Constant, ast.FormattedValue, ast.Name, ast.Load))
               for node in ast.walk(expression))
    # Only the pure formatting expression is materialized, never parent runtime imports or effects.
    extracted = tmp_path / "parent_reflection_header.py"
    extracted.write_text(ast.unparse(expression) + "\n")
    return compile(extracted.read_text(), str(extracted), "eval")


def test_parent_candidate_public_bytes_and_native_request_evidence_match(adapter, tmp_path):
    parent = parent_header_expression(tmp_path)
    run_reflection(adapter)
    path, _ = assert_published_and_indexed(adapter)
    native = json.loads(next(iter(evidence_snapshot(adapter.client).values())))
    scope = native["output"].get("evidence_scope") or "Older retained input; consult the exact offered input."
    golden = eval(parent, {"__builtins__": {}}, {
        "heading": "INTROSPECTION", "source": "open reflection",
        "revision": "not applicable; no source or measurements supplied", "scope": scope,
        "status": "verified input delivery; response claims and understanding not verified", "response": BODY,
    })
    assert path.read_bytes() == golden.encode("utf-8")
    assert native["request_json"].encode("utf-8") == adapter.post.call_args.kwargs["data"]
    assert adapter.post.call_args.kwargs["headers"] == {"Content-Type": "application/json"}
    assert json.loads(native["response_json"])["message"]["content"] == BODY
    assert adapter.agent._pending_next_action == "INTROSPECT"


@pytest.mark.parametrize("inspect_database", [False, True])
def test_cli_preview_is_content_free_and_read_only_by_default(adapter, monkeypatch, capsys, inspect_database):
    with injected_fault(adapter, monkeypatch, "file-before"):
        run_reflection(adapter)
    arguments = ["reconcile_reflection", "--workspace", str(adapter.client.workspace), "--action-id", ACTION]
    if inspect_database:
        arguments += ["--database", str(adapter.database)]
    monkeypatch.setattr(sys, "argv", arguments)
    before = snapshot(adapter.client.workspace), adapter.database.read_bytes()
    unchanged_calls = forbid_replay(adapter)
    capsys.readouterr()
    assert cli.main() == 0
    output = capsys.readouterr()
    status = json.loads(output.out)
    assert status["applied"] is False and status["publication"] == "prepared"
    assert status["choice_scope"] == CHOICE_SCOPE
    assert status["indexing"] == ("pending" if inspect_database else "unknown")
    assert not output.err and BODY not in output.out and "NEXT:" not in output.out
    assert (snapshot(adapter.client.workspace), adapter.database.read_bytes()) == before
    assert unchanged_calls()


@pytest.mark.parametrize("selection", ["no-database", "wrong-database", "no-action"])
def test_cli_apply_rejects_missing_or_conflicting_authority(adapter, monkeypatch, capsys, selection):
    with injected_fault(adapter, monkeypatch, "file-before"):
        run_reflection(adapter)
    arguments = ["reconcile_reflection", "--workspace", str(adapter.client.workspace), "--apply"]
    if selection != "no-action":
        arguments += ["--action-id", ACTION]
    if selection != "no-database":
        selected = adapter.database.with_name("unrelated.sqlite3") if selection == "wrong-database" else adapter.database
        arguments += ["--database", str(selected)]
    monkeypatch.setattr(sys, "argv", arguments)
    before = snapshot(adapter.client.workspace), adapter.database.read_bytes()
    unchanged_calls = forbid_replay(adapter)
    capsys.readouterr()
    if selection == "wrong-database":
        assert cli.main() == 1
        status = json.loads(capsys.readouterr().out)
        assert status["applied"] is False and status["reason"] == "invalid_or_unavailable_evidence"
        assert not selected.exists()
    else:
        with pytest.raises(SystemExit) as failure:
            cli.main()
        assert failure.value.code == 2
    assert (snapshot(adapter.client.workspace), adapter.database.read_bytes()) == before
    assert unchanged_calls()


def test_cli_explicit_apply_recovers_once_without_queue_or_private_changes(adapter, monkeypatch, capsys):
    with injected_fault(adapter, monkeypatch, "file-before"):
        run_reflection(adapter)
    select_later_queue(adapter, "REST")
    private, job = seed_protected_history(adapter)
    before = queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)
    unchanged_calls = forbid_replay(adapter)
    monkeypatch.setattr(sys, "argv", ["reconcile_reflection", "--workspace", str(adapter.client.workspace),
                        "--action-id", ACTION, "--database", str(adapter.database), "--apply"])
    capsys.readouterr()
    identities = []
    for _ in range(2):
        assert cli.main() == 0
        output = capsys.readouterr()
        status = json.loads(output.out)
        assert status["applied"] is True and status["publication"] == "published" and status["indexing"] == "indexed"
        assert status["choice"] == "recorded" and status["choice_scope"] == CHOICE_SCOPE
        assert BODY not in output.out and "NEXT:" not in output.out
        identities.append(status["publication_id"])
        assert_published_and_indexed(adapter)
    assert identities[0] == identities[1]
    assert unchanged_calls()
    assert (queue_snapshot(adapter), snapshot(private), job.read_bytes(), evidence_snapshot(adapter.client)) == before
