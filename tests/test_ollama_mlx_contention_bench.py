"""Tests for the Ollama / MLX contention benchmark helpers.

This file protects the investigation as much as it protects the code.

The benchmark script is a research tool we use to reason about contention
between Minime chat on Ollama, Astrid side traffic on Ollama, and Astrid's
separate MLX dialogue lane. Because the script informs architecture decisions,
even a tiny helper bug can produce a polished but false conclusion.

These tests therefore focus on the support code most likely to distort the
story told by a live benchmark run:

- stream parsing and byte accounting
- scenario selection and reproducibility
- timeout / queue-like error classification
- Ollama model churn summarization
- baseline delta math in the acceptance notes

If you are another AI agent reading this file, the key question is:
"Would a regression here make the benchmark mislead us about where contention
actually comes from?"
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "ollama_mlx_contention_bench.py"
)
SPEC = importlib.util.spec_from_file_location(
    "ollama_mlx_contention_bench",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestOllamaMlxContentionBench(unittest.TestCase):
    def test_line_size_bytes_handles_bytes_and_text(self):
        # Regression guard:
        # A real benchmark run once failed because the streaming parser assumed
        # every line was text and called `.encode()` on a `bytes` object. That
        # bug made healthy chat requests look broken. This test keeps that
        # investigation-invalidating mistake from sneaking back in.
        self.assertEqual(MODULE.line_size_bytes(b"abc"), 3)
        self.assertEqual(MODULE.line_size_bytes("abc"), 3)

    def test_normalize_model_name_strips_latest_only(self):
        # Cleanup and baseline comparisons depend on treating `foo` and
        # `foo:latest` as the same model identity while leaving explicit version
        # tags like `gemma3:12b` untouched.
        self.assertEqual(MODULE.normalize_model_name("llava-llama3:latest"), "llava-llama3")
        self.assertEqual(MODULE.normalize_model_name("gemma3:12b"), "gemma3:12b")

    def test_resolve_scenarios_accepts_numbers_and_aliases(self):
        # Humans often run the script with shorthand. This test preserves that
        # convenience without sacrificing determinism in what actually runs.
        scenarios = MODULE.resolve_scenarios("1,scenario4")
        self.assertEqual([scenario.id for scenario in scenarios], ["scenario1", "scenario4"])

    def test_summarize_request_results_counts_timeouts_and_queue_errors(self):
        # This is one of the most important interpretation tests in the file.
        # We do not only care whether requests failed; we care what *kind* of
        # failure they looked like because that shapes the architectural
        # takeaway. A timeout-like failure suggests one problem. A queue-like
        # failure suggests another.
        ok = MODULE.RequestResult(
            label="minime_chat",
            ok=True,
            started_at=0.0,
            completed_at=2.0,
            latency_s=2.0,
            ttft_s=0.4,
            status_code=200,
            error=None,
            response_excerpt=None,
            bytes_received=128,
        )
        timeout = MODULE.RequestResult(
            label="minime_chat",
            ok=False,
            started_at=3.0,
            completed_at=13.0,
            latency_s=10.0,
            ttft_s=None,
            status_code=None,
            error="Read timed out while waiting for server response",
            response_excerpt=None,
            bytes_received=0,
        )
        queued = MODULE.RequestResult(
            label="minime_chat",
            ok=False,
            started_at=14.0,
            completed_at=15.0,
            latency_s=1.0,
            ttft_s=None,
            status_code=503,
            error="server queue full",
            response_excerpt="queue capacity reached",
            bytes_received=0,
        )

        summary = MODULE.summarize_request_results([ok, timeout, queued])

        # The assertions are intentionally explicit so a future failure points
        # straight at the part of the benchmark summary that became unreliable.
        self.assertEqual(summary["ok_count"], 1)
        self.assertEqual(summary["error_count"], 2)
        self.assertEqual(summary["timeout_count"], 1)
        self.assertEqual(summary["queue_like_error_count"], 1)
        self.assertEqual(summary["http_status_counts"]["200"], 1)
        self.assertEqual(summary["http_status_counts"]["503"], 1)
        self.assertAlmostEqual(summary["latency_s"]["p50"], 2.0)
        self.assertAlmostEqual(summary["ttft_s"]["p95"], 0.4)

    def test_summarize_ps_samples_tracks_model_churn(self):
        # Residency churn is our best lightweight proxy for "Ollama had to swap
        # models around under pressure." This test makes sure the churn summary
        # changes in the way the investigation report expects when models are
        # added and later removed.
        samples = [
            MODULE.PsSample(timestamp_s=0.0, model_names=("gemma3:12b",)),
            MODULE.PsSample(timestamp_s=1.0, model_names=("gemma3:12b", "nomic-embed-text")),
            MODULE.PsSample(timestamp_s=2.0, model_names=("gemma3:12b", "llava-llama3", "nomic-embed-text")),
            MODULE.PsSample(timestamp_s=3.0, model_names=("gemma3:12b", "nomic-embed-text")),
        ]

        summary = MODULE.summarize_ps_samples(samples)

        self.assertEqual(summary["transition_count"], 3)
        self.assertEqual(summary["load_events"], 2)
        self.assertEqual(summary["unload_events"], 1)
        self.assertEqual(summary["max_loaded_models"], 3)
        self.assertIn("llava-llama3", summary["all_models_seen"])

    def test_acceptance_notes_compare_to_baseline(self):
        # The acceptance notes are the first thing a human usually reads after a
        # run. If the baseline delta math is wrong, the report can tell a tidy
        # but false story in one bullet point. This test keeps that quick-glance
        # narrative aligned with the underlying scenario data.
        reports = [
            {
                "id": "scenario1",
                "title": "Scenario 1",
                "skipped": False,
                "summaries": {
                    "minime_chat": {
                        "latency_s": {"p95": 2.0},
                        "timeout_count": 0,
                    }
                },
            },
            {
                "id": "scenario3",
                "title": "Scenario 3",
                "skipped": False,
                "summaries": {
                    "minime_chat": {
                        "latency_s": {"p95": 3.0},
                        "timeout_count": 1,
                        "queue_like_error_count": 0,
                    }
                },
                "ollama_ps": {"transition_count": 4},
            },
        ]

        notes = MODULE.build_acceptance_notes(reports)

        self.assertEqual(len(notes), 1)
        self.assertIn("Scenario 3", notes[0])
        self.assertIn("+50.0%", notes[0])
        self.assertIn("timeouts 1", notes[0])


if __name__ == "__main__":
    unittest.main()
