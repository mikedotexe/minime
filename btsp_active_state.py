"""Durable active BTSP proposal state for Minime.

The bridge owns BTSP memory. This sidecar only keeps Minime's latest active
proposal envelope available long enough for ordinary NEXT replies to receive
machine-readable round-trip metadata.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from btsp_sovereignty import (
    BTSPProposalEnvelope,
    is_envelope_expired,
    proposal_envelope_from_dict,
    proposal_envelope_to_dict,
)


DEFAULT_ACTIVE_PROPOSAL_PATH = (
    Path(__file__).resolve().parent / "workspace" / "runtime" / "btsp_active_proposal.json"
)

TERMINAL_REPLY_CLASSIFICATIONS = {"exact_accept", "refusal", "counter"}
ACTIVE_PROPOSAL_SCHEMA = "minime.btsp.active_proposal.v2"
REPLY_METADATA_KEYS = {
    "last_reply_classification",
    "last_observed_next",
    "last_study_first_reason",
    "last_counteroffer_template",
    "last_refusal_template",
    "study_first_resolution_due",
    "last_replied_at_unix_s",
}

STUDY_FIRST_OBSERVED_BASES = {
    "BROWSE",
    "DECOMPOSE",
    "EXPERIMENT_EVIDENCE",
    "EXPERIMENT_REVIEW",
    "EXAMINE_CODE",
    "INTROSPECT",
    "READ_MORE",
    "SEARCH",
    "SELF_STUDY",
    "THINK_DEEP",
}


def save_active_proposal(
    envelope: BTSPProposalEnvelope,
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
    now_s: Optional[int] = None,
) -> Optional[BTSPProposalEnvelope]:
    if is_envelope_expired(envelope, now_s):
        clear_active_proposal(envelope.proposal_id, path)
        return None
    previous = load_active_proposal_record(path, now_s)
    payload = {
        "schema": ACTIVE_PROPOSAL_SCHEMA,
        "stored_at_unix_s": int(time.time()) if now_s is None else int(now_s),
        "proposal": proposal_envelope_to_dict(envelope),
    }
    if previous and _proposal_id(previous) == envelope.proposal_id:
        for key in REPLY_METADATA_KEYS:
            if key in previous:
                payload[key] = previous[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return envelope


def load_active_proposal_record(
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
    now_s: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        _unlink_quietly(path)
        return None
    if not isinstance(payload, dict):
        _unlink_quietly(path)
        return None
    envelope = proposal_envelope_from_dict(payload.get("proposal"))
    if not envelope:
        _unlink_quietly(path)
        return None
    if is_envelope_expired(envelope, now_s):
        _unlink_quietly(path)
        return None
    payload["proposal"] = proposal_envelope_to_dict(envelope)
    return payload


def load_active_proposal(
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
    now_s: Optional[int] = None,
) -> Optional[BTSPProposalEnvelope]:
    payload = load_active_proposal_record(path, now_s)
    if not payload:
        return None
    envelope = proposal_envelope_from_dict(payload.get("proposal"))
    if not envelope:
        _unlink_quietly(path)
        return None
    return envelope


def active_proposal_metadata(
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
    now_s: Optional[int] = None,
) -> dict[str, Any]:
    payload = load_active_proposal_record(path, now_s)
    if not payload:
        return {}
    return {key: payload[key] for key in REPLY_METADATA_KEYS if key in payload}


def record_active_proposal_reply(
    proposal_id: str,
    classification: str,
    observed_next: Optional[str] = None,
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
    now_s: Optional[int] = None,
    study_first_reason: Optional[str] = None,
) -> bool:
    payload = load_active_proposal_record(path, now_s)
    if not payload or _proposal_id(payload) != proposal_id:
        return False
    payload["schema"] = ACTIVE_PROPOSAL_SCHEMA
    payload["stored_at_unix_s"] = int(time.time()) if now_s is None else int(now_s)
    payload["last_reply_classification"] = classification
    if observed_next and classification == "observed_next":
        payload["last_observed_next"] = observed_next
        payload["last_counteroffer_template"] = _counteroffer_template(observed_next)
        payload["last_refusal_template"] = (
            "BTSP_REFUSAL study_first"
            if _is_study_first_observed_next(observed_next)
            else "BTSP_REFUSAL not_now"
        )
        payload["study_first_resolution_due"] = False
    if study_first_reason and classification == "study_first":
        payload["last_study_first_reason"] = study_first_reason
        prior_observed = payload.get("last_observed_next")
        payload["last_counteroffer_template"] = _counteroffer_template(
            str(prior_observed) if prior_observed else None
        )
        payload["last_refusal_template"] = "BTSP_REFUSAL not_now"
        payload["study_first_resolution_due"] = True
    payload["last_replied_at_unix_s"] = int(time.time()) if now_s is None else int(now_s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return True


def clear_active_proposal(
    expected_proposal_id: Optional[str] = None,
    path: Path = DEFAULT_ACTIVE_PROPOSAL_PATH,
) -> bool:
    if expected_proposal_id:
        current = load_active_proposal(path)
        if current and current.proposal_id != expected_proposal_id:
            return False
    return _unlink_quietly(path)


def should_clear_for_classification(classification: str) -> bool:
    return classification in TERMINAL_REPLY_CLASSIFICATIONS


def _proposal_id(payload: dict[str, Any]) -> Optional[str]:
    proposal = payload.get("proposal")
    if not isinstance(proposal, dict):
        return None
    value = proposal.get("proposal_id")
    return str(value) if value else None


def _counteroffer_template(observed_next: Optional[str]) -> str:
    compact = _compact_action(observed_next)
    base = compact.split(None, 1)[0].upper().rstrip(":") if compact else ""
    if base in {"BTSP_STUDY_FIRST", "BTSP_REFUSAL", "BTSP_COUNTER"}:
        compact = ""
    if compact and base not in STUDY_FIRST_OBSERVED_BASES:
        return "BTSP_COUNTER softer_contact"
    if compact:
        return f"BTSP_COUNTER NEXT: {compact}"
    return "BTSP_COUNTER NEXT: ..."


def _compact_action(action: Optional[str], limit: int = 140) -> str:
    compact = " ".join(str(action or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip()


def _is_study_first_observed_next(observed_next: str) -> bool:
    base = observed_next.strip().split(None, 1)[0].upper().rstrip(":")
    return base in STUDY_FIRST_OBSERVED_BASES


def _unlink_quietly(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
