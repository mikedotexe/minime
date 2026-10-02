"""Real provider adapters with isolated reader/state; no model or live I/O."""
import hashlib
import json
import os
from pathlib import Path
import stat
from unittest.mock import Mock, patch

import pytest
import autonomous_agent as aa
from minime_autonomy import generation_record as gr
from minime_autonomy.source_study import StudyClient
from minime_autonomy.source_study_diagnostics import StudyAttemptDiagnostics, WIRE_BYTES


@pytest.fixture
def study(tmp_path, monkeypatch):
    root = tmp_path / "minime"
    source = root / "minime_autonomy/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("def entry():\n    pass\n" * 2000)
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    workspace = tmp_path / "workspace"
    client = StudyClient(root, workspace, astrid_root=astrid,
                         executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    monkeypatch.setenv(gr.ENV_ENABLED, "on")
    monkeypatch.setattr(aa, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(aa, "LLM_TIMING_PATH", workspace / "runtime/llm_timing.jsonl")
    monkeypatch.setattr(aa, "MODEL", "fixture")
    monkeypatch.setattr(aa, "FALLBACK_MODEL", "fixture")
    gr.reset_thread_state()
    yield client, object.__new__(aa.AutonomousAgent)
    gr.reset_thread_state()


@pytest.mark.parametrize("backend", ["ollama", "mlx"])
@pytest.mark.parametrize("content,finish,reason", [
    ("", "length", "empty_final"),
    ("<think>private scratch</think>", "stop", "cleaned_empty"),
    ("<end_of_turn>", "stop", "cleaned_empty"),
    ("unfinished account", "length", "output_limit"),
])
def test_failed_attempt_is_retained_and_retry_delivers_once(study, monkeypatch, backend, content, finish, reason):
    client, agent = study
    monkeypatch.setattr(aa, "LLM_BACKEND", backend)
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture")
    prompt = client.prepare("SELF_STUDY OPEN minime/minime_autonomy/runtime.py 1")
    page_id = prompt.output["page"]["id"]
    body = ({"choices": [{"message": {"content": content}, "finish_reason": finish}]}
            if backend == "mlx" else {"message": {"content": content}, "done": True, "done_reason": finish,
                                      "eval_count": 4096})
    def answer(body):
        response = Mock(status_code=200, text=json.dumps(body))
        response.json.return_value = body
        return response
    with patch.object(aa.requests, "post", return_value=answer(body)):
        assert agent._query_llm_raw(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study", journal=True) is None
    state_path = client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json"
    state = json.loads(state_path.read_text())
    assert state["bookmarks"] == {} and prompt.receipt is None
    assert client.prepare("SELF_STUDY CONTINUE").output["page"]["id"] == page_id
    failures = list((client.workspace / "diagnostics/source_study_attempts").glob("*.json"))
    # MLX failure may also exercise the existing Ollama fallback; retain each attempt.
    assert failures
    record = next(json.loads(p.read_text()) for p in failures if json.loads(p.read_text())["source_study_failure"] == reason)
    assert record["native_finish"] == finish
    assert record["raw_content_chars"] == len(content)
    assert record["cleaned_content_chars"] == (len(content) if reason == "output_limit" else 0)
    assert json.loads(record["response"]["text"]) == body
    assert record["response"]["sha256"] == hashlib.sha256(json.dumps(body).encode()).hexdigest()
    assert not record["response"]["truncated"]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in failures)
    generations = [json.loads(p.read_text()) for p in (client.workspace / "generations").glob("*/gen_*.json")]
    assert any(g["backend_timing"].get("native_finish") == finish and
               g["backend_timing"].get("source_study_diagnostic_path") for g in generations)
    assert not list((client.workspace / "journal").glob("*"))
    good = {"message": {"content": "I can continue or change direction.\nNEXT: SELF_STUDY CONTINUE"}, "done": True, "done_reason": "stop"}
    monkeypatch.setattr(aa, "LLM_BACKEND", "ollama")
    retry = client.prepare("SELF_STUDY CONTINUE")
    with patch.object(aa.requests, "post", return_value=answer(good)):
        assert agent._query_llm_raw(retry, retry.output["system_prompt"], 2048, prompt_class="source_study", journal=True)
    after = json.loads(state_path.read_text())
    assert len(after["bookmarks"]) == 1 and len(after["receipts"]) == 1
    assert len(list((client.workspace / "diagnostics/source_study_attempts").glob("*.json"))) == len(failures)


def test_failed_wire_is_bounded_with_original_digest(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    monkeypatch.setenv(gr.ENV_ENABLED, "on")
    raw = "🦀" * WIRE_BYTES
    d = StudyAttemptDiagnostics(tmp_path, {}, raw)
    d.response(Mock(status_code=503, text=raw))
    record = json.loads(Path(d.summary["source_study_diagnostic_path"]).read_text())
    for wire in [record["request"], record["response"]]:
        assert wire["truncated"] and wire["retained_bytes"] <= WIRE_BYTES
        assert wire["sha256"] == hashlib.sha256(raw.encode()).hexdigest()


def test_diagnostic_storage_failure_does_not_change_completion(study):
    client, _ = study
    prompt = client.prepare("SELF_STUDY MAP")
    body = json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length"})
    prompt.post(Mock(return_value=Mock(status_code=200, text=body)), "fixture", {"messages": [{"role": "user", "content": str(prompt)}]}, 1)
    with patch.object(Path, "mkdir", side_effect=OSError("unavailable diagnostics")):
        assert prompt.clean_content(lambda _: None, "") is None
    assert prompt.receipt is None


@pytest.mark.parametrize("backend", ["ollama", "mlx"])
@pytest.mark.parametrize("finish", ["stop", "length"])
def test_private_writing_wire_stays_on_private_path(study, monkeypatch, backend, finish):
    client, agent = study
    monkeypatch.setattr(aa, "LLM_BACKEND", backend)
    monkeypatch.setattr(aa, "MLX_MODEL", "fixture")
    general_override = client.workspace / "general-record-override"
    monkeypatch.setenv(gr.ENV_DIR, str(general_override))
    secret = "PRIVATE_FIXTURE_ONLY exact continuation"
    prompt = client.prepare("WRITE START " + secret)
    content = secret + "\nNEXT: WRITE CONTINUE"
    body = ({"choices": [{"message": {"content": content}, "finish_reason": finish}]}
            if backend == "mlx" else {"message": {"content": content}, "done": True, "done_reason": finish})
    response = Mock(status_code=200, text=json.dumps(body))
    response.json.return_value = body
    with patch.object(aa.requests, "post", return_value=response):
        result = agent._query_llm_raw(prompt, prompt.output["system_prompt"], 2048,
                                      prompt_class="source_study", journal=True)
    assert bool(result) is (finish == "stop")
    private = client.workspace / "private_writing"
    records = list((private / "generations").glob("*/gen_*.json"))
    assert records
    assert any(secret in path.read_text() for path in records)
    assert not list(general_override.rglob("*.json"))
    assert not list((client.workspace / "generations").rglob("*.json"))
    assert not list((client.workspace / "diagnostics/source_study_attempts").glob("*.json"))
    failures = list((private / "diagnostics/source_study_attempts").glob("*.json"))
    assert bool(failures) is (finish == "length")
    assert "source_study_diagnostic_path" not in prompt.diagnostic_summary
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in records + failures)
    for path in (client.workspace / "runtime").rglob("*"):
        if path.is_file():
            assert secret not in path.read_text()
            assert "private_writing/diagnostics" not in path.read_text()


def test_failed_private_record_cannot_link_to_previous_public_generation(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.ENV_IN_TESTS, "1")
    monkeypatch.setenv(gr.ENV_ENABLED, "on")
    gr.reset_thread_state()
    public = gr.begin(tmp_path, prompt="Public input", system_msg="System",
                      prompt_class="source_study", attempts=["ollama"], kind="full")
    record = gr.record_attempt(public, 0, "ollama", result="Public result")
    before = record.read_bytes()
    private = gr.begin(tmp_path, prompt="Synthetic private input", system_msg="System",
                       prompt_class="private_writing", attempts=["ollama"], kind="full")
    with patch.object(gr, "write_record_at", return_value=None):
        assert gr.record_attempt(private, 0, "ollama", result="PRIVATE_ONLY") is None
    assert gr.note_next_action("WRITE START PRIVATE_ONLY") is False
    assert record.read_bytes() == before
    gr.reset_thread_state()
