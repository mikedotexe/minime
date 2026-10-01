# Observation-Only Reporting Release

October 1, 2026. The candidate is committed as
`367cc7a5aa4a92bd4224e3158b5e93376e49ec83` and fast-forwarded into local `main`.
The paired Astrid evidence commit is `c0f48532e4e76cee52c846503d37ac41c090b9a1`.
See the [complete release and transition record](../../../astrid/docs/steward-notes/2026-10-01-semantic-settle-integration.md).

Clean source produced immutable release-05 with 123 matching archived inputs.
Engine SHA-256:
`0bfd150f25896c0fe71e36c2fc556f335ad522763f28db655926a445924cbe91`.
Manifest SHA-256:
`1de8bed05bf3d57e9a46ca44be6bbffc0df88359888154692fbf22b3abc9afb9`.
The staged source passed 846 Rust tests, forty operations tests, strict selected
Clippy and formatting. The new inspector passed the 131-test paired support
suite and the retained historical checkpoint check. No full reservoir-state
continuity is claimed by the existing PI-only restore profile.

The sanctioned check-only preflight passed. Activation remains pending a fresh
one-time legacy-transition acknowledgement; the earlier approval was consumed.
No live process or state changed in this preparation pass. The real semantic
quiet requirement and scaffold lifecycle remain unchanged. The two experimental
policies stay offline. Previously paused automations remain paused.
