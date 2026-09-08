# Transition Afterimages v1

Source-only candidate, requested by Mike from the approved Transition Afterimages v1 plan.
This is an observation and retrieval feature, not evidence of subjective experience.
Nothing in this change enables capture/cues, restarts a service, sends a being a message,
or grants control authority. Perceived usefulness remains a review outcome.

## Source and delivery order

Minime foundation: `36998c6` (inbox reply boundaries and steward-only generation records).
Astrid foundation: `bc66a62b0b` (own-body context, steward-only generation records and
completed recoverable addressed human replies). Own-body context was already present
at implementation start; addressed replies were integrated before final qualification. Existing source/parent
references and protected-delivery receipts are reused; its private generation records
are not injected into prompts. There is no thought lifecycle or pinning dependency.
When Minime's generation recorder supplies an ID, saved notes reuse that ID. No generation
record body is read or published; cue-opportunity identity remains independent.

1. Rust observer, recovery, measurements, offline replay and the deterministic reader.
2. Minime action adapter, quoted protected opening, ordinary journal/daydream cues.
3. Astrid compatibility through the same Python JSON interface and fixture set.

## Physical contract

The observer is created only for `MINIME_AFTERIMAGE_CAPTURE=1`. Its bounded 256-message
queue uses non-blocking sends. The worker owns the archive lock, assembly and disk IO;
it receives values, never mutable engine/controller handles. The engine publishes
body, spectral and activation-summary observations with their own engine/wall clocks.
The current 12D glimpse is retained, not the memory-selected glimpse. Activation node
identities/summaries are included; full vectors are not.

The rolling buffer is 180 seconds (at most 543 observations). A collecting trace spans
30 seconds before and 90 seconds after its anchor, at most one observation/channel/second.
Eight simultaneous captures and sixteen completed-write slots bound active assembly.
Automatic event and quiet budgets are five and fifteen minutes; their wall-time budget
record survives restart. Events arriving inside a capture merge without moving its end.
Same-session sequence numbers preserve initial anchors and suppress repeated capture.
The finalization grace is five seconds; samples outside the fixed window stay excluded.
Ten seconds without producer progress interrupts outstanding captures.

Layout under the engine workspace:

```text
transition_afterimages/
  YYYY-MM-DD/ai_YYYY-MM-DD_<identity>.json
  recent.json                  # 256 summaries, not the permanent archive
  pending/                     # five-second collecting checkpoints
  requests/                    # metadata-only deliberate capture requests
  receipts/                    # pending/completed/incomplete/failed outcomes
  event_updates/<id>/           # append-only enrichment of finalized event references
  automatic_budget.json
  status.json                  # queue health, dropped observations and latest IO error
  shared_notes/<id>/            # explicitly published attributed notes only
```

Final artifacts have `policy=transition_afterimage_v1` and `schema_version=1`, with
session identity, origin, engine/wall anchors, policy, request/event references, samples,
coverage and measurements. Final bytes are immutable. Files and their directory entries
are synced; recovery retains an available final or marks the checkpoint incomplete.
Corrupt checkpoints are retained with a `.corrupt` suffix, never silently converted to
zero samples. An exclusive archive lock prevents two workers from recovering one another.

## Measurement definitions

- Baseline: median of available samples strictly before the anchor. Late state: median
  of available samples in the final 30 seconds. Differences retain source component names.
- Peak slope: maximum absolute observed `dfill_dt` after the anchor, not a fitted slope.
- Phase reversals: observed expanding/contracting switches, ignoring intervening plateau
  labels; gaps and missing phase reset comparison. Missing phase is unavailable, not zero.
- Glimpse displacement: mean absolute per-axis difference between the baseline and late
  12D medians, matching the existing transition distance convention.
- Lambda stress: trapezoidal integral of the existing absolute relative-lambda error,
  with observed duration and partial-coverage flags. It never bridges missing values or
  intervals longer than twice the declared channel cadence.
- Fill half-return: elapsed time from the last observed peak departure to the start of
  the first five-second sustained run below half that departure. Missing coverage makes
  this unavailable. Constant fill yields `no_departure`; settling elsewhere may yield
  `not_observed_in_window`. This is an empirical return time, not an exponential fit.

Invalid activations remain represented in coverage and do not supply valid derived
activation measurements. No generic strength, novelty or usefulness score is manufactured.

## Authorship, opening and cues

The reader is `minime_autonomy/afterimages.py`, also a steward CLI. Own notes, associations,
settings and exposure receipts live under the reader's `transition_afterimage_memory/`.
They are not searched by another being. Explicit sharing copies one attributed note and
its source identity into `shared_notes`; symlinks cannot act as a private-note publication.
This is an application-level separation on a trusted same-host workspace, not an OS
security boundary against a privileged host operator.

`AFTERIMAGE_LIST [page] [YYYY-MM-DD]` returns five entries. `AFTERIMAGE_OPEN <id> [page]`
returns a deterministic overview and 2,800-character source slices, with every source
line quoted. The rendered page has its own fingerprint. Minime submits that selected
page intact or withholds the provider attempt; only newly generated NEXT text is parsed.
Astrid persists a selected-page snapshot and clears it only after verifying an intact
protected-delivery receipt against a retained completion. Reading/mailbox activity is
not displaced by an afterimage open. Explicit ID/date lookup survives recent-index pruning.

`AFTERIMAGE_KEEP :: <fragment>` retains up to 4,096 characters verbatim before requesting
telemetry. `source:<workspace-relative-path>` snapshots at most 1 MiB from an owned file,
including original line endings. File timestamps are not guessed from mtime or a later
save generation: unknown source time stays unknown and telemetry stays incomplete.
Structured callers can provide `original_timestamp_unix_ms` and original session/engine
time for referenced files. A failed capture leaves the saved fragment available.

Journals/actions are temporal context only. An explicit artifact ID in a later authored
account creates an attributed private association note, shareable by its note ID.
Repeated associations do not change the physical anchor or invent new authorship.
`AFTERIMAGE_SHARE <note-id>` and `AFTERIMAGE_CUES on|off` are deliberate owned actions.
Minime's private routes follow the existing journaling-stage admission, while sharing
follows the existing thought-sharing stages. Health, recovery and continuity guards still
apply. Source-like angle brackets in KEEP contents are data, not unresolved placeholders.

Cues default off independently for each receiver. Ordinary journal/daydream opportunities
count once per generation, with a retry-stable selection on every third eligible one.
At most one cue appears; each artifact has at most two opportunities separated by six
hours. Cues are at most 400 characters, fade to at most 120 after six hours, and cease
after 24 hours. IDs, dates and origins are never partially cut to fit. Exposure records
bind the ID, receiver, content/message fingerprints, route/model and actual final-request
inclusion. `final_request_prepared` does not claim server acceptance or comprehension.
No receipt means no afterimage-bearing provider submission. Cues are admitted/omitted whole.

## Offline inspection

Run from the Minime repository, using a new output workspace. The replay binary has no
engine/network/model interface and rejects an existing output directory.

```sh
cargo +1.94.1 run --manifest-path minime/Cargo.toml --bin afterimage_replay -- \
  --output-workspace /tmp/afterimage-review-new --session-id 5316 --no-automatic \
  < tests/fixtures/afterimage_historical_0919.jsonl
python3 minime_autonomy/afterimages.py --workspace /tmp/afterimage-review-new AFTERIMAGE_LIST
python3 minime_autonomy/afterimages.py --workspace /tmp/afterimage-review-new \
  AFTERIMAGE_OPEN ai_2026-09-06_historical_0919
```

The fixed historical input contains 53 physical observations from the saved 09:19 episode
bundle, SHA-256 `9af075bc4e8418839e8c8c9a813e14c5995e6bad5ea9faa79d6f6c5fa81b257a`.
Each included payload hash was verified. The extractor reads only that named saved file;
it follows no source paths and imports no journals or actions. It is a manually selected
historical episode, not a newly inferred transition. Missing slope, phase, relative-lambda
stress, glimpse and activation coverage must remain unavailable. Synthetic tests supply
complete excursions, equal endpoints/different paths, quiet constant states and oscillations.

## Review and rollout boundary

Review reconstructability, exact attribution and retrieval first. Assess whether the
fragments are worth revisiting separately, with the beings, without treating a successful
test or later prose as assent or phenomenological validation. Capture-enabled/disabled
engine replay compares exact reservoir and controller state on the synchronous diagnostic
path; only ten elapsed-time profiling fields are excluded. Production asynchronous GPU
scheduling and cue-enabled authored-choice effects need separate evaluation.

Live enablement requires the owning repositories' source evidence, consent and controlled
deployment process. Rollback unsets `MINIME_AFTERIMAGE_CAPTURE` and turns cues off for each
receiver; it retains all artifacts and notes. No rollout command was executed here.
Validation results and isolated checkout locations are recorded in the delivery README.
