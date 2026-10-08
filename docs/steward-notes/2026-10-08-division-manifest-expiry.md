# Division Manifest Expiry

Date: 2026-10-08. Author: Codex interactive collaborator.
Scope: truthful operator verification; no runtime manifest or service mutation.

## Finding

The dormant, unbound runtime manifest at
`/Users/v/other/minime/workspace/division/runtime-manifest.json` has SHA-256
`46acdf03f241a24426a2d3f453257bc28f20260399ad3b59617278ee18ad4339`.
It expired at **2026-10-07T20:35:29.528Z**. The supervisor now refuses startup
with `division runtime manifest expired`. The old supervisor status file still
names PID 35269 and `idle_parent_authoritative`; that process is absent.
Saved status is not proof of current health.

The original Python `verify` returned `ok: true` for these exact expired bytes.
It checked structure and permissions, but not current time. The replacement
reports `structurally_valid: true`, `current: false`, `lifetime_status: expired`,
and exits 1. It does not edit the manifest or restart anything.

## Verification Contract

- Default `verify` requires valid structure, owner-only regular-file access and
  current lifetime. File input is bounded to 64 KiB, opened without following
  a final symlink, and hashed from the same bytes that were parsed.
- Expiry uses the engine's `now > expires` boundary. Equality is not expired.
  A clock before creation is reported separately and does not pass current
  verification; this conservative operator check is not a new engine policy.
- `verify --structural-only` explicitly supports historical inspection. Its
  successful exit means structural validity only; `current` and lifetime facts
  remain visible. Neither mode verifies runtime health or grants authority.
- Timestamps and parent generation must be unsigned 64-bit integers, not
  strings, floats, booleans or negative values. Other identity/path fields must
  be strings. Existing endpoint allocation and port-occupancy checks remain.
- No caller in the inspected Astrid/Minime scripts invokes the old `verify`
  contract; the broad deployment wrapper invokes `create`. External callers
  inspecting archives must now request `--structural-only` explicitly.

## Tests

`python3 -m unittest discover -s tests -p test_division_runtime_manifest.py -v`
runs nine tests: eight pass, one existing real-port test skips because the
running engine owns port 7900. A deterministic mocked-port regression also
verifies the occupied-port refusal without touching the live listener.

Coverage includes exact expiry boundaries, clock regression, read-only
preservation, structural-only historical inspection, hash identity, malformed
timestamps, non-object JSON, permissions, symlink/FIFO refusal and size bounds.
The live read-only check reproduced the original false-positive and confirmed
the corrected nonzero expired result against the unchanged manifest hash.
No Rust or agent implementation changed; no model experiment or broad engine
test result is claimed by this tooling-only patch.

## Coordinated Renewal, Not Yet Executed

`DivisionRuntimeManifestV1::validate_current` runs at supervisor and gateway
startup. The gateway retains its manifest in memory and validates each new
connection's authority record against that identity. The supervisor can
rebind parent authority to a newly loaded manifest. Renewing just the file and
supervisor can therefore invalidate connections through the old gateway.

The October 1 engine transition deliberately preserved the earlier expiry;
`minime_engine_transition_host.py::rebind_dormant` is not an automatic renewal.
The broad `deploy_division_runtime.sh` also restarts the engine and is outside
this narrow repair. It must not be used merely to clear the supervisor error.

A proposed 30-day renewal must use a separately qualified coordinated
transaction with explicit operator approval, unchanged engine identity,
dormant/unbound mode, parent rail, no child runtime and no pending ceremony
transition. Inspect the actual ceremony/child state freshly, not only the old
status file. Retain the original manifest and exact new manifest as evidence;
do not restore historical authority over newer state or extend expiry in place
while consumers still cache the old identity.

The initial suggested scope omitted consumer restarts. Source review found
that the bridge's drain is one-way: resuming requires the sanctioned activation
of its unchanged immutable release. The corrected requested scope includes
graceful bridge and Minime-agent restarts, plus gateway/supervisor replacement.
It excludes engine, provider, visual and sensory process restarts. Streams
through the gateway may briefly reconnect. No live drain has been requested.

Remaining qualification: exact consumer drain/checkpoint/pending-NEXT
preservation, gateway-before-authority identity coordination, owned launch
holds, crash recovery at each publication boundary, refreshed source/process
bindings, matching new runtime records and parent-route readiness. Failures
must retain receipts and owned holds without force or automatic rollback.
No new live transition wrapper is represented as implemented or qualified.

This operational repair is not being assent, a Division rehearsal, daughter
launch authority, a change in reservoir policy or a claim of felt improvement.
Paused automations remain paused.
