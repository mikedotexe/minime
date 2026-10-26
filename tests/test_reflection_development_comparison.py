"""Synthetic public records; only the explicitly selected helper may execute."""
from collections import Counter
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import reflection_development_comparison as d
from scripts import reflection_comparison as base
from tests.test_reflection_comparison import assets as base_assets, execution  # noqa: F401


@pytest.fixture(autouse=True)
def no_provider_or_network(monkeypatch, request):
    run = subprocess.run

    def guarded_run(command, **kwargs):
        if request.node.name != "test_real_helper_exact_native_preparation":
            raise AssertionError("unmocked process execution")
        helper = os.environ.get("ASTRID_SOURCE_STUDY_BIN")
        assert command == ["/usr/bin/sandbox-exec", "-f", str(Path(kwargs["cwd"]) / "helper.sb"), helper]
        assert "(allow network" not in Path(command[2]).read_text()
        return run(command, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("unmocked provider, signal or network operation")

    monkeypatch.setattr(base.subprocess, "run", guarded_run)
    # subprocess.run uses Popen internally for the real-helper test only.
    if request.node.name != "test_real_helper_exact_native_preparation":
        monkeypatch.setattr(base.subprocess, "Popen", forbidden)
    monkeypatch.setattr(base.subprocess, "check_output", forbidden)
    monkeypatch.setattr(base.socket, "socket", forbidden)
    monkeypatch.setattr(base.os, "killpg", forbidden)
    monkeypatch.setattr(base, "HTTPConnection", forbidden)


def public_bytes(passage, *, header_extra=""):
    return ("=== INTROSPECTION: open reflection ===\n"
            "Delivery: verified input delivery; claims unverified\n"
            + header_extra + "\nUnselected opening: caf\u00e9.\n\n" + passage
            + "\n\nUnselected ending.\n\nNEXT: REST\n").encode()


def synthetic_native(helper, root, passage):
    root.mkdir()
    frame = {"input_kind": "reflection", "system_prompt": "Unchanged fresh system",
             "text": "Unchanged fresh invitation; WRITE FROM_REFLECTION synthetic-reflection",
             "navigation_id": "synthetic-reflection", "input_budget_bytes": 48000,
             "context_tokens": 65536, "evidence_scope": "Presentation: fresh-reflection-v2."}
    command = f"WRITE FROM_REFLECTION synthetic-reflection 0 {len(passage.encode())}"
    writing = {"input_kind": "private_writing", "system_prompt": "Native writing system",
               "text": "Selected writing profile: Default; output ceiling: 8192 tokens, no minimum.\n"
                       + "Complete current draft:\n" + passage + "\nEnd of retained draft context.",
               "input_budget_bytes": 48000, "context_tokens": 65536}
    fixture = {"experimental_stub": True, "native_command": command,
               "delivery": {"synthetic": True}, "selected_passage_sha256": base.digest(passage.encode()),
               "stub_passage_utf8_bytes": [0, len(passage.encode())],
               "native_limits": d.native_limits(frame, writing), "fresh": frame, "writing": writing}
    base.save(root / "synthetic-operation.json", fixture)
    return frame, writing, fixture


@pytest.fixture
def assets(base_assets, monkeypatch):
    provider = base_assets.root / "provider-runtime" / "Resources" / "ollama"
    provider.parent.mkdir(parents=True)
    base.save_bytes(provider, b"synthetic provider, not executable")
    base_assets.provider = provider
    journal = base_assets.root / "synthetic-public-journal"
    journal.mkdir()
    for selection in d.SELECTIONS:
        passage = selection["start"] + "\n\nSynthetic distinction: caf\u00e9, \u03bb, \u6c34.\n\n" + selection["end"]
        base.save_bytes(journal / selection["filename"], public_bytes(passage))
    base_assets.journal = journal
    monkeypatch.setattr(d, "helper_inputs", synthetic_native)
    return base_assets


def freeze(assets, name="development-packet"):
    out = assets.root / name
    packet = d.freeze(assets.new, assets.models, assets.provider, assets.journal, out)
    return out, packet, base.file_hash(out / "packet.json")


def rewrite_packet(out, packet):
    (out / "packet.json").write_bytes(base.encoded(packet))
    sha = base.file_hash(out / "packet.json")
    (out / "packet.sha256").write_text(sha + "\n")
    return sha


def test_exact_schedule_matched_anchors_and_repeat_controls():
    jobs = d.schedule()
    assert len(jobs) == 24 and len({j["id"] for j in jobs}) == len({j["blind_id"] for j in jobs}) == 24
    assert Counter(j["cell"] for j in jobs) == {0: 8, 1: 8, 2: 8}
    for block, seed in enumerate([7, 17, 29, 43, 61, 79, 97]):
        rows = jobs[block * 3:block * 3 + 3]
        assert [j["cell"] for j in rows] == [block % 3, (block + 1) % 3, (block + 2) % 3]
        assert all(j["seed"] == seed and j["anchor"] == block % 2 and not j["repeat"] for j in rows)
    assert [j["cell"] for j in jobs[21:]] == [2, 0, 1]
    assert all(j["repeat"] and j["anchor"] == 0 and j["seed"] == 7 for j in jobs[21:])
    assert d.schedule() == jobs


def test_exact_utf8_selection_is_only_authored_prose(assets):
    selection = d.SELECTIONS[0]
    path = assets.journal / selection["filename"]
    result = d.select_excerpt(path, selection)
    raw = path.read_bytes()
    start, end = result["source_utf8_bytes"]
    assert raw[start:end].decode() == result["passage"]
    assert len(raw[:start].decode()) < start  # Multi-byte text before the selection.
    assert "caf\u00e9, \u03bb, \u6c34" in result["passage"]
    assert "Unselected" not in result["passage"] and "NEXT: REST" not in result["passage"]
    assert result["source_sha256"] == base.digest(raw)
    # A matching marker only in the wrapper cannot become selected prose.
    altered = public_bytes(selection["end"], header_extra=selection["start"] + "\n")
    with pytest.raises(ValueError, match="boundaries"):
        d.select_excerpt_bytes(altered, selection)
    with pytest.raises(ValueError, match="boundaries"):
        d.select_excerpt_bytes(public_bytes(result["passage"] * 2), selection)
    with pytest.raises(ValueError, match="filename"):
        d.select_excerpt(path, d.SELECTIONS[1])


@pytest.mark.parametrize("raw", [b"Private draft\n\nnot a public record\n", b"=== RUNTIME NOTICE ===\n\nnotice\n",
                                public_bytes("synthetic")[:-1], b"\xff"])
def test_ambiguous_or_nonpublic_sources_fail_closed(raw):
    with pytest.raises((ValueError, UnicodeError)):
        d.select_excerpt_bytes(raw, d.SELECTIONS[0])


def test_freeze_load_exact_inputs_immutable_fixtures_and_native_limits(assets):
    out, packet, sha = freeze(assets)
    assert d.load_packet(out, sha) == packet
    assert packet["schema"] == d.POLICY != base.POLICY
    assert len(packet["helpers"]) == 1
    assert packet["selection_implementation_sha256"] == base.file_hash(Path(d.public_audit.__file__))
    for index, anchor in enumerate(packet["anchors"]):
        assert (out / f"public-source-{index}.txt").read_bytes() == (assets.journal / anchor["filename"]).read_bytes()
        native = base.read_json(out / f"native-fixture-{index}.json")
        assert native["experimental_stub"] is True
        assert native["native_limits"]["writing_output_tokens"] == 8192
        assert native["native_limits"]["writing_input_bytes"] == 48000
        assert packet["cells"][2]["messages_by_anchor"][index][1]["content"] == native["writing"]["text"]
        assert native["native_command"].endswith(f"0 {len(anchor['passage'].encode())}")
    for job in packet["jobs"]:
        request = d.request_for(packet, job)
        assert request["think"] is False and request["stream"] is False and request["keep_alive"] == 0
        assert request["options"] == {"temperature": .7, "top_p": .95, "num_predict": 4096,
                                      "num_ctx": 65536, "seed": job["seed"]}
    for cell in range(3):
        pair = [d.request_for(packet, j) for j in packet["jobs"] if j["cell"] == cell and j["seed"] == 7]
        assert len(pair) == 2 and pair[0] == pair[1]
    original = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        freeze(assets)
    assert {p: p.read_bytes() for p in original} == original
    # Once frozen, live public file changes cannot become implicit new inputs.
    (assets.journal / d.SELECTIONS[0]["filename"]).write_bytes(b"changed source")
    assert d.load_packet(out, sha) == packet


@pytest.mark.parametrize("kind", ["helper", "provider", "manifest", "blob", "public-source", "native-fixture",
                                 "helper-state", "rubric", "runtime-added"])
def test_asset_and_fixture_drift_refused(assets, kind):
    out, packet, sha = freeze(assets)
    path = {"helper": assets.new, "provider": assets.provider, "manifest": assets.models / base.MANIFEST,
            "blob": assets.models / "blobs" / next(iter(packet["model_blobs"])),
            "public-source": out / "public-source-0.txt", "native-fixture": out / "native-fixture-0.json",
            "helper-state": out / "synthetic-helper-0/synthetic-operation.json", "rubric": out / "rubric.md",
            "runtime-added": assets.provider.parent / "new-library"}[kind]
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        d.load_packet(out, sha)


@pytest.mark.parametrize("key,value", [("schema", base.POLICY), ("model", "other"), ("think", True),
                                      ("seeds", [7]), ("jobs", []), ("cells", []), ("options", {})])
def test_altered_design_refused(assets, key, value):
    _, packet, _ = freeze(assets)
    packet[key] = value
    with pytest.raises(ValueError):
        d.validate_design(packet)


@pytest.mark.parametrize("kind", ["path", "source", "native", "fresh", "limits"])
def test_resealed_inconsistent_fixture_refused(assets, kind):
    out, packet, _ = freeze(assets)
    if kind == "path":
        packet["fixtures"]["../outside"] = "0" * 64
    elif kind == "source":
        packet["anchors"][0]["source_sha256"] = "0" * 64
    elif kind == "fresh":
        for cell in packet["cells"][:2]:
            for messages in cell["messages_by_anchor"]:
                messages[0]["content"] = "Changed fresh system"
    else:
        name = "native-fixture-0.json"
        native = base.read_json(out / name)
        if kind == "native":
            native["native_command"] = "WRITE START something else"
        else:
            native["native_limits"]["writing_output_tokens"] = 16384
        (out / name).write_bytes(base.encoded(native))
        packet["fixtures"][name] = base.file_hash(out / name)
    packet["cell_sha256"] = [base.digest(base.encoded(c)) for c in packet["cells"]]
    sha = rewrite_packet(out, packet)
    with pytest.raises(ValueError):
        d.load_packet(out, sha)


def test_wrong_digest_and_symlinked_fixture_refused(assets):
    out, _, sha = freeze(assets)
    with pytest.raises(ValueError, match="pinned digest"):
        d.load_packet(out, "0" * 64)
    path = out / "native-fixture-0.json"
    copy_path = out / "copy.json"
    copy_path.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy_path)
    with pytest.raises(ValueError):
        d.load_packet(out, sha)


def test_helper_changed_during_freeze_preserves_failed_attempt(assets, monkeypatch):
    def drifting(helper, root, passage):
        result = synthetic_native(helper, root, passage)
        helper.write_bytes(b"changed helper implementation")
        return result
    monkeypatch.setattr(d, "helper_inputs", drifting)
    with pytest.raises(ValueError, match="identity changed"):
        freeze(assets)
    out = assets.root / "development-packet"
    assert (out / "native-fixture-0.json").exists() and not (out / "packet.json").exists()
    with pytest.raises(FileExistsError):
        freeze(assets)


def test_validate_cli_is_read_only_and_never_executes(assets, monkeypatch, capsys):
    out, packet, sha = freeze(assets)
    before = {str(p): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    monkeypatch.setattr("sys.argv", ["reflection_development_comparison.py", "validate", "--packet-dir", str(out),
                                     "--packet-sha256", sha])
    d.main()
    assert json.loads(capsys.readouterr().out) == {
        "schema": packet["schema"], "packet_sha256": sha, "planned_completions": 24, "valid": True}
    assert before == {str(p): p.read_bytes() for p in out.rglob("*") if p.is_file()}


def test_shared_executor_runs_exactly_24_inert_requests_and_three_repeats(assets, execution):
    out, packet, sha = freeze(assets)
    execution.outcome = lambda: {"model": base.MODEL, "done": True, "done_reason": "stop", "eval_count": 15,
                               "message": {"role": "assistant", "content": "Synthetic continuation.\nNEXT: REST"}}
    base.execute(out, sha, packet_loader=d.load_packet, request_builder=d.request_for)
    assert execution.calls == [d.request_for(packet, j) for j in packet["jobs"]]
    assert execution.stops == [execution.process.pid]
    summary = base.read_json(out / "summary.json")
    assert summary["schema"] == d.POLICY and summary["completed"] == 24
    assert len(summary["seed_repeats"]) == 3
    assert all(r["nonempty_exact_text_match"] for r in summary["seed_repeats"])
    review = base.read_json(out / "blind-review.json")
    assert [r["id"] for r in review] == [f"sample-{i:02d}" for i in range(1, 25)]
    assert all("cell" not in r and "anchor" not in r and "seed" not in r and r["text"].endswith("NEXT: REST") for r in review)
    assert not (out / "journal").exists()
    assert base.read_json(out / "resource-receipt.json")["owned_group_empty"] is True
    with pytest.raises(ValueError, match="already attempted"):
        base.execute(out, sha, packet_loader=d.load_packet, request_builder=d.request_for)


def test_low_headroom_never_launches_provider(assets, execution, monkeypatch):
    out, _, sha = freeze(assets)
    monkeypatch.setattr(base, "free_percent", lambda: 19)
    with pytest.raises(RuntimeError, match="headroom"):
        base.execute(out, sha, packet_loader=d.load_packet, request_builder=d.request_for)
    assert not execution.calls and not execution.stops and not (out / "execution.json").exists()


def test_executor_rejects_nonidentical_repeat_pair(assets, execution):
    out, _, sha = freeze(assets)
    def altered(packet, job):
        request = copy.deepcopy(d.request_for(packet, job))
        if job["repeat"]:
            request["messages"][1]["content"] += "changed repeat"
        return request
    with pytest.raises(ValueError, match="repeat control"):
        base.execute(out, sha, packet_loader=d.load_packet, request_builder=altered)
    assert execution.stops and not (out / "summary.json").exists()
    assert base.read_json(out / "failure.json")["attempted"] == 24


def test_prior_four_cell_defaults_remain_compatible(base_assets, execution):
    out = base_assets.root / "prior-four-cell"
    packet = base.freeze(base_assets.old, base_assets.new, base_assets.models, base_assets.provider, out)
    sha = base.file_hash(out / "packet.json")
    assert len(packet["helpers"]) == 2 and len(packet["cells"]) == 4
    base.execute(out, sha)
    summary = base.read_json(out / "summary.json")
    assert summary["schema"] == base.POLICY and len(summary["seed_repeats"]) == 4
    assert execution.calls == [base.request_for(packet, j) for j in base.schedule()]
    with pytest.raises(ValueError, match="frozen schema"):
        d.load_packet(out, sha)


def test_real_helper_exact_native_preparation(tmp_path):
    configured = os.environ.get("ASTRID_SOURCE_STUDY_BIN")
    if not configured or not Path(configured).is_file():
        pytest.skip("explicit qualified helper required; no build or runtime fallback")
    root = tmp_path.resolve() / "isolated-native-fixture"
    passage = 'An exact synthetic thought: caf\u00e9, \u03bb, \u6c34.\n\n"NEXT: REST" remains quoted prose.'
    frame, writing, fixture = d.helper_inputs(Path(configured), root, passage)
    assert frame["input_kind"] == "reflection" and writing["input_kind"] == "private_writing"
    assert fixture["stub_passage_utf8_bytes"] == [0, len(passage.encode())]
    assert fixture["experimental_stub"] is True and fixture["native_limits"]["writing_output_tokens"] == 8192
    # The helper omits the default-true field. This is only a preparation.
    assert writing.get("generation_requested", True) is True
    assert f"Complete current draft:\n{passage}\nEnd of retained draft context" in writing["text"]
    operations = [base.read_json(path) for path in sorted(root.glob("operation-*.json"))]
    assert [r["request"]["operation"] for r in operations] == [
        "preparation_revision", "prepare_once", "navigation_delivered", "preparation_revision", "prepare_once"]
    wire = json.loads(operations[2]["request"]["response_json"])
    assert wire["message"]["content"] == passage and wire["model"] == "synthetic-public-delivery"
    assert operations[-1]["request"]["action"] == fixture["native_command"]
    assert all(r["experimental_stub"] and r["returncode"] == 0 for r in operations)
