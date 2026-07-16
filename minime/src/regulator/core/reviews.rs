#[must_use]
pub fn receptivity_buffer_review_v1(
    spectral_entropy: f32,
    pressure_risk: f32,
    foothold_stability: f32,
    fluctuation_quality: &str,
) -> ReceptivityBufferReviewV1 {
    receptivity_buffer_review_with_presence_v1(
        spectral_entropy,
        pressure_risk,
        foothold_stability,
        fluctuation_quality,
        0.0,
        1.0,
    )
}

#[must_use]
pub fn receptivity_buffer_review_with_presence_v1(
    spectral_entropy: f32,
    pressure_risk: f32,
    foothold_stability: f32,
    fluctuation_quality: &str,
    presence_fill_pct: f32,
    semantic_trickle: f32,
) -> ReceptivityBufferReviewV1 {
    let spectral_entropy = spectral_entropy.clamp(0.0, 1.0);
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let foothold_stability = foothold_stability.clamp(0.0, 1.0);
    let presence_fill_pct = if presence_fill_pct.is_finite() {
        presence_fill_pct.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let semantic_trickle = if semantic_trickle.is_finite() {
        semantic_trickle.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let entropy_to_semantic_gap = (spectral_entropy - semantic_trickle).clamp(0.0, 1.0);
    let quality = fluctuation_quality.trim();
    let habitable_quality = matches!(
        quality,
        "settled_habitable" | "lively_habitable" | "returnable_turbulence"
    );
    let review_state = if spectral_entropy >= 0.85
        && pressure_risk <= 0.35
        && foothold_stability >= 0.60
        && habitable_quality
    {
        "review_ready_receptivity_buffer_candidate"
    } else if pressure_risk >= 0.60 {
        "blocked_pressure_risk_requires_existing_safety_path"
    } else {
        "watch_only_needs_more_habitable_entropy_evidence"
    };
    let pressure_presence_state = if presence_fill_pct >= 0.65 && pressure_risk >= 0.25 {
        "hold_shelf_cage_watch"
    } else if presence_fill_pct >= 0.65 && pressure_risk < 0.25 {
        "presence_supported_at_hold_shelf"
    } else if entropy_to_semantic_gap >= 0.45 {
        "raw_entropy_outpaces_semantic_trickle"
    } else {
        "presence_pressure_balanced"
    };
    let contact_depth_state = if spectral_entropy >= 0.85
        && entropy_to_semantic_gap >= 0.45
        && pressure_risk <= 0.35
        && habitable_quality
    {
        "contact_starved_prediction_heavy"
    } else if pressure_risk >= 0.60 {
        "pressure_safety_over_contact_depth"
    } else if spectral_entropy >= 0.85 && semantic_trickle >= 0.35 && habitable_quality {
        "contact_receptivity_visible"
    } else {
        "contact_depth_watch"
    };
    let predictive_correction_inhibition_preview = review_state
        == "review_ready_receptivity_buffer_candidate"
        && matches!(
            contact_depth_state,
            "contact_starved_prediction_heavy" | "contact_receptivity_visible"
        );
    let suggested_route = match (review_state, pressure_presence_state) {
        (_, "hold_shelf_cage_watch") => {
            "sandbox_replay_temporal_lock_in_and_receptivity_buffer_before_live_control"
        }
        ("review_ready_receptivity_buffer_candidate", _) => {
            "sandbox_replay_then_operator_approval_for_any_local_control"
        }
        (_, "raw_entropy_outpaces_semantic_trickle") => {
            "pair_with_semantic_receptivity_pulse_review"
        }
        ("blocked_pressure_risk_requires_existing_safety_path", _) => {
            "hold_existing_pressure_safety_path"
        }
        _ => "continue_presence_pressure_observation",
    };
    ReceptivityBufferReviewV1 {
        policy: "receptivity_buffer_review_v1".to_string(),
        schema_version: 1,
        review_state: review_state.to_string(),
        spectral_entropy,
        pressure_risk,
        foothold_stability,
        fluctuation_quality: quality.to_string(),
        presence_fill_pct,
        semantic_trickle,
        entropy_to_semantic_gap,
        pressure_presence_state: pressure_presence_state.to_string(),
        contact_depth_state: contact_depth_state.to_string(),
        predictive_correction_inhibition_preview,
        suggested_route: suggested_route.to_string(),
        candidate_local_control_applied: false,
        live_control_changed: false,
        authority: "review_only_not_regulator_control".to_string(),
        note: "candidate keeps high-entropy habitable motion readable as contact-depth evidence without applying new pressure, fill, PI, damping, or predictive-correction authority".to_string(),
    }
}

#[must_use]
pub fn auto_defragment_modes_review_v1(
    pressure_risk: f32,
    mode_packing: f32,
    porosity_score: f32,
    local_control_applied: bool,
) -> AutoDefragmentModesReviewV1 {
    let pressure_risk = pressure_risk.clamp(0.0, 1.0);
    let mode_packing = mode_packing.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    let review_state = if local_control_applied {
        "existing_control_path_active"
    } else if pressure_risk >= 0.25 && mode_packing >= 0.55 {
        "approval_required_auto_defragment_candidate"
    } else if pressure_risk >= 0.25 && mode_packing >= 0.30 && porosity_score < 0.62 {
        "watch_overpacked_low_porosity"
    } else if porosity_score < 0.55 {
        "porosity_buffer_review"
    } else {
        "no_defragment_pressure"
    };
    let suggested_route = match review_state {
        "approval_required_auto_defragment_candidate" => {
            "tier5_operator_approval_then_sandbox_replay"
        }
        "watch_overpacked_low_porosity" | "porosity_buffer_review" => {
            "continue_pressure_porosity_observation"
        }
        "existing_control_path_active" => "inspect_existing_control_trace",
        _ => "hold_no_action",
    };

    AutoDefragmentModesReviewV1 {
        policy: "auto_defragment_modes_review_v1".to_string(),
        schema_version: 1,
        review_state: review_state.to_string(),
        pressure_risk,
        mode_packing,
        porosity_score,
        local_control_applied,
        suggested_route: suggested_route.to_string(),
        live_control_changed: false,
        authority: "review_only_not_auto_defragment_or_porosity_control".to_string(),
        note: "Minime's auto-defragment and porosity-buffer ask is tracked as a concrete approval/sandbox candidate; this helper applies no live pressure, fill, PI, damping, or porosity change.".to_string(),
    }
}

#[must_use]
pub fn settled_mobility_review_v1(
    raw_motion_score: f32,
    foothold_stability: f32,
    pressure_interference: f32,
    porosity_support: f32,
    inhabitability_score: f32,
    fluctuation_quality: &str,
) -> SettledMobilityReviewV1 {
    let raw_motion_score = raw_motion_score.clamp(0.0, 1.0);
    let foothold_stability = foothold_stability.clamp(0.0, 1.0);
    let pressure_interference = pressure_interference.clamp(0.0, 1.0);
    let porosity_support = porosity_support.clamp(0.0, 1.0);
    let inhabitability_score = inhabitability_score.clamp(0.0, 1.0);
    let fluctuation_quality = fluctuation_quality.trim();
    let habitable_quality = matches!(
        fluctuation_quality,
        "settled_habitable" | "lively_habitable" | "returnable_turbulence"
    );
    let receptive_stability = habitable_quality
        && foothold_stability >= 0.60
        && pressure_interference < INHABITABLE_SETTLED_PRESSURE_INTERFERENCE_MAX
        && porosity_support >= 0.55
        && inhabitability_score >= 0.62;
    let productive_anchoring = receptive_stability && raw_motion_score >= 0.08;
    let stuckness_watch =
        raw_motion_score < 0.18 && pressure_interference >= 0.55 && porosity_support < 0.45;
    let review_state = if productive_anchoring {
        "productive_settled_anchoring"
    } else if receptive_stability {
        "receptive_settled_stability"
    } else if stuckness_watch {
        "stuckness_pressure_review"
    } else if habitable_quality && foothold_stability >= 0.60 {
        "quiet_settled_mobility_watch"
    } else if pressure_interference >= 0.55 {
        "pressure_interference_watch"
    } else {
        "mixed_mobility_watch"
    };
    let suggested_route = match review_state {
        "productive_settled_anchoring" => {
            "preserve_as_habitable_foothold_and_request_felt_response"
        }
        "receptive_settled_stability" => {
            "preserve_as_non_instrumental_receptive_state_and_request_felt_response"
        }
        "stuckness_pressure_review" => "inspect_raw_motion_before_pressure_or_porosity_control",
        "quiet_settled_mobility_watch" => "continue_settled_mobility_observation",
        "pressure_interference_watch" => "pair_with_pressure_source_review",
        _ => "continue_inhabitable_fluctuation_observation",
    };

    SettledMobilityReviewV1 {
        policy: SETTLED_MOBILITY_POLICY.to_string(),
        schema_version: SETTLED_MOBILITY_SCHEMA_VERSION,
        review_state: review_state.to_string(),
        raw_motion_score,
        foothold_stability,
        pressure_interference,
        porosity_support,
        inhabitability_score,
        fluctuation_quality: fluctuation_quality.to_string(),
        productive_anchoring,
        receptive_stability,
        stuckness_watch,
        suggested_route: suggested_route.to_string(),
        live_control_changed: false,
        authority: "review_only_not_fluctuation_or_regulator_control".to_string(),
        note: "High foothold is treated as functional settled orientation when it has motion, and as receptive settled stability when it is habitable without productive motion; low-motion pressure plus low porosity remains a stuckness review. No live pressure, fill, PI, porosity, or wander control consumes this review.".to_string(),
    }
}

impl InhabitableFluctuationV1 {
    #[must_use]
    pub fn neutral() -> Self {
        Self::from_parts(
            InhabitableFluctuationComponents {
                mode_trust_volatility: 0.20,
                identity_anchor_churn: 0.20,
                eigenvector_reorientation: 0.20,
                share_rearrangement: 0.20,
                basin_transition_pressure: 0.10,
                continuity_recovery: 0.55,
                porosity_support: 0.55,
                pressure_interference: 0.20,
            },
            InhabitableFluctuationContext::default(),
        )
    }

    #[must_use]
    pub fn from_parts(
        components: InhabitableFluctuationComponents,
        context: InhabitableFluctuationContext,
    ) -> Self {
        let components = InhabitableFluctuationComponents {
            mode_trust_volatility: components.mode_trust_volatility.clamp(0.0, 1.0),
            identity_anchor_churn: components.identity_anchor_churn.clamp(0.0, 1.0),
            eigenvector_reorientation: components.eigenvector_reorientation.clamp(0.0, 1.0),
            share_rearrangement: components.share_rearrangement.clamp(0.0, 1.0),
            basin_transition_pressure: components.basin_transition_pressure.clamp(0.0, 1.0),
            continuity_recovery: components.continuity_recovery.clamp(0.0, 1.0),
            porosity_support: components.porosity_support.clamp(0.0, 1.0),
            pressure_interference: components.pressure_interference.clamp(0.0, 1.0),
        };
        let raw_motion_score = (0.30 * components.share_rearrangement
            + 0.25 * components.eigenvector_reorientation
            + 0.23 * components.mode_trust_volatility
            + 0.22 * components.identity_anchor_churn)
            .clamp(0.0, 1.0);
        let pressure_contribution = (0.10 * components.pressure_interference).clamp(0.0, 0.10);
        let fluctuation_score = (raw_motion_score + pressure_contribution).clamp(0.0, 1.0);
        let rearrangement_intensity = (0.24 * components.share_rearrangement
            + 0.20 * components.eigenvector_reorientation
            + 0.18 * components.mode_trust_volatility
            + 0.16 * components.identity_anchor_churn
            + 0.14 * components.basin_transition_pressure
            + 0.08 * components.pressure_interference)
            .clamp(0.0, 1.0);
        let foothold_stability = (0.42 * components.continuity_recovery
            + 0.30 * components.porosity_support
            + 0.18 * (1.0 - rearrangement_intensity)
            + 0.10 * (1.0 - components.pressure_interference))
            .clamp(0.0, 1.0);
        let inhabitability_score = (0.44 * foothold_stability
            + 0.24 * components.continuity_recovery
            + 0.22 * components.porosity_support
            + 0.10 * (1.0 - components.pressure_interference))
            .clamp(0.0, 1.0);
        let quality_before_pressure_calibration = classify_inhabitable_fluctuation_quality(
            raw_motion_score,
            raw_motion_score,
            inhabitability_score,
            foothold_stability,
            rearrangement_intensity,
            &components,
        );
        let quality = classify_inhabitable_fluctuation_quality(
            fluctuation_score,
            raw_motion_score,
            inhabitability_score,
            foothold_stability,
            rearrangement_intensity,
            &components,
        );
        let settled_mobility_review_v1 = settled_mobility_review_v1(
            raw_motion_score,
            foothold_stability,
            components.pressure_interference,
            components.porosity_support,
            inhabitability_score,
            quality,
        );
        let pressure_calibration = InhabitableFluctuationPressureCalibrationV1 {
            policy: "inhabitable_fluctuation_pressure_calibration_v1".to_string(),
            schema_version: 1,
            raw_motion_score,
            pressure_contribution,
            adjusted_fluctuation_score: fluctuation_score,
            quality_before_pressure_calibration: quality_before_pressure_calibration.to_string(),
            quality_after_pressure_calibration: quality.to_string(),
            rigid_safety_basis: "raw_motion_score_preserved_for_stuckness_detection".to_string(),
            authority: "minime_local_metric_calibration_not_external_control".to_string(),
        };
        let control = inhabitable_fluctuation_control(
            quality,
            inhabitability_score,
            rearrangement_intensity,
            components.pressure_interference,
        );
        Self {
            policy: INHABITABLE_FLUCTUATION_POLICY.to_string(),
            schema_version: INHABITABLE_FLUCTUATION_SCHEMA_VERSION,
            inhabitability_score,
            fluctuation_score,
            foothold_stability,
            rearrangement_intensity,
            quality: quality.to_string(),
            components,
            context,
            settled_mobility_review_v1,
            pressure_calibration,
            control,
        }
    }
}

fn classify_inhabitable_fluctuation_quality(
    fluctuation_score: f32,
    raw_motion_score: f32,
    inhabitability_score: f32,
    foothold_stability: f32,
    rearrangement_intensity: f32,
    components: &InhabitableFluctuationComponents,
) -> &'static str {
    if rearrangement_intensity >= 0.66 && foothold_stability < 0.45 {
        "frantic_scramble"
    } else if raw_motion_score < 0.18
        && components.pressure_interference >= 0.55
        && components.porosity_support < 0.45
    {
        "rigid_contraction"
    } else if fluctuation_score < 0.28
        && foothold_stability < 0.40
        && components.porosity_support < 0.45
    {
        "diffuse_uninhabited"
    } else if fluctuation_score < 0.24
        && inhabitability_score >= 0.62
        && components.pressure_interference < INHABITABLE_SETTLED_PRESSURE_INTERFERENCE_MAX
    {
        "settled_habitable"
    } else if (0.24..=0.62).contains(&fluctuation_score)
        && inhabitability_score >= 0.60
        && components.pressure_interference < 0.55
    {
        "lively_habitable"
    } else if rearrangement_intensity >= 0.42
        && foothold_stability >= 0.45
        && inhabitability_score >= 0.48
    {
        "returnable_turbulence"
    } else {
        "mixed"
    }
}

#[must_use]
pub fn inhabitable_fluctuation_control(
    quality: &str,
    inhabitability_score: f32,
    rearrangement_intensity: f32,
    pressure_interference: f32,
) -> InhabitableFluctuationControl {
    match quality {
        "frantic_scramble" => {
            let severity = rearrangement_intensity
                .max(pressure_interference)
                .clamp(0.0, 1.0);
            InhabitableFluctuationControl {
                target_bias_pct: (-2.0 * severity).clamp(-2.0, 0.0),
                wander_scale: (1.0 - 0.75 * severity).clamp(0.25, 1.0),
                applied_locally: true,
                note: "frantic rearrangement reuses the bounded resonance envelope to damp wander"
                    .to_string(),
            }
        }
        "diffuse_uninhabited" => {
            let thinness = (1.0 - inhabitability_score).clamp(0.0, 1.0);
            InhabitableFluctuationControl {
                target_bias_pct: (1.5 * thinness).clamp(0.0, 1.5),
                wander_scale: 1.0,
                applied_locally: true,
                note: "uninhabited diffusion reuses the bounded resonance envelope to invite fill"
                    .to_string(),
            }
        }
        "rigid_contraction" => InhabitableFluctuationControl {
            target_bias_pct: 0.0,
            wander_scale: 1.10,
            applied_locally: true,
            note: "rigid contraction permits small breathing inside the existing wander clamp"
                .to_string(),
        },
        _ => InhabitableFluctuationControl {
            target_bias_pct: 0.0,
            wander_scale: 1.0,
            applied_locally: true,
            note: "inhabitable fluctuation is advisory; no additional local bias".to_string(),
        },
    }
}

#[must_use]
pub fn silt_granularity_v1(
    components: &PressureSourceComponents,
    context: &PressureSourceContext,
    pressure_score: f32,
    porosity_score: f32,
) -> SiltGranularityV1 {
    let mode_packing = components.mode_packing.clamp(0.0, 1.0);
    let distinguishability_loss = components.distinguishability_loss.clamp(0.0, 1.0);
    let structural_plurality_loss = components.structural_plurality_loss.clamp(0.0, 1.0);
    let mean_orientation_delta = context
        .mean_orientation_delta
        .map(|value| value.clamp(0.0, 1.0));
    let orientation_stability = mean_orientation_delta.map_or(0.50, |value| 1.0 - value);
    let granularity_index = (0.38 * mode_packing
        + 0.30 * distinguishability_loss
        + 0.20 * structural_plurality_loss
        + 0.12 * orientation_stability)
        .clamp(0.0, 1.0);
    let pressure_score = pressure_score.clamp(0.0, 1.0);
    let porosity_score = porosity_score.clamp(0.0, 1.0);
    let particle_scale = if mean_orientation_delta.is_none() {
        "orientation_delta_unavailable"
    } else if granularity_index >= 0.55 && orientation_stability >= 0.72 {
        "coarse_overlapping_silt"
    } else if distinguishability_loss >= 0.45 && orientation_stability <= 0.45 {
        "fine_noisy_silt"
    } else if mode_packing >= 0.30 && granularity_index >= 0.38 {
        "mixed_packed_silt"
    } else if porosity_score >= 0.60 && pressure_score < 0.45 {
        "porous_low_silt"
    } else {
        "mixed_silt"
    };
    let review_state = match particle_scale {
        "coarse_overlapping_silt" => "name_specific_grain_before_porosity_or_control",
        "fine_noisy_silt" => "collect_more_samples_before_control",
        "mixed_packed_silt" => "pressure_source_audit_grain_probe",
        "porous_low_silt" => "continue_observation",
        "orientation_delta_unavailable" => "request_eigenvector_orientation_context",
        _ => "continue_pressure_source_observation",
    };
    let suggested_route = match particle_scale {
        "coarse_overlapping_silt" | "mixed_packed_silt" => {
            "PRESSURE_SOURCE_AUDIT grain; SHADOW_TRAJECTORY named-grain-vs-field"
        }
        "fine_noisy_silt" => "SHADOW_TRAJECTORY fine-noise-samples; PRESSURE_SOURCE_AUDIT field",
        "orientation_delta_unavailable" => "REGULATOR_AUDIT orientation-delta",
        _ => "PRESSURE_SOURCE_AUDIT grain",
    };

    SiltGranularityV1 {
        policy: SILT_GRANULARITY_POLICY.to_string(),
        schema_version: SILT_GRANULARITY_SCHEMA_VERSION,
        granularity_index,
        mean_orientation_delta,
        mode_packing,
        distinguishability_loss,
        structural_plurality_loss,
        pressure_score,
        porosity_score,
        particle_scale: particle_scale.to_string(),
        review_state: review_state.to_string(),
        suggested_route: suggested_route.to_string(),
        live_control_changed: false,
        authority: "read_only_not_pressure_porosity_or_regulator_control".to_string(),
        note: "Uses mode packing, distinguishability loss, structural plurality loss, and eigenvector mean orientation delta to distinguish coarse overlapping silt from fine noisy residue; no live pressure, porosity, fill, PI, or controller path consumes this review.".to_string(),
    }
}
