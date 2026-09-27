"""Synthetic database identity stays with historical excerpts, without file reads."""
import hashlib
import json
import sqlite3

import pytest
import autonomous_agent as aa
from minime_autonomy.journal_recall import latest_journal_recall, render_journal_recall


def database(path, *, file_column=True):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sovereignty_journal (id INTEGER PRIMARY KEY, timestamp, entry_type, content"
                     + (", file_path" if file_column else "") + ")")


def test_full_row_identity_survives_unicode_excerpt_and_stored_path_is_not_followed(tmp_path):
    path = tmp_path / "history.db"
    database(path)
    body = "  Prior 65.6% / 16.512 interpretation.\n" + "λ thick air. " * 100 + " END_SENTINEL"
    absent = tmp_path / "nonexistent.txt"
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO sovereignty_journal VALUES (7, 1000.25, 'reflection', ?, ?)", (body, str(absent)))
    before = path.read_bytes()
    recall = latest_journal_recall(path)
    text = render_journal_recall(recall)
    meta = recall.metadata()
    assert meta["row_id"] == 7 and meta["recorded_at_unix_s"] == 1000.25
    assert meta["entry_type"] == "reflection" and meta["excerpt_truncated"]
    assert meta["content_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert meta["file_path_as_recorded"] == str(absent)
    assert meta["measurement_source"] is None and meta["measurement_capture_time"] is None
    assert json.dumps(meta, ensure_ascii=False, sort_keys=True) in text
    assert "END_SENTINEL" not in text and "65.6% / 16.512" in text
    assert recall.excerpt() == body.strip()[:400] + "..."
    assert path.read_bytes() == before and not absent.exists()


def test_existing_selection_excludes_private_drafts_and_skips_system_rows(tmp_path):
    path = tmp_path / "history.db"
    database(path, file_column=False)
    rows = [(1, 1, "reflection", "earlier"), (2, 2, "reflection", "selected"),
            (3, 3, "reflection", "[Similarity gate] synthetic"),
            (4, 4, "reflection", "## Ongoing issue synthetic"),
            (5, 5, "reflection", ""), (6, 6, "private_writing", "secret draft"),
            (7, 7, "private_writing_notice", "secret notice")]
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?)", rows)
    recall = latest_journal_recall(path)
    assert recall.row_id == 2 and recall.file_path is None
    assert "secret" not in render_journal_recall(recall)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM sovereignty_journal ORDER BY id").fetchall() == rows
        # Keep the original six eligible-row horizon; do not search farther back.
        conn.executemany("INSERT INTO sovereignty_journal VALUES (?, ?, 'reflection', '[Similarity gate] skip')",
                         [(n, n) for n in range(8, 14)])
    assert latest_journal_recall(path) is None


@pytest.mark.parametrize("recorded", [None, "legacy", -1, float("inf")])
def test_unknown_time_never_borrows_a_body_claim_filename_or_mtime(tmp_path, recorded):
    path = tmp_path / "history.db"
    database(path, file_column=False)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO sovereignty_journal VALUES (1, ?, 'reflection', ?)",
                     (recorded, "Timestamp: 9999\nA prior body with a timestamp claim."))
    meta = latest_journal_recall(path).metadata()
    assert meta["recorded_at_unix_s"] is None
    assert meta["file_path_as_recorded"] is None


def test_missing_database_remains_missing_and_runtime_returns_no_recall(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setattr(aa, "DB_PATH", path)
    agent = object.__new__(aa.AutonomousAgent)
    assert agent._last_journal_recall() is None
    assert agent._last_journal_entry() == ""
    assert not path.exists()
    assert "no recent own-journal excerpt" in render_journal_recall(None)
