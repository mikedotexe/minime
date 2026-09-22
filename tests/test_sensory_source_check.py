"""Synthetic snapshots only; no contacts with the live engine or status writers."""
from copy import deepcopy
import json

import pytest

from scripts import sensory_source_check as check
from scripts.sensory_check_evidence import intake_state

NOW = 100_000


def records():
    return {
        "spectral": {
            "provenance": {"wall_clock_unix_ms": NOW, "session_id": 1},
            "modalities": {
                "video_source": "external", "video_age_ms": 100,
                "video_freshness_class": "fresh_sample",
                "audio_source": "external", "audio_age_ms": 100,
                "audio_freshness_class": "fresh_sample",
            },
        },
        "health": {
            "provenance": {"wall_clock_unix_ms": NOW, "session_id": 1},
            "sensory": {"live_video_enabled": True, "live_audio_enabled": True,
                        "live_video_divisor": 12, "live_audio_divisor": 12,
                        "admit_fraction": 0.12},
        },
        "camera": {"ts_ms": NOW, "healthy": True, "connected": True,
                   "fps": 0.2, "last_frame_age_ms": 0, "frame_health_grace_secs": 10},
        "mic": {"ts_ms": NOW, "healthy": True, "connected": True,
                "chunk_interval_ms": 500, "last_chunk_age_ms": 0,
                "chunk_health_grace_secs": 5},
        "sensory": {"updated_at_ms": NOW, "video": {"source": "physical"},
                    "audio": {"source": "physical"}},
    }


def report(data):
    original = deepcopy(data)
    result = check.build_sensory_freshness_v1(**data, observed_at_ms=NOW)
    assert data == original
    return result


@pytest.mark.parametrize("value,state", [
    (0, "zero_probability"), (None, "unknown"), ("bad", "invalid"),
    (-0.1, "invalid"), (1.1, "invalid"), (float("inf"), "invalid"),
    (float("nan"), "invalid"), (True, "invalid"),
])
def test_gate_never_becomes_optimistic_default(value, state):
    data = records()
    data["health"]["sensory"]["admit_fraction"] = value
    assert check._live_intake_state("video", data["spectral"], data["health"])["state"] == state
    assert check._expected_engine_interval_ms("video", data["camera"], data["spectral"], data["health"]) is None


@pytest.mark.parametrize("value,state", [
    (0, "disabled"), (None, "unknown"), (1.5, "invalid"), (False, "invalid"),
    (-1, "invalid"), (2**32, "invalid"), (float("inf"), "invalid"),
])
def test_divisor_evidence(value, state):
    budget = records()["health"]["sensory"]
    budget["live_video_divisor"] = value
    assert intake_state(budget, "video")["state"] == state


@pytest.mark.parametrize("enabled,state", [(False, "disabled"), (None, "unknown"), ("false", "invalid")])
def test_enabled_is_not_inferred(enabled, state):
    budget = records()["health"]["sensory"]
    budget["live_video_enabled"] = enabled
    assert intake_state(budget, "video")["state"] == state


def test_conditional_estimate_never_claims_held_input_or_application():
    data = records()
    data["spectral"]["modalities"].update(video_source="stale", video_age_ms=60_000,
                                        video_freshness_class="stale_beyond_engine_window")
    result = report(data)
    row = result["lanes"]["video"]
    assert row["expected_engine_interval_ms"] == 500_000
    assert row["status"] == "engine_stale_within_conditional_cadence"
    assert result["status"] == "watch"
    assert row["applied_to_esn"] is None and row["applied_to_covariance"] is None


def test_missing_audio_cadence_has_no_silent_500ms_default():
    data = records()
    del data["mic"]["chunk_interval_ms"]
    assert report(data)["lanes"]["audio"]["expected_engine_interval_ms"] is None


@pytest.mark.parametrize("kind", ["spectral", "health", "camera", "mic", "sensory"])
@pytest.mark.parametrize("age,state", [(20_000, "stale"), (-1, "future"), (None, "unknown")])
def test_independent_record_clocks(kind, age, state):
    data = records()
    record = data[kind]
    if kind in {"spectral", "health"}:
        record = record["provenance"]
        key = "wall_clock_unix_ms"
    else:
        key = "updated_at_ms" if kind == "sensory" else "ts_ms"
    record[key] = NOW - age if age is not None else None
    result = report(data)
    assert result["snapshot_clocks"][kind]["state"] == state
    if kind == "spectral":
        assert result["lanes"]["video"]["status"] == "unverified_engine_clock"
    if kind in {"spectral", "health", "camera"}:
        assert result["lanes"]["video"]["expected_engine_interval_ms"] is None


def test_age_advances_since_snapshot_and_can_expire_fresh_class():
    data = records()
    data["spectral"]["provenance"]["wall_clock_unix_ms"] -= 2500
    data["camera"]["ts_ms"] -= 3000
    row = report(data)["lanes"]["video"]
    assert row["engine_age_ms"] == 2600
    assert row["client_age_ms"] == 3000
    assert row["engine_age_at_snapshot_ms"] == 100
    assert row["status"] != "engine_fresh_or_held"


@pytest.mark.parametrize("session", [None, 2])
def test_cross_session_budget_is_not_combined(session):
    data = records()
    data["health"]["provenance"]["session_id"] = session
    row = report(data)["lanes"]["video"]
    assert row["intake_evidence"] == "unverified_session_alignment"
    assert row["expected_engine_interval_ms"] is None


def test_missing_engine_is_not_ok_even_with_host_fallback():
    data = records()
    data["spectral"] = None
    data["sensory"]["video"]["source"] = "host"
    result = report(data)
    assert result["status"] == "watch"
    assert result["lanes"]["video"]["status"] == "missing_engine_status"


@pytest.mark.parametrize("age", [100, 10_000])
def test_synthetic_is_not_client_failure_and_does_not_hide_age(age):
    data = records()
    data["spectral"]["modalities"].update(audio_source="synthetic", audio_age_ms=age,
                                        audio_freshness_class="synthetic_or_mixed")
    row = report(data)["lanes"]["audio"]
    assert row["client_healthy"] is True
    assert row["status"] != "client_unhealthy_or_disconnected"
    assert (row["status"] == "engine_synthetic_recent") == (age <= 2000)


def test_corrupt_top_level_and_missing_files(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    assert check._safe_load_json(bad) == (None, "status must be a JSON object")
    for name in ("SENSORY_SOURCE_PATH", "CAMERA_STATUS_PATH", "MIC_STATUS_PATH", "SPECTRAL_STATE_PATH", "HEALTH_PATH"):
        monkeypatch.setattr(check, name, bad)
    result = check.collect()
    assert result["sensory_freshness_v1"]["status"] == "watch"
    assert "ERROR" in check.render_markdown(result)


def test_collect_uses_snapshot_clock_not_recent_mtime(tmp_path, monkeypatch):
    data = records()
    data["camera"]["ts_ms"] -= 20_000
    monkeypatch.setattr(check.time, "time", lambda: NOW / 1000)
    for kind, name in (("spectral", "SPECTRAL_STATE_PATH"), ("health", "HEALTH_PATH"),
                       ("camera", "CAMERA_STATUS_PATH"), ("mic", "MIC_STATUS_PATH"),
                       ("sensory", "SENSORY_SOURCE_PATH")):
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(data[kind]))
        monkeypatch.setattr(check, name, path)
    result = check.collect()
    assert result["camera_frame_age"] == 20
    assert result["sensory_freshness_v1"]["snapshot_clocks"]["camera"]["state"] == "stale"
