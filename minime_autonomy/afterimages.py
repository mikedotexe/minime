"""Transition archive reader and private authored memory; also the shared CLI for Astrid.

Only explicit memory commands write notes or capture requests. Cue preparation is
default-off. This module has no model, telemetry-control, or runtime dependencies.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

POLICY = "transition_afterimage_v1"
ACTIONS = frozenset({"AFTERIMAGE_LIST", "AFTERIMAGE_OPEN", "AFTERIMAGE_KEEP", "AFTERIMAGE_SHARE", "AFTERIMAGE_CUES"})
ID = re.compile(r"^ai_(\d{4}-\d{2}-\d{2})_[A-Za-z0-9_-]{1,100}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
HOUR_MS = 3_600_000
PAGE_CHARS = 2800
INDEX_LIMIT = 256


def now_ms():
    return time.time_ns() // 1_000_000


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path, default=None):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_record(path, value):
    with locked(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def dated(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


def quoted(text):
    # Every source line is quoted, including source text containing NEXT or fence markers.
    return "\n".join("> " + line for line in text.split("\n"))


class AfterimageStore:
    def __init__(self, workspace, archive_workspace=None, actor="minime"):
        if actor not in {"minime", "astrid"}:
            raise ValueError("unknown afterimage actor")
        self.workspace = Path(workspace).resolve()
        self.archive = Path(archive_workspace or workspace).resolve() / "transition_afterimages"
        self.private = self.workspace / "transition_afterimage_memory"
        self.actor = actor

    def _id(self, value):
        match = ID.fullmatch(value)
        if not match:
            raise ValueError("invalid afterimage id")
        datetime.strptime(match[1], "%Y-%m-%d")
        return match[1]

    def _artifact(self, identifier):
        date = self._id(identifier)
        path = self.archive / date / (identifier + ".json")
        value = read_json(path)
        if value is not None:
            if value.get("policy") != POLICY or value.get("schema_version") != 1 or value.get("id") != identifier:
                raise ValueError("unsupported or mismatched afterimage artifact")
            return value
        return None

    def _notes(self, identifier):
        self._id(identifier)
        result = {}
        # Only the actor's own directory and explicit shared copies are readable here.
        for directory in (self.private / "by_artifact" / identifier, self.archive / "shared_notes" / identifier):
            if not directory.exists():
                continue
            expected_root = self.private if directory.is_relative_to(self.private) else self.archive / "shared_notes"
            if expected_root.is_symlink() or not directory.resolve().is_relative_to(expected_root.resolve()):
                continue
            for path in sorted(directory.glob("*.json")):
                if path.is_symlink():
                    continue
                note = read_json(path)
                if note and note.get("afterimage_id") == identifier:
                    if directory.is_relative_to(self.private) and note.get("author") != self.actor:
                        continue
                    result[note["note_id"]] = note
        return sorted(result.values(), key=lambda note: (note["recorded_at_unix_ms"], note["note_id"]))

    def _index_add(self, root, row):
        with locked(root / "index.lock"):
            rows = read_json(root / "index.json", [])
            rows = [item for item in rows if item["id"] != row["id"]]
            rows.append(row)
            rows.sort(key=lambda item: (item["anchor_unix_ms"], item["id"]), reverse=True)
            atomic_json(root / "index.json", rows[:INDEX_LIMIT])
            date = self._id(row["id"])
            atomic_json(root / "dates" / date / (row["id"] + ".json"), row)

    def entries(self, date=None):
        rows = {}
        if date:
            datetime.strptime(date, "%Y-%m-%d")
            directory = self.archive / date
            if directory.exists():
                for path in directory.glob("ai_*.json"):
                    artifact = self._artifact(path.stem)
                    if artifact:
                        rows[artifact["id"]] = self._summary(artifact)
        else:
            for row in read_json(self.archive / "recent.json", []):
                self._id(row["id"])
                rows[row["id"]] = row
        for root in (self.private, self.archive / "shared_notes"):
            if root.is_symlink() or (root / "index.json").is_symlink():
                continue
            dated_root = root / "dates" / date if date else None
            indexed = [read_json(path) for path in sorted(dated_root.glob("*.json"))] if dated_root else read_json(root / "index.json", [])
            for row in indexed:
                if date is None or self._id(row["id"]) == date:
                    rows.setdefault(row["id"], row)
        return sorted(rows.values(), key=lambda row: (row["anchor_unix_ms"], row["id"]), reverse=True)

    @staticmethod
    def _summary(artifact):
        return {key: artifact.get(key) for key in ("id", "anchor_unix_ms", "origin", "status", "coverage", "session_id")}

    def list_page(self, page=1, date=None):
        if page < 1:
            raise ValueError("page must be positive")
        rows = self.entries(date)
        selected = rows[(page-1)*5:page*5]
        lines = [f"Afterimages | page {page} | {len(rows)} indexed entries"]
        for row in selected:
            channels = (row.get("coverage") or {}).get("channels", {})
            observed = sum(int(channel.get("samples", 0)) for channel in channels.values())
            lines.append(f"{row['id']} | {dated(row['anchor_unix_ms'])} | {row['origin']} | {row['status']} | {observed} samples")
        if not selected:
            lines.append("No entries on this page.")
        return {"text": "\n".join(lines), "entries": selected, "page": page, "has_more": page*5 < len(rows)}

    def open_page(self, identifier, page=1):
        if page < 1:
            raise ValueError("page must be positive")
        artifact = self._artifact(identifier)
        notes = self._notes(identifier)
        if artifact is None and not notes:
            raise ValueError("afterimage not found or not visible to this reader")
        if artifact is None:
            note = notes[0]
            receipt = read_json(self.archive / "receipts" / (note["request_id"] + ".json"), {})
            receipt = read_json(self.private / "capture_results" / (note["request_id"] + ".json"), receipt)
            outcome = receipt.get("status", note["capture_status"])
            reason = receipt.get("reason") or "telemetry_not_available"
            if outcome == "pending":
                status = read_json(self.archive / "status.json", {})
                age = now_ms() - status.get("updated_at_unix_ms", 0)
                missing = not (self.archive / "pending" / (identifier + ".json")).exists() and not (self.archive / "requests" / (note["request_id"] + ".json")).exists()
                if not status.get("enabled") or not 0 <= age <= 10_000 or (missing and now_ms()-receipt.get("recorded_at_unix_ms", 0)>10_000):
                    outcome, reason = "incomplete", "capture_worker_or_checkpoint_unavailable"
            artifact = {"id": identifier, "origin": "authored_save", "anchor_unix_ms": note.get("anchor_unix_ms") or note["source_timestamp_unix_ms"] or note["recorded_at_unix_ms"],
                        "status": outcome, "coverage": {}, "samples": [],
                        "measurements": {}, "reasons": [reason]}
        overview = {key: artifact.get(key) for key in ("id", "origin", "anchor_unix_ms", "session_id", "status", "reasons", "coverage")}
        # Each page remains a stable slice of immutable source records, with explicit page numbering.
        sections = [json.dumps(overview, ensure_ascii=False, sort_keys=True, indent=2)]
        for note in notes:
            source_time = dated(note["source_timestamp_unix_ms"]) if note["source_timestamp_unix_ms"] is not None else "original source time unavailable"
            sections.append(f"Authored note {note['note_id']} | {note['author']} | {source_time}\n"
                            f"Source: {json.dumps(note.get('source', {}), ensure_ascii=False, sort_keys=True)}\n{note['text']}")
        sections.append("Measurements\n" + json.dumps(artifact.get("measurements", {}), sort_keys=True, indent=2))
        for event in artifact.get("events", []):
            sections.append("Observed event\n" + json.dumps(event, sort_keys=True, ensure_ascii=False))
        updates = self.archive / "event_updates" / identifier
        if updates.exists():
            for path in sorted(updates.glob("*.json")):
                sections.append("Later event enrichment (original trace unchanged)\n" + json.dumps(read_json(path), sort_keys=True, ensure_ascii=False))
        for sample in artifact.get("samples", []):
            sections.append("Observation\n" + json.dumps(sample, sort_keys=True, ensure_ascii=False))
        links = self.private / "associations" / (identifier + ".jsonl")
        if links.exists():
            sections.append("Source associations (reader-specific)\n" + links.read_text(encoding="utf-8"))
        nearby = [record for record in read_json(self.private / "context_index.json", [])
                  if abs(record.get("timestamp_unix_ms", 0) - artifact["anchor_unix_ms"]) <= 300_000]
        if nearby:
            sections.append("Nearby source records (temporal context)\n" + json.dumps(nearby, sort_keys=True, ensure_ascii=False))
        content = "\n\n".join(sections)
        pages = max(1, (len(content) + PAGE_CHARS - 1) // PAGE_CHARS)
        if page > pages:
            raise ValueError(f"page {page} is beyond the {pages} available pages")
        part = content[(page-1)*PAGE_CHARS:page*PAGE_CHARS]
        text = f"Historical afterimage {identifier} | page {page}/{pages}\n{quoted(part)}"
        return {"text": text, "id": identifier, "page": page, "pages": pages,
                "content_fingerprint": fingerprint(content), "page_fingerprint": fingerprint(text),
                "anchor_unix_ms": artifact["anchor_unix_ms"], "origin": artifact["origin"], "protected": True}

    def keep(self, fragment, source=None, source_ref=None, timestamp_ms=None):
        recorded = now_ms()
        source = dict(source or {})
        text = fragment
        if source_ref is not None:
            path = (self.workspace / source_ref).resolve()
            if not path.is_relative_to(self.workspace) or not path.is_file():
                raise ValueError("source reference must be a file in the author's workspace")
            if path.stat().st_size > 1_048_576:
                raise ValueError("source reference exceeds the 1 MiB snapshot limit")
            with path.open("rb") as handle:
                original = handle.read(1_048_577)
            if len(original) > 1_048_576:
                raise ValueError("source reference exceeds the 1 MiB snapshot limit")
            text = original.decode("utf-8")
            source.update({"path": str(path.relative_to(self.workspace)), "content_fingerprint": fingerprint(text)})
        elif len(text) > 4096:
            raise ValueError("inline fragment exceeds 4096 characters; use source:<workspace-relative path>")
        if not text or not text.strip():
            raise ValueError("an authored fragment or source reference is required")
        source_time = timestamp_ms if timestamp_ms is not None else (
            source.get("original_timestamp_unix_ms") if source_ref is not None else source.get("timestamp_unix_ms", recorded))
        timestamp_ms = int(source_time if source_time is not None else recorded)
        date = dated(timestamp_ms)[:10]
        token = uuid.uuid4().hex
        identifier = f"ai_{date}_authored_{token}"
        note_id, request_id = "note_" + token, "req_" + token
        status = read_json(self.archive / "status.json", {})
        fresh = (source_time is not None and status.get("enabled") is True and 0 <= recorded - status.get("updated_at_unix_ms", 0) <= 10_000)
        note = {"policy": "transition_afterimage_note_v1", "note_id": note_id, "afterimage_id": identifier,
                "request_id": request_id, "author": self.actor, "text": text, "source": source,
                "source_timestamp_unix_ms": int(source_time) if source_time is not None else None,
                "anchor_unix_ms":timestamp_ms, "recorded_at_unix_ms": recorded,
                "capture_status": "pending" if fresh else "incomplete", "content_fingerprint": fingerprint(text)}
        path = self.private / "notes" / (note_id + ".json")
        atomic_json(path, note)
        atomic_json(self.private / "by_artifact" / identifier / (note_id + ".json"), note)
        append_record(self.private / "authorship.jsonl", {key: note[key] for key in ("note_id", "afterimage_id", "author", "recorded_at_unix_ms", "content_fingerprint")})
        self._index_add(self.private, {"id": identifier, "anchor_unix_ms": timestamp_ms, "origin": "authored_save",
                                     "status": note["capture_status"], "coverage": {}})
        if fresh:
            request = {"request_id": request_id, "afterimage_id": identifier,
                       "session_id": source.get("original_session_id" if source_ref else "session_id"),
                       "anchor_engine_t_ms": source.get("original_engine_t_ms" if source_ref else "engine_t_ms"),
                       "anchor_unix_ms": timestamp_ms, "requested_at_unix_ms": recorded}
            try:
                atomic_json(self.archive / "requests" / (request_id + ".json"), request)
            except OSError as error:
                append_record(self.private / "capture_outcomes.jsonl", {"note_id": note_id, "status": "failed", "reason": str(error)})
                atomic_json(self.private / "capture_results" / (request_id + ".json"), {"status":"failed", "reason":str(error)})
                return {"text": f"Saved {note_id}; capture failed: {error}", "id": identifier, "note_id": note_id, "status": "failed"}
        return {"text": f"Saved {note_id} as {identifier}; telemetry {note['capture_status']}.",
                "id": identifier, "note_id": note_id, "status": note["capture_status"]}

    def share(self, note_id):
        if not SAFE_ID.fullmatch(note_id):
            raise ValueError("invalid note id")
        note = read_json(self.private / "notes" / (note_id + ".json"))
        if not note or note.get("author") != self.actor:
            raise ValueError("only the author's own note can be shared")
        identifier = note["afterimage_id"]
        self._id(identifier)
        shared_path = self.archive / "shared_notes" / identifier / (note_id + ".json")
        if not shared_path.exists():
            atomic_json(shared_path, note)
            append_record(self.private / "sharing.jsonl", {"note_id": note_id, "afterimage_id": identifier,
                          "author": self.actor, "shared_at_unix_ms": now_ms(), "content_fingerprint": note["content_fingerprint"]})
        artifact = self._artifact(identifier)
        anchor = artifact["anchor_unix_ms"] if artifact else (note.get("anchor_unix_ms") or note["source_timestamp_unix_ms"] or note["recorded_at_unix_ms"])
        self._index_add(self.archive / "shared_notes", {"id": identifier, "anchor_unix_ms": anchor,
                       "origin": "authored_save", "status": note["capture_status"], "coverage": {}})
        return {"text": f"Shared {note_id}, authored by {self.actor}.", "note_id": note_id, "id": identifier}

    def associate(self, identifier, source, text=None, relation="temporal_context"):
        self._id(identifier)
        if self._artifact(identifier) is None and not self._notes(identifier):
            raise ValueError("association target is unavailable")
        if relation not in {"temporal_context", "authored_reference"}:
            raise ValueError("invalid association relation")
        record = {"afterimage_id": identifier, "author": self.actor, "source": source, "text": text,
                  "relation": relation, "recorded_at_unix_ms": now_ms()}
        if relation == "authored_reference" and text is not None:
            # Explicitly referenced accounts become separately shareable owned notes.
            identity = fingerprint(json.dumps([identifier, self.actor, source, text], sort_keys=True, ensure_ascii=False))
            note_id = "note_" + identity[:32]
            note = {"policy":"transition_afterimage_note_v1", "note_id":note_id, "afterimage_id":identifier,
                    "request_id":"associated_" + identity[:32], "author":self.actor, "source":source, "text":text,
                    "source_timestamp_unix_ms":source.get("timestamp_unix_ms", now_ms()),
                    "recorded_at_unix_ms":now_ms(), "capture_status":"incomplete", "content_fingerprint":fingerprint(text)}
            with locked(self.private / "association_notes.lock"):
                path = self.private / "notes" / (note_id + ".json")
                if not path.exists():
                    atomic_json(path, note)
                    atomic_json(self.private / "by_artifact" / identifier / (note_id + ".json"), note)
                    append_record(self.private / "authorship.jsonl", {key:note[key] for key in ("note_id", "afterimage_id", "author", "recorded_at_unix_ms", "content_fingerprint")})
            record["note_id"] = note_id
            record["text"] = None
        append_record(self.private / "associations" / (identifier + ".jsonl"), record)

    def link_context(self, source, raw_text=""):
        with locked(self.private / "context_index.lock"):
            records = read_json(self.private / "context_index.json", [])
            records.append(source)
            atomic_json(self.private / "context_index.json", records[-INDEX_LIMIT:])
        exact = set(re.findall(r"ai_\d{4}-\d{2}-\d{2}_[A-Za-z0-9_-]+", raw_text))
        if str(source.get("authorship") or "").startswith("minime_owned") and self.actor != "minime":
            exact = set()
        for identifier in exact:
            if self._artifact(identifier) or self._notes(identifier):
                self.associate(identifier, source, raw_text, "authored_reference")
        timestamp = source.get("timestamp_unix_ms")
        if isinstance(timestamp, int):
            for row in self.entries()[:INDEX_LIMIT]:
                if row["id"] not in exact and abs(row["anchor_unix_ms"] - timestamp) <= 300_000:
                    self.associate(row["id"], source, relation="temporal_context")

    def set_cues(self, enabled):
        with locked(self.private / "cues.lock"):
            state = read_json(self.private / "cues.json", {})
            state["enabled"] = bool(enabled)
            atomic_json(self.private / "cues.json", state)
        return {"text": f"Afterimage cues {'on' if enabled else 'off'} for {self.actor}.", "enabled": bool(enabled)}

    def prepare_cue(self, opportunity_id, eligible=True, timestamp_ms=None):
        if not SAFE_ID.fullmatch(opportunity_id):
            raise ValueError("invalid opportunity id")
        timestamp = now_ms() if timestamp_ms is None else int(timestamp_ms)
        state = read_json(self.private / "cues.json", {})
        if not eligible or not state.get("enabled", False):
            return None
        with locked(self.private / "cues.lock"):
            state = read_json(self.private / "cues.json", {})
            if not state.get("enabled", False):
                return None
            cached = state.setdefault("opportunities", {})
            if opportunity_id in cached:
                return cached[opportunity_id]["selection"]
            counter = int(state.get("eligible_count", 0)) + 1
            state["eligible_count"] = counter
            selection = None
            histories = state.setdefault("artifact_opportunities", {})
            if counter % 3 == 0:
                for row in self.entries():
                    age = timestamp - row["anchor_unix_ms"]
                    prior = histories.get(row["id"], [])
                    if age < 0 or age >= 24*HOUR_MS or len(prior) >= 2:
                        continue
                    if prior and timestamp - prior[-1] < 6*HOUR_MS:
                        continue
                    limit = 120 if age >= 6*HOUR_MS else 400
                    text = f"Past {row['id']} | {dated(row['anchor_unix_ms'])} | {row['origin']}"
                    if len(text) > limit:
                        continue  # Never truncate an artifact identity or its historical attribution.
                    notes = self._notes(row["id"])
                    if notes and age < 6*HOUR_MS:
                        excerpt = json.dumps(notes[-1]["text"].replace("\n", " "), ensure_ascii=False)
                        text += f" | {notes[-1]['author']} wrote: {excerpt}"
                    elif age < 6*HOUR_MS:
                        text += f" | {row.get('status', 'coverage unavailable')} physical trace"
                    # The cue is an explicitly bounded excerpt; the saved note stays exact.
                    if len(text) > limit:
                        text = text[:limit-3] + "..."
                    selection = {"id": row["id"], "opportunity_id": opportunity_id, "receiver": self.actor,
                                 "anchor_unix_ms": row["anchor_unix_ms"], "text": text,
                                 "fingerprint": fingerprint(text), "protected": False}
                    histories.setdefault(row["id"], []).append(timestamp)
                    break
            cached[opportunity_id] = {"selection": selection, "created_at_unix_ms": timestamp}
            state["opportunities"] = dict([(key, value) for key, value in cached.items() if timestamp-value["created_at_unix_ms"] <= 48*HOUR_MS][-4096:])
            state["artifact_opportunities"] = {key: value for key, value in histories.items() if value and timestamp-value[-1] <= 48*HOUR_MS}
            atomic_json(self.private / "cues.json", state)
            return selection

    def exposure(self, selection, messages, backend, model, outcome="final_request_prepared", reason=None):
        content = "\n".join(str(message.get("content", "")) for message in messages)
        text = selection["text"]
        included = text in content
        record = {"afterimage_id": selection["id"], "opportunity_id": selection.get("opportunity_id"),
                  "receiver": self.actor, "attempt_id": uuid.uuid4().hex, "backend": backend, "model": model,
                  "content_fingerprint": fingerprint(text), "included": included,
                  "final_messages_fingerprint": fingerprint(json.dumps(messages, ensure_ascii=False, sort_keys=True)),
                  "outcome": outcome, "reason": reason, "recorded_at_unix_ms": now_ms()}
        date = dated(record["recorded_at_unix_ms"])[:10]
        append_record(self.private / "exposures" / (date + ".jsonl"), record)
        return record

    def handle(self, action, source=None):
        base, _, arg = action.partition(" ")
        base, arg = base.upper(), arg.strip()
        if base == "AFTERIMAGE_LIST":
            parts = arg.split()
            date = next((item for item in parts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item)), None)
            page = next((int(item) for item in parts if item.isdigit()), 1)
            return self.list_page(page, date)
        if base == "AFTERIMAGE_OPEN":
            parts = arg.split()
            if len(parts) not in (1, 2):
                raise ValueError("AFTERIMAGE_OPEN requires an id and optional page")
            return self.open_page(parts[0], int(parts[1]) if len(parts) == 2 else 1)
        if base == "AFTERIMAGE_KEEP":
            _, separator, fragment = action.partition("::")
            if not separator:
                raise ValueError("AFTERIMAGE_KEEP requires :: followed by a fragment")
            # Remove only the syntax separator's one optional space, preserving authored whitespace.
            fragment = fragment[1:] if fragment.startswith(" ") else fragment
            if fragment.startswith("source:"):
                return self.keep("", source, fragment[len("source:"):].strip())
            return self.keep(fragment, source)
        if base == "AFTERIMAGE_SHARE":
            return self.share(arg)
        if base == "AFTERIMAGE_CUES" and arg.lower() in {"on", "off"}:
            return self.set_cues(arg.lower() == "on")
        raise ValueError("unknown or malformed afterimage action")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--archive-workspace")
    parser.add_argument("--actor", choices=("minime", "astrid"), default="minime")
    parser.add_argument("action", nargs="*")
    parser.add_argument("--json-request", action="store_true")
    args = parser.parse_args()
    store = AfterimageStore(args.workspace, args.archive_workspace, args.actor)
    try:
        request = json.load(sys.stdin) if args.json_request else {"action": " ".join(args.action)}
        operation = request.get("operation", "action")
        if operation == "cue":
            result = {"selection": store.prepare_cue(request["opportunity_id"], request.get("eligible", True), request.get("timestamp_ms"))}
        elif operation == "exposure":
            result = store.exposure(request["selection"], request["messages"], request["backend"], request["model"],
                                    request.get("outcome", "final_request_prepared"), request.get("reason"))
        elif operation == "select":
            result = store.open_page(request["artifact_id"], int(request.get("page", 1)))
            result.update(content_id="afterimage_open_" + uuid.uuid4().hex,
                          opportunity_id="open_" + uuid.uuid4().hex, receiver=store.actor)
            with locked(store.private / "selection.lock"):
                atomic_json(store.private / "pending_open.json", result)
        elif operation == "ack":
            with locked(store.private / "selection.lock"):
                pending = read_json(store.private / "pending_open.json", {})
                if pending.get("content_id") != request["content_id"]:
                    raise ValueError("Selected page changed; acknowledgement rejected")
                append_record(store.private / "opened.jsonl", {
                    "content_id": request["content_id"], "artifact_id": pending["id"],
                    "timestamp_ms": now_ms(), "receipt": request["receipt"]})
                (store.private / "pending_open.json").unlink()
            result = {"text": "Selected page delivery recorded."}
        elif operation == "associate":
            store.link_context(request["source"], request.get("raw_text", ""))
            result = {"text": "Source associations recorded."}
        else:
            result = store.handle(request["action"], request.get("source"))
        if args.json_request:
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, allow_nan=False))
        else:
            print(result["text"])
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}) if args.json_request else str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
