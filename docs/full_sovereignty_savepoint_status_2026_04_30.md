# Full Sovereignty Savepoint Status

- Generated: `2026-05-01T07:41:12Z`
- Reason: `codex_pre_sensory_restart_check`
- Runtime profile: `stable_core_v1`
- Minime agency: `full_sovereignty`
- Fill: `68.05733489990234`
- Stage: `hold`
- Watchdog: `monitoring`
- Telemetry: `fresh`
- Semantic energy: `0.0`
- Bridge profile: `bridge_budgeted_sovereignty_v1`
- Astrid sends: `1`
- Sensory profile: `tiny_trickle_v1`
- Reservoir status: `ok`
- Lineage mode: `quarantined`
- Checkpoint lineage enabled: `False`
- Neural bundle enabled: `False`

## Rollback Commands

```bash
python3 /Users/v/other/minime/scripts/stable_core_ops.py bridge-write-set bridge_observe_only --reason full_sovereignty_rollback
python3 /Users/v/other/minime/scripts/stable_core_ops.py sensory-profile-set muted_v1 --reason full_sovereignty_rollback
python3 /Users/v/other/minime/scripts/stable_core_ops.py lineage-set quarantined --reason full_sovereignty_rollback
launchctl kickstart -k gui/$(id -u)/com.minime.engine-rescue
```

Scaffold/drain, stable-core watchdog monitoring, and rollback semantics remain the survival kernel.
