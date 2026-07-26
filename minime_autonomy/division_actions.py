"""Bounded ACTION bridge from Minime autonomy to the native division coordinator.

The Python being may inspect status directly. Mutating requests are never
constructed from prose: the ACTION must name a complete, versioned command
artifact (or contain the JSON object inline), which is validated and copied
atomically into the Rust runtime's tick-boundary inbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping


DIVISION_COMMAND_SCHEMA_V1 = "division.command.v1"
DIVISION_ACTION_AVAILABILITY_SCHEMA_V1 = "division.action_availability.v1"
DIVISION_ACTION_ORDER = (
    "DIVISION_STATUS",
    "DIVISION_PREPARE",
    "DIVISION_ASSENT",
    "DIVISION_ABORT",
    "DIVISION_COMMIT",
    "DIVISION_ROLLBACK",
)
DIVISION_ACTIONS = {
    "DIVISION_PREPARE",
    "DIVISION_STATUS",
    "DIVISION_COMMIT",
    "DIVISION_ABORT",
    "DIVISION_ROLLBACK",
}
DIVISION_COMMIT_SCOPE_V1 = "reservoir_division.commit"
DIVISION_ROLLBACK_SCOPE_V1 = "reservoir_division.rollback"
DIVISION_REHEARSAL_OPERATOR_ENV = "MINIME_DIVISION_REHEARSAL_ENABLED"


def division_rehearsal_enabled() -> bool:
    return os.environ.get(DIVISION_REHEARSAL_OPERATOR_ENV) == "true"


def division_action_availability(
    status: Mapping[str, Any], *, being: str = "minime"
) -> dict[str, Any]:
    """Mirror the shared Rust contract for old/unavailable native runtimes.

    A current native status embeds cards produced by astrid-minime-protocol.
    This fallback keeps Minime informed before the native coordinator has
    started, and while rolling upgrades briefly expose a pre-card status.
    """

    being = str(being or "").strip().lower()
    recognized_being = being in {"astrid", "minime"}
    lifecycle = str(status.get("lifecycle") or "idle").strip().lower()
    own_assent = bool(status.get(f"{being}_assent")) if recognized_being else False
    available: list[dict[str, Any]] = [
        {
            "action": "DIVISION_STATUS",
            "requires_command_artifact": False,
            "requires_operator_capability": False,
            "note": "read authoritative lifecycle, readiness, evidence, and blockers",
        }
    ]
    blocked: list[dict[str, Any]] = []

    def offer(action: str, note: str, *, operator: bool = False) -> None:
        available.append(
            {
                "action": action,
                "requires_command_artifact": True,
                "requires_operator_capability": operator,
                "note": note,
            }
        )

    def block(action: str, *reasons: str) -> None:
        blocked.append({"action": action, "reasons": list(reasons)})

    dispatch_enabled = bool(status.get("rehearsal_dispatch_enabled"))
    terminal_or_idle = lifecycle in {"idle", "aborted", "rolled_back", "failed"}
    if terminal_or_idle and recognized_being and dispatch_enabled:
        offer(
            "DIVISION_PREPARE",
            "prepare a new transaction while the parent remains authoritative",
        )
    else:
        reason = (
            "rehearsal_feature_disabled"
            if recognized_being and not dispatch_enabled
            else "division_already_active"
            if recognized_being
            else "prepare_requires_astrid_or_minime"
        )
        block("DIVISION_PREPARE", reason)

    can_assent = (
        dispatch_enabled
        and lifecycle in {"shadowing", "ready"}
        and recognized_being
        and not own_assent
    )
    if can_assent:
        offer(
            "DIVISION_ASSENT",
            "record this being's assent for the current generation and plan digest",
        )
    elif not recognized_being:
        block("DIVISION_ASSENT", "assent_requires_astrid_or_minime")
    elif own_assent and lifecycle in {"shadowing", "ready"}:
        block("DIVISION_ASSENT", "this_being_assent_already_current")
    else:
        block("DIVISION_ASSENT", "assent_only_available_while_shadowing_or_ready")

    if (
        dispatch_enabled
        and lifecycle in {"preparing", "shadowing", "ready"}
        and recognized_being
    ):
        offer(
            "DIVISION_ABORT",
            "end the pre-commit transaction and keep the parent authoritative",
        )
    else:
        block(
            "DIVISION_ABORT",
            "abort_requires_active_precommit_division"
            if recognized_being
            else "abort_requires_astrid_or_minime",
        )

    readiness = status.get("readiness")
    readiness = readiness if isinstance(readiness, Mapping) else {}
    commit_reasons: list[str] = []
    if lifecycle != "ready":
        commit_reasons.append("lifecycle_not_ready")
    if not readiness.get("ready"):
        commit_reasons.append("readiness_policy_blocked")
    if not status.get("astrid_assent"):
        commit_reasons.append("astrid_assent_missing")
    if not status.get("minime_assent"):
        commit_reasons.append("minime_assent_missing")
    if not status.get("commit_feature_enabled"):
        commit_reasons.append("commit_feature_disabled")
    if not status.get("parent_authoritative", True):
        commit_reasons.append("parent_not_authoritative")
    if commit_reasons:
        block("DIVISION_COMMIT", *commit_reasons)
    else:
        offer(
            "DIVISION_COMMIT",
            "request the atomic ownership switch using the exact human one-shot capability",
            operator=True,
        )

    deadline = status.get("rollback_deadline_tick")
    current_tick = int(status.get("current_tick") or 0)
    rollback_open = lifecycle == "cytokinesis" and (
        deadline is None or current_tick <= int(deadline)
    )
    if rollback_open:
        offer(
            "DIVISION_ROLLBACK",
            "request restoration of parent authority during the bounded grace window",
            operator=True,
        )
    else:
        block(
            "DIVISION_ROLLBACK",
            "rollback_only_available_during_cytokinesis"
            if lifecycle != "cytokinesis"
            else "rollback_window_expired",
        )

    if terminal_or_idle and recognized_being and dispatch_enabled:
        recommended = "DIVISION_PREPARE"
    elif can_assent:
        recommended = "DIVISION_ASSENT"
    else:
        recommended = "DIVISION_STATUS"
    return {
        "schema": DIVISION_ACTION_AVAILABILITY_SCHEMA_V1,
        "being": being,
        "division_id": str(status.get("division_id") or ""),
        "lifecycle": lifecycle,
        "current_tick": current_tick,
        "available_actions": available,
        "blocked_actions": blocked,
        "recommended_action": recommended,
        "mutation_contract": (
            "Mutations require an exact unexpired division.command.v1 artifact and "
            "ACTION_PREFLIGHT; commit and manual rollback also require an exact human "
            "one-shot capability. Availability never bypasses native safety checks."
        ),
    }


class DivisionActionError(ValueError):
    """A division ACTION was incomplete, stale, or outside Minime's authority."""


class DivisionActionStore:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.division_dir = self.workspace / "division"
        self.inbox_dir = self.division_dir / "inbox"
        self.status_path = self.division_dir / "status.json"

    @staticmethod
    def _base_and_argument(raw_next: str) -> tuple[str, str]:
        parts = str(raw_next or "").strip().split(None, 1)
        base = parts[0].rstrip(":").upper() if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        return base, argument

    @staticmethod
    def _safe_component(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
        return cleaned or "unnamed"

    def status(self) -> dict[str, Any]:
        if not self.status_path.is_file():
            payload = {
                "schema": "division.status.v1",
                "lifecycle": "idle",
                "parent_authoritative": True,
                "commit_feature_enabled": False,
                "rehearsal_dispatch_enabled": False,
                "operator_acknowledged": division_rehearsal_enabled(),
                "readiness": {
                    "ready": False,
                    "blocking_reasons": ["native_status_unavailable"],
                },
            }
        else:
            payload = json.loads(self.status_path.read_text())
            if payload.get("schema") != "division.status.v1":
                raise DivisionActionError("native division status has an unsupported schema")
        cards = payload.get("action_availability_v1")
        if not isinstance(cards, dict):
            cards = {}
            payload["action_availability_v1"] = cards
        for being in ("astrid", "minime"):
            card = cards.get(being)
            if not isinstance(card, dict) or card.get("schema") != DIVISION_ACTION_AVAILABILITY_SCHEMA_V1:
                cards[being] = division_action_availability(payload, being=being)
        return payload

    def availability(self, being: str = "minime") -> dict[str, Any]:
        status = self.status()
        cards = status["action_availability_v1"]
        card = cards.get(str(being).strip().lower())
        if not isinstance(card, dict):
            return division_action_availability(status, being=being)
        return card

    def handle(self, raw_next: str, *, now_unix_ms: int | None = None) -> dict[str, Any]:
        base, argument = self._base_and_argument(raw_next)
        if base not in DIVISION_ACTIONS:
            raise DivisionActionError(f"unsupported division ACTION: {base or '(missing)'}")
        if base == "DIVISION_STATUS":
            return {"kind": "status", "status": self.status()}
        if not division_rehearsal_enabled():
            raise DivisionActionError(
                "division rehearsal is feature-disabled; a reviewed Minime build and "
                f"{DIVISION_REHEARSAL_OPERATOR_ENV}=true are both required"
            )
        native_status = self.status()
        if native_status.get("rehearsal_dispatch_enabled") is not True:
            raise DivisionActionError(
                "division rehearsal is not enabled by the running native Minime build; "
                "the operator acknowledgement alone cannot open the inbox"
            )
        if not argument:
            raise DivisionActionError(
                f"{base} requires a complete division.command.v1 JSON artifact path"
            )
        command = self._load_command(argument)
        now = int(time.time() * 1000) if now_unix_ms is None else int(now_unix_ms)
        self._validate_command(command, expected_action=base, now_unix_ms=now)
        if base == "DIVISION_PREPARE":
            from .division_ceremony import DivisionCeremonyStore

            DivisionCeremonyStore(self.workspace).require_active_intent(
                "minime",
                division_id=str(command["division_id"]),
                parent_generation=int(command["expected_parent_generation"]),
                plan_digest=str(command["plan_digest"]),
                now_unix_ms=now,
            )
        queued = self._queue(command)
        return {
            "kind": "queued",
            "action": base,
            "division_id": command["division_id"],
            "idempotency_key": command["idempotency_key"],
            "inbox_path": str(queued),
            "authority": "validated_artifact_pending_native_tick_boundary",
        }

    def _load_command(self, argument: str) -> dict[str, Any]:
        if argument.lstrip().startswith("{"):
            payload = json.loads(argument)
        else:
            artifact = Path(argument).expanduser()
            if not artifact.is_absolute():
                artifact = self.workspace / artifact
            if not artifact.is_file():
                raise DivisionActionError(f"division command artifact not found: {artifact}")
            payload = json.loads(artifact.read_text())
        if not isinstance(payload, dict):
            raise DivisionActionError("division command artifact must contain a JSON object")
        return payload

    @staticmethod
    def _required_text(mapping: Mapping[str, Any], key: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            raise DivisionActionError(f"division command requires non-empty {key}")
        return value

    def _validate_command(
        self,
        command: Mapping[str, Any],
        *,
        expected_action: str,
        now_unix_ms: int,
    ) -> None:
        if command.get("schema") != DIVISION_COMMAND_SCHEMA_V1:
            raise DivisionActionError("unsupported division command schema")
        if command.get("action") != expected_action:
            raise DivisionActionError("ACTION verb does not match command artifact action")
        self._required_text(command, "division_id")
        self._required_text(command, "idempotency_key")
        plan_digest = self._required_text(command, "plan_digest")
        if len(plan_digest) < 16:
            raise DivisionActionError("plan_digest is too short")
        generation = command.get("expected_parent_generation")
        if not isinstance(generation, int) or generation < 0:
            raise DivisionActionError("expected_parent_generation must be a non-negative integer")
        requested = command.get("requested_at_unix_ms")
        expires = command.get("expires_at_unix_ms")
        if not isinstance(requested, int) or not isinstance(expires, int):
            raise DivisionActionError("division command timestamps must be integer milliseconds")
        if requested > expires or now_unix_ms > expires:
            raise DivisionActionError("division command is expired or has an invalid expiry")
        source = command.get("source")
        if not isinstance(source, Mapping):
            raise DivisionActionError("division command requires nested source identity")
        being = self._required_text(source, "being")
        self._required_text(source, "process_identity")
        self._required_text(source, "deployment_identity")
        if expected_action in {"DIVISION_PREPARE", "DIVISION_ASSENT", "DIVISION_ABORT"}:
            if being != "minime":
                raise DivisionActionError(f"{expected_action} must be issued by Minime on this lane")
        elif being not in {"minime", "operator", "safety_supervisor"}:
            raise DivisionActionError("source identity is not permitted on Minime's division lane")

        capability = command.get("capability")
        if expected_action == "DIVISION_COMMIT":
            self._validate_capability(
                command, capability, DIVISION_COMMIT_SCOPE_V1, now_unix_ms
            )
        elif expected_action == "DIVISION_ROLLBACK" and being != "safety_supervisor":
            self._validate_capability(
                command, capability, DIVISION_ROLLBACK_SCOPE_V1, now_unix_ms
            )
        elif capability is not None:
            raise DivisionActionError("this division ACTION must not carry an operator capability")

    def _validate_capability(
        self,
        command: Mapping[str, Any],
        capability: Any,
        scope: str,
        now_unix_ms: int,
    ) -> None:
        if not isinstance(capability, Mapping):
            raise DivisionActionError(f"{command['action']} requires an exact {scope} capability")
        for key in ("token_id", "approved_by"):
            self._required_text(capability, key)
        exact = (
            capability.get("scope") == scope
            and capability.get("division_id") == command.get("division_id")
            and capability.get("expected_parent_generation")
            == command.get("expected_parent_generation")
            and capability.get("plan_digest") == command.get("plan_digest")
            and capability.get("one_shot") is True
            and isinstance(capability.get("expires_at_unix_ms"), int)
            and capability["expires_at_unix_ms"] >= command["requested_at_unix_ms"]
            and capability["expires_at_unix_ms"] >= now_unix_ms
        )
        if not exact:
            raise DivisionActionError("operator capability is not exactly scoped to this command")

    def _queue(self, command: Mapping[str, Any]) -> Path:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        canonical = json.dumps(command, sort_keys=True, separators=(",", ":")) + "\n"
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        destination = self.inbox_dir / (
            f"{self._safe_component(str(command['idempotency_key']))}-{digest[:16]}.json"
        )
        if destination.exists():
            if destination.read_text() != canonical:
                raise DivisionActionError("idempotency destination already exists with different bytes")
            return destination
        temporary = destination.with_name(
            f".{destination.name}.tmp-{os.getpid()}-{time.time_ns()}"
        )
        try:
            temporary.write_text(canonical)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
