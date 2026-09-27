"""Recorded-event selection and units; no interpretation or control authority."""

import json
import math
import re


# A scheduling window, not a physiological or retention threshold. Longer-lived
# records stay in the database for explicit historical inspection.
AUTOMATIC_MOMENT_MAX_AGE_S = 15 * 60


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def select_recent_markers(connection, session_id, *, recorded_now, engine_now):
    """Read up to three unconsumed records recent in both independent clocks.

    Unknown/future clocks and old records are left untouched. Engine time is
    scoped to the selected session; recording time alone cannot make a delayed
    insertion of an old engine event current.
    """
    recorded_now, engine_now = finite_number(recorded_now), finite_number(engine_now)
    if recorded_now is None or recorded_now <= 0 or engine_now is None or engine_now < 0:
        return []
    columns = {row[1] for row in connection.execute("PRAGMA table_info(moment_markers)")}
    if "created_at_unix" not in columns:
        return []
    rows = connection.execute(
        """SELECT id, marker_type, description, spectral_context, timestamp, created_at_unix
           FROM moment_markers
           WHERE session_id = ? AND consumed = 0
             AND typeof(created_at_unix) IN ('integer', 'real')
             AND created_at_unix > 0 AND created_at_unix BETWEEN ? AND ?
             AND typeof(timestamp) IN ('integer', 'real')
             AND timestamp >= 0 AND timestamp BETWEEN ? AND ?
           ORDER BY created_at_unix DESC, timestamp DESC, id DESC LIMIT 3""",
        (session_id, recorded_now - AUTOMATIC_MOMENT_MAX_AGE_S, recorded_now,
         engine_now - AUTOMATIC_MOMENT_MAX_AGE_S, engine_now),
    ).fetchall()
    keys = ("id", "marker_type", "description", "spectral_context", "timestamp", "created_at_unix")
    return [dict(zip(keys, row)) for row in rows]


def selection_note():
    return (f"Automatic event selection: this session only, at most 3 unconsumed records within "
            f"{AUTOMATIC_MOMENT_MAX_AGE_S}s in both recording and engine clocks at capture. "
            "Older or clock-unknown records remain stored; this selection is not a complete history.")


_CROSSING = re.compile(
    r"Fill crossed (?:above|below) target \(([+-]?\d+(?:\.\d+)?)% -> ([+-]?\d+(?:\.\d+)?)%\)"
)
_SPIKE = re.compile(r"Large dfill/dt spike: ([+-]?\d+(?:\.\d+)?)%/s")


def marker_measurements(marker_type, description, context):
    """Expose legacy recorded endpoint precision without deriving change from rate."""
    description = str(description or "")
    parts = []
    if marker_type == "spectral_spike" and (match := _SPIKE.fullmatch(description)):
        description = f"Large dfill/dt spike: {match[1]} percentage-points/s"
    crossing = _CROSSING.fullmatch(description) if marker_type == "fill_crossing" else None
    endpoint_available = False
    if crossing:
        before, after = (float(value) for value in crossing.groups())
        if all(math.isfinite(value) and 0 <= value <= 100 for value in (before, after)):
            parts.append(f"reported_fill_from={before:g}%, reported_fill_to={after:g}%, "
                         f"endpoint_change={after - before:+.3f} percentage points "
                         "(calculated from rounded recorded description)")
            endpoint_available = True
    rate = finite_number(context.get("dfill_dt")) if isinstance(context, dict) else None
    if rate is not None or marker_type == "spectral_spike":
        if not endpoint_available:
            parts.append("endpoint_change=unavailable (two recorded endpoints are required)")
        parts.append("event_interval_s=unavailable; a rate is not a total fill change")
    return description, parts


def pressure_classifier_context(pressure):
    """Describe the supplied classifier separately from memory/context capacity."""
    if not isinstance(pressure, dict) or not pressure.get("quality"):
        return ""
    fields = {"label": str(pressure["quality"])}
    for name in ("pressure_score", "porosity_score"):
        if (value := finite_number(pressure.get(name))) is not None:
            fields[name] = value
    if pressure.get("dominant_source"):
        fields["dominant_source"] = str(pressure["dominant_source"])
    components = pressure.get("components")
    if isinstance(components, dict) and (value := finite_number(components.get("mode_packing"))) is not None:
        fields["mode_packing"] = value
    definition = (" In pressure_source_v1, overpacked_mode_packing is selected when mode_packing "
                  "is the dominant component and at least 0.55, after the divergence check."
                  if fields["label"] == "overpacked_mode_packing" else "")
    return ("Pressure classifier context (supplied snapshot; advisory): "
            + json.dumps(fields, ensure_ascii=False, sort_keys=True) + "." + definition
            + " These scores do not measure language-model context occupancy or hardware memory capacity.")
