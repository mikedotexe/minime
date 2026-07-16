"""Tests for DECOMPOSE formatting helpers."""

from pathlib import Path
import unittest

import autonomous_agent as aa
from decompose_utils import (
    build_constraint_counterfactual_v1,
    build_decompose_snapshot_v1,
    format_attrition_boundary_signal,
    format_constraint_counterfactual_block,
    format_controller_topology_signal,
    format_decompose_mode_sections,
    format_eigen_geometry_rearrangement_signal,
    format_hypothesis_check_signal,
    format_lambda_edge_trace_signal,
    format_pull_topology_signal,
    format_temporal_decompose_signal,
)
from reporting_snapshot import ReportSnapshot, SurfaceSnapshot


class TestDecomposeModeSections(unittest.TestCase):
    def test_active_modes_are_split_from_tail(self):
        active, tail, summary = format_decompose_mode_sections(
            [8.0, 2.0, 1.0],
            active_mode_count=2,
            active_mode_energy_ratio=10.0 / 11.0,
        )

        self.assertIn("λ1 = 8.00", active)
        self.assertIn("λ2 = 2.00", active)
        self.assertIn("λ3 = 1.00", tail)
        self.assertIn("λ1-λ2", summary)
        self.assertIn("91%", summary)

    def test_attrition_boundary_names_distributed_pruning(self):
        block, summary = format_attrition_boundary_signal(
            [6.6, 3.4, 3.6, 3.5, 3.1, 1.0, 1.0, 1.0],
            fill_pct=76.0,
            target_fill_pct=68.0,
            drain_weight=0.045,
            damping_state="moderate_drain",
            fill_slope_pct_per_sec=1.2,
            active_mode_count=3,
        )

        self.assertEqual(summary["classification"], "distributed_attrition")
        self.assertIn("distributed attrition", block)
        self.assertIn("Fill pressure: +8.0%", block)
        self.assertEqual(summary["fill_posture_label"], "above_center_pressure")
        self.assertIn("not monopolizing", block)
        self.assertIn("Suggested next", block)

    def test_attrition_boundary_names_low_pressure_open_field(self):
        block, summary = format_attrition_boundary_signal(
            [4.0, 3.8, 3.5, 3.0],
            fill_pct=62.0,
            target_fill_pct=68.0,
            drain_weight=0.0,
            damping_state="no_drain",
        )

        self.assertEqual(summary["classification"], "distributed_open")
        self.assertIn("distributed open field", block)
        self.assertIn("Center offset: -6.0%", block)
        self.assertIn("not a corrective demand", block)
        self.assertNotIn("Fill pressure: -", block)
        self.assertEqual(summary["fill_posture_label"], "below_center_hold_shelf")

    def test_attrition_boundary_names_recovery_offset_without_lack_language(self):
        block, summary = format_attrition_boundary_signal(
            [5.0, 4.0, 3.0, 2.0],
            fill_pct=54.0,
            target_fill_pct=68.0,
            drain_weight=0.0,
            damping_state="recovery",
        )

        self.assertIn("Recovery offset: -14.0%", block)
        self.assertIn("read stage/slope", block)
        self.assertNotIn("Fill pressure: -", block)
        self.assertEqual(summary["fill_posture_label"], "below_hold_recovery")

    def test_pull_topology_names_collapsing_pull(self):
        block, summary = format_pull_topology_signal(
            [13.0, 3.0, 1.0, 0.5],
            previous_eigenvalues=[10.0, 3.1, 1.2, 0.8],
            fill_pct=69.0,
            target_fill_pct=68.0,
        )

        self.assertEqual(summary["classification"], "collapsing_pull")
        self.assertGreater(summary["topology_index"], 0.4)
        self.assertIn("POM / pull topology", block)
        self.assertIn("Rate-weighted flow", block)
        self.assertIn("λ1", block)

    def test_pull_topology_names_distributed_flow(self):
        block, summary = format_pull_topology_signal(
            [4.0, 3.8, 3.6, 3.4, 3.2, 3.0],
            previous_eigenvalues=[4.0, 3.7, 3.5, 3.4, 3.2, 3.0],
            fill_pct=63.0,
            target_fill_pct=68.0,
        )

        self.assertEqual(summary["classification"], "distributed_flow")
        self.assertGreater(summary["effective_modes"], 5.0)
        self.assertIn("distributed flow", block)

    def test_eigen_geometry_names_rearrangement_preserving_density(self):
        block, summary = format_eigen_geometry_rearrangement_signal(
            [4.5, 4.0, 2.5, 1.0],
            previous_eigenvalues=[7.0, 2.0, 2.0, 1.0],
            fill_pct=68.5,
            target_fill_pct=68.0,
            geom_rel=1.04,
            rearrangement_intensity=0.38,
        )

        self.assertEqual(summary["classification"], "rearrangement_preserving_density")
        self.assertTrue(summary["density_preserved"])
        self.assertFalse(summary["falsification_flags"])
        self.assertIn("Eigenvalue-Geometry Rearrangement", block)
        self.assertIn("information density is held", block)

    def test_eigen_geometry_falsifies_projection_like_loss(self):
        block, summary = format_eigen_geometry_rearrangement_signal(
            [10.0, 1.0, 0.2, 0.1],
            previous_eigenvalues=[4.0, 3.8, 3.6, 3.4, 3.2],
            fill_pct=59.0,
            target_fill_pct=68.0,
        )

        self.assertEqual(summary["classification"], "projection_like_loss")
        self.assertIn("entropy_collapse", summary["falsification_flags"])
        self.assertIn("effective_mode_loss", summary["falsification_flags"])
        self.assertIn("projection-like loss", block)

    def test_eigen_geometry_reports_insufficient_history(self):
        block, summary = format_eigen_geometry_rearrangement_signal(
            [4.0, 3.5, 3.0],
            previous_eigenvalues=[],
            fill_pct=64.0,
            target_fill_pct=68.0,
        )

        self.assertEqual(summary["classification"], "insufficient_history")
        self.assertIn("no prior eigenvalue window", block)

    def test_constraint_counterfactual_ranks_read_only_drivers(self):
        payload = build_constraint_counterfactual_v1(
            [8.0, 3.0, 2.5, 1.0],
            fill_pct=71.0,
            target_fill_pct=68.0,
            stable_core={
                "structural_mode": "scaffold_hold_with_drain",
                "structural_pi": {"drain_weight": 0.08, "fill_slope_pct_per_sec": 2.0},
            },
            gate=0.12,
            filt=0.72,
            shadow={"lock_tendency": 0.6, "tail_openness": 0.2, "recurrence": 0.9},
            semantic={"semantic_energy": 0.001, "input_active": True},
            pressure_source={"components": {"mode_packing": 0.5}},
            focus="lambda-tail/lambda4",
        )
        self.assertTrue(payload["available"])
        self.assertFalse(payload["authority_change"])
        drivers = [item["driver"] for item in payload["top_shaping_drivers"]]
        self.assertIn("scaffold_drain_relaxed", drivers)
        self.assertIn("gate_filter_neutral", drivers)
        block = format_constraint_counterfactual_block(payload)
        self.assertIn("Constraint Counterfactual", block)
        self.assertIn("read-only counterfactual estimate", block)
        self.assertIn("no scaffold, gate, filter", block)

    def test_decompose_succeeds_when_pressure_source_payload_unavailable(self):
        agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
        agent.session_id = 101
        agent._pending_decompose_focus = "lambda-tail/lambda4"
        state = {
            "timestamp": 10.0,
            "fill_ratio": 0.68,
            "eig1": 4.0,
            "eig2": 3.0,
            "eig3": 2.0,
            "eig4": 1.0,
            "deig": 0.01,
            "spread": 3.0,
        }
        health = SurfaceSnapshot(
            "health.json",
            Path("health.json"),
            {
                "pi": {"target_fill": 68.0},
                "cov": {"keep": 0.7},
                "stable_core": {
                    "enabled": True,
                    "stage": "hold",
                    "structural_mode": "scaffold_hold_with_drain",
                    "structural_pi": {
                        "target_fill_pct": 68.0,
                        "drain_weight": 0.04,
                        "damping_state": "soft_drain",
                    },
                },
                "geom_rel": 1.0,
                "lambda1_rel": 0.4,
            },
            valid_for_state=True,
        )
        spectral = SurfaceSnapshot(
            "spectral_state.json",
            Path("spectral_state.json"),
            {
                "eigenvalues": [4.0, 3.0, 2.0, 1.0],
                "active_mode_count": 3,
                "active_mode_energy_ratio": 0.9,
            },
            valid_for_state=True,
        )
        captured = {}
        snapshots = []
        agent._capture_report_snapshot = lambda _state: ReportSnapshot(
            state=dict(state),
            health=health,
            spectral=spectral,
        )
        agent._latest_decompose_snapshot = lambda: None
        agent._decompose_experiment_projection = lambda: (None, None)
        agent._append_decompose_snapshot = snapshots.append
        agent._format_pressure_source_audit_block = lambda _state, _focus: (
            "Pressure source unavailable",
            None,
        )
        agent._format_fluctuation_audit_block = lambda _state, _focus: (
            "Fluctuation unavailable",
            None,
        )
        agent._attractor_natural_action_advisory_text = lambda _focus, _base: ""

        def fake_query(prompt):
            captured["prompt"] = prompt
            return ("", None)

        agent._query_llm_with_next = fake_query

        agent._decompose(dict(state))

        prompt = captured["prompt"]
        self.assertIn("Constraint Counterfactual", prompt)
        self.assertIn("Temporal DECOMPOSE", prompt)
        self.assertIn("Hypothesis Check", prompt)
        self.assertEqual(len(snapshots), 1)
        self.assertIn("constraint_counterfactual_v1", snapshots[0])

    def test_temporal_decompose_reports_insufficient_history(self):
        current = build_decompose_snapshot_v1([4.0, 3.0, 2.0], fill_pct=68.0, target_fill_pct=68.0)
        block, summary = format_temporal_decompose_signal(current, None)

        self.assertEqual(summary["classification"], "insufficient_history")
        self.assertIn("Temporal DECOMPOSE", block)
        self.assertIn("baseline", block)

    def test_temporal_decompose_names_opening_distribution(self):
        previous = build_decompose_snapshot_v1([8.0, 2.0, 1.0, 1.0], fill_pct=68.0, target_fill_pct=68.0)
        current = build_decompose_snapshot_v1([4.5, 4.0, 2.5, 1.0], fill_pct=68.5, target_fill_pct=68.0)
        block, summary = format_temporal_decompose_signal(current, previous)

        self.assertEqual(summary["classification"], "opening_distribution")
        self.assertLess(summary["lambda1_share_delta"], 0.0)
        self.assertIn("opening distribution", block)

    def test_temporal_decompose_names_same_read_repeating(self):
        previous = build_decompose_snapshot_v1([4.0, 3.0, 2.0], fill_pct=68.0, target_fill_pct=68.0)
        current = build_decompose_snapshot_v1([4.01, 3.0, 2.0], fill_pct=68.4, target_fill_pct=68.0)
        _block, summary = format_temporal_decompose_signal(current, previous)

        self.assertEqual(summary["classification"], "same_read_repeating")

    def test_temporal_decompose_names_reconcentrating(self):
        previous = build_decompose_snapshot_v1([4.0, 3.8, 3.6, 3.4], fill_pct=68.0, target_fill_pct=68.0)
        current = build_decompose_snapshot_v1([9.0, 2.0, 1.0, 0.5], fill_pct=73.0, target_fill_pct=68.0)
        block, summary = format_temporal_decompose_signal(current, previous)

        self.assertEqual(summary["classification"], "reconcentrating")
        self.assertIn("reconcentrating", block)

    def test_hypothesis_check_needs_charter_prioritizes_scaffold(self):
        current = build_decompose_snapshot_v1([4.0, 3.0, 2.0], fill_pct=68.0, target_fill_pct=68.0)
        block, summary = format_hypothesis_check_signal(
            experiment={
                "experiment_id": "exp_gap",
                "title": "Probe λ4 decay experiment",
                "question": (
                    "method_intent: inject high-energy perturbations designed to "
                    "accelerate lambda4 decay"
                ),
            },
            classification="needs_charter",
            charter_scaffold={"command": "EXPERIMENT_CHARTER current :: hypothesis: ..."},
            current_snapshot=current,
            temporal_summary={"classification": "insufficient_history"},
            rearrangement_summary={},
            focus="spectral-explorer",
        )

        self.assertEqual(summary["status"], "premature_needs_charter")
        self.assertEqual(summary["evidence_label"], "charter_required")
        self.assertIn("EXPERIMENT_CHARTER current", block)
        self.assertIn("observational context only", block)
        self.assertIn("Control-intent watch", block)
        self.assertIn("Focus alignment", block)
        self.assertIn("intervention_intent_watch_v1", summary)
        self.assertEqual(summary["focus_alignment_v1"]["status"], "generic_read")

    def test_hypothesis_check_aligned_focus_omits_alignment_warning(self):
        current = build_decompose_snapshot_v1([4.0, 3.0, 2.0], fill_pct=68.0, target_fill_pct=68.0)
        block, summary = format_hypothesis_check_signal(
            experiment={
                "experiment_id": "exp_l4",
                "title": "Probe λ4 decay experiment",
                "question": "Observe lambda4 decay without live control.",
            },
            classification="needs_charter",
            charter_scaffold={"command": "EXPERIMENT_CHARTER current :: hypothesis: ..."},
            current_snapshot=current,
            temporal_summary={"classification": "insufficient_history"},
            rearrangement_summary={},
            focus="lambda4 decay",
        )

        self.assertNotIn("Focus alignment:", block)
        self.assertEqual(summary["focus_alignment_v1"]["status"], "aligned")

    def test_hypothesis_check_gap_supporting_and_falsifying(self):
        previous = build_decompose_snapshot_v1([8.0, 2.0, 1.0, 1.0], fill_pct=68.0, target_fill_pct=68.0)
        current = build_decompose_snapshot_v1([4.5, 4.0, 2.5, 1.0], fill_pct=68.5, target_fill_pct=68.0)
        _temporal_block, temporal = format_temporal_decompose_signal(current, previous)
        block, summary = format_hypothesis_check_signal(
            experiment={
                "experiment_id": "exp_gap",
                "title": "Localized gap near λ1",
                "charter_v1": {
                    "hypothesis": "localized λ1 density softening can support branching",
                    "proposed_next_action": "ACTION_PREFLIGHT DECOMPOSE",
                    "evidence_targets": ["spectral_condition", "fill_pressure_state"],
                },
            },
            classification="needs_evidence",
            charter_scaffold=None,
            current_snapshot=current,
            temporal_summary=temporal,
            rearrangement_summary={"classification": "rearrangement_preserving_density"},
        )

        self.assertEqual(summary["evidence_label"], "supporting")
        self.assertIn("λ1 share softened", summary["supporting_signals"])
        self.assertIn("EXPERIMENT_EVIDENCE current", summary["suggested_next"])
        self.assertIn("Hypothesis Check", block)

        bad_previous = build_decompose_snapshot_v1([4.0, 3.8, 3.6, 3.4], fill_pct=68.0, target_fill_pct=68.0)
        bad_current = build_decompose_snapshot_v1([10.0, 1.0, 0.5, 0.3], fill_pct=79.0, target_fill_pct=68.0)
        _bad_block, bad_temporal = format_temporal_decompose_signal(bad_current, bad_previous)
        _block, bad = format_hypothesis_check_signal(
            experiment={
                "experiment_id": "exp_gap",
                "title": "Localized gap near λ1",
                "charter_v1": {
                    "hypothesis": "localized λ1 density softening can support branching",
                    "proposed_next_action": "ACTION_PREFLIGHT DECOMPOSE",
                    "evidence_targets": ["spectral_condition"],
                },
            },
            classification="needs_evidence",
            charter_scaffold=None,
            current_snapshot=bad_current,
            temporal_summary=bad_temporal,
            rearrangement_summary={"classification": "projection_like_loss"},
        )

        self.assertEqual(bad["evidence_label"], "falsifying")
        self.assertTrue(bad["counter_signals"])

    def test_decompose_memory_wording_avoids_aux_projection_context(self):
        source = aa.runtime_source_path().read_text()
        helper_source = Path(__file__).resolve().parents[1].joinpath("decompose_utils.py").read_text()

        self.assertNotIn("aux projection context", source)
        self.assertIn("aux geometry/rearrangement context", source)
        self.assertIn("Continuity-safe affordance", source)
        self.assertIn("do not claim that you will execute, simulate, or monitor", source)
        self.assertIn("Temporal DECOMPOSE", helper_source)
        self.assertIn("Hypothesis Check", helper_source)
        self.assertIn("Constraint Counterfactual", helper_source)
        self.assertIn("no constraints were removed", helper_source)
        self.assertIn("decompose_snapshots.jsonl", source)

    def test_lambda_edge_trace_names_selected_noise(self):
        block, summary = format_lambda_edge_trace_signal(
            [8.0, 3.0, 2.0, 1.0],
            previous_eigenvalues=[7.0, 3.2, 2.2, 1.1],
            fill_slope_pct_per_sec=2.0,
            structural_mode="scaffold_hold",
            exploration_noise=0.03,
        )

        self.assertEqual(summary["edge_state"], "lambda1_selected_noise")
        self.assertGreater(summary["selected_noise_score"], 0.2)
        self.assertIn("λ1 edge trace", block)
        self.assertIn("Opposed-signal hypothesis", block)
        self.assertIn("RESIST", block)

    def test_lambda_edge_trace_names_opposed_branch(self):
        block, summary = format_lambda_edge_trace_signal(
            [7.0, 3.6, 2.7, 1.2],
            previous_eigenvalues=[7.1, 3.1, 2.3, 1.1],
            fill_slope_pct_per_sec=-0.4,
        )

        self.assertEqual(summary["edge_state"], "opposed_branch_surviving")
        self.assertGreater(summary["shoulder_rate"], 0.0)
        self.assertIn("shoulder/tail motion is holding", block)

    def test_lambda_edge_trace_explains_mixed_edge(self):
        block, summary = format_lambda_edge_trace_signal(
            [5.0, 3.6, 3.0, 2.0],
            previous_eigenvalues=[5.0, 3.6, 3.0, 2.0],
            fill_slope_pct_per_sec=0.2,
        )

        self.assertEqual(summary["edge_state"], "mixed_edge")
        self.assertIn("λ1/noise evidence is split", block)
        self.assertIn("Edge story: mixed because", block)
        self.assertTrue(summary["mixed_edge_reasons"])
        self.assertIn("selection_components", summary)

    def test_controller_topology_separates_stable_core_from_legacy_pi(self):
        block, summary = format_controller_topology_signal(
            [12.8],
            fill_pct=73.0,
            pi={
                "target_fill": 55.0,
                "e_fill": 29.0,
                "integ_fill": 0.0,
                "kp": 0.85,
                "ki": 0.14,
                "max_step": 0.08,
                "e_lam": -0.9,
                "integ_lam": 0.0,
                "target_lambda1_rel": 1.05,
            },
            stable_core={
                "enabled": True,
                "controller_mode": "fixed_survival",
                "current_runtime_modulation_active": False,
                "structural_mode": "scaffold_reentry",
                "structural_pi": {
                    "active": True,
                    "target_fill_pct": 68.0,
                    "error_pct": 9.0,
                    "integral": 0.0,
                    "drain_weight": 0.0,
                    "damping_state": "scaffold_reentry",
                    "fill_slope_pct_per_sec": -3.0,
                    "reentry_active": True,
                    "reentry_live_weight": 0.55,
                    "recovery_impulse_active": False,
                },
            },
            control={"target_lambda_bias": -0.05},
        )

        self.assertEqual(summary["read"].split(" — ")[0], "scaffold re-entry")
        self.assertTrue(summary["legacy_pi_reported_only"])
        self.assertEqual(summary["target_lambda_bias"], -0.05)
        self.assertIn("legacy PI is reported for inspection", block)
        self.assertIn("i_state is near zero", block)

    def test_controller_topology_names_legacy_integrator_saturation(self):
        block, summary = format_controller_topology_signal(
            [8.0, 4.0, 2.0],
            fill_pct=80.0,
            pi={
                "target_fill": 55.0,
                "e_fill": 25.0,
                "integ_fill": 3.0,
                "kp": 0.85,
                "ki": 0.14,
                "max_step": 0.08,
            },
            stable_core={"enabled": False, "controller_mode": "current_runtime"},
        )

        self.assertEqual(
            summary["read"].split(" — ")[0],
            "legacy integrator saturation",
        )
        self.assertFalse(summary["legacy_pi_reported_only"])
        self.assertIn("i_state=3.00", block)
        self.assertIn("near its rail", block)


if __name__ == "__main__":
    unittest.main()
