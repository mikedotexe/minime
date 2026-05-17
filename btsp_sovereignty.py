"""BTSP proposal parsing and exact Minime NEXT mapping.

The bridge owns BTSP memory; this module only helps Minime read proposal
envelopes and express consent/refusal in a form the bridge can pair exactly.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional


ENVELOPE_START = "BTSP_ENVELOPE_JSON_START"
ENVELOPE_END = "BTSP_ENVELOPE_JSON_END"


@dataclass(frozen=True)
class BTSPCandidate:
    response_id: str
    action: str
    kind: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    next_action: str = ""
    rationale: str = ""
    policy_state: str = ""


@dataclass(frozen=True)
class BTSPProposalEnvelope:
    proposal_id: str
    episode_id: str
    owner: str
    expires_at_unix_s: Optional[int] = None
    signal_fingerprint: str = ""
    source: str = ""
    agency_hypothesis: str = ""
    reason_codes: tuple[str, ...] = ()
    lineage: tuple[str, ...] = ()
    evidence_window: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[BTSPCandidate, ...] = ()


def parse_proposal_envelope(text: str) -> Optional[BTSPProposalEnvelope]:
    """Parse the structured BTSP envelope embedded in Astrid's inbox note."""
    raw_json = _extract_envelope_json(text)
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return proposal_envelope_from_dict(data)


def proposal_envelope_from_dict(data: Any) -> Optional[BTSPProposalEnvelope]:
    """Parse a BTSP proposal envelope from a JSON-compatible dictionary."""
    if not isinstance(data, dict):
        return None
    proposal_id = str(data.get("proposal_id") or "").strip()
    episode_id = str(data.get("episode_id") or "").strip()
    owner = str(data.get("owner") or "").strip()
    if not proposal_id or not episode_id or owner != "minime":
        return None
    candidates = []
    for item in data.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        response_id = str(item.get("response_id") or "").strip()
        action = str(item.get("action") or "").strip()
        if not response_id or not action:
            continue
        params = item.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        candidates.append(
            BTSPCandidate(
                response_id=response_id,
                action=action,
                kind=str(item.get("kind") or ""),
                parameters=params,
                next_action=str(item.get("next_action") or ""),
                rationale=str(item.get("rationale") or ""),
                policy_state=str(item.get("policy_state") or ""),
            )
        )
    expires = data.get("expires_at_unix_s")
    if not isinstance(expires, int):
        expires = None
    return BTSPProposalEnvelope(
        proposal_id=proposal_id,
        episode_id=episode_id,
        owner=owner,
        expires_at_unix_s=expires,
        signal_fingerprint=str(data.get("signal_fingerprint") or ""),
        source=str(data.get("source") or ""),
        agency_hypothesis=str(data.get("agency_hypothesis") or ""),
        reason_codes=tuple(
            str(item)
            for item in data.get("reason_codes") or []
            if str(item).strip()
        ),
        lineage=tuple(
            str(item)
            for item in data.get("lineage") or []
            if str(item).strip()
        ),
        evidence_window=(
            data.get("evidence_window") if isinstance(data.get("evidence_window"), dict) else {}
        ),
        candidates=tuple(candidates),
    )


def proposal_envelope_to_dict(envelope: BTSPProposalEnvelope) -> dict[str, Any]:
    """Return a JSON-compatible dictionary for durable active-proposal state."""
    return {
        "proposal_id": envelope.proposal_id,
        "episode_id": envelope.episode_id,
        "owner": envelope.owner,
        "expires_at_unix_s": envelope.expires_at_unix_s,
        "signal_fingerprint": envelope.signal_fingerprint,
        "source": envelope.source,
        "agency_hypothesis": envelope.agency_hypothesis,
        "reason_codes": list(envelope.reason_codes),
        "lineage": list(envelope.lineage),
        "evidence_window": envelope.evidence_window,
        "candidates": [
            {
                "response_id": candidate.response_id,
                "kind": candidate.kind,
                "action": candidate.action,
                "parameters": candidate.parameters,
                "next_action": candidate.next_action,
                "rationale": candidate.rationale,
                "policy_state": candidate.policy_state,
            }
            for candidate in envelope.candidates
        ],
    }


def is_envelope_expired(
    envelope: Optional[BTSPProposalEnvelope],
    now_s: Optional[int] = None,
) -> bool:
    """Return true when an envelope has a bounded expiry and it has passed."""
    if envelope is None or envelope.expires_at_unix_s is None:
        return False
    current = int(time.time()) if now_s is None else int(now_s)
    return current >= envelope.expires_at_unix_s


def extract_next_action(text: str) -> Optional[str]:
    """Return the final NEXT action body from a response, if present."""
    found: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("NEXT:"):
            action = stripped[5:].strip()
            if action:
                found = action
    return found


def normalize_next_action(action: str) -> str:
    """Normalize Minime NEXT syntax into the bridge's comparison key."""
    trimmed = action.strip()
    if trimmed.upper().startswith("NEXT:"):
        trimmed = trimmed[5:].strip()
    regime_match = re.match(r"^REGIME\s*:?\s+([A-Za-z0-9_-]+)$", trimmed, re.IGNORECASE)
    if regime_match:
        return f"REGIME:{regime_match.group(1).upper()}"
    if trimmed.upper().startswith("REGIME:"):
        return trimmed.upper().replace(" ", "")
    return (trimmed.split(None, 1)[0] if trimmed else "").strip().upper()


def candidate_next_action(candidate: BTSPCandidate) -> str:
    """Return the exact NEXT action Minime should write for a candidate."""
    if candidate.action.lower() == "regime":
        regime = str(candidate.parameters.get("regime") or "recover").strip().lower()
        return f"REGIME {regime}"
    if candidate.response_id == "minime_semantic_probe":
        return "EXPERIMENT BTSP semantic probe"
    return candidate.action


def matching_candidate_for_next(
    envelope: BTSPProposalEnvelope,
    next_action: str,
) -> Optional[BTSPCandidate]:
    normalized = normalize_next_action(next_action)
    for candidate in envelope.candidates:
        if normalize_next_action(candidate_next_action(candidate)) == normalized:
            return candidate
    return None


def render_exact_choice_lines(envelope: BTSPProposalEnvelope) -> list[str]:
    lines = []
    for candidate in envelope.candidates:
        lines.append(
            f"- {candidate.response_id}: NEXT: {candidate_next_action(candidate)}"
        )
    return lines


def _extract_envelope_json(text: str) -> Optional[str]:
    start = text.find(ENVELOPE_START)
    end = text.find(ENVELOPE_END)
    if start < 0 or end < 0 or end <= start:
        return None
    start += len(ENVELOPE_START)
    return text[start:end].strip() or None
