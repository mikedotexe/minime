"""Bounded, fail-closed reads of continuity evidence without runtime refreshes."""

import hashlib
import json
import os
import stat
from pathlib import Path


MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ROWS = 20000
MAX_THREADS = 256


class EvidenceUnavailable(ValueError):
    """Evidence cannot be presented as a stable readable snapshot."""


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceUnavailable("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise EvidenceUnavailable("non-finite JSON value")


def _decode(data):
    try:
        return json.loads(data, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EvidenceUnavailable("malformed JSON evidence") from exc


class StableSnapshot:
    """Check source identities both during each read and after the complete read set."""

    def __init__(self):
        self.sources = {}
        self.contents = {}
        self.total_bytes = 0

    def _track(self, path):
        try:
            fingerprint = _fingerprint(path.lstat())
        except OSError as exc:
            raise EvidenceUnavailable(f"missing or unreadable {path.name}") from exc
        prior = self.sources.setdefault(path, fingerprint)
        if prior != fingerprint:
            raise EvidenceUnavailable(f"changing evidence: {path.name}")
        return fingerprint

    def read(self, path):
        path = Path(path)
        before = self._track(path)
        if not stat.S_ISREG(before[2]):
            raise EvidenceUnavailable(f"not a regular evidence file: {path.name}")
        extra_bytes = 0 if path in self.contents else before[3]
        if before[3] > MAX_FILE_BYTES or self.total_bytes + extra_bytes > MAX_TOTAL_BYTES:
            raise EvidenceUnavailable("evidence exceeds bounded read limit")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as source:
                if _fingerprint(os.fstat(source.fileno())) != before:
                    raise EvidenceUnavailable(f"changing evidence: {path.name}")
                data = source.read(MAX_FILE_BYTES + 1)
                if _fingerprint(os.fstat(source.fileno())) != before:
                    raise EvidenceUnavailable(f"changing evidence: {path.name}")
        except OSError as exc:
            raise EvidenceUnavailable(f"unreadable {path.name}") from exc
        if len(data) != before[3]:
            raise EvidenceUnavailable(f"changing evidence: {path.name}")
        if path in self.contents and self.contents[path] != data:
            raise EvidenceUnavailable(f"changing evidence: {path.name}")
        self.total_bytes += extra_bytes
        self.contents[path] = data
        self._track(path)
        return data

    def json(self, path):
        value = _decode(self.read(path))
        if not isinstance(value, dict):
            raise EvidenceUnavailable(f"malformed object: {Path(path).name}")
        return value

    def jsonl(self, path):
        data = self.read(path)
        lines = data.splitlines()
        if len(lines) > MAX_ROWS:
            raise EvidenceUnavailable("evidence exceeds bounded row limit")
        rows = [_decode(line) for line in lines if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise EvidenceUnavailable(f"malformed record: {Path(path).name}")
        return rows, data

    def thread_dirs(self, root):
        root = Path(root)
        self.directory(root)
        try:
            with os.scandir(root) as entries:
                paths = []
                for entry in entries:
                    if len(paths) >= MAX_THREADS:
                        raise EvidenceUnavailable("thread discovery exceeds bounded limit")
                    if not entry.is_dir(follow_symlinks=False):
                        raise EvidenceUnavailable("unexpected thread directory entry")
                    paths.append(Path(entry.path))
        except OSError as exc:
            raise EvidenceUnavailable("thread directory unreadable") from exc
        return sorted(paths)

    def directory(self, path):
        if not stat.S_ISDIR(self._track(Path(path))[2]):
            raise EvidenceUnavailable("thread directory unavailable")

    def verify(self):
        for path in list(self.contents):
            self.read(path)
        for path in list(self.sources):
            self._track(path)


def valid_identifier(value):
    return (isinstance(value, str) and bool(value) and value not in {".", ".."}
            and all(c.isascii() and (c.isalnum() or c in "_-.") for c in value))


def validate_thread(thread, thread_id, owner):
    if (thread.get("thread_id") != thread_id or not valid_identifier(thread_id)
            or thread.get("system_origin") != owner
            or type(thread.get("schema_version")) is not int or thread["schema_version"] != 1
            or any(not isinstance(thread.get(key), str) for key in
                   ("title", "status", "created_at", "updated_at"))
            or any(thread.get(key) is not None and not isinstance(thread[key], str)
                   for key in ("current_next", "active_experiment_id"))):
        raise EvidenceUnavailable("malformed thread or identity/owner mismatch")
    for key in ("experiment_summary", "motif_allowance_v1"):
        if thread.get(key) is not None and not isinstance(thread[key], dict):
            raise EvidenceUnavailable(f"malformed thread {key}")
    return thread


def validate_experiment(record, thread_id):
    required_text = ("experiment_id", "thread_id", "title", "question", "status",
                     "authority_envelope", "created_at", "updated_at")
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or any(not isinstance(record.get(key), str) for key in required_text)
            or not valid_identifier(record.get("experiment_id"))
            or record.get("thread_id") != thread_id
            or not record.get("status")):
        raise EvidenceUnavailable("malformed experiment record")
    for key in ("planned_next", "hypothesis", "success_observation", "parent_experiment_id",
                "primary_return_next", "resume_next"):
        if record.get(key) is not None and not isinstance(record[key], str):
            raise EvidenceUnavailable(f"malformed experiment {key}")
    for key in ("peer_review_refs", "branch_refs"):
        value = record.get(key, [] if key == "branch_refs" else None)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise EvidenceUnavailable(f"malformed experiment {key}")
    for key in ("motif_allowance_v1", "charter_v1", "evidence_v1", "workbench_candidates_v1"):
        if record.get(key) is not None and not isinstance(record[key], dict):
            raise EvidenceUnavailable(f"malformed experiment {key}")
    return record


def exact_experiment(snapshot, path, reference):
    rows, data = snapshot.jsonl(path)
    found = None
    for row in rows:
        validate_experiment(row, Path(path).parent.name)
        if row["experiment_id"] == reference:
            found = row
    if found is None:
        raise EvidenceUnavailable("referenced experiment missing")
    return found, data


def digest_sources(*sources):
    digest = hashlib.sha256()
    for data in sources:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return "sha256:" + digest.hexdigest()
