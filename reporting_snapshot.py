"""Provenance-aware live reporting snapshots for the autonomous agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


MAX_SNAPSHOT_SKEW_S = 3.0
RESCUE_MODE = "rescue_b8823ad"


@dataclass
class SurfaceSnapshot:
    """A single live surface plus validation metadata."""

    source_name: str
    path: Path
    data: Dict[str, Any] = field(default_factory=dict)
    valid_for_state: bool = False
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ReportSnapshot:
    """A DB state enriched with guarded live workspace surfaces."""

    state: Dict[str, Any]
    health: SurfaceSnapshot
    spectral: SurfaceSnapshot


def resolve_runtime_db_path(base_dir: Path) -> Path:
    """Prefer the active root DB, fall back to the legacy nested location."""

    root_db = base_dir / "minime_consciousness.db"
    if root_db.exists():
        return root_db
    return base_dir / "minime" / "minime_consciousness.db"


def load_workspace_json(base_dir: Path, workspace_dir: Path, file_name: str) -> Dict[str, Any]:
    """Load a JSON surface from the active workspace, with legacy fallback."""

    candidates = [
        workspace_dir / file_name,
        base_dir / "workspace" / file_name,
        base_dir / "minime" / "workspace" / file_name,
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(file_name)


def normalize_spectral_state(surface: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Preserve the raw surface while backfilling convenience fields."""

    if not isinstance(surface, dict):
        return {}

    normalized = dict(surface)
    fill_pct = normalized.get("fill_pct")
    fill_ratio = normalized.get("fill_ratio")
    if fill_ratio is None and isinstance(fill_pct, (int, float)):
        normalized["fill_ratio"] = float(fill_pct) / 100.0

    eigenvalues = normalized.get("eigenvalues")
    if normalized.get("eig1") is None and isinstance(eigenvalues, list) and eigenvalues:
        first = eigenvalues[0]
        if isinstance(first, (int, float)):
            normalized["eig1"] = float(first)

    provenance = normalized.get("provenance")
    if isinstance(provenance, dict):
        engine_t_s = provenance.get("engine_t_s")
        if (
            normalized.get("timestamp") is None
            and isinstance(engine_t_s, (int, float))
            and not _is_rescue_provenance(provenance)
        ):
            normalized["timestamp"] = float(engine_t_s)

    return normalized


def capture_report_snapshot(
    *,
    state: Dict[str, Any],
    session_id: Optional[int],
    base_dir: Path,
    workspace_dir: Path,
) -> ReportSnapshot:
    """Capture guarded health/spectral surfaces around a DB state."""

    base_state = dict(state or {})
    state_ts = _as_float(base_state.get("timestamp"))

    health_raw = _safe_workspace_json(base_dir, workspace_dir, "health.json")
    spectral_raw = _safe_workspace_json(base_dir, workspace_dir, "spectral_state.json")
    spectral_normalized = normalize_spectral_state(spectral_raw)

    health = _validate_surface(
        source_name="health.json",
        path=_surface_path(base_dir, workspace_dir, "health.json"),
        data=health_raw,
        session_id=session_id,
        state_timestamp=state_ts,
        require_provenance=True,
        compare_later_than_db=False,
    )
    spectral = _validate_surface(
        source_name="spectral_state.json",
        path=_surface_path(base_dir, workspace_dir, "spectral_state.json"),
        data=spectral_normalized,
        session_id=session_id,
        state_timestamp=state_ts,
        require_provenance=False,
        compare_later_than_db=False,
    )
    _apply_later_than_db_policy(
        health=health,
        spectral=spectral,
        state_timestamp=state_ts,
    )

    merged_state = dict(base_state)
    if spectral.valid_for_state:
        for key, value in spectral.data.items():
            if key not in {"provenance"}:
                merged_state[key] = value

    return ReportSnapshot(state=merged_state, health=health, spectral=spectral)


def format_snapshot_provenance(snapshot: ReportSnapshot) -> str:
    """Render a human-readable provenance block for journals/reports."""

    lines = ["Live provenance surfaces:"]
    for surface in (snapshot.health, snapshot.spectral):
        status = "ok" if surface.valid_for_state else "guarded"
        lines.append(f"- {surface.source_name}: {status}")
        if surface.issues:
            lines.append(f"  issues: {'; '.join(surface.issues)}")
        if surface.notes:
            lines.append(f"  notes: {'; '.join(surface.notes)}")
        provenance = surface.data.get("provenance") if isinstance(surface.data, dict) else None
        if isinstance(provenance, dict):
            session = provenance.get("session_id")
            engine_t_s = provenance.get("engine_t_s")
            sequence = provenance.get("snapshot_sequence")
            details = []
            if session is not None:
                details.append(f"session={session}")
            if engine_t_s is not None:
                details.append(f"engine_t_s={engine_t_s}")
            if sequence is not None:
                details.append(f"seq={sequence}")
            if details:
                lines.append(f"  {' '.join(details)}")
        elif surface.path.exists():
            lines.append(f"  path={surface.path}")
    return "\n".join(lines)


def format_snapshot_summary(snapshot: ReportSnapshot) -> str:
    """Compact one-line summary for report footers and agent surfaces."""

    health_guard = _surface_summary(snapshot.health)
    spectral_guard = _surface_summary(snapshot.spectral)
    return (
        f"Snapshot guard={snapshot.health.source_name}:{health_guard}; "
        f"{snapshot.spectral.source_name}:{spectral_guard}"
    )


def _surface_summary(surface: SurfaceSnapshot) -> str:
    if surface.valid_for_state:
        if surface.notes:
            return f"ok ({'; '.join(surface.notes)})"
        return "ok"
    return "; ".join(surface.issues)


def _safe_workspace_json(base_dir: Path, workspace_dir: Path, file_name: str) -> Dict[str, Any]:
    try:
        loaded = load_workspace_json(base_dir, workspace_dir, file_name)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _surface_path(base_dir: Path, workspace_dir: Path, file_name: str) -> Path:
    for path in (
        workspace_dir / file_name,
        base_dir / "workspace" / file_name,
        base_dir / "minime" / "workspace" / file_name,
    ):
        if path.exists():
            return path
    return workspace_dir / file_name


def _apply_later_than_db_policy(
    *,
    health: SurfaceSnapshot,
    spectral: SurfaceSnapshot,
    state_timestamp: Optional[float],
) -> None:
    """Accept a newer live spectral surface only when health corroborates it.

    The DB row can lag the live workspace surfaces during journal formatting.
    Treating every live-ahead surface as invalid made entries drop the cascade
    even when health.json and spectral_state.json were from the same fresh engine
    tick. Keep the old guard when health cannot corroborate the newer surface.
    """

    if not spectral.valid_for_state:
        return
    lead_s = _surface_leads_state_by(spectral.data, state_timestamp)
    if lead_s is None or lead_s <= MAX_SNAPSHOT_SKEW_S:
        return

    if _live_surfaces_are_aligned(health, spectral):
        spectral.notes.append(f"DB state refreshed from live surface by {lead_s:.1f}s")
        return

    spectral.issues.append(f"later than DB state by {lead_s:.1f}s")
    spectral.valid_for_state = False


def _surface_leads_state_by(
    data: Dict[str, Any],
    state_timestamp: Optional[float],
) -> Optional[float]:
    if state_timestamp is None:
        return None
    provenance = data.get("provenance") if isinstance(data, dict) else None
    if isinstance(provenance, dict):
        engine_t_s = _as_float(provenance.get("engine_t_s"))
        if engine_t_s is not None:
            return engine_t_s - state_timestamp
    surface_ts = _as_float(data.get("timestamp")) if isinstance(data, dict) else None
    if surface_ts is not None:
        return surface_ts - state_timestamp
    return None


def _live_surfaces_are_aligned(
    health: SurfaceSnapshot,
    spectral: SurfaceSnapshot,
) -> bool:
    if not health.valid_for_state:
        return False

    health_provenance = (
        health.data.get("provenance") if isinstance(health.data, dict) else None
    )
    spectral_provenance = (
        spectral.data.get("provenance") if isinstance(spectral.data, dict) else None
    )
    if not isinstance(health_provenance, dict) or not isinstance(spectral_provenance, dict):
        return False

    health_session = health_provenance.get("session_id")
    spectral_session = spectral_provenance.get("session_id")
    if (
        health_session is not None
        and spectral_session is not None
        and health_session != spectral_session
    ):
        return False

    health_engine_t_s = _as_float(health_provenance.get("engine_t_s"))
    spectral_engine_t_s = _as_float(spectral_provenance.get("engine_t_s"))
    if health_engine_t_s is None or spectral_engine_t_s is None:
        return False
    return abs(health_engine_t_s - spectral_engine_t_s) <= MAX_SNAPSHOT_SKEW_S


def _validate_surface(
    *,
    source_name: str,
    path: Path,
    data: Dict[str, Any],
    session_id: Optional[int],
    state_timestamp: Optional[float],
    require_provenance: bool,
    compare_later_than_db: bool,
) -> SurfaceSnapshot:
    issues: list[str] = []
    provenance = data.get("provenance") if isinstance(data, dict) else None
    rescue_surface = _is_rescue_provenance(provenance)
    if not isinstance(data, dict) or not data:
        issues.append("surface missing")
    if require_provenance and not isinstance(provenance, dict):
        issues.append("missing provenance")

    if isinstance(provenance, dict):
        if rescue_surface:
            if not provenance.get("rescue_active", False):
                issues.append("rescue surface inactive")
            surface_state = provenance.get("surface_state")
            if surface_state not in {"fresh", None}:
                issues.append(f"rescue surface {surface_state}")
        else:
            live_session = provenance.get("session_id")
            if session_id is not None and live_session is not None and live_session != session_id:
                issues.append(f"session mismatch ({live_session} != {session_id})")

            engine_t_s = _as_float(provenance.get("engine_t_s"))
            if (
                compare_later_than_db
                and engine_t_s is not None
                and state_timestamp is not None
                and engine_t_s - state_timestamp > MAX_SNAPSHOT_SKEW_S
            ):
                issues.append(
                    f"later than DB state by {engine_t_s - state_timestamp:.1f}s"
                )

    if compare_later_than_db and not issues and not rescue_surface:
        surface_ts = _as_float(data.get("timestamp"))
        if (
            surface_ts is not None
            and state_timestamp is not None
            and surface_ts - state_timestamp > MAX_SNAPSHOT_SKEW_S
        ):
            issues.append(f"later than DB state by {surface_ts - state_timestamp:.1f}s")

    return SurfaceSnapshot(
        source_name=source_name,
        path=path,
        data=data,
        valid_for_state=not issues,
        issues=issues,
    )


def _is_rescue_provenance(provenance: Any) -> bool:
    return isinstance(provenance, dict) and provenance.get("mode") == RESCUE_MODE


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None
