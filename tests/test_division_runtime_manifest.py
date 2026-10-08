import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/division_runtime_manifest.py"
SPEC = importlib.util.spec_from_file_location("division_manifest", SCRIPT)
MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANIFEST)


class DivisionRuntimeManifestTests(unittest.TestCase):
    def command(self, root: Path, output: Path) -> list[str]:
        return [
            "python3",
            str(SCRIPT),
            "create",
            "--output",
            str(output),
            "--mode",
            "dormant",
            "--division-id",
            "division-dormant-test",
            "--plan-digest",
            "a" * 64,
            "--parent-generation",
            "0",
            "--candidate-hash",
            "unbound",
            "--parent-process-identity",
            "process-test",
            "--parent-deployment-identity",
            "deployment-test",
            "--runtime-dir",
            str(root / "shared"),
            "--ceremony-ledger",
            str(root / "ceremony.jsonl"),
            "--minime-root",
            str(root / "minime"),
            "--astrid-root",
            str(root / "astrid"),
            "--expires-at-unix-ms",
            str(int(time.time() * 1000) + 60_000),
        ]

    def test_dormant_manifest_is_owner_only_and_unbound(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "shared" / "manifest.json"
            command = self.command(root, output)
            created = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(created.stdout)["ok"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            verified = subprocess.run(
                ["python3", str(SCRIPT), "verify", "--manifest", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(json.loads(verified.stdout)["ok"])
            report = json.loads(verified.stdout)
            self.assertEqual(report["verification_scope"], "structure_and_lifetime")
            self.assertEqual(report["lifetime_status"], "current")
            self.assertFalse(report["runtime_health_verified"])
            self.assertFalse(report["live_authority_granted_by_record"])

    def test_expired_verification_fails_without_changing_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "shared" / "manifest.json"
            subprocess.run(self.command(root, output), check=True, capture_output=True)
            value = json.loads(output.read_bytes())
            value.update(created_at_unix_ms=1, expires_at_unix_ms=2)
            output.write_text(json.dumps(value))
            before, timestamp = output.read_bytes(), output.stat().st_mtime_ns
            for flags, expected_exit in (([], 1), (["--structural-only"], 0)):
                result = subprocess.run(
                    ["python3", str(SCRIPT), "verify", "--manifest", str(output), *flags],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected_exit, result.stdout)
                report = json.loads(result.stdout)
                self.assertEqual(report["ok"], bool(flags))
                self.assertEqual(report["lifetime_status"], "expired")
                self.assertFalse(report["current"])
                self.assertTrue(report["structurally_valid"])
                self.assertEqual(report["remaining_ms"], 0)
                self.assertGreater(report["expired_by_ms"], 0)
                self.assertEqual(report["manifest_sha256"], hashlib.sha256(before).hexdigest())
                self.assertEqual(output.read_bytes(), before)
                self.assertEqual(output.stat().st_mtime_ns, timestamp)

    def test_lifetime_boundaries_and_clock_regression(self):
        value = {"created_at_unix_ms": 100, "expires_at_unix_ms": 200}
        for now, expected in ((99, "clock_before_creation"), (100, "current"),
                              (199, "current"), (200, "current"), (201, "expired")):
            with self.subTest(now=now):
                result = MANIFEST.lifetime(value, now)
                self.assertEqual(result["lifetime_status"], expected)
                self.assertEqual(result["current"], expected == "current")
                self.assertEqual(result["expired_by_ms"], max(0, now - 200))

    def test_future_clock_is_unqualified_and_port_refusal_is_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "shared" / "manifest.json"
            subprocess.run(self.command(root, output), check=True, capture_output=True)
            value = json.loads(output.read_bytes())
            value.update(created_at_unix_ms=1000, expires_at_unix_ms=2000)
            output.write_text(json.dumps(value))
            args = MANIFEST.parser().parse_args(["verify", "--manifest", str(output)])
            with mock.patch.object(MANIFEST.time, "time", return_value=0.999):
                result = MANIFEST.verify(args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["lifetime_status"], "clock_before_creation")
            with mock.patch.object(MANIFEST.socket, "socket") as socket_mock:
                socket_mock.return_value.__enter__.return_value.bind.side_effect = OSError("occupied")
                with self.assertRaisesRegex(MANIFEST.ManifestError, "7900 is occupied"):
                    MANIFEST.validate(value, require_free_ports=True)

    def test_verify_refuses_bad_timestamps_and_non_objects(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "shared" / "manifest.json"
            subprocess.run(self.command(root, output), check=True, capture_output=True)
            valid = json.loads(output.read_bytes())
            for bad in (True, "200", 2.5, -1, 2**64, None):
                with self.subTest(timestamp=bad):
                    output.write_text(json.dumps({**valid, "expires_at_unix_ms": bad}))
                    result = subprocess.run(
                        ["python3", str(SCRIPT), "verify", "--manifest", str(output)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("timestamps", json.loads(result.stdout)["error"])
            output.write_text("[]")
            result = subprocess.run(
                ["python3", str(SCRIPT), "verify", "--manifest", str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("JSON object", json.loads(result.stdout)["error"])

    def test_verify_refuses_link_fifo_oversize_and_public_permissions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target.json"
            target.write_text("{}")
            target.chmod(0o600)
            linked = root / "linked.json"
            linked.symlink_to(target)
            fifo = root / "fifo"
            os.mkfifo(fifo, 0o600)
            large = root / "large.json"
            large.write_bytes(b" " * (64 * 1024 + 1))
            large.chmod(0o600)
            public = root / "public.json"
            public.write_text("{}")
            public.chmod(0o644)
            for path in (linked, fifo, large, public):
                with self.subTest(kind=path.name):
                    result = subprocess.run(
                        ["python3", str(SCRIPT), "verify", "--manifest", str(path)],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(json.loads(result.stdout)["ok"])

    def test_dormant_manifest_rejects_candidate_hash(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            command = [
                "python3",
                str(SCRIPT),
                "create",
                "--output",
                str(root / "shared" / "manifest.json"),
                "--mode",
                "dormant",
                "--division-id",
                "division-dormant-test",
                "--plan-digest",
                "a" * 64,
                "--parent-generation",
                "0",
                "--candidate-hash",
                "b" * 64,
                "--parent-process-identity",
                "process-test",
                "--parent-deployment-identity",
                "deployment-test",
                "--runtime-dir",
                str(root / "shared"),
                "--ceremony-ledger",
                str(root / "ceremony.jsonl"),
                "--minime-root",
                str(root / "minime"),
                "--astrid-root",
                str(root / "astrid"),
                "--expires-at-unix-ms",
                str(int(time.time() * 1000) + 60_000),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unbound", json.loads(result.stdout)["error"])

    def test_nested_daughter_root_and_expired_manifest_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            command = self.command(root, root / "shared" / "manifest.json")
            astrid_index = command.index("--astrid-root") + 1
            command[astrid_index] = str(root / "shared" / "astrid")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("disjoint", json.loads(result.stdout)["error"])

            command = self.command(root, root / "shared" / "expired.json")
            expiry_index = command.index("--expires-at-unix-ms") + 1
            command[expiry_index] = "1"
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lifetime", json.loads(result.stdout)["error"])

    def test_occupied_internal_port_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", 7900))
                except OSError:
                    self.skipTest("internal test port 7900 is already occupied")
                command = self.command(root, root / "shared" / "manifest.json")
                command.append("--require-free-ports")
                result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("occupied", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
