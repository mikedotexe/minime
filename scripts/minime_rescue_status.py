#!/usr/bin/env python3
"""Shared rescue-status helpers for the Minime operational rescue lane."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minime_rescue_investigation import default_context, load_active_profile


CONTEXT = default_context()
PROJECT_DIR = CONTEXT.project_dir
STATUS_PATH = PROJECT_DIR / "workspace" / "rescue_status.json"
HEALTH_PATH = PROJECT_DIR / "workspace" / "health.json"
SPECTRAL_PATH = PROJECT_DIR / "workspace" / "spectral_state.json"
RUNTIME_DIR = PROJECT_DIR / "workspace" / "runtime"
MIC_STATUS_PATH = RUNTIME_DIR / "mic_status.json"
CAMERA_STATUS_PATH = RUNTIME_DIR / "camera_status.json"
DEFAULT_BINARY = str(CONTEXT.engine_binary)
BASELINE_COMMIT = "b8823ad"
TARGET_FILL = 68.0
DEFAULT_PORTS = {"7878": False, "7879": False, "7880": False}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def write_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_spectral(payload: dict[str, Any]) -> None:
    SPECTRAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPECTRAL_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _normalize_ports(ports_ready: dict[str, Any] | None) -> dict[str, bool]:
    payload = dict(DEFAULT_PORTS)
    if not isinstance(ports_ready, dict):
        return payload
    for key in payload:
        payload[key] = bool(ports_ready.get(key, False))
    return payload


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _load_runtime_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _active_engine_target_fill(
    active_profile: dict[str, Any],
    rescue_health: dict[str, Any],
    structural_pi: dict[str, Any],
) -> float:
    stable_core_enabled = bool(active_profile.get("stable_core_enabled")) or (
        active_profile.get("runtime_profile") == "stable_core_v1"
    )
    stable_core_target = _as_float(
        rescue_health.get("stability_pi_target_fill_pct")
    ) or _as_float(structural_pi.get("target_fill_pct"))
    profile_target = _as_float(active_profile.get("engine_target_fill"))
    if stable_core_enabled and stable_core_target is not None:
        return stable_core_target
    if profile_target is not None:
        return profile_target
    return TARGET_FILL


def _input_lane_snapshot() -> dict[str, Any]:
    mic_status = _load_runtime_status(MIC_STATUS_PATH)
    camera_status = _load_runtime_status(CAMERA_STATUS_PATH)
    return {
        "socket_liveness": {
            "7879": bool(mic_status.get("connected", False)),
            "7880": bool(camera_status.get("connected", False)),
        },
        "audio_disconnect_count": _as_int(mic_status.get("reconnect_count")),
        "video_disconnect_count": _as_int(camera_status.get("reconnect_count")),
        "audio_last_disconnect_reason": mic_status.get("last_error"),
        "video_last_disconnect_reason": camera_status.get("last_error"),
    }


def build_active_status(
    *,
    watchdog_state: str,
    binary_path: str,
    started_at: str | None = None,
    last_restart_at: str | None = None,
    engine_pid: int | None = None,
    gpu_status: str | None = None,
    ports_ready: dict[str, Any] | None = None,
    last_health_at: str | None = None,
    telemetry_state: str | None = None,
) -> dict[str, Any]:
    current = load_status()
    active_profile = load_active_profile(CONTEXT)
    health_payload = _load_runtime_status(HEALTH_PATH)
    rescue_health = (
        health_payload.get("rescue") if isinstance(health_payload.get("rescue"), dict) else {}
    )
    stable_core_health = (
        health_payload.get("stable_core")
        if isinstance(health_payload.get("stable_core"), dict)
        else {}
    )
    structural_pi = (
        stable_core_health.get("structural_pi")
        if isinstance(stable_core_health.get("structural_pi"), dict)
        else {}
    )
    started_at_value = started_at or current.get("started_at") or now_iso()
    last_restart_value = last_restart_at or current.get("last_restart_at") or started_at_value
    lane_snapshot = _input_lane_snapshot()
    previous_engine_pid = current.get("engine_pid")
    effective_engine_pid = engine_pid if engine_pid is not None else previous_engine_pid
    pid_changed = (
        previous_engine_pid is not None
        and effective_engine_pid is not None
        and previous_engine_pid != effective_engine_pid
    )
    previous_restart_at = current.get("last_restart_at")
    unaccounted_pid_change = bool(pid_changed and last_restart_value == previous_restart_at)
    engine_pid_changed_at = (
        now_iso() if pid_changed else current.get("engine_pid_changed_at")
    )
    return {
        "agent_enabled": False,
        "audio_disconnect_count": lane_snapshot["audio_disconnect_count"],
        "audio_last_disconnect_reason": lane_snapshot["audio_last_disconnect_reason"],
        "baseline_commit": BASELINE_COMMIT,
        "binary_path": binary_path,
        "db_path": active_profile.get("db_path"),
        "engine_pid": effective_engine_pid,
        "engine_pid_changed_at": engine_pid_changed_at,
        "engine_pid_changed_without_watchdog_restart": unaccounted_pid_change,
        "engine_target_fill": _active_engine_target_fill(
            active_profile, rescue_health, structural_pi
        ),
        "gpu_status": gpu_status or current.get("gpu_status", "unavailable"),
        "last_restart_at": last_restart_value,
        "last_health_at": last_health_at if last_health_at is not None else current.get("last_health_at"),
        "matrix_run_id": active_profile.get("matrix_run_id"),
        "mode": active_profile.get("runtime_profile") or "rescue_b8823ad",
        "ports_ready": _normalize_ports(ports_ready or current.get("ports_ready")),
        "run_profile": active_profile.get("profile"),
        "runtime_root": active_profile.get("runtime_root"),
        "scaffold_activation_pending": bool(
            rescue_health.get(
                "scaffold_activation_pending",
                current.get("scaffold_activation_pending", False),
            )
        ),
        "scaffold_archived_stale_at_startup": bool(
            rescue_health.get(
                "scaffold_archived_stale_at_startup",
                current.get("scaffold_archived_stale_at_startup", False),
            )
        ),
        "scaffold_available": bool(
            rescue_health.get("scaffold_available", current.get("scaffold_available", False))
        ),
        "scaffold_drain_weight": rescue_health.get(
            "scaffold_drain_weight", current.get("scaffold_drain_weight")
        ),
        "scaffold_last_captured_at_unix_ms": rescue_health.get(
            "scaffold_last_captured_at_unix_ms",
            current.get("scaffold_last_captured_at_unix_ms"),
        ),
        "scaffold_last_loaded_at_unix_ms": rescue_health.get(
            "scaffold_last_loaded_at_unix_ms",
            current.get("scaffold_last_loaded_at_unix_ms"),
        ),
        "scaffold_mode_cap": rescue_health.get(
            "scaffold_mode_cap", current.get("scaffold_mode_cap")
        ),
        "scaffold_profile": rescue_health.get(
            "scaffold_profile", current.get("scaffold_profile")
        ),
        "scaffold_profile_version": rescue_health.get(
            "scaffold_profile_version", current.get("scaffold_profile_version")
        ),
        "scaffold_regenerated_at_startup": bool(
            rescue_health.get(
                "scaffold_regenerated_at_startup",
                current.get("scaffold_regenerated_at_startup", False),
            )
        ),
        "scaffold_source": rescue_health.get("scaffold_source", current.get("scaffold_source")),
        "socket_liveness": lane_snapshot["socket_liveness"],
        "stability_pi_active": bool(
            rescue_health.get(
                "stability_pi_active",
                structural_pi.get("active", current.get("stability_pi_active", False)),
            )
        ),
        "stability_pi_error_pct": rescue_health.get(
            "stability_pi_error_pct",
            structural_pi.get("error_pct", current.get("stability_pi_error_pct")),
        ),
        "stability_pi_integral": rescue_health.get(
            "stability_pi_integral",
            structural_pi.get("integral", current.get("stability_pi_integral")),
        ),
        "stability_pi_target_fill_pct": rescue_health.get(
            "stability_pi_target_fill_pct",
            structural_pi.get("target_fill_pct", current.get("stability_pi_target_fill_pct")),
        ),
        "state_variant": active_profile.get("state_variant"),
        "started_at": started_at_value,
        "telemetry_state": telemetry_state or current.get("telemetry_state", "stale"),
        "previous_engine_pid": previous_engine_pid if pid_changed else current.get("previous_engine_pid"),
        "video_disconnect_count": lane_snapshot["video_disconnect_count"],
        "video_last_disconnect_reason": lane_snapshot["video_last_disconnect_reason"],
        "watchdog_state": watchdog_state,
        "workspace_path": active_profile.get("workspace_path"),
    }


def build_inactive_status(*, watchdog_state: str) -> dict[str, Any]:
    current = load_status()
    return {
        "agent_enabled": False,
        "audio_disconnect_count": 0,
        "audio_last_disconnect_reason": None,
        "baseline_commit": BASELINE_COMMIT,
        "binary_path": current.get("binary_path", DEFAULT_BINARY),
        "db_path": current.get("db_path"),
        "engine_pid": None,
        "engine_pid_changed_at": current.get("engine_pid_changed_at"),
        "engine_pid_changed_without_watchdog_restart": False,
        "engine_target_fill": TARGET_FILL,
        "gpu_status": "unavailable",
        "last_restart_at": None,
        "last_health_at": current.get("last_health_at"),
        "matrix_run_id": current.get("matrix_run_id"),
        "mode": "inactive",
        "ports_ready": dict(DEFAULT_PORTS),
        "previous_engine_pid": current.get("previous_engine_pid"),
        "run_profile": current.get("run_profile"),
        "runtime_root": current.get("runtime_root"),
        "scaffold_activation_pending": False,
        "scaffold_archived_stale_at_startup": False,
        "scaffold_available": False,
        "scaffold_drain_weight": None,
        "scaffold_last_captured_at_unix_ms": None,
        "scaffold_last_loaded_at_unix_ms": None,
        "scaffold_mode_cap": None,
        "scaffold_profile": None,
        "scaffold_profile_version": None,
        "scaffold_regenerated_at_startup": False,
        "scaffold_source": None,
        "socket_liveness": {"7879": False, "7880": False},
        "stability_pi_active": False,
        "stability_pi_error_pct": None,
        "stability_pi_integral": None,
        "stability_pi_target_fill_pct": None,
        "state_variant": current.get("state_variant"),
        "started_at": None,
        "telemetry_state": "inactive",
        "video_disconnect_count": 0,
        "video_last_disconnect_reason": None,
        "watchdog_state": watchdog_state,
        "workspace_path": current.get("workspace_path"),
    }


def build_rescue_spectral_surface(
    *,
    health_payload: dict[str, Any] | None,
    last_restart_at: str | None,
    engine_pid: int | None,
    rescue_active: bool,
    surface_state: str,
) -> dict[str, Any]:
    health = health_payload if isinstance(health_payload, dict) else {}
    fill_pct = _as_float(health.get("fill_pct"))
    target_fill = _as_float(health.get("target_fill_pct"))
    if target_fill is None:
        pi = health.get("pi")
        if isinstance(pi, dict):
            target_fill = _as_float(pi.get("target_fill"))
    target_fill = target_fill if target_fill is not None else TARGET_FILL
    lambda1_cov = _as_float(health.get("lambda1_cov"))
    gate = _as_float(health.get("gate"))
    filt = _as_float(health.get("filt"))
    geom_rel = _as_float(health.get("geom_rel"))
    lambda1_rel = _as_float(health.get("lambda1_rel"))
    eigenvalues = [lambda1_cov] if lambda1_cov is not None else []

    provenance: dict[str, Any] = {
        "mode": "rescue_b8823ad",
        "baseline_commit": BASELINE_COMMIT,
        "source_surface": "health.json",
        "mirrored_at": now_iso(),
        "last_restart_at": last_restart_at,
        "engine_pid": engine_pid,
        "rescue_active": rescue_active,
        "surface_state": surface_state,
    }
    engine_t_s = _as_float(health.get("t_s"))
    if engine_t_s is not None:
        provenance["engine_t_s"] = engine_t_s

    return {
        "calm": health.get("calm") if isinstance(health.get("calm"), bool) else None,
        "eig1": lambda1_cov,
        "eigenvalues": eigenvalues,
        "fill_pct": fill_pct,
        "fill_ratio": (fill_pct / 100.0) if fill_pct is not None else None,
        "filt": filt,
        "gate": gate,
        "geom_rel": geom_rel,
        "ising_shadow": None,
        "lambda1_rel": lambda1_rel,
        "provenance": provenance,
        "strong": health.get("strong") if isinstance(health.get("strong"), bool) else None,
        "target_fill_pct": target_fill,
    }


def mirror_spectral_from_health(
    *,
    health_payload: dict[str, Any],
    last_restart_at: str | None,
    engine_pid: int | None,
    surface_state: str = "fresh",
) -> dict[str, Any]:
    payload = build_rescue_spectral_surface(
        health_payload=health_payload,
        last_restart_at=last_restart_at,
        engine_pid=engine_pid,
        rescue_active=True,
        surface_state=surface_state,
    )
    write_spectral(payload)
    return payload


def write_inactive_spectral(*, last_restart_at: str | None = None) -> dict[str, Any]:
    payload = build_rescue_spectral_surface(
        health_payload={},
        last_restart_at=last_restart_at,
        engine_pid=None,
        rescue_active=False,
        surface_state="inactive",
    )
    write_spectral(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage workspace/rescue_status.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    active = subparsers.add_parser("write-active")
    active.add_argument("--watchdog-state", required=True)
    active.add_argument("--binary-path", default=DEFAULT_BINARY)
    active.add_argument("--started-at")
    active.add_argument("--last-restart-at")

    inactive = subparsers.add_parser("write-inactive")
    inactive.add_argument("--watchdog-state", default="inactive")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "write-active":
        payload = build_active_status(
            watchdog_state=args.watchdog_state,
            binary_path=args.binary_path,
            started_at=args.started_at,
            last_restart_at=args.last_restart_at,
        )
    else:
        payload = build_inactive_status(watchdog_state=args.watchdog_state)
    write_status(payload)
    if args.command == "write-inactive":
        write_inactive_spectral()


if __name__ == "__main__":
    main()
