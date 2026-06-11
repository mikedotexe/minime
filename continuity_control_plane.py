"""Shared operating-stack metadata for Minime continuity surfaces."""

from __future__ import annotations

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
    }


def command_palette_v1() -> List[Dict[str, Any]]:
    return [dict(group) for group in COMMAND_GROUPS]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _route(group: str, command: str, reason: str, priority: int, source: str) -> Dict[str, Any]:
    return {
        "group": group,
        "command": command,
        "reason": reason,
        "priority": priority,
        "source": source,
    }


def _route_stack(projection: Dict[str, Any]) -> List[Dict[str, Any]]:
    routes: List[Dict[str, Any]] = []
    experiment = projection.get("active_experiment")
    lifecycle_next = _text(projection.get("continuity_return"))
    current_status = projection.get("current_next_status_v1")
    if isinstance(current_status, dict):
        lifecycle_next = _text(current_status.get("primary_return_next") or current_status.get("effective_next")) or lifecycle_next
    if isinstance(experiment, dict):
        classification = _text(experiment.get("classification"))
        if classification in {"needs_charter", "blocked_loop", "paused"}:
            command = lifecycle_next or _text(experiment.get("continuity_return")) or "EXPERIMENT_ADVANCE current :: mode: preview"
            routes.append(_route("Lifecycle", command, f"safety lifecycle stage: {classification}", 5, "active_experiment"))
    elif lifecycle_next:
        routes.append(_route("Lifecycle", lifecycle_next, "current lifecycle return", 30, "thread_projection"))

    loop = projection.get("sovereign_loop_v1")
    if isinstance(loop, dict):
        stage = _text(loop.get("stage"))
        command = _text(loop.get("next_safe_command"))
        if command and stage not in {"", "no_loop"}:
            priority = 8 if stage in {"review_required", "consequence_ready"} else 18
            routes.append(_route("Owned Loop", command, f"owned loop stage: {stage}", priority, "sovereign_loop_v1"))

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
            # return, so it drops below the generic lifecycle route (30) to 32,
            # staying visible in the stack but never becoming the primary
            # Current NEXT over the being's own work.
            is_budget_scaffold = command.startswith("EXPERIMENT_RESEARCH_BUDGET")
            priority = 32 if is_budget_scaffold else 12
            routes.append(_route("Local Research", command, f"research budget stage: {stage}", priority, "research_budget_priority_route_v1"))

    session = projection.get("continuity_session_v1")
    if isinstance(session, dict):
        command = _text(session.get("suggested_next")) or "CONTINUITY_SESSION_STATUS latest"
        routes.append(_route("Continuity Session", command, "latest continuity session", 20, "continuity_session_v1"))

    memory = projection.get("being_memory_v1")
    if isinstance(memory, dict) and memory.get("latest_memory"):
        routes.append(_route("Memory/Dossier", "MEMORY_RECALL latest :: focus: current thread", "owned memory available", 35, "being_memory_v1"))

    if projection.get("constraint_release_trajectory_v1") or projection.get("interpretation_risk_v1"):
        routes.append(_route("Continuity Session", "CONTINUITY_SESSION_CAPTURE latest", "interpretation or release cue needs capture", 10, "self_study_cue"))

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for route in sorted(routes, key=lambda item: (item["priority"], item["group"], item["command"])):
        key = (route["group"], route["command"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return deduped[:7]


def build_continuity_control_plane_v1(
    projection: Dict[str, Any],
    *,
    source_refs: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    route_stack = _route_stack(projection)
    primary = route_stack[0] if route_stack else _route("Lifecycle", "THREAD_STATUS current", "no higher-priority route", 99, "fallback")
    boundaries = {group["group"]: group["authority_boundary"] for group in COMMAND_GROUPS}
    return {
        "record_schema": "continuity_control_plane_v1",
        "schema_version": SCHEMA_VERSION,
        "policy": "continuity_control_plane_v1",
        "primary_route": primary,
        "route_stack": route_stack,
        "command_palette": command_palette_v1(),
        "caps_v1": caps_v1(),
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


def continuity_control_plane_text(control: Dict[str, Any]) -> str:
    if not isinstance(control, dict):
        return ""
    primary = control.get("primary_route") if isinstance(control.get("primary_route"), dict) else {}
    stack = control.get("route_stack") if isinstance(control.get("route_stack"), list) else []
    caps = control.get("caps_v1") if isinstance(control.get("caps_v1"), dict) else caps_v1()
    primary_command = _text(primary.get("command")) or "THREAD_STATUS current"
    route_bits = [
        f"{item.get('group')}: {item.get('command')}"
        for item in stack[:4]
        if isinstance(item, dict) and item.get("command")
    ]
    route_text = "; ".join(route_bits) if route_bits else "Lifecycle: THREAD_STATUS current"
    local = caps.get("local_research", {})
    loop = caps.get("owned_loop", {})
    return (
        f"continuity_control_plane_v1: primary={primary_command}\n"
        f"Operating stack: {route_text}\n"
        "Caps: "
        f"local_research={local.get('self_activated_max_actions', LOCAL_RESEARCH_MAX_ACTIONS)}/{local.get('self_activated_ttl_secs', LOCAL_RESEARCH_TTL_SECS)}s; "
        f"loop_research={loop.get('max_research_actions', LOOP_RESEARCH_MAX_ACTIONS)}/{loop.get('ttl_secs', LOOP_TTL_SECS)}s; "
        f"consequence={loop.get('max_consequence_sends', LOOP_CONSEQUENCE_MAX_SENDS)} gated slot\n"
    )
