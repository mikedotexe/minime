import json
import struct
import subprocess
import unittest

from minime_autonomy.self_control_v2 import (
    MinimeSelfControlV2Client,
    SelfControlV2Error,
    validate_exact_self_control_values,
)


def _f32(value):
    """The engine's wire domain for numeric dials (SelfControlValuesV2 is f32)."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _result(
    family,
    values=None,
    status="applied",
    intent_suffix="1",
    felt_effect=False,
):
    deployment = "deployment:test"
    values = dict(values or {})
    receipt = {
        "schema": "self_control.receipt.v2",
        "receipt_id": f"receipt:{family}:{intent_suffix}",
        "command_id": f"command:{family}:{intent_suffix}",
        "intent_id": f"intent:{family}:{intent_suffix}",
        "idempotency_key": f"idempotency:{family}:{intent_suffix}",
        "status": status,
        "requested_revision": 1,
        "resulting_revision": 1,
        "target_being": "minime",
        "target_deployment_identity": deployment,
        "requested_values": values,
        "clamped_values": values,
        "applied_values": values,
        "previous_values": {},
        "received_at_unix_ms": 100,
        "completed_at_unix_ms": 101,
        "control_expires_at_unix_ms": 5000,
        "server_process_identity": "pid:test",
        "server_deployment_identity": deployment,
        "felt_effect_established": felt_effect,
    }
    return {
        "schema": "minime.self_control.issue_result.v1",
        "being": "minime",
        "server_process_identity": "pid:test",
        "server_deployment_identity": deployment,
        "attempts": [{"self_control_receipt": receipt}],
        "felt_effect_established": felt_effect,
    }


class SelfControlV2ClientTests(unittest.TestCase):
    def test_groups_fields_by_family_and_preserves_machine_receipts(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            family = command[command.index("--family") + 1]
            values = json.loads(command[command.index("--values-json") + 1])
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(_result(family, values=values)),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        delivery = client.issue(
            {
                "fill_target": 0.68,
                "geom_curiosity": 0.12,
                "pi_kp": 0.4,
            },
            duration_secs=60,
            evidence_refs=["felt-contract:test"],
        )

        self.assertEqual(
            delivery["families"],
            ["reservoir-regulation", "reservoir-geometry", "pi-controller"],
        )
        self.assertEqual(len(delivery["receipts"]), 3)
        self.assertEqual(delivery["server_deployment_identity"], "deployment:test")
        self.assertTrue(all(call[1]["check"] is False for call in calls))
        values = [
            json.loads(call[0][call[0].index("--values-json") + 1])
            for call in calls
        ]
        # Numeric dials travel f32-quantized (the wire's actual value domain),
        # so the sent JSON carries the f32-exact decimal, not the raw f64.
        self.assertEqual(values[0], {"fill_target": _f32(0.68)})
        self.assertEqual(values[1], {"geom_curiosity": _f32(0.12)})
        self.assertEqual(values[2], {"pi_kp": _f32(0.4)})

    def test_partial_multi_family_failure_withdraws_prior_family(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "withdraw" in command:
                family = command[command.index("--family") + 1]
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        _result(
                            family,
                            values={},
                            status="withdrawn",
                            intent_suffix="w",
                        )
                    ),
                    stderr="",
                )
            family = command[command.index("--family") + 1]
            if family == "reservoir-geometry":
                return subprocess.CompletedProcess(command, 2, stdout="", stderr="blocked")
            values = json.loads(command[command.index("--values-json") + 1])
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(_result(family, values=values)),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        with self.assertRaises(SelfControlV2Error) as caught:
            client.issue({"fill_target": 0.68, "geom_curiosity": 0.12})

        self.assertIn("partial_rollback", caught.exception.details)
        withdraw = [call for call in calls if "withdraw" in call]
        self.assertEqual(len(withdraw), 1)
        self.assertIn("intent:reservoir-regulation:1", withdraw[0])

    def test_status_requires_hash_verified_settled_state(self):
        valid = {
            "schema": "minime.self_control.status.v2",
            "target_being": "minime",
            "integrity_verified": True,
            "pending_transition": False,
            "recent_receipts": [],
        }

        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(valid), stderr=""
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        self.assertEqual(client.status()["target_being"], "minime")
        valid["pending_transition"] = True
        with self.assertRaises(SelfControlV2Error):
            client.status()

    def test_rejects_nonfinite_and_lease_use_of_one_shot_fields(self):
        client = MinimeSelfControlV2Client(binary="/tmp/minime")
        with self.assertRaises(SelfControlV2Error):
            client.issue({"fill_target": float("nan")})
        with self.assertRaises(SelfControlV2Error):
            client.issue({"fill_target": 0.9})
        with self.assertRaises(SelfControlV2Error):
            client.issue({"semantic_strand_retention_turns": 2.5})
        with self.assertRaises(SelfControlV2Error):
            client.issue({"porosity": 0.2}, durability="lease")

    def test_exact_validator_rejects_aliases_and_orphan_timing(self):
        with self.assertRaisesRegex(SelfControlV2Error, "aliases"):
            validate_exact_self_control_values(
                {"porosity": 0.2, "mode_disperse": 0.2}
            )
        with self.assertRaisesRegex(SelfControlV2Error, "requires esn_leak_override"):
            validate_exact_self_control_values({"esn_leak_override_ticks": 2})

    def test_rejects_receipt_that_substitutes_requested_values(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            family = command[command.index("--family") + 1]
            if "withdraw" in command:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        _result(
                            family,
                            values={},
                            status="withdrawn",
                            intent_suffix="rollback",
                        )
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    _result(family, values={"fill_target": 0.55})
                ),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        with self.assertRaisesRegex(SelfControlV2Error, "substituted"):
            client.issue({"fill_target": 0.68})
        withdrawals = [call for call in calls if "withdraw" in call]
        self.assertEqual(len(withdrawals), 1)
        self.assertIn("intent:reservoir-regulation:1", withdrawals[0])

    def test_applies_non_f32_exact_owner_choice_without_false_substitution(self):
        # Regression for 2026-09-01: the engine APPLIED exploration_noise=0.08,
        # echoed its f32 value (0.07999999821186066), and the raw-f64 comparison
        # wrongly rolled the applied control back as "substituted". The choice
        # must be quantized to the wire domain up front so a faithful engine
        # echo validates.
        def runner(command, **_kwargs):
            family = command[command.index("--family") + 1]
            sent = json.loads(command[command.index("--values-json") + 1])
            echoed = {k: _f32(v) if isinstance(v, float) else v for k, v in sent.items()}
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(_result(family, values=echoed)),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        delivery = client.issue({"exploration_noise": 0.08}, duration_secs=60)
        receipt = delivery["receipts"][0]
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(
            receipt["applied_values"], {"exploration_noise": _f32(0.08)}
        )

    def test_rejects_receipt_that_clamps_or_changes_effective_values(self):
        def runner(command, **_kwargs):
            family = command[command.index("--family") + 1]
            payload = _result(family, values={"fill_target": _f32(0.68)})
            payload["attempts"][-1]["self_control_receipt"]["clamped_values"] = {
                "fill_target": 0.55
            }
            payload["attempts"][-1]["self_control_receipt"]["applied_values"] = {
                "fill_target": 0.55
            }
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        with self.assertRaisesRegex(SelfControlV2Error, "exact owner choice"):
            client.issue({"fill_target": 0.68})

    def test_rejects_machine_receipt_that_asserts_felt_effect(self):
        def runner(command, **_kwargs):
            family = command[command.index("--family") + 1]
            values = json.loads(command[command.index("--values-json") + 1])
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    _result(
                        family,
                        values=values,
                        felt_effect=True,
                    )
                ),
                stderr="",
            )

        client = MinimeSelfControlV2Client(binary="/tmp/minime", runner=runner)
        with self.assertRaisesRegex(SelfControlV2Error, "felt effect"):
            client.issue({"fill_target": 0.68})
