"""Synthetic shared search envelopes; no providers, grants, or service actions."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import public_web as web
from . import test_public_web as adapter_tests


QUERY = '  "CONTROL Vec<T>"  \u03bb & q=other;\nexact  '
HIT = {"title": "PRIVATE_TITLE", "url": "https://example.org/synthetic",
       "snippet": "PRIVATE_SNIPPET"}


@pytest.fixture
def adapter():
    case = adapter_tests.PublicWebTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def envelope(query=QUERY, hits=None):
    return {"schema": "astrid.search.results.v1", "provider": "brave_web_v1", "query": query,
            "results": [HIT.copy()] if hits is None else hits}


def response(adapter, value=None, *, raw=None, query=QUERY):
    body = raw if raw is not None else adapter_tests.wire(envelope(query) if value is None else value)
    result = adapter.response("search", query, body)
    result["content_type"] = web.SEARCH_CONTENT_TYPE
    # Counts are raw provider bytes; the shared normalized JSON can be larger.
    result["receipt"]["decoded_bytes_observed"] = 23
    result["receipt"]["wire_bytes_observed"] = 21
    adapter.invoke.return_value = (0, adapter_tests.wire(result))
    return result


@pytest.mark.parametrize("schema", ["astrid.public_web.config.v2", "astrid.public_web.config.v3"])
def test_config_versions_keep_preview_and_exact_config_guard(adapter, schema):
    adapter.config["schema"] = schema
    adapter.save_config()
    response(adapter)
    web.fetch(adapter.agent, "search", QUERY)
    metadata = adapter.metadata()
    adapter.invoke.return_value = (0, adapter_tests.wire(metadata))
    assert web.preview(adapter.agent, "search") == metadata
    assert metadata["implementation_scope"] == "transport_foundation"

    result = response(adapter)
    def drift(*_):
        adapter.config_path.write_bytes(adapter_tests.wire(adapter.config) + b" ")
        return 0, adapter_tests.wire(result)
    adapter.invoke.side_effect = drift
    adapter.reject("config_changed", "search", QUERY)


@pytest.mark.parametrize("hits", [[], [HIT], [HIT] * 5])
def test_normalized_results_bind_exact_query_and_normalized_hash(adapter, hits):
    expected = response(adapter, envelope(hits=hits))
    actual = web.fetch(adapter.agent, "search", QUERY)
    assert actual == expected
    assert web.normalized_search_results(actual, QUERY) == hits
    assert actual["receipt"]["decoded_bytes_observed"] < len(actual["body"])
    assert actual["receipt"]["body_sha256"] == adapter_tests.digest(bytes(actual["body"]))
    argv, request = adapter.invoke.call_args.args
    assert QUERY not in argv and json.loads(request)["target"] == QUERY
    adapter.reject("invalid_helper_response", "search", QUERY.strip())


@pytest.mark.parametrize("field,value", [
    ("schema", "other"), ("provider", "other"), ("query", QUERY.strip()),
    ("results", None), ("results", {}), ("results", [HIT] * 6),
    ("results", [None]), ("results", [{"title": "x", "url": "https://example.org/"}]),
    ("results", [{**HIT, "url": 3}]), ("results", [{**HIT, "snippet": False}]),
    ("results", [{**HIT, "title": "\ud800"}]), ("results", [{**HIT, "extra": "PRIVATE"}]),
    ("extra", "PRIVATE"),
])
def test_invalid_envelope_is_rejected_even_with_matching_receipt(adapter, field, value):
    payload = envelope()
    payload[field] = value
    response(adapter, raw=json.dumps(payload).encode())
    adapter.reject("invalid_helper_response", "search", QUERY)


@pytest.mark.parametrize("raw", [b"PRIVATE_BODY", b"[]", b"\xff", b'{"web":{"results":[]}}',
                                 b'{"schema":"a","schema":"b"}',
                                 b'{"results":[NaN]}'])
def test_only_shared_utf8_json_is_accepted(adapter, raw):
    response(adapter, raw=raw)
    adapter.reject("invalid_helper_response", "search", QUERY)


@pytest.mark.parametrize("field,value", [
    ("decoded_bytes_observed", -1), ("decoded_bytes_observed", True),
    ("decoded_bytes_observed", web.MAX_BODY + 1),
    ("wire_bytes_observed", web.MAX_BODY + 1), ("body_sha256", "d" * 64),
])
def test_normalized_body_still_requires_bounded_counts_and_matching_hash(adapter, field, value):
    result = response(adapter)
    result["receipt"][field] = value
    adapter.invoke.return_value = (0, adapter_tests.wire(result))
    adapter.reject("invalid_helper_response", "search", QUERY)


def test_normalized_and_provider_bodies_have_independent_limits(adapter, monkeypatch):
    result = response(adapter)
    monkeypatch.setattr(web, "MAX_BODY", len(result["body"]) - 1)
    adapter.reject("invalid_helper_response", "search", QUERY)


def test_vendor_search_media_cannot_be_used_for_pages(adapter):
    result = response(adapter)
    request = {"schema": web.REQUEST_SCHEMA, "operation": "page", "target": QUERY}
    result["receipt"]["request_sha256"] = adapter_tests.digest(adapter_tests.wire(request))
    adapter.invoke.return_value = (0, adapter_tests.wire(result))
    adapter.reject("invalid_helper_response", "page", QUERY)


@pytest.mark.parametrize("code", ["credential_unavailable", "search_authentication",
    "search_rate_limited", "search_response_invalid", "search_spending_limit", "search_spending_state"])
def test_new_helper_codes_retain_only_safe_diagnostics(adapter, code):
    adapter.invoke.return_value = (1, adapter_tests.wire({
        "complete": False, "code": code, "http_status": 429,
        "error": "PRIVATE_CREDENTIAL", "body": "PRIVATE_BODY"}))
    with pytest.raises(web.PublicWebError) as caught:
        web.fetch(adapter.agent, "search", QUERY)
    assert caught.value.code == code
    assert "HTTP 429" in caught.value.delivery_message()
    assert "PRIVATE" not in caught.value.delivery_message()


def runtime_agent(adapter):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    agent._agent_inputs_at_start = adapter.agent._agent_inputs_at_start
    agent.session_id = 1
    agent._hard_recovery_reset = False
    agent._last_read_path, agent._last_read_offset, agent._last_read_summary = "saved", 12, "kept"
    agent._last_research_anchor = "prior anchor"
    agent._last_research_anchor_origin = {"source": "prior"}
    agent._pending_next_action = "WRITE CONTINUE"
    agent._current_action_continuity_context = {}
    agent._current_action_continuity_event = {}
    agent._summarize_research_meaning = Mock(side_effect=AssertionError("no summary"))
    agent._query_llm_with_next = Mock(side_effect=AssertionError("no reflection"))
    agent._save_research = Mock(side_effect=AssertionError("no research save"))
    agent._fetch_url = Mock(side_effect=AssertionError("no page navigation"))
    return agent


def test_runtime_nonempty_search_consumes_shared_hits_without_provider_or_html_parsing(adapter, monkeypatch, caplog):
    response(adapter)
    agent = runtime_agent(adapter)
    agent._summarize_research_meaning = Mock(return_value="Synthetic summary")
    agent._save_research = Mock()
    monkeypatch.setattr(aa, "extract_duckduckgo_hits", Mock(side_effect=AssertionError("no HTML")))
    with caplog.at_level("INFO"):
        result = agent._web_search(QUERY)
    assert result.succeeded() and len(result.hits) == 1
    assert result.hits[0] == aa.ResearchHit(**HIT)
    assert result.anchor == QUERY
    assert "navigation candidates" in result.prompt_body()
    assert "not verified page evidence" in result.prompt_body()
    assert agent._summarize_research_meaning.call_args.args[2] == QUERY
    assert "not verified page evidence" in agent._summarize_research_meaning.call_args.args[3]
    agent._save_research.assert_called_once_with(QUERY, result)
    agent._fetch_url.assert_not_called()
    agent._query_llm_with_next.assert_not_called()
    assert agent._pending_next_action == "WRITE CONTINUE"
    assert "PRIVATE" not in caplog.text and QUERY not in caplog.text


@pytest.mark.parametrize("empty", [True, False])
def test_empty_or_invalid_runtime_search_preserves_bookmarks_and_pending_choice(adapter, monkeypatch, caplog, empty):
    value = envelope(hits=[])
    if not empty:
        value["query"] = "PRIVATE_MISMATCH"
    response(adapter, value)
    agent = runtime_agent(adapter)
    agent._pending_search_topic = QUERY
    monkeypatch.setattr(aa, "extract_duckduckgo_hits", Mock(side_effect=AssertionError("no HTML")))
    original_glob = Path.glob
    def no_local_source(path, pattern, *args, **kwargs):
        assert not path.is_relative_to("/Users/v/other/autoresearch"), "no local source fallback"
        return original_glob(path, pattern, *args, **kwargs)
    monkeypatch.setattr(Path, "glob", no_local_source)
    with caplog.at_level("DEBUG"):
        agent._research_exploration({})
    receipt = agent._current_action_continuity_event["continuity_action_result_v1"]
    assert receipt == {"status": "handled" if empty else "failed",
        "reason": "web_search_zero_results" if empty else "web_source_not_delivered",
        "source_delivered": False, "generation_requested": False}
    assert ("zero results" if empty else "invalid_helper_response") in agent._current_action_outcome_summary
    assert "PRIVATE" not in caplog.text and QUERY not in caplog.text
    assert "PRIVATE" not in agent._current_action_outcome_summary
    assert agent._pending_search_topic is None
    assert agent._pending_next_action == "WRITE CONTINUE"
    assert (agent._last_read_path, agent._last_read_offset, agent._last_read_summary) == ("saved", 12, "kept")
    assert agent._last_research_anchor == "prior anchor"
    assert agent._last_research_anchor_origin == {"source": "prior"}
    for name in ("_summarize_research_meaning", "_query_llm_with_next", "_save_research", "_fetch_url"):
        getattr(agent, name).assert_not_called()


def test_empty_search_completion_survives_real_continuity_finalizer(adapter, monkeypatch):
    response(adapter, envelope(query="synthetic query", hits=[]), query="synthetic query")
    agent = runtime_agent(adapter)
    agent._pending_search_topic = "synthetic query"
    agent._action_continuity = aa.ActionContinuityStore(aa.WORKSPACE_DIR)
    agent._low_fill_guard_status = Mock(return_value={"active": False})
    agent._stable_core_action_allowed = Mock(return_value=(True, "synthetic admission"))
    agent._write_action_manifest = Mock(return_value=None)
    agent._log_decision = Mock()
    agent._record_stable_core_agent_success = Mock()
    agent._execute_action("research_exploration", {"fill_ratio": .68, "eig1": 4.7}, _from_llm_job=True,
        _precreated_continuity_context={"raw_next": "SEARCH synthetic query",
                                      "canonical_action": "SEARCH synthetic query", "source": "next"})
    event = agent._last_action_continuity_event
    assert event["status"] == "handled"
    assert event["continuity_action_result_v1"]["reason"] == "web_search_zero_results"
    assert event["continuity_action_result_v1"]["generation_requested"] is False
    persisted = [json.loads(line) for line in (agent._continuity_store()._thread_dir(event["thread_id"])
        / "events.jsonl").read_text().splitlines()]
    assert persisted[-1]["outcome_summary"] == event["outcome_summary"]
    assert persisted[-1]["continuity_action_result_v1"] == event["continuity_action_result_v1"]
    assert agent._pending_next_action == "WRITE CONTINUE"
    agent._query_llm_with_next.assert_not_called()


def test_legacy_html_search_is_retained(adapter):
    html = (b'<a class="result__a" href="https://example.org/">Synthetic title</a>'
            b'<span class="result__snippet">A sufficiently long synthetic snippet.</span>')
    adapter.invoke.return_value = (0, adapter_tests.wire(adapter.response("search", QUERY, html)))
    agent = runtime_agent(adapter)
    agent._summarize_research_meaning = Mock(return_value="summary")
    agent._save_research = Mock()
    result = agent._web_search(QUERY)
    assert result.succeeded() and len(result.hits) == 1
    assert result.hits[0].title == "Synthetic title"
    adapter.invoke.return_value = (0, adapter_tests.wire(adapter.response("search", QUERY, b"<html></html>")))
    assert agent._web_search(QUERY) is None
