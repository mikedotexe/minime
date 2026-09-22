"""Synthetic private drafts never enter general journal or diagnostic recall."""
import sqlite3
from unittest.mock import Mock

import pytest
import autonomous_agent as aa


@pytest.mark.parametrize("kind", ["private_writing", "private_writing_notice"])
def test_private_artifact_keeps_prose_out_of_public_hooks(tmp_path, monkeypatch, kind):
    agent = object.__new__(aa.AutonomousAgent)
    text = "Exact synthetic private passage ai_2026-09-21_fixture.\nNEXT: WRITE CONTINUE"
    path = tmp_path / "draft.txt"
    path.write_text(text)
    forbidden = Mock(side_effect=AssertionError("private draft reached public hook"))
    for name in ("_afterimage_store", "_register_pressure_vocabulary_fatigue_if_needed",
                 "_register_agency_vernacular_notice_if_needed",
                 "_register_afterimage_absence_notice_if_needed",
                 "_register_internal_topology_fatigue_if_needed",
                 "_maybe_compress_journal_entry"):
        monkeypatch.setattr(agent, name, forbidden)
    link = Mock()
    monkeypatch.setattr(aa.generation_record, "link_artifact", link)
    with sqlite3.connect(aa.DB_PATH) as db:
        db.execute("CREATE TABLE sovereignty_journal (entry_type, content, timestamp)")
    agent._write_journal_entry(kind, text, {}, str(path), private_canvas=True)
    forbidden.assert_not_called()
    assert path.read_text() == text
    with sqlite3.connect(aa.DB_PATH) as db:
        assert db.execute("SELECT COUNT(*) FROM sovereignty_journal").fetchone()[0] == 0
    assert link.call_args.kwargs["visibility"] == "protected"
    assert "content" not in link.call_args.kwargs
    assert text not in str(link.call_args)


def test_legacy_private_rows_are_retained_but_not_ambient_context():
    agent = object.__new__(aa.AutonomousAgent)
    with sqlite3.connect(aa.DB_PATH) as db:
        db.execute("CREATE TABLE sovereignty_journal (entry_type, content, timestamp)")
        db.executemany("INSERT INTO sovereignty_journal VALUES (?, ?, ?)", [
            ("reflection", "Public synthetic reflection", 1),
            ("private_writing", "Private synthetic draft", 2),
            ("private_writing_notice", "Private synthetic notice", 3),
        ])
    assert agent._last_journal_entry() == "Public synthetic reflection"
    with sqlite3.connect(aa.DB_PATH) as db:
        assert db.execute("SELECT COUNT(*) FROM sovereignty_journal").fetchone()[0] == 3
