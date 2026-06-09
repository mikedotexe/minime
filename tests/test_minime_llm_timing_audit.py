"""Tests for scripts/minime_llm_timing_audit.py."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/minime_llm_timing_audit.py"
SPEC = importlib.util.spec_from_file_location("minime_llm_timing_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


class MinimeLlmTimingAuditTests(unittest.TestCase):
    def test_summarizes_prompt_class_latency_and_risk(self) -> None:
        now = dt.datetime.now(dt.UTC).isoformat()
        records = [
            {
                "timestamp": now,
                "prompt_class": "private_journal",
                "backend": "ollama",
                "model": "gemma4:12b",
                "status": "ok",
                "elapsed_s": 4.0,
                "response_chars": 240,
                "prompt_chars": 1400,
                "system_chars": 500,
                "adapted_prompt_chars": 1400,
                "prompt_compacted": False,
                "eval_count": 80,
            },
            {
                "timestamp": now,
                "prompt_class": "autonomous_next",
                "backend": "ollama_fast",
                "model": "gemma3:4b",
                "status": "error",
                "error": "ReadTimeout",
                "elapsed_s": 60.0,
                "response_chars": 0,
                "prompt_chars": 18000,
                "system_chars": 7000,
                "adapted_prompt_chars": 9000,
                "prompt_compacted": True,
            },
        ]

        summary = audit.summarize_records(records, hours=2, thin_chars=80)

        self.assertEqual(summary["record_count"], 2)
        risks = summary["top_risk_classes"]
        self.assertEqual(risks[0]["prompt_class"], "autonomous_next")
        self.assertEqual(risks[0]["timeout_count"], 1)
        groups = {
            (group["prompt_class"], group["model"], group["backend"]): group
            for group in summary["groups"]
        }
        self.assertEqual(
            groups[("autonomous_next", "gemma3:4b", "ollama_fast")][
                "fallback_count"
            ],
            1,
        )
        self.assertEqual(
            groups[("autonomous_next", "gemma3:4b", "ollama_fast")][
                "compaction_rate"
            ],
            1.0,
        )

    def test_load_records_filters_to_recent_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_timing.jsonl"
            recent = dt.datetime.now(dt.UTC).isoformat()
            old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)).isoformat()
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"timestamp": old, "prompt_class": "old"}),
                        json.dumps({"timestamp": recent, "prompt_class": "new"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = audit.load_records(path, hours=2)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["prompt_class"], "new")


if __name__ == "__main__":
    unittest.main()
