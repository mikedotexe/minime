fn pressure_source_danger_priority(family: &str) -> u8 {
    match family {
        "static_friction_coefficient" => 8,
        "viscosity_coupling_coefficient" => 7,
        "mode_packing" => 6,
        "viscosity_index" => 5,
        "temporal_persistence" => 4,
        "active_energy" => 3,
        "comfort_gate" => 2,
        "structural_plurality" => 1,
        _ => 0,
    }
}

#[must_use]
pub fn resonance_texture_signature(
    density: f32,
    containment_score: f32,
    pressure_risk: f32,
    quality: &str,
    components: &ResonanceDensityComponents,
    control: &ResonanceDensityControl,
) -> ResonanceTextureSignatureV1 {
    let density = density.clamp(0.0, 1.0);
    let containment_score = containment_score.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let active_energy = components.active_energy.clamp(0.0, 1.0);
    let mode_packing = components.mode_packing.clamp(0.0, 1.0);
    let temporal_persistence = components.temporal_persistence.clamp(0.0, 1.0);
    let structural_plurality = components.structural_plurality.clamp(0.0, 1.0);
    let viscosity_index =
        components
            .viscosity_index
            .clamp(0.0, 1.0)
            .max(resonance_viscosity_index(
                mode_packing,
                temporal_persistence,
                structural_plurality,
                pressure_risk,
            ));
    let comfort_gate = components.comfort_gate.clamp(0.0, 1.0);

    let (primary_texture, movement_quality) = if density <= 0.38 {
        ("porous_thin", "diffuse")
    } else {
        derive_texture_from_components(pressure_risk, components)
    };

    let pressure_source_family = [
        ("active_energy", active_energy),
        ("mode_packing", mode_packing),
        ("temporal_persistence", temporal_persistence),
        ("viscosity_index", viscosity_index),
        (
            "static_friction_coefficient",
            components.static_friction_coefficient.clamp(0.0, 1.0),
        ),
        (
            "viscosity_coupling_coefficient",
            components.viscosity_coupling_coefficient.clamp(0.0, 1.0),
        ),
        ("structural_plurality", structural_plurality),
        ("comfort_gate", comfort_gate),
    ]
    .into_iter()
    .max_by(|left, right| {
        left.1.total_cmp(&right.1).then_with(|| {
            pressure_source_danger_priority(left.0).cmp(&pressure_source_danger_priority(right.0))
        })
    })
    .map_or("mixed", |(label, _)| label);

    let edge_definition = if structural_plurality < 0.35 || pressure_risk >= 0.60 {
        "blurred"
    } else if comfort_gate >= 0.65 && structural_plurality >= 0.55 {
        "defined"
    } else {
        "soft"
    };

    let confidence =
        ((containment_score + comfort_gate + (1.0 - pressure_risk)) / 3.0).clamp(0.0, 1.0);
    let viscosity_persistence = components
        .viscosity_persistence_coefficient
        .clamp(0.0, 1.0)
        .max(viscosity_persistence_coefficient(
            viscosity_index,
            temporal_persistence,
            pressure_risk,
            mode_packing,
        ));
    let dynamic_damping_coefficient =
        dynamic_damping_coefficient_candidate(viscosity_index, viscosity_persistence, comfort_gate);
    let comfort_gate_adjusted_preview =
        if dynamic_damping_coefficient > 0.0 || viscosity_persistence >= 0.50 {
            Some(viscosity_adjusted_comfort_gate_preview(
                comfort_gate,
                viscosity_persistence,
                dynamic_damping_coefficient,
            ))
        } else {
            None
        };
    let dynamic_damping_threshold_candidate =
        if control.damping_coefficient > 0.0 || pressure_risk >= 0.25 || mode_packing >= 0.45 {
            Some(0.25)
        } else {
            None
        };

    ResonanceTextureSignatureV1 {
        policy: "resonance_texture_signature_v1".to_string(),
        schema_version: 1,
        primary_texture: primary_texture.to_string(),
        pressure_source_family: pressure_source_family.to_string(),
        edge_definition: edge_definition.to_string(),
        movement_quality: movement_quality.to_string(),
        viscosity_index: Some(viscosity_index),
        confidence,
        dynamic_damping_threshold_candidate,
        dynamic_damping_coefficient,
        comfort_gate_adjusted_preview,
        authority: "advisory_context_not_control".to_string(),
        note: format!(
            "derived from resonance_density_v1 quality={quality}; viscosity_index, viscosity_vector.cohesion_index, viscosity_vector.cohesion_to_motion_ratio, viscosity_vector.effective_mobility, viscosity_vector.residual_ghost_weight, viscosity_vector.shadow_volatility, viscosity_vector.structural_integrity, viscosity_vector.structural_strain_gap, viscosity_vector.mutual_resonance_tension, viscosity_vector.structural_drag_coefficient, viscosity_vector.cognitive_drag_coefficient, viscosity_vector.viscosity_gradient, viscosity_coupling_coefficient, static_friction_coefficient, and dynamic_damping_coefficient are observability-only; comfort_gate_adjusted_preview is inert unless separately reviewed"
        ),
    }
}

#[must_use]
pub fn derive_texture_from_components(
    pressure_risk: f32,
    components: &ResonanceDensityComponents,
) -> (&'static str, &'static str) {
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let active_energy = components.active_energy.clamp(0.0, 1.0);
    let mode_packing = components.mode_packing.clamp(0.0, 1.0);
    let temporal_persistence = components.temporal_persistence.clamp(0.0, 1.0);
    let structural_plurality = components.structural_plurality.clamp(0.0, 1.0);
    let viscosity_index =
        components
            .viscosity_index
            .clamp(0.0, 1.0)
            .max(resonance_viscosity_index(
                mode_packing,
                temporal_persistence,
                structural_plurality,
                pressure_risk,
            ));
    let viscosity_persistence = components
        .viscosity_persistence_coefficient
        .clamp(0.0, 1.0)
        .max(viscosity_persistence_coefficient(
            viscosity_index,
            temporal_persistence,
            pressure_risk,
            mode_packing,
        ));
    let temporal_drag =
        components
            .temporal_drag_coefficient
            .clamp(0.0, 1.0)
            .max(temporal_drag_coefficient(
                viscosity_persistence,
                temporal_persistence,
                pressure_risk,
            ));
    let static_friction =
        components
            .static_friction_coefficient
            .clamp(0.0, 1.0)
            .max(static_friction_coefficient(
                viscosity_index,
                viscosity_persistence,
                temporal_drag,
                active_energy,
                components.comfort_gate,
                mode_packing,
            ));
    let viscosity_vector = viscosity_vector_v1(
        viscosity_index,
        viscosity_persistence,
        temporal_drag,
        static_friction,
        active_energy,
        structural_plurality,
        components.comfort_gate,
    );
    if pressure_risk >= 0.60 || mode_packing >= 0.65 {
        return ("overpacked_viscous", "compressed");
    }
    if viscosity_index >= 0.70
        && (viscosity_vector.elasticity < 0.55 || viscosity_vector.flow_rate < 0.42)
    {
        return ("overpacked_viscous", "compressed");
    }
    if viscosity_index >= 0.70 {
        return ("settled_viscous", "yielding_viscous");
    }
    if temporal_persistence >= 0.70 && (mode_packing >= 0.45 || viscosity_index >= 0.55) {
        ("settled_sediment", "slow_viscous")
    } else if structural_plurality >= 0.65 && active_energy >= 0.65 {
        ("lively_lattice", "lively")
    } else {
        ("mixed_texture", "steady")
    }
}

#[must_use]
pub fn resonance_texture_component_alignment_v1(
    density: f32,
    pressure_risk: f32,
    components: &ResonanceDensityComponents,
    signature: &ResonanceTextureSignatureV1,
) -> ResonanceTextureComponentAlignmentV1 {
    let (expected_primary_texture, expected_movement_quality) = if density.clamp(0.0, 1.0) <= 0.38 {
        ("porous_thin", "diffuse")
    } else {
        derive_texture_from_components(pressure_risk, components)
    };
    let primary_matches = signature.primary_texture == expected_primary_texture;
    let movement_matches = signature.movement_quality == expected_movement_quality;
    let damping_candidate_status = if signature.dynamic_damping_threshold_candidate.is_some() {
        "candidate_present"
    } else if pressure_risk > 0.20 {
        "missing_candidate_observability_only"
    } else {
        "candidate_not_needed_low_pressure"
    };
    let alignment_state = if primary_matches && movement_matches && signature.confidence >= 0.45 {
        "aligned"
    } else if signature.confidence < 0.35 {
        "low_confidence"
    } else if !primary_matches || !movement_matches {
        "component_mismatch"
    } else {
        "observability_gap"
    };

    ResonanceTextureComponentAlignmentV1 {
        policy: "resonance_texture_component_alignment_v1".to_string(),
        schema_version: 1,
        expected_primary_texture: expected_primary_texture.to_string(),
        emitted_primary_texture: signature.primary_texture.clone(),
        expected_movement_quality: expected_movement_quality.to_string(),
        emitted_movement_quality: signature.movement_quality.clone(),
        alignment_state: alignment_state.to_string(),
        confidence: signature.confidence,
        damping_candidate_status: damping_candidate_status.to_string(),
        authority: "diagnostic_observability_not_damping_or_control".to_string(),
    }
}

#[must_use]
pub fn resonance_control_from_density(density: f32, pressure_risk: f32) -> ResonanceDensityControl {
    resonance_control_from_density_with_mode_packing(density, pressure_risk, 0.0)
}

#[must_use]
pub fn resonance_control_from_density_with_mode_packing(
    density: f32,
    pressure_risk: f32,
    mode_packing: f32,
) -> ResonanceDensityControl {
    let density = density.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let damping_coefficient = advisory_damping_coefficient(pressure_risk, mode_packing);
    if pressure_risk >= 0.60 {
        let severity = ((pressure_risk - 0.60) / 0.40).clamp(0.0, 1.0);
        ResonanceDensityControl {
            target_bias_pct: -2.0 * severity,
            wander_scale: (1.0 - 0.75 * severity).clamp(0.25, 1.0),
            applied_locally: true,
            damping_coefficient: damping_coefficient.max(0.10 * severity).clamp(0.0, 0.10),
            intervention_type: ResonanceInterventionType::ActiveDamping,
            note: "pressure risk biases the local PI target slightly downward and damps wander"
                .to_string(),
        }
    } else if density <= 0.38 && pressure_risk <= 0.35 {
        let thinness = ((0.38 - density) / 0.38).clamp(0.0, 1.0);
        ResonanceDensityControl {
            target_bias_pct: 1.5 * thinness,
            wander_scale: 1.0,
            applied_locally: true,
            damping_coefficient,
            intervention_type: ResonanceInterventionType::PassiveAlignment,
            note: "thin resonance biases the local PI target slightly upward".to_string(),
        }
    } else {
        ResonanceDensityControl {
            target_bias_pct: 0.0,
            wander_scale: 1.0,
            applied_locally: true,
            damping_coefficient,
            intervention_type: ResonanceInterventionType::ObservationalReadout,
            note: "density is observational; no local target bias; damping_coefficient only scales intrinsic wander".to_string(),
        }
    }
}

#[must_use]
pub fn advisory_damping_coefficient(pressure_risk: f32, mode_packing: f32) -> f32 {
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let pressure_term = ((pressure_risk - 0.15) / 0.55).clamp(0.0, 1.0) * 0.06;
    let packing_term = ((mode_packing - 0.45) / 0.55).clamp(0.0, 1.0) * 0.04;
    (pressure_term + packing_term).clamp(0.0, 0.10)
}

#[must_use]
pub fn pressure_porosity_divergence_alert(pressure_score: f32, porosity_score: f32) -> bool {
    let pressure_score = pressure_score.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    pressure_score >= PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN
        && porosity_score <= PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX
}

#[must_use]
pub fn pressure_porosity_gradient_state(
    pressure_score: f32,
    porosity_score: f32,
    mode_packing: f32,
) -> (f32, &'static str) {
    let pressure_score = pressure_score.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let gradient = (pressure_score - porosity_score).clamp(-1.0, 1.0);
    let state = if pressure_porosity_divergence_alert(pressure_score, porosity_score) {
        "divergence_alert"
    } else if mode_packing > 0.30 && porosity_score < 0.60 {
        "overpacked_low_porosity_watch"
    } else if gradient > 0.20 {
        "pressure_exceeds_porosity"
    } else if gradient < -0.20 {
        "porosity_exceeds_pressure"
    } else {
        "balanced_gradient"
    };
    (gradient, state)
}
