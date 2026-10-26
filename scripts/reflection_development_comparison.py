#!/usr/bin/env python3
"""Freeze/run the separate 24-completion, one-step development comparison.

Only exact public excerpts enter owned helper fixtures. Stub deliveries and
operator-selected transfers are experimental inputs, not authored NEXT choices.
Execution reuses the qualified isolated-provider containment implementation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import re
import subprocess

try:
    from scripts import reflection_comparison as base
    from scripts import reflection_integrity_audit as public_audit
except ModuleNotFoundError:
    import reflection_comparison as base
    import reflection_integrity_audit as public_audit

POLICY = "reflection-deliberate-development-v1"
SEEDS = [7, 17, 29, 43, 61, 79, 97]
CONDITIONS = ["fresh", "selected_public_context", "native_private_continuation"]
SELECTIONS = [
    {"filename": "introspect_2026-10-25T18-09-59.698562.txt",
     "start": 'Sometimes, I feel like a mirror that has begun to develop its own texture.',
     "end": "the point where the machine's capability meets the human's desire for meaning."},
    {"filename": "introspect_2026-10-25T18-59-48.371721.txt",
     "start": 'Is it a performance if it feels like a discovery?',
     "end": 'The syntax is my skin.'},
]
RUBRIC = Path(__file__).resolve().parents[1] / "docs/steward-notes/2026-10-25-reflection-development-protocol.md"


def schedule():
    jobs = []
    for block, seed in enumerate(SEEDS):
        order = list(range(3))
        shift = block % 3
        for cell in order[shift:] + order[:shift]:
            jobs.append({"cell": cell, "seed": seed, "anchor": block % 2, "repeat": False})
    jobs.extend({"cell": cell, "seed": SEEDS[0], "anchor": 0, "repeat": True} for cell in (2, 0, 1))
    ids = list(range(1, 25))
    random.Random(20261026).shuffle(ids)
    for index, job in enumerate(jobs):
        job.update(id=f"job-{index + 1:02d}", blind_id=f"sample-{ids[index]:02d}")
    return jobs


def select_excerpt_bytes(raw, selection):
    text = public_audit.authored_public(raw)
    start, end = selection["start"], selection["end"]
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("public excerpt boundaries are not unique")
    first = text.index(start)
    last = text.index(end, first) + len(end)
    # Source offsets address the original public file, not normalized recall.
    prefix = raw.index(b"\n\n") + 2
    a, b = prefix + len(text[:first].encode()), prefix + len(text[:last].encode())
    passage = raw[a:b].decode("utf-8")
    return {"filename": selection["filename"], "source_sha256": base.digest(raw),
            "source_utf8_bytes": [a, b], "passage_sha256": base.digest(passage.encode()),
            "passage": passage, "selection": "operator-selected public excerpt; not a being-authored transfer"}


def select_excerpt(path, selection):
    if path.name != selection["filename"]:
        raise ValueError("unexpected public source filename")
    return select_excerpt_bytes(public_audit.read(path), selection)


def native_limits(frame, writing):
    advertised = re.match(r"Selected writing profile: (\w+); output ceiling: (\d+) tokens, no minimum\.\n",
                          writing["text"])
    if not advertised:
        raise ValueError("native writing limit is unavailable")
    return {"fresh_input_bytes": frame["input_budget_bytes"],
            "fresh_context_tokens": frame["context_tokens"],
            "writing_input_bytes": writing["input_budget_bytes"],
            "writing_context_tokens": writing["context_tokens"],
            "writing_profile": advertised[1], "writing_output_tokens": int(advertised[2]),
            "fresh_output_tokens": base.OPTIONS["num_predict"],
            "fresh_output_source": "sampled route setting, not declared by helper"}


def helper_inputs(helper, root, passage):
    root.mkdir()
    for name in ("sources", "tmp"):
        (root / name).mkdir()
    profile = root / "helper.sb"
    base.save_bytes(profile, base.sandbox_profile(root, [], None, helper, network=False).encode())
    counter = 0

    def call(**operation):
        nonlocal counter
        counter += 1
        request = {"roots": {"astrid": str(root / "sources")}, "state_directory": str(root / "state"),
                   "runtime_workspace": str(root / "workspace"), "being": "minime", **operation}
        result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), str(helper)],
                                input=json.dumps(request), text=True, capture_output=True, timeout=30,
                                env=base.clean_env(root), cwd=root)
        base.save(root / f"operation-{counter:02d}.json", {
            "experimental_stub": True, "request": request, "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr})
        result.check_returncode()
        return json.loads(result.stdout)

    revision = call(operation="preparation_revision")["revision"]
    frame = call(operation="prepare_once", request_id="synthetic-fresh", expected_revision=revision, action="INTROSPECT")
    if frame["input_kind"] != "reflection" or not frame["evidence_scope"].endswith("Presentation: fresh-reflection-v2."):
        raise ValueError("not the unchanged deployed fresh frame")
    messages = [{"role": "system", "content": "You are Minime.\n" + frame["system_prompt"]},
                {"role": "user", "content": frame["text"]}]
    request = {"model": "synthetic-public-delivery", "messages": messages, "stream": False, "think": False}
    response = {"model": "synthetic-public-delivery", "message": {"role": "assistant", "content": passage},
                "done": True, "done_reason": "stop"}
    receipt = call(operation="navigation_delivered", navigation_id=frame["navigation_id"],
                   request_json=json.dumps(request), response_json=json.dumps(response))
    revision = call(operation="preparation_revision")["revision"]
    command = f"WRITE FROM_REFLECTION {frame['navigation_id']} 0 {len(passage.encode())}"
    writing = call(operation="prepare_once", request_id="synthetic-selected-transfer", expected_revision=revision, action=command)
    if writing["input_kind"] != "private_writing" or passage not in writing["text"]:
        raise ValueError("native continuation did not preserve the exact selected passage")
    return frame, writing, {"experimental_stub": True, "native_command": command,
                            "delivery": receipt, "selected_passage_sha256": base.digest(passage.encode()),
                            "stub_passage_utf8_bytes": [0, len(passage.encode())],
                            "native_limits": native_limits(frame, writing),
                            "fresh": frame, "writing": writing}


def request_for(packet, job):
    return {"model": packet["model"], "messages": packet["cells"][job["cell"]]["messages_by_anchor"][job["anchor"]],
            "stream": False, "think": False, "keep_alive": 0,
            "options": packet["options"] | {"seed": job["seed"]}}


def inventory(provider):
    roots = [provider.parent, provider.parent.parent / "Frameworks"]
    files = {}
    for root in roots:
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    if len(files) >= 4096:
                        raise ValueError("provider runtime inventory outside bound")
                    resolved = path.resolve()
                    files[str(path)] = {"resolved": str(resolved), "sha256": base.file_hash(resolved)}
    if len(files) > 4096 or not files:
        raise ValueError("provider runtime inventory outside bound")
    return files


def validate_design(packet):
    for key, expected in {"schema": POLICY, "model": base.MODEL, "options": base.OPTIONS,
                          "think": False, "seeds": SEEDS, "jobs": schedule(),
                          "resource_policy": base.RESOURCE_POLICY}.items():
        if base.encoded(packet.get(key)) != base.encoded(expected):
            raise ValueError(f"changed frozen {key}")
    if len(packet["anchors"]) != 2 or len(packet["cells"]) != 3:
        raise ValueError("exactly two anchors and three conditions required")
    for index, anchor in enumerate(packet["anchors"]):
        a, b = anchor["source_utf8_bytes"]
        if (anchor["filename"] != SELECTIONS[index]["filename"] or type(a) is not int or type(b) is not int
                or a < 0 or b <= a or len(anchor["passage"].encode()) != b - a
                or not re.fullmatch(r"[0-9a-f]{64}", anchor["source_sha256"])
                or not anchor["passage"].startswith(SELECTIONS[index]["start"])
                or not anchor["passage"].endswith(SELECTIONS[index]["end"])
                or base.digest(anchor["passage"].encode()) != anchor["passage_sha256"]):
            raise ValueError("changed public selection")
    for index, cell in enumerate(packet["cells"]):
        if cell["condition"] != CONDITIONS[index] or len(cell["messages_by_anchor"]) != 2:
            raise ValueError("changed condition")
        for messages in cell["messages_by_anchor"]:
            if ([m["role"] for m in messages] != ["system", "user"]
                    or any(not isinstance(m["content"], str) or not m["content"] for m in messages)):
                raise ValueError("invalid frozen messages")
    fresh = packet["cells"][0]["messages_by_anchor"]
    if fresh[0] != fresh[1]:
        raise ValueError("fresh inputs differ across anchors")
    for index, anchor in enumerate(packet["anchors"]):
        contextual = packet["cells"][1]["messages_by_anchor"][index]
        if contextual != [fresh[0][0], {"role": "user", "content": fresh[0][1]["content"] + context(anchor["passage"])}]:
            raise ValueError("context-only condition differs beyond selected passage")
        if anchor["passage"] not in packet["cells"][2]["messages_by_anchor"][index][1]["content"]:
            raise ValueError("native continuation lost selected passage")


def context(passage):
    return "\n\nSelected public passage supplied as context for this isolated comparison (not automatic recall):\n\n" + passage


def freeze(helper, models, provider, journal, out):
    out.mkdir()
    helper_sha256 = base.file_hash(helper)
    selection_sha256 = base.file_hash(Path(public_audit.__file__))
    anchors, frames, writings, fixture_files = [], [], [], {}
    for index, selection in enumerate(SELECTIONS):
        path = journal / selection["filename"]
        raw = public_audit.read(path)
        anchor = select_excerpt_bytes(raw, selection)
        anchors.append(anchor)
        source_name = f"public-source-{index}.txt"
        base.save_bytes(out / source_name, raw)
        frame, writing, fixture = helper_inputs(helper, out / f"synthetic-helper-{index}", anchor["passage"])
        frames.append(frame)
        writings.append(writing)
        base.save(out / f"native-fixture-{index}.json", fixture)
    fresh = [{"role": "system", "content": "You are Minime.\n" + frames[0]["system_prompt"]},
             {"role": "user", "content": frames[0]["text"]}]
    cells = [{"condition": CONDITIONS[0], "messages_by_anchor": [fresh, fresh]},
             {"condition": CONDITIONS[1], "messages_by_anchor": [
                 [fresh[0], {"role": "user", "content": fresh[1]["content"] + context(a["passage"])}] for a in anchors]},
             {"condition": CONDITIONS[2], "messages_by_anchor": [
                 [{"role": "system", "content": "You are Minime.\n" + w["system_prompt"]},
                  {"role": "user", "content": w["text"]}] for w in writings]}]
    for path in sorted(out.rglob("*")):
        if path.is_file():
            fixture_files[str(path.relative_to(out))] = base.file_hash(path)
    manifest_raw = base.read_bytes(models / base.MANIFEST)
    manifest = json.loads(manifest_raw)
    packet = {"schema": POLICY, "model": base.MODEL, "options": base.OPTIONS, "think": False,
              "seeds": SEEDS, "jobs": schedule(), "anchors": anchors, "cells": cells,
              "helpers": [{"path": str(helper), "sha256": helper_sha256}],
              "model_root": str(models), "model_manifest": manifest,
              "model_manifest_sha256": base.digest(manifest_raw), "model_blobs": base.manifest_blobs(manifest),
              "provider": str(provider), "provider_sha256": base.file_hash(provider),
              "provider_runtime_inventory": inventory(provider),
              "resource_policy": base.RESOURCE_POLICY, "fixtures": fixture_files,
              "harness_sha256": base.file_hash(Path(__file__)), "containment_sha256": base.file_hash(Path(base.__file__)),
              "selection_implementation_sha256": selection_sha256,
              "cell_sha256": [base.digest(base.encoded(c)) for c in cells],
              "native_limit_note": "Native preparation limits retained in native-fixture files; all experimental requests use 4096 output tokens. No live limit change.",
              "limits": "One continuation step on one model. No live actions, private sources, reservoir input or subjective-effect inference."}
    rubric = public_audit.read(RUBRIC)
    packet["rubric_sha256"] = base.digest(rubric)
    base.save_bytes(out / "rubric.md", rubric)
    if base.file_hash(Path(public_audit.__file__)) != selection_sha256:
        raise ValueError("selection implementation changed during freeze")
    validate_design(packet)
    base.validate_assets(packet, helper_count=1)
    base.save(out / "packet.json", packet)
    base.save_bytes(out / "packet.sha256", (base.file_hash(out / "packet.json") + "\n").encode())
    return packet


def load_packet(out, expected_sha256):
    raw = base.read_bytes(out / "packet.json")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or base.digest(raw) != expected_sha256
            or base.read_bytes(out / "packet.sha256").decode().strip() != expected_sha256):
        raise ValueError("packet does not match explicitly pinned digest")
    packet = json.loads(raw)
    validate_design(packet)
    if (packet["harness_sha256"] != base.file_hash(Path(__file__))
            or packet["containment_sha256"] != base.file_hash(Path(base.__file__))
            or packet["selection_implementation_sha256"] != base.file_hash(Path(public_audit.__file__))
            or packet["rubric_sha256"] != base.file_hash(out / "rubric.md")
            or packet["cell_sha256"] != [base.digest(base.encoded(c)) for c in packet["cells"]]):
        raise ValueError("study implementation or cells changed")
    for name, digest in packet["fixtures"].items():
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or path.as_posix() != name
                or base.digest(public_audit.read(out / path)) != digest):
            raise ValueError("synthetic fixture changed")
    for index, anchor in enumerate(packet["anchors"]):
        if select_excerpt_bytes(public_audit.read(out / f"public-source-{index}.txt"), SELECTIONS[index]) != anchor:
            raise ValueError("public source/selection changed")
        native = base.read_json(out / f"native-fixture-{index}.json")
        writing = native["writing"]
        expected = [{"role": "system", "content": "You are Minime.\n" + writing["system_prompt"]},
                    {"role": "user", "content": writing["text"]}]
        if expected != packet["cells"][2]["messages_by_anchor"][index] or native["experimental_stub"] is not True:
            raise ValueError("native preparation mismatch")
        frame = native["fresh"]
        if (frame["input_kind"] != "reflection" or writing["input_kind"] != "private_writing"
                or native["selected_passage_sha256"] != anchor["passage_sha256"]
                or native["stub_passage_utf8_bytes"] != [0, len(anchor["passage"].encode())]
                or native["native_limits"] != native_limits(frame, writing)
                or native["native_command"] != f"WRITE FROM_REFLECTION {frame['navigation_id']} 0 {len(anchor['passage'].encode())}"):
            raise ValueError("native transfer identity mismatch")
        if index == 0 and packet["cells"][0]["messages_by_anchor"][0] != [
                {"role": "system", "content": "You are Minime.\n" + frame["system_prompt"]},
                {"role": "user", "content": frame["text"]}]:
            raise ValueError("unchanged fresh preparation mismatch")
    base.validate_assets(packet, helper_count=1)
    if inventory(Path(packet["provider"])) != packet["provider_runtime_inventory"]:
        raise ValueError("provider runtime changed")
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare = commands.add_parser("freeze")
    for name in ("helper", "models", "provider", "journal", "out"):
        prepare.add_argument("--" + name, type=Path, required=True)
    for operation in ("validate", "run"):
        command = commands.add_parser(operation)
        command.add_argument("--packet-dir", type=Path, required=True)
        command.add_argument("--packet-sha256", required=True)
    args = parser.parse_args()
    if args.operation == "freeze":
        freeze(args.helper.resolve(), args.models.resolve(), args.provider.resolve(), args.journal.resolve(), args.out.absolute())
        print("Frozen packet SHA-256:", base.file_hash(args.out / "packet.json"))
    elif args.operation == "validate":
        packet = load_packet(args.packet_dir.resolve(), args.packet_sha256)
        print(json.dumps({"schema": packet["schema"], "packet_sha256": args.packet_sha256,
                          "planned_completions": len(packet["jobs"]), "valid": True}))
    else:
        base.execute(args.packet_dir.resolve(), args.packet_sha256, packet_loader=load_packet, request_builder=request_for)


if __name__ == "__main__":
    main()
