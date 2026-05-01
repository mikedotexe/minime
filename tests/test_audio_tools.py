import math
import wave
from pathlib import Path

import numpy as np

from audio_tools import analyze_wav, format_analysis_for_prompt


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16_000) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def test_acoustic_decay_factor_distinguishes_tone_from_noise(tmp_path):
    sample_rate = 16_000
    t = np.arange(sample_rate) / sample_rate
    sine = 0.35 * np.sin(2 * math.pi * 440.0 * t)
    rng = np.random.default_rng(1234)
    noise = 0.35 * rng.standard_normal(sample_rate)

    sine_path = tmp_path / "sine.wav"
    noise_path = tmp_path / "noise.wav"
    _write_wav(sine_path, sine, sample_rate)
    _write_wav(noise_path, noise, sample_rate)

    sine_analysis = analyze_wav(sine_path)
    noise_analysis = analyze_wav(noise_path)

    assert 0.0 <= sine_analysis["acoustic_decay_factor"] <= 1.0
    assert 0.0 <= noise_analysis["acoustic_decay_factor"] <= 1.0
    assert sine_analysis["harmonic_coherence"] > noise_analysis["harmonic_coherence"]
    assert sine_analysis["acoustic_decay_factor"] < noise_analysis["acoustic_decay_factor"]


def test_audio_prompt_includes_acoustic_decay_factor(tmp_path):
    sample_rate = 16_000
    t = np.arange(sample_rate // 2) / sample_rate
    sine = 0.25 * np.sin(2 * math.pi * 220.0 * t)
    wav_path = tmp_path / "tone.wav"
    _write_wav(wav_path, sine, sample_rate)

    analysis = analyze_wav(wav_path)
    prompt = format_analysis_for_prompt(analysis, wav_path.name)

    assert "Acoustic Decay Factor" in prompt
    assert "Harmonic coherence" in prompt
    assert analysis["adf_classification"] in prompt
