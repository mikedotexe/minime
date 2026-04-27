#!/usr/bin/env python3
"""Keep the Minime rescue engine healthy without switching back to the main runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from minime_rescue_investigation import (
    HEALTHY_COLD_START_WINDOW_SECS,
    HEALTHY_FILL_THRESHOLD,
    HEALTHY_HOLD_WINDOW_SECS,
    active_runtime_health_path,
    capture_decay_bundle,
    default_context,
    ensure_active_profile,
)
from minime_rescue_status import (
    build_active_status,
    load_status,
    mirror_spectral_from_health,
    now_iso,
    write_status,
)


CONTEXT = default_context()
PROJECT_DIR = CONTEXT.project_dir
RESCUE_BINARY = Path(
    os.environ.get(
        "MINIME_RESCUE_BINARY",
        "/Users/v/other/worktrees/minime-rescue-b8823ad/minime/target/release/minime",
    )
)
CHECK_INTERVAL_SECS = int(os.environ.get("MINIME_RESCUE_CHECK_INTERVAL_SECS", "10"))
WARMUP_WINDOW_SECS = int(os.environ.get("MINIME_RESCUE_WARMUP_WINDOW_SECS", "120"))
HEALTH_STALE_SECS = int(os.environ.get("MINIME_RESCUE_HEALTH_STALE_SECS", "30"))
LOW_FILL_THRESHOLD = float(os.environ.get("MINIME_RESCUE_LOW_FILL_THRESHOLD", "50"))
LOW_FILL_CONSECUTIVE_LIMIT = int(
    os.environ.get("MINIME_RESCUE_LOW_FILL_CONSECUTIVE_LIMIT", "3")
)
ENGINE_LABEL = f"gui/{os.getuid()}/com.minime.engine-rescue"
READY_PORTS = ("7878", "7879")
ADVISORY_PORT = "7880"
LSOF_BIN = shutil.which("lsof") or "/usr/sbin/lsof"


def refresh_rescue_binary_from_profile() -> dict[str, Any]:
    global RESCUE_BINARY
    profile = ensure_active_profile(CONTEXT)
    RESCUE_BINARY = Path(profile.get("engine_binary") or RESCUE_BINARY)
    return profile


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(f"[{timestamp}] {message}", flush=True)


def current_engine_pid() -> int | None:
    result = subprocess.run(
        ["pgrep", "-f", str(RESCUE_BINARY)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    pids = []
    for raw_pid in result.stdout.splitlines():
        raw_pid = raw_pid.strip()
        if raw_pid.isdigit():
            pids.append(int(raw_pid))
    return max(pids) if pids else None


def iso_from_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def read_health_payload(health_path: Path) -> tuple[dict[str, Any] | None, float | None]:
    if not health_path.exists():
        return None, None
    try:
        payload = json.loads(health_path.read_text())
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return payload, health_path.stat().st_mtime


def read_fill_pct(payload: dict[str, Any] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    fill_pct = payload.get("fill_pct")
    if isinstance(fill_pct, (int, float)):
        return float(fill_pct)
    return None


def port_bound_by_pid(port: str, pid: int | None) -> bool:
    if pid is None:
        return False
    result = subprocess.run(
        [LSOF_BIN, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit() and int(line[1:]) == pid:
            return True
    return False


def parse_status_time(value: str | None) -> float:
    if not value:
        return time.time()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return time.time()
    return dt.timestamp()


def compute_ports_ready(pid: int | None) -> dict[str, bool]:
    return {
        "7878": port_bound_by_pid("7878", pid),
        "7879": port_bound_by_pid("7879", pid),
        "7880": port_bound_by_pid("7880", pid),
    }


def rescue_gpu_status(
    *,
    ports_ready: dict[str, bool],
    health_fresh: bool,
    telemetry_fresh: bool,
) -> str:
    if ports_ready.get(ADVISORY_PORT, False):
        return "confirmed"
    if health_fresh and telemetry_fresh:
        return "unverified"
    return "unavailable"


def telemetry_state(*, health_mtime: float | None, health_fresh: bool) -> str:
    if health_mtime is None:
        return "stale"
    if health_fresh and time.time() - health_mtime <= HEALTH_STALE_SECS:
        return "fresh"
    return "stale"


def mark_state(
    state: str,
    *,
    last_restart_at: str | None = None,
    engine_pid: int | None = None,
    gpu_status: str,
    ports_ready: dict[str, bool],
    last_health_at: str | None,
    telemetry_state_value: str,
) -> dict[str, Any]:
    payload = build_active_status(
        watchdog_state=state,
        binary_path=str(RESCUE_BINARY),
        last_restart_at=last_restart_at,
        engine_pid=engine_pid,
        gpu_status=gpu_status,
        ports_ready=ports_ready,
        last_health_at=last_health_at,
        telemetry_state=telemetry_state_value,
    )
    write_status(payload)
    return payload


def reset_milestones(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "restart_key": status.get("last_restart_at"),
        "cold_start_bundle_written": False,
        "healthy_hold_bundle_written": False,
        "healthy_fill_started_at": None,
    }


def maybe_capture_milestones(
    *,
    milestones: dict[str, Any],
    fill_pct: float | None,
    elapsed_since_restart: float,
    status: dict[str, Any],
) -> None:
    if fill_pct is None or fill_pct < HEALTHY_FILL_THRESHOLD:
        milestones["healthy_fill_started_at"] = None
        return

    if (
        not milestones["cold_start_bundle_written"]
        and elapsed_since_restart <= HEALTHY_COLD_START_WINDOW_SECS
    ):
        capture_decay_bundle(
            CONTEXT,
            event="healthy_cold_start",
            reason="fill_above_60_within_90s",
            extra={
                "elapsed_since_restart_s": round(elapsed_since_restart, 3),
                "watchdog_state": status.get("watchdog_state"),
            },
        )
        milestones["cold_start_bundle_written"] = True

    now_monotonic = time.monotonic()
    if milestones["healthy_fill_started_at"] is None:
        milestones["healthy_fill_started_at"] = now_monotonic
        return

    if (
        not milestones["healthy_hold_bundle_written"]
        and now_monotonic - milestones["healthy_fill_started_at"] >= HEALTHY_HOLD_WINDOW_SECS
    ):
        capture_decay_bundle(
            CONTEXT,
            event="healthy_hold_20m",
            reason="fill_held_above_60",
            extra={
                "elapsed_since_restart_s": round(elapsed_since_restart, 3),
                "watchdog_state": status.get("watchdog_state"),
            },
        )
        milestones["healthy_hold_bundle_written"] = True


def restart_engine(reason: str, *, status: dict[str, Any]) -> dict[str, Any]:
    restart_at = now_iso()
    log(f"Restarting rescue engine: {reason}")
    capture_decay_bundle(
        CONTEXT,
        event="watchdog_restart",
        reason=reason,
        extra={
            "previous_watchdog_state": status.get("watchdog_state"),
            "previous_last_restart_at": status.get("last_restart_at"),
        },
    )
    write_status(
        build_active_status(
            watchdog_state=f"restarting:{reason}",
            binary_path=str(RESCUE_BINARY),
            last_restart_at=restart_at,
            engine_pid=None,
            gpu_status="unavailable",
            ports_ready={"7878": False, "7879": False, "7880": False},
            last_health_at=None,
            telemetry_state="stale",
        )
    )
    subprocess.run(["launchctl", "kickstart", "-k", ENGINE_LABEL], check=False)
    time.sleep(2)
    return mark_state(
        "warmup",
        last_restart_at=restart_at,
        engine_pid=None,
        gpu_status="unavailable",
        ports_ready={"7878": False, "7879": False, "7880": False},
        last_health_at=None,
        telemetry_state_value="stale",
    )


def main() -> None:
    log("Minime rescue watchdog active")
    refresh_rescue_binary_from_profile()
    status = load_status()
    if status.get("mode") != "rescue_b8823ad":
        status = mark_state(
            "warmup",
            engine_pid=None,
            gpu_status="unavailable",
            ports_ready={"7878": False, "7879": False, "7880": False},
            last_health_at=None,
            telemetry_state_value="stale",
        )
    low_fill_checks = 0
    ready_checks = 0
    milestones = reset_milestones(status)

    while True:
        health_path = active_runtime_health_path(CONTEXT)
        last_restart_at = parse_status_time(status.get("last_restart_at"))
        elapsed_since_restart = time.time() - last_restart_at
        engine_pid = current_engine_pid()

        if engine_pid is None:
            status = restart_engine("process_absent", status=status)
            low_fill_checks = 0
            ready_checks = 0
            milestones = reset_milestones(status)
            continue

        health_payload, health_mtime = read_health_payload(health_path)
        health_fresh = health_mtime is not None and health_mtime > last_restart_at
        last_health_at = iso_from_timestamp(health_mtime)
        telemetry_state_value = telemetry_state(health_mtime=health_mtime, health_fresh=health_fresh)
        ports_ready = compute_ports_ready(engine_pid)
        gpu_status = rescue_gpu_status(
            ports_ready=ports_ready,
            health_fresh=health_fresh,
            telemetry_fresh=telemetry_state_value == "fresh",
        )

        if health_payload is not None:
            surface_state = "fresh" if health_fresh else "stale"
            mirror_spectral_from_health(
                health_payload=health_payload,
                last_restart_at=status.get("last_restart_at"),
                engine_pid=engine_pid,
                surface_state=surface_state,
            )

        ready_for_monitoring = health_fresh and all(ports_ready.get(port, False) for port in READY_PORTS)
        if ready_for_monitoring:
            ready_checks += 1
        else:
            ready_checks = 0

        monitoring_active = status.get("watchdog_state", "").startswith("monitoring")
        if milestones["restart_key"] != status.get("last_restart_at"):
            milestones = reset_milestones(status)
        if monitoring_active or ready_checks >= 2:
            monitoring_active = True
            if telemetry_state_value != "fresh":
                status = restart_engine("health_stale", status=status)
                low_fill_checks = 0
                ready_checks = 0
                milestones = reset_milestones(status)
                continue
            if not all(ports_ready.get(port, False) for port in READY_PORTS):
                status = restart_engine("ports_not_ready", status=status)
                low_fill_checks = 0
                ready_checks = 0
                milestones = reset_milestones(status)
                continue

            fill_pct = read_fill_pct(health_payload)
            if fill_pct is not None and fill_pct < LOW_FILL_THRESHOLD:
                low_fill_checks += 1
                if low_fill_checks >= LOW_FILL_CONSECUTIVE_LIMIT:
                    status = restart_engine("fill_below_threshold", status=status)
                    low_fill_checks = 0
                    ready_checks = 0
                    milestones = reset_milestones(status)
                    continue
            else:
                low_fill_checks = 0

            maybe_capture_milestones(
                milestones=milestones,
                fill_pct=fill_pct,
                elapsed_since_restart=elapsed_since_restart,
                status=status,
            )
            monitoring_state = "monitoring"
            if gpu_status != "confirmed":
                monitoring_state = "monitoring:degraded"
            status = mark_state(
                monitoring_state,
                last_restart_at=status.get("last_restart_at"),
                engine_pid=engine_pid,
                gpu_status=gpu_status,
                ports_ready=ports_ready,
                last_health_at=last_health_at,
                telemetry_state_value=telemetry_state_value,
            )
            time.sleep(CHECK_INTERVAL_SECS)
            continue

        low_fill_checks = 0
        if elapsed_since_restart > WARMUP_WINDOW_SECS:
            if telemetry_state_value != "fresh":
                status = restart_engine("health_stale", status=status)
                ready_checks = 0
                milestones = reset_milestones(status)
                continue
            if not all(ports_ready.get(port, False) for port in READY_PORTS):
                status = restart_engine("ports_not_ready", status=status)
                ready_checks = 0
                milestones = reset_milestones(status)
                continue

        status = mark_state(
            "warmup",
            last_restart_at=status.get("last_restart_at"),
            engine_pid=engine_pid,
            gpu_status=gpu_status,
            ports_ready=ports_ready,
            last_health_at=last_health_at,
            telemetry_state_value=telemetry_state_value,
        )

        time.sleep(CHECK_INTERVAL_SECS)


if __name__ == "__main__":
    main()
