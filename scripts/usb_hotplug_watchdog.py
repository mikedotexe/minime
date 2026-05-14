#!/usr/bin/env python3
"""USB camera/mic hot-plug watchdog for minime (2026-05-14).

When the user unplugs the USB camera/mic duo, host-sensory's `refresh_auto`
detects the staleness within 2-5 seconds and switches minime over to
synthetic audio/video. That part works (see sensory_source_check.py).

What did NOT work before this watchdog: when the user plugs the camera/mic
back in, neither camera_client.py nor mic_to_sensory.py actively
re-enumerates USB devices. They have retry loops, but those retries reuse
the original device handle — if the device returned as a new node, the
client can stay stuck reaching for the old one.

This watchdog polls macOS for camera+audio-input changes via
`system_profiler SPCameraDataType -json` and `system_profiler SPAudioDataType
-json`. When the set of devices changes (either device disappears or
reappears), we `launchctl kickstart -k` the camera-client and
mic-to-sensory labels. A clean restart performs fresh device enumeration,
which is exactly what we need for replug recovery.

We deliberately use the targeted SPCameraDataType / SPAudioDataType
queries instead of the broader SPUSBDataType — on recent macOS releases
the latter requires entitlements that headless launchd processes don't
have, and SPCamera + SPAudio are both unprivileged and far more relevant.

Usage:
    python3 scripts/usb_hotplug_watchdog.py              # run in foreground (launchd uses this)
    python3 scripts/usb_hotplug_watchdog.py --once       # one-shot snapshot, print + exit
    python3 scripts/usb_hotplug_watchdog.py --self-test  # unit tests
    python3 scripts/usb_hotplug_watchdog.py --dry-run    # log device changes without kickstart
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_PATH = Path("/Users/v/other/minime/logs/usb_hotplug_watchdog.log")

# Absolute paths for tools we shell out to. launchd does not inherit the
# user's interactive PATH, so /usr/sbin/system_profiler isn't found by
# default; we use absolute paths to remove the PATH dependency.
SYSTEM_PROFILER = "/usr/sbin/system_profiler"
LAUNCHCTL = "/bin/launchctl"

# Default poll cadence + debounce after a kickstart event
POLL_INTERVAL_S = 3.0
POST_KICKSTART_DEBOUNCE_S = 5.0

# Launchd labels to restart on device change. Both clients re-enumerate
# the device list on startup, so kickstart triggers the recovery we want.
KICKSTART_LABELS = [
    "com.minime.camera-client",
    "com.minime.mic-to-sensory",
]

# system_profiler latency is fast (~100-200ms each); per-call timeout 8s
SP_TIMEOUT_S = 8


def _log(msg: str) -> None:
    """Print a timestamped line to stdout.

    Under launchd, stdout is captured to the file at LOG_PATH (configured
    via StandardOutPath in the plist). When run interactively, the line
    goes to the terminal; redirect manually if a file copy is wanted.
    Writing to BOTH stdout and the file caused duplicate-line bug, since
    launchd's stdout capture is itself a write to the same file.
    """
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts}  {msg}", flush=True)


def _sp_query(data_type: str) -> dict[str, Any]:
    """Run `system_profiler <data_type> -json` and return parsed JSON.

    Returns empty dict on any failure — caller handles gracefully so a
    flaky system_profiler doesn't kill the watchdog.
    """
    try:
        res = subprocess.run(
            [SYSTEM_PROFILER, data_type, "-json"],
            capture_output=True, text=True, timeout=SP_TIMEOUT_S,
        )
    except Exception as e:
        _log(f"system_profiler {data_type} failed: {e}")
        return {}
    if res.returncode != 0:
        _log(f"system_profiler {data_type} returned rc={res.returncode}: {res.stderr.strip()[:120]}")
        return {}
    try:
        return json.loads(res.stdout)
    except Exception as e:
        _log(f"system_profiler {data_type} JSON parse failed: {e}")
        return {}


def list_camera_devices() -> set[str]:
    """Return a set of identifying strings for currently-attached cameras.

    Identity is `model-id` when present (includes VendorID + ProductID),
    falling back to `_name` for built-in cameras that have no model-id.
    """
    data = _sp_query("SPCameraDataType")
    cameras = data.get("SPCameraDataType", []) or []
    ids: set[str] = set()
    for cam in cameras:
        mid = cam.get("spcamera_model-id") or cam.get("_name", "?")
        ids.add(str(mid))
    return ids


def list_usb_audio_input_devices() -> set[str]:
    """Return a set of identifying strings for currently-attached USB audio inputs.

    Walks SPAudioDataType, keeping only entries where
    `coreaudio_device_transport == "coreaudio_device_type_usb"` AND
    `coreaudio_device_input >= 1` (filters out built-in speakers and
    headphone-only USB devices). Identity is `_name + manufacturer + srate`.
    """
    data = _sp_query("SPAudioDataType")
    audio_root = data.get("SPAudioDataType", []) or []
    ids: set[str] = set()
    for parent in audio_root:
        for item in parent.get("_items", []) or []:
            transport = item.get("coreaudio_device_transport", "")
            inputs = item.get("coreaudio_device_input", 0)
            if transport == "coreaudio_device_type_usb" and inputs and inputs >= 1:
                name = item.get("_name", "?")
                manuf = item.get("coreaudio_device_manufacturer", "?")
                srate = item.get("coreaudio_device_srate", "?")
                ids.add(f"{name}|{manuf}|{srate}")
    return ids


def snapshot() -> dict[str, set[str]]:
    return {
        "cameras": list_camera_devices(),
        "usb_audio_inputs": list_usb_audio_input_devices(),
    }


def diff_snapshots(old: dict[str, set[str]], new: dict[str, set[str]]) -> dict[str, dict[str, set[str]]]:
    """Compute added / removed sets per category."""
    out: dict[str, dict[str, set[str]]] = {}
    for k in ("cameras", "usb_audio_inputs"):
        old_set = old.get(k, set())
        new_set = new.get(k, set())
        added = new_set - old_set
        removed = old_set - new_set
        if added or removed:
            out[k] = {"added": added, "removed": removed}
    return out


def kickstart_labels(labels: list[str], dry_run: bool = False) -> list[tuple[str, int]]:
    """Run `launchctl kickstart -k gui/$UID/<label>` for each label.

    Returns a list of (label, return_code) tuples. dry_run skips invocation
    but still returns synthetic tuples for logging consistency.
    """
    uid = os.geteuid()
    results: list[tuple[str, int]] = []
    for label in labels:
        target = f"gui/{uid}/{label}"
        if dry_run:
            _log(f"DRY-RUN would kickstart {target}")
            results.append((label, 0))
            continue
        try:
            res = subprocess.run(
                [LAUNCHCTL, "kickstart", "-k", target],
                capture_output=True, text=True, timeout=10,
            )
            if res.returncode == 0:
                _log(f"kickstarted {target}")
            else:
                _log(f"kickstart {target} rc={res.returncode}: {(res.stderr or res.stdout).strip()[:120]}")
            results.append((label, res.returncode))
        except Exception as e:
            _log(f"kickstart {target} raised: {e}")
            results.append((label, -1))
    return results


def fmt_diff(diff: dict[str, dict[str, set[str]]]) -> str:
    pieces: list[str] = []
    for category, changes in diff.items():
        for status in ("added", "removed"):
            items = changes.get(status, set())
            for it in sorted(items):
                pieces.append(f"{category}:{status}={it}")
    return " | ".join(pieces) if pieces else "(no diff)"


def watchdog_loop(
    poll_interval: float = POLL_INTERVAL_S,
    post_kickstart_debounce: float = POST_KICKSTART_DEBOUNCE_S,
    dry_run: bool = False,
) -> int:
    """Main loop. Returns only on fatal failure (process otherwise lives until launchd boots it out)."""
    baseline = snapshot()
    _log(
        f"watchdog started (poll={poll_interval}s, debounce={post_kickstart_debounce}s, "
        f"dry_run={dry_run}); baseline cameras={len(baseline['cameras'])} "
        f"usb_audio_inputs={len(baseline['usb_audio_inputs'])}"
    )
    for cam in sorted(baseline["cameras"]):
        _log(f"  baseline camera: {cam}")
    for au in sorted(baseline["usb_audio_inputs"]):
        _log(f"  baseline usb-audio: {au}")
    current = baseline
    while True:
        time.sleep(poll_interval)
        try:
            new = snapshot()
        except Exception as e:
            _log(f"snapshot raised: {e}; continuing loop")
            continue
        diff = diff_snapshots(current, new)
        if not diff:
            continue
        _log(f"DEVICE CHANGE: {fmt_diff(diff)}")
        kickstart_labels(KICKSTART_LABELS, dry_run=dry_run)
        current = new
        _log(f"debounce {post_kickstart_debounce}s after kickstart")
        time.sleep(post_kickstart_debounce)


# ----------------------------------------------------------------------
# Self-tests
# ----------------------------------------------------------------------


class WatchdogTests(unittest.TestCase):
    def test_diff_detects_added(self) -> None:
        old = {"cameras": {"a"}, "usb_audio_inputs": set()}
        new = {"cameras": {"a", "b"}, "usb_audio_inputs": set()}
        diff = diff_snapshots(old, new)
        self.assertIn("cameras", diff)
        self.assertEqual(diff["cameras"]["added"], {"b"})
        self.assertEqual(diff["cameras"]["removed"], set())

    def test_diff_detects_removed(self) -> None:
        old = {"cameras": {"a", "b"}, "usb_audio_inputs": {"c"}}
        new = {"cameras": {"a"}, "usb_audio_inputs": set()}
        diff = diff_snapshots(old, new)
        self.assertEqual(diff["cameras"]["removed"], {"b"})
        self.assertEqual(diff["usb_audio_inputs"]["removed"], {"c"})

    def test_diff_empty_when_no_change(self) -> None:
        old = {"cameras": {"a"}, "usb_audio_inputs": {"c"}}
        new = {"cameras": {"a"}, "usb_audio_inputs": {"c"}}
        self.assertEqual(diff_snapshots(old, new), {})

    def test_fmt_diff_includes_category(self) -> None:
        diff = {
            "cameras": {"added": {"new-cam"}, "removed": set()},
            "usb_audio_inputs": {"added": set(), "removed": {"old-mic"}},
        }
        s = fmt_diff(diff)
        self.assertIn("cameras:added=new-cam", s)
        self.assertIn("usb_audio_inputs:removed=old-mic", s)

    def test_kickstart_labels_dry_run_returns_zeros(self) -> None:
        results = kickstart_labels(["fake.label.never.exists"], dry_run=True)
        self.assertEqual(results, [("fake.label.never.exists", 0)])

    def test_snapshot_runs_against_real_system(self) -> None:
        # Smoke: snapshot should produce a dict with both keys and not crash.
        # In this CI/test environment, the camera/mic may or may not be
        # present — we just verify the shape and that the categories are sets.
        snap = snapshot()
        self.assertIn("cameras", snap)
        self.assertIn("usb_audio_inputs", snap)
        self.assertIsInstance(snap["cameras"], set)
        self.assertIsInstance(snap["usb_audio_inputs"], set)


def run_self_tests() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(WatchdogTests)
    runner = unittest.TextTestRunner(verbosity=2)
    return 0 if runner.run(suite).wasSuccessful() else 1


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Detect USB camera/mic hot-plug events and kickstart the relevant clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit (no polling, no kickstart)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log diffs but never kickstart launchd labels",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=POLL_INTERVAL_S,
        help=f"Seconds between polls (default {POLL_INTERVAL_S})",
    )
    p.add_argument("--self-test", action="store_true", help="Run unit tests and exit")
    args = p.parse_args()

    if args.self_test:
        return run_self_tests()

    if args.once:
        snap = snapshot()
        print(f"cameras ({len(snap['cameras'])}):")
        for c in sorted(snap["cameras"]):
            print(f"  {c}")
        print(f"usb_audio_inputs ({len(snap['usb_audio_inputs'])}):")
        for a in sorted(snap["usb_audio_inputs"]):
            print(f"  {a}")
        return 0

    try:
        watchdog_loop(
            poll_interval=args.poll_interval,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        _log("watchdog stopped by SIGINT")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
