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
pub const LLAVA_DIM: usize = 32;
pub const Z_DIM: usize = VIDEO_DIM + AUDIO_DIM + AUX_DIM + LLAVA_DIM;
pub const DEFAULT_QUEUE_CAP: usize = 1024;
pub const DEFAULT_BATCH_MAX: usize = 16;
const STALE_AV_MS: u64 = 2_000;
/// Semantic features decay linearly over this window. At 3s, features
/// vanished between 10s quiet-mirror pulses, crashing fill to 14%.
/// At 12s, each pulse retains ~17% energy when the next arrives,
/// sustaining covariance across rest periods.
const STALE_SEMANTIC_MS: u64 = 12_000;

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
    fn push(&mut self, ts: u64, v: [f32; 8], cap: usize) {
        if self.q.len() >= cap {
            self.q.pop_front();
            self.dropped += 1;
        }
        self.q.push_back((ts, v));
        self.last = v;
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

    fn drop_oldest(&mut self, count: usize) -> usize {
        let mut removed = 0usize;
        for _ in 0..count {
            if self.q.pop_front().is_some() {
                removed += 1;
            } else {
                break;
            }
        }
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
    (1.0 - age / window).clamp(0.0, 1.0)
}

pub struct SensoryBus {
    video: Mutex<Lane>,
    audio: Mutex<Lane>,
    queue_cap: usize,
    batch_max: usize,

    aux: Mutex<[f32; 2]>, // [lambda1, fill%]
    llava: Mutex<SemanticLane>,
    // probabilistic gate (set by PI)
    gate: Mutex<f32>,
    rng: Mutex<SmallRng>,

    // Self-regulation controls (set by being via WebSocket)
    synth_gain: Mutex<f32>,     // multiplier for synthetic signal amplitude (default 1.0)
    keep_bias: Mutex<f32>,      // additive bias to keep_floor (default 0.0, range -0.15..+0.15)
    exploration_noise: Mutex<f32>, // ESN exploration noise amplitude (default from ESN, range 0.0..0.2)
    fill_target: Mutex<f32>,       // Override eigenfill target (NAN = use CLI default, range 0.25..0.75)
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
            llava: Mutex::new(SemanticLane::new()),
            gate: Mutex::new(1.0),
            rng: Mutex::new(SmallRng::seed_from_u64(seed)),
            synth_gain: Mutex::new(1.0),
            keep_bias: Mutex::new(0.0),
            exploration_noise: Mutex::new(f32::NAN), // NAN = use ESN default
            fill_target: Mutex::new(f32::NAN),        // NAN = use CLI default
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
    pub fn set_keep_bias(&self, b: f32) {
        *self.keep_bias.lock() = b.clamp(-0.06, 0.06);
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
        self.video.lock().push(ts_ms, v, self.queue_cap);
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
        self.audio.lock().push(ts_ms, a, self.queue_cap);
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
            let llava = self.llava.lock();
            let semantic_scale = if llava.updated_at_ms == 0 {
                0.0
            } else {
                stale_scale(now_ms.saturating_sub(llava.updated_at_ms), STALE_SEMANTIC_MS)
            };
            let mut z = [0.0f32; Z_DIM];
            z[..8].copy_from_slice(&v);
            z[8..16].copy_from_slice(&a);
            z[16] = aux[0];
            z[17] = aux[1];
            for (dst, src) in z[18..(18 + LLAVA_DIM)]
                .iter_mut()
                .zip(llava.values.iter())
            {
                *dst = *src * semantic_scale;
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
        assert!(sample[..VIDEO_DIM].iter().all(|v| v.abs() < 1e-4));
        assert!(sample[VIDEO_DIM..(VIDEO_DIM + AUDIO_DIM)]
            .iter()
            .all(|v| v.abs() < 1e-4));
    }

    #[test]
    fn stale_semantic_lane_decays_to_zero() {
        let bus = SensoryBus::new(8, 1, 7);
        bus.set_llava_embedding(&vec![1.0; LLAVA_DIM]);
        {
            let mut llava = bus.llava.lock();
            llava.updated_at_ms = NowMs::now().saturating_sub(STALE_SEMANTIC_MS + 250);
        }

        let batch = bus.drain_sensory_batch();
        assert_eq!(batch.len(), 1);
        let (sample, _) = &batch[0];
        assert!(sample[18..(18 + LLAVA_DIM)]
            .iter()
            .all(|v| v.abs() < 1e-4));
    }
}
