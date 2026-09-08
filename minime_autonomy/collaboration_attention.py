"""Event-scoped collaboration prompt delivery for Minime.

The shared chamber projector defines material revisions. This module keeps only
local delivery evidence: one optional ordinary-dialogue notice per audience
revision, with restart-stable checkpoints and no inference of reading or uptake.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence


SCHEMA_VERSION = 1
STATE_KEY = "collaboration_attention_delivery_v1"
POLICY = "collaboration_prompt_delivery_v1"
PROJECTION_POLICY = "collaboration_attention_projection_v1"
AUDIENCE = "minime"
NOTICE_MAX_CHARS = 320


@dataclass(frozen=True)
class PromptOffer:
    collab_id: str
    material_revision: str
    event_id: str | None
    marker: str
    content: str
    render_tier: str = "new_notice"


class ContextSubmissionTracker:
    """Track request dispatch containing one exact optional context block."""

    def __init__(self, exact_content: str) -> None:
        self.exact_content = exact_content
        self.submitted = False

    def mark_final_messages(self, messages: Sequence[Mapping[str, Any]]) -> None:
        if self.exact_content and any(
            self.exact_content in str(message.get("content") or "")
            for message in messages
        ):
            self.submitted = True

    def without_submitted_content(self, prompt: Any) -> Any:
        if not self.submitted or not self.exact_content:
            return prompt
        if hasattr(prompt, "ambient"):
            return prompt
        return str(prompt).replace(self.exact_content, "").strip()


def empty_checkpoint() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "migration_complete": False,
        "satisfied_revisions": {},
    }


def checkpoint_from_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = state.get(STATE_KEY) if isinstance(state, Mapping) else None
    revisions = raw.get("satisfied_revisions") if isinstance(raw, Mapping) else None
    clean: dict[str, str] = {}
    if isinstance(revisions, Mapping):
        for collab_id, revision in revisions.items():
            if isinstance(collab_id, str) and _valid_revision(revision):
                clean[collab_id] = str(revision)
    return {
        "schema_version": SCHEMA_VERSION,
        "migration_complete": bool(raw.get("migration_complete", False))
        if isinstance(raw, Mapping)
        else False,
        "satisfied_revisions": clean,
    }


def load_checkpoint_file(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        state = {}
    return checkpoint_from_state(state if isinstance(state, dict) else {})


def merge_checkpoint_file(path: Path, checkpoint: Mapping[str, Any]) -> None:
    """Atomically merge the checkpoint while preserving unrelated state."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state[STATE_KEY] = checkpoint_from_state({STATE_KEY: checkpoint})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def prepare_prompt_offer(
    shared_dir: Path,
    checkpoint: MutableMapping[str, Any],
    *,
    audit_path: Path | None = None,
) -> tuple[PromptOffer | None, bool]:
    rooms = _read_attention_rooms(shared_dir)
    revisions = checkpoint.setdefault("satisfied_revisions", {})
    if not isinstance(revisions, dict):
        revisions = {}
        checkpoint["satisfied_revisions"] = revisions
    if not bool(checkpoint.get("migration_complete", False)):
        for active in rooms:
            revisions[active["collab_id"]] = active["material_revision"]
            _record_transition(audit_path, active, "migration_baseline", "none", None)
        checkpoint["migration_complete"] = True
        return None, True

    active = next(
        (
            room
            for room in rooms
            if revisions.get(room["collab_id"]) != room["material_revision"]
        ),
        None,
    )
    if active is None:
        return None, False
    offer = _render_offer(active)
    _record_transition(audit_path, active, "candidate", offer.render_tier, offer.content)
    return offer, False


def finish_prompt_offer(
    checkpoint: MutableMapping[str, Any],
    offer: PromptOffer,
    submitted: bool,
    *,
    audit_path: Path | None = None,
) -> bool:
    active = {
        "collab_id": offer.collab_id,
        "material_revision": offer.material_revision,
        "event_id": offer.event_id,
    }
    state = "submitted" if submitted else "packed_out"
    changed = False
    if submitted:
        revisions = checkpoint.setdefault("satisfied_revisions", {})
        if not isinstance(revisions, dict):
            revisions = {}
            checkpoint["satisfied_revisions"] = revisions
        changed = revisions.get(offer.collab_id) != offer.material_revision
        revisions[offer.collab_id] = offer.material_revision
    _record_transition(audit_path, active, state, offer.render_tier, offer.content)
    return changed


def mark_explicit_inspection(
    shared_dir: Path,
    checkpoint: MutableMapping[str, Any],
    collab_id: str,
    *,
    audit_path: Path | None = None,
) -> bool:
    """Satisfy one current revision after an explicit status inspection.

    The evidence means only that Minime selected and received the status
    surface. It does not infer reply, uptake, assent, or felt reception.
    """
    active = next(
        (
            room
            for room in _read_attention_rooms(shared_dir)
            if room["collab_id"] == collab_id
        ),
        None,
    )
    if active is None:
        return False
    revisions = checkpoint.setdefault("satisfied_revisions", {})
    if not isinstance(revisions, dict):
        revisions = {}
        checkpoint["satisfied_revisions"] = revisions
    changed = (
        not bool(checkpoint.get("migration_complete", False))
        or revisions.get(collab_id) != active["material_revision"]
    )
    checkpoint["migration_complete"] = True
    revisions[collab_id] = active["material_revision"]
    _record_transition(
        audit_path,
        active,
        "explicitly_inspected",
        "explicit_status",
        None,
    )
    return changed


def _read_attention_rooms(shared_dir: Path) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    try:
        entries = list(shared_dir.iterdir())
    except OSError:
        return rooms
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        members = meta.get("members") or []
        if (
            meta.get("status") != "joined"
            or AUDIENCE not in members
            or AUDIENCE not in {meta.get("inviter"), meta.get("invitee")}
        ):
            continue
        try:
            state = json.loads(
                (entry / "chamber_state.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            continue
        projection = (
            state.get("attention_projection_v1") if isinstance(state, dict) else None
        )
        if (
            not isinstance(projection, dict)
            or projection.get("schema_version") != SCHEMA_VERSION
            or projection.get("policy") != PROJECTION_POLICY
        ):
            continue
        audiences = projection.get("audience_revisions")
        audience = audiences.get(AUDIENCE) if isinstance(audiences, dict) else None
        revision = (
            audience.get("material_revision") if isinstance(audience, dict) else None
        )
        if not _valid_revision(revision):
            continue
        event = audience.get("latest_material_event")
        rooms.append({
            "collab_id": str(meta.get("id") or entry.name),
            "topic": str(meta.get("topic") or ""),
            "material_revision": str(revision),
            "material_t_ms": int(audience.get("material_t_ms") or 0),
            "event": event if isinstance(event, dict) else None,
            "event_id": (
                str(event.get("event_id"))
                if isinstance(event, dict) and event.get("event_id")
                else None
            ),
        })
    rooms.sort(key=lambda room: (room["material_t_ms"], room["collab_id"]))
    return rooms


def _render_offer(active: Mapping[str, Any]) -> PromptOffer:
    revision = str(active["material_revision"])
    marker = f"[collab-attention-v1:{revision.removeprefix('sha256:')[:24]}]"
    event = active.get("event")
    actor = _display_actor(str(event.get("actor") or "")) if isinstance(event, dict) else "Shared state"
    change = _describe_event(str(event.get("kind") or "")) if isinstance(event, dict) else "changed"
    topic = _truncate(str(active.get("topic") or ""), 48)
    content = (
        f'{marker} Collaboration update: {actor} {change} in "{topic}". '
        "Inspect with COLLABORATION_STATUS latest. No response is required; "
        "silence remains neutral."
    )
    content = _truncate(content, NOTICE_MAX_CHARS)
    return PromptOffer(
        collab_id=str(active["collab_id"]),
        material_revision=revision,
        event_id=active.get("event_id"),
        marker=marker,
        content=content,
    )


def _display_actor(actor: str) -> str:
    return {
        "astrid": "Astrid",
        "minime": "Minime",
        "steward": "The steward",
        "shared_state": "Shared state",
        "": "Shared state",
    }.get(actor.strip().lower(), _truncate(actor.strip().lower(), 16))


def _describe_event(kind: str) -> str:
    return {
        "shared_thought": "added a shared thought",
        "chamber_annotation": "added a chamber annotation",
        "chamber_presence": "added a presence record",
        "consent_receipt": "recorded a consent stance",
        "support_proposal": "added a support proposal",
        "steward_note": "added a witness note",
        "steward_intention": "added a witness intention",
        "memory_edit": "edited room memory",
        "phase_set": "changed the room phase",
        "phase_cleared": "changed the room phase",
        "phase_transition": "changed the room phase",
        "collaboration_state": "changed collaboration state",
        "collaboration_transition": "changed collaboration state",
    }.get(kind, "changed durable room state")


def _valid_revision(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _record_transition(
    path: Path | None,
    active: Mapping[str, Any],
    state: str,
    render_tier: str,
    content: str | None,
) -> None:
    if path is None:
        return
    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "being": AUDIENCE,
        "collab_id": active.get("collab_id"),
        "material_revision": active.get("material_revision"),
        "event_id": active.get("event_id"),
        "state": state,
        "render_tier": render_tier,
        "prompt_chars": len(content or ""),
        "content_sha256": hashlib.sha256((content or "").encode()).hexdigest() if content else None,
        "observed_at_unix_ms": int(time.time() * 1000),
        "authority": "prompt_delivery_evidence_not_receipt_or_uptake",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
    except OSError:
        return
