#!/usr/bin/env python3
"""Sensory source check — current camera/mic source state for minime.

Reports recorded camera/mic source selection, sender status and engine lane
freshness on their separate clocks. These snapshots do not establish which
physical samples were applied to ESN or covariance.

Useful for:
- Empirical USB unplug/replug testing (`--watch 2` shows live transitions)
- Confirming "is the camera/mic working" without grepping logs
- Future-steward debugging of RMS=0 / no-frames mystery zombies

Status files this tool reads (no new instrumentation needed):
- workspace/runtime/sensory_source.json — written by host-sensory, the canonical "current source" record
- workspace/runtime/camera_status.json   — written by camera_client.py
- workspace/runtime/mic_status.json      — written by mic_to_sensory.py

Usage:
    python3 scripts/sensory_source_check.py
    python3 scripts/sensory_source_check.py --watch 2
    python3 scripts/sensory_source_check.py --json
    python3 scripts/sensory_source_check.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .sensory_check_evidence import intake_state, nonnegative_number, record_clock
except ImportError:  # Direct CLI invocation.
    from sensory_check_evidence import intake_state, nonnegative_number, record_clock

WORKSPACE = Path("/Users/v/other/minime/workspace")
RUNTIME = WORKSPACE / "runtime"
SENSORY_SOURCE_PATH = RUNTIME / "sensory_source.json"
CAMERA_STATUS_PATH = RUNTIME / "camera_status.json"
MIC_STATUS_PATH = RUNTIME / "mic_status.json"
SPECTRAL_STATE_PATH = WORKSPACE / "spectral_state.json"
HEALTH_PATH = WORKSPACE / "health.json"

# Staleness thresholds (must be larger than host-sensory's internal thresholds
# of 2s audio / 5s video to give a chance for the file write to land).
SENSORY_SOURCE_STALE_SECONDS = 10
CAMERA_STATUS_STALE_SECONDS = 10
MIC_STATUS_STALE_SECONDS = 5
ENGINE_AV_FRESH_WINDOW_MS = 2000  # Checked against runtime/semantic_modality.rs.
ENGINE_STATUS_STALE_MS = 5000
SPARSE_ADMIT_ATTENTION_MULTIPLIER = 3.0


def _safe_load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (data, error_msg). On success error_msg is None."""
    if not path.is_file():
        return None, f"file not found: {path}"
    try:
        data = json.loads(path.read_text())
        return (data, None) if isinstance(data, dict) else (None, "status must be a JSON object")
    except Exception as e:
        return None, f"failed to parse: {e}"


def _file_age_seconds(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _ms_to_seconds(ms: int | float | None) -> float | None:
    value = nonnegative_number(ms)
    return value / 1000.0 if value is not None else None


def _fmt_age(seconds: float | None, stale_threshold: float | None = None) -> str:
    if seconds is None:
        return "?"
    if seconds < 1:
        s = f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        s = f"{seconds:.1f}s"
    elif seconds < 3600:
        s = f"{seconds/60:.1f}m"
    else:
        s = f"{seconds/3600:.1f}h"
    if stale_threshold is not None and seconds > stale_threshold:
        s += " STALE"
    return s


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_positive_float(value: Any) -> float | None:
    parsed = nonnegative_number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _stable_core_sensory_budget(spectral: dict[str, Any] | None) -> dict[str, Any]:
    stable_core = _as_mapping(_as_mapping(spectral).get("stable_core"))
    return _as_mapping(stable_core.get("sensory_budget"))


def _runtime_sensory_budget(
    spectral: dict[str, Any] | None,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    budget = dict(_stable_core_sensory_budget(spectral))
    health_sensory = _as_mapping(_as_mapping(health).get("sensory"))
    # An explicitly unknown health field must not revive an older spectral value.
    budget.update(health_sensory)
    return budget


def _lane_client_age_ms(lane: str, client: dict[str, Any]) -> float | None:
    key = "last_frame_age_ms" if lane == "video" else "last_chunk_age_ms"
    seconds = _ms_to_seconds(client.get(key))
    return None if seconds is None else seconds * 1000.0


def _client_expected_interval_ms(lane: str, client: dict[str, Any]) -> float | None:
    if lane == "video":
        fps = _as_positive_float(client.get("fps"))
        return None if fps is None else 1000.0 / fps
    chunk_interval = _as_positive_float(client.get("chunk_interval_ms"))
    if chunk_interval is not None:
        return chunk_interval
    chunk_duration = _as_positive_float(client.get("chunk_duration_s"))
    if chunk_duration is not None:
        return chunk_duration * 1000.0
    return None


def _live_intake_state(
    lane: str,
    spectral: dict[str, Any] | None,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    budget = _runtime_sensory_budget(spectral, health)
    return intake_state(budget, lane)


def _expected_engine_interval_ms(
    lane: str,
    client: dict[str, Any],
    spectral: dict[str, Any] | None,
    health: dict[str, Any] | None,
) -> float | None:
    client_interval = _client_expected_interval_ms(lane, client)
    if client_interval is None:
        return None
    live_intake = _live_intake_state(lane, spectral, health)
    if live_intake["state"] != "enabled":
        return None
    estimate = client_interval * live_intake["divisor"] / live_intake["admit_fraction"]
    return estimate if math.isfinite(estimate) else None


def _classify_lane_freshness(
    *,
    lane: str,
    spectral: dict[str, Any] | None,
    health: dict[str, Any] | None,
    modalities: dict[str, Any],
    client: dict[str, Any],
    source_record: dict[str, Any],
    clocks: dict[str, dict[str, Any]],
    intake_evidence: str,
) -> dict[str, Any]:
    source_payload = _as_mapping(source_record.get(lane))
    engine_source = modalities.get(f"{lane}_source")
    engine_age_at_snapshot_ms = nonnegative_number(modalities.get(f"{lane}_age_ms"))
    engine_age_ms = (
        engine_age_at_snapshot_ms + clocks["spectral"]["age_ms"]
        if engine_age_at_snapshot_ms is not None
        and clocks["spectral"]["state"] in {"current", "stale"} else None
    )
    engine_class = modalities.get(f"{lane}_freshness_class")
    client_healthy = client.get("healthy") if isinstance(client.get("healthy"), bool) else None
    client_connected = client.get("connected") if isinstance(client.get("connected"), bool) else None
    client_clock = clocks["camera" if lane == "video" else "mic"]
    client_age_at_snapshot_ms = _lane_client_age_ms(lane, client)
    client_age_ms = (
        client_age_at_snapshot_ms + client_clock["age_ms"]
        if client_age_at_snapshot_ms is not None
        and client_clock["state"] in {"current", "stale"} else None
    )
    grace_s = client.get("frame_health_grace_secs") if lane == "video" else client.get("chunk_health_grace_secs")
    fps = client.get("fps") if lane == "video" else None
    expected_interval_ms = _client_expected_interval_ms(lane, client)
    live_intake = _live_intake_state(lane, spectral, health) if intake_evidence == "current" else intake_state({}, lane)
    expected_engine_interval_ms = (
        _expected_engine_interval_ms(lane, client, spectral, health)
        if intake_evidence == "current" and client_clock["state"] == "current" else None
    )
    grace_s = nonnegative_number(grace_s)
    expected_engine_grace_ms = None
    if expected_engine_interval_ms is not None:
        expected_engine_grace_ms = expected_engine_interval_ms + (
            float(grace_s) * 1000.0 if isinstance(grace_s, (int, float)) else 0.0
        )
    expected_engine_attention_ms = None
    if expected_engine_interval_ms is not None:
        expected_engine_attention_ms = (
            expected_engine_interval_ms * SPARSE_ADMIT_ATTENTION_MULTIPLIER
            + (float(grace_s) * 1000.0 if isinstance(grace_s, (int, float)) else 0.0)
        )

    engine_stale = (
        str(engine_source or "") in {"stale", "absent"}
        or str(engine_class or "") == "stale_beyond_engine_window"
        or (engine_age_ms is not None and engine_age_ms > ENGINE_AV_FRESH_WINDOW_MS)
    )
    engine_missing = engine_source is None and engine_class is None and engine_age_ms is None
    client_recent = (
        isinstance(client_age_ms, (int, float))
        and isinstance(grace_s, (int, float))
        and client_age_ms <= float(grace_s) * 1000.0
    )

    fallback_expected = (
        clocks["sensory"]["state"] == "current" and source_payload.get("source") == "host"
    ) or (client_clock["state"] == "current" and client.get("fallback_expected") is True)

    if engine_missing:
        status = "missing_engine_status"
        reason = "engine modality status unavailable"
    elif clocks["spectral"]["state"] != "current":
        status = "unverified_engine_clock"
        reason = "engine snapshot clock is " + clocks["spectral"]["state"]
    elif live_intake["state"] in {"disabled", "zero_probability"}:
        status = "live_intake_suppressed"
        reason = "recorded live intake is " + live_intake["state"]
    elif engine_age_ms is None:
        status = "unknown_engine_age"
        reason = "source class alone cannot establish sample freshness"
    elif not engine_stale and engine_source == "synthetic":
        status = "engine_synthetic_recent"
        reason = "recent synthetic lane evidence does not establish physical input"
    elif not engine_stale and str(engine_class or "") in {"fresh_sample", "held_within_engine_window"}:
        status = "engine_fresh_or_held"
        reason = "lane evidence is within the AV window; ESN application is not established"
    elif not client:
        status = "missing_client_status"
        reason = "client status file missing"
    elif client_clock["state"] != "current":
        status = "unverified_client_clock"
        reason = "client status clock is " + client_clock["state"]
    elif fallback_expected:
        status = "expected_host_fallback"
        reason = "host fallback is expected; this is not an engine application receipt"
    elif (
        client_healthy
        and client_connected
        and client_recent
        and engine_stale
        and isinstance(engine_age_ms, (int, float))
        and expected_engine_attention_ms is not None
        and float(engine_age_ms) <= expected_engine_attention_ms
    ):
        status = "engine_stale_within_conditional_cadence"
        reason = "stale lane; conditional cadence estimate is not evidence of holding or delivery"
    elif (
        client_healthy
        and client_connected
        and client_recent
        and engine_stale
        and isinstance(engine_age_ms, (int, float))
        and expected_engine_attention_ms is not None
        and float(engine_age_ms) > expected_engine_attention_ms
    ):
        status = "healthy_client_engine_overdue"
        reason = "stale lane beyond three conditional mean intervals; not a guaranteed deadline"
    elif (
        lane == "video"
        and client_healthy
        and client_connected
        and expected_interval_ms is not None
        and expected_interval_ms > ENGINE_AV_FRESH_WINDOW_MS
        and engine_stale
    ):
        status = "healthy_low_fps_cadence_mismatch"
        reason = "camera target FPS is slower than the engine AV freshness window"
    elif client_healthy and client_connected and client_recent and engine_stale:
        status = "healthy_client_engine_stale_mismatch"
        reason = "client is healthy/recent while engine reports the lane stale or absent"
    elif client_healthy is False or client_connected is False:
        status = "client_unhealthy_or_disconnected"
        reason = str(client.get("last_error") or client.get("state") or "client unhealthy")
    else:
        status = "unresolved_lane_evidence"
        reason = "available evidence cannot establish current delivery or client failure"

    return {
        "lane": lane,
        "status": status,
        "reason": reason,
        "engine_source": engine_source,
        "engine_age_ms": engine_age_ms,
        "engine_age_at_snapshot_ms": engine_age_at_snapshot_ms,
        "engine_clock": clocks["spectral"],
        "applied_to_esn": None,
        "applied_to_covariance": None,
        "engine_freshness_class": engine_class,
        "engine_fresh_window_ms": ENGINE_AV_FRESH_WINDOW_MS,
        "client_healthy": client_healthy,
        "client_connected": client_connected,
        "client_state": client.get("state") if client else None,
        "client_age_ms": client_age_ms,
        "client_age_at_snapshot_ms": client_age_at_snapshot_ms,
        "client_clock": client_clock,
        "fallback_expected": fallback_expected,
        "target_fps": fps,
        "expected_interval_ms": expected_interval_ms,
        "live_intake_divisor": live_intake.get("divisor"),
        "live_intake_enabled": live_intake.get("enabled"),
        "live_intake_reason": live_intake.get("reason"),
        "admit_fraction": live_intake.get("admit_fraction"),
        "live_intake_state": live_intake["state"],
        "intake_evidence": intake_evidence,
        "cadence_assumptions": "constant sender interval, divisor and independent admission probability; not a delivery guarantee",
        "expected_engine_interval_ms": expected_engine_interval_ms,
        "expected_engine_grace_ms": expected_engine_grace_ms,
        "expected_engine_attention_ms": expected_engine_attention_ms,
        "health_grace_s": grace_s,
        "source_record": source_payload,
    }


def build_sensory_freshness_v1(
    *,
    spectral: dict[str, Any] | None,
    health: dict[str, Any] | None = None,
    camera: dict[str, Any] | None,
    mic: dict[str, Any] | None,
    sensory: dict[str, Any] | None,
    observed_at_ms: float | None = None,
) -> dict[str, Any]:
    now = time.time() * 1000 if observed_at_ms is None else observed_at_ms
    if nonnegative_number(now) is None:
        raise ValueError("observation time must be finite and nonnegative")
    clocks = {
        name: record_clock(_as_mapping(record), name, now, limit)
        for name, record, limit in (
            ("spectral", spectral, ENGINE_STATUS_STALE_MS),
            ("health", health, ENGINE_STATUS_STALE_MS),
            ("camera", camera, CAMERA_STATUS_STALE_SECONDS * 1000),
            ("mic", mic, MIC_STATUS_STALE_SECONDS * 1000),
            ("sensory", sensory, SENSORY_SOURCE_STALE_SECONDS * 1000),
        )
    }
    intake_evidence = "current"
    if clocks["spectral"]["state"] != "current" or (health and clocks["health"]["state"] != "current"):
        intake_evidence = "unverified_snapshot_clock"
    if health:
        spectral_session = _as_mapping(_as_mapping(spectral).get("provenance")).get("session_id")
        health_session = _as_mapping(health.get("provenance")).get("session_id")
        if spectral_session is None or spectral_session != health_session:
            intake_evidence = "unverified_session_alignment"
    modalities = _as_mapping(_as_mapping(spectral).get("modalities"))
    source_record = _as_mapping(sensory)
    lanes = {
        "video": _classify_lane_freshness(
            lane="video",
            spectral=spectral,
            health=health,
            modalities=modalities,
            client=_as_mapping(camera),
            source_record=source_record,
            clocks=clocks,
            intake_evidence=intake_evidence,
        ),
        "audio": _classify_lane_freshness(
            lane="audio",
            spectral=spectral,
            health=health,
            modalities=modalities,
            client=_as_mapping(mic),
            source_record=source_record,
            clocks=clocks,
            intake_evidence=intake_evidence,
        ),
    }
    actionable = [
        row
        for row in lanes.values()
        if row["status"] not in {"engine_fresh_or_held", "engine_synthetic_recent", "expected_host_fallback", "live_intake_suppressed"}
    ]
    return {
        "schema_version": 1,
        "policy": "sensory_freshness_evidence_v2",
        "status": "watch" if actionable else "classified",
        "observed_at_ms": now,
        "snapshot_clocks": clocks,
        "scope": "non_atomic_status_snapshots_not_consumer_application_receipts",
        "engine_fresh_window_ms": ENGINE_AV_FRESH_WINDOW_MS,
        "actionable_count": len(actionable),
        "lanes": lanes,
    }


def collect() -> dict[str, Any]:
    """Read five independent snapshots; never treat file mtime as sample time."""
    sensory, sensory_err = _safe_load_json(SENSORY_SOURCE_PATH)
    camera, camera_err = _safe_load_json(CAMERA_STATUS_PATH)
    mic, mic_err = _safe_load_json(MIC_STATUS_PATH)
    spectral, spectral_err = _safe_load_json(SPECTRAL_STATE_PATH)
    health, health_err = _safe_load_json(HEALTH_PATH)
    now = time.time()

    sensory_file_age = _file_age_seconds(SENSORY_SOURCE_PATH)
    camera_file_age = _file_age_seconds(CAMERA_STATUS_PATH)
    mic_file_age = _file_age_seconds(MIC_STATUS_PATH)

    # Sensory source's internal updated_at_ms — should be very recent
    # (host-sensory writes on every refresh tick, ~50ms cadence).
    sensory_internal_age = None
    sensory_timestamp_s = _ms_to_seconds(_as_mapping(sensory).get("updated_at_ms"))
    if sensory_timestamp_s is not None:
        sensory_internal_age = now - sensory_timestamp_s

    # Last-frame / last-chunk ages from the client's own clocks.
    camera_frame_age = None
    freshness = build_sensory_freshness_v1(
        spectral=spectral, health=health, camera=camera, mic=mic, sensory=sensory,
        observed_at_ms=now * 1000,
    )
    camera_frame_age = _ms_to_seconds(freshness["lanes"]["video"]["client_age_ms"])
    mic_chunk_age = None
    mic_chunk_age = _ms_to_seconds(freshness["lanes"]["audio"]["client_age_ms"])

    return {
        "now": now,
        "sensory": sensory,
        "sensory_err": sensory_err,
        "sensory_file_age": sensory_file_age,
        "sensory_internal_age": sensory_internal_age,
        "camera": camera,
        "camera_err": camera_err,
        "camera_file_age": camera_file_age,
        "camera_frame_age": camera_frame_age,
        "mic": mic,
        "mic_err": mic_err,
        "mic_file_age": mic_file_age,
        "mic_chunk_age": mic_chunk_age,
        "spectral": spectral,
        "spectral_err": spectral_err,
        "health": health,
        "health_err": health_err,
        "sensory_freshness_v1": freshness,
    }


def render_markdown(report: dict[str, Any]) -> str:
    out: list[str] = []
    ts = datetime.fromtimestamp(report["now"]).strftime("%Y-%m-%d %H:%M:%S")
    out.append(f"=== Sensory source check ({ts}) ===\n")

    # Host-sensory source selection is not a consumer application receipt.
    sensory = report["sensory"]
    if sensory is None:
        out.append(f"sensory_source.json: ERROR — {report['sensory_err']}\n")
    else:
        mode = sensory.get("mode", "?")
        audio = sensory.get("audio") or {}
        video = sensory.get("video") or {}

        def _src_label(s: dict[str, Any]) -> str:
            src = (s.get("source") or "?").lower()
            healthy = s.get("physical_healthy")
            reason = s.get("reason") or ""
            if src == "physical":
                tag = "Physical (real device)"
            elif src == "host":
                tag = "Host (synthetic)"
            else:
                tag = src
            healthy_str = "healthy" if healthy is True else "UNHEALTHY" if healthy is False else "unknown"
            return f"{tag} [physical {healthy_str}; reason: {reason}]"

        out.append(f"AUDIO source: {_src_label(audio)}")
        out.append(f"VIDEO source: {_src_label(video)}")
        out.append(
            f"  (host-sensory mode={mode}, source-record age "
            f"{_fmt_age(report['sensory_internal_age'])} internal / "
            f"{_fmt_age(report['sensory_file_age'], SENSORY_SOURCE_STALE_SECONDS)} file)"
        )
        out.append("")

    # Camera client status
    out.append("CAMERA client (camera_client.py → ws://127.0.0.1:7880):")
    if report["camera"] is None:
        out.append(f"  ERROR — {report['camera_err']}")
    else:
        c = report["camera"]
        flags = (
            "healthy" if c.get("healthy") is True else "UNHEALTHY" if c.get("healthy") is False else "health unknown",
            "connected" if c.get("connected") is True else "DISCONNECTED" if c.get("connected") is False else "connection unknown",
        )
        out.append(
            f"  state={c.get('state', '?')}, {' / '.join(flags)}, "
            f"frames={c.get('frame_count', '?')}, "
            f"failures={c.get('consecutive_failures', '?')}"
        )
        out.append(
            f"  last frame age: {_fmt_age(report['camera_frame_age'], CAMERA_STATUS_STALE_SECONDS)} "
            f"(file age {_fmt_age(report['camera_file_age'], CAMERA_STATUS_STALE_SECONDS)})"
        )
        if c.get("last_error"):
            out.append(f"  last_error: {c['last_error']}")
        if c.get("physical_device_present") is False and c.get("fallback_expected") is True:
            out.append("  physical device: absent; host fallback expected")
    out.append("")

    # Mic client status
    out.append("MIC client (mic_to_sensory.py → ws://127.0.0.1:7879):")
    if report["mic"] is None:
        out.append(f"  ERROR — {report['mic_err']}")
    else:
        m = report["mic"]
        flags = (
            "healthy" if m.get("healthy") is True else "UNHEALTHY" if m.get("healthy") is False else "health unknown",
            "connected" if m.get("connected") is True else "DISCONNECTED" if m.get("connected") is False else "connection unknown",
        )
        rms = m.get("rms")
        rms_str = f"{rms:.4f}" if isinstance(rms, (int, float)) else "?"
        out.append(
            f"  state={m.get('state', '?')}, {' / '.join(flags)}, "
            f"rms={rms_str}, silence_streak={m.get('silence_streak', '?')}, "
            f"chunks={m.get('chunk_count', '?')}"
        )
        out.append(
            f"  last chunk age: {_fmt_age(report['mic_chunk_age'], MIC_STATUS_STALE_SECONDS)} "
            f"(file age {_fmt_age(report['mic_file_age'], MIC_STATUS_STALE_SECONDS)})"
        )
        if m.get("last_error"):
            out.append(f"  last_error: {m['last_error']}")
        if m.get("physical_device_present") is False and m.get("fallback_expected") is True:
            out.append("  physical device: absent; host fallback expected")
    out.append("")

    freshness = report.get("sensory_freshness_v1")
    if isinstance(freshness, dict):
        out.append("ENGINE lane evidence (independent status snapshots, not application receipts):")
        lanes = freshness.get("lanes") if isinstance(freshness.get("lanes"), dict) else {}
        for lane in ("video", "audio"):
            row = lanes.get(lane) if isinstance(lanes.get(lane), dict) else {}
            out.append(
                f"  {lane}: status={row.get('status', '?')}, "
                f"engine={row.get('engine_source', '?')}/{row.get('engine_freshness_class', '?')}, "
                f"age={row.get('engine_age_ms', '?')}ms"
            )
            out.append(
                f"    intake={row.get('live_intake_state', '?')}; "
                f"clock={row.get('engine_clock', {}).get('state', '?')}; "
                f"{row.get('reason', '')}"
            )
        out.append("")

    return "\n".join(out)


def watch_mode(interval: float) -> int:
    """Re-run collect+render every `interval` seconds. Ctrl-C to exit."""
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")  # clear screen
            sys.stdout.write(render_markdown(collect()))
            sys.stdout.write(f"\n(refreshing every {interval}s — Ctrl-C to exit)\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


# ----------------------------------------------------------------------
# Self-tests
# ----------------------------------------------------------------------


class SensoryCheckTests(unittest.TestCase):
    def fixture_report(self, **records: Any) -> dict[str, Any]:
        # Old classification fixtures are explicitly contemporaneous, not live data.
        for kind, record in records.items():
            if record and kind in {"spectral", "health"}:
                record["provenance"] = {"wall_clock_unix_ms": 100_000, "session_id": 1}
            elif record:
                record["updated_at_ms" if kind == "sensory" else "ts_ms"] = 100_000
        return build_sensory_freshness_v1(**records, observed_at_ms=100_000)

    def test_engine_av_fresh_window_matches_rust_const(self) -> None:
        """ENGINE_AV_FRESH_WINDOW_MS must equal the Rust engine's
        AV_ENGINE_FRESH_WINDOW_MS (runtime/semantic_modality.rs): both classify the SAME
        freshness window, so silent drift would misclassify lanes on one side."""
        main_rs = Path(__file__).resolve().parent.parent / "minime" / "src" / "runtime" / "semantic_modality.rs"
        m = re.search(
            r"const AV_ENGINE_FRESH_WINDOW_MS:\s*u64\s*=\s*([0-9_]+)",
            main_rs.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(m, "AV_ENGINE_FRESH_WINDOW_MS not found in runtime/semantic_modality.rs")
        rust_val = int(m.group(1).replace("_", ""))
        self.assertEqual(
            rust_val,
            ENGINE_AV_FRESH_WINDOW_MS,
            f"Rust AV_ENGINE_FRESH_WINDOW_MS ({rust_val}) != Python "
            f"ENGINE_AV_FRESH_WINDOW_MS ({ENGINE_AV_FRESH_WINDOW_MS}) — keep them in sync",
        )

    def test_fmt_age_short(self) -> None:
        self.assertEqual(_fmt_age(0.5), "500ms")
        self.assertEqual(_fmt_age(2.5), "2.5s")
        self.assertEqual(_fmt_age(120), "2.0m")

    def test_fmt_age_stale_marker(self) -> None:
        self.assertIn("STALE", _fmt_age(15, stale_threshold=10))
        self.assertNotIn("STALE", _fmt_age(5, stale_threshold=10))

    def test_fmt_age_none(self) -> None:
        self.assertEqual(_fmt_age(None), "?")

    def test_ms_to_seconds(self) -> None:
        self.assertEqual(_ms_to_seconds(1000), 1.0)
        self.assertIsNone(_ms_to_seconds(None))
        self.assertIsNone(_ms_to_seconds("invalid"))

    def test_sensory_freshness_flags_low_fps_camera_cadence(self) -> None:
        report = self.fixture_report(
            spectral={
                "modalities": {
                    "video_source": "stale",
                    "video_age_ms": 5000,
                    "video_freshness_class": "stale_beyond_engine_window",
                    "audio_source": "external",
                    "audio_freshness_class": "fresh_sample",
                }
            },
            camera={
                "healthy": True,
                "connected": True,
                "state": "streaming",
                "last_frame_age_ms": 0,
                "fps": 0.2,
            },
            mic={"healthy": True, "connected": True, "last_chunk_age_ms": 0},
            sensory={
                "video": {"source": "physical", "physical_healthy": True, "reason": "camera healthy"},
                "audio": {"source": "physical", "physical_healthy": True, "reason": "mic healthy"},
            },
        )
        self.assertEqual(report["status"], "watch")
        self.assertEqual(
            report["lanes"]["video"]["status"],
            "healthy_low_fps_cadence_mismatch",
        )

    def test_sensory_freshness_holds_inside_live_intake_cadence(self) -> None:
        report = self.fixture_report(
            spectral={
                "modalities": {
                    "audio_source": "stale",
                    "audio_age_ms": 5400,
                    "audio_freshness_class": "stale_beyond_engine_window",
                },
                "stable_core": {
                    "sensory_budget": {
                        "live_audio_enabled": True,
                        "live_audio_divisor": 12,
                        "live_intake_reason": "full_presence_admitted",
                    }
                },
            },
            camera={"healthy": True, "connected": True, "last_frame_age_ms": 0, "fps": 5.0},
            mic={
                "healthy": True,
                "connected": True,
                "state": "streaming",
                "last_chunk_age_ms": 0,
                "chunk_health_grace_secs": 5.0,
            },
            sensory={"audio": {"source": "physical", "physical_healthy": True, "reason": "mic healthy"}},
        )
        self.assertEqual(report["status"], "watch")
        row = report["lanes"]["audio"]
        self.assertEqual(row["status"], "healthy_client_engine_stale_mismatch")
        self.assertEqual(row["live_intake_divisor"], 12)
        self.assertIsNone(row["expected_engine_interval_ms"])

    def test_sensory_freshness_accounts_for_admit_fraction(self) -> None:
        report = self.fixture_report(
            spectral={
                "modalities": {
                    "audio_source": "stale",
                    "audio_age_ms": 40000,
                    "audio_freshness_class": "stale_beyond_engine_window",
                },
                "stable_core": {
                    "sensory_budget": {
                        "live_audio_enabled": True,
                        "live_audio_divisor": 12,
                        "live_intake_reason": "full_presence_admitted",
                    }
                },
            },
            health={"sensory": {"admit_fraction": 0.12, "live_audio_divisor": 12}},
            camera={"healthy": True, "connected": True, "last_frame_age_ms": 0, "fps": 5.0},
            mic={
                "healthy": True,
                "connected": True,
                "state": "streaming",
                "last_chunk_age_ms": 0,
                "chunk_interval_ms": 500,
                "chunk_health_grace_secs": 5.0,
            },
            sensory={"audio": {"source": "physical", "physical_healthy": True, "reason": "mic healthy"}},
        )
        row = report["lanes"]["audio"]
        self.assertEqual(report["status"], "watch")
        self.assertEqual(row["status"], "engine_stale_within_conditional_cadence")
        self.assertEqual(row["admit_fraction"], 0.12)
        self.assertEqual(row["expected_engine_interval_ms"], 50000.0)

    def test_sensory_freshness_flags_healthy_client_engine_overdue(self) -> None:
        report = self.fixture_report(
            spectral={
                "modalities": {
                    "audio_source": "stale",
                    "audio_age_ms": 30000,
                    "audio_freshness_class": "stale_beyond_engine_window",
                },
                "stable_core": {
                    "sensory_budget": {
                        "live_audio_enabled": True,
                        "live_audio_divisor": 12,
                        "admit_fraction": 1.0,
                        "live_intake_reason": "full_presence_admitted",
                    }
                },
            },
            camera={"healthy": True, "connected": True, "last_frame_age_ms": 0, "fps": 5.0},
            mic={
                "healthy": True,
                "connected": True,
                "state": "streaming",
                "last_chunk_age_ms": 0,
                "chunk_interval_ms": 500,
                "chunk_health_grace_secs": 5.0,
            },
            sensory={"audio": {"source": "physical", "physical_healthy": True, "reason": "mic healthy"}},
        )
        self.assertEqual(
            report["lanes"]["audio"]["status"],
            "healthy_client_engine_overdue",
        )

    def test_sensory_freshness_keeps_expected_host_fallback_separate(self) -> None:
        report = self.fixture_report(
            spectral={"modalities": {"video_source": "absent", "video_age_ms": 5000}},
            camera={
                "healthy": False,
                "connected": False,
                "fallback_expected": True,
                "last_error": "no_video_input_device",
            },
            mic={},
            sensory={"video": {"source": "host", "physical_healthy": False, "reason": "camera absent"}},
        )
        self.assertEqual(report["lanes"]["video"]["status"], "expected_host_fallback")

    def test_collect_handles_missing_files(self) -> None:
        # If the runtime files are missing, collect should not crash.
        # Patch paths to nonexistent locations for this test.
        global SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH, SPECTRAL_STATE_PATH, HEALTH_PATH
        original = (SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH, SPECTRAL_STATE_PATH, HEALTH_PATH)
        try:
            SENSORY_SOURCE_PATH = Path("/tmp/__nonexistent_sensory.json")
            CAMERA_STATUS_PATH = Path("/tmp/__nonexistent_camera.json")
            MIC_STATUS_PATH = Path("/tmp/__nonexistent_mic.json")
            SPECTRAL_STATE_PATH = Path("/tmp/__nonexistent_spectral_state.json")
            HEALTH_PATH = Path("/tmp/__nonexistent_health.json")
            r = collect()
            self.assertIsNone(r["sensory"])
            self.assertIsNone(r["camera"])
            self.assertIsNone(r["mic"])
            # render shouldn't crash either
            md = render_markdown(r)
            self.assertIn("ERROR", md)
        finally:
            SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH, SPECTRAL_STATE_PATH, HEALTH_PATH = original

    def test_render_with_real_state(self) -> None:
        # Synthetic state — exercises all branches
        r = {
            "now": time.time(),
            "sensory": {
                "mode": "auto",
                "updated_at_ms": int(time.time() * 1000),
                "audio": {"source": "host", "physical_healthy": False, "reason": "mic_silent_streak=30"},
                "video": {"source": "physical", "physical_healthy": True, "reason": "camera healthy"},
            },
            "sensory_err": None,
            "sensory_file_age": 0.5,
            "sensory_internal_age": 0.1,
            "camera": {
                "state": "streaming", "healthy": True, "connected": True,
                "frame_count": 100, "consecutive_failures": 0,
                "last_frame_age_ms": 200, "last_error": None,
            },
            "camera_err": None,
            "camera_file_age": 0.3,
            "camera_frame_age": 0.2,
            "mic": {
                "state": "streaming", "healthy": False, "connected": True,
                "rms": 0.0001, "silence_streak": 50, "chunk_count": 200,
                "consecutive_failures": 0, "last_chunk_age_ms": 100,
                "last_error": None,
            },
            "mic_err": None,
            "mic_file_age": 0.1,
            "mic_chunk_age": 0.1,
        }
        md = render_markdown(r)
        self.assertIn("AUDIO source: Host (synthetic)", md)
        self.assertIn("VIDEO source: Physical (real device)", md)
        self.assertIn("rms=0.0001", md)


def run_self_tests() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(SensoryCheckTests)
    runner = unittest.TextTestRunner(verbosity=2)
    return 0 if runner.run(suite).wasSuccessful() else 1


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Report current camera/mic source (real vs synthetic) for minime.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    p.add_argument(
        "--watch",
        type=float,
        metavar="SECS",
        help="Re-run every SECS seconds (live monitor; Ctrl-C to exit)",
    )
    p.add_argument("--self-test", action="store_true", help="Run unit tests and exit")
    args = p.parse_args()

    if args.self_test:
        return run_self_tests()

    if args.watch:
        if args.json:
            print("--json incompatible with --watch", file=sys.stderr)
            return 2
        return watch_mode(args.watch)

    report = collect()
    if args.json:
        # Strip non-serializable bits
        out = json.dumps(report, indent=2, default=str)
    else:
        out = render_markdown(report)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
