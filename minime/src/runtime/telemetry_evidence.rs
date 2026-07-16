fn compute_resonance_density_v1(
    eigenvalues: &[f32],
    active_modes: ActiveModeTelemetry,
    effective_dimensionality: Option<f32>,
    distinguishability_loss: Option<f32>,
    structural_entropy: f32,
    fill_pct: f32,
    target_fill_pct: f32,
    previous_eigenvalues: Option<&[f32]>,
) -> ResonanceDensityV1 {
    let shares = normalized_energy_shares(eigenvalues);
    let active_capacity = shares.len().max(1) as f32;
    let lambda1_share = shares.first().copied().unwrap_or(0.0);
    let entropy = normalized_entropy_from_shares(&shares);
    let active_energy = active_modes.energy_ratio.clamp(0.0, 1.0);
    let mode_packing = (active_modes.count as f32 / active_capacity.min(6.0)).clamp(0.0, 1.0);
    let temporal_persistence = share_temporal_persistence(&shares, previous_eigenvalues);
    let effective_norm = effective_dimensionality
        .map(|value| (value / active_capacity).clamp(0.0, 1.0))
        .unwrap_or(if shares.is_empty() { 0.0 } else { mode_packing });
    let structural_plurality = (0.38 * entropy + 0.34 * structural_entropy + 0.28 * effective_norm)
        * (1.0 - 0.55 * lambda1_share.powf(1.4)).clamp(0.25, 1.0);
    let comfort_gate = (1.0 - ((fill_pct - target_fill_pct).abs() / 24.0)).clamp(0.0, 1.0);
    let overfill_pressure = ((fill_pct - (target_fill_pct + 4.0)) / 16.0).clamp(0.0, 1.0);
    let loss = distinguishability_loss
        .unwrap_or(1.0 - effective_norm)
        .clamp(0.0, 1.0);
    let pressure_risk =
        (0.36 * lambda1_share + 0.24 * loss + 0.20 * (1.0 - entropy) + 0.20 * overfill_pressure)
            .clamp(0.0, 1.0);
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let viscosity_index = resonance_viscosity_index_with_entropy(
        mode_packing,
        temporal_persistence,
        structural_plurality,
        pressure_risk,
        entropy,
    );
    let density = (0.30 * active_energy
        + 0.20 * mode_packing
        + 0.20 * temporal_persistence
        + 0.20 * structural_plurality
        + 0.10 * comfort_gate)
        .clamp(0.0, 1.0);
    let containment_score = (density
        * (0.55 + 0.45 * temporal_persistence)
        * (0.65 + 0.35 * comfort_gate)
        * (1.0 - 0.45 * pressure_risk))
        .clamp(0.0, 1.0);
    let quality = if pressure_risk >= 0.68 && density >= 0.55 {
        "overpacked_pressure"
    } else if lambda1_share >= 0.62 && structural_plurality < 0.45 {
        "lambda_monopoly"
    } else if density < 0.32 && containment_score < 0.30 {
        "lonely_diffuse"
    } else if containment_score >= 0.58 && pressure_risk < 0.45 {
        "rich_containment"
    } else if density >= 0.45 && pressure_risk < 0.60 {
        "forming_containment"
    } else {
        "mixed"
    };
    ResonanceDensityV1::from_parts(
        density,
        containment_score,
        pressure_risk,
        quality,
        ResonanceDensityComponents {
            active_energy,
            mode_packing,
            temporal_persistence,
            viscosity_index,
            viscosity_persistence_coefficient: viscosity_persistence_coefficient(
                viscosity_index,
                temporal_persistence,
                pressure_risk,
                mode_packing,
            ),
            temporal_drag_coefficient: 0.0,
            static_friction_coefficient: 0.0,
            viscosity_vector: ViscosityVector::default(),
            viscosity_coupling_coefficient: 0.0,
            structural_plurality,
            comfort_gate,
        },
    )
}

fn source_scarcity_score(source: &str) -> f32 {
    match source {
        "absent" => 0.65,
        "stale" => 0.45,
        "synthetic" => 0.25,
        "mixed" => 0.12,
        "fresh" | "external" => 0.0,
        _ => 0.30,
    }
}

fn sensory_scarcity_from_sources(audio_source: &str, video_source: &str) -> f32 {
    (0.5 * source_scarcity_score(audio_source) + 0.5 * source_scarcity_score(video_source))
        .clamp(0.0, 1.0)
}

fn semantic_trickle_pressure(semantic: &SemanticEnergyV1) -> f32 {
    let admission_pressure = if semantic.admission.contains("trickle")
        || semantic.admission.contains("muted")
        || semantic.admission.contains("zeroed")
    {
        0.25
    } else {
        0.0
    };
    if !(semantic.input_active || semantic.kernel_active) {
        return admission_pressure;
    }
    (0.35 * (semantic.input_energy / 0.006).clamp(0.0, 1.0)
        + 0.30 * (semantic.kernel_energy / 0.003).clamp(0.0, 1.0)
        + 0.20 * (semantic.regulator_drive_energy / 0.010).clamp(0.0, 1.0)
        + admission_pressure)
        .clamp(0.0, 1.0)
}

fn compute_pressure_source_v1(
    eigenvalues: &[f32],
    active_modes: ActiveModeTelemetry,
    resonance: &ResonanceDensityV1,
    effective_dimensionality: Option<f32>,
    distinguishability_loss: Option<f32>,
    structural_entropy: f32,
    mean_orientation_delta: Option<f32>,
    fill_pct: f32,
    target_fill_pct: f32,
    semantic: &SemanticEnergyV1,
    audio_source: &str,
    video_source: &str,
) -> PressureSourceV1 {
    let shares = normalized_energy_shares(eigenvalues);
    let active_capacity = shares.len().max(1) as f32;
    let lambda1_share = shares.first().copied().unwrap_or(0.0);
    let entropy = normalized_entropy_from_shares(&shares);
    let effective_norm = effective_dimensionality
        .map(|value| (value / active_capacity).clamp(0.0, 1.0))
        .unwrap_or(1.0 - distinguishability_loss.unwrap_or(0.0).clamp(0.0, 1.0));
    let distinguishability_loss = distinguishability_loss
        .unwrap_or(1.0 - effective_norm)
        .clamp(0.0, 1.0);
    let structural_plurality_loss = (1.0
        - (0.55 * resonance.components.structural_plurality
            + 0.45 * structural_entropy.clamp(0.0, 1.0)))
    .clamp(0.0, 1.0);
    let lambda_monopoly_base = (0.55 * lambda1_share
        + 0.25 * (1.0 - entropy)
        + 0.20 * (1.0 - structural_entropy.clamp(0.0, 1.0)))
    .clamp(0.0, 1.0);
    let lambda_monopoly = if lambda1_share >= 0.62 {
        lambda_monopoly_base.max(structural_plurality_loss)
    } else {
        lambda_monopoly_base
    };
    let raw_mode_packing = (0.70 * resonance.components.mode_packing
        + 0.30 * (active_modes.count as f32 / active_capacity.min(6.0)))
    .clamp(0.0, 1.0);
    let mode_packing = (raw_mode_packing
        * (0.35 + 0.65 * resonance.pressure_risk.max(structural_plurality_loss)))
    .clamp(0.0, 1.0);
    let fill_gap = fill_pct - target_fill_pct;
    let controller_pressure = (0.65 * (fill_gap.max(0.0) / 12.0).clamp(0.0, 1.0)
        + 0.35 * (fill_gap.abs() / 24.0).clamp(0.0, 1.0))
    .clamp(0.0, 1.0);
    let temporal_lock_in = (resonance.components.temporal_persistence
        * (0.45 + 0.55 * resonance.pressure_risk))
        .clamp(0.0, 1.0);
    let semantic_trickle = semantic_trickle_pressure(semantic);
    let semantic_friction = semantic_friction_from_parts(
        semantic_trickle,
        structural_plurality_loss,
        distinguishability_loss,
    );
    let components = PressureSourceComponents {
        lambda_monopoly,
        mode_packing,
        controller_pressure,
        semantic_trickle,
        semantic_friction,
        structural_plurality_loss,
        distinguishability_loss,
        temporal_lock_in,
        sensory_scarcity: sensory_scarcity_from_sources(audio_source, video_source),
    };
    PressureSourceV1::from_parts(
        components,
        PressureSourceContext {
            mean_orientation_delta,
            ..PressureSourceContext::default()
        },
    )
}

fn share_rearrangement_score(
    current_eigenvalues: &[f32],
    previous_eigenvalues: Option<&[f32]>,
) -> (f32, f32, bool) {
    let Some(previous_eigenvalues) = previous_eigenvalues else {
        return (0.20, 0.20, false);
    };
    let current = normalized_energy_shares(current_eigenvalues);
    let previous = normalized_energy_shares(previous_eigenvalues);
    if current.is_empty() || previous.is_empty() {
        return (0.20, 0.20, false);
    }
    let len = current.len().max(previous.len());
    let distance = (0..len)
        .map(|index| {
            let current_share = current.get(index).copied().unwrap_or(0.0);
            let previous_share = previous.get(index).copied().unwrap_or(0.0);
            (current_share - previous_share).abs()
        })
        .sum::<f32>();
    let share_rearrangement = (0.5 * distance).clamp(0.0, 1.0);
    let anchor_delta = (current.first().copied().unwrap_or(0.0)
        - previous.first().copied().unwrap_or(0.0))
    .abs()
    .clamp(0.0, 1.0);
    (share_rearrangement, anchor_delta, true)
}

fn eigenvector_reorientation_from_field(eigenvector_field: &serde_json::Value) -> f32 {
    let summary = eigenvector_field.get("summary");
    let has_previous = summary
        .and_then(|value| value.get("previous_overlap_available"))
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    if !has_previous {
        return 0.20;
    }
    summary
        .and_then(|value| value.get("mean_orientation_delta"))
        .and_then(serde_json::Value::as_f64)
        .map(|value| (value as f32).clamp(0.0, 1.0))
        .unwrap_or(0.20)
}

fn basin_transition_pressure_from_event(
    transition_event_v1: &serde_json::Value,
    transition_event_active: bool,
) -> f32 {
    if !transition_event_active {
        return 0.0;
    }
    transition_event_v1
        .get("basin_shift_score")
        .and_then(serde_json::Value::as_f64)
        .map(|value| (value as f32).clamp(0.0, 1.0))
        .unwrap_or(0.0)
}

fn should_write_phase_transition_moment_marker(
    debounced: bool,
    crossed_target_fill: bool,
    fill_band_crossed: bool,
    spectral_spike: bool,
) -> bool {
    !debounced && !(crossed_target_fill || fill_band_crossed || spectral_spike)
}

fn compute_inhabitable_fluctuation_v1(
    eigenvalues: &[f32],
    previous_eigenvalues: Option<&[f32]>,
    eigenvector_field: &serde_json::Value,
    transition_event_v1: &serde_json::Value,
    transition_event_active: bool,
    resonance: &ResonanceDensityV1,
    pressure: &PressureSourceV1,
    effective_dimensionality: Option<f32>,
    distinguishability_loss: Option<f32>,
) -> InhabitableFluctuationV1 {
    let (share_rearrangement, anchor_delta, previous_sample_available) =
        share_rearrangement_score(eigenvalues, previous_eigenvalues);
    let eigenvector_reorientation = eigenvector_reorientation_from_field(eigenvector_field);
    let basin_transition_pressure =
        basin_transition_pressure_from_event(transition_event_v1, transition_event_active);
    let active_capacity = eigenvalues.len().max(1) as f32;
    let distinguishability = distinguishability_loss
        .unwrap_or_else(|| {
            effective_dimensionality
                .map(|value| 1.0 - (value / active_capacity).clamp(0.0, 1.0))
                .unwrap_or(0.20)
        })
        .clamp(0.0, 1.0);
    let effective_support = effective_dimensionality
        .map(|value| (value / active_capacity).clamp(0.0, 1.0))
        .unwrap_or(1.0 - distinguishability);
    let pressure_interference = pressure
        .pressure_score
        .max(resonance.pressure_risk)
        .max(1.0 - pressure.porosity_score)
        .clamp(0.0, 1.0);
    let continuity_recovery = (0.30 * resonance.containment_score
        + 0.22 * resonance.components.temporal_persistence
        + 0.18 * effective_support
        + 0.16 * (1.0 - share_rearrangement)
        + 0.14 * (1.0 - basin_transition_pressure))
        .clamp(0.0, 1.0);
    let mode_trust_volatility =
        (0.52 * share_rearrangement + 0.28 * eigenvector_reorientation + 0.20 * distinguishability)
            .clamp(0.0, 1.0);
    let identity_anchor_churn =
        (0.48 * anchor_delta + 0.30 * basin_transition_pressure + 0.22 * pressure_interference)
            .clamp(0.0, 1.0);
    InhabitableFluctuationV1::from_parts(
        InhabitableFluctuationComponents {
            mode_trust_volatility,
            identity_anchor_churn,
            eigenvector_reorientation,
            share_rearrangement,
            basin_transition_pressure,
            continuity_recovery,
            porosity_support: pressure.porosity_score,
            pressure_interference,
        },
        InhabitableFluctuationContext {
            previous_sample_available,
            transition_event_active,
            resonance_quality: Some(resonance.quality.clone()),
            pressure_quality: Some(pressure.quality.clone()),
        },
    )
}
