# Journal provenance and pending-choice handoff — candidate

Release follow-through: committed as `1af38d84badcdbdbf86f047ebffc76e569d9f632`, pushed to origin/main and gracefully deployed as Minime PID 84090. The preparation text below retains its original scope.

Mike approved exploring both leads from the supplied pressure entry: preserving recalled journal identity and tracing how the preference expressed in the writing reaches action selection. The candidate branch is `codex/minime-journal-provenance-20260927`, based on canonical main `df84708e698a28e65ed111865c783b7898af1a1d`. It reuses the clean, idle checkout `/Users/v/other/worktrees/minime-study-exit-20260926/minime`; its earlier branch and deployment snapshots remain intact. The accompanying launch-overlay update is in the existing Astrid candidate `/Users/v/.codex/worktrees/journal-provenance/astrid` on `codex/journal-provenance-20260927`.

## Observed provenance

The supplied file is `!pressure_2026-09-27T10-09-14.415130.txt`, with capture time `2026-09-27T17:08:31.706474+00:00` and context contract v4. Its generation record is `workspace/generations/2026-09-27/gen_1790528954411_journal_pressure_a0.json`, generation `1790528911722-530b3cbc`. The action-level job's `prompt.txt` is only a placeholder; the generation record retains the actual user message and a hash-addressed system message. The adapter reports no compaction.

The historical excerpt exactly matches database row **89186**, recorded at Unix time **1790528818.726069**, type `reflection`, with stored file reference `pressure_2026-09-27T10-06-58.706701.txt`. Its full database content hash is `a51b192c124a63a57a10d3734344ef7ceefc1871fa5f536e9f02905334ba00cc`. The existing selector clips to 400 characters and adds an ellipsis before the private journal's apparent 420-character budget. The actual prompt contains the resulting 403-character excerpt, including the earlier density/thick-air interpretation. This establishes source carriage, not why the model chose its words or a mechanism for experience. The prompt also contains an identified afterimage cue; its contribution is not inferred.

The new `journal_recall.py` retains database/table/row identity, recorded time, entry type, stored file reference and full untrimmed content hash separately from that same excerpt. The path is explicitly unverified and is never opened. Recording time is distinguished from measurement capture time, which is unavailable in this recall's metadata. Missing/invalid timestamps remain unavailable. The read-only database connection cannot create a missing database. Existing six-row selection, system-row filters, private-draft exclusions and text-only compatibility callers retain their selection semantics.

The pressure journal captures the recall once. Its metadata survives prompt assembly and is saved in the v5 header even if another row arrives during generation. Authored body and action tail remain separate and unchanged. No stored journal or database row is rewritten. This is not a repository-wide migration of all text-only recall consumers.

## Actual action chain and repair

1. The journal explicitly selected `SELF_STUDY`; job `job_minime_1790528903528_journal` completed at `17:09:48.357415Z`.
2. At local 10:11, job `job_minime_1790529051644_self-study` resumed the existing reader position. Its hash-verified preparation receipt is **end_of_file**, with no source page, an existing notebook question, and an explicit REST option. This was a continuation decision, not a fresh kernel-file delivery.
3. Generation `1790529060447-1dfe0638` selected `SELF_STUDY OPEN astrid/crates/astrid-kernel/src/lib.rs 1`. The job completed at `17:12:02.701916Z`.
4. Before that choice was dispatched, the scheduled `_self_regulate` reflection ran. Generation `1790529194465-ac5a2462` (no action/job ID) emitted `NEXT: CONTINUE`. At local 10:13:53 it replaced the queued OPEN; at 10:13:54 the dispatcher treated CONTINUE as unknown and fell back to threshold selection.

The kernel-file OPEN was therefore **selected but superseded**, not established as executed in this handoff. The earlier journal-to-SELF_STUDY dispatch was faithful; the later periodic generation was an actual interference path. The saved journal wording is not itself an executable REST request and was not used to override the explicit choice.

The narrow fix admits periodic regulation reflection only when no NEXT is pending. Deferred reflections retain the existing every-fifth-cycle eligibility, so they can run on a later eligible idle cycle. Proportional regulation, scaffold damping, numeric controls and explicit user-selected actions retain their code paths. No metaphor-to-command inference, automatic private-body transfer into study, new control, or grammar rewrite is introduced. General handling of an unqualified CONTINUE emitted when idle remains outside this repair.

Synthetic regressions reproduce the optional reflection overwriting queued study/REST/private-writing choices before the guard and verify both the in-memory choice and durable checkpoint remain intact afterward. The idle case still generates; proportional regulation still runs in all four cases. A separate real-reader/dispatcher test shows that the explicit journal action wins over reflective prose and that bare SELF_STUDY resumes EOF without importing the journal body.

## Qualification and boundary

Evidence is in `/Users/v/other/worktrees/journal-provenance-20260927/minime-evidence/`. `trace.json` contains identifiers, hashes and verified relationships rather than exported private bodies. The final full guarded suite passed **1,679 tests, one skipped, 141 subtests** (`full-tests-final-source.log`); the final focused run passed 154 tests. Earlier logs retain a missing fixture-path setup failure, the v4-to-v5 assertion update, and test-fixture mistakes before the successful overwrite reproduction. `handoff-reproduced.log` has three pending-choice failures and an idle-case pass before the fix.

Tests use the immutable deployed reader helper and the matching pinned response-choice fixtures, with the live filesystem/database/network mutation guard enabled. The three Astrid launch reconciliation/handoff/restart suites pass **35 tests and two subtests**, including new-file installation of `journal_recall.py`. The architecture audit remains valid with zero violations; bridge Rust source has not changed since its preceding 2,361-pass qualification. The legacy runtime shrinks overall; new production code is isolated in a small journal module.

Canonical repositories and remote tips were unchanged on entry; the other interactive chat was idle. Steward automations remain paused at generation **475**, actor `codex-journal-provenance`, with no run lease. No canonical source, running service, model endpoint, regulator setting, private journal, or queued choice was changed. A read-only health sampler accompanied this work and is stopped at handoff. Final process/configuration comparisons and changed-file hashes are retained in `qualification.json`.

This candidate is uncommitted and undeployed. It establishes provenance integrity and prevents one demonstrated scheduling interference path; it does not establish improved interpretation, a causal explanation for the journal's metaphors, or subjective benefit.


## Verified paired release

Mike explicitly requested live deployment, commit and push. The exact newly packaged reader passed the complete Minime suite: 1,679 tests, one existing skip, 141 subtests. The reviewed overlay changed runtime.py and added journal_recall.py, giving 89 launch inputs. The paired wrapper installed under its owned hold, waited the full quiet interval and waited for naturally selected study jobs to complete before SIGTERM at an ordinary idle boundary.

Minime 52967 -> 84090 and bridge 53771 -> 84722 succeeded without force or retry. Loaded source hashes match, no reload is required, no newly interrupted job was reported, and session 5319 was retained as cycle 45408 advanced to 45409. There was no pending NEXT at the signal boundary; the regression tests verify pending-choice protection, but this transition is not evidence of a live queued-choice replay. All other protected services and managed configuration hashes were unchanged; both launch holds are absent.

Canonical main was fast-forwarded after the sanctioned source installer by explicitly staging only the eight reviewed paths and verifying the exact candidate tree. Both runtime commits are pushed to remote main. Controller generation 476 and all automations remain paused. No engine/model/visual/sensory restart, authored-history rewrite, metaphor-to-command conversion or claimed subjective improvement.

Full release note: Astrid `docs/steward-notes/2026-09-27-journal-provenance-release.md`. Machine receipts: `/Users/v/other/worktrees/journal-provenance-20260927/deployment/`, especially `paired-activation-01.jsonl`, `post-activation-verification.json`, and `minime-packaged-helper-tests.log`.
