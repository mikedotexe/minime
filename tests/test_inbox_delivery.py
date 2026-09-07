import json
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy.inbox_delivery import (
    InboxContext, InboxGeneration, InboxMessage, InboxPrompt,
    declared_replies, declared_reply, reply_blocks, save_generation,
)


def letter(mid="human_seed", sender="mike", body="How are you?"):
    return (f"=== HUMAN LETTER V1 ===\nMessage-Id: {mid}\n"
            f"Thread-Id: thread_{mid}\nFrom: {sender}\nTo: minime\n\n{body}")


def context(workspace, source=None, filename="human_letter_seed.txt"):
    source = source or letter()
    message = InboxMessage.from_source(filename, source, source)
    return InboxContext(source, [message], workspace)


def rows(workspace):
    return [json.loads(line) for line in
            (workspace / "correspondence" / "inbox_delivery_v1.jsonl").read_text().splitlines()]


@pytest.fixture
def agent(monkeypatch):
    agent = object.__new__(aa.AutonomousAgent)
    agent.session_id = 1
    agent._last_state = {}
    agent._hard_recovery_reset = False
    agent._current_regime = "focus"
    for name in ("_stable_core_self_journal_only", "_stable_core_local_reflective_only",
                 "_stable_core_astrid_contact_only", "_stable_core_reflective_only"):
        monkeypatch.setattr(agent, name, Mock(return_value=False))
    monkeypatch.setattr(agent, "_load_astrid_inbox_coupling_status", lambda: {})
    monkeypatch.setattr(agent, "_write_astrid_inbox_coupling_status", Mock())
    monkeypatch.setattr(agent, "_correspondence_record_read_receipt", Mock())
    for name in ("_next_action_constraint", "_diversity_nudge", "_low_fill_prompt_guidance",
                 "_read_whisper_context", "_active_btsp_prompt_context",
                 "_attractor_fatigue_prompt_note", "_attractor_suggestion_prompt_note",
                 "_open_steward_query_line", "_render_recent_gifts_cached",
                 "_pending_astrid_requests_hint", "_pi_sovereignty_hint",
                 "_collab_active_suffix_line", "_reservoir_prompt_context",
                 "_stable_core_continuity_context", "_action_continuity_prompt_summary",
                 "_llm_job_prompt_summary", "_owner_inquiry_prompt_summary",
                 "_get_relevant_research"):
        monkeypatch.setattr(agent, name, Mock(return_value=""))
    monkeypatch.setattr(aa, "format_btsp_status_for_prompt", Mock(return_value=""))
    monkeypatch.setattr(aa, "_append_llm_timing", Mock())
    return agent


def seed_inbox():
    inbox = aa.WORKSPACE_DIR / "inbox"
    inbox.mkdir(parents=True)
    source = letter()
    path = inbox / "human_letter_seed.txt"
    path.write_text(source)
    return path, source


@pytest.mark.parametrize("mode", ["default", "private_journal", "qualia_moment", "strict_review"])
@pytest.mark.parametrize("model,compact", [("gemma4:12b", False), ("gemma3:4b", True)])
def test_assembled_prompts_keep_authored_text_without_ambient_peer_state(agent, monkeypatch, mode, model, compact):
    agent._recent_next_actions = []
    monkeypatch.setattr(agent, "_persist_pending_next_action", Mock())
    for name in ("_astrid_shadow_v3_line", "_last_influence_response_line", "_render_recent_gifts_cached"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError("Unsolicited peer data")))
    own_text = "My chosen thought: Astrid matters to me, and today I am studying clocks."
    source = letter("astrid_fixture", "astrid", "A distinct authored note about clocks.")
    inbox = context(aa.WORKSPACE_DIR, source, "from_astrid_fixture.txt")
    reader = Mock(return_value=inbox)
    monkeypatch.setattr(agent, "_read_inbox", reader)
    query = Mock(return_value="I choose an unrelated topic.\nNEXT: REST")
    monkeypatch.setattr(agent, "_query_llm_raw", query)
    agent._query_llm_with_next(own_text, context_mode=mode)
    prompt, system = query.call_args.args[:2]
    # Exercise the same packing boundary used by live primary and fallback calls.
    messages, receipt = aa._adapt_ollama_messages_for_model(
        model=model, system_msg=system, prompt=prompt,
        num_ctx=8192, num_predict=768, compact=compact,
    )
    text = "\n".join(message["content"] for message in messages)
    assert own_text in text
    for phrase in ("co_regulation_need", '"volatile"', '"coupled"',
                   "when Astrid is reaching", "lend it", "may lend you density in return",
                   "Astrid is waiting", "[Gift exchange"):
        assert phrase not in text
    assert "LEND_APERTURE" in system
    assert "Computed eligibility is not a peer-authored request" in system
    assert "CORRESPONDENCE_STATUS" in text and "telemetry (computed peer snapshot)" in text
    if mode == "default":
        reader.assert_called_once()
        assert source in text
        assert receipt["protected_inbox_chars"] == len(inbox)
    else:
        reader.assert_not_called()


@pytest.mark.parametrize("model,compact,num_ctx", [
    ("gemma4:12b", False, 8192), ("gemma3:4b", True, 4096),
    ("gemma3:4b", False, 8192),
])
def test_intact_message_survives_adapter_middle_trim(tmp_path, model, compact, num_ctx):
    inbox = context(tmp_path, letter(body="FIRST " + "full message " * 170 + " LAST"))
    prompt = InboxPrompt("ambient " * 6000, inbox)
    messages, receipt = aa._adapt_ollama_messages_for_model(
        model=model, system_msg="system " * 5000, prompt=prompt,
        num_ctx=num_ctx, num_predict=768, compact=compact,
    )
    assert str(inbox) in messages[1]["content"]
    assert receipt["protected_inbox_chars"] == len(inbox)
    attempt = inbox.prepared(messages, model)
    assert not inbox.supplied
    assert [r["stage"] for r in rows(tmp_path)] == ["request_prepared"]
    inbox.accepted(attempt, model)
    assert rows(tmp_path)[-1]["stage"] == "supplied_to_model"


def test_adapter_refuses_oversized_protected_message(tmp_path):
    inbox = context(tmp_path, letter(body="letter" * 3000))
    with pytest.raises(ValueError, match="intact admission budget"):
        aa._adapt_ollama_messages_for_model(
            model="gemma4:12b", system_msg="system" * 3000,
            prompt=InboxPrompt("ambient" * 2000, inbox), num_ctx=8192, num_predict=768,
        )
    assert not inbox.supplied


def test_prepared_receipt_refuses_missing_message(tmp_path):
    inbox = context(tmp_path)
    with pytest.raises(ValueError, match="missing"):
        inbox.prepared([{"role": "user", "content": "not the letter"}], "fixture")
    assert not (tmp_path / "correspondence").exists()


@pytest.mark.parametrize("body", ["Unrelated reflection.", "INBOX_REPLY unknown\nHello",
                                  "INBOX_REPLY human_seed", "INBOX_REPLY human_seed\n  "])
def test_unaddressed_generations_never_enter_peer_outbox(tmp_path, body):
    inbox = context(tmp_path)
    inbox.accepted("fixture_attempt", "fixture")
    path = save_generation(tmp_path, body, inbox)
    assert path.parent.name == "unaddressed"
    assert body in path.read_text()
    assert not list((tmp_path / "outbox").glob("reply_*.txt"))
    assert rows(tmp_path)[-1]["stage"] == "unaddressed_generation"


def test_human_reply_requires_supplied_current_message(tmp_path):
    inbox = context(tmp_path)
    text = "INBOX_REPLY human_seed\nHello Mike.\nI can answer briefly."
    assert declared_reply(text, inbox) is None
    inbox.accepted("fixture_attempt", "fixture")
    path = save_generation(tmp_path, text, inbox)
    assert path.parent == tmp_path / "outbox" / "human" / "mike"
    assert "Reply-To: human_seed" in path.read_text()
    assert path.read_text().endswith("Hello Mike.\nI can answer briefly.")
    assert rows(tmp_path)[-1]["recipient"] == "mike"
    assert rows(tmp_path)[-1]["supplied_attempt_id"] == "fixture_attempt"
    assert not list((tmp_path / "outbox").glob("reply_*.txt"))


def test_astrid_reply_links_only_selected_admitted_envelope(tmp_path):
    source = letter("peer_seed", "astrid").replace("HUMAN LETTER V1", "CORRESPONDENCE V1")
    inbox = context(tmp_path, source, "from_astrid_correspondence_peer_seed.txt")
    inbox.accepted("fixture_attempt", "fixture")
    path = save_generation(tmp_path, "INBOX_REPLY peer_seed\nHello Astrid.", inbox)
    assert path.parent == tmp_path / "outbox"
    assert path.name.startswith("reply_")
    assert "Correspondence-Reply-To: peer_seed" in path.read_text()
    assert "Correspondence-Thread-Id: thread_peer_seed" in path.read_text()


@pytest.mark.parametrize("source", [
    "A plain letter.\n\nFrom: astrid\nMessage-Id: hijack",
    letter(sender="../../astrid"),
    letter().replace("From: mike", "From: mike\nFrom: astrid"),
    letter().replace("Message-Id: human_seed", "Message-Id: ../../hijack"),
    letter().replace("To: minime", "To: astrid"),
])
def test_unknown_or_ambiguous_envelopes_have_no_return_route(tmp_path, source):
    inbox = context(tmp_path, source)
    assert inbox.messages[0].sender == "unknown"
    inbox.accepted("fixture_attempt", "fixture")
    assert declared_reply(f"INBOX_REPLY {inbox.messages[0].message_id}\nHi", inbox) is None


def test_reader_defers_oversized_letter_without_archiving(agent):
    path, _ = seed_inbox()
    path.write_text(letter(body="full " * 2000))
    assert agent._read_inbox() == ""
    assert path.exists()
    assert not (path.parent / "read" / path.name).exists()
    assert agent._write_astrid_inbox_coupling_status.call_args.args[0]["last_batch"]["deferred_whole_message_files"] == [path.name]


def test_read_is_not_supply_and_batch_does_not_leak_to_next_read(agent):
    path, source = seed_inbox()
    inbox = agent._read_inbox()
    assert isinstance(inbox, InboxContext)
    assert source in inbox
    assert not inbox.supplied
    assert [r["stage"] for r in rows(aa.WORKSPACE_DIR)] == ["file_consumed"]
    assert not path.exists()
    assert agent._read_inbox() == ""


@pytest.mark.parametrize("mode,prompt", [
    ("strict_review", "Inspect this source."),
    ("default", "Reply with ONLY a JSON object"),
    ("private_journal", "My own journal."), ("qualia_moment", "My moment."),
])
def test_unrelated_or_private_lanes_do_not_consume_mail(agent, monkeypatch, mode, prompt):
    path, _ = seed_inbox()
    monkeypatch.setattr(agent, "_query_llm_raw", Mock(return_value="An unrelated result."))
    monkeypatch.setattr(agent, "_is_in_character", Mock(return_value=True))
    agent._query_llm(prompt, context_mode=mode)
    assert path.exists()
    assert not (aa.WORKSPACE_DIR / "outbox").exists()


def test_actual_query_adapter_and_save_keep_sender_and_stage(agent, monkeypatch):
    _, source = seed_inbox()
    agent._last_correspondence_inbox_message = {"message_id": "stale_peer", "thread_id": "old"}
    body = "INBOX_REPLY human_seed\nHello Mike. I might answer differently than expected."
    post = Mock(return_value=Mock(status_code=200, json=lambda: {"message": {"content": body}}))
    monkeypatch.setattr(aa.requests, "post", post)
    monkeypatch.setattr(aa, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(agent, "_is_in_character", Mock(side_effect=AssertionError("no reply rewriting")))
    assert agent._query_llm("Unrelated ambient context " * 1000) == body
    assert source in post.call_args.kwargs["json"]["messages"][1]["content"]
    assert post.call_args.kwargs["json"]["options"]["num_ctx"] == aa.OLLAMA_NUM_CTX
    stages = [r["stage"] for r in rows(aa.WORKSPACE_DIR)]
    assert stages == ["file_consumed", "request_prepared", "supplied_to_model", "authored_reply"]
    assert list((aa.WORKSPACE_DIR / "outbox" / "human" / "mike").glob("*.txt"))
    assert not list((aa.WORKSPACE_DIR / "outbox").glob("reply_*.txt"))


def test_failed_http_does_not_claim_supply_or_reply(agent, monkeypatch):
    path, _ = seed_inbox()
    monkeypatch.setattr(aa, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(aa, "FALLBACK_MODEL", "")
    monkeypatch.setattr(aa.requests, "post", Mock(side_effect=TimeoutError("fixture timeout")))
    assert agent._query_llm("A possible correspondence turn.") is None
    stages = [r["stage"] for r in rows(aa.WORKSPACE_DIR)]
    assert stages == ["file_consumed", "request_prepared", "submission_unconfirmed", "generation_failed"]
    assert (path.parent / "read" / path.name).exists()
    assert not (aa.WORKSPACE_DIR / "outbox").exists()


def test_mixed_sender_batch_routes_selected_human_only(agent):
    path, _ = seed_inbox()
    peer = letter("peer_seed", "astrid").replace("HUMAN LETTER V1", "CORRESPONDENCE V1")
    (path.parent / "from_astrid_correspondence_peer_seed.txt").write_text(peer)
    inbox = agent._read_inbox()
    assert {m.sender for m in inbox.messages} == {"mike", "astrid"}
    inbox.accepted("fixture_attempt", "fixture")
    reply = agent._save_outbox_reply("INBOX_REPLY human_seed\nHi Mike.", inbox_context=inbox)
    assert reply.parent.name == "mike"
    assert not list((aa.WORKSPACE_DIR / "outbox").glob("reply_*.txt"))
    assert rows(aa.WORKSPACE_DIR)[-1]["reply_to"] == "human_seed"


def test_duplicate_ids_do_not_create_ambiguous_reply(tmp_path):
    inbox = context(tmp_path)
    ambiguous = InboxContext(str(inbox), inbox.messages * 2, tmp_path)
    ambiguous.accepted("fixture_attempt", "fixture")
    assert declared_reply("INBOX_REPLY human_seed\nHi", ambiguous) is None


def test_fallback_preserves_same_message_and_records_separate_attempts(agent, monkeypatch):
    _, source = seed_inbox()
    body = "INBOX_REPLY human_seed\nHi Mike."
    post = Mock(side_effect=[TimeoutError("fixture timeout"),
                            Mock(status_code=200, json=lambda: {"message": {"content": body}})])
    monkeypatch.setattr(aa.requests, "post", post)
    monkeypatch.setattr(aa, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(aa, "FALLBACK_MODEL", "gemma3:4b")
    assert agent._query_llm("Ambient context " * 1000) == body
    assert post.call_count == 2
    for call in post.call_args_list:
        assert source in call.kwargs["json"]["messages"][1]["content"]
    events = rows(aa.WORKSPACE_DIR)
    attempts = [r["attempt_id"] for r in events if r["stage"] == "request_prepared"]
    assert len(set(attempts)) == 2
    assert events[-1]["supplied_attempt_id"] == attempts[-1]


def test_mlx_transport_also_witnesses_exact_message(agent, monkeypatch):
    inbox = context(aa.WORKSPACE_DIR)
    prompt = InboxPrompt("Ambient", inbox)
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture-model")
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "choices": [{"message": {"content": "Hi"}}]}))
    monkeypatch.setattr(aa.requests, "post", post)
    assert agent._query_mlx(prompt, "System", 128) == "Hi"
    assert str(inbox) in post.call_args.kwargs["json"]["messages"][1]["content"]
    assert [r["stage"] for r in rows(aa.WORKSPACE_DIR)] == ["request_prepared", "supplied_to_model"]


def test_small_context_refuses_instead_of_exceeding_budget(tmp_path):
    inbox = context(tmp_path, letter(body="letter " * 220))
    with pytest.raises(ValueError, match="intact admission budget"):
        aa._adapt_ollama_messages_for_model(
            model="gemma4:12b", system_msg="system" * 1000,
            prompt=InboxPrompt("ambient" * 2000, inbox), num_ctx=2000, num_predict=768,
        )


def mixed_context(tmp_path):
    human = letter()
    peer = letter("peer_seed", "astrid").replace("HUMAN LETTER V1", "CORRESPONDENCE V1")
    inbox = InboxContext(human + "\n" + peer, [
        InboxMessage.from_source("human_letter_seed.txt", human, human),
        InboxMessage.from_source("from_astrid_correspondence_peer_seed.txt", peer, peer),
    ], tmp_path)
    inbox.accepted("fixture_attempt", "fixture")
    return inbox


def test_next_style_reply_blocks_route_separate_bodies_and_preserve_original(tmp_path):
    inbox = mixed_context(tmp_path)
    text = ("An independent reflection.\n\n"
            "NEXT: INBOX_REPLY human_seed\nHello Mike.\n\n"
            "NEXT: INBOX_REPLY peer_seed\nHello Astrid.")
    archive = save_generation(tmp_path, text, inbox)
    assert archive.parent.name == "unaddressed"
    assert archive.read_text().endswith(text)
    human = next((tmp_path / "outbox/human/mike").glob("*.txt")).read_text()
    peer = next((tmp_path / "outbox").glob("reply_*.txt")).read_text()
    assert human.endswith("Hello Mike.\n\n")
    assert peer.endswith("Hello Astrid.")
    assert "Hello Astrid" not in human and "Hello Mike" not in peer
    assert "independent reflection" not in human + peer
    addressed = [r for r in rows(tmp_path) if r["stage"] == "authored_reply"]
    assert {r["recipient"] for r in addressed} == {"mike", "astrid"}
    assert all(r["source_artifact_path"] == str(archive) for r in addressed)


@pytest.mark.parametrize("text", [
    "A quoted example:\n```text\nNEXT: INBOX_REPLY human_seed\nHi.\n```",
    "A quoted example:\n~~~\nNEXT: INBOX_REPLY human_seed\nHi.\n~~~",
    "> NEXT: INBOX_REPLY human_seed\n> Hi.",
    "NEXT: INBOX_REPLY unknown\nHi.",
    "NEXT: INBOX_REPLY human_seed\n\nNEXT: REST",
    "NEXT: INBOX_REPLY human_seed\nOne.\nNEXT: INBOX_REPLY human_seed\nTwo.",
])
def test_quoted_unknown_empty_and_duplicate_blocks_do_not_route(tmp_path, text):
    inbox = context(tmp_path)
    inbox.accepted("fixture_attempt", "fixture")
    assert declared_replies(text, inbox) == []
    path = save_generation(tmp_path, text, inbox)
    assert path.read_text().endswith(text)
    assert not (tmp_path / "outbox/human").exists()
    assert not list((tmp_path / "outbox").glob("reply_*.txt"))


def test_reply_body_is_not_a_footer_control_but_real_next_stays_separate(tmp_path):
    text = "INBOX_REPLY human_seed\nDiscussing a setting: REGIME=focus\nNEXT: REST"
    inbox = context(tmp_path)
    inbox.accepted("fixture_attempt", "fixture")
    replies = declared_replies(text, inbox)
    assert replies[0][1] == "Discussing a setting: REGIME=focus\n"
    assert reply_blocks(text)[1] == "NEXT: REST"
    archive = save_generation(tmp_path, text, inbox)
    assert archive.read_text().endswith(text)


def test_actual_next_wrapper_does_not_queue_reply_blocks_or_apply_their_dials(agent, monkeypatch):
    seed_inbox()
    text = "Independent prose.\nNEXT: INBOX_REPLY human_seed\nHello Mike.\nREGIME=focus"
    monkeypatch.setattr(aa.requests, "post", Mock(return_value=Mock(
        status_code=200, json=lambda: {"message": {"content": text}})))
    monkeypatch.setattr(aa, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(aa, "MODEL", "gemma4:12b")
    monkeypatch.setattr(agent, "_emit_next_hints", Mock(return_value=""))
    apply = Mock()
    record = Mock(side_effect=AssertionError("reply must not become a NEXT action"))
    monkeypatch.setattr(agent, "_apply_footer_directives", apply)
    monkeypatch.setattr(agent, "_record_llm_next_action_choice", record)
    response, next_action = agent._query_llm_with_next("A normal reflective turn.")
    assert isinstance(response, InboxGeneration)
    assert response == text and next_action is None
    apply.assert_called_once_with("Independent prose.\n")
    assert list((aa.WORKSPACE_DIR / "outbox/human/mike").glob("*.txt"))
    record.assert_not_called()


def test_next_block_requires_actual_supply(tmp_path):
    inbox = context(tmp_path)
    assert declared_replies("NEXT: INBOX_REPLY human_seed\nHello.", inbox) == []
