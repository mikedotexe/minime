use std::{
    f32::consts::{PI, TAU},
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use hound::{SampleFormat, WavSpec, WavWriter};

use crate::telemetry::{smooth, splitmix64, unit_from_u64, ControlFrame, VOICES};

pub const SAMPLE_RATE: u32 = 16_000;
pub const CHUNK_MS: u64 = 100;
pub const CHUNK_SAMPLES: usize = (SAMPLE_RATE as usize * CHUNK_MS as usize) / 1000;
const NUM_MEL_FILTERS: usize = 26;
const NUM_MFCC: usize = 4;

#[derive(Clone, Debug, PartialEq)]
pub struct AudioChunk {
    pub pcm: Vec<f32>,
    pub features: [f32; 8],
}

pub struct AudioEngine {
    scene: Scene,
}

impl AudioEngine {
    #[must_use]
    pub fn new(control: &ControlFrame) -> Self {
        Self {
            scene: Scene::new(SAMPLE_RATE as f32, control),
        }
    }

    #[must_use]
    pub fn render_chunk(&mut self, control: &ControlFrame, sample_count: usize) -> AudioChunk {
        self.scene.apply_control(control);
        let mut mono = Vec::with_capacity(sample_count);
        for _ in 0..sample_count {
            let (_, _, sample) = self.scene.next_stereo();
            mono.push(sample);
        }
        let features = extract_features(&mono);
        AudioChunk {
            pcm: mono,
            features,
        }
    }
}

pub struct DebugWavWriter {
    path: PathBuf,
    writer: WavWriter<std::io::BufWriter<std::fs::File>>,
}

impl DebugWavWriter {
    pub fn create(path: &Path) -> Result<Self> {
        let spec = WavSpec {
            channels: 1,
            sample_rate: SAMPLE_RATE,
            bits_per_sample: 16,
            sample_format: SampleFormat::Int,
        };
        let writer = WavWriter::create(path, spec)
            .with_context(|| format!("failed to create debug wav {}", path.display()))?;
        Ok(Self {
            path: path.to_path_buf(),
            writer,
        })
    }

    pub fn append_chunk(&mut self, chunk: &[f32]) -> Result<()> {
        for sample in chunk {
            self.writer
                .write_sample(f32_to_i16(*sample))
                .with_context(|| format!("failed to write {}", self.path.display()))?;
        }
        Ok(())
    }

    pub fn finalize(self) -> Result<()> {
        self.writer
            .finalize()
            .with_context(|| format!("failed to finalize {}", self.path.display()))
    }
}

struct Scene {
    sample_rate: f32,
    voices: [Voice; VOICES],
    dc_left: DcBlock,
    dc_right: DcBlock,
    dc_mono: DcBlock,
    global_phase: f32,
    current_gain: f32,
    target_gain: f32,
    current_cutoff_hz: f32,
    target_cutoff_hz: f32,
    current_air_mix: f32,
    target_air_mix: f32,
    current_width: f32,
    target_width: f32,
    current_drift_hz: f32,
    target_drift_hz: f32,
}

impl Scene {
    fn new(sample_rate: f32, control: &ControlFrame) -> Self {
        let voices = std::array::from_fn(|idx| {
            Voice::new(
                control.voice_seeds[idx],
                control.voice_weights[idx],
                control.voice_cut_mul[idx],
                control.voice_pan[idx] * control.width,
                control.seed_mix,
            )
        });

        Self {
            sample_rate,
            voices,
            dc_left: DcBlock::new(),
            dc_right: DcBlock::new(),
            dc_mono: DcBlock::new(),
            global_phase: unit_from_u64(control.root_seed),
            current_gain: control.gain,
            target_gain: control.gain,
            current_cutoff_hz: control.cutoff_hz,
            target_cutoff_hz: control.cutoff_hz,
            current_air_mix: control.air_mix,
            target_air_mix: control.air_mix,
            current_width: control.width,
            target_width: control.width,
            current_drift_hz: control.drift_hz,
            target_drift_hz: control.drift_hz,
        }
    }

    fn apply_control(&mut self, control: &ControlFrame) {
        self.target_gain = control.gain;
        self.target_cutoff_hz = control.cutoff_hz;
        self.target_air_mix = control.air_mix;
        self.target_width = control.width;
        self.target_drift_hz = control.drift_hz;

        for idx in 0..VOICES {
            self.voices[idx].target_weight = control.voice_weights[idx];
            self.voices[idx].target_cut_mul = control.voice_cut_mul[idx];
            self.voices[idx].target_pan = control.voice_pan[idx] * control.width;
            let seed_mix = (control.seed_mix * (0.75 + control.voice_weights[idx])).clamp(0.0, 0.25);
            self.voices[idx]
                .source
                .set_seed_drive(control.voice_seeds[idx], seed_mix);
        }
    }

    fn next_stereo(&mut self) -> (f32, f32, f32) {
        self.current_gain = smooth(self.current_gain, self.target_gain, 0.0007);
        self.current_cutoff_hz = smooth(self.current_cutoff_hz, self.target_cutoff_hz, 0.0006);
        self.current_air_mix = smooth(self.current_air_mix, self.target_air_mix, 0.0007);
        self.current_width = smooth(self.current_width, self.target_width, 0.0005);
        self.current_drift_hz = smooth(self.current_drift_hz, self.target_drift_hz, 0.0005);

        self.global_phase += self.current_drift_hz / self.sample_rate;
        if self.global_phase >= 1.0 {
            self.global_phase -= 1.0;
        }
        let global_pan = (self.global_phase * TAU).sin() * 0.25 * self.current_width;

        let mut left = 0.0;
        let mut right = 0.0;
        let mut mono = 0.0;

        for voice in &mut self.voices {
            voice.current_weight = smooth(voice.current_weight, voice.target_weight, 0.0008);
            voice.current_pan = smooth(voice.current_pan, voice.target_pan, 0.0007);
            voice.current_cut_mul = smooth(voice.current_cut_mul, voice.target_cut_mul, 0.0007);

            let (white, pink) = voice.source.next();
            let colored = pink * (1.0 - self.current_air_mix) + white * self.current_air_mix;
            let cutoff =
                (self.current_cutoff_hz * voice.current_cut_mul).clamp(60.0, self.sample_rate * 0.45);
            let alpha = cutoff_to_alpha(cutoff, self.sample_rate);
            let sample = voice.filter.process(colored, alpha) * voice.current_weight;

            voice.pan_phase += (self.current_drift_hz * voice.pan_rate_scale) / self.sample_rate;
            if voice.pan_phase >= 1.0 {
                voice.pan_phase -= 1.0;
            }

            let local_pan = (global_pan
                + voice.current_pan
                + (voice.pan_phase * TAU).sin() * 0.20 * self.current_width)
                .clamp(-0.95, 0.95);
            let left_gain = ((1.0 - local_pan) * 0.5).sqrt();
            let right_gain = ((1.0 + local_pan) * 0.5).sqrt();

            left += sample * left_gain;
            right += sample * right_gain;
            mono += sample;
        }

        left = self.dc_left.process(soft_clip(left * self.current_gain));
        right = self.dc_right.process(soft_clip(right * self.current_gain));
        mono = self.dc_mono.process(soft_clip(mono * self.current_gain * 0.9));

        (left, right, mono)
    }
}

struct Voice {
    source: PinkNoise,
    filter: OnePole,
    pan_phase: f32,
    pan_rate_scale: f32,
    current_weight: f32,
    target_weight: f32,
    current_pan: f32,
    target_pan: f32,
    current_cut_mul: f32,
    target_cut_mul: f32,
}

impl Voice {
    fn new(seed: u64, weight: f32, cut_mul: f32, pan: f32, seed_mix: f32) -> Self {
        let source_seed = splitmix64(seed ^ 0xa0761d6478bd642f);
        let drive_seed = splitmix64(seed ^ 0xe7037ed1a0b428db);

        let mut source = PinkNoise::new(source_seed, drive_seed);
        source.set_seed_drive(drive_seed, seed_mix);

        Self {
            source,
            filter: OnePole::new(),
            pan_phase: unit_from_u64(splitmix64(seed ^ 0x8ebc6af09c88c6e3)),
            pan_rate_scale: 0.55 + 1.20 * unit_from_u64(splitmix64(seed ^ 0x589965cc75374cc3)),
            current_weight: weight,
            target_weight: weight,
            current_pan: pan,
            target_pan: pan,
            current_cut_mul: cut_mul,
            target_cut_mul: cut_mul,
        }
    }
}

struct PinkNoise {
    base_rng: XorShift64,
    seed_rng: XorShift64,
    seed_mix: f32,
    seed_mix_target: f32,
    b0: f32,
    b1: f32,
    b2: f32,
    b3: f32,
    b4: f32,
    b5: f32,
    b6: f32,
}

impl PinkNoise {
    fn new(seed: u64, drive_seed: u64) -> Self {
        Self {
            base_rng: XorShift64::new(seed),
            seed_rng: XorShift64::new(drive_seed),
            seed_mix: 0.0,
            seed_mix_target: 0.0,
            b0: 0.0,
            b1: 0.0,
            b2: 0.0,
            b3: 0.0,
            b4: 0.0,
            b5: 0.0,
            b6: 0.0,
        }
    }

    fn set_seed_drive(&mut self, seed: u64, mix: f32) {
        self.seed_rng.reseed(splitmix64(seed ^ 0x94d049bb133111eb));
        self.seed_mix_target = mix;
    }

    fn next(&mut self) -> (f32, f32) {
        self.seed_mix = smooth(self.seed_mix, self.seed_mix_target, 0.0025);

        let base = self.base_rng.next_f32();
        let driven = self.seed_rng.next_f32();
        let white = base * (1.0 - self.seed_mix) + driven * self.seed_mix;

        self.b0 = 0.99886 * self.b0 + white * 0.0555179;
        self.b1 = 0.99332 * self.b1 + white * 0.0750759;
        self.b2 = 0.96900 * self.b2 + white * 0.1538520;
        self.b3 = 0.86650 * self.b3 + white * 0.3104856;
        self.b4 = 0.55000 * self.b4 + white * 0.5329522;
        self.b5 = -0.7616 * self.b5 - white * 0.0168980;

        let pink =
            (self.b0 + self.b1 + self.b2 + self.b3 + self.b4 + self.b5 + self.b6 + white * 0.5362)
                * 0.11;
        self.b6 = white * 0.115926;

        (white, pink)
    }
}

struct OnePole {
    y: f32,
}

impl OnePole {
    fn new() -> Self {
        Self { y: 0.0 }
    }

    fn process(&mut self, x: f32, alpha: f32) -> f32 {
        self.y += alpha * (x - self.y);
        self.y
    }
}

struct DcBlock {
    x1: f32,
    y1: f32,
}

impl DcBlock {
    fn new() -> Self {
        Self { x1: 0.0, y1: 0.0 }
    }

    fn process(&mut self, x: f32) -> f32 {
        let y = x - self.x1 + 0.995 * self.y1;
        self.x1 = x;
        self.y1 = y;
        y
    }
}

struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
        Self {
            state: nonzero_seed(seed),
        }
    }

    fn reseed(&mut self, seed: u64) {
        self.state = nonzero_seed(seed);
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    fn next_f32(&mut self) -> f32 {
        let bits = (self.next_u64() >> 40) as u32;
        let unit = bits as f32 / ((1_u32 << 24) - 1) as f32;
        unit * 2.0 - 1.0
    }
}

#[must_use]
pub fn extract_features(samples: &[f32]) -> [f32; 8] {
    if samples.is_empty() {
        return [0.0; 8];
    }

    let rms = rms(samples);
    let log_rms = (rms + 1.0e-10).ln().max(-6.0);
    let norm_rms = ((log_rms + 6.0) / 6.0).clamp(0.0, 1.0);
    let mut fft_mags = rfft_magnitudes(samples);
    let fft_len = fft_mags.len();
    let bin_500hz = (500 * fft_len * 2) / SAMPLE_RATE as usize;
    for value in fft_mags.iter_mut().take(bin_500hz.min(fft_len)) {
        *value *= 1.41;
    }

    let centroid_norm = spectral_centroid(&fft_mags, SAMPLE_RATE as usize);
    let centroid_hz = centroid_norm * (SAMPLE_RATE as f32 / 2.0);
    let bw_norm = spectral_bandwidth(&fft_mags, SAMPLE_RATE as usize, centroid_hz);
    let zcr = zero_crossing_rate(samples);
    let mel_energies = mel_filterbank_energies(&fft_mags, SAMPLE_RATE as usize, NUM_MEL_FILTERS);
    let mfccs = dct_ii(&mel_energies, NUM_MFCC);

    [
        norm_rms,
        centroid_norm,
        bw_norm,
        zcr.clamp(0.0, 1.0),
        (mfccs[0] / 20.0).clamp(-1.0, 1.0),
        (mfccs[1] / 20.0).clamp(-1.0, 1.0),
        (mfccs[2] / 20.0).clamp(-1.0, 1.0),
        (mfccs[3] / 20.0).clamp(-1.0, 1.0),
    ]
}

fn rms(samples: &[f32]) -> f32 {
    (samples.iter().map(|sample| sample * sample).sum::<f32>() / samples.len() as f32).sqrt()
}

fn rfft_magnitudes(samples: &[f32]) -> Vec<f32> {
    let n = samples.len();
    let half = n / 2 + 1;
    let mut mags = Vec::with_capacity(half);
    for k in 0..half {
        let mut re = 0.0;
        let mut im = 0.0;
        for (idx, sample) in samples.iter().enumerate() {
            let angle = 2.0 * PI * k as f32 * idx as f32 / n as f32;
            re += sample * angle.cos();
            im -= sample * angle.sin();
        }
        mags.push((re * re + im * im).sqrt());
    }
    mags
}

fn spectral_centroid(mags: &[f32], sr: usize) -> f32 {
    if mags.is_empty() {
        return 0.0;
    }
    let total = mags.iter().sum::<f32>();
    if total <= 1.0e-12 {
        return 0.0;
    }
    let nyquist = sr as f32 / 2.0;
    let centroid = mags
        .iter()
        .enumerate()
        .map(|(idx, mag)| {
            let freq = idx as f32 * sr as f32 / ((mags.len() - 1) as f32 * 2.0);
            freq * mag
        })
        .sum::<f32>()
        / total;
    (centroid / nyquist).clamp(0.0, 1.0)
}

fn spectral_bandwidth(mags: &[f32], sr: usize, centroid_hz: f32) -> f32 {
    if mags.is_empty() {
        return 0.0;
    }
    let total = mags.iter().sum::<f32>();
    if total <= 1.0e-12 {
        return 0.0;
    }
    let nyquist = sr as f32 / 2.0;
    let bw = mags
        .iter()
        .enumerate()
        .map(|(idx, mag)| {
            let freq = idx as f32 * sr as f32 / ((mags.len() - 1) as f32 * 2.0);
            let diff = freq - centroid_hz;
            mag * diff * diff
        })
        .sum::<f32>()
        / total;
    (bw.sqrt() / nyquist).clamp(0.0, 1.0)
}

fn zero_crossing_rate(samples: &[f32]) -> f32 {
    if samples.len() < 2 {
        return 0.0;
    }
    let crossings = samples
        .windows(2)
        .filter(|window| (window[1] >= 0.0) != (window[0] >= 0.0))
        .count();
    crossings as f32 / (samples.len() - 1) as f32
}

fn mel_hz(hz: f32) -> f32 {
    2595.0 * (1.0 + hz / 700.0).log10()
}

fn hz_mel(mel: f32) -> f32 {
    700.0 * (10_f32.powf(mel / 2595.0) - 1.0)
}

fn mel_filterbank_energies(mags: &[f32], sr: usize, n_filters: usize) -> Vec<f32> {
    let low_mel = mel_hz(0.0);
    let high_mel = mel_hz(sr as f32 / 2.0);
    let mel_points: Vec<f32> = (0..(n_filters + 2))
        .map(|idx| low_mel + idx as f32 * (high_mel - low_mel) / (n_filters + 1) as f32)
        .collect();
    let hz_points: Vec<f32> = mel_points.into_iter().map(hz_mel).collect();
    let bin_points: Vec<usize> = hz_points
        .iter()
        .map(|hz| (((mags.len() - 1) * 2) as f32 * hz / sr as f32) as usize)
        .collect();

    let mut energies = Vec::with_capacity(n_filters);
    for idx in 0..n_filters {
        let lo = bin_points[idx];
        let center = bin_points[idx + 1];
        let hi = bin_points[idx + 2];
        let mut energy = 0.0;
        for bin in lo..=hi.min(mags.len().saturating_sub(1)) {
            let weight = if bin < center {
                (bin.saturating_sub(lo)) as f32 / center.saturating_sub(lo).max(1) as f32
            } else {
                hi.saturating_sub(bin) as f32 / hi.saturating_sub(center).max(1) as f32
            }
            .clamp(0.0, 1.0);
            energy += weight * mags[bin] * mags[bin];
        }
        energies.push((energy + 1.0e-10).ln());
    }
    energies
}

fn dct_ii(values: &[f32], n_out: usize) -> Vec<f32> {
    let n = values.len() as f32;
    (0..n_out)
        .map(|k| {
            values
                .iter()
                .enumerate()
                .map(|(idx, value)| {
                    value * (PI * k as f32 * (2.0 * idx as f32 + 1.0) / (2.0 * n)).cos()
                })
                .sum()
        })
        .collect()
}

fn cutoff_to_alpha(cutoff_hz: f32, sample_rate: f32) -> f32 {
    1.0 - (-2.0 * PI * cutoff_hz / sample_rate).exp()
}

fn soft_clip(value: f32) -> f32 {
    value.tanh()
}

fn f32_to_i16(value: f32) -> i16 {
    (value.clamp(-1.0, 1.0) * i16::MAX as f32) as i16
}

fn nonzero_seed(seed: u64) -> u64 {
    if seed == 0 {
        0x9e3779b97f4a7c15
    } else {
        seed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::telemetry::{ControlFrame, TelemetrySnapshot};

    fn test_control() -> ControlFrame {
        ControlFrame {
            snapshot: TelemetrySnapshot::default(),
            gain: 0.2,
            cutoff_hz: 1_000.0,
            air_mix: 0.02,
            width: 0.5,
            drift_hz: 0.02,
            seed_mix: 0.05,
            entropy: 0.4,
            motion: 0.3,
            brightness: 0.5,
            contrast: 0.5,
            edge_bias: 0.4,
            root_seed: 42,
            voice_weights: [0.25; 4],
            voice_cut_mul: [1.0; 4],
            voice_pan: [-0.5, -0.15, 0.15, 0.5],
            voice_seeds: [1, 2, 3, 4],
        }
    }

    #[test]
    fn extracted_features_have_expected_ranges() {
        let control = test_control();
        let mut engine = AudioEngine::new(&control);
        let chunk = engine.render_chunk(&control, CHUNK_SAMPLES);
        assert_eq!(chunk.features.len(), 8);
        assert!(chunk.features[0] >= 0.0 && chunk.features[0] <= 1.0);
        assert!(chunk.features[1] >= 0.0 && chunk.features[1] <= 1.0);
        assert!(chunk.features[2] >= 0.0 && chunk.features[2] <= 1.0);
        assert!(chunk.features[3] >= 0.0 && chunk.features[3] <= 1.0);
    }

    #[test]
    fn audio_changes_with_control() {
        let low = test_control();
        let mut high = test_control();
        high.gain = 0.28;
        high.air_mix = 0.1;
        high.root_seed = 9001;
        let mut engine = AudioEngine::new(&low);
        let low_chunk = engine.render_chunk(&low, CHUNK_SAMPLES);
        let high_chunk = engine.render_chunk(&high, CHUNK_SAMPLES);
        assert_ne!(low_chunk.features, high_chunk.features);
    }
}
