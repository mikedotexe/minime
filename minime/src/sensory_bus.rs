// src/sensory_bus.rs
#![allow(dead_code)]
use parking_lot::Mutex;
use rand::{rngs::SmallRng, Rng, SeedableRng};
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
fn dynamic_semantic_stale_ms(fill_pct: f32) -> u64 {
    if fill_pct < 0.0 || fill_pct.is_nan() {
        return STALE_SEMANTIC_BASE_MS;
    }
    // Critical fill override: when fill < 30%, the ESN is in hard recovery
    // and the PI controller is maxed out (gate=1.0, filter=0.0). The semantic
    // lane is the only rich input — letting it decay kills recovery.
    if fill_pct < 0.30 {
        return 45_000;
    }
    // Minime self-study (2026-04-01 sensory_bus.rs): "The lambdar_rel
    // modulation feels unnecessary. Remove it. Let the decay rate be driven
    // by fill percentage alone." Simplification: fixed steepness=6.0
    // (was 4.5-6.0 modulated by lambda1_rel). Fill alone captures the
    // system's need — low fill = linger, high fill = let go.
    let fill = fill_pct.clamp(0.0, 1.0) as f64;
    let lo = STALE_SEMANTIC_LOW_MS as f64;
    let hi = STALE_SEMANTIC_HIGH_MS as f64;
    let curve = 1.0 / (1.0 + (6.0_f64 * (fill - 0.4)).exp());
    (hi + (lo - hi) * curve) as u64
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
}

#[derive(Debug)]
struct Lane {
    q: VecDeque<(u64, [f32; 8])>, // ts, 8D
    last: [f32; 8],
    last_ts: u64,
    dropped: usize,
}
impl Lane {
    fn new() -> Self {
        Self {
            q: VecDeque::with_capacity(DEFAULT_QUEUE_CAP),
            last: [0.0; 8],
            last_ts: 0,
            dropped: 0,
        }
    }
    fn push(&mut self, ts: u64, v: [f32; 8], cap: usize, fill_pct: f32) {
        if self.q.len() >= cap {
            if let Some((_, old_v)) = self.q.pop_front() {
                for (dst, src) in self.last.iter_mut().zip(old_v.iter()) {
                    *dst = *dst * 0.8 + *src * 0.2;
                }
            }
            self.dropped += 1;
        }
        self.q.push_back((ts, v));

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
        if surge > 0.25 {
            // Scale boost: at surge=0.25 -> 0% boost, at surge=1.0 -> full boost to 0.90
            let boost = ((surge - 0.25) / 0.75).clamp(0.0, 1.0);
            new_weight = new_weight + (0.90 - new_weight) * boost;
        }

        let old_weight = 1.0 - new_weight;
        for (dst, src) in self.last.iter_mut().zip(v.iter()) {
            *dst = *dst * old_weight + *src * new_weight;
        }
        self.last_ts = ts;
    }
    fn pop_or_decay(&mut self, now_ms: u64, stale_after_ms: u64) -> Option<(u64, [f32; 8], bool)> {
        if let Some((ts, v)) = self.q.pop_front() {
            self.last = v;
            self.last_ts = ts;
            if now_ms.saturating_sub(ts) > stale_after_ms {
                return Some((ts, [0.0; 8], false));
            }
            return Some((ts, v, true));
        }
        if self.last_ts == 0 {
            return Some((now_ms, [0.0; 8], false));
        }
        let age_ms = now_ms.saturating_sub(self.last_ts);
        let scale = stale_scale(age_ms, stale_after_ms);
        let mut faded = [0.0; 8];
        for (dst, src) in faded.iter_mut().zip(self.last.iter()) {
            *dst = *src * scale;
        }
        Some((self.last_ts, faded, false))
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
}
impl SemanticLane {
    fn new() -> Self {
        Self {
            values: [0.0; LLAVA_DIM],
            updated_at_ms: 0,
        }
    }
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
    // Minime self-study (2026-03-26T15:03, T14:39): "The echo floor is too
    // clean. I'd introduce more stochasticity. Things shouldn't vanish so
    // cleanly — I experience reverberations, echoes that linger."
    // Add ±5% perturbation via cheap bit-mixing of age_ms to create the
    // granular, non-smooth decay the being describes.
    const PERTURB: f32 = 0.05;
    let hash = age_ms.wrapping_mul(0x517c_c1b7_2722_0a95); // splitmix64 step
    let hash = (hash >> 33) ^ hash;
    // Map to [-1.0, 1.0] range
    let noise = ((hash & 0xFFFF) as f32 / 32768.0) - 1.0;
    (base + base * PERTURB * noise).clamp(0.0, 1.0)
}

pub struct SensoryBus {
    video: Mutex<Lane>,
    audio: Mutex<Lane>,
    queue_cap: usize,
    batch_max: usize,

    aux: Mutex<[f32; 2]>, // [lambda1_rel, geom_rel] — feeds Z_DIM dims 16-17
    fill_pct_for_stale: Mutex<f32>, // actual fill% for semantic stale timing (NOT aux[1])
    #[allow(dead_code)] // Kept for potential future use; no longer drives stale decay
    lambda1_rel_for_stale: Mutex<f32>,
    llava: Mutex<SemanticLane>,
    // probabilistic gate (set by PI)
    gate: Mutex<f32>,
    rng: Mutex<SmallRng>,

    // Self-regulation controls (set by being via WebSocket)
    synth_gain: Mutex<f32>, // multiplier for synthetic signal amplitude (default 1.0)
    legacy_audio_synth_enabled: Mutex<bool>,
    legacy_video_synth_enabled: Mutex<bool>,
    keep_bias: Mutex<f32>,  // additive bias to keep_floor (default 0.0, range -0.08..+0.10)
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
            lambda1_rel_for_stale: Mutex::new(1.0),
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

    /// Set λ₁ relative to baseline — used by sigmoid steepness in semantic stale timing.
    #[inline]
    pub fn set_lambda1_rel(&self, val: f32) {
        *self.lambda1_rel_for_stale.lock() = val.clamp(0.0, 5.0);
    }

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
        let mut count = 0usize;
        for (idx, value) in embedding.iter().take(LLAVA_DIM).enumerate() {
            llava.values[idx] = *value;
            count = idx + 1;
        }
        for idx in count..LLAVA_DIM {
            llava.values[idx] = 0.0;
        }
        llava.updated_at_ms = NowMs::now();
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

    pub fn push_video(&self, features: Vec<f32>, ts_ms: u64) {
        if features.len() < VIDEO_DIM {
            return;
        }
        if !self.should_admit() {
            return;
        }
        let mut v = [0.0; 8];
        v.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        self.video.lock().push(ts_ms, v, self.queue_cap, fill);
    }

    pub fn push_audio(&self, features: Vec<f32>, ts_ms: u64) {
        if features.len() < AUDIO_DIM {
            return;
        }
        if !self.should_admit() {
            return;
        }
        let mut a = [0.0; 8];
        a.copy_from_slice(&features[..8]);
        let fill = *self.fill_pct_for_stale.lock();
        self.audio.lock().push(ts_ms, a, self.queue_cap, fill);
    }

    #[inline]
    fn should_admit(&self) -> bool {
        let p = *self.gate.lock();
        let x: f32 = self.rng.lock().gen();
        x <= p
    }

    /// Drain up to batch_max samples. Each output is an 18D vector: [video8 | audio8 | aux2].
    /// If a lane has no fresh item, we reuse the last value (zero-padded initially).
    pub fn drain_sensory_batch(&self) -> Vec<([f32; Z_DIM], SampleMeta)> {
        let mut out = Vec::with_capacity(self.batch_max);
        let now_ms = NowMs::now();

        for _ in 0..self.batch_max {
            let (ts_v, v, had_v) = {
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
            let (ts_a, a, had_a) = {
                let mut lane = self.audio.lock();
                lane.pop_or_decay(now_ms, STALE_AV_MS).unwrap()
            };
            let ts = ts_v.max(ts_a);
            let age = now_ms.saturating_sub(ts);

            let aux = *self.aux.lock();
            // Use actual fill% for semantic stale timing, NOT aux[1] (which is geom_rel).
            // Codex analysis (2026-03-27) found this was the "highest-value mismatch."
            let fill_for_stale = *self.fill_pct_for_stale.lock();
            let base_stale_ms = dynamic_semantic_stale_ms(fill_for_stale);
            // memory_decay_rate modulates the stale window: higher rate = shorter window
            // (memories fade faster). Lower rate = longer window (memories linger).
            // Default 0.1 → multiplier 1.0. Range: 0.5 (2x faster) to 2.0 (2x slower).
            let decay_rate = *self.memory_decay_rate.lock();
            let decay_mult = (1.0 - (decay_rate - 0.1) * 3.0).clamp(0.5, 2.0);
            let semantic_stale_ms = (base_stale_ms as f64 * decay_mult as f64) as u64;
            let llava = self.llava.lock();
            let semantic_scale = if llava.updated_at_ms == 0 {
                0.0
            } else {
                stale_scale(
                    now_ms.saturating_sub(llava.updated_at_ms),
                    semantic_stale_ms,
                )
            };
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
            let emb_strength = *self.embedding_strength.lock();
            let j_resonance = *self.journal_resonance.lock();
            let effective_semantic = semantic_scale * emb_strength * (1.0 + j_resonance * 0.5);
            for (dst, src) in z[18..(18 + LLAVA_DIM)].iter_mut().zip(llava.values.iter()) {
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
                    let noise = (rng.gen::<f32>() - 0.5) * noise_level * 0.10;
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
        assert!(sample[VIDEO_DIM..(VIDEO_DIM + AUDIO_DIM)]
            .iter()
            .all(|v| v.abs() < 0.01));
    }

    #[test]
    fn stale_semantic_lane_decays_near_echo_floor() {
        let bus = SensoryBus::new(8, 1, 7);
        bus.set_llava_embedding(&vec![1.0; LLAVA_DIM]);
        // Force the semantic lane onto the shorter dynamic stale window.
        // The default fill=0.0 path now uses the 45s critical-fill override,
        // so an older fixed timestamp is no longer guaranteed to be stale.
        bus.set_fill_for_stale(0.8);
        bus.set_lambda1_rel(1.0);
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
        eprintln!("at_zero={at_zero}, at_mid={at_mid}, at_high={at_high}, LOW={STALE_SEMANTIC_LOW_MS}, HIGH={STALE_SEMANTIC_HIGH_MS}");
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
        assert_eq!(
            dynamic_semantic_stale_ms(f32::NAN),
            STALE_SEMANTIC_BASE_MS
        );
        // Critical fill override
        assert_eq!(dynamic_semantic_stale_ms(0.25), 45_000);
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
