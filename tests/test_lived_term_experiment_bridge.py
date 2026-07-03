import json
import tempfile
import unittest
from pathlib import Path

import autonomous_agent as aa


class LivedTermExperimentBridgeTests(unittest.TestCase):
    def _write_review(self, root: Path) -> Path:
        run_dir = root / "run-001"
        run_dir.mkdir(parents=True)
        review = {
            "lived_term_experiment_bridge_v1": {
                "candidates": [
                    {
                        "term": "silt",
                        "card_status": "promote_to_experiment_candidate",
                        "bridge_status": "ready_to_charter",
                        "recommended_next": (
                            "EXPERIMENT_START Lived term: silt :: "
                            "Does silt track telemetry?"
                        ),
                        "experiment_question": "Does silt track telemetry?",
                        "hypothesis_prompt": (
                            "If silt is signal, name the telemetry/audit evidence."
                        ),
                        "method_intent": "Compare later prose with audits.",
                        "evidence_targets": [
                            "telemetry_anchor",
                            "audit_or_review_artifact",
                            "counter_descriptor",
                        ],
                        "stop_criteria": "Stop if later entries repeat without evidence.",
                        "evidence_awareness_v1": {
                            "authority": "diagnostic_context_not_command",
                            "lease_workbench": {
                                "status": "preflight_prompts",
                                "suggested_playbook_count": 0,
                                "caution_card_count": 0,
                                "preflight_prompt_count": 1,
                                "suggested_playbooks": [],
                                "caution_cards": [],
                                "preflight_prompts": [
                                    {
                                        "signal": "semantic_friction_cluster_without_lease",
                                    }
                                ],
                            },
                            "recommended_action": (
                                "Read review evidence before choosing a scaffold."
                            ),
                        },
                        "charter_draft": {
                            "experiment_title": "Lived term: silt",
                            "question": "Does silt track telemetry?",
                            "hypothesis": (
                                "If silt is durable, later entries should move with "
                                "telemetry and audit evidence."
                            ),
                            "method_intent": "Compare later prose with audits.",
                            "proposed_next_action": "LIVED_TERM_STATUS silt",
                            "evidence_targets": [
                                "telemetry_anchor",
                                "audit_or_review_artifact",
                                "counter_descriptor",
                            ],
                            "stop_criteria": "Stop if later entries repeat without evidence.",
                            "suggested_charter_next": (
                                "EXPERIMENT_CHARTER current :: title: Lived term: silt"
                            ),
                        },
                        "source_card": {
                            "evidence_anchors": ["pressure_risk", "REGULATOR_AUDIT"],
                            "sample_paths": ["/tmp/public_silt.txt"],
                        },
                    },
                    {
                        "term": "empty pocket",
                        "card_status": "needs_counterexample",
                        "bridge_status": "needs_counterexample_first",
                        "recommended_next": (
                            "EXPERIMENT_START Lived term contrast: empty pocket :: "
                            "Find a counterexample."
                        ),
                        "experiment_question": "What counterexample clarifies empty pocket?",
                        "hypothesis_prompt": (
                            "If empty pocket is signal, name the telemetry/audit evidence."
                        ),
                        "method_intent": "Ask for contrast first.",
                        "evidence_targets": ["counter_descriptor"],
                        "stop_criteria": "Stop if later entries repeat without evidence.",
                        "evidence_awareness_v1": {
                            "authority": "diagnostic_context_not_command",
                            "absence_evidence": {
                                "classification": "needs_followup_read",
                                "expected_missing_count": 0,
                                "source_window_gap_count": 1,
                                "interrupted_thread_count": 0,
                                "named_missing_coordinate_count": 1,
                                "read_more_requested_but_not_followed": True,
                                "sample_paths": ["/tmp/public_empty_pocket.txt"],
                            },
                            "recommended_action": (
                                "Follow up READ_MORE before chartering absence."
                            ),
                        },
                        "counterexample_draft": {
                            "contrast_question": "What counterexample clarifies empty pocket?",
                            "counter_descriptor_prompt": (
                                "Name what `empty pocket` is not."
                            ),
                            "ordinary_gap_prompt": (
                                "Compare against an ordinary source gap."
                            ),
                            "negative_case_targets": [
                                "counter_descriptor",
                                "ordinary_gap",
                            ],
                            "suggested_contrast_next": (
                                "EXPERIMENT_START Lived term contrast: empty pocket :: "
                                "Find a counterexample."
                            ),
                            "suggested_dossier_counterclaim_next": (
                                "DOSSIER_CLAIM current :: claim: `empty pocket` has "
                                "a counterexample"
                            ),
                        },
                        "source_card": {
                            "sample_paths": ["/tmp/public_empty_pocket.txt"],
                        },
                    }
                ]
            },
            "regulator_live_replay_v1": {
                "status": "felt_pressure_boundary_context",
                "cartography_source": "/tmp/regulator_boundary_cartography/latest.json",
                "felt_pressure_match_count": 2,
            },
            "regulator_boundary_replay_cards_v1": {
                "status": "boundary_near_felt_pressure",
                "card_count": 2,
                "status_counts": {
                    "near_pressure_jump": 1,
                    "observational_plateau": 1,
                },
                "cards": [
                    {
                        "card_id": "regulator_near_pressure_jump_1",
                        "status": "near_pressure_jump",
                        "term": "pressure_risk",
                        "finding_label": "pressure_risk >= 0.60 downward-bias boundary",
                        "axis": "pressure_risk",
                        "nearest_threshold": 0.60,
                        "evidence_anchors": ["pressure_risk", "regulator_audit"],
                        "texture_terms": ["heavy", "pressure"],
                        "public_sample_paths": ["/tmp/public_pressure.txt"],
                        "recommended_action": "Compare audits before tuning.",
                    },
                    {
                        "card_id": "regulator_observational_plateau_2",
                        "status": "observational_plateau",
                        "term": "observational_plateau",
                        "finding_label": "felt pressure recurs while output is unchanged",
                        "axis": "pressure_risk",
                        "public_sample_paths": ["/tmp/public_plateau.txt"],
                    },
                ],
            },
            "regulator_plateau_missing_variable_model_v1": {
                "status": "plateau_missing_variable_hypotheses",
                "findings": [
                    {"variable": "semantic_friction"},
                    {"variable": "stable_core"},
                ],
            },
            "regulator_replay_time_series_v1": {
                "status": "repeated_boundary_near_pressure",
                "window_review_count": 3,
            },
            "regulator_counterfactual_sweep_v1": {
                "status": "counterfactual_sweep_available",
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_family": "pressure_hysteresis",
                        "affected_region": "pressure_risk >= 0.60",
                    }
                ],
            },
            "regulator_counterfactual_replay_lab_v1": {
                "status": "replay_supported_with_plateau_caution",
                "verdict_counts": {
                    "replay_supported_offline_candidate": 1,
                    "missing_variable_first": 1,
                },
                "evaluated_candidates": [
                    {
                        "candidate_family": "pressure_hysteresis",
                        "replay_fit": "repeated_boundary_support",
                        "verdict": "replay_supported_offline_candidate",
                        "target_statuses": ["near_pressure_jump"],
                        "matched_statuses": ["near_pressure_jump"],
                        "matched_card_ids": ["regulator_near_pressure_jump_1"],
                        "recurrent_count": 3,
                        "estimated_reduction_pct": 60.0,
                    },
                    {
                        "candidate_family": "thin_density_softening",
                        "replay_fit": "plateau_recurrence_outweighs_threshold_smoothing",
                        "verdict": "missing_variable_first",
                        "target_statuses": ["thin_density_boundary"],
                        "matched_statuses": [],
                        "matched_card_ids": [],
                        "recurrent_count": 0,
                        "estimated_reduction_pct": 40.0,
                    },
                ],
            },
            "regulator_plateau_evidence_matrix_v1": {
                "status": "unresolved_missing_variables",
                "top_unresolved_variables": [
                    {
                        "variable": "semantic_friction",
                        "confidence": "high",
                        "score": 9.5,
                    },
                    {
                        "variable": "pressure_source",
                        "confidence": "medium",
                        "score": 5.0,
                    },
                ],
            },
            "regulator_tuning_readiness_gate_v1": {
                "status": "blocked_missing_variable",
                "gate_counts": {"blocked_missing_variable": 2},
                "unresolved_missing_variables": [
                    "semantic_friction",
                    "pressure_source",
                ],
                "gated_candidates": [
                    {
                        "candidate_family": "pressure_hysteresis",
                        "gate_status": "blocked_missing_variable",
                        "gate_reason": (
                            "plateau evidence has unresolved high/medium missing variables"
                        ),
                        "replay_verdict": "replay_supported_offline_candidate",
                        "matched_card_ids": ["regulator_near_pressure_jump_1"],
                        "unresolved_missing_variables": [
                            "semantic_friction",
                            "pressure_source",
                        ],
                    },
                    {
                        "candidate_family": "thin_density_softening",
                        "gate_status": "blocked_missing_variable",
                        "gate_reason": (
                            "plateau evidence has unresolved high/medium missing variables"
                        ),
                        "replay_verdict": "missing_variable_first",
                        "matched_card_ids": [],
                        "unresolved_missing_variables": [
                            "semantic_friction",
                            "pressure_source",
                        ],
                    },
                ],
            },
            "pi_pressure_wiring_replay_v1": {
                "status": "replay_supported_candidates",
                "source": "live-db",
                "source_status": "live_window_ready",
                "sample_count": 12,
                "candidate_count": 2,
                "artifact_path": "/tmp/pi_pressure_wiring_replay.json",
                "candidate_status_counts": {
                    "replay_supported": 1,
                    "snap_risk": 1,
                },
                "top_candidates": [
                    {
                        "candidate_family": "pressure_source_target_bias",
                        "status": "replay_supported",
                        "estimated_improvement_pct": 18.0,
                        "pressure_alignment_delta": 0.08,
                        "snap_risk_delta": -0.02,
                        "afterimage_risk_delta": -0.01,
                        "default_off_canary": {
                            "default_off_env": "MINIME_PI_PRESSURE_WIRING_CANARY",
                            "eligible": True,
                        },
                    },
                ],
            },
            "pi_pressure_candidate_readiness_v1": {
                "status": "blocked_missing_variable",
                "readiness_counts": {
                    "blocked_missing_variable": 1,
                    "blocked_safety_review": 1,
                },
                "unresolved_missing_variables": [
                    "semantic_friction",
                    "pressure_source",
                ],
                "candidates": [
                    {
                        "candidate_family": "pressure_source_target_bias",
                        "gate_status": "blocked_missing_variable",
                        "gate_reason": (
                            "plateau evidence still has unresolved high/medium "
                            "missing variables"
                        ),
                        "replay_status": "replay_supported",
                        "estimated_improvement_pct": 18.0,
                        "snap_risk_delta": -0.02,
                        "afterimage_risk_delta": -0.01,
                        "default_off_canary": {
                            "default_off_env": "MINIME_PI_PRESSURE_WIRING_CANARY",
                            "eligible": False,
                        },
                    },
                ],
            },
            "pressure_source_to_pi_gap_v1": {
                "status": "replay_available_gap_open",
                "pressure_vector_status": "rising_overpacked_pressure",
                "pressure_medium_status": "semantic_friction_medium",
                "pi_replay_status": "replay_supported_candidates",
                "pi_readiness_status": "blocked_missing_variable",
                "source_anchors": ["pressure_vector:rising_overpacked_pressure"],
                "recommended_routes": [
                    "PI_PRESSURE_REPLAY_STATUS latest",
                    "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                ],
            },
            "regulator_missing_variable_evidence_loop_v1": {
                "status": "evidence_needed_before_tuning",
                "blocked_gate_status": "blocked_missing_variable",
                "probe_count": 2,
                "top_probes": [
                    {
                        "variable": "semantic_friction",
                        "priority": "high",
                        "suggested_next": "PRESSURE_SOURCE_AUDIT semantic-friction",
                        "source_confidence": "high",
                    },
                    {
                        "variable": "pressure_source",
                        "priority": "high",
                        "suggested_next": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                        "source_confidence": "medium",
                    },
                ],
                "probes": [
                    {
                        "variable": "semantic_friction",
                        "priority": "high",
                        "suggested_next": "PRESSURE_SOURCE_AUDIT semantic-friction",
                        "source_confidence": "high",
                    },
                    {
                        "variable": "pressure_source",
                        "priority": "high",
                        "suggested_next": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                        "source_confidence": "medium",
                    },
                ],
            },
            "returnable_distinctions_v1": {
                "status": "returnable_distinctions_present",
                "active_card_count": 3,
                "cards": [
                    {
                        "card_id": "pressure_level_vs_pressure_velocity",
                        "status": "felt_pressure_without_trend_context",
                        "lifecycle_state": "needs_audit",
                        "preflight_verdict": "audit_first",
                        "next_resolution_route": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                        "recommended_read_only_route": "PRESSURE_SOURCE_AUDIT current-fill_pressure",
                        "relevant_self_regulation_route": "SELF_REGULATION_PREFLIGHT latest",
                        "relevant_experiment_lived_term_route": "EXPERIMENT_OBSERVE current :: pressure_trend=<stable|rising|falling>",
                    },
                    {
                        "card_id": "slope_drag_vs_medium_mass",
                        "status": "low_gradient_weight_mismatch",
                        "lifecycle_state": "needs_audit",
                        "preflight_verdict": "audit_first",
                        "next_resolution_route": "PRESSURE_SOURCE_AUDIT semantic-friction",
                        "recommended_read_only_route": "PRESSURE_SOURCE_AUDIT semantic-friction",
                        "relevant_self_regulation_route": "SELF_REGULATION_STATUS",
                        "relevant_experiment_lived_term_route": "LIVED_TERM_EXPERIMENT viscosity",
                    },
                    {
                        "card_id": "codec_smoothing_vs_pressure",
                        "status": "projection_compression_risk",
                        "lifecycle_state": "needs_audit",
                        "preflight_verdict": "audit_first",
                        "next_resolution_route": "CODEC_MAP",
                        "recommended_read_only_route": "CODEC_MAP",
                        "relevant_self_regulation_route": "SELF_REGULATION_STATUS",
                        "relevant_experiment_lived_term_route": "LIVED_TERM_STATUS viscosity",
                    },
                ],
            },
        }
        path = run_dir / "review.json"
        path.write_text(json.dumps(review), encoding="utf-8")
        return path

    def test_parse_next_action_accepts_lived_term_verbs(self) -> None:
        action, cleaned = aa.parse_next_action(
            "The card feels ready to inspect.\nNEXT: LIVED_TERM_EXPERIMENT silt"
        )

        self.assertEqual(action, "LIVED_TERM_EXPERIMENT silt")
        self.assertNotIn("NEXT:", cleaned)

    def test_parse_next_action_accepts_regulator_map_verbs(self) -> None:
        action, cleaned = aa.parse_next_action(
            "The replay card feels relevant.\nNEXT: REGULATOR_BOUNDARY_CARD near_pressure_jump"
        )

        self.assertEqual(action, "REGULATOR_BOUNDARY_CARD near_pressure_jump")
        self.assertNotIn("NEXT:", cleaned)

        action, cleaned = aa.parse_next_action(
            "The PI replay feels relevant.\nNEXT: PI_PRESSURE_REPLAY_STATUS latest"
        )

        self.assertEqual(action, "PI_PRESSURE_REPLAY_STATUS latest")
        self.assertNotIn("NEXT:", cleaned)

    def test_renderer_returns_advisory_scaffold_without_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)

            text = aa.render_lived_term_bridge_action(
                "LIVED_TERM_EXPERIMENT",
                "silt",
                review_root=review_root,
            )

            self.assertIn("diagnostic_context_not_command", text)
            self.assertIn("No experiment was created or advanced.", text)
            self.assertIn("Evidence awareness", text)
            self.assertIn("lease_workbench", text)
            self.assertIn("semantic_friction_cluster_without_lease", text)
            self.assertIn("Returnable distinctions", text)
            self.assertIn("slope_drag_vs_medium_mass", text)
            self.assertIn("lifecycle=`needs_audit`", text)
            self.assertIn("preflight=`audit_first`", text)
            self.assertIn("NEXT: EXPERIMENT_START", text)
            self.assertIn("Charter draft", text)
            self.assertIn("NEXT: EXPERIMENT_CHARTER current ::", text)
            self.assertIn("NEXT: EXPERIMENT_OBSERVE current ::", text)
            self.assertIn("NEXT: DOSSIER_CLAIM current ::", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_renderer_displays_counterexample_forge_without_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)

            text = aa.render_lived_term_bridge_action(
                "LIVED_TERM_EXPERIMENT",
                "empty pocket",
                review_root=review_root,
            )

            self.assertIn("Counterexample forge", text)
            self.assertIn("Evidence awareness", text)
            self.assertIn("absence_evidence", text)
            self.assertIn("needs_followup_read", text)
            self.assertIn("Name what `empty pocket` is not", text)
            self.assertIn("NEXT: EXPERIMENT_START Lived term contrast", text)
            self.assertIn("NEXT: DOSSIER_CLAIM current ::", text)
            self.assertNotIn("Charter draft", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_thread_action_surface_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)
            store = aa.ActionContinuityStore(workspace)

            original = aa.render_lived_term_bridge_action

            aa.render_lived_term_bridge_action = (
                lambda base, selector="latest": original(
                    base,
                    selector,
                    review_root=review_root,
                )
            )
            try:
                text = store.handle_thread_action(
                    "LIVED_TERM_STATUS latest",
                    {"fill_ratio": 0.68},
                )
            finally:
                aa.render_lived_term_bridge_action = original

            self.assertIn("=== LIVED TERM STATUS ===", text)
            self.assertIn("Term: `silt`", text)
            self.assertIn("Evidence awareness", text)
            self.assertIn("lease_workbench", text)
            self.assertIn("Returnable distinctions", text)
            self.assertIn("SELF_REGULATION_STATUS", text)
            self.assertIn("lifecycle=`needs_audit`", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_regulator_map_status_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)

            text = aa.render_regulator_map_bridge_action(
                "REGULATOR_MAP_STATUS",
                "latest",
                review_root=review_root,
            )

            self.assertIn("=== REGULATOR MAP STATUS ===", text)
            self.assertIn("diagnostic_context_not_command", text)
            self.assertIn("felt_pressure_boundary_context", text)
            self.assertIn("repeated_boundary_near_pressure", text)
            self.assertIn("pressure_hysteresis", text)
            self.assertIn("replay_supported_with_plateau_caution", text)
            self.assertIn("replay_supported_offline_candidate", text)
            self.assertIn("Plateau evidence matrix", text)
            self.assertIn("Tuning readiness gate", text)
            self.assertIn("blocked_missing_variable", text)
            self.assertIn("Why not tuning yet", text)
            self.assertIn("PI pressure wiring replay", text)
            self.assertIn("Pressure-source-to-PI gap", text)
            self.assertIn("PI_PRESSURE_REPLAY_STATUS latest", text)
            self.assertIn("Missing-variable evidence loop", text)
            self.assertIn("Returnable distinctions", text)
            self.assertIn("pressure_level_vs_pressure_velocity", text)
            self.assertIn("lifecycle=`needs_audit`", text)
            self.assertIn(
                "semantic_friction->PRESSURE_SOURCE_AUDIT semantic-friction",
                text,
            )
            self.assertIn("no controller was tuned", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_pi_pressure_replay_status_surface_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)

            text = aa.render_regulator_map_bridge_action(
                "PI_PRESSURE_REPLAY_STATUS",
                "latest",
                review_root=review_root,
            )

            self.assertIn("=== PI PRESSURE REPLAY STATUS ===", text)
            self.assertIn("diagnostic_context_not_command", text)
            self.assertIn("pressure_source_target_bias", text)
            self.assertIn("blocked_missing_variable", text)
            self.assertIn("MINIME_PI_PRESSURE_WIRING_CANARY", text)
            self.assertIn("runtime_ignored_in_this_tranche=true", text)
            self.assertIn("no controller was tuned", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_regulator_boundary_card_renderer_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)

            text = aa.render_regulator_map_bridge_action(
                "REGULATOR_BOUNDARY_CARD",
                "regulator_near_pressure_jump_1",
                review_root=review_root,
            )

            self.assertIn("=== REGULATOR BOUNDARY CARD ===", text)
            self.assertIn("pressure_risk >= 0.60", text)
            self.assertIn("pressure_risk, regulator_audit", text)
            self.assertIn("Compare audits before tuning.", text)
            self.assertIn("pressure_hysteresis:replay_supported_offline_candidate", text)
            self.assertIn("pressure_hysteresis:blocked_missing_variable", text)
            self.assertIn("Evidence loop probes", text)
            self.assertIn("Returnable distinctions", text)
            self.assertIn("codec_smoothing_vs_pressure", text)
            self.assertIn("preflight=`audit_first`", text)
            self.assertIn(
                "pressure_source->PRESSURE_SOURCE_AUDIT current-fill_pressure",
                text,
            )
            self.assertIn("no peer was mutated", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())

    def test_regulator_thread_action_surface_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_root = root / "reviews"
            workspace = root / "workspace"
            workspace.mkdir()
            self._write_review(review_root)
            store = aa.ActionContinuityStore(workspace)

            original = aa.render_regulator_map_bridge_action

            aa.render_regulator_map_bridge_action = (
                lambda base, selector="latest": original(
                    base,
                    selector,
                    review_root=review_root,
                )
            )
            try:
                text = store.handle_thread_action(
                    "REGULATOR_REPLAY_STATUS observational_plateau",
                    {"fill_ratio": 0.68},
                )
            finally:
                aa.render_regulator_map_bridge_action = original

            self.assertIn("=== REGULATOR REPLAY STATUS ===", text)
            self.assertIn("Matched cards: 1", text)
            self.assertIn("regulator_observational_plateau_2", text)
            self.assertIn("Counterfactual matches", text)
            self.assertIn("missing_variable_first", text)
            self.assertIn("Tuning readiness gate", text)
            self.assertIn("blocked_missing_variable", text)
            self.assertIn("Missing-variable evidence loop", text)
            self.assertIn("Returnable distinctions", text)
            self.assertIn("PRESSURE_SOURCE_AUDIT semantic-friction", text)
            self.assertIn("no controller was tuned", text)
            self.assertFalse((workspace / "action_threads" / "experiments").exists())


if __name__ == "__main__":
    unittest.main()
