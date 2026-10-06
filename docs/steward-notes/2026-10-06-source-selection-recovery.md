# Source-selection recovery

Coordinator: Codex, 2026-10-06. Scope: agent adapter and shared-reader release only.

The detailed paired packet lives in Astrid at
`docs/steward-notes/2026-10-06-source-selection-recovery.md`.

This candidate starts at Minime main `cadf6639b25be683f5b9931abbcc66d030e88ce0`.
It carries forward the installed regulation-review repair in
`minime_autonomy/runtime.py` and `minime_autonomy/generation_record.py`, with its
focused tests. The latter remains byte-identical to the live version; runtime
adds only reader decision classification to that existing repair.

The added source-study behavior is narrow: `source_selection_needed` is recorded
as `needs_choice` and authored output is filed under `study_decision`. No generic
host feedback is appended to this recovery prompt. Rust still owns grammar,
candidate validation, ownership, positions and delivery verification.

Source witness: public
`workspace/journal/study_navigation_2026-10-06T02-45-56.180961.txt`, SHA-256
`c7025308d74521fa15ea33b23e114f92ae33c4ba481bbcba5db9cf487035b56c`.
The body selects an intended OPEN, but final NEXT selects CONTINUE. Neither
the narrative nor a previous unselected command establishes source delivery.

Qualification/activation are recorded in the paired Astrid packet. No larger
capacity/provider work, engine or sensory change, automation resume, private
writing disclosure or forced change of activity is included.

Paired activation succeeded on 2026-10-06 at 20:14:25 UTC: agent 88761 -> 25454,
93 qualified source inputs loaded exactly, session 5321 and the durable pending
NEXT restoration preserved. Shared helper SHA-256:
`1ed14cf09483dc546f5e05a8b540150b5cffc1df8bf3a48f7fe5bddaccc7a3e6`.
The 1,920-case complete Python suite passed (one skipped, 144 subtests); 66 focused
cases passed again against that immutable helper. Both-owner staged preservation,
corruption/downgrade refusal and preparation retries passed. See the paired
packet for the retained unsuccessful attempts and exact receipts.
