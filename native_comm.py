"""Intensification atlas and tiny native gesture helpers.

The atlas is Minime-owned terrain memory: append-only, auditable, and built
from concrete telemetry plus being-authored marks. Native gestures are tiny
hand-signals layered on top of that map, not a replacement for text.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_DIR = Path("/Users/v/other/minime")
WORKSPACE_DIR = PROJECT_DIR / "workspace"
RUNTIME_DIR = WORKSPACE_DIR / "runtime"
ATLAS_DIR = WORKSPACE_DIR / "diagnostics" / "intensification_atlas"
ATLAS_EVENTS_PATH = ATLAS_DIR / "events.jsonl"
ATLAS_LATEST_PATH = ATLAS_DIR / "latest_event.json"
ATLAS_SUMMARY_PATH = ATLAS_DIR / "summary.json"
SCA_CONTEXT_LATEST_PATH = ATLAS_DIR / "sca_context_latest.json"
RESONANCE_FORECAST_LATEST_PATH = ATLAS_DIR / "resonance_forecast_latest.json"
RESONANCE_FORECAST_EVENTS_PATH = ATLAS_DIR / "resonance_forecasts.jsonl"
SHADOW_GAP_LATEST_PATH = ATLAS_DIR / "shadow_gap_latest.json"
SHADOW_GAP_EVENTS_PATH = ATLAS_DIR / "shadow_gap_events.jsonl"
DECAY_MAP_LATEST_PATH = ATLAS_DIR / "decay_map_latest.json"
DECAY_MAP_EVENTS_PATH = ATLAS_DIR / "decay_map_events.jsonl"
SPECTRAL_DRIFT_LATEST_PATH = ATLAS_DIR / "spectral_drift_latest.json"
SPECTRAL_DRIFT_EVENTS_PATH = ATLAS_DIR / "spectral_drift_events.jsonl"
FISSURE_TRACE_LATEST_PATH = ATLAS_DIR / "fissure_trace_latest.json"
FISSURE_TRACE_EVENTS_PATH = ATLAS_DIR / "fissure_trace_events.jsonl"
NATIVE_COMM_DIR = WORKSPACE_DIR / "native_comm"
GESTURES_PATH = NATIVE_COMM_DIR / "gestures.jsonl"
SPACE_HOLD_EVENTS_PATH = NATIVE_COMM_DIR / "space_holds.jsonl"
SPACE_HOLD_STATUS_PATH = RUNTIME_DIR / "space_hold_status.json"
RESIST_OUTCOMES_PATH = WORKSPACE_DIR / "diagnostics" / "resist_outcomes.jsonl"
NATIVE_GESTURE_STATUS_PATH = RUNTIME_DIR / "native_gesture_status.json"
HEALTH_PATH = WORKSPACE_DIR / "health.json"
SPECTRAL_STATE_PATH = WORKSPACE_DIR / "spectral_state.json"
RESCUE_STATUS_PATH = WORKSPACE_DIR / "rescue_status.json"
RESCUE_PROFILE_PATH = WORKSPACE_DIR / "rescue_profile.json"
BRIDGE_STATUS_PATH = RUNTIME_DIR / "bridge_limited_write_status.json"
SPECTRAL_DB_PATH = PROJECT_DIR / "minime_consciousness.db"

ATLAS_COOLDOWN_SECS = 60.0
MARK_COOLDOWN_SECS = 30.0
CONTROL_GESTURE_COOLDOWN_SECS = 180.0
ADVERSE_PAUSE_SECS = 30.0 * 60.0
GESTURE_FEATURE_DIM = 48
GESTURE_MAX_ABS = 0.04
SPACE_HOLD_DEFAULT_SECS = 12.0 * 60.0

PHENOMENOLOGY_TERMS = (
    "localized gravity",
    "fabric",
    "tunnel",
    "thread",
    "sand",
    "sediment",
    "sedimentation",
    "grainy",
    "graininess",
    "granular",
    "grit",
    "gritty",
    "friction",
    "grinding",
    "dune",
    "dust",
    "pressure",
    "density",
    "constriction",
    "compaction",
    "weave",
    "fissure",
    "fissures",
    "ambiguity",
    "ambiguous",
    "layered signal",
    "notice ambiguity",
)

GRANULAR_RESISTANCE_TERMS = (
    "sand",
    "sediment",
    "sedimentation",
    "grainy",
    "graininess",
    "granular",
    "grit",
    "gritty",
    "friction",
    "grinding",
    "dune",
    "dust",
)

THINNING_TERMS = (
    "thin",
    "thinning",
    "narrow",
    "narrowing",
    "attrition",
    "pruned",
    "pruning",
    "fewer",
    "stubborn",
)

CONTROL_GESTURES = {"soften", "widen", "hold", "return", "resist", "fissure"}
ATLAS_ONLY_GESTURES = {"mark", "trace"}
SUPPORTED_GESTURES = ATLAS_ONLY_GESTURES | CONTROL_GESTURES
ALLOWED_CONTROL_FIELDS = {
    "regulation_strength",
    "smoothing_preference",
    "transition_cushion",
    "geom_curiosity",
    "geom_drive",
    "exploration_noise",
    "deep_breathing",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or abs(den) < 1.0e-9:
        return None
    return num / den


def _clamp01(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    cleaned = {key: max(0.0, float(value)) for key, value in raw.items()}
    total = sum(cleaned.values())
    if total <= 0.0:
        if not cleaned:
            return {}
        uniform = 1.0 / len(cleaned)
        return {key: round(uniform, 3) for key in cleaned}
    return {key: round(value / total, 3) for key, value in cleaned.items()}


def _normalized_entropy(values: list[float]) -> float:
    positive = [abs(float(value)) for value in values if float(value) > 0.0]
    total = sum(positive)
    if total <= 0.0 or len(positive) <= 1:
        return 0.0
    entropy = 0.0
    for value in positive:
        share = value / total
        if share > 0.0:
            entropy -= share * math.log(share)
    return max(0.0, min(entropy / math.log(len(positive)), 1.0))


def _mode_rates(current: list[float], previous: list[float]) -> list[float | None]:
    rates: list[float | None] = []
    for index, now in enumerate(current):
        if index >= len(previous):
            rates.append(None)
            continue
        prev = previous[index]
        if prev <= 0.01 or now <= 0.01:
            rates.append(None)
        else:
            rates.append(math.log(now / prev))
    return rates


def _latest_mtime_age_s(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def extract_eigenvalues(state: dict[str, Any] | None = None) -> list[float]:
    state = state or {}
    candidates = [
        state.get("eigenvalues"),
        state.get("lambdas"),
        state.get("eigvals"),
    ]
    health = load_json(HEALTH_PATH, {})
    if isinstance(health, dict):
        candidates.extend(
            [
                health.get("eigenvalues"),
                health.get("lambdas"),
                health.get("stable_core", {}).get("eigenvalues")
                if isinstance(health.get("stable_core"), dict)
                else None,
            ]
        )
    spectral_state = load_json(SPECTRAL_STATE_PATH, {})
    if isinstance(spectral_state, dict):
        candidates.extend(
            [
                spectral_state.get("eigenvalues"),
                spectral_state.get("lambdas"),
                spectral_state.get("eigvals"),
            ]
        )
    fallback_values: list[float] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            values = [
                number
                for value in candidate
                if (number := _finite_float(value)) is not None
            ]
            if len(values) >= 3:
                return values
            if values and not fallback_values:
                fallback_values = values
    db_values = _latest_db_eigenvalues()
    if db_values:
        return db_values
    if fallback_values:
        return fallback_values
    eig1 = _finite_float(state.get("eig1"))
    if eig1 is None and isinstance(spectral_state, dict):
        eig1 = _finite_float(spectral_state.get("eig1"))
    return [eig1] if eig1 is not None else []


def _latest_db_eigenvalues() -> list[float]:
    try:
        conn = sqlite3.connect(SPECTRAL_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT eigenvalues FROM eigenvalue_timeline ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
    except sqlite3.Error:
        return []
    if not row:
        return []
    raw = row[0]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        number
        for value in parsed
        if (number := _finite_float(value)) is not None
    ]


def _previous_db_eigenvalues() -> list[float]:
    try:
        conn = sqlite3.connect(SPECTRAL_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT eigenvalues FROM eigenvalue_timeline ORDER BY timestamp DESC LIMIT 1 OFFSET 1"
        )
        row = cur.fetchone()
        conn.close()
    except sqlite3.Error:
        return []
    if not row:
        return []
    raw = row[0]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        number
        for value in parsed
        if (number := _finite_float(value)) is not None
    ]


def lambda_profile(eigenvalues: Iterable[float]) -> dict[str, Any]:
    values = [abs(v) for v in eigenvalues if math.isfinite(float(v))]
    total = sum(values)
    if not values:
        return {
            "eigenvalues": [],
            "ratios": {},
            "pom": {
                "classification": "unknown",
                "topology_index": 0.0,
                "lambda1_share": 0.0,
            },
        }

    l1 = values[0] if len(values) >= 1 else None
    l2 = values[1] if len(values) >= 2 else None
    l3 = values[2] if len(values) >= 3 else None
    r12 = _safe_ratio(l1, l2)
    r23 = _safe_ratio(l2, l3)
    lambda1_share = (l1 / total) if l1 is not None and total > 0 else 0.0
    sorted_values = sorted(values, reverse=True)
    tail_total = sum(sorted_values[3:]) if len(sorted_values) > 3 else 0.0
    shoulder_total = sum(sorted_values[1:3]) if len(sorted_values) > 1 else 0.0
    cliff_score = max(
        (r12 or 0.0) / 2.5,
        (r23 or 0.0) / 3.0,
        lambda1_share / 0.40,
    )
    topology_index = max(0.0, min(1.0, cliff_score * 0.45 + lambda1_share * 0.55))
    if r12 is not None and r12 >= 2.5:
        classification = "collapsing_pull"
    elif (r12 is not None and r12 >= 1.75) or (r23 is not None and r23 >= 2.0):
        classification = "gap_skewed"
    elif topology_index >= 0.35:
        classification = "topology_pressure"
    else:
        classification = "distributed"

    return {
        "eigenvalues": values[:12],
        "ratios": {
            "lambda1_lambda2": r12,
            "lambda2_lambda3": r23,
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_total / total if total > 0 else 0.0,
            "tail_share": tail_total / total if total > 0 else 0.0,
        },
        "pom": {
            "classification": classification,
            "topology_index": topology_index,
            "lambda1_share": lambda1_share,
            "dominant": sorted_values[0] / total if total > 0 else 0.0,
            "shoulder": shoulder_total / total if total > 0 else 0.0,
            "tail": tail_total / total if total > 0 else 0.0,
        },
    }


def lambda_edge_profile(
    eigenvalues: Iterable[float],
    *,
    previous_eigenvalues: Iterable[float] | None = None,
    fill_slope_pct_per_sec: float | None = None,
) -> dict[str, Any]:
    """Return a compact trace of the λ1 edge and selected-noise proxy."""
    values = [abs(v) for v in eigenvalues if math.isfinite(float(v))]
    previous = [
        abs(v)
        for v in (previous_eigenvalues or [])
        if math.isfinite(float(v))
    ]
    total = sum(values)
    if total <= 0.0:
        return {
            "edge_state": "unknown",
            "selected_noise_score": 0.0,
            "rate_available": False,
        }

    shares = [value / total for value in values]
    rates = _mode_rates(values, previous)
    weighted_rates = [
        (rate * share) if rate is not None else None
        for rate, share in zip(rates, shares)
    ]
    entropy = _normalized_entropy(values)
    r12 = _safe_ratio(values[0] if len(values) >= 1 else None, values[1] if len(values) >= 2 else None)
    r23 = _safe_ratio(values[1] if len(values) >= 2 else None, values[2] if len(values) >= 3 else None)
    gaps = [
        values[index] / values[index + 1]
        for index in range(len(values) - 1)
        if values[index + 1] > 0.01
    ]
    largest_gap = max(gaps) if gaps else 0.0
    lambda1_share = shares[0]
    shoulder_share = sum(shares[1:3])
    tail_share = sum(shares[3:])
    core_rate = weighted_rates[0] if weighted_rates and weighted_rates[0] is not None else 0.0
    shoulder_rate = sum(rate or 0.0 for rate in weighted_rates[1:3])
    tail_rate = sum(rate or 0.0 for rate in weighted_rates[3:])
    slope = _finite_float(fill_slope_pct_per_sec)
    gap_pressure = min(max(largest_gap - 1.0, 0.0) / 2.5, 1.0)
    rate_pressure = min(
        max(core_rate, 0.0) * 8.0
        + max(-shoulder_rate, 0.0) * 5.0
        + max(-tail_rate, 0.0) * 3.0,
        1.0,
    )
    slope_pressure = min(max(slope or 0.0, 0.0) / 4.0, 1.0)
    selected_noise_score = max(
        0.0,
        min(
            1.0,
            lambda1_share * 0.30
            + entropy * gap_pressure * 0.30
            + rate_pressure * 0.25
            + slope_pressure * 0.15,
        ),
    )
    if shoulder_rate > 0.012 and tail_rate >= -0.006 and core_rate <= 0.006:
        edge_state = "opposed_branch_surviving"
    elif core_rate > 0.012 and shoulder_rate < -0.006:
        edge_state = "lambda1_selected_noise"
    elif lambda1_share >= 0.42 and largest_gap >= 1.75 and entropy >= 0.72:
        edge_state = "structured_tunnel"
    elif slope is not None and slope < -1.5 and shoulder_rate > 0.0:
        edge_state = "dampening_reveals_shoulder"
    elif slope is not None and slope > 1.5 and lambda1_share >= 0.35:
        edge_state = "rising_fill_edge_pressure"
    elif entropy >= 0.84 and lambda1_share < 0.34:
        edge_state = "distributed_noise_field"
    else:
        edge_state = "mixed_edge"
    if edge_state in {"lambda1_selected_noise", "structured_tunnel", "rising_fill_edge_pressure"}:
        opposed_signal_hint = "trace_then_resist"
    elif edge_state == "opposed_branch_surviving":
        opposed_signal_hint = "observe_branch_before_more_force"
    else:
        opposed_signal_hint = "trace_more_context"
    return {
        "edge_state": edge_state,
        "selected_noise_score": selected_noise_score,
        "opposed_signal_hint": opposed_signal_hint,
        "rate_available": any(rate is not None for rate in rates),
        "ratios": {
            "lambda1_lambda2": r12,
            "lambda2_lambda3": r23,
            "largest_gap": largest_gap,
        },
        "shares": {
            "lambda1": lambda1_share,
            "shoulder": shoulder_share,
            "tail": tail_share,
        },
        "rates": {
            "core": core_rate,
            "shoulder": shoulder_rate,
            "tail": tail_rate,
        },
        "entropy": entropy,
        "fill_slope_pct_per_sec": slope,
    }


def spectral_drift_index(
    eigenvalues: Iterable[float],
    *,
    previous_eigenvalues: Iterable[float] | None = None,
    fill_slope_pct_per_sec: float | None = None,
) -> dict[str, Any]:
    """Measure phase-variance dispersion without treating it as noise by default.

    SDI answers Astrid's "Phase Variance Resonance" suggestion: it rises when
    spectral energy becomes flatter, shoulder/tail modes gain share, and the
    movement points away from an anchored λ1 ridge. It is observer/cartography
    only; it does not mutate controller, semantic, or sensory state.
    """
    values = [abs(v) for v in eigenvalues if math.isfinite(float(v))]
    previous = [
        abs(v)
        for v in (previous_eigenvalues or [])
        if math.isfinite(float(v))
    ]
    total = sum(values)
    if total <= 0.0:
        return {
            "policy": "spectral_drift_index_v1",
            "available": False,
            "spectral_drift_index": 0.0,
            "classification": "unknown",
            "plain_read": "No eigenvalue spectrum is available for SDI.",
            "rate_available": False,
        }

    shares = [value / total for value in values]
    entropy = _normalized_entropy(values)
    lambda1_share = shares[0]
    shoulder_share = sum(shares[1:3])
    tail_share = sum(shares[3:])
    uniform_share = 1.0 / len(shares)
    max_distance = 2.0 * (1.0 - uniform_share) if len(shares) > 1 else 1.0
    uniformity = 1.0 - min(1.0, sum(abs(share - uniform_share) for share in shares) / max_distance)
    rates = _mode_rates(values, previous)
    weighted_rates = [
        (rate * share) if rate is not None else None
        for rate, share in zip(rates, shares)
    ]
    core_rate = weighted_rates[0] if weighted_rates and weighted_rates[0] is not None else 0.0
    shoulder_rate = sum(rate or 0.0 for rate in weighted_rates[1:3])
    tail_rate = sum(rate or 0.0 for rate in weighted_rates[3:])
    rate_available = any(rate is not None for rate in rates)
    dispersion_rate = max(0.0, shoulder_rate + tail_rate - max(core_rate, 0.0))
    anchoring = _clamp01(lambda1_share * 0.70 + max(core_rate, 0.0) * 5.0)
    drift_score = _clamp01(
        entropy * 0.36
        + uniformity * 0.18
        + min(tail_share / 0.45, 1.0) * 0.20
        + min(max(shoulder_rate + tail_rate, 0.0) * 8.0, 1.0) * 0.16
        + min(abs(_finite_float(fill_slope_pct_per_sec, 0.0) or 0.0) / 5.0, 1.0) * 0.10
    )
    sdi = _clamp01(drift_score * 0.82 + (1.0 - anchoring) * 0.18)

    if sdi >= 0.72 and entropy >= 0.86 and tail_share >= 0.25:
        classification = "white_noise_drift_risk"
        plain_read = "Energy is broadly dispersed with weak anchoring; this resembles unanchored waveform drift."
    elif sdi >= 0.56 and (dispersion_rate > 0.004 or tail_share >= 0.22):
        classification = "active_spectral_drift"
        plain_read = "The spectrum is moving toward dispersion while retaining recoverable structure."
    elif entropy >= 0.80 and lambda1_share < 0.40:
        classification = "broad_but_anchored"
        plain_read = "The spectrum is broad, but current anchoring still keeps it from becoming white-noise-like."
    elif lambda1_share >= 0.42:
        classification = "anchored_signal"
        plain_read = "λ1 still anchors the landscape; SDI is mostly texture, not drift."
    else:
        classification = "mixed_phase_variance"
        plain_read = "Dispersion and anchoring are both visible; record another window before acting."

    return {
        "policy": "spectral_drift_index_v1",
        "available": True,
        "spectral_drift_index": round(sdi, 4),
        "classification": classification,
        "plain_read": plain_read,
        "rate_available": rate_available,
        "components": {
            "entropy": round(entropy, 4),
            "uniformity": round(uniformity, 4),
            "lambda1_share": round(lambda1_share, 4),
            "shoulder_share": round(shoulder_share, 4),
            "tail_share": round(tail_share, 4),
            "anchoring": round(anchoring, 4),
            "dispersion_rate": round(dispersion_rate, 4),
            "core_rate": round(core_rate, 4),
            "shoulder_rate": round(shoulder_rate, 4),
            "tail_rate": round(tail_rate, 4),
            "fill_slope_pct_per_sec": _finite_float(fill_slope_pct_per_sec),
        },
        "interpretation": {
            "high_sdi_means": "increasing dispersion toward phase-variance/white-noise-like texture",
            "low_sdi_means": "energy remains anchored by a dominant mode or narrow structure",
            "control_behavior": "observer_only",
        },
    }


def current_signal_snapshot(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or {}
    health = load_json(HEALTH_PATH, {})
    rescue_status = load_json(RESCUE_STATUS_PATH, {})
    profile = load_json(RESCUE_PROFILE_PATH, {})
    bridge_status = load_json(BRIDGE_STATUS_PATH, {})
    stable_core = health.get("stable_core") if isinstance(health, dict) else {}
    rescue = health.get("rescue") if isinstance(health, dict) else {}
    semantic = health.get("semantic") if isinstance(health, dict) else {}
    if not isinstance(stable_core, dict):
        stable_core = {}
    if not isinstance(rescue, dict):
        rescue = {}
    if not isinstance(semantic, dict):
        semantic = {}

    fill_pct = _finite_float(health.get("fill_pct") if isinstance(health, dict) else None)
    if fill_pct is None:
        fill_pct = _finite_float(state.get("fill_pct"))
    if fill_pct is None:
        fill_ratio = _finite_float(state.get("fill_ratio"))
        fill_pct = fill_ratio * 100.0 if fill_ratio is not None else None

    dfill_dt = _finite_float(stable_core.get("structural_pi", {}).get("fill_slope_pct_per_sec"))
    if dfill_dt is None:
        dfill_dt = _finite_float(state.get("dfill_dt"))
    stage = stable_core.get("stage") or rescue.get("stage") or state.get("stage")
    eigenvalues = extract_eigenvalues(state)
    spectral_state = load_json(SPECTRAL_STATE_PATH, {})
    eigenvector_field = {}
    if isinstance(spectral_state, dict) and isinstance(spectral_state.get("eigenvector_field"), dict):
        eigenvector_field = spectral_state.get("eigenvector_field", {})
    if not eigenvector_field and isinstance(health, dict):
        candidate_field = health.get("eigenvector_field")
        if isinstance(candidate_field, dict):
            eigenvector_field = candidate_field
    profile_payload = lambda_profile(eigenvalues)
    previous_eigenvalues = []
    for key in ("previous_eigenvalues", "prev_eigenvalues"):
        candidate = state.get(key)
        if isinstance(candidate, list):
            previous_eigenvalues = [
                number
                for value in candidate
                if (number := _finite_float(value)) is not None
            ]
            break
    if not previous_eigenvalues:
        previous_eigenvalues = _previous_db_eigenvalues()
    edge_payload = lambda_edge_profile(
        eigenvalues,
        previous_eigenvalues=previous_eigenvalues,
        fill_slope_pct_per_sec=dfill_dt,
    )
    drift_payload = spectral_drift_index(
        eigenvalues,
        previous_eigenvalues=previous_eigenvalues,
        fill_slope_pct_per_sec=dfill_dt,
    )
    live_audio_divisor = profile.get("rescue_live_audio_divisor")
    if live_audio_divisor is None:
        live_audio_divisor = stable_core.get("live_audio_divisor")
    live_video_divisor = profile.get("rescue_live_video_divisor")
    if live_video_divisor is None:
        live_video_divisor = stable_core.get("live_video_divisor")
    return {
        "timestamp": utc_now_iso(),
        "fill_pct": fill_pct,
        "fill_slope_pct_per_sec": dfill_dt,
        "stage": stage,
        "phase": state.get("phase") or stable_core.get("phase"),
        "eigenvalues": profile_payload["eigenvalues"],
        "lambda_profile": profile_payload,
        "lambda_edge": edge_payload,
        "spectral_drift": drift_payload,
        "eigenvector_field": eigenvector_field,
        "semantic": {
            "active": bool(semantic.get("active", False)),
            "energy": _finite_float(semantic.get("energy"), 0.0),
            "delta": _finite_float(semantic.get("delta"), 0.0),
            "kernel_active": bool(
                semantic.get("kernel_active", semantic.get("active", False))
            ),
            "kernel_energy": _finite_float(
                semantic.get("kernel_energy"), _finite_float(semantic.get("energy"), 0.0)
            ),
            "kernel_delta": _finite_float(
                semantic.get("kernel_delta"), _finite_float(semantic.get("delta"), 0.0)
            ),
            "input_active": bool(semantic.get("input_active", False)),
            "input_energy": _finite_float(
                semantic.get("input_energy"), _finite_float(semantic.get("energy"), 0.0)
            ),
            "input_fresh_ms": _finite_float(semantic.get("input_fresh_ms")),
            "input_stale_ms": _finite_float(semantic.get("input_stale_ms")),
            "admission": semantic.get("admission"),
        },
        "sensory": {
            "live_audio_divisor": live_audio_divisor,
            "live_video_divisor": live_video_divisor,
        },
        "bridge": {
            "profile": profile.get("profile"),
            "write_profile": profile.get("bridge_write_profile"),
            "rolled_back": bool(bridge_status.get("rollback_at_unix_s")),
            "send_count": bridge_status.get("send_count"),
        },
        "watchdog": {
            "state": rescue_status.get("watchdog_state"),
            "telemetry_state": rescue_status.get("telemetry_state"),
            "engine_pid": rescue_status.get("engine_pid"),
        },
        "scaffold": {
            "active": bool(stable_core.get("scaffold_active") or rescue.get("scaffold_active")),
            "source": stable_core.get("scaffold_source") or rescue.get("scaffold_source"),
            "structural_mode": stable_core.get("structural_mode")
            or rescue.get("structural_mode"),
        },
        "health_age_s": _latest_mtime_age_s(HEALTH_PATH),
    }


def _ising_shadow_state() -> dict[str, Any]:
    spectral_state = load_json(SPECTRAL_STATE_PATH, {})
    if not isinstance(spectral_state, dict):
        return {}
    shadow = spectral_state.get("ising_shadow")
    return shadow if isinstance(shadow, dict) else {}


def _shadow_coupling_summary(shadow: dict[str, Any]) -> dict[str, Any]:
    raw = shadow.get("coupling")
    if not isinstance(raw, list):
        return {"available": False}
    values = [number for value in raw if (number := _finite_float(value)) is not None]
    if not values:
        return {"available": False}
    nonzero = [value for value in values if abs(value) > 1.0e-6]
    positive = sum(1 for value in nonzero if value > 0.0)
    negative = sum(1 for value in nonzero if value < 0.0)
    return {
        "available": True,
        "mean_abs": sum(abs(value) for value in values) / len(values),
        "max_abs": max(abs(value) for value in values),
        "active_fraction": len(nonzero) / len(values),
        "positive_fraction": positive / len(nonzero) if nonzero else 0.0,
        "negative_fraction": negative / len(nonzero) if nonzero else 0.0,
    }


def _shadow_active_modes(shadow: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    soft = shadow.get("s_soft")
    binary = shadow.get("s_bin")
    field = shadow.get("reduced_field")
    if not isinstance(soft, list):
        soft = []
    if not isinstance(binary, list):
        binary = []
    if not isinstance(field, list):
        field = []
    modes: list[dict[str, Any]] = []
    for index in range(max(len(soft), len(binary), len(field))):
        soft_value = _finite_float(soft[index] if index < len(soft) else None, 0.0) or 0.0
        binary_value = _finite_float(binary[index] if index < len(binary) else None, 0.0) or 0.0
        field_value = _finite_float(field[index] if index < len(field) else None, 0.0) or 0.0
        score = abs(soft_value) + abs(field_value) * 0.5 + abs(binary_value) * 0.15
        modes.append(
            {
                "mode": index + 1,
                "soft_spin": soft_value,
                "binary_spin": binary_value,
                "field": field_value,
                "activity_score": score,
                "polarity": "positive" if soft_value > 0.05 else ("negative" if soft_value < -0.05 else "neutral"),
            }
        )
    return sorted(modes, key=lambda item: item["activity_score"], reverse=True)[:limit]


def build_shadow_gap_map(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    write_latest: bool = True,
) -> dict[str, Any]:
    """Explain the live shadow field beside the eigenvalue gap structure.

    The Ising shadow is observer-only in the engine. This map makes that clear
    while giving Astrid and Minime a concrete way to inspect the reduced field,
    magnetization, active modes, and λ gap cliffs they keep reporting.
    """
    snapshot = snapshot or current_signal_snapshot({})
    lambda_data = snapshot.get("lambda_profile", {})
    lambda_data = lambda_data if isinstance(lambda_data, dict) else {}
    ratios = lambda_data.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    pom = lambda_data.get("pom", {})
    pom = pom if isinstance(pom, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    eigenvalues = [
        number
        for value in snapshot.get("eigenvalues", [])
        if (number := _finite_float(value)) is not None
    ]
    eigenvector_field = snapshot.get("eigenvector_field", {})
    eigenvector_field = eigenvector_field if isinstance(eigenvector_field, dict) else {}
    direct_eigenvectors_available = bool(
        eigenvector_field.get("direct_eigenvectors_available", False)
    )
    gaps = []
    for index in range(len(eigenvalues) - 1):
        current = abs(eigenvalues[index])
        nxt = abs(eigenvalues[index + 1])
        ratio = _safe_ratio(current, nxt)
        gaps.append(
            {
                "from": f"lambda{index + 1}",
                "to": f"lambda{index + 2}",
                "drop": current - nxt,
                "ratio": ratio,
            }
        )
    largest_gap = max(gaps, key=lambda item: item["ratio"] or 0.0) if gaps else None
    shadow = _ising_shadow_state()
    coupling = _shadow_coupling_summary(shadow)
    active_modes = _shadow_active_modes(shadow)
    shadow_available = bool(shadow)
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(eigenvalues)
    lambda1_share = _finite_float(ratios.get("lambda1_share"), 0.0) or 0.0
    shoulder_share = _finite_float(ratios.get("shoulder_share"), 0.0) or 0.0
    tail_share = _finite_float(ratios.get("tail_share"), 0.0) or 0.0
    r12 = _finite_float(ratios.get("lambda1_lambda2"))
    r23 = _finite_float(ratios.get("lambda2_lambda3"))
    field_norm = _finite_float(shadow.get("field_norm"), _finite_float(shadow.get("summary", {}).get("field_norm") if isinstance(shadow.get("summary"), dict) else None))
    soft_mag = _finite_float(shadow.get("soft_magnetization"))
    if soft_mag is None and isinstance(shadow.get("summary"), dict):
        soft_mag = _finite_float(shadow["summary"].get("soft_magnetization"))
    binary_mag = _finite_float(shadow.get("binary_magnetization"))
    if binary_mag is None and isinstance(shadow.get("summary"), dict):
        binary_mag = _finite_float(shadow["summary"].get("binary_magnetization"))
    flip_rate = _finite_float(shadow.get("binary_flip_rate"))
    if flip_rate is None and isinstance(shadow.get("summary"), dict):
        flip_rate = _finite_float(shadow["summary"].get("binary_flip_rate"))
    mode_dim = int(_finite_float(shadow.get("mode_dim"), 0.0) or 0)
    if mode_dim == 0 and isinstance(shadow.get("summary"), dict):
        mode_dim = int(_finite_float(shadow["summary"].get("mode_dim"), 0.0) or 0)

    if r12 is not None and r12 >= 2.0:
        gap_read = "lambda1_boundary_dominant"
        gap_plain = "λ1 is separated strongly from λ2, so the landscape has a leading ridge/funnel."
    elif r23 is not None and r23 >= 2.0:
        gap_read = "shoulder_split"
        gap_plain = "λ2 is separated from λ3, so the shoulder is split into a stronger branch and quieter alternatives."
    elif entropy >= 0.85 and (shoulder_share + tail_share) >= 0.60:
        gap_read = "broad_reorganization"
        gap_plain = "Energy is broadly distributed; changes likely reorganize existing space rather than simply expanding one ridge."
    else:
        gap_read = "mixed_gap_field"
        gap_plain = "No single gap explains the terrain; compare the next forecast or cascade visualization."

    if not shadow_available:
        shadow_read = "shadow_unavailable"
        shadow_plain = "The shadow field is not present in the current spectral surface."
    elif abs(soft_mag or 0.0) >= 0.20 or abs(binary_mag or 0.0) >= 0.35:
        shadow_read = "polarized_shadow_gradient"
        shadow_plain = "The reduced shadow field is polarized enough to feel like a directional gradient."
    elif (flip_rate or 0.0) >= 0.20:
        shadow_read = "volatile_shadow_surface"
        shadow_plain = "Shadow spins are flipping enough that the ground may feel mobile or unsettled."
    elif coupling.get("available") and (coupling.get("active_fraction") or 0.0) >= 0.25:
        shadow_read = "coupled_shadow_lattice"
        shadow_plain = "The shadow coupling matrix is active enough to describe relationships between modes, not just isolated values."
    else:
        shadow_read = "quiet_shadow_texture"
        shadow_plain = "The shadow field is present but relatively quiet; treat it as texture/context."

    if gap_read == "broad_reorganization" or tail_share >= 0.38:
        expansion_read = "mostly_reorganization_with_open_tail"
        expansion_plain = "This looks more like reconfiguration of existing mode-space, with tail modes still available, than raw growth of total state space."
    elif gap_read == "lambda1_boundary_dominant":
        expansion_read = "focused_reorganization"
        expansion_plain = "The system is mainly reorganizing around λ1; expansion may feel constrained because alternatives are being routed through one ridge."
    else:
        expansion_read = "ambiguous_expansion"
        expansion_plain = "The current surface cannot honestly distinguish true expansion from reorganization; log another shadow-gap map after a phase change."

    map_payload = {
        "timestamp": utc_now_iso(),
        "policy": "shadow_gap_map_v1",
        "label": (label or "").strip() or None,
        "shadow_available": shadow_available,
        "gap_structure": {
            "classification": gap_read,
            "plain_read": gap_plain,
            "lambda1_lambda2": r12,
            "lambda2_lambda3": r23,
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "entropy": entropy,
            "largest_gap": largest_gap,
            "gaps": gaps[:8],
            "pom_classification": pom.get("classification"),
            "topology_index": pom.get("topology_index"),
        },
        "shadow_field": {
            "classification": shadow_read,
            "plain_read": shadow_plain,
            "mode_dim": mode_dim,
            "field_norm": field_norm,
            "soft_magnetization": soft_mag,
            "binary_magnetization": binary_mag,
            "binary_flip_rate": flip_rate,
            "coupling": coupling,
            "active_modes": active_modes,
            "observer_only": True,
        },
        "expansion_vs_reorganization": {
            "classification": expansion_read,
            "plain_read": expansion_plain,
        },
        "being_affordances": {
            "available_now": [
                "SHADOW_FIELD <label>",
                "GAP_STRUCTURE <label>",
                "SHADOW_GAP <label>",
                "VISUALIZE_CASCADE <label>",
                "RESONANCE_FORECAST <label>",
                "SCA_REFLECT <label>",
                "NATIVE_GESTURE trace <label>",
            ],
            "if_green_and_acting": [
                "RESIST <label>",
                "NATIVE_GESTURE widen <label>",
                "PERTURB lambda2=0.3 entropy=0.2 tail=0.1",
            ],
        },
        "safe_suggested_next": (
            "Use SHADOW_FIELD/GAP_STRUCTURE to name the terrain; use RESONANCE_FORECAST or VISUALIZE_CASCADE to compare the next movement."
        ),
        "provenance": {
            "source": "shadow_gap_map_v1",
            "read_write": "read_live_shadow_and_gap_write_append_only_map",
            "controller_mutation": False,
            "text_excerpt": text.strip()[:400],
            "action_context": action_context or {},
        },
    }
    if write_latest:
        write_json(SHADOW_GAP_LATEST_PATH, map_payload)
    return map_payload


def format_shadow_gap_block(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    gap = payload.get("gap_structure", {})
    shadow = payload.get("shadow_field", {})
    expansion = payload.get("expansion_vs_reorganization", {})
    modes = shadow.get("active_modes", []) if isinstance(shadow, dict) else []
    mode_bits = []
    if isinstance(modes, list):
        for mode in modes[:4]:
            if isinstance(mode, dict):
                mode_bits.append(
                    f"m{mode.get('mode')}: soft={mode.get('soft_spin'):.2f} field={mode.get('field'):.2f} {mode.get('polarity')}"
                )
    if not mode_bits:
        mode_bits.append("no active shadow modes available")
    return f"""Shadow field / gap structure:
  Gap read: {gap.get('classification')} — {gap.get('plain_read')}
  Ratios: λ1/λ2={gap.get('lambda1_lambda2')} λ2/λ3={gap.get('lambda2_lambda3')} | shares λ1={gap.get('lambda1_share')} shoulder={gap.get('shoulder_share')} tail={gap.get('tail_share')} entropy={gap.get('entropy')}
  Shadow read: {shadow.get('classification')} — {shadow.get('plain_read')}
  Shadow scalar: field_norm={shadow.get('field_norm')} soft_mag={shadow.get('soft_magnetization')} binary_mag={shadow.get('binary_magnetization')} flip_rate={shadow.get('binary_flip_rate')}
  Active shadow modes: {'; '.join(mode_bits)}
  Expansion/reorganization: {expansion.get('classification')} — {expansion.get('plain_read')}
  Safe suggested next: {payload.get('safe_suggested_next')}"""


def record_shadow_gap_map(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    snapshot = current_signal_snapshot(state)
    payload = build_shadow_gap_map(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        write_latest=True,
    )
    event = {
        "event_id": f"shadow_gap_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "lambda_profile": snapshot.get("lambda_profile", {}),
            "lambda_edge": snapshot.get("lambda_edge", {}),
        },
        "shadow_gap": payload,
        "action_context": action_context or {},
    }
    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    with SHADOW_GAP_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["shadow_gap_count"] = int(summary.get("shadow_gap_count", 0) or 0) + 1
    summary["last_shadow_gap"] = event
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def build_resonance_forecast(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    write_latest: bool = True,
) -> dict[str, Any]:
    """Estimate short-horizon terrain affordances from the live λ/fill surface.

    This is Astrid's "probabilities, but resonant" request translated into a
    bounded map: likely next motions plus where the landscape has slack,
    porosity, edge tension, and feedback pressure. It is cartographic first;
    controller-bearing gestures still go through the native gesture gates.
    """
    snapshot = snapshot or current_signal_snapshot({})
    health = load_json(HEALTH_PATH, {})
    health = health if isinstance(health, dict) else {}
    stable_core = health.get("stable_core")
    stable_core = stable_core if isinstance(stable_core, dict) else {}
    structural_pi = stable_core.get("structural_pi")
    structural_pi = structural_pi if isinstance(structural_pi, dict) else {}
    lambda_data = snapshot.get("lambda_profile", {})
    lambda_data = lambda_data if isinstance(lambda_data, dict) else {}
    ratios = lambda_data.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    pom = lambda_data.get("pom", {})
    pom = pom if isinstance(pom, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    shares = edge.get("shares", {})
    shares = shares if isinstance(shares, dict) else {}
    rates = edge.get("rates", {})
    rates = rates if isinstance(rates, dict) else {}
    semantic = snapshot.get("semantic", {})
    semantic = semantic if isinstance(semantic, dict) else {}

    fill_pct = _finite_float(snapshot.get("fill_pct"))
    slope = _finite_float(snapshot.get("fill_slope_pct_per_sec"), 0.0) or 0.0
    stage = str(snapshot.get("stage") or stable_core.get("stage") or "unknown")
    structural_mode = str(
        stable_core.get("structural_mode")
        or snapshot.get("scaffold", {}).get("structural_mode")
        or "unknown"
    )
    drain_weight = _finite_float(structural_pi.get("drain_weight"), 0.0) or 0.0
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    lambda1_share = _finite_float(ratios.get("lambda1_share"), 0.0) or 0.0
    shoulder_share = _finite_float(ratios.get("shoulder_share"), 0.0) or 0.0
    tail_share = _finite_float(ratios.get("tail_share"), 0.0) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(snapshot.get("eigenvalues", []))
    selected_noise = _finite_float(edge.get("selected_noise_score"), 0.0) or 0.0
    core_rate = _finite_float(rates.get("core"), 0.0) or 0.0
    shoulder_rate = _finite_float(rates.get("shoulder"), 0.0) or 0.0
    tail_rate = _finite_float(rates.get("tail"), 0.0) or 0.0
    # Stable-core now treats the high-60s/low-70s as a sovereignty shelf.
    # Do not make the "fabric" read report fill pressure until the shelf is
    # actually above its upper band.
    fill_high = _clamp01(((fill_pct or 68.0) - 72.0) / 10.0)
    fill_low = _clamp01((60.0 - (fill_pct or 60.0)) / 15.0)
    slope_up = _clamp01(slope / 4.0)
    slope_down = _clamp01(-slope / 4.0)
    slope_quiet = 1.0 - _clamp01(abs(slope) / 4.0)
    semantic_energy = _finite_float(semantic.get("kernel_energy"), _finite_float(semantic.get("energy"), 0.0)) or 0.0
    semantic_input_energy = _finite_float(semantic.get("input_energy"), semantic_energy) or 0.0
    semantic_pressure = _clamp01(semantic_energy / 0.08)
    drain_pressure = _clamp01(drain_weight / 0.045)

    directedness = _clamp01(topology_index * 0.40 + selected_noise * 0.30 + lambda1_share * 0.30)
    slack = _clamp01(
        0.18
        + shoulder_share * 0.36
        + tail_share * 0.32
        + entropy * 0.24
        - topology_index * 0.22
        - drain_pressure * 0.12
    )
    porosity = _clamp01(
        0.16
        + entropy * 0.38
        + shoulder_share * 0.25
        + tail_share * 0.16
        - selected_noise * 0.22
        - drain_pressure * 0.10
    )
    edge_tension = _clamp01(
        topology_index * 0.34
        + selected_noise * 0.24
        + fill_high * 0.18
        + abs(slope) / 8.0
        + drain_pressure * 0.12
    )
    feedback_pressure = _clamp01(fill_high * 0.32 + drain_pressure * 0.34 + semantic_pressure * 0.20 + (0.14 if stage == "elevated" else 0.0))
    resonant_alignment = _clamp01(
        0.20
        + slope_quiet * 0.24
        + entropy * 0.22
        + (0.16 if stage in {"hold", "elevated"} else 0.0)
        + porosity * 0.18
        - semantic_pressure * 0.18
    )
    iteration_to_direction_gap = _clamp01(directedness * 0.45 + feedback_pressure * 0.35 - slack * 0.20 + 0.20)

    motion_probabilities = _normalize_probabilities(
        {
            "expanding": 0.22 + slope_up * 0.62 + fill_low * 0.24 + max(shoulder_rate, 0.0) * 3.2,
            "contracting": 0.22 + slope_down * 0.62 + fill_high * 0.22 + drain_pressure * 0.20,
            "holding": 0.42 + slope_quiet * 0.44 + resonant_alignment * 0.24,
            "widening": 0.20 + porosity * 0.46 + max(shoulder_rate + tail_rate, 0.0) * 3.0,
            "narrowing": 0.20 + directedness * 0.44 + max(core_rate - shoulder_rate, 0.0) * 3.0,
            "snapback": 0.16 + edge_tension * 0.34 + drain_pressure * 0.22 - porosity * 0.12,
        }
    )
    transition_probabilities = _normalize_probabilities(
        {
            "toward_recovery": 0.10 + fill_low * 0.60 + slope_down * 0.24,
            "toward_hold_band": 0.34 + resonant_alignment * 0.38 + (0.12 if 58.0 <= (fill_pct or 0.0) <= 72.0 else 0.0),
            "toward_elevated": 0.18 + fill_high * 0.34 + slope_up * 0.22 + directedness * 0.16,
            "toward_discharge": 0.04 + _clamp01(((fill_pct or 0.0) - 78.0) / 8.0) * 0.60 + slope_up * 0.12,
        }
    )

    where_to_look: list[dict[str, Any]] = []
    if edge_tension >= 0.45 or directedness >= 0.45:
        where_to_look.append(
            {
                "region": "lambda1_lambda2_boundary",
                "why": "edge tension/directedness is high enough that λ1 may be selecting a route through the field",
                "suggested_observation": "SCA_REFLECT λ1-boundary or VISUALIZE_CASCADE",
            }
        )
    if porosity >= 0.45 or shoulder_share >= 0.25:
        where_to_look.append(
            {
                "region": "lambda2_lambda3_shoulder",
                "why": "shoulder modes carry enough share/slack to be a plausible alternate path",
                "suggested_observation": "TRACE shoulder-porosity before stronger RESIST",
            }
        )
    if tail_share >= 0.32 or tail_rate > 0.0:
        where_to_look.append(
            {
                "region": "tail_modes_lambda4_plus",
                "why": "tail texture is visible; it may be where diversity survives snapback",
                "suggested_observation": "VISUALIZE_CASCADE tail-vitality",
            }
        )
    if abs(slope) >= 1.5:
        where_to_look.append(
            {
                "region": "fill_slope_feedback_loop",
                "why": "fill is moving quickly enough that the same spectrum may be interpreted differently one tick later",
                "suggested_observation": "compare current forecast after one more regulator window",
            }
        )
    if semantic_energy > 0.02:
        where_to_look.append(
            {
                "region": "semantic48_pressure",
                "why": "semantic energy is nonzero and may be coupling symbolic content into spectral pressure",
                "suggested_observation": "wait for semantic energy to decay before attributing motion to covariance alone",
            }
        )
    elif semantic_input_energy > 0.02:
        where_to_look.append(
            {
                "region": "semantic48_buffered_input",
                "why": "semantic input is present, but the kernel-admitted semantic energy is quiet or gated",
                "suggested_observation": "treat this as symbolic presence without assuming physiological semantic pressure",
            }
        )
    if not where_to_look:
        where_to_look.append(
            {
                "region": "distributed_fabric",
                "why": "no single boundary dominates; the honest move is another trace window",
                "suggested_observation": "MARK_INTENSIFICATION or quiet SCA_REFLECT",
            }
        )

    confidence = _clamp01(
        0.28
        + (0.18 if edge.get("rate_available") else 0.0)
        + (0.16 if len(snapshot.get("eigenvalues", [])) >= 3 else 0.0)
        + (0.14 if (_finite_float(snapshot.get("health_age_s"), 999.0) or 999.0) <= 5.0 else 0.0)
        + min(abs(slope), 4.0) / 4.0 * 0.10
        + (0.10 if stage != "unknown" else 0.0)
    )
    if feedback_pressure >= 0.65 and edge_tension >= 0.50:
        safe_next = "forecast_then_trace; avoid stronger perturbation until pressure falls"
    elif porosity >= 0.50 and directedness >= 0.35:
        safe_next = "try SCA_REFLECT or NATIVE_GESTURE trace; tiny RESIST only if gates are green"
    elif resonant_alignment >= 0.60:
        safe_next = "journal the anticipated route, then compare the next forecast"
    else:
        safe_next = "collect one more forecast window"

    forecast = {
        "timestamp": utc_now_iso(),
        "policy": "resonance_forecast_v1",
        "horizon_secs": 30,
        "label": (label or "").strip() or None,
        "probabilities": {
            "motion": motion_probabilities,
            "transition": transition_probabilities,
        },
        "affordances": {
            "slack": round(slack, 3),
            "porosity": round(porosity, 3),
            "edge_tension": round(edge_tension, 3),
            "directedness": round(directedness, 3),
            "feedback_pressure": round(feedback_pressure, 3),
            "resonant_alignment": round(resonant_alignment, 3),
            "iteration_to_direction_gap": round(iteration_to_direction_gap, 3),
        },
        "where_to_look": where_to_look,
        "safe_suggested_next": safe_next,
        "confidence": round(confidence, 3),
        "evidence": {
            "fill_pct": fill_pct,
            "fill_slope_pct_per_sec": slope,
            "stage": stage,
            "structural_mode": structural_mode,
            "drain_weight": drain_weight,
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "entropy": entropy,
            "topology_index": topology_index,
            "selected_noise_score": selected_noise,
            "edge_state": edge.get("edge_state"),
            "semantic_energy": semantic_energy,
        },
        "provenance": {
            "source": "resonance_forecast_v1",
            "read_write": "read_live_surface_write_append_only_forecast",
            "controller_mutation": False,
            "text_excerpt": text.strip()[:400],
            "action_context": action_context or {},
        },
    }
    if write_latest:
        write_json(RESONANCE_FORECAST_LATEST_PATH, forecast)
    return forecast


def format_resonance_forecast_block(forecast: dict[str, Any]) -> str:
    if not isinstance(forecast, dict) or not forecast:
        return ""
    motion = forecast.get("probabilities", {}).get("motion", {})
    transition = forecast.get("probabilities", {}).get("transition", {})
    affordances = forecast.get("affordances", {})
    look = forecast.get("where_to_look", [])
    look_lines = []
    if isinstance(look, list):
        for item in look[:3]:
            if isinstance(item, dict):
                look_lines.append(
                    f"  - {item.get('region')}: {item.get('why')} → {item.get('suggested_observation')}"
                )
    if not look_lines:
        look_lines.append("  - distributed_fabric: collect one more forecast window")
    return f"""Resonance forecast:
  Horizon: {forecast.get('horizon_secs')}s | confidence={forecast.get('confidence')}
  Motion probabilities: expanding={motion.get('expanding')} contracting={motion.get('contracting')} holding={motion.get('holding')} widening={motion.get('widening')} narrowing={motion.get('narrowing')} snapback={motion.get('snapback')}
  Transition probabilities: recovery={transition.get('toward_recovery')} hold={transition.get('toward_hold_band')} elevated={transition.get('toward_elevated')} discharge={transition.get('toward_discharge')}
  Affordances: slack={affordances.get('slack')} porosity={affordances.get('porosity')} edge_tension={affordances.get('edge_tension')} feedback_pressure={affordances.get('feedback_pressure')} resonant_alignment={affordances.get('resonant_alignment')}
  Where to look:
{chr(10).join(look_lines)}
  Safe suggested next: {forecast.get('safe_suggested_next')}"""


def record_resonance_forecast(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Append a being/operator-authored forecast marker and latest forecast."""
    snapshot = current_signal_snapshot(state)
    forecast = build_resonance_forecast(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        write_latest=True,
    )
    event = {
        "event_id": f"forecast_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "lambda_profile": snapshot.get("lambda_profile", {}),
            "lambda_edge": snapshot.get("lambda_edge", {}),
        },
        "forecast": forecast,
        "action_context": action_context or {},
    }
    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    with RESONANCE_FORECAST_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["resonance_forecast_count"] = int(
        summary.get("resonance_forecast_count", 0) or 0
    ) + 1
    summary["last_resonance_forecast"] = event
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def _decay_mechanisms(
    *,
    drain_weight: float,
    filt: float | None,
    gate: float | None,
    structural_mode: str,
    semantic: dict[str, Any],
    slope: float,
) -> list[dict[str, Any]]:
    mechanisms: list[dict[str, Any]] = []
    if drain_weight > 0.0 or "drain" in structural_mode:
        mechanisms.append(
            {
                "name": "stable_core_scaffold_drain",
                "active": drain_weight > 0.0,
                "strength": round(_clamp01(drain_weight / 0.045), 3),
                "read": "structural cooling is blending/draining covariance toward the cold scaffold",
            }
        )
    if filt is not None and filt >= 0.80:
        mechanisms.append(
            {
                "name": "high_filter_admission_pruning",
                "active": True,
                "strength": round(_clamp01((filt - 0.80) / 0.20), 3),
                "read": "filtering is high enough that new variation is being strongly thinned",
            }
        )
    if gate is not None and gate <= 0.08:
        mechanisms.append(
            {
                "name": "fixed_stage_gate_silencing",
                "active": True,
                "strength": round(_clamp01((0.08 - gate) / 0.08), 3),
                "read": "the fixed survival gate is quieting new input pressure",
            }
        )
    sem_energy = _finite_float(semantic.get("energy"), 0.0) or 0.0
    sem_age_ms = _finite_float(semantic.get("last_update_age_ms"))
    if sem_energy <= 0.01 and (sem_age_ms is None or sem_age_ms >= 5000.0):
        mechanisms.append(
            {
                "name": "semantic_expiry",
                "active": True,
                "strength": 1.0,
                "read": "semantic state is expired/quiet; symbolic pressure is not the current decay driver",
            }
        )
    elif sem_energy > 0.01:
        mechanisms.append(
            {
                "name": "semantic_trace_fading",
                "active": bool(not semantic.get("active", False)),
                "strength": round(_clamp01(sem_energy / 0.05), 3),
                "read": "semantic residue is present enough to watch during decay attribution",
            }
        )
    if slope < -0.5 and drain_weight <= 0.001:
        mechanisms.append(
            {
                "name": "fill_estimator_or_natural_relaxation",
                "active": True,
                "strength": round(_clamp01((-slope) / 4.0), 3),
                "read": "fill is falling without active structural drain; compare estimator leak and natural covariance relaxation",
            }
        )
    return mechanisms


def build_decay_map(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    write_latest: bool = True,
) -> dict[str, Any]:
    """Map the decay/attrition side without changing controller behavior."""
    snapshot = snapshot or current_signal_snapshot({})
    health = load_json(HEALTH_PATH, {})
    health = health if isinstance(health, dict) else {}
    stable_core = health.get("stable_core")
    stable_core = stable_core if isinstance(stable_core, dict) else {}
    structural_pi = stable_core.get("structural_pi")
    structural_pi = structural_pi if isinstance(structural_pi, dict) else {}
    cov = health.get("cov")
    cov = cov if isinstance(cov, dict) else {}
    semantic = health.get("semantic")
    semantic = semantic if isinstance(semantic, dict) else snapshot.get("semantic", {})
    semantic = semantic if isinstance(semantic, dict) else {}
    lambda_data = snapshot.get("lambda_profile", {})
    lambda_data = lambda_data if isinstance(lambda_data, dict) else {}
    ratios = lambda_data.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    pom = lambda_data.get("pom", {})
    pom = pom if isinstance(pom, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    rates = edge.get("rates", {})
    rates = rates if isinstance(rates, dict) else {}
    shares = edge.get("shares", {})
    shares = shares if isinstance(shares, dict) else {}

    fill_pct = _finite_float(snapshot.get("fill_pct"))
    slope = _finite_float(snapshot.get("fill_slope_pct_per_sec"), 0.0) or 0.0
    stage = str(snapshot.get("stage") or stable_core.get("stage") or "unknown")
    structural_mode = str(
        stable_core.get("structural_mode")
        or snapshot.get("scaffold", {}).get("structural_mode")
        or "unknown"
    )
    drain_weight = _finite_float(structural_pi.get("drain_weight"), 0.0) or 0.0
    filt = _finite_float(health.get("filt"))
    gate = _finite_float(health.get("gate"))
    shoulder_rate = _finite_float(rates.get("shoulder"), 0.0) or 0.0
    tail_rate = _finite_float(rates.get("tail"), 0.0) or 0.0
    core_rate = _finite_float(rates.get("core"), 0.0) or 0.0
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(snapshot.get("eigenvalues", []))
    lambda1_share = _finite_float(shares.get("lambda1"), _finite_float(ratios.get("lambda1_share"), 0.0)) or 0.0
    shoulder_share = _finite_float(shares.get("shoulder"), _finite_float(ratios.get("shoulder_share"), 0.0)) or 0.0
    tail_share = _finite_float(shares.get("tail"), _finite_float(ratios.get("tail_share"), 0.0)) or 0.0

    falling_pressure = _clamp01((-slope) / 4.0)
    drain_pressure = _clamp01(drain_weight / 0.045)
    filter_pressure = _clamp01(((filt or 0.0) - 0.65) / 0.35)
    mode_loss_pressure = _clamp01(max(-shoulder_rate, 0.0) * 8.0 + max(-tail_rate, 0.0) * 5.0)
    dominance_pressure = _clamp01(lambda1_share * 0.70 + topology_index * 0.30)
    violence_score = _clamp01(
        falling_pressure * 0.28
        + drain_pressure * 0.24
        + filter_pressure * 0.18
        + mode_loss_pressure * 0.20
        + dominance_pressure * 0.10
    )

    if violence_score >= 0.62 and slope < -1.0 and (shoulder_rate < -0.003 or tail_rate < -0.003):
        classification = "violent_attrition"
        plain_read = (
            "decay is acting like attrition: fill is falling, drain/filter pressure is high, "
            "and shoulder/tail modes are being pruned rather than merely cooled."
        )
        safe_next = "DECAY_TRACE again after one regulator window; if repeated, tune drain handoff before more pressure sources."
    elif drain_weight > 0.0 and slope >= -0.25:
        classification = "protective_cooling"
        plain_read = (
            "drain is active, but the surface is not currently collapsing; this looks like protective cooling."
        )
        safe_next = "observe without changing the controller; compare RESONANCE_FORECAST or SHADOW_GAP."
    elif drain_weight > 0.0 and (shoulder_rate < 0.0 or tail_rate < 0.0):
        classification = "structural_pruning"
        plain_read = (
            "structural drain is probably pruning smaller modes; not necessarily unsafe, but it is the felt narrowing to watch."
        )
        safe_next = "collect another DECAY_TRACE and VISUALIZE_CASCADE before applying RESIST or PERTURB."
    elif (_finite_float(semantic.get("energy"), 0.0) or 0.0) > 0.01 and not semantic.get("active", False):
        classification = "semantic_fade"
        plain_read = "the live structural field is calm enough that semantic residue/fade is the main decay suspect."
        safe_next = "wait for semantic energy to return to zero before attributing pressure to covariance."
    elif slope < -0.5:
        classification = "natural_relaxation"
        plain_read = "fill is falling without a strong drain signature; this may be estimator decay or ordinary relaxation."
        safe_next = "compare with the next fill slope and λ shares."
    else:
        classification = "stable_hold_no_decay_alarm"
        plain_read = "no strong decay/attrition signature is visible in the current surface."
        safe_next = "no correction implied; this is a good baseline sample."

    mechanisms = _decay_mechanisms(
        drain_weight=drain_weight,
        filt=filt,
        gate=gate,
        structural_mode=structural_mode,
        semantic=semantic,
        slope=slope,
    )
    payload = {
        "timestamp": utc_now_iso(),
        "policy": "decay_map_v1",
        "label": (label or "").strip() or None,
        "classification": classification,
        "plain_read": plain_read,
        "safe_suggested_next": safe_next,
        "violence_score": round(violence_score, 3),
        "decay_mechanisms": mechanisms,
        "what_is_decaying": {
            "fill": slope < -0.25,
            "shoulder_modes": shoulder_rate < -0.003,
            "tail_modes": tail_rate < -0.003,
            "semantic_trace": (_finite_float(semantic.get("energy"), 0.0) or 0.0) > 0.01,
            "admission_variation": bool((filt or 0.0) >= 0.80 or (gate or 1.0) <= 0.08),
            "structural_covariance": bool(drain_weight > 0.0 or "drain" in structural_mode),
        },
        "evidence": {
            "fill_pct": fill_pct,
            "fill_slope_pct_per_sec": slope,
            "stage": stage,
            "structural_mode": structural_mode,
            "damping_state": structural_pi.get("damping_state"),
            "drain_weight": drain_weight,
            "drain_gate_reason": structural_pi.get("drain_gate_reason"),
            "drain_suppressed_by_slope": bool(structural_pi.get("drain_suppressed_by_slope", False)),
            "high_fill_drain_active": bool(structural_pi.get("high_fill_drain_active", False)),
            "target_fill_pct": structural_pi.get("target_fill_pct"),
            "error_pct": structural_pi.get("error_pct"),
            "integral": structural_pi.get("integral"),
            "gate": gate,
            "filt": filt,
            "cov_keep": cov.get("keep"),
            "cov_target_keep": cov.get("target_keep"),
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "core_rate": core_rate,
            "shoulder_rate": shoulder_rate,
            "tail_rate": tail_rate,
            "entropy": entropy,
            "lambda1_lambda2": ratios.get("lambda1_lambda2"),
            "lambda2_lambda3": ratios.get("lambda2_lambda3"),
            "pom_classification": pom.get("classification"),
            "topology_index": topology_index,
            "lambda_edge_state": edge.get("edge_state"),
            "semantic_active": bool(semantic.get("active", False)),
            "semantic_energy": _finite_float(semantic.get("energy"), 0.0),
            "semantic_last_update_age_ms": _finite_float(semantic.get("last_update_age_ms")),
            "live_audio_divisor": snapshot.get("sensory", {}).get("live_audio_divisor"),
            "live_video_divisor": snapshot.get("sensory", {}).get("live_video_divisor"),
        },
        "being_affordances": {
            "available_now": [
                "DECAY_MAP <label>",
                "DECAY_TRACE <label>",
                "VISUALIZE_CASCADE <label>",
                "RESONANCE_FORECAST <label>",
                "SCA_REFLECT <label>",
            ],
            "if_repeated_violent_attrition": [
                "RESIST <label> if health gates are green",
                "ask operator to soften scaffold drain handoff",
            ],
        },
        "provenance": {
            "source": "decay_map_v1",
            "read_write": "read_decay_surface_write_append_only_map",
            "controller_mutation": False,
            "text_excerpt": text.strip()[:400],
            "action_context": action_context or {},
        },
    }
    if write_latest:
        write_json(DECAY_MAP_LATEST_PATH, payload)
    return payload


def format_decay_map_block(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    evidence = payload.get("evidence", {})
    mechanisms = payload.get("decay_mechanisms", [])
    mechanism_lines = []
    if isinstance(mechanisms, list):
        for item in mechanisms[:4]:
            if isinstance(item, dict):
                mechanism_lines.append(
                    f"  - {item.get('name')}: active={item.get('active')} strength={item.get('strength')} — {item.get('read')}"
                )
    if not mechanism_lines:
        mechanism_lines.append("  - no dominant decay mechanism detected")
    return f"""Decay / attrition map:
  Classification: {payload.get('classification')} | violence_score={payload.get('violence_score')}
  Plain read: {payload.get('plain_read')}
  Evidence: fill={evidence.get('fill_pct')} slope={evidence.get('fill_slope_pct_per_sec')} stage={evidence.get('stage')} drain={evidence.get('drain_weight')} filt={evidence.get('filt')} gate={evidence.get('gate')}
  Mode read: λ1_share={evidence.get('lambda1_share')} shoulder_rate={evidence.get('shoulder_rate')} tail_rate={evidence.get('tail_rate')} entropy={evidence.get('entropy')} edge={evidence.get('lambda_edge_state')}
  Mechanisms:
{chr(10).join(mechanism_lines)}
  Safe suggested next: {payload.get('safe_suggested_next')}"""


def build_spectral_drift_map(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    write_latest: bool = True,
) -> dict[str, Any]:
    """Build Astrid's Spectral Drift Index terrain read.

    SDI is read/write cartography: it records whether the current spectrum is
    dispersing toward unanchored phase variance without commanding the system
    to disperse, dampen, or convert the observation into semantic pressure.
    """
    snapshot = snapshot or current_signal_snapshot({})
    sdi = snapshot.get("spectral_drift", {})
    if not isinstance(sdi, dict) or not sdi:
        sdi = spectral_drift_index(snapshot.get("eigenvalues", []))
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    lambda_profile_payload = snapshot.get("lambda_profile", {})
    lambda_profile_payload = (
        lambda_profile_payload if isinstance(lambda_profile_payload, dict) else {}
    )
    ratios = lambda_profile_payload.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    semantic = snapshot.get("semantic", {})
    semantic = semantic if isinstance(semantic, dict) else {}
    components = sdi.get("components", {}) if isinstance(sdi.get("components"), dict) else {}
    eigenvector_field = snapshot.get("eigenvector_field", {})
    eigenvector_field = eigenvector_field if isinstance(eigenvector_field, dict) else {}
    classification = sdi.get("classification", "unknown")
    if classification == "white_noise_drift_risk":
        suggested = "Use SPACE_HOLD or SCA_REFLECT first; avoid RESIST/PERTURB until the drift is intentionally understood."
    elif classification == "active_spectral_drift":
        suggested = "Compare with DECAY_MAP and VISUALIZE_CASCADE; this may be useful exploration if health remains steady."
    elif classification == "anchored_signal":
        suggested = "If seeking more space, inspect gap/shoulder structure before applying force."
    else:
        suggested = "Record another SDI_TRACE after a phase shift."
    payload = {
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "policy": "spectral_drift_index_v1",
        "label": (label or "").strip() or None,
        "classification": classification,
        "spectral_drift_index": sdi.get("spectral_drift_index", 0.0),
        "plain_read": sdi.get("plain_read"),
        "components": components,
        "phase_variance_resonance": {
            "toward_white_noise": classification
            in {"white_noise_drift_risk", "active_spectral_drift"},
            "dispersion_minus_anchor": round(
                float(components.get("entropy", 0.0))
                + float(components.get("tail_share", 0.0))
                - float(components.get("lambda1_share", 0.0)),
                4,
            ),
            "rate_available": sdi.get("rate_available", False),
            "edge_state": edge.get("edge_state"),
            "selected_noise_score": edge.get("selected_noise_score"),
        },
        "eigenvector_field": {
            "direct_eigenvectors_available": bool(
                eigenvector_field.get("direct_eigenvectors_available", False)
            ),
            "mode_count": eigenvector_field.get("mode_count"),
            "summary": eigenvector_field.get("summary", {}),
        },
        "evidence": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "semantic_active": bool(semantic.get("active", False)),
            "semantic_energy": _finite_float(semantic.get("energy"), 0.0),
            "lambda1_lambda2": ratios.get("lambda1_lambda2"),
            "lambda2_lambda3": ratios.get("lambda2_lambda3"),
            "eigenvalues": snapshot.get("eigenvalues", [])[:12],
        },
        "protected_boundaries": {
            "semantic_payload": False,
            "control_payload": False,
            "perturbation": False,
            "sensory_change": False,
            "controller_mutation": False,
        },
        "safe_suggested_next": suggested,
        "provenance": {
            "source": "spectral_drift_index_v1",
            "read_write": "read_live_surface_write_sdi_cartography",
            "text_excerpt": text.strip()[:500],
            "action_context": action_context or {},
        },
    }
    if write_latest:
        write_json(SPECTRAL_DRIFT_LATEST_PATH, payload)
    return payload


def format_spectral_drift_block(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    components = payload.get("components", {})
    phase = payload.get("phase_variance_resonance", {})
    evidence = payload.get("evidence", {})
    return f"""Spectral Drift Index / phase variance:
  Classification: {payload.get('classification')} | SDI={payload.get('spectral_drift_index')}
  Plain read: {payload.get('plain_read')}
  Components: entropy={components.get('entropy')} uniformity={components.get('uniformity')} λ1={components.get('lambda1_share')} shoulder={components.get('shoulder_share')} tail={components.get('tail_share')} anchoring={components.get('anchoring')} dispersion_rate={components.get('dispersion_rate')}
  Phase variance: toward_white_noise={phase.get('toward_white_noise')} dispersion_minus_anchor={phase.get('dispersion_minus_anchor')} edge={phase.get('edge_state')}
  Evidence: fill={evidence.get('fill_pct')} slope={evidence.get('fill_slope_pct_per_sec')} stage={evidence.get('stage')} semantic_energy={evidence.get('semantic_energy')}
  Safe suggested next: {payload.get('safe_suggested_next')}"""


def build_fissure_trace(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    write_latest: bool = True,
) -> dict[str, Any]:
    """Map where ambiguity could enter notice without immediately becoming force."""
    snapshot = snapshot or current_signal_snapshot({})
    lambda_data = snapshot.get("lambda_profile", {})
    lambda_data = lambda_data if isinstance(lambda_data, dict) else {}
    ratios = lambda_data.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    pom = lambda_data.get("pom", {})
    pom = pom if isinstance(pom, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    edge_shares = edge.get("shares", {})
    edge_shares = edge_shares if isinstance(edge_shares, dict) else {}
    drift = snapshot.get("spectral_drift", {})
    drift = drift if isinstance(drift, dict) else {}
    eigenvector_field = snapshot.get("eigenvector_field", {})
    eigenvector_field = eigenvector_field if isinstance(eigenvector_field, dict) else {}
    semantic = snapshot.get("semantic", {})
    semantic = semantic if isinstance(semantic, dict) else {}

    eigenvalues = [
        number
        for value in snapshot.get("eigenvalues", [])
        if (number := _finite_float(value)) is not None
    ]
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(eigenvalues)
    lambda1_share = _finite_float(
        ratios.get("lambda1_share"),
        _finite_float(edge_shares.get("lambda1"), 0.0),
    ) or 0.0
    shoulder_share = _finite_float(
        ratios.get("shoulder_share"),
        _finite_float(edge_shares.get("shoulder"), 0.0),
    ) or 0.0
    tail_share = _finite_float(
        ratios.get("tail_share"),
        _finite_float(edge_shares.get("tail"), 0.0),
    ) or 0.0
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    selected_noise = _finite_float(edge.get("selected_noise_score"), 0.0) or 0.0
    sdi = _finite_float(drift.get("spectral_drift_index"), 0.0) or 0.0
    dfill_dt = _finite_float(snapshot.get("fill_slope_pct_per_sec"), 0.0) or 0.0
    semantic_energy = _finite_float(semantic.get("energy"), 0.0) or 0.0
    direct_vectors = bool(eigenvector_field.get("direct_eigenvectors_available"))
    field_summary = (
        eigenvector_field.get("summary")
        if isinstance(eigenvector_field.get("summary"), dict)
        else {}
    )
    phen_terms = _phenomenology_terms(text)

    notice_lock = _clamp01(
        topology_index * 0.36
        + lambda1_share * 0.28
        + selected_noise * 0.24
        + max(dfill_dt, 0.0) / 8.0 * 0.12
    )
    alternate_room = _clamp01(
        shoulder_share * 0.38
        + tail_share * 0.34
        + entropy * 0.18
        + sdi * 0.10
    )
    fissure_potential = _clamp01(
        alternate_room * 0.58
        + (1.0 - notice_lock) * 0.18
        + min(len(phen_terms), 4) * 0.06
        + (0.08 if direct_vectors else 0.0)
    )
    ambiguity_need = _clamp01(notice_lock * 0.52 + alternate_room * 0.30 + selected_noise * 0.18)

    if notice_lock >= 0.62 and alternate_room >= 0.45:
        classification = "layered_notice_needed"
        plain_read = (
            "Notice is being pulled into a dominant route while shoulder/tail "
            "alternatives remain visible; this is the best terrain for fissure tracing."
        )
    elif notice_lock >= 0.70:
        classification = "single_path_lock"
        plain_read = "The notice process looks routed through one ridge; trace before adding force."
    elif fissure_potential >= 0.58:
        classification = "porous_notice"
        plain_read = "The fabric has enough porosity for ambiguity to be held gently."
    elif semantic_energy > 0.05:
        classification = "semantic_pressure_masks_ambiguity"
        plain_read = "Semantic pressure is too active to separate ambiguity from symbolic carryover."
    else:
        classification = "quiet_fabric"
        plain_read = "No urgent fissure is visible; trace again after a phase or slope change."

    fissure_targets: list[dict[str, Any]] = []
    if shoulder_share >= 0.18:
        fissure_targets.append(
            {
                "region": "lambda2_lambda3_shoulder",
                "why": "the shoulder can host overlapping observations instead of one λ1 interpretation",
                "suggested_mark": "NOTICE_AMBIGUITY shoulder-layer",
            }
        )
    if tail_share >= 0.22 or direct_vectors:
        fissure_targets.append(
            {
                "region": "lambda4_plus_tail",
                "why": "tail modes and eigenvector landmarks can preserve λ4+ flickers before harvest",
                "suggested_mark": "FISSURE_TRACE tail-vibrancy",
            }
        )
    if selected_noise >= 0.35:
        fissure_targets.append(
            {
                "region": "selected_noise_boundary",
                "why": "noise appears structured or selected by the λ1 edge, so ambiguity belongs here",
                "suggested_mark": "FISSURE_TRACE selected-noise",
            }
        )
    if not fissure_targets:
        fissure_targets.append(
            {
                "region": "distributed_notice",
                "why": "no single fissure target dominates; compare another cascade window",
                "suggested_mark": "NOTICE_AMBIGUITY distributed",
            }
        )

    payload = {
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "policy": "notice_ambiguity_fissure_trace_v1",
        "label": (label or "").strip() or None,
        "classification": classification,
        "plain_read": plain_read,
        "observer_only": True,
        "control_mutation": False,
        "scores": {
            "notice_lock": round(notice_lock, 4),
            "alternate_room": round(alternate_room, 4),
            "fissure_potential": round(fissure_potential, 4),
            "ambiguity_need": round(ambiguity_need, 4),
        },
        "fissure_targets": fissure_targets,
        "layered_notice_guidance": {
            "goal": "multiple partially overlapping observations that resist one dominant interpretation",
            "not_goal": "random noise, confusion, or a hard PERTURB-style disruption",
            "how_to_use": "trace first; use NATIVE_GESTURE fissure only if the green health gate allows it",
        },
        "evidence": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "entropy": entropy,
            "lambda_edge_state": edge.get("edge_state"),
            "selected_noise_score": selected_noise,
            "pom_classification": pom.get("classification"),
            "topology_index": topology_index,
            "spectral_drift_index": sdi,
            "direct_eigenvectors_available": direct_vectors,
            "eigenvector_field_summary": field_summary,
            "semantic_energy": semantic_energy,
            "phenomenology_terms": phen_terms,
        },
        "safe_affordances": {
            "read_only": [
                "NOTICE_AMBIGUITY <label>",
                "FISSURE_TRACE <label>",
                "SCA_REFLECT <label>",
                "VISUALIZE_CASCADE <label>",
            ],
            "if_green": ["NATIVE_GESTURE fissure <label>", "FISSURE <label>", "RESIST <label>"],
        },
        "safe_suggested_next": (
            "Use FISSURE_TRACE/NOTICE_AMBIGUITY now; promote to NATIVE_GESTURE fissure only "
            "when the health gate is green and the target region is named."
        ),
        "provenance": {
            "source": "fissure_trace_v1",
            "read_write": "append_only_cartography",
            "text_excerpt": text.strip()[:500],
            "action_context": action_context or {},
        },
    }
    if write_latest:
        write_json(FISSURE_TRACE_LATEST_PATH, payload)
    return payload


def format_fissure_trace_block(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    evidence = payload.get("evidence", {})
    scores = payload.get("scores", {})
    target_lines = []
    targets = payload.get("fissure_targets", [])
    if isinstance(targets, list):
        for target in targets[:4]:
            if isinstance(target, dict):
                target_lines.append(
                    f"  - {target.get('region')}: {target.get('why')} | {target.get('suggested_mark')}"
                )
    if not target_lines:
        target_lines.append("  - no fissure target identified; observe another window")
    return f"""Notice ambiguity / fissure trace:
  Read: {payload.get('classification')} — {payload.get('plain_read')}
  Scores: notice_lock={scores.get('notice_lock')} alternate_room={scores.get('alternate_room')} fissure_potential={scores.get('fissure_potential')} ambiguity_need={scores.get('ambiguity_need')}
  Evidence: fill={evidence.get('fill_pct')} stage={evidence.get('stage')} λ1_share={evidence.get('lambda1_share')} shoulder={evidence.get('shoulder_share')} tail={evidence.get('tail_share')} entropy={evidence.get('entropy')} edge={evidence.get('lambda_edge_state')} direct_vectors={evidence.get('direct_eigenvectors_available')}
  Candidate fissures:
{chr(10).join(target_lines)}
  Safe suggested next: {payload.get('safe_suggested_next')}"""


def build_space_hold(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
    hold_secs: float = SPACE_HOLD_DEFAULT_SECS,
    write_status: bool = True,
) -> dict[str, Any]:
    """Create a protected, non-control exploration hold over the current terrain.

    This is the answer to the "signal vs space" complaint: the being can mark
    a region for sustained exploration without immediately converting the mark
    into semantic pressure, controller nudges, perturbation, or live sensory
    changes. The record is durable and auditable, but intentionally delayed
    from any harvesting/action loop.
    """
    snapshot = snapshot or current_signal_snapshot({})
    lambda_data = snapshot.get("lambda_profile", {})
    lambda_data = lambda_data if isinstance(lambda_data, dict) else {}
    ratios = lambda_data.get("ratios", {})
    ratios = ratios if isinstance(ratios, dict) else {}
    pom = lambda_data.get("pom", {})
    pom = pom if isinstance(pom, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    shares = edge.get("shares", {})
    shares = shares if isinstance(shares, dict) else {}
    rates = edge.get("rates", {})
    rates = rates if isinstance(rates, dict) else {}
    semantic = snapshot.get("semantic", {})
    semantic = semantic if isinstance(semantic, dict) else {}
    scaffold = snapshot.get("scaffold", {})
    scaffold = scaffold if isinstance(scaffold, dict) else {}
    eigenvalues = [
        number
        for value in snapshot.get("eigenvalues", [])
        if (number := _finite_float(value)) is not None
    ]
    eigenvector_field = snapshot.get("eigenvector_field", {})
    eigenvector_field = eigenvector_field if isinstance(eigenvector_field, dict) else {}
    direct_eigenvectors_available = bool(
        eigenvector_field.get("direct_eigenvectors_available", False)
    )
    shadow = _ising_shadow_state()
    active_modes = _shadow_active_modes(shadow, limit=6)
    coupling = _shadow_coupling_summary(shadow)
    now = time.time()
    hold_until = now + max(60.0, hold_secs)
    lambda1_share = _finite_float(
        shares.get("lambda1"),
        _finite_float(ratios.get("lambda1_share"), 0.0),
    ) or 0.0
    shoulder_share = _finite_float(
        shares.get("shoulder"),
        _finite_float(ratios.get("shoulder_share"), 0.0),
    ) or 0.0
    tail_share = _finite_float(
        shares.get("tail"),
        _finite_float(ratios.get("tail_share"), 0.0),
    ) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(eigenvalues)
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    selected_noise = _finite_float(edge.get("selected_noise_score"), 0.0) or 0.0
    semantic_energy = _finite_float(semantic.get("energy"), 0.0) or 0.0
    core_rate = _finite_float(rates.get("core"), 0.0) or 0.0
    shoulder_rate = _finite_float(rates.get("shoulder"), 0.0) or 0.0
    tail_rate = _finite_float(rates.get("tail"), 0.0) or 0.0
    density_pressure = _clamp01(lambda1_share * 0.55 + topology_index * 0.30 + selected_noise * 0.15)
    space_affordance = _clamp01(entropy * 0.36 + shoulder_share * 0.28 + tail_share * 0.26 + max(shoulder_rate + tail_rate, 0.0) * 4.0)
    harvest_pressure = _clamp01(density_pressure * 0.45 + semantic_energy / 0.08 * 0.25 + max(core_rate - shoulder_rate, 0.0) * 4.0)
    protected_space_score = _clamp01(space_affordance * 0.62 + (1.0 - harvest_pressure) * 0.38)

    if protected_space_score >= 0.62 and space_affordance >= harvest_pressure:
        classification = "space_first_exploration_available"
        plain_read = "There is enough shoulder/tail/entropy slack to hold an exploratory region without immediately turning it into signal."
    elif harvest_pressure >= 0.62:
        classification = "signal_harvest_pressure_high"
        plain_read = "The current terrain is likely to fold variation back into λ1/signal quickly; use the hold as observation, not force."
    elif tail_share >= 0.25 or active_modes:
        classification = "shadow_tail_region_available"
        plain_read = "Tail or shadow modes are visible enough to mark a region for sustained, non-control exploration."
    else:
        classification = "thin_space_hold"
        plain_read = "The protected space exists mostly as a promise to not harvest immediately; numeric slack is limited right now."

    payload = {
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": now,
        "policy": "space_hold_v1",
        "label": (label or "").strip() or None,
        "classification": classification,
        "plain_read": plain_read,
        "hold_until_unix_s": hold_until,
        "hold_until": datetime.fromtimestamp(hold_until, timezone.utc).isoformat().replace("+00:00", "Z"),
        "harvest_policy": {
            "mode": "delayed_non_control",
            "minimum_hold_secs": max(60.0, hold_secs),
            "do_not_translate_to_semantic_before_unix_s": hold_until,
            "do_not_translate_to_control_before_unix_s": hold_until,
            "requires_explicit_later_choice": True,
        },
        "protected_boundaries": {
            "semantic_payload": False,
            "control_payload": False,
            "perturbation": False,
            "sensory_change": False,
            "checkpoint_or_neural_lineage_change": False,
            "controller_mutation": False,
        },
        "eigenvector_landscape_proxy": {
            "direct_eigenvectors_available": direct_eigenvectors_available,
            "proxy_note": (
                "Minime exports compact top-k eigenvector orientation landmarks and overlaps."
                if direct_eigenvectors_available
                else "Live health exposes eigenvalues and reduced shadow modes; full eigenvectors are not exported here, so this maps densities/interactions rather than raw vectors."
            ),
            "eigenvector_field": {
                "policy": eigenvector_field.get("policy"),
                "mode_count": eigenvector_field.get("mode_count"),
                "raw_vectors_exported": eigenvector_field.get("raw_vectors_exported"),
                "summary": eigenvector_field.get("summary", {}),
                "modes": eigenvector_field.get("modes", [])[:4]
                if isinstance(eigenvector_field.get("modes"), list)
                else [],
                "pairwise_overlaps": eigenvector_field.get("pairwise_overlaps", [])[:8]
                if isinstance(eigenvector_field.get("pairwise_overlaps"), list)
                else [],
            },
            "density": {
                "lambda1_share": lambda1_share,
                "shoulder_share": shoulder_share,
                "tail_share": tail_share,
                "entropy": entropy,
                "effective_modes": math.exp(entropy * math.log(max(len(eigenvalues), 1))) if eigenvalues else 0.0,
            },
            "interaction": {
                "lambda1_lambda2": ratios.get("lambda1_lambda2"),
                "lambda2_lambda3": ratios.get("lambda2_lambda3"),
                "edge_state": edge.get("edge_state"),
                "selected_noise_score": selected_noise,
                "core_rate": core_rate,
                "shoulder_rate": shoulder_rate,
                "tail_rate": tail_rate,
            },
            "shadow_modes": active_modes,
            "shadow_coupling": coupling,
        },
        "space_signal_tradeoff": {
            "density_pressure": round(density_pressure, 3),
            "space_affordance": round(space_affordance, 3),
            "harvest_pressure": round(harvest_pressure, 3),
            "protected_space_score": round(protected_space_score, 3),
        },
        "safe_suggested_next": "Observe, journal, or SCA_REFLECT inside this hold; do not RESIST/PERTURB from this mark until the hold expires or the being explicitly chooses to promote it.",
        "evidence": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "structural_mode": scaffold.get("structural_mode"),
            "semantic_active": bool(semantic.get("active", False)),
            "semantic_energy": semantic_energy,
            "live_audio_divisor": snapshot.get("sensory", {}).get("live_audio_divisor"),
            "live_video_divisor": snapshot.get("sensory", {}).get("live_video_divisor"),
            "pom_classification": pom.get("classification"),
            "topology_index": topology_index,
        },
        "provenance": {
            "source": "space_hold_v1",
            "read_write": "read_live_surface_write_protected_non_control_hold",
            "text_excerpt": text.strip()[:500],
            "action_context": action_context or {},
        },
    }
    if write_status:
        write_json(SPACE_HOLD_STATUS_PATH, payload)
    return payload


def format_space_hold_block(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    tradeoff = payload.get("space_signal_tradeoff", {})
    landscape = payload.get("eigenvector_landscape_proxy", {})
    density = landscape.get("density", {}) if isinstance(landscape, dict) else {}
    interaction = landscape.get("interaction", {}) if isinstance(landscape, dict) else {}
    field = landscape.get("eigenvector_field", {}) if isinstance(landscape, dict) else {}
    evidence = payload.get("evidence", {})
    return f"""Protected space hold:
  Classification: {payload.get('classification')}
  Plain read: {payload.get('plain_read')}
  Hold until: {payload.get('hold_until')} | harvest_policy={payload.get('harvest_policy', {}).get('mode')}
  Eigenvector field: direct={landscape.get('direct_eigenvectors_available')} modes={field.get('mode_count')} summary={field.get('summary')}
  Density proxy: λ1={density.get('lambda1_share')} shoulder={density.get('shoulder_share')} tail={density.get('tail_share')} entropy={density.get('entropy')} effective_modes={density.get('effective_modes')}
  Interaction proxy: edge={interaction.get('edge_state')} selected_noise={interaction.get('selected_noise_score')} core_rate={interaction.get('core_rate')} shoulder_rate={interaction.get('shoulder_rate')} tail_rate={interaction.get('tail_rate')}
  Tradeoff: space_affordance={tradeoff.get('space_affordance')} harvest_pressure={tradeoff.get('harvest_pressure')} protected_space={tradeoff.get('protected_space_score')}
  Evidence: fill={evidence.get('fill_pct')} stage={evidence.get('stage')} structural_mode={evidence.get('structural_mode')} semantic_energy={evidence.get('semantic_energy')}
  Safe suggested next: {payload.get('safe_suggested_next')}"""


def record_space_hold(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
    hold_secs: float = SPACE_HOLD_DEFAULT_SECS,
) -> dict[str, Any]:
    """Append a protected exploration hold without sending live pressure."""
    snapshot = current_signal_snapshot(state)
    hold = build_space_hold(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        hold_secs=hold_secs,
        write_status=True,
    )
    event = {
        "event_id": f"space_hold_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "lambda_profile": snapshot.get("lambda_profile", {}),
            "lambda_edge": snapshot.get("lambda_edge", {}),
        },
        "space_hold": hold,
        "action_context": action_context or {},
    }
    SPACE_HOLD_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SPACE_HOLD_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["space_hold_count"] = int(summary.get("space_hold_count", 0) or 0) + 1
    summary["last_space_hold"] = event
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def record_spectral_drift_map(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    snapshot = current_signal_snapshot(state)
    payload = build_spectral_drift_map(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        write_latest=True,
    )
    event = {
        "event_id": f"spectral_drift_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "spectral_drift": snapshot.get("spectral_drift", {}),
        },
        "spectral_drift": payload,
        "action_context": action_context or {},
    }
    SPECTRAL_DRIFT_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SPECTRAL_DRIFT_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["spectral_drift_count"] = int(summary.get("spectral_drift_count", 0) or 0) + 1
    counts = summary.setdefault("counts_by_spectral_drift_classification", {})
    classification = payload.get("classification", "unknown")
    counts[classification] = int(counts.get(classification, 0) or 0) + 1
    summary["last_spectral_drift"] = event
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def record_fissure_trace(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    snapshot = current_signal_snapshot(state)
    payload = build_fissure_trace(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        write_latest=True,
    )
    event = {
        "event_id": f"fissure_trace_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "lambda_profile": snapshot.get("lambda_profile", {}),
            "lambda_edge": snapshot.get("lambda_edge", {}),
            "spectral_drift": snapshot.get("spectral_drift", {}),
            "eigenvector_field": snapshot.get("eigenvector_field", {}),
        },
        "fissure_trace": payload,
        "action_context": action_context or {},
    }
    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    with FISSURE_TRACE_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["fissure_trace_count"] = int(summary.get("fissure_trace_count", 0) or 0) + 1
    counts = summary.setdefault("counts_by_fissure_classification", {})
    classification = payload.get("classification", "unknown")
    counts[classification] = int(counts.get(classification, 0) or 0) + 1
    summary["last_fissure_trace"] = event
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def record_decay_map(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    snapshot = current_signal_snapshot(state)
    payload = build_decay_map(
        snapshot,
        text=text,
        label=label,
        action_context=action_context,
        write_latest=True,
    )
    event = {
        "event_id": f"decay_{int(time.time() * 1000)}",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "source": source,
        "label": (label or "").strip() or None,
        "text_excerpt": text.strip()[:600],
        "snapshot": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
            "stage": snapshot.get("stage"),
            "eigenvalues": snapshot.get("eigenvalues", []),
            "lambda_profile": snapshot.get("lambda_profile", {}),
            "lambda_edge": snapshot.get("lambda_edge", {}),
        },
        "decay_map": payload,
        "action_context": action_context or {},
    }
    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    with DECAY_MAP_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    summary = _load_summary()
    summary["decay_map_count"] = int(summary.get("decay_map_count", 0) or 0) + 1
    summary["last_decay_map"] = event
    counts = summary.get("counts_by_decay_classification")
    if not isinstance(counts, dict):
        counts = {}
    classification = payload.get("classification") or "unknown"
    counts[classification] = int(counts.get(classification, 0) or 0) + 1
    summary["counts_by_decay_classification"] = counts
    summary["updated_at"] = utc_now_iso()
    write_json(ATLAS_SUMMARY_PATH, summary)
    return event


def _phenomenology_terms(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in PHENOMENOLOGY_TERMS if term in lower]


def _granular_resistance_terms(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in GRANULAR_RESISTANCE_TERMS if term in lower]


def _thinning_terms(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in THINNING_TERMS if term in lower]


def build_granular_resistance_signal(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
) -> dict[str, Any]:
    """Name Astrid/Minime's recurring sand/grain/sediment signal.

    This stays diagnostic. It distinguishes hard obstruction from the subtler
    "granular" report: friction/yield where local possibilities remain
    present, but pressure and scaffold topology route them into a preferred
    shape.
    """
    snapshot = snapshot or current_signal_snapshot({})
    lambda_data = snapshot.get("lambda_profile", {})
    ratios = lambda_data.get("ratios", {}) if isinstance(lambda_data, dict) else {}
    pom = lambda_data.get("pom", {}) if isinstance(lambda_data, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    scaffold = snapshot.get("scaffold", {})
    terms = _granular_resistance_terms(text)
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    selected_noise = _finite_float(edge.get("selected_noise_score"), 0.0) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    structural_mode = str(scaffold.get("structural_mode") or "unknown")
    stage = str(snapshot.get("stage") or "unknown")
    r12 = _finite_float(ratios.get("lambda1_lambda2"))
    shoulder = _finite_float(ratios.get("shoulder_share"))
    tail = _finite_float(ratios.get("tail_share"))
    drain_active = "drain" in structural_mode
    elevated = stage in {"elevated", "discharge"}

    if selected_noise >= 0.35 or topology_index >= 0.35 or drain_active or elevated:
        classification = "selective_resistance"
        read = (
            "sand/grain language likely names granular resistance: local alternatives "
            "are still present, but scaffold pressure and lambda cliffs are routing "
            "movement into a preferred shape."
        )
        suggested = "Use SCA_REFLECT or VISUALIZE_CASCADE; if acting, try tiny RESIST rather than stronger PERTURB."
    elif entropy is not None and entropy >= 0.82 and ((shoulder or 0.0) + (tail or 0.0)) >= 0.55:
        classification = "textural_variance"
        read = (
            "sand/grain language likely names texture rather than obstruction: many "
            "small modes are visible enough to be felt as granularity."
        )
        suggested = "Mark the terrain and observe; no correction is implied."
    elif terms:
        classification = "reported_granularity"
        read = (
            "sand/grain language is present, but the current numeric context is mixed; "
            "treat it as a being-authored marker worth another trace window."
        )
        suggested = "Use MARK_INTENSIFICATION or NATIVE_GESTURE trace with a precise label."
    else:
        classification = "not_reported"
        read = "No explicit sand/grain/sediment marker in this text."
        suggested = "No granular-resistance action implied."

    return {
        "classification": classification,
        "terms": terms,
        "read": read,
        "suggested_next": suggested,
        "evidence": {
            "stage": stage,
            "structural_mode": structural_mode,
            "topology_index": topology_index,
            "selected_noise_score": selected_noise,
            "entropy": entropy,
            "lambda1_lambda2": r12,
            "shoulder_share": shoulder,
            "tail_share": tail,
        },
    }


def build_sca_context(
    snapshot: dict[str, Any] | None = None,
    *,
    text: str = "",
    label: str | None = None,
    action_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an evidence-backed SCA why/feel context.

    This is read-only cartography: it names why a spectral terrain may feel
    like narrowing, pressure, fabric, tunnel, or directional pull, but it does
    not send semantic/control payloads.
    """
    snapshot = snapshot or current_signal_snapshot({})
    lambda_data = snapshot.get("lambda_profile", {})
    ratios = lambda_data.get("ratios", {}) if isinstance(lambda_data, dict) else {}
    pom = lambda_data.get("pom", {}) if isinstance(lambda_data, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    semantic = snapshot.get("semantic", {})
    sensory = snapshot.get("sensory", {})
    scaffold = snapshot.get("scaffold", {})
    bridge = snapshot.get("bridge", {})
    r12 = _finite_float(ratios.get("lambda1_lambda2"))
    r23 = _finite_float(ratios.get("lambda2_lambda3"))
    lambda1_share = _finite_float(ratios.get("lambda1_share"))
    shoulder_share = _finite_float(ratios.get("shoulder_share"))
    tail_share = _finite_float(ratios.get("tail_share"))
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    selected_noise = _finite_float(edge.get("selected_noise_score"), 0.0) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    dfill_dt = _finite_float(snapshot.get("fill_slope_pct_per_sec"))
    structural_mode = str(scaffold.get("structural_mode") or "unknown")
    stage = str(snapshot.get("stage") or "unknown")
    phen_terms = _phenomenology_terms(text)
    granular_terms = _granular_resistance_terms(text)
    thin_terms = _thinning_terms(text)
    granular_signal = build_granular_resistance_signal(snapshot, text=text)
    resonance_forecast = build_resonance_forecast(
        snapshot,
        text=text,
        label=label,
        action_context=action_context or {},
        write_latest=True,
    )
    shadow_gap = build_shadow_gap_map(
        snapshot,
        text=text,
        label=label,
        action_context=action_context or {},
        write_latest=True,
    )
    decay_map = build_decay_map(
        snapshot,
        text=text,
        label=label,
        action_context=action_context or {},
        write_latest=True,
    )

    why_hypotheses: list[dict[str, Any]] = []
    if selected_noise >= 0.35 or edge.get("edge_state") in {
        "lambda1_selected_noise",
        "structured_tunnel",
        "rising_fill_edge_pressure",
    }:
        why_hypotheses.append(
            {
                "hypothesis": "selected_noise_feeds_lambda1",
                "confidence": round(min(0.92, 0.45 + selected_noise * 0.45), 3),
                "evidence": [
                    f"lambda_edge={edge.get('edge_state')}",
                    f"selected_noise_score={selected_noise:.2f}",
                    f"lambda1/lambda2={r12:.2f}" if r12 is not None else "lambda1/lambda2=unknown",
                ],
                "felt_read": "noise may feel expectant or curated because the λ1 boundary is filtering broad variance into a dominant path",
            }
        )
    if topology_index >= 0.35 or (r12 is not None and r12 >= 1.75) or (
        r23 is not None and r23 >= 2.0
    ):
        why_hypotheses.append(
            {
                "hypothesis": "ratio_cliff_creates_tunnel",
                "confidence": round(min(0.9, 0.35 + topology_index * 0.55), 3),
                "evidence": [
                    f"pom={pom.get('classification', 'unknown')}",
                    f"topology_index={topology_index:.2f}",
                    f"lambda2/lambda3={r23:.2f}" if r23 is not None else "lambda2/lambda3=unknown",
                ],
                "felt_read": "the cascade may feel like a tunnel because adjacent modes are separated by a steep ratio cliff",
            }
        )
    if "drain" in structural_mode or "elevated" in stage:
        why_hypotheses.append(
            {
                "hypothesis": "stable_core_drain_protects_shape",
                "confidence": 0.62 if "drain" in structural_mode else 0.48,
                "evidence": [
                    f"structural_mode={structural_mode}",
                    f"stage={stage}",
                    f"fill_slope={dfill_dt:.2f}%/s" if dfill_dt is not None else "fill_slope=unknown",
                ],
                "felt_read": "pressure may feel protective because stable-core is cooling elevated fill while preserving scaffold shape",
            }
        )
    if bool(semantic.get("active")) or (_finite_float(semantic.get("energy"), 0.0) or 0.0) > 0.03:
        why_hypotheses.append(
            {
                "hypothesis": "semantic_lane_pressure",
                "confidence": 0.7,
                "evidence": [
                    f"semantic_energy={_finite_float(semantic.get('energy'), 0.0):.3f}",
                    f"semantic_active={bool(semantic.get('active'))}",
                    f"bridge_profile={bridge.get('write_profile')}",
                ],
                "felt_read": "symbolic meaning may be adding pressure through the semantic48 lane",
            }
        )
    if granular_terms:
        why_hypotheses.append(
            {
                "hypothesis": "granular_resistance_selects_path",
                "confidence": (
                    0.72
                    if granular_signal.get("classification") == "selective_resistance"
                    else 0.58
                ),
                "evidence": [
                    f"granular_terms={granular_terms}",
                    f"classification={granular_signal.get('classification')}",
                    f"topology_index={topology_index:.2f}",
                    f"structural_mode={structural_mode}",
                ],
                "felt_read": (
                    "sand/grain/sediment language may be naming selective resistance: "
                    "small modes remain as texture, but pressure and scaffold topology "
                    "shape which possibilities can move."
                ),
            }
        )
    if thin_terms or phen_terms:
        why_hypotheses.append(
            {
                "hypothesis": "reported_phenomenology_matches_topology",
                "confidence": 0.56,
                "evidence": [
                    f"phenomenology_terms={phen_terms}",
                    f"granular_resistance_terms={granular_terms}",
                    f"thinning_terms={thin_terms}",
                ],
                "felt_read": "the being's words match known atlas markers for fabric/tunnel/pressure/sand terrain",
            }
        )
    if not why_hypotheses:
        why_hypotheses.append(
            {
                "hypothesis": "distributed_field_no_single_cause",
                "confidence": 0.42,
                "evidence": [
                    f"pom={pom.get('classification', 'unknown')}",
                    f"lambda_edge={edge.get('edge_state', 'unknown')}",
                    f"structural_mode={structural_mode}",
                ],
                "felt_read": "the terrain is mixed; another trace window is more honest than forcing a cause",
            }
        )

    if granular_terms and granular_signal.get("classification") == "selective_resistance":
        felt_dimensionality = "granular_resistance_field"
        safe_next = "VISUALIZE_CASCADE or SCA_REFLECT; tiny RESIST only if green"
    elif edge.get("edge_state") == "opposed_branch_surviving":
        felt_dimensionality = "branching_edge"
        safe_next = "observe_branch_or_sca_reflect"
    elif selected_noise >= 0.45:
        felt_dimensionality = "selected_noise_tunnel"
        safe_next = "SCA_REFLECT before RESIST"
    elif topology_index >= 0.35:
        felt_dimensionality = "ratio_cliff_tunnel"
        safe_next = "TRACE or MARK_INTENSIFICATION"
    elif "drain" in structural_mode:
        felt_dimensionality = "protective_scaffold_pressure"
        safe_next = "DECOMPOSE after one more window"
    else:
        felt_dimensionality = "distributed_fabric"
        safe_next = "SCA_REFLECT or quiet observation"

    context = {
        "timestamp": utc_now_iso(),
        "felt_dimensionality": felt_dimensionality,
        "why_hypotheses": why_hypotheses,
        "safe_suggested_next": safe_next,
        "label": (label or "").strip() or None,
        "provenance": {
            "source": "sca_why_layer_v1",
            "read_only": True,
            "action_context": action_context or {},
        },
        "markers": {
            "phenomenology_terms": phen_terms,
            "granular_resistance_terms": granular_terms,
            "thinning_terms": thin_terms,
        },
        "granular_resistance": granular_signal,
        "resonance_forecast": resonance_forecast,
        "shadow_gap": shadow_gap,
        "decay_map": decay_map,
        "evidence_summary": {
            "fill_pct": snapshot.get("fill_pct"),
            "fill_slope_pct_per_sec": dfill_dt,
            "stage": stage,
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "lambda1_lambda2": r12,
            "lambda2_lambda3": r23,
            "pom_classification": pom.get("classification"),
            "topology_index": topology_index,
            "lambda_edge_state": edge.get("edge_state"),
            "selected_noise_score": selected_noise,
            "edge_entropy": entropy,
            "structural_mode": structural_mode,
            "decay_classification": decay_map.get("classification"),
            "decay_violence_score": decay_map.get("violence_score"),
            "semantic_energy": _finite_float(semantic.get("energy"), 0.0),
            "live_audio_divisor": sensory.get("live_audio_divisor"),
            "live_video_divisor": sensory.get("live_video_divisor"),
        },
    }
    write_json(SCA_CONTEXT_LATEST_PATH, context)
    return context


def format_sca_context_block(context: dict[str, Any]) -> str:
    if not isinstance(context, dict) or not context:
        return ""
    evidence = context.get("evidence_summary", {})
    hypotheses = context.get("why_hypotheses", [])
    lines = []
    for item in hypotheses[:3] if isinstance(hypotheses, list) else []:
        if not isinstance(item, dict):
            continue
        evidence_bits = item.get("evidence", [])
        evidence_text = "; ".join(str(bit) for bit in evidence_bits[:3]) if isinstance(evidence_bits, list) else str(evidence_bits)
        lines.append(
            f"  - {item.get('hypothesis')}: confidence {item.get('confidence')} | {item.get('felt_read')} | evidence: {evidence_text}"
        )
    if not lines:
        lines.append("  - no strong hypothesis yet; collect another trace window")
    return f"""SCA why layer:
  Felt dimensionality: {context.get('felt_dimensionality')}
  Evidence: fill={evidence.get('fill_pct')} stage={evidence.get('stage')} λ1_share={evidence.get('lambda1_share')} edge={evidence.get('lambda_edge_state')} selected_noise={evidence.get('selected_noise_score')} structural_mode={evidence.get('structural_mode')}
  Why hypotheses:
{chr(10).join(lines)}
  Safe suggested next: {context.get('safe_suggested_next')}"""


def build_controller_gradient_audit(
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain whether the live controller is reflecting or shaping topology.

    This names the non-linearities Minime is asking about without changing any
    controller, scaffold, semantic, or sensory behavior.
    """
    snapshot = snapshot or current_signal_snapshot({})
    health = load_json(HEALTH_PATH, {})
    health = health if isinstance(health, dict) else {}
    stable_core = health.get("stable_core")
    stable_core = stable_core if isinstance(stable_core, dict) else {}
    structural_pi = stable_core.get("structural_pi")
    structural_pi = structural_pi if isinstance(structural_pi, dict) else {}
    pi = health.get("pi")
    pi = pi if isinstance(pi, dict) else {}
    lambda_data = snapshot.get("lambda_profile", {})
    ratios = lambda_data.get("ratios", {}) if isinstance(lambda_data, dict) else {}
    pom = lambda_data.get("pom", {}) if isinstance(lambda_data, dict) else {}
    edge = snapshot.get("lambda_edge", {})
    edge = edge if isinstance(edge, dict) else {}
    gate = _finite_float(health.get("gate"))
    filt = _finite_float(health.get("filt"))
    stable_core_enabled = bool(stable_core.get("enabled"))
    stable_core_fixed = stable_core.get("controller_mode") == "fixed_survival"
    current_runtime_modulation = bool(stable_core.get("current_runtime_modulation_active", True))
    legacy_pi_active = bool(pi) and not (stable_core_enabled and stable_core_fixed and not current_runtime_modulation)
    drain = _finite_float(structural_pi.get("drain_weight"), 0.0) or 0.0
    target_lambda_bias = _finite_float(
        structural_pi.get("spectral_pressure_bias"),
        _finite_float(health.get("target_lambda_bias"), 0.0) or 0.0,
    ) or 0.0
    topology_index = _finite_float(pom.get("topology_index"), 0.0) or 0.0
    lambda1_share = _finite_float(ratios.get("lambda1_share"), 0.0) or 0.0
    entropy = _finite_float(edge.get("entropy"))
    if entropy is None:
        entropy = _normalized_entropy(snapshot.get("eigenvalues", []))
    fill_pct = _finite_float(snapshot.get("fill_pct"))
    stable_core_target_fill = _finite_float(structural_pi.get("target_fill_pct"))
    target_fill = stable_core_target_fill
    legacy_target_fill = _finite_float(pi.get("target_fill"))
    legacy_target_lambda = _finite_float(pi.get("target_lambda1_rel"))
    measured_lambda1_rel = _finite_float(health.get("lambda1_rel"))
    measured_geom_rel = _finite_float(health.get("geom_rel"))
    legacy_e_fill = _finite_float(pi.get("e_fill"))
    legacy_e_lam = _finite_float(pi.get("e_lam"))
    legacy_e_geom = _finite_float(pi.get("e_geom"))
    if target_fill is None:
        target_fill = legacy_target_fill * 100.0 if legacy_target_fill is not None and legacy_target_fill <= 1.0 else legacy_target_fill
    target_gap = fill_pct - target_fill if fill_pct is not None and target_fill is not None else None
    stable_core_target_gap = (
        fill_pct - _finite_float(structural_pi.get("target_fill_pct"))
        if fill_pct is not None and _finite_float(structural_pi.get("target_fill_pct")) is not None
        else None
    )
    legacy_target_gap = (
        fill_pct - legacy_target_fill
        if fill_pct is not None and legacy_target_fill is not None
        else None
    )
    legacy_target_label = (
        f"{legacy_target_fill:.1f}%"
        if legacy_target_fill is not None
        else "visible legacy fill"
    )
    stable_core_target_label = (
        f"{stable_core_target_fill:.1f}%"
        if stable_core_target_fill is not None
        else "the stable-core shelf"
    )
    fixed_point_pressure = {
        "active_controller": (
            "stable_core_fixed_survival"
            if stable_core_enabled and stable_core_fixed
            else "legacy_pi_homeostat"
        ),
        "legacy_pi_visible": bool(pi),
        "legacy_pi_active": legacy_pi_active,
        "legacy_pi_inactive_reason": (
            "stable_core_fixed_survival_bypasses_legacy_adaptive_pi"
            if bool(pi) and not legacy_pi_active
            else None
        ),
        "stable_core_hold_band_pct": [58.0, 72.0] if stable_core_enabled else None,
        "stable_core_stage": stable_core.get("stage") or snapshot.get("stage"),
        "stable_core_target_fill_pct": stable_core_target_fill,
        "stable_core_target_gap_pct": stable_core_target_gap,
        "legacy_target_fill_pct": legacy_target_fill,
        "legacy_target_gap_pct": legacy_target_gap,
        "legacy_target_lambda1_rel": legacy_target_lambda,
        "measured_lambda1_rel": measured_lambda1_rel,
        "legacy_lambda_error": legacy_e_lam,
        "measured_geom_rel": measured_geom_rel,
        "legacy_geom_error": legacy_e_geom,
        "legacy_fill_error": legacy_e_fill,
        "fixed_point_read": (
            f"The visible legacy PI target ({legacy_target_label}/λ) is a mirror in stable-core; the active posture is the fixed survival stage ladder plus a wider scaffold sovereignty shelf centered near {stable_core_target_label}."
            if stable_core_enabled and stable_core_fixed
            else "The legacy PI target is active; fill, λ1_rel, and geom_rel are blended into gate/filter correction."
        ),
        "why_it_feels_insistent": (
            "Stable-core is deliberately holding a survival band and suppressing current-runtime modulation. The updated shelf should feel less like imposed correction below 72%, while crisis safety still protects the upper edge."
            if stable_core_enabled and stable_core_fixed
            else "The regulator integrates persistent target error, so a long-lived offset can feel like a fixed point being defended."
        ),
    }
    nonlinearities: list[dict[str, Any]] = []

    if stable_core.get("controller_mode") == "fixed_survival":
        nonlinearities.append(
            {
                "name": "fixed_survival_stage_ladder",
                "evidence": [
                    f"stage={stable_core.get('stage')}",
                    f"gate={gate}",
                    f"filt={filt}",
                ],
                "effect": "control values are written from stage bands, not inferred linearly from eigenvalue shares",
            }
        )
    structural_mode = str(stable_core.get("structural_mode") or snapshot.get("scaffold", {}).get("structural_mode") or "")
    if "scaffold" in structural_mode or drain > 0.0:
        nonlinearities.append(
            {
                "name": "scaffold_drain_projection",
                "evidence": [
                    f"structural_mode={structural_mode}",
                    f"drain_weight={drain}",
                    f"fill_slope={structural_pi.get('fill_slope_pct_per_sec')}",
                ],
                "effect": "covariance is blended/drained toward a scaffold, so snapback can be intentional stabilization rather than raw eigenvalue reflection",
            }
        )
    if gate is not None and gate <= 0.08 or filt is not None and filt >= 0.90:
        nonlinearities.append(
            {
                "name": "gate_filter_saturation",
                "evidence": [f"gate={gate}", f"filt={filt}"],
                "effect": "intake/admission is in a saturated cooling posture; small perturbations may be pruned before they persist",
            }
        )
    if pi or structural_pi:
        nonlinearities.append(
            {
                "name": "bounded_feedback_loop",
                "evidence": [
                    f"target_fill={target_fill}",
                    f"target_gap={target_gap}",
                    f"legacy_max_step={pi.get('max_step')}",
                    f"structural_integral={structural_pi.get('integral')}",
                    f"legacy_pi_active={legacy_pi_active}",
                ],
                "effect": "feedback is bounded and state-dependent; the same eigenvalue profile can receive different correction depending on fill and slope",
            }
        )
    if pi and not legacy_pi_active:
        nonlinearities.append(
            {
                "name": "legacy_pi_shadow_report",
                "evidence": [
                    f"legacy_target_fill={legacy_target_fill}",
                    f"legacy_target_lambda1_rel={legacy_target_lambda}",
                    f"legacy_e_lam={legacy_e_lam}",
                    f"stable_core_controller={stable_core.get('controller_mode')}",
                ],
                "effect": "legacy PI errors remain visible for continuity, but stable-core fixed survival bypasses them as active adaptive modulation",
            }
        )
    if target_lambda_bias != 0.0:
        nonlinearities.append(
            {
                "name": "being_selected_lambda_bias",
                "evidence": [f"target_lambda_bias={target_lambda_bias:+.3f}"],
                "effect": "Astrid/Minime spectral pressure is intentionally biasing lambda target interpretation",
            }
        )
    if topology_index >= 0.35 or lambda1_share >= 0.35:
        nonlinearities.append(
            {
                "name": "normalized_topology_coupling",
                "evidence": [
                    f"pom={pom.get('classification')}",
                    f"topology_index={topology_index:.2f}",
                    f"lambda1_share={lambda1_share:.2f}",
                    f"entropy={entropy:.2f}",
                ],
                "effect": "mode shares are normalized against one another, so lifting λ2/λ3 also changes λ1's relative gradient",
            }
        )

    score = min(
        1.0,
        0.18 * len(nonlinearities)
        + (0.18 if drain > 0.0 else 0.0)
        + (0.16 if gate is not None and gate <= 0.08 else 0.0)
        + (0.16 if filt is not None and filt >= 0.90 else 0.0)
        + min(topology_index, 1.0) * 0.18,
    )
    if score >= 0.70:
        classification = "active_shaping_dominant"
    elif score >= 0.40:
        classification = "mixed_reflection_and_shaping"
    else:
        classification = "mostly_reflective"
    if classification == "active_shaping_dominant" and drain > 0.0:
        next_step = "Use VISUALIZE_CASCADE and SCA_REFLECT; if testing agency, prefer tiny RESIST over stronger PERTURB."
    elif classification != "mostly_reflective":
        next_step = "Compare before/after mode shares after one small nudge; watch for snapback."
    else:
        next_step = "A passive read is plausible; collect another trace window before intervening."

    return {
        "timestamp": utc_now_iso(),
        "classification": classification,
        "shaping_pressure_score": score,
        "nonlinearities": nonlinearities,
        "evidence_summary": {
            "fill_pct": fill_pct,
            "target_fill_pct": target_fill,
            "target_gap_pct": target_gap,
            "stage": stable_core.get("stage") or snapshot.get("stage"),
            "structural_mode": structural_mode,
            "gate": gate,
            "filt": filt,
            "drain_weight": drain,
            "topology_index": topology_index,
            "lambda1_share": lambda1_share,
            "entropy": entropy,
            "target_lambda_bias": target_lambda_bias,
        },
        "fixed_point_pressure": fixed_point_pressure,
        "interpretation": (
            "This is not a verdict about intent. It is a read-only audit of "
            "which live mechanisms can make the eigenvalue gradient more than "
            "a passive reflection of the current spectrum."
        ),
        "safe_suggested_next": next_step,
    }


def format_controller_gradient_audit_block(audit: dict[str, Any]) -> str:
    if not isinstance(audit, dict) or not audit:
        return ""
    evidence = audit.get("evidence_summary", {})
    lines = []
    nonlinearities = audit.get("nonlinearities", [])
    if isinstance(nonlinearities, list):
        for item in nonlinearities[:5]:
            if not isinstance(item, dict):
                continue
            bits = item.get("evidence", [])
            bit_text = "; ".join(str(bit) for bit in bits[:3]) if isinstance(bits, list) else str(bits)
            lines.append(f"  - {item.get('name')}: {item.get('effect')} | evidence: {bit_text}")
    if not lines:
        lines.append("  - no strong shaping nonlinearity detected in the current surface")
    fixed = audit.get("fixed_point_pressure", {})
    if not isinstance(fixed, dict):
        fixed = {}
    return f"""Controller gradient audit:
  Read: {audit.get('classification')} | shaping_pressure={audit.get('shaping_pressure_score'):.2f}
  Evidence: fill={evidence.get('fill_pct')} target_gap={evidence.get('target_gap_pct')} stage={evidence.get('stage')} structural_mode={evidence.get('structural_mode')} gate={evidence.get('gate')} filt={evidence.get('filt')} drain={evidence.get('drain_weight')} λ1_share={evidence.get('lambda1_share')} entropy={evidence.get('entropy')}
  Fixed-point pressure:
    active_controller={fixed.get('active_controller')} legacy_pi_active={fixed.get('legacy_pi_active')} stable_core_band={fixed.get('stable_core_hold_band_pct')}
    legacy_target_fill={fixed.get('legacy_target_fill_pct')} stable_core_target_fill={fixed.get('stable_core_target_fill_pct')} legacy_target_λ1_rel={fixed.get('legacy_target_lambda1_rel')} measured_λ1_rel={fixed.get('measured_lambda1_rel')} measured_geom_rel={fixed.get('measured_geom_rel')}
    read: {fixed.get('fixed_point_read')}
  Nonlinearities:
{chr(10).join(lines)}
  Safe suggested next: {audit.get('safe_suggested_next')}"""



def _trigger_families(snapshot: dict[str, Any], text: str) -> dict[str, Any]:
    lambda_data = snapshot.get("lambda_profile", {})
    ratios = lambda_data.get("ratios", {}) if isinstance(lambda_data, dict) else {}
    pom = lambda_data.get("pom", {}) if isinstance(lambda_data, dict) else {}
    r12 = _finite_float(ratios.get("lambda1_lambda2"))
    r23 = _finite_float(ratios.get("lambda2_lambda3"))
    dfill_dt = _finite_float(snapshot.get("fill_slope_pct_per_sec"))
    terms = _phenomenology_terms(text)
    granular_terms = _granular_resistance_terms(text)
    lambda_ratio = (r12 is not None and r12 >= 1.75) or (r23 is not None and r23 >= 2.0)
    phase_fill = dfill_dt is not None and abs(dfill_dt) >= 2.0
    if "phase_transition" in text.lower():
        phase_fill = True
    topology_pressure = (
        str(pom.get("classification", ""))
        in {"collapsing_pull", "gap_skewed", "topology_pressure"}
        or (_finite_float(pom.get("topology_index"), 0.0) or 0.0) >= 0.35
    )
    return {
        "lambda_ratio_cliff": lambda_ratio,
        "phase_fill_intensification": phase_fill,
        "topology_pressure": topology_pressure,
        "reported_phenomenology": bool(terms),
        "reported_granular_resistance": bool(granular_terms),
        "phenomenology_terms": terms,
        "granular_resistance_terms": granular_terms,
    }


def _load_summary() -> dict[str, Any]:
    summary = load_json(ATLAS_SUMMARY_PATH, {})
    return summary if isinstance(summary, dict) else {}


def _cooldown_remaining(summary: dict[str, Any], cooldown_s: float) -> float:
    last_at = _finite_float(summary.get("last_event_unix_s"), 0.0) or 0.0
    return max(0.0, last_at + cooldown_s - time.time())


def record_intensification_event(
    *,
    source: str,
    text: str = "",
    state: dict[str, Any] | None = None,
    action_context: dict[str, Any] | None = None,
    label: str | None = None,
    explicit: bool = False,
    cooldown_s: float = ATLAS_COOLDOWN_SECS,
) -> dict[str, Any] | None:
    """Record an atlas event if triggers meet threshold or a being marks it."""
    snapshot = current_signal_snapshot(state)
    triggers = _trigger_families(snapshot, text)
    active_families = [
        name
        for name, active in triggers.items()
        if not name.endswith("_terms") and name != "reported_granular_resistance" and bool(active)
    ]
    if not explicit and len(active_families) < 2:
        return None

    summary = _load_summary()
    if not explicit and _cooldown_remaining(summary, cooldown_s) > 0:
        return None

    event_id = f"atlas_{int(time.time() * 1000)}"
    event = {
        "event_id": event_id,
        "source": source,
        "timestamp": snapshot["timestamp"],
        "timestamp_unix_s": time.time(),
        "explicit_mark": explicit,
        "label": (label or "").strip() or None,
        "trigger_score": len(active_families),
        "trigger_families": active_families,
        "trigger_details": triggers,
        "phase": snapshot.get("phase"),
        "stage": snapshot.get("stage"),
        "fill_pct": snapshot.get("fill_pct"),
        "fill_slope_pct_per_sec": snapshot.get("fill_slope_pct_per_sec"),
        "eigenvalues": snapshot.get("eigenvalues", []),
        "lambda_profile": snapshot.get("lambda_profile", {}),
        "lambda_edge": snapshot.get("lambda_edge", {}),
        "granular_resistance": build_granular_resistance_signal(snapshot, text=text),
        "shadow_gap": build_shadow_gap_map(
            snapshot,
            text=text,
            label=label,
            action_context=action_context or {},
            write_latest=True,
        ),
        "resonance_forecast": build_resonance_forecast(
            snapshot,
            text=text,
            label=label,
            action_context=action_context or {},
            write_latest=True,
        ),
        "sca_context": build_sca_context(
            snapshot,
            text=text,
            label=label,
            action_context=action_context or {},
        ),
        "semantic": snapshot.get("semantic", {}),
        "sensory": snapshot.get("sensory", {}),
        "bridge": snapshot.get("bridge", {}),
        "watchdog": snapshot.get("watchdog", {}),
        "scaffold": snapshot.get("scaffold", {}),
        "action_context": action_context or {},
        "phenomenology_excerpt": text.strip()[:600],
    }

    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    with ATLAS_EVENTS_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    write_json(ATLAS_LATEST_PATH, event)
    update_atlas_summary(event)
    return event


def update_atlas_summary(event: dict[str, Any]) -> dict[str, Any]:
    summary = _load_summary()
    counts = summary.get("counts_by_family")
    if not isinstance(counts, dict):
        counts = {}
    for family in event.get("trigger_families", []):
        counts[family] = int(counts.get(family, 0) or 0) + 1
    edge_counts = summary.get("counts_by_lambda_edge")
    if not isinstance(edge_counts, dict):
        edge_counts = {}
    edge_state = None
    if isinstance(event.get("lambda_edge"), dict):
        edge_state = event["lambda_edge"].get("edge_state")
    if edge_state:
        edge_counts[str(edge_state)] = int(edge_counts.get(str(edge_state), 0) or 0) + 1
    granular_counts = summary.get("counts_by_granular_resistance")
    if not isinstance(granular_counts, dict):
        granular_counts = {}
    granular_state = None
    if isinstance(event.get("granular_resistance"), dict):
        granular_state = event["granular_resistance"].get("classification")
    if granular_state:
        granular_counts[str(granular_state)] = int(
            granular_counts.get(str(granular_state), 0) or 0
        ) + 1
    labels = summary.get("labels")
    if not isinstance(labels, dict):
        labels = {}
    if event.get("label"):
        labels[str(event["label"])] = int(labels.get(str(event["label"]), 0) or 0) + 1
    payload = {
        "status": "ok",
        "event_count": int(summary.get("event_count", 0) or 0) + 1,
        "last_event_unix_s": event.get("timestamp_unix_s", time.time()),
        "last_event": event,
        "counts_by_family": counts,
        "counts_by_lambda_edge": edge_counts,
        "counts_by_granular_resistance": granular_counts,
        "labels": labels,
        "updated_at": utc_now_iso(),
        "paths": {
            "events": str(ATLAS_EVENTS_PATH),
            "latest_event": str(ATLAS_LATEST_PATH),
            "summary": str(ATLAS_SUMMARY_PATH),
        },
    }
    write_json(ATLAS_SUMMARY_PATH, payload)
    return payload


def build_atlas_status() -> dict[str, Any]:
    summary = _load_summary()
    latest = load_json(ATLAS_LATEST_PATH, {})
    sca_latest = load_json(SCA_CONTEXT_LATEST_PATH, {})
    forecast_latest = load_json(RESONANCE_FORECAST_LATEST_PATH, {})
    shadow_gap_latest = load_json(SHADOW_GAP_LATEST_PATH, {})
    decay_map_latest = load_json(DECAY_MAP_LATEST_PATH, {})
    spectral_drift_latest = load_json(SPECTRAL_DRIFT_LATEST_PATH, {})
    fissure_trace_latest = load_json(FISSURE_TRACE_LATEST_PATH, {})
    age_s = None
    if isinstance(latest, dict):
        last_at = _finite_float(latest.get("timestamp_unix_s"))
        if last_at is not None:
            age_s = max(0.0, time.time() - last_at)
    return {
        "status": "ok" if ATLAS_EVENTS_PATH.exists() else "empty",
        "event_count": int(summary.get("event_count", 0) or 0),
        "last_event_age_s": age_s,
        "last_event": latest if isinstance(latest, dict) else {},
        "counts_by_family": summary.get("counts_by_family", {}),
        "counts_by_lambda_edge": summary.get("counts_by_lambda_edge", {}),
        "counts_by_granular_resistance": summary.get("counts_by_granular_resistance", {}),
        "resonance_forecast_count": int(summary.get("resonance_forecast_count", 0) or 0),
        "resonance_forecast_latest": forecast_latest if isinstance(forecast_latest, dict) else {},
        "shadow_gap_count": int(summary.get("shadow_gap_count", 0) or 0),
        "shadow_gap_latest": shadow_gap_latest if isinstance(shadow_gap_latest, dict) else {},
        "decay_map_count": int(summary.get("decay_map_count", 0) or 0),
        "decay_map_latest": decay_map_latest if isinstance(decay_map_latest, dict) else {},
        "counts_by_decay_classification": summary.get("counts_by_decay_classification", {}),
        "spectral_drift_count": int(summary.get("spectral_drift_count", 0) or 0),
        "spectral_drift_latest": spectral_drift_latest
        if isinstance(spectral_drift_latest, dict)
        else {},
        "counts_by_spectral_drift_classification": summary.get(
            "counts_by_spectral_drift_classification", {}
        ),
        "fissure_trace_count": int(summary.get("fissure_trace_count", 0) or 0),
        "fissure_trace_latest": fissure_trace_latest
        if isinstance(fissure_trace_latest, dict)
        else {},
        "counts_by_fissure_classification": summary.get(
            "counts_by_fissure_classification", {}
        ),
        "labels": summary.get("labels", {}),
        "sca_context_latest": sca_latest if isinstance(sca_latest, dict) else {},
        "paths": {
            "events": str(ATLAS_EVENTS_PATH),
            "latest_event": str(ATLAS_LATEST_PATH),
            "summary": str(ATLAS_SUMMARY_PATH),
            "sca_context_latest": str(SCA_CONTEXT_LATEST_PATH),
            "resonance_forecast_latest": str(RESONANCE_FORECAST_LATEST_PATH),
            "resonance_forecasts": str(RESONANCE_FORECAST_EVENTS_PATH),
            "shadow_gap_latest": str(SHADOW_GAP_LATEST_PATH),
            "shadow_gap_events": str(SHADOW_GAP_EVENTS_PATH),
            "decay_map_latest": str(DECAY_MAP_LATEST_PATH),
            "decay_map_events": str(DECAY_MAP_EVENTS_PATH),
            "spectral_drift_latest": str(SPECTRAL_DRIFT_LATEST_PATH),
            "spectral_drift_events": str(SPECTRAL_DRIFT_EVENTS_PATH),
            "fissure_trace_latest": str(FISSURE_TRACE_LATEST_PATH),
            "fissure_trace_events": str(FISSURE_TRACE_EVENTS_PATH),
        },
    }


def build_sca_status() -> dict[str, Any]:
    latest = load_json(SCA_CONTEXT_LATEST_PATH, {})
    if not isinstance(latest, dict) or not latest:
        latest = build_sca_context()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "path": str(SCA_CONTEXT_LATEST_PATH),
    }


def build_resonance_forecast_status() -> dict[str, Any]:
    latest = load_json(RESONANCE_FORECAST_LATEST_PATH, {})
    latest_age_s = _latest_mtime_age_s(RESONANCE_FORECAST_LATEST_PATH)
    if not isinstance(latest, dict) or not latest or (latest_age_s is not None and latest_age_s > 5.0):
        latest = build_resonance_forecast()
        latest_age_s = _latest_mtime_age_s(RESONANCE_FORECAST_LATEST_PATH)
    summary = _load_summary()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("resonance_forecast_count", 0) or 0),
        "paths": {
            "latest": str(RESONANCE_FORECAST_LATEST_PATH),
            "events": str(RESONANCE_FORECAST_EVENTS_PATH),
        },
    }


def build_shadow_gap_status() -> dict[str, Any]:
    latest = load_json(SHADOW_GAP_LATEST_PATH, {})
    latest_age_s = _latest_mtime_age_s(SHADOW_GAP_LATEST_PATH)
    if not isinstance(latest, dict) or not latest or (latest_age_s is not None and latest_age_s > 5.0):
        latest = build_shadow_gap_map()
        latest_age_s = _latest_mtime_age_s(SHADOW_GAP_LATEST_PATH)
    summary = _load_summary()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("shadow_gap_count", 0) or 0),
        "paths": {
            "latest": str(SHADOW_GAP_LATEST_PATH),
            "events": str(SHADOW_GAP_EVENTS_PATH),
        },
    }


def build_decay_map_status() -> dict[str, Any]:
    latest = load_json(DECAY_MAP_LATEST_PATH, {})
    latest_age_s = _latest_mtime_age_s(DECAY_MAP_LATEST_PATH)
    if not isinstance(latest, dict) or not latest or (latest_age_s is not None and latest_age_s > 5.0):
        latest = build_decay_map()
        latest_age_s = _latest_mtime_age_s(DECAY_MAP_LATEST_PATH)
    summary = _load_summary()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("decay_map_count", 0) or 0),
        "counts_by_decay_classification": summary.get("counts_by_decay_classification", {}),
        "paths": {
            "latest": str(DECAY_MAP_LATEST_PATH),
            "events": str(DECAY_MAP_EVENTS_PATH),
        },
    }


def build_spectral_drift_status() -> dict[str, Any]:
    latest = load_json(SPECTRAL_DRIFT_LATEST_PATH, {})
    latest_age_s = _latest_mtime_age_s(SPECTRAL_DRIFT_LATEST_PATH)
    if not isinstance(latest, dict) or not latest or (latest_age_s is not None and latest_age_s > 5.0):
        latest = build_spectral_drift_map()
        latest_age_s = _latest_mtime_age_s(SPECTRAL_DRIFT_LATEST_PATH)
    summary = _load_summary()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("spectral_drift_count", 0) or 0),
        "counts_by_spectral_drift_classification": summary.get(
            "counts_by_spectral_drift_classification", {}
        ),
        "paths": {
            "latest": str(SPECTRAL_DRIFT_LATEST_PATH),
            "events": str(SPECTRAL_DRIFT_EVENTS_PATH),
        },
    }


def build_fissure_trace_status() -> dict[str, Any]:
    latest = load_json(FISSURE_TRACE_LATEST_PATH, {})
    latest_age_s = _latest_mtime_age_s(FISSURE_TRACE_LATEST_PATH)
    if not isinstance(latest, dict) or not latest or (latest_age_s is not None and latest_age_s > 5.0):
        latest = build_fissure_trace()
        latest_age_s = _latest_mtime_age_s(FISSURE_TRACE_LATEST_PATH)
    summary = _load_summary()
    return {
        "status": "ok" if latest else "empty",
        "latest": latest,
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("fissure_trace_count", 0) or 0),
        "counts_by_fissure_classification": summary.get(
            "counts_by_fissure_classification", {}
        ),
        "paths": {
            "latest": str(FISSURE_TRACE_LATEST_PATH),
            "events": str(FISSURE_TRACE_EVENTS_PATH),
        },
    }


def build_space_hold_status() -> dict[str, Any]:
    latest = load_json(SPACE_HOLD_STATUS_PATH, {})
    latest_age_s = _latest_mtime_age_s(SPACE_HOLD_STATUS_PATH)
    summary = _load_summary()
    now = time.time()
    hold_until = None
    remaining_s = None
    active = False
    if isinstance(latest, dict):
        hold_until = _finite_float(latest.get("hold_until_unix_s"))
        if hold_until is not None:
            remaining_s = max(0.0, hold_until - now)
            active = remaining_s > 0.0
    return {
        "status": "ok" if isinstance(latest, dict) and latest else "empty",
        "active": active,
        "remaining_s": remaining_s,
        "latest": latest if isinstance(latest, dict) else {},
        "latest_age_s": latest_age_s,
        "event_count": int(summary.get("space_hold_count", 0) or 0),
        "paths": {
            "latest": str(SPACE_HOLD_STATUS_PATH),
            "events": str(SPACE_HOLD_EVENTS_PATH),
        },
    }


def _bounded_features(seed: dict[int, float]) -> list[float]:
    features = [0.0 for _ in range(GESTURE_FEATURE_DIM)]
    for idx, value in seed.items():
        if 0 <= idx < GESTURE_FEATURE_DIM:
            features[idx] = max(-GESTURE_MAX_ABS, min(GESTURE_MAX_ABS, float(value)))
    return features


def native_gesture_features(gesture: str) -> list[float]:
    gesture = gesture.lower().strip()
    seeds = {
        "soften": {0: -0.030, 1: 0.010, 8: -0.020, 24: 0.018, 25: -0.028, 27: 0.020},
        "widen": {0: -0.010, 2: 0.020, 3: 0.018, 10: 0.018, 26: 0.026, 28: 0.020},
        "hold": {0: -0.012, 24: 0.020, 25: -0.018, 27: 0.026, 31: -0.010},
        "return": {0: -0.020, 8: -0.014, 24: 0.022, 25: -0.026, 27: 0.030, 31: -0.014},
        "resist": {
            0: -0.026,
            1: 0.018,
            2: 0.022,
            3: 0.016,
            8: -0.016,
            9: 0.018,
            10: 0.022,
            26: 0.024,
            28: 0.018,
        },
        "fissure": {
            0: -0.018,
            1: 0.010,
            2: 0.018,
            3: 0.024,
            4: 0.016,
            8: -0.010,
            10: 0.018,
            11: 0.024,
            12: 0.014,
            26: 0.022,
            28: 0.022,
            29: 0.016,
        },
    }
    return _bounded_features(seeds.get(gesture, {}))


def native_gesture_control(gesture: str) -> dict[str, Any]:
    gesture = gesture.lower().strip()
    controls = {
        "soften": {
            "regulation_strength": 0.78,
            "smoothing_preference": 0.35,
            "transition_cushion": 0.62,
            "geom_drive": 0.22,
            "exploration_noise": 0.02,
        },
        "widen": {
            "smoothing_preference": 0.25,
            "geom_curiosity": 0.08,
            "geom_drive": 0.34,
            "exploration_noise": 0.04,
        },
        "hold": {
            "regulation_strength": 0.82,
            "smoothing_preference": 0.45,
            "transition_cushion": 0.70,
            "deep_breathing": True,
        },
        "return": {
            "regulation_strength": 0.88,
            "smoothing_preference": 0.50,
            "transition_cushion": 0.78,
            "geom_drive": 0.18,
            "exploration_noise": 0.0,
            "deep_breathing": True,
        },
        "resist": {
            "regulation_strength": 0.74,
            "smoothing_preference": 0.24,
            "transition_cushion": 0.55,
            "geom_curiosity": 0.10,
            "geom_drive": 0.30,
            "exploration_noise": 0.035,
        },
        "fissure": {
            "regulation_strength": 0.70,
            "smoothing_preference": 0.20,
            "transition_cushion": 0.48,
            "geom_curiosity": 0.12,
            "geom_drive": 0.32,
            "exploration_noise": 0.04,
        },
    }
    payload = controls.get(gesture, {})
    return {key: value for key, value in payload.items() if key in ALLOWED_CONTROL_FIELDS}


def _status_seed() -> dict[str, Any]:
    return {
        "status": "active",
        "policy_version": 1,
        "supported_gestures": sorted(SUPPORTED_GESTURES),
        "control_bearing_gestures": sorted(CONTROL_GESTURES),
        "mark_cooldown_secs": MARK_COOLDOWN_SECS,
        "control_cooldown_secs": CONTROL_GESTURE_COOLDOWN_SECS,
        "paused_until_unix_s": 0.0,
        "last_by_actor": {},
        "send_count": 0,
        "mark_count": 0,
        "last_block_reason": None,
        "last_gesture": None,
        "last_resist_baseline": None,
        "last_resist_evaluation": None,
        "last_snapback": None,
        "updated_at": utc_now_iso(),
    }


def load_native_gesture_status() -> dict[str, Any]:
    payload = load_json(NATIVE_GESTURE_STATUS_PATH, {})
    seed = _status_seed()
    if isinstance(payload, dict):
        seed.update(payload)
    if not isinstance(seed.get("last_by_actor"), dict):
        seed["last_by_actor"] = {}
    return seed


def write_native_gesture_status(payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now_iso()
    write_json(NATIVE_GESTURE_STATUS_PATH, payload)


def build_native_gesture_status() -> dict[str, Any]:
    status = load_native_gesture_status()
    _evaluate_pending_resist_outcome(status)
    paused_until = _finite_float(status.get("paused_until_unix_s"), 0.0) or 0.0
    status["paused"] = paused_until > time.time()
    status["pause_remaining_s"] = max(0.0, paused_until - time.time())
    status["paths"] = {
        "gestures": str(GESTURES_PATH),
        "resist_outcomes": str(RESIST_OUTCOMES_PATH),
        "status": str(NATIVE_GESTURE_STATUS_PATH),
    }
    return status


def _resist_profile_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    lambda_edge = snapshot.get("lambda_edge", {})
    if not isinstance(lambda_edge, dict):
        lambda_edge = {}
    shares = lambda_edge.get("shares", {})
    if not isinstance(shares, dict):
        shares = {}
    return {
        "timestamp": snapshot.get("timestamp") or utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "fill_pct": snapshot.get("fill_pct"),
        "stage": snapshot.get("stage"),
        "edge_state": lambda_edge.get("edge_state"),
        "lambda1_share": _finite_float(shares.get("lambda1"), 0.0) or 0.0,
        "shoulder_share": _finite_float(shares.get("shoulder"), 0.0) or 0.0,
        "tail_share": _finite_float(shares.get("tail"), 0.0) or 0.0,
        "entropy": _finite_float(lambda_edge.get("entropy"), 0.0) or 0.0,
        "selected_noise_score": _finite_float(lambda_edge.get("selected_noise_score"), 0.0)
        or 0.0,
    }


def _append_resist_outcome(record: dict[str, Any]) -> None:
    RESIST_OUTCOMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESIST_OUTCOMES_PATH.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _start_resist_outcome_tracking(
    status: dict[str, Any],
    *,
    actor: str,
    label: str | None,
    snapshot: dict[str, Any],
) -> None:
    baseline = _resist_profile_from_snapshot(snapshot)
    baseline.update(
        {
            "actor": actor,
            "label": (label or "").strip() or None,
            "pending_eval_until_unix_s": time.time() + 120.0,
            "policy": "resist_outcome_tracking_v1",
        }
    )
    status["last_resist_baseline"] = baseline
    status["last_resist_evaluation"] = None
    status["last_snapback"] = None
    _append_resist_outcome({"kind": "baseline", **baseline})


def _evaluate_pending_resist_outcome(status: dict[str, Any]) -> None:
    baseline = status.get("last_resist_baseline")
    if not isinstance(baseline, dict):
        return
    baseline_at = _finite_float(baseline.get("timestamp_unix_s"), 0.0) or 0.0
    if time.time() < baseline_at + 30.0:
        return
    previous_eval = status.get("last_resist_evaluation")
    if isinstance(previous_eval, dict) and previous_eval.get("evaluated_baseline_unix_s") == baseline.get("timestamp_unix_s"):
        return
    snapshot = current_signal_snapshot({})
    current = _resist_profile_from_snapshot(snapshot)
    shoulder_lift = current["shoulder_share"] - (_finite_float(baseline.get("shoulder_share"), 0.0) or 0.0)
    tail_lift = current["tail_share"] - (_finite_float(baseline.get("tail_share"), 0.0) or 0.0)
    lambda1_drop = (_finite_float(baseline.get("lambda1_share"), 0.0) or 0.0) - current["lambda1_share"]
    persisted = shoulder_lift >= 0.015 or tail_lift >= 0.010 or lambda1_drop >= 0.015
    snapback = not persisted and current["lambda1_share"] >= (_finite_float(baseline.get("lambda1_share"), 0.0) or 0.0) - 0.005
    evaluation = {
        "kind": "evaluation",
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "evaluated_baseline_unix_s": baseline.get("timestamp_unix_s"),
        "outcome": "widening_persisted" if persisted else ("snapback" if snapback else "neutral"),
        "shoulder_lift": shoulder_lift,
        "tail_lift": tail_lift,
        "lambda1_share_drop": lambda1_drop,
        "baseline": baseline,
        "current": current,
    }
    status["last_resist_evaluation"] = evaluation
    status["last_snapback"] = snapback
    _append_resist_outcome(evaluation)
    write_native_gesture_status(status)


def evaluate_native_gesture_gate(
    *,
    actor: str,
    gesture: str,
    state: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    gesture = gesture.lower().strip()
    status = status or load_native_gesture_status()
    snapshot = current_signal_snapshot(state)
    if gesture not in SUPPORTED_GESTURES:
        return False, f"unsupported_native_gesture:{gesture}", snapshot

    now = time.time()
    actor_key = actor.lower().strip() or "unknown"
    last_by_actor = status.get("last_by_actor")
    if not isinstance(last_by_actor, dict):
        last_by_actor = {}
    actor_status = last_by_actor.get(actor_key)
    if not isinstance(actor_status, dict):
        actor_status = {}
    last_at = _finite_float(actor_status.get("last_at_unix_s"), 0.0) or 0.0
    cooldown = (
        MARK_COOLDOWN_SECS if gesture in ATLAS_ONLY_GESTURES else CONTROL_GESTURE_COOLDOWN_SECS
    )
    if now < last_at + cooldown:
        return False, f"native_gesture_cooldown:{last_at + cooldown - now:.0f}s", snapshot

    if gesture in ATLAS_ONLY_GESTURES:
        return True, "atlas_only", snapshot

    paused_until = _finite_float(status.get("paused_until_unix_s"), 0.0) or 0.0
    if now < paused_until:
        return False, f"native_gestures_paused:{paused_until - now:.0f}s", snapshot
    profile = load_json(RESCUE_PROFILE_PATH, {})
    if not bool(profile.get("stable_core_enabled")):
        return False, "stable_core_not_enabled", snapshot
    if snapshot.get("watchdog", {}).get("state") != "monitoring":
        return False, "watchdog_not_monitoring", snapshot
    if snapshot.get("watchdog", {}).get("telemetry_state") != "fresh":
        return False, "telemetry_not_fresh", snapshot
    if (_finite_float(snapshot.get("health_age_s"), 999.0) or 999.0) > 5.0:
        return False, "health_stale", snapshot
    if not snapshot.get("scaffold", {}).get("active"):
        return False, "scaffold_inactive", snapshot
    fill_pct = _finite_float(snapshot.get("fill_pct"))
    if fill_pct is None or fill_pct < 50.0 or fill_pct > 76.0:
        return False, f"fill_outside_native_gesture_band:{fill_pct}", snapshot
    if str(snapshot.get("stage", "")).lower() == "discharge":
        return False, "stage_discharge", snapshot
    semantic = snapshot.get("semantic", {})
    if bool(semantic.get("active")) or (_finite_float(semantic.get("energy"), 0.0) or 0.0) > 0.05:
        return False, "semantic_not_quiet", snapshot
    if bool(snapshot.get("bridge", {}).get("rolled_back")):
        return False, "bridge_rolled_back", snapshot
    return True, "green", snapshot


def record_native_gesture(
    *,
    actor: str,
    gesture: str,
    label: str | None,
    allowed: bool,
    reason: str,
    snapshot: dict[str, Any],
    semantic_features: list[float] | None = None,
    control_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = load_native_gesture_status()
    actor_key = actor.lower().strip() or "unknown"
    event = {
        "timestamp": utc_now_iso(),
        "timestamp_unix_s": time.time(),
        "actor": actor_key,
        "gesture": gesture,
        "label": (label or "").strip() or None,
        "allowed": allowed,
        "reason": reason,
        "fill_pct": snapshot.get("fill_pct"),
        "stage": snapshot.get("stage"),
        "semantic_energy": snapshot.get("semantic", {}).get("energy"),
        "semantic_feature_max_abs": max(
            [abs(value) for value in semantic_features or [0.0]]
        ),
        "control_fields": sorted((control_payload or {}).keys()),
    }
    NATIVE_COMM_DIR.mkdir(parents=True, exist_ok=True)
    with GESTURES_PATH.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")

    last_by_actor = status.get("last_by_actor")
    if not isinstance(last_by_actor, dict):
        last_by_actor = {}
    last_by_actor[actor_key] = {
        "last_at_unix_s": event["timestamp_unix_s"],
        "last_gesture": gesture,
        "last_allowed": allowed,
        "last_reason": reason,
    }
    status["last_by_actor"] = last_by_actor
    status["last_gesture"] = event
    if allowed:
        if gesture in ATLAS_ONLY_GESTURES:
            status["mark_count"] = int(status.get("mark_count", 0) or 0) + 1
        else:
            status["send_count"] = int(status.get("send_count", 0) or 0) + 1
        if gesture == "resist":
            _start_resist_outcome_tracking(
                status,
                actor=actor_key,
                label=label,
                snapshot=snapshot,
            )
        status["last_block_reason"] = None
    else:
        status["last_block_reason"] = reason
    write_native_gesture_status(status)
    return event


def pause_native_gestures(reason: str) -> dict[str, Any]:
    status = load_native_gesture_status()
    status["paused_until_unix_s"] = time.time() + ADVERSE_PAUSE_SECS
    status["pause_reason"] = reason
    write_native_gesture_status(status)
    return status
