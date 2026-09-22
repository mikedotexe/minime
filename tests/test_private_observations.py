"""Real shared helper + Minime dispatch, synthetic recorder and stubbed providers only."""
import json
import itertools
import os
from pathlib import Path
import time
from unittest.mock import Mock, patch

import pytest
import autonomous_agent as aa
from minime_autonomy.parsing import parse_next_action
from minime_autonomy.source_study import StudyClient


def deliver(prompt, text):
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True, "done_reason": "stop"}))
    prompt.post(Mock(return_value=response), "fixture://no-network", {"messages": messages}, 1)
    prompt.accepted()


def test_real_adapter_preservation_analysis_and_deliberate_disclosure(tmp_path):
    astrid, minime = tmp_path / "astrid", tmp_path / "minime"
    astrid.mkdir(); (minime / "workspace/runtime").mkdir(parents=True)
    client = StudyClient(minime, minime / "workspace", astrid_root=astrid,
                         executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    operations = itertools.count()
    def prepare(action):
        return client.prepare(action, request_id=f"observation-host-{next(operations)}")
    store = client.workspace / "diagnostics/source_first_v3/shared_reader"
    now = time.time_ns() // 1_000_000
    frames = [{"t_ms": i*1000, "wall_clock_unix_ms": now-(79-i)*1000,
               "summary": {"finite_fraction": 1.0}, "activations": [0.25 if i%8<4 else -0.25]*128} for i in range(80)]
    (minime / "workspace/runtime/esn_activation_trace_v1.json").write_text(json.dumps({
        "policy": "esn_activation_trace_v1", "reservoir_dim": 128, "sample_interval_ms": 1000,
        "retained_secs": 180, "updated_at_unix_ms": now, "frames": frames}))
    first = prepare("WRITE START Private title")
    passage = "Unselected beginning.\nA pattern I want to keep: café.\nUnselected ending."
    deliver(first, passage + "\nNEXT: REST")

    def draft():
        return json.loads((store / "writing/drafts-v2.json").read_bytes())["drafts"]["d1"]

    def request(operation, ident="", present=False):
        status = prepare('WRITE OBSERVE {"owner":"minime","draft":"d1","operation":{"kind":"status"}}')
        revision = str(status).split("revision ", 1)[1].splitlines()[0]
        records = draft()["observations"]["records"]
        payload = {"owner": "minime", "draft": "d1", "revision": revision,
                   "request_id": ident, "expected_head": records[-1]["id"] if records else "empty",
                   "operation": operation, "present": present}
        action = "WRITE OBSERVE " + json.dumps(payload, ensure_ascii=False)
        assert parse_next_action("An authored choice.\nNEXT: " + action)[0] == action
        return prepare(action)

    capture = request({"kind": "capture", "seconds": 180}, "capture")
    assert capture.output["generation_requested"] is False
    ident = draft()["observations"]["records"][-1]["id"]
    request({"kind": "annotate", "target": ident, "text": 'Private <think> AND REST RESIDUE: "NEXT: REST"'}, "note")
    prepare("WRITE PARK"); prepare("WRITE START unrelated")
    restored = prepare("WRITE RESUME d1")
    assert passage in restored and "Private <think>" not in restored
    analysis = {"recipe": "state-return-rms-v1", "window": {"capture": ident, "start_ms": 0, "end_ms": 79000}, "threshold": 0.01}
    result = request({"kind": "analyze", "analysis": analysis}, "analysis", present=True)
    deliver(result, "The numerical result leaves my interpretation open.")
    assert draft()["parts"] == [passage]
    preview = request({"kind": "link_preview", "captures": [ident],
                       "destination": {"kind": "new", "question": "Does this pattern recur?"}}, "preview", present=True)
    preview_id = draft()["observations"]["records"][-1]["id"]
    with pytest.raises(RuntimeError, match="preview must first"):
        request({"kind": "link_confirm", "preview": preview_id}, "early-confirm")
    deliver(preview, "The preview contains only selected numerical evidence and my question.")
    request({"kind": "link_confirm", "preview": preview_id}, "confirm")
    public = (store / "reader-v1.json").read_text()
    assert "Does this pattern recur?" in public
    for private in ["Private title", "Unselected", "café", "Private <think>"]:
        assert private not in public
    state = json.loads(public)
    assert state["questions"]["active"] is None
    assert not (client.workspace / "journal").exists()
    assert not (client.workspace / "sensory").exists()


def test_storage_only_runtime_dispatch_never_calls_model_or_public_writers(tmp_path):
    agent = object.__new__(aa.AutonomousAgent)
    agent._current_action_continuity_event = {"action_id": "synthetic-observation"}
    agent._query_llm_with_next = Mock(side_effect=AssertionError("storage must not generate"))
    agent._write_journal_entry = Mock(side_effect=AssertionError("storage must not publish"))
    agent._record_current_action_artifact = Mock(side_effect=AssertionError("no public artifact"))
    prompt = Mock(output={"generation_requested": False, "input_kind": "private_writing"})
    before = sorted(tmp_path.rglob("*"))
    with patch.object(aa, "StudyClient") as client, patch.object(aa, "WORKSPACE_DIR", tmp_path):
        client.return_value.prepare.return_value = prompt
        agent._run_shared_source_study({}, 'WRITE OBSERVE {"operation":{"kind":"capture"}}')
    agent._query_llm_with_next.assert_not_called()
    agent._write_journal_entry.assert_not_called()
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("prefix", ["WRITE OBSERVE", "SELF_STUDY OBSERVE"])
def test_typed_payload_bytes_survive_next(prefix):
    action = prefix + ' {"text":"<think> AND REST RESIDUE: NEXT: WRITE START café </s>"}  '
    assert parse_next_action("NEXT: " + action)[0] == action
    agent = object.__new__(aa.AutonomousAgent)
    assert agent._split_multi_action(action) == [action]


def test_private_choices_do_not_enter_continuity_summaries_or_pending_logs(tmp_path, caplog):
    from collections import deque
    from minime_autonomy import writing
    secret = "PRIVATE_OBSERVATION_SENTINEL"
    action = 'WRITE OBSERVE {"text":"' + secret + '"}'
    store = aa.ActionContinuityStore(tmp_path)
    event = store.begin_action(action, action, "self_study", "self_study", {},
                               normalization_signal={"raw_next": action},
                               choice_envelope_v1={"residue": secret, "raw_next": action})
    assert secret not in json.dumps(event)
    assert event["visibility"] == "protected_summary"
    assert event["raw_next"] is None and event["suggested_next"] is None
    agent = object.__new__(aa.AutonomousAgent)
    agent.session_id = 1
    agent._recent_next_actions = deque()
    agent._pending_choice_envelope_v1 = None
    agent._sovereignty_state_path = lambda: str(tmp_path / "owner-pending.json")
    with caplog.at_level("INFO"):
        agent._persist_pending_next_action(action, reason="synthetic authored choice")
        agent._persist_pending_next_action(None, reason="synthetic mismatch", expected_action=action + " ")
    assert secret not in caplog.text
    assert writing.diagnostic_action(action) == "WRITE [private payload withheld]"
    assert json.loads((tmp_path / "owner-pending.json").read_text())["pending_next_action"] == action
