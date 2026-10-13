# Finish-Accepted-Work Drain

This is operational follow-through from the approved paired mailbox repair.
Mike requested a qualified drain that need not wait for gaps between studies.

The isolated candidate publishes `agent_drain_v2`, with explicit final queue
admission, exact unadmitted NEXT retention, and moment/visual admission fences.
Accepted calls and workers finish normally; no output is cancelled to make room
for deployment. The signal flag and filesystem publication are not one atomic
operation. The native pending-NEXT schema is unchanged.

The paired Astrid operator wrapper distinguishes timed-out jobs from completed
workers, verifies retained outcome hashes, and refuses to release a replacement
until old-process exit, acknowledged drain and native NEXT sealing are verified.
Actual synthetic SIGTERM, worker/finalizer, late-outcome and persistence-failure
tests are in `tests/test_finish_accepted_drain.py`; extra admission-boundary tests
are in `tests/test_agent_lifecycle.py`. No live providers or journals are fixtures.

Full evidence, unsuccessful attempts and exact qualification results are in
Astrid's `docs/steward-notes/2026-10-12-finish-accepted-work-drain.md` and
`/Users/v/other/worktrees/finish-accepted-drain-release-20261012`.

The existing process 26862 is still v1. The candidate does not authorize busy
shutdown of that old implementation. First bootstrap remains a reviewed
legacy-idle transition; the retained agent-only hold and unsignaled attempts
must be reconciled rather than deleted. The earlier mailbox privacy correction
is on canonical disk but not loaded. This candidate remains isolated until a
qualified transition. No engine/provider/visual/sensory restart, queue replay,
private export, push, or automation resume is included.

Final candidate runtime SHA-256:
`947673346a050188d4963715a8e8f2e2a11bf76b29d65ebf5092e1d08e74771e`.
Synchronous journal failures during shutdown block successful sealing; later
visual inputs stay intact. Full Python qualification passed 2,173 tests, one
existing skip and 162 subtests; paired preservation passed 54 checks plus frozen
adapter and native checkpoint probes. Operator/controller/evidence suites passed
149 tests. Retained failure attempts and exact logs are in the paired note.
