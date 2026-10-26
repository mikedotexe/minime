# Local Experiment Render Reuse

Candidate only. Retain the two projections around mutations; reuse the verified
post-mutation projection only for the following `next.md` render. The extension
observes local experiment/run/dossier/ledger dependencies and their expiry
predicates, including empty shared discovery, directory membership, absent
optional files and dependency path bindings. Populated peer/shared dependencies,
corrupt reads and changed inputs fall back. No authority or admission cache.

The 107 focused tests and 103 subtests cover independent projections, single-use scope, restart,
failed writes, concurrent changes, exact output parity, corruption and time
boundaries. Synthetic populated legacy-experiment tests reduce qualified
write/refresh projection counts from three to two, with complete logical
record/database parity after only fixture/identity/timestamp normalization.
Whole-job performance remains a separate measurement, not a promised speedup.

Independent review caught an expiry edge: observing time before a ledger read
could miss a clock reversal after the actual consumer decision. All six relevant
consumers now observe the timestamp they actually use. The regression advances
100 -> 102 across expiry, then reverses to 100.5; reuse is rejected rather than
rendering the earlier expired result as current. Authority computation itself
still runs independently with its existing comparisons and bounds.

The immutable candidate and preservation results are documented in Astrid's
`docs/steward-notes/2026-10-25-reflection-development-and-render-reuse.md` and
`/Users/v/other/worktrees/reflection-development-20261025`.
No live reflection wording, leak, provider or capacity change. New profiling
contains bounded reason counts only. Fresh rollout approval remains required;
automations stay paused and no push/tag is authorized.
