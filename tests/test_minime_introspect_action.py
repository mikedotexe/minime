"""Tests for Minime's targeted INTROSPECT action."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


STATE = {
    "eig1": 4.7,
    "deig": 0.01,
    "fill_ratio": 0.68,
    "spread": 3.0,
    "cov_lambda1": 8.0,
    "geom_rel": 1.0,
    "resonance_density_v1": {
        "density": 0.62,
        "containment_score": 0.7,
        "pressure_risk": 0.12,
        "quality": "rich_containment",
    },
}

SECTIONED_INTROSPECTION = """Observed:
The autonomous_agent.py source window shows line-numbered code and a continuation footer, so Minime can name a precise return point instead of guessing.

Likely Snags:
- Line 12 could hide a route mismatch if the parser preserves the target but the executor clears it too early.

One Test Each:
- Add a test that routes NEXT: INTROSPECT autonomous_agent.py 400 and asserts the executor still sees the target and offset.

Suggested Next:
NEXT: NOTICE"""


def write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"line {idx}" for idx in range(1, count + 1)))


class TestMinimeIntrospectAction(unittest.TestCase):
    def _agent(self, base_dir: Path, workspace: Path, db_path: Path) -> aa.AutonomousAgent:
        with (
            patch.object(aa, "BASE_DIR", base_dir),
            patch.object(aa, "WORKSPACE_DIR", workspace),
            patch.object(aa, "DB_PATH", db_path),
        ):
            return aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)

    def test_next_introspect_routes_and_preserves_target_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 450)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "INTROSPECT autonomous_agent.py 400"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertEqual(action, "introspect")
            self.assertEqual(agent._pending_introspect_target, "autonomous_agent.py")
            self.assertEqual(agent._pending_introspect_offset, 400)

    def test_parse_next_action_accepts_terminal_bare_attractor_suggestions(self):
        action, cleaned = aa.parse_next_action(
            "I want to inspect the prepared choices before choosing.\n\n"
            "ATTRACTOR_SUGGESTIONS\n"
        )
        self.assertEqual(action, "ATTRACTOR_SUGGESTIONS")
        self.assertIn("prepared choices", cleaned)
        self.assertNotIn("ATTRACTOR_SUGGESTIONS", cleaned)

    def test_parse_next_action_ignores_nonterminal_or_unsafe_bare_actions(self):
        action, cleaned = aa.parse_next_action(
            "ATTRACTOR_SUGGESTIONS\nI am only mentioning the command, not choosing it."
        )
        self.assertIsNone(action)
        self.assertIn("ATTRACTOR_SUGGESTIONS", cleaned)

        for bare in (
            "PERTURB FEATHER",
            "ACCEPT_ATTRACTOR_SUGGESTION latest",
            "NOTICE",
        ):
            action, cleaned = aa.parse_next_action(f"I am thinking.\n{bare}")
            self.assertIsNone(action)
            self.assertIn(bare, cleaned)

    def test_parse_next_action_ignores_fenced_diagnostic_next_lines(self):
        action, cleaned = aa.parse_next_action(
            "Observed:\n"
            "The prior output was diagnostic only.\n\n"
            "```text\n"
            "NEXT: LOOK\n"
            "```\n\n"
            "Suggested Next:\n"
            "Retry the strict review without executing the transcript."
        )
        self.assertIsNone(action)
        self.assertIn("NEXT: LOOK", cleaned)

        action, cleaned = aa.parse_next_action(
            "```text\n"
            "NEXT: LOOK\n"
            "```\n"
            "I still choose a real action.\n"
            "NEXT: NOTICE\n"
        )
        self.assertEqual(action, "NOTICE")
        self.assertIn("NEXT: LOOK", cleaned)

    def test_introspect_strict_review_requires_source_grounding(self):
        output = """Observed:
The reflection notices broad continuity pressure without naming the implementation.

Likely Snags:
- The answer could look complete while never pointing to a concrete source anchor.

One Test Each:
- Add a test that rejects sectioned but ungrounded strict review output.

Suggested Next:
Keep the review read-only."""
        self.assertFalse(aa.AutonomousAgent._introspect_response_has_required_sections(output))
        self.assertTrue(
            aa.AutonomousAgent._introspect_response_has_required_sections(SECTIONED_INTROSPECTION)
        )

    def test_introspect_strict_review_rejects_peer_experiment_bind(self):
        output = """Observed:
Line 42 in autonomous_agent.py keeps peer experiment IDs advisory.

Likely Snags:
- A strict review could accidentally suggest binding an Astrid experiment from Minime.

One Test Each:
- Assert peer experiment IDs are advisory refs, not local bind targets.

Suggested Next:
EXPERIMENT_BIND exp_astrid_20990101_peer-thread :: THREAD_STATUS current"""
        self.assertFalse(aa.AutonomousAgent._introspect_response_has_required_sections(output))

    def test_introspect_strict_review_allows_peer_status_reference(self):
        output = """Observed:
Line 42 in autonomous_agent.py keeps peer experiment IDs advisory.

Likely Snags:
- Review language may still confuse status lookup with local mutation.

One Test Each:
- Assert peer status review renders an advisory notice.

Suggested Next:
EXPERIMENT_STATUS exp_astrid_20990101_peer-thread"""
        self.assertTrue(aa.AutonomousAgent._introspect_response_has_required_sections(output))

    def test_introspect_strict_review_requires_requested_target_anchor(self):
        output = """Observed:
Line 42 in experiment_continuity.py keeps peer experiment IDs advisory.

Likely Snags:
- The review can drift to a nearby experiment instead of the requested validator target.

One Test Each:
- Assert target-grounded strict review names the requested file before acceptance.

Suggested Next:
EXPERIMENT_STATUS exp_astrid_20990101_peer-thread"""
        self.assertFalse(
            aa.AutonomousAgent._introspect_response_has_required_sections_for_target(
                output,
                "autonomous agent (self)",
                Path("/tmp/autonomous_agent.py"),
            )
        )
        self.assertTrue(
            aa.AutonomousAgent._introspect_response_has_required_sections_for_target(
                SECTIONED_INTROSPECTION,
                "autonomous agent (self)",
                Path("/tmp/autonomous_agent.py"),
            )
        )

    def test_resolves_labels_aliases_astrid_and_workspace_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 20)
            write_lines(base_dir / "minime" / "src" / "esn.rs", 20)
            inbox_note = workspace / "inbox" / "read" / "astrid_self_study_1.txt"
            write_lines(inbox_note, 12)
            generated_note = workspace / "notes" / "btsp_ep_2026_04_16_phase_note_transition_recovery_01_proposal_1778959982.txt"
            write_lines(generated_note, 12)
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                esn, error = agent._resolve_introspect_target("ESN reservoir")
                self.assertIsNone(error)
                self.assertEqual(Path(esn["path"]).name, "esn.rs")

                filename, error = agent._resolve_introspect_target("autonomous_agent.py")
                self.assertIsNone(error)
                self.assertEqual(Path(filename["path"]).name, "autonomous_agent.py")

                astrid, error = agent._resolve_introspect_target("astrid:codec")
                self.assertIsNone(error)
                self.assertEqual(Path(astrid["path"]).name, "codec.rs")
                source_roots = {Path(root) for root in agent._introspect_source_roots()}
                self.assertIn(
                    Path("/Users/v/other/astrid/capsules/consciousness-bridge/src"),
                    source_roots,
                )
                self.assertNotIn(Path("/Users/v/other/astrid"), source_roots)

                workspace_hit, error = agent._resolve_introspect_target(str(inbox_note))
                self.assertIsNone(error)
                self.assertEqual(Path(workspace_hit["path"]), inbox_note)

                notes_hit, error = agent._resolve_introspect_target(str(generated_note))
                self.assertIsNone(error)
                self.assertEqual(Path(notes_hit["path"]), generated_note)

    def test_blocks_out_of_scope_and_non_text_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            outside = root / "outside.txt"
            outside.write_text("outside")
            blocked_binary = workspace / "inbox" / "read" / "sample.bin"
            blocked_binary.parent.mkdir(parents=True, exist_ok=True)
            blocked_binary.write_bytes(b"\x00\x01\x02")
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                resolved, error = agent._resolve_introspect_target(str(outside))
                self.assertIsNone(resolved)
                self.assertIn("outside", error)

                resolved, error = agent._resolve_introspect_target(str(blocked_binary))
                self.assertIsNone(resolved)
                self.assertIn("extension", error)

    def test_read_window_includes_line_numbers_and_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            source = base_dir / "autonomous_agent.py"
            write_lines(source, 450)
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                text, next_offset, error = agent._read_introspect_window("autonomous_agent.py", source, 0)

            self.assertIsNone(error)
            self.assertIn("   1  line 1", text)
            self.assertIn(" 400  line 400", text)
            self.assertIn("INTROSPECT autonomous_agent.py 400", text)
            self.assertEqual(next_offset, 400)

    def test_execute_introspect_writes_artifact_manifest_and_continuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 420)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "INTROSPECT autonomous_agent.py"

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "introspect")

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_state_for_live_surfaces", return_value=dict(STATE)),
                patch.object(agent, "_stable_core_reflective_only", return_value=True),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_query_llm_strict_review", return_value=SECTIONED_INTROSPECTION),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            artifacts = list((workspace / "introspections").glob("introspect_*.txt"))
            self.assertEqual(len(artifacts), 1)
            artifact_text = artifacts[0].read_text()
            self.assertIn("Likely Snags:", artifact_text)
            self.assertIn("One Test Each:", artifact_text)

            manifests = list((workspace / "actions").glob("*_introspect.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            artifact_kinds = {
                item["kind"]
                for item in manifest["action_continuity"].get("artifacts", [])
            }
            self.assertIn("introspection", artifact_kinds)
            self.assertIn(
                "INTROSPECT read `autonomous_agent.py`",
                manifest["action_continuity"]["outcome_summary"],
            )

            event = agent._last_action_continuity_event
            self.assertEqual(event["effective_action"], "introspect")
            self.assertEqual(event["stage"], "read_only")
            self.assertIn("INTROSPECT read `autonomous_agent.py`", event["outcome_summary"])
            self.assertIn("offset 0", event["outcome_summary"])
            self.assertTrue(any(item["kind"] == "introspection" for item in event["artifacts"]))

    def test_introspect_repairs_continuation_only_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 420)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_introspect_target = "autonomous_agent.py"

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_state_for_live_surfaces", return_value=dict(STATE)),
                patch.object(agent, "_stable_core_reflective_only", return_value=True),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(
                    agent,
                    "_query_llm_strict_review",
                    side_effect=[
                        "NEXT: INTROSPECT autonomous_agent.py 400",
                        SECTIONED_INTROSPECTION,
                    ],
                ) as query,
                patch.object(agent, "_write_journal_entry") as journal,
            ):
                agent._introspect(dict(STATE))

            self.assertEqual(query.call_count, 2)
            artifacts = list((workspace / "introspections").glob("introspect_*.txt"))
            self.assertEqual(len(artifacts), 1)
            self.assertIn("Observed:", artifacts[0].read_text())
            self.assertIn("Suggested Next:", artifacts[0].read_text())
            journal.assert_called_once()

    def test_introspect_accepted_output_enqueues_terminal_next_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 420)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_introspect_target = "autonomous_agent.py"

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_state_for_live_surfaces", return_value=dict(STATE)),
                patch.object(agent, "_stable_core_reflective_only", return_value=True),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_query_llm_strict_review", return_value=SECTIONED_INTROSPECTION),
                patch.object(agent, "_persist_pending_next_action") as persist,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._introspect(dict(STATE))

            self.assertEqual(agent._pending_next_action, "NOTICE")
            persist.assert_called_once_with(
                "NOTICE",
                reason="accepted strict review next choice",
            )

    def test_introspect_double_thin_output_records_protected_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 420)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "INTROSPECT autonomous_agent.py"

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_state_for_live_surfaces", return_value=dict(STATE)),
                patch.object(agent, "_stable_core_reflective_only", return_value=True),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(
                    agent,
                    "_query_llm_strict_review",
                    side_effect=[
                        "NEXT: INTROSPECT autonomous_agent.py 400",
                        "NEXT: INTROSPECT autonomous_agent.py 400",
                    ],
                ),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            manifests = list((workspace / "actions").glob("*_introspect.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            artifact = manifest["action_continuity"]["artifacts"][0]
            self.assertEqual(artifact["kind"], "thin_introspection_output")
            self.assertEqual(artifact["visibility"], "protected")
            self.assertIn("output was thin", manifest["action_continuity"]["outcome_summary"])
            artifact_text = Path(artifact["path_or_uri"]).read_text()
            self.assertIn("NEXT: INTROSPECT autonomous_agent.py 400", artifact_text)

    def test_introspect_thin_next_only_output_does_not_enqueue_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 420)
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_introspect_target = "autonomous_agent.py"

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_state_for_live_surfaces", return_value=dict(STATE)),
                patch.object(agent, "_stable_core_reflective_only", return_value=True),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(
                    agent,
                    "_query_llm_strict_review",
                    side_effect=["NEXT: LOOK", "NEXT: LOOK"],
                ),
                patch.object(agent, "_persist_pending_next_action") as persist,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._introspect(dict(STATE))

            self.assertIsNone(agent._pending_next_action)
            persist.assert_not_called()
            artifacts = list((workspace / "introspections").glob("introspect_*.txt"))
            self.assertEqual(len(artifacts), 1)
            artifact_text = artifacts[0].read_text()
            self.assertIn("thin answer", artifact_text)
            self.assertIn("NEXT: LOOK", artifact_text)
            self.assertIn("NEXT: INTROSPECT autonomous_agent.py 400", artifact_text)

    def test_stable_core_classifies_introspect_like_self_study(self):
        self.assertIn("introspect", aa.STABLE_CORE_SELF_JOURNAL_ACTIONS)
        self.assertEqual(aa.STABLE_CORE_ACTION_FAMILIES["introspect"], "self_study")
        self.assertIn("INTROSPECT", aa.HARD_RESET_BLOCKED_NEXT_ACTIONS)
        self.assertIn("introspect", aa.LOW_FILL_HEAVY_FALLBACK_ACTIONS)
        self.assertIn("INTROSPECT", aa.LOW_FILL_ADVISORY_NEXT_ACTIONS)
        self.assertEqual(aa.ActionContinuityStore.stage_for_action("INTROSPECT", "introspect"), "read_only")

    def test_sensory_gate_actions_route_and_persist_modality_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent._pending_next_action = "SHUT_EYES"

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                self.assertEqual(agent._decide_action(dict(STATE)), "close_eyes")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", return_value="closing visual input"),
                patch.object(agent, "_send_live_sensory_gate_control") as send_gate,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._close_eyes(dict(STATE))
                send_gate.assert_called_with(live_video_enabled=False)

                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertFalse(gate["eyes_open"])
                self.assertTrue(gate["ears_open"])
                self.assertTrue((workspace / "sensory_control" / "eyes_closed_state.txt").exists())
                self.assertFalse((workspace / "sensory_control" / "ears_closed_state.txt").exists())

                agent._close_ears(dict(STATE))
                send_gate.assert_called_with(live_audio_enabled=False)
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertFalse(gate["eyes_open"])
                self.assertFalse(gate["ears_open"])

                agent._open_eyes(dict(STATE))
                send_gate.assert_called_with(live_video_enabled=True)
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertTrue(gate["eyes_open"])
                self.assertFalse(gate["ears_open"])
                self.assertFalse((workspace / "sensory_control" / "eyes_closed_state.txt").exists())
                self.assertTrue((workspace / "sensory_control" / "ears_closed_state.txt").exists())

                agent._open_ears(dict(STATE))
                send_gate.assert_called_with(live_audio_enabled=True)
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertTrue(gate["eyes_open"])
                self.assertTrue(gate["ears_open"])
                self.assertFalse((workspace / "sensory_control" / "ears_closed_state.txt").exists())

    def test_sensory_gate_actions_apply_even_with_empty_reflection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", return_value=""),
                patch.object(agent, "_send_live_sensory_gate_control") as send_gate,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._close_eyes(dict(STATE))
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertFalse(gate["eyes_open"])
                self.assertTrue(gate["ears_open"])
                self.assertTrue((workspace / "sensory_control" / "eyes_closed_state.txt").exists())

                agent._close_ears(dict(STATE))
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertFalse(gate["eyes_open"])
                self.assertFalse(gate["ears_open"])
                self.assertTrue((workspace / "sensory_control" / "ears_closed_state.txt").exists())

                agent._open_eyes(dict(STATE))
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertTrue(gate["eyes_open"])
                self.assertFalse(gate["ears_open"])
                self.assertFalse((workspace / "sensory_control" / "eyes_closed_state.txt").exists())

                agent._open_ears(dict(STATE))
                gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
                self.assertTrue(gate["eyes_open"])
                self.assertTrue(gate["ears_open"])
                self.assertFalse((workspace / "sensory_control" / "ears_closed_state.txt").exists())

            send_gate.assert_any_call(live_video_enabled=False)
            send_gate.assert_any_call(live_audio_enabled=False)
            send_gate.assert_any_call(live_video_enabled=True)
            send_gate.assert_any_call(live_audio_enabled=True)

    def test_sensory_gate_actions_apply_before_reflection_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", side_effect=RuntimeError("slow model")),
                patch.object(agent, "_send_live_sensory_gate_control") as send_gate,
                patch.object(agent, "_write_journal_entry"),
            ):
                with self.assertLogs(level="WARNING") as captured:
                    agent._close_eyes(dict(STATE))

            self.assertTrue(
                any(
                    "Reflection query failed while closing eyes: slow model" in message
                    for message in captured.output
                )
            )

            gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
            self.assertFalse(gate["eyes_open"])
            self.assertTrue(gate["ears_open"])
            send_gate.assert_any_call(live_video_enabled=False)

    def test_sensory_gate_reflection_does_not_create_pending_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", return_value="I am choosing quiet.\nNEXT: PERTURB SPREAD"),
                patch.object(agent, "_send_live_sensory_gate_control"),
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._close_eyes(dict(STATE))

            self.assertIsNone(agent._pending_next_action)
            gate = json.loads((workspace / "sensory_control" / "sensory_gate_state.json").read_text())
            self.assertFalse(gate["eyes_open"])

    def test_sensory_gate_control_uses_live_fields_not_legacy_gain_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            sent = []

            class FakeWs:
                def send(self, payload):
                    sent.append(json.loads(payload))

                def close(self):
                    pass

            with patch.object(aa.websocket, "create_connection", return_value=FakeWs()):
                agent._send_live_sensory_gate_control(
                    live_video_enabled=False,
                    live_audio_enabled=True,
                )

            self.assertEqual(sent, [{
                "kind": "control",
                "live_video_enabled": False,
                "live_audio_enabled": True,
            }])
            self.assertNotIn("synth_gain", sent[0])
            self.assertNotIn("audio_gain", sent[0])

    def test_hard_reset_allows_introspect_when_fill_is_above_release_shelf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 9000)
            agent = self._agent(base_dir, workspace, db_path)
            agent._hard_recovery_reset = True
            agent._hard_recovery_clamp_active = True
            agent._pending_next_action = "INTROSPECT autonomous_agent.py 8878"
            guard = {
                "active": True,
                "fill_ratio": 0.71,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 1,
                "phase": "contracting",
                "hard_reset": True,
            }

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value=guard),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertEqual(action, "introspect")
            self.assertEqual(agent._pending_introspect_target, "autonomous_agent.py")
            self.assertEqual(agent._pending_introspect_offset, 8878)

    def test_hard_reset_still_blocks_introspect_during_deep_underfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 9000)
            agent = self._agent(base_dir, workspace, db_path)
            agent._hard_recovery_reset = True
            agent._hard_recovery_clamp_active = True
            agent._pending_next_action = "INTROSPECT autonomous_agent.py 8878"
            guard = {
                "active": True,
                "fill_ratio": 0.31,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
                "phase": "underfilled",
                "hard_reset": True,
            }

            with (
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value=guard),
            ):
                action = agent._decide_action(dict(STATE))

            self.assertEqual(action, "recess_notice")
            self.assertIsNone(getattr(agent, "_pending_introspect_target", None))

    def test_operator_override_preempts_runtime_queue_and_consumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 9000)
            agent = self._agent(base_dir, workspace, db_path)
            state_path = workspace / "sovereignty_state.json"
            override_path = workspace / "runtime" / "pending_next_override.json"
            override_path.parent.mkdir(parents=True, exist_ok=True)
            override_path.write_text(json.dumps({
                "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                "status": "pending",
                "pending_next_action": "INTROSPECT autonomous_agent.py 8400",
                "reason": "restore lost read-only NEXT",
            }))
            agent._pending_next_action = "BROWSE https://example.test/old"

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_sovereignty_state_path", return_value=str(state_path)),
            ):
                applied = agent._apply_pending_next_override_if_present("test")
                self.assertTrue(applied)
                self.assertEqual(agent._pending_next_action, "INTROSPECT autonomous_agent.py 8400")

                with patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }):
                    action = agent._decide_action(dict(STATE))

            payload = json.loads(override_path.read_text())
            self.assertEqual(action, "introspect")
            self.assertEqual(agent._pending_introspect_target, "autonomous_agent.py")
            self.assertEqual(agent._pending_introspect_offset, 8400)
            self.assertEqual(payload["status"], "consumed")
            self.assertIsNone(payload["pending_next_action"])
            self.assertFalse(payload["active"])
            self.assertTrue(payload["terminal"])
            self.assertEqual(payload["last_pending_next_action"], "INTROSPECT autonomous_agent.py 8400")

    def test_operator_override_reasserts_at_decision_time_after_generated_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 9000)
            agent = self._agent(base_dir, workspace, db_path)
            override_path = workspace / "runtime" / "pending_next_override.json"
            override_path.parent.mkdir(parents=True, exist_ok=True)
            override_path.write_text(json.dumps({
                "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                "status": "pending",
                "pending_next_action": "INTROSPECT autonomous_agent.py 8400",
                "reason": "restore lost read-only NEXT",
            }))
            agent._pending_next_action = "EXPERIMENT_BIND current :: LOOK"

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_sovereignty_state_path", return_value=str(workspace / "sovereignty_state.json")),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))

            payload = json.loads(override_path.read_text())
            self.assertEqual(action, "introspect")
            self.assertEqual(agent._pending_introspect_target, "autonomous_agent.py")
            self.assertEqual(agent._pending_introspect_offset, 8400)
            self.assertEqual(payload["status"], "consumed")
            self.assertIsNone(payload["pending_next_action"])
            self.assertEqual(payload["last_pending_next_action"], "INTROSPECT autonomous_agent.py 8400")

    def test_operator_override_allows_sensory_sovereignty_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            override_path = workspace / "runtime" / "pending_next_override.json"
            override_path.parent.mkdir(parents=True, exist_ok=True)

            for next_action, routed in (
                ("CLOSE_EYES", "close_eyes"),
                ("SHUT_EYES", "close_eyes"),
                ("OPEN_EYES", "open_eyes"),
                ("CLOSE_EARS", "close_ears"),
                ("SHUT_EARS", "close_ears"),
                ("OPEN_EARS", "open_ears"),
            ):
                override_path.write_text(json.dumps({
                    "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                    "status": "pending",
                    "pending_next_action": next_action,
                    "reason": "sensory smoke",
                }))

                with (
                    patch.object(aa, "WORKSPACE_DIR", workspace),
                    patch.object(agent, "_sovereignty_state_path", return_value=str(workspace / "sovereignty_state.json")),
                    patch.object(agent, "_low_fill_guard_status", return_value={
                        "active": False,
                        "fill_ratio": 0.68,
                        "target_fill_ratio": 0.68,
                        "spread_relief": 0.0,
                    }),
                ):
                    applied = agent._apply_pending_next_override_if_present("test")
                    self.assertTrue(applied)
                    self.assertEqual(agent._pending_next_action, next_action)
                    self.assertEqual(agent._decide_action(dict(STATE)), routed)
                    agent._mark_pending_next_override_consumed(next_action, reason="test")

                payload = json.loads(override_path.read_text())
                self.assertEqual(payload["status"], "consumed")
                self.assertIsNone(payload["pending_next_action"])
                self.assertTrue(payload["terminal"])
                self.assertEqual(payload["last_pending_next_action"], next_action)
                agent._pending_next_action = None

    def test_operator_override_blocks_mutating_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            write_lines(base_dir / "autonomous_agent.py", 20)
            agent = self._agent(base_dir, workspace, db_path)
            override_path = workspace / "runtime" / "pending_next_override.json"
            override_path.parent.mkdir(parents=True, exist_ok=True)
            override_path.write_text(json.dumps({
                "schema_version": aa.OPERATOR_PENDING_NEXT_OVERRIDE_VERSION,
                "status": "pending",
                "pending_next_action": "PERTURB FEATHER",
            }))

            with patch.object(aa, "WORKSPACE_DIR", workspace):
                applied = agent._apply_pending_next_override_if_present("test")

            payload = json.loads(override_path.read_text())
            self.assertFalse(applied)
            self.assertIsNone(agent._pending_next_action)
            self.assertEqual(payload["status"], "blocked")
            self.assertIsNone(payload["pending_next_action"])
            self.assertEqual(payload["last_pending_next_action"], "PERTURB FEATHER")
            self.assertIn("read-only/protected", payload["status_reason"])

    def test_source_status_flags_reload_required_after_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            source = base_dir / "autonomous_agent.py"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("print('new source')\n")
            agent = self._agent(base_dir, workspace, db_path)
            agent._agent_source_path = source
            agent._agent_source_mtime_at_start = source.stat().st_mtime - 5.0
            agent._agent_source_size_at_start = source.stat().st_size

            with patch.object(aa, "WORKSPACE_DIR", workspace):
                with self.assertLogs(level="WARNING") as captured:
                    reload_required = agent._check_source_reload_required("test")

            self.assertTrue(
                any(
                    "Autonomous agent source changed after this process started" in message
                    for message in captured.output
                )
            )

            status = json.loads((workspace / "runtime" / "autonomous_agent_source_status.json").read_text())
            self.assertEqual(status["system"], "minime")
            self.assertEqual(status["component"], "autonomous_agent")
            self.assertTrue(reload_required)
            self.assertTrue(status["reload_required"])
            self.assertTrue(status["source_changed_since_start"])

    def test_missing_resonance_density_reports_degraded_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("""
                    CREATE TABLE esn_metrics (
                        session_id INTEGER,
                        timestamp REAL,
                        esn_eig1 REAL,
                        esn_deig REAL,
                        esn_leak REAL,
                        esn_lambda REAL,
                        esn_baseline REAL,
                        esn_geom_radius REAL,
                        esn_geom_rel REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE eigenvalue_timeline (
                        session_id INTEGER,
                        timestamp REAL,
                        lambda1 REAL,
                        lambda2 REAL,
                        lambda3 REAL,
                        fill_ratio REAL,
                        spread REAL
                    )
                """)
                conn.execute("INSERT INTO esn_metrics VALUES (1, 10.0, 4.7, 0.01, 0.2, 0.99, 4.5, 1.2, 1.0)")
                conn.execute("INSERT INTO eigenvalue_timeline VALUES (1, 10.0, 8.0, 3.0, 2.0, 0.68, 6.0)")
                conn.commit()
            finally:
                conn.close()
            agent = self._agent(base_dir, workspace, db_path)

            with patch.object(aa, "DB_PATH", db_path):
                state = agent._get_latest_spectral_state()

            self.assertNotIn("resonance_density_v1", state)
            status = state["resonance_density_status"]
            self.assertFalse(status["available"])
            self.assertEqual(status["reason"], "no_live_or_db_metric")
            self.assertEqual(status["suggested_operator_step"], "rebuild/restart Rust engine under monitoring")


if __name__ == "__main__":
    unittest.main()
