#!/usr/bin/env python3
"""Read-only public-reflection integrity audit; JSON output, never runtime writes.

Freeze its stdout in an operator-owned evidence directory. The audit executes
the two production cleanup method bodies without importing/initializing the
runtime. No model call, action dispatch, private-store traversal or prose output.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Optional


POLICY = "public-reflection-integrity-v1"
MAX_BYTES = 16 * 1024 * 1024
SAMPLE = [
    ("18-05-41.876951", "1792976699539"), ("18-09-59.698562", "1792976900078"),
    ("18-14-25.457483", "1792977186222"), ("18-19-28.641902", "1792977488835"),
    ("18-24-47.043832", "1792977790416"), ("18-29-33.499183", "1792978094383"),
    ("18-36-08.010440", "1792978445996"), ("18-40-34.481280", "1792978754723"),
    ("18-45-33.032591", "1792979051002"), ("18-50-43.489988", "1792979351790"),
    ("18-54-56.161059", "1792979622021"), ("18-59-48.371721", "1792979904758"),
    ("19-04-48.122520", "1792980187869"), ("19-09-07.815037", "1792980467779"),
    ("19-13-37.955290", "1792980753016"), ("19-17-06.312617", "1792980956290"),
    ("19-21-15.154157", "1792981162456"), ("19-25-36.915281", "1792981443519"),
    ("19-29-57.417805", "1792981721124"), ("19-34-46.250769", "1792982004804"),
]
NAVIGATION = Path("diagnostics/source_first_v3/shared_reader/navigation")
SOURCE_HASHES = ("journal_sha256", "job_sha256", "delivery_sha256")
LINKAGE = ("explicit public delivery references and job artifact references; content equality "
           "is checked separately, not a provider-side request ID")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate evidence field")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite evidence value")

    result = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise ValueError("evidence must be an object")
    return result


def identifier(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value):
        raise ValueError("unsupported evidence identifier")
    return value


def token_count(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else None


def sha(data):
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError("noncanonical evidence path")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError("unsupported evidence type or size")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        if identity(os.fstat(handle.fileno())) != identity(before):
            raise ValueError("evidence changed before read")
        data = handle.read(MAX_BYTES + 1)
        if identity(os.fstat(handle.fileno())) != identity(before):
            raise ValueError("evidence changed during read")
    if len(data) != before.st_size or identity(path.lstat()) != identity(before):
        raise ValueError("evidence changed after read")
    return data


def authored_public(data):
    header, separator, body = data.decode("utf-8").partition("\n\n")
    if (not separator or not header.startswith("=== INTROSPECTION: open reflection ===\n")
            or "Delivery: verified input delivery;" not in header or not body.endswith("\n")):
        raise ValueError("not a verified public reflection record")
    return body[:-1]  # Remove the publication wrapper's one newline, not authored bytes.


def cleanup_functions(runtime_source):
    """Execute source-bound production bodies, without runtime import side effects."""
    data = read(runtime_source)
    tree = ast.parse(data)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AutonomousAgent"]
    if len(classes) != 1:
        raise ValueError("ambiguous production cleanup class")
    cls = classes[0]
    names = ("_clean_llm_content", "_strip_model_artifacts")
    selected = []
    for name in names:
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(methods) != 1:
            raise ValueError("ambiguous production cleanup method")
        selected.append(methods[0])
    allowed_nodes = {
        ast.FunctionDef, ast.arguments, ast.arg, ast.Expr, ast.Constant, ast.Assign,
        ast.Name, ast.Load, ast.Store, ast.Return, ast.If, ast.IfExp, ast.UnaryOp,
        ast.Not, ast.For, ast.Tuple, ast.Compare, ast.In, ast.Call, ast.Attribute,
        ast.keyword, ast.Subscript,
    }
    for node in selected:
        node.decorator_list = []
        for child in ast.walk(node):
            if type(child) not in allowed_nodes:
                raise ValueError("cleanup method now requires an unqualified dependency")
            if isinstance(child, ast.Attribute):
                is_re = isinstance(child.value, ast.Name) and child.value.id == "re"
                if (child.attr in {"sub", "DOTALL"} and is_re) or child.attr in {"strip", "replace"}:
                    continue
                raise ValueError("cleanup method now requires an unqualified dependency")
            if isinstance(child, ast.Call) and not isinstance(child.func, ast.Attribute):
                raise ValueError("cleanup method now requires an unqualified dependency")
            if isinstance(child, ast.Assign) and any(not isinstance(t, ast.Name) for t in child.targets):
                raise ValueError("cleanup method contains an unqualified mutation")
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {"re": re, "Optional": Optional, "__builtins__": {}}
    exec(compile(module, str(runtime_source), "exec"), namespace)
    return (lambda text: namespace[names[0]](None, text.strip()) or "",
            namespace[names[1]], {"runtime_sha256": sha(data),
            "cleanup_ast_sha256": sha(ast.dump(module, include_attributes=False))})


def differences(left, right):
    a, b = left.encode("utf-8"), right.encode("utf-8")
    if max(len(a), len(b)) > 128 * 1024:
        raise ValueError("visible comparison exceeds bounded audit size")
    if a == b:
        return {"equal": True, "locations": [], "location_count": 0, "locations_omitted": 0}
    # Compare characters, then map to UTF-8 boundaries; byte matching can split
    # a code point. Large ambiguous edits get one exact covering range rather
    # than an unbounded quadratic search for the smallest edit script.
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    end_left, end_right = len(left), len(right)
    while end_left > prefix and end_right > prefix and left[end_left - 1] == right[end_right - 1]:
        end_left -= 1
        end_right -= 1
    lmid, rmid = left[prefix:end_left], right[prefix:end_right]
    coalesced = len(lmid) * len(rmid) > 4_000_000
    edits = ([('replace', 0, len(lmid), 0, len(rmid))] if coalesced else
             difflib.SequenceMatcher(None, lmid, rmid, autojunk=False).get_opcodes())
    changes = [{"operation": tag,
                "left_utf8_bytes": [len(left[:prefix + i].encode("utf-8")), len(left[:prefix + j].encode("utf-8"))],
                "right_utf8_bytes": [len(right[:prefix + k].encode("utf-8")), len(right[:prefix + l].encode("utf-8"))]}
               for tag, i, j, k, l in edits if tag != "equal"]
    return {"equal": a == b, "locations": changes[:32], "location_count": len(changes),
            "locations_omitted": max(0, len(changes) - 32),
            "coalesced_covering_range": coalesced}


def inspect_delivery(data, clean, strip):
    value = strict_json(data)
    output = value.get("output") or {}
    if value.get("schema") != "source_study_navigation_delivery_v1" or output.get("input_kind") != "reflection":
        raise ValueError("not a public reflection delivery")
    request, response = strict_json(value["request_json"]), strict_json(value["response_json"])
    if request.get("think") is not False or response.get("done") is not True:
        raise ValueError("unsupported or incomplete reflection response")
    content = response["message"]["content"]
    if not isinstance(content, str) or len(content.encode("utf-8")) > 128 * 1024:
        raise ValueError("missing visible response")
    # Hidden blocks are excluded using the production filter. The complete wire
    # is represented only by a digest; thinking fields are never inspected.
    visible = clean(content)
    return visible, strip(visible), {
        "navigation_id": identifier(output["navigation_id"]),
        "request_sha256": sha(value["request_json"]), "response_sha256": sha(value["response_json"]),
        "completion_reason": identifier(response.get("done_reason")), "model": identifier(response.get("model")),
        "prompt_tokens": token_count(response.get("prompt_eval_count")), "output_tokens": token_count(response.get("eval_count")),
        "provider_content_sha256": sha(content),
        "provider_content_matches_visible": content == visible,
        "provider_visible_sha256": sha(visible), "cleanup_sha256": sha(strip(visible)),
        "comparison_scope": "Provider-visible comparison starts after production meta-block filtering and trim; raw content and wire are digest-only. No thinking field is emitted.",
    }


def audit_entry(workspace, journal_relative, job_relative, delivery_relative, clean, strip, pinned=None):
    if (Path(journal_relative).parts[:1] != ("journal",)
            or len(Path(journal_relative).parts) != 2
            or not re.fullmatch(r"introspect_[A-Za-z0-9_.-]+\.txt", Path(journal_relative).name)
            or Path(job_relative).parts[:2] != ("llm_jobs", "jobs")
            or len(Path(job_relative).parts) != 4
            or Path(job_relative).name != "job.json"
            or Path(delivery_relative).parts[:len(NAVIGATION.parts)] != NAVIGATION.parts
            or len(Path(delivery_relative).parts) != len(NAVIGATION.parts) + 2
            or any(".." in Path(p).parts for p in (journal_relative, job_relative, delivery_relative))):
        raise ValueError("evidence outside public audit scope")
    journal, job_data, delivery = [read(workspace / p) for p in (journal_relative, job_relative, delivery_relative)]
    hashes = {"journal_sha256": sha(journal), "job_sha256": sha(job_data), "delivery_sha256": sha(delivery)}
    if pinned is not None and any(pinned.get(k) != v for k, v in hashes.items()):
        raise ValueError("frozen evidence drift")
    prose = authored_public(journal)
    job = strict_json(job_data)
    if (job.get("action_text") != "INTROSPECT" or job.get("system") != "minime"
            or job.get("job_id") != Path(job_relative).parts[2]
            or not any(a.get("kind") in {"journal", "introspect"}
                       and a.get("path_or_uri") == str(workspace / journal_relative)
                       for a in job.get("artifact_refs", []))):
        raise ValueError("job/publication association unavailable")
    visible, cleaned, details = inspect_delivery(delivery, clean, strip)
    if Path(delivery_relative).parent.name != details["navigation_id"]:
        raise ValueError("delivery identity mismatch")
    if Path(delivery_relative).name != hashes["delivery_sha256"] + ".json":
        raise ValueError("delivery content-address mismatch")
    attempts = job.get("phase_timings", {}).get("attempt_counts")
    count = (sum(attempts.values()) if isinstance(attempts, dict)
             and set(attempts) == {"ok", "empty", "error"}
             and all(type(n) is int and n >= 0 for n in attempts.values()) else None)
    # No transaction is opened against runtime state. Recheck all three inputs
    # after consuming the group; a changing record cannot yield a success report.
    for relative, expected in zip((journal_relative, job_relative, delivery_relative), hashes.values()):
        if sha(read(workspace / relative)) != expected:
            raise ValueError("evidence changed across audit")
    return {"journal": journal_relative, "job": job_relative, "delivery": delivery_relative,
            **hashes, **details, "job_id": identifier(job["job_id"]), "action_id": identifier(job.get("action_id")),
            "job_status": identifier(job.get("status")), "attempt_count": count,
            "published_sha256": sha(prose), "provider_to_cleanup": differences(visible, cleaned),
            "cleanup_to_publication": differences(cleaned, prose),
            "limits": "Termination is not prose quality. Content agreement does not identify model, server or transport cause."}


def sample_references(references):
    expected = [(f"journal/introspect_2026-10-25T{stamp}.txt",
                 f"llm_jobs/jobs/job_minime_{job}_introspect/job.json") for stamp, job in SAMPLE]
    entries = references.get("entries", [])
    if [(r["journal"], r["job"]) for r in entries] != expected:
        raise ValueError("explicit references differ from the selected twenty-entry sample")
    if len({r["delivery"] for r in entries}) != len(expected):
        raise ValueError("public delivery references must be distinct")
    return entries


def freeze_sample(workspace, runtime_source, references):
    clean, strip, implementation = cleanup_functions(runtime_source)
    entries = sample_references(references)
    # Never scan a mixed delivery family. The operator supplies the exact public
    # receipt locations established in the original investigation.
    rows = [audit_entry(workspace, r["journal"], r["job"], r["delivery"], clean, strip,
                        r if any(k in r for k in SOURCE_HASHES) else None) for r in entries]
    return {"schema": POLICY, "implementation": implementation, "entries": rows,
            "sample_count": len(rows), "read_only": True,
            "linkage": LINKAGE}


def audit_frozen(workspace, runtime_source, manifest):
    clean, strip, implementation = cleanup_functions(runtime_source)
    if manifest.get("schema") != POLICY or manifest.get("implementation") != implementation:
        raise ValueError("unsupported audit or cleanup implementation drift")
    entries = sample_references(manifest)
    return {"schema": POLICY, "implementation": implementation, "read_only": True,
            "sample_count": len(entries), "linkage": LINKAGE,
            "entries": [audit_entry(workspace, r["journal"], r["job"], r["delivery"], clean, strip, r) for r in entries]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("freeze", "audit"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--runtime-source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if not args.manifest:
        parser.error("both operations require --manifest with explicit public receipt references")
    try:
        operation = freeze_sample if args.operation == "freeze" else audit_frozen
        report = operation(args.workspace.resolve(), args.runtime_source.resolve(), strict_json(read(args.manifest.resolve())))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, SyntaxError):
        # Parser/OS exception messages may contain source text or private paths.
        print(json.dumps({"schema": POLICY, "read_only": True, "error": "evidence_unavailable_or_invalid"}))
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
