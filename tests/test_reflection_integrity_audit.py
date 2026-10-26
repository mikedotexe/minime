"""Public synthetic evidence and real adapter replay, without live generation."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import autonomous_agent as aa
from minime_autonomy.mailbox_fs import Directory
from scripts import reflection_integrity_audit as audit
from tests.test_private_writing_continuation import STATE, writing_agent


RUNTIME = Path(aa.AutonomousAgent._strip_model_artifacts.__code__.co_filename).resolve()
SPLICE = 'Synthetic opening. A question that doesn\'Synthetic opening.\n\nNEXT: INTROSPECT'


def test_audit_executes_exact_production_cleanup_without_hidden_output():
    clean, strip, binding = audit.cleanup_functions(RUNTIME)
    agent = object.__new__(aa.AutonomousAgent)
    for text in (SPLICE, '<think>HIDDEN PRIVATE REASONING</think>Visible.<end_of_turn>',
                 'Quoted `NEXT: REST` is prose.\n\nNEXT: INTROSPECT', "", "  UTF-8: café  "):
        assert clean(text) == (agent._clean_llm_content(text.strip()) or "")
        assert strip(clean(text)) == agent._strip_model_artifacts(clean(text))
    assert len(binding["cleanup_ast_sha256"]) == 64


def synthetic_evidence(tmp_path, response_text=SPLICE, published_text=SPLICE):
    root = tmp_path.resolve()
    journal = "journal/introspect_synthetic.txt"
    job = "llm_jobs/jobs/job_synthetic/job.json"
    delivery = str(audit.NAVIGATION / "input_synthetic/receipt.json")
    for name in (journal, job, delivery):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / journal).write_text('=== INTROSPECTION: open reflection ===\nDelivery: verified input delivery; test\n\n' + published_text + '\n')
    (root / job).write_text(json.dumps({
        "job_id": "job_synthetic", "system": "minime", "action_text": "INTROSPECT", "status": "completed",
        "artifact_refs": [{"kind": "introspect", "path_or_uri": str(root / journal)}],
        "phase_timings": {"attempt_counts": {"ok": 1, "empty": 0, "error": 0}},
    }))
    wire = json.dumps({
        "schema": "source_study_navigation_delivery_v1",
        "output": {"input_kind": "reflection", "navigation_id": "input_synthetic"},
        "request_json": json.dumps({"think": False}),
        "response_json": json.dumps({"done": True, "done_reason": "stop", "model": "synthetic",
                                     "message": {"content": response_text, "thinking": "NEVER EXPORT"}}),
    })
    delivery = str(Path(delivery).with_name(audit.sha(wire) + ".json"))
    (root / delivery).write_text(wire)
    return root, journal, job, delivery


def test_exact_offsets_and_content_free_report(tmp_path):
    paths = synthetic_evidence(tmp_path, 'café: A', 'café: B')
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    result = audit.audit_entry(*paths, clean, strip)
    assert result["cleanup_to_publication"]["locations"] == [
        {"operation": "replace", "left_utf8_bytes": [7, 8], "right_utf8_bytes": [7, 8]}]
    assert "NEVER EXPORT" not in json.dumps(result)
    assert "café" not in json.dumps(result, ensure_ascii=False)
    assert result["attempt_count"] == 1


def test_utf8_mismatches_are_codepoint_aligned_and_large_edits_are_bounded():
    result = audit.differences("café", "cafê")
    assert result["locations"] == [
        {"operation": "replace", "left_utf8_bytes": [3, 5], "right_utf8_bytes": [3, 5]}]
    result = audit.differences("a" * 5000, "b" * 5000)
    assert result["coalesced_covering_range"]
    assert result["locations"][0]["left_utf8_bytes"] == [0, 5000]
    with pytest.raises(ValueError, match="bounded audit"):
        audit.differences("a" * (128 * 1024 + 1), "")


@pytest.mark.parametrize("data", ['{"done": true, "done": false}', '{"count": NaN}', '[]'])
def test_ambiguous_or_nonfinite_evidence_fails_closed(data):
    with pytest.raises(ValueError):
        audit.strict_json(data)


def test_delivery_content_address_is_verified(tmp_path):
    root, journal, job, delivery = synthetic_evidence(tmp_path)
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    incorrect = Path(delivery).with_name("wrong.json")
    (root / delivery).rename(root / incorrect)
    with pytest.raises(ValueError, match="content-address"):
        audit.audit_entry(root, journal, job, str(incorrect), clean, strip)


def test_evidence_group_is_rechecked_after_consumption(tmp_path, monkeypatch):
    paths = synthetic_evidence(tmp_path)
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    original = audit.inspect_delivery

    def concurrent_change(*args):
        result = original(*args)
        (paths[0] / paths[1]).write_text("changed after initial read")
        return result

    monkeypatch.setattr(audit, "inspect_delivery", concurrent_change)
    with pytest.raises(ValueError, match="across audit"):
        audit.audit_entry(*paths, clean, strip)


def test_frozen_manifest_cannot_substitute_a_different_public_sample():
    rows = [{"journal": f"journal/introspect_2026-10-25T{stamp}.txt",
             "job": f"llm_jobs/jobs/job_minime_{job}_introspect/job.json",
             "delivery": str(audit.NAVIGATION / f"input_{i}/receipt.json")}
            for i, (stamp, job) in enumerate(audit.SAMPLE)]
    assert audit.sample_references({"entries": rows}) == rows
    rows[-1]["job"] = rows[0]["job"]
    with pytest.raises(ValueError, match="selected twenty"):
        audit.sample_references({"entries": rows})


def test_cli_failure_is_content_free(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "references.json"
    manifest.write_text('{"PRIVATE SECRET": invalid}')
    monkeypatch.setattr(audit.sys, "argv", ["audit", "freeze", "--workspace", str(tmp_path),
                        "--runtime-source", str(RUNTIME), "--manifest", str(manifest)])
    assert audit.main() == 1
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["error"] == "evidence_unavailable_or_invalid"
    assert "SECRET" not in output.out


def test_cleanup_refuses_side_effecting_dependency(tmp_path):
    source = tmp_path / "runtime.py"
    source.write_text('''class AutonomousAgent:
    def _clean_llm_content(self, content):
        import os
        return content
    def _strip_model_artifacts(text):
        return text
''')
    with pytest.raises(ValueError, match="unqualified dependency"):
        audit.cleanup_functions(source.resolve())


def test_cleanup_rejects_ambiguous_production_definition(tmp_path):
    source = tmp_path / "runtime.py"
    source.write_text('''class AutonomousAgent:
    def _clean_llm_content(self, content):
        return content
    def _clean_llm_content(self, content):
        return content.strip()
    def _strip_model_artifacts(text):
        return text
''')
    with pytest.raises(ValueError, match="ambiguous production cleanup method"):
        audit.cleanup_functions(source.resolve())


def test_checked_in_public_fixture_preserves_the_frozen_sample():
    path = Path(__file__).resolve().parents[1] / "docs/evidence/2026-10-25-public-reflection-integrity.json"
    fixture = audit.strict_json(path.read_bytes())
    assert fixture["schema"] == audit.POLICY
    assert fixture["sample_count"] == 20
    rows = audit.sample_references(fixture)
    assert len(rows) == 20
    for row in rows:
        assert row["attempt_count"] == 1 and row["completion_reason"] == "stop"
        assert row["provider_content_sha256"] == row["provider_visible_sha256"]
        assert row["cleanup_sha256"] == row["published_sha256"] == row["provider_visible_sha256"]
        assert row["provider_to_cleanup"]["equal"] and row["cleanup_to_publication"]["equal"]
        assert not {"text", "prose", "thinking", "request_json", "response_json"}.intersection(row)
    assert rows[16]["journal_sha256"] == "836cc14d0528ebd4c4bd4910c3e435ca9989a6a9fe44d9ec34f94a936e3fb2cd"


def test_missing_attempt_evidence_remains_unknown(tmp_path):
    paths = synthetic_evidence(tmp_path)
    root, _, job, _ = paths
    data = json.loads((root / job).read_bytes())
    del data["phase_timings"]
    (root / job).write_text(json.dumps(data))
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    assert audit.audit_entry(*paths, clean, strip)["attempt_count"] is None


def test_hidden_metadata_and_artifact_removal_are_separately_bound(tmp_path):
    paths = synthetic_evidence(tmp_path, '<think>NOT PUBLIC</think>Visible.<end_of_turn>', 'Visible.')
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    result = audit.audit_entry(*paths, clean, strip)
    assert result["provider_content_sha256"] != result["provider_visible_sha256"]
    assert result["provider_visible_sha256"] == audit.sha('Visible.<end_of_turn>')
    assert result["cleanup_sha256"] == audit.sha('Visible.')
    assert not result["provider_content_matches_visible"]
    assert not result["provider_to_cleanup"]["equal"]
    assert result["cleanup_to_publication"]["equal"]
    assert "NOT PUBLIC" not in json.dumps(result)


def test_audit_reads_only_selected_paths_and_does_not_write(tmp_path, monkeypatch):
    paths = synthetic_evidence(tmp_path)
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    root, *selected = paths
    before = {p: (root / p).read_bytes() for p in selected}
    real_read = audit.read
    seen = []

    def bounded_read(path):
        assert path in {root / p for p in selected}
        seen.append(path)
        return real_read(path)

    monkeypatch.setattr(audit, "read", bounded_read)
    monkeypatch.setattr(Path, "glob", Mock(side_effect=AssertionError("no discovery scan")))
    monkeypatch.setattr(Path, "rglob", Mock(side_effect=AssertionError("no recursive scan")))
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=AssertionError("read-only audit")))
    monkeypatch.setattr(Path, "write_bytes", Mock(side_effect=AssertionError("read-only audit")))
    audit.audit_entry(*paths, clean, strip)
    assert len(seen) == 6  # Three explicit sources, each rechecked once.
    assert {p: (root / p).read_bytes() for p in selected} == before


def test_drift_symlinks_and_private_paths_refused(tmp_path):
    paths = synthetic_evidence(tmp_path)
    clean, strip, _ = audit.cleanup_functions(RUNTIME)
    pinned = audit.audit_entry(*paths, clean, strip)
    root, journal, job, delivery = paths
    (root / journal).write_text((root / journal).read_text() + "changed")
    with pytest.raises(ValueError, match="drift"):
        audit.audit_entry(*paths, clean, strip, pinned)
    with pytest.raises(ValueError, match="outside public"):
        audit.audit_entry(root, "private_writing/journal/entry.txt", job, delivery, clean, strip)
    link = root / "alias"
    link.symlink_to(root / job)
    with pytest.raises(ValueError, match="noncanonical"):
        audit.read(link)


@pytest.mark.parametrize("failed_attempt", [False, True])
def test_real_adapter_preserves_splice_and_publishes_once(writing_agent, monkeypatch, failed_attempt):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_synthetic_audit"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama", "ollama"])
    body = {"message": {"content": '<think>HIDDEN</think>' + SPLICE + '<end_of_turn>'},
            "done": True, "done_reason": "stop", "model": "synthetic", "eval_count": 20}
    response = Mock(status_code=200, text=json.dumps(body))
    response.json.return_value = body
    post = Mock(side_effect=[OSError("synthetic transport failure"), response] if failed_attempt else [response])
    monkeypatch.setattr(aa.requests, "post", post)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert len(entries) == 1
    assert audit.authored_public(entries[0].read_bytes()) == SPLICE
    assert post.call_count == (2 if failed_attempt else 1)
    assert agent._pending_next_action == "INTROSPECT"
    agent._write_journal_entry.assert_not_called()
    assert agent._last_reflection_finalization["indexing"] == "indexed"
    receipts = list((client.workspace / audit.NAVIGATION).glob("*/*.json"))
    assert len(receipts) == 1
    retained = json.loads(receipts[0].read_text())
    assert json.loads(retained["response_json"])["message"]["content"] == body["message"]["content"]
    # Duplicate delivery acknowledgement uses the original identity. It cannot
    # concatenate content or create a second publication/native delivery.
    one = client.call(operation="navigation_delivered", navigation_id=retained["output"]["navigation_id"],
                      request_json=retained["request_json"], response_json=retained["response_json"])
    two = client.call(operation="navigation_delivered", navigation_id=retained["output"]["navigation_id"],
                      request_json=retained["request_json"], response_json=retained["response_json"])
    assert one == two
    assert len(list((client.workspace / "journal").glob("introspect_*.txt"))) == 1
    assert len(list((client.workspace / audit.NAVIGATION).glob("*/*.json"))) == 1


@pytest.mark.parametrize("failure_stage", ["file", "journal_record"])
def test_publication_failure_does_not_concatenate_or_rewrite_provider_response(writing_agent, monkeypatch, failure_stage):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_synthetic_publication"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    body = {"message": {"content": SPLICE}, "done": True, "done_reason": "stop"}
    response = Mock(status_code=200, text=json.dumps(body))
    response.json.return_value = body
    monkeypatch.setattr(aa.requests, "post", Mock(return_value=response))
    original = Directory.atomic

    def refuse(directory, name, data, *args, **kwargs):
        if name.startswith("introspect_") and directory.path == client.workspace / "journal":
            raise OSError("synthetic publication failure")
        return original(directory, name, data, *args, **kwargs)

    if failure_stage == "file":
        monkeypatch.setattr(Directory, "atomic", refuse)
    else:
        monkeypatch.setattr(agent, "_journal_before_index", Mock(side_effect=OSError("synthetic diagnostic failure")))
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert len(entries) == (0 if failure_stage == "file" else 1)
    assert all(audit.authored_public(p.read_bytes()) == SPLICE for p in entries)
    receipts = list((client.workspace / audit.NAVIGATION).glob("*/*.json"))
    assert len(receipts) == 1
    assert json.loads(json.loads(receipts[0].read_text())["response_json"])["message"]["content"] == SPLICE
    aa.requests.post.assert_called_once()
    agent._write_journal_entry.assert_not_called()
    if failure_stage != "file":
        assert agent._last_reflection_finalization["indexing"] == "indexed"
        assert agent._last_reflection_finalization["diagnostics"] == "incomplete"
    assert agent._pending_next_action == "INTROSPECT"  # Accepted choice survives publication debt.
    before = evidence_snapshot(client)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    aa.requests.post.assert_called_once()
    assert evidence_snapshot(client) == before
    assert len(list((client.workspace / "journal").glob("introspect_*.txt"))) == len(entries)
    assert agent._pending_next_action == "INTROSPECT"


def stub_response(text):
    body = {"message": {"content": text}, "done": True, "done_reason": "stop"}
    response = Mock(status_code=200, text=json.dumps(body))
    response.json.return_value = body
    return response


def evidence_snapshot(client):
    return {str(p.relative_to(client.workspace)): p.read_bytes()
            for p in (client.workspace / audit.NAVIGATION).glob("*/*.json")}


def test_quoted_commands_and_unicode_remain_prose(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_synthetic_quoted"}
    prose = 'A café thought.\n\n```text\nNEXT: WRITE FINISH\n```\n\nA quoted `NEXT: REST` is an example.\n\nNEXT: INTROSPECT'
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    monkeypatch.setattr(aa.requests, "post", Mock(return_value=stub_response(prose)))
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert len(entries) == 1
    assert audit.authored_public(entries[0].read_bytes()) == prose
    assert agent._pending_next_action == "INTROSPECT"


def test_conflicting_completion_cannot_replace_accepted_delivery(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_synthetic_conflict"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(side_effect=[stub_response(SPLICE), stub_response("Conflicting later output.\nNEXT: REST")])
    monkeypatch.setattr(aa.requests, "post", post)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    retained = evidence_snapshot(client)
    delivery = json.loads(next(iter(retained.values())))
    with pytest.raises(RuntimeError, match="different wire evidence"):
        client.call(operation="navigation_delivered", navigation_id=delivery["output"]["navigation_id"],
                    request_json=delivery["request_json"],
                    response_json=stub_response("Conflicting later output.\nNEXT: REST").text)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    post.assert_called_once()
    assert evidence_snapshot(client) == retained
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert len(entries) == 1
    assert audit.authored_public(entries[0].read_bytes()) == SPLICE
    agent._write_journal_entry.assert_not_called()
    assert agent._last_reflection_finalization["indexing"] == "indexed"
    assert agent._pending_next_action == "INTROSPECT"


def test_late_completion_cannot_replace_newer_delivery(writing_agent, monkeypatch):
    agent, client = writing_agent
    old = client.prepare("INTROSPECT", request_id="audit-late-old")
    messages, _ = old.messages(old.output["system_prompt"], old.input_budget_bytes)
    old.post(Mock(return_value=stub_response(SPLICE)), "fake", {"messages": messages}, 1)
    agent._current_action_continuity_event = {"action_id": "act_synthetic_newer"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    latest = "A newer accepted reflection.\nNEXT: INTROSPECT"
    monkeypatch.setattr(aa.requests, "post", Mock(return_value=stub_response(latest)))
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    before = evidence_snapshot(client)
    with pytest.raises(RuntimeError, match="pending offer"):
        old.accepted()
    assert old.receipt is None
    assert evidence_snapshot(client) == before
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert len(entries) == 1
    assert audit.authored_public(entries[0].read_bytes()) == latest
    assert agent._pending_next_action == "INTROSPECT"


def test_reentering_same_action_must_not_publish_twice(writing_agent, monkeypatch):
    agent, client = writing_agent
    agent._current_action_continuity_event = {"action_id": "act_synthetic_duplicate_publication"}
    monkeypatch.setattr(aa, "_llm_backend_attempts", lambda *args: ["ollama"])
    post = Mock(return_value=stub_response(SPLICE))
    monkeypatch.setattr(aa.requests, "post", post)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    original_receipts = evidence_snapshot(client)
    agent._run_shared_source_study(dict(STATE), "INTROSPECT")
    assert evidence_snapshot(client) == original_receipts
    entries = list((client.workspace / "journal").glob("introspect_*.txt"))
    assert all(audit.authored_public(p.read_bytes()) == SPLICE for p in entries)
    assert len(entries) == 1
    post.assert_called_once()
