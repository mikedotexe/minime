# Maintenance Durability Release

## Scope and Authority

Mike requested deployment and commits on 2026-10-05. This isolated release is
based on local main `1e53310d9d6f15264470300c51cf2d04a3744b31` and ports only
reviewed durability repairs from the larger writing-capacity candidate.

It does not enable 96,000-byte input or 16,384-token output, change providers,
alter research policy, restart the engine or claim subjective improvement.
The existing bridge/helper and model/visual/sensory processes remain protected.
Previously paused automations remain paused.

## Implemented Behavior

- Source status uses bounded, owned regular files, full writes, atomic replacement,
  file/directory sync and exact mandatory retries. Startup acknowledgement precedes
  scheduling. Drained acknowledgement follows joined workers and the NEXT seal.
  Failed mandatory publication is not reported as success; recovery stays blocked.
- NEXT sealing leaves logical record/byte capacity for one restoration receipt.
  This is not a reservation of disk space and makes no arbitrary ENOSPC guarantee.
- Exact job-outcome retry verifies retained result identity and re-syncs files and
  directory before acknowledgement. Torn or conflicting event history remains
  preserved and fails visibly rather than being skipped or rewritten.

No authored journal, private draft, queued choice or historical result is rewritten.
The runtime's existing large-file organization is retained for this narrow port;
the new cohesive publisher lives in its own module.

## Qualification

The first focused command named nonexistent `tests/test_llm_access.py` and ran no
tests. The actual outcome suites and full Python suite are being run against the
unchanged deployed reader, using synthetic data and no live generation.
Final results and activation receipt will be appended before close-out.

Paired operator record: Astrid
`docs/steward-notes/2026-10-05-maintenance-durability-release.md`.

## Qualification Completed

- Full current-main Minime suite: **1,907 passed, 1 skipped, 144 subtests**.
- Frozen-source focused durability/outcome suite: **142 passed**. The final run
  pre-imported the actual frozen runtime, status publisher, NEXT and job modules
  and asserted every module path before pytest; subprocess fixtures used
  byte-identical candidate sources.
- Astrid reconcile/paired-handoff/restart/NEXT/compatibility suite: **68 passed**.
- Controller, projector and Evidence Event Store suite: **64 passed**.
- Same-schema synthetic preservation qualifier: **40 checks passed** for both
  owners, unchanged schema 12 and unchanged helper selection.
- Both candidate diffs pass whitespace checks. No bridge Rust or engine source
  changed, so no Rust rebuild or engine test is represented as newly run.

Frozen reconciliation:
`/Users/v/other/worktrees/maintenance-durability-20261005/release-01/reconciliation.json`
SHA-256 `fffa8b0747aa8f8e4971f736da666e926b4e6e2e472ed973fe7d78c161f59f63`.

Preservation receipt:
`/Users/v/other/worktrees/maintenance-durability-20261005/qualification-02/qualification.json`
SHA-256 `7d420d091167ce16d4937ec5c7f25c2e47cce07a5bef731c81644a22b9fda0ad`.

Selected changed source SHA-256:

| Path in Minime | SHA-256 |
| --- | --- |
| `minime_autonomy/runtime.py` | `8ad590bd912818002731d4bff978fa21935622d35b6f14f62ca644b3f197241b` |
| `minime_autonomy/source_status.py` | `fb3d892b800e3b6d6d02c890d46351695e0b8d320d454eb36f0bc6e17f7f2e46` |
| `minime_autonomy/maintenance_next.py` | `5fe8ba8e800225a7b788c02e2db05c9addd99c093c8f68b39e2a1b4e430be405` |
| `minime_autonomy/llm_access.py` | `634f51276a2b17eba8f0526fde925c5312a1dd4e48cb187dff69b631dc466db0` |

Unsuccessful attempts retained: the first focused invocation named a nonexistent
test module and ran nothing; the pre-v5 geometry migrator correctly refused the
current schema-12 helper (qualification-01/failure.json); two frozen pytest
invocations could not find Homebrew site-packages with explicit PYTHONPATH.
Selecting the same-schema qualifier and the actual installed site-packages
resolved the harness errors. No live service was changed by those attempts.

Before activation: old agent 76377, all 92 inputs match; protected processes and
the selected bridge stage match prior deployment. Shared Ollama 9458 retains its
October 2 12:48:41 process start. Controller remains paused at generation 495,
with no lease; V2 indexed-tail verification passes and V1 sources remain immutable.
Remote main tips rechecked unchanged: Astrid `a66f7e190e0ecd3a0a4988abbcf6b0bf2cfb2a32`,
Minime `9072abff9ed839851709300b3c3eaae3afaf669e`. Both canonical trees are clean.

## Live Activation and Git Integration

The approved agent-only wrapper completed successfully at
`2026-10-05T22:07:41.356212+00:00`. It installed the exact reviewed overlay,
kept replacement admission held during the quiet interval, sent one SIGTERM to
agent **76377**, observed its exit, and verified replacement **1499** (process
start **2026-10-05 15:06:57 PDT**, runtime start **15:07:07**). No forced
termination, bootout, queue edit or historical-state restore was used.

- All **93** loaded source inputs equal the frozen release and canonical source.
  `reload_required=false`; normal idle/loop readiness passed.
- Session **5321** is preserved. The live stopped queue was **empty**. Its seal
  `2b5a32f6bda7c96da8b666205aaf33936891056ee8cc33e0b2d25c5572b8ccd1`
  links to restoration
  `b0e247893db44d71d7cc3c2409a35608ed9a3cb7ae8281cf0b8802e5b8673d61`.
  This proves exact empty-queue restoration, not execution or nonempty live
  recovery; synthetic cases cover nonempty recovery.
- No newly interrupted job was found. The wrapper saw no new job during its
  transition; a subsequent read-only check found one naturally admitted job.
  Admission is not a claim of completed generation or improved experience.
- All ten wrapper-protected process identities and starts are unchanged.
  Shared Ollama **9458** was checked separately and is unchanged.
- Bridge **4732**, coupled provider **3893**, and engine **35303** are unchanged.
  The selected bridge/helper stage remains
  `/Users/v/other/worktrees/writing-room-20261001/bridge-stage-03`.
- The owned agent launch hold was removed only by the verified wrapper.
  Controller generation **495** and previously paused automations remain paused.

Durable activation receipt:
`/Users/v/other/worktrees/maintenance-durability-20261005/release-01/activation.jsonl`,
SHA-256 `f1f72f66bcf662e4d4c545c00fa7acacdef46866f28cb0acf88a322bb215b6c5`.
Original source backups remain in `release-01/activation.source-before`;
they are not authority to overwrite newer authored state.

Read-only telemetry observations, with zero control messages sent:

| Window | Seconds | Samples | Fill range | Last fill | Max receive gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before restart, beginning 22:03:54.940426 UTC | 181.912 | 77 | 71.029365-73.041620% | 73.015654% | 2.414 s |
| After restart, beginning 22:07:39.928273 UTC | 47.079 | 20 | 71.020370-73.029640% | 73.017970% | 2.396 s |

Neither interval had a receive timeout. These bounded observations do not prove
controller settling, long-term stability or subjective effects.

### Committed Sources

Both source commits were tested in staged state and fast-forwarded to local main:

- Minime `ffa511dc094bd5d8c944cffd95a44e59570533bf`.
- Astrid `3fb01de169d57d5f6cb436c0541d280255cc7637`.

Minime exact committed paths:
`CHANGELOG.md`,
`docs/steward-notes/2026-10-05-maintenance-durability-release.md`,
`minime_autonomy/llm_access.py`,
`minime_autonomy/maintenance_next.py`,
`minime_autonomy/runtime.py`,
`minime_autonomy/source_status.py`,
`tests/test_maintenance_next_edges.py`,
`tests/test_maintenance_receipt_capacity.py`,
`tests/test_source_status.py`.

Astrid exact committed paths:
`CHANGELOG.md`,
`docs/steward-notes/2026-10-05-maintenance-durability-release.md`,
`docs/steward-notes/AI_BEINGS_FEEDBACK_TO_CHANGE_LEDGER.md`,
`scripts/reconcile_minime_launch.py`,
`scripts/test_paired_minime_handoff.py`,
`scripts/test_reconcile_minime_launch.py`.

The first Minime fast-forward refused the installed worktree files. No reset,
stash or discard followed. The coordinator staged only the four installed source
paths, proved the index byte-identical to the reviewed commit for those paths,
then completed the fast-forward. Both canonical trees and indexes were clean
after integration; older candidate worktrees were preserved. No remote push was
performed for this release.

### Remaining Capacity Work

The parallel provider-holder re-sync repair is offline in the original capacity
worktree, not in this deployment. Its 69-test holder suite and combined 156-test
holder/legacy/write-capacity suite pass, including nine pre-repair reproductions.
Coordinator reran the combined suite. See the candidate note
`/Users/v/.codex/worktrees/writing-capacity-next-budget/astrid/docs/steward-notes/2026-10-05-provider-holder-durability-repair.md`.

Full writing-capacity activation still requires bridge failed-drain continuation
retention, a finite qualified caller stop/restore transaction, isolated resource
qualification and the real-model four-cell measurements. Production provider
stopping remains disabled. The already approved maintenance window is retained;
no new approval request or relaxed resource limit is implied. The 96,000-byte
private input and 16,384-token expressive output promises are **not live**.
