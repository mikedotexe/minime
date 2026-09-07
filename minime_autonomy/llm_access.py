"""Durable LLM job persistence and prompt-adaptation ownership."""

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from . import job_history


_STORE_LOCKS = {}
_STORE_LOCKS_GUARD = threading.Lock()


def _serialized(method):
    """One read/modify/write transaction across store instances and processes."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._transaction():
            return method(self, *args, **kwargs)
    return locked


class LlmJobStore:
    """File-first durable status for long local LLM work."""

    schema_version = 1
    terminal_statuses = {"completed", "thin_output", "timeout", "failed", "canceled", "blocked"}
    active_statuses = {"queued", "running", "cancel_requested"}

    def __init__(self, workspace_dir: Path, system: str = "minime"):
        self.workspace_dir = Path(workspace_dir)
        self.system = system
        self.root = self.workspace_dir / "llm_jobs"
        self.jobs_dir = self.root / "jobs"
        self.index_path = self.root / "index.json"
        self.status_path = self.workspace_dir / "runtime" / "llm_jobs_status.json"

    @contextmanager
    def _transaction(self):
        # The shared RLock permits nested public calls and separate store objects
        # in one thread. flock serializes the same transaction with other processes.
        key = (os.getpid(), str(self.root.resolve()))
        with _STORE_LOCKS_GUARD:
            state = _STORE_LOCKS.setdefault(key, {"lock": threading.RLock(), "depth": 0})
        with state["lock"]:
            if not state["depth"]:
                self.root.mkdir(parents=True, exist_ok=True)
                handle = (self.root / ".store.lock").open("a+")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except BaseException:
                    handle.close()
                    raise
                state["handle"] = handle
            state["depth"] += 1
            try:
                yield
            finally:
                state["depth"] -= 1
                if not state["depth"]:
                    handle = state.pop("handle")
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    handle.close()

    @_serialized
    def ensure_dirs(self) -> None:
        self.ensure_dirs_no_recover()
        self.recover_stale_running_jobs()
        self.write_runtime_status()

    @_serialized
    def ensure_dirs_no_recover(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_json(self.index_path, {
                "schema_version": self.schema_version,
                "system": self.system,
                "latest_job_id": None,
                "active_primary_job_id": None,
                "active_background_job_id": None,
                "recent_jobs": [],
                "updated_at": self._now(),
            })

    @_serialized
    def submit(
        self,
        *,
        action_id: Optional[str],
        thread_id: Optional[str],
        action_text: str,
        call_kind: str,
        prompt: str = "",
        timeout_s: float = 300.0,
        validation_contract: str = "action_finalizer",
        next_policy: str = "finalizer_owned",
        priority: str = "primary",
        job_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_dirs()
        if job_key:
            existing = self.find_active_by_key(job_key)
            if existing:
                return existing
        job_id = self._unique_job_id(action_text or call_kind)
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = job_dir / "prompt.txt"
        result_path = job_dir / "result.txt"
        self._write_text(job_dir / "events.jsonl", "")
        self._write_text(prompt_path, prompt or "")
        now = self._now()
        job = {
            "schema_version": self.schema_version,
            "job_id": job_id,
            "system": self.system,
            "action_id": action_id,
            "thread_id": thread_id,
            "action_text": action_text,
            "call_kind": call_kind,
            "status": "queued",
            "worker_status": "queued",
            "worker_pid": None,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "completed_at": None,
            "deadline_at": None,
            "deadline_exceeded_at": None,
            "outcome": None,
            "timeout_s": timeout_s,
            "validation_contract": validation_contract,
            "next_policy": next_policy,
            "prompt_path": str(prompt_path),
            "result_path": str(result_path),
            "artifact_refs": [],
            "error": None,
            "summary": "Queued LLM job.",
            "priority": priority,
            "job_key": job_key,
        }
        job["deadline_at"] = self._deadline(job)
        self._write_job(job)
        self._append_event(job_id, {"event": "queued", "at": now, "summary": job["summary"]})
        self._update_index(job)
        self.write_runtime_status()
        return job

    @_serialized
    def claim_running(self, job_id: str) -> Dict[str, Any]:
        job = self.read_job(job_id)
        if not job:
            raise ValueError(f"No LLM job matched `{job_id}`")
        self._expire_job(job)
        if job.get("status") != "queued":
            return dict(job, claim_acquired=False)
        job["status"] = "running"
        job["worker_status"] = "running"
        job["worker_pid"] = os.getpid()
        job["started_at"] = self._now()
        job["deadline_at"] = self._deadline(job)
        job["summary"] = f"Running {job.get('call_kind') or 'llm'} job."
        self._write_job(job)
        self._append_event(job_id, {"event": "running", "at": job["started_at"], "summary": job["summary"]})
        self._update_index(job)
        self.write_runtime_status()
        # This permission is deliberately not persisted: reading or retrying a
        # claim must not grant a second caller permission to execute the action.
        return dict(job, claim_acquired=True)

    @_serialized
    def finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Optional[str] = None,
        summary: str = "",
        error: Optional[str] = None,
        artifact_refs: Optional[List[Dict[str, Any]]] = None,
        phase_timings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = self.read_job(job_id)
        if not job:
            raise ValueError(f"No LLM job matched `{job_id}`")
        worker_status = status if status in self.terminal_statuses else "failed"
        evidence = {
            "status": worker_status,
            "summary": summary or worker_status.replace("_", " "),
            "error": error,
            "result_sha256": hashlib.sha256(result.encode("utf-8")).hexdigest() if result is not None else None,
            "artifact_refs": artifact_refs or [],
            "phase_timings": phase_timings or {},
        }
        # JSON normalization also detaches caller-owned lists/dictionaries.
        evidence = json.loads(json.dumps(evidence, sort_keys=True, allow_nan=False))
        fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        if job.get("outcome") is not None:
            if job.get("outcome_sha256") != fingerprint:
                raise ValueError(f"Conflicting final outcome for LLM job `{job_id}`")
            # The authoritative job may have committed just before a projection
            # write failed. Retrying repairs the event/index/status, without
            # changing the outcome or publishing a second completion event.
            self._record_outcome(job)
            self._update_index(job)
            self.write_runtime_status()
            return job
        if job.get("status") in self.terminal_statuses and job.get("status") not in {"timeout", "canceled"}:
            # A schema-v1 terminal record has no independent worker evidence.
            # Preserve its authority; a retry must not rewrite historical results.
            return job
        if job.get("status") == "canceled" and not job.get("started_at"):
            return job
        now = self._now()
        self._expire_job(job, now=now)
        if job.get("status") == "timeout" and not job.get("deadline_exceeded_at"):
            job["deadline_at"] = self._deadline(job)
            job["deadline_exceeded_at"] = job["deadline_at"]
        late = job.get("status") in {"timeout", "canceled", "cancel_requested"}
        result_path = None
        if result is not None:
            result_path = self.jobs_dir / job_id / ("late_result.txt" if late else "result.txt")
            if result_path.exists() and result_path.read_text() != result:
                raise ValueError(f"Conflicting retained result for LLM job `{job_id}`")
            if not result_path.exists():
                self._write_text(result_path, result)
        evidence["result_path"] = str(result_path) if result_path else None
        job["outcome"] = evidence
        job["outcome_sha256"] = fingerprint
        job["worker_status"] = worker_status
        job["completed_at"] = now
        job["artifact_refs"] = evidence["artifact_refs"]
        job["phase_timings"] = evidence["phase_timings"]
        job["retained_result_path"] = evidence["result_path"]
        if job.get("status") == "timeout":
            job["summary"] = f"Deadline exceeded; worker {worker_status}. {evidence['summary']} Evidence retained."
        elif job.get("status") in {"canceled", "cancel_requested"}:
            job["status"] = "canceled"
            job["finished_at"] = job.get("finished_at") or now
            job["summary"] = f"Cancellation requested; worker {worker_status}. {evidence['summary']} Performed effects and evidence were retained."
        else:
            job["status"] = worker_status
            job["finished_at"] = now
            job["summary"] = evidence["summary"]
            job["error"] = error
        self._write_job(job)
        self._record_outcome(job)
        self._update_index(job)
        self.write_runtime_status()
        return job

    @_serialized
    def request_cancel(self, selector: str = "latest") -> Dict[str, Any]:
        self.expire_timed_out_jobs()
        job = self.resolve(selector)
        if not job:
            raise ValueError(f"No LLM job matched `{selector or 'latest'}`")
        if job.get("status") == "queued":
            job.update(status="canceled", worker_status="not_started", finished_at=self._now(),
                       cancel_requested_at=self._now(), summary="Canceled before worker start.")
            self._write_job(job)
            self._append_event(job["job_id"], {"event": "canceled", "at": job["finished_at"], "summary": job["summary"]})
            self._update_index(job)
            self.write_runtime_status()
        elif self.worker_is_running(job) and not job.get("cancel_requested_at"):
            if job.get("status") != "timeout":
                job["status"] = "cancel_requested"
            job["cancel_requested_at"] = self._now()
            job["summary"] = "Cancel requested; the accepted worker will drain. Already performed effects and its eventual evidence are retained."
            self._write_job(job)
            self._append_event(job["job_id"], {
                "event": "cancel_requested",
                "at": self._now(),
                "summary": job["summary"],
            })
            self._update_index(job)
            self.write_runtime_status()
        return job

    @_serialized
    def resolve(self, selector: Optional[str] = None) -> Optional[Dict[str, Any]]:
        self.ensure_dirs()
        self.expire_timed_out_jobs()
        selector = (selector or "latest").strip()
        if not selector or selector.lower() == "latest":
            job_id = self._read_index().get("latest_job_id")
            return self.read_job(job_id) if job_id else None
        if selector.startswith("job_"):
            return self.read_job(selector)
        for job in reversed(self.list_jobs(50)):
            if selector == str(job.get("action_id") or ""):
                return job
        lowered = selector.lower()
        for job in reversed(self.list_jobs(50)):
            if lowered in str(job.get("action_text") or "").lower():
                return job
        return None

    @_serialized
    def status_text(self, selector: Optional[str] = None) -> str:
        self.expire_timed_out_jobs()
        job = self.resolve(selector)
        if not job:
            return f"No LLM job matched `{selector or 'latest'}`."
        return (
            f"LLM job `{job['job_id']}` [{job.get('status')}]\n"
            f"Action: {job.get('action_text') or '(none)'}\n"
            f"Call kind: {job.get('call_kind') or '(unknown)'}\n"
            f"Action id: {job.get('action_id') or '(pending)'}\n"
            f"Thread id: {job.get('thread_id') or '(none)'}\n"
            f"Elapsed: {self._elapsed_text(job)}\n"
            f"Worker: {job.get('worker_status') or 'legacy / unknown'}\n"
            f"Worker completed: {job.get('completed_at') or '(not recorded)'}\n"
            f"Deadline exceeded: {job.get('deadline_exceeded_at') or '(not recorded)'}\n"
            f"Validation: {job.get('validation_contract') or '(none)'}\n"
            f"NEXT policy: {job.get('next_policy') or '(none)'}\n"
            f"Summary: {job.get('summary') or ''}\n"
            f"Outcome: {(job.get('outcome') or {}).get('summary') or '(not recorded)'}\n"
            f"Retained result: {job.get('retained_result_path') or '(none recorded)'}"
        )

    @staticmethod
    def worker_is_running(job: Dict[str, Any]) -> bool:
        if job.get("worker_status") is not None:
            return job.get("worker_status") == "running"
        return job.get("status") in {"running", "cancel_requested"}

    @classmethod
    def job_is_active(cls, job: Dict[str, Any]) -> bool:
        return job.get("status") in cls.active_statuses or cls.worker_is_running(job)

    @_serialized
    def active_primary_job(self) -> Optional[Dict[str, Any]]:
        self.expire_timed_out_jobs()
        for job in reversed(self.list_jobs(20)):
            if job.get("priority") == "primary" and self.job_is_active(job):
                return job
        return None

    @_serialized
    def find_active_by_key(self, job_key: str) -> Optional[Dict[str, Any]]:
        self.expire_timed_out_jobs()
        for job in reversed(self.list_jobs(30)):
            if job.get("job_key") == job_key and self.job_is_active(job):
                return job
        return None

    @_serialized
    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        self.ensure_dirs_no_recover()
        return job_history.recent_jobs(self.jobs_dir, limit)

    @_serialized
    def read_job(self, job_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not job_id:
            return None
        path = self.jobs_dir / job_id / "job.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    @_serialized
    def recover_stale_running_jobs(self) -> None:
        self.ensure_dirs_no_recover()
        for job in self.list_jobs(100):
            if not self.worker_is_running(job):
                continue
            # A store observer may be a different, concurrently running process.
            # Only confirmed kernel absence establishes a dead worker. Missing
            # identity or permission errors leave ownership uncertain, not failed.
            pid = job.get("worker_pid")
            if not isinstance(pid, int) or pid <= 0:
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except OSError:
                continue
            else:
                continue
            # A crash can occur after a result/checkpoint replacement and before
            # job.json commits. Retain all such files, including conflicting
            # ordinary/late outputs, without overwriting either as recovery.
            directory = self.jobs_dir / job["job_id"]
            artifacts = list(job.get("artifact_refs") or [])
            retained = {}
            phase_timings = job.get("phase_timings")
            for name in ("result.txt", "late_result.txt", "phase_timings.json"):
                path = directory / name
                if not path.is_file():
                    continue
                data = path.read_bytes()
                retained[name] = data
                if not any(item.get("path_or_uri") == str(path) for item in artifacts if isinstance(item, dict)):
                    artifacts.append({"kind": "llm_job_recovered_evidence", "path_or_uri": str(path),
                                      "sha256": hashlib.sha256(data).hexdigest()})
                if name == "phase_timings.json":
                    try:
                        parsed = json.loads(data)
                        json.dumps(parsed, allow_nan=False)
                        if isinstance(parsed, dict):
                            phase_timings = parsed
                    except (ValueError, TypeError):
                        pass
            deadline = self._deadline(job)
            late = job.get("status") in {"timeout", "canceled", "cancel_requested"} or (
                deadline is not None and self._parse_time(self._now()) > self._parse_time(deadline)
            )
            destination = "late_result.txt" if late else "result.txt"
            data = retained.get(destination)
            if data is None:
                data = retained.get("result.txt") or retained.get("late_result.txt")
            try:
                result = data.decode("utf-8") if data is not None else None
            except UnicodeDecodeError:
                result = None  # Raw-byte evidence remains referenced and hashed.
            self.finish(job["job_id"], "failed", result=result,
                        summary="Worker process exited before its final outcome was recorded; existing evidence retained.",
                        error="worker_restarted_before_completion", artifact_refs=artifacts,
                        phase_timings=phase_timings)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    def _deadline(self, job: Dict[str, Any]) -> Optional[str]:
        try:
            timeout = float(job.get("timeout_s"))
            if not math.isfinite(timeout) or timeout <= 0:
                return None
            start = self._parse_time(job.get("started_at") or job.get("created_at"))
            return (start + timedelta(seconds=timeout)).isoformat().replace("+00:00", "Z")
        except (ValueError, TypeError, OverflowError):
            return None

    def _expire_job(self, job: Dict[str, Any], *, now: Optional[str] = None) -> bool:
        if job.get("status") not in self.active_statuses:
            return False
        deadline = self._deadline(job)
        now = now or self._now()
        if deadline is None or self._parse_time(now) <= self._parse_time(deadline):
            return False
        job["deadline_at"] = deadline
        job["deadline_exceeded_at"] = deadline
        job["deadline_observed_at"] = now
        job["status"] = "timeout"
        job["finished_at"] = deadline
        job["error"] = "llm_job_timeout"
        if not job.get("started_at"):
            job["worker_status"] = "not_started"
        elif "worker_status" not in job:
            job["worker_status"] = "running"
        job["summary"] = "Deadline exceeded; accepted work may still be running. Its eventual outcome and evidence will be retained."
        self._write_job(job)
        self._append_event(job["job_id"], {
            "event": "timeout", "at": now, "deadline_exceeded_at": deadline,
            "error": job["error"], "summary": job["summary"],
        })
        self._update_index(job)
        return True

    @_serialized
    def expire_timed_out_jobs(self) -> None:
        self.ensure_dirs_no_recover()
        now = self._now()
        for job in self.list_jobs(100):
            self._expire_job(job, now=now)

    @_serialized
    def write_runtime_status(self) -> None:
        self.ensure_dirs_no_recover()
        self.expire_timed_out_jobs()
        jobs = self.list_jobs(12)
        active = [job for job in jobs if self.job_is_active(job)]
        payload = {
            "schema_version": self.schema_version,
            "system": self.system,
            "updated_at": self._now(),
            "active_count": len(active),
            "running_worker_count": sum(self.worker_is_running(job) for job in jobs),
            "deadline_exceeded_running_count": sum(self.worker_is_running(job) and job.get("status") == "timeout" for job in jobs),
            "latest_job_id": jobs[-1].get("job_id") if jobs else None,
            "active_jobs": [self._compact_job(job) for job in active[-5:]],
            "recent_jobs": [self._compact_job(job) for job in jobs[-8:]],
        }
        self._write_json(self.status_path, payload)

    def _compact_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        outcome = job.get("outcome")
        compact_outcome = ({key: outcome.get(key) for key in ("status", "summary", "error", "result_path")}
                           if isinstance(outcome, dict) else None)
        return {
            "job_id": job.get("job_id"),
            "action_id": job.get("action_id"),
            "thread_id": job.get("thread_id"),
            "action_text": job.get("action_text"),
            "call_kind": job.get("call_kind"),
            "status": job.get("status"),
            "worker_status": job.get("worker_status"),
            "completed_at": job.get("completed_at"),
            "deadline_exceeded_at": job.get("deadline_exceeded_at"),
            "outcome": compact_outcome,
            "retained_result_path": job.get("retained_result_path"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "elapsed": self._elapsed_text(job),
            "summary": job.get("summary"),
        }

    def _update_index(self, job: Dict[str, Any]) -> None:
        index = self._read_index()
        recent = [item for item in index.get("recent_jobs", []) if item != job["job_id"]]
        recent.append(job["job_id"])
        index.update({
            "schema_version": self.schema_version,
            "system": self.system,
            "latest_job_id": job["job_id"],
            "recent_jobs": recent[-30:],
            "updated_at": self._now(),
        })
        if job.get("priority") == "primary" and self.job_is_active(job):
            index["active_primary_job_id"] = job["job_id"]
        elif index.get("active_primary_job_id") == job["job_id"]:
            index["active_primary_job_id"] = None
        if job.get("priority") == "background" and self.job_is_active(job):
            index["active_background_job_id"] = job["job_id"]
        elif index.get("active_background_job_id") == job["job_id"]:
            index["active_background_job_id"] = None
        self._write_json(self.index_path, index)

    def _read_index(self) -> Dict[str, Any]:
        self.ensure_dirs_no_recover()
        try:
            return json.loads(self.index_path.read_text())
        except Exception:
            return {
                "schema_version": self.schema_version,
                "system": self.system,
                "latest_job_id": None,
                "active_primary_job_id": None,
                "active_background_job_id": None,
                "recent_jobs": [],
                "updated_at": self._now(),
            }

    def _write_job(self, job: Dict[str, Any]) -> None:
        job["updated_at"] = self._now()
        self._write_json(self.jobs_dir / job["job_id"] / "job.json", job)

    def _record_outcome(self, job: Dict[str, Any]) -> None:
        path = self.jobs_dir / job["job_id"] / "events.jsonl"
        if path.is_file():
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("outcome_sha256") == job["outcome_sha256"]:
                    return
        self._append_event(job["job_id"], {
            "event": "late_result_retained" if job["status"] in {"timeout", "canceled"} else job["worker_status"],
            "at": job["completed_at"], "worker_status": job["worker_status"],
            "outcome_sha256": job["outcome_sha256"], "summary": job["summary"],
            "error": job["outcome"]["error"],
        })

    def _append_event(self, job_id: str, payload: Dict[str, Any]) -> None:
        path = self.jobs_dir / job_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        self._write_text(path, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _unique_job_id(self, action_text: str) -> str:
        root = f"job_{self.system}_{int(time.time() * 1000)}_{self._slug(action_text or 'llm')}"
        candidate = root[:120]
        suffix = 2
        while (self.jobs_dir / candidate).exists():
            candidate = f"{root[:112]}_{suffix}"
            suffix += 1
        return candidate

    def _slug(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
        return slug[:48] or "llm"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _elapsed_text(self, job: Dict[str, Any]) -> str:
        start = job.get("started_at") or job.get("created_at")
        end = job.get("completed_at") or (None if self.worker_is_running(job) else job.get("finished_at"))
        try:
            start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            end_dt = (
                datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                if end
                else datetime.now(timezone.utc)
            )
            return f"{max(0, int((end_dt - start_dt).total_seconds()))}s"
        except Exception:
            return "unknown"


def runtime_source_path() -> Path:
    """Return the substantive implementation behind the stable root facade."""
    candidate = Path(__file__).with_name("runtime.py")
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve()


class LlmRuntime(Protocol):
    def _query_llm(self, prompt: str) -> str | None: ...

    def _query_llm_with_next(self, prompt: str) -> tuple[str | None, str | None]: ...

    def _query_llm_raw(self, messages: List[Dict[str, Any]]) -> str | None: ...


__all__ = ["LlmJobStore", "LlmRuntime", "runtime_source_path"]
