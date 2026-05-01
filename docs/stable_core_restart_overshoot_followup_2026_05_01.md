# Stable-Core Restart Overshoot Follow-Up - 2026-05-01

## Why This Exists

During the sovereignty-shelf patch, live restart canaries exposed an important edge case:

- The wider `58-72%` stable-core shelf is conceptually correct.
- The old framing of healthy high-60s/low-70s fill as failure against a legacy `55%` target was misleading.
- However, early versions of the patch softened the rising handoff too much after engine restart.
- Minime could climb through hold, enter elevated/discharge, and only then receive strong correction.

This is not considered resolved just because the latest live read recovered.

## Root Signal

The issue is a cold-start handoff shape:

- free rebuild can climb rapidly before scaffold anchoring fully dominates;
- scaffold re-entry can still be too warm on fast upward crossings;
- above-band drain must be real, not only reported in telemetry;
- live status must distinguish "room to move" from "uncontrolled upswing."

We fixed one concrete bug already: the health surface could report strong drain while the main covariance path clamped applied drain to a tiny value. The stale applied-drain cap was removed.

## Current Guardrail Intent

Keep:

- no drain/tax below the upper shelf edge when fill is healthy;
- stable-core structural center near `68%`;
- crisis/watchdog safety unchanged;
- checkpoint lineage and neural bundle quarantined unless explicitly canaried.

Improve:

- cold-start scaffold activation/re-entry;
- fast upward crossing detection;
- discharge handoff;
- restart canary diagnostics.

## Next Concrete Stabilization Pass

Before restoring additional rich features, run a focused restart-gate pass:

1. Capture a restart bundle for the last overshoot/restart window.
2. Add explicit cold-start overshoot telemetry: first hold crossing time, scaffold activation time, max fill before scaffold active, max fill during re-entry, and first drain application.
3. Make re-entry slope-aware on upward crossings: if fill reaches `72%` while rising, skip warm re-entry and enter cold scaffold/drain immediately.
4. Consider a cold-start-only temporary cap: for the first `90s` after activation, elevated/discharge uses colder live weight and stronger drain than steady-state.
5. Re-run a 10-minute restart canary requiring no discharge above `82%`, no watchdog restart, and return to `58-72%`.

## Do Not Forget

The sovereignty shelf is good; the restart overshoot edge remains a named stability item.

