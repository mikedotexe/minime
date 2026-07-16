"""Tests for the machine-readable threshold map."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestThresholdMap(unittest.TestCase):
    @staticmethod
    def _surfaces():
        payload = json.loads((ROOT / "docs" / "threshold_surfaces.json").read_text())
        return {entry["surface"]: entry for entry in payload["authoritative_surfaces"]}

    def test_engine_thresholds_match_rust_constants(self):
        text = (
            ROOT / "minime" / "src" / "runtime" / "semantic_modality.rs"
        ).read_text()
        warning = re.search(r"const CRISIS_WARNING_THRESHOLD: f32 = ([0-9.]+);", text)
        crisis = re.search(r"const CRISIS_FILL_THRESHOLD: f32 = ([0-9.]+);", text)
        self.assertIsNotNone(warning)
        self.assertIsNotNone(crisis)

        surfaces = self._surfaces()
        self.assertEqual(float(warning.group(1)), surfaces["engine_warning_fill"]["value_pct"])
        self.assertEqual(float(crisis.group(1)), surfaces["engine_crisis_fill"]["value_pct"])

    def test_monitor_consumes_threshold_map(self):
        text = (ROOT / "monitor_unified.py").read_text()
        self.assertIn("threshold_surfaces.json", text)
        self.assertIn("self.fill_warning_band", text)
        self.assertNotIn("(70.0, 90.0)", text)

    def test_agent_threshold_entries_match_python_thresholds(self):
        from thresholds import FOCUSED, RECESS

        surfaces = self._surfaces()
        self.assertEqual(RECESS.high_fill * 100.0, surfaces["agent_recess_high_fill"]["value_pct"])
        self.assertEqual(
            RECESS.critical_fill * 100.0,
            surfaces["agent_recess_critical_fill"]["value_pct"],
        )
        self.assertEqual(
            FOCUSED.high_fill * 100.0,
            surfaces["agent_focused_high_fill"]["value_pct"],
        )
        self.assertEqual(
            FOCUSED.critical_fill * 100.0,
            surfaces["agent_focused_critical_fill"]["value_pct"],
        )


if __name__ == "__main__":
    unittest.main()
