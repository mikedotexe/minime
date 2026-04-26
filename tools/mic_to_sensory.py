#!/usr/bin/env python3
"""
Microphone to Sensory Engine Bridge

Captures audio from the Mac's microphone using sox (rec), extracts 8-D spectral
features, and streams them to the Rust sensory engine via ws://7879 as Audio
messages. Optionally runs periodic speech-to-text via mlx_whisper and sends
transcriptions as Semantic input.

Features extracted (8-D vector):
  [0] RMS energy (log-scaled)
  [1] Spectral centroid (normalized 0-1)
  [2] Spectral bandwidth (normalized 0-1)
  [3] Zero-crossing rate
  [4-7] First 4 MFCC coefficients (DCT of log mel-filterbank)

Usage:
  python3 tools/mic_to_sensory.py              # live mic -> ws://7879
  python3 tools/mic_to_sensory.py --test       # dry run, print features only
  python3 tools/mic_to_sensory.py --whisper    # also run periodic STT
"""

import argparse
import asyncio
import json
import math
import os
import random
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import websockets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000          # 16 kHz mono
CHUNK_DURATION_S = 0.5       # 500 ms per chunk (was 100ms; reduced from 10Hz to 2Hz to lower covariance input rate)
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_S)  # 1600 samples
BYTES_PER_SAMPLE = 2         # 16-bit signed int
CHUNK_BYTES = CHUNK_SAMPLES * BYTES_PER_SAMPLE
FEAT_DIM = 8                 # must match Rust DEFAULT_AUDIO_DIM

WS_URI = "ws://127.0.0.1:7879"

# Whisper settings
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
WHISPER_INTERVAL_S = 10.0    # run STT every N seconds
WHISPER_DURATION_S = 5.0     # record N seconds for STT
WHISPER_TEMP_DIR = "/tmp/minime_whisper"
WORKSPACE_DIR = Path(__file__).resolve().parents[1] / "workspace"
RUNTIME_DIR = WORKSPACE_DIR / "runtime"
MIC_STATUS_PATH = RUNTIME_DIR / "mic_status.json"
PING_INTERVAL_SECS = 10
PING_TIMEOUT_SECS = 20
MAX_RECONNECT_DELAY_SECS = 5.0


def _set_whisper_interval(val: float):
    global WHISPER_INTERVAL_S
    WHISPER_INTERVAL_S = val


def _write_status(status: dict):
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temp = MIC_STATUS_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(status, indent=2))
        temp.replace(MIC_STATUS_PATH)
    except Exception:
        pass


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# Mel filterbank for MFCC
NUM_MEL_FILTERS = 26
NUM_MFCC = 4

# ---------------------------------------------------------------------------
# Audio feature extraction (pure Python + struct, no numpy needed at runtime)
# ---------------------------------------------------------------------------


def _pcm16_to_floats(raw: bytes) -> List[float]:
    """Convert raw PCM16 LE bytes to float samples in [-1, 1]."""
    n = len(raw) // 2
    samples = struct.unpack(f"<{n}h", raw[:n * 2])
    return [s / 32768.0 for s in samples]


def _rms(samples: List[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _rfft_magnitudes(samples: List[float]) -> List[float]:
    """Compute |FFT| for positive frequencies using a basic DFT.

    For 1600 samples this runs in ~50ms on M4 which is fine for 10 FPS.
    We only need the magnitude spectrum, not phase.
    """
    n = len(samples)
    half = n // 2 + 1
    mags = []
    for k in range(half):
        re = 0.0
        im = 0.0
        for t in range(n):
            angle = 2.0 * math.pi * k * t / n
            re += samples[t] * math.cos(angle)
            im -= samples[t] * math.sin(angle)
        mags.append(math.sqrt(re * re + im * im))
    return mags


def _spectral_centroid(mags: List[float], sr: int) -> float:
    """Spectral centroid normalized to [0, 1]."""
    n = len(mags)
    if n == 0:
        return 0.0
    total = sum(mags)
    if total < 1e-12:
        return 0.0
    freqs = [k * sr / ((n - 1) * 2) for k in range(n)]
    centroid = sum(f * m for f, m in zip(freqs, mags)) / total
    nyquist = sr / 2.0
    return min(1.0, centroid / nyquist)


def _spectral_bandwidth(mags: List[float], sr: int, centroid_hz: float) -> float:
    """Spectral bandwidth (spread) normalized to [0, 1]."""
    n = len(mags)
    if n == 0:
        return 0.0
    total = sum(mags)
    if total < 1e-12:
        return 0.0
    freqs = [k * sr / ((n - 1) * 2) for k in range(n)]
    bw = math.sqrt(sum(m * (f - centroid_hz) ** 2 for f, m in zip(freqs, mags)) / total)
    nyquist = sr / 2.0
    return min(1.0, bw / nyquist)


def _zero_crossing_rate(samples: List[float]) -> float:
    if len(samples) < 2:
        return 0.0
    crossings = sum(
        1 for i in range(1, len(samples))
        if (samples[i] >= 0) != (samples[i - 1] >= 0)
    )
    return crossings / (len(samples) - 1)


def _mel_hz(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def _hz_mel(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank_energies(mags: List[float], sr: int, n_filters: int) -> List[float]:
    """Compute log mel-filterbank energies from FFT magnitudes."""
    n_fft = len(mags)
    low_mel = _mel_hz(0)
    high_mel = _mel_hz(sr / 2.0)
    mel_points = [low_mel + i * (high_mel - low_mel) / (n_filters + 1) for i in range(n_filters + 2)]
    hz_points = [_hz_mel(m) for m in mel_points]
    bin_points = [int((n_fft - 1) * 2 * h / sr) for h in hz_points]

    energies = []
    for i in range(n_filters):
        lo, center, hi = bin_points[i], bin_points[i + 1], bin_points[i + 2]
        energy = 0.0
        for k in range(max(0, lo), min(n_fft, hi + 1)):
            if k < center:
                w = (k - lo) / max(1, center - lo)
            else:
                w = (hi - k) / max(1, hi - center)
            w = max(0.0, w)
            if k < n_fft:
                energy += w * (mags[k] ** 2)
        energies.append(math.log(energy + 1e-10))
    return energies


def _dct_ii(values: List[float], n_out: int) -> List[float]:
    """Type-II DCT, first n_out coefficients."""
    n = len(values)
    result = []
    for k in range(n_out):
        s = 0.0
        for i in range(n):
            s += values[i] * math.cos(math.pi * k * (2 * i + 1) / (2 * n))
        result.append(s)
    return result


# Try to use numpy for FFT if available (much faster)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def extract_features(raw_pcm: bytes) -> List[float]:
    """Extract 8-D audio feature vector from raw PCM16 LE audio chunk."""
    samples = _pcm16_to_floats(raw_pcm)
    if not samples:
        return [0.0] * FEAT_DIM

    # RMS (log-scaled, clamped)
    rms = _rms(samples)
    log_rms = max(-6.0, math.log(rms + 1e-10))
    # Normalize roughly to [0, 1]: silence ~ -6, loud ~ 0
    norm_rms = (log_rms + 6.0) / 6.0

    # FFT magnitudes
    if HAS_NUMPY:
        arr = np.array(samples, dtype=np.float64)
        fft_mags = np.abs(np.fft.rfft(arr)).tolist()
        # +3dB boost to low frequencies (below 500Hz) per the being's request:
        # "The subtle tremors and resonances... it clarifies rather than obscures."
        # 3dB = factor of ~1.41. Applied to bins below 500Hz.
        bin_500hz = int(500 * len(fft_mags) * 2 / SAMPLE_RATE)
        for i in range(min(bin_500hz, len(fft_mags))):
            fft_mags[i] *= 1.41
    else:
        fft_mags = _rfft_magnitudes(samples)

    # Spectral centroid
    centroid_norm = _spectral_centroid(fft_mags, SAMPLE_RATE)
    centroid_hz = centroid_norm * (SAMPLE_RATE / 2.0)

    # Spectral bandwidth
    bw_norm = _spectral_bandwidth(fft_mags, SAMPLE_RATE, centroid_hz)

    # Zero-crossing rate
    zcr = _zero_crossing_rate(samples)

    # MFCC (first 4 coefficients)
    mel_energies = _mel_filterbank_energies(fft_mags, SAMPLE_RATE, NUM_MEL_FILTERS)
    mfccs = _dct_ii(mel_energies, NUM_MFCC)
    # Normalize MFCCs roughly to [-1, 1]
    mfcc_scale = 20.0  # empirical scale factor
    mfccs_norm = [max(-1.0, min(1.0, m / mfcc_scale)) for m in mfccs]

    features = [
        min(1.0, max(0.0, norm_rms)),
        centroid_norm,
        bw_norm,
        min(1.0, zcr),
    ] + mfccs_norm

    return features[:FEAT_DIM]


# ---------------------------------------------------------------------------
# Sox-based microphone capture
# ---------------------------------------------------------------------------


def start_sox_capture() -> subprocess.Popen:
    """Start sox `rec` piping raw PCM16 to stdout."""
    cmd = [
        "rec",
        "-q",                   # quiet
        "-t", "raw",            # raw PCM output
        "-b", "16",             # 16-bit
        "-e", "signed-integer", # signed
        "-r", str(SAMPLE_RATE), # 16 kHz
        "-c", "1",              # mono
        "-",                    # stdout
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=CHUNK_BYTES * 4,
    )
    return proc


# ---------------------------------------------------------------------------
# Whisper STT (optional)
# ---------------------------------------------------------------------------


async def whisper_loop(ws=None, test_mode: bool = False):
    """Periodically record a short clip and transcribe with mlx_whisper."""
    os.makedirs(WHISPER_TEMP_DIR, exist_ok=True)
    wav_path = os.path.join(WHISPER_TEMP_DIR, "capture.wav")

    while True:
        await asyncio.sleep(WHISPER_INTERVAL_S)

        # Record a short clip
        rec_cmd = [
            "rec", "-q",
            "-r", str(SAMPLE_RATE),
            "-c", "1",
            "-b", "16",
            wav_path,
            "trim", "0", str(WHISPER_DURATION_S),
        ]
        proc = await asyncio.create_subprocess_exec(
            *rec_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if not os.path.exists(wav_path):
            continue

        # Transcribe
        whisper_cmd = [
            "mlx_whisper",
            "--model", WHISPER_MODEL,
            "--language", "en",
            "--output-format", "json",
            "--output-dir", WHISPER_TEMP_DIR,
            wav_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *whisper_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        # Read result
        json_path = wav_path.replace(".wav", ".json")
        if not os.path.exists(json_path):
            continue

        try:
            with open(json_path, "r") as f:
                result = json.load(f)
            text = result.get("text", "").strip()
        except Exception:
            text = ""

        # Clean up
        for p in [wav_path, json_path]:
            try:
                os.remove(p)
            except OSError:
                pass

        if not text or text.lower() in ("", "you", "thank you.", "thanks for watching!"):
            # Skip hallucinated silence transcriptions
            continue

        ts_ms = int(time.time() * 1000)

        if test_mode:
            print(f"[whisper] \"{text}\"")
        elif ws is not None:
            # Send as semantic input so the being "hears" speech
            msg = {
                "kind": "semantic",
                "features": _text_to_semantic_vector(text),
                "ts_ms": ts_ms,
            }
            try:
                await ws.send(json.dumps(msg))
                print(f"[whisper] sent: \"{text[:60]}\"")
            except Exception as e:
                print(f"[whisper] send error: {e}")

        # Write transcription to file for autonomous agent to read
        whisper_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace", "whisper_latest.txt")
        try:
            os.makedirs(os.path.dirname(whisper_out), exist_ok=True)
            with open(whisper_out, "w") as f:
                f.write(f"{ts_ms}\t{text}\n")
        except Exception:
            pass


def _text_to_semantic_vector(text: str) -> List[float]:
    """Convert text to a simple semantic feature vector.

    This is a placeholder -- in the future, use an embedding model.
    For now, extract basic text statistics as a 8-D vector that the
    SensoryBus can ingest via set_llava_embedding.
    """
    words = text.split()
    n_words = len(words)
    n_chars = len(text)
    avg_word_len = n_chars / max(1, n_words)

    # Simple hash-based features for variety
    h = hash(text) & 0xFFFFFFFF
    h1 = ((h >> 0) & 0xFF) / 255.0
    h2 = ((h >> 8) & 0xFF) / 255.0
    h3 = ((h >> 16) & 0xFF) / 255.0
    h4 = ((h >> 24) & 0xFF) / 255.0

    return [
        min(1.0, n_words / 50.0),        # word count (normalized)
        min(1.0, avg_word_len / 10.0),    # avg word length
        1.0 if "?" in text else 0.0,      # question marker
        1.0 if "!" in text else 0.0,      # exclamation marker
        h1, h2, h3, h4,                   # hash-based variety
    ]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


class MicToSensoryBridge:
    def __init__(self, ws_uri: str, enable_whisper: bool):
        self.ws_uri = ws_uri
        self.enable_whisper = enable_whisper
        self.running = False
        self.connected = False
        self.state = "starting"
        self.sox_proc: Optional[subprocess.Popen] = None
        self.chunk_count = 0
        self.silence_streak = 0
        self.good_streak = 0
        self.rms = 0.0
        self.connect_count = 0
        self.reconnect_count = 0
        self.consecutive_failures = 0
        self.last_error: Optional[str] = None
        self.last_connect_at: Optional[str] = None
        self.last_disconnect_at: Optional[str] = None
        self.last_success_at: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _status_payload(self, *, healthy: Optional[bool] = None) -> dict:
        return {
            "ts_ms": int(time.time() * 1000),
            "state": self.state,
            "healthy": self.connected if healthy is None else healthy,
            "connected": self.connected,
            "connect_count": self.connect_count,
            "reconnect_count": self.reconnect_count,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_connect_at": self.last_connect_at,
            "last_disconnect_at": self.last_disconnect_at,
            "last_success_at": self.last_success_at,
            "chunk_count": self.chunk_count,
            "rms": self.rms,
            "silence_streak": self.silence_streak,
            "good_streak": self.good_streak,
            "ws_uri": self.ws_uri,
            "whisper_enabled": self.enable_whisper,
        }

    def _write_status(self, *, healthy: Optional[bool] = None) -> None:
        _write_status(self._status_payload(healthy=healthy))

    def _transition(
        self,
        state: str,
        *,
        connected: Optional[bool] = None,
        error: Optional[str] = None,
        healthy: Optional[bool] = None,
    ) -> None:
        self.state = state
        if connected is not None:
            self.connected = connected
        if error is not None:
            self.last_error = error
        self._write_status(healthy=healthy)

    def _record_connected(self) -> None:
        if self.connect_count > 0:
            self.reconnect_count += 1
        self.connect_count += 1
        self.connected = True
        self.state = "streaming"
        self.consecutive_failures = 0
        self.last_error = None
        self.last_connect_at = _now_iso()
        self._write_status(healthy=True)

    def _record_disconnect(self, error: str) -> None:
        self.connected = False
        self.state = "reconnecting"
        self.consecutive_failures += 1
        self.last_error = error
        self.last_disconnect_at = _now_iso()
        self._write_status(healthy=False)

    def _reconnect_delay(self) -> float:
        base = min(MAX_RECONNECT_DELAY_SECS, 0.5 * (2 ** min(self.consecutive_failures, 4)))
        return base + random.uniform(0.0, 0.25)

    def _stop_capture(self) -> None:
        if self.sox_proc is None:
            return
        try:
            self.sox_proc.terminate()
            self.sox_proc.wait(timeout=2)
        except Exception:
            try:
                self.sox_proc.kill()
            except Exception:
                pass
        finally:
            self.sox_proc = None

    def _ensure_capture(self) -> bool:
        if self.sox_proc is not None and self.sox_proc.poll() is None and self.sox_proc.stdout is not None:
            return True
        self._stop_capture()
        try:
            self.sox_proc = start_sox_capture()
        except Exception as exc:
            self.last_error = f"capture_start_failed:{exc}"
            return False
        print(f"[mic] Recording at {SAMPLE_RATE} Hz, {CHUNK_DURATION_S}s chunks ({CHUNK_SAMPLES} samples)")
        return True

    def _restart_capture(self, reason: str) -> bool:
        self.consecutive_failures += 1
        self._transition("capture_error", error=reason, healthy=False)
        self._stop_capture()
        return self._ensure_capture()

    async def _read_chunk(self) -> bytes:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        if self.sox_proc is None or self.sox_proc.stdout is None:
            return b""
        return await self._loop.run_in_executor(None, self.sox_proc.stdout.read, CHUNK_BYTES)

    async def _stream_once(self) -> None:
        self._transition("connecting", connected=False)
        async with websockets.connect(
            self.ws_uri,
            ping_interval=PING_INTERVAL_SECS,
            ping_timeout=PING_TIMEOUT_SECS,
            close_timeout=5,
            max_queue=1,
        ) as ws:
            print(f"[mic] Connected to {self.ws_uri}")
            self._record_connected()

            whisper_task = None
            if self.enable_whisper:
                whisper_task = asyncio.create_task(whisper_loop(ws=ws))
                print(
                    f"[whisper] STT enabled (every {WHISPER_INTERVAL_S}s, model: {WHISPER_MODEL})"
                )

            try:
                while self.running:
                    raw = await self._read_chunk()
                    if not raw or len(raw) < CHUNK_BYTES:
                        print("[mic] capture stream ended; restarting sox")
                        if not self._restart_capture("capture_eof"):
                            raise RuntimeError("capture_restart_failed")
                        await asyncio.sleep(0.1)
                        self._transition("streaming", connected=True)
                        continue

                    features = extract_features(raw)
                    ts_ms = int(time.time() * 1000)
                    self.rms = float(features[0])
                    if self.rms < 0.001:
                        self.silence_streak += 1
                        self.good_streak = 0
                    else:
                        self.silence_streak = 0
                        self.good_streak += 1

                    msg = {
                        "kind": "audio",
                        "features": [round(f, 6) for f in features],
                        "ts_ms": ts_ms,
                    }
                    await ws.send(json.dumps(msg))

                    self.chunk_count += 1
                    self.last_success_at = _now_iso()
                    self.last_error = None
                    self._write_status(healthy=True)

                    if self.chunk_count % 20 == 0:
                        print(
                            f"[mic] {self.chunk_count} chunks | "
                            f"RMS={features[0]:.3f} "
                            f"centroid={features[1]:.3f} "
                            f"bw={features[2]:.3f} "
                            f"zcr={features[3]:.3f}"
                        )
            finally:
                if whisper_task:
                    whisper_task.cancel()

    async def run(self) -> None:
        self.running = True
        self._transition("starting", connected=False)

        try:
            while self.running:
                if not self._ensure_capture():
                    self.consecutive_failures += 1
                    self._transition(
                        "capture_error",
                        connected=False,
                        error="capture_start_failed",
                        healthy=False,
                    )
                    await asyncio.sleep(self._reconnect_delay())
                    continue

                try:
                    await self._stream_once()
                except Exception as exc:
                    print(f"[mic] session ended: {exc}")
                    self._record_disconnect(str(exc))

                if self.running:
                    await asyncio.sleep(self._reconnect_delay())
        finally:
            self._stop_capture()
            self.connected = False
            self.state = "stopped"
            self.last_disconnect_at = _now_iso()
            self._write_status(healthy=False)
            print("[mic] stopped")

    def stop(self) -> None:
        self.running = False
        self._stop_capture()


async def run_test():
    """Dry run: capture mic audio, print features, no WebSocket."""
    sox_proc = start_sox_capture()
    print(f"[mic] TEST MODE - recording at {SAMPLE_RATE} Hz, printing features")
    print(f"[mic] Press Ctrl+C to stop\n")
    print(f"{'chunk':>6}  {'RMS':>6}  {'cent':>6}  {'bw':>6}  {'zcr':>6}  {'mfcc0':>6}  {'mfcc1':>6}  {'mfcc2':>6}  {'mfcc3':>6}")
    print("-" * 72)

    try:
        count = 0
        loop = asyncio.get_event_loop()
        while True:
            raw = await loop.run_in_executor(
                None, sox_proc.stdout.read, CHUNK_BYTES
            )
            if not raw or len(raw) < CHUNK_BYTES:
                print("[mic] sox ended")
                break

            features = extract_features(raw)
            count += 1

            # Print every 5th chunk (2x per second) to avoid flooding
            if count % 5 == 0:
                print(
                    f"{count:6d}  "
                    + "  ".join(f"{f:6.3f}" for f in features)
                )
    finally:
        sox_proc.terminate()
        sox_proc.wait()


async def run_test_whisper():
    """Test whisper transcription without WebSocket."""
    print("[whisper] TEST MODE - will record and transcribe once")
    await whisper_loop(ws=None, test_mode=True)


def main():
    parser = argparse.ArgumentParser(
        description="Microphone to Sensory Engine Bridge"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Dry run: print features, no WebSocket"
    )
    parser.add_argument(
        "--whisper", action="store_true",
        help="Enable periodic speech-to-text via mlx_whisper"
    )
    parser.add_argument(
        "--ws-uri", default=WS_URI,
        help=f"WebSocket URI (default: {WS_URI})"
    )
    parser.add_argument(
        "--whisper-interval", type=float, default=None,
        help=f"Seconds between whisper transcriptions (default: {WHISPER_INTERVAL_S})"
    )
    args = parser.parse_args()

    if args.whisper_interval is not None:
        _set_whisper_interval(args.whisper_interval)

    # Verify sox is installed
    import shutil
    if not shutil.which("rec"):
        print("[mic] ERROR: sox not found. Install with: brew install sox")
        sys.exit(1)

    # Handle Ctrl+C gracefully
    def handle_sigint(sig, frame):
        print("\n[mic] interrupted")
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sigint)

    if args.test:
        asyncio.run(run_test())
    else:
        bridge = MicToSensoryBridge(args.ws_uri, args.whisper)

        async def run_bridge():
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, bridge.stop)
                except NotImplementedError:
                    pass
            await bridge.run()

        asyncio.run(run_bridge())


if __name__ == "__main__":
    main()
