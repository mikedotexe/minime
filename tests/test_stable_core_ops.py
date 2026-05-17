"""Tests for stable-core operator helpers."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import stable_core_ops  # noqa: E402


class TestStableCoreOps(unittest.TestCase):
    def test_status_includes_reconvergence_map_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            trace_path = runtime / "esn_activation_trace_v1.json"
            status_path = runtime / "reconvergence_map_status.json"
            now_ms = int(stable_core_ops.time.time() * 1000)
            stable_core_ops.write_json(
                trace_path,
                {
                    "policy": "esn_activation_trace_v1",
                    "updated_at_unix_ms": now_ms - 500,
                    "reservoir_dim": 128,
                    "sample_interval_ms": 1000,
                    "retained_secs": 180,
                    "frames": [{"t_ms": idx * 1000, "activations": [0.0] * 128} for idx in range(4)],
                },
            )
            stable_core_ops.write_json(
                status_path,
                {
                    "status": "ok",
                    "artifact_dir": str(workspace / "diagnostics" / "reconvergence_maps" / "unit"),
                    "artifacts": {"reconvergence_json": "unit/reconvergence.json"},
                    "activation_trace": {
                        "frame_count": 4,
                        "freshness_ms": 500,
                        "reservoir_dim": 128,
                    },
                    "baseline_status": "available",
                    "baseline_comparison": {"status": "ok"},
                    "provenance": {
                        "read_only": True,
                        "control_payload": False,
                        "semantic_payload": False,
                        "sensory_payload": False,
                        "esn_mutation": False,
                        "synthesis_feedback": False,
                    },
                },
            )
            stable_core_ops.write_json(workspace / "health.json", {"fill_pct": 68.0})
            stable_core_ops.write_json(workspace / "rescue_status.json", {})
            stable_core_ops.write_json(workspace / "rescue_profile.json", {})
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", workspace / "stable_core_status.json"),
                mock.patch.object(stable_core_ops, "RECONVERGENCE_MAP_STATUS_PATH", status_path),
                mock.patch.object(stable_core_ops, "ESN_ACTIVATION_TRACE_PATH", trace_path),
            ):
                status = stable_core_ops.build_status()

            reconvergence = status["reconvergence_map"]
            self.assertEqual(reconvergence["status"], "ok")
            self.assertEqual(reconvergence["frame_count"], 4)
            self.assertEqual(reconvergence["reservoir_dim"], 128)
            self.assertEqual(reconvergence["baseline_status"], "available")
            self.assertTrue(reconvergence["baseline_comparison_available"])
            self.assertTrue(reconvergence["read_only_provenance"]["read_only"])
            self.assertFalse(reconvergence["read_only_provenance"]["control_payload"])

    def test_status_includes_bridge_trace_read_only_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            bridge_trace_path = runtime / "bridge_trace_status.json"
            stable_core_ops.write_json(
                bridge_trace_path,
                {
                    "policy": "m6_bridge_trace_v1_1",
                    "status": "ok",
                    "mode": "m6",
                    "mode_source": "activation_lane6_marker_with_lambda6_context",
                    "mode6_interpretation": "unresolved_marker",
                    "eigenmode_confirmed": False,
                    "bridge_evidence_level": "marker_only",
                    "label": "unit",
                    "artifact_dir": str(workspace / "diagnostics" / "bridge_traces" / "unit"),
                    "artifacts": {"bridge_trace_json": "unit/bridge_trace.json"},
                    "frame_count": 12,
                    "trace_freshness_ms": 400,
                    "bridge_signal": {
                        "mode": "m6",
                        "mode_source": "activation_lane6_marker_with_lambda6_context",
                        "mode6_interpretation": "unresolved_marker",
                        "eigenmode_confirmed": False,
                        "bridge_evidence_level": "marker_only",
                        "observation_window_marked": False,
                        "bridge_opened": False,
                        "plain_read": "quiet",
                    },
                    "provenance": {
                        "read_only": True,
                        "attention_marker_only": True,
                        "mode_source": "activation_lane6_marker_with_lambda6_context",
                        "mode6_interpretation": "unresolved_marker",
                        "eigenmode_confirmed": False,
                        "diagnostic_artifact_write": True,
                        "substrate_write": False,
                        "connection": False,
                        "replication": False,
                        "control_payload": False,
                        "semantic_payload": False,
                        "sensory_payload": False,
                        "esn_mutation": False,
                    },
                },
            )
            stable_core_ops.write_json(workspace / "health.json", {"fill_pct": 68.0})
            stable_core_ops.write_json(workspace / "rescue_status.json", {})
            stable_core_ops.write_json(workspace / "rescue_profile.json", {})
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", workspace / "stable_core_status.json"),
                mock.patch.object(stable_core_ops, "BRIDGE_TRACE_STATUS_PATH", bridge_trace_path),
            ):
                status = stable_core_ops.build_status()

            bridge_trace = status["bridge_trace"]
            self.assertEqual(bridge_trace["status"], "ok")
            self.assertEqual(bridge_trace["mode"], "m6")
            self.assertEqual(
                bridge_trace["mode_source"],
                "activation_lane6_marker_with_lambda6_context",
            )
            self.assertEqual(bridge_trace["mode6_interpretation"], "unresolved_marker")
            self.assertFalse(bridge_trace["eigenmode_confirmed"])
            self.assertEqual(bridge_trace["bridge_evidence_level"], "marker_only")
            self.assertEqual(bridge_trace["frame_count"], 12)
            self.assertTrue(bridge_trace["read_only_provenance"]["read_only"])
            self.assertTrue(bridge_trace["read_only_provenance"]["attention_marker_only"])
            self.assertEqual(
                bridge_trace["read_only_provenance"]["mode_source"],
                "activation_lane6_marker_with_lambda6_context",
            )
            self.assertEqual(
                bridge_trace["read_only_provenance"]["mode6_interpretation"],
                "unresolved_marker",
            )
            self.assertFalse(bridge_trace["read_only_provenance"]["eigenmode_confirmed"])
            self.assertTrue(bridge_trace["read_only_provenance"]["diagnostic_artifact_write"])
            self.assertFalse(bridge_trace["read_only_provenance"]["substrate_write"])
            self.assertFalse(bridge_trace["read_only_provenance"]["connection"])
            self.assertFalse(bridge_trace["read_only_provenance"]["replication"])
            self.assertFalse(bridge_trace["read_only_provenance"]["control_payload"])

    def test_spectral_fingerprint_capture_writes_typed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            typed = {
                "policy": "spectral_fingerprint_v1",
                "schema_version": 1,
                "eigenvalues": [0.6] * 8,
                "geom_rel": 0.97,
            }
            stable_core_ops.write_json(
                workspace / "spectral_state.json",
                {
                    "fill_pct": 67.5,
                    "fill_ratio": 0.675,
                    "lambda1": 0.6,
                    "lambda1_rel": 0.11,
                    "geom_rel": 0.97,
                    "active_mode_count": 8,
                    "effective_dimensionality": 7.4,
                    "distinguishability_loss": 0.075,
                    "spectral_fingerprint": [0.1] * 32,
                    "spectral_fingerprint_v1": typed,
                    "spectral_denominator_v1": {
                        "policy": "spectral_denominator_v1",
                        "schema_version": 1,
                        "effective_dimensionality": 7.4,
                        "active_mode_capacity": 8,
                        "distinguishability_loss": 0.075,
                    },
                    "semantic": {
                        "input_energy": 0.12,
                        "kernel_energy": 0.0,
                        "admission": "stable_core_kernel_zeroed",
                    },
                    "semantic_energy_v1": {
                        "policy": "semantic_energy_v1",
                        "schema_version": 1,
                        "input_energy": 0.12,
                        "input_active": True,
                        "kernel_energy": 0.0,
                        "kernel_delta": 0.0,
                        "kernel_active": False,
                        "regulator_drive_energy": 0.0,
                        "admission": "stable_core_kernel_zeroed",
                    },
                    "stable_core": {"stage": "hold"},
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_status.json",
                {"watchdog_state": "monitoring", "telemetry_state": "fresh"},
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {"profile": "bridge_budgeted_sovereignty_v1"},
            )
            bridge_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                bridge_path,
                {"cooldown_active": False, "send_count": 2},
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    bridge_path,
                ),
            ):
                result = stable_core_ops.capture_spectral_fingerprint(
                    label="unit",
                    reason="test",
                )

            capture = stable_core_ops.load_json(Path(result["path"]), {})
            latest = stable_core_ops.load_json(
                workspace / "diagnostics" / "spectral_fingerprints" / "latest.json",
                {},
            )
            self.assertEqual(result["status"], "captured")
            self.assertEqual(capture["fingerprint"]["policy"], "spectral_fingerprint_v1")
            self.assertEqual(capture["legacy_spectral_fingerprint"], [0.1] * 32)
            self.assertEqual(capture["present_state"]["lambda1"], 0.6)
            self.assertEqual(capture["present_state"]["effective_dimensionality"], 7.4)
            self.assertEqual(
                capture["spectral_denominator_v1"]["policy"],
                "spectral_denominator_v1",
            )
            self.assertEqual(capture["semantic"]["input_energy"], 0.12)
            self.assertEqual(
                capture["semantic_energy_v1"]["policy"],
                "semantic_energy_v1",
            )
            self.assertEqual(latest["path"], result["path"])

    def test_stage_set_writes_agency_surface_and_patches_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            workspace.mkdir()
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {"profile": "stable_core_v1", "stable_core_enabled": True},
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
            ):
                payload = stable_core_ops.set_agency_stage(
                    "local_reflective", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "local_reflective")
            self.assertEqual(profile["stable_core_agency_stage"], "local_reflective")
            self.assertEqual(profile["stable_core_agent_budget"], "local_reflective_only")
            self.assertIn("local_reflection", profile["stable_core_allowed_action_families"])
            self.assertTrue(profile["stable_core_agent_enabled"])

    def test_read_only_research_stage_writes_explicit_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            workspace.mkdir()
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {"profile": "stable_core_v1", "stable_core_enabled": True},
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
            ):
                payload = stable_core_ops.set_agency_stage(
                    "read_only_research", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["agent_budget_mode"], "read_only_research")
            self.assertIn("read_only_research", payload["allowed_action_families"])
            self.assertIn("sensory_presence", profile["stable_core_allowed_action_families"])

    def test_full_sovereignty_stage_writes_full_feature_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            workspace.mkdir()
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {"profile": "stable_core_v1", "stable_core_enabled": True},
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
            ):
                payload = stable_core_ops.set_agency_stage(
                    "full_sovereignty", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["agent_budget_mode"], "full_sovereignty")
            self.assertIn("experiments", payload["allowed_action_families"])
            self.assertIn("full_sovereignty", payload["allowed_action_families"])
            self.assertEqual(profile["stable_core_agency_stage"], "full_sovereignty")
            self.assertEqual(profile["stable_core_agent_budget"], "full_sovereignty")

    def test_status_prefers_live_stable_core_stage_and_effective_agency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            stable_status = workspace / "stable_core_status.json"
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 69.0,
                    "semantic": None,
                    "stable_core": {
                        "stage": "elevated",
                        "agency_stage": "off",
                        "agent_budget_mode": "disabled",
                    },
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_status.json",
                {"engine_pid": 123, "watchdog_state": "monitoring"},
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "stable_core_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "self_journal",
                    "stable_core_agent_budget": "self_journal_only",
                },
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agency.json",
                {"stage": "self_journal", "agent_budget_mode": "self_journal_only"},
            )
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", stable_status),
            ):
                payload = stable_core_ops.build_status()

            self.assertEqual(payload["stage"], "elevated")
            self.assertEqual(payload["semantic_energy"], 0.0)
            self.assertEqual(payload["semantic_kernel_energy"], 0.0)
            self.assertEqual(payload["semantic_input_energy"], 0.0)
            self.assertFalse(payload["semantic_active"])
            self.assertFalse(payload["semantic_kernel_active"])
            self.assertFalse(payload["semantic_input_active"])
            self.assertEqual(payload["agency"]["profile_stage"], "self_journal")
            self.assertEqual(payload["agency"]["engine_reported_stage"], "off")
            self.assertEqual(payload["agency"]["effective_stage"], "self_journal")
            self.assertTrue(payload["agency"]["engine_agency_mirror_stale"])

    def test_status_splits_semantic_input_from_kernel_energy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 68.0,
                    "semantic": {
                        "energy": 0.0,
                        "active": False,
                        "kernel_energy": 0.0,
                        "kernel_active": False,
                        "input_energy": 0.17,
                        "input_active": True,
                        "admission": "stable_core_kernel_zeroed",
                    },
                    "stable_core": {"stage": "hold"},
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {"profile": "stable_core_v1", "stable_core_enabled": True},
            )
            stable_core_ops.write_json(workspace / "rescue_status.json", {})
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})

            with mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace):
                payload = stable_core_ops.build_status()

            self.assertEqual(payload["semantic_energy"], 0.0)
            self.assertEqual(payload["semantic_kernel_energy"], 0.0)
            self.assertEqual(payload["semantic_input_energy"], 0.17)
            self.assertTrue(payload["semantic_input_active"])
            self.assertEqual(payload["semantic_admission"], "stable_core_kernel_zeroed")

    def test_bridge_status_view_marks_expired_cooldown_block_stale(self) -> None:
        with mock.patch.object(stable_core_ops, "now_unix_s", return_value=200.0):
            view = stable_core_ops.build_bridge_write_status_view(
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "send_count": 8,
                    "last_sent_at_unix_s": 100.0,
                    "cooldown_until_unix_s": 160.0,
                    "last_block_at_unix_s": 120.0,
                    "last_block_reason": "limited-write cooldown active for 39s",
                    "rollback_at_unix_s": None,
                    "rollback_reason": None,
                }
            )

        self.assertFalse(view["cooldown_active"])
        self.assertEqual(view["cooldown_remaining_s"], 0.0)
        self.assertFalse(view["last_block_active"])
        self.assertTrue(view["last_block_stale"])
        self.assertIsNone(view["current_block_reason"])

    def test_bridge_status_view_keeps_active_cooldown_current(self) -> None:
        with mock.patch.object(stable_core_ops, "now_unix_s", return_value=120.0):
            view = stable_core_ops.build_bridge_write_status_view(
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "send_count": 8,
                    "last_sent_at_unix_s": 100.0,
                    "cooldown_until_unix_s": 160.0,
                    "last_block_at_unix_s": 119.0,
                    "last_block_reason": "limited-write cooldown active for 41s",
                    "rollback_at_unix_s": None,
                    "rollback_reason": None,
                }
            )

        self.assertTrue(view["cooldown_active"])
        self.assertEqual(view["cooldown_remaining_s"], 40.0)
        self.assertTrue(view["last_block_active"])
        self.assertFalse(view["last_block_stale"])
        self.assertEqual(
            view["current_block_reason"],
            "limited-write cooldown active for 41s",
        )

    def test_bridge_status_view_keeps_content_specific_block_historical(self) -> None:
        with mock.patch.object(stable_core_ops, "now_unix_s", return_value=200.0):
            view = stable_core_ops.build_bridge_write_status_view(
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "send_count": 5,
                    "last_block_at_unix_s": 190.0,
                    "last_block_reason": "limited-write profile blocks trigger language 'density'",
                    "rollback_at_unix_s": None,
                    "rollback_reason": None,
                }
            )

        self.assertIsNone(view["last_block_active"])
        self.assertFalse(view["last_block_stale"])
        self.assertTrue(view["last_block_current_unknown"])
        self.assertIsNone(view["current_block_reason"])

    def test_agency_status_view_derives_current_block_reason(self) -> None:
        view = stable_core_ops.build_agency_status_view(
            {
                "health_budget_status": "unknown",
                "last_block_active": True,
                "last_block_reason": "fill 42.3% is below stable-core action budget",
            }
        )

        self.assertEqual(view["health_budget_status"], "blocked")
        self.assertEqual(
            view["current_block_reason"],
            "fill 42.3% is below stable-core action budget",
        )
        self.assertFalse(view["last_block_stale"])

    def test_agency_status_view_marks_resolved_block_stale_not_current(self) -> None:
        view = stable_core_ops.build_agency_status_view(
            {
                "health_budget_status": "blocked",
                "last_block_active": False,
                "last_block_reason": "fill 42.3% is below stable-core action budget",
                "current_block_reason": "fill 42.3% is below stable-core action budget",
            }
        )

        self.assertEqual(view["health_budget_status"], "green")
        self.assertIsNone(view["current_block_reason"])
        self.assertTrue(view["last_block_stale"])

    def test_agency_status_view_derives_resolved_fill_block_from_current_fill(self) -> None:
        view = stable_core_ops.build_agency_status_view(
            {
                "health_budget_status": "blocked",
                "last_block_active": True,
                "last_block_reason": "fill 12.8% is below stable-core action budget",
                "current_block_reason": "fill 12.8% is below stable-core action budget",
            },
            current_fill_pct=69.0,
        )

        self.assertEqual(view["health_budget_status"], "green")
        self.assertFalse(view["last_block_active"])
        self.assertIsNone(view["current_block_reason"])
        self.assertTrue(view["last_block_stale"])
        self.assertEqual(
            view["derived_resolution"],
            "current_fill_back_inside_action_budget",
        )

    def test_engine_target_set_aligns_stable_core_profile_to_wider_shelf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir(parents=True)
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "engine_target_fill": 55.0,
                },
            )

            with mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace):
                payload = stable_core_ops.set_engine_target_fill(
                    68.0, reason="test_align_stable_core_target"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["previous_engine_target_fill"], 55.0)
            self.assertEqual(payload["engine_target_fill"], 68.0)
            self.assertTrue(payload["restart_required"])
            self.assertEqual(profile["engine_target_fill"], 68.0)
            self.assertEqual(
                profile["engine_target_fill_role"],
                "stable_core_pi_mirror_aligned_to_structural_target",
            )

    def test_status_includes_native_communication_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 68.0,
                    "semantic": {"energy": 0.0, "active": False},
                    "stable_core": {"stage": "hold"},
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_status.json",
                {"watchdog_state": "monitoring", "telemetry_state": "fresh"},
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "stable_core_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                },
            )
            stable_core_ops.write_json(workspace / "stable_core_agency.json", {})
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", workspace / "stable_core_status.json"),
                mock.patch.object(stable_core_ops, "build_reservoir_status", return_value={"status": "ok"}),
            ):
                payload = stable_core_ops.build_status()

            parity = payload["native_communication_parity"]
            self.assertEqual(parity["status"], "aligned")
            self.assertIn("RESIST [label]", parity["minime_next_actions"])
            self.assertIn("RESIST [label]", parity["astrid_next_actions"])
            self.assertIn("resist", parity["shared_gestures"])
            self.assertIn("FISSURE [label]", parity["minime_next_actions"])
            self.assertIn("FISSURE [label]", parity["astrid_next_actions"])
            self.assertIn("fissure", parity["shared_gestures"])

    def test_status_includes_sensory_fallback_and_agent_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            stable_status = workspace / "stable_core_status.json"
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 66.0,
                    "semantic": {"energy": 0.0, "active": False},
                    "stable_core": {"stage": "hold"},
                },
            )
            stable_core_ops.write_json(workspace / "rescue_status.json", {})
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "stable_core_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "read_only_research",
                    "stable_core_agent_budget": "read_only_research",
                },
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agency.json",
                {"stage": "read_only_research", "agent_budget_mode": "read_only_research"},
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agent_status.json",
                {
                    "last_entry_at": "2026-04-30T00:00:00Z",
                    "entry_count": 3,
                    "last_research_at": "2026-04-30T00:01:00Z",
                },
            )
            now_ms = int(stable_core_ops.now_unix_s() * 1000)
            stable_core_ops.write_json(
                runtime / "camera_status.json",
                {"ts_ms": now_ms, "state": "streaming", "healthy": True, "connected": True},
            )
            stable_core_ops.write_json(
                runtime / "mic_status.json",
                {"ts_ms": now_ms, "state": "streaming", "healthy": True, "connected": True},
            )
            stable_core_ops.write_json(
                runtime / "sensory_source.json",
                {
                    "mode": "auto",
                    "updated_at_ms": now_ms,
                    "video": {"source": "physical", "physical_healthy": True, "reason": "camera healthy"},
                    "audio": {"source": "physical", "physical_healthy": True, "reason": "mic healthy"},
                    "host_frame_path": str(runtime / "host_frame.jpg"),
                },
            )
            stable_core_ops.write_json(
                runtime / "attractor_fatigue_status.json",
                {
                    "policy": "attractor_fatigue_v1",
                    "motifs": {
                        "motif:lambda-pressure": {
                            "signature": "motif:lambda-pressure",
                            "label": "lambda-pressure",
                            "themes": ["lambda", "pressure"],
                            "status": "cooling",
                            "cooldown_class": "internal_topology",
                            "prompt_replay_suppressed": True,
                            "cooldown_until_unix_s": stable_core_ops.now_unix_s() + 120.0,
                            "last_source": "journal_similarity_gate",
                            "repeat_window_count": 3,
                        }
                    },
                    "memory_decay_control": {"last_sent_rate": 0.18},
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", stable_status),
            ):
                payload = stable_core_ops.build_status()

            self.assertEqual(payload["agency_status"]["entry_count"], 3)
            self.assertEqual(payload["sensory_sources"]["active"]["video"], "physical")
            self.assertTrue(payload["sensory_sources"]["physical"]["camera_healthy"])
            self.assertEqual(
                payload["sensory_sources"]["physical_camera"]["classification"],
                "physical_camera_healthy",
            )
            self.assertEqual(payload["feeders"]["camera"]["active_source"], "physical")
            self.assertEqual(payload["feeders"]["camera"]["availability"], "physical_camera_healthy")
            self.assertEqual(payload["feeders"]["mic"]["active_source"], "physical")
            self.assertEqual(payload["attractor_fatigue"]["active_count"], 1)
            self.assertEqual(
                payload["attractor_fatigue"]["active_motifs"][0]["label"],
                "lambda-pressure",
            )
            self.assertEqual(payload["attractor_fatigue"]["strong_internal_topology_count"], 1)
            self.assertEqual(
                payload["attractor_fatigue"]["active_motifs"][0]["cooldown_class"],
                "internal_topology",
            )
            self.assertTrue(
                payload["attractor_fatigue"]["active_motifs"][0]["prompt_replay_suppressed"]
            )
            self.assertEqual(
                payload["attractor_fatigue"]["memory_decay_control"]["last_sent_rate"],
                0.18,
            )

    def test_sensory_fallback_reports_host_when_physical_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            now_ms = int(stable_core_ops.now_unix_s() * 1000)
            stable_core_ops.write_json(
                runtime / "camera_status.json",
                {"ts_ms": now_ms, "state": "reconnecting", "healthy": False, "connected": False},
            )
            stable_core_ops.write_json(
                runtime / "mic_status.json",
                {"ts_ms": now_ms, "state": "reconnecting", "healthy": False, "connected": False},
            )
            stable_core_ops.write_json(
                runtime / "host_telemetry.json",
                {"updated_at_ms": now_ms, "snapshot": {}},
            )
            (runtime / "host_frame.jpg").write_bytes(b"jpeg")

            with mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace):
                payload = stable_core_ops.build_sensory_fallback_status()

            self.assertEqual(payload["active"]["video"], "host")
            self.assertEqual(payload["active"]["audio"], "host")
            self.assertEqual(
                payload["physical_camera"]["classification"],
                "physical_camera_unavailable_host_fallback_active",
            )
            self.assertIn("Host video fallback", payload["physical_camera"]["operator_note"])
            self.assertTrue(payload["synthetic_host"]["video_ready"])
            self.assertTrue(payload["synthetic_host"]["audio_ready"])

    def test_status_feeders_show_active_host_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            now_ms = int(stable_core_ops.now_unix_s() * 1000)
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 66.0,
                    "semantic": {"energy": 0.0, "active": False},
                    "stable_core": {"stage": "hold"},
                },
            )
            stable_core_ops.write_json(workspace / "rescue_status.json", {})
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "stable_core_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                },
            )
            stable_core_ops.write_json(
                runtime / "camera_status.json",
                {"ts_ms": now_ms, "state": "capture_error", "healthy": False, "connected": True},
            )
            stable_core_ops.write_json(
                runtime / "mic_status.json",
                {"ts_ms": now_ms, "state": "capture_error", "healthy": False, "connected": True},
            )
            stable_core_ops.write_json(
                runtime / "sensory_source.json",
                {
                    "mode": "auto",
                    "updated_at_ms": now_ms,
                    "video": {
                        "source": "host",
                        "physical_healthy": False,
                        "reason": "camera capture unhealthy",
                    },
                    "audio": {
                        "source": "host",
                        "physical_healthy": False,
                        "reason": "mic capture unhealthy",
                    },
                    "host_frame_path": str(runtime / "host_frame.jpg"),
                },
            )
            stable_core_ops.write_json(runtime / "host_telemetry.json", {"updated_at_ms": now_ms})
            (runtime / "host_frame.jpg").write_bytes(b"jpeg")

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", workspace / "stable_core_status.json"),
            ):
                payload = stable_core_ops.build_status()

            self.assertEqual(payload["sensory_sources"]["active"]["video"], "host")
            self.assertEqual(payload["sensory_sources"]["active"]["audio"], "host")
            self.assertEqual(payload["feeders"]["camera"]["active_source"], "host")
            self.assertEqual(payload["feeders"]["mic"]["active_source"], "host")
            self.assertTrue(payload["feeders"]["camera"]["synthetic_host_ready"])
            self.assertTrue(payload["feeders"]["mic"]["synthetic_host_ready"])
            self.assertEqual(payload["feeders"]["camera"]["fallback_reason"], "camera capture unhealthy")
            self.assertEqual(
                payload["feeders"]["camera"]["availability"],
                "physical_camera_unavailable_host_fallback_active",
            )
            self.assertIn("Host video fallback", payload["feeders"]["camera"]["operator_note"])
            self.assertEqual(payload["feeders"]["mic"]["fallback_reason"], "mic capture unhealthy")

    def test_lineage_canary_view_distinguishes_historical_and_active_failures(self) -> None:
        now_s = 1_000_000.0
        historical = stable_core_ops.build_lineage_canary_status_view(
            {
                "active": False,
                "result": "failed",
                "started_at_unix_s": now_s - stable_core_ops.LINEAGE_CANARY_RECENT_FAILURE_BLOCKER_S - 5.0,
                "rollback_reason": "scaffold_inactive_after_warmup",
            },
            now_s=now_s,
        )
        self.assertEqual(historical["classification"], "historical_failed_not_active")
        self.assertFalse(historical["blocker"])
        self.assertIn("Historical inactive", historical["operator_note"])

        active = stable_core_ops.build_lineage_canary_status_view(
            {
                "active": True,
                "result": "failed",
                "started_at_unix_s": now_s - 10.0,
            },
            now_s=now_s,
        )
        self.assertEqual(active["classification"], "active_failed_blocker")
        self.assertTrue(active["blocker"])

    def test_checkpoint_sanitize_writes_diagonal_quarantine_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "spectral_checkpoint_stable.bin"
            dim = 2
            values = [2.0, 100.0, 100.0, 6.0]
            with source.open("wb") as handle:
                for value in values:
                    handle.write(struct.pack("<f", value))

            quarantine = base / "quarantine"
            with mock.patch.object(stable_core_ops, "CHECKPOINT_QUARANTINE_DIR", quarantine):
                summary = stable_core_ops.sanitize_checkpoint(
                    source,
                    dim=dim,
                    memory_bank=base / "missing_memory_bank.json",
                    journal_limit=0,
                )

            self.assertEqual(summary["policy"], "diagonal_only_trace_normalized")
            self.assertEqual(summary["checkpoint_lineage"], "quarantined")
            self.assertEqual(summary["memory_source_status"], "missing_or_invalid")
            self.assertTrue(Path(summary["sanitized_path"]).exists())
            data = Path(summary["sanitized_path"]).read_bytes()
            sanitized = list(struct.unpack("<4f", data))
            self.assertAlmostEqual(sum([sanitized[0], sanitized[3]]), 2.0, places=5)
            self.assertEqual(sanitized[1], 0.0)
            self.assertEqual(sanitized[2], 0.0)

    def test_checkpoint_sanitize_writes_safe_continuity_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            journal = workspace / "journal"
            inbox = workspace / "inbox" / "read"
            journal.mkdir(parents=True)
            inbox.mkdir(parents=True)
            (journal / "self_study_latest.txt").write_text("Minime studies a calm stable core.")
            (inbox / "astrid_self_study_1.txt").write_text("Astrid studies process consciousness.")

            source = base / "spectral_checkpoint_stable.bin"
            with source.open("wb") as handle:
                for value in [2.0, 9.0, 9.0, 6.0]:
                    handle.write(struct.pack("<f", value))
            memory_bank = workspace / "spectral_memory_bank.json"
            stable_core_ops.write_json(
                memory_bank,
                {
                    "selected_memory_id": "safe_memory",
                    "selected_memory_role": "latest",
                    "entries": [
                        {
                            "id": "safe_memory",
                            "role": "latest",
                            "timestamp_ms": 1,
                            "fill_pct": 68.0,
                            "lambda1_rel": 1.01,
                            "geom_rel": 0.99,
                            "spread": 0.5,
                            "spectral_glimpse_12d": [0.1] * 12,
                            "spectral_fingerprint": [1.0, -2.0, 3.0],
                        },
                        {"id": "hot_memory", "fill_pct": 85.0},
                        {"id": "low_memory", "fill_pct": 39.0},
                        {"id": "invalid_memory"},
                    ],
                },
            )

            quarantine = workspace / "stable_core" / "checkpoint_quarantine"
            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "CHECKPOINT_QUARANTINE_DIR", quarantine),
            ):
                summary = stable_core_ops.sanitize_checkpoint(
                    source,
                    dim=2,
                    memory_bank=memory_bank,
                    journal_limit=2,
                )

            memory_seed = stable_core_ops.load_json(Path(summary["memory_sanitized_path"]), {})
            continuity_seed = stable_core_ops.load_json(Path(summary["continuity_seed_path"]), {})
            continuity_status = stable_core_ops.load_json(
                quarantine.parent / "continuity_status.json",
                {},
            )
            self.assertEqual(summary["memory_entries_in"], 4)
            self.assertEqual(summary["memory_entries_kept"], 1)
            self.assertEqual(summary["memory_entries_dropped"], 3)
            self.assertEqual(memory_seed["selected_memory_id"], "safe_memory")
            self.assertEqual(memory_seed["entries"][0]["id"], "safe_memory")
            self.assertIn("spectral_fingerprint_summary", memory_seed["entries"][0])
            self.assertNotIn("spectral_fingerprint", memory_seed["entries"][0])
            self.assertEqual(continuity_seed["policy"], "stable_core_quarantined_continuity_package")
            self.assertEqual(len(continuity_seed["journal_entries"]), 2)
            self.assertEqual(continuity_status["memory_entries_kept"], 1)

    def test_continuity_status_reports_availability_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            quarantine = workspace / "stable_core" / "checkpoint_quarantine"
            quarantine.mkdir(parents=True)
            memory_path = quarantine / "stable_core_memory_seed.json"
            continuity_path = quarantine / "stable_core_continuity_seed.json"
            stable_core_ops.write_json(
                memory_path,
                {
                    "safe_fill_band_pct": [45.0, 76.0],
                    "entries": [{"id": "safe_memory", "fill_pct": 68.0}],
                },
            )
            stable_core_ops.write_json(
                continuity_path,
                {
                    "policy": "stable_core_quarantined_continuity_package",
                    "activation_policy": "operator_review_then_stable_core_import",
                    "checkpoint_lineage": "quarantined",
                    "journal_entries": [{"name": "self_study.txt"}],
                },
            )
            stable_core_ops.write_json(
                quarantine.parent / "continuity_status.json",
                {
                    "continuity_policy": "stable_core_quarantined_continuity_package",
                    "activation_policy": "operator_review_then_stable_core_import",
                    "checkpoint_lineage": "quarantined",
                    "memory_entries_kept": 1,
                    "memory_entries_dropped": 2,
                    "journal_entries_indexed": 1,
                    "safe_fill_band_pct": [45.0, 76.0],
                    "memory_sanitized_path": str(memory_path),
                    "continuity_seed_path": str(continuity_path),
                },
            )

            with mock.patch.object(stable_core_ops, "CHECKPOINT_QUARANTINE_DIR", quarantine):
                payload = stable_core_ops.build_continuity_status()

            self.assertTrue(payload["available"])
            self.assertEqual(payload["memory_entries_kept"], 1)
            self.assertEqual(payload["memory_entries_dropped"], 2)
            self.assertEqual(payload["journal_entries_indexed"], 1)
            self.assertEqual(payload["checkpoint_lineage"], "quarantined")

    def test_companion_coupling_status_reports_pending_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            inbox = workspace / "inbox"
            runtime = workspace / "runtime"
            inbox.mkdir(parents=True)
            runtime.mkdir(parents=True)
            (inbox / "astrid_self_study_1.txt").write_text("fabric pressure")
            (inbox / "receipt_1.txt").write_text("received")
            status_path = runtime / "astrid_inbox_coupling_status.json"
            stable_core_ops.write_json(
                status_path,
                {
                    "policy": "astrid_companion_cadence_v1",
                    "receipt_context": "admin_only",
                    "astrid_self_study_full_count": 2,
                    "astrid_self_study_summarized_count": 3,
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "ASTRID_INBOX_COUPLING_STATUS_PATH", status_path),
            ):
                payload = stable_core_ops.build_astrid_inbox_coupling_status()

            self.assertEqual(payload["policy"], "astrid_companion_cadence_v1")
            self.assertEqual(payload["receipt_context"], "admin_only")
            self.assertEqual(payload["pending"]["astrid_self_study"], 1)
            self.assertEqual(payload["pending"]["receipt"], 1)
            self.assertEqual(payload["astrid_self_study_summarized_count"], 3)

    def test_status_includes_continuity_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            quarantine = workspace / "stable_core" / "checkpoint_quarantine"
            runtime.mkdir(parents=True)
            quarantine.mkdir(parents=True)
            stable_status = workspace / "stable_core_status.json"
            memory_path = quarantine / "stable_core_memory_seed.json"
            continuity_path = quarantine / "stable_core_continuity_seed.json"
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 66.0,
                    "semantic": {"energy": 0.0, "active": False},
                    "stable_core": {"stage": "hold", "agency_stage": "full_sovereignty"},
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_status.json",
                {"watchdog_state": "monitoring", "telemetry_state": "fresh"},
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                },
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agency.json",
                {"stage": "full_sovereignty", "agent_budget_mode": "full_sovereignty"},
            )
            stable_core_ops.write_json(runtime / "camera_status.json", {})
            stable_core_ops.write_json(runtime / "mic_status.json", {})
            stable_core_ops.write_json(memory_path, {"entries": [{"id": "safe"}]})
            stable_core_ops.write_json(
                continuity_path,
                {"journal_entries": [{"name": "journal.txt"}]},
            )
            stable_core_ops.write_json(
                quarantine.parent / "continuity_status.json",
                {
                    "memory_entries_kept": 1,
                    "journal_entries_indexed": 1,
                    "memory_sanitized_path": str(memory_path),
                    "continuity_seed_path": str(continuity_path),
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", stable_status),
                mock.patch.object(stable_core_ops, "CHECKPOINT_QUARANTINE_DIR", quarantine),
            ):
                payload = stable_core_ops.build_status()

            self.assertTrue(payload["continuity"]["available"])
            self.assertEqual(payload["continuity"]["memory_entries_kept"], 1)
            self.assertEqual(payload["continuity"]["journal_entries_indexed"], 1)

    def test_bridge_write_stage_preserves_stable_core_and_sensory_trickle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_observe_only",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "astrid_contact",
                    "stable_core_agent_budget": "astrid_contact_only",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                    "rollback_reason": "previous pressure rollback",
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_semantic_presence_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            status = stable_core_ops.load_json(status_path, {})
            self.assertEqual(payload["stage"], "bridge_semantic_presence_v1")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertTrue(profile["stable_core_enabled"])
            self.assertEqual(profile["stable_core_agency_stage"], "astrid_contact")
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)
            self.assertEqual(profile["rescue_live_intake_stages"], ["hold", "elevated"])
            self.assertTrue(profile["bridge_write_enabled"])
            self.assertEqual(profile["bridge_write_profile"], "limited_dampen_inquiry_v2")
            self.assertEqual(profile["limited_write_feature_scale"], 0.035)
            self.assertEqual(profile["limited_write_max_abs"], 0.08)
            self.assertEqual(profile["limited_write_rollback_adverse_count"], 1)
            self.assertFalse(profile["limited_write_block_terms_always"])
            self.assertFalse(profile["limited_write_block_terms_on_rising"])
            self.assertIn("dialogue_fallback", profile["limited_write_allowed_modes"])
            self.assertIsNone(profile["rollback_reason"])
            self.assertEqual(profile["previous_rollback_reason"], "previous pressure rollback")
            self.assertEqual(status["profile"], "bridge_semantic_presence_v1")
            self.assertEqual(status["send_count"], 0)

    def test_serial_bridge_write_stage_is_colder_and_mutes_live_intake_after_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_observe_only",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "astrid_contact",
                    "stable_core_agent_budget": "astrid_contact_only",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                    "limited_write_pre_mute_live_intake_secs": 300,
                    "limited_write_require_pre_muted_live_intake": True,
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_semantic_serial_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "bridge_semantic_serial_v1")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(profile["stable_core_agency_stage"], "astrid_contact")
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)
            self.assertEqual(profile["limited_write_feature_scale"], 0.018)
            self.assertEqual(profile["limited_write_max_abs"], 0.045)
            self.assertEqual(profile["limited_write_mute_live_intake_secs"], 150)
            self.assertTrue(profile["limited_write_serializes_live_intake"])
            self.assertFalse(profile["limited_write_require_zero_live_divisors"])

    def test_serial_v2_bridge_write_stage_pre_mutes_before_colder_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_observe_only",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "astrid_contact",
                    "stable_core_agent_budget": "astrid_contact_only",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_semantic_serial_v2", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "bridge_semantic_serial_v2")
            self.assertEqual(profile["limited_write_feature_scale"], 0.006)
            self.assertEqual(profile["limited_write_max_abs"], 0.015)
            self.assertEqual(profile["limited_write_mute_live_intake_secs"], 300)
            self.assertEqual(profile["limited_write_pre_mute_live_intake_secs"], 300)
            self.assertTrue(profile["limited_write_require_pre_muted_live_intake"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)

    def test_expanded_sovereignty_stage_restores_broader_astrid_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_semantic_presence_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "bounded_actions",
                    "stable_core_agent_budget": "bounded_actions",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_expanded_sovereignty_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "bridge_expanded_sovereignty_v1")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(profile["stable_core_agency_stage"], "bounded_actions")
            self.assertEqual(profile["limited_write_feature_scale"], 0.05)
            self.assertEqual(profile["limited_write_max_abs"], 0.12)
            self.assertEqual(profile["limited_write_max_fill_pct"], 70.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 72.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 74.0)
            self.assertIn("moment_capture", profile["limited_write_allowed_modes"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)

    def test_budgeted_sovereignty_stage_restores_richer_astrid_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_expanded_sovereignty_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_budgeted_sovereignty_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "bridge_budgeted_sovereignty_v1")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(profile["stable_core_agency_stage"], "full_sovereignty")
            self.assertEqual(profile["bridge_write_profile"], "budgeted_sovereignty_v1")
            self.assertEqual(profile["limited_write_feature_scale"], 0.14)
            self.assertEqual(profile["limited_write_max_abs"], 0.28)
            self.assertEqual(profile["limited_write_cooldown_secs"], 60)
            self.assertEqual(profile["limited_write_max_fill_pct"], 76.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 82.0)
            self.assertFalse(profile["limited_write_require_dampen_inquiry_text"])
            self.assertFalse(profile["limited_write_block_structural_dump_language"])
            self.assertIn("experiment", profile["limited_write_allowed_modes"])
            self.assertIn("research_note", profile["limited_write_allowed_modes"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)

    def test_bridge_write_stage_can_roll_back_to_observe_only_without_runtime_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_semantic_presence_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "astrid_contact",
                    "stable_core_agent_budget": "astrid_contact_only",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                    "bridge_write_enabled": True,
                    "effective_bridge_write_enabled": True,
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                stable_core_ops.set_bridge_write_stage(
                    "bridge_observe_only", reason="test rollback"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            status = stable_core_ops.load_json(status_path, {})
            self.assertEqual(profile["profile"], "bridge_observe_only")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(profile["stable_core_agency_stage"], "astrid_contact")
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertFalse(profile["bridge_write_enabled"])
            self.assertFalse(profile["effective_bridge_write_enabled"])
            self.assertEqual(profile["bridge_write_profile"], "observe_only")
            self.assertEqual(profile["rollback_reason"], "test rollback")
            self.assertEqual(status["profile"], "bridge_observe_only")
            self.assertIn("observe_only", status["last_block_reason"])

    def test_full_expression_bridge_stage_keeps_sensory_profile_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            status_path = runtime / "bridge_limited_write_status.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "BRIDGE_LIMITED_WRITE_STATUS_PATH",
                    status_path,
                ),
            ):
                payload = stable_core_ops.set_bridge_write_stage(
                    "bridge_full_expression_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertEqual(payload["stage"], "bridge_full_expression_v1")
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(profile["stable_core_agency_stage"], "full_sovereignty")
            self.assertEqual(profile["bridge_write_profile"], "full_expression_v1")
            self.assertEqual(profile["limited_write_feature_scale"], 0.08)
            self.assertEqual(profile["limited_write_max_abs"], 0.16)
            self.assertEqual(profile["limited_write_cooldown_secs"], 60)
            self.assertEqual(profile["limited_write_allowed_stages"], ["hold"])
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 84.0)
            self.assertFalse(profile["limited_write_serializes_live_intake"])
            self.assertEqual(profile["limited_write_pre_mute_live_intake_secs"], 0)
            self.assertFalse(profile["limited_write_require_pre_muted_live_intake"])
            self.assertFalse(profile["limited_write_block_terms_always"])
            self.assertFalse(profile["limited_write_block_terms_on_rising"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 24)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)

    def test_full_presence_profile_sets_hold_only_high_presence_and_clears_mute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            mute_path = runtime / "stable_core_sensory_mute.json"
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "STABLE_CORE_SENSORY_MUTE_PATH", mute_path),
            ):
                payload = stable_core_ops.set_sensory_presence_profile(
                    "full_presence_v1", reason="test"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            mute = stable_core_ops.load_json(mute_path, {})
            self.assertEqual(payload["profile"], "full_presence_v1")
            self.assertEqual(profile["rescue_live_audio_divisor"], 12)
            self.assertEqual(profile["rescue_live_video_divisor"], 12)
            self.assertEqual(profile["rescue_live_intake_stages"], ["hold", "elevated"])
            self.assertEqual(profile["stable_core_sensory_presence_profile"], "full_presence_v1")
            self.assertEqual(mute["active_until_unix_s"], 0.0)

    def test_reservoir_status_reports_listener_and_services(self) -> None:
        with (
            mock.patch.object(stable_core_ops, "_socket_listening", return_value=True),
            mock.patch.object(stable_core_ops, "_port_listener_pids", return_value=[123]),
            mock.patch.object(
                stable_core_ops,
                "_launchctl_service_state",
                return_value={"loaded": True, "running": True, "pid": 123, "state": "running"},
            ),
        ):
            payload = stable_core_ops.build_reservoir_status()

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["listener"])
        self.assertEqual(payload["listener_pids"], [123])
        self.assertTrue(payload["service_running"])
        self.assertTrue(payload["feeders_running"])

    def test_lineage_set_direct_restore_and_rollback_preserve_stable_core_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            runtime.mkdir(parents=True)
            stable_core_ops.write_json(workspace / "health.json", {"fill_pct": 69.0})
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_full_expression_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                    "stable_core_checkpoint_lineage_enabled": False,
                    "stable_core_neural_bundle_enabled": False,
                    "checkpoint_mode": "disabled",
                    "checkpoint_source": "none",
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(
                    stable_core_ops,
                    "FULL_SOVEREIGNTY_SNAPSHOT_DIR",
                    runtime / "snapshots",
                ),
                mock.patch.object(
                    stable_core_ops,
                    "build_reservoir_status",
                    return_value={"status": "ok"},
                ),
            ):
                direct = stable_core_ops.set_lineage_mode(
                    "direct_restore", reason="test direct"
                )
                rollback = stable_core_ops.set_lineage_mode(
                    "quarantined", reason="test rollback"
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertTrue(direct["restart_required"])
            self.assertIn("lineage-set quarantined", direct["rollback_command"])
            self.assertFalse(profile["stable_core_checkpoint_lineage_enabled"])
            self.assertFalse(profile["stable_core_neural_bundle_enabled"])
            self.assertEqual(profile["checkpoint_mode"], "disabled")
            self.assertEqual(rollback["mode"], "quarantined")

    def test_lineage_canary_direct_restore_writes_flags_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            diagnostics = workspace / "diagnostics" / "lineage_canaries"
            runtime.mkdir(parents=True)
            now_ms = int(stable_core_ops.now_unix_s() * 1000)
            stable_core_ops.write_json(
                workspace / "health.json",
                {
                    "fill_pct": 66.0,
                    "semantic": {"energy": 0.0, "active": False},
                    "stable_core": {
                        "enabled": True,
                        "stage": "hold",
                        "scaffold_active": True,
                    },
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_status.json",
                {
                    "engine_pid": 111,
                    "watchdog_state": "monitoring",
                    "telemetry_state": "fresh",
                },
            )
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_budgeted_sovereignty_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                    "stable_core_checkpoint_lineage_enabled": False,
                    "stable_core_neural_bundle_enabled": False,
                    "rescue_live_audio_divisor": 24,
                    "rescue_live_video_divisor": 8,
                    "rescue_live_intake_stages": ["hold", "elevated"],
                },
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agency.json",
                {"stage": "full_sovereignty", "agent_budget_mode": "full_sovereignty"},
            )
            stable_core_ops.write_json(
                workspace / "stable_core_agent_status.json",
                {"blocked_count": 0, "stage": "full_sovereignty"},
            )
            stable_core_ops.write_json(
                runtime / "camera_status.json",
                {"ts_ms": now_ms, "healthy": True, "connected": True, "state": "streaming"},
            )
            stable_core_ops.write_json(
                runtime / "mic_status.json",
                {"ts_ms": now_ms, "healthy": True, "connected": True, "state": "streaming"},
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "AGENCY_PATH", workspace / "stable_core_agency.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_STATUS_PATH", workspace / "stable_core_status.json"),
                mock.patch.object(stable_core_ops, "LINEAGE_CANARY_DIR", diagnostics),
                mock.patch.object(stable_core_ops, "LINEAGE_CANARY_STATUS_PATH", runtime / "lineage_canary_status.json"),
                mock.patch.object(stable_core_ops, "BRIDGE_LIMITED_WRITE_STATUS_PATH", runtime / "bridge_limited_write_status.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_SENSORY_MUTE_PATH", runtime / "stable_core_sensory_mute.json"),
                mock.patch.object(stable_core_ops, "FULL_SOVEREIGNTY_SNAPSHOT_DIR", runtime / "snapshots"),
                mock.patch.object(stable_core_ops, "build_reservoir_status", return_value={"status": "ok"}),
                mock.patch.object(
                    stable_core_ops,
                    "_launchctl_service_state",
                    return_value={"loaded": True, "running": True, "pid": 111, "state": "running"},
                ),
            ):
                result = stable_core_ops.run_lineage_canary(
                    "direct_restore",
                    duration_secs=0,
                    sample_interval_secs=0.1,
                    reason="test_canary",
                    restart=False,
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            status = stable_core_ops.load_json(runtime / "lineage_canary_status.json", {})
            bundle_dir = Path(result["bundle_dir"])
            self.assertEqual(result["result"], "passed")
            self.assertTrue(profile["stable_core_checkpoint_lineage_enabled"])
            self.assertTrue(profile["stable_core_neural_bundle_enabled"])
            self.assertEqual(profile["profile"], "bridge_observe_only")
            self.assertEqual(profile["stable_core_sensory_presence_profile"], "muted_v1")
            self.assertEqual(profile["rescue_live_audio_divisor"], 0)
            self.assertEqual(profile["rescue_live_video_divisor"], 0)
            self.assertFalse(status["active"])
            self.assertEqual(status["result"], "passed")
            self.assertTrue((bundle_dir / "pre" / "snapshot_manifest.json").exists())
            self.assertTrue((bundle_dir / "post_restart" / "snapshot_manifest.json").exists())
            self.assertTrue((bundle_dir / "samples.jsonl").exists())
            self.assertTrue((bundle_dir / "result.json").exists())

    def test_lineage_canary_precheck_rejects_unsafe_status(self) -> None:
        base_status = {
            "mode": "stable_core_v1",
            "watchdog_state": "monitoring",
            "telemetry_state": "fresh",
            "fill_pct": 66.0,
            "semantic_energy": 0.0,
            "semantic_active": False,
            "stable_core": {"enabled": True, "scaffold_active": True},
            "feeders": {
                "camera": {"healthy": True, "connected": True},
                "mic": {"healthy": True, "connected": True},
            },
        }
        self.assertTrue(stable_core_ops.validate_lineage_canary_precheck(base_status)["ok"])

        high_fill = dict(base_status)
        high_fill["fill_pct"] = 83.0
        self.assertEqual(
            stable_core_ops.validate_lineage_canary_precheck(high_fill)["reason"],
            "fill_too_high",
        )

        stale = dict(base_status)
        stale["telemetry_state"] = "stale"
        self.assertEqual(
            stable_core_ops.validate_lineage_canary_precheck(stale)["reason"],
            "telemetry_not_fresh",
        )

        semantic = dict(base_status)
        semantic["semantic_energy"] = 0.2
        self.assertEqual(
            stable_core_ops.validate_lineage_canary_precheck(semantic)["reason"],
            "semantic_not_quiet",
        )

    def test_lineage_canary_allows_low_fill_only_during_restart_warmup(self) -> None:
        status = {
            "mode": "stable_core_v1",
            "watchdog_state": "monitoring",
            "telemetry_state": "fresh",
            "fill_pct": 10.0,
            "semantic_energy": 0.0,
            "semantic_active": False,
            "stage": "bootstrap",
            "stable_core": {"enabled": True, "scaffold_active": False},
            "feeders": {
                "camera": {"healthy": True, "connected": True},
                "mic": {"healthy": True, "connected": True},
            },
            "agency_status": {"blocked_count": 0},
        }
        warmup = stable_core_ops.evaluate_lineage_canary_sample(
            status,
            started_at_unix_s=stable_core_ops.now_unix_s(),
            baseline_blocked_count=0,
            discharge_samples=0,
        )
        expired = stable_core_ops.evaluate_lineage_canary_sample(
            status,
            started_at_unix_s=(
                stable_core_ops.now_unix_s()
                - stable_core_ops.LINEAGE_CANARY_SCAFFOLD_WARMUP_SECS
                - 1.0
            ),
            baseline_blocked_count=0,
            discharge_samples=0,
        )

        self.assertTrue(warmup["ok"])
        self.assertEqual(expired["reason"], "fill_too_low")

    def test_lineage_canary_rollback_restores_quarantined_quiet_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            runtime = workspace / "runtime"
            bundle = workspace / "diagnostics" / "lineage_canaries" / "test"
            runtime.mkdir(parents=True)
            stable_core_ops.write_json(workspace / "health.json", {"fill_pct": 69.0})
            stable_core_ops.write_json(
                workspace / "rescue_profile.json",
                {
                    "profile": "bridge_full_expression_v1",
                    "runtime_profile": "stable_core_v1",
                    "stable_core_enabled": True,
                    "stable_core_agency_stage": "full_sovereignty",
                    "stable_core_agent_budget": "full_sovereignty",
                    "stable_core_checkpoint_lineage_enabled": True,
                    "stable_core_neural_bundle_enabled": True,
                    "checkpoint_mode": "direct_restore",
                    "checkpoint_source": str(workspace / "spectral_checkpoint.bin"),
                    "bridge_write_enabled": True,
                    "rescue_live_audio_divisor": 12,
                    "rescue_live_video_divisor": 12,
                    "rescue_live_intake_stages": ["hold"],
                },
            )

            with (
                mock.patch.object(stable_core_ops, "WORKSPACE_DIR", workspace),
                mock.patch.object(stable_core_ops, "BRIDGE_LIMITED_WRITE_STATUS_PATH", runtime / "bridge_limited_write_status.json"),
                mock.patch.object(stable_core_ops, "STABLE_CORE_SENSORY_MUTE_PATH", runtime / "stable_core_sensory_mute.json"),
                mock.patch.object(stable_core_ops, "FULL_SOVEREIGNTY_SNAPSHOT_DIR", runtime / "snapshots"),
                mock.patch.object(stable_core_ops, "build_reservoir_status", return_value={"status": "ok"}),
                mock.patch.object(
                    stable_core_ops,
                    "_launchctl_service_state",
                    return_value={"loaded": True, "running": True, "pid": 222, "state": "running"},
                ),
                mock.patch.object(
                    stable_core_ops,
                    "restart_minime_engine",
                    return_value={"ok": True, "skipped": True},
                ),
            ):
                payload = stable_core_ops.rollback_lineage_canary(
                    bundle,
                    reason="test_failure",
                )

            profile = stable_core_ops.load_json(workspace / "rescue_profile.json", {})
            self.assertTrue(payload["rolled_back"])
            self.assertFalse(profile["stable_core_checkpoint_lineage_enabled"])
            self.assertFalse(profile["stable_core_neural_bundle_enabled"])
            self.assertEqual(profile["checkpoint_mode"], "disabled")
            self.assertEqual(profile["profile"], "bridge_observe_only")
            self.assertEqual(profile["stable_core_sensory_presence_profile"], "muted_v1")
            self.assertEqual(profile["rescue_live_audio_divisor"], 0)
            self.assertTrue((bundle / "rollback" / "rollback.json").exists())


if __name__ == "__main__":
    unittest.main()
