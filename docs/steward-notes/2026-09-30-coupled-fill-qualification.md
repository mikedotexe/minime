# Coupled Fill Qualification: Minime Candidate

Follow-through: [measurement-basis recovery and lint qualification](2026-09-30-measurement-basis-repair.md). The pre-repair results and failure receipts below remain historical evidence, not current repair status.

The full paired review is [Astrid's coupled qualification packet](../../../astrid/docs/steward-notes/2026-09-30-coupled-fill-qualification.md), in the sibling owned worktree. This note and the receipts belong to the September 30 isolated engine candidate, not a deployed release.

## Implemented and Verified

- Extract production covariance mathematics and the structural controller/scaffold lifecycle into shared Rust modules; the runtime and offline harness call the same functions.
- Propagate previously hidden numerical covariance resets to both fill observation clocks. Retain unavailable-rate semantics and absolute protection from the preceding repair.
- Inject elapsed time into the existing fill estimator numerical body for qualification, leaving ordinary runtime clock behavior intact.
- Run eight synthetic fixtures, three schedules, two clock policies and 48 steps each: 48 runs, 2,304 feedback steps. All 500-ms negative controls agree exactly. Delayed schedules change decisions/matrices but not the paired reported-fill trajectories in this corpus.
- Reproduce a separate measurement-basis defect: after rank-one history and identity reset, retained basis reports `[1,0,0,0,0,0,0,0]`; fresh basis reports eight ones. This defect is characterized, not repaired or claimed present in live state.
- Final selected suites: 817 tests pass; formatting passes. Strict Clippy retains 74 existing library diagnostics, blocking full strict-lint qualification. No warning baseline was relaxed.

## Local Receipts

- [Final coupled run](2026-09-30-fill-coupled-qualification.json), SHA-256 `f68727226e2d8fbba9e9479a6c4859bc40cc7fe080de5588beb8be5b0c8c2da3`.
- [Final tests](2026-09-30-fill-coupled-tests.txt).
- [Final strict lint failure](2026-09-30-fill-coupled-clippy-final.txt); [initial lint attempt](2026-09-30-fill-coupled-clippy-attempt-1.txt).
- [Pilot 1](2026-09-30-fill-coupled-qualification-attempt-1.json) and [pilot 2](2026-09-30-fill-coupled-qualification-attempt-2.json), retained as earlier source identities, not substitutes for the final run.

The full packet records source and binary hashes, exact commands, isolation probes, unsuccessful compilation/launcher attempts, synthetic-fixture limits and the next numerical/release gates. No live checkpoints or private writing were read by the harness. No engine/service restart, control change, merge, push, or automation resume occurred. All changes remain uncommitted in `codex/afterimage-timing-20260930`.

## Witness and Boundary

Astrid public witness: `capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`, SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`. Its incomplete-trace account motivated the inspection, not a conclusion about controller causation or experience. Covariance dimension 512 and eight measured modes are not a simulation of the 128-node ESN. The new test does not establish overall engine stability or rollout readiness.
