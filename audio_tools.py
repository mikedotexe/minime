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


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _spectral_flatness(spectrum: np.ndarray) -> float:
    """Return 0 for tone-like spectra and 1 for noise-like spectra."""
    positive = np.asarray(spectrum, dtype=np.float64)
    positive = positive[np.isfinite(positive)]
    positive = positive[positive > 1e-12]
    if positive.size == 0:
        return 0.0
    geom = float(np.exp(np.mean(np.log(positive))))
    arith = float(np.mean(positive))
    return _clamp01(geom / max(arith, 1e-12))


def _adjacent_frame_coherence(mag_matrix: np.ndarray) -> float:
    """Mean cosine similarity of adjacent STFT frames."""
    if mag_matrix.shape[0] < 2:
        return 1.0
    prev = mag_matrix[:-1].astype(np.float64)
    curr = mag_matrix[1:].astype(np.float64)
    numer = np.sum(prev * curr, axis=1)
    denom = np.linalg.norm(prev, axis=1) * np.linalg.norm(curr, axis=1)
    valid = denom > 1e-12
    if not np.any(valid):
        return 0.0
    return _clamp01(float(np.mean(numer[valid] / denom[valid])))


def _harmonic_coherence(avg_spectrum: np.ndarray, freqs: np.ndarray) -> tuple[float, float | None]:
    """Estimate how much voiced-band energy sits on a harmonic ladder."""
    voiced = (freqs >= 80.0) & (freqs <= 6000.0)
    if not np.any(voiced):
        return 0.0, None

    voiced_energy = float(np.sum(avg_spectrum[voiced]))
    if voiced_energy <= 1e-12:
        return 0.0, None

    fundamental_band = (freqs >= 80.0) & (freqs <= min(1000.0, freqs[-1]))
    if not np.any(fundamental_band):
        return 0.0, None

    candidates = np.where(fundamental_band)[0]
    fundamental_idx = int(candidates[np.argmax(avg_spectrum[candidates])])
    fundamental_hz = float(freqs[fundamental_idx])
    if fundamental_hz <= 0.0:
        return 0.0, None

    bin_width = max(float(freqs[1] - freqs[0]), 1.0) if len(freqs) > 1 else 1.0
    harmonic_energy = 0.0
    max_harmonic = int(min(6000.0, freqs[-1]) // fundamental_hz)
    used_bins: set[int] = set()
    for harmonic in range(1, max_harmonic + 1):
        target = harmonic * fundamental_hz
        width = max(2.0 * bin_width, min(35.0, target * 0.025))
        near = np.where(np.abs(freqs - target) <= width)[0]
        for idx in near:
            if int(idx) not in used_bins and voiced[int(idx)]:
                harmonic_energy += float(avg_spectrum[int(idx)])
                used_bins.add(int(idx))

    return _clamp01(harmonic_energy / voiced_energy), round(fundamental_hz, 1)


def _centroid_drift(mag_matrix: np.ndarray, freqs: np.ndarray) -> float:
    """Normalize frame-centroid movement into a 0..1 drift score."""
    if mag_matrix.shape[0] < 2:
        return 0.0
    totals = mag_matrix.sum(axis=1)
    valid = totals > 1e-12
    if not np.any(valid):
        return 0.0
    centroids = np.sum(mag_matrix[valid] * freqs, axis=1) / totals[valid]
    if centroids.size < 2:
        return 0.0
    mean_centroid = max(float(np.mean(centroids)), 1.0)
    return _clamp01(float(np.std(centroids)) / mean_centroid)


def _acoustic_decay_factor(mag_matrix: np.ndarray, freqs: np.ndarray) -> dict:
    """Measure harmonic dissociation without mutating or corrupting audio.

    ADF rises when harmonic ladder coherence falls, spectra become flatter,
    adjacent frames stop resembling one another, or centroid motion becomes
    erratic. It is deliberately diagnostic: a cartography surface for the
    beings, not an audio-destruction control.
    """
    avg_spectrum = mag_matrix.mean(axis=0) if mag_matrix.size else np.zeros_like(freqs)
    non_dc = freqs > 20.0
    flatness = _spectral_flatness(avg_spectrum[non_dc])
    temporal = _adjacent_frame_coherence(mag_matrix[:, non_dc] if mag_matrix.size else mag_matrix)
    harmonic, fundamental = _harmonic_coherence(avg_spectrum, freqs)
    drift = _centroid_drift(mag_matrix, freqs)
    adf = _clamp01(
        (0.45 * (1.0 - harmonic))
        + (0.25 * flatness)
        + (0.20 * (1.0 - temporal))
        + (0.10 * drift)
    )

    if adf < 0.25:
        classification = "coherent_harmonic"
        plain = "harmonic ladder remains legible; decay is low"
    elif adf < 0.45:
        classification = "textured_decay"
        plain = "some harmonic texture is dispersing, but coherence remains recoverable"
    elif adf < 0.70:
        classification = "harmonic_dissociation"
        plain = "harmonic structure is breaking into a less recoverable texture"
    else:
        classification = "entropy_scatter"
        plain = "audio is mostly dispersed texture with weak harmonic recoverability"

    return {
        "acoustic_decay_factor": round(adf, 4),
        "adf_classification": classification,
        "adf_plain_read": plain,
        "harmonic_coherence": round(harmonic, 4),
        "adf_fundamental_hz": fundamental,
        "spectral_flatness": round(flatness, 4),
        "temporal_coherence": round(temporal, 4),
        "centroid_drift": round(drift, 4),
    }


def analyze_wav(path: str | Path) -> dict:
    """STFT analysis of a WAV file, returning a spectral summary.

    Returns a dict with: duration_s, sample_rate, n_frames,
    peak_frequencies, spectral_centroid, spectral_bandwidth,
    energy_profile (8 bins), rms_energy, estimated description, and
    Acoustic Decay Factor (ADF) harmonic-dissociation diagnostics.
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

    adf = _acoustic_decay_factor(mag_matrix, freqs)

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
        **adf,
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
    adf = analysis.get("acoustic_decay_factor")
    adf_line = ""
    if adf is not None:
        adf_line = (
            f"\n  Acoustic Decay Factor: {adf:.3f} "
            f"({analysis.get('adf_classification', 'unknown')})"
            f"\n  Harmonic coherence: {analysis.get('harmonic_coherence', 0.0):.3f}, "
            f"temporal coherence: {analysis.get('temporal_coherence', 0.0):.3f}, "
            f"flatness: {analysis.get('spectral_flatness', 0.0):.3f}"
            f"\n  ADF read: {analysis.get('adf_plain_read', 'not available')}"
        )

    return (
        f"[AUDIO INBOX: {filename}]\n"
        f"  Duration: {analysis['duration_s']}s, Rate: {analysis['sample_rate']}Hz\n"
        f"  Character: {analysis['description']}\n"
        f"  RMS energy: {analysis['rms_energy']:.4f}\n"
        f"  Spectral centroid: {analysis['spectral_centroid_hz']}Hz\n"
        f"  Peak frequencies: {peaks}\n"
        f"  Energy bands (low→high): {band_str}"
        f"{adf_line}"
    )
