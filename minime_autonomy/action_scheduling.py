"""Regulation-request admission and content-free scheduler observations.

The existing NEXT slot and its transaction/handoff remain authoritative. These
observations neither schedule work nor establish delivery or completion.
"""
from datetime import datetime, timezone
from functools import wraps
import hashlib
import logging


REGULATION_ACTIONS = {
    "self_experiment": "SELF_EXPERIMENT",
    "compose_audio": "COMPOSE_AUDIO",
    "reservoir_read": "RESERVOIR_READ",
    "reservoir_resonance": "RESERVOIR_RESONANCE",
    "self_study": "SELF_STUDY",
    "introspect": "INTROSPECT",
}


def observation(agent, reason):
    agent._scheduler_observation = {
        "reason": reason,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def decision(method):
    @wraps(method)
    def call(agent, *args, **kwargs):
        observation(agent, "decision_in_progress")
        try:
            result = method(agent, *args, **kwargs)
        except Exception:
            observation(agent, "decision_failed")
            raise
        if getattr(agent, "_shutdown_requested", False):
            observation(agent, "shutdown_requested")
        elif result is not None:
            observation(agent, "action_selected_not_yet_executed")
        elif agent._scheduler_observation["reason"] == "decision_in_progress":
            observation(agent, "decision_returned_no_route")
        return result
    return call


def snapshot(agent):
    """Inspect process metadata only; never invoke a reader or inspect prose."""
    return {
        "schema": "action_scheduler_v1",
        "pending_choice_present": bool(getattr(agent, "_pending_next_action", None)),
        "last_observation": dict(getattr(agent, "_scheduler_observation", {
            "reason": "not_observed", "observed_at": None,
        })),
        "last_regulation_request": dict(getattr(agent, "_regulation_action_receipt", {})),
    }


def queue_regulation_request(agent, requested, *, response_next=None, response=""):
    """Normalize a fresh JSON action into the normal, guarded durable queue.

    Explicit NEXT (including REST) wins. Do not remember a deferred request for
    replay after protection, a different choice, or a restart.
    """
    if requested is None or requested == "":
        return
    command = REGULATION_ACTIONS.get(requested) if isinstance(requested, str) else None
    receipt = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "status": "unsupported_request" if command is None else "not_queued",
    }
    agent._regulation_action_receipt = receipt
    if command is None:
        return
    if getattr(agent, "_shutdown_requested", False) or getattr(agent, "_next_handoff_failed", False):
        receipt["status"] = "deferred_shutdown_or_recovery"
    elif response_next or getattr(agent, "_pending_next_action", None):
        receipt["status"] = "deferred_explicit_choice"
    elif getattr(agent, "_unadmitted_next_checkpoint", None):
        receipt["status"] = "deferred_unadmitted_choice"
    elif agent._attention_protected():
        receipt["status"] = "deferred_protected_work"
    else:
        envelope = {
            "policy": "choice_envelope_v1", "schema_version": 1,
            "source": "regulation_review_json_action",
            "authority": "diagnostic_context_not_command",
            "primary_next": command, "alternate_nexts": [], "return_threads": [],
            "regulation_request_v1": {
                "requested_action": requested, "canonical_action": command,
                "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                "authored_next_line": False,
            },
        }
        try:
            agent._persist_pending_next_action(
                command, reason="regulation review action request",
                only_if_unqueued=True, queue_envelope=envelope,
            )
        except Exception:
            receipt["status"] = "persistence_failed"
            if hasattr(agent, "_agent_boot_id"):
                agent._next_handoff_failed = True
            raise
        # A concurrent durable NEXT wins even when it names the same command.
        if getattr(agent, "_pending_choice_envelope_v1", None) == envelope:
            receipt["status"] = "queued_not_executed"
        else:
            receipt["status"] = "deferred_existing_durable_choice"
    logging.info("Regulation action request: %s [%s]", command, receipt["status"])
