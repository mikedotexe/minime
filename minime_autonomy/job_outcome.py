"""Worker-owned action evidence, independent of shared runtime scratch fields."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import threading


_current = ContextVar("minime_job_outcome", default=None)


class ActionOutcome:
    def __init__(self, action_id):
        self.action_id = action_id
        self.owner = threading.get_ident()
        self.event = None
        self.error = None
        self.summary = None
        self.artifacts = []
        self.queries = {"full": {"ok": 0, "empty": 0}, "compact": {"ok": 0, "empty": 0}}

    def matches(self, event):
        return isinstance(event, dict) and event.get("action_id") == self.action_id

    def finish(self):
        event = self.event or {}
        artifacts = list(event.get("artifacts") or [])
        for artifact in self.artifacts:
            if artifact not in artifacts:
                artifacts.append(artifact)
        summary = self.summary or event.get("outcome_summary") or "Action finalization was not confirmed."
        error = self.error
        raw_status = str(event.get("status") or "").lower()
        if error or raw_status == "failed":
            status = "failed"
            error = error or "action_failed"
        elif raw_status in {"blocked", "canceled", "timeout", "thin_output"}:
            status = raw_status
        elif not self.event:
            status, error = "failed", "action_finalization_unconfirmed"
        elif any(a.get("kind") == "thin_introspection_output" for a in artifacts if isinstance(a, dict)):
            status = "thin_output"
        elif self.queries["full"]["empty"] and not self.queries["full"]["ok"]:
            status, error = "failed", "no_model_output"
            summary = "Action returned, but its full model queries produced no usable output."
        else:
            status = "completed"
        return status, summary, error, artifacts


def current():
    outcome = _current.get()
    return outcome if outcome and outcome.owner == threading.get_ident() else None


@contextmanager
def capture(action_id):
    outcome = ActionOutcome(action_id)
    token = _current.set(outcome)
    try:
        yield outcome
    finally:
        _current.reset(token)


def fail_action(error, summary):
    outcome = current()
    if outcome:
        outcome.error = str(error)
        outcome.summary = str(summary)


def finalizer(fn):
    @wraps(fn)
    def wrapped(self, event, status, outcome_summary, post_state, artifacts=None):
        outcome = current()
        owned = outcome is not None and outcome.matches(event)
        if owned:
            outcome.artifacts.extend(artifacts or [])
        try:
            result = fn(self, event, status, outcome_summary, post_state, artifacts=artifacts)
        except Exception:
            if owned:
                fail_action("continuity_finalization_failed", "Action continuity finalization failed; saved artifacts remain recorded.")
            raise
        if owned:
            outcome.event = dict(result)
        return result
    return wrapped


def query(kind):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            result = fn(*args, **kwargs)
            outcome = current()
            if outcome:
                outcome.queries[kind]["ok" if isinstance(result, str) and result.strip() else "empty"] += 1
            return result
        return wrapped
    return decorate


def journal_write(fn):
    @wraps(fn)
    def wrapped(self, entry_type, content, state, file_path, **kwargs):
        try:
            return fn(self, entry_type, content, state, file_path, **kwargs)
        finally:
            outcome = current()
            if outcome and file_path:
                # The caller creates the journal before running registration hooks.
                # Preserve that evidence even if a later hook fails.
                try:
                    if Path(file_path).is_file():
                        outcome.artifacts.append({"kind": "journal", "path_or_uri": str(file_path), "entry_type": entry_type})
                except OSError:
                    pass
    return wrapped
