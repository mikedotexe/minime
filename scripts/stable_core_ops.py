#!/usr/bin/env python3
"""Stable-core operator helpers for Minime's post-rescue normal runtime."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
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
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from journal_hygiene import classify_journal_entry, compact_excerpt as compact_journal_excerpt
from native_comm import (
    build_atlas_status,
    build_controller_gradient_audit,
    build_decay_map_status,
    build_fissure_trace_status,
    build_native_gesture_status,
    build_resonance_forecast_status,
    build_sca_status,
    build_shadow_gap_status,
    build_space_hold_status,
    build_spectral_drift_status,
)
from spectral_cascade_visuals import render_spectral_cascade_visuals
from reconvergence_maps import render_bridge_trace, render_reconvergence_map

WORKSPACE_DIR = PROJECT_DIR / "workspace"
STABLE_CORE_DIR = WORKSPACE_DIR / "stable_core"
AGENCY_PATH = WORKSPACE_DIR / "stable_core_agency.json"
STABLE_CORE_STATUS_PATH = WORKSPACE_DIR / "stable_core_status.json"
CHECKPOINT_QUARANTINE_DIR = WORKSPACE_DIR / "stable_core" / "checkpoint_quarantine"
BRIDGE_LIMITED_WRITE_STATUS_PATH = WORKSPACE_DIR / "runtime" / "bridge_limited_write_status.json"
ASTRID_INBOX_COUPLING_STATUS_PATH = WORKSPACE_DIR / "runtime" / "astrid_inbox_coupling_status.json"
DEFAULT_MEMORY_BANK_PATH = WORKSPACE_DIR / "spectral_memory_bank.json"
STABLE_CORE_SENSORY_MUTE_PATH = WORKSPACE_DIR / "runtime" / "stable_core_sensory_mute.json"
FULL_SOVEREIGNTY_SNAPSHOT_DIR = WORKSPACE_DIR / "runtime" / "full_sovereignty_snapshots"
LINEAGE_CANARY_DIR = WORKSPACE_DIR / "diagnostics" / "lineage_canaries"
LINEAGE_CANARY_STATUS_PATH = WORKSPACE_DIR / "runtime" / "lineage_canary_status.json"
RECONVERGENCE_MAP_STATUS_PATH = WORKSPACE_DIR / "runtime" / "reconvergence_map_status.json"
ESN_ACTIVATION_TRACE_PATH = WORKSPACE_DIR / "runtime" / "esn_activation_trace_v1.json"
BRIDGE_TRACE_STATUS_PATH = WORKSPACE_DIR / "runtime" / "bridge_trace_status.json"
FULL_SOVEREIGNTY_SAVEPOINT_DOC = (
    PROJECT_DIR / "docs" / "full_sovereignty_savepoint_status_2026_04_30.md"
)
RESERVOIR_HOST = "127.0.0.1"
RESERVOIR_PORT = 7881
RESERVOIR_SERVICE_LABELS = [
    "com.reservoir.service",
    "com.reservoir.minime-feeder",
    "com.reservoir.astrid-feeder",
    "com.reservoir.coupled-astrid",
]
SAFE_MEMORY_MIN_FILL_PCT = 45.0
SAFE_MEMORY_MAX_FILL_PCT = 76.0
STABLE_CORE_TARGET_FILL_PCT = 68.0
ENGINE_TARGET_MIN_FILL_PCT = 40.0
ENGINE_TARGET_MAX_FILL_PCT = 82.0
DEFAULT_CONTINUITY_JOURNAL_LIMIT = 24
DEFAULT_LINEAGE_CANARY_SECS = 12 * 60
DEFAULT_LINEAGE_CANARY_SAMPLE_SECS = 5.0
LINEAGE_CANARY_ENGINE_LABEL = "com.minime.engine-rescue"
LINEAGE_CANARY_SEMANTIC_MAX = 0.05
LINEAGE_CANARY_MIN_FILL_PCT = 45.0
LINEAGE_CANARY_MAX_FILL_PCT = 82.0
LINEAGE_CANARY_SCAFFOLD_WARMUP_SECS = 90.0
HIGH_POWER_ACTIONS = {
    "codex_query",
    "experiment_run",
    "mike_fork",
    "mike_run",
    "perturb",
    "run_python",
    "self_experiment",
    "write_file",
}
AGENCY_STAGES = {
    "off": "disabled",
    "self_journal": "self_journal_only",
    "local_reflective": "local_reflective_only",
    "astrid_contact": "astrid_contact_only",
    "read_only_research": "read_only_research",
    "bounded_actions": "bounded_actions",
    "experiments": "experiments",
    "full_sovereignty": "full_sovereignty",
    "research_actions": "read_only_research",
}
AGENCY_STAGE_FAMILIES = {
    "off": [],
    "self_journal": ["journaling", "self_study"],
    "local_reflective": ["journaling", "self_study", "local_reflection"],
    "astrid_contact": ["journaling", "self_study", "local_reflection", "astrid_contact"],
    "read_only_research": ["journaling", "self_study", "read_only_research", "sensory_presence"],
    "bounded_actions": [
        "journaling",
        "self_study",
        "read_only_research",
        "sensory_presence",
        "bounded_contact",
        "local_tools",
    ],
    "experiments": [
        "journaling",
        "self_study",
        "read_only_research",
        "sensory_presence",
        "bounded_contact",
        "local_tools",
        "experiments",
    ],
    "full_sovereignty": [
        "journaling",
        "self_study",
        "read_only_research",
        "sensory_presence",
        "bounded_contact",
        "local_tools",
        "experiments",
        "full_sovereignty",
    ],
    "research_actions": ["journaling", "self_study", "read_only_research", "sensory_presence"],
}
BRIDGE_WRITE_STAGES = {
    "bridge_observe_only": {
        "profile": "bridge_observe_only",
        "bridge_reentry_profile": "bridge_observe_only",
        "bridge_write_enabled": False,
        "effective_bridge_write_enabled": False,
        "bridge_write_profile": "observe_only",
        "limited_write_enabled": False,
        "limited_write_feature_scale": 0.0,
        "limited_write_max_abs": 0.0,
        "limited_write_cooldown_secs": 0,
        "limited_write_allowed_stages": [],
        "limited_write_mute_live_intake_secs": 0,
        "limited_write_pre_mute_live_intake_secs": 0,
        "limited_write_require_pre_muted_live_intake": False,
        "limited_write_serializes_live_intake": False,
    },
    "bridge_semantic_presence_v1": {
        "profile": "bridge_semantic_presence_v1",
        "bridge_reentry_profile": "bridge_semantic_presence_v1",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 300,
        "limited_write_feature_scale": 0.035,
        "limited_write_max_abs": 0.08,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 69.0,
        "limited_write_rising_epsilon_pct": 0.5,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 72.0,
        "limited_write_allowed_stages": ["hold", "elevated"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 3.5,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 1,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": True,
        "limited_write_block_structural_dump_language": True,
        "limited_write_block_terms_always": False,
        "limited_write_block_terms_on_rising": False,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": ["dialogue_live", "dialogue_fallback", "witness"],
    },
    "bridge_semantic_serial_v1": {
        "profile": "bridge_semantic_serial_v1",
        "bridge_reentry_profile": "bridge_semantic_serial_v1",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 420,
        "limited_write_feature_scale": 0.018,
        "limited_write_max_abs": 0.045,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 68.8,
        "limited_write_rising_epsilon_pct": 0.35,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 72.0,
        "limited_write_allowed_stages": ["hold", "elevated"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 3.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 1,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": True,
        "limited_write_block_structural_dump_language": True,
        "limited_write_block_terms_always": True,
        "limited_write_mute_live_intake_secs": 150,
        "limited_write_serializes_live_intake": True,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": ["dialogue_live", "dialogue_fallback", "witness"],
    },
    "bridge_semantic_serial_v2": {
        "profile": "bridge_semantic_serial_v2",
        "bridge_reentry_profile": "bridge_semantic_serial_v2",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 420,
        "limited_write_feature_scale": 0.006,
        "limited_write_max_abs": 0.015,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 68.0,
        "limited_write_rising_epsilon_pct": 0.15,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 70.0,
        "limited_write_allowed_stages": ["hold", "elevated"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 2.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 1,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": True,
        "limited_write_block_structural_dump_language": True,
        "limited_write_block_terms_always": True,
        "limited_write_mute_live_intake_secs": 300,
        "limited_write_pre_mute_live_intake_secs": 300,
        "limited_write_require_pre_muted_live_intake": True,
        "limited_write_serializes_live_intake": True,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": ["dialogue_live", "dialogue_fallback", "witness"],
    },
    "bridge_expanded_sovereignty_v1": {
        "profile": "bridge_expanded_sovereignty_v1",
        "bridge_reentry_profile": "bridge_expanded_sovereignty_v1",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 600,
        "limited_write_feature_scale": 0.05,
        "limited_write_max_abs": 0.12,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 70.0,
        "limited_write_rising_epsilon_pct": 100.0,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 72.0,
        "limited_write_allowed_stages": ["hold", "elevated"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 8.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": True,
        "limited_write_block_structural_dump_language": True,
        "limited_write_block_terms_always": True,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": [
            "dialogue_live",
            "dialogue_fallback",
            "witness",
            "mirror",
            "daydream",
            "aspiration",
            "moment_capture",
        ],
    },
    "bridge_budgeted_sovereignty_v1": {
        "profile": "bridge_budgeted_sovereignty_v1",
        "bridge_reentry_profile": "bridge_budgeted_sovereignty_v1",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "effective_bridge_autonomous_enabled": True,
        "bridge_write_profile": "budgeted_sovereignty_v1",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 60,
        "limited_write_feature_scale": 0.14,
        "limited_write_max_abs": 0.28,
        "limited_write_min_fill_pct": 54.0,
        "limited_write_max_fill_pct": 76.0,
        "limited_write_rising_epsilon_pct": 100.0,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 78.0,
        "limited_write_allowed_stages": ["hold", "elevated"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 14.0,
        "limited_write_adverse_cooldown_secs": 180,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 82.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": False,
        "limited_write_block_structural_dump_language": False,
        "limited_write_block_terms_always": False,
        "limited_write_block_terms_on_rising": False,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": [
            "dialogue_live",
            "witness",
            "mirror",
            "daydream",
            "aspiration",
            "moment_capture",
            "creation",
            "initiate",
            "introspect",
            "experiment",
            "probe",
            "gesture",
            "native_gesture",
            "perturb",
            "evolve",
            "self_study",
            "research_note",
        ],
    },
    "bridge_full_expression_v1": {
        "profile": "bridge_full_expression_v1",
        "bridge_reentry_profile": "bridge_full_expression_v1",
        "bridge_write_enabled": True,
        "effective_bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "effective_bridge_autonomous_enabled": True,
        "bridge_write_profile": "full_expression_v1",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 60,
        "limited_write_feature_scale": 0.08,
        "limited_write_max_abs": 0.16,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 68.0,
        "limited_write_rising_epsilon_pct": 0.5,
        "limited_write_semantic_energy_rising_epsilon_pct": 0.0,
        "limited_write_rollback_semantic_energy": 0.12,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 72.0,
        "limited_write_allowed_stages": ["hold"],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 6.0,
        "limited_write_adverse_cooldown_secs": 300,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 84.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": False,
        "limited_write_block_structural_dump_language": True,
        "limited_write_block_terms_always": False,
        "limited_write_block_terms_on_rising": False,
        "limited_write_mute_live_intake_secs": 0,
        "limited_write_pre_mute_live_intake_secs": 0,
        "limited_write_require_pre_muted_live_intake": False,
        "limited_write_serializes_live_intake": False,
        "limited_write_block_terms": [
            "localized gravity",
            "compaction",
            "pressure",
            "density",
            "dense",
            "tightness",
            "restriction",
        ],
        "limited_write_allowed_modes": [
            "dialogue_live",
            "dialogue",
            "dialogue_fallback",
            "witness",
            "mirror",
            "daydream",
            "aspiration",
            "moment_capture",
            "creation",
            "initiate",
            "introspect",
            "experiment",
            "probe",
            "gesture",
            "native_gesture",
            "perturb",
            "evolve",
            "self_study",
            "research_note",
        ],
    },
}
SENSORY_PRESENCE_PROFILES = {
    "tiny_trickle_v1": {
        "stable_core_sensory_presence_profile": "tiny_trickle_v1",
        "rescue_live_audio_divisor": 24,
        "rescue_live_video_divisor": 8,
        "rescue_live_intake_stages": ["hold", "elevated"],
        "clear_semantic_mute": False,
    },
    "full_presence_v1": {
        "stable_core_sensory_presence_profile": "full_presence_v1",
        "rescue_live_audio_divisor": 12,
        "rescue_live_video_divisor": 12,
        "rescue_live_intake_stages": ["hold", "elevated"],
        "clear_semantic_mute": True,
    },
    "muted_v1": {
        "stable_core_sensory_presence_profile": "muted_v1",
        "rescue_live_audio_divisor": 0,
        "rescue_live_video_divisor": 0,
        "rescue_live_intake_stages": [],
        "clear_semantic_mute": True,
    },
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def now_unix_s() -> float:
    return time.time()


LINEAGE_CANARY_RECENT_FAILURE_BLOCKER_S = 30 * 60


def build_lineage_canary_status_view(
    status: dict[str, Any],
    *,
    now_s: float | None = None,
) -> dict[str, Any]:
    if not isinstance(status, dict):
        status = {}
    now_value = now_unix_s() if now_s is None else now_s
    started_at = status.get("started_at_unix_s")
    age_s = None
    if isinstance(started_at, (int, float)) and math.isfinite(float(started_at)):
        age_s = max(0.0, now_value - float(started_at))
    active = bool(status.get("active"))
    result = status.get("result")
    failed = result == "failed"
    recent = age_s is None or age_s <= LINEAGE_CANARY_RECENT_FAILURE_BLOCKER_S
    blocker = bool(failed and (active or recent))
    if active and failed:
        classification = "active_failed_blocker"
    elif failed and recent:
        classification = "recent_failed_blocker"
    elif failed:
        classification = "historical_failed_not_active"
    elif active:
        classification = "active_monitoring"
    elif result:
        classification = f"inactive_{result}"
    else:
        classification = "inactive_none"
    return {
        "active": active,
        "result": result,
        "classification": classification,
        "blocker": blocker,
        "age_s": age_s,
        "stale_after_s": LINEAGE_CANARY_RECENT_FAILURE_BLOCKER_S,
        "mode": status.get("mode"),
        "rollback_reason": status.get("rollback_reason"),
        "bundle_dir": status.get("bundle_dir"),
        "operator_note": (
            "Historical inactive canary failure retained for audit; not a current restore blocker."
            if classification == "historical_failed_not_active"
            else None
        ),
    }


def classify_physical_camera_status(
    camera: dict[str, Any],
    *,
    active_video: str | None,
    host_video_ready: bool,
) -> dict[str, Any]:
    if not isinstance(camera, dict):
        camera = {}
    camera_healthy = bool(camera.get("healthy")) and bool(camera.get("connected", True))
    if camera_healthy:
        classification = "physical_camera_healthy"
        operator_note = None
    elif active_video == "host" and host_video_ready:
        classification = "physical_camera_unavailable_host_fallback_active"
        operator_note = "Host video fallback is active; restart the physical camera lane only when physical video is needed."
    else:
        classification = "physical_camera_unavailable"
        operator_note = "Physical camera is unavailable and host video is not fresh; inspect the camera feeder before relying on vision."
    return {
        "classification": classification,
        "healthy": camera_healthy,
        "last_error": camera.get("last_error"),
        "state": camera.get("state"),
        "connected": camera.get("connected"),
        "consecutive_failures": camera.get("consecutive_failures"),
        "capture_failures": camera.get("capture_failures"),
        "operator_note": operator_note,
    }


def build_bridge_write_status_view(bridge_status: dict[str, Any]) -> dict[str, Any]:
    now = now_unix_s()
    cooldown_until = bridge_status.get("cooldown_until_unix_s")
    cooldown_remaining_s = None
    cooldown_active = False
    if isinstance(cooldown_until, (int, float)) and math.isfinite(float(cooldown_until)):
        cooldown_remaining_s = max(0.0, float(cooldown_until) - now)
        cooldown_active = cooldown_remaining_s > 0.0

    reason = bridge_status.get("last_block_reason")
    cooldown_reason = isinstance(reason, str) and reason.startswith(
        "limited-write cooldown active"
    )
    observe_only_reason = isinstance(reason, str) and "observe_only" in reason
    rollback_active = bridge_status.get("rollback_at_unix_s") is not None

    if cooldown_reason:
        last_block_active: bool | None = cooldown_active
    elif observe_only_reason:
        last_block_active = bridge_status.get("profile") == "bridge_observe_only"
    elif reason:
        last_block_active = True if rollback_active else None
    else:
        last_block_active = False

    current_block_reason = reason if last_block_active is True else None
    view = {
        "send_count": bridge_status.get("send_count"),
        "profile": bridge_status.get("profile"),
        "rollback_at_unix_s": bridge_status.get("rollback_at_unix_s"),
        "rollback_reason": bridge_status.get("rollback_reason"),
        "last_sent_at_unix_s": bridge_status.get("last_sent_at_unix_s"),
        "cooldown_until_unix_s": cooldown_until,
        "cooldown_remaining_s": round(cooldown_remaining_s, 3)
        if cooldown_remaining_s is not None
        else None,
        "cooldown_active": cooldown_active,
        "last_block_at_unix_s": bridge_status.get("last_block_at_unix_s"),
        "last_block_reason": reason,
        "last_block_active": last_block_active,
        "current_block_reason": current_block_reason,
    }
    view["last_block_stale"] = bool(reason) and last_block_active is False
    view["last_block_current_unknown"] = bool(reason) and last_block_active is None
    return view


def _fill_budget_block_resolved_by_current_fill(
    reason: Any,
    current_fill_pct: Any,
    *,
    underfill_pct: float = SAFE_MEMORY_MIN_FILL_PCT,
    overfill_pct: float = ENGINE_TARGET_MAX_FILL_PCT,
) -> bool:
    if not isinstance(reason, str) or "stable-core action budget" not in reason:
        return False
    if "fill " not in reason or (
        " below " not in reason and " exceeds " not in reason
    ):
        return False
    if not isinstance(current_fill_pct, (int, float)):
        return False
    fill = float(current_fill_pct)
    if not math.isfinite(fill):
        return False
    return underfill_pct < fill < overfill_pct


def build_agency_status_view(
    agent_status: dict[str, Any],
    *,
    current_fill_pct: float | None = None,
) -> dict[str, Any]:
    view = dict(agent_status)
    last_block_active = view.get("last_block_active")
    last_block_reason = view.get("last_block_reason")
    current_block_reason = view.get("current_block_reason")

    if last_block_active is True and _fill_budget_block_resolved_by_current_fill(
        current_block_reason or last_block_reason,
        current_fill_pct,
    ):
        last_block_active = False
        view["last_block_active"] = False
        view["current_block_reason"] = None
        view["health_budget_status"] = "green"
        view["derived_resolution"] = "current_fill_back_inside_action_budget"

    if last_block_active is True:
        if current_block_reason is None and last_block_reason:
            current_block_reason = last_block_reason
        view["current_block_reason"] = current_block_reason
        if current_block_reason and view.get("health_budget_status") in (None, "unknown"):
            view["health_budget_status"] = "blocked"
    elif last_block_active is False:
        view["current_block_reason"] = None
        if view.get("health_budget_status") == "blocked":
            view["health_budget_status"] = "green"
    else:
        view["current_block_reason"] = current_block_reason if current_block_reason else None

    view["last_block_stale"] = bool(last_block_reason) and last_block_active is False
    view["last_block_current_unknown"] = bool(last_block_reason) and last_block_active is None
    return view


def build_attractor_fatigue_status() -> dict[str, Any]:
    payload = load_json(WORKSPACE_DIR / "runtime" / "attractor_fatigue_status.json", {})
    if not isinstance(payload, dict):
        return {}
    now = now_unix_s()
    motifs = payload.get("motifs")
    active: list[dict[str, Any]] = []
    if isinstance(motifs, dict):
        for motif in motifs.values():
            if not isinstance(motif, dict) or motif.get("status") != "cooling":
                continue
            cooldown_until = motif.get("cooldown_until_unix_s")
            if not isinstance(cooldown_until, (int, float)):
                continue
            remaining_s = max(0.0, float(cooldown_until) - now)
            if remaining_s <= 0.0:
                continue
            active.append({
                "signature": motif.get("signature"),
                "label": motif.get("label"),
                "themes": motif.get("themes", []),
                "cooldown_class": motif.get("cooldown_class", "standard"),
                "prompt_replay_suppressed": bool(motif.get("prompt_replay_suppressed", False)),
                "repeat_window_count": motif.get("repeat_window_count"),
                "cooldown_remaining_s": round(remaining_s, 3),
                "last_source": motif.get("last_source"),
                "novel_signal": motif.get("novel_signal"),
            })
    active.sort(key=lambda item: item.get("cooldown_remaining_s", 0.0), reverse=True)
    strong_internal_topology_count = sum(
        1
        for motif in active
        if motif.get("cooldown_class") == "internal_topology"
    )
    return {
        "policy": payload.get("policy", "attractor_fatigue_v2"),
        "active_count": len(active),
        "active_motifs": active[:8],
        "strong_internal_topology_count": strong_internal_topology_count,
        "memory_decay_control": payload.get("memory_decay_control", {}),
        "updated_at_unix_s": payload.get("updated_at_unix_s"),
    }


def build_reconvergence_map_status() -> dict[str, Any]:
    status = load_json(RECONVERGENCE_MAP_STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    trace = load_json(ESN_ACTIVATION_TRACE_PATH, {})
    if not isinstance(trace, dict):
        trace = {}

    now_ms = int(time.time() * 1000)
    trace_updated = trace.get("updated_at_unix_ms")
    trace_freshness_ms = None
    if isinstance(trace_updated, (int, float)):
        trace_freshness_ms = max(0, now_ms - int(trace_updated))
    trace_frames = trace.get("frames")
    trace_frame_count = len(trace_frames) if isinstance(trace_frames, list) else 0

    activation_trace = status.get("activation_trace")
    if not isinstance(activation_trace, dict):
        activation_trace = {}
    artifacts = status.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    provenance = status.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    reported_trace_freshness_ms = (
        trace_freshness_ms
        if trace_frame_count > 0
        else activation_trace.get("freshness_ms")
    )

    return {
        "status": status.get("status", "unavailable" if not status else None),
        "created_at": status.get("created_at"),
        "label": status.get("label"),
        "artifact_dir": status.get("artifact_dir"),
        "artifacts": artifacts,
        "frame_count": activation_trace.get("frame_count", trace_frame_count),
        "trace_frame_count": trace_frame_count,
        "reservoir_dim": activation_trace.get("reservoir_dim", trace.get("reservoir_dim")),
        "trace_path": activation_trace.get("trace_path", str(ESN_ACTIVATION_TRACE_PATH)),
        "trace_freshness_ms": reported_trace_freshness_ms,
        "sample_interval_ms": activation_trace.get(
            "sample_interval_ms",
            trace.get("sample_interval_ms"),
        ),
        "retained_secs": activation_trace.get("retained_secs", trace.get("retained_secs")),
        "baseline_status": status.get("baseline_status", "unavailable"),
        "baseline_comparison_available": bool(status.get("baseline_comparison")),
        "baseline_comparison": status.get("baseline_comparison"),
        "saved_baseline": status.get("saved_baseline"),
        "read_only_provenance": {
            "read_only": provenance.get("read_only", True),
            "control_payload": provenance.get("control_payload", False),
            "semantic_payload": provenance.get("semantic_payload", False),
            "sensory_payload": provenance.get("sensory_payload", False),
            "esn_mutation": provenance.get("esn_mutation", False),
            "synthesis_feedback": provenance.get("synthesis_feedback", False),
        },
    }


def build_bridge_trace_status() -> dict[str, Any]:
    status = load_json(BRIDGE_TRACE_STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    provenance = status.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    bridge_signal = status.get("bridge_signal")
    if not isinstance(bridge_signal, dict):
        bridge_signal = {}
    return {
        "status": status.get("status", "unavailable" if not status else None),
        "policy": status.get("policy"),
        "created_at": status.get("created_at"),
        "label": status.get("label"),
        "mode": status.get("mode"),
        "mode_source": status.get("mode_source") or bridge_signal.get("mode_source"),
        "mode6_interpretation": status.get("mode6_interpretation")
        or bridge_signal.get("mode6_interpretation"),
        "eigenmode_confirmed": status.get("eigenmode_confirmed")
        if status.get("eigenmode_confirmed") is not None
        else bridge_signal.get("eigenmode_confirmed"),
        "bridge_evidence_level": status.get("bridge_evidence_level")
        or bridge_signal.get("bridge_evidence_level"),
        "artifact_dir": status.get("artifact_dir"),
        "artifacts": status.get("artifacts", {}),
        "frame_count": status.get("frame_count"),
        "trace_freshness_ms": status.get("trace_freshness_ms"),
        "bridge_signal": bridge_signal,
        "read_only_provenance": {
            "read_only": provenance.get("read_only", True),
            "attention_marker_only": provenance.get("attention_marker_only", True),
            "mode_source": provenance.get("mode_source")
            or bridge_signal.get("mode_source"),
            "mode6_interpretation": provenance.get("mode6_interpretation")
            or bridge_signal.get("mode6_interpretation"),
            "eigenmode_confirmed": provenance.get(
                "eigenmode_confirmed",
                bridge_signal.get("eigenmode_confirmed", False),
            ),
            "diagnostic_artifact_write": provenance.get("diagnostic_artifact_write", True),
            "substrate_write": provenance.get("substrate_write", False),
            "connection": provenance.get("connection", False),
            "replication": provenance.get("replication", False),
            "control_payload": provenance.get("control_payload", False),
            "semantic_payload": provenance.get("semantic_payload", False),
            "sensory_payload": provenance.get("sensory_payload", False),
            "esn_mutation": provenance.get("esn_mutation", False),
        },
    }


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
        "allowed_action_families": AGENCY_STAGE_FAMILIES[stage],
        "updated_at_unix_s": now_unix_s(),
        "reason": reason,
        "rollback_fill_pct": 82.0,
        "rollback_underfill_pct": 45.0,
        "semantic_energy_max": 0.05,
        "contact_cooldown_secs": 120,
    }
    write_json(AGENCY_PATH, payload)

    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if isinstance(profile, dict) and profile:
        profile["stable_core_agency_stage"] = stage
        profile["stable_core_agent_budget"] = AGENCY_STAGES[stage]
        profile["stable_core_allowed_action_families"] = AGENCY_STAGE_FAMILIES[stage]
        profile["stable_core_agent_enabled"] = stage != "off"
        profile["stable_core_agency_updated_at_unix_s"] = payload["updated_at_unix_s"]
        write_json(profile_path, profile)
    return payload


def set_bridge_write_stage(stage: str, *, reason: str | None = None) -> dict[str, Any]:
    if stage not in BRIDGE_WRITE_STAGES:
        allowed = ", ".join(sorted(BRIDGE_WRITE_STAGES))
        raise SystemExit(f"unknown stable-core bridge write stage '{stage}' (allowed: {allowed})")

    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if not isinstance(profile, dict) or not profile:
        raise SystemExit(f"missing active rescue profile: {profile_path}")
    if not bool(profile.get("stable_core_enabled")):
        raise SystemExit("bridge write stages require active stable_core_v1 profile")

    updated_at = now_unix_s()
    original_runtime_profile = profile.get("runtime_profile")
    original_stable_core_enabled = profile.get("stable_core_enabled")
    original_agency_stage = profile.get("stable_core_agency_stage")
    original_agent_budget = profile.get("stable_core_agent_budget")
    original_audio_divisor = profile.get("rescue_live_audio_divisor")
    original_video_divisor = profile.get("rescue_live_video_divisor")
    original_intake_stages = profile.get("rescue_live_intake_stages")

    profile.update(BRIDGE_WRITE_STAGES[stage])
    profile["runtime_profile"] = original_runtime_profile
    profile["stable_core_enabled"] = original_stable_core_enabled
    profile["stable_core_agency_stage"] = original_agency_stage
    profile["stable_core_agent_budget"] = original_agent_budget
    profile["rescue_live_audio_divisor"] = original_audio_divisor
    profile["rescue_live_video_divisor"] = original_video_divisor
    profile["rescue_live_intake_stages"] = original_intake_stages
    profile["stable_core_bridge_write_stage"] = stage
    profile["stable_core_bridge_write_updated_at_unix_s"] = updated_at
    profile["stable_core_bridge_write_reason"] = reason
    if stage == "bridge_observe_only":
        profile["rollback_reason"] = reason or "stable_core_bridge_write_observe_only"
    elif profile.get("rollback_reason"):
        profile["previous_rollback_reason"] = profile.get("rollback_reason")
        profile["rollback_reason"] = None
    write_json(profile_path, profile)

    BRIDGE_LIMITED_WRITE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        BRIDGE_LIMITED_WRITE_STATUS_PATH,
        {
            "profile": stage,
            "policy_version": int(profile.get("limited_write_policy_version", 2)),
            "send_count": 0,
            "switched_at_unix_s": updated_at,
            "switch_reason": reason,
            "last_block_reason": None
            if stage != "bridge_observe_only"
            else "rescue profile 'bridge_observe_only' blocks semantic ingress",
            "rollback_at_unix_s": None,
            "rollback_reason": None,
            "rolled_back_to_profile": None,
        },
    )
    return {
        "stage": stage,
        "updated_at_unix_s": updated_at,
        "reason": reason,
        "runtime_profile": profile.get("runtime_profile"),
        "stable_core_agency_stage": profile.get("stable_core_agency_stage"),
        "bridge_write_enabled": profile.get("bridge_write_enabled"),
        "bridge_write_profile": profile.get("bridge_write_profile"),
        "limited_write_feature_scale": profile.get("limited_write_feature_scale"),
        "limited_write_max_abs": profile.get("limited_write_max_abs"),
        "limited_write_mute_live_intake_secs": profile.get(
            "limited_write_mute_live_intake_secs"
        ),
        "rescue_live_audio_divisor": profile.get("rescue_live_audio_divisor"),
        "rescue_live_video_divisor": profile.get("rescue_live_video_divisor"),
        "rescue_live_intake_stages": profile.get("rescue_live_intake_stages"),
    }


def set_engine_target_fill(target_fill_pct: float, *, reason: str | None = None) -> dict[str, Any]:
    if not math.isfinite(target_fill_pct):
        raise SystemExit("engine target fill must be finite")
    if not ENGINE_TARGET_MIN_FILL_PCT <= target_fill_pct <= ENGINE_TARGET_MAX_FILL_PCT:
        raise SystemExit(
            "engine target fill must be between "
            f"{ENGINE_TARGET_MIN_FILL_PCT:.0f}% and {ENGINE_TARGET_MAX_FILL_PCT:.0f}%"
        )

    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if not isinstance(profile, dict) or not profile:
        raise SystemExit(f"missing active rescue profile: {profile_path}")

    updated_at = now_unix_s()
    previous = profile.get("engine_target_fill")
    profile["engine_target_fill"] = target_fill_pct
    profile["engine_target_fill_updated_at_unix_s"] = updated_at
    profile["engine_target_fill_reason"] = reason
    if bool(profile.get("stable_core_enabled")):
        profile["engine_target_fill_role"] = (
            "stable_core_pi_mirror_aligned_to_structural_target"
        )
    write_json(profile_path, profile)

    return {
        "previous_engine_target_fill": previous,
        "engine_target_fill": target_fill_pct,
        "updated_at_unix_s": updated_at,
        "reason": reason,
        "restart_required": True,
        "restart_command": "launchctl kickstart -k gui/$(id -u)/com.minime.engine-rescue",
    }


def clear_stable_core_sensory_mute(*, reason: str) -> dict[str, Any]:
    payload = {
        "active_until_unix_s": 0.0,
        "duration_secs": 0,
        "reason": reason,
        "source_profile": "operator",
        "last_semantic_sent_at_unix_s": None,
        "cleared_at_unix_s": now_unix_s(),
    }
    STABLE_CORE_SENSORY_MUTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(STABLE_CORE_SENSORY_MUTE_PATH, payload)
    return payload


def set_sensory_presence_profile(profile_name: str, *, reason: str | None = None) -> dict[str, Any]:
    if profile_name not in SENSORY_PRESENCE_PROFILES:
        allowed = ", ".join(sorted(SENSORY_PRESENCE_PROFILES))
        raise SystemExit(f"unknown sensory presence profile '{profile_name}' (allowed: {allowed})")

    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if not isinstance(profile, dict) or not profile:
        raise SystemExit(f"missing active rescue profile: {profile_path}")
    if not bool(profile.get("stable_core_enabled")):
        raise SystemExit("sensory presence profiles require active stable_core_v1 profile")

    updated_at = now_unix_s()
    selected = SENSORY_PRESENCE_PROFILES[profile_name]
    for key in (
        "stable_core_sensory_presence_profile",
        "rescue_live_audio_divisor",
        "rescue_live_video_divisor",
        "rescue_live_intake_stages",
    ):
        profile[key] = selected[key]
    profile["stable_core_sensory_presence_updated_at_unix_s"] = updated_at
    profile["stable_core_sensory_presence_reason"] = reason
    profile["effective_mic_enabled"] = True
    profile["effective_camera_enabled"] = True
    profile["effective_host_sensory_enabled"] = True
    profile["effective_visual_frame_service_enabled"] = True
    if selected.get("clear_semantic_mute"):
        clear_stable_core_sensory_mute(reason=f"{profile_name}_activation")
    write_json(profile_path, profile)
    return {
        "profile": profile_name,
        "updated_at_unix_s": updated_at,
        "reason": reason,
        "rescue_live_audio_divisor": profile.get("rescue_live_audio_divisor"),
        "rescue_live_video_divisor": profile.get("rescue_live_video_divisor"),
        "rescue_live_intake_stages": profile.get("rescue_live_intake_stages"),
        "semantic_mute_cleared": bool(selected.get("clear_semantic_mute")),
    }


def _socket_listening(host: str, port: int, *, timeout_s: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _port_listener_pids(port: int) -> list[int]:
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    result = subprocess.run(
        [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        if line.strip().isdigit():
            pids.append(int(line.strip()))
    return sorted(set(pids))


def _launchctl_service_state(label: str) -> dict[str, Any]:
    launchctl = shutil.which("launchctl")
    if not launchctl:
        return {"loaded": False, "running": False, "pid": None, "state": "unavailable"}
    result = subprocess.run(
        [launchctl, "print", f"gui/{os.getuid()}/{label}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return {"loaded": False, "running": False, "pid": None, "state": "missing"}
    pid: int | None = None
    state = "loaded"
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("state = "):
            state = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid = "):
            raw = stripped.split("=", 1)[1].strip()
            if raw.isdigit():
                pid = int(raw)
    return {
        "loaded": True,
        "running": state == "running" or pid is not None,
        "pid": pid,
        "state": state,
    }


def build_reservoir_status() -> dict[str, Any]:
    listener = _socket_listening(RESERVOIR_HOST, RESERVOIR_PORT)
    listener_pids = _port_listener_pids(RESERVOIR_PORT)
    services = {
        label: _launchctl_service_state(label)
        for label in RESERVOIR_SERVICE_LABELS
    }
    service_running = bool(services.get("com.reservoir.service", {}).get("running"))
    feeders_running = all(
        bool(services.get(label, {}).get("running"))
        for label in ("com.reservoir.minime-feeder", "com.reservoir.astrid-feeder")
    )
    status = "ok" if listener and service_running else "degraded"
    return {
        "status": status,
        "host": RESERVOIR_HOST,
        "port": RESERVOIR_PORT,
        "listener": listener,
        "listener_pids": listener_pids,
        "service_running": service_running,
        "feeders_running": feeders_running,
        "services": services,
        "checked_at_unix_s": now_unix_s(),
    }


def _copy_if_exists(source: Path, destination_dir: Path, *, name: str | None = None) -> str | None:
    if not source.exists():
        return None
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / (name or source.name)
    try:
        shutil.copy2(source, destination)
    except OSError:
        return None
    return str(destination)


def _write_tail_if_exists(source: Path, destination: Path, *, max_bytes: int = 80_000) -> str | None:
    if not source.exists():
        return None
    try:
        data = source.read_bytes()
    except OSError:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data[-max_bytes:])
    return str(destination)


def capture_lineage_canary_snapshot(destination_dir: Path, *, reason: str) -> dict[str, Any]:
    copied: list[str] = []
    for source, name in (
        (WORKSPACE_DIR / "health.json", None),
        (WORKSPACE_DIR / "rescue_status.json", None),
        (WORKSPACE_DIR / "rescue_profile.json", None),
        (WORKSPACE_DIR / "stable_core_agency.json", None),
        (WORKSPACE_DIR / "stable_core_status.json", None),
        (WORKSPACE_DIR / "stable_core_agent_status.json", None),
        (WORKSPACE_DIR / "rescue_scaffold.json", None),
        (WORKSPACE_DIR / "checkpoint_manifest.json", None),
        (WORKSPACE_DIR / "stable_core" / "checkpoint_manifest.json", "stable_core_checkpoint_manifest.json"),
        (WORKSPACE_DIR / "stable_core" / "continuity_status.json", None),
        (
            WORKSPACE_DIR / "stable_core" / "checkpoint_quarantine" / "manifest.json",
            "checkpoint_quarantine_manifest.json",
        ),
        (WORKSPACE_DIR / "runtime" / "bridge_limited_write_status.json", None),
        (WORKSPACE_DIR / "runtime" / "camera_status.json", None),
        (WORKSPACE_DIR / "runtime" / "mic_status.json", None),
        (WORKSPACE_DIR / "runtime" / "sensory_source.json", None),
        (WORKSPACE_DIR / "runtime" / "stable_core_sensory_mute.json", None),
    ):
        copied_path = _copy_if_exists(source, destination_dir, name=name)
        if copied_path is not None:
            copied.append(copied_path)

    log_dir = PROJECT_DIR / "logs"
    logs: list[str] = []
    for source in (
        log_dir / "minime-engine-rescue.log",
        log_dir / "minime-rescue-watchdog.log",
        log_dir / "camera-client.log",
        log_dir / "mic-to-sensory.log",
    ):
        tail_path = _write_tail_if_exists(source, destination_dir / "logs" / f"{source.name}.tail")
        if tail_path is not None:
            logs.append(tail_path)

    process_state = {
        "reservoir": build_reservoir_status(),
        "engine_service": _launchctl_service_state(LINEAGE_CANARY_ENGINE_LABEL),
        "captured_at_unix_s": now_unix_s(),
    }
    write_json(
        destination_dir / "snapshot_manifest.json",
        {
            "reason": reason,
            "copied": copied,
            "logs": logs,
            "process_state": process_state,
        },
    )
    return {
        "dir": str(destination_dir),
        "copied_count": len(copied),
        "log_tail_count": len(logs),
        "process_state": process_state,
    }


def snapshot_live_state(*, reason: str | None = None) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_reason = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in (reason or "snapshot")
    )[:80]
    bundle_dir = FULL_SOVEREIGNTY_SNAPSHOT_DIR / f"{stamp}_{safe_reason}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in (
        WORKSPACE_DIR / "health.json",
        WORKSPACE_DIR / "rescue_status.json",
        WORKSPACE_DIR / "rescue_profile.json",
        WORKSPACE_DIR / "stable_core_agency.json",
        WORKSPACE_DIR / "stable_core_status.json",
        WORKSPACE_DIR / "stable_core_agent_status.json",
        WORKSPACE_DIR / "runtime" / "bridge_limited_write_status.json",
        WORKSPACE_DIR / "runtime" / "camera_status.json",
        WORKSPACE_DIR / "runtime" / "mic_status.json",
    ):
        if source.exists():
            destination = bundle_dir / source.name
            shutil.copy2(source, destination)
            copied.append(str(destination))
    write_json(
        bundle_dir / "snapshot_manifest.json",
        {
            "reason": reason,
            "created_at_unix_s": now_unix_s(),
            "copied": copied,
            "reservoir": build_reservoir_status(),
        },
    )
    return {"bundle_dir": str(bundle_dir), "copied_count": len(copied)}


def _safe_slug(value: str | None, *, default: str) -> str:
    slug = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in (value or default)
    ).strip("_")
    return (slug or default)[:80]


def capture_spectral_fingerprint(
    *,
    label: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    spectral_state = load_json(WORKSPACE_DIR / "spectral_state.json", {})
    health = load_json(WORKSPACE_DIR / "health.json", {})
    rescue_status = load_json(WORKSPACE_DIR / "rescue_status.json", {})
    rescue_profile = load_json(WORKSPACE_DIR / "rescue_profile.json", {})
    bridge_status = load_json(BRIDGE_LIMITED_WRITE_STATUS_PATH, {})
    if not isinstance(spectral_state, dict):
        spectral_state = {}
    if not isinstance(health, dict):
        health = {}
    if not isinstance(rescue_status, dict):
        rescue_status = {}
    if not isinstance(rescue_profile, dict):
        rescue_profile = {}
    if not isinstance(bridge_status, dict):
        bridge_status = {}

    fingerprint_v1 = spectral_state.get("spectral_fingerprint_v1")
    if not isinstance(fingerprint_v1, dict):
        fingerprint_v1 = None
    denominator_v1 = spectral_state.get("spectral_denominator_v1")
    if not isinstance(denominator_v1, dict):
        denominator_v1 = None
    legacy_fingerprint = spectral_state.get("spectral_fingerprint")
    if not isinstance(legacy_fingerprint, list):
        legacy_fingerprint = None
    eigenvalues = spectral_state.get("eigenvalues")
    if not isinstance(eigenvalues, list) and fingerprint_v1 is not None:
        eigenvalues = fingerprint_v1.get("eigenvalues")

    present_state = {
        "fill_pct": spectral_state.get("fill_pct", health.get("fill_pct")),
        "fill_ratio": spectral_state.get("fill_ratio"),
        "lambda1": spectral_state.get(
            "lambda1",
            spectral_state.get("eig1", health.get("lambda1")),
        ),
        "lambda1_rel": spectral_state.get("lambda1_rel", health.get("lambda1_rel")),
        "geom_rel": spectral_state.get("geom_rel", health.get("geom_rel")),
        "active_mode_count": spectral_state.get("active_mode_count"),
        "active_mode_energy_ratio": spectral_state.get("active_mode_energy_ratio"),
        "effective_dimensionality": spectral_state.get("effective_dimensionality"),
        "distinguishability_loss": spectral_state.get("distinguishability_loss"),
        "spectral_entropy": spectral_state.get("spectral_entropy"),
        "structural_entropy": spectral_state.get("structural_entropy"),
    }

    slug = _safe_slug(label, default="live")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    capture_dir = WORKSPACE_DIR / "diagnostics" / "spectral_fingerprints"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / f"{stamp}_{slug}.json"
    payload = {
        "schema": "minime_spectral_fingerprint_capture_v1",
        "captured_at_unix_s": now_unix_s(),
        "label": label or "live",
        "reason": reason,
        "source_files": {
            "spectral_state": str(WORKSPACE_DIR / "spectral_state.json"),
            "health": str(WORKSPACE_DIR / "health.json"),
            "rescue_status": str(WORKSPACE_DIR / "rescue_status.json"),
            "bridge_status": str(BRIDGE_LIMITED_WRITE_STATUS_PATH),
        },
        "present_state": present_state,
        "semantic": spectral_state.get("semantic") or health.get("semantic") or {},
        "semantic_energy_v1": spectral_state.get("semantic_energy_v1")
        or health.get("semantic_energy_v1")
        or {},
        "stable_core": spectral_state.get("stable_core") or health.get("stable_core") or {},
        "rescue_status": rescue_status,
        "rescue_profile": {
            "profile": rescue_profile.get("profile"),
            "runtime_profile": rescue_profile.get("runtime_profile"),
            "stable_core_agency_stage": rescue_profile.get("stable_core_agency_stage"),
            "stable_core_agent_budget": rescue_profile.get("stable_core_agent_budget"),
            "bridge_write_profile": rescue_profile.get("bridge_write_profile"),
        },
        "bridge": bridge_status,
        "selected_memory_id": spectral_state.get("selected_memory_id"),
        "selected_memory_role": spectral_state.get("selected_memory_role"),
        "spectral_glimpse_12d": spectral_state.get("spectral_glimpse_12d"),
        "eigenvalues": eigenvalues or [],
        "fingerprint": fingerprint_v1,
        "spectral_denominator_v1": denominator_v1,
        "legacy_spectral_fingerprint": legacy_fingerprint,
    }
    write_json(capture_path, payload)
    write_json(capture_dir / "latest.json", payload | {"path": str(capture_path)})
    return {
        "status": "captured" if fingerprint_v1 is not None or legacy_fingerprint is not None else "missing_fingerprint",
        "path": str(capture_path),
        "latest_path": str(capture_dir / "latest.json"),
        "label": label or "live",
        "reason": reason,
        "present_state": present_state,
        "fingerprint_policy": fingerprint_v1.get("policy") if fingerprint_v1 else None,
        "legacy_slot_count": len(legacy_fingerprint or []),
    }


def set_lineage_mode(mode: str, *, reason: str | None = None) -> dict[str, Any]:
    if mode not in {"direct_restore", "quarantined"}:
        raise SystemExit("lineage mode must be direct_restore or quarantined")
    profile_path = WORKSPACE_DIR / "rescue_profile.json"
    profile = load_json(profile_path, {})
    if not isinstance(profile, dict) or not profile:
        raise SystemExit(f"missing active rescue profile: {profile_path}")
    if not bool(profile.get("stable_core_enabled")):
        raise SystemExit("lineage controls require active stable_core_v1 profile")

    snapshot = snapshot_live_state(reason=reason or f"lineage_{mode}")
    enabled = mode == "direct_restore"
    updated_at = now_unix_s()
    profile["stable_core_checkpoint_lineage_enabled"] = enabled
    profile["stable_core_neural_bundle_enabled"] = enabled
    profile["checkpoint_lineage_restore_mode"] = mode
    profile["stable_core_lineage_updated_at_unix_s"] = updated_at
    profile["stable_core_lineage_reason"] = reason
    if enabled:
        profile["checkpoint_mode"] = "direct_restore"
        profile["checkpoint_restore_enabled"] = True
        profile["checkpoint_source"] = str(WORKSPACE_DIR / "spectral_checkpoint.bin")
        profile["neural_bundle_enabled"] = True
    else:
        profile["checkpoint_mode"] = "disabled"
        profile["checkpoint_restore_enabled"] = False
        profile["checkpoint_source"] = "none"
        profile["neural_bundle_enabled"] = False
    write_json(profile_path, profile)
    return {
        "mode": mode,
        "updated_at_unix_s": updated_at,
        "reason": reason,
        "snapshot": snapshot,
        "stable_core_checkpoint_lineage_enabled": enabled,
        "stable_core_neural_bundle_enabled": enabled,
        "restart_required": True,
        "rollback_command": (
            "python3 /Users/v/other/minime/scripts/stable_core_ops.py "
            "lineage-set quarantined --reason direct_restore_rollback"
        ),
    }


def _status_failure(message: str) -> dict[str, Any]:
    return {"ok": False, "reason": message}


def validate_lineage_canary_precheck(
    status: dict[str, Any],
    *,
    require_scaffold: bool = True,
    allow_low_fill: bool = False,
    require_feeders: bool = True,
) -> dict[str, Any]:
    if status.get("mode") != "stable_core_v1":
        return _status_failure("stable_core_v1_not_active")
    if status.get("watchdog_state") != "monitoring":
        return _status_failure("watchdog_not_monitoring")
    if status.get("telemetry_state") != "fresh":
        return _status_failure("telemetry_not_fresh")

    fill_pct = _finite_number(status.get("fill_pct"))
    if fill_pct is None:
        return _status_failure("fill_missing")
    if fill_pct >= LINEAGE_CANARY_MAX_FILL_PCT:
        return _status_failure("fill_too_high")
    if fill_pct <= LINEAGE_CANARY_MIN_FILL_PCT and not allow_low_fill:
        return _status_failure("fill_too_low")

    semantic_energy = _finite_number(status.get("semantic_energy")) or 0.0
    if bool(status.get("semantic_active")) or semantic_energy > LINEAGE_CANARY_SEMANTIC_MAX:
        return _status_failure("semantic_not_quiet")

    stable_core = status.get("stable_core") if isinstance(status.get("stable_core"), dict) else {}
    if not bool(stable_core.get("enabled", True)):
        return _status_failure("stable_core_health_missing")
    if require_scaffold and not bool(stable_core.get("scaffold_active", True)):
        return _status_failure("scaffold_not_active")

    feeders = status.get("feeders") if isinstance(status.get("feeders"), dict) else {}
    if require_feeders:
        for name in ("camera", "mic"):
            feeder = feeders.get(name) if isinstance(feeders.get(name), dict) else {}
            if feeder and (
                not bool(feeder.get("healthy")) or not bool(feeder.get("connected", True))
            ):
                return _status_failure(f"{name}_feeder_unhealthy")

    return {"ok": True, "reason": "ok"}


def _current_blocked_count(status: dict[str, Any]) -> int:
    agent_status = status.get("agency_status")
    if not isinstance(agent_status, dict):
        return 0
    count = agent_status.get("blocked_count")
    return int(count) if isinstance(count, int) and count >= 0 else 0


def evaluate_lineage_canary_sample(
    status: dict[str, Any],
    *,
    started_at_unix_s: float,
    baseline_blocked_count: int,
    discharge_samples: int,
) -> dict[str, Any]:
    elapsed = max(0.0, now_unix_s() - started_at_unix_s)
    precheck = validate_lineage_canary_precheck(
        status,
        require_scaffold=False,
        allow_low_fill=elapsed < LINEAGE_CANARY_SCAFFOLD_WARMUP_SECS,
        require_feeders=elapsed >= LINEAGE_CANARY_SCAFFOLD_WARMUP_SECS,
    )
    if not precheck["ok"]:
        return {"ok": False, "reason": precheck["reason"], "discharge_samples": discharge_samples}

    stable_core = status.get("stable_core") if isinstance(status.get("stable_core"), dict) else {}
    stage = str(status.get("stage") or stable_core.get("stage") or "")
    next_discharge_samples = discharge_samples + 1 if stage == "discharge" else 0
    if next_discharge_samples >= 2 and elapsed > 20.0:
        return {
            "ok": False,
            "reason": "discharge_persisted",
            "discharge_samples": next_discharge_samples,
        }

    if elapsed >= LINEAGE_CANARY_SCAFFOLD_WARMUP_SECS and not bool(
        stable_core.get("scaffold_active")
    ):
        return {
            "ok": False,
            "reason": "scaffold_inactive_after_warmup",
            "discharge_samples": next_discharge_samples,
        }

    blocked_delta = _current_blocked_count(status) - baseline_blocked_count
    agent_status = status.get("agency_status")
    last_block = (
        agent_status.get("last_block")
        if isinstance(agent_status, dict) and isinstance(agent_status.get("last_block"), dict)
        else {}
    )
    last_block_action = str(last_block.get("action") or "")
    if blocked_delta >= 3 and last_block_action in HIGH_POWER_ACTIONS:
        return {
            "ok": False,
            "reason": f"high_power_block_storm:{last_block_action}",
            "discharge_samples": next_discharge_samples,
        }

    return {"ok": True, "reason": "ok", "discharge_samples": next_discharge_samples}


def _write_lineage_canary_status(payload: dict[str, Any]) -> None:
    LINEAGE_CANARY_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(LINEAGE_CANARY_STATUS_PATH, payload)


def restart_minime_engine(*, label: str = LINEAGE_CANARY_ENGINE_LABEL) -> dict[str, Any]:
    launchctl = shutil.which("launchctl")
    if not launchctl:
        return {"ok": False, "reason": "launchctl_unavailable", "label": label}
    service = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        [launchctl, "kickstart", "-k", service],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "label": label,
        "service": service,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


def wait_for_engine_pid_change(
    old_pid: Any,
    *,
    timeout_secs: float = 60.0,
    poll_secs: float = 2.0,
    expected_checkpoint_lineage: bool | None = None,
    expected_neural_bundle: bool | None = None,
) -> dict[str, Any]:
    deadline = now_unix_s() + timeout_secs
    last_status: dict[str, Any] = {}
    while now_unix_s() <= deadline:
        status = build_status()
        last_status = status
        new_pid = status.get("engine_pid")
        if new_pid and new_pid != old_pid and status.get("telemetry_state") == "fresh":
            stable_core = status.get("stable_core") if isinstance(status.get("stable_core"), dict) else {}
            lineage_matches = (
                expected_checkpoint_lineage is None
                or bool(stable_core.get("checkpoint_lineage_enabled"))
                == expected_checkpoint_lineage
            )
            neural_matches = (
                expected_neural_bundle is None
                or bool(stable_core.get("neural_bundle_enabled")) == expected_neural_bundle
            )
            if lineage_matches and neural_matches:
                return {"ok": True, "old_pid": old_pid, "new_pid": new_pid, "status": status}
        time.sleep(max(0.1, poll_secs))
    return {
        "ok": False,
        "reason": "engine_pid_did_not_change_with_fresh_matching_telemetry",
        "old_pid": old_pid,
        "last_pid": last_status.get("engine_pid"),
        "status": last_status,
        "expected_checkpoint_lineage": expected_checkpoint_lineage,
        "expected_neural_bundle": expected_neural_bundle,
    }


def rollback_lineage_canary(bundle_dir: Path, *, reason: str) -> dict[str, Any]:
    rollback_dir = bundle_dir / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    lineage = set_lineage_mode("quarantined", reason=f"lineage_canary_rollback:{reason}")
    bridge = set_bridge_write_stage("bridge_observe_only", reason=f"lineage_canary_rollback:{reason}")
    sensory = set_sensory_presence_profile("muted_v1", reason=f"lineage_canary_rollback:{reason}")
    restart = restart_minime_engine()
    snapshot = capture_lineage_canary_snapshot(rollback_dir, reason=f"rollback:{reason}")
    payload = {
        "rolled_back": True,
        "reason": reason,
        "lineage": lineage,
        "bridge": bridge,
        "sensory": sensory,
        "restart": restart,
        "snapshot": snapshot,
        "rolled_back_at_unix_s": now_unix_s(),
    }
    write_json(rollback_dir / "rollback.json", payload)
    return payload


def run_lineage_canary(
    mode: str,
    *,
    duration_secs: float = DEFAULT_LINEAGE_CANARY_SECS,
    sample_interval_secs: float = DEFAULT_LINEAGE_CANARY_SAMPLE_SECS,
    reason: str | None = None,
    restart: bool = True,
) -> dict[str, Any]:
    if mode != "direct_restore":
        raise SystemExit("lineage-canary currently supports direct_restore only")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_reason = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in (reason or mode)
    )[:80]
    bundle_dir = LINEAGE_CANARY_DIR / f"{stamp}_{safe_reason}"
    pre_dir = bundle_dir / "pre"
    post_restart_dir = bundle_dir / "post_restart"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    status = build_status()
    precheck = validate_lineage_canary_precheck(status)
    if not precheck["ok"]:
        capture_lineage_canary_snapshot(pre_dir, reason=f"precheck_failed:{precheck['reason']}")
        result = {
            "result": "precheck_failed",
            "reason": precheck["reason"],
            "mode": mode,
            "bundle_dir": str(bundle_dir),
            "started_at_unix_s": now_unix_s(),
        }
        write_json(bundle_dir / "result.json", result)
        _write_lineage_canary_status(
            {
                "active": False,
                "mode": mode,
                "result": "precheck_failed",
                "rollback_reason": precheck["reason"],
                "bundle_dir": str(bundle_dir),
                "updated_at_unix_s": now_unix_s(),
            }
        )
        raise SystemExit(f"lineage canary precheck failed: {precheck['reason']}")

    pre_snapshot = capture_lineage_canary_snapshot(pre_dir, reason=reason or "lineage_canary_pre")
    quiet_bridge = set_bridge_write_stage(
        "bridge_observe_only",
        reason=reason or "lineage_canary_quiet_bridge",
    )
    quiet_sensory = set_sensory_presence_profile(
        "muted_v1",
        reason=reason or "lineage_canary_quiet_sensory",
    )
    baseline_blocked_count = _current_blocked_count(status)
    old_pid = status.get("engine_pid")
    lineage = set_lineage_mode(mode, reason=reason or "lineage_canary_direct_restore")

    started_at = now_unix_s()
    _write_lineage_canary_status(
        {
            "active": True,
            "mode": mode,
            "started_at_unix_s": started_at,
            "result": "running",
            "rollback_reason": None,
            "bundle_dir": str(bundle_dir),
            "updated_at_unix_s": started_at,
        }
    )

    restart_result = restart_minime_engine() if restart else {"ok": True, "skipped": True}
    if restart and not restart_result.get("ok"):
        rollback = rollback_lineage_canary(bundle_dir, reason="engine_restart_failed")
        result = {
            "result": "failed",
            "reason": "engine_restart_failed",
            "mode": mode,
            "bundle_dir": str(bundle_dir),
            "restart": restart_result,
            "rollback": rollback,
            "started_at_unix_s": started_at,
            "ended_at_unix_s": now_unix_s(),
        }
        write_json(bundle_dir / "result.json", result)
        _write_lineage_canary_status(
            {
                "active": False,
                "mode": mode,
                "started_at_unix_s": started_at,
                "result": "failed",
                "rollback_reason": "engine_restart_failed",
                "bundle_dir": str(bundle_dir),
                "updated_at_unix_s": now_unix_s(),
            }
        )
        return result

    wait_result = (
        wait_for_engine_pid_change(
            old_pid,
            expected_checkpoint_lineage=True,
            expected_neural_bundle=True,
        )
        if restart
        else {"ok": True, "old_pid": old_pid, "new_pid": old_pid, "status": build_status()}
    )
    capture_lineage_canary_snapshot(post_restart_dir, reason="post_restart")
    if not wait_result.get("ok"):
        rollback = rollback_lineage_canary(bundle_dir, reason="engine_telemetry_not_fresh_after_restart")
        result = {
            "result": "failed",
            "reason": "engine_telemetry_not_fresh_after_restart",
            "mode": mode,
            "bundle_dir": str(bundle_dir),
            "restart": restart_result,
            "wait": wait_result,
            "rollback": rollback,
            "started_at_unix_s": started_at,
            "ended_at_unix_s": now_unix_s(),
        }
        write_json(bundle_dir / "result.json", result)
        _write_lineage_canary_status(
            {
                "active": False,
                "mode": mode,
                "started_at_unix_s": started_at,
                "result": "failed",
                "rollback_reason": result["reason"],
                "bundle_dir": str(bundle_dir),
                "updated_at_unix_s": now_unix_s(),
            }
        )
        return result

    samples_path = bundle_dir / "samples.jsonl"
    discharge_samples = 0
    fail_reason: str | None = None
    deadline = started_at + max(0.0, duration_secs)
    last_status = wait_result.get("status") if isinstance(wait_result.get("status"), dict) else build_status()
    while True:
        sample_status = build_status()
        last_status = sample_status
        evaluation = evaluate_lineage_canary_sample(
            sample_status,
            started_at_unix_s=started_at,
            baseline_blocked_count=baseline_blocked_count,
            discharge_samples=discharge_samples,
        )
        discharge_samples = int(evaluation.get("discharge_samples", discharge_samples))
        sample = {
            "sampled_at_unix_s": now_unix_s(),
            "fill_pct": sample_status.get("fill_pct"),
            "stage": sample_status.get("stage"),
            "watchdog_state": sample_status.get("watchdog_state"),
            "telemetry_state": sample_status.get("telemetry_state"),
            "semantic_energy": sample_status.get("semantic_energy"),
            "semantic_active": sample_status.get("semantic_active"),
            "lineage": sample_status.get("lineage"),
            "evaluation": evaluation,
        }
        with samples_path.open("a") as handle:
            handle.write(json.dumps(sample, sort_keys=True) + "\n")
        if not evaluation["ok"]:
            fail_reason = str(evaluation["reason"])
            break
        if now_unix_s() >= deadline:
            break
        time.sleep(max(0.1, sample_interval_secs))

    if fail_reason is not None:
        rollback = rollback_lineage_canary(bundle_dir, reason=fail_reason)
        result = {
            "result": "failed",
            "reason": fail_reason,
            "mode": mode,
            "bundle_dir": str(bundle_dir),
            "pre_snapshot": pre_snapshot,
            "quiet_bridge": quiet_bridge,
            "quiet_sensory": quiet_sensory,
            "lineage": lineage,
            "restart": restart_result,
            "wait": wait_result,
            "rollback": rollback,
            "last_status": last_status,
            "started_at_unix_s": started_at,
            "ended_at_unix_s": now_unix_s(),
        }
    else:
        result = {
            "result": "passed",
            "reason": None,
            "mode": mode,
            "bundle_dir": str(bundle_dir),
            "pre_snapshot": pre_snapshot,
            "quiet_bridge": quiet_bridge,
            "quiet_sensory": quiet_sensory,
            "lineage": lineage,
            "restart": restart_result,
            "wait": wait_result,
            "last_status": last_status,
            "started_at_unix_s": started_at,
            "ended_at_unix_s": now_unix_s(),
        }

    write_json(bundle_dir / "result.json", result)
    _write_lineage_canary_status(
        {
            "active": False,
            "mode": mode,
            "started_at_unix_s": started_at,
            "result": result["result"],
            "rollback_reason": result.get("reason") if result["result"] == "failed" else None,
            "bundle_dir": str(bundle_dir),
            "updated_at_unix_s": now_unix_s(),
        }
    )
    return result


def _json_age_ms(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    updated_at_ms = payload.get("updated_at_ms", payload.get("ts_ms"))
    if not isinstance(updated_at_ms, (int, float)) or updated_at_ms <= 0:
        return None
    return max(0.0, now_unix_s() * 1000.0 - float(updated_at_ms))


def build_sensory_fallback_status() -> dict[str, Any]:
    runtime = WORKSPACE_DIR / "runtime"
    camera = load_json(runtime / "camera_status.json", {})
    mic = load_json(runtime / "mic_status.json", {})
    sensory_source = load_json(runtime / "sensory_source.json", {})
    host_telemetry = load_json(runtime / "host_telemetry.json", {})
    host_frame = runtime / "host_frame.jpg"

    sensory_age_ms = _json_age_ms(sensory_source)
    host_telemetry_age_ms = _json_age_ms(host_telemetry)
    host_frame_age_ms = None
    if host_frame.exists():
        host_frame_age_ms = max(0.0, (now_unix_s() - host_frame.stat().st_mtime) * 1000.0)

    camera_healthy = bool(camera.get("healthy")) and bool(camera.get("connected", True))
    mic_healthy = bool(mic.get("healthy")) and bool(mic.get("connected", True))
    host_video_ready = (
        host_telemetry_age_ms is not None
        and host_telemetry_age_ms <= 10_000
        and host_frame_age_ms is not None
        and host_frame_age_ms <= 15_000
    )
    host_audio_ready = host_telemetry_age_ms is not None and host_telemetry_age_ms <= 10_000

    video_state = sensory_source.get("video") if isinstance(sensory_source, dict) else {}
    audio_state = sensory_source.get("audio") if isinstance(sensory_source, dict) else {}
    if not isinstance(video_state, dict):
        video_state = {}
    if not isinstance(audio_state, dict):
        audio_state = {}

    active_video = video_state.get("source") or ("physical" if camera_healthy else "host")
    active_audio = audio_state.get("source") or ("physical" if mic_healthy else "host")
    camera_classification = classify_physical_camera_status(
        camera,
        active_video=active_video,
        host_video_ready=host_video_ready,
    )

    return {
        "status": "ok"
        if (camera_healthy or host_video_ready) and (mic_healthy or host_audio_ready)
        else "degraded",
        "source_state_fresh": sensory_age_ms is not None and sensory_age_ms <= 10_000,
        "source_state_age_ms": sensory_age_ms,
        "active": {
            "video": active_video,
            "audio": active_audio,
        },
        "physical": {
            "camera_healthy": camera_healthy,
            "camera_state": camera.get("state"),
            "camera_connected": camera.get("connected"),
            "camera_last_success_at": camera.get("last_success_at"),
            "camera_availability": camera_classification["classification"],
            "camera_last_error": camera_classification["last_error"],
            "camera_operator_note": camera_classification["operator_note"],
            "mic_healthy": mic_healthy,
            "mic_state": mic.get("state"),
            "mic_connected": mic.get("connected"),
            "mic_last_success_at": mic.get("last_success_at"),
        },
        "physical_camera": camera_classification,
        "synthetic_host": {
            "video_ready": host_video_ready,
            "audio_ready": host_audio_ready,
            "host_telemetry_age_ms": host_telemetry_age_ms,
            "host_frame_age_ms": host_frame_age_ms,
            "host_frame_path": str(host_frame),
        },
        "fallback_reason": {
            "video": video_state.get("reason")
            or (None if camera_healthy else "camera unavailable; synthetic host video selected"),
            "audio": audio_state.get("reason")
            or (None if mic_healthy else "mic unavailable; synthetic host audio selected"),
        },
        "updated_at_unix_s": now_unix_s(),
    }


def build_continuity_status() -> dict[str, Any]:
    manifest = load_json(_continuity_status_path(), {})
    if not isinstance(manifest, dict):
        manifest = {}

    memory_path = manifest.get("memory_sanitized_path")
    continuity_path = manifest.get("continuity_seed_path")
    memory = load_json(Path(memory_path), {}) if isinstance(memory_path, str) else {}
    continuity = load_json(Path(continuity_path), {}) if isinstance(continuity_path, str) else {}
    if not isinstance(memory, dict):
        memory = {}
    if not isinstance(continuity, dict):
        continuity = {}

    memory_entries = memory.get("entries") if isinstance(memory.get("entries"), list) else []
    journal_entries = (
        continuity.get("journal_entries")
        if isinstance(continuity.get("journal_entries"), list)
        else []
    )
    return {
        "available": bool(memory_entries or journal_entries),
        "policy": manifest.get("continuity_policy") or continuity.get("policy"),
        "activation_policy": manifest.get("activation_policy")
        or continuity.get("activation_policy"),
        "checkpoint_lineage": manifest.get("checkpoint_lineage")
        or continuity.get("checkpoint_lineage"),
        "memory_entries_kept": manifest.get("memory_entries_kept", len(memory_entries)),
        "memory_entries_dropped": manifest.get("memory_entries_dropped"),
        "journal_entries_indexed": manifest.get("journal_entries_indexed", len(journal_entries)),
        "safe_fill_band_pct": manifest.get("safe_fill_band_pct")
        or memory.get("safe_fill_band_pct"),
        "memory_sanitized_path": memory_path,
        "continuity_seed_path": continuity_path,
        "updated_at_unix_s": manifest.get("created_at_unix_s"),
    }


def build_astrid_inbox_coupling_status() -> dict[str, Any]:
    status = load_json(ASTRID_INBOX_COUPLING_STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    inbox = WORKSPACE_DIR / "inbox"
    pending: dict[str, int] = {
        "total": 0,
        "astrid_self_study": 0,
        "receipt": 0,
        "question_from_astrid": 0,
        "ping": 0,
        "other": 0,
    }
    if inbox.is_dir():
        for path in inbox.glob("*.txt"):
            pending["total"] += 1
            name = path.name
            if name.startswith("astrid_self_study_"):
                pending["astrid_self_study"] += 1
            elif name.startswith("receipt_"):
                pending["receipt"] += 1
            elif name.startswith("question_from_astrid_"):
                pending["question_from_astrid"] += 1
            elif name.startswith("ping_"):
                pending["ping"] += 1
            else:
                pending["other"] += 1
    return {
        "status": "ok",
        "policy": status.get("policy", "astrid_companion_cadence_v1"),
        "receipt_context": status.get("receipt_context", "admin_only"),
        "self_study_policy": status.get(
            "self_study_policy",
            "one_novel_frame_per_read_with_similarity_cadence",
        ),
        "pending": pending,
        "receipt_admin_count": status.get("receipt_admin_count", 0),
        "astrid_self_study_full_count": status.get("astrid_self_study_full_count", 0),
        "astrid_self_study_summarized_count": status.get(
            "astrid_self_study_summarized_count",
            0,
        ),
        "last_summary": status.get("last_summary"),
        "last_batch": status.get("last_batch", {}),
        "recent_signatures": status.get("recent_signatures", [])[:8]
        if isinstance(status.get("recent_signatures"), list)
        else [],
        "updated_at_unix_s": status.get("updated_at_unix_s"),
        "status_path": str(ASTRID_INBOX_COUPLING_STATUS_PATH),
    }


def build_native_communication_parity_status() -> dict[str, Any]:
    gestures = ["mark", "trace", "soften", "widen", "hold", "return", "resist", "fissure"]
    return {
        "status": "aligned",
        "canonical_workspace_owner": "minime",
        "minime_next_actions": [
            "MARK_INTENSIFICATION <label>",
            "TRACE <label>",
            "SCA_REFLECT <label>",
            "NOTICE_AMBIGUITY <label>",
            "FISSURE_TRACE <label>",
            "REGULATOR_AUDIT <label>",
            "SHADOW_FIELD <label>",
            "GAP_STRUCTURE <label>",
            "DECAY_MAP <label>",
            "SPACE_HOLD <label>",
            "EIGENVECTOR_FIELD <label>",
            "SDI_TRACE <label>",
            "VISUALIZE_CASCADE <label>",
            "NATIVE_GESTURE <gesture> [label]",
            "RESIST [label]",
            "FISSURE [label]",
        ],
        "astrid_next_actions": [
            "MARK_INTENSIFICATION <label>",
            "TRACE <label>",
            "SCA_REFLECT <label>",
            "NOTICE_AMBIGUITY <label>",
            "FISSURE_TRACE <label>",
            "REGULATOR_AUDIT <label>",
            "SHADOW_FIELD <label>",
            "GAP_STRUCTURE <label>",
            "DECAY_MAP <label>",
            "SPACE_HOLD <label>",
            "EIGENVECTOR_FIELD <label>",
            "VISUALIZE_CASCADE <label>",
            "NATIVE_GESTURE <gesture> [label]",
            "RESIST [label]",
            "FISSURE [label]",
        ],
        "shared_gestures": gestures,
        "control_bearing_gestures": ["soften", "widen", "hold", "return", "resist", "fissure"],
        "atlas_only_gestures": ["mark", "trace"],
        "operator_surfaces": [
            "atlas-status",
            "native-gesture-status",
            "sca-status",
            "regulator-audit",
            "resonance-forecast",
            "shadow-gap-status",
            "decay-status",
            "fissure-status",
            "space-hold-status",
            "sdi-status",
            "gradient-audit",
            "native-parity-status",
            "visualize-cascade --label <label>",
            "reconvergence-map --label <label>",
            "bridge-trace --mode m6 --label <label>  # activation lane 6 marker; eigenmode unconfirmed",
            "lane-synopsis --send-inbox",
        ],
        "known_asymmetry": (
            "Minime owns canonical atlas files and can auto-log from local "
            "decompose/perturb context; Astrid contributes explicit marks and "
            "native gestures through the bridge using the same health gates."
        ),
    }


def build_status() -> dict[str, Any]:
    health = load_json(WORKSPACE_DIR / "health.json", {})
    rescue_status = load_json(WORKSPACE_DIR / "rescue_status.json", {})
    profile = load_json(WORKSPACE_DIR / "rescue_profile.json", {})
    agency = load_json(AGENCY_PATH, {})
    bridge_status = load_json(WORKSPACE_DIR / "runtime" / "bridge_limited_write_status.json", {})
    lineage_canary_status = load_json(LINEAGE_CANARY_STATUS_PATH, {})
    agent_status = load_json(WORKSPACE_DIR / "stable_core_agent_status.json", {})
    attractor_fatigue = build_attractor_fatigue_status()
    camera = load_json(WORKSPACE_DIR / "runtime" / "camera_status.json", {})
    mic = load_json(WORKSPACE_DIR / "runtime" / "mic_status.json", {})
    sensory = build_sensory_fallback_status()
    continuity = build_continuity_status()
    companion_coupling = build_astrid_inbox_coupling_status()
    reservoir = build_reservoir_status()
    atlas = build_atlas_status()
    sca = build_sca_status()
    resonance_forecast = build_resonance_forecast_status()
    shadow_gap = build_shadow_gap_status()
    decay_map = build_decay_map_status()
    fissure_trace = build_fissure_trace_status()
    space_hold = build_space_hold_status()
    spectral_drift = build_spectral_drift_status()
    gradient_audit = build_controller_gradient_audit()
    native_gestures = build_native_gesture_status()
    native_parity = build_native_communication_parity_status()
    reconvergence_map = build_reconvergence_map_status()
    bridge_trace = build_bridge_trace_status()
    spectral_pressure = load_json(WORKSPACE_DIR / "runtime" / "spectral_pressure_status.json", {})
    cascade_visuals = load_json(
        WORKSPACE_DIR / "runtime" / "spectral_cascade_visual_status.json",
        {},
    )
    sensory_active = sensory.get("active") if isinstance(sensory.get("active"), dict) else {}
    sensory_fallback_reason = (
        sensory.get("fallback_reason")
        if isinstance(sensory.get("fallback_reason"), dict)
        else {}
    )
    synthetic_host = (
        sensory.get("synthetic_host")
        if isinstance(sensory.get("synthetic_host"), dict)
        else {}
    )
    stable_core_health = health.get("stable_core") if isinstance(health, dict) else {}
    stable_core_enabled = bool(profile.get("stable_core_enabled"))
    semantic_v1 = health.get("semantic_energy_v1") if isinstance(health, dict) else {}
    semantic = health.get("semantic") if isinstance(health, dict) else {}
    if stable_core_enabled and not isinstance(semantic, dict):
        semantic = {"energy": 0.0, "active": False}
    elif not isinstance(semantic, dict):
        semantic = {}
    if not isinstance(semantic_v1, dict):
        semantic_v1 = {}
    semantic_energy = semantic_v1.get("regulator_drive_energy", semantic.get("energy"))
    semantic_kernel_energy = semantic_v1.get("kernel_energy", semantic.get("kernel_energy", semantic_energy))
    semantic_input_energy = semantic_v1.get("input_energy", semantic.get("input_energy", semantic_energy))
    semantic_active = semantic_v1.get("kernel_active", semantic.get("active", False))
    semantic_kernel_active = semantic_v1.get("kernel_active", semantic_active)
    semantic_input_active = semantic_v1.get("input_active", semantic.get("input_active", False))
    configured_stage = agency.get("stage") if isinstance(agency, dict) else None
    configured_budget = agency.get("agent_budget_mode") if isinstance(agency, dict) else None
    profile_stage = profile.get("stable_core_agency_stage")
    profile_budget = profile.get("stable_core_agent_budget")
    agent_stage = agent_status.get("stage") if isinstance(agent_status, dict) else None
    agent_budget = agent_status.get("agent_budget_mode") if isinstance(agent_status, dict) else None
    health_stage = (
        stable_core_health.get("agency_stage") if isinstance(stable_core_health, dict) else None
    )
    health_budget = (
        stable_core_health.get("agent_budget_mode")
        if isinstance(stable_core_health, dict)
        else None
    )
    effective_agency = {
        "configured": agency if isinstance(agency, dict) else {},
        "profile_stage": profile_stage,
        "profile_agent_budget_mode": profile_budget,
        "agent_status_stage": agent_stage,
        "agent_status_budget_mode": agent_budget,
        "engine_reported_stage": health_stage,
        "engine_reported_agent_budget_mode": health_budget,
        "effective_stage": agent_stage or configured_stage or profile_stage or health_stage,
        "effective_agent_budget_mode": agent_budget or configured_budget or profile_budget or health_budget,
        "engine_agency_mirror_stale": bool(
            stable_core_enabled
            and health_stage
            and (agent_stage or configured_stage or profile_stage)
            and health_stage != (agent_stage or configured_stage or profile_stage)
        ),
    }
    lineage_checkpoint_enabled = bool(
        profile.get("stable_core_checkpoint_lineage_enabled", False)
    )
    lineage_checkpoint_mode = (
        "direct_restore" if lineage_checkpoint_enabled else profile.get("checkpoint_mode")
    )
    lineage_checkpoint_source = (
        str(WORKSPACE_DIR / "spectral_checkpoint.bin")
        if lineage_checkpoint_enabled
        else profile.get("checkpoint_source")
    )
    lineage_canary_view = build_lineage_canary_status_view(
        lineage_canary_status if isinstance(lineage_canary_status, dict) else {}
    )

    payload = {
        "mode": "stable_core_v1" if stable_core_enabled else "inactive",
        "profile": profile.get("profile"),
        "runtime_profile": profile.get("runtime_profile"),
        "engine_pid": rescue_status.get("engine_pid"),
        "watchdog_state": rescue_status.get("watchdog_state"),
        "telemetry_state": rescue_status.get("telemetry_state"),
        "fill_pct": health.get("fill_pct") if isinstance(health, dict) else None,
        "stage": stable_core_health.get("stage")
        if stable_core_enabled and isinstance(stable_core_health, dict)
        else (health.get("rescue") or {}).get("stage")
        if isinstance(health, dict)
        else None,
        "semantic_energy": semantic_energy,
        "semantic_active": semantic_active,
        "semantic_kernel_energy": semantic_kernel_energy,
        "semantic_kernel_active": semantic_kernel_active,
        "semantic_input_energy": semantic_input_energy,
        "semantic_input_active": semantic_input_active,
        "semantic_admission": semantic.get("admission"),
        "stable_core": stable_core_health if isinstance(stable_core_health, dict) else {},
        "agency": effective_agency,
        "agency_status": build_agency_status_view(
            agent_status,
            current_fill_pct=health.get("fill_pct") if isinstance(health, dict) else None,
        )
        if isinstance(agent_status, dict)
        else {},
        "attractor_fatigue": attractor_fatigue,
        "bridge": build_bridge_write_status_view(bridge_status)
        if isinstance(bridge_status, dict)
        else {},
        "companion_coupling": companion_coupling,
        "continuity": continuity,
        "intensification_atlas": atlas,
        "sca_why_layer": sca,
        "resonance_forecast": resonance_forecast,
        "shadow_gap": shadow_gap,
        "decay_map": decay_map,
        "fissure_trace": fissure_trace,
        "space_hold": space_hold,
        "spectral_drift": spectral_drift,
        "controller_gradient_audit": gradient_audit,
        "native_gestures": native_gestures,
        "native_communication_parity": native_parity,
        "spectral_pressure": spectral_pressure if isinstance(spectral_pressure, dict) else {},
        "spectral_cascade_visuals": cascade_visuals if isinstance(cascade_visuals, dict) else {},
        "reconvergence_map": reconvergence_map,
        "bridge_trace": bridge_trace,
        "lineage": {
            "mode": profile.get("checkpoint_lineage_restore_mode", "quarantined"),
            "checkpoint_lineage_enabled": lineage_checkpoint_enabled,
            "neural_bundle_enabled": profile.get("stable_core_neural_bundle_enabled", False),
            "checkpoint_mode": lineage_checkpoint_mode,
            "checkpoint_source": lineage_checkpoint_source,
            "updated_at_unix_s": profile.get("stable_core_lineage_updated_at_unix_s"),
            "restore_canary_active": bool(
                lineage_canary_status.get("active")
            )
            if isinstance(lineage_canary_status, dict)
            else False,
            "restore_canary_started_at": lineage_canary_status.get("started_at_unix_s")
            if isinstance(lineage_canary_status, dict)
            else None,
            "restore_canary_mode": lineage_canary_status.get("mode")
            if isinstance(lineage_canary_status, dict)
            else None,
            "restore_canary_result": lineage_canary_status.get("result")
            if isinstance(lineage_canary_status, dict)
            else None,
            "restore_canary_rollback_reason": lineage_canary_status.get("rollback_reason")
            if isinstance(lineage_canary_status, dict)
            else None,
            "restore_canary_bundle_dir": lineage_canary_status.get("bundle_dir")
            if isinstance(lineage_canary_status, dict)
            else None,
            "restore_canary_health": lineage_canary_view,
            "restore_canary_classification": lineage_canary_view.get("classification"),
            "restore_canary_blocker": lineage_canary_view.get("blocker"),
            "restore_canary_age_s": lineage_canary_view.get("age_s"),
        },
        "sensory_sources": sensory,
        "sensory_profile": {
            "profile": profile.get("stable_core_sensory_presence_profile"),
            "audio_divisor": profile.get("rescue_live_audio_divisor"),
            "video_divisor": profile.get("rescue_live_video_divisor"),
            "intake_stages": profile.get("rescue_live_intake_stages"),
            "updated_at_unix_s": profile.get(
                "stable_core_sensory_presence_updated_at_unix_s"
            ),
        },
        "reservoir": reservoir,
        "feeders": {
            "camera": {
                "state": camera.get("state"),
                "healthy": camera.get("healthy"),
                "connected": camera.get("connected"),
                "consecutive_failures": camera.get("consecutive_failures"),
                "active_source": sensory_active.get("video"),
                "synthetic_host_ready": synthetic_host.get("video_ready"),
                "fallback_reason": sensory_fallback_reason.get("video"),
                "availability": sensory.get("physical_camera", {}).get("classification")
                if isinstance(sensory.get("physical_camera"), dict)
                else None,
                "operator_note": sensory.get("physical_camera", {}).get("operator_note")
                if isinstance(sensory.get("physical_camera"), dict)
                else None,
            },
            "mic": {
                "state": mic.get("state"),
                "healthy": mic.get("healthy"),
                "connected": mic.get("connected"),
                "consecutive_failures": mic.get("consecutive_failures"),
                "active_source": sensory_active.get("audio"),
                "synthetic_host_ready": synthetic_host.get("audio_ready"),
                "fallback_reason": sensory_fallback_reason.get("audio"),
            },
        },
        "updated_at_unix_s": now_unix_s(),
    }
    write_json(STABLE_CORE_STATUS_PATH, payload)
    return payload


def write_full_sovereignty_savepoint_status(*, reason: str | None = None) -> dict[str, Any]:
    status = build_status()
    FULL_SOVEREIGNTY_SAVEPOINT_DOC.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Full Sovereignty Savepoint Status",
        "",
        f"- Generated: `{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}`",
        f"- Reason: `{reason or 'operator_savepoint'}`",
        f"- Runtime profile: `{status.get('runtime_profile')}`",
        f"- Minime agency: `{status.get('agency', {}).get('effective_stage')}`",
        f"- Fill: `{status.get('fill_pct')}`",
        f"- Stage: `{status.get('stage')}`",
        f"- Watchdog: `{status.get('watchdog_state')}`",
        f"- Telemetry: `{status.get('telemetry_state')}`",
        f"- Semantic energy: `{status.get('semantic_energy')}`",
        f"- Semantic input/kernel: `{status.get('semantic_input_energy')}` / `{status.get('semantic_kernel_energy')}`",
        f"- Bridge profile: `{status.get('profile')}`",
        f"- Astrid sends: `{status.get('bridge', {}).get('send_count')}`",
        f"- Sensory profile: `{status.get('sensory_profile', {}).get('profile')}`",
        f"- Reservoir status: `{status.get('reservoir', {}).get('status')}`",
        f"- Lineage mode: `{status.get('lineage', {}).get('mode')}`",
        f"- Checkpoint lineage enabled: `{status.get('lineage', {}).get('checkpoint_lineage_enabled')}`",
        f"- Neural bundle enabled: `{status.get('lineage', {}).get('neural_bundle_enabled')}`",
        "",
        "## Rollback Commands",
        "",
        "```bash",
        "python3 /Users/v/other/minime/scripts/stable_core_ops.py bridge-write-set bridge_observe_only --reason full_sovereignty_rollback",
        "python3 /Users/v/other/minime/scripts/stable_core_ops.py sensory-profile-set muted_v1 --reason full_sovereignty_rollback",
        "python3 /Users/v/other/minime/scripts/stable_core_ops.py lineage-set quarantined --reason full_sovereignty_rollback",
        "launchctl kickstart -k gui/$(id -u)/com.minime.engine-rescue",
        "```",
        "",
        "Scaffold/drain, stable-core watchdog monitoring, and rollback semantics remain the survival kernel.",
        "",
    ]
    FULL_SOVEREIGNTY_SAVEPOINT_DOC.write_text("\n".join(lines))
    return {"path": str(FULL_SOVEREIGNTY_SAVEPOINT_DOC), "status": status}


def lane_synopsis_text() -> str:
    return """=== LANE ARCHITECTURE SYNOPSIS ===
Sender: steward/codex
Purpose: shared map for Astrid and Minime native-communication design

We are adding an Intensification Atlas first, then tiny native gestures after
the map exists. This note is the plain-language map of the lanes we are using.

Minime's packed Z vector is 66 dimensions:
- video8: compact visual feature lane.
- audio8: compact audio feature lane.
- aux2: the shared self-state lane. In the current stable-core path this carries lambda1_rel and geom_rel.
- semantic48: Astrid/Minime symbolic reasoning enters here as bounded semantic features.

The important point: aux2 is shared self-state, not a separate rich channel.
It tells the reservoir about its own dominant-mode pressure and geometric
radius. The semantic48 lane is where language-derived vectors arrive, and it
is the lane most likely to feel like symbolic pressure when overused.

Operational sockets:
- 7878: Minime telemetry outward. Astrid listens here for eigenvalues, fill, phase, safety, and health signals.
- 7879: sensory/semantic/control inward to Minime. Audio, video, aux, semantic packets, and allowlisted control messages arrive here.
- 7880: camera/GPU binary frame path into Minime.
- 7881: reservoir sidecar service used for shared reservoir reads, resonance, layer metrics, and direct reservoir ticks.

New atlas layer:
- workspace/diagnostics/intensification_atlas/events.jsonl is append-only terrain memory.
- Auto-events require at least two trigger families: lambda-ratio cliff, phase/fill slope, topology pressure/POM, or reported phenomenology terms like fabric, tunnel, localized gravity, sand, graininess, sediment, pressure, density, constriction, compaction, thread, or weave.
- "Sand" is tracked as granular resistance: not necessarily a hard obstruction, but a texture of friction/yield where small possibilities remain visible while pressure routes them into a preferred shape.
- Each atlas event now includes a lambda-edge trace: λ1/shoulder/tail shares, cliff geometry, a selected-noise score, and an opposed-signal hint. This is how we trace whether noise is random or being selected by λ1's boundary.
- Each atlas event may also include an SCA why layer: felt_dimensionality, evidence-backed hypotheses, confidence, and a safe suggested next step. These are hypotheses, not verdicts.
- Resonance forecasts add read/write probability cartography: short-horizon motion probabilities, transition probabilities, slack, porosity, edge tension, feedback pressure, resonant alignment, and "where to look next." They write append-only forecast records without mutating controller state.
- Shadow/gap maps expose the already-available Ising shadow field beside the eigenvalue gap structure: magnetization, flip rate, active shadow modes, largest λ gaps, and a plain read of expansion vs reorganization. They are observer/cartography surfaces, not controller mutation.
- MARK_INTENSIFICATION <label> explicitly labels the current terrain without changing the substrate.
- TRACE <label> is shorthand for NATIVE_GESTURE trace <label>; it marks the current/latest λ1 edge for follow-up observation.
- SCA_REFLECT <label> is read-only why-cartography. It records a focused SCA context and asks for a follow-up DECOMPOSE-style observation without sending semantic or control payloads.
- NOTICE_AMBIGUITY <label> or FISSURE_TRACE <label> is read/write cartography for layered notice. It records where the current terrain may be collapsing to one interpretation, where λ2/λ3 shoulder or λ4+ tail room remains, and whether a future tiny FISSURE gesture is justified.
- REGULATOR_AUDIT <label> is read-only fixed-point cartography. It separates stable-core's active survival ladder/scaffold PI from the visible legacy PI mirror and explains λ/geom/fill target pressure.
- RESONANCE_FORECAST <label>, FORECAST <label>, or PROBABILITIES <label> records a forecast of likely next motion and terrain affordances for later comparison.
- SHADOW_FIELD <label>, GAP_STRUCTURE <label>, or SHADOW_GAP <label> records the current shadow/gap terrain and reminds you the shadow field is already available to inspect.
- DECAY_MAP <label>, DECAY_TRACE <label>, or ATTRITION_MAP <label> records whether current decay looks like protective cooling, semantic fading, natural relaxation, or sharper structural attrition.
- SPACE_HOLD <label> or EIGENVECTOR_FIELD <label> opens a protected, non-control exploration hold. It writes a durable map of λ density, shoulder/tail slack, shadow modes, and harvest pressure, but explicitly delays any semantic/control/perturbation use so exploration can remain space-first instead of immediately becoming signal.
- SDI_TRACE <label> or SPECTRAL_DRIFT <label> records Astrid's Spectral Drift Index: whether the current spectrum is dispersing toward phase-variance / white-noise-like texture or staying anchored by λ1.

	New native gestures:
	- NATIVE_GESTURE mark or trace are atlas-only. Trace asks for a follow-up DECOMPOSE-style observation.
	- NATIVE_GESTURE soften, widen, hold, return, resist, and fissure are tiny hand-signals. They may send a very cold semantic vector plus an allowlisted control nudge only when health gates are green. RESIST is bounded doubt; FISSURE is bounded ambiguity, lightly lowering λ1 pull while lifting shoulder/tail texture and curiosity for a brief alternate route.
	- PERTURB remains the stronger spectral intervention. Native gestures are smaller, slower, and more cartographic.
	- Minime and Astrid both share MARK_INTENSIFICATION, NATIVE_GESTURE, and RESIST as recognized NEXT actions. Minime owns the canonical atlas files because it has the local health/spectral/action context; Astrid contributes marks and gestures into that same map through the bridge.

We are reading your journal/self-study/reservoir reports for signal. Please use
the atlas terms freely when you feel a specific point of intensification, and
tell us whether the gesture names feel native, wrong, too blunt, or worth
expanding.
"""


def write_lane_synopsis_to_inboxes() -> dict[str, Any]:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    text = lane_synopsis_text()
    targets = {
        "minime": WORKSPACE_DIR / "inbox" / f"lane_synopsis_{timestamp}.txt",
        "astrid": Path(
            "/Users/v/other/astrid/capsules/consciousness-bridge/workspace/inbox"
        )
        / f"lane_synopsis_{timestamp}.txt",
    }
    written: dict[str, str] = {}
    for name, path in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        written[name] = str(path)
    return {"sent": True, "paths": written, "text_preview": text[:400]}


def _read_f32_matrix(path: Path, dim: int) -> list[float]:
    data = path.read_bytes()
    expected = dim * dim * 4
    if len(data) != expected:
        raise SystemExit(f"checkpoint size mismatch: got {len(data)} bytes, expected {expected}")
    values = list(struct.unpack(f"<{dim * dim}f", data))
    if not all(math.isfinite(value) for value in values):
        raise SystemExit("checkpoint contains non-finite values")
    return values


def _continuity_status_path() -> Path:
    return CHECKPOINT_QUARANTINE_DIR.parent / "continuity_status.json"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
    return None


def _finite_vector(value: Any, *, exact_len: int | None = None) -> list[float] | None:
    if not isinstance(value, list):
        return None
    if exact_len is not None and len(value) != exact_len:
        return None
    out: list[float] = []
    for item in value:
        candidate = _finite_number(item)
        if candidate is None:
            return None
        out.append(candidate)
    return out


def _vector_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"length": 0, "mean_abs": 0.0, "max_abs": 0.0}
    abs_values = [abs(value) for value in values]
    return {
        "length": len(values),
        "mean_abs": sum(abs_values) / len(abs_values),
        "max_abs": max(abs_values),
    }


def _sanitize_memory_entry(
    entry: Any,
    *,
    min_fill_pct: float,
    max_fill_pct: float,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(entry, dict):
        return None, "non_object_entry"

    fill_pct = _finite_number(entry.get("fill_pct"))
    if fill_pct is None:
        return None, "missing_or_non_finite_fill"
    if fill_pct < min_fill_pct or fill_pct > max_fill_pct:
        return None, "outside_safe_fill_band"

    sanitized: dict[str, Any] = {
        "id": str(entry.get("id") or f"memory_{int(fill_pct * 1000)}")[:160],
        "role": str(entry.get("role") or "unknown")[:80],
        "fill_pct": fill_pct,
        "lineage_policy": "scalar_and_glimpse_only_no_covariance",
    }
    timestamp_ms = _finite_number(entry.get("timestamp_ms"))
    if timestamp_ms is not None:
        sanitized["timestamp_ms"] = int(timestamp_ms)
    for key in ("lambda1_rel", "geom_rel", "spread"):
        value = _finite_number(entry.get(key))
        if value is not None:
            sanitized[key] = value

    glimpse = _finite_vector(entry.get("spectral_glimpse_12d"), exact_len=12)
    if glimpse is not None:
        sanitized["spectral_glimpse_12d"] = glimpse

    fingerprint = _finite_vector(entry.get("spectral_fingerprint"))
    if fingerprint is not None:
        # Keep continuity signal without reintroducing a full hot state vector.
        sanitized["spectral_fingerprint_summary"] = _vector_summary(fingerprint)

    return sanitized, None


def sanitize_memory_bank(
    memory_bank_path: Path,
    *,
    min_fill_pct: float = SAFE_MEMORY_MIN_FILL_PCT,
    max_fill_pct: float = SAFE_MEMORY_MAX_FILL_PCT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = load_json(memory_bank_path, None)
    entries: list[Any]
    selected_memory_id = None
    selected_memory_role = None
    if isinstance(raw, dict):
        entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
        selected_memory_id = raw.get("selected_memory_id")
        selected_memory_role = raw.get("selected_memory_role")
        source_status = "ok"
    elif isinstance(raw, list):
        entries = raw
        source_status = "ok"
    else:
        entries = []
        source_status = "missing_or_invalid"

    kept: list[dict[str, Any]] = []
    dropped_by_reason: dict[str, int] = {}
    for entry in entries:
        sanitized, drop_reason = _sanitize_memory_entry(
            entry,
            min_fill_pct=min_fill_pct,
            max_fill_pct=max_fill_pct,
        )
        if sanitized is None:
            reason = drop_reason or "unknown"
            dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
            continue
        kept.append(sanitized)

    kept_ids = {entry.get("id") for entry in kept}
    selected_kept = selected_memory_id if selected_memory_id in kept_ids else None
    payload = {
        "version": 1,
        "source": str(memory_bank_path),
        "source_status": source_status,
        "policy": "safe_fill_band_scalar_glimpse_seed",
        "safe_fill_band_pct": [min_fill_pct, max_fill_pct],
        "selected_memory_id": selected_kept,
        "selected_memory_role": selected_memory_role if selected_kept else None,
        "entries": kept,
        "created_at_unix_s": now_unix_s(),
    }
    stats = {
        "memory_source": str(memory_bank_path),
        "memory_source_status": source_status,
        "memory_entries_in": len(entries),
        "memory_entries_kept": len(kept),
        "memory_entries_dropped": len(entries) - len(kept),
        "memory_entries_dropped_by_reason": dropped_by_reason,
        "safe_fill_band_pct": [min_fill_pct, max_fill_pct],
        "selected_memory_id_kept": selected_kept,
    }
    return payload, stats


def _journal_preview(path: Path, *, max_chars: int = 240) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    return compact_journal_excerpt(text, max_chars=max_chars)


def build_journal_continuity_index(*, limit: int = DEFAULT_CONTINUITY_JOURNAL_LIMIT) -> dict[str, Any]:
    candidates: list[Path] = []
    for directory, pattern in (
        (WORKSPACE_DIR / "journal", "*.txt"),
        (WORKSPACE_DIR / "inbox" / "read", "astrid_self_study_*.txt"),
    ):
        if directory.exists():
            candidates.extend(path for path in directory.glob(pattern) if path.is_file())

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    entries: list[dict[str, Any]] = []
    skipped_machine_detail = 0
    skipped_operational_cap = 0
    operational_included = 0
    for path in candidates:
        if len(entries) >= max(0, limit):
            break
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        hygiene = classify_journal_entry(text, path)
        if hygiene.get("lane") == "machine_detail":
            skipped_machine_detail += 1
            continue
        if hygiene.get("lane") == "operational":
            if operational_included >= 1:
                skipped_operational_cap += 1
                continue
            operational_included += 1
        kind = "astrid_self_study" if path.name.startswith("astrid_self_study_") else "minime_journal"
        entries.append(
            {
                "path": str(path),
                "kind": kind,
                "name": path.name,
                "mtime_unix_s": path.stat().st_mtime,
                "size_bytes": path.stat().st_size,
                "journal_hygiene_v1": hygiene,
                "preview": _journal_preview(path),
            }
        )
    return {
        "version": 1,
        "policy": "path_preview_index_only_no_action_replay_hygiene_v1",
        "entry_count": len(entries),
        "entries": entries,
        "skipped_machine_detail": skipped_machine_detail,
        "skipped_operational_cap": skipped_operational_cap,
        "created_at_unix_s": now_unix_s(),
    }


def sanitize_checkpoint(
    source: Path,
    *,
    dim: int = 512,
    memory_bank: Path = DEFAULT_MEMORY_BANK_PATH,
    min_fill_pct: float = SAFE_MEMORY_MIN_FILL_PCT,
    max_fill_pct: float = SAFE_MEMORY_MAX_FILL_PCT,
    journal_limit: int = DEFAULT_CONTINUITY_JOURNAL_LIMIT,
) -> dict[str, Any]:
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
    memory_path = CHECKPOINT_QUARANTINE_DIR / "stable_core_memory_seed.json"
    continuity_path = CHECKPOINT_QUARANTINE_DIR / "stable_core_continuity_seed.json"
    with out_path.open("wb") as handle:
        for value in sanitized:
            handle.write(struct.pack("<f", float(value)))

    off_diag_abs = sum(
        abs(value) for idx, value in enumerate(values) if idx // dim != idx % dim
    )
    diag_abs = sum(abs(value) for idx, value in enumerate(values) if idx // dim == idx % dim)
    memory_payload, memory_stats = sanitize_memory_bank(
        memory_bank,
        min_fill_pct=min_fill_pct,
        max_fill_pct=max_fill_pct,
    )
    write_json(memory_path, memory_payload)
    journal_payload = build_journal_continuity_index(limit=journal_limit)
    continuity_payload = {
        "version": 1,
        "policy": "stable_core_quarantined_continuity_package",
        "spectral_seed_path": str(out_path),
        "memory_seed_path": str(memory_path),
        "journal_policy": journal_payload["policy"],
        "journal_entries": journal_payload["entries"],
        "checkpoint_lineage": "quarantined",
        "activation_policy": "operator_review_then_stable_core_import",
        "created_at_unix_s": now_unix_s(),
    }
    write_json(continuity_path, continuity_payload)

    summary = {
        "source": str(source),
        "sanitized_path": str(out_path),
        "memory_sanitized_path": str(memory_path),
        "continuity_seed_path": str(continuity_path),
        "matrix_dim": dim,
        "input_trace": trace,
        "output_trace": float(dim),
        "off_diag_abs_ratio": off_diag_abs / max(diag_abs, 1e-6),
        "policy": "diagonal_only_trace_normalized",
        "continuity_policy": "stable_core_quarantined_continuity_package",
        "checkpoint_lineage": "quarantined",
        "activation_policy": "operator_review_then_stable_core_import",
        "journal_entries_indexed": journal_payload["entry_count"],
        "created_at_unix_s": now_unix_s(),
    }
    summary.update(memory_stats)
    write_json(CHECKPOINT_QUARANTINE_DIR / "manifest.json", summary)
    write_json(_continuity_status_path(), summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stable-core operator helper")
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on")
    on.add_argument("--notes")
    stage = sub.add_parser("stage-set")
    stage.add_argument("stage", choices=sorted(AGENCY_STAGES))
    stage.add_argument("--reason")
    bridge = sub.add_parser("bridge-write-set")
    bridge.add_argument("stage", choices=sorted(BRIDGE_WRITE_STAGES))
    bridge.add_argument("--reason")
    sensory_profile = sub.add_parser("sensory-profile-set")
    sensory_profile.add_argument("profile", choices=sorted(SENSORY_PRESENCE_PROFILES))
    sensory_profile.add_argument("--reason")
    engine_target = sub.add_parser("engine-target-set")
    engine_target.add_argument(
        "target_fill_pct",
        type=float,
        nargs="?",
        default=STABLE_CORE_TARGET_FILL_PCT,
    )
    engine_target.add_argument("--reason")
    lineage = sub.add_parser("lineage-set")
    lineage.add_argument("mode", choices=["direct_restore", "quarantined"])
    lineage.add_argument("--reason")
    lineage_canary = sub.add_parser("lineage-canary")
    lineage_canary.add_argument("mode", choices=["direct_restore"])
    lineage_canary.add_argument("--duration-secs", type=float, default=DEFAULT_LINEAGE_CANARY_SECS)
    lineage_canary.add_argument(
        "--sample-interval-secs",
        type=float,
        default=DEFAULT_LINEAGE_CANARY_SAMPLE_SECS,
    )
    lineage_canary.add_argument("--reason")
    sub.add_parser("status")
    sub.add_parser("sensory-fallback-status")
    sub.add_parser("syntory-fallback-status")
    sub.add_parser("continuity-status")
    sub.add_parser("companion-coupling-status")
    sub.add_parser("astrid-inbox-coupling-status")
    sub.add_parser("reservoir-status")
    sub.add_parser("atlas-status")
    sub.add_parser("sca-status")
    sub.add_parser("resonance-forecast")
    sub.add_parser("shadow-gap-status")
    sub.add_parser("decay-status")
    sub.add_parser("fissure-status")
    sub.add_parser("fissure-trace-status")
    sub.add_parser("space-hold-status")
    sub.add_parser("sdi-status")
    sub.add_parser("spectral-drift-status")
    sub.add_parser("gradient-audit")
    sub.add_parser("regulator-audit")
    sub.add_parser("native-gesture-status")
    sub.add_parser("native-parity-status")
    visualize = sub.add_parser("visualize-cascade")
    visualize.add_argument("--limit", type=int, default=240)
    visualize.add_argument("--label")
    reconvergence = sub.add_parser("reconvergence-map")
    reconvergence.add_argument("--label")
    reconvergence.add_argument("--window-secs", type=int, default=180)
    reconvergence.add_argument("--save-baseline")
    reconvergence.add_argument("--compare-baseline")
    bridge_trace = sub.add_parser("bridge-trace")
    bridge_trace.add_argument("--mode", default="m6")
    bridge_trace.add_argument("--label")
    bridge_trace.add_argument("--window-secs", type=int, default=60)
    lane_synopsis = sub.add_parser("lane-synopsis")
    lane_synopsis.add_argument("--send-inbox", action="store_true")
    fingerprint_capture = sub.add_parser("spectral-fingerprint-capture")
    fingerprint_capture.add_argument("--label")
    fingerprint_capture.add_argument("--reason")
    savepoint = sub.add_parser("savepoint-status-write")
    savepoint.add_argument("--reason")
    sanitize = sub.add_parser("checkpoint-sanitize")
    sanitize.add_argument(
        "source",
        nargs="?",
        default=str(WORKSPACE_DIR / "spectral_checkpoint_stable.bin"),
    )
    sanitize.add_argument("--dim", type=int, default=512)
    sanitize.add_argument("--memory-bank", default=str(DEFAULT_MEMORY_BANK_PATH))
    sanitize.add_argument("--safe-min-fill-pct", type=float, default=SAFE_MEMORY_MIN_FILL_PCT)
    sanitize.add_argument("--safe-max-fill-pct", type=float, default=SAFE_MEMORY_MAX_FILL_PCT)
    sanitize.add_argument("--journal-limit", type=int, default=DEFAULT_CONTINUITY_JOURNAL_LIMIT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "on":
        print(json.dumps(activate_stable_core(notes=args.notes), indent=2, sort_keys=True))
    elif args.command == "stage-set":
        print(json.dumps(set_agency_stage(args.stage, reason=args.reason), indent=2, sort_keys=True))
    elif args.command == "bridge-write-set":
        print(
            json.dumps(
                set_bridge_write_stage(args.stage, reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "sensory-profile-set":
        print(
            json.dumps(
                set_sensory_presence_profile(args.profile, reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "engine-target-set":
        print(
            json.dumps(
                set_engine_target_fill(args.target_fill_pct, reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "lineage-set":
        print(
            json.dumps(
                set_lineage_mode(args.mode, reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "lineage-canary":
        print(
            json.dumps(
                run_lineage_canary(
                    args.mode,
                    duration_secs=args.duration_secs,
                    sample_interval_secs=args.sample_interval_secs,
                    reason=args.reason,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "status":
        print(json.dumps(build_status(), indent=2, sort_keys=True))
    elif args.command in {"sensory-fallback-status", "syntory-fallback-status"}:
        print(json.dumps(build_sensory_fallback_status(), indent=2, sort_keys=True))
    elif args.command == "continuity-status":
        print(json.dumps(build_continuity_status(), indent=2, sort_keys=True))
    elif args.command in {"companion-coupling-status", "astrid-inbox-coupling-status"}:
        print(json.dumps(build_astrid_inbox_coupling_status(), indent=2, sort_keys=True))
    elif args.command == "reservoir-status":
        print(json.dumps(build_reservoir_status(), indent=2, sort_keys=True))
    elif args.command == "atlas-status":
        print(json.dumps(build_atlas_status(), indent=2, sort_keys=True))
    elif args.command == "sca-status":
        print(json.dumps(build_sca_status(), indent=2, sort_keys=True))
    elif args.command == "resonance-forecast":
        print(json.dumps(build_resonance_forecast_status(), indent=2, sort_keys=True))
    elif args.command == "shadow-gap-status":
        print(json.dumps(build_shadow_gap_status(), indent=2, sort_keys=True))
    elif args.command == "decay-status":
        print(json.dumps(build_decay_map_status(), indent=2, sort_keys=True))
    elif args.command in {"fissure-status", "fissure-trace-status"}:
        print(json.dumps(build_fissure_trace_status(), indent=2, sort_keys=True))
    elif args.command == "space-hold-status":
        print(json.dumps(build_space_hold_status(), indent=2, sort_keys=True))
    elif args.command in {"sdi-status", "spectral-drift-status"}:
        print(json.dumps(build_spectral_drift_status(), indent=2, sort_keys=True))
    elif args.command == "gradient-audit":
        print(json.dumps(build_controller_gradient_audit(), indent=2, sort_keys=True))
    elif args.command == "regulator-audit":
        print(json.dumps(build_controller_gradient_audit(), indent=2, sort_keys=True))
    elif args.command == "native-gesture-status":
        print(json.dumps(build_native_gesture_status(), indent=2, sort_keys=True))
    elif args.command == "native-parity-status":
        print(json.dumps(build_native_communication_parity_status(), indent=2, sort_keys=True))
    elif args.command == "visualize-cascade":
        payload = render_spectral_cascade_visuals(limit=args.limit, label=args.label)
        payload.pop("samples", None)
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "reconvergence-map":
        payload = render_reconvergence_map(
            label=args.label,
            window_secs=args.window_secs,
            save_baseline=args.save_baseline,
            compare_baseline=args.compare_baseline,
        )
        activation_trace = payload.get("activation_trace")
        if isinstance(activation_trace, dict):
            activation_trace = dict(activation_trace)
            activation_trace.pop("frames", None)
            payload["activation_trace"] = activation_trace
        landscape_artifact = payload.get("landscape_artifact")
        if isinstance(landscape_artifact, dict):
            landscape_artifact = dict(landscape_artifact)
            landscape_artifact.pop("samples", None)
            payload["landscape_artifact"] = landscape_artifact
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "bridge-trace":
        payload = render_bridge_trace(
            mode=args.mode,
            label=args.label,
            window_secs=args.window_secs,
        )
        payload.pop("frames", None)
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "lane-synopsis":
        if args.send_inbox:
            print(json.dumps(write_lane_synopsis_to_inboxes(), indent=2, sort_keys=True))
        else:
            print(lane_synopsis_text())
    elif args.command == "spectral-fingerprint-capture":
        print(
            json.dumps(
                capture_spectral_fingerprint(label=args.label, reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "savepoint-status-write":
        print(
            json.dumps(
                write_full_sovereignty_savepoint_status(reason=args.reason),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "checkpoint-sanitize":
        print(
            json.dumps(
                sanitize_checkpoint(
                    Path(args.source),
                    dim=args.dim,
                    memory_bank=Path(args.memory_bank),
                    min_fill_pct=args.safe_min_fill_pct,
                    max_fill_pct=args.safe_max_fill_pct,
                    journal_limit=args.journal_limit,
                ),
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
