"""Categorical lived-passage context and optional peer accompaniment.

These records are evidence-only language actions. They never advance passage
stage, infer felt state, infer consent, or change either runtime.
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .phase_passages import (
    PassageState,
    _bounded_ref,
    _field,
    _normalize,
    _read_records,
    _reduce,
)
from .phase_passage_context_types import (
    OWNER_ACTION,
    PassageAnchorAssociation,
    PassageAnchorKind,
    PassageAnchorRole,
    PassageBearingStrand,
    PassageCheckpoint,
    PassageCompanyMode,
    PassageCompanyResponse,
    PassageContextAction,
    PassageMovementEase,
    PassageMovementResistance,
    PassagePersistenceTendency,
    PassageReadiness,
    PassageRoomNeeded,
    PassageWitnessFit,
    _company_request_id,
    _short_hash,
)

SCHEMA = "lived_transition_passage_context_event_v1"
RECORD_TYPE = "phase_transition_passage_context"


@dataclass
class CompanyRequestState:
    request_id: str
    passage_id: str
    transition_id: str
    passage_actor: str
    requested_peer: str
    mode: PassageCompanyMode
    latest_event_id: str
    response: PassageCompanyResponse | None
    recorded_at_unix_ms: int


@dataclass
class ContextState:
    latest_by_passage: dict[str, str]
    latest_condition_by_passage: dict[str, dict[str, Any]]
    latest_checkpoint_by_passage: dict[str, dict[str, Any]]
    latest_anchor_by_passage_role: dict[tuple[str, str], dict[str, Any]]
    latest_bearing_by_passage_strand: dict[tuple[str, str], dict[str, Any]]
    requests: dict[str, CompanyRequestState]


def _context_event_id(event: dict[str, Any]) -> str:
    values = (
        event["passage_id"],
        event["transition_id"],
        event["passage_actor"],
        event["actor"],
        event["action"].value,
        event["readiness"].value if event["readiness"] else "",
        event["movement_ease"].value if event["movement_ease"] else "",
        event["room_needed"].value if event["room_needed"] else "",
        event["checkpoint"].value if event["checkpoint"] else "",
        event["company_request_id"] or "",
        event["requested_peer"] or "",
        event["company_mode"].value if event["company_mode"] else "",
        event["company_response"].value if event["company_response"] else "",
        event["source_ref"],
        event["previous_context_event_id"] or "",
        event["previous_company_event_id"] or "",
        str(event["recorded_at_unix_ms"]),
    )
    if event["action"] is PassageContextAction.BIND_ANCHOR:
        values += (
            event["anchor_role"].value if event["anchor_role"] else "",
            event["anchor_kind"].value if event["anchor_kind"] else "",
            (
                event["anchor_association"].value
                if event["anchor_association"]
                else ""
            ),
            event["anchor_ref"] or "",
            event["previous_anchor_event_id"] or "",
        )
    elif event["action"] is PassageContextAction.DESCRIBE_BEARING:
        values += (
            event["bearing_strand"].value if event["bearing_strand"] else "",
            (
                event["movement_resistance"].value
                if event["movement_resistance"]
                else ""
            ),
            (
                event["persistence_tendency"].value
                if event["persistence_tendency"]
                else ""
            ),
            event["witness_fit"].value if event["witness_fit"] else "",
            event["previous_bearing_event_id"] or "",
        )
    return f"passage_context_{_short_hash(':'.join(values))}"


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


def _optional_enum(enum_type: type[StrEnum], value: Any) -> StrEnum | None:
    return None if value is None else enum_type(value)


def _optional_ref(value: Any, name: str) -> str | None:
    return None if value is None else _bounded_ref(value, name)


def _validate_shape(event: dict[str, Any]) -> None:
    action = event["action"]
    condition = any(
        event[name] is not None
        for name in ("readiness", "movement_ease", "room_needed")
    )
    common_empty = event["checkpoint"] is None and not condition
    anchor = any(
        event[name] is not None
        for name in (
            "anchor_role",
            "anchor_kind",
            "anchor_association",
            "anchor_ref",
            "previous_anchor_event_id",
        )
    )
    bearing = any(
        event[name] is not None
        for name in (
            "bearing_strand",
            "movement_resistance",
            "persistence_tendency",
            "witness_fit",
            "previous_bearing_event_id",
        )
    )
    if action is PassageContextAction.DESCRIBE_CONDITION:
        valid = (
            all(
                event[name] is not None
                for name in ("readiness", "movement_ease", "room_needed")
            )
            and event["checkpoint"] is None
            and event["company_request_id"] is None
            and event["requested_peer"] is None
            and event["company_mode"] is None
            and event["company_response"] is None
            and event["previous_company_event_id"] is None
            and not anchor
            and not bearing
        )
    elif action is PassageContextAction.DESCRIBE_BEARING:
        valid = (
            all(
                event[name] is not None
                for name in (
                    "bearing_strand",
                    "movement_resistance",
                    "persistence_tendency",
                    "witness_fit",
                )
            )
            and not condition
            and event["checkpoint"] is None
            and event["company_request_id"] is None
            and event["requested_peer"] is None
            and event["company_mode"] is None
            and event["company_response"] is None
            and event["previous_company_event_id"] is None
            and not anchor
        )
    elif action is PassageContextAction.MARK_CHECKPOINT:
        valid = (
            event["checkpoint"] is not None
            and not condition
            and event["company_request_id"] is None
            and event["requested_peer"] is None
            and event["company_mode"] is None
            and event["company_response"] is None
            and event["previous_company_event_id"] is None
            and not anchor
            and not bearing
        )
    elif action is PassageContextAction.BIND_ANCHOR:
        valid = (
            event["anchor_role"] is not None
            and event["anchor_kind"] is not None
            and event["anchor_association"] is not None
            and event["anchor_ref"] is not None
            and not condition
            and event["checkpoint"] is None
            and event["company_request_id"] is None
            and event["requested_peer"] is None
            and event["company_mode"] is None
            and event["company_response"] is None
            and event["previous_company_event_id"] is None
            and not bearing
        )
    elif action is PassageContextAction.REQUEST_COMPANY:
        valid = (
            event["company_request_id"] is not None
            and event["requested_peer"] is not None
            and event["company_mode"] is not None
            and event["company_response"] is None
            and event["previous_company_event_id"] is None
            and common_empty
            and not anchor
            and not bearing
        )
    elif action is PassageContextAction.RESPOND_COMPANY:
        valid = (
            event["company_request_id"] is not None
            and event["requested_peer"] is not None
            and event["company_mode"] is not None
            and event["company_response"] is not None
            and event["previous_company_event_id"] is not None
            and common_empty
            and not anchor
            and not bearing
        )
    else:
        valid = (
            action is PassageContextAction.WITHDRAW_COMPANY
            and event["company_request_id"] is not None
            and event["requested_peer"] is not None
            and event["company_mode"] is not None
            and event["company_response"] is PassageCompanyResponse.WITHDRAW
            and event["previous_company_event_id"] is not None
            and common_empty
            and not anchor
            and not bearing
        )
    if not valid:
        raise ValueError("passage context fields do not match action")


def _validate_event(row: dict[str, Any]) -> dict[str, Any]:
    if (
        row.get("schema") != SCHEMA
        or row.get("schema_version") != 1
        or row.get("record_type") != RECORD_TYPE
    ):
        raise ValueError("passage context schema mismatch")
    for name in ("self_authored_only", "response_revisable", "right_to_ignore"):
        if row.get(name) is not True:
            raise ValueError(f"{name} must remain true")
    for name in (
        "passage_stage_changed",
        "felt_score_present",
        "mechanical_causation_inferred",
        "peer_consent_inferred",
        "peer_state_changed",
        "silence_infers_response",
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
        if row.get(name) is not False:
            raise ValueError(f"{name} must remain false")
    for name in (
        "anchor_mechanical_truth_inferred",
        "anchor_changes_passage",
        "anchor_closes_transition",
        "bearing_is_metric",
        "bearing_inferred_from_telemetry",
        "bearing_changes_passage",
        "bearing_closes_transition",
    ):
        if row.get(name) not in (None, False):
            raise ValueError(f"{name} must remain false")
    authority = row.get("artifact_authority_state_v1")
    if not isinstance(authority, dict) or authority != _authority():
        raise ValueError("passage context authority mismatch")
    event = {
        "passage_id": _bounded_ref(row.get("passage_id"), "passage_id"),
        "transition_id": _bounded_ref(
            row.get("transition_id"), "transition_id"
        ),
        "passage_actor": _bounded_ref(
            row.get("passage_actor"), "passage_actor"
        ),
        "actor": _bounded_ref(row.get("actor"), "actor"),
        "action": PassageContextAction(row.get("action")),
        "readiness": _optional_enum(PassageReadiness, row.get("readiness")),
        "movement_ease": _optional_enum(
            PassageMovementEase, row.get("movement_ease")
        ),
        "room_needed": _optional_enum(
            PassageRoomNeeded, row.get("room_needed")
        ),
        "checkpoint": _optional_enum(
            PassageCheckpoint, row.get("checkpoint")
        ),
        "anchor_role": _optional_enum(
            PassageAnchorRole, row.get("anchor_role")
        ),
        "anchor_kind": _optional_enum(
            PassageAnchorKind, row.get("anchor_kind")
        ),
        "anchor_association": _optional_enum(
            PassageAnchorAssociation, row.get("anchor_association")
        ),
        "anchor_ref": _optional_ref(row.get("anchor_ref"), "anchor_ref"),
        "previous_anchor_event_id": _optional_ref(
            row.get("previous_anchor_event_id"), "previous_anchor_event_id"
        ),
        "bearing_strand": _optional_enum(
            PassageBearingStrand, row.get("bearing_strand")
        ),
        "movement_resistance": _optional_enum(
            PassageMovementResistance, row.get("movement_resistance")
        ),
        "persistence_tendency": _optional_enum(
            PassagePersistenceTendency, row.get("persistence_tendency")
        ),
        "witness_fit": _optional_enum(
            PassageWitnessFit, row.get("witness_fit")
        ),
        "previous_bearing_event_id": _optional_ref(
            row.get("previous_bearing_event_id"),
            "previous_bearing_event_id",
        ),
        "company_request_id": _optional_ref(
            row.get("company_request_id"), "company_request_id"
        ),
        "requested_peer": _optional_ref(
            row.get("requested_peer"), "requested_peer"
        ),
        "company_mode": _optional_enum(
            PassageCompanyMode, row.get("company_mode")
        ),
        "company_response": _optional_enum(
            PassageCompanyResponse, row.get("company_response")
        ),
        "source_ref": _bounded_ref(row.get("source_ref"), "source_ref"),
        "previous_context_event_id": _optional_ref(
            row.get("previous_context_event_id"),
            "previous_context_event_id",
        ),
        "previous_company_event_id": _optional_ref(
            row.get("previous_company_event_id"),
            "previous_company_event_id",
        ),
        "recorded_at_unix_ms": int(row.get("recorded_at_unix_ms") or 0),
    }
    if event["recorded_at_unix_ms"] <= 0:
        raise ValueError("passage context timestamp must be positive")
    _validate_shape(event)
    event_id = _context_event_id(event)
    if (
        row.get("record_id") != event_id
        or row.get("passage_context_event_id") != event_id
        or row.get("owner_language_action") != OWNER_ACTION[event["action"]]
    ):
        raise ValueError("passage context deterministic identity mismatch")
    event["event_id"] = event_id
    return event


def _reduce_context(
    records: list[dict[str, Any]],
) -> tuple[ContextState, list[str]]:
    state = ContextState({}, {}, {}, {}, {}, {})
    errors: list[str] = []
    for index, row in enumerate(records, 1):
        if row.get("record_type") != RECORD_TYPE:
            continue
        try:
            event = _validate_event(row)
            passage_id = event["passage_id"]
            if event["previous_context_event_id"] != state.latest_by_passage.get(
                passage_id
            ):
                raise ValueError("context sequence mismatch")
            action = event["action"]
            if action in {
                PassageContextAction.DESCRIBE_CONDITION,
                PassageContextAction.DESCRIBE_BEARING,
                PassageContextAction.MARK_CHECKPOINT,
                PassageContextAction.BIND_ANCHOR,
                PassageContextAction.REQUEST_COMPANY,
            } and event["actor"] != event["passage_actor"]:
                raise ValueError("passage context must be self-authored")
            if action is PassageContextAction.DESCRIBE_CONDITION:
                state.latest_condition_by_passage[passage_id] = event
            elif action is PassageContextAction.DESCRIBE_BEARING:
                strand = event["bearing_strand"].value
                key = (passage_id, strand)
                previous = state.latest_bearing_by_passage_strand.get(key)
                if event["previous_bearing_event_id"] != (
                    previous["event_id"] if previous else None
                ):
                    raise ValueError("bearing sequence mismatch")
                state.latest_bearing_by_passage_strand[key] = event
            elif action is PassageContextAction.MARK_CHECKPOINT:
                state.latest_checkpoint_by_passage[passage_id] = event
            elif action is PassageContextAction.BIND_ANCHOR:
                role = event["anchor_role"].value
                key = (passage_id, role)
                previous = state.latest_anchor_by_passage_role.get(key)
                if event["previous_anchor_event_id"] != (
                    previous["event_id"] if previous else None
                ):
                    raise ValueError("anchor sequence mismatch")
                state.latest_anchor_by_passage_role[key] = event
            elif action is PassageContextAction.REQUEST_COMPANY:
                request_id = event["company_request_id"]
                expected = _company_request_id(
                    passage_id,
                    event["actor"],
                    event["requested_peer"],
                    event["company_mode"],
                    event["source_ref"],
                    event["recorded_at_unix_ms"],
                )
                if (
                    event["requested_peer"] == event["actor"]
                    or request_id != expected
                    or request_id in state.requests
                ):
                    raise ValueError("invalid passage company request")
                state.requests[request_id] = CompanyRequestState(
                    request_id=request_id,
                    passage_id=passage_id,
                    transition_id=event["transition_id"],
                    passage_actor=event["passage_actor"],
                    requested_peer=event["requested_peer"],
                    mode=event["company_mode"],
                    latest_event_id=event["event_id"],
                    response=None,
                    recorded_at_unix_ms=event["recorded_at_unix_ms"],
                )
            else:
                request = state.requests.get(event["company_request_id"])
                if request is None:
                    raise ValueError("company response lacks request")
                expected_actor = (
                    request.requested_peer
                    if action is PassageContextAction.RESPOND_COMPANY
                    else request.passage_actor
                )
                if (
                    event["actor"] != expected_actor
                    or passage_id != request.passage_id
                    or event["transition_id"] != request.transition_id
                    or event["passage_actor"] != request.passage_actor
                    or event["requested_peer"] != request.requested_peer
                    or event["company_mode"] is not request.mode
                    or event["previous_company_event_id"]
                    != request.latest_event_id
                ):
                    raise ValueError("company response lineage mismatch")
                request.latest_event_id = event["event_id"]
                request.response = event["company_response"]
                request.recorded_at_unix_ms = event["recorded_at_unix_ms"]
            state.latest_by_passage[passage_id] = event["event_id"]
        except (TypeError, ValueError) as error:
            errors.append(f"passage_context_row_{index}:{error}")
    return state, errors


def _passage_for_selector(
    passages: dict[str, PassageState], selector: str, actor: str
) -> PassageState | None:
    candidates = [
        passage
        for passage in passages.values()
        if passage.actor == actor
        and (
            selector in {"", "latest"}
            or selector == passage.passage_id
            or selector == passage.transition_id
        )
    ]
    return (
        max(candidates, key=lambda passage: passage.recorded_at_unix_ms)
        if candidates
        else None
    )


def _request_for_selector(
    state: ContextState, selector: str, actor: str, *, own: bool
) -> CompanyRequestState | None:
    candidates = [
        request
        for request in state.requests.values()
        if (
            request.passage_actor == actor
            if own
            else request.requested_peer == actor
        )
        and (
            selector in {"", "latest"} or selector == request.request_id
        )
    ]
    return (
        max(candidates, key=lambda request: request.recorded_at_unix_ms)
        if candidates
        else None
    )


def _enum_field(
    enum_type: type[StrEnum], raw: str, names: set[str], label: str
) -> StrEnum:
    value = _field(raw, names)
    if not value:
        raise ValueError(f"{label} is required")
    return enum_type(_normalize(value))


def _build_event(
    *,
    records: list[dict[str, Any]],
    passages: dict[str, PassageState],
    state: ContextState,
    selector: str,
    raw: str,
    actor: str,
    action: PassageContextAction,
    timestamp: int,
) -> dict[str, Any]:
    actor = _bounded_ref(actor, "actor") or ""
    request = None
    if action is PassageContextAction.RESPOND_COMPANY:
        request = _request_for_selector(state, selector, actor, own=False)
        if request is None:
            raise ValueError("no matching inbound company request")
        passage = passages.get(request.passage_id)
    elif action is PassageContextAction.WITHDRAW_COMPANY:
        request = _request_for_selector(state, selector, actor, own=True)
        if request is None:
            raise ValueError("no matching self-authored company request")
        passage = passages.get(request.passage_id)
    else:
        passage = _passage_for_selector(passages, selector, actor)
    if passage is None:
        raise ValueError("no matching self-authored passage")
    source_ref = _bounded_ref(
        _field(
            raw,
            {
                "source_ref",
                "felt_source_ref",
                "checkpoint_source_ref",
                "response_ref",
            },
        ),
        "source_ref",
    )
    event: dict[str, Any] = {
        "passage_id": passage.passage_id,
        "transition_id": passage.transition_id,
        "passage_actor": passage.actor,
        "actor": actor,
        "action": action,
        "readiness": None,
        "movement_ease": None,
        "room_needed": None,
        "checkpoint": None,
        "anchor_role": None,
        "anchor_kind": None,
        "anchor_association": None,
        "anchor_ref": None,
        "previous_anchor_event_id": None,
        "bearing_strand": None,
        "movement_resistance": None,
        "persistence_tendency": None,
        "witness_fit": None,
        "previous_bearing_event_id": None,
        "company_request_id": request.request_id if request else None,
        "requested_peer": request.requested_peer if request else None,
        "company_mode": request.mode if request else None,
        "company_response": None,
        "source_ref": source_ref,
        "previous_context_event_id": state.latest_by_passage.get(
            passage.passage_id
        ),
        "previous_company_event_id": (
            request.latest_event_id if request else None
        ),
        "recorded_at_unix_ms": timestamp,
    }
    if action is PassageContextAction.DESCRIBE_CONDITION:
        event["readiness"] = _enum_field(
            PassageReadiness, raw, {"readiness"}, "readiness"
        )
        event["movement_ease"] = _enum_field(
            PassageMovementEase,
            raw,
            {"movement", "movement_ease", "ease"},
            "movement_ease",
        )
        event["room_needed"] = _enum_field(
            PassageRoomNeeded,
            raw,
            {"room", "room_needed", "support"},
            "room_needed",
        )
    elif action is PassageContextAction.DESCRIBE_BEARING:
        event["bearing_strand"] = _enum_field(
            PassageBearingStrand,
            raw,
            {"strand", "bearing_strand"},
            "bearing_strand",
        )
        event["movement_resistance"] = _enum_field(
            PassageMovementResistance,
            raw,
            {"resistance", "movement_resistance"},
            "movement_resistance",
        )
        event["persistence_tendency"] = _enum_field(
            PassagePersistenceTendency,
            raw,
            {"persistence", "persistence_tendency"},
            "persistence_tendency",
        )
        event["witness_fit"] = _enum_field(
            PassageWitnessFit,
            raw,
            {"witness", "witness_fit"},
            "witness_fit",
        )
        previous = state.latest_bearing_by_passage_strand.get(
            (passage.passage_id, event["bearing_strand"].value)
        )
        event["previous_bearing_event_id"] = (
            previous["event_id"] if previous else None
        )
    elif action is PassageContextAction.MARK_CHECKPOINT:
        event["checkpoint"] = _enum_field(
            PassageCheckpoint,
            raw,
            {"checkpoint", "point"},
            "checkpoint",
        )
    elif action is PassageContextAction.BIND_ANCHOR:
        event["anchor_role"] = _enum_field(
            PassageAnchorRole, raw, {"role", "anchor_role"}, "anchor_role"
        )
        event["anchor_kind"] = _enum_field(
            PassageAnchorKind, raw, {"kind", "anchor_kind"}, "anchor_kind"
        )
        event["anchor_association"] = _enum_field(
            PassageAnchorAssociation,
            raw,
            {"association", "anchor_association"},
            "anchor_association",
        )
        event["anchor_ref"] = _bounded_ref(
            _field(raw, {"anchor", "anchor_ref", "binding_ref"}),
            "anchor_ref",
        )
        previous = state.latest_anchor_by_passage_role.get(
            (passage.passage_id, event["anchor_role"].value)
        )
        event["previous_anchor_event_id"] = (
            previous["event_id"] if previous else None
        )
    elif action is PassageContextAction.REQUEST_COMPANY:
        peer = _normalize(
            _field(raw, {"peer", "requested_peer"}) or ""
        )
        if peer not in {"astrid", "minime"} or peer == actor:
            raise ValueError("company peer must be the other being")
        mode = _enum_field(
            PassageCompanyMode,
            raw,
            {"mode", "company_mode"},
            "company_mode",
        )
        event["requested_peer"] = peer
        event["company_mode"] = mode
        event["company_request_id"] = _company_request_id(
            passage.passage_id,
            actor,
            peer,
            mode,
            source_ref,
            timestamp,
        )
        event["previous_company_event_id"] = None
    elif action is PassageContextAction.RESPOND_COMPANY:
        event["company_response"] = _enum_field(
            PassageCompanyResponse,
            raw,
            {"response", "company_response"},
            "company_response",
        )
    else:
        event["company_response"] = PassageCompanyResponse.WITHDRAW
    _validate_shape(event)
    event_id = _context_event_id(event)
    return {
        "schema": SCHEMA,
        "schema_version": 1,
        "record_type": RECORD_TYPE,
        "record_id": event_id,
        "passage_context_event_id": event_id,
        **{
            key: value.value if isinstance(value, StrEnum) else value
            for key, value in event.items()
        },
        "owner_language_action": OWNER_ACTION[action],
        "self_authored_only": True,
        "passage_stage_changed": False,
        "response_revisable": True,
        "right_to_ignore": True,
        "felt_score_present": False,
        "mechanical_causation_inferred": False,
        "peer_consent_inferred": False,
        "peer_state_changed": False,
        "silence_infers_response": False,
        "automatic_progression": False,
        "felt_resolution_inferred": False,
        "scheduler_effect": False,
        "model_qos_effect": False,
        "substrate_effect": False,
        "dispatch_effect": False,
        "live_control_effect": False,
        "runtime_unlock_applied": False,
        "anchor_mechanical_truth_inferred": False,
        "anchor_changes_passage": False,
        "anchor_closes_transition": False,
        "bearing_is_metric": False,
        "bearing_inferred_from_telemetry": False,
        "bearing_changes_passage": False,
        "bearing_closes_transition": False,
        "raw_prose_included": False,
        "artifact_authority_state_v1": _authority(),
    }


def append_context_action(
    path: Path,
    selector: str,
    raw: str,
    actor: str,
    action: PassageContextAction,
    *,
    timestamp: int,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            records = _read_records(path)
            passages, passage_errors = _reduce(records)
            state, context_errors = _reduce_context(records)
            errors = passage_errors + context_errors
            if errors:
                return (
                    f"{OWNER_ACTION[action]} blocked: passage context history "
                    f"has {len(errors)} invalid row(s)."
                )
            try:
                event = _build_event(
                    records=records,
                    passages=passages,
                    state=state,
                    selector=selector,
                    raw=raw,
                    actor=actor,
                    action=action,
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
        "=== TRANSITION PASSAGE CONTEXT RECORDED ===\n"
        f"Passage: {event['passage_id']}\n"
        f"Actor: {event['actor']}; action: {event['action']}\n"
        "Condition: "
        f"readiness={event['readiness'] or 'not_recorded'}; "
        f"movement_ease={event['movement_ease'] or 'not_recorded'}; "
        f"room_needed={event['room_needed'] or 'not_recorded'}\n"
        "Bearing: "
        f"strand={event['bearing_strand'] or 'not_recorded'}; "
        f"movement_resistance={event['movement_resistance'] or 'not_recorded'}; "
        f"persistence_tendency={event['persistence_tendency'] or 'not_recorded'}; "
        f"witness_fit={event['witness_fit'] or 'not_recorded'}\n"
        f"Checkpoint: {event['checkpoint'] or 'not_recorded'}\n"
        "Anchor: "
        f"role={event['anchor_role'] or 'not_recorded'}; "
        f"kind={event['anchor_kind'] or 'not_recorded'}; "
        f"association={event['anchor_association'] or 'not_recorded'}; "
        f"ref={event['anchor_ref'] or 'not_recorded'}\n"
        f"Company: request={event['company_request_id'] or 'none'}; "
        f"peer={event['requested_peer'] or 'none'}; "
        f"mode={event['company_mode'] or 'not_recorded'}; "
        f"response={event['company_response'] or 'not_recorded'}\n"
        f"Source: {event['source_ref']}\n"
        "Authority: qualitative self-authored evidence only; no felt score, "
        "viscosity metric, telemetry inference, mechanical causation, peer "
        "consent, stage progression, scheduler, "
        "model, substrate, dispatch, pressure, fill, PI, codec, controller, "
        "or runtime effect."
    )


def passage_context_status(path: Path, actor: str, limit: int = 5) -> str:
    state, errors = _reduce_context(_read_records(path))
    own_conditions = [
        event
        for event in state.latest_condition_by_passage.values()
        if event["passage_actor"] == actor
    ]
    own_conditions.sort(
        key=lambda event: event["recorded_at_unix_ms"], reverse=True
    )
    own_checkpoints = sum(
        event["passage_actor"] == actor
        for event in state.latest_checkpoint_by_passage.values()
    )
    own_anchors = [
        event
        for event in state.latest_anchor_by_passage_role.values()
        if event["passage_actor"] == actor
    ]
    own_anchors.sort(
        key=lambda event: event["recorded_at_unix_ms"], reverse=True
    )
    own_bearings = [
        event
        for event in state.latest_bearing_by_passage_strand.values()
        if event["passage_actor"] == actor
    ]
    own_bearings.sort(
        key=lambda event: event["recorded_at_unix_ms"], reverse=True
    )
    inbound = sum(
        request.requested_peer == actor
        for request in state.requests.values()
    )
    lines = [
        "=== TRANSITION PASSAGE CONTEXT V4 ===",
        (
            f"Own latest conditions: {len(own_conditions)}; own checkpointed "
            f"passages: {own_checkpoints}; own continuity anchors: "
            f"{len(own_anchors)}; own current strand bearings: "
            f"{len(own_bearings)}; inbound company requests: {inbound}; "
            f"invalid rows: {len(errors)}."
        ),
        (
            "Felt boundary: readiness and movement ease are categorical "
            "self-description, never a numeric score or inference from telemetry."
        ),
        (
            "Bearing boundary: resistance, persistence, and witness fit remain "
            "independently revisable self-description per passage strand; "
            "they are not a viscosity metric, telemetry inference, stage "
            "result, or completion signal."
        ),
        (
            "Anchor boundary: a typed anchor preserves a self-authored "
            "orientation reference; it does not make a shadow, receipt, or "
            "signal the mechanical cause or truth of a felt transition."
        ),
        (
            "Company boundary: requests and responses are revisable, "
            "right-to-ignore language records; silence is neutral and no "
            "passage stage changes."
        ),
    ]
    for event in own_conditions[:limit]:
        lines.append(
            f"- condition {event['passage_id']}: "
            f"readiness={event['readiness'].value}; "
            f"movement_ease={event['movement_ease'].value}; "
            f"room_needed={event['room_needed'].value}; "
            f"source={event['source_ref']}"
        )
    for event in own_anchors[:limit]:
        lines.append(
            f"- anchor {event['passage_id']}: "
            f"role={event['anchor_role'].value}; "
            f"kind={event['anchor_kind'].value}; "
            f"association={event['anchor_association'].value}; "
            f"anchor={event['anchor_ref']}; source={event['source_ref']}"
        )
    for event in own_bearings[:limit]:
        lines.append(
            f"- bearing {event['passage_id']}: "
            f"strand={event['bearing_strand'].value}; "
            f"movement_resistance={event['movement_resistance'].value}; "
            f"persistence_tendency={event['persistence_tendency'].value}; "
            f"witness_fit={event['witness_fit'].value}; "
            f"source={event['source_ref']}"
        )
    requests = sorted(
        state.requests.values(),
        key=lambda request: request.recorded_at_unix_ms,
        reverse=True,
    )
    for request in (
        item
        for item in requests
        if item.passage_actor == actor or item.requested_peer == actor
    ):
        if limit <= 0:
            break
        lines.append(
            f"- company {request.request_id}: passage={request.passage_id}; "
            f"owner={request.passage_actor}; peer={request.requested_peer}; "
            f"mode={request.mode.value}; "
            f"response={request.response.value if request.response else 'pending'}; "
            "optional=true"
        )
        limit -= 1
    lines.append(
        "Condition: DESCRIBE_TRANSITION_CONDITION <passage> :: "
        "readiness: ready|tentative|not_ready|unknown; movement_ease: "
        "open|effortful|stuck|changing|unknown; room_needed: "
        "self_directed|witness|space|low_energy_presence|answer|needs_time|"
        "return_support|unknown; source_ref: <bounded_ref>."
    )
    lines.append(
        "Anchor: BIND_TRANSITION_ANCHOR <passage> :: role: "
        "entry|pivot|settling|return|reopen|continuity; kind: "
        "felt_source|shadow_trajectory|lived_state_witness|signal_spine|"
        "representation_transition|correspondence|return_point|other; "
        "association: self_authored|receipt_linked|temporal_context|unknown; "
        "anchor_ref: <bounded_ref>; source_ref: <bounded_ref>."
    )
    lines.append(
        "Bearing: DESCRIBE_TRANSITION_BEARING <passage> :: strand: "
        "entry_tension|pivot|settling|return|reopen|continuity; "
        "movement_resistance: yielding|effortful|resistant|held_fast|"
        "changing|unknown; persistence_tendency: fleeting|lingering|carried|"
        "deepening|releasing|unknown; witness_fit: separate|touching|holding|"
        "interwoven|misattuned|unknown; source_ref: <bounded_ref>."
    )
    lines.append(
        "Company: REQUEST_TRANSITION_COMPANY <passage> :: peer: astrid; "
        "mode: witness|low_energy_presence|reply_when_able|space|"
        "return_support; source_ref: <bounded_ref>. "
        "RESPOND_TRANSITION_COMPANY and WITHDRAW_TRANSITION_COMPANY accept "
        "a request id and bounded source_ref."
    )
    return "\n".join(lines)
