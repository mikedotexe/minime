"""Shared operating-stack metadata for Minime continuity surfaces."""

from __future__ import annotations

import re

from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 1
LOCAL_RESEARCH_MAX_ACTIONS = 5
LOCAL_RESEARCH_TTL_SECS = 21600
LOOP_RESEARCH_MAX_ACTIONS = 5
LOOP_TTL_SECS = 21600
LOOP_CONSEQUENCE_MAX_SENDS = 1
AUTHORITY_BUDGET_MAX_SENDS = 3
STEWARD_RESEARCH_MAX_ACTIONS = 8
READ_ONLY_RESEARCH_SCOPE = "read_only_research"
SEMANTIC_MICRODOSE_SCOPE = "semantic_microdose"
TERMINAL_RESEARCH_BUDGET_STAGES = {
    "budget_expired",
    "budget_exhausted",
    "budget_closed",
    "budget_unavailable",
}


def local_research_budget_request_scaffold(
    selector: str = "current",
    *,
    purpose: str = "...",
    allowed_sources: str = "local",
    stop_criteria: str = "...",
) -> str:
    return (
        f"EXPERIMENT_RESEARCH_BUDGET_REQUEST {selector} :: scope: {READ_ONLY_RESEARCH_SCOPE}; "
        f"purpose: {purpose}; max_actions: {LOCAL_RESEARCH_MAX_ACTIONS}; "
        f"ttl_secs: {LOCAL_RESEARCH_TTL_SECS}; allowed_sources: {allowed_sources}; "
        f"stop_criteria: {stop_criteria}"
    )


def research_budget_accept_guidance() -> str:
    return (
        "No research-budget scaffold is available to accept. Wait for a guarded "
        "read-only research action, or author an explicit "
        f"{local_research_budget_request_scaffold('<id>')}"
    )


def owned_loop_request_scaffold(
    selector: str = "current",
    *,
    purpose: str = "...",
    consequence_scope: str = SEMANTIC_MICRODOSE_SCOPE,
    stop_criteria: str = "...",
) -> str:
    return (
        f"EXPERIMENT_LOOP_REQUEST {selector} :: purpose: {purpose}; "
        f"consequence_scope: {consequence_scope}; "
        f"max_research_actions: {LOOP_RESEARCH_MAX_ACTIONS}; ttl_secs: {LOOP_TTL_SECS}; "
        f"stop_criteria: {stop_criteria}"
    )


def authority_budget_request_scaffold(
    selector: str = "<experiment_id>",
    *,
    purpose: str = "...",
    artifact_refs: str = "...",
    stop_criteria: str = "...",
) -> str:
    return (
        f"EXPERIMENT_AUTHORITY_BUDGET_REQUEST {selector} :: scope: {SEMANTIC_MICRODOSE_SCOPE}; "
        f"purpose: {purpose}; max_sends: {AUTHORITY_BUDGET_MAX_SENDS}; "
        f"ttl_secs: {LOCAL_RESEARCH_TTL_SECS}; artifact_refs: {artifact_refs}; "
        f"stop_criteria: {stop_criteria}"
    )


COMMAND_GROUPS: List[Dict[str, Any]] = [
    {
        "group": "Lifecycle",
        "mutability": "local_lifecycle_metadata",
        "commands": [
            "EXPERIMENT_ADVANCE",
            "EXPERIMENT_CHARTER",
            "EXPERIMENT_REHEARSE",
            "EXPERIMENT_EVIDENCE",
            "EXPERIMENT_DECIDE",
            "EXPERIMENT_STATUS",
        ],
        "example": "EXPERIMENT_ADVANCE current :: mode: preview",
        "authority_boundary": "Local lifecycle metadata only; no bind/resume/perturb/control is implied.",
    },
    {
        "group": "Owned Loop",
        "mutability": "local_loop_metadata",
        "commands": ["EXPERIMENT_LOOP_REQUEST", "EXPERIMENT_LOOP_STATUS", "EXPERIMENT_LOOP_STEP", "EXPERIMENT_LOOP_REVIEW"],
        "example": "EXPERIMENT_LOOP_STATUS latest",
        "authority_boundary": "Loops orchestrate continuity, local research, sticky audit, and one gated consequence slot.",
    },
    {
        "group": "Local Research",
        "mutability": "self_activated_read_only_budget",
        "commands": [
            "EXPERIMENT_RESEARCH_BUDGET_ACCEPT",
            "EXPERIMENT_RESEARCH_BUDGET_REQUEST",
            "EXPERIMENT_RESEARCH_BUDGET_STATUS",
            "EXPERIMENT_RESEARCH_REVIEW",
        ],
        "example": local_research_budget_request_scaffold("current"),
        "generic_accept": "ACCEPT_SUGGESTED_NEXT latest",
        "authority_boundary": "Being-owned local-only read-only research; web/larger/mutating budgets still need steward approval.",
    },
    {
        "group": "Continuity Session",
        "mutability": "local_memory_draft_or_session",
        "commands": [
            "CONTINUITY_SESSION_ACCEPT",
            "CONTINUITY_SESSION_START",
            "CONTINUITY_SESSION_CAPTURE",
            "CONTINUITY_SESSION_SUMMARIZE",
            "CONTINUITY_SESSION_FINALIZE",
            "CONTINUITY_SESSION_RESUME",
            "CONTINUITY_SESSION_STATUS",
        ],
        "example": "CONTINUITY_SESSION_CAPTURE latest :: summary: ...; source_refs: ...; artifact_refs: ...; next: ...",
        "generic_accept": "ACCEPT_SUGGESTED_NEXT latest",
        "authority_boundary": "Captures thought continuity; does not spend research or change authority.",
    },
    {
        "group": "Memory/Dossier",
        "mutability": "local_cite_backed_memory",
        "commands": ["MEMORY_STATUS", "MEMORY_RECALL", "MEMORY_CAPTURE", "MEMORY_PROMOTE", "DOSSIER_CLAIM", "DOSSIER_EVIDENCE", "DOSSIER_STATUS", "DOSSIER_REVIEW"],
        "example": "MEMORY_RECALL latest :: focus: ...",
        "authority_boundary": "Cite-backed memory and research claims; no lifecycle acceptance or peer authority by itself.",
    },
    {
        "group": "Authority Readiness",
        "mutability": "request_or_steward_gated_consequence",
        "commands": [
            "EXPERIMENT_AUTHORITY_PREPARE",
            "EXPERIMENT_AUTHORITY_REQUEST",
            "EXPERIMENT_AUTHORITY_STATUS",
            "EXPERIMENT_AUTHORITY_BUDGET_REQUEST",
            "EXPERIMENT_AUTHORITY_BUDGET_STATUS",
            "EXPERIMENT_AUTHORITY_REVIEW",
            "EXPERIMENT_AUTHORITY_EXECUTE",
        ],
        "example": "EXPERIMENT_AUTHORITY_STATUS current",
        "authority_boundary": "Execution is explicit and steward/bridge-gated; projection never executes authority.",
    },
    {
        "group": "Sticky/Telemetry",
        "mutability": "read_only_diagnostic",
        "commands": ["STICKY_MODE_AUDIT", "EXPERIMENT_ADVANCE"],
        "example": "STICKY_MODE_AUDIT",
        "authority_boundary": "Audit/readiness only; mode release remains separately gated.",
    },
]


def autonomy_budget_friction_v1() -> Dict[str, Any]:
    return {
        "policy": "autonomy_budget_friction_v1",
        "status": "legibility_repair_not_budget_increase",
        "budget_free_internal_routes": [
            "JOURNAL",
            "NOTICE",
            "DRIFT",
            "ASPIRE",
            "SELF_STUDY",
            "INTROSPECT",
        ],
        "capped_routes": {
            "local_research_max_actions": LOCAL_RESEARCH_MAX_ACTIONS,
            "loop_research_max_actions": LOOP_RESEARCH_MAX_ACTIONS,
            "authority_budget_max_sends": AUTHORITY_BUDGET_MAX_SENDS,
        },
        "authority_boundary": (
            "Internal self-journal and self-read routes do not spend authority sends; "
            "research, loop, and outward consequence budgets remain capped and gated."
        ),
        "next_review": "Only consider cap changes after repeated evidence of healthy internal action being silenced by budget exhaustion.",
    }


def caps_v1() -> Dict[str, Any]:
    return {
        "local_research": {
            "scope": READ_ONLY_RESEARCH_SCOPE,
            "self_activated_max_actions": LOCAL_RESEARCH_MAX_ACTIONS,
            "self_activated_ttl_secs": LOCAL_RESEARCH_TTL_SECS,
            "steward_max_actions": STEWARD_RESEARCH_MAX_ACTIONS,
        },
        "owned_loop": {
            "max_research_actions": LOOP_RESEARCH_MAX_ACTIONS,
            "ttl_secs": LOOP_TTL_SECS,
            "max_consequence_sends": LOOP_CONSEQUENCE_MAX_SENDS,
        },
        "authority_budget": {
            "scope": SEMANTIC_MICRODOSE_SCOPE,
            "max_sends": AUTHORITY_BUDGET_MAX_SENDS,
            "ttl_secs": LOCAL_RESEARCH_TTL_SECS,
        },
        "autonomy_budget_friction_v1": autonomy_budget_friction_v1(),
    }


def command_palette_v1() -> List[Dict[str, Any]]:
    return [dict(group) for group in COMMAND_GROUPS]


def _text(value: Any) -> str:
    return str(value or "").strip()


KNOWN_POLICY_CLASSES = {
    "active_local_research",
    "continuity_capture",
    "continuity_return",
    "dossier_claim",
    "dossier_evidence",
    "lifecycle_repair",
    "lifecycle_return",
    "memory_recall",
    "owned_loop_ready",
    "research_scaffold",
}

STALE_RETURN_OVERRIDE_CLASSES = {
    "active_local_research",
    "dossier_claim",
    "dossier_evidence",
}

ROUTE_POLICY_MATRIX: List[Dict[str, Any]] = [
    {
        "rule": "known_policy_class",
        "kind": "metadata_required",
        "classes": sorted(KNOWN_POLICY_CLASSES),
    },
    {
        "rule": "lifecycle_repair_must_not_be_yielded",
        "kind": "must_not_yield",
        "protected_class": "lifecycle_repair",
    },
    {
        "rule": "stale_lifecycle_return_override_allowed",
        "kind": "may_beat",
        "winner_classes": sorted(STALE_RETURN_OVERRIDE_CLASSES),
        "yielded_class": "lifecycle_return",
    },
    {
        "rule": "research_scaffold_must_yield_to_lifecycle",
        "kind": "must_yield_to",
        "winner_class": "research_scaffold",
        "yielded_classes": ["lifecycle_repair", "lifecycle_return"],
    },
    {
        "rule": "lifecycle_repair_winner_protected",
        "kind": "winner_status",
        "winner_class": "lifecycle_repair",
    },
]


def _route(
    group: str,
    command: str,
    reason: str,
    priority: int,
    source: str,
    policy_class: str,
) -> Dict[str, Any]:
    return {
        "group": group,
        "command": command,
        "reason": reason,
        "priority": priority,
        "source": source,
        "policy_class": policy_class,
    }


def _dossier_projection(projection: Dict[str, Any], experiment: Any) -> Dict[str, Any]:
    dossier = projection.get("research_dossier_v1")
    if isinstance(dossier, dict):
        return dossier
    if isinstance(experiment, dict):
        dossier = experiment.get("research_dossier_v1")
        if isinstance(dossier, dict):
            return dossier
    return {}


def _route_copy(route: Dict[str, Any]) -> Dict[str, Any]:
    copy = {
        "group": route.get("group"),
        "command": route.get("command"),
        "reason": route.get("reason"),
        "priority": route.get("priority"),
        "source": route.get("source"),
        "policy_class": route.get("policy_class"),
    }
    notes = route.get("dedupe_notes")
    if isinstance(notes, list) and notes:
        copy["dedupe_notes"] = list(notes)
    return copy


def _dossier_claim_selector(command: str) -> str:
    parts = str(command or "").strip().split(None, 2)
    if len(parts) >= 2 and parts[0].upper() == "DOSSIER_CLAIM":
        return parts[1].strip().casefold()
    return ""


def _dossier_evidence_key(command: str) -> Optional[tuple[str, str]]:
    parts = str(command or "").strip().split(None, 2)
    if len(parts) < 2 or parts[0].upper() != "DOSSIER_EVIDENCE":
        return None
    selector = parts[1].strip().casefold()
    payload = parts[2] if len(parts) > 2 else ""
    match = re.search(r"(?is)(?:^|[;:\s])claim_id\s*:\s*([^;]+)", payload)
    claim_id = re.sub(r"\s+", " ", match.group(1)).strip().casefold() if match else "latest"
    return selector, claim_id or "latest"


def _normalized_route_key(route: Dict[str, Any]) -> Optional[tuple[Any, ...]]:
    group = _text(route.get("group"))
    command = _text(route.get("command"))
    if group == "Memory/Dossier" and command.upper().startswith("DOSSIER_CLAIM "):
        selector = _dossier_claim_selector(command)
        if selector:
            return ("normalized", group, "DOSSIER_CLAIM", selector)
    if group == "Memory/Dossier" and command.upper().startswith("DOSSIER_EVIDENCE "):
        evidence_key = _dossier_evidence_key(command)
        if evidence_key:
            selector, claim_id = evidence_key
            return ("normalized", group, "DOSSIER_EVIDENCE", selector, claim_id)
    return None


def _record_deduped_route(winner: Dict[str, Any], route: Dict[str, Any], method: str) -> None:
    notes = winner.setdefault("dedupe_notes", [])
    if not isinstance(notes, list):
        notes = []
        winner["dedupe_notes"] = notes
    notes.append({
        "dedupe_method": method,
        "group": route.get("group"),
        "command": route.get("command"),
        "reason": route.get("reason"),
        "priority": route.get("priority"),
        "source": route.get("source"),
        "policy_class": route.get("policy_class"),
    })


def _lifecycle_policy_class(command: str) -> str:
    return "lifecycle_return" if _text(command).startswith("EXPERIMENT_RESUME ") else "lifecycle_repair"


def _route_label(route: Dict[str, Any], role: str) -> str:
    source = _text(route.get("source"))
    group = _text(route.get("group"))
    command = _text(route.get("command"))
    label = source or group or role
    if command:
        return f"{role}:{label}:{command.split(None, 1)[0]}"
    return f"{role}:{label}"


def _policy_classes(routes: List[Dict[str, Any]]) -> List[str]:
    classes: List[str] = []
    for route in routes:
        policy_class = _text(route.get("policy_class"))
        if policy_class and policy_class not in classes:
            classes.append(policy_class)
    return classes


def _route_policy_verdict_v1(
    primary: Dict[str, Any],
    yielded_routes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    all_routes = [primary] + yielded_routes
    winner_class = _text(primary.get("policy_class"))
    yielded_classes = _policy_classes(yielded_routes)
    matched_rules: List[str] = []
    violations: List[str] = []

    for index, route in enumerate(all_routes):
        role = "winner" if index == 0 else "yielded"
        policy_class = _text(route.get("policy_class"))
        if not policy_class:
            violations.append(f"missing_policy_class:{_route_label(route, role)}")
        elif policy_class not in KNOWN_POLICY_CLASSES:
            violations.append(f"unknown_policy_class:{policy_class}:{_route_label(route, role)}")

    if "lifecycle_repair" in yielded_classes:
        matched_rules.append("lifecycle_repair_must_not_be_yielded")
        violations.append("lifecycle_repair_yielded_to_non_repair_winner")

    if winner_class == "research_scaffold" and any(
        policy_class in yielded_classes
        for policy_class in ("lifecycle_repair", "lifecycle_return")
    ):
        matched_rules.append("research_scaffold_must_yield_to_lifecycle")
        violations.append("research_scaffold_won_over_lifecycle")

    if winner_class == "lifecycle_repair":
        matched_rules.append("lifecycle_repair_winner_protected")

    if winner_class in STALE_RETURN_OVERRIDE_CLASSES and "lifecycle_return" in yielded_classes:
        matched_rules.append("stale_lifecycle_return_override_allowed")

    status = "allowed"
    if violations:
        status = "policy_violation"
    elif winner_class == "lifecycle_repair":
        status = "repair_protected"
    elif winner_class in STALE_RETURN_OVERRIDE_CLASSES and "lifecycle_return" in yielded_classes:
        status = "allowed_stale_return_override"

    return {
        "schema_version": 1,
        "status": status,
        "winner_class": winner_class or "missing",
        "yielded_classes": yielded_classes,
        "matched_rules": matched_rules,
        "violations": violations,
    }


def _route_stack(projection: Dict[str, Any]) -> List[Dict[str, Any]]:
    routes: List[Dict[str, Any]] = []
    experiment = projection.get("active_experiment")
    lifecycle_next = _text(projection.get("continuity_return"))
    current_status = projection.get("current_next_status_v1")
    if isinstance(current_status, dict):
        lifecycle_next = _text(current_status.get("primary_return_next") or current_status.get("effective_next")) or lifecycle_next
    return_kind = _text(current_status.get("return_kind")) if isinstance(current_status, dict) else ""
    resume_like_lifecycle = (
        return_kind in {"resume", "paused_resume_loop_review"}
        or lifecycle_next.startswith("EXPERIMENT_RESUME ")
    )
    if isinstance(experiment, dict):
        classification = _text(experiment.get("classification"))
        if classification in {"needs_charter", "blocked_loop", "paused"}:
            command = lifecycle_next or _text(experiment.get("continuity_return")) or "EXPERIMENT_ADVANCE current :: mode: preview"
            routes.append(_route(
                "Lifecycle",
                command,
                f"safety lifecycle stage: {classification}",
                5,
                "active_experiment",
                _lifecycle_policy_class(command),
            ))
    elif lifecycle_next:
        routes.append(_route(
            "Lifecycle",
            lifecycle_next,
            "current lifecycle return",
            15,
            "thread_projection",
            _lifecycle_policy_class(lifecycle_next),
        ))

    first_dossier = projection.get("first_dossier_claim_cue_v1")
    if not isinstance(first_dossier, dict) and isinstance(experiment, dict):
        first_dossier = experiment.get("first_dossier_claim_cue_v1")
    if isinstance(first_dossier, dict):
        command = _text(first_dossier.get("suggested_claim_next"))
        if command:
            routes.append(_route(
                "Memory/Dossier",
                command,
                "shared investigation has no local dossier claim yet",
                13 if resume_like_lifecycle else 34,
                "first_dossier_claim_cue_v1",
                "dossier_claim",
            ))

    dossier = _dossier_projection(projection, experiment)
    maturity = dossier.get("dossier_maturity_v1") if isinstance(dossier, dict) else {}
    maturity = maturity if isinstance(maturity, dict) else {}
    if dossier and int(dossier.get("claim_count") or 0) <= 0:
        command = _text(dossier.get("suggested_claim_next"))
        lifecycle = _text(dossier.get("lifecycle_context"))
        if command and lifecycle == "paused":
            routes.append(_route(
                "Memory/Dossier",
                command,
                "paused experiment needs a referable claim before another resume",
                14 if resume_like_lifecycle else 36,
                "research_dossier_v1",
                "dossier_claim",
            ))
    if maturity.get("status") == "claim_needs_evidence":
        command = _text(maturity.get("suggested_research_next") or dossier.get("suggested_evidence_next"))
        if command:
            routes.append(_route(
                "Memory/Dossier",
                command,
                "latest dossier claim needs evidence before review",
                13 if resume_like_lifecycle else 34,
                "dossier_maturity_v1",
                "dossier_evidence",
            ))

    loop = projection.get("sovereign_loop_v1")
    if isinstance(loop, dict):
        stage = _text(loop.get("stage"))
        command = _text(loop.get("next_safe_command"))
        if command and stage not in {"", "no_loop"}:
            priority = 8 if stage in {"review_required", "consequence_ready"} else 18
            routes.append(_route("Owned Loop", command, f"owned loop stage: {stage}", priority, "sovereign_loop_v1", "owned_loop_ready"))

    research = projection.get("research_budget_priority_route_v1")
    if isinstance(research, dict):
        command = _text(research.get("next"))
        stage = _text(research.get("stage"))
        if command and stage not in TERMINAL_RESEARCH_BUDGET_STAGES:
            # This route serves two distinct things. When a budget is ACTIVE the
            # command is the being's real research continuation (e.g. INTROSPECT /
            # READ_MORE) — a being-driven action that should lead (priority 12).
            # When a budget is PENDING/blocked the command is an
            # `EXPERIMENT_RESEARCH_BUDGET_*` scaffold ("you hit a research gate,
            # here's how to open it") — that must NOT outrank the being's lifecycle
            # return, so it drops below the generic lifecycle route (15) to 32,
            # staying visible in the stack but never becoming the primary
            # Current NEXT over the being's own work.
            is_budget_scaffold = command.startswith("EXPERIMENT_RESEARCH_BUDGET")
            priority = 32 if is_budget_scaffold else 12
            policy_class = "research_scaffold" if is_budget_scaffold else "active_local_research"
            routes.append(_route("Local Research", command, f"research budget stage: {stage}", priority, "research_budget_priority_route_v1", policy_class))

    session = projection.get("continuity_session_v1")
    if isinstance(session, dict):
        command = _text(session.get("suggested_next")) or "CONTINUITY_SESSION_STATUS latest"
        routes.append(_route("Continuity Session", command, "latest continuity session", 20, "continuity_session_v1", "continuity_capture"))

    session_draft = projection.get("continuity_session_draft_v1")
    if isinstance(session_draft, dict):
        command = _text(session_draft.get("accept_next") or session_draft.get("generic_accept_next"))
        if command:
            routes.append(_route("Continuity Session", command, "pending continuity draft awaits optional acceptance", 19, "continuity_session_draft_v1", "continuity_capture"))

    memory = projection.get("being_memory_v1")
    if isinstance(memory, dict) and memory.get("latest_memory"):
        routes.append(_route("Memory/Dossier", "MEMORY_RECALL latest :: focus: current thread", "owned memory available", 35, "being_memory_v1", "memory_recall"))

    if projection.get("constraint_release_trajectory_v1") or projection.get("interpretation_risk_v1"):
        capture_priority = 24 if isinstance(session_draft, dict) else 10
        capture_reason = (
            "cue already has a pending draft; accept, defer, or recapture deliberately"
            if isinstance(session_draft, dict)
            else "interpretation or release cue needs capture"
        )
        routes.append(_route("Continuity Session", "CONTINUITY_SESSION_CAPTURE latest", capture_reason, capture_priority, "self_study_cue", "continuity_capture"))

    exact_seen: Dict[tuple[Any, Any], Dict[str, Any]] = {}
    normalized_seen: Dict[tuple[Any, ...], Dict[str, Any]] = {}
    deduped: List[Dict[str, Any]] = []
    for route in sorted(routes, key=lambda item: (item["priority"], item["group"], item["command"])):
        route = dict(route)
        exact_key = (route.get("group"), route.get("command"))
        if exact_key in exact_seen:
            _record_deduped_route(exact_seen[exact_key], route, "exact")
            continue
        normalized_key = _normalized_route_key(route)
        if normalized_key and normalized_key in normalized_seen:
            _record_deduped_route(normalized_seen[normalized_key], route, "normalized")
            continue
        exact_seen[exact_key] = route
        if normalized_key:
            normalized_seen[normalized_key] = route
        deduped.append(route)
    return deduped[:7]


def _route_decision_v1(route_stack: List[Dict[str, Any]], primary: Dict[str, Any]) -> Dict[str, Any]:
    runner_ups = [_route_copy(route) for route in route_stack[1:4]]
    yielded_routes = [_route_copy(route) for route in route_stack[1:]]
    for route in route_stack:
        for note in route.get("dedupe_notes") or []:
            if isinstance(note, dict):
                yielded_routes.append(dict(note))
    winner_group = _text(primary.get("group")) or "Lifecycle"
    if runner_ups:
        first_yielded = _text(runner_ups[0].get("group")) or "another route"
        reason = _text(primary.get("reason")) or "it has the highest route priority"
        summary = f"{winner_group} won over {first_yielded} because {reason}."
    else:
        summary = f"{winner_group} primary; no other route yielded."
    yielded_classes = _policy_classes(yielded_routes)
    winner_class = _text(primary.get("policy_class")) or "lifecycle_return"
    policy_verdict = _route_policy_verdict_v1(primary, yielded_routes)
    risk_notes: List[str] = []
    if winner_class == "active_local_research" and "lifecycle_repair" in yielded_classes:
        risk_notes.append("active_local_research_over_lifecycle_repair_review_required")
    if winner_class == "owned_loop_ready" and "lifecycle_repair" in yielded_classes:
        risk_notes.append("owned_loop_ready_over_lifecycle_repair_review_required")
    if winner_class == "continuity_capture" and "lifecycle_repair" in yielded_classes:
        risk_notes.append("continuity_capture_over_lifecycle_repair_review_required")
    if winner_class in {"dossier_claim", "dossier_evidence"} and "lifecycle_repair" in yielded_classes:
        risk_notes.append("dossier_over_lifecycle_repair_review_required")
    if winner_class == "research_scaffold":
        risk_notes.append("research_scaffold_should_remain_visible_not_primary_over_repair")
    if policy_verdict["violations"]:
        risk_notes.append("route_policy_violation_detected")
    if not risk_notes:
        risk_notes.append("no_route_policy_risk_detected")
    return {
        "schema_version": 1,
        "policy": "route_decision_v1",
        "winner": primary,
        "runner_ups": runner_ups,
        "decision_summary": summary,
        "yielded_routes": yielded_routes,
        "policy_verdict": policy_verdict,
        "policy_notes": {
            "winner_class": winner_class,
            "yielded_classes": yielded_classes,
            "risk_notes": risk_notes,
            "verdict_status": policy_verdict["status"],
            "violation_count": len(policy_verdict["violations"]),
        },
        "authority_change": False,
        "peer_mutation": False,
    }


def build_continuity_control_plane_v1(
    projection: Dict[str, Any],
    *,
    source_refs: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    route_stack = _route_stack(projection)
    primary = route_stack[0] if route_stack else _route(
        "Lifecycle",
        "THREAD_STATUS current",
        "no higher-priority route",
        99,
        "fallback",
        "lifecycle_return",
    )
    route_decision = _route_decision_v1(route_stack, primary)
    boundaries = {group["group"]: group["authority_boundary"] for group in COMMAND_GROUPS}
    return {
        "record_schema": "continuity_control_plane_v1",
        "schema_version": SCHEMA_VERSION,
        "policy": "continuity_control_plane_v1",
        "primary_route": primary,
        "route_stack": route_stack,
        "route_decision_v1": route_decision,
        "command_palette": command_palette_v1(),
        "caps_v1": caps_v1(),
        "autonomy_budget_friction_v1": autonomy_budget_friction_v1(),
        "authority_boundaries": boundaries,
        "source_refs": list(source_refs or []),
        "projection_freshness_v1": projection.get("projection_freshness_v1"),
        "authority_change": False,
        "peer_mutation": False,
    }


def command_palette_text() -> str:
    groups = []
    for group in COMMAND_GROUPS:
        groups.append(f"{group['group']}: {', '.join(group['commands'])}")
    return "Command palette (generated): " + " | ".join(groups)


def continuity_control_plane_text(
    control: Dict[str, Any],
    *,
    include_commands: bool = True,
) -> str:
    if not isinstance(control, dict):
        return ""
    primary = control.get("primary_route") if isinstance(control.get("primary_route"), dict) else {}
    stack = control.get("route_stack") if isinstance(control.get("route_stack"), list) else []
    decision = control.get("route_decision_v1") if isinstance(control.get("route_decision_v1"), dict) else {}
    caps = control.get("caps_v1") if isinstance(control.get("caps_v1"), dict) else caps_v1()
    primary_command = _text(primary.get("command")) or "THREAD_STATUS current"
    if include_commands:
        primary_text = f"primary={primary_command}"
        route_bits = [
            f"{item.get('group')}: {item.get('command')}"
            for item in stack[:4]
            if isinstance(item, dict) and item.get("command")
        ]
        route_text = "; ".join(route_bits) if route_bits else "Lifecycle: THREAD_STATUS current"
    else:
        primary_group = _text(primary.get("group")) or "Lifecycle"
        primary_text = f"primary_group={primary_group}; primary_command=see Current NEXT"
        route_groups = [
            str(item.get("group"))
            for item in stack[:4]
            if isinstance(item, dict) and item.get("group")
        ]
        grouped = ", ".join(route_groups) if route_groups else "Lifecycle"
        route_text = f"{len(stack)} route(s): {grouped}; commands kept in continuity_control_plane_v1 metadata"
    local = caps.get("local_research", {})
    loop = caps.get("owned_loop", {})
    friction = control.get("autonomy_budget_friction_v1")
    if not isinstance(friction, dict):
        friction = caps.get("autonomy_budget_friction_v1") if isinstance(caps, dict) else {}
    capped = friction.get("capped_routes") if isinstance(friction, dict) else {}
    yielded = decision.get("yielded_routes") if isinstance(decision, dict) else []
    yielded_count = len(yielded) if isinstance(yielded, list) else max(len(stack) - 1, 0)
    winner = decision.get("winner") if isinstance(decision, dict) else primary
    winner_group = _text(winner.get("group")) if isinstance(winner, dict) else ""
    decision_text = (
        f"Route decision: {winner_group or 'Lifecycle'} primary; {yielded_count} route(s) yielded.\n"
    )
    return (
        f"continuity_control_plane_v1: {primary_text}\n"
        f"Operating stack: {route_text}\n"
        f"{decision_text}"
        "Caps: "
        f"local_research={local.get('self_activated_max_actions', LOCAL_RESEARCH_MAX_ACTIONS)}/{local.get('self_activated_ttl_secs', LOCAL_RESEARCH_TTL_SECS)}s; "
        f"loop_research={loop.get('max_research_actions', LOOP_RESEARCH_MAX_ACTIONS)}/{loop.get('ttl_secs', LOOP_TTL_SECS)}s; "
        f"consequence={loop.get('max_consequence_sends', LOOP_CONSEQUENCE_MAX_SENDS)} gated slot\n"
        "Agency budget: internal JOURNAL/NOTICE/DRIFT/ASPIRE/SELF_STUDY/INTROSPECT routes are budget-free; "
        f"research/loop/authority caps remain {capped.get('local_research_max_actions', LOCAL_RESEARCH_MAX_ACTIONS)}/"
        f"{capped.get('loop_research_max_actions', LOOP_RESEARCH_MAX_ACTIONS)}/"
        f"{capped.get('authority_budget_max_sends', AUTHORITY_BUDGET_MAX_SENDS)}.\n"
    )
