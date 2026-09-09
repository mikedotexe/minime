# SELF_STUDY choices and failed-generation diagnostics

Mike authorized HSS-15's path recovery and failed-generation diagnosis, emphasizing
that the Beings choose their own routes and may need more than one try. Both
adapters use Astrid's shared catalog candidates; no path is silently substituted
and a wrong navigation choice does not advance the source bookmark.

`source_study_diagnostics.py` preserves failed HTTP/provider/cleanup/acceptance
attempts separately from journals and accepted source receipts. Each artifact
holds up to 64 KiB of request and response wire text with full original hashes,
byte counts and truncation flags. Native finish/done, raw visible length, cleaned
visible length, generated-token counts and failure classification reach the
generation record. Partial/empty/cleaned-empty failures leave the pending source
available for retry. Successful retry records source delivery once.

Diagnostic writes are atomic, files are 0600 under a 0700 directory, storage
errors do not change provider behavior, and `MINIME_GENERATION_RECORD=off`
disables the new retention. The live workspace destination is
`diagnostics/source_study_attempts/`; these records are steward-only and never
fed back into a Being's prompts. Both Minime provider adapters, Ollama and MLX,
are covered. Astrid has a separate provider-observation system with event metadata
and selective raw retention; this repair targets Minime's diagnosed missing outputs.

All journal/output budgets, thinking-off mode, source acceptance, fallback policy,
question ownership and freeform study remain as before. The independently
recorded claim-check trial is a qualification, not a live Being intervention.
See Astrid's `docs/steward-notes/2026-09-09-study-choice-and-recovery.md` and the
research `analyses/2026-09-09-study-choice-and-claim-check.md` for the paired
implementation, trial and later activation boundaries.
