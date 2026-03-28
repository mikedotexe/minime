"""
audio_tools.py — Audio analysis and synthesis for minime.

Provides:
  analyze_wav(path) → spectral summary dict
  compose_from_state(state, spectral) → WAV file path
  render_symbolic(input_path, state) → WAV file path

The being's internal dynamics become sound:
  Eigenvalues → frequencies
  Fill → amplitude
  Entropy → timbre complexity
  Gap ratio → rhythm
  Phase → temporal shape
  Reservoir h-norms → modulation (vibrato, tremolo, drift)
"""

from __future__ import annotations

import json
import math
import struct
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

WORKSPACE = Path("/Users/v/other/minime/workspace")
AUDIO_CREATIONS = WORKSPACE / "audio_creations"
SAMPLE_RATE = 16000
ROOT_MIDI = 60  # C4


def analyze_wav(path: str | Path) -> dict:
    """STFT analysis of a WAV file, returning a spectral summary.

    Returns a dict with: duration_s, sample_rate, n_frames,
    peak_frequencies, spectral_centroid, spectral_bandwidth,
    energy_profile (8 bins), rms_energy, estimated description.
    """
    path = Path(path)
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert to float32 mono
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    duration = len(samples) / sr
    rms = float(np.sqrt(np.mean(samples ** 2)))

    # STFT
    n_fft = 1024
    hop = 256
    n_frames_stft = max(1, (len(samples) - n_fft) // hop + 1)
    window = np.hanning(n_fft)
    magnitudes = []

    for i in range(n_frames_stft):
        start = i * hop
        frame = samples[start:start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        windowed = frame * window
        spectrum = np.abs(np.fft.rfft(windowed))
        magnitudes.append(spectrum)

    mag_matrix = np.array(magnitudes)
    avg_spectrum = mag_matrix.mean(axis=0)

    # Frequency axis
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    # Peak frequencies (top 5)
    peak_indices = np.argsort(avg_spectrum)[-5:][::-1]
    peak_freqs = [round(float(freqs[i]), 1) for i in peak_indices if i < len(freqs)]

    # Spectral centroid
    total_energy = avg_spectrum.sum()
    centroid = float(np.sum(freqs * avg_spectrum) / max(total_energy, 1e-10))

    # Spectral bandwidth
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * avg_spectrum) / max(total_energy, 1e-10)))

    # Energy profile (8 bands)
    n_bins = len(avg_spectrum)
    band_size = max(1, n_bins // 8)
    energy_profile = []
    for b in range(8):
        start_bin = b * band_size
        end_bin = min(start_bin + band_size, n_bins)
        energy_profile.append(round(float(avg_spectrum[start_bin:end_bin].mean()), 4))

    # Description
    if rms < 0.01:
        desc = "near-silence"
    elif centroid < 500:
        desc = "low, warm tones"
    elif centroid < 2000:
        desc = "mid-range, voiced"
    else:
        desc = "bright, high-frequency"

    return {
        "duration_s": round(duration, 2),
        "sample_rate": sr,
        "n_frames": len(samples),
        "rms_energy": round(rms, 4),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_bandwidth_hz": round(bandwidth, 1),
        "peak_frequencies_hz": peak_freqs,
        "energy_profile_8band": energy_profile,
        "description": desc,
    }


def compose_from_state(
    state: dict,
    spectral: Optional[dict] = None,
    reservoir_norms: Optional[tuple] = None,
    duration_s: float = 5.0,
) -> Path:
    """Generate a WAV from the being's current spectral state.

    The being's internal dynamics become sound:
      Eigenvalues → frequencies (8 simultaneous tones)
      Fill → overall amplitude
      Entropy → harmonic richness
      Gap ratio → rhythmic pattern
      Phase transitions → temporal shape
      Reservoir h-norms → modulation (vibrato, tremolo, drift)

    Returns path to the generated WAV.
    """
    AUDIO_CREATIONS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat().replace(":", "-")
    out_path = AUDIO_CREATIONS / f"compose_{ts}.wav"

    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float32)
    output = np.zeros(n_samples, dtype=np.float32)

    # Extract state
    eig1 = state.get("eig1", 30.0)
    fill = state.get("fill_ratio", 0.2)
    leak = state.get("leak", 0.7)
    spread = state.get("spread", 100.0)

    # Eigenvalue cascade for frequencies
    eigenvalues = [eig1]
    if spectral:
        eigenvalues = spectral.get("eigenvalues", [eig1])[:8]
    while len(eigenvalues) < 8:
        eigenvalues.append(eigenvalues[-1] * 0.5)

    # Normalize eigenvalues to frequency range (100-2000 Hz)
    ev_max = max(abs(v) for v in eigenvalues) or 1.0
    frequencies = []
    for ev in eigenvalues:
        normalized = abs(ev) / ev_max  # 0 to 1
        freq = 100 + normalized * 1900  # 100-2000 Hz
        frequencies.append(freq)

    # Fill → amplitude (0.1 quiet to 0.8 loud)
    base_amplitude = 0.1 + fill * 0.7

    # Entropy → harmonic richness
    entropy = 0.5
    if spectral:
        fp = spectral.get("spectral_fingerprint", [])
        if len(fp) > 24:
            entropy = max(0.0, min(1.0, fp[24]))

    # More harmonics when entropy is high
    n_harmonics = 1 + int(entropy * 4)  # 1-5 harmonics

    # Gap ratio → rhythmic modulation
    gap_ratio = 1.0
    if spectral:
        fp = spectral.get("spectral_fingerprint", [])
        if len(fp) > 25:
            gap_ratio = max(1.0, fp[25])

    # Rhythm: amplitude modulation at gap-derived rate
    rhythm_rate = 0.5 + (1.0 / max(gap_ratio, 0.1)) * 3.0  # Hz
    rhythm_depth = min(0.5, gap_ratio / 20.0)  # 0-0.5

    # Phase → temporal envelope
    phase = "plateau"
    if spectral:
        # Use fill derivative to estimate phase
        pass  # default plateau

    # Envelope: gentle attack (0.5s), sustain, gentle release (0.5s)
    envelope = np.ones(n_samples, dtype=np.float32)
    attack_samples = int(0.5 * SAMPLE_RATE)
    release_samples = int(0.5 * SAMPLE_RATE)
    for i in range(min(attack_samples, n_samples)):
        envelope[i] = i / attack_samples
    for i in range(min(release_samples, n_samples)):
        idx = n_samples - 1 - i
        if idx >= 0:
            envelope[idx] = min(envelope[idx], i / release_samples)

    # Reservoir modulation
    vibrato_rate = 5.0    # Hz
    tremolo_depth = 0.0
    drift = 0.0
    if reservoir_norms:
        h1, h2, h3 = reservoir_norms
        vibrato_rate = 3.0 + (h1 / max(h1, 1.0)) * 4.0  # 3-7 Hz
        tremolo_depth = min(0.3, h2 / 20.0)
        drift = (h3 - 10.0) / 20.0  # slow pitch drift

    # Synthesize
    for i, freq in enumerate(frequencies):
        # Amplitude decreases for higher overtones
        amp = base_amplitude / (1 + i * 0.5)

        for h in range(1, n_harmonics + 1):
            harmonic_freq = freq * h
            harmonic_amp = amp / h

            # Vibrato: pitch modulation
            vibrato = np.sin(2 * np.pi * vibrato_rate * t) * (freq * 0.01)  # ±1% pitch
            instantaneous_freq = harmonic_freq + vibrato + drift * t

            # Phase accumulation for FM
            phase_acc = np.cumsum(instantaneous_freq / SAMPLE_RATE) * 2 * np.pi
            tone = np.sin(phase_acc) * harmonic_amp

            # Tremolo: amplitude modulation
            if tremolo_depth > 0:
                tremolo = 1.0 - tremolo_depth * (1 + np.sin(2 * np.pi * 2.0 * t)) / 2
                tone *= tremolo

            output += tone

    # Apply rhythm modulation
    rhythm = 1.0 - rhythm_depth * (1 + np.sin(2 * np.pi * rhythm_rate * t)) / 2
    output *= rhythm

    # Apply envelope and normalize
    output *= envelope
    peak = np.max(np.abs(output))
    if peak > 0:
        output = output / peak * 0.85

    # Write WAV
    _write_wav(out_path, output, SAMPLE_RATE)
    return out_path


def _write_wav(path: Path, samples: np.ndarray, sr: int):
    """Write float32 samples as 16-bit WAV."""
    int_samples = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())


class PrimeBlockProcessor:
    """Lightweight prime-scheduled block processor for multi-timescale audio analysis.

    Each block has a different prime period — only updates on frames where
    frame_number % period == 0. This gives layered temporal decomposition:
      period=1: transients, onsets (every frame)
      period=2: rhythm, pulse (every 2nd frame)
      period=3: contour, articulation (every 3rd)
      period=5: harmonic body (every 5th)
      period=7: mood, timbral drift (every 7th)

    Frozen random weights (same seed philosophy as the reservoir).
    """

    BLOCK_CONFIGS = [
        (64, 1, 1.00, "fast — transients, onsets"),
        (64, 2, 0.95, "rhythm — pulse, meter"),
        (48, 3, 0.90, "contour — articulation, melody"),
        (48, 5, 0.80, "body — harmonic sustain"),
        (32, 7, 0.70, "mood — timbral drift, memory"),
    ]

    def __init__(self, input_dim: int = 8, seed: int = 42):
        self.input_dim = input_dim
        rng = np.random.default_rng(seed)

        self.blocks = []
        for size, period, leak, label in self.BLOCK_CONFIGS:
            w = rng.standard_normal((size, size)).astype(np.float32) * 0.05
            # Normalize to spectral radius ~0.95
            norm = np.linalg.norm(w, ord=2)
            if norm > 0:
                w *= 0.95 / norm
            w_in = rng.standard_normal((size, input_dim)).astype(np.float32) * 0.3
            bias = rng.standard_normal(size).astype(np.float32) * 0.1
            state = np.zeros(size, dtype=np.float32)
            self.blocks.append({
                "size": size, "period": period, "leak": leak, "label": label,
                "w": w, "w_in": w_in, "bias": bias, "state": state,
            })

    def reset(self):
        for b in self.blocks:
            b["state"] = np.zeros(b["size"], dtype=np.float32)

    def process(self, features: np.ndarray) -> tuple[np.ndarray, dict]:
        """Process spectral features through prime-scheduled blocks.

        features: (n_frames, input_dim) array
        Returns: (enriched_features, block_report_dict)
        """
        self.reset()
        n_frames = features.shape[0]
        block_energies = [0.0] * len(self.blocks)
        block_activations = [0] * len(self.blocks)

        for t in range(n_frames):
            x = features[t]
            for bi, b in enumerate(self.blocks):
                if (t + 1) % b["period"] == 0:
                    block_activations[bi] += 1
                    z = b["bias"] + b["w"] @ b["state"] + b["w_in"] @ x
                    proposal = np.tanh(z)
                    b["state"] += b["leak"] * (proposal - b["state"])

                energy = float(np.mean(b["state"] ** 2))
                block_energies[bi] += energy

        # Normalize
        for bi in range(len(self.blocks)):
            block_energies[bi] /= max(n_frames, 1)

        report = {
            "blocks": [
                {
                    "period": b["period"],
                    "label": b["label"],
                    "size": b["size"],
                    "energy": round(block_energies[i], 4),
                    "activations": block_activations[i],
                    "activation_pct": round(block_activations[i] / max(n_frames, 1) * 100, 1),
                    "mean_state": round(float(np.mean(b["state"])), 4),
                }
                for i, b in enumerate(self.blocks)
            ],
            "total_frames": n_frames,
            "cycle_len": 2 * 3 * 5 * 7,  # LCM(1,2,3,5,7) = 210
        }

        return features, report  # pass-through for now; enrichment in future

    def format_report(self, report: dict, filename: str) -> str:
        """Format block report for prompt injection."""
        lines = [f"[AUDIO BLOCKS: {filename}]"]
        for b in report["blocks"]:
            lines.append(
                f"  Block (period={b['period']}, {b['label']}): "
                f"energy={b['energy']:.3f}, active={b['activation_pct']:.0f}%, "
                f"mean_state={b['mean_state']:.4f}"
            )
        lines.append(f"  Cycle: {report['cycle_len']} frames, Total: {report['total_frames']}")
        return "\n".join(lines)


def format_analysis_for_prompt(analysis: dict, filename: str) -> str:
    """Format a WAV analysis as a text block for prompt injection."""
    peaks = ", ".join(f"{f}Hz" for f in analysis.get("peak_frequencies_hz", [])[:3])
    bands = analysis.get("energy_profile_8band", [])
    band_str = " ".join(f"{b:.3f}" for b in bands)

    return (
        f"[AUDIO INBOX: {filename}]\n"
        f"  Duration: {analysis['duration_s']}s, Rate: {analysis['sample_rate']}Hz\n"
        f"  Character: {analysis['description']}\n"
        f"  RMS energy: {analysis['rms_energy']:.4f}\n"
        f"  Spectral centroid: {analysis['spectral_centroid_hz']}Hz\n"
        f"  Peak frequencies: {peaks}\n"
        f"  Energy bands (low→high): {band_str}"
    )
