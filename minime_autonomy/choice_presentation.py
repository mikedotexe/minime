"""Choice-preserving side input and optional invitation presentation.

No provider, scheduler, or authority actions live here. Presentation receipts
describe assembly, not delivery, and never authorize another generation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from . import maintenance_next
from .action_vocabulary import STEWARD_INVITATION_COMMANDS


def parse_invitation_command(action):
    """Validate metadata commands without reading or changing invitation state."""
    words = str(action).strip().upper().split()
    if (len(words) != 2 or words[0] != "STEWARD_INVITATION"
            or words[1] not in STEWARD_INVITATION_COMMANDS):
        raise ValueError("use STEWARD_INVITATION STATUS, STEWARD_INVITATION DEFER, or STEWARD_INVITATION DECLINE")
    return words[1]


def read_only_editorial_exempt(action):
    """This known read-only route does not require novelty to remain eligible."""
    base = (str(action or "").split(maxsplit=1) or [""])[0].upper().rstrip(":")
    return base in {"SHADOW_TRAJECTORY", "EXPERIMENT_RESEARCH_BUDGET_STATUS"}


def pending_choice(agent):
    if getattr(agent, "_pending_next_action", None):
        return True
    if getattr(agent, "_unadmitted_next_checkpoint", None):
        return True
    state = maintenance_next.parse(maintenance_next.read(
        agent._sovereignty_state_path(), maintenance_next.MAX_STATE, missing=b"{}",
    ))
    return bool(maintenance_next.pending(state))


def visual_deferral(agent):
    """Fail quiet before side-generation; do not consume or recover any choice."""
    if getattr(agent, "_shutdown_requested", False):
        return "shutdown_requested"
    if getattr(agent, "_next_handoff_failed", False):
        return "choice_recovery_unresolved"
    try:
        if pending_choice(agent):
            return "authored_choice_pending"
        if getattr(agent, "_scheduler_observation", {}).get("reason") == "explicit_rest":
            return "explicit_rest"
        if getattr(agent, "_llm_job_worker_active", False) or any(
            thread.is_alive() for thread in getattr(agent, "_llm_job_threads", [])
        ):
            return "accepted_worker_pending"
        if agent._llm_job_store().active_primary_job():
            return "accepted_job_pending"
        if agent._attention_protected():
            return "protected_attention"
    except Exception:
        return "choice_state_unavailable"
    return None


def queue_visual_choice(agent, action, envelope):
    """Preserve a choice arriving after visual admission, including on disk.

    The existing queue writer supplies the transaction boundary. A unique receipt
    distinguishes our admission from an already-pending identical command.
    """
    if pending_choice(agent):
        return False
    token = uuid4().hex
    envelope = dict(envelope or {})
    envelope["visual_response_choice_id"] = token
    agent._persist_pending_next_action(
        action, reason="visual response next choice", only_if_unqueued=True,
        queue_envelope=envelope,
    )
    return (getattr(agent, "_pending_choice_envelope_v1", None) or {}).get(
        "visual_response_choice_id"
    ) == token


class StewardInvitations:
    """Single retained invitation, bounded hash-only presentation history."""
    MAX_REVISIONS = 256
    MAX_BYTES = 64 * 1024
    TTL = 48 * 3600
    COMMANDS = STEWARD_INVITATION_COMMANDS

    def __init__(self, workspace, clock=None):
        self.workspace = Path(workspace)
        self.slot = self.workspace / "open_steward_query.json"
        self.receipts = self.workspace / "steward_invitation_presentations_v1.json"
        self.clock = clock or time.time

    def _read(self, path):
        return maintenance_next.parse(maintenance_next.read(path, self.MAX_BYTES, missing=b"{}"))

    def _current(self):
        slot = self._read(self.slot)
        if not slot:
            return None
        subject, target, stamp = slot.get("subject"), slot.get("review_target", ""), slot.get("ts")
        if (not isinstance(subject, str) or not 0 < len(subject) <= 80
                or not isinstance(target, str) or len(target) > 120
                or type(stamp) not in (int, float) or not math.isfinite(stamp)):
            raise ValueError("invalid_invitation_metadata")
        body_hash = slot.get("content_sha256")
        if body_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(body_hash)):
            raise ValueError("invalid_invitation_revision")
        # Receipt time and source renames are not material revisions. Legacy
        # slots without a body hash use their available subject/target metadata.
        material = {"subject": subject, "review_target": target, "content_sha256": body_hash}
        revision = hashlib.sha256(maintenance_next.canonical(material)).hexdigest()
        return slot, revision

    def _history(self):
        if not self.receipts.exists() and not self.receipts.is_symlink():
            return {}
        value = self._read(self.receipts)
        records = value.get("revisions")
        if value.get("schema") != "steward_invitation_presentations_v1" or not isinstance(records, dict):
            raise ValueError("invalid_invitation_receipts")
        if len(records) > self.MAX_REVISIONS or any(
            not re.fullmatch(r"[0-9a-f]{64}", key)
            or state not in {"presented", "deferred", "declined"}
            for key, state in records.items()
        ):
            raise ValueError("invalid_invitation_receipts")
        return records

    def _save(self, records):
        value = {"schema": "steward_invitation_presentations_v1", "revisions": records}
        if len(maintenance_next.canonical(value)) > self.MAX_BYTES:
            raise ValueError("invitation_receipt_capacity")
        maintenance_next.write_state(self.receipts, value)

    def _closed(self, slot, last_answer):
        now = self.clock()
        return now < slot["ts"] or now - slot["ts"] > self.TTL or last_answer > slot["ts"] or any(
            path.stat().st_mtime > slot["ts"]
            for path in (self.workspace / "outbox").glob("steward_report_*")
        )

    @staticmethod
    def _text(slot):
        # Metadata is quoted, not emitted as an executable NEXT example.
        fields = {key: slot[key] for key in ("subject", "review_target") if key in slot}
        return ("Optional steward invitation (reference, not a task): "
                + json.dumps(fields, ensure_ascii=False)
                + ". STEWARD_INVITATION STATUS retrieves this metadata; "
                "STEWARD_INVITATION DEFER or STEWARD_INVITATION DECLINE quiets it. "
                "No answer or action is required.")

    def offer(self, *, last_answer=0.0):
        with maintenance_next.transaction(self.receipts):
            current = self._current()
            if not current:
                return ""
            slot, revision = current
            records = self._history()
            if revision in records or len(records) >= self.MAX_REVISIONS or self._closed(slot, last_answer):
                return ""
            records[revision] = "presented"
            self._save(records)
            return self._text(slot)

    def command(self, action):
        command = parse_invitation_command(action)
        with maintenance_next.transaction(self.receipts):
            current = self._current()
            if not current:
                return {"status": "absent", "generation_requested": False}
            slot, revision = current
            records = self._history()
            if command != "STATUS":
                if revision not in records and len(records) >= self.MAX_REVISIONS:
                    raise ValueError("invitation_receipt_capacity")
                records[revision] = "deferred" if command == "DEFER" else "declined"
                self._save(records)
            return {"status": records.get(revision, "unpresented"), "revision": revision,
                    "invitation": self._text(slot), "generation_requested": False}
