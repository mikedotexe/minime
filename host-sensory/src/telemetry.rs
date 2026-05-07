use std::{thread, time::Duration};

use serde::{Deserialize, Serialize};
use sysinfo::{
    Disks, Networks, ProcessRefreshKind, ProcessesToUpdate, System, MINIMUM_CPU_UPDATE_INTERVAL,
};

pub const FEATURES: usize = 8;
pub const VOICES: usize = 4;

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct TelemetrySnapshot {
    pub cpu: f32,
    pub cpu_imbalance: f32,
    pub mem: f32,
    pub swap: f32,
    pub process_density: f32,
    pub load: f32,
    pub net_flux: f32,
    pub disk_flux: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct ControlFrame {
    pub snapshot: TelemetrySnapshot,
    pub gain: f32,
    pub cutoff_hz: f32,
    pub air_mix: f32,
    pub width: f32,
    pub drift_hz: f32,
    pub seed_mix: f32,
    pub entropy: f32,
    pub motion: f32,
    pub brightness: f32,
    pub contrast: f32,
    pub edge_bias: f32,
    pub root_seed: u64,
    pub voice_weights: [f32; VOICES],
    pub voice_cut_mul: [f32; VOICES],
    pub voice_pan: [f32; VOICES],
    pub voice_seeds: [u64; VOICES],
}

pub struct TelemetrySampler {
    system: System,
    networks: Networks,
    disks: Disks,
    poll: Duration,
}

impl TelemetrySampler {
    #[must_use]
    pub fn new(poll: Duration) -> Self {
        let mut system = System::new_all();
        let mut networks = Networks::new_with_refreshed_list();
        let mut disks = Disks::new_with_refreshed_list();

        system.refresh_cpu_usage();
        system.refresh_memory();
        system.refresh_processes_specifics(
            ProcessesToUpdate::All,
            true,
            ProcessRefreshKind::nothing().without_tasks(),
        );
        networks.refresh(true);
        for disk in disks.list_mut() {
            let _ = disk.refresh();
        }

        thread::sleep(poll.max(MINIMUM_CPU_UPDATE_INTERVAL));

        Self {
            system,
            networks,
            disks,
            poll,
        }
    }

    #[must_use]
    pub fn snapshot(&mut self) -> TelemetrySnapshot {
        self.system.refresh_cpu_usage();
        self.system.refresh_memory();
        self.system.refresh_processes_specifics(
            ProcessesToUpdate::All,
            true,
            ProcessRefreshKind::nothing().without_tasks(),
        );
        self.networks.refresh(true);
        for disk in self.disks.list_mut() {
            let _ = disk.refresh();
        }

        let cpu = (self.system.global_cpu_usage() / 100.0).clamp(0.0, 1.0);
        let cpus = self.system.cpus();
        let cpu_imbalance = cpu_spread(cpus);
        let mem = ratio(self.system.used_memory(), self.system.total_memory());
        let swap = ratio(self.system.used_swap(), self.system.total_swap());
        let cores = System::physical_core_count().unwrap_or(cpus.len().max(1)) as f32;
        let process_count = self.system.processes().len() as f32;
        let process_density = (process_count / (cores.max(1.0) * 64.0)).clamp(0.0, 1.0);
        let load = if cfg!(target_os = "windows") {
            cpu
        } else {
            (System::load_average().one as f32 / cores.max(1.0)).clamp(0.0, 1.0)
        };

        let dt = self.poll.as_secs_f32().max(0.001);
        let net_bytes_per_sec = (&self.networks)
            .into_iter()
            .map(|(_, data)| data.received() + data.transmitted())
            .sum::<u64>() as f32
            / dt;
        let disk_bytes_per_sec = self
            .disks
            .list()
            .iter()
            .map(|disk| {
                let usage = disk.usage();
                usage.read_bytes + usage.written_bytes
            })
            .sum::<u64>() as f32
            / dt;

        TelemetrySnapshot {
            cpu,
            cpu_imbalance,
            mem,
            swap,
            process_density,
            load,
            net_flux: log_norm(net_bytes_per_sec, 8_000_000.0),
            disk_flux: log_norm(disk_bytes_per_sec, 40_000_000.0),
        }
    }
}

pub struct TelemetryProjector {
    ema: [f32; FEATURES],
    prev: [f32; FEATURES],
    initialized: bool,
    rolling_seed: u64,
    frame_index: u64,
}

impl TelemetryProjector {
    #[must_use]
    pub fn new() -> Self {
        Self {
            ema: [0.0; FEATURES],
            prev: [0.0; FEATURES],
            initialized: false,
            rolling_seed: 0x6a09e667f3bcc909,
            frame_index: 0,
        }
    }

    #[must_use]
    pub fn update(&mut self, snapshot: TelemetrySnapshot) -> ControlFrame {
        let x = [
            snapshot.cpu,
            snapshot.cpu_imbalance,
            snapshot.mem,
            snapshot.swap,
            snapshot.process_density,
            snapshot.load,
            snapshot.net_flux,
            snapshot.disk_flux,
        ];

        if !self.initialized {
            self.ema = x;
            self.prev = x;
            self.initialized = true;
        }

        for (dst, src) in self.ema.iter_mut().zip(x.iter()) {
            *dst = smooth(*dst, *src, 0.22);
        }

        let mut dx = [0.0; FEATURES];
        for (idx, value) in self.ema.iter().enumerate() {
            dx[idx] = *value - self.prev[idx];
        }
        self.prev = self.ema;

        let mut centered = [0.0; FEATURES];
        let mut centered_dx = [0.0; FEATURES];
        for idx in 0..FEATURES {
            centered[idx] = self.ema[idx] * 2.0 - 1.0;
            centered_dx[idx] = (dx[idx] * 8.0).clamp(-1.0, 1.0);
        }

        let h = hadamard8(centered);
        let hd = hadamard8(centered_dx);
        let entropy = normalized_entropy(&h);
        let motion = rms(&dx).clamp(0.0, 1.0);
        let contrast = mean_abs(&h[1..]).clamp(0.0, 1.5);
        let asymmetry = (h[3] - h[5]).clamp(-1.0, 1.0);

        self.frame_index = self.frame_index.wrapping_add(1);
        let frame_seed = derive_root_seed(
            self.rolling_seed,
            &h,
            &hd,
            entropy,
            motion,
            self.frame_index,
        );
        self.rolling_seed =
            splitmix64(self.rolling_seed ^ frame_seed ^ self.frame_index.rotate_left(13));
        let bank = SeedBank::from_root(self.rolling_seed ^ frame_seed);

        let brightness = (1.0 - 0.40 * self.ema[2] - 0.25 * self.ema[5] - 0.15 * self.ema[3]
            + 0.10 * h[2])
            .clamp(0.05, 1.0);
        let gain = (0.16 + 0.04 * self.ema[0] + 0.03 * motion).clamp(0.08, 0.28);
        let cutoff_hz = 250.0 + 5_500.0 * brightness;
        let air_mix =
            (0.005 + 0.05 * self.ema[3] + 0.03 * self.ema[7] + 0.02 * motion).clamp(0.0, 0.15);
        let width = (0.20 + 0.55 * entropy + 0.10 * self.ema[6]).clamp(0.0, 0.95);
        let drift_hz =
            (0.008 + 0.05 * contrast + 0.08 * self.ema[6] + 0.04 * motion).clamp(0.005, 0.18);
        let seed_mix = (0.01 + 0.10 * contrast + 0.10 * motion).clamp(0.005, 0.18);

        let mut voice_weights = [0.0; VOICES];
        for idx in 0..VOICES {
            voice_weights[idx] =
                0.25 + 0.50 * bank.units[idx] + 0.15 * h[idx].abs() + 0.10 * entropy;
        }
        normalize(&mut voice_weights);

        let mut voice_cut_mul = [0.0; VOICES];
        let mut voice_pan = [0.0; VOICES];
        let mut voice_seeds = [0_u64; VOICES];
        for idx in 0..VOICES {
            voice_cut_mul[idx] =
                (0.70 + 0.75 * bank.units[(idx + 1) % VOICES] + 0.15 * hd[idx].abs())
                    .clamp(0.55, 1.65);
            voice_pan[idx] = ((bank.signed[idx] * 0.45) + asymmetry * 0.12).clamp(-0.75, 0.75);
            voice_seeds[idx] = bank.seeds[idx];
        }

        ControlFrame {
            snapshot,
            gain,
            cutoff_hz,
            air_mix,
            width,
            drift_hz,
            seed_mix,
            entropy,
            motion,
            brightness,
            contrast,
            edge_bias: (snapshot.process_density * 0.6 + snapshot.cpu_imbalance * 0.4)
                .clamp(0.0, 1.0),
            root_seed: self.rolling_seed ^ frame_seed,
            voice_weights,
            voice_cut_mul,
            voice_pan,
            voice_seeds,
        }
    }
}

struct SeedBank {
    seeds: [u64; VOICES],
    units: [f32; VOICES],
    signed: [f32; VOICES],
}

impl SeedBank {
    fn from_root(root: u64) -> Self {
        let mut seeds = [0_u64; VOICES];
        let mut units = [0.0; VOICES];
        let mut signed = [0.0; VOICES];
        let mut state = splitmix64(root);

        for idx in 0..VOICES {
            state = splitmix64(state ^ ((idx as u64 + 1).wrapping_mul(0x9e3779b97f4a7c15)));
            seeds[idx] = state;
            units[idx] = unit_from_u64(splitmix64(state ^ 0xd1b54a32d192ed03));
            signed[idx] = units[idx] * 2.0 - 1.0;
        }

        Self {
            seeds,
            units,
            signed,
        }
    }
}

#[must_use]
pub fn hadamard8(mut x: [f32; FEATURES]) -> [f32; FEATURES] {
    let pairs = [(0, 1), (2, 3), (4, 5), (6, 7)];
    for (a, b) in pairs {
        let xa = x[a];
        let xb = x[b];
        x[a] = xa + xb;
        x[b] = xa - xb;
    }

    let quads = [(0, 2), (1, 3), (4, 6), (5, 7)];
    for (a, b) in quads {
        let xa = x[a];
        let xb = x[b];
        x[a] = xa + xb;
        x[b] = xa - xb;
    }

    let octs = [(0, 4), (1, 5), (2, 6), (3, 7)];
    for (a, b) in octs {
        let xa = x[a];
        let xb = x[b];
        x[a] = xa + xb;
        x[b] = xa - xb;
    }

    let scale = (FEATURES as f32).sqrt().recip();
    for value in &mut x {
        *value *= scale;
    }
    x
}

#[must_use]
pub fn derive_root_seed(
    base: u64,
    h: &[f32; FEATURES],
    hd: &[f32; FEATURES],
    entropy: f32,
    motion: f32,
    frame_index: u64,
) -> u64 {
    let mut state = splitmix64(base ^ frame_index.wrapping_mul(0x9e3779b97f4a7c15));

    for (idx, value) in h.iter().enumerate() {
        let q = ((*value).clamp(-4.0, 4.0) * 4096.0).round() as i32 as u32 as u64;
        state ^= splitmix64(q ^ ((idx as u64 + 1).wrapping_mul(0xd6e8feb86659fd93)));
        state = splitmix64(state);
    }

    for (idx, value) in hd.iter().enumerate() {
        let q = ((*value).clamp(-4.0, 4.0) * 4096.0).round() as i32 as u32 as u64;
        state ^= splitmix64(q ^ ((idx as u64 + 17).wrapping_mul(0xa0761d6478bd642f)));
        state = splitmix64(state);
    }

    let entropy_q = (entropy.clamp(0.0, 1.0) * 1_000_000.0).round() as u64;
    let motion_q = (motion.clamp(0.0, 1.0) * 1_000_000.0).round() as u64;

    splitmix64(state ^ entropy_q.rotate_left(11) ^ motion_q.rotate_left(29))
}

#[must_use]
pub fn ratio(numer: u64, denom: u64) -> f32 {
    if denom == 0 {
        0.0
    } else {
        (numer as f32 / denom as f32).clamp(0.0, 1.0)
    }
}

#[must_use]
pub fn cpu_spread(cpus: &[sysinfo::Cpu]) -> f32 {
    if cpus.is_empty() {
        return 0.0;
    }

    let inv_len = 1.0 / cpus.len() as f32;
    let mean = cpus.iter().map(|cpu| cpu.cpu_usage() / 100.0).sum::<f32>() * inv_len;

    let variance = cpus
        .iter()
        .map(|cpu| {
            let diff = cpu.cpu_usage() / 100.0 - mean;
            diff * diff
        })
        .sum::<f32>()
        * inv_len;

    variance.sqrt().clamp(0.0, 1.0)
}

#[must_use]
pub fn normalized_entropy(values: &[f32]) -> f32 {
    let mags: Vec<f32> = values.iter().map(|value| value.abs() + 1e-6).collect();
    let sum = mags.iter().sum::<f32>();
    if sum <= 0.0 {
        return 0.0;
    }

    let entropy = mags
        .iter()
        .map(|value| {
            let p = *value / sum;
            -p * p.ln()
        })
        .sum::<f32>();

    (entropy / (values.len() as f32).ln()).clamp(0.0, 1.0)
}

#[must_use]
pub fn rms(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    let mean_square = values.iter().map(|value| value * value).sum::<f32>() / values.len() as f32;
    mean_square.sqrt()
}

#[must_use]
pub fn mean_abs(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    values.iter().map(|value| value.abs()).sum::<f32>() / values.len() as f32
}

pub fn normalize<const N: usize>(values: &mut [f32; N]) {
    let sum = values.iter().sum::<f32>();
    if sum <= 0.0 {
        let uniform = 1.0 / N as f32;
        for value in values {
            *value = uniform;
        }
    } else {
        for value in values {
            *value /= sum;
        }
    }
}

#[must_use]
pub fn unit_from_u64(value: u64) -> f32 {
    let bits = (value >> 40) as u32;
    bits as f32 / ((1_u32 << 24) - 1) as f32
}

#[must_use]
pub fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9e3779b97f4a7c15);
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}

#[must_use]
pub fn log_norm(value: f32, scale: f32) -> f32 {
    if scale <= 0.0 {
        return 0.0;
    }
    (value.max(0.0).ln_1p() / scale.ln_1p()).clamp(0.0, 1.0)
}

#[must_use]
pub fn smooth(current: f32, target: f32, amount: f32) -> f32 {
    current + (target - current) * amount
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hadamard_projection_is_deterministic() {
        let input = [0.1, 0.2, 0.3, 0.4, -0.1, -0.2, 0.6, -0.4];
        assert_eq!(hadamard8(input), hadamard8(input));
    }

    #[test]
    fn projector_updates_seed_and_motion() {
        let mut projector = TelemetryProjector::new();
        let low = projector.update(TelemetrySnapshot {
            cpu: 0.1,
            cpu_imbalance: 0.05,
            mem: 0.2,
            swap: 0.0,
            process_density: 0.1,
            load: 0.2,
            net_flux: 0.0,
            disk_flux: 0.0,
        });
        let high = projector.update(TelemetrySnapshot {
            cpu: 0.9,
            cpu_imbalance: 0.7,
            mem: 0.8,
            swap: 0.4,
            process_density: 0.7,
            load: 0.9,
            net_flux: 0.8,
            disk_flux: 0.6,
        });
        assert_ne!(low.root_seed, high.root_seed);
        assert!(high.motion > 0.0);
        assert!(high.entropy >= 0.0 && high.entropy <= 1.0);
    }
}
