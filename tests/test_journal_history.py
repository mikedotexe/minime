"""Recent journal selection must preserve original SQL rows and read-only behavior."""

import importlib.util
from pathlib import Path
import sqlite3
import unittest


SPEC = importlib.util.spec_from_file_location("isolated_journal_history", Path(__file__).resolve().parents[1] / "minime_autonomy" / "journal_history.py")
history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history)


class TestJournalHistory(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
            CREATE TABLE sovereignty_journal(id INTEGER PRIMARY KEY, entry_type TEXT, content TEXT, timestamp REAL);
            CREATE INDEX idx_journal_type ON sovereignty_journal(entry_type);
            CREATE INDEX idx_journal_time ON sovereignty_journal(timestamp);
        """)

    def populate(self, count=1000):
        self.connection.executemany("INSERT INTO sovereignty_journal VALUES(?,?,?,?)",
                                    ((i, "notice" if i % 2 else "daydream", f"synthetic {i}", float(i)) for i in range(count)))

    def original(self, types, limit):
        ordered = sorted(types)
        return self.connection.execute("SELECT entry_type, content FROM sovereignty_journal WHERE entry_type IN (" +
                                       ",".join("?" for _ in ordered) + ") ORDER BY timestamp DESC LIMIT ?", (*ordered, limit)).fetchall()

    def compare(self, types=("notice", "daydream"), limit=11):
        expected = self.original(types, limit)
        before_changes = self.connection.total_changes
        before_schema = self.connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
        statements = []
        self.connection.set_trace_callback(statements.append)
        try:
            actual = history.recent_reflective_rows(self.connection, types, limit)
        finally:
            self.connection.set_trace_callback(None)
        self.assertEqual(actual, expected)
        self.assertEqual(self.connection.total_changes, before_changes)
        self.assertEqual(self.connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall(), before_schema)
        return statements

    def test_common_recent_window_uses_bounded_probe_without_history_sort(self):
        self.populate()
        statements = self.compare()
        self.assertTrue(any("INDEXED BY idx_journal_time" in sql and "LIMIT 64" in sql for sql in statements))
        self.assertFalse(any("WHERE entry_type IN" in sql for sql in statements))

    def test_sparse_matches_fall_back_after_bounded_probe(self):
        self.populate()
        self.connection.execute("UPDATE sovereignty_journal SET entry_type='rare' WHERE id < 3")
        statements = self.compare(("rare",))
        self.assertTrue(any("INDEXED BY idx_journal_time" in sql and "LIMIT 64" in sql for sql in statements))
        self.assertTrue(any("WHERE entry_type IN" in sql for sql in statements))

    def test_timestamp_ties_preserve_original_selection_and_order(self):
        self.populate()
        self.connection.execute("UPDATE sovereignty_journal SET timestamp=1001 WHERE id > 980")
        statements = self.compare()
        self.assertTrue(any("WHERE entry_type IN" in sql for sql in statements))

    def test_tie_at_probe_boundary_cannot_hide_additional_matching_rows(self):
        self.populate(200)
        self.connection.execute("UPDATE sovereignty_journal SET timestamp=0, entry_type='other'")
        self.connection.execute("UPDATE sovereignty_journal SET timestamp=100+id, entry_type='notice' WHERE id < 10")
        self.connection.execute("UPDATE sovereignty_journal SET timestamp=50, entry_type='notice' WHERE id IN (20,90,170)")
        self.connection.execute("UPDATE sovereignty_journal SET timestamp=50 WHERE id BETWEEN 10 AND 199")
        statements = self.compare(("notice",))
        self.assertTrue(any("WHERE entry_type IN" in sql for sql in statements))

    def test_missing_or_incompatible_time_index_uses_original_query(self):
        self.populate()
        self.connection.execute("DROP INDEX idx_journal_time")
        for replacement in (None, "CREATE INDEX idx_journal_time ON sovereignty_journal(content)",
                            "CREATE INDEX idx_journal_time ON sovereignty_journal(timestamp) WHERE entry_type='notice'"):
            if replacement:
                self.connection.execute(replacement)
            statements = self.compare()
            self.assertFalse(any("INDEXED BY" in sql for sql in statements))
            self.assertTrue(any("WHERE entry_type IN" in sql for sql in statements))
            if replacement:
                self.connection.execute("DROP INDEX idx_journal_time")

    def test_empty_short_and_unbounded_results_preserve_behavior(self):
        self.compare()
        self.populate(5)
        for limit in (0, 1, 11, -1, 256):
            with self.subTest(limit=limit):
                self.compare(limit=limit)

    def test_legacy_nonnumeric_timestamp_falls_back_without_error(self):
        self.populate()
        self.connection.execute("UPDATE sovereignty_journal SET timestamp='legacy' WHERE id=999")
        statements = self.compare()
        self.assertTrue(any("WHERE entry_type IN" in sql for sql in statements))

    def test_concurrent_index_removal_falls_back_to_original_sql(self):
        self.populate()
        expected = self.original(("notice", "daydream"), 11)
        connection = self.connection

        class DropBeforeProbe:
            def execute(self, sql, *args):
                if "INDEXED BY" in sql:
                    connection.execute("DROP INDEX idx_journal_time")
                return connection.execute(sql, *args)

        actual = history.recent_reflective_rows(DropBeforeProbe(), ("notice", "daydream"), 11)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
