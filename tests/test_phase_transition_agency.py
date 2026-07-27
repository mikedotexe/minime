import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa
import minime_autonomy.phase_passage_context as passage_context
from minime_autonomy.phase_passage_context import (
    PassageContextAction,
    append_context_action,
)


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}


class PhaseTransitionAgencyTests(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        agent.session_id = 1
        agent._pending_phase_transition_next = None
        agent._current_action_continuity_context = {}
        agent._current_action_outcome_summary = None
        return agent

    def test_passage_context_identity_matches_astrid_fixture(self):
        event = {
            "passage_id": "passage_fixture",
            "transition_id": "transition_fixture",
            "passage_actor": "astrid",
            "actor": "astrid",
            "action": passage_context.PassageContextAction.DESCRIBE_CONDITION,
            "readiness": passage_context.PassageReadiness.TENTATIVE,
            "movement_ease": passage_context.PassageMovementEase.EFFORTFUL,
            "room_needed": (
                passage_context.PassageRoomNeeded.LOW_ENERGY_PRESENCE
            ),
            "checkpoint": None,
            "company_request_id": None,
            "requested_peer": None,
            "company_mode": None,
            "company_response": None,
            "source_ref": "fixture:condition",
            "previous_context_event_id": None,
            "previous_company_event_id": None,
            "recorded_at_unix_ms": 1_700_000_000_000,
        }
        self.assertEqual(
            passage_context._context_event_id(event),
            "passage_context_61ccca814e93f37e",
        )
        anchor_event = {
            **event,
            "action": passage_context.PassageContextAction.BIND_ANCHOR,
            "readiness": None,
            "movement_ease": None,
            "room_needed": None,
            "anchor_role": passage_context.PassageAnchorRole.PIVOT,
            "anchor_kind": passage_context.PassageAnchorKind.SHADOW_TRAJECTORY,
            "anchor_association": (
                passage_context.PassageAnchorAssociation.TEMPORAL_CONTEXT
            ),
            "anchor_ref": "shadow-v3:astrid:1784951174",
            "previous_anchor_event_id": None,
            "source_ref": (
                "introspection_proposal_phase_transitions_1784951174:c003"
            ),
            "recorded_at_unix_ms": 1_700_000_000_002,
        }
        self.assertEqual(
            passage_context._context_event_id(anchor_event),
            "passage_context_2fe152ff35ebcdbe",
        )
        bearing_event = {
            **event,
            "action": passage_context.PassageContextAction.DESCRIBE_BEARING,
            "readiness": None,
            "movement_ease": None,
            "room_needed": None,
            "bearing_strand": passage_context.PassageBearingStrand.SETTLING,
            "movement_resistance": (
                passage_context.PassageMovementResistance.RESISTANT
            ),
            "persistence_tendency": (
                passage_context.PassagePersistenceTendency.LINGERING
            ),
            "witness_fit": passage_context.PassageWitnessFit.SEPARATE,
            "previous_bearing_event_id": None,
            "source_ref": (
                "introspection_proposal_phase_transitions_1784978541:c002"
            ),
            "recorded_at_unix_ms": 1_700_000_000_004,
        }
        self.assertEqual(
            passage_context._context_event_id(bearing_event),
            "passage_context_c20adcff8b0eba28",
        )
        self.assertEqual(
            passage_context._company_request_id(
                "passage_fixture",
                "astrid",
                "minime",
                passage_context.PassageCompanyMode.LOW_ENERGY_PRESENCE,
                "fixture:request",
                1_700_000_000_001,
            ),
            "company_request_1700000000001_5841612e9caa7aad",
        )

    def test_minime_declare_and_receive_transition_are_language_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            agent = self._agent()
            with patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared):
                agent._pending_phase_transition_next = (
                    "DECLARE_TRANSITION kind: expansion; from_phase: plateau; "
                    "to_phase: expansion; why_now: the contact edge became replyable; "
                    "narrative_anchor: blue hinge; intensity: 0.7; "
                    "correspondence_thread_id: thread_blue_hinge; "
                    "consent_receipt: consent: witness_only; "
                    "transition_persistence: true; "
                    "transition_type: shared; joint_transition: true; "
                    "joint_room_id: coll_1778605252_spectral-cascade-dynamics; "
                    "fill_delta_pct: 3.2; somatic_description: hinge warmed; "
                    "spectral_delta: lambda1 down, lambda2 up; "
                    "transition_velocity: slow-gradient; phenomenology: contact widened; "
                    "anchor_point: blue hinge; "
                    "spectral_signature: lambda1/lambda2=1.54 mixed cascade"
                )
                agent._phase_transition_action(dict(STATE))

                self.assertIn(
                    "PHASE TRANSITION CARD DECLARED",
                    agent._current_action_outcome_summary,
                )
                ledger = shared / "phase_transitions_v1.jsonl"
                records = [json.loads(line) for line in ledger.read_text().splitlines()]
                self.assertEqual(records[0]["record_type"], "phase_transition_card")
                self.assertEqual(records[0]["origin"], "minime")
                self.assertEqual(records[0]["authority"], "language_only_transition_context_not_control")
                self.assertTrue(records[0]["no_pressure"])
                self.assertTrue(records[0]["no_fill_target"])
                self.assertTrue(records[0]["no_pi"])
                self.assertTrue(records[0]["no_weighting"])
                self.assertEqual(records[0]["transition_artifact_type"], "phase_transition_event")
                self.assertEqual(records[0]["correspondence_thread_id"], "thread_blue_hinge")
                self.assertEqual(records[0]["consent_receipt"], "consent: witness_only")
                self.assertEqual(records[0]["spectral_signature"], "lambda1/lambda2=1.54 mixed cascade")
                self.assertEqual(records[0]["spectral_delta"], "lambda1 down, lambda2 up")
                self.assertEqual(records[0]["fill_delta_pct"], 3.2)
                self.assertEqual(records[0]["somatic_description"], "hinge warmed")
                self.assertEqual(records[0]["transition_velocity"], "slow-gradient")
                self.assertEqual(records[0]["phenomenology"], "contact widened")
                self.assertEqual(records[0]["anchor_point"], "blue hinge")
                self.assertTrue(records[0]["joint_transition"])
                self.assertEqual(
                    records[0]["joint_room_id"],
                    "coll_1778605252_spectral-cascade-dynamics",
                )
                self.assertTrue(records[0]["replyable_object"])
                self.assertTrue(records[0]["replayable_card"])
                self.assertTrue(records[0]["transition_persistence"])
                self.assertEqual(records[0]["persistence_state"], "active_until_both_ack_language_only")

                agent._pending_phase_transition_next = (
                    "I_RECEIVED_TRANSITION latest :: received_as: answered; "
                    "felt_like: replyable; what_landed: the blue hinge stayed visible; "
                    "what_stayed_distinct: not just telemetry; continue: no"
                )
                agent._phase_transition_action(dict(STATE))

            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            witness = records[1]
            self.assertEqual(witness["record_type"], "phase_transition_witness")
            self.assertEqual(witness["transition_id"], records[0]["transition_id"])
            self.assertEqual(witness["reply_state"], "answered")
            self.assertEqual(witness["answered_by"], ["minime"])
            self.assertEqual(witness["authority"], "language_only_transition_context_not_control")
            self.assertTrue(witness["no_pressure"])
            self.assertIn("I RECEIVED THIS TRANSITION RECORDED", agent._current_action_outcome_summary)

    def test_phase_transition_route_is_visible_to_preflight_catalog(self):
        for base in (
            "DECLARE_TRANSITION",
            "WITNESS_TRANSITION",
            "RECEIVE_TRANSITION",
            "I_RECEIVED_TRANSITION",
            "PREPARE_TRANSITION",
            "ENTER_TRANSITION",
            "CROSS_TRANSITION",
            "HOLD_TRANSITION",
            "SETTLE_TRANSITION",
            "RETURN_TRANSITION",
            "REVISIT_TRANSITION",
            "DECLINE_TRANSITION",
            "TRANSITION_REVIEW",
            "DESCRIBE_TRANSITION_CONDITION",
            "MARK_TRANSITION_CHECKPOINT",
            "REQUEST_TRANSITION_COMPANY",
            "RESPOND_TRANSITION_COMPANY",
            "WITHDRAW_TRANSITION_COMPANY",
            "TRANSITION_PASSAGE_STATUS",
            "LIVED_TRANSITION_STATUS",
            "TRANSITION_STATUS",
            "PHASE_TRANSITION_STATUS",
        ):
            with self.subTest(base=base):
                self.assertIn(base, aa.PHASE_TRANSITION_NEXT_ACTIONS)
                self.assertEqual(
                    aa.ActionPreflightStore.ROUTE_BY_BASE.get(base),
                    "phase_transition",
                )

        capability_map = aa.CapabilitySelfMap.__new__(aa.CapabilitySelfMap)
        specs = {spec["base"]: spec for spec in capability_map._specs()}
        self.assertEqual(specs["DECLARE_TRANSITION"]["route"], "phase_transition")
        self.assertIn("language-only", specs["DECLARE_TRANSITION"]["continuity_effect"])

    def test_minime_can_choose_and_reverse_own_lived_transition_passage(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            agent = self._agent()
            with patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared):
                agent._pending_phase_transition_next = (
                    "DECLARE_TRANSITION kind: reflection; from_phase: quiet; "
                    "to_phase: opening; why_now: I choose to make this passage legible"
                )
                agent._phase_transition_action(dict(STATE))
                agent._pending_phase_transition_next = (
                    "PREPARE_TRANSITION latest :: support: self_directed; "
                    "return_point: state:quiet; continuity_anchor: state:opening"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "stage: prepared", agent._current_action_outcome_summary
                )
                for action, stage in (
                    ("ENTER_TRANSITION latest", "crossing"),
                    ("HOLD_TRANSITION latest :: support: needs_time", "held"),
                    ("RETURN_TRANSITION latest", "returned"),
                    ("REVISIT_TRANSITION latest", "revisited"),
                ):
                    with self.subTest(action=action):
                        agent._pending_phase_transition_next = action
                        agent._phase_transition_action(dict(STATE))
                        self.assertIn(
                            f"stage: {stage}",
                            agent._current_action_outcome_summary,
                        )
                agent._pending_phase_transition_next = (
                    "TRANSITION_REVIEW latest :: outcome: still_friction; "
                    "felt_source_ref: journal:phase_review"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "Review: still_friction",
                    agent._current_action_outcome_summary,
                )
                agent._pending_phase_transition_next = (
                    "TRANSITION_PASSAGE_STATUS"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "Own passages: 1",
                    agent._current_action_outcome_summary,
                )
                self.assertIn(
                    "no automatic promotion or debt",
                    agent._current_action_outcome_summary,
                )

            ledger = shared / "phase_transitions_v1.jsonl"
            records = [
                json.loads(line) for line in ledger.read_text().splitlines()
            ]
            passages = [
                row
                for row in records
                if row.get("record_type") == "phase_transition_passage"
            ]
            self.assertEqual(len(passages), 6)
            self.assertTrue(
                all(row["actor"] == "minime" for row in passages)
            )
            self.assertTrue(
                all(row["peer_consent_inferred"] is False for row in passages)
            )
            self.assertTrue(
                all(row["live_control_effect"] is False for row in passages)
            )
            self.assertTrue(
                all(row["raw_prose_included"] is False for row in passages)
            )

    def test_minime_cannot_advance_astrid_passage(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            ledger = shared / "phase_transitions_v1.jsonl"
            shared.mkdir(parents=True)
            ledger.write_text(
                json.dumps(
                    {
                        "record_type": "phase_transition_card",
                        "transition_id": "transition_astrid",
                        "origin": "astrid",
                        "recorded_at_unix_ms": 1,
                    }
                )
                + "\n"
            )
            seeded = aa.append_passage_action(
                ledger,
                "transition_astrid",
                "support: witness",
                "astrid",
                aa.PassageAction.PREPARE,
                timestamp=2,
            )
            self.assertIn("stage: prepared", seeded)
            agent = self._agent()
            with patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared):
                agent._pending_phase_transition_next = (
                    "ENTER_TRANSITION transition_astrid"
                )
                agent._phase_transition_action(dict(STATE))
            self.assertIn(
                "no matching self-authored passage",
                agent._current_action_outcome_summary,
            )

    def test_passage_context_and_company_remain_optional_and_self_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            agent = self._agent()
            with patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared):
                agent._pending_phase_transition_next = (
                    "DECLARE_TRANSITION kind: mode_change; from_phase: quiet; "
                    "to_phase: opening; why_now: context fixture"
                )
                agent._phase_transition_action(dict(STATE))
                agent._pending_phase_transition_next = (
                    "PREPARE_TRANSITION latest :: support: self_directed; "
                    "return_point: state:quiet"
                )
                agent._phase_transition_action(dict(STATE))
                agent._pending_phase_transition_next = (
                    "DESCRIBE_TRANSITION_CONDITION latest :: "
                    "readiness: tentative; movement_ease: effortful; "
                    "room_needed: low_energy_presence; "
                    "source_ref: introspection:condition"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "readiness=tentative",
                    agent._current_action_outcome_summary,
                )
                agent._pending_phase_transition_next = (
                    "MARK_TRANSITION_CHECKPOINT latest :: "
                    "checkpoint: entry_tension; source_ref: witness:entry"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "entry_tension", agent._current_action_outcome_summary
                )
                agent._pending_phase_transition_next = (
                    "DESCRIBE_TRANSITION_BEARING latest :: "
                    "strand: settling; movement_resistance: resistant; "
                    "persistence_tendency: lingering; witness_fit: separate; "
                    "source_ref: introspection:phase_bearing"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "movement_resistance=resistant",
                    agent._current_action_outcome_summary,
                )
                agent._pending_phase_transition_next = (
                    "DESCRIBE_TRANSITION_BEARING latest :: "
                    "strand: continuity; "
                    "movement_resistance: active_within_restlessness; "
                    "persistence_tendency: dynamic_equilibrium; "
                    "witness_fit: holding; "
                    "source_ref: introspection:dynamic_persistence"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "movement_resistance=active_within_restlessness",
                    agent._current_action_outcome_summary,
                )
                agent._pending_phase_transition_next = (
                    "BIND_TRANSITION_ANCHOR latest :: role: pivot; "
                    "kind: shadow_trajectory; association: temporal_context; "
                    "anchor_ref: shadow-v3:minime:fixture; "
                    "source_ref: introspection:phase_anchor"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "kind=shadow_trajectory",
                    agent._current_action_outcome_summary,
                )
                agent._pending_phase_transition_next = (
                    "REQUEST_TRANSITION_COMPANY latest :: peer: astrid; "
                    "mode: low_energy_presence; source_ref: self:request"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "mode=low_energy_presence",
                    agent._current_action_outcome_summary,
                )

            ledger = shared / "phase_transitions_v1.jsonl"
            records = [
                json.loads(line) for line in ledger.read_text().splitlines()
            ]
            passage_rows = [
                row
                for row in records
                if row.get("record_type") == "phase_transition_passage"
            ]
            context_rows = [
                row
                for row in records
                if row.get("record_type")
                == "phase_transition_passage_context"
            ]
            self.assertEqual(len(passage_rows), 1)
            self.assertEqual(len(context_rows), 6)
            request_id = context_rows[-1]["company_request_id"]
            request_timestamp = context_rows[-1]["recorded_at_unix_ms"]
            self.assertTrue(
                all(row["passage_stage_changed"] is False for row in context_rows)
            )
            self.assertTrue(
                all(row["felt_score_present"] is False for row in context_rows)
            )
            self.assertTrue(
                all(row["live_control_effect"] is False for row in context_rows)
            )
            bearing_rows = [
                row
                for row in context_rows
                if row["action"] == "describe_bearing"
            ]
            self.assertEqual(len(bearing_rows), 2)
            self.assertTrue(
                all(row["bearing_is_metric"] is False for row in bearing_rows)
            )
            self.assertTrue(
                all(
                    row["bearing_inferred_from_telemetry"] is False
                    for row in bearing_rows
                )
            )
            self.assertTrue(
                all(row["bearing_changes_passage"] is False for row in bearing_rows)
            )
            self.assertTrue(
                all(row["bearing_closes_transition"] is False for row in bearing_rows)
            )
            anchor_rows = [
                row for row in context_rows if row["action"] == "bind_anchor"
            ]
            self.assertEqual(len(anchor_rows), 1)
            self.assertFalse(
                anchor_rows[0]["anchor_mechanical_truth_inferred"]
            )
            self.assertFalse(anchor_rows[0]["anchor_changes_passage"])
            self.assertFalse(anchor_rows[0]["anchor_closes_transition"])
            tampered = dict(context_rows[0])
            tampered["artifact_authority_state_v1"] = dict(
                tampered["artifact_authority_state_v1"]
            )
            tampered["artifact_authority_state_v1"]["state"] = "approved"
            with self.assertRaisesRegex(ValueError, "authority mismatch"):
                passage_context._validate_event(tampered)

            wrong_actor = append_context_action(
                ledger,
                request_id,
                "response: accept; source_ref: self:wrong",
                "minime",
                PassageContextAction.RESPOND_COMPANY,
                timestamp=request_timestamp,
            )
            self.assertIn("no matching inbound company request", wrong_actor)
            accepted = append_context_action(
                ledger,
                request_id,
                "response: accept; source_ref: self:available",
                "astrid",
                PassageContextAction.RESPOND_COMPANY,
                timestamp=request_timestamp,
            )
            self.assertIn("response=accept", accepted)

            with patch.object(aa.AutonomousAgent, "SHARED_COLLAB_DIR", shared):
                agent._pending_phase_transition_next = (
                    f"WITHDRAW_TRANSITION_COMPANY {request_id} :: "
                    "source_ref: self:withdraw"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "response=withdraw", agent._current_action_outcome_summary
                )
                agent._pending_phase_transition_next = (
                    "TRANSITION_PASSAGE_STATUS"
                )
                agent._phase_transition_action(dict(STATE))
                self.assertIn(
                    "silence is neutral",
                    agent._current_action_outcome_summary,
                )
                self.assertIn(
                    "not a viscosity metric",
                    agent._current_action_outcome_summary,
                )
                self.assertIn(
                    "owner-language alternatives to a stalled reading",
                    agent._current_action_outcome_summary,
                )
                self.assertIn(
                    "response=withdraw",
                    agent._current_action_outcome_summary,
                )


if __name__ == "__main__":
    unittest.main()
