"""Historical journal identity, kept outside the existing excerpt budget."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class JournalRecall:
    database: str
    row_id: int
    recorded_at: float | None
    entry_type: str | None
    file_path: str | None
    content: str

    def excerpt(self) -> str:
        """Preserve the legacy 400-character selection before whitespace folding."""
        text = self.content.strip()
        return text[:400] + "..." if len(text) > 400 else text

    def metadata(self) -> dict:
        return {
            "schema": "journal_recall_v1",
            "database": self.database,
            "table": "sovereignty_journal",
            "row_id": self.row_id,
            "recorded_at_unix_s": self.recorded_at,
            "entry_type": self.entry_type,
            "file_path_as_recorded": self.file_path,
            "content_sha256": hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
            "excerpt_truncated": len(self.content.strip()) > 400,
            "measurement_source": None,
            "measurement_capture_time": None,
        }


def latest_journal_recall(database: Path) -> JournalRecall | None:
    """Read the same six-row window without opening files named by those rows.

    Private drafts remain excluded. The path is a stored reference, not proof
    that an artifact exists or matches the recalled database content.
    """
    database = Path(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sovereignty_journal)")}
        source = "file_path" if "file_path" in columns else "NULL"
        rows = conn.execute(
            f"SELECT rowid, timestamp, entry_type, content, {source} FROM sovereignty_journal "
            "WHERE entry_type NOT IN ('private_writing', 'private_writing_notice') "
            "ORDER BY timestamp DESC LIMIT 6"
        ).fetchall()
    for row_id, recorded, kind, content, file_path in rows:
        if not isinstance(content, str) or not content:
            continue
        if content.strip().startswith(("[Similarity gate]", "## Ongoing issue")):
            continue
        valid_clock = (isinstance(recorded, (int, float)) and not isinstance(recorded, bool)
                       and math.isfinite(recorded) and recorded >= 0)
        return JournalRecall(
            database=database.name, row_id=row_id,
            recorded_at=recorded if valid_clock else None,
            entry_type=kind if isinstance(kind, str) and kind else None,
            file_path=file_path if isinstance(file_path, str) and file_path else None,
            content=content,
        )
    return None


def render_journal_recall(recall: JournalRecall | None) -> str:
    prefix = "Optional own-journal context (historical; legacy system annotations may be present):\n"
    if recall is None:
        return prefix + "(no recent own-journal excerpt available)"
    return (
        prefix + "Provenance: " + json.dumps(recall.metadata(), ensure_ascii=False, sort_keys=True)
        + "\nThis is prior journal text. Null metadata is unavailable. Recording time is not "
        "measurement capture time; original measurement source/time are unavailable in this "
        "recall's metadata. The recorded file path has not been checked."
        + "\nExcerpt:\n" + " ".join(recall.excerpt().split()) + "\nEnd historical excerpt."
    )
