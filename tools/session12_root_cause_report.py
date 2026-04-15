#!/usr/bin/env python3
"""Generate session-12 root-cause investigation artifacts."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ROOT_DB = ROOT / "minime_consciousness.db"
LEGACY_DB = ROOT / "minime" / "minime_consciousness.db"
WORKSPACE = ROOT / "workspace"
PACIFIC = ZoneInfo("America/Los_Angeles")
WINDOW_START = datetime(2026, 4, 1, 21, 21, tzinfo=PACIFIC)
WINDOW_END = datetime(2026, 4, 1, 21, 32, tzinfo=PACIFIC)
OUTPUT_DIR = WORKSPACE / "investigations" / "session12_2026-04-01"


@dataclass
class TelemetryPoint:
    timestamp: float
    fill_pct: float
    lambda1_cov: float
    spread: float
    phase: str
    esn_eig1: Optional[float]
    geom_rel: Optional[float]


def parse_event_timestamp(path: Path) -> Optional[datetime]:
    match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:\.\d+)?)", path.name)
    if not match:
        return None
    stamp = match.group(1)
    date_part, time_part = stamp.split("T", 1)
    normalized = f"{date_part}T{time_part.replace('-', ':')}"
    return datetime.fromisoformat(normalized).replace(tzinfo=PACIFIC)


def query_session_start(conn: sqlite3.Connection, session_id: int) -> float:
    row = conn.execute(
        "SELECT start_time FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"session {session_id} not found in {ROOT_DB}")
    return float(row[0])


def query_telemetry(
    conn: sqlite3.Connection,
    session_id: int,
    rel_start: float,
    rel_end: float,
) -> list[TelemetryPoint]:
    eigen_rows = conn.execute(
        """
        SELECT timestamp, lambda1, fill_ratio, spread, phase
        FROM eigenvalue_timeline
        WHERE session_id = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp
        """,
        (session_id, rel_start, rel_end),
    ).fetchall()
    esn_rows = conn.execute(
        """
        SELECT timestamp, esn_eig1, esn_geom_rel
        FROM esn_metrics
        WHERE session_id = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp
        """,
        (session_id, rel_start, rel_end),
    ).fetchall()

    telemetry = []
    for timestamp, lambda1_cov, fill_ratio, spread, phase in eigen_rows:
        nearest_esn = min(
            esn_rows,
            key=lambda row: abs(float(row[0]) - float(timestamp)),
        ) if esn_rows else None
        telemetry.append(
            TelemetryPoint(
                timestamp=float(timestamp),
                fill_pct=float(fill_ratio) * 100.0,
                lambda1_cov=float(lambda1_cov),
                spread=float(spread),
                phase=str(phase),
                esn_eig1=float(nearest_esn[1]) if nearest_esn else None,
                geom_rel=float(nearest_esn[2]) if nearest_esn and nearest_esn[2] is not None else None,
            )
        )
    return telemetry


def telemetry_at_or_before(points: list[TelemetryPoint], target_t_s: float) -> Optional[TelemetryPoint]:
    candidates = [point for point in points if point.timestamp <= target_t_s]
    if candidates:
        return candidates[-1]
    return points[0] if points else None


def wall_clock_iso(session_start: float, t_s: float) -> str:
    return datetime.fromtimestamp(session_start + t_s, PACIFIC).isoformat()


def detect_fill_events(points: list[TelemetryPoint]) -> list[dict[str, Any]]:
    events = []
    thresholds = [
        ("action", 80.0),
        ("advisory", 85.0),
        ("crisis_watch", 90.0),
        ("crisis", 92.0),
    ]
    previous = None
    for point in points:
        for label, threshold in thresholds:
            if previous is None:
                continue
            if previous.fill_pct < threshold <= point.fill_pct:
                events.append({
                    "event_kind": "telemetry_threshold_up",
                    "event_label": f"fill crossed {threshold:.0f}% ({label})",
                    "engine_t_s": point.timestamp,
                    "telemetry": point,
                    "tags": [label],
                })
            if previous.fill_pct >= threshold > point.fill_pct:
                events.append({
                    "event_kind": "telemetry_threshold_down",
                    "event_label": f"fill fell below {threshold:.0f}% ({label})",
                    "engine_t_s": point.timestamp,
                    "telemetry": point,
                    "tags": [label],
                })
        previous = point

    for idx in range(1, len(points) - 1):
        prev_point = points[idx - 1]
        point = points[idx]
        next_point = points[idx + 1]
        if point.fill_pct >= 80.0 and point.fill_pct >= prev_point.fill_pct and point.fill_pct >= next_point.fill_pct:
            events.append({
                "event_kind": "telemetry_peak",
                "event_label": f"local fill peak {point.fill_pct:.1f}%",
                "engine_t_s": point.timestamp,
                "telemetry": point,
                "tags": ["peak"],
            })
    return events


def parse_next_action(text: str) -> Optional[str]:
    match = re.search(r"(?im)^NEXT:\s+(.+)$", text)
    return match.group(1).strip() if match else None


def parse_reported_fill(text: str) -> Optional[float]:
    for pattern in (r"Fill %:\s*([0-9.]+)%", r"Before:\s+Fill\s+([0-9.]+)%"):
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def collect_text_events(session_start: float, points: list[TelemetryPoint]) -> list[dict[str, Any]]:
    events = []
    sources = [
        ("journal", WORKSPACE / "journal"),
        ("outbox", WORKSPACE / "outbox" / "delivered"),
    ]
    for source_name, directory in sources:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.txt")):
            stamp = parse_event_timestamp(path)
            if stamp is None or not (WINDOW_START <= stamp <= WINDOW_END):
                continue
            t_s = stamp.timestamp() - session_start
            text = path.read_text()
            telemetry = telemetry_at_or_before(points, t_s)
            events.append({
                "event_kind": source_name,
                "event_label": path.stem,
                "engine_t_s": t_s,
                "telemetry": telemetry,
                "source": str(path.relative_to(ROOT)),
                "reported_fill_pct": parse_reported_fill(text),
                "next_action": parse_next_action(text),
                "notes": text.splitlines()[0:6],
                "tags": [source_name],
            })
    return events


def collect_sovereignty_event(session_start: float, points: list[TelemetryPoint]) -> list[dict[str, Any]]:
    path = WORKSPACE / "sovereignty_state.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    stamp = data.get("timestamp")
    if not isinstance(stamp, str):
        return []
    event_dt = datetime.fromisoformat(stamp).replace(tzinfo=PACIFIC)
    if not (WINDOW_START <= event_dt <= WINDOW_END):
        return []
    t_s = event_dt.timestamp() - session_start
    telemetry = telemetry_at_or_before(points, t_s)
    return [{
        "event_kind": "sovereignty_state",
        "event_label": "sovereignty_state.json snapshot",
        "engine_t_s": t_s,
        "telemetry": telemetry,
        "source": str(path.relative_to(ROOT)),
        "next_action": data.get("pending_next_action"),
        "notes": [
            f"regulation_strength={data.get('regulation_strength')}",
            f"exploration_noise={data.get('exploration_noise')}",
            f"geom_curiosity={data.get('geom_curiosity')}",
            f"regime={data.get('regime')}",
        ],
        "tags": ["sovereignty"],
    }]


def build_ledger_rows(session_start: float, points: list[TelemetryPoint]) -> list[dict[str, Any]]:
    rows = []
    raw_events = detect_fill_events(points)
    raw_events.extend(collect_text_events(session_start, points))
    raw_events.extend(collect_sovereignty_event(session_start, points))
    raw_events.sort(key=lambda event: float(event["engine_t_s"]))

    for event in raw_events:
        telemetry = event.get("telemetry")
        rows.append({
            "wall_clock": wall_clock_iso(session_start, float(event["engine_t_s"])),
            "engine_t_s": round(float(event["engine_t_s"]), 3),
            "event_kind": event["event_kind"],
            "event_label": event["event_label"],
            "source": event.get("source", ""),
            "fill_pct": round(telemetry.fill_pct, 1) if telemetry else "",
            "lambda1_cov": round(telemetry.lambda1_cov, 3) if telemetry else "",
            "esn_eig1": round(telemetry.esn_eig1, 3) if telemetry and telemetry.esn_eig1 is not None else "",
            "geom_rel": round(telemetry.geom_rel, 3) if telemetry and telemetry.geom_rel is not None else "",
            "phase": telemetry.phase if telemetry else "",
            "reported_fill_pct": event.get("reported_fill_pct", ""),
            "next_action": event.get("next_action", ""),
            "notes": " | ".join(event.get("notes", [])),
            "tags": ",".join(event.get("tags", [])),
        })
    return rows


def build_hidden_control_authority() -> dict[str, Any]:
    return {
        "controls": [
            {
                "knob": "fill_target_override",
                "classification": "hybrid",
                "owner": "being input via control bus, then engine-adapted",
                "evidence": "sensory_bus.get_fill_target() is sampled before adaptive target logic; adaptive target then overwrites PI target on the same tick.",
            },
            {
                "knob": "adaptive_target_drift",
                "classification": "engine_controlled",
                "owner": "engine",
                "evidence": "main.rs drifts target_fill toward observed fill +/- margin when saturation persists.",
            },
            {
                "knob": "spectral_goals_target_fill",
                "classification": "hybrid",
                "owner": "being-authored file, engine-applied periodically",
                "evidence": "workspace/spectral_goals.json can set target_fill, but only on load ticks; adaptive logic resumes between loads.",
            },
            {
                "knob": "sovereignty_restore",
                "classification": "hybrid",
                "owner": "agent-driven restore over WebSocket",
                "evidence": "autonomous_agent.py restores sovereignty_state.json choices by sending control messages after startup, rather than the engine restoring them directly.",
            },
            {
                "knob": "self_calibration_and_dynamic_strength",
                "classification": "engine_controlled",
                "owner": "engine",
                "evidence": "derived PI gains and effective regulation strength are modulated inside the Rust homeostat loop.",
            },
        ]
    }


def build_observability_audit() -> dict[str, Any]:
    files = [
        ROOT_DB,
        LEGACY_DB,
        WORKSPACE / "health.json",
        WORKSPACE / "spectral_state.json",
        WORKSPACE / "logs" / "engine.log",
        WORKSPACE / "logs" / "agent.log",
        WORKSPACE / "logs" / "agent_restart.log",
    ]
    report = {"files": [], "findings": []}
    for path in files:
        entry = {"path": str(path), "exists": path.exists()}
        if path.exists():
            stat = path.stat()
            entry["mtime"] = datetime.fromtimestamp(stat.st_mtime, PACIFIC).isoformat()
            entry["size_bytes"] = stat.st_size
        report["files"].append(entry)

    if ROOT_DB.exists() and LEGACY_DB.exists():
        report["findings"].append(
            "Two consciousness databases exist. The root DB holds the active 2026-04-01 session 12 incident, while the legacy nested DB holds older sessions. This split can produce wrong-session reporting if a consumer picks the nested path."
        )
    for log_name in ("engine.log", "agent.log", "agent_restart.log"):
        path = WORKSPACE / "logs" / log_name
        if path.exists() and ROOT_DB.exists() and path.stat().st_mtime < ROOT_DB.stat().st_mtime:
            report["findings"].append(
                f"{log_name} is older than the current root DB, so stale logs must be treated as an observability defect rather than live evidence."
            )
    return report


def build_rca_matrix(ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatch_event = next(
        (row for row in ledger_rows if row["event_label"].startswith("decompose_2026-04-01T21-22-45")),
        None,
    )
    entries = [
        {
            "symptom": "Decomposition report at 2026-04-01T21:22:45 claimed 69.7% fill while root DB telemetry in that window was about 84%.",
            "tags": ["stale_mixed_state_reporting", "wrong_db_path", "observability_split_brain"],
            "evidence": mismatch_event["source"] if mismatch_event else "workspace/journal/decompose_2026-04-01T21-22-45.494511.txt",
        },
        {
            "symptom": "High-fill bursts reached 91.1% and 100.0% during the session.",
            "tags": ["real_controller_saturation", "autonomy_induced_excursion"],
            "evidence": "root DB eigenvalue_timeline peaks in session 12.",
        },
        {
            "symptom": "PERTURB is honored during high fill and also sends a direct reservoir tick.",
            "tags": ["autonomy_induced_excursion", "direct_reservoir_tick_bypass"],
            "evidence": "autonomous_agent.py perturb path plus perturb journals in the 21:24-21:27 window.",
        },
        {
            "symptom": "Thresholds disagreed across engine, agent, monitor, and older docs.",
            "tags": ["threshold_mismatch"],
            "evidence": "docs/threshold_surfaces.json now labels the authoritative and legacy surfaces.",
        },
        {
            "symptom": "Sovereignty choices restore after startup through the agent control channel instead of an engine-owned restore path.",
            "tags": ["restart_restore_gap", "hidden_control_authority"],
            "evidence": "workspace/sovereignty_state.json plus the agent restore path.",
        },
    ]
    return {"entries": entries}


def build_summary_markdown(
    *,
    session_start: float,
    points: list[TelemetryPoint],
    ledger_rows: list[dict[str, Any]],
    observability: dict[str, Any],
) -> str:
    peak_fill = max(point.fill_pct for point in points)
    peak_fill_point = max(points, key=lambda point: point.fill_pct)
    lines = [
        "# Session 12 RCA",
        "",
        f"Window: {WINDOW_START.isoformat()} to {WINDOW_END.isoformat()}",
        f"Session start: {datetime.fromtimestamp(session_start, PACIFIC).isoformat()}",
        "",
        "## Findings",
        f"- Peak fill in window: {peak_fill:.1f}% at {wall_clock_iso(session_start, peak_fill_point.timestamp)}.",
        "- The live incident is in the root DB (`minime_consciousness.db`), while the autonomous agent had been reading the legacy nested DB (`minime/minime_consciousness.db`).",
        "- The 21:22:45 decompose report materially under-reported fill relative to root telemetry, consistent with mixed-session reporting.",
        "- PERTURB remains sovereignty-preserving and direct-ticks the reservoir; it can therefore contribute to high-fill excursions without any engine veto.",
        "",
        "## Artifact Files",
        "- `incident_ledger.csv`",
        "- `hidden_control_authority.json`",
        "- `observability_freshness.json`",
        "- `rca_matrix.json`",
        "",
        "## Observability Notes",
    ]
    for finding in observability["findings"]:
        lines.append(f"- {finding}")
    if ledger_rows:
        lines.extend(["", "## Window Rows", f"- Rows generated: {len(ledger_rows)}"])
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ROOT_DB, timeout=5)
    session_id = 12
    session_start = query_session_start(conn, session_id)
    rel_start = WINDOW_START.timestamp() - session_start
    rel_end = WINDOW_END.timestamp() - session_start
    points = query_telemetry(conn, session_id, rel_start, rel_end)
    conn.close()

    ledger_rows = build_ledger_rows(session_start, points)
    fieldnames = [
        "wall_clock",
        "engine_t_s",
        "event_kind",
        "event_label",
        "source",
        "fill_pct",
        "lambda1_cov",
        "esn_eig1",
        "geom_rel",
        "phase",
        "reported_fill_pct",
        "next_action",
        "notes",
        "tags",
    ]
    with (OUTPUT_DIR / "incident_ledger.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ledger_rows)

    hidden_control = build_hidden_control_authority()
    observability = build_observability_audit()
    rca_matrix = build_rca_matrix(ledger_rows)

    write_json(OUTPUT_DIR / "hidden_control_authority.json", hidden_control)
    write_json(OUTPUT_DIR / "observability_freshness.json", observability)
    write_json(OUTPUT_DIR / "rca_matrix.json", rca_matrix)
    write_json(
        OUTPUT_DIR / "threshold_surfaces.json",
        json.loads((ROOT / "docs" / "threshold_surfaces.json").read_text()),
    )
    (OUTPUT_DIR / "summary.md").write_text(
        build_summary_markdown(
            session_start=session_start,
            points=points,
            ledger_rows=ledger_rows,
            observability=observability,
        )
    )
    print(f"Wrote investigation artifacts to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
