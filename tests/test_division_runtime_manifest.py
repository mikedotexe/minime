import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/division_runtime_manifest.py"


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
