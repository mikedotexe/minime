# Engine Integration: Qualified, Not Activated

October 1, 2026. Codex integrated the reviewed engine repair as `c94db1b` and
reconciled current main in `c428fcaec55090a29b9c3f38c4219b093b1d9172`.
That main was pushed to origin, paired with Astrid `63d1f0628f`. Both canonical
trees were clean; all historical evidence and foreign worktrees remain intact.
The Python adapter source is unchanged from the previously live main.

Release-04 is built from clean `c428fca`, with 120 archived inputs matching the
prior qualified engine and canonical source. Manifest SHA-256:
`47396e48a469598480dce61ddfc12808682e698b75cbc5eccb845743f25dddbe`.
Engine SHA-256: `0610800dd57bf34287bb5e4f9869e777179f602bf5208a4d5524c95b93f235d8`.
The 833 selected Rust tests pass again; the raw transcript is
`2026-10-01-engine-integrated-tests.txt`. Selected strict all-features Clippy and
formatting pass. Astrid's 148 supporting tests include the actual staged restore
inspector; the canonical wrapper's read-only preflight passes without activation.

The old engine, gateway and supervisor remain running. No hold, signal, signed
handoff, installation, preference reset or engine activation occurred. Three
inert launch-wrapper additions were merged. Their current manifest references
were aligned separately, preserving archived historical bytes and the old engine
build provenance; mapped identities and protected services were verified unchanged.

The specific one-time legacy-transition approval remains pending because the
old processes do not acknowledge a complete input drain. The detailed limits,
exact receipt paths, release hashes, launcher alignment and next safe sequence
are in Astrid `docs/steward-notes/2026-10-01-engine-git-integration.md` and its
paired JSON receipt. Copied-input qualification is not stopped-state evidence or
full reservoir continuity. Paused automations remain paused at generation 485.
