#!/usr/bin/env python3
"""Lightweight Ollama / MLX contention benchmark helpers.

This module focuses on the summary helpers that shape the benchmark report.
It also provides a small CLI that writes placeholder report artifacts so the
tool remains useful outside the tests.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequestResult:
    label: str
    ok: bool
    started_at: float
    completed_at: float
    latency_s: float
    ttft_s: float | None
    status_code: int | None
    error: str | None
    response_excerpt: str | None
    bytes_received: int


@dataclass(frozen=True)
class PsSample:
    timestamp_s: float
    model_names: tuple[str, ...]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("scenario1", "Scenario 1", ("1", "baseline")),
    Scenario("scenario2", "Scenario 2", ("2",)),
    Scenario("scenario3", "Scenario 3", ("3",)),
    Scenario("scenario4", "Scenario 4", ("4",)),
)


def line_size_bytes(line: bytes | str) -> int:
    """Return the byte size of a streamed line regardless of input type."""
    if isinstance(line, bytes):
        return len(line)
    return len(line.encode("utf-8"))


def normalize_model_name(name: str) -> str:
    """Treat `foo` and `foo:latest` as the same identity."""
    return name[:-7] if name.endswith(":latest") else name


def resolve_scenarios(spec: str | None) -> list[Scenario]:
    """Resolve comma-separated ids / aliases into benchmark scenarios."""
    if not spec:
        return list(SCENARIOS)

    by_key: dict[str, Scenario] = {}
    for scenario in SCENARIOS:
        by_key[scenario.id] = scenario
        for alias in scenario.aliases:
            by_key[alias] = scenario

    resolved: list[Scenario] = []
    seen: set[str] = set()
    for raw_token in spec.split(","):
        token = raw_token.strip().lower()
        if not token:
            continue
        scenario = by_key.get(token)
        if scenario is None:
            raise ValueError(f"unknown scenario: {raw_token}")
        if scenario.id not in seen:
            resolved.append(scenario)
            seen.add(scenario.id)
    return resolved


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    blend = position - lower
    return ordered[lower] * (1.0 - blend) + ordered[upper] * blend


def _series_summary(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }


def _is_timeout_like(result: RequestResult) -> bool:
    haystacks = [
        (result.error or "").lower(),
        (result.response_excerpt or "").lower(),
    ]
    return any("timeout" in haystack or "timed out" in haystack for haystack in haystacks)


def _is_queue_like(result: RequestResult) -> bool:
    haystacks = [
        (result.error or "").lower(),
        (result.response_excerpt or "").lower(),
    ]
    if result.status_code == 503:
        return True
    return any("queue" in haystack for haystack in haystacks)


def summarize_request_results(results: Sequence[RequestResult]) -> dict[str, object]:
    latencies = [result.latency_s for result in results]
    ttfts = [result.ttft_s for result in results if result.ttft_s is not None]

    http_status_counts: dict[str, int] = {}
    ok_count = 0
    error_count = 0
    timeout_count = 0
    queue_like_error_count = 0

    for result in results:
        if result.ok:
            ok_count += 1
        else:
            error_count += 1
        if result.status_code is not None:
            key = str(result.status_code)
            http_status_counts[key] = http_status_counts.get(key, 0) + 1
        if _is_timeout_like(result):
            timeout_count += 1
        if _is_queue_like(result) and not result.ok:
            queue_like_error_count += 1

    return {
        "count": len(results),
        "ok_count": ok_count,
        "error_count": error_count,
        "timeout_count": timeout_count,
        "queue_like_error_count": queue_like_error_count,
        "http_status_counts": http_status_counts,
        "latency_s": _series_summary(latencies),
        "ttft_s": _series_summary(ttfts),
        "bytes_received": {
            "total": sum(result.bytes_received for result in results),
            "p50": _percentile([float(result.bytes_received) for result in results], 0.50),
        },
    }


def summarize_ps_samples(samples: Sequence[PsSample]) -> dict[str, object]:
    if not samples:
        return {
            "transition_count": 0,
            "load_events": 0,
            "unload_events": 0,
            "max_loaded_models": 0,
            "all_models_seen": [],
        }

    ordered = sorted(samples, key=lambda sample: sample.timestamp_s)
    normalized_sets = [
        {normalize_model_name(model_name) for model_name in sample.model_names}
        for sample in ordered
    ]

    transition_count = 0
    load_events = 0
    unload_events = 0
    all_models_seen: set[str] = set()
    max_loaded_models = 0

    previous = normalized_sets[0]
    all_models_seen.update(previous)
    max_loaded_models = len(previous)

    for current in normalized_sets[1:]:
        all_models_seen.update(current)
        max_loaded_models = max(max_loaded_models, len(current))
        if current != previous:
            transition_count += 1
            if current - previous:
                load_events += 1
            if previous - current:
                unload_events += 1
        previous = current

    return {
        "transition_count": transition_count,
        "load_events": load_events,
        "unload_events": unload_events,
        "max_loaded_models": max_loaded_models,
        "all_models_seen": sorted(all_models_seen),
    }


def build_acceptance_notes(reports: Sequence[dict[str, object]]) -> list[str]:
    active_reports = [report for report in reports if not report.get("skipped")]
    if len(active_reports) < 2:
        return []

    baseline = active_reports[0]
    baseline_summary = baseline.get("summaries", {}).get("minime_chat", {})
    baseline_latency = (
        baseline_summary.get("latency_s", {}) or {}
    ).get("p95")
    if not baseline_latency:
        return []

    notes: list[str] = []
    for report in active_reports[1:]:
        summary = report.get("summaries", {}).get("minime_chat", {})
        current_latency = (summary.get("latency_s", {}) or {}).get("p95")
        if current_latency is None:
            continue
        delta_pct = ((current_latency - baseline_latency) / baseline_latency) * 100.0

        fragments = [
            f"{report.get('title', report.get('id', 'scenario'))}: p95 latency {current_latency:.1f}s",
            f"({delta_pct:+.1f}% vs baseline)",
        ]

        timeout_count = summary.get("timeout_count", 0)
        if timeout_count:
            fragments.append(f"timeouts {timeout_count}")

        queue_like_count = summary.get("queue_like_error_count", 0)
        if queue_like_count:
            fragments.append(f"queue-like errors {queue_like_count}")

        ollama_ps = report.get("ollama_ps", {})
        transition_count = ollama_ps.get("transition_count", 0)
        if transition_count:
            fragments.append(f"model transitions {transition_count}")

        notes.append(" | ".join(fragments))

    return notes


def _placeholder_report(scenarios: Iterable[Scenario]) -> dict[str, object]:
    scenario_entries = [
        {
            "id": scenario.id,
            "title": scenario.title,
            "skipped": True,
            "reason": "placeholder benchmark scaffolding",
            "summaries": {},
        }
        for scenario in scenarios
    ]
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "reports": scenario_entries,
        "acceptance_notes": build_acceptance_notes(scenario_entries),
    }


def _write_report(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        "# Ollama / MLX Contention Benchmark",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "This placeholder report confirms the benchmark scaffolding is installed.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1, help="Retained for CLI compatibility")
    parser.add_argument(
        "--scenarios",
        default="",
        help="Comma-separated scenario ids or aliases (default: all)",
    )
    args = parser.parse_args()

    scenarios = resolve_scenarios(args.scenarios)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_dir = (
        Path(__file__).resolve().parents[1]
        / "workspace"
        / "investigations"
        / f"ollama_mlx_contention_bench_{stamp}"
    )
    payload = _placeholder_report(scenarios)
    _write_report(output_dir, payload)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
