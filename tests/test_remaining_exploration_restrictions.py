"""Synthetic qualification of choice preservation and creation-only eligibility."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import research_transactions as tx


STATE = {"fill_ratio": 0.68, "eig1": 4.7, "spread": 3.0}
SCOPE = {
    "eligibility_scope": "research_budget_creation",
    "action_admission_evaluated": False,
    "execution_authorized": False,
    "publication_evaluated": False,
    "disabled_actions_scope": "this_budget_only",
}


@pytest.fixture
def store(tmp_path):
    return aa.ActionContinuityStore(tmp_path / "workspace", session_id=7)


def paused(store):
    thread = store.create_thread("Synthetic inspection")
    experiment = store.start_experiment("Retained question", "What does the saved record say?")
    store.experiment_decide(experiment["experiment_id"], "pause until explicitly selected")
    experiment = store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])
    return thread, experiment


def repeat_history(store, thread, experiment, *, diluted=False):
    actions = [f"EXPERIMENT_RESUME {experiment['experiment_id']}"] * 2
    actions += [f"EXPERIMENT_REVIEW {experiment['experiment_id']}"] * 3
    if diluted:
        actions += ["JOURNAL"] * 40
    for index, action in enumerate(actions):
        store._append_jsonl(store._thread_dir(thread["thread_id"]) / "events.jsonl", {
            "schema_version": store.schema_version, "action_id": f"synthetic_{index}",
            "thread_id": thread["thread_id"], "system": "minime", "raw_next": action,
            "canonical_action": action, "effective_action": action,
            "route": "thread_action", "stage": "read_only", "status": "handled",
            "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:00:01+00:00",
            "outcome_summary": "Synthetic metadata inspection",
        })


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("base", ["EXPERIMENT_REVIEW", "EXPERIMENT_STATUS"])
@pytest.mark.parametrize("diluted", [False, True])
def test_actual_projection_consumers_preserve_explicit_inspection(store, base, diluted):
    thread, experiment = paused(store)
    repeat_history(store, thread, experiment, diluted=diluted)
    folder = store._thread_dir(thread["thread_id"])
    chosen = f"{base} {experiment['experiment_id']}"
    current = json.loads((folder / "thread.json").read_bytes())
    current["current_next"] = chosen
    current["raw_current_next_v1"] = "EXPERIMENT_PLAN 1 old pressure"
    current["projection_freshness_v1"] = {"schema_version": 11}
    current["current_next_status_v1"] = {
        "status": "shadowed_by_paused_summary", "effective_next": "REGULATOR_AUDIT current-fill_pressure",
        "paused_review_loop_repair_v1": {"status": "projected_regulator_audit_before_repeat_review"},
    }
    (folder / "thread.json").write_text(json.dumps(current))
    histories = {name: (folder / name).read_bytes() for name in ("events.jsonl", "experiments.jsonl")}

    refreshed = store._read_thread(thread["thread_id"])
    projection = store._thread_projection(refreshed)
    assert refreshed["current_next"] == chosen
    assert projection["current_next_status_v1"]["effective_next"] == chosen
    assert projection["paused_review_loop_cue_v1"] is None
    assert "paused_review_loop_repair_v1" not in refreshed["current_next_status_v1"]
    assert refreshed["active_experiment_id"] is None
    for surface in (store.prompt_summary(), store._format_thread_status(refreshed),
                    (folder / "next.md").read_text()):
        assert f"Current NEXT: {chosen}" in surface
        assert "guidance routes" not in surface
        assert "REGULATOR_AUDIT current-fill_pressure" not in surface
    for _ in range(3):
        response = store.handle_thread_action(chosen, STATE)
        assert experiment["experiment_id"] in response
        assert "REGULATOR_AUDIT current-fill_pressure" not in response
    assert {name: (folder / name).read_bytes() for name in histories} == histories
    assert store._find_experiment_by_id(thread["thread_id"], experiment["experiment_id"])["status"] == "paused"


def test_retained_review_cue_is_inert_even_when_supplied_directly(store):
    chosen = "EXPERIMENT_REVIEW exp_minime_fixture"
    status = {"effective_next": chosen, "primary_return_next": chosen, "return_kind": "inspection"}
    old = {"recommended_next": "REGULATOR_AUDIT current-fill_pressure",
           "attempted_review_next": chosen, "cue": "Use audit before another review."}
    before = deepcopy(status)
    assert store._demote_paused_review_loop_next_v1(status, old) is status
    assert status == before
    projection = {"planned_next": chosen, "paused_review_loop_cue_v1": old}
    assert store._review_suggested_next(projection) == chosen
    for compact in (False, True):
        assert store._paused_review_loop_cue_line(projection, compact=compact) == ""


@pytest.mark.parametrize("command", ["EXPERIMENT_REVIEW", "EXPERIMENT_STATUS", "REST"])
def test_real_choice_routing_keeps_metadata_and_rest_non_generating(monkeypatch, command):
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = True
    agent._hard_recovery_reset = False
    agent._low_fill_guard_status = Mock(return_value={"active": False})
    agent._stable_core_action_allowed = Mock(return_value=(True, "synthetic healthy state"))
    agent._canonical_source_action = lambda action: action
    agent._log_decision = Mock()
    for name in ("_query_llm", "_query_llm_raw", "_queue_llm_action_job"):
        setattr(agent, name, Mock(side_effect=AssertionError("metadata must not generate")))
    monkeypatch.setattr(aa.requests, "post", Mock(side_effect=AssertionError("no provider")))
    monkeypatch.setattr(aa.websocket, "create_connection", Mock(side_effect=AssertionError("no control")))
    local = agent._continuity_store()
    thread, experiment = paused(local)
    repeat_history(local, thread, experiment)
    choice = command if command == "REST" else f"{command} {experiment['experiment_id']}"
    agent._pending_next_action = choice
    agent._persist_pending_next_action(choice, reason="synthetic explicit choice")
    route = agent._decide_action(STATE)
    if command == "REST":
        assert route is None
        assert agent._scheduler_observation["reason"] == "explicit_rest"
    else:
        assert route == "thread_action"
        assert agent._pending_action_continuity_context["raw_next"] == choice
        agent._execute_action(route, STATE)
    assert agent._pending_next_action is None
    agent._query_llm.assert_not_called()
    agent._query_llm_raw.assert_not_called()
    agent._queue_llm_action_job.assert_not_called()


@pytest.mark.parametrize("plan", [
    "EXPERIMENT_CHARTER current :: hypothesis: synthetic repair",
    "THREAD_STATUS current",
    "EXPERIMENT_PLAN current :: inspect perturbation vocabulary",
    "CONTROL amplitude=0.1",
])
def test_explicit_resume_appends_one_context_revision_without_renewing_held_budget(store, plan):
    thread, experiment = paused(store)
    experiment["planned_next"] = plan
    experiment["charter_v1"] = {"hypothesis": "Synthetic retained charter"}
    experiment["evidence_v1"] = {"synthetic": "retained evidence"}
    store._persist_experiment_update(store._read_thread(thread["thread_id"]), experiment, keep_active=False)
    gate = store._authority_gate_path(thread["thread_id"])
    for kind, fields in [
        ("research_budget_approval", {"scope": "read_only_research", "status": "active",
            "max_actions": 5, "expires_at_unix_s": 4102444800, "allowed_sources": ["local"]}),
        ("research_budget_review", {"outcome": "hold"}),
    ]:
        store._append_jsonl(gate, store._research_budget_record(kind, "resbud_held", thread, experiment, STATE, fields))
    history_path = store._experiments_path(thread["thread_id"])
    before = history_path.read_bytes()
    budget_before = gate.read_bytes()
    runs_before = store._experiment_runs_path(thread["thread_id"]).read_bytes()

    result = store.experiment_resume(experiment["experiment_id"])
    assert "Context selected; saved next action was not executed" in result
    after = history_path.read_bytes()
    assert after.startswith(before)
    rows = after[len(before):].splitlines()
    assert len(rows) == 1
    resumed = json.loads(rows[0])
    assert resumed["status"] == "active"
    assert {key: value for key, value in resumed.items() if key not in {"status", "updated_at"}} == {
        key: value for key, value in experiment.items() if key not in {"status", "updated_at"}}
    assert store._read_thread(thread["thread_id"])["active_experiment_id"] == experiment["experiment_id"]
    store.experiment_resume(experiment["experiment_id"])
    assert history_path.read_bytes() == after
    assert gate.read_bytes() == budget_before
    assert store._experiment_runs_path(thread["thread_id"]).read_bytes() == runs_before
    assert store._active_research_budget(thread["thread_id"], experiment["experiment_id"]) is None
    with pytest.raises(ValueError, match="allowance|budget"):
        tx.admit(store, experiment["experiment_id"], "INTROSPECT autonomous_agent.py", "held-operation", STATE)
    assert gate.read_bytes() == budget_before


def test_start_match_does_not_resume_or_append_parked_context(store):
    thread, experiment = paused(store)
    path = store._experiments_path(thread["thread_id"])
    before = path.read_bytes()
    result = store.start_experiment(experiment["experiment_id"], "ignored question")
    assert result["_selection_blocked"] is True
    assert path.read_bytes() == before
    assert store._read_thread(thread["thread_id"])["active_experiment_id"] is None


@pytest.mark.parametrize("plan,kind", [
    ("EXPERIMENT_CHARTER current :: hypothesis: retained repair", "charter_repair"),
    ("THREAD_STATUS current", "hold"),
    ("EXPERIMENT_REVIEW exp_minime_fixture", "inspection"),
    ("EXPERIMENT_PLAN current :: proposed_next_action: PERTURB", "resume"),
])
def test_paused_summary_preserves_saved_references_not_keyword_repair(store, plan, kind):
    thread, experiment = paused(store)
    experiment["planned_next"] = plan
    current = store._read_thread(thread["thread_id"])
    current["experiment_summary"] = store._experiment_summary(experiment)
    current["raw_current_next_v1"] = "EXPERIMENT_PLAN current :: proposed_next_action: PERTURB"
    summary = store._last_experiment_summary_v1(current)
    assert summary["planned_next"] == plan
    assert summary["return_kind"] == kind
    assert "projection_guard_v1" not in summary
    if kind != "resume":
        assert summary["primary_return_next"] == plan


@pytest.mark.parametrize("failure,missing", [
    ("none", None), ("purpose", "research_purpose"),
    ("scope", "scope_read_only_research_v1"), ("sources", "allowed_sources_web_or_local"),
    ("safety", "green_or_yellow_safety"), ("active", "no_active_read_only_research_budget"),
])
def test_creation_eligibility_is_pure_scoped_metadata_with_existing_safeguards(store, failure, missing):
    thread = store.create_thread("Eligibility scope")
    experiment = store.start_experiment("Creation only", "What does eligibility evaluate?")
    request = {"scope": "read_only_research", "purpose": "Synthetic local inspection", "allowed_sources": ["local"]}
    state = dict(STATE)
    if failure == "purpose":
        request["purpose"] = ""
    elif failure == "scope":
        request["scope"] = "control_envelope"
    elif failure == "sources":
        request["allowed_sources"] = []
    elif failure == "safety":
        state["fill_ratio"] = .96
    elif failure == "active":
        store._append_jsonl(store._authority_gate_path(thread["thread_id"]),
            store._research_budget_record("research_budget_approval", "resbud_existing", thread, experiment, state,
                {"scope": "read_only_research", "status": "active", "max_actions": 5,
                 "expires_at_unix_s": 4102444800, "allowed_sources": ["local"]}))
    before = snapshot(store.root)
    result = store._research_budget_eligibility(thread, experiment, request, state)
    assert {key: result[key] for key in SCOPE} == SCOPE
    assert result["policy"] == "research_budget_v1"
    assert result["eligible"] == (missing is None)
    assert result["missing_requirements"] == ([] if missing is None else [missing])
    assert "CONTROL" in result["disabled_actions"]
    assert result["enabled_execution_scope"] == "read_only_research"
    assert snapshot(store.root) == before


def test_request_and_historical_status_present_creation_scope_without_rewriting_receipts(store):
    thread = store.create_thread("Eligibility presentation")
    experiment = store.start_experiment("Local request", "What can this allowance authorize?")
    response = store.experiment_research_budget_request(
        f"{experiment['experiment_id']} :: scope: read_only_research; purpose: synthetic inspection; "
        "allowed_sources: local; stop_criteria: one observation", STATE)
    assert "Eligibility concerns budget creation only" in response
    assert "not globally prohibited" in response
    request = json.loads(response.split("research_budget_v1:\n", 1)[1])
    assert {key: request["eligibility_v1"][key] for key in SCOPE} == SCOPE
    assert request["stop_criteria"] == "one observation"
    gate = store._authority_gate_path(thread["thread_id"])
    old = deepcopy(request)
    old["record_id"] = "synthetic_legacy_request"
    old["eligibility_v1"] = {"policy": "research_budget_v1", "eligible": False, "disabled_actions": ["CONTROL"]}
    store._append_jsonl(gate, old)
    before = gate.read_bytes()
    status = store._research_budget_status_v1(thread, experiment, STATE, selector=experiment["experiment_id"])
    assert status["creation_eligibility_scope_v1"] == SCOPE
    assert status["latest_rows"][-1] == old
    assert gate.read_bytes() == before


def test_generated_budget_guidance_separates_allowance_and_action_authority(store):
    thread, experiment = paused(store)
    before = snapshot(store.root)
    boundary = store._research_budget_boundary()
    assert "only to explicitly bound research" in boundary
    assert "Ordinary reading, writing, and context return do not require it" in boundary
    assert "larger or web-enabled budgets still require steward approval" in boundary
    assert "grants no network, control, or peer-mutation authority" in boundary
    assert "Standing web authorization" in boundary
    scaffold = store._research_budget_request_scaffold(experiment)
    for term in ("chosen hold/close", "expiry/exhaustion", "unavailable source", "safety/resource/privacy"):
        assert term in scaffold
    assert "duplicate source loops" not in scaffold
    assert "bind/resume" not in scaffold
    assert snapshot(store.root) == before


@pytest.mark.parametrize("choice", ["INTROSPECT autonomous_agent.py", "WRITE LIST", "JOURNAL", "REST"])
def test_snapshot_refresh_and_next_md_keep_newer_ordinary_choice(store, choice):
    thread = store.create_thread("Newer choice")
    experiment = store.start_experiment("Old context", "Synthetic context question")
    folder = store._thread_dir(thread["thread_id"])
    experiment["status"] = "paused"
    experiment["planned_next"] = "THREAD_STATUS current"
    store._append_jsonl(store._experiments_path(thread["thread_id"]), experiment)
    old = json.loads((folder / "thread.json").read_bytes())
    old["current_next"] = choice
    old["projection_freshness_v1"] = {"schema_version": 11}
    (folder / "thread.json").write_text(json.dumps(old))
    before = store._experiments_path(thread["thread_id"]).read_bytes()
    refreshed = store._read_thread(thread["thread_id"])
    assert refreshed["active_experiment_id"] is None
    assert refreshed["current_next"] == choice
    assert refreshed["current_next_status_v1"]["effective_next"] == choice
    assert f"Current NEXT: {choice}" in (folder / "next.md").read_text()
    assert f"Current NEXT: {choice}" in store.prompt_summary()
    assert store._experiments_path(thread["thread_id"]).read_bytes() == before
    store.experiment_resume(experiment["experiment_id"])
    assert store._read_thread(thread["thread_id"])["current_next"] == choice
    assert f"Current NEXT: {choice}" in (folder / "next.md").read_text()


@pytest.mark.parametrize("status", ["active", "paused"])
@pytest.mark.parametrize("damage", ["corrupt_tail", "incomplete_tail", "foreign_owner", "symlink"])
def test_resume_refuses_unreadable_owner_history_before_projection_repair(store, status, damage):
    thread, experiment = paused(store)
    experiment["status"] = status
    path = store._experiments_path(thread["thread_id"])
    store._append_jsonl(path, experiment)
    if damage == "corrupt_tail":
        path.write_bytes(path.read_bytes() + b"{bad-json}\n")
    elif damage == "incomplete_tail":
        path.write_bytes(path.read_bytes() + b"{")
    elif damage == "foreign_owner":
        invalid = dict(experiment, experiment_id="exp_astrid_synthetic")
        store._append_jsonl(path, invalid)
    else:
        target = path.with_name("retained-history.jsonl")
        path.rename(target)
        path.symlink_to(target)
    with tx.transaction(store.root):
        pass
    before = snapshot(store.root)
    with pytest.raises(ValueError):
        store.experiment_resume(experiment["experiment_id"])
    assert snapshot(store.root) == before
    if damage == "symlink":
        assert path.is_symlink()


def test_concurrent_explicit_resumes_append_one_revision(store):
    thread, experiment = paused(store)
    path = store._experiments_path(thread["thread_id"])
    before = path.read_bytes()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(store.experiment_resume, [experiment["experiment_id"]] * 2))
    assert all("Context selected" in result for result in results)
    after = path.read_bytes()
    assert after.startswith(before)
    assert len(after[len(before):].splitlines()) == 1
    assert store._read_thread(thread["thread_id"])["active_experiment_id"] == experiment["experiment_id"]


@pytest.mark.parametrize("choice", [
    "CREATE a poem about control and the shape of a pulse",
    "FORM a metaphor about amplitude",
    "ASPIRE then shift the story",
    "DAYDREAM then spread the idea",
    "EXPERIMENT_START Control :: Does amplitude alter the result?",
    "EXPERIMENT_BRANCH Pulse :: Which observation contradicts the hypothesis?",
    "EXPERIMENT_RESUME current",
    "EXPERIMENT_COMPARE current WITH retained",
])
def test_known_expressive_and_context_routes_treat_topics_as_data(store, choice):
    paused(store)
    before = snapshot(store.root)
    assert tx.ordinary_exploration(store, choice)
    assert store.charter_required_guard_assessment(choice) is None
    assert store.research_budget_guard_assessment(choice, STATE) is None
    assert snapshot(store.root) == before
    for actual in ("CONTROL_APPLY_LEASE actual", "RUN_PYTHON code", "PERTURB SPREAD", "UNKNOWN pulse"):
        assert not tx.ordinary_exploration(store, actual)


@pytest.mark.parametrize("base,route", [
    ("CREATE", "recess_aspiration"), ("FORM", "recess_aspiration"),
    ("DAYDREAM", "recess_daydream"), ("ASPIRE", "recess_aspiration"),
])
def test_actual_writing_selection_never_substitutes_a_research_guard(base, route):
    agent = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    agent.running = True
    agent._hard_recovery_reset = False
    agent._low_fill_guard_status = Mock(return_value={"active": False})
    agent._stable_core_action_allowed = Mock(return_value=(True, "synthetic healthy state"))
    agent._canonical_source_action = lambda action: action
    agent._log_decision = Mock()
    paused(agent._continuity_store())
    choice = f"{base} a thought about control and the shape of a pulse"
    agent._pending_next_action = choice
    agent._persist_pending_next_action(choice, reason="synthetic explicit choice")
    assert agent._decide_action(STATE) == route
    assert agent._pending_action_continuity_context["raw_next"] == choice
