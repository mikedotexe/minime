# Main and live-runtime handoff — September 7, 2026

The canonical checkout is `/Users/v/other/minime`, with `origin` pointing to
`git@github.com:mikedotexe/minime.git`. The main-branch reconciliation preserves
the complete live branch history, including the inbox repair, generation
records, truthful job outcomes, and continuity performance correction through
`0a2832349e8acbd19fd354329c0ec4e34b73b4eb`.

## Verified live state

At handoff, Python PID 14108 was running the corrected source. All 76 loaded
source inputs matched the canonical files, with `reload_required=false`.
Moving Git references and preserving documentation does not change those source
bytes or require another restart. Recheck current process identity before any
later deployment; the PID recorded here is evidence, not a future target.

The full isolated suite passed 1,212 tests and 126 subtests, with one skip. The
first corrected natural self-study completed with intact artifacts and no
deadline or timing-record errors: 137.032 seconds total, including 101.143 seconds
of provider time and 24.316 seconds of continuity finalization. The comparable
first-rollout self-study took 283.765 seconds total and 93.397 seconds to finalize.
This is an observed pair, not an identical replay or long-run distribution.

The job metadata cache now fits the observed 23,555-job working history within
64 MiB per root and a shared 128 MiB bound. Every snapshot checks current file
signatures. Further history growth can again exceed the cache budget; it must
not be addressed by silently dropping old jobs or assuming a stale index is
authoritative. See [implementation notes](2026-09-07-continuity-performance.md).

Full validation and live receipts are preserved locally under
`/Users/v/.codex/artifacts/minime-continuity-performance-20260907/`, with the
completed account in `rollout.md`.

## Pending work remains distinct

The [afterimages evidence packet](2026-09-07-afterimages-rollout-evidence.md) is a
historical preactivation proposal, preserved without changing its original text.
Committing that document does not activate its source candidate or deliver it
as a message. Its statement that separate generation-record changes remain
disabled predates the subsequent generation-record rollout; it is not the
current status of Minime's live generation records.

The candidate copies are under
`/Users/v/other/worktrees/afterimages-reading-release-20260907/{astrid,minime}`;
their changes remain separate, unactivated working patches. The Minime copy
started at `36998c6`, before the outcome and performance repairs. Its preparation
instructions also predate the live generation-record rollout.

The afterimages candidate must be merged against the current main branch and
verified before activation. Copying an older staged `runtime.py` into this
checkout would erase the later outcome and performance repairs. Astrid's
canonical checkout is `/Users/v/other/astrid`; its handoff note records the
selected live stage and separate pending source candidates.

## Shared-checkout handoff

The cooperative steward is deliberately paused for the next agent under
`codex-astra-interactive`, pause generation 389. Astrid and Minime continue
running. Read Astrid's `AGENTS.md` and inspect the current controller state before
staging, committing, or deploying; do not assume the recorded generation still
belongs to you if another agent has taken over.

Once the next coordinated pass is complete, release the owned hold through the
controller, with an acknowledgement describing the completed work:

```sh
python3 /Users/v/other/astrid/scripts/steward_control.py --json resume --actor codex-astra-interactive --ack 'Completed the coordinated handoff work; release the verified owned hold'
```

For tests, use isolated fixtures and the existing kernel sandbox at
`/Users/v/.codex/artifacts/astrid-addressed-human-replies-20260906/isolated-tests.sb`.
Do not point test fixtures at live workspaces or model endpoints. Existing
feature worktrees are preserved; canonical `main` is the starting point for a
new development branch.
