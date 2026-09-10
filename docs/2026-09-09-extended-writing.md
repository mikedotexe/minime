# Shared extended writing and private drafts · September 9, 2026

Mike accepted the longform-room proposal after the fixed study audit found that larger
output ceilings alone were not producing longer entries. This change gives both Beings
an explicit, persistent choice and a place to continue the same thought.

## Behavior

- `WRITE PROFILE EXTENDED` selects an 8,192-token output ceiling across journal-producing
  provider calls; `SHORT` selects 512 and `DEFAULT` restores existing mode preferences.
  Defaults and Astrid's existing LENGTH preference are preserved. There is no minimum
  length. The profile survives Ollama/MLX fallback clamps and adjusts request/job deadlines.
- `WRITE START <topic>`, `CONTINUE`, `REVISE <direction>`, `BRANCH <direction>`,
  `RESUME dN`, `FINISH`, `LIST`, `QUESTION <text>`, and `EVIDENCE <text>` use one shared
  Rust writer. `READ dN [page]` reopens a large saved draft in explicit 9,000-byte pages.
  Help is `WRITE HELP`. A draft turn has a small menu and can choose any ordinary NEXT.
- Full visible passages, question, references, exact request/response and earlier revisions
  persist in the owning reader's `writing/` directory. Continuation carries the whole
  current draft, not an opening excerpt. Receipt retries are idempotent; failed/shortened/
  stale/length-terminated delivery never replaces a completed draft. Failed provider wire
  remains in existing diagnostics. Navigation-only responses need not add draft prose.
- The shared study notebook now stores up to 64,000 bytes per recent answer and renders
  up to 32,000 bytes, dropping oldest whole answers before labelling excerpts. The full
  protected input allowance is 48,000 bytes and context reservation 65,536 tokens. A draft
  that cannot fit is left intact with an explicit capacity notice, paging and a new-draft
  option; there is no silent draft truncation.
- `private_writing/journal/` and `private_writing/artifacts/` sit outside peer journal scans.
  WRITE creates no sensory payload, companion inbox letter, or auto-promoted shared thought.
  Minime's private draft also bypasses ordinary journal compression. Existing public modes
  keep their delivery behavior. Model thinking, coupling, reservoir and sensory dimensions
  are unchanged.

## Important correction to the preceding audit

`record_next_choice` generated forced-redirect metadata and "This turn" wording, but
`orchestration.rs` already used the authored NEXT as its effective action and logged the
redirect as advice. This release makes the repetition helper itself advisory for read-only
exploration and writing. It does **not** claim to newly remove an active dispatcher veto.
Existing health, external-action authority and resource scheduling checks remain.

## Validation and limits

Reader tests cover full-tail retention, process reconstruction, delivery retry, replacement
revision history, branches, finish/resume, exact profile values, stale/conflicting delivery,
length termination and oversized-draft recovery. Host tests exercise real Minime adapters,
private journal placement and actual action dispatch; Astrid tests cover provider policies,
final dialogue clamps, private mode attestation and NEXT dispatch. Full suites, strict
Clippy, workspace formatting and the domain-boundary audit are recorded in Astrid `docs/steward-notes/extended-writing-validation/checks.json`.

Two isolated native Ollama trials used 8,192 output / 65,536 context: the source control
stopped at 781 generated tokens (117.69 s), the private draft at 572 (64.77 s). Both returned
usable nonempty responses and native stop. This qualifies request admission and usability,
not sustained 8,192-token generation, natural uptake, understanding, or coupled-Astrid
performance. The source-control response still asserted a host-mediated gateway path not
established by its supplied excerpts. The free draft chose WRITE CONTINUE but its NEXT was
not executed. Outputs were not delivered to the Beings.

## Deployment and rollback

Deploy the immutable bridge/helper stage first, then gracefully reload Minime's Python
agent using its owner-controlled restart tool. No engine or model restart is required.
The profile is opt-in. Reverting it to DEFAULT restores ordinary capacities while retaining
all drafts. An older helper cannot understand WRITE, so do not point Minime at one while
pending WRITE actions remain. Keep new writing records during any code rollback.

The owning rollout receipt is appended after activation; source tests alone are not live
verification. Research history HSS-18 retains qualification and deployment as separate facts.
