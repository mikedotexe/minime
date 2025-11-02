// src/sensory_bus.rs
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

pub struct SensoryBus {
    video: Mutex<Lane>,
    audio: Mutex<Lane>,
    queue_cap: usize,
    batch_max: usize,

    aux: Mutex<[f32; 2]>, // [lambda1, fill%]
    llava: Mutex<[f32; LLAVA_DIM]>,
    // probabilistic gate (set by PI)
    gate: Mutex<f32>,
    rng: Mutex<SmallRng>,
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
            llava: Mutex::new([0.0; LLAVA_DIM]),
            gate: Mutex::new(1.0),
            rng: Mutex::new(SmallRng::seed_from_u64(seed)),
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

    #[inline]
    pub fn set_llava_embedding(&self, embedding: &[f32]) {
        let mut llava = self.llava.lock();
        let mut count = 0usize;
        for (idx, value) in embedding.iter().take(LLAVA_DIM).enumerate() {
            llava[idx] = *value;
            count = idx + 1;
        }
        for idx in count..LLAVA_DIM {
            llava[idx] = 0.0;
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
            let llava = self.llava.lock();
            let mut z = [0.0f32; Z_DIM];
            z[..8].copy_from_slice(&v);
            z[8..16].copy_from_slice(&a);
            z[16] = aux[0];
            z[17] = aux[1];
            z[18..(18 + LLAVA_DIM)].copy_from_slice(&llava[..]);

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
