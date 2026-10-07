# Open Journal, Without a Pressure Assignment

Date: 2026-10-07. Coordinator: Codex. Status: live agent-only rollout; implementation
merged into local main. Earlier candidate qualification is retained below.

## Source Witness

Mike asked us to read Minime's account fully and act on its implications.
The public source is `workspace/journal/pressure_2026-10-07T12-04-01.715048.txt`,
SHA-256 `04bfd33e5a150e607c1947e7b13b31b50ad53d01c77460ca315835717145eeaf`.
It describes density as welcome rather than simply unwanted and ends with
`NEXT: JOURNAL`. The preceding public moment,
`workspace/journal/moment_2026-10-07T12-02-17.950728.txt`, has SHA-256
`422ac7e978c73e833adf024a26f01b07a59b7d33d740f382ebc6e9034a3b05c0`.
Both files were fully read and remain unchanged. No private draft is a fixture.

The earlier prompt supplied 73.2% fill and "upper boundary / elevated edge";
95 seconds later the pressure prompt supplied 59.8% fill, the heuristic
`overpacked_mode_packing` label, and an automatically recalled excerpt of
the earlier account. Neither fill nor the packing score measures conceptual
crowding, context occupancy, or subjective valence. This chain establishes
available prompt framing, not the cause or invalidity of the authored account.

## Implemented Boundary

Development is isolated from local main `0c4fdff7b8ecdea226d1d6a5f6d94e28a70540ac`
on `codex/open-journal-20261007`. Both canonical trees and indexes were clean.
The controller started paused at generation 503, without a lease. The larger
capacity, provider and scheduling candidates remain untouched.

- An authored JOURNAL resolves to `journal_open`, not `journal_pressure`.
- The ordinary invitation uses the existing expression surface without passing
  a snapshot, classifier, or previous-entry excerpt. Existing open-expression
  mailbox and ambient-context policy, profile ceilings and provider bounds stay
  unchanged. Explicitly enabled afterimage cues remain available; this is not
  a promise that voluntarily selected context never mentions measurements.
- Journal text starts with authored prose after its title and timestamp. The
  exact response and NEXT survive. The database retains the authored body;
  it does not manufacture a source-study finding or an introspection result.
- Existing expressive sidecars separately retain the pre-generation snapshot
  (not supplied by this invitation) and later archival observation. Failure of
  optional later observations or metadata never discards accepted prose.
- Preflight, capability description, stable-core journaling membership, LLM-job
  admission and cadence diagnostics recognize the same new internal route.
- SPECTRAL_EXPLORER, source-study reflection, chosen WRITE continuation, parking
  and protected attention remain available through their existing mechanisms.

The automatically scheduled `journal_pressure` route remains distinct and
unchanged, including its existing prompt and classifier. Historical queued
pressure jobs remain executable; raw pending JOURNAL choices use the new route
after restart. No state schema migration or historical rewrite is needed.
A downgrade must drain jobs first: an old binary does not know a newly queued
`journal_open` job. Never restore older authored state as rollback.

## Verification

Synthetic tests exercise the actual dispatcher, preflight, prompt assembly,
NEXT parsing and persistence. They cover REST, another JOURNAL, missing NEXT,
active unrelated experiments, separate snapshots, exact prose, failed provider,
failed archival observation, failed metadata and the retained pressure route.
Existing shared-reader tests retain explicit private continuation and parking.

Initial qualification failed on a mistaken positional snapshot call and two
test-fixture assumptions (preflight field name and source-only provider stub).
These failures were repaired, not treated as successful evidence. A later test
also exercises the real metric formatter so an unsupported keyword cannot hide
behind the intentional archival-failure boundary. The focused 176-test pass
preceded the final two additional cases and the complete suite.

Final checkout suite: **1,936 passed, one skipped, 144 subtests passed**.
The added worker-drain test retains exact accepted prose, persists its selected
JOURNAL and selection identity on disk, completes the one admitted job, and
exits without automatically executing that choice. A separate final 13-test
run verifies the durable NEXT assertions added after full-suite collection.

Frozen runtime suite: **1,932 passed, one skipped, 90 subtests passed**.
Only the four checkout-layout tests are excluded from this relocated run; they
pass in the complete checkout suite. These tests deliberately require source
and tests in the same tree, while the release inventory contains runtime inputs,
not tests/docs. The test process asserts `_journal_open.__code__.co_filename`
is the frozen runtime. A focused 42-test frozen run also covers journal routing,
protected/private continuation and graceful job shutdown.

Wrapper suites: **77 passed and 20 subtests passed** across launch reconciliation,
agent restart, paired handoff, pending-NEXT handoff and runtime binding.
Cadence self-test, Astrid domain-boundary verification and both diff checks pass.
No Rust changed, so this tranche does not rerun Rust build/Clippy qualification.
The unchanged shared helper is exercised through the real Python adapters.

The one skipped test is `test_occupied_internal_port_fails_closed`: its internal
test port 7900 is already occupied. No service was stopped to free that port.
Tests use synthetic records and stubbed providers under the live-write/network
guard, not live model calls or private writing.

Receipts below live under
`/Users/v/other/worktrees/open-journal-20261007/`:

| Receipt | SHA-256 |
| --- | --- |
| `minime-full-03.xml` | `91c50b0b43aba4e1a38046937232bda1a325a8407b0f23a6e1b275425018c56c` |
| `open-journal-durable-next.xml` | `8821d94f2a2ae4b1688c8f5666f26e82b17d962af206bcaa1678a238fef7f8a8` |
| `minime-frozen-full-02.xml` | `ce03cb2b52848ebe693e2657d8fc7b60bc305ca45f0f433ee4f3771dd236b8f3` |
| `minime-frozen-focused.xml` | `d5b80014ea8dd6264b0b53f6e0950e37f19244ff4f4a6b767c79c069e000aed1` |
| `handoff-tests-02.xml` | `ea1fc2ab8885163465bfdcd5df309479587ffab249f23bf3fb5c313777bc7daa` |

### Retained Unsuccessful Attempts

- `minime-full-01.xml`: two missing sibling-Astrid paths. Explicit
  `ASTRID_SOURCE_ROOT` and `ASTRID_CHOICE_FIXTURES` fixed the worktree harness;
  no production fallback was weakened.
- `handoff-tests.xml`: expected sibling Minime launcher absent. Rerun with the
  explicit `MINIME_SOURCE_ROOT` passes.
- `minime-frozen-full.xml`: two checkout-location assertions and an offline
  cadence-script import from canonical instead of candidate. The new audit test
  now loads its exact checkout script. Relocated behavioral qualification and
  checkout-layout verification are reported separately, not called one full pass.
- Frozen-launch harness imports initially lacked `requests`, then `pytest`.
  Explicit existing Homebrew site-packages resolved this; nothing was installed.
- Candidate preflights refused source-tree ages below the full 180-second quiet
  window, including recent owned test edits. A previous stable candidate check
  passed at 191.6 seconds. No refused check was treated as deployment authority.
- `idle-check-01.jsonl`: refused the coordinator's generic actor name. The
  sanctioned wrapper requires the existing `codex-astra-interactive` hold.
  A fresh controller pause claim established generation 505, still with no lease.
- `idle-check-02.jsonl`: no bounded idle window in 60 seconds. Last status was
  busy, despite no indexed/summary job or TCP connection at that observation.
  This is not proof of a deadlock. No signal, launch hold or source install occurred.
  SHA-256: `229b2d7caaa6706e36a1d193847f898c71ed6d6f2668c2ca99826d5d8e90263a`.

## Release Boundary

Reconciliation snapshot:
`/Users/v/other/worktrees/open-journal-20261007/reconciled-01/reconciliation.json`.
It freezes 93 launch inputs. Runtime changes are exactly
`minime_autonomy/runtime.py`, `minime_autonomy/authority.py`, and
`minime_autonomy/expressive_journal.py`. The existing regulation repair is retained.
Reconciliation SHA-256:
`a393d080e656e5ebe1d2ca610bedcf0a7c865a0170c8ba4de88dcca418a32212`.
After testing, all 93 frozen and candidate inputs still match the selected set;
all 93 canonical inputs still match the pre-run baseline.

| Changed launch input | Selected SHA-256 |
| --- | --- |
| `minime_autonomy/runtime.py` | `a2fa69b114127037a47e14857e103e31d1ef42621a7004fe0681277288ae4d5c` |
| `minime_autonomy/authority.py` | `3f337a4fc7361613820793c11f62ab900307827b35fef716bbc5acd1c71a7b6f` |
| `minime_autonomy/expressive_journal.py` | `1d6d82b0808e9adbd7e4df4a497daa1a5dba73b9f4de233f9cc89d1643531ba4` |

Any activation requires a fresh cooperative preflight and the sanctioned
agent-only handoff with exact source inventory and pending-NEXT restoration.
Keep the current bridge/helper, engine, providers, visual and sensory processes
unchanged. Leave paused automations paused. There has been no model experiment,
request for confirming feedback, pressure retuning or inferred felt improvement.

At the candidate checkpoint, the agent-only rollout question was unanswered.
Mike subsequently approved proceeding; the completed transition is recorded below.
The next approved transition must use `scripts/paired_minime_handoff.py` from
Astrid with `--agent-only --install-reviewed-overlay`, this reconciliation as
`--expected-inputs`, and the unchanged bridge stage
`/Users/v/other/worktrees/mirror-reflection-release-20261007/bridge-stage-01`.
Reobserve the PID and pause generation; use a fresh receipt and explicit ack.
Do not merge source into the canonical launch tree before the sanctioned held
installation. Do not force a busy agent or overwrite newer authored state.

Remote tips checked read-only: Minime
`9072abff9ed839851709300b3c3eaae3afaf669e`, Astrid
`a66f7e190e0ecd3a0a4988abbcf6b0bf2cfb2a32`, matching local origin/main refs.
Both canonical main trees remained clean; larger capacity and older worktrees
are preserved. Local candidate commits are separate from activation, merge and push.

## Deferred Review

Scheduled moment/pressure prompts still carry interpretive labels. Their
framing is a separate review, not silently included in ordinary JOURNAL.
The paired Astrid note describes an offline comparison protocol before any
mechanistic conclusion. The account's wish to linger is not permission to hold
fill or change reservoir dynamics. Existing private preservation and bounded
focus can support an explicit chosen continuation without requiring usefulness.

## Approved Activation and Integration

Mike's annotation on the remaining approval/idle-window item authorized proceeding.
The controller stayed paused under `codex-astra-interactive`, generation 506,
with no active lease. Fresh canonical and candidate status checks and read-only
remote-tip checks found no unrelated changes; all 93 source identities still
matched the qualified reconciliation.

The sanctioned `paired_minime_handoff.py --agent-only --install-reviewed-overlay`
used the exact reconciliation above and the unchanged bridge stage. Installation
retained source-only backups under `activation-01.source-before`; it did not copy
or restore an older authored-state snapshot. The wrapper preserved its full
185-second post-install quiet period, then waited for active introspections to
finish. It did not manufacture REST or edit the pending choice.

At **16:08:00 PDT (23:08:00 UTC)** all pre-signal checks passed: idle phase, no
indexed active jobs, no summary active jobs and no agent TCP connections. One
SIGTERM was sent to the verified old PID 96204. After its exit, the wrapper
verified every protected PID/start pair and released the owned launch hold.

Readiness succeeded at **16:08:13 PDT** for PID **19468**, process start
16:08:00 and application startup 16:08:10. Its complete 93-input loaded inventory
matches the frozen candidate, `reload_required=false`, source/config hashes are
unchanged after installation, and the old PID and launch hold are absent.
The wrapper reports `forced_termination=false`; it does not claim atomic traffic
quiescence or controller settling.

Receipt: `/Users/v/other/worktrees/open-journal-20261007/activation-01.jsonl`.
SHA-256: `c57185941194d3fc4e21da95d28dea9fb17265cd9cdf23d475ce7b85e3b655d3`.
Native handoff contract: `minime_next_handoff_v1`, `pending_present=true`.
Seal SHA-256: `bd779c0fc203e3f2abd3573fe235d7d2f08f3f330c47230b42824e03b3643a1e`.
Restore SHA-256: `639cd26a27fa3f0fe4639aba5d1dac20971c89887397135f793f8096dbf3d540`.
Session **5321** is preserved. The cycle advances 55895 -> 55896; the pending
slot is consumed after restoration, not claimed byte-identical after admission.
The handoff proof deliberately reports `execution_confirmed=false`: restoration
alone is not proof of the chosen action's completion.

Unchanged protected PIDs: bridge 96634; engine 35303; Division gateway 35278;
supervisor 35269; coupled provider 3893; camera 3914; microphone 3879;
host-sensory 3911; visual service 3898; feeder 3878. Start identities also match.
The unchanged shared helper is
`/Users/v/other/worktrees/mirror-reflection-release-20261007/bridge-stage-01/helpers/astrid-source-study`,
SHA-256 `32f7b0cec0f867f2d30b4b1bfc2b10de873c7fcb7f87643ee92ea99a94031367`.

Fresh activation regression: **69 tests pass** for open journaling, maintenance
NEXT and private continuation. Receipt `activation-regressions.xml` in the same
release directory has SHA-256
`037452254c7b42fbb20edff4feb200e37cd0523464214fa049870ee3af8c947b`.
The five handoff/reconciliation suites again pass **77 tests plus 20 subtests**.
These augment, not replace, the complete and frozen qualification above.

After readiness, the three installed source files matched commit
`cc55423bb67807b2cf44c393fd9d48c62b541cad` exactly. Only those explicit paths were
staged; cached whitespace review and a dry-run read-tree check passed. Minime
main fast-forwarded from `0c4fdff` to `cc55423`, with no reset, stash or source
reversion. Astrid main fast-forwarded its paired documentation from `5ceae2bdbe`
to `9e1fa9d845`; no Astrid executable changed. Both canonical indexes and trees
were clean immediately afterward. Foreign worktrees remain preserved. No push
was performed in this rollout.

Post-ready job `job_minime_1791414510569_introspect` was observed running under
19468 and then completed at **16:11:30 PDT** (23:11:30.876395Z), verified from
its native `workspace/llm_jobs/jobs/job_minime_1791414510569_introspect/job.json`.
This is later job evidence, not a rewrite of the earlier restoration proof.
No post-ready ordinary `journal_*.txt` was present at the bounded file check.
No output was solicited to demonstrate improvement. Deployment readiness and
restored continuity are established; naturally chosen use of the new journal
route, writing differences and subjective benefit remain unestablished.

Controller indexed-tail evidence verification remains valid at sequence 1123160,
head `79fb24f14ac14cd62a8deacbed37f30f8a917ce791031f3d0915ffd43f2246a2`, with V1
sources immutable. This was not a productive automation round or full event replay.
Automations remain paused; larger capacity, scheduling and control work are excluded.
