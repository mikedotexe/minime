"""Explicit research admission against the native owner authority stream.

No generation or control calls live here. Reservations survive crashes, and a
started operation is never automatically replayed or refunded.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path
import threading
import time


RESEARCH_TRANSACTION_VERSION = 1
binding = ContextVar("explicit_research_binding", default=None)
executing = ContextVar("executing_research_reservation", default=None)
READ_ONLY_METADATA = frozenset({"THREADS", "THREAD_STATUS", "STATE", "FACULTIES", "ACTION_PREFLIGHT", "PREFLIGHT", "ACTION_CHECK"})
# These handlers inspect snapshots or render artifacts; their labels are data.
READ_ONLY_DIAGNOSTICS = frozenset({
    "DECOMPOSE", "SPECTRAL_EXPLORER", "VISUALIZE_CASCADE", "CASCADE", "EXAMINE_CASCADE",
    "PRESSURE_SOURCE_AUDIT", "PRESSURE_SOURCE", "STRUCTURAL_PRESSURE", "INWARD_PRESSURE",
    "FLUCTUATION_AUDIT", "INHABITABLE_FLUCTUATION", "EIGENTRUST", "EIGENTRUST_AUDIT", "FOOTHOLD_AUDIT",
    "RESONANCE_FORECAST", "FORECAST", "PROBABILITIES",
})


def literal_arguments(action):
    """These existing handlers consume text, not embedded NEXT commands."""
    words = str(action or "").split(None, 2)
    if not words:
        return False
    base = words[0].upper().rstrip(":")
    return base in {"SEARCH", "RESEARCH", "MIKE_SEARCH"} or (
        base == "SELF_STUDY" and len(words) > 1
        and words[1].upper() in {"FIND", "RELATE", "QUESTION", "NEW", "HELP"}
    )


def ordinary_exploration(store, action):
    base = store.base_action(action)
    return base in (store._research_budget_allowed_bases()
        | store._research_budget_projection_only_bases()
        | store._research_budget_local_selfmap_bases() | READ_ONLY_METADATA | READ_ONLY_DIAGNOSTICS
        | {"RESEARCH", "DECOMPOSE", "SELF_STUDY", "OPEN", "JOURNAL", "WRITE",
           "CREATE", "FORM", "DAYDREAM", "ASPIRE", "NOTICE", "CONTEMPLATE", "BE", "STILL",
           "EXPERIMENT_START", "EXPERIMENT_BRANCH", "EXPERIMENT_RESUME", "EXPERIMENT_COMPARE",
           "EXPERIMENT_REVIEW", "EXPERIMENT_STATUS", "ACTION_STATUS", "JOB_STATUS", "MAILBOX_STATUS"})


def validate_action_shape(store, action):
    """An exemption is for one known route, not a prefix hiding another action."""
    base = store.base_action(action)
    if not base or any(char in action for char in "\r\n\x00"):
        raise ValueError("research action must be one bounded command")
    if base in READ_ONLY_METADATA:
        return  # Inspection arguments are data; the route cannot dispatch them.
    if literal_arguments(action):
        return
    for match in re.finditer(r"\bAND\s+([A-Za-z][A-Za-z0-9_]*)", action, re.IGNORECASE):
        token = match.group(1).upper()
        if len(token) >= 5 and "_" in token:
            raise ValueError("compound research requires separately bound actions")
    if base == "INTROSPECT" and len(action.split()) > 1:
        # Actual target/path authorization remains with the source/artifact reader.
        import shlex
        args = shlex.split(action)[1:]
        if len(args) > 2 or not args or args[0].upper() in {"AND", "OR"} or (len(args) == 2 and not args[1].isdigit()):
            raise ValueError("unresolved introspection target; use explicit source navigation")


def is_metered(store, action):
    validate_action_shape(store, action)
    base = store.base_action(action)
    if base in READ_ONLY_METADATA:
        return False
    if base in {"OPEN", "SELF_STUDY"}:
        from .source_study import StudyClient
        try:
            canonical = StudyClient(store.workspace_dir.parent, store.workspace_dir).research_source_route(action)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            raise ValueError("shared research source routing unavailable") from exc
        if canonical is None:
            raise ValueError("bound source operation is not verified navigation; inspect source help")
        return True
    if store._live_control_binding_key(action) or base in store._research_budget_mutating_bases():
        return False  # Existing mutation/control gates remain authoritative.
    if base in store._research_budget_allowed_bases() | store._research_budget_projection_only_bases():
        return True
    raise ValueError("bound action is not a verified read-only route")
_held = threading.local()


@contextmanager
def transaction(root):
    root = Path(root).resolve()
    held = getattr(_held, "paths", {})
    if root in held:
        yield
        return
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".research-transaction.lock"
    if path.is_symlink():
        raise ValueError("research transaction lock is a symlink")
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        held[root] = handle
        _held.paths = held
        try:
            yield
        finally:
            del held[root]
            fcntl.flock(handle, fcntl.LOCK_UN)


def locked(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with transaction(self.root):
            return method(self, *args, **kwargs)
    return invoke


def record_id(owner, kind):
    return f"resbud_{owner}_{secrets.token_hex(16)}_{kind}"


def _unique_state_fields(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate research state field; state preserved")
        value[key] = item
    return value


def require_capability(store):
    """Durable release-guard input; old adapters cannot enforce this themselves."""
    if store.root.is_symlink():
        raise ValueError("research capability directory is a symlink")
    path = store.root / "research-transactions-required.json"
    payload = {"schema_version": 1, "owner": store.system,
               "required_research_transaction_version": RESEARCH_TRANSACTION_VERSION}
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
            raise ValueError("invalid research capability requirement preserved")
        with path.open("rb") as handle:
            raw = handle.read(4097)
            value = json.loads(raw, object_pairs_hook=_unique_state_fields)
            if (len(raw) > 4096 or not isinstance(value, dict) or set(value) != set(payload)
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or value["owner"] != store.system
                    or type(value["required_research_transaction_version"]) is not int
                    or value["required_research_transaction_version"] != RESEARCH_TRANSACTION_VERSION):
                raise ValueError("unsupported research capability requirement preserved")
            # A valid file left after failed fsync is not yet durable admission.
            os.fsync(handle.fileno())
    else:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
            handle.write(json.dumps(payload, sort_keys=True).encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    for directory in (store.root, store.root.parent):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def rows(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("research history is a symlink")
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError("research history is not a regular file")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete research history preserved")
    result = [json.loads(line, object_pairs_hook=_unique_state_fields) for line in raw.splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in result):
        raise ValueError("invalid research history preserved")
    if any(type(row.get("research_transaction_version", 1)) is not int
           or row.get("research_transaction_version", 1) != 1 for row in result):
        raise ValueError("unsupported research transaction history preserved")
    return result


def append(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows(path)
    with path.open("ab") as handle:
        handle.write(json.dumps(row, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def latest_operations(history, budget_id):
    latest = {}
    for row in history:
        if row.get("budget_id") == budget_id and row.get("research_transaction_version") == 1:
            operation = row.get("operation_id")
            if operation:
                latest[operation] = row
    return latest


def reserved_count(history, budget_id):
    return sum(row.get("lifecycle") in {"admitted", "queued"} for row in latest_operations(history, budget_id).values())


def active_budget(history, experiment_id, now=None):
    now = time.time() if now is None else now
    seen = set()
    for approval in reversed(history):
        if approval.get("record_type") != "research_budget_approval":
            continue
        budget_id = approval.get("budget_id")
        if budget_id in seen:
            continue
        seen.add(budget_id)
        if approval.get("experiment_id") != experiment_id:
            continue
        if not budget_id or approval.get("scope") != "read_only_research" or approval.get("status", "active") != "active":
            continue
        expiry = approval.get("expires_at_unix_s")
        if isinstance(expiry, bool) or not isinstance(expiry, (float, int)) or not math.isfinite(expiry) or expiry <= now:
            continue
        related = [row for row in history if row.get("budget_id") == budget_id]
        if any(row.get("record_type") == "research_budget_closed" or
               (row.get("record_type") == "research_budget_review" and row.get("outcome") == "close") for row in related):
            continue
        reviews = [row for row in related if row.get("record_type") == "research_budget_review"]
        if reviews and reviews[-1].get("outcome") in {"hold", "close"}:
            continue
        spent = sum(row.get("record_type") == "research_budget_debit" for row in related)
        reserved = reserved_count(history, budget_id)
        maximum = approval.get("max_actions")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            continue
        remaining = maximum - spent - reserved
        if remaining > 0:
            return {**approval, "spent_actions": spent, "reserved_actions": reserved, "remaining_actions": remaining}
    return None


def permission(history, budget_id, target, action):
    used = {row.get("retry_permission_id") for row in history if row.get("record_type") == "research_budget_reservation"}
    return next((row for row in reversed(history)
                 if row.get("record_type") == "research_budget_review"
                 and row.get("budget_id") == budget_id and row.get("outcome") == "continue"
                 and row.get("retry_of") and row.get("retry_target") == target
                 and row.get("retry_action") == action
                 and row.get("record_id") not in used), None)


def retry_fields(history, budget_id, outcome, retry_of):
    if not retry_of:
        return {}
    if outcome != "continue":
        raise ValueError("retry_of requires outcome continue")
    blocked = next((row for row in history if row.get("record_id") == retry_of
                    and row.get("budget_id") == budget_id
                    and row.get("record_type") == "research_budget_blocked"
                    and row.get("reason") == "duplicate_query_or_url_review_required"), None)
    if blocked is None or not blocked.get("normalized_target") or not blocked.get("raw_action"):
        raise ValueError("retry_of must name an exact local duplicate-target blocked record")
    if any(row.get("retry_of") == retry_of for row in history):
        raise ValueError("this blocked record already has a retry review")
    active = active_budget(history, blocked.get("experiment_id"))
    if active is None or active.get("budget_id") != budget_id:
        raise ValueError("retry cannot revive a held, closed, expired or exhausted allowance")
    if any(blocked.get(key) != active.get(key) for key in ("being", "thread_id", "experiment_id")):
        raise ValueError("blocked record owner or experiment differs from allowance")
    return {"retry_of": retry_of, "retry_target": blocked["normalized_target"],
            "retry_action": blocked["raw_action"], "retry_limit": 1,
            "next_safe_command": f"EXPERIMENT_BIND {blocked['experiment_id']} :: {blocked['raw_action']}"}


def strict_experiment(store, thread_id, experiment_id):
    """Read the pinned owner history without projection repair or UI selection."""
    if not isinstance(thread_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", thread_id):
        raise ValueError("invalid experiment thread identity")
    if not isinstance(experiment_id, str) or not experiment_id.startswith(f"exp_{store.system}_"):
        raise ValueError("experiment owner mismatch")
    thread_dir = store._thread_dir(thread_id)
    thread_path = thread_dir / "thread.json"
    if any(path.is_symlink() for path in (store.root, store.root / "threads", thread_dir, thread_path)):
        raise ValueError("experiment owner history is a symlink")
    if not thread_path.is_file():
        raise ValueError("missing experiment owner thread")
    thread = json.loads(thread_path.read_bytes(), object_pairs_hook=_unique_state_fields)
    if (not isinstance(thread, dict) or type(thread.get("schema_version")) is not int
            or thread["schema_version"] != store.schema_version or thread.get("thread_id") != thread_id
            or thread.get("system_origin") != store.system):
        raise ValueError("experiment thread identity, owner or schema mismatch")
    selected = None
    for record in rows(store._experiments_path(thread_id)):
        identity = record.get("experiment_id")
        if (type(record.get("schema_version")) is not int or record["schema_version"] != store.schema_version
                or record.get("thread_id") != thread_id or not isinstance(identity, str)
                or not identity.startswith(f"exp_{store.system}_")
                or not isinstance(record.get("status"), str) or not record["status"]):
            raise ValueError("experiment history identity, owner, status or schema mismatch")
        if identity == experiment_id:
            selected = record
    if selected is None:
        raise ValueError("missing exact experiment in owner history")
    return thread, selected


def inspect(store, experiment_id, action):
    """Called under the owner transaction; no selection or inferred binding."""
    if not is_metered(store, action):
        raise ValueError("metadata route does not consume research allowance")
    pinned = store.resolve_experiment_bind_target(experiment_id)
    index = json.loads((store.root / "index.json").read_text())
    thread_id = index.get("active_thread_id")
    thread, experiment = strict_experiment(store, thread_id, pinned)
    if experiment.get("status") in {"refused", "paused", "held", "hold", "closed", "complete", "completed", "abandoned"}:
        raise ValueError("experiment is not available for bound execution")
    history = rows(store._authority_gate_path(thread_id))
    budget = active_budget(history, pinned)
    if budget is None:
        raise ValueError("no active allowance for this exact experiment")
    if budget.get("being") != store.system or budget.get("thread_id") != thread_id:
        raise ValueError("allowance owner or thread mismatch")
    base = store.base_action(action)
    # is_metered above includes the shared Rust source-navigation decision.
    if store._live_control_binding_key(action):
        raise ValueError("research allowance does not authorize control-shaped intent")
    validate_source_scope(store, budget, action)
    return thread, experiment, history, budget


def validate_source_scope(store, budget, action):
    base = store.base_action(action)
    sources = budget.get("allowed_sources")
    if not isinstance(sources, list) or not sources or any(source not in {"web", "local"} for source in sources):
        raise ValueError("allowance source scope is missing or unsupported")
    required = {"web"} if base in {"SEARCH", "RESEARCH", "BROWSE"} else {"local"}
    if base == "READ_MORE":
        # The stored bookmark can select either kind at execution. Without a
        # frozen source attestation, require both rather than guessing its scope.
        required = {"web", "local"}
    if not required.issubset(sources):
        raise ValueError("action source is outside the exact allowance")


def repeat_count(history, budget_id, target):
    pending = latest_operations(history, budget_id)
    return sum(row.get("budget_id") == budget_id and row.get("normalized_target") == target
               and (row.get("record_type") == "research_budget_debit" or
                    (row.get("record_type") == "research_budget_reservation" and
                     pending.get(row.get("operation_id"), {}).get("lifecycle") in {"admitted", "queued"}))
               for row in history)


def admit(store, experiment_id, action, operation_id, state, *, canonical_action=None):
    if not operation_id or len(operation_id) > 256:
        raise ValueError("research admission requires a bounded durable operation id")
    with transaction(store.root):
        effective = canonical_action or action
        thread, experiment, history, budget = inspect(store, experiment_id, effective)
        digest = hashlib.sha256(json.dumps([action, effective], ensure_ascii=False).encode()).hexdigest()
        old = [row for row in history if row.get("operation_id") == operation_id]
        if old:
            if old[-1].get("request_sha256") != digest or old[-1].get("experiment_id") != experiment_id:
                raise ValueError("conflicting research operation retry")
            raise ValueError("operation already admitted; inspect its receipt, never automatically replay")
        target = store._research_budget_normalized_target(action)
        record = store._research_budget_record("research_budget_reservation", budget["budget_id"], thread, experiment, state,
                    {"research_transaction_version": 1, "operation_id": operation_id,
                     "request_sha256": digest, "lifecycle": "admitted", "raw_action": action,
                     "canonical_action": effective,
                     "normalized_target": target, "repeat_policy": "counts_normally"})
        require_capability(store)
        store._append_jsonl(store._authority_gate_path(thread["thread_id"]), record)
        return record


def transition(store, reservation, lifecycle, state, *, job_id=None):
    if lifecycle not in {"queued", "execution_started", "completed", "failed", "blocked", "released_unstarted"}:
        raise ValueError("invalid research lifecycle")
    with transaction(store.root):
        path = store._authority_gate_path(reservation["thread_id"])
        history = rows(path)
        records = [row for row in history if row.get("operation_id") == reservation["operation_id"]]
        if not records or records[0] != reservation:
            raise ValueError("reservation identity mismatch")
        previous = records[-1]["lifecycle"]
        if previous == lifecycle:
            return records[-1]
        expected = {"admitted"} if lifecycle == "queued" else {"admitted", "queued"} if lifecycle in {"execution_started", "released_unstarted"} else {"execution_started"}
        if previous not in expected:
            raise ValueError("research operation cannot replay or refund an uncertain execution")
        if lifecycle == "execution_started":
            # Ignore only this reservation's hold on capacity, never another job.
            eligible = [row for row in history if row.get("operation_id") != reservation["operation_id"]]
            active = active_budget(eligible, reservation["experiment_id"])
            if active is None or active.get("budget_id") != reservation["budget_id"]:
                raise ValueError("allowance expired or changed before execution")
            if any(active.get(key) != reservation.get(key) for key in ("being", "thread_id", "experiment_id")):
                raise ValueError("allowance identity changed before execution")
            validate_source_scope(store, active, reservation.get("canonical_action", reservation["raw_action"]))
            if reservation.get("being") != store.system:
                raise ValueError("reservation owner mismatch before execution")
            _, experiment = strict_experiment(store, reservation["thread_id"], reservation["experiment_id"])
            if experiment.get("status") in {"refused", "paused", "held", "hold", "closed", "complete", "completed", "abandoned"}:
                raise ValueError("experiment held before execution")
        record = {**reservation, "record_id": f"{reservation['record_id']}:{lifecycle}",
                  "record_type": "research_budget_debit" if lifecycle == "execution_started" else "research_budget_lifecycle",
                  "lifecycle": lifecycle, "recorded_at_unix_s": time.time(),
                  "execution_scope": "action_worker", "input_delivered": "unknown",
                  "job_id": job_id or records[-1].get("job_id")}
        store._append_jsonl(path, record)
        return record


def current_operation(store, ticket):
    history = rows(store._authority_gate_path(ticket["thread_id"]))
    records = [row for row in history if row.get("operation_id") == ticket["operation_id"]]
    if not records or records[0] != ticket:
        raise ValueError("canonical reservation identity mismatch")
    return records[-1]


def execute_bound_action(method):
    """Transfer a canonical admission across the existing job/thread boundary."""
    @wraps(method)
    def invoke(agent, action, state, **kwargs):
        context = kwargs.get("_precreated_continuity_context") or getattr(agent, "_pending_action_continuity_context", None) or {}
        ticket = context.get("research_reservation_v1")
        if not isinstance(ticket, dict):
            return method(agent, action, state, **kwargs)
        store = agent._continuity_store()
        if context.get("raw_next") != ticket.get("raw_action"):
            raise ValueError("bound worker action identity changed")
        if context.get("canonical_action", context.get("raw_next")) != ticket.get("canonical_action", ticket.get("raw_action")):
            raise ValueError("bound worker effective route changed")
        queueing = not kwargs.get("_from_llm_job") and getattr(agent, "running", False) and action in agent.LLM_JOB_ACTIONS
        if queueing:
            result = method(agent, action, state, **kwargs)
            with transaction(store.root):
                if current_operation(store, ticket)["lifecycle"] == "admitted":
                    # The queue call returned without accepting a job. A crash
                    # instead leaves the reservation held, never silently freed.
                    transition(store, ticket, "released_unstarted", state)
            return result
        with transaction(store.root):
            if current_operation(store, ticket)["lifecycle"] not in {"admitted", "queued"}:
                raise ValueError("research execution already started or uncertain; inspect, do not replay")
            transition(store, ticket, "execution_started", state)
        token = binding.set(ticket["experiment_id"])
        execution_token = executing.set(ticket)
        terminal = "failed"
        try:
            result = method(agent, action, state, **kwargs)
            from . import job_outcome
            captured = job_outcome.current()
            event = getattr(agent, "_last_action_continuity_event", None) or {}
            status = captured.finish()[0] if captured else event.get("status", "unknown")
            terminal = "completed" if status in {"completed", "handled"} else "blocked" if status in {"blocked", "denied", "skipped", "canceled"} else "failed"
            return result
        finally:
            try:
                transition(store, ticket, terminal, state)
            finally:
                executing.reset(execution_token)
                binding.reset(token)
    return invoke
