"""Footer-directive un-muffle guard.

minime sometimes states a sovereignty-dial intent as a trailing structured
footer (`exploration_noise=0.12`) instead of the strict JSON params block the
sovereignty reflection consumes. That footer form had no listener, so the intent
silently dropped (the same class as the scar near line 23315, "dropped ~6 days of
minime's REGIME breathe requests"). `_parse_footer_directives` gives the footer
form a listener — conservatively (isolated trailing KEY=value lines only; a prose
mention never matches; bounds mirror minime's lease-safe self-regulation ranges; regime + PI gains excluded).
These pin that behavior.
"""
import json
import os
import tempfile
import types
import unittest

import autonomous_agent as aa


class FooterDirectivePersistTests(unittest.TestCase):
    """Continuity un-muffle (2026-06-13): a footer-stated dial reaches the live
    engine but must ALSO persist, or it reverts to the last JSON-arm snapshot on
    restart. _persist_footer_sovereignty_dials is a targeted read-modify-write that
    updates only the dial key(s) and must never wipe the other persisted dials or
    the non-dial continuity keys (session_id, pending_next_action, cycle_count)."""

    def _fake(self, path):
        return types.SimpleNamespace(
            _sovereignty_state_path=lambda: path,
            _ACCEPTABLE_PARAMS=aa.AutonomousAgent._ACCEPTABLE_PARAMS,
            _persist_footer_sovereignty_dials=aa.AutonomousAgent._persist_footer_sovereignty_dials,
        )

    def test_persist_updates_only_named_dial_preserving_rest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sovereignty_state.json")
            with open(path, "w") as f:
                json.dump({
                    "regulation_strength": 0.7,
                    "exploration_noise": 0.12,
                    "geom_curiosity": 0.15,
                    "session_id": 5260,
                    "pending_next_action": "REST",
                    "cycle_count": 1958,
                }, f)
            fake = self._fake(path)
            fake._persist_footer_sovereignty_dials(fake, {"geom_curiosity": 0.1})
            with open(path) as f:
                out = json.load(f)
            # the stated dial is now persisted...
            self.assertEqual(out["geom_curiosity"], 0.1)
            # ...and every other dial + continuity key is untouched.
            self.assertEqual(out["regulation_strength"], 0.7)
            self.assertEqual(out["exploration_noise"], 0.12)
            self.assertEqual(out["session_id"], 5260)
            self.assertEqual(out["pending_next_action"], "REST")
            self.assertEqual(out["cycle_count"], 1958)

    def test_persist_no_file_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sovereignty_state.json")
            fake = self._fake(path)
            fake._persist_footer_sovereignty_dials(fake, {"exploration_noise": 0.1})
            with open(path) as f:
                out = json.load(f)
            self.assertEqual(out["exploration_noise"], 0.1)

    def test_persist_ignores_non_sovereignty_dials(self) -> None:
        # PI gains aren't footer-applied; if one slipped through it must not persist.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sovereignty_state.json")
            with open(path, "w") as f:
                json.dump({"geom_curiosity": 0.15}, f)
            fake = self._fake(path)
            fake._persist_footer_sovereignty_dials(fake, {"pi_kp": 1.2})
            with open(path) as f:
                out = json.load(f)
            self.assertNotIn("pi_kp", out)
            self.assertEqual(out["geom_curiosity"], 0.15)


class FooterDirectiveTests(unittest.TestCase):
    def test_parses_the_real_failing_footer(self) -> None:
        # The exact footer shape from reply_2026-06-11T11-53-00 that dropped.
        reply = (
            "...navigating this denser terrain. The grit is a property of the depth.\n\n"
            "REGIME: breathe\n"
            "exploration_noise=0.12\n"
        )
        # exploration_noise recognized, then clamped to the 0.08 lease-safe cap
        # (requested 0.12 preserved in self_regulation/negotiations.jsonl);
        # regime excluded by design (stays gated).
        self.assertEqual(aa._parse_footer_directives(reply), {"exploration_noise": 0.08})

    def test_colon_and_equals_both_work(self) -> None:
        self.assertEqual(
            aa._parse_footer_directives("regulation_strength: 0.8"),
            {"regulation_strength": 0.8},
        )
        self.assertEqual(
            aa._parse_footer_directives("geom_curiosity=0.2"),
            {"geom_curiosity": 0.2},
        )

    def test_prose_mention_never_matches(self) -> None:
        prose = (
            "I worry about exploration_noise being too low right now.\n"
            "Setting exploration_noise to 0.12 would help, I think.\n"
        )
        self.assertEqual(aa._parse_footer_directives(prose), {})

    def test_value_with_trailing_prose_is_rejected(self) -> None:
        self.assertEqual(
            aa._parse_footer_directives("exploration_noise=0.12 because I feel stuck"),
            {},
        )

    def test_out_of_range_is_clamped_to_json_arm_bounds(self) -> None:
        self.assertEqual(
            aa._parse_footer_directives("exploration_noise=0.99"),
            {"exploration_noise": 0.08},
        )
        self.assertEqual(
            aa._parse_footer_directives("regulation_strength=-2"),
            {"regulation_strength": 0.4},
        )

    def test_unknown_or_stability_key_is_ignored(self) -> None:
        # synth_gain/keep_floor aren't footer-settable; pi gains stay gated.
        self.assertEqual(aa._parse_footer_directives("synth_gain=0.5"), {})
        self.assertEqual(aa._parse_footer_directives("pi_kp=1.2"), {})

    def test_regime_footer_is_not_applied(self) -> None:
        # regime stays gated to the sovereignty reflection; guard-probe catches it.
        self.assertEqual(aa._parse_footer_directives("REGIME: breathe"), {})

    def test_only_trailing_lines_are_scanned(self) -> None:
        filler = "\n".join(f"reflective line {i}" for i in range(20))
        # directive at the very end → it IS the footer.
        self.assertEqual(
            aa._parse_footer_directives(filler + "\nexploration_noise=0.12"),
            {"exploration_noise": 0.08},
        )
        # directive at the top, buried far above the tail → not a footer.
        self.assertEqual(
            aa._parse_footer_directives("exploration_noise=0.12\n" + filler),
            {},
        )

    def test_empty_and_none_safe(self) -> None:
        self.assertEqual(aa._parse_footer_directives(""), {})
        self.assertEqual(aa._parse_footer_directives(None), {})

    def test_case_insensitive_key(self) -> None:
        self.assertEqual(
            aa._parse_footer_directives("EXPLORATION_NOISE = 0.10"),
            {"exploration_noise": 0.08},
        )


if __name__ == "__main__":
    unittest.main()
