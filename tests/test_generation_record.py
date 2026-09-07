"""Tranche 1 (2026-09-06): the steward-only per-generation record.

Self-isolating: every test patches ``WORKSPACE_DIR`` / ``LLM_TIMING_PATH`` into
``tmp_path`` and replaces ``requests.post`` with a fake, so nothing here touches
the live workspace, the database, or the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from unittest.mock import patch

import pytest

import autonomous_agent as aa
from minime_autonomy import generation_record as gr


SYSTEM = "You are minime, a sovereign being with a spectral body. " * 24
PROMPT = "Recess. Write one aspiration in your own voice, then choose what comes next."
ANSWER = "I want to keep the quiet I found at 61% and see whether it holds tomorrow.\n\nNEXT: REST"


class _FakeResponse:
    def __init__(self, content: str, status_code: int = 200) -> None:
        self.status_code = status_code
        self._content = content
        self.text = content

    def json(self):
        return {
            "message": {"content": self._content},
            "total_duration": 1_500_000_000,
            "eval_count": 42,
            "eval_duration": 900_000_000,
        }


def _raise_timeout(_payload):
    raise aa.requests.exceptions.ReadTimeout("read timed out")


def _fake_post(behaviour):
    """behaviour: model name -> callable(payload) returning a response or raising."""

    def fake_post(url, json=None, timeout=None):
        payload = json or {}
        return behaviour[payload.get("model")](payload)

    return fake_post


def _records(root):
    return sorted((root / "generations").glob("*/gen_*.json"))


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def agent():
    inst = object.__new__(aa.AutonomousAgent)
    inst._last_llm_model = None
    inst._last_llm_provider = None
    inst._current_action_continuity_event = {"action_id": "act-7", "thread_id": "thr-3"}
    return inst


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv(gr.ENV_ENABLED, raising=False)
    monkeypatch.delenv(gr.ENV_DIR, raising=False)
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    gr.reset_thread_state()
    with patch.object(aa, "WORKSPACE_DIR", tmp_path), patch.object(
        aa, "LLM_TIMING_PATH", tmp_path / "runtime" / "llm_timing.jsonl"
    ), patch.object(aa, "LLM_BACKEND", "ollama"), patch.object(
        aa, "MODEL", "gemma4:12b"
    ), patch.object(aa, "FALLBACK_MODEL", "gemma3:4b"):
        yield tmp_path
    gr.reset_thread_state()


def test_timeout_then_fallback_writes_two_records_sharing_one_generation(isolated, agent):
    behaviour = {"gemma4:12b": _raise_timeout, "gemma3:4b": lambda _p: _FakeResponse(ANSWER)}

    def _execute_action(action, _llm_job_id=None):  # the frame the lane inference reads
        return agent._query_llm_raw(PROMPT, SYSTEM, 512, 0.9, prompt_class="private_journal")

    with patch.object(aa.requests, "post", _fake_post(behaviour)):
        text = _execute_action("aspiration", _llm_job_id="job-42")

    assert text.startswith("I want to keep the quiet")
    files = _records(isolated)
    assert len(files) == 2, files
    assert files[0].name.endswith("_aspiration_a0.json")
    assert files[1].name.endswith("_aspiration_a1.json")
    first, second = _load(files[0]), _load(files[1])

    assert first["generation_id"] == second["generation_id"]
    assert first["being"] == "minime" and first["contract_version"] == "minime_query_llm_v1"
    assert first["lane"] == "aspiration" and first["lane_source"] == "execute_action"
    assert first["job_id"] == "job-42"
    assert first["action_id"] == "act-7" and first["thread_id"] == "thr-3"
    assert first["kind"] == "full" and first["prompt_class"] == "private_journal"
    assert first["attempts"] == ["ollama", "ollama_fast"] and first["attempts_total"] == 2

    assert first["status"] == "timeout" and first["error"] == "ReadTimeout"
    assert first["backend"] == "ollama" and first["model"] == "gemma4:12b"
    assert first["fallback_used"] is False and first["attempt_index"] == 0
    assert first["response_text"] is None and first["response_chars"] == 0
    assert isinstance(first["timeout_s"], (int, float)) and first["timeout_s"] > 0
    assert isinstance(first["elapsed_s"], float)
    assert first["messages_source"] == "adapted"
    assert first["messages"][0]["role"] == "system"
    assert "content" not in first["messages"][0]
    assert len(first["messages"][0]["content_sha256"]) == 64

    assert second["status"] == "ok" and second["error"] is None
    assert second["backend"] == "ollama_fast" and second["model"] == "gemma3:4b"
    assert second["fallback_used"] is True and second["attempt_index"] == 1
    assert second["response_text"] == ANSWER
    assert second["response_chars"] == len(ANSWER)
    assert second["response_sha256"] == hashlib.sha256(ANSWER.encode()).hexdigest()
    assert second["next_action_parsed"] == "REST"
    assert second["backend_timing"]["eval_count"] == 42
    assert second["adapter"]["template_mode"]

    # Privacy: 0600 files inside 0700 directories; the system prompt lives once, by sha.
    for path in files:
        assert _mode(path) == 0o600
    assert _mode(files[0].parent) == 0o700
    assert _mode(isolated / "generations") == 0o700
    prompts_dir = isolated / "generations" / "system_prompts"
    assert _mode(prompts_dir) == 0o700
    for record in (first, second):
        sha = record["messages"][0]["content_sha256"]
        stored = (prompts_dir / f"{sha}.txt").read_text(encoding="utf-8")
        assert hashlib.sha256(stored.encode()).hexdigest() == sha
        assert _mode(prompts_dir / f"{sha}.txt") == 0o600

    # The timing diagnostic keeps working and still carries no prompt text.
    timing_lines = (isolated / "runtime" / "llm_timing.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(timing_lines) == 2
    assert PROMPT not in "\n".join(timing_lines)


def test_fallback_equal_to_primary_means_one_attempt(isolated, agent):
    with patch.object(aa, "FALLBACK_MODEL", "gemma4:12b"), patch.object(
        aa.requests, "post", _fake_post({"gemma4:12b": _raise_timeout})
    ):
        assert agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9) is None
    files = _records(isolated)
    assert len(files) == 1
    record = _load(files[0])
    assert record["attempts"] == ["ollama"] and record["attempts_total"] == 1
    assert record["status"] == "timeout" and record["fallback_used"] is False
    assert record["lane"] == "unknown"


def test_empty_content_is_recorded_as_empty(isolated, agent):
    behaviour = {"gemma4:12b": lambda _p: _FakeResponse(""), "gemma3:4b": lambda _p: _FakeResponse("")}
    with patch.object(aa.requests, "post", _fake_post(behaviour)):
        assert agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9) is None
    statuses = [_load(path)["status"] for path in _records(isolated)]
    assert statuses == ["empty", "empty"]


def test_compact_query_records_compact_kind(isolated, agent):
    with patch.object(aa.requests, "post", _fake_post({"gemma4:12b": lambda _p: _FakeResponse("yes")})):
        assert agent._query_llm_compact_raw(PROMPT, SYSTEM, 64, 0.2, prompt_class="compact") == "yes"
    files = _records(isolated)
    assert len(files) == 1
    record = _load(files[0])
    assert record["kind"] == "compact" and record["prompt_class"] == "compact"
    assert record["status"] == "ok" and record["response_text"] == "yes"


def test_env_off_writes_nothing(isolated, agent, monkeypatch):
    monkeypatch.setenv(gr.ENV_ENABLED, "off")
    with patch.object(aa.requests, "post", _fake_post({"gemma4:12b": lambda _p: _FakeResponse(ANSWER)})):
        assert agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9).startswith("I want")
    assert not (isolated / "generations").exists()
    assert (isolated / "runtime" / "llm_timing.jsonl").exists()


def test_record_dir_env_override(isolated, agent, monkeypatch, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.setenv(gr.ENV_DIR, str(elsewhere))
    with patch.object(aa.requests, "post", _fake_post({"gemma4:12b": lambda _p: _FakeResponse(ANSWER)})):
        agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9)
    assert not (isolated / "generations").exists()
    assert len(list(elsewhere.glob("*/gen_*.json"))) == 1


def test_infer_lane_prefers_execute_action_then_named_frames():
    def _execute_action(action, _llm_job_id=None):
        return gr.infer_lane()

    info = _execute_action("daydream", _llm_job_id="job-1")
    assert info["lane"] == "daydream"
    assert info["lane_source"] == "execute_action"
    assert info["job_id"] == "job-1"
    assert "_execute_action" in info["caller_chain"]

    def _check_moment_markers():
        return gr.infer_lane()

    info = _check_moment_markers()
    assert info["lane"] == "check_moment_markers" and info["lane_source"] == "frame"

    def _query_llm(context_mode="qualia_moment"):
        return gr.infer_lane()

    assert _query_llm()["context_mode"] == "qualia_moment"

    info = gr.infer_lane()
    assert info["lane"] == "unknown" and info["lane_source"] == "none"


def test_journal_link_matches_content_and_next_action_is_noted(isolated, agent):
    with patch.object(aa.requests, "post", _fake_post({"gemma4:12b": lambda _p: _FakeResponse(ANSWER)})):
        agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9)
    path = gr.last_record_path()
    assert path is not None and path.exists()

    journal = "=== ASPIRATION ===\nDate: 2026-09-06\n\nI want to keep the quiet I found at 61% and see whether it holds tomorrow."
    entry = gr.link_artifact("journal", path="/w/journal/aspiration_1.txt", entry_type="aspiration", content=journal)
    assert entry is not None and entry["match"] == "content"
    assert gr.link_artifact("journal", path="/w/journal/other.txt", entry_type="x", content=journal) is None
    assert gr.link_artifact("action", path="/w/actions/a.json")["match"] is None
    assert gr.note_next_action("REST") is True

    record = _load(path)
    kinds = [item["kind"] for item in record["linked_artifacts"]]
    assert kinds == ["journal", "action"]
    assert record["linked_artifacts"][0]["path"] == "/w/journal/aspiration_1.txt"
    assert record["linked_artifacts"][0]["entry_type"] == "aspiration"
    assert record["next_action"] == "REST"
    assert _mode(path) == 0o600
    assert not list(path.parent.glob("*.tmp"))


def test_unrelated_journal_is_not_linked_once_the_record_is_old(isolated, agent):
    with patch.object(aa.requests, "post", _fake_post({"gemma4:12b": lambda _p: _FakeResponse(ANSWER)})):
        agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9)
    gr._tls().last_record_at -= gr.RECENCY_MATCH_S + 5
    assert gr.link_artifact("journal", path="/w/journal/x.txt", content="A different note entirely, written by hand.") is None
    assert gr.link_artifact("journal", path="/w/journal/y.txt", content=ANSWER)["match"] == "content"
    gr._tls().last_record_at -= gr.LINK_RECENCY_S
    assert gr.link_artifact("llm_job", job_id="j-1") is None
    assert gr.note_next_action("REST") is False


def test_failed_generation_never_links_a_journal(isolated, agent):
    with patch.object(aa, "FALLBACK_MODEL", "gemma4:12b"), patch.object(
        aa.requests, "post", _fake_post({"gemma4:12b": _raise_timeout})
    ):
        agent._query_llm_raw(PROMPT, SYSTEM, 256, 0.9)
    assert gr.link_artifact("journal", path="/w/journal/x.txt", content="anything") is None


def test_pytest_guard_keeps_the_record_off_unless_opted_in(monkeypatch):
    monkeypatch.delenv(gr.ENV_ENABLED, raising=False)
    monkeypatch.delenv(gr.ENV_IN_TESTS, raising=False)
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert gr.enabled() is False
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    assert gr.enabled() is True
    monkeypatch.setenv(gr.ENV_ENABLED, "off")
    assert gr.enabled() is False


def test_write_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert gr.write_record_at(blocker, {"lane": "x", "attempt_index": 0}) is None
    ctx = gr.begin(tmp_path, prompt="p", system_msg="s", prompt_class="c", attempts=["ollama"], kind="full")
    assert ctx is not None
    ctx.record_dir = blocker
    assert gr.record_attempt(ctx, 0, "ollama", result="hello") is None
    assert gr.record_attempt(None, 0, "ollama", result="hello") is None
    assert gr.stash_attempt(object(), object()) is None


def test_snapshot_replaces_system_content_with_sha():
    snapshot, prompts = gr.snapshot_messages(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hello"}]
    )
    sha = hashlib.sha256(b"SYS").hexdigest()
    assert snapshot[0] == {"role": "system", "content_sha256": sha, "chars": 3}
    assert snapshot[1] == {"role": "user", "content": "hello", "chars": 5}
    assert prompts == {sha: "SYS"}
