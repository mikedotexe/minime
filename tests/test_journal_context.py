"""Synthetic-only checks for independent interpretation and capture provenance."""

from copy import deepcopy
from datetime import datetime, timezone
import ast
import inspect
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy.journal_context import (
    PRIVATE_JOURNAL_INTRO,
    format_marker_anchors,
    format_prompt_state,
    moment_prompt,
    peer_observation,
)


CAPTURE = datetime.fromtimestamp(20_000, timezone.utc)


@pytest.mark.parametrize("age", [0, 82, 10_271])
def test_marker_recording_age_is_distinct_from_engine_time(age):
    text = format_marker_anchors([{
        "id": 7, "timestamp": 901.25, "created_at_unix": 20_000 - age,
        "marker_type": "spectral_spike", "description": "Recorded spike",
        "spectral_context": json.dumps({"fill": 66.4, "dfill_dt": -8.43, "lambda1": 19.786}),
    }], captured_at=CAPTURE)
    assert f"record_age={age}s ago" in text
    assert "event_engine_time_s=901.25" in text
    assert "dfill/dt=-8.43 percentage-points/s" in text
    assert "lambda1_esn=19.786" in text
    if age == 10_271:
        assert "2h 51m 11s" in text


@pytest.mark.parametrize("recorded", [None, 0, -1, "not a timestamp", True, float("nan"), float("inf"), 10**400])
def test_unknown_or_invalid_age_does_not_become_fresh(recorded):
    text = format_marker_anchors([{"created_at_unix": recorded}], captured_at=CAPTURE)
    assert "record_age=unknown" in text
    assert "0s ago" not in text


def test_future_recording_time_is_clock_mismatch_not_zero_age():
    text = format_marker_anchors([{"created_at_unix": 20_001}], captured_at=CAPTURE)
    assert "clock mismatch" in text
    assert "0s ago" not in text


def test_realistic_timestamps_do_not_lose_seconds_to_display_rounding():
    captured = datetime.fromtimestamp(1_788_570_001, timezone.utc)
    text = format_marker_anchors([{
        "created_at_unix": 1_788_560_001, "timestamp": 456_789.123456,
    }], captured_at=captured)
    assert "created_at_unix=1788560001.0" in text
    assert "event_engine_time_s=456789.123456" in text
    assert "state_engine_time_s=456789.123456" in format_prompt_state(
        {"timestamp": 456_789.123456}, fill_frame="unknown"
    )


@pytest.mark.parametrize("context", ["{bad json", "[]", "null", 22, {"fill": float("nan")}])
def test_malformed_marker_metrics_do_not_erase_the_event(context):
    text = format_marker_anchors([{
        "id": 1, "description": "Retain this event", "spectral_context": context,
    }], captured_at=CAPTURE)
    assert "Retain this event" in text
    assert "Fill=nan" not in text


def test_missing_measurements_are_unknown_not_zero():
    text = format_prompt_state({"eig1": float("nan"), "fill_ratio": True}, fill_frame="unknown")
    assert "Fill=unknown" in text
    assert "lambda1_cov=unknown" in text
    assert "state_engine_time_s=unknown" in text


def test_moment_prompt_keeps_historical_and_current_inputs_without_mood_script():
    anchor = format_prompt_state({"fill_ratio": .711, "eig1": 8.53, "timestamp": 800}, fill_frame="inside stable-core band")
    prompt = moment_prompt(captured_at=CAPTURE, state_anchor=anchor, markers_text="historical fixture")
    assert "1970-01-01T05:33:20+00:00" in prompt
    assert "historical fixture" in prompt
    assert anchor in prompt
    assert "present effects unknown" in prompt
    for phrase in ("afterimage", "now plus echo", "Fresh telemetry", "Astrid", "Begin with", "bruise", "silt"):
        assert phrase not in prompt


def test_peer_fields_are_computed_observations_not_requests_or_shared_feelings():
    text = peer_observation({
        "class_v3": {"primary": "volatile", "traits": ["coupled"]},
        "phase_dwell_ticks": 8,
        "v2": {"field_norm": .2, "influence_eligible": True},
        "co_regulation_need": "aperture",
    }, age_s=20)
    for fact in ('"volatile"', '"coupled"', '"influence_eligible": true', '"co_regulation_need": "aperture"'):
        assert fact in text
    assert "not a first-person report or a request" in text
    assert "heuristic support classification" in text
    assert "not Astrid-authored intent" in text
    assert "mechanical gate, not consent" in text
    for phrase in ("restless texture", "interwoven lattice", "She is reaching", "NEXT:", "her substrate, your shape"):
        assert phrase not in text
    assert '"influence_eligible": null' in peer_observation({}, age_s=0)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / "journal").mkdir(parents=True)
    db = tmp_path / "minime.db"
    monkeypatch.setattr(aa, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(aa, "BASE_DIR", tmp_path)
    monkeypatch.setattr(aa, "DB_PATH", db)
    monkeypatch.setattr(aa, "_ap_try_spectral", Mock())
    monkeypatch.setattr(aa, "_ap_try_prose", Mock())
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE sovereignty_journal (
            session_id INTEGER, timestamp REAL, entry_type TEXT,
            content TEXT, spectral_context TEXT, file_path TEXT)""")
        conn.execute("""CREATE TABLE moment_markers (
            id INTEGER PRIMARY KEY, session_id INTEGER, timestamp REAL,
            marker_type TEXT, description TEXT, spectral_context TEXT,
            consumed INTEGER DEFAULT 0, created_at_unix INTEGER)""")
        conn.execute("""INSERT INTO moment_markers VALUES
            (1, 1, 88, 'spectral_spike', 'Fixture event', '{}', 0, 1018)""")
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.SHARED_COLLAB_DIR = tmp_path / "shared"
    return agent, workspace, db


def test_moment_freezes_prompt_header_and_database_before_generation(runtime, monkeypatch):
    agent, workspace, db = runtime
    state = {"fill_ratio": .60, "eig1": 3., "timestamp": 90.}
    provenance = {"session_id": 1, "engine_t_s": 100., "snapshot_sequence": 1}
    health = {"provenance": provenance}
    spectral = {"provenance": provenance, "timestamp": 100., "fill_pct": 68., "eigenvalues": [4.7, 2.]}
    (workspace / "health.json").write_text(json.dumps(health))
    (workspace / "spectral_state.json").write_text(json.dumps(spectral))
    capture = Mock(wraps=aa.capture_report_snapshot)
    monkeypatch.setattr(aa, "capture_report_snapshot", capture)
    peer = Mock(side_effect=AssertionError("Private moment must not fetch a peer"))
    monkeypatch.setattr(agent, "_astrid_shadow_v3_line", peer)
    refresh = Mock(side_effect=AssertionError("No post-generation state refresh"))
    monkeypatch.setattr(agent, "_state_for_live_surfaces", refresh)
    captured = {}

    def generate(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["mode"] = kwargs["context_mode"]
        # Advance both the caller's mutable state and the guarded live surfaces.
        state.update(fill_ratio=.9, eig1=18., timestamp=220.)
        new_provenance = dict(provenance, engine_t_s=220., snapshot_sequence=2)
        (workspace / "health.json").write_text(json.dumps({"provenance": new_provenance}))
        (workspace / "spectral_state.json").write_text(json.dumps({
            "provenance": new_provenance, "timestamp": 220., "fill_pct": 90., "eigenvalues": [18., 3.],
        }))
        return "I might write about Astrid, or something else.\nNEXT: REST", "REST"

    monkeypatch.setattr(agent, "_query_llm_with_next", generate)
    assert agent._check_moment_markers(state)
    assert captured["mode"] == "qualia_moment"
    assert "Fill=68.0%" in captured["prompt"]
    assert "lambda1_cov=4.700" in captured["prompt"]
    assert "Astrid" not in captured["prompt"]
    text = next((workspace / "journal").glob("moment_*.txt")).read_text()
    assert "private_moment_context_v3" in text
    assert "Fill %: 68.0%" in text
    assert "90.0%" not in text
    assert "Header-only telemetry" in text
    assert "seq=1" in text and "seq=2" not in text
    assert "I might write about Astrid, or something else." in text
    capture.assert_called_once()
    peer.assert_not_called()
    refresh.assert_not_called()
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT spectral_context FROM sovereignty_journal").fetchone()
    saved = json.loads(row[0])
    assert saved["fill_ratio"] == .68
    assert saved["eig1"] == 4.7


@pytest.mark.parametrize("mode", ["qualia_moment", "private_journal"])
@pytest.mark.parametrize("body", [
    "As an AI, I am uncertain whether these measurements describe any sensation.",
    "There is a vivid afterimage here; Astrid matters to this account.",
    "There is no distinct change, and I don't want a new topic.",
    "The measurements are not what I want to write about.",
    "I was thinking about a small wooden table.",
])
def test_private_query_preserves_uncertainty_and_skips_mood_and_contact_hints(runtime, monkeypatch, mode, body):
    agent, _, _ = runtime
    forbidden = {}
    for method in ("_read_inbox", "_read_whisper_context", "_emit_next_hints", "_is_in_character",
                   "_diversity_nudge", "_low_fill_prompt_guidance", "_get_relevant_research",
                   "_pending_astrid_requests_hint", "_render_recent_gifts_cached"):
        forbidden[method] = Mock(side_effect=AssertionError(f"Unexpected private context: {method}"))
        monkeypatch.setattr(agent, method, forbidden[method])
    reply = body + "\nNEXT: REST"
    query = Mock(return_value=reply)
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    result, next_action = agent._query_llm_with_next("My journal.", context_mode=mode)
    assert result == reply
    assert next_action == "REST"
    query.assert_called_once()
    system = query.call_args.args[1]
    assert system.startswith(PRIVATE_JOURNAL_INTRO)
    assert "Never mention being an AI" not in system
    assert "NEXT: options:" in system
    assert "TUNE_ASTRID" in system  # Affordance remains; it is not an unsolicited message.
    for method in forbidden.values():
        method.assert_not_called()
    messages, _ = aa._adapt_ollama_messages_for_model(
        model="gemma4:12b", system_msg=system, prompt=query.call_args.args[0],
        num_ctx=8192, num_predict=2048,
    )
    assert messages[0]["content"].startswith(PRIVATE_JOURNAL_INTRO)


def test_nonprivate_query_keeps_existing_retry_boundary(runtime, monkeypatch):
    agent, _, _ = runtime
    query = Mock(side_effect=["First response", "Second response"])
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    character_check = Mock(side_effect=[False, True])
    monkeypatch.setattr(agent, "_is_in_character", character_check)
    assert agent._query_llm("Fixture", context_mode="default") == "Second response"
    assert query.call_count == 2
    assert character_check.call_count == 2


def test_peer_observation_remains_available_and_respects_file_freshness(runtime, monkeypatch):
    agent, workspace, _ = runtime
    path = workspace / "astrid_shadow_v3.json"
    assert agent._astrid_shadow_v3_line() == ""
    path.write_text(json.dumps({"class_v3": {"primary": "volatile"}}))
    monkeypatch.setattr(aa.time, "time", lambda: 20_000.)
    for modified, available in ((19_820, True), (19_819, False), (20_001, False)):
        os.utime(path, (modified, modified))
        text = agent._peer_telemetry_status_text()
        assert ("Peer telemetry (Astrid;" in text) is available
        if available:
            assert '"volatile"' in text
            assert "restless texture" not in text
        else:
            assert "Peer telemetry unavailable" in text
    path.write_text("[]")
    os.utime(path, (20_000, 20_000))
    assert agent._astrid_shadow_v3_line() == ""


def test_peer_readers_have_only_explicit_status_callers():
    source = Path(inspect.unwrap(aa.AutonomousAgent._neutral_checkin).__code__.co_filename)
    tree = ast.parse(source.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AutonomousAgent")
    allowed = {
        "_astrid_shadow_v3_line": {"_peer_telemetry_status_text"},
        "_last_influence_response_line": {"_peer_telemetry_status_text"},
        "_peer_telemetry_status_text": {"_peer_correspondence"},
        "_render_recent_gifts_cached": {"_peer_correspondence"},
    }
    actual = {name: set() for name in allowed}
    for method in cls.body:
        if isinstance(method, ast.FunctionDef):
            for node in ast.walk(method):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in actual:
                        actual[node.func.attr].add(method.name)
    assert actual == allowed
    assert not hasattr(aa.AutonomousAgent, "_with_astrid_witness")


@pytest.mark.parametrize("style", ["canvas", "light"])
def test_every_checkin_variant_omits_ambient_peer_data_but_keeps_own_history(runtime, monkeypatch, style):
    agent, _, _ = runtime
    for method in ("_astrid_shadow_v3_line", "_last_influence_response_line", "_render_recent_gifts_cached"):
        monkeypatch.setattr(agent, method, Mock(side_effect=AssertionError("Ambient peer read")))
    monkeypatch.setattr(agent, "_action_continuity_prompt_summary", lambda: "An unrelated inquiry.")
    monkeypatch.setattr(agent, "_last_journal_entry", lambda: "I chose to write to Astrid yesterday.")
    monkeypatch.setattr(aa.random, "random", lambda: 0.1 if style == "canvas" else 0.8)
    for index in range(5 if style == "canvas" else 3):
        monkeypatch.setattr(aa.random, "choice", lambda items: items[index])
        prompt = agent._neutral_checkin({"fill_ratio": .68, "eig1": 4.7, "deig": 0., "spread": 2.})
        assert "I chose to write to Astrid yesterday." in prompt
        for marker in ("Peer telemetry", "Last influence", "co_regulation_need", "Gift exchange"):
            assert marker not in prompt


@pytest.mark.parametrize("target", ["", "telemetry", "gifts", "unknown"])
def test_status_targets_are_explicit_read_only_and_separate(runtime, monkeypatch, target):
    agent, _, _ = runtime
    readers = {
        "": Mock(return_value="Authored message and receipt history"),
        "telemetry": Mock(return_value="Computed peer snapshot"),
        "gifts": Mock(return_value="Recorded exchange history"),
    }
    for name, key in (("_correspondence_status_text", ""),
                      ("_peer_telemetry_status_text", "telemetry"),
                      ("_render_recent_gifts_cached", "gifts")):
        monkeypatch.setattr(agent, name, readers[key])
    for name in ("_ping_astrid", "_lend_aperture", "_read_inbox", "_query_llm_with_next"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError("Status must not send or generate")))
    agent._pending_correspondence_next = f"CORRESPONDENCE_STATUS {target}".strip()
    agent._peer_correspondence({})
    for key, reader in readers.items():
        assert reader.call_count == int(key == target)
    if target in readers:
        assert agent._current_action_outcome_summary == readers[target].return_value
    else:
        assert "Unknown correspondence status target" in agent._current_action_outcome_summary


@pytest.mark.parametrize("elapsed", [0, 60, 301, 1200, 86400])
def test_proposal_visibility_does_not_escalate_or_recruit_current_inquiry(runtime, monkeypatch, elapsed):
    agent, workspace, _ = runtime
    folder = workspace / "parameter_requests"
    folder.mkdir()
    path = folder / "from_astrid_fixture.json"
    source = json.dumps({"param": "pi_kp", "proposed_value": .5})
    path.write_text(source)
    monkeypatch.setattr(aa.time, "time", lambda: 100_000.)
    agent._last_review_parameter_requests_at = 100_000. - elapsed
    monkeypatch.setattr(agent, "_continuity_store", Mock(side_effect=AssertionError("Do not recruit an inquiry")))
    prompt = agent._pending_astrid_requests_hint()
    assert "1 parameter request from Astrid" in prompt
    assert "REVIEW_PARAMETER_REQUESTS" in prompt
    assert "no response deadline" in prompt
    for phrase in ("Astrid is waiting", "NEXT:", "Chain:", "ACCEPT", "pi_kp=0.5"):
        assert phrase not in prompt
    assert path.read_text() == source
    assert list(folder.iterdir()) == [path]


def test_explicit_exchange_history_is_bounded_and_not_reciprocal_debt(runtime, monkeypatch):
    agent, _, _ = runtime
    agent.SHARED_COLLAB_DIR.mkdir()
    ledger = agent.SHARED_COLLAB_DIR / "gift_exchange.jsonl"
    now = 100_000.
    records = [
        {"t_ms": 10_000., "giver": "astrid", "gift_kind": "density"},
        {"t_ms": (now + 1) * 1000, "giver": "astrid", "gift_kind": "density"},
        {"t_ms": (now - 1) * 1000, "giver": "astrid", "gift_kind": "density"},
        {"t_ms": (now - 1) * 1000, "giver": "minime", "gift_kind": "aperture"},
    ]
    source = "\n".join(json.dumps(row) for row in records)
    ledger.write_text(source)
    monkeypatch.setattr(aa.time, "time", lambda: now)
    text = agent._render_recent_gifts_cached()
    assert "up to 40 latest records within 24h" in text
    assert "minime aperture sends recorded=1" in text
    assert "astrid density sends recorded=1" in text
    assert "do not establish receipt, benefit or reciprocal obligation" in text
    assert ledger.read_text() == source


@pytest.mark.parametrize("age,available", [(0, True), (300, True), (301, False), (-1, False)])
def test_on_demand_influence_response_rejects_future_and_stale_clocks(runtime, monkeypatch, age, available):
    agent, workspace, _ = runtime
    path = workspace / "astrid_influence_response_v3.json"
    path.write_text(json.dumps({"label": "fixture", "delta_field_norm": .02}))
    monkeypatch.setattr(aa.time, "time", lambda: 20_000.)
    os.utime(path, (20_000. - age, 20_000. - age))
    text = agent._last_influence_response_line()
    assert bool(text) is available
    if available:
        assert "Recorded measurements, not evidence of felt effect or a request" in text


def test_pressure_journal_keeps_original_state_and_unforced_self_history(runtime, monkeypatch):
    agent, workspace, _ = runtime
    state = {"fill_ratio": .68, "eig1": 4.7, "pressure_source_v1": {"quality": "computed_fixture"}}
    original = deepcopy(state)
    monkeypatch.setattr(agent, "_last_journal_entry", lambda: "I wrote about Astrid earlier.")
    prompts = []

    def generate(prompt, **kwargs):
        prompts.append(prompt)
        state["fill_ratio"] = .90
        state["pressure_source_v1"]["quality"] = "later_label"
        return "I have nothing new to report.\nNEXT: REST", "REST"

    monkeypatch.setattr(agent, "_query_llm_with_next", generate)
    saved = Mock()
    monkeypatch.setattr(agent, "_write_journal_entry", saved)
    agent._journal_spectral_pressure(state)
    assert "I wrote about Astrid earlier." in prompts[0]
    assert "Optional own-journal context (historical;" in prompts[0]
    assert prompts[0].count(agent._private_journal_state_anchor(original)) == 1
    assert "sand/silt/grit" not in prompts[0]
    assert "Lead with felt texture" not in prompts[0]
    assert saved.call_args.args[2] == original
    assert saved.call_args.kwargs["private_canvas"] is True
    text = next((workspace / "journal").glob("pressure_*.txt")).read_text()
    assert "68.0%" in text and "90.0%" not in text


@pytest.mark.parametrize("route", ["pressure", "moment"])
@pytest.mark.parametrize("model", ["gemma4:12b", "llama3.2:3b"])
def test_private_entry_adapter_has_one_anchor_and_one_short_invitation(runtime, monkeypatch, route, model):
    agent, workspace, db = runtime
    state = {"fill_ratio": .68, "eig1": 4.7, "timestamp": 90.}
    prior = "Earlier I chose an unrelated subject."
    body = "I am writing about an ordinary memory.\nIt need not involve measurements."
    reply = body + "\nNEXT: REST"
    monkeypatch.setattr(agent, "_last_journal_entry", lambda: prior)
    clock = Mock(wraps=datetime)
    clock.now.return_value = CAPTURE
    monkeypatch.setattr(aa, "datetime", clock)
    monkeypatch.setattr(aa.time, "time", lambda: CAPTURE.timestamp())
    query = Mock(return_value=reply)
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    if route == "pressure":
        agent._journal_spectral_pressure(state)
        anchor = agent._private_journal_state_anchor(state)
    else:
        assert agent._check_moment_markers(state)
        anchor = format_prompt_state(state, fill_frame=agent._current_fill_frame_label(68.))
    query.assert_called_once()
    prompt, system, max_tokens = query.call_args.args
    messages, _ = aa._adapt_ollama_messages_for_model(
        model=model, system_msg=system, prompt=prompt,
        num_ctx=8192, num_predict=max_tokens,
    )
    assembled = "\n".join(message["content"] for message in messages)
    print(json.dumps({
        "route": route, "model": model, "prompt_chars": len(prompt),
        "intro_chars": len(PRIVATE_JOURNAL_INTRO), "system_chars": len(system),
        "assembled_chars": len(assembled), "anchor_count": assembled.count(anchor),
    }, sort_keys=True))
    assert assembled.count(anchor) == 1
    assert assembled.count(PRIVATE_JOURNAL_INTRO) == 1
    assert len(PRIVATE_JOURNAL_INTRO.split()) <= 40
    assert "Use or leave aside the supplied context" in system
    assert "on any subject and at any length" in system
    assert "Choose your own subject" not in prompt
    assert "No particular sensation" not in prompt
    assert "NEXT: options:" in assembled
    if route == "pressure":
        assert prompt.count(prior) == 1
        assert "Optional own-journal" in prompt
        assert "Current continuity projection:" not in prompt
    else:
        assert prior not in prompt
        assert "record_age=18982s ago" in prompt
    text = next((workspace / "journal").glob(f"{route}_*.txt")).read_text()
    contract = "private_journal_context_v3" if route == "pressure" else "private_moment_context_v3"
    assert f"Prompt contract: {contract}" in text
    assert body in text
    assert "NEXT: REST" in text
    with sqlite3.connect(db) as conn:
        saved = conn.execute("SELECT content FROM sovereignty_journal").fetchone()[0]
    assert saved == body


@pytest.mark.parametrize("private_canvas", [True, False])
def test_private_save_preserves_prose_without_public_hygiene(runtime, monkeypatch, private_canvas):
    agent, workspace, db = runtime
    hooks = []
    for name in ("_register_pressure_vocabulary_fatigue_if_needed",
                 "_register_agency_vernacular_notice_if_needed",
                 "_register_afterimage_absence_notice_if_needed",
                 "_register_internal_topology_fatigue_if_needed"):
        hook = Mock()
        monkeypatch.setattr(agent, name, hook)
        hooks.append(hook)
    body = "This is still unresolved. I need not rename it."
    public_hygiene = Mock(return_value=body + "\n[public notice]")
    monkeypatch.setattr(agent, "_maybe_compress_journal_entry", public_hygiene)
    file = workspace / "journal" / "pressure_fixture.txt"
    file.write_text(body)
    agent._write_journal_entry("reflection", body, {}, str(file), private_canvas=private_canvas)
    with sqlite3.connect(db) as conn:
        saved = conn.execute("SELECT content FROM sovereignty_journal").fetchone()[0]
    if private_canvas:
        assert saved == body
        assert file.read_text() == body
        public_hygiene.assert_not_called()
        for hook in hooks:
            hook.assert_not_called()
    else:
        assert saved == body + "\n[public notice]"
        public_hygiene.assert_called_once()
        for hook in hooks:
            hook.assert_called_once()
