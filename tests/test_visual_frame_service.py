"""Tests for stable-core-safe visual request handling."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import visual_frame_service as vfs  # noqa: E402


class TestVisualFrameService(unittest.TestCase):
    def test_shutdown_finishes_current_request_and_preserves_next(self):
        service = vfs.VisualFrameService()
        first = vfs.REQUESTS_DIR / "a.json"
        second = vfs.REQUESTS_DIR / "b.json"
        first.write_text("{}")
        second.write_text("{}")
        calls = []
        def process(path):
            self.assertEqual(service.active_request, "a.json")
            service.request_stop()
            calls.append(path.name)
            path.rename(vfs.REQUESTS_DIR / "processed" / path.name)
        with mock.patch.object(service, "process_request", side_effect=process):
            service.start()
        self.assertEqual(calls, ["a.json"])
        self.assertTrue(second.exists())
        self.assertFalse(service.running)
        status = json.loads(vfs.VISUAL_STATUS_PATH.read_text())
        self.assertEqual(status["state"], "stopping")
        self.assertIsNone(status["active_request"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["pid"], vfs.os.getpid())
        self.assertEqual(status["lifecycle_contract"], "visual_finish_current_request_v1")
        self.assertEqual(status["source_inputs_sha256_at_start"], service.source_inputs_sha256_at_start)

    def test_busy_status_written_before_request(self):
        service = vfs.VisualFrameService()
        (vfs.REQUESTS_DIR / "fixture.json").write_text("{}")
        def process(path):
            status = json.loads(vfs.VISUAL_STATUS_PATH.read_text())
            self.assertEqual(status["state"], "busy")
            self.assertEqual(status["active_request"], path.name)
        with mock.patch.object(service, "process_request", side_effect=process):
            service.process_pending()
        self.assertIsNone(service.active_request)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name)
        (workspace / "runtime").mkdir()
        for name, path in {
            "WORKSPACE_DIR": workspace, "REQUESTS_DIR": workspace / "visual_requests",
            "RESPONSES_DIR": workspace / "visual_responses", "CAPTURES_DIR": workspace / "visual_captures",
            "RUNTIME_DIR": workspace / "runtime",
            "VISUAL_STATUS_PATH": workspace / "runtime/visual_status.json",
        }.items():
            patcher = mock.patch.object(vfs, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_command_only_legacy_request_has_receipt_without_capture(self):
        service = vfs.VisualFrameService()
        request = vfs.REQUESTS_DIR / "fixture.json"
        request.write_text(json.dumps({"prompt": "NEXT: EXPERIMENT_PLAN 4"}))
        with mock.patch.object(service, "capture_frame") as capture:
            service.process_request(request)
        capture.assert_not_called()
        data = json.loads((vfs.RESPONSES_DIR / "response_fixture.json").read_text())
        self.assertEqual(data["error"], "visual_prompt_empty_after_action_separation")
        self.assertFalse(data["semantic_sent"])
        self.assertTrue((vfs.REQUESTS_DIR / "processed/fixture.json").exists())

    def test_capture_clock_precedes_analysis_and_next_never_reaches_model(self):
        service = vfs.VisualFrameService()
        request = vfs.REQUESTS_DIR / "fixture.json"
        request.write_text(json.dumps({"prompt": "Describe the window.\nNEXT: REST"}))
        start = datetime(2026, 9, 18, tzinfo=timezone.utc)
        clock = mock.Mock(wraps=datetime)
        clock.now.return_value = start
        def analyze(frame, prompt):
            self.assertEqual(prompt, "Describe the window.")
            clock.now.return_value = start + timedelta(seconds=15)
            return "A window"
        with (
            mock.patch.object(vfs, "datetime", clock),
            mock.patch.object(service, "capture_frame", return_value=(vfs.np.zeros((8, 8), dtype=vfs.np.uint8), "host")),
            mock.patch.object(service, "analyze_with_llava", side_effect=analyze),
            mock.patch.object(service, "_semantic_send_allowed", return_value=(False, "fixture")),
        ):
            service.process_request(request)
        data = json.loads((vfs.RESPONSES_DIR / "response_fixture.json").read_text())
        self.assertEqual(data["capture_timestamp"], start.isoformat())
        self.assertEqual(data["response_timestamp"], (start + timedelta(seconds=15)).isoformat())
        with mock.patch.object(vfs.time, "time", return_value=start.timestamp() + 900):
            service._write_status()
        status = json.loads(vfs.VISUAL_STATUS_PATH.read_text())
        self.assertTrue(status["healthy"])
        self.assertEqual(status["visual_freshness"]["response_freshness"], "stale")
        self.assertEqual(status["visual_freshness"]["last_frame_acquired_age_s"], 900)

    def test_stale_requests_are_skipped_without_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            requests = workspace / "visual_requests"
            responses = workspace / "visual_responses"
            captures = workspace / "visual_captures"
            runtime = workspace / "runtime"

            with (
                mock.patch.object(vfs, "WORKSPACE_DIR", workspace),
                mock.patch.object(vfs, "REQUESTS_DIR", requests),
                mock.patch.object(vfs, "RESPONSES_DIR", responses),
                mock.patch.object(vfs, "CAPTURES_DIR", captures),
                mock.patch.object(vfs, "RUNTIME_DIR", runtime),
                mock.patch.object(vfs, "REQUEST_MAX_AGE_S", 1.0),
            ):
                service = vfs.VisualFrameService()
                request = requests / "old.json"
                request.write_text(json.dumps({"timestamp": "2026-04-20T00:00:00"}))
                old = time.time() - 3600
                request.touch()
                import os

                os.utime(request, (old, old))

                with mock.patch.object(service, "capture_frame") as capture:
                    service.process_request(request)

                capture.assert_not_called()
                response = json.loads((responses / "response_old.json").read_text())
                self.assertEqual(response["error"], "stale_request_skipped")
                self.assertFalse(response["semantic_sent"])

    def test_stable_core_blocks_visual_semantic_send_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            profile = workspace / "rescue_profile.json"
            profile.write_text(json.dumps({"stable_core_enabled": True}))

            with mock.patch.object(vfs, "RESCUE_PROFILE_PATH", profile):
                allowed, reason = vfs.VisualFrameService()._semantic_send_allowed()

            self.assertFalse(allowed)
            self.assertEqual(reason, "stable_core_visual_semantic_disabled")

    def test_captured_frame_without_analysis_is_not_a_model_description(self) -> None:
        for analyze in (True, False):
            with self.subTest(analyze=analyze), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                requests = workspace / "visual_requests"
                responses = workspace / "visual_responses"
                with (
                    mock.patch.object(vfs, "REQUESTS_DIR", requests),
                    mock.patch.object(vfs, "RESPONSES_DIR", responses),
                    mock.patch.object(vfs, "CAPTURES_DIR", workspace / "visual_captures"),
                ):
                    service = vfs.VisualFrameService()
                    request = requests / "fixture.json"
                    request.write_text(json.dumps({"request_id": "fixture", "analyze": analyze}))
                    frame = vfs.np.zeros((8, 8), dtype=vfs.np.uint8)
                    with (
                        mock.patch.object(service, "capture_frame", return_value=(frame, "host")),
                        mock.patch.object(service, "analyze_with_llava", return_value=None) as model,
                        mock.patch.object(service, "_semantic_send_allowed", return_value=(False, "fixture")),
                        mock.patch.object(service, "send_semantic") as semantic,
                    ):
                        service.process_request(request)
                    self.assertEqual(model.call_count, int(analyze))
                    semantic.assert_not_called()
                    response = json.loads((responses / "response_fixture.json").read_text())
                    self.assertTrue(response["visual_available"])
                    self.assertEqual(response["source"], "host")
                    self.assertEqual(response["analysis_type"], "none")
                    self.assertEqual(response["description"], "(LLaVA unavailable)")
                    self.assertIn("response_timestamp", response)
                    self.assertNotIn("error", response)


if __name__ == "__main__":
    unittest.main()
