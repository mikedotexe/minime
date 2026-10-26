# Recoverable Reflection Finalization

## Boundary

Offline candidate based on local main
`e86801d98c5aa4a2b1725fba99356049f647d674`. The separately committed
architecture review maps both runtimes; this implementation changes only
Minime's open-reflection finalization. Astrid's changes are documentation and
operator compatibility tooling. No live activation, push or tag is authorized
by this report. Providers, engine, framing, leak, capacity and paused automations
remain unchanged.

Public witness: `introspect_2026-10-25T19-21-15.154157.txt`, SHA-256
`836cc14d0528ebd4c4bd4910c3e435ca9989a6a9fe44d9ec34f94a936e3fb2cd`.
The earlier public integrity audit established that the splice already existed
in retained provider output. This refactor does not explain or rewrite it.
Its motivating adapter defect was independently reproduced duplicate publication
and the v1 guard's incomplete local recovery. All new fault and continuity
fixtures use synthetic prose and stores, never private writing.

## One Local Owner

`ReflectionPublication` now owns publication and its repairable SQLite index.
The generic source-study branch no longer calls separate reflection
`accepted`, `publish`, journal-registration and `complete` operations. Instead
it passes the normal response-handler result to one finalizer. The first-run
diagnostic callbacks remain explicit; they are never replayed by recovery.

Native reader delivery still owns accepted input/output evidence. Public journal
files own published writing. The existing queue owns pending NEXT. Job/action
records retain their historical outcomes. A local recovery receipt adds linked
evidence; it does not rewrite a failed job as an earlier success.

Before publication, a version-two immutable intent freezes exact final public
bytes, destination, native delivery hashes, original index metadata, a digest
of loaded implementation inputs and the observed choice disposition. This is
not raw provider wire or hidden reasoning. Identity/checksum validation and the
existing pinned owner-scoped filesystem lock protect publication and recovery.
No lock is held across inference.

The database adds only nullable `publication_id` and a partial unique index.
Historical rows remain unchanged; content equality never deduplicates unrelated
writing. Existing same-path or same-identity conflicting rows remain untouched.
The finalizer verifies index structure, exact inserted values and database
identity before committing. Hook or database failure does not invalidate an
already verified public file or invite another generation.

## Recovery and Limits

- Startup scans unfinished v2 receipts; action re-entry uses the same finalizer.
  Neither path reconstructs prompts, calls a provider, changes attention budgets,
  invokes the generic response handler or selects another activity.
- Matching live, starred or supported archived publications are recognized by
  exact name and bytes. Published files that are missing, changed or ambiguous
  are not silently recreated. Only a complete previously sealed intent in the
  pre-publication phase authorizes a missing public-file write.
- A saved choice is evidence of its original disposition, not current execution
  eligibility. Recovery leaves the current queue byte-exact, even when consumed,
  superseded or uncertain. The authored choice remains in frozen public bytes.
- Native evidence without complete frozen publication intent remains unresolved.
  Evidence presence alone is not reported as verified acceptance. V1 receipts
  remain byte-exact and are not upgraded or assigned invented index outcomes.
- Hooks interrupted after starting are not replayed. Missing diagnostic effects
  remain explicit. Broader notice/control policy changes are separate work.
- `scripts/reconcile_reflection.py --workspace <root> --action-id <id>` defaults
  to content-free read-only preview. Index inspection requires explicit
  `--database`; `--apply` requires that exact bound database and can only complete
  verified local writes. An incomplete application returns nonzero.
- Preview does not create SQLite WAL/shared-memory files. An active side-file
  database is reported as unavailable for passive index inspection; a stable,
  side-file-free database is read immutably. Application uses normal transactions.

## Subtraction, Not a New Framework

Publication/index completion decisions move from two coordinating owners
(generic study orchestration and the publication guard) into the existing
publication component. The old reflection-specific branches and four-step host
orchestration are removed. Native acceptance, queue persistence and outer
job/action completion deliberately remain distinct owners.

This is not a net source-line reduction: explicit recovery and verification add
code and tests. The simplification claim is narrower: one local finalization
entry point, no replay of a broad journal writer, one keyed index row, and
automatic completion of evidence-supported local steps. No general workflow
framework, new memory system or runtime policy layer was added.

Qualification results and exact release identities are recorded in the sibling
Astrid `2026-10-26-reflection-finalization-qualification.md` and the retained
`reflection-finalization-20261026` evidence directory. Failed attempts are retained,
not replaced by the final successful run.
