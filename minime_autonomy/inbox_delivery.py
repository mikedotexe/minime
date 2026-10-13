"""Sender-bound, language-only inbox provenance. No control or model authority."""

from dataclasses import dataclass
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from .mailbox_fs import Directory


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_event(workspace: Path, stage: str, **fields) -> None:
    row = {
        "schema": "inbox_delivery_v1", "stage": stage,
        "at_unix_s": time.time(), "authority": "language_only", **fields,
    }
    with Directory(workspace, create=True) as root:
        root.child("correspondence", create=True).append(
            "inbox_delivery_v1.jsonl", (json.dumps(row, sort_keys=True) + "\n").encode())


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
    """Split language-only reply blocks from native actions, preserving raw bytes.

    A column-zero declaration can occur after ordinary prose or another reply.
    Even an invalid address ends the preceding reply and keeps its own body out
    of action parsing; only declared_replies validates and routes recipients.
    """
    lines = text.splitlines(keepends=True)
    boundaries = []
    fenced = None
    for i, line in enumerate(lines):
        content = line.rstrip("\r\n")
        fence = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", content)
        if fence:
            marker, suffix = fence.groups()
            if fenced is None:
                fenced = (marker[0], len(marker))
            elif marker[0] == fenced[0] and len(marker) >= fenced[1] and not suffix.strip():
                fenced = None
            continue
        if fenced is not None:
            continue
        declaration = re.fullmatch(r"(?:NEXT:[ \t]*)?INBOX_REPLY(?:[ \t]+(.*))?", content)
        if declaration:
            address = (declaration[1] or "").strip()
            mid = address if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", address) else None
            boundaries.append((i, True, mid))
        elif line.startswith("NEXT:"):
            boundaries.append((i, False, None))
    blocks, removed = [], set()
    for position, (start, is_reply, mid) in enumerate(boundaries):
        if not is_reply:
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
        if mid is None:
            continue
        matches = [m for m in context.messages if m.message_id == mid]
        if (sum(ident == mid for ident, _ in blocks) != 1 or len(matches) != 1
                or matches[0].sender == "unknown" or not body.strip()):
            continue
        result.append((matches[0], body))
    return result


def declared_reply(text: str, context):
    replies = declared_replies(text, context)
    return replies[0] if len(replies) == 1 else None


def save_generation(workspace: Path, text: str, context, *, artifact_id=None, root=None):
    """Do not turn context co-occurrence into an authored address or peer delivery."""
    if artifact_id is not None and not re.fullmatch(r"[0-9a-f]{64}", artifact_id):
        raise ValueError("invalid retained inbox generation identity")
    replies = declared_replies(text, context)
    blocks, action_text = reply_blocks(text)
    # Retain the complete mixed output separately; recipients get only their block.
    if (len(replies) == len(blocks) == 1 and not action_text
            and text.startswith("INBOX_REPLY ")):
        return _save_artifact(workspace, text, context, replies[0], artifact_id=artifact_id, root=root)
    archive = _save_artifact(workspace, text, context, None, artifact_id=artifact_id, root=root)
    for selected in replies:
        reply_identity = digest(artifact_id + "\0" + selected[0].message_id) if artifact_id else None
        _save_artifact(workspace, text, context, selected, source_artifact=archive,
                       artifact_id=reply_identity, root=root)
    return archive


def _publish_once(root, parts, name, content):
    directory = root
    for part in parts:
        directory = directory.child(part, create=True)
    relative = "/".join((*parts, name))
    metadata = json.dumps({"schema": "inbox_publication_v1", "path": relative,
                           "sha256": hashlib.sha256(content).hexdigest()}, sort_keys=True).encode()
    receipts = root.child("correspondence", create=True).child("inbox_publications_v1", create=True)
    with receipts.lock(".publication.lock"):
        receipt = receipts.child(digest(relative), create=True)
        if receipt.created:
            # An intent is durable BEFORE any recipient-visible name can exist.
            receipt.atomic("intent.json", metadata)
        elif not receipt.exists("intent.json"):
            raise ValueError("publication history incomplete; reconcile without republishing")
        if receipt.read("intent.json", 4096) != metadata:
            raise ValueError("publication identity conflict; output retained unchanged")
        if receipt.exists("published.json"):
            if receipt.read("published.json", 4096) != metadata:
                raise ValueError("corrupt publication receipt; no republishing")
            if directory.exists(name) and directory.read(name, max(len(content), 1)) != content:
                raise ValueError("published output conflict; retained unchanged")
            return directory.path / name, True
        if not receipt.created:
            # Absence could mean a recipient already consumed an unacknowledged
            # publication. Never infer permission to publish again from absence.
            if not directory.exists(name):
                raise ValueError("publication uncertain; reconcile without republishing")
            if directory.read(name, max(len(content), 1)) != content:
                raise ValueError("publication conflict; output retained unchanged")
            directory.sync()
        else:
            directory.atomic(name, content)
        receipt.atomic("published.json", metadata)
        return directory.path / name, False


def _save_artifact(workspace, text, context, selected, *, source_artifact=None, artifact_id=None, root=None):
    reply_id = artifact_id or uuid4().hex
    if selected:
        message, body = selected
        if message.sender not in {"mike", "steward", "astrid"}:
            raise ValueError("unsupported inbox reply recipient")
        if message.sender == "astrid":
            parts = ("outbox",)
            name = f"reply_{reply_id}.txt"
            header = (
                f"Correspondence-Reply-To: {message.message_id}\n"
                f"Correspondence-Thread-Id: {message.thread_id}\n"
                "Correspondence-Authority: language_only\n"
            )
        else:
            parts = ("outbox", "human", message.sender)
            name = f"human_reply_{reply_id}.txt"
            header = f"To: {message.sender}\nReply-To: {message.message_id}\nThread-Id: {message.thread_id}\n"
        stage = "authored_reply"
        header = "=== MINIME ADDRESSED REPLY ===\n" + header
        header += "Address evidence: explicit INBOX_REPLY declaration; not inferred engagement\n"
    else:
        parts = ("outbox", "unaddressed")
        name = f"inbox_generation_{reply_id}.txt"
        body = text
        stage = "unaddressed_generation"
        header = "=== INBOX-CONTEXT GENERATION; NOT AN ADDRESSED REPLY ===\n"
    content = (header + "\n" + body).encode("utf-8")
    with nullcontext(root) if root is not None else Directory(workspace, create=True) as filesystem:
        path, reused = _publish_once(filesystem, parts, name, content)
    if isinstance(context, InboxContext):
        context.record(stage, artifact_path=str(path),
                       source_artifact_path=str(source_artifact) if source_artifact else None,
                       supplied_attempt_id=context.last_supplied_attempt,
                       raw_generation_sha256=digest(text),
                       publication_reused=reused,
                       reply_to=selected[0].message_id if selected else None,
                       recipient=selected[0].sender if selected else None)
    return path
