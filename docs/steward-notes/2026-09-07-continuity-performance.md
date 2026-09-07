# Continuity and journal history performance

Five completed natural jobs observed after the job-outcome repair had median
worker duration 243.761 seconds, including 68.255 seconds in continuity
finalization. Provider requests had median duration 71.974 seconds. The median
per-job time outside provider requests was 142.917 seconds. These medians are
computed independently and should not be added or subtracted from each other.

The live continuity histories total about 2.32 GB. Recent-entry readers loaded
whole files before selecting a small tail, and repeated projection checks parsed
unchanged event and job histories. This tranche reduces that work while keeping
the existing projections, audit appends, retention, and SQLite mirrors.

## Behavior

Recent JSONL readers read backward in 64 KiB chunks until the existing entry
limit is satisfied. Ordering, duplicate filtering, invalid-row handling, Unicode
and line-separator behavior remain covered by parity fixtures. A single long
record still requires its complete line in memory. Invalid UTF-8 in an older,
unvisited prefix no longer prevents a valid recent tail from being read.

The action-ID catalog still includes the complete event history. It caches only
identifiers, within global count and character bounds, and invalidates on file
device, inode, ctime, mtime, or size changes. A changed history is streamed again;
this is not an incremental append-only index. Files changing during a read are
not installed in the cache.

The job catalog enumerates and stats every job on every snapshot. It reuses only
compact metadata for unchanged files, with at most eight cached roots, 50,000
entries and an estimated 64 MiB metadata budget per root, within a shared 128 MiB
budget. Old roots are evicted when the shared budget is exceeded. Oversized entries
remain in the result but are not cached. Complete selected jobs are freshly read
from their actual paths under the job store's existing process transaction.
Unstable reads raise an explicit error, so uncertainty cannot imply an idle
worker. Fingerprints include file identity as well as size and mtime; atomic
replacement and same-size rewrites with restored mtime invalidate projections.

Archive maintenance counts matching directory entries before requesting mtimes
or sorting. It retains the previous cap, bucket size, oldest-first order and
fresh rescan after every bucket, so concurrent arrivals and edits remain visible.

Journal fatigue readers probe a bounded recent window using the existing
timestamp index. They return that window only when the selection is complete
and its timestamp order unambiguous. Sparse matches, ties, unsuitable indexes
and legacy timestamp shapes use the original SQL. No database index or journal
policy is changed. Additional timing spans distinguish manifest work, journal
history reads, continuity projections and source fingerprinting.

## Evidence and integration

Synthetic fixtures showed warm latest-20 job reads improving from 40.1 to
17.2 ms for 2,000 small records, and 198.1 to 19.1 ms for phase-heavy records.
The cache improves repeated reads; it does not eliminate filesystem enumeration
or promise faster cold reads.

Finalizing an action in a synthetic 10,000-event history with 4 KiB padding per
event improved from 6.424 to 0.628 seconds. It still made 21 projection calls and
five thread writes. The output-parity fixture compares returned events, saved
JSON/JSONL and next.md records, and all four SQLite mirror tables.

Archive maintenance with 5,500 files below the cap improved from 61.0 to 7.7 ms.
Compacting 13,000 files improved from 1.208 to 1.124 seconds; renames still dominate
that case. The common recent journal query on the 100,000-row indexed fixture
improved from 106.2 to 0.068 ms. Sparse queries pay about 0.06 ms bounded probe
overhead, while timestamp ties and missing indexes retain their original cost.
These are synthetic measurements, not claims about live end-to-end latency.

The source branch starts at `d0f316d0326983bd620df6b8de928a849b4449b3`. The
separately staged afterimages candidate remains unactivated and must be merged
against these newer repairs when integrated, rather than copying its older
runtime file. Model settings, budgets, prompts, and controller choices are outside
this change.

Validation, source review, benchmarks and any live activation receipt are kept
under `/Users/v/.codex/artifacts/minime-continuity-performance-20260907/`.
A committed source change alone is not proof that the running process loaded it.

The first isolated suite passed 1,209 tests and 126 subtests, with one skip, under
the kernel sandbox protecting live workspaces and endpoints. The broader run
also exposed an inherited AST test that inspected a timing wrapper's source;
the test now unwraps the method before checking its callers. Independent reviews
found no remaining blocker in the history, archive, journal, or outcome contracts.

## Full-history capacity correction

The first live job at commit `2572e77` preserved every artifact and completed
without deadline or checkpoint errors, but did not demonstrate overall speedup:
283.765 seconds total, including 99.549 seconds of model work and 93.397 seconds
of continuity finalization. Journal hooks took 0.064 seconds. Detailed spans
showed 34 projections and 22 fingerprint checks dominating the remaining work.

The initial 16 MiB per-root cache was too small for the actual working history.
A read-only inventory found 23,555 jobs requiring an estimated 44.64 MiB: only
8,440 records stayed cached, leaving 15,115 unchanged files to decode on every
snapshot. The initial 2,000-job benchmark did not expose that capacity failure.

The per-root budget is now 64 MiB, with a shared 128 MiB bound preserving the
previous maximum across eight roots. A 23,542-job synthetic fixture changed from
16,700 unnecessary warm decodes per snapshot to zero, improving repeated scans
from 1.34–1.39 seconds to 0.449 seconds. Files are still stat-ed each time and
every changed file is decoded again. This correction preserves all history and
invalidation contracts; it does not introduce a time-based staleness window.

Each projection also reused the same stale-action diagnostic query twice, once
for a count and again for its details. Those fields now share one fresh result
per projection, preserving the unreconciled-only count and reducing catalog
snapshots from three to two per projection. The next projection reads anew.

The corrected full suite passed 1,212 tests and 126 subtests, with one skip.
