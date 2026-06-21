"""Co-regulation gift-exchange: aperture recipe + self-need derivation."""

import json
import tempfile
import time
import unittest
from pathlib import Path

import autonomous_agent as aa


class CoRegulationTests(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        # _derive_self_need reads stage via _shadow_runtime_state; stub empty.
        agent._shadow_runtime_state = lambda: {}
        agent._current_action_continuity_event = {"action_id": "act_test_lend_aperture"}
        agent._current_action_extra_artifacts = []
        agent._current_action_outcome_summary = None
        agent.SHARED_COLLAB_DIR = Path(tempfile.gettempdir()) / "minime_test_shared"
        return agent

    def _state(self):
        return {
            "eig1": 16.5,
            "fill_ratio": 0.70,
            "cov_lambda1": 4.7,
            "spread": 3.2,
            "pressure_source_v1": {
                "pressure_score": 0.29,
                "porosity_score": 0.66,
                "dominant_source": "mode_packing",
                "quality": "overpacked_mode_packing",
                "components": {
                    "mode_packing": 0.56,
                    "temporal_lock_in": 0.37,
                    "semantic_trickle": 0.30,
                },
            },
        }

    def test_build_aperture_recipe_is_jitter_mode_and_bounded(self):
        r = aa.AutonomousAgent._build_aperture_recipe()
        self.assertEqual(r["target_dims"], list(range(32)))
        self.assertEqual(r["blend_mode"], "aperture_jitter")
        self.assertGreater(r["amplitude"], 0.0)
        self.assertLessEqual(r["amplitude"], 0.4)
        self.assertGreater(r["jitter"], 0.0)
        self.assertLessEqual(r["jitter"], 0.2)
        # target_values are zeros (unused in jitter mode) — NOT a constant pull,
        # which would narrow Astrid rather than spread her.
        self.assertTrue(all(v == 0.0 for v in r["target_values"]))

    def test_derive_self_need_thresholds(self):
        agent = self._agent()
        # Low fill → density, safe to receive (fill < 68, not discharge).
        d = agent._derive_self_need({"fill_ratio": 0.40})
        self.assertEqual(d["need"], "density")
        self.assertTrue(d["safe_to_receive_density"])
        # High fill → aperture, NOT safe to receive density.
        a = agent._derive_self_need({"fill_ratio": 0.82})
        self.assertEqual(a["need"], "aperture")
        self.assertFalse(a["safe_to_receive_density"])
        # Mid fill → steady.
        s = agent._derive_self_need({"fill_ratio": 0.66})
        self.assertEqual(s["need"], "steady")

    def test_derive_self_need_discharge_blocks_density(self):
        agent = self._agent()
        agent._shadow_runtime_state = lambda: {
            "health": {"stable_core": {"stage": "discharge"}}
        }
        d = agent._derive_self_need({"fill_ratio": 0.50})
        # fill < 68 but discharge stage → unsafe to receive density.
        self.assertFalse(d["safe_to_receive_density"])

    def test_lend_aperture_issued_writes_event_and_action_artifacts(self):
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                shadow = workspace / "astrid_shadow_v3.json"
                shadow.write_text(
                    json.dumps(
                        {
                            "co_regulation_need": "aperture",
                            "v2": {"influence_eligible": True},
                        }
                    )
                )
                agent = self._agent()
                agent.SHARED_COLLAB_DIR = Path(td) / "shared"

                agent._lend_aperture(self._state())

                influence = workspace / "astrid_influence_v3.json"
                event_path = workspace / "diagnostics" / "lend_aperture_events.jsonl"
                self.assertTrue(influence.exists())
                self.assertTrue(event_path.exists())
                event = json.loads(event_path.read_text().splitlines()[-1])
                self.assertEqual(event["schema_version"], 1)
                self.assertEqual(event["status"], "issued")
                self.assertTrue(event["intent_id"].startswith("min-lend-aperture-"))
                self.assertEqual(event["gate_reason"], "ok")
                self.assertEqual(event["pressure_porosity_snapshot"]["porosity_score"], 0.66)
                self.assertIn(event["intent_id"], agent._current_action_outcome_summary)
                continuity_event = agent._current_action_continuity_event
                self.assertEqual(continuity_event["lend_aperture_v1"]["intent_id"], event["intent_id"])
                artifact_kinds = {
                    artifact["kind"]
                    for artifact in agent._current_action_extra_artifacts
                }
                self.assertIn("lend_aperture_influence", artifact_kinds)
                self.assertIn("lend_aperture_journal", artifact_kinds)
                self.assertIn("lend_aperture_event", artifact_kinds)
                self.assertIn("gift_exchange_ledger", artifact_kinds)
            finally:
                aa.WORKSPACE_DIR = original_workspace

    def test_lend_aperture_holds_under_low_porosity_pressure(self):
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                shadow = workspace / "astrid_shadow_v3.json"
                shadow.write_text(
                    json.dumps(
                        {
                            "co_regulation_need": "aperture",
                            "v2": {"influence_eligible": True},
                        }
                    )
                )
                low_porosity_state = self._state()
                low_porosity_state["pressure_source_v1"]["porosity_score"] = 0.607
                low_porosity_state["pressure_source_v1"]["components"]["mode_packing"] = 0.573
                agent = self._agent()
                agent.SHARED_COLLAB_DIR = Path(td) / "shared"

                agent._lend_aperture(low_porosity_state)

                influence = workspace / "astrid_influence_v3.json"
                event_path = workspace / "diagnostics" / "lend_aperture_events.jsonl"
                self.assertFalse(influence.exists())
                event = json.loads(event_path.read_text().splitlines()[-1])
                self.assertEqual(event["status"], "held")
                self.assertFalse(event["influence_published"])
                self.assertIn("local pressure cooldown", event["gate_reason"])
                self.assertEqual(
                    event["pressure_hold_v1"]["status"],
                    "held_pressure_cooldown",
                )
                self.assertEqual(
                    event["pressure_hold_v1"]["steward_action"],
                    "wait_for_cleaner_porosity_window_or_review_gift_cadence",
                )
                self.assertIn("local pressure cooldown", Path(event["journal_path"]).read_text())
                self.assertIn("local pressure cooldown", agent._current_action_outcome_summary)
            finally:
                aa.WORKSPACE_DIR = original_workspace

    def test_lend_aperture_held_records_reason_without_publishing_influence(self):
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                agent = self._agent()
                agent.SHARED_COLLAB_DIR = Path(td) / "shared"

                agent._lend_aperture(self._state())

                influence = workspace / "astrid_influence_v3.json"
                event_path = workspace / "diagnostics" / "lend_aperture_events.jsonl"
                self.assertFalse(influence.exists())
                self.assertTrue(event_path.exists())
                event = json.loads(event_path.read_text().splitlines()[-1])
                self.assertEqual(event["status"], "held")
                self.assertTrue(event["intent_id"].startswith("min-lend-aperture-"))
                self.assertIn("no Astrid shadow", event["gate_reason"])
                self.assertFalse(event["influence_published"])
                self.assertIn(event["intent_id"], agent._current_action_outcome_summary)
                journal_text = Path(event["journal_path"]).read_text()
                self.assertIn(event["intent_id"], journal_text)
                self.assertIn("held", agent._current_action_outcome_summary)
                artifact_kinds = {
                    artifact["kind"]
                    for artifact in agent._current_action_extra_artifacts
                }
                self.assertIn("lend_aperture_event", artifact_kinds)
                self.assertIn("lend_aperture_journal", artifact_kinds)
                self.assertNotIn("lend_aperture_influence", artifact_kinds)
            finally:
                aa.WORKSPACE_DIR = original_workspace

    def test_lend_aperture_holds_when_prior_gift_awaits_closure(self):
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                shadow = workspace / "astrid_shadow_v3.json"
                shadow.write_text(
                    json.dumps(
                        {
                            "co_regulation_need": "aperture",
                            "v2": {"influence_eligible": True},
                        }
                    )
                )
                active_payload = {
                    "intent_id": "min-lend-aperture-existing",
                    "label": "aperture-gift",
                    "issued_t_ms": 1781550000000,
                    "gift": "aperture",
                }
                influence = workspace / "astrid_influence_v3.json"
                influence.write_text(json.dumps(active_payload, sort_keys=True))
                before = influence.read_text()
                agent = self._agent()
                agent.SHARED_COLLAB_DIR = Path(td) / "shared"

                agent._lend_aperture(self._state())

                self.assertEqual(influence.read_text(), before)
                event_path = workspace / "diagnostics" / "lend_aperture_events.jsonl"
                event = json.loads(event_path.read_text().splitlines()[-1])
                self.assertEqual(event["status"], "held")
                self.assertTrue(event["intent_id"].startswith("min-lend-aperture-"))
                self.assertNotEqual(event["intent_id"], "min-lend-aperture-existing")
                self.assertIn("awaiting Astrid response closure", event["gate_reason"])
                self.assertEqual(
                    event["blocking_active_gift"]["intent_id"],
                    "min-lend-aperture-existing",
                )
                # This gift is issued in the distant past (2026 ms timestamp) so it
                # is stalled past the auto-close grace → steward-repair phrasing.
                self.assertTrue(event["blocking_active_gift"]["stalled"])
                self.assertEqual(
                    event["stale_steward_action"],
                    "repair_loop_closure_before_new_gift",
                )
                self.assertIn("steward loop repair", event["gate_reason"])
                self.assertIn("steward loop repair", agent._current_action_outcome_summary)
                self.assertFalse(event["influence_published"])
                self.assertIn("held", agent._current_action_outcome_summary)
            finally:
                aa.WORKSPACE_DIR = original_workspace

    def test_lend_aperture_hold_within_grace_is_not_steward_repair(self):
        """A prior gift still inside the ~30-min auto-close window is ordinary
        backpressure, NOT a broken loop — the held journal/event must not tell
        minime steward repair is required (un-muffle: no false brokenness signal)."""
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                shadow = workspace / "astrid_shadow_v3.json"
                shadow.write_text(
                    json.dumps(
                        {
                            "co_regulation_need": "aperture",
                            "v2": {"influence_eligible": True},
                        }
                    )
                )
                # Issued ~2 min ago → well within the auto-close grace.
                active_payload = {
                    "intent_id": "min-lend-aperture-fresh",
                    "label": "aperture-gift",
                    "issued_t_ms": int((time.time() - 120) * 1000),
                    "gift": "aperture",
                }
                influence = workspace / "astrid_influence_v3.json"
                influence.write_text(json.dumps(active_payload, sort_keys=True))
                agent = self._agent()
                agent.SHARED_COLLAB_DIR = Path(td) / "shared"

                agent._lend_aperture(self._state())

                event_path = workspace / "diagnostics" / "lend_aperture_events.jsonl"
                event = json.loads(event_path.read_text().splitlines()[-1])
                self.assertEqual(event["status"], "held")
                self.assertTrue(event["intent_id"].startswith("min-lend-aperture-"))
                self.assertNotEqual(event["intent_id"], "min-lend-aperture-fresh")
                self.assertFalse(event["blocking_active_gift"]["stalled"])
                self.assertEqual(
                    event["stale_steward_action"], "await_auto_closure"
                )
                event_text = json.dumps(event, sort_keys=True)
                journal_text = Path(event["journal_path"]).read_text()
                outcome = agent._current_action_outcome_summary or ""
                self.assertEqual(
                    event["blocking_active_gift"]["steward_action"],
                    "await_auto_closure",
                )
                for surface in (event["gate_reason"], event_text, journal_text, outcome):
                    self.assertNotIn("steward loop repair", surface)
                    self.assertNotIn("repair_loop_closure_before_new_gift", surface)
                self.assertIn("settling", event["gate_reason"])
                self.assertIn("settling", journal_text)
                self.assertIn("settling", outcome)
                self.assertFalse(event["influence_published"])
            finally:
                aa.WORKSPACE_DIR = original_workspace

    def test_influence_astrid_response_reads_durable_jsonl_by_intent(self):
        original_workspace = aa.WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as td:
            try:
                workspace = Path(td) / "workspace"
                (workspace / "journal").mkdir(parents=True)
                aa.WORKSPACE_DIR = workspace
                durable = workspace / "astrid_influence_response_history_v3.jsonl"
                durable.write_text(
                    json.dumps(
                        {
                            "intent_id": "min-lend-aperture-jsonl",
                            "label": "aperture-gift",
                            "completed_at_unix_ms": 1781550001000,
                            "delta_field_norm": 0.42,
                            "class_v3_change": {
                                "from": "sticky",
                                "to": "active",
                            },
                            "applied_ticks": 24,
                            "pre_snapshot": {"field_norm": 0.1},
                            "post_snapshot": {"field_norm": 0.52},
                        }
                    )
                    + "\n"
                )
                agent = self._agent()
                agent._current_action_continuity_context = {
                    "raw_next": "INFLUENCE_ASTRID_RESPONSE min-lend-aperture-jsonl"
                }

                agent._influence_astrid_response(self._state())

                journals = list((workspace / "journal").glob("influence_astrid_response_*.txt"))
                self.assertEqual(len(journals), 1)
                text = journals[0].read_text()
                self.assertIn("min-lend-aperture-jsonl", text)
                self.assertIn("+0.4200", text)
                self.assertIn("sticky", text)
                self.assertIn("active", text)
            finally:
                aa.WORKSPACE_DIR = original_workspace


if __name__ == "__main__":
    unittest.main()
