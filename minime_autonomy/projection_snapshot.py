"""Operation-local read observations for the next.md projection handoff.

Readers still execute normally. Their decorators observe identities, not values,
and do nothing outside the SECOND projection of a write/refresh operation. Any
failed/uncertain read, attempted side effect, identity change, or
changed temporal predicate disables reuse. No TTL, persistent cache, global I/O
hooks, or authority/admission result cache is installed.

The caller must retain the premutation projection, mutation, freshness receipt,
control-plane rebuild, thread write, next.md write, and DB/index receipts. Only
projection_for_next_md may consume the sealed result. Saved-thread return support
is revalidated after the intentional thread.json write, never assumed unchanged.

Qualified sources include populated clean journals and job metadata, events,
proposals, and the instrumented local ledgers. A successful optional-file absence
is tracked with its parent identity; a failed attempted read is never reusable.
Experiments, populated authority records, draft-age decisions, peer/shared reads,
and hygiene writers fall back. Running-action age uses the exact existing
predicate at capture and consumption, including backward-clock rejection.

This is optimistic verification, not a filesystem transaction: as with a fresh
projection, another writer can act after the final observation. Reader additions
require extending the audited instrumentation and its source-coverage test.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import json
import math
import os
from pathlib import Path
import stat
import threading

from .continuity_snapshot import StableSnapshot, validate_thread


_CURRENT = ContextVar("continuity_projection_reads", default=None)
MAX_IDENTITIES = 100_000
MAX_TEMPORAL_PREDICATES = 4096
OUTPUT_FIELDS = frozenset({
    "interpretation_risk_v1", "constraint_release_trajectory_v1",
    "repeated_action_cadence_v1", "thread_load_triage_v1",
    "projection_freshness_v1", "continuity_control_plane_v1",
})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _inputs(thread):
    return _json({key: value for key, value in thread.items() if key not in OUTPUT_FIELDS})


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return os.getpid(), threading.get_ident(), task


def _signature(info):
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("unsupported source type")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _identity(path):
    return _signature(os.lstat(path))


def _tree(root, depth):
    before = _identity(root)
    if not stat.S_ISDIR(before[2]):
        raise ValueError("discovery root is not a directory")
    rows = [(str(root), before)]
    with os.scandir(root) as entries:
        for entry in entries:
            identity = _signature(entry.stat(follow_symlinks=False))
            rows.append((entry.path, identity))
            if depth and stat.S_ISDIR(identity[2]):
                # Job discovery reads exactly this child, not other job artifacts.
                child = os.path.join(entry.path, "job.json")
                rows.append((child, _identity(child)))
            if len(rows) >= MAX_IDENTITIES:
                raise ValueError("observation bound exceeded")
    if before != _identity(root):
        raise ValueError("directory changed during discovery")
    # Preserve enumeration order: several existing readers use it to break ties.
    return tuple(rows)


def _configuration(store):
    def freeze(value):
        if callable(value) or isinstance(value, (staticmethod, classmethod)):
            return ("callable", id(value))
        if isinstance(value, Path):
            return ("path", str(value))
        if isinstance(value, (set, frozenset)):
            return ("set", _json(sorted(value)))
        return ("value", _json(value))

    return tuple(
        (kind, name, freeze(value))
        for kind, fields in (("class", vars(type(store))), ("instance", vars(store)))
        for name, value in sorted(fields.items()) if not name.startswith("__")
    )


class _Observation:
    def __init__(self, store, thread):
        self.store = store
        self.thread = thread
        self.owner = _owner()
        self.files = {}
        self.directories = {}
        self.parents = {}
        self.receipt_files = {}
        self.returns = []
        self.predicates = []
        self.failures = set()

    def fail(self, reason):
        self.failures.add(reason)

    def _path(self, path):
        path = Path(path)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("noncanonical observation path")
        for parent in path.parents:
            identity = _identity(parent)
            if not stat.S_ISDIR(identity[2]):
                raise ValueError("non-directory ancestor")
            identity = identity[:3]
            if self.parents.setdefault(parent, identity) != identity:
                raise ValueError("ancestor changed")
        return path

    def record(self, path, *, depth=None, receipt=False, optional=False):
        if self.failures:
            return
        if self.owner != _owner():
            self.fail("different_execution_context")
        try:
            path = self._path(path)
            if depth is not None:
                if (path, depth) in self.directories:
                    return
                key, value, target = (path, depth), _tree(path, depth), self.directories
            else:
                key, value = path, _identity(path)
                if not stat.S_ISREG(value[2]):
                    raise ValueError("read source is not a regular file")
                target = self.receipt_files if receipt else self.files
            if len(self.files) + len(self.parents) + sum(len(v) for v in self.directories.values()) >= MAX_IDENTITIES:
                raise ValueError("observation bound exceeded")
            if target.setdefault(key, value) != value:
                self.fail("source_changed")
        except FileNotFoundError:
            try:
                if not optional or not path.parent.is_dir() or path.exists():
                    raise ValueError("required source missing")
                value = ("absent", _identity(path.parent))
                if self.files.setdefault(path, value) != value:
                    self.fail("source_changed")
            except (OSError, ValueError, TypeError):
                self.fail("source_unavailable")
        except (OSError, ValueError, TypeError, RecursionError):
            self.fail("source_unavailable")

    def verify(self, *, receipts=False):
        if self.owner != _owner():
            self.fail("different_execution_context")
        try:
            if receipts:
                # This source is about to be intentionally overwritten. Other
                # identities are checked once, at consumption, after that write.
                for path, identity in self.receipt_files.items():
                    if _identity(path) != identity:
                        self.fail("receipt_changed_before_write")
                return not self.failures
            for path, identity in self.parents.items():
                if _identity(path)[:3] != identity:
                    self.fail("ancestor_changed")
            for path, identity in self.files.items():
                if identity[0] == "absent":
                    if path.exists() or path.is_symlink() or _identity(path.parent) != identity[1]:
                        self.fail("absence_changed")
                elif _identity(path) != identity:
                    self.fail("source_changed")
            for (path, depth), identity in self.directories.items():
                if _tree(path, depth) != identity:
                    self.fail("discovery_changed")
            for predicate, observed, clock, result in self.predicates:
                current = clock()
                if current < observed or predicate(current) != result:
                    self.fail("temporal_validity_changed")
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            self.fail("verification_unavailable")
        return not self.failures


def uncertain(reason="read_failed"):
    """Call inside caught read/parse failures and before attempted reader writes."""
    observation = _CURRENT.get()
    if observation is not None:
        observation.fail(reason)


@contextmanager
def _reading(path, *, depth=None, receipt=False, optional=False):
    observation = _CURRENT.get()
    if observation is None or path is None:
        yield
        return
    observation.record(path, depth=depth, receipt=receipt, optional=optional)
    try:
        yield
    except BaseException:
        observation.fail("read_failed")
        raise
    finally:
        observation.record(path, depth=depth, receipt=receipt, optional=optional)


def file_reader(path_for, *, optional=False, unsupported_nonempty=False):
    """Observe a normal synchronous reader, including its existence branch."""
    def decorate(function):
        @wraps(function)
        def reader(*args, **kwargs):
            if _CURRENT.get() is None:
                return function(*args, **kwargs)
            with _reading(path_for(*args, **kwargs), optional=optional):
                result = function(*args, **kwargs)
                if unsupported_nonempty and result:
                    uncertain("unsupported_populated_dependency")
                return result
        return reader
    return decorate


def directory_reader(path_for, *, depth=0):
    """Observe membership, order and entry identities around directory readers."""
    def decorate(function):
        @wraps(function)
        def reader(*args, **kwargs):
            if _CURRENT.get() is None:
                return function(*args, **kwargs)
            with _reading(path_for(*args, **kwargs), depth=depth):
                return function(*args, **kwargs)
        return reader
    return decorate


def observed_jobs(root, records):
    """Reject metadata scans that omitted missing or malformed job records."""
    observation = _CURRENT.get()
    if observation is None:
        return
    tree = observation.directories.get((Path(root), 1))
    if tree is None:
        observation.fail("job_discovery_unobserved")
        return
    entries = dict(tree)
    root = str(root)
    expected = {
        os.path.join(path, "job.json") for path, signature in entries.items()
        if os.path.dirname(path) == root and stat.S_ISDIR(signature[2])
    }
    if expected != {str(record.path) for record in records}:
        observation.fail("incomplete_job_read")
    for record in records:
        identity = entries.get(str(record.path))
        if identity is None or record.signature != (*identity[:2], *identity[3:]):
            observation.fail("job_identity_changed")


def temporal(predicate, observed, clock):
    """Evaluate the existing predicate; retain its exact validity condition.

    Predicate closures must freeze their source values in default arguments.
    The clock callable resolves the same clock used by the existing reader.
    Backward clock movement or a changed predicate always recomputes.
    """
    result = predicate(observed)
    observation = _CURRENT.get()
    if observation is not None:
        if (len(observation.predicates) >= MAX_TEMPORAL_PREDICATES
                or (isinstance(observed, (int, float)) and not math.isfinite(observed))
                or (isinstance(observed, datetime) and observed.tzinfo is None)):
            observation.fail("uncertain_clock")
        else:
            observation.predicates.append((predicate, observed, clock, result))
    return result


def return_support_reader(function):
    """Observe saved support, keeping the intentional thread write explicit."""
    @wraps(function)
    def reader(store, thread, experiment_id=None, *, thread_id=None):
        observation = _CURRENT.get()
        if observation is None:
            return function(store, thread, experiment_id, thread_id=thread_id)
        actual_id = thread_id or thread["thread_id"]
        if store is not observation.store or actual_id != observation.thread["thread_id"]:
            observation.fail("foreign_return_receipt")
        directory = store._thread_dir(actual_id)
        with _reading(directory / "thread.json", receipt=True), _reading(directory / "experiments.jsonl"):
            result = function(store, thread, experiment_id, thread_id=thread_id)
        if not isinstance(result, dict) or result.get("record_status") == "unavailable":
            observation.fail("unavailable_return_support")
        else:
            observation.returns.append((experiment_id, _json(result)))
        return result
    return reader


class ProjectionReadScope:
    """One lexical operation, one observed postmutation projection, one render."""

    def __init__(self, store, thread):
        self.store, self.thread = store, thread
        self.observation = None
        self.active = False
        self.used = False
        self.payload = None

    def __enter__(self):
        if self.active or self.used:
            raise RuntimeError("projection read scope cannot be reentered")
        self.active = True
        self.owner = _owner()
        return self

    def __exit__(self, *exc):
        self.active = False
        self.used = True
        self.observation = self.payload = None
        self.projection = self.input = self.config = self.final_thread = None
        self.store = self.thread = None

    def project(self):
        if not self.active or self.used or self.observation is not None:
            self.used = True
            return self.store._thread_projection(self.thread)
        observation = self.observation = _Observation(self.store, self.thread)
        if self.thread.get("active_experiment_id") or self.thread.get("experiment_summary") is not None:
            observation.fail("experiment_profile_not_qualified")
            self.projection = self.store._thread_projection(self.thread)
            return self.projection
        try:
            self.input = _inputs(self.thread)
            self.config = _configuration(self.store)
        except (ValueError, TypeError, RecursionError):
            observation.fail("unknown_inputs")
        if _CURRENT.get() is not None:
            _CURRENT.get().fail("nested_projection")
            observation.fail("nested_projection")
        token = _CURRENT.set(observation)
        try:
            self.projection = self.store._thread_projection(self.thread)
            return self.projection
        finally:
            _CURRENT.reset(token)

    def seal(self, projection):
        observation = self.observation
        if not self.active or self.used or observation is None or self.payload is not None:
            self.used = True
            return
        try:
            if (observation.failures or projection is not self.projection
                    or _inputs(self.thread) != self.input or _configuration(self.store) != self.config
                    or any(key not in self.thread or self.thread[key] != projection.get(key) for key in OUTPUT_FIELDS)
                    or not observation.returns or not observation.verify(receipts=True)):
                self.used = True
                return
            self.payload = _json(projection)
            self.final_thread = _json(self.thread)
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            self.used = True

    def take(self, store, thread):
        ready = self.active and not self.used and self.payload is not None
        self.used = True
        if not ready or store is not self.store or thread is not self.thread or _owner() != self.owner:
            return None
        try:
            if (_json(thread) != self.final_thread or _json(self.projection) != self.payload
                    or _configuration(store) != self.config):
                return None
            receipt = StableSnapshot()
            path = store._thread_dir(thread["thread_id"]) / "thread.json"
            receipt.directory(path.parent)
            saved = receipt.json(path)
            validate_thread(saved, thread["thread_id"], store.system)
            if _json(saved) != self.final_thread:
                return None
            for reference, expected in self.observation.returns:
                if _json(store._return_support_v1(thread, reference)) != expected:
                    return None
            receipt.verify()
            if (_json(thread) != self.final_thread or _json(self.projection) != self.payload
                    or not self.observation.verify()):
                return None
            return json.loads(self.payload)
        except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            return None


def projection_for_next_md(store, thread, snapshot=None):
    projection = snapshot.take(store, thread) if isinstance(snapshot, ProjectionReadScope) else None
    return projection if projection is not None else store._thread_projection(thread)
