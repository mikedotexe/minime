"""Synthetic real-method qualification; no providers or live state."""
from collections import Counter, deque
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy import choice_presentation as presentation
from minime_autonomy import maintenance_next


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "WORKSPACE_DIR", tmp_path)
    (tmp_path / "journal").mkdir()
    value = object.__new__(aa.AutonomousAgent)
    value.session_id = "synthetic-choice"
    value._pending_next_action = None
    value._recent_next_actions = deque(maxlen=16)
    value._last_state = {}
    value._llm_job_threads = []
    value._llm_job_worker_active = False
    value._attention_protected = Mock(return_value=False)
    value._query_llm = Mock(return_value="Synthetic accepted reflection.\nNEXT: REST")
    value._emit_next_hints = Mock(return_value="")
    value._apply_footer_directives = Mock()
    value._terminal_research_budget_status_stage_for_next = Mock(return_value=None)
    value._notice_attractor_body_consent = Mock()
    value._write_journal_entry = Mock()
    return value


def response_file(root, index=1):
    folder = root / "visual_responses"
    folder.mkdir(exist_ok=True)
    path = folder / f"response_{index}.json"
    raw = json.dumps({"response_timestamp": f"synthetic-{index}", "description": "Synthetic camera unavailable.",
                      "visual_available": False}).encode() + b"\r\n"
    path.write_bytes(raw)
    return path, raw


@pytest.mark.parametrize("choice", ["REST", "PASS", "WRITE CONTINUE", "SELF_STUDY CONTINUE"])
@pytest.mark.parametrize("disk_only", [False, True])
def test_visual_defers_exact_pending_choice_without_touching_source(agent, tmp_path, choice, disk_only):
    agent._record_llm_next_action_choice(choice, "", reason="test choice")
    state = Path(agent._sovereignty_state_path())
    before = state.read_bytes()
    if disk_only:
        agent._pending_next_action = None
    path, raw = response_file(tmp_path)
    agent._check_visual_responses()
    agent._query_llm.assert_not_called()
    assert path.read_bytes() == raw and state.read_bytes() == before
    assert not (path.parent / "processed").exists()


@pytest.mark.parametrize("barrier", ["job", "worker", "finalizer", "unadmitted", "rest", "focus", "shutdown", "recovery", "corrupt"])
def test_visual_respects_accepted_work_rest_and_fail_closed_state(agent, tmp_path, barrier):
    path, raw = response_file(tmp_path)
    if barrier == "job":
        agent._llm_job_store().submit(action_id=None, thread_id=None, action_text="JOURNAL",
                                      call_kind="journal", prompt="synthetic")
    elif barrier == "worker":
        agent._llm_job_worker_active = True
    elif barrier == "finalizer":
        agent._llm_job_threads = [Mock(is_alive=Mock(return_value=True))]
    elif barrier == "unadmitted":
        agent._unadmitted_next_checkpoint = {"pending": {"pending_next_action": "WRITE CONTINUE"}}
    elif barrier == "rest":
        agent._scheduler_observation = {"reason": "explicit_rest"}
    elif barrier == "focus":
        agent._attention_protected.return_value = True
    elif barrier == "shutdown":
        agent._shutdown_requested = True
    elif barrier == "recovery":
        agent._next_handoff_failed = True
    else:
        Path(agent._sovereignty_state_path()).write_text("not json")
    agent._check_visual_responses()
    agent._query_llm.assert_not_called()
    assert path.read_bytes() == raw


def test_visual_rechecks_after_prompt_preparation(agent, tmp_path, monkeypatch):
    path, raw = response_file(tmp_path)
    def prepare(*args, **kwargs):
        agent._record_llm_next_action_choice("WRITE CONTINUE", "", reason="test choice")
        return "Synthetic prepared observation"
    monkeypatch.setattr(aa, "visual_observation", prepare)
    agent._check_visual_responses()
    agent._query_llm.assert_not_called()
    assert path.read_bytes() == raw
    assert agent._pending_next_action == "WRITE CONTINUE"


def test_visual_runs_later_once_and_does_not_consume_second_source(agent, tmp_path):
    first, raw = response_file(tmp_path)
    second, raw2 = response_file(tmp_path, 2)
    agent._pending_next_action = "REST"
    agent._check_visual_responses()
    agent._query_llm.assert_not_called()
    agent._pending_next_action = None  # Simulate a later cycle after explicit REST.
    agent._check_visual_responses()
    agent._query_llm.assert_called_once()
    assert (first.parent / "processed" / first.name).read_bytes() == raw
    assert second.read_bytes() == raw2
    assert agent._pending_next_action == "REST"
    saved = json.loads(Path(agent._sovereignty_state_path()).read_bytes())
    assert saved["pending_next_action"] == "REST"
    assert saved["choice_envelope_v1"]["visual_response_choice_id"]
    agent._check_visual_responses()
    agent._query_llm.assert_called_once()


def test_choice_arriving_during_accepted_visual_generation_wins(agent, tmp_path):
    path, raw = response_file(tmp_path)
    saved = []
    def provider(*args, **kwargs):
        agent._record_llm_next_action_choice("WRITE CONTINUE", "", reason="test choice")
        saved.append(Path(agent._sovereignty_state_path()).read_bytes())
        return "Synthetic accepted visual reflection.\nNEXT: REST"
    agent._query_llm.side_effect = provider
    agent._check_visual_responses()
    assert agent._pending_next_action == "WRITE CONTINUE"
    assert Path(agent._sovereignty_state_path()).read_bytes() == saved[0]
    assert (path.parent / "processed" / path.name).read_bytes() == raw
    assert "NEXT: REST" in next((tmp_path / "journal").glob("visual_experience_*")).read_text()


@pytest.mark.parametrize("concurrent", ["WRITE CONTINUE", "REST"])
def test_existing_writer_linearizes_visual_queue_without_overwriting_even_same_command(agent, concurrent):
    original = agent._persist_pending_next_action
    snapshots = []
    def competing_write(action, **kwargs):
        if kwargs.get("only_if_unqueued"):
            original(concurrent, reason="concurrent explicit choice", only_if_unqueued=True,
                     queue_envelope={"source": "synthetic competing choice"})
            snapshots.append(Path(agent._sovereignty_state_path()).read_bytes())
        return original(action, **kwargs)
    agent._persist_pending_next_action = competing_write
    result = agent._record_llm_next_action_choice("REST", "", reason="visual", preserve_pending_choice=True)
    assert result is None
    assert agent._pending_next_action == concurrent
    assert Path(agent._sovereignty_state_path()).read_bytes() == snapshots[0]
    assert not agent._recent_next_actions


@pytest.mark.parametrize("base", ["SHADOW_TRAJECTORY", "EXPERIMENT_RESEARCH_BUDGET_STATUS"])
def test_read_only_repetition_reaches_real_next_parser_and_queue(agent, monkeypatch, base):
    agent._recent_next_actions.extend([base] * 8)
    agent._recent_journal_kind_mix = Mock(return_value=Counter(moment=14))
    agent._latest_operational_tail_artifact_mtime = Mock(return_value=0.0)
    assert agent._operational_tail_cooldown_available(f"{base} same-target") is False
    # Independently pin the consumer, even if an old cooldown implementation is supplied.
    monkeypatch.setattr(agent, "_operational_tail_cooldown_available", Mock(return_value=True))
    response = f"Synthetic chosen inspection.\nNEXT: {base} same-target"
    agent._query_llm.return_value = response
    result, choice = agent._query_llm_with_next("Synthetic ordinary reflection")
    assert result == response and choice == f"{base} same-target"
    assert agent._pending_next_action == choice
    agent._operational_tail_cooldown_available.assert_not_called()
    assert not presentation.read_only_editorial_exempt("PERTURB same-target")
    assert presentation.read_only_editorial_exempt("shadow_trajectory: same-target")


def invitation(agent, body="Synthetic question?", filename="mike_query_fixture.txt"):
    agent._record_open_steward_query(filename, "Subject: Synthetic invitation\nREVIEW TARGET: synthetic.rs\n" + body)


def test_invitation_once_per_material_revision_across_restart_and_rename(agent, tmp_path):
    invitation(agent)
    first = agent._open_steward_query_line()
    assert "STEWARD_INVITATION STATUS" in first and "not a task" in first
    assert agent._open_steward_query_line() == ""
    restarted = presentation.StewardInvitations(tmp_path)
    assert restarted.offer() == ""
    invitation(agent, filename="mike_query_renamed.txt")
    assert restarted.offer() == ""
    invitation(agent, body="A materially different synthetic question?")
    assert restarted.offer()
    assert restarted.offer() == ""
    stored = (tmp_path / "steward_invitation_presentations_v1.json").read_text()
    assert "Synthetic" not in stored and "synthetic.rs" not in stored
    agent._query_llm.assert_not_called()


@pytest.mark.parametrize("command", ["DEFER", "DECLINE"])
def test_explicit_invitation_controls_preserve_source_and_never_generate(agent, tmp_path, command):
    invitation(agent)
    source = tmp_path / "open_steward_query.json"
    before = source.read_bytes()
    result = agent._steward_invitation_action("STEWARD_INVITATION " + command)
    assert result["status"] == {"DEFER": "deferred", "DECLINE": "declined"}[command]
    assert result["generation_requested"] is False
    assert agent._open_steward_query_line() == ""
    status = agent._steward_invitation_action("STEWARD_INVITATION STATUS")
    assert status == result
    assert source.read_bytes() == before
    assert agent._pending_next_action is None
    agent._query_llm.assert_not_called()


@pytest.mark.parametrize("failure", ["corrupt", "empty", "symlink", "full"])
def test_unverifiable_or_full_invitation_history_never_replays(agent, tmp_path, failure):
    invitation(agent)
    path = tmp_path / "steward_invitation_presentations_v1.json"
    if failure == "corrupt":
        path.write_text("bad json")
    elif failure == "empty":
        path.write_text("{}")
    elif failure == "symlink":
        target = tmp_path / "foreign.json"
        target.write_text("{}")
        path.symlink_to(target)
    else:
        maintenance_next.write_state(path, {"schema": "steward_invitation_presentations_v1",
            "revisions": {f"{i:064x}": "presented" for i in range(presentation.StewardInvitations.MAX_REVISIONS)}})
    before = path.read_bytes()
    assert agent._open_steward_query_line() == ""
    assert path.read_bytes() == before


def test_expiry_is_quiet_but_keeps_explicit_retrieval(agent, tmp_path):
    invitation(agent)
    store = presentation.StewardInvitations(tmp_path, clock=lambda: aa.time.time() + 49 * 3600)
    assert store.offer() == ""
    assert store.command("STEWARD_INVITATION STATUS")["invitation"]
    with pytest.raises(ValueError, match="use STEWARD_INVITATION"):
        store.command("STEWARD_INVITATION DECLINE AND WRITE CONTINUE")


@pytest.mark.parametrize("failure_site", ["file", "journal_entry"])
def test_admitted_visual_write_failure_still_blocks_drain(agent, tmp_path, monkeypatch, failure_site):
    path, raw = response_file(tmp_path)
    agent._agent_boot_id = "synthetic-identity"
    # Admission starts with an empty queue. Shutdown and a new explicit choice
    # arrive inside the accepted call, not before the visual admission check.
    def accepted(*args, **kwargs):
        agent._shutdown_requested = True
        agent._pending_next_action = "REST"
        return "Synthetic accepted visual response.", "REST"
    agent._query_llm_with_next = Mock(side_effect=accepted)
    if failure_site == "file":
        monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("synthetic write failure")))
    else:
        agent._write_journal_entry.side_effect = OSError("synthetic write failure")
    agent._check_visual_responses()
    agent._query_llm_with_next.assert_called_once()
    assert agent._next_handoff_failed is True
    assert agent._pending_next_action == "REST"
    assert path.read_bytes() == raw
    assert not (path.parent / "processed").exists()
    agent._check_visual_responses()
    agent._query_llm_with_next.assert_called_once()


@pytest.fixture
def dispatch_agent(monkeypatch):
    value = aa.AutonomousAgent(1, check_interval=999, recess_mode=True)
    value.running = True
    value._hard_recovery_reset = False
    value._low_fill_guard_status = Mock(return_value={"active": False})
    value._stable_core_action_allowed = Mock(return_value=(True, "synthetic healthy gate"))
    for name in ("_query_llm", "_query_llm_raw", "_queue_llm_action_job"):
        setattr(value, name, Mock(side_effect=AssertionError("metadata route must not generate")))
    value._log_decision = Mock()
    monkeypatch.setattr(aa.websocket, "create_connection", Mock(side_effect=AssertionError("no controls")))
    monkeypatch.setattr(aa.requests, "post", Mock(side_effect=AssertionError("no providers")))
    return value


@pytest.mark.parametrize("command", ["STATUS", "DEFER", "DECLINE"])
def test_invitation_preflight_dispatch_and_restart_are_metadata_only(dispatch_agent, command):
    agent = dispatch_agent
    state = {"fill_ratio": .68, "eig1": 4.7, "spread": 3.0}
    invitation(agent)
    root = aa.WORKSPACE_DIR
    slot = root / "open_steward_query.json"
    original = slot.read_bytes()
    letter = root / "inbox/mike_query_fixture.txt"
    letter.parent.mkdir(exist_ok=True)
    letter.write_bytes(b"Synthetic retained letter.\r\n")
    text = "STEWARD_INVITATION " + command
    # Exercise the actual parser, not only a handler called out of band.
    parsed, _ = aa.parse_next_action("Synthetic choice.\nNEXT: " + text)
    assert parsed == text
    receipts = root / "steward_invitation_presentations_v1.json"
    report = aa.ActionPreflightStore(agent).report("ACTION_PREFLIGHT " + text, state)
    assert report["effective_route"] == "steward_invitation"
    assert report["stage"] == "language_only" and report["visibility"] == "protected_summary"
    assert "No generation" in report["expected_continuity_effect"]
    assert not receipts.exists()  # A dry run cannot present or defer the invitation.
    focus = Mock()
    agent._activity_checkpoint_exists = Mock(return_value=True)
    agent._activity_focus = Mock(return_value=focus)
    agent._pending_next_action = text
    agent._persist_pending_next_action(text, reason="synthetic explicit choice")
    route = agent._decide_action(state)
    assert route == report["effective_route"]
    agent._execute_action(route, state)
    result = json.loads(agent._pending_activity_feedback)
    assert result["status"] == {"STATUS": "unpresented", "DEFER": "deferred", "DECLINE": "declined"}[command]
    assert result["generation_requested"] is False
    assert agent._last_action_continuity_event["status"] == "handled"
    focus.release_for_choice.assert_not_called()
    assert "steward_invitation" not in agent.LLM_JOB_ACTIONS
    agent._query_llm.assert_not_called()
    agent._query_llm_raw.assert_not_called()
    agent._queue_llm_action_job.assert_not_called()
    assert slot.read_bytes() == original and letter.read_bytes() == b"Synthetic retained letter.\r\n"
    assert not list((root / "outbox").rglob("*.txt"))
    assert not list((root / "journal").rglob("*.txt"))
    assert not agent._pending_next_action
    # Retrieval does not rearm an ambient offer; disposition survives restart.
    if command == "STATUS":
        assert agent._open_steward_query_line()
    assert presentation.StewardInvitations(root).offer() == ""
    if command != "STATUS":
        receipt = json.loads(receipts.read_bytes())
        assert receipt["revisions"] == {result["revision"]: result["status"]}
    agent._pending_next_action = "REST"
    agent._persist_pending_next_action("REST", reason="synthetic rest after metadata")
    before = Path(agent._sovereignty_state_path()).read_bytes()
    maintenance_next.seal(agent)
    restarted = aa.AutonomousAgent(2, check_interval=999, recess_mode=True)
    maintenance_next.restore(restarted)
    restarted._restore_sovereignty_state()
    assert restarted._pending_next_action == "REST"
    assert restarted._open_steward_query_line() == ""
    assert Path(restarted._sovereignty_state_path()).read_bytes() == before
    restarted._hard_recovery_reset = False
    restarted._low_fill_guard_status = agent._low_fill_guard_status
    assert restarted._decide_action(state) is None
    assert restarted._scheduler_observation["reason"] == "explicit_rest"
    source, raw = response_file(root)
    restarted._query_llm = Mock(side_effect=AssertionError("REST must not admit visual generation"))
    restarted._check_visual_responses()
    assert source.read_bytes() == raw


@pytest.mark.parametrize("text", ["STEWARD_INVITATION", "STEWARD_INVITATION SEND", "STEWARD_INVITATION DEFER extra"])
def test_invalid_invitation_stays_non_generating_and_preflight_is_truthful(dispatch_agent, text):
    agent = dispatch_agent
    invitation(agent)
    report = aa.ActionPreflightStore(agent).report(text, {})
    assert report["stage"] == "blocked"
    assert report["stable_core_gate"]["allowed"] is False
    agent._pending_next_action = text
    agent._persist_pending_next_action(text, reason="synthetic invalid metadata choice")
    route = agent._decide_action({})
    assert route == "steward_invitation"
    agent._execute_action(route, {})
    assert agent._last_action_continuity_event["status"] == "failed"
    assert not (aa.WORKSPACE_DIR / "steward_invitation_presentations_v1.json").exists()
    agent._query_llm.assert_not_called()
    agent._queue_llm_action_job.assert_not_called()


def test_invitation_dispatch_retains_existing_stage_and_health_refusal(dispatch_agent):
    agent = dispatch_agent
    invitation(agent)
    agent._stable_core_action_allowed.return_value = (False, "synthetic health refusal")
    command = "STEWARD_INVITATION DECLINE"
    assert not aa.ActionPreflightStore(agent).report(command, {})["stable_core_gate"]["allowed"]
    agent._pending_next_action = command
    agent._persist_pending_next_action(command, reason="synthetic metadata choice")
    agent._execute_action(agent._decide_action({}), {})
    assert agent._last_action_continuity_event["status"] == "blocked"
    assert not (aa.WORKSPACE_DIR / "steward_invitation_presentations_v1.json").exists()
    agent._query_llm.assert_not_called()


def test_choice_helper_is_bound_by_native_source_inventory(tmp_path):
    from minime_autonomy.deployment import source_inputs
    path = tmp_path / "minime_autonomy/choice_presentation.py"
    path.parent.mkdir()
    path.write_bytes(b"# synthetic helper\n")
    assert "minime_autonomy/choice_presentation.py" in source_inputs(tmp_path)


def test_invitation_metadata_classification_and_stage_registration(dispatch_agent):
    agent = dispatch_agent
    assert aa.ActionContinuityStore.stage_for_action("STEWARD_INVITATION", "steward_invitation") == "language_only"
    assert aa.ActionContinuityStore.visibility_for_action("STEWARD_INVITATION", "steward_invitation") == "protected_summary"
    assert "steward_invitation" in aa.STABLE_CORE_SELF_JOURNAL_ACTIONS
    agent._stable_core_health_budget_allows = Mock(return_value=(True, "synthetic fresh health"))
    for stage in aa.STABLE_CORE_STAGE_ACTIONS:
        agent._stable_core_agency_budget = Mock(return_value={"active": True, "stage": stage})
        allowed, _ = aa.AutonomousAgent._stable_core_action_allowed(agent, "steward_invitation", {})
        assert allowed == ("mailbox_status" in aa.STABLE_CORE_STAGE_ACTIONS[stage])
    agent._stable_core_agency_budget.return_value = {"active": True, "stage": "self_journal"}
    agent._stable_core_health_budget_allows.return_value = (False, "synthetic health refusal")
    assert not aa.AutonomousAgent._stable_core_action_allowed(agent, "steward_invitation", {})[0]
