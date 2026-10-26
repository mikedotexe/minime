#!/usr/bin/env python3
"""Bounded synthetic parent/candidate comparison; no canonical runtime execution."""

import argparse
import ast
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from statistics import median
import subprocess
import sys
import time
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID


REVISION = "e86801d98c5aa4a2b1725fba99356049f647d674"
STAMP = 1793001600.125
STATE = {"eig1": 4.7, "deig": 0.01, "fill_ratio": 0.68, "spread": 3.0, "cov_lambda1": 8.0}
CASES = {
    "introspect": "A synthetic caf\u00e9 reflection.\nQuoted `NEXT: REST` remains prose.\nNEXT: INTROSPECT",
    "rest": "A separate synthetic reflection, with exact spacing.\n\nNEXT: REST",
    "no_next": "A synthetic reflection without a selected next action.",
}
UNCHANGED_METHODS = (
    "_query_llm", "_query_llm_with_next", "_clean_llm_content", "_strip_model_artifacts",
    "_record_llm_next_action_choice", "_persist_pending_next_action", "_apply_footer_directives",
    "_maybe_compress_journal_entry",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def methods(raw):
    tree = ast.parse(raw)
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AutonomousAgent")
    return {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}


def old_methods(parent, destination):
    selected = [deepcopy(parent[name]) for name in ("_run_shared_source_study", "_write_journal_entry")]
    tree = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    path = destination / "parent_adapter_methods.py"
    path.write_text(ast.unparse(tree) + "\n")
    return compile(path.read_text(), str(path), "exec")


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(STAMP, tz)


def db_rows(path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM sovereignty_journal ORDER BY id")]


def db_schema(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


def setup_context(active, helper, modules, seed=None):
    @contextmanager
    def context():
        with modules.pytest.MonkeyPatch.context() as patch:
            patch.setenv("ASTRID_SOURCE_STUDY_BIN", str(helper))
            request = SimpleNamespace(node=SimpleNamespace(path=Path("synthetic_comparison.py")))
            modules.conftest.isolated_default_autonomy_paths.__wrapped__(active, patch, request)
            if seed is not None:
                shutil.copytree(seed, active, dirs_exist_ok=True)
            patch.setattr(modules.aa.time, "time", lambda: STAMP)
            patch.setattr(modules.aa, "datetime", FrozenDateTime)
            patch.setattr(modules.aa, "uuid4", lambda: UUID(hex="1" * 32))
            astrid = active / "astrid"
            if astrid.exists():
                assert not list(astrid.iterdir())
                astrid.rmdir()
            pair = modules.tests.writing_agent.__wrapped__(patch, active)
            adapter = modules.tests.adapter.__wrapped__(None, pair, patch)
            # The comparison exercises the real generic DB writer on the parent path.
            generic = MethodType(modules.aa.AutonomousAgent._write_journal_entry, adapter.agent)
            patch.setattr(adapter.agent, "_write_journal_entry", Mock(wraps=generic))
            yield adapter, patch
    return context()


def parent_mode(adapter, patch, modules, code, legacy):
    namespace = dict(vars(modules.aa))
    namespace["ReflectionPublication"] = legacy.ReflectionPublication
    exec(code, namespace)
    patch.setattr(adapter.agent, "_run_shared_source_study", MethodType(namespace["_run_shared_source_study"], adapter.agent))
    patch.setattr(adapter.agent, "_write_journal_entry", Mock(wraps=MethodType(namespace["_write_journal_entry"], adapter.agent)))


def seed_history(adapter, body):
    with sqlite3.connect(adapter.database) as connection:
        connection.executemany("""INSERT INTO sovereignty_journal
            (session_id,timestamp,entry_type,content,spectral_context,file_path)
            VALUES (?,?,?,?,?,?)""", [
                (1, 100.0, "reflection", body, "{}", str(adapter.client.workspace / "journal/older.txt")),
                (1, 101.0, "reflection", body, "{}", str(adapter.client.workspace / "journal/older-again.txt")),
            ])


def capture(adapter, body, baseline_rows, destination, modules):
    paths = list((adapter.client.workspace / "journal").glob("introspect_*.txt"))
    assert len(paths) == 1
    public = paths[0].read_bytes()
    assert public.endswith((body + "\n").encode())
    evidence = modules.tests.evidence_snapshot(adapter.client)
    assert len(evidence) == 1
    delivery_raw = next(iter(evidence.values()))
    delivery = json.loads(delivery_raw)
    request = adapter.post.call_args.kwargs["data"]
    assert request == delivery["request_json"].encode()
    assert json.loads(delivery["response_json"])["message"]["content"] == body
    prompt = adapter.query.call_args.args[0]
    assert prompt.receipt
    rows = db_rows(adapter.database)
    assert len(rows) == 3
    columns = tuple(baseline_rows[0])
    prior = [{key: row[key] for key in columns} for row in rows[:2]]
    assert prior == baseline_rows
    original_new = {key: rows[2][key] for key in columns}
    queue = adapter.client.workspace / "sovereignty_state.json"
    queue_raw = queue.read_bytes() if queue.exists() else None
    destination.mkdir()
    (destination / "request.json").write_bytes(request)
    (destination / "public.txt").write_bytes(public)
    (destination / "native-delivery.json").write_bytes(delivery_raw)
    (destination / "authored.txt").write_text(body)
    write_json(destination / "database-before.json", baseline_rows)
    write_json(destination / "database-after.json", rows)
    write_json(destination / "database-schema.json", db_schema(adapter.database))
    write_json(destination / "native-receipt.json", prompt.receipt)
    if queue_raw is not None:
        (destination / "queue.json").write_bytes(queue_raw)
    counters = {
        "provider_calls": adapter.post.call_count,
        "next_handler_calls": adapter.choice.call_count,
        "control_handler_calls": adapter.agent._apply_footer_directives.call_count,
        "generic_journal_calls": adapter.agent._write_journal_entry.call_count,
        "before_index_calls": adapter.before.call_count,
        "after_index_calls": adapter.after.call_count,
    }
    return {
        "request": request, "prompt": str(prompt).encode(), "public": public,
        "authored": body.encode(), "native": delivery_raw, "receipt": prompt.receipt,
        "queue": queue_raw, "next": getattr(adapter.agent, "_pending_next_action", None),
        "new_db_original_columns": original_new, "before": baseline_rows,
        "historical_unchanged": True, "schema": db_schema(adapter.database),
        "has_publication_id": bool(rows[2].get("publication_id")), "counters": counters,
    }


def compare_case(name, body, root, helper, modules, code, legacy):
    case = root / name
    case.mkdir()
    active, seed = case / "active", case / "seed"
    active.mkdir()
    results = {}
    for variant in ("parent", "candidate"):
        if variant == "candidate":
            active.mkdir()
        with setup_context(active, helper, modules, seed if variant == "candidate" else None) as (adapter, patch):
            adapter.post.return_value = modules.tests.stub_response(body)
            if variant == "parent":
                adapter.client.prepare("INTROSPECT", request_id="prepare-" + modules.tests.ACTION)
                seed_history(adapter, body)
                shutil.copytree(active, seed)
                parent_mode(adapter, patch, modules, code, legacy)
            before = db_rows(adapter.database)
            modules.tests.run_reflection(adapter)
            results[variant] = capture(adapter, body, before, case / (variant + "-artifacts"), modules)
        active.rename(case / (variant + "-store"))
    parent, candidate = results["parent"], results["candidate"]
    checks = {key + "_exact": parent[key] == candidate[key] for key in (
        "request", "prompt", "public", "authored", "native", "receipt", "queue", "next", "new_db_original_columns", "before")}
    checks["historical_rows_preserved"] = parent["historical_unchanged"] and candidate["historical_unchanged"]
    checks["candidate_adds_identity_parent_unchanged"] = candidate["has_publication_id"] and not parent["has_publication_id"]
    result = {
        "case": name, "checks": checks, "all_passed": all(checks.values()),
        "parent": {"sha256": {key: sha(parent[key] or b"") for key in ("request", "prompt", "public", "authored", "native", "queue")},
                   "counters": parent["counters"]},
        "candidate": {"sha256": {key: sha(candidate[key] or b"") for key in ("request", "prompt", "public", "authored", "native", "queue")},
                      "counters": candidate["counters"]},
    }
    write_json(case / "comparison.json", result)
    return result


@contextmanager
def measure_io(patch, modules):
    atomic, connect = modules.tests.Directory.atomic, sqlite3.connect
    counters = Counter()
    statements = Counter()

    def write(directory, name, raw, **kwargs):
        counters["atomic_calls"] += 1
        counters["atomic_payload_bytes"] += len(raw)
        counters["public_atomic_calls" if directory.path.name == "journal" else "receipt_atomic_calls"] += 1
        return atomic(directory, name, raw, **kwargs)

    def connection(*args, **kwargs):
        counters["sqlite_connections"] += 1
        result = connect(*args, **kwargs)
        result.set_trace_callback(lambda sql: statements.update([sql.split()[0].upper()] if sql.split() else []))
        return result

    with patch.context() as child:
        child.setattr(modules.tests.Directory, "atomic", write)
        child.setattr(sqlite3, "connect", connection)
        started = time.perf_counter_ns()
        yield counters, statements
        counters["elapsed_ns"] = time.perf_counter_ns() - started


def recovery_case(root, helper, modules, boundary, mode):
    case = root / (mode + "-" + boundary)
    case.mkdir()
    active = case / "store"
    active.mkdir()
    with setup_context(active, helper, modules) as (adapter, patch):
        with modules.tests.injected_fault(adapter, patch, boundary):
            modules.tests.run_reflection(adapter)
        modules.tests.assert_first_fault_status(adapter, boundary)
        modules.tests.select_later_queue(adapter, "REST")
        private, job = modules.tests.seed_protected_history(adapter)
        before = modules.tests.queue_snapshot(adapter), modules.tests.snapshot(private), job.read_bytes(), modules.tests.evidence_snapshot(adapter.client)
        unchanged = modules.tests.forbid_replay(adapter)
        samples = []
        for _ in range(3):
            with measure_io(patch, modules) as (io, statements):
                if mode == "startup":
                    adapter.agent._recover_reflection_publications()
                else:
                    modules.tests.run_reflection(adapter)
            modules.tests.assert_published_and_indexed(adapter)
            samples.append({"elapsed_ms": round(io.pop("elapsed_ns") / 1_000_000, 3),
                            "io": dict(io), "sql_statement_counts": dict(statements)})
        assert unchanged()
        assert (modules.tests.queue_snapshot(adapter), modules.tests.snapshot(private), job.read_bytes(), modules.tests.evidence_snapshot(adapter.client)) == before
        storage = adapter.client.workspace / "runtime/reflection_publications"
        owned_bytes = sum(path.stat().st_size for path in storage.iterdir() if path.is_file())
        result = {"fault": boundary, "mode": mode, "samples": samples,
                  "publication_files": 1, "new_database_rows": 1,
                  "provider_control_choice_callback_replay": 0,
                  "queue_private_native_history_unchanged": True,
                  "receipt_storage_bytes_after_recovery": owned_bytes}
        write_json(case / "recovery-cost.json", result)
        return result


def cost_summary(costs):
    result = {}
    for mode in ("startup", "reentry"):
        for phase, indexes in (("first_recovery", (0,)), ("idempotent_repeat", (1, 2))):
            samples = [case["samples"][index] for case in costs if case["mode"] == mode for index in indexes]
            elapsed = [sample["elapsed_ms"] for sample in samples]
            result[mode + "_" + phase] = {
                "sample_count": len(samples), "min_ms": min(elapsed),
                "median_ms": round(median(elapsed), 3), "max_ms": max(elapsed),
                "atomic_calls_range": [min(s["io"].get("atomic_calls", 0) for s in samples),
                                       max(s["io"].get("atomic_calls", 0) for s in samples)],
                "sqlite_connections_range": [min(s["io"].get("sqlite_connections", 0) for s in samples),
                                             max(s["io"].get("sqlite_connections", 0) for s in samples)],
                "insert_statements_total": sum(s["sql_statement_counts"].get("INSERT", 0) for s in samples),
            }
    result["interpretation"] = (
        "Local fixture timings only. Startup skips fully indexed receipts on repeat. "
        "Action reentry still verifies the database and stages an idempotent recovery receipt; "
        "it is not a write-free scan. No repeated publication, DB insert, inference, choice, control, or journal hook."
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate, parent, helper, root = (path.resolve() for path in (args.candidate, args.parent, args.helper, args.output))
    assert helper.is_file()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=parent, text=True).strip() == REVISION
    root.mkdir()
    extracted = root / "extracted-parent"
    extracted.mkdir()
    parent_raw = subprocess.check_output(["git", "show", f"{REVISION}:minime_autonomy/runtime.py"], cwd=candidate)
    legacy_raw = subprocess.check_output(["git", "show", f"{REVISION}:minime_autonomy/reflection_publication.py"], cwd=candidate)
    assert (parent / "minime_autonomy/runtime.py").read_bytes() == parent_raw
    assert (parent / "minime_autonomy/reflection_publication.py").read_bytes() == legacy_raw
    candidate_raw = (candidate / "minime_autonomy/runtime.py").read_bytes()
    old, new = methods(parent_raw), methods(candidate_raw)
    unchanged_methods = {name: ast.dump(old[name], include_attributes=False) == ast.dump(new[name], include_attributes=False)
                         for name in UNCHANGED_METHODS}
    assert all(unchanged_methods.values())
    assert (parent / "minime_autonomy/source_study.py").read_bytes() == (candidate / "minime_autonomy/source_study.py").read_bytes()
    code = old_methods(old, extracted)
    legacy_file = extracted / "reflection_publication_v1.py"
    legacy_file.write_bytes(legacy_raw)
    identities = {str(path): sha(path.read_bytes()) for path in (
        parent / "minime_autonomy/runtime.py", parent / "minime_autonomy/reflection_publication.py",
        candidate / "minime_autonomy/runtime.py", candidate / "minime_autonomy/reflection_publication.py", helper,
        candidate / "tests/test_reflection_finalization_adapter.py", Path(__file__).resolve())}
    sys.path.insert(0, str(candidate))
    import pytest
    from tests import conftest
    from tests import test_reflection_finalization_adapter as tests
    import autonomous_agent as aa
    modules = SimpleNamespace(pytest=pytest, conftest=conftest, tests=tests, aa=aa)
    logging.disable(logging.CRITICAL)
    spec = importlib.util.spec_from_file_location("minime_autonomy._comparison_legacy_publication", legacy_file)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    golden_root = root / "golden"
    golden_root.mkdir()
    golden = [compare_case(name, body, golden_root, helper, modules, code, legacy) for name, body in CASES.items()]
    cost_root = root / "recovery-cost"
    cost_root.mkdir()
    costs = [recovery_case(cost_root, helper, modules, boundary, mode)
             for mode in ("startup", "reentry") for boundary in tests.FAULTS]
    final_identities = {name: sha(Path(name).read_bytes()) for name in identities}
    unchanged = identities == final_identities
    report = {
        "schema": "synthetic_reflection_comparison_v1", "parent_revision": REVISION,
        "source_and_helper_sha256": identities, "source_and_helper_unchanged": unchanged,
        "unchanged_shared_method_ast": unchanged_methods, "source_study_module_byte_identical": True,
        "golden": golden, "recovery_cost": costs, "recovery_cost_summary": cost_summary(costs),
        "all_passed": unchanged and all(case["all_passed"] for case in golden),
        "scope": {
            "synthetic_only": True, "live_provider_calls": 0, "service_operations": 0,
            "parent_execution": "Two runtime methods and v1 publication module extracted from immutable Git revision into evidence directory; canonical module never imported.",
            "shared_runtime": "Unchanged query/cleanup/NEXT/control methods AST-verified; candidate fixture initializes isolated stores for both variants.",
            "determinism": "Identical cloned native pending preparation at the same absolute sandbox path; frozen Python clock and queue UUID; untouched frozen native helper.",
            "db_comparison": "Exact original columns before/after; historical rows preserved; candidate-only nullable publication identity expected.",
            "cost_limit": "One synthetic case per fault and entry mode, followed by two idempotent repeats; local timings, not a production latency benchmark.",
            "retained_stores": "Paired active sandbox renamed after each run; recorded absolute paths intentionally retain the shared comparison path.",
        },
    }
    write_json(root / "report.json", report)
    print(json.dumps({"report": str(root / "report.json"), "all_passed": report["all_passed"],
                      "golden_cases": len(golden), "recovery_scenarios": len(costs)}, sort_keys=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
