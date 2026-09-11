"""Tests for stable-core-safe visual request handling."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import visual_frame_service as vfs  # noqa: E402


class TestVisualFrameService(unittest.TestCase):
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
