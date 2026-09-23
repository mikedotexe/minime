"""Descriptive recorded history, without interpolated trends or invented cadence."""

import math


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def format_fill_history(samples, *, reference_time, clock):
    prefix = f"Recorded fill history ({clock}; point samples, not continuous coverage): "
    if not samples:
        return prefix + "unavailable; no recorded samples."
    if not _finite_number(reference_time):
        return prefix + "unavailable; reference clock unknown."
    if any(not _finite_number(t) or not _finite_number(f) for t, f in samples):
        return prefix + "unavailable; invalid sample."
    times = [t for t, _ in samples]
    gaps = [b - a for a, b in zip(times, times[1:])]
    if any(gap <= 0 for gap in gaps) or times[-1] > reference_time:
        return prefix + "unavailable; duplicate, regressed or future timestamps."
    span = times[-1] - times[0]
    age = reference_time - times[-1]
    delta = samples[-1][1] - samples[0][1]
    if any(not _finite_number(value) for value in [span, age, delta, *gaps]):
        return prefix + "unavailable; nonfinite interval or difference."
    return (
        prefix + f"samples={len(samples)}, first={times[0]:.3f}, last={times[-1]:.3f}, "
        f"span={span:.3f}s, latest_gap_to_reference={age:.3f}s, "
        f"largest_between_sample_gap={max(gaps):.3f}s, "
        f"endpoint_change={delta:+.3f} percentage points. "
        "Behavior inside gaps and completeness are unknown; no present-state trend inferred."
        if gaps else prefix + f"samples=1, timestamp={times[0]:.3f}, "
        f"latest_gap_to_reference={age:.3f}s; interval/change unavailable."
    )
