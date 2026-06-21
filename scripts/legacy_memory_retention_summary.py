#!/usr/bin/env python3
"""Summarize legacy Minime memory drafts as steward retention evidence.

Default mode is read-only and prints Markdown. Use --json for structured output.
Use --write to append an idempotent summary record to the active thread's
legacy_memory_retention_summaries.jsonl ledger. The tool never deletes,
promotes, rewrites, or reminds a being about old drafts.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_WORKSPACE = Path("/Users/v/other/minime/workspace")
ACTIVE_WINDOW_HOURS = 48


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def active_thread_dir(workspace: Path, selector: str | None = None) -> Path:
    threads_root = workspace / "action_threads" / "threads"
    if selector:
        candidate = threads_root / selector
        if candidate.exists():
            return candidate
        matches = [
            path
            for path in threads_root.glob("*")
            if path.is_dir() and selector in path.name
        ]
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


def classify_drafts(
    rows: list[dict[str, Any]],
    *,
    active_window_hours: int = ACTIVE_WINDOW_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    drafts = [row for row in rows if row.get("record_type") == "draft"]
    active: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    undated: list[dict[str, Any]] = []
    for row in drafts:
        created = parse_time(row.get("created_at"))
        if created is None:
            undated.append(row)
            continue
        age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
        if age_hours <= active_window_hours:
            active.append(row)
        else:
            legacy.append(row)
    return {
        "drafts": drafts,
        "active": active,
        "legacy": legacy,
        "undated": undated,
    }


def compact_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def covered_ids(summary_rows: list[dict[str, Any]]) -> set[str]:
    for row in reversed(summary_rows):
        ids = {
            str(item).strip()
            for item in (row.get("covered_memory_ids") or [])
            if str(item).strip()
        }
        if ids:
            return ids
    return set()


def build_summary(
    thread_dir: Path,
    *,
    active_window_hours: int = ACTIVE_WINDOW_HOURS,
    timestamp: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = timestamp or now_iso()
    thread = read_json(thread_dir / "thread.json")
    memory_rows = [
        row
        for row in read_jsonl(thread_dir / "being_memory.jsonl")
        if row.get("record_schema") == "being_memory_v1"
    ]
    existing = read_jsonl(thread_dir / "legacy_memory_retention_summaries.jsonl")
    classified = classify_drafts(memory_rows, active_window_hours=active_window_hours, now=now)
    legacy = classified["legacy"]
    legacy_ids = [
        str(row.get("memory_id") or "").strip()
        for row in legacy
        if str(row.get("memory_id") or "").strip()
    ]
    legacy_id_set = set(legacy_ids)
    already_covered = covered_ids(existing) & legacy_id_set
    missing_ids = sorted(legacy_id_set - already_covered)
    by_card_type = Counter(str(row.get("card_type") or "unknown") for row in legacy)
    oldest = min(
        (str(row.get("created_at") or "") for row in legacy if row.get("created_at")),
        default=None,
    )
    newest = max(
        (str(row.get("created_at") or "") for row in legacy if row.get("created_at")),
        default=None,
    )
    samples = [
        {
            "memory_id": row.get("memory_id"),
            "card_type": row.get("card_type"),
            "created_at": row.get("created_at"),
            "summary": compact_text(row.get("summary"), 220),
        }
        for row in legacy[-8:]
    ]
    summary_id = f"legacy-retention-{timestamp.replace(':', '').replace('.', '-')}"
    record = {
        "schema_version": 1,
        "record_schema": "legacy_memory_retention_summary_v1",
        "record_type": "steward_retention_summary",
        "summary_id": summary_id,
        "thread_id": thread.get("thread_id") or thread_dir.name,
        "created_at": timestamp,
        "active_window_hours": active_window_hours,
        "covered_legacy_count": len(legacy_ids),
        "covered_memory_ids": legacy_ids,
        "covered_by_card_type": dict(by_card_type),
        "oldest_legacy_created_at": oldest,
        "newest_legacy_created_at": newest,
        "sample_summaries": samples,
        "steward_summary": (
            f"{len(legacy_ids)} legacy memory draft(s) are retained as evidence/backlog, "
            f"not current obligation. Main types: "
            + ", ".join(f"{key}={value}" for key, value in by_card_type.most_common(5))
        ),
        "source_refs": [str(thread_dir / "being_memory.jsonl")],
        "pressure_target": "steward",
        "being_obligation": "none",
        "runtime_change": "none",
    }
    if not legacy:
        write_status = "no_legacy_retention"
    elif not missing_ids and already_covered:
        write_status = "already_current"
    else:
        write_status = "write_needed"
    return {
        "schema_version": 1,
        "policy": "legacy_memory_retention_summary_v1",
        "thread_id": thread.get("thread_id") or thread_dir.name,
        "thread_dir": str(thread_dir),
        "active_draft_count": len(classified["active"]),
        "legacy_retention_count": len(legacy),
        "undated_draft_count": len(classified["undated"]),
        "existing_summary_count": len(existing),
        "already_covered_count": len(already_covered),
        "unsummarized_legacy_retention_count": len(missing_ids),
        "write_status": write_status,
        "record": record,
        "runtime_change": "none",
        "pressure_target": "steward",
        "being_obligation": "none",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    lines = [
        "# Legacy Memory Retention Summary",
        "",
        f"- thread_id: `{payload.get('thread_id')}`",
        f"- active_draft_count: `{payload.get('active_draft_count')}`",
        f"- legacy_retention_count: `{payload.get('legacy_retention_count')}`",
        f"- already_covered_count: `{payload.get('already_covered_count')}`",
        f"- unsummarized_legacy_retention_count: `{payload.get('unsummarized_legacy_retention_count')}`",
        f"- write_status: `{payload.get('write_status')}`",
        f"- runtime_change: `{payload.get('runtime_change')}`",
        f"- pressure_target: `{payload.get('pressure_target')}`",
        f"- being_obligation: `{payload.get('being_obligation')}`",
        "",
        "## Summary",
        "",
        str(record.get("steward_summary") or "No legacy drafts to summarize."),
        "",
        "## Types",
        "",
    ]
    by_type = record.get("covered_by_card_type") if isinstance(record, dict) else {}
    if isinstance(by_type, dict) and by_type:
        for key, value in sorted(by_type.items()):
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Guardrail",
        "",
        "This is steward-side aging evidence only. It does not delete, promote, rewrite, invite, or pressure Minime.",
    ])
    return "\n".join(lines) + "\n"


def self_test() -> int:
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        thread_dir = Path(td) / "workspace" / "action_threads" / "threads" / "th_test"
        thread_dir.mkdir(parents=True)
        (thread_dir / "thread.json").write_text(json.dumps({"thread_id": "th_test"}))
        legacy = {
            "record_schema": "being_memory_v1",
            "record_type": "draft",
            "memory_id": "mem_old",
            "card_type": "authority_request_draft",
            "summary": "old optional authority draft",
            "created_at": "2026-06-14T00:00:00Z",
        }
        active = {
            "record_schema": "being_memory_v1",
            "record_type": "draft",
            "memory_id": "mem_recent",
            "card_type": "read_only_action_draft",
            "summary": "recent optional draft",
            "created_at": "2026-06-17T23:00:00Z",
        }
        append_jsonl(thread_dir / "being_memory.jsonl", legacy)
        append_jsonl(thread_dir / "being_memory.jsonl", active)
        classified = classify_drafts([legacy, active], now=now)
        assert len(classified["active"]) == 1
        assert len(classified["legacy"]) == 1
        payload = build_summary(
            thread_dir,
            timestamp="2026-06-18T00:00:00Z",
            now=now,
        )
        assert payload["write_status"] == "write_needed"
        assert payload["legacy_retention_count"] == 1
        append_jsonl(thread_dir / "legacy_memory_retention_summaries.jsonl", payload["record"])
        second = build_summary(
            thread_dir,
            timestamp="2026-06-18T00:01:00Z",
            now=now,
        )
        assert second["write_status"] == "already_current"
        assert "must respond" not in json.dumps(second).lower()
        assert "runtime_change" in render_markdown(second)
    print("legacy_memory_retention_summary self-test OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--thread", help="Thread id or substring; defaults to active thread")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    thread_dir = active_thread_dir(args.workspace, args.thread)
    payload = build_summary(thread_dir)
    if args.write and payload["write_status"] == "write_needed":
        append_jsonl(thread_dir / "legacy_memory_retention_summaries.jsonl", payload["record"])
        payload["write_status"] = "written"
        payload["written_path"] = str(thread_dir / "legacy_memory_retention_summaries.jsonl")
    elif args.write:
        payload["written_path"] = None
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
