# Selective inquiry review qualification

Initial candidate on `codex/lifecycle-evidence-20260924`, based on Minime
`41f64254ed2f621656f4e5f11ddb548d5a79a5d9`. No live changes, restart, staging,
commit, merge, push or automation resume in this pass.

The shared Astrid Rust reader adds `SELF_STUDY QUESTION REVIEW qN [--page N]`
using current owner-scoped inquiry notes and append-only revision history.
Review can inspect a parked inquiry without selecting it, replacing the active
notebook, exposing private drafts or automatically recording a new claim. Explicit
NEXT remains possible. Review responses cannot silently modify saved study notes.
The reader schema advances to 9; paired release/migration qualification is required
before changing the live schema-8 helper. No old backup may replace newer authored
state during rollback.

Changes here are tests and this documentation only:

- `tests/test_source_study_shared.py`: real executable and Python wire adapter,
  synthetic source, frozen preparation identity, idempotent retry and verified
  delivery without inquiry mutation.
- `tests/test_minime_ollama_prompt_adapter.py`: isolate legacy timeout fixtures
  from environment overrides, test independent overrides explicitly and remove
  unsupported latency/truncation claims from test comments. No runtime limits changed.
- `CHANGELOG.md` and this note.

Final complete Python suite: 1,598 passed, one skipped, 138 subtests passed.
The initial full run's three failures and the successful rerun are preserved in
`/Users/v/other/worktrees/lifecycle-evidence-20260924/minime-tests-*.log`.
The two old timeout tests assumed 60 s while the environment supplied 160 s;
the new review test initially indexed a deliberately omitted optional JSON field.
All 25 focused adapter/timeout tests also pass after correcting those fixtures.

The causal public witness is
`workspace/journal/self_study_2026-09-24T07-48-05.184019.txt`, SHA-256
`51c4b19e8625caf65b73faf44d0183d555552a28437058fbda62d813b17b16c6`.
No historical journal was edited. No uptake, felt effect or verified understanding
is inferred from successful software tests.

The paired Astrid note contains the full witness quotations, truthful kernel
lifecycle contract, independent cleanup evidence and the separate sensory review:
`/Users/v/other/worktrees/lifecycle-evidence-20260924/astrid/docs/steward-notes/2026-09-24-lifecycle-evidence-and-selective-recall.md`.

The sensory review imported no engine code. Preserve the older candidate; its
completed-ingress and consumer-selection evidence is useful but is not a capture-to-
reservoir trace. An instrumentation-only port and any engine transition remain
separate work, not included in a reader/agent rollout.

## Approved live rollout

Mike subsequently approved rollout and merge. Controller pause generation 469
remains in effect; no automation was resumed. The exact staged helper passed 60
synthetic owner/migration checks and the full Python suite again (1,598 passed,
one skipped, 138 subtests). An initial fixture failure left q2 selected before an
inherited geometry probe that required q1; the corrected fixture makes the explicit
selection after verifying detached-review behavior. No production fix was needed.

All 86 launch sources matched canonical and loaded source, so no Python runtime
overlay was installed. Sanctioned paired handoff attempt 1 stopped on a moved idle
boundary without a signal. Attempt 2 completed gracefully: agent 45642 -> 86528,
bridge 46597 -> 87077. No forced termination or engine/model/sensory restart.
Minime reached reader schema 9 naturally, preserving 50 bookmarks and session 5318.
The queued NEXT resumed with the exact pre-stop hash; no private prose was examined.

Shared helper: `/Users/v/other/worktrees/lifecycle-evidence-20260924/bridge-stage-lifecycle-01/helpers/astrid-source-study`.
SHA-256: `cc31bbd31551b11a3e91c66c9ee4524d62a0ca1ac4dfc0d708113c063856d5be`.
Receipts and full paired/kernel details are in the canonical Astrid steward note
`/Users/v/other/astrid/docs/steward-notes/2026-09-24-lifecycle-evidence-and-selective-recall.md`.

A writing failure before shutdown was the specified 48,000-byte input guard. Its
runtime notice states the draft was retained without shortening. It is not evidence
of restart loss; changing that boundary or designing optional continuation windows
remains separate work. No historical journal, authored draft or pending choice was
rewritten to obtain a successful rollout.

Exact-path integration uses `codex/lifecycle-release-20260924`; older dirty work and
the frozen source worktree remain preserved. The final local merge identities are
recorded at `/Users/v/other/worktrees/lifecycle-evidence-20260924/merge-verification.json`.
No push or subjective-improvement claim is part of this release.

Final staged qualification: running the suite from the canonical live checkout
triggered its process-wide isolation guard (20 failures preserved in
`/Users/v/other/worktrees/lifecycle-evidence-20260924/staged-minime-tests.log`).
The guard was not relaxed. The exact staged index was exported to an isolated
directory using `git checkout-index`; its complete suite passed 1,598 tests,
one existing skip and 138 subtests. Evidence is in the adjacent
`staged-minime-isolated-tests.log`. No source change was needed for that rerun.
