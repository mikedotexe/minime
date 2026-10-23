"""Durable ordinary inbox batches, sharing the explicit mailbox's state and lock.

Only pre-dispatch selections resume inference. Retained completions recover
publication and source retirement, never a provider call or a NEXT action.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import re
from uuid import uuid4

from .inbox_delivery import InboxContext, InboxMessage, save_generation
from .mailbox import MAX_SEEN, MAX_SOURCE_BYTES, _hash, _sha, _stopped

CONTEXT_SCHEMA = "minime_automatic_inbox_context_v1"
COMPLETION_SCHEMA = "minime_automatic_inbox_completion_v1"
MAX_BATCHES = MAX_SEEN
MAX_BATCH_FILES = 256
MAX_CONTEXT_BYTES = 1_048_576
MAX_FROZEN_BYTES = 2_097_152
MAX_BATCH_SOURCE_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 1_048_576
MAX_OUTPUTS = 8
MAX_PROVIDER_BYTES = 8_000_000
PHASES = {"selected", "started", "supplied", "response_retained", "incomplete", "completed"}
INCOMPLETE_REASONS = {"unconfirmed_input", "provider_stop_unverified", "empty_output",
                      "completion_missing", "cleaned_output_mismatch", "completion_changed",
                      "provider_metadata_unavailable"}


def _require(condition, message="corrupt automatic inbox history; retained unchanged"):
    if not condition:
        raise ValueError(message)


def _filename(value):
    return (isinstance(value, str) and value not in {"", ".", ".."}
            and "/" not in value and "\0" not in value and len(value.encode("utf-8")) <= 255)


def _source_id(batch_id, name):
    return _sha(("automatic-source\0" + batch_id + "\0" + name).encode())


def _attempt(value):
    return isinstance(value, str) and re.fullmatch(r"submission_[0-9a-f]{32}", value) is not None


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def validate_automatic(value):
    """Pure structural validation of the state.json `automatic` mapping; no I/O."""
    try:
        _validate_automatic(value)
    except (TypeError, KeyError, UnicodeError, OverflowError):
        raise ValueError("corrupt automatic inbox history; retained unchanged") from None


def _validate_automatic(value):
    _require(isinstance(value, dict) and len(value) <= MAX_BATCHES)
    reserved = set()
    required = {"phase", "context_sha256", "sources", "outputs", "published_outputs"}
    optional = {"attempt_id", "supplied_attempt", "completion_sha256", "incomplete_reason"}
    for batch_id, batch in value.items():
        _require(_hash(batch_id) and isinstance(batch, dict))
        _require(required <= set(batch) <= required | optional)
        phase = batch["phase"]
        _require(isinstance(phase, str) and phase in PHASES and _hash(batch["context_sha256"]))
        sources = batch["sources"]
        _require(isinstance(sources, list) and 1 <= len(sources) <= MAX_BATCH_FILES)
        names = set()
        for source in sources:
            _require(isinstance(source, dict)
                     and {"filename", "source_sha256", "artifact_id"} <= set(source)
                     <= {"filename", "source_sha256", "artifact_id", "retirement", "retirement_debt"})
            name = source["filename"]
            _require(_filename(name) and name not in names and _hash(source["source_sha256"])
                     and source["artifact_id"] == _source_id(batch_id, name)
                     and source.get("retirement") in {None, "armed"}
                     and source.get("retirement_debt") in {None, "changed_source_retained"})
            _require(not source.get("retirement_debt") or source.get("retirement") == "armed")
            _require(phase in {"response_retained", "completed"}
                     or not (source.get("retirement") or source.get("retirement_debt")))
            _require(phase != "completed" or not source.get("retirement_debt"))
            names.add(name)
        if phase != "completed":
            _require(not names.intersection(reserved))
            reserved.update(names)
        for key in ("outputs", "published_outputs"):
            hashes = batch[key]
            _require(isinstance(hashes, list) and len(hashes) <= MAX_OUTPUTS
                     and all(_hash(item) for item in hashes) and len(set(hashes)) == len(hashes))
        _require(set(batch["published_outputs"]) <= set(batch["outputs"]))
        if phase == "selected":
            _require(set(batch) == required and not batch["outputs"])
        else:
            _require(_attempt(batch.get("attempt_id")))
        if "supplied_attempt" in batch:
            _require(batch["supplied_attempt"] == batch.get("attempt_id"))
        if phase in {"supplied", "response_retained", "completed"}:
            _require(batch.get("supplied_attempt") == batch.get("attempt_id"))
        if phase == "started":
            _require("supplied_attempt" not in batch and "completion_sha256" not in batch)
        if "completion_sha256" in batch:
            _require(_hash(batch["completion_sha256"]) and bool(batch["outputs"]))
        if phase in {"response_retained", "completed"}:
            _require("completion_sha256" in batch and "incomplete_reason" not in batch)
        if phase == "completed":
            _require(bool(batch["published_outputs"]))
        if phase == "incomplete":
            _require(batch.get("incomplete_reason") in INCOMPLETE_REASONS)
        else:
            _require("incomplete_reason" not in batch)


def phase_by_name(value):
    return {source["filename"]: batch["phase"] for batch in value.values()
            if batch["phase"] != "completed" for source in batch["sources"]}


def reserved_names(value):
    return set(phase_by_name(value))


def status_projection(value):
    counts = {phase: 0 for phase in sorted(PHASES)}
    for batch in value.values():
        counts[batch["phase"]] += 1
    return {**counts, "reserved_files": len(reserved_names(value)),
            "reconciliation_required": any(counts[phase] for phase in
                                           ("started", "supplied", "response_retained", "incomplete")),
            "semantics": "recorded ordinary inbox batches, not a fresh verification of frozen artifacts; accepted input is not attention or understanding; incomplete output stays private and sources remain held"}


class AutomaticInboxContext(InboxContext):
    @property
    def dispatch_claimed(self):
        """Unknown durable state fails closed against a second provider attempt."""
        try:
            with self.automatic.store._observed() as files:
                state = self.automatic._state(files)
                batch = self.automatic._batch(state, self)
                return batch["phase"] != "selected"
        except (OSError, ValueError):
            return True

    def prepared(self, messages, model):
        with self.automatic.store.locked() as files:
            state = self.automatic._state(files)
            batch = self.automatic._batch(state, self, files)
            _require(batch["phase"] == "selected", "automatic inbox dispatch already claimed; no replay")
            attempt = super().prepared(messages, model)
            batch["attempt_id"] = attempt
            batch["phase"] = "started"
            self.automatic.store._save(state, files)
            return attempt

    def accepted(self, attempt, model):
        with self.automatic.store.locked() as files:
            state = self.automatic._state(files)
            batch = self.automatic._batch(state, self, files)
            _require(batch.get("attempt_id") == attempt, "automatic inbox acceptance identity mismatch")
            if batch.get("supplied_attempt") == attempt:
                self.supplied, self.last_supplied_attempt = True, attempt
                return
            _require(batch["phase"] == "started", "automatic inbox acceptance phase mismatch")
            super().accepted(attempt, model)
            batch["supplied_attempt"] = attempt
            batch["phase"] = "supplied"
            self.automatic.store._save(state, files)

    def provider_completed(self, parsed, cleaned_output):
        return self.automatic._provider_completed(self, parsed, cleaned_output)

    def finish(self, response):
        """Keep all bounded output; only verified complete input/output can retire mail."""
        return self.automatic._finish(self, response)


class AutomaticInbox:
    def __init__(self, store):
        self.store = store

    def _state(self, files):
        root = Path(os.path.abspath(self.store.workspace))
        _require(files.root.path == root
                 and (files.inbox is None or files.inbox.path == root / "inbox")
                 and (files.data is None or files.data.path == root / "correspondence/mailbox_v1"),
                 "automatic inbox filesystem owner mismatch")
        files.root.check()
        return self.store._load(files.data)

    def reserved_names_locked(self, files):
        return reserved_names(self._state(files)["automatic"])

    def status_locked(self, files):
        return status_projection(self._state(files)["automatic"])

    def _payload(self, batch_id, batch, payload, raw_sources):
        _require(isinstance(payload, dict) and set(payload) == {"schema", "batch_id", "text", "messages"}
                 and payload["schema"] == CONTEXT_SCHEMA and payload["batch_id"] == batch_id,
                 "automatic inbox frozen context identity mismatch")
        text, records = payload["text"], payload["messages"]
        _require(isinstance(text, str) and 0 < len(text.encode()) <= MAX_CONTEXT_BYTES
                 and isinstance(records, list) and len(records) == len(batch["sources"]),
                 "automatic inbox frozen context exceeds bounds")
        messages = []
        names = set()
        for record in records:
            _require(isinstance(record, dict) and set(record) == {
                "message_id", "sender", "thread_id", "filename", "source_sha256", "rendered_text"}
                and all(isinstance(item, str) for item in record.values()),
                "automatic inbox message record invalid")
            message = InboxMessage(**record)
            _require(message.filename in raw_sources and message.filename not in names
                     and message.rendered_text in text, "automatic inbox message missing from frozen context")
            raw = raw_sources[message.filename]
            source = raw.decode("utf-8")
            variants = {source, source.strip(), source.replace("\r\n", "\n").replace("\r", "\n").strip()}
            _require(any(InboxMessage.from_source(message.filename, variant, message.rendered_text) == message
                         for variant in variants), "automatic inbox source/message identity mismatch")
            names.add(message.filename)
            messages.append(message)
        _require(names == set(raw_sources), "automatic inbox source set mismatch")
        return text, tuple(messages)

    def _restore(self, batch_id, batch, files):
        raw = files.data.read(batch_id + ".automatic-context.json", MAX_FROZEN_BYTES)
        _require(_sha(raw) == batch["context_sha256"], "automatic inbox frozen context changed")
        sources = {}
        total = 0
        for source in batch["sources"]:
            raw_source = files.data.read(source["source_sha256"] + ".txt", MAX_SOURCE_BYTES)
            _require(_sha(raw_source) == source["source_sha256"], "automatic inbox retained source changed")
            total += len(raw_source)
            sources[source["filename"]] = raw_source
        _require(total <= MAX_BATCH_SOURCE_BYTES, "automatic inbox sources exceed retention bound")
        text, messages = self._payload(batch_id, batch, json.loads(raw), sources)
        context = AutomaticInboxContext(text, messages, self.store.workspace)
        context.automatic, context.artifact_id = self, batch_id
        context.batch_id = "automatic_" + batch_id
        context.supplied = "supplied_attempt" in batch
        context.last_supplied_attempt = batch.get("supplied_attempt")
        return context

    def _batch(self, state, context, files=None):
        batch_id = context.artifact_id
        _require(_hash(batch_id) and context.batch_id == "automatic_" + batch_id
                 and context.workspace == self.store.workspace and batch_id in state["automatic"],
                 "automatic inbox context identity mismatch")
        batch = state["automatic"][batch_id]
        if files is not None:
            frozen = self._restore(batch_id, batch, files)
            _require(str(frozen) == str(context) and frozen.messages == context.messages,
                     "automatic inbox context differs from retained selection")
        return batch

    def prepare_locked(self, text, messages, sources, files):
        state = self._state(files)
        _require(isinstance(sources, dict) and 1 <= len(sources) <= MAX_BATCH_FILES
                 and all(_filename(name) and isinstance(raw, bytes) and len(raw) <= MAX_SOURCE_BYTES
                         for name, raw in sources.items())
                 and sum(map(len, sources.values())) <= MAX_BATCH_SOURCE_BYTES,
                 "automatic inbox requires bounded admitted raw sources")
        _require(len(state["automatic"]) < MAX_BATCHES, "automatic inbox history full; sources retained")
        held = reserved_names(state["automatic"])
        if state["pending"]:
            held.add(state["pending"]["filename"])
        _require(not held.intersection(sources), "automatic inbox source already reserved")
        batch_id = _sha(uuid4().bytes)
        _require(batch_id not in state["automatic"], "automatic inbox batch identity conflict")
        batch = {"phase": "selected", "context_sha256": "", "outputs": [], "published_outputs": [],
                 "sources": [{"filename": name, "source_sha256": _sha(raw),
                              "artifact_id": _source_id(batch_id, name)} for name, raw in sorted(sources.items())]}
        _require(isinstance(messages, (list, tuple)) and all(isinstance(m, InboxMessage) for m in messages),
                 "automatic inbox requires admitted message records")
        payload = {"schema": CONTEXT_SCHEMA, "batch_id": batch_id, "text": str(text),
                   "messages": [asdict(message) for message in messages]}
        self._payload(batch_id, batch, payload, sources)
        raw = _json(payload)
        _require(len(raw) <= MAX_FROZEN_BYTES, "automatic inbox frozen context exceeds retention bound")
        batch["context_sha256"] = _sha(raw)
        for name, source in sources.items():
            _require(files.inbox.read(name, MAX_SOURCE_BYTES) == source, "automatic inbox source changed before selection")
        # Fence v1 writers before any new automatic reservation artifacts exist.
        self.store._save(state, files)
        for source in sources.values():
            files.data.atomic(_sha(source) + ".txt", source)
        files.data.atomic(batch_id + ".automatic-context.json", raw)
        state["automatic"][batch_id] = batch
        self.store._save(state, files)
        return self._restore(batch_id, batch, files)

    def pending_context_locked(self, files):
        state = self._state(files)
        for batch_id, batch in sorted(state["automatic"].items()):
            try:
                if batch["phase"] == "response_retained":
                    self._finish_record(state, batch_id, batch, files)
                elif batch["phase"] == "incomplete":
                    for digest in batch["outputs"]:
                        self._publish(state, batch_id, batch, digest, files, verified=False)
            except (OSError, ValueError) as error:
                # Held work reserves its own filenames, not unrelated ordinary mail.
                logging.warning("Automatic inbox storage recovery deferred; batch=%s; error=%s",
                                batch_id, type(error).__name__)
                continue
        for batch_id, batch in sorted(state["automatic"].items()):
            if batch["phase"] == "selected":
                try:
                    return self._restore(batch_id, batch, files)
                except (OSError, ValueError) as error:
                    logging.warning("Automatic inbox selected evidence unavailable; batch=%s; error=%s",
                                    batch_id, type(error).__name__)
                    continue
        return None

    def _retain_output(self, batch, response, files):
        _require(isinstance(response, str), "automatic inbox response must be text")
        raw = response.encode("utf-8")
        _require(len(raw) <= MAX_OUTPUT_BYTES, "automatic inbox response exceeds retention bound; sources held")
        digest = _sha(raw)
        _require(digest in batch["outputs"] or len(batch["outputs"]) < MAX_OUTPUTS,
                 "automatic inbox retained output limit reached; sources held")
        files.data.atomic(digest + ".automatic-output.txt", raw)
        if digest not in batch["outputs"]:
            batch["outputs"].append(digest)
        return raw, digest

    def _provider_completed(self, context, parsed, cleaned_output):
        with self.store.locked() as files:
            state = self._state(files)
            batch = self._batch(state, context, files)
            _require(batch["phase"] not in {"selected", "completed"}, "automatic inbox completion phase mismatch")
            raw, digest = self._retain_output(batch, cleaned_output, files)
            self.store._save(state, files)
            try:
                provider = _json(parsed)
                provider_hash = _sha(provider) if len(provider) <= MAX_PROVIDER_BYTES else None
            except (TypeError, ValueError, UnicodeError):
                provider_hash = None
            completion = {"schema": COMPLETION_SCHEMA, "batch_id": context.artifact_id,
                          "attempt_id": batch["attempt_id"], "context_sha256": batch["context_sha256"],
                          "provider_sha256": provider_hash, "response_sha256": digest,
                          "response_bytes": len(raw), "normal_stop": bool(provider_hash and _stopped(parsed))}
            encoded = _json(completion)
            if batch.get("completion_sha256") and batch["completion_sha256"] != _sha(encoded):
                batch["phase"], batch["incomplete_reason"] = "incomplete", "completion_changed"
                self.store._save(state, files)
                return
            files.data.atomic(context.artifact_id + ".automatic-completion.json", encoded)
            batch["completion_sha256"] = _sha(encoded)
            reason = ("unconfirmed_input" if "supplied_attempt" not in batch else
                      "provider_metadata_unavailable" if provider_hash is None else
                      "provider_stop_unverified" if not completion["normal_stop"] else
                      "empty_output" if not raw else None)
            if reason or batch["phase"] == "incomplete":
                batch["phase"] = "incomplete"
                batch.setdefault("incomplete_reason", reason)
            else:
                batch["phase"] = "response_retained"
            self.store._save(state, files)

    def _completion(self, batch_id, batch, files):
        raw = files.data.read(batch_id + ".automatic-completion.json", 4096)
        _require(_sha(raw) == batch.get("completion_sha256"), "automatic inbox completion receipt changed")
        value = json.loads(raw)
        _require(isinstance(value, dict) and set(value) == {
            "schema", "batch_id", "attempt_id", "context_sha256", "provider_sha256",
            "response_sha256", "response_bytes", "normal_stop"}
            and value["schema"] == COMPLETION_SCHEMA and value["batch_id"] == batch_id
            and value["attempt_id"] == batch["attempt_id"] and value["context_sha256"] == batch["context_sha256"]
            and (value["provider_sha256"] is None or _hash(value["provider_sha256"]))
            and value["response_sha256"] in batch["outputs"]
            and type(value["response_bytes"]) is int and 0 <= value["response_bytes"] <= MAX_OUTPUT_BYTES
            and type(value["normal_stop"]) is bool
            and (not value["normal_stop"] or value["provider_sha256"] is not None),
            "automatic inbox completion identity mismatch")
        return value

    def _publish(self, state, batch_id, batch, digest, files, *, verified):
        if digest in batch["published_outputs"]:
            return
        raw = files.data.read(digest + ".automatic-output.txt", MAX_OUTPUT_BYTES)
        _require(_sha(raw) == digest, "automatic inbox retained output changed")
        context = self._restore(batch_id, batch, files)
        if not verified:
            context.supplied = False  # Partial/unconfirmed output never becomes an addressed reply.
        artifact_id = _sha(("automatic-output\0" + batch_id + "\0" + digest).encode())
        save_generation(self.store.workspace, raw.decode("utf-8"), context,
                        artifact_id=artifact_id, root=files.root)
        batch["published_outputs"].append(digest)
        self.store._save(state, files)

    def _finish_record(self, state, batch_id, batch, files):
        completion = self._completion(batch_id, batch, files)
        _require(batch.get("supplied_attempt") == batch.get("attempt_id") and completion["normal_stop"]
                 and completion["response_bytes"] > 0, "automatic inbox completion not verified; sources held")
        digest = completion["response_sha256"]
        raw = files.data.read(digest + ".automatic-output.txt", MAX_OUTPUT_BYTES)
        _require(_sha(raw) == digest and len(raw) == completion["response_bytes"],
                 "automatic inbox cleaned output changed; sources held")
        self._restore(batch_id, batch, files)
        self._publish(state, batch_id, batch, digest, files, verified=True)
        for source in batch["sources"]:
            self.store._retire_source(state, files, pending=source)
        batch["phase"] = "completed"
        self.store._save(state, files)
        return True

    def _finish(self, context, response):
        with self.store.locked() as files:
            state = self._state(files)
            batch = self._batch(state, context, files)
            _require(batch["phase"] != "selected", "automatic inbox output has no claimed attempt")
            if batch["phase"] == "completed":
                completion = self._completion(context.artifact_id, batch, files)
                _require(isinstance(response, str) and _sha(response.encode()) == completion["response_sha256"],
                         "automatic inbox completed output identity mismatch")
                return True
            _, digest = self._retain_output(batch, response, files)
            if batch["phase"] == "response_retained":
                completion = self._completion(context.artifact_id, batch, files)
                if digest == completion["response_sha256"]:
                    return self._finish_record(state, context.artifact_id, batch, files)
                reason = "cleaned_output_mismatch"
            else:
                reason = "completion_missing"
            batch["phase"] = "incomplete"
            batch.setdefault("incomplete_reason", reason)
            self.store._save(state, files)
            self._publish(state, context.artifact_id, batch, digest, files, verified=False)
            return False
