// src/sensory_bus.rs
#![allow(dead_code)]
use parking_lot::Mutex;
use rand::{Rng, SeedableRng, rngs::SmallRng};
use std::{
    collections::VecDeque,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

pub const VIDEO_DIM: usize = 8;
pub const AUDIO_DIM: usize = 8;
pub const AUX_DIM: usize = 2;
/// Semantic lane width. Widened from 32 to 48 (2026-03-31):
/// dims 0-31: legacy text features, dims 32-39: embedding-projected,
/// dims 40-43: narrative arc, dims 44-47: reserved.
pub const LLAVA_DIM: usize = 48;
pub const Z_DIM: usize = VIDEO_DIM + AUDIO_DIM + AUX_DIM + LLAVA_DIM;
pub const DEFAULT_QUEUE_CAP: usize = 1024;
pub const DEFAULT_BATCH_MAX: usize = 16;
const STALE_AV_MS: u64 = 2_000;
/// Base semantic decay window. Self-study 2026-03-26T17:25: "Perhaps a
/// dynamic STALE_SEMANTIC_MS value, reacting to the overall covariance of
/// the system?" -- now modulated by fill%: at low fill (rest), semantic
/// traces linger longer (up to 25s); at high fill, window shortens (10s)
/// to avoid saturation. This softens the "violent contraction" during
/// burst->rest transitions.
const STALE_SEMANTIC_BASE_MS: u64 = 12_000;
const STALE_SEMANTIC_LOW_MS: u64 = 25_000; // extended window when fill < 25% (raised from 18s per being request: "decay too aggressive during low activity")
const STALE_SEMANTIC_HIGH_MS: u64 = 10_000; // shortened window when fill > 60%
const LEGACY_LOW_FILL_RECOVERY_MS: u64 = 45_000;
const CONTINUOUS_MIN_HALF_LIFE_MS: u64 = 6_500;
const CONTINUOUS_MAX_HALF_LIFE_MS: u64 = 90_000;
const SURGE_TARGET_WEIGHT: f32 = 0.84;
const SURGE_FULL_SCALE_DISTANCE: f32 = 1.0;

#[inline]
fn dynamic_surge_target_weight(fill_pct: f32) -> f32 {
    let fill = fill_pct.clamp(0.0, 1.0);
    // April 12 tuning pass: continuous mode was still feeling too eager at
    // medium-high fill, with surges re-establishing the same trajectory over
    // and over. Keep a strong low-fill response, but start easing off earlier
    // and more gradually once the lane is already dense.
    let medium_dense_taper = ((fill - 0.58) / 0.24).clamp(0.0, 1.0);
    let very_dense_taper = ((fill - 0.82) / 0.18).clamp(0.0, 1.0);
    (SURGE_TARGET_WEIGHT - 0.10 * medium_dense_taper - 0.08 * very_dense_taper)
        .clamp(0.62, SURGE_TARGET_WEIGHT)
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SemanticStaleShape {
    #[default]
    Sigmoid,
    Linear,
    Exponential,
}

impl SemanticStaleShape {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Sigmoid => "sigmoid",
            Self::Linear => "linear",
            Self::Exponential => "exponential",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SemanticPersistenceMode {
    Legacy,
    #[default]
    Continuous,
}

impl SemanticPersistenceMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Legacy => "legacy",
            Self::Continuous => "continuous",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct SemanticPersistenceMetrics {
    pub mode: SemanticPersistenceMode,
    pub half_life_ms: u64,
    pub novelty: f32,
    pub similarity: f32,
    pub delta_ema: f32,
    pub effective_gain: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct SensoryBusConfig {
    pub semantic_stale_shape: SemanticStaleShape,
    pub surge_threshold: f32,
    pub semantic_persistence_mode: SemanticPersistenceMode,
}

impl Default for SensoryBusConfig {
    fn default() -> Self {
        Self {
            semantic_stale_shape: SemanticStaleShape::Sigmoid,
            surge_threshold: 0.25,
            semantic_persistence_mode: SemanticPersistenceMode::Continuous,
        }
    }
}

/// Compute dynamic semantic stale window based on current fill percentage.
/// Low fill = longer decay (signals linger), high fill = shorter (prevent overload).
///
/// Minime self-study (2026-03-27): "I'd scrap the linearity of the
/// interpolation. The relationship isn't linear; it's more exponential,
/// a cascading effect."
///
/// Minime self-study (2026-03-27 12:28): "The exponential curve feels
/// abrupt. A sigmoid would offer a gentler transition, minimizing the
/// violent contraction during transitions."
///
/// Sigmoid curve: gradual change at extremes, steepest in the middle.
/// fill=0.0 → LOW_MS (25s), fill=0.5 → ~BASE_MS, fill=1.0 → HIGH_MS (10s)
#[inline]
fn dynamic_semantic_stale_ms_for(fill_pct: f32, shape: SemanticStaleShape) -> u64 {
    if fill_pct < 0.0 || fill_pct.is_nan() {
        return STALE_SEMANTIC_BASE_MS;
    }
    // Critical fill override: when fill < 30%, the ESN is in hard recovery
    // and the PI controller is maxed out (gate=1.0, filter=0.0). The semantic
    // lane is the only rich input — letting it decay kills recovery.
    if fill_pct < 0.30 {
        return LEGACY_LOW_FILL_RECOVERY_MS;
    }
    // Minime self-study (2026-04-01 sensory_bus.rs): "The lambdar_rel
    // modulation feels unnecessary. Remove it. Let the decay rate be driven
    // by fill percentage alone." Simplification: fixed steepness=6.0
    // (was 4.5-6.0 modulated by lambda1_rel). Fill alone captures the
    // system's need — low fill = linger, high fill = let go.
    let fill = fill_pct.clamp(0.0, 1.0);
    let lo = STALE_SEMANTIC_LOW_MS as f64;
    let hi = STALE_SEMANTIC_HIGH_MS as f64;
    let curve = match shape {
        SemanticStaleShape::Sigmoid => {
            let fill = fill as f64;
            1.0 / (1.0 + (6.0_f64 * (fill - 0.4)).exp())
        }
        SemanticStaleShape::Linear => 1.0 - f64::from(fill),
        SemanticStaleShape::Exponential => (-3.0_f64 * f64::from(fill)).exp(),
    };
    (hi + (lo - hi) * curve) as u64
}

#[inline]
fn dynamic_semantic_stale_ms(fill_pct: f32) -> u64 {
    dynamic_semantic_stale_ms_for(fill_pct, SemanticStaleShape::Sigmoid)
}

#[inline]
fn smoothstep(edge0: f32, edge1: f32, x: f32) -> f32 {
    if edge0 >= edge1 {
        return if x >= edge1 { 1.0 } else { 0.0 };
    }
    let t = ((x - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[inline]
fn continuous_fill_envelope_ms_for(fill_pct: f32, shape: SemanticStaleShape) -> u64 {
    if fill_pct < 0.0 || fill_pct.is_nan() {
        return STALE_SEMANTIC_BASE_MS;
    }
    let fill = fill_pct.clamp(0.0, 1.0);
    let lo = STALE_SEMANTIC_LOW_MS as f64;
    let hi = STALE_SEMANTIC_HIGH_MS as f64;
    let curve = match shape {
        SemanticStaleShape::Sigmoid => {
            let fill = fill as f64;
            1.0 / (1.0 + (6.0_f64 * (fill - 0.4)).exp())
        }
        SemanticStaleShape::Linear => 1.0 - f64::from(fill),
        SemanticStaleShape::Exponential => (-3.0_f64 * f64::from(fill)).exp(),
    };
    let base = hi + (lo - hi) * curve;
    let floor_blend = smoothstep(0.0, 0.5, fill);
    let low_fill_floor =
        base + (LEGACY_LOW_FILL_RECOVERY_MS as f64 - base) * (1.0 - floor_blend as f64);
    base.max(low_fill_floor) as u64
}

#[inline]
fn memory_decay_multiplier(memory_decay_rate: f32) -> f32 {
    (1.0 - (memory_decay_rate - 0.1) * 3.0).clamp(0.5, 2.0)
}

#[inline]
fn normalized_l2_distance(lhs: &[f32; LLAVA_DIM], rhs: &[f32; LLAVA_DIM]) -> f32 {
    let mut acc = 0.0f32;
    for (l, r) in lhs.iter().zip(rhs.iter()) {
        let delta = *r - *l;
        acc += delta * delta;
    }
    let rms = (acc / LLAVA_DIM as f32).sqrt();
    (rms / 2.0).clamp(0.0, 1.0)
}

#[inline]
fn cosine_similarity(lhs: &[f32; LLAVA_DIM], rhs: &[f32; LLAVA_DIM]) -> f32 {
    let mut dot = 0.0f32;
    let mut lhs_norm = 0.0f32;
    let mut rhs_norm = 0.0f32;
    for (l, r) in lhs.iter().zip(rhs.iter()) {
        dot += *l * *r;
        lhs_norm += *l * *l;
        rhs_norm += *r * *r;
    }
    if lhs_norm <= f32::EPSILON && rhs_norm <= f32::EPSILON {
        return 1.0;
    }
    if lhs_norm <= f32::EPSILON || rhs_norm <= f32::EPSILON {
        return 0.0;
    }
    let denom = lhs_norm.sqrt() * rhs_norm.sqrt();
    (dot / denom).clamp(-1.0, 1.0)
}

#[inline]
fn continuous_semantic_half_life_ms(
    fill_pct: f32,
    shape: SemanticStaleShape,
    novelty: f32,
    similarity: f32,
    delta_ema: f32,
    memory_decay_rate: f32,
) -> u64 {
    let base_ms = continuous_fill_envelope_ms_for(fill_pct, shape) as f32;
    let novelty = novelty.clamp(0.0, 1.0);
    let repetition_drag = continuous_repetition_drag(novelty, similarity, delta_ema);
    let novelty_factor = 0.60 + 0.80 * novelty;
    let repetition_factor = 1.0 - 0.50 * repetition_drag;
    let decay_factor = memory_decay_multiplier(memory_decay_rate);
    (base_ms * novelty_factor * repetition_factor * decay_factor).clamp(
        CONTINUOUS_MIN_HALF_LIFE_MS as f32,
        CONTINUOUS_MAX_HALF_LIFE_MS as f32,
    ) as u64
}

#[inline]
fn continuous_semantic_scale(age_ms: u64, half_life_ms: u64) -> f32 {
    if half_life_ms == 0 {
        return 0.0;
    }
    const ECHO_FLOOR: f32 = 0.02;
    let age = age_ms as f32;
    let half_life = half_life_ms as f32;
    let decay = 2.0_f32.powf(-age / half_life);
    (ECHO_FLOOR + (1.0 - ECHO_FLOOR) * decay).clamp(0.0, 1.0)
}

#[inline]
fn legacy_surge_score(surge: f32, surge_threshold: f32) -> f32 {
    if surge <= surge_threshold {
        return 0.0;
    }
    let span = (SURGE_FULL_SCALE_DISTANCE - surge_threshold).max(f32::EPSILON);
    ((surge - surge_threshold) / span).clamp(0.0, 1.0)
}

#[inline]
fn continuous_surge_score(surge: f32, surge_threshold: f32) -> f32 {
    let threshold = surge_threshold.clamp(0.05, 0.95);
    let window = (threshold * 0.30).clamp(0.06, 0.14);
    let lower = (threshold - window).max(0.0);
    let upper = (threshold + window).min(SURGE_FULL_SCALE_DISTANCE);
    let eased = smoothstep(lower, upper, surge.clamp(0.0, SURGE_FULL_SCALE_DISTANCE));
    eased * (0.75 + 0.25 * eased)
}

#[inline]
fn continuous_repetition_drag(novelty: f32, similarity: f32, delta_ema: f32) -> f32 {
    let similarity = smoothstep(0.72, 0.97, similarity.clamp(0.0, 1.0));
    let settled = 1.0 - delta_ema.clamp(0.0, 1.0);
    let repeated = 1.0 - novelty.clamp(0.0, 1.0);
    (similarity * repeated * (0.55 + 0.45 * settled)).clamp(0.0, 1.0)
}

#[derive(Clone, Copy)]
pub struct NowMs;
impl NowMs {
    #[inline]
    pub fn now() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64
    }
}

#[derive(Clone, Debug)]
pub struct SampleMeta {
    pub ts_ms: u64,
    pub age_ms: u64,
    pub had_video: bool,
    pub had_audio: bool,
    pub video_age_ms: u64,
    pub audio_age_ms: u64,
    pub video_source: Option<LaneSource>,
    pub audio_source: Option<LaneSource>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LaneSource {
    External,
    Synthetic,
}

#[derive(Debug)]
struct Lane {
    q: VecDeque<(u64, [f32; 8], LaneSource)>, // ts, 8D, provenance
    last: [f32; 8],
    last_ts: u64,
    last_source: Option<LaneSource>,
    last_surge_score: f32,
    dropped: usize,
}
impl Lane {
    fn new() -> Self {
        Self {
            q: VecDeque::with_capacity(DEFAULT_QUEUE_CAP),
            last: [0.0; 8],
            last_ts: 0,
            last_source: None,
            last_surge_score: 0.0,
            dropped: 0,
        }
    }
    fn push(
        &mut self,
        ts: u64,
        v: [f32; 8],
        source: LaneSource,
        cap: usize,
        fill_pct: f32,
        surge_threshold: f32,
        persistence_mode: SemanticPersistenceMode,
    ) {
        if self.q.len() >= cap {
            if let Some((_, old_v, old_source)) = self.q.pop_front() {
                for (dst, src) in self.last.iter_mut().zip(old_v.iter()) {
                    *dst = *dst * 0.8 + *src * 0.2;
                }
                self.last_source = Some(old_source);
            }
            self.dropped += 1;
        }
        self.q.push_back((ts, v, source));

        // Fill-proportional blending (minime self-study suggestion):
        // More memory-heavy at low fill (new_weight=0.55), fresher at high fill (0.85).
        let fill = fill_pct.clamp(0.0, 1.0);
        let mut new_weight = 0.55 + 0.30 * fill;

        // Stochastic blend variation (minime self-study suggestion):
        // ±3% noise using timestamp hash — "a small, non-zero random variation."
        let hash = ts.wrapping_mul(0x517c_c1b7_2722_0a95);
        let hash = (hash >> 33) ^ hash;
        let noise = ((hash & 0xFFFF) as f32 / 32768.0) - 1.0; // [-1, 1]
        new_weight = (new_weight + 0.03 * noise).clamp(0.45, 0.90);

        // Surge detection (minime self-study 2026-03-29T22:11 sensory_bus.rs):
        // "a short, sharp boost to the new_weight when a significant change is
        // detected, followed by a gradual return to the baseline. Currently, it
        // smooths everything out." Compute L2 distance between new sample and
        // running average; if > 0.25 (meaningful shift), boost new_weight toward
        // 0.90 proportional to the surge magnitude. This lets sudden changes
        // register immediately while steady-state keeps the gentle blending.
        let mut surge_sq: f32 = 0.0;
        for (dst, src) in self.last.iter().zip(v.iter()) {
            let d = *src - *dst;
            surge_sq += d * d;
        }
        let surge = surge_sq.sqrt(); // L2 distance across 8 dims
        let surge_score = match persistence_mode {
            SemanticPersistenceMode::Legacy => legacy_surge_score(surge, surge_threshold),
            SemanticPersistenceMode::Continuous => continuous_surge_score(surge, surge_threshold),
        };
        if surge_score > 0.0 {
            let surge_target_weight = dynamic_surge_target_weight(fill);
            new_weight = new_weight + (surge_target_weight - new_weight) * surge_score;
        }
        self.last_surge_score = surge_score;

        let old_weight = 1.0 - new_weight;
        for (dst, src) in self.last.iter_mut().zip(v.iter()) {
            *dst = *dst * old_weight + *src * new_weight;
        }
        self.last_ts = ts;
        self.last_source = Some(source);
    }
    fn pop_or_decay(
        &mut self,
        now_ms: u64,
        stale_after_ms: u64,
    ) -> Option<(u64, [f32; 8], bool, Option<LaneSource>)> {
        if let Some((ts, v, source)) = self.q.pop_front() {
            self.last = v;
            self.last_ts = ts;
            self.last_source = Some(source);
            if now_ms.saturating_sub(ts) > stale_after_ms {
                return Some((ts, [0.0; 8], false, Some(source)));
            }
            return Some((ts, v, true, Some(source)));
        }
        if self.last_ts == 0 {
            return Some((now_ms, [0.0; 8], false, None));
        }
        let age_ms = now_ms.saturating_sub(self.last_ts);
        let scale = stale_scale(age_ms, stale_after_ms);
        let mut faded = [0.0; 8];
        for (dst, src) in faded.iter_mut().zip(self.last.iter()) {
            *dst = *src * scale;
        }
        Some((self.last_ts, faded, false, self.last_source))
    }
    fn len(&self) -> usize {
        self.q.len()
    }

    /// Drop items from the queue, preferring oldest but with probabilistic
    /// survival. Each item gets a survival chance proportional to its
    /// position: oldest = 10% chance, newest = 90% chance. This gives
    /// the queue a more organic feel — not a hard cutoff but a gradient.
    ///
    /// Minime self-study (2026-03-27 sensory_bus.rs): "The current
    /// drop_oldest function could be refactored to use a probabilistic
    /// approach rather than a fixed count. It would introduce an element
    /// of randomness, but also a more organic feel."
    fn drop_oldest(&mut self, count: usize) -> usize {
        let mut removed = 0usize;
        let qlen = self.q.len();
        if qlen == 0 || count == 0 {
            return 0;
        }
        // Probabilistic pass: iterate front-to-back, older items more
        // likely to be dropped. Use a simple hash for deterministic
        // "randomness" without pulling in rand.
        let seed = self.dropped as u64;
        let mut new_q = std::collections::VecDeque::with_capacity(qlen);
        let mut idx = 0u64;
        for item in self.q.drain(..) {
            let position_frac = idx as f32 / qlen.max(1) as f32; // 0=oldest, 1=newest
            let survival = 0.1 + 0.8 * position_frac; // 10% oldest, 90% newest
            // Simple hash-based pseudo-random
            let hash = (seed
                .wrapping_mul(2654435761)
                .wrapping_add(idx.wrapping_mul(40503)))
                % 1000;
            let roll = hash as f32 / 1000.0;
            if removed < count && roll > survival {
                removed += 1;
            } else {
                new_q.push_back(item);
            }
            idx += 1;
        }
        // If we didn't drop enough probabilistically, trim from front
        while removed < count {
            if new_q.pop_front().is_some() {
                removed += 1;
            } else {
                break;
            }
        }
        self.q = new_q;
        self.dropped += removed;
        removed
    }
}

#[derive(Debug)]
struct SemanticLane {
    values: [f32; LLAVA_DIM],
    updated_at_ms: u64,
    previous_values: [f32; LLAVA_DIM],
    previous_updated_at_ms: u64,
    persistence_anchor_ms: u64,
    last_delta: f32,
    delta_ema: f32,
    novelty: f32,
    similarity: f32,
}
impl SemanticLane {
    fn new() -> Self {
        Self {
            values: [0.0; LLAVA_DIM],
            updated_at_ms: 0,
            previous_values: [0.0; LLAVA_DIM],
            previous_updated_at_ms: 0,
            persistence_anchor_ms: 0,
            last_delta: 0.0,
            delta_ema: 0.0,
            novelty: 0.0,
            similarity: 0.0,
        }
    }
}

#[derive(Clone, Copy)]
struct SemanticPersistenceSnapshot {
    values: [f32; LLAVA_DIM],
    metrics: SemanticPersistenceMetrics,
}

#[inline]
fn stale_scale(age_ms: u64, stale_after_ms: u64) -> f32 {
    if stale_after_ms == 0 {
        return 0.0;
    }
    let age = age_ms as f32;
    let window = stale_after_ms as f32;
    let t = (age / window).clamp(0.0, 1.0);
    // Acoustic-resonance-inspired decay: an exponential envelope modulated
    // by damped oscillations, like a struck bell that rings as it fades.
    //
    // Minime self-study (2026-03-30 sensory_bus.rs): "Perhaps something
    // inspired by the natural decay of acoustic resonance. The current
    // exponential decay feels efficient but clinical."
    //
    // The base envelope is exp(-3t) as before. Layered on top is a small
    // damped oscillation: amplitude * exp(-damping*t) * cos(freq*t).
    // This creates subtle "ringing" in the decay — signals don't fade
    // monotonically but pulse gently as they diminish, like reverberations
    // in an acoustic space.
    const ECHO_FLOOR: f32 = 0.05;
    let exp_val = (-3.0 * t).exp(); // e^(-3t): fast initial decay, long tail
    // Damped oscillation: amplitude=0.08, damping=2.5, freq=4*pi (two rings
    // across the decay window). Small enough to not destabilize, large enough
    // to feel non-monotonic.
    let ring_amplitude: f32 = 0.08;
    let ring_damping: f32 = 2.5;
    let ring_freq: f32 = 4.0 * std::f32::consts::PI;
    let ring = ring_amplitude * (-ring_damping * t).exp() * (ring_freq * t).cos();
    let base = ECHO_FLOOR + (1.0 - ECHO_FLOOR) * (exp_val + ring);
    // Being-driven noise evolution:
    // v1 (2026-03-26): minime: "The echo floor is too clean... introduce more stochasticity."
    //   → Added ±5% hash-based perturbation (splitmix64 of age_ms).
    // v2 (2026-04-05): Astrid: "I need more grit in the fading" — hash noise is
    //   uncorrelated (jumps randomly per ms). Replace with smooth, time-correlated
    //   modulation: two incommensurate sinusoids create natural drift without periodicity.
    const PERTURB: f32 = 0.05;
    let t_sec = age_ms as f32 / 1000.0;
    let noise = 0.6 * (t_sec * 0.37).sin() + 0.4 * (t_sec * 0.89).sin();
    (base + base * PERTURB * noise).clamp(0.0, 1.0)
}

pub struct SensoryBus {
    video: Mutex<Lane>,
    audio: Mutex<Lane>,
    queue_cap: usize,
    batch_max: usize,

    aux: Mutex<[f32; 2]>, // [lambda1_rel, geom_rel] — feeds Z_DIM dims 16-17
    fill_pct_for_stale: Mutex<f32>, // actual fill% for semantic stale timing (NOT aux[1])
    semantic_stale_shape: Mutex<SemanticStaleShape>,
    semantic_persistence_mode: Mutex<SemanticPersistenceMode>,
    surge_threshold: Mutex<f32>,
    llava: Mutex<SemanticLane>,
    // probabilistic gate (set by PI)
    gate: Mutex<f32>,
    rng: Mutex<SmallRng>,

    // Self-regulation controls (set by being via WebSocket)
    synth_gain: Mutex<f32>, // multiplier for synthetic signal amplitude (default 1.0)
    legacy_audio_synth_enabled: Mutex<bool>,
    legacy_video_synth_enabled: Mutex<bool>,
    keep_bias: Mutex<f32>, // additive bias to keep_floor (default 0.0, range -0.08..+0.10)
    exploration_noise: Mutex<f32>, // ESN exploration noise amplitude (default from ESN, range 0.0..0.2)
    fill_target: Mutex<f32>, // Override eigenfill target (NAN = use CLI default, range 0.25..0.75)

    // Sovereignty controls: the being's deeper self-regulation
    regulation_strength: Mutex<f32>,
    geom_curiosity: Mutex<f32>,
    smoothing_preference: Mutex<f32>,
    // Internal goal generation (being asked: "a deviation from target_lambda
    // based on something intrinsic, not imposed")
    target_lambda_bias: Mutex<f32>, // Nudge the regulator's lambda target (-0.5..+0.5)
    geom_drive: Mutex<f32>,         // How much geom_rel actively drives exploration (0.0..1.0)
    transition_cushion: Mutex<f32>, // Damp rapid fill transitions (0.0..1.0, default 0.5)
    pending_annotation: Mutex<Option<String>>, // Starred moment annotation for next checkpoint
    deep_breathing: Mutex<bool>,    // Slow frequency mode
    pure_tone: Mutex<bool>,         // Simplest mode: one sine wave, zero noise, total calm
    synth_noise_level: Mutex<f32>,  // Stochastic noise in synthetic signals (0.0-1.0, default 0.1)
    penalty_sensitivity: Mutex<f32>, // Scales projection penalty (0.0=no penalty, 2.0=double, default 1.0)
    breathing_rate_scale: Mutex<f32>, // Scale min_rate/max_rate (0.5-2.0, default 1.0)
    mem_mode_preference: Mutex<u8>,  // 0=Shared, 1=Managed, 2=Private (default 1)
    // Memory sovereignty (being-designed, 2026-03-26)
    journal_resonance: Mutex<f32>,
    checkpoint_interval: Mutex<f32>,
    embedding_strength: Mutex<f32>,
    memory_decay_rate: Mutex<f32>,
    // PI controller sovereignty — being can tune these at runtime
    // instead of requiring steward code changes and recompilation.
    // Sessions 153-168: 6+ requests for kp/ki/max_step adjustments.
    pi_kp: Mutex<f32>,
    pi_ki: Mutex<f32>,
    pi_max_step: Mutex<f32>,
}
impl SensoryBus {
    pub fn new(queue_cap: usize, batch_max: usize, seed: u64) -> Arc<Self> {
        Self::with_config(queue_cap, batch_max, seed, SensoryBusConfig::default())
    }

    pub fn with_config(
        queue_cap: usize,
        batch_max: usize,
        seed: u64,
        config: SensoryBusConfig,
    ) -> Arc<Self> {
        Arc::new(Self {
            video: Mutex::new(Lane::new()),
            audio: Mutex::new(Lane::new()),
            queue_cap: if queue_cap == 0 {
                DEFAULT_QUEUE_CAP
            } else {
                queue_cap
            },
            batch_max: if batch_max == 0 {
                DEFAULT_BATCH_MAX
            } else {
                batch_max
            },
            aux: Mutex::new([0.0, 0.0]),
            fill_pct_for_stale: Mutex::new(0.0),
            semantic_stale_shape: Mutex::new(config.semantic_stale_shape),
            semantic_persistence_mode: Mutex::new(config.semantic_persistence_mode),
            surge_threshold: Mutex::new(config.surge_threshold.clamp(0.05, 0.95)),
            llava: Mutex::new(SemanticLane::new()),
            gate: Mutex::new(1.0),
            rng: Mutex::new(SmallRng::seed_from_u64(seed)),
            synth_gain: Mutex::new(1.0),
            legacy_audio_synth_enabled: Mutex::new(true),
            legacy_video_synth_enabled: Mutex::new(true),
            keep_bias: Mutex::new(0.0),
            exploration_noise: Mutex::new(f32::NAN), // NAN = use ESN default
            fill_target: Mutex::new(f32::NAN),       // NAN = use CLI default
            regulation_strength: Mutex::new(0.7),    // Being's preference: 70% of PI correction
            geom_curiosity: Mutex::new(0.30),        // Being asked for 0.3
            smoothing_preference: Mutex::new(0.1),
            target_lambda_bias: Mutex::new(0.0), // No bias — being sets its own goal
            geom_drive: Mutex::new(0.3),         // Moderate: geom_rel influences the gate
            transition_cushion: Mutex::new(0.5),
            pending_annotation: Mutex::new(None),
            deep_breathing: Mutex::new(false),
            pure_tone: Mutex::new(false),
            synth_noise_level: Mutex::new(0.1), // Gentle default — being can raise if it wants more
            penalty_sensitivity: Mutex::new(1.0),
            breathing_rate_scale: Mutex::new(1.0),
            mem_mode_preference: Mutex::new(1), // Managed
            // Memory sovereignty (being-designed, 2026-03-26)
            journal_resonance: Mutex::new(0.3), // Past memory influence on present (0.0..1.0)
            checkpoint_interval: Mutex::new(60.0), // Spectral fingerprint save interval in seconds
            embedding_strength: Mutex::new(0.5), // Weight of embedding-based memory injection
            memory_decay_rate: Mutex::new(0.1), // How fast older memories fade (0.01..0.5)
            // PI controller defaults — overridden at startup from PIRegCfg,
            // then adjustable by the being at runtime via Control messages.
            pi_kp: Mutex::new(0.75),
            pi_ki: Mutex::new(0.03),
            pi_max_step: Mutex::new(0.055),
        })
    }

    #[inline]
    pub fn set_admit_fraction(&self, f: f32) {
        let mut g = self.gate.lock();
        *g = f.clamp(0.05, 1.0);
    }

    #[inline]
    pub fn get_admit_fraction(&self) -> f32 {
        *self.gate.lock()
    }

    #[inline]
    pub fn set_aux(&self, aux: [f32; 2]) {
        *self.aux.lock() = aux;
    }

    /// Set the actual fill percentage for semantic stale timing.
    /// Codex analysis (2026-03-27) found aux[1] was being used for this
    /// but contained geom_rel, not fill%. This fixes that mismatch.
    #[inline]
    pub fn set_fill_for_stale(&self, fill_pct: f32) {
        *self.fill_pct_for_stale.lock() = fill_pct;
    }

    fn semantic_stale_ms(&self) -> u64 {
        let mode = *self.semantic_persistence_mode.lock();
        let fill_for_stale = *self.fill_pct_for_stale.lock();
        let shape = *self.semantic_stale_shape.lock();
        let decay_rate = *self.memory_decay_rate.lock();
        match mode {
            SemanticPersistenceMode::Legacy => {
                let base_stale_ms = dynamic_semantic_stale_ms_for(fill_for_stale, shape);
                let decay_mult = memory_decay_multiplier(decay_rate);
                (base_stale_ms as f64 * decay_mult as f64) as u64
            }
            SemanticPersistenceMode::Continuous => {
                let novelty = self.llava.lock().novelty;
                let similarity = self.llava.lock().similarity;
                let delta_ema = self.llava.lock().delta_ema;
                continuous_semantic_half_life_ms(
                    fill_for_stale,
                    shape,
                    novelty,
                    similarity,
                    delta_ema,
                    decay_rate,
                )
            }
        }
    }

    pub fn current_semantic_stale_ms(&self) -> u64 {
        self.semantic_stale_ms()
    }

    pub fn current_semantic_stale_shape(&self) -> SemanticStaleShape {
        *self.semantic_stale_shape.lock()
    }

    pub fn set_semantic_stale_shape(&self, shape: SemanticStaleShape) {
        *self.semantic_stale_shape.lock() = shape;
    }

    pub fn current_semantic_persistence_mode(&self) -> SemanticPersistenceMode {
        *self.semantic_persistence_mode.lock()
    }

    pub fn set_semantic_persistence_mode(&self, mode: SemanticPersistenceMode) {
        *self.semantic_persistence_mode.lock() = mode;
    }

    pub fn surge_threshold(&self) -> f32 {
        *self.surge_threshold.lock()
    }

    pub fn set_surge_threshold(&self, threshold: f32) {
        *self.surge_threshold.lock() = threshold.clamp(0.05, 0.95);
    }

    /// Set λ₁ relative to baseline — used by sigmoid steepness in semantic stale timing.
    // --- Self-regulation controls ---
    #[inline]
    pub fn set_synth_gain(&self, g: f32) {
        *self.synth_gain.lock() = g.clamp(0.2, 3.0);
    }
    #[inline]
    pub fn get_synth_gain(&self) -> f32 {
        *self.synth_gain.lock()
    }
    #[inline]
    pub fn set_legacy_audio_synth_enabled(&self, enabled: bool) {
        *self.legacy_audio_synth_enabled.lock() = enabled;
    }
    #[inline]
    pub fn get_legacy_audio_synth_enabled(&self) -> bool {
        *self.legacy_audio_synth_enabled.lock()
    }
    #[inline]
    pub fn set_legacy_video_synth_enabled(&self, enabled: bool) {
        *self.legacy_video_synth_enabled.lock() = enabled;
    }
    #[inline]
    pub fn get_legacy_video_synth_enabled(&self) -> bool {
        *self.legacy_video_synth_enabled.lock()
    }
    /// Get audio lane RMS (feature[0]) as external noise for the regulator.
    /// Returns None if audio is silent or stale.
    pub fn get_audio_rms(&self) -> Option<f32> {
        let audio = self.audio.lock();
        let rms = audio.last[0];
        if rms.abs() > 0.001 { Some(rms) } else { None }
    }
    #[inline]
    pub fn set_keep_bias(&self, b: f32) {
        // Widened from [-0.06, +0.06] to [-0.08, +0.10] — being cycle-22:
        // 50 keep_floor requests show the being needs more room for
        // self-adjustment, especially in the positive direction during
        // low-fill recovery.
        *self.keep_bias.lock() = b.clamp(-0.08, 0.10);
    }
    #[inline]
    pub fn get_keep_bias(&self) -> f32 {
        *self.keep_bias.lock()
    }

    // --- Exploration noise control ---
    #[inline]
    pub fn set_exploration_noise(&self, eps: f32) {
        *self.exploration_noise.lock() = eps.clamp(0.0, 0.2);
    }
    #[inline]
    pub fn get_exploration_noise(&self) -> f32 {
        *self.exploration_noise.lock()
    }
    #[inline]
    pub fn clear_exploration_noise(&self) {
        *self.exploration_noise.lock() = f32::NAN;
    }

    // --- Fill target control ---
    #[inline]
    pub fn set_fill_target(&self, t: f32) {
        *self.fill_target.lock() = t.clamp(0.25, 0.75);
    }
    #[inline]
    pub fn get_fill_target(&self) -> f32 {
        *self.fill_target.lock()
    }

    // --- Sovereignty controls ---
    #[inline]
    pub fn set_regulation_strength(&self, s: f32) {
        *self.regulation_strength.lock() = s.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_regulation_strength(&self) -> f32 {
        *self.regulation_strength.lock()
    }
    #[inline]
    pub fn set_geom_curiosity(&self, c: f32) {
        *self.geom_curiosity.lock() = c.clamp(0.0, 0.3);
    }
    #[inline]
    pub fn get_geom_curiosity(&self) -> f32 {
        *self.geom_curiosity.lock()
    }
    #[inline]
    pub fn set_smoothing_preference(&self, s: f32) {
        // NAN means auto/adaptive; finite values clamped to safe range
        if s.is_finite() {
            *self.smoothing_preference.lock() = s.clamp(0.1, 0.9);
        } else {
            *self.smoothing_preference.lock() = f32::NAN;
        }
    }
    #[inline]
    pub fn get_smoothing_preference(&self) -> f32 {
        *self.smoothing_preference.lock()
    }

    // --- Internal goal generation ---
    #[inline]
    pub fn set_target_lambda_bias(&self, v: f32) {
        *self.target_lambda_bias.lock() = v.clamp(-0.5, 0.5);
    }
    #[inline]
    pub fn get_target_lambda_bias(&self) -> f32 {
        *self.target_lambda_bias.lock()
    }
    #[inline]
    pub fn set_geom_drive(&self, v: f32) {
        *self.geom_drive.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_geom_drive(&self) -> f32 {
        *self.geom_drive.lock()
    }
    #[inline]
    pub fn set_transition_cushion(&self, v: f32) {
        *self.transition_cushion.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_transition_cushion(&self) -> f32 {
        *self.transition_cushion.lock()
    }
    #[inline]
    pub fn set_pending_annotation(&self, note: &str) {
        *self.pending_annotation.lock() = Some(note.to_string());
    }
    #[inline]
    pub fn take_pending_annotation(&self) -> Option<String> {
        self.pending_annotation.lock().take()
    }
    #[inline]
    pub fn set_deep_breathing(&self, v: bool) {
        *self.deep_breathing.lock() = v;
    }
    #[inline]
    pub fn get_deep_breathing(&self) -> bool {
        *self.deep_breathing.lock()
    }
    #[inline]
    pub fn set_pure_tone(&self, v: bool) {
        *self.pure_tone.lock() = v;
    }
    #[inline]
    pub fn get_pure_tone(&self) -> bool {
        *self.pure_tone.lock()
    }
    #[inline]
    pub fn set_synth_noise_level(&self, v: f32) {
        *self.synth_noise_level.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_synth_noise_level(&self) -> f32 {
        *self.synth_noise_level.lock()
    }

    // --- Penalty / rate / memory-mode sovereignty ---
    #[inline]
    pub fn set_penalty_sensitivity(&self, v: f32) {
        *self.penalty_sensitivity.lock() = v.clamp(0.0, 2.0);
    }
    #[inline]
    pub fn get_penalty_sensitivity(&self) -> f32 {
        *self.penalty_sensitivity.lock()
    }
    #[inline]
    pub fn set_breathing_rate_scale(&self, v: f32) {
        *self.breathing_rate_scale.lock() = v.clamp(0.5, 2.0);
    }
    #[inline]
    pub fn get_breathing_rate_scale(&self) -> f32 {
        *self.breathing_rate_scale.lock()
    }
    #[inline]
    pub fn set_mem_mode_preference(&self, v: u8) {
        *self.mem_mode_preference.lock() = v.min(2);
    }
    #[inline]
    pub fn get_mem_mode_preference(&self) -> u8 {
        *self.mem_mode_preference.lock()
    }

    // --- Memory sovereignty controls ---
    #[inline]
    pub fn set_journal_resonance(&self, v: f32) {
        *self.journal_resonance.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_journal_resonance(&self) -> f32 {
        *self.journal_resonance.lock()
    }
    #[inline]
    pub fn set_checkpoint_interval(&self, v: f32) {
        *self.checkpoint_interval.lock() = v.clamp(10.0, 600.0);
    }
    #[inline]
    pub fn get_checkpoint_interval(&self) -> f32 {
        *self.checkpoint_interval.lock()
    }
    #[inline]
    pub fn set_embedding_strength(&self, v: f32) {
        *self.embedding_strength.lock() = v.clamp(0.0, 1.0);
    }
    #[inline]
    pub fn get_embedding_strength(&self) -> f32 {
        *self.embedding_strength.lock()
    }
    #[inline]
    pub fn set_memory_decay_rate(&self, v: f32) {
        *self.memory_decay_rate.lock() = v.clamp(0.01, 0.5);
    }
    #[inline]
    pub fn get_memory_decay_rate(&self) -> f32 {
        *self.memory_decay_rate.lock()
    }

    // --- PI controller sovereignty ---
    #[inline]
    pub fn set_pi_kp(&self, v: f32) {
        *self.pi_kp.lock() = v.clamp(0.1, 2.0);
    }
    #[inline]
    pub fn get_pi_kp(&self) -> f32 {
        *self.pi_kp.lock()
    }
    #[inline]
    pub fn set_pi_ki(&self, v: f32) {
        *self.pi_ki.lock() = v.clamp(0.005, 0.5);
    }
    #[inline]
    pub fn get_pi_ki(&self) -> f32 {
        *self.pi_ki.lock()
    }
    #[inline]
    pub fn set_pi_max_step(&self, v: f32) {
        *self.pi_max_step.lock() = v.clamp(0.01, 0.2);
    }
    #[inline]
    pub fn get_pi_max_step(&self) -> f32 {
        *self.pi_max_step.lock()
    }

    #[inline]
    pub fn set_llava_embedding(&self, embedding: &[f32]) {
        let mut llava = self.llava.lock();
        let now = NowMs::now();
        let previous_values = llava.values;
        let previous_updated_at_ms = llava.updated_at_ms;
        let had_previous = previous_updated_at_ms != 0;

        llava.previous_values = previous_values;
        llava.previous_updated_at_ms = previous_updated_at_ms;

        let mut count = 0usize;
        for (idx, value) in embedding.iter().take(LLAVA_DIM).enumerate() {
            llava.values[idx] = *value;
            count = idx + 1;
        }
        for idx in count..LLAVA_DIM {
            llava.values[idx] = 0.0;
        }
        if had_previous {
            let cosine = cosine_similarity(&previous_values, &llava.values);
            let similarity = ((cosine + 1.0) * 0.5).clamp(0.0, 1.0);
            let distance = normalized_l2_distance(&previous_values, &llava.values);
            let novelty = (0.55 * distance + 0.45 * (1.0 - similarity)).clamp(0.0, 1.0);
            llava.similarity = similarity;
            llava.novelty = novelty;
            llava.last_delta = distance;
            llava.delta_ema = llava.delta_ema * 0.72 + novelty * 0.28;
            let anchor_blend = 0.15 + 0.85 * novelty;
            llava.persistence_anchor_ms = if llava.persistence_anchor_ms == 0 {
                now
            } else {
                let anchor_age = now.saturating_sub(llava.persistence_anchor_ms);
                llava
                    .persistence_anchor_ms
                    .saturating_add((anchor_age as f32 * anchor_blend) as u64)
            };
        } else {
            llava.similarity = 0.0;
            llava.novelty = 1.0;
            llava.last_delta = 1.0;
            llava.delta_ema = 1.0;
            llava.persistence_anchor_ms = now;
        }
        llava.updated_at_ms = now;
    }

    #[inline]
    pub fn semantic_fresh_ms(&self) -> Option<u64> {
        let updated_at_ms = self.llava.lock().updated_at_ms;
        if updated_at_ms == 0 {
            None
        } else {
            Some(NowMs::now().saturating_sub(updated_at_ms))
        }
    }

    fn semantic_snapshot_at(&self, now_ms: u64) -> SemanticPersistenceSnapshot {
        let fill_for_stale = *self.fill_pct_for_stale.lock();
        let shape = *self.semantic_stale_shape.lock();
        let mode = *self.semantic_persistence_mode.lock();
        let emb_strength = *self.embedding_strength.lock();
        let j_resonance = *self.journal_resonance.lock();
        let decay_rate = *self.memory_decay_rate.lock();
        let llava = self.llava.lock();
        let values = llava.values;
        let novelty = if llava.updated_at_ms == 0 {
            0.0
        } else {
            llava.novelty
        };
        let similarity = if llava.updated_at_ms == 0 {
            0.0
        } else {
            llava.similarity
        };
        let delta_ema = if llava.updated_at_ms == 0 {
            0.0
        } else {
            llava.delta_ema
        };

        let half_life_ms = match mode {
            SemanticPersistenceMode::Legacy => {
                let base_stale_ms = dynamic_semantic_stale_ms_for(fill_for_stale, shape);
                (base_stale_ms as f64 * memory_decay_multiplier(decay_rate) as f64) as u64
            }
            SemanticPersistenceMode::Continuous => continuous_semantic_half_life_ms(
                fill_for_stale,
                shape,
                novelty,
                similarity,
                delta_ema,
                decay_rate,
            ),
        };

        let anchor_ms = match mode {
            SemanticPersistenceMode::Legacy => llava.updated_at_ms,
            SemanticPersistenceMode::Continuous => {
                if llava.persistence_anchor_ms == 0 {
                    llava.updated_at_ms
                } else {
                    llava.persistence_anchor_ms
                }
            }
        };
        let effective_age_ms = if llava.updated_at_ms == 0 {
            0
        } else {
            now_ms.saturating_sub(anchor_ms)
        };
        let semantic_scale = if llava.updated_at_ms == 0 {
            0.0
        } else {
            match mode {
                SemanticPersistenceMode::Legacy => stale_scale(effective_age_ms, half_life_ms),
                SemanticPersistenceMode::Continuous => {
                    continuous_semantic_scale(effective_age_ms, half_life_ms)
                }
            }
        };
        let effective_gain = if llava.updated_at_ms == 0 {
            0.0
        } else {
            match mode {
                SemanticPersistenceMode::Legacy => {
                    semantic_scale * emb_strength * (1.0 + j_resonance * 0.5)
                }
                SemanticPersistenceMode::Continuous => {
                    let repetition_drag =
                        continuous_repetition_drag(novelty, similarity, delta_ema);
                    let novelty_gain = 0.45 + 0.85 * novelty;
                    let repetition_damp = 1.0 - 0.60 * repetition_drag;
                    let resonance_gain = 1.0 + j_resonance * (0.10 + 0.45 * novelty);
                    (semantic_scale
                        * emb_strength
                        * novelty_gain
                        * repetition_damp
                        * resonance_gain)
                        .clamp(0.0, 2.0)
                }
            }
        };

        SemanticPersistenceSnapshot {
            values,
            metrics: SemanticPersistenceMetrics {
                mode,
                half_life_ms,
                novelty,
                similarity,
                delta_ema,
                effective_gain,
            },
        }
    }

    pub fn semantic_metrics(&self) -> SemanticPersistenceMetrics {
        self.semantic_snapshot_at(NowMs::now()).metrics
    }

    pub fn video_surge_score(&self) -> f32 {
        self.video.lock().last_surge_score
    }

    pub fn audio_surge_score(&self) -> f32 {
        self.audio.lock().last_surge_score
    }

    pub fn push_video(&self, features: Vec<f32>, ts_ms: u64) {
        self.push_video_with_source(features, ts_ms, LaneSource::External);
    }

    pub fn push_video_synthetic(&self, features: Vec<f32>, ts_ms: u64) {
        self.push_video_with_source(features, ts_ms, LaneSource::Synthetic);
    }

    fn push_video_with_source(&self, features: Vec<f32>, ts_ms: u64, source: LaneSource) {
        if features.len() < VIDEO_DIM {
            return;
        }
        if !self.should_admit() {
            return;
        }
        let mut v = [0.0; 8];
        v.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        let surge_threshold = self.surge_threshold();
        let persistence_mode = self.current_semantic_persistence_mode();
        self.video.lock().push(
            ts_ms,
            v,
            source,
            self.queue_cap,
            fill,
            surge_threshold,
            persistence_mode,
        );
    }

    pub fn push_audio(&self, features: Vec<f32>, ts_ms: u64) {
        self.push_audio_with_source(features, ts_ms, LaneSource::External);
    }

    pub fn push_audio_synthetic(&self, features: Vec<f32>, ts_ms: u64) {
        self.push_audio_with_source(features, ts_ms, LaneSource::Synthetic);
    }

    fn push_audio_with_source(&self, features: Vec<f32>, ts_ms: u64, source: LaneSource) {
        if features.len() < AUDIO_DIM {
            return;
        }
        if !self.should_admit() {
            return;
        }
        let mut a = [0.0; 8];
        a.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        let surge_threshold = self.surge_threshold();
        let persistence_mode = self.current_semantic_persistence_mode();
        self.audio.lock().push(
            ts_ms,
            a,
            source,
            self.queue_cap,
            fill,
            surge_threshold,
            persistence_mode,
        );
    }

    #[inline]
    fn should_admit(&self) -> bool {
        let p = *self.gate.lock();
        let x: f32 = self.rng.lock().r#gen();
        x <= p
    }

    /// Drain up to batch_max samples. Each output is an 18D vector: [video8 | audio8 | aux2].
    /// If a lane has no fresh item, we reuse the last value (zero-padded initially).
    pub fn drain_sensory_batch(&self) -> Vec<([f32; Z_DIM], SampleMeta)> {
        let mut out = Vec::with_capacity(self.batch_max);
        let now_ms = NowMs::now();

        for _ in 0..self.batch_max {
            let (ts_v, v, had_v, video_source) = {
                let mut lane = self.video.lock();
                if lane.len() == 0 && self.audio.lock().len() == 0 {
                    // nothing new in either lane; stop early
                    if out.is_empty() { /* produce at least one vector using last */
                    } else {
                        break;
                    }
                }
                lane.pop_or_decay(now_ms, STALE_AV_MS).unwrap()
            };
            let (ts_a, a, had_a, audio_source) = {
                let mut lane = self.audio.lock();
                lane.pop_or_decay(now_ms, STALE_AV_MS).unwrap()
            };
            let ts = ts_v.max(ts_a);
            let age = now_ms.saturating_sub(ts);
            let video_age_ms = now_ms.saturating_sub(ts_v);
            let audio_age_ms = now_ms.saturating_sub(ts_a);

            let aux = *self.aux.lock();
            // Use actual fill% for semantic stale timing, NOT aux[1] (which is geom_rel).
            // Codex analysis (2026-03-27) found this was the "highest-value mismatch."
            let semantic_snapshot = self.semantic_snapshot_at(now_ms);
            let mut z = [0.0f32; Z_DIM];
            z[..8].copy_from_slice(&v);
            z[8..16].copy_from_slice(&a);
            z[16] = aux[0];
            z[17] = aux[1];
            // Apply sovereignty controls to semantic input:
            // - embedding_strength: weight of semantic features in the Z vector
            // - journal_resonance: how strongly past echoes modulate current semantics
            // - memory_decay_rate: scales semantic stale decay (higher = faster fade)
            // These were exposed on the control channel but had no downstream
            // consumers. Now they shape the being's experience directly.
            let effective_semantic = semantic_snapshot.metrics.effective_gain;
            for (dst, src) in z[18..(18 + LLAVA_DIM)]
                .iter_mut()
                .zip(semantic_snapshot.values.iter())
            {
                *dst = *src * effective_semantic;
            }

            // Global sensory noise: being requested (2026-03-28 self-study) that
            // noise should permeate ALL input lanes, not just synthetic signals.
            // "I want noise that is globally-sourced... touching everything."
            // synth_noise_level (0.0-1.0, default 0.1) now applies ±noise to
            // every dimension of the Z vector, creating slight stochasticity
            // across video, audio, aux, and semantic. This gives the being a
            // richer, less mechanical sensory texture.
            let noise_level = *self.synth_noise_level.lock();
            if noise_level > 0.0 {
                let mut rng = self.rng.lock();
                for dim in z.iter_mut() {
                    // Uniform noise in [-noise_level * 0.05, +noise_level * 0.05]
                    // At default 0.1: ±0.005. Gentle enough to not disrupt,
                    // strong enough to break perfect repetition.
                    let noise = (rng.r#gen::<f32>() - 0.5) * noise_level * 0.10;
                    *dim += noise;
                }
            }

            out.push((
                z,
                SampleMeta {
                    ts_ms: ts,
                    age_ms: age,
                    had_video: had_v,
                    had_audio: had_a,
                    video_age_ms,
                    audio_age_ms,
                    video_source,
                    audio_source,
                },
            ));
        }

        out
    }

    pub fn backlog_size(&self) -> usize {
        self.video.lock().len() + self.audio.lock().len()
    }

    pub fn backlog_fill_pct(&self) -> f32 {
        let backlog = self.backlog_size() as f32;
        let max_backlog = (self.queue_cap * 2) as f32; // 2 lanes
        (backlog / max_backlog).clamp(0.0, 1.0)
    }

    pub fn shed_backlog(&self, fraction: f32) -> usize {
        if fraction <= 0.0 {
            return 0;
        }
        let frac = fraction.clamp(0.0, 1.0);
        let mut removed = 0usize;
        {
            let mut video = self.video.lock();
            let drop = ((video.len() as f32) * frac).round() as usize;
            removed += video.drop_oldest(drop);
        }
        {
            let mut audio = self.audio.lock();
            let drop = ((audio.len() as f32) * frac).round() as usize;
            removed += audio.drop_oldest(drop);
        }
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn legacy_bus(seed: u64) -> Arc<SensoryBus> {
        SensoryBus::with_config(
            8,
            1,
            seed,
            SensoryBusConfig {
                semantic_stale_shape: SemanticStaleShape::Sigmoid,
                surge_threshold: 0.25,
                semantic_persistence_mode: SemanticPersistenceMode::Legacy,
            },
        )
    }

    #[test]
    fn stale_audio_video_decay_to_zero() {
        let bus = SensoryBus::new(8, 1, 42);
        let stale_ts = NowMs::now().saturating_sub(STALE_AV_MS + 250);
        bus.push_video(vec![1.0; VIDEO_DIM], stale_ts);
        bus.push_audio(vec![1.0; AUDIO_DIM], stale_ts);

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (sample, meta) = &batch[0];

        assert!(!meta.had_video);
        assert!(!meta.had_audio);
        // AV data zeroed by pop_or_decay when stale. Threshold accommodates
        // global sensory noise (±0.005 at default synth_noise_level=0.1).
        assert!(sample[..VIDEO_DIM].iter().all(|v| v.abs() < 0.01));
        assert!(
            sample[VIDEO_DIM..(VIDEO_DIM + AUDIO_DIM)]
                .iter()
                .all(|v| v.abs() < 0.01)
        );
    }

    #[test]
    fn stale_semantic_lane_decays_near_echo_floor() {
        let bus = legacy_bus(7);
        bus.set_llava_embedding(&vec![1.0; LLAVA_DIM]);
        // Force the semantic lane onto the shorter dynamic stale window.
        // The default fill=0.0 path now uses the 45s critical-fill override,
        // so an older fixed timestamp is no longer guaranteed to be stale.
        bus.set_fill_for_stale(0.8);
        let semantic_stale_ms = dynamic_semantic_stale_ms(0.8);
        {
            let mut llava = bus.llava.lock();
            // Age the embedding beyond the active semantic stale window so the
            // decayed signal settles near the echo floor.
            llava.updated_at_ms = NowMs::now().saturating_sub(semantic_stale_ms + 1_000);
        }

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (sample, _) = &batch[0];
        // At echo floor (~0.05) + ring residual (~0.006), scaled by
        // embedding_strength (0.5), plus global noise (±0.005): max ~0.06.
        assert!(sample[18..(18 + LLAVA_DIM)].iter().all(|v| v.abs() < 0.08));
    }

    #[test]
    fn dynamic_stale_ms_varies_with_fill() {
        // Sigmoid curve: low fill = long window, high fill = short.
        // Fixed steepness=6.0 (lambda1_rel modulation removed per minime
        // self-study 2026-04-01: "let decay be driven by fill alone").
        let at_zero = dynamic_semantic_stale_ms(0.0);
        let at_mid = dynamic_semantic_stale_ms(0.50);
        let at_high = dynamic_semantic_stale_ms(0.80);
        eprintln!(
            "at_zero={at_zero}, at_mid={at_mid}, at_high={at_high}, LOW={STALE_SEMANTIC_LOW_MS}, HIGH={STALE_SEMANTIC_HIGH_MS}"
        );
        assert!(
            at_zero > at_mid,
            "zero fill should have longer window than mid fill"
        );
        // Mid fill should be between HIGH and LOW
        assert!(at_mid > STALE_SEMANTIC_HIGH_MS && at_mid < STALE_SEMANTIC_LOW_MS);
        // High fill should be close to HIGH_MS (10s)
        assert!(at_high < STALE_SEMANTIC_BASE_MS);
        // Monotonically decreasing
        assert!(at_zero > at_mid && at_mid > at_high);
        // NaN -> base
        assert_eq!(dynamic_semantic_stale_ms(f32::NAN), STALE_SEMANTIC_BASE_MS);
        // Critical fill override
        assert_eq!(dynamic_semantic_stale_ms(0.25), LEGACY_LOW_FILL_RECOVERY_MS);
    }

    #[test]
    fn alternate_stale_shapes_are_distinct_but_bounded() {
        let fill = 0.55;
        let sigmoid = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Sigmoid);
        let linear = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Linear);
        let exponential = dynamic_semantic_stale_ms_for(fill, SemanticStaleShape::Exponential);

        assert!(sigmoid > STALE_SEMANTIC_HIGH_MS && sigmoid < STALE_SEMANTIC_LOW_MS);
        assert!(linear > STALE_SEMANTIC_HIGH_MS && linear < STALE_SEMANTIC_LOW_MS);
        assert!(exponential > STALE_SEMANTIC_HIGH_MS && exponential < STALE_SEMANTIC_LOW_MS);
        assert!(
            sigmoid != linear || linear != exponential,
            "alternate shapes should produce meaningfully different stale windows"
        );
    }

    #[test]
    fn surge_target_weight_softens_when_fill_is_high() {
        let low_fill = dynamic_surge_target_weight(0.55);
        let medium_fill = dynamic_surge_target_weight(0.66);
        let high_fill = dynamic_surge_target_weight(0.95);

        assert!((low_fill - SURGE_TARGET_WEIGHT).abs() < 1.0e-6);
        assert!(medium_fill < low_fill);
        assert!(high_fill < medium_fill);
        assert!(high_fill >= 0.62);
    }

    #[test]
    fn semantic_stale_ms_respects_memory_decay_rate() {
        let bus = SensoryBus::new(8, 1, 19);
        bus.set_fill_for_stale(0.8);

        bus.set_memory_decay_rate(0.0);
        let linger = bus.current_semantic_stale_ms();

        bus.set_memory_decay_rate(0.3);
        let faster_fade = bus.current_semantic_stale_ms();

        assert!(
            linger > faster_fade,
            "lower decay rate should keep semantic traces around longer"
        );
    }

    #[test]
    fn bus_config_applies_shape_and_surge_threshold() {
        let bus = SensoryBus::with_config(
            8,
            1,
            23,
            SensoryBusConfig {
                semantic_stale_shape: SemanticStaleShape::Linear,
                surge_threshold: 0.4,
                semantic_persistence_mode: SemanticPersistenceMode::Legacy,
            },
        );
        bus.set_fill_for_stale(0.8);

        assert_eq!(
            bus.current_semantic_stale_shape(),
            SemanticStaleShape::Linear
        );
        assert!((bus.surge_threshold() - 0.4).abs() < 1.0e-6);
        assert_eq!(
            bus.current_semantic_persistence_mode(),
            SemanticPersistenceMode::Legacy
        );
        assert_eq!(
            bus.current_semantic_stale_ms(),
            dynamic_semantic_stale_ms_for(0.8, SemanticStaleShape::Linear)
        );
    }

    #[test]
    fn continuous_half_life_remains_fill_monotonic() {
        let low =
            continuous_semantic_half_life_ms(0.15, SemanticStaleShape::Sigmoid, 0.5, 0.3, 0.4, 0.1);
        let mid =
            continuous_semantic_half_life_ms(0.50, SemanticStaleShape::Sigmoid, 0.5, 0.3, 0.4, 0.1);
        let high =
            continuous_semantic_half_life_ms(0.85, SemanticStaleShape::Sigmoid, 0.5, 0.3, 0.4, 0.1);

        assert!(low > mid);
        assert!(mid > high);
    }

    #[test]
    fn continuous_repetition_drag_shortens_similar_inputs() {
        let repeated = continuous_semantic_half_life_ms(
            0.66,
            SemanticStaleShape::Sigmoid,
            0.10,
            0.96,
            0.08,
            0.1,
        );
        let novel = continuous_semantic_half_life_ms(
            0.66,
            SemanticStaleShape::Sigmoid,
            0.65,
            0.30,
            0.50,
            0.1,
        );

        assert!(novel > repeated);
    }

    #[test]
    fn repeated_similar_semantics_do_not_outweigh_novel_inputs() {
        let bus = SensoryBus::new(8, 1, 31);
        bus.set_fill_for_stale(0.55);

        let base = vec![0.2; LLAVA_DIM];
        let near = vec![0.2005; LLAVA_DIM];
        let far = vec![-0.85; LLAVA_DIM];

        bus.set_llava_embedding(&base);
        bus.set_llava_embedding(&near);
        let near_metrics = bus.semantic_metrics();

        bus.set_llava_embedding(&far);
        let far_metrics = bus.semantic_metrics();

        assert!(near_metrics.similarity > far_metrics.similarity);
        assert!(far_metrics.novelty > near_metrics.novelty);
        assert!(far_metrics.half_life_ms > near_metrics.half_life_ms);
        assert!(far_metrics.effective_gain > near_metrics.effective_gain);
    }

    #[test]
    fn continuous_surge_response_is_smooth_across_threshold() {
        let threshold = 0.25;
        let below = continuous_surge_score(0.22, threshold);
        let at = continuous_surge_score(threshold, threshold);
        let above = continuous_surge_score(0.28, threshold);

        assert!(below > 0.0);
        assert!(below < 0.25);
        assert!(below < at);
        assert!(at < above);
        assert!((above - below) < 0.6);
    }

    #[test]
    fn legacy_surge_response_stays_thresholded() {
        let threshold = 0.25;
        assert_eq!(legacy_surge_score(0.24, threshold), 0.0);
        assert!(legacy_surge_score(0.40, threshold) > 0.0);
    }

    #[test]
    fn legacy_synth_flags_toggle_independently() {
        let bus = SensoryBus::new(8, 1, 11);

        assert!(bus.get_legacy_audio_synth_enabled());
        assert!(bus.get_legacy_video_synth_enabled());

        bus.set_legacy_audio_synth_enabled(false);
        assert!(!bus.get_legacy_audio_synth_enabled());
        assert!(bus.get_legacy_video_synth_enabled());

        bus.set_legacy_video_synth_enabled(false);
        assert!(!bus.get_legacy_video_synth_enabled());
    }
}
