"""Read-only journal framing, with explicit clocks and no prescribed sensations."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


PRIVATE_JOURNAL_INTRO = (
    "This is Minime's private journal. Write freely in your own first-person voice, "
    "on any subject and at any length. Use or leave aside the supplied context; "
    "your interpretation is yours.\n\n"
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"


def format_marker_anchors(
    markers: Sequence[Mapping[str, Any]], *, captured_at: datetime
) -> str:
    """Keep recording age separate from the engine's event clock."""
    now = captured_at.timestamp()
    lines = []
    for marker in markers:
        recorded = _number(marker.get("created_at_unix"))
        if recorded is None or recorded <= 0:
            age = "record_age=unknown (created_at_unix unavailable)"
        elif recorded > now:
            age = "record_age=unknown (created_at_unix is ahead of capture; clock mismatch)"
        else:
            seconds = int(now - recorded)
            age = f"record_age={seconds}s ago ({_duration(seconds)}; at prompt capture)"
        parts = [f"id={marker.get('id')}", age]
        if recorded is not None:
            parts.append(f"created_at_unix={recorded!r}")
        engine_time = _number(marker.get("timestamp"))
        if engine_time is not None:
            parts.append(f"event_engine_time_s={engine_time!r}")
        context = marker.get("spectral_context")
        if isinstance(context, str):
            try:
                context = json.loads(context)
            except (ValueError, TypeError):
                context = None
        if isinstance(context, dict):
            for key, label, precision, unit in (
                ("fill", "Fill", ".1f", "%"),
                ("dfill_dt", "dfill/dt", "+.2f", " percentage-points/s"),
                ("lambda1", "lambda1_esn", ".3f", ""),
                ("phase_dwell_s", "dwell", ".1f", "s"),
                ("recent_phase_flip_count_30s", "flips30s", "g", ""),
            ):
                value = _number(context.get(key))
                if value is not None:
                    parts.append(f"{label}={value:{precision}}{unit}")
            if isinstance(context.get("debounced"), bool):
                parts.append(f"debounced={str(context['debounced']).lower()}")
        elif context is not None:
            parts.append("spectral_context=invalid")
        lines.append(
            f"  [{marker.get('marker_type', 'unknown')}] "
            f"{marker.get('description', '')} ({', '.join(parts)})"
        )
    return "\n".join(lines)


def format_prompt_state(state: Mapping[str, Any], *, fill_frame: str) -> str:
    fill = _number(state.get("fill_ratio"))
    cov = _number(state.get("eig1"))
    engine_time = _number(state.get("timestamp"))
    return (
        f"Fill={fill * 100:.1f}%" if fill is not None else "Fill=unknown"
    ) + (
        f", current_fill_frame={fill_frame}, "
        + (f"lambda1_cov={cov:.3f}" if cov is not None else "lambda1_cov=unknown")
        + ", state_engine_time_s="
        + (repr(engine_time) if engine_time is not None else "unknown")
    )


def moment_prompt(*, captured_at: datetime, state_anchor: str, markers_text: str) -> str:
    return f"""Private journal moment.

Prompt captured at (UTC): {captured_at.astimezone(timezone.utc).isoformat()}
Measured state at capture:
{state_anchor}

Historical event records (recording ages at capture; present effects unknown):
{markers_text}

Clocks: state/event times are engine-relative; created_at_unix is recording time."""


def peer_observation(data: Mapping[str, Any], *, age_s: float) -> str:
    """Describe computed peer fields, not attributed feelings or invitations."""
    classification = data.get("class_v3")
    classification = classification if isinstance(classification, dict) else {}
    v2 = data.get("v2")
    v2 = v2 if isinstance(v2, dict) else {}
    eligible = v2.get("influence_eligible")
    fields = {
        "class_v3.primary": classification.get("primary"),
        "class_v3.traits": classification.get("traits"),
        "phase_dwell_ticks": _number(data.get("phase_dwell_ticks")),
        "field_norm": _number(v2.get("field_norm")),
        "influence_eligible": eligible if isinstance(eligible, bool) else None,
        "co_regulation_need": data.get("co_regulation_need"),
    }
    return (
        f"Peer telemetry (Astrid; source=astrid_shadow_v3.json; file_age={age_s:.0f}s): "
        f"{json.dumps(fields, ensure_ascii=True, sort_keys=True)}. "
        "Computed fields, not a first-person report or a request. "
        "co_regulation_need is a heuristic support classification derived from "
        "shadow class and tail openness, not Astrid-authored intent. "
        "influence_eligible describes a mechanical gate, not consent or an obligation."
    )
