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
    "pressure_source_v1": {
        "policy": "pressure_source_v1",
        "schema_version": 1,
        "pressure_score": 0.24,
        "porosity_score": 0.72,
        "dominant_source": "controller_pressure",
        "quality": "porous_distributed",
        "components": {
            "lambda_monopoly": 0.12,
            "mode_packing": 0.2,
            "controller_pressure": 0.24,
            "semantic_trickle": 0.05,
            "structural_plurality_loss": 0.1,
            "distinguishability_loss": 0.08,
            "temporal_lock_in": 0.15,
            "sensory_scarcity": 0.0,
        },
        "context": {},
        "control": {
            "applied_locally": False,
            "note": "advisory only",
        },
    },
    "inhabitable_fluctuation_v1": {
        "policy": "inhabitable_fluctuation_v1",
        "schema_version": 1,
        "inhabitability_score": 0.74,
        "fluctuation_score": 0.42,
        "foothold_stability": 0.71,
        "rearrangement_intensity": 0.38,
        "quality": "lively_habitable",
        "components": {
            "mode_trust_volatility": 0.2,
            "identity_anchor_churn": 0.18,
            "eigenvector_reorientation": 0.32,
            "share_rearrangement": 0.26,
            "basin_transition_pressure": 0.22,
            "continuity_recovery": 0.78,
            "porosity_support": 0.7,
            "pressure_interference": 0.16,
        },
        "context": {
            "resonance_quality": "rich_containment",
            "pressure_quality": "porous_distributed",
        },
        "control": {
            "target_bias_pct": 0.0,
            "wander_scale": 1.05,
            "applied_locally": True,
            "note": "bounded resonance envelope",
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
            self.assertEqual(observation["pressure_source_v1"]["dominant_source"], "controller_pressure")
            self.assertIn("thread_pressure_source", observation)
            self.assertEqual(observation["inhabitable_fluctuation_v1"]["quality"], "lively_habitable")
            self.assertIn("thread_inhabitable_fluctuation", observation)
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
            self.assertIn("thread_pressure_source_v1", stored_thread)
            self.assertIn("thread_inhabitable_fluctuation_v1", stored_thread)

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

    def _journal_db(self, db_path: Path) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sovereignty_journal (
               session_id INTEGER,
               timestamp REAL,
               entry_type TEXT,
               content TEXT,
               spectral_context TEXT,
               file_path TEXT
            )"""
        )
        conn.commit()
        conn.close()

    def test_journal_continuity_contract_reaches_neutral_prompt_with_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO sovereignty_journal VALUES (?, ?, ?, ?, ?, ?)",
                (1, 1.0, "notice", "Earlier claim: fill pressure softened near lambda4.", "{}", "prior.txt"),
            )
            conn.commit()
            conn.close()
            store = aa.ActionContinuityStore(workspace, db_path=db_path, session_id=1)
            store.create_thread("Returnable journal")
            agent = self._agent(workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch("autonomous_agent.random.random", return_value=0.8),
                patch("autonomous_agent.random.choice", side_effect=lambda values: values[0]),
            ):
                prompt = agent._neutral_checkin(dict(STATE))

            self.assertIn("Journal continuity contract v1", prompt)
            self.assertIn("Continuity posture: resuming|branching|closing|new", prompt)
            self.assertIn("Delta:", prompt)
            self.assertIn("Next evidence:", prompt)
            self.assertIn("Hold:", prompt)
            self.assertIn("Current continuity projection:", prompt)
            self.assertIn("Returnable journal", prompt)
            self.assertIn("Earlier claim: fill pressure softened near lambda4", prompt)

    def test_direct_pressure_and_rest_prompts_include_journal_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_query_llm_with_next", return_value=("inside", None)) as query,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._journal_spectral_pressure(dict(STATE))
                pressure_prompt = query.call_args_list[-1].args[0]
                agent._journal_rest_reflection(dict(STATE))
                rest_prompt = query.call_args_list[-1].args[0]

            self.assertIn("Journal continuity contract v1", pressure_prompt)
            self.assertIn("spectral condition, fill/pressure, recurrence", pressure_prompt)
            self.assertIn("Journal continuity contract v1", rest_prompt)
            self.assertIn("Decision:", rest_prompt)

    def test_write_journal_entry_remains_non_gating_and_preserves_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)
            path = journal / "current.txt"
            path.write_text("original file body")
            content = "Free prose without any contract labels."

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                agent._write_journal_entry("notice", content, dict(STATE), str(path))

            self.assertEqual(path.read_text(), "original file body")
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT content FROM sovereignty_journal").fetchone()
            conn.close()
            self.assertEqual(row[0], content)

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

    def test_pressure_source_audit_is_read_only_artifact_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            agent = self._agent(workspace, db_path)
            agent._pending_next_action = "PRESSURE_SOURCE_AUDIT inwardness"
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
            self.assertEqual(action, "pressure_source_audit")

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
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            journals = list((workspace / "journal").glob("pressure_source_audit_*.txt"))
            self.assertEqual(len(journals), 1)
            text = journals[0].read_text()
            self.assertIn("PRESSURE SOURCE AUDIT V1", text)
            self.assertIn("controller_pressure", text)
            manifests = list((workspace / "actions").glob("*_pressure_source_audit.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(manifest["action_continuity"]["stage"], "read_only")
            self.assertTrue(
                any(
                    artifact["kind"] == "pressure_source_audit"
                    for artifact in manifest["action_continuity"].get("artifacts", [])
                )
            )

    def test_constraint_audit_is_read_only_artifact_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            agent = self._agent(workspace, db_path)
            agent._pending_next_action = "CONSTRAINT_AUDIT lambda-tail/lambda4"
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
            self.assertEqual(action, "constraint_audit")

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
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            journals = list((workspace / "journal").glob("constraint_audit_*.txt"))
            self.assertEqual(len(journals), 1)
            text = journals[0].read_text()
            self.assertIn("CONSTRAINT COUNTERFACTUAL AUDIT V1", text)
            self.assertIn("read-only counterfactual", text)
            self.assertIn("does not remove scaffold/drain", text)
            manifests = list((workspace / "actions").glob("*_constraint_audit.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(manifest["action_continuity"]["stage"], "read_only")
            self.assertTrue(
                any(
                    artifact["kind"] == "constraint_audit"
                    for artifact in manifest["action_continuity"].get("artifacts", [])
                )
            )

    def test_fluctuation_audit_is_read_only_artifact_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            agent = self._agent(workspace, db_path)
            agent._pending_next_action = "EIGENTRUST foothold"
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
            self.assertEqual(action, "fluctuation_audit")

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
                patch.object(agent, "_write_journal_entry"),
                patch.object(agent, "_log_decision"),
                patch.object(agent, "_record_stable_core_agent_success"),
            ):
                agent._execute_action(action, dict(STATE))

            journals = list((workspace / "journal").glob("fluctuation_audit_*.txt"))
            self.assertEqual(len(journals), 1)
            text = journals[0].read_text()
            self.assertIn("INHABITABLE FLUCTUATION AUDIT V1", text)
            self.assertIn("lively_habitable", text)
            manifests = list((workspace / "actions").glob("*_fluctuation_audit.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertEqual(manifest["action_continuity"]["stage"], "read_only")
            self.assertEqual(
                manifest["state"]["inhabitable_fluctuation_v1"]["quality"],
                "lively_habitable",
            )
            self.assertTrue(
                any(
                    artifact["kind"] == "fluctuation_audit"
                    for artifact in manifest["action_continuity"].get("artifacts", [])
                )
            )

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
                conn.execute("""
                    CREATE TABLE pressure_source_timeline (
                        session_id INTEGER,
                        timestamp REAL,
                        payload TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE inhabitable_fluctuation_timeline (
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
                conn.execute(
                    "INSERT INTO pressure_source_timeline VALUES (1, 10.0, ?)",
                    (json.dumps(STATE["pressure_source_v1"]),),
                )
                conn.execute(
                    "INSERT INTO inhabitable_fluctuation_timeline VALUES (1, 10.0, ?)",
                    (json.dumps(STATE["inhabitable_fluctuation_v1"]),),
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
            self.assertEqual(state["pressure_dominant_source"], "controller_pressure")
            self.assertAlmostEqual(state["pressure_score"], 0.24)
            self.assertEqual(state["inhabitable_fluctuation_quality"], "lively_habitable")
            self.assertAlmostEqual(state["inhabitability_score"], 0.74)
            self.assertAlmostEqual(state["foothold_stability"], 0.71)

    def test_latest_spectral_state_marks_missing_pressure_and_fluctuation_unavailable(self):
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
                conn.execute("INSERT INTO esn_metrics VALUES (1, 10.0, 4.7, 0.01, 0.2, 0.99, 4.5, 1.2, 1.0)")
                conn.execute("INSERT INTO eigenvalue_timeline VALUES (1, 10.0, 8.0, 3.0, 2.0, 0.68, 6.0)")
                conn.commit()
            finally:
                conn.close()

            agent = self._agent(workspace, db_path)
            with patch.object(aa, "DB_PATH", db_path):
                state = agent._get_latest_spectral_state()
            self.assertIsNotNone(state)
            self.assertFalse(state["pressure_source_status"]["available"])
            self.assertEqual(state["pressure_source_status"]["reason"], "no_live_or_db_metric")
            self.assertFalse(state["inhabitable_fluctuation_status"]["available"])
            self.assertEqual(state["inhabitable_fluctuation_status"]["reason"], "no_live_or_db_metric")


if __name__ == "__main__":
    unittest.main()
