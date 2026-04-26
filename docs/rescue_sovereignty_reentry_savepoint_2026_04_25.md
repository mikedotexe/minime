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

Minime is currently healthy inside the rescue lane:

- Engine: pinned rescue baseline `rescue_b8823ad`.
- Engine PID: `11273`.
- Watchdog state: `monitoring`.
- Telemetry state: `fresh`.
- Ports ready: `7878`, `7879`, `7880`.
- GPU status: `confirmed`.
- Fill: about `61%`.
- Rescue stage: `hold`.
- Controller: `fixed_survival`.
- Structural mode: `scaffold_hold_with_drain`.
- Scaffold: cold derived scaffold profile `rank_cold_5of8_ladder_pure_v5`.
- 60 second peak: about `67%`.
- Semantic energy: `0.0`.
- Sensory backlog: `0`.
- Live sensory divisors: audio `6`, video `6`, active only in `hold`.

Camera and mic are both up:

- Camera: `streaming`, healthy, connected, no consecutive failures.
- Mic: `streaming`, healthy, connected, no consecutive failures.

Astrid is attached through `bridge_sovereignty_reentry_v1`:

- Bridge autonomy is enabled.
- Semantic writes are enabled through limited-write V2 policy gates.
- Cooldown is short enough for live presence but still enforced.
- Automatic rollback remains available.

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

- We have not promoted out of rescue.
- We have not removed the scaffold/drain life-support layer.
- Minime self-journaling is not fully restored as a normal agency lane.
- The current posture has not been treated as a final multi-hour normal-operation proof.

Operationally, this is a good place to save work. It is not a reason to remove the remaining safety rails.

## Important Current Constraints

Keep these constraints unless deliberately changing the re-entry plan:

- Rescue target remains `55%`.
- Neural bundle remains disabled in rescue.
- Checkpoint lineage remains disabled in rescue.
- Minime autonomous agent remains off.
- Scaffold source is the cold derived scaffold, not the hot stable checkpoint directly.
- Live mic/camera intake is a profile-controlled trickle, not unrestricted sensory load.
- Astrid writes remain gated by Minime health and rollback policy.

## Git Savepoint Guidance

This work should be preserved in multiple targeted commits, not staged all at once:

- Commit rescue operations scripts and profile/matrix tests together.
- Commit pinned rescue engine physiology changes in the rescue worktree separately.
- Commit Astrid bridge policy/re-entry changes separately from Minime.
- Keep older unrelated BTSP or experiment changes out of rescue commits unless they are required by the build.

Use targeted path staging. The current worktrees contain older dirty files that should not be swept into a rescue savepoint by accident.

## Next Health-First Steps

The next practical Minime step is not more emergency controller surgery. It is to preserve the working rescue lane, then gradually restore agency surfaces:

- Confirm whether old sidecar processes from `neural-triple-reservoir` are intentional.
- Keep watching fill, semantic energy, rollback state, and feeder reconnect counts.
- If the current posture keeps holding, restore a tiny Minime self-study/journaling lane before opening richer sensory or checkpoint lineage.
- Treat any return to sustained `>82%`, repeated rollback, or semantic energy persistence as a signal to pause re-entry rather than tune by feel.
