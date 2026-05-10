"""Tests for Minime durable LLM job status."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomous_agent as aa


STATE = {
    "eig1": 4.7,
    "deig": 0.01,
    "fill_ratio": 0.68,
    "spread": 3.0,
    "cov_lambda1": 8.0,
    "geom_rel": 1.0,
}


class FakeThread:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True


class TestMinimeLlmJobs(unittest.TestCase):
    def _agent(self, base_dir: Path, workspace: Path, db_path: Path) -> aa.AutonomousAgent:
        with (
            patch.object(aa, "BASE_DIR", base_dir),
            patch.object(aa, "WORKSPACE_DIR", workspace),
            patch.object(aa, "DB_PATH", db_path),
        ):
            return aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)

    def test_job_store_lifecycle_and_status_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.LlmJobStore(workspace)
            job = store.submit(
                action_id="act_minime_test_notice",
                thread_id="th_minime_test",
                action_text="NOTICE",
                call_kind="recess_notice",
                prompt="notice prompt",
                validation_contract="action_finalizer",
                next_policy="finalizer_owned",
            )
            self.assertEqual(job["status"], "queued")
            self.assertTrue((workspace / "llm_jobs" / "jobs" / job["job_id"] / "prompt.txt").exists())

            running = store.claim_running(job["job_id"])
            self.assertEqual(running["status"], "running")
            self.assertIn("running", store.status_text("latest").lower())

            completed = store.finish(
                job["job_id"],
                "completed",
                result="done",
                summary="notice completed",
            )
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(
                (workspace / "llm_jobs" / "jobs" / job["job_id"] / "result.txt").read_text(),
                "done",
            )
            runtime = json.loads((workspace / "runtime" / "llm_jobs_status.json").read_text())
            self.assertEqual(runtime["latest_job_id"], job["job_id"])

    def test_action_execution_queues_llm_job_without_running_model_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent.running = True
            FakeThread.instances = []

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(aa.threading, "Thread", FakeThread),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_query_llm_with_next") as query,
            ):
                agent._execute_action("recess_notice", dict(STATE))

            query.assert_not_called()
            self.assertEqual(len(FakeThread.instances), 1)
            self.assertTrue(FakeThread.instances[0].started)
            status = json.loads((workspace / "runtime" / "llm_jobs_status.json").read_text())
            self.assertEqual(status["active_count"], 1)
            self.assertEqual(status["active_jobs"][0]["call_kind"], "recess_notice")

            events = list((workspace / "action_threads" / "threads").glob("*/events.jsonl"))
            self.assertEqual(len(events), 1)
            self.assertIn('"status": "llm_running"', events[0].read_text())

    def test_action_status_and_cancel_are_thread_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            store = aa.ActionContinuityStore(workspace, session_id=7)
            jobs = aa.LlmJobStore(workspace)
            job = jobs.submit(
                action_id="act_minime_status",
                thread_id="th_minime_status",
                action_text="INTROSPECT autonomous_agent.py",
                call_kind="introspect",
            )

            status_text = store.handle_thread_action("ACTION_STATUS latest", dict(STATE))
            self.assertIn(job["job_id"], status_text)

            cancel_text = store.handle_thread_action("ACTION_CANCEL latest", dict(STATE))
            self.assertIn("canceled", cancel_text)
            self.assertEqual(jobs.read_job(job["job_id"])["status"], "canceled")

    def test_running_job_times_out_and_late_result_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            jobs = aa.LlmJobStore(workspace)
            job = jobs.submit(
                action_id="act_minime_timeout",
                thread_id="th_minime_timeout",
                action_text="INTROSPECT autonomous_agent.py",
                call_kind="introspect",
                timeout_s=1.0,
            )
            running = jobs.claim_running(job["job_id"])
            running["started_at"] = "2026-05-10T00:00:00Z"
            jobs._write_job(running)

            jobs.write_runtime_status()
            timed_out = jobs.read_job(job["job_id"])
            self.assertEqual(timed_out["status"], "timeout")
            self.assertEqual(timed_out["error"], "llm_job_timeout")

            late = jobs.finish(job["job_id"], "completed", result="late", summary="late")
            self.assertEqual(late["status"], "timeout")
            result_path = workspace / "llm_jobs" / "jobs" / job["job_id"] / "result.txt"
            self.assertFalse(result_path.exists())

    def test_active_worker_defers_llm_action_instead_of_inline_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "minime"
            workspace = base_dir / "workspace"
            db_path = root / "minime.db"
            agent = self._agent(base_dir, workspace, db_path)
            agent.running = True
            agent._llm_job_worker_active = True

            with (
                patch.object(aa, "BASE_DIR", base_dir),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "DB_PATH", db_path),
                patch.object(agent, "_low_fill_guard_status", return_value={
                    "active": False,
                    "fill_ratio": 0.68,
                    "target_fill_ratio": 0.68,
                    "spread_relief": 0.0,
                }),
                patch.object(agent, "_query_llm_with_next") as query,
            ):
                agent._execute_action("recess_notice", dict(STATE))

            query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
