"""Tests for DECOMPOSE formatting helpers."""

import unittest

from decompose_utils import format_decompose_mode_sections


class TestDecomposeModeSections(unittest.TestCase):
    def test_active_modes_are_split_from_tail(self):
        active, tail, summary = format_decompose_mode_sections(
            [8.0, 2.0, 1.0],
            active_mode_count=2,
            active_mode_energy_ratio=10.0 / 11.0,
        )

        self.assertIn("λ1 = 8.00", active)
        self.assertIn("λ2 = 2.00", active)
        self.assertIn("λ3 = 1.00", tail)
        self.assertIn("λ1-λ2", summary)
        self.assertIn("91%", summary)


if __name__ == "__main__":
    unittest.main()
