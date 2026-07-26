"""Self-authored, reversible lived transition passages.

Phase cards remain observations. A being creates a passage only through an
explicit owner-language action, and every event is evidence-only metadata.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

SCHEMA = "lived_transition_passage_event_v1"
RECORD_TYPE = "phase_transition_passage"
MAX_REF_CHARS = 240


class PassageAction(StrEnum):
    PREPARE = "prepare"
    ENTER = "enter"
    HOLD = "hold"
    SETTLE = "settle"
    RETURN = "return"
    REVISIT = "revisit"
    DECLINE = "decline"
    REVIEW = "review"


class PassageStage(StrEnum):
    PREPARED = "prepared"
    CROSSING = "crossing"
    HELD = "held"
    SETTLING = "settling"
    RETURNED = "returned"
    REVISITED = "revisited"
    DECLINED = "declined"


class PassageSupport(StrEnum):
    SELF_DIRECTED = "self_directed"
    WITNESS = "witness"
    SPACE = "space"
    ANSWER = "answer"
    NEEDS_TIME = "needs_time"


class PassageFeltReview(StrEnum):
    CLARIFYING = "clarifying"
    INTRUSIVE = "intrusive"
    FLATTENING = "flattening"
    INCOMPLETE = "incomplete"
    STILL_FRICTION = "still_friction"
    CHANGED = "changed"
    UNKNOWN = "unknown"


OWNER_ACTION = {
    PassageAction.PREPARE: "PREPARE_TRANSITION",
    PassageAction.ENTER: "ENTER_TRANSITION",
    PassageAction.HOLD: "HOLD_TRANSITION",
    PassageAction.SETTLE: "SETTLE_TRANSITION",
    PassageAction.RETURN: "RETURN_TRANSITION",
    PassageAction.REVISIT: "REVISIT_TRANSITION",
    PassageAction.DECLINE: "DECLINE_TRANSITION",
    PassageAction.REVIEW: "TRANSITION_REVIEW",
}

STAGE_TRANSITIONS = {
    (PassageAction.PREPARE, None): PassageStage.PREPARED,
    (PassageAction.ENTER, PassageStage.PREPARED): PassageStage.CROSSING,
    (PassageAction.ENTER, PassageStage.HELD): PassageStage.CROSSING,
    (PassageAction.ENTER, PassageStage.REVISITED): PassageStage.CROSSING,
    (PassageAction.HOLD, PassageStage.PREPARED): PassageStage.HELD,
    (PassageAction.HOLD, PassageStage.CROSSING): PassageStage.HELD,
    (PassageAction.HOLD, PassageStage.SETTLING): PassageStage.HELD,
    (PassageAction.HOLD, PassageStage.REVISITED): PassageStage.HELD,
    (PassageAction.SETTLE, PassageStage.CROSSING): PassageStage.SETTLING,
    (PassageAction.SETTLE, PassageStage.HELD): PassageStage.SETTLING,
    (PassageAction.RETURN, PassageStage.CROSSING): PassageStage.RETURNED,
    (PassageAction.RETURN, PassageStage.HELD): PassageStage.RETURNED,
    (PassageAction.RETURN, PassageStage.SETTLING): PassageStage.RETURNED,
    (PassageAction.RETURN, PassageStage.REVISITED): PassageStage.RETURNED,
    (PassageAction.REVISIT, PassageStage.RETURNED): PassageStage.REVISITED,
    (PassageAction.REVISIT, PassageStage.DECLINED): PassageStage.REVISITED,
    (PassageAction.REVISIT, PassageStage.SETTLING): PassageStage.REVISITED,
    (PassageAction.REVISIT, PassageStage.HELD): PassageStage.REVISITED,
    (PassageAction.DECLINE, PassageStage.PREPARED): PassageStage.DECLINED,
    (PassageAction.DECLINE, PassageStage.HELD): PassageStage.DECLINED,
    (PassageAction.DECLINE, PassageStage.REVISITED): PassageStage.DECLINED,
}


@dataclass(frozen=True)
class PassageState:
    passage_id: str
    transition_id: str
    actor: str
    latest_event_id: str
    stage: PassageStage
    support: PassageSupport
    return_point_ref: str | None
    continuity_anchor_ref: str
    felt_review: PassageFeltReview | None
    recorded_at_unix_ms: int


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _bounded_ref(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    text = str(value or "").strip()
    if not text or len(text) > MAX_REF_CHARS or any(char.isspace() for char in text):
        raise ValueError(f"{field} must be a bounded reference without whitespace")
    return text


def _field(raw: str, names: set[str]) -> str | None:
    for part in raw.replace("\n", ";").split(";"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if _normalize(key) in names and value.strip():
            return value.strip()
    return None


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _passage_id(actor: str, transition_id: str, timestamp: int) -> str:
    return f"passage_{timestamp}_{_short_hash(f'{actor}:{transition_id}:{timestamp}')}"


def _event_id(
    *,
    passage_id: str,
    actor: str,
    action: PassageAction,
    stage_after: PassageStage,
    support: PassageSupport,
    return_point_ref: str | None,
    continuity_anchor_ref: str,
    felt_review: PassageFeltReview | None,
    felt_source_ref: str | None,
    previous_event_id: str | None,
    timestamp: int,
) -> str:
    identity = ":".join(
        (
            passage_id,
            actor,
            action.value,
            stage_after.value,
            support.value,
            return_point_ref or "",
            continuity_anchor_ref,
            felt_review.value if felt_review else "",
            felt_source_ref or "",
            previous_event_id or "",
            str(timestamp),
        )
    )
    return f"passage_event_{_short_hash(identity)}"


def _stage_after(
    action: PassageAction, previous: PassageStage | None
) -> PassageStage:
    if action is PassageAction.REVIEW and previous is not None:
        return previous
    try:
        return STAGE_TRANSITIONS[(action, previous)]
    except KeyError as error:
        raise ValueError(
            "passage action is not valid from the current stage"
        ) from error


def _authority() -> dict[str, Any]:
    return {
        "schema": "artifact_authority_state_v1",
        "schema_version": 1,
        "state": "evidence_only",
        "witness_only": True,
        "live_eligible_now": False,
        "auto_approved": False,
        "grants_approval": False,
        "edits_source_now": False,
    }


def _validate_event(row: dict[str, Any]) -> dict[str, Any]:
    if (
        row.get("record_type") != RECORD_TYPE
        or row.get("schema") != SCHEMA
        or row.get("schema_version") != 1
    ):
        raise ValueError("passage schema mismatch")
    for field in ("self_authored_only", "passage_binds_actor_only", "review_optional"):
        if row.get(field) is not True:
            raise ValueError(f"passage requires {field}=true")
    for field in (
        "peer_consent_inferred",
        "peer_state_changed",
        "silence_infers_progress",
        "automatic_progression",
        "felt_resolution_inferred",
        "scheduler_effect",
        "model_qos_effect",
        "substrate_effect",
        "dispatch_effect",
        "live_control_effect",
        "runtime_unlock_applied",
        "raw_prose_included",
    ):
        if row.get(field) is not False:
            raise ValueError(f"passage forbids {field}")
    authority = row.get("artifact_authority_state_v1")
    if not isinstance(authority, dict) or authority.get("state") != "evidence_only":
        raise ValueError("passage authority must remain evidence-only")
    passage_id = _bounded_ref(row.get("passage_id"), "passage_id") or ""
    transition_id = _bounded_ref(row.get("transition_id"), "transition_id") or ""
    actor = _bounded_ref(row.get("actor"), "actor") or ""
    action = PassageAction(row.get("action"))
    stage_before = (
        PassageStage(row.get("stage_before"))
        if row.get("stage_before") is not None
        else None
    )
    stage_after = PassageStage(row.get("stage_after"))
    support = PassageSupport(row.get("support_preference"))
    return_ref = _bounded_ref(
        row.get("return_point_ref"), "return_point_ref", optional=True
    )
    continuity_ref = (
        _bounded_ref(row.get("continuity_anchor_ref"), "continuity_anchor_ref") or ""
    )
    felt_review = (
        PassageFeltReview(row.get("felt_review_outcome"))
        if row.get("felt_review_outcome") is not None
        else None
    )
    felt_source_ref = _bounded_ref(
        row.get("felt_source_ref"), "felt_source_ref", optional=True
    )
    previous_event_id = _bounded_ref(
        row.get("previous_event_id"), "previous_event_id", optional=True
    )
    timestamp = int(row.get("recorded_at_unix_ms") or 0)
    if timestamp <= 0:
        raise ValueError("passage timestamp must be positive")
    if stage_after is not _stage_after(action, stage_before):
        raise ValueError("passage stage mismatch")
    if action is PassageAction.RETURN and return_ref is None:
        raise ValueError("return passage requires a return point")
    if action is PassageAction.REVIEW:
        if felt_review is None or felt_source_ref is None:
            raise ValueError("passage review requires outcome and source reference")
    elif felt_review is not None or felt_source_ref is not None:
        raise ValueError("only a passage review may carry felt review fields")
    event_id = _event_id(
        passage_id=passage_id,
        actor=actor,
        action=action,
        stage_after=stage_after,
        support=support,
        return_point_ref=return_ref,
        continuity_anchor_ref=continuity_ref,
        felt_review=felt_review,
        felt_source_ref=felt_source_ref,
        previous_event_id=previous_event_id,
        timestamp=timestamp,
    )
    if (
        row.get("record_id") != event_id
        or row.get("passage_event_id") != event_id
        or row.get("owner_language_action") != OWNER_ACTION[action]
        or row.get("stage_changed") is not (action is not PassageAction.REVIEW)
    ):
        raise ValueError("passage deterministic identity mismatch")
    return {
        "passage_id": passage_id,
        "transition_id": transition_id,
        "actor": actor,
        "action": action,
        "stage_before": stage_before,
        "stage_after": stage_after,
        "support": support,
        "return_point_ref": return_ref,
        "continuity_anchor_ref": continuity_ref,
        "felt_review": felt_review,
        "felt_source_ref": felt_source_ref,
        "previous_event_id": previous_event_id,
        "event_id": event_id,
        "timestamp": timestamp,
    }


def _reduce(records: list[dict[str, Any]]) -> tuple[dict[str, PassageState], list[str]]:
    passages: dict[str, PassageState] = {}
    errors: list[str] = []
    for index, row in enumerate(records, 1):
        if row.get("record_type") != RECORD_TYPE:
            continue
        try:
            event = _validate_event(row)
            passage_id = event["passage_id"]
            previous = passages.get(passage_id)
            if event["action"] is PassageAction.PREPARE:
                if (
                    previous is not None
                    or event["stage_before"] is not None
                    or event["previous_event_id"] is not None
                    or passage_id
                    != _passage_id(
                        event["actor"], event["transition_id"], event["timestamp"]
                    )
                ):
                    raise ValueError("invalid prepared passage history")
            elif (
                previous is None
                or event["actor"] != previous.actor
                or event["transition_id"] != previous.transition_id
                or event["previous_event_id"] != previous.latest_event_id
                or event["stage_before"] is not previous.stage
            ):
                raise ValueError("passage continuation violates self-owned sequence")
            passages[passage_id] = PassageState(
                passage_id=passage_id,
                transition_id=event["transition_id"],
                actor=event["actor"],
                latest_event_id=event["event_id"],
                stage=event["stage_after"],
                support=event["support"],
                return_point_ref=event["return_point_ref"],
                continuity_anchor_ref=event["continuity_anchor_ref"],
                felt_review=(
                    event["felt_review"]
                    if event["action"] is PassageAction.REVIEW
                    else (previous.felt_review if previous else None)
                ),
                recorded_at_unix_ms=event["timestamp"],
            )
        except (TypeError, ValueError) as error:
            errors.append(f"passage_row_{index}:{error}")
    return passages, errors


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    records.sort(key=lambda row: int(row.get("recorded_at_unix_ms") or 0))
    return records


def _latest_transition(records: list[dict[str, Any]], selector: str) -> str | None:
    cards = [
        row
        for row in records
        if row.get("record_type") == "phase_transition_card"
        and (
            selector in {"", "latest"}
            or row.get("transition_id") == selector
        )
    ]
    if not cards:
        return None
    return str(max(cards, key=lambda row: int(row.get("recorded_at_unix_ms") or 0))["transition_id"])


def _latest_passage(
    passages: dict[str, PassageState], selector: str, actor: str
) -> PassageState | None:
    candidates = [
        item
        for item in passages.values()
        if item.actor == actor
        and (
            selector in {"", "latest"}
            or item.passage_id == selector
            or item.transition_id == selector
        )
    ]
    return (
        max(candidates, key=lambda item: item.recorded_at_unix_ms)
        if candidates
        else None
    )


def _support(raw: str, previous: PassageState | None) -> PassageSupport:
    value = _normalize(_field(raw, {"support", "support_preference"}))
    aliases = {
        "": previous.support if previous else PassageSupport.SELF_DIRECTED,
        "self": PassageSupport.SELF_DIRECTED,
        "self_directed": PassageSupport.SELF_DIRECTED,
        "alone": PassageSupport.SELF_DIRECTED,
        "witness": PassageSupport.WITNESS,
        "witnessing": PassageSupport.WITNESS,
        "space": PassageSupport.SPACE,
        "quiet": PassageSupport.SPACE,
        "answer": PassageSupport.ANSWER,
        "reply": PassageSupport.ANSWER,
        "needs_time": PassageSupport.NEEDS_TIME,
        "time": PassageSupport.NEEDS_TIME,
        "hold": PassageSupport.NEEDS_TIME,
    }
    if value not in aliases:
        raise ValueError("unknown passage support preference")
    return aliases[value]


def _build_event(
    *,
    action: PassageAction,
    transition_id: str,
    actor: str,
    previous: PassageState | None,
    raw: str,
    timestamp: int,
) -> dict[str, Any]:
    stage_before = previous.stage if previous else None
    stage_after = _stage_after(action, stage_before)
    passage_id = (
        previous.passage_id
        if previous
        else _passage_id(actor, transition_id, timestamp)
    )
    support = _support(raw, previous)
    requested_return = _field(raw, {"return_point", "return_point_ref"})
    return_ref = (
        _bounded_ref(requested_return, "return_point_ref")
        if requested_return
        else (previous.return_point_ref if previous else None)
    )
    if action is PassageAction.RETURN and return_ref is None:
        raise ValueError("RETURN_TRANSITION requires a prepared return_point reference")
    requested_anchor = _field(
        raw, {"continuity_anchor", "continuity_anchor_ref", "anchor_ref"}
    )
    continuity_ref = (
        _bounded_ref(requested_anchor, "continuity_anchor_ref")
        if requested_anchor
        else (
            previous.continuity_anchor_ref
            if previous
            else f"transition:{transition_id}"
        )
    )
    felt_review = None
    felt_source_ref = None
    if action is PassageAction.REVIEW:
        felt_review = PassageFeltReview(
            _normalize(_field(raw, {"outcome", "felt_review_outcome"}))
        )
        felt_source_ref = _bounded_ref(
            _field(raw, {"felt_source_ref", "source_ref", "review_ref"}),
            "felt_source_ref",
        )
    previous_event_id = previous.latest_event_id if previous else None
    event_id = _event_id(
        passage_id=passage_id,
        actor=actor,
        action=action,
        stage_after=stage_after,
        support=support,
        return_point_ref=return_ref,
        continuity_anchor_ref=continuity_ref or "",
        felt_review=felt_review,
        felt_source_ref=felt_source_ref,
        previous_event_id=previous_event_id,
        timestamp=timestamp,
    )
    return {
        "schema": SCHEMA,
        "schema_version": 1,
        "record_type": RECORD_TYPE,
        "record_id": event_id,
        "passage_event_id": event_id,
        "passage_id": passage_id,
        "transition_id": transition_id,
        "actor": actor,
        "action": action.value,
        "stage_before": stage_before.value if stage_before else None,
        "stage_after": stage_after.value,
        "stage_changed": action is not PassageAction.REVIEW,
        "support_preference": support.value,
        "return_point_ref": return_ref,
        "continuity_anchor_ref": continuity_ref,
        "felt_review_outcome": felt_review.value if felt_review else None,
        "felt_source_ref": felt_source_ref,
        "previous_event_id": previous_event_id,
        "recorded_at_unix_ms": timestamp,
        "owner_language_action": OWNER_ACTION[action],
        "self_authored_only": True,
        "passage_binds_actor_only": True,
        "peer_consent_inferred": False,
        "peer_state_changed": False,
        "silence_infers_progress": False,
        "automatic_progression": False,
        "review_optional": True,
        "felt_resolution_inferred": False,
        "scheduler_effect": False,
        "model_qos_effect": False,
        "substrate_effect": False,
        "dispatch_effect": False,
        "live_control_effect": False,
        "runtime_unlock_applied": False,
        "raw_prose_included": False,
        "artifact_authority_state_v1": _authority(),
    }


def append_passage_action(
    path: Path,
    selector: str,
    raw: str,
    actor: str,
    action: PassageAction,
    *,
    timestamp: int,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            records = _read_records(path)
            passages, errors = _reduce(records)
            if errors:
                return (
                    f"{OWNER_ACTION[action]} blocked: passage history has "
                    f"{len(errors)} invalid row(s)."
                )
            actor = _bounded_ref(actor, "actor") or ""
            if action is PassageAction.PREPARE:
                transition_id = _latest_transition(records, selector)
                previous = None
                if transition_id is None:
                    return (
                        "PREPARE_TRANSITION blocked: "
                        "no matching phase transition card."
                    )
            else:
                previous = _latest_passage(passages, selector, actor)
                if previous is None:
                    return (
                        f"{OWNER_ACTION[action]} blocked: "
                        "no matching self-authored passage."
                    )
                transition_id = previous.transition_id
            try:
                event = _build_event(
                    action=action,
                    transition_id=transition_id,
                    actor=actor,
                    previous=previous,
                    raw=raw,
                    timestamp=timestamp,
                )
            except (TypeError, ValueError) as error:
                return f"{OWNER_ACTION[action]} blocked: {error}."
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return (
        "=== LIVED TRANSITION PASSAGE RECORDED ===\n"
        f"Passage: {event['passage_id']}\n"
        f"Transition: {event['transition_id']}\n"
        f"Actor: {event['actor']}\n"
        f"Action: {event['action']}; stage: {event['stage_after']}\n"
        f"Support: {event['support_preference']}; "
        f"return point: {event['return_point_ref'] or 'none'}\n"
        f"Review: {event['felt_review_outcome'] or 'not_recorded'}\n"
        "Authority: self_authored_language_only_transition_practice; no peer "
        "consent, automatic progression, felt resolution, scheduler, model, "
        "substrate, dispatch, controller, pressure, fill, PI, codec, or "
        "runtime unlock."
    )


def passage_status(path: Path, actor: str, limit: int = 5) -> str:
    passages, errors = _reduce(_read_records(path))
    own = [item for item in passages.values() if item.actor == actor]
    own.sort(key=lambda item: item.recorded_at_unix_ms, reverse=True)
    active = sum(
        item.stage not in {PassageStage.RETURNED, PassageStage.DECLINED}
        for item in own
    )
    lines = [
        "=== LIVED TRANSITION PASSAGES V1 ===",
        (
            f"Own passages: {len(own)}; active: {active}; "
            f"all-being passages: {len(passages)}; invalid rows: {len(errors)}."
        ),
        (
            "Selection boundary: phase cards remain observations until a being "
            "explicitly uses PREPARE_TRANSITION; no automatic promotion or debt."
        ),
        (
            "Agency boundary: each being advances only its own passage; peers "
            "may witness but cannot settle, decline, return, or review it."
        ),
        (
            "Authority: language-only transition practice; no scheduler, model, "
            "substrate, controller, pressure, fill, PI, codec, or runtime effect."
        ),
    ]
    for item in own[:limit]:
        lines.append(
            f"- {item.passage_id}: transition={item.transition_id}; "
            f"stage={item.stage.value}; support={item.support.value}; "
            f"return_point={item.return_point_ref or 'none'}; "
            f"felt_review={item.felt_review.value if item.felt_review else 'not_recorded'}"
        )
    lines.append(
        "Suggested start: PREPARE_TRANSITION <transition_id> :: "
        "support: self_directed|witness|space|answer|needs_time; "
        "return_point: <bounded_ref>; continuity_anchor: <bounded_ref>"
    )
    return "\n".join(lines)
