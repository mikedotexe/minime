import json
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa
from minime_autonomy.self_control_v2 import SELF_CONTROL_FAMILY_BY_FIELD


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}


class _FakeWs:
    def __init__(self, sent):
        self.sent = sent

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        pass


class _FakeSelfControlV2:
    def __init__(self, sent):
        self.sent = sent
        self.issued = []
        self.withdrawals = []
        self.expire = False

    def issue(self, values, *, duration_secs, durability="lease", **_kwargs):
        values = dict(values)
        self.sent.append(values)
        expiry = int(time.time() * 1000) + int(duration_secs) * 1000
        families = []
        for field in values:
            family = SELF_CONTROL_FAMILY_BY_FIELD[field]
            if family not in families:
                families.append(family)
        receipts = []
        for family in families:
            index = len(self.issued) + 1
            intent_id = f"self-control-test-intent:{index}"
            receipt_id = f"self-control-test-receipt:{index}"
            family_values = {
                field: value
                for field, value in values.items()
                if SELF_CONTROL_FAMILY_BY_FIELD[field] == family
            }
            receipt = {
                "schema": "self_control.receipt.v2",
                "receipt_id": receipt_id,
                "intent_id": intent_id,
                "status": "applied",
                "control_expires_at_unix_ms": (
                    expiry if durability == "lease" else None
                ),
                "server_deployment_identity": "deployment:test",
                "target_deployment_identity": "deployment:test",
                "applied_values": family_values,
                "previous_values": {},
                "felt_effect_established": False,
            }
            self.issued.append(receipt)
            receipts.append(receipt)
        return {
            "schema": "minime.self_control.autonomy_delivery.v2",
            "server_deployment_identity": "deployment:test",
            "families": families,
            "receipts": receipts,
            "intent_ids": [receipt["intent_id"] for receipt in receipts],
            "receipt_ids": [receipt["receipt_id"] for receipt in receipts],
            "control_expires_at_unix_ms": (
                expiry if durability == "lease" else None
            ),
            "felt_effect_established": False,
        }

    def withdraw(self, family, related_intent_id, **_kwargs):
        receipt = {
            "schema": "self_control.receipt.v2",
            "receipt_id": f"withdrawal:{related_intent_id}",
            "intent_id": f"withdraw:{related_intent_id}",
            "status": "withdrawn",
            "server_deployment_identity": "deployment:test",
            "target_deployment_identity": "deployment:test",
            "applied_values": {},
            "previous_values": {},
            "felt_effect_established": False,
        }
        self.withdrawals.append((family, related_intent_id))
        return {"receipt": receipt, "result": {"attempts": []}}

    def status(self):
        receipts = []
        if self.expire:
            receipts = [
                {
                    **receipt,
                    "receipt_id": f"{receipt['receipt_id']}:expiry",
                    "status": "expired",
                    "applied_values": receipt.get("previous_values") or {},
                    "previous_values": receipt.get("applied_values") or {},
                    "rollback_receipt_id": receipt["receipt_id"],
                }
                for receipt in self.issued
            ]
        return {
            "schema": "minime.self_control.status.v2",
            "target_being": "minime",
            "state_sha256": "a" * 64,
            "preferences": {},
            "held_intents": [],
            "recent_receipts": receipts,
            "integrity_verified": True,
            "pending_transition": False,
        }

    @staticmethod
    def terminal_receipts(status, intent_ids):
        wanted = set(intent_ids)
        return {
            receipt["intent_id"]: receipt
            for receipt in status.get("recent_receipts") or []
            if receipt.get("intent_id") in wanted
            and receipt.get("status")
            in {"expired", "withdrawn", "safety_held", "rolled_back"}
        }


class SelfRegulationLeaseTests(unittest.TestCase):
    def _agent(self, workspace: Path):
        agent = object.__new__(aa.AutonomousAgent)
        agent.session_id = 1
        agent._hard_recovery_reset = False
        agent._current_regime = "focus"
        agent._pi_kp = 0.30
        agent._pi_ki = 0.01
        agent._pi_max_step = 0.04
        agent._pending_self_regulation_next = None
        agent._pending_texture_agency_next = None
        agent._pending_notice_prompt = None
        agent._last_state = dict(STATE)
        agent._sovereignty_state_path = lambda: str(workspace / "sovereignty_state.json")
        agent._low_fill_guard_status = lambda state: {
            "active": False,
            "fill_ratio": state.get("fill_ratio", 0.68),
            "target_fill_ratio": 0.68,
            "spread_relief": 0.0,
        }
        return agent

    def _expire_latest_control(self, workspace: Path) -> None:
        active_path = workspace / "self_regulation/active_lease.json"
        active = json.loads(active_path.read_text())
        active["expires_at_unix_s"] = 1
        active_path.write_text(json.dumps(active))
        ledger_path = workspace / "self_regulation/active_leases_v2.json"
        ledger = json.loads(ledger_path.read_text())
        ledger["leases_by_intent"][active["intent_id"]] = active
        ledger_path.write_text(json.dumps(ledger))

    def test_minime_self_regulation_applies_bounded_dial_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.03,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT open :: goal: test; "
                    "target: exploration_noise; value: 0.20; duration_secs: 60"
                )
                agent._self_regulation_action(dict(STATE))
                self.assertIn("drafted", agent._pending_notice_prompt)

                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(dict(STATE))
                self.assertIn("apply_allowed", agent._pending_notice_prompt)

                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))

            self.assertEqual(sent[-1], {"exploration_noise": 0.2})
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "active")
            self.assertEqual(active["authority"], "authenticated_self_control_v2")
            self.assertTrue(active["machine_receipts"])
            self.assertEqual(active["previous_value"], 0.03)
            self.assertEqual(active["applied_value"], 0.2)
            self.assertIn("baseline_evidence", active)
            self.assertTrue(active["baseline_evidence"])
            persisted = json.loads((workspace / "sovereignty_state.json").read_text())
            self.assertEqual(persisted["exploration_noise"], 0.2)
            negotiations = [
                json.loads(line)
                for line in (workspace / "self_regulation/negotiations.jsonl").read_text().splitlines()
            ]
            apply_record = negotiations[-1]
            self.assertEqual(apply_record["source_action"], "SELF_REGULATION_APPLY")
            self.assertEqual(apply_record["candidate_control"], "exploration_noise")
            self.assertEqual(apply_record["requested_value"], 0.20)
            self.assertEqual(apply_record["applied_value"], 0.2)
            self.assertTrue(apply_record["lease_related"])
            self.assertEqual(apply_record["safe_cap_or_range"]["max"], 0.2)

            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_OUTCOME latest :: helped: felt clearer"
                )
                agent._self_regulation_action(dict(STATE))
            latest = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ][-1]
            self.assertEqual(latest["outcome_score"], 0.82)
            self.assertEqual(latest["repeatability_hint"], "repeatable_playbook_candidate")
            self.assertTrue(latest["promotion_candidate"])
            self.assertTrue(latest["post_lease_evidence"])
            self.assertEqual(latest["outcome_texture"]["status"], "texture_fields_recorded")
            self.assertEqual(latest["outcome_texture"]["what_helped"], "felt clearer")

    def test_footer_directive_clamps_over_cap_request_and_records_negotiation(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.03,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                parsed = aa._parse_footer_directive_requests(
                    "I need more edge.\nexploration_noise: 0.12"
                )
                self.assertEqual(parsed["exploration_noise"]["requested_value"], 0.12)
                self.assertEqual(parsed["exploration_noise"]["applied_value"], 0.08)
                agent._apply_footer_directives(
                    "I need more edge.\nexploration_noise: 0.12"
                )

            self.assertEqual(sent[-1], {"exploration_noise": 0.08})
            self.assertEqual(receiver.issued[-1]["status"], "applied")
            persisted = json.loads((workspace / "sovereignty_state.json").read_text())
            self.assertEqual(persisted["exploration_noise"], 0.08)
            record = [
                json.loads(line)
                for line in (workspace / "self_regulation/negotiations.jsonl").read_text().splitlines()
            ][-1]
            self.assertEqual(record["source"], "footer_directive")
            self.assertFalse(record["lease_related"])
            self.assertEqual(record["candidate_control"], "exploration_noise")
            self.assertEqual(record["requested_value"], 0.12)
            self.assertEqual(record["applied_value"], 0.08)
            self.assertEqual(record["clamp_or_defer_reason"], "clamped_to_lease_safe_range")
            self.assertEqual(record["safe_cap_or_range"]["max"], 0.08)

    def test_metabolism_choice_uses_receipted_lease_without_shadow_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agent = self._agent(workspace)
            agent.thresholds = types.SimpleNamespace(metabolism_low=5.0)
            agent._query_llm_with_next = lambda _prompt: (
                "I choose more stimulation and a faster rhythm.",
                None,
            )
            agent._write_journal_entry = lambda *_args, **_kwargs: None
            sent = []
            receiver = _FakeSelfControlV2(sent)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "runtime_health_path", return_value=workspace / "missing-health.json"
                ),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
                patch.object(agent, "_inject_texture_burst") as shadow_pulse,
            ):
                agent._adjust_metabolism(dict(STATE))

            self.assertEqual(sent, [{"synth_gain": 1.79}])
            self.assertEqual(
                receiver.issued[-1]["control_expires_at_unix_ms"] is not None,
                True,
            )
            shadow_pulse.assert_not_called()
            artifact = next((workspace / "journal").glob("metabolism_increase_*.txt"))
            text = artifact.read_text()
            self.assertIn("Authenticated live control:", text)
            self.assertIn("receiver receipts: self-control-test-receipt:1", text)

    def test_status_accepts_values_inside_expanded_receiver_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.12,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_self_regulation_next = "SELF_REGULATION_STATUS"
                agent._self_regulation_action(dict(STATE))

            self.assertIn("SELF_REGULATION_STATUS", agent._pending_notice_prompt)
            self.assertNotIn("current_above_cap", agent._pending_notice_prompt)
            persisted = json.loads((workspace / "sovereignty_state.json").read_text())
            self.assertEqual(persisted["exploration_noise"], 0.12)

    def test_minime_self_regulation_expiry_reverts_previous_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "geom_curiosity": 0.10,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT curiosity :: target: geom_curiosity; "
                    "delta: +0.20; duration_secs: 60"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))
                self._expire_latest_control(workspace)
                receiver.expire = True
                agent._self_regulation_reconcile_active_lease(dict(STATE))

            self.assertEqual(sent, [{"geom_curiosity": 0.3}])
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "reverted")
            self.assertFalse(active["requires_outcome"])
            self.assertTrue(active["felt_review_available"])
            self.assertFalse(active["felt_review_blocks_control"])
            self.assertTrue(active["post_lease_evidence"])
            self.assertTrue(active["terminal_machine_receipts"])

    def test_felt_review_is_optional_and_only_same_family_overlap_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.03,
                "memory_mode": 0,
                "fill_target": 0.68,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT noise :: "
                    "target: exploration_noise; value: 0.10"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))

                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT memory :: "
                    "target: memory_mode; value: full; durability: standing"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))

                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT fill :: "
                    "target: fill_target; value: 0.65"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_PREFLIGHT latest"
                )
                agent._self_regulation_action(dict(STATE))

            self.assertEqual(
                sent,
                [
                    {"exploration_noise": 0.1},
                    {"memory_mode": 2},
                ],
            )
            self.assertIn(
                "one active mutation is allowed per control family",
                agent._pending_notice_prompt,
            )
            ledger = json.loads(
                (
                    workspace
                    / "self_regulation"
                    / "active_leases_v2.json"
                ).read_text()
            )
            self.assertEqual(
                ledger["schema"],
                "minime.self_regulation.active_leases.v2",
            )
            self.assertFalse(ledger["felt_review_blocks_control"])
            self.assertEqual(len(ledger["leases_by_intent"]), 2)
            families = {
                tuple(lease["self_control_v2_families"])
                for lease in ledger["leases_by_intent"].values()
            }
            self.assertEqual(
                families,
                {("reservoir-regulation",), ("memory",)},
            )

    def test_minime_pressure_relief_bundle_applies_and_reverts_all_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.05,
                "geom_curiosity": 0.12,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            state = dict(STATE, pressure_risk=0.24, mode_packing=0.36, semantic_friction=0.31)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: pressure_relief; "
                    "bundle: reduce_restless_saturation; duration_secs: 60"
                )
                agent._self_regulation_action(state)
                self.assertIn("drafted", agent._pending_notice_prompt)
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(state)
                self.assertIn("pressure relief bundle", agent._pending_notice_prompt)
                self.assertIn("reduce_restless_saturation", agent._pending_notice_prompt)
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(state)

                self.assertEqual(
                    sent[-1],
                    {
                        "exploration_noise": 0.03,
                        "geom_curiosity": 0.07,
                    },
                )
                active_path = workspace / "self_regulation/active_lease.json"
                active = json.loads(active_path.read_text())
                self.assertEqual(active["lease_mode"], "pressure_relief_bundle_v3")
                self.assertEqual(active["bundle_class"], "reduce_restless_saturation")
                self.assertEqual(len(active["bundle_controls"]), 2)
                self.assertEqual(active["previous_value"][0]["previous_value"], 0.05)
                self.assertEqual(active["applied_value"][0]["applied_value"], 0.03)
                negotiations = [
                    json.loads(line)
                    for line in (workspace / "self_regulation/negotiations.jsonl").read_text().splitlines()
                ]
                applied_controls = {
                    row["candidate_control"]: row["applied_value"]
                    for row in negotiations
                    if row["source_action"] == "SELF_REGULATION_APPLY"
                }
                self.assertEqual(applied_controls["exploration_noise"], 0.03)
                self.assertEqual(applied_controls["geom_curiosity"], 0.07)
                self._expire_latest_control(workspace)
                receiver.expire = True
                agent._self_regulation_reconcile_active_lease(state)

            self.assertEqual(len(sent), 1)
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "reverted")
            self.assertFalse(active["requires_outcome"])
            self.assertTrue(active["felt_review_available"])

    def test_minime_pressure_auto_is_advisory_and_apply_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "exploration_noise": 0.05,
                "geom_curiosity": 0.12,
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            state = dict(
                STATE,
                pressure_risk=0.24,
                mode_packing=0.36,
                semantic_friction=0.31,
            )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: pressure_relief; "
                    "bundle: auto; duration_secs: 60"
                )
                agent._self_regulation_action(state)
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_PREFLIGHT latest"
                )
                agent._self_regulation_action(state)
                self.assertIn("selection_required", agent._pending_notice_prompt)
                self.assertIn(
                    "telemetry suggests reduce_restless_saturation",
                    agent._pending_notice_prompt,
                )
                self.assertIn(
                    "telemetry is advisory and cannot author a target",
                    agent._pending_notice_prompt,
                )

                latest = [
                    json.loads(line)
                    for line in (
                        workspace / "self_regulation/leases.jsonl"
                    ).read_text().splitlines()
                ][-1]
                self.assertEqual(latest["bundle_class"], "auto")
                self.assertEqual(
                    latest["suggested_bundle_class"],
                    "reduce_restless_saturation",
                )
                self.assertEqual(latest["bundle_controls"], [])
                self.assertEqual(latest["preflight_status"], "selection_required")

                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_APPLY latest"
                )
                agent._self_regulation_action(state)
                self.assertIn("selection_required", agent._pending_notice_prompt)

            self.assertEqual(sent, [])
            self.assertEqual(receiver.issued, [])

    def test_pressure_agency_status_and_request_keep_pi_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            sent = []
            state = dict(
                STATE,
                pressure_risk=0.42,
                pressure_score=0.39,
                pressure_source="mode_packing",
                pressure_quality="mixed_pressure",
                mode_packing=0.58,
                semantic_friction=0.31,
            )
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
            ):
                agent._pending_pressure_agency_next = "PRESSURE_AGENCY_STATUS"
                agent._pressure_agency_action(state)
                self.assertIn("pressure_source is advisory today", agent._pending_notice_prompt)
                self.assertIn("fill_target changes go through scripts/inhabit_window.py", agent._pending_notice_prompt)
                self.assertIn("MINIME_PI_PRESSURE_WIRING_CANARY remains off", agent._pending_notice_prompt)
                self.assertIn("legible|partly|confusing", agent._pending_notice_prompt)
                self.assertIn("secondary_pressure_shift", agent._pending_notice_prompt)
                self.assertIn("ambiguity_preserved", agent._pending_notice_prompt)
                self.assertIn("legibility_effect", agent._pending_notice_prompt)

                agent._pending_pressure_agency_next = "PRESSURE_AGENCY_REQUEST lower fill_target"
                agent._pressure_agency_action(state)
                self.assertIn("steward_offer_only_no_controller_mutation", agent._pending_notice_prompt)
                self.assertFalse((workspace / "self_regulation/leases.jsonl").exists())

                agent._pending_pressure_agency_next = (
                    "PRESSURE_AGENCY_REQUEST partly :: missing_pressure_variable: pressure velocity"
                )
                agent._pressure_agency_action(state)
                self.assertIn("legibility_feedback_only_no_lease", agent._pending_notice_prompt)
                self.assertFalse((workspace / "self_regulation/leases.jsonl").exists())

                agent._pending_pressure_agency_next = "PRESSURE_AGENCY_REQUEST settle packed pressure"
                agent._pressure_agency_action(state)
                self.assertIn("Drafted SELF_REGULATION pressure_relief intent", agent._pending_notice_prompt)

            self.assertEqual(sent, [])
            leases = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0]["candidate_control"], "pressure_relief")
            self.assertEqual(leases[0]["lease_mode"], "pressure_relief_bundle_v3")
            self.assertEqual(leases[0]["status"], "drafted")
            self.assertEqual(leases[0]["duration_secs"], 600)

    def test_texture_agency_status_and_request_keep_controller_authority_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "health.json").write_text(json.dumps({
                "fill_ratio": 0.73,
                "spectral_entropy": 0.88,
                "semantic_stale_ms": 15000,
                "esn": {
                    "rho": 0.872,
                    "rank1_us": 120,
                    "pending_rank1_depth": 2,
                },
                "stable_core": {"enabled": False},
                "resonance_density_v1": {
                    "texture_signature": {
                        "primary_texture": "overpacked_viscous",
                        "pressure_source_family": "mode_packing",
                        "edge_definition": "soft",
                        "movement_quality": "slow_viscous",
                        "confidence": 0.71,
                        "dynamic_damping_threshold_candidate": 0.25,
                    }
                },
            }))
            agent = self._agent(workspace)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_texture_agency_next = "TEXTURE_AGENCY_STATUS"
                agent._texture_agency_action(dict(STATE))
                self.assertIn("TEXTURE AGENCY STATUS V1", agent._pending_notice_prompt)
                self.assertIn("primary=overpacked_viscous", agent._pending_notice_prompt)
                self.assertIn("rho: 0.872", agent._pending_notice_prompt)
                self.assertIn("rank1_us: 120", agent._pending_notice_prompt)
                self.assertIn("semantic_stale_ms: 15000", agent._pending_notice_prompt)
                self.assertIn("surge_target_weight: 0.846", agent._pending_notice_prompt)
                self.assertIn("active_damping", agent._pending_notice_prompt)
                self.assertIn("MINIME_PI_PRESSURE_WIRING_CANARY remains off", agent._pending_notice_prompt)

                agent._pending_texture_agency_next = "TEXTURE_AGENCY_REQUEST active_damping now"
                agent._texture_agency_action(dict(STATE))
                self.assertIn("steward_review_only_no_controller_mutation", agent._pending_notice_prompt)
                self.assertFalse((workspace / "self_regulation/leases.jsonl").exists())

                agent._pending_texture_agency_next = (
                    "TEXTURE_AGENCY_REQUEST partly :: missing_texture_variable: edge velocity"
                )
                agent._texture_agency_action(dict(STATE))
                self.assertIn("texture_feedback_only_no_lease", agent._pending_notice_prompt)
                self.assertFalse((workspace / "self_regulation/leases.jsonl").exists())

                agent._pending_texture_agency_next = (
                    "TEXTURE_AGENCY_REQUEST soften viscosity with exploration_noise"
                )
                agent._texture_agency_action(dict(STATE))
                self.assertIn("drafted_bounded_texture_lease", agent._pending_notice_prompt)

            leases = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0]["candidate_control"], "exploration_noise")
            self.assertEqual(leases[0]["status"], "drafted")
            self.assertEqual(leases[0]["duration_secs"], 600)

    def test_minime_outcome_records_texture_shift_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "sovereignty_state.json").write_text(json.dumps({
                "regime": "focus",
            }))
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: regime; value: calm; duration_secs: 60"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_OUTCOME latest :: before_texture: grinding compaction; "
                    "after_texture: suspension; texture_shift: compaction -> suspension; "
                    "agency_fit: legible; what_helped: smaller bundle; what_worsened: none"
                )
                agent._self_regulation_action(dict(STATE))

            latest = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ][-1]
            self.assertEqual(
                latest["outcome_texture"]["policy"],
                "pressure_relief_outcome_texture_v1",
            )
            self.assertEqual(latest["outcome_texture"]["schema_version"], 2)
            self.assertEqual(
                latest["outcome_texture"]["texture_shift"],
                "compaction -> suspension",
            )
            self.assertEqual(latest["outcome_texture"]["agency_fit"], "legible")
            self.assertEqual(latest["outcome_texture"]["secondary_pressure_status"], "none")
            self.assertFalse(latest["outcome_texture"]["ambiguity_preserved"])
            self.assertIn("grinding_compaction", latest["outcome_texture"]["signal_families"])
            self.assertIn("suspension_porosity", latest["outcome_texture"]["signal_families"])
            self.assertTrue(
                any("outcome_texture" in entry for entry in latest["post_lease_evidence"])
            )

    def test_minime_outcome_records_v2_pressure_texture_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: regime; value: calm; duration_secs: 60"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_OUTCOME latest :: texture_shift: eased compaction; "
                    "what_worsened: eased compaction but tightened a different knot elsewhere; "
                    "ambiguity_preserved: yes; legibility_effect: flattened"
                )
                agent._self_regulation_action(dict(STATE))

            latest = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ][-1]
            self.assertEqual(
                latest["outcome_texture"]["secondary_pressure_status"],
                "tightened_elsewhere",
            )
            self.assertTrue(latest["outcome_texture"]["ambiguity_preserved"])
            self.assertEqual(latest["outcome_texture"]["legibility_effect"], "flattened")
            self.assertIn(
                "secondary_knot_tightening",
                latest["outcome_texture"]["signal_families"],
            )
            self.assertTrue(
                any(
                    "secondary_pressure_status=tightened_elsewhere" in entry
                    for entry in latest["post_lease_evidence"]
                )
            )

    def test_minime_self_regulation_keeps_peer_change_preflight_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT peer :: target: TUNE_ASTRID; goal: no peer mutation"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(dict(STATE))

            self.assertIn("preflight_only", agent._pending_notice_prompt)
            latest = [
                json.loads(line)
                for line in (workspace / "self_regulation/leases.jsonl").read_text().splitlines()
            ][-1]
            self.assertEqual(latest["candidate_control"], "tune_astrid")
            self.assertEqual(latest["preflight_status"], "preflight_only")

    def test_minime_self_regulation_status_renders_returnable_distinctions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            review_root = root / "reviews"
            run_dir = review_root / "run"
            workspace.mkdir()
            run_dir.mkdir(parents=True)
            (run_dir / "review.json").write_text(json.dumps({
                "returnable_distinctions_v1": {
                    "status": "returnable_distinctions_present",
                    "cards": [
                        {
                            "card_id": "pressure_level_vs_pressure_velocity",
                            "status": "felt_pressure_without_trend_context",
                            "lifecycle_state": "needs_audit",
                            "preflight_verdict": "audit_first",
                            "next_resolution_route": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                            "recommended_read_only_route": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                            "relevant_self_regulation_route": "SELF_REGULATION_PREFLIGHT latest",
                            "relevant_experiment_lived_term_route": "EXPERIMENT_OBSERVE current :: pressure_trend=<stable|rising|falling>",
                        }
                    ],
                }
            }))
            agent = self._agent(workspace)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "ASTRID_SELF_STUDY_REVIEW_DIR", review_root),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: exploration_noise; direction: up"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(dict(STATE))
                self.assertIn("apply_allowed", agent._pending_notice_prompt)
                self.assertIn("Distinction-aware preflight", agent._pending_notice_prompt)
                self.assertIn("audit_first", agent._pending_notice_prompt)
                self.assertIn("preflight_status unchanged", agent._pending_notice_prompt)
                self.assertIn(
                    "pressure_level_vs_pressure_velocity",
                    agent._pending_notice_prompt,
                )

                agent._pending_self_regulation_next = "SELF_REGULATION_STATUS"
                agent._self_regulation_action(dict(STATE))
                self.assertIn("SELF_REGULATION_STATUS", agent._pending_notice_prompt)
                self.assertIn("Returnable distinctions", agent._pending_notice_prompt)
                self.assertIn("lifecycle=`needs_audit`", agent._pending_notice_prompt)

    def test_minime_self_regulation_blocks_apply_during_hard_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            agent._hard_recovery_reset = True
            agent._low_fill_guard_status = lambda state: {
                "active": True,
                "fill_ratio": 0.25,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
            }
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT noise :: target: exploration_noise; direction: up"
                )
                agent._self_regulation_action({"fill_ratio": 0.25})
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action({"fill_ratio": 0.25})

            self.assertIn("hard recovery reset", agent._pending_notice_prompt)

    def test_broad_memory_standing_preference_can_be_withdrawn_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT memory :: target: memory_mode; "
                    "value: full; durability: standing"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(dict(STATE))
                self.assertIn("apply_allowed", agent._pending_notice_prompt)
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))
                active = json.loads(
                    (workspace / "self_regulation/active_lease.json").read_text()
                )
                self.assertEqual(active["durability"], "standing")
                self.assertIsNone(active["expires_at_unix_s"])
                self.assertEqual(active["self_control_v2_families"], ["memory"])
                agent._pending_self_regulation_next = "SELF_REGULATION_WITHDRAW"
                agent._self_regulation_action(dict(STATE))

            self.assertEqual(sent, [{"memory_mode": 2}])
            self.assertEqual(
                receiver.withdrawals,
                [("memory", "self-control-test-intent:1")],
            )
            active = json.loads(
                (workspace / "self_regulation/active_lease.json").read_text()
            )
            self.assertEqual(active["status"], "withdrawn")
            self.assertTrue(active["withdrawal_receipts"])

    def test_porosity_is_inferred_as_receipted_one_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            sent = []
            receiver = _FakeSelfControlV2(sent)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(
                    aa, "MinimeSelfControlV2Client", return_value=receiver
                ),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT loosen :: target: porosity; value: 0.6"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))

            self.assertEqual(
                sent,
                [{
                    "porosity": 0.6,
                    "mode_disperse_duration_ticks": 4,
                    "mode_disperse_decay_ticks": 8,
                }],
            )
            active = json.loads(
                (workspace / "self_regulation/active_lease.json").read_text()
            )
            self.assertEqual(active["durability"], "one_shot")
            self.assertEqual(active["status"], "completed_one_shot")
            self.assertIsNone(active["expires_at_unix_s"])

    def test_nonzero_semantic_companion_mix_reaches_signed_self_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            agent = self._agent(workspace)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT companion :: "
                    "target: semantic_companion_mix; value: 0.2"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_PREFLIGHT latest"
                agent._self_regulation_action(dict(STATE))

            self.assertIn("apply_allowed", agent._pending_notice_prompt)


if __name__ == "__main__":
    unittest.main()
