import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.0}


class PhaseTransitionAgencyTests(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        agent.session_id = 1
        agent._pending_phase_transition_next = None
        agent._current_action_continuity_context = {}
        agent._current_action_outcome_summary = None
        return agent

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


if __name__ == "__main__":
    unittest.main()
