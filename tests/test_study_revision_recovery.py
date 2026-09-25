"""Deployment-shaped recovery through the runtime adapter; no real provider."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import autonomous_agent as aa
from minime_autonomy.source_study import StudyClient


STATE = {"eig1": 4.7, "fill_ratio": .68}
SOURCE = "astrid/crates/example/src/lib.rs"
OPEN = f"SELF_STUDY OPEN {SOURCE} 1"


def test_runtime_delivers_revision_recovery_and_preserves_explicit_next(tmp_path, monkeypatch):
    astrid = tmp_path / "astrid"
    source = tmp_path / SOURCE
    source.parent.mkdir(parents=True)
    source.write_text("pub fn before() {}\n" + "// old source\n" * 1500)
    workspace = tmp_path / "workspace"
    client = StudyClient(tmp_path / "minime", workspace, astrid_root=astrid,
                        executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    monkeypatch.setattr(aa, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    agent = object.__new__(aa.AutonomousAgent)
    agent._record_current_action_artifact = Mock()
    agent._write_journal_entry = Mock()
    agent._state_for_live_surfaces = lambda state, **kw: state
    agent._record_introspect_notice = Mock(side_effect=AssertionError("recovery is offered input, not an exception"))
    offered = []

    def provider(prompt, **kwargs):
        offered.append(prompt)
        assert kwargs["context_mode"] == "source_study"
        response = (f"STUDY_NOTE: Do not silently save this.\nNEXT: {OPEN}"
                    if prompt.output["input_kind"] == "revision_recovery"
                    else "STUDY_NOTE: Original account.\nNEXT: SELF_STUDY CONTINUE")
        messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
        prompt.post(Mock(return_value=Mock(status_code=200, text=json.dumps({
            "message": {"content": response}, "done": True}))),
            "fake", {"messages": messages}, 1)
        prompt.accepted()
        return response, response.rsplit("NEXT: ", 1)[1]

    agent._query_llm_with_next = provider
    reader_state = workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json"

    def run(action, ident):
        agent._current_action_continuity_event = {"action_id": ident}
        agent._current_action_continuity_context = {"source_study_action": action}
        agent._self_study(dict(STATE))

    run(OPEN, "first")
    before = json.loads(reader_state.read_bytes())
    source.write_text("pub fn after() {}\n" + "// new source\n" * 1500)
    run("SELF_STUDY CONTINUE", "recovery")
    recovery = offered[-1]
    assert recovery.output["input_kind"] == "revision_recovery"
    assert recovery.receipt["choice_feedback"]["selected_next"] == OPEN
    after = json.loads(reader_state.read_bytes())
    for key in ("bookmarks", "current", "progress", "notebook", "questions", "last_input"):
        assert after[key] == before[key]
    journals = list((workspace / "journal").glob("self_study_*.txt"))
    assert any("=== STUDY NAVIGATION RESPONSE: source revision recovery ===" in p.read_text() for p in journals)
    assert not list((workspace / "journal").glob("introspect_notice*"))
    run(OPEN, "explicit-reselection")
    assert offered[-1].output["input_kind"] == "source_page"
    assert offered[-1].output["page"]["start"]["byte"] == 0
    run("SELF_STUDY CONTINUE", "resumed")
    assert offered[-1].output["page"]["start"]["byte"] > 0


def test_runtime_failure_is_not_authored_journal_or_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)
    agent = object.__new__(aa.AutonomousAgent)
    agent._current_action_continuity_event = {"action_id": "failed"}
    agent._write_journal_entry = Mock(side_effect=AssertionError("runtime failure is not a journal"))
    agent._format_metrics = Mock(side_effect=AssertionError("no metric wall"))
    agent._state_for_live_surfaces = Mock(side_effect=AssertionError("no implied measurement"))
    agent._record_current_action_artifact = Mock()
    agent._query_llm_with_next = Mock(side_effect=AssertionError("corruption must fail closed"))
    client = Mock()
    client.prepare.side_effect = RuntimeError("source-study state is unreadable; preserved")
    monkeypatch.setattr(aa, "StudyClient", lambda *args: client)
    with aa.job_outcome.capture("failure") as outcome:
        agent._run_shared_source_study(dict(STATE), "SELF_STUDY CONTINUE")
    assert outcome.finish()[0] == "failed"
    assert not (tmp_path / "journal").exists()
    notice = next((tmp_path / "diagnostics/source_study/notices").glob("runtime_notice_*.txt")).read_text()
    assert "runtime diagnostic, not Minime's authored reflection" in notice
    assert "SELF_STUDY CONTINUE to retry" not in notice
    assert "Fill" not in notice and "source-study state is unreadable" in notice
    assert agent._record_current_action_artifact.call_args.kwargs["visibility"] == "protected"
