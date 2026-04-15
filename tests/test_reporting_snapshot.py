"""Tests for provenance-aware reporting snapshots."""

import json
import tempfile
import unittest
from pathlib import Path

from reporting_snapshot import (
    capture_report_snapshot,
    format_snapshot_summary,
    normalize_spectral_state,
    resolve_runtime_db_path,
)


class TestReportingSnapshot(unittest.TestCase):
    def test_root_db_path_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            root_db = base_dir / "minime_consciousness.db"
            legacy_dir = base_dir / "minime"
            legacy_dir.mkdir()
            legacy_db = legacy_dir / "minime_consciousness.db"
            root_db.write_text("")
            legacy_db.write_text("")
            self.assertEqual(resolve_runtime_db_path(base_dir), root_db)

    def test_spectral_state_normalizes_fill_and_eig1(self):
        normalized = normalize_spectral_state({
            "fill_pct": 84.1,
            "eigenvalues": [102.0, 12.0],
        })
        self.assertAlmostEqual(normalized["fill_ratio"], 0.841)
        self.assertEqual(normalized["eig1"], 102.0)

    def test_capture_snapshot_flags_mismatched_live_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            workspace_dir = base_dir / "workspace"
            workspace_dir.mkdir()
            (workspace_dir / "health.json").write_text(json.dumps({
                "provenance": {
                    "session_id": 99,
                    "engine_t_s": 120.0,
                    "snapshot_sequence": 4,
                    "target_provenance": "adaptive",
                    "sovereignty_inputs": {},
                },
                "pi": {"target_fill": 61.0},
            }))
            (workspace_dir / "spectral_state.json").write_text(json.dumps({
                "provenance": {
                    "session_id": 12,
                    "engine_t_s": 125.5,
                    "snapshot_sequence": 5,
                    "target_provenance": "adaptive",
                    "sovereignty_inputs": {},
                },
                "fill_pct": 84.1,
                "eigenvalues": [102.0, 12.0],
            }))

            snapshot = capture_report_snapshot(
                state={"timestamp": 120.0, "fill_ratio": 0.84, "eig1": 24.0},
                session_id=12,
                base_dir=base_dir,
                workspace_dir=workspace_dir,
            )

            self.assertFalse(snapshot.health.valid_for_state)
            self.assertFalse(snapshot.spectral.valid_for_state)
            self.assertIn("session mismatch", " ".join(snapshot.health.issues))
            self.assertIn("later than DB state", " ".join(snapshot.spectral.issues))

    def test_snapshot_summary_mentions_guard_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            workspace_dir = base_dir / "workspace"
            workspace_dir.mkdir()
            (workspace_dir / "health.json").write_text(json.dumps({
                "provenance": {
                    "session_id": 12,
                    "engine_t_s": 120.2,
                    "snapshot_sequence": 4,
                    "target_provenance": "adaptive",
                    "sovereignty_inputs": {},
                },
                "pi": {"target_fill": 61.0},
            }))
            (workspace_dir / "spectral_state.json").write_text(json.dumps({
                "fill_pct": 84.1,
                "eigenvalues": [102.0, 12.0],
            }))

            snapshot = capture_report_snapshot(
                state={"timestamp": 120.0, "fill_ratio": 0.84, "eig1": 24.0},
                session_id=12,
                base_dir=base_dir,
                workspace_dir=workspace_dir,
            )

            summary = format_snapshot_summary(snapshot)
            self.assertIn("guard=", summary)
            self.assertIn("spectral_state.json", summary)


if __name__ == "__main__":
    unittest.main()
