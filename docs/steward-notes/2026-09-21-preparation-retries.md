# Durable Preparation Retries

Candidate-only follow-through on the geometry and voluntary-continuity qualification.
The runtime now requires the existing action-event identity for shared source and
private-draft preparation. Python fetches a first-admission revision and calls Rust
`prepare_once`; exact retries retain the original input, conflicting retries fail,
and new deliberate choices are not deduplicated by their text.

Standalone explicit `StudyClient.prepare` callers retain compatibility when no
request ID is supplied; that legacy entry point is not advertised as idempotent.
Production `_run_shared_source_study` supplies the durable ID and refuses to prepare
or infer without one. The helper owns locking, validation, redo recovery and native
schema migration. No parallel Python parser or memory database was introduced.

Synthetic direct-call fixtures now supply an action event. The initial full suite
exposed 15 fixtures without it; those failures and their repair are documented in
the paired Astrid note. Focused follow-through and private-delivery tests pass.

Full paired evidence, final tests, release hashes and remaining activation gates:
`/Users/v/other/worktrees/voluntary-continuity-20260920/astrid/docs/steward-notes/2026-09-21-preparation-retry-qualification.md`.
No canonical source overwrite, restart, live migration, engine/model/sensory
change, git commit or automation resumption is part of this repair qualification.

## Release Validation

Fresh paired stage `bridge-stage-geometry-02` completed through Astrid's sanctioned
wrapper. Shared helper SHA-256:
`8f729416fa6ddead4c2235d002328c843626a4f8fdfbf3f037e3bbbc310daa75`.
Full Minime suite against that executable: 1,453 passed, one skipped, 136 subtests
passed in 48.17 seconds. Both-owner exact preparation retries and migrations from
the old live helper and prior candidate pass without duplicate questions or
overwriting newer draft/source formats. The immutable 84-file Python snapshot
and detailed receipts are in `geometry-paired-qualification-03` beside the stage.

Status remains `offline_checks_passed_not_activatable`: complete scheduler crash,
stop, mailbox and privacy qualification, then canonical launch/source reconciliation.
Do not replace the newer canonical visual service with this isolated tree's older
copy. No live subjective outcome is inferred from synthetic success.
