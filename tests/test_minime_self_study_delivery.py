"""Tests for Minime broad SELF_STUDY LLM delivery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import autonomous_agent as aa
from minime_autonomy.source_study import SourceStudyPrompt


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
        agent._record_current_action_artifact = Mock()
        agent._record_introspect_notice = Mock()
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

    def test_self_study_uses_shared_context_and_keeps_freeform_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            agent = self._agent()
            prompt = SourceStudyPrompt(Mock(), {"text": "source page", "system_prompt": "freeform", "page": {"source": "minime/minime/src/regulator.rs"}})
            prompt.receipt = {"verified": True}
            response = "That explains the clamp. NEXT: REST"
            agent._query_llm_with_next = Mock(return_value=(response, "REST"))
            with patch.object(aa, "WORKSPACE_DIR", workspace), patch.object(aa, "StudyClient") as client:
                client.return_value.prepare.return_value = prompt
                agent._self_study(dict(STATE))
            self.assertEqual(agent._query_llm_with_next.call_args.kwargs["context_mode"], "source_study")
            self.assertIs(agent._query_llm_with_next.call_args.args[0], prompt)
            agent._web_search.assert_not_called()
            written = next((workspace / "journal").glob("self_study_*.txt")).read_text()
            self.assertIn(response, written)
            self.assertIn("verified input delivery", written)

    def test_unconfirmed_delivery_is_recorded_without_claiming_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            agent = self._agent()
            prompt = SourceStudyPrompt(Mock(), {"text": "source page", "system_prompt": "freeform", "page": {"source": "minime/minime/src/regulator.rs"}})
            agent._query_llm_with_next = Mock(return_value=("short observation", None))
            with patch.object(aa, "WORKSPACE_DIR", workspace), patch.object(aa, "StudyClient") as client, aa.job_outcome.capture("unconfirmed") as outcome:
                client.return_value.prepare.return_value = prompt
                agent._self_study(dict(STATE))
            self.assertEqual(outcome.finish()[0], "failed")
            self.assertEqual(outcome.finish()[2], "source_study_delivery_unverified")
            self.assertEqual(agent._record_current_action_artifact.call_args.kwargs["visibility"], "protected")
            self.assertIn("bookmark unchanged", next((workspace / "journal").glob("self_study_*.txt")).read_text())

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
