use std::{env, path::PathBuf};

use crate::sensory_bus::{AUDIO_DIM, AUX_DIM, VIDEO_DIM, Z_DIM};

pub const STABLE_CORE_PROFILE: &str = "stable_core_v1";
pub const DEFAULT_AGENCY_STAGE: &str = "off";
pub const DEFAULT_AGENT_BUDGET_MODE: &str = "disabled";
pub const PINNED_RESCUE_INPUT_PATH: &str = "pinned_rescue_aux_projection";
pub const PINNED_RESCUE_ESN_PATH: &str = "pinned_rescue_direct";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StableCoreRuntime {
    pub enabled: bool,
    pub profile: String,
    pub agency_stage: String,
    pub agent_budget_mode: String,
    pub live_audio_divisor: u32,
    pub live_video_divisor: u32,
    pub live_intake_stages: Vec<String>,
    pub checkpoint_lineage_enabled: bool,
    pub neural_bundle_enabled: bool,
    pub rollback_reason: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StableCoreEsnPolicy {
    pub stochastic_cheby_perturbation: bool,
    pub exploration_noise_override: bool,
    pub dynamic_rho_modulation: bool,
    pub external_geom_noise: bool,
}

impl StableCoreEsnPolicy {
    #[must_use]
    pub const fn pinned_rescue_direct() -> Self {
        Self {
            stochastic_cheby_perturbation: false,
            exploration_noise_override: false,
            dynamic_rho_modulation: false,
            external_geom_noise: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct StableCoreProjection {
    pub projection_active: bool,
    pub input_path: &'static str,
    pub proj_input: Vec<f32>,
    pub activated_features: Vec<f32>,
    pub semantic_energy: f32,
    pub semantic_delta: f32,
    pub audio_rms: f32,
    pub video_var: f32,
}

#[must_use]
pub fn fixed_survival_aux_z(lambda1_rel: f32, geom_rel: f32, geom_clamp_hi: f32) -> [f32; Z_DIM] {
    let mut z = [0.0f32; Z_DIM];
    let lambda = if lambda1_rel.is_finite() {
        lambda1_rel.clamp(0.0, 4.0)
    } else {
        1.0
    };
    let geom_hi = if geom_clamp_hi.is_finite() {
        geom_clamp_hi.max(1.0)
    } else {
        4.0
    };
    let geom = if geom_rel.is_finite() {
        geom_rel.clamp(0.0, geom_hi)
    } else {
        1.0
    };
    let aux_start = VIDEO_DIM + AUDIO_DIM;
    z[aux_start] = lambda;
    z[aux_start + 1] = geom;
    z
}

#[must_use]
pub fn pinned_rescue_projection(
    z: &[f32; Z_DIM],
    dimension_scales: &[f32],
    activation_gain: f32,
    warmup_progress: f32,
) -> StableCoreProjection {
    let mut proj_input = vec![0.0f32; Z_DIM];
    let mut activated_features = vec![0.0f32; Z_DIM];
    let semantic_offset = VIDEO_DIM + AUDIO_DIM + AUX_DIM;

    normalize_slice(&z[..VIDEO_DIM], &mut proj_input[..VIDEO_DIM]);

    let audio_start = VIDEO_DIM;
    let audio_end = audio_start + AUDIO_DIM;
    normalize_slice(
        &z[audio_start..audio_end],
        &mut proj_input[audio_start..audio_end],
    );

    let aux_start = audio_end;
    let aux_end = semantic_offset;
    normalize_slice(&z[aux_start..aux_end], &mut proj_input[aux_start..aux_end]);

    // Stable-core proof mode deliberately ignores semantic carryover and
    // current-runtime semantic bias. Astrid may be present, but writes are not
    // allowed to shape the physiological kernel during Gate B.
    proj_input[semantic_offset..].fill(0.0);

    let warmup = warmup_progress.clamp(0.0, 1.0).max(0.2);
    for (idx, activated) in activated_features.iter_mut().enumerate() {
        let scale = dimension_scales.get(idx).copied().unwrap_or(1.0);
        let raw = proj_input[idx] * scale * activation_gain * warmup;
        *activated = raw.tanh();
    }

    let audio_rms = rms(&z[audio_start..audio_end]);
    let video_var = variance(&z[..VIDEO_DIM]);

    StableCoreProjection {
        projection_active: true,
        input_path: PINNED_RESCUE_INPUT_PATH,
        proj_input,
        activated_features,
        semantic_energy: 0.0,
        semantic_delta: 0.0,
        audio_rms,
        video_var,
    }
}

#[must_use]
pub fn project_covariance_vector(
    proj_matrix: &[f32],
    activated_features: &[f32],
    reservoir_dim: usize,
    sensory_dim: usize,
    proj_scale: f32,
) -> Option<Vec<f32>> {
    if sensory_dim == 0
        || reservoir_dim == 0
        || activated_features.len() < sensory_dim
        || proj_matrix.len() < reservoir_dim.checked_mul(sensory_dim)?
    {
        return None;
    }

    let mut cov_vec = vec![0.0f32; reservoir_dim];
    for (i, dst) in cov_vec.iter_mut().enumerate() {
        let row_start = i * sensory_dim;
        let mut acc = 0.0f32;
        for j in 0..sensory_dim {
            acc += proj_matrix[row_start + j] * activated_features[j];
        }
        *dst = acc * proj_scale;
    }
    Some(cov_vec)
}

fn normalize_slice(src: &[f32], dst: &mut [f32]) {
    let norm = rms(src);
    let scale = if norm > 1e-3 { 1.0 / norm } else { 1.0 };
    for (out, value) in dst.iter_mut().zip(src.iter()) {
        *out = *value * scale;
    }
}

fn rms(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    (values.iter().map(|v| v * v).sum::<f32>() / values.len() as f32).sqrt()
}

fn variance(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    let mean = values.iter().copied().sum::<f32>() / values.len() as f32;
    values
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta
        })
        .sum::<f32>()
        / values.len() as f32
}

impl StableCoreRuntime {
    #[must_use]
    pub fn from_env() -> Self {
        Self::from_lookup(|name| env::var(name).ok())
    }

    #[must_use]
    pub fn from_lookup<F>(lookup: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let runtime_profile = lookup("MINIME_RUNTIME_PROFILE")
            .or_else(|| lookup("MINIME_STABLE_CORE_PROFILE"))
            .or_else(|| lookup("MINIME_RESCUE_PROFILE"))
            .unwrap_or_else(|| "current".to_string());
        let enabled = flag_from_lookup(&lookup, "MINIME_STABLE_CORE", false)
            || runtime_profile == STABLE_CORE_PROFILE;
        let checkpoint_lineage_enabled = if enabled {
            flag_from_lookup(
                &lookup,
                "MINIME_STABLE_CORE_ENABLE_CHECKPOINT_LINEAGE",
                false,
            )
        } else {
            true
        };
        let neural_bundle_enabled = if enabled {
            flag_from_lookup(&lookup, "MINIME_STABLE_CORE_ENABLE_NEURAL_BUNDLE", false)
                && !flag_from_lookup(&lookup, "MINIME_RESCUE_DISABLE_NEURAL_BUNDLE", false)
        } else {
            !flag_from_lookup(&lookup, "MINIME_RESCUE_DISABLE_NEURAL_BUNDLE", false)
        };

        Self {
            enabled,
            profile: runtime_profile,
            agency_stage: lookup("MINIME_STABLE_CORE_AGENCY_STAGE")
                .unwrap_or_else(|| DEFAULT_AGENCY_STAGE.to_string()),
            agent_budget_mode: lookup("MINIME_STABLE_CORE_AGENT_BUDGET")
                .unwrap_or_else(|| DEFAULT_AGENT_BUDGET_MODE.to_string()),
            live_audio_divisor: u32_from_lookup(&lookup, "MINIME_RESCUE_LIVE_AUDIO_DIVISOR", 0),
            live_video_divisor: u32_from_lookup(&lookup, "MINIME_RESCUE_LIVE_VIDEO_DIVISOR", 0),
            live_intake_stages: csv_from_lookup(&lookup, "MINIME_RESCUE_LIVE_INTAKE_STAGES"),
            checkpoint_lineage_enabled,
            neural_bundle_enabled,
            rollback_reason: lookup("MINIME_STABLE_CORE_ROLLBACK_REASON"),
        }
    }

    #[must_use]
    pub fn allows_live_intake_for_stage(&self, stage: &str) -> bool {
        self.live_intake_stages
            .iter()
            .any(|candidate| candidate == stage)
    }

    #[must_use]
    pub fn stable_checkpoint_path(&self, workspace_dir: &std::path::Path) -> PathBuf {
        workspace_dir
            .join("stable_core")
            .join("spectral_checkpoint_stable_core.bin")
    }
}

fn u32_from_lookup<F>(lookup: &F, name: &str, default: u32) -> u32
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name)
        .and_then(|raw| raw.trim().parse::<u32>().ok())
        .unwrap_or(default)
}

fn csv_from_lookup<F>(lookup: &F, name: &str) -> Vec<String>
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name)
        .map(|raw| {
            raw.split(',')
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn flag_from_lookup<F>(lookup: &F, name: &str, default: bool) -> bool
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name).map_or(default, |raw| {
        !matches!(
            raw.trim().to_ascii_lowercase().as_str(),
            "0" | "false" | "off" | "no"
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn runtime(values: &[(&str, &str)]) -> StableCoreRuntime {
        let map: HashMap<&str, &str> = values.iter().copied().collect();
        StableCoreRuntime::from_lookup(|name| map.get(name).map(|value| (*value).to_string()))
    }

    #[test]
    fn stable_core_profile_enables_quarantine_defaults() {
        let runtime = runtime(&[("MINIME_RUNTIME_PROFILE", STABLE_CORE_PROFILE)]);

        assert!(runtime.enabled);
        assert!(!runtime.checkpoint_lineage_enabled);
        assert!(!runtime.neural_bundle_enabled);
        assert_eq!(runtime.agency_stage, DEFAULT_AGENCY_STAGE);
        assert_eq!(runtime.live_audio_divisor, 0);
    }

    #[test]
    fn stable_core_requires_explicit_lineage_and_neural_reenable() {
        let runtime = runtime(&[
            ("MINIME_RUNTIME_PROFILE", STABLE_CORE_PROFILE),
            ("MINIME_STABLE_CORE_ENABLE_CHECKPOINT_LINEAGE", "1"),
            ("MINIME_STABLE_CORE_ENABLE_NEURAL_BUNDLE", "true"),
            ("MINIME_STABLE_CORE_AGENCY_STAGE", "local_reflective"),
            ("MINIME_RESCUE_LIVE_AUDIO_DIVISOR", "4"),
            ("MINIME_RESCUE_LIVE_VIDEO_DIVISOR", "6"),
            ("MINIME_RESCUE_LIVE_INTAKE_STAGES", "hold,elevated"),
        ]);

        assert!(runtime.checkpoint_lineage_enabled);
        assert!(runtime.neural_bundle_enabled);
        assert_eq!(runtime.agency_stage, "local_reflective");
        assert_eq!(runtime.live_audio_divisor, 4);
        assert_eq!(runtime.live_video_divisor, 6);
        assert!(runtime.allows_live_intake_for_stage("hold"));
        assert!(!runtime.allows_live_intake_for_stage("recovery"));
    }

    #[test]
    fn pinned_projection_stays_active_with_aux_only_input() {
        let z = fixed_survival_aux_z(1.0, 1.0, 4.0);
        let projection = pinned_rescue_projection(&z, &vec![1.0; Z_DIM], 0.58, 0.0);

        assert!(projection.projection_active);
        assert_eq!(projection.input_path, PINNED_RESCUE_INPUT_PATH);
        assert!(projection.proj_input[..VIDEO_DIM].iter().all(|v| *v == 0.0));
        assert!(projection.proj_input[VIDEO_DIM..VIDEO_DIM + AUDIO_DIM]
            .iter()
            .all(|v| *v == 0.0));
        assert!(projection.proj_input[VIDEO_DIM + AUDIO_DIM] > 0.0);
        assert!(projection.proj_input[VIDEO_DIM + AUDIO_DIM + 1] > 0.0);
    }

    #[test]
    fn pinned_projection_zeros_semantics_and_bias_terms() {
        let mut z = fixed_survival_aux_z(1.2, 0.9, 4.0);
        let semantic_offset = VIDEO_DIM + AUDIO_DIM + AUX_DIM;
        for dim in &mut z[semantic_offset..] {
            *dim = 10.0;
        }

        let projection = pinned_rescue_projection(&z, &vec![1.0; Z_DIM], 0.58, 1.0);

        assert_eq!(projection.semantic_energy, 0.0);
        assert_eq!(projection.semantic_delta, 0.0);
        assert!(projection.proj_input
            [semantic_offset..semantic_offset + crate::sensory_bus::LLAVA_DIM]
            .iter()
            .all(|v| *v == 0.0));
        assert!(projection.activated_features
            [semantic_offset..semantic_offset + crate::sensory_bus::LLAVA_DIM]
            .iter()
            .all(|v| *v == 0.0));
    }

    #[test]
    fn pinned_projection_generates_covariance_vector_from_aux() {
        let z = fixed_survival_aux_z(1.0, 1.0, 4.0);
        let projection = pinned_rescue_projection(&z, &vec![1.0; Z_DIM], 0.58, 1.0);
        let reservoir_dim = 4;
        let sensory_dim = Z_DIM;
        let matrix = vec![1.0f32; reservoir_dim * sensory_dim];
        let cov = project_covariance_vector(
            &matrix,
            &projection.activated_features,
            reservoir_dim,
            sensory_dim,
            (1.0 / sensory_dim as f32).sqrt(),
        )
        .expect("valid covariance projection");

        assert_eq!(cov.len(), reservoir_dim);
        assert!(cov.iter().all(|v| *v > 0.0));
    }

    #[test]
    fn stable_core_esn_policy_disables_current_runtime_modulation() {
        let policy = StableCoreEsnPolicy::pinned_rescue_direct();

        assert!(!policy.stochastic_cheby_perturbation);
        assert!(!policy.exploration_noise_override);
        assert!(!policy.dynamic_rho_modulation);
        assert!(!policy.external_geom_noise);
    }
}
