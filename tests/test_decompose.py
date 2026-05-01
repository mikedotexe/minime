"""Tests for DECOMPOSE formatting helpers."""

import unittest

from decompose_utils import (
    format_attrition_boundary_signal,
    format_controller_topology_signal,
    format_decompose_mode_sections,
    format_lambda_edge_trace_signal,
    format_pull_topology_signal,
)


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
