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
            self.assertTrue(profile["stable_core_agent_enabled"])

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
                summary = stable_core_ops.sanitize_checkpoint(source, dim=dim)

            self.assertEqual(summary["policy"], "diagonal_only_trace_normalized")
            self.assertTrue(Path(summary["sanitized_path"]).exists())
            data = Path(summary["sanitized_path"]).read_bytes()
            sanitized = list(struct.unpack("<4f", data))
            self.assertAlmostEqual(sum([sanitized[0], sanitized[3]]), 2.0, places=5)
            self.assertEqual(sanitized[1], 0.0)
            self.assertEqual(sanitized[2], 0.0)


if __name__ == "__main__":
    unittest.main()
