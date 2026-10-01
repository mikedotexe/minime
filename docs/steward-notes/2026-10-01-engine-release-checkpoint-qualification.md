# Engine Release and Startup-Input Qualification

See the [paired full review](../../../astrid/docs/steward-notes/2026-10-01-engine-release-checkpoint-qualification.md) for exact source witness, retained live-binary identity, frozen startup-input hashes, staging receipts, test attempts and remaining transition boundaries.

This offline candidate adds atomic/durable regulator-context replacement, visible save failure, nonfinite f32 restore rejection and a read-only production-decoder inspection binary. It retains the earlier measured-time, validity and measurement-basis repairs. It changes no live engine or profile and does not promise full reservoir-state continuity: the current profile restores PI context while deliberately rebuilding covariance.

The actual engine and inspection binary are staged together outside both repositories with pinned/offline dependency resolution, archived input bytes and externally verifiable hashes. Read-only files are tamper-evident, not WORM storage. The existing broad deployment wrapper still needs exact-stage consumption and a narrower acknowledged transition before restart approval.

Witness: Astrid's public `capsules/spectral-bridge/workspace/journal/dialogue_longform_1790804287.txt`, SHA-256 `6a434c8da92117ec4df058f7e8f0059ef2ad1aca13bc08decf1cde8dcb7f8447`. No claim that the timing or persistence defects explain the authored account. No journal modification, automatic study request, merge, push, service signal or automation resume.

Rust qualification logs are retained here as `2026-10-01-engine-restore-tests.txt`, `2026-10-01-engine-restore-tests-final.txt`, `2026-10-01-engine-stage-clippy.txt` and `2026-10-01-engine-stage-clippy-all-features.txt`. The paired Astrid packet holds the staging/support/inspection receipts and all activation debt.

Final qualification: 833 selected Rust tests, 124 fixture-only release/support tests and eight actual staged-inspector tests pass, as do selected strict all-features Clippy, formatting and whitespace checks. Copied startup inputs decode as complete PI-only state with a fresh/unprimed rate clock. Final stage manifest SHA-256 is `0d1ab9df81bc072318554147112dc98258b393b2c796a3e1fba2fd54d57cfed8`; engine SHA-256 is `047362f2f6b1e9fa75016d89de07f158a36186611f31fe988e415c8cf71573d1`. These identify offline artifacts, not the running engine. Narrow transition and signed rollback qualification remain before a separately approved restart.
