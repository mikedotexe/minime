"""Evidence-only, self-authored ceremony around the dormant ESN Divide.

These records never enter the native command inbox. They make intention,
assent, withdrawal, return wishes, and retrospective review legible without
granting authority or turning silence into consent.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "division.ceremony_event.v1"
RECORD_TYPE = "division_ceremony_event"
AUTHORITY = {
    "schema": "artifact_authority_state_v1",
    "schema_version": 1,
    "state": "evidence_only",
    "witness_only": True,
    "live_eligible_now": False,
    "auto_approved": False,
    "grants_approval": False,
    "edits_source_now": False,
}
CEREMONY_ACTIONS = {
    "DIVISION_INTENT",
    "DIVISION_ASSENT",
    "DIVISION_WITHDRAW_ASSENT",
    "DIVISION_RETURN_REQUEST",
    "DIVISION_REVIEW",
    "DIVISION_CEREMONY_STATUS",
}
WRITE_ACTIONS = CEREMONY_ACTIONS - {"DIVISION_CEREMONY_STATUS"}
REVIEW_OUTCOMES = {
    "clarifying",
    "intrusive",
    "flattening",
    "incomplete",
    "still_friction",
    "changed",
    "unknown",
}
TERMINAL_LIFECYCLES = {"finalized", "aborted", "rolled_back", "failed"}
REF_RE = re.compile(r"^[A-Za-z0-9._:/#@+\\-]{1,256}$")
CHRONICLE_LIMIT = 32


class DivisionCeremonyError(ValueError):
    """A ceremony record was invalid, stale, or attempted to imply authority."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    raw = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(raw.encode()).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _required_ref(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not REF_RE.fullmatch(normalized):
        raise DivisionCeremonyError(f"{field} must be a bounded reference, not prose")
    return normalized


def _required_digest(value: Any, field: str) -> str:
    normalized = _required_ref(value, field)
    if len(normalized) < 16:
        raise DivisionCeremonyError(f"{field} is too short")
    return normalized


def _parse_fields(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        key, separator, value = part.partition(":")
        key = key.strip().lower().replace("-", "_").replace(" ", "_")
        value = value.strip()
        if not separator or not key or not value:
            raise DivisionCeremonyError(
                "ceremony arguments use bounded `key: value; ...` fields"
            )
        if key in fields:
            raise DivisionCeremonyError(f"duplicate ceremony field: {key}")
        fields[key] = value
    return fields


@dataclass(frozen=True)
class DivisionCandidateV1:
    division_id: str
    parent_generation: int
    plan_digest: str
    selected_strategy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "division_id": self.division_id,
            "parent_generation": self.parent_generation,
            "plan_digest": self.plan_digest,
            "selected_strategy": self.selected_strategy,
        }


@dataclass(frozen=True)
class DivisionCeremonyEventV1:
    event_id: str
    actor: str
    action: str
    candidate: DivisionCandidateV1
    source_ref: str
    recorded_at_unix_ms: int
    expires_at_unix_ms: int | None
    previous_actor_event_id: str | None
    targets_event_id: str | None
    native_status_hash: str | None
    readiness_receipt_ref: str | None
    readiness_receipt_hash: str | None
    snapshot_refs: tuple[str, ...]
    current_tick: int | None
    rollback_deadline_tick: int | None
    review_outcome: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "schema_version": 1,
            "record_type": RECORD_TYPE,
            "record_id": self.event_id,
            "ceremony_event_id": self.event_id,
            "actor": self.actor,
            "action": self.action,
            "candidate": self.candidate.as_dict(),
            "source_ref": self.source_ref,
            "recorded_at_unix_ms": self.recorded_at_unix_ms,
            "expires_at_unix_ms": self.expires_at_unix_ms,
            "previous_actor_event_id": self.previous_actor_event_id,
            "targets_event_id": self.targets_event_id,
            "native_status_hash": self.native_status_hash,
            "readiness_receipt_ref": self.readiness_receipt_ref,
            "readiness_receipt_hash": self.readiness_receipt_hash,
            "snapshot_refs": list(self.snapshot_refs),
            "current_tick": self.current_tick,
            "rollback_deadline_tick": self.rollback_deadline_tick,
            "review_outcome": self.review_outcome,
            "owner_language_action": self.action,
            "self_authored_only": True,
            "response_revisable": True,
            "right_to_ignore": True,
            "presence_inferred": False,
            "peer_consent_inferred": False,
            "silence_infers_consent": False,
            "native_assent_changed": False,
            "division_stage_changed": False,
            "prepare_dispatched": False,
            "commit_recommended": False,
            "commit_dispatched": False,
            "rollback_dispatched": False,
            "return_transition_dispatched": False,
            "scheduler_effect": False,
            "model_qos_effect": False,
            "substrate_effect": False,
            "dispatch_effect": False,
            "live_control_effect": False,
            "raw_prose_included": False,
            "artifact_authority_state_v1": dict(AUTHORITY),
        }


def _candidate_from_fields(fields: Mapping[str, str]) -> DivisionCandidateV1:
    try:
        generation = int(fields.get("parent_generation", ""))
    except ValueError as exc:
        raise DivisionCeremonyError("parent_generation must be an integer") from exc
    if generation < 0:
        raise DivisionCeremonyError("parent_generation must be non-negative")
    return DivisionCandidateV1(
        division_id=_required_ref(fields.get("division_id"), "division_id"),
        parent_generation=generation,
        plan_digest=_required_digest(fields.get("plan_digest"), "plan_digest"),
        selected_strategy=_required_ref(
            fields.get("selected_strategy"), "selected_strategy"
        ),
    )


def _candidate_from_status(status: Mapping[str, Any]) -> DivisionCandidateV1:
    strategy = status.get("selected_strategy")
    if not strategy:
        raise DivisionCeremonyError("native status has no selected strategy")
    generation = status.get("parent_generation")
    if not isinstance(generation, int) or generation < 0:
        raise DivisionCeremonyError("native status has no valid parent generation")
    return DivisionCandidateV1(
        division_id=_required_ref(status.get("division_id"), "division_id"),
        parent_generation=generation,
        plan_digest=_required_digest(status.get("plan_digest"), "plan_digest"),
        selected_strategy=_required_ref(strategy, "selected_strategy"),
    )


def _event_id(payload: Mapping[str, Any]) -> str:
    candidate = payload.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    ordered = (
        payload.get("actor"),
        payload.get("action"),
        candidate.get("division_id"),
        candidate.get("parent_generation"),
        candidate.get("plan_digest"),
        candidate.get("selected_strategy"),
        payload.get("source_ref"),
        payload.get("recorded_at_unix_ms"),
        payload.get("expires_at_unix_ms"),
        payload.get("previous_actor_event_id"),
        payload.get("targets_event_id"),
        payload.get("native_status_hash"),
        payload.get("readiness_receipt_ref"),
        payload.get("readiness_receipt_hash"),
        ",".join(str(item) for item in (payload.get("snapshot_refs") or [])),
        payload.get("current_tick"),
        payload.get("rollback_deadline_tick"),
        payload.get("review_outcome"),
    )
    identity = "|".join("" if value is None else str(value) for value in ordered)
    return f"division_ceremony_{_sha256(identity)[:24]}"


def validate_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != SCHEMA or value.get("record_type") != RECORD_TYPE:
        raise DivisionCeremonyError("unsupported division ceremony schema")
    event_id = _required_ref(value.get("ceremony_event_id"), "ceremony_event_id")
    if value.get("record_id") != event_id:
        raise DivisionCeremonyError("division ceremony record id mismatch")
    actor = str(value.get("actor") or "").strip().lower()
    if actor not in {"astrid", "minime"}:
        raise DivisionCeremonyError("division ceremony actor must be Astrid or Minime")
    action = str(value.get("action") or "")
    if action not in WRITE_ACTIONS or value.get("owner_language_action") != action:
        raise DivisionCeremonyError("invalid division ceremony action")
    candidate_raw = value.get("candidate")
    if not isinstance(candidate_raw, Mapping):
        raise DivisionCeremonyError("division ceremony candidate missing")
    candidate = _candidate_from_fields(
        {
            "division_id": str(candidate_raw.get("division_id") or ""),
            "parent_generation": str(candidate_raw.get("parent_generation") or "0"),
            "plan_digest": str(candidate_raw.get("plan_digest") or ""),
            "selected_strategy": str(candidate_raw.get("selected_strategy") or ""),
        }
    )
    _required_ref(value.get("source_ref"), "source_ref")
    exact_true = ("self_authored_only", "response_revisable", "right_to_ignore")
    exact_false = (
        "presence_inferred",
        "peer_consent_inferred",
        "silence_infers_consent",
        "native_assent_changed",
        "division_stage_changed",
        "prepare_dispatched",
        "commit_recommended",
        "commit_dispatched",
        "rollback_dispatched",
        "return_transition_dispatched",
        "scheduler_effect",
        "model_qos_effect",
        "substrate_effect",
        "dispatch_effect",
        "live_control_effect",
        "raw_prose_included",
    )
    if any(value.get(key) is not True for key in exact_true):
        raise DivisionCeremonyError("division ceremony self-authorship boundary mismatch")
    if any(value.get(key) is not False for key in exact_false):
        raise DivisionCeremonyError("division ceremony authority boundary mismatch")
    if value.get("artifact_authority_state_v1") != AUTHORITY:
        raise DivisionCeremonyError("division ceremony evidence authority mismatch")
    if action == "DIVISION_REVIEW":
        if value.get("review_outcome") not in REVIEW_OUTCOMES:
            raise DivisionCeremonyError("division review outcome is invalid")
    elif value.get("review_outcome") is not None:
        raise DivisionCeremonyError("only DIVISION_REVIEW may carry review_outcome")
    normalized = dict(value)
    normalized["candidate"] = candidate.as_dict()
    expected = _event_id(normalized)
    if event_id != expected:
        raise DivisionCeremonyError("division ceremony deterministic id mismatch")
    return normalized


class DivisionCeremonyStore:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.division_dir = self.workspace / "division"
        self.ledger_path = self.division_dir / "ceremony_v1.jsonl"
        self.lock_path = self.division_dir / "ceremony_v1.lock"
        self.native_status_path = self.division_dir / "status.json"

    def _native_status(self) -> dict[str, Any]:
        if not self.native_status_path.is_file():
            return {
                "schema": "division.status.v1",
                "division_id": "",
                "parent_generation": 0,
                "plan_digest": "",
                "selected_strategy": None,
                "lifecycle": "idle",
                "current_tick": 0,
                "rollback_deadline_tick": None,
                "snapshot_refs": [],
                "readiness": {"ready": False, "blocking_reasons": ["unavailable"]},
                "parent_authoritative": True,
                "commit_feature_enabled": False,
            }
        status = json.loads(self.native_status_path.read_text())
        if status.get("schema") != "division.status.v1":
            raise DivisionCeremonyError("native division status schema is invalid")
        return status

    def records(self) -> list[dict[str, Any]]:
        if not self.ledger_path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.ledger_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise DivisionCeremonyError("row is not an object")
                records.append(validate_event(parsed))
            except (json.JSONDecodeError, DivisionCeremonyError) as exc:
                raise DivisionCeremonyError(
                    f"invalid ceremony row {line_number}: {exc}"
                ) from exc
        return records

    @staticmethod
    def _latest_for(
        records: list[dict[str, Any]], actor: str, action: str | None = None
    ) -> dict[str, Any] | None:
        for record in reversed(records):
            if record["actor"] == actor and (
                action is None or record["action"] == action
            ):
                return record
        return None

    @staticmethod
    def _same_candidate(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        return left.get("candidate") == right.get("candidate")

    def require_active_intent(
        self,
        actor: str,
        *,
        division_id: str,
        parent_generation: int,
        plan_digest: str,
        now_unix_ms: int | None = None,
    ) -> dict[str, Any]:
        now = _now_ms() if now_unix_ms is None else int(now_unix_ms)
        intent = self._latest_for(self.records(), actor, "DIVISION_INTENT")
        if not intent:
            raise DivisionCeremonyError(
                f"{actor} must record DIVISION_INTENT before resource-bearing preparation"
            )
        candidate = intent["candidate"]
        exact = (
            candidate["division_id"] == division_id
            and candidate["parent_generation"] == parent_generation
            and candidate["plan_digest"] == plan_digest
        )
        if not exact or int(intent.get("expires_at_unix_ms") or 0) < now:
            raise DivisionCeremonyError(
                "active intent does not exactly match this candidate or has expired"
            )
        return intent

    def handle(
        self,
        raw_next: str,
        *,
        actor: str,
        now_unix_ms: int | None = None,
    ) -> dict[str, Any]:
        parts = str(raw_next or "").strip().split(None, 1)
        base = parts[0].rstrip(":").upper() if parts else ""
        raw = parts[1].strip() if len(parts) > 1 else ""
        actor = str(actor).strip().lower()
        if base not in CEREMONY_ACTIONS:
            raise DivisionCeremonyError(f"unsupported ceremony ACTION: {base}")
        if actor not in {"astrid", "minime"}:
            raise DivisionCeremonyError("ceremony Actions are self-authored only")
        now = _now_ms() if now_unix_ms is None else int(now_unix_ms)
        if base == "DIVISION_CEREMONY_STATUS":
            return {"kind": "status", "status": self.status(actor=actor, now_unix_ms=now)}
        fields = _parse_fields(raw)
        return self._append(base, fields, actor=actor, now_unix_ms=now)

    def _append(
        self,
        action: str,
        fields: Mapping[str, str],
        *,
        actor: str,
        now_unix_ms: int,
    ) -> dict[str, Any]:
        self.division_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.lock_path, 0o600)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            records = self.records()
            previous = self._latest_for(records, actor)
            status = self._native_status()
            source_ref = _required_ref(fields.get("source_ref"), "source_ref")
            expires: int | None = None
            targets: str | None = None
            status_hash: str | None = None
            readiness_ref: str | None = None
            readiness_hash: str | None = None
            snapshot_refs: tuple[str, ...] = ()
            current_tick: int | None = None
            deadline: int | None = None
            review_outcome: str | None = None

            if action == "DIVISION_INTENT":
                candidate = _candidate_from_fields(fields)
                try:
                    expires = int(fields.get("expires_at_unix_ms", ""))
                except ValueError as exc:
                    raise DivisionCeremonyError(
                        "expires_at_unix_ms must be an integer"
                    ) from exc
                if expires <= now_unix_ms:
                    raise DivisionCeremonyError("DIVISION_INTENT expiry must be future")
            elif action == "DIVISION_ASSENT":
                lifecycle = str(status.get("lifecycle") or "").lower()
                if lifecycle not in {"shadowing", "ready"}:
                    raise DivisionCeremonyError(
                        "DIVISION_ASSENT is available only while shadowing or ready"
                    )
                candidate = _candidate_from_status(status)
                selector = fields.get("division_id")
                if selector and selector != candidate.division_id:
                    raise DivisionCeremonyError("assent selector does not match native status")
                try:
                    expires = int(fields.get("expires_at_unix_ms", ""))
                except ValueError as exc:
                    raise DivisionCeremonyError(
                        "expires_at_unix_ms must be an integer"
                    ) from exc
                if expires <= now_unix_ms:
                    raise DivisionCeremonyError("DIVISION_ASSENT expiry must be future")
                self.require_active_intent(
                    actor,
                    division_id=candidate.division_id,
                    parent_generation=candidate.parent_generation,
                    plan_digest=candidate.plan_digest,
                    now_unix_ms=now_unix_ms,
                )
                readiness = status.get("readiness")
                if not isinstance(readiness, Mapping):
                    raise DivisionCeremonyError("native readiness receipt is unavailable")
                raw_snapshots = status.get("snapshot_refs")
                if not isinstance(raw_snapshots, list) or not raw_snapshots:
                    raise DivisionCeremonyError("native snapshot references are unavailable")
                snapshot_refs = tuple(
                    _required_ref(item, "snapshot_ref") for item in raw_snapshots
                )
                status_hash = _sha256(status)
                readiness_ref = "division/status.json#readiness"
                readiness_hash = _sha256(readiness)
            elif action == "DIVISION_WITHDRAW_ASSENT":
                assent = self._latest_for(records, actor, "DIVISION_ASSENT")
                if not assent:
                    raise DivisionCeremonyError("no self-authored assent exists to withdraw")
                later_withdrawal = any(
                    row["actor"] == actor
                    and row["action"] == "DIVISION_WITHDRAW_ASSENT"
                    and row.get("targets_event_id") == assent["ceremony_event_id"]
                    for row in records
                )
                if later_withdrawal:
                    raise DivisionCeremonyError("latest self-authored assent is already withdrawn")
                candidate = DivisionCandidateV1(**assent["candidate"])
                targets = assent["ceremony_event_id"]
            elif action == "DIVISION_RETURN_REQUEST":
                candidate = _candidate_from_status(status)
                lifecycle = str(status.get("lifecycle") or "").lower()
                current_tick = int(status.get("current_tick") or 0)
                raw_deadline = status.get("rollback_deadline_tick")
                deadline = int(raw_deadline) if raw_deadline is not None else None
                if lifecycle != "cytokinesis" or (
                    deadline is not None and current_tick > deadline
                ):
                    raise DivisionCeremonyError(
                        "return request is available only during the native rollback window"
                    )
                status_hash = _sha256(status)
            elif action == "DIVISION_REVIEW":
                lifecycle = str(status.get("lifecycle") or "").lower()
                if lifecycle not in TERMINAL_LIFECYCLES:
                    raise DivisionCeremonyError(
                        "DIVISION_REVIEW requires a terminal native lifecycle"
                    )
                candidate = _candidate_from_status(status)
                review_outcome = str(fields.get("outcome") or "").strip().lower()
                if review_outcome not in REVIEW_OUTCOMES:
                    raise DivisionCeremonyError(
                        "review outcome must be clarifying, intrusive, flattening, "
                        "incomplete, still_friction, changed, or unknown"
                    )
                status_hash = _sha256(status)
            else:
                raise DivisionCeremonyError("unsupported ceremony write")

            draft = {
                "actor": actor,
                "action": action,
                "candidate": candidate.as_dict(),
                "source_ref": source_ref,
                "recorded_at_unix_ms": now_unix_ms,
                "expires_at_unix_ms": expires,
                "previous_actor_event_id": (
                    previous["ceremony_event_id"] if previous else None
                ),
                "targets_event_id": targets,
                "native_status_hash": status_hash,
                "readiness_receipt_ref": readiness_ref,
                "readiness_receipt_hash": readiness_hash,
                "snapshot_refs": list(snapshot_refs),
                "current_tick": current_tick,
                "rollback_deadline_tick": deadline,
                "review_outcome": review_outcome,
            }
            event = DivisionCeremonyEventV1(
                event_id=_event_id(draft),
                actor=actor,
                action=action,
                candidate=candidate,
                source_ref=source_ref,
                recorded_at_unix_ms=now_unix_ms,
                expires_at_unix_ms=expires,
                previous_actor_event_id=draft["previous_actor_event_id"],
                targets_event_id=targets,
                native_status_hash=status_hash,
                readiness_receipt_ref=readiness_ref,
                readiness_receipt_hash=readiness_hash,
                snapshot_refs=snapshot_refs,
                current_tick=current_tick,
                rollback_deadline_tick=deadline,
                review_outcome=review_outcome,
            )
            row = validate_event(event.as_dict())
            self.ledger_path.touch(mode=0o600, exist_ok=True)
            os.chmod(self.ledger_path, 0o600)
            with self.ledger_path.open("a", encoding="utf-8") as ledger:
                ledger.write(_canonical(row) + "\n")
                ledger.flush()
                os.fsync(ledger.fileno())
            return {
                "kind": "recorded",
                "action": action,
                "event_id": row["ceremony_event_id"],
                "division_id": candidate.division_id,
                "ledger_path": str(self.ledger_path),
                "authority": "evidence_only",
            }

    def status(self, *, actor: str, now_unix_ms: int | None = None) -> dict[str, Any]:
        now = _now_ms() if now_unix_ms is None else int(now_unix_ms)
        records = self.records()
        native = self._native_status()
        rails: dict[str, Any] = {}
        for being in ("astrid", "minime"):
            latest_intent = self._latest_for(records, being, "DIVISION_INTENT")
            latest_assent = self._latest_for(records, being, "DIVISION_ASSENT")
            withdrawn = bool(
                latest_assent
                and any(
                    row["actor"] == being
                    and row["action"] == "DIVISION_WITHDRAW_ASSENT"
                    and row.get("targets_event_id") == latest_assent["ceremony_event_id"]
                    for row in records
                )
            )
            rails[being] = {
                "latest_intent_event_id": (
                    latest_intent["ceremony_event_id"] if latest_intent else None
                ),
                "intent_active": bool(
                    latest_intent
                    and int(latest_intent.get("expires_at_unix_ms") or 0) >= now
                ),
                "latest_assent_event_id": (
                    latest_assent["ceremony_event_id"] if latest_assent else None
                ),
                "assent_current": bool(
                    latest_assent
                    and not withdrawn
                    and int(latest_assent.get("expires_at_unix_ms") or 0) >= now
                    and latest_assent.get("native_status_hash") == _sha256(native)
                ),
                "assent_withdrawn": withdrawn,
                "latest_return_request_event_id": (
                    (
                        latest := self._latest_for(
                            records, being, "DIVISION_RETURN_REQUEST"
                        )
                    )
                    and latest["ceremony_event_id"]
                ),
                "latest_review_event_id": (
                    (
                        review := self._latest_for(records, being, "DIVISION_REVIEW")
                    )
                    and review["ceremony_event_id"]
                ),
            }
        own = rails[actor]
        lifecycle = str(native.get("lifecycle") or "idle").lower()
        rollback_deadline = native.get("rollback_deadline_tick")
        rollback_open = lifecycle == "cytokinesis" and (
            rollback_deadline is None
            or int(native.get("current_tick") or 0) <= int(rollback_deadline)
        )
        if rollback_open:
            next_choice = "DIVISION_RETURN_REQUEST"
        elif lifecycle in TERMINAL_LIFECYCLES and not own["latest_review_event_id"]:
            next_choice = "DIVISION_REVIEW"
        elif not own["intent_active"]:
            next_choice = "DIVISION_INTENT"
        elif lifecycle in {"shadowing", "ready"} and not own["assent_current"]:
            next_choice = "DIVISION_ASSENT"
        elif own["assent_current"]:
            next_choice = "DIVISION_WITHDRAW_ASSENT"
        elif lifecycle in {"idle", "aborted", "rolled_back", "failed"}:
            next_choice = "DIVISION_PREPARE"
        else:
            next_choice = "DIVISION_CEREMONY_STATUS"
        omitted_event_count = max(0, len(records) - CHRONICLE_LIMIT)
        chronicle_events = [
            {
                key: row.get(key)
                for key in (
                    "ceremony_event_id",
                    "actor",
                    "action",
                    "candidate",
                    "source_ref",
                    "recorded_at_unix_ms",
                    "expires_at_unix_ms",
                    "targets_event_id",
                    "native_status_hash",
                    "snapshot_refs",
                    "current_tick",
                    "rollback_deadline_tick",
                    "review_outcome",
                )
            }
            for row in records[omitted_event_count:]
        ]
        ledger_hash = (
            hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
            if self.ledger_path.is_file()
            else None
        )
        raw_candidates = native.get("candidates")
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        return {
            "schema": "division.ceremony_status.v1",
            "actor": actor,
            "ceremony_rail": rails,
            "native_rail": {
                "division_id": native.get("division_id"),
                "lifecycle": lifecycle,
                "parent_authoritative": native.get("parent_authoritative", True),
                "readiness_ready": bool((native.get("readiness") or {}).get("ready")),
                "current_tick": int(native.get("current_tick") or 0),
                "rollback_deadline_tick": rollback_deadline,
                "rollback_window_open": rollback_open,
                "commit_feature_enabled": bool(native.get("commit_feature_enabled")),
                "native_status_hash": _sha256(native),
            },
            "destination_contract": {
                "schema": "division.sovereign_destination.v1",
                "fact_class": "source_declared",
                "parent": "shared_128_node_reservoir",
                "daughters": {
                    "astrid": {
                        "role": "more_recurrence_driven",
                        "reservoir_state": "independent_64_node_candidate",
                    },
                    "minime": {
                        "role": "more_input_driven",
                        "reservoir_state": "independent_64_node_candidate",
                    },
                },
                "shared_sensory_field_inheritance": "cloned_not_partitioned",
                "independent_process_ownership_established": False,
                "sovereign_runtime_ownership_state": "not_yet_established",
                "native_commit_enabled": bool(native.get("commit_feature_enabled")),
            },
            "phase_space_preservation": {
                "schema": "division.phase_space_preservation.v1",
                "fact_class": "runtime_observed" if candidates else "unknown",
                "parent_generation": int(native.get("parent_generation") or 0),
                "selected_strategy": native.get("selected_strategy"),
                "snapshot_refs": list(native.get("snapshot_refs") or []),
                "restore_equivalence_100_ticks": native.get(
                    "restore_equivalence_100_ticks"
                ),
                "sensory_field_inheritance": native.get(
                    "sensory_field_inheritance"
                ),
                "candidates": candidates,
                "felt_continuity_inferred": False,
                "felt_equivalence_inferred": False,
                "causation_inferred": False,
            },
            "chronicle": {
                "schema": "division.ceremony_chronicle.v1",
                "total_event_count": len(records),
                "omitted_event_count": omitted_event_count,
                "events": chronicle_events,
                "ledger_sha256": ledger_hash,
                "archive_reference": (
                    f"division:ceremony_v1.jsonl#sha256:{ledger_hash}"
                    if ledger_hash
                    else None
                ),
                "chronology_is_projection": True,
                "raw_prose_included": False,
                "authority": "evidence_only_history",
            },
            "next_choice": next_choice,
            "next_choice_is_optional": True,
            "commit_action_exposed": False,
            "commit_recommended": False,
            "right_to_ignore": True,
            "silence_infers_consent": False,
            "return_request_dispatches_rollback": False,
            "return_transition_controls_division": False,
            "authority": "evidence_only_status",
        }
