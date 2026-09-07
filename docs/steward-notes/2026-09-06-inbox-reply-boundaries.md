# Bare inbox reply boundaries

Original source-only branch: `codex/minime-inbox-reply-boundaries`, based on
`a9f85f3c74c3d8e1c996c3689fe5aef696dacf27`. During that source-only review, no
deployment, inbox resend, historical reply recovery or runtime service control
was performed. The later authorized rollout is recorded at the end of this note.
The initial test isolation defect and its narrowly verified restoration are recorded below.

## Reviewed source foundation

The shared Minime checkout contained the already-developed sender-bound inbox,
quiet peer context, voluntary session bookmarks, journal provenance and graceful
agent lifecycle work. A branch from its committed HEAD alone would omit the
inbox implementation being repaired. Following explicit authorization, this
worktree imported exactly its 11 modified tracked paths and nine untracked
source/test paths; runtime data, configuration and ignored workspace files were
not copied. This foundation is preserved work, not authored by the parser repair.
Existing changelog deployment claims describe that earlier work.

[The foundation manifest](2026-09-06-inbox-reply-foundation.json) records every
imported file's byte length and SHA-256, source commit and original tracked status.
The baseline patch and byte-exact source snapshots are retained separately at
`/Users/v/.codex/artifacts/minime-inbox-reply-boundaries-20260906/foundation.patch`
and its `foundation/` sibling directory. Source status and all imported bytes were
rechecked unchanged before and after capture. The shared checkout was not edited.

## Repair

The old parser honored a bare `INBOX_REPLY` only on the first line. After ordinary
prose, a bare declaration therefore produced no addressed artifact. When it
followed a recognized reply block, its text was swallowed into the earlier
recipient's body. This repair treats every column-zero, unfenced declaration as
a boundary, whether it is bare or has a `NEXT:` prefix with or without spacing.
Only a unique
valid ID in the supplied inbox batch can route a nonempty body.

Invalid address declarations end the preceding reply and keep their own body out
of executable action/footer text. Quoted and indented examples remain prose;
Markdown fence length and marker matching prevent shorter or different fences
from prematurely exposing declarations. Body bytes and CRLF line endings are
preserved. A mixed generation remains intact in its separate archive; the final
native NEXT and ordinary preceding prose remain available to the existing action
caller.

The mailbox prompt shows an optional concrete example with a currently admitted
message ID. It does not create a reply obligation or change question/session
state. Long message IDs continue to use the existing envelope contract.

## Isolation and validation

The imported guarded inbox suite passed 47 tests before the repair. The repaired
focused inbox suite passes 69 tests, including a synthetic reproduction of the reported
three-paragraph opening, horizontal rule, long bare ID, two-paragraph human reply,
and `SHADOW_TRAJECTORY lambda-tail/lambda4` final action. No private source prose
was added to fixtures.

The first complete test run exposed six inherited continuity-fixture failures:
a temporary local store still discovered Astrid's live peer experiment through
hard-coded path defaults. It also appended nine synthetic correspondence rows
(10,450 bytes) to the shared `correspondence_v1.jsonl` ledger between
`2026-09-07T03:39:56.676Z` and `03:39:57.624Z`. The imported guard protected three
live checkout roots but omitted the sibling shared root; the two fake-inbox
tests reached the class-level shared path through legacy correspondence mirroring.
Exact temporary fixture paths, fixture body hashes, row hashes and timestamps
established ownership of these nine rows. An independent audit confirmed them.

The controller restored only that confirmed final suffix under a file lock,
after checking the complete file checksum, size and inode. All preceding
64,355,140 bytes were preserved exactly: their SHA-256 before and after was
`a4a38acf02ef2f192f0193b0e5c5a1d54800a2cd3252a32f650bd314928557f5`.
Older unrelated synthetic rows were left untouched. Whether the transient rows
were observed by another process is unknown. Private forensic evidence and the
restoration record are retained in
`/Users/v/.codex/artifacts/minime-inbox-reply-boundaries-20260906/` as
`shared-ledger-fixture-contamination.json` and `shared-ledger-restoration.json`.

The fixture now redirects module and class peer inbox/shared/research paths,
including definition-time review defaults. The process audit guard covers all
six live roots, the additional reservoir/relay ports, and subprocess commands
targeting live checkouts. Registry consumers use the checked-in seed copied to a
temporary workspace; status tests mock listener, process and service inspection.
Isolation decision tests exercise the guard without attempting live operations.

Final validation used a macOS kernel sandbox inherited by child processes. It
denies writes to all six live roots, reads of the live peer/local workspace and
shared directory, non-loopback outbound traffic, and live service ports. The
full suite passed **1,060 tests, one skipped, and 115 subtests** in 27.32 seconds.
The directly affected isolation/status/registry suite passed 65 tests separately.
Runtime behavior and the existing continuity assertions are unchanged.

Final command, run from the isolated worktree:

```sh
/usr/bin/sandbox-exec -f /Users/v/.codex/artifacts/astrid-addressed-human-replies-20260906/isolated-tests.sb env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

The artifact directory retains `final-full-suite.log` and
`final-fixture-suite.log`, as well as `repair.patch` against the captured source
foundation. The kernel profile is required for the recorded isolation guarantee;
the Python audit hook alone does not contain arbitrary child processes.

Oversize handling, open-question closure, sender migration and retrieving prior
messages by thread ID remain outside this repair.

## Authorized agent rollout

After the source-only review above, Mike authorized integration and deployment.
The canonical Minime checkout was advanced to
`63c1ab99abee7284df46e1532ce5f427c1b0fb21`, preserving the reviewed foundation.
Only `minime_autonomy/inbox_delivery.py` and `minime_autonomy/runtime.py` changed
among the agent's 70 startup inputs.

The sanctioned agent-only wrapper sent one SIGTERM to PID **36143** at
**2026-09-07T04:29:53.034638Z**, after a verified quiet boundary with no active
jobs or TCP connections. Its process start was `Fri Sep 4 23:00:37 2026` local.
Replacement PID **12456** started at `Sun Sep 6 21:30:44 2026` local. The reload
succeeded at **2026-09-07T04:32:26.607251Z**, with `agent_drain_v1`, normal
lifecycle activity and `reload_required=false`. No forced termination occurred;
the wrapper does not claim atomic traffic quiescence.

The pre-signal and post-ready continuity records match exactly: session **5316**,
cycle **24725**, no pending NEXT, and canonical state digest
`c90c35b5569242459a9847959240eeaf98fcce6c3c74580644cf87899e27b219`.
All 70 recorded source hashes equal both the running process's startup inventory
and current disk bytes. Managed launchd environment, rescue-profile and installed
plist hashes are unchanged. All **ten protected services** retained their PID and
process start across this Minime reload. Independent observations confirmed these
claims before the separately authorized Astrid bridge activation.

The model remained ready with a connected reservoir and no last generation
error. Post-reload engine telemetry advanced with finite fill, lambda1_rel and
geom_rel; the independent 04:32:19Z sample ranged **71.05–73.04% fill**. This is
runtime health evidence, not proof of a delivered human reply. No test letter,
inbox resend or synthetic live reply was used for this verification.

Inference reliability remains a separate follow-up. Two natural jobs finished
with `llm_job_timeout` while the wrapper waited for its quiet boundary, before
the signal. This parser repair does not claim to fix those timeouts.

The durable receipt is
`/Users/v/other/minime/workspace/runtime/deployments/2026-09-06-inbox-reply-boundaries/reload.jsonl`
(SHA-256 `ef5909892858e7277bfb1f803c78f33f11025bf3eb2ea0c872d4751fd161f425`).
Independent source/configuration/continuity/identity verification and the
read-only health samples are retained under
`/Users/v/.codex/artifacts/human-replies-rollout-20260906/`, including
`minime-independent-rollout-verification.json` and `minime-reload-success.json`.
