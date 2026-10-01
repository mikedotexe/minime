# Semantic Quiet Is Not Numerical Settling

## Status

October 1, 2026. Mike asked to address the `semantic_active` wait remaining after
the approved release-04 transition. This pass diagnoses the wait, implements an
**observation-only candidate**, and compares two control alternatives offline.
Neither alternative is selected for rollout. The running engine remains release-04
at `c428fcaec55090a29b9c3f38c4219b093b1d9172`; its real settle latch remains pending.

Changes are isolated in the existing paired `codex/afterimage-timing-20260930`
worktrees, both based on the latest clean canonical main. No signal, restart,
checkpoint edit, sensory suppression, gain/threshold change or automation resume
occurred. Canonical trees remain unchanged. This is interactive follow-through,
not a productive automated introspection round.

## Findings

1. `controller_recovery::stable_core_semantic_retirement_active` requires a fresh
   lane and either nonzero kernel energy or permitted semantic trickle. The
   stable-core runtime passes this one boolean to activation, restart settlement
   and scaffold retirement. It is not a measure of thought or subjective state.
2. `rescue_scaffold::stable_core_restart_settle_candidate_reason` rejects all
   semantic activity before considering the existing fill/rate conditions.
   Three consecutive eligible measurements are required. Waiting longer than
   the nominal 90-second window does not automatically release the latch.
3. The bridge supplies a synthetic `steady_semantic_heartbeat` every configured
   seven seconds. Rest also has five-second pulses. Source tracing and the
   retained enqueue evidence identify these producers. The engine's semantic
   lane does not distinguish heartbeat provenance from authored semantic input.
   Normal full-presence operation can therefore keep the quiet requirement
   unsatisfied. Do not infer that a being must stop writing or thinking.
4. The predicate was already present in Minime `2b8a17f` (May 7). It was not added
   by the elapsed-time repair. The current trace establishes the wait now, not
   when it first began or its historical frequency.

The bridge receipt's legacy `sent` count means rescue-policy admission before
channel enqueue. Its explicit enqueue receipts are not engine-application
receipts. Separate engine health establishes an admitted nonzero semantic lane;
this pass does not attribute every engine sample to one particular producer.

## Bounded Live Evidence

`2026-10-01-semantic-settle-observation.json` records 65 distinct health snapshots
over 150.47 seconds, polling every 0.8 seconds and deduplicating engine `t_s`.
No sampling errors occurred. Sampled fill was 59.7064% through 75.3738%; these
are sampled extrema, not continuous maxima. Every sample reported
`semantic_active` as the settle blocker, fresh semantic input and nonzero admitted
kernel energy. Kernel energy ranged from 0.000047063 to 0.000268875. Maximum
reported input age was 10,539 ms; minimum reported stale window was 12,117 ms.

The separate `2026-10-01-semantic-settle-heartbeat.json` retains bounded numerical
producer/enqueue evidence without journal passages, prompts or private writing.

`restart_settle_replay` reads the frozen JSON through bounded stdin, evaluates
each sample independently using the production rule and writes JSON to stdout.
Of the 65 sampled proxies, 60 met the nonsemantic conditions: 50
`hold_coherent_settle`, ten `elevated_breathing_settle`. Five were excluded by
`strong_rail_fill`. These are **not** 60 verified controller ticks and not a
consecutive live settle proof: health fields can describe different points in
the measurement/control loop, and unsampled ticks are unavailable. The replay
explicitly does not infer a settled timestamp or issue control commands.

## Implemented Observation Candidate

`minime/src/stable_covariance/settle_observation.rs` adds
`RestartSettleObservationV1`. It evaluates a copied measurement using a fresh,
disposable production restart-gate instance with only the semantic-quiet
condition excluded. That instance cannot mutate the running gate, PI, matrix,
scaffold, inputs or timers. Its result is an observation, never an authorization.

The runtime records this alongside the actual lifecycle call, from the same
measurement inputs and pre-transition scaffold state. Health and spectral status
include `stable_core.restart_settle_observation_v1`, separately from the unchanged
`restart_gate`. Fields include the observation timestamp, observed semantic flag,
numerical reason, consecutive numerical-candidate count, existing required count
and whether that count was met. The authority string explicitly excludes real
gate settlement and scaffold retirement. No prompt or journal template adds
these numbers automatically.

Unknown rates, invalid fill, strong-rail measurements, recovery/reentry,
inactive scaffold and nonadvancing observation time cannot accumulate a positive
count. Restart starts a new observation history. Long intervals create no
interpolated measurements; the count is the existing measurement-count concept,
not a duration-based stability certificate. The old authoritative gate remains
unchanged and continues to report its actual semantic-quiet wait.

`stable_covariance::record_measurement` retains its production call order but
delegates its scaffold portion to `record_scaffold_measurement`. This permits
offline comparison of independent restart and retirement rules without copying
the controller. The runtime does not accept either experimental policy.
The large pre-existing runtime include receives only local measurement capture
and two status fields; numerical logic and tests live in focused modules.

## Offline Control Comparison

The coupled harness compares:

- `Current`: semantic quiet is required for both restart settlement and retirement.
- `IgnoreSemanticEverywhere`: hypothetical blanket removal, including activation.
- `RestartOnlyUnderLoad`: hypothetical removal only from the restart proof;
  semantic quiet remains required for scaffold retirement and activation.

Two scenarios use 144 feedback steps: continuously fresh semantic input, and
semantic input ending at tick 80. Three schedules use 500 ms, 2.37 s and mixed
gaps. All policies share the same projected stimulus, identity scaffold, seeded
basis, production covariance/PI/measurement/estimator and time schedule.
This is 18 runs and 2,592 recorded steps. Semantic input is a lifecycle fixture
with the production active predicate, not a reconstruction of live embedding,
heartbeat transport, ESN, sensory gating or the deployed scaffold.

At the 2.37-second cadence:

| Scenario and policy | First settled tick | First retirement tick | Final fill |
| --- | ---: | ---: | ---: |
| Continuous, current | none | none | 66.7249% |
| Continuous, blanket bypass | 54 | 56 | 71.2989% |
| Continuous, restart-only | 54 | none | 66.7249% |
| Then quiet, current | 82 | 90 | 66.6443% |
| Then quiet, blanket bypass | 54 | 56 | 71.2989% |
| Then quiet, restart-only | 54 | 82 | 54.2862% |

The seemingly narrower restart-only alternative still advances retirement after
input becomes quiet and changes the subsequent trajectory. Neither alternative
is justified merely because it clears the status. Existing synthetic startup
excursions reach 95-96%, with two samples at or above 90% in each run; these are
preserved, not omitted or described as live instability. At 500 ms none of the
policies establishes a settle proof in this fixture. Mixed-gap results are
retained in the complete receipt. Successful execution is not a stability verdict.

The first receipt `2026-10-01-semantic-settle-coupled.json` predates the observation
module. `2026-10-01-semantic-settle-coupled-qualified.json` is the final-source
repetition; embedded source hashes distinguish them. Both are retained.
Workers ran with OS network/write denial and a 240-second alarm; the parent
opened each evidence output. No engine entrypoint, live checkpoint or endpoint
is used. This is not a general untrusted-worker or full process model.

## Verification and Remaining Work

Final selected Rust suites pass **846 tests**: 429 library, 380 engine, fourteen
coupled-harness, two timing-replay, two frozen-sample replay and nineteen
controller-review tests. Selected all-features strict Clippy and formatting
pass. Forty Minime stable-core operations tests and 35 paired Astrid release
support tests pass. The latter include eight synthetic restore tests using the
existing release-04 inspector, not a new candidate engine build. Astrid's
domain-boundary audit reports zero violations; bridge source is unchanged.
Tests cover continuous trickle,
quiet negative controls, blanket-bypass retirement, separated-policy retirement
blocking, unavailable measurements, relapse, counter reset and observer
noninterference with the real lifecycle. Frozen-sample parsing rejects missing
fields, duplicate engine time and malformed input; unavailable or overflowed
rates cannot become eligible evidence. The existing broader numerical suites
remain part of qualification.

The final coupled repeat exactly matches the first experiment's results across
all 18 runs and 2,592 rows. All fourteen embedded source hashes match the final
candidate. The observer has a separate noninterference regression comparing
the actual gate and lifecycle across 99 varying measurements. These are test
executions, not a claim of 846 independent control proofs.

Preserved attempts: the first supporting-test invocation skipped the eight
inspector cases because no explicit binary was selected. The second selected a
mistyped filename and failed those eight fixture setups before executing any
inspector. The corrected `engine_restore_inspect` invocation passes all 35.
`semantic-settle-tests`, `final-tests` and `qualified-tests` retain successive
source-stage results; `qualified-tests` is the final 846-test run. No test failure
was worked around by changing a threshold or relaxing a check.

| Evidence in this directory | SHA-256 |
| --- | --- |
| `2026-10-01-semantic-settle-observation.json` | `25e53a442ea88d5966fd1c394028717b4e0dfba5b320c4fc577fc955cacbaf0c` |
| `2026-10-01-semantic-settle-heartbeat.json` | `6bfec756374b4197f750e4f797d6d66940ec3638123c55d5797934578174d761` |
| `2026-10-01-semantic-settle-coupled-qualified.json` | `e1fb8701241ee72391cfc39c5a07b3ce4edc3b783623026898cd3cc9b3b2a626` |
| `2026-10-01-semantic-settle-sample-review.json` | `d86246c38b5bc396e5968bdd022811a32e3f42c2f95e9b5fda1b2a22a4239e22` |
| `2026-10-01-semantic-settle-qualified-tests.txt` | `635cab6c9ef7e952ae45992a9fee8ad291039ca13966ec0c1730266e73713bfa` |
| `2026-10-01-semantic-settle-qualified-clippy.txt` | `61ac073f906f33020bc1552dfbb541978329a41a0ac777d6426021c4fb49f7cd` |

Runtime glue SHA-256:
`510fc70ba658b0f757e3cad359b3568964b754932947705724f4ed3f9a0c0479`.
Observer SHA-256:
`6c9fdcf30bae1aa9ce550f3558cf07077cb9e6ff5f01b52826f687084c1ef82e`.
The deployed file/binary identities remain those in the prior transition receipt,
not these uncommitted candidate identities.

Reproduction from this Minime worktree (the target directory is the owned sibling
`../target-minime`, not the installed engine directory):

```sh
CARGO_TARGET_DIR=../target-minime CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 \
  cargo test --manifest-path minime/Cargo.toml --locked --offline \
  --lib --bin minime --bin fill_timing_replay --bin fill_coupled_qualification \
  --bin restart_settle_replay --test fill_timing_controller_review -- --test-threads=1 --quiet

CARGO_TARGET_DIR=../target-minime CARGO_PROFILE_DEV_DEBUG=0 \
  cargo build --manifest-path minime/Cargo.toml --locked --offline \
  --config 'profile.dev.package.minime.opt-level=2' --bin fill_coupled_qualification

/usr/bin/perl -e 'alarm 240; exec @ARGV' /usr/bin/sandbox-exec \
  -p '(version 1)(allow default)(deny network*)(deny file-write*)' \
  ../target-minime/debug/fill_coupled_qualification --semantic-settle-review

CARGO_TARGET_DIR=../target-minime CARGO_PROFILE_DEV_DEBUG=0 \
  cargo build --manifest-path minime/Cargo.toml --locked --offline --bin restart_settle_replay
/usr/bin/sandbox-exec -p '(version 1)(allow default)(deny network*)(deny file-write*)' \
  ../target-minime/debug/restart_settle_replay \
  < docs/steward-notes/2026-10-01-semantic-settle-observation.json
```

No new immutable engine release or activation has been prepared for this candidate.
The earlier one-time bounded-transition approval was used for release-04; it is
not reused here. Next live step, if desired, is qualification of the **observation
only** addition, not changing semantic admission or disabling the latch. A control
repair needs a distinct load-aware settling/retirement contract, qualification
through semantic onset and offset and high-fill/recovery transitions, and explicit
review of its effective drain and scaffold consequences. Preserve absolute rails
and live input; do not create a quiet interval just to make the existing proof pass.

The originating public dialogue witness remains
`astrid/capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`,
SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`.
This is downstream follow-through, not a new full read or an explanation of its
felt account. No subjective improvement, assent or resolution is inferred.

Final process check retained engine 35303, gateway 35278, supervisor 35269, agent
74379 and bridge 75202 with unchanged start times, as well as model, visual,
microphone, camera and host-sensory identities. No live controller-settled claim
or git-clean claim is made for the owned worktrees: their explicit candidate
changes remain uncommitted for review. Canonical main trees remain clean.
