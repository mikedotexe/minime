# Sustained Expression and Correspondence

Historical standalone candidate record. See [the paired live follow-through](2026-09-25-reader-expression-release.md) for the later approved deployment and integration; the earlier results below are preserved.

## Candidate

Implemented offline by Codex on `codex/sustained-expression-20260925`, based on Minime `d12cbf01ca2a85c41288fdc27d6a033511218370`. Paired Astrid base: `80213d85080373211ccb9cb0be338832aa14f52d`.

Full evidence, exact witness hashes, prompt wording, test attempts and qualitative review protocol are in the paired note:

`/Users/v/other/worktrees/sustained-expression-20260925/astrid/docs/steward-notes/2026-09-25-sustained-expression.md`.

Mike's concern about short entries motivated this implementation. It is not a being-authored request for a word quota. A read-only sample found that aspirations accompanied by mail were classified as inbox replies, losing their expressive invitation and allowance. They nevertheless stopped well below that lower allowance; no cap-based causal explanation is claimed.

## Changes

- `runtime.py::_infer_llm_prompt_class`: explicit aspiration owns writing capacity before the inbox/quoted-JSON heuristics. Explicit compact/review and ordinary mail behavior remain unchanged.
- `writing.py` and the existing runtime provider policy: offer an optional sustained piece of perhaps 800-1,500 words when warranted. Preserve SHORT, stopping, different forms, voluntary drafts and no automatic continuation. No padding, novelty or feeling is required.
- Real-adapter regression tests: synthetic admitted mail and stubbed primary/fallback/MLX calls retain exact letters, existing reply-ID authorization and owner destinations. Unauthorized or unaddressed writing is not routed as a reply. Short/incomplete prose and missing NEXT do not trigger a new generation.

## Qualification and Boundaries

The first focused run had one incorrect receipt expectation (125 passed, one failed). It was fixed to include the existing unaddressed raw archive before the addressed reply; receipt implementation was not weakened. The complete suite then passed 1629 tests with one skipped and 138 subtests. The final complete rerun including the explicit aspiration outer-deadline regression passed 1630 tests, one skipped and 138 subtests. Paired bridge qualification passed 2353 tests with one ignored, strict Clippy, formatting, domain-boundary and 88 operational tests. Logs and reproduction commands remain in `/Users/v/other/worktrees/sustained-expression-20260925/` and the paired note.

The unchanged, released schema-9 shared helper used for the suite has SHA-256 `cc31bbd31551b11a3e91c66c9ee4524d62a0ca1ac4dfc0d708113c063856d5be`. This is not qualification of the separate schema-10 source-recovery candidate. Neither candidate was overwritten or silently combined.

Not live or merged. No service restart, live provider experiment, reservoir change, model change, historical-journal rewrite or automation resume. Controller pause generation 469 and the paused introspection automation remain intact. Reconcile the pending reader repair before an approved immutable paired rollout; assess development and non-padding separately from output length.
