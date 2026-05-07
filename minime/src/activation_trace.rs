//! Read-only ESN activation trace export.
//!
//! The recorder samples the live reservoir state for diagnostics only. It
//! clones `esn.x`, summarizes it, and writes a bounded JSON ring without
//! mutating the reservoir or any controller path.

use serde::{Deserialize, Serialize};
use std::{collections::VecDeque, fs, path::Path};

pub const ACTIVATION_TRACE_POLICY: &str = "esn_activation_trace_v1";
pub const ACTIVATION_SAMPLE_INTERVAL_MS: u64 = 1_000;
pub const ACTIVATION_RETAINED_SECS: u64 = 180;
pub const ACTIVATION_MAX_FRAMES: usize = 180;
pub const ACTIVATION_TOP_NODE_COUNT: usize = 8;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct ActivationSummary {
    pub mean: f32,
    pub abs_mean: f32,
    pub rms: f32,
    pub min: f32,
    pub max: f32,
    pub saturation_fraction: f32,
    pub positive_fraction: f32,
    pub finite_fraction: f32,
}

impl Default for ActivationSummary {
    fn default() -> Self {
        Self {
            mean: 0.0,
            abs_mean: 0.0,
            rms: 0.0,
            min: 0.0,
            max: 0.0,
            saturation_fraction: 0.0,
            positive_fraction: 0.0,
            finite_fraction: 0.0,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct ActivationFrame {
    pub t_ms: u64,
    pub wall_clock_unix_ms: u64,
    pub fill_pct: f32,
    pub stage: String,
    pub geom_rel: f32,
    pub lambda1_rel: f32,
    pub summary: ActivationSummary,
    pub top_active_node_indexes: Vec<usize>,
    pub activations: Vec<f32>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct ActivationTrace {
    pub policy: &'static str,
    pub updated_at_unix_ms: u64,
    pub reservoir_dim: usize,
    pub sample_interval_ms: u64,
    pub retained_secs: u64,
    pub frames: Vec<ActivationFrame>,
}

#[derive(Clone, Debug, Default)]
pub struct ActivationTraceRecorder {
    frames: VecDeque<ActivationFrame>,
    last_sample_t_ms: Option<u64>,
    reservoir_dim: usize,
    updated_at_unix_ms: u64,
}

impl ActivationTraceRecorder {
    #[must_use]
    pub fn frame_count(&self) -> usize {
        self.frames.len()
    }

    #[must_use]
    pub fn snapshot(&self) -> ActivationTrace {
        ActivationTrace {
            policy: ACTIVATION_TRACE_POLICY,
            updated_at_unix_ms: self.updated_at_unix_ms,
            reservoir_dim: self.reservoir_dim,
            sample_interval_ms: ACTIVATION_SAMPLE_INTERVAL_MS,
            retained_secs: ACTIVATION_RETAINED_SECS,
            frames: self.frames.iter().cloned().collect(),
        }
    }

    pub fn maybe_sample(
        &mut self,
        t_ms: u64,
        wall_clock_unix_ms: u64,
        fill_pct: f32,
        stage: &str,
        geom_rel: f32,
        lambda1_rel: f32,
        activations: &[f32],
    ) -> bool {
        if self
            .last_sample_t_ms
            .is_some_and(|last| t_ms.saturating_sub(last) < ACTIVATION_SAMPLE_INTERVAL_MS)
        {
            return false;
        }

        let sanitized: Vec<f32> = activations
            .iter()
            .map(|value| if value.is_finite() { *value } else { 0.0 })
            .collect();
        let frame = ActivationFrame {
            t_ms,
            wall_clock_unix_ms,
            fill_pct: finite_or_zero(fill_pct),
            stage: stage.to_string(),
            geom_rel: finite_or_zero(geom_rel),
            lambda1_rel: finite_or_zero(lambda1_rel),
            summary: summarize_activations(activations),
            top_active_node_indexes: top_active_node_indexes(&sanitized, ACTIVATION_TOP_NODE_COUNT),
            activations: sanitized,
        };

        self.last_sample_t_ms = Some(t_ms);
        self.updated_at_unix_ms = wall_clock_unix_ms;
        self.reservoir_dim = activations.len();
        self.frames.push_back(frame);
        while self.frames.len() > ACTIVATION_MAX_FRAMES {
            self.frames.pop_front();
        }
        true
    }

    pub fn write_json(&self, path: &Path) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let tmp_path = path.with_extension("json.tmp");
        let bytes = serde_json::to_vec_pretty(&self.snapshot()).map_err(std::io::Error::other)?;
        fs::write(&tmp_path, bytes)?;
        fs::rename(tmp_path, path)?;
        Ok(())
    }
}

fn finite_or_zero(value: f32) -> f32 {
    if value.is_finite() {
        value
    } else {
        0.0
    }
}

fn summarize_activations(activations: &[f32]) -> ActivationSummary {
    if activations.is_empty() {
        return ActivationSummary::default();
    }

    let mut finite_count = 0usize;
    let mut sum = 0.0f32;
    let mut abs_sum = 0.0f32;
    let mut square_sum = 0.0f32;
    let mut min_value = f32::INFINITY;
    let mut max_value = f32::NEG_INFINITY;
    let mut saturation_count = 0usize;
    let mut positive_count = 0usize;

    for value in activations
        .iter()
        .copied()
        .filter(|value| value.is_finite())
    {
        finite_count = finite_count.saturating_add(1);
        sum += value;
        let abs_value = value.abs();
        abs_sum += abs_value;
        square_sum += value * value;
        min_value = min_value.min(value);
        max_value = max_value.max(value);
        if abs_value >= 0.95 {
            saturation_count = saturation_count.saturating_add(1);
        }
        if value > 0.0 {
            positive_count = positive_count.saturating_add(1);
        }
    }

    if finite_count == 0 {
        return ActivationSummary::default();
    }

    let finite_count_f = finite_count as f32;
    let total_count_f = activations.len() as f32;
    ActivationSummary {
        mean: sum / finite_count_f,
        abs_mean: abs_sum / finite_count_f,
        rms: (square_sum / finite_count_f).sqrt(),
        min: min_value,
        max: max_value,
        saturation_fraction: saturation_count as f32 / finite_count_f,
        positive_fraction: positive_count as f32 / finite_count_f,
        finite_fraction: finite_count_f / total_count_f,
    }
}

fn top_active_node_indexes(activations: &[f32], limit: usize) -> Vec<usize> {
    let mut indexed: Vec<(usize, f32)> = activations
        .iter()
        .enumerate()
        .map(|(index, value)| (index, value.abs()))
        .collect();
    indexed.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.0.cmp(&right.0))
    });
    indexed
        .into_iter()
        .take(limit)
        .map(|(index, _)| index)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn samples_at_one_hz_and_retains_bounded_ring() {
        let mut recorder = ActivationTraceRecorder::default();
        assert!(recorder.maybe_sample(0, 10, 68.0, "hold", 1.0, 0.98, &[0.1; 128]));
        assert!(!recorder.maybe_sample(999, 20, 68.0, "hold", 1.0, 0.98, &[0.2; 128]));

        for index in 1..=180u64 {
            let activation = (index as f32 / 180.0).min(1.0);
            assert!(recorder.maybe_sample(
                index * ACTIVATION_SAMPLE_INTERVAL_MS,
                10 + index,
                68.0,
                "hold",
                1.0,
                0.98,
                &vec![activation; 128],
            ));
        }

        let snapshot = recorder.snapshot();
        assert_eq!(snapshot.policy, ACTIVATION_TRACE_POLICY);
        assert_eq!(snapshot.sample_interval_ms, ACTIVATION_SAMPLE_INTERVAL_MS);
        assert_eq!(snapshot.retained_secs, ACTIVATION_RETAINED_SECS);
        assert_eq!(snapshot.reservoir_dim, 128);
        assert_eq!(snapshot.frames.len(), ACTIVATION_MAX_FRAMES);
        assert_eq!(
            snapshot.frames.first().map(|frame| frame.t_ms),
            Some(ACTIVATION_SAMPLE_INTERVAL_MS)
        );
    }

    #[test]
    fn summary_is_finite_and_top_indexes_are_abs_sorted() {
        let mut recorder = ActivationTraceRecorder::default();
        let activations = vec![0.2, -0.9, f32::NAN, 0.98, -0.97, 0.1];
        assert!(recorder.maybe_sample(0, 42, 68.0, "hold", 1.0, 0.98, &activations));

        let frame = recorder.snapshot().frames.remove(0);
        assert_eq!(frame.activations, vec![0.2, -0.9, 0.0, 0.98, -0.97, 0.1]);
        assert_eq!(&frame.top_active_node_indexes[..4], &[3, 4, 1, 0]);
        assert!(frame.summary.mean.is_finite());
        assert!(frame.summary.rms.is_finite());
        assert_eq!(frame.summary.finite_fraction, 5.0 / 6.0);
        assert_eq!(frame.summary.saturation_fraction, 2.0 / 5.0);
    }

    #[test]
    fn sampling_does_not_mutate_source_activation_vector() {
        let mut recorder = ActivationTraceRecorder::default();
        let activations = vec![0.1f32, -0.2, 0.3];
        let before = activations.clone();
        assert!(recorder.maybe_sample(0, 10, 68.0, "hold", 1.0, 0.98, &activations));
        assert_eq!(activations, before);
        assert_eq!(recorder.frame_count(), 1);
    }
}
