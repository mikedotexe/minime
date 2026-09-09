# Shared study context

The shared reader now carries recent complete visible answers, explicit excerpts
that retain endings when needed, and optional question-directed RELATE/two-page
SESSION choices. Minime honors its 24,000-byte protected input budget and
32,768-token SELF_STUDY Ollama context on primary/fallback lanes. The helper
remains the same immutable artifact used by Astrid. Older helper outputs retain
16,000-byte/10,240-token defaults during rollout. The 4,096 output ceiling and
production thinking-off setting remain. Full provider tests verify no truncation.

Qualification and ordered rollout are recorded in Astrid's
`docs/steward-notes/2026-09-09-study-context.md` and research HSS-14. Reload this
adapter before activating the larger shared-reader input. The existing large
`runtime.py` receives only provider-budget hooks; reader policy stays in the
shared reader and wrapper, with no new subsystem inside the runtime.

Author/provenance: Codex Astra interactive; Mike approved the repair based on
Minime's nine selected September 9 source studies.
