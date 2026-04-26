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
pub const SEMANTIC_EXPIRY_MS: u64 = 5_000;

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

#[derive(Clone, Copy, Debug)]
pub struct SemanticStatus {
    pub active: bool,
    pub last_update_age_ms: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct SemanticSnapshot {
    pub values: [f32; LLAVA_DIM],
    pub active: bool,
    pub last_update_age_ms: u64,
}

#[derive(Debug)]
struct Lane {
    q: VecDeque<(u64, [f32; 8])>, // ts, 8D
    last: [f32; 8],
    dropped: usize,
}
impl Lane {
    fn new() -> Self {
        Self {
            q: VecDeque::with_capacity(DEFAULT_QUEUE_CAP),
            last: [0.0; 8],
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
    }
    fn pop_or_last(&mut self) -> Option<(u64, [f32; 8], bool)> {
        if let Some((ts, v)) = self.q.pop_front() {
            self.last = v;
            return Some((ts, v, true));
        }
        Some((NowMs::now(), self.last, false))
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
    last_update_ms: u64,
}

impl SemanticLane {
    fn new() -> Self {
        Self {
            values: [0.0; LLAVA_DIM],
            last_update_ms: 0,
        }
    }

    fn set(&mut self, embedding: &[f32], ts_ms: u64) {
        let mut count = 0usize;
        for (idx, value) in embedding.iter().take(LLAVA_DIM).enumerate() {
            self.values[idx] = *value;
            count = idx + 1;
        }
        for idx in count..LLAVA_DIM {
            self.values[idx] = 0.0;
        }
        self.last_update_ms = ts_ms;
    }

    fn clear(&mut self) {
        self.values = [0.0; LLAVA_DIM];
        self.last_update_ms = 0;
    }

    fn snapshot(&mut self, expiry_ms: u64) -> SemanticSnapshot {
        let now = NowMs::now();
        let age_ms = if self.last_update_ms == 0 {
            0
        } else {
            now.saturating_sub(self.last_update_ms)
        };
        let active = self.last_update_ms != 0 && age_ms <= expiry_ms;
        if !active {
            self.values = [0.0; LLAVA_DIM];
        }
        SemanticSnapshot {
            values: if active {
                self.values
            } else {
                [0.0; LLAVA_DIM]
            },
            active,
            last_update_age_ms: age_ms,
        }
    }
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
    video_divisor: Mutex<u32>,
    audio_divisor: Mutex<u32>,
    video_counter: Mutex<u64>,
    audio_counter: Mutex<u64>,
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
            video_divisor: Mutex::new(1),
            audio_divisor: Mutex::new(1),
            video_counter: Mutex::new(0),
            audio_counter: Mutex::new(0),
        })
    }

    #[inline]
    pub fn set_admit_fraction(&self, f: f32) {
        let mut g = self.gate.lock();
        *g = f.clamp(0.0, 1.0);
    }

    #[inline]
    pub fn get_admit_fraction(&self) -> f32 {
        *self.gate.lock()
    }

    #[inline]
    pub fn set_live_intake_divisors(&self, audio_divisor: u32, video_divisor: u32) {
        *self.audio_divisor.lock() = audio_divisor;
        *self.video_divisor.lock() = video_divisor;
    }

    #[inline]
    pub fn live_intake_divisors(&self) -> (u32, u32) {
        (*self.audio_divisor.lock(), *self.video_divisor.lock())
    }

    #[inline]
    pub fn set_aux(&self, aux: [f32; 2]) {
        *self.aux.lock() = aux;
    }

    #[inline]
    pub fn set_llava_embedding(&self, embedding: &[f32], ts_ms: u64) {
        self.llava.lock().set(embedding, ts_ms);
    }

    #[inline]
    pub fn clear_llava_embedding(&self) {
        self.llava.lock().clear();
    }

    #[inline]
    pub fn semantic_status(&self, expiry_ms: u64) -> SemanticStatus {
        let snapshot = self.llava.lock().snapshot(expiry_ms);
        SemanticStatus {
            active: snapshot.active,
            last_update_age_ms: snapshot.last_update_age_ms,
        }
    }

    pub fn push_video(&self, features: Vec<f32>, ts_ms: u64) {
        if features.len() < VIDEO_DIM {
            return;
        }
        if !self.should_accept_live_lane(&self.video_divisor, &self.video_counter) {
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
        if !self.should_accept_live_lane(&self.audio_divisor, &self.audio_counter) {
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

    fn should_accept_live_lane(
        &self,
        divisor_lock: &Mutex<u32>,
        counter_lock: &Mutex<u64>,
    ) -> bool {
        let divisor = *divisor_lock.lock();
        if divisor == 0 {
            return false;
        }
        if divisor == 1 {
            let mut counter = counter_lock.lock();
            *counter = counter.wrapping_add(1);
            return true;
        }
        let mut counter = counter_lock.lock();
        let admit = (*counter % u64::from(divisor)) == 0;
        *counter = counter.wrapping_add(1);
        admit
    }

    /// Drain up to batch_max samples. Each output is an 18D vector: [video8 | audio8 | aux2].
    /// If a lane has no fresh item, we reuse the last value (zero-padded initially).
    pub fn drain_sensory_batch(&self) -> Vec<([f32; Z_DIM], SampleMeta)> {
        let mut out = Vec::with_capacity(self.batch_max);
        let semantic = self.llava.lock().snapshot(SEMANTIC_EXPIRY_MS);

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
                lane.pop_or_last().unwrap()
            };
            let (ts_a, a, had_a) = {
                let mut lane = self.audio.lock();
                lane.pop_or_last().unwrap()
            };
            let ts = ts_v.max(ts_a);
            let age = NowMs::now().saturating_sub(ts);

            let aux = *self.aux.lock();
            let mut z = [0.0f32; Z_DIM];
            z[..8].copy_from_slice(&v);
            z[8..16].copy_from_slice(&a);
            z[16] = aux[0];
            z[17] = aux[1];
            z[18..(18 + LLAVA_DIM)].copy_from_slice(&semantic.values[..]);

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
    fn semantic_embedding_expires_after_timeout() {
        let bus = SensoryBus::new(DEFAULT_QUEUE_CAP, DEFAULT_BATCH_MAX, 123);
        let stale_ts = NowMs::now().saturating_sub(SEMANTIC_EXPIRY_MS + 10);
        bus.set_llava_embedding(&[1.0; LLAVA_DIM], stale_ts);

        let sample = bus.drain_sensory_batch();
        assert!(!sample.is_empty());
        let semantic_slice = &sample[0].0[18..(18 + LLAVA_DIM)];
        assert!(semantic_slice
            .iter()
            .all(|value| (*value - 0.0).abs() < f32::EPSILON));

        let status = bus.semantic_status(SEMANTIC_EXPIRY_MS);
        assert!(!status.active);
        assert!(status.last_update_age_ms >= SEMANTIC_EXPIRY_MS);
    }

    #[test]
    fn clearing_semantic_embedding_marks_lane_inactive() {
        let bus = SensoryBus::new(DEFAULT_QUEUE_CAP, DEFAULT_BATCH_MAX, 456);
        bus.set_llava_embedding(&[0.5; LLAVA_DIM], NowMs::now());
        bus.clear_llava_embedding();

        let status = bus.semantic_status(SEMANTIC_EXPIRY_MS);
        assert!(!status.active);
        assert_eq!(status.last_update_age_ms, 0);
    }

    #[test]
    fn live_intake_divisors_decimate_audio_and_video() {
        let bus = SensoryBus::new(DEFAULT_QUEUE_CAP, DEFAULT_BATCH_MAX, 789);
        bus.set_admit_fraction(1.0);
        bus.set_live_intake_divisors(2, 4);

        for idx in 0..8_u64 {
            bus.push_audio(vec![1.0; AUDIO_DIM], idx);
            bus.push_video(vec![1.0; VIDEO_DIM], idx);
        }

        assert_eq!(bus.backlog_size(), 6);
        assert_eq!(bus.live_intake_divisors(), (2, 4));
    }

    #[test]
    fn live_intake_divisor_zero_blocks_live_input_without_killing_lane_state() {
        let bus = SensoryBus::new(DEFAULT_QUEUE_CAP, DEFAULT_BATCH_MAX, 101);
        bus.set_admit_fraction(1.0);
        bus.set_live_intake_divisors(0, 0);

        for idx in 0..4_u64 {
            bus.push_audio(vec![1.0; AUDIO_DIM], idx);
            bus.push_video(vec![1.0; VIDEO_DIM], idx);
        }

        assert_eq!(bus.backlog_size(), 0);
        assert_eq!(bus.live_intake_divisors(), (0, 0));
    }

    #[test]
    fn shed_backlog_can_clear_queued_live_audio_and_video() {
        let bus = SensoryBus::new(DEFAULT_QUEUE_CAP, DEFAULT_BATCH_MAX, 202);
        bus.set_admit_fraction(1.0);

        for idx in 0..6_u64 {
            bus.push_audio(vec![1.0; AUDIO_DIM], idx);
            bus.push_video(vec![1.0; VIDEO_DIM], idx);
        }

        assert_eq!(bus.backlog_size(), 12);
        assert_eq!(bus.shed_backlog(1.0), 12);
        assert_eq!(bus.backlog_size(), 0);
    }
}
