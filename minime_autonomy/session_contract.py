"""Small, non-live contracts for voluntary continuity actions."""

import re


QUIET_SESSION_STATES = frozenset({"parked", "held", "complete"})


class ContinuityReply(str):
    """Keep text callers compatible while carrying a machine-readable outcome."""

    def __new__(cls, message, *, status="handled", record_ref=None):
        reply = super().__new__(cls, message)
        reply.receipt = {
            "schema": "continuity_action_result_v1",
            "status": status,
            "persisted": record_ref is not None,
            "record_ref": record_ref,
            "authority_change": False,
        }
        return reply


def authored_summary(payload, field_reader):
    """A field-only command or help placeholder is not an authored note."""
    summary = field_reader(payload, ["summary", "note", "memory"])
    if summary is None and not re.search(r"(?:^|[;\n])\s*[a-zA-Z_ -]+\s*:", payload):
        summary = payload.strip()
    if not summary or summary.strip() in {"...", "\u2026", "<summary>", "<note>"}:
        return None
    return summary


def latest_sessions(rows):
    """Resolve lifecycle state before looking for an active historical record."""
    latest = {}
    for row in rows:
        session_id = row.get("session_id")
        if session_id and row.get("record_type") != "session_draft":
            latest.pop(session_id, None)
            latest[session_id] = row
    return list(latest.values())


def resolve_session_reference(rows, target):
    """Historical record references identify a session, not a stale live state."""
    record = next((row for row in reversed(rows) if target in {
        str(row.get("session_id") or ""), str(row.get("record_id") or ""),
    }), None)
    if record is None or not record.get("session_id"):
        return record
    return next(row for row in reversed(rows) if row.get("session_id") == record["session_id"])
