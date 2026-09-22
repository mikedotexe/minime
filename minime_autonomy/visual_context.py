"""Visual input selection and provenance; no camera, model or control calls."""

from __future__ import annotations

from datetime import datetime
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from functools import lru_cache

from .journal_context import visual_observation
from .parsing import eligible_choice_line_indices, final_bare_choice_index

AMBIENT_MAX_AGE_S = 300
MAX_RECORD_BYTES = 1_048_576
MAX_RESPONSE_FILES = 2048


def recorded_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        # Historical service records used local naive timestamps.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def response_signature(directory: Path) -> tuple:
    paths = [*directory.glob("response_*.json"), *(directory / "processed").glob("response_*.json")]
    ranked = []
    for path in paths:
        try:
            stat = path.stat()
            if not path.is_symlink() and stat.st_size <= MAX_RECORD_BYTES:
                ranked.append((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, str(path)))
        except OSError:
            continue
    ranked.sort(reverse=True)
    return tuple(ranked[:MAX_RESPONSE_FILES])


def _records(signature):
    records = []
    for _, _, _, name in signature:
        path = Path(name)
        try:
            if path.is_symlink() or path.stat().st_size > MAX_RECORD_BYTES:
                continue
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                records.append((path, data))
        except (OSError, ValueError):
            continue
    return records


def response_records(directory: Path) -> list[tuple[Path, dict]]:
    return _records(response_signature(directory))


def visual_content_identity(data: dict) -> str:
    fields = {key: data.get(key) for key in (
        "description", "source", "analysis_type", "visual_available", "error",
    )}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def ambient_visual_context(workspace: Path, *, captured_at: datetime) -> str:
    """Reserve fresh changed text once, only for a selected metrics-bearing input.

    Reservation means prompt assembly, not model delivery or understanding. A
    failed/compacted generation does not trigger unsolicited replay. Historical
    response files and explicit visual reflection remain unchanged.
    """
    now = captured_at.timestamp()
    try:
        candidates = []
        for path, data in response_records(workspace / "visual_responses"):
            stamp = recorded_time(data.get("response_timestamp"))
            if stamp is not None and 0 <= now - stamp <= AMBIENT_MAX_AGE_S:
                candidates.append((stamp, str(path), data))
        if not candidates:
            return ""
        _, source_path, data = max(candidates, key=lambda item: (item[0], item[1]))
        identity = visual_content_identity(data)
        runtime = workspace / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        state = runtime / "ambient_visual_context_v1.json"
        lock = runtime / "ambient_visual_context_v1.lock"
        if state.is_symlink() or lock.is_symlink():
            return ""
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if state.exists():
                if state.stat().st_size > 4096:
                    return ""
                previous = json.loads(state.read_text())
                if not isinstance(previous, dict) or previous.get("schema") != "ambient_visual_context_v1":
                    return ""
                if (not re.fullmatch(r"[a-f0-9]{64}", str(previous.get("content_sha256", "")))
                        or previous.get("scope") != "prompt_assembly_not_delivery"):
                    return ""
                if previous.get("content_sha256") == identity:
                    return ""
            payload = {
                "schema": "ambient_visual_context_v1", "content_sha256": identity,
                "response_path": source_path, "response_timestamp": data.get("response_timestamp"),
                "reserved_at": captured_at.isoformat(), "scope": "prompt_assembly_not_delivery",
            }
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", dir=runtime, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(payload, output, sort_keys=True)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(state)
                directory_fd = os.open(runtime, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return visual_observation(data, captured_at=captured_at, max_chars=300)
    except (OSError, ValueError, TypeError):
        # Unknown/corrupt state must not restart a repeating context stream.
        return ""


def vision_prompt_parts(text: object) -> tuple[str, list[str]]:
    """Separate top-level NEXT lines using the shared choice scanner, not a new parser."""
    if not isinstance(text, str):
        return "", []
    lines = text.splitlines()
    eligible = eligible_choice_line_indices(lines)
    selected = {index for index in eligible
                if lines[index].strip().upper().startswith("NEXT:")}
    if not selected:
        bare = final_bare_choice_index(lines, eligible)
        if bare is not None:
            selected.add(bare)
    return ("\n".join(line for index, line in enumerate(lines) if index not in selected).strip(),
            [lines[index] for index in sorted(selected)])


@lru_cache(maxsize=1)
def _freshness_clocks(signature):
    # Polling unchanged status must not repeatedly decode archived base64 images.
    records = _records(signature)
    stamps = [(recorded_time(data.get("response_timestamp")), data) for _, data in records]
    known = [(stamp, data) for stamp, data in stamps if stamp is not None]
    latest = max(known, key=lambda item: item[0]) if known else None
    captures = [recorded_time(data.get("capture_timestamp")) for _, data in records
                if data.get("visual_available") is True]
    return (latest[0] if latest else None,
            latest[1].get("response_timestamp") if latest else None,
            tuple(stamp for stamp in captures if stamp is not None), len(records))


def visual_freshness(directory: Path, *, now: float) -> dict:
    """Response freshness is separate from poll-loop health and capture evidence."""
    stamp, latest_timestamp, captures, count = _freshness_clocks(response_signature(directory))
    age = now - stamp if stamp is not None else None
    captures = [stamp for stamp in captures if stamp <= now]
    return {
        "schema": "visual_freshness_v1", "automatic_context_max_age_s": AMBIENT_MAX_AGE_S,
        "response_age_s": age if age is not None and age >= 0 else None,
        "response_freshness": ("unknown" if age is None else "clock_mismatch" if age < 0
                               else "fresh" if age <= AMBIENT_MAX_AGE_S else "stale"),
        "latest_response_timestamp": latest_timestamp,
        "response_clock_scope": "latest_valid_timestamp_in_bounded_scan",
        "last_frame_acquired_age_s": now - max(captures) if captures else None,
        "capture_clock_scope": "service_frame_acquisition; not_host_image_creation; legacy_response_time_not_capture_time",
        "scan_limit": MAX_RESPONSE_FILES, "records_examined": count,
        "authority": "status_only_no_capture_or_retry",
    }
