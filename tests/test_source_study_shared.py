"""Wire-level parity: real shared executable, fake HTTP, no live model or runtime."""
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from minime_autonomy.source_study import StudyClient, selected_reader

BINARY = Path(os.environ.get("ASTRID_SOURCE_STUDY_BIN", str(Path(__file__).resolve().parents[2] / "astrid/target/debug/astrid-source-study")))

class SharedSourceStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.astrid = root / "astrid"
        self.minime = root / "minime"
        self.source = self.minime / "minime_autonomy/runtime.py"
        self.source.parent.mkdir(parents=True)
        self.astrid.mkdir()
        self.source.write_text("def entry():\n" + "    # source line\n" * 2000)
        self.client = StudyClient(self.minime, root / "workspace", astrid_root=self.astrid, executable=BINARY)
        self.action = "SELF_STUDY OPEN minime/minime_autonomy/runtime.py"

    def test_intact_page_survives_retry_and_advances_only_after_completed_wire_response(self):
        prompt = self.client.prepare(self.action)
        messages, _ = prompt.messages(prompt.output["system_prompt"], 16000)
        failed = Mock(status_code=503, text='{"error":"busy"}')
        prompt.post(Mock(return_value=failed), "fake", {"messages":messages}, 1)
        retry = self.client.prepare("SELF_STUDY CONTINUE")
        self.assertEqual(retry.output, prompt.output)
        complete = Mock(status_code=200, text=json.dumps({"message":{"content":"NEXT: SELF_STUDY CONTINUE"},"done":True}))
        post = Mock(return_value=complete)
        retry.post(post, "fake", {"messages":messages}, 1)
        self.assertEqual(self.client.prepare("SELF_STUDY CONTINUE").output, prompt.output)
        retry.accepted()
        submitted = post.call_args.kwargs["data"].decode()
        artifact = json.loads(Path(retry.receipt["artifact_path"]).read_text())
        self.assertEqual(artifact["request_json"], submitted)
        self.assertEqual(json.loads(submitted)["messages"][1]["content"], str(prompt))
        next_page = self.client.prepare("SELF_STUDY CONTINUE")
        self.assertEqual(next_page.output["page"]["start"], prompt.output["page"]["end"])

    def test_trimmed_or_incomplete_page_cannot_advance(self):
        prompt = self.client.prepare(self.action)
        with self.assertRaises(ValueError):
            prompt.messages(prompt.output["system_prompt"], 100)
        with self.assertRaises(ValueError):
            prompt.post(Mock(), "fake", {"messages":[{"role":"user","content":str(prompt)[:100]}]}, 1)
        messages, _ = prompt.messages(prompt.output["system_prompt"], 16000)
        partial = Mock(status_code=200, text=json.dumps({"choices":[{"message":{"content":"partial"},"finish_reason":"length"}]}))
        with self.assertRaises(RuntimeError):
            prompt.post(Mock(return_value=partial), "fake", {"messages":messages}, 1)
            prompt.accepted()
        self.assertEqual(self.client.prepare("SELF_STUDY CONTINUE").output, prompt.output)

    def test_search_and_map_show_same_file_identity(self):
        result = self.client.prepare("SELF_STUDY FIND entry")
        self.assertIn("OPEN minime/minime_autonomy/runtime.py 1", result)
        self.assertIsNone(result.output["page"])
        self.assertIn("minime/minime_autonomy/runtime.py", self.client.prepare("SELF_STUDY MAP minime"))

    def test_recovery_is_stateless_and_does_not_prepare_or_claim_source(self):
        self.assertFalse(self.client.workspace.exists())
        recovery = self.client.recover_navigation("RELATE entry")
        self.assertIn("SELF_STUDY RELATE entry", recovery["commands"])
        self.assertFalse(self.client.workspace.exists())
        self.assertIsNone(self.client.recover_navigation("SEARCH reservoir continuity"))
        self.assertIsNone(self.client.recover_navigation("WRITE CONTINUE"))
        self.assertFalse(self.client.workspace.exists())

    def test_navigation_keeps_owned_notes_and_exact_pending_source(self):
        source = self.client.prepare(self.action)
        messages, _ = source.messages(source.output["system_prompt"], 16000)
        body = {"message":{"content":"STUDY_NOTE: Trace the entry point.\nSTUDY_QUESTION: Who calls entry?\nNEXT: SELF_STUDY MAP"},"done":True}
        source.post(Mock(return_value=Mock(status_code=200, text=json.dumps(body))), "fake", {"messages":messages}, 1)
        source.accepted()
        next_page = self.client.prepare("SELF_STUDY CONTINUE")
        navigation = self.client.prepare("SELF_STUDY MAP minime")
        self.assertIn("Partial delivery", navigation)
        self.assertIn("Who calls entry?", navigation)
        self.assertIn("SELF_STUDY RESUME minime/minime_autonomy/runtime.py", navigation)
        messages, _ = navigation.messages(navigation.output["system_prompt"], 16000)
        body = {"choices":[{"message":{"content":"STUDY_QUESTION: Which Action calls entry?\nNEXT: SELF_STUDY CONTINUE"},"finish_reason":"stop"}]}
        navigation.post(Mock(return_value=Mock(status_code=200, text=json.dumps(body))), "fake", {"messages":messages}, 1)
        navigation.accepted()
        self.assertTrue(Path(navigation.receipt["artifact_path"]).is_file())
        resumed = self.client.prepare("SELF_STUDY CONTINUE")
        self.assertEqual(next_page.output["page"], resumed.output["page"])
        self.assertIn("Which Action calls entry?", resumed)
        self.assertIn("Trace the entry point.", resumed)
        self.assertNotIn("Which Action calls entry?", resumed.output["system_prompt"])
        self.assertIn('No matches for the exact literal query "entry;"', self.client.prepare("SELF_STUDY FIND entry;"))

    def test_selected_release_reader_is_bound_to_astrid_manifest(self):
        stage = (self.astrid.parent / "release").resolve()
        executable = stage / "helpers/astrid-source-study"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"reader fixture")
        manifest = stage / "manifest.json"
        manifest.write_text(json.dumps({"artifacts": {"source-study-reader": {
            "path": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}}}))
        selection = self.astrid / ".runtime/bridge-deployment/active.json"
        selection.parent.mkdir(parents=True)
        selection.write_text(json.dumps({"schema": "bridge_release_selection_v1", "stage": str(stage),
                                        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
        self.assertEqual(selected_reader(self.astrid), executable)
        executable.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "executable changed"):
            selected_reader(self.astrid)
        manifest.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "manifest changed"):
            selected_reader(self.astrid)

if __name__ == "__main__":
    unittest.main()


def test_actual_mlx_and_ollama_adapters_submit_same_protected_page(tmp_path):
    from unittest.mock import patch
    import autonomous_agent as aa
    source = tmp_path / "minime/minime_autonomy/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("# model request parity\n" * 500)
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    client = StudyClient(tmp_path / "minime", tmp_path / "workspace", astrid_root=astrid, executable=BINARY)
    agent = object.__new__(aa.AutonomousAgent)
    for backend in ("mlx", "ollama", "ollama_fast"):
        prompt = client.prepare("SELF_STUDY OPEN minime/minime_autonomy/runtime.py")
        body = ({"choices":[{"message":{"content":"NEXT: SELF_STUDY CONTINUE"},"finish_reason":"stop"}]} if backend == "mlx" else {"message":{"content":"NEXT: SELF_STUDY CONTINUE"},"done":True})
        response = Mock(status_code=200, text=json.dumps(body))
        response.json.return_value = body
        with patch.object(aa.requests, "post", return_value=response) as post, patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "_append_llm_timing"), patch.object(aa.generation_record, "stash_attempt"):
            if backend == "mlx":
                result = agent._query_mlx(prompt, prompt.output["system_prompt"], 2048, journal=True)
            elif backend == "ollama":
                result = agent._query_ollama(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study", journal=True)
            else:
                with patch.object(aa, "FALLBACK_MODEL", "fixture-fallback"):
                    result = agent._query_ollama_fast_fallback(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study", journal=True)
        assert result == "NEXT: SELF_STUDY CONTINUE"
        assert prompt.receipt is None
        prompt.accepted()
        assert prompt.receipt is not None
        submitted = json.loads(post.call_args.kwargs["data"])
        assert submitted["messages"][1]["content"] == str(prompt)
        assert submitted.get("max_tokens", submitted.get("options", {}).get("num_predict")) == 4096
        if backend != "mlx":
            assert submitted["options"]["num_ctx"] >= 10240


def test_dispatch_retries_invisible_completion_before_recording_delivery(tmp_path):
    from unittest.mock import patch
    import autonomous_agent as aa
    source = tmp_path / "minime/minime_autonomy/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("# complete source\n" * 500)
    astrid = tmp_path / "astrid"
    astrid.mkdir()
    client = StudyClient(tmp_path / "minime", tmp_path / "workspace", astrid_root=astrid, executable=BINARY)
    prompt = client.prepare("SELF_STUDY OPEN minime/minime_autonomy/runtime.py")
    agent = object.__new__(aa.AutonomousAgent)
    bodies = [
        {"choices":[{"message":{"content":"<think>internal only</think>"},"finish_reason":"stop"}]},
        {"message":{"content":"NEXT: SELF_STUDY CONTINUE"},"done":True},
    ]
    def post(url, **kwargs):
        assert client.prepare("SELF_STUDY CONTINUE").output == prompt.output
        assert str(prompt) == json.loads(kwargs["data"])["messages"][1]["content"]
        body = bodies.pop(0)
        response = Mock(status_code=200, text=json.dumps(body))
        response.json.return_value = body
        return response
    with patch.object(aa.requests, "post", side_effect=post), patch.object(aa, "MLX_MODEL", "fixture"), patch.object(aa, "_llm_backend_attempts", return_value=["mlx", "ollama"]), patch.object(aa.generation_record, "begin", return_value=None), patch.object(aa.generation_record, "stash_attempt"), patch.object(aa, "_append_llm_timing"):
        result = agent._query_llm_raw(prompt, prompt.output["system_prompt"], 2048, prompt_class="source_study")
    assert not bodies
    assert result == "NEXT: SELF_STUDY CONTINUE"
    assert prompt.receipt is not None
    assert client.prepare("SELF_STUDY CONTINUE").output["page"]["start"] == prompt.output["page"]["end"]
