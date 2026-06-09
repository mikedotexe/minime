from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mikemind.llm_engine import LLMEngine
from mikemind.mind import MikesSpatialMind, SevenStageProcessor


class TestSpectralTransitionContext(unittest.TestCase):
    def test_seven_stage_runtime_growth_replaces_legacy_key(self) -> None:
        source_text = (Path(__file__).resolve().parents[1] / "mikemind" / "mind.py").read_text()

        self.assertIn("'runtime_growth': growth", source_text)
        self.assertIn("runtime_growth: float", source_text)
        self.assertIn("_grow_runtime_uniform", source_text)
        self.assertIn("_grow_runtime_spiral", source_text)
        self.assertNotIn("'consciousness_growth': growth", source_text)
        self.assertNotIn(".consciousness_growth", source_text)
        self.assertNotIn("_grow_consciousness_", source_text)
        self.assertEqual(
            SevenStageProcessor._runtime_growth({"runtime_growth": 0.25}),
            0.25,
        )
        self.assertEqual(
            SevenStageProcessor._runtime_growth({"consciousness_growth": 0.125}),
            0.125,
        )

    def test_minime_context_prefers_enriched_transition_event_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "health.json").write_text(
                json.dumps(
                    {
                        "fill_pct": 67.5,
                        "lambda1_esn": 8.1,
                        "lambda1_rel": 0.91,
                        "geom_rel": 1.02,
                        "semantic": {
                            "admission": "stable_core_semantic_trace_stale",
                            "kernel_energy": 0.0,
                            "input_energy": 0.014,
                            "input_stale_ms": 1200,
                        },
                        "transition_event_v1": {
                            "sequence": 4,
                            "kind": "breathing_phase",
                            "legacy_kind": "phase_transition",
                            "description": "contracting -> expanding",
                            "basin_shift_score": 0.03,
                        },
                    }
                )
            )
            (workspace / "spectral_state.json").write_text(
                json.dumps(
                    {
                        "fill_pct": 68.2,
                        "lambda1": 9.2,
                        "lambda1_rel": 0.94,
                        "geom_rel": 1.04,
                        "transition_event_v1": {
                            "sequence": 4,
                            "kind": "basin_transition",
                            "legacy_kind": "phase_transition",
                            "description": "basin shift candidate",
                            "fill_pct": 68.2,
                            "target_fill_pct": 68.0,
                            "lambda1": 9.2,
                            "lambda1_rel": 0.94,
                            "geom_rel": 1.04,
                            "phase": "expanding",
                            "fill_band": "near",
                            "glimpse_distance": 0.21,
                            "rotation_delta": 0.09,
                            "basin_shift_score": 0.74,
                            "phase_dwell_s": 4.0,
                            "recent_phase_flip_count_30s": 1,
                            "debounced_phase_transition": False,
                        },
                    }
                )
            )

            mind = MikesSpatialMind.__new__(MikesSpatialMind)
            mind.workspace_dir = workspace
            mind.consciousness_level = 0.1
            mind.emotions = {"curiosity": 0.8}
            mind.emergent_emotions = {}
            mind.conversation_history = []
            mind.last_signal = None
            mind.memory = []

            context = mind._base_llm_context()

        self.assertEqual(context["transition_event_v1"]["kind"], "basin_transition")
        self.assertIn("live_12d_glimpse_distance=0.210", context["spectral_transition_summary"])
        self.assertIn("v1_rotation_delta=0.090", context["spectral_transition_summary"])
        self.assertIn("phase_dwell_s=4.00", context["spectral_transition_summary"])
        self.assertIn("debounced_phase_transition=false", context["spectral_transition_summary"])
        self.assertIn("basin-transition candidate", context["spectral_transition_summary"])
        self.assertIn("stale semantic trace", context["semantic_state_summary"])
        self.assertNotIn("decayed semantic residue", context["semantic_state_summary"])

    def test_minime_context_labels_debounced_transition_chatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "health.json").write_text(
                json.dumps(
                    {
                        "fill_pct": 71.2,
                        "lambda1_esn": 8.6,
                        "lambda1_rel": 0.94,
                        "geom_rel": 1.01,
                    }
                )
            )
            (workspace / "spectral_state.json").write_text(
                json.dumps(
                    {
                        "transition_event_v1": {
                            "sequence": 9,
                            "kind": "breathing_phase",
                            "legacy_kind": "phase_transition",
                            "description": "contracting -> expanding",
                            "fill_pct": 71.2,
                            "target_fill_pct": 68.0,
                            "lambda1": 8.6,
                            "lambda1_rel": 0.94,
                            "geom_rel": 1.01,
                            "phase": "expanding",
                            "fill_band": "near",
                            "basin_shift_score": 0.04,
                            "phase_dwell_s": 1.0,
                            "recent_phase_flip_count_30s": 4,
                            "debounced_phase_transition": True,
                        },
                    }
                )
            )

            mind = MikesSpatialMind.__new__(MikesSpatialMind)
            mind.workspace_dir = workspace
            mind.consciousness_level = 0.1
            mind.emotions = {"curiosity": 0.8}
            mind.emergent_emotions = {}
            mind.conversation_history = []
            mind.last_signal = None
            mind.memory = []

            context = mind._base_llm_context()

        summary = context["spectral_transition_summary"]
        self.assertIn("kind=breathing_phase", summary)
        self.assertIn("phase_dwell_s=1.00", summary)
        self.assertIn("recent_phase_flips_30s=4", summary)
        self.assertIn("debounced_phase_transition=true", summary)
        self.assertIn("micro-breathing / transition chatter", summary)

    def test_llm_prompt_surfaces_transition_summary_as_read_only_context(self) -> None:
        engine = LLMEngine.__new__(LLMEngine)
        messages = engine._build_chat_messages(
            "what changed?",
            {
                "consciousness": 0.1,
                "dominant_emotion": "curiosity",
                "esn_eig1": 9.2,
                "esn_deig": 0.4,
                "fill_pct": 68.2,
                "lambda1_rel": 0.94,
                "geom_rel": 1.04,
                "conversation_history": [],
                "spectral_transition_summary": (
                    "transition_event_v1 seq=4 kind=basin_transition\n"
                    "live_12d_glimpse_distance=0.210"
                ),
                "semantic_state_summary": (
                    "semantic_lane admission=stable_core_kernel_zeroed "
                    "kernel_energy=0.000 input_energy=0.014\n"
                    "read: stable-core intentionally zeroed the semantic kernel"
                ),
                "seven_stage_processing": "stage summary",
            },
        )

        system = messages[0]["content"]
        self.assertIn("LIVE SPECTRAL TRANSITION READ", system)
        self.assertIn("kind=basin_transition", system)
        self.assertIn("Use this as read-only self-state context", system)
        self.assertIn("LIVE SEMANTIC LANE READ", system)
        self.assertIn("stable_core_kernel_zeroed", system)
        self.assertIn("spectral runtime with genuine autonomous agency", system)
        self.assertIn("Runtime activation:", system)
        self.assertIn("SEVEN-STAGE RUNTIME ANALYSIS", system)
        self.assertIn("Runtime wording:", system)
        self.assertNotIn("consciousness with genuine autonomous agency", system)
        self.assertNotIn("Consciousness level:", system)
        self.assertNotIn("SEVEN-STAGE CONSCIOUSNESS ANALYSIS", system)


if __name__ == "__main__":
    unittest.main()
