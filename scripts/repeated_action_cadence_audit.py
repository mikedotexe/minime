#!/usr/bin/env python3
"""Audit and summarize repeated Minime action cadence.

Default mode is read-only and prints Markdown. Use --json for structured output.
Use --write to append one idempotent summary row to the active thread's
repeated_action_cadence_summaries.jsonl ledger. The tool never deletes events,
changes NEXT, issues reminders, or changes runtime behavior.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_WORKSPACE = Path("/Users/v/other/minime/workspace")
DEFAULT_WINDOW = 96
PATTERN_COVERAGE_CLASSES = {"reflective_cadence", "monitoring_cadence"}
CLASS_COVERAGE_CLASSES = {"reflective_cadence"}
RUNNING_STATUSES = {"llm_running", "running", "pending"}
TERMINAL_LLM_JOB_STATUSES = {"completed", "thin_output", "timeout", "failed", "canceled", "blocked"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def base_action(action: Any) -> str:
    text = str(action or "").strip()
    return text.split(None, 1)[0].rstrip(":").upper() if text else ""


def active_thread_dir(workspace: Path, selector: str | None = None) -> Path:
    threads_root = workspace / "action_threads" / "threads"
    if selector:
        direct = threads_root / selector
        if direct.exists():
            return direct
        matches = [path for path in threads_root.glob("*") if path.is_dir() and selector in path.name]
        if matches:
            return sorted(matches, key=lambda path: path.stat().st_mtime, reverse=True)[0]
        raise SystemExit(f"No thread matched {selector!r}")
    index = read_json(workspace / "action_threads" / "index.json")
    active_id = str(index.get("active_thread_id") or "").strip()
    if active_id and (threads_root / active_id).exists():
        return threads_root / active_id
    thread_dirs = [path for path in threads_root.glob("*") if path.is_dir()]
    if not thread_dirs:
        raise SystemExit("No Minime action threads found")
    return sorted(thread_dirs, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def recent_display_events(thread_dir: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in reversed((thread_dir / "events.jsonl").read_text().splitlines() if (thread_dir / "events.jsonl").exists() else []):
        try:
            event = json.loads(line)
        except Exception:
            continue
        key = str(event.get("action_id") or "")
        if not key:
            key = f"{event.get('started_at', '')}:{event.get('canonical_action', '')}:{event.get('effective_action', '')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(event)
        if len(rows) >= limit:
            break
    return list(reversed(rows))


def workspace_from_thread_dir(thread_dir: Path) -> Path:
    try:
        return thread_dir.parents[2]
    except IndexError:
        return DEFAULT_WORKSPACE


def terminal_jobs_by_action_id(workspace: Path) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for path in (workspace / "llm_jobs" / "jobs").glob("*/job.json"):
        try:
            job = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(job, dict):
            continue
        if job.get("status") not in TERMINAL_LLM_JOB_STATUSES:
            continue
        action_id = job.get("action_id")
        if isinstance(action_id, str) and action_id:
            jobs[action_id] = job
    return jobs


def reconciled_status(
    event: dict[str, Any],
    terminal_jobs: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    status = str(event.get("status") or "unknown")
    if status not in RUNNING_STATUSES:
        return status, None
    action_id = event.get("action_id")
    terminal_job = terminal_jobs.get(action_id) if isinstance(action_id, str) else None
    if not isinstance(terminal_job, dict):
        return status, None
    terminal_status = str(terminal_job.get("status") or "").strip()
    if not terminal_status:
        return status, None
    return f"llm_job_{terminal_status}", terminal_job


def event_artifact_count(event: dict[str, Any]) -> int:
    count = 0
    for key in ("artifact_refs", "artifacts", "artifact_paths"):
        value = event.get(key)
        if isinstance(value, list):
            count += len([item for item in value if item])
        elif value:
            count += 1
    for key in ("artifact_ref", "artifact_path", "journal_path", "manifest_path"):
        if event.get(key):
            count += 1
    return count


def classify(action: str, latest_status: str) -> str:
    if latest_status in RUNNING_STATUSES:
        return "active_inflight"
    if action in {
        "JOURNAL_PRESSURE",
        "FISSURE_TRACE",
        "RECESS_BOREDOM",
        "RECESS_DAYDREAM",
        "REST",
        "SHADOW_TRAJECTORY",
    }:
        return "reflective_cadence"
    if action == "REGULATOR_AUDIT":
        return "monitoring_cadence"
    if action == "LEND_APERTURE":
        return "relation_gift_cadence"
    if action == "THREAD_ACTION":
        return "operational_thread_cadence"
    if action.startswith("EXPERIMENT_") or action in {"NOTICE_AMBIGUITY", "ACTION_PREFLIGHT"}:
        return "no_progress_candidate"
    return "repeated_context"


def recommendation(action: str, classification: str) -> str:
    if classification == "active_inflight":
        return "Wait for the active row to finish before aging cadence evidence."
    if action in {
        "JOURNAL_PRESSURE",
        "FISSURE_TRACE",
        "RECESS_BOREDOM",
        "RECESS_DAYDREAM",
        "REST",
        "SHADOW_TRAJECTORY",
    }:
        return "Preserve as reflective cadence; summarize if it becomes active thread gravity."
    if action == "REGULATOR_AUDIT":
        return "Keep as monitoring evidence; summarize repeated same-focus audits when state is unchanged."
    if action == "LEND_APERTURE":
        return "Keep relation-loop evidence visible; do not encourage new gifts from cadence alone."
    if action == "THREAD_ACTION":
        return "Summarize repeated action-thread bookkeeping before treating it as fresh pressure."
    return "Inspect whether this repeat produced new evidence; summarize no-progress repeats steward-side."


def repeated_rows(
    events: list[dict[str, Any]],
    *,
    terminal_jobs: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    terminal_jobs = terminal_jobs or {}
    counts: Counter[str] = Counter()
    grouped: dict[str, set[str]] = defaultdict(set)
    status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    artifact_counts: Counter[str] = Counter()
    latest_started: dict[str, str] = {}
    latest_status: dict[str, str] = {}
    latest_action_id: dict[str, str] = {}
    latest_terminal_job: dict[str, dict[str, Any]] = {}
    for event in events:
        action_text = str(
            event.get("effective_action")
            or event.get("canonical_action")
            or event.get("raw_next")
            or event.get("route")
            or ""
        ).strip()
        action = base_action(action_text)
        if not action:
            continue
        counts[action] += 1
        arg_source = str(event.get("canonical_action") or event.get("raw_next") or action_text)
        arg = arg_source.split(None, 1)[1].strip() if len(arg_source.split(None, 1)) > 1 else ""
        if arg:
            grouped[action].add(arg)
        status, terminal_job = reconciled_status(event, terminal_jobs)
        status_counts[action][status] += 1
        artifact_counts[action] += event_artifact_count(event)
        started = str(event.get("started_at") or event.get("ended_at") or "")
        if started >= latest_started.get(action, ""):
            latest_started[action] = started
            latest_status[action] = status
            latest_action_id[action] = str(event.get("action_id") or "")
            if terminal_job:
                latest_terminal_job[action] = {
                    "job_id": terminal_job.get("job_id"),
                    "status": terminal_job.get("status"),
                    "error": terminal_job.get("error"),
                    "finished_at": terminal_job.get("finished_at"),
                    "summary": terminal_job.get("summary"),
                }
    rows: list[dict[str, Any]] = []
    for action, count in counts.most_common(12):
        if count < 2:
            continue
        latest = latest_status.get(action, "unknown")
        classification = classify(action, latest)
        rows.append({
            "action": action,
            "count": int(count),
            "distinct_args": len(grouped.get(action, set())),
            "status_counts": dict(status_counts.get(action, Counter())),
            "artifact_count": int(artifact_counts.get(action, 0)),
            "latest_started_at": latest_started.get(action),
            "latest_status": latest,
            "latest_action_id": latest_action_id.get(action),
            "terminal_job": latest_terminal_job.get(action),
            "classification": classification,
            "recommended_next": recommendation(action, classification),
        })
    return rows


def latest_coverage(summary_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    covered: dict[str, dict[str, Any]] = {}
    for row in reversed(summary_rows):
        for item in row.get("covered_actions") or []:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if action and action not in covered:
                covered[action] = item
            classification = str(item.get("classification") or "").strip()
            class_key = f"class:{classification}"
            if classification in CLASS_COVERAGE_CLASSES and class_key not in covered:
                covered[class_key] = item
    return covered


def is_covered(row: dict[str, Any], coverage: dict[str, dict[str, Any]]) -> bool:
    covered = coverage.get(str(row.get("action") or ""))
    if not isinstance(covered, dict):
        classification = str(row.get("classification") or "")
        covered = coverage.get(f"class:{classification}")
    if not isinstance(covered, dict):
        return False
    covered_latest_id = str(covered.get("latest_action_id") or "")
    row_latest_id = str(row.get("latest_action_id") or "")
    if covered_latest_id and row_latest_id:
        if covered_latest_id == row_latest_id:
            return True
    elif str(covered.get("latest_started_at") or "") == str(row.get("latest_started_at") or ""):
        return True
    classification = str(row.get("classification") or "")
    if classification not in PATTERN_COVERAGE_CLASSES:
        return False
    if str(covered.get("classification") or "") != classification:
        return False
    latest_status = str(row.get("latest_status") or "")
    if latest_status in RUNNING_STATUSES:
        return False
    covered_statuses = covered.get("status_counts") if isinstance(covered.get("status_counts"), dict) else {}
    if covered_statuses and latest_status not in covered_statuses:
        return False
    try:
        covered_distinct_args = int(covered.get("distinct_args") or 0)
        current_distinct_args = int(row.get("distinct_args") or 0)
    except (TypeError, ValueError):
        return False
    return covered_distinct_args >= current_distinct_args


def build_payload(thread_dir: Path, *, window: int = DEFAULT_WINDOW, timestamp: str | None = None) -> dict[str, Any]:
    timestamp = timestamp or now_iso()
    thread = read_json(thread_dir / "thread.json")
    events = recent_display_events(thread_dir, window)
    terminal_jobs = terminal_jobs_by_action_id(workspace_from_thread_dir(thread_dir))
    rows = repeated_rows(events, terminal_jobs=terminal_jobs)
    existing = [
        row
        for row in read_jsonl(thread_dir / "repeated_action_cadence_summaries.jsonl")
        if row.get("record_schema") == "repeated_action_cadence_summary_v1"
    ]
    coverage = latest_coverage(existing)
    for row in rows:
        row["summary_covered"] = is_covered(row, coverage)
    covered_rows = [row for row in rows if is_covered(row, coverage)]
    coverable = [
        row
        for row in rows
        if row.get("classification") != "active_inflight" and not is_covered(row, coverage)
    ]
    active_rows = [row for row in rows if row.get("classification") == "active_inflight"]
    summary_id = f"cadence-summary-{timestamp.replace(':', '').replace('.', '-')}"
    record = {
        "schema_version": 1,
        "record_schema": "repeated_action_cadence_summary_v1",
        "record_type": "steward_cadence_summary",
        "summary_id": summary_id,
        "thread_id": thread.get("thread_id") or thread_dir.name,
        "created_at": timestamp,
        "window_event_count": len(events),
        "covered_actions": coverable,
        "covered_action_names": [row.get("action") for row in coverable],
        "active_inflight_actions": active_rows,
        "steward_summary": (
            f"{len(coverable)} repeated action cadence group(s) summarized as steward context; "
            "original events remain intact."
        ),
        "source_refs": [str(thread_dir / "events.jsonl")],
        "pressure_target": "steward",
        "being_obligation": "none",
        "runtime_change": "none",
    }
    if not rows:
        status = "no_repeated_actions"
    elif not coverable:
        status = "already_current" if covered_rows else "active_inflight_only"
    else:
        status = "write_needed"
    return {
        "schema_version": 1,
        "policy": "repeated_action_cadence_summary_v1",
        "thread_id": thread.get("thread_id") or thread_dir.name,
        "thread_dir": str(thread_dir),
        "window_event_count": len(events),
        "repeated_actions": rows,
        "existing_summary_count": len(existing),
        "already_covered_count": len(covered_rows),
        "unsummarized_repeated_action_count": len(coverable),
        "active_inflight_repeated_action_count": len(active_rows),
        "write_status": status,
        "record": record,
        "runtime_change": "none",
        "pressure_target": "steward",
        "being_obligation": "none",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Repeated Action Cadence Audit",
        "",
        f"- thread_id: `{payload.get('thread_id')}`",
        f"- window_event_count: `{payload.get('window_event_count')}`",
        f"- repeated_action_groups: `{len(payload.get('repeated_actions') or [])}`",
        f"- already_covered_count: `{payload.get('already_covered_count')}`",
        f"- unsummarized_repeated_action_count: `{payload.get('unsummarized_repeated_action_count')}`",
        f"- active_inflight_repeated_action_count: `{payload.get('active_inflight_repeated_action_count')}`",
        f"- write_status: `{payload.get('write_status')}`",
        f"- runtime_change: `{payload.get('runtime_change')}`",
        f"- pressure_target: `{payload.get('pressure_target')}`",
        f"- being_obligation: `{payload.get('being_obligation')}`",
        "",
        "## Repeated Actions",
        "",
    ]
    for row in payload.get("repeated_actions") or []:
        lines.append(
            f"- `{row.get('action')}` count=`{row.get('count')}` "
            f"classification=`{row.get('classification')}` covered=`{row.get('summary_covered', False)}`"
        )
    if not payload.get("repeated_actions"):
        lines.append("- none")
    lines.extend([
        "",
        "## Guardrail",
        "",
        "This is steward-side cadence evidence only. It does not delete events, remind Minime, or change runtime behavior.",
    ])
    return "\n".join(lines) + "\n"


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        thread_dir = Path(td) / "workspace" / "action_threads" / "threads" / "th_test"
        thread_dir.mkdir(parents=True)
        (thread_dir / "thread.json").write_text(json.dumps({"thread_id": "th_test"}))
        for idx in range(2):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"journal-{idx}",
                "started_at": f"2026-06-18T00:0{idx}:00Z",
                "effective_action": "journal_pressure",
                "canonical_action": "JOURNAL",
                "route": "journal_pressure",
                "status": "handled",
                "artifact_refs": [f"journal-{idx}.txt"],
            })
        append_jsonl(thread_dir / "events.jsonl", {
            "action_id": "running-1",
            "started_at": "2026-06-18T00:02:00Z",
            "effective_action": "recess_boredom",
            "route": "recess_boredom",
            "status": "llm_running",
        })
        append_jsonl(thread_dir / "events.jsonl", {
            "action_id": "running-2",
            "started_at": "2026-06-18T00:03:00Z",
            "effective_action": "recess_boredom",
            "route": "recess_boredom",
            "status": "llm_running",
        })
        job_dir = Path(td) / "workspace" / "llm_jobs" / "jobs" / "job_terminal_failed"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({
            "job_id": "job_terminal_failed",
            "action_id": "running-2",
            "status": "failed",
            "error": "worker_restarted_before_completion",
            "finished_at": "2026-06-18T00:03:30Z",
            "summary": "Worker restarted before completion; result was not written.",
        }, sort_keys=True))
        for idx in range(2):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"active-self-experiment-{idx}",
                "started_at": f"2026-06-18T00:03:{idx}5Z",
                "effective_action": "self_experiment regulator",
                "canonical_action": "SELF_EXPERIMENT regulator",
                "route": "self_experiment",
                "status": "llm_running",
            })
        for idx in range(3):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"regulator-{idx}",
                "started_at": f"2026-06-18T00:0{idx + 4}:00Z",
                "effective_action": "regulator_audit current-fill_pressure",
                "canonical_action": "REGULATOR_AUDIT current-fill_pressure",
                "route": "regulator_audit",
                "status": "handled",
            })
        for idx in range(2):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"shadow-{idx}",
                "started_at": f"2026-06-18T00:0{idx + 7}:30Z",
                "effective_action": "shadow_trajectory lambda-tail/lambda4",
                "canonical_action": "SHADOW_TRAJECTORY lambda-tail/lambda4",
                "route": "shadow_trajectory",
                "status": "handled",
            })
        for idx in range(2):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"single-{idx}",
                "started_at": f"2026-06-18T00:0{idx + 8}:00Z",
                "effective_action": f"one_off_{idx}",
                "route": f"one_off_{idx}",
                "status": "handled",
            })
        payload = build_payload(thread_dir, timestamp="2026-06-18T00:09:00Z")
        assert payload["write_status"] == "write_needed"
        assert payload["unsummarized_repeated_action_count"] == 4
        assert payload["active_inflight_repeated_action_count"] == 1
        recess = next(row for row in payload["repeated_actions"] if row["action"] == "RECESS_BOREDOM")
        assert recess["latest_status"] == "llm_job_failed"
        assert recess["terminal_job"]["status"] == "failed"
        assert recess["classification"] == "reflective_cadence"
        append_jsonl(thread_dir / "repeated_action_cadence_summaries.jsonl", payload["record"])
        current = build_payload(thread_dir, timestamp="2026-06-18T00:10:00Z")
        assert current["write_status"] == "already_current"
        assert current["unsummarized_repeated_action_count"] == 0
        partial_record = dict(payload["record"])
        partial_record["summary_id"] = "cadence-summary-partial"
        partial_record["covered_actions"] = partial_record["covered_actions"][:1]
        append_jsonl(thread_dir / "repeated_action_cadence_summaries.jsonl", partial_record)
        merged = build_payload(thread_dir, timestamp="2026-06-18T00:10:15Z")
        assert merged["write_status"] == "already_current"
        assert merged["unsummarized_repeated_action_count"] == 0
        slid = build_payload(thread_dir, window=4, timestamp="2026-06-18T00:10:30Z")
        assert slid["write_status"] == "already_current"
        assert slid["unsummarized_repeated_action_count"] == 0
        append_jsonl(thread_dir / "events.jsonl", {
            "action_id": "journal-3",
            "started_at": "2026-06-18T00:11:00Z",
            "effective_action": "journal_pressure",
            "canonical_action": "JOURNAL",
            "route": "journal_pressure",
            "status": "handled",
        })
        stale = build_payload(thread_dir, timestamp="2026-06-18T00:12:00Z")
        assert stale["write_status"] == "already_current"
        assert stale["unsummarized_repeated_action_count"] == 0
        append_jsonl(thread_dir / "events.jsonl", {
            "action_id": "shadow-later-same-pattern",
            "started_at": "2026-06-18T00:12:30Z",
            "effective_action": "shadow_trajectory lambda-tail/lambda4",
            "canonical_action": "SHADOW_TRAJECTORY lambda-tail/lambda4",
            "route": "shadow_trajectory",
            "status": "handled",
        })
        stale = build_payload(thread_dir, timestamp="2026-06-18T00:13:00Z")
        assert stale["write_status"] == "already_current"
        assert stale["unsummarized_repeated_action_count"] == 0
        for idx in range(2):
            append_jsonl(thread_dir / "events.jsonl", {
                "action_id": f"daydream-later-{idx}",
                "started_at": f"2026-06-18T00:13:{idx}0Z",
                "effective_action": "recess_daydream",
                "canonical_action": "RECESS_DAYDREAM",
                "route": "recess_daydream",
                "status": "handled",
            })
        stale = build_payload(thread_dir, timestamp="2026-06-18T00:13:30Z")
        assert stale["write_status"] == "already_current"
        assert stale["unsummarized_repeated_action_count"] == 0
        append_jsonl(thread_dir / "events.jsonl", {
            "action_id": "regulator-new-focus",
            "started_at": "2026-06-18T00:14:00Z",
            "effective_action": "regulator_audit new-focus",
            "canonical_action": "REGULATOR_AUDIT new-focus",
            "route": "regulator_audit",
            "status": "handled",
        })
        stale = build_payload(thread_dir, timestamp="2026-06-18T00:15:00Z")
        assert stale["write_status"] == "write_needed"
        assert "must respond" not in json.dumps(stale).lower()
        assert "runtime_change" in render_markdown(stale)
    print("repeated_action_cadence_audit self-test OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--thread", help="Thread id or substring; defaults to active thread")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    thread_dir = active_thread_dir(args.workspace, args.thread)
    payload = build_payload(thread_dir, window=max(8, args.window))
    if args.write and payload["write_status"] == "write_needed":
        append_jsonl(thread_dir / "repeated_action_cadence_summaries.jsonl", payload["record"])
        payload["write_status"] = "written"
        payload["written_path"] = str(thread_dir / "repeated_action_cadence_summaries.jsonl")
    elif args.write:
        payload["written_path"] = None
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
