"""Fresh reflection leaves mailbox availability and authored work untouched."""
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from minime_autonomy.mailbox import Mailbox
from tests.test_explicit_mailbox import seed
from tests.test_private_writing_continuation import STATE, deliver, writing_agent

pytestmark = pytest.mark.skipif(not os.environ.get("ASTRID_SOURCE_STUDY_BIN"), reason="shared helper required")


@pytest.mark.parametrize("feedback", [None, "Requested status: no selected letter."])
@pytest.mark.parametrize("completed", [False, True])
def test_fresh_reflection_does_not_inventory_or_acknowledge_mail(
    writing_agent, monkeypatch, feedback, completed,
):
    agent, client = writing_agent
    path, letter = seed(client.workspace)
    mailbox = Mailbox(client.workspace)
    notice = mailbox.notice()
    before = mailbox.path.read_bytes() if mailbox.path.exists() else None
    agent._pending_mailbox_feedback = feedback
    offered = []

    def provider(prompt, **kwargs):
        offered.append(prompt)
        assert prompt.output["input_kind"] == "reflection"
        assert "CHECK_MAILBOX" in prompt and "MAILBOX_STATUS" in prompt
        assert "Mailbox availability:" not in prompt
        assert "file(s) await inspection" not in prompt
        assert letter not in prompt
        assert prompt.mailbox_notice is None
        if feedback:
            assert feedback in prompt
        if not completed:
            return None
        text = "Synthetic authored reflection.\nNEXT: REST"
        deliver(prompt, text)
        return text

    monkeypatch.setattr(agent, "_query_llm", provider)
    agent._pending_next_action = "INTROSPECT"
    agent._persist_pending_next_action("INTROSPECT", reason="synthetic explicit choice")
    with monkeypatch.context() as scoped:
        scoped.setattr(Mailbox, "notice", Mock(side_effect=AssertionError("no ambient mailbox scan")))
        assert agent._decide_action(dict(STATE)) == "self_study"
        agent._execute_action("self_study", dict(STATE), _from_llm_job=True)
    assert len(offered) == 1
    assert (mailbox.path.read_bytes() if mailbox.path.exists() else None) == before
    assert mailbox.notice() == notice
    assert path.read_bytes() == letter.encode()
    assert not list((client.workspace / "outbox").rglob("*.txt"))
    assert agent._pending_mailbox_feedback == (None if completed else feedback)


def test_fresh_frame_keeps_scope_as_metadata_and_help_explicit(writing_agent):
    _, client = writing_agent
    reflection = client.prepare("INTROSPECT", request_id="fresh-frame")
    assert "Fresh reflection" in reflection
    assert "not continuous model activation" not in reflection
    assert "telemetry snapshot" not in reflection
    assert "telemetry snapshot" in reflection.output["evidence_scope"]
    assert "800-1,500 words" in reflection.output["system_prompt"]
    assert reflection.output["evidence_scope"].endswith("Presentation: fresh-reflection-v3.")
    assert "`NEXT: INTROSPECT` starts another fresh reflection without this passage supplied." in reflection
    assert (f"`NEXT: WRITE FROM_REFLECTION {reflection.output['navigation_id']}` preserves this response "
            "in a new private draft and requests a new appended passage after verified delivery.") in reflection
    assert "`NEXT: REST` stops without continuing." in reflection
    assert client.prepare("INTROSPECT", request_id="fresh-frame").output == reflection.output
    help_prompt = client.prepare("SELF_STUDY HELP attention")
    assert "retains public entries" in help_prompt
    assert "WRITE FROM_REFLECTION" in help_prompt


@pytest.mark.skipif(not os.environ.get("QUALIFICATION_OLD_READER"), reason="old immutable helper required")
def test_old_pending_frame_keeps_legacy_mail_presentation(writing_agent, monkeypatch):
    agent, client = writing_agent
    new = client.executable
    client.executable = Path(os.environ["QUALIFICATION_OLD_READER"])
    pending = client.prepare("INTROSPECT", request_id="prepare-retained-old")
    quiet_mail = pending.output["evidence_scope"].endswith("Presentation: fresh-reflection-v2.")
    client.executable = new
    _, letter = seed(client.workspace)
    offered = []

    def provider(prompt, **kwargs):
        offered.append(prompt)
        assert prompt.output == pending.output
        assert str(prompt).startswith(str(pending))
        assert ("Mailbox availability:" in prompt) is not quiet_mail
        assert letter not in prompt
        assert (prompt.mailbox_notice is None) is quiet_mail
        return None

    monkeypatch.setattr(agent, "_query_llm", provider)
    agent._current_action_continuity_event = {"action_id": "retained-old"}
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert len(offered) == 1
    assert Mailbox(client.workspace).notice() is not None
