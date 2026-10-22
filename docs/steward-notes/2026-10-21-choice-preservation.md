# Optional Steward Invitation Metadata

The supported commands are `STEWARD_INVITATION STATUS`,
`STEWARD_INVITATION DEFER`, and `STEWARD_INVITATION DECLINE`. STATUS retrieves the
latest retained subject/review-target metadata and disposition, not the letter
body. DEFER and DECLINE quiet that revision without deleting the retained source.
Neither schedules a revisit, generates prose, sends a reply, releases focus,
or manufactures a NEXT choice. Existing admission and health gates still apply.

An optional invitation is offered at most once per material revision when an
ordinary prompt is assembled. The durable receipt records assembly, not provider
delivery or acknowledgement. Restart or source rename does not rearm it. A
changed subject, review target, or supplied full-content hash is a new revision;
legacy slots without that hash can distinguish only their available metadata.
Expired invitations remain explicitly retrievable while their latest slot is
retained. This is a single-slot surface, not an archive browser. Receipt history
is bounded to 256 revision hashes; corrupt or full history suppresses ambient
offers instead of evicting history and repeating them.

Visual side-generation defers while an authored NEXT, accepted work, REST in the
current cycle, or protected attention is pending. A choice arriving during an
already accepted visual call wins the queue; the visual response can still be
retained without overwriting it. No live deployment or model trial is implied.
