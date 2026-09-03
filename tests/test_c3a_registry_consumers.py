"""Constitution C3a: the V2 validator and footer bounds consult the envelope
registry, with compiled tables as the fail-closed backstop. Today's registry
records compiled values verbatim, so live behavior is byte-identical; these
tests pin the consultation mechanics and the never-wider-than-compiled rule.
"""

import struct
import unittest
from unittest import mock

from minime_autonomy import envelope_registry as er
from minime_autonomy.parsing import _footer_bounds
from minime_autonomy.self_control_v2 import (
    SelfControlV2Error,
    validate_exact_self_control_values,
)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _registry(fields: dict) -> dict:
    return {
        "schema": "being_envelope_registry_v1",
        "being": "minime",
        "revision": 1,
        "fields": fields,
    }


class ValidatorRegistryConsultationTests(unittest.TestCase):
    def test_live_registry_keeps_compiled_behavior_byte_identical(self) -> None:
        # The installed registry records compiled bounds verbatim: the same
        # values pass/fail as before C3a.
        cleaned = validate_exact_self_control_values({"exploration_noise": 0.15})
        self.assertIn("exploration_noise", cleaned)
        with self.assertRaises(SelfControlV2Error):
            validate_exact_self_control_values({"exploration_noise": 0.25})

    def test_narrowed_registry_envelope_rejects_within_compiled(self) -> None:
        narrowed = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.1,
                    "engine_backstop": {"floor": 0.0, "ceiling": 0.2},
                }
            }
        )
        with mock.patch.object(er, "load_registry", return_value=narrowed):
            with self.assertRaises(SelfControlV2Error):
                validate_exact_self_control_values({"exploration_noise": 0.18})
            cleaned = validate_exact_self_control_values({"exploration_noise": 0.05})
            self.assertIn("exploration_noise", cleaned)

    def test_registry_can_never_widen_past_compiled(self) -> None:
        # A (hypothetical) registry wider than the compiled python table is
        # intersected down: compiled remains the outermost python backstop
        # until C3c closes the engine-side gaps.
        widened = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.5,
                    # No engine_backstop recorded: the loader has nothing to
                    # refuse against, so the consumer's intersection is the guard.
                }
            }
        )
        with mock.patch.object(er, "load_registry", return_value=widened):
            with self.assertRaises(SelfControlV2Error):
                validate_exact_self_control_values({"exploration_noise": 0.3})

    def test_registry_fault_falls_closed_to_compiled(self) -> None:
        with mock.patch.object(er, "load_registry", side_effect=RuntimeError("boom")):
            cleaned = validate_exact_self_control_values({"exploration_noise": 0.15})
            self.assertIn("exploration_noise", cleaned)


class FooterBoundsRegistryTests(unittest.TestCase):
    def test_live_registry_footer_matches_compiled_today(self) -> None:
        self.assertEqual(_footer_bounds("exploration_noise"), (0.0, _f32(0.08)))
        self.assertEqual(_footer_bounds("regulation_strength"), (_f32(0.4), 1.0))

    def test_granted_channel_widens_by_document_not_code(self) -> None:
        # The C6 shape: a consent-backed grant raises the footer channel in
        # the registry; the code path picks it up with no code change.
        granted = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.15,
                    "engine_backstop": {"floor": 0.0, "ceiling": 0.2},
                    "channel_ranges": {"footer": {"floor": 0.0, "ceiling": 0.15}},
                }
            }
        )
        with mock.patch.object(er, "load_registry", return_value=granted):
            self.assertEqual(_footer_bounds("exploration_noise"), (0.0, _f32(0.15)))

    def test_channel_cannot_reach_past_the_field_envelope(self) -> None:
        overreaching = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.15,
                    "engine_backstop": {"floor": 0.0, "ceiling": 0.2},
                    "channel_ranges": {"footer": {"floor": 0.0, "ceiling": 0.5}},
                }
            }
        )
        with mock.patch.object(er, "load_registry", return_value=overreaching):
            self.assertEqual(_footer_bounds("exploration_noise"), (0.0, _f32(0.15)))

    def test_registry_absent_falls_back_to_compiled(self) -> None:
        with mock.patch.object(er, "load_registry", return_value=None):
            self.assertEqual(_footer_bounds("exploration_noise"), (0.0, 0.08))


if __name__ == "__main__":
    unittest.main()
