#!/usr/bin/env python3
"""Helpers for staged Minime rescue stability investigation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_PROJECT_DIR = Path("/Users/v/other/minime")
DEFAULT_RESCUE_WORKTREE = Path("/Users/v/other/worktrees/minime-rescue-b8823ad")
HEALTHY_FILL_THRESHOLD = 60.0
HEALTHY_COLD_START_WINDOW_SECS = 90
HEALTHY_HOLD_WINDOW_SECS = 20 * 60
DEFAULT_HOLD_WINDOW_SECS = HEALTHY_HOLD_WINDOW_SECS
RESCUE_MIN_FILL_AFTER_WARMUP = 45.0
RESCUE_MAX_FILL_AFTER_WARMUP = 82.0
RESCUE_TARGET_FILL = 68.0
RESCUE_REG_TICK_SECS = 0.5
RESCUE_MODE = "rescue_b8823ad"
RESCUE_PHYSIOLOGICAL_FALLBACK = True
BRIDGE_USER_LABEL = "com.astrid.consciousness-bridge"
CAMERA_USER_LABEL = "com.minime.camera-client"
MIC_USER_LABEL = "com.minime.mic-to-sensory"
HOST_SENSORY_USER_LABEL = "com.minime.host-sensory"
VISUAL_FRAME_SERVICE_USER_LABEL = "com.minime.visual-frame-service"
HOME_LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
DEFAULT_OPERATIONAL_PROFILE = "bridge_telemetry_only"
DEFAULT_OPERATIONAL_STATE_VARIANT = "current_live_workspace"
STABLE_CORE_PROFILE = "stable_core_v1"

PROFILE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "full_live": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Rescue engine with bridge, mic, and camera live; agent remains off.",
    },
    "bridge_telemetry_only": {
        "bridge_enabled": True,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": False,
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Rescue engine with bridge attached for telemetry only; no autonomous loop and no semantic ingress.",
    },
    "bridge_observe_only": {
        "bridge_enabled": True,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": True,
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Rescue engine with bridge attached in observe-only mode; mic and camera stay live while semantic ingress is clamped.",
    },
    "bridge_limited_write": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry",
        "limited_write_enabled": True,
        "limited_write_cooldown_secs": 300,
        "limited_write_feature_scale": 0.08,
        "limited_write_max_abs": 0.18,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 68.0,
        "limited_write_rising_epsilon_pct": 0.5,
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
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Rescue bridge with one low-energy dampen/inquiry semantic packet per cooldown; hazardous rising-fill language stays blocked.",
    },
    "bridge_limited_write_v2": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 900,
        "limited_write_feature_scale": 0.04,
        "limited_write_max_abs": 0.10,
        "limited_write_min_fill_pct": 60.0,
        "limited_write_max_fill_pct": 66.0,
        "limited_write_rising_epsilon_pct": 0.25,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 68.0,
        "limited_write_required_stage": "hold",
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 3.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 2,
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
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Self-rolling rescue bridge with green-zone-only low-energy dampen/inquiry writes and automatic observe-only rollback.",
    },
    "bridge_expanded_sovereignty_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
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
        "limited_write_allowed_stages": [
            "hold",
            "elevated",
        ],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 8.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 2,
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
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Expanded rescue sovereignty: high-60s phase motion and self-study modes are allowed while discharge, pressure language, spectral dumps, semantic energy, and repeated adverse responses still self-roll back.",
    },
    "bridge_richer_coupling_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 300,
        "limited_write_feature_scale": 0.08,
        "limited_write_max_abs": 0.18,
        "limited_write_min_fill_pct": 58.0,
        "limited_write_max_fill_pct": 72.0,
        "limited_write_rising_epsilon_pct": 100.0,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 74.0,
        "limited_write_allowed_stages": [
            "hold",
            "elevated",
        ],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 10.0,
        "limited_write_adverse_cooldown_secs": 1200,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 78.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_require_zero_live_divisors": False,
        "rescue_live_audio_divisor": 8,
        "rescue_live_video_divisor": 8,
        "rescue_live_intake_stages": [
            "hold",
            "elevated",
        ],
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
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Richer rescue coupling: small hold-band mic/camera trickle plus expanded semantic sovereignty, with discharge/high-fill/adverse rollback preserved.",
    },
    "bridge_sovereignty_reentry_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "bridge_write_profile": "limited_dampen_inquiry_v2",
        "limited_write_enabled": True,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 120,
        "limited_write_feature_scale": 0.10,
        "limited_write_max_abs": 0.22,
        "limited_write_min_fill_pct": 56.0,
        "limited_write_max_fill_pct": 74.0,
        "limited_write_rising_epsilon_pct": 100.0,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 76.0,
        "limited_write_allowed_stages": [
            "hold",
            "elevated",
        ],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 12.0,
        "limited_write_adverse_cooldown_secs": 600,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 82.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": False,
        "limited_write_block_structural_dump_language": False,
        "rescue_live_audio_divisor": 6,
        "rescue_live_video_divisor": 6,
        "rescue_live_intake_stages": [
            "hold",
            "elevated",
        ],
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
            "evolve",
            "self_study",
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Sovereignty re-entry: broad autonomous expression modes and a faster semantic cadence are allowed while Minime retains hard physiological rollback authority.",
    },
    "bridge_budgeted_sovereignty_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
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
        "limited_write_allowed_stages": [
            "hold",
            "elevated",
        ],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 10.0,
        "limited_write_adverse_cooldown_secs": 600,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 82.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": False,
        "limited_write_require_zero_live_divisors": False,
        "limited_write_require_dampen_inquiry_text": False,
        "limited_write_block_structural_dump_language": False,
        "rescue_live_audio_divisor": 4,
        "rescue_live_video_divisor": 4,
        "rescue_live_intake_stages": [
            "hold",
            "elevated",
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
            "evolve",
            "self_study",
            "research_note",
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Budgeted sovereignty: richer Astrid expression and hold/elevated sensory trickle, still bounded by health-scored rollback.",
    },
    "bridge_full_expression_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
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
        "limited_write_allowed_stages": [
            "hold",
        ],
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
        "rescue_live_audio_divisor": 12,
        "rescue_live_video_divisor": 12,
        "rescue_live_intake_stages": [
            "hold",
        ],
        "stable_core_sensory_presence_profile": "full_presence_v1",
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
            "evolve",
            "self_study",
            "research_note",
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Full expression: broad Astrid semantic modes and simultaneous live sensory trickle, with only hard physiology-backed rollback.",
    },
    "stable_core_v1": {
        "bridge_enabled": True,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": True,
        "host_sensory_enabled": True,
        "visual_frame_service_enabled": True,
        "bridge_write_profile": "observe_only",
        "limited_write_enabled": False,
        "limited_write_policy_version": 2,
        "limited_write_cooldown_secs": 0,
        "limited_write_feature_scale": 0.0,
        "limited_write_max_abs": 0.0,
        "limited_write_min_fill_pct": 60.0,
        "limited_write_max_fill_pct": 66.0,
        "limited_write_rising_epsilon_pct": 0.0,
        "limited_write_health_max_age_secs": 5,
        "limited_write_peak_fill_max_pct": 68.0,
        "limited_write_allowed_stages": [],
        "limited_write_post_send_eval_secs": 120,
        "limited_write_adverse_fill_rise_pct": 3.0,
        "limited_write_adverse_cooldown_secs": 1800,
        "limited_write_rollback_target": "bridge_observe_only",
        "limited_write_rollback_fill_pct": 74.0,
        "limited_write_rollback_adverse_count": 2,
        "limited_write_rollback_on_elevated_peak": True,
        "limited_write_require_zero_live_divisors": True,
        "limited_write_require_dampen_inquiry_text": True,
        "limited_write_block_structural_dump_language": True,
        "rescue_live_audio_divisor": 0,
        "rescue_live_video_divisor": 0,
        "rescue_live_intake_stages": [],
        "stable_core_enabled": True,
        "stable_core_profile": STABLE_CORE_PROFILE,
        "stable_core_agency_stage": "self_journal",
        "stable_core_agent_budget": "self_journal_only",
        "stable_core_allowed_action_families": ["journaling", "self_study"],
        "stable_core_checkpoint_lineage_enabled": False,
        "stable_core_neural_bundle_enabled": False,
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
            "evolve",
            "self_study",
            "research_note",
        ],
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "New Core V1 Gate B: promote the proven rescue physiology as the normal stability kernel with Astrid observe-only and zero live sensory intake until stable-core fill proves itself.",
    },
    "no_bridge_ingress": {
        "bridge_enabled": False,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": False,
        "mic_enabled": True,
        "camera_enabled": True,
        "gpu_av_enabled": True,
        "description": "Rescue engine with mic and camera live but bridge ingress disabled.",
    },
    "no_camera": {
        "bridge_enabled": True,
        "bridge_write_enabled": True,
        "bridge_autonomous_enabled": True,
        "mic_enabled": True,
        "camera_enabled": False,
        "gpu_av_enabled": False,
        "description": "Rescue engine with bridge live, mic enabled, and camera path disabled.",
    },
    "engine_only": {
        "bridge_enabled": False,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": False,
        "mic_enabled": False,
        "camera_enabled": False,
        "gpu_av_enabled": False,
        "description": "Rescue engine alone with only minimal telemetry consumers.",
    },
    "clean_room": {
        "bridge_enabled": False,
        "bridge_write_enabled": False,
        "bridge_autonomous_enabled": False,
        "mic_enabled": False,
        "camera_enabled": False,
        "gpu_av_enabled": False,
        "description": "Rescue engine on a fresh isolated runtime root.",
    },
}

STATE_VARIANTS: dict[str, dict[str, Any]] = {
    "current_live_workspace": {
        "isolated_runtime": False,
        "copy_current_checkpoints": False,
        "disable_checkpoint_restore": False,
        "description": "Use the live runtime root, live workspace, and live checkpoints.",
    },
    "fresh_workspace_current_checkpoints": {
        "isolated_runtime": True,
        "copy_current_checkpoints": True,
        "disable_checkpoint_restore": False,
        "description": "Fresh runtime root with current checkpoints copied into a fresh DB.",
    },
    "fresh_workspace_no_checkpoints": {
        "isolated_runtime": True,
        "copy_current_checkpoints": False,
        "disable_checkpoint_restore": True,
        "description": "Fresh runtime root with checkpoint restore disabled via an empty checkpoint table.",
    },
    "pinned_march_checkpoints": {
        "isolated_runtime": True,
        "copy_current_checkpoints": False,
        "disable_checkpoint_restore": False,
        "description": "Fresh runtime root with pinned March-era checkpoints when available.",
    },
}

MATRIX_PROFILES: list[tuple[str, str]] = [
    ("full_live", "current_live_workspace"),
    ("bridge_telemetry_only", "current_live_workspace"),
    ("bridge_observe_only", "current_live_workspace"),
    ("no_bridge_ingress", "current_live_workspace"),
    ("no_camera", "current_live_workspace"),
    ("engine_only", "current_live_workspace"),
    ("clean_room", "fresh_workspace_no_checkpoints"),
]

STATE_MATRIX_PROFILES: list[tuple[str, str]] = [
    ("engine_only", "current_live_workspace"),
    ("clean_room", "fresh_workspace_current_checkpoints"),
    ("clean_room", "fresh_workspace_no_checkpoints"),
    ("clean_room", "pinned_march_checkpoints"),
]


@dataclass(frozen=True)
class InvestigationContext:
    project_dir: Path
    rescue_worktree: Path

    @property
    def workspace_dir(self) -> Path:
        return self.project_dir / "workspace"

    @property
    def profile_path(self) -> Path:
        return self.workspace_dir / "rescue_profile.json"

    @property
    def status_path(self) -> Path:
        return self.workspace_dir / "rescue_status.json"

    @property
    def spectral_path(self) -> Path:
        return self.workspace_dir / "spectral_state.json"

    @property
    def diagnostics_root(self) -> Path:
        return self.workspace_dir / "diagnostics"

    @property
    def bundle_root(self) -> Path:
        return self.diagnostics_root / "rescue_decay_bundles"

    @property
    def summary_path(self) -> Path:
        return self.diagnostics_root / "rescue_stability_matrix" / "summary.json"

    @property
    def runtime_profiles_root(self) -> Path:
        return self.project_dir / "runtime_profiles"

    @property
    def live_db_path(self) -> Path:
        return self.project_dir / "minime_consciousness.db"

    @property
    def engine_binary(self) -> Path:
        return self.rescue_worktree / "minime" / "target" / "release" / "minime"

    @property
    def current_engine_binary(self) -> Path:
        return self.project_dir / "minime" / "target" / "release" / "minime"

    def engine_binary_for_profile(self, profile_name: str) -> Path:
        if profile_name == STABLE_CORE_PROFILE:
            return self.current_engine_binary
        return self.engine_binary

    @property
    def bridge_log_path(self) -> Path:
        return Path("/tmp/bridge.log")

    @property
    def rescue_engine_log_path(self) -> Path:
        return self.project_dir / "logs" / "minime-engine-rescue.log"

    @property
    def watchdog_log_path(self) -> Path:
        return self.project_dir / "logs" / "minime-rescue-watchdog.log"

    @property
    def camera_log_path(self) -> Path:
        return self.project_dir / "logs" / "camera-client.log"

    @property
    def mic_log_path(self) -> Path:
        return self.project_dir / "logs" / "mic-to-sensory.log"

    @property
    def mic_status_path(self) -> Path:
        return self.project_dir / "workspace" / "runtime" / "mic_status.json"

    @property
    def camera_plist_candidates(self) -> list[Path]:
        return [
            self.project_dir / "launchd" / "com.minime.camera-client.plist",
            HOME_LAUNCH_AGENTS / "com.minime.camera-client.plist",
        ]

    @property
    def mic_plist_candidates(self) -> list[Path]:
        return [
            self.project_dir / "launchd" / "com.minime.mic-to-sensory.plist",
            HOME_LAUNCH_AGENTS / "com.minime.mic-to-sensory.plist",
        ]

    @property
    def host_sensory_plist_candidates(self) -> list[Path]:
        return [
            self.project_dir / "launchd" / "com.minime.host-sensory.plist",
            HOME_LAUNCH_AGENTS / "com.minime.host-sensory.plist",
        ]

    @property
    def visual_frame_service_plist_candidates(self) -> list[Path]:
        return [
            self.project_dir / "launchd" / "com.minime.visual-frame-service.plist",
            HOME_LAUNCH_AGENTS / "com.minime.visual-frame-service.plist",
        ]

    @property
    def bridge_plist_candidates(self) -> list[Path]:
        return [
            Path("/Users/v/other/astrid/launchd/com.astrid.consciousness-bridge.plist"),
            HOME_LAUNCH_AGENTS / "com.astrid.consciousness-bridge.plist",
        ]

    @property
    def launchd_domain(self) -> str:
        return f"gui/{os.getuid()}"


class ProfilePreparationUnavailableError(RuntimeError):
    """Raised when a requested investigation profile cannot be prepared honestly."""

    def __init__(
        self,
        *,
        profile_name: str,
        state_variant: str,
        reason: str,
        notes: Sequence[str] | None = None,
    ) -> None:
        self.profile_name = profile_name
        self.state_variant = state_variant
        self.reason = reason
        self.notes = list(notes or [])
        super().__init__(f"{profile_name}/{state_variant} unavailable: {reason}")


def default_context() -> InvestigationContext:
    return InvestigationContext(
        project_dir=Path(os.environ.get("MINIME_PROJECT_DIR", str(DEFAULT_PROJECT_DIR))),
        rescue_worktree=Path(
            os.environ.get("MINIME_RESCUE_WORKTREE", str(DEFAULT_RESCUE_WORKTREE))
        ),
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_slug(value: str | None = None) -> str:
    return (value or now_iso()).replace(":", "").replace("-", "")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _profile_definition(name: str) -> dict[str, Any]:
    if name not in PROFILE_DEFINITIONS:
        raise ValueError(f"unknown rescue profile: {name}")
    return PROFILE_DEFINITIONS[name]


def _state_definition(name: str) -> dict[str, Any]:
    if name not in STATE_VARIANTS:
        raise ValueError(f"unknown rescue state variant: {name}")
    return STATE_VARIANTS[name]


def default_state_variant_for_profile(profile_name: str) -> str:
    return "fresh_workspace_no_checkpoints" if profile_name == "clean_room" else "current_live_workspace"


def resolve_state_variant(profile_name: str, requested: str | None) -> str:
    state_variant = requested or default_state_variant_for_profile(profile_name)
    _state_definition(state_variant)
    return state_variant


def build_default_profile(context: InvestigationContext) -> dict[str, Any]:
    return _apply_physiological_fallback_metadata(
        {
        "profile": DEFAULT_OPERATIONAL_PROFILE,
        "state_variant": "current_live_workspace",
        "runtime_root": str(context.project_dir),
        "workspace_path": str(context.workspace_dir),
        "db_path": str(context.live_db_path),
        "engine_binary": str(context.engine_binary_for_profile(DEFAULT_OPERATIONAL_PROFILE)),
        "engine_target_fill": RESCUE_TARGET_FILL,
        "reg_tick_secs": RESCUE_REG_TICK_SECS,
        "bridge_enabled": True,
        "effective_bridge_enabled": True,
        "bridge_write_enabled": False,
        "effective_bridge_write_enabled": False,
        "bridge_autonomous_enabled": False,
        "effective_bridge_autonomous_enabled": False,
        "mic_enabled": True,
        "effective_mic_enabled": True,
        "camera_enabled": True,
        "effective_camera_enabled": True,
        "enable_gpu_av": True,
        "hold_window_secs": DEFAULT_HOLD_WINDOW_SECS,
        "matrix_run_id": None,
        "notes": None,
        "mode": "rescue_stability_investigation",
        "checkpoint_mode": "live",
        "checkpoint_source": "live_workspace",
        "created_at": now_iso(),
        "prepared_at": now_iso(),
        }
    )


def _apply_physiological_fallback_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    payload = dict(profile)
    payload["physiological_fallback"] = RESCUE_PHYSIOLOGICAL_FALLBACK
    payload["neural_bundle_enabled"] = False
    payload["checkpoint_restore_enabled"] = False
    payload["checkpoint_save_enabled"] = False
    payload["requested_checkpoint_mode"] = payload.get("checkpoint_mode", "disabled")
    payload["requested_checkpoint_source"] = payload.get("checkpoint_source", "none")
    payload["checkpoint_mode"] = "disabled"
    payload["checkpoint_source"] = "none"
    return payload


def load_active_profile(context: InvestigationContext) -> dict[str, Any]:
    payload = load_json(context.profile_path, {})
    if not isinstance(payload, dict) or not payload:
        return build_default_profile(context)
    return _apply_physiological_fallback_metadata(payload)


def runtime_root_for_profile(
    context: InvestigationContext, profile_name: str, state_variant: str
) -> Path:
    if state_variant == "current_live_workspace":
        return context.project_dir
    return context.runtime_profiles_root / profile_name / state_variant


def _schema_statements(connection: sqlite3.Connection) -> list[str]:
    statements: list[str] = []
    rows = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND type IN ('table', 'index', 'trigger', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY
          CASE type
            WHEN 'table' THEN 0
            WHEN 'index' THEN 1
            WHEN 'trigger' THEN 2
            ELSE 3
          END,
          name
        """
    ).fetchall()
    for (sql,) in rows:
        if isinstance(sql, str):
            statements.append(sql)
    return statements


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def create_schema_only_db(source_db: Path, dest_db: Path) -> None:
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    if dest_db.exists():
        dest_db.unlink()
    with sqlite3.connect(source_db) as source, sqlite3.connect(dest_db) as dest:
        dest.execute("PRAGMA foreign_keys=OFF")
        for statement in _schema_statements(source):
            dest.execute(statement)
        dest.commit()


def copy_table_rows(
    source: sqlite3.Connection,
    dest: sqlite3.Connection,
    table: str,
    *,
    where: str | None = None,
    params: Sequence[Any] = (),
) -> int:
    columns = _table_columns(source, table)
    if not columns:
        return 0
    select_sql = f"SELECT {', '.join(columns)} FROM {table}"
    if where:
        select_sql += f" WHERE {where}"
    rows = source.execute(select_sql, params).fetchall()
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    dest.executemany(insert_sql, rows)
    dest.commit()
    return len(rows)


def pinned_march_checkpoint_db_candidates(context: InvestigationContext) -> list[Path]:
    explicit = os.environ.get("MINIME_PINNED_MARCH_DB")
    candidates = [
        Path(explicit) if explicit else None,
        context.rescue_worktree / "minime_consciousness.db",
        context.rescue_worktree / "workspace" / "minime_consciousness.db",
    ]
    return [path for path in candidates if isinstance(path, Path)]


def prepare_isolated_database(
    context: InvestigationContext, profile_name: str, state_variant: str, dest_db: Path
) -> dict[str, Any]:
    source_db = context.live_db_path
    if not source_db.exists():
        raise FileNotFoundError(f"live DB missing: {source_db}")

    create_schema_only_db(source_db, dest_db)
    copied_tables: dict[str, int] = {}
    checkpoint_source = "none"
    checkpoint_mode = "disabled"
    notes: list[str] = []

    variant = _state_definition(state_variant)
    if state_variant == "fresh_workspace_current_checkpoints":
        with sqlite3.connect(source_db) as source, sqlite3.connect(dest_db) as dest:
            copied_tables["sessions"] = copy_table_rows(source, dest, "sessions")
            copied_tables["nn_checkpoints"] = copy_table_rows(source, dest, "nn_checkpoints")
        checkpoint_source = str(source_db)
        checkpoint_mode = "current_checkpoints"
    elif state_variant == "pinned_march_checkpoints":
        pinned_source = next(
            (candidate for candidate in pinned_march_checkpoint_db_candidates(context) if candidate.exists()),
            None,
        )
        if pinned_source is None:
            raise ProfilePreparationUnavailableError(
                profile_name=profile_name,
                state_variant=state_variant,
                reason="pinned_march_checkpoint_db_unavailable",
                notes=[
                    "Pinned March checkpoint DB unavailable; skipping pinned March checkpoint variant."
                ],
            )
        else:
            with sqlite3.connect(pinned_source) as source, sqlite3.connect(dest_db) as dest:
                copied_tables["sessions"] = copy_table_rows(source, dest, "sessions")
                copied_tables["nn_checkpoints"] = copy_table_rows(source, dest, "nn_checkpoints")
            checkpoint_source = str(pinned_source)
            checkpoint_mode = "pinned_march_checkpoints"
    elif variant["disable_checkpoint_restore"]:
        checkpoint_mode = "disabled"

    return {
        "checkpoint_mode": checkpoint_mode,
        "checkpoint_source": checkpoint_source,
        "copied_tables": copied_tables,
        "notes": notes,
    }


def prepare_runtime_root(
    context: InvestigationContext, profile_name: str, state_variant: str
) -> dict[str, Any]:
    runtime_root = runtime_root_for_profile(context, profile_name, state_variant)
    state_variant_def = _state_definition(state_variant)
    if not state_variant_def["isolated_runtime"]:
        return {
            "runtime_root": str(runtime_root),
            "workspace_path": str(context.workspace_dir),
            "db_path": str(context.live_db_path),
            "checkpoint_mode": "live",
            "checkpoint_source": "live_workspace",
            "copied_tables": {},
            "notes": [],
        }

    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    (runtime_root / "workspace" / "diagnostics").mkdir(parents=True, exist_ok=True)
    (runtime_root / "workspace" / "journal").mkdir(parents=True, exist_ok=True)

    db_path = runtime_root / "minime_consciousness.db"
    db_info = prepare_isolated_database(context, profile_name, state_variant, db_path)
    return {
        "runtime_root": str(runtime_root),
        "workspace_path": str(runtime_root / "workspace"),
        "db_path": str(db_path),
        **db_info,
    }


def prepare_profile(
    context: InvestigationContext,
    *,
    profile_name: str,
    state_variant: str | None = None,
    hold_window_secs: int | None = None,
    matrix_run_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    profile_def = _profile_definition(profile_name)
    resolved_state_variant = resolve_state_variant(profile_name, state_variant)
    runtime_info = prepare_runtime_root(context, profile_name, resolved_state_variant)
    runtime_root = Path(runtime_info["runtime_root"])
    effective_bridge_enabled = bool(
        profile_def["bridge_enabled"] and runtime_root == context.project_dir
    )
    effective_bridge_write_enabled = bool(
        profile_def.get("bridge_write_enabled", profile_def["bridge_enabled"])
        and effective_bridge_enabled
    )
    effective_bridge_autonomous_enabled = bool(
        profile_def.get("bridge_autonomous_enabled", profile_def["bridge_enabled"])
        and effective_bridge_enabled
    )
    effective_mic_enabled = bool(profile_def["mic_enabled"])
    effective_camera_enabled = bool(profile_def["camera_enabled"])
    host_sensory_enabled = bool(
        profile_def.get("host_sensory_enabled", profile_def.get("stable_core_enabled", False))
    )
    visual_frame_service_enabled = bool(
        profile_def.get(
            "visual_frame_service_enabled",
            profile_def.get("stable_core_enabled", False),
        )
    )
    engine_binary = context.engine_binary_for_profile(profile_name)
    payload = {
        "profile": profile_name,
        "state_variant": resolved_state_variant,
        "runtime_root": str(runtime_root),
        "workspace_path": runtime_info["workspace_path"],
        "db_path": runtime_info["db_path"],
        "engine_binary": str(engine_binary),
        "engine_target_fill": RESCUE_TARGET_FILL,
        "reg_tick_secs": RESCUE_REG_TICK_SECS,
        "bridge_enabled": bool(profile_def["bridge_enabled"]),
        "effective_bridge_enabled": effective_bridge_enabled,
        "bridge_write_enabled": bool(
            profile_def.get("bridge_write_enabled", profile_def["bridge_enabled"])
        ),
        "effective_bridge_write_enabled": effective_bridge_write_enabled,
        "bridge_autonomous_enabled": bool(
            profile_def.get("bridge_autonomous_enabled", profile_def["bridge_enabled"])
        ),
        "effective_bridge_autonomous_enabled": effective_bridge_autonomous_enabled,
        "bridge_write_profile": profile_def.get("bridge_write_profile", "unrestricted"),
        "limited_write_enabled": bool(profile_def.get("limited_write_enabled", False)),
        "limited_write_policy_version": int(profile_def.get("limited_write_policy_version", 0)),
        "limited_write_cooldown_secs": int(profile_def.get("limited_write_cooldown_secs", 0)),
        "limited_write_feature_scale": float(profile_def.get("limited_write_feature_scale", 1.0)),
        "limited_write_max_abs": float(profile_def.get("limited_write_max_abs", 5.0)),
        "limited_write_min_fill_pct": float(profile_def.get("limited_write_min_fill_pct", 0.0)),
        "limited_write_max_fill_pct": float(profile_def.get("limited_write_max_fill_pct", 100.0)),
        "limited_write_rising_epsilon_pct": float(
            profile_def.get("limited_write_rising_epsilon_pct", 0.0)
        ),
        "limited_write_semantic_energy_rising_epsilon_pct": float(
            profile_def.get(
                "limited_write_semantic_energy_rising_epsilon_pct",
                profile_def.get("limited_write_rising_epsilon_pct", 0.0),
            )
        ),
        "limited_write_rollback_semantic_energy": float(
            profile_def.get("limited_write_rollback_semantic_energy", 0.05)
        ),
        "limited_write_health_max_age_secs": int(
            profile_def.get("limited_write_health_max_age_secs", 0)
        ),
        "limited_write_peak_fill_max_pct": float(
            profile_def.get("limited_write_peak_fill_max_pct", 100.0)
        ),
        "limited_write_required_stage": profile_def.get("limited_write_required_stage"),
        "limited_write_allowed_stages": list(
            profile_def.get("limited_write_allowed_stages", [])
        ),
        "limited_write_post_send_eval_secs": int(
            profile_def.get("limited_write_post_send_eval_secs", 0)
        ),
        "limited_write_adverse_fill_rise_pct": float(
            profile_def.get("limited_write_adverse_fill_rise_pct", 0.0)
        ),
        "limited_write_adverse_cooldown_secs": int(
            profile_def.get("limited_write_adverse_cooldown_secs", 0)
        ),
        "limited_write_rollback_target": profile_def.get("limited_write_rollback_target"),
        "limited_write_rollback_fill_pct": float(
            profile_def.get("limited_write_rollback_fill_pct", 100.0)
        ),
        "limited_write_rollback_adverse_count": int(
            profile_def.get("limited_write_rollback_adverse_count", 0)
        ),
        "limited_write_rollback_on_elevated_peak": bool(
            profile_def.get("limited_write_rollback_on_elevated_peak", True)
        ),
        "limited_write_require_zero_live_divisors": bool(
            profile_def.get("limited_write_require_zero_live_divisors", True)
        ),
        "limited_write_require_dampen_inquiry_text": bool(
            profile_def.get("limited_write_require_dampen_inquiry_text", True)
        ),
        "limited_write_block_structural_dump_language": bool(
            profile_def.get("limited_write_block_structural_dump_language", True)
        ),
        "limited_write_block_terms_always": bool(
            profile_def.get("limited_write_block_terms_always", False)
        ),
        "limited_write_block_terms_on_rising": bool(
            profile_def.get("limited_write_block_terms_on_rising", True)
        ),
        "limited_write_mute_live_intake_secs": int(
            profile_def.get("limited_write_mute_live_intake_secs", 0)
        ),
        "limited_write_pre_mute_live_intake_secs": int(
            profile_def.get("limited_write_pre_mute_live_intake_secs", 0)
        ),
        "limited_write_require_pre_muted_live_intake": bool(
            profile_def.get("limited_write_require_pre_muted_live_intake", False)
        ),
        "limited_write_serializes_live_intake": bool(
            profile_def.get("limited_write_serializes_live_intake", False)
        ),
        "rescue_live_audio_divisor": int(profile_def.get("rescue_live_audio_divisor", 0)),
        "rescue_live_video_divisor": int(profile_def.get("rescue_live_video_divisor", 0)),
        "rescue_live_intake_stages": list(profile_def.get("rescue_live_intake_stages", [])),
        "stable_core_enabled": bool(profile_def.get("stable_core_enabled", False)),
        "stable_core_profile": profile_def.get("stable_core_profile"),
        "stable_core_agency_stage": profile_def.get("stable_core_agency_stage", "off"),
        "stable_core_agent_budget": profile_def.get("stable_core_agent_budget", "disabled"),
        "stable_core_allowed_action_families": list(
            profile_def.get("stable_core_allowed_action_families", [])
        ),
        "stable_core_sensory_presence_profile": profile_def.get(
            "stable_core_sensory_presence_profile", ""
        ),
        "stable_core_checkpoint_lineage_enabled": bool(
            profile_def.get("stable_core_checkpoint_lineage_enabled", False)
        ),
        "stable_core_neural_bundle_enabled": bool(
            profile_def.get("stable_core_neural_bundle_enabled", False)
        ),
        "limited_write_block_terms": list(profile_def.get("limited_write_block_terms", [])),
        "limited_write_allowed_modes": list(profile_def.get("limited_write_allowed_modes", [])),
        "mic_enabled": bool(profile_def["mic_enabled"]),
        "effective_mic_enabled": effective_mic_enabled,
        "camera_enabled": bool(profile_def["camera_enabled"]),
        "effective_camera_enabled": effective_camera_enabled,
        "host_sensory_enabled": host_sensory_enabled,
        "effective_host_sensory_enabled": host_sensory_enabled,
        "visual_frame_service_enabled": visual_frame_service_enabled,
        "effective_visual_frame_service_enabled": visual_frame_service_enabled,
        "enable_gpu_av": bool(profile_def["gpu_av_enabled"] and effective_camera_enabled),
        "hold_window_secs": int(hold_window_secs or DEFAULT_HOLD_WINDOW_SECS),
        "matrix_run_id": matrix_run_id,
        "notes": notes,
        "mode": "rescue_stability_investigation",
        "runtime_profile": profile_def.get("stable_core_profile", RESCUE_MODE),
        "checkpoint_mode": runtime_info["checkpoint_mode"],
        "checkpoint_source": runtime_info["checkpoint_source"],
        "copied_tables": runtime_info.get("copied_tables", {}),
        "runtime_notes": runtime_info.get("notes", []),
        "created_at": now_iso(),
        "prepared_at": now_iso(),
        "healthy_fill_threshold": HEALTHY_FILL_THRESHOLD,
        "healthy_cold_start_window_secs": HEALTHY_COLD_START_WINDOW_SECS,
        "healthy_hold_window_secs": HEALTHY_HOLD_WINDOW_SECS,
    }
    payload = _apply_physiological_fallback_metadata(payload)
    write_json(context.profile_path, payload)
    return payload


def ensure_active_profile(context: InvestigationContext) -> dict[str, Any]:
    current = load_active_profile(context)
    if context.profile_path.exists():
        persisted = load_json(context.profile_path, {})
        if isinstance(persisted, dict) and persisted != current:
            write_json(context.profile_path, current)
        return current
    payload = prepare_profile(
        context,
        profile_name=str(current.get("profile", "full_live")),
        state_variant=str(current.get("state_variant", "current_live_workspace")),
        hold_window_secs=int(current.get("hold_window_secs", DEFAULT_HOLD_WINDOW_SECS)),
        matrix_run_id=current.get("matrix_run_id"),
        notes=current.get("notes"),
    )
    return payload


def active_runtime_health_path(context: InvestigationContext) -> Path:
    profile = load_active_profile(context)
    return Path(profile["runtime_root"]) / "workspace" / "health.json"


def active_runtime_workspace(context: InvestigationContext) -> Path:
    profile = load_active_profile(context)
    return Path(profile["workspace_path"])


def _existing_plists(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def _service_label(context: InvestigationContext, user_label: str) -> str:
    return f"{context.launchd_domain}/{user_label}"


def bootout_service(context: InvestigationContext, user_label: str) -> None:
    subprocess.run(
        ["launchctl", "bootout", _service_label(context, user_label)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def service_loaded(context: InvestigationContext, user_label: str) -> bool:
    result = subprocess.run(
        ["launchctl", "print", _service_label(context, user_label)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def bootstrap_service(
    context: InvestigationContext, user_label: str, plist_candidates: Iterable[Path]
) -> bool:
    plists = _existing_plists(plist_candidates)
    if not plists:
        return False

    for plist in plists:
        bootout_service(context, user_label)
        bootstrap = subprocess.run(
            ["launchctl", "bootstrap", context.launchd_domain, str(plist)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if bootstrap.returncode != 0:
            continue

        kickstart = subprocess.run(
            ["launchctl", "kickstart", "-k", _service_label(context, user_label)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if kickstart.returncode != 0:
            bootout_service(context, user_label)
            continue

        if service_loaded(context, user_label):
            return True

        bootout_service(context, user_label)

    return False


def quiesce_optional_services(context: InvestigationContext) -> dict[str, Any]:
    bootout_service(context, BRIDGE_USER_LABEL)
    bootout_service(context, MIC_USER_LABEL)
    bootout_service(context, CAMERA_USER_LABEL)
    bootout_service(context, HOST_SENSORY_USER_LABEL)
    bootout_service(context, VISUAL_FRAME_SERVICE_USER_LABEL)
    return {
        "bridge": "stopped",
        "mic": "stopped",
        "camera": "stopped",
        "host_sensory": "stopped",
        "visual_frame_service": "stopped",
    }


def apply_profile_services(context: InvestigationContext, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    active = profile or load_active_profile(context)
    actions: dict[str, Any] = {}
    if active.get("effective_bridge_enabled", False):
        actions["bridge"] = "started" if bootstrap_service(
            context, BRIDGE_USER_LABEL, context.bridge_plist_candidates
        ) else "missing_plist"
    else:
        bootout_service(context, BRIDGE_USER_LABEL)
        actions["bridge"] = "stopped"

    if active.get("effective_mic_enabled", False):
        actions["mic"] = "started" if bootstrap_service(
            context, MIC_USER_LABEL, context.mic_plist_candidates
        ) else "missing_plist"
    else:
        bootout_service(context, MIC_USER_LABEL)
        actions["mic"] = "stopped"

    if active.get("effective_camera_enabled", False):
        actions["camera"] = "started" if bootstrap_service(
            context, CAMERA_USER_LABEL, context.camera_plist_candidates
        ) else "missing_plist"
    else:
        bootout_service(context, CAMERA_USER_LABEL)
        actions["camera"] = "stopped"

    if active.get("effective_host_sensory_enabled", False):
        actions["host_sensory"] = "started" if bootstrap_service(
            context, HOST_SENSORY_USER_LABEL, context.host_sensory_plist_candidates
        ) else "missing_plist"
    else:
        bootout_service(context, HOST_SENSORY_USER_LABEL)
        actions["host_sensory"] = "stopped"

    if active.get("effective_visual_frame_service_enabled", False):
        actions["visual_frame_service"] = "started" if bootstrap_service(
            context,
            VISUAL_FRAME_SERVICE_USER_LABEL,
            context.visual_frame_service_plist_candidates,
        ) else "missing_plist"
    else:
        bootout_service(context, VISUAL_FRAME_SERVICE_USER_LABEL)
        actions["visual_frame_service"] = "stopped"
    return actions


def emit_launch_env(context: InvestigationContext) -> str:
    profile = ensure_active_profile(context)
    target_fill = float(profile["engine_target_fill"])
    exports = {
        "RUNTIME_ROOT": profile["runtime_root"],
        "MINIME_RESCUE_WORKTREE": str(context.rescue_worktree),
        "MINIME_RESCUE_BINARY": profile["engine_binary"],
        # The rescue profile stores percent for operator-facing status, but the
        # pinned March engine CLI still expects a 0-1 ratio.
        "EIGENFILL_TARGET": f"{target_fill / 100.0:.4f}",
        "REG_TICK_SECS": str(profile["reg_tick_secs"]),
        "ENABLE_GPU_AV": "true" if profile.get("enable_gpu_av", False) else "false",
        "MINIME_RESCUE_PROFILE": str(profile["profile"]),
        "MINIME_RESCUE_STATE_VARIANT": str(profile["state_variant"]),
        "MINIME_RESCUE_LIVE_AUDIO_DIVISOR": str(
            int(profile.get("rescue_live_audio_divisor", 0))
        ),
        "MINIME_RESCUE_LIVE_VIDEO_DIVISOR": str(
            int(profile.get("rescue_live_video_divisor", 0))
        ),
        "MINIME_RESCUE_LIVE_INTAKE_STAGES": ",".join(
            str(stage) for stage in profile.get("rescue_live_intake_stages", [])
        ),
        "MINIME_STABLE_CORE_SENSORY_PROFILE": str(
            profile.get("stable_core_sensory_presence_profile") or ""
        ),
        "MINIME_RUNTIME_PROFILE": str(profile.get("runtime_profile", RESCUE_MODE)),
        "MINIME_STABLE_CORE": "1" if profile.get("stable_core_enabled", False) else "0",
        "MINIME_HARD_RECOVERY_RESET": "0"
        if profile.get("stable_core_enabled", False)
        else "1",
        "MINIME_STABLE_CORE_PROFILE": str(profile.get("stable_core_profile") or ""),
        "MINIME_STABLE_CORE_AGENCY_STAGE": str(
            profile.get("stable_core_agency_stage", "off")
        ),
        "MINIME_STABLE_CORE_AGENT_BUDGET": str(
            profile.get("stable_core_agent_budget", "disabled")
        ),
        "SENSORY_SOURCE": "auto"
        if profile.get("effective_host_sensory_enabled", False)
        else "physical",
        "LOOK_SOURCE": "active"
        if profile.get("effective_visual_frame_service_enabled", False)
        else "physical",
        "MINIME_STABLE_CORE_ENABLE_CHECKPOINT_LINEAGE": "1"
        if profile.get("stable_core_checkpoint_lineage_enabled", False)
        else "0",
        "MINIME_STABLE_CORE_ENABLE_NEURAL_BUNDLE": "1"
        if profile.get("stable_core_neural_bundle_enabled", False)
        else "0",
        "MINIME_RESCUE_PHYSIOLOGICAL_FALLBACK": "1",
        "MINIME_RESCUE_DISABLE_NN_CHECKPOINTS": "0"
        if (
            profile.get("stable_core_checkpoint_lineage_enabled", False)
            or profile.get("stable_core_neural_bundle_enabled", False)
        )
        else "1",
        "MINIME_RESCUE_DISABLE_NEURAL_BUNDLE": "0"
        if profile.get("stable_core_neural_bundle_enabled", False)
        else "1",
    }
    return "\n".join(f"{key}={shlex.quote(value)}" for key, value in exports.items())


def _tail_lines(path: Path, line_count: int) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(errors="ignore").splitlines()
    return "\n".join(lines[-line_count:]) + ("\n" if lines else "")


def _safe_copy(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copy2(source, destination)


def _port_snapshot(ports: Sequence[str]) -> dict[str, list[int]]:
    result = subprocess.run(
        [shutil.which("lsof") or "/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-FpPn"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return {port: [] for port in ports}

    active_pid: int | None = None
    snapshot = {port: [] for port in ports}
    port_set = {f":{port}" for port in ports}
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            active_pid = int(line[1:])
        elif line.startswith("n"):
            name = line[1:]
            for port in port_set:
                if name.endswith(port) and active_pid is not None:
                    snapshot[port[1:]].append(active_pid)
    return snapshot


def _pgrep_latest(pattern: str) -> int | None:
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    pids = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    return max(pids) if pids else None


def collect_process_state(context: InvestigationContext, profile: dict[str, Any]) -> dict[str, Any]:
    runtime_root = Path(profile["runtime_root"])
    engine_binary = str(profile.get("engine_binary") or context.engine_binary)
    return {
        "captured_at": now_iso(),
        "runtime_root": str(runtime_root),
        "engine_pid": _pgrep_latest(engine_binary),
        "bridge_pid": _pgrep_latest("consciousness-bridge-server"),
        "mic_pid": _pgrep_latest("mic_to_sensory.py"),
        "camera_pid": _pgrep_latest("camera_client.py"),
        "ports": _port_snapshot(["7878", "7879", "7880"]),
    }


def _summary_template() -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "promotion_criteria": {
            "cold_start_fill_threshold": HEALTHY_FILL_THRESHOLD,
            "cold_start_window_secs": HEALTHY_COLD_START_WINDOW_SECS,
            "hold_window_secs": HEALTHY_HOLD_WINDOW_SECS,
            "three_consecutive_runs_required": 3,
            "soak_window_secs": 2 * 60 * 60,
        },
        "events": [],
        "runs": [],
        "winning_profile": None,
    }


def load_summary(context: InvestigationContext) -> dict[str, Any]:
    payload = load_json(context.summary_path, {})
    if not isinstance(payload, dict) or not payload:
        return _summary_template()
    payload.setdefault("events", [])
    payload.setdefault("runs", [])
    payload.setdefault("promotion_criteria", _summary_template()["promotion_criteria"])
    return payload


def write_summary(context: InvestigationContext, payload: dict[str, Any]) -> None:
    payload["generated_at"] = now_iso()
    write_json(context.summary_path, payload)


def record_summary_event(context: InvestigationContext, event: dict[str, Any]) -> None:
    summary = load_summary(context)
    summary["events"].append(event)
    write_summary(context, summary)


def record_run_result(context: InvestigationContext, run_result: dict[str, Any]) -> None:
    summary = load_summary(context)
    runs = summary["runs"]
    existing_index = next(
        (index for index, item in enumerate(runs) if item.get("run_id") == run_result.get("run_id")),
        None,
    )
    if existing_index is None:
        runs.append(run_result)
    else:
        runs[existing_index] = run_result
    write_summary(context, summary)


def capture_decay_bundle(
    context: InvestigationContext,
    *,
    event: str,
    reason: str | None = None,
    profile: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    active = profile or load_active_profile(context)
    timestamp = now_iso()
    bundle_dir = context.bundle_root / f"{iso_slug(timestamp)}_{active['profile']}_{event}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    runtime_root = Path(active["runtime_root"])
    runtime_health = runtime_root / "workspace" / "health.json"
    _safe_copy(runtime_health, bundle_dir / "health.json")
    _safe_copy(context.spectral_path, bundle_dir / "spectral_state.json")
    _safe_copy(context.status_path, bundle_dir / "rescue_status.json")
    _safe_copy(context.profile_path, bundle_dir / "rescue_profile.json")
    _safe_copy(context.mic_status_path, bundle_dir / "mic_status.json")

    (bundle_dir / "engine_homeostat_window.log").write_text(
        _tail_lines(context.rescue_engine_log_path, 200)
    )
    (bundle_dir / "watchdog_window.log").write_text(
        _tail_lines(context.watchdog_log_path, 160)
    )
    (bundle_dir / "bridge_window.log").write_text(
        _tail_lines(context.bridge_log_path, 120)
    )
    (bundle_dir / "mic_window.log").write_text(
        _tail_lines(context.mic_log_path, 160)
    )
    (bundle_dir / "camera_window.log").write_text(
        _tail_lines(context.camera_log_path, 120)
    )

    process_state = collect_process_state(context, active)
    write_json(bundle_dir / "process_port_state.json", process_state)

    metadata = {
        "captured_at": timestamp,
        "event": event,
        "reason": reason,
        "profile": active["profile"],
        "state_variant": active["state_variant"],
        "runtime_root": active["runtime_root"],
        "workspace_path": active["workspace_path"],
        "db_path": active["db_path"],
        "matrix_run_id": active.get("matrix_run_id"),
        "engine_target_fill": active.get("engine_target_fill", RESCUE_TARGET_FILL),
        "checkpoint_mode": active.get("checkpoint_mode"),
        "checkpoint_source": active.get("checkpoint_source"),
        "extra": extra or {},
    }
    write_json(bundle_dir / "metadata.json", metadata)
    record_summary_event(
        context,
        {
            **metadata,
            "bundle_dir": str(bundle_dir),
        },
    )
    return bundle_dir


def _sample_health(path: Path) -> dict[str, Any]:
    payload = load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _sample_point(elapsed_s: float, health: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "elapsed_s": round(elapsed_s, 3),
        "fill_pct": _as_float(health.get("fill_pct")),
        "health_t_s": _as_float(health.get("t_s")),
        "lambda1_rel": _as_float(health.get("lambda1_rel")),
        "geom_rel": _as_float(health.get("geom_rel")),
        "gate": _as_float(health.get("gate")),
        "filt": _as_float(health.get("filt")),
        "engine_pid": status.get("engine_pid"),
        "watchdog_state": status.get("watchdog_state"),
        "last_restart_at": status.get("last_restart_at"),
    }


def build_run_id(profile_name: str, state_variant: str) -> str:
    return f"{profile_name}_{state_variant}_{iso_slug()}"


def operational_restore_target() -> tuple[str, str]:
    return (DEFAULT_OPERATIONAL_PROFILE, DEFAULT_OPERATIONAL_STATE_VARIANT)


def restore_operational_profile(
    context: InvestigationContext, *, notes: str | None = None
) -> dict[str, Any]:
    profile_name, state_variant = operational_restore_target()
    prepare_profile(
        context,
        profile_name=profile_name,
        state_variant=state_variant,
        hold_window_secs=DEFAULT_HOLD_WINDOW_SECS,
        matrix_run_id=None,
        notes=notes,
    )
    subprocess.run(
        [str(context.project_dir / "scripts" / "minime_rescue_on")],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return load_active_profile(context)


def run_profile(
    context: InvestigationContext,
    *,
    profile_name: str,
    state_variant: str | None,
    hold_window_secs: int,
    sample_interval_secs: int,
    notes: str | None,
    skip_cold_start: bool,
) -> dict[str, Any]:
    resolved_state_variant = resolve_state_variant(profile_name, state_variant)
    run_id = build_run_id(profile_name, resolved_state_variant)
    run_started_at = now_iso()
    try:
        profile = prepare_profile(
            context,
            profile_name=profile_name,
            state_variant=resolved_state_variant,
            hold_window_secs=hold_window_secs,
            matrix_run_id=run_id,
            notes=notes,
        )
    except ProfilePreparationUnavailableError as exc:
        runtime_root = runtime_root_for_profile(context, profile_name, resolved_state_variant)
        workspace_path = (
            context.workspace_dir
            if resolved_state_variant == "current_live_workspace"
            else runtime_root / "workspace"
        )
        db_path = (
            context.live_db_path
            if resolved_state_variant == "current_live_workspace"
            else runtime_root / "minime_consciousness.db"
        )
        run_result = {
            "run_id": run_id,
            "profile": profile_name,
            "state_variant": resolved_state_variant,
            "runtime_root": str(runtime_root),
            "workspace_path": str(workspace_path),
            "db_path": str(db_path),
            "started_at": run_started_at,
            "ended_at": now_iso(),
            "hold_window_secs": hold_window_secs,
            "sample_interval_secs": sample_interval_secs,
            "notes": notes,
            "status": "unavailable",
            "availability_reason": exc.reason,
            "runtime_notes": exc.notes,
            "time_to_healthy_fill_s": None,
            "reached_healthy_fill_within_90s": False,
            "time_to_first_contraction_s": None,
            "time_to_restart_s": None,
            "restart_detected": False,
            "minimum_fill_pct": None,
            "maximum_fill_pct": None,
            "minimum_fill_after_warmup_pct": None,
            "maximum_fill_after_warmup_pct": None,
            "below_45_after_warmup_count": 0,
            "above_82_after_warmup_count": 0,
            "ending_fill_pct": None,
            "rescue_soak_criteria_passed": False,
            "sustained_healthy_hold": False,
            "samples": [],
            "bridge_enabled": False,
            "mic_enabled": False,
            "camera_enabled": False,
            "gpu_av_enabled": False,
            "checkpoint_mode": "unavailable",
            "checkpoint_source": "unavailable",
        }
        record_run_result(context, run_result)
        record_summary_event(
            context,
            {
                "captured_at": now_iso(),
                "event": "run_unavailable",
                "reason": exc.reason,
                "profile": profile_name,
                "state_variant": resolved_state_variant,
                "runtime_root": str(runtime_root),
                "workspace_path": str(workspace_path),
                "db_path": str(db_path),
                "matrix_run_id": run_id,
                "engine_target_fill": RESCUE_TARGET_FILL,
                "checkpoint_mode": "unavailable",
                "checkpoint_source": "unavailable",
                "extra": {"runtime_notes": exc.notes},
            },
        )
        return run_result

    if not skip_cold_start:
        subprocess.run(
            [str(context.project_dir / "scripts" / "minime_rescue_on")],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    status = load_json(context.status_path, {})
    initial_restart_at = status.get("last_restart_at")
    initial_engine_pid = status.get("engine_pid")
    if initial_engine_pid is None:
        initial_engine_pid = collect_process_state(context, profile).get("engine_pid")
    start_monotonic = time.monotonic()
    health_path = Path(profile["runtime_root"]) / "workspace" / "health.json"
    samples: list[dict[str, Any]] = []
    time_to_healthy_fill_s: float | None = None
    time_to_first_contraction_s: float | None = None
    time_to_restart_s: float | None = None
    restart_reason: str | None = None
    previous_health_t_s: float | None = None
    reached_healthy_band = False

    while True:
        elapsed_s = time.monotonic() - start_monotonic
        status = load_json(context.status_path, {})
        health = _sample_health(health_path)
        sample = _sample_point(elapsed_s, health, status)
        samples.append(sample)

        fill_pct = sample["fill_pct"]
        if fill_pct is not None and fill_pct >= HEALTHY_FILL_THRESHOLD:
            reached_healthy_band = True
            if time_to_healthy_fill_s is None:
                time_to_healthy_fill_s = elapsed_s
        elif reached_healthy_band and time_to_first_contraction_s is None:
            time_to_first_contraction_s = elapsed_s

        current_restart_at = status.get("last_restart_at")
        if initial_restart_at and current_restart_at and current_restart_at != initial_restart_at:
            time_to_restart_s = elapsed_s
            restart_reason = "watchdog_restart_at_changed"
            break

        current_engine_pid = status.get("engine_pid")
        if initial_engine_pid is not None and current_engine_pid not in (None, initial_engine_pid):
            time_to_restart_s = elapsed_s
            restart_reason = "engine_pid_changed"
            break

        current_health_t_s = sample.get("health_t_s")
        if (
            isinstance(previous_health_t_s, (int, float))
            and isinstance(current_health_t_s, (int, float))
            and current_health_t_s + float(sample_interval_secs) < previous_health_t_s
        ):
            time_to_restart_s = elapsed_s
            restart_reason = "engine_uptime_reset"
            break
        if isinstance(current_health_t_s, (int, float)):
            previous_health_t_s = current_health_t_s

        if elapsed_s >= hold_window_secs:
            break
        time.sleep(sample_interval_secs)

    fills = [sample["fill_pct"] for sample in samples if isinstance(sample.get("fill_pct"), (int, float))]
    post_warmup_samples = [
        sample
        for sample in samples
        if sample["elapsed_s"] >= HEALTHY_COLD_START_WINDOW_SECS
        and isinstance(sample.get("fill_pct"), (int, float))
    ]
    post_warmup_fills = [float(sample["fill_pct"]) for sample in post_warmup_samples]
    below_45_after_warmup_count = sum(
        1 for fill in post_warmup_fills if fill < RESCUE_MIN_FILL_AFTER_WARMUP
    )
    above_82_after_warmup_count = sum(
        1 for fill in post_warmup_fills if fill > RESCUE_MAX_FILL_AFTER_WARMUP
    )
    post_healthy_samples = []
    if time_to_healthy_fill_s is not None:
        post_healthy_samples = [
            sample for sample in samples if sample["elapsed_s"] >= time_to_healthy_fill_s
        ]
    sustained_healthy_hold = bool(
        time_to_restart_s is None
        and time_to_healthy_fill_s is not None
        and time_to_healthy_fill_s <= HEALTHY_COLD_START_WINDOW_SECS
        and post_healthy_samples
        and all(
            isinstance(sample.get("fill_pct"), (int, float))
            and float(sample["fill_pct"]) >= HEALTHY_FILL_THRESHOLD
            for sample in post_healthy_samples
        )
        and samples[-1]["elapsed_s"] >= hold_window_secs
    )
    rescue_soak_criteria_passed = bool(
        time_to_restart_s is None
        and time_to_healthy_fill_s is not None
        and time_to_healthy_fill_s <= HEALTHY_COLD_START_WINDOW_SECS
        and post_warmup_fills
        and below_45_after_warmup_count == 0
        and above_82_after_warmup_count == 0
        and samples[-1]["elapsed_s"] >= hold_window_secs
    )

    run_result = {
        "run_id": run_id,
        "profile": profile["profile"],
        "state_variant": profile["state_variant"],
        "runtime_root": profile["runtime_root"],
        "workspace_path": profile["workspace_path"],
        "db_path": profile["db_path"],
        "started_at": run_started_at,
        "ended_at": now_iso(),
        "hold_window_secs": hold_window_secs,
        "sample_interval_secs": sample_interval_secs,
        "notes": notes,
        "time_to_healthy_fill_s": round(time_to_healthy_fill_s, 3)
        if time_to_healthy_fill_s is not None
        else None,
        "reached_healthy_fill_within_90s": bool(
            time_to_healthy_fill_s is not None
            and time_to_healthy_fill_s <= HEALTHY_COLD_START_WINDOW_SECS
        ),
        "time_to_first_contraction_s": round(time_to_first_contraction_s, 3)
        if time_to_first_contraction_s is not None
        else None,
        "time_to_restart_s": round(time_to_restart_s, 3) if time_to_restart_s is not None else None,
        "restart_detected": time_to_restart_s is not None,
        "restart_reason": restart_reason,
        "initial_engine_pid": initial_engine_pid,
        "ending_engine_pid": samples[-1].get("engine_pid") if samples else None,
        "minimum_fill_pct": min(fills) if fills else None,
        "maximum_fill_pct": max(fills) if fills else None,
        "minimum_fill_after_warmup_pct": min(post_warmup_fills)
        if post_warmup_fills
        else None,
        "maximum_fill_after_warmup_pct": max(post_warmup_fills)
        if post_warmup_fills
        else None,
        "below_45_after_warmup_count": below_45_after_warmup_count,
        "above_82_after_warmup_count": above_82_after_warmup_count,
        "ending_fill_pct": fills[-1] if fills else None,
        "rescue_soak_criteria_passed": rescue_soak_criteria_passed,
        "sustained_healthy_hold": sustained_healthy_hold,
        "samples": samples,
        "bridge_enabled": profile["effective_bridge_enabled"],
        "mic_enabled": profile["effective_mic_enabled"],
        "camera_enabled": profile["effective_camera_enabled"],
        "gpu_av_enabled": profile["enable_gpu_av"],
        "checkpoint_mode": profile["checkpoint_mode"],
        "checkpoint_source": profile["checkpoint_source"],
        "status": "completed",
    }
    record_run_result(context, run_result)
    return run_result


def run_profile_sequence(
    context: InvestigationContext,
    *,
    sequence: Sequence[tuple[str, str]],
    hold_window_secs: int,
    sample_interval_secs: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for profile_name, state_variant in sequence:
        results.append(
            run_profile(
                context,
                profile_name=profile_name,
                state_variant=state_variant,
                hold_window_secs=hold_window_secs,
                sample_interval_secs=sample_interval_secs,
                notes=None,
                skip_cold_start=False,
            )
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minime rescue stability investigation helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-active-profile")
    prepare.add_argument("--profile", default=DEFAULT_OPERATIONAL_PROFILE)
    prepare.add_argument("--state-variant")
    prepare.add_argument("--hold-window-secs", type=int, default=DEFAULT_HOLD_WINDOW_SECS)
    prepare.add_argument("--matrix-run-id")
    prepare.add_argument("--notes")
    prepare.add_argument("--json", action="store_true")

    subparsers.add_parser("ensure-active-profile")
    subparsers.add_parser("emit-launch-env")
    subparsers.add_parser("quiesce-optional-services")
    subparsers.add_parser("apply-profile-services")

    capture = subparsers.add_parser("capture-bundle")
    capture.add_argument("--event", required=True)
    capture.add_argument("--reason")
    capture.add_argument("--extra-json")

    run_one = subparsers.add_parser("run-profile")
    run_one.add_argument("--profile", required=True)
    run_one.add_argument("--state-variant")
    run_one.add_argument("--hold-window-secs", type=int, default=DEFAULT_HOLD_WINDOW_SECS)
    run_one.add_argument("--sample-interval-secs", type=int, default=10)
    run_one.add_argument("--notes")
    run_one.add_argument("--skip-cold-start", action="store_true")

    run_matrix_parser = subparsers.add_parser("run-matrix")
    run_matrix_parser.add_argument("--hold-window-secs", type=int, default=DEFAULT_HOLD_WINDOW_SECS)
    run_matrix_parser.add_argument("--sample-interval-secs", type=int, default=10)
    run_matrix_parser.add_argument("--leave-active-profile", action="store_true")

    run_state_matrix = subparsers.add_parser("run-state-matrix")
    run_state_matrix.add_argument("--hold-window-secs", type=int, default=DEFAULT_HOLD_WINDOW_SECS)
    run_state_matrix.add_argument("--sample-interval-secs", type=int, default=10)
    run_state_matrix.add_argument("--leave-active-profile", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    context = default_context()

    if args.command == "prepare-active-profile":
        payload = prepare_profile(
            context,
            profile_name=args.profile,
            state_variant=args.state_variant,
            hold_window_secs=args.hold_window_secs,
            matrix_run_id=args.matrix_run_id,
            notes=args.notes,
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(str(context.profile_path))
        return

    if args.command == "ensure-active-profile":
        payload = ensure_active_profile(context)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    if args.command == "emit-launch-env":
        print(emit_launch_env(context))
        return

    if args.command == "quiesce-optional-services":
        print(json.dumps(quiesce_optional_services(context), indent=2, sort_keys=True))
        return

    if args.command == "apply-profile-services":
        print(json.dumps(apply_profile_services(context), indent=2, sort_keys=True))
        return

    if args.command == "capture-bundle":
        extra = json.loads(args.extra_json) if args.extra_json else None
        bundle_dir = capture_decay_bundle(
            context,
            event=args.event,
            reason=args.reason,
            extra=extra,
        )
        print(str(bundle_dir))
        return

    if args.command == "run-profile":
        result = run_profile(
            context,
            profile_name=args.profile,
            state_variant=args.state_variant,
            hold_window_secs=args.hold_window_secs,
            sample_interval_secs=args.sample_interval_secs,
            notes=args.notes,
            skip_cold_start=args.skip_cold_start,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "run-matrix":
        results = run_profile_sequence(
            context,
            sequence=MATRIX_PROFILES,
            hold_window_secs=args.hold_window_secs,
            sample_interval_secs=args.sample_interval_secs,
        )
        if not args.leave_active_profile:
            restore_operational_profile(
                context, notes="post_live_load_matrix_restore_to_no_bridge_ingress"
            )
        print(json.dumps(results, indent=2, sort_keys=True))
        return

    if args.command == "run-state-matrix":
        results = run_profile_sequence(
            context,
            sequence=STATE_MATRIX_PROFILES,
            hold_window_secs=args.hold_window_secs,
            sample_interval_secs=args.sample_interval_secs,
        )
        if not args.leave_active_profile:
            restore_operational_profile(
                context, notes="post_state_matrix_restore_to_no_bridge_ingress"
            )
        print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
