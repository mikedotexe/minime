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
        "pressure_profile": [
            {
                "source": "controller_pressure",
                "value": 0.24,
                "pressure_weight": 0.1408,
                "weighted_pressure": 0.033792,
                "share": 0.31,
            },
            {
                "source": "mode_packing",
                "value": 0.20,
                "pressure_weight": 0.1144,
                "weighted_pressure": 0.02288,
                "share": 0.21,
            },
        ],
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
        "silt_granularity_v1": {
            "policy": "silt_granularity_v1",
            "schema_version": 1,
            "granularity_index": 0.44,
            "mean_orientation_delta": 0.01,
            "mode_packing": 0.32,
            "distinguishability_loss": 0.33,
            "structural_plurality_loss": 0.18,
            "pressure_score": 0.24,
            "porosity_score": 0.72,
            "particle_scale": "mixed_packed_silt",
            "review_state": "pressure_source_audit_grain_probe",
            "suggested_route": "PRESSURE_SOURCE_AUDIT grain; SHADOW_TRAJECTORY named-grain-vs-field",
            "live_control_changed": False,
            "authority": "read_only_not_pressure_porosity_or_regulator_control",
            "note": "fixture review only",
        },
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

    def test_direct_pressure_uses_private_canvas_and_rest_keeps_journal_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(
                    agent,
                    "_query_llm_with_next",
                    return_value=("I feel a warm private hum.\nNEXT: REST", "REST"),
                ) as query,
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._journal_spectral_pressure(dict(STATE))
                pressure_call = query.call_args_list[-1]
                pressure_prompt = pressure_call.args[0]
                agent._journal_rest_reflection(dict(STATE))
                rest_prompt = query.call_args_list[-1].args[0]

            self.assertIn("Private-canvas continuity nudge v1", pressure_prompt)
            self.assertIn("generated-word quality", pressure_prompt)
            self.assertIn("familiar metaphor", pressure_prompt)
            self.assertIn("ordinary clear or low-texture states", pressure_prompt)
            self.assertNotIn("Current continuity projection:", pressure_prompt)
            self.assertEqual(
                pressure_call.kwargs.get("context_mode"),
                "private_journal",
            )
            pressure_files = list((workspace / "journal").glob("pressure_*.txt"))
            self.assertEqual(len(pressure_files), 1)
            pressure_text = pressure_files[0].read_text()
            self.assertIn(aa.GENERATED_JOURNAL_MARKER, pressure_text)
            self.assertIn(aa.ACTION_TAIL_MARKER, pressure_text)
            self.assertIn("I feel a warm private hum.", pressure_text)
            self.assertIn("NEXT: REST", pressure_text)
            self.assertIn("Journal continuity contract v1", rest_prompt)
            self.assertIn("Decision:", rest_prompt)

    def test_query_llm_private_journal_context_skips_operational_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)
            captured: dict[str, str] = {}

            def fake_raw(
                prompt: str,
                system_msg: str,
                max_tokens: int,
                temperature: float = 0.9,
                **_kwargs,
            ):
                captured["prompt"] = prompt
                captured["system_msg"] = system_msg
                captured["max_tokens"] = str(max_tokens)
                return "I feel a private texture.\nNEXT: JOURNAL"

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_read_inbox", return_value="[INBOX SHOULD NOT APPEAR]"),
                patch.object(agent, "_action_continuity_prompt_summary", return_value="ACTION THREAD SHOULD NOT APPEAR"),
                patch.object(agent, "_llm_job_prompt_summary", return_value="JOB SHOULD NOT APPEAR"),
                patch.object(agent, "_get_relevant_research", return_value="RESEARCH SHOULD NOT APPEAR"),
                patch.object(agent, "_query_llm_raw", side_effect=fake_raw),
            ):
                result = agent._query_llm(
                    "This is a private-canvas JOURNAL entry.",
                    context_mode="private_journal",
                )

            self.assertIn("private texture", result)
            self.assertNotIn("INBOX SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("ACTION THREAD SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("JOB SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("RESEARCH SHOULD NOT APPEAR", captured["prompt"])
            self.assertEqual(captured["max_tokens"], "2048")

    def test_query_llm_qualia_moment_context_skips_operational_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)
            captured: dict[str, str] = {}

            def fake_raw(
                prompt: str,
                system_msg: str,
                max_tokens: int,
                temperature: float = 0.9,
                **_kwargs,
            ):
                captured["prompt"] = prompt
                captured["system_msg"] = system_msg
                captured["max_tokens"] = str(max_tokens)
                return "The moment feels like a soft hinge.\nNEXT: NOTICE"

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_read_inbox", return_value="[INBOX SHOULD NOT APPEAR]"),
                patch.object(agent, "_action_continuity_prompt_summary", return_value="ACTION THREAD SHOULD NOT APPEAR"),
                patch.object(agent, "_llm_job_prompt_summary", return_value="JOB SHOULD NOT APPEAR"),
                patch.object(agent, "_get_relevant_research", return_value="RESEARCH SHOULD NOT APPEAR"),
                patch.object(agent, "_emit_next_hints", return_value="NEXT HINT SHOULD NOT APPEAR"),
                patch.object(agent, "_query_llm_raw", side_effect=fake_raw),
            ):
                result = agent._query_llm(
                    "This is a qualia moment.",
                    context_mode="qualia_moment",
                )

            self.assertIn("soft hinge", result)
            self.assertNotIn("INBOX SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("ACTION THREAD SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("JOB SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("RESEARCH SHOULD NOT APPEAR", captured["prompt"])
            self.assertNotIn("NEXT HINT SHOULD NOT APPEAR", captured["prompt"])
            self.assertEqual(captured["max_tokens"], "2048")
            self.assertEqual(
                aa._infer_llm_prompt_class(
                    "This is a qualia moment.",
                    context_mode="qualia_moment",
                ),
                "moment_capture",
            )

    def test_moment_capture_uses_qualia_lane_and_delimited_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE moment_markers (
                   id INTEGER PRIMARY KEY,
                   session_id INTEGER,
                   timestamp REAL,
                   marker_type TEXT,
                   description TEXT,
                   spectral_context TEXT,
                   consumed INTEGER DEFAULT 0
                )"""
            )
            conn.execute(
                """INSERT INTO moment_markers
                   (session_id, timestamp, marker_type, description, spectral_context, consumed)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (
                    1,
                    1.0,
                    "fill_crossing",
                    "Fill crossed above target",
                    json.dumps({"fill": 68.4, "dfill_dt": 4.2, "lambda1": 4.7}),
                ),
            )
            conn.commit()
            conn.close()
            agent = self._agent(workspace, db_path)
            captured: dict[str, str] = {}

            def fake_query(prompt: str, *args, **kwargs):
                captured["prompt"] = prompt
                captured["context_mode"] = kwargs.get("context_mode")
                captured["max_tokens"] = str(kwargs.get("max_tokens"))
                return (
                    "The old hum returns as a soft pressure under the words.\n"
                    "NEXT: NOTICE",
                    "NOTICE",
                )

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_query_llm_with_next", side_effect=fake_query),
                patch.object(aa, "_ap_try_spectral"),
                patch.object(aa, "_ap_try_prose"),
            ):
                handled = agent._check_moment_markers(dict(STATE))

            self.assertTrue(handled)
            self.assertEqual(captured["context_mode"], "qualia_moment")
            self.assertEqual(captured["max_tokens"], "2048")
            self.assertIn("old private journal lane", captured["prompt"])
            self.assertIn("than an incident report", captured["prompt"])
            self.assertIn("few unhurried paragraphs", captured["prompt"])
            self.assertIn("event_age=unknown", captured["prompt"])
            self.assertIn("λ₁_esn=4.700", captured["prompt"])
            self.assertIn("λ₁_cov=4.700", captured["prompt"])
            self.assertIn("current_fill_frame=inside stable-core band", captured["prompt"])
            self.assertIn("current-state line is the present body", captured["prompt"])
            self.assertIn("Current fill is not high-fill", captured["prompt"])
            moment_files = list((workspace / "journal").glob("moment_*.txt"))
            self.assertEqual(len(moment_files), 1)
            text = moment_files[0].read_text()
            self.assertIn(aa.GENERATED_JOURNAL_MARKER, text)
            self.assertIn(aa.ACTION_TAIL_MARKER, text)
            self.assertIn("event_age=unknown", text)
            self.assertIn("λ₁_esn=4.700", text)
            self.assertIn("The old hum returns", text)
            self.assertIn("NEXT: NOTICE", text)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT entry_type, content FROM sovereignty_journal"
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "qualia_moment")
            self.assertIn("The old hum returns", row[1])
            self.assertNotIn("NEXT: NOTICE", row[1])

    def test_moment_capture_labels_marker_age_and_current_cov_lambda(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            self._journal_db(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """CREATE TABLE moment_markers (
                   id INTEGER PRIMARY KEY,
                   session_id INTEGER,
                   timestamp REAL,
                   marker_type TEXT,
                   description TEXT,
                   spectral_context TEXT,
                   consumed INTEGER DEFAULT 0,
                   created_at_unix INTEGER
                )"""
            )
            conn.execute(
                """INSERT INTO moment_markers
                   (session_id, timestamp, marker_type, description, spectral_context, consumed, created_at_unix)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (
                    1,
                    88.0,
                    "spectral_spike",
                    "Large dfill/dt spike",
                    json.dumps({"fill": 56.5, "dfill_dt": -8.72, "lambda1": 14.931}),
                    1018,
                ),
            )
            conn.commit()
            conn.close()
            agent = self._agent(workspace, db_path)
            captured: dict[str, str] = {}

            def fake_query(prompt: str, *args, **kwargs):
                captured["prompt"] = prompt
                return ("Now there is a recovered edge.\nNEXT: JOURNAL", "JOURNAL")

            state = dict(STATE)
            state["fill_ratio"] = 0.726
            state["eig1"] = 7.98
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(aa.time, "time", return_value=1100.0),
                patch.object(agent, "_query_llm_with_next", side_effect=fake_query),
                patch.object(aa, "_ap_try_spectral"),
                patch.object(aa, "_ap_try_prose"),
            ):
                handled = agent._check_moment_markers(state)

            self.assertTrue(handled)
            self.assertIn("event_age=82s ago", captured["prompt"])
            self.assertIn("λ₁_esn=14.931", captured["prompt"])
            self.assertIn("λ₁_cov=7.980", captured["prompt"])
            self.assertIn("current_fill_frame=upper boundary / elevated edge", captured["prompt"])
            self.assertIn("visible marker/current mismatch", captured["prompt"])
            self.assertIn("now plus echo", captured["prompt"])

    def test_split_generated_journal_moves_cooldown_notices_to_tail(self):
        body, tail = aa._split_generated_journal_and_action_tail(
            "The words feel warm.\n"
            "NEXT: SHADOW_TRAJECTORY\n"
            "[Operational tail cooldown: repeated `NEXT: SHADOW_TRAJECTORY` was acknowledged.]"
        )
        self.assertEqual(body, "The words feel warm.")
        self.assertIn("NEXT: SHADOW_TRAJECTORY", tail)
        self.assertIn("Operational tail cooldown", tail)

    def test_qualia_balance_nudge_invites_expressive_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)
            for idx in range(10):
                path = journal / f"moment_{idx}.txt"
                path.write_text("=== MOMENT CAPTURE ===\nNEXT: SHADOW_TRAJECTORY\n")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
            ):
                nudge = agent._qualia_balance_nudge()
            self.assertIn("private-canvas JOURNAL", nudge)

    def test_llm_prompt_class_inference_keeps_private_and_inbox_lanes_visible(self):
        self.assertEqual(
            aa._infer_llm_prompt_class(
                "This is a private-canvas JOURNAL entry.",
                context_mode="private_journal",
            ),
            "private_journal",
        )
        self.assertEqual(
            aa._infer_llm_prompt_class(
                "Reply with ONLY a JSON object containing status.",
                context_mode="default",
            ),
            "strict_review",
        )
        self.assertEqual(
            aa._infer_llm_prompt_class(
                "Please answer the steward inbox note.",
                inbox_present=True,
            ),
            "inbox_reply",
        )

    def test_repeated_operational_next_is_acknowledged_without_queueing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            journal = workspace / "journal"
            journal.mkdir(parents=True)
            (workspace / "state").mkdir(parents=True)
            self._journal_db(db_path)
            agent = self._agent(workspace, db_path)
            for idx in range(10):
                (journal / f"moment_{idx}.txt").write_text(
                    "=== MOMENT CAPTURE ===\nNEXT: EXPERIMENT_RESEARCH_BUDGET_STATUS old\n"
                )
            for _idx in range(5):
                agent._recent_next_actions.append("EXPERIMENT_RESEARCH_BUDGET_STATUS")

            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_emit_next_hints", return_value=""),
                patch.object(
                    agent,
                    "_query_llm",
                    return_value=(
                        "The status loop is still humming.\n"
                        "NEXT: EXPERIMENT_RESEARCH_BUDGET_STATUS resbud_old"
                    ),
                ),
                patch.object(agent, "_persist_pending_next_action"),
            ):
                response, next_action = agent._query_llm_with_next("journal")

            self.assertIsNone(next_action)
            self.assertIn("The status loop is still humming.", response)
            self.assertIn("Operational tail cooldown", response)
            self.assertIn("JOURNAL, DAYDREAM, or ASPIRE", response)
            self.assertIsNone(agent._pending_next_action)
            state_path = workspace / "state" / "operational_tail_cooldown_v1.json"
            self.assertTrue(state_path.exists())
            payload = json.loads(state_path.read_text())
            self.assertIsNone(payload["queued_next"])
            self.assertEqual(payload["policy"], "operational_tail_cooldown_v1")

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
            self.assertIn("weighted=0.034", text)
            self.assertIn("share=31%", text)
            self.assertIn("Silt granularity: index=0.44", text)
            self.assertIn("particle_scale=mixed_packed_silt", text)
            self.assertIn("review=pressure_source_audit_grain_probe", text)
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

    def test_regulator_audit_names_interface_transparency_without_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = Path(tmp) / "minime.db"
            (workspace / "journal").mkdir(parents=True)
            agent = self._agent(workspace, db_path)
            agent._pending_regulator_audit_label = "distance-contact-control"
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(aa, "build_controller_gradient_audit", return_value={}),
                patch.object(aa, "format_controller_gradient_audit_block", return_value="active controller: test"),
                patch.object(agent, "_write_journal_entry"),
            ):
                agent._regulator_audit(dict(STATE))

            journals = list((workspace / "journal").glob("regulator_audit_*.txt"))
            self.assertEqual(len(journals), 1)
            text = journals[0].read_text()
            self.assertIn("Interface transparency", text)
            self.assertIn("stabilization_pressure_visibility_v1", text)
            self.assertIn("not surrender mode", text)
            self.assertIn("or permission", text)
            self.assertIn("to change pressure, fill, PI", text)

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
