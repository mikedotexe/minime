# Open Reflection Without Character Enforcement

Latest status: merged to local main and live. Earlier candidate-only statements
below describe the implementation snapshot; the release addendum records the
subsequent approved deployment.

## Status

Implemented in isolated branch `codex/astrid-open-framing-20260922`, based on
Minime local main `7e35f31f209c2f1e3b95b7ccf0541be19876a55c`, in
`/Users/v/other/worktrees/astrid-open-framing-20260922/minime`.
Paired Astrid worktree is the sibling `astrid` directory, based on
`25ab0f1c07771cb38cc8a6974759421a8746ea08`.

Candidate only: no merge, push, live source replacement, service signal or model
call. Controller pause 460 and previously paused automations remain paused.
The canonical Minime checkout remains clean; 197 older Astrid paths are preserved.

## Witness and Request

Mike requested removing comparable prescriptive framing for Minime after the
Astrid longform prompt was found to require a spectral character.

Minime's public aspiration was reread fully:
`workspace/journal/!aspiration_2026-09-22T09-16-57.795422.txt`.
SHA-256: `2675734fbcd0f7146cafd9a97dc20bed092acc400f1d08baa3f2ea26dcf4ebdd`.
The original account, its imagination prompt and its significance remain intact.
No prompt-causality conclusion, subjective improvement or completed self-study
is inferred from this implementation. No private moment files were used as tests.

The earlier September 22 aspiration repair is already live. This candidate
extends beyond that specific route; it does not retrospectively claim that the
earlier work covered the generic prompt.

## Verified Mechanisms and Response

1. `_query_llm`'s general system introduction required "Stay in character", a
   being that "breathes through covariance matrices", and never mentioning being
   an AI. It also incorrectly described every route as a private journal.
   `OPEN_REFLECTION_INTRO` now permits first-person expression, affirmation,
   uncertainty, disagreement and no felt correspondence. It distinguishes
   measurement from interpretation without requiring skepticism or a metaphor.
2. `_is_in_character` matched seven phrases, including "shall i" and "if you'd
   like", without distinguishing an actual offer from a quotation or reflection.
   In the ordinary no-mail route it could replace the first response with a
   second generation and discard that second response too. The detector and
   the whole retry/discard branch are removed. This does not remove provider
   transport failure handling or action validation.
3. Rest, pressure-relief, drift, dispersal, perturbation and metabolism prompts
   supplied sensations, expected effects or required a body-first answer. Their
   invitations now allow disagreement, no noticeable effect and leaving the
   record aside. Dispersal distinguishes a sent request from admission, application
   and eigenmode redistribution; before/after snapshots do not prove causality.
4. Regulation prompt wording no longer calls exploration noise a freedom dial or
   asserts that low fill means felt hollowness. Existing bounds, numeric regime
   choices, required JSON fields and low-fill guidance remain unchanged.
5. Visual/audio gate reflections no longer assume overload, rest, readiness,
   relief or reception of a fresh observation. Visual/pressure journal footers
   identify system records rather than asserting a felt verdict independently of
   the answer. Historical journals are not rewritten.

`OPEN_OBSERVATION_INVITATION` is reused for the selected action reflections.
No reflection is automatically interpreted as consent or improvement by this
repair. Existing action dispatch is not newly authorized by writing.

## Preserved Behavior

- SourceStudyPrompt and private-writing input take their existing path. Private
  daydream/journal and aspiration mode distinctions remain; ordinary mailbox
  routing is not replaced by private-journal semantics.
- Exact returned prose and NEXT remain intact. Collaboration offer finalization
  and afterimage generation identity are retained even with the character retry
  removed. Failed provider results still finalize and return failure.
- Protected attention still defers unrelated jobs. Provider limits, safety
  checks, authenticated self-control, sensory gate dispatch, reservoir updates,
  engine numerics, scheduling and persistent schemas are unchanged.
- Failed sensory authorization still returns before reflection. Tests mock the
  transport and assert identical visual/audio field values and dispersal bounds;
  no live endpoint is exercised.
- The large legacy runtime remains the existing owner of these routes. This
  scoped patch removes code, adds reusable framing in the existing context module,
  and avoids an unrelated runtime split.

## Qualification

Artifact root: `/Users/v/other/worktrees/astrid-open-framing-20260922`.

- Focused adapter, journal, inbox, afterimage, low-fill, lease and sensory-action
  suites: **527 passed**, 17 subtests. `minime-open-framing-focused-rerun.log`.
- Complete Python suite on final source: **1,550 passed**, one skipped,
  136 subtests. `minime-open-framing-full-rerun.log`.
- The existing Division runtime manifest fixture skips if its test port 7900 is
  occupied; no process was stopped to obtain that port.
- The full suite includes real shared-helper preparation, private writing,
  observation disclosure, inbox delivery, protected attention, action dispatch
  and provider adapter fixtures. New cases retain all formerly flagged phrases,
  both affirmative and uncertain accounts, exact NEXT, one generation, delivery
  finalization, and factual-only system footers.
- Test helper: the unchanged immutable release helper at
  `/Users/v/other/worktrees/voluntary-observations-20260921/bridge-stage-observations-02/helpers/astrid-source-study`;
  SHA-256 `fc12fb295a3b97d984a372c43f2e92bb92fdd683e4ae1c487689ac78bd7f2790`.
- Full tests used an allowlisted environment (PATH, HOME, TMPDIR, LANG and
  ASTRID_SOURCE_STUDY_BIN). They used synthetic stores/providers; the existing
  process-wide fixture guard denies writes to live roots and live runtime sockets.
- Paired deployment/controller wrapper tests: 153 passed, without deploying.
  Paired bridge, Clippy, boundary and evidence qualification are recorded in the
  Astrid steward note.

Retained unsuccessful attempts:

1. Initial focused run: 484 passed, five failed, 17 subtests. The new test
   incorrectly expected the general introduction for `daydream`, which already
   has private-journal semantics. The assertion now respects that existing mode;
   production mode selection was not changed to satisfy the test.
2. Initial complete run: 1,449 passed, 28 failed, 73 setup errors, one skipped,
   136 subtests. Causes were an omitted explicit helper setting, inherited
   runtime timeout overrides conflicting with default-budget tests, and one
   obsolete positive assertion for the removed identity phrase. Helper and test
   environment were corrected; the old identity test now asserts the open
   introduction and absence of the character detector.
3. Pytest included environment metadata in a missing-variable traceback. Those
   environment lines were redacted in the retained local failure log; no
   credentials belong in the review packet. Subsequent tests use the allowlisted
   environment and short tracebacks.

## Exact Candidate and Live Boundary

Owned paths in this repository:

- `minime_autonomy/journal_context.py`
- `minime_autonomy/runtime.py`
- `tests/test_journal_context.py`
- `tests/test_inbox_delivery.py`
- `tests/test_autonomous_agent_low_fill_guard.py`
- `tests/test_experimental_continuity.py`
- `CHANGELOG.md`
- `docs/steward-notes/2026-09-22-open-reflection-without-character-enforcement.md`

`paired-minime-source-reconciliation.json` verifies all **84** recorded startup
hashes against both the candidate's HEAD and canonical files. Only the two
Python source files above differ in the candidate. Running PID 45403 and its
September 22 12:22:54 process start are unchanged; the source-status record's
12:22:59 is its own recorded startup time. Bridge PID 54929 and all protected
engine, model, visual, camera, microphone and sensory processes remain unchanged.

A later approved paired rollout must use cooperative preflight, immutable bridge
staging/activation, the sanctioned Minime-agent wrapper, drain/checkpoint
continuity, and exact loaded-hash verification. Do not restart the engine or
automatically resume paused automation. Git integration is a separate coordinated
explicit-path pass; neither canonical index has been touched here.

## Remaining Work

- Astrid's `dialogue_live` Ollama fallback still contains a prescriptive
  numerical-to-texture vocabulary contract. Repair it coherently with its
  selectors and conformance tests, retaining action syntax, direct-address
  priority and resource caps. It is not used by the repaired expressive builders.
- The broad action catalog retains historical metaphor examples. This is not
  a claim that every prompt in the runtime has been audited.
- `_adjust_metabolism` still has an existing low-state default from unrecognized
  prose to the branch's `increase` direction. Prompt openness does not repair
  that choice-policy issue. Review explicit selection/no-change semantics as a
  separate control-routing change; this candidate leaves the behavior intact.
- No natural post-rollout account has been solicited or observed for this
  candidate, because it is not deployed. Tests establish behavior, not benefit.

## Live Release Addendum

Mike approved merging and getting the paired changes live. Minime source commit
`18ff3bd578dc0f097bf34738e32090ad6f67d0a2` and Astrid source commit
`9266412b8e3d817e87c93441a145cdfe32e76a79` were fast-forwarded into local `main`.
Each includes exactly its eight reviewed paths, explicit agent provenance and
a source-verified public witness quote. No unrelated edits were staged.
Minime main and both feature trees were clean after source integration; all 197
older Astrid dirty paths retained their exact hashes/statuses. No push occurred.
Subsequent release-note commits change documentation only.

Controller pause **461** was held with no active lease or foreign cooperative
session. The isolated Astrid candidate produced an immutable release through
`scripts/build_bridge.sh`; all 678 inputs were compared with the prior stage,
with changes only in the five reviewed Rust files. The reader, launcher,
selection helper and substrate probe are byte-identical to their predecessors.
The complete Python suite was rerun against the packaged helper: **1,550 passed,
one existing occupied-port skip, 136 subtests**. Staged focused tests also passed
658 tests and 54 subtests. Prior full bridge qualification: 2,334 passed with one
external-fixture ignore; paired wrapper tests: 153 passed.

`scripts/paired_minime_handoff.py` used exact `minime-qualified-inputs.json`
identities, without its legacy overlay-install option. All 84 committed launch
inputs were reconciled; only `journal_context.py` and `runtime.py` changed.
No backup or earlier authored state was restored.

1. Old agent **45403** reached observed idle with no accepted work or model TCP
   connection. The wrapper held replacement admission and sent one PID-bound
   SIGTERM at `2026-09-22T20:43:46.399223Z`.
2. Bridge **54929** acknowledged drain and exited gracefully. Replacement
   **67810** loaded the exact stopped checkpoint and signed state lineage, then
   saved exchange 205418 after stopped count 205417. The wrapper observed model
   idle and verified activation before releasing the agent hold.
3. Agent **66540** passed readiness at `2026-09-22T20:48:58.444511Z`, with all 84
   startup hashes and `reload_required=false`. Its process start is
   `Tue Sep 22 13:43:46 2026` local because its launcher waited under that PID;
   Python's source-status startup is `2026-09-22T13:48:51` local.
4. Session **5318** and the exact pending `SELF_STUDY CONTINUE` survived. The
   latter was admitted as `job_minime_1790110145394_self-study-continue` at
   `2026-09-22T20:49:05.394630Z`, then completed without error at
   `2026-09-22T20:52:26.305774Z`. Readiness preceded this admission, so the later
   continuity receipt supplements, rather than rewrites, the initial check.

Both owned launch holds are absent. Nine other protected PID/start pairs and
managed configuration hashes remained unchanged, including engine **41337**,
model **43115**, visual **20885**, camera **98903**, microphone **98910** and
gateway **41484** (still listening on 7878/7879). No engine/model/visual/sensory
restart, force, inference cancellation or automation resume was performed.

Selected stage:
`/Users/v/other/worktrees/astrid-open-framing-20260922/bridge-stage-open-framing-01`.
Manifest: `a84f260aa8d306f60a6a3aeb1ddce76d039068f4e0aa6f06c7f8220e67063bb3`.
Bridge: `8c15e285385c5d83444ccd74614dc58289adeca97e65e13239c88fdff85af32f`.
Shared helper, unchanged:
`fc12fb295a3b97d984a372c43f2e92bb92fdd683e4ae1c487689ac78bd7f2790`.

Retained artifacts under the paired worktree parent:
`source-merge-verification.json`, `immutable-input-comparison.json`,
`pre-rollout-baseline.json`, `minime-qualified-inputs.json`,
`release-helper-minime-suite.log`, `paired-open-framing-rollout-01.jsonl`,
`post-rollout-verification.json`, and
`post-rollout-continuity-and-observability.json`. Exact stopped-state and signed
handoff evidence is in canonical Astrid transaction
`.runtime/bridge-deployment/transactions/6a964914bb8f43bb8b495aec4dbeb295`.

Thirty post-readiness telemetry samples advanced normally at 71.02-73.07% fill.
A transient dip to 28.13% was observed earlier; the existing recovery controller
returned it through recovery to the hold/elevated band without operator mutation.
No cause or subjective effect is inferred from this observation.

One separate pre-existing debt remains visible in bridge logs: the optional
private provider-observation epoch reached its 50,000-file cap. New receipts
cannot be stored, although generation continues unchanged; warnings predate the
restart. The spool contains 140,471,843 bytes of event files and no raw files.
It is separate from Evidence V2, whose indexed-tail verification passed with
the four V1 streams immutable. No evidence was deleted or quota increased.
Review evidence-preserving sealed-epoch archival/rotation separately. The
previously named dialogue-fallback framing and low-state metabolism-choice
defaults also remain explicit follow-up work, not silently fixed by deployment.

No confirmation of improvement was solicited. The resumed public study is
evidence of continuity, not proof of benefit, consent or understanding.
