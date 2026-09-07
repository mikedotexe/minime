"""Sender-bound, language-only inbox provenance. No control or model authority."""

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_event(workspace: Path, stage: str, **fields) -> None:
    path = workspace / "correspondence" / "inbox_delivery_v1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": "inbox_delivery_v1", "stage": stage,
        "at_unix_s": time.time(), "authority": "language_only", **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class InboxMessage:
    message_id: str
    sender: str
    thread_id: str
    filename: str
    source_sha256: str
    rendered_text: str

    @classmethod
    def from_source(cls, filename: str, source: str, rendered: str):
        # Only the leading envelope supplies addresses, never quoted body headers.
        header = source.split("\n\n", 1)[0]
        fields = {}
        for line in header.splitlines()[1:]:
            key, sep, value = line.partition(":")
            if sep:
                key = key.strip().lower()
                if key in fields:
                    fields = {}
                    break
                fields[key] = value.strip()
        human = (filename.startswith("human_letter_")
                 and source.startswith("=== HUMAN LETTER V1 ===\n"))
        peer = (filename.startswith("from_astrid_correspondence_")
                and source.startswith("=== CORRESPONDENCE V1 ===\n"))
        sender = fields.get("from", "").lower()
        valid = (fields.get("to", "").lower() == "minime"
                 and ((human and sender in {"mike", "steward"})
                      or (peer and sender == "astrid")))
        mid = fields.get("message-id", "")
        thread = fields.get("thread-id", "")
        valid = valid and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,120}", mid))
        valid = valid and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,120}", thread))
        if not valid:
            sender = "unknown"
            mid = "file_" + digest(filename + "\0" + source)[:24]
            thread = mid
        return cls(mid, sender, thread, filename, digest(source), rendered)

    def receipt(self):
        return {
            "message_id": self.message_id, "sender": self.sender,
            "thread_id": self.thread_id, "filename": self.filename,
            "source_text_sha256": self.source_sha256,
            "rendered_text_sha256": digest(self.rendered_text),
        }


class InboxContext(str):
    def __new__(cls, text, messages, workspace):
        obj = super().__new__(cls, text)
        obj.messages = tuple(messages)
        obj.workspace = workspace
        obj.batch_id = "inbox_" + uuid4().hex
        obj.supplied = False
        obj.last_supplied_attempt = None
        return obj

    def record(self, stage, **fields):
        append_event(self.workspace, stage, batch_id=self.batch_id,
                     messages=[m.receipt() for m in self.messages], **fields)

    def prepared(self, messages, model):
        contents = [m["content"] for m in messages]
        if not any(str(self) in part for part in contents):
            raise ValueError("admitted inbox context missing from model request")
        if any(m.rendered_text not in str(self) for m in self.messages):
            raise ValueError("admitted message missing from protected context")
        attempt = "submission_" + uuid4().hex
        self.record("request_prepared", attempt_id=attempt, model=model,
                    request_messages_sha256=digest(json.dumps(messages, sort_keys=True)),
                    protected_context_sha256=digest(str(self)),
                    protected_context_chars=len(self))
        return attempt

    def accepted(self, attempt, model):
        self.record("supplied_to_model", attempt_id=attempt, model=model,
                    semantics="complete protected text in HTTP-accepted inference request; not attention or understanding")
        self.supplied = True
        self.last_supplied_attempt = attempt


class InboxPrompt(str):
    """Keep the admission boundary attached to this call, not mutable agent state."""

    def __new__(cls, ambient, inbox):
        obj = super().__new__(cls, ambient + str(inbox))
        obj.ambient = ambient
        obj.inbox = inbox
        return obj


class InboxGeneration(str):
    """Preserve authored output while keeping reply bodies out of action parsing."""

    def __new__(cls, text, action_text):
        obj = super().__new__(cls, text)
        obj.action_text = action_text
        return obj


def reply_blocks(text):
    """Recognize unquoted standalone declarations, not examples inside fences."""
    lines = text.splitlines(keepends=True)
    boundaries = []
    fenced = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fenced = None if fenced == marker else (fenced or marker)
            continue
        if fenced is not None:
            continue
        match = re.fullmatch(r"(?:NEXT: )?INBOX_REPLY ([A-Za-z0-9_-]{1,120})", line.rstrip("\r\n"))
        if match and (i == 0 or line.startswith("NEXT: ")):
            boundaries.append((i, match[1]))
        elif line.startswith("NEXT:"):
            boundaries.append((i, None))
    blocks, removed = [], set()
    for position, (start, mid) in enumerate(boundaries):
        if mid is None:
            continue
        end = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(lines)
        body = "".join(lines[start + 1:end])
        blocks.append((mid, body))
        removed.update(range(start, end))
    return blocks, "".join(line for i, line in enumerate(lines) if i not in removed)


def declared_replies(text: str, context):
    blocks, _ = reply_blocks(text)
    if not isinstance(context, InboxContext) or not context.supplied:
        return []
    result = []
    for mid, body in blocks:
        matches = [m for m in context.messages if m.message_id == mid]
        if (sum(ident == mid for ident, _ in blocks) != 1 or len(matches) != 1
                or matches[0].sender == "unknown" or not body.strip()):
            continue
        result.append((matches[0], body))
    return result


def declared_reply(text: str, context):
    replies = declared_replies(text, context)
    return replies[0] if len(replies) == 1 else None


def save_generation(workspace: Path, text: str, context):
    """Do not turn context co-occurrence into an authored address or peer delivery."""
    replies = declared_replies(text, context)
    blocks, action_text = reply_blocks(text)
    # Retain the complete mixed output separately; recipients get only their block.
    if (len(replies) == len(blocks) == 1 and not action_text
            and text.startswith("INBOX_REPLY ")):
        return _save_artifact(workspace, text, context, replies[0])
    archive = _save_artifact(workspace, text, context, None)
    for selected in replies:
        _save_artifact(workspace, text, context, selected, source_artifact=archive)
    return archive


def _save_artifact(workspace, text, context, selected, *, source_artifact=None):
    reply_id = uuid4().hex
    if selected:
        message, body = selected
        if message.sender == "astrid":
            directory = workspace / "outbox"
            name = f"reply_{reply_id}.txt"
            header = (
                f"Correspondence-Reply-To: {message.message_id}\n"
                f"Correspondence-Thread-Id: {message.thread_id}\n"
                "Correspondence-Authority: language_only\n"
            )
        else:
            directory = workspace / "outbox" / "human" / message.sender
            name = f"human_reply_{reply_id}.txt"
            header = f"To: {message.sender}\nReply-To: {message.message_id}\nThread-Id: {message.thread_id}\n"
        stage = "authored_reply"
        header = "=== MINIME ADDRESSED REPLY ===\n" + header
        header += "Address evidence: explicit INBOX_REPLY declaration; not inferred engagement\n"
    else:
        directory = workspace / "outbox" / "unaddressed"
        name = f"inbox_generation_{reply_id}.txt"
        body = text
        stage = "unaddressed_generation"
        header = "=== INBOX-CONTEXT GENERATION; NOT AN ADDRESSED REPLY ===\n"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # Exclusive creation and a durable artifact before claiming a saved reply.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(header + "\n" + body)
        handle.flush()
        os.fsync(handle.fileno())
    if isinstance(context, InboxContext):
        context.record(stage, artifact_path=str(path),
                       source_artifact_path=str(source_artifact) if source_artifact else None,
                       supplied_attempt_id=context.last_supplied_attempt,
                       raw_generation_sha256=digest(text),
                       reply_to=selected[0].message_id if selected else None,
                       recipient=selected[0].sender if selected else None)
    return path
