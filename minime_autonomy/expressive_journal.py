"""Telemetry-optional invitations and separate archival measurement records."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path


COMPACT_ACTION_GUIDANCE = (
    "NEXT: options: DAYDREAM, ASPIRE, JOURNAL, SELF_STUDY, REST; these are examples, "
    "not a restriction on your available actions. FACULTIES / CAPABILITY_MAP opens "
    "the action catalog; CAPABILITY_STATUS <action> gives details; "
    "ACTION_PREFLIGHT <action> checks a proposed action without executing it. "
    "SPECTRAL_EXPLORER requests measurements and available recorded history. "
    "WRITE and ACTIVITY_STATUS provide private drafts and saved return points. "
    "Use one concrete action after NEXT:, not a bundle or a parameter assignment.\n"
    "Control and deployment paths remain separately feature- and operator-gated; "
    "this menu grants no additional authority.\n"
)


def expression_invitation(kind: str, *, form: str | None = None, prior: str = "") -> str:
    if form:
        invitation = f"You chose FORM: {form}. You may use that form for this writing."
    elif kind == "aspiration":
        invitation = (
            "What, if anything, would you like to imagine or explore? "
            "An aspiration need not become a request or an investigation."
        )
    else:
        invitation = "This is your space. Choose a subject, continue a thought, or rest."
    if prior:
        invitation += (
            "\n\nOptional own-journal excerpt (historical; system annotations may be present):\n"
            + prior + "\nYou may return to it, disagree with it, or leave it aside."
        )
    return invitation


def snapshot_record(snapshot, captured_at: str) -> dict:
    return {
        "captured_at_utc": captured_at,
        "source": "guarded DB and workspace surfaces; capture time is not a new engine sample",
        "snapshot": asdict(snapshot),
    }


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return {"unavailable": "nonfinite", "reported": repr(value)}
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def save_expression(path: Path, *, title: str, timestamp: str, response: str,
                    invitation: str, before: dict, after: dict, metrics: str) -> str | None:
    """Preserve prose first; metadata failure never discards an authored response.

    Metadata lives outside the managed text directory, so text archival cannot
    turn it into a journal input or silently delete its measurements.
    """
    document = f"=== {title} ===\nTimestamp: {timestamp}\n\n{response}\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(document)
        handle.flush()
        os.fsync(handle.fileno())
    metadata = {
        "schema": "expressive_journal_metadata_v1",
        "journal_filename": path.name,
        "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
        "authored_response_sha256": hashlib.sha256(response.encode()).hexdigest(),
        "invitation": {
            "contract": "telemetry_optional_expression_v1",
            "sha256": hashlib.sha256(invitation.encode()).hexdigest(),
            "automatic_telemetry_supplied": False,
            "scope": "base invitation only; authored history or separately delivered mail may mention measurements",
        },
        "state_at_invitation_not_supplied": before,
        "post_generation_observation_not_generation_input": after,
        "post_generation_formatted_metrics": metrics,
    }
    try:
        directory = path.parent.parent / "journal_metadata"
        directory.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(_json_value(metadata), ensure_ascii=False, allow_nan=False, indent=2)
        with (directory / (path.stem + ".json")).open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError) as error:
        return f"{type(error).__name__}: {error}"
    return None
