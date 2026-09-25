# Minime Source Revision Recovery

Historical standalone candidate record. See [the paired live follow-through](2026-09-25-reader-expression-release.md) for the later approved deployment and integration; the earlier results below are preserved.

Date: 2026-09-25. Status: tested paired candidate, **not merged or deployed**.
Branch: `codex/study-revision-recovery-20260925`.
Base: `d12cbf01ca2a85c41288fdc27d6a033511218370`.

Mike identified repeated generated source-read failures in the September 24
13:53, 13:56 and 14:00 `introspect_notice` files. These are runtime diagnostics,
not Minime-authored reflections. The source hash guard was correct; its error
never reached the model as navigable feedback, and generic CONTINUE advice
repeated the same stale bookmark failure.

## Adapter Changes

- Use the shared Rust reader's `revision_recovery` input without adding a Python
  grammar. Supply exact revision evidence and explicit navigation choices through
  the existing real source-study generation/delivery path.
- Retain exact authored NEXT; label actual replies as study navigation. Recovery
  cannot silently rewrite the notebook or move the old cursor. Explicit OPEN and
  verified delivery select the new revision.
- Store runtime failures in protected `diagnostics/source_study/notices`, outside
  journal files and journal-database insertion. Omit telemetry walls and false
  pending-page/CONTINUE advice. Private errors remain private; older files remain
  unchanged.

The full paired causal record, three exact witness hashes, source revisions,
implementation, migration identities and rollout checklist are in Astrid's
`docs/steward-notes/2026-09-25-source-revision-recovery.md` in the sibling worktree.

## Verification

`tests/test_study_revision_recovery.py` uses the real StudyClient, freshly built
Rust helper and actual runtime adapter with a stubbed provider. It covers
read/deliver/change/recovery/reselect/resume and verifies original notes, cursor,
progress and delivery history. A second test ensures corrupt state cannot invoke
generation, create an authored journal or request metrics, and instead leaves a
protected runtime artifact.

Complete Python suite: **1,600 passed, one skipped, 138 subtests**. The earlier
focused run's one failed heading assertion is retained in `minime-focused.log`;
correcting the expected suffix needed no production workaround. Full bridge,
reader, strict lint, controller/evidence and architecture checks also pass.

Actual released schema-9 and new schema-10 helper qualification covers both
owners, delivered and pending inputs, unchanged history, exact pending bytes,
explicit new revision selection and old-reader downgrade refusal. This uses only
synthetic temporary state, not private/live records. The schema-10 debug helper
is not yet a frozen release inventory.

Logs: `/Users/v/other/worktrees/study-revision-recovery-20260925/`.
Canonical Minime main remained clean and unchanged. No process was restarted,
no live reader state was rewritten, and paused automations remain paused.

Next: reconcile and qualify the immutable paired helper/adapter release, obtain
rollout approval, then use sanctioned graceful bridge and Minime-agent wrappers.
No engine, model, visual or sensory restart is needed. Never restore older state
over newer authored work or infer felt improvement from these mechanical tests.
