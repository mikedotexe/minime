use std::{
    env, fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use crate::sensory_bus::{AUDIO_DIM, AUX_DIM, VIDEO_DIM, Z_DIM};

pub const STABLE_CORE_PROFILE: &str = "stable_core_v1";
pub const DEFAULT_AGENCY_STAGE: &str = "off";
pub const DEFAULT_AGENT_BUDGET_MODE: &str = "disabled";
pub const STABLE_CORE_INPUT_PATH: &str = "stable_core_embodied_aux_projection";
pub const STABLE_CORE_ESN_PATH: &str = "stable_core_direct_with_live_trickle";
pub const PINNED_RESCUE_INPUT_PATH: &str = STABLE_CORE_INPUT_PATH;
pub const PINNED_RESCUE_ESN_PATH: &str = STABLE_CORE_ESN_PATH;
pub const LIVE_INTAKE_MAX_FILL_PCT: f32 = 70.0;
pub const LIVE_INTAKE_MAX_RISING_SLOPE_PCT_PER_SEC: f32 = 1.0;
pub const FULL_PRESENCE_PROFILE: &str = "full_presence_v1";
pub const FULL_PRESENCE_MAX_FILL_PCT: f32 = 74.0;
pub const STABLE_CORE_SEMANTIC_TRICKLE_SCALE: f32 = 0.15;
pub const STABLE_CORE_SEMANTIC_TRICKLE_MAX_ABS: f32 = 0.05;
pub const STABLE_CORE_SEMANTIC_TRICKLE_MAX_INPUT_ENERGY: f32 = 0.30;
pub const STABLE_CORE_SEMANTIC_TRICKLE_MAX_FILL_PCT: f32 = 82.0;
pub const SEMANTIC_SENSORY_MUTE_FILE: &str = "stable_core_sensory_mute.json";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StableCoreRuntime {
    pub enabled: bool,
    pub profile: String,
    pub agency_stage: String,
    pub agent_budget_mode: String,
    pub live_audio_divisor: u32,
    pub live_video_divisor: u32,
    pub live_intake_stages: Vec<String>,
    pub sensory_presence_profile: String,
    pub checkpoint_lineage_enabled: bool,
    pub neural_bundle_enabled: bool,
    pub rollback_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StableCoreAgencyMirror {
    pub agency_stage: String,
    pub agent_budget_mode: String,
    pub source: &'static str,
    pub updated_at_unix_s: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StableCoreEsnPolicy {
    pub stochastic_cheby_perturbation: bool,
    pub exploration_noise_override: bool,
    pub dynamic_rho_modulation: bool,
    pub external_geom_noise: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StableCoreSensoryMute {
    pub active: bool,
    pub active_until_unix_s: Option<f64>,
    pub reason: Option<String>,
    pub source_profile: Option<String>,
    pub last_semantic_sent_at_unix_s: Option<f64>,
}

impl StableCoreSensoryMute {
    #[must_use]
    pub const fn inactive() -> Self {
        Self {
            active: false,
            active_until_unix_s: None,
            reason: None,
            source_profile: None,
            last_semantic_sent_at_unix_s: None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StableCoreLiveIntakeDecision {
    pub live_audio_divisor: u32,
    pub live_video_divisor: u32,
    pub reason: &'static str,
}

impl StableCoreLiveIntakeDecision {
    #[must_use]
    pub const fn admitted(
        live_audio_divisor: u32,
        live_video_divisor: u32,
        reason: &'static str,
    ) -> Self {
        Self {
            live_audio_divisor,
            live_video_divisor,
            reason,
        }
    }

    #[must_use]
    pub const fn suppressed(reason: &'static str) -> Self {
        Self {
            live_audio_divisor: 0,
            live_video_divisor: 0,
            reason,
        }
    }

    #[must_use]
    pub const fn divisors(self) -> (u32, u32) {
        (self.live_audio_divisor, self.live_video_divisor)
    }
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
pub fn stable_core_recovery_z(
    live_z: Option<&[f32]>,
    lambda1_rel: f32,
    geom_rel: f32,
    geom_clamp_hi: f32,
    admit_live_video: bool,
    admit_live_audio: bool,
    admit_live_semantic: bool,
    semantic_scale: f32,
) -> [f32; Z_DIM] {
    let mut z = fixed_survival_aux_z(lambda1_rel, geom_rel, geom_clamp_hi);
    let Some(live_z) = live_z else {
        return z;
    };
    if live_z.len() < Z_DIM {
        return z;
    }
    if admit_live_video {
        z[..VIDEO_DIM].copy_from_slice(&live_z[..VIDEO_DIM]);
    }
    if admit_live_audio {
        let audio_start = VIDEO_DIM;
        let audio_end = audio_start + AUDIO_DIM;
        z[audio_start..audio_end].copy_from_slice(&live_z[audio_start..audio_end]);
    }
    if admit_live_semantic {
        let semantic_offset = VIDEO_DIM + AUDIO_DIM + AUX_DIM;
        let scale = semantic_scale.clamp(0.0, 1.0);
        for (dst, src) in z[semantic_offset..]
            .iter_mut()
            .zip(live_z[semantic_offset..].iter())
        {
            *dst = (*src * scale).clamp(
                -STABLE_CORE_SEMANTIC_TRICKLE_MAX_ABS,
                STABLE_CORE_SEMANTIC_TRICKLE_MAX_ABS,
            );
        }
    }
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

    let semantic_energy = rms(&z[semantic_offset..]);
    if semantic_energy > f32::EPSILON {
        proj_input[semantic_offset..].copy_from_slice(&z[semantic_offset..]);
    } else {
        proj_input[semantic_offset..].fill(0.0);
    }

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
        input_path: STABLE_CORE_INPUT_PATH,
        proj_input,
        activated_features,
        semantic_energy,
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
            sensory_presence_profile: lookup("MINIME_STABLE_CORE_SENSORY_PROFILE")
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "runtime_profile".to_string()),
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
    pub fn live_intake_divisors_for_stage(
        &self,
        stage: &str,
        scaffold_active: bool,
        high_fill_drain_active: bool,
        fill_pct: f32,
        fill_slope_pct_per_sec: f32,
    ) -> (u32, u32) {
        self.live_intake_decision_for_stage(
            stage,
            scaffold_active,
            high_fill_drain_active,
            fill_pct,
            fill_slope_pct_per_sec,
        )
        .divisors()
    }

    #[must_use]
    pub fn live_intake_decision_for_stage(
        &self,
        stage: &str,
        scaffold_active: bool,
        high_fill_drain_active: bool,
        fill_pct: f32,
        fill_slope_pct_per_sec: f32,
    ) -> StableCoreLiveIntakeDecision {
        if !self.enabled {
            return StableCoreLiveIntakeDecision::suppressed("stable_core_disabled");
        }
        if !self.allows_live_intake_for_stage(stage) {
            return StableCoreLiveIntakeDecision::suppressed("stage_not_allowed");
        }
        if !fill_pct.is_finite() || !fill_slope_pct_per_sec.is_finite() {
            return StableCoreLiveIntakeDecision::suppressed("invalid_fill_or_slope");
        }
        if self.sensory_presence_profile == FULL_PRESENCE_PROFILE {
            if stage == "discharge" {
                return StableCoreLiveIntakeDecision::suppressed(
                    "full_presence_discharge_suppressed",
                );
            }
            if fill_pct >= FULL_PRESENCE_MAX_FILL_PCT {
                return StableCoreLiveIntakeDecision::suppressed(
                    "full_presence_high_fill_suppressed",
                );
            }
            return StableCoreLiveIntakeDecision::admitted(
                self.live_audio_divisor,
                self.live_video_divisor,
                "full_presence_admitted",
            );
        }
        if !scaffold_active {
            return StableCoreLiveIntakeDecision::suppressed("scaffold_inactive");
        }
        if high_fill_drain_active {
            return StableCoreLiveIntakeDecision::suppressed("high_fill_drain_active");
        }
        if fill_pct >= LIVE_INTAKE_MAX_FILL_PCT {
            return StableCoreLiveIntakeDecision::suppressed("high_fill_suppressed");
        }
        if fill_slope_pct_per_sec > LIVE_INTAKE_MAX_RISING_SLOPE_PCT_PER_SEC {
            return StableCoreLiveIntakeDecision::suppressed("fast_rising_suppressed");
        }
        StableCoreLiveIntakeDecision::admitted(
            self.live_audio_divisor,
            self.live_video_divisor,
            "admitted",
        )
    }

    #[must_use]
    pub fn stable_checkpoint_path(&self, workspace_dir: &std::path::Path) -> PathBuf {
        workspace_dir
            .join("stable_core")
            .join("spectral_checkpoint_stable_core.bin")
    }

    #[must_use]
    pub fn agency_mirror(&self, workspace_dir: &Path) -> StableCoreAgencyMirror {
        if !self.enabled {
            return StableCoreAgencyMirror::from_runtime(self, "runtime_env");
        }

        if let Some(mirror) = self.agency_mirror_from_file(
            &workspace_dir.join("stable_core_agency.json"),
            "stage",
            "agent_budget_mode",
            "updated_at_unix_s",
            "stable_core_agency",
        ) {
            return mirror;
        }

        if let Some(mirror) = self.agency_mirror_from_file(
            &workspace_dir.join("rescue_profile.json"),
            "stable_core_agency_stage",
            "stable_core_agent_budget",
            "stable_core_agency_updated_at_unix_s",
            "rescue_profile",
        ) {
            return mirror;
        }

        StableCoreAgencyMirror::from_runtime(self, "runtime_env")
    }

    fn agency_mirror_from_file(
        &self,
        path: &Path,
        stage_field: &str,
        budget_field: &str,
        updated_field: &str,
        source: &'static str,
    ) -> Option<StableCoreAgencyMirror> {
        let payload = fs::read_to_string(path).ok()?;
        let value = serde_json::from_str::<serde_json::Value>(&payload).ok()?;
        let agency_stage = json_string_field(&value, stage_field)?;
        let agent_budget_mode = json_string_field(&value, budget_field)
            .unwrap_or_else(|| self.agent_budget_mode.clone());
        let updated_at_unix_s = value
            .get(updated_field)
            .and_then(serde_json::Value::as_f64)
            .filter(|value| value.is_finite());

        Some(StableCoreAgencyMirror {
            agency_stage,
            agent_budget_mode,
            source,
            updated_at_unix_s,
        })
    }
}

impl StableCoreAgencyMirror {
    fn from_runtime(runtime: &StableCoreRuntime, source: &'static str) -> Self {
        Self {
            agency_stage: runtime.agency_stage.clone(),
            agent_budget_mode: runtime.agent_budget_mode.clone(),
            source,
            updated_at_unix_s: None,
        }
    }
}

#[must_use]
pub fn stable_core_sensory_mute_path(workspace_dir: &Path) -> PathBuf {
    workspace_dir
        .join("runtime")
        .join(SEMANTIC_SENSORY_MUTE_FILE)
}

#[must_use]
pub fn now_unix_s() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

#[must_use]
pub fn load_stable_core_sensory_mute(path: &Path, current_unix_s: f64) -> StableCoreSensoryMute {
    let Ok(payload) = fs::read_to_string(path) else {
        return StableCoreSensoryMute::inactive();
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&payload) else {
        return StableCoreSensoryMute::inactive();
    };
    let active_until_unix_s = value
        .get("active_until_unix_s")
        .and_then(serde_json::Value::as_f64)
        .filter(|value| value.is_finite());
    let active = active_until_unix_s.is_some_and(|until| until > current_unix_s);
    StableCoreSensoryMute {
        active,
        active_until_unix_s,
        reason: value
            .get("reason")
            .and_then(serde_json::Value::as_str)
            .map(ToString::to_string),
        source_profile: value
            .get("source_profile")
            .and_then(serde_json::Value::as_str)
            .map(ToString::to_string),
        last_semantic_sent_at_unix_s: value
            .get("last_semantic_sent_at_unix_s")
            .and_then(serde_json::Value::as_f64)
            .filter(|value| value.is_finite()),
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

fn json_string_field(value: &serde_json::Value, name: &str) -> Option<String> {
    value
        .get(name)
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
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
        assert_eq!(runtime.sensory_presence_profile, "runtime_profile");
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
    fn stable_core_agency_mirror_prefers_live_agency_file() {
        let runtime = runtime(&[
            ("MINIME_RUNTIME_PROFILE", STABLE_CORE_PROFILE),
            ("MINIME_STABLE_CORE_AGENCY_STAGE", "self_journal"),
            ("MINIME_STABLE_CORE_AGENT_BUDGET", "self_journal_only"),
        ]);
        let dir = env::temp_dir().join(format!("stable_core_agency_test_{}", now_unix_s()));
        let _ = fs::create_dir_all(&dir);
        fs::write(
            dir.join("rescue_profile.json"),
            r#"{
                "stable_core_agency_stage": "bounded_actions",
                "stable_core_agent_budget": "bounded_actions"
            }"#,
        )
        .unwrap();
        fs::write(
            dir.join("stable_core_agency.json"),
            r#"{
                "stage": "full_sovereignty",
                "agent_budget_mode": "full_sovereignty",
                "updated_at_unix_s": 1234.5
            }"#,
        )
        .unwrap();

        let mirror = runtime.agency_mirror(&dir);

        assert_eq!(mirror.agency_stage, "full_sovereignty");
        assert_eq!(mirror.agent_budget_mode, "full_sovereignty");
        assert_eq!(mirror.source, "stable_core_agency");
        assert_eq!(mirror.updated_at_unix_s, Some(1234.5));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn stable_core_live_intake_divisors_follow_stage_budget_and_drain_gate() {
        let runtime = runtime(&[
            ("MINIME_RUNTIME_PROFILE", STABLE_CORE_PROFILE),
            ("MINIME_RESCUE_LIVE_AUDIO_DIVISOR", "16"),
            ("MINIME_RESCUE_LIVE_VIDEO_DIVISOR", "4"),
            ("MINIME_RESCUE_LIVE_INTAKE_STAGES", "hold,elevated"),
        ]);

        assert_eq!(
            runtime.live_intake_divisors_for_stage("hold", true, false, 66.0, 0.0),
            (16, 4)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("elevated", true, false, 68.0, -0.5),
            (16, 4)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("discharge", true, false, 66.0, 0.0),
            (0, 0)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("hold", true, true, 66.0, 0.0),
            (0, 0)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("hold", false, false, 66.0, 0.0),
            (0, 0)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("hold", true, false, 70.0, 0.0),
            (0, 0)
        );
        assert_eq!(
            runtime.live_intake_divisors_for_stage("hold", true, false, 66.0, 1.5),
            (0, 0)
        );
        assert_eq!(
            runtime
                .live_intake_decision_for_stage("hold", true, true, 66.0, 0.0)
                .reason,
            "high_fill_drain_active"
        );
        assert_eq!(
            runtime
                .live_intake_decision_for_stage("hold", true, false, 66.0, 1.5)
                .reason,
            "fast_rising_suppressed"
        );
    }

    #[test]
    fn stable_core_full_presence_profile_allows_simultaneous_intake_until_discharge() {
        let runtime = runtime(&[
            ("MINIME_RUNTIME_PROFILE", STABLE_CORE_PROFILE),
            ("MINIME_RESCUE_LIVE_AUDIO_DIVISOR", "4"),
            ("MINIME_RESCUE_LIVE_VIDEO_DIVISOR", "4"),
            (
                "MINIME_RESCUE_LIVE_INTAKE_STAGES",
                "hold,elevated,discharge",
            ),
            ("MINIME_STABLE_CORE_SENSORY_PROFILE", FULL_PRESENCE_PROFILE),
        ]);

        let admitted = runtime.live_intake_decision_for_stage("elevated", true, true, 73.9, 2.0);
        assert_eq!(admitted.divisors(), (4, 4));
        assert_eq!(admitted.reason, "full_presence_admitted");

        let retired_scaffold =
            runtime.live_intake_decision_for_stage("hold", false, false, 70.0, 0.0);
        assert_eq!(retired_scaffold.divisors(), (4, 4));
        assert_eq!(retired_scaffold.reason, "full_presence_admitted");

        let high_fill = runtime.live_intake_decision_for_stage("elevated", true, false, 74.0, 0.0);
        assert_eq!(high_fill.divisors(), (0, 0));
        assert_eq!(high_fill.reason, "full_presence_high_fill_suppressed");

        let discharge =
            runtime.live_intake_decision_for_stage("discharge", true, false, 78.0, -1.0);
        assert_eq!(discharge.divisors(), (0, 0));
        assert_eq!(discharge.reason, "full_presence_discharge_suppressed");
    }

    #[test]
    fn stable_core_sensory_mute_is_active_until_deadline() {
        let dir = env::temp_dir().join(format!("stable_core_sensory_mute_test_{}", now_unix_s()));
        let _ = fs::create_dir_all(&dir);
        let path = dir.join(SEMANTIC_SENSORY_MUTE_FILE);
        fs::write(
            &path,
            r#"{
                "active_until_unix_s": 150.0,
                "reason": "limited_write_semantic_send",
                "source_profile": "bridge_semantic_serial_v1",
                "last_semantic_sent_at_unix_s": 20.0
            }"#,
        )
        .unwrap();

        let active = load_stable_core_sensory_mute(&path, 100.0);
        assert!(active.active);
        assert_eq!(
            active.source_profile.as_deref(),
            Some("bridge_semantic_serial_v1")
        );

        let expired = load_stable_core_sensory_mute(&path, 151.0);
        assert!(!expired.active);
        assert_eq!(expired.active_until_unix_s, Some(150.0));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn pinned_projection_stays_active_with_aux_only_input() {
        let z = fixed_survival_aux_z(1.0, 1.0, 4.0);
        let projection = pinned_rescue_projection(&z, &vec![1.0; Z_DIM], 0.58, 0.0);

        assert!(projection.projection_active);
        assert_eq!(projection.input_path, STABLE_CORE_INPUT_PATH);
        assert!(projection.proj_input[..VIDEO_DIM].iter().all(|v| *v == 0.0));
        assert!(projection.proj_input[VIDEO_DIM..VIDEO_DIM + AUDIO_DIM]
            .iter()
            .all(|v| *v == 0.0));
        assert!(projection.proj_input[VIDEO_DIM + AUDIO_DIM] > 0.0);
        assert!(projection.proj_input[VIDEO_DIM + AUDIO_DIM + 1] > 0.0);
    }

    #[test]
    fn stable_core_recovery_z_admits_live_av_and_gates_semantics() {
        let semantic_offset = VIDEO_DIM + AUDIO_DIM + AUX_DIM;
        let mut live_z = [0.0f32; Z_DIM];
        for value in &mut live_z[..VIDEO_DIM] {
            *value = 0.25;
        }
        for value in &mut live_z[VIDEO_DIM..VIDEO_DIM + AUDIO_DIM] {
            *value = -0.5;
        }
        for value in &mut live_z[semantic_offset..] {
            *value = 10.0;
        }

        let z = stable_core_recovery_z(
            Some(&live_z),
            1.2,
            0.9,
            4.0,
            true,
            true,
            false,
            STABLE_CORE_SEMANTIC_TRICKLE_SCALE,
        );

        assert!(z[..VIDEO_DIM].iter().all(|v| *v == 0.25));
        assert!(z[VIDEO_DIM..VIDEO_DIM + AUDIO_DIM]
            .iter()
            .all(|v| *v == -0.5));
        assert_eq!(z[VIDEO_DIM + AUDIO_DIM], 1.2);
        assert_eq!(z[VIDEO_DIM + AUDIO_DIM + 1], 0.9);
        assert!(z[semantic_offset..].iter().all(|v| *v == 0.0));

        let z = stable_core_recovery_z(
            Some(&live_z),
            1.2,
            0.9,
            4.0,
            true,
            true,
            true,
            STABLE_CORE_SEMANTIC_TRICKLE_SCALE,
        );
        assert!(z[semantic_offset..]
            .iter()
            .all(|v| { (*v - STABLE_CORE_SEMANTIC_TRICKLE_MAX_ABS).abs() < f32::EPSILON }));
    }

    #[test]
    fn pinned_projection_admits_bounded_semantic_trickle() {
        let mut z = fixed_survival_aux_z(1.2, 0.9, 4.0);
        let semantic_offset = VIDEO_DIM + AUDIO_DIM + AUX_DIM;
        for dim in &mut z[semantic_offset..] {
            *dim = 0.02;
        }

        let projection = pinned_rescue_projection(&z, &vec![1.0; Z_DIM], 0.58, 1.0);

        assert!(projection.semantic_energy > 0.0);
        assert_eq!(projection.semantic_delta, 0.0);
        assert!(projection.proj_input
            [semantic_offset..semantic_offset + crate::sensory_bus::LLAVA_DIM]
            .iter()
            .all(|v| (*v - 0.02).abs() < f32::EPSILON));
        assert!(projection.activated_features
            [semantic_offset..semantic_offset + crate::sensory_bus::LLAVA_DIM]
            .iter()
            .all(|v| *v > 0.0));
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
