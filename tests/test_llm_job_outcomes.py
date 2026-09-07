"""Isolated durable job-store tests; no autonomous runtime or model imports."""

import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


from minime_autonomy import llm_access


class ClockStore(llm_access.LlmJobStore):
    seconds = 0

    def _now(self):
        return (datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).isoformat().replace("+00:00", "Z")


def process_operation(workspace, job_id, operation, ready, start, results):
    """Spawn-safe child: only the standalone store module and temporary files."""
    store = ClockStore(Path(workspace))
    store.seconds = 200
    ready.put(True)
    if not start.wait(10):
        results.put({"error": "start timeout"})
        return
    try:
        if operation == "poll":
            store.expire_timed_out_jobs()
            result = store.read_job(job_id)
        else:
            result = store.finish(job_id, "completed", result="same result", summary="same outcome")
        results.put({"status": result["status"]})
    except Exception as exc:
        results.put({"error": repr(exc)})


class TestLlmJobOutcomes(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.store = ClockStore(self.workspace)

    def submit(self, *, claim=True, store=None):
        store = store or self.store
        job = store.submit(action_id="action", thread_id="thread", action_text="NOTICE",
                           call_kind="notice", timeout_s=150, job_key="notice")
        if claim:
            claimed = store.claim_running(job["job_id"])
            self.assertTrue(claimed["claim_acquired"])
        return job["job_id"]

    def events(self, job_id):
        return [json.loads(line) for line in (self.store.jobs_dir / job_id / "events.jsonl").read_text().splitlines()]

    def test_finish_classifies_deadline_with_and_without_prior_poll(self):
        outcomes = []
        for poll_first in (False, True):
            store = ClockStore(self.workspace / str(poll_first))
            job_id = self.submit(store=store)
            if poll_first:
                store.seconds = 151
                store.expire_timed_out_jobs()
            store.seconds = 200
            job = store.finish(job_id, "completed", result="useful output", summary="Saved a journal.")
            self.assertEqual(job["status"], "timeout")
            self.assertEqual(job["worker_status"], "completed")
            self.assertEqual(job["deadline_exceeded_at"], "2020-01-01T00:02:30Z")
            self.assertEqual(job["completed_at"], "2020-01-01T00:03:20Z")
            self.assertEqual(job["finished_at"], "2020-01-01T00:02:30Z")
            self.assertEqual(Path(job["retained_result_path"]).read_text(), "useful output")
            outcomes.append((job["status"], job["worker_status"], job["completed_at"], job["deadline_exceeded_at"]))
        self.assertEqual(*outcomes)

    def test_exact_deadline_remains_on_time(self):
        job_id = self.submit()
        self.store.seconds = 150
        job = self.store.finish(job_id, "completed", result="on time")
        self.assertEqual(job["status"], "completed")
        self.assertIsNone(job["deadline_exceeded_at"])
        self.assertEqual(Path(job["result_path"]).read_text(), "on time")

    def test_late_artifacts_and_phase_evidence_survive_poll_timeout(self):
        job_id = self.submit()
        self.store.seconds = 151
        self.store.write_runtime_status()
        active = self.store.active_primary_job()
        self.assertEqual(active["status"], "timeout")
        self.assertEqual(active["worker_status"], "running")
        self.assertIsNone(active["completed_at"])
        status = json.loads(self.store.status_path.read_text())
        self.assertEqual(status["active_count"], 1)
        self.assertEqual(status["deadline_exceeded_running_count"], 1)
        self.assertEqual(self.store.find_active_by_key("notice")["job_id"], job_id)
        self.assertEqual(self.store.submit(action_id="second", thread_id=None, action_text="NOTICE",
                                          call_kind="notice", job_key="notice")["job_id"], job_id)
        journal = self.workspace / "journal.txt"
        journal.write_text("Already performed action effect.")
        artifacts = [{"kind": "journal", "path_or_uri": str(journal)}]
        timings = {"version": 1, "phases": [{"phase": "model", "duration_s": 82.5}]}
        self.store.seconds = 200
        job = self.store.finish(job_id, "completed", result="journal saved", summary="Journal saved.",
                                artifact_refs=artifacts, phase_timings=timings)
        self.assertTrue(journal.exists())
        self.assertEqual(job["artifact_refs"], artifacts)
        self.assertEqual(job["outcome"]["artifact_refs"], artifacts)
        self.assertEqual(job["outcome"]["phase_timings"], timings)
        self.assertEqual(job["phase_timings"], timings)
        compact = json.loads(self.store.status_path.read_text())["recent_jobs"][0]
        self.assertNotIn("phase_timings", compact["outcome"])
        self.assertNotIn("artifact_refs", compact["outcome"])
        self.assertEqual(compact["outcome"]["summary"], "Journal saved.")
        self.assertIsNone(self.store.active_primary_job())
        self.assertIn("Worker: completed", self.store.status_text(job_id))
        self.assertIn("Journal saved.", self.store.status_text(job_id))
        self.assertEqual([event["event"] for event in self.events(job_id)].count("late_result_retained"), 1)
        self.assertNotIn("late_result_ignored", [event["event"] for event in self.events(job_id)])

    def test_duplicate_and_terminal_claims_never_grant_execution(self):
        job_id = self.submit()
        before = self.store.read_job(job_id)
        self.assertFalse(self.store.claim_running(job_id)["claim_acquired"])
        self.assertEqual(before, self.store.read_job(job_id))
        self.store.finish(job_id, "completed")
        self.assertFalse(self.store.claim_running(job_id)["claim_acquired"])

    def test_canceled_queued_job_is_not_resurrected(self):
        job_id = self.submit(claim=False)
        job = self.store.request_cancel(job_id)
        self.assertEqual(job["worker_status"], "not_started")
        self.assertFalse(self.store.claim_running(job_id)["claim_acquired"])
        self.assertEqual(self.store.read_job(job_id)["status"], "canceled")
        job = self.store.finish(job_id, "completed", result="must not publish")
        self.assertEqual(job["status"], "canceled")
        self.assertFalse(Path(job["result_path"]).exists())
        self.assertIsNone(job["completed_at"])

    def test_expired_queued_job_is_not_claimed(self):
        job_id = self.submit(claim=False)
        self.store.seconds = 151
        job = self.store.claim_running(job_id)
        self.assertFalse(job["claim_acquired"])
        self.assertEqual(job["status"], "timeout")
        self.assertEqual(job["worker_status"], "not_started")
        self.assertIsNone(self.store.active_primary_job())

    def test_running_cancellation_preserves_actual_outcome_and_effects(self):
        job_id = self.submit()
        canceled = self.store.request_cancel(job_id)
        self.assertEqual(canceled["status"], "cancel_requested")
        self.assertIn("drain", canceled["summary"])
        self.assertEqual(self.store.active_primary_job()["job_id"], job_id)
        artifacts = [{"kind": "journal", "path_or_uri": "synthetic-existing-journal"}]
        self.store.seconds = 100
        job = self.store.finish(job_id, "failed", result="partial useful evidence", error="finalizer failed",
                                artifact_refs=artifacts)
        self.assertEqual(job["status"], "canceled")
        self.assertEqual(job["worker_status"], "failed")
        self.assertEqual(job["outcome"]["error"], "finalizer failed")
        self.assertEqual(job["outcome"]["artifact_refs"], artifacts)
        self.assertEqual(Path(job["retained_result_path"]).read_text(), "partial useful evidence")
        self.assertIsNone(self.store.active_primary_job())

    def test_identical_finish_retry_is_noop_and_conflict_is_rejected(self):
        job_id = self.submit()
        self.store.seconds = 200
        original = self.store.finish(job_id, "completed", result="one", phase_timings={"total_s": 200})
        files_before = {path.name: path.read_bytes() for path in (self.store.jobs_dir / job_id).iterdir() if path.is_file()}
        self.store.seconds = 250
        self.assertEqual(self.store.finish(job_id, "completed", result="one", phase_timings={"total_s": 200}), original)
        with self.assertRaisesRegex(ValueError, "Conflicting final outcome"):
            self.store.finish(job_id, "failed", result="two")
        files_after = {path.name: path.read_bytes() for path in (self.store.jobs_dir / job_id).iterdir() if path.is_file()}
        self.assertEqual(files_before, files_after)

    def test_thread_race_across_store_instances_has_one_outcome(self):
        job_id = self.submit()
        barrier = threading.Barrier(3)

        def action(poll):
            store = ClockStore(self.workspace)
            store.seconds = 200
            barrier.wait(timeout=5)
            if poll:
                store.expire_timed_out_jobs()
            else:
                store.finish(job_id, "completed", result="same result", summary="same outcome")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(action, poll) for poll in (False, True, False)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.store.read_job(job_id)["status"], "timeout")
        events = [event["event"] for event in self.events(job_id)]
        self.assertEqual(events.count("timeout"), 1)
        self.assertEqual(events.count("late_result_retained"), 1)

    def test_process_race_serializes_poll_and_identical_finalizers(self):
        job_id = self.submit()
        context = multiprocessing.get_context("spawn")
        ready, results, start = context.Queue(), context.Queue(), context.Event()
        processes = [context.Process(target=process_operation,
                     args=(str(self.workspace), job_id, operation, ready, start, results))
                     for operation in ("finish", "poll", "finish")]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=10))
            start.set()
            for _ in processes:
                result = results.get(timeout=10)
                self.assertNotIn("error", result)
                self.assertEqual(result["status"], "timeout")
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
        finally:
            start.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            results.close()
        events = [event["event"] for event in self.events(job_id)]
        self.assertEqual(events.count("timeout"), 1)
        self.assertEqual(events.count("late_result_retained"), 1)
        self.assertEqual(self.store.read_job(job_id)["worker_status"], "completed")

    def test_recovery_keeps_live_other_pid_and_permission_uncertainty(self):
        job_id = self.submit()
        job = self.store.read_job(job_id)
        job["worker_pid"] = os.getpid() + 100000
        self.store._write_job(job)
        for effect in (None, PermissionError()):
            with patch.object(llm_access.os, "kill", side_effect=effect) as alive:
                self.store.ensure_dirs()
                self.assertEqual(self.store.read_job(job_id)["worker_status"], "running")
                self.assertEqual(self.store.read_job(job_id)["worker_pid"], job["worker_pid"])
                alive.assert_called_with(job["worker_pid"], 0)

    def test_recovery_records_dead_worker_without_erasing_existing_result(self):
        job_id = self.submit()
        job = self.store.read_job(job_id)
        Path(job["result_path"]).write_text("Evidence from before worker exit.")
        self.store.seconds = 200
        with patch.object(llm_access.os, "kill", side_effect=ProcessLookupError()):
            self.store.recover_stale_running_jobs()
        recovered = self.store.read_job(job_id)
        self.assertEqual(recovered["status"], "timeout")
        self.assertEqual(recovered["worker_status"], "failed")
        self.assertEqual(recovered["outcome"]["error"], "worker_restarted_before_completion")
        self.assertEqual(Path(recovered["retained_result_path"]).read_text(), "Evidence from before worker exit.")

    def test_recovery_retains_uncommitted_late_output_and_phase_checkpoint(self):
        job_id = self.submit()
        self.store.seconds = 200
        self.store.expire_timed_out_jobs()
        directory = self.store.jobs_dir / job_id
        late_path = directory / "late_result.txt"
        late_path.write_text("Late evidence written just before a crash.")
        original_path = directory / "result.txt"
        original_path.write_text("Different earlier evidence must also survive.")
        phase_path = directory / "phase_timings.json"
        timings = {"schema": "arbitrary supported timing summary", "job_id": job_id,
                   "snapshot_stage": "before_outcome_commit", "elapsed_s": 199.5}
        phase_path.write_text(json.dumps(timings))
        originals = {path: path.read_bytes() for path in (late_path, original_path, phase_path)}
        with patch.object(llm_access.os, "kill", side_effect=ProcessLookupError()):
            self.store.recover_stale_running_jobs()
        recovered = self.store.read_job(job_id)
        self.assertEqual(recovered["status"], "timeout")
        self.assertEqual(recovered["worker_status"], "failed")
        self.assertEqual(recovered["retained_result_path"], str(late_path))
        self.assertEqual(recovered["phase_timings"], timings)
        references = {ref["path_or_uri"] for ref in recovered["artifact_refs"]}
        self.assertTrue({str(path) for path in originals}.issubset(references))
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_legacy_completed_record_is_readable_and_not_overwritten(self):
        job_id = self.submit()
        job = self.store.finish(job_id, "completed", result="historical output")
        for key in ("outcome", "outcome_sha256", "worker_status", "completed_at", "deadline_exceeded_at"):
            job.pop(key, None)
        self.store._write_job(job)
        self.assertEqual(self.store.read_job(job_id)["status"], "completed")
        self.assertIn("legacy / unknown", self.store.status_text(job_id))
        self.store.finish(job_id, "failed", result="do not replace")
        self.assertEqual(Path(job["result_path"]).read_text(), "historical output")

    def test_failed_atomic_job_replace_preserves_json_and_allows_retry(self):
        job_id = self.submit()
        original = self.store.read_job(job_id)
        replace = llm_access.os.replace

        def fail_job_replace(source, destination):
            if Path(destination).name == "job.json":
                raise OSError("synthetic replace failure")
            return replace(source, destination)

        with patch.object(llm_access.os, "replace", side_effect=fail_job_replace):
            with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                self.store.finish(job_id, "completed", result="retained before commit")
        self.assertEqual(self.store.read_job(job_id), original)
        retried = self.store.finish(job_id, "completed", result="retained before commit")
        self.assertEqual(retried["worker_status"], "completed")
        self.assertEqual(Path(retried["retained_result_path"]).read_text(), "retained before commit")

    def test_retry_repairs_event_and_status_after_committed_outcome(self):
        job_id = self.submit()
        with patch.object(self.store, "_record_outcome", side_effect=OSError("synthetic event failure")):
            with self.assertRaisesRegex(OSError, "synthetic event failure"):
                self.store.finish(job_id, "completed", result="durable result")
        committed = self.store.read_job(job_id)
        self.assertEqual(committed["worker_status"], "completed")
        self.assertNotIn("completed", [event["event"] for event in self.events(job_id)])
        self.store.finish(job_id, "completed", result="durable result")
        self.store.finish(job_id, "completed", result="durable result")
        self.assertEqual(self.store.read_job(job_id), committed)
        self.assertEqual([event["event"] for event in self.events(job_id)].count("completed"), 1)
        self.assertEqual(json.loads(self.store.status_path.read_text())["active_count"], 0)

    def test_legacy_running_and_timeout_records_remain_compatible(self):
        job_id = self.submit()
        job = self.store.read_job(job_id)
        job.pop("worker_status")
        job.pop("deadline_exceeded_at")
        self.store._write_job(job)
        self.assertTrue(self.store.worker_is_running(job))
        self.assertTrue(self.store.worker_is_running(self.store._compact_job(job)))
        self.store.seconds = 200
        self.store.expire_timed_out_jobs()
        self.assertTrue(self.store.worker_is_running(self.store.read_job(job_id)))
        late = self.store.finish(job_id, "completed", result="legacy worker output")
        self.assertEqual(late["status"], "timeout")
        self.assertEqual(late["worker_status"], "completed")
        self.assertEqual(Path(late["retained_result_path"]).read_text(), "legacy worker output")


if __name__ == "__main__":
    unittest.main()
