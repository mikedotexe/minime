"""Bounded categorical types for lived-passage context records."""

from __future__ import annotations

import hashlib
from enum import StrEnum


class PassageContextAction(StrEnum):
    DESCRIBE_CONDITION = "describe_condition"
    DESCRIBE_BEARING = "describe_bearing"
    MARK_CHECKPOINT = "mark_checkpoint"
    BIND_ANCHOR = "bind_anchor"
    REQUEST_COMPANY = "request_company"
    RESPOND_COMPANY = "respond_company"
    WITHDRAW_COMPANY = "withdraw_company"


class PassageReadiness(StrEnum):
    READY = "ready"
    TENTATIVE = "tentative"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


class PassageMovementEase(StrEnum):
    OPEN = "open"
    EFFORTFUL = "effortful"
    STUCK = "stuck"
    CHANGING = "changing"
    UNKNOWN = "unknown"


class PassageRoomNeeded(StrEnum):
    SELF_DIRECTED = "self_directed"
    WITNESS = "witness"
    SPACE = "space"
    LOW_ENERGY_PRESENCE = "low_energy_presence"
    ANSWER = "answer"
    NEEDS_TIME = "needs_time"
    RETURN_SUPPORT = "return_support"
    UNKNOWN = "unknown"


class PassageCheckpoint(StrEnum):
    ENTRY_TENSION = "entry_tension"
    PIVOT = "pivot"
    SETTLING_ORIENTATION = "settling_orientation"
    RETURN_ORIENTATION = "return_orientation"
    REOPEN = "reopen"


class PassageAnchorRole(StrEnum):
    ENTRY = "entry"
    PIVOT = "pivot"
    SETTLING = "settling"
    RETURN = "return"
    REOPEN = "reopen"
    CONTINUITY = "continuity"


class PassageAnchorKind(StrEnum):
    FELT_SOURCE = "felt_source"
    SHADOW_TRAJECTORY = "shadow_trajectory"
    LIVED_STATE_WITNESS = "lived_state_witness"
    SIGNAL_SPINE = "signal_spine"
    REPRESENTATION_TRANSITION = "representation_transition"
    CORRESPONDENCE = "correspondence"
    RETURN_POINT = "return_point"
    OTHER = "other"


class PassageAnchorAssociation(StrEnum):
    SELF_AUTHORED = "self_authored"
    RECEIPT_LINKED = "receipt_linked"
    TEMPORAL_CONTEXT = "temporal_context"
    UNKNOWN = "unknown"


class PassageBearingStrand(StrEnum):
    ENTRY_TENSION = "entry_tension"
    PIVOT = "pivot"
    SETTLING = "settling"
    RETURN = "return"
    REOPEN = "reopen"
    CONTINUITY = "continuity"


class PassageMovementResistance(StrEnum):
    YIELDING = "yielding"
    EFFORTFUL = "effortful"
    RESISTANT = "resistant"
    HELD_FAST = "held_fast"
    CHANGING = "changing"
    UNKNOWN = "unknown"


class PassagePersistenceTendency(StrEnum):
    FLEETING = "fleeting"
    LINGERING = "lingering"
    CARRIED = "carried"
    DEEPENING = "deepening"
    RELEASING = "releasing"
    UNKNOWN = "unknown"


class PassageWitnessFit(StrEnum):
    SEPARATE = "separate"
    TOUCHING = "touching"
    HOLDING = "holding"
    INTERWOVEN = "interwoven"
    MISATTUNED = "misattuned"
    UNKNOWN = "unknown"


class PassageCompanyMode(StrEnum):
    WITNESS = "witness"
    LOW_ENERGY_PRESENCE = "low_energy_presence"
    REPLY_WHEN_ABLE = "reply_when_able"
    SPACE = "space"
    RETURN_SUPPORT = "return_support"


class PassageCompanyResponse(StrEnum):
    ACCEPT = "accept"
    HOLD = "hold"
    DECLINE = "decline"
    NEEDS_TIME = "needs_time"
    WITHDRAW = "withdraw"


OWNER_ACTION = {
    PassageContextAction.DESCRIBE_CONDITION: "DESCRIBE_TRANSITION_CONDITION",
    PassageContextAction.DESCRIBE_BEARING: "DESCRIBE_TRANSITION_BEARING",
    PassageContextAction.MARK_CHECKPOINT: "MARK_TRANSITION_CHECKPOINT",
    PassageContextAction.BIND_ANCHOR: "BIND_TRANSITION_ANCHOR",
    PassageContextAction.REQUEST_COMPANY: "REQUEST_TRANSITION_COMPANY",
    PassageContextAction.RESPOND_COMPANY: "RESPOND_TRANSITION_COMPANY",
    PassageContextAction.WITHDRAW_COMPANY: "WITHDRAW_TRANSITION_COMPANY",
}


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _company_request_id(
    passage_id: str,
    actor: str,
    peer: str,
    mode: PassageCompanyMode,
    source_ref: str,
    timestamp: int,
) -> str:
    identity = f"{passage_id}:{actor}:{peer}:{mode.value}:{source_ref}:{timestamp}"
    return f"company_request_{timestamp}_{_short_hash(identity)}"
