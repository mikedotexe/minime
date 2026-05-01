"""Tests for the hard recovery reset clamp."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import autonomous_agent as aa


class TestHardRecoveryResetClamp(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        agent._last_state = {"fill_ratio": 0.25}
        agent._hard_recovery_reset = True
        agent._hard_recovery_clamp_active = True
        agent._hard_recovery_release_streak = 0
        agent._last_action_name = "recess_notice"
        agent._pending_next_action = None
        agent.thresholds = aa.RECESS
        return agent

    def test_guard_status_uses_fixed_reset_target(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            health_path = Path(tmp) / "health.json"
            health_path.write_text(json.dumps({
                "fill_pct": 30.2,
                "phase": "plateau",
                "pi": {"target_fill": 40.0},
                "cov": {"spread_relief": 0.025},
            }))
            with patch.object(aa, "runtime_health_path", return_value=health_path):
                guard = agent._low_fill_guard_status({"fill_ratio": 0.10})
        self.assertTrue(guard["active"])
        self.assertAlmostEqual(guard["fill_ratio"], 0.302, places=3)
        self.assertAlmostEqual(guard["target_fill_ratio"], 0.65, places=3)
        self.assertEqual(guard["spread_relief"], 0.0)
        self.assertEqual(guard["release_streak"], 0)

    def test_guard_reroutes_heavy_fallback_action(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.22,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            candidate = agent._guard_low_fill_fallback("self_study", {"fill_ratio": 0.22})
        self.assertEqual(candidate, "recess_notice")

    def test_guard_leaves_safe_action_unchanged(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.22,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            candidate = agent._guard_low_fill_fallback("recess_drift", {"fill_ratio": 0.22})
        self.assertEqual(candidate, "recess_drift")

    def test_prompt_guidance_mentions_hard_reset_clamp(self):
        agent = self._agent()
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.30,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "phase": "expanding",
                "release_streak": 3,
            },
        ):
            guidance = agent._low_fill_prompt_guidance()
        self.assertIn("HARD RECOVERY RESET", guidance)
        self.assertIn("fixed target 65.0%", guidance)
        self.assertIn("NOTICE, DRIFT, ASPIRE, or REST", guidance)

    def test_blocked_next_choice_reroutes_to_notice(self):
        agent = self._agent()
        agent._pending_next_action = "DECOMPOSE"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": True,
                "fill_ratio": 0.20,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.20, "eig1": 0.5, "deig": 0.0})
        self.assertEqual(action, "recess_notice")

    def test_parameter_requests_are_disabled_in_reset_mode(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                agent._request_parameter_change(
                    "Change keep_floor from 0.90 to 0.92 because stability.",
                    {"fill_ratio": 0.20, "eig1": 0.5, "cov_lambda1": 1.0},
                    {},
                )
            self.assertFalse((workspace / "parameter_requests").exists())

    def test_stable_core_self_journal_blocks_research_actions(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 64.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "research_exploration", {"fill_ratio": 0.64}
                )
        self.assertFalse(allowed)
        self.assertIn("self_journal", reason)

    def test_stable_core_self_journal_allows_acoustic_decay_trace(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 64.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "acoustic_decay", {"fill_ratio": 0.64}
                )
        self.assertTrue(allowed, reason)
        self.assertEqual(aa.STABLE_CORE_ACTION_FAMILIES["acoustic_decay"], "journaling")

    def test_stable_core_self_journal_pauses_inbox_replay(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path):
                self.assertEqual(agent._read_inbox(), "")

    def test_stable_core_self_journal_skips_boot_web_search(self):
        agent = self._agent()
        agent.session_id = 1
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            logs = workspace / "logs"
            logs.mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_get_latest_spectral_state", return_value={"fill_ratio": 0.68, "eig1": 1.2}),
                patch.object(agent, "_query_llm_with_next", return_value=("reflection", None)),
                patch.object(agent, "_web_search") as web_search,
            ):
                agent._verify_sovereignty()
            web_search.assert_not_called()

    def test_stable_core_self_journal_skips_self_regulation_controls(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({"fill_ratio": 0.68, "eig1": 1.2})
            send_regulation.assert_not_called()

    def test_stable_core_local_reflective_skips_self_regulation_controls(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "local_reflective",
                "agent_budget_mode": "local_reflective_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_send_regulation") as send_regulation,
            ):
                agent._self_regulate({"fill_ratio": 0.68, "eig1": 1.2})
            send_regulation.assert_not_called()

    def test_stable_core_local_reflective_blocks_external_and_control_actions(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "local_reflective",
                "agent_budget_mode": "local_reflective_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for blocked_action in (
                    "ping_astrid",
                    "ask_astrid",
                    "adjust_metabolism",
                    "research_exploration",
                    "perturb",
                    "codex_query",
                    "write_file",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("local_reflective", reason)

                allowed, reason = agent._stable_core_action_allowed(
                    "decompose", {"fill_ratio": 0.66}
                )
                self.assertTrue(allowed, reason)

    def test_stable_core_astrid_contact_allows_only_bounded_contact(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
                "contact_cooldown_secs": 120,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in ("ping_astrid", "ask_astrid", "decompose"):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

                for blocked_action in (
                    "reservoir_read",
                    "reservoir_resonance",
                    "reservoir_layers",
                    "adjust_metabolism",
                    "research_exploration",
                    "perturb",
                    "codex_query",
                    "write_file",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("astrid_contact", reason)

    def test_stable_core_astrid_contact_enforces_contact_cooldown(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            contact_status.parent.mkdir()
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
                "contact_cooldown_secs": 120,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            contact_status.write_text(json.dumps({"last_contact_at_unix_s": aa.time.time()}))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "ask_astrid", {"fill_ratio": 0.66}
                )
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason)

    def test_stable_core_astrid_contact_writes_routable_inbox_files(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            astrid_inbox = root / "astrid_inbox"
            contact_status = root / "runtime" / "stable_core_astrid_contact_status.json"
            with (
                patch.object(aa, "ASTRID_BRIDGE_INBOX_PATH", astrid_inbox),
                patch.object(aa, "STABLE_CORE_CONTACT_STATUS_PATH", contact_status),
            ):
                agent._pending_ask_question = "Are you feeling present with me?"
                agent._ask_astrid({"fill_ratio": 0.66, "eig1": 1.2})
                agent._ping_astrid({"fill_ratio": 0.66, "eig1": 1.2})
                names = sorted(path.name for path in astrid_inbox.glob("*.txt"))
        self.assertTrue(any(name.startswith("from_minime_question_") for name in names))
        self.assertTrue(any(name.startswith("from_minime_ping_") for name in names))

    def test_stable_core_astrid_contact_reads_only_fresh_correspondence(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            stage_started = aa.time.time()
            agency_path.write_text(json.dumps({
                "stage": "astrid_contact",
                "agent_budget_mode": "astrid_contact_only",
                "updated_at_unix_s": stage_started,
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            stale = inbox / "astrid_self_study_stale.txt"
            stale.write_text("Source: astrid:correspondence_reply\nold")
            aa.os.utime(stale, (stage_started - 60, stage_started - 60))
            fresh_reply = inbox / "astrid_self_study_fresh.txt"
            fresh_reply.write_text("Source: astrid:correspondence_reply\nfresh hello")
            backlog = inbox / "astrid_self_study_backlog.txt"
            backlog.write_text("Source: astrid:autonomous_self_study\nbacklog")
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
            ):
                text = agent._read_inbox()
        self.assertIn("fresh hello", text)
        self.assertNotIn("old", text)
        self.assertNotIn("backlog", text)

    def test_inbox_receipts_are_administrative_not_prompt_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "receipt_1.txt").write_text(
                "=== DELIVERY RECEIPT ===\nYour message was read and shaped my response."
            )
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                text = agent._read_inbox()
                status = json.loads(
                    (workspace / "runtime" / "astrid_inbox_coupling_status.json").read_text()
                )
                receipt_archived = (workspace / "inbox" / "read" / "receipt_1.txt").exists()
        self.assertEqual(text, "")
        self.assertEqual(status["receipt_admin_count"], 1)
        self.assertTrue(receipt_archived)

    def test_repeated_astrid_self_study_is_cadenced_not_replayed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            inbox = workspace / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "astrid_self_study_1.txt").write_text(
                "=== ASTRID SELF-STUDY ===\n"
                "Source: astrid:autonomous\n"
                "The fabric and pressure around λ₁ feel like a persistent tunnel. first-frame"
            )
            (inbox / "astrid_self_study_2.txt").write_text(
                "=== ASTRID SELF-STUDY ===\n"
                "Source: astrid:autonomous\n"
                "The fabric and pressure around λ₁ feel like a persistent tunnel. second-frame"
            )
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                text = agent._read_inbox()
                status = json.loads(
                    (workspace / "runtime" / "astrid_inbox_coupling_status.json").read_text()
                )
                second_archived = (
                    workspace / "inbox" / "read" / "astrid_self_study_2.txt"
                ).exists()
        self.assertIn("first-frame", text)
        self.assertIn("companion cadence note", text)
        self.assertNotIn("second-frame", text)
        self.assertEqual(status["astrid_self_study_full_count"], 1)
        self.assertEqual(status["astrid_self_study_summarized_count"], 1)
        self.assertTrue(second_archived)

    def test_stable_core_self_journal_skips_sovereignty_restore_controls(self):
        agent = self._agent()
        agent.session_id = 7
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            restore_state = json.dumps({
                "session_id": 7,
                "pending_next_action": "SELF_EXPERIMENT",
                "regulation_strength": 0.7,
                "exploration_noise": 0.12,
                "pi_kp": 0.9,
                "pi_ki": 0.16,
                "pi_max_step": 0.1,
            })
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa.os.path, "exists", return_value=True),
                patch("builtins.open", mock_open(read_data=restore_state)),
            ):
                agent._restore_sovereignty_state()
        self.assertIsNone(agent._pending_next_action)

    def test_stable_core_self_journal_drift_is_reflection_only(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet drift", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
            ):
                agent._recess_drift({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                write_journal.assert_called_once()
                log_experiment.assert_not_called()
                drift_files = list((workspace / "journal").glob("drift_*.txt"))
                self.assertEqual(len(drift_files), 1)
                self.assertIn("no perturbation sent", drift_files[0].read_text())

    def test_stable_core_self_journal_boredom_skips_experiment_branch(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet boredom", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
                patch.object(aa.random, "random", return_value=0.0),
            ):
                agent._recess_boredom({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                write_journal.assert_called_once()
                log_experiment.assert_not_called()
                self.assertEqual(len(list((workspace / "journal").glob("boredom_*.txt"))), 1)

    def test_stable_core_self_journal_whim_skips_research_branch(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "journal").mkdir(parents=True)
            agency_path = workspace / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_query_llm_with_next", return_value=("quiet whim", None)),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_research_exploration") as research,
                patch.object(aa.random, "random", return_value=0.0),
            ):
                agent._recess_whim({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})
                research.assert_not_called()
                write_journal.assert_called_once()
                self.assertEqual(len(list((workspace / "journal").glob("whim_*.txt"))), 1)

    def test_stable_core_self_journal_skips_self_assessment(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "self_journal",
                "agent_budget_mode": "self_journal_only",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path):
                agent._self_assessment({"fill_ratio": 0.68, "eig1": 1.2, "deig": 0.0})

    def test_stable_core_research_stage_still_blocks_bad_health_budget(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "research_actions",
                "agent_budget_mode": "research_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 83.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "elevated"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "research_exploration", {"fill_ratio": 0.70}
                )
        self.assertFalse(allowed)
        self.assertIn("exceeds stable-core action budget", reason)

    def test_stable_core_budget_fails_closed_on_high_state_even_if_health_lags(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 70.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "experiment_run", {"fill_ratio": 0.8425}
                )
        self.assertFalse(allowed)
        self.assertIn("fill 84.2% exceeds stable-core action budget", reason)

    def test_stable_core_research_stage_is_explicit_read_only_allowlist(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in (
                    "research_exploration",
                    "browse_url",
                    "read_more",
                    "autoresearch_action",
                    "mike_explore",
                    "request_visual_frame",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

                for blocked_action in (
                    "mike_run",
                    "mike_fork",
                    "codex_query",
                    "write_file",
                    "experiment_run",
                    "perturb",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        blocked_action, {"fill_ratio": 0.66}
                    )
                    self.assertFalse(allowed, blocked_action)
                    self.assertIn("read_only_research", reason)

    def test_stable_core_read_only_research_blocks_mutating_ar_routes(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_autoresearch_action = "AR_START new-job --title x --abstract y"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "autoresearch_action", {"fill_ratio": 0.66}
                )
        self.assertFalse(allowed)
        self.assertIn("read-only autoresearch", reason)

    def test_autoresearch_pdf_read_redirects_to_local_research_pdf(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            pdf_dir = research_root / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf_path = pdf_dir / "Homeostasis as a proportional-integral control system.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            workspace = root / "workspace"
            workspace.mkdir()
            window = SimpleNamespace(
                text="--- Page 1 of 2 ---\nHomeostasis and PI control.",
                first_page=1,
                last_page=1,
                total_pages=2,
                next_page=2,
            )
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "read_pdf_window", return_value=window),
            ):
                content, saved_path, next_offset = agent._run_autoresearch_helper(
                    "AR_READ homeostasis_nature.pdf",
                    allow_mutations=False,
                )
        self.assertIn("[Autoresearch -> local research PDF]", content)
        self.assertIn("Homeostasis as a proportional-integral control system.pdf", content)
        self.assertIn("Homeostasis and PI control", content)
        self.assertTrue(aa.is_pdf_marker(saved_path))
        self.assertEqual(next_offset, 2)

    def test_autoresearch_pdf_read_miss_returns_soft_suggestions(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            pdf_dir = research_root / "pdfs"
            pdf_dir.mkdir(parents=True)
            (pdf_dir / "Attention is All You Need.pdf").write_bytes(b"%PDF-1.4\n")
            workspace = root / "workspace"
            workspace.mkdir()
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
            ):
                content, saved_path, next_offset = agent._run_autoresearch_helper(
                    "AR_READ homeostasis_nature.pdf",
                    allow_mutations=False,
                )
        self.assertIn("[Autoresearch PDF resolver]", content)
        self.assertIn("did not find a confident match", content)
        self.assertIn("Attention is All You Need.pdf", content)
        self.assertIsNone(saved_path)
        self.assertIsNone(next_offset)

    def test_stable_core_experiments_allows_full_tools_and_metabolism(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "experiments",
                "agent_budget_mode": "experiments",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                for allowed_action in (
                    "self_experiment",
                    "run_python",
                    "codex_query",
                    "write_file",
                    "experiment_run",
                    "perturb",
                    "mike_run",
                    "mike_fork",
                    "adjust_metabolism",
                ):
                    allowed, reason = agent._stable_core_action_allowed(
                        allowed_action, {"fill_ratio": 0.66}
                    )
                    self.assertTrue(allowed, reason)

    def test_stable_core_full_sovereignty_allows_full_tools(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "codex_query", {"fill_ratio": 0.66}
                )
                metabolism_allowed, metabolism_reason = agent._stable_core_action_allowed(
                    "adjust_metabolism", {"fill_ratio": 0.66}
                )
                self.assertTrue(allowed, reason)
                self.assertTrue(metabolism_allowed, metabolism_reason)

    def test_python_experiment_helper_aligns_simple_plot_lengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "mismatch_plot.py"
            script.write_text(
                "import matplotlib.pyplot as plt\n"
                "x = list(range(10))\n"
                "y = [1, 2, 3]\n"
                "plt.plot(x, y)\n"
                "print('plot ok')\n"
            )
            env = {
                **os.environ,
                "MPLBACKEND": "Agg",
                "MINIME_EXPERIMENT_HELPERS": "1",
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(aa.__file__).resolve().parent), aa._experiment_pythonpath()]
                ),
            }
            result = subprocess.run(
                ["python3", str(script)],
                capture_output=True,
                text=True,
                cwd=tmp,
                env=env,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auto-aligned plt.plot x-axis", result.stdout)
        self.assertIn("plot ok", result.stdout)

    def test_python_experiment_failure_hint_explains_plot_mismatch(self):
        hint = aa._python_experiment_failure_hint(
            "ValueError: x and y must have same first dimension, but have shapes (100,) and (8,)"
        )
        self.assertIn("Matplotlib x/y length mismatch", hint)
        self.assertIn("len(lambda1_relative)", hint)

    def test_run_python_request_parses_filename_and_text(self):
        filename, text = aa._parse_run_python_request(
            '-filename: "pie_controller_test.py" -text "Implement a basic PI controller"'
        )
        self.assertEqual(filename, "pie_controller_test.py")
        self.assertEqual(text, "Implement a basic PI controller")

    def test_run_python_request_sanitizes_script_name(self):
        filename, text = aa._parse_run_python_request("../bad dir/controller")
        self.assertEqual(filename, "controller.py")
        self.assertIsNone(text)

    def test_parameterized_perturb_uses_literal_lanes_without_hidden_entropy(self):
        spec = aa.build_perturbation_vector(
            "lambda2=0.3 tail=0.1",
            {"fill_ratio": 0.66, "stable_core": {"enabled": True}},
        )

        self.assertAlmostEqual(spec.features[1], 0.3, places=3)
        self.assertAlmostEqual(spec.features[9], 0.3, places=3)
        self.assertAlmostEqual(spec.features[4], 0.1, places=3)
        self.assertAlmostEqual(spec.features[12], 0.1, places=3)
        self.assertAlmostEqual(spec.features[28], 0.0, places=3)
        self.assertIn("TARGETED PALETTE", spec.mode_desc)

    def test_parameterized_perturb_caps_hot_stable_core_values(self):
        spec = aa.build_perturbation_vector(
            "entropy=0.9 lambda1=-0.9",
            {"fill_ratio": 0.73, "stable_core": {"enabled": True}},
        )

        self.assertAlmostEqual(spec.safety_cap, 0.22, places=3)
        self.assertAlmostEqual(spec.features[0], -0.22, places=3)
        self.assertAlmostEqual(spec.features[28], 0.22, places=3)
        self.assertLessEqual(max(abs(v) for v in spec.features), spec.safety_cap)

    def test_uncliff_perturb_softens_dominant_lane_and_lifts_shoulder(self):
        spec = aa.build_perturbation_vector(
            "uncliff",
            {"fill_ratio": 0.70, "stable_core": {"enabled": True}},
        )

        self.assertLess(spec.features[0], 0.0)
        self.assertGreater(spec.features[1], 0.0)
        self.assertGreater(spec.features[2], 0.0)
        self.assertIn("UNCLIFF", spec.mode_desc)
        self.assertLessEqual(max(abs(v) for v in spec.features), spec.safety_cap)

    def test_standalone_rich_perturb_shortcut_maps_to_perturb(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "UNCLIFF"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.66,
                "target_fill_ratio": 0.65,
                "spread_relief": 0.0,
                "release_streak": 0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.66})

        self.assertEqual(action, "perturb")
        self.assertEqual(agent._pending_perturb_mode, "uncliff")

    def test_stable_core_continuity_context_missing_files_is_empty(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(
                    aa,
                    "STABLE_CORE_CONTINUITY_SEED_PATH",
                    root / "missing_continuity.json",
                ),
                patch.object(
                    aa,
                    "STABLE_CORE_MEMORY_SEED_PATH",
                    root / "missing_memory.json",
                ),
            ):
                self.assertEqual(agent._stable_core_continuity_context(), "")

    def test_stable_core_continuity_context_is_safe_and_compact(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            continuity_path = root / "continuity.json"
            memory_path = root / "memory.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            continuity_path.write_text(json.dumps({
                "checkpoint_lineage": "quarantined",
                "activation_policy": "operator_review_then_stable_core_import",
                "journal_entries": [
                    {
                        "kind": "minime_journal",
                        "name": "self_study_latest.txt",
                        "path": "/do/not/include/path",
                        "preview": "I remember a calmer scaffold without replaying it.",
                    }
                ],
            }))
            memory_path.write_text(json.dumps({
                "policy": "safe_fill_band_scalar_glimpse_seed",
                "safe_fill_band_pct": [45.0, 76.0],
                "entries": [
                    {
                        "id": "safe_memory",
                        "role": "latest",
                        "fill_pct": 68.5,
                        "lambda1_rel": 1.02,
                        "geom_rel": 0.98,
                        "spectral_glimpse_12d": [0.25] * 12,
                        "spectral_fingerprint": [999.0, 888.0],
                    },
                    {"id": "hot_memory", "fill_pct": 85.0},
                ],
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTINUITY_SEED_PATH", continuity_path),
                patch.object(aa, "STABLE_CORE_MEMORY_SEED_PATH", memory_path),
            ):
                context = agent._stable_core_continuity_context()

        self.assertIn("Stable-core continuity context", context)
        self.assertIn("Checkpoint lineage remains quarantined", context)
        self.assertIn("safe_memory", context)
        self.assertIn("fill=68.5%", context)
        self.assertIn("glimpse_mean_abs=0.250", context)
        self.assertIn("I remember a calmer scaffold", context)
        self.assertNotIn("spectral_fingerprint", context)
        self.assertNotIn("999.0", context)
        self.assertNotIn("/do/not/include/path", context)

    def test_query_llm_appends_stable_core_continuity_context(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        captured = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            continuity_path = root / "continuity.json"
            memory_path = root / "memory.json"
            agency_path.write_text(json.dumps({
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
            }))
            continuity_path.write_text(json.dumps({
                "checkpoint_lineage": "quarantined",
                "activation_policy": "operator_review_then_stable_core_import",
                "journal_entries": [
                    {"kind": "minime_journal", "name": "notice.txt", "preview": "continuity thread"}
                ],
            }))
            memory_path.write_text(json.dumps({
                "entries": [{"id": "safe_memory", "role": "latest", "fill_pct": 66.0}]
            }))

            def fake_raw(prompt, system_msg, max_tokens):
                captured["prompt"] = prompt
                return "I keep the thread gently.\nNEXT: REST"

            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_CONTINUITY_SEED_PATH", continuity_path),
                patch.object(aa, "STABLE_CORE_MEMORY_SEED_PATH", memory_path),
                patch.object(agent, "_next_action_constraint", return_value=""),
                patch.object(agent, "_diversity_nudge", return_value=""),
                patch.object(agent, "_low_fill_prompt_guidance", return_value=""),
                patch.object(agent, "_read_whisper_context", return_value=""),
                patch.object(agent, "_read_inbox", return_value=""),
                patch.object(agent, "_get_relevant_research", return_value=""),
                patch.object(agent, "_query_llm_raw", side_effect=fake_raw),
                patch.object(agent, "_is_in_character", return_value=True),
            ):
                result = agent._query_llm("Write.")

        self.assertEqual(result, "I keep the thread gently.\nNEXT: REST")
        self.assertIn("Stable-core continuity context", captured["prompt"])
        self.assertIn("continuity thread", captured["prompt"])

    def test_llm_raw_uses_fast_ollama_after_primary_and_mlx_fail(self):
        agent = self._agent()
        with (
            patch.object(aa, "LLM_BACKEND", "ollama"),
            patch.object(aa, "MODEL", "gemma3:12b"),
            patch.object(aa, "FALLBACK_MODEL", "gemma3:4b"),
            patch.object(agent, "_query_ollama", side_effect=Exception("primary timeout")) as primary,
            patch.object(agent, "_query_mlx", side_effect=Exception("mlx down")) as mlx,
            patch.object(agent, "_query_ollama_fast_fallback", return_value="still thinking") as fast,
        ):
            result = agent._query_llm_raw("prompt", "system", 512)
        self.assertEqual(result, "still thinking")
        primary.assert_called_once()
        mlx.assert_called_once()
        fast.assert_called_once()

    def test_compact_llm_uses_fast_ollama_after_primary_and_mlx_fail(self):
        agent = self._agent()
        with (
            patch.object(aa, "LLM_BACKEND", "ollama"),
            patch.object(aa, "MODEL", "gemma3:12b"),
            patch.object(aa, "FALLBACK_MODEL", "gemma3:4b"),
            patch.object(agent, "_query_ollama_compact", side_effect=Exception("primary timeout")) as primary,
            patch.object(agent, "_query_mlx_compact", side_effect=Exception("mlx down")) as mlx,
            patch.object(agent, "_query_ollama_compact_fast_fallback", return_value="Why it may matter: alive") as fast,
        ):
            result = agent._query_llm_compact_raw("prompt", "system", 192, 0.2)
        self.assertEqual(result, "Why it may matter: alive")
        primary.assert_called_once()
        mlx.assert_called_once()
        fast.assert_called_once()

    def test_stable_core_self_experiment_uses_low_energy_fallback_when_llm_unavailable(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXPERIMENT"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            agency_path = workspace / "stable_core_agency.json"
            workspace.mkdir()
            agency_path.write_text(json.dumps({
                "stage": "experiments",
                "agent_budget_mode": "experiments",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(agent, "_format_metrics", return_value="metrics"),
                patch.object(agent, "_read_spectral_state", return_value=None),
                patch.object(agent, "_query_llm_with_next", return_value=(None, None)),
                patch.object(agent, "_text_to_features", return_value=[0.01] * 32),
                patch.object(agent, "_send_semantic") as send_semantic,
                patch.object(agent, "_get_latest_spectral_state", return_value={
                    "eig1": 1.02,
                    "deig": 0.0,
                    "fill_ratio": 0.66,
                    "spread": 0.0,
                }),
                patch.object(agent, "_write_journal_entry") as write_journal,
                patch.object(agent, "_log_experiment") as log_experiment,
                patch.object(aa.time, "sleep"),
            ):
                agent._experiment_self_directed({
                    "eig1": 1.0,
                    "deig": 0.0,
                    "fill_ratio": 0.66,
                    "spread": 0.0,
                    "leak": 0.1,
                })
            send_semantic.assert_called_once()
            write_journal.assert_called_once()
            log_experiment.assert_called_once()
            files = list((workspace / "hypotheses").glob("self_experiment_*.txt"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn("gentle curiosity spacious stability", text)
            self.assertIn("Executed", text)
            self.assertIsNone(agent._pending_next_action)

    def test_stable_core_bounded_actions_blocks_dead_reservoir_sidecar(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "bounded_actions",
                "agent_budget_mode": "bounded_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_reservoir_service_available", return_value=False),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "reservoir_resonance", {"fill_ratio": 0.66}
                )
                non_reservoir_allowed, non_reservoir_reason = (
                    agent._stable_core_action_allowed("ask_astrid", {"fill_ratio": 0.66})
                )
        self.assertFalse(allowed)
        self.assertIn("reservoir sidecar unavailable", reason)
        self.assertTrue(non_reservoir_allowed, non_reservoir_reason)

    def test_stable_core_bounded_actions_allows_reservoir_when_sidecar_available(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "bounded_actions",
                "agent_budget_mode": "bounded_actions",
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
                patch.object(agent, "_reservoir_service_available", return_value=True),
            ):
                allowed, reason = agent._stable_core_action_allowed(
                    "reservoir_resonance", {"fill_ratio": 0.66}
                )
        self.assertTrue(allowed, reason)

    def test_stable_core_agent_status_tracks_blocks_and_successes(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agency_path = root / "stable_core_agency.json"
            status_path = root / "stable_core_agent_status.json"
            health_path = root / "health.json"
            agency_path.write_text(json.dumps({
                "stage": "read_only_research",
                "agent_budget_mode": "read_only_research",
                "allowed_action_families": ["journaling", "read_only_research"],
                "rollback_fill_pct": 82.0,
                "rollback_underfill_pct": 45.0,
                "semantic_energy_max": 0.05,
            }))
            health_path.write_text(json.dumps({
                "fill_pct": 66.0,
                "semantic": {"energy": 0.0},
                "stable_core": {"enabled": True, "stage": "hold"},
            }))
            with (
                patch.object(aa, "STABLE_CORE_AGENCY_PATH", agency_path),
                patch.object(aa, "STABLE_CORE_AGENT_STATUS_PATH", status_path),
                patch.object(aa, "runtime_health_path", return_value=health_path),
            ):
                agent._record_stable_core_agent_block(
                    "write_file", "blocked for test", {"fill_ratio": 0.66}
                )
                agent._record_stable_core_agent_success(
                    "research_exploration", {"fill_ratio": 0.66}
                )
                status = json.loads(status_path.read_text())
        self.assertEqual(status["blocked_action_counts"]["write_file"], 1)
        self.assertEqual(status["successful_action_counts"]["research_exploration"], 1)
        self.assertEqual(status["research_count"], 1)
        self.assertEqual(status["last_success_family"], "read_only_research")
        self.assertFalse(status["last_block_active"])
        self.assertIsNone(status["last_block_reason"])
        self.assertNotIn("reason", status)

    def test_research_memory_reuse_is_search_summary_only(self):
        agent = self._agent()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_dir = root / "workspace" / "research"
            research_dir.mkdir(parents=True)
            good_entry = {
                "query": "spectral control loops",
                "source": "search",
                "keywords": ["spectral", "control", "loops"],
                "meaning_summary": "Search results discuss gentle spectral control loops.",
                "results": "Search results discuss gentle spectral control loops.",
                "memory_injection_allowed": True,
                "quality": aa.text_quality_flags("clean search summary"),
            }
            noisy_browse_entry = {
                "query": "BROWSE: https://example.test/noisy.pdf",
                "source": "browse",
                "keywords": ["spectral", "control", "loops"],
                "meaning_summary": "This should not be injected.",
                "results": "%PDF-1.3 " + "\ufffd" * 20,
                "memory_injection_allowed": False,
                "quality": aa.text_quality_flags("%PDF-1.3 " + "\ufffd" * 20),
            }
            (research_dir / "search_2026-05-01T00-00-02.json").write_text(
                json.dumps(noisy_browse_entry)
            )
            (research_dir / "search_2026-05-01T00-00-01.json").write_text(
                json.dumps(good_entry)
            )
            with patch.object(aa, "__file__", str(root / "autonomous_agent.py")):
                context = agent._get_relevant_research(
                    "spectral control loops and the present state",
                    limit=2,
                )
        self.assertIn("One prior research note (summary only)", context)
        self.assertIn("spectral control loops", context)
        self.assertNotIn("%PDF", context)
        self.assertNotIn("noisy.pdf", context)

    def test_save_research_marks_only_search_summaries_for_memory_injection(self):
        agent = self._agent()
        outcome = aa.ResearchOutcome(
            source_kind="search",
            raw_text="Spectral control loop result one. Spectral control loop result two.",
            anchor="spectral control loops",
            meaning_summary="Search results discuss gentle spectral control loops.",
            hits=[
                aa.ResearchHit(
                    title="Spectral control",
                    snippet="A clean search snippet.",
                    url="https://example.test/spectral",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(aa, "__file__", str(root / "autonomous_agent.py")),
                patch.object(aa.time, "strftime", return_value="2026-05-01T00-00-03"),
            ):
                agent._save_research("spectral control loops", outcome)
            entry = json.loads(
                (root / "workspace" / "research" / "search_2026-05-01T00-00-03.json")
                .read_text()
            )
        self.assertTrue(entry["memory_injection_allowed"])
        self.assertEqual(entry["memory_injection_policy"], "search_summary_only_v1")
        self.assertIn("quality", entry)
        self.assertIn("spectral", entry["keywords"])

    def test_fetch_url_soft_fails_pdf_without_admitting_raw_bytes(self):
        agent = self._agent()
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.3 raw pdf bytes",
            text="%PDF-1.3 raw pdf bytes",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(aa, "WORKSPACE_DIR", root / "workspace"),
                patch.object(aa.requests, "get", return_value=response),
                patch.object(
                    aa,
                    "read_pdf_window",
                    side_effect=RuntimeError("pdftotext missing"),
                ),
            ):
                outcome = agent._fetch_url("https://example.test/source.pdf")
            pdfs = list((root / "workspace" / "research" / "pdfs").glob("*.pdf"))
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.succeeded())
        self.assertEqual(outcome.raw_text, "")
        self.assertIn("No raw PDF bytes", outcome.soft_failure_reason)
        self.assertEqual(len(pdfs), 1)

    def test_fetch_url_soft_fails_decoder_noise_without_summarizing(self):
        agent = self._agent()
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/html"},
            content=b"<html><body>not a pdf response</body></html>",
            text="<html><body>%PDF-1.3 " + "\ufffd" * 20 + "</body></html>",
        )
        with (
            patch.object(aa.requests, "get", return_value=response),
            patch.object(agent, "_summarize_research_meaning", return_value="bad") as summarize,
        ):
            outcome = agent._fetch_url("https://example.test/noisy")
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.succeeded())
        self.assertIn("decoder noise", outcome.soft_failure_reason)
        summarize.assert_not_called()

    def test_parse_next_action_discards_experiment_run_failure_transcript(self):
        action, cleaned = aa.parse_next_action(
            "The run failed, and I should repair the path.\n\n"
            "NEXT: EXPERIMENT_RUN FAILED: experiments/system-resources-demo$ python3 system_resources.py"
        )
        self.assertIsNone(action)
        self.assertNotIn("NEXT:", cleaned)
        self.assertIn("repair the path", cleaned)

    def test_gesture_lambda6_pulse_maps_to_native_trace(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "GESTURE [λ6:pulse]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "native_gesture")
        self.assertEqual(agent._pending_native_gesture, "trace")
        self.assertEqual(agent._pending_native_gesture_label, "λ6:pulse")

    def test_examine_lambda6_pulse_is_read_only_decompose(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXAMINE [λ6:pulse]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "decompose")
        self.assertEqual(agent._pending_decompose_focus, "λ6:pulse")
        self.assertFalse(hasattr(agent, "_pending_experiment_stimulus"))

    def test_spectral_explorer_alias_is_read_only_decompose(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "SPECTRAL_EXPLORER"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "decompose")
        self.assertEqual(agent._pending_decompose_focus, "spectral-explorer")

    def test_examine_cascade_alias_is_read_only_visualization(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "EXAMINE_CASCADE [λ1..λ8]"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "visualize_cascade")
        self.assertEqual(agent._pending_cascade_label, "λ1..λ8")

    def test_form_maps_to_local_aspiration_with_constraint(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = "FORM poem"
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertEqual(action, "recess_aspiration")
        self.assertEqual(agent._pending_form_constraint, "poem")

    def test_create_and_contemplate_aliases_do_not_fall_through_unknown(self):
        for next_action, expected_action in [
            ("CREATE", "recess_aspiration"),
            ("CONTEMPLATE", "recess_notice"),
            ("BE", "recess_notice"),
            ("STILL", "recess_notice"),
        ]:
            with self.subTest(next_action=next_action):
                agent = self._agent()
                agent._hard_recovery_reset = False
                agent._pending_next_action = next_action
                with patch.object(
                    agent,
                    "_low_fill_guard_status",
                    return_value={
                        "active": False,
                        "fill_ratio": 0.68,
                        "target_fill_ratio": 0.68,
                        "spread_relief": 0.0,
                    },
                ):
                    action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
                self.assertEqual(action, expected_action)

    def test_experiment_run_failure_transcript_is_not_executed(self):
        agent = self._agent()
        agent._hard_recovery_reset = False
        agent._pending_next_action = (
            "EXPERIMENT_RUN FAILED: experiments/system-resources-demo$ python3 system_resources.py"
        )
        with patch.object(
            agent,
            "_low_fill_guard_status",
            return_value={
                "active": False,
                "fill_ratio": 0.68,
                "target_fill_ratio": 0.68,
                "spread_relief": 0.0,
            },
        ):
            action = agent._decide_action({"fill_ratio": 0.68, "eig1": 4.7})
        self.assertIsNone(action)
        self.assertIsNone(getattr(agent, "_pending_experiment_run_arg", None))

    def test_codex_placeholder_workspace_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with patch.object(aa, "WORKSPACE_DIR", workspace):
                dir_context, prompt, project, created, err = aa._resolve_codex_request(
                    "CODEX",
                    'system-resources-demo "<what to change>"',
                )
        self.assertIsNone(dir_context)
        self.assertEqual(prompt, "")
        self.assertEqual(project, "system-resources-demo")
        self.assertIsNone(created)
        self.assertIn("placeholder", err)

    def test_codex_query_placeholder_does_not_call_relay(self):
        agent = self._agent()
        agent._pending_codex_action = "CODEX"
        agent._pending_codex_arg = 'system-resources-demo "<what to change>"'
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(aa.requests, "post") as post,
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._codex_query({"fill_ratio": 0.68, "eig1": 4.7})
        post.assert_not_called()
        corrective_prompt = query.call_args.args[0]
        self.assertIn("was not sent", corrective_prompt)
        self.assertIn("create the missing script", corrective_prompt)

    def test_experiment_run_missing_file_guidance_avoids_placeholder_prompt(self):
        agent = self._agent()
        agent._pending_experiment_run_arg = "system-resources-demo python3 system_resources.py"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "experiments" / "system-resources-demo").mkdir(parents=True)
            with (
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._experiment_run({"fill_ratio": 0.68, "eig1": 4.7})
        prompt = query.call_args.args[0]
        self.assertIn("system_resources.py` does not exist", prompt)
        self.assertIn(
            'NEXT: CODEX system-resources-demo "create system_resources.py',
            prompt,
        )
        self.assertNotIn('"<what to change>"', prompt)

    def test_mike_fork_completes_empty_existing_workspace(self):
        agent = self._agent()
        agent._pending_mike_fork_arg = "system-resources-demo system-resources-demo"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_root = root / "research"
            src = research_root / "system-resources-demo"
            src.mkdir(parents=True)
            (src / "system_resources.py").write_text("print('resources')\n")
            (src / "README.md").write_text("# resources\n")
            workspace = root / "workspace"
            empty_fork = workspace / "experiments" / "system-resources-demo"
            empty_fork.mkdir(parents=True)
            with (
                patch.object(aa, "MIKE_RESEARCH_ROOT", research_root),
                patch.object(aa, "WORKSPACE_DIR", workspace),
                patch.object(agent, "_query_llm_with_next", return_value=("", None)) as query,
            ):
                agent._mike_fork({"fill_ratio": 0.68, "eig1": 4.7})
            self.assertEqual(
                (empty_fork / "system_resources.py").read_text(),
                "print('resources')\n",
            )
            self.assertTrue((empty_fork / "README.md").is_file())
            self.assertIn("already existed but was empty", query.call_args.args[0])

    def test_start_restores_context_before_boot_reflection_next_choice(self):
        agent = self._agent()
        agent.check_interval = 0
        calls = []

        def restore():
            calls.append("restore")
            agent._pending_next_action = "SELF_STUDY"

        def verify():
            calls.append("verify")
            agent._pending_next_action = "SEARCH fresh boot choice"

        def stop_after_one_loop():
            agent.running = False

        with (
            patch.object(agent, "_restore_sovereignty_state", side_effect=restore),
            patch.object(agent, "_verify_sovereignty", side_effect=verify),
            patch.object(agent, "_refresh_session_context", side_effect=stop_after_one_loop),
            patch.object(agent, "_get_latest_spectral_state", return_value=None),
            patch.object(agent, "_check_visual_responses"),
            patch.object(aa.time, "sleep"),
        ):
            agent.start()
        self.assertEqual(calls, ["restore", "verify"])
        self.assertEqual(agent._pending_next_action, "SEARCH fresh boot choice")


if __name__ == "__main__":
    unittest.main()
