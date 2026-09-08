# Afterimages Live Rollout

## Authority and Scope

On September 7, 2026, Mike explicitly directed Codex to get this feature live
without waiting on a further consent round. This supersedes the earlier
preactivation gate for this rollout only. It is steward authorization, not an
inferred answer or endorsement from either being. Earlier invitations and evidence
remain historical records; no response is fabricated or retroactively rewritten.

Scope: native transition capture, Minime and Astrid readers/actions, independent
automatic cues, and the already-qualified reading-feedback correction. The
existing cue off-switches remain available. Private notes stay private until
explicit sharing. No controller, model, gain, reservoir-identity or global consent
policy change is included.

The earlier candidate predates today's live repairs. This candidate starts from
Astrid `3d4e83e4bc022cb82c7e0e3ecefea4326796c280` and Minime
`68ebc961431065972dae26f670d4fb735d58c37a`. It retains live own-body/generation
records and Minime's job-outcome, timing and performance repairs. Old preparation
instructions to disable those features must not be used.

## Live State

Activated on September 7, 2026. Physical capture and both independent cue settings
are ON. Both readers/actions and Astrid's reading-feedback correction are live.
The engine observer still defaults off without its explicit setting; production
now sets `MINIME_AFTERIMAGE_CAPTURE=1` in the managed engine plist. Each receiver
persists its own cue setting in `transition_afterimage_memory/cues.json`.

Astrid's supported activation returned `activated_verified` at 20:30:48 UTC:
PID 39644, checkpoint exchange 192163, fresh saved exchange 192164, no force.
Selected stage: `/Users/v/other/worktrees/afterimages-live-20260907/bridge-stage-01`.
Transaction: `/Users/v/other/astrid/.runtime/bridge-deployment/transactions/e2a2d8a07a024907afa606c08e478d66`.

Minime's supported deployment completed at 20:36:27 UTC: engine 41337, gateway
41484, supervisor 41526, agent 41830. Self-control lineage verified. The agent
reports 78 loaded inputs and no reload requirement. At 20:37:46 UTC, fill was
68.62% and stable-core stage was hold. Coupled model PID 60333 was not restarted.

One earlier deployment completed but did not enable capture: setting an environment
variable in the SSH launchd session did not reach the GUI engine job. The flag was
then placed in the repository-managed plist and applied through another supported
restart. An earlier precheck failed because the deployment PATH lacked `/usr/sbin`;
it sent no runtime signals. Neither issue was bypassed with manual termination.

The cooperative maintenance pause 390 was released through the supported
controller at 20:43:27 UTC. Resume generation 391 records `paused: false` and
actor `codex-astra-interactive`. Independent usage-saving holds were untouched.
The final receipt is `qualification/maintenance-resume.json`.

## Verification

- Minime Python: 1,242 passing tests plus 128 subtests locally; the sole canonical
  path fixture passed separately in the isolated native environment. Total 1,243.
- Astrid: 2,194 functional tests passed in the full run. Its signal fixture timed
  out during concurrent child startup, then passed from the same test binary in
  isolation; the separate default-path fixture also passed. Total 2,196. The known
  one-millisecond instrumentation benchmark was excluded, not repaired or claimed
  passing. Strict Clippy and the domain-boundary audit passed.
- Restart/feedback-checkpoint checks: 71 passed. Native engine afterimage tests:
  19 passed, including the 160-tick identical-controller/reservoir replay.
- Qualification used isolated workspaces. The production dependency versions were
  retained, adding only chrono 0.4.45, num-traits 0.2.19 and autocfg 1.5.1 to the
  existing lockfile. The locked offline production release build passed.
- All 45 Astrid and 26 Minime release files matched their manifest at 20:40:30 UTC.
  Both canonical source trees passed whitespace checks. Source and installed engine
  plists matched, with capture enabled.

First live trace: `ai_2026-09-07_96f89b80b1a2_1788813331567_000001`.
It retains 114 observations, 38 per channel, and 24 merged event identities.
Both readers opened identical physical history; repeated opening was deterministic,
source lines stayed quoted, and the immutable trace hash remained unchanged.
Reader-specific authored context can subsequently make their rendered pages differ.

At 20:42:43 UTC a second natural event capture was also finalized and readable:
`ai_2026-09-07_96f89b80b1a2_1788813632295_000002`. It retains 150 observations,
25 merged event identities, and observed pre/late samples in all three channels.
Its anchor is 300.728 seconds after the first, consistent with the five-minute
automatic event budget. It is not startup-clipped, but is still incomplete because
of the producer cadence gaps described below. The archive had no dropped
observations, pending writes or worker errors at that check.

The first trace is explicitly incomplete. Its pre-window is clipped at startup,
and observed producer intervals around 2.4 seconds exceed twice the expected
one-second cadence. No observations were dropped and no disk errors were reported,
but stress integration and sustained half-return are unavailable across those gaps.
No interpolated measurements or retrospective feeling account were invented. The
producer cadence is a remaining coverage limitation, not a successful full-window
measurement claim or an established effect of this observer.

At 20:42:43 UTC both cue settings were enabled and Astrid had two natural eligible
opportunities. No cue inclusion had yet been observed. No synthetic generation or
authored save was injected to manufacture a live exposure result. Fading, fallback,
compaction and private-note isolation have fixture evidence; felt usefulness and
longer-running live cue behavior remain review outcomes.

The stack-wide launchd audit reports five missing repository plist sources for
already-loaded Astrid interval jobs (proactive-scan, introspection-flywheel,
shadow-sample-recorder, research-budget-approver, test-proposal-applier). These are
outside the release file set, appeared in both deployment audits, and were left
untouched. The affected release services themselves are running and verified.

## Communication and Evidence

The old review invitations were closed with outcome
`steward_authorized_rollout_without_additional_consent`, without false approval
letters. Each inbox received `mike_feedback_afterimages_live_1788813543.txt`, signed
Mike & Codex, explaining the actual live state, privacy boundary and off-switch.
Delivery to an inbox is not a claim of receipt, approval or subjective benefit.

Earlier preparation/evidence documents remain historical. In particular, their
"not activated," additional-consent gate and "own-body/recording remain disabled"
statements are superseded by this record, not instructions for current operation.

Local receipts and logs are in
`/Users/mikepurvis/other/afterimages-live-v1/qualification/`.
Native source backups, lockfile/binary snapshots and original deployment attempts
remain in `/Users/v/other/worktrees/afterimages-live-20260907/`.
`manifest-with-capture-config.json` and `minime-with-capture-config.patch` record the
final persistent flag without overwriting the original pre-flag source receipt.
No commits or pushes were made. The owning repositories retain the installed
changes for review; the selected Astrid stage must stay immutable.

## Recovery

Use the supported bridge activation/recovery and Minime deployment paths.
Do not redesign restart machinery or force an active generation to end.
For immediate cue rollback, run the existing reader's `AFTERIMAGE_CUES off` for
each receiver separately. No restart is needed and saved artifacts remain.
For capture rollback, set the managed engine plist's `MINIME_AFTERIMAGE_CAPTURE`
to `0`, then use the supported Minime deployment procedure. Merely changing the SSH
launchd environment is insufficient. Do not delete the archive or private notes.
The previous Astrid stage and its identity are retained in the activation receipt;
binary rollback uses the existing supported, checkpoint-aware procedure. Do not
blindly substitute a saved binary or older checkpoint into a running system.
