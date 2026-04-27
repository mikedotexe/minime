use crate::rescue_overfill::OverfillStage;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

const DIAGONAL_FLOOR: f32 = 1e-3;
const MODE_CAP_PASSES: usize = 8;
const MODE_CAP_POWER_ITERS: usize = 24;
pub const COLD_SCAFFOLD_PROFILE_VERSION: u32 = 5;
pub const COLD_SCAFFOLD_STABLE_WEIGHT: f32 = 0.0;
pub const COLD_SCAFFOLD_DIAGONAL_WEIGHT: f32 = 0.0;
pub const COLD_SCAFFOLD_RANK_COLD_WEIGHT: f32 = 1.0;
pub const COLD_SCAFFOLD_MODE_CAP: f32 = 1.15;
pub const COLD_SCAFFOLD_PROFILE: &str = "rank_cold_5of8_ladder_pure_v5";
pub const COLD_SCAFFOLD_ACTIVATION_POLICY: &str = "delay_until_hold_entry";
pub const SCAFFOLD_ACTIVATION_FILL_MIN: f32 = 58.0;
pub const SCAFFOLD_ACTIVATION_FILL_MAX: f32 = 72.0;
pub const STABILITY_PI_TARGET_FILL_PCT: f32 = 64.0;
pub const STABILITY_PI_DEADBAND_PCT: f32 = 2.0;
const STABILITY_PI_KP: f32 = 0.55;
const STABILITY_PI_KI: f32 = 0.04;
const STABILITY_PI_MAX_OUTPUT: f32 = 0.045;
const STABILITY_PI_INTEGRAL_DECAY: f32 = 0.85;
pub const STABILITY_PI_RECOVERY_IMPULSE_TRIGGER_PCT: f32 = STABILITY_PI_TARGET_FILL_PCT;
pub const STABILITY_PI_RECOVERY_SLOPE_TRIGGER_FILL_PCT: f32 = 68.0;
pub const STABILITY_PI_RECOVERY_SLOPE_TRIGGER_PCT_PER_SEC: f32 = -2.0;
pub const STABILITY_PI_LOW_FILL_TRIGGER_PCT: f32 = 55.0;
pub const STABILITY_PI_IMPULSE_MIN_TICKS: u32 = 2;
pub const STABILITY_PI_RELEASE_FILL_PCT: f32 = 60.0;
pub const STABILITY_PI_RELEASE_STRONG_FILL_PCT: f32 = 62.0;
pub const STABILITY_PI_RELEASE_STABLE_TICKS: u32 = 2;
pub const STABILITY_PI_REENTRY_TICKS: u32 = 12;
pub const STABILITY_PI_REENTRY_FALLBACK_FILL_PCT: f32 = 58.0;
pub const STABILITY_PI_REENTRY_SLOPE_FALLBACK_FILL_PCT: f32 = 62.0;
pub const STABILITY_PI_REENTRY_SLOPE_FALLBACK_PCT_PER_SEC: f32 = -1.5;
pub const STABILITY_PI_REENTRY_ELEVATED_FILL_PCT: f32 = 72.0;
const STABILITY_PI_SOFT_DRAIN_FILL_PCT: f32 = 68.0;
const STABILITY_PI_MODERATE_DRAIN_FILL_PCT: f32 = 72.0;
const STABILITY_PI_STRONG_DRAIN_FILL_PCT: f32 = 78.0;
const STABILITY_PI_SOFT_DRAIN: f32 = 0.015;
const STABILITY_PI_MODERATE_DRAIN: f32 = 0.030;
const STABILITY_PI_STRONG_DRAIN: f32 = 0.060;
const STABILITY_PI_FALLING_DRAIN_CAP: f32 = 0.015;
pub const STABLE_CORE_RECOVERY_IMPULSE_KEEP: f32 = 0.90;
pub const STABLE_CORE_RECOVERY_IMPULSE_TRACE_SCALE: f32 = 1.0;
pub const STABLE_CORE_SCAFFOLD_REENTRY_INITIAL_LIVE_WEIGHT: f32 = 0.55;
pub const STABLE_CORE_SCAFFOLD_REENTRY_FINAL_LIVE_WEIGHT: f32 = 0.20;
pub const SCAFFOLD_ACTIVATION_STABLE_FILL_MIN: f32 = 60.0;
pub const SCAFFOLD_ACTIVATION_STABLE_FILL_MAX: f32 = 66.0;
pub const SCAFFOLD_ACTIVATION_SLOPE_MAX_ABS: f32 = 3.0;
pub const SCAFFOLD_ACTIVATION_PROTECTIVE_DOWNSLOPE_PCT_PER_SEC: f32 = -3.0;
pub const SCAFFOLD_ACTIVATION_REQUIRED_TICKS: u32 = 2;
const RANK_COLD_SCAFFOLD_ACTIVE_MODES: usize = 5;
const RANK_COLD_DRAIN_ACTIVE_MODES: usize = 4;
const RANK_COLD_DRAIN_INACTIVE_FLOOR: f32 = 1e-3;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RescueScaffoldMetadata {
    pub source: String,
    pub matrix_dim: usize,
    pub trace: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub derived_from: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cold_profile: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub activation_policy: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mode_cap: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stable_weight: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diagonal_weight: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rank_cold_weight: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub activation_fill_band: Option<[f32; 2]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub captured_at_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub captured_fill_pct: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub captured_geom_rel: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub captured_stage: Option<String>,
}

#[derive(Debug, Clone)]
pub struct RescueScaffold {
    pub matrix: Vec<f32>,
    pub dim: usize,
    pub trace: f32,
    pub source: String,
    #[allow(dead_code)]
    pub loaded_at_unix_ms: u64,
    pub profile_version: Option<u32>,
    pub captured_at_unix_ms: Option<u64>,
    pub captured_fill_pct: Option<f32>,
    pub captured_geom_rel: Option<f32>,
    pub captured_stage: Option<String>,
    pub derived_from: Option<String>,
    pub cold_profile: Option<String>,
    pub activation_policy: Option<String>,
    pub mode_cap: Option<f32>,
    pub stable_weight: Option<f32>,
    pub diagonal_weight: Option<f32>,
    pub activation_fill_band: Option<[f32; 2]>,
}

impl RescueScaffold {
    fn from_parts(
        matrix: Vec<f32>,
        dim: usize,
        source: String,
        loaded_at_unix_ms: u64,
        profile_version: Option<u32>,
        captured_at_unix_ms: Option<u64>,
        captured_fill_pct: Option<f32>,
        captured_geom_rel: Option<f32>,
        captured_stage: Option<String>,
        derived_from: Option<String>,
        cold_profile: Option<String>,
        activation_policy: Option<String>,
        mode_cap: Option<f32>,
        stable_weight: Option<f32>,
        diagonal_weight: Option<f32>,
        activation_fill_band: Option<[f32; 2]>,
    ) -> Option<Self> {
        let (matrix, trace) = normalize_covariance_matrix(&matrix, dim)?;
        Some(Self {
            matrix,
            dim,
            trace,
            source,
            loaded_at_unix_ms,
            profile_version,
            captured_at_unix_ms,
            captured_fill_pct,
            captured_geom_rel,
            captured_stage,
            derived_from,
            cold_profile,
            activation_policy,
            mode_cap,
            stable_weight,
            diagonal_weight,
            activation_fill_band,
        })
    }

    #[must_use]
    pub fn is_current_dedicated_profile(&self) -> bool {
        if self.profile_version != Some(COLD_SCAFFOLD_PROFILE_VERSION)
            || self.activation_policy.as_deref() != Some(COLD_SCAFFOLD_ACTIVATION_POLICY)
        {
            return false;
        }

        if self.source == "captured_live" {
            return true;
        }

        self.source == "derived_cold_from_stable"
            && self.cold_profile.as_deref() == Some(COLD_SCAFFOLD_PROFILE)
            && self.mode_cap == Some(COLD_SCAFFOLD_MODE_CAP)
            && self.stable_weight == Some(COLD_SCAFFOLD_STABLE_WEIGHT)
            && self.diagonal_weight == Some(COLD_SCAFFOLD_DIAGONAL_WEIGHT)
    }
}

#[must_use]
pub fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| u64::try_from(duration.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or(0)
}

fn read_matrix(path: &Path, dim: usize) -> Option<Vec<f32>> {
    let bytes = fs::read(path).ok()?;
    if bytes.len() != dim.checked_mul(dim)?.checked_mul(4)? {
        return None;
    }
    let floats: Vec<f32> = bytes
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect();
    if floats.iter().all(|value| value.is_finite()) {
        Some(floats)
    } else {
        None
    }
}

fn read_metadata(path: &Path) -> Option<RescueScaffoldMetadata> {
    let json = fs::read_to_string(path).ok()?;
    serde_json::from_str::<RescueScaffoldMetadata>(&json).ok()
}

#[must_use]
pub fn load_scaffold(
    bin_path: &Path,
    metadata_path: Option<&Path>,
    dim: usize,
    default_source: &str,
    loaded_at_unix_ms: u64,
) -> Option<RescueScaffold> {
    let matrix = read_matrix(bin_path, dim)?;
    let metadata = metadata_path.and_then(read_metadata);
    let source = metadata
        .as_ref()
        .map(|meta| meta.source.clone())
        .unwrap_or_else(|| default_source.to_string());
    let captured_at_unix_ms = metadata.as_ref().and_then(|meta| meta.captured_at_unix_ms);
    let profile_version = metadata.as_ref().and_then(|meta| meta.profile_version);
    let captured_fill_pct = metadata.as_ref().and_then(|meta| meta.captured_fill_pct);
    let captured_geom_rel = metadata.as_ref().and_then(|meta| meta.captured_geom_rel);
    let captured_stage = metadata
        .as_ref()
        .and_then(|meta| meta.captured_stage.clone());
    let derived_from = metadata.as_ref().and_then(|meta| meta.derived_from.clone());
    let cold_profile = metadata.as_ref().and_then(|meta| meta.cold_profile.clone());
    let activation_policy = metadata
        .as_ref()
        .and_then(|meta| meta.activation_policy.clone());
    let mode_cap = metadata.as_ref().and_then(|meta| meta.mode_cap);
    let stable_weight = metadata.as_ref().and_then(|meta| meta.stable_weight);
    let diagonal_weight = metadata.as_ref().and_then(|meta| meta.diagonal_weight);
    let activation_fill_band = metadata.as_ref().and_then(|meta| meta.activation_fill_band);
    RescueScaffold::from_parts(
        matrix,
        dim,
        source,
        loaded_at_unix_ms,
        profile_version,
        captured_at_unix_ms,
        captured_fill_pct,
        captured_geom_rel,
        captured_stage,
        derived_from,
        cold_profile,
        activation_policy,
        mode_cap,
        stable_weight,
        diagonal_weight,
        activation_fill_band,
    )
}

#[allow(dead_code)]
pub fn archive_stale_scaffold_artifacts(
    bin_path: &Path,
    metadata_path: &Path,
    archive_root: &Path,
    archived_at_unix_ms: u64,
) -> Option<bool> {
    if !bin_path.exists() && !metadata_path.exists() {
        return Some(false);
    }
    let archive_dir = archive_root.join(format!("{archived_at_unix_ms}"));
    fs::create_dir_all(&archive_dir).ok()?;
    if bin_path.exists() {
        fs::copy(bin_path, archive_dir.join("rescue_scaffold.bin")).ok()?;
    }
    if metadata_path.exists() {
        fs::copy(metadata_path, archive_dir.join("rescue_scaffold.json")).ok()?;
    }
    Some(true)
}

fn write_scaffold_artifacts(
    scaffold: &RescueScaffold,
    bin_path: &Path,
    metadata_path: &Path,
) -> Option<()> {
    let mut bytes = Vec::with_capacity(scaffold.matrix.len() * 4);
    for value in &scaffold.matrix {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    fs::write(bin_path, bytes).ok()?;
    let metadata = RescueScaffoldMetadata {
        source: scaffold.source.clone(),
        matrix_dim: scaffold.dim,
        trace: scaffold.trace,
        profile_version: scaffold.profile_version,
        derived_from: scaffold.derived_from.clone(),
        cold_profile: scaffold.cold_profile.clone(),
        activation_policy: scaffold.activation_policy.clone(),
        mode_cap: scaffold.mode_cap,
        stable_weight: scaffold.stable_weight,
        diagonal_weight: scaffold.diagonal_weight,
        rank_cold_weight: if scaffold.cold_profile.as_deref() == Some(COLD_SCAFFOLD_PROFILE) {
            Some(COLD_SCAFFOLD_RANK_COLD_WEIGHT)
        } else {
            None
        },
        activation_fill_band: scaffold.activation_fill_band,
        captured_at_unix_ms: scaffold.captured_at_unix_ms,
        captured_fill_pct: scaffold.captured_fill_pct,
        captured_geom_rel: scaffold.captured_geom_rel,
        captured_stage: scaffold.captured_stage.clone(),
    };
    let json = serde_json::to_string_pretty(&metadata).ok()?;
    fs::write(metadata_path, json).ok()?;
    Some(())
}

pub fn capture_scaffold(
    matrix: &[f32],
    dim: usize,
    bin_path: &Path,
    metadata_path: &Path,
    fill_pct: f32,
    geom_rel: f32,
    stage: &str,
    captured_at_unix_ms: u64,
) -> Option<RescueScaffold> {
    let scaffold = RescueScaffold::from_parts(
        matrix.to_vec(),
        dim,
        "captured_live".to_string(),
        captured_at_unix_ms,
        Some(COLD_SCAFFOLD_PROFILE_VERSION),
        Some(captured_at_unix_ms),
        Some(fill_pct),
        Some(geom_rel),
        Some(stage.to_string()),
        None,
        None,
        Some(COLD_SCAFFOLD_ACTIVATION_POLICY.to_string()),
        None,
        None,
        None,
        Some([SCAFFOLD_ACTIVATION_FILL_MIN, SCAFFOLD_ACTIVATION_FILL_MAX]),
    )?;
    write_scaffold_artifacts(&scaffold, bin_path, metadata_path)?;
    Some(scaffold)
}

fn matvec(matrix: &[f32], vector: &[f32], dim: usize) -> Vec<f32> {
    let mut out = vec![0.0; dim];
    for row in 0..dim {
        let mut acc = 0.0;
        for col in 0..dim {
            acc += matrix[row * dim + col] * vector[col];
        }
        out[row] = acc;
    }
    out
}

fn normalize_vector(vector: &mut [f32]) -> bool {
    let norm = vector.iter().map(|value| value * value).sum::<f32>().sqrt();
    if !norm.is_finite() || norm <= 1e-9 {
        return false;
    }
    for value in vector {
        *value /= norm;
    }
    true
}

fn dominant_mode(matrix: &[f32], dim: usize) -> Option<(f32, Vec<f32>)> {
    if dim == 0 {
        return None;
    }
    let seed = 1.0 / (dim as f32).sqrt();
    let mut vector = vec![seed; dim];
    for _ in 0..MODE_CAP_POWER_ITERS {
        let mut next = matvec(matrix, &vector, dim);
        if !normalize_vector(&mut next) {
            return None;
        }
        vector = next;
    }
    let av = matvec(matrix, &vector, dim);
    let lambda = vector
        .iter()
        .zip(av.iter())
        .map(|(v, av)| v * av)
        .sum::<f32>();
    if lambda.is_finite() {
        Some((lambda, vector))
    } else {
        None
    }
}

fn cap_dominant_modes(matrix: &[f32], dim: usize, mode_cap: f32) -> Option<Vec<f32>> {
    let (mut capped, _) = normalize_covariance_matrix(matrix, dim)?;
    for _ in 0..MODE_CAP_PASSES {
        let (lambda, vector) = dominant_mode(&capped, dim)?;
        if lambda <= mode_cap {
            break;
        }
        let excess = lambda - mode_cap;
        for row in 0..dim {
            for col in 0..dim {
                capped[row * dim + col] -= excess * vector[row] * vector[col];
            }
        }
        let (normalized, _) = normalize_covariance_matrix(&capped, dim)?;
        capped = normalized;
    }
    Some(capped)
}

pub fn derive_cold_scaffold(
    stable_scaffold: &RescueScaffold,
    bin_path: &Path,
    metadata_path: &Path,
    derived_at_unix_ms: u64,
    derived_from: &str,
) -> Option<RescueScaffold> {
    let rank_cold = rank_cold_matrix(stable_scaffold.dim, RANK_COLD_SCAFFOLD_ACTIVE_MODES);
    let blended: Vec<f32> = rank_cold
        .iter()
        .map(|rank_cold| COLD_SCAFFOLD_RANK_COLD_WEIGHT * *rank_cold)
        .collect();
    let blended = cap_dominant_modes(&blended, stable_scaffold.dim, COLD_SCAFFOLD_MODE_CAP)?;
    let scaffold = RescueScaffold::from_parts(
        blended,
        stable_scaffold.dim,
        "derived_cold_from_stable".to_string(),
        derived_at_unix_ms,
        Some(COLD_SCAFFOLD_PROFILE_VERSION),
        None,
        None,
        None,
        None,
        Some(derived_from.to_string()),
        Some(COLD_SCAFFOLD_PROFILE.to_string()),
        Some(COLD_SCAFFOLD_ACTIVATION_POLICY.to_string()),
        Some(COLD_SCAFFOLD_MODE_CAP),
        Some(COLD_SCAFFOLD_STABLE_WEIGHT),
        Some(COLD_SCAFFOLD_DIAGONAL_WEIGHT),
        Some([SCAFFOLD_ACTIVATION_FILL_MIN, SCAFFOLD_ACTIVATION_FILL_MAX]),
    )?;
    write_scaffold_artifacts(&scaffold, bin_path, metadata_path)?;
    Some(scaffold)
}

#[must_use]
pub fn scaffold_live_weight(stage: OverfillStage) -> f32 {
    match stage {
        OverfillStage::Bootstrap => 1.0,
        OverfillStage::Recovery => 0.0,
        OverfillStage::Hold => 0.0,
        OverfillStage::Elevated => 0.0,
        OverfillStage::Discharge => 0.0,
    }
}

#[must_use]
pub fn base_scaffold_drain_weight(stage: OverfillStage) -> f32 {
    match stage {
        OverfillStage::Bootstrap | OverfillStage::Recovery => 0.0,
        OverfillStage::Hold | OverfillStage::Elevated | OverfillStage::Discharge => 0.0,
    }
}

#[must_use]
pub fn scaffold_reentry_live_weight(reentry_ticks: u32) -> f32 {
    if reentry_ticks == 0 || reentry_ticks > STABILITY_PI_REENTRY_TICKS {
        return 0.0;
    }
    let completed = reentry_ticks
        .saturating_sub(1)
        .min(STABILITY_PI_REENTRY_TICKS);
    let span = STABILITY_PI_REENTRY_TICKS.saturating_sub(1).max(1) as f32;
    let progress = (completed as f32 / span).clamp(0.0, 1.0);
    let live_weight = STABLE_CORE_SCAFFOLD_REENTRY_INITIAL_LIVE_WEIGHT
        + (STABLE_CORE_SCAFFOLD_REENTRY_FINAL_LIVE_WEIGHT
            - STABLE_CORE_SCAFFOLD_REENTRY_INITIAL_LIVE_WEIGHT)
            * progress;
    live_weight.clamp(0.0, 1.0)
}

#[must_use]
pub fn stable_core_scaffold_activation_delay_reason(
    stage: OverfillStage,
    fill_pct: f32,
    fill_slope_pct_per_sec: f32,
    semantic_active: bool,
    live_audio_divisor: u32,
    live_video_divisor: u32,
) -> &'static str {
    if !matches!(stage, OverfillStage::Hold) {
        return "stage_not_hold";
    }
    if !(SCAFFOLD_ACTIVATION_STABLE_FILL_MIN..=SCAFFOLD_ACTIVATION_STABLE_FILL_MAX)
        .contains(&fill_pct)
    {
        return "fill_out_of_activation_band";
    }
    if !fill_slope_pct_per_sec.is_finite()
        || fill_slope_pct_per_sec.abs() > SCAFFOLD_ACTIVATION_SLOPE_MAX_ABS
    {
        if fill_slope_pct_per_sec <= SCAFFOLD_ACTIVATION_PROTECTIVE_DOWNSLOPE_PCT_PER_SEC {
            return "protective_downslope_candidate";
        }
        return "fill_slope_too_fast";
    }
    if semantic_active {
        return "semantic_active";
    }
    if live_audio_divisor != 0 || live_video_divisor != 0 {
        return "live_intake_enabled";
    }
    "candidate"
}

#[must_use]
pub fn normalize_covariance_matrix(matrix: &[f32], dim: usize) -> Option<(Vec<f32>, f32)> {
    if matrix.len() != dim.checked_mul(dim)? || !matrix.iter().all(|value| value.is_finite()) {
        return None;
    }

    let mut normalized = matrix.to_vec();
    for i in 0..dim {
        for j in (i + 1)..dim {
            let idx_ij = i * dim + j;
            let idx_ji = j * dim + i;
            let avg = 0.5 * (normalized[idx_ij] + normalized[idx_ji]);
            normalized[idx_ij] = avg;
            normalized[idx_ji] = avg;
        }
        let diag_idx = i * dim + i;
        normalized[diag_idx] = normalized[diag_idx].max(DIAGONAL_FLOOR);
    }

    let trace = (0..dim).map(|idx| normalized[idx * dim + idx]).sum::<f32>();
    if !trace.is_finite() || trace <= 0.0 {
        return None;
    }
    let target_trace = dim as f32;
    let scale = target_trace / trace;
    for value in &mut normalized {
        *value *= scale;
    }
    Some((normalized, target_trace))
}

#[cfg(test)]
#[must_use]
pub fn blend_toward_scaffold(
    live_matrix: &[f32],
    scaffold: &RescueScaffold,
    live_weight: f32,
) -> Option<Vec<f32>> {
    if live_matrix.len() != scaffold.matrix.len() || scaffold.dim == 0 {
        return None;
    }
    let (normalized_live, _) = normalize_covariance_matrix(live_matrix, scaffold.dim)?;
    let live_weight = live_weight.clamp(0.0, 1.0);
    let scaffold_weight = 1.0 - live_weight;
    let blended: Vec<f32> = normalized_live
        .iter()
        .zip(scaffold.matrix.iter())
        .map(|(live, anchor)| live_weight * *live + scaffold_weight * *anchor)
        .collect();
    let (normalized, _) = normalize_covariance_matrix(&blended, scaffold.dim)?;
    Some(normalized)
}

#[must_use]
fn rank_cold_matrix(dim: usize, requested_active_modes: usize) -> Vec<f32> {
    let mut matrix = vec![0.0; dim * dim];
    let active_modes = requested_active_modes.min(dim);
    for idx in 0..dim {
        matrix[idx * dim + idx] = if idx < active_modes {
            1.0 - 0.04 * idx as f32
        } else {
            RANK_COLD_DRAIN_INACTIVE_FLOOR
        };
    }
    normalize_covariance_matrix(&matrix, dim)
        .map(|(normalized, _)| normalized)
        .unwrap_or(matrix)
}

#[must_use]
pub fn rank_cold_drain_matrix(dim: usize) -> Vec<f32> {
    rank_cold_matrix(dim, RANK_COLD_DRAIN_ACTIVE_MODES)
}

#[must_use]
pub fn blend_toward_scaffold_with_drain(
    live_matrix: &[f32],
    scaffold: &RescueScaffold,
    live_weight: f32,
    drain_weight: f32,
) -> Option<Vec<f32>> {
    if live_matrix.len() != scaffold.matrix.len() || scaffold.dim == 0 {
        return None;
    }
    let (normalized_live, _) = normalize_covariance_matrix(live_matrix, scaffold.dim)?;
    let live_weight = live_weight.clamp(0.0, 1.0);
    let drain_weight = drain_weight.clamp(0.0, 1.0 - live_weight);
    let scaffold_weight = 1.0 - live_weight - drain_weight;
    let drain = rank_cold_drain_matrix(scaffold.dim);
    let blended: Vec<f32> = normalized_live
        .iter()
        .zip(scaffold.matrix.iter())
        .zip(drain.iter())
        .map(|((live, anchor), drain)| {
            live_weight * *live + scaffold_weight * *anchor + drain_weight * *drain
        })
        .collect();
    let (normalized, _) = normalize_covariance_matrix(&blended, scaffold.dim)?;
    Some(normalized)
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StabilityPiOutput {
    pub active: bool,
    pub target_fill_pct: f32,
    pub error_pct: f32,
    pub integral: f32,
    pub pi_output: f32,
    pub drain_weight: f32,
    pub damping_state: &'static str,
    pub drain_gate_reason: &'static str,
    pub drain_suppressed_by_slope: bool,
    pub fill_slope_pct_per_sec: f32,
    pub low_fill_escape_active: bool,
    pub high_fill_drain_active: bool,
    pub recovery_impulse_active: bool,
    pub recovery_impulse_ticks: u32,
    pub recovery_impulse_keep: f32,
    pub recovery_impulse_trace_scale: f32,
    pub reentry_active: bool,
    pub reentry_ticks: u32,
    pub reentry_live_weight: f32,
}

impl StabilityPiOutput {
    #[must_use]
    pub fn inactive(integral: f32) -> Self {
        Self {
            active: false,
            target_fill_pct: STABILITY_PI_TARGET_FILL_PCT,
            error_pct: 0.0,
            integral,
            pi_output: 0.0,
            drain_weight: 0.0,
            damping_state: "inactive",
            drain_gate_reason: "inactive",
            drain_suppressed_by_slope: false,
            fill_slope_pct_per_sec: 0.0,
            low_fill_escape_active: false,
            high_fill_drain_active: false,
            recovery_impulse_active: false,
            recovery_impulse_ticks: 0,
            recovery_impulse_keep: 0.0,
            recovery_impulse_trace_scale: 0.0,
            reentry_active: false,
            reentry_ticks: 0,
            reentry_live_weight: 0.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StabilityPiState {
    pub integral: f32,
    pub low_fill_escape_active: bool,
    pub high_fill_drain_active: bool,
    pub recovery_impulse_ticks: u32,
    release_candidate_ticks: u32,
    pub reentry_active: bool,
    pub reentry_ticks: u32,
}

impl Default for StabilityPiState {
    fn default() -> Self {
        Self {
            integral: 0.0,
            low_fill_escape_active: false,
            high_fill_drain_active: false,
            recovery_impulse_ticks: 0,
            release_candidate_ticks: 0,
            reentry_active: false,
            reentry_ticks: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct DrainPolicy {
    weight: f32,
    damping_state: &'static str,
    reason: &'static str,
    suppressed_by_slope: bool,
    high_fill_active: bool,
}

fn stable_core_drain_policy(
    fill_pct: f32,
    fill_slope_pct_per_sec: f32,
    pi_output: f32,
) -> DrainPolicy {
    if !fill_pct.is_finite() || !fill_slope_pct_per_sec.is_finite() {
        return DrainPolicy {
            weight: 0.0,
            damping_state: "invalid_fill_or_slope",
            reason: "invalid_fill_or_slope",
            suppressed_by_slope: false,
            high_fill_active: false,
        };
    }
    if fill_pct < STABILITY_PI_SOFT_DRAIN_FILL_PCT {
        return DrainPolicy {
            weight: 0.0,
            damping_state: "none",
            reason: "below_soft_drain_band",
            suppressed_by_slope: false,
            high_fill_active: false,
        };
    }
    if fill_pct >= STABILITY_PI_STRONG_DRAIN_FILL_PCT {
        return DrainPolicy {
            weight: pi_output.max(STABILITY_PI_STRONG_DRAIN).clamp(0.0, 1.0),
            damping_state: "strong_drain",
            reason: "strong_high_fill",
            suppressed_by_slope: false,
            high_fill_active: true,
        };
    }
    if fill_pct >= STABILITY_PI_MODERATE_DRAIN_FILL_PCT {
        if fill_slope_pct_per_sec < 0.0 {
            return DrainPolicy {
                weight: pi_output
                    .min(STABILITY_PI_FALLING_DRAIN_CAP)
                    .clamp(0.0, 1.0),
                damping_state: "moderate_drain_capped",
                reason: "falling_slope_capped",
                suppressed_by_slope: true,
                high_fill_active: false,
            };
        }
        return DrainPolicy {
            weight: pi_output.max(STABILITY_PI_MODERATE_DRAIN).clamp(0.0, 1.0),
            damping_state: "moderate_drain",
            reason: "moderate_high_fill_rising",
            suppressed_by_slope: false,
            high_fill_active: false,
        };
    }
    if fill_slope_pct_per_sec > 0.0 {
        return DrainPolicy {
            weight: STABILITY_PI_SOFT_DRAIN,
            damping_state: "soft_drain",
            reason: "soft_high_fill_rising",
            suppressed_by_slope: false,
            high_fill_active: false,
        };
    }
    DrainPolicy {
        weight: 0.0,
        damping_state: "soft_drain_suppressed",
        reason: "falling_slope_suppressed",
        suppressed_by_slope: true,
        high_fill_active: false,
    }
}

impl StabilityPiState {
    #[must_use]
    pub fn step(
        &mut self,
        fill_pct: f32,
        fill_slope_pct_per_sec: f32,
        stage: OverfillStage,
        scaffold_active: bool,
    ) -> StabilityPiOutput {
        if !scaffold_active || !fill_pct.is_finite() {
            self.integral *= STABILITY_PI_INTEGRAL_DECAY;
            self.high_fill_drain_active = false;
            self.low_fill_escape_active = false;
            self.recovery_impulse_ticks = 0;
            self.release_candidate_ticks = 0;
            self.reentry_active = false;
            self.reentry_ticks = 0;
            return StabilityPiOutput::inactive(self.integral);
        }

        self.high_fill_drain_active = fill_pct >= STABILITY_PI_STRONG_DRAIN_FILL_PCT;

        if fill_pct >= STABILITY_PI_REENTRY_ELEVATED_FILL_PCT {
            self.low_fill_escape_active = false;
            self.recovery_impulse_ticks = 0;
            self.release_candidate_ticks = 0;
            self.reentry_active = false;
            self.reentry_ticks = 0;
        }

        if self.reentry_active {
            let steep_reentry_downslope = fill_pct < STABILITY_PI_REENTRY_SLOPE_FALLBACK_FILL_PCT
                && fill_slope_pct_per_sec < STABILITY_PI_REENTRY_SLOPE_FALLBACK_PCT_PER_SEC;
            if fill_pct < STABILITY_PI_REENTRY_FALLBACK_FILL_PCT || steep_reentry_downslope {
                self.reentry_active = false;
                self.reentry_ticks = 0;
                self.low_fill_escape_active = true;
                self.recovery_impulse_ticks = 0;
                self.release_candidate_ticks = 0;
            } else {
                self.reentry_ticks = self.reentry_ticks.saturating_add(1);
                if self.reentry_ticks <= STABILITY_PI_REENTRY_TICKS {
                    return self.reentry_output(fill_pct, fill_slope_pct_per_sec);
                }
                self.reentry_active = false;
                self.reentry_ticks = 0;
            }
        }

        let slope_trigger = fill_pct < STABILITY_PI_RECOVERY_SLOPE_TRIGGER_FILL_PCT
            && fill_slope_pct_per_sec < STABILITY_PI_RECOVERY_SLOPE_TRIGGER_PCT_PER_SEC;
        let fill_trigger = fill_pct < STABILITY_PI_RECOVERY_IMPULSE_TRIGGER_PCT;
        if fill_trigger || slope_trigger {
            if !self.low_fill_escape_active {
                self.recovery_impulse_ticks = 0;
                self.release_candidate_ticks = 0;
            }
            self.low_fill_escape_active = true;
            self.integral = 0.0;
        }

        if self.low_fill_escape_active {
            self.recovery_impulse_ticks = self.recovery_impulse_ticks.saturating_add(1);
            let release_on_slope =
                fill_pct >= STABILITY_PI_RELEASE_FILL_PCT && fill_slope_pct_per_sec >= 0.0;
            if release_on_slope {
                self.release_candidate_ticks = self.release_candidate_ticks.saturating_add(1);
            } else {
                self.release_candidate_ticks = 0;
            }
            let release_allowed = self.recovery_impulse_ticks >= STABILITY_PI_IMPULSE_MIN_TICKS
                && (fill_pct >= STABILITY_PI_RELEASE_STRONG_FILL_PCT
                    || self.release_candidate_ticks >= STABILITY_PI_RELEASE_STABLE_TICKS);
            if release_allowed {
                self.low_fill_escape_active = false;
                self.recovery_impulse_ticks = 0;
                self.release_candidate_ticks = 0;
                self.reentry_active = true;
                self.reentry_ticks = 1;
                return self.reentry_output(fill_pct, fill_slope_pct_per_sec);
            }
            return StabilityPiOutput {
                active: true,
                target_fill_pct: STABILITY_PI_TARGET_FILL_PCT,
                error_pct: fill_pct - STABILITY_PI_TARGET_FILL_PCT,
                integral: self.integral,
                pi_output: 0.0,
                drain_weight: 0.0,
                damping_state: "recovery_impulse",
                drain_gate_reason: "impulse_no_drain",
                drain_suppressed_by_slope: false,
                fill_slope_pct_per_sec,
                low_fill_escape_active: true,
                high_fill_drain_active: self.high_fill_drain_active,
                recovery_impulse_active: true,
                recovery_impulse_ticks: self.recovery_impulse_ticks,
                recovery_impulse_keep: STABLE_CORE_RECOVERY_IMPULSE_KEEP,
                recovery_impulse_trace_scale: STABLE_CORE_RECOVERY_IMPULSE_TRACE_SCALE,
                reentry_active: false,
                reentry_ticks: 0,
                reentry_live_weight: 0.0,
            };
        }

        let error_pct = fill_pct - STABILITY_PI_TARGET_FILL_PCT;
        let effective_error = (error_pct - STABILITY_PI_DEADBAND_PCT).max(0.0);
        let normalized_error = (effective_error / 20.0).clamp(0.0, 1.0);
        if normalized_error > 0.0 {
            self.integral = (self.integral + normalized_error).clamp(0.0, 1.0);
        } else {
            self.integral *= STABILITY_PI_INTEGRAL_DECAY;
        }
        let pi_output = (STABILITY_PI_KP * normalized_error + STABILITY_PI_KI * self.integral)
            .clamp(0.0, STABILITY_PI_MAX_OUTPUT);
        let drain_policy = stable_core_drain_policy(
            fill_pct,
            fill_slope_pct_per_sec,
            base_scaffold_drain_weight(stage).max(pi_output),
        );
        self.high_fill_drain_active = drain_policy.high_fill_active;
        StabilityPiOutput {
            active: true,
            target_fill_pct: STABILITY_PI_TARGET_FILL_PCT,
            error_pct,
            integral: self.integral,
            pi_output,
            drain_weight: drain_policy.weight,
            damping_state: drain_policy.damping_state,
            drain_gate_reason: drain_policy.reason,
            drain_suppressed_by_slope: drain_policy.suppressed_by_slope,
            fill_slope_pct_per_sec,
            low_fill_escape_active: false,
            high_fill_drain_active: self.high_fill_drain_active,
            recovery_impulse_active: false,
            recovery_impulse_ticks: 0,
            recovery_impulse_keep: 0.0,
            recovery_impulse_trace_scale: 0.0,
            reentry_active: false,
            reentry_ticks: 0,
            reentry_live_weight: 0.0,
        }
    }

    #[must_use]
    pub fn preview(
        &self,
        fill_pct: f32,
        fill_slope_pct_per_sec: f32,
        stage: OverfillStage,
        scaffold_active: bool,
    ) -> StabilityPiOutput {
        let mut clone = *self;
        clone.step(fill_pct, fill_slope_pct_per_sec, stage, scaffold_active)
    }

    fn reentry_output(&self, fill_pct: f32, fill_slope_pct_per_sec: f32) -> StabilityPiOutput {
        StabilityPiOutput {
            active: true,
            target_fill_pct: STABILITY_PI_TARGET_FILL_PCT,
            error_pct: fill_pct - STABILITY_PI_TARGET_FILL_PCT,
            integral: self.integral,
            pi_output: 0.0,
            drain_weight: 0.0,
            damping_state: "scaffold_reentry",
            drain_gate_reason: "reentry_no_drain",
            drain_suppressed_by_slope: false,
            fill_slope_pct_per_sec,
            low_fill_escape_active: false,
            high_fill_drain_active: self.high_fill_drain_active,
            recovery_impulse_active: false,
            recovery_impulse_ticks: 0,
            recovery_impulse_keep: 0.0,
            recovery_impulse_trace_scale: 0.0,
            reentry_active: true,
            reentry_ticks: self.reentry_ticks,
            reentry_live_weight: scaffold_reentry_live_weight(self.reentry_ticks),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{env, f32, fs, path::PathBuf, process};

    fn identity(dim: usize) -> Vec<f32> {
        let mut matrix = vec![0.0; dim * dim];
        for idx in 0..dim {
            matrix[idx * dim + idx] = 1.0;
        }
        matrix
    }

    fn make_temp_dir(label: &str) -> PathBuf {
        let dir = env::temp_dir().join(format!(
            "minime-rescue-scaffold-{}-{}-{}",
            label,
            process::id(),
            now_unix_ms()
        ));
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    #[test]
    fn loader_rejects_invalid_matrix_size() {
        let temp = make_temp_dir("bad-size");
        let path = temp.join("bad.bin");
        fs::write(&path, vec![0_u8; 8]).expect("write");

        let scaffold = load_scaffold(&path, None, 4, "dedicated", now_unix_ms());
        assert!(scaffold.is_none());
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn loader_rejects_non_finite_values() {
        let temp = make_temp_dir("non-finite");
        let path = temp.join("nan.bin");
        let values = [f32::NAN; 4];
        let mut bytes = Vec::new();
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        fs::write(&path, bytes).expect("write");

        let scaffold = load_scaffold(&path, None, 2, "dedicated", now_unix_ms());
        assert!(scaffold.is_none());
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn normalize_symmetrizes_and_renormalizes_trace() {
        let matrix = vec![2.0, 3.0, 1.0, 4.0];
        let (normalized, trace) = normalize_covariance_matrix(&matrix, 2).expect("normalize");

        assert!((trace - 2.0).abs() < 1e-5);
        assert!((normalized[1] - normalized[2]).abs() < 1e-6);
        let diag_trace = normalized[0] + normalized[3];
        assert!((diag_trace - 2.0).abs() < 1e-5);
    }

    #[test]
    fn capture_writes_metadata_and_reloads() {
        let temp = make_temp_dir("capture");
        let bin_path = temp.join("rescue_scaffold.bin");
        let meta_path = temp.join("rescue_scaffold.json");
        let captured = capture_scaffold(
            &identity(2),
            2,
            &bin_path,
            &meta_path,
            64.2,
            1.12,
            "hold",
            1234,
        )
        .expect("capture");

        assert_eq!(captured.source, "captured_live");
        let reloaded =
            load_scaffold(&bin_path, Some(&meta_path), 2, "dedicated", 5678).expect("reload");
        assert_eq!(reloaded.source, "captured_live");
        assert_eq!(reloaded.captured_at_unix_ms, Some(1234));
        assert_eq!(reloaded.captured_stage.as_deref(), Some("hold"));
        assert_eq!(reloaded.derived_from, None);
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn derive_cold_scaffold_writes_dedicated_metadata() {
        let temp = make_temp_dir("derive");
        let bin_path = temp.join("rescue_scaffold.bin");
        let meta_path = temp.join("rescue_scaffold.json");
        let stable = RescueScaffold::from_parts(
            vec![3.0, 1.0, 1.0, 1.0],
            2,
            "stable_checkpoint".to_string(),
            10,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .expect("stable");

        let derived = derive_cold_scaffold(
            &stable,
            &bin_path,
            &meta_path,
            22,
            "spectral_checkpoint_stable.bin",
        )
        .expect("derive");
        assert_eq!(derived.source, "derived_cold_from_stable");
        assert_eq!(
            derived.derived_from.as_deref(),
            Some("spectral_checkpoint_stable.bin")
        );
        assert_eq!(derived.cold_profile.as_deref(), Some(COLD_SCAFFOLD_PROFILE));
        assert_eq!(
            derived.activation_policy.as_deref(),
            Some(COLD_SCAFFOLD_ACTIVATION_POLICY)
        );
        assert_eq!(derived.profile_version, Some(COLD_SCAFFOLD_PROFILE_VERSION));
        assert_eq!(derived.mode_cap, Some(COLD_SCAFFOLD_MODE_CAP));
        assert_eq!(derived.stable_weight, Some(COLD_SCAFFOLD_STABLE_WEIGHT));
        assert_eq!(derived.diagonal_weight, Some(COLD_SCAFFOLD_DIAGONAL_WEIGHT));
        assert_eq!(
            derived.activation_fill_band,
            Some([SCAFFOLD_ACTIVATION_FILL_MIN, SCAFFOLD_ACTIVATION_FILL_MAX])
        );
        assert!(derived.matrix[1].abs() < stable.matrix[1].abs());

        let reloaded =
            load_scaffold(&bin_path, Some(&meta_path), 2, "dedicated", 33).expect("reload");
        assert_eq!(reloaded.source, "derived_cold_from_stable");
        assert_eq!(
            reloaded.derived_from.as_deref(),
            Some("spectral_checkpoint_stable.bin")
        );
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn stage_blend_weights_match_rescue_policy() {
        assert!((scaffold_live_weight(OverfillStage::Recovery) - 0.0).abs() < 1e-6);
        assert!((scaffold_live_weight(OverfillStage::Hold) - 0.0).abs() < 1e-6);
        assert!((scaffold_live_weight(OverfillStage::Elevated) - 0.0).abs() < 1e-6);
        assert!((scaffold_live_weight(OverfillStage::Discharge) - 0.0).abs() < 1e-6);
        assert!((base_scaffold_drain_weight(OverfillStage::Hold) - 0.0).abs() < 1e-6);
        assert!((base_scaffold_drain_weight(OverfillStage::Elevated) - 0.0).abs() < 1e-6);
        assert!((base_scaffold_drain_weight(OverfillStage::Discharge) - 0.0).abs() < 1e-6);
    }

    #[test]
    fn blend_preserves_scaffold_trace() {
        let scaffold = RescueScaffold::from_parts(
            identity(2),
            2,
            "stable_checkpoint".to_string(),
            10,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .expect("scaffold");
        let live = vec![2.0, 1.0, 1.0, 2.0];
        let blended = blend_toward_scaffold(&live, &scaffold, 0.35).expect("blend");
        let trace = blended[0] + blended[3];
        assert!((trace - scaffold.trace).abs() < 1e-5);
    }

    #[test]
    fn blend_with_drain_preserves_trace_and_cools_off_diagonal() {
        let scaffold = RescueScaffold::from_parts(
            identity(2),
            2,
            "derived_cold_from_stable".to_string(),
            10,
            Some(COLD_SCAFFOLD_PROFILE_VERSION),
            None,
            None,
            None,
            None,
            Some("spectral_checkpoint_stable.bin".to_string()),
            Some(COLD_SCAFFOLD_PROFILE.to_string()),
            Some(COLD_SCAFFOLD_ACTIVATION_POLICY.to_string()),
            Some(COLD_SCAFFOLD_MODE_CAP),
            Some(COLD_SCAFFOLD_STABLE_WEIGHT),
            Some(COLD_SCAFFOLD_DIAGONAL_WEIGHT),
            Some([SCAFFOLD_ACTIVATION_FILL_MIN, SCAFFOLD_ACTIVATION_FILL_MAX]),
        )
        .expect("scaffold");
        let live = vec![2.0, 1.0, 1.0, 2.0];
        let blended =
            blend_toward_scaffold_with_drain(&live, &scaffold, 0.10, 0.70).expect("blend");
        let trace = blended[0] + blended[3];
        assert!((trace - scaffold.trace).abs() < 1e-5);
        assert!(blended[1].abs() < 0.2);
    }

    #[test]
    fn rank_cold_drain_keeps_only_target_modes_hot() {
        let drain = rank_cold_drain_matrix(8);
        let trace = (0..8).map(|idx| drain[idx * 8 + idx]).sum::<f32>();
        assert!((trace - 8.0).abs() < 1e-5);
        assert!(drain[0] > drain[8 + 1]);
        assert!(drain[8 + 1] > drain[3 * 8 + 3]);
        assert!(drain[3 * 8 + 3] > 1.0);
        assert!(drain[4 * 8 + 4] < 0.01);
    }

    #[test]
    fn current_profile_accepts_current_derived_and_captured_scaffolds() {
        let derived = RescueScaffold::from_parts(
            identity(2),
            2,
            "derived_cold_from_stable".to_string(),
            10,
            Some(COLD_SCAFFOLD_PROFILE_VERSION),
            None,
            None,
            None,
            None,
            Some("spectral_checkpoint_stable.bin".to_string()),
            Some(COLD_SCAFFOLD_PROFILE.to_string()),
            Some(COLD_SCAFFOLD_ACTIVATION_POLICY.to_string()),
            Some(COLD_SCAFFOLD_MODE_CAP),
            Some(COLD_SCAFFOLD_STABLE_WEIGHT),
            Some(COLD_SCAFFOLD_DIAGONAL_WEIGHT),
            Some([SCAFFOLD_ACTIVATION_FILL_MIN, SCAFFOLD_ACTIVATION_FILL_MAX]),
        )
        .expect("derived");
        assert!(derived.is_current_dedicated_profile());

        let temp = make_temp_dir("profile");
        let captured = capture_scaffold(
            &identity(2),
            2,
            &temp.join("rescue_scaffold.bin"),
            &temp.join("rescue_scaffold.json"),
            64.0,
            1.0,
            "hold",
            10,
        )
        .expect("captured");
        assert!(captured.is_current_dedicated_profile());

        let stale = RescueScaffold::from_parts(
            identity(2),
            2,
            "derived_cold_from_stable".to_string(),
            10,
            Some(1),
            None,
            None,
            None,
            None,
            Some("spectral_checkpoint_stable.bin".to_string()),
            Some("diag_blend_0.20_0.80".to_string()),
            Some(COLD_SCAFFOLD_ACTIVATION_POLICY.to_string()),
            Some(1.15),
            Some(0.20),
            Some(0.80),
            Some([60.0, 66.0]),
        )
        .expect("stale");
        assert!(!stale.is_current_dedicated_profile());
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn stability_pi_uses_tiered_slope_aware_drain() {
        let mut pi = StabilityPiState::default();
        let neutral = pi.step(64.0, 0.0, OverfillStage::Hold, true);
        assert!(neutral.active);
        assert_eq!(neutral.pi_output, 0.0);
        assert_eq!(neutral.drain_weight, 0.0);

        let below_soft = pi.step(67.9, 2.0, OverfillStage::Hold, true);
        assert_eq!(below_soft.drain_weight, 0.0);
        assert_eq!(below_soft.drain_gate_reason, "below_soft_drain_band");

        let soft_rising = pi.step(68.5, 0.2, OverfillStage::Hold, true);
        assert_eq!(soft_rising.damping_state, "soft_drain");
        assert!((soft_rising.drain_weight - STABILITY_PI_SOFT_DRAIN).abs() < 1e-6);

        let soft_falling = pi.step(69.0, -0.1, OverfillStage::Hold, true);
        assert_eq!(soft_falling.drain_weight, 0.0);
        assert!(soft_falling.drain_suppressed_by_slope);

        let moderate_rising = pi.step(72.0, 0.1, OverfillStage::Elevated, true);
        assert_eq!(moderate_rising.damping_state, "moderate_drain");
        assert!(moderate_rising.drain_weight >= STABILITY_PI_MODERATE_DRAIN);
        assert!(moderate_rising.drain_weight <= STABILITY_PI_MAX_OUTPUT);

        let moderate_falling = pi.step(73.0, -0.5, OverfillStage::Elevated, true);
        assert_eq!(moderate_falling.damping_state, "moderate_drain_capped");
        assert!(moderate_falling.drain_suppressed_by_slope);
        assert!(moderate_falling.drain_weight <= STABILITY_PI_FALLING_DRAIN_CAP);

        let strong = pi.step(78.0, -1.0, OverfillStage::Elevated, true);
        assert!(strong.high_fill_drain_active);
        assert_eq!(strong.damping_state, "strong_drain");
        assert!(strong.drain_weight >= STABILITY_PI_STRONG_DRAIN);
        assert!(!strong.drain_suppressed_by_slope);
    }

    #[test]
    fn stability_pi_low_fill_escape_suspends_drain_until_recovered() {
        let mut pi = StabilityPiState::default();
        let early_escape = pi.step(63.5, 0.0, OverfillStage::Hold, true);
        assert!(early_escape.low_fill_escape_active);
        assert!(early_escape.recovery_impulse_active);
        assert_eq!(
            early_escape.recovery_impulse_keep,
            STABLE_CORE_RECOVERY_IMPULSE_KEEP
        );
        assert_eq!(early_escape.drain_weight, 0.0);

        let escape = pi.step(54.9, -1.0, OverfillStage::Recovery, true);
        assert!(escape.low_fill_escape_active);
        assert!(escape.recovery_impulse_active);
        assert_eq!(
            escape.recovery_impulse_keep,
            STABLE_CORE_RECOVERY_IMPULSE_KEEP
        );
        assert_eq!(
            escape.recovery_impulse_trace_scale,
            STABLE_CORE_RECOVERY_IMPULSE_TRACE_SCALE
        );
        assert_eq!(escape.drain_weight, 0.0);

        let still_escape = pi.step(59.5, -0.5, OverfillStage::Recovery, true);
        assert!(still_escape.low_fill_escape_active);
        assert!(still_escape.recovery_impulse_active);

        let released = pi.step(64.0, 0.0, OverfillStage::Hold, true);
        assert!(!released.low_fill_escape_active);
        assert!(!released.recovery_impulse_active);
        assert!(released.reentry_active);
        assert_eq!(released.reentry_ticks, 1);
        assert!(released.reentry_live_weight > 0.0);
    }

    #[test]
    fn stability_pi_enters_on_negative_slope_before_low_fill() {
        let mut pi = StabilityPiState::default();
        let output = pi.step(66.0, -2.5, OverfillStage::Elevated, true);

        assert!(output.low_fill_escape_active);
        assert!(output.recovery_impulse_active);
        assert_eq!(output.recovery_impulse_ticks, 1);
        assert_eq!(output.fill_slope_pct_per_sec, -2.5);
    }

    #[test]
    fn stability_pi_release_requires_rising_or_strong_fill() {
        let mut pi = StabilityPiState::default();
        assert!(
            pi.step(63.5, -1.0, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
        assert!(
            pi.step(60.5, -0.1, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
        assert!(
            pi.step(60.5, 0.0, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
        let released = pi.step(60.8, 0.2, OverfillStage::Hold, true);

        assert!(!released.recovery_impulse_active);
        assert!(released.reentry_active);
        assert_eq!(released.reentry_ticks, 1);
    }

    #[test]
    fn scaffold_reentry_live_weight_decays_to_soft_floor() {
        let first = scaffold_reentry_live_weight(1);
        let middle = scaffold_reentry_live_weight(STABILITY_PI_REENTRY_TICKS / 2);
        let last = scaffold_reentry_live_weight(STABILITY_PI_REENTRY_TICKS);

        assert!((first - STABLE_CORE_SCAFFOLD_REENTRY_INITIAL_LIVE_WEIGHT).abs() < 1e-6);
        assert!(middle < first);
        assert!(middle > last);
        assert!((last - STABLE_CORE_SCAFFOLD_REENTRY_FINAL_LIVE_WEIGHT).abs() < 1e-6);
        assert_eq!(
            scaffold_reentry_live_weight(STABILITY_PI_REENTRY_TICKS + 1),
            0.0
        );
    }

    #[test]
    fn stability_pi_reentry_falls_back_to_impulse_on_underfill() {
        let mut pi = StabilityPiState::default();
        assert!(
            pi.step(63.5, -1.0, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
        let reentry = pi.step(62.0, 0.0, OverfillStage::Hold, true);
        assert!(reentry.reentry_active);

        let fallback = pi.step(57.9, -1.0, OverfillStage::Recovery, true);
        assert!(fallback.recovery_impulse_active);
        assert!(!fallback.reentry_active);
    }

    #[test]
    fn stability_pi_reentry_falls_back_to_impulse_on_steep_downslope() {
        let mut pi = StabilityPiState::default();
        assert!(
            pi.step(63.5, -1.0, OverfillStage::Hold, true)
                .recovery_impulse_active
        );
        let reentry = pi.step(62.0, 0.0, OverfillStage::Hold, true);
        assert!(reentry.reentry_active);

        let fallback = pi.step(61.5, -1.6, OverfillStage::Hold, true);
        assert!(fallback.recovery_impulse_active);
        assert!(!fallback.reentry_active);
        assert_eq!(fallback.drain_weight, 0.0);
    }

    #[test]
    fn scaffold_activation_policy_requires_slope_safe_hold() {
        assert_eq!(
            stable_core_scaffold_activation_delay_reason(
                OverfillStage::Recovery,
                62.0,
                0.0,
                false,
                0,
                0,
            ),
            "stage_not_hold"
        );
        assert_eq!(
            stable_core_scaffold_activation_delay_reason(
                OverfillStage::Hold,
                62.0,
                4.0,
                false,
                0,
                0,
            ),
            "fill_slope_too_fast"
        );
        assert_eq!(
            stable_core_scaffold_activation_delay_reason(
                OverfillStage::Hold,
                62.0,
                -4.0,
                false,
                0,
                0,
            ),
            "protective_downslope_candidate"
        );
        assert_eq!(
            stable_core_scaffold_activation_delay_reason(
                OverfillStage::Hold,
                62.0,
                0.5,
                false,
                0,
                0,
            ),
            "candidate"
        );
    }
}
