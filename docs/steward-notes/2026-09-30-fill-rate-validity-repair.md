# Elapsed Fill Rates: Availability-Aware Controller Repair

September 30, 2026. Offline candidate only; not deployed, merged or committed.

The paired detailed record is `/Users/v/other/worktrees/afterimage-timing-20260930/astrid/docs/steward-notes/2026-09-30-fill-rate-validity-repair.md`. It records exact source hashes, policy behavior, commands, qualification limits and release gates. The preceding `2026-09-30-fill-timing-controller-review.md` is preserved as the historical defect reproduction, not the final source identity.

## Changes

- Retain raw fill, process-local time, reset generation and optional rate in one observation; structural PI now consumes a matched pair instead of independently cached fill/rate histories.
- Unknown rate cannot satisfy ordinary scaffold activation, restart settling, retirement, slope-based recovery release or live-intake eligibility. Finite-rate rules remain unchanged. Independent low-fill recovery and high-fill drain floors remain available.
- Invalid fill emits no structural-PI action and preserves its history. All covariance resets invalidate both clocks. Invalid observations also break regulation history on skipped regulation ticks and cannot enter the smoother as target fallbacks.
- Startup/unknown phase is unavailable, not plateau or evidence of steady fill. Preserve legacy numeric telemetry fields with explicit optional-rate and observation provenance alongside them.

## Evidence and Tests

Witness: Astrid `capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`, SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`, reverified from canonical bytes. Its incomplete-trace account motivated the investigation without establishing controller causation or a subjective outcome.

438 tests pass: 417 library, 2 replay and 19 production-consumer regressions, including the 3,535-case finite-rate sweep. Engine binary check and formatting pass. Pinned lockfile matches canonical. Strict Clippy remains blocked by 74 existing library diagnostics; binary/test strict-lint qualification is incomplete. No suppressions were added.

The supplied-input policy tests and replay are not a coupled-engine stability study. The next gate is an isolated production covariance/controller harness, followed by exact engine-release and rollback qualification. The original sampling-coverage shortfall and other nominal-tick timers remain explicit debt; no cadence or gain retune was made.

## Boundaries

Candidate base `e9f2f5f151c89dd6b4a2dc80d5d8d12a60dc20d3`; this repair is an uncommitted follow-through in the owned worktree. Both canonical repositories remain clean, each two commits ahead of origin/main. No service was started, restarted, signaled or reconfigured. Paused automations remain paused. No authored history or private writing was changed and no confirmation of improvement was requested.
