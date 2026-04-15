"""Helpers for provenance-aware reporting snapshots.

The agent used to compose reports from a mix of DB state, live health.json,
and later spectral_state.json reads without checking whether they described the
same session or moment. This module centralizes path resolution, normalization,
and provenance guards so reporting can refuse mixed-state snapshots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

MAX_SNAPSHOT_SKEW_S = 2.0


def resolve_runtime_db_path(base_dir: Path) -> Path:
    """Prefer the active runtime DB in the repo root, then fall back to legacy."""
    primary = base_dir / "minime_consciousness.db"
    legacy = base_dir / "minime" / "minime_consciousness.db"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def candidate_workspace_paths(base_dir: Path, workspace_dir: Path, name: str) -> Iterable[Path]:
    """Yield workspace file candidates in priority order."""
    yield workspace_dir / name
    yield base_dir / "minime" / "workspace" / name


def load_workspace_json(base_dir: Path, workspace_dir: Path, name: str) -> Dict[str, Any]:
    """Load one workspace JSON surface, preferring the active root workspace."""
    for path in candidate_workspace_paths(base_dir, workspace_dir, name):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def normalize_spectral_state(surface: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in convenience keys expected by older reporting code."""
    normalized = dict(surface or {})
    fill_pct = normalized.get("fill_pct")
    if "fill_ratio" not in normalized and isinstance(fill_pct, (int, float)):
        normalized["fill_ratio"] = float(fill_pct) / 100.0
    if "eig1" not in normalized:
        eigenvalues = normalized.get("eigenvalues")
        if isinstance(eigenvalues, list) and eigenvalues:
            first = eigenvalues[0]
            if isinstance(first, (int, float)):
                normalized["eig1"] = float(first)
    return normalized


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _extract_provenance(surface: Dict[str, Any]) -> Dict[str, Any]:
    raw = surface.get("provenance")
    if not isinstance(raw, dict):
        return {}
    sovereignty_inputs = raw.get("sovereignty_inputs")
    if not isinstance(sovereignty_inputs, dict):
        sovereignty_inputs = {}
    target_provenance = raw.get("target_provenance")
    return {
        "session_id": _coerce_int(raw.get("session_id")),
        "wall_clock_unix_ms": _coerce_int(raw.get("wall_clock_unix_ms")),
        "engine_t_s": _coerce_float(raw.get("engine_t_s")),
        "snapshot_sequence": _coerce_int(raw.get("snapshot_sequence")),
        "target_provenance": target_provenance if isinstance(target_provenance, str) else None,
        "sovereignty_inputs": sovereignty_inputs,
    }


def _surface_label(surface_name: str) -> str:
    if surface_name == "health":
        return "health.json"
    if surface_name == "spectral":
        return "spectral_state.json"
    return surface_name


@dataclass(frozen=True)
class SurfaceSnapshot:
    name: str
    data: Dict[str, Any]
    provenance: Dict[str, Any]
    valid_for_state: bool
    issues: Tuple[str, ...]

    def short_label(self) -> str:
        seq = self.provenance.get("snapshot_sequence")
        engine_t_s = self.provenance.get("engine_t_s")
        label = _surface_label(self.name)
        if seq is not None:
            label += f"#{seq}"
        if engine_t_s is not None:
            label += f"@{engine_t_s:.1f}s"
        return label


@dataclass(frozen=True)
class ReportSnapshot:
    session_id: Optional[int]
    state_timestamp: Optional[float]
    state: Dict[str, Any]
    health: SurfaceSnapshot
    spectral: SurfaceSnapshot

    @property
    def issues(self) -> Tuple[str, ...]:
        return self.health.issues + self.spectral.issues

    @property
    def target_provenance(self) -> Optional[str]:
        return self.health.provenance.get("target_provenance") or self.spectral.provenance.get(
            "target_provenance"
        )


def _evaluate_surface(
    *,
    name: str,
    data: Dict[str, Any],
    session_id: Optional[int],
    state_timestamp: Optional[float],
) -> SurfaceSnapshot:
    label = _surface_label(name)
    if not data:
        return SurfaceSnapshot(
            name=name,
            data={},
            provenance={},
            valid_for_state=False,
            issues=(f"{label} unavailable",),
        )

    provenance = _extract_provenance(data)
    if not provenance:
        return SurfaceSnapshot(
            name=name,
            data=data,
            provenance={},
            valid_for_state=False,
            issues=(f"{label} missing provenance block",),
        )

    issues = []
    valid = True
    surface_session = provenance.get("session_id")
    if surface_session is not None and session_id is not None and surface_session != session_id:
        if surface_session < session_id:
            # Data from an older session — genuinely stale, reject
            issues.append(
                f"{label} session mismatch: surface session {surface_session}, expected {session_id}"
            )
            valid = False
        else:
            # Data from a newer session — fresher than agent's view, accept with note
            issues.append(
                f"{label} session advanced: surface session {surface_session}, agent has {session_id}"
            )

    surface_t_s = provenance.get("engine_t_s")
    if surface_t_s is None:
        issues.append(f"{label} missing engine-relative timestamp")
        valid = False
    elif state_timestamp is not None:
        skew_s = float(surface_t_s) - float(state_timestamp)
        if abs(skew_s) > MAX_SNAPSHOT_SKEW_S:
            direction = "later" if skew_s > 0 else "earlier"
            issues.append(
                f"{label} is {direction} than DB state by {abs(skew_s):.1f}s"
            )
            valid = False

    return SurfaceSnapshot(
        name=name,
        data=data,
        provenance=provenance,
        valid_for_state=valid,
        issues=tuple(issues),
    )


def capture_report_snapshot(
    *,
    state: Dict[str, Any],
    session_id: Optional[int],
    base_dir: Path,
    workspace_dir: Path,
) -> ReportSnapshot:
    """Capture one provenance-checked reporting snapshot."""
    normalized_state = dict(state or {})
    state_timestamp = _coerce_float(normalized_state.get("timestamp"))
    health = load_workspace_json(base_dir, workspace_dir, "health.json")
    spectral = normalize_spectral_state(
        load_workspace_json(base_dir, workspace_dir, "spectral_state.json")
    )
    return ReportSnapshot(
        session_id=session_id,
        state_timestamp=state_timestamp,
        state=normalized_state,
        health=_evaluate_surface(
            name="health",
            data=health,
            session_id=session_id,
            state_timestamp=state_timestamp,
        ),
        spectral=_evaluate_surface(
            name="spectral",
            data=spectral,
            session_id=session_id,
            state_timestamp=state_timestamp,
        ),
    )


def format_snapshot_summary(snapshot: ReportSnapshot) -> str:
    """Render one compact provenance line for journal/report headers."""
    state_bits = [f"session {snapshot.session_id if snapshot.session_id is not None else '?'}"]
    if snapshot.state_timestamp is not None:
        state_bits.append(f"db@{snapshot.state_timestamp:.1f}s")
    summary = [f"Snapshot: {' '.join(state_bits)}"]

    for surface in (snapshot.health, snapshot.spectral):
        status = "ok" if surface.valid_for_state else "omitted"
        summary.append(f"{surface.short_label()} {status}")

    if snapshot.target_provenance:
        summary.append(f"target={snapshot.target_provenance}")
    if snapshot.issues:
        summary.append(f"guard={snapshot.issues[0]}")
    return " | ".join(summary)


def format_snapshot_provenance(snapshot: ReportSnapshot) -> str:
    """Render a multiline provenance block for richer reports."""
    lines = ["Snapshot provenance:"]
    if snapshot.state_timestamp is None:
        lines.append(
            f"  DB state: session {snapshot.session_id if snapshot.session_id is not None else '?'}"
        )
    else:
        lines.append(
            f"  DB state: session {snapshot.session_id if snapshot.session_id is not None else '?'} @ {snapshot.state_timestamp:.1f}s"
        )
    for surface in (snapshot.health, snapshot.spectral):
        lines.append(
            f"  {_surface_label(surface.name)}: {surface.short_label()} ({'usable' if surface.valid_for_state else 'guarded'})"
        )
        for issue in surface.issues:
            lines.append(f"    - {issue}")
    if snapshot.target_provenance:
        lines.append(f"  Target provenance: {snapshot.target_provenance}")
    return "\n".join(lines)
