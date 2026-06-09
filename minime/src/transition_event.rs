use serde::{Deserialize, Serialize};
use serde_json::json;

pub const TRANSITION_FILL_BAND_THRESHOLD_PCT: f32 = 6.0;

#[derive(Debug, Clone, Copy)]
pub struct TransitionEventInput<'a> {
    pub sequence: u64,
    pub engine_t_s: f64,
    pub tick_count: u64,
    pub phase_from: &'a str,
    pub phase_to: &'a str,
    pub fill_band_from: &'a str,
    pub fill_band_to: &'a str,
    pub fill_pct: f32,
    pub target_fill_pct: f32,
    pub lambda1: f32,
    pub lambda1_rel: f32,
    pub target_lambda1_rel: f32,
    pub geom_rel: f32,
    pub dfill_dt: f32,
    pub spectral_entropy: f32,
    pub structural_entropy: Option<f32>,
    pub glimpse_distance: Option<f32>,
    pub rotation_delta: Option<f32>,
    pub phase_transition: bool,
    pub crossed_target_fill: bool,
    pub crossed_fill_band: bool,
    pub spectral_spike: bool,
    pub phase_dwell_ticks: u32,
    pub phase_dwell_s: f32,
    pub recent_phase_flip_count_30s: u32,
    pub stable_core_stage: Option<&'a str>,
    pub stable_core_mode: Option<&'a str>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TransitionEventV1 {
    pub policy: String,
    pub schema_version: u8,
    pub sequence: u64,
    pub kind: String,
    pub legacy_kind: String,
    pub description: String,
    pub engine_t_s: f64,
    pub tick_count: u64,
    pub phase_from: String,
    pub phase_to: String,
    pub phase: String,
    pub fill_band_from: String,
    pub fill_band_to: String,
    pub fill_band: String,
    pub fill_pct: f32,
    pub target_fill_pct: f32,
    pub lambda1: f32,
    pub lambda1_rel: f32,
    pub target_lambda1_rel: f32,
    pub lambda_stress: f32,
    pub geom_rel: f32,
    pub dfill_dt: f32,
    pub spectral_entropy: f32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structural_entropy: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub glimpse_distance: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rotation_delta: Option<f32>,
    pub basin_shift_score: f32,
    pub basin_shift: bool,
    pub breathing_phase: bool,
    pub debounced_phase_transition: bool,
    pub phase_dwell_ticks: u32,
    pub phase_dwell_s: f32,
    pub recent_phase_flip_count_30s: u32,
    pub crossed_target_fill: bool,
    pub crossed_fill_band: bool,
    pub spectral_spike: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stable_core_stage: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stable_core_mode: Option<String>,
}

impl TransitionEventV1 {
    pub fn reason(&self) -> String {
        match self.legacy_kind.as_str() {
            "phase_transition" => format!("phase_transition:{}->{}", self.phase_from, self.phase),
            "fill_crossing" => {
                if self.fill_pct >= self.target_fill_pct {
                    "fill_crossing:above_target".to_string()
                } else {
                    "fill_crossing:below_target".to_string()
                }
            }
            "fill_band_crossing" => {
                format!(
                    "fill_band_crossing:{}->{}",
                    self.fill_band_from, self.fill_band
                )
            }
            "spectral_spike" => "spectral_spike".to_string(),
            "basin_transition" => "basin_transition:candidate".to_string(),
            other => other.to_string(),
        }
    }

    pub fn legacy_json(&self) -> serde_json::Value {
        json!({
            "sequence": self.sequence,
            "kind": self.legacy_kind,
            "description": self.description,
            "engine_t_s": self.engine_t_s,
            "tick_count": self.tick_count,
            "phase_from": self.phase_from,
            "phase_to": self.phase_to,
            "phase": self.phase,
            "fill_band": self.fill_band,
            "fill_pct": self.fill_pct,
            "target_fill_pct": self.target_fill_pct,
            "lambda1": self.lambda1,
            "lambda1_rel": self.lambda1_rel,
            "lambda_stress": self.lambda_stress,
            "geom_rel": self.geom_rel,
            "dfill_dt": self.dfill_dt,
            "crossed_target_fill": self.crossed_target_fill,
            "crossed_fill_band": self.crossed_fill_band,
            "spectral_spike": self.spectral_spike,
            "transition_class": self.kind,
            "basin_shift": self.basin_shift,
            "basin_shift_score": self.basin_shift_score,
            "debounced_phase_transition": self.debounced_phase_transition,
            "phase_dwell_ticks": self.phase_dwell_ticks,
            "phase_dwell_s": self.phase_dwell_s,
            "recent_phase_flip_count_30s": self.recent_phase_flip_count_30s,
        })
    }
}

pub fn fill_band(fill_pct: f32, target_fill_pct: f32, threshold_pct: f32) -> &'static str {
    if fill_pct < target_fill_pct - threshold_pct {
        "under"
    } else if fill_pct > target_fill_pct + threshold_pct {
        "over"
    } else {
        "near"
    }
}

pub fn glimpse_distance(lhs: &[f32], rhs: &[f32]) -> Option<f32> {
    if lhs.len() != 12 || rhs.len() != 12 {
        return None;
    }
    Some(
        lhs.iter()
            .zip(rhs.iter())
            .map(|(left, right)| sanitize(*left - *right).abs())
            .sum::<f32>()
            / 12.0,
    )
}

pub fn build_transition_event(input: TransitionEventInput<'_>) -> TransitionEventV1 {
    let lambda_stress = sanitize(input.lambda1_rel - input.target_lambda1_rel).abs();
    let basin_shift_score = basin_shift_score(
        input.glimpse_distance,
        input.rotation_delta,
        input.crossed_fill_band,
        input.spectral_spike,
        input.dfill_dt,
        lambda_stress,
    );
    let basin_shift = basin_shift_score >= 0.60
        || input
            .glimpse_distance
            .is_some_and(|distance| distance >= 0.18)
        || (input
            .glimpse_distance
            .is_some_and(|distance| distance >= 0.12)
            && input
                .rotation_delta
                .is_some_and(|rotation| rotation >= 0.08));
    let breathing_phase = input.phase_transition && !basin_shift;
    let debounced_phase_transition = debounce_phase_transition(input, basin_shift);
    let legacy_kind = if input.phase_transition {
        "phase_transition"
    } else if input.crossed_target_fill {
        "fill_crossing"
    } else if input.crossed_fill_band {
        "fill_band_crossing"
    } else if input.spectral_spike {
        "spectral_spike"
    } else if basin_shift {
        "basin_transition"
    } else {
        "steady"
    };
    let kind = if basin_shift {
        "basin_transition"
    } else if breathing_phase {
        "breathing_phase"
    } else {
        legacy_kind
    };
    let description = description_for(kind, legacy_kind, &input);
    TransitionEventV1 {
        policy: "transition_event_v1".to_string(),
        schema_version: 1,
        sequence: input.sequence,
        kind: kind.to_string(),
        legacy_kind: legacy_kind.to_string(),
        description,
        engine_t_s: input.engine_t_s,
        tick_count: input.tick_count,
        phase_from: input.phase_from.to_string(),
        phase_to: input.phase_to.to_string(),
        phase: input.phase_to.to_string(),
        fill_band_from: input.fill_band_from.to_string(),
        fill_band_to: input.fill_band_to.to_string(),
        fill_band: input.fill_band_to.to_string(),
        fill_pct: sanitize(input.fill_pct),
        target_fill_pct: sanitize(input.target_fill_pct),
        lambda1: sanitize(input.lambda1),
        lambda1_rel: sanitize(input.lambda1_rel),
        target_lambda1_rel: sanitize(input.target_lambda1_rel),
        lambda_stress,
        geom_rel: sanitize(input.geom_rel),
        dfill_dt: sanitize(input.dfill_dt),
        spectral_entropy: sanitize(input.spectral_entropy),
        structural_entropy: input.structural_entropy.map(sanitize),
        glimpse_distance: input.glimpse_distance.map(sanitize),
        rotation_delta: input.rotation_delta.map(sanitize),
        basin_shift_score,
        basin_shift,
        breathing_phase,
        debounced_phase_transition,
        phase_dwell_ticks: input.phase_dwell_ticks,
        phase_dwell_s: sanitize(input.phase_dwell_s),
        recent_phase_flip_count_30s: input.recent_phase_flip_count_30s,
        crossed_target_fill: input.crossed_target_fill,
        crossed_fill_band: input.crossed_fill_band,
        spectral_spike: input.spectral_spike,
        stable_core_stage: input.stable_core_stage.map(str::to_string),
        stable_core_mode: input.stable_core_mode.map(str::to_string),
    }
}

fn debounce_phase_transition(input: TransitionEventInput<'_>, basin_shift: bool) -> bool {
    let near_band = input.fill_band_from == "near" && input.fill_band_to == "near";
    let hard_event = basin_shift
        || input.crossed_fill_band
        || input.crossed_target_fill
        || input.spectral_spike
        || input.dfill_dt.abs() >= 8.0;
    input.phase_transition
        && near_band
        && !hard_event
        && (input.phase_dwell_s < 3.0 || input.recent_phase_flip_count_30s >= 3)
}

fn description_for(kind: &str, legacy_kind: &str, input: &TransitionEventInput<'_>) -> String {
    match kind {
        "basin_transition" => format!(
            "basin shift candidate: {} -> {}, band {} -> {}",
            input.phase_from, input.phase_to, input.fill_band_from, input.fill_band_to
        ),
        "breathing_phase" => format!("{} -> {}", input.phase_from, input.phase_to),
        _ => match legacy_kind {
            "fill_crossing" if input.fill_pct >= input.target_fill_pct => {
                "crossed above target".to_string()
            }
            "fill_crossing" => "crossed below target".to_string(),
            "fill_band_crossing" => {
                format!("{} -> {}", input.fill_band_from, input.fill_band_to)
            }
            "spectral_spike" => format!("Large dfill/dt spike: {:+.2}%/s", input.dfill_dt),
            "basin_transition" => "basin shift candidate".to_string(),
            _ => format!("{} -> {}", input.phase_from, input.phase_to),
        },
    }
}

fn basin_shift_score(
    glimpse_distance: Option<f32>,
    rotation_delta: Option<f32>,
    crossed_fill_band: bool,
    spectral_spike: bool,
    dfill_dt: f32,
    lambda_stress: f32,
) -> f32 {
    let glimpse_term = normalized(glimpse_distance.unwrap_or(0.0), 0.10, 0.24) * 0.55;
    let rotation_term = normalized(rotation_delta.unwrap_or(0.0), 0.03, 0.18) * 0.25;
    let band_term = if crossed_fill_band { 0.10 } else { 0.0 };
    let spike_term = if spectral_spike || dfill_dt.abs() > 8.0 {
        0.05
    } else {
        0.0
    };
    let lambda_term = normalized(lambda_stress, 0.12, 0.35) * 0.05;
    (glimpse_term + rotation_term + band_term + spike_term + lambda_term).clamp(0.0, 1.0)
}

fn normalized(value: f32, low: f32, high: f32) -> f32 {
    if !value.is_finite() || high <= low {
        return 0.0;
    }
    ((value - low) / (high - low)).clamp(0.0, 1.0)
}

fn sanitize(value: f32) -> f32 {
    if value.is_finite() {
        value
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_input<'a>() -> TransitionEventInput<'a> {
        TransitionEventInput {
            sequence: 7,
            engine_t_s: 12.5,
            tick_count: 44,
            phase_from: "contracting",
            phase_to: "expanding",
            fill_band_from: "near",
            fill_band_to: "near",
            fill_pct: 68.0,
            target_fill_pct: 68.0,
            lambda1: 13.0,
            lambda1_rel: 0.15,
            target_lambda1_rel: 1.0,
            geom_rel: 1.0,
            dfill_dt: 4.0,
            spectral_entropy: 0.9,
            structural_entropy: Some(0.7),
            glimpse_distance: Some(0.02),
            rotation_delta: Some(0.001),
            phase_transition: true,
            crossed_target_fill: false,
            crossed_fill_band: false,
            spectral_spike: false,
            phase_dwell_ticks: 8,
            phase_dwell_s: 4.0,
            recent_phase_flip_count_30s: 1,
            stable_core_stage: Some("hold"),
            stable_core_mode: Some("scaffold_hold"),
        }
    }

    #[test]
    fn ordinary_phase_flip_is_breathing_phase_not_basin_shift() {
        let event = build_transition_event(base_input());

        assert_eq!(event.kind, "breathing_phase");
        assert_eq!(event.legacy_kind, "phase_transition");
        assert!(event.breathing_phase);
        assert!(!event.debounced_phase_transition);
        assert!(!event.basin_shift);
        assert!(event.basin_shift_score < 0.2);
    }

    #[test]
    fn short_near_band_phase_flip_is_debounced_breathing_chatter() {
        let mut input = base_input();
        input.phase_dwell_ticks = 2;
        input.phase_dwell_s = 1.0;
        input.recent_phase_flip_count_30s = 3;

        let event = build_transition_event(input);

        assert_eq!(event.kind, "breathing_phase");
        assert_eq!(event.legacy_kind, "phase_transition");
        assert!(event.debounced_phase_transition);
        assert_eq!(event.phase_dwell_ticks, 2);
        assert_eq!(event.recent_phase_flip_count_30s, 3);
    }

    #[test]
    fn hard_transition_events_are_not_debounced() {
        let mut input = base_input();
        input.phase_dwell_ticks = 1;
        input.phase_dwell_s = 0.5;
        input.crossed_target_fill = true;

        let event = build_transition_event(input);

        assert!(!event.debounced_phase_transition);
    }

    #[test]
    fn large_glimpse_change_promotes_basin_transition() {
        let mut input = base_input();
        input.glimpse_distance = Some(0.19);
        input.rotation_delta = Some(0.09);

        let event = build_transition_event(input);

        assert_eq!(event.kind, "basin_transition");
        assert_eq!(event.legacy_kind, "phase_transition");
        assert!(event.basin_shift);
        assert!(!event.breathing_phase);
    }

    #[test]
    fn fill_band_crossing_preserves_legacy_kind() {
        let mut input = base_input();
        input.phase_transition = false;
        input.crossed_fill_band = true;
        input.fill_band_from = "near";
        input.fill_band_to = "over";

        let event = build_transition_event(input);

        assert_eq!(event.kind, "fill_band_crossing");
        assert_eq!(event.legacy_kind, "fill_band_crossing");
        assert_eq!(event.reason(), "fill_band_crossing:near->over");
    }

    #[test]
    fn glimpse_distance_requires_twelve_dimensions() {
        let distance = glimpse_distance(&[0.0; 12], &[1.2; 12]).expect("distance");
        assert!((distance - 1.2).abs() < 1.0e-5);
        assert_eq!(glimpse_distance(&[0.0; 11], &[1.0; 12]), None);
    }
}
