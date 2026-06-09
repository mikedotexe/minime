"""Journal lane classification and anti-rumination helpers for Minime.

The journal can carry reflective prose, compact operational summaries, and
machine contracts. These helpers keep those lanes explicit so prompt/retrieval
surfaces do not accidentally treat large machine payloads as reflective thought.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MACHINE_JSON_DENSITY_THRESHOLD = 0.12
MACHINE_JSON_SIZE_THRESHOLD = 1_500
OVERSIZED_OPERATIONAL_CHARS = 2_500
OPERATIONAL_DOMINANCE_THRESHOLD = 0.60
REPEAT_WINDOW_SECONDS = 30 * 60
REPEAT_WINDOW_COUNT = 3
REPEAT_RECENT_LIMIT = 12
REPEAT_RECENT_COUNT = 4
RECENT_SCAN_LIMIT = 20

REFLECTIVE_MODES = {
    "aspiration",
    "boredom",
    "daydream",
    "dialogue_live",
    "dialogue_live_longform",
    "drift",
    "drift_reflection",
    "initiate",
    "introspect",
    "journal",
    "mirror",
    "moment",
    "moment_capture",
    "notice",
    "reflection",
    "rest",
    "self",
    "self_study",
    "decompose",
    "spectral_decomposition",
    "whim",
}

NATIVE_REFLECTIVE_DIAGNOSTIC_MODES = {
    "decompose",
    "spectral_decomposition",
}

OPERATIONAL_MODES = {
    "action_preflight",
    "action_thread",
    "continued_reading",
    "experiment_bind",
    "research",
    "resonance_forecast",
    "shadow_field_autonomy",
    "web_page_read",
    "web_search",
}

MACHINE_MARKERS = (
    "conveyor_v1:\n",
    "research_budget_v1:\n",
    "\nJSON:\n",
    "\nJSON:\r\n",
    "\njson:\n",
    "\njson:\r\n",
)


def mode_from_path(path_or_name: str | Path, text: str = "") -> str:
    name = Path(path_or_name).name if path_or_name else ""
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith("Mode:"):
            return _slug(stripped.split(":", 1)[1].strip() or name)
        if stripped.startswith("===") and stripped.endswith("==="):
            return _slug(stripped.strip("= "))
    stem = Path(name).stem
    if stem.startswith("action_thread_"):
        return "action_thread"
    if stem.startswith("action_preflight_"):
        return "action_preflight"
    if stem.startswith("experiment_bind_"):
        return "experiment_bind"
    if "_" in stem:
        return _slug(stem.split("_", 1)[0])
    return _slug(stem or "unknown")


def classify_journal_entry(text: str, path_or_name: str | Path = "") -> dict[str, Any]:
    raw = text or ""
    mode = mode_from_path(path_or_name, raw)
    size_bytes = len(raw.encode("utf-8", errors="replace"))
    density = json_density(raw)
    signals: list[str] = []
    marker = explicit_machine_marker(raw)
    if marker:
        signals.append("explicit_machine_payload")
    if density >= MACHINE_JSON_DENSITY_THRESHOLD and size_bytes >= MACHINE_JSON_SIZE_THRESHOLD:
        signals.append("json_density_high")

    operational = mode in OPERATIONAL_MODES
    reflective = mode in REFLECTIVE_MODES
    if operational and len(raw) > OVERSIZED_OPERATIONAL_CHARS:
        signals.append("oversized_operational")
    if repeated_next_scaffold_signal(raw):
        signals.append("repeated_next_scaffold")

    repeat_key = repeat_key_for_text(raw, mode)
    if marker or "json_density_high" in signals:
        lane = "machine_detail"
        recommended = "move_to_actions_artifact"
    elif operational:
        lane = "operational"
        recommended = "compact_or_cooldown" if "oversized_operational" in signals else "allow_compact"
    elif reflective:
        lane = "reflective"
        recommended = "allow"
    else:
        lane = "reflective"
        recommended = "allow_conservative"

    return {
        "schema_version": SCHEMA_VERSION,
        "lane": lane,
        "native_lane": (
            "minime_reflective_diagnostic"
            if mode in NATIVE_REFLECTIVE_DIAGNOSTIC_MODES
            else None
        ),
        "mode": mode,
        "size_bytes": size_bytes,
        "json_density": round(density, 4),
        "repeat_key": repeat_key,
        "signals": signals,
        "recommended_action": recommended,
    }


def scan_journal_directory(
    journal_dir: Path,
    *,
    limit: int = RECENT_SCAN_LIMIT,
    now_s: float | None = None,
) -> dict[str, Any]:
    now_s = time.time() if now_s is None else now_s
    entries: list[dict[str, Any]] = []
    if journal_dir.is_dir():
        paths = sorted(
            (path for path in journal_dir.glob("*.txt") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in paths[: max(0, limit)]:
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            entry = classify_journal_entry(text, path)
            entry["path"] = str(path)
            entry["modified_at_unix_s"] = round(path.stat().st_mtime, 3)
            entries.append(entry)

    counts = Counter(str(entry.get("lane") or "unknown") for entry in entries)
    mode_counts = Counter(str(entry.get("mode") or "unknown") for entry in entries)
    repeat_counts = Counter(
        str(entry.get("repeat_key") or "")
        for entry in entries[:REPEAT_RECENT_LIMIT]
        if entry.get("repeat_key")
    )
    recent_repeat_keys = [
        {"repeat_key": key, "count": count}
        for key, count in sorted(repeat_counts.items())
        if count >= REPEAT_RECENT_COUNT
    ]

    window_repeat_counts = Counter(
        str(entry.get("repeat_key") or "")
        for entry in entries
        if entry.get("repeat_key")
        and now_s - float(entry.get("modified_at_unix_s") or 0.0) <= REPEAT_WINDOW_SECONDS
    )
    window_repeat_keys = [
        {"repeat_key": key, "count": count}
        for key, count in sorted(window_repeat_counts.items())
        if count >= REPEAT_WINDOW_COUNT
    ]

    total = len(entries)
    operational_count = counts.get("operational", 0) + counts.get("machine_detail", 0)
    operational_ratio = operational_count / total if total else 0.0
    signals: list[str] = []
    if counts.get("machine_detail", 0):
        signals.append("machine_detail_present")
    if recent_repeat_keys or window_repeat_keys:
        signals.append("repeated_loop_present")
    if total and operational_ratio > OPERATIONAL_DOMINANCE_THRESHOLD:
        signals.append("operational_dominance")

    status = "ok"
    if "machine_detail_present" in signals:
        status = "warning"
    elif signals:
        status = "notice"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "sample_size": total,
        "counts": {
            "reflective": counts.get("reflective", 0),
            "operational": counts.get("operational", 0),
            "machine_detail": counts.get("machine_detail", 0),
        },
        "mode_counts": dict(mode_counts),
        "operational_ratio": round(operational_ratio, 4),
        "recent_repeat_keys": recent_repeat_keys,
        "window_repeat_keys": window_repeat_keys,
        "signals": signals,
        "entries": entries,
    }


def compact_excerpt(text: str, *, max_chars: int = 1_000) -> str:
    classification = classify_journal_entry(text)
    if classification["lane"] == "machine_detail":
        marker = explicit_machine_marker(text)
        if marker and marker in text:
            text = text.split(marker, 1)[0].strip()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "JSON:" or line == "json:" or line == "conveyor_v1:":
            break
        if len(line) > 400 and json_density(line) >= MACHINE_JSON_DENSITY_THRESHOLD:
            continue
        lines.append(line)
        if len(" ".join(lines)) >= max_chars:
            break
    excerpt = " ".join(lines).strip()
    if len(excerpt) > max_chars:
        return excerpt[: max_chars - 3].rstrip() + "..."
    return excerpt


def conveyor_signature(readout: dict[str, Any]) -> str:
    def pick(key: str) -> Any:
        return readout.get(key)

    payload = {
        "experiment_id": pick("experiment_id"),
        "stage": pick("stage"),
        "mode": pick("mode"),
        "proposed_next": pick("proposed_next"),
        "conveyor_next": pick("conveyor_next"),
        "missing_requirements": pick("missing_requirements") or [],
        "apply_blocked_reason": pick("apply_blocked_reason"),
        "applied": bool(pick("applied")),
        "can_apply": bool(pick("can_apply")),
        "source_refs": pick("source_refs") or [],
    }
    return stable_hash(payload)


def research_budget_status_signature(status: dict[str, Any]) -> str:
    def pick(key: str) -> Any:
        return status.get(key)

    artifacts = pick("latest_artifact_refs") or pick("artifact_refs") or []
    if not isinstance(artifacts, list):
        artifacts = []
    payload = {
        "budget_id": pick("active_budget_id") or pick("budget_id") or pick("latest_budget_request_id"),
        "stage": pick("stage") or pick("status"),
        "scope": pick("scope"),
        "remaining_actions": pick("remaining_actions"),
        "max_actions": pick("max_actions"),
        "duplicate_blocked_target": pick("duplicate_blocked_target"),
        "latest_review_id": pick("latest_review_id"),
        "latest_review_outcome": pick("latest_review_outcome"),
        "next_safe_command": pick("next_safe_command") or pick("latest_review_next_safe_command"),
        "artifact_refs": artifacts[:12],
        "artifact_count": len(artifacts),
    }
    return stable_hash(payload)


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def json_density(text: str) -> float:
    if not text:
        return 0.0
    punctuation = sum(text.count(ch) for ch in '{}[]":,')
    return punctuation / max(1, len(text))


def explicit_machine_marker(text: str) -> str | None:
    for marker in MACHINE_MARKERS:
        if marker in text:
            return marker
    return None


def repeated_next_scaffold_signal(text: str) -> bool:
    bases = re.findall(r"(?im)^\s*(?:proposed\s+next|conveyor\s+next|current\s+next|suggested\s+next|next)\s*:\s*([A-Z_]{3,})\b", text)
    if len(bases) >= 3 and len(set(bases)) <= 1:
        return True
    all_bases = re.findall(r"\b(?:EXPERIMENT_ADVANCE|EXPERIMENT_CHARTER|THREAD_STATUS|ACTION_PREFLIGHT|EXPERIMENT_RESEARCH_BUDGET_ACCEPT|CONTINUITY_SESSION_CAPTURE)\b", text)
    return len(all_bases) >= 6 and len(set(all_bases)) <= 2


def repeat_key_for_text(text: str, mode: str | None = None) -> str | None:
    mode = mode or mode_from_path("", text)
    if "conveyor_v1:\n" in text:
        try:
            payload = json.loads(text.split("conveyor_v1:\n", 1)[1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return f"conveyor:{conveyor_signature(payload)}"
    if "research_budget_v1:\n" in text:
        try:
            payload = json.loads(text.split("research_budget_v1:\n", 1)[1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return f"research_budget:{research_budget_status_signature(payload)}"

    next_values = []
    for match in re.finditer(
        r"(?im)^\s*(?:proposed\s+next|conveyor\s+next|current\s+next|suggested\s+next|next)\s*:\s*(.+?)\s*$",
        text,
    ):
        next_values.append(_normalize_next(match.group(1)))
    if next_values:
        return f"{mode}:next:{stable_hash(next_values[:4])}"

    folded = _normalize_next(text)
    if folded:
        return f"{mode}:body:{stable_hash(folded[:500])}"
    return None


def _normalize_next(value: str) -> str:
    return " ".join(str(value or "").upper().split())


def _slug(value: str) -> str:
    value = value.strip().casefold().replace(" ", "_").replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "", value)
    return value or "unknown"
