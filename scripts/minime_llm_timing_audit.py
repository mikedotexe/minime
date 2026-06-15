#!/usr/bin/env python3
"""Summarize Minime LLM timing diagnostics by prompt class.

The audit never reads or writes raw prompts. It works only from the compact
metadata already emitted to `workspace/diagnostics/llm_timing.jsonl`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


MINIME_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMING_PATH = MINIME_ROOT / "workspace/diagnostics/llm_timing.jsonl"
DEFAULT_OUTPUT_ROOT = MINIME_ROOT / "workspace/diagnostics/llm_timing_audits"


def run_id() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def load_records(path: Path, *, hours: float) -> list[dict[str, Any]]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=max(0.0, hours))
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_timestamp(record.get("timestamp"))
            if timestamp is None or timestamp < cutoff:
                continue
            records.append(record)
    return records


def percentile(values: Iterable[float], pct: float) -> float | None:
    ordered = sorted(value for value in values if isinstance(value, (int, float)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(float(ordered[0]), 3)
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return round(float(ordered[rank]), 3)


def numeric_values(records: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for record in records:
        value = record.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def average(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def is_timeout(record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").lower()
    error = str(record.get("error") or "").lower()
    return "timeout" in status or "timeout" in error or "readtimeout" in error


def is_fallback(record: dict[str, Any]) -> bool:
    return "fast" in str(record.get("backend") or "").lower()


def is_thin_fallback_success(record: dict[str, Any], *, thin_chars: int) -> bool:
    return (
        record.get("status") == "ok"
        and is_fallback(record)
        and isinstance(record.get("response_chars"), (int, float))
        and int(record.get("response_chars") or 0) <= thin_chars
    )


def group_summary(
    key: tuple[str, str, str],
    records: list[dict[str, Any]],
    *,
    thin_chars: int,
) -> dict[str, Any]:
    prompt_class, model, backend = key
    elapsed = numeric_values(records, "elapsed_s")
    response_chars = numeric_values(records, "response_chars")
    eval_counts = numeric_values(records, "eval_count")
    prompt_chars = numeric_values(records, "prompt_chars")
    system_chars = numeric_values(records, "system_chars")
    adapted_prompt_chars = numeric_values(records, "adapted_prompt_chars")
    compacted = sum(1 for record in records if bool(record.get("prompt_compacted")))
    fallback_count = sum(1 for record in records if is_fallback(record))
    ok_records = [record for record in records if record.get("status") == "ok"]
    thin_fallback = sum(
        1 for record in ok_records if is_thin_fallback_success(record, thin_chars=thin_chars)
    )
    return {
        "prompt_class": prompt_class,
        "model": model,
        "backend": backend,
        "call_count": len(records),
        "ok_count": len(ok_records),
        "timeout_count": sum(1 for record in records if is_timeout(record)),
        "fallback_count": fallback_count,
        "thin_fallback_count": thin_fallback,
        "elapsed_s": {
            "p50": percentile(elapsed, 50),
            "p95": percentile(elapsed, 95),
            "max": round(max(elapsed), 3) if elapsed else None,
        },
        "response_chars": {
            "avg": average(response_chars),
            "max": round(max(response_chars), 3) if response_chars else None,
        },
        "prompt_chars": {
            "avg": average(prompt_chars),
            "max": round(max(prompt_chars), 3) if prompt_chars else None,
        },
        "system_chars": {
            "avg": average(system_chars),
            "max": round(max(system_chars), 3) if system_chars else None,
        },
        "adapted_prompt_chars": {
            "avg": average(adapted_prompt_chars),
            "max": round(max(adapted_prompt_chars), 3) if adapted_prompt_chars else None,
        },
        "compaction_rate": round(compacted / len(records), 3) if records else 0.0,
        "eval_count": {
            "p50": percentile(eval_counts, 50),
            "p95": percentile(eval_counts, 95),
            "max": round(max(eval_counts), 3) if eval_counts else None,
        },
    }


def summarize_records(
    records: list[dict[str, Any]],
    *,
    hours: float,
    thin_chars: int = 80,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        prompt_class = str(record.get("prompt_class") or "unknown")
        model = str(record.get("model") or "unknown")
        backend = str(record.get("backend") or "unknown")
        grouped[(prompt_class, model, backend)].append(record)
        by_class[prompt_class].append(record)

    groups = [
        group_summary(key, bucket, thin_chars=thin_chars)
        for key, bucket in sorted(grouped.items())
    ]
    class_risks = []
    for prompt_class, bucket in by_class.items():
        elapsed = numeric_values(bucket, "elapsed_s")
        class_risks.append(
            {
                "prompt_class": prompt_class,
                "call_count": len(bucket),
                "timeout_count": sum(1 for record in bucket if is_timeout(record)),
                "fallback_count": sum(1 for record in bucket if is_fallback(record)),
                "thin_success_count": sum(
                    1
                    for record in bucket
                    if is_thin_fallback_success(record, thin_chars=thin_chars)
                ),
                "p95_elapsed_s": percentile(elapsed, 95),
                "max_elapsed_s": round(max(elapsed), 3) if elapsed else None,
            }
        )
    class_risks.sort(
        key=lambda item: (
            int(item["timeout_count"]),
            int(item["thin_success_count"]),
            int(item["fallback_count"]),
            float(item["p95_elapsed_s"] or 0.0),
            int(item["call_count"]),
        ),
        reverse=True,
    )
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "window_hours": hours,
        "record_count": len(records),
        "groups": groups,
        "top_risk_classes": class_risks[:8],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Minime LLM Timing Audit",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- window_hours: `{summary['window_hours']}`",
        f"- records: `{summary['record_count']}`",
        "",
        "## Top Risk Classes",
        "",
    ]
    risks = summary.get("top_risk_classes") or []
    if risks:
        for risk in risks:
            lines.append(
                f"- {risk['prompt_class']}: calls={risk['call_count']}, "
                f"timeouts={risk['timeout_count']}, fallbacks={risk['fallback_count']}, "
                f"thin_successes={risk['thin_success_count']}, "
                f"p95={risk['p95_elapsed_s']}, max={risk['max_elapsed_s']}"
            )
    else:
        lines.append("- no records in window")
    lines.extend(["", "## Groups", ""])
    for group in summary.get("groups") or []:
        elapsed = group.get("elapsed_s") or {}
        prompt_chars = group.get("prompt_chars") or {}
        eval_count = group.get("eval_count") or {}
        lines.append(
            f"- {group['prompt_class']} / {group['model']} / {group['backend']}: "
            f"calls={group['call_count']}, ok={group['ok_count']}, "
            f"timeouts={group['timeout_count']}, fallbacks={group['fallback_count']}, "
            f"thin_fallbacks={group['thin_fallback_count']}, "
            f"elapsed p50/p95/max={elapsed.get('p50')}/{elapsed.get('p95')}/{elapsed.get('max')}, "
            f"prompt avg/max={prompt_chars.get('avg')}/{prompt_chars.get('max')}, "
            f"compaction={group['compaction_rate']}, "
            f"eval p50/p95={eval_count.get('p50')}/{eval_count.get('p95')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing-path", type=Path, default=DEFAULT_TIMING_PATH)
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--thin-chars", type=int, default=80)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    records = load_records(args.timing_path, hours=args.hours)
    summary = summarize_records(records, hours=args.hours, thin_chars=args.thin_chars)
    target = args.output_dir / (args.run_id or run_id())
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "audit.json"
    md_path = target / "audit.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(f"minime llm timing audit: {md_path}")
    if args.print_summary:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
