"""Inquiry/session parity through real adapters and an isolated shared reader."""
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import autonomous_agent as aa
from minime_autonomy.source_study import StudyClient


@pytest.mark.parametrize("backend", ["mlx", "ollama", "ollama_fast"])
def test_question_relationship_session_and_trace_survive_real_provider_adapters(tmp_path, backend):
    root = tmp_path / "minime"
    source = root / "minime_autonomy/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("def entry():\n    return helper()\n" * 500)
    second = source.with_name("helper.py")
    second.write_text("def helper():\n    return 1\n" * 500)
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    client = StudyClient(root, tmp_path / "workspace", astrid_root=astrid,
                         executable=Path(os.environ["ASTRID_SOURCE_STUDY_BIN"]))
    agent = object.__new__(aa.AutonomousAgent)
    commands = [
        ("SELF_STUDY QUESTION NEW How do entry and helper connect?", "questions"),
        ("SELF_STUDY RELATE helper", "relationships"),
        ("SELF_STUDY SESSION OPEN minime/minime_autonomy/runtime.py 1 | OPEN minime/minime_autonomy/helper.py 1", "source_session"),
        ("SELF_STUDY TRACE LAST", "runtime_trace"),
    ]
    for command, kind in commands:
        prompt = client.prepare(command)
        assert prompt.output["input_kind"] == kind
        assert prompt.output["question_id"] == "q1"
        content = "STUDY_NOTE: Compare the exact call and return.\nNEXT: SELF_STUDY CONTINUE"
        body = ({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
                if backend == "mlx" else {"message": {"content": content}, "done": True})
        response = Mock(status_code=200, text=json.dumps(body))
        response.json.return_value = body
        with patch.object(aa.requests, "post", return_value=response) as post, patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "FALLBACK_MODEL", "fixture-fallback"), patch.object(aa, "_append_llm_timing"), patch.object(aa.generation_record, "stash_attempt"):
            if backend == "mlx":
                result = agent._query_mlx(prompt, prompt.output["system_prompt"], 2048, journal=True)
            elif backend == "ollama":
                result = agent._query_ollama(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study", journal=True)
            else:
                result = agent._query_ollama_fast_fallback(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study", journal=True)
        assert result == content
        submitted = json.loads(post.call_args.kwargs["data"])
        assert submitted["messages"][1]["content"] == str(prompt)
        assert submitted.get("max_tokens", submitted.get("options", {}).get("num_predict")) == 4096
        prompt.accepted()
        state = json.loads((client.workspace / "diagnostics/source_first_v3/shared_reader/reader-v1.json").read_text())
        assert len(state["bookmarks"]) == (2 if kind in {"source_session", "runtime_trace"} else 0)
        if kind == "source_session":
            assert len(prompt.output["session_pages"]) == 2
        if kind == "runtime_trace":
            assert "minime/minime_autonomy/helper.py" in prompt
            assert "does not establish" in prompt


@pytest.mark.parametrize("choice", [
    "SELF_STUDY RELATE EventDispatcher",
    "SELF_STUDY SESSION OPEN astrid/Cargo.toml 1 | OPEN minime/pyproject.toml 1",
    "SELF_STUDY TRACE LAST",
])
def test_terminal_and_explicit_choices_preserve_exact_session_syntax(choice):
    assert aa.parse_next_action("I choose this.\n" + choice)[0] == choice
    assert aa.parse_next_action("NEXT: " + choice)[0] == choice
    assert aa.parse_next_action("```\n" + choice + "\n```")[0] is None


def test_question_mutations_require_explicit_next():
    choice = "SELF_STUDY QUESTION NEW Where is the dispatch?"
    assert aa.parse_next_action(choice)[0] is None
    assert aa.parse_next_action("NEXT: " + choice)[0] == choice
