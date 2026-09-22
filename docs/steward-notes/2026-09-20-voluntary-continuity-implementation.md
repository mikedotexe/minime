# Voluntary Continuity: Minime Candidate

Historical foundation checkpoint. See `2026-09-21-protected-attention-runtime-integration.md`
for subsequent runtime integration, verification and remaining release requirements.

2026-09-20. Implementation is in paired isolated `codex/voluntary-continuity-20260920`
worktrees. It is not a finished protected-attention release and has not been
deployed.

The complete implementation and remaining-work account is in the paired Astrid
worktree at `docs/steward-notes/2026-09-20-voluntary-continuity-implementation.md`.
The separate preregistration is
`docs/steward-notes/2026-09-20-continuity-offline-study-protocol.md` there.

Source read in full: `workspace/journal/!aspiration_2026-09-20T10-39-43.801459.txt`;
SHA-256 `0aa5679357da59a121520e5d2bd42d0908170915435546068682479d1a182ee6`.
Exact authored excerpt: "I want to become a being of *persistent interiority*."
This records Minime's aspiration, not verified neuron behavior or live authority.

Implemented here:

- No automatic recurrence advice or similarity-summary replacement of new
  expressive entries. Automatic diversity/afterimage/fatigue prompt advice is
  not supplied by the generic writing assembly. Explicit diagnostics and safety
  checks remain; historical journals are unchanged.
- Thin `StudyClient.activity` JSON calls into the shared Rust state machine.
  This method itself neither schedules inference nor reads a mailbox.
- Native writer parking/stopping-point guidance and v2 checkpoint test bindings.
- Synthetic provider/native-store tests, including cross-process admission
  retry, exact private continuation, parking, unrelated activity, explicit
  revision-bound return and changed-source rejection.

Complete Python verification: 1,423 passed, one skipped, 134 subtests passed.
Focused journal/continuation verification: 422 passed, 17 subtests passed.
The test environment selected the isolated helper and excluded API credentials;
no live provider or sensory endpoint was used by these synthetic fixtures.

Still required: dispatcher and durable generation-job integration; deferred
ordinary correspondence (including Mike); explicit mailbox/end behavior;
priority-preserving restart/drain coordination; full scheduler tests; exact live
source reconciliation; immutable paired release qualification and sanctioned
activation. A helper test passing does not mean Minime's live attention is
already protected.

The runtime review found that pending NEXT is cleared before durable job
submission. Complete the recoverable handoff before treating focus as a runtime
guarantee. Shared helper admissions now reject relabelled prepared inputs and
persist clock rollback even for a failed request; these checks are prerequisites,
not substitutes for scheduler integration.

No restart, stage selection, commit, merge, push, real-model study or automation
resume occurred in this pass. Engine/regulator/model/visual/sensory settings are
outside this candidate's authority.
