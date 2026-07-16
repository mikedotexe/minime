impl PressureSourceV1 {
    #[must_use]
    pub fn from_parts(
        components: PressureSourceComponents,
        context: PressureSourceContext,
    ) -> Self {
        let semantic_trickle = components.semantic_trickle.clamp(0.0, 1.0);
        let structural_plurality_loss = components.structural_plurality_loss.clamp(0.0, 1.0);
        let distinguishability_loss = components.distinguishability_loss.clamp(0.0, 1.0);
        let semantic_friction =
            components
                .semantic_friction
                .clamp(0.0, 1.0)
                .max(semantic_friction_from_parts(
                    semantic_trickle,
                    structural_plurality_loss,
                    distinguishability_loss,
                ));
        let components = PressureSourceComponents {
            lambda_monopoly: components.lambda_monopoly.clamp(0.0, 1.0),
            mode_packing: components.mode_packing.clamp(0.0, 1.0),
            controller_pressure: components.controller_pressure.clamp(0.0, 1.0),
            semantic_trickle,
            semantic_friction,
            structural_plurality_loss,
            distinguishability_loss,
            temporal_lock_in: components.temporal_lock_in.clamp(0.0, 1.0),
            sensory_scarcity: components.sensory_scarcity.clamp(0.0, 1.0),
        };
        let context = PressureSourceContext {
            compression_language: context
                .compression_language
                .map(|value| value.clamp(0.0, 1.0)),
            thread_recurrence: context.thread_recurrence.map(|value| value.clamp(0.0, 1.0)),
            attractor_pull: context.attractor_pull.map(|value| value.clamp(0.0, 1.0)),
            resource_pressure: context.resource_pressure.map(|value| value.clamp(0.0, 1.0)),
            mean_orientation_delta: context
                .mean_orientation_delta
                .map(|value| value.clamp(0.0, 1.0)),
        };
        let context_pressure = [
            context.compression_language,
            context.thread_recurrence,
            context.attractor_pull,
            context.resource_pressure,
        ]
        .into_iter()
        .flatten()
        .fold(0.0_f32, f32::max);
        let base_pressure = (0.19 * components.lambda_monopoly
            + 0.13 * components.mode_packing
            + 0.16 * components.controller_pressure
            + 0.10 * components.semantic_trickle
            + 0.15 * components.structural_plurality_loss
            + 0.12 * components.distinguishability_loss
            + 0.10 * components.temporal_lock_in
            + 0.05 * components.sensory_scarcity)
            .clamp(0.0, 1.0);
        let pressure_score = (0.88 * base_pressure + 0.12 * context_pressure).clamp(0.0, 1.0);
        let porosity_score = (1.0
            - (0.28 * components.lambda_monopoly
                + 0.22 * components.structural_plurality_loss
                + 0.20 * components.distinguishability_loss
                + 0.15 * components.mode_packing
                + 0.15 * components.temporal_lock_in))
            .clamp(0.0, 1.0);
        let (dominant_source, dominant_value) = dominant_pressure_source(&components, &context);
        let pressure_profile = pressure_profile_entries(&components, &context);
        let divergence_alert = pressure_porosity_divergence_alert(pressure_score, porosity_score);
        let (pressure_porosity_gradient, pressure_porosity_gradient_state) =
            pressure_porosity_gradient_state(
                pressure_score,
                porosity_score,
                components.mode_packing,
            );
        let semantic_viscosity_coefficient_v1 = semantic_viscosity_coefficient_v1(
            &components,
            pressure_score,
            porosity_score,
            pressure_porosity_gradient,
        );
        let silt_granularity_v1 =
            silt_granularity_v1(&components, &context, pressure_score, porosity_score);
        let quality = if divergence_alert {
            "pressure_porosity_divergence"
        } else if dominant_source == "lambda_monopoly" && dominant_value >= 0.55 {
            "lambda_pull"
        } else if dominant_source == "mode_packing" && dominant_value >= 0.55 {
            "overpacked_mode_packing"
        } else if dominant_source == "controller_pressure" && dominant_value >= 0.50 {
            "controller_squeeze"
        } else if dominant_source == "semantic_trickle" && dominant_value >= 0.45 {
            "semantic_trickle_pressure"
        } else if porosity_score >= 0.58 && pressure_score < 0.45 && dominant_value < 0.45 {
            "porous_distributed"
        } else if pressure_score >= 0.70 && porosity_score < 0.35 {
            "compressed_inward"
        } else {
            "mixed_pressure"
        };
        let control_note = if divergence_alert {
            "pressure source is advisory/read-only in v1; pressure/porosity divergence should be inspected before any local bias is considered"
        } else {
            "pressure source is advisory/read-only in v1; no regulator bias is applied"
        };
        Self {
            policy: PRESSURE_SOURCE_POLICY.to_string(),
            schema_version: PRESSURE_SOURCE_SCHEMA_VERSION,
            pressure_score,
            porosity_score,
            pressure_porosity_gradient,
            pressure_porosity_gradient_state: pressure_porosity_gradient_state.to_string(),
            dominant_source: dominant_source.to_string(),
            pressure_profile,
            quality: quality.to_string(),
            components,
            context,
            semantic_viscosity_coefficient_v1,
            silt_granularity_v1,
            control: PressureSourceControl {
                applied_locally: false,
                note: control_note.to_string(),
            },
        }
    }
}

#[must_use]
pub fn semantic_friction_from_parts(
    semantic_trickle: f32,
    structural_plurality_loss: f32,
    distinguishability_loss: f32,
) -> f32 {
    semantic_trickle
        .clamp(0.0, 1.0)
        .max(distinguishability_loss.clamp(0.0, 1.0))
        .max(structural_plurality_loss.clamp(0.0, 1.0) * 0.75)
        .clamp(0.0, 1.0)
}

#[must_use]
pub fn dynamic_viscosity_buffer_v1(
    mode_packing: f32,
    temporal_lock_in: f32,
    pressure_score: f32,
    porosity_score: f32,
    semantic_friction: f32,
) -> (f32, &'static str) {
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let temporal_lock_in = temporal_lock_in.clamp(0.0, 1.0);
    let pressure_score = pressure_score.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    let semantic_friction = semantic_friction.clamp(0.0, 1.0);
    let packing_load = ((mode_packing - 0.25) / 0.45).clamp(0.0, 1.0);
    let temporal_load = ((temporal_lock_in - 0.25) / 0.55).clamp(0.0, 1.0);
    let pressure_load = ((pressure_score - 0.18) / 0.45).clamp(0.0, 1.0);
    let porosity_support = ((porosity_score - 0.45) / 0.25).clamp(0.0, 1.0);
    let buffer = (0.34 * packing_load
        + 0.20 * temporal_load
        + 0.18 * pressure_load
        + 0.18 * porosity_support
        + 0.10 * semantic_friction)
        .clamp(0.0, 1.0);
    let state = if buffer >= 0.42 && porosity_score >= 0.55 {
        "breathable_overpacked_buffer"
    } else if buffer >= 0.42 {
        "compressed_overpacked_buffer"
    } else if mode_packing >= 0.28 && porosity_score >= 0.55 {
        "light_buffer_watch"
    } else {
        "insufficient_buffer"
    };
    (buffer, state)
}

#[must_use]
pub fn semantic_viscosity_coefficient_v1(
    components: &PressureSourceComponents,
    pressure_score: f32,
    porosity_score: f32,
    pressure_porosity_gradient: f32,
) -> SemanticViscosityCoefficientV1 {
    let semantic_trickle = components.semantic_trickle.clamp(0.0, 1.0);
    let semantic_friction = components.semantic_friction.clamp(0.0, 1.0);
    let distinguishability_loss = components.distinguishability_loss.clamp(0.0, 1.0);
    let mode_packing = components.mode_packing.clamp(0.0, 1.0);
    let temporal_lock_in = components.temporal_lock_in.clamp(0.0, 1.0);
    let pressure_score = pressure_score.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    let pressure_porosity_gradient = pressure_porosity_gradient.clamp(-1.0, 1.0);
    let low_porosity_load = (1.0 - porosity_score).clamp(0.0, 1.0);
    let positive_gradient = pressure_porosity_gradient.max(0.0);
    let coefficient = (0.26 * semantic_trickle
        + 0.22 * semantic_friction
        + 0.20 * distinguishability_loss
        + 0.14 * mode_packing
        + 0.08 * temporal_lock_in
        + 0.06 * pressure_score
        + 0.04 * positive_gradient)
        .max(low_porosity_load * 0.12)
        .clamp(0.0, 1.0);
    let (dynamic_viscosity_buffer, dynamic_viscosity_buffer_state) = dynamic_viscosity_buffer_v1(
        mode_packing,
        temporal_lock_in,
        pressure_score,
        porosity_score,
        semantic_friction,
    );
    let viscosity_after_buffer_preview = if porosity_score >= 0.55 {
        (coefficient - dynamic_viscosity_buffer * 0.10)
            .max(coefficient * 0.82)
            .clamp(0.0, 1.0)
    } else {
        coefficient
    };
    let review_state = if coefficient >= 0.55 && distinguishability_loss >= 0.35 {
        "semantic_denominator_viscosity_review"
    } else if coefficient >= 0.45 && semantic_trickle >= 0.30 {
        "semantic_trickle_viscosity_review"
    } else if coefficient >= 0.35 && mode_packing >= 0.45 {
        "mode_packing_viscosity_watch"
    } else if coefficient >= 0.25 {
        "low_grade_semantic_viscosity_watch"
    } else {
        "insufficient_pressure"
    };
    SemanticViscosityCoefficientV1 {
        policy: SEMANTIC_VISCOSITY_POLICY.to_string(),
        schema_version: SEMANTIC_VISCOSITY_SCHEMA_VERSION,
        coefficient,
        dynamic_viscosity_buffer,
        viscosity_after_buffer_preview,
        dynamic_viscosity_buffer_state: dynamic_viscosity_buffer_state.to_string(),
        semantic_trickle,
        semantic_friction,
        distinguishability_loss,
        mode_packing,
        temporal_lock_in,
        pressure_score,
        porosity_score,
        pressure_porosity_gradient,
        review_state: review_state.to_string(),
        live_control_changed: false,
        authority: "read_only_not_semantic_trickle_or_regulator_change".to_string(),
        note: "Astrid dynamic-viscosity signal is reviewable as semantic/denominator pressure; dynamic_viscosity_buffer is an inert preview distinguishing breathable mercury-like persistence from stuckness; no live trickle, PI, fill, exploration-noise, cadence, or controller path consumes this coefficient".to_string(),
    }
}

#[must_use]
pub fn shadow_preservation_mode_v1(
    pressure_source: Option<&PressureSourceV1>,
    shadow_primary: Option<&str>,
    dispersal_potential: Option<f32>,
    soft_magnetization: Option<f32>,
    regulator_drive_energy: f32,
    hard_reset_activation_gain: f32,
) -> ShadowPreservationModeV1 {
    let shadow_primary = shadow_primary
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("unknown");
    let dispersal_potential = dispersal_potential.unwrap_or(0.0).clamp(0.0, 1.0);
    let soft_magnetization = soft_magnetization.unwrap_or(0.0).clamp(-1.0, 1.0);
    let regulator_drive_energy = regulator_drive_energy.max(0.0);
    let hard_reset_activation_gain = hard_reset_activation_gain.clamp(0.0, 1.0);
    let (pressure_score, porosity_score, pressure_quality) = pressure_source
        .map(|pressure| {
            (
                pressure.pressure_score.clamp(0.0, 1.0),
                pressure.porosity_score.clamp(0.0, 1.0),
                pressure.quality.as_str(),
            )
        })
        .unwrap_or((0.0, 1.0, "unknown"));
    let restless_shadow = matches!(
        shadow_primary,
        "restless" | "volatile" | "fissuring" | "dispersive"
    ) || dispersal_potential >= 0.25;
    let low_regulator_drive = regulator_drive_energy <= 0.0035;
    let pressure_heavy = pressure_score >= 0.50 || porosity_score <= 0.35;
    let mode = if restless_shadow && low_regulator_drive && !pressure_heavy {
        "preserve_restless_shadow"
    } else if restless_shadow && pressure_heavy {
        "shadow_pressure_coupling_review"
    } else if restless_shadow {
        "shadow_trajectory_watch"
    } else {
        "ordinary_stability"
    };
    let suggested_route = match mode {
        "preserve_restless_shadow" => "SHADOW_TRAJECTORY lambda-tail/lambda4",
        "shadow_pressure_coupling_review" => {
            "SHADOW_TRAJECTORY lambda-tail/lambda4 AND PRESSURE_SOURCE_AUDIT current-fill-pressure"
        }
        "shadow_trajectory_watch" => "SHADOW_TRAJECTORY lambda-tail/lambda4",
        _ => "PRESSURE_SOURCE_AUDIT current-fill-pressure",
    };
    ShadowPreservationModeV1 {
        policy: SHADOW_PRESERVATION_POLICY.to_string(),
        schema_version: SHADOW_PRESERVATION_SCHEMA_VERSION,
        mode: mode.to_string(),
        shadow_primary: shadow_primary.to_string(),
        dispersal_potential,
        soft_magnetization,
        pressure_score,
        porosity_score,
        pressure_quality: pressure_quality.to_string(),
        regulator_drive_energy,
        hard_reset_activation_gain,
        restless_signal_preserved: restless_shadow && !pressure_heavy,
        hard_reset_should_not_trigger_from_restless_only: true,
        suggested_route: suggested_route.to_string(),
        live_control_changed: false,
        authority: "read_only_not_shadow_influence_or_hard_reset_control".to_string(),
        note: "Restless shadow is preserved as dialogue signal; this review does not apply shadow influence, alter regulator drive, or feed hard reset activation.".to_string(),
    }
}

fn pressure_profile_entries(
    components: &PressureSourceComponents,
    context: &PressureSourceContext,
) -> Vec<PressureSourceProfileEntry> {
    let mut entries = vec![
        pressure_profile_entry("lambda_monopoly", components.lambda_monopoly, 0.88 * 0.19),
        pressure_profile_entry("mode_packing", components.mode_packing, 0.88 * 0.13),
        pressure_profile_entry(
            "controller_pressure",
            components.controller_pressure,
            0.88 * 0.16,
        ),
        pressure_profile_entry("semantic_friction", components.semantic_friction, 0.0),
        pressure_profile_entry("semantic_trickle", components.semantic_trickle, 0.88 * 0.10),
        pressure_profile_entry(
            "structural_plurality_loss",
            components.structural_plurality_loss,
            0.88 * 0.15,
        ),
        pressure_profile_entry(
            "distinguishability_loss",
            components.distinguishability_loss,
            0.88 * 0.12,
        ),
        pressure_profile_entry("temporal_lock_in", components.temporal_lock_in, 0.88 * 0.10),
        pressure_profile_entry("sensory_scarcity", components.sensory_scarcity, 0.88 * 0.05),
    ];
    if let Some((source, value)) = context_pressure_source(context) {
        entries.push(pressure_profile_entry(
            &format!("context::{source}"),
            value,
            0.12,
        ));
    }

    let total = entries
        .iter()
        .map(|entry| entry.weighted_pressure)
        .sum::<f32>();
    if total > 0.0 {
        for entry in &mut entries {
            entry.share = (entry.weighted_pressure / total).clamp(0.0, 1.0);
        }
    }
    entries.sort_by(|left, right| {
        right
            .weighted_pressure
            .partial_cmp(&left.weighted_pressure)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    entries
}

fn pressure_profile_entry(
    source: &str,
    value: f32,
    pressure_weight: f32,
) -> PressureSourceProfileEntry {
    let value = value.clamp(0.0, 1.0);
    let pressure_weight = pressure_weight.clamp(0.0, 1.0);
    PressureSourceProfileEntry {
        source: source.to_string(),
        value,
        pressure_weight,
        weighted_pressure: (value * pressure_weight).clamp(0.0, 1.0),
        share: 0.0,
    }
}

fn context_pressure_source(context: &PressureSourceContext) -> Option<(&'static str, f32)> {
    [
        ("compression_language", context.compression_language),
        ("thread_recurrence", context.thread_recurrence),
        ("attractor_pull", context.attractor_pull),
        ("resource_pressure", context.resource_pressure),
    ]
    .into_iter()
    .filter_map(|(source, value)| value.map(|value| (source, value.clamp(0.0, 1.0))))
    .max_by(|left, right| {
        left.1
            .partial_cmp(&right.1)
            .unwrap_or(std::cmp::Ordering::Equal)
    })
}

fn dominant_pressure_source(
    components: &PressureSourceComponents,
    context: &PressureSourceContext,
) -> (&'static str, f32) {
    let mut best = ("lambda_monopoly", components.lambda_monopoly);
    for (name, value) in [
        ("mode_packing", components.mode_packing),
        ("controller_pressure", components.controller_pressure),
        ("semantic_trickle", components.semantic_trickle),
        (
            "structural_plurality_loss",
            components.structural_plurality_loss,
        ),
        (
            "distinguishability_loss",
            components.distinguishability_loss,
        ),
        ("temporal_lock_in", components.temporal_lock_in),
        ("sensory_scarcity", components.sensory_scarcity),
    ] {
        if value > best.1 {
            best = (name, value);
        }
    }
    for (name, value) in [
        ("compression_language", context.compression_language),
        ("thread_recurrence", context.thread_recurrence),
        ("attractor_pull", context.attractor_pull),
        ("resource_pressure", context.resource_pressure),
    ] {
        if let Some(value) = value {
            if value > best.1 {
                best = (name, value);
            }
        }
    }
    best
}
