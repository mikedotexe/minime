"""Un-muffle guards shipped 2026-10-01 for the longer-entries plan (steps 2-3).

No live model, runtime or journal mutation: synthetic prompts, temporary workspaces.
"""
from pathlib import Path
from unittest.mock import Mock, patch

import autonomous_agent as aa
from minime_autonomy.parsing import parse_next_action
from minime_autonomy.source_study import SourceStudyPrompt


def _study_prompt(input_kind="source_page", receipt=None):
    prompt = Mock(spec=SourceStudyPrompt)
    prompt.output = {"input_kind": input_kind, "navigation_id": "nav-1",
                     "page": {"source": "astrid/crates/astrid-kernel/src/lib.rs"} if input_kind == "source_page" else None}
    prompt.receipt = receipt
    prompt.diagnostic_summary = None
    return prompt


def test_write_underscore_aliases_reach_the_write_verb_and_file_action_is_untouched():
    assert parse_next_action("Prose.\nNEXT: WRITE_CONTINUE")[0] == "WRITE CONTINUE"
    assert parse_next_action("Prose.\nNEXT: write_continue")[0] == "WRITE CONTINUE"
    assert parse_next_action("Prose.\nNEXT: WRITE_START The architecture of the threshold")[0] == "WRITE START The architecture of the threshold"
    assert parse_next_action("Prose.\nNEXT: WRITE_PROFILE EXTENDED")[0] == "WRITE PROFILE EXTENDED"
    assert parse_next_action("Prose.\nNEXT: WRITE_FILE notes/a.txt FROM_SELF")[0] == "WRITE_FILE notes/a.txt FROM_SELF"
    assert parse_next_action("Prose.\nNEXT: WRITE_SOMETHING_ELSE")[0] == "WRITE_SOMETHING_ELSE"
    # Her authored line is unchanged in the cleaned text's provenance: only the action is normalized.
    assert parse_next_action("Prose.\nNEXT: WRITE_CONTINUE")[1] == "Prose."


def test_fallback_stub_is_never_filed_as_a_study_and_is_retained_for_the_notice():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    prompt = _study_prompt()
    prompt.clean_content.return_value = "CONTINUE"
    with patch.object(aa, "_llm_backend_attempts", return_value=["ollama", "ollama_fast"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.job_timing, "correlate_generation"), \
         patch.object(agent, "_query_ollama", return_value=""), \
         patch.object(agent, "_query_ollama_fast_fallback", return_value="CONTINUE"), \
         patch.object(agent, "_strip_model_artifacts", side_effect=lambda t: t):
        assert agent._query_llm_raw(prompt, "system", 2048, journal=True, prompt_class="source_study") is None
    prompt.accepted.assert_not_called()
    stub = agent._take_fallback_stub()
    assert isinstance(stub, aa.FallbackStubDelivery)
    assert stub.text == "CONTINUE" and stub.backend == "ollama_fast"
    assert "CONTINUE" not in str(stub)  # the public summary never carries the stub text
    assert agent._take_fallback_stub() is None


def test_primary_model_output_is_never_treated_as_a_stub():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    prompt = _study_prompt()
    prompt.clean_content.return_value = "Okay"
    with patch.object(aa, "_llm_backend_attempts", return_value=["ollama"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.job_timing, "correlate_generation"), \
         patch.object(agent, "_query_ollama", return_value="Okay"), \
         patch.object(agent, "_strip_model_artifacts", side_effect=lambda t: t):
        assert agent._query_llm_raw(prompt, "system", 2048, journal=True, prompt_class="source_study") == "Okay"
    prompt.accepted.assert_called_once()


def test_rejected_delivery_is_retained_verbatim_without_advancing_the_bookmark(tmp_path):
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    agent._record_current_action_artifact = Mock()
    prompt = _study_prompt()
    prompt.clean_content.return_value = "A long study that hit the ceiling..."
    prompt.accepted.side_effect = RuntimeError("provider did not retain a completed generation; bookmark unchanged")
    with patch.object(aa, "WORKSPACE_DIR", tmp_path), \
         patch.object(aa, "_llm_backend_attempts", return_value=["ollama"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.job_timing, "correlate_generation"), \
         patch.object(agent, "_query_ollama", return_value="A long study that hit the ceiling..."), \
         patch.object(agent, "_strip_model_artifacts", side_effect=lambda t: t):
        assert agent._query_llm_raw(prompt, "system", 2048, journal=True, prompt_class="source_study") is None
    notices = list((tmp_path / "diagnostics/source_study/notices").glob("incomplete_*.txt"))
    assert len(notices) == 1
    text = notices[0].read_text()
    assert "A long study that hit the ceiling..." in text
    assert "bookmark unchanged" in text and "SELF_STUDY CONTINUE" in text
    kind = agent._record_current_action_artifact.call_args.args[0]
    assert kind == "source_study_incomplete"
    # Private drafts are retained inside her private writing directory, never in public diagnostics.
    private = _study_prompt(input_kind="private_writing")
    with patch.object(aa, "WORKSPACE_DIR", tmp_path):
        agent._retain_incomplete_delivery(private, "Private passage.", "finish length; bookmark unchanged", "ollama")
    private_notices = list((tmp_path / "private_writing/journal").glob("notice_*.txt"))
    assert len(private_notices) == 1 and "Private passage." in private_notices[0].read_text()
    assert len(list((tmp_path / "diagnostics/source_study/notices").glob("*.txt"))) == 1


def test_bare_continue_in_a_public_study_turn_means_the_bookmark():
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    agent._emit_next_hints = Mock(return_value="")
    agent._apply_footer_directives = Mock()
    agent._terminal_research_budget_status_stage_for_next = Mock(return_value=None)
    agent._experiment_resume_loop_note_for_llm_next = Mock(return_value=None)
    agent._operational_tail_cooldown_available = Mock(return_value=False)
    agent._record_llm_next_action_choice = Mock(side_effect=lambda next_action, cleaned, **kw: next_action)
    for kind, expected in [("source_page", "SELF_STUDY CONTINUE"), ("map", "SELF_STUDY CONTINUE"),
                           ("reflection", "CONTINUE")]:
        prompt = _study_prompt(input_kind=kind)
        agent._query_llm = Mock(return_value="Her prose.\nNEXT: CONTINUE")
        with patch.object(aa, "delivery_origin", return_value=None):
            response, next_action = agent._query_llm_with_next(prompt, context_mode="source_study")
        assert response == "Her prose.\nNEXT: CONTINUE"
        assert next_action == expected, kind
        if expected == "SELF_STUDY CONTINUE":
            envelope = agent._record_llm_next_action_choice.call_args.kwargs["choice_envelope"]
            assert envelope["study_continue_normalization"]["authored_next"] == "CONTINUE"
            assert envelope["executable_next"] == "SELF_STUDY CONTINUE"


def test_navigation_kinds_file_under_their_own_heading():
    assert {"map", "recovery", "questions", "help", "search"} <= set(aa.STUDY_NAVIGATION_KINDS)
    assert "source_page" not in aa.STUDY_NAVIGATION_KINDS
    assert "end_of_file" not in aa.STUDY_NAVIGATION_KINDS  # already a study decision


def test_recess_prompts_no_longer_ask_for_a_sentence_count():
    source = Path(aa.__file__).read_text()
    for stale in ("(1-2 sentences)", "(3-5 sentences)", "(2-4 sentences)"):
        assert stale not in source, stale


def test_write_underscore_alias_normalizes_before_payload_classification():
    payload = '{"owner":"minime","draft":"d1","present":true,"operation":{"kind":"status"},"note":"Does exploration_noise explain this?"}'
    exact = parse_next_action("Prose.\nNEXT: WRITE OBSERVE " + payload)
    spelled = parse_next_action("Prose.\nNEXT: WRITE_OBSERVE " + payload)
    assert spelled == exact
    assert spelled[0] == "WRITE OBSERVE " + payload
    # Authored text inside a WRITE sub-command never reroutes the turn, in either spelling.
    for verb in ("WRITE STOPPING_POINT", "WRITE_STOPPING_POINT"):
        action = parse_next_action(f"Prose.\nNEXT: {verb} keep_floor and exploration_noise feel related")[0]
        assert action == "WRITE STOPPING_POINT keep_floor and exploration_noise feel related", action
    assert parse_next_action("Prose.\nNEXT: **WRITE_CONTINUE**")[0] == "WRITE CONTINUE"
    assert parse_next_action("Prose.\nNEXT: WRITE_CONTINUE2")[0] == "WRITE_CONTINUE2"


def test_action_footer_does_not_rescue_a_fallback_stub():
    assert aa._is_degenerate_self_study_response("Obs\nNEXT: SELF_STUDY CONTINUE")
    assert aa._is_degenerate_self_study_response("Obs\nSELF_STUDY CONTINUE")
    assert aa._is_degenerate_self_study_response("NEXT: WRITE CONTINUE")
    assert not aa._is_degenerate_self_study_response(
        "The regulator clamps keep_bias before the covariance update, which explains the plateau.\nNEXT: SELF_STUDY CONTINUE")
    # The original response is classified, never altered.
    agent = aa.AutonomousAgent.__new__(aa.AutonomousAgent)
    prompt = _study_prompt()
    prompt.clean_content.return_value = "Obs\nNEXT: SELF_STUDY CONTINUE"
    with patch.object(aa, "_llm_backend_attempts", return_value=["ollama", "ollama_fast"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.job_timing, "correlate_generation"), \
         patch.object(agent, "_query_ollama", return_value=""), \
         patch.object(agent, "_query_ollama_fast_fallback", return_value="Obs\nNEXT: SELF_STUDY CONTINUE"), \
         patch.object(agent, "_strip_model_artifacts", side_effect=lambda t: t):
        assert agent._query_llm_raw(prompt, "system", 2048, journal=True, prompt_class="source_study") is None
    prompt.accepted.assert_not_called()
    assert agent._take_fallback_stub().text == "Obs\nNEXT: SELF_STUDY CONTINUE"
    # A bare NEXT is a complete answer to a navigation input: the guard applies only where prose is expected.
    navigation = _study_prompt(input_kind="map")
    navigation.clean_content.return_value = "NEXT: SELF_STUDY OPEN astrid/crates/astrid-kernel/src/lib.rs 1"
    with patch.object(aa, "_llm_backend_attempts", return_value=["ollama_fast"]), \
         patch.object(aa.generation_record, "begin", return_value=None), \
         patch.object(aa.generation_record, "record_attempt"), \
         patch.object(aa.job_timing, "correlate_generation"), \
         patch.object(agent, "_query_ollama_fast_fallback", return_value="NEXT: SELF_STUDY OPEN astrid/crates/astrid-kernel/src/lib.rs 1"), \
         patch.object(agent, "_strip_model_artifacts", side_effect=lambda t: t):
        assert agent._query_llm_raw(navigation, "system", 2048, journal=True, prompt_class="source_study")
    navigation.accepted.assert_called_once()
