"""Bounded, content-free phase checkpoints for one synchronous background job.

Durations use a monotonic clock. Spans are nested: inclusive seconds include
children; exclusive seconds subtract direct children. Atomic replacement keeps
the last checkpoint readable after a process crash (not a power-loss guarantee).
No history is read and timing failures must never change an action's outcome.
The record's state describes the timing scope, not the job's semantic outcome.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

MAX_SPANS = 128
MAX_ATTEMPTS = 24
MAX_GENERATIONS = 24
_active = ContextVar("minime_job_timing", default=None)
_preparation = ContextVar("minime_job_timing_preparation", default=None)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_PHASE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")


def _identifier(value):
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _current():
    recorder = _active.get()
    return recorder if recorder and recorder.owner == threading.get_ident() else None


class _Span:
    def __init__(self, recorder=None, row=None):
        self.recorder, self.row = recorder, row

    def __enter__(self):
        return self

    def finish(self, error_type=None):
        try:
            if self.row is not None and self.row["end"] is None:
                self.recorder.end(self.row, error_type)
        except Exception:
            pass

    def __exit__(self, kind, value, traceback):
        self.finish(kind.__name__ if kind else None)
        return False


class Recorder:
    def __init__(self, workspace, job_id, action_id=None, thread_id=None):
        self.owner = threading.get_ident()
        self.started = time.monotonic()
        self.finished = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.job_id = job_id
        self.action_id, self.thread_id = _identifier(action_id), _identifier(thread_id)
        self.spans, self.stack, self.attempts, self.generation_ids = [], [], [], []
        self.current_generation = None
        self.attempt_counts = {"ok": 0, "empty": 0, "error": 0}
        self.dropped_spans = self.dropped_attempts = self.dropped_generations = 0
        self.persistence_errors = self.checkpoint_sequence = 0
        self.state = "running"
        self.path = None
        try:
            directory = Path(workspace) / "llm_jobs" / "jobs" / job_id
            if directory.is_symlink():
                raise OSError("symlink job directory")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = directory / "phase_timings.json"
        except Exception:
            self.persistence_errors += 1
        self.checkpoint()

    def begin(self, name, **metadata):
        if not isinstance(name, str) or not _PHASE.fullmatch(name):
            return _Span()
        if len(self.spans) >= MAX_SPANS:
            self.dropped_spans += 1
            return _Span()
        row = {"span_id": len(self.spans) + 1,
               "parent_id": self.stack[-1]["span_id"] if self.stack else None,
               "phase": name, "start": time.monotonic(), "end": None,
               "status": "active", "generation_id": self.current_generation}
        # A fixed metadata allowlist deliberately excludes prompt/body/error text.
        for key in ("backend", "model"):
            if _identifier(metadata.get(key)):
                row[key] = metadata[key]
        self.spans.append(row)
        self.stack.append(row)
        self.checkpoint()
        return _Span(self, row)

    def end(self, row, error_type=None):
        now = time.monotonic()
        # An exception during preparation may leave its child span open.
        while self.stack:
            current = self.stack.pop()
            current["end"] = now
            current["status"] = "error" if error_type else "ok"
            if error_type:
                current["error_type"] = _identifier(error_type) or "Exception"
            if current is row:
                break
        self.checkpoint()

    def snapshot(self):
        now = self.finished if self.finished is not None else time.monotonic()
        spans = []
        for row in self.spans:
            elapsed = max(0.0, (row["end"] if row["end"] is not None else now) - row["start"])
            children = sum(max(0.0, (c["end"] if c["end"] is not None else now) - c["start"])
                           for c in self.spans if c["parent_id"] == row["span_id"])
            spans.append({k: v for k, v in row.items() if k not in {"start", "end"}} | {
                "start_s": round(max(0.0, row["start"] - self.started), 6),
                "inclusive_s": round(elapsed, 6),
                "exclusive_s": round(max(0.0, elapsed - children), 6),
            })
        elapsed = max(0.0, now - self.started)
        result = {
            "schema": "minime_job_phase_timings_v1", "job_id": self.job_id,
            "action_id": self.action_id, "thread_id": self.thread_id,
            "started_at": self.started_at, "state": self.state,
            "snapshot_complete": self.finished is not None,
            "checkpoint_file": "phase_timings.json",
            "elapsed_s": round(elapsed, 6), "spans": spans,
            "unattributed_s": round(max(0.0, elapsed - sum(
                s["inclusive_s"] for s in spans if s["parent_id"] is None)), 6),
            "attempt_counts": dict(self.attempt_counts),
            "attempts": [dict(a) for a in self.attempts],
            "generation_ids": list(self.generation_ids),
            "dropped_spans": self.dropped_spans, "dropped_attempts": self.dropped_attempts,
            "dropped_generations": self.dropped_generations,
            "checkpoint_sequence": self.checkpoint_sequence,
            "persistence_errors": self.persistence_errors,
        }
        return result

    def summary(self):
        try:
            return self.snapshot()
        except Exception:
            return {}

    def checkpoint(self):
        if self.path is None:
            return
        temporary = self.path.with_name(".phase_timings-" + uuid4().hex + ".tmp")
        try:
            self.checkpoint_sequence += 1
            payload = json.dumps(self.snapshot(), allow_nan=False, separators=(",", ":"))
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            os.replace(temporary, self.path)
        except Exception:
            self.persistence_errors += 1
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass

    def finish(self, error_type=None):
        if self.stack:
            self.end(self.stack[0], error_type)
        self.finished = time.monotonic()
        self.state = "error" if error_type else "complete"
        self.checkpoint()


class _Disabled:
    def summary(self):
        return {}

    snapshot = summary


@contextmanager
def job_scope(workspace, *, job_id, action_id=None, thread_id=None):
    recorder = None
    try:
        if isinstance(job_id, str) and re.fullmatch(r"job_[A-Za-z0-9_-]{1,150}", job_id):
            recorder = Recorder(workspace, job_id, action_id, thread_id)
    except Exception:
        pass
    token = _active.set(recorder)
    preparation_token = _preparation.set(None)
    failure = None
    try:
        yield recorder if recorder is not None else _Disabled()
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        try:
            if recorder is not None:
                recorder.finish(failure)
        except Exception:
            pass
        _preparation.reset(preparation_token)
        _active.reset(token)


def phase(name, **metadata):
    try:
        recorder = _current()
        return recorder.begin(name, **metadata) if recorder else _Span()
    except Exception:
        return _Span()


def finish_preparation():
    span = _preparation.get()
    if span is not None and span.recorder is _current():
        span.finish()


def measured(name, *, preparation=None):
    """Decorate a synchronous seam; optional preparation ends at an explicit marker."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            recorder = _current()
            if recorder is None:
                return function(*args, **kwargs)
            previous_generation = recorder.current_generation
            with phase(name):
                prep = phase(preparation) if preparation else None
                token = _preparation.set(prep) if prep else None
                try:
                    return function(*args, **kwargs)
                finally:
                    if prep:
                        prep.finish()
                    if token is not None:
                        _preparation.reset(token)
                    recorder.current_generation = previous_generation
        return wrapped
    return decorate


def correlate_generation(generation=None):
    """Use an existing generation ID, or a diagnostic ID when recording is off."""
    try:
        recorder = _current()
        if recorder is None:
            return None
        ident = _identifier(getattr(generation, "generation_id", None)) or "timing-" + uuid4().hex
        recorder.current_generation = ident
        if ident not in recorder.generation_ids:
            if len(recorder.generation_ids) < MAX_GENERATIONS:
                recorder.generation_ids.append(ident)
            else:
                recorder.dropped_generations += 1
        if recorder.stack:
            recorder.stack[-1]["generation_id"] = ident
        recorder.checkpoint()
        return ident
    except Exception:
        return None


class _Attempt:
    def __init__(self, backend=None, model=None):
        self.recorder = _current()
        self.span = phase("provider.attempt", backend=backend, model=model)
        self.status = "empty"
        self.row = {"backend": _identifier(backend), "model": _identifier(model),
                    "generation_id": self.recorder.current_generation if self.recorder else None}

    def record_result(self, result):
        # The value is inspected only for emptiness, never retained or serialized.
        try:
            self.status = "ok" if isinstance(result, str) and str.strip(result) else "empty"
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if self.recorder:
                status = "error" if kind else self.status
                self.row["status"] = status
                if kind:
                    self.row["error_type"] = _identifier(kind.__name__) or "Exception"
                if self.span.row:
                    self.row["span_id"] = self.span.row["span_id"]
                self.recorder.attempt_counts[status] += 1
                if len(self.recorder.attempts) < MAX_ATTEMPTS:
                    self.recorder.attempts.append(self.row)
                else:
                    self.recorder.dropped_attempts += 1
        except Exception:
            pass
        self.span.__exit__(kind, value, traceback)
        try:
            if self.recorder and self.span.row is None:
                self.recorder.checkpoint()
        except Exception:
            pass
        return False


class _DisabledAttempt:
    def __enter__(self):
        return self

    def record_result(self, result):
        pass

    def __exit__(self, kind, value, traceback):
        return False


def provider_attempt(*, backend=None, model=None):
    try:
        return _Attempt(backend, model)
    except Exception:
        return _DisabledAttempt()
