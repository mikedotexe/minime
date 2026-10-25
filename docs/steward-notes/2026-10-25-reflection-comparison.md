# Isolated Reflection Comparison

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

## Execution Boundary

An owned Ollama process uses an independent HOME and model manifest with
read-only original blobs. macOS sandbox rules prohibit production workspace
contents, protected service ports and non-loopback networking; writes stay in
the owned experiment directory. There is no live coupled endpoint. One model
and one generation run at a time, without action dispatch.

The current guard requires 20% reported free memory at launch and stops the
owned process group above 10 GiB RSS or below 7% reported free memory. Each
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

The 24-completion study is unfinished. A proposed 14 GiB monitored RSS boundary
with 13% system-free reserve requires a separate decision; it is not implemented
or approved by this note. A new execution packet must preserve the same design
and failed-attempt provenance. Do not expand the sample based on output.
Two synthetic harness tests pass; they are not model-outcome qualification.
