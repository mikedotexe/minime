"""Bounded failed-provider evidence; never a journal, prompt or delivery receipt."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import uuid

from . import generation_record

WIRE_BYTES = 65536


def _bounded_wire(text: str) -> dict:
    raw = text.encode("utf-8")
    kept = raw[:WIRE_BYTES].decode("utf-8", errors="ignore")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "retained_bytes": len(kept.encode("utf-8")), "truncated": len(raw) > WIRE_BYTES,
            "text": kept}


class StudyAttemptDiagnostics:
    def __init__(self, workspace: Path, output: dict, request_json: str):
        self.directory = workspace / "diagnostics/source_study_attempts"
        self.request_json = request_json
        self.response_json = None
        self.summary = {}
        self.record = {"schema": "source_study_failed_attempt_v1", "attempt_id": uuid.uuid4().hex,
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "page_id": (output.get("page") or {}).get("id"),
                       "navigation_id": output.get("navigation_id"),
                       "input_kind": output.get("input_kind"), "question_id": output.get("question_id"),
                       "evidence_scope": "Provider attempt only; no journal or accepted source delivery is implied."}
        self.retained = False

    def response(self, response):
        """Observe the HTTP body before parsing/cleaning can discard it."""
        self.response_json = response.text
        self.record["http_status"] = response.status_code
        if response.status_code != 200:
            self.fail("http_error")
            return
        try:
            parsed = json.loads(self.response_json)
            if "choices" in parsed:
                choice = parsed["choices"][0]
                message = choice.get("message", {})
                finish = choice.get("finish_reason")
                done = finish is not None
            else:
                message = parsed.get("message", {})
                finish = parsed.get("done_reason")
                done = parsed.get("done")
            content = message.get("content", "")
            if not isinstance(content, str):
                raise ValueError("non-text source-study response")
            self.summary.update(native_finish=finish, native_done=done,
                                raw_content_chars=len(content), thinking_chars=len(message.get("thinking") or ""),
                                provider_eval_count=parsed.get("eval_count"))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            self.fail("invalid_provider_response")

    def cleaned(self, content):
        self.summary["cleaned_content_chars"] = len(content) if isinstance(content, str) else 0
        if not content:
            self.fail("empty_final" if not self.summary.get("raw_content_chars") else "cleaned_empty")
        elif self.summary.get("native_finish") in {"length", "max_tokens"}:
            self.fail("output_limit")
        elif self.summary.get("native_done") is False:
            self.fail("incomplete_response")

    def fail(self, reason: str, error: Exception | None = None):
        """Diagnostics must never alter provider success, retry or acceptance policy."""
        try:
            if self.retained or not generation_record.enabled():
                return
            self.summary["source_study_failure"] = reason
            self.record.update(self.summary)
            if error is not None:
                self.record["error_type"] = type(error).__name__
            self.record["request"] = _bounded_wire(self.request_json)
            self.record["response"] = _bounded_wire(self.response_json) if self.response_json is not None else None
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
            path = self.directory / f"attempt_{self.record['attempt_id']}.json"
            temporary = path.with_suffix(".json.pending")
            with open(temporary, "x", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
                json.dump(self.record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
            self.summary["source_study_diagnostic_path"] = str(path)
            self.retained = True
        except Exception:
            logging.getLogger(__name__).debug("Source-study diagnostic could not be retained", exc_info=True)
