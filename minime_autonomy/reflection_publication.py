"""Reflection publication and local recovery, never inference or choice execution.

Native delivery, published writing and the NEXT queue remain distinct authorities.
Only a sealed public publication intent authorizes completing local writes.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import uuid4

from .mailbox_fs import Directory


LEGACY_SCHEMA = "minime_reflection_publication_v1"
SCHEMA = "minime_reflection_publication_v2"
REFLECTION_PUBLICATION_VERSION = 2
MAX_RECEIPT = 16 * 1024
MAX_PUBLICATION = 2 * 1024 * 1024
MAX_INTENT = MAX_PUBLICATION * 12 + MAX_RECEIPT
STAGES = {"reserved", "failed_unaccepted", "prepared", "published"}
LEGACY_STAGES = {"reserved", "failed_unaccepted", "accepted", "publishing", "published", "completed"}
NAVIGATION = ("diagnostics", "source_first_v3", "shared_reader", "navigation")


class RecoveryRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class FinalizationResult:
    accepted: bool | None
    publication: str
    indexing: str = "unknown"
    choice: str = "unknown"
    reason: str | None = None
    publication_id: str | None = None
    path: str | None = None
    diagnostics: str = "not_replayed"

    def status(self):
        """Operator facts only, never authored text or executable commands."""
        return {**asdict(self), "choice_scope": "at_publication_intent_not_current_queue"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate reflection receipt field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite reflection receipt")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("invalid reflection receipt")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid reflection evidence hash")
    return value


def _envelope(value):
    return _bytes({"record": value, "sha256": _sha(_bytes(value))})


def _record(raw):
    envelope = _json(raw)
    if set(envelope) != {"record", "sha256"} or _sha(_bytes(envelope["record"])) != envelope["sha256"]:
        raise ValueError("reflection receipt integrity failure")
    record = envelope["record"]
    if not isinstance(record, dict) or record.get("schema") not in {SCHEMA, LEGACY_SCHEMA}:
        raise ValueError("unsupported reflection publication schema")
    return record


def _child(root, parts):
    for part in parts:
        root = root.child(part)
    return root


class ReflectionPublication:
    def __init__(self, workspace, action_id, input_id):
        if not isinstance(action_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", action_id):
            raise ValueError("reflection requires a bounded action identity")
        self.workspace = Path(workspace)
        self.action_id, self.input_id = action_id, _hash(input_id)
        self.name = "action-" + _sha(action_id.encode("utf-8")) + ".json"
        self.index = "input-" + input_id + ".json"
        self.intent_name = "intent-" + _sha(action_id.encode("utf-8")) + ".json"
        self.binding = None
        self.completed = False
        self.result = None

    @contextmanager
    def _locked(self, *, create=False, readonly=False):
        with Directory(self.workspace) as root:
            data = root.child("runtime", create=create).child("reflection_publications", create=create)
            if not readonly:
                # Establish the empty lock exclusively; concurrent nonexclusive
                # O_CREAT|O_NOFOLLOW can fail on first creation on this host.
                if create:
                    try:
                        fd = os.open(".transaction.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL
                                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=data.fd)
                    except FileExistsError:
                        data.check()
                    else:
                        try:
                            os.fsync(fd)
                            data.sync()
                        finally:
                            os.close(fd)
                with data.lock(".transaction.lock"):
                    yield root, data
            else:
                # Inspection must not create a lock or repair a partial claim.
                fd = os.open(".transaction.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=data.fd)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise ValueError("invalid reflection lock")
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    if os.fstat(fd).st_ino != data.stat(".transaction.lock").st_ino:
                        raise ValueError("reflection lock changed")
                    yield root, data
                    data.check()
                finally:
                    os.close(fd)

    def _load(self, data):
        record = _record(data.read(self.name, MAX_RECEIPT))
        binding = record.get("binding")
        if (not isinstance(binding, dict) or set(binding) != {"owner", "action_id", "input_id", "nonce"}
                or binding.get("owner") != "minime" or binding.get("action_id") != self.action_id
                or binding.get("input_id") != self.input_id
                or not re.fullmatch(r"[0-9a-f]{32}", str(binding.get("nonce")))):
            raise ValueError("reflection publication identity conflict")
        if self.binding is not None and binding != self.binding:
            raise ValueError("reflection publication ownership changed")
        stage, legacy = record.get("stage"), record["schema"] == LEGACY_SCHEMA
        if not isinstance(stage, str) or stage not in (LEGACY_STAGES if legacy else STAGES):
            raise ValueError("unsupported reflection publication state")
        keys = {"schema", "binding", "stage"}
        if legacy:
            if stage not in {"reserved", "failed_unaccepted"}:
                keys.add("delivery")
            if stage in {"publishing", "published", "completed"}:
                keys.add("publication")
        elif stage in {"prepared", "published"}:
            keys.update({"intent_sha256", "indexing", "hooks"})
            _hash(record.get("intent_sha256"))
            if record.get("indexing") not in {"pending", "indexed"}:
                raise ValueError("invalid reflection index state")
            hooks = record.get("hooks")
            if (not isinstance(hooks, dict) or set(hooks) != {"before", "after"}
                    or any(v not in {"pending", "started", "done", "failed"} for v in hooks.values())):
                raise ValueError("invalid reflection diagnostic state")
        if set(record) != keys:
            raise ValueError("unsupported reflection publication state")
        expected_index = {"schema": record["schema"], "action_file": self.name, "binding_sha256": _sha(_bytes(binding))}
        if stage != "failed_unaccepted" and _record(data.read(self.index, MAX_RECEIPT)) != expected_index:
            raise ValueError("reflection input binding changed")
        return record

    def _save(self, data, record):
        raw = _envelope(record)
        if len(raw) > MAX_RECEIPT:
            raise ValueError("reflection receipt exceeds limit")
        data.atomic(self.name, raw, replace=True)

    @classmethod
    def begin(cls, workspace, action_id, input_id, *, database=None):
        operation = cls(workspace, action_id, input_id)
        with operation._locked(create=True) as (root, data):
            if data.exists(operation.name):
                record = operation._load(data)
                operation.binding = record["binding"]
                if record["schema"] == LEGACY_SCHEMA and record["stage"] == "completed":
                    operation._verify_delivery(root, record["delivery"])
                    path = operation._verify_publication(root, record["publication"])
                    operation.result = FinalizationResult(True, "published", reason="legacy_index_and_choice_unverified", path=str(path))
                elif record["schema"] == SCHEMA and data.exists(operation.intent_name):
                    operation.result = operation._reconcile(root, data, record, apply=True, database=database)
                else:
                    raise RecoveryRequired("reflection_publication_recovery_required:" + record["stage"]
                                           + "; no automatic generation or NEXT replay")
                operation.completed = True
                return operation
            replace_index = False
            if data.exists(operation.index):
                previous = _record(data.read(operation.index, MAX_RECEIPT))
                filename = previous.get("action_file")
                if not isinstance(filename, str) or not re.fullmatch(r"action-[0-9a-f]{64}\.json", filename):
                    raise ValueError("invalid previous reflection reservation")
                prior = _record(data.read(filename, MAX_RECEIPT))
                binding = prior.get("binding") or {}
                if not isinstance(binding, dict):
                    raise ValueError("invalid previous reflection binding")
                earlier = cls(workspace, binding.get("action_id"), input_id)
                if (earlier.name != filename or previous != {"schema": prior["schema"], "action_file": filename,
                        "binding_sha256": _sha(_bytes(binding))}
                        or earlier._load(data)["stage"] != "failed_unaccepted"):
                    raise RecoveryRequired("reflection_publication_input_already_reserved; no automatic replay")
                replace_index = True
            # Older accepted inputs have no guard receipt. Do not manufacture an
            # invocation for them or infer that missing host bookkeeping is safe.
            if operation._native_delivery_exists(root):
                raise RecoveryRequired("reflection_publication_legacy_delivery_requires_reconciliation")
            operation.binding = {"owner": "minime", "action_id": action_id, "input_id": input_id,
                                 "nonce": uuid4().hex}
            record = {"schema": SCHEMA, "binding": operation.binding, "stage": "reserved"}
            # If interrupted between these writes, the incomplete claim fails
            # closed. Provider submission only follows both durable writes.
            data.atomic(operation.name, _envelope(record))
            data.atomic(operation.index, _envelope({"schema": SCHEMA, "action_file": operation.name,
                        "binding_sha256": _sha(_bytes(operation.binding))}), replace=replace_index)
        return operation

    def _native_delivery_exists(self, root):
        try:
            existing = _child(root, NAVIGATION + (self.input_id,))
        except FileNotFoundError:
            root.check()
            return False
        return bool(existing.names())

    def failed_unaccepted(self):
        """Only the caller that observed a returned failure may release input use.

        A new action must still recheck native evidence. The old action cannot
        rerun, and a crash without this durable acknowledgement stays uncertain.
        """
        with self._locked() as (root, data):
            record = self._load(data)
            if record["schema"] != SCHEMA:
                raise RecoveryRequired("legacy receipt retained unchanged")
            if record["stage"] != "reserved" or self._native_delivery_exists(root):
                raise RecoveryRequired("reflection failure is not verified unaccepted; no replay")
            record["stage"] = "failed_unaccepted"
            self._save(data, record)

    def _verify_delivery(self, root, delivery):
        if not isinstance(delivery, dict) or set(delivery) != {"artifact_sha256", "request_sha256", "response_sha256"}:
            raise ValueError("invalid reflection delivery binding")
        for value in delivery.values():
            _hash(value)
        directory = _child(root, NAVIGATION + (self.input_id,))
        raw = directory.read(delivery["artifact_sha256"] + ".json", MAX_PUBLICATION)
        if _sha(raw) != delivery["artifact_sha256"]:
            raise ValueError("reflection delivery artifact changed")
        artifact = _json(raw)
        output = artifact.get("output") or {}
        if (artifact.get("schema") != "source_study_navigation_delivery_v1"
                or not isinstance(output, dict)
                or output.get("input_kind") != "reflection" or output.get("navigation_id") != self.input_id
                or not isinstance(artifact.get("request_json"), str)
                or not isinstance(artifact.get("response_json"), str)
                or _sha(artifact["request_json"].encode("utf-8")) != delivery["request_sha256"]
                or _sha(artifact["response_json"].encode("utf-8")) != delivery["response_sha256"]):
            raise ValueError("reflection delivery identity conflict")

    def _verify_publication(self, root, publication, *, missing_ok=False):
        if (not isinstance(publication, dict) or set(publication) != {"filename", "sha256"}
                or not isinstance(publication["filename"], str)
                or not re.fullmatch(r"introspect_[0-9T.-]+\.txt", publication["filename"])):
            raise ValueError("invalid reflection publication binding")
        expected = _hash(publication["sha256"])
        try:
            journal = root.child("journal")
        except FileNotFoundError:
            if missing_ok:
                return None
            raise
        found = []

        def check(directory):
            # Starred names are a supported operator rename, not different prose.
            for name in (publication["filename"], "!" + publication["filename"]):
                if directory.exists(name):
                    if _sha(directory.read(name, MAX_PUBLICATION)) != expected:
                        raise ValueError("reflection publication changed; preserved unchanged")
                    found.append(directory.path / name)

        check(journal)
        if journal.exists("archive"):
            archive = journal.child("archive")
            for name in sorted(archive.names()):
                if re.fullmatch(r"until_[0-9T-]+", name):
                    # Each child is closed promptly even in a long-lived archive.
                    with Directory(archive.path / name) as bucket:
                        check(bucket)
        if len(found) > 1:
            raise ValueError("ambiguous reflection publication locations")
        if not found and not missing_ok:
            raise FileNotFoundError("retained reflection publication missing; not recreated")
        return found[0] if found else None

    def finalize(self, receipt, *, filename, text, content, metadata, choice="unknown",
                 before_index=None, after_index=None):
        """Freeze after normal response handling; only this first call runs hooks."""
        if not isinstance(receipt, dict) or receipt.get("page_id") != self.input_id:
            raise ValueError("reflection publication requires verified input delivery")
        delivery = {key: receipt.get(key) for key in ("artifact_sha256", "request_sha256", "response_sha256")}
        with self._locked() as (root, data):
            record = self._load(data)
            if record["schema"] != SCHEMA or record["stage"] != "reserved" or data.exists(self.intent_name):
                raise RecoveryRequired("reflection already prepared; reconcile, never replay response handling")
            intent = {"schema": SCHEMA, "binding": record["binding"], "delivery": delivery,
                      "publication": {"filename": filename, "sha256": _sha(text.encode("utf-8"))},
                      "text": text, "content": content, "metadata": metadata, "choice": choice}
            self._validate_intent(root, intent, record)
            if self._verify_publication(root, intent["publication"], missing_ok=True) is not None:
                raise ValueError("reflection publication filename already exists; retained unchanged")
            raw = _envelope(intent)
            if len(raw) > MAX_INTENT:
                raise ValueError("reflection intent exceeds limit")
            data.atomic(self.intent_name, raw)
            # This sealed intent also recovers a lost prepared-receipt acknowledgement.
            record = self._prepared(record, _sha(raw))
            self._save(data, record)
            self.result = self._reconcile(root, data, record, apply=True,
                database=metadata["database"], before_index=before_index, after_index=after_index)
            self.completed = True
            return self.result

    def _prepared(self, record, digest):
        return {"schema": SCHEMA, "binding": record["binding"], "stage": "prepared",
                "intent_sha256": digest, "indexing": "pending",
                "hooks": {"before": "pending", "after": "pending"}}

    def _validate_intent(self, root, intent, record):
        if (set(intent) != {"schema", "binding", "delivery", "publication", "text", "content", "metadata", "choice"}
                or intent["schema"] != SCHEMA or intent["binding"] != record["binding"]):
            raise ValueError("reflection intent identity conflict")
        self._verify_delivery(root, intent["delivery"])
        text, content, metadata = intent["text"], intent["content"], intent["metadata"]
        if (not isinstance(text, str) or not isinstance(content, str) or not content
                or len(text.encode("utf-8")) > MAX_PUBLICATION
                or (text != content and not text.endswith(content + "\n"))
                or intent["publication"].get("sha256") != _sha(text.encode("utf-8"))
                or intent["choice"] not in {"recorded", "none", "unknown"}):
            raise ValueError("invalid frozen reflection content or choice disposition")
        if (not isinstance(metadata, dict) or set(metadata) - {"database", "session_id", "timestamp", "entry_type",
                "spectral_context", "implementation_sha256", "job_id"}
                or not {"database", "session_id", "timestamp", "entry_type", "spectral_context", "implementation_sha256"} <= metadata.keys()
                or metadata["entry_type"] != "introspect"
                or not isinstance(metadata["session_id"], int) or isinstance(metadata["session_id"], bool)
                or not isinstance(metadata["timestamp"], (float, int)) or isinstance(metadata["timestamp"], bool)
                or not math.isfinite(metadata["timestamp"]) or metadata["timestamp"] < 0
                or not isinstance(metadata["database"], str) or not Path(metadata["database"]).is_absolute()
                or Path(metadata["database"]).resolve() != Path(metadata["database"])
                or not isinstance(metadata["spectral_context"], str)):
            raise ValueError("invalid frozen reflection metadata")
        _json(metadata["spectral_context"].encode("utf-8"))
        _hash(metadata["implementation_sha256"])
        if metadata.get("job_id") is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", str(metadata["job_id"])):
            raise ValueError("invalid reflection job identity")
        self._verify_publication(root, intent["publication"], missing_ok=True)

    def _intent(self, root, data, record):
        raw = data.read(self.intent_name, MAX_INTENT)
        if record.get("intent_sha256", _sha(raw)) != _sha(raw):
            raise ValueError("reflection intent hash conflict")
        intent = _record(raw)
        self._validate_intent(root, intent, record)
        return intent, _sha(raw)

    def reconcile(self, *, apply=False, database=None):
        with self._locked(readonly=not apply) as (root, data):
            record = self._load(data)
            self.binding = record["binding"]
            self.result = self._reconcile(root, data, record, apply=apply, database=database)
            return self.result

    def _reconcile(self, root, data, record, *, apply, database, before_index=None, after_index=None):
        if record["schema"] == LEGACY_SCHEMA:
            if "delivery" not in record:
                return FinalizationResult(None, "unresolved", reason="legacy_unsealed")
            self._verify_delivery(root, record["delivery"])
            if "publication" not in record:
                return FinalizationResult(True, "unresolved", reason="legacy_unsealed")
            path = self._verify_publication(root, record["publication"])
            return FinalizationResult(True, "published", path=str(path), reason="legacy_index_and_choice_unverified")
        if not data.exists(self.intent_name):
            return FinalizationResult(None if self._native_delivery_exists(root) else False,
                                      "unresolved", reason="publication_intent_unavailable")
        if record["stage"] == "failed_unaccepted":
            raise ValueError("failed reflection has conflicting publication intent")
        intent, digest = self._intent(root, data, record)
        if database is not None and str(Path(database).absolute()) != intent["metadata"]["database"]:
            raise ValueError("reflection database binding differs; no writes")
        if apply and database is None:
            raise ValueError("recovery requires the explicit bound database")
        path = self._verify_publication(root, intent["publication"], missing_ok=record["stage"] != "published")
        publication_id = _sha(_bytes(record["binding"]))
        if not apply:
            indexed = self._index(intent, publication_id, apply=False) if database is not None else "unknown"
            return FinalizationResult(True, "published" if path else "prepared", indexed, intent["choice"],
                "read_only_preview", publication_id, str(path) if path else None)
        reason = None
        indexed = "unavailable"
        try:
            if record["stage"] == "reserved":
                record = self._prepared(record, digest)
                self._save(data, record)
            if path is None:
                journal = root.child("journal", create=True)
                journal.atomic(intent["publication"]["filename"], intent["text"].encode("utf-8"))
                path = self._verify_publication(root, intent["publication"])
            if record["stage"] != "published":
                record["stage"] = "published"
                self._save(data, record)
            self._hook(data, record, "before", before_index)
            indexed = self._index(intent, publication_id, apply=True)
            if record["indexing"] != indexed:
                record["indexing"] = indexed
                self._save(data, record)
            self._hook(data, record, "after", after_index)
        except (OSError, ValueError, sqlite3.Error):
            # A local mirror failure cannot un-accept a provider completion.
            reason = "local_finalization_incomplete"
        path = self._verify_publication(root, intent["publication"], missing_ok=record["stage"] != "published")
        if indexed != "indexed":
            try:
                indexed = self._index(intent, publication_id, apply=False)
            except (OSError, ValueError, sqlite3.Error):
                indexed = "unavailable"
        hooks = record.get("hooks", {})
        diagnostics = "completed" if hooks and all(v == "done" for v in hooks.values()) else "not_replayed"
        if any(v in {"started", "failed"} for v in hooks.values()):
            diagnostics = "incomplete"
        result = FinalizationResult(True, "published" if path else "prepared", indexed, intent["choice"],
                                    reason, publication_id, str(path) if path else None, diagnostics)
        if before_index is None and after_index is None:
            # Content-addressed evidence adds recovery facts without rewriting job history.
            evidence = {"schema": SCHEMA, "binding": record["binding"], "intent_sha256": digest,
                        "result": result.status()}
            try:
                data.atomic("recovery-" + _sha(_bytes(evidence)) + ".json", _envelope(evidence))
            except OSError:
                return FinalizationResult(True, result.publication, indexed, intent["choice"],
                    "recovery_receipt_unavailable", publication_id, result.path, diagnostics)
        return result

    def _hook(self, data, record, name, callback):
        if callback is None or record["hooks"][name] != "pending":
            return
        record["hooks"][name] = "started"
        self._save(data, record)
        try:
            callback()
        except Exception:
            record["hooks"][name] = "failed"
        else:
            record["hooks"][name] = "done"
        self._save(data, record)

    def _index(self, intent, publication_id, *, apply):
        metadata = intent["metadata"]
        database = Path(metadata["database"])
        with Directory(database.parent) as parent:
            info = parent.stat(database.name)
            if not stat.S_ISREG(info.st_mode) or database.resolve() != database:
                raise ValueError("invalid bound reflection database")
            def has_side_files():
                return any(parent.exists(database.name + suffix) for suffix in ("-wal", "-shm", "-journal"))

            # A read-only SQLite connection can still create WAL shared memory.
            # Inspect a stable, side-file-free database immutably or say unknown.
            if not apply and has_side_files():
                return "unavailable_live_sqlite_state"
            conn = sqlite3.connect(database.as_uri() + ("?mode=rw" if apply else "?mode=ro&immutable=1"), uri=True, timeout=5)
            try:
                if apply:
                    conn.execute("BEGIN IMMEDIATE")
                columns = {row[1] for row in conn.execute("PRAGMA table_info(sovereignty_journal)")}
                required = {"session_id", "timestamp", "entry_type", "content", "spectral_context", "file_path"}
                if not required <= columns:
                    raise ValueError("journal database schema unavailable")
                if "publication_id" not in columns:
                    if not apply:
                        return "pending"
                    conn.execute("ALTER TABLE sovereignty_journal ADD COLUMN publication_id TEXT")
                if apply:
                    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS reflection_publication_identity "
                                 "ON sovereignty_journal(publication_id) WHERE publication_id IS NOT NULL")
                self._verify_index_constraint(conn)
                original_path = str(self.workspace / "journal" / intent["publication"]["filename"])
                expected = (metadata["session_id"], metadata["timestamp"], "introspect", intent["content"],
                            metadata["spectral_context"], original_path, publication_id)
                rows = conn.execute("SELECT session_id,timestamp,entry_type,content,spectral_context,file_path,publication_id "
                    "FROM sovereignty_journal WHERE publication_id=? OR file_path=?", (publication_id, original_path)).fetchall()
                if rows and rows != [expected]:
                    raise ValueError("reflection database identity/content conflict")
                if not rows and apply:
                    conn.execute("INSERT INTO sovereignty_journal "
                        "(session_id,timestamp,entry_type,content,spectral_context,file_path,publication_id) "
                        "VALUES (?,?,?,?,?,?,?)", expected)
                    recorded = conn.execute("SELECT session_id,timestamp,entry_type,content,spectral_context,file_path,publication_id "
                        "FROM sovereignty_journal WHERE publication_id=?", (publication_id,)).fetchall()
                    if recorded != [expected]:
                        raise ValueError("reflection database changed inserted content")
                current = parent.stat(database.name)
                if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                    raise ValueError("reflection database replaced during indexing")
                if not apply and (has_side_files() or (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                                  != (current.st_size, current.st_mtime_ns, current.st_ctime_ns)):
                    raise ValueError("reflection database changed during inspection")
                parent.check()
                if apply:
                    conn.commit()
                return "indexed" if rows or apply else "pending"
            finally:
                conn.close()

    @staticmethod
    def _verify_index_constraint(conn):
        name = "reflection_publication_identity"
        indexes = {row[1]: row for row in conn.execute("PRAGMA index_list(sovereignty_journal)")}
        row = indexes.get(name)
        definition = conn.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        if (row is None or row[2] != 1 or row[4] != 1 or definition is None
                or definition[0] != "sovereignty_journal"
                or " ".join(definition[1].upper().split()).partition(" WHERE ")[2] != "PUBLICATION_ID IS NOT NULL"):
            raise ValueError("reflection database uniqueness constraint is incompatible")
        keys = [(r[2], r[3], r[4]) for r in conn.execute("PRAGMA index_xinfo(reflection_publication_identity)") if r[5]]
        if keys != [("publication_id", 0, "BINARY")]:
            raise ValueError("reflection database uniqueness columns are incompatible")

    @classmethod
    def for_action(cls, workspace, action_id):
        probe = cls(workspace, action_id, "0" * 64)
        with probe._locked(readonly=True) as (_, data):
            record = _record(data.read(probe.name, MAX_RECEIPT))
            operation = cls(workspace, action_id, record.get("binding", {}).get("input_id"))
            operation._load(data)
            return operation

    @classmethod
    def recover_pending(cls, workspace, database):
        """Startup-only local recovery; no history hydration, queue or model access."""
        probe = cls(workspace, "startup", "0" * 64)
        try:
            with probe._locked(readonly=True) as (_, data):
                names = sorted(n for n in data.names() if re.fullmatch(r"action-[0-9a-f]{64}\.json", n))
        except FileNotFoundError:
            return []
        results = []
        for name in names:
            try:
                with probe._locked(readonly=True) as (_, data):
                    record = _record(data.read(name, MAX_RECEIPT))
                    if (record["schema"] == LEGACY_SCHEMA or record.get("stage") == "failed_unaccepted"
                            or (record.get("stage") == "published" and record.get("indexing") == "indexed")):
                        continue
                    binding = record.get("binding", {})
                    operation = cls(workspace, binding.get("action_id"), binding.get("input_id"))
                    if operation.name != name:
                        raise ValueError("reflection action filename mismatch")
                result = operation.reconcile(apply=True, database=database)
                results.append({"action_id": operation.action_id, **result.status()})
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                results.append({"record": name, "publication": "unresolved", "reason": "invalid_or_unavailable_evidence"})
        return results
