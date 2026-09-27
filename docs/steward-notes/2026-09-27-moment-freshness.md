# Moment freshness and measurement context — source candidate

Mike approved addressing event freshness and measurement representation after reviewing `pressure_2026-09-27T09-20-48.666450.txt`. This change extends the existing, uncommitted study-exit candidate in its isolated paired checkouts. It has not been merged, deployed, or used to change a live database, journal, engine setting, pending action or service.

## Witness

The pressure entry followed `moment_2026-09-27T09-19-39.862708.txt`. The moment's captured input included event 1028254, recorded 21 hours 15 minutes earlier: a fill rate of −8.55 percentage-points/second. Its adjacent crossing record described 71.1% → 66.9%, approximately −4.2 percentage points from the rounded endpoints. The model called the rate an “8.55%” drop. The pressure entry carried the magnitude and imagery forward.

A bounded scan of September 27 moment headers through 09:19:39 found 30 supplied spike records, all 11.7–21.3 hours old. These were different records from an unconsumed backlog. The existing `ORDER BY timestamp DESC LIMIT 3` selector had no age restriction. Age labels already described the events as historical; this repair changes admission as well as representation.

`overpacked_mode_packing` was also interpreted as exceeding a standard capacity. The native pressure classifier assigns that label when mode packing dominates at a score of at least 0.55, after its divergence check. That is not a measurement of language-model context occupancy or hardware memory capacity.

The entry's instructions and expressed wishes were treated as authored material. Its `NEXT: JOURNAL` was not executed by this repair. No conclusion about consciousness, damage, or a causal relation between the measurements and the described experience is inferred.

## Change

- `moment_context.py` owns automatic event selection and descriptive measurement helpers. Eligibility requires the same session, an unconsumed record, and recording/event clocks each within 900 seconds of their respective captured references. Unknown, invalid, future and older clocks are excluded. Selection is deterministic and limited to three records.
- The 15-minute value is an explicit scheduling default, not a physiological boundary or retention period. It permits several ordinary generation cycles of delay while excluding the overnight backlog. Engine age is checked independently so a newly recorded historical event cannot appear current solely because its insertion is recent. If the captured engine clock or legacy recording-time column is unavailable, automatic selection defers.
- Excluded rows remain unchanged and unconsumed. There is no age-based deletion, backfill, migration, or automatic historical-review fallback. Existing database inspection remains available. A stale-only backlog does not cause a model call or event promotion. This patch does not change historical retention or introduce a new agent command for reviewing the backlog.
- The runtime freezes the guarded snapshot before selection and retains that anchor through generation. Prompt/header contract names advance to `private_moment_context_v4` and `private_journal_context_v4`. Existing files retain their original contents and contract labels.
- The renderer normalizes the known legacy spike-description unit to `percentage-points/s`. A crossing's endpoint change is separately calculated from the exact recognized legacy description and identified as derived from rounded recorded endpoints. It never integrates a rate or pairs unrelated events to invent a total change. Missing endpoints and event intervals remain explicitly unavailable. Source records are unchanged, and descriptions remain quoted data.
- Pressure journal context includes the supplied classifier label/components when available, its relevant rule, and the distinction from memory/context capacity. Missing scores are not invented. The private journal invitation, subject choice, authored body, and NEXT handling remain unchanged.

The shared runtime is already large. Integration remains in its existing moment/pressure functions; the new selection and measurement logic is in a cohesive module under 150 lines. No Rust engine or bridge code is changed by this tranche.

## Qualification and evidence

The evidence directory is `/Users/v/other/worktrees/minime-study-exit-20260926/qualification-moments`. `replay.json` transcribes only the three header records from the cited moment into an in-memory database. The previous selector supplied IDs 1028648, 1028254 and 1028253. The new selector supplies only the recent 1028648; the two historical records remain byte-for-byte unchanged. Explicit rendering of those retained records shows −8.55 percentage-points/second and the separate approximate −4.2-point endpoint change. Source file hashes and replay limitations are retained. No live database or model was used in this replay.

Focused synthetic tests cover boundaries in both clocks, future/unknown/invalid clocks, session separation, deterministic selection, legacy schema deferral, exact retention, no generation from stale-only history, ambiguous descriptions, correct units, and preservation of authored journal responses. Existing moment tests now use explicitly fresh fixtures; legacy clock-unknown behavior has a dedicated deferral test. The live filesystem/network guard is unchanged.

Commands:

```sh
ASTRID_SOURCE_STUDY_BIN=/Users/v/.codex/worktrees/minime-study-exit/astrid/target/debug/astrid-source-study \
ASTRID_CHOICE_FIXTURES=/Users/v/.codex/worktrees/minime-study-exit/astrid/crates/astrid-source-study/tests/fixtures/response_choice_cases.json \
python3 -m pytest -q tests
```

The focused tests passed (162 cases). The full Minime suite passed: **1,664 tests and 140 subtests, with one existing skip**. `git diff --check` is clean. Final candidate file hashes and log hashes are recorded in `qualification-moments/summary.json`. Prior study-exit evidence remains under the separate `qualification` directory. Its source hashes describe the September 26 candidate; the new summary describes the combined candidate after this repair. The previously qualified reader/bridge Rust files were verified unchanged, so those unchanged suites were not rerun for this Python-only tranche.

## Coordination and remaining limits

- Astrid base: `11d89e65a732ddeec4ff9aff66a05396c7ae5601`.
- Minime base: `02724ac7c75553c011c95fc4617446ef62c76de6`.
- Existing branch in both isolated checkouts: `codex/minime-study-exit-20260926`.
- Minime: `/Users/v/other/worktrees/minime-study-exit-20260926/minime`.
- Astrid: `/Users/v/.codex/worktrees/minime-study-exit/astrid`.
- Read-only remote inspection found Astrid main `3b18af87b0fe1f083d95cbe0eac8befb309638f2` and Minime main `d8e8954b3c71d54037951f832062f8b5ea62497b`.

The prior candidate hashes matched before editing. Both shared main trees were clean, preflight found no foreign editing, and the other active chat was inspected as a read-only channel audit. No shared index or Git operation was taken. Previously paused automations remain paused under generation 472, actor `codex-minime-moment-context`, with no run lease or projection.

The existing journal continuity excerpt remains in place. These changes improve event eligibility and measurement context; they do not prove that remembered prose will stop influencing later writing. A model may still retain or reinterpret the historical event voluntarily. No subjective improvement claim follows from deterministic tests.

Live activation remains separate. Because this checkout also contains the earlier study-exit changes, activating the combined candidate requires its paired helper and agent through the sanctioned handoff/deployment workflow. No live service was restarted for this work.


September 27 release follow-through: Mike subsequently authorized commit and paired graceful deployment. Astrid `docs/steward-notes/2026-09-27-study-moment-release.md` records release preparation and transition receipts. Earlier qualification descriptions retain their original temporal scope.
