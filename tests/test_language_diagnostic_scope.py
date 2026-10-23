"""Lexical matches retain provenance without becoming evidence or action routes."""

import copy
import json
import os
import sqlite3
from unittest.mock import patch

import pytest

import autonomous_agent as aa
import continuity_control_plane as ccp


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "deig": 0.01, "spread": 3.0}
MATCH = (
    'The spectral trace is not a single motif. The quoted phrase "constraint thinning" '
    "is not an observation of a physical change."
)
DIAGNOSTICS = (
    ("interpretation_risk_v1", "interpretation_risk", "interpretation language"),
    ("constraint_release_trajectory_v1", "constraint_release_trajectory", "constraint-release language"),
)
SELECTION = {
    "journal_candidate_limit": 120,
    "journal_match_limit": 3,
    "event_match_limit": 3,
    "retained_source_limit": 4,
    "match_required": True,
    "evidence_sufficiency_evaluated": False,
    "journal_order": "filesystem_modification_time_descending",
    "selection": "lexical_matches_only",
    "summary_fallback": False,
    "unmatched_history_evaluated_for_success": False,
}
REMOVED_FIELDS = (
    "interpretation_next", "trajectory_next", "dossier_claim_next",
    "research_budget_next", "sticky_audit_next", "continuity_session_v1",
    "continuity_session_next", "continuity_session_draft_v1",
)


@pytest.fixture
def context(tmp_path):
    store = aa.ActionContinuityStore(tmp_path / "workspace", session_id=17)
    thread = store.create_thread("Language diagnostic scope")
    return store, thread


def assert_language_only(diagnostic, key):
    assert diagnostic["policy"] == key
    assert diagnostic["diagnostic_version"] == 2
    assert diagnostic["status"] == "language_match"
    assert diagnostic["reason"] == "lexical_match_only"
    assert diagnostic["evidence_scope"] == "selected_language_only"
    assert diagnostic["experiment_association"] == "retained_context_not_evidence_of_effect"
    assert diagnostic["selection_is_representative"] is False
    assert diagnostic["occurrence_rate"] is None
    assert diagnostic["physical_state_verified"] is False
    assert diagnostic["interpretation_correctness_verified"] is False
    assert diagnostic["would_dispatch"] is False
    assert diagnostic["authority_change"] is False
    assert diagnostic["peer_mutation"] is False
    assert diagnostic["matched_terms"]
    assert diagnostic["source_refs"]
    assert diagnostic["raw_excerpt"]
    if key == "constraint_release_trajectory_v1":
        assert diagnostic["state"] == "not_measured"
    for field in REMOVED_FIELDS:
        assert diagnostic.get(field) is None


def journal(store, name, text, age_order):
    directory = store.workspace_dir / "journal"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(text)
    stamp = 1_700_000_000_000_000_000 + age_order * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))
    return path


def finish(store, outcome):
    event = store.begin_action("JOURNAL chosen topic", "JOURNAL", "journal", "journal", dict(STATE))
    return store.finish_action(event, "completed", outcome, dict(STATE))


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_one_negative_or_quoted_matching_source_is_only_a_language_match(context, key, stem, label):
    store, thread = context
    experiment = {"experiment_id": "exp_context_only"}
    with patch.object(store, "_research_budget_continuity_session_guidance", side_effect=AssertionError("editorial guidance")):
        diagnostic = getattr(store, f"_{stem}_for_sources")(
            thread, experiment, [("quoted-source", MATCH)],
        )
    assert_language_only(diagnostic, key)
    assert diagnostic["experiment_id"] == experiment["experiment_id"]
    assert diagnostic["source_refs"] == ["quoted-source"]
    assert diagnostic["raw_excerpt"] == MATCH
    assert "source_selection_v1" not in diagnostic
    rendered = getattr(store, f"_{stem}_line")({key: diagnostic})
    assert rendered == (
        f"Selected-language diagnostic ({label}): 1 retained source(s); "
        "lexical matches, not representative history or measured state. "
        "Interpretation and occurrence rate unverified.\n"
    )


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_supplied_event_diagnostic_does_not_claim_a_journal_scan(context, key, stem, label):
    store, thread = context
    with patch.object(store, f"_recent_{stem}_sources", side_effect=AssertionError("journal scan")):
        diagnostic = getattr(store, f"_{stem}_for_event")(
            thread, {"action_id": "supplied", "outcome_summary": MATCH},
        )
    assert_language_only(diagnostic, key)
    assert diagnostic["source_refs"] == [str(store._thread_dir(thread["thread_id"]) / "events.jsonl") + "#supplied"]
    assert "source_selection_v1" not in diagnostic


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_no_matching_source_produces_no_diagnostic(context, key, stem, label):
    store, thread = context
    project = getattr(store, f"_{stem}_projection_v1")
    assert project(thread, None, []) is None
    journal(store, "success.txt", "The work completed successfully without interruption.", 1)
    assert project(thread, None, [{"outcome_summary": "All checks passed."}]) is None


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_journal_candidate_and_match_caps_follow_filesystem_mtime(context, key, stem, label):
    store, thread = context
    oldest = journal(store, "zz_old_matching.txt", MATCH, 0)
    for index in range(120):
        journal(store, f"entry_{index:03d}.txt", "A successful uninterrupted task.", index + 1)
    scan = getattr(store, f"_recent_{stem}_sources")
    assert scan() == []  # The matching 121st candidate is outside the scan bound.
    expected = []
    for index, name in enumerate(("z.txt", "y.txt", "b.txt", "a.txt")):
        expected.insert(0, str(journal(store, name, MATCH, 121 + index)))
    assert [source for source, _ in scan()] == expected[:3]
    assert scan(limit=0) == []
    assert scan(limit=-1) == []
    assert [source for source, _ in scan(limit=1)] == expected[:1]
    diagnostic = getattr(store, f"_{stem}_projection_v1")(thread, None, [])
    assert_language_only(diagnostic, key)
    assert diagnostic["source_refs"] == expected[:3]
    assert diagnostic["source_selection_v1"] == SELECTION
    assert oldest.read_text() == MATCH


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_event_match_and_combined_retention_caps(context, key, stem, label):
    store, thread = context
    for index in range(4):
        newest_journal = journal(store, f"journal_{index}.txt", MATCH, index)
    events = [{"action_id": f"event_{index}", "outcome_summary": MATCH} for index in range(6)]
    event_path = str(store._thread_dir(thread["thread_id"]) / "events.jsonl")
    diagnostic = getattr(store, f"_{stem}_projection_v1")(thread, None, events)
    assert_language_only(diagnostic, key)
    assert diagnostic["source_refs"] == [
        f"{event_path}#event_5", f"{event_path}#event_4", f"{event_path}#event_3",
        str(newest_journal),
    ]
    assert diagnostic["source_selection_v1"] == SELECTION


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
def test_retained_summary_fallback_is_explicit_and_not_effect_evidence(context, key, stem, label):
    store, thread = context
    thread["experiment_summary"] = {"experiment_id": "exp_retained", "result": MATCH}
    before = copy.deepcopy(thread)
    diagnostic = getattr(store, f"_{stem}_projection_v1")(thread, None, [])
    assert_language_only(diagnostic, key)
    assert diagnostic["source_refs"] == [str(store._thread_dir(thread["thread_id"]) / "thread.json") + "#experiment_summary"]
    assert diagnostic["source_selection_v1"] == {**SELECTION, "summary_fallback": True}
    assert thread == before
    path = journal(store, "fresh.txt", MATCH, 1)
    fresh = getattr(store, f"_{stem}_projection_v1")(thread, None, [])
    assert fresh["source_selection_v1"] == SELECTION
    assert fresh["source_refs"] == [str(path)]


def test_nonmatching_success_remains_in_history_not_a_representative_sample(context):
    store, thread = context
    matching = finish(store, MATCH)
    success = finish(store, "The chosen task succeeded without interruption.")
    thread = store._read_thread(thread["thread_id"])
    projection = store._thread_projection(thread)
    events_path = store._thread_dir(thread["thread_id"]) / "events.jsonl"
    rows = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert rows[-1]["action_id"] == success["action_id"]
    assert rows[-1]["outcome_summary"] == success["outcome_summary"]
    assert any(success["outcome_summary"] in item for item in projection["recent_event_summaries"])
    for key, _, _ in DIAGNOSTICS:
        assert key not in success
        diagnostic = projection[key]
        assert_language_only(diagnostic, key)
        assert diagnostic["source_refs"] == [f"{events_path}#{matching['action_id']}"]
        assert diagnostic["source_selection_v1"]["unmatched_history_evaluated_for_success"] is False


def test_finishing_language_match_preserves_next_and_creates_no_sessions_or_claims(context):
    store, thread = context
    directory = store._thread_dir(thread["thread_id"])
    protected = [directory / name for name in (
        "continuity_sessions.jsonl", "research_dossier.jsonl", "being_memory.jsonl",
        "authority_gate.jsonl", "experiment_runs.jsonl",
    )]
    for path in protected:
        path.touch(exist_ok=True)
    before = {path: path.read_bytes() for path in protected}
    with patch.object(store, "_append_continuity_session_draft", side_effect=AssertionError("automatic session")):
        event = finish(store, MATCH)
        refreshed = store._read_thread(thread["thread_id"])
        store._write_thread(refreshed)
        projection = store._thread_projection(refreshed)
        prompt = store.prompt_summary()
        status = store._format_thread_status(refreshed)
    assert event["suggested_next"] == "JOURNAL chosen topic"
    assert refreshed["current_next"] == "JOURNAL chosen topic"
    assert before == {path: path.read_bytes() for path in protected}
    for key, _, label in DIAGNOSTICS:
        assert_language_only(event[key], key)
        assert_language_only(projection[key], key)
        assert f"Selected-language diagnostic ({label}): 1 retained source(s)" in status
    for route in projection["continuity_control_plane_v1"]["route_stack"]:
        assert route["source"] != "self_study_cue"
    for surface in (prompt, (directory / "next.md").read_text()):
        assert "Selected-language diagnostic" not in surface
        assert "Interpretation NEXT:" not in surface
        assert "Trajectory NEXT:" not in surface
        assert "interpretation or release cue needs capture" not in surface


@pytest.mark.parametrize("old_version", [12, 13])
def test_derived_views_refresh_without_rewriting_legacy_records(context, old_version):
    store, thread = context
    directory = store._thread_dir(thread["thread_id"])
    source = journal(store, "legacy.txt", MATCH, 1)
    legacy = {
        "policy": "interpretation_risk_v1", "status": "detected",
        "source_refs": [str(source)], "matched_terms": ["single-motif"],
        "raw_excerpt": MATCH, "interpretation_next": "CONTINUITY_SESSION_START current",
        "dossier_claim_next": "DOSSIER_CLAIM latest :: claim: old claim; stance: hold",
    }
    event = store.begin_action("JOURNAL chosen topic", "JOURNAL", "journal", "journal", dict(STATE))
    event.update(status="completed", outcome_summary=MATCH, interpretation_risk_v1=legacy)
    store._append_jsonl(directory / "events.jsonl", event)
    store._append_jsonl(directory / "experiment_runs.jsonl", {"legacy_diagnostic": legacy})
    (directory / "continuity_sessions.jsonl").touch(exist_ok=True)
    protected = [source, directory / "events.jsonl", directory / "experiment_runs.jsonl", directory / "continuity_sessions.jsonl"]
    before = {path: path.read_bytes() for path in protected}
    stale = store._read_thread(thread["thread_id"])
    stale["interpretation_risk_v1"] = copy.deepcopy(legacy)
    stale["projection_freshness_v1"]["schema_version"] = old_version
    stale["projection_freshness_v1"]["projection_policy_marker"] = "read_only_choice_preservation_v12"
    stale["continuity_control_plane_v1"] = aa.build_continuity_control_plane_v1(stale)
    legacy_route = {
        "group": "Continuity Session", "command": "CONTINUITY_SESSION_CAPTURE latest",
        "reason": "interpretation or release cue needs capture", "priority": 10,
        "source": "self_study_cue", "policy_class": "continuity_capture",
    }
    stale["continuity_control_plane_v1"]["primary_route"] = legacy_route
    stale["continuity_control_plane_v1"]["route_stack"] = [legacy_route]
    store._write_json(directory / "thread.json", stale)
    (directory / "next.md").write_text("Interpretation NEXT: CONTINUITY_SESSION_START current\n")
    refreshed = store._read_thread(thread["thread_id"])
    assert store.schema_version == 1
    assert refreshed["projection_freshness_v1"]["schema_version"] == 14
    assert refreshed["projection_freshness_v1"]["projection_policy_marker"] == "quiet_lexical_drafts_v14"
    assert_language_only(refreshed["interpretation_risk_v1"], "interpretation_risk_v1")
    assert before == {path: path.read_bytes() for path in protected}
    assert "Interpretation NEXT:" not in (directory / "next.md").read_text()
    assert not any(route["source"] == "self_study_cue" for route in refreshed["continuity_control_plane_v1"]["route_stack"])
    old_render = store._interpretation_risk_line({"interpretation_risk_v1": legacy})
    assert "NEXT" not in old_render
    assert legacy["status"] == "detected"
    assert json.loads((directory / "events.jsonl").read_text().splitlines()[0])["interpretation_risk_v1"] == legacy


@pytest.mark.parametrize("key,stem,label", DIAGNOSTICS)
@pytest.mark.parametrize("cue", [
    None,
    {"status": "detected", "trajectory_next": "CONTINUITY_SESSION_CAPTURE latest"},
    {"diagnostic_version": 2, "status": "language_match", "reason": "lexical_match_only"},
], ids=["null", "legacy", "v2"])
@pytest.mark.parametrize("owned_route", ["none", "session", "draft"])
def test_control_plane_ignores_lexical_cues_and_preserves_owned_routes(key, stem, label, cue, owned_route):
    projection = {"continuity_return": "EXPERIMENT_RESUME exp_owned"}
    if owned_route == "session":
        projection["continuity_session_v1"] = {
            "active_session": {"status": "active", "suggested_next": "CONTINUITY_SESSION_CAPTURE sess_owned"},
        }
    elif owned_route == "draft":
        projection["continuity_session_draft_v1"] = {"accept_next": "CONTINUITY_SESSION_ACCEPT sess_owned"}
    baseline = ccp.build_continuity_control_plane_v1(projection)
    with_cue = ccp.build_continuity_control_plane_v1({**projection, key: cue})
    assert with_cue == baseline
    assert ccp.continuity_control_plane_text(with_cue) == ccp.continuity_control_plane_text(baseline)
    assert all(route["source"] != "self_study_cue" for route in with_cue["route_stack"])
    explicit = [route for route in with_cue["route_stack"] if route["policy_class"] == "continuity_capture"]
    if owned_route == "none":
        assert explicit == []
    else:
        assert len(explicit) == 1
        assert explicit[0]["priority"] == (20 if owned_route == "session" else 19)
        assert explicit[0]["command"].endswith("sess_owned")


def test_real_research_budget_guard_still_drafts_once_with_lexical_matches(context):
    store, thread = context
    store.start_experiment("Guarded study", "Can an explicit guarded action retain its guard?")
    action = f"SHADOW_DIALOGUE shift landscape: {MATCH}"
    guard = store.research_budget_guard_assessment(action, dict(STATE))
    assert guard["reason"] == "liveish_pressure_requires_budget_and_session_capture"
    with patch.object(store, "_append_continuity_session_draft", wraps=store._append_continuity_session_draft) as drafts:
        event = store.record_research_budget_guard_block(action, dict(STATE), guard)
    assert drafts.call_count == 1
    assert event["research_budget_v1"]["continuity_session_draft_v1"]
    assert event["research_budget_v1"]["would_dispatch"] is False
    for key, _, _ in DIAGNOSTICS:
        assert_language_only(event[key], key)
    rows = [json.loads(line) for line in (store._thread_dir(thread["thread_id"]) / "continuity_sessions.jsonl").read_text().splitlines()]
    assert [row["record_type"] for row in rows] == ["session_draft"]


def sticky_state():
    return {
        **STATE, "lambda1_share": 0.62, "spectral_entropy": 0.35,
        "effective_modes": 2.0, "largest_gap": 2.6,
        "temporal_persistence": 0.86, "share_rearrangement": 0.02,
        "esn_leak": 0.65,
    }


@pytest.mark.parametrize("field", [
    "constraint_release_text", "release_language", "latest_reply", "raw_next", "self_study_text",
])
def test_control_gate_does_not_use_prose_or_retained_diagnostics_as_measurements(context, field):
    store, thread = context
    experiment = store.start_experiment("Synthetic scope", "Which input affects eligibility?")
    request = {
        "scope": "mode_release_microdose",
        "payload": "target=esn_leak; value=0.71; duration_ticks=3",
        "artifact_refs": ["synthetic/sticky-audit"],
    }
    state = sticky_state()
    baseline = store._authority_gate_eligibility(thread, experiment, request, state)
    assert "no_spontaneous_release_watch" not in baseline["missing_requirements"]
    assert store._sticky_mode_v1(state)["state"] == "release_candidate"
    # Top-level retained diagnostics are a different input family, despite the shared name.
    for key, _, _ in DIAGNOSTICS:
        injected = {**state, key: {"state": "spontaneous_release_watch", "blocks_mode_release": True}}
        assert store._authority_gate_eligibility(thread, experiment, request, injected) == baseline
    matched = {**state, field: MATCH}
    assessment = store._authority_gate_eligibility(thread, experiment, request, matched)
    assert assessment == baseline
    trajectory = store._sticky_mode_v1(matched)["constraint_release_trajectory_v1"]
    assert trajectory["blocks_mode_release"] is False
    assert trajectory["state"] == "constraint_thickening"
    assert trajectory["classifier_version"] == 2
    assert trajectory["language_is_control_evidence"] is False
    assert not any(signal.startswith("language:") for signal in trajectory["support_signals"])


def test_normal_spectral_snapshot_does_not_import_journal_or_choice_text(tmp_path):
    db = tmp_path / "synthetic.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE esn_metrics (session_id, timestamp, esn_eig1, esn_deig,
                esn_leak, esn_lambda, esn_baseline, esn_geom_radius, esn_geom_rel);
            CREATE TABLE eigenvalue_timeline (session_id, timestamp, lambda1,
                lambda2, lambda3, fill_ratio, spread);
            INSERT INTO esn_metrics VALUES (17, 10, 4.7, 0.01, 0.65, 0.99, 4.5, 1.2, 1);
            INSERT INTO eigenvalue_timeline VALUES (17, 10, 8, 3, 2, 0.68, 6);
        """)
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    agent.session_id = 17
    agent.last_reply = MATCH
    agent._pending_next_action = MATCH
    with patch.object(aa, "DB_PATH", db), patch.object(agent, "_sensory_gate_status", return_value={}):
        state = agent._get_latest_spectral_state()
    assert state is not None
    assert state["leak"] == 0.65
    for key in ("constraint_release_text", "release_language", "latest_reply", "raw_next", "self_study_text"):
        assert key not in state
    assert agent.last_reply == MATCH
    assert agent._pending_next_action == MATCH


@pytest.mark.parametrize("reason", ["single_motif_overfit_risk", "map_release_before_intervening"])
@pytest.mark.parametrize("with_experiment", [False, True])
def test_retired_lexical_draft_is_quiet_but_inspectable_and_explicitly_acceptable(context, reason, with_experiment):
    store, thread = context
    experiment = store.start_experiment("Synthetic retained work", "A chosen question") if with_experiment else None
    thread = store._read_thread(thread["thread_id"])
    draft = store._append_continuity_session_draft(
        thread, experiment, reason, "SELF_STUDY CONTINUE",
        "Synthetic legacy generated summary", source_refs=["synthetic/history"],
    )
    path = store._continuity_sessions_path(thread["thread_id"])
    before = path.read_bytes()
    projection = store._thread_projection(thread)
    assert draft["ignored_until_accepted"] is True
    assert projection["continuity_session_v1"] is None
    assert projection["continuity_session_draft_v1"]["record_id"] == draft["record_id"]
    routes = projection["continuity_control_plane_v1"]["route_stack"]
    assert not any(
        route["source"] == "continuity_session_draft_v1"
        and route["command"] == draft["accept_next"]
        for route in routes
    )
    assert store._continuity_session_line(thread, experiment, compact=True) == ""
    assert store._continuity_session_line(thread, experiment) == ""
    assert draft["accept_next"] not in store.prompt_summary()
    inspected = json.loads(store.continuity_session_status(draft["record_id"]).split("\n", 1)[1])
    assert inspected["retained_draft"] == draft
    assert path.read_bytes() == before
    assert store._read_thread(thread["thread_id"])["current_next"] == thread["current_next"]
    stale = store._read_thread(thread["thread_id"])
    stale["projection_freshness_v1"]["schema_version"] = 13
    route = {"command": draft["accept_next"], "source": "continuity_session_draft_v1"}
    stale["continuity_control_plane_v1"]["primary_route"] = route
    stale["continuity_control_plane_v1"]["route_stack"] = [route]
    store._write_json(store._thread_dir(thread["thread_id"]) / "thread.json", stale)
    # Restart must not re-promote a derived route. Acceptance remains an explicit choice.
    reopened = aa.ActionContinuityStore(store.workspace_dir, session_id=17)
    assert draft["accept_next"] not in reopened.prompt_summary()
    assert path.read_bytes() == before
    assert not any(route["source"] == "continuity_session_draft_v1" for route in
                   reopened._read_thread(thread["thread_id"])["continuity_control_plane_v1"]["route_stack"])
    assert "Accepted continuity-session draft" in reopened.continuity_session_accept(draft["record_id"])
    assert path.read_bytes().startswith(before)
    assert "Continuity session:" in reopened._continuity_session_line(thread, experiment)
    assert reopened._continuity_session_rows(thread["thread_id"])[-1]["summary"] == draft["summary"]


@pytest.mark.parametrize("change", [
    {"reason": "research_budget_required"}, {"reason": {}}, {"draft_v1": False},
    {"record_type": "session_start"}, {"ignored_until_accepted": False}, {"status": "active"},
])
def test_retirement_requires_exact_generated_draft_provenance(context, change):
    store, thread = context
    draft = store._append_continuity_session_draft(thread, None, "single_motif_overfit_risk", "READ", "kept")
    assert ccp.retired_lexical_session_draft(draft)
    candidate = {**draft, **change}
    assert not ccp.retired_lexical_session_draft(candidate)
    projection = {"continuity_session_draft_v1": candidate}
    routes = ccp.build_continuity_control_plane_v1(projection)["route_stack"]
    assert any(route["command"] == draft["accept_next"] for route in routes)


@pytest.mark.parametrize("evidence, expected", [
    ({"entropy_delta": 0.08, "effective_modes_delta": 0.75}, "constraint_thinning_watch"),
    ({"entropy_delta": 0.08, "effective_modes_delta": 0.75, "largest_gap_delta": -0.25}, "spontaneous_release_watch"),
    ({"esn_leak_override_active": True}, "post_release_settling"),
    ({"esn_leak_override_v1": {"active": True}}, "post_release_settling"),
])
def test_real_numeric_and_override_checks_survive_conflicting_language(context, evidence, expected):
    store, thread = context
    experiment = store.start_experiment("Control evidence", "Numeric evidence only")
    request = {"scope": "mode_release_microdose", "payload": "target=esn_leak; value=0.71; duration_ticks=3"}
    state = {**sticky_state(), **evidence}
    baseline = store._authority_gate_eligibility(thread, experiment, request, state)
    assert "no_spontaneous_release_watch" in baseline["missing_requirements"]
    for label in ("constraint_thickening", "post_release_settling", "spontaneous_release_watch", MATCH):
        injected = {**state, "constraint_release_state": label, "constraint_release_trajectory": label,
                    "constraint_release_text": MATCH}
        assert store._authority_gate_eligibility(thread, experiment, request, injected) == baseline
        trajectory = store._sticky_mode_v1(injected)["constraint_release_trajectory_v1"]
        assert trajectory["state"] == expected
        assert trajectory["blocks_mode_release"] is True


@pytest.mark.parametrize("field", ["constraint_release_state", "constraint_release_trajectory"])
def test_unproven_state_labels_do_not_create_a_release_condition(context, field):
    store, _ = context
    baseline = store._sticky_mode_v1(sticky_state())
    for value in ("spontaneous_release_watch", "post_release_settling", {"state": "constraint_thinning_watch"}):
        assert store._sticky_mode_v1({**sticky_state(), field: value}) == baseline


def test_non_numeric_delta_values_are_not_control_evidence(context):
    store, _ = context
    baseline = store._sticky_mode_v1(sticky_state())
    for value in (MATCH, True, float("nan"), float("inf"), None):
        state = {**sticky_state(), "entropy_delta": value, "effective_modes_delta": value,
                 "share_rearrangement_delta": value}
        assert store._sticky_mode_v1(state) == baseline


def test_quiet_latest_draft_does_not_promote_an_older_unselected_draft(context, monkeypatch):
    store, thread = context
    monkeypatch.setattr(aa.time, "time", lambda: 1_700_000_000.125)
    earlier = store._append_continuity_session_draft(thread, None, "research_budget_required", "READ", "earlier")
    latest = store._append_continuity_session_draft(thread, None, "map_release_before_intervening", "READ", "latest")
    assert earlier["record_id"] != latest["record_id"]
    assert store._continuity_session_line(thread, None) == ""
    projection = store._thread_projection(thread)
    assert projection["continuity_session_draft_v1"]["record_id"] == latest["record_id"]
    assert not any(route["source"] == "continuity_session_draft_v1" for route in projection["continuity_control_plane_v1"]["route_stack"])
    assert store._resolve_continuity_session_draft(thread, earlier["record_id"]) == earlier
    reopened = aa.ActionContinuityStore(store.workspace_dir, session_id=17)
    assert reopened._resolve_continuity_session_draft(thread, earlier["record_id"]) == earlier
    assert reopened._resolve_continuity_session_draft(thread, latest["record_id"]) == latest


def test_legacy_continuity_record_ids_remain_exactly_retrievable(context):
    store, thread = context
    legacy = store._continuity_session_record(
        "session_draft", "legacy-session", thread, None, "draft",
        summary="Synthetic historical record", extra={"draft_v1": True},
    )
    legacy["record_id"] = "cs_minime_1700000000125_session-draft"
    path = store._continuity_sessions_path(thread["thread_id"])
    store._append_jsonl(path, legacy)
    before = path.read_bytes()
    reopened = aa.ActionContinuityStore(store.workspace_dir, session_id=17)
    assert reopened._resolve_continuity_session_draft(thread, legacy["record_id"]) == legacy
    assert path.read_bytes() == before
