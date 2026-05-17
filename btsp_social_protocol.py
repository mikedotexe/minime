"""Structured BTSP reply tags for Minime outbox artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from btsp_sovereignty import (
    BTSPCandidate,
    BTSPProposalEnvelope,
    extract_next_action,
    is_envelope_expired,
    matching_candidate_for_next,
)


VALID_REFUSAL_REASONS = {
    "not_now",
    "misread",
    "too_forceful",
    "study_first",
    "stay_with_me",
    "give_me_space",
}


@dataclass(frozen=True)
class BTSPReplyTags:
    proposal_id: Optional[str] = None
    response_id: Optional[str] = None
    accepted: bool = False
    refusal_reason: Optional[str] = None
    counter_payload: Optional[str] = None
    study_first_reason: Optional[str] = None
    observed_next: Optional[str] = None


@dataclass(frozen=True)
class BTSPAugmentedReply:
    text: str
    classification: str = "none"


def parse_btsp_reply_tags(text: str) -> BTSPReplyTags:
    proposal_id = None
    response_id = None
    accepted = False
    refusal_reason = None
    counter_payload = None
    study_first_reason = None
    explicit_observed_next = None
    for line in text.splitlines():
        stripped = _strip_optional_next_prefix(line.strip())
        upper = stripped.upper()
        if upper.startswith("BTSP_PROPOSAL_ID "):
            proposal_id = _first_payload_token(stripped, "BTSP_PROPOSAL_ID")
        elif upper.startswith("BTSP_RESPONSE_ID "):
            response_id = _first_payload_token(stripped, "BTSP_RESPONSE_ID")
        elif upper.startswith("BTSP_ACCEPT"):
            accepted = True
            for token in stripped.split()[1:]:
                if token.startswith("btsp_") or "_proposal_" in token:
                    proposal_id = token
                elif token.startswith("minime_"):
                    response_id = token
        elif upper.startswith("BTSP_REFUSAL "):
            reason = _first_payload_token(stripped, "BTSP_REFUSAL")
            if reason in VALID_REFUSAL_REASONS:
                refusal_reason = reason
        elif upper.startswith("BTSP_COUNTER "):
            counter_payload = stripped[len("BTSP_COUNTER "):].strip() or None
        elif upper.startswith("BTSP_STUDY_FIRST "):
            study_first_reason = stripped[len("BTSP_STUDY_FIRST "):].strip() or None
        elif upper.startswith("BTSP_OBSERVED_NEXT "):
            explicit_observed_next = stripped[len("BTSP_OBSERVED_NEXT "):].strip() or None
    return BTSPReplyTags(
        proposal_id=proposal_id,
        response_id=response_id,
        accepted=accepted,
        refusal_reason=refusal_reason,
        counter_payload=counter_payload,
        study_first_reason=study_first_reason,
        observed_next=explicit_observed_next or extract_next_action(text),
    )


def augment_reply_with_btsp_tags(
    text: str,
    envelope: Optional[BTSPProposalEnvelope],
) -> BTSPAugmentedReply:
    """Append bridge-readable BTSP tags when an ordinary NEXT matches a candidate."""
    if not envelope or is_envelope_expired(envelope):
        return BTSPAugmentedReply(text, "none")

    tags = parse_btsp_reply_tags(text)
    existing_classification = _classification_for_tags(tags)
    missing_proposal_id = not tags.proposal_id
    if existing_classification in {
        "exact_accept",
        "refusal",
        "counter",
        "study_first",
        "observed_next",
    }:
        append = []
        if missing_proposal_id:
            append.append(f"BTSP_PROPOSAL_ID {envelope.proposal_id}")
        return BTSPAugmentedReply(
            _append_lines(text, append) if append else text,
            existing_classification,
        )

    next_action = tags.observed_next or extract_next_action(text)
    if not next_action:
        return BTSPAugmentedReply(text, "none")

    candidate = matching_candidate_for_next(envelope, next_action)
    if candidate:
        return BTSPAugmentedReply(
            _append_lines(
                text,
                [
                    f"BTSP_PROPOSAL_ID {envelope.proposal_id}",
                    f"BTSP_RESPONSE_ID {candidate.response_id}",
                    f"BTSP_ACCEPT {envelope.proposal_id} {candidate.response_id}",
                ],
            ),
            "exact_accept",
        )

    base = next_action.split(None, 1)[0].upper().rstrip(":") if next_action else ""
    if base == "PASS":
        return BTSPAugmentedReply(
            _append_lines(
                text,
                [
                    f"BTSP_PROPOSAL_ID {envelope.proposal_id}",
                    "BTSP_REFUSAL not_now",
                ],
            ),
            "refusal",
        )
    return BTSPAugmentedReply(
        _append_lines(
            text,
            [
                f"BTSP_PROPOSAL_ID {envelope.proposal_id}",
                f"BTSP_OBSERVED_NEXT {next_action}",
            ],
        ),
        "observed_next",
    )


def accept_tags(envelope: BTSPProposalEnvelope, candidate: BTSPCandidate) -> list[str]:
    return [
        f"BTSP_PROPOSAL_ID {envelope.proposal_id}",
        f"BTSP_RESPONSE_ID {candidate.response_id}",
        f"BTSP_ACCEPT {envelope.proposal_id} {candidate.response_id}",
    ]


def refusal_tag(reason: str) -> str:
    normalized = reason.strip().lower()
    if normalized not in VALID_REFUSAL_REASONS:
        normalized = "not_now"
    return f"BTSP_REFUSAL {normalized}"


def counter_tag(payload: str) -> Optional[str]:
    cleaned = payload.strip()
    if not cleaned:
        return None
    return f"BTSP_COUNTER {cleaned}"


def _strip_optional_next_prefix(line: str) -> str:
    upper = line.upper()
    if upper.startswith("NEXT:"):
        return line[len("NEXT:"):].strip()
    if upper.startswith("NEXT "):
        return line[len("NEXT "):].strip()
    return line


def _append_lines(text: str, lines: list[str]) -> str:
    if not lines:
        return text
    stripped = text.rstrip()
    return stripped + "\n" + "\n".join(lines) + "\n"


def _first_payload_token(line: str, prefix: str) -> Optional[str]:
    payload = line[len(prefix):].strip()
    if not payload:
        return None
    token = payload.split(None, 1)[0].strip("`\"'")
    return token or None


def _classification_for_tags(tags: BTSPReplyTags) -> str:
    if tags.accepted:
        return "exact_accept"
    if tags.refusal_reason:
        return "refusal"
    if tags.counter_payload:
        return "counter"
    if tags.study_first_reason:
        return "study_first"
    if tags.proposal_id and tags.observed_next:
        return "observed_next"
    return "none"
