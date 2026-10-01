# Quiet Notebook Return: Minime Adapter

Candidate only, not deployed or merged. Paired branch:
`codex/quiet-study-return-20260930`; base `cc7796a05b8cbc0233fc5f55731f396bd3ddff10`.

Witness: `workspace/journal/self_study_2026-09-30T14-15-20.701876.txt`, SHA-256
`be7e291246059a08e85632b59f5b239b74d096592b493df2e652e9ea8e989a71`.
The exact authored `NEXT: REST` was a completed response to a continuation decision,
not a truncated study. The adapter previously recognized decisions only at EOF.

The adapter now consumes the shared Rust `continuation_decision` marker, retaining
the EOF compatibility fallback. New files use `study_decision` and STUDY DECISION;
such replies are not flagged as verified source studies. Provider generation,
delivery verification, NEXT extraction, REST and scheduling policy are unchanged.

The paired schema-11 reader adds explicit `QUESTION NOTEBOOK` inspection,
`QUESTION PARK NOTEBOOK` and `QUESTION RETURN NOTEBOOK`. Python adds no grammar
or state migration. End-to-end tests use the actual dispatcher and shared helper,
synthetic source and mocked provider wire with the live-write/network guard intact.

The detailed contract, qualification attempts and activation boundaries are in
Astrid's `docs/steward-notes/2026-09-30-quiet-notebook-return.md`. Logs reside in
`/Users/v/other/worktrees/quiet-study-return-20260930/`. Final qualification passes
1,703 Minime tests and 141 subtests, with one existing skip, plus 53 focused tests.
Paired reader: 299 tests; bridge: 2,367 tests and one existing ignore. Strict Rust
Clippy, formatting, domain boundaries and affected deployment/evidence/controller
checks pass. The exact tested helper SHA-256 is
`f74fad6bd0a8289bdcc5fecc6f31c710dfa0705c0ec18a145b72ab197e4ff07c`.
No canonical journal or live state was rewritten. Release packaging, paired
schema transition qualification, Git integration and activation remain next work.
