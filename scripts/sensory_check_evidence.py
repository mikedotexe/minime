"""Read-only validation of sensory snapshot clocks and admission evidence."""
from __future__ import annotations

import math
from typing import Any


def nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def record_clock(
    record: dict[str, Any], kind: str, observed_at_ms: float, max_age_ms: float
) -> dict[str, Any]:
    if kind in {"spectral", "health"}:
        provenance = record.get("provenance")
        raw = provenance.get("wall_clock_unix_ms") if isinstance(provenance, dict) else None
        field = "provenance.wall_clock_unix_ms"
    else:
        field = "updated_at_ms" if kind == "sensory" else "ts_ms"
        raw = record.get(field)
    timestamp = nonnegative_number(raw)
    age = observed_at_ms - timestamp if timestamp is not None and timestamp > 0 else None
    state = (
        "missing" if not record else
        "unknown" if age is None else
        "future" if age < 0 else
        "stale" if age > max_age_ms else "current"
    )
    return {"state": state, "age_ms": age, "field": field, "max_age_ms": max_age_ms}


def intake_state(budget: dict[str, Any], lane: str) -> dict[str, Any]:
    raw_divisor = budget.get(f"live_{lane}_divisor")
    divisor = nonnegative_number(raw_divisor)
    if divisor is not None and (not divisor.is_integer() or divisor > 2**32 - 1):
        divisor = None
    raw_fraction = budget.get("admit_fraction")
    fraction = nonnegative_number(raw_fraction)
    if fraction is not None and fraction > 1:
        fraction = None
    raw_enabled = budget.get(f"live_{lane}_enabled")
    enabled = raw_enabled if isinstance(raw_enabled, bool) else None
    missing = raw_divisor is None or raw_fraction is None or enabled is None
    invalid = (raw_enabled is not None and enabled is None) or (raw_divisor is not None and divisor is None) or (
        raw_fraction is not None and fraction is None
    )
    state = (
        "invalid" if invalid else
        "disabled" if enabled is False or divisor == 0 else
        "zero_probability" if fraction == 0 else
        "unknown" if missing else "enabled"
    )
    return {
        "state": state,
        "divisor": int(divisor) if divisor is not None else None,
        "enabled": enabled,
        "admit_fraction": fraction,
        "reason": budget.get("live_intake_reason"),
    }
