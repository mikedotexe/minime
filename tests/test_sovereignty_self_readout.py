"""Tests for minime's self-transparency dial readout (being-facing transparency item c).

She is shown her CURRENT sovereign dial values (not just the defaults the
sovereignty-reflection prompt describes), read live from sovereignty_state.json so
she can see what she actually has them set to before she tunes.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autonomous_agent as aa


class CurrentDialsReadoutTests(unittest.TestCase):
    def test_full_state_shows_current_values(self):
        block = aa._format_current_dials_block(
            {
                "regulation_strength": 0.7,
                "exploration_noise": 0.12,
                "geom_curiosity": 0.15,
                "regime": "breathe",
                "pi_kp": 0.85,
                "pi_ki": 0.14,
                "pi_max_step": 0.08,
            }
        )
        self.assertIn("YOUR CURRENT DIALS", block)
        self.assertIn("regulation_strength: 0.7", block)
        self.assertIn("exploration_noise: 0.12", block)
        self.assertIn("geom_curiosity: 0.15", block)
        self.assertIn("regime: breathe", block)
        self.assertIn("kp=0.85", block)
        self.assertIn("max_step=0.08", block)

    def test_empty_state_is_blank(self):
        self.assertEqual(aa._format_current_dials_block({}), "")

    def test_missing_keys_render_as_default(self):
        block = aa._format_current_dials_block({"regime": "focus"})
        # the dials she hasn't set fall back to a clear "default" marker, not a crash
        self.assertIn("regulation_strength: default", block)
        self.assertIn("exploration_noise: default", block)
        self.assertIn("geom_curiosity: default", block)
        self.assertIn("regime: focus", block)
        self.assertIn("kp=?", block)
        self.assertIn("ki=?", block)
        self.assertIn("max_step=?", block)


if __name__ == "__main__":
    unittest.main()
