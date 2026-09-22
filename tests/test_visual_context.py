"""Synthetic records only; never capture images or contact a model."""

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from unittest.mock import patch

import pytest

from minime_autonomy.visual_context import (
    ambient_visual_context, visual_freshness, vision_prompt_parts,
)

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def record(workspace, name="new", **fields):
    directory = workspace / "visual_responses"
    directory.mkdir(exist_ok=True)
    path = directory / f"response_{name}.json"
    path.write_text(json.dumps({
        "description": "A window", "analysis_type": "llava", "source": "physical",
        "visual_available": True, "response_timestamp": NOW.isoformat(), **fields,
    }))
    return path


def reserve(workspace):
    return ambient_visual_context(workspace, captured_at=NOW)


@pytest.mark.parametrize("stamp", [None, "invalid", (NOW + timedelta(seconds=1)).isoformat(),
                                       (NOW - timedelta(days=105)).isoformat()])
def test_unknown_future_and_old_responses_stay_quiet_despite_new_mtime(tmp_path, stamp):
    path = record(tmp_path, response_timestamp=stamp)
    before = path.read_bytes()
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    assert reserve(tmp_path) == ""
    assert path.read_bytes() == before
    assert not (tmp_path / "runtime").exists()


def test_changed_content_once_across_fresh_receipts_and_processes(tmp_path):
    record(tmp_path)
    with ProcessPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(reserve, [tmp_path] * 6))
    assert sum(bool(result) for result in results) == 1
    assert reserve(tmp_path) == ""
    record(tmp_path, "newer", request_id="another request")
    assert reserve(tmp_path) == ""
    record(tmp_path, "newer", description="A door")
    assert "A door" in reserve(tmp_path)
    assert reserve(tmp_path) == ""
    state = json.loads((tmp_path / "runtime/ambient_visual_context_v1.json").read_text())
    assert state["scope"] == "prompt_assembly_not_delivery"


@pytest.mark.parametrize("content", ["{broken", '{"schema":"ambient_visual_context_v1"}'])
def test_corrupt_reservation_fails_quiet_without_rewriting(tmp_path, content):
    record(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    state = runtime / "ambient_visual_context_v1.json"
    state.write_text(content)
    assert reserve(tmp_path) == ""
    assert state.read_text() == content


def test_response_time_not_file_time_selects_latest(tmp_path):
    record(tmp_path, "old", description="Old", response_timestamp=(NOW - timedelta(seconds=90)).isoformat())
    new = record(tmp_path, description="New")
    os.utime(new, (1, 1))
    assert "New" in reserve(tmp_path)


def test_health_freshness_requires_separate_capture_clock(tmp_path):
    path = record(tmp_path, response_timestamp=(NOW - timedelta(days=105)).isoformat())
    result = visual_freshness(path.parent, now=NOW.timestamp())
    assert result["response_freshness"] == "stale"
    assert result["last_frame_acquired_age_s"] is None
    record(tmp_path, capture_timestamp=(NOW - timedelta(seconds=40)).isoformat())
    result = visual_freshness(path.parent, now=NOW.timestamp())
    assert result["response_age_s"] == 0
    assert result["last_frame_acquired_age_s"] == 40


def test_choice_lines_separated_without_parsing_or_modifying_quotes():
    assert vision_prompt_parts("NEXT: EXPERIMENT_PLAN 4") == ("", ["NEXT: EXPERIMENT_PLAN 4"])
    prose = "Describe the window.\n> NEXT: REST\n```text\nNEXT: SEARCH quoted\n```"
    text, actions = vision_prompt_parts(prose + "\nNEXT: REST")
    assert text == prose
    assert actions == ["NEXT: REST"]
    assert vision_prompt_parts("SELF_STUDY OPEN astrid/src/lib.rs 1") == (
        "", ["SELF_STUDY OPEN astrid/src/lib.rs 1"])


def test_freshness_caches_metadata_but_not_age_and_invalidates_changes(tmp_path):
    from minime_autonomy import visual_context as module
    path = record(tmp_path)
    with patch.object(module, "_records", wraps=module._records) as reads:
        assert visual_freshness(path.parent, now=NOW.timestamp())["response_age_s"] == 0
        assert visual_freshness(path.parent, now=NOW.timestamp() + 400)["response_freshness"] == "stale"
        assert reads.call_count == 1
        record(tmp_path, response_timestamp=(NOW + timedelta(seconds=400)).isoformat())
        assert visual_freshness(path.parent, now=NOW.timestamp() + 400)["response_age_s"] == 0
        assert reads.call_count == 2
