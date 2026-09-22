"""The real JSON adapter and native stores, with synthetic content and a stub provider."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from minime_autonomy.source_study import StudyClient
from minime_autonomy.activity_focus import ActivityFocus


@pytest.fixture
def client(tmp_path):
    astrid = tmp_path / "astrid"
    minime = tmp_path / "minime"
    astrid.mkdir()
    minime.mkdir()
    (astrid / "Cargo.toml").write_text("[workspace]\nmembers=[]\n")
    (astrid / "crates/fixture/src").mkdir(parents=True)
    (astrid / "crates/fixture/src/lib.rs").write_text("pub fn first() {}\npub fn last() {}\n")
    return StudyClient(minime, minime / "workspace", astrid_root=astrid,
                       executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))


def status(client, at=100):
    return client.activity({"op": "status"}, request_id="status", expected_revision=None, now_ms=at)


def command(client, action, ident, at=100):
    return client.activity({"op": "command", "action": action}, request_id=ident,
                           expected_revision=status(client, at)["revision"], now_ms=at)


def deliver(prompt, text):
    response = Mock(status_code=200, text=json.dumps({"message": {"content": text}, "done": True, "done_reason": "stop"}))
    messages, _ = prompt.messages(prompt.output["system_prompt"], prompt.input_budget_bytes)
    prompt.post(Mock(return_value=response), "fixture://no-network", {"messages": messages}, 1)
    prompt.accepted()


def test_host_recovery_never_repeats_uncertain_call(client):
    client.prepare("WRITE START fixture")
    host = ActivityFocus(client, clock=lambda: 100)
    host.command("ACTIVITY_FOCUS WRITE d1")
    prompt = client.prepare(host.next()["next_action"])
    admission = host.admit(prompt, "WRITE RESUME d1", "job")
    replacement = ActivityFocus(client, clock=lambda: 101)
    with pytest.raises(RuntimeError, match="delivery|receipt"):
        replacement.recover_committed()
    assert replacement.status()["pending_job"] == "job"
    with pytest.raises(RuntimeError, match="pending"):
        replacement.admit(prompt, "WRITE RESUME d1", "replacement")
    deliver(prompt, "Exact retained output.\nNEXT: WRITE CONTINUE")
    replacement.recover_committed()
    assert replacement.next()["next_action"] == "WRITE CONTINUE"
    assert replacement.status()["admitted"] == 1
    assert admission == ("job", prompt.output["navigation_id"])


def test_provider_failure_ends_priority_without_erasing_pending_input(client):
    client.prepare("WRITE START fixture")
    host = ActivityFocus(client, clock=lambda: 100)
    host.command("ACTIVITY_FOCUS WRITE d1")
    prompt = client.prepare("WRITE RESUME d1")
    admitted = host.admit(prompt, "WRITE RESUME d1", "job")
    host.finish(admitted, verified=False)
    assert not host.status()["protected"]
    assert host.next().get("next_action") is None
    assert client.prepare("WRITE CONTINUE").output["navigation_id"] == prompt.output["navigation_id"]


def test_native_adapter_write_continue_park_return_revision(client):
    draft = client.prepare("WRITE START private fixture")
    deliver(draft, "Private exact first passage.\nNEXT: REST")
    focus = command(client, "ACTIVITY_FOCUS WRITE d1 turns 2", "start")
    for n, action in enumerate(("WRITE RESUME d1", "WRITE CONTINUE")):
        prompt = client.prepare(action)
        assert "Private exact first passage." in prompt
        input_id = prompt.output["navigation_id"]
        focus = client.activity({"op": "admit", "job_id": f"job{n}", "input_id": input_id, "action": action},
                                request_id=f"admit{n}", expected_revision=focus["revision"], now_ms=101+n)
        deliver(prompt, "Additional exact passage.\nNEXT: WRITE CONTINUE")
        focus = client.activity({"op": "complete", "job_id": f"job{n}", "input_id": input_id},
                                request_id=f"done{n}", expected_revision=focus["revision"], now_ms=101+n)
    assert focus["admitted"] == 2 and not focus["protected"]
    command(client, "PARK_ACTIVITY", "park", 110)
    unrelated = client.prepare("WRITE START independent")
    deliver(unrelated, "Unrelated private passage.")
    saved = status(client, 111)
    returned = command(client, saved["return_command"], "return", 111)
    assert not returned["protected"] and returned["admitted"] == 2
    revision = client.prepare("WRITE REVISE qualify")
    assert "Private exact first passage." in revision
    assert "Unrelated private passage." not in revision
    deliver(revision, "The new account remains unresolved.\nNEXT: REST")
    checkpoint = (client.workspace / "diagnostics/source_first_v3/shared_reader/activity-focus-v1.json").read_text()
    assert "Private exact first passage." not in checkpoint
    assert "Additional exact passage." not in checkpoint
    assert "private fixture" not in json.dumps(status(client, 112))


def test_concurrent_helpers_admit_only_once_and_conflicting_retry_fails(client):
    client.prepare("WRITE START fixture")
    focus = command(client, "ACTIVITY_FOCUS WRITE d1", "start")
    prompt = client.prepare("WRITE RESUME d1")
    request = {"op": "admit", "job_id": "job", "input_id": prompt.output["navigation_id"], "action": "WRITE RESUME d1"}

    def admit(_):
        return client.activity(request, request_id="same-operation", expected_revision=focus["revision"], now_ms=101)
    # Each call launches an independent Rust process with the same owner lock.
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(admit, range(8)))
    assert all(result["admitted"] == 1 for result in replies)
    with pytest.raises(RuntimeError, match="conflicting"):
        client.activity({**request, "job_id": "other"}, request_id="same-operation",
                        expected_revision=focus["revision"], now_ms=102)
    assert status(client, 103)["admitted"] == 1


def test_question_source_changes_require_explicit_reselection(client):
    question = client.prepare("SELF_STUDY QUESTION NEW What does first do?")
    deliver(question, "An unresolved question.")
    page = client.prepare("SELF_STUDY OPEN astrid/crates/fixture/src/lib.rs 1")
    assert page.output.get("page") is not None
    deliver(page, "STUDY_NOTE: The fixture has two functions.")
    command(client, "ACTIVITY_FOCUS QUESTION q1", "focus")
    command(client, "PARK_ACTIVITY", "park", 101)
    back = status(client, 102)["return_command"]
    (client.astrid_root / "crates/fixture/src/lib.rs").write_text("pub fn replacement() {}\n")
    with pytest.raises(RuntimeError, match="source changed"):
        command(client, back, "return", 102)
    # Recovery releases priority, retaining the authored notebook.
    with pytest.raises(RuntimeError, match="interrupted activity"):
        status(client, 103)
    assert not status(client, 104)["protected"]
    selected = client.prepare("SELF_STUDY QUESTION q1")
    assert "fixture has two functions" in selected
    fresh = client.prepare("SELF_STUDY OPEN astrid/crates/fixture/src/lib.rs 1")
    assert "replacement" in fresh
