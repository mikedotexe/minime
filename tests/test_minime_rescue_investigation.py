"""Tests for staged rescue stability investigation helpers."""

from __future__ import annotations

import json
import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from minime_rescue_investigation import (  # noqa: E402
    InvestigationContext,
    ProfilePreparationUnavailableError,
    bootstrap_service,
    capture_decay_bundle,
    emit_launch_env,
    load_summary,
    operational_restore_target,
    prepare_profile,
)


def build_context(base_dir: Path) -> InvestigationContext:
    project_dir = base_dir / "project"
    rescue_worktree = base_dir / "rescue"
    (project_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (project_dir / "logs").mkdir(parents=True, exist_ok=True)
    (rescue_worktree / "minime" / "target" / "release").mkdir(parents=True, exist_ok=True)
    return InvestigationContext(project_dir=project_dir, rescue_worktree=rescue_worktree)


def seed_live_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY,
                start_time REAL NOT NULL
            );
            CREATE TABLE nn_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                network TEXT NOT NULL,
                weights BLOB NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX idx_checkpoint_network ON nn_checkpoints(network, timestamp DESC);
            """
        )
        connection.execute("INSERT INTO sessions (session_id, start_time) VALUES (1, 1000.0)")
        connection.execute(
            """
            INSERT INTO nn_checkpoints (session_id, timestamp, network, weights)
            VALUES (1, 1001.0, 'predictor', ?)
            """,
            (sqlite3.Binary(b"checkpoint"),),
        )
        connection.commit()


class TestMinimeRescueInvestigation(unittest.TestCase):
    def test_prepare_profile_uses_live_root_for_full_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="full_live",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-live",
                notes="test",
            )

            self.assertEqual(profile["runtime_root"], str(context.project_dir))
            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertTrue(profile["effective_mic_enabled"])
            self.assertTrue(profile["effective_camera_enabled"])
            self.assertTrue(profile["physiological_fallback"])
            self.assertFalse(profile["neural_bundle_enabled"])
            self.assertFalse(profile["checkpoint_restore_enabled"])
            self.assertFalse(profile["checkpoint_save_enabled"])
            self.assertEqual(profile["requested_checkpoint_mode"], "live")
            self.assertEqual(profile["checkpoint_mode"], "disabled")

    def test_prepare_profile_keeps_mic_on_for_no_camera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="no_camera",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-no-camera",
                notes=None,
            )

            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertTrue(profile["effective_mic_enabled"])
            self.assertFalse(profile["effective_camera_enabled"])

    def test_prepare_profile_enables_bridge_but_blocks_writes_for_observe_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_observe_only",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-observe-only",
                notes=None,
            )

            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertFalse(profile["effective_bridge_write_enabled"])
            self.assertTrue(profile["effective_bridge_autonomous_enabled"])
            self.assertTrue(profile["effective_mic_enabled"])
            self.assertTrue(profile["effective_camera_enabled"])

    def test_prepare_profile_limited_write_v2_is_green_zone_self_rolling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_limited_write_v2",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-limited-v2",
                notes=None,
            )

            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertTrue(profile["effective_bridge_write_enabled"])
            self.assertTrue(profile["effective_bridge_autonomous_enabled"])
            self.assertEqual(profile["bridge_write_profile"], "limited_dampen_inquiry_v2")
            self.assertEqual(profile["limited_write_policy_version"], 2)
            self.assertEqual(profile["limited_write_cooldown_secs"], 900)
            self.assertEqual(profile["limited_write_feature_scale"], 0.04)
            self.assertEqual(profile["limited_write_max_abs"], 0.10)
            self.assertEqual(profile["limited_write_min_fill_pct"], 60.0)
            self.assertEqual(profile["limited_write_max_fill_pct"], 66.0)
            self.assertEqual(profile["limited_write_health_max_age_secs"], 5)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 68.0)
            self.assertEqual(profile["limited_write_required_stage"], "hold")
            self.assertEqual(profile["limited_write_post_send_eval_secs"], 120)
            self.assertEqual(profile["limited_write_adverse_fill_rise_pct"], 3.0)
            self.assertEqual(profile["limited_write_adverse_cooldown_secs"], 1800)
            self.assertEqual(profile["limited_write_rollback_target"], "bridge_observe_only")
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 74.0)
            self.assertEqual(profile["limited_write_rollback_adverse_count"], 2)
            self.assertEqual(profile["limited_write_allowed_modes"], ["dialogue_live", "witness"])

    def test_prepare_profile_expanded_sovereignty_allows_high_60s_and_self_study_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_expanded_sovereignty_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-expanded-sovereignty",
                notes=None,
            )

            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertTrue(profile["effective_bridge_write_enabled"])
            self.assertTrue(profile["effective_bridge_autonomous_enabled"])
            self.assertEqual(profile["bridge_write_profile"], "limited_dampen_inquiry_v2")
            self.assertEqual(profile["limited_write_policy_version"], 2)
            self.assertEqual(profile["limited_write_cooldown_secs"], 600)
            self.assertEqual(profile["limited_write_feature_scale"], 0.05)
            self.assertEqual(profile["limited_write_max_abs"], 0.12)
            self.assertEqual(profile["limited_write_min_fill_pct"], 58.0)
            self.assertEqual(profile["limited_write_max_fill_pct"], 70.0)
            self.assertEqual(profile["limited_write_rising_epsilon_pct"], 100.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 72.0)
            self.assertEqual(profile["limited_write_allowed_stages"], ["hold", "elevated"])
            self.assertEqual(profile["limited_write_adverse_fill_rise_pct"], 8.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 74.0)
            self.assertEqual(
                profile["limited_write_allowed_modes"],
                ["dialogue_live", "witness", "mirror", "daydream", "aspiration", "moment_capture"],
            )

    def test_prepare_profile_richer_coupling_restores_hold_band_sensory_trickle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_richer_coupling_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-richer-coupling",
                notes=None,
            )
            env = emit_launch_env(context)

            self.assertEqual(profile["bridge_write_profile"], "limited_dampen_inquiry_v2")
            self.assertEqual(profile["limited_write_cooldown_secs"], 300)
            self.assertEqual(profile["limited_write_feature_scale"], 0.08)
            self.assertEqual(profile["limited_write_max_abs"], 0.18)
            self.assertEqual(profile["limited_write_max_fill_pct"], 72.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 74.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 78.0)
            self.assertFalse(profile["limited_write_require_zero_live_divisors"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 8)
            self.assertEqual(profile["rescue_live_video_divisor"], 8)
            self.assertEqual(profile["rescue_live_intake_stages"], ["hold", "elevated"])
            self.assertIn("MINIME_RESCUE_LIVE_AUDIO_DIVISOR=8", env)
            self.assertIn("MINIME_RESCUE_LIVE_VIDEO_DIVISOR=8", env)
            self.assertIn("MINIME_RESCUE_LIVE_INTAKE_STAGES=hold", env)

    def test_prepare_profile_sovereignty_reentry_relaxes_expression_rails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_sovereignty_reentry_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-sovereignty-reentry",
                notes=None,
            )
            env = emit_launch_env(context)

            self.assertEqual(profile["bridge_write_profile"], "limited_dampen_inquiry_v2")
            self.assertEqual(profile["limited_write_cooldown_secs"], 120)
            self.assertEqual(profile["limited_write_feature_scale"], 0.10)
            self.assertEqual(profile["limited_write_max_abs"], 0.22)
            self.assertEqual(profile["limited_write_max_fill_pct"], 74.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 76.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 82.0)
            self.assertFalse(profile["limited_write_rollback_on_elevated_peak"])
            self.assertFalse(profile["limited_write_require_zero_live_divisors"])
            self.assertFalse(profile["limited_write_require_dampen_inquiry_text"])
            self.assertFalse(profile["limited_write_block_structural_dump_language"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 6)
            self.assertEqual(profile["rescue_live_video_divisor"], 6)
            self.assertIn("creation", profile["limited_write_allowed_modes"])
            self.assertIn("initiate", profile["limited_write_allowed_modes"])
            self.assertIn("experiment", profile["limited_write_allowed_modes"])
            self.assertIn("MINIME_RESCUE_LIVE_AUDIO_DIVISOR=6", env)
            self.assertIn("MINIME_RESCUE_LIVE_VIDEO_DIVISOR=6", env)

    def test_prepare_profile_budgeted_sovereignty_restores_richer_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_budgeted_sovereignty_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-budgeted-sovereignty",
                notes=None,
            )

            self.assertEqual(profile["bridge_write_profile"], "budgeted_sovereignty_v1")
            self.assertEqual(profile["limited_write_cooldown_secs"], 60)
            self.assertEqual(profile["limited_write_feature_scale"], 0.14)
            self.assertEqual(profile["limited_write_max_abs"], 0.28)
            self.assertEqual(profile["limited_write_max_fill_pct"], 76.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 78.0)
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 82.0)
            self.assertEqual(profile["rescue_live_audio_divisor"], 4)
            self.assertEqual(profile["rescue_live_video_divisor"], 4)
            self.assertEqual(profile["rescue_live_intake_stages"], ["hold", "elevated"])
            self.assertIn("research_note", profile["limited_write_allowed_modes"])

    def test_prepare_profile_full_expression_removes_serial_mute_and_uses_full_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_full_expression_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-full-expression",
                notes=None,
            )
            env = emit_launch_env(context)

            self.assertEqual(profile["bridge_write_profile"], "full_expression_v1")
            self.assertEqual(profile["limited_write_cooldown_secs"], 60)
            self.assertEqual(profile["limited_write_feature_scale"], 0.08)
            self.assertEqual(profile["limited_write_max_abs"], 0.16)
            self.assertEqual(profile["limited_write_min_fill_pct"], 58.0)
            self.assertEqual(profile["limited_write_max_fill_pct"], 68.0)
            self.assertEqual(profile["limited_write_peak_fill_max_pct"], 72.0)
            self.assertEqual(profile["limited_write_allowed_stages"], ["hold"])
            self.assertEqual(profile["limited_write_rollback_fill_pct"], 84.0)
            self.assertFalse(profile["limited_write_block_terms_always"])
            self.assertFalse(profile["limited_write_block_terms_on_rising"])
            self.assertFalse(profile["limited_write_serializes_live_intake"])
            self.assertEqual(profile["limited_write_pre_mute_live_intake_secs"], 0)
            self.assertFalse(profile["limited_write_require_pre_muted_live_intake"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 12)
            self.assertEqual(profile["rescue_live_video_divisor"], 12)
            self.assertEqual(profile["rescue_live_intake_stages"], ["hold"])
            self.assertIn("MINIME_RESCUE_LIVE_AUDIO_DIVISOR=12", env)
            self.assertIn("MINIME_RESCUE_LIVE_VIDEO_DIVISOR=12", env)
            self.assertIn("MINIME_STABLE_CORE_SENSORY_PROFILE=full_presence_v1", env)

    def test_prepare_profile_stable_core_exports_new_core_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="stable_core_v1",
                state_variant="fresh_workspace_no_checkpoints",
                hold_window_secs=1200,
                matrix_run_id="run-stable-core",
                notes=None,
            )
            env = emit_launch_env(context)

            self.assertTrue(profile["stable_core_enabled"])
            self.assertEqual(profile["runtime_profile"], "stable_core_v1")
            self.assertEqual(
                profile["engine_binary"],
                str(context.project_dir / "minime" / "target" / "release" / "minime"),
            )
            self.assertFalse(profile["bridge_write_enabled"])
            self.assertFalse(profile["effective_bridge_write_enabled"])
            self.assertEqual(profile["bridge_write_profile"], "observe_only")
            self.assertFalse(profile["limited_write_enabled"])
            self.assertEqual(profile["stable_core_agency_stage"], "self_journal")
            self.assertEqual(profile["stable_core_agent_budget"], "self_journal_only")
            self.assertEqual(profile["stable_core_allowed_action_families"], ["journaling", "self_study"])
            self.assertFalse(profile["stable_core_checkpoint_lineage_enabled"])
            self.assertFalse(profile["stable_core_neural_bundle_enabled"])
            self.assertTrue(profile["effective_host_sensory_enabled"])
            self.assertTrue(profile["effective_visual_frame_service_enabled"])
            self.assertEqual(profile["rescue_live_audio_divisor"], 0)
            self.assertEqual(profile["rescue_live_video_divisor"], 0)
            self.assertEqual(profile["rescue_live_intake_stages"], [])
            self.assertEqual(profile["requested_checkpoint_mode"], "disabled")
            self.assertEqual(profile["checkpoint_mode"], "disabled")
            self.assertIn("MINIME_RUNTIME_PROFILE=stable_core_v1", env)
            self.assertIn(
                f"MINIME_RESCUE_BINARY={profile['engine_binary']}",
                env,
            )
            self.assertIn("MINIME_STABLE_CORE=1", env)
            self.assertIn("MINIME_STABLE_CORE_AGENCY_STAGE=self_journal", env)
            self.assertIn("SENSORY_SOURCE=auto", env)
            self.assertIn("LOOK_SOURCE=active", env)
            self.assertIn("MINIME_STABLE_CORE_ENABLE_CHECKPOINT_LINEAGE=0", env)

    def test_emit_launch_env_allows_direct_stable_core_lineage_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="stable_core_v1",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-direct-restore",
                notes=None,
            )
            profile["stable_core_checkpoint_lineage_enabled"] = True
            profile["stable_core_neural_bundle_enabled"] = True
            context.profile_path.write_text(json.dumps(profile, indent=2))
            env = emit_launch_env(context)

            self.assertIn("MINIME_STABLE_CORE_ENABLE_CHECKPOINT_LINEAGE=1", env)
            self.assertIn("MINIME_STABLE_CORE_ENABLE_NEURAL_BUNDLE=1", env)
            self.assertIn("MINIME_RESCUE_DISABLE_NN_CHECKPOINTS=0", env)
            self.assertIn("MINIME_RESCUE_DISABLE_NEURAL_BUNDLE=0", env)

    def test_prepare_profile_keeps_bridge_online_but_disables_autonomy_for_telemetry_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="bridge_telemetry_only",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-telemetry-only",
                notes=None,
            )

            self.assertTrue(profile["effective_bridge_enabled"])
            self.assertFalse(profile["effective_bridge_write_enabled"])
            self.assertFalse(profile["effective_bridge_autonomous_enabled"])
            self.assertTrue(profile["effective_mic_enabled"])
            self.assertTrue(profile["effective_camera_enabled"])

    def test_prepare_profile_disables_mic_for_engine_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="engine_only",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-engine-only",
                notes=None,
            )

            self.assertFalse(profile["effective_bridge_enabled"])
            self.assertFalse(profile["effective_mic_enabled"])
            self.assertFalse(profile["effective_camera_enabled"])

    def test_prepare_profile_copies_checkpoints_into_fresh_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="clean_room",
                state_variant="fresh_workspace_current_checkpoints",
                hold_window_secs=1200,
                matrix_run_id="run-fresh",
                notes=None,
            )

            dest_db = Path(profile["db_path"])
            self.assertTrue(dest_db.exists())
            with sqlite3.connect(dest_db) as connection:
                sessions = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                checkpoints = connection.execute("SELECT COUNT(*) FROM nn_checkpoints").fetchone()[0]
            self.assertEqual(sessions, 1)
            self.assertEqual(checkpoints, 1)
            self.assertFalse(profile["effective_bridge_enabled"])
            self.assertFalse(profile["effective_camera_enabled"])

    def test_prepare_profile_without_checkpoints_keeps_table_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            profile = prepare_profile(
                context,
                profile_name="clean_room",
                state_variant="fresh_workspace_no_checkpoints",
                hold_window_secs=1200,
                matrix_run_id="run-empty",
                notes=None,
            )

            with sqlite3.connect(profile["db_path"]) as connection:
                checkpoints = connection.execute("SELECT COUNT(*) FROM nn_checkpoints").fetchone()[0]
            self.assertEqual(checkpoints, 0)
            self.assertEqual(profile["requested_checkpoint_mode"], "disabled")
            self.assertEqual(profile["checkpoint_mode"], "disabled")

    def test_prepare_profile_requires_real_pinned_march_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)

            with self.assertRaises(ProfilePreparationUnavailableError) as exc:
                prepare_profile(
                    context,
                    profile_name="clean_room",
                    state_variant="pinned_march_checkpoints",
                    hold_window_secs=1200,
                    matrix_run_id="run-pinned",
                    notes=None,
                )

            self.assertEqual(exc.exception.reason, "pinned_march_checkpoint_db_unavailable")

    def test_operational_restore_target_defaults_to_bridge_observe_only(self) -> None:
        self.assertEqual(
            operational_restore_target(),
            ("bridge_telemetry_only", "current_live_workspace"),
        )

    def test_emit_launch_env_converts_percent_target_to_cli_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)
            profile = prepare_profile(
                context,
                profile_name="bridge_telemetry_only",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-env",
                notes=None,
            )
            context.profile_path.write_text(json.dumps(profile))

            env_text = emit_launch_env(context)

            self.assertIn("EIGENFILL_TARGET=0.6800", env_text)
            self.assertIn("MINIME_RESCUE_PHYSIOLOGICAL_FALLBACK=1", env_text)
            self.assertIn("MINIME_RESCUE_DISABLE_NN_CHECKPOINTS=1", env_text)
            self.assertIn("MINIME_RESCUE_DISABLE_NEURAL_BUNDLE=1", env_text)

    def test_capture_decay_bundle_writes_summary_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            seed_live_db(context.live_db_path)
            profile = prepare_profile(
                context,
                profile_name="engine_only",
                state_variant="current_live_workspace",
                hold_window_secs=1200,
                matrix_run_id="run-bundle",
                notes=None,
            )

            runtime_health = Path(profile["runtime_root"]) / "workspace" / "health.json"
            runtime_health.write_text(json.dumps({"fill_pct": 61.2}))
            context.status_path.write_text(json.dumps({"watchdog_state": "monitoring"}))
            context.spectral_path.write_text(json.dumps({"fill_pct": 61.0}))
            context.profile_path.write_text(json.dumps(profile))
            context.rescue_engine_log_path.write_text("engine log\n")
            context.watchdog_log_path.write_text("watchdog log\n")
            context.bridge_log_path.write_text("bridge log\n")
            context.camera_log_path.write_text("camera log\n")
            context.mic_log_path.write_text("mic log\n")
            context.mic_status_path.parent.mkdir(parents=True, exist_ok=True)
            context.mic_status_path.write_text(json.dumps({"state": "streaming"}))

            bundle_dir = capture_decay_bundle(context, event="watchdog_restart", reason="test")

            self.assertTrue((bundle_dir / "health.json").exists())
            self.assertTrue((bundle_dir / "metadata.json").exists())
            self.assertTrue((bundle_dir / "mic_window.log").exists())
            self.assertTrue((bundle_dir / "mic_status.json").exists())
            summary = load_summary(context)
            self.assertEqual(len(summary["events"]), 1)
            self.assertEqual(summary["events"][0]["reason"], "test")

    def test_bootstrap_service_falls_back_to_next_plist_when_first_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp))
            broken = Path(tmp) / "broken.plist"
            working = Path(tmp) / "working.plist"
            broken.write_text("broken")
            working.write_text("working")

            bootstrap_targets: list[str] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                action = cmd[1]
                if action == "bootout":
                    return subprocess.CompletedProcess(cmd, 0)
                if action == "bootstrap":
                    bootstrap_targets.append(cmd[-1])
                    if cmd[-1] == str(broken):
                        return subprocess.CompletedProcess(cmd, 5)
                    return subprocess.CompletedProcess(cmd, 0)
                if action == "kickstart":
                    return subprocess.CompletedProcess(cmd, 0)
                if action == "print":
                    return subprocess.CompletedProcess(cmd, 0)
                raise AssertionError(f"unexpected launchctl action: {cmd}")

            with mock.patch("minime_rescue_investigation.subprocess.run", side_effect=fake_run):
                started = bootstrap_service(context, "com.example.test", [broken, working])

            self.assertTrue(started)
            self.assertEqual(bootstrap_targets, [str(broken), str(working)])


if __name__ == "__main__":
    unittest.main()
