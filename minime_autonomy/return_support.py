"""Truthful presence/readability facts, never permission to execute a saved action."""

from .continuity_snapshot import (
    EvidenceUnavailable, StableSnapshot, exact_experiment, valid_identifier, validate_thread,
)


def project_return_support(reference, thread_next, record, guarded_return_kind=None):
    """Pure shared contract; callers validate persistent records before projection."""
    reference = reference if isinstance(reference, str) and reference.strip() else None
    readable = (reference is not None and isinstance(record, dict)
                and record.get("experiment_id") == reference)
    if reference is None:
        status, scope, next_value = "absent", "thread", thread_next
    elif readable:
        status, scope, next_value = "verified_readable", "experiment", record.get("planned_next")
    else:
        status, scope, next_value = "unavailable", "unavailable", None
    return {
        "schema_version": 1,
        "experiment_reference": reference,
        "record_status": status,
        "saved_next_action": ("unknown" if status == "unavailable" else
                              "present" if isinstance(next_value, str) and next_value.strip() else "absent"),
        "saved_next_action_scope": scope,
        "guarded_return_kind": guarded_return_kind if readable else None,
        "execution_eligibility": "not_evaluated",
    }


def unavailable_return_support(reference):
    result = project_return_support(reference, None, None)
    result.update(record_status="unavailable", saved_next_action="unknown",
                  saved_next_action_scope="unavailable")
    return result


def read_return_support(thread, experiments_path, explicit_reference, paused_return, *, snapshot=None):
    if not isinstance(thread, dict):
        return unavailable_return_support(explicit_reference)
    reference = explicit_reference if explicit_reference is not None else thread.get("active_experiment_id")
    reference = reference if isinstance(reference, str) and reference.strip() else None
    record, kind = None, None
    try:
        snapshot = snapshot or StableSnapshot()
        if reference is not None:
            record, _ = exact_experiment(snapshot, experiments_path, reference)
        snapshot.verify()
    except EvidenceUnavailable:
        return unavailable_return_support(reference)
    if record is not None and record.get("status", "").lower() == "paused":
        kind = paused_return(reference, record.get("planned_next"),
                             record.get("primary_return_next") or record.get("resume_next")).get("return_kind")
    return project_return_support(reference, thread.get("current_next"), record, kind)


def saved_return_support(thread_path, experiments_path, explicit_reference, paused_return, owner):
    """Validate the saved thread as well: an unreadable thread is not an absent reference."""
    try:
        snapshot = StableSnapshot()
        snapshot.directory(thread_path.parent)
        thread = snapshot.json(thread_path)
        validate_thread(thread, thread_path.parent.name, owner)
        reference = explicit_reference if explicit_reference is not None else thread.get("active_experiment_id")
        if reference and (not valid_identifier(reference) or not reference.startswith(f"exp_{owner}_")):
            return unavailable_return_support(reference)
        return read_return_support(thread, experiments_path, explicit_reference, paused_return, snapshot=snapshot)
    except EvidenceUnavailable:
        return unavailable_return_support(explicit_reference)


def return_support_line(support):
    return (
        "Return support (return_support_v1): "
        f"reference={support['experiment_reference'] or '(none)'} "
        f"record_status={support['record_status']} "
        f"saved_next_action={support['saved_next_action']} "
        f"saved_next_action_scope={support['saved_next_action_scope']} "
        f"guarded_return_kind={support['guarded_return_kind'] or '(none)'} "
        "execution_eligibility=not_evaluated. Snapshot facts at capture, "
        "not live eligibility or recovered understanding.\n"
    )


def retired_heuristic_line(*allowances):
    if any(isinstance(allowance, dict) and "returnability" in allowance for allowance in allowances):
        return "Historical motif returnability: retired heuristic; stored value is not displayed or used.\n"
    return ""
