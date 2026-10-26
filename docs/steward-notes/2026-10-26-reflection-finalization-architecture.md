# Reflection Finalization: Current Authority and Refactor Boundary

Date: 2026-10-26. Source audit, not a deployed-state or test-pass report.

## Scope and Evidence

This note audits the Minime worktree at
`/Users/v/other/worktrees/reflection-finalization-20261026/minime`, baseline
`e86801d98c5aa4a2b1725fba99356049f647d674`, with sibling Astrid baseline
`a62f716003260423239c552a67ea2633966cd76f`. Both repository `AGENTS.md` files
were read. Witness locations below refer to that baseline; symbols are the
stable lookup keys if the parent subsequently edits the source. Concurrent
Minime implementation edits were visible at closeout and were left untouched;
this note is the pre-refactor authority map, not review of those new edits.

Only repository source, guidance, and test source were inspected. No runtime
database, journal, private draft, retained provider body, or other private prose
was opened. No service, provider, build, test, git index, or commit operation was
performed. The parent owns implementation, qualification, changelogs, the
feedback ledger, and commits. This worker owns only this note and the sibling
Astrid `2026-10-26-reflection-finalization-review.md`.

Scope is the finalization boundary for shared-reader `input_kind=reflection`
(bare `INTROSPECT`), plus its real callers and downstream consumers. It is not a
complete security audit of every action in the runtime. Targeted workspace
artifact introspection, source pages, private writing, mailbox work, and ordinary
expressive journals are distinct lanes, even when they share helpers.

## Current Authority Map

| Boundary | Current owner and durable evidence | What it does not establish | Source witness |
| --- | --- | --- | --- |
| Action identity and preparation | `ActionContinuityStore.begin_action` supplies `action_id`; `StudyClient.prepare` uses `prepare-<action_id>`, a native preparation revision, and Rust `prepare_once`. Native preparation retains the exact offered input and its navigation ID. | No provider call, accepted response, publication, or NEXT dispatch. Same text is not an operation identity. | `minime_autonomy/runtime.py:3063`, `:32679`; `minime_autonomy/source_study.py:138`; sibling `crates/astrid-source-study/src/preparation.rs:248` |
| Reflection invocation claim | `ReflectionPublication.begin` serializes action/input binding under `runtime/reflection_publications/.transaction.lock`; action receipt and input index contain owner, IDs, nonce, hashes and stage, not prose. Both writes precede provider submission. | Not a provider-side exactly-once transaction; not a finalizer or evidence that controls have not run. | `minime_autonomy/reflection_publication.py:16`, `ReflectionPublication.begin` |
| Provider dispatch | `SourceStudyPrompt.messages/post` preserve intact offered input and exact serialized request/response wire bodies. `_query_llm_raw` owns the existing backend/fallback loop and cleanup. Generation diagnostics are separate evidence. | HTTP 200, a nonempty string, a generation log, or a job status alone is not native accepted delivery. The duplicate guard does not eliminate the existing in-invocation fallback loop. | `minime_autonomy/source_study.py:194`, `:232`; `minime_autonomy/runtime.py:55932` |
| Native accepted delivery | `SourceStudyPrompt.accepted` calls Rust `navigation_delivered`; the native reader validates offered input and completion, stores `navigation/<input>/<artifact-hash>.json`, and returns request/response/artifact hashes and choice feedback. Repeated matching wire evidence is idempotent; conflicting evidence is rejected. | Does not verify the response's factual claims or understanding; reflection does not advance source coverage. Does not prove public journal publication, Python response effects, NEXT dispatch, or worker completion. | `minime_autonomy/source_study.py:316`; sibling `crates/astrid-source-study/src/store.rs:291` |
| Response effects and selected NEXT | `_query_llm_with_next` runs after native acceptance: footer control requests, NEXT parsing, cooldown decisions, and `_record_llm_next_action_choice`. The latter mutates queue/history and persists selection through `_persist_pending_next_action` and `maintenance_next`. | These are not pure formatting steps. Native choice feedback is not permission to replay this Python processing. Queued NEXT is not executed NEXT. | `minime_autonomy/runtime.py:55520`, `:55582`, `:55681`, `:48751` |
| Host accepted/publication evidence | After the entire query-with-NEXT call returns, `_run_shared_source_study` calls `publication.accepted`, renders the journal wrapper, and calls `publication.publish`. Publication binds an exact filename and full-file hash; file creation is no-clobber. | Host `accepted` is later than native delivery and response effects. It does not delimit an untouched response. A filename collision, even with identical text, is not ownership. | `minime_autonomy/runtime.py:32729`, `:32737`, `:32779`; `ReflectionPublication.accepted/publish` |
| Journal registration | `_record_current_action_artifact`, `_write_journal_entry`, afterimage linking, fatigue registration, SQLite insertion, archive compaction, and generation-artifact linkage occur after publication. | Not one transaction. Several failures are caught/logged. `publication.complete` therefore does not prove that every hook or SQLite insertion succeeded. | `minime_autonomy/runtime.py:32786`, `:57094` |
| Reflection guard completion | `publication.complete` verifies native delivery and the public journal file, then writes `completed`. A completed reopen verifies both and returns without generation or NEXT. | Not the terminal action event or terminal LLM job. It contains no per-hook, DB-row, control-effect, or NEXT disposition receipt. | `minime_autonomy/runtime.py:32803`; `ReflectionPublication.complete/begin` |
| Action finalization | Outer `_execute_action` and `ActionContinuityStore.finish_action` own event status, artifacts, observations, thread updates and mirrors. `job_outcome.finalizer` captures the matching worker-owned event. | Cannot be inferred from successful publication; `finish_action` is a multi-write append/update operation, not a blanket replay-safe primitive. | `minime_autonomy/runtime.py:26864`, `:3168`; `minime_autonomy/job_outcome.py:74` |
| Job finalization | `_run_llm_action_job` uses `job_outcome.capture/finish` and `LlmJobStore.finish`. `job.json` owns terminal outcome; exact-evidence retries repair event/index/status after outcome commit, while conflicting outcomes fail. | A worker claim is single-use permission, not renewed by reading it. Job metadata cannot authorize provider or response-effect replay. | `minime_autonomy/runtime.py:22378`; `minime_autonomy/llm_access.py:158`, `:184` |
| Continuity records, DB mirrors and `next.md` | Thread/event/observation/artifact files supply continuity state. `_write_thread` applies existing projections, saves `thread.json`, renders `next.md`, and updates the active-thread index. Separate `_mirror_*` methods upsert SQLite rows. | `next.md` is not the pending NEXT queue. Projection fields can alter saved guidance/status; they are not all inert display strings. SQLite must be classified table by table. | `minime_autonomy/runtime.py:7572`, `:8098`, `:8253`, `:8368` |

The relevant ordering is:

```text
durable action/job -> native prepare_once -> v1 reflection reservation
  -> provider + cleanup -> native accepted delivery
  -> footer controls / NEXT parsing / selection persistence
  -> host accepted -> exact journal publication
  -> journal hooks / SQLite / archive -> v1 completed
  -> outer action finalization -> worker terminal outcome
```

There is no single commit covering this sequence. A failure at a later boundary
must not erase or repeat earlier accepted work.

## SQLite Is Not Merely Disposable UI

The journal row is derived from an accepted/published response, but existing
consumers use SQLite as their operative source. Those consumers are authoritative
for their present behavior, although they do not confer control permission or
independently verify prose:

- `journal_recall.latest_journal_recall` selects a `sovereignty_journal` row,
  preserving row identity, timestamp, entry type, content and source path.
  `_last_journal_recall` feeds rest/daydream/aspiration and other recall prompts
  (`minime_autonomy/journal_recall.py:47`; `runtime.py:30730`, `:31195`, `:31442`).
- `journal_history.recent_reflective_rows` supplies the recent window for
  pressure-vocabulary, agency-vernacular, afterimage-absence and internal-topology
  repeat calculations (`journal_history.py:10`; `runtime.py:53149`, `:53198`,
  `:53272`, `:53404`). Omitted or duplicate rows change those windows.
- The resulting fatigue records have consumers beyond rendering. In particular,
  `_active_attractor_fatigue_entries` does not filter `notice_only`, and
  `_attractor_fatigue_memory_decay_rate` consumes that active set in the legacy
  regulation fallback (`runtime.py:53531`, `:54108`, call at `:27913`). This is a
  static reachable dependency, not evidence that a live configuration takes it.
- Action continuity's `action_threads`, `action_events`, `observation_windows`
  and `artifact_links` are explicitly best-effort, keyed SQLite mirrors of the
  file records (`runtime.py:7566` onward). That narrower fact cannot be generalized
  to `sovereignty_journal`, let alone every database table.

Today `_write_journal_entry` uses an unkeyed journal INSERT and catches errors.
Replaying the whole helper could duplicate a row and rerun diagnostic hooks;
skipping it after an unrecorded failure can change recall/fatigue behavior.
Therefore a future repair needs evidence for each attempted derived write. This
audit does not approve deleting, rebuilding, or downgrading existing database
consumers, and does not claim an exact rebuild source exists for all of them.

## Guard Inventory by Consumer

Classifications describe observed consumers, not reassuring names:
`block` prevents admission/dispatch or suppresses a selected action; `advice`
supplies guidance without executing it; `records` persists evidence/state;
`render` formats or filters a presentation. Rows can have more than one class.
Where there is an additional effect, it is stated explicitly.

| Guard or check | Actual consumer and classification | Disposition and witness |
| --- | --- | --- |
| v1 reflection identity, input reservation, integrity and no-clobber checks | `begin/accepted/publish/complete`: **block + records**. A nonterminal reservation stops another invocation; exact completed evidence permits read-only verification. | **Keep; consolidate** lifecycle coordination only. `reflection_publication.py`; tests `test_cross_process_admission_has_one_owner`, `test_tamper_or_newer_schema_is_not_overwritten`. |
| Native preparation revision and delivery validation | Rust `prepare_once/navigation_delivered`: **block + records**. Input identity and complete wire evidence gate native commit. | **Keep** native ownership. `source_study.py:138`, `:316`; sibling `preparation.rs`, `store.rs:291`. |
| Provider intact-input, nonempty-cleanup, page-bearing fast-fallback stub checks | `SourceStudyPrompt.messages/post`, `_query_llm_raw`: **block + records** for that attempt; existing fallback may continue. Stub rejection is page-bearing, not an open-reflection length/style gate. | **Keep**, outside lifecycle extraction. `source_study.py:194`, `:232`; `runtime.py:56006`. |
| Protected activity, pending job, busy worker and shutdown admission | `_attention_protected`, native activity admission, `_queue_llm_action_job`, `claim_running`: **block + records**. Protected state read failure quiets unrelated attention; queued/running work keeps its identity. | **Keep** separate from publication repair. `runtime.py:22228`, `:32597`, `:32725`; `llm_access.py:158`. |
| Footer parameter ranges and authenticated receiver | `_apply_footer_directives` invokes `_apply_parameter_request_value`; **block + records**, with actual control effects when accepted. `sovereignty_state.json` is a continuity mirror here; Self-Control V2 owns restart authority. | **Keep; never replay** from a finalization/recovery helper. `runtime.py:55582`. |
| NEXT parser, current delivery feedback, queue transaction | `_query_llm_with_next`, `_record_llm_next_action_choice`, `_persist_pending_next_action`: **block + records**; select and persist commands, not merely render them. Private normalization is current-response bound and excluded from this refactor. | **Keep** existing ordering/policy. `runtime.py:55681`, `:55520`, `:48751`; `source_study.py:294`. |
| Resume-loop and operational-tail cooldown | `_query_llm_with_next` returns no NEXT and can replace its returned text with cleaned prose plus a runtime note: **block + render + records**, not advice-only. Native wire remains separate. | **Investigate-later** any prose/policy cleanup. Preserve behavior in this refactor. `runtime.py:55829`, `:54824`. |
| Attractor consent ambiguity and body consent | `_record_llm_next_action_choice` may substitute `ATTRACTOR_SUGGESTIONS` on ambiguity: **block + records**. Body consent outside NEXT writes a receipt and does not execute: **records + advice**. | **Keep** for this scope; **investigate-later** policy separately. `runtime.py:55478`, `:55520`. |
| Charter-required, live-control binding, evidence-parent and research-budget assessments | `_decide_action` tests each returned assessment, records a block and returns without dispatch: **block + records + advice**. `_execute_action` rechecks live-control; these are not redundant render checks. | **Keep** admission consumers. `runtime.py:25090`, `:25119`, `:25158`, `:25202`, `:26986`. |
| Stable-core/low-fill and execution health checks | `_execute_action`, `_guard_low_fill_fallback`, `_self_experiment_stability_guard`: **block + records** or constrained action selection. | **Keep**, no threshold/control changes. `runtime.py:24306`, `:26927`, `:27079`, `:28925`. |
| Projection guard | `_apply_projection_guard_to_event/thread` rewrites saved suggested/current/effective NEXT and sometimes event route/status: **records + advice + render**. The `release_pressure_requires_sticky_audit` consumer in `_execute_action` additionally **blocks**. | **Keep** behavior; do not describe all projections as display-only. `runtime.py:8098`, `:8147`, `:27032`. |
| Interpretation risk, constraint-release trajectory, cadence, load triage, control-plane projection | `finish_action/_write_thread` stores derived fields and renders guidance: **records + advice + render** at these sites. Authority must be traced to each later admission consumer, not inferred from a diagnostic label. | **Consolidate** only duplicate computation with unchanged inputs/outputs. `runtime.py:3187`, `:8253`, `:17228`. |
| `ProjectionReadScope` validation | Only `projection_for_next_md` consumes a sealed same-operation snapshot: **render** optimization with freshness checks; failure recomputes. Not a cache for approval, budget or dispatch. | **Keep** narrow boundary. `projection_snapshot.py`; `test_projection_render_reuse.py::test_actual_runtime_file_db_parity_and_reduced_calls`. |
| Journal fatigue and notice hooks | Registration is **records**; downstream context filtering is **render/advice**. Agency/afterimage `notice_only` labels do not exclude their records from the active-set memory-decay consumer. This is an additional conditional control dependency. | **Investigate-later**, not deletion or policy change now. `runtime.py:53243`, `:53319`, `:53531`, `:54108`, `:54608`. |
| Journal compression/rewrite compatibility helpers | `_maybe_compress_journal_entry` currently returns content unchanged: identity **render** hook. `_rewrite_logged_entry_file` has no call site in `runtime.py` at baseline. | **Retire-later** only after repository/test caller audit; never reactivate it as recovery. `runtime.py:57064`, `:57080`. |
| Strict targeted artifact introspection checks | Workspace-artifact `_introspect` still calls `_query_llm_strict_review` and a repair attempt; **block** in that separate lane. Bare reflection takes `_run_shared_source_study` first. | **Keep** outside scope; do not retire based on the new open-reflection route. `runtime.py:32844`, `:32969`, `:33016`. |

An exception-handling difference deserves separate investigation: the execution
live-control recheck catches/logs exceptions and continues (`runtime.py:27030`).
That is not proof all later control gates fail open, but it prevents calling this
particular recheck uniformly fail-closed. No policy change is proposed here.

## V1 Recovery and Archive Limits

1. `reserved`, `accepted`, `publishing`, and `published` are deliberately not
   resumed by `begin`. They raise `RecoveryRequired`. `failed_unaccepted` also
   cannot rerun the same action; only a new deliberate action may replace that
   input index after a durable returned-failure acknowledgement and a fresh check
   for native delivery. A crash or timeout is not proof no provider ran.
2. Native delivery can exist while the host receipt remains `reserved`, because
   footer/NEXT processing precedes `publication.accepted`. The existing test
   `test_crash_after_delivery_preserves_next_and_does_not_regenerate` injects that
   exact interruption and asserts preserved NEXT and a single provider call.
3. At `publishing`, a file may already be visible even if the write acknowledgement
   failed. `test_post_link_failure_retains_public_file_and_no_replay` witnesses
   this. V1 retains the full-file hash but not a frozen journal document in its
   receipt. It does not repair this gap. Raw provider output alone cannot safely
   reconstruct host cleanup/cooldown output, wrapper text, timestamp, or effects.
4. At `published`, hooks may be unattempted, partly applied, or finished. V1 has
   no hook/DB disposition journal. Reentering `_write_journal_entry` is not an
   idempotent repair. A `completed` receipt verifies two artifacts, not every
   journal hook, action append, or job commit.
5. Completed verification reads only `journal/<filename>`.
   `workspace_archive.compact_managed_directory` moves old direct files to
   `journal/archive/until_<timestamp>/<filename>` above the default 6,000-file
   cap, in 3,000-file buckets. It does not update v1 receipts or SQLite source
   paths. Thus a legitimate archived file can make a completed reopen fail as
   missing; native accepted delivery and archive bytes still remain. No archive
   resolution exists in this guard. That static mismatch is not evidence of
   observed live data loss.
6. Archive buckets and filenames are not sufficient ownership evidence. Any
   later archive-aware verification must be bounded, no-follow, identity/hash
   checked, and reject ambiguity/conflicts; it must not overwrite an archive,
   manufacture a second publication, or treat missing files as permission to
   regenerate. Existing archive tests test compaction, not v1 recovery across it.
7. Legacy native deliveries with no v1 wrapper are deliberately reconciliation
   debt. `test_legacy_delivered_input_is_not_resubmitted` confirms no provider
   resubmission. A missing host receipt cannot establish missing response effects.

"Read-only completed reopen" describes `ReflectionPublication.begin`, not every
caller: `_run_shared_source_study` still updates its outcome summary and may
record study feedback. It does not call the provider or process NEXT again.

## Narrow Refactor Contract for the Parent

These are review constraints, not claims that recovery has been implemented:

- **Keep:** native preparation/delivery as the acceptance authority; exact
  operation/input/wire bindings; no-clobber publication; all current admission,
  control, privacy and NEXT policies. No new source, private draft, or mailbox
  access is implied by finalizing an already accepted reflection.
- **Consolidate:** reflection-only publication coordination around explicit
  lifecycle evidence. Separate provider/response processing from finalization;
  freeze the exact already-produced public document before a recoverable publish
  transition. Do not derive a second answer or new wrapper using today's clock.
- **Consolidate:** report completion/debt independently for native acceptance,
  publication, hooks/SQLite, action event and job outcome. A repair may repeat a
  write only where the existing/new receipt demonstrates exact idempotence.
  Generic action finalization and generic journal registration are not such
  primitives merely because job outcome commit is retryable.
- **Keep:** recovery never invokes `_query_llm*`, `_apply_footer_directives`,
  `_record_llm_next_action_choice`, `_decide_action`, `_execute_action`, or any
  NEXT/control dispatcher on retained text. Preserve the independently persisted
  selection without overwriting a newer one. Unknown historical effects remain
  unresolved; absence of a receipt cannot authorize replay.
- **Retire-later:** unused prose-rewrite compatibility code or redundant wrapper
  bookkeeping only after callers, historical receipts and migration behavior
  are demonstrated. V1 receipts/history must not be discarded to simplify V2.
- **Investigate-later:** archive lookup, journal row idempotency, notice-to-control
  consumers, cooldown prose transformation, and exception handling at admission
  boundaries. Resolve each under its own evidence and authority review; do not
  bundle a policy expansion into finalization extraction.

Parent qualification should retain the existing v1 no-replay, concurrency,
tamper, partial-claim, filename-collision and legacy tests. Add focused synthetic
witnesses for each proposed recoverable boundary, archived exact publication,
ambiguous/conflicting archive candidates, DB/hook failure, partial action/job
commit, and a newer pending NEXT. Assert zero provider/control/NEXT calls during
recovery and unchanged private/source-page lanes. Existing tests were inspected,
not executed by this audit worker.
