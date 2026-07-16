"""Durable LLM job persistence and prompt-adaptation ownership."""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

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

    def ensure_dirs(self) -> None:
        self.ensure_dirs_no_recover()
        self.recover_stale_running_jobs()
        self.write_runtime_status()

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
        (job_dir / "events.jsonl").write_text("")
        prompt_path.write_text(prompt or "")
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
            "created_at": now,
            "started_at": None,
            "finished_at": None,
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
        self._write_job(job)
        self._append_event(job_id, {"event": "queued", "at": now, "summary": job["summary"]})
        self._update_index(job)
        self.write_runtime_status()
        return job

    def claim_running(self, job_id: str) -> Dict[str, Any]:
        job = self.read_job(job_id)
        if not job:
            raise ValueError(f"No LLM job matched `{job_id}`")
        if job.get("status") == "cancel_requested":
            return self.finish(job_id, "canceled", summary="Canceled before worker start.")
        job["status"] = "running"
        job["started_at"] = job.get("started_at") or self._now()
        job["summary"] = f"Running {job.get('call_kind') or 'llm'} job."
        self._write_job(job)
        self._append_event(job_id, {"event": "running", "at": job["started_at"], "summary": job["summary"]})
        self._update_index(job)
        self.write_runtime_status()
        return job

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Optional[str] = None,
        summary: str = "",
        error: Optional[str] = None,
        artifact_refs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        job = self.read_job(job_id)
        if not job:
            raise ValueError(f"No LLM job matched `{job_id}`")
        if job.get("status") in self.terminal_statuses:
            self._append_event(job_id, {
                "event": "late_result_ignored",
                "at": self._now(),
                "summary": f"Late `{status}` result ignored because job is already `{job.get('status')}`.",
            })
            self.write_runtime_status()
            return job
        final_status = (
            "canceled"
            if job.get("status") == "cancel_requested" and status == "completed"
            else status
        )
        if final_status not in self.terminal_statuses:
            final_status = "failed"
        if result is not None and final_status != "canceled":
            Path(job["result_path"]).write_text(result)
        job["status"] = final_status
        job["finished_at"] = self._now()
        job["summary"] = summary or final_status.replace("_", " ")
        job["error"] = error
        if artifact_refs is not None:
            job["artifact_refs"] = artifact_refs
        self._write_job(job)
        self._append_event(job_id, {
            "event": final_status,
            "at": job["finished_at"],
            "summary": job["summary"],
            "error": error,
        })
        self._update_index(job)
        self.write_runtime_status()
        return job

    def request_cancel(self, selector: str = "latest") -> Dict[str, Any]:
        self.expire_timed_out_jobs()
        job = self.resolve(selector)
        if not job:
            raise ValueError(f"No LLM job matched `{selector or 'latest'}`")
        if job.get("status") == "queued":
            return self.finish(job["job_id"], "canceled", summary="Canceled before worker start.")
        if job.get("status") == "running":
            job["status"] = "cancel_requested"
            job["summary"] = "Cancel requested; running LLM call will be discarded when it returns."
            self._write_job(job)
            self._append_event(job["job_id"], {
                "event": "cancel_requested",
                "at": self._now(),
                "summary": job["summary"],
            })
            self._update_index(job)
            self.write_runtime_status()
        return job

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
            f"Validation: {job.get('validation_contract') or '(none)'}\n"
            f"NEXT policy: {job.get('next_policy') or '(none)'}\n"
            f"Summary: {job.get('summary') or ''}"
        )

    def active_primary_job(self) -> Optional[Dict[str, Any]]:
        self.expire_timed_out_jobs()
        for job in reversed(self.list_jobs(20)):
            if job.get("priority") == "primary" and job.get("status") in self.active_statuses:
                return job
        return None

    def find_active_by_key(self, job_key: str) -> Optional[Dict[str, Any]]:
        self.expire_timed_out_jobs()
        for job in reversed(self.list_jobs(30)):
            if job.get("job_key") == job_key and job.get("status") in self.active_statuses:
                return job
        return None

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        self.ensure_dirs_no_recover()
        jobs: List[Dict[str, Any]] = []
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                jobs.append(json.loads(path.read_text()))
            except Exception:
                continue
        jobs.sort(key=lambda item: item.get("created_at") or "")
        return jobs[-limit:]

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

    def recover_stale_running_jobs(self) -> None:
        self.ensure_dirs_no_recover()
        current_pid = os.getpid()
        for job in self.list_jobs(100):
            if job.get("status") not in {"running", "cancel_requested"}:
                continue
            result_path = Path(str(job.get("result_path") or ""))
            if result_path.exists() and result_path.stat().st_size > 0:
                continue
            if job.get("worker_pid") == current_pid:
                continue
            job["status"] = "failed"
            job["finished_at"] = self._now()
            job["error"] = "worker_restarted_before_completion"
            job["summary"] = "Worker restarted before completion; result was not written."
            self._write_job(job)
            self._append_event(job["job_id"], {
                "event": "failed",
                "at": job["finished_at"],
                "error": job["error"],
                "summary": job["summary"],
            })
            self._update_index(job)

    def expire_timed_out_jobs(self) -> None:
        self.ensure_dirs_no_recover()
        now = datetime.now(timezone.utc)
        changed = False
        for job in self.list_jobs(100):
            if job.get("status") not in self.active_statuses:
                continue
            timeout_s = job.get("timeout_s")
            try:
                timeout = float(timeout_s)
            except (TypeError, ValueError):
                continue
            if timeout <= 0.0:
                continue
            start = job.get("started_at") or job.get("created_at")
            try:
                start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            except Exception:
                continue
            elapsed = max(0.0, (now - start_dt).total_seconds())
            if elapsed <= timeout:
                continue
            job["status"] = "timeout"
            job["finished_at"] = self._now()
            job["error"] = "llm_job_timeout"
            job["summary"] = (
                f"Timed out after {int(timeout)}s; any late worker result will be ignored."
            )
            self._write_job(job)
            self._append_event(job["job_id"], {
                "event": "timeout",
                "at": job["finished_at"],
                "error": job["error"],
                "summary": job["summary"],
            })
            self._update_index(job)
            changed = True
        if changed:
            self.ensure_dirs_no_recover()

    def write_runtime_status(self) -> None:
        self.ensure_dirs_no_recover()
        self.expire_timed_out_jobs()
        jobs = self.list_jobs(12)
        active = [job for job in jobs if job.get("status") in self.active_statuses]
        payload = {
            "schema_version": self.schema_version,
            "system": self.system,
            "updated_at": self._now(),
            "active_count": len(active),
            "latest_job_id": jobs[-1].get("job_id") if jobs else None,
            "active_jobs": [self._compact_job(job) for job in active[-5:]],
            "recent_jobs": [self._compact_job(job) for job in jobs[-8:]],
        }
        self._write_json(self.status_path, payload)

    def _compact_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": job.get("job_id"),
            "action_id": job.get("action_id"),
            "thread_id": job.get("thread_id"),
            "action_text": job.get("action_text"),
            "call_kind": job.get("call_kind"),
            "status": job.get("status"),
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
        if job.get("priority") == "primary" and job.get("status") in self.active_statuses:
            index["active_primary_job_id"] = job["job_id"]
        elif index.get("active_primary_job_id") == job["job_id"]:
            index["active_primary_job_id"] = None
        if job.get("priority") == "background" and job.get("status") in self.active_statuses:
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
        if job.get("status") in self.active_statuses:
            job["worker_pid"] = os.getpid()
        self._write_json(self.jobs_dir / job["job_id"] / "job.json", job)

    def _append_event(self, job_id: str, payload: Dict[str, Any]) -> None:
        path = self.jobs_dir / job_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

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
        end = job.get("finished_at")
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
