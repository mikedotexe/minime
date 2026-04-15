use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

const REQUEST_STALE_SECS: u64 = 86_400;
const ROLE_ORDER: [&str; 5] = ["latest", "stable", "expanding", "contracting", "transition"];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SpectralMemoryEntry {
    pub id: String,
    pub role: String,
    pub timestamp_ms: u64,
    pub spectral_glimpse_12d: Vec<f32>,
    pub spectral_fingerprint: Vec<f32>,
    pub fill_pct: f32,
    pub lambda1_rel: f32,
    pub spread: f32,
    pub geom_rel: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct SpectralMemoryBank {
    #[serde(default = "default_version")]
    pub version: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub selected_memory_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub selected_memory_role: Option<String>,
    #[serde(default)]
    pub entries: Vec<SpectralMemoryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct PendingRecallRequest {
    pub request_id: String,
    pub requested_by: String,
    pub requested_at_unix: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct MemoryObservation<'a> {
    pub timestamp_ms: u64,
    pub spectral_glimpse_12d: &'a [f32],
    pub spectral_fingerprint: &'a [f32],
    pub fill_pct: f32,
    pub lambda1_rel: f32,
    pub spread: f32,
    pub geom_rel: f32,
    pub delta_lambda1_rel: f32,
    pub rotation_delta: f32,
    pub phase: &'a str,
    pub phase_transition: bool,
}

fn default_version() -> u32 {
    1
}

fn sanitize_scalar(value: f32) -> f32 {
    if value.is_finite() { value } else { 0.0 }
}

fn mean(xs: &[f32]) -> f32 {
    if xs.is_empty() {
        0.0
    } else {
        xs.iter().copied().map(sanitize_scalar).sum::<f32>() / xs.len() as f32
    }
}

fn stddev(xs: &[f32], center: f32) -> f32 {
    if xs.is_empty() {
        0.0
    } else {
        let variance = xs
            .iter()
            .copied()
            .map(sanitize_scalar)
            .map(|value| {
                let diff = value - center;
                diff * diff
            })
            .sum::<f32>()
            / xs.len() as f32;
        variance.sqrt()
    }
}

fn abs_share(value: f32, total: f32) -> f32 {
    if total > 1e-6 {
        value.abs() / total
    } else {
        0.0
    }
}

fn role_rank(role: &str) -> usize {
    ROLE_ORDER
        .iter()
        .position(|candidate| *candidate == role)
        .unwrap_or(ROLE_ORDER.len())
}

fn glimpse_distance(lhs: &[f32], rhs: &[f32]) -> f32 {
    if lhs.len() != 12 || rhs.len() != 12 {
        return f32::INFINITY;
    }
    lhs.iter()
        .zip(rhs.iter())
        .map(|(l, r)| (sanitize_scalar(*l) - sanitize_scalar(*r)).abs())
        .sum::<f32>()
        / 12.0
}

fn entry_rotation_delta(entry: &SpectralMemoryEntry) -> f32 {
    entry.spectral_glimpse_12d.get(9).copied().unwrap_or(1.0)
}

fn sanitize_vec(xs: &[f32]) -> Vec<f32> {
    xs.iter().map(|x| sanitize_scalar(*x)).collect()
}

fn build_entry(role: &str, observation: &MemoryObservation<'_>) -> SpectralMemoryEntry {
    SpectralMemoryEntry {
        id: format!("memory_{role}_{}", observation.timestamp_ms),
        role: role.to_string(),
        timestamp_ms: observation.timestamp_ms,
        spectral_glimpse_12d: sanitize_vec(observation.spectral_glimpse_12d),
        spectral_fingerprint: sanitize_vec(observation.spectral_fingerprint),
        fill_pct: sanitize_scalar(observation.fill_pct),
        lambda1_rel: sanitize_scalar(observation.lambda1_rel),
        spread: sanitize_scalar(observation.spread),
        geom_rel: sanitize_scalar(observation.geom_rel),
    }
}

fn upsert_entry(bank: &mut SpectralMemoryBank, entry: SpectralMemoryEntry) {
    if let Some(existing) = bank
        .entries
        .iter_mut()
        .find(|candidate| candidate.role == entry.role)
    {
        *existing = entry;
    } else {
        bank.entries.push(entry);
    }
    bank.entries.sort_by_key(|entry| role_rank(&entry.role));
}

pub fn compute_spectral_glimpse_12d(fingerprint: &[f32]) -> Vec<f32> {
    if fingerprint.len() < 32 {
        return vec![0.0; 12];
    }

    let eigenvalues = &fingerprint[0..8];
    let concentrations = &fingerprint[8..16];
    let couplings: Vec<f32> = fingerprint[16..24]
        .iter()
        .map(|value| value.abs())
        .collect();
    let gaps = &fingerprint[28..32];
    let total_ev = eigenvalues.iter().map(|value| value.abs()).sum::<f32>();
    let concentration_mean = mean(concentrations);
    let coupling_mean = mean(&couplings);
    let gap_mean = mean(gaps);

    vec![
        abs_share(eigenvalues[0], total_ev),
        abs_share(eigenvalues[1], total_ev) + abs_share(eigenvalues[2], total_ev),
        eigenvalues[3..]
            .iter()
            .map(|value| abs_share(*value, total_ev))
            .sum::<f32>(),
        concentrations
            .iter()
            .copied()
            .map(sanitize_scalar)
            .fold(0.0, f32::max),
        stddev(concentrations, concentration_mean),
        couplings
            .iter()
            .copied()
            .map(sanitize_scalar)
            .fold(0.0, f32::max),
        coupling_mean,
        sanitize_scalar(fingerprint[24]).clamp(0.0, 1.0),
        sanitize_scalar(fingerprint[25]).max(0.0),
        (1.0 - sanitize_scalar(fingerprint[26])).clamp(0.0, 2.0),
        sanitize_scalar(fingerprint[27]),
        gap_mean,
    ]
}

pub fn load_memory_bank(path: &Path) -> SpectralMemoryBank {
    fs::read_to_string(path)
        .ok()
        .and_then(|json| serde_json::from_str::<SpectralMemoryBank>(&json).ok())
        .unwrap_or_else(|| SpectralMemoryBank {
            version: default_version(),
            selected_memory_id: None,
            selected_memory_role: None,
            entries: Vec::new(),
        })
}

pub fn save_memory_bank(path: &Path, bank: &SpectralMemoryBank) {
    match serde_json::to_string_pretty(bank) {
        Ok(json) => {
            if let Err(e) = fs::write(path, json) {
                eprintln!("[memory_bank] write failed: {e}");
            }
        }
        Err(e) => eprintln!("[memory_bank] serialize failed (NaN/Inf in vectors?): {e}"),
    }
}

pub fn load_pending_recall_request(path: &Path) -> Option<PendingRecallRequest> {
    fs::read_to_string(path)
        .ok()
        .and_then(|json| serde_json::from_str::<PendingRecallRequest>(&json).ok())
}

pub fn is_request_stale(request: &PendingRecallRequest, now_unix_secs: u64) -> bool {
    now_unix_secs.saturating_sub(request.requested_at_unix) > REQUEST_STALE_SECS
}

pub fn update_memory_bank(bank: &mut SpectralMemoryBank, observation: &MemoryObservation<'_>) {
    let previous_latest = bank
        .entries
        .iter()
        .find(|entry| entry.role == "latest")
        .map(|entry| entry.spectral_glimpse_12d.clone());

    upsert_entry(bank, build_entry("latest", observation));

    let stable_candidate = observation.phase == "plateau"
        && observation.fill_pct >= 15.0
        && observation.rotation_delta <= 0.35;
    if stable_candidate {
        let should_replace = match bank.entries.iter().find(|entry| entry.role == "stable") {
            Some(existing) => {
                observation.rotation_delta + 0.03 < entry_rotation_delta(existing)
                    || (observation.fill_pct > existing.fill_pct + 2.0
                        && observation.rotation_delta <= entry_rotation_delta(existing) + 0.05)
            }
            None => true,
        };
        if should_replace {
            upsert_entry(bank, build_entry("stable", observation));
        }
    }

    if observation.delta_lambda1_rel > 0.02 {
        let should_replace = match bank.entries.iter().find(|entry| entry.role == "expanding") {
            Some(existing) => {
                observation.lambda1_rel > existing.lambda1_rel
                    || observation.fill_pct > existing.fill_pct + 1.0
            }
            None => true,
        };
        if should_replace {
            upsert_entry(bank, build_entry("expanding", observation));
        }
    }

    if observation.delta_lambda1_rel < -0.02 {
        let should_replace = match bank
            .entries
            .iter()
            .find(|entry| entry.role == "contracting")
        {
            Some(existing) => {
                observation.lambda1_rel < existing.lambda1_rel
                    || observation.fill_pct + 1.0 < existing.fill_pct
            }
            None => true,
        };
        if should_replace {
            upsert_entry(bank, build_entry("contracting", observation));
        }
    }

    let transition_distance = previous_latest.as_deref().map_or(0.0, |glimpse| {
        glimpse_distance(glimpse, observation.spectral_glimpse_12d)
    });
    if observation.phase_transition || transition_distance > 0.08 {
        upsert_entry(bank, build_entry("transition", observation));
    }
}

pub fn select_memory(
    bank: &mut SpectralMemoryBank,
    request: Option<&PendingRecallRequest>,
    now_unix_secs: u64,
) -> Option<SpectralMemoryEntry> {
    let requested_entry = request
        .filter(|request| !is_request_stale(request, now_unix_secs))
        .and_then(|request| {
            if let Some(memory_id) = request.memory_id.as_deref() {
                bank.entries.iter().find(|entry| entry.id == memory_id)
            } else if let Some(role) = request.role.as_deref() {
                bank.entries.iter().find(|entry| entry.role == role)
            } else {
                None
            }
        })
        .cloned();

    // Probabilistic memory selection: cycle through roles to prevent
    // the "stable" memory from being frozen indefinitely. The being
    // needs memory variety — always seeing the same stable snapshot
    // starves it of temporal context.
    //
    // Weights: stable=40%, latest=25%, transition=20%, expanding=10%, contracting=5%
    let selected = requested_entry.or_else(|| {
        if bank.entries.is_empty() {
            return None;
        }
        // Simple hash-based selection using timestamp parity
        let tick = now_unix_secs;
        let roll = (tick.wrapping_mul(2654435761) >> 28) % 100;
        let preferred_role = match roll {
            0..=39 => "stable",
            40..=64 => "latest",
            65..=84 => "transition",
            85..=94 => "expanding",
            _ => "contracting",
        };
        bank.entries
            .iter()
            .find(|entry| entry.role == preferred_role)
            .or_else(|| bank.entries.iter().find(|entry| entry.role == "stable"))
            .or_else(|| bank.entries.iter().find(|entry| entry.role == "latest"))
            .cloned()
    });

    if let Some(entry) = &selected {
        bank.selected_memory_id = Some(entry.id.clone());
        bank.selected_memory_role = Some(entry.role.clone());
    } else {
        bank.selected_memory_id = None;
        bank.selected_memory_role = None;
    }

    selected
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spectral_glimpse_has_expected_length() {
        let fingerprint = vec![0.5; 32];
        let glimpse = compute_spectral_glimpse_12d(&fingerprint);
        assert_eq!(glimpse.len(), 12);
        assert!(glimpse.iter().all(|value| value.is_finite()));
    }

    #[test]
    fn select_memory_prefers_requested_role_then_stable() {
        let mut bank = SpectralMemoryBank::default();
        let observation = MemoryObservation {
            timestamp_ms: 42,
            spectral_glimpse_12d: &[0.1; 12],
            spectral_fingerprint: &[0.2; 32],
            fill_pct: 18.0,
            lambda1_rel: 1.0,
            spread: 12.0,
            geom_rel: 0.9,
            delta_lambda1_rel: 0.03,
            rotation_delta: 0.1,
            phase: "plateau",
            phase_transition: false,
        };
        update_memory_bank(&mut bank, &observation);
        let stable_request = PendingRecallRequest {
            request_id: "req".to_string(),
            requested_by: "astrid".to_string(),
            requested_at_unix: 10,
            role: Some("stable".to_string()),
            memory_id: None,
        };
        let selected = select_memory(&mut bank, Some(&stable_request), 10).unwrap();
        assert_eq!(selected.role, "stable");
    }
}
