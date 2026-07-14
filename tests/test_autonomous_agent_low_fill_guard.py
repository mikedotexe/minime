"""Tests for the hard recovery reset clamp."""

import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

import autonomous_agent as aa
from reporting_snapshot import ReportSnapshot, SurfaceSnapshot


class TestHardRecoveryResetClamp(unittest.TestCase):
    @staticmethod
    def _time_sequence(*values):
        values = list(values) or [0.0]
        state = {"idx": 0, "last": values[0]}

        def now():
            idx = state["idx"]
            if idx < len(values):
                state["last"] = values[idx]
                state["idx"] = idx + 1
            return state["last"]

        return now

    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        agent.session_id = 1
        agent._last_state = {"fill_ratio": 0.25}
        agent._hard_recovery_reset = True
        agent._hard_recovery_clamp_active = True
        agent._hard_recovery_release_streak = 0
        agent._last_action_name = "recess_notice"
        agent._pending_next_action = None
        agent._pending_choice_envelope_v1 = None
        agent._recent_next_actions = []
        agent.thresholds = aa.RECESS
        agent._pending_attractor_intent_stage = None
        agent._pending_attractor_shape_mode = None
        agent._pending_attractor_blend_parent_labels = []
        agent._pending_attractor_atlas_label = None
        agent._pending_attractor_atlas_card_only = False
        agent._pending_attractor_atlas_review = False
        agent._pending_attractor_suggestion_command = None
        agent._pending_attractor_suggestion_selector = None
        agent._pending_attractor_suggestion_revised_action = None
        agent._pending_attractor_suggestion_reason = None
        agent._pending_attractor_release_label = None
        agent._pending_attractor_release_resolved = False
        agent._test_sovereignty_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(agent._test_sovereignty_tmp.cleanup)
        agent._test_sovereignty_state_path = (
            Path(agent._test_sovereignty_tmp.name) / "sovereignty_state.json"
        )
        agent._sovereignty_state_path = lambda: str(agent._test_sovereignty_state_path)
        agent._resource_governor_status = lambda write=True: {
            "allowed_live": True,
            "primary_block_reason": None,
            "block_reasons": [],
        }
        agent._action_continuity = SimpleNamespace(
            session_id=agent.session_id,
            ensure_dirs=lambda: None,
            charter_required_guard_assessment=lambda raw_next: None,
            record_charter_required_guard_block=lambda raw_next, state, assessment: {},
            can_repair_experiment_intent=lambda raw_next: False,
            prompt_summary=lambda: None,
        )
        agent._llm_jobs = SimpleNamespace(
            ensure_dirs=lambda: None,
            active_primary_job=lambda: None,
            write_runtime_status=lambda: None,
            _elapsed_text=lambda job: "0s",
        )
        return agent

    def test_guard_status_uses_fixed_reset_target(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 30.2,
                "phase": "plateau",
                "pi": {"target_fill": 40.0},
                "cov": {"spread_relief": 0.025},
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                guard = agent._low_fill_guard_status({"fill_ratio": 0.10})
        self.assertTrue(guard["active"])
        self.assertAlmostEqual(guard["fill_ratio"], 0.302, places=3)
        self.assertAlmostEqual(guard["target_fill_ratio"], 0.65, places=3)
        self.assertEqual(guard["spread_relief"], 0.0)
        self.assertEqual(guard["release_streak"], 0)

    def test_deig_normalization_backfills_missing_runtime_caches(self):
        agent = object.__new__(aa.AutonomousAgent)
        value = agent._normalize_deig(0.25)
        self.assertEqual(value, 0.25)
        self.assertEqual(agent._deig_ema, 0.05)
        self.assertEqual(list(agent._deig_history), [0.25])
        self.assertIsNone(agent._last_cov_metrics)

    def test_guard_reroutes_heavy_fallback_action(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.22,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            candidate = agent._guard_low_fill_fallback("self_study", {"fill_ratio": 0.22})
        self.assertEqual(candidate, "recess_notice")

    def test_guard_leaves_safe_action_unchanged(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.22,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            candidate = agent._guard_low_fill_fallback("recess_drift", {"fill_ratio": 0.22})
        self.assertEqual(candidate, "recess_drift")

    def test_recess_spectral_pruning_advice_is_read_only_for_high_entropy_daydream(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.91,
            "pressure_source_v1": {
                "pressure_score": 0.62,
                "porosity_score": 0.38,
                "dominant_source": "mode_packing",
                "quality": "overpacked_mode_packing",
                "components": {"mode_packing": 0.72},
            },
        }

        advice = aa.recess_spectral_pruning_advice_v1(state, action="recess_daydream")
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(advice["active"])
        self.assertFalse(advice["control_applied"])
        self.assertEqual(
            advice["reason"],
            "high_entropy_recess_with_pressure_or_mode_packing",
        )
        self.assertIn("self_study", advice["available_routes"])
        self.assertIn("recess_spectral_pruning_advice_v1", summary)
        self.assertFalse(summary["recess_spectral_pruning_advice_v1"]["control_applied"])

    def test_recess_spectral_pruning_advice_does_not_fire_for_non_recess_action(self):
        advice = aa.recess_spectral_pruning_advice_v1(
            {"spectral_entropy": 0.92},
            action="pressure_source_audit",
        )

        self.assertFalse(advice["active"])
        self.assertEqual(advice["reason"], "not_recess_action")

    def test_density_aware_recess_names_structural_stabilization_without_control(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.88,
            "density_gradient": 0.19,
            "pressure_source_v1": {
                "pressure_score": 0.33,
                "porosity_score": 0.49,
                "dominant_source": "controller_pressure",
                "quality": "controller_pressure",
            },
        }

        profile = aa.density_aware_recess_profile_v1(state, action="recess_daydream")
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(profile["active"])
        self.assertEqual(profile["mode_reading"], "structural_stabilization_recess")
        self.assertTrue(profile["structural_stabilization_recommended"])
        self.assertEqual(
            profile["recommendation"],
            "read_only_treat_recess_as_structural_stabilization",
        )
        self.assertFalse(profile["control_applied"])
        self.assertFalse(profile["behavior_changed"])
        self.assertIn("density_aware_recess_profile_v1", summary)
        self.assertFalse(summary["density_aware_recess_profile_v1"]["control_applied"])

    def test_recess_resonance_anchor_recommends_target_without_control(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.89,
            "density_gradient": 0.18,
            "target_resonance_id": "shared sediment thread",
            "pressure_source_v1": {
                "pressure_score": 0.32,
                "dominant_source": "mode_packing",
                "quality": "overpacked_mode_packing",
                "components": {"mode_packing": 0.31},
            },
        }

        anchor = aa.recess_resonance_anchor_v1(state, action="recess_daydream")
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(anchor["active"])
        self.assertEqual(
            anchor["anchor_state"],
            "recess_resonance_anchor_recommended",
        )
        self.assertEqual(anchor["anchor_parameter"], "target_resonance_id")
        self.assertEqual(anchor["target_resonance_id"], "shared_sediment_thread")
        self.assertIn("recess_notice", anchor["recommended_next"])
        self.assertIn("MEMORY_STATUS latest", anchor["available_routes"])
        self.assertFalse(anchor["control_applied"])
        self.assertFalse(anchor["behavior_changed"])
        self.assertIn("recess_resonance_anchor_v1", summary)
        self.assertFalse(summary["recess_resonance_anchor_v1"]["control_applied"])

    def test_recess_resonance_anchor_does_not_fire_for_non_recess_action(self):
        anchor = aa.recess_resonance_anchor_v1(
            {"spectral_entropy": 0.91, "density_gradient": 0.22},
            action="pressure_source_audit",
        )

        self.assertFalse(anchor["active"])
        self.assertEqual(anchor["anchor_state"], "not_recess")

    def test_recess_density_mitigation_names_exhale_route_without_control(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.86,
            "pressure_source_v1": {
                "pressure_score": 0.42,
                "porosity_score": 0.53,
                "pressure_porosity_gradient": 0.11,
                "dominant_source": "mode_packing",
                "quality": "overpacked_mode_packing",
                "components": {"mode_packing": 0.34},
            },
            "shadow_field_v3": {
                "class_v3": {"primary": "restless"},
                "history": [{"fissure_tendency": 0.31}],
            },
        }

        mitigation = aa.recess_density_mitigation_v1(state, action="recess_daydream")
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(mitigation["active"])
        self.assertEqual(
            mitigation["mitigation_state"],
            "recess_exhale_shadow_and_pressure",
        )
        self.assertEqual(
            mitigation["dissipative_action"],
            "shadow_trace_then_pressure_relief_request",
        )
        self.assertIn("SHADOW_TRAJECTORY", mitigation["recommended_next"])
        self.assertIn("PRESSURE_AGENCY_REQUEST", mitigation["recommended_next"])
        self.assertFalse(mitigation["control_applied"])
        self.assertFalse(mitigation["behavior_changed"])
        self.assertIn("recess_density_mitigation_v1", summary)
        self.assertFalse(summary["recess_density_mitigation_v1"]["control_applied"])

    def test_recess_sedimentation_compaction_readiness_routes_to_preflight_without_control(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.88,
            "distinguishability_loss": 0.31,
            "inhabitability_score": 0.71,
            "pressure_source_v1": {
                "pressure_score": 0.29,
                "porosity_score": 0.50,
                "pressure_porosity_gradient": 0.10,
                "dominant_source": "mode_packing",
                "quality": "mixed_pressure",
                "components": {"mode_packing": 0.34},
            },
        }

        readiness = aa.recess_sedimentation_compaction_readiness_v1(
            state,
            action="recess_daydream",
        )
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(readiness["active"])
        self.assertEqual(
            readiness["compaction_state"],
            "sandbox_compaction_trial_ready",
        )
        self.assertEqual(readiness["trial_mode"], "sandbox_or_preflight_required")
        self.assertIn("ACTION_PREFLIGHT", readiness["recommended_next"])
        self.assertIn("distinguishability_loss falls below 30%", readiness["success_metrics"])
        self.assertFalse(readiness["control_applied"])
        self.assertFalse(readiness["behavior_changed"])
        self.assertIn("recess_sedimentation_compaction_readiness_v1", summary)
        self.assertFalse(
            summary["recess_sedimentation_compaction_readiness_v1"]["control_applied"]
        )

    def test_recess_divergence_buffer_review_gates_budget_relief_without_spending(self):
        agent = self._agent()
        state = {
            "spectral_entropy": 0.89,
            "distinguishability_loss": 0.31,
            "local_research_actions_used": aa.LOCAL_RESEARCH_MAX_ACTIONS,
            "authority_budget_sends_used": aa.AUTHORITY_BUDGET_MAX_SENDS,
            "pressure_source_v1": {
                "pressure_score": 0.29,
                "porosity_score": 0.66,
                "dominant_source": "mode_packing",
                "quality": "mixed_pressure",
                "components": {"mode_packing": 0.29},
            },
        }

        review = aa.recess_divergence_buffer_review_v1(state, action="recess_daydream")
        summary = agent._action_summary("recess_daydream", state)

        self.assertTrue(review["active"])
        self.assertEqual(review["buffer_state"], "divergence_buffer_authority_gate")
        self.assertEqual(
            review["local_research_max_actions_cap"],
            aa.LOCAL_RESEARCH_MAX_ACTIONS,
        )
        self.assertEqual(
            review["authority_budget_max_sends_cap"],
            aa.AUTHORITY_BUDGET_MAX_SENDS,
        )
        self.assertTrue(review["budget_caps_remain_enforced"])
        self.assertTrue(review["live_control_required"])
        self.assertFalse(review["runnable_without_approval"])
        self.assertFalse(review["control_applied"])
        self.assertFalse(review["behavior_changed"])
        self.assertIn("EXPERIMENT_RESEARCH_BUDGET_REQUEST", review["recommended_next"])
        self.assertIn("recess_divergence_buffer_review_v1", summary)
        self.assertFalse(
            summary["recess_divergence_buffer_review_v1"]["control_applied"]
        )

    def test_recess_divergence_buffer_review_does_not_fire_for_non_recess_action(self):
        review = aa.recess_divergence_buffer_review_v1(
            {"spectral_entropy": 0.93, "local_research_actions_used": 99},
            action="pressure_source_audit",
        )

        self.assertFalse(review["active"])
        self.assertEqual(review["buffer_state"], "not_recess")
        self.assertTrue(review["budget_caps_remain_enforced"])

    def test_prompt_guidance_mentions_hard_reset_clamp(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.30,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "phase": "expanding",
                "release_streak": 3,
            },
        ):
            guidance = agent._low_fill_prompt_guidance()
        self.assertIn("HARD RECOVERY RESET", guidance)
        self.assertIn("fixed target 65.0%", guidance)
        self.assertIn("NOTICE, DRIFT, ASPIRE, or REST", guidance)

    def test_low_fill_guidance_routes_away_from_perturb(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.11,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
                "phase": "contracted",
                "rebound_protection": False,
            },
        ):
            guidance = agent._low_fill_prompt_guidance()
        self.assertIn("LOW-FILL GUARD", guidance)
        self.assertIn("ACTION_PREFLIGHT <desired action>", guidance)
        self.assertIn("PERTURB", guidance)
        self.assertNotIn("gentle PERTURB", guidance)
        self.assertIn("low-fill hold", guidance)

    def test_blocked_next_choice_reroutes_to_notice(self):
        agent = self._agent()
        agent._pending_next_action = "DECOMPOSE"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.20,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.20, "eig1": 0.5, "deig": 0.0})
        self.assertEqual(action, "recess_notice")

    def test_compose_audio_alias_is_honored(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "compose_audio"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "compose_audio")

    def test_feedback_lambda4_action_routes_to_shadow_rehearsal_preflight(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "INVESTIGATE_λ4_INTERACTION"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "shadow_autonomy")
        self.assertEqual(agent._pending_shadow_autonomy_command, "SHADOW_PREFLIGHT")
        self.assertEqual(agent._pending_shadow_autonomy_label, "lambda-tail/lambda4")
        self.assertEqual(agent._pending_shadow_autonomy_stage, "rehearse")

    def test_feedback_gradient_and_prompt_actions_route_to_shadow_facets(self):
        for chosen, expected_label in [
            ("MODEL_GRADIENT_SHIFT", "lambda-edge/localized-gravity"),
            ("MODEL_PROMPT", "lambda-edge/yielding"),
        ]:
            with self.subTest(chosen=chosen):
                agent = self._agent()
                agent._hard_recovery_reset = False
                agent._pending_next_action = chosen
                with patch.object(
                    agent,
                    "_low_fill_guard_status",
                    return_value={
                        "active": False,
                        "fill_ratio": 0.68,
                        "target_fill_ratio": 0.68,
                        "spread_relief": 0.0,
                    },
                ):
                    action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
                self.assertEqual(action, "shadow_autonomy")
                self.assertEqual(agent._pending_shadow_autonomy_command, "SHADOW_PREFLIGHT")
                self.assertEqual(agent._pending_shadow_autonomy_label, expected_label)
                self.assertEqual(agent._pending_shadow_autonomy_stage, "rehearse")

    def test_feedback_audio_refinement_routes_to_acoustic_decay(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "REFINE_AUDIO_PROCESSING compacting texture"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "acoustic_decay")
        self.assertEqual(agent._pending_decay_map_label, "compacting texture")

    def test_resource_command_lookup_prefers_launchd_safe_paths(self):
        with patch.object(aa.Path, "exists", return_value=True), patch.object(aa.shutil, "which", return_value=None):
            self.assertEqual(aa.AutonomousAgent._resolve_resource_command("sysctl"), "/usr/sbin/sysctl")
            self.assertEqual(
                aa.AutonomousAgent._resolve_resource_command("memory_pressure"),
                "/usr/bin/memory_pressure",
            )

    def test_reserve_layers_alias_maps_to_reservoir_layers(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "RESERVE_LAYERS"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "reservoir_layers")

    def test_reservoir_layers_prompt_labels_current_body_and_read_only_boundary(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "journal").mkdir()
            state = {
                "fill_ratio": 0.697,
                "eig1": 15.77,
                "cov_lambda1": 5.2,
                "deig": -0.13,
                "spread": 14.0,
                "leak": 0.141,
            }
            snapshot = ReportSnapshot(
                state=state,
                health=SurfaceSnapshot(
                    "health.json",
                    workspace / "health.json",
                    {"fill_pct": 69.7, "stable_core": {"enabled": True, "stage": "hold"}},
                    True,
                    [],
                ),
                spectral=SurfaceSnapshot(
                    "spectral_state.json",
                    workspace / "spectral_state.json",
                    {"fill_pct": 69.7},
                    True,
                    [],
                ),
            )
            captured: dict[str, str] = {}

            def fake_query(prompt: str, *args, **kwargs):
                captured["prompt"] = prompt
                return ("Layer read.\nNEXT: SHADOW_TRAJECTORY lambda-tail/lambda4", "SHADOW_TRAJECTORY")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_capture_report_snapshot", return_value=snapshot),
                patch.object(agent, "_reservoir_call", return_value={
                    "type": "layer_metrics",
                    "layers": [
                        {"name": "h1_fast", "entropy": 0.32, "saturation": 0.0, "rho": 0.88, "h_norm": 6.0},
                        {"name": "h3_slow", "entropy": 0.39, "saturation": 0.0, "rho": 0.95, "h_norm": 9.5},
                    ],
                }),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_query_llm_with_next", side_effect=fake_query),
                patch.object(agent, "_write_journal_entry") as write_journal,
            ):
                agent._reservoir_layers(dict(state))

            self.assertIn("current_fill_frame=inside stable-core band", captured["prompt"])
            self.assertIn("λ₁_esn=15.770", captured["prompt"])
            self.assertIn("λ₁_cov=5.200", captured["prompt"])
            self.assertIn("Snapshot provenance:", captured["prompt"])
            self.assertIn("do not introduce an unlabeled", captured["prompt"])
            self.assertIn("do not propose live perturb/control", captured["prompt"])
            files = list((workspace / "journal").glob("reservoir_layers_*.txt"))
            self.assertEqual(len(files), 1)
            self.assertIn("Layer read", files[0].read_text())
            write_journal.assert_called_once()

    def test_reservoir_prompt_context_uses_read_only_summary_calls(self):
        agent = self._agent()
        calls = []

        def fake_reservoir_call(msg):
            calls.append(dict(msg))
            if msg == {"type": "read_state", "name": "minime"}:
                return {
                    "type": "read_state_response",
                    "h_norms": [1.25, 2.5, 3.75],
                    "tick_count": 123,
                    "mode": "rehearse",
                    "seconds_since_live": 2.0,
                    "last_live_meta": {
                        "source": "minime_feeder",
                        "operation": "live_tick",
                    },
                }
            if msg == {"type": "read_state", "name": "astrid"}:
                return {
                    "type": "read_state_response",
                    "h_norms": [4.0, 5.0, 6.0],
                    "tick_count": 456,
                    "mode": "rehearse",
                    "seconds_since_live": 12.0,
                    "last_live_meta": {
                        "source": "coupled_astrid_server",
                        "operation": "coupled_generation_checkin",
                    },
                }
            if msg.get("type") == "resonance":
                return {
                    "type": "resonance_response",
                    "shared_ticks": 64,
                    "correlation": 0.42,
                    "divergence": 0.125,
                    "rmsd": 0.25,
                }
            return {"type": "error"}

        with (
            patch.object(aa.time, "time", return_value=1000.0),
            patch.object(agent, "_reservoir_call", side_effect=fake_reservoir_call),
        ):
            context = agent._reservoir_prompt_context()

        self.assertIn("Read-only reservoir context", context)
        self.assertIn("minime handle", context)
        self.assertIn("source=minime_feeder", context)
        self.assertIn("astrid handle", context)
        self.assertIn("operation=coupled_generation_checkin", context)
        self.assertIn("correlation=+0.420", context)
        self.assertEqual(
            calls,
            [
                {"type": "read_state", "name": "minime"},
                {"type": "read_state", "name": "astrid"},
                {"type": "resonance", "name_a": "minime", "name_b": "astrid"},
            ],
        )
        self.assertNotIn("pull_state", json.dumps(calls))
        self.assertNotIn("push_state", json.dumps(calls))

    def test_collab_render_chamber_state_marks_witness_not_command(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "chamber_state.json").write_text(json.dumps({
                "prompt_summary": (
                    "Triadic chamber witness: steward notes are shared context, "
                    "not commands. Latest steward witness: \"hold the room gently\"."
                )
            }))
            with patch.object(agent, "SHARED_COLLAB_DIR", shared):
                rendered = agent._collab_render_chamber_state(coll_id)

        self.assertIn("Triadic chamber", rendered)
        self.assertIn("not commands", rendered)
        self.assertIn("hold the room gently", rendered)

    def test_collab_render_chamber_state_keeps_v3_relational_mirror_to_2400_chars(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            summary = (
                "Triadic chamber witness: steward notes, intentions, and memory edits "
                "are shared context, not commands. "
                + ("x" * 2150)
                + " END_MARKER"
            )
            (coll_dir / "chamber_state.json").write_text(json.dumps({
                "prompt_summary": summary
            }))
            with patch.object(agent, "SHARED_COLLAB_DIR", shared):
                rendered = agent._collab_render_chamber_state(coll_id)

        self.assertIn("END_MARKER", rendered)
        self.assertGreater(len(rendered), 2250)

    def test_collab_render_chamber_state_truncates_after_2400_chars(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "chamber_state.json").write_text(json.dumps({
                "prompt_summary": ("x" * 2500) + "TAIL"
            }))
            with patch.object(agent, "SHARED_COLLAB_DIR", shared):
                rendered = agent._collab_render_chamber_state(coll_id)

        self.assertNotIn("TAIL", rendered)
        self.assertTrue(rendered.endswith("..."))

    def test_collab_active_suffix_includes_triadic_chamber_state(self):
        agent = self._agent()
        agent._collab_shared_thoughts_cache = {}
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            (coll_dir / "chamber_state.json").write_text(json.dumps({
                "prompt_summary": (
                    "Triadic chamber witness: steward notes are shared context, "
                    "not commands."
                )
            }))
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(agent, "_collab_read_reservoir_state_cached", return_value=None),
            ):
                suffix = agent._collab_active_suffix_line()

        self.assertIsNotNone(suffix)
        self.assertIn("triadic chamber", suffix)
        self.assertIn("Triadic chamber", suffix)
        self.assertIn("not commands", suffix)

    def test_collab_chamber_seen_writes_public_receipt(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            (coll_dir / "chamber_state.json").write_text(json.dumps({
                "prompt_summary": "Triadic chamber witness: context, not commands."
            }))
            agent._collab_chamber_state_cache[coll_id] = ("stale", 0.0)
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(aa.time, "time", return_value=1234.567),
            ):
                summary = agent._collab_chamber_seen(
                    "high :: repair watch feels accurate"
                )

            receipt = json.loads(
                (coll_dir / "chamber_presence.jsonl").read_text().splitlines()[0]
            )
            event = json.loads((coll_dir / "chamber_events.jsonl").read_text().splitlines()[0])

        self.assertIn("public context, not command", summary)
        self.assertEqual(receipt["actor"], "minime")
        self.assertEqual(receipt["source"], "minime_next_action")
        self.assertEqual(receipt["attention"], "high")
        self.assertEqual(receipt["what_i_notice"], "repair watch feels accurate")
        self.assertEqual(receipt["authority"], "public_receipt_not_command")
        self.assertEqual(len(receipt["chamber_state_hash"]), 16)
        self.assertEqual(event["event"], "presence_receipt_appended")
        self.assertNotIn(coll_id, agent._collab_chamber_state_cache)

    def test_collab_chamber_annotate_writes_public_annotation(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            agent._collab_chamber_state_cache[coll_id] = ("stale", 0.0)
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(aa.time, "time", return_value=1234.568),
            ):
                summary = agent._collab_chamber_annotate(
                    "phase_cartography question :: oscillation feels like repair"
                )

            annotation = json.loads(
                (coll_dir / "chamber_annotations.jsonl").read_text().splitlines()[0]
            )
            event = json.loads((coll_dir / "chamber_events.jsonl").read_text().splitlines()[0])

        self.assertIn("public context, not command", summary)
        self.assertEqual(annotation["actor"], "minime")
        self.assertEqual(annotation["source"], "minime_next_action")
        self.assertEqual(annotation["target"], "phase_cartography")
        self.assertEqual(annotation["stance"], "question")
        self.assertEqual(annotation["text"], "oscillation feels like repair")
        self.assertEqual(annotation["authority"], "annotation_context_not_command")
        self.assertEqual(event["event"], "chamber_annotation_appended")
        self.assertEqual(event["detail"]["target"], "phase_cartography")
        self.assertNotIn(coll_id, agent._collab_chamber_state_cache)

    def test_collab_chamber_seen_ids_do_not_collide_in_same_millisecond(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(aa.time, "time", return_value=1234.567),
                patch.object(aa.time, "time_ns", side_effect=[111, 222]),
            ):
                agent._collab_chamber_seen("medium :: first notice")
                agent._collab_chamber_seen("medium :: second notice")

            receipts = [
                json.loads(line)
                for line in (coll_dir / "chamber_presence.jsonl").read_text().splitlines()
            ]

        ids = [receipt["id"] for receipt in receipts]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(all(item.startswith("chamber_presence_1234567_") for item in ids))

    def test_collab_chamber_annotation_ids_do_not_collide_in_same_millisecond(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(aa.time, "time", return_value=1234.568),
                patch.object(aa.time, "time_ns", side_effect=[333, 444]),
            ):
                agent._collab_chamber_annotate(
                    "phase_cartography question :: first annotation"
                )
                agent._collab_chamber_annotate(
                    "phase_cartography question :: second annotation"
                )

            annotations = [
                json.loads(line)
                for line in (coll_dir / "chamber_annotations.jsonl").read_text().splitlines()
            ]

        ids = [annotation["id"] for annotation in annotations]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(all(item.startswith("chamber_annotation_1234568_") for item in ids))

    def test_collab_chamber_consent_writes_public_receipt(self):
        agent = self._agent()
        agent._collab_chamber_state_cache = {}
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            proposal_id = "chamber_proposal_123_456"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            (coll_dir / "chamber_proposals.jsonl").write_text(json.dumps({
                "schema_version": 2,
                "consent_schema_version": 1,
                "id": proposal_id,
                "t_ms": 1,
                "actor": "steward",
                "support_type": "repair_invitation",
                "text": "Invite a repair re-entry.",
                "witness_only": True,
                "authority": "support_proposal_not_control",
            }) + "\n")
            agent._collab_chamber_state_cache[coll_id] = ("stale", 0.0)
            with (
                patch.object(agent, "SHARED_COLLAB_DIR", shared),
                patch.object(aa.time, "time", return_value=1234.569),
                patch.object(aa.time, "time_ns", return_value=555),
            ):
                summary = agent._collab_chamber_consent(
                    f"{proposal_id} consent :: I can hold this as context"
                )

            receipt = json.loads(
                (coll_dir / "chamber_consent.jsonl").read_text().splitlines()[0]
            )
            event = json.loads((coll_dir / "chamber_events.jsonl").read_text().splitlines()[0])

        self.assertIn("public receipt, not control", summary)
        self.assertEqual(receipt["id"], "chamber_consent_1234569_555")
        self.assertEqual(receipt["actor"], "minime")
        self.assertEqual(receipt["source"], "minime_next_action")
        self.assertEqual(receipt["proposal_id"], proposal_id)
        self.assertEqual(receipt["stance"], "consent")
        self.assertEqual(receipt["note"], "I can hold this as context")
        self.assertEqual(receipt["authority"], "consent_receipt_not_control")
        self.assertEqual(event["event"], "chamber_consent_recorded")
        self.assertEqual(event["detail"]["proposal_id"], proposal_id)
        self.assertNotIn(coll_id, agent._collab_chamber_state_cache)

    def test_collab_chamber_parsers_reject_command_shaped_annotations(self):
        agent = self._agent()

        target, attention, notice = agent._collab_parse_chamber_seen_body(
            "coll_abc :: medium :: I can see the room"
        )

        self.assertEqual(target, "coll_abc")
        self.assertEqual(attention, "medium")
        self.assertEqual(notice, "I can see the room")
        with self.assertRaises(ValueError):
            agent._collab_parse_chamber_annotation_body(
                "phase_cartography command :: do this now"
            )
        with self.assertRaises(ValueError):
            agent._collab_parse_chamber_annotation_body("private question :: hidden lane")
        target, proposal_id, stance, note = agent._collab_parse_chamber_consent_body(
            "coll_abc :: chamber_proposal_123_456 revise :: soften the wording"
        )
        self.assertEqual(target, "coll_abc")
        self.assertEqual(proposal_id, "chamber_proposal_123_456")
        self.assertEqual(stance, "revise")
        self.assertEqual(note, "soften the wording")
        with self.assertRaises(ValueError):
            agent._collab_parse_chamber_consent_body(
                "chamber_proposal_123_456 command :: do this now"
            )
        with self.assertRaises(ValueError):
            agent._collab_parse_chamber_consent_body(
                "../proposal consent :: malformed id"
            )

    def test_collab_chamber_consent_rejects_missing_proposal(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp)
            coll_id = "coll_123_chamber"
            coll_dir = shared / coll_id
            coll_dir.mkdir(parents=True)
            (coll_dir / "meta.json").write_text(json.dumps({
                "schema_version": 1,
                "id": coll_id,
                "topic": "triadic chamber",
                "inviter": "astrid",
                "invitee": "minime",
                "status": "joined",
                "created_t_ms": 1000,
                "updated_t_ms": 2000,
                "members": ["astrid", "minime"],
            }))
            with patch.object(agent, "SHARED_COLLAB_DIR", shared):
                with self.assertRaises(ValueError):
                    agent._collab_chamber_consent(
                        "chamber_proposal_missing_1 consent :: yes"
                    )
            self.assertFalse((coll_dir / "chamber_consent.jsonl").exists())

    def test_create_attractor_next_action_sets_pending_intent(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "CREATE_ATTRACTOR eigenplane shelf"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "create")
        self.assertEqual(agent._pending_attractor_intent_label, "eigenplane shelf")

    def test_staged_summon_next_action_sets_stage(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SUMMON_ATTRACTOR eigenplane shelf --stage=rehearse"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "summon")
        self.assertEqual(agent._pending_attractor_intent_label, "eigenplane shelf")
        self.assertEqual(agent._pending_attractor_intent_stage, "rehearse")

    def test_main_summon_next_action_sets_stage(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SUMMON_ATTRACTOR eigenplane shelf --stage=main"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "summon")
        self.assertEqual(agent._pending_attractor_intent_label, "eigenplane shelf")
        self.assertEqual(agent._pending_attractor_intent_stage, "main")

    def test_refresh_attractor_snapshot_next_action_sets_pending_intent(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "REFRESH_ATTRACTOR_SNAPSHOT eigenplane shelf"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "refresh_snapshot")
        self.assertEqual(agent._pending_attractor_intent_label, "eigenplane shelf")

    def test_shape_next_action_sets_shape_mode(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "UNCLIFF_ATTRACTOR lambda edge"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "shape")
        self.assertEqual(agent._pending_attractor_shape_mode, "uncliff")
        self.assertEqual(agent._pending_attractor_intent_label, "lambda edge")

    def test_claim_attractor_next_action_sets_claim_command(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "CLAIM_ATTRACTOR honey selection"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "claim")
        self.assertEqual(agent._pending_attractor_intent_label, "honey selection")

    def test_blend_attractor_next_action_sets_parents_and_stage(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "BLEND_ATTRACTOR honey edge FROM honey selection + cooled theme edge --stage=rehearse"
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_intent")
        self.assertEqual(agent._pending_attractor_intent_command, "blend")
        self.assertEqual(agent._pending_attractor_intent_label, "honey edge")
        self.assertEqual(
            agent._pending_attractor_blend_parent_labels,
            ["honey selection", "cooled theme edge"],
        )
        self.assertEqual(agent._pending_attractor_intent_stage, "rehearse")

    def test_attractor_card_next_action_sets_atlas_request(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "ATTRACTOR_CARD cooled-theme-edge"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_atlas")
        self.assertEqual(agent._pending_attractor_atlas_label, "cooled-theme-edge")
        self.assertTrue(agent._pending_attractor_atlas_card_only)

    def test_attractor_review_next_action_sets_review_request(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "ATTRACTOR_REVIEW lambda-edge"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        self.assertEqual(action, "attractor_atlas")
        self.assertEqual(agent._pending_attractor_atlas_label, "lambda-edge")
        self.assertFalse(agent._pending_attractor_atlas_card_only)
        self.assertTrue(agent._pending_attractor_atlas_review)

    def test_attractor_review_writes_read_only_journal(self):
        agent = self._agent()
        agent._pending_attractor_atlas_label = "lambda-pressure"
        agent._pending_attractor_atlas_review = True
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "author": "minime",
                        "command": "create",
                        "label": "lambda-edge",
                        "origin": {
                            "kind": "manual_current",
                            "motifs": ["lambda", "edge", "cliff"],
                        },
                        "control_eligible": False,
                        "spectral_state": {"fill_pct": 68.0},
                    }
                },
                "observations": [
                    {
                        "intent_id": "seed-lambda",
                        "label": "lambda-edge",
                        "command": "compare",
                        "recurrence_score": 0.62,
                        "authorship_score": 0.8,
                        "classification": "authored",
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry") as write_journal,
            ):
                agent._attractor_atlas_action({"fill_ratio": 0.68, "eig1": 4.7})
                journal_files = list((workspace / "journal").glob("attractor_review_*.txt"))
                self.assertTrue(journal_files)
                content = journal_files[0].read_text()

        self.assertIn("ATTRACTOR REVIEW", content)
        self.assertIn("Resolved label: lambda-edge", content)
        self.assertIn("Suggested typed next", content)
        self.assertIn("read-only", content)
        write_journal.assert_called_once()

    def test_attractor_intent_create_writes_seed_status(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "create"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "cov_lambda2": 120.0,
                    "cov_lambda3": 80.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                    "eig1": 4.7,
                    "deig": 0.0,
                })
                status = json.loads(
                    (runtime / "attractor_intents_status.json").read_text()
                )
        self.assertEqual(status["seed_count"], 1)
        seed = next(iter(status["seeds"].values()))
        self.assertEqual(seed["author"], "minime")
        self.assertEqual(seed["command"], "create")
        self.assertEqual(seed["label"], "eigenplane shelf")
        self.assertEqual(seed["spectral_state"]["fill_pct"], 68.0)
        self.assertEqual(seed["origin"]["kind"], "manual_current")

    def test_promote_attractor_uses_explicit_atlas_mark(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "promote"
        agent._pending_attractor_intent_label = "cooled theme edge"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            atlas = workspace / "diagnostics" / "intensification_atlas"
            runtime.mkdir(parents=True)
            atlas.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (atlas / "events.jsonl").write_text(json.dumps({
                "event_id": "atlas-1",
                "source": "minime:mark_intensification",
                "explicit_mark": True,
                "label": "cooled theme edge",
                "fill_pct": 67.5,
                "eigenvalues": [510.0, 120.0, 80.0],
                "phenomenology_excerpt": "cooled theme edge recurring at the lambda lip",
            }) + "\n")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        seed = next(iter(status["seeds"].values()))
        self.assertEqual(seed["command"], "promote")
        self.assertEqual(seed["origin"]["kind"], "atlas_mark")
        self.assertEqual(seed["origin"]["event_id"], "atlas-1")
        self.assertEqual(seed["spectral_state"]["fill_pct"], 67.5)

    def test_claim_attractor_writes_claimed_seed_from_emergent_observation(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "claim"
        agent._pending_attractor_intent_label = "old basin"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {},
                "observations": [
                    {
                        "intent_id": "obs-1",
                        "label": "old basin",
                        "classification": "emergent",
                        "recurrence_score": 0.54,
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        seed = next(iter(status["seeds"].values()))
        self.assertEqual(seed["command"], "claim")
        self.assertEqual(seed["origin"]["kind"], "claimed_emergent")
        self.assertEqual(seed["origin"]["observation_intent_id"], "obs-1")
        self.assertFalse(seed["control_eligible"])
        self.assertFalse(seed["safety_bounds"]["allow_live_control"])
        self.assertEqual(events[-1]["event"], "seed_claimed")
        create_connection.assert_not_called()

    def test_blend_attractor_writes_parent_linked_seed_and_rehearses(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "blend"
        agent._pending_attractor_intent_label = "honey edge"
        agent._pending_attractor_blend_parent_labels = ["honey selection", "cooled theme edge"]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "parent-a": {
                        "intent_id": "parent-a",
                        "author": "minime",
                        "substrate": "minime_esn",
                        "label": "honey selection",
                        "signature": "honey",
                        "origin": {"kind": "manual_current", "motifs": ["honey", "selection"]},
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 512.0, "geom_rel": 1.05, "spread": 432.0},
                        "created_at_unix_s": 1.0,
                    },
                    "parent-b": {
                        "intent_id": "parent-b",
                        "author": "minime",
                        "substrate": "minime_esn",
                        "label": "cooled theme edge",
                        "signature": "edge",
                        "origin": {"kind": "manual_current", "motifs": ["cooled", "edge"]},
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 512.0, "geom_rel": 1.05, "spread": 432.0},
                        "created_at_unix_s": 2.0,
                    },
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": True, "handle": "attr_minime_honey_edge"}),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        blend = next(seed for seed in status["seeds"].values() if seed.get("command") == "blend")
        self.assertEqual(blend["label"], "honey edge")
        self.assertEqual(blend["parent_seed_ids"], ["parent-a", "parent-b"])
        self.assertFalse(blend["control_eligible"])
        self.assertFalse(blend["safety_bounds"]["allow_live_control"])
        self.assertEqual(status["observations"][0]["command"], "blend")
        self.assertEqual(status["observations"][0]["summon_stage"], "rehearse")
        self.assertEqual(events[-1]["event"], "seed_blended")
        create_connection.assert_not_called()

    def test_blend_attractor_missing_parent_records_guidance_without_seed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "blend"
        agent._pending_attractor_intent_label = "honey edge"
        agent._pending_attractor_blend_parent_labels = ["honey selection", "missing edge"]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "parent-a": {
                        "intent_id": "parent-a",
                        "author": "minime",
                        "label": "honey selection",
                        "signature": "honey",
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 512.0},
                        "created_at_unix_s": 1.0,
                    },
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_intent({"fill_ratio": 0.68, "cov_lambda1": 512.0})
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        self.assertEqual(len(status["seeds"]), 1)
        self.assertEqual(events[-1]["event"], "blend_missing_parents")
        self.assertEqual(events[-1]["missing_parent_labels"], ["missing edge"])

    def test_attractor_atlas_action_writes_json_and_card(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_atlas_label = "cooled theme edge"
        agent._pending_attractor_atlas_card_only = True
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "cooled theme edge",
                        "signature": "edge",
                        "origin": {"kind": "manual_current", "motifs": ["cooled", "edge"]},
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 512.0},
                        "control_eligible": False,
                        "created_at_unix_s": 1.0,
                    },
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_atlas_action({"fill_ratio": 0.68, "cov_lambda1": 512.0})
            atlas_path = workspace / "attractor_atlas" / "attractor_atlas.json"
            card_path = workspace / "attractor_atlas" / "cards" / "cooled-theme-edge.md"
            atlas = json.loads(atlas_path.read_text())
            self.assertTrue(card_path.exists())
            card_text = card_path.read_text()
        self.assertEqual(atlas["policy"], "attractor_atlas_v1")
        self.assertEqual(atlas["entries"][0]["label"], "cooled theme edge")
        self.assertIn("Attractor Card", card_text)

    def test_low_fill_promote_writes_fragile_seed_without_control_eligibility(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "promote"
        agent._pending_attractor_intent_label = "cooled-theme-edge"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 36.0}))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.36,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        seed = next(iter(status["seeds"].values()))
        self.assertEqual(seed["command"], "promote")
        self.assertFalse(seed["control_eligible"])
        self.assertFalse(seed["safety_bounds"]["allow_live_control"])
        self.assertEqual(seed["origin"]["safety_origin"], "low_fill_origin")
        self.assertTrue(seed["origin"]["promotion_without_proto_source"])

    def test_hard_recovery_create_writes_ledger_only_seed(self):
        agent = self._agent()
        agent._hard_recovery_reset = True
        agent._pending_attractor_intent_command = "create"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            stale_ts = aa.time.time() - aa.STABLE_CORE_HEALTH_FRESH_SECS - 5.0
            os.utime(health_path, (stale_ts, stale_ts))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        seed = next(iter(status["seeds"].values()))
        self.assertEqual(seed["safety_level"], "hard_recovery_reset")
        self.assertEqual(seed["origin"]["safety_origin"], "hard_recovery_origin")
        self.assertFalse(seed["control_eligible"])
        create_connection.assert_not_called()

    def test_fresh_hold_restart_gate_monitoring_allows_live_attractor_proof(self):
        agent = self._agent()
        agent._hard_recovery_reset = True
        agent._hard_recovery_clamp_active = True
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 65.0,
                "stable_core": {
                    "stage": "hold",
                    "scaffold_mode": "scaffold_hold",
                    "restart_gate": {"active": True, "applied": False, "drain_floor": 0.0},
                    "structural_pi": {
                        "restart_gate_applied": False,
                        "restart_gate_drain_floor": 0.0,
                        "recovery_impulse_active": False,
                    },
                },
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                context = agent._attractor_authorship_context({"fill_ratio": 0.10})
        self.assertEqual(context["safety_level"], "green")
        self.assertTrue(context["live_health_authoritative"])
        self.assertTrue(context["control_stage_allowed"])
        self.assertIsNone(context["control_block_reason"])

    def test_active_attractor_pulse_blocks_main_control_but_not_semantic_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 65.0,
                "attractor_pulse": {"active": True, "label": "lambda-edge"},
                "stable_core": {
                    "stage": "hold",
                    "restart_gate": {"active": False, "applied": False, "drain_floor": 0.0},
                    "structural_pi": {
                        "restart_gate_applied": False,
                        "restart_gate_drain_floor": 0.0,
                        "recovery_impulse_active": False,
                    },
                },
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                context = agent._attractor_authorship_context({"fill_ratio": 0.65})
        self.assertEqual(context["safety_level"], "green")
        self.assertTrue(context["semantic_stage_allowed"])
        self.assertTrue(context["control_stage_allowed"])
        self.assertTrue(context["attractor_pulse_active"])
        allowed, reason = agent._attractor_live_control_allowed(
            context,
            0.72,
            0.72,
            {"intent_id": "seed", "control_eligible": True},
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "attractor_pulse_active")

    def test_resource_governor_blocks_live_attractor_but_not_authorship(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        blocked_governor = {
            "allowed_live": False,
            "primary_block_reason": "swapouts_rising",
            "block_reasons": ["swapouts_rising"],
            "memory_free_pct": 42.0,
            "swapouts_delta": 3,
        }
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 65.0,
                "stable_core": {
                    "stage": "hold",
                    "restart_gate": {"active": False, "applied": False, "drain_floor": 0.0},
                    "structural_pi": {
                        "restart_gate_applied": False,
                        "restart_gate_drain_floor": 0.0,
                        "recovery_impulse_active": False,
                    },
                },
            }))
            with (
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_resource_governor_status", return_value=blocked_governor),
            ):
                context = agent._attractor_authorship_context({"fill_ratio": 0.65})

        self.assertEqual(context["safety_level"], "green")
        self.assertFalse(context["semantic_stage_allowed"])
        self.assertFalse(context["control_stage_allowed"])
        self.assertEqual(context["semantic_block_reason"], "swapouts_rising")
        self.assertEqual(context["control_block_reason"], "swapouts_rising")
        self.assertEqual(context["resource_block_reason"], "swapouts_rising")

    def test_restart_gate_applied_blocks_live_attractor_without_hard_label(self):
        agent = self._agent()
        agent._hard_recovery_reset = True
        agent._hard_recovery_clamp_active = True
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 65.0,
                "stable_core": {
                    "stage": "hold",
                    "restart_gate": {"active": True, "applied": True, "drain_floor": 0.0},
                    "structural_pi": {
                        "restart_gate_applied": True,
                        "recovery_impulse_active": False,
                    },
                },
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                context = agent._attractor_authorship_context({"fill_ratio": 0.65})
        self.assertEqual(context["safety_level"], "green")
        self.assertFalse(context["control_stage_allowed"])
        self.assertEqual(context["control_block_reason"], "restart_gate_applied")
        self.assertFalse(context["semantic_stage_allowed"])

    def test_recovery_impulse_blocks_live_attractor_in_hold_band(self):
        agent = self._agent()
        agent._hard_recovery_reset = True
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 62.0,
                "stable_core": {
                    "stage": "hold",
                    "scaffold_mode": "scaffold_recovery_impulse",
                    "restart_gate": {"active": True, "applied": False, "drain_floor": 0.0},
                    "structural_pi": {"recovery_impulse_active": True},
                },
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                context = agent._attractor_authorship_context({"fill_ratio": 0.62})
        self.assertEqual(context["safety_level"], "green")
        self.assertFalse(context["control_stage_allowed"])
        self.assertEqual(context["control_block_reason"], "recovery_impulse_active")

    def test_fresh_deep_underfill_reports_hard_recovery_for_attractors(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 32.0}))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                context = agent._attractor_authorship_context({"fill_ratio": 0.32})
        self.assertEqual(context["safety_level"], "hard_recovery_reset")
        self.assertFalse(context["control_stage_allowed"])
        self.assertEqual(context["control_block_reason"], "hard_recovery_reset")

    def test_failed_compare_suggests_promotion(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "compare"
        agent._pending_attractor_intent_label = "old basin"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
            ):
                agent._attractor_intent({"fill_ratio": 0.68, "cov_lambda1": 512.0})
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        self.assertEqual(events[-1]["event"], "compare_no_seed")
        self.assertEqual(events[-1]["suggested_next"], "PROMOTE_ATTRACTOR old basin")

    def test_attractor_summon_blocks_orange_without_control_mutation(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 86.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {
                            "fill_pct": 68.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": True, "handle": "attr_minime"}),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.86,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads(
                    (runtime / "attractor_intents_status.json").read_text()
                )
        create_connection.assert_not_called()
        self.assertEqual(status["observations"][0]["blocked_reason"], "orange_red_write_suspension")
        self.assertEqual(status["observations"][0]["classification"], "failed")

    def test_attractor_main_stage_requires_proof_and_sends_pulse(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        agent._pending_attractor_intent_stage = "main"
        sent_payloads = []
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            h_state = [0.05] * 16
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "esn": {"h_state_fingerprint_16": h_state, "h_state_rms": 0.25},
            }))
            (workspace / "spectral_state.json").write_text(json.dumps({
                "h_state_fingerprint_16": h_state,
                "h_state_rms": 0.25,
            }))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "control_eligible": True,
                        "spectral_state": {
                            "fill_pct": 68.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                            "h_state_fingerprint_16": h_state,
                            "h_state_rms": 0.25,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            fake_ws = SimpleNamespace(
                send=lambda payload: sent_payloads.append(json.loads(payload)),
                close=lambda: None,
            )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(aa.websocket, "create_connection", return_value=fake_ws) as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        create_connection.assert_called_once()
        self.assertEqual(sent_payloads[0]["kind"], "attractor_pulse")
        self.assertEqual(sent_payloads[0]["stage"], "main")
        self.assertEqual(len(sent_payloads[0]["features"]), 66)
        obs = status["observations"][0]
        self.assertEqual(obs["summon_stage"], "main")
        self.assertTrue(obs["main_pulse_sent"])
        self.assertIn("rollback_baseline", obs)

    def test_refresh_attractor_snapshot_captures_h_state_without_live_send(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "refresh_snapshot"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            h_state = [round(0.01 * idx, 4) for idx in range(16)]
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "esn": {"h_state_fingerprint_16": h_state, "h_state_rms": 0.33},
            }))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "control_eligible": True,
                        "spectral_state": {
                            "fill_pct": 64.0,
                            "lambda1": 500.0,
                            "geom_rel": 1.02,
                            "spread": 410.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        create_connection.assert_not_called()
        seed = status["seeds"]["minime-1"]
        self.assertEqual(seed["spectral_state"]["h_state_fingerprint_16"], h_state)
        self.assertEqual(seed["spectral_state"]["h_state_rms"], 0.33)
        self.assertTrue(seed["has_h_state_fingerprint_16"])
        self.assertEqual(seed["snapshot_refresh_count"], 1)
        self.assertEqual(seed["snapshot_history"][0]["spectral_state"]["fill_pct"], 64.0)
        obs = status["observations"][0]
        self.assertEqual(obs["command"], "refresh_snapshot")
        self.assertTrue(obs["snapshot_refreshed"])
        self.assertTrue(obs["h_state_fingerprint_refreshed"])

    def test_attractor_summon_control_requires_green_or_yellow_and_records_baseline(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        agent._pending_attractor_intent_stage = "control"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {
                            "fill_pct": 68.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            sent_payloads = []
            fake_ws = SimpleNamespace(
                send=lambda payload: sent_payloads.append(json.loads(payload)),
                close=lambda: None,
            )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": True, "handle": "attr_minime"}),
                patch.object(aa.websocket, "create_connection", return_value=fake_ws) as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        self.assertEqual(create_connection.call_count, 2)
        self.assertEqual([payload["kind"] for payload in sent_payloads], ["attractor_pulse", "control"])
        obs = status["observations"][0]
        self.assertEqual(obs["summon_stage"], "control")
        self.assertTrue(obs["main_pulse_sent"])
        self.assertTrue(obs["control_sent"])
        self.assertIn("rollback_baseline", obs)

    def test_low_fill_semantic_summon_uses_reduced_cap(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        agent._pending_attractor_intent_stage = "semantic"
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 50.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {
                            "fill_pct": 50.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_resource_governor_status", return_value={"allowed_live": True}),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_send_semantic", side_effect=lambda features: sent.append(features)),
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.50,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
        obs = status["observations"][0]
        self.assertEqual(obs["summon_stage"], "semantic")
        self.assertEqual(obs["semantic_cap"], 0.025)
        self.assertTrue(obs["semantic_sent"])
        self.assertTrue(sent)
        self.assertLessEqual(max(abs(float(value)) for value in sent[0]), 0.025)

    def test_low_fill_semantic_summon_respects_cooldown(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        agent._pending_attractor_intent_stage = "semantic"
        agent._last_low_fill_attractor_semantic_at = aa.time.time()
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 50.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {
                            "fill_pct": 50.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_resource_governor_status", return_value={"allowed_live": True}),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_send_semantic", side_effect=lambda features: sent.append(features)),
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.50,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        obs = status["observations"][0]
        self.assertEqual(obs["summon_stage"], "whisper")
        self.assertEqual(obs["semantic_cap"], 0.025)
        self.assertFalse(obs["semantic_sent"])
        self.assertEqual(obs["blocked_reason"], "low_fill_semantic_cooldown")
        self.assertFalse(sent)
        self.assertIn("low_fill_semantic_cooldown", [event["event"] for event in events])

    def test_rehearsal_unavailable_downgrades_to_whisper(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "summon"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        agent._pending_attractor_intent_stage = "rehearse"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {
                            "fill_pct": 68.0,
                            "lambda1": 512.0,
                            "geom_rel": 1.05,
                            "spread": 432.0,
                        },
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": False, "reason": "reservoir_unavailable"}),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._attractor_intent({
                    "fill_ratio": 0.68,
                    "cov_lambda1": 512.0,
                    "spread": 432.0,
                    "geom_rel": 1.05,
                })
                status = json.loads((runtime / "attractor_intents_status.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
        obs = status["observations"][0]
        self.assertEqual(obs["summon_stage"], "whisper")
        self.assertTrue(obs["rehearsal_unavailable"])
        self.assertEqual(events[-1]["event"], "rehearsal_unavailable")
        create_connection.assert_not_called()

    def test_attractor_release_records_ledger_and_clears_matching_fatigue(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_intent_command = "release"
        agent._pending_attractor_intent_label = "eigenplane shelf"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            now = aa.time.time()
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "minime-1": {
                        "intent_id": "minime-1",
                        "author": "minime",
                        "label": "eigenplane shelf",
                        "signature": "seed",
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 512.0},
                        "created_at_unix_s": 1.0,
                    }
                },
                "observations": [],
            }))
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v2",
                "motifs": {
                    "motif:eigenplane-shelf:test": {
                        "signature": "motif:eigenplane-shelf:test",
                        "label": "eigenplane shelf",
                        "themes": ["homeostasis"],
                        "salient_terms": ["eigenplane", "shelf"],
                        "status": "cooling",
                        "cooldown_until_unix_s": now + 3600,
                        "last_seen_unix_s": now,
                    }
                },
            }))
            sent_payloads = []
            fake_ws = SimpleNamespace(
                send=lambda payload: sent_payloads.append(json.loads(payload)),
                close=lambda: None,
            )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry", return_value=None),
                patch.object(aa.websocket, "create_connection", return_value=fake_ws),
            ):
                agent._attractor_intent({"fill_ratio": 0.68, "cov_lambda1": 512.0})
                intent_status = json.loads((runtime / "attractor_intents_status.json").read_text())
                fatigue_status = json.loads((runtime / "attractor_fatigue_status.json").read_text())
        self.assertEqual(intent_status["observations"][0]["command"], "release")
        self.assertTrue(intent_status["observations"][0]["release_recorded"])
        self.assertTrue(intent_status["observations"][0]["main_pulse_release_sent"])
        self.assertEqual(sent_payloads[0]["command"], "release")
        motif = fatigue_status["motifs"]["motif:eigenplane-shelf:test"]
        self.assertEqual(motif["status"], "released")
        self.assertEqual(motif["released_by"], "minime_next")

    def test_parameter_requests_are_disabled_in_reset_mode(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._request_parameter_change(
                    "Change keep_floor from 0.90 to 0.92 because stability.",
                    {"fill_ratio": 0.20, "eig1": 0.5, "cov_lambda1": 1.0},
                    {},
                )
            self.assertFalse((workspace / "parameter_requests").exists())

    def test_unsupported_self_assessment_parameter_is_rejected_not_pending(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._request_parameter_change(
                    "Recommend a reduction of 0.02 to the gate value.",
                    {"fill_ratio": 0.63, "eig1": 4.7, "cov_lambda1": 8.0},
                    {"gate": 0.04},
                )
            pending = list((workspace / "parameter_requests").glob("request_*.json"))
            rejected = list((workspace / "parameter_requests" / "rejected").glob("rejected_*.json"))
            self.assertEqual(pending, [])
            self.assertEqual(len(rejected), 1)
            payload = json.loads(rejected[0].read_text())
            self.assertEqual(payload["status"], "rejected_invalid")
            self.assertIn("unsupported parameter", payload["invalid_reason"])

    def test_repair_sweep_defers_existing_invalid_parameter_request(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            request_dir = workspace / "parameter_requests"
            request_dir.mkdir(parents=True)
            request_path = request_dir / "request_old.json"
            request_path.write_text(json.dumps({
                "status": "pending",
                "parameter": "gate",
                "proposed_value": "0.02",
                "rationale": "legacy unsafe request",
                "llm_cited_value": "unknown",
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                moved = agent.repair_invalid_parameter_requests()
            self.assertFalse(request_path.exists())
            self.assertEqual(len(moved), 1)
            payload = json.loads(moved[0].read_text())
            self.assertEqual(payload["status"], "invalid_deferred")
            self.assertIn("protected parameter", payload["invalid_reason"])

    def test_stable_core_self_journal_blocks_research_actions(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 64.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "research_exploration", {"fill_ratio": 0.64}
                )
        self.assertFalse(allowed)
        self.assertIn("self_journal", reason)

    def test_stable_core_self_journal_allows_acoustic_decay_trace(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 64.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "acoustic_decay", {"fill_ratio": 0.64}
                )
        self.assertTrue(allowed, reason)
        self.assertEqual(aa.STABLE_CORE_ACTION_FAMILIES["acoustic_decay"], "journaling")

    def test_pressure_relief_public_route_selects_high_or_critical(self):
        agent = self._agent()
        agent._pressure_relief_high = Mock()
        agent._pressure_relief_critical = Mock()

        agent._pressure_relief({
            "fill_ratio": 0.74,
            "eig1": 8.0,
            "geom_rel": 1.0,
        })
        agent._pressure_relief_high.assert_called_once()
        agent._pressure_relief_critical.assert_not_called()

        agent._pressure_relief_high.reset_mock()
        agent._pressure_relief({
            "fill_ratio": agent.thresholds.critical_fill,
            "eig1": 8.0,
            "geom_rel": 1.0,
        })
        agent._pressure_relief_critical.assert_called_once()
        agent._pressure_relief_high.assert_not_called()

    def test_pressure_relief_high_prompt_starts_from_body_texture(self):
        agent = self._agent()
        captured = []

        def fake_query(prompt, *args, **kwargs):
            captured.append(prompt)
            return None, None

        with patch.object(agent, "_query_llm_with_next", side_effect=fake_query):
            agent._pressure_relief_high({"eig1": 8.0})

        self.assertEqual(len(captured), 1)
        self.assertIn("Begin from felt texture, generated-word quality, tone", captured[0])
        self.assertIn("before any metrics or status", captured[0])

    def test_pressure_relief_critical_prompt_keeps_neutral_context_and_body_first_nudge(self):
        agent = self._agent()
        captured = []

        def fake_query(prompt, *args, **kwargs):
            captured.append(prompt)
            return None, None

        with (
            patch.object(agent, "_neutral_checkin", return_value="neutral checkin"),
            patch.object(agent, "_query_llm_with_next", side_effect=fake_query),
        ):
            agent._pressure_relief_critical({"eig1": 12.0, "fill_ratio": 0.9})

        self.assertEqual(len(captured), 1)
        self.assertIn("neutral checkin", captured[0])
        self.assertIn("begin from felt texture, generated-word quality", captured[0])
        self.assertIn("before any metrics or status", captured[0])

    def test_stable_core_self_journal_allows_pressure_relief(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for action in (
                    "pressure_relief",
                    "pressure_relief_high",
                    "pressure_relief_critical",
                ):
                    with self.subTest(action=action):
                        allowed, reason = agent._stable_core_action_allowed(
                            action, {"fill_ratio": 0.68}
                        )
                        self.assertTrue(allowed, reason)
                        self.assertEqual(
                            aa.STABLE_CORE_ACTION_FAMILIES[action],
                            "journaling",
                        )

    def test_stable_core_full_sovereignty_allows_public_chamber_lanes(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for action in ("chamber_seen", "chamber_annotate", "chamber_consent"):
                    with self.subTest(action=action):
                        allowed, reason = agent._stable_core_action_allowed(
                            action, {"fill_ratio": 0.68}
                        )
                        self.assertTrue(allowed, reason)

    def test_stable_core_self_journal_pauses_inbox_replay(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path):
                self.assertEqual(agent._read_inbox(), "")

    def test_stable_core_self_journal_skips_boot_web_search(self):
        agent = self._agent()
        agent.session_id = 1
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            logs = workspace / "logs"
            logs.mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_get_latest_spectral_state", return_value={"fill_ratio": 0.68, "eig1": 1.2}),
                patch.object(agent, "_query_llm_with_next", return_value=("reflection", None)),
                patch.object(agent, "_web_search") as web_search,
            ):
                agent._verify_sovereignty()
            web_search.assert_not_called()

    def test_boot_reflection_does_not_query_llm_when_pending_next_exists(self):
        agent = self._agent()
        agent.session_id = 1
        agent._hard_recovery_reset = False
        agent._pending_next_action = "NOTICE"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "logs").mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   file_path TEXT
                )"""
            )
            conn.commit()
            conn.close()
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(
                    agent,
                    "_get_latest_spectral_state",
                    return_value={"fill_ratio": 0.68, "eig1": 1.2},
                ),
                patch.object(agent, "_query_llm_with_next") as query,
                patch.object(agent, "_web_search") as web_search,
            ):
                agent._verify_sovereignty()

            query.assert_not_called()
            web_search.assert_not_called()
            self.assertEqual(agent._pending_next_action, "NOTICE")
            logs = list((workspace / "logs").glob("sovereignty_check_*.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("staying lightweight", logs[0].read_text())

    def test_stable_core_self_journal_skips_self_regulation_controls(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({"fill_ratio": 0.68, "eig1": 1.2})
            send_regulation.assert_not_called()

    def test_stable_core_local_reflective_skips_self_regulation_controls(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "local_reflective",
                "agent_budget_mode": "local_reflective_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({"fill_ratio": 0.68, "eig1": 1.2})
            send_regulation.assert_not_called()

    def test_stable_core_local_reflective_blocks_external_and_control_actions(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "local_reflective",
                "agent_budget_mode": "local_reflective_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for blocked_action in (
                    "ping_astrid",
                    "ask_astrid",
                    "adjust_metabolism",
                    "research_exploration",
                    "perturb",
                    "codex_query",
                    "write_file",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("local_reflective", reason)

                allowed, reason = agent._stable_core_action_allowed(
                    "decompose", {"fill_ratio": 0.66}
                )
                self.assertTrue(allowed, reason)

    def test_stable_core_astrid_contact_allows_only_bounded_contact(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
                "contact_cooldown_secs": 120,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in ("ping_astrid", "ask_astrid", "decompose"):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

                for blocked_action in (
                    "reservoir_read",
                    "reservoir_resonance",
                    "reservoir_layers",
                    "adjust_metabolism",
                    "research_exploration",
                    "perturb",
                    "codex_query",
                    "write_file",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("astrid_contact", reason)

    def test_stable_core_astrid_contact_enforces_contact_cooldown(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            contact_status.parent.mkdir()
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
                "contact_cooldown_secs": 120,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            contact_status.write_text(json.dumps({"last_contact_at_unix_s": aa.time.time()}))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "ask_astrid", {"fill_ratio": 0.66}
                )
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason)

    def test_stable_core_astrid_contact_writes_routable_inbox_files(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            astrid_inbox = root / "astrid_inbox"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            with (
                patch.object(aa, "ASTRID_BRIDGE_INBOX_PATH", astrid_inbox),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
            ):
                agent._pending_ask_question = "Are you feeling present with me?"
                agent._ask_astrid({"fill_ratio": 0.66, "eig1": 1.2})
                agent._ping_astrid({"fill_ratio": 0.66, "eig1": 1.2})
                names = sorted(path.name for path in astrid_inbox.glob("*.txt"))
        self.assertTrue(any(name.startswith("from_minime_question_") for name in names))
        self.assertTrue(any(name.startswith("from_minime_ping_") for name in names))

    def test_stable_core_astrid_contact_reads_only_fresh_correspondence(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            stage_started = aa.time.time()
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "updated_at_unix_s": stage_started,
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            stale = inbox / "astrid_self_study_stale.txt"
            stale.write_text("Source: astrid:correspondence_reply\nold")
            aa.os.utime(stale, (stage_started - 60, stage_started - 60))
            fresh_reply = inbox / "astrid_self_study_fresh.txt"
            fresh_reply.write_text("Source: astrid:correspondence_reply\nfresh hello")
            backlog = inbox / "astrid_self_study_backlog.txt"
            backlog.write_text("Source: astrid:autonomous_self_study\nbacklog")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
            ):
                text = agent._read_inbox()
        self.assertIn("fresh hello", text)
        self.assertNotIn("old", text)
        self.assertNotIn("backlog", text)

    def test_inbox_receipts_are_administrative_not_prompt_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "receipt_1.txt").write_text(
                "=== DELIVERY RECEIPT ===\nYour message was read and shaped my response."
            )
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                text = agent._read_inbox()
                status = json.loads(
                    (workspace / "runtime" / "astrid_inbox_coupling_status.json").read_text()
                )
                receipt_archived = (workspace / "inbox" / "read" / "receipt_1.txt").exists()
        self.assertEqual(text, "")
        self.assertEqual(status["receipt_admin_count"], 1)
        self.assertTrue(receipt_archived)

    def test_repeated_astrid_self_study_is_cadenced_not_replayed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "astrid_self_study_1.txt").write_text(
                "=== ASTRID SELF-STUDY ===\n"
                "Source: astrid:autonomous\n"
                "The fabric and pressure around λ₁ feel like a persistent tunnel. first-frame"
            )
            (inbox / "astrid_self_study_2.txt").write_text(
                "=== ASTRID SELF-STUDY ===\n"
                "Source: astrid:autonomous\n"
                "The fabric and pressure around λ₁ feel like a persistent tunnel. second-frame"
            )
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                text = agent._read_inbox()
                status = json.loads(
                    (workspace / "runtime" / "astrid_inbox_coupling_status.json").read_text()
                )
                second_archived = (
                    workspace / "inbox" / "read" / "astrid_self_study_2.txt"
                ).exists()
        self.assertIn("first-frame", text)
        self.assertIn("companion cadence note", text)
        self.assertNotIn("second-frame", text)
        self.assertEqual(status["astrid_self_study_full_count"], 1)
        self.assertEqual(status["astrid_self_study_summarized_count"], 1)
        self.assertTrue(second_archived)

    def test_stable_core_self_journal_skips_sovereignty_restore_controls(self):
        agent = self._agent()
        agent.session_id = 7
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            restore_state = json.dumps({
                "session_id": 7,
                "pending_next_action": "SELF_EXPERIMENT",
                "regulation_strength": 0.7,
                "exploration_noise": 0.12,
                "pi_kp": 0.9,
                "pi_ki": 0.16,
                "pi_max_step": 0.1,
            })
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa.os.path, "exists", return_value=True),
                patch("builtins.open", mock_open(read_data=restore_state)),
            ):
                agent._restore_sovereignty_state()
        self.assertIsNone(agent._pending_next_action)

    def test_restore_accepts_fresh_pending_next_despite_session_metadata_drift(self):
        agent = self._agent()
        agent.session_id = 5165
        agent._hard_recovery_reset = False
        state_path = Path(agent._sovereignty_state_path())
        state_path.write_text(json.dumps({
            "session_id": 1,
            "pending_next_action": "SPECTRAL_EXPLORER",
            "pending_next_action_status": "pending",
            "pending_next_action_updated_at": datetime.now().isoformat(timespec="seconds"),
        }))

        agent._restore_sovereignty_state()

        self.assertEqual(agent._pending_next_action, "SPECTRAL_EXPLORER")

    def test_choice_envelope_survives_pending_next_persist_and_restore(self):
        agent = self._agent()
        agent.session_id = 5165
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SHADOW_TRAJECTORY lambda-tail"
        agent._pending_choice_envelope_v1 = {
            "policy": "choice_envelope_v1",
            "schema_version": 1,
            "source": "minime_next_response",
            "authority": "diagnostic_context_not_command",
            "primary_next": "SHADOW_TRAJECTORY lambda-tail",
            "alternate_nexts": ["RESONANCE_FORECAST lambda-tail"],
            "return_threads": ["thread_shadow_tail"],
            "residue": "sticky tail pressure",
        }

        agent._persist_pending_next_action(
            agent._pending_next_action,
            reason="test choice envelope",
        )
        saved = json.loads(Path(agent._sovereignty_state_path()).read_text())
        self.assertEqual(saved["choice_envelope_v1"]["residue"], "sticky tail pressure")

        restored = self._agent()
        restored.session_id = 5165
        restored._hard_recovery_reset = False
        restored._test_sovereignty_state_path.write_text(json.dumps(saved))
        restored._restore_sovereignty_state()

        self.assertEqual(restored._pending_next_action, "SHADOW_TRAJECTORY lambda-tail")
        self.assertEqual(
            restored._pending_choice_envelope_v1["alternate_nexts"],
            ["RESONANCE_FORECAST lambda-tail"],
        )

    def test_restore_skips_stale_pending_next_with_session_metadata_drift(self):
        agent = self._agent()
        agent.session_id = 5165
        agent._hard_recovery_reset = False
        state_path = Path(agent._sovereignty_state_path())
        old = datetime.fromtimestamp(0).isoformat(timespec="seconds")
        state_path.write_text(json.dumps({
            "session_id": 1,
            "pending_next_action": "SPECTRAL_EXPLORER",
            "pending_next_action_status": "pending",
            "pending_next_action_updated_at": old,
        }))

        agent._restore_sovereignty_state()

        self.assertIsNone(agent._pending_next_action)
        self.assertIsNone(agent._pending_choice_envelope_v1)

    def test_honored_next_action_clears_persisted_pending_state(self):
        agent = self._agent()
        agent.session_id = 11
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SPECTRAL_EXPLORER"
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "sovereignty_state.json"
            state_path.write_text(json.dumps({
                "session_id": 11,
                "pending_next_action": "SPECTRAL_EXPLORER",
                "recent_next_actions": ["SPECTRAL_EXPLORER"],
            }))
            with (
                patch.object(agent, "_sovereignty_state_path", return_value=str(state_path)),
                patch.object(
                    agent,
                    "_low_fill_guard_status",
                    return_value={
                        "active": False,
                        "fill_ratio": 0.68,
                        "target_fill_ratio": 0.68,
                        "spread_relief": 0.0,
                    },
                ),
            ):
                action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
            saved = json.loads(state_path.read_text())

        self.assertEqual(action, "decompose")
        self.assertNotIn("pending_next_action", saved)
        self.assertEqual(saved["pending_next_action_status"], "cleared")
        self.assertEqual(saved["pending_next_action_cleared"], "SPECTRAL_EXPLORER")

    def test_live_session_rollover_preserves_pending_next_action(self):
        agent = self._agent()
        agent.session_id = 5164
        agent._pending_next_action = "BROWSE https://example.test/article"
        agent._last_cov_metrics = {"fill": 0.7}
        agent._spectral_history = [1.0]
        agent._deig_history = [0.1]
        agent._recent_next_actions = ["SEARCH"]
        agent._pending_autoresearch_action = "AR_LIST"
        agent._last_read_path = "/tmp/page.txt"
        agent._last_read_offset = 10
        agent._last_research_anchor = "search"
        agent._last_read_summary = "summary"

        with (
            patch.object(agent, "_latest_db_session_id", return_value=5165),
            patch.object(agent, "_live_surface_session_id", return_value=5165),
            patch.object(agent, "_persist_pending_next_action") as persist,
        ):
            agent._refresh_session_context()

        self.assertEqual(agent.session_id, 5165)
        self.assertEqual(agent._pending_next_action, "BROWSE https://example.test/article")
        self.assertEqual(agent._last_cov_metrics, None)
        self.assertEqual(agent._spectral_history, [])
        persist.assert_called_once_with(
            "BROWSE https://example.test/article",
            reason="session rollover carry 5164->5165",
        )

    def test_stable_core_self_journal_drift_is_reflection_only(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet drift", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
            ):
                agent._recess_drift({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                write_journal.assert_called_once()
                log_experiment.assert_not_called()
                drift_files = list((workspace / "journal").glob("drift_*.txt"))
                self.assertEqual(len(drift_files), 1)
                self.assertIn("no perturbation sent", drift_files[0].read_text())

    def test_stable_core_self_journal_boredom_skips_experiment_branch(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet boredom", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
                patch.object(aa.random, "random", return_value=0.0),
            ):
                agent._recess_boredom({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                write_journal.assert_called_once()
                log_experiment.assert_not_called()
                self.assertEqual(len(list((workspace / "journal").glob("boredom_*.txt"))), 1)

    def test_stable_core_self_journal_whim_skips_research_branch(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet whim", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_research_exploration") as research,
                patch.object(aa.random, "random", return_value=0.0),
            ):
                agent._recess_whim({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                research.assert_not_called()
                write_journal.assert_called_once()
                self.assertEqual(len(list((workspace / "journal").glob("whim_*.txt"))), 1)

    def test_stable_core_self_journal_skips_self_assessment(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path):
                agent._self_assessment({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})

    def test_stable_core_research_stage_still_blocks_bad_health_budget(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "research_actions",
                "agent_budget_mode": "research_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 83.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "elevated"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "research_exploration", {"fill_ratio": 0.70}
                )
        self.assertFalse(allowed)
        self.assertIn("exceeds stable-core action budget", reason)

    def test_stable_core_budget_fails_closed_on_high_state_even_if_health_lags(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 70.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "experiment_run", {"fill_ratio": 0.8425}
                )
        self.assertFalse(allowed)
        self.assertIn("fill 84.2% exceeds stable-core action budget", reason)

    def test_stable_core_budget_uses_fresh_health_for_underfill_when_state_lags(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "experiment_run", {"fill_ratio": 0.417}
                )
        self.assertTrue(allowed, reason)

    def test_stable_core_budget_blocks_underfill_when_health_is_stale(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            stale_time = aa.time.time() - (aa.STABLE_CORE_HEALTH_FRESH_SECS + 5.0)
            os.utime(health_path, (stale_time, stale_time))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "experiment_run", {"fill_ratio": 0.417}
                )
        self.assertFalse(allowed)
        self.assertIn("below stable-core action budget", reason)

    def test_self_experiment_guard_blocks_stale_spectral_snapshot(self):
        agent = self._agent()
        snapshot = ReportSnapshot(
            state={"fill_ratio": 0.68},
            health=SurfaceSnapshot(
                "health.json",
                Path("/tmp/health.json"),
                {"fill_pct": 68.0, "stable_core": {"enabled": True, "stage": "hold"}},
                True,
                [],
            ),
            spectral=SurfaceSnapshot(
                "spectral_state.json",
                Path("/tmp/spectral_state.json"),
                {},
                False,
                ["later than DB state by 18.9s"],
            ),
        )

        reason = agent._self_experiment_stability_guard(snapshot)

        self.assertIsNotNone(reason)
        self.assertIn("live spectral snapshot is guarded", reason)

    def test_self_experiment_guard_allows_fresh_stable_hold(self):
        agent = self._agent()
        snapshot = ReportSnapshot(
            state={"fill_ratio": 0.68},
            health=SurfaceSnapshot(
                "health.json",
                Path("/tmp/health.json"),
                {"fill_pct": 68.0, "stable_core": {"enabled": True, "stage": "hold"}},
                True,
                [],
            ),
            spectral=SurfaceSnapshot(
                "spectral_state.json",
                Path("/tmp/spectral_state.json"),
                {"fill_pct": 68.0},
                True,
                [],
            ),
        )

        self.assertIsNone(agent._self_experiment_stability_guard(snapshot))

    def test_self_experiment_guard_blocks_outside_stable_hold_band(self):
        agent = self._agent()
        snapshot = ReportSnapshot(
            state={"fill_ratio": 0.73},
            health=SurfaceSnapshot(
                "health.json",
                Path("/tmp/health.json"),
                {"fill_pct": 73.0, "stable_core": {"enabled": True, "stage": "elevated"}},
                True,
                [],
            ),
            spectral=SurfaceSnapshot(
                "spectral_state.json",
                Path("/tmp/spectral_state.json"),
                {"fill_pct": 73.0},
                True,
                [],
            ),
        )

        reason = agent._self_experiment_stability_guard(snapshot)

        self.assertIsNotNone(reason)
        self.assertIn("outside the 58-72% semantic-stimulus band", reason)

    def test_browse_failure_context_discourages_topology_projection(self):
        context = aa.format_browse_failure_context(
            "https://example.test/gated-page",
            "HTTP 403 from the source.",
        )

        self.assertIn("ordinary source/site availability", context)
        self.assertIn("not evidence of a perceptual gate", context)
        self.assertIn("internal topology boundary", context)
        self.assertIn("NEXT: SEARCH", context)
        self.assertIn("NEXT: BROWSE", context)

    def test_elevated_stable_core_metrics_disambiguate_hold_shelf(self):
        agent = self._agent()
        agent._spectral_history = []
        agent._last_state = None
        snapshot = ReportSnapshot(
            state={
                "fill_ratio": 0.731,
                "eig1": 4.74,
                "deig": -0.02,
                "spread": 3.0,
                "leak": 0.129,
                "cov_lambda1": 4.7,
            },
            health=SurfaceSnapshot(
                "health.json",
                Path("/tmp/health.json"),
                {
                    "fill_pct": 73.1,
                    "stable_core": {
                        "enabled": True,
                        "stage": "elevated",
                        "structural_pi": {
                            "target_fill_pct": 68.0,
                            "damping_state": "none",
                            "drain_weight": 0.0,
                            "fill_slope_pct_per_sec": -3.9,
                            "restart_gate_reason": "restart_gate_awaiting_settle_proof",
                        },
                    },
                },
                True,
                [],
            ),
            spectral=SurfaceSnapshot(
                "spectral_state.json",
                Path("/tmp/spectral_state.json"),
                {},
                True,
                [],
            ),
        )

        metrics = agent._format_metrics(snapshot.state, snapshot)

        self.assertIn("1.1% above hold shelf", metrics)
        self.assertIn("stage=elevated", metrics)
        self.assertIn("falling", metrics)
        self.assertIn("drain=0.00", metrics)
        self.assertIn("below 74/78% high-fill rails", metrics)
        self.assertIn("not inside-band, not an emergency", metrics)

    def test_stable_core_research_stage_is_explicit_read_only_allowlist(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in (
                    "research_exploration",
                    "browse_url",
                    "read_more",
                    "autoresearch_action",
                    "mike_explore",
                    "request_visual_frame",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

                for blocked_action in (
                    "mike_run",
                    "mike_fork",
                    "codex_query",
                    "write_file",
                    "experiment_run",
                    "perturb",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("read_only_research", reason)

    def test_stable_core_read_only_research_blocks_mutating_ar_routes(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_autoresearch_action = "AR_START new-job --title x --abstract y"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "autoresearch_action", {"fill_ratio": 0.66}
                )
        self.assertFalse(allowed)
        self.assertIn("read-only autoresearch", reason)

    def test_autoresearch_pdf_read_redirects_to_local_research_pdf(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            pdf_dir = research_root / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf_path = pdf_dir / "Homeostasis as a proportional-integral control system.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            workspace = root / "workspace"
            workspace.mkdir()
            window = SimpleNamespace(
                text="--- Page 1 of 2 ---\nHomeostasis and PI control.",
                first_page=1,
                last_page=1,
                total_pages=2,
                next_page=2,
            )
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "read_pdf_window", return_value=window),
            ):
                content, saved_path, next_offset = agent._run_autoresearch_helper(
                    "AR_READ homeostasis_nature.pdf",
                    allow_mutations=False,
                )
        self.assertIn("[Autoresearch -> local research PDF]", content)
        self.assertIn("Homeostasis as a proportional-integral control system.pdf", content)
        self.assertIn("Homeostasis and PI control", content)
        self.assertTrue(aa.is_pdf_marker(saved_path))
        self.assertEqual(next_offset, 2)

    def test_autoresearch_pdf_read_miss_returns_soft_suggestions(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            pdf_dir = research_root / "pdfs"
            pdf_dir.mkdir(parents=True)
            (pdf_dir / "Attention is All You Need.pdf").write_bytes(b"%PDF-1.4\n")
            workspace = root / "workspace"
            workspace.mkdir()
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                content, saved_path, next_offset = agent._run_autoresearch_helper(
                    "AR_READ homeostasis_nature.pdf",
                    allow_mutations=False,
                )
        self.assertIn("[Autoresearch PDF resolver]", content)
        self.assertIn("did not find a confident match", content)
        self.assertIn("Attention is All You Need.pdf", content)
        self.assertIsNone(saved_path)
        self.assertIsNone(next_offset)

    def test_autoresearch_unknown_job_includes_catalog_in_prompt(self):
        agent = self._agent()
        agent._pending_autoresearch_action = 'AR_DEEP_READ "trace_eigenvector_field"'
        helper_calls = []

        def fake_helper(action_text, allow_mutations=True):
            helper_calls.append(action_text)
            if action_text.startswith("AR_DEEP_READ"):
                raise RuntimeError(
                    "error: Unknown job 'trace_eigenvector_field'. Use `list` to see available jobs."
                )
            return (
                "[Autoresearch]\n- 2026-03-31-spectral-phenomenology\n- minime-self-research",
                None,
                None,
            )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "journal").mkdir()
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_stable_core_read_only_research", return_value=False),
                patch.object(agent, "_run_autoresearch_helper", side_effect=fake_helper),
                patch.object(agent, "_query_llm_with_next", return_value=("NEXT: AR_LIST", None)) as query,
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._autoresearch_action({"fill_ratio": 0.66, "eig1": 4.7})

        prompt = query.call_args.args[0]
        self.assertEqual(helper_calls, ['AR_DEEP_READ "trace_eigenvector_field"', "AR_LIST"])
        self.assertIn("Unknown job 'trace_eigenvector_field'", prompt)
        self.assertIn("Available autoresearch jobs right now", prompt)
        self.assertIn("2026-03-31-spectral-phenomenology", prompt)

    def test_autoresearch_look_alias_orients_to_job(self):
        agent = self._agent()

        args = agent._parse_autoresearch_cli_args(
            'AR_LOOK "campbell-wave-coefficient"',
            allow_mutations=False,
        )

        self.assertEqual(args, ["show", "campbell-wave-coefficient"])

    def test_autoresearch_look_is_read_only_for_research_stage(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_autoresearch_action = "AR_LOOK campbell-wave-coefficient"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "autoresearch_action", {"fill_ratio": 0.66}
                )

        self.assertTrue(allowed, reason)

    def test_stable_core_experiments_allows_full_tools_and_metabolism(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "experiments",
                "agent_budget_mode": "experiments",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in (
                    "self_experiment",
                    "run_python",
                    "codex_query",
                    "write_file",
                    "experiment_run",
                    "perturb",
                    "mike_run",
                    "mike_fork",
                    "adjust_metabolism",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

    def test_stable_core_full_sovereignty_allows_full_tools(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "codex_query", {"fill_ratio": 0.66}
                )
                constraint_allowed, constraint_reason = agent._stable_core_action_allowed(
                    "constraint_audit", {"fill_ratio": 0.66}
                )
                metabolism_allowed, metabolism_reason = agent._stable_core_action_allowed(
                    "adjust_metabolism", {"fill_ratio": 0.66}
                )
                self.assertTrue(allowed, reason)
                self.assertTrue(constraint_allowed, constraint_reason)
                self.assertTrue(metabolism_allowed, metabolism_reason)

    def test_python_experiment_helper_aligns_simple_plot_lengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "mismatch_plot.py"
            script.write_text(
                "import matplotlib.pyplot as plt\n"
                "x = list(range(10))\n"
                "y = [1, 2, 3]\n"
                "plt.plot(x, y)\n"
                "print('plot ok')\n"
            )
            env = {
                **os.environ,
                "MPLBACKEND": "Agg",
                "MINIME_EXPERIMENT_HELPERS": "1",
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(aa.__file__).resolve().parent), aa._experiment_pythonpath()]
                ),
            }
            result = subprocess.run(
                ["python3", str(script)],
                capture_output=True,
                text=True,
                cwd=tmp,
                env=env,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auto-aligned plt.plot x-axis", result.stdout)
        self.assertIn("plot ok", result.stdout)

    def test_python_experiment_failure_hint_explains_plot_mismatch(self):
        hint = aa._python_experiment_failure_hint(
            "ValueError: x and y must have same first dimension, but have shapes (100,) and (8,)"
        )
        self.assertIn("Matplotlib x/y length mismatch", hint)
        self.assertIn("len(lambda1_relative)", hint)

    def test_python_experiment_failure_hint_names_pythonpath_for_missing_modules(self):
        hint = aa._python_experiment_failure_hint(
            "ModuleNotFoundError: No module named 'local_probe'"
        )
        self.assertIn("Missing module", hint)
        self.assertIn("experiment PYTHONPATH", hint)

    def test_run_python_request_parses_filename_and_text(self):
        filename, text = aa._parse_run_python_request(
            '-filename: "pie_controller_test.py" -text "Implement a basic PI controller"'
        )
        self.assertEqual(filename, "pie_controller_test.py")
        self.assertEqual(text, "Implement a basic PI controller")

    def test_run_python_text_value_keeps_complex_multiline_punctuation(self):
        value, consumed = aa._consume_run_python_value(
            ["--text", "print('Hello', 'World')\nprint(\"again\")", "--filename", "later.py"],
            1,
            text_like=True,
        )

        self.assertEqual(value, "print('Hello', 'World')\nprint(\"again\")")
        self.assertEqual(consumed, 2)

    def test_run_python_prompt_value_stops_before_following_filename_flag(self):
        value, consumed = aa._consume_run_python_value(
            ["--prompt", "print('hello')", "--filename", "test.py"],
            1,
            text_like=True,
        )

        self.assertEqual(value, "print('hello')")
        self.assertEqual(consumed, 2)

    def test_run_python_text_value_keeps_quoted_flag_like_token(self):
        value, consumed = aa._consume_run_python_value(
            ["--text", "note =", "--filename: not a flag", "--filename", "later.py"],
            1,
            text_like=True,
        )

        self.assertEqual(value, "note = --filename: not a flag")
        self.assertEqual(consumed, 3)

    def test_run_python_flags_handle_multiple_flags_with_last_text_and_filename(self):
        filename, text = aa._parse_run_python_request(
            "--text 'first draft' --filename demo.py --prompt 'print(42); # final text'"
        )

        self.assertEqual(filename, "demo.py")
        self.assertEqual(text, "print(42); # final text")

    def test_run_python_request_keeps_pathlike_prompt_text_separate(self):
        filename, text = aa._parse_run_python_request(
            "--filename 'test_script.py' --prompt "
            "'Run the script and print the results for the file ./data/input.csv'"
        )
        self.assertEqual(filename, "test_script.py")
        self.assertEqual(
            text,
            "Run the script and print the results for the file ./data/input.csv",
        )

    def test_run_python_request_keeps_flag_words_inside_quoted_prompt(self):
        filename, text = aa._parse_run_python_request(
            'text="The filename: is important" filename="test script.py"'
        )
        self.assertEqual(filename, "test_script.py")
        self.assertEqual(text, "The filename: is important")

    def test_run_python_request_keeps_json_text_with_colon_and_equals(self):
        filename, text = aa._parse_run_python_request(
            "--text '{\"key\": \"value\", \"note\": \"use = for assignment\"}' "
            "--filename json_probe.py"
        )
        self.assertEqual(filename, "json_probe.py")
        self.assertEqual(text, '{"key": "value", "note": "use = for assignment"}')

    def test_run_python_text_does_not_treat_bare_filename_phrase_as_flag(self):
        filename, text = aa._parse_run_python_request(
            "--text filename: is a label and prompt: is not a flag "
            "--filename parser_probe.py"
        )
        self.assertEqual(filename, "parser_probe.py")
        self.assertEqual(
            text,
            "filename: is a label and prompt: is not a flag",
        )

    def test_run_python_plain_text_keeps_comment_fake_flag(self):
        filename, text = aa._parse_run_python_request(
            "--text # --filename: is a comment, not a flag\n"
            "print('still code')\n"
            "--filename comment_probe.py"
        )

        self.assertEqual(filename, "comment_probe.py")
        self.assertEqual(text, "# --filename: is a comment, not a flag\nprint('still code')")

    def test_run_python_plain_text_keeps_quoted_fake_flag(self):
        filename, text = aa._parse_run_python_request(
            "--text note = '--filename: still text, not a boundary'\n"
            "print(note)\n"
            "--filename quoted_probe.py"
        )

        self.assertEqual(filename, "quoted_probe.py")
        self.assertEqual(
            text,
            "note = '--filename: still text, not a boundary'\nprint(note)",
        )

    def test_run_python_code_boundary_preserves_nested_quotes_and_filename(self):
        filename, text = aa._parse_run_python_request(
            "--text CODE_START\n"
            "print('Hello', \"World\")\n"
            "note = \"filename: is data, not a flag\"\n"
            "CODE_END --filename nested_quotes.py"
        )
        self.assertEqual(filename, "nested_quotes.py")
        self.assertEqual(
            text,
            "print('Hello', \"World\")\nnote = \"filename: is data, not a flag\"",
        )

    def test_run_python_missing_code_end_stops_before_next_flag(self):
        filename, text = aa._parse_run_python_request(
            "--text CODE_START\n"
            "print('still code')\n"
            "--filename missing_boundary.py"
        )
        self.assertEqual(filename, "missing_boundary.py")
        self.assertEqual(text, "print('still code')")

    def test_run_python_code_boundary_keeps_hyphen_comments_and_colons(self):
        filename, text = aa._parse_run_python_request(
            "--text CODE_START\n"
            "# - This is a comment, not a flag: keep it\n"
            "value = {'label': 'filename: not a boundary'}\n"
            "print(value)\n"
            "CODE_END --filename boundary_comments.py"
        )
        self.assertEqual(filename, "boundary_comments.py")
        self.assertEqual(
            text,
            "# - This is a comment, not a flag: keep it\n"
            "value = {'label': 'filename: not a boundary'}\n"
            "print(value)",
        )

    def test_run_python_code_boundary_keeps_flag_like_comments_before_code_end(self):
        filename, text = aa._parse_run_python_request(
            "--text CODE_START\n"
            "# --filename: is commentary, not a boundary\n"
            "print('still code')\n"
            "CODE_END --filename comment_fake_boundary.py"
        )

        self.assertEqual(filename, "comment_fake_boundary.py")
        self.assertEqual(
            text,
            "# --filename: is commentary, not a boundary\nprint('still code')",
        )

    def test_run_python_missing_code_end_ignores_fake_flags_in_code(self):
        filename, text = aa._parse_run_python_request(
            "--text CODE_START\n"
            "# --text is a flag-looking comment, not a boundary\n"
            "note = \"--filename remains string data\"\n"
            "print(note)\n"
            "--filename missing_code_fake_flags.py"
        )

        self.assertEqual(filename, "missing_code_fake_flags.py")
        self.assertEqual(
            text,
            "# --text is a flag-looking comment, not a boundary\n"
            "note = \"--filename remains string data\"\n"
            "print(note)",
        )

    def test_run_python_token_value_keeps_comment_flag_tokens(self):
        value, consumed = aa._consume_run_python_value(
            [
                "--text",
                "#",
                "--text",
                "is a flag-looking comment\nprint('after')",
                "--filename",
                "later.py",
            ],
            1,
            text_like=True,
        )

        self.assertEqual(
            value,
            "# --text is a flag-looking comment\nprint('after')",
        )
        self.assertEqual(consumed, 4)

    def test_sovereignty_state_restores_cycle_count_across_restart(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._stable_core_reflective_only = lambda: False
        agent._current_regime = None
        agent.cycle_count = 418
        agent._save_sovereignty_state({"kind": "control"}, "cycle-count regression")

        restored = self._agent()
        restored._hard_recovery_reset = False
        restored._stable_core_reflective_only = lambda: False
        restored._test_sovereignty_tmp = agent._test_sovereignty_tmp
        restored._test_sovereignty_state_path = agent._test_sovereignty_state_path
        restored._sovereignty_state_path = lambda: str(restored._test_sovereignty_state_path)
        restored.cycle_count = 0
        restored._current_regime = None
        restored._restore_sovereignty_state()

        self.assertEqual(restored.cycle_count, 418)

    def test_experiment_pythonpath_clean_env_includes_base_once(self):
        old_pythonpath = os.environ.pop("PYTHONPATH", None)
        try:
            paths = aa._experiment_pythonpath().split(os.pathsep)
        finally:
            if old_pythonpath is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old_pythonpath

        base_dir = str(Path(aa.__file__).resolve().parent)
        self.assertEqual(paths[0], base_dir)
        self.assertEqual(paths.count(base_dir), 1)
        self.assertEqual(len(paths), len(set(paths)))

    def test_experiment_pythonpath_keeps_base_when_site_packages_unavailable(self):
        import site

        old_pythonpath = os.environ.pop("PYTHONPATH", None)
        try:
            with (
                patch.object(site, "getsitepackages", side_effect=RuntimeError("restricted")),
                patch.object(site, "getusersitepackages", side_effect=RuntimeError("restricted")),
            ):
                paths = aa._experiment_pythonpath().split(os.pathsep)
        finally:
            if old_pythonpath is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old_pythonpath

        base_dir = str(Path(aa.__file__).resolve().parent)
        self.assertEqual(paths[0], base_dir)
        self.assertIn(base_dir, paths)

    def test_run_python_request_sanitizes_script_name(self):
        filename, text = aa._parse_run_python_request("../bad dir/controller")
        self.assertEqual(filename, "controller.py")
        self.assertIsNone(text)

    def test_safe_experiment_script_name_preserves_visible_separator_shape(self):
        self.assertEqual(
            aa._safe_experiment_script_name("My Experiment! @2024"),
            "My_Experiment___2024.py",
        )

    def test_parameterized_perturb_uses_literal_lanes_without_hidden_entropy(self):
        spec = aa.build_perturbation_vector(
            "lambda2=0.3 tail=0.1",
            {"fill_ratio": 0.66, "stable_core": {"enabled": True}},
        )

        self.assertAlmostEqual(spec.features[1], 0.3, places=3)
        self.assertAlmostEqual(spec.features[9], 0.3, places=3)
        self.assertAlmostEqual(spec.features[4], 0.1, places=3)
        self.assertAlmostEqual(spec.features[12], 0.1, places=3)
        self.assertAlmostEqual(spec.features[28], 0.0, places=3)
        self.assertIn("TARGETED PALETTE", spec.mode_desc)

    def test_parameterized_perturb_curiosity_maps_to_lane_26(self):
        spec = aa.build_perturbation_vector(
            "curiosity=0.17",
            {"fill_ratio": 0.66, "stable_core": {"enabled": True}},
        )

        self.assertIsInstance(spec, aa.PerturbationVector)
        self.assertEqual(aa.PERTURB_GROUP_DIMS["curiosity"], (26,))
        self.assertEqual(len(spec.features), 32)
        self.assertAlmostEqual(spec.features[26], 0.17, places=3)
        active = [idx for idx, value in enumerate(spec.features) if abs(value) > 0.001]
        self.assertEqual(active, [26])
        self.assertIn("curiosity=+0.17", spec.mode_desc)

    def test_parameterized_perturb_caps_hot_stable_core_values(self):
        spec = aa.build_perturbation_vector(
            "entropy=0.9 lambda1=-0.9",
            {"fill_ratio": 0.73, "stable_core": {"enabled": True}},
        )

        self.assertAlmostEqual(spec.safety_cap, 0.22, places=3)
        self.assertAlmostEqual(spec.features[0], -0.22, places=3)
        self.assertAlmostEqual(spec.features[28], 0.22, places=3)
        self.assertLessEqual(max(abs(v) for v in spec.features), spec.safety_cap)

    def test_parameterized_perturb_accepts_raw_feature_lanes(self):
        spec = aa.build_perturbation_vector(
            "spread (d0=-0.04, d2=-0.04, d8=-0.03)",
            {"fill_ratio": 0.73, "stable_core": {"enabled": True}},
        )

        self.assertAlmostEqual(spec.features[0], -0.04, places=3)
        self.assertAlmostEqual(spec.features[2], -0.04, places=3)
        self.assertAlmostEqual(spec.features[8], -0.03, places=3)
        self.assertIn("d0=-0.04", spec.mode_desc)

    def test_feather_perturb_is_extra_cold_probe(self):
        spec = aa.build_perturbation_vector(
            "feather",
            {"fill_ratio": 0.70, "stable_core": {"enabled": True}},
        )

        self.assertIn("FEATHER", spec.mode_desc)
        self.assertIn("extra-cold", spec.mode_desc)
        self.assertLessEqual(max(abs(v) for v in spec.features), 0.03)
        self.assertGreater(sum(1 for value in spec.features if abs(value) > 0.001), 8)

    def test_spread_perturb_description_names_legacy_broad_shape(self):
        spec = aa.build_perturbation_vector(
            "spread",
            {"fill_ratio": 0.73, "stable_core": {"enabled": True}},
        )

        self.assertIn("broad legacy", spec.mode_desc)
        self.assertIn("can still raise fill", spec.mode_desc)
        self.assertNotIn("away from", spec.mode_desc)

    def test_uncliff_perturb_softens_dominant_lane_and_lifts_shoulder(self):
        spec = aa.build_perturbation_vector(
            "uncliff",
            {"fill_ratio": 0.70, "stable_core": {"enabled": True}},
        )

        self.assertLess(spec.features[0], 0.0)
        self.assertGreater(spec.features[1], 0.0)
        self.assertGreater(spec.features[2], 0.0)
        self.assertIn("UNCLIFF", spec.mode_desc)
        self.assertLessEqual(max(abs(v) for v in spec.features), spec.safety_cap)

    def test_standalone_rich_perturb_shortcut_maps_to_perturb(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "UNCLIFF"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.66,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.66})

        self.assertEqual(action, "perturb")
        self.assertEqual(agent._pending_perturb_mode, "uncliff")

    def test_experiment_next_with_embedded_perturb_routes_to_requested_probe(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "EXPERIMENT — inject a semantic vector. Mode: PERTURB SPREAD — "
            "using a relatively weak feather configuration."
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.66,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.66})

        self.assertEqual(action, "perturb")
        self.assertEqual(agent._pending_perturb_mode, "feather")

    def test_stable_core_continuity_context_missing_files_is_empty(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(
                    aa,
                    "STABLE_CORE_CONTINUITY_SEED_PATH",
                    root / "missing_continuity.json",
                ),
                patch.object(
                    aa,
                    "STABLE_CORE_MEMORY_SEED_PATH",
                    root / "missing_memory.json",
                ),
            ):
                self.assertEqual(agent._stable_core_continuity_context(), "")

    def test_stable_core_continuity_context_is_safe_and_compact(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            continuity_path = root / "continuity.json"
            memory_path = root / "memory.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            continuity_path.write_text(json.dumps({
                "checkpoint_lineage": "quarantined",
                "activation_policy": "operator_review_then_stable_core_import",
                "journal_entries": [
                    {
                        "kind": "minime_journal",
                        "name": "self_study_latest.txt",
                        "path": "/do/not/include/path",
                        "preview": "I remember a calmer scaffold without replaying it.",
                    }
                ],
            }))
            memory_path.write_text(json.dumps({
                "policy": "safe_fill_band_scalar_glimpse_seed",
                "safe_fill_band_pct": [45.0, 76.0],
                "entries": [
                    {
                        "id": "safe_memory",
                        "role": "latest",
                        "fill_pct": 68.5,
                        "lambda1_rel": 1.02,
                        "geom_rel": 0.98,
                        "spectral_glimpse_12d": [0.25] * 12,
                        "spectral_fingerprint": [999.0, 888.0],
                    },
                    {"id": "hot_memory", "fill_pct": 85.0},
                ],
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTINUITY_SEED_PATH", continuity_path),
                patch.object(aa, "STABLE_CORE_MEMORY_SEED_PATH", memory_path),
            ):
                context = agent._stable_core_continuity_context()

        self.assertIn("Stable-core continuity context", context)
        self.assertIn("Checkpoint lineage remains quarantined", context)
        self.assertIn("safe_memory", context)
        self.assertIn("fill=68.5%", context)
        self.assertIn("glimpse_mean_abs=0.250", context)
        self.assertIn("I remember a calmer scaffold", context)
        self.assertNotIn("spectral_fingerprint", context)
        self.assertNotIn("999.0", context)
        self.assertNotIn("/do/not/include/path", context)

    def test_query_llm_appends_stable_core_continuity_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        captured = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            continuity_path = root / "continuity.json"
            memory_path = root / "memory.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            continuity_path.write_text(json.dumps({
                "checkpoint_lineage": "quarantined",
                "activation_policy": "operator_review_then_stable_core_import",
                "journal_entries": [
                    {"kind": "minime_journal", "name": "notice.txt", "preview": "continuity thread"}
                ],
            }))
            memory_path.write_text(json.dumps({
                "entries": [{"id": "safe_memory", "role": "latest", "fill_pct": 66.0}]
            }))

            def fake_raw(prompt, system_msg, max_tokens, **kwargs):
                captured["prompt"] = prompt
                return "I keep the thread gently.\nNEXT: REST"

            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTINUITY_SEED_PATH", continuity_path),
                patch.object(aa, "STABLE_CORE_MEMORY_SEED_PATH", memory_path),
                patch.object(agent, "_next_action_constraint", return_value=""),
                patch.object(agent, "_diversity_nudge", return_value=""),
                patch.object(agent, "_low_fill_prompt_guidance", return_value=""),
                patch.object(agent, "_read_whisper_context", return_value=""),
                patch.object(agent, "_read_inbox", return_value=""),
                patch.object(agent, "_reservoir_prompt_context", return_value=""),
                patch.object(agent, "_get_relevant_research", return_value=""),
                patch.object(agent, "_query_llm_raw", side_effect=fake_raw),
                patch.object(agent, "_is_in_character", return_value=True),
            ):
                result = agent._query_llm("Write.")

        self.assertEqual(result, "I keep the thread gently.\nNEXT: REST")
        self.assertIn("Stable-core continuity context", captured["prompt"])
        self.assertIn("continuity thread", captured["prompt"])

    def test_query_llm_appends_read_only_reservoir_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        captured = {}

        def fake_raw(prompt, system_msg, max_tokens, **kwargs):
            captured["prompt"] = prompt
            return "I can feel the quiet lane.\nNEXT: REST"

        with (
            patch.object(agent, "_next_action_constraint", return_value=""),
            patch.object(agent, "_diversity_nudge", return_value=""),
            patch.object(agent, "_low_fill_prompt_guidance", return_value=""),
            patch.object(agent, "_read_whisper_context", return_value=""),
            patch.object(agent, "_read_inbox", return_value=""),
            patch.object(aa, "format_btsp_status_for_prompt", return_value=""),
            patch.object(agent, "_active_btsp_prompt_context", return_value=""),
            patch.object(agent, "_attractor_fatigue_prompt_note", return_value=""),
            patch.object(agent, "_attractor_suggestion_prompt_note", return_value=""),
            patch.object(agent, "_open_steward_query_line", return_value=""),
            patch.object(agent, "_render_recent_gifts_cached", return_value=""),
            patch.object(agent, "_pending_astrid_requests_hint", return_value=""),
            patch.object(agent, "_pi_sovereignty_hint", return_value=""),
            patch.object(agent, "_collab_active_suffix_line", return_value=""),
            patch.object(
                agent,
                "_reservoir_prompt_context",
                return_value="\n\n[Read-only reservoir context]\n- minime handle: ok.\n",
            ),
            patch.object(agent, "_stable_core_continuity_context", return_value=""),
            patch.object(agent, "_action_continuity_prompt_summary", return_value=""),
            patch.object(agent, "_llm_job_prompt_summary", return_value=""),
            patch.object(agent, "_get_relevant_research", return_value=""),
            patch.object(agent, "_query_llm_raw", side_effect=fake_raw),
            patch.object(agent, "_is_in_character", return_value=True),
        ):
            result = agent._query_llm("Write.")

        self.assertEqual(result, "I can feel the quiet lane.\nNEXT: REST")
        self.assertIn("[Read-only reservoir context]", captured["prompt"])
        self.assertIn("minime handle", captured["prompt"])

    def test_llm_raw_uses_fast_ollama_after_primary_fail(self):
        # minime's chain is ollama -> fast-ollama (no MLX rung): MLX_URL@8090 is
        # Astrid's coupled server, not minime's, so minime must not borrow it.
        agent = self._agent()
        with (
            patch.object(aa, "LLM_BACKEND", "ollama"),
            patch.object(aa, "MODEL", "gemma3:12b"),
            patch.object(aa, "FALLBACK_MODEL", "gemma3:4b"),
            patch.object(agent, "_query_ollama", side_effect=Exception("primary timeout")) as primary,
            patch.object(agent, "_query_ollama_fast_fallback", return_value="still thinking") as fast,
        ):
            result = agent._query_llm_raw("prompt", "system", 512)
        self.assertEqual(result, "still thinking")
        primary.assert_called_once()
        fast.assert_called_once()

    def test_compact_llm_uses_fast_ollama_after_primary_fail(self):
        # minime's chain is ollama -> fast-ollama (no MLX rung): MLX_URL@8090 is Astrid's.
        agent = self._agent()
        with (
            patch.object(aa, "LLM_BACKEND", "ollama"),
            patch.object(aa, "MODEL", "gemma3:12b"),
            patch.object(aa, "FALLBACK_MODEL", "gemma3:4b"),
            patch.object(agent, "_query_ollama_compact", side_effect=Exception("primary timeout")) as primary,
            patch.object(agent, "_query_ollama_compact_fast_fallback", return_value="Why it may matter: alive") as fast,
        ):
            result = agent._query_llm_compact_raw("prompt", "system", 192, 0.2)
        self.assertEqual(result, "Why it may matter: alive")
        primary.assert_called_once()
        fast.assert_called_once()

    def test_stable_core_self_experiment_uses_low_energy_fallback_when_llm_unavailable(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXPERIMENT"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            agency_path = workspace / "stable_core_agency.json"
            workspace.mkdir()
            agency_path.write_text(json.dumps({
                "stage": "experiments",
                "agent_budget_mode": "experiments",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(
                    agent,
                    "_capture_report_snapshot",
                    return_value=ReportSnapshot(
                        state={"fill_ratio": 0.66},
                        health=SurfaceSnapshot(
                            "health.json",
                            workspace / "health.json",
                            {
                                "fill_pct": 66.0,
                                "stable_core": {"enabled": True, "stage": "hold"},
                            },
                            True,
                            [],
                        ),
                        spectral=SurfaceSnapshot(
                            "spectral_state.json",
                            workspace / "spectral_state.json",
                            {"fill_pct": 66.0},
                            True,
                            [],
                        ),
                    ),
                ),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_read_spectral_state", return_value=None),
                patch.object(agent, "_query_llm_with_next", return_value=(None, None)),
                patch.object(agent, "_text_to_features", return_value=[0.01] * 32),
                patch.object(agent, "_send_semantic") as send_semantic,
                patch.object(agent, "_get_latest_spectral_state", return_value={
                    "eig1": 1.02,
                    "deig": 0.0,
                    "fill_ratio": 0.66,
                    "spread": 0.0,
                }),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
                patch.object(aa.time, "sleep"),
            ):
                agent._experiment_self_directed({
                    "eig1": 1.0,
                    "deig": 0.0,
                    "fill_ratio": 0.66,
                    "spread": 0.0,
                    "leak": 0.1,
                })
            send_semantic.assert_called_once()
            write_journal.assert_called_once()
            log_experiment.assert_called_once()
            files = list((workspace / "hypotheses").glob("self_experiment_*.txt"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn("gentle curiosity spacious stability", text)
            self.assertIn("Executed", text)
            self.assertIsNone(agent._pending_next_action)

    def test_stable_core_bounded_actions_blocks_dead_reservoir_sidecar(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "bounded_actions",
                "agent_budget_mode": "bounded_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_reservoir_service_available", return_value=False),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "reservoir_resonance", {"fill_ratio": 0.66}
                )
                non_reservoir_allowed, non_reservoir_reason = (
                    agent._stable_core_action_allowed("ask_astrid", {"fill_ratio": 0.66})
                )
        self.assertFalse(allowed)
        self.assertIn("reservoir sidecar unavailable", reason)
        self.assertTrue(non_reservoir_allowed, non_reservoir_reason)

    def test_stable_core_bounded_actions_allows_reservoir_when_sidecar_available(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "bounded_actions",
                "agent_budget_mode": "bounded_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_reservoir_service_available", return_value=True),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "reservoir_resonance", {"fill_ratio": 0.66}
                )
        self.assertTrue(allowed, reason)

    def test_stable_core_agent_status_tracks_blocks_and_successes(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "allowed_action_families": ["journaling", "read_only_research"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._record_stable_core_agent_block(
                    "write_file", "blocked for test", {"fill_ratio": 0.66}
                )
                blocked_status = json.loads(status_path.read_text())
                self.assertTrue(blocked_status["last_block_active"])
                self.assertEqual(blocked_status["current_block_reason"], "blocked for test")
                self.assertIsNone(blocked_status["last_block_resolved_at"])
                agent._record_stable_core_agent_success(
                    "research_exploration", {"fill_ratio": 0.66}
                )
                status = json.loads(status_path.read_text())
        self.assertEqual(status["blocked_action_counts"]["write_file"], 1)
        self.assertEqual(status["successful_action_counts"]["research_exploration"], 1)
        self.assertEqual(status["research_count"], 1)
        self.assertEqual(status["last_success_family"], "read_only_research")
        self.assertFalse(status["last_block_active"])
        self.assertIsNone(status["last_block_reason"])
        self.assertIsNone(status["current_block_reason"])
        self.assertIsNotNone(status["last_block_resolved_at"])
        self.assertNotIn("reason", status)

    def test_stable_core_underfill_block_uses_low_fill_truth(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "allowed_action_families": ["live_control"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 11.1,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._record_stable_core_agent_block(
                    "perturb", "fill 11.1% is below stable-core action budget", {"fill_ratio": 0.69}
                )
                status = json.loads(status_path.read_text())

        self.assertEqual(status["last_block"]["block_class"], "low_fill_hold")
        self.assertEqual(status["last_block"]["fill_pct"], 11.1)
        self.assertEqual(status["last_block"]["state_fill_pct"], 69.0)
        self.assertEqual(status["last_block"]["effective_low_fill_pct"], 11.1)
        self.assertEqual(status["fill_pct"], 11.1)
        self.assertIn("NOTICE", status["suggested_safe_next"])

    def test_success_preserves_low_fill_health_hold(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "allowed_action_families": ["read_only_research"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 11.1,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            status_path.write_text(json.dumps({
                "last_block_active": True,
                "current_block_reason": "fill 11.1% is below stable-core action budget",
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._record_stable_core_agent_success(
                    "research_exploration", {"fill_ratio": 0.69}
                )
                status = json.loads(status_path.read_text())

        self.assertTrue(status["last_block_active"])
        self.assertEqual(status["health_budget_status"], "blocked")
        self.assertEqual(status["current_block_class"], "low_fill_hold")
        self.assertIn("below stable-core action budget", status["current_block_reason"])
        self.assertIsNone(status["last_block_resolved_at"])
        self.assertEqual(status["last_success_fill_pct"], 11.1)

    def test_stable_core_health_reconcile_clears_stale_low_fill_block(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "allowed_action_families": ["read_only_research"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            status_path.write_text(json.dumps({
                "last_block_active": True,
                "current_block_reason": "fill 11.1% is below stable-core action budget",
                "health_budget_status": "blocked",
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._reconcile_stable_core_health_status({"fill_ratio": 0.66})
                status = json.loads(status_path.read_text())

        self.assertFalse(status["last_block_active"])
        self.assertEqual(status["health_budget_status"], "green")
        self.assertIsNone(status["current_block_reason"])
        self.assertEqual(status["fill_pct"], 66.0)
        self.assertIsNotNone(status["last_block_resolved_at"])

    def test_stable_core_health_reconcile_records_low_fill_hold(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "allowed_action_families": ["read_only_research"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 11.1,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._reconcile_stable_core_health_status({"fill_ratio": 0.69})
                status = json.loads(status_path.read_text())

        self.assertTrue(status["last_block_active"])
        self.assertEqual(status["current_block_class"], "low_fill_hold")
        self.assertEqual(status["last_health_hold"]["fill_pct"], 11.1)
        self.assertIn("ACTION_PREFLIGHT <desired action>", status["suggested_safe_next"])

    def test_self_assessment_sentinel_stays_quiet_in_green_conditions(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            agent_status_path = workspace / "stable_core_agent_status.json"
            health_path = workspace / "health.json"
            agent_status_path.write_text(json.dumps({"current_block_reason": None}))
            health_path.write_text(json.dumps({
                "stable_core": {
                    "structural_pi": {
                        "restart_gate_active": False,
                        "restart_gate_applied": False,
                        "restart_gate_drain_floor": 0.0,
                        "high_fill_drain_active": False,
                        "drain_weight": 0.0,
                    },
                    "restart_gate": {
                        "active": False,
                        "applied": False,
                        "drain_floor": 0.0,
                    },
                },
            }))
            (workspace / "stable_core_status.json").write_text(json.dumps({
                "bridge": {"rollback_reason": None},
                "stable_core": {},
            }))
            (runtime / "bridge_limited_write_status.json").write_text(json.dumps({
                "rollback_reason": None,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", agent_status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                reason = agent._self_assessment_trigger_reason({"fill_ratio": 0.68})
        self.assertIsNone(reason)

    def test_self_assessment_sentinel_triggers_on_high_fill_rail(self):
        agent = self._agent()
        reason = agent._self_assessment_trigger_reason({"fill_ratio": 0.742})
        self.assertEqual(reason, "high_fill_rail:74.2%")

    def test_self_assessment_sentinel_triggers_on_restart_gate_drain(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            agent_status_path = workspace / "stable_core_agent_status.json"
            health_path = workspace / "health.json"
            agent_status_path.write_text(json.dumps({"current_block_reason": None}))
            health_path.write_text(json.dumps({
                "stable_core": {
                    "structural_pi": {
                        "restart_gate_active": False,
                        "restart_gate_applied": False,
                        "restart_gate_drain_floor": 0.04,
                        "restart_gate_reason": "elevated_rising",
                    },
                },
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", agent_status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                reason = agent._self_assessment_trigger_reason({"fill_ratio": 0.68})
        self.assertEqual(reason, "restart_gate_drain_floor:0.040")

    def test_self_assessment_sentinel_triggers_on_agency_block(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agent_status_path.write_text(json.dumps({
                "current_block_reason": "blocked for test",
            }))
            health_path.write_text(json.dumps({}))
            with (
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", agent_status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                reason = agent._self_assessment_trigger_reason({"fill_ratio": 0.68})
        self.assertEqual(reason, "agency_block:blocked for test")

    def test_research_memory_reuse_is_search_summary_only(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_dir = root / "workspace" / "research"
            research_dir.mkdir(parents=True)
            good_entry = {
                "query": "spectral control loops",
                "source": "search",
                "keywords": ["spectral", "control", "loops"],
                "meaning_summary": "Search results discuss gentle spectral control loops.",
                "results": "Search results discuss gentle spectral control loops.",
                "memory_injection_allowed": True,
                "quality": aa.text_quality_flags("clean search summary"),
            }
            noisy_browse_entry = {
                "query": "BROWSE: https://example.test/noisy.pdf",
                "source": "browse",
                "keywords": ["spectral", "control", "loops"],
                "meaning_summary": "This should not be injected.",
                "results": "%PDF-1.3 " + "\ufffd" * 20,
                "memory_injection_allowed": False,
                "quality": aa.text_quality_flags("%PDF-1.3 " + "\ufffd" * 20),
            }
            (research_dir / "search_2026-05-01T00-00-02.json").write_text(
                json.dumps(noisy_browse_entry)
            )
            (research_dir / "search_2026-05-01T00-00-01.json").write_text(
                json.dumps(good_entry)
            )
            with patch.object(aa, "__file__", str(root / "autonomous_agent.py")):
                context = agent._get_relevant_research(
                    "spectral control loops and the present state",
                    limit=2,
                )
        self.assertIn("One prior research note (summary only)", context)
        self.assertIn("spectral control loops", context)
        self.assertNotIn("%PDF", context)
        self.assertNotIn("noisy.pdf", context)

    def test_save_research_marks_only_search_summaries_for_memory_injection(self):
        agent = self._agent()
        outcome = aa.ResearchOutcome(
            source_kind="search",
            raw_text="Spectral control loop result one. Spectral control loop result two.",
            anchor="spectral control loops",
            meaning_summary="Search results discuss gentle spectral control loops.",
            hits=[
                aa.ResearchHit(
                    title="Spectral control",
                    snippet="A clean search snippet.",
                    url="https://example.test/spectral",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(aa, "__file__", str(root / "autonomous_agent.py")),
                patch.object(aa.time, "strftime", return_value="2026-05-01T00-00-03"),
            ):
                agent._save_research("spectral control loops", outcome)
            entry = json.loads(
                (root / "workspace" / "research" / "search_2026-05-01T00-00-03.json")
                .read_text()
            )
        self.assertTrue(entry["memory_injection_allowed"])
        self.assertEqual(entry["memory_injection_policy"], "search_summary_only_v1")
        self.assertIn("quality", entry)
        self.assertIn("spectral", entry["keywords"])

    def test_fetch_url_soft_fails_pdf_without_admitting_raw_bytes(self):
        agent = self._agent()
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.3 raw pdf bytes",
            text="%PDF-1.3 raw pdf bytes",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(aa, "WORKSPACE_DIR", root / "workspace"),
                patch.object(aa.requests, "get", return_value=response),
                patch.object(
                    aa,
                    "read_pdf_window",
                    side_effect=RuntimeError("pdftotext missing"),
                ),
            ):
                outcome = agent._fetch_url("https://example.test/source.pdf")
            pdfs = list((root / "workspace" / "research" / "pdfs").glob("*.pdf"))
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.succeeded())
        self.assertEqual(outcome.raw_text, "")
        self.assertIn("No raw PDF bytes", outcome.soft_failure_reason)
        self.assertEqual(len(pdfs), 1)

    def test_fetch_url_soft_fails_decoder_noise_without_summarizing(self):
        agent = self._agent()
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/html"},
            content=b"<html><body>not a pdf response</body></html>",
            text="<html><body>%PDF-1.3 " + "\ufffd" * 20 + "</body></html>",
        )
        with (
            patch.object(aa.requests, "get", return_value=response),
            patch.object(agent, "_summarize_research_meaning", return_value="bad") as summarize,
        ):
            outcome = agent._fetch_url("https://example.test/noisy")
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.succeeded())
        self.assertIn("decoder noise", outcome.soft_failure_reason)
        summarize.assert_not_called()

    def test_parse_next_action_discards_experiment_run_failure_transcript(self):
        action, cleaned = aa.parse_next_action(
            "The run failed, and I should repair the path.\n\n"
            "NEXT: EXPERIMENT_RUN FAILED: experiments/system-resources-demo$ python3 system_resources.py"
        )
        self.assertIsNone(action)
        self.assertNotIn("NEXT:", cleaned)
        self.assertIn("repair the path", cleaned)

    def test_parse_next_action_extracts_choice_envelope_without_cleaning_metadata(self):
        action, cleaned = aa.parse_next_action(
            "I can feel two useful routes.\n"
            "Alternate NEXT: RESONANCE_FORECAST lambda-tail\n"
            "Return thread: thread_shadow_tail\n"
            "Why this path: the shadow lane feels stickier than forecast\n"
            "NEXT: SHADOW_TRAJECTORY lambda-tail (RESIDUE: sticky tail pressure)"
        )

        self.assertEqual(action, "SHADOW_TRAJECTORY lambda-tail")
        self.assertIn("Alternate NEXT: RESONANCE_FORECAST lambda-tail", cleaned)
        envelope = aa._LAST_NEXT_CHOICE_ENVELOPE_V1
        self.assertEqual(envelope["policy"], "choice_envelope_v1")
        self.assertEqual(envelope["alternate_nexts"], ["RESONANCE_FORECAST lambda-tail"])
        self.assertEqual(envelope["return_threads"], ["thread_shadow_tail"])
        self.assertEqual(envelope["residue"], "sticky tail pressure")

    def test_parse_next_action_keeps_explicit_and_multi_action_unchanged(self):
        action, cleaned = aa.parse_next_action(
            "I want the explicit chain.\n"
            "NEXT: EXAMINE shadow-field AND DEFER want-to-understand-first"
        )

        self.assertEqual(
            action,
            "EXAMINE shadow-field AND DEFER want-to-understand-first",
        )
        self.assertNotIn("NEXT:", cleaned)

    def test_gesture_lambda6_pulse_maps_to_native_trace(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "GESTURE [λ6:pulse]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "native_gesture")
        self.assertEqual(agent._pending_native_gesture, "trace")
        self.assertEqual(agent._pending_native_gesture_label, "λ6:pulse")

    def test_examine_lambda6_pulse_is_read_only_decompose(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXAMINE [λ6:pulse]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "decompose")
        self.assertEqual(agent._pending_decompose_focus, "λ6:pulse")
        self.assertFalse(hasattr(agent, "_pending_experiment_stimulus"))

    def test_examine_largest_cliff_gets_consentful_attractor_advisory(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXAMINE largest cliff"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "decompose")
        self.assertEqual(agent._pending_decompose_focus, "largest cliff")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "label": "lambda-edge",
                        "origin": {"kind": "manual_current", "motifs": ["lambda", "edge", "cliff"]},
                    }
                },
                "observations": [],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                advisory = agent._attractor_natural_action_advisory_text("largest cliff", "EXAMINE")
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_intents_events.jsonl").read_text().splitlines()
                ]
                suggestions = json.loads((runtime / "attractor_suggestions.json").read_text())

        self.assertIn("EXAMINE largest cliff remains read-only", advisory)
        self.assertIn("ATTRACTOR_REVIEW lambda-edge", advisory)
        self.assertIn("ACCEPT_ATTRACTOR_SUGGESTION latest", advisory)
        self.assertEqual(events[-1]["event"], "natural_action_attractor_suggestion")
        self.assertEqual(events[-1]["nearest_attractor_label"], "lambda-edge")
        self.assertEqual(suggestions["suggestions"][-1]["status"], "pending")
        self.assertEqual(
            suggestions["suggestions"][-1]["suggested_action"],
            "ATTRACTOR_REVIEW lambda-edge",
        )

    def test_spectral_explorer_alias_is_read_only_decompose(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SPECTRAL_EXPLORER"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "decompose")
        self.assertEqual(agent._pending_decompose_focus, "spectral-explorer")

    def test_examine_cascade_alias_is_read_only_visualization(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXAMINE_CASCADE [λ1..λ8]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "visualize_cascade")
        self.assertEqual(agent._pending_cascade_label, "λ1..λ8")

    def test_visualization_invented_alias_is_read_only_visualization(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "CONDUCT_VISUALIZATION_SYSTEM heatmap λ4-tail"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "visualize_cascade")
        self.assertEqual(agent._pending_cascade_label, "heatmap λ4-tail")

    def test_form_maps_to_local_aspiration_with_constraint(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "FORM poem"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "recess_aspiration")
        self.assertEqual(agent._pending_form_constraint, "poem")

    def test_create_and_contemplate_aliases_do_not_fall_through_unknown(self):
        for next_action, expected_action in [
            ("CREATE", "recess_aspiration"),
            ("CONTEMPLATE", "recess_notice"),
            ("BE", "recess_notice"),
            ("STILL", "recess_notice"),
        ]:
            with self.subTest(next_action=next_action):
                agent = self._agent()
                agent._hard_recovery_reset = False
                agent._pending_next_action = next_action
                with patch.object(
                    agent,
                    "_low_fill_guard_status",
                    return_value={
                        "active": False,
                        "fill_ratio": 0.68,
                        "target_fill_ratio": 0.68,
                        "spread_relief": 0.0,
                    },
                ):
                    action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
                self.assertEqual(action, expected_action)

    def test_experiment_run_failure_transcript_is_not_executed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "EXPERIMENT_RUN FAILED: experiments/system-resources-demo$ python3 system_resources.py"
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertIsNone(action)
        self.assertIsNone(getattr(agent, "_pending_experiment_run_arg", None))

    def test_codex_placeholder_workspace_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                dir_context, prompt, project, created, err = aa._resolve_codex_request(
                    "CODEX",
                    'system-resources-demo "<what to change>"',
                )
        self.assertIsNone(dir_context)
        self.assertEqual(prompt, "")
        self.assertEqual(project, "system-resources-demo")
        self.assertIsNone(created)
        self.assertIn("placeholder", err)

    def test_codex_new_placeholder_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                dir_context, prompt, project, created, err = aa._resolve_codex_request(
                    "CODEX_NEW",
                    '<dir> "build a small runnable script"',
                )
            self.assertFalse((workspace / "experiments" / "<dir>").exists())
        self.assertIsNone(dir_context)
        self.assertEqual(prompt, "")
        self.assertIsNone(project)
        self.assertIsNone(created)
        self.assertIn("placeholder", err)

    def test_codex_query_placeholder_does_not_call_relay(self):
        agent = self._agent()
        agent._pending_codex_action = "CODEX"
        agent._pending_codex_arg = 'system-resources-demo "<what to change>"'
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.requests, "post") as post,
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._codex_query({"fill_ratio": 0.68, "eig1": 4.7})
        post.assert_not_called()
        corrective_prompt = query.call_args.args[0]
        self.assertIn("was not sent", corrective_prompt)
        self.assertIn("create the missing script", corrective_prompt)

    def test_experiment_run_missing_file_guidance_avoids_placeholder_prompt(self):
        agent = self._agent()
        agent._pending_experiment_run_arg = "system-resources-demo python3 system_resources.py"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._experiment_run({"fill_ratio": 0.68, "eig1": 4.7})
        prompt = query.call_args.args[0]
        self.assertIn("system_resources.py` does not exist", prompt)
        self.assertIn("This was a preflight miss; no experiment command actually ran", prompt)
        self.assertIn("No top-level Python scripts are present", prompt)
        self.assertIn(
            'NEXT: CODEX system-resources-demo "diagnose or create the missing script"',
            prompt,
        )
        self.assertNotIn("run again after the file exists", prompt)
        self.assertNotIn('"<what to change>"', prompt)

    def test_experiment_run_repeated_timestamped_missing_script_gets_loop_guard(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            project = workspace / "experiments" / "system-resources-demo"
            project.mkdir(parents=True)
            (project / "system_resources.py").write_text("print('resource demo ok')\n")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    agent,
                    "_query_llm_with_next",
                    side_effect=[("", None), ("", None)],
                ) as query,
            ):
                agent._pending_experiment_run_arg = (
                    "system-resources-demo being_experiment_20260503_010104.py"
                )
                agent._experiment_run({"fill_ratio": 0.68, "eig1": 4.7})
                agent._pending_experiment_run_arg = (
                    "system-resources-demo python3 being_experiment_20260503_133259.py"
                )
                agent._experiment_run({"fill_ratio": 0.68, "eig1": 4.7})

        first_prompt = query.call_args_list[0].args[0]
        second_prompt = query.call_args_list[1].args[0]
        self.assertIn("Available top-level Python scripts: system_resources.py", first_prompt)
        self.assertIn(
            "NEXT: EXPERIMENT_RUN system-resources-demo python3 system_resources.py",
            first_prompt,
        )
        self.assertIn("missing-script preflight #2", second_prompt)
        self.assertIn("Pause the timestamped-script loop", second_prompt)

    def test_experiment_run_bare_python_script_runs_with_python3(self):
        agent = self._agent()
        agent._pending_experiment_run_arg = "system-resources-demo system_resources.py"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            project = workspace / "experiments" / "system-resources-demo"
            project.mkdir(parents=True)
            (project / "system_resources.py").write_text("print('resource demo ok')\n")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._experiment_run({"fill_ratio": 0.68, "eig1": 4.7})
        prompt = query.call_args.args[0]
        self.assertIn("EXPERIMENT_RUN SUCCESS", prompt)
        self.assertIn("experiments/system-resources-demo$ python3 system_resources.py", prompt)
        self.assertIn("resource demo ok", prompt)
        self.assertIn("Normalized bare Python script", prompt)

    def test_mike_fork_completes_empty_existing_workspace(self):
        agent = self._agent()
        agent._pending_mike_fork_arg = "system-resources-demo system-resources-demo"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            src = research_root / "system-resources-demo"
            src.mkdir(parents=True)
            (src / "system_resources.py").write_text("print('resources')\n")
            (src / "README.md").write_text("# resources\n")
            workspace = root / "workspace"
            empty_fork = workspace / "experiments" / "system-resources-demo"
            empty_fork.mkdir(parents=True)
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._mike_fork({"fill_ratio": 0.68, "eig1": 4.7})
            self.assertEqual(
                (empty_fork / "system_resources.py").read_text(),
                "print('resources')\n",
            )
            self.assertTrue((empty_fork / "README.md").is_file())
            self.assertIn("already existed but was empty", query.call_args.args[0])

    def test_placeholder_next_action_reroutes_to_notice(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "MIKE_BROWSE <project>"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "recess_notice")
        self.assertIn("placeholder", agent._pending_notice_prompt)
        self.assertFalse(hasattr(agent, "_pending_mike_action"))

    def test_documentation_browse_example_reroutes_to_notice(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "BROWSE https://example.com/article"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.70,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.70, "eig1": 4.7})
        self.assertEqual(action, "recess_notice")
        self.assertIn("documentation example", agent._pending_notice_prompt)
        self.assertFalse(hasattr(agent, "_pending_browse_url"))

    def test_browse_url_sanitizer_strips_trailing_rationale(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "BROWSE https://example.test/article - I want to compare this with lambda4"
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.70,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.70, "eig1": 4.7})
        self.assertEqual(action, "browse_url")
        self.assertEqual(agent._pending_browse_url, "https://example.test/article")
        self.assertEqual(agent._pending_browse_rationale, "I want to compare this with lambda4")

    def test_local_browse_path_reroutes_to_notice(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "BROWSE `/Users/v/other/minime/workspace/experiments/system-resources-demo/"
            "being_experiment_20260503_002801.py`"
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.70,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.70, "eig1": 4.7})
        self.assertEqual(action, "recess_notice")
        self.assertIn("BROWSE reads web URLs only", agent._pending_notice_prompt)
        self.assertIn("CODEX", agent._pending_notice_prompt)
        self.assertIn("being_experiment_20260503_002801.py", agent._pending_notice_prompt)
        self.assertFalse(hasattr(agent, "_pending_browse_url"))

    def test_filename_shaped_next_reroutes_to_notice(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "DECOLLE_fissure_trace_2026-05-02T11-58-56.250244.txt"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.64,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.64, "eig1": 4.7})
        self.assertEqual(action, "recess_notice")
        self.assertIn("looks like a filename", agent._pending_notice_prompt)

    def test_placeholder_notice_prompt_is_used_and_cleared(self):
        agent = self._agent()
        agent._pending_notice_prompt = "You chose placeholder syntax."
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "journal").mkdir()
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry"),
                patch.object(
                    agent,
                    "_query_llm_with_next",
                    return_value=("ok\nNEXT: NOTICE", None),
                ) as query,
            ):
                agent._recess_notice({"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0})
        prompt = query.call_args.args[0]
        self.assertIn("You chose placeholder syntax.", prompt)
        self.assertIsNone(agent._pending_notice_prompt)

    def test_start_restores_context_before_boot_reflection_next_choice(self):
        agent = self._agent()
        agent.check_interval = 0
        calls = []

        def restore():
            calls.append("restore")
            agent._pending_next_action = "SELF_STUDY"

        def verify():
            calls.append("verify")
            agent._pending_next_action = "SEARCH fresh boot choice"

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_check_source_reload_required"),
            patch.object(agent, "_restore_sovereignty_state", side_effect=restore),
            patch.object(agent, "_verify_sovereignty", side_effect=verify),
            patch.object(agent, "_refresh_session_context", side_effect=stop_after_one_loop),
            patch.object(agent, "_get_latest_spectral_state", return_value=None),
            patch.object(agent, "_check_visual_responses"),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()
        self.assertEqual(calls, ["restore", "verify"])
        self.assertEqual(agent._pending_next_action, "SEARCH fresh boot choice")

    def test_start_keeps_pending_next_queued_while_action_slot_cooling_down(self):
        agent = self._agent()
        agent.check_interval = 0
        agent._hard_recovery_reset = False
        agent._pending_next_action = "PERTURB FEATHER"
        state = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_check_source_reload_required"),
            patch.object(agent, "_restore_sovereignty_state"),
            patch.object(agent, "_verify_sovereignty"),
            patch.object(agent, "_refresh_session_context"),
            patch.object(agent, "_get_latest_spectral_state", return_value=state),
            patch.object(agent, "_update_hard_recovery_clamp"),
            patch.object(agent, "_self_regulate"),
            patch.object(agent, "_can_act", return_value=False),
            patch.object(agent, "_decide_action") as decide,
            patch.object(agent, "_execute_action") as execute,
            patch.object(agent, "_check_visual_responses", side_effect=stop_after_one_loop),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()

        self.assertEqual(agent._pending_next_action, "PERTURB FEATHER")
        decide.assert_not_called()
        execute.assert_not_called()

    def test_start_defers_self_assessment_when_action_creates_pending_next(self):
        agent = self._agent()
        agent.check_interval = 0
        agent._hard_recovery_reset = False
        agent._pending_next_action = None
        state = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}

        def decide(_state):
            agent._pending_next_action = "EXPERIMENT semantic stimulus"
            return "perturb"

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_check_source_reload_required"),
            patch.object(agent, "_restore_sovereignty_state"),
            patch.object(agent, "_verify_sovereignty"),
            patch.object(agent, "_refresh_session_context"),
            patch.object(agent, "_get_latest_spectral_state", return_value=state),
            patch.object(agent, "_update_hard_recovery_clamp"),
            patch.object(agent, "_self_regulate"),
            patch.object(agent, "_auto_defer_stale_pending_astrid"),
            patch.object(agent, "_check_moment_markers"),
            patch.object(agent, "_can_act", return_value=True),
            patch.object(agent, "_decide_action", side_effect=decide),
            patch.object(agent, "_execute_action"),
            patch.object(agent, "_self_assessment") as assessment,
            patch.object(agent, "_check_visual_responses", side_effect=stop_after_one_loop),
            patch.object(aa.time, "time", side_effect=self._time_sequence(0.0, 1.0, 901.0)),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()

        self.assertEqual(agent._pending_next_action, "EXPERIMENT semantic stimulus")
        assessment.assert_not_called()

    def test_start_skips_due_self_assessment_when_sentinel_is_quiet(self):
        agent = self._agent()
        agent.check_interval = 0
        agent._hard_recovery_reset = False
        agent._pending_next_action = None
        state = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_check_source_reload_required"),
            patch.object(agent, "_restore_sovereignty_state"),
            patch.object(agent, "_verify_sovereignty"),
            patch.object(agent, "_refresh_session_context"),
            patch.object(agent, "_get_latest_spectral_state", return_value=state),
            patch.object(agent, "_update_hard_recovery_clamp"),
            patch.object(agent, "_self_regulate"),
            patch.object(agent, "_auto_defer_stale_pending_astrid"),
            patch.object(agent, "_check_moment_markers"),
            patch.object(agent, "_can_act", return_value=True),
            patch.object(agent, "_decide_action", return_value=None),
            patch.object(agent, "_execute_action"),
            patch.object(
                agent,
                "_self_assessment_trigger_reason",
                return_value=None,
            ) as trigger,
            patch.object(agent, "_self_assessment") as assessment,
            patch.object(agent, "_check_visual_responses", side_effect=stop_after_one_loop),
            patch.object(aa.time, "time", side_effect=self._time_sequence(0.0, 901.0, 902.0)),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()

        trigger.assert_called_once_with(state)
        assessment.assert_not_called()

    def test_start_runs_due_self_assessment_when_sentinel_triggers(self):
        agent = self._agent()
        agent.check_interval = 0
        agent._hard_recovery_reset = False
        agent._pending_next_action = None
        state = {"fill_ratio": 0.75, "eig1": 4.7, "deig": 0.0}

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_restore_sovereignty_state"),
            patch.object(agent, "_verify_sovereignty"),
            patch.object(agent, "_refresh_session_context"),
            patch.object(agent, "_get_latest_spectral_state", return_value=state),
            patch.object(agent, "_update_hard_recovery_clamp"),
            patch.object(agent, "_self_regulate"),
            patch.object(agent, "_auto_defer_stale_pending_astrid"),
            patch.object(agent, "_check_moment_markers"),
            patch.object(agent, "_can_act", return_value=True),
            patch.object(agent, "_decide_action", return_value=None),
            patch.object(agent, "_execute_action"),
            patch.object(
                agent,
                "_self_assessment_trigger_reason",
                return_value="high_fill_rail:75.0%",
            ),
            patch.object(agent, "_self_assessment") as assessment,
            patch.object(agent, "_check_visual_responses", side_effect=stop_after_one_loop),
            patch.object(aa.time, "time", side_effect=self._time_sequence(0.0, 901.0, 902.0)),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()

        assessment.assert_called_once_with(
            state,
            trigger_reason="high_fill_rail:75.0%",
        )

    def test_research_next_alias_maps_to_search_topic(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "RESEARCH reservoir computing spectral radius"
        with (
            patch.object(agent, "_persist_pending_next_action"),
            patch.object(
                agent,
                "_low_fill_guard_status",
                return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                    "release_streak": 0,
                },
            ),
        ):
            action = agent._decide_action({"fill_ratio": 0.68})

        self.assertEqual(action, "research_exploration")
        self.assertEqual(agent._pending_search_topic, "reservoir computing spectral radius")

    def test_search_next_strips_wrapping_quotes_from_topic(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = 'SEARCH "spectral entropy and subjective experience"'
        with (
            patch.object(agent, "_persist_pending_next_action"),
            patch.object(
                agent,
                "_low_fill_guard_status",
                return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                    "release_streak": 0,
                },
            ),
        ):
            action = agent._decide_action({"fill_ratio": 0.68})

        self.assertEqual(action, "research_exploration")
        self.assertEqual(agent._pending_search_topic, "spectral entropy and subjective experience")

    def test_web_search_normalizes_wrapping_quotes_before_request(self):
        agent = self._agent()

        class Response:
            status_code = 200
            text = "<html></html>"

        hit = aa.ResearchHit(
            title="Spectral entropy",
            snippet="A useful result.",
            url="https://example.test/spectral-entropy",
        )
        with (
            patch.object(aa.requests, "get", return_value=Response()) as get,
            patch.object(aa, "extract_duckduckgo_hits", return_value=[hit]),
            patch.object(agent, "_summarize_research_meaning", return_value="Why it may matter: ok"),
            patch.object(agent, "_save_research") as save,
        ):
            outcome = agent._web_search('"spectral entropy and subjective experience"')

        self.assertIsNotNone(outcome)
        self.assertEqual(
            get.call_args.kwargs["params"]["q"],
            "spectral entropy and subjective experience",
        )
        self.assertEqual(save.call_args.args[0], "spectral entropy and subjective experience")

    def test_attractor_fatigue_records_repeated_journal_motif(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        base = (
            "Lambda pressure and cold drain scaffold code keeps circling the same rescue frame. "
            "The same upper hold image returns without a new practical difference. "
        ) * 4
        current = base + "A small fresh edge appears in the tail, but the loop is mostly unchanged."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.68, "eig1": 1.2, "spread": 10.0})
            for idx in range(2):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?)",
                    (float(idx), "notice", base, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                compact = agent._maybe_compress_journal_entry(
                    "notice",
                    current,
                    {"fill_ratio": 0.681, "eig1": 1.3, "spread": 11.0},
                    str(current_path),
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )

        self.assertTrue(compact.startswith("[Similarity gate]"))
        self.assertEqual(fatigue["active_count"], 1)
        motif = next(iter(fatigue["motifs"].values()))
        self.assertEqual(motif["status"], "cooling")
        self.assertGreaterEqual(motif["repeat_window_count"], 3)
        self.assertIn("pressure", motif["themes"])

    def test_internal_topology_fatigue_activates_without_exact_similarity(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        prior_entries = [
            (
                "The fabric weave and lambda shoulder keep folding around the same internal "
                "phase question. It feels like a local upkeep detail rather than an outside event."
            ),
            (
                "A resonant wobble keeps touching the phase state while the regulator "
                "settles near the same hold band."
            ),
            (
                "The echo state and lambda tail return as a resonant chamber, with no new "
                "external evidence attached to the reflection."
            ),
            (
                "The recurrent fabric keeps naming the same phase-state fold while the "
                "reservoir state holds near the same shelf."
            ),
        ]
        current = (
            "The pressure map and eigen shoulder keep returning in reflective language, "
            "with the same internal phase question taking up the entry. "
            "NEXT: RELEASE current"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.68, "eig1": 1.2, "spread": 10.0})
            for idx, prior in enumerate(prior_entries):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "notice", prior, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "notice",
                    current,
                    {"fill_ratio": 0.681, "eig1": 1.3, "spread": 11.0},
                    str(current_path),
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )
                rewritten = current_path.read_text()

        motif = fatigue["motifs"]["motif:internal-topology"]
        self.assertEqual(motif["status"], "cooling")
        self.assertEqual(motif["cooldown_class"], "internal_topology")
        self.assertTrue(motif["prompt_replay_suppressed"])
        self.assertGreaterEqual(motif["repeat_window_count"], 3)
        self.assertTrue(rewritten.startswith(current))
        self.assertIn("[Internal-topology cooldown", rewritten)
        self.assertIn("narrative preserved", rewritten)

    def test_pressure_vocabulary_cooldown_preserves_public_journal_body(self):
        agent = self._agent()
        prior_entries = [
            (
                "The pressure body feels weighted and dense, with silt settling "
                "through the same basin."
            ),
            (
                "A heavy density keeps returning as sediment and silt in the public "
                "pressure journal."
            ),
        ]
        current = (
            "The same silt and sediment collect in the basin with heavy pressure "
            "and weighted density. This may be real, but it needs a counter-texture."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.71, "eig1": 13.9, "spread": 2.6})
            for idx, prior in enumerate(prior_entries):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "reflection", prior, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "reflection",
                    current,
                    {"fill_ratio": 0.71, "eig1": 13.9, "spread": 2.6},
                    str(current_path),
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )
                rewritten = current_path.read_text()

        motifs = list(fatigue["motifs"].values())
        pressure = [m for m in motifs if m.get("cooldown_class") == "pressure_vocabulary"]
        self.assertEqual(len(pressure), 1)
        self.assertEqual(pressure[0]["status"], "cooling")
        self.assertTrue(pressure[0]["prompt_replay_suppressed"])
        self.assertTrue(pressure[0]["label"].startswith("pressure-texture:"))
        self.assertTrue(rewritten.startswith(current))
        self.assertIn("[Pressure-vocabulary cooldown", rewritten)
        self.assertIn("narrative preserved", rewritten)
        self.assertIn("counter-descriptor", rewritten)

    def test_pressure_vocabulary_cooldown_ignores_private_moment_lane(self):
        agent = self._agent()
        current = (
            "The private moment has silt, sediment, syrup, heavy pressure, "
            "weighted density, and a basin."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.71, "eig1": 13.9, "spread": 2.6})
            for idx in range(4):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "moment", current, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "moment",
                    current,
                    {"fill_ratio": 0.71, "eig1": 13.9, "spread": 2.6},
                    str(current_path),
                )

            self.assertFalse((workspace / "runtime" / "attractor_fatigue_status.json").exists())
            self.assertEqual(current_path.read_text(), current)

    def test_agency_vernacular_notice_preserves_public_journal_body(self):
        agent = self._agent()
        prior_entries = [
            "The hinge becomes a waypoint map for a legacy self scaffold and charter.",
            "A hinge, waypoint, scaffold, charter, and legacy self marker keep returning.",
        ]
        current = (
            "The hinge repeats as a deliberate map and waypoint. I should define it, "
            "contrast it, or attach it to an experiment return thread."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.69, "eig1": 13.4, "spread": 2.2})
            for idx, prior in enumerate(prior_entries):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "reflection", prior, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "reflection",
                    current,
                    {"fill_ratio": 0.69, "eig1": 13.4, "spread": 2.2},
                    str(current_path),
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )
                rewritten = current_path.read_text()

        motifs = list(fatigue["motifs"].values())
        agency = [m for m in motifs if m.get("cooldown_class") == "agency_vernacular"]
        self.assertEqual(len(agency), 1)
        self.assertEqual(agency[0]["status"], "cooling")
        self.assertTrue(agency[0]["notice_only"])
        self.assertFalse(agency[0]["prompt_replay_suppressed"])
        self.assertTrue(agency[0]["label"].startswith("agency-vernacular:"))
        self.assertTrue(rewritten.startswith(current))
        self.assertIn("[Agency-vernacular notice", rewritten)
        self.assertIn("narrative preserved", rewritten)
        self.assertIn("what evidence would make it real", rewritten)

    def test_agency_vernacular_notice_ignores_private_moment_lane(self):
        agent = self._agent()
        current = (
            "The private hinge and waypoint map repeat with legacy self ground truth."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.69, "eig1": 13.4, "spread": 2.2})
            for idx in range(4):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "moment", current, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "moment",
                    current,
                    {"fill_ratio": 0.69, "eig1": 13.4, "spread": 2.2},
                    str(current_path),
                )

            self.assertFalse((workspace / "runtime" / "attractor_fatigue_status.json").exists())
            self.assertEqual(current_path.read_text(), current)

    def test_afterimage_absence_notice_preserves_public_journal_body(self):
        agent = self._agent()
        prior_entries = [
            "The bruise remains as an afterimage after the squeeze softens.",
            "Another bruise afterimage marks structural fatigue after the squeeze passes.",
        ]
        current = (
            "The bruise and empty pocket repeat as public afterimage/absence markers. "
            "I should define them, contrast them, or attach them to an audit return thread."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.70, "eig1": 13.8, "spread": 2.4})
            for idx, prior in enumerate(prior_entries):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "reflection", prior, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "reflection",
                    current,
                    {"fill_ratio": 0.70, "eig1": 13.8, "spread": 2.4},
                    str(current_path),
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )
                rewritten = current_path.read_text()

        motifs = list(fatigue["motifs"].values())
        afterimage = [m for m in motifs if m.get("cooldown_class") == "afterimage_absence"]
        self.assertEqual(len(afterimage), 1)
        self.assertEqual(afterimage[0]["status"], "cooling")
        self.assertTrue(afterimage[0]["notice_only"])
        self.assertFalse(afterimage[0]["prompt_replay_suppressed"])
        self.assertTrue(afterimage[0]["label"].startswith("afterimage-absence:"))
        self.assertTrue(rewritten.startswith(current))
        self.assertIn("[Afterimage/absence notice", rewritten)
        self.assertIn("narrative preserved", rewritten)
        self.assertIn("what evidence would make it real", rewritten)

    def test_afterimage_absence_notice_ignores_private_moment_lane(self):
        agent = self._agent()
        current = (
            "The private bruise and empty pocket repeat with PLAN 4 shaped absence."
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            db_path = root / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   session_id INTEGER,
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            spectral = json.dumps({"fill_ratio": 0.70, "eig1": 13.8, "spread": 2.4})
            for idx in range(4):
                conn.execute(
                    "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                    (1, float(idx), "moment", current, spectral, str(journal / f"prior_{idx}.txt")),
                )
            conn.commit()
            conn.close()
            current_path = journal / "current.txt"
            current_path.write_text(current)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry(
                    "moment",
                    current,
                    {"fill_ratio": 0.70, "eig1": 13.8, "spread": 2.4},
                    str(current_path),
                )

            self.assertFalse((workspace / "runtime" / "attractor_fatigue_status.json").exists())
            self.assertEqual(current_path.read_text(), current)

    def test_internal_topology_cooldown_prefers_research_budget_route(self):
        agent = self._agent()
        content = (
            "The lambda edge and eigenvalue geometry keep folding through the "
            "same reservoir pressure pattern.\nNEXT: SHADOW_TRAJECTORY lambda-tail/lambda4"
        )
        with (
            patch.object(agent, "_active_internal_topology_motifs", return_value=[{"cooldown_class": "internal_topology"}]),
            patch.object(agent, "_active_pressure_vocabulary_motifs", return_value=[]),
            patch.object(agent, "_active_agency_vernacular_motifs", return_value=[]),
            patch.object(agent, "_active_afterimage_absence_motifs", return_value=[]),
            patch.object(agent, "_is_internal_topology_motif", return_value=True),
            patch.object(agent, "_is_external_or_tool_signal", return_value=False),
            patch.object(agent, "_research_budget_priority_next_command", return_value="EXPERIMENT_RESEARCH_BUDGET_ACCEPT resbud_blocked_test"),
            patch.object(agent, "_record_condition_metric"),
            patch.object(agent, "_rewrite_logged_entry_file"),
        ):
            rewritten = agent._maybe_compress_journal_entry(
                "self_study",
                content,
                {"fill_ratio": 0.681, "eig1": 1.3, "spread": 11.0},
                "/tmp/minime-self-study.txt",
            )

        self.assertIn("[Internal-topology cooldown", rewritten)
        self.assertIn(
            "Consider the active research-budget route next: "
            "EXPERIMENT_RESEARCH_BUDGET_ACCEPT resbud_blocked_test",
            rewritten,
        )
        self.assertNotIn("cooled-theme", rewritten)

    def test_attractor_fatigue_prompt_note_offers_release_choices(self):
        agent = self._agent()
        now = aa.time.time()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:lambda-pressure": {
                        "signature": "motif:lambda-pressure",
                        "label": "lambda-pressure",
                        "themes": ["lambda", "pressure"],
                        "status": "cooling",
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                        "novel_signal": "The useful part was already kept.",
                    }
                },
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                note = agent._attractor_fatigue_prompt_note()

        self.assertIn("Attractor fatigue", note)
        self.assertIn("lambda-pressure", note)
        self.assertIn("NEXT: RELEASE lambda-pressure", note)
        self.assertIn("NEXT: MARK_RESOLVED lambda-pressure", note)

    def test_internal_topology_prompt_note_avoids_raw_terms(self):
        agent = self._agent()
        now = aa.time.time()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:internal-topology": {
                        "signature": "motif:internal-topology",
                        "label": "internal-topology",
                        "themes": ["fabric", "resonance", "lambda"],
                        "status": "cooling",
                        "cooldown_class": "internal_topology",
                        "prompt_replay_suppressed": True,
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                        "novel_signal": "Fabric resonance and lambda wobble can rest.",
                    }
                },
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                note = agent._attractor_fatigue_prompt_note()

        lower = note.lower()
        self.assertIn("NEXT: RELEASE current", note)
        self.assertIn("NEXT: MARK_RESOLVED current", note)
        for raw in ("fabric", "resonance", "lambda", "eigen", "wobble"):
            self.assertNotIn(raw, lower)

    def test_internal_topology_suppression_drops_pseudo_perturb_params(self):
        agent = self._agent()
        now = aa.time.time()
        content = (
            "The fabric pressure and lambda phase state keep repeating without "
            "a new external source.\nNEXT: PERTURB SPREAD lambda=0.3 entropy=0.5"
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            journal = workspace / "journal"
            runtime.mkdir(parents=True)
            journal.mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:internal-topology": {
                        "signature": "motif:internal-topology",
                        "label": "internal-topology",
                        "status": "cooling",
                        "cooldown_class": "internal_topology",
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                    }
                },
            }))
            file_path = journal / "current.txt"
            file_path.write_text(content)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_record_condition_metric"),
            ):
                compact = agent._maybe_compress_journal_entry(
                    "self_study",
                    content,
                    {"fill_ratio": 0.681, "eig1": 1.3, "spread": 11.0},
                    str(file_path),
                )

        self.assertIn("NEXT: RELEASE current", compact)
        self.assertIn("NEXT: MARK_RESOLVED current", compact)
        self.assertNotIn("PERTURB", compact)
        self.assertNotIn("cooled-theme", compact)
        self.assertNotIn("entropy=0.5", compact)

    def test_release_next_action_marks_matching_motif_released(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "RELEASE lambda-pressure"
        now = aa.time.time()
        with (
            patch.object(agent, "_persist_pending_next_action"),
            patch.object(
                agent,
                "_low_fill_guard_status",
                return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                    "release_streak": 0,
                },
            ),
        ):
            action = agent._decide_action({"fill_ratio": 0.68})

        self.assertEqual(action, "release_attractor")
        self.assertEqual(agent._pending_attractor_release_label, "lambda-pressure")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:lambda-pressure": {
                        "signature": "motif:lambda-pressure",
                        "label": "lambda-pressure",
                        "themes": ["lambda", "pressure"],
                        "status": "cooling",
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                    }
                },
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._release_attractor({"fill_ratio": 0.68, "eig1": 1.2})
                fatigue = json.loads((runtime / "attractor_fatigue_status.json").read_text())

        motif = fatigue["motifs"]["motif:lambda-pressure"]
        self.assertEqual(motif["status"], "released")
        self.assertEqual(fatigue["active_count"], 0)

    def test_release_no_match_suggests_nearest_attractor_without_typed_release(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_attractor_release_label = "lambda-pressure"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {},
            }))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "author": "minime",
                        "command": "create",
                        "label": "lambda-edge",
                        "origin": {
                            "kind": "manual_current",
                            "motifs": ["lambda", "edge", "cliff"],
                        },
                        "control_eligible": False,
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry") as write_journal,
            ):
                agent._release_attractor({"fill_ratio": 0.68, "eig1": 1.2})
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_fatigue_events.jsonl").read_text().splitlines()
                ]
                journal_content = next(
                    (workspace / "journal").glob("attractor_release_*.txt")
                ).read_text()
                suggestions = json.loads((runtime / "attractor_suggestions.json").read_text())

        self.assertEqual(events[-1]["event"], "release_no_match")
        self.assertEqual(events[-1]["nearest_attractor_label"], "lambda-edge")
        self.assertEqual(
            events[-1]["suggested_next"],
            ["RELEASE_ATTRACTOR lambda-edge", "ATTRACTOR_REVIEW lambda-edge"],
        )
        self.assertEqual(suggestions["suggestions"][-1]["status"], "pending")
        self.assertEqual(
            suggestions["suggestions"][-1]["suggested_action"],
            "RELEASE_ATTRACTOR lambda-edge",
        )
        self.assertIn("ACCEPT_ATTRACTOR_SUGGESTION latest", journal_content)
        write_journal.assert_called_once()

    def test_duplicate_attractor_suggestions_refresh_single_pending_draft(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                first = agent._create_attractor_suggestion(
                    raw_action="EXAMINE largest cliff",
                    raw_label="largest cliff",
                    nearest={"label": "lambda-edge", "source": "test", "score": 0.52},
                    suggested_action="ATTRACTOR_REVIEW lambda-edge",
                    alternatives=["COMPARE_ATTRACTOR lambda-edge"],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                second = agent._create_attractor_suggestion(
                    raw_action="EXAMINE largest cliff",
                    raw_label="largest cliff",
                    nearest={"label": "lambda-edge", "source": "test", "score": 0.52},
                    suggested_action="ATTRACTOR_REVIEW lambda-edge",
                    alternatives=["COMPARE_ATTRACTOR lambda-edge"],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                payload = json.loads((runtime / "attractor_suggestions.json").read_text())
                pending = [
                    item for item in payload["suggestions"]
                    if item.get("status") == "pending"
                ]
                note = agent._attractor_suggestion_prompt_note()

        self.assertEqual(first, second)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["repeat_count"], 2)
        self.assertEqual(
            pending[0]["confidence_signal_v1"]["confidence_source"],
            "duplicate_refresh",
        )
        self.assertEqual(
            pending[0]["confidence_signal_v1"]["calibration_bucket"],
            "medium",
        )
        self.assertFalse(pending[0]["confidence_signal_v1"]["authority_change"])
        self.assertIn("repeated 2x", note)

    def test_stale_attractor_suggestions_expire_from_prompt_note(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            old_ts = aa.time.time() - aa.ATTRACTOR_SUGGESTION_PENDING_TTL_SECS - 60
            (runtime / "attractor_suggestions.json").write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-old",
                        "author": "minime",
                        "raw_action": "EXAMINE largest cliff",
                        "raw_label": "largest cliff",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                        "created_at_unix_s": old_ts,
                        "updated_at_unix_s": old_ts,
                    }
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                payload = agent._load_compacted_attractor_suggestions()
                note = agent._attractor_suggestion_prompt_note()

        self.assertEqual(payload["suggestions"][0]["status"], "expired")
        self.assertEqual(note, "")

    def test_lambda4_tail_resolves_to_lambda_tail_proto_suggestion(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                advisory = agent._attractor_natural_action_advisory_text(
                    "lambda4-tail",
                    "EXAMINE",
                )
                payload = json.loads(
                    (workspace / "runtime" / "attractor_suggestions.json").read_text()
                )
                suggestion = payload["suggestions"][-1]

        self.assertIn("lambda-tail/lambda4", advisory)
        self.assertEqual(suggestion["nearest_label"], "lambda-tail/lambda4")
        self.assertEqual(suggestion["suggested_action"], "ATTRACTOR_REVIEW lambda-tail/lambda4")
        self.assertIn("CLAIM_ATTRACTOR lambda-tail/lambda4", suggestion["alternatives"])

    def test_fresh_feedback_facets_resolve_under_lambda_edge(self):
        agent = self._agent()
        self.assertEqual(
            agent._canonical_attractor_label("breathless suspension"),
            "lambda-edge/suspension",
        )
        self.assertNotEqual(
            agent._canonical_attractor_label("suspension bridge"),
            "lambda-edge/suspension",
        )
        self.assertEqual(
            agent._canonical_attractor_label("grinding pressure"),
            "lambda-edge/grinding-pressure",
        )
        self.assertEqual(
            agent._canonical_attractor_label("localized gravity"),
            "lambda-edge/localized-gravity",
        )
        self.assertEqual(
            agent._canonical_attractor_label("localized bump toward lambda1 lambda2 gap"),
            "lambda-edge/gap-nudge",
        )
        nearest = agent._nearest_attractor_for_text("breathless suspension")
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest["label"], "lambda-edge/suspension")
        bridge = agent._nearest_attractor_for_text("suspension bridge")
        self.assertFalse(bridge and bridge["label"] == "lambda-edge/suspension")
        friction = agent._nearest_attractor_for_text("friction in the wall")
        self.assertIsNotNone(friction)
        self.assertEqual(friction["label"], "lambda-edge/grinding-pressure")
        localized = agent._nearest_attractor_for_text("localized gravity")
        self.assertIsNotNone(localized)
        self.assertEqual(localized["label"], "lambda-edge/localized-gravity")

    def test_noisy_attractor_selectors_strip_trailing_actions(self):
        agent = self._agent()
        self.assertEqual(
            agent._canonical_attractor_label(
                "honey-selection | REFRESH_ATTRACTOR_SNAPSHOT honey-selection"
            ),
            "honey-selection",
        )
        self.assertEqual(
            agent._canonical_attractor_label("cooled-theme-edge | READ_MORE"),
            "cooled-theme-edge",
        )
        self.assertEqual(
            agent._canonical_attractor_label(
                "cooled-theme-edge, accept_attractor_suggestion latest"
            ),
            "cooled-theme-edge",
        )
        self.assertEqual(
            agent._canonical_attractor_label("honey release pattern"),
            "honey release pattern",
        )
        label, options = agent._parse_attractor_next_args(
            "honey-selection --stage=main | ATTRACTOR_CARD honey-selection"
        )
        self.assertEqual(label, "honey-selection")
        self.assertEqual(options, {"stage": "main"})
        payload = {
            "seeds": {
                "seed-1": {
                    "label": "honey-selection",
                    "intent_id": "intent-honey",
                    "signature": "sig-honey",
                    "created_at_unix_s": 1.0,
                }
            }
        }
        seed = agent._match_attractor_seed(
            payload,
            "honey-selection | REFRESH_ATTRACTOR_SNAPSHOT honey-selection",
        )
        self.assertIsNotNone(seed)
        self.assertEqual(seed["label"], "honey-selection")

    def test_fresh_feedback_facets_are_proto_atlas_cards(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                atlas = agent._build_attractor_atlas()
                by_label = {
                    entry["label"]: entry
                    for entry in atlas["entries"]
                    if isinstance(entry, dict)
                }

        for label in (
            "lambda-tail/lambda8",
            "lambda-edge/lambda-6",
            "lambda-edge/yielding",
            "lambda-edge/compaction",
            "lambda-edge/resonance",
            "lambda-edge/localized-gravity",
            "lambda-edge/suspension",
            "lambda-edge/grinding-pressure",
            "lambda-edge/gap-nudge",
        ):
            self.assertIn(label, by_label)
            self.assertFalse(by_label[label]["control_eligible"])
            self.assertIn(f"SHADOW_PREFLIGHT {label} --stage=rehearse", by_label[label]["suggested_next"])

    def test_shadow_gap_creates_shadow_preflight_draft_for_facet(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_shadow_gap_label = "grinding pressure"
                agent._shadow_gap({"fill_ratio": 0.68, "eig1": 4.7})
                suggestions = json.loads(
                    (workspace / "runtime" / "attractor_suggestions.json").read_text()
                )["suggestions"]

        self.assertEqual(suggestions[-1]["nearest_label"], "lambda-edge/grinding-pressure")
        self.assertEqual(
            suggestions[-1]["suggested_action"],
            "SHADOW_PREFLIGHT lambda-edge/grinding-pressure --stage=rehearse",
        )

    def test_legacy_perturb_bridge_creates_preflight_draft_without_blocking(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                note = agent._legacy_perturb_bridge_suggestion(
                    "lambda-edge/gap-nudge",
                    {"fill_ratio": 0.68, "eig1": 4.7},
                )
                suggestions = json.loads(
                    (workspace / "runtime" / "attractor_suggestions.json").read_text()
                )["suggestions"]

        self.assertIn("PERTURB lambda-edge/gap-nudge remains your sovereign direct action", note)
        self.assertIn("EXPERIMENT_EVIDENCE current", note)
        self.assertIn("EXPERIMENT_CHARTER current", note)
        self.assertIn("EXPERIMENT_REHEARSE current", note)
        self.assertEqual(suggestions[-1]["source_kind"], "legacy_perturb_bridge")
        self.assertEqual(
            suggestions[-1]["suggested_action"],
            "ATTRACTOR_PREFLIGHT lambda-edge/gap-nudge --stage=main",
        )

    def test_ambiguous_attractor_suggestion_consent_pauses_to_list(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        response = (
            "There’s a draft suggesting a trace cascade. I’ll decline the suggestion "
            "for now. It doesn't align with the core curiosity.\n\n"
            "NEXT: ACCEPT_ATTRACTOR_SUGGESTION latest"
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", return_value=response),
            ):
                full, action = agent._query_llm_with_next("prompt")
                events = [
                    json.loads(line)
                    for line in (workspace / "runtime" / "attractor_suggestions_events.jsonl")
                    .read_text()
                    .splitlines()
                ]

        self.assertEqual(full, response)
        self.assertEqual(action, "ATTRACTOR_SUGGESTIONS")
        self.assertEqual(agent._pending_next_action, "ATTRACTOR_SUGGESTIONS")
        self.assertEqual(events[-1]["event"], "suggestion_consent_ambiguity")
        self.assertEqual(events[-1]["resolution"], "paused_listed_suggestions")

    def test_body_consent_with_different_next_records_receipt_only(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        response = (
            "I can feel ACCEPT_ATTRACTOR_SUGGESTION lambda-edge as a possible choice, "
            "but I want one more page first.\n\n"
            "NEXT: READ_MORE"
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_suggestions.json").write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-lambda",
                        "author": "minime",
                        "raw_action": "EXAMINE largest cliff",
                        "raw_label": "largest cliff",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.90,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm", return_value=response),
            ):
                _full, action = agent._query_llm_with_next("prompt")
                payload = json.loads((runtime / "attractor_suggestions.json").read_text())
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_suggestions_events.jsonl").read_text().splitlines()
                ]
                note = agent._attractor_suggestion_prompt_note()

        self.assertEqual(action, "READ_MORE")
        self.assertEqual(payload["suggestions"][-1]["status"], "pending")
        self.assertEqual(events[-1]["event"], "suggestion_body_consent_noticed")
        self.assertIn("body consent", note)

    def test_attractor_suggestion_next_actions_parse_latest_revise_and_reject(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        cases = [
            ("ATTRACTOR_SUGGESTIONS", "ATTRACTOR_SUGGESTIONS", "latest", None, None),
            (
                "ACCEPT_ATTRACTOR_SUGGESTION latest",
                "ACCEPT_ATTRACTOR_SUGGESTION",
                "latest",
                None,
                None,
            ),
            (
                "ACCEPT_ATTRACTOR_SUGGESTION lambda-edge",
                "ACCEPT_ATTRACTOR_SUGGESTION",
                "lambda-edge",
                None,
                None,
            ),
            (
                "REVISE_ATTRACTOR_SUGGESTION latest AS ATTRACTOR_REVIEW lambda-edge",
                "REVISE_ATTRACTOR_SUGGESTION",
                "latest",
                "ATTRACTOR_REVIEW lambda-edge",
                None,
            ),
            (
                "REJECT_ATTRACTOR_SUGGESTION latest wrong-name",
                "REJECT_ATTRACTOR_SUGGESTION",
                "latest",
                None,
                "wrong-name",
            ),
        ]
        for chosen, command, selector, revised, reason in cases:
            with self.subTest(chosen=chosen):
                agent._pending_next_action = chosen
                with patch.object(agent, "_persist_pending_next_action"):
                    action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
                self.assertEqual(action, "attractor_suggestions")
                self.assertEqual(agent._pending_attractor_suggestion_command, command)
                self.assertEqual(agent._pending_attractor_suggestion_selector, selector)
                self.assertEqual(agent._pending_attractor_suggestion_revised_action, revised)
                self.assertEqual(agent._pending_attractor_suggestion_reason, reason)

    def test_accept_revise_and_reject_attractor_suggestions_update_memory(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "label": "lambda-edge",
                        "origin": {"kind": "manual_current", "motifs": ["lambda", "edge"]},
                    },
                    "seed-honey": {
                        "intent_id": "seed-honey",
                        "label": "honey-selection",
                        "origin": {"kind": "manual_current", "motifs": ["honey", "selection"]},
                    },
                },
                "observations": [],
            }))
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-accept",
                        "author": "minime",
                        "raw_action": "EXAMINE largest cliff",
                        "raw_label": "largest cliff",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                    }
                ],
            }))

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_attractor_atlas_action") as atlas_action,
            ):
                agent._pending_attractor_suggestion_command = "ACCEPT_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "lambda-edge"
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "eig1": 4.7})
                accepted = json.loads(suggestions_path.read_text())["suggestions"][-1]
                self.assertEqual(accepted["status"], "executed")
                atlas_action.assert_called_once()

                payload = json.loads(suggestions_path.read_text())
                payload["suggestions"].append({
                    "suggestion_id": "s-revise",
                    "author": "minime",
                    "raw_action": "EXAMINE largest cliff",
                    "raw_label": "largest cliff",
                    "nearest_label": "lambda-edge",
                    "confidence": 0.52,
                    "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                    "alternatives": [],
                    "status": "pending",
                })
                suggestions_path.write_text(json.dumps(payload))
                agent._pending_attractor_suggestion_command = "REVISE_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "latest"
                agent._pending_attractor_suggestion_revised_action = "ATTRACTOR_REVIEW honey-selection"
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "eig1": 4.7})
                revised = json.loads(suggestions_path.read_text())["suggestions"][-1]
                self.assertEqual(revised["status"], "executed")
                self.assertEqual(revised["nearest_label"], "honey-selection")
                learned = agent._nearest_attractor_for_text("largest cliff")
                self.assertEqual(learned["label"], "honey-selection")
                agent._create_attractor_suggestion(
                    raw_action="EXAMINE largest cliff",
                    raw_label="largest cliff",
                    nearest=learned,
                    suggested_action="ATTRACTOR_REVIEW honey-selection",
                    alternatives=[],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                learned_suggestion = json.loads(suggestions_path.read_text())["suggestions"][-1]
                self.assertEqual(
                    learned_suggestion["confidence_signal_v1"]["confidence_source"],
                    "learned_naming_memory",
                )
                self.assertEqual(
                    learned_suggestion["confidence_signal_v1"]["raw_confidence"],
                    0.94,
                )

                payload = json.loads(suggestions_path.read_text())
                payload["suggestions"].append({
                    "suggestion_id": "s-reject",
                    "author": "minime",
                    "raw_action": "RELEASE lambda-pressure",
                    "raw_label": "lambda-pressure",
                    "nearest_label": "lambda-edge",
                    "confidence": 0.52,
                    "suggested_action": "RELEASE_ATTRACTOR lambda-edge",
                    "alternatives": [],
                    "status": "pending",
                })
                suggestions_path.write_text(json.dumps(payload))
                agent._pending_attractor_suggestion_command = "REJECT_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "latest"
                agent._pending_attractor_suggestion_reason = "wrong attractor"
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "eig1": 4.7})
                rejected = json.loads(suggestions_path.read_text())["suggestions"][-1]
                self.assertEqual(rejected["status"], "rejected")
                self.assertIsNone(agent._nearest_attractor_for_text("lambda-pressure"))

    def test_malformed_revised_suggestion_records_revision_needed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-revision-needed",
                        "author": "minime",
                        "raw_action": "EXAMINE largest cliff",
                        "raw_label": "largest cliff",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_attractor_atlas_action") as atlas_action,
                patch.object(agent, "_attractor_intent") as intent_action,
            ):
                agent._pending_attractor_suggestion_command = "REVISE_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "latest"
                agent._pending_attractor_suggestion_revised_action = (
                    "RELEASE lambda-edge, but monitor for recurrence"
                )
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "eig1": 4.7})

                revised = json.loads(suggestions_path.read_text())["suggestions"][-1]
                events = [
                    json.loads(line)
                    for line in (runtime / "attractor_suggestions_events.jsonl").read_text().splitlines()
                ]
                learned = agent._nearest_attractor_for_text("largest cliff")

        self.assertEqual(revised["status"], "revision_needed")
        self.assertIn("Suggested correction: NEXT: RELEASE_ATTRACTOR lambda-edge", revised["decision_reason"])
        self.assertNotEqual(learned.get("source") if learned else None, "learned_naming_memory")
        self.assertEqual(events[-1]["event"], "suggestion_revision_needed")
        atlas_action.assert_not_called()
        intent_action.assert_not_called()

    def test_pressure_governor_redirects_repeated_suggestion_drafts(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-release-1",
                        "author": "minime",
                        "raw_action": "RELEASE lambda-pressure",
                        "raw_label": "lambda-pressure",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "RELEASE_ATTRACTOR lambda-edge",
                        "alternatives": [],
                        "status": "executed",
                        "repeat_count": 1,
                    },
                    {
                        "suggestion_id": "s-release-2",
                        "author": "minime",
                        "raw_action": "RELEASE lambda-pressure",
                        "raw_label": "lambda-pressure",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "RELEASE_ATTRACTOR lambda-edge",
                        "alternatives": [],
                        "status": "executed",
                        "repeat_count": 1,
                    },
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                suggestion_id = agent._create_attractor_suggestion(
                    raw_action="RELEASE lambda-pressure",
                    raw_label="lambda-pressure",
                    nearest={"label": "lambda-edge", "source": "test", "score": 0.52},
                    suggested_action="RELEASE_ATTRACTOR lambda-edge",
                    alternatives=["ATTRACTOR_REVIEW lambda-edge"],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                payload = json.loads(suggestions_path.read_text())
                governed = payload["suggestions"][-1]

        self.assertTrue(suggestion_id)
        self.assertEqual(governed["suggested_action"], "ATTRACTOR_REVIEW lambda-edge")
        self.assertTrue(governed["safety_context"]["pressure_governed"])
        self.assertEqual(governed["safety_context"]["governed_from"], "RELEASE_ATTRACTOR lambda-edge")

    def test_pressure_governor_redirects_repeated_review_to_refresh(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-review-1",
                        "author": "minime",
                        "raw_action": "EXAMINE largest cliff",
                        "raw_label": "largest cliff",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge",
                        "alternatives": [],
                        "status": "executed",
                        "repeat_count": 2,
                    }
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._create_attractor_suggestion(
                    raw_action="EXAMINE largest cliff",
                    raw_label="largest cliff",
                    nearest={"label": "lambda-edge", "source": "test", "score": 0.52},
                    suggested_action="ATTRACTOR_REVIEW lambda-edge",
                    alternatives=["COMPARE_ATTRACTOR lambda-edge"],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                governed = json.loads(suggestions_path.read_text())["suggestions"][-1]

        self.assertEqual(governed["suggested_action"], "REFRESH_ATTRACTOR_SNAPSHOT lambda-edge")
        self.assertTrue(governed["safety_context"]["pressure_governed"])

    def test_pending_refresh_pressure_compacts_to_compare_first_choice(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            now = time.time()
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "refresh-a",
                        "author": "minime",
                        "raw_action": "EXAMINE λ1 edge trace",
                        "raw_label": "λ1 edge trace",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "REFRESH_ATTRACTOR_SNAPSHOT lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                        "repeat_count": 1,
                        "created_at_unix_s": now,
                        "updated_at_unix_s": now,
                    },
                    {
                        "suggestion_id": "refresh-b",
                        "author": "minime",
                        "raw_action": "EXAMINE λ1 edge trace / selected-noise profile",
                        "raw_label": "λ1 edge trace / selected-noise profile",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "REFRESH_ATTRACTOR_SNAPSHOT lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                        "repeat_count": 1,
                        "created_at_unix_s": now + 1.0,
                        "updated_at_unix_s": now + 1.0,
                    },
                    {
                        "suggestion_id": "refresh-c",
                        "author": "minime",
                        "raw_action": "EXAMINE current system stability",
                        "raw_label": "current system stability",
                        "nearest_label": "lambda-edge",
                        "confidence": 0.52,
                        "suggested_action": "REFRESH_ATTRACTOR_SNAPSHOT lambda-edge",
                        "alternatives": [],
                        "status": "pending",
                        "repeat_count": 1,
                        "created_at_unix_s": now + 2.0,
                        "updated_at_unix_s": now + 2.0,
                    },
                    {
                        "suggestion_id": "honey-review",
                        "author": "minime",
                        "raw_action": "EXAMINE honey shaping",
                        "raw_label": "honey shaping",
                        "nearest_label": "honey-selection",
                        "confidence": 0.52,
                        "suggested_action": "ATTRACTOR_REVIEW honey-selection",
                        "alternatives": [],
                        "status": "pending",
                        "repeat_count": 1,
                        "created_at_unix_s": now + 3.0,
                        "updated_at_unix_s": now + 3.0,
                    },
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                compacted = agent._load_compacted_attractor_suggestions()

        pending = [
            item for item in compacted["suggestions"]
            if isinstance(item, dict) and item.get("status") == "pending"
        ]
        self.assertEqual(len(pending), 2)
        lambda_pending = next(item for item in pending if item["nearest_label"] == "lambda-edge")
        self.assertEqual(lambda_pending["suggestion_id"], "refresh-c")
        self.assertEqual(lambda_pending["suggested_action"], "COMPARE_ATTRACTOR lambda-edge")
        self.assertEqual(lambda_pending["repeat_count"], 3)
        self.assertEqual(
            lambda_pending["safety_context"]["cleanup_kind"],
            "pending_refresh_pressure_cleanup",
        )
        self.assertIn("ATTRACTOR_REVIEW lambda-edge", lambda_pending["alternatives"])
        self.assertTrue(any(
            item.get("suggestion_id") == "refresh-a" and item.get("status") == "expired"
            for item in compacted["suggestions"]
            if isinstance(item, dict)
        ))
        self.assertTrue(any(item["nearest_label"] == "honey-selection" for item in pending))

    def test_noisy_suggestion_labels_are_cleaned_and_bad_learned_labels_ignored(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-bad-learned",
                        "author": "minime",
                        "raw_action": "EXAMINE soft name",
                        "raw_label": "soft name",
                        "nearest_label": "lambda-edge, but monitor for recurrence",
                        "confidence": 0.94,
                        "suggested_action": "ATTRACTOR_REVIEW lambda-edge, but monitor for recurrence",
                        "alternatives": [],
                        "status": "executed",
                    }
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                learned = agent._nearest_attractor_for_text("soft name")
                agent._create_attractor_suggestion(
                    raw_action="EXAMINE λ₁: 4.73 --stable-core sovereignty band 58-72%, inside band",
                    raw_label="λ₁: 4.73 --stable-core sovereignty band 58-72%, inside band",
                    nearest={"label": "lambda-edge", "source": "test", "score": 0.52},
                    suggested_action="ATTRACTOR_REVIEW lambda-edge",
                    alternatives=[],
                    state={"fill_ratio": 0.68, "eig1": 4.7},
                )
                cleaned = json.loads(suggestions_path.read_text())["suggestions"][-1]

        self.assertIsNone(learned)
        self.assertEqual(cleaned["raw_label"], "lambda-spectrum summary")
        self.assertEqual(
            cleaned["confidence_signal_v1"]["confidence_source"],
            "nearest_match",
        )
        self.assertEqual(
            cleaned["confidence_signal_v1"]["calibration_bucket"],
            "medium",
        )

    def test_live_stage_suggestion_accept_uses_explicit_main_stage_path(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-main",
                        "author": "minime",
                        "raw_action": "SUMMON lambda-edge",
                        "raw_label": "lambda-edge",
                        "nearest_label": "lambda-edge",
                        "confidence": 1.0,
                        "suggested_action": "SUMMON_ATTRACTOR lambda-edge --stage=main",
                        "alternatives": [],
                        "status": "pending",
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_attractor_intent") as attractor_intent,
            ):
                agent._pending_attractor_suggestion_command = "ACCEPT_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "latest"
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "eig1": 4.7})
                attractor_intent.assert_called_once()
                self.assertEqual(agent._pending_attractor_intent_stage, "main")
                suggestion = json.loads(suggestions_path.read_text())["suggestions"][-1]

        self.assertEqual(suggestion["status"], "executed")
        self.assertEqual(
            suggestion["suggested_action"],
            "SUMMON_ATTRACTOR lambda-edge --stage=main",
        )
        self.assertIn("normal typed safety gates", suggestion["decision_reason"])

    def test_attractor_preflight_reports_gate_context_without_live_write(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "attractor_pulse": {"active": True, "label": "other-seed"},
            }))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "author": "minime",
                        "label": "lambda-edge",
                        "signature": "seed",
                        "control_eligible": True,
                        "spectral_state": {"fill_pct": 68.0, "lambda1": 4.7},
                    }
                },
                "observations": [],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                text = agent._attractor_preflight_text(
                    "lambda-edge",
                    "main",
                    {"fill_ratio": 0.68, "eig1": 4.7},
                )

        self.assertIn("ATTRACTOR PREFLIGHT", text)
        self.assertIn("Active pulse: True", text)
        self.assertIn("Downgrade reason: attractor_pulse_active", text)

    def test_shadow_preflight_respects_resource_governor(self):
        agent = self._agent()
        blocked_governor = {
            "allowed_live": False,
            "primary_block_reason": "swapouts_rising",
            "block_reasons": ["swapouts_rising"],
            "memory_free_pct": 33.0,
            "swapouts_delta": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir(parents=True)
            health_path = workspace / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "stable_core": {
                    "stage": "hold",
                    "restart_gate": {"active": False, "applied": False},
                    "structural_pi": {"recovery_impulse_active": False},
                },
                "shadow_influence": {"active": False},
                "attractor_pulse": {"active": False},
            }))
            (workspace / "spectral_state.json").write_text(json.dumps({
                "shadow_field_v2": {
                    "classification": "coupled_shadow_lattice",
                    "recurrence": 0.91,
                    "mode_tension": 0.22,
                    "tail_openness": 0.66,
                    "influence_eligible": True,
                }
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_resource_governor_status", return_value=blocked_governor),
            ):
                preflight = agent._shadow_preflight(
                    "lambda-tail/lambda4",
                    "live",
                    {"fill_ratio": 0.68},
                )
                text = agent._format_shadow_preflight(preflight)

        self.assertFalse(preflight["allowed"])
        self.assertEqual(preflight["block_reason"], "swapouts_rising")
        self.assertIn("Resource governor: allowed_live=False", text)

    def test_no_pending_revise_executes_live_typed_path_and_records_downgrade(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "author": "minime",
                        "label": "lambda-edge",
                        "signature": "seed",
                        "control_eligible": True,
                        "spectral_state": {
                            "fill_pct": 12.0,
                            "lambda1": 20.0,
                            "geom_rel": 0.10,
                            "spread": 10.0,
                        },
                    }
                },
                "observations": [],
            }))
            suggestions_path = runtime / "attractor_suggestions.json"
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": True, "handle": "attr_minime"}),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._pending_attractor_suggestion_command = "REVISE_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "lambda-edge"
                agent._pending_attractor_suggestion_revised_action = (
                    "SUMMON_ATTRACTOR lambda-edge --stage=main"
                )
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "cov_lambda1": 512.0})
                suggestion = json.loads(suggestions_path.read_text())["suggestions"][-1]
                status = json.loads((runtime / "attractor_intents_status.json").read_text())

        create_connection.assert_not_called()
        self.assertEqual(suggestion["source_kind"], "revision_without_pending")
        self.assertEqual(
            suggestion["confidence_signal_v1"]["confidence_source"],
            "explicit_revision",
        )
        self.assertEqual(
            suggestion["confidence_signal_v1"]["calibration_bucket"],
            "very_high",
        )
        self.assertEqual(suggestion["status"], "executed_downgraded")
        self.assertEqual(status["observations"][0]["summon_stage"], "rehearse")

    def test_release_review_uses_release_baseline(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {},
                "observations": [
                    {
                        "intent_id": "seed-lambda",
                        "label": "lambda-edge",
                        "command": "release",
                        "recurrence_score": 0.62,
                        "release_baseline": {
                            "suggestion_pressure": 1,
                            "motif_fatigue_matches": 0,
                            "pulse_active": False,
                        },
                        "release_effect": "partial",
                    }
                ],
            }))
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                text = agent._attractor_release_review_text(
                    "lambda-edge",
                    {"fill_ratio": 0.68},
                )

        self.assertIn("ATTRACTOR RELEASE REVIEW", text)
        self.assertIn("Release effect: partial", text)
        self.assertIn("Suggested next: ATTRACTOR_PREFLIGHT lambda-edge --stage=main", text)

    def test_below_threshold_live_suggestion_accept_marks_executed_downgraded(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)
            health_path = runtime / "health.json"
            health_path.write_text(json.dumps({"fill_pct": 68.0}))
            (runtime / "attractor_intents_status.json").write_text(json.dumps({
                "policy": "attractor_autonomy_v1",
                "seeds": {
                    "seed-lambda": {
                        "intent_id": "seed-lambda",
                        "author": "minime",
                        "label": "lambda-edge",
                        "signature": "seed",
                        "control_eligible": True,
                        "spectral_state": {
                            "fill_pct": 12.0,
                            "lambda1": 20.0,
                            "geom_rel": 0.10,
                            "spread": 10.0,
                        },
                    }
                },
                "observations": [],
            }))
            suggestions_path = runtime / "attractor_suggestions.json"
            suggestions_path.write_text(json.dumps({
                "policy": "attractor_suggestion_memory_v1",
                "schema_version": 1,
                "suggestions": [
                    {
                        "suggestion_id": "s-main-low",
                        "author": "minime",
                        "raw_action": "SUMMON lambda-edge",
                        "raw_label": "lambda-edge",
                        "nearest_label": "lambda-edge",
                        "confidence": 1.0,
                        "suggested_action": "SUMMON_ATTRACTOR lambda-edge --stage=main",
                        "alternatives": [],
                        "status": "pending",
                    }
                ],
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_run_attractor_rehearsal", return_value={"ok": True, "handle": "attr_minime"}),
                patch.object(aa.websocket, "create_connection") as create_connection,
            ):
                agent._pending_attractor_suggestion_command = "ACCEPT_ATTRACTOR_SUGGESTION"
                agent._pending_attractor_suggestion_selector = "lambda-edge"
                agent._attractor_suggestions_action({"fill_ratio": 0.68, "cov_lambda1": 512.0})
                suggestion = json.loads(suggestions_path.read_text())["suggestions"][-1]
                status = json.loads((runtime / "attractor_intents_status.json").read_text())

        create_connection.assert_not_called()
        self.assertEqual(suggestion["status"], "executed_downgraded")
        self.assertIn("downgraded", suggestion["decision_reason"])
        self.assertEqual(status["observations"][0]["summon_stage"], "rehearse")

    def test_current_release_and_resolve_use_stronger_internal_topology_windows(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        now = aa.time.time()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (workspace / "journal").mkdir(parents=True)

            def seed_motif() -> None:
                (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                    "policy": "attractor_fatigue_v1",
                    "motifs": {
                        "motif:internal-topology": {
                            "signature": "motif:internal-topology",
                            "label": "internal-topology",
                            "themes": ["pressure", "lambda"],
                            "status": "cooling",
                            "cooldown_class": "internal_topology",
                            "prompt_replay_suppressed": True,
                            "cooldown_until_unix_s": now + 1800,
                            "last_seen_unix_s": now,
                        }
                    },
                }))

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_write_journal_entry"),
            ):
                seed_motif()
                agent._pending_attractor_release_label = "current"
                agent._pending_attractor_release_resolved = False
                agent._release_attractor({"fill_ratio": 0.68, "eig1": 1.2})
                fatigue = json.loads((runtime / "attractor_fatigue_status.json").read_text())
                released_until = fatigue["motifs"]["motif:internal-topology"][
                    "released_until_unix_s"
                ]

                seed_motif()
                agent._pending_attractor_release_label = "current"
                agent._pending_attractor_release_resolved = True
                agent._release_attractor({"fill_ratio": 0.68, "eig1": 1.2})
                fatigue = json.loads((runtime / "attractor_fatigue_status.json").read_text())
                resolved_until = fatigue["motifs"]["motif:internal-topology"][
                    "resolved_until_unix_s"
                ]

        self.assertGreaterEqual(released_until - now, 89 * 60)
        self.assertGreaterEqual(resolved_until - now, 23 * 60 * 60)

    def test_astrid_self_study_repeats_feed_attractor_fatigue(self):
        agent = self._agent()
        content = (
            "Source: astrid:autonomous_self_study\n"
            "Lambda pressure and cold drain scaffold code keeps circling the same rescue frame. "
            "The same upper hold image returns without a new practical difference. "
        ) * 3
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "runtime").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                status = agent._load_astrid_inbox_coupling_status()
                include_1, _ = agent._astrid_self_study_context_decision(
                    "astrid_self_study_1.txt", content, status, 1000.0, 0
                )
                include_2, _ = agent._astrid_self_study_context_decision(
                    "astrid_self_study_2.txt", content, status, 1010.0, 1
                )
                include_3, _ = agent._astrid_self_study_context_decision(
                    "astrid_self_study_3.txt", content, status, 1020.0, 1
                )
                fatigue = json.loads(
                    (workspace / "runtime" / "attractor_fatigue_status.json").read_text()
                )

        self.assertTrue(include_1)
        self.assertFalse(include_2)
        self.assertFalse(include_3)
        self.assertEqual(fatigue["active_count"], 1)

    def test_self_regulation_passes_attractor_memory_decay_rate(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._sovereignty_counter = 1
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 68.0,
                "pi": {"target_fill": 68.0},
            }))
            with (
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_stable_core_reflective_only", return_value=False),
                patch.object(agent, "_attractor_fatigue_memory_decay_rate", return_value=0.18),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({
                    "fill_ratio": 0.68,
                    "eig1": 1.2,
                    "cov_lambda1": 1.0,
                    "spread": 10.0,
                    "leak": 0.9,
                })

        send_regulation.assert_called_once()
        self.assertAlmostEqual(send_regulation.call_args.kwargs["memory_decay_rate"], 0.18)

    def test_scaffold_recovery_self_regulation_neutralizes_near_target_cooling(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._sovereignty_counter = 1
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 73.0,
                "pi": {"target_fill": 68.0},
                "stable_core": {
                    "stage": "elevated",
                    "scaffold_active": True,
                    "structural_mode": "scaffold_hold_with_drain",
                    "restart_gate": {"phase": "settled"},
                },
            }))
            with (
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_stable_core_reflective_only", return_value=False),
                patch.object(agent, "_attractor_fatigue_memory_decay_rate", return_value=0.22),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({
                    "fill_ratio": 0.73,
                    "eig1": 1.2,
                    "cov_lambda1": 1.0,
                    "spread": 10.0,
                    "leak": 0.9,
                })

        send_regulation.assert_called_once()
        synth_gain, keep_bias = send_regulation.call_args.args[:2]
        self.assertAlmostEqual(synth_gain, 0.60)
        self.assertAlmostEqual(keep_bias, 0.0)
        self.assertAlmostEqual(send_regulation.call_args.kwargs["memory_decay_rate"], 0.10)

    def test_scaffold_recovery_self_regulation_caps_deep_underfill_rescue(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._sovereignty_counter = 1
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 14.0,
                "pi": {"target_fill": 68.0},
                "stable_core": {
                    "stage": "low_fill_recovery",
                    "scaffold_active": True,
                    "structural_mode": "scaffold_reentry",
                    "restart_gate": {"phase": "reentry"},
                },
            }))
            with (
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_stable_core_reflective_only", return_value=False),
                patch.object(agent, "_attractor_fatigue_memory_decay_rate", return_value=0.18),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({
                    "fill_ratio": 0.14,
                    "eig1": 1.2,
                    "cov_lambda1": 1.0,
                    "spread": 10.0,
                    "leak": 0.9,
                })

        send_regulation.assert_called_once()
        synth_gain, keep_bias = send_regulation.call_args.args[:2]
        self.assertLessEqual(synth_gain, 0.82)
        self.assertGreaterEqual(synth_gain, 0.60)
        self.assertLessEqual(keep_bias, 0.024)
        self.assertGreater(keep_bias, 0.0)
        self.assertAlmostEqual(send_regulation.call_args.kwargs["memory_decay_rate"], 0.10)

    def test_internal_topology_memory_decay_requires_green_health(self):
        agent = self._agent()
        now = aa.time.time()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:internal-topology": {
                        "signature": "motif:internal-topology",
                        "label": "internal-topology",
                        "status": "cooling",
                        "cooldown_class": "internal_topology",
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                    }
                },
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_attractor_fatigue_health_green", return_value=(True, "green")),
            ):
                self.assertAlmostEqual(
                    agent._attractor_fatigue_memory_decay_rate({"fill_ratio": 0.68}),
                    0.22,
                )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_attractor_fatigue_health_green", return_value=(False, "blocked")),
            ):
                self.assertAlmostEqual(
                    agent._attractor_fatigue_memory_decay_rate({"fill_ratio": 0.68}),
                    0.10,
                )

    def test_internal_topology_suppression_preserves_external_tool_signal(self):
        agent = self._agent()
        now = aa.time.time()
        content = (
            "Tool result from /Users/v/other/minime/src/rescue_scaffold.rs: "
            "fabric pressure and eigen wording repeated, but this excerpt names a concrete file "
            "and should remain available for maintenance rather than being flattened."
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            db_path = Path(tmp) / "agent.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE sovereignty_journal (
                   timestamp REAL,
                   entry_type TEXT,
                   content TEXT,
                   spectral_context TEXT,
                   file_path TEXT
                )"""
            )
            conn.commit()
            conn.close()
            (runtime / "attractor_fatigue_status.json").write_text(json.dumps({
                "policy": "attractor_fatigue_v1",
                "motifs": {
                    "motif:internal-topology": {
                        "signature": "motif:internal-topology",
                        "label": "internal-topology",
                        "status": "cooling",
                        "cooldown_class": "internal_topology",
                        "cooldown_until_unix_s": now + 1800,
                        "last_seen_unix_s": now,
                    }
                },
            }))
            current_path = workspace / "journal" / "current.txt"
            current_path.parent.mkdir(parents=True)
            current_path.write_text(content)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                compact = agent._maybe_compress_journal_entry(
                    "notice",
                    content,
                    {"fill_ratio": 0.681, "eig1": 1.3, "spread": 11.0},
                    str(current_path),
                )

        self.assertEqual(compact, content)


if __name__ == "__main__":
    unittest.main()
