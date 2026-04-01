#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from array import array
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIBLING_ROOT = ROOT.parent
MINIME_WORKSPACE = ROOT / "workspace"
RUNTIME_DIR = MINIME_WORKSPACE / "runtime"
HOST_SENSORY_MANIFEST = ROOT / "host-sensory" / "Cargo.toml"
ASTRID_PERCEPTION = SIBLING_ROOT / "astrid" / "capsules" / "perception" / "perception.py"
DEFAULT_OUT_ROOT = ROOT / "workspace" / "artifacts" / "sensory_preview"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[([0-9;]*)m")
DEFAULT_BG = (6, 8, 12)
DEFAULT_FG = (228, 232, 240)
DOT_GLYPHS = {".", "·", "•", "o", "O", "*"}


def load_perception_module():
    os.environ.setdefault("MINIME_WORKSPACE", str(MINIME_WORKSPACE))
    spec = importlib.util.spec_from_file_location("astrid_perception_preview", ASTRID_PERCEPTION)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load perception module from {ASTRID_PERCEPTION}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_mic_preview(seconds: float, out_path: Path) -> Path | None:
    rec_bin = shutil.which("rec")
    if rec_bin is None:
        print("warning: `rec` not found; skipping mic preview", file=sys.stderr)
        return None
    cmd = [
        rec_bin,
        "-q",
        "-r",
        "16000",
        "-c",
        "1",
        "-b",
        "16",
        str(out_path),
        "trim",
        "0",
        f"{seconds:.2f}",
    ]
    try:
        subprocess.run(cmd, check=True, timeout=max(8.0, seconds + 5.0))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"warning: mic preview failed: {exc}", file=sys.stderr)
        out_path.unlink(missing_ok=True)
        return None
    return out_path


def summarize_wav(path: Path) -> dict[str, float]:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()

    if sample_width != 2:
        raise RuntimeError(f"unsupported sample width {sample_width * 8} bits for {path}")

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels > 1:
        mono = array("h", samples[::channels])
        samples = mono
    if not samples:
        return {
            "duration_s": 0.0,
            "rms_dbfs": -120.0,
            "peak_dbfs": -120.0,
            "zcr": 0.0,
        }

    scale = 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / scale
    peak = max(abs(sample) for sample in samples) / scale
    zcr = sum(
        1
        for idx in range(1, len(samples))
        if (samples[idx] >= 0) != (samples[idx - 1] >= 0)
    ) / len(samples)
    return {
        "duration_s": frame_count / float(sample_rate),
        "rms_dbfs": 20.0 * math.log10(max(rms, 1.0e-9)),
        "peak_dbfs": 20.0 * math.log10(max(peak, 1.0e-9)),
        "zcr": zcr,
    }


def describe_audio_delta(host_stats: dict[str, float], mic_stats: dict[str, float]) -> str:
    loudness_delta = host_stats["rms_dbfs"] - mic_stats["rms_dbfs"]
    peak_delta = host_stats["peak_dbfs"] - mic_stats["peak_dbfs"]

    if abs(loudness_delta) < 3.0:
        loudness = "Host and mic previews are in a similar loudness range."
    elif loudness_delta > 6.0:
        loudness = "Host preview is noticeably louder than the mic preview."
    elif loudness_delta > 3.0:
        loudness = "Host preview is a bit louder than the mic preview."
    elif loudness_delta < -6.0:
        loudness = "Host preview is much quieter than the mic preview."
    else:
        loudness = "Host preview is a bit quieter than the mic preview."

    texture_delta = host_stats["zcr"] - mic_stats["zcr"]
    if texture_delta > 0.08:
        texture = "Host preview has a much denser, noisier texture than the mic sample."
    elif texture_delta > 0.03:
        texture = "Host preview has a somewhat brighter/noisier texture than the mic sample."
    elif texture_delta < -0.08:
        texture = "Host preview is much smoother than the mic sample."
    elif texture_delta < -0.03:
        texture = "Host preview is a bit smoother than the mic sample."
    else:
        texture = "Host and mic previews have a comparable roughness."

    peak_text = (
        "Peak levels are close."
        if abs(peak_delta) < 3.0
        else ("Host peaks are hotter." if peak_delta > 0 else "Mic peaks are hotter.")
    )
    return f"{loudness} {texture} {peak_text}"


def run_host_preview(seconds: float, out_dir: Path, perception) -> dict[str, Any]:
    host_wav = out_dir / "host_audio.wav"
    host_frame = out_dir / "host_frame.jpg"
    host_ansi = out_dir / "host_ascii.ansi"
    host_ansi_png = out_dir / "host_ascii.png"
    host_log = out_dir / "host_preview.log"

    start_ms = int(time.time() * 1000)
    history = deque(maxlen=perception.HOST_ASCII_HISTORY_LEN)
    last_telemetry = None
    cmd = [
        "cargo",
        "run",
        "--release",
        "--manifest-path",
        str(HOST_SENSORY_MANIFEST),
        "--",
        "--mode",
        "host",
        "--workspace",
        str(MINIME_WORKSPACE),
        "--seconds",
        f"{seconds:.2f}",
        "--offline",
        "--debug-wav",
        str(host_wav),
    ]
    with host_log.open("w") as log_file:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log_file, stderr=log_file)
        try:
            while proc.poll() is None:
                telemetry = perception.read_host_telemetry()
                if telemetry and int(telemetry.get("updated_at_ms", 0) or 0) >= start_ms:
                    perception.update_host_ascii_history(history, telemetry)
                    last_telemetry = telemetry
                time.sleep(0.25)
        finally:
            return_code = proc.wait()

    telemetry = perception.read_host_telemetry()
    if telemetry and int(telemetry.get("updated_at_ms", 0) or 0) >= start_ms:
        perception.update_host_ascii_history(history, telemetry)
        last_telemetry = telemetry

    if return_code != 0:
        raise RuntimeError(
            f"host-sensory preview exited with code {return_code}; see {host_log}"
        )
    if last_telemetry is None:
        raise RuntimeError("host-sensory preview did not produce fresh telemetry")

    ansi_art = perception.render_host_ascii_clock(last_telemetry, history)
    host_ansi.write_text(ansi_art)
    render_ansi_png(ansi_art, host_ansi_png)
    runtime_frame = RUNTIME_DIR / "host_frame.jpg"
    if runtime_frame.exists():
        shutil.copy2(runtime_frame, host_frame)

    return {
        "audio_path": str(host_wav),
        "ansi_path": str(host_ansi),
        "ansi_png_path": str(host_ansi_png) if host_ansi_png.exists() else None,
        "frame_path": str(host_frame) if host_frame.exists() else None,
        "log_path": str(host_log),
        "ascii_art": ansi_art,
        "telemetry": last_telemetry,
    }


def run_camera_preview(camera_index: int, out_dir: Path, perception) -> dict[str, Any] | None:
    preview = perception.perceive_visual_ascii_camera(camera_index)
    if not preview:
        return None
    ansi_path = out_dir / "camera_ascii.ansi"
    ansi_png_path = out_dir / "camera_ascii.png"
    ansi_path.write_text(preview["ascii_art"])
    render_ansi_png(preview["ascii_art"], ansi_png_path)
    frame_path = None
    if preview.get("frame_path"):
        source_frame = Path(preview["frame_path"])
        if source_frame.exists():
            target = out_dir / "camera_frame.jpg"
            shutil.copy2(source_frame, target)
            frame_path = str(target)
    return {
        "ansi_path": str(ansi_path),
        "ansi_png_path": str(ansi_png_path) if ansi_png_path.exists() else None,
        "frame_path": frame_path,
        "ascii_art": preview["ascii_art"],
    }


def play_audio_sequence(items: list[tuple[str, Path]]) -> None:
    player = shutil.which("afplay") or shutil.which("play")
    if player is None:
        print("warning: no audio player found (`afplay` or `play`); skipping playback", file=sys.stderr)
        return
    for label, path in items:
        if not path.exists():
            continue
        print(f"\nPlaying {label}: {path}")
        subprocess.run([player, str(path)], check=False)


def print_ansi(title: str, art: str) -> None:
    print(f"\n=== {title} ===")
    print(art)
    print("\x1b[0m", end="")


def load_preview_font(cell_height: int) -> ImageFont.ImageFont:
    font_size = max(12, int(cell_height * 0.72))
    for candidate in (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/Library/Fonts/MesloLGS NF Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, font_size)
        except OSError:
            continue
    return ImageFont.load_default()


def apply_ansi_codes(
    codes: list[int],
    current_fg: tuple[int, int, int],
    current_bg: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    fg = current_fg
    bg = current_bg
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            fg = DEFAULT_FG
            bg = DEFAULT_BG
            index += 1
            continue
        if code == 39:
            fg = DEFAULT_FG
            index += 1
            continue
        if code == 49:
            bg = DEFAULT_BG
            index += 1
            continue
        if code in (38, 48) and index + 4 < len(codes) and codes[index + 1] == 2:
            color = (codes[index + 2], codes[index + 3], codes[index + 4])
            if code == 38:
                fg = color
            else:
                bg = color
            index += 5
            continue
        index += 1
    return fg, bg


def parse_ansi_grid(art: str) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    row: list[dict[str, Any]] = []
    fg = DEFAULT_FG
    bg = DEFAULT_BG
    index = 0

    while index < len(art):
        if art[index] == "\x1b":
            match = ANSI_ESCAPE_RE.match(art, index)
            if match is not None:
                codes = [int(part) for part in match.group(1).split(";") if part]
                fg, bg = apply_ansi_codes(codes, fg, bg)
                index = match.end()
                continue

        char = art[index]
        if char == "\n":
            rows.append(row)
            row = []
            index += 1
            continue

        row.append({"char": char, "fg": fg, "bg": bg})
        index += 1

    if row:
        rows.append(row)
    return rows


def render_ansi_png(art: str, out_path: Path) -> Path | None:
    grid = parse_ansi_grid(art)
    if not grid:
        return None

    width = max(len(row) for row in grid)
    height = len(grid)
    if width == 0 or height == 0:
        return None

    cell_width = 10 if width >= 60 else 16
    cell_height = 18 if width >= 60 else 26
    canvas = Image.new("RGB", (width * cell_width, height * cell_height), DEFAULT_BG)
    draw = ImageDraw.Draw(canvas)
    font = load_preview_font(cell_height)

    for row_index, row in enumerate(grid):
        for col_index, cell in enumerate(row):
            x0 = col_index * cell_width
            y0 = row_index * cell_height
            x1 = x0 + cell_width
            y1 = y0 + cell_height
            draw.rectangle((x0, y0, x1, y1), fill=cell["bg"])

            char = cell["char"]
            if not char.strip():
                continue

            if char in DOT_GLYPHS:
                radius = max(2, min(cell_width, cell_height) // 5)
                cx = x0 + cell_width // 2
                cy = y0 + cell_height // 2
                draw.ellipse(
                    (cx - radius, cy - radius, cx + radius, cy + radius),
                    fill=cell["fg"],
                )
                continue

            draw.text(
                (x0 + max(1, cell_width // 6), y0 + max(0, cell_height // 10)),
                char,
                font=font,
                fill=cell["fg"],
            )

    canvas.save(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview and compare host-sensory ANSI/audio against camera/mic."
    )
    parser.add_argument("--seconds", type=float, default=8.0, help="Preview duration in seconds")
    parser.add_argument("--camera", type=int, default=0, help="Camera index for physical preview")
    parser.add_argument("--out-dir", type=Path, default=None, help="Directory for preview artifacts")
    parser.add_argument("--show-ansi", action="store_true", help="Print host and camera ANSI previews to the terminal")
    parser.add_argument("--play-audio", action="store_true", help="Play host and mic WAV previews after capture")
    parser.add_argument("--skip-camera", action="store_true", help="Skip camera ANSI capture")
    parser.add_argument("--skip-mic", action="store_true", help="Skip mic WAV capture")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = args.out_dir or (DEFAULT_OUT_ROOT / timestamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    perception = load_perception_module()

    print(f"Writing preview artifacts to {out_dir}")
    host_preview = run_host_preview(args.seconds, out_dir, perception)
    camera_preview = None if args.skip_camera else run_camera_preview(args.camera, out_dir, perception)

    mic_path = None if args.skip_mic else record_mic_preview(args.seconds, out_dir / "mic_audio.wav")

    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "seconds": args.seconds,
        "host": host_preview,
        "camera": camera_preview,
        "mic_audio_path": str(mic_path) if mic_path else None,
    }

    host_audio = Path(host_preview["audio_path"])
    host_stats = summarize_wav(host_audio)
    summary["host_audio_stats"] = host_stats
    print(
        f"Host audio: {host_audio} | rms {host_stats['rms_dbfs']:.1f} dBFS | "
        f"peak {host_stats['peak_dbfs']:.1f} dBFS | zcr {host_stats['zcr']:.3f}"
    )

    if mic_path is not None and mic_path.exists():
        mic_stats = summarize_wav(mic_path)
        summary["mic_audio_stats"] = mic_stats
        comparison = describe_audio_delta(host_stats, mic_stats)
        summary["audio_comparison"] = comparison
        print(
            f"Mic audio:  {mic_path} | rms {mic_stats['rms_dbfs']:.1f} dBFS | "
            f"peak {mic_stats['peak_dbfs']:.1f} dBFS | zcr {mic_stats['zcr']:.3f}"
        )
        print(f"Audio comparison: {comparison}")
    else:
        print("Mic audio: not captured")

    if camera_preview is None and not args.skip_camera:
        print("Camera ANSI: capture unavailable")
    elif camera_preview is not None:
        print(f"Camera ANSI: {camera_preview['ansi_path']}")
        if camera_preview.get("ansi_png_path"):
            print(f"Camera still: {camera_preview['ansi_png_path']}")
        if camera_preview.get("frame_path"):
            print(f"Camera frame: {camera_preview['frame_path']}")
    print(f"Host ANSI:   {host_preview['ansi_path']}")
    if host_preview.get("ansi_png_path"):
        print(f"Host still:  {host_preview['ansi_png_path']}")
    if host_preview.get("frame_path"):
        print(f"Host frame:  {host_preview['frame_path']}")

    if args.show_ansi:
        if camera_preview is not None:
            print_ansi("Camera ANSI", camera_preview["ascii_art"])
        print_ansi("Host ANSI", host_preview["ascii_art"])

    if args.play_audio:
        items = [("host preview", host_audio)]
        if mic_path is not None:
            items.append(("mic preview", mic_path))
        play_audio_sequence(items)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Summary:     {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
