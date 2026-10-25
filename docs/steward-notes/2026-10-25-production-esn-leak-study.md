# Production ESN Leak Study

Offline only. No live leak, controller, engine, model or provider change.
`minime/src/bin/leak_investigation.rs` links production ESN construction,
stepping and snapshot restoration; it does not copy the recurrence algorithm.

## Reproduction

Use the reviewed canonical Cargo.lock, `--locked`, an explicitly owned target
directory and a new output directory:

```sh
CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 CARGO_INCREMENTAL=0 \
  cargo run --locked --manifest-path minime/Cargo.toml \
  --bin leak_investigation -- --output /absolute/new/evidence-directory
```

Audit build-cache budgets first. Retain the complete generated manifest, inputs,
snapshots, traces and report. This command never opens a runtime endpoint or
reads an engine checkpoint. Existing output directories are refused.

## Design And Scope

- Four seeds: 7, 17, 29, 43. Production 128-node ESN, current 66+12 input layout
  (78), companion lane zero. Constructor scale .5, density .1, target radius .9,
  common warm-up base leak .65 and lambda .995.
- 128 common warm-up updates; 512 measured updates. Each paired condition
  restores the same complete snapshot, including weights, state, spectral
  history and RNG, then changes only base leak to .45, .65 or .85.
- Bounded synthetic impulse, step/reversal and seeded broadband fixtures;
  matched zero-input and separately declared zero-noise controls. Production
  adaptive leak remains enabled. Every effective leak is recorded.
- Synchronous production spectral rank-one measurement mode. This eliminates
  asynchronous scheduling variation for the comparison; it is not a claim of
  full live-loop equivalence.
- Double-precision descriptive RMS, centered lagged autocorrelation, paired
  trajectory distance, response/recovery relative to matched zero input,
  saturation and effective-leak history. Degenerate correlations are null.
  Units are ESN updates; zero input still updates the state.

## Results

All 96 trajectories and all 12 controls were retained. Identical-input replay
and midpoint snapshot/restart have zero state and effective-leak difference.
Bounded direct overrides expire after three updates, including across restart.
Three runner/oracle tests and 23 focused production ESN tests pass, as do focused
strict Clippy and formatting.

For noisy broadband fixtures across four seeds:

| Base leak | Lag-one correlation range | Effective leak range |
| --- | --- | --- |
| .45 | .429-.445 | .514-.801 |
| .65 | .241-.247 | .689-.908 |
| .85 | .051-.059 | .701-.950 |

These results describe these inputs and initial conditions only. Base leak is
not fixed effective leak. Lower one-update correlation is not a demonstrated
reduction in prose repetition, a preferred setting or a universal memory time.

Evidence root: `/Users/v/other/worktrees/lighter-reflection-20261025`.
Final formatted-run manifest `leak-results-02/manifest.json` SHA-256:
`6c65d0e4bcc9a2d8eafac44469b9faecffbe6c0fac4140d3d57c1f2ad4dcbcc0`.
Report SHA-256:
`41c739e560466174f993ee7952d0139eee7b6d135c33b6781f22e71edb887e8d`.
Run 01 is preserved. Both runs have identical traces, controls and metrics;
snapshot identities differ because measured GPU timing fields are retained.
The initial unpinned dependency-resolution attempt is preserved separately;
reported numerical runs use the canonical lockfile, not a dependency update.

## Applicability

`minime/src/runtime/orchestration.rs` clears direct leak overrides in stable-core
and resets the legacy PI controller. Its structural controller and separate
covariance loop are outside this runner. This study does not qualify that full
feedback loop, changes in published fill, language output or experience, and
authorizes no live parameter change. The companion 24-completion prompt study
remains independent and incomplete; it supplies no reservoir-state comparison.

## Independent Review Follow-Through

Review identified a weak expiry assertion: checking three override values and
absence after five updates could incorrectly accept a four- or five-update
override. The original traces were correct; the acceptance test was incomplete.
The control now retains each post-update remaining budget and requires
`[2, 1, null, null, null]`, with adaptive leak resumed on update four. A fourth
unit test rejects delayed expiry and a replenished restart budget.

Run 03 passes all 12 strengthened controls, all four runner tests and focused
strict Clippy. It ran after the isolated language provider was stopped, not
concurrently with it. Manifest SHA-256:
`a4faf14c143a8bda62936cc5bb085fdc4185c80f703aefe61be620b6a3fb86bb`.
Report SHA-256:
`20255918d37024bbf5c030e8bd43cd8ad1920a5717fda40f4aae8a758d77ecd5`.
Earlier evidence is preserved. The independent review also confirmed all 96
trajectories, 96 paired comparisons, 72 matched-zero comparisons and exact
replay/restart equality against a float32-aware metric recomputation.

The four seeds vary construction and synthetic inputs; exploration noise uses
production's common fixed seed. They are not four independently sampled noise
histories. This limitation does not change the paired comparison or authorize
a broader controller or language claim.
