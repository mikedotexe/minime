//! Reduced-mode Ising/Hamiltonian shadow core over the covariance/eigenfield layer.
//!
//! This is intentionally observer-only in v1. It does not influence regulation,
//! covariance updates, fill computation, or phase transitions. The goal is to
//! compare the current covariance/eigen geometry against a small energy-based
//! reduced field in parallel.

use fastrand::Rng;
use serde::Serialize;

#[derive(Debug, Clone, Serialize, Default)]
pub struct IsingShadowSummary {
    pub mode_dim: usize,
    pub field_norm: f32,
    pub soft_energy: f32,
    pub soft_magnetization: f32,
    pub binary_energy: f32,
    pub binary_magnetization: f32,
    pub binary_flip_rate: f32,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct IsingShadowSnapshot {
    pub reduced_field: Vec<f32>,
    pub s_soft: Vec<f32>,
    pub s_bin: Vec<f32>,
    pub coupling: Vec<f32>,
    pub summary: IsingShadowSummary,
    pub coupling_ema: f32,
    pub damping: f32,
    pub temperature: f32,
}

#[derive(Debug, Clone)]
pub struct IsingShadowConfig {
    pub max_modes: usize,
    pub coupling_ema: f32,
    pub damping: f32,
    pub temperature: f32,
    pub quiet_threshold: f32,
}

impl Default for IsingShadowConfig {
    fn default() -> Self {
        Self {
            max_modes: 8,
            coupling_ema: 0.96,
            damping: 0.18,
            temperature: 0.35,
            quiet_threshold: 0.05,
        }
    }
}

pub struct IsingShadowCore {
    cfg: IsingShadowConfig,
    mode_dim: usize,
    field_mean: Vec<f32>,
    coupling: Vec<f32>,
    s_soft: Vec<f32>,
    s_bin: Vec<f32>,
    last_snapshot: Option<IsingShadowSnapshot>,
    rng: Rng,
}

impl IsingShadowCore {
    pub fn new(cfg: IsingShadowConfig, seed: u64) -> Self {
        Self {
            cfg,
            mode_dim: 0,
            field_mean: Vec::new(),
            coupling: Vec::new(),
            s_soft: Vec::new(),
            s_bin: Vec::new(),
            last_snapshot: None,
            rng: Rng::with_seed(seed),
        }
    }

    pub fn update(
        &mut self,
        cov_input: &[f32],
        eigenvectors_col_major: &[f32],
        reservoir_dim: usize,
        eigenvector_count: usize,
    ) -> Option<&IsingShadowSnapshot> {
        let mode_dim = self
            .cfg
            .max_modes
            .min(eigenvector_count)
            .min(
                eigenvectors_col_major
                    .len()
                    .checked_div(reservoir_dim)
                    .unwrap_or(0),
            )
            .min(cov_input.len());
        if mode_dim == 0 || reservoir_dim == 0 {
            self.last_snapshot = None;
            return None;
        }

        self.ensure_dim(mode_dim);

        let reduced_field =
            project_field(cov_input, eigenvectors_col_major, reservoir_dim, mode_dim);
        let centered = self.update_coupling(&reduced_field);
        self.update_soft_spin(&reduced_field);
        let field_norm = l2_norm(&reduced_field) / (mode_dim as f32).sqrt().max(1.0);
        let binary_flip_rate = self.update_binary_spin(&reduced_field, field_norm);

        let summary = IsingShadowSummary {
            mode_dim,
            field_norm,
            soft_energy: compute_energy(&self.coupling, &self.s_soft, &reduced_field),
            soft_magnetization: mean(&self.s_soft),
            binary_energy: compute_energy(&self.coupling, &self.s_bin, &reduced_field),
            binary_magnetization: mean(&self.s_bin),
            binary_flip_rate,
        };

        // Keep centered referenced so the compiler doesn't optimize away the work
        // in test builds where only summary fields are inspected.
        let _ = centered;

        self.last_snapshot = Some(IsingShadowSnapshot {
            reduced_field,
            s_soft: self.s_soft.clone(),
            s_bin: self.s_bin.clone(),
            coupling: self.coupling.clone(),
            summary,
            coupling_ema: self.cfg.coupling_ema,
            damping: self.cfg.damping,
            temperature: self.cfg.temperature,
        });
        self.last_snapshot.as_ref()
    }

    fn ensure_dim(&mut self, mode_dim: usize) {
        if self.mode_dim == mode_dim {
            return;
        }
        self.mode_dim = mode_dim;
        self.field_mean = vec![0.0; mode_dim];
        self.coupling = vec![0.0; mode_dim * mode_dim];
        self.s_soft = vec![0.0; mode_dim];
        self.s_bin = vec![1.0; mode_dim];
        self.last_snapshot = None;
    }

    fn update_coupling(&mut self, field: &[f32]) -> Vec<f32> {
        let keep = self.cfg.coupling_ema.clamp(0.0, 0.9999);
        let update = 1.0 - keep;

        for (mean, value) in self.field_mean.iter_mut().zip(field.iter().copied()) {
            *mean = keep * *mean + update * value;
        }

        let centered: Vec<f32> = field
            .iter()
            .zip(self.field_mean.iter())
            .map(|(value, mean)| value - mean)
            .collect();

        for i in 0..self.mode_dim {
            for j in 0..self.mode_dim {
                let idx = i * self.mode_dim + j;
                self.coupling[idx] = keep * self.coupling[idx] + update * centered[i] * centered[j];
            }
        }

        for i in 0..self.mode_dim {
            for j in (i + 1)..self.mode_dim {
                let a = i * self.mode_dim + j;
                let b = j * self.mode_dim + i;
                let avg = 0.5 * (self.coupling[a] + self.coupling[b]);
                self.coupling[a] = avg;
                self.coupling[b] = avg;
            }
            self.coupling[i * self.mode_dim + i] = 0.0;
        }

        centered
    }

    fn update_soft_spin(&mut self, field: &[f32]) {
        let mut next = vec![0.0; self.mode_dim];
        let damping = self.cfg.damping.clamp(0.0, 1.0);
        for i in 0..self.mode_dim {
            let local = field[i] + row_dot(&self.coupling, self.mode_dim, i, &self.s_soft);
            let proposal = local.clamp(-8.0, 8.0).tanh();
            next[i] = ((1.0 - damping) * self.s_soft[i] + damping * proposal).clamp(-1.0, 1.0);
        }
        self.s_soft = next;
    }

    fn update_binary_spin(&mut self, field: &[f32], field_norm: f32) -> f32 {
        let mut flips = 0usize;
        let temp = self.cfg.temperature.max(0.05);
        let quiet_threshold = self.cfg.quiet_threshold.max(0.0);

        for i in 0..self.mode_dim {
            let local = field[i] + row_dot(&self.coupling, self.mode_dim, i, &self.s_bin);
            let prev = self.s_bin[i];
            let next = if field_norm < quiet_threshold {
                if local.abs() >= quiet_threshold * 2.0 {
                    if local >= 0.0 {
                        1.0
                    } else {
                        -1.0
                    }
                } else {
                    prev
                }
            } else if local.abs() < quiet_threshold {
                prev
            } else {
                let prob_pos = sigmoid(2.0 * local / temp);
                if self.rng.f32() < prob_pos {
                    1.0
                } else {
                    -1.0
                }
            };
            if (next - prev).abs() > f32::EPSILON {
                flips += 1;
            }
            self.s_bin[i] = next;
        }

        flips as f32 / self.mode_dim as f32
    }
}

fn project_field(
    cov_input: &[f32],
    eigenvectors_col_major: &[f32],
    reservoir_dim: usize,
    mode_dim: usize,
) -> Vec<f32> {
    let input_norm = l2_norm(cov_input).max(1e-6);
    let mut reduced = vec![0.0; mode_dim];

    for mode in 0..mode_dim {
        let start = mode * reservoir_dim;
        let end = start + reservoir_dim;
        if end > eigenvectors_col_major.len() {
            break;
        }
        let proj = dot(cov_input, &eigenvectors_col_major[start..end]) / input_norm;
        reduced[mode] = proj.clamp(-4.0, 4.0).tanh();
    }

    reduced
}

fn compute_energy(coupling: &[f32], spins: &[f32], field: &[f32]) -> f32 {
    let dim = spins.len();
    let mut pair_sum = 0.0f32;
    for i in 0..dim {
        for j in 0..dim {
            pair_sum += spins[i] * coupling[i * dim + j] * spins[j];
        }
    }
    let field_sum: f32 = spins.iter().zip(field.iter()).map(|(s, h)| s * h).sum();
    -0.5 * pair_sum - field_sum
}

fn row_dot(matrix: &[f32], dim: usize, row: usize, vec: &[f32]) -> f32 {
    let start = row * dim;
    let end = start + dim;
    dot(&matrix[start..end], vec)
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

fn l2_norm(values: &[f32]) -> f32 {
    values.iter().map(|v| v * v).sum::<f32>().sqrt()
}

fn mean(values: &[f32]) -> f32 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f32>() / values.len() as f32
    }
}

fn sigmoid(x: f32) -> f32 {
    let clamped = x.clamp(-20.0, 20.0);
    1.0 / (1.0 + (-clamped).exp())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn basic_eigenvectors(dim: usize, modes: usize) -> Vec<f32> {
        let mut y = vec![0.0; dim * modes];
        for mode in 0..modes {
            y[mode * dim + mode.min(dim - 1)] = 1.0;
        }
        y
    }

    #[test]
    fn initializes_cleanly_on_zero_input() {
        let cfg = IsingShadowConfig::default();
        let mut shadow = IsingShadowCore::new(cfg, 7);
        let cov_input = vec![0.0; 8];
        let y = basic_eigenvectors(8, 4);
        let snapshot = shadow.update(&cov_input, &y, 8, 4).expect("snapshot");
        assert_eq!(snapshot.summary.mode_dim, 4);
        assert!(snapshot.reduced_field.iter().all(|v| v.abs() <= 1.0));
        assert!(snapshot.s_soft.iter().all(|v| v.abs() <= 1.0));
        assert!(snapshot.s_bin.iter().all(|&v| v == -1.0 || v == 1.0));
    }

    #[test]
    fn coupling_remains_symmetric_and_zero_diagonal() {
        let cfg = IsingShadowConfig::default();
        let mut shadow = IsingShadowCore::new(cfg, 11);
        let y = basic_eigenvectors(8, 4);
        for _ in 0..12 {
            let cov_input = vec![0.6, -0.2, 0.3, 0.4, 0.0, 0.0, 0.0, 0.0];
            let _ = shadow.update(&cov_input, &y, 8, 4);
        }
        let dim = shadow.mode_dim;
        for i in 0..dim {
            assert_eq!(shadow.coupling[i * dim + i], 0.0);
            for j in (i + 1)..dim {
                let a = shadow.coupling[i * dim + j];
                let b = shadow.coupling[j * dim + i];
                assert!((a - b).abs() < 1e-6);
                assert!(a.is_finite());
            }
        }
    }

    #[test]
    fn constant_input_stays_finite_and_bounded() {
        let cfg = IsingShadowConfig::default();
        let mut shadow = IsingShadowCore::new(cfg, 17);
        let y = basic_eigenvectors(8, 4);
        for _ in 0..128 {
            let cov_input = vec![0.8, -0.3, 0.5, 0.1, 0.0, 0.0, 0.0, 0.0];
            let snapshot = shadow.update(&cov_input, &y, 8, 4).expect("snapshot");
            assert!(snapshot.summary.soft_energy.is_finite());
            assert!(snapshot.summary.binary_energy.is_finite());
            assert!(snapshot.s_soft.iter().all(|v| (-1.0..=1.0).contains(v)));
            assert!(snapshot.s_bin.iter().all(|&v| v == -1.0 || v == 1.0));
        }
    }

    #[test]
    fn zero_field_relaxes_toward_quiet() {
        let cfg = IsingShadowConfig::default();
        let mut shadow = IsingShadowCore::new(cfg, 23);
        let y = basic_eigenvectors(8, 4);
        let active = vec![0.7, 0.2, -0.5, 0.1, 0.0, 0.0, 0.0, 0.0];
        for _ in 0..16 {
            let _ = shadow.update(&active, &y, 8, 4);
        }
        let mut last_soft_mag = mean(&shadow.s_soft).abs();
        let mut last_flip = 1.0f32;
        for _ in 0..24 {
            let snapshot = shadow
                .update(&vec![0.0; 8], &y, 8, 4)
                .expect("quiet snapshot");
            assert!(snapshot.summary.field_norm <= 1e-6);
            assert!(snapshot.summary.binary_flip_rate <= last_flip + 1e-6);
            assert!(snapshot.summary.soft_magnetization.abs() <= last_soft_mag + 1e-6);
            last_flip = snapshot.summary.binary_flip_rate;
            last_soft_mag = snapshot.summary.soft_magnetization.abs();
        }
    }
}
