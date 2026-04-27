#!/usr/bin/env python3
"""Stable-core operator helpers for Minime's post-rescue normal runtime."""

from __future__ import annotations

import argparse
import json
import math
import struct
import time
from pathlib import Path
from typing import Any

from minime_rescue_investigation import (
    DEFAULT_HOLD_WINDOW_SECS,
    STABLE_CORE_PROFILE,
    default_context,
    prepare_profile,
    write_json,
)

PROJECT_DIR = Path("/Users/v/other/minime")
WORKSPACE_DIR = PROJECT_DIR / "workspace"
STABLE_CORE_DIR = WORKSPACE_DIR / "stable_core"
AGENCY_PATH = WORKSPACE_DIR / "stable_core_agency.json"
STABLE_CORE_STATUS_PATH = WORKSPACE_DIR / "stable_core_status.json"
CHECKPOINT_QUARANTINE_DIR = WORKSPACE_DIR / "stable_core" / "checkpoint_quarantine"
AGENCY_STAGES = {
    "off": "disabled",
    "self_journal": "self_journal_only",
    "local_reflective": "local_reflective_only",
    "research_actions": "budgeted_research_actions",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def now_unix_s() -> float:
    return time.time()


def activate_stable_core(*, notes: str | None = None) -> dict[str, Any]:
    context = default_context()
    profile = prepare_profile(
        context,
        profile_name=STABLE_CORE_PROFILE,
        state_variant="current_live_workspace",
        hold_window_secs=DEFAULT_HOLD_WINDOW_SECS,
        matrix_run_id=None,
        notes=notes or "stable_core_v1_activation",
    )
    set_agency_stage("self_journal", reason="stable_core_v1_activation")
    return profile


def set_agency_stage(stage: str, *, reason: str | None = None) -> dict[str, Any]:
    if stage not in AGENCY_STAGES:
        allowed = ", ".join(sorted(AGENCY_STAGES))
        raise SystemExit(f"unknown stable-core agency stage '{stage}' (allowed: {allowed})")

    payload = {
        "stage": stage,
        "agent_budget_mode": AGENCY_STAGES[stage],
        "updated_at_unix_s": now_unix_s(),
        "reason": reason,
        "rollback_fill_pct": 82.0,
        "rollback_underfill_pct": 45.0,
        "semantic_energy_max": 0.05,
    }
    write_json(AGENCY_PATH, payload)

    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if isinstance(profile, dict) and profile:
        profile["stable_core_agency_stage"] = stage
        profile["stable_core_agent_budget"] = AGENCY_STAGES[stage]
        profile["stable_core_agent_enabled"] = stage != "off"
        profile["stable_core_agency_updated_at_unix_s"] = payload["updated_at_unix_s"]
        write_json(profile_path, profile)
    return payload


def build_status() -> dict[str, Any]:
    health = load_json(WORKSPACE_DIR / "health.json", {})
    rescue_status = load_json(WORKSPACE_DIR / "rescue_status.json", {})
    profile = load_json(WORKSPACE_DIR / "rescue_profile.json", {})
    agency = load_json(AGENCY_PATH, {})
    bridge_status = load_json(WORKSPACE_DIR / "runtime" / "bridge_limited_write_status.json", {})
    camera = load_json(WORKSPACE_DIR / "runtime" / "camera_status.json", {})
    mic = load_json(WORKSPACE_DIR / "runtime" / "mic_status.json", {})
    stable_core_health = health.get("stable_core") if isinstance(health, dict) else {}

    payload = {
        "mode": "stable_core_v1" if profile.get("stable_core_enabled") else "inactive",
        "profile": profile.get("profile"),
        "runtime_profile": profile.get("runtime_profile"),
        "engine_pid": rescue_status.get("engine_pid"),
        "watchdog_state": rescue_status.get("watchdog_state"),
        "telemetry_state": rescue_status.get("telemetry_state"),
        "fill_pct": health.get("fill_pct") if isinstance(health, dict) else None,
        "stage": (health.get("rescue") or {}).get("stage") if isinstance(health, dict) else None,
        "semantic_energy": (health.get("semantic") or {}).get("energy")
        if isinstance(health, dict)
        else None,
        "stable_core": stable_core_health if isinstance(stable_core_health, dict) else {},
        "agency": agency,
        "bridge": {
            "send_count": bridge_status.get("send_count"),
            "rollback_at_unix_s": bridge_status.get("rollback_at_unix_s"),
            "rollback_reason": bridge_status.get("rollback_reason"),
        },
        "feeders": {
            "camera": {
                "state": camera.get("state"),
                "healthy": camera.get("healthy"),
                "connected": camera.get("connected"),
                "consecutive_failures": camera.get("consecutive_failures"),
            },
            "mic": {
                "state": mic.get("state"),
                "healthy": mic.get("healthy"),
                "connected": mic.get("connected"),
                "consecutive_failures": mic.get("consecutive_failures"),
            },
        },
        "updated_at_unix_s": now_unix_s(),
    }
    write_json(STABLE_CORE_STATUS_PATH, payload)
    return payload


def _read_f32_matrix(path: Path, dim: int) -> list[float]:
    data = path.read_bytes()
    expected = dim * dim * 4
    if len(data) != expected:
        raise SystemExit(f"checkpoint size mismatch: got {len(data)} bytes, expected {expected}")
    values = list(struct.unpack(f"<{dim * dim}f", data))
    if not all(math.isfinite(value) for value in values):
        raise SystemExit("checkpoint contains non-finite values")
    return values


def sanitize_checkpoint(source: Path, *, dim: int = 512) -> dict[str, Any]:
    values = _read_f32_matrix(source, dim)
    diagonal = [max(values[i * dim + i], 1e-3) for i in range(dim)]
    trace = sum(diagonal)
    if trace <= 0.0:
        raise SystemExit("checkpoint trace is not positive")
    scale = dim / trace
    sanitized = [0.0] * (dim * dim)
    for i, value in enumerate(diagonal):
        sanitized[i * dim + i] = value * scale

    CHECKPOINT_QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHECKPOINT_QUARANTINE_DIR / "stable_core_spectral_seed.bin"
    with out_path.open("wb") as handle:
        for value in sanitized:
            handle.write(struct.pack("<f", float(value)))

    off_diag_abs = sum(
        abs(value) for idx, value in enumerate(values) if idx // dim != idx % dim
    )
    diag_abs = sum(abs(value) for idx, value in enumerate(values) if idx // dim == idx % dim)
    summary = {
        "source": str(source),
        "sanitized_path": str(out_path),
        "matrix_dim": dim,
        "input_trace": trace,
        "output_trace": float(dim),
        "off_diag_abs_ratio": off_diag_abs / max(diag_abs, 1e-6),
        "policy": "diagonal_only_trace_normalized",
        "checkpoint_lineage": "quarantined",
        "created_at_unix_s": now_unix_s(),
    }
    write_json(CHECKPOINT_QUARANTINE_DIR / "manifest.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stable-core operator helper")
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on")
    on.add_argument("--notes")
    stage = sub.add_parser("stage-set")
    stage.add_argument("stage", choices=sorted(AGENCY_STAGES))
    stage.add_argument("--reason")
    sub.add_parser("status")
    sanitize = sub.add_parser("checkpoint-sanitize")
    sanitize.add_argument(
        "source",
        nargs="?",
        default=str(WORKSPACE_DIR / "spectral_checkpoint_stable.bin"),
    )
    sanitize.add_argument("--dim", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "on":
        print(json.dumps(activate_stable_core(notes=args.notes), indent=2, sort_keys=True))
    elif args.command == "stage-set":
        print(json.dumps(set_agency_stage(args.stage, reason=args.reason), indent=2, sort_keys=True))
    elif args.command == "status":
        print(json.dumps(build_status(), indent=2, sort_keys=True))
    elif args.command == "checkpoint-sanitize":
        print(
            json.dumps(
                sanitize_checkpoint(Path(args.source), dim=args.dim),
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
