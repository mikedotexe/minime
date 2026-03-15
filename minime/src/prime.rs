// Prime-driven scheduling and ring buffers
#![allow(dead_code)]

#[derive(Clone)]
pub struct PrimeRing {
    data: Vec<f32>,
    len: usize,
    write_idx: usize,
    filled: usize,
}

impl PrimeRing {
    pub fn with_prime_len(p: usize) -> Self {
        assert!(p >= 7, "Prime must be >= 7");
        Self {
            data: vec![0.0; p],
            len: p,
            write_idx: 0,
            filled: 0,
        }
    }

    pub fn push_scalar(&mut self, v: f32) {
        self.data[self.write_idx] = v;
        self.write_idx = (self.write_idx + 1) % self.len;
        if self.filled < self.len {
            self.filled += 1;
        }
    }

    pub fn fill_ratio(&self) -> f32 {
        (self.filled as f32) / (self.len as f32)
    }

    pub fn is_full(&self) -> bool {
        self.filled >= self.len
    }

    pub fn slice(&self) -> &[f32] {
        &self.data
    }

    pub fn len(&self) -> usize {
        self.len
    }
}

#[derive(Clone)]
pub struct PrimeScheduler {
    pub periods: Vec<usize>,
    pub counters: Vec<usize>,
}

impl PrimeScheduler {
    pub fn new(periods: &[usize]) -> Self {
        Self {
            periods: periods.to_vec(),
            counters: vec![0; periods.len()],
        }
    }

    pub fn tick(&mut self) -> Vec<bool> {
        let mut fires = vec![false; self.periods.len()];
        for (i, c) in self.counters.iter_mut().enumerate() {
            *c += 1;
            if *c % self.periods[i] == 0 {
                fires[i] = true;
                *c = 0;
            }
        }
        fires
    }
}

// Co-prime periods for different modalities
pub fn sensory_primes() -> Vec<usize> {
    vec![97, 101, 7] // audio, video, history (changed from 113 to 7 for 16x faster ESN updates)
}

// Synthetic feature generators for testing
pub fn synth_audio_features(n: usize, phase: &mut f32) -> Vec<f32> {
    let mut v = vec![0.0f32; n];
    for i in 0..n {
        let t = *phase + i as f32 * 0.03;
        v[i] = t.sin() * 0.5 + (t * 0.5).cos() * 0.25;
    }
    *phase += n as f32 * 0.03;
    v
}

pub fn synth_video_features(n: usize, rng: &mut fastrand::Rng) -> Vec<f32> {
    (0..n).map(|_| rng.f32() * 2.0 - 1.0).collect()
}

pub fn rms(x: &[f32]) -> f32 {
    let s: f64 = x.iter().map(|v| (*v as f64).powi(2)).sum();
    (s / (x.len() as f64)).sqrt() as f32
}

pub fn variance(x: &[f32]) -> f32 {
    let m: f64 = x.iter().map(|&v| v as f64).sum::<f64>() / (x.len() as f64);
    let s: f64 = x
        .iter()
        .map(|&v| {
            let d = (v as f64) - m;
            d * d
        })
        .sum::<f64>()
        / (x.len() as f64);
    s as f32
}
