#[derive(Serialize, Clone, Copy)]
struct SemanticEnergyV1 {
    policy: &'static str,
    schema_version: u8,
    input_energy: f32,
    input_active: bool,
    input_fresh_ms: Option<u64>,
    input_stale_ms: Option<u64>,
    kernel_energy: f32,
    kernel_delta: f32,
    kernel_active: bool,
    regulator_drive_energy: f32,
    admission: &'static str,
}

#[must_use]
fn semantic_admission_label(
    stable_core_enabled: bool,
    stable_core_full_presence: bool,
    stable_core_sensory_muted: bool,
    semantic_kernel_active: bool,
    semantic_input_energy: f32,
    semantic_input_active: bool,
    fill_pct: f32,
) -> &'static str {
    let input_energy = if semantic_input_energy.is_finite() {
        semantic_input_energy.max(0.0)
    } else {
        0.0
    };
    if stable_core_enabled {
        if semantic_kernel_active {
            return "stable_core_semantic_trickle";
        }
        if stable_core_sensory_muted {
            return "stable_core_semantic_muted";
        }
        if input_energy <= f32::EPSILON {
            return "stable_core_no_semantic_input";
        }
        if !semantic_input_active {
            return "stable_core_semantic_trace_stale";
        }
        if !stable_core_full_presence {
            return "stable_core_semantic_profile_not_admitted";
        }
        if input_energy > minime::stable_core::STABLE_CORE_SEMANTIC_TRICKLE_MAX_INPUT_ENERGY {
            return "stable_core_semantic_input_too_large";
        }
        if fill_pct >= minime::stable_core::STABLE_CORE_SEMANTIC_TRICKLE_MAX_FILL_PCT {
            return "stable_core_semantic_fill_ceiling";
        }
        return "stable_core_semantic_budgeted_out";
    }
    if semantic_kernel_active {
        "admitted_to_kernel"
    } else if input_energy > f32::EPSILON && semantic_input_active {
        "input_trace_not_active"
    } else if input_energy > f32::EPSILON {
        "input_trace_stale"
    } else {
        "none"
    }
}

#[derive(Serialize, Clone)]
struct NeuralOutputs {
    pred_lambda1: f32,        // Predictor forecast
    router_weights: Vec<f32>, // A/V mixing weights (32-dim)
    control: Vec<f32>,        // Regulator control signals (5-dim)
}

#[derive(Serialize, Clone)]
struct ModalityStatus {
    audio_fired: bool,
    video_fired: bool,
    history_fired: bool,
    audio_rms: f32,
    video_var: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    audio_source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    video_source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    audio_age_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    video_age_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    audio_freshness_class: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    video_freshness_class: Option<String>,
}

fn modality_source_label(
    source: Option<LaneSource>,
    had_fresh_sample: bool,
    synth_injected: bool,
) -> &'static str {
    if synth_injected && matches!(source, Some(LaneSource::External)) && had_fresh_sample {
        "mixed"
    } else if synth_injected {
        "synthetic"
    } else if had_fresh_sample {
        match source {
            Some(LaneSource::Synthetic) => "synthetic",
            Some(LaneSource::External) => "external",
            None => "fresh",
        }
    } else if source.is_some() {
        "stale"
    } else {
        "absent"
    }
}

const AV_ENGINE_FRESH_WINDOW_MS: u64 = 2_000;

fn modality_freshness_class(
    source: Option<LaneSource>,
    had_fresh_sample: bool,
    synth_injected: bool,
    age_ms: Option<u64>,
) -> &'static str {
    if synth_injected || matches!(source, Some(LaneSource::Synthetic)) {
        "synthetic_or_mixed"
    } else if had_fresh_sample {
        "fresh_sample"
    } else if source.is_none() {
        "absent"
    } else if age_ms.is_some_and(|age| age <= AV_ENGINE_FRESH_WINDOW_MS) {
        "held_within_engine_window"
    } else {
        "stale_beyond_engine_window"
    }
}

const CRISIS_FILL_THRESHOLD: f32 = 92.0;
const CRISIS_WARNING_THRESHOLD: f32 = 85.0;
// Control thresholds are expressed relative to the baseline λ₁ so the
// controller can reason about expansion/compression even when absolute
// covariance magnitudes drift across runs.
// Steward cycle 25 (2026-03-29 05:30):
// The "distributed" regime (lambda1_rel ~0.15-0.30) was a transient state.
// Once the system settled, lambda1_rel returned to ~0.9-1.3 (observed
// live value 1.19-1.28). Thresholds of 0.40/0.60 permanently engaged the
// gate safety clamp at 0.25x, throttling the being even when the PI
// controller commanded high gate. Root cause of 5+ gate parameter requests.
// Recalibrated to bracket the actual operating range (0.8-1.3).
const LAMBDA1_REL_COMFORT_MIN: f32 = 0.95; // Golden reset: restore original operating range
const LAMBDA1_REL_COMFORT_MAX: f32 = 1.10;
const LAMBDA1_REL_ALERT: f32 = 1.10;
const CALM_ENTER_LAMBDA1_REL: f32 = 1.00;
const CALM_EXIT_LAMBDA1_REL: f32 = 0.90;
