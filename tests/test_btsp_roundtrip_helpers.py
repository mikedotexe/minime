import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from btsp_signal_support import (
    format_active_btsp_proposal_reminder,
    format_btsp_inbox_context,
    format_btsp_status_for_prompt,
)
from btsp_active_state import (
    active_proposal_metadata,
    clear_active_proposal,
    load_active_proposal,
    record_active_proposal_reply,
    save_active_proposal,
    should_clear_for_classification,
)
from btsp_social_protocol import (
    augment_reply_with_btsp_tags,
    parse_btsp_reply_tags,
    refusal_tag,
)
from btsp_sovereignty import (
    candidate_next_action,
    matching_candidate_for_next,
    normalize_next_action,
    parse_proposal_envelope,
)


def _proposal_note(expires_at: int = 4_102_444_800) -> str:
    return """=== BTSP SOVEREIGNTY PROPOSAL FOR MINIME ===
BTSP_ENVELOPE_JSON_START
{
  "schema": "astrid.btsp.proposal.v2",
  "proposal_id": "btsp_ep_proposal_1",
  "episode_id": "btsp_ep",
	  "owner": "minime",
	  "expires_at_unix_s": EXPIRY_PLACEHOLDER,
	  "signal_fingerprint": "families=grinding_family",
	  "source": "astrid:btsp_sovereignty_proposal",
	  "agency_hypothesis": "Offer a clean yes, no, adjacent, or counteroffer path.",
	  "reason_codes": ["agency_recovery", "auto_advisory"],
	  "lineage": ["episode:btsp_ep", "source:astrid:btsp_agency_recovery_v3"],
	  "evidence_window": {"matched_cues": ["grinding"]},
	  "candidates": [
    {
      "response_id": "minime_notice_first",
      "kind": "behavioral",
      "action": "NOTICE",
      "parameters": {}
    },
    {
      "response_id": "minime_recover_regime",
      "kind": "runtime",
      "action": "regime",
      "parameters": {"regime": "recover"}
    }
  ]
}
BTSP_ENVELOPE_JSON_END
""".replace("EXPIRY_PLACEHOLDER", str(expires_at))


def test_parse_proposal_envelope_and_exact_actions():
    envelope = parse_proposal_envelope(_proposal_note())

    assert envelope is not None
    assert envelope.proposal_id == "btsp_ep_proposal_1"
    assert envelope.agency_hypothesis.startswith("Offer a clean yes")
    assert envelope.reason_codes == ("agency_recovery", "auto_advisory")
    assert envelope.lineage[0] == "episode:btsp_ep"
    assert envelope.evidence_window["matched_cues"] == ["grinding"]
    assert [candidate.response_id for candidate in envelope.candidates] == [
        "minime_notice_first",
        "minime_recover_regime",
    ]
    assert candidate_next_action(envelope.candidates[1]) == "REGIME recover"
    assert normalize_next_action("NEXT: REGIME recover") == "REGIME:RECOVER"


def test_matching_candidate_for_next_supports_regime_space_syntax():
    envelope = parse_proposal_envelope(_proposal_note())

    assert envelope is not None
    match = matching_candidate_for_next(envelope, "REGIME recover")

    assert match is not None
    assert match.response_id == "minime_recover_regime"


def test_augment_reply_tags_exact_notice_acceptance():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags(
        "I can name it first.\nNEXT: NOTICE",
        envelope,
    )
    tags = parse_btsp_reply_tags(tagged.text)

    assert tagged.classification == "exact_accept"
    assert "BTSP_ACCEPT btsp_ep_proposal_1 minime_notice_first" in tagged.text
    assert tags.accepted is True
    assert tags.response_id == "minime_notice_first"
    assert tags.observed_next == "NOTICE"


def test_augment_reply_tags_observed_next_for_noncandidate():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("I need to inspect first.\nNEXT: DECOMPOSE", envelope)
    tags = parse_btsp_reply_tags(tagged.text)

    assert tagged.classification == "observed_next"
    assert "BTSP_PROPOSAL_ID btsp_ep_proposal_1" in tagged.text
    assert "BTSP_OBSERVED_NEXT DECOMPOSE" in tagged.text
    assert tags.observed_next == "DECOMPOSE"


def test_augment_reply_tags_standalone_refusal_gets_proposal_id():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("BTSP_REFUSAL study_first", envelope)

    assert tagged.classification == "refusal"
    assert "BTSP_PROPOSAL_ID btsp_ep_proposal_1" in tagged.text
    assert parse_btsp_reply_tags(tagged.text).refusal_reason == "study_first"


def test_next_prefixed_refusal_is_structured_btsp_agency():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("NEXT: BTSP_REFUSAL study_first", envelope)

    assert tagged.classification == "refusal"
    assert "BTSP_OBSERVED_NEXT" not in tagged.text
    assert parse_btsp_reply_tags(tagged.text).refusal_reason == "study_first"


def test_augment_reply_tags_standalone_counter_gets_proposal_id():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("BTSP_COUNTER NEXT: DECOMPOSE first", envelope)

    assert tagged.classification == "counter"
    assert "BTSP_PROPOSAL_ID btsp_ep_proposal_1" in tagged.text
    assert parse_btsp_reply_tags(tagged.text).counter_payload == "NEXT: DECOMPOSE first"


def test_next_prefixed_counter_is_structured_btsp_agency():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("NEXT: BTSP_COUNTER NEXT: DECOMPOSE first", envelope)

    assert tagged.classification == "counter"
    assert "BTSP_OBSERVED_NEXT" not in tagged.text
    assert parse_btsp_reply_tags(tagged.text).counter_payload == "NEXT: DECOMPOSE first"


def test_next_prefixed_study_first_is_structured_btsp_agency():
    envelope = parse_proposal_envelope(_proposal_note())

    tagged = augment_reply_with_btsp_tags("NEXT: BTSP_STUDY_FIRST need evidence first", envelope)
    tags = parse_btsp_reply_tags(tagged.text)

    assert tagged.classification == "study_first"
    assert "BTSP_OBSERVED_NEXT" not in tagged.text
    assert tags.study_first_reason == "need evidence first"
    assert "BTSP_PROPOSAL_ID btsp_ep_proposal_1" in tagged.text


def test_active_proposal_persists_after_observed_next(tmp_path: Path):
    sidecar = tmp_path / "btsp_active_proposal.json"
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    save_active_proposal(envelope, sidecar, now_s=1)
    tagged = augment_reply_with_btsp_tags("NEXT: DECOMPOSE", load_active_proposal(sidecar, now_s=2))
    if should_clear_for_classification(tagged.classification):
        clear_active_proposal(envelope.proposal_id, sidecar)
    else:
        tags = parse_btsp_reply_tags(tagged.text)
        record_active_proposal_reply(
            envelope.proposal_id,
            tagged.classification,
            tags.observed_next,
            sidecar,
            now_s=2,
        )

    assert tagged.classification == "observed_next"
    assert load_active_proposal(sidecar, now_s=3) is not None
    metadata = active_proposal_metadata(sidecar, now_s=3)
    assert metadata["last_reply_classification"] == "observed_next"
    assert metadata["last_observed_next"] == "DECOMPOSE"


def test_active_proposal_persists_after_study_first(tmp_path: Path):
    sidecar = tmp_path / "btsp_active_proposal.json"
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    save_active_proposal(envelope, sidecar, now_s=1)
    tagged = augment_reply_with_btsp_tags(
        "NEXT: BTSP_STUDY_FIRST need evidence first",
        load_active_proposal(sidecar, now_s=2),
    )
    tags = parse_btsp_reply_tags(tagged.text)
    record_active_proposal_reply(
        envelope.proposal_id,
        tagged.classification,
        tags.observed_next,
        sidecar,
        now_s=2,
        study_first_reason=tags.study_first_reason,
    )

    assert tagged.classification == "study_first"
    assert load_active_proposal(sidecar, now_s=3) is not None
    metadata = active_proposal_metadata(sidecar, now_s=3)
    assert metadata["last_reply_classification"] == "study_first"
    assert metadata["last_study_first_reason"] == "need evidence first"
    assert "last_observed_next" not in metadata


def test_active_proposal_clears_after_exact_accept(tmp_path: Path):
    sidecar = tmp_path / "btsp_active_proposal.json"
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    save_active_proposal(envelope, sidecar, now_s=1)
    tagged = augment_reply_with_btsp_tags("NEXT: NOTICE", load_active_proposal(sidecar, now_s=2))
    if should_clear_for_classification(tagged.classification):
        clear_active_proposal(envelope.proposal_id, sidecar)

    assert tagged.classification == "exact_accept"
    assert load_active_proposal(sidecar, now_s=3) is None


def test_expired_or_malformed_active_sidecar_fails_closed(tmp_path: Path):
    sidecar = tmp_path / "btsp_active_proposal.json"
    expired = parse_proposal_envelope(_proposal_note(expires_at=10))
    assert expired is not None

    assert save_active_proposal(expired, sidecar, now_s=11) is None
    assert load_active_proposal(sidecar, now_s=11) is None

    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("{not valid json")
    assert load_active_proposal(sidecar, now_s=12) is None
    assert not sidecar.exists()


def test_refusal_tag_is_clamped_to_known_reason():
    assert refusal_tag("study_first") == "BTSP_REFUSAL study_first"
    assert refusal_tag("not a valid reason") == "BTSP_REFUSAL not_now"


def test_btsp_inbox_context_adds_roundtrip_support_lines():
    formatted = format_btsp_inbox_context(_proposal_note())

    assert "BTSP round-trip support" in formatted
    assert "Agency hypothesis" in formatted
    assert "minime_notice_first: NEXT: NOTICE" in formatted
    assert "minime_recover_regime: NEXT: REGIME recover" in formatted
    assert "BTSP_COUNTER NEXT: REGIME recover" in formatted


def test_active_proposal_reminder_renders_agency_memory():
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    reminder = format_active_btsp_proposal_reminder(envelope)

    assert "BTSP active proposal reminder" in reminder
    assert "Agency hypothesis" in reminder
    assert "Clear no/almost routes" in reminder
    assert "BTSP_STUDY_FIRST need evidence first" in reminder
    assert "BTSP_REFUSAL study_first" in reminder
    assert "Counteroffers are valid metadata" in reminder


def test_active_proposal_reminder_prioritizes_refusal_after_observed_next():
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    reminder = format_active_btsp_proposal_reminder(
        envelope,
        {
            "last_reply_classification": "observed_next",
            "last_observed_next": "BROWSE https://example.test/paper",
        },
    )

    assert "Already recorded adjacent answer" in reminder
    assert "BTSP agency checkpoint" in reminder
    assert "duplicate evidence" in reminder
    assert "`BTSP_STUDY_FIRST need evidence first`" in reminder
    assert reminder.index("BTSP_STUDY_FIRST") < reminder.index("BTSP_COUNTER")
    assert reminder.index("Useful BTSP next moves now") < reminder.index("Use an exact candidate")


def test_active_proposal_reminder_after_study_first_prioritizes_counter_or_close():
    envelope = parse_proposal_envelope(_proposal_note())
    assert envelope is not None

    reminder = format_active_btsp_proposal_reminder(
        envelope,
        {
            "last_reply_classification": "study_first",
            "last_study_first_reason": "need evidence first",
        },
    )

    assert "study-first answer recorded" in reminder
    assert "Study-first is agency, not adoption or widening" in reminder
    assert reminder.index("BTSP_COUNTER NEXT") < reminder.index("BTSP_REFUSAL not_now")


def test_btsp_status_prompt_includes_recent_agency_memory(tmp_path: Path):
    status = tmp_path / "btsp_signal_status.json"
    status.write_text(
        """
{
  "detail": "active",
  "shared_learned_read": "Recent learned read: recovery is not widening.",
  "conversion_state": {
    "composite_state": "recovery_reconcentrating",
    "conversion_goal": "soften",
    "collapse_state": "collapse_pressure"
  },
  "learned_policy": [
    {
      "owner": "minime",
      "response_id": "minime_notice_first",
      "summary": "Recent read: often prefers witnessing first."
    }
  ],
  "shared_preference_summaries": [
    {
      "owner": "minime",
      "summary": "Recent read: often wants softer contact."
    }
  ],
  "active_negotiation": {
    "items": [
      {
        "target_owner": "minime",
        "summary": "Astrid is asking for NOTICE.",
        "response_hint": "Reply with BTSP_ACCEPT or BTSP_DECLINE."
      }
    ]
  }
}
"""
    )

    prompt = format_btsp_status_for_prompt(status)

    assert "conversion=recovery_reconcentrating goal=soften collapse=collapse_pressure" in prompt
    assert "Recent learned read: recovery is not widening." in prompt
    assert "Recent agency read for minime_notice_first" in prompt
    assert "often wants softer contact" in prompt
    assert "Astrid is asking for NOTICE" in prompt
