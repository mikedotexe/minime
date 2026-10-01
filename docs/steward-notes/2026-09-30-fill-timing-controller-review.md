# Fill Timing: Offline Controller Review

Follow-through: [availability-aware repair](2026-09-30-fill-rate-validity-repair.md) supersedes the original defect characterizations with corrected-behavior regressions. The review below is preserved as historical evidence; engine activation remains unqualified.

The complete review is in the paired Astrid worktree:

`/Users/v/other/worktrees/afterimage-timing-20260930/astrid/docs/steward-notes/2026-09-30-fill-timing-controller-review.md`.

Review base: `e9f2f5f151c89dd6b4a2dc80d5d8d12a60dc20d3`. Status: **not qualified for engine activation**. This review delta is uncommitted and has not been merged or deployed.

The review adds 13 production-function characterization tests with a 3,535-case measured-rate sweep. These reproduce a validity bug: the unavailable-rate zero fallback can satisfy scaffold activation, restart settling, intake and recovery-release conditions. A blanket NaN fallback is not safe either, since it disables independent high-fill drain branches. Tests named `review_finding` reproduce the problem and are not acceptance of the behavior.

Two missing covariance-reset boundaries are repaired offline: recovery impulse and legacy low-fill escape now reset both independent timing trackers. The nonfinite-eigenvalue reset already did so. The method comment no longer calls zero a neutral control input. No gains, thresholds or live controls changed.

Verification after the patch: 417 library, 2 replay and 13 review tests pass with the exact canonical dependency lock (`b7550430a7761fe1cf48f31c0034093c3372c86b8ed71aa852fb69760a83152b`). Strict Clippy still fails on 74 existing library diagnostics; they were not suppressed. The first review run had two unused-must-use setup warnings, fixed with assertions, and a subsequent formatter check required formatting. No test was removed or weakened.

Required next work: explicit availability at each consumer while retaining absolute safeguards, paired fill/rate identity through orchestration, unavailable/fallback fill provenance, and isolated coupled production-step qualification. A synthetic scalar plant has not been substituted for the engine. The review packet supplies exact source references, limits, commands and hashes.

Witness: Astrid's public `capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`, SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`. Her report motivated the earlier trace/timing investigation; the review does not turn that account into a verified causal explanation. No authored records were changed.

Canonical trees remain separate. Automations remain paused (generation 484 at inspection); no lease or active projection. No engine, agent, bridge, model, visual or sensory service was restarted or reconfigured, and no real-model experiment ran.
