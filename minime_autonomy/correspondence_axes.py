"""Independent correspondence axes for Minime's compatibility status path."""

from __future__ import annotations

from typing import Any


def correspondence_relation_axes_v4(
    *,
    role: str,
    reply_linked: bool,
    ack_present: bool,
    ack_is_address_evidence: bool,
    trace_observed: bool,
    attention_outcome_present: bool,
    read: bool,
    delivered: bool,
) -> dict[str, Any]:
    mutual_address_evidence = (
        ack_is_address_evidence or trace_observed or attention_outcome_present
    )
    if trace_observed:
        continuity_state, continuity_basis = "active", "direct_address_trace"
        mutual_address_state = "confirmed_by_trace"
    elif attention_outcome_present:
        continuity_state, continuity_basis = "active", "attention_outcome"
        mutual_address_state = "confirmed_by_attention_outcome"
    elif ack_is_address_evidence:
        continuity_state = "active"
        continuity_basis = "being_authored_address_receipt"
        mutual_address_state = "confirmed_by_being_authored_receipt"
    elif reply_linked:
        continuity_state, continuity_basis = "active", "reply_chain"
        mutual_address_state = "not_confirmed"
    elif ack_present or read:
        continuity_state = "visible"
        continuity_basis = "seen_or_read_without_address_evidence"
        mutual_address_state = "not_confirmed"
    elif delivered:
        continuity_state, continuity_basis = "visible", "delivery_receipt"
        mutual_address_state = "not_confirmed"
    else:
        continuity_state, continuity_basis = "unaddressed", "none"
        mutual_address_state = "not_confirmed"

    if mutual_address_evidence:
        attention_state = "eligible_from_current_evidence"
        receipt_posture = "already_present"
    else:
        attention_state = "blocked_no_being_authored_address_evidence"
        receipt_posture = (
            "optional_being_authored"
            if role == "recipient"
            else "peer_authored_optional_no_substitution"
        )

    return {
        "schema_version": 4,
        "policy": "correspondence_relation_axes_v4",
        "continuity_axis": {
            "state": continuity_state,
            "basis": continuity_basis,
            "requires_new_action": continuity_state != "active",
        },
        "mutual_address_axis": {
            "state": mutual_address_state,
            "evidence_present": mutual_address_evidence,
            "silence_inferred": False,
        },
        "authority_axis": {
            "attention": attention_state,
            "semantic_microdose": (
                "separate_mutual_receipt_and_steward_review_required"
            ),
            "live_control": "not_granted",
        },
        "action_axis": {
            "receipt_posture": receipt_posture,
            "right_to_ignore": True,
            "reply_chain_requires_receipt_to_remain_continuous": False,
            "runtime_may_substitute_peer_evidence": False,
        },
        "causality_axis": {
            "pressure_effect": "not_measured_no_inference",
            "felt_effect": "not_established",
        },
        "compatibility": {
            "native_thread_continuity_v3_retained": True,
        },
        "authority": "derived_language_context_not_control",
    }


__all__ = ["correspondence_relation_axes_v4"]
