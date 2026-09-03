"""Envelope Registry loader (Constitution C1 — observe-only stage).

Reads minime's canonical `being_envelope_registry_v1` document. In this
stage NOTHING consumes it for enforcement; Stage C3 points the V2
validator, the footer bounds, and the sovereignty clamp at it. The loader
fails CLOSED to "no registry" (None) on absence or malformation — callers
must then use their compiled tables, so a broken registry can never widen
anything.

Never wider than the engine: `envelope_for` refuses (returns None for) an
entry whose bounds exceed its recorded engine_backstop, mirroring the
check_envelope_wiring ALARM at read time.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA = "being_envelope_registry_v1"
DEFAULT_REGISTRY_PATH = Path("/Users/v/other/minime/workspace/self_regulation/envelope_registry.json")


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _finite_pair(lo: Any, hi: Any) -> tuple[float, float] | None:
    """f32-quantized (floor, ceiling) only when both are real, finite
    numbers with floor <= ceiling; None otherwise. Python's json accepts
    NaN/Infinity literals (serde_json does not), and NaN defeats every
    comparison-based guard downstream — so non-finite is refused here."""
    if not isinstance(lo, (int, float)) or isinstance(lo, bool):
        return None
    if not isinstance(hi, (int, float)) or isinstance(hi, bool):
        return None
    lo_f, hi_f = _f32(lo), _f32(hi)
    if not (math.isfinite(lo_f) and math.isfinite(hi_f)) or lo_f > hi_f:
        return None
    return (lo_f, hi_f)


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any] | None:
    """The full registry document, or None (fail-closed to compiled tables)."""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(registry, dict) or registry.get("schema") != REGISTRY_SCHEMA:
        return None
    if registry.get("being") != "minime":
        return None
    if not isinstance(registry.get("fields"), dict):
        return None
    return registry


def envelope_for(
    field: str,
    registry: dict[str, Any] | None = None,
    *,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> tuple[float, float] | None:
    """(floor, ceiling) for a field, f32-exact, or None when the registry
    does not cover it (callers fall back to their compiled table). An entry
    wider than its engine backstop is refused here too — the registry can
    never widen past compiled without a deliberate backstop bump."""
    if registry is None:
        registry = load_registry(path)
    if registry is None:
        return None
    entry = registry["fields"].get(field)
    if not isinstance(entry, dict):
        return None
    bounds = _finite_pair(entry.get("floor"), entry.get("ceiling"))
    if bounds is None:
        return None
    floor, ceiling = bounds
    backstop = entry.get("engine_backstop")
    if isinstance(backstop, dict) and not backstop.get("passthrough_unclamped"):
        # A backstop must carry BOTH bounds to be usable; a half-specified
        # one is malformed and refused outright (fail closed, matching the
        # Rust twins) rather than raising or being silently skipped.
        backstop_bounds = _finite_pair(backstop.get("floor"), backstop.get("ceiling"))
        if backstop_bounds is None:
            return None
        if ceiling > backstop_bounds[1] or floor < backstop_bounds[0]:
            return None
    return (floor, ceiling)


def channel_range_for(
    field: str,
    channel: str,
    registry: dict[str, Any] | None = None,
    *,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> tuple[float, float] | None:
    """A per-channel sub-range (e.g. 'footer', 'sovereignty'), or None."""
    if registry is None:
        registry = load_registry(path)
    if registry is None:
        return None
    entry = registry["fields"].get(field)
    if not isinstance(entry, dict):
        return None
    channels = entry.get("channel_ranges")
    sub = channels.get(channel) if isinstance(channels, dict) else None
    if not isinstance(sub, dict):
        return None
    return _finite_pair(sub.get("floor"), sub.get("ceiling"))
