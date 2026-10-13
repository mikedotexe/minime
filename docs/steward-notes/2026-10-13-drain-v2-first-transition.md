# Drain V2 First Transition

Mike approved source reconciliation, the safe idle-only first transition, and
local integration on October 13 (America/Los_Angeles). This completes the live
handoff for the qualified shutdown-admission fences and the previously installed
but unloaded mailbox explicit-NEXT/privacy correction.

The exact loaded v1, installed mailbox-corrected v1, and qualified v2 inventories
each contain 96 inputs and differ only in `minime_autonomy/runtime.py`. The
operator wrapper verifies all three plus original unsignaled attempts 02/03/04
and their retained hold, without manufacturing a source-status match. It uses
the unchanged idle-only restart gate, not the new busy drain on old code.

Old PID 26862 exited with a durable native NEXT seal at 07:42:36. Only then did
the wrapper install the reviewed runtime and release the owned launch hold.
New PID 95712 initialized at 07:43:12, loads all 96 qualified inputs, publishes
`agent_drain_v2`, and reports `reload_required=false`.
Runtime SHA-256:
`947673346a050188d4963715a8e8f2e2a11bf76b29d65ebf5092e1d08e74771e`.

Native NEXT seal:
`5467b2e008d9a8306e5c86fdd9be703b3fe814f661646fb1a1ade275f10a20b5`.
Restoration record:
`c99c2794ee0658fb7268c29af59ce0c18dbd66cc18c313271b54bec5a96279f5`.
The pending choice was preserved; this does not establish its successful execution.
No authored state was restored, reconstructed, or overwritten by the operator.

Evidence root: `/Users/v/other/worktrees/finish-accepted-drain-release-20261012`.
The successful attempt is `bootstrap-20261013-01/completed.json`; its manifest is
`1bd2cc3d70b45459da379e4b42ccf04a1f76dd3519662c18cdec5ea891224544`.
`2026-10-13-post-activation-01.json` verifies exact loaded/disk source, native NEXT,
absent hold, configuration, shared bridge stage and ten protected PID/start pairs.
Session 5321 continues at cycle 61650. Telemetry sequence 863831 had valid fill
70.30% and target 68%; fresh work was admitted after startup. No subjective
improvement, mailbox uptake, or long-term stability follows from these checks.

The runtime candidate retains its prior complete qualification: 2,173 tests,
one existing skip, 162 subtests, and 54 paired preservation checks. This turn's
runtime recheck passed 45 tests. The new operator/bootstrap/native handoff plus
controller/evidence suites passed 194 tests, including 39 new synthetic bootstrap
cases. Initial invalid job fixtures and an unsignaled source-quiet refusal are
retained in the corresponding Astrid steward note, not erased.

No engine, model/provider, bridge, visual or sensory process was restarted.
Controller pause generation 514 remains active and automations remain paused.
No push, forced termination, automatic retry, mailbox conversion or resend.
Parent Codex is the sole Git coordinator; Sagan implemented the operator adapter
and James supplied its independent qualification. Full source reconciliation and
test details are in Astrid's note with this same filename.
