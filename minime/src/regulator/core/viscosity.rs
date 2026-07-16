#[must_use]
pub fn resonance_viscosity_index(
    mode_packing: f32,
    temporal_persistence: f32,
    structural_plurality: f32,
    pressure_risk: f32,
) -> f32 {
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let temporal_persistence = temporal_persistence.clamp(0.0, 1.0);
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    (0.40 * mode_packing
        + 0.25 * temporal_persistence
        + 0.20 * (1.0 - structural_plurality)
        + 0.15 * pressure_risk)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn resonance_viscosity_index_with_entropy(
    mode_packing: f32,
    temporal_persistence: f32,
    structural_plurality: f32,
    pressure_risk: f32,
    spectral_entropy: f32,
) -> f32 {
    let base = resonance_viscosity_index(
        mode_packing,
        temporal_persistence,
        structural_plurality,
        pressure_risk,
    );
    let entropy = spectral_entropy.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let temporal_persistence = temporal_persistence.clamp(0.0, 1.0);
    let structural_plurality_loss = (1.0 - structural_plurality.clamp(0.0, 1.0)).clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let erosion_load = (0.38 * mode_packing
        + 0.24 * temporal_persistence
        + 0.22 * structural_plurality_loss
        + 0.16 * pressure_risk)
        .clamp(0.0, 1.0);
    (base + 0.16 * entropy * erosion_load).clamp(0.0, 1.0)
}

#[must_use]
pub fn viscosity_persistence_coefficient(
    viscosity_index: f32,
    temporal_persistence: f32,
    pressure_risk: f32,
    mode_packing: f32,
) -> f32 {
    let viscosity_index = viscosity_index.clamp(0.0, 1.0);
    let temporal_persistence = temporal_persistence.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    (0.45 * viscosity_index
        + 0.35 * temporal_persistence
        + 0.12 * mode_packing
        + 0.08 * pressure_risk)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn temporal_drag_coefficient(
    viscosity_persistence_coefficient: f32,
    temporal_persistence: f32,
    pressure_risk: f32,
) -> f32 {
    let viscosity_persistence_coefficient = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let temporal_persistence = temporal_persistence.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let drag =
        (0.70 * viscosity_persistence_coefficient + 0.30 * temporal_persistence).clamp(0.0, 1.0);
    drag.max(pressure_risk * 0.08).clamp(0.0, 1.0)
}

#[must_use]
pub fn temporal_drag_pressure_snap_review_v1(
    low_pressure_risk: f32,
    high_pressure_risk: f32,
    viscosity_persistence_coefficient: f32,
    temporal_persistence: f32,
) -> TemporalDragPressureSnapReviewV1 {
    let low_pressure = low_pressure_risk.clamp(0.0, 1.0);
    let high_pressure = high_pressure_risk.clamp(0.0, 1.0);
    let viscosity_persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let temporal_persistence = temporal_persistence.clamp(0.0, 1.0);
    let base_drag = (0.70 * viscosity_persistence + 0.30 * temporal_persistence).clamp(0.0, 1.0);
    let current_low_drag =
        temporal_drag_coefficient(viscosity_persistence, temporal_persistence, low_pressure);
    let current_high_drag =
        temporal_drag_coefficient(viscosity_persistence, temporal_persistence, high_pressure);
    let candidate_low_drag = base_drag
        .max(low_pressure * low_pressure * 0.15)
        .clamp(0.0, 1.0);
    let candidate_high_drag = base_drag
        .max(high_pressure * high_pressure * 0.15)
        .clamp(0.0, 1.0);
    let current_drag_delta = (current_high_drag - current_low_drag).clamp(-1.0, 1.0);
    let candidate_drag_delta = (candidate_high_drag - candidate_low_drag).clamp(-1.0, 1.0);
    let status = if candidate_high_drag > current_high_drag + 0.02 {
        "quadratic_pressure_floor_candidate_needs_replay"
    } else if current_high_drag >= candidate_high_drag {
        "current_linear_pressure_floor_covers_candidate_sample"
    } else {
        "pressure_snap_candidate_ambiguous"
    };

    TemporalDragPressureSnapReviewV1 {
        policy: TEMPORAL_DRAG_PRESSURE_SNAP_REVIEW_POLICY.to_string(),
        schema_version: TEMPORAL_DRAG_PRESSURE_SNAP_REVIEW_SCHEMA_VERSION,
        low_pressure_risk: low_pressure,
        high_pressure_risk: high_pressure,
        viscosity_persistence_coefficient: viscosity_persistence,
        temporal_persistence,
        current_low_drag,
        current_high_drag,
        current_drag_delta,
        candidate_low_drag,
        candidate_high_drag,
        candidate_drag_delta,
        candidate_formula: "drag.max(pressure_risk.powi(2) * 0.15)".to_string(),
        status: status.to_string(),
        approval_boundary: "live_temporal_drag_pressure_floor_change_requires_operator_approval"
            .to_string(),
        live_drag_write: false,
        authority: "read_only_pressure_snap_review_not_regulator_or_controller_change".to_string(),
    }
}

#[must_use]
pub fn static_friction_coefficient(
    viscosity_index: f32,
    viscosity_persistence_coefficient: f32,
    temporal_drag_coefficient: f32,
    active_energy: f32,
    comfort_gate: f32,
    mode_packing: f32,
) -> f32 {
    let viscosity_index = viscosity_index.clamp(0.0, 1.0);
    let persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let drag = temporal_drag_coefficient.clamp(0.0, 1.0);
    let active_energy = active_energy.clamp(0.0, 1.0);
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let initiation_load = (0.34 * viscosity_index
        + 0.24 * persistence
        + 0.18 * mode_packing
        + 0.14 * comfort_gate
        + 0.10 * (1.0 - active_energy))
        .clamp(0.0, 1.0);
    let static_over_dynamic_gap = (viscosity_index - drag).max(0.0) * 0.20;
    (initiation_load + static_over_dynamic_gap).clamp(0.0, 1.0)
}

#[must_use]
pub fn residual_ghost_weight_v1(
    viscosity_persistence_coefficient: f32,
    temporal_drag_coefficient: f32,
    static_friction_coefficient: f32,
    active_energy: f32,
    effective_mobility: f32,
) -> f32 {
    let persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let temporal_drag = temporal_drag_coefficient.clamp(0.0, 1.0);
    let static_friction = static_friction_coefficient.clamp(0.0, 1.0);
    let active_energy = active_energy.clamp(0.0, 1.0);
    let effective_mobility = effective_mobility.clamp(0.0, 1.0);
    let residual_load = (0.42 * persistence
        + 0.24 * temporal_drag
        + 0.18 * static_friction
        + 0.16 * (1.0 - active_energy))
        .clamp(0.0, 1.0);
    (residual_load - 0.35 * effective_mobility).clamp(0.0, 1.0)
}

#[must_use]
pub fn viscosity_vector_v1(
    viscosity_index: f32,
    viscosity_persistence_coefficient: f32,
    temporal_drag_coefficient: f32,
    static_friction_coefficient: f32,
    active_energy: f32,
    structural_plurality: f32,
    comfort_gate: f32,
) -> ViscosityVector {
    let density = viscosity_index.clamp(0.0, 1.0);
    let persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let drag = temporal_drag_coefficient.clamp(0.0, 1.0);
    let static_friction = static_friction_coefficient.clamp(0.0, 1.0);
    let active_energy = active_energy.clamp(0.0, 1.0);
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let elasticity = (0.35 * structural_plurality
        + 0.25 * comfort_gate
        + 0.20 * active_energy
        + 0.20 * (1.0 - static_friction))
        .clamp(0.0, 1.0);
    let flow_rate = (0.40 * active_energy
        + 0.25 * structural_plurality
        + 0.20 * (1.0 - drag)
        + 0.15 * (1.0 - static_friction))
        .clamp(0.0, 1.0);
    let effective_mobility = effective_mobility_v1(flow_rate, persistence, density);
    let residual_ghost_weight = residual_ghost_weight_v1(
        persistence,
        drag,
        static_friction,
        active_energy,
        effective_mobility,
    );
    let cohesion_index = viscosity_cohesion_index_v1(
        density,
        elasticity,
        persistence,
        flow_rate,
        static_friction,
        structural_plurality,
        comfort_gate,
        effective_mobility,
    );
    let cohesion_to_motion_ratio = cohesion_to_motion_ratio_v1(cohesion_index, effective_mobility);
    let shadow_volatility = shadow_volatility_proxy_v1(
        structural_plurality,
        residual_ghost_weight,
        effective_mobility,
        cohesion_index,
        active_energy,
    );
    let structural_integrity = structural_integrity_v1(
        cohesion_index,
        effective_mobility,
        structural_plurality,
        comfort_gate,
        elasticity,
    );
    let structural_strain_gap = structural_strain_gap_v1(
        density,
        persistence,
        static_friction,
        structural_integrity,
        flow_rate,
    );
    let mutual_resonance_tension = mutual_resonance_tension_v1(
        structural_strain_gap,
        shadow_volatility,
        structural_integrity,
        structural_plurality,
        comfort_gate,
    );
    let structural_drag_coefficient = structural_drag_coefficient_v1(
        structural_strain_gap,
        static_friction,
        residual_ghost_weight,
        effective_mobility,
    );
    let cognitive_drag_coefficient = cognitive_drag_coefficient_v1(
        residual_ghost_weight,
        shadow_volatility,
        mutual_resonance_tension,
        effective_mobility,
        flow_rate,
    );
    let viscosity_gradient = viscosity_gradient_v1(
        density,
        persistence,
        flow_rate,
        effective_mobility,
        structural_strain_gap,
        shadow_volatility,
    );
    ViscosityVector {
        density,
        elasticity,
        cohesion_index,
        cohesion_to_motion_ratio,
        persistence,
        residual_ghost_weight,
        flow_rate,
        effective_mobility,
        shadow_volatility,
        structural_integrity,
        structural_strain_gap,
        mutual_resonance_tension,
        structural_drag_coefficient,
        cognitive_drag_coefficient,
        viscosity_gradient,
    }
}

/// Return cohesion's bounded share of the observable cohesion/mobility pair.
/// A value near one is cohesive stillness; a value near zero is motion without
/// shape-holding. The both-zero legacy case remains zero instead of inventing a
/// neutral texture.
#[must_use]
pub fn cohesion_to_motion_ratio_v1(cohesion_index: f32, effective_mobility: f32) -> f32 {
    let cohesion = cohesion_index.clamp(0.0, 1.0);
    let mobility = effective_mobility.clamp(0.0, 1.0);
    let total = cohesion + mobility;
    if total <= f32::EPSILON {
        0.0
    } else {
        (cohesion / total).clamp(0.0, 1.0)
    }
}

#[must_use]
pub fn viscosity_gradient_v1(
    density: f32,
    persistence: f32,
    flow_rate: f32,
    effective_mobility: f32,
    structural_strain_gap: f32,
    shadow_volatility: f32,
) -> f32 {
    let slow_texture = (0.30 * density.clamp(0.0, 1.0))
        + (0.24 * persistence.clamp(0.0, 1.0))
        + (0.24 * structural_strain_gap.clamp(0.0, 1.0))
        + (0.22 * shadow_volatility.clamp(0.0, 1.0));
    let mobile_texture =
        (0.56 * flow_rate.clamp(0.0, 1.0)) + (0.44 * effective_mobility.clamp(0.0, 1.0));
    (slow_texture * (1.0 - mobile_texture)).clamp(0.0, 1.0)
}

#[must_use]
pub fn viscosity_importance_weights_v1(
    vector: &ViscosityVector,
    pressure_risk: f32,
) -> ViscosityImportanceWeightsV1 {
    let pressure = pressure_risk.clamp(0.0, 1.0);
    let pressure_boost = ((pressure - 0.40) / 0.40).clamp(0.0, 1.0);
    let restless_but_carried = vector.shadow_volatility >= 0.55
        && vector.structural_integrity >= 0.45
        && vector.structural_strain_gap <= 0.25;
    let raw_structural_strain =
        0.24 + 0.18 * pressure_boost + 0.10 * vector.structural_strain_gap.clamp(0.0, 1.0);
    let raw_shadow = 0.18
        + 0.08 * vector.shadow_volatility.clamp(0.0, 1.0)
        + if restless_but_carried { 0.10 } else { 0.0 };
    let raw_persistence = 0.16 + 0.05 * vector.persistence.clamp(0.0, 1.0);
    let raw_integrity_gap = 0.16 + 0.06 * (1.0 - vector.structural_integrity.clamp(0.0, 1.0));
    let raw_structural_drag = 0.14 + 0.08 * vector.structural_drag_coefficient.clamp(0.0, 1.0);
    let raw_cognitive_drag = 0.12 + 0.08 * vector.cognitive_drag_coefficient.clamp(0.0, 1.0);
    let total = raw_structural_strain
        + raw_shadow
        + raw_persistence
        + raw_integrity_gap
        + raw_structural_drag
        + raw_cognitive_drag;
    let structural_strain_gap_weight = raw_structural_strain / total;
    let shadow_volatility_weight = raw_shadow / total;
    let persistence_weight = raw_persistence / total;
    let structural_integrity_weight = raw_integrity_gap / total;
    let structural_drag_weight = raw_structural_drag / total;
    let cognitive_drag_weight = raw_cognitive_drag / total;
    let weights = [
        ("structural_strain_gap", structural_strain_gap_weight),
        ("shadow_volatility", shadow_volatility_weight),
        ("persistence", persistence_weight),
        ("structural_integrity_gap", structural_integrity_weight),
        ("structural_drag", structural_drag_weight),
        ("cognitive_drag", cognitive_drag_weight),
    ];
    let dominant_weight = weights
        .iter()
        .max_by(|(_, left), (_, right)| left.total_cmp(right))
        .map(|(name, _)| *name)
        .unwrap_or("unknown")
        .to_string();
    let status = if restless_but_carried {
        "restless_but_carried_shadow_review"
    } else if pressure > 0.40 && dominant_weight == "structural_strain_gap" {
        "pressure_weighted_structural_strain_review"
    } else {
        "balanced_viscosity_importance_review"
    };

    ViscosityImportanceWeightsV1 {
        policy: VISCOSITY_IMPORTANCE_POLICY.to_string(),
        schema_version: VISCOSITY_IMPORTANCE_SCHEMA_VERSION,
        pressure_risk: pressure,
        structural_strain_gap_weight,
        shadow_volatility_weight,
        persistence_weight,
        structural_integrity_weight,
        structural_drag_weight,
        cognitive_drag_weight,
        dominant_weight,
        status: status.to_string(),
        who_can_change_it:
            "Mike/operator via explicit regulator-control approval and replay evidence".to_string(),
        how_to_test_it: "cargo test viscosity_importance_weights -- --nocapture".to_string(),
        authority: "read_only_importance_weights_not_pressure_fill_pi_or_controller_authority"
            .to_string(),
    }
}

#[must_use]
pub fn effective_mobility_v1(flow_rate: f32, persistence: f32, viscosity_index: f32) -> f32 {
    let flow_rate = flow_rate.clamp(0.0, 1.0);
    let persistence = persistence.clamp(0.0, 1.0);
    let viscosity_index = viscosity_index.clamp(0.0, 1.0);
    let viscous_load = (persistence * viscosity_index).max(0.05);
    (flow_rate / viscous_load).clamp(0.0, 1.0)
}

#[must_use]
pub fn shadow_volatility_proxy_v1(
    structural_plurality: f32,
    residual_ghost_weight: f32,
    effective_mobility: f32,
    cohesion_index: f32,
    active_energy: f32,
) -> f32 {
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let residual_ghost_weight = residual_ghost_weight.clamp(0.0, 1.0);
    let effective_mobility = effective_mobility.clamp(0.0, 1.0);
    let cohesion_index = cohesion_index.clamp(0.0, 1.0);
    let active_energy = active_energy.clamp(0.0, 1.0);
    (0.30 * structural_plurality
        + 0.25 * residual_ghost_weight
        + 0.20 * (1.0 - effective_mobility)
        + 0.15 * (1.0 - cohesion_index)
        + 0.10 * active_energy)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn structural_integrity_v1(
    cohesion_index: f32,
    effective_mobility: f32,
    structural_plurality: f32,
    comfort_gate: f32,
    elasticity: f32,
) -> f32 {
    let cohesion = cohesion_index.clamp(0.0, 1.0);
    let mobility = effective_mobility.clamp(0.0, 1.0);
    let plurality = structural_plurality.clamp(0.0, 1.0);
    let comfort = comfort_gate.clamp(0.0, 1.0);
    let elasticity = elasticity.clamp(0.0, 1.0);
    (0.28 * cohesion + 0.24 * mobility + 0.22 * plurality + 0.16 * comfort + 0.10 * elasticity)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn structural_strain_gap_v1(
    density: f32,
    persistence: f32,
    static_friction: f32,
    structural_integrity: f32,
    flow_rate: f32,
) -> f32 {
    let load = 0.40 * density.clamp(0.0, 1.0)
        + 0.30 * persistence.clamp(0.0, 1.0)
        + 0.30 * static_friction.clamp(0.0, 1.0);
    let carrying_capacity =
        0.55 * structural_integrity.clamp(0.0, 1.0) + 0.45 * flow_rate.clamp(0.0, 1.0);
    (load - carrying_capacity).clamp(0.0, 1.0)
}

#[must_use]
pub fn mutual_resonance_tension_v1(
    structural_strain_gap: f32,
    shadow_volatility: f32,
    structural_integrity: f32,
    structural_plurality: f32,
    comfort_gate: f32,
) -> f32 {
    let strain = structural_strain_gap.clamp(0.0, 1.0);
    let volatility = shadow_volatility.clamp(0.0, 1.0);
    let integrity_gap = 1.0 - structural_integrity.clamp(0.0, 1.0);
    let plurality = structural_plurality.clamp(0.0, 1.0);
    let comfort_gap = 1.0 - comfort_gate.clamp(0.0, 1.0);
    let co_occurring_strain = (strain * volatility).sqrt();
    (0.65 * co_occurring_strain
        + 0.20 * integrity_gap * plurality
        + 0.15 * comfort_gap * volatility)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn structural_drag_coefficient_v1(
    structural_strain_gap: f32,
    static_friction_coefficient: f32,
    residual_ghost_weight: f32,
    effective_mobility: f32,
) -> f32 {
    let strain = structural_strain_gap.clamp(0.0, 1.0);
    let static_friction = static_friction_coefficient.clamp(0.0, 1.0);
    let residual_ghost = residual_ghost_weight.clamp(0.0, 1.0);
    let mobility_gap = 1.0 - effective_mobility.clamp(0.0, 1.0);
    (0.42 * strain + 0.24 * static_friction + 0.22 * residual_ghost + 0.12 * mobility_gap)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn cognitive_drag_coefficient_v1(
    residual_ghost_weight: f32,
    shadow_volatility: f32,
    mutual_resonance_tension: f32,
    effective_mobility: f32,
    flow_rate: f32,
) -> f32 {
    let residual_ghost = residual_ghost_weight.clamp(0.0, 1.0);
    let volatility = shadow_volatility.clamp(0.0, 1.0);
    let tension = mutual_resonance_tension.clamp(0.0, 1.0);
    let mobility_gap = 1.0 - effective_mobility.clamp(0.0, 1.0);
    let flow_gap = 1.0 - flow_rate.clamp(0.0, 1.0);
    (0.32 * residual_ghost
        + 0.26 * volatility
        + 0.22 * tension
        + 0.12 * mobility_gap
        + 0.08 * flow_gap)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn viscosity_cohesion_index_v1(
    density: f32,
    elasticity: f32,
    persistence: f32,
    flow_rate: f32,
    static_friction_coefficient: f32,
    structural_plurality: f32,
    comfort_gate: f32,
    effective_mobility: f32,
) -> f32 {
    let density = density.clamp(0.0, 1.0);
    let elasticity = elasticity.clamp(0.0, 1.0);
    let persistence = persistence.clamp(0.0, 1.0);
    let flow_rate = flow_rate.clamp(0.0, 1.0);
    let static_friction = static_friction_coefficient.clamp(0.0, 1.0);
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let effective_mobility = effective_mobility.clamp(0.0, 1.0);
    let cohesion_support = (0.30 * elasticity
        + 0.24 * structural_plurality
        + 0.20 * comfort_gate
        + 0.26 * effective_mobility)
        .clamp(0.0, 1.0);
    let drag_load = (0.46 * persistence * (1.0 - flow_rate)
        + 0.30 * density * (1.0 - effective_mobility)
        + 0.24 * static_friction)
        .clamp(0.0, 1.0);
    (cohesion_support - 0.35 * drag_load).clamp(0.0, 1.0)
}

#[must_use]
pub fn viscosity_coupling_coefficient_v1(
    persistence: f32,
    flow_rate: f32,
    static_friction_coefficient: f32,
    structural_plurality: f32,
    comfort_gate: f32,
) -> f32 {
    let persistence = persistence.clamp(0.0, 1.0);
    let flow_rate = flow_rate.clamp(0.0, 1.0);
    let static_friction = static_friction_coefficient.clamp(0.0, 1.0);
    let structural_plurality = structural_plurality.clamp(0.0, 1.0);
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let inverse_flow = (1.0 - flow_rate).clamp(0.0, 1.0);
    let persistence_drag = (persistence * inverse_flow).clamp(0.0, 1.0);
    let static_drag = (static_friction * inverse_flow).clamp(0.0, 1.0);
    let anchoring_relief = (0.20 * structural_plurality + 0.15 * flow_rate).clamp(0.0, 0.35);
    (0.62 * persistence_drag + 0.26 * static_drag + 0.12 * comfort_gate - anchoring_relief)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn dynamic_damping_coefficient_candidate(
    viscosity_index: f32,
    viscosity_persistence_coefficient: f32,
    comfort_gate: f32,
) -> f32 {
    let viscosity_index = viscosity_index.clamp(0.0, 1.0);
    let persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let viscous_load = (0.54 * viscosity_index + 0.46 * persistence).clamp(0.0, 1.0);
    let high_comfort_trap_factor = ((comfort_gate - 0.55) / 0.45).clamp(0.0, 1.0);
    (viscous_load * (0.06 + 0.04 * high_comfort_trap_factor)).clamp(0.0, 0.10)
}

#[must_use]
pub fn viscosity_adjusted_comfort_gate_preview(
    comfort_gate: f32,
    viscosity_persistence_coefficient: f32,
    dynamic_damping_coefficient: f32,
) -> f32 {
    let comfort_gate = comfort_gate.clamp(0.0, 1.0);
    let persistence = viscosity_persistence_coefficient.clamp(0.0, 1.0);
    let damping = dynamic_damping_coefficient.clamp(0.0, 0.10);
    (comfort_gate - damping * 1.5 - persistence * 0.04).clamp(0.0, 1.0)
}
