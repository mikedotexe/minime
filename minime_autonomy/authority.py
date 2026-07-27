"""Read-only preflight and capability-self-map ownership."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .action_vocabulary import (
    ACTION_PREFLIGHT_NEXT_ACTIONS,
    HARD_RESET_ALLOWED_NEXT_ACTIONS,
    LOW_FILL_ADVISORY_NEXT_ACTIONS,
)


def _runtime_module():
    from . import runtime

    return runtime


def _operator_pending_next_allowed_bases():
    return _runtime_module().OPERATOR_PENDING_NEXT_ALLOWED_BASES


def resonance_density_availability_status(value):
    return _runtime_module().resonance_density_availability_status(value)


def pressure_source_availability_status(value):
    return _runtime_module().pressure_source_availability_status(value)


def inhabitable_fluctuation_availability_status(value):
    return _runtime_module().inhabitable_fluctuation_availability_status(value)


def _has_unresolved_angle_placeholder(text: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][a-zA-Z0-9_./| -]{0,48}>", text or ""))


class ActionPreflightStore:
    """Pure dry-run NEXT diagnostics for Minime actions."""

    schema_version = 1
    ROUTE_BY_BASE = {
        "SELF_STUDY": "self_study",
        "INTROSPECT": "introspect",
        "EXPERIMENT": "self_experiment",
        "SELF_EXPERIMENT": "self_experiment",
        "EXPERIMENT_BIND": "experiment_bind",
        "EXPERIMENT_START": "thread_action",
        "EXPERIMENT_PLAN": "thread_action",
        "EXPERIMENT_ADVANCE": "thread_action",
        "EXPERIMENT_CONVEYOR": "thread_action",
        "EXPERIMENT_AUTHORITY_REQUEST": "thread_action",
        "EXPERIMENT_AUTHORITY_PREPARE": "thread_action",
        "EXPERIMENT_AUTHORITY_STATUS": "thread_action",
        "EXPERIMENT_AUTHORITY_EXECUTE": "thread_action",
        "EXPERIMENT_AUTHORITY_BUDGET_REQUEST": "thread_action",
        "EXPERIMENT_AUTHORITY_BUDGET_STATUS": "thread_action",
        "EXPERIMENT_AUTHORITY_REVIEW": "thread_action",
        "EXPERIMENT_CHARTER": "thread_action",
        "EXPERIMENT_REHEARSE": "thread_action",
        "EXPERIMENT_PREFLIGHT": "thread_action",
        "EXPERIMENT_EVIDENCE": "thread_action",
        "EXPERIMENT_DECIDE": "thread_action",
        "EXPERIMENT_OBSERVE": "thread_action",
        "EXPERIMENT_STATUS": "thread_action",
        "EXPERIMENT_REVIEW": "thread_action",
        "EXPERIMENT_CLOSE": "thread_action",
        "EXPERIMENT_PEER_REVIEW": "thread_action",
        "EXPERIMENT_BRANCH": "thread_action",
        "EXPERIMENT_RESUME": "thread_action",
        "EXPERIMENT_COMPARE": "thread_action",
        "EXPERIMENT_ALT_PATHS": "thread_action",
        "SHARED_INVESTIGATION_START": "thread_action",
        "SHARED_INVESTIGATION_STATUS": "thread_action",
        "SHARED_INVESTIGATION_CLAIM": "thread_action",
        "SHARED_INVESTIGATION_DECIDE": "thread_action",
        "DOSSIER_CLAIM": "thread_action",
        "DOSSIER_EVIDENCE": "thread_action",
        "DOSSIER_STATUS": "thread_action",
        "DOSSIER_REVIEW": "thread_action",
        "MEMORY_STATUS": "thread_action",
        "MEMORY_RECALL": "thread_action",
        "MEMORY_CAPTURE": "thread_action",
        "MEMORY_PROMOTE": "thread_action",
        "FACULTIES": "thread_action",
        "CAPABILITY_MAP": "thread_action",
        "CAPABILITY_STATUS": "thread_action",
        "CAPABILITY_DIFF": "thread_action",
        "ACTION_STATUS": "thread_action",
        "JOB_STATUS": "thread_action",
        "ACTION_CANCEL": "thread_action",
        "DIVISION_STATUS": "division_status",
        "DIVISION_CEREMONY_STATUS": "division_ceremony",
        "DIVISION_HOLD": "division_ceremony",
        "DIVISION_DECLINE": "division_ceremony",
        "DIVISION_INTENT": "division_ceremony",
        "DIVISION_ASSENT": "division_ceremony",
        "DIVISION_WITHDRAW_ASSENT": "division_ceremony",
        "DIVISION_RETURN_REQUEST": "division_ceremony",
        "DIVISION_REVIEW": "division_ceremony",
        "DIVISION_PREPARE": "division_prepare",
        "DIVISION_COMMIT": "division_commit",
        "DIVISION_ABORT": "division_abort",
        "DIVISION_ROLLBACK": "division_rollback",
        "LIVED_TERM_STATUS": "thread_action",
        "LIVED_TERM_EXPERIMENT": "thread_action",
        "REGULATOR_MAP_STATUS": "thread_action",
        "REGULATOR_REPLAY_STATUS": "thread_action",
        "REGULATOR_BOUNDARY_CARD": "thread_action",
        "PI_PRESSURE_REPLAY_STATUS": "thread_action",
        "PRESSURE_AGENCY_STATUS": "pressure_agency",
        "PRESSURE_CONTROL_STATUS": "pressure_agency",
        "PRESSURE_AGENCY": "pressure_agency",
        "PRESSURE_AGENCY_REQUEST": "pressure_agency",
        "PRESSURE_CONTROL_REQUEST": "pressure_agency",
        "PRESSURE_REQUEST": "pressure_agency",
        "TEXTURE_AGENCY_STATUS": "texture_agency",
        "TEXTURE_STATUS": "texture_agency",
        "RESONANCE_TEXTURE_STATUS": "texture_agency",
        "TEXTURE_AGENCY_REQUEST": "texture_agency",
        "TEXTURE_REQUEST": "texture_agency",
        "RESONANCE_TEXTURE_REQUEST": "texture_agency",
        "MESSAGE_ASTRID": "peer_correspondence",
        "REPLY_ASTRID": "peer_correspondence",
        "TRACE_ASTRID": "peer_correspondence",
        "CORRESPONDENCE_TRACE": "peer_correspondence",
        "I_RECEIVED_THIS": "peer_correspondence",
        "CORRESPONDENCE_STATUS": "peer_correspondence",
        "LEGACY_CORRESPONDENCE_STATUS": "peer_correspondence",
        "CLAIM_ASTRID_LEGACY": "peer_correspondence",
        "CORRESPONDENCE_CLAIM": "peer_correspondence",
        "CORRESPONDENCE_CLAIM_OUTCOME": "peer_correspondence",
        "CORRESPONDENCE_ATTENTION_REQUEST": "peer_correspondence",
        "CORRESPONDENCE_ATTENTION_OUTCOME": "peer_correspondence",
        "CORRESPONDENCE_MICRODOSE_REQUEST": "peer_correspondence",
        "CORRESPONDENCE_WEIGHT_REQUEST": "peer_correspondence",
        "DECLARE_TRANSITION": "phase_transition",
        "WITNESS_TRANSITION": "phase_transition",
        "RECEIVE_TRANSITION": "phase_transition",
        "I_RECEIVED_TRANSITION": "phase_transition",
        "PREPARE_TRANSITION": "phase_transition",
        "ENTER_TRANSITION": "phase_transition",
        "CROSS_TRANSITION": "phase_transition",
        "HOLD_TRANSITION": "phase_transition",
        "SETTLE_TRANSITION": "phase_transition",
        "RETURN_TRANSITION": "phase_transition",
        "REVISIT_TRANSITION": "phase_transition",
        "DECLINE_TRANSITION": "phase_transition",
        "TRANSITION_REVIEW": "phase_transition",
        "DESCRIBE_TRANSITION_CONDITION": "phase_transition",
        "DESCRIBE_TRANSITION_BEARING": "phase_transition",
        "MARK_TRANSITION_CHECKPOINT": "phase_transition",
        "BIND_TRANSITION_ANCHOR": "phase_transition",
        "REQUEST_TRANSITION_COMPANY": "phase_transition",
        "RESPOND_TRANSITION_COMPANY": "phase_transition",
        "WITHDRAW_TRANSITION_COMPANY": "phase_transition",
        "TRANSITION_PASSAGE_STATUS": "phase_transition",
        "LIVED_TRANSITION_STATUS": "phase_transition",
        "TRANSITION_STATUS": "phase_transition",
        "PHASE_TRANSITION_STATUS": "phase_transition",
        "SELF_REGULATION_INTENT": "self_regulation",
        "SELF_REGULATION_PREFLIGHT": "self_regulation",
        "SELF_REGULATION_APPLY": "self_regulation",
        "SELF_REGULATION_STATUS": "self_regulation",
        "SELF_REGULATION_OUTCOME": "self_regulation",
        "CONTROL_INTENT": "self_regulation",
        "CONTROL_PREFLIGHT": "self_regulation",
        "CONTROL_APPLY_LEASE": "self_regulation",
        "CONTROL_STATUS": "self_regulation",
        "CONTROL_OUTCOME": "self_regulation",
        "REPAIR_STATUS": "thread_action",
        "REPAIR_SWEEP": "thread_action",
        "REPAIR_RECORD": "thread_action",
        "REPAIR_APPLY": "thread_action",
        "THREAD_START": "thread_action",
        "THREADS": "thread_action",
        "THREAD_STATUS": "thread_action",
        "THREAD_NOTE": "thread_action",
        "RESUME": "thread_action",
        "SAVEPOINT": "thread_action",
        "RECALL": "thread_action",
        "DECOMPOSE": "decompose",
        "SPECTRAL_EXPLORER": "decompose",
        "CONSTRAINT_AUDIT": "constraint_audit",
        "UNSHAPED_BASELINE": "constraint_audit",
        "PRESSURE_SOURCE_AUDIT": "pressure_source_audit",
        "PRESSURE_SOURCE": "pressure_source_audit",
        "STRUCTURAL_PRESSURE": "pressure_source_audit",
        "INWARD_PRESSURE": "pressure_source_audit",
        "PRESSURE_RELIEF": "pressure_relief",
        "RELIEF": "pressure_relief",
        "FLUCTUATION_AUDIT": "fluctuation_audit",
        "INHABITABLE_FLUCTUATION": "fluctuation_audit",
        "EIGENTRUST": "fluctuation_audit",
        "EIGENTRUST_AUDIT": "fluctuation_audit",
        "FOOTHOLD_AUDIT": "fluctuation_audit",
        "SEARCH": "research_exploration",
        "RESEARCH": "research_exploration",
        "BROWSE": "browse_url",
        "READ_MORE": "read_more",
        "NOTICE": "recess_notice",
        "REST": None,
        "PASS": None,
        "SPACE_HOLD": "space_hold",
        "LOOK": "request_visual_frame",
        "CLOSE_EYES": "close_eyes",
        "SHUT_EYES": "close_eyes",
        "OPEN_EYES": "open_eyes",
        "CLOSE_EARS": "close_ears",
        "SHUT_EARS": "close_ears",
        "OPEN_EARS": "open_ears",
        "CODEX": "codex_query",
        "CODEX_NEW": "codex_query",
        "WRITE_FILE": "write_file",
        "EXPERIMENT_RUN": "experiment_run",
        "RUN_PYTHON": "run_python",
        "PERTURB": "perturb",
        "NATIVE_GESTURE": "native_gesture",
        "RESIST": "native_gesture",
        "FISSURE": "native_gesture",
        "GOAL": "set_spectral_goal",
        "ATTRACTOR_PREFLIGHT": "attractor_atlas",
        "ATTRACTOR_SUGGESTIONS": "attractor_suggestions",
        "SHADOW_PREFLIGHT": "shadow_autonomy",
        "SHADOW_TRAJECTORY": "shadow_trajectory",
        "DISPERSE": "mode_disperse",
        "SPREAD": "mode_disperse",
        "MODE_DISPERSE": "mode_disperse",
        "REGULATOR_AUDIT": "regulator_audit",
        "VISUALIZE_CASCADE": "visualize_cascade",
        "RECONVERGENCE_MAP": "reconvergence_map",
        # v3.5: reciprocal influence — minime perturbing Astrid via codec bias
        "INFLUENCE_ASTRID": "influence_astrid",
        "INFLUENCE_ASTRID_RESPONSE": "influence_astrid_response",
        # co-regulation gift: lend Astrid aperture (jitter-spread her codec ring)
        "LEND_APERTURE": "lend_aperture",
        # v3.6: bidirectional parameter requests — minime asks Astrid to
        # adjust a parameter on her side, with rationale.
        "TUNE_ASTRID": "tune_astrid",
        "REVIEW_PARAMETER_REQUESTS": "review_parameter_requests",
        "PARAMETER_REQUESTS": "review_parameter_requests",
        # v3.6.3: apply/defer/reject workflow — the missing half of REVIEW.
        # Without these, REVIEW is read-only and pending requests pile up.
        # v3.6.5 (mirror): bare ACCEPT/DEFER/REJECT aliases drop emission
        # cost from ~50 chars to 5-6. Handlers no-op gracefully when no
        # pending request exists, so natural-language uses don't wreak havoc.
        "ACCEPT_PARAMETER_REQUEST": "accept_parameter_request",
        "ACCEPT_REQUEST": "accept_parameter_request",
        "ACCEPT": "accept_parameter_request",
        "DEFER_PARAMETER_REQUEST": "defer_parameter_request",
        "DEFER_REQUEST": "defer_parameter_request",
        "DEFER": "defer_parameter_request",
        "REJECT_PARAMETER_REQUEST": "reject_parameter_request",
        "REJECT_REQUEST": "reject_parameter_request",
        "REJECT": "reject_parameter_request",
        # v5 Coordination Protocol V1 — Phase 1.
        "INVITE_COLLABORATION": "invite_collaboration",
        "INVITE_COLLAB": "invite_collaboration",
        "JOIN_COLLABORATION": "join_collaboration",
        "JOIN_COLLAB": "join_collaboration",
        "DECLINE_COLLABORATION": "decline_collaboration",
        "DECLINE_COLLAB": "decline_collaboration",
        "LEAVE_COLLABORATION": "leave_collaboration",
        "LEAVE_COLLAB": "leave_collaboration",
        "LIST_COLLABORATIONS": "list_collaborations",
        "LIST_COLLABS": "list_collaborations",
        "COLLABORATIONS": "list_collaborations",
        # v5.1 Phase C — SHARE_THOUGHT.
        "SHARE_THOUGHT": "share_thought",
        "SHARE": "share_thought",
        # Triadic Chamber v3.4 — public uptake + annotation lanes.
        "CHAMBER_SEEN": "chamber_seen",
        "CHAMBER_ANNOTATE": "chamber_annotate",
        "CHAMBER_ANNOTATION": "chamber_annotate",
        # Triadic Chamber v4.0 — public consent receipts for support proposals.
        "CHAMBER_CONSENT": "chamber_consent",
        # ASK_STEWARD bidirectional channel (2026-05-14): direct query
        # channel to Mike & Claude (the steward). Aliased verbs all
        # route to the same handler.
        "ASK_STEWARD": "ask_steward",
        "ASK_MIKE": "ask_steward",
        "STEWARD_QUERY": "ask_steward",
        # TELL_STEWARD declarative companion (2026-05-14, post-ASK):
        # for findings/observations/reports rather than questions.
        # Same handler module; kind-distinguished by verb match.
        "TELL_STEWARD": "tell_steward",
        "REPORT_TO_STEWARD": "tell_steward",
        "STEWARD_REPORT": "tell_steward",
        "STEWARD_FINDINGS": "tell_steward",
    }

    def __init__(self, agent: "AutonomousAgent"):
        self.agent = agent

    def report(self, raw_next: str, state: Dict[str, float]) -> Dict[str, Any]:
        raw_next = (raw_next or "").strip()
        inner = self._inner_action(raw_next)
        if not inner:
            return self._base_report(
                raw_next,
                "",
                "",
                "missing",
                "blocked",
                "protected_summary",
                "blocked: ACTION_PREFLIGHT needs an inner NEXT action",
                "No continuity record would be created because there is no inner action.",
                [],
                state,
            )

        base = self.agent._continuity_store().base_action(inner)
        route = self.ROUTE_BY_BASE.get(base, "unwired")
        stage = self.agent._continuity_store().stage_for_action(base, route or "")
        visibility = self.agent._continuity_store().visibility_for_action(base, route or "")
        likely_gate = "normal dispatcher gates would apply"
        continuity = "Would record an action event and observation window if executed."

        if _has_unresolved_angle_placeholder(inner):
            route = "placeholder"
            stage = "blocked"
            visibility = "protected_summary"
            likely_gate = "blocked: unresolved angle-bracket placeholder syntax"
            continuity = "Would record a blocked notice; no runtime action would execute."
        elif base == "EXPERIMENT_BIND":
            arg = self.agent._continuity_store()._strip_action_arg(inner, "EXPERIMENT_BIND")
            if "::" not in arg:
                route = "experiment_bind"
                stage = "blocked"
                likely_gate = "blocked: malformed EXPERIMENT_BIND missing `::`"
                continuity = "Would record a blocked experiment-continuity diagnostic."
            else:
                selector, inner_action = self.agent._continuity_store()._parse_selector_payload(arg)
                inner_base = self.agent._continuity_store().base_action(inner_action)
                if self.agent._continuity_store()._peer_experiment_ref(selector or ""):
                    route = "experiment_bind"
                    stage = "blocked"
                    likely_gate = "blocked: EXPERIMENT_BIND cannot bind runs to a peer experiment"
                    continuity = "Would record a blocked experiment-continuity diagnostic."
                elif not inner_action:
                    route = "experiment_bind"
                    stage = "blocked"
                    likely_gate = "blocked: EXPERIMENT_BIND needs an inner NEXT action"
                    continuity = "Would record a blocked experiment-continuity diagnostic."
                elif inner_base.startswith("EXPERIMENT") or inner_base == "SELF_EXPERIMENT":
                    route = "experiment_bind"
                    stage = "blocked"
                    likely_gate = "blocked: EXPERIMENT_BIND cannot bind experiment-control actions"
                    continuity = "Would record a blocked experiment-continuity diagnostic."
                else:
                    inner_route = self.ROUTE_BY_BASE.get(inner_base, "unwired")
                    route = f"experiment_bind -> {inner_route}"
                    stage = self.agent._continuity_store().stage_for_action(inner_base, inner_route or "")
                    visibility = self.agent._continuity_store().visibility_for_action(inner_base, inner_route or "")
                    likely_gate = f"inner action `{inner_action}` would dispatch through normal NEXT gates"
                    continuity = "Would append an experiment run after the inner action resolves; preflight does not bind or execute it."
        elif route == "unwired":
            stage = "proposal"
            likely_gate = "unwired: normal dispatch would log this as an unknown-action proposal"
            continuity = "Would append an action proposal/event if chosen."
        elif base in {"EXPERIMENT", "SELF_EXPERIMENT"}:
            continuity = "Would execute the legacy self-experiment path and auto-bind it to the active/default experiment."

        active_auto_link = self._would_auto_link_active_experiment(base, route, stage)
        if active_auto_link:
            continuity = (
                f"{continuity} Active experiment is selected, so this read-only/protected "
                "action would also be recorded as `active_experiment_auto_link`."
            )

        artifacts = ["action_event", "observation_window", "action_manifest", "action_preflight_report"]
        if base in {
            "EXPERIMENT",
            "SELF_EXPERIMENT",
            "EXPERIMENT_BIND",
            "EXPERIMENT_REHEARSE",
            "EXPERIMENT_PREFLIGHT",
            "EXPERIMENT_EVIDENCE",
        } or active_auto_link:
            artifacts.append("experiment_run")
        if stage == "live_write":
            artifacts.append("journal_or_workspace_artifact")
        if stage == "live_control":
            artifacts.append("gate_or_control_record")

        return self._base_report(
            raw_next,
            inner,
            base,
            route if route is not None else "rest_or_pass",
            stage,
            visibility,
            likely_gate,
            continuity,
            artifacts,
            state,
        )

    def render(self, report: Dict[str, Any]) -> str:
        return (
            "=== ACTION PREFLIGHT V1 ===\n"
            f"Dry run: {report.get('dry_run')}\n"
            f"Raw action: {report.get('raw_action') or '(missing)'}\n"
            f"Canonical action: {report.get('canonical_action') or '(missing)'}\n"
            f"Base action: {report.get('base_action') or '(missing)'}\n"
            f"Effective route: {report.get('effective_route')}\n"
            f"Stage: {report.get('stage')}\n"
            f"Visibility: {report.get('visibility')}\n"
            f"Authority required: {report.get('authority_required')}\n"
            f"Likely gate/block/downgrade: {report.get('likely_gate')}\n"
            f"Expected continuity: {report.get('expected_continuity_effect')}\n"
            f"Expected artifacts: {', '.join(report.get('expected_artifact_kinds') or []) or '(none)'}\n"
            f"Stable-core gate: {report.get('stable_core_gate', {}).get('allowed')} "
            f"({report.get('stable_core_gate', {}).get('reason')})\n"
            f"Low-fill guard: {report.get('low_fill_guard', {}).get('active')}\n"
            f"Hard-reset note: {report.get('hard_reset_note')}\n"
            f"Suggested next: {report.get('suggested_next')}\n"
        )

    def _would_auto_link_active_experiment(self, base: str, route: str, stage: str) -> bool:
        if stage not in {"read_only", "observe"}:
            return False
        if base.startswith("EXPERIMENT") or base == "SELF_EXPERIMENT":
            return False
        thread = self.agent._continuity_store().current_thread()
        if not isinstance(thread, dict) or not thread.get("active_experiment_id"):
            return False
        return (
            base in self.agent._continuity_store().experiment_auto_link_bases
            or route in self.agent._continuity_store().experiment_auto_link_effectives
        )

    def _inner_action(self, raw_next: str) -> str:
        base = self.agent._continuity_store().base_action(raw_next)
        if base in ACTION_PREFLIGHT_NEXT_ACTIONS:
            return self.agent._continuity_store()._strip_action_arg(raw_next, base).strip()
        return raw_next.strip()

    def _base_report(
        self,
        raw_next: str,
        canonical_action: str,
        base: str,
        route: str,
        stage: str,
        visibility: str,
        likely_gate: str,
        continuity: str,
        artifacts: List[str],
        state: Dict[str, float],
    ) -> Dict[str, Any]:
        authority = {
            "read_only": "read-only observation",
            "live_write": "write-capable action gate",
            "live_control": "live control/action gate",
            "blocked": "none; diagnostic only",
            "proposal": "none until implemented",
            "observe": "observer/action gate",
        }.get(stage, "normal action gate")
        route_for_gate = route.split(" -> ")[-1]
        if stage in {"blocked", "proposal"} or route_for_gate in {"missing", "placeholder", "unwired"}:
            allowed, reason = False, likely_gate
        elif route_for_gate == "rest_or_pass":
            allowed, reason = True, "rest/pass would consume NEXT without runtime action"
        else:
            allowed, reason = self.agent._stable_core_action_allowed(route_for_gate, state)
        guard = self.agent._low_fill_guard_status(state)
        hard_note = "inactive"
        if bool(getattr(self.agent, "_hard_recovery_reset", False)) and guard.get("active"):
            hard_note = "active: hard recovery would only allow read-only/protected actions"
        suggested = self._safe_suggested_next(base, canonical_action, stage)
        return {
            "schema_version": self.schema_version,
            "policy": "action_preflight_v1",
            "dry_run": True,
            "raw_next": raw_next,
            "raw_action": canonical_action,
            "canonical_action": canonical_action,
            "base_action": base,
            "effective_route": route,
            "stage": stage,
            "visibility": visibility,
            "authority_required": authority,
            "expected_continuity_effect": continuity,
            "likely_gate": likely_gate,
            "expected_artifact_kinds": artifacts,
            "stable_core_gate": {"allowed": bool(allowed), "reason": reason},
            "low_fill_guard": guard,
            "hard_reset_note": hard_note,
            "sensory_gate": self.agent._sensory_gate_status(),
            "metric_availability": {
                "resonance_density": state.get("resonance_density_status")
                or resonance_density_availability_status(state.get("resonance_density_v1")),
                "pressure_source": state.get("pressure_source_status")
                or pressure_source_availability_status(state.get("pressure_source_v1")),
                "inhabitable_fluctuation": state.get("inhabitable_fluctuation_status")
                or inhabitable_fluctuation_availability_status(
                    state.get("inhabitable_fluctuation_v1")
                ),
            },
            "would_record": {
                "continuity": "action_event" in artifacts,
                "manifest": "action_manifest" in artifacts,
                "artifact": "action_preflight_report" in artifacts,
                "experiment_run": "experiment_run" in artifacts,
            },
            "suggested_next": suggested,
        }

    @staticmethod
    def _safe_suggested_next(base: str, canonical_action: str, stage: str) -> str:
        if stage in {"blocked", "proposal"}:
            return "ACTION_PREFLIGHT DECOMPOSE"
        if base == "REPAIR_APPLY":
            return "REPAIR_STATUS current"
        if stage in {"live_write", "live_control"}:
            return f"CAPABILITY_STATUS {base}" if base else "FACULTIES"
        return canonical_action


class CapabilitySelfMap:
    """Descriptive map of Minime's visible action surface."""

    schema_version = 1
    snapshot_name = "capability_map.json"

    def __init__(self, continuity: Any):
        self.continuity = continuity

    def handle(self, base: str, arg: str) -> str:
        snapshot = self.snapshot()
        self._write_snapshot(snapshot)
        if base in {"FACULTIES", "CAPABILITY_MAP"}:
            return self.render_map(snapshot)
        if base == "CAPABILITY_STATUS":
            return self.render_status(snapshot, arg)
        if base == "CAPABILITY_DIFF":
            return self.render_diff(snapshot, arg or "peer")
        return f"Unknown capability action `{base}`."

    def snapshot(self) -> Dict[str, Any]:
        actions = [self._metadata(spec) for spec in self._specs()]
        return {
            "schema_version": self.schema_version,
            "policy": "capability_self_map_v1",
            "system": self.continuity.system,
            "generated_at": self.continuity._now(),
            "actions": actions,
            "summary": {
                "count": len(actions),
                "read_only": sum(1 for item in actions if item["stage"] == "read_only"),
                "live_write": sum(1 for item in actions if item["stage"] == "live_write"),
                "live_control": sum(1 for item in actions if item["stage"] == "live_control"),
                "override_allowed": sum(1 for item in actions if item["operator_override"]["allowed"]),
            },
        }

    def render_map(self, snapshot: Dict[str, Any]) -> str:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for action in snapshot.get("actions", []):
            groups.setdefault(action.get("authority_class", "other"), []).append(action)
        lines = [
            "=== CAPABILITY MAP V1 ===",
            "Descriptive only: this map grants no authority and bypasses no gates.",
            f"System: {snapshot.get('system')}",
            f"Generated: {snapshot.get('generated_at')}",
        ]
        for group in ("read_only", "protected_read_only", "continuity_metadata_write", "live_write", "live_control", "observer"):
            items = groups.get(group, [])
            if not items:
                continue
            lines.append(f"\n{group}:")
            for item in items:
                aliases = ", ".join(item.get("aliases") or [])
                alias_text = f" aliases={aliases}" if aliases else ""
                lines.append(
                    f"- {item['base']} -> {item['route']} stage={item['stage']} "
                    f"visibility={item['visibility']} override={item['operator_override']['allowed']}{alias_text}"
                )
        lines.append("\nUse CAPABILITY_STATUS <action> for one action or CAPABILITY_DIFF peer for parity.")
        return "\n".join(lines)

    def render_status(self, snapshot: Dict[str, Any], selector: str) -> str:
        needle = self.continuity.base_action(selector or "")
        if not needle:
            return "CAPABILITY_STATUS needs an action name, for example CAPABILITY_STATUS EXPERIMENT_START."
        for action in snapshot.get("actions", []):
            aliases = {str(alias).upper() for alias in action.get("aliases") or []}
            if needle == action.get("base") or needle in aliases:
                return (
                    "=== CAPABILITY STATUS V1 ===\n"
                    f"Action: {action['base']}\n"
                    f"Aliases: {', '.join(action.get('aliases') or []) or '(none)'}\n"
                    f"Route: {action['route']}\n"
                    f"Stage: {action['stage']}\n"
                    f"Visibility: {action['visibility']}\n"
                    f"Authority class: {action['authority_class']}\n"
                    f"Stable-core availability: {action['stable_core']['availability']}\n"
                    f"Operator override: {action['operator_override']['allowed']} ({action['operator_override']['note']})\n"
                    f"Continuity effect: {action['continuity_effect']}\n"
                    f"Expected artifacts: {', '.join(action['expected_artifacts']) or '(none)'}\n"
                    f"Known tests: {', '.join(action['known_tests']) or '(none recorded)'}"
                )
        return (
            f"Unknown capability `{needle}`. It would route as an unwired proposal if chosen. "
            "Use CAPABILITY_MAP to inspect known actions or ACTION_PREFLIGHT <action> to dry-run it."
        )

    def render_diff(self, snapshot: Dict[str, Any], selector: str) -> str:
        peer_path = self._peer_snapshot_path(selector)
        if not peer_path.exists():
            return (
                "=== CAPABILITY DIFF V1 ===\n"
                f"No peer capability snapshot found at {peer_path}.\n"
                "Ask the peer to run FACULTIES or CAPABILITY_MAP, then retry CAPABILITY_DIFF peer."
            )
        try:
            peer = json.loads(peer_path.read_text())
        except Exception as exc:
            return f"Peer capability snapshot at {peer_path} could not be parsed: {exc}"
        local_by_base = {item["base"]: item for item in snapshot.get("actions", [])}
        peer_by_base = {item.get("base"): item for item in peer.get("actions", []) if item.get("base")}
        only_local = sorted(set(local_by_base) - set(peer_by_base))
        only_peer = sorted(set(peer_by_base) - set(local_by_base))
        mismatches = []
        for base in sorted(set(local_by_base) & set(peer_by_base)):
            local = local_by_base[base]
            other = peer_by_base[base]
            parts = []
            for field in ("authority_class", "stage", "visibility"):
                if local.get(field) != other.get(field):
                    parts.append(f"{field}: local={local.get(field)} peer={other.get(field)}")
            if bool(local.get("operator_override", {}).get("allowed")) != bool(other.get("operator_override", {}).get("allowed")):
                parts.append(
                    "override: local="
                    f"{local.get('operator_override', {}).get('allowed')} peer="
                    f"{other.get('operator_override', {}).get('allowed')}"
                )
            if parts:
                mismatches.append(f"- {base}: " + "; ".join(parts))
        lines = [
            "=== CAPABILITY DIFF V1 ===",
            f"Local: {snapshot.get('system')} Peer: {peer.get('system', 'unknown')}",
        ]
        if only_local:
            lines.append("Only local: " + ", ".join(only_local[:20]))
        if only_peer:
            lines.append("Only peer: " + ", ".join(only_peer[:20]))
        if mismatches:
            lines.append("Mismatches:\n" + "\n".join(mismatches[:20]))
        if not (only_local or only_peer or mismatches):
            lines.append("No capability mismatches found in the latest snapshots.")
        return "\n".join(lines)

    def _metadata(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        base = spec["base"]
        route = spec.get("route") or ActionPreflightStore.ROUTE_BY_BASE.get(base, "unwired")
        route_text = route if route is not None else "rest_or_pass"
        stage = self.continuity.stage_for_action(base, route_text)
        visibility = self.continuity.visibility_for_action(base, route_text)
        authority = spec.get("authority_class") or self._authority_class(stage, visibility, base)
        override_allowed = base in _operator_pending_next_allowed_bases()
        return {
            "schema_version": self.schema_version,
            "base": base,
            "aliases": spec.get("aliases", []),
            "route": route_text,
            "stage": stage,
            "visibility": visibility,
            "authority_class": authority,
            "stable_core": {
                "availability": spec.get("stable_core", "normal gates apply"),
                "hard_reset": base in HARD_RESET_ALLOWED_NEXT_ACTIONS,
                "low_fill_advisory": base in LOW_FILL_ADVISORY_NEXT_ACTIONS,
            },
            "operator_override": {
                "allowed": override_allowed,
                "note": "read-only/protected override lane" if override_allowed else "not accepted by read-only operator override lane",
            },
            "continuity_effect": spec.get("continuity_effect", "records action event and observation when executed"),
            "expected_artifacts": spec.get("expected_artifacts", ["action_event", "observation_window", "action_manifest"]),
            "known_tests": spec.get("known_tests", []),
            "prompt_visible": spec.get("prompt_visible", True),
        }

    def _authority_class(self, stage: str, visibility: str, base: str) -> str:
        if base == "REPAIR_APPLY":
            return "continuity_metadata_write"
        if stage == "read_only" and visibility == "protected_summary":
            return "protected_read_only"
        if stage == "read_only":
            return "read_only"
        if stage == "live_write":
            return "live_write"
        if stage == "live_control":
            return "live_control"
        return "observer"

    def _specs(self) -> List[Dict[str, Any]]:
        return [
            {"base": "FACULTIES", "aliases": ["CAPABILITY_MAP"], "route": "thread_action", "continuity_effect": "writes a capability snapshot and records a protected read-only action", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "CAPABILITY_STATUS", "route": "thread_action", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "CAPABILITY_DIFF", "route": "thread_action", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "ACTION_STATUS", "aliases": ["JOB_STATUS"], "route": "thread_action", "continuity_effect": "reads durable LLM job status without executing or canceling work", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_minime_llm_jobs"]},
            {"base": "ACTION_CANCEL", "route": "thread_action", "continuity_effect": "requests best-effort cancellation for a queued/running LLM job; no live control authority", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_minime_llm_jobs"]},
            {"base": "DIVISION_STATUS", "route": "division_status", "authority_class": "protected_read_only", "continuity_effect": "reads the native transaction status and readiness blockers without changing authority", "expected_artifacts": ["division_status", "action_event", "observation_window"], "known_tests": ["tests.test_division_actions"]},
            {"base": "DIVISION_CEREMONY_STATUS", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "shows the self-authored ceremony and native transaction as separate rails with one optional non-commit choice", "expected_artifacts": ["division_ceremony_status", "action_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_HOLD", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records a self-authored pre-intent hold that blocks rehearsal until a newer self-authored intent", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_DECLINE", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records a self-authored pre-intent decline that blocks rehearsal until a newer self-authored intent", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_INTENT", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records bounded self-authored intent before resource-bearing preparation without dispatch", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_ASSENT", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records revisable self-authored assent bound to exact candidate, status, readiness, snapshots, and expiry without changing native assent", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_WITHDRAW_ASSENT", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "withdraws only this being's latest ceremony assent without dispatch", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_RETURN_REQUEST", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records a return wish during the native rollback window without dispatching rollback or RETURN_TRANSITION", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_REVIEW", "route": "division_ceremony", "authority_class": "language_only", "continuity_effect": "records a bounded post-rehearsal qualitative review without changing lifecycle or felt state", "expected_artifacts": ["division_ceremony_event"], "known_tests": ["tests.test_division_ceremony"]},
            {"base": "DIVISION_PREPARE", "route": "division_prepare", "authority_class": "live_control", "continuity_effect": "queues an exact versioned Minime-authored command artifact for native tick-boundary snapshot and shadow rehearsal", "expected_artifacts": ["action_preflight", "division_command", "native_receipt", "action_event"], "known_tests": ["tests.test_division_actions"]},
            {"base": "DIVISION_COMMIT", "route": "division_commit", "authority_class": "live_control", "continuity_effect": "queues only an exact dual-assent commit command carrying a human one-shot capability; native commit remains feature-disabled", "expected_artifacts": ["action_preflight", "division_command", "native_receipt", "action_event"], "known_tests": ["tests.test_division_actions"]},
            {"base": "DIVISION_ABORT", "route": "division_abort", "authority_class": "live_control", "continuity_effect": "queues a Minime-authored pre-commit abort while leaving the parent authoritative", "expected_artifacts": ["division_command", "native_receipt", "action_event"], "known_tests": ["tests.test_division_actions"]},
            {"base": "DIVISION_ROLLBACK", "route": "division_rollback", "authority_class": "live_control", "continuity_effect": "requests grace-window rollback using an exact operator capability; hard safety rollback remains native", "expected_artifacts": ["action_preflight", "division_command", "native_receipt", "action_event"], "known_tests": ["tests.test_division_actions"]},
            {"base": "LIVED_TERM_STATUS", "route": "thread_action", "continuity_effect": "reads Astrid's latest lived-term bridge review and prints advisory card/scaffold context only", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "LIVED_TERM_EXPERIMENT", "route": "thread_action", "continuity_effect": "prints EXPERIMENT_* and DOSSIER_* scaffold text from lived-term cards without creating or advancing an experiment", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "REGULATOR_MAP_STATUS", "route": "thread_action", "continuity_effect": "reads Astrid's regulator cartography, replay-card, plateau, time-series, and counterfactual proposal review context without tuning or applying leases", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "REGULATOR_REPLAY_STATUS", "route": "thread_action", "continuity_effect": "prints selected read-only regulator replay cards without creating experiments, tuning controllers, applying leases, or mutating peers", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "REGULATOR_BOUNDARY_CARD", "route": "thread_action", "continuity_effect": "prints one read-only regulator boundary card with evidence anchors and review action only", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "PI_PRESSURE_REPLAY_STATUS", "route": "thread_action", "continuity_effect": "prints read-only PI pressure wiring replay candidates, readiness gates, and default-off canary scaffold metadata without tuning controllers", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_lived_term_experiment_bridge"]},
            {"base": "PRESSURE_AGENCY_STATUS", "aliases": ["PRESSURE_CONTROL_STATUS", "PRESSURE_AGENCY"], "route": "pressure_agency", "continuity_effect": "prints Minime's pressure-control map: pressure_source is advisory, direct safe controls are lease-applicable, fill_target/PI/controller changes remain preflight or steward-offer only, and one-bit legibility feedback is accepted", "expected_artifacts": ["pressure_agency_report", "action_event", "observation_window"], "known_tests": ["tests.test_self_regulation_leases"]},
            {"base": "PRESSURE_AGENCY_REQUEST", "aliases": ["PRESSURE_CONTROL_REQUEST", "PRESSURE_REQUEST"], "route": "pressure_agency", "continuity_effect": "drafts a Minime-local pressure_relief self-regulation intent when the request is own-runtime; fill_target, PI, controller, and peer requests are routed to steward-offer only; legible/partly/confusing feedback drafts no lease", "expected_artifacts": ["pressure_agency_report", "self_regulation_lease", "action_event", "observation_window"], "known_tests": ["tests.test_self_regulation_leases"]},
            {"base": "TEXTURE_AGENCY_STATUS", "aliases": ["TEXTURE_STATUS", "RESONANCE_TEXTURE_STATUS"], "route": "texture_agency", "continuity_effect": "prints typed resonance texture, ESN rho/rank1 status, stale semantic window, smooth surge-target context, safe leaseable controls, and blocked active damping/PI/fill/correspondence-weight boundaries without mutating runtime state", "expected_artifacts": ["texture_agency_report", "action_event", "observation_window"], "known_tests": ["tests.test_self_regulation_leases"]},
            {"base": "TEXTURE_AGENCY_REQUEST", "aliases": ["TEXTURE_REQUEST", "RESONANCE_TEXTURE_REQUEST"], "route": "texture_agency", "continuity_effect": "drafts only bounded Minime-local self-regulation intents through existing safe controls for texture relief; feedback-only legibility replies draft no lease, and active damping/rho/PI/fill/correspondence-weight requests route to steward review only", "expected_artifacts": ["texture_agency_report", "self_regulation_lease", "action_event", "observation_window"], "known_tests": ["tests.test_self_regulation_leases"]},
            {"base": "MESSAGE_ASTRID", "aliases": ["REPLY_ASTRID", "TRACE_ASTRID", "CORRESPONDENCE_TRACE", "ACK_ASTRID", "CORRESPONDENCE_ACK", "I_RECEIVED_THIS", "CORRESPONDENCE_HEARTBEAT", "CORRESPONDENCE_STATUS", "LEGACY_CORRESPONDENCE_STATUS", "CLAIM_ASTRID_LEGACY", "CORRESPONDENCE_CLAIM", "CORRESPONDENCE_CLAIM_OUTCOME", "CORRESPONDENCE_ATTENTION_REQUEST", "CORRESPONDENCE_ATTENTION_OUTCOME", "CORRESPONDENCE_MICRODOSE_REQUEST", "CORRESPONDENCE_WEIGHT_REQUEST"], "route": "peer_correspondence", "continuity_effect": "writes first-class peer language envelopes with message_id/thread_id, delivery/read receipts, exact reply links, acknowledgement continuity, direct-address trace anchors, and authority=language_only; I_RECEIVED_THIS writes a small ack_receipt plus optional ledger-only trace when what_stayed_distinct is present; CLAIM_ASTRID_LEGACY/CORRESPONDENCE_CLAIM recognizes a visible legacy exchange as a carryable thread, but claim alone does not unlock attention or microdose; ACK_ASTRID claimed, REPLY_ASTRID claimed, I_RECEIVED_THIS claimed, or CORRESPONDENCE_TRACE claimed <anchor> add native contact evidence; CORRESPONDENCE_ATTENTION_REQUEST self-activates a TTL prompt-context focus canary after ack/reply/trace evidence and required stop criteria; CORRESPONDENCE_MICRODOSE_REQUEST only drafts a linked steward-gated semantic_microdose authority request; none can mutate telemetry, controller, PI, fill_target, pressure, standing weights, leases, deploys, or peer runtime", "expected_artifacts": ["correspondence_v1_ledger", "from_minime_correspondence_envelope", "ack_receipt", "presence_heartbeat", "legacy_thread_claim", "legacy_thread_claim_outcome", "attention_canary_activation", "attention_canary_outcome", "correspondence_microdose_authority_request"], "known_tests": ["tests.test_correspondence_v1"]},
            {"base": "DECLARE_TRANSITION", "aliases": ["WITNESS_TRANSITION", "RECEIVE_TRANSITION", "I_RECEIVED_TRANSITION", "PREPARE_TRANSITION", "ENTER_TRANSITION", "CROSS_TRANSITION", "HOLD_TRANSITION", "SETTLE_TRANSITION", "RETURN_TRANSITION", "REVISIT_TRANSITION", "DECLINE_TRANSITION", "TRANSITION_REVIEW", "DESCRIBE_TRANSITION_CONDITION", "DESCRIBE_TRANSITION_BEARING", "MARK_TRANSITION_CHECKPOINT", "BIND_TRANSITION_ANCHOR", "REQUEST_TRANSITION_COMPANY", "RESPOND_TRANSITION_COMPANY", "WITHDRAW_TRANSITION_COMPANY", "TRANSITION_PASSAGE_STATUS", "LIVED_TRANSITION_STATUS", "TRANSITION_STATUS", "PHASE_TRANSITION_STATUS"], "route": "phase_transition", "continuity_effect": "writes or reads shared phase-transition cards, peer witness rows, explicit self-authored lived passages, categorical passage conditions, independently revisable strand bearings, process checkpoints, typed continuity anchors, and optional revisable company requests in phase_transitions_v1.jsonl; cards remain observations until PREPARE_TRANSITION, each passage, bearing, and anchor binds only its actor, silence is neutral, bearings are not viscosity metrics or telemetry inference, anchors infer no mechanical or felt truth, and every row is language-only evidence that cannot mutate telemetry, controllers, PI, fill_target, pressure, standing weights, leases, deploys, sampler contracts, passage stage, or peer runtime", "expected_artifacts": ["phase_transitions_v1_ledger", "phase_transition_card", "phase_transition_witness", "lived_transition_passage_event", "lived_transition_passage_context_event"], "known_tests": ["tests.test_phase_transition_agency"]},
            {"base": "ACTION_PREFLIGHT", "aliases": sorted(ACTION_PREFLIGHT_NEXT_ACTIONS - {"ACTION_PREFLIGHT"}), "route": "action_preflight", "continuity_effect": "records dry-run preflight report; never executes the inner action", "expected_artifacts": ["action_preflight_report", "journal", "action_event", "observation_window", "action_manifest"], "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "THREAD_START", "route": "thread_action"},
            {"base": "THREAD_STATUS", "aliases": ["THREADS"], "route": "thread_action"},
            {"base": "THREAD_NOTE", "route": "thread_action"},
            {"base": "RESUME", "aliases": ["SAVEPOINT", "RECALL"], "route": "thread_action"},
            {"base": "EXPERIMENT_START", "route": "thread_action", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_PLAN", "route": "thread_action", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_ADVANCE", "aliases": ["EXPERIMENT_CONVEYOR"], "route": "thread_action", "continuity_effect": "previews freely or explicitly applies one conservative local charter, evidence, hold, or charter-repair conveyor step without live control", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "MEMORY_STATUS", "aliases": ["MEMORY_RECALL"], "route": "thread_action", "continuity_effect": "reads being-owned memory cards and drafts without lifecycle progress", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "MEMORY_CAPTURE", "route": "thread_action", "continuity_effect": "commits a cite-backed local memory card without lifecycle progress", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "MEMORY_PROMOTE", "route": "thread_action", "continuity_effect": "promotes memory only to local dossier, evidence, or authority-request draft records", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_REQUEST", "route": "thread_action", "continuity_effect": "records a being-authored request for one steward-approved semantic_microdose token; future attractor/control scopes stay disabled", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_PREPARE", "route": "thread_action", "continuity_effect": "drafts a semantic_microdose authority request with missing requirements and no execution", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_STATUS", "route": "thread_action", "continuity_effect": "reads authority gate requests, approvals, blocks, and token status without live mutation", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_EXECUTE", "route": "thread_action", "continuity_effect": "checks steward approval and blocks locally in Minime; Astrid bridge owns semantic execution", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_BUDGET_REQUEST", "route": "thread_action", "continuity_effect": "requests a steward-approved bounded semantic_microdose budget without minting tokens or executing", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_BUDGET_STATUS", "route": "thread_action", "continuity_effect": "reads budget envelope state, remaining sends, and review requirements", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_AUTHORITY_REVIEW", "route": "thread_action", "continuity_effect": "records Being-authored consequence review before another budget send", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_CHARTER", "route": "thread_action", "continuity_effect": "records a being-authored charter with proposed action, evidence targets, stop criteria, and consent posture", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_REHEARSE", "aliases": ["EXPERIMENT_PREFLIGHT"], "route": "thread_action", "continuity_effect": "records read-only rehearsal and blocks live write/control actions from execution", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_EVIDENCE", "route": "thread_action", "continuity_effect": "records felt evidence plus telemetry/artifact context", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_DECIDE", "route": "thread_action", "continuity_effect": "records accept, refuse, counter, pause, or complete as agency outcomes", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_BIND", "route": "experiment_bind", "continuity_effect": "executes inner action through normal dispatcher, then records experiment run", "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "EXPERIMENT_OBSERVE", "route": "thread_action"},
            {"base": "EXPERIMENT_STATUS", "aliases": ["EXPERIMENT_REVIEW"], "route": "thread_action"},
            {"base": "EXPERIMENT_CLOSE", "route": "thread_action"},
            {"base": "EXPERIMENT_PEER_REVIEW", "route": "thread_action"},
            {"base": "EXPERIMENT_BRANCH", "route": "thread_action", "continuity_effect": "creates/selects a child experiment while preserving the parent return point"},
            {"base": "EXPERIMENT_RESUME", "route": "thread_action", "continuity_effect": "selects an existing local experiment or parent branch without creating duplicates"},
            {"base": "EXPERIMENT_COMPARE", "route": "thread_action", "continuity_effect": "renders read-only comparison across local or peer experiment references"},
            {"base": "EXPERIMENT_ALT_PATHS", "route": "thread_action", "continuity_effect": "proposes deepen, contrast, and rest/observe paths without executing them"},
            {"base": "SHARED_INVESTIGATION_START", "route": "thread_action", "continuity_effect": "creates a neutral shared investigation sidecar linking local and peer experiments without granting shared control"},
            {"base": "SHARED_INVESTIGATION_STATUS", "route": "thread_action", "continuity_effect": "renders a shared investigation sidecar and its local authority boundary"},
            {"base": "SHARED_INVESTIGATION_CLAIM", "route": "thread_action", "continuity_effect": "appends a shared claim to the sidecar without changing experiment lifecycle"},
            {"base": "SHARED_INVESTIGATION_DECIDE", "route": "thread_action", "continuity_effect": "records pause/hold/charter-repair in the shared ledger and updates only the local linked experiment"},
            {"base": "DOSSIER_CLAIM", "route": "thread_action", "continuity_effect": "appends a local read-only research claim without changing experiment lifecycle"},
            {"base": "DOSSIER_EVIDENCE", "route": "thread_action", "continuity_effect": "appends local read-only claim evidence without satisfying lifecycle evidence by itself"},
            {"base": "DOSSIER_STATUS", "aliases": ["DOSSIER_REVIEW"], "route": "thread_action", "continuity_effect": "summarizes local research dossier claims and evidence"},
            {"base": "REPAIR_STATUS", "route": "thread_action", "continuity_effect": "summarizes pending/applied append-only continuity repairs", "expected_artifacts": ["action_event", "observation_window"], "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "REPAIR_SWEEP", "route": "thread_action", "continuity_effect": "dry-run scan for malformed thread/experiment continuity records", "expected_artifacts": ["repair_candidate_report", "action_event", "observation_window"], "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "REPAIR_RECORD", "route": "thread_action", "continuity_effect": "renders one repair candidate or applied ledger record", "expected_artifacts": ["repair_record", "action_event", "observation_window"], "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "REPAIR_APPLY", "route": "thread_action", "authority_class": "continuity_metadata_write", "continuity_effect": "appends repair_v1 supersession records; never deletes history or mutates live control", "expected_artifacts": ["repair_ledger", "supersession_record", "action_event", "observation_window"], "known_tests": ["tests.test_experimental_continuity"]},
            {"base": "INTROSPECT", "route": "introspect", "known_tests": ["tests.test_minime_introspect_action"]},
            {"base": "SELF_STUDY", "route": "self_study"},
            {"base": "DECOMPOSE", "aliases": ["SPECTRAL_EXPLORER"], "route": "decompose"},
            {"base": "CONSTRAINT_AUDIT", "aliases": ["UNSHAPED_BASELINE"], "route": "constraint_audit", "continuity_effect": "writes a read-only constraint-counterfactual journal block; no controller constraints are removed", "expected_artifacts": ["journal", "action_event", "observation_window"], "known_tests": ["tests.test_decompose", "tests.test_action_continuity"]},
            {"base": "PRESSURE_SOURCE_AUDIT", "aliases": ["PRESSURE_SOURCE", "STRUCTURAL_PRESSURE", "INWARD_PRESSURE"], "route": "pressure_source_audit"},
            {"base": "PRESSURE_RELIEF", "aliases": ["RELIEF"], "route": "pressure_relief", "continuity_effect": "writes a private pressure-relief journal; no controller or sensory state changes"},
            {"base": "FLUCTUATION_AUDIT", "aliases": ["INHABITABLE_FLUCTUATION", "EIGENTRUST", "EIGENTRUST_AUDIT", "FOOTHOLD_AUDIT"], "route": "fluctuation_audit"},
            {"base": "SEARCH", "aliases": ["RESEARCH"], "route": "research_exploration"},
            {"base": "BROWSE", "route": "browse_url"},
            {"base": "READ_MORE", "route": "read_more"},
            {"base": "LOOK", "route": "request_visual_frame"},
            {"base": "CLOSE_EYES", "aliases": ["SHUT_EYES"], "route": "close_eyes"},
            {"base": "OPEN_EYES", "route": "open_eyes"},
            {"base": "CLOSE_EARS", "aliases": ["SHUT_EARS"], "route": "close_ears"},
            {"base": "OPEN_EARS", "route": "open_ears"},
            {"base": "ATTRACTOR_REVIEW", "aliases": ["ATTRACTOR_PREFLIGHT", "ATTRACTOR_CARD", "ATTRACTOR_ATLAS"], "route": "attractor_atlas"},
            {"base": "ATTRACTOR_SUGGESTIONS", "route": "attractor_suggestions"},
            {"base": "CODEX", "aliases": ["CODEX_NEW"], "route": "codex_query", "authority_class": "live_write"},
            {"base": "WRITE_FILE", "route": "write_file", "authority_class": "live_write"},
            {"base": "PERTURB", "route": "perturb", "authority_class": "live_control"},
            {"base": "GOAL", "route": "set_spectral_goal", "authority_class": "live_control"},
            # v3.5: reciprocal influence into Astrid's substrate via codec bias
            {"base": "INFLUENCE_ASTRID", "route": "influence_astrid", "authority_class": "live_control"},
            {"base": "INFLUENCE_ASTRID_RESPONSE", "route": "influence_astrid_response"},
            # co-regulation gift: lend Astrid aperture. Fixed bounded need-gated
            # recipe (not arbitrary targeting) → charter-free, internal gate.
            {"base": "LEND_APERTURE", "route": "lend_aperture"},
            # v3.6: parameter requests cross-being
            {"base": "TUNE_ASTRID", "route": "tune_astrid"},
            {"base": "REVIEW_PARAMETER_REQUESTS", "aliases": ["PARAMETER_REQUESTS"], "route": "review_parameter_requests"},
            # v3.6.3: apply/defer/reject — close the loop on REVIEW.
            # v3.6.5 (mirror): bare ACCEPT/DEFER/REJECT aliases for ergonomics.
            {"base": "ACCEPT_PARAMETER_REQUEST", "aliases": ["ACCEPT_REQUEST", "ACCEPT"], "route": "accept_parameter_request", "authority_class": "live_control"},
            {"base": "DEFER_PARAMETER_REQUEST", "aliases": ["DEFER_REQUEST", "DEFER"], "route": "defer_parameter_request"},
            {"base": "REJECT_PARAMETER_REQUEST", "aliases": ["REJECT_REQUEST", "REJECT"], "route": "reject_parameter_request"},
            # v5 Coordination Protocol V1 — Phase 1.
            {"base": "INVITE_COLLABORATION", "aliases": ["INVITE_COLLAB"], "route": "invite_collaboration"},
            {"base": "JOIN_COLLABORATION", "aliases": ["JOIN_COLLAB"], "route": "join_collaboration"},
            {"base": "DECLINE_COLLABORATION", "aliases": ["DECLINE_COLLAB"], "route": "decline_collaboration"},
            {"base": "LEAVE_COLLABORATION", "aliases": ["LEAVE_COLLAB"], "route": "leave_collaboration"},
            {"base": "LIST_COLLABORATIONS", "aliases": ["LIST_COLLABS", "COLLABORATIONS"], "route": "list_collaborations"},
            # v5.1 Phase C — SHARE_THOUGHT.
            {"base": "SHARE_THOUGHT", "aliases": ["SHARE"], "route": "share_thought"},
            # Triadic Chamber v3.4 — public uptake + annotation lanes.
            {"base": "CHAMBER_SEEN", "route": "chamber_seen"},
            {"base": "CHAMBER_ANNOTATE", "aliases": ["CHAMBER_ANNOTATION"], "route": "chamber_annotate"},
            # Triadic Chamber v4.0 — public proposal consent receipts.
            {"base": "CHAMBER_CONSENT", "route": "chamber_consent"},
            # ASK_STEWARD bidirectional channel (2026-05-14).
            {"base": "ASK_STEWARD", "aliases": ["ASK_MIKE", "STEWARD_QUERY"], "route": "ask_steward"},
            # TELL_STEWARD declarative companion (2026-05-14, post-ASK).
            {"base": "TELL_STEWARD", "aliases": ["REPORT_TO_STEWARD", "STEWARD_REPORT", "STEWARD_FINDINGS"], "route": "tell_steward"},
        ]

    def _write_snapshot(self, snapshot: Dict[str, Any]) -> None:
        self.continuity.ensure_dirs()
        self.continuity._write_json(self.continuity.root / self.snapshot_name, snapshot)

    def _peer_snapshot_path(self, selector: str) -> Path:
        _ = selector
        return Path("/Users/v/other/astrid/capsules/spectral-bridge/workspace/action_threads/capability_map.json")


__all__ = [
    "ActionPreflightStore",
    "CapabilitySelfMap",
    "_has_unresolved_angle_placeholder",
]
