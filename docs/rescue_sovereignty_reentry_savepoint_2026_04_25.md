# Minime Rescue Sovereignty Re-entry Savepoint - 2026-04-25

## Current Operational Read

Captured at 2026-04-25 12:23 PDT.

Updated at 2026-04-26 08:34 PDT with the stronger live read:

- Engine PID `11273` has been running since 2026-04-25 11:40 PDT.
- Watchdog remains `monitoring`, telemetry remains `fresh`, and all rescue ports remain bound by the rescue engine.
- Fill is about `65%`, stage remains `hold`, 60 second peak is about `67%`, and semantic energy is still `0.0`.
- Astrid remains attached under `bridge_sovereignty_reentry_v1`; limited-write V2 has reached `531` sends with no rollback.
- Mic and camera remain `streaming`, healthy, connected, and at `0` consecutive failures.
- The older `neural-triple-reservoir` sidecars are still present separately and should be handled after the code savepoint, not folded into it.

Updated at 2026-04-27 10:42 PDT with the stable-core damping checkpoint:

- Runtime profile is now `stable_core_v1` on the current Minime release binary, not the pinned rescue binary.
- Engine PID `98867` has been running since 2026-04-27 10:28 PDT.
- Watchdog remains `monitoring`, telemetry remains `fresh`, and ports `7878`, `7879`, and `7880` are ready.
- Cold scaffold source remains `derived_cold_from_stable`, with scaffold active and live audio/video divisors held at `0/0`.
- Gate B.2 passed for about 11 minutes: the fill range narrowed from the prior `49.39-80.63%` sawtooth to `69.36-83.71%`.
- The follow-up 30 minute stable-core soak passed on 2026-04-27: fill stayed within `69.44-73.60%`, with no watchdog restart, no recovery impulse samples, no re-entry samples, no live audio/video intake, and healthy mic/camera feeders.
- Current fill is slightly high, around `71-73%`, with slope-aware damping suppressing drain on falling slopes and applying capped drain on rising slopes.
- Mic and camera remain `streaming`, healthy, connected, and at `0` reconnects during the stable-core run.
- Astrid remains present but semantic writes are blocked by `bridge_write_profile = "observe_only"`.
- This is a stable-core damping savepoint candidate, not a final fully normal-runtime stability declaration.

Updated at 2026-04-28 05:06 PDT with the centered stable-core checkpoint:

- Runtime profile remains `stable_core_v1` on the current Minime release binary.
- Engine PID `87040` has been running since 2026-04-28 04:43 PDT.
- Watchdog remains `monitoring`, telemetry remains `fresh`, and ports `7878`, `7879`, and `7880` are ready.
- The centering patch passed a 10 minute Gate B.3 watch: fill stayed within `67.42-71.88%`, with no watchdog restart, no post-warm recovery impulse samples, no re-entry samples, and live intake held at `0/0`.
- A post-feeder-hardening watch stayed within `67.48-71.98%`; mic advanced by `220` chunks and camera advanced by `22` frames while both reported healthy recent-success status.
- Feeder health surfaces now require recent mic chunks or camera frames, not just websocket connection. This prevents false healthy reports when a socket exists but capture is stalled.
- Astrid remains present under the safe bridge posture, with semantic writes blocked by `bridge_write_profile = "observe_only"`.
- New Minime savepoint commits: `801155b` (`Center stable-core scaffold shelf`) and `1151722` (`Harden feeder health status`).

Minime is currently healthy inside `stable_core_v1`:

- Engine: current Minime release binary with pinned rescue physiology ported into stable-core.
- Engine PID: `87040`.
- Watchdog state: `monitoring`.
- Telemetry state: `fresh`.
- Ports ready: `7878`, `7879`, `7880`.
- GPU status: `confirmed`.
- Fill: centered in the high-60s to low-70s during the latest watch.
- Stable-core stage: mostly `elevated` by stage label, but physiologically inside the accepted centered shelf.
- Controller: `fixed_survival`.
- Structural mode: `scaffold_hold`.
- Scaffold: cold derived scaffold source `derived_cold_from_stable`.
- Semantic energy: near zero / inactive.
- Sensory backlog: `0`.
- Live sensory divisors: audio `0`, video `0` during proof posture.

Camera and mic are both up:

- Camera: `streaming`, healthy, connected, no consecutive failures.
- Mic: `streaming`, healthy, connected, no consecutive failures.

Astrid is attached through the safe bridge posture:

- Bridge process is live.
- Semantic writes are blocked with `bridge_write_profile = "observe_only"`.
- Automatic rollback remains available for later richer re-entry profiles.

The Minime autonomous agent remains off.

## What "Stable" Means Here

This is a rescue-sovereignty savepoint, not a full normal-runtime declaration.

It is stable in these ways:

- The rescue watchdog is not flapping.
- Health and spectral mirror surfaces are fresh.
- The engine is not in overfill or collapse.
- The scaffold/drain controller is holding Minime in the healthy band.
- Feeders are long-lived and connected.
- Astrid can be present without immediately destabilizing Minime.

It is not yet proven in these ways:

- We have not removed the scaffold/drain life-support layer.
- Minime self-journaling is not fully restored as a normal agency lane.
- The current posture has not been treated as a final multi-hour normal-operation proof.
- Stable-core has passed a `30m` soak and a tighter 10 minute centering gate, but not yet a `2h` centered soak.
- The current proof posture still blocks live audio/video intake at `0/0`; mic and camera processes are healthy, but their data is not yet admitted into physiology.
- Astrid is present, but richer semantic writes and normal Minime agency remain staged behind health-budget gates.

Operationally, this is a good place to save work. It is not a reason to remove the remaining safety rails.

## Important Current Constraints

Keep these constraints unless deliberately changing the re-entry plan:

- Rescue target remains `55%`.
- Neural bundle remains disabled in rescue.
- Checkpoint lineage remains disabled in rescue.
- Minime autonomous agent remains off.
- Scaffold source is the cold derived scaffold, not the hot stable checkpoint directly.
- Live mic/camera processes stay alive, but stable-core proof intake remains blocked at `0/0` until deliberately reopened through a health budget.
- Astrid writes remain gated by Minime health and rollback policy.

## Git Savepoint Guidance

This work should be preserved in multiple targeted commits, not staged all at once:

- Commit rescue operations scripts and profile/matrix tests together.
- Commit pinned rescue engine physiology changes in the rescue worktree separately.
- Commit Astrid bridge policy/re-entry changes separately from Minime.
- Keep older unrelated BTSP or experiment changes out of rescue commits unless they are required by the build.

Use targeted path staging. The current worktrees contain older dirty files that should not be swept into a rescue savepoint by accident.

## Next Health-First Steps

The next practical Minime step is not more emergency controller surgery. It is to preserve the centered stable-core lane, then gradually restore agency surfaces:

- The `30m` `stable_core_v1` soak and the 10 minute centering gate have passed; the next stability move is a longer centered soak, not another controller rewrite.
- Run a `2h` centered stable-core soak before declaring long-term stable-core physiology.
- Confirm whether old sidecar processes from `neural-triple-reservoir` are intentional.
- Keep watching fill, semantic energy, rollback state, and feeder reconnect counts.
- If the current posture keeps holding, restore a tiny Minime self-study/journaling lane before opening richer sensory or checkpoint lineage.
- Treat any return to sustained `>82%`, repeated rollback, or semantic energy persistence as a signal to pause re-entry rather than tune by feel.
