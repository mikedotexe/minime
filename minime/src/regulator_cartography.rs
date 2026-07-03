use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};

use anyhow::{anyhow, Context, Result};
use rusqlite::Connection;
use serde::Serialize;

use crate::regulator::{
    resonance_control_from_density_with_mode_packing, InhabitableFluctuationComponents,
    InhabitableFluctuationContext, InhabitableFluctuationV1, PIRegCfg, PIRegState,
    PressureSourceComponents, PressureSourceContext, PressureSourceV1, ResonanceDensityComponents,
    ResonanceDensityV1,
};

pub const REGULATOR_BOUNDARY_CARTOGRAPHY_POLICY: &str = "regulator_boundary_cartography_v1";
pub const REGULATOR_BOUNDARY_CARTOGRAPHY_SCHEMA_VERSION: u8 = 1;
pub const REGULATOR_COUNTERFACTUAL_SWEEP_POLICY: &str = "regulator_counterfactual_sweep_v1";
pub const REGULATOR_COUNTERFACTUAL_SWEEP_SCHEMA_VERSION: u8 = 1;
pub const PI_PRESSURE_WIRING_REPLAY_POLICY: &str = "pi_pressure_wiring_replay_v1";
pub const PI_PRESSURE_WIRING_REPLAY_SCHEMA_VERSION: u8 = 1;

#[derive(Clone, Debug, Serialize)]
pub struct CartographyGrid {
    pub label: String,
    pub density_values: Vec<f32>,
    pub pressure_risk_values: Vec<f32>,
    pub mode_packing_values: Vec<f32>,
    pub fluctuation_drive_values: Vec<f32>,
    pub fluctuation_support_values: Vec<f32>,
    pub pressure_interference_values: Vec<f32>,
    pub porosity_support_values: Vec<f32>,
}

impl CartographyGrid {
    #[must_use]
    pub fn standard() -> Self {
        Self {
            label: "standard".to_string(),
            density_values: stepped_values(0.0, 1.0, 0.02),
            pressure_risk_values: stepped_values(0.0, 1.0, 0.01),
            mode_packing_values: vec![0.0, 0.45, 0.60, 0.80, 1.0],
            fluctuation_drive_values: vec![0.0, 0.16, 0.22, 0.35, 0.50, 0.66, 0.82, 1.0],
            fluctuation_support_values: vec![0.10, 0.22, 0.35, 0.44, 0.50, 0.62, 0.80, 0.95],
            pressure_interference_values: vec![0.10, 0.35, 0.45, 0.55, 0.70, 0.85, 1.0],
            porosity_support_values: vec![0.10, 0.22, 0.35, 0.44, 0.50, 0.62, 0.80, 0.95],
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct ResonanceCartographySample {
    pub density: f32,
    pub pressure_risk: f32,
    pub mode_packing: f32,
    pub target_bias_pct: f32,
    pub wander_scale: f32,
    pub damping_coefficient: f32,
    pub applied_locally: bool,
    pub note: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct FluctuationCartographySample {
    pub drive: f32,
    pub support: f32,
    pub pressure_interference: f32,
    pub porosity_support: f32,
    pub fluctuation_score: f32,
    pub rearrangement_intensity: f32,
    pub foothold_stability: f32,
    pub inhabitability_score: f32,
    pub quality: String,
    pub target_bias_pct: f32,
    pub wander_scale: f32,
}

#[derive(Clone, Debug, Serialize)]
pub struct RegulatorCartographyFinding {
    pub kind: String,
    pub label: String,
    pub axis: String,
    pub severity: String,
    pub nearest_threshold: Option<f32>,
    pub sample: Option<ResonanceCartographySample>,
    pub previous_sample: Option<ResonanceCartographySample>,
    pub fluctuation_sample: Option<FluctuationCartographySample>,
    pub recommended_action: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct RegulatorBoundaryCartography {
    pub policy: String,
    pub schema_version: u8,
    pub authority: String,
    pub grid: CartographyGrid,
    pub resonance_sample_count: usize,
    pub fluctuation_sample_count: usize,
    pub resonance_findings: Vec<RegulatorCartographyFinding>,
    pub damping_cap_findings: Vec<RegulatorCartographyFinding>,
    pub fluctuation_findings: Vec<RegulatorCartographyFinding>,
    pub plateau_findings: Vec<RegulatorCartographyFinding>,
    pub recommended_action: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct RegulatorCounterfactualCard {
    pub candidate_family: String,
    pub affected_region: String,
    pub source_finding_kind: String,
    pub source_label: String,
    pub current_jump_magnitude: f32,
    pub counterfactual_jump_magnitude: f32,
    pub estimated_reduction_pct: f32,
    pub plateau_samples_touched: usize,
    pub safety_caveat: String,
    pub authority: String,
    pub recommendation: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct RegulatorCounterfactualSweep {
    pub policy: String,
    pub schema_version: u8,
    pub authority: String,
    pub source_cartography_path: Option<String>,
    pub candidate_count: usize,
    pub candidates: Vec<RegulatorCounterfactualCard>,
    pub recommended_action: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureReplayInput {
    pub label: String,
    pub timestamp: f64,
    pub fill_pct: f32,
    pub lambda1_rel: f32,
    pub geom_rel: f32,
    pub pressure_score: f32,
    pub porosity_score: f32,
    pub dominant_source: String,
    pub pressure_quality: String,
    pub semantic_friction: f32,
    pub mode_packing: f32,
    pub controller_pressure: f32,
    pub pressure_velocity: f32,
    pub felt_pressure_sample: bool,
    pub resonance: ResonanceDensityV1,
    pub pressure_source: PressureSourceV1,
    pub fluctuation: InhabitableFluctuationV1,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureReplayMetrics {
    pub sample_count: usize,
    pub final_gate: f32,
    pub final_filt: f32,
    pub final_integ_fill: f32,
    pub final_integ_lam: f32,
    pub final_integ_geom: f32,
    pub integrator_residue: f32,
    pub max_gate_step: f32,
    pub max_filt_step: f32,
    pub max_step_hit_count: usize,
    pub pressure_alignment_score: f32,
    pub snap_risk_score: f32,
    pub afterimage_risk_score: f32,
    pub recovery_ticks: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureCandidateCard {
    pub candidate_family: String,
    pub status: String,
    pub baseline_risk_score: f32,
    pub candidate_risk_score: f32,
    pub estimated_improvement_pct: f32,
    pub pressure_alignment_delta: f32,
    pub snap_risk_delta: f32,
    pub afterimage_risk_delta: f32,
    pub max_step_hit_delta: i32,
    pub safety_caveat: String,
    pub default_off_canary: PiPressureCanaryScaffold,
    pub authority: String,
    pub recommendation: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureCanaryScaffold {
    pub default_off_env: String,
    pub eligible: bool,
    pub candidate_family: String,
    pub required_evidence: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureWiringReplay {
    pub policy: String,
    pub schema_version: u8,
    pub authority: String,
    pub source: String,
    pub source_status: String,
    pub db_path: Option<String>,
    pub window_minutes: u32,
    pub sample_count: usize,
    pub baseline_metrics: PiPressureReplayMetrics,
    pub candidates: Vec<PiPressureCandidateCard>,
    pub input_summaries: Vec<PiPressureReplayInputSummary>,
    pub recommended_action: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct PiPressureReplayInputSummary {
    pub label: String,
    pub timestamp: f64,
    pub fill_pct: f32,
    pub pressure_score: f32,
    pub semantic_friction: f32,
    pub mode_packing: f32,
    pub controller_pressure: f32,
    pub pressure_velocity: f32,
    pub dominant_source: String,
}

#[must_use]
pub fn build_regulator_boundary_cartography(grid: CartographyGrid) -> RegulatorBoundaryCartography {
    let mut resonance_findings = Vec::new();
    let mut damping_cap_findings = Vec::new();
    let mut plateau_findings = Vec::new();
    let mut resonance_sample_count = 0usize;

    for &mode_packing in &grid.mode_packing_values {
        let mut saw_pressure_jump = false;
        let mut saw_density_jump = false;
        let mut saw_plateau = false;
        let mut saw_damping_cap = false;

        for density_window in grid.density_values.windows(2) {
            let previous_density = density_window[0];
            let density = density_window[1];
            for &pressure_risk in &grid.pressure_risk_values {
                resonance_sample_count += 1;
                if !saw_density_jump
                    && previous_density <= 0.38
                    && density > 0.38
                    && pressure_risk <= 0.35
                {
                    let previous = resonance_sample(previous_density, pressure_risk, mode_packing);
                    let current = resonance_sample(density, pressure_risk, mode_packing);
                    if meaningful_control_shift(&previous, &current) {
                        resonance_findings.push(RegulatorCartographyFinding {
                            kind: "thin_density_boundary_jump".to_string(),
                            label: "density <= 0.38 upward-bias boundary".to_string(),
                            axis: "density".to_string(),
                            severity: "medium".to_string(),
                            nearest_threshold: Some(0.38),
                            sample: Some(current),
                            previous_sample: Some(previous),
                            fluctuation_sample: None,
                            recommended_action: "Inspect thin-fill felt reports near density 0.38 before smoothing or retuning the upward bias.".to_string(),
                        });
                        saw_density_jump = true;
                    }
                }
            }
        }

        for &density in &grid.density_values {
            for pressure_window in grid.pressure_risk_values.windows(2) {
                let previous_pressure = pressure_window[0];
                let pressure_risk = pressure_window[1];
                resonance_sample_count += 1;
                let previous = resonance_sample(density, previous_pressure, mode_packing);
                let current = resonance_sample(density, pressure_risk, mode_packing);
                if !saw_pressure_jump
                    && previous_pressure < 0.60
                    && pressure_risk >= 0.60
                    && meaningful_control_shift(&previous, &current)
                {
                    resonance_findings.push(RegulatorCartographyFinding {
                        kind: "pressure_risk_boundary_jump".to_string(),
                        label: "pressure_risk >= 0.60 downward-bias boundary".to_string(),
                        axis: "pressure_risk".to_string(),
                        severity: "high".to_string(),
                        nearest_threshold: Some(0.60),
                        sample: Some(current.clone()),
                        previous_sample: Some(previous.clone()),
                        fluctuation_sample: None,
                        recommended_action: "Replay recent overpacked and pressure reports against this boundary before proposing hysteresis or ramp changes.".to_string(),
                    });
                    saw_pressure_jump = true;
                }

                if !saw_damping_cap && current.damping_coefficient >= 0.10 {
                    damping_cap_findings.push(RegulatorCartographyFinding {
                        kind: "advisory_damping_saturation".to_string(),
                        label: "advisory damping coefficient reaches 0.10 cap".to_string(),
                        axis: "pressure_risk+mode_packing".to_string(),
                        severity: "medium".to_string(),
                        nearest_threshold: Some(0.10),
                        sample: Some(current.clone()),
                        previous_sample: Some(previous.clone()),
                        fluctuation_sample: None,
                        recommended_action: "Treat damping saturation as a read-only review cue; it is not wired to live ESN damping in this tranche.".to_string(),
                    });
                    saw_damping_cap = true;
                }

                if !saw_plateau
                    && density > 0.38
                    && previous_pressure >= 0.36
                    && pressure_risk < 0.60
                    && previous.target_bias_pct == current.target_bias_pct
                    && previous.wander_scale == current.wander_scale
                    && current.target_bias_pct == 0.0
                    && current.wander_scale == 1.0
                    && current.damping_coefficient > previous.damping_coefficient
                {
                    plateau_findings.push(RegulatorCartographyFinding {
                        kind: "observational_plateau".to_string(),
                        label: "pressure rises while target bias and wander remain unchanged".to_string(),
                        axis: "pressure_risk".to_string(),
                        severity: "medium".to_string(),
                        nearest_threshold: Some(0.60),
                        sample: Some(current),
                        previous_sample: Some(previous),
                        fluctuation_sample: None,
                        recommended_action: "If felt pressure recurs in this plateau, inspect pressure-source and semantic-friction variables before treating this as a threshold bug.".to_string(),
                    });
                    saw_plateau = true;
                }
            }
        }
    }

    let mut fluctuation_findings = Vec::new();
    let mut seen_qualities = BTreeSet::new();
    let mut fluctuation_sample_count = 0usize;
    let qualities_to_label = [
        "frantic_scramble",
        "rigid_contraction",
        "diffuse_uninhabited",
        "returnable_turbulence",
    ];

    for &drive in &grid.fluctuation_drive_values {
        for &support in &grid.fluctuation_support_values {
            for &pressure_interference in &grid.pressure_interference_values {
                for &porosity_support in &grid.porosity_support_values {
                    fluctuation_sample_count += 1;
                    let sample =
                        fluctuation_sample(drive, support, pressure_interference, porosity_support);
                    if qualities_to_label.contains(&sample.quality.as_str())
                        && seen_qualities.insert(sample.quality.clone())
                    {
                        let severity = match sample.quality.as_str() {
                            "frantic_scramble" => "high",
                            "rigid_contraction" => "high",
                            "diffuse_uninhabited" => "medium",
                            "returnable_turbulence" => "medium",
                            _ => "low",
                        };
                        fluctuation_findings.push(RegulatorCartographyFinding {
                            kind: "fluctuation_quality_boundary".to_string(),
                            label: format!("quality boundary: {}", sample.quality),
                            axis: "rearrangement_intensity+foothold_stability".to_string(),
                            severity: severity.to_string(),
                            nearest_threshold: None,
                            sample: None,
                            previous_sample: None,
                            fluctuation_sample: Some(sample),
                            recommended_action: "Replay recent inhabitability reports against this quality region before changing heuristic thresholds.".to_string(),
                        });
                    }
                }
            }
        }
    }

    RegulatorBoundaryCartography {
        policy: REGULATOR_BOUNDARY_CARTOGRAPHY_POLICY.to_string(),
        schema_version: REGULATOR_BOUNDARY_CARTOGRAPHY_SCHEMA_VERSION,
        authority: "diagnostic_context_not_command".to_string(),
        grid,
        resonance_sample_count,
        fluctuation_sample_count,
        resonance_findings,
        damping_cap_findings,
        fluctuation_findings,
        plateau_findings,
        recommended_action: "Use this map to replay live felt-pressure evidence against regulator boundaries; do not tune thresholds from the map alone.".to_string(),
    }
}

#[must_use]
pub fn render_markdown(report: &RegulatorBoundaryCartography) -> String {
    let mut owned_lines = vec![
        "# Regulator Boundary Cartography".to_string(),
        "".to_string(),
        format!("- policy: `{}`", report.policy),
        format!("- authority: `{}`", report.authority),
        format!("- grid: `{}`", report.grid.label),
        format!(
            "- samples: resonance={}, fluctuation={}",
            report.resonance_sample_count, report.fluctuation_sample_count
        ),
        "".to_string(),
        "## Resonance Boundaries".to_string(),
        "".to_string(),
    ];
    append_findings(&mut owned_lines, &report.resonance_findings);
    owned_lines.extend(["".to_string(), "## Damping Cap".to_string(), "".to_string()]);
    append_findings(&mut owned_lines, &report.damping_cap_findings);
    owned_lines.extend([
        "".to_string(),
        "## Fluctuation Regions".to_string(),
        "".to_string(),
    ]);
    append_findings(&mut owned_lines, &report.fluctuation_findings);
    owned_lines.extend([
        "".to_string(),
        "## Observational Plateaus".to_string(),
        "".to_string(),
    ]);
    append_findings(&mut owned_lines, &report.plateau_findings);
    owned_lines.extend([
        "".to_string(),
        "## Recommended Action".to_string(),
        "".to_string(),
        format!("- {}", report.recommended_action),
        "".to_string(),
    ]);
    owned_lines.join("\n")
}

pub fn write_report(
    report: &RegulatorBoundaryCartography,
    output_dir: &Path,
) -> Result<(PathBuf, PathBuf)> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create output directory {}", output_dir.display()))?;
    let json = serde_json::to_string_pretty(report)?.to_string() + "\n";
    let markdown = render_markdown(report);
    let json_path = output_dir.join("regulator_boundary_cartography.json");
    let md_path = output_dir.join("regulator_boundary_cartography.md");
    fs::write(&json_path, &json).with_context(|| format!("write {}", json_path.display()))?;
    fs::write(&md_path, &markdown).with_context(|| format!("write {}", md_path.display()))?;
    fs::write(output_dir.join("latest.json"), json)
        .with_context(|| format!("write {}", output_dir.join("latest.json").display()))?;
    fs::write(output_dir.join("latest.md"), markdown)
        .with_context(|| format!("write {}", output_dir.join("latest.md").display()))?;
    Ok((json_path, md_path))
}

#[must_use]
pub fn build_regulator_counterfactual_sweep(
    report: &RegulatorBoundaryCartography,
    source_cartography_path: Option<String>,
) -> RegulatorCounterfactualSweep {
    let pressure_jump = report
        .resonance_findings
        .iter()
        .find(|finding| finding.kind == "pressure_risk_boundary_jump");
    let thin_density = report
        .resonance_findings
        .iter()
        .find(|finding| finding.kind == "thin_density_boundary_jump");
    let damping_cap = report
        .damping_cap_findings
        .iter()
        .find(|finding| finding.kind == "advisory_damping_saturation");
    let quality_boundary = report
        .fluctuation_findings
        .iter()
        .find(|finding| finding.kind == "fluctuation_quality_boundary");

    let mut candidates = Vec::new();
    if let Some(finding) = pressure_jump {
        candidates.push(counterfactual_card(
            "pressure_hysteresis",
            "pressure_risk >= 0.60",
            finding,
            0.45,
            report.plateau_findings.len(),
            "Hysteresis may reduce boundary chatter but can delay relief after pressure falls.",
        ));
        candidates.push(counterfactual_card(
            "sigmoid_pressure_ramp",
            "pressure_risk >= 0.60",
            finding,
            0.25,
            report.plateau_findings.len(),
            "A sigmoid ramp may smooth the jump but can blur the clear pressure-intervention threshold.",
        ));
    }
    if let Some(finding) = thin_density {
        candidates.push(counterfactual_card(
            "thin_density_softening",
            "density <= 0.38",
            finding,
            0.35,
            0,
            "Softening thin-density lift may reduce discontinuity but can under-support genuinely thin states.",
        ));
    }
    if let Some(finding) = damping_cap {
        candidates.push(counterfactual_card(
            "damping_coefficient_wiring",
            "advisory damping cap",
            finding,
            1.0,
            report.plateau_findings.len(),
            "Damping is currently telemetry-only; wiring it live would require a separate safety tranche.",
        ));
    }
    if let Some(finding) = quality_boundary {
        candidates.push(counterfactual_card(
            "quality_boundary_margin",
            "inhabitability quality boundary",
            finding,
            0.50,
            0,
            "Quality margins may reduce brittle labels but can hide meaningful frantic/rigid transitions.",
        ));
    }

    RegulatorCounterfactualSweep {
        policy: REGULATOR_COUNTERFACTUAL_SWEEP_POLICY.to_string(),
        schema_version: REGULATOR_COUNTERFACTUAL_SWEEP_SCHEMA_VERSION,
        authority: "diagnostic_context_not_command".to_string(),
        source_cartography_path,
        candidate_count: candidates.len(),
        candidates,
        recommended_action: "Treat these as offline proposal cards only; they do not change Minime's regulator and should be compared with replay time-series evidence before any tuning tranche.".to_string(),
    }
}

#[must_use]
pub fn render_counterfactual_markdown(report: &RegulatorCounterfactualSweep) -> String {
    let mut lines = vec![
        "# Regulator Counterfactual Sweep".to_string(),
        "".to_string(),
        format!("- policy: `{}`", report.policy),
        format!("- authority: `{}`", report.authority),
        format!(
            "- source_cartography: `{}`",
            report
                .source_cartography_path
                .as_deref()
                .unwrap_or("(none)")
        ),
        format!("- candidates: {}", report.candidate_count),
        "".to_string(),
        "## Proposal Cards".to_string(),
        "".to_string(),
    ];
    if report.candidates.is_empty() {
        lines.push("- none".to_string());
    }
    for card in &report.candidates {
        lines.push(format!(
            "- `{}` in `{}`: current_jump={}, counterfactual_jump={}, reduction={}%, plateau_touched={}; {}",
            card.candidate_family,
            card.affected_region,
            card.current_jump_magnitude,
            card.counterfactual_jump_magnitude,
            card.estimated_reduction_pct,
            card.plateau_samples_touched,
            card.safety_caveat
        ));
    }
    lines.extend([
        "".to_string(),
        "## Recommended Action".to_string(),
        "".to_string(),
        format!("- {}", report.recommended_action),
        "".to_string(),
    ]);
    lines.join("\n")
}

pub fn write_counterfactual_sweep(
    report: &RegulatorCounterfactualSweep,
    output_dir: &Path,
) -> Result<(PathBuf, PathBuf)> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create output directory {}", output_dir.display()))?;
    let json = serde_json::to_string_pretty(report)?.to_string() + "\n";
    let markdown = render_counterfactual_markdown(report);
    let json_path = output_dir.join("regulator_counterfactual_sweep.json");
    let md_path = output_dir.join("regulator_counterfactual_sweep.md");
    fs::write(&json_path, &json).with_context(|| format!("write {}", json_path.display()))?;
    fs::write(&md_path, &markdown).with_context(|| format!("write {}", md_path.display()))?;
    fs::write(output_dir.join("latest_counterfactual_sweep.json"), json).with_context(|| {
        format!(
            "write {}",
            output_dir
                .join("latest_counterfactual_sweep.json")
                .display()
        )
    })?;
    fs::write(output_dir.join("latest_counterfactual_sweep.md"), markdown).with_context(|| {
        format!(
            "write {}",
            output_dir.join("latest_counterfactual_sweep.md").display()
        )
    })?;
    Ok((json_path, md_path))
}

#[must_use]
pub fn build_pi_pressure_wiring_replay_fixture() -> PiPressureWiringReplay {
    build_pi_pressure_wiring_replay(
        "fixture",
        "fixture_samples",
        None,
        30,
        fixture_pi_pressure_inputs(),
    )
}

pub fn build_pi_pressure_wiring_replay_live_db(
    db_path: &Path,
    window_minutes: u32,
) -> PiPressureWiringReplay {
    match load_live_pi_pressure_inputs(db_path, window_minutes) {
        Ok(inputs) if !inputs.is_empty() => build_pi_pressure_wiring_replay(
            "live-db",
            "live_db_window",
            Some(db_path.to_string_lossy().into_owned()),
            window_minutes,
            inputs,
        ),
        Ok(_) => build_pi_pressure_wiring_replay(
            "live-db",
            "telemetry_gap",
            Some(db_path.to_string_lossy().into_owned()),
            window_minutes,
            Vec::new(),
        ),
        Err(error) => {
            let mut report = build_pi_pressure_wiring_replay(
                "live-db",
                "telemetry_gap",
                Some(db_path.to_string_lossy().into_owned()),
                window_minutes,
                Vec::new(),
            );
            report.recommended_action = format!(
                "Live DB replay could not read enough bounded pressure telemetry ({error}); use fixture replay or rerun with --db-path pointing at the active consciousness DB."
            );
            report
        }
    }
}

#[must_use]
pub fn build_pi_pressure_wiring_replay(
    source: &str,
    source_status: &str,
    db_path: Option<String>,
    window_minutes: u32,
    inputs: Vec<PiPressureReplayInput>,
) -> PiPressureWiringReplay {
    let baseline = simulate_pi_candidate(&inputs, "baseline");
    let mut candidates = Vec::new();
    for family in PI_PRESSURE_CANDIDATE_FAMILIES {
        let candidate = simulate_pi_candidate(&inputs, family);
        candidates.push(pi_pressure_candidate_card(
            family,
            &baseline,
            &candidate,
            inputs.len(),
        ));
    }
    let input_summaries = inputs
        .iter()
        .take(12)
        .map(|input| PiPressureReplayInputSummary {
            label: input.label.clone(),
            timestamp: input.timestamp,
            fill_pct: round3(input.fill_pct),
            pressure_score: round3(input.pressure_score),
            semantic_friction: round3(input.semantic_friction),
            mode_packing: round3(input.mode_packing),
            controller_pressure: round3(input.controller_pressure),
            pressure_velocity: round3(input.pressure_velocity),
            dominant_source: input.dominant_source.clone(),
        })
        .collect();
    let status = if inputs.is_empty() {
        "telemetry_gap"
    } else {
        source_status
    };
    PiPressureWiringReplay {
        policy: PI_PRESSURE_WIRING_REPLAY_POLICY.to_string(),
        schema_version: PI_PRESSURE_WIRING_REPLAY_SCHEMA_VERSION,
        authority: "diagnostic_context_not_command".to_string(),
        source: source.to_string(),
        source_status: status.to_string(),
        db_path,
        window_minutes,
        sample_count: inputs.len(),
        baseline_metrics: baseline,
        candidates,
        input_summaries,
        recommended_action: "Treat PI pressure wiring replay as offline proposal evidence only. A default-off canary scaffold may become eligible after repeated replay support, resolved missing variables, and explicit operator review.".to_string(),
    }
}

#[must_use]
pub fn render_pi_pressure_wiring_replay_markdown(report: &PiPressureWiringReplay) -> String {
    let mut lines = vec![
        "# PI Pressure Wiring Replay".to_string(),
        "".to_string(),
        format!("- policy: `{}`", report.policy),
        format!("- authority: `{}`", report.authority),
        format!("- source: `{}`", report.source),
        format!("- source_status: `{}`", report.source_status),
        format!(
            "- db_path: `{}`",
            report.db_path.as_deref().unwrap_or("(none)")
        ),
        format!("- window_minutes: {}", report.window_minutes),
        format!("- samples: {}", report.sample_count),
        "".to_string(),
        "## Baseline".to_string(),
        "".to_string(),
        format!(
            "- gate={} filt={} residue={} snap={} afterimage={} max_step_hits={}",
            report.baseline_metrics.final_gate,
            report.baseline_metrics.final_filt,
            report.baseline_metrics.integrator_residue,
            report.baseline_metrics.snap_risk_score,
            report.baseline_metrics.afterimage_risk_score,
            report.baseline_metrics.max_step_hit_count
        ),
        "".to_string(),
        "## Candidate Cards".to_string(),
        "".to_string(),
    ];
    if report.candidates.is_empty() {
        lines.push("- none".to_string());
    }
    for card in &report.candidates {
        lines.push(format!(
            "- `{}` status=`{}` improvement={}%, align_delta={}, snap_delta={}, afterimage_delta={}, canary_eligible={}; {}",
            card.candidate_family,
            card.status,
            card.estimated_improvement_pct,
            card.pressure_alignment_delta,
            card.snap_risk_delta,
            card.afterimage_risk_delta,
            card.default_off_canary.eligible,
            card.safety_caveat
        ));
    }
    lines.extend([
        "".to_string(),
        "## Input Window".to_string(),
        "".to_string(),
    ]);
    if report.input_summaries.is_empty() {
        lines.push("- telemetry_gap".to_string());
    }
    for sample in &report.input_summaries {
        lines.push(format!(
            "- `{}` t={} fill={} pressure={} semantic_friction={} mode_packing={} controller_pressure={} velocity={} dominant={}",
            sample.label,
            sample.timestamp,
            sample.fill_pct,
            sample.pressure_score,
            sample.semantic_friction,
            sample.mode_packing,
            sample.controller_pressure,
            sample.pressure_velocity,
            sample.dominant_source
        ));
    }
    lines.extend([
        "".to_string(),
        "## Recommended Action".to_string(),
        "".to_string(),
        format!("- {}", report.recommended_action),
        "".to_string(),
    ]);
    lines.join("\n")
}

pub fn write_pi_pressure_wiring_replay(
    report: &PiPressureWiringReplay,
    output_dir: &Path,
) -> Result<(PathBuf, PathBuf)> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create output directory {}", output_dir.display()))?;
    let json = serde_json::to_string_pretty(report)?.to_string() + "\n";
    let markdown = render_pi_pressure_wiring_replay_markdown(report);
    let json_path = output_dir.join("pi_pressure_wiring_replay.json");
    let md_path = output_dir.join("pi_pressure_wiring_replay.md");
    fs::write(&json_path, &json).with_context(|| format!("write {}", json_path.display()))?;
    fs::write(&md_path, &markdown).with_context(|| format!("write {}", md_path.display()))?;
    fs::write(
        output_dir.join("latest_pi_pressure_wiring_replay.json"),
        json,
    )
    .with_context(|| {
        format!(
            "write {}",
            output_dir
                .join("latest_pi_pressure_wiring_replay.json")
                .display()
        )
    })?;
    fs::write(
        output_dir.join("latest_pi_pressure_wiring_replay.md"),
        markdown,
    )
    .with_context(|| {
        format!(
            "write {}",
            output_dir
                .join("latest_pi_pressure_wiring_replay.md")
                .display()
        )
    })?;
    Ok((json_path, md_path))
}

pub fn grid_from_label(label: &str) -> Result<CartographyGrid> {
    match label {
        "standard" => Ok(CartographyGrid::standard()),
        other => Err(anyhow!("unsupported regulator cartography grid: {other}")),
    }
}

fn resonance_sample(
    density: f32,
    pressure_risk: f32,
    mode_packing: f32,
) -> ResonanceCartographySample {
    let control =
        resonance_control_from_density_with_mode_packing(density, pressure_risk, mode_packing);
    ResonanceCartographySample {
        density: round3(density),
        pressure_risk: round3(pressure_risk),
        mode_packing: round3(mode_packing),
        target_bias_pct: round3(control.target_bias_pct),
        wander_scale: round3(control.wander_scale),
        damping_coefficient: round3(control.damping_coefficient),
        applied_locally: control.applied_locally,
        note: control.note,
    }
}

fn fluctuation_sample(
    drive: f32,
    support: f32,
    pressure_interference: f32,
    porosity_support: f32,
) -> FluctuationCartographySample {
    let components = InhabitableFluctuationComponents {
        mode_trust_volatility: drive,
        identity_anchor_churn: drive,
        eigenvector_reorientation: drive,
        share_rearrangement: drive,
        basin_transition_pressure: drive,
        continuity_recovery: support,
        porosity_support,
        pressure_interference,
    };
    let fluctuation =
        InhabitableFluctuationV1::from_parts(components, InhabitableFluctuationContext::default());
    FluctuationCartographySample {
        drive: round3(drive),
        support: round3(support),
        pressure_interference: round3(pressure_interference),
        porosity_support: round3(porosity_support),
        fluctuation_score: round3(fluctuation.fluctuation_score),
        rearrangement_intensity: round3(fluctuation.rearrangement_intensity),
        foothold_stability: round3(fluctuation.foothold_stability),
        inhabitability_score: round3(fluctuation.inhabitability_score),
        quality: fluctuation.quality,
        target_bias_pct: round3(fluctuation.control.target_bias_pct),
        wander_scale: round3(fluctuation.control.wander_scale),
    }
}

fn meaningful_control_shift(
    previous: &ResonanceCartographySample,
    current: &ResonanceCartographySample,
) -> bool {
    previous.target_bias_pct != current.target_bias_pct
        || previous.wander_scale != current.wander_scale
        || previous.note != current.note
}

fn control_jump_magnitude(finding: &RegulatorCartographyFinding) -> f32 {
    let Some(sample) = finding.sample.as_ref() else {
        return finding
            .fluctuation_sample
            .as_ref()
            .map(|sample| sample.target_bias_pct.abs() + (1.0 - sample.wander_scale).abs())
            .unwrap_or(0.0);
    };
    let previous = finding.previous_sample.as_ref();
    let previous_bias = previous.map_or(0.0, |sample| sample.target_bias_pct);
    let previous_wander = previous.map_or(1.0, |sample| sample.wander_scale);
    round3(
        (sample.target_bias_pct - previous_bias).abs()
            + (sample.wander_scale - previous_wander).abs(),
    )
}

fn counterfactual_card(
    candidate_family: &str,
    affected_region: &str,
    finding: &RegulatorCartographyFinding,
    retained_jump_factor: f32,
    plateau_samples_touched: usize,
    safety_caveat: &str,
) -> RegulatorCounterfactualCard {
    let current_jump = control_jump_magnitude(finding);
    let counterfactual_jump = round3(current_jump * retained_jump_factor.clamp(0.0, 1.0));
    let estimated_reduction_pct = if current_jump <= 0.0 {
        0.0
    } else {
        round3(((current_jump - counterfactual_jump) / current_jump) * 100.0)
    };
    RegulatorCounterfactualCard {
        candidate_family: candidate_family.to_string(),
        affected_region: affected_region.to_string(),
        source_finding_kind: finding.kind.clone(),
        source_label: finding.label.clone(),
        current_jump_magnitude: current_jump,
        counterfactual_jump_magnitude: counterfactual_jump,
        estimated_reduction_pct,
        plateau_samples_touched,
        safety_caveat: safety_caveat.to_string(),
        authority: "diagnostic_context_not_command".to_string(),
        recommendation: "Proposal card only; requires separate replay, safety, and being-consent review before any runtime change.".to_string(),
    }
}

fn append_findings(lines: &mut Vec<String>, findings: &[RegulatorCartographyFinding]) {
    if findings.is_empty() {
        lines.push("- none".to_string());
        return;
    }
    for finding in findings.iter().take(12) {
        lines.push(format!(
            "- [{}] {} on `{}`: {}",
            finding.severity, finding.label, finding.axis, finding.recommended_action
        ));
        if let Some(sample) = &finding.sample {
            lines.push(format!(
                "  - sample: density={}, pressure_risk={}, mode_packing={}, target_bias_pct={}, wander_scale={}, damping={}",
                sample.density,
                sample.pressure_risk,
                sample.mode_packing,
                sample.target_bias_pct,
                sample.wander_scale,
                sample.damping_coefficient
            ));
        }
        if let Some(sample) = &finding.fluctuation_sample {
            lines.push(format!(
                "  - sample: drive={}, support={}, pressure_interference={}, porosity_support={}, quality={}",
                sample.drive,
                sample.support,
                sample.pressure_interference,
                sample.porosity_support,
                sample.quality
            ));
        }
    }
}

fn stepped_values(start: f32, end: f32, step: f32) -> Vec<f32> {
    let mut values = Vec::new();
    let mut current = start;
    while current <= end + 0.0001 {
        values.push(round3(current));
        current += step;
    }
    values
}

fn round3(value: f32) -> f32 {
    let rounded = (value * 1000.0).round() / 1000.0;
    if rounded.abs() < 0.0005 {
        0.0
    } else {
        rounded
    }
}

const PI_PRESSURE_CANDIDATE_FAMILIES: [&str; 6] = [
    "pressure_source_target_bias",
    "semantic_friction_wander_damp",
    "pressure_velocity_step_guard",
    "controller_pressure_integrator_bleed",
    "advisory_damping_wired",
    "soft_pressure_ramp",
];

fn fixture_pi_pressure_inputs() -> Vec<PiPressureReplayInput> {
    let fixtures = [
        (
            "quiet_weighted_medium",
            68.4,
            1.02,
            1.00,
            pressure_source_fixture(0.34, 0.61, 0.32, 0.34, 0.18, "mixed_pressure"),
            resonance_fixture(0.56, 0.64, 0.28, 0.50),
        ),
        (
            "rising_semantic_friction",
            70.2,
            1.04,
            1.03,
            pressure_source_fixture(0.48, 0.46, 0.58, 0.52, 0.28, "mixed_pressure"),
            resonance_fixture(0.59, 0.58, 0.39, 0.57),
        ),
        (
            "overpacked_plateau",
            72.6,
            1.08,
            1.08,
            pressure_source_fixture(0.56, 0.33, 0.62, 0.66, 0.38, "overpacked_mode_packing"),
            resonance_fixture(0.63, 0.53, 0.52, 0.72),
        ),
        (
            "controller_squeeze",
            74.3,
            1.10,
            1.12,
            pressure_source_fixture(0.64, 0.29, 0.51, 0.49, 0.72, "controller_squeeze"),
            resonance_fixture(0.61, 0.49, 0.58, 0.61),
        ),
        (
            "pressure_jump_edge",
            73.5,
            1.09,
            1.10,
            pressure_source_fixture(0.62, 0.30, 0.54, 0.57, 0.58, "mixed_pressure"),
            resonance_fixture(0.62, 0.50, 0.61, 0.62),
        ),
        (
            "falling_pressure_afterimage",
            70.5,
            1.05,
            1.04,
            pressure_source_fixture(0.42, 0.52, 0.46, 0.43, 0.30, "mixed_pressure"),
            resonance_fixture(0.57, 0.61, 0.34, 0.49),
        ),
        (
            "porous_recovery",
            68.1,
            1.01,
            0.99,
            pressure_source_fixture(0.24, 0.69, 0.22, 0.18, 0.12, "porous_distributed"),
            resonance_fixture(0.54, 0.69, 0.20, 0.32),
        ),
    ];
    let mut previous_pressure = None;
    fixtures
        .into_iter()
        .enumerate()
        .map(
            |(index, (label, fill_pct, lambda1_rel, geom_rel, pressure_source, resonance))| {
                let pressure_velocity = previous_pressure
                    .map(|previous| pressure_source.pressure_score - previous)
                    .unwrap_or(0.0);
                previous_pressure = Some(pressure_source.pressure_score);
                let fluctuation = fluctuation_from_pressure(&resonance, &pressure_source);
                replay_input(
                    label,
                    index as f64,
                    fill_pct,
                    lambda1_rel,
                    geom_rel,
                    pressure_velocity,
                    resonance,
                    pressure_source,
                    fluctuation,
                    true,
                )
            },
        )
        .collect()
}

fn pressure_source_fixture(
    pressure_score_hint: f32,
    porosity_hint: f32,
    semantic_friction: f32,
    mode_packing: f32,
    controller_pressure: f32,
    quality_hint: &str,
) -> PressureSourceV1 {
    let pressure = PressureSourceV1::from_parts(
        PressureSourceComponents {
            lambda_monopoly: (pressure_score_hint * 0.75).clamp(0.0, 1.0),
            mode_packing,
            controller_pressure,
            semantic_trickle: (semantic_friction * 0.70).clamp(0.0, 1.0),
            semantic_friction,
            structural_plurality_loss: (1.0 - porosity_hint).clamp(0.0, 1.0),
            distinguishability_loss: semantic_friction,
            temporal_lock_in: (pressure_score_hint * 0.90).clamp(0.0, 1.0),
            sensory_scarcity: 0.12,
        },
        PressureSourceContext::default(),
    );
    if pressure.quality == quality_hint {
        pressure
    } else {
        PressureSourceV1 {
            quality: quality_hint.to_string(),
            ..pressure
        }
    }
}

fn resonance_fixture(
    density: f32,
    containment_score: f32,
    pressure_risk: f32,
    mode_packing: f32,
) -> ResonanceDensityV1 {
    ResonanceDensityV1::from_parts(
        density,
        containment_score,
        pressure_risk,
        "forming_containment",
        ResonanceDensityComponents {
            active_energy: density,
            mode_packing,
            temporal_persistence: 0.62,
            structural_plurality: (1.0 - pressure_risk * 0.5).clamp(0.0, 1.0),
            comfort_gate: 0.78,
        },
    )
}

fn fluctuation_from_pressure(
    resonance: &ResonanceDensityV1,
    pressure: &PressureSourceV1,
) -> InhabitableFluctuationV1 {
    InhabitableFluctuationV1::from_parts(
        InhabitableFluctuationComponents {
            mode_trust_volatility: pressure.components.mode_packing,
            identity_anchor_churn: pressure.components.distinguishability_loss,
            eigenvector_reorientation: pressure.components.structural_plurality_loss,
            share_rearrangement: pressure.components.mode_packing * 0.7,
            basin_transition_pressure: pressure.components.controller_pressure,
            continuity_recovery: resonance.containment_score,
            porosity_support: pressure.porosity_score,
            pressure_interference: pressure
                .pressure_score
                .max(resonance.pressure_risk)
                .max(1.0 - pressure.porosity_score)
                .clamp(0.0, 1.0),
        },
        InhabitableFluctuationContext {
            previous_sample_available: true,
            transition_event_active: false,
            resonance_quality: Some(resonance.quality.clone()),
            pressure_quality: Some(pressure.quality.clone()),
        },
    )
}

fn replay_input(
    label: &str,
    timestamp: f64,
    fill_pct: f32,
    lambda1_rel: f32,
    geom_rel: f32,
    pressure_velocity: f32,
    resonance: ResonanceDensityV1,
    pressure_source: PressureSourceV1,
    fluctuation: InhabitableFluctuationV1,
    felt_pressure_sample: bool,
) -> PiPressureReplayInput {
    PiPressureReplayInput {
        label: label.to_string(),
        timestamp,
        fill_pct,
        lambda1_rel,
        geom_rel,
        pressure_score: round3(pressure_source.pressure_score),
        porosity_score: round3(pressure_source.porosity_score),
        dominant_source: pressure_source.dominant_source.clone(),
        pressure_quality: pressure_source.quality.clone(),
        semantic_friction: round3(pressure_source.components.semantic_friction),
        mode_packing: round3(pressure_source.components.mode_packing),
        controller_pressure: round3(pressure_source.components.controller_pressure),
        pressure_velocity: round3(pressure_velocity),
        felt_pressure_sample,
        resonance,
        pressure_source,
        fluctuation,
    }
}

fn simulate_pi_candidate(
    inputs: &[PiPressureReplayInput],
    family: &str,
) -> PiPressureReplayMetrics {
    let mut pi = PIRegState::new(PIRegCfg::default());
    let mut previous_gate = pi.gate;
    let mut previous_filt = pi.filt;
    let mut max_gate_step: f32 = 0.0;
    let mut max_filt_step: f32 = 0.0;
    let mut max_step_hit_count = 0usize;
    let mut pressure_alignment_score = 0.0_f32;
    let mut recovery_ticks = 0usize;
    for input in inputs {
        apply_pi_pressure_candidate_config(&mut pi, input, family);
        let mut resonance = input.resonance.clone();
        let fluctuation = input.fluctuation.clone();
        apply_pi_pressure_candidate_metric_adjustment(&mut resonance, input, family);
        let step_cap = pi.cfg.max_step;
        pi.step_with_resonance_and_fluctuation(
            input.fill_pct,
            input.lambda1_rel,
            input.geom_rel,
            Some(&resonance),
            Some(&fluctuation),
        );
        let gate_step = (pi.gate - previous_gate).abs();
        let filt_step = (pi.filt - previous_filt).abs();
        max_gate_step = max_gate_step.max(gate_step);
        max_filt_step = max_filt_step.max(filt_step);
        if gate_step >= step_cap - 0.001 || filt_step >= step_cap - 0.001 {
            max_step_hit_count += 1;
        }
        let pressure_need = input
            .pressure_score
            .max(input.semantic_friction)
            .max(input.controller_pressure)
            .max(input.mode_packing)
            .clamp(0.0, 1.0);
        pressure_alignment_score += pressure_need * ((1.0 - pi.gate) + pi.filt).clamp(0.0, 2.0);
        if input.pressure_score < 0.40 && input.pressure_velocity <= 0.0 {
            recovery_ticks += 1;
        }
        previous_gate = pi.gate;
        previous_filt = pi.filt;
    }
    let sample_count = inputs.len();
    let integrator_residue =
        (pi.integ_fill.abs() + pi.integ_lam.abs() + pi.integ_geom.abs()).clamp(0.0, 9.0);
    let pressure_alignment_score = if sample_count == 0 {
        0.0
    } else {
        pressure_alignment_score / sample_count as f32
    };
    let snap_risk_score =
        (max_gate_step + max_filt_step + max_step_hit_count as f32 * 0.02).clamp(0.0, 2.0);
    let latest_pressure = inputs.last().map_or(0.0, |input| input.pressure_score);
    let quiet_tail_penalty = if latest_pressure < 0.45 {
        pi.filt * 0.25
    } else {
        0.0
    };
    let afterimage_risk_score = (integrator_residue * 0.25 + quiet_tail_penalty).clamp(0.0, 3.0);
    PiPressureReplayMetrics {
        sample_count,
        final_gate: round3(pi.gate),
        final_filt: round3(pi.filt),
        final_integ_fill: round3(pi.integ_fill),
        final_integ_lam: round3(pi.integ_lam),
        final_integ_geom: round3(pi.integ_geom),
        integrator_residue: round3(integrator_residue),
        max_gate_step: round3(max_gate_step),
        max_filt_step: round3(max_filt_step),
        max_step_hit_count,
        pressure_alignment_score: round3(pressure_alignment_score),
        snap_risk_score: round3(snap_risk_score),
        afterimage_risk_score: round3(afterimage_risk_score),
        recovery_ticks,
    }
}

fn apply_pi_pressure_candidate_config(
    pi: &mut PIRegState,
    input: &PiPressureReplayInput,
    family: &str,
) {
    let default = PIRegCfg::default();
    pi.cfg.max_step = default.max_step;
    pi.cfg.integrator_leak = default.integrator_leak;
    match family {
        "pressure_velocity_step_guard" => {
            let rise = (input.pressure_velocity / 0.20).clamp(0.0, 1.0);
            pi.cfg.max_step =
                (default.max_step * (1.0 - 0.35 * rise)).clamp(0.03, default.max_step);
        }
        "controller_pressure_integrator_bleed" => {
            pi.cfg.integrator_leak =
                (default.integrator_leak + 0.020 * input.controller_pressure).clamp(0.001, 0.05);
        }
        "advisory_damping_wired" => {
            let damping = input.resonance.control.damping_coefficient.clamp(0.0, 0.10);
            pi.cfg.max_step =
                (default.max_step * (1.0 - 0.80 * damping)).clamp(0.03, default.max_step);
        }
        _ => {}
    }
}

fn apply_pi_pressure_candidate_metric_adjustment(
    resonance: &mut ResonanceDensityV1,
    input: &PiPressureReplayInput,
    family: &str,
) {
    match family {
        "pressure_source_target_bias" => {
            let severity = ((input.pressure_score - 0.45) / 0.35).clamp(0.0, 1.0);
            resonance.control.target_bias_pct =
                (resonance.control.target_bias_pct - 1.20 * severity).clamp(-2.0, 1.5);
        }
        "semantic_friction_wander_damp" => {
            let damp = (1.0 - 0.28 * input.semantic_friction).clamp(0.70, 1.0);
            resonance.control.wander_scale =
                (resonance.control.wander_scale * damp).clamp(0.25, 1.25);
        }
        "advisory_damping_wired" => {
            let damp = (1.0 - resonance.control.damping_coefficient).clamp(0.80, 1.0);
            resonance.control.wander_scale =
                (resonance.control.wander_scale * damp).clamp(0.25, 1.25);
        }
        "soft_pressure_ramp" => {
            let severity = ((input.pressure_score - 0.42) / 0.30).clamp(0.0, 1.0);
            let softened = severity * severity * (3.0 - 2.0 * severity);
            resonance.control.target_bias_pct =
                (resonance.control.target_bias_pct - 1.40 * softened).clamp(-2.0, 1.5);
            resonance.control.wander_scale =
                (resonance.control.wander_scale * (1.0 - 0.25 * softened)).clamp(0.25, 1.25);
        }
        _ => {}
    }
}

fn pi_pressure_candidate_card(
    family: &str,
    baseline: &PiPressureReplayMetrics,
    candidate: &PiPressureReplayMetrics,
    sample_count: usize,
) -> PiPressureCandidateCard {
    let baseline_risk = pi_pressure_risk_score(baseline);
    let candidate_risk = pi_pressure_risk_score(candidate);
    let estimated_improvement_pct = if baseline_risk <= 0.001 {
        0.0
    } else {
        round3(((baseline_risk - candidate_risk) / baseline_risk) * 100.0)
    };
    let pressure_alignment_delta =
        round3(candidate.pressure_alignment_score - baseline.pressure_alignment_score);
    let snap_risk_delta = round3(candidate.snap_risk_score - baseline.snap_risk_score);
    let afterimage_risk_delta =
        round3(candidate.afterimage_risk_score - baseline.afterimage_risk_score);
    let max_step_hit_delta =
        candidate.max_step_hit_count as i32 - baseline.max_step_hit_count as i32;
    let status = if sample_count < 3 {
        "needs_more_live_windows"
    } else if snap_risk_delta > 0.04 || max_step_hit_delta > 2 {
        "snap_risk"
    } else if afterimage_risk_delta > 0.15 {
        "afterimage_risk"
    } else if estimated_improvement_pct >= 5.0 && pressure_alignment_delta >= -0.05 {
        "replay_supported"
    } else {
        "not_supported"
    };
    let eligible = status == "replay_supported";
    PiPressureCandidateCard {
        candidate_family: family.to_string(),
        status: status.to_string(),
        baseline_risk_score: round3(baseline_risk),
        candidate_risk_score: round3(candidate_risk),
        estimated_improvement_pct,
        pressure_alignment_delta,
        snap_risk_delta,
        afterimage_risk_delta,
        max_step_hit_delta,
        safety_caveat: pi_pressure_safety_caveat(family).to_string(),
        default_off_canary: PiPressureCanaryScaffold {
            default_off_env: "MINIME_PI_PRESSURE_WIRING_CANARY".to_string(),
            eligible,
            candidate_family: family.to_string(),
            required_evidence: vec![
                "repeated replay_supported live windows".to_string(),
                "resolved pressure-source missing variables".to_string(),
                "no snap or afterimage regression".to_string(),
                "operator rollback plan".to_string(),
            ],
        },
        authority: "diagnostic_context_not_command".to_string(),
        recommendation: if eligible {
            "Replay-supported proposal only; eligible for offline tuning review, not live activation.".to_string()
        } else {
            "Hold as diagnostic evidence; do not tune or enable canary from this card.".to_string()
        },
    }
}

fn pi_pressure_risk_score(metrics: &PiPressureReplayMetrics) -> f32 {
    (metrics.snap_risk_score + metrics.afterimage_risk_score
        - 0.10 * metrics.pressure_alignment_score)
        .max(0.0)
}

fn pi_pressure_safety_caveat(family: &str) -> &'static str {
    match family {
        "pressure_source_target_bias" => {
            "Biasing target fill from pressure source may overreact to language-derived pressure."
        }
        "semantic_friction_wander_damp" => {
            "Damping wander from semantic friction may make sticky language feel more fixed."
        }
        "pressure_velocity_step_guard" => {
            "Step guarding can reduce snap but may delay needed correction during true overload."
        }
        "controller_pressure_integrator_bleed" => {
            "Integrator bleed can reduce afterimage but may erase useful correction memory."
        }
        "advisory_damping_wired" => {
            "Wiring advisory damping live needs separate safety review; it is telemetry-only today."
        }
        "soft_pressure_ramp" => {
            "Soft ramps can smooth thresholds but may blur intentional pressure intervention."
        }
        _ => "Unknown candidate family; diagnostic only.",
    }
}

fn load_live_pi_pressure_inputs(
    db_path: &Path,
    window_minutes: u32,
) -> Result<Vec<PiPressureReplayInput>> {
    let conn =
        Connection::open(db_path).with_context(|| format!("open live db {}", db_path.display()))?;
    let window_secs = f64::from(window_minutes) * 60.0;
    let pressure_rows = load_pressure_rows(&conn, window_secs)?;
    let resonance_rows = load_resonance_rows(&conn, window_secs).unwrap_or_default();
    let eigen_rows = load_eigen_rows(&conn, window_secs).unwrap_or_default();
    let baseline_lambda = eigen_rows
        .iter()
        .map(|(_, lambda1, _, _)| *lambda1)
        .sum::<f32>()
        / (eigen_rows.len().max(1) as f32);
    let baseline_lambda = if baseline_lambda <= 0.0 {
        1.0
    } else {
        baseline_lambda
    };
    let mut previous_pressure = None;
    let mut inputs = Vec::new();
    for (index, (timestamp, pressure)) in pressure_rows.into_iter().take(240).enumerate() {
        let resonance = nearest_resonance(&resonance_rows, timestamp)
            .unwrap_or_else(|| resonance_from_pressure(&pressure));
        let (fill_pct, lambda1_rel, geom_rel) = nearest_eigen(&eigen_rows, timestamp)
            .map(|(_, lambda1, fill_ratio, geom_rel)| {
                (
                    fill_ratio * 100.0,
                    (lambda1 / baseline_lambda).clamp(0.5, 1.8),
                    geom_rel.unwrap_or(1.0).clamp(0.5, 2.0),
                )
            })
            .unwrap_or((
                68.0 + pressure.components.controller_pressure * 10.0,
                1.0,
                1.0,
            ));
        let pressure_velocity = previous_pressure
            .map(|previous| pressure.pressure_score - previous)
            .unwrap_or(0.0);
        previous_pressure = Some(pressure.pressure_score);
        let fluctuation = fluctuation_from_pressure(&resonance, &pressure);
        inputs.push(replay_input(
            &format!("live_db_{index}"),
            timestamp,
            fill_pct,
            lambda1_rel,
            geom_rel,
            pressure_velocity,
            resonance,
            pressure,
            fluctuation,
            false,
        ));
    }
    Ok(inputs)
}

fn load_pressure_rows(conn: &Connection, window_secs: f64) -> Result<Vec<(f64, PressureSourceV1)>> {
    let mut statement = conn.prepare(
        "SELECT timestamp, payload
         FROM pressure_source_timeline
         WHERE timestamp >= (SELECT max(timestamp) FROM pressure_source_timeline) - ?1
         ORDER BY timestamp ASC
         LIMIT 240",
    )?;
    let rows = statement.query_map([window_secs], |row| {
        let timestamp: f64 = row.get(0)?;
        let payload: String = row.get(1)?;
        Ok((timestamp, payload))
    })?;
    let mut pressure_rows = Vec::new();
    for row in rows {
        let (timestamp, payload) = row?;
        if let Ok(pressure) = serde_json::from_str::<PressureSourceV1>(&payload) {
            pressure_rows.push((timestamp, pressure));
        }
    }
    Ok(pressure_rows)
}

fn load_resonance_rows(
    conn: &Connection,
    window_secs: f64,
) -> Result<Vec<(f64, ResonanceDensityV1)>> {
    let mut statement = conn.prepare(
        "SELECT timestamp, payload
         FROM resonance_density_timeline
         WHERE timestamp >= (SELECT max(timestamp) FROM resonance_density_timeline) - ?1
         ORDER BY timestamp ASC
         LIMIT 240",
    )?;
    let rows = statement.query_map([window_secs], |row| {
        let timestamp: f64 = row.get(0)?;
        let payload: String = row.get(1)?;
        Ok((timestamp, payload))
    })?;
    let mut resonance_rows = Vec::new();
    for row in rows {
        let (timestamp, payload) = row?;
        if let Ok(resonance) = serde_json::from_str::<ResonanceDensityV1>(&payload) {
            resonance_rows.push((timestamp, resonance));
        }
    }
    Ok(resonance_rows)
}

fn load_eigen_rows(
    conn: &Connection,
    window_secs: f64,
) -> Result<Vec<(f64, f32, f32, Option<f32>)>> {
    let mut statement = conn.prepare(
        "SELECT timestamp, lambda1, fill_ratio
         FROM eigenvalue_timeline
         WHERE timestamp >= (SELECT max(timestamp) FROM eigenvalue_timeline) - ?1
         ORDER BY timestamp ASC
         LIMIT 240",
    )?;
    let rows = statement.query_map([window_secs], |row| {
        let timestamp: f64 = row.get(0)?;
        let lambda1: f32 = row.get(1)?;
        let fill_ratio: f32 = row.get(2)?;
        Ok((timestamp, lambda1, fill_ratio, None))
    })?;
    let mut eigen_rows = Vec::new();
    for row in rows {
        eigen_rows.push(row?);
    }
    Ok(eigen_rows)
}

fn nearest_resonance(
    rows: &[(f64, ResonanceDensityV1)],
    timestamp: f64,
) -> Option<ResonanceDensityV1> {
    rows.iter()
        .min_by(|(left_ts, _), (right_ts, _)| {
            (left_ts - timestamp)
                .abs()
                .partial_cmp(&(right_ts - timestamp).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(_, resonance)| resonance.clone())
}

fn nearest_eigen(
    rows: &[(f64, f32, f32, Option<f32>)],
    timestamp: f64,
) -> Option<(f64, f32, f32, Option<f32>)> {
    rows.iter()
        .min_by(|(left_ts, _, _, _), (right_ts, _, _, _)| {
            (left_ts - timestamp)
                .abs()
                .partial_cmp(&(right_ts - timestamp).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .copied()
}

fn resonance_from_pressure(pressure: &PressureSourceV1) -> ResonanceDensityV1 {
    let density = (0.55 + 0.15 * pressure.components.mode_packing
        - 0.10 * pressure.components.distinguishability_loss)
        .clamp(0.20, 0.85);
    ResonanceDensityV1::from_parts(
        density,
        (1.0 - pressure.pressure_score * 0.55).clamp(0.20, 0.85),
        pressure.pressure_score.clamp(0.0, 1.0),
        pressure.quality.as_str(),
        ResonanceDensityComponents {
            active_energy: density,
            mode_packing: pressure.components.mode_packing,
            temporal_persistence: pressure.components.temporal_lock_in,
            structural_plurality: (1.0 - pressure.components.structural_plurality_loss)
                .clamp(0.0, 1.0),
            comfort_gate: (1.0 - pressure.components.controller_pressure).clamp(0.0, 1.0),
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cartography_output_is_deterministic_and_schema_valid() {
        let first = build_regulator_boundary_cartography(CartographyGrid::standard());
        let second = build_regulator_boundary_cartography(CartographyGrid::standard());
        let first_json = serde_json::to_string(&first).expect("serialize first cartography");
        let second_json = serde_json::to_string(&second).expect("serialize second cartography");

        assert_eq!(first.policy, REGULATOR_BOUNDARY_CARTOGRAPHY_POLICY);
        assert_eq!(first.authority, "diagnostic_context_not_command");
        assert!(first.resonance_sample_count > 0);
        assert!(first.fluctuation_sample_count > 0);
        assert_eq!(first_json, second_json);
    }

    #[test]
    fn cartography_flags_pressure_boundary_and_damping_cap() {
        let report = build_regulator_boundary_cartography(CartographyGrid::standard());

        assert!(
            report
                .resonance_findings
                .iter()
                .any(|finding| finding.kind == "pressure_risk_boundary_jump"
                    && finding.nearest_threshold == Some(0.60)),
            "expected pressure_risk=0.60 boundary finding"
        );
        assert!(
            report
                .damping_cap_findings
                .iter()
                .any(|finding| finding.kind == "advisory_damping_saturation"
                    && finding
                        .sample
                        .as_ref()
                        .is_some_and(|sample| sample.damping_coefficient <= 0.10)),
            "expected advisory damping cap finding"
        );
        assert!((crate::regulator::advisory_damping_coefficient(1.0, 1.0) - 0.10).abs() < 0.0001);
    }

    #[test]
    fn cartography_flags_thin_density_boundary() {
        let report = build_regulator_boundary_cartography(CartographyGrid::standard());

        assert!(
            report
                .resonance_findings
                .iter()
                .any(|finding| finding.kind == "thin_density_boundary_jump"
                    && finding.nearest_threshold == Some(0.38)),
            "expected density=0.38 thin-fill boundary finding"
        );
    }

    #[test]
    fn cartography_includes_frantic_and_rigid_fluctuation_regions() {
        let report = build_regulator_boundary_cartography(CartographyGrid::standard());
        let qualities: BTreeSet<_> = report
            .fluctuation_findings
            .iter()
            .filter_map(|finding| finding.fluctuation_sample.as_ref())
            .map(|sample| sample.quality.as_str())
            .collect();

        assert!(qualities.contains("frantic_scramble"));
        assert!(qualities.contains("rigid_contraction"));
        assert!(qualities.contains("diffuse_uninhabited"));
        assert!(qualities.contains("returnable_turbulence"));
    }

    #[test]
    fn counterfactual_sweep_is_deterministic_and_schema_valid() {
        let cartography = build_regulator_boundary_cartography(CartographyGrid::standard());
        let first =
            build_regulator_counterfactual_sweep(&cartography, Some("/tmp/map.json".to_string()));
        let second =
            build_regulator_counterfactual_sweep(&cartography, Some("/tmp/map.json".to_string()));
        let first_json = serde_json::to_string(&first).expect("serialize first sweep");
        let second_json = serde_json::to_string(&second).expect("serialize second sweep");

        assert_eq!(first.policy, REGULATOR_COUNTERFACTUAL_SWEEP_POLICY);
        assert_eq!(first.authority, "diagnostic_context_not_command");
        assert_eq!(first_json, second_json);
        assert_eq!(first.candidate_count, first.candidates.len());
    }

    #[test]
    fn counterfactual_sweep_includes_all_candidate_families_without_live_tuning() {
        let cartography = build_regulator_boundary_cartography(CartographyGrid::standard());
        let sweep = build_regulator_counterfactual_sweep(&cartography, None);
        let families: BTreeSet<_> = sweep
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_family.as_str())
            .collect();

        assert!(families.contains("pressure_hysteresis"));
        assert!(families.contains("sigmoid_pressure_ramp"));
        assert!(families.contains("thin_density_softening"));
        assert!(families.contains("damping_coefficient_wiring"));
        assert!(families.contains("quality_boundary_margin"));
        assert!(sweep
            .candidates
            .iter()
            .all(|candidate| candidate.authority == "diagnostic_context_not_command"));
        assert!(sweep
            .candidates
            .iter()
            .all(|candidate| candidate.recommendation.contains("Proposal card only")));
    }

    #[test]
    fn pi_pressure_wiring_fixture_replay_is_deterministic_and_schema_valid() {
        let first = build_pi_pressure_wiring_replay_fixture();
        let second = build_pi_pressure_wiring_replay_fixture();
        let first_json = serde_json::to_string(&first).expect("serialize first replay");
        let second_json = serde_json::to_string(&second).expect("serialize second replay");

        assert_eq!(first.policy, PI_PRESSURE_WIRING_REPLAY_POLICY);
        assert_eq!(first.authority, "diagnostic_context_not_command");
        assert_eq!(first.source, "fixture");
        assert!(first.sample_count >= 3);
        assert_eq!(first.candidates.len(), PI_PRESSURE_CANDIDATE_FAMILIES.len());
        assert_eq!(first_json, second_json);
    }

    #[test]
    fn pi_pressure_wiring_replay_includes_all_candidate_families_without_live_tuning() {
        let replay = build_pi_pressure_wiring_replay_fixture();
        let families: BTreeSet<_> = replay
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_family.as_str())
            .collect();

        for family in PI_PRESSURE_CANDIDATE_FAMILIES {
            assert!(families.contains(family), "missing {family}");
        }
        assert!(replay.candidates.iter().all(|candidate| {
            candidate.authority == "diagnostic_context_not_command"
                && candidate.default_off_canary.default_off_env
                    == "MINIME_PI_PRESSURE_WIRING_CANARY"
                && (candidate.recommendation.contains("offline tuning review")
                    || candidate.recommendation.contains("do not tune"))
        }));
    }

    #[test]
    fn pi_pressure_wiring_live_db_gap_is_non_fatal() {
        let replay =
            build_pi_pressure_wiring_replay_live_db(Path::new("/tmp/minime-missing-state.db"), 5);

        assert_eq!(replay.policy, PI_PRESSURE_WIRING_REPLAY_POLICY);
        assert_eq!(replay.source, "live-db");
        assert_eq!(replay.source_status, "telemetry_gap");
        assert_eq!(replay.sample_count, 0);
        assert!(replay
            .recommended_action
            .contains("could not read enough bounded pressure telemetry"));
    }
}
