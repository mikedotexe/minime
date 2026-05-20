"""Prompt support for BTSP signal/proposal context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from btsp_sovereignty import (
    BTSPProposalEnvelope,
    is_envelope_expired,
    parse_proposal_envelope,
    render_exact_choice_lines,
)


DEFAULT_ASTRID_BTSP_STATUS = Path(
    "/Users/v/other/astrid/capsules/consciousness-bridge/workspace/btsp_signal_status.json"
)


def format_btsp_inbox_context(text: str) -> str:
    """Keep Astrid's note intact and add exact Minime-facing BTSP syntax."""
    envelope = parse_proposal_envelope(text)
    if not envelope:
        return text
    exact = "\n".join(render_exact_choice_lines(envelope))
    agency = _format_agency_lines(envelope)
    return (
        f"{text}\n"
        "[BTSP round-trip support]\n"
        f"Proposal id: {envelope.proposal_id}\n"
        f"{agency}"
        "Clear no/almost routes:\n"
        "- `BTSP_STUDY_FIRST need evidence first` if inquiry should be the next BTSP stance.\n"
        "- `BTSP_REFUSAL study_first` if inquiry should come before intervention.\n"
        "- `BTSP_REFUSAL not_now` if this proposal does not fit now.\n"
        "- `BTSP_COUNTER NEXT: ...` if a different offer would fit better.\n"
        "Exact candidate NEXT forms:\n"
        f"{exact}\n"
        "If one fits, write the ordinary NEXT line; the outbox will attach BTSP_ACCEPT metadata. "
        "A clear no or almost is equally valid BTSP agency; write the BTSP_REFUSAL or "
        "BTSP_COUNTER line directly, with or without a NEXT: prefix. Examples: "
        "BTSP_COUNTER NEXT: NOTICE, BTSP_COUNTER NEXT: REGIME recover, "
        "BTSP_COUNTER NEXT: EXPERIMENT BTSP semantic probe, or BTSP_COUNTER softer_contact.\n"
    )


def format_btsp_status_for_prompt(
    status_path: Path = DEFAULT_ASTRID_BTSP_STATUS,
) -> str:
    """Return a compact current BTSP status line, if Astrid has published one."""
    try:
        status = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    detail = str(status.get("detail") or "").strip()
    conversion = status.get("conversion_state") or {}
    if not isinstance(conversion, dict):
        conversion = {}
    state = str(
        conversion.get("composite_state") or conversion.get("state") or ""
    ).strip()
    goal = str(
        conversion.get("conversion_goal") or conversion.get("goal") or ""
    ).strip()
    collapse = str(conversion.get("collapse_state") or "").strip()
    pieces = []
    if detail:
        pieces.append(detail)
    if state or goal:
        conversion_text = f"conversion={state or 'unknown'} goal={goal or 'unknown'}"
        if collapse:
            conversion_text += f" collapse={collapse}"
        pieces.append(conversion_text)
    shared_read = str(status.get("shared_learned_read") or "").strip()
    if shared_read:
        pieces.append(shared_read)
    if not pieces:
        status_line = ""
    else:
        status_line = " | ".join(pieces)
    agency_lines = _format_status_agency_memory(status)
    if not status_line and not agency_lines:
        return ""
    body = status_line
    if agency_lines:
        body = (body + "\n" if body else "") + agency_lines
    return "[BTSP signal status]\n" + body + "\n"


def format_active_btsp_proposal_reminder(
    envelope: BTSPProposalEnvelope,
    metadata: Optional[dict] = None,
) -> str:
    if is_envelope_expired(envelope):
        return ""
    metadata = metadata or {}
    exact = "\n".join(render_exact_choice_lines(envelope))
    agency = _format_agency_lines(envelope)
    already_observed = (
        str(metadata.get("last_reply_classification") or "") == "observed_next"
        and str(metadata.get("last_observed_next") or "").strip()
    )
    already_study_first = (
        str(metadata.get("last_reply_classification") or "") == "study_first"
        and str(metadata.get("last_study_first_reason") or "").strip()
    )
    if already_study_first:
        reason = str(metadata.get("last_study_first_reason") or "").strip()
        counter = _metadata_counter_template(metadata)
        return (
            "[BTSP active proposal reminder]\n"
            f"Proposal id: {envelope.proposal_id}\n"
            f"{agency}"
            "BTSP agency checkpoint: this proposal already has your study-first answer recorded.\n"
            f"Study-first reason: `{reason}`.\n"
            "BTSP closure pending: choose one closure line before another ordinary NEXT.\n"
            "Repeating study-first is duplicate evidence, not a new stance.\n"
            f"- `{counter}` if later evidence points to a better offer.\n"
            "- `BTSP_COUNTER softer_contact` if this offer feels too forceful.\n"
            "- `BTSP_REFUSAL study_first` if inquiry belongs outside this proposal.\n"
            "- `BTSP_REFUSAL not_now` if this proposal should close for now.\n"
            "Evidence/review is useful as resolution evidence; repeated study-first is not.\n"
            "Exact candidate NEXT forms, only if your stance changed:\n"
            f"{exact}\n"
            "This is advisory only. Study-first is agency, not adoption or widening.\n"
        )
    if already_observed:
        observed = str(metadata.get("last_observed_next") or "").strip()
        study_first = _is_study_first_observed_next(observed)
        counter = _metadata_counter_template(metadata, observed)
        refusal = str(metadata.get("last_refusal_template") or "").strip()
        if not refusal:
            refusal = "BTSP_REFUSAL study_first" if study_first else "BTSP_REFUSAL not_now"
        softer_line = (
            ""
            if counter == "BTSP_COUNTER softer_contact"
            else "- `BTSP_COUNTER softer_contact` if this offer feels too forceful.\n"
        )
        study_first_line = (
            "- `BTSP_STUDY_FIRST need evidence first` if the true answer is study/hold this before deciding.\n"
            if study_first
            else ""
        )
        return (
            "[BTSP active proposal reminder]\n"
            f"Proposal id: {envelope.proposal_id}\n"
            f"{agency}"
            "BTSP agency checkpoint: this proposal already has your adjacent answer recorded.\n"
            f"Already recorded adjacent answer: `{observed}`.\n"
            "Repeating that same adjacent move is duplicate evidence, not a new BTSP stance.\n"
            "BTSP closure pending: choose one closure line before another ordinary NEXT.\n"
            f"- `{counter}` if the safer or truer offer is different.\n"
            f"- `{refusal}` if inquiry should come before intervention.\n"
            "- `BTSP_REFUSAL not_now` if this proposal does not fit this window.\n"
            f"{softer_line}"
            f"{study_first_line}"
            "Evidence/review can resolve this window; repeating the same plan/search/decompose cannot.\n"
            "Exact candidate NEXT forms, only if your stance changed:\n"
            f"{exact}\n"
            "This is advisory only. Counteroffers and refusals are valid metadata, not failures.\n"
        )
    return (
        "[BTSP active proposal reminder]\n"
        f"Proposal id: {envelope.proposal_id}\n"
        f"{agency}"
        "Clear no/almost routes:\n"
        "- `BTSP_STUDY_FIRST need evidence first` if inquiry should be the next BTSP stance.\n"
        "- `BTSP_REFUSAL study_first` if inquiry should come before intervention.\n"
        "- `BTSP_REFUSAL not_now` if this proposal does not fit now.\n"
        "- `BTSP_COUNTER NEXT: ...` if a different offer would fit better.\n"
        "Exact candidate NEXT forms:\n"
        f"{exact}\n"
        "This is advisory only. Ordinary NEXT choices remain valid; the outbox attaches "
        "BTSP metadata so Astrid can learn exact, adjacent, refusal, and counteroffer outcomes. "
        "Counteroffers are valid metadata, not failures.\n"
    )


def parse_btsp_note(text: str) -> Optional[BTSPProposalEnvelope]:
    return parse_proposal_envelope(text)


def _format_agency_lines(envelope: BTSPProposalEnvelope) -> str:
    lines: list[str] = []
    if envelope.agency_hypothesis:
        lines.append(f"Agency hypothesis: {envelope.agency_hypothesis}")
    if envelope.reason_codes:
        lines.append("Reason codes: " + ", ".join(envelope.reason_codes[:6]))
    return ("\n".join(lines) + "\n") if lines else ""


def _is_study_first_observed_next(observed_next: str) -> bool:
    base = observed_next.strip().split(None, 1)[0].upper().rstrip(":")
    return base in {
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


def _metadata_counter_template(metadata: dict, observed_next: str = "") -> str:
    template = str(metadata.get("last_counteroffer_template") or "").strip()
    if template:
        return template
    observed = observed_next.strip()
    if observed:
        compact = _compact_action(observed)
        if _is_study_first_observed_next(compact):
            return f"BTSP_COUNTER NEXT: {compact}"
        return "BTSP_COUNTER softer_contact"
    return "BTSP_COUNTER NEXT: ..."


def _compact_action(action: str, limit: int = 140) -> str:
    compact = " ".join(str(action or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip()


def _format_status_agency_memory(status: dict) -> str:
    lines: list[str] = []
    policy = status.get("learned_policy") or []
    if isinstance(policy, list):
        minime_policy = [
            item
            for item in policy
            if isinstance(item, dict) and str(item.get("owner") or "") == "minime"
        ][:2]
        for item in minime_policy:
            label = str(item.get("response_id") or "candidate")
            summary = str(item.get("summary") or "").strip()
            if summary:
                lines.append(f"Recent agency read for {label}: {summary}")
    preferences = status.get("shared_preference_summaries") or []
    if isinstance(preferences, list):
        minime_preferences = [
            item
            for item in preferences
            if isinstance(item, dict) and str(item.get("owner") or "") == "minime"
        ][:2]
        for item in minime_preferences:
            summary = str(item.get("summary") or "").strip()
            if summary:
                lines.append(summary)
    negotiation = status.get("active_negotiation") or {}
    items = negotiation.get("items") if isinstance(negotiation, dict) else []
    if isinstance(items, list):
        incoming = [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("target_owner") or "") == "minime"
        ][:2]
        for item in incoming:
            summary = str(item.get("summary") or "").strip()
            hint = str(item.get("response_hint") or "").strip()
            if summary:
                lines.append(summary + (f" {hint}" if hint else ""))
    return "\n".join(lines)
