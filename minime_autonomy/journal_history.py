"""Read the same recent journal rows without sorting the full common-case history."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable


def recent_reflective_rows(connection: sqlite3.Connection, entry_types: Iterable[str], limit: int) -> list[tuple]:
    """Use a bounded recent probe; ambiguous ties and sparse matches keep old SQL.

    The original query can prefer the entry-type index and sort all matching
    history. The existing timestamp index can answer common recent windows
    cheaply, but forcing a whole-history walk would penalize sparse types and
    could change the original query's unspecified ordering at timestamp ties.
    Only an unambiguous result wholly inside this bounded probe is returned.
    """
    types = sorted(entry_types)
    placeholders = ",".join("?" for _ in types)
    original = (
        "SELECT entry_type, content FROM sovereignty_journal "
        f"WHERE entry_type IN ({placeholders}) ORDER BY timestamp DESC LIMIT ?"
    )
    if 0 < limit < 256:
        indexes = connection.execute("PRAGMA index_list(sovereignty_journal)").fetchall()
        time_index = any(row[1] == "idx_journal_time" and not row[4] for row in indexes)
        index_columns = connection.execute("PRAGMA index_info(idx_journal_time)").fetchall()
        if time_index and [row[2] for row in index_columns] == ["timestamp"]:
            scan_limit = min(256, max(64, limit * 4))
            try:
                rows = connection.execute(
                    "SELECT entry_type, content, timestamp FROM sovereignty_journal "
                    "INDEXED BY idx_journal_time ORDER BY timestamp DESC LIMIT ?",
                    (scan_limit,),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such index" not in str(exc).lower() and "no query solution" not in str(exc).lower():
                    raise
                # The index may have been removed/replaced since the schema
                # probe. The original SQL remains valid without this hint.
                rows = []
            allowed = set(types)
            matches = [row for row in rows if row[0] in allowed]
            if len(matches) >= limit:
                selected = matches[:limit]
                timestamps = [row[2] for row in selected]
                valid = all(isinstance(row[2], (int, float)) and math.isfinite(row[2]) for row in rows)
                # Include the next matching row when checking the cutoff tie.
                unique = len(set(timestamps)) == len(timestamps)
                next_is_older = len(matches) == limit or matches[limit][2] != timestamps[-1]
                complete_boundary = valid and (len(rows) < scan_limit or timestamps[-1] > rows[-1][2])
                if valid and unique and next_is_older and complete_boundary:
                    return [(row[0], row[1]) for row in selected]
    return connection.execute(original, (*types, limit)).fetchall()
