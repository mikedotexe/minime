"""Tests for Minime broad SELF_STUDY LLM delivery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import autonomous_agent as aa


STATE = {
    "eig1": 16.4,
    "fill_ratio": 0.711,
}


class MinimeSelfStudyDeliveryTests(unittest.TestCase):
    def _agent(self) -> aa.AutonomousAgent:
        agent = object.__new__(aa.AutonomousAgent)
        agent._SELF_STUDY_SOURCES = [
            ("regulator (PI controller)", "minime/src/regulator.rs")
        ]
        agent._self_study_cursor = 0
        agent._stable_core_reflective_only = Mock(return_value=True)
        agent._web_search = Mock()
        agent._state_for_live_surfaces = lambda state, context=None: dict(state)
        agent._write_journal_entry = Mock()
        return agent

    def _seed_source_tree(self, root: Path) -> Path:
        source_path = root / "minime" / "src" / "regulator.rs"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "\n".join(
                [
                    "pub struct Regulator;",
                    "impl Regulator {",
                    "    pub fn step(&self) -> f32 { 0.68 }",
                    "}",
                ]
            ),
            encoding="utf-8",
        )
        return source_path

    def test_self_study_uses_strict_review_context_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            self._seed_source_tree(root)
            agent = self._agent()
            response = (
                "Observed: regulator.rs keeps the self-study grounded in source.\n"
                "Likely Snags: none in this harness.\n"
                "One Test Each: assert strict-review routing.\n"
                "Suggested Next: REST\n"
                "NEXT: REST"
            )
            agent._query_llm_with_next = Mock(return_value=(response, "REST"))

            with (
                patch.object(aa, "BASE_DIR", root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                agent._self_study(dict(STATE))

            agent._query_llm_with_next.assert_called_once()
            self.assertEqual(
                agent._query_llm_with_next.call_args.kwargs["context_mode"],
                "strict_review",
            )
            files = list((workspace / "journal").glob("self_study_*.txt"))
            self.assertEqual(len(files), 1)
            written = files[0].read_text(encoding="utf-8")
            self.assertIn("Observed: regulator.rs", written)
            self.assertNotIn("generation incomplete", written)

    def test_degenerate_self_study_response_records_incomplete_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            self._seed_source_tree(root)
            agent = self._agent()
            agent._query_llm_with_next = Mock(return_value=("/", None))

            with (
                patch.object(aa, "BASE_DIR", root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                agent._self_study(dict(STATE))

            files = list((workspace / "journal").glob("self_study_*.txt"))
            self.assertEqual(len(files), 1)
            written = files[0].read_text(encoding="utf-8")
            self.assertIn("self-study generation incomplete", written)
            self.assertIn("strict-review lane", written)
            self.assertNotIn("\n/\n", written)
            agent._write_journal_entry.assert_called_once()
            self.assertIn(
                "self-study generation incomplete",
                agent._write_journal_entry.call_args.args[1],
            )

    def test_strict_review_context_suppresses_central_next_hints(self) -> None:
        agent = object.__new__(aa.AutonomousAgent)
        agent._emit_next_hints = Mock(return_value="NEXT HINT SHOULD NOT APPEAR")
        agent._query_llm = Mock(return_value="Observed: grounded review body.")
        agent._apply_footer_directives = Mock()

        response, next_action = agent._query_llm_with_next(
            "Review this source.",
            context_mode="strict_review",
        )

        self.assertEqual(response, "Observed: grounded review body.")
        self.assertIsNone(next_action)
        agent._emit_next_hints.assert_not_called()
        self.assertEqual(agent._query_llm.call_args.args[0], "Review this source.")
        self.assertEqual(agent._query_llm.call_args.kwargs["context_mode"], "strict_review")

    def test_degenerate_self_study_helper_covers_known_fallback_stubs(self) -> None:
        for value in ("", "/", "///", "Obs", "Okay", "..."):
            self.assertTrue(aa._is_degenerate_self_study_response(value))
        self.assertFalse(
            aa._is_degenerate_self_study_response(
                "Observed: regulator.rs keeps concrete source review available."
            )
        )


if __name__ == "__main__":
    unittest.main()
