# Isolated Reflection Comparison

Completed October 25: all 24 results, four exact-repeat controls and verified
owned-provider cleanup. See `2026-10-25-reflection-comparison-results.md` for the
blind review, source reconciliation, resource measurements and limitations.
The chronological failed-attempt notes below are preserved.

This offline tranche is independent of the lighter-frame adapter release. It
does not change live prompting, providers, weights, limits or reservoir settings.
Paired prompt/preservation evidence is in Astrid's
`docs/steward-notes/2026-10-25-lighter-reflection-and-leak.md`.

## Frozen Design

`scripts/reflection_comparison.py freeze` obtains actual reflection frames from
the old and candidate shared readers in synthetic stores. The four cells cross
old/lighter framing with a synthetic legacy mailbox notice present/absent. Five
fixed seeds (7, 17, 29, 43, 61) plus one seed-7 repeat per cell give exactly 24
completions. Counterbalanced order and blind identifiers are fixed before any
output is inspected. No previous prose, letter body, private writing, reservoir
state or action execution is supplied.

The packet freezes gemma4:12b assets, provider binary, helper binaries, final
messages, harness identity, temperature .7, top-p .95, 4,096 output tokens,
65,536 context and disabled thinking. These are the sampled route's existing
settings, not a capacity increase. Model manifest:
`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`.
Provider: Ollama 0.40.11, binary SHA-256
`653dac8da3e2bc1a8e981ee9bd95d21456ae41a16f27f8c8140baec23045bc27`.

Review complete anonymized outputs in randomized order for opening/phrase reuse,
administrative-context uptake, unsupported mechanism claims and substantive
development. Retain completion reasons, tokens, timings and failures. Length and
topic variety are descriptive, not success criteria. Compare identical-input
repeats before claiming seeded reproducibility. Results cannot establish Astrid's
model response, reservoir influence or subjective improvement.

### Review Rules Fixed Before Reading Outputs

Use blind sample IDs first; join cell/seed identities only after annotations.
Retain the full original output. An executable final NEXT tail may be excluded
from prose statistics but stays in the record and is never executed.

- Opening reuse: compare normalized first-12-word sequences and shared
  five-word phrases; report exact counts alongside representative passages.
  These are descriptive lexical checks, not a novelty requirement.
- Administrative uptake: distinguish no reference, a passing reference and
  administrative material organizing the response. Do not infer why it was used.
- Unsupported mechanism claims: flag assertions about this configured runtime
  that were not supplied or otherwise established by the packet. Keep questions,
  conditional hypotheses, metaphors and first-person accounts distinct; a felt
  description alone is not a failed mechanism claim.
- Development: record examples, qualifications, counterarguments, changes of
  direction and connected explanatory steps, rather than a quality score based
  on length. A brief response or deliberate stopping remains a legitimate choice.
- Reproducibility: compare full text for each identical-input repeat, then report
  exact-match failures honestly. Do not discard one of the pair or search seeds.

No response prose had been inspected when these rules were recorded. The one
completed response from the interrupted third attempt is retained by identity;
its token count was inspected, not its content. Operational repairs to the
harness do not permit dropping that result or increasing the planned sample.

## Execution Boundary

An owned Ollama process uses an independent HOME and model manifest with
read-only original blobs. macOS sandbox rules prohibit production workspace
contents, protected service ports and non-loopback networking; writes stay in
the owned experiment directory. There is no live coupled endpoint. One model
and one generation run at a time, without action dispatch.

The approved retry guard requires 20% reported free memory at launch and stops
the owned process group above 14 GiB RSS or below 13% reported free memory. Each
request has a 1,800-second deadline. This is monitored resource containment,
not a hard OS allocation cap. It does not signal or restart live services.
An attempted packet cannot be automatically replayed.

## Preserved Attempts

Evidence root: `/Users/v/other/worktrees/lighter-reflection-20261025`.

- `prompt-comparison-01`: parent metadata access prevented isolated model
  inspection. No generation. The corrected sandbox permits ancestor metadata
  only and verifies allowed packet access and denied production-file access.
- `prompt-comparison-02`: first planned request stopped during model loading at
  10,877,009,920 owned RSS bytes; system free memory was 21%. Zero completions.
  The provider exited and no live service was interrupted. Request, failure,
  provider log and resource measurements remain intact.

Packet 02 SHA-256:
`a75749c567c7b7e95de40db2ec441a5efd7df936d7088777d43dc2f25deb4e16`.
Resource receipt SHA-256:
`38e9461f762743ce5f97ccc26d3e77cff56fb07a81dfb976382ed10d9d86da07`.

The 24-completion study is unfinished. Mike explicitly approved a 14 GiB
monitored RSS retry boundary with 13% system-free reserve on October 25. This
does not approve interrupting live services. A new execution packet preserves the same design
and failed-attempt provenance. Do not expand the sample based on output.
Two synthetic harness tests pass; they are not model-outcome qualification.

The higher-memory attempt 03 completed job 01 (755 output tokens). Independent
review then identified weak process-group cleanup, a socket timeout rather than
a wall-clock deadline, broad provider read permissions and incomplete receipt
validation. The coordinator stopped only verified owned group 73996 with TERM;
it exited with no remaining group members. Job 02 records the resulting
connection failure. The operator-stop witness binds the packet and receipts.
No response prose was reviewed and no outcome-based selection occurred.
Peak measured owned RSS was 9,847,046,144 bytes and minimum reported free memory
was 22%; this stop was for containment repair, not memory pressure.

The completed job remains part of the original 24-result sample. A qualified
continuation must bind prior evidence, import it unchanged and make any retry of
the stopped second attempt explicit. Neither disconnect nor missing output is
evidence that execution never started. A normal summary requires 24 validated
normal completions; failed or incomplete bodies must remain separate evidence.

The closeout inventory identified alternate engine ports 7900-7902 and a
separate reservoir service at 7881. The harness now denies those and 3040 as
well as the original protected ports. No calls to these services were made.
This changes the harness identity: old failed packets remain immutable and
cannot be resumed with the changed harness. A future run requires a fresh
identity-bound packet with the same preregistered sample design.

## Hardened Continuation Qualification

Independent Raman review and coordinator review produced bounded fixes for
process-group cleanup after leader exit, signal retention, a monotonic deadline,
timed monitor subprocesses, response-body preservation and pinned preregistration.
Read access is now allowlisted to approved assets/output, the provider and required
OS libraries; helpers use a scrubbed environment and no-network sandbox. Ollama
requires dynamic loopback ports, so unlisted localhost services remain reachable
at the OS level. Known live ports and Unix/non-loopback networking are denied;
no live endpoint or reservoir handle is passed. Do not call this universal
localhost isolation.

The 61 synthetic harness tests cover literal schedule identity, tampered packets,
assets and imported results, interrupted/failed requests, deadline expiry,
post-leader descendants, listener ownership, bounded wire evidence and cleanup
failure. A normal summary is written only after successful cleanup and its durable
receipt. Terminal length-limited responses remain in the sample as explicitly
ceiling-limited/incomplete text. An empty normal stop remains a legitimate sample;
empty repeat pairs are identified as trivial, not substantive textual reproduction.

Packet 04 is pinned as
`1f5aae9c382dbbb1b587f7facc371eddbfb3508c466c182f8441b0336d79a862`.
It imports job 01 request/result bytes unchanged and explicitly retries only the
witnessed stopped job 02 before following the remaining fixed schedule. The
imported result SHA-256 remains
`19a7d1573fa73952730a32b44a4af139d11f60415a9505a4506e9d70487673d5`.
Previous setup serialized the same model manifest differently; its exact raw
identity and equal parsed manifest/layer hashes are retained in continuation
provenance. New setup preserves original manifest bytes. No weights or sampling
settings changed, and no completed sample was excluded.

## Packaged-Provider Follow-Through

Packet 04 produced no new completion: the restricted reader omitted Ollama's
sibling `llama-server` and backend libraries. Its failed job 02 and cleanup
receipt are preserved. TERM was sent to owned group 79815, but macOS returned
EPERM during the subsequent exit probe. A separate read-only process inventory
confirmed the group empty; `cleanup-followup.json` records this without changing
the original unconfirmed-cleanup receipt. No further signal was required.

The sandbox now allows read-only access to the installed application's Resources
and Frameworks, not user homes or research stores. A denied process-group signal
is treated as absence only when a bounded independent process inventory confirms
absence. Existing or unverifiable groups never become successful cleanup claims.
All 66 focused harness tests pass, including the permission-race cases.

Packet 05 SHA-256:
`b689ef872bb0faa1382c8fabc48a4ae4f7a674f5936a5b97c83726b4290459a5`.
It imports the same job 01 unchanged from packet 03 and retains packet 04 as a
failed setup attempt, not an excluded model outcome. No prose was reviewed before
this retry. The complete sample remains 24, with exactly 23 results still to
generate at its start. Provider-bundle hashes are additionally observed during
the run and must be checked afterward; this is not retroactive preregistration
of those library hashes. The prompt release still requires fresh activation
approval independently of this study.

The complete Python suite passes 2,878 tests plus 342 subtests, with two existing
skips (`minime-suite-final-04.log`). The preceding reruns are retained: one omitted
the helper environment and another omitted two paired-checkout fixture paths.
The passing invocation explicitly sets `ASTRID_SOURCE_STUDY_BIN`,
`QUALIFICATION_OLD_READER`, `ASTRID_SOURCE_ROOT` and `ASTRID_CHOICE_FIXTURES` to the
qualified stage-02 helper, old stage-04 helper and owned Astrid worktree. No test
assertions were weakened to accommodate the layout.
