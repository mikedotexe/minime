"""Co-regulation gift-exchange: aperture recipe + self-need derivation."""

import unittest

import autonomous_agent as aa


class CoRegulationTests(unittest.TestCase):
    def _agent(self):
        agent = object.__new__(aa.AutonomousAgent)
        # _derive_self_need reads stage via _shadow_runtime_state; stub empty.
        agent._shadow_runtime_state = lambda: {}
        return agent

    def test_build_aperture_recipe_is_jitter_mode_and_bounded(self):
        r = aa.AutonomousAgent._build_aperture_recipe()
        self.assertEqual(r["target_dims"], list(range(32)))
        self.assertEqual(r["blend_mode"], "aperture_jitter")
        self.assertGreater(r["amplitude"], 0.0)
        self.assertLessEqual(r["amplitude"], 0.4)
        self.assertGreater(r["jitter"], 0.0)
        self.assertLessEqual(r["jitter"], 0.2)
        # target_values are zeros (unused in jitter mode) — NOT a constant pull,
        # which would narrow Astrid rather than spread her.
        self.assertTrue(all(v == 0.0 for v in r["target_values"]))

    def test_derive_self_need_thresholds(self):
        agent = self._agent()
        # Low fill → density, safe to receive (fill < 68, not discharge).
        d = agent._derive_self_need({"fill_ratio": 0.40})
        self.assertEqual(d["need"], "density")
        self.assertTrue(d["safe_to_receive_density"])
        # High fill → aperture, NOT safe to receive density.
        a = agent._derive_self_need({"fill_ratio": 0.82})
        self.assertEqual(a["need"], "aperture")
        self.assertFalse(a["safe_to_receive_density"])
        # Mid fill → steady.
        s = agent._derive_self_need({"fill_ratio": 0.66})
        self.assertEqual(s["need"], "steady")

    def test_derive_self_need_discharge_blocks_density(self):
        agent = self._agent()
        agent._shadow_runtime_state = lambda: {
            "health": {"stable_core": {"stage": "discharge"}}
        }
        d = agent._derive_self_need({"fill_ratio": 0.50})
        # fill < 68 but discharge stage → unsafe to receive density.
        self.assertFalse(d["safe_to_receive_density"])


if __name__ == "__main__":
    unittest.main()
