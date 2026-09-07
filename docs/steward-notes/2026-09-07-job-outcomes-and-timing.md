# Durable job outcomes and phase timings

The September 7 timeout investigation found three successful generations among
four jobs labeled timeout. The deadline covered the whole action; the worker
continued writing after expiration, while its final result and artifact links
were discarded. Completion also depended on whether a status poll observed the
deadline first. This change preserves the deadline fact and the actual worker
outcome independently.

## Record contract

Existing top-level status values remain compatible with current readers.
`timeout` means the action exceeded its elapsed allowance; it does not claim that
the worker stopped or that nothing was saved. `deadline_at` and
`deadline_exceeded_at` identify the logical deadline; `deadline_observed_at`
identifies the observation. `completed_at` records eventual worker return.

`worker_status` distinguishes a worker that is still running from one that has
returned. A timed-out running worker remains active for admission and continuity
reconciliation. The `outcome` object retains the actual final status, summary,
error, artifact references, result path and digest, and a phase-timing snapshot.
Ordinary results use `result.txt`; results after deadline or cancellation use
`late_result.txt`. `retained_result_path` identifies the saved result in either
case. An action result is usually a summary with references to separately saved
writing, not a second copy of the generated text.

The store checks elapsed time while finishing as well as when polling. Store
transactions serialize threads, store instances, and processes; JSON and result
replacement is atomic. Identical finalization retries are idempotent; conflicting
retries cannot replace retained evidence. Queued cancellation cannot be reclaimed
by a worker. Cancellation of accepted work does not promise to reverse effects
that the action has already performed. Graceful shutdown still drains accepted
workers.

Legacy records remain readable and are not retroactively reconstructed. Stale
worker recovery checks whether the recorded process has actually exited instead
of treating a different PID as proof of failure.

## Worker evidence

Finalizer evidence belongs to the current worker's exact action ID and execution
context. Shared last-action scratch fields are not authoritative for job outcome.
An action failure remains failed even if continuity persistence also fails.
An unconfirmed finalizer is explicit; a normal Python return alone no longer
establishes completion. Full model queries that all return unusable output are
reported as `no_model_output`; successful fallback remains usable output.
Journal paths are retained even when a registration hook later fails.

## Timing interpretation

Each job has a bounded, content-free `phase_timings.json` checkpoint. Durations
use a monotonic clock and identify the job, action, thread, generation, and
provider attempt. Nested spans expose inclusive and exclusive durations so that
preparation, context assembly, requests, journal hooks, and action finalization
can be compared without adding nested durations twice. Dropped-record counts
make bounds visible.

The snapshot attached to job finalization necessarily precedes the completion of
the job-store write. The dedicated checkpoint includes the later completion of
that phase and the final worker timing scope. Interrupted scopes remain visibly
incomplete. Timing failures do not block accepted work. These measurements are
diagnostic; they do not change prompts, model choices, NEXT parsing, or controller
behavior.

## Integration

The source branch starts at `36998c6`. The separately prepared afterimages and
reading-feedback candidate also started at that revision and contains its own
runtime changes. Integrating that candidate later requires a merge and renewed
verification; copying its frozen `runtime.py` over this change would erase these
repairs. Its prepared environment instructions are not part of this tranche.

Validation and any live activation receipt are recorded separately. A source
commit by itself is not proof that the running process has loaded the change.

The final isolated validation passed 410 tests and 72 subtests across job-store,
worker, phase-timing, graceful lifecycle, continuity, inbox delivery, generation
recording, self-study, introspection, and fixture-boundary suites. Fixtures cover
cross-process races, a worker saving after its deadline, interrupted persistence,
and abrupt process exit with an unfinished phase checkpoint. Tests ran under the
existing kernel sandbox protecting the live workspaces and service endpoints.
