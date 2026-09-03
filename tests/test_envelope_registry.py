import json
import struct
import tempfile
import unittest
from pathlib import Path

from minime_autonomy.envelope_registry import (
    DEFAULT_REGISTRY_PATH,
    channel_range_for,
    envelope_for,
    load_registry,
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


class EnvelopeRegistryLoaderTests(unittest.TestCase):
    def test_live_registry_loads_and_covers_exploration_noise(self) -> None:
        registry = load_registry()
        self.assertIsNotNone(registry, "canonical registry should be installed (C1)")
        bounds = envelope_for("exploration_noise", registry)
        self.assertEqual(bounds, (_f32(0.0), _f32(0.2)))
        footer = channel_range_for("exploration_noise", "footer", registry)
        self.assertEqual(footer, (_f32(0.0), _f32(0.08)))
        sovereignty = channel_range_for("exploration_noise", "sovereignty", registry)
        self.assertEqual(sovereignty, (_f32(0.0), _f32(0.15)))

    def test_fails_closed_on_absence_and_malformation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            self.assertIsNone(load_registry(missing))
            self.assertIsNone(envelope_for("exploration_noise", path=missing))
            bad = Path(tmp) / "bad.json"
            bad.write_text("{ not json")
            self.assertIsNone(load_registry(bad))
            wrong_being = Path(tmp) / "wrong.json"
            wrong_being.write_text(json.dumps({**_registry({}), "being": "astrid"}))
            self.assertIsNone(load_registry(wrong_being))

    def test_refuses_entry_wider_than_engine_backstop(self) -> None:
        registry = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.5,
                    "engine_backstop": {"floor": 0.0, "ceiling": _f32(0.2)},
                }
            }
        )
        self.assertIsNone(envelope_for("exploration_noise", registry))

    def test_uncovered_field_returns_none_for_compiled_fallback(self) -> None:
        registry = _registry({})
        self.assertIsNone(envelope_for("synth_gain", registry))

    def test_half_specified_backstop_refuses_without_raising(self) -> None:
        # {"ceiling": only} used to raise KeyError from a loader whose
        # contract is fail-closed-to-None (adversarial review 2026-09-02).
        for backstop in (
            {"ceiling": 0.2},
            {"floor": 0.0},
            {"floor": None, "ceiling": 0.2},
            {},
        ):
            registry = _registry(
                {"exploration_noise": {"floor": 0.0, "ceiling": 0.15, "engine_backstop": backstop}}
            )
            self.assertIsNone(envelope_for("exploration_noise", registry), backstop)

    def test_passthrough_backstop_marker_passes(self) -> None:
        registry = _registry(
            {
                "mode_disperse_duration_ticks": {
                    "floor": 1.0,
                    "ceiling": 64.0,
                    "engine_backstop": {"passthrough_unclamped": True},
                }
            }
        )
        self.assertEqual(
            envelope_for("mode_disperse_duration_ticks", registry), (1.0, 64.0)
        )

    def test_refuses_non_finite_and_inverted_bounds(self) -> None:
        # Python's json accepts NaN/Infinity literals (serde_json refuses
        # them), and NaN defeats every comparison-based guard — the Rust
        # twins refuse these shapes, and so must this loader.
        nan_entry = json.loads(
            '{"exploration_noise": {"floor": 0.0, "ceiling": NaN,'
            ' "engine_backstop": {"floor": 0.0, "ceiling": 0.2}}}'
        )
        self.assertIsNone(envelope_for("exploration_noise", _registry(nan_entry)))
        inf_entry = json.loads('{"exploration_noise": {"floor": 0.0, "ceiling": Infinity}}')
        self.assertIsNone(envelope_for("exploration_noise", _registry(inf_entry)))
        nan_backstop = json.loads(
            '{"exploration_noise": {"floor": 0.0, "ceiling": 0.15,'
            ' "engine_backstop": {"floor": 0.0, "ceiling": NaN}}}'
        )
        self.assertIsNone(envelope_for("exploration_noise", _registry(nan_backstop)))
        inverted = _registry({"fill_target": {"floor": 0.75, "ceiling": 0.25}})
        self.assertIsNone(envelope_for("fill_target", inverted))
        inverted_channel = _registry(
            {
                "exploration_noise": {
                    "floor": 0.0,
                    "ceiling": 0.2,
                    "channel_ranges": {"footer": {"floor": 0.1, "ceiling": 0.05}},
                }
            }
        )
        self.assertIsNone(channel_range_for("exploration_noise", "footer", inverted_channel))

    def test_default_path_is_the_canonical_location(self) -> None:
        self.assertTrue(str(DEFAULT_REGISTRY_PATH).endswith("workspace/self_regulation/envelope_registry.json"))


if __name__ == "__main__":
    unittest.main()
