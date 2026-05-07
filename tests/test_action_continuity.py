"""Tests for file-first action continuity."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


STATE = {
    "eig1": 4.7,
    "deig": 0.01,
    "fill_ratio": 0.68,
    "spread": 3,
    "cov_lambda1": 8.0,
    "geom_rel": 1.0,
    "resonance_density_v1": {
        "policy": "resonance_density_v1",
        "schema_version": 1,
        "density": 0.66,
        "containment_score": 0.61,
        "pressure_risk": 0.18,
        "quality": "rich_containment",
        "components": {
            "active_energy": 0.9,
            "mode_packing": 0.7,
            "temporal_persistence": 0.8,
            "structural_plurality": 0.7,
            "comfort_gate": 1.0,
        },
        "control": {
            "target_bias_pct": 0.0,
            "wander_scale": 1.0,
            "applied_locally": True,
            "note": "test",
        },
    },
}


class TestActionContinuityStore(unittest.TestCase):
    def test_store_creates_thread_event_observation_artifact_and_db_mirrors(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            store = aa.ActionContinuityStore(workspace, db_path=db_path, session_id=7)
            thread = store.create_thread("Spectral Entropy Map")
            event = store.begin_action(
                "SEARCH spectral entropy",
                "SEARCH spectral entropy",
                "research_exploration",
                "research_exploration",
                STATE,
            )
            artifact = {
                "schema_version": 1,
                "artifact_id": f"art_{event['action_id']}_manifest",
                "action_id": event["action_id"],
                "kind": "action_manifest",
                "path_or_uri": str(workspace / "actions" / "manifest.json"),
                "summary": "manifest",
                "visibility": "summary",
            }
            finished = store.finish_action(
                event,
                "handled",
                "Executed search",
                STATE,
                artifacts=[artifact],
            )

            thread_dir = workspace / "action_threads" / "threads" / thread["thread_id"]
            self.assertTrue((thread_dir / "thread.json").exists())
            self.assertIn(finished["action_id"], (thread_dir / "events.jsonl").read_text())
            observations_text = (thread_dir / "observations.jsonl").read_text()
            self.assertIn(finished["action_id"], observations_text)
            observation = json.loads(observations_text.strip().splitlines()[-1])
            self.assertEqual(observation["resonance_density_v1"]["quality"], "rich_containment")
            self.assertEqual(observation["thread_resonance"]["quality"], "open_experiment")
            self.assertIn(artifact["artifact_id"], (thread_dir / "artifacts.jsonl").read_text())

            conn = sqlite3.connect(db_path)
            try:
                event_count = conn.execute("SELECT COUNT(*) FROM action_events").fetchone()[0]
                observation_count = conn.execute("SELECT COUNT(*) FROM observation_windows").fetchone()[0]
                artifact_count = conn.execute("SELECT COUNT(*) FROM artifact_links").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(event_count, 1)
            self.assertEqual(observation_count, 1)
            self.assertEqual(artifact_count, 1)

            stored_thread = json.loads((thread_dir / "thread.json").read_text())
            self.assertIn("thread_resonance_density_v1", stored_thread)

    def test_protected_actions_are_summary_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = aa.ActionContinuityStore(Path(tmp) / "workspace", session_id=8)
            event = store.begin_action("SPACE_HOLD eigenplane", "SPACE_HOLD eigenplane", "space_hold", "space_hold", STATE)
            self.assertEqual(event["visibility"], "protected_summary")
            self.assertEqual(event["stage"], "read_only")


class TestAutonomousAgentActionContinuity(unittest.TestCase):
    def _agent(self, workspace: Path, db_path: Path) -> aa.AutonomousAgent:
        with patch.object(aa, "WORKSPACE_DIR", workspace), patch.object(aa, "DB_PATH", db_path):
            return aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)

    def test_pending_next_context_survives_decide_into_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            agent = self._agent(workspace, db_path)
            agent._pending_next_action = "NOTICE"
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                action = agent._decide_action(dict(STATE))
            self.assertEqual(action, "recess_notice")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_stable_core_action_allowed", return_value=(True, "test")),
                patch.object(agent, "_recess_notice"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            manifests = list((workspace / "actions").glob("*_recess_notice.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(manifest["action_continuity"]["raw_next"], "NOTICE")
            self.assertEqual(manifest["action_continuity"]["thread_id"], agent._last_action_continuity_event["thread_id"])

    def test_unknown_next_becomes_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            agent = self._agent(workspace, db_path)
            agent._pending_next_action = "INVENT_NEW_SURFACE lambda"
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_persist_pending_next_action"),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
            ):
                agent._decide_action(dict(STATE))
            proposals = workspace / "action_threads" / "proposals.jsonl"
            self.assertIn("INVENT_NEW_SURFACE", proposals.read_text())

    def test_latest_spectral_state_includes_resonance_density(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("""
                    CREATE TABLE esn_metrics (
                        session_id INTEGER,
                        timestamp REAL,
                        esn_eig1 REAL,
                        esn_deig REAL,
                        esn_leak REAL,
                        esn_lambda REAL,
                        esn_baseline REAL,
                        esn_geom_radius REAL,
                        esn_geom_rel REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE eigenvalue_timeline (
                        session_id INTEGER,
                        timestamp REAL,
                        lambda1 REAL,
                        lambda2 REAL,
                        lambda3 REAL,
                        fill_ratio REAL,
                        spread REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE resonance_density_timeline (
                        session_id INTEGER,
                        timestamp REAL,
                        payload TEXT
                    )
                """)
                conn.execute("INSERT INTO esn_metrics VALUES (1, 10.0, 4.7, 0.01, 0.2, 0.99, 4.5, 1.2, 1.0)")
                conn.execute("INSERT INTO eigenvalue_timeline VALUES (1, 10.0, 8.0, 3.0, 2.0, 0.68, 6.0)")
                conn.execute(
                    "INSERT INTO resonance_density_timeline VALUES (1, 10.0, ?)",
                    (json.dumps(STATE["resonance_density_v1"]),),
                )
                conn.commit()
            finally:
                conn.close()

            agent = self._agent(workspace, db_path)
            with patch.object(aa, "DB_PATH", db_path):
                state = agent._get_latest_spectral_state()
            self.assertIsNotNone(state)
            self.assertEqual(state["resonance_quality"], "rich_containment")
            self.assertAlmostEqual(state["resonance_density"], 0.66)


if __name__ == "__main__":
    unittest.main()
