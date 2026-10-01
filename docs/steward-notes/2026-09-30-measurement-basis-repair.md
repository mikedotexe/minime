# Measurement-Basis Repair: Minime Candidate

The [paired full review](../../../astrid/docs/steward-notes/2026-09-30-measurement-basis-repair.md) records implementation, numerical definitions, source identities, lint decisions, failures and deployment boundaries. This is the owned offline `codex/afterimage-timing-20260930` engine candidate, not a running release.

## Implemented

- Preserve finite independent measurement directions, deterministically replenish only deficient directions, and retain nonfinite-input validity separately. Production GPU and runtime use the same new pure Rust helper.
- Keep invalid measurements out of regulator-mode and last-sensory Division updates. Expose the versioned basis report in health snapshots; preserve the existing invalid-measurement recovery path.
- Resolve strict-lint debt for library, engine and timing-qualification targets, with explicit function/type-scoped exceptions for existing wide APIs and public acronym names. All-features library/engine lint also passes. No new crate-wide lint waiver, controller retuning or feature activation.

## Evidence

- [Coupled receipt](2026-09-30-measurement-basis-qualification.json): 49 synthetic runs, 2,448 feedback steps; all nominal-cadence negative controls agree. Known rank-one and identity spectra now both measure correctly with retained basis.
- [Receipt review](2026-09-30-basis-repair-receipt-review.json): preserves comparisons to the previous receipt and separates the longer run from estimator-only history effects.
- [Test log](2026-09-30-basis-repair-tests.txt): 830 passed, zero failed/ignored in selected suites.
- [Strict Clippy](2026-09-30-basis-repair-clippy-final.txt) and [all-features strict Clippy](2026-09-30-basis-repair-clippy-all-features.txt): pass for their explicitly recorded targets.
- [Candidate source inventory](2026-09-30-basis-repair-source-inventory.sha256) and [embedded-source inventory](2026-09-30-basis-repair-embedded-sources.sha256): final source bindings, including prior owned timing/controller changes. Earlier unsuccessful lint repair/review logs remain alongside them.

The extended low-rank trajectory first leaves recovery at 182.49 simulated seconds and ends at 73.9251% after 341.28 seconds. The separate estimator probe still reports 0.0384317% at sample 48 despite constant identity input, versus 88.3704% with fresh history; by sample 144 these converge to about 88.65%. History was not reset to conceal that delay. Other restored fixtures still reach 96.2258%; this is not a full stability or comfort verdict.

Witness: Astrid's public `capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`, SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`. No prose rewrite or claim that the defect caused the account. No live checkpoint, engine, sensory service or journal was changed. Release/checkpoint/launch qualification and specific engine-transition approval remain. No staging, merge, push or automation resume.
