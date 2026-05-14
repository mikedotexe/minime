#!/usr/bin/env python3
"""Sensory source check — current camera/mic source state for minime.

Reports whether minime is currently receiving REAL camera/mic input or
host-sensory-generated SYNTHETIC input, plus the supporting evidence
(client-side status files, last-frame age, RMS, etc).

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
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path("/Users/v/other/minime/workspace")
RUNTIME = WORKSPACE / "runtime"
SENSORY_SOURCE_PATH = RUNTIME / "sensory_source.json"
CAMERA_STATUS_PATH = RUNTIME / "camera_status.json"
MIC_STATUS_PATH = RUNTIME / "mic_status.json"

# Staleness thresholds (must be larger than host-sensory's internal thresholds
# of 2s audio / 5s video to give a chance for the file write to land).
SENSORY_SOURCE_STALE_SECONDS = 10
CAMERA_STATUS_STALE_SECONDS = 10
MIC_STATUS_STALE_SECONDS = 5


def _safe_load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (data, error_msg). On success error_msg is None."""
    if not path.is_file():
        return None, f"file not found: {path}"
    try:
        return json.loads(path.read_text()), None
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
    if ms is None:
        return None
    try:
        return float(ms) / 1000.0
    except (TypeError, ValueError):
        return None


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


def collect() -> dict[str, Any]:
    """Read all three status files and synthesize a single state report."""
    now = time.time()
    sensory, sensory_err = _safe_load_json(SENSORY_SOURCE_PATH)
    camera, camera_err = _safe_load_json(CAMERA_STATUS_PATH)
    mic, mic_err = _safe_load_json(MIC_STATUS_PATH)

    sensory_file_age = _file_age_seconds(SENSORY_SOURCE_PATH)
    camera_file_age = _file_age_seconds(CAMERA_STATUS_PATH)
    mic_file_age = _file_age_seconds(MIC_STATUS_PATH)

    # Sensory source's internal updated_at_ms — should be very recent
    # (host-sensory writes on every refresh tick, ~50ms cadence).
    sensory_internal_age = None
    if sensory and "updated_at_ms" in sensory:
        sensory_internal_age = now - (sensory["updated_at_ms"] / 1000.0)

    # Last-frame / last-chunk ages from the client's own clocks.
    camera_frame_age = None
    if camera and "last_frame_age_ms" in camera:
        camera_frame_age = _ms_to_seconds(camera["last_frame_age_ms"])
    mic_chunk_age = None
    if mic and "last_chunk_age_ms" in mic:
        mic_chunk_age = _ms_to_seconds(mic["last_chunk_age_ms"])

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
    }


def render_markdown(report: dict[str, Any]) -> str:
    out: list[str] = []
    ts = datetime.fromtimestamp(report["now"]).strftime("%Y-%m-%d %H:%M:%S")
    out.append(f"=== Sensory source check ({ts}) ===\n")

    # Sensory source (the truth file written by host-sensory)
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
            healthy_str = "healthy" if healthy else "UNHEALTHY"
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
            "healthy" if c.get("healthy") else "UNHEALTHY",
            "connected" if c.get("connected") else "DISCONNECTED",
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
    out.append("")

    # Mic client status
    out.append("MIC client (mic_to_sensory.py → ws://127.0.0.1:7879):")
    if report["mic"] is None:
        out.append(f"  ERROR — {report['mic_err']}")
    else:
        m = report["mic"]
        flags = (
            "healthy" if m.get("healthy") else "UNHEALTHY",
            "connected" if m.get("connected") else "DISCONNECTED",
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

    def test_collect_handles_missing_files(self) -> None:
        # If the runtime files are missing, collect should not crash.
        # Patch paths to nonexistent locations for this test.
        global SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH
        original = (SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH)
        try:
            SENSORY_SOURCE_PATH = Path("/tmp/__nonexistent_sensory.json")
            CAMERA_STATUS_PATH = Path("/tmp/__nonexistent_camera.json")
            MIC_STATUS_PATH = Path("/tmp/__nonexistent_mic.json")
            r = collect()
            self.assertIsNone(r["sensory"])
            self.assertIsNone(r["camera"])
            self.assertIsNone(r["mic"])
            # render shouldn't crash either
            md = render_markdown(r)
            self.assertIn("ERROR", md)
        finally:
            SENSORY_SOURCE_PATH, CAMERA_STATUS_PATH, MIC_STATUS_PATH = original

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
