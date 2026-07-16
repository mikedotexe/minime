"""Structural and compatibility checks for staged autonomy extraction."""

import unittest
from pathlib import Path

import autonomous_agent as aa
from minime_autonomy import (
    attractors,
    authority,
    continuity,
    correspondence,
    journaling,
    llm_access,
    memory,
    parsing,
    research,
    runtime_actions,
    self_regulation,
)


ROOT = Path(__file__).resolve().parents[1]


class TestMinimeAutonomyBoundaries(unittest.TestCase):
    def test_root_facade_preserves_public_module_identity(self):
        self.assertEqual(Path(aa.__file__).resolve(), ROOT / "autonomous_agent.py")
        self.assertEqual(aa.BASE_DIR.resolve(), ROOT)
        self.assertIs(runtime_actions.AutonomousAgent, aa.AutonomousAgent)

    def test_source_monitoring_and_self_study_use_runtime_implementation(self):
        expected = ROOT / "minime_autonomy" / "runtime.py"
        self.assertEqual(aa.runtime_source_path().resolve(), expected)
        agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
        entry = next(
            item
            for item in agent._introspect_source_entries()
            if item["source"] == "autonomous_agent.py"
        )
        self.assertEqual(entry["path"].resolve(), expected)

    def test_domain_surfaces_resolve_canonical_implementations(self):
        self.assertIs(parsing.parse_next_action, aa.parse_next_action)
        self.assertIs(continuity.ActionContinuityStore, aa.ActionContinuityStore)
        self.assertIs(authority.ActionPreflightStore, aa.ActionPreflightStore)
        self.assertIs(research.ResearchOutcome, aa.ResearchOutcome)
        self.assertIs(memory.research_entry_allowed_for_memory, aa.research_entry_allowed_for_memory)
        self.assertIs(self_regulation.build_perturbation_vector, aa.build_perturbation_vector)
        self.assertIs(llm_access.LlmJobStore, aa.LlmJobStore)
        self.assertTrue(hasattr(correspondence.CorrespondenceRuntime, "_peer_correspondence"))
        self.assertTrue(hasattr(journaling.JournalRuntime, "_write_journal_entry"))
        self.assertTrue(hasattr(attractors.AttractorRuntime, "_attractor_intent"))

    def test_facades_and_domain_surfaces_stay_small(self):
        surfaces = [
            ROOT / "autonomous_agent.py",
            *(ROOT / "minime_autonomy").glob("*.py"),
        ]
        for path in surfaces:
            if path.name == "runtime.py":
                continue
            with self.subTest(path=path.name):
                self.assertLess(path.read_text().count("\n") + 1, 1000)
        note = (ROOT / "docs" / "DOMAIN_BOUNDARIES.md").read_text()
        self.assertIn("deliberate staged exception", note)


if __name__ == "__main__":
    unittest.main()
