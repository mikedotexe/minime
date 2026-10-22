"""Explicit web failures must not become unrelated research or generated writing."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import autonomous_agent as aa
import pytest

from minime_autonomy import public_web as web


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
        assert (result.soft_failure_reason if result is not None else
                "No readable search result was delivered") in agent._current_action_outcome_summary
        assert agent._pending_search_topic is None


@pytest.mark.parametrize("code, metadata, expected", [
    ("search_challenge", {"http_status": 202},
     "Search provider returned a human-verification challenge: search_challenge (HTTP 202)"),
    ("http_status", {"http_status": 202}, "Public web request incomplete: http_status (HTTP 202)"),
    ("http_status", {}, "Public web request incomplete: http_status"),
    ("search_challenge", {"http_status": None},
     "Search provider returned a human-verification challenge: search_challenge"),
    ("search_challenge", {"http_status": "202"}, "Public web request incomplete: invalid_helper_response"),
])
def test_search_helper_failure_reaches_durable_action_outcome_without_payload_or_recovery_execution(
        code, metadata, expected, monkeypatch, caplog):
    # Run the real dispatcher, adapter failure decoder and continuity finalizer;
    # only helper transport/identity and unrelated runtime surfaces are stubbed.
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    agent.session_id = 1
    agent._hard_recovery_reset = False
    agent._pending_search_topic = "PRIVATE_QUERY_MARKER"
    agent._pending_next_action = None
    agent._last_read_path, agent._last_read_offset, agent._last_read_summary = "saved", 12, "kept"
    agent._last_research_anchor = "prior anchor"
    agent._action_continuity = aa.ActionContinuityStore(aa.WORKSPACE_DIR)
    store = agent._continuity_store()
    agent._low_fill_guard_status = Mock(return_value={"active": False})
    agent._stable_core_action_allowed = Mock(return_value=(True, "synthetic admission"))
    agent._write_action_manifest = Mock(return_value=None)
    agent._log_decision = Mock()
    for name in ("_query_llm_with_next", "_summarize_research_meaning", "_save_research",
                 "_fetch_url", "_record_stable_core_agent_success"):
        setattr(agent, name, Mock(side_effect=AssertionError("failure must not execute " + name)))

    context = {"helper": Path("/synthetic-helper-never-executed"),
               "config_path": Path("/synthetic-config-never-read"), "owner": {}}
    monkeypatch.setattr(web, "_context", lambda _: context)
    monkeypatch.setattr(web, "_unchanged", lambda *_: None)
    invoke = Mock(return_value=(1, json.dumps({
        "complete": False, "code": code, **metadata,
        "error": "PRIVATE_RAW_ERROR_MARKER", "body": "PRIVATE_BODY_MARKER",
    }).encode()))
    monkeypatch.setattr(web, "_invoke", invoke)
    monkeypatch.setattr(aa, "extract_duckduckgo_hits", Mock(side_effect=AssertionError("no HTML parsing")))
    original_glob = Path.glob

    def no_local_source(path, pattern, *args, **kwargs):
        assert not path.is_relative_to("/Users/v/other/autoresearch"), "no local source substitution"
        return original_glob(path, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", no_local_source)
    state = {"fill_ratio": .68, "eig1": 4.7}
    raw = "SEARCH " + agent._pending_search_topic
    with caplog.at_level("DEBUG"):
        agent._execute_action("research_exploration", state, _from_llm_job=True,
                              _precreated_continuity_context={"raw_next": raw, "canonical_action": raw,
                                                             "source": "next"})
    event = agent._last_action_continuity_event
    assert event["status"] == "failed"
    assert event["continuity_action_result_v1"] == {
        "status": "failed", "reason": "web_source_not_delivered",
        "source_delivered": False, "generation_requested": False,
    }
    summary = event["outcome_summary"]
    assert expected in summary
    assert "No local source was substituted" in summary and "no reflection was generated" in summary
    if code == "http_status":
        assert "challenge" not in summary
    assert "refin" not in summary.lower()
    persisted = [json.loads(line) for line in (store._thread_dir(event["thread_id"]) / "events.jsonl")
                 .read_text().splitlines()]
    assert persisted[-1]["outcome_summary"] == summary
    assert persisted[-1]["continuity_action_result_v1"] == event["continuity_action_result_v1"]
    assert "PRIVATE_" not in summary and "PRIVATE_" not in caplog.text
    assert "PRIVATE_BODY_MARKER" not in json.dumps(event)
    assert "PRIVATE_RAW_ERROR_MARKER" not in json.dumps(event)
    invoke.assert_called_once()
    assert json.loads(invoke.call_args.args[1])["target"] == "PRIVATE_QUERY_MARKER"
    assert agent._pending_search_topic is None and agent._pending_next_action is None
    assert (agent._last_read_path, agent._last_read_offset, agent._last_read_summary) == ("saved", 12, "kept")
    assert agent._last_research_anchor == "prior anchor"
    for name in ("_query_llm_with_next", "_summarize_research_meaning", "_save_research",
                 "_fetch_url", "_record_stable_core_agent_success"):
        getattr(agent, name).assert_not_called()


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
