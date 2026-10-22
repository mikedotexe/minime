"""Explicit web failures must not become unrelated research or generated writing."""
from unittest.mock import Mock, patch

import autonomous_agent as aa


def test_routine_next_diagnostics_withhold_web_targets_including_bound_requests():
    from minime_autonomy.writing import diagnostic_action
    for command in ("SEARCH confidential query", "browse https://user:secret@example.org/",
                    "EXPERIMENT_BIND e1 :: SEARCH private query", "EXAMINE https://user:secret@example.org/"):
        assert diagnostic_action(command) == "WEB [request arguments withheld]"
    assert diagnostic_action("REST") == "REST"
    assert diagnostic_action("WRITE START private") == "WRITE [private payload withheld]"


def test_requested_search_failure_preserves_choice_and_has_no_local_fallback():
    for result in (None, aa.ResearchOutcome(source_kind="search", raw_text="", anchor="fixture",
            meaning_summary="", soft_failure_reason="public_web_revoked")):
        agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
        agent._pending_search_topic = "CONTROL Vec<T> amplitude"
        agent._current_action_continuity_context = {}
        agent._current_action_continuity_event = {}
        agent._web_search = Mock(return_value=result)
        agent._query_llm_with_next = Mock(side_effect=AssertionError("no substitute generation"))
        with patch.object(aa.Path, "glob", side_effect=AssertionError("no local source fallback")):
            agent._research_exploration({})
        agent._query_llm_with_next.assert_not_called()
        assert agent._current_action_continuity_event["continuity_action_result_v1"]["status"] == "failed"
        assert "No local source was substituted" in agent._current_action_outcome_summary
        assert agent._pending_search_topic is None


def test_failed_browse_preserves_bookmark_and_has_no_prescribed_reflection(caplog):
    from minime_autonomy.public_web import target_fingerprint
    for result in (None, aa.ResearchOutcome(source_kind="page", raw_text="", anchor="fixture",
            meaning_summary="", soft_failure_reason="public_web_revoked")):
        agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
        agent._pending_browse_url = "https://user:secret@example.org/?q=sensitive"
        agent._last_research_anchor = "prior anchor"
        agent._last_read_path, agent._last_read_offset, agent._last_read_summary = "saved", 12, "kept"
        agent._current_action_continuity_event = {}
        agent._fetch_url = Mock(return_value=result)
        agent._query_llm_with_next = Mock(side_effect=AssertionError("no failure generation"))
        with patch.object(aa, "latest_journal_file_recall", return_value=None), caplog.at_level("INFO"):
            agent._browse_url({})
        agent._query_llm_with_next.assert_not_called()
        assert (agent._last_read_path, agent._last_read_offset, agent._last_read_summary) == ("saved", 12, "kept")
        assert agent._last_research_anchor == "prior anchor"
        assert agent._current_action_continuity_event["continuity_action_result_v1"]["source_delivered"] is False
        assert "secret" not in caplog.text and "sensitive" not in caplog.text
        assert target_fingerprint("https://user:secret@example.org/?q=sensitive") in caplog.text
