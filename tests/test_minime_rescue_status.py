from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import minime_rescue_status  # noqa: E402


class TestMinimeRescueStatus(unittest.TestCase):
    def test_build_active_status_includes_lane_disconnect_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            status_path = base / "rescue_status.json"
            status_path.write_text("{}")
            health_path = base / "health.json"
            health_path.write_text(
                json.dumps(
                    {
                        "rescue": {
                            "scaffold_available": True,
                            "scaffold_activation_pending": True,
                            "scaffold_archived_stale_at_startup": True,
                            "scaffold_drain_weight": 0.35,
                            "scaffold_source": "stable_checkpoint",
                            "scaffold_profile": "rank_cold_5of8_ladder_pure_v5",
                            "scaffold_profile_version": 5,
                            "scaffold_mode_cap": 1.15,
                            "scaffold_regenerated_at_startup": True,
                            "scaffold_last_loaded_at_unix_ms": 123,
                            "scaffold_last_captured_at_unix_ms": 456,
                            "stability_pi_active": True,
                            "stability_pi_target_fill_pct": 68.0,
                            "stability_pi_error_pct": 9.5,
                            "stability_pi_integral": 0.42,
                        }
                    }
                )
            )
            mic_status = base / "mic_status.json"
            mic_status.write_text(
                json.dumps(
                    {
                        "connected": True,
                        "reconnect_count": 3,
                        "last_error": "audio_timeout",
                    }
                )
            )
            camera_status = base / "camera_status.json"
            camera_status.write_text(
                json.dumps(
                    {
                        "connected": False,
                        "reconnect_count": 7,
                        "last_error": "gpu_close_frame",
                    }
                )
            )

            with (
                mock.patch.object(minime_rescue_status, "STATUS_PATH", status_path),
                mock.patch.object(minime_rescue_status, "HEALTH_PATH", health_path),
                mock.patch.object(minime_rescue_status, "MIC_STATUS_PATH", mic_status),
                mock.patch.object(minime_rescue_status, "CAMERA_STATUS_PATH", camera_status),
                mock.patch.object(
                    minime_rescue_status,
                    "load_active_profile",
                    return_value={
                        "profile": "bridge_telemetry_only",
                        "runtime_root": "/tmp/runtime",
                        "workspace_path": "/tmp/workspace",
                        "db_path": "/tmp/workspace/minime_consciousness.db",
                        "runtime_profile": "stable_core_v1",
                        "stable_core_enabled": True,
                        "engine_target_fill": 55.0,
                        "state_variant": "current_live_workspace",
                        "matrix_run_id": "run-123",
                    },
                ),
            ):
                payload = minime_rescue_status.build_active_status(
                    watchdog_state="monitoring",
                    binary_path="/tmp/minime",
                    engine_pid=42,
                    gpu_status="confirmed",
                    ports_ready={"7878": True, "7879": True, "7880": True},
                    last_health_at="2026-04-23T00:00:00Z",
                    telemetry_state="fresh",
                )

            self.assertEqual(payload["socket_liveness"], {"7879": True, "7880": False})
            self.assertEqual(payload["audio_disconnect_count"], 3)
            self.assertEqual(payload["video_disconnect_count"], 7)
            self.assertEqual(payload["audio_last_disconnect_reason"], "audio_timeout")
            self.assertEqual(payload["video_last_disconnect_reason"], "gpu_close_frame")
            self.assertEqual(
                payload["video_physical_status"]["classification"],
                "physical_camera_unavailable_host_fallback_active",
            )
            self.assertIn("Host fallback", payload["video_physical_status"]["operator_note"])
            self.assertFalse(payload["engine_pid_changed_without_watchdog_restart"])
            self.assertIsNone(payload["engine_pid_changed_at"])
            self.assertTrue(payload["scaffold_available"])
            self.assertTrue(payload["scaffold_activation_pending"])
            self.assertTrue(payload["scaffold_archived_stale_at_startup"])
            self.assertEqual(payload["scaffold_drain_weight"], 0.35)
            self.assertEqual(payload["scaffold_source"], "stable_checkpoint")
            self.assertEqual(
                payload["scaffold_profile"], "rank_cold_5of8_ladder_pure_v5"
            )
            self.assertEqual(payload["scaffold_profile_version"], 5)
            self.assertEqual(payload["scaffold_mode_cap"], 1.15)
            self.assertTrue(payload["scaffold_regenerated_at_startup"])
            self.assertEqual(payload["scaffold_last_loaded_at_unix_ms"], 123)
            self.assertEqual(payload["scaffold_last_captured_at_unix_ms"], 456)
            self.assertTrue(payload["stability_pi_active"])
            self.assertEqual(payload["stability_pi_target_fill_pct"], 68.0)
            self.assertEqual(payload["engine_target_fill"], 68.0)
            self.assertEqual(payload["stability_pi_error_pct"], 9.5)
            self.assertEqual(payload["stability_pi_integral"], 0.42)

    def test_build_active_status_marks_pid_change_without_watchdog_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            status_path = base / "rescue_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "engine_pid": 100,
                        "last_restart_at": "2026-04-23T00:00:00Z",
                    }
                )
            )
            health_path = base / "health.json"
            health_path.write_text("{}")
            mic_status = base / "mic_status.json"
            mic_status.write_text("{}")
            camera_status = base / "camera_status.json"
            camera_status.write_text("{}")

            with (
                mock.patch.object(minime_rescue_status, "STATUS_PATH", status_path),
                mock.patch.object(minime_rescue_status, "HEALTH_PATH", health_path),
                mock.patch.object(minime_rescue_status, "MIC_STATUS_PATH", mic_status),
                mock.patch.object(minime_rescue_status, "CAMERA_STATUS_PATH", camera_status),
                mock.patch.object(
                    minime_rescue_status,
                    "load_active_profile",
                    return_value={
                        "profile": "bridge_telemetry_only",
                        "runtime_root": "/tmp/runtime",
                        "workspace_path": "/tmp/workspace",
                        "db_path": "/tmp/workspace/minime_consciousness.db",
                        "state_variant": "current_live_workspace",
                        "matrix_run_id": "run-123",
                    },
                ),
            ):
                payload = minime_rescue_status.build_active_status(
                    watchdog_state="monitoring",
                    binary_path="/tmp/minime",
                    engine_pid=200,
                )

            self.assertEqual(payload["previous_engine_pid"], 100)
            self.assertEqual(payload["engine_pid"], 200)
            self.assertTrue(payload["engine_pid_changed_without_watchdog_restart"])
            self.assertIsNotNone(payload["engine_pid_changed_at"])

    def test_build_active_status_uses_stable_core_structural_pi_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            status_path = base / "rescue_status.json"
            status_path.write_text(json.dumps({"stability_pi_target_fill_pct": 64.0}))
            health_path = base / "health.json"
            health_path.write_text(
                json.dumps(
                    {
                        "stable_core": {
                            "structural_pi": {
                                "active": True,
                                "target_fill_pct": 68.0,
                                "error_pct": 0.5,
                                "integral": 0.1,
                            }
                        }
                    }
                )
            )
            mic_status = base / "mic_status.json"
            mic_status.write_text("{}")
            camera_status = base / "camera_status.json"
            camera_status.write_text("{}")

            with (
                mock.patch.object(minime_rescue_status, "STATUS_PATH", status_path),
                mock.patch.object(minime_rescue_status, "HEALTH_PATH", health_path),
                mock.patch.object(minime_rescue_status, "MIC_STATUS_PATH", mic_status),
                mock.patch.object(minime_rescue_status, "CAMERA_STATUS_PATH", camera_status),
                mock.patch.object(
                    minime_rescue_status,
                    "load_active_profile",
                    return_value={
                        "profile": "bridge_budgeted_sovereignty_v1",
                        "runtime_profile": "stable_core_v1",
                        "stable_core_enabled": True,
                        "engine_target_fill": 55.0,
                    },
                ),
            ):
                payload = minime_rescue_status.build_active_status(
                    watchdog_state="monitoring",
                    binary_path="/tmp/minime",
                    engine_pid=42,
                )

            self.assertEqual(payload["engine_target_fill"], 68.0)
            self.assertTrue(payload["stability_pi_active"])
            self.assertEqual(payload["stability_pi_target_fill_pct"], 68.0)
            self.assertEqual(payload["stability_pi_error_pct"], 0.5)
            self.assertEqual(payload["stability_pi_integral"], 0.1)

    def test_build_inactive_status_resets_lane_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            status_path = base / "rescue_status.json"
            status_path.write_text("{}")

            with mock.patch.object(minime_rescue_status, "STATUS_PATH", status_path):
                payload = minime_rescue_status.build_inactive_status(watchdog_state="inactive")

            self.assertEqual(payload["socket_liveness"], {"7879": False, "7880": False})
            self.assertFalse(payload["engine_pid_changed_without_watchdog_restart"])
            self.assertEqual(payload["audio_disconnect_count"], 0)
            self.assertEqual(payload["video_disconnect_count"], 0)
            self.assertIsNone(payload["audio_last_disconnect_reason"])
            self.assertIsNone(payload["video_last_disconnect_reason"])
            self.assertEqual(
                payload["video_physical_status"]["classification"],
                "physical_camera_unavailable_host_fallback_active",
            )
            self.assertFalse(payload["scaffold_available"])
            self.assertFalse(payload["scaffold_activation_pending"])
            self.assertFalse(payload["scaffold_archived_stale_at_startup"])
            self.assertIsNone(payload["scaffold_drain_weight"])
            self.assertIsNone(payload["scaffold_source"])
            self.assertIsNone(payload["scaffold_profile"])
            self.assertIsNone(payload["scaffold_profile_version"])
            self.assertIsNone(payload["scaffold_mode_cap"])
            self.assertFalse(payload["scaffold_regenerated_at_startup"])
            self.assertIsNone(payload["scaffold_last_loaded_at_unix_ms"])
            self.assertIsNone(payload["scaffold_last_captured_at_unix_ms"])
            self.assertFalse(payload["stability_pi_active"])
            self.assertIsNone(payload["stability_pi_target_fill_pct"])
            self.assertIsNone(payload["stability_pi_error_pct"])
            self.assertIsNone(payload["stability_pi_integral"])
