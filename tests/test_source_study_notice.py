"""Research receipts, rather than authored vocabulary, control the notice exemption."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import autonomous_agent as aa


@pytest.mark.parametrize("verified,entry_type,expected_notice", [
    (True, "self_study", False),
    (False, "self_study", True),
    (True, "reflection", True),
])
def test_receipt_gates_agency_hook_and_existing_motif_notice(
    tmp_path, monkeypatch, verified, entry_type, expected_notice,
):
    agent = object.__new__(aa.AutonomousAgent)
    agent.session_id = 1
    content = "The evidence mapping follows a new branch of the source."
    path = tmp_path / "entry.txt"
    path.write_text(content)
    with sqlite3.connect(aa.DB_PATH) as db:
        db.execute("CREATE TABLE sovereignty_journal (session_id, timestamp, entry_type, content, spectral_context, file_path)")
    monkeypatch.setattr(agent, "_afterimage_store", lambda: SimpleNamespace(archive=tmp_path / "archive", private=tmp_path / "private"))
    register = Mock()
    monkeypatch.setattr(agent, "_register_agency_vernacular_notice_if_needed", register)
    for name in ("_register_pressure_vocabulary_fatigue_if_needed", "_register_afterimage_absence_notice_if_needed", "_register_internal_topology_fatigue_if_needed", "_record_condition_metric"):
        monkeypatch.setattr(agent, name, Mock())
    for name in ("_active_pressure_vocabulary_motifs", "_active_afterimage_absence_motifs", "_active_internal_topology_motifs"):
        monkeypatch.setattr(agent, name, lambda: [])
    monkeypatch.setattr(agent, "_active_agency_vernacular_motifs", lambda: [{"label": "agency-vernacular:evidence_mapping"}])
    monkeypatch.setattr(aa.generation_record, "link_artifact", Mock())
    agent._write_journal_entry(entry_type, content, {}, str(path), verified_source_study=verified)
    assert register.called == expected_notice
    # Diagnostics stay separate from authored prose even without a study receipt.
    assert "Agency-vernacular notice" not in path.read_text()
    with sqlite3.connect(aa.DB_PATH) as db:
        stored = db.execute("SELECT content FROM sovereignty_journal").fetchone()[0]
    assert stored == path.read_text()
    if not expected_notice:
        assert stored == content


@pytest.mark.parametrize("kind,receipt,expected", [
    ("source_page", {}, True),
    ("map", {}, True),
    ("search", {}, True),
    ("recovery", {}, True),
    ("source_page", None, False),
    ("private_writing", {}, False),
])
def test_shared_study_passes_only_verified_public_receipt_to_journal(
    tmp_path, monkeypatch, kind, receipt, expected,
):
    agent = object.__new__(aa.AutonomousAgent)
    prompt = SimpleNamespace(output={"input_kind": kind}, receipt=receipt)
    monkeypatch.setattr(aa, "StudyClient", lambda *args: SimpleNamespace(prepare=lambda action, **kwargs: prompt))
    monkeypatch.setattr(agent, "_query_llm_with_next", lambda *args, **kwargs: ("Source mapping remains open.", None))
    monkeypatch.setattr(agent, "_state_for_live_surfaces", lambda state, **kwargs: state)
    monkeypatch.setattr(agent, "_record_current_action_artifact", Mock())
    monkeypatch.setattr(aa.job_outcome, "fail_action", Mock())
    write = Mock()
    monkeypatch.setattr(agent, "_write_journal_entry", write)
    agent._current_action_continuity_event = {"action_id": "synthetic-dispatch-64"}
    agent._run_shared_source_study({}, "SELF_STUDY MAP")
    assert write.call_count == 1
    assert write.call_args.kwargs["verified_source_study"] is expected
    assert write.call_args.kwargs["private_canvas"] == (kind == "private_writing")
