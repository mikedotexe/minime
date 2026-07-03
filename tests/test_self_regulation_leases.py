import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}


class _FakeWs:
    def __init__(self, sent):
        self.sent = sent

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        pass


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
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
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

            self.assertEqual(sent[-1], {"kind": "control", "exploration_noise": 0.05})
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "active")
            self.assertEqual(active["previous_value"], 0.03)
            self.assertEqual(active["applied_value"], 0.05)
            self.assertIn("baseline_evidence", active)
            self.assertTrue(active["baseline_evidence"])
            persisted = json.loads((workspace / "sovereignty_state.json").read_text())
            self.assertEqual(persisted["exploration_noise"], 0.05)
            negotiations = [
                json.loads(line)
                for line in (workspace / "self_regulation/negotiations.jsonl").read_text().splitlines()
            ]
            apply_record = negotiations[-1]
            self.assertEqual(apply_record["source_action"], "SELF_REGULATION_APPLY")
            self.assertEqual(apply_record["candidate_control"], "exploration_noise")
            self.assertEqual(apply_record["requested_value"], 0.20)
            self.assertEqual(apply_record["applied_value"], 0.05)
            self.assertTrue(apply_record["lease_related"])
            self.assertEqual(apply_record["safe_cap_or_range"]["max"], 0.08)

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
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
            ):
                parsed = aa._parse_footer_directive_requests(
                    "I need more edge.\nexploration_noise: 0.12"
                )
                self.assertEqual(parsed["exploration_noise"]["requested_value"], 0.12)
                self.assertEqual(parsed["exploration_noise"]["applied_value"], 0.08)
                agent._apply_footer_directives(
                    "I need more edge.\nexploration_noise: 0.12"
                )

            self.assertEqual(sent[-1], {"kind": "control", "exploration_noise": 0.08})
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

    def test_status_reports_already_persisted_over_cap_without_auto_lowering(self):
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

            self.assertIn("current_above_cap", agent._pending_notice_prompt)
            self.assertIn("exploration_noise", agent._pending_notice_prompt)
            self.assertIn("not auto-lowered", agent._pending_notice_prompt)
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
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT curiosity :: target: geom_curiosity; "
                    "delta: +0.20; duration_secs: 60"
                )
                agent._self_regulation_action(dict(STATE))
                agent._pending_self_regulation_next = "SELF_REGULATION_APPLY latest"
                agent._self_regulation_action(dict(STATE))
                active_path = workspace / "self_regulation/active_lease.json"
                active = json.loads(active_path.read_text())
                active["expires_at_unix_s"] = 1
                active_path.write_text(json.dumps(active))
                agent._self_regulation_reconcile_active_lease(dict(STATE))

            self.assertEqual(sent[-1], {"kind": "control", "geom_curiosity": 0.1})
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "reverted")
            self.assertTrue(active["requires_outcome"])
            self.assertTrue(active["post_lease_evidence"])

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
            state = dict(STATE, pressure_risk=0.24, mode_packing=0.36, semantic_friction=0.31)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
            ):
                agent._pending_self_regulation_next = (
                    "SELF_REGULATION_INTENT pressure :: target: pressure_relief; "
                    "bundle: auto; duration_secs: 60"
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
                        "kind": "control",
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
                active["expires_at_unix_s"] = 1
                active_path.write_text(json.dumps(active))
                agent._self_regulation_reconcile_active_lease(state)

            self.assertEqual(
                sent[-1],
                {
                    "kind": "control",
                    "geom_curiosity": 0.12,
                    "exploration_noise": 0.05,
                },
            )
            active = json.loads((workspace / "self_regulation/active_lease.json").read_text())
            self.assertEqual(active["status"], "reverted")
            self.assertTrue(active["requires_outcome"])

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
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
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
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.websocket, "create_connection", return_value=_FakeWs(sent)),
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


if __name__ == "__main__":
    unittest.main()
