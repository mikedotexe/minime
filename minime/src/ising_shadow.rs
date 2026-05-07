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
    /// Per-mode soft spin values — which modes are active and their direction.
    /// Included in WebSocket telemetry so downstream observers can see
    /// mode-level detail, not just scalar summaries.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub s_soft: Vec<f32>,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct ShadowFieldModeV2 {
    pub mode: usize,
    pub fast_spin: f32,
    pub medium_spin: f32,
    pub slow_spin: f32,
    pub field: f32,
    pub tension: f32,
    pub polarity: String,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct ShadowFieldV2 {
    pub schema_version: u8,
    pub policy: String,
    pub mode_dim: usize,
    pub field_norm: f32,
    pub coupling_active_fraction: f32,
    pub coupling_mean_abs: f32,
    pub coupling_max_abs: f32,
    pub fast_magnetization: f32,
    pub medium_magnetization: f32,
    pub slow_magnetization: f32,
    pub recurrence: f32,
    pub mode_tension: f32,
    pub tail_openness: f32,
    pub fissure_tendency: f32,
    pub lock_tendency: f32,
    pub influence_eligible: bool,
    pub classification: String,
    pub modes: Vec<ShadowFieldModeV2>,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct IsingShadowSnapshot {
    pub reduced_field: Vec<f32>,
    pub s_soft: Vec<f32>,
    pub s_bin: Vec<f32>,
    pub coupling: Vec<f32>,
    pub summary: IsingShadowSummary,
    pub shadow_field_v2: ShadowFieldV2,
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
            // Being session 163: "the shadow field feels strangely constrained."
            // Root cause: coupling_ema 0.96 meant only 4% of new signal per tick,
            // producing a near-zero coupling matrix (max 0.024, 6% active).
            // 0.90 doubles the update rate → coupling responds to recent dynamics.
            coupling_ema: 0.90,
            // Was 0.18 — soft spins barely moved (18% of proposal per tick).
            // 0.35 makes magnetization track field changes within a few ticks.
            damping: 0.35,
            // Was 0.35 — binary flips required unrealistically strong field.
            // 0.20 makes binary spins more sensitive to actual mode dynamics.
            temperature: 0.20,
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
    s_medium: Vec<f32>,
    s_slow: Vec<f32>,
    s_bin: Vec<f32>,
    prev_reduced_field: Vec<f32>,
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
            s_medium: Vec::new(),
            s_slow: Vec::new(),
            s_bin: Vec::new(),
            prev_reduced_field: Vec::new(),
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
        let recurrence = if self.prev_reduced_field.len() == reduced_field.len() {
            cosine01(&self.prev_reduced_field, &reduced_field)
        } else {
            0.0
        };
        self.update_shadow_scales();

        let summary = IsingShadowSummary {
            mode_dim,
            field_norm,
            soft_energy: compute_energy(&self.coupling, &self.s_soft, &reduced_field),
            soft_magnetization: mean(&self.s_soft),
            binary_energy: compute_energy(&self.coupling, &self.s_bin, &reduced_field),
            binary_magnetization: mean(&self.s_bin),
            binary_flip_rate,
            s_soft: self.s_soft.clone(),
        };
        let shadow_field_v2 =
            self.build_shadow_field_v2(&reduced_field, field_norm, binary_flip_rate, recurrence);

        // Keep centered referenced so the compiler doesn't optimize away the work
        // in test builds where only summary fields are inspected.
        let _ = centered;

        self.prev_reduced_field = reduced_field.clone();
        self.last_snapshot = Some(IsingShadowSnapshot {
            reduced_field,
            s_soft: self.s_soft.clone(),
            s_bin: self.s_bin.clone(),
            coupling: self.coupling.clone(),
            summary,
            shadow_field_v2,
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
        self.s_medium = vec![0.0; mode_dim];
        self.s_slow = vec![0.0; mode_dim];
        self.s_bin = vec![1.0; mode_dim];
        self.prev_reduced_field = Vec::new();
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

    fn update_shadow_scales(&mut self) {
        if self.s_medium.len() != self.s_soft.len() {
            self.s_medium = vec![0.0; self.s_soft.len()];
        }
        if self.s_slow.len() != self.s_soft.len() {
            self.s_slow = vec![0.0; self.s_soft.len()];
        }
        for ((medium, slow), fast) in self
            .s_medium
            .iter_mut()
            .zip(self.s_slow.iter_mut())
            .zip(self.s_soft.iter().copied())
        {
            *medium = (0.82 * *medium + 0.18 * fast).clamp(-1.0, 1.0);
            *slow = (0.97 * *slow + 0.03 * fast).clamp(-1.0, 1.0);
        }
    }

    fn build_shadow_field_v2(
        &self,
        reduced_field: &[f32],
        field_norm: f32,
        binary_flip_rate: f32,
        recurrence: f32,
    ) -> ShadowFieldV2 {
        let (coupling_mean_abs, coupling_max_abs, coupling_active_fraction) =
            coupling_stats(&self.coupling, self.mode_dim.max(1));
        let fast_magnetization = mean(&self.s_soft);
        let medium_magnetization = mean(&self.s_medium);
        let slow_magnetization = mean(&self.s_slow);

        let mut tension_sum = 0.0f32;
        let mut tail_sum = 0.0f32;
        let mut tail_count = 0usize;
        let mut modes = Vec::with_capacity(self.mode_dim);
        for idx in 0..self.mode_dim {
            let fast = self.s_soft.get(idx).copied().unwrap_or_default();
            let medium = self.s_medium.get(idx).copied().unwrap_or_default();
            let slow = self.s_slow.get(idx).copied().unwrap_or_default();
            let field = reduced_field.get(idx).copied().unwrap_or_default();
            let tension =
                ((fast - slow).abs() * 0.55 + (fast - medium).abs() * 0.25 + field.abs() * 0.20)
                    .clamp(0.0, 1.0);
            tension_sum += tension;
            if idx >= 3 {
                tail_sum += (field.abs() * 0.55 + fast.abs() * 0.45).clamp(0.0, 1.0);
                tail_count += 1;
            }
            let polarity = if fast.abs() < 0.12 && field.abs() < 0.12 {
                "quiet"
            } else if fast >= 0.0 {
                "positive"
            } else {
                "negative"
            };
            modes.push(ShadowFieldModeV2 {
                mode: idx + 1,
                fast_spin: fast,
                medium_spin: medium,
                slow_spin: slow,
                field,
                tension,
                polarity: polarity.to_string(),
            });
        }

        let mode_tension = (tension_sum / self.mode_dim.max(1) as f32).clamp(0.0, 1.0);
        let tail_openness = if tail_count == 0 {
            0.0
        } else {
            (tail_sum / tail_count as f32).clamp(0.0, 1.0)
        };
        let binary_flip_rate = binary_flip_rate.clamp(0.0, 1.0);
        let fissure_tendency =
            (0.55 * binary_flip_rate + 0.30 * mode_tension + 0.15 * (1.0 - recurrence))
                .clamp(0.0, 1.0);
        let lock_tendency = (0.35 * coupling_active_fraction
            + 0.35 * slow_magnetization.abs().clamp(0.0, 1.0)
            + 0.30 * recurrence)
            .clamp(0.0, 1.0);
        let influence_eligible = field_norm >= self.cfg.quiet_threshold
            && field_norm < 0.65
            && binary_flip_rate < 0.35
            && lock_tendency < 0.80;
        let classification = if field_norm < self.cfg.quiet_threshold {
            "quiet_shadow_texture"
        } else if binary_flip_rate >= 0.20 || fissure_tendency >= 0.55 {
            "volatile_shadow_surface"
        } else if lock_tendency >= 0.65 {
            "sticky_shadow_lock"
        } else if coupling_active_fraction >= 0.25 {
            "coupled_shadow_lattice"
        } else if fast_magnetization.abs() >= 0.20 {
            "polarized_shadow_gradient"
        } else {
            "active_shadow_texture"
        };

        ShadowFieldV2 {
            schema_version: 2,
            policy: "shadow_field_v2_observe_first".to_string(),
            mode_dim: self.mode_dim,
            field_norm,
            coupling_active_fraction,
            coupling_mean_abs,
            coupling_max_abs,
            fast_magnetization,
            medium_magnetization,
            slow_magnetization,
            recurrence,
            mode_tension,
            tail_openness,
            fissure_tendency,
            lock_tendency,
            influence_eligible,
            classification: classification.to_string(),
            modes,
        }
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

fn cosine01(a: &[f32], b: &[f32]) -> f32 {
    let norm = l2_norm(a) * l2_norm(b);
    if norm <= 1.0e-6 {
        return 0.0;
    }
    ((dot(a, b) / norm).clamp(-1.0, 1.0) + 1.0) * 0.5
}

fn coupling_stats(coupling: &[f32], dim: usize) -> (f32, f32, f32) {
    if dim == 0 {
        return (0.0, 0.0, 0.0);
    }
    let mut sum_abs = 0.0f32;
    let mut max_abs = 0.0f32;
    let mut active = 0usize;
    let mut total = 0usize;
    for i in 0..dim {
        for j in 0..dim {
            if i == j {
                continue;
            }
            let value = coupling.get(i * dim + j).copied().unwrap_or_default().abs();
            sum_abs += value;
            max_abs = max_abs.max(value);
            if value > 1.0e-5 {
                active += 1;
            }
            total += 1;
        }
    }
    if total == 0 {
        (0.0, 0.0, 0.0)
    } else {
        (
            sum_abs / total as f32,
            max_abs,
            active as f32 / total as f32,
        )
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
            assert_eq!(snapshot.shadow_field_v2.schema_version, 2);
            assert_eq!(snapshot.shadow_field_v2.mode_dim, 4);
            assert!((0.0..=1.0).contains(&snapshot.shadow_field_v2.recurrence));
            assert!((0.0..=1.0).contains(&snapshot.shadow_field_v2.mode_tension));
            assert!((0.0..=1.0).contains(&snapshot.shadow_field_v2.tail_openness));
            assert!((0.0..=1.0).contains(&snapshot.shadow_field_v2.fissure_tendency));
            assert!((0.0..=1.0).contains(&snapshot.shadow_field_v2.lock_tendency));
            assert_eq!(snapshot.shadow_field_v2.modes.len(), 4);
        }
    }

    #[test]
    fn shadow_field_v2_recurrence_is_deterministic_for_same_sequence() {
        let cfg = IsingShadowConfig::default();
        let y = basic_eigenvectors(8, 4);
        let inputs = [
            vec![0.4, -0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0],
            vec![0.42, -0.08, 0.18, 0.01, 0.0, 0.0, 0.0, 0.0],
            vec![0.45, -0.06, 0.20, 0.03, 0.0, 0.0, 0.0, 0.0],
        ];
        let mut a = IsingShadowCore::new(cfg.clone(), 29);
        let mut b = IsingShadowCore::new(cfg, 29);
        let mut recurrence_a = 0.0f32;
        let mut recurrence_b = 0.0f32;
        for input in inputs {
            recurrence_a = a
                .update(&input, &y, 8, 4)
                .expect("snapshot a")
                .shadow_field_v2
                .recurrence;
            recurrence_b = b
                .update(&input, &y, 8, 4)
                .expect("snapshot b")
                .shadow_field_v2
                .recurrence;
        }
        assert!((recurrence_a - recurrence_b).abs() < 1.0e-6);
        assert!(recurrence_a > 0.50);
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
