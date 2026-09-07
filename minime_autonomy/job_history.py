"""Bounded, change-aware metadata views of the authoritative job files.

Every snapshot enumerates and stats the files; there is no expiry window or
persisted index to go stale. Only unchanged compact metadata is reused. Readers
needing complete jobs read the selected authoritative paths again.
"""

import hashlib
import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


_FIELDS = (
    "created_at", "job_id", "action_id", "thread_id", "status", "worker_status",
    "worker_pid", "completed_at", "finished_at", "priority", "job_key", "error",
    "summary", "deadline_exceeded_at", "deadline_at", "started_at",
)
_MAX_ROOTS = 8
_MAX_ENTRIES = 50_000
_MAX_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_CATALOGS = OrderedDict()
_LOCK = threading.RLock()


class JobHistoryChanged(OSError):
    """A job changed during observation; callers must retry, not assume idle."""


def _signature(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class Record:
    path: Path
    signature: tuple
    values: tuple
    outcome_status: object

    def metadata(self):
        result = dict(zip(_FIELDS, self.values))
        result["outcome"] = {"status": self.outcome_status} if self.outcome_status is not None else None
        return result


def _stable_read(path):
    for _ in range(2):
        try:
            with path.open("rb") as handle:
                before = _signature(os.fstat(handle.fileno()))
                raw = handle.read()
                after = _signature(os.fstat(handle.fileno()))
            current = _signature(path.stat())
        except FileNotFoundError:
            continue
        if before != after or after != current:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            value = None
        return current, value if isinstance(value, dict) else None
    raise JobHistoryChanged(f"Job changed while reading: {path}")


def _record(path, signature, value):
    if value is None:
        return None
    # Keep values immutable without caching arbitrary payloads. The persisted
    # schema uses scalar values for these fields; malformed composite fields
    # cannot safely participate in the metadata view.
    def scalar(item):
        return item if isinstance(item, (str, int, float, bool, type(None))) else None
    outcome = value.get("outcome")
    return Record(path, signature, tuple(scalar(value.get(key)) for key in _FIELDS),
                  scalar(outcome.get("status")) if isinstance(outcome, dict) else None)


def _job_paths(root):
    # Path.glob suppresses directory access errors on recent Python versions.
    # Such an error must not turn an unreadable active history into an empty one.
    try:
        scan = os.scandir(root)
    except FileNotFoundError:
        return
    with scan:
        for entry in scan:
            if entry.is_dir():
                yield root / entry.name / "job.json"


def metadata_snapshot(jobs_dir):
    """Return immutable records in filesystem order, including all valid jobs."""
    root = Path(jobs_dir).resolve()
    with _LOCK:
        previous = _CATALOGS.pop(root, {})
        current = {}
        records = []
        cached_bytes = 0
        for path in _job_paths(root):
            try:
                signature = _signature(path.stat())
            except FileNotFoundError:
                # A directory may exist before its first job.json is committed.
                # Files disappearing after this stat are rejected by stable_read.
                continue
            cached = previous.get(path)
            if cached is not None and cached[0] == signature:
                _, record, cost = cached
            else:
                signature, value = _stable_read(path)
                record = _record(path, signature, value)
                cost = 256 + len(str(path)) * 4
                if record is not None:
                    cost += sum(len(item) * 4 if isinstance(item, str) else 32 for item in record.values)
                    if isinstance(record.outcome_status, str):
                        cost += len(record.outcome_status) * 4
            if record is not None:
                records.append(record)
            if len(current) < _MAX_ENTRIES and cached_bytes + cost <= _MAX_BYTES:
                current[path] = (signature, record, cost)
                cached_bytes += cost
        _CATALOGS[root] = current
        total_bytes = sum(item[2] for entries in _CATALOGS.values() for item in entries.values())
        while len(_CATALOGS) > _MAX_ROOTS or total_bytes > _MAX_TOTAL_BYTES:
            _, removed = _CATALOGS.popitem(last=False)
            total_bytes -= sum(item[2] for item in removed.values())
        return tuple(records)


def recent_jobs(jobs_dir, limit):
    """Read full selected jobs. Store callers hold their existing process lock."""
    for _ in range(2):
        records = sorted(metadata_snapshot(jobs_dir), key=lambda item: item.values[0] or "")[-limit:]
        result = []
        for record in records:
            signature, value = _stable_read(record.path)
            if signature != record.signature or value is None:
                break
            result.append(value)
        else:
            return result
    raise JobHistoryChanged("Selected jobs changed during snapshot")


def fingerprint_for_actions(jobs_dir, action_ids):
    """Include replacement/rewrite identity, even when size and mtime match."""
    relevant = [record for record in (metadata_snapshot(jobs_dir) if action_ids else ())
                if record.values[2] in action_ids]
    digest = hashlib.sha256()
    for record in sorted(relevant, key=lambda item: str(item.path)):
        digest.update(json.dumps((str(record.path), record.signature), ensure_ascii=True).encode())
        digest.update(b"\n")
    return {
        "mtime_ns": max((record.signature[3] for record in relevant), default=0),
        "size": sum(record.signature[2] for record in relevant),
        "signature_digest": int.from_bytes(digest.digest(), "big"),
    }
