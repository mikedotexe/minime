"""Reflection-only invocation/publication guard; no inference or automatic recovery.

Receipts contain identities and hashes, never authored content. A reserved but
unfinished invocation is uncertain on restart and cannot be replayed implicitly.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from .mailbox_fs import Directory


SCHEMA = "minime_reflection_publication_v1"
MAX_RECEIPT = 16 * 1024
MAX_PUBLICATION = 2 * 1024 * 1024
STAGES = {"reserved", "failed_unaccepted", "accepted", "publishing", "published", "completed"}
NAVIGATION = ("diagnostics", "source_first_v3", "shared_reader", "navigation")


class RecoveryRequired(RuntimeError):
    pass


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
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
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
        self.binding = None
        self.completed = False

    @contextmanager
    def _locked(self):
        with Directory(self.workspace) as root:
            data = root.child("runtime", create=True).child("reflection_publications", create=True)
            with data.lock(".transaction.lock"):
                yield root, data

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
        stage = record.get("stage")
        if not isinstance(stage, str) or stage not in STAGES:
            raise ValueError("unsupported reflection publication state")
        keys = {"schema", "binding", "stage"}
        if stage not in {"reserved", "failed_unaccepted"}:
            keys.add("delivery")
        if stage in {"publishing", "published", "completed"}:
            keys.add("publication")
        if stage not in STAGES or set(record) != keys:
            raise ValueError("unsupported reflection publication state")
        expected_index = {"schema": SCHEMA, "action_file": self.name, "binding_sha256": _sha(_bytes(binding))}
        if stage != "failed_unaccepted" and _record(data.read(self.index, MAX_RECEIPT)) != expected_index:
            raise ValueError("reflection input binding changed")
        return record

    def _save(self, data, record):
        raw = _envelope(record)
        if len(raw) > MAX_RECEIPT:
            raise ValueError("reflection receipt exceeds limit")
        data.atomic(self.name, raw, replace=True)

    @classmethod
    def begin(cls, workspace, action_id, input_id):
        operation = cls(workspace, action_id, input_id)
        with operation._locked() as (root, data):
            if data.exists(operation.name):
                record = operation._load(data)
                operation.binding = record["binding"]
                if record["stage"] != "completed":
                    raise RecoveryRequired("reflection_publication_recovery_required:" + record["stage"]
                                           + "; no automatic generation or NEXT replay")
                operation._verify_delivery(root, record["delivery"])
                operation._verify_publication(root, record["publication"])
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
                if (earlier.name != filename or previous != {"schema": SCHEMA, "action_file": filename,
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

    def accepted(self, receipt):
        if not isinstance(receipt, dict) or receipt.get("page_id") != self.input_id:
            raise ValueError("reflection publication requires verified input delivery")
        delivery = {key: receipt.get(key) for key in ("artifact_sha256", "request_sha256", "response_sha256")}
        with self._locked() as (root, data):
            record = self._load(data)
            if record["stage"] != "reserved":
                raise RecoveryRequired("reflection acceptance already recorded; no replay")
            self._verify_delivery(root, delivery)
            record.update(stage="accepted", delivery=delivery)
            self._save(data, record)

    def _verify_publication(self, root, publication):
        if (not isinstance(publication, dict) or set(publication) != {"filename", "sha256"}
                or not isinstance(publication["filename"], str)
                or not re.fullmatch(r"introspect_[0-9T.-]+\.txt", publication["filename"])):
            raise ValueError("invalid reflection publication binding")
        expected = _hash(publication["sha256"])
        if _sha(root.child("journal").read(publication["filename"], MAX_PUBLICATION)) != expected:
            raise ValueError("reflection publication changed; preserved unchanged")

    def publish(self, filename, text):
        if not isinstance(filename, str) or not re.fullmatch(r"introspect_[0-9T.-]+\.txt", filename):
            raise ValueError("invalid reflection publication filename")
        raw = text.encode("utf-8")
        if len(raw) > MAX_PUBLICATION:
            raise ValueError("reflection publication exceeds existing delivery evidence bound")
        with self._locked() as (root, data):
            record = self._load(data)
            if record["stage"] != "accepted":
                raise RecoveryRequired("reflection publication already started; no replay")
            self._verify_delivery(root, record["delivery"])
            journal = root.child("journal", create=True)
            if journal.exists(filename):
                raise ValueError("reflection publication filename already exists; retained unchanged")
            record.update(stage="publishing", publication={"filename": filename, "sha256": _sha(raw)})
            self._save(data, record)
            journal.atomic(filename, raw)
            self._verify_publication(root, record["publication"])
            record["stage"] = "published"
            self._save(data, record)
        return self.workspace / "journal" / filename

    def complete(self):
        with self._locked() as (root, data):
            record = self._load(data)
            if record["stage"] != "published":
                raise RecoveryRequired("reflection completion requires reconciled publication")
            self._verify_delivery(root, record["delivery"])
            self._verify_publication(root, record["publication"])
            record["stage"] = "completed"
            self._save(data, record)
        self.completed = True
