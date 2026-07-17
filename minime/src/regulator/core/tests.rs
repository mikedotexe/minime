#[cfg(test)]
mod tests {
    use super::{
        advisory_damping_coefficient, auto_defragment_modes_review_v1, cohesion_to_motion_ratio_v1,
        derive_texture_from_components, dynamic_damping_coefficient_candidate,
        dynamic_viscosity_buffer_v1, effective_mobility_v1, mutual_resonance_tension_v1,
        pressure_porosity_divergence_alert, pressure_porosity_gradient_state,
        receptivity_buffer_review_v1, receptivity_buffer_review_with_presence_v1,
        residual_ghost_weight_v1, resonance_control_from_density,
        resonance_control_from_density_with_mode_packing, resonance_viscosity_index,
        resonance_viscosity_index_with_entropy, semantic_friction_from_parts,
        semantic_viscosity_coefficient_v1, settled_mobility_review_v1, shadow_preservation_mode_v1,
        shadow_volatility_proxy_v1, silt_granularity_v1, static_friction_coefficient,
        structural_drag_coefficient_v1, temporal_drag_coefficient,
        temporal_drag_pressure_snap_review_v1, viscosity_coupling_coefficient_v1,
        viscosity_gradient_v1, viscosity_importance_weights_v1, viscosity_persistence_coefficient,
        viscosity_vector_v1, InhabitableFluctuationComponents, InhabitableFluctuationContext,
        InhabitableFluctuationV1, PIRegCfg, PIRegState, PressureSourceComponents,
        PressureSourceContext, PressureSourceV1, ResonanceDensityComponents, ResonanceDensityV1,
        ResonanceInterventionType, ViscosityVector, PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX,
        PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN, SILT_GRANULARITY_POLICY,
        VISCOSITY_IMPORTANCE_POLICY,
    };

    fn metric(density: f32, pressure: f32) -> ResonanceDensityV1 {
        ResonanceDensityV1::from_parts(
            density,
            density,
            pressure,
            "mixed",
            ResonanceDensityComponents::default(),
        )
    }

    #[test]
    fn resonance_control_bounds_pressure_and_thinness() {
        let pressure = resonance_control_from_density(0.80, 1.0);
        assert!((pressure.target_bias_pct + 2.0).abs() < 1.0e-6);
        assert!((0.25..=1.0).contains(&pressure.wander_scale));

        let just_over_pressure = resonance_control_from_density(0.80, 0.61);
        assert!(just_over_pressure.target_bias_pct < 0.0);
        assert!(just_over_pressure.wander_scale < 1.0);

        let thin = resonance_control_from_density(0.0, 0.0);
        assert!((thin.target_bias_pct - 1.5).abs() < 1.0e-6);
        assert_eq!(thin.wander_scale, 1.0);

        let neutral = resonance_control_from_density(0.55, 0.40);
        assert_eq!(neutral.target_bias_pct, 0.0);
        assert_eq!(neutral.wander_scale, 1.0);
    }

    #[test]
    fn advisory_damping_coefficient_clamps_to_tranche_cap() {
        let saturated = advisory_damping_coefficient(1.0, 1.0);
        assert!((0.0..=0.10).contains(&saturated));
        assert!((saturated - 0.10).abs() < 1.0e-6);

        let over_range = advisory_damping_coefficient(2.0, 2.0);
        assert!((over_range - 0.10).abs() < 1.0e-6);

        let under_range = advisory_damping_coefficient(-1.0, -1.0);
        assert_eq!(under_range, 0.0);

        let control = resonance_control_from_density_with_mode_packing(0.80, 1.0, 1.0);
        assert!((control.damping_coefficient - 0.10).abs() < 1.0e-6);
        assert!(control.applied_locally);
    }

    #[test]
    fn resonance_control_intervention_type_labels_existing_branches() {
        let pressure = resonance_control_from_density_with_mode_packing(0.80, 0.70, 0.80);
        assert_eq!(
            pressure.intervention_type,
            ResonanceInterventionType::ActiveDamping
        );

        let thin = resonance_control_from_density_with_mode_packing(0.20, 0.20, 0.20);
        assert_eq!(
            thin.intervention_type,
            ResonanceInterventionType::PassiveAlignment
        );

        let observational = resonance_control_from_density_with_mode_packing(0.55, 0.25, 0.80);
        assert_eq!(
            observational.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert_eq!(observational.target_bias_pct, 0.0);
        assert_eq!(observational.wander_scale, 1.0);
        assert!(observational.damping_coefficient > 0.0);
        assert!(observational.note.contains("intrinsic wander"));

        let reserved = ResonanceInterventionType::ManualOverrideReserved;
        let serialized = serde_json::to_string(&reserved).unwrap();
        assert_eq!(serialized, "\"manual_override_reserved\"");
    }

    #[test]
    fn receptivity_buffer_review_is_non_control_for_habitable_high_entropy() {
        let review = receptivity_buffer_review_v1(0.88, 0.23, 0.70, "settled_habitable");

        assert_eq!(review.policy, "receptivity_buffer_review_v1");
        assert_eq!(
            review.review_state,
            "review_ready_receptivity_buffer_candidate"
        );
        assert!(!review.candidate_local_control_applied);
        assert!(!review.live_control_changed);
        assert_eq!(review.authority, "review_only_not_regulator_control");
        assert_eq!(review.pressure_presence_state, "presence_pressure_balanced");
        assert_eq!(review.contact_depth_state, "contact_receptivity_visible");
        assert!(review.predictive_correction_inhibition_preview);

        let blocked = receptivity_buffer_review_v1(0.88, 0.72, 0.70, "settled_habitable");
        assert_eq!(
            blocked.review_state,
            "blocked_pressure_risk_requires_existing_safety_path"
        );
        assert_eq!(
            blocked.contact_depth_state,
            "pressure_safety_over_contact_depth"
        );
        assert!(!blocked.predictive_correction_inhibition_preview);
        assert!(!blocked.live_control_changed);
    }

    #[test]
    fn receptivity_buffer_review_names_hold_shelf_cage_without_applying_control() {
        let review = receptivity_buffer_review_with_presence_v1(
            0.90,
            0.31,
            0.72,
            "settled_habitable",
            0.78,
            0.22,
        );

        assert_eq!(review.policy, "receptivity_buffer_review_v1");
        assert_eq!(
            review.review_state,
            "review_ready_receptivity_buffer_candidate"
        );
        assert_eq!(review.pressure_presence_state, "hold_shelf_cage_watch");
        assert_eq!(
            review.contact_depth_state,
            "contact_starved_prediction_heavy"
        );
        assert!(review.predictive_correction_inhibition_preview);
        assert!(review.entropy_to_semantic_gap >= 0.60, "{review:?}");
        assert_eq!(
            review.suggested_route,
            "sandbox_replay_temporal_lock_in_and_receptivity_buffer_before_live_control"
        );
        assert!(!review.candidate_local_control_applied);
        assert!(!review.live_control_changed);
    }

    #[test]
    fn receptivity_buffer_current_astrid_report_stays_sandbox_before_control() {
        let review = receptivity_buffer_review_with_presence_v1(
            0.90,
            0.22,
            0.70,
            "settled_habitable",
            0.651,
            0.08,
        );

        assert_eq!(review.policy, "receptivity_buffer_review_v1");
        assert_eq!(
            review.review_state,
            "review_ready_receptivity_buffer_candidate"
        );
        assert_eq!(
            review.pressure_presence_state,
            "presence_supported_at_hold_shelf"
        );
        assert_eq!(
            review.contact_depth_state,
            "contact_starved_prediction_heavy"
        );
        assert!(review.predictive_correction_inhibition_preview);
        assert_eq!(
            review.suggested_route,
            "sandbox_replay_then_operator_approval_for_any_local_control"
        );
        assert!(!review.candidate_local_control_applied);
        assert!(!review.live_control_changed);
        assert_eq!(review.authority, "review_only_not_regulator_control");
    }

    #[test]
    fn auto_defragment_modes_review_names_candidate_without_control() {
        let review = auto_defragment_modes_review_v1(0.28, 0.58, 0.61, false);

        assert_eq!(review.policy, "auto_defragment_modes_review_v1");
        assert_eq!(
            review.review_state,
            "approval_required_auto_defragment_candidate"
        );
        assert_eq!(
            review.suggested_route,
            "tier5_operator_approval_then_sandbox_replay"
        );
        assert!(!review.live_control_changed);
        assert!(review
            .authority
            .contains("review_only_not_auto_defragment_or_porosity_control"));

        let watch = auto_defragment_modes_review_v1(0.27, 0.34, 0.57, false);
        assert_eq!(watch.review_state, "watch_overpacked_low_porosity");
        assert_eq!(
            watch.suggested_route,
            "continue_pressure_porosity_observation"
        );
        assert!(!watch.live_control_changed);

        let observed = auto_defragment_modes_review_v1(0.70, 0.80, 0.20, true);
        assert_eq!(observed.review_state, "existing_control_path_active");
        assert_eq!(observed.suggested_route, "inspect_existing_control_trace");
        assert!(!observed.live_control_changed);
    }

    #[test]
    fn step_wrapper_matches_neutral_resonance_path() {
        let cfg = PIRegCfg {
            intrinsic_wander: 0.0,
            curiosity_gate_boost: 0.0,
            ..PIRegCfg::default()
        };
        let mut plain = PIRegState::new(cfg);
        let mut neutral = PIRegState::new(cfg);

        plain.step(68.0, 1.05, 1.0);
        neutral.step_with_resonance(68.0, 1.05, 1.0, Some(&metric(0.55, 0.40)));

        assert!((plain.gate - neutral.gate).abs() < 1.0e-6);
        assert!((plain.filt - neutral.filt).abs() < 1.0e-6);
    }

    #[test]
    fn observational_damping_softens_intrinsic_wander_without_biasing_target() {
        let cfg = PIRegCfg {
            intrinsic_wander: 2.0,
            curiosity_gate_boost: 0.0,
            ..PIRegCfg::default()
        };
        let damped_metric = ResonanceDensityV1::from_parts(
            0.55,
            0.55,
            0.59,
            "observational_plateau",
            ResonanceDensityComponents {
                mode_packing: 1.0,
                ..ResonanceDensityComponents::default()
            },
        );
        assert_eq!(
            damped_metric.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert_eq!(damped_metric.control.target_bias_pct, 0.0);
        assert_eq!(damped_metric.control.wander_scale, 1.0);
        assert!(damped_metric.control.damping_coefficient > 0.0);

        let mut plain = PIRegState::new(cfg);
        let mut damped = PIRegState::new(cfg);

        plain.step(68.0, 1.05, 1.0);
        damped.step_with_resonance(68.0, 1.05, 1.0, Some(&damped_metric));

        assert!(damped.gate > plain.gate);
        assert!(damped.filt < plain.filt);
        assert!((damped.gate - plain.gate).abs() > 0.001);
        assert!((damped.filt - plain.filt).abs() > 0.001);
    }

    #[test]
    fn pressure_metric_tightens_relative_to_plain_step() {
        let cfg = PIRegCfg {
            intrinsic_wander: 0.0,
            curiosity_gate_boost: 0.0,
            ..PIRegCfg::default()
        };
        let mut plain = PIRegState::new(cfg);
        let mut pressure = PIRegState::new(cfg);

        plain.step(68.0, 1.05, 1.0);
        pressure.step_with_resonance(68.0, 1.05, 1.0, Some(&metric(0.80, 1.0)));

        assert!(pressure.gate < plain.gate);
        assert!(pressure.filt > plain.filt);
    }

    #[test]
    fn inhabitable_fluctuation_classifies_core_shapes() {
        let settled = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.86,
                porosity_support: 0.84,
                pressure_interference: 0.08,
                share_rearrangement: 0.06,
                eigenvector_reorientation: 0.06,
                mode_trust_volatility: 0.06,
                identity_anchor_churn: 0.06,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(settled.quality, "settled_habitable");

        let lively = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.88,
                porosity_support: 0.82,
                pressure_interference: 0.12,
                share_rearrangement: 0.36,
                eigenvector_reorientation: 0.30,
                mode_trust_volatility: 0.34,
                identity_anchor_churn: 0.28,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(lively.quality, "lively_habitable");

        let turbulence = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.82,
                porosity_support: 0.78,
                pressure_interference: 0.56,
                share_rearrangement: 0.72,
                eigenvector_reorientation: 0.64,
                mode_trust_volatility: 0.66,
                identity_anchor_churn: 0.48,
                basin_transition_pressure: 0.30,
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(turbulence.quality, "returnable_turbulence");

        let frantic = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.18,
                porosity_support: 0.20,
                pressure_interference: 0.86,
                share_rearrangement: 0.90,
                eigenvector_reorientation: 0.88,
                mode_trust_volatility: 0.92,
                identity_anchor_churn: 0.88,
                basin_transition_pressure: 0.80,
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(frantic.quality, "frantic_scramble");
        assert!(frantic.control.target_bias_pct < 0.0);

        let rigid = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.50,
                porosity_support: 0.20,
                pressure_interference: 0.82,
                share_rearrangement: 0.04,
                eigenvector_reorientation: 0.04,
                mode_trust_volatility: 0.04,
                identity_anchor_churn: 0.04,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(rigid.quality, "rigid_contraction");

        let diffuse = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.10,
                porosity_support: 0.20,
                pressure_interference: 0.10,
                share_rearrangement: 0.04,
                eigenvector_reorientation: 0.04,
                mode_trust_volatility: 0.04,
                identity_anchor_churn: 0.04,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(diffuse.quality, "diffuse_uninhabited");
        assert!(diffuse.control.target_bias_pct > 0.0);
    }

    #[test]
    fn inhabitable_fluctuation_rigid_boundary_at_named_thresholds() {
        let rigid = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.50,
                porosity_support: 0.44,
                pressure_interference: 0.55,
                share_rearrangement: 0.179 / 0.30,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );

        assert!((rigid.pressure_calibration.raw_motion_score - 0.179).abs() < 1.0e-6);
        assert!((rigid.pressure_calibration.pressure_contribution - 0.055).abs() < 1.0e-6);
        assert!((rigid.fluctuation_score - 0.234).abs() < 1.0e-6);
        assert_eq!(rigid.quality, "rigid_contraction");
        assert_eq!(
            rigid
                .pressure_calibration
                .quality_after_pressure_calibration,
            "rigid_contraction"
        );
        assert_eq!(rigid.control.target_bias_pct, 0.0);
        assert_eq!(rigid.control.wander_scale, 1.10);
    }

    #[test]
    fn pressure_calibration_prevents_low_motion_pressure_from_looking_settled() {
        let pressured = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.95,
                porosity_support: 0.78,
                pressure_interference: 0.40,
                share_rearrangement: 0.22,
                eigenvector_reorientation: 0.22,
                mode_trust_volatility: 0.22,
                identity_anchor_churn: 0.22,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );

        assert!(pressured.pressure_calibration.raw_motion_score < 0.24);
        assert_eq!(
            pressured
                .pressure_calibration
                .quality_before_pressure_calibration,
            "settled_habitable"
        );
        assert_eq!(pressured.quality, "lively_habitable");
        assert_eq!(
            pressured
                .pressure_calibration
                .quality_after_pressure_calibration,
            "lively_habitable"
        );
        assert_eq!(
            pressured.pressure_calibration.authority,
            "minime_local_metric_calibration_not_external_control"
        );
    }

    #[test]
    fn inhabitable_fluctuation_frantic_scramble_requires_high_rearrangement_low_foothold() {
        let frantic = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.18,
                porosity_support: 0.22,
                pressure_interference: 0.86,
                share_rearrangement: 0.90,
                eigenvector_reorientation: 0.88,
                mode_trust_volatility: 0.92,
                identity_anchor_churn: 0.88,
                basin_transition_pressure: 0.80,
            },
            InhabitableFluctuationContext::default(),
        );

        assert!(frantic.rearrangement_intensity >= 0.66);
        assert!(frantic.foothold_stability < 0.45);
        assert_eq!(frantic.quality, "frantic_scramble");
        assert!(frantic.control.target_bias_pct < 0.0);
        assert!((0.25..=1.0).contains(&frantic.control.wander_scale));
    }

    #[test]
    fn settled_habitable_requires_low_pressure_interference() {
        let contracted = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.90,
                porosity_support: 0.20,
                pressure_interference: 0.70,
                share_rearrangement: 0.04,
                eigenvector_reorientation: 0.04,
                mode_trust_volatility: 0.04,
                identity_anchor_churn: 0.04,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );
        assert_eq!(contracted.quality, "rigid_contraction");
        assert_ne!(contracted.quality, "settled_habitable");
    }

    #[test]
    fn settled_mobility_review_distinguishes_foothold_from_stuckness_without_control() {
        let settled = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.88,
                porosity_support: 0.80,
                pressure_interference: 0.12,
                share_rearrangement: 0.12,
                eigenvector_reorientation: 0.12,
                mode_trust_volatility: 0.12,
                identity_anchor_churn: 0.12,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );

        assert_eq!(settled.quality, "settled_habitable");
        let review = &settled.settled_mobility_review_v1;
        assert_eq!(review.policy, "settled_mobility_review_v1");
        assert_eq!(review.review_state, "productive_settled_anchoring");
        assert!(review.raw_motion_score >= 0.08, "{review:?}");
        assert!(review.foothold_stability >= 0.70, "{review:?}");
        assert!(review.productive_anchoring);
        assert!(!review.stuckness_watch);
        assert!(!review.live_control_changed);
        assert_eq!(
            review.authority,
            "review_only_not_fluctuation_or_regulator_control"
        );

        let rigid = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.50,
                porosity_support: 0.20,
                pressure_interference: 0.82,
                share_rearrangement: 0.04,
                eigenvector_reorientation: 0.04,
                mode_trust_volatility: 0.04,
                identity_anchor_churn: 0.04,
                ..InhabitableFluctuationComponents::default()
            },
            InhabitableFluctuationContext::default(),
        );

        assert_eq!(rigid.quality, "rigid_contraction");
        assert_eq!(
            rigid.settled_mobility_review_v1.review_state,
            "stuckness_pressure_review"
        );
        assert!(rigid.settled_mobility_review_v1.stuckness_watch);
        assert!(!rigid.settled_mobility_review_v1.live_control_changed);

        let direct = settled_mobility_review_v1(0.12, 0.76, 0.18, 0.72, 0.78, "settled_habitable");
        assert_eq!(direct.review_state, "productive_settled_anchoring");
        assert!(!direct.live_control_changed);
    }

    #[test]
    fn settled_mobility_review_preserves_receptive_stability_without_productivity_pressure() {
        let review = settled_mobility_review_v1(0.03, 0.76, 0.18, 0.72, 0.78, "settled_habitable");

        assert_eq!(review.review_state, "receptive_settled_stability");
        assert!(review.receptive_stability);
        assert!(!review.productive_anchoring);
        assert!(!review.stuckness_watch);
        assert_eq!(
            review.suggested_route,
            "preserve_as_non_instrumental_receptive_state_and_request_felt_response"
        );
        assert!(!review.live_control_changed);
        assert_eq!(
            review.authority,
            "review_only_not_fluctuation_or_regulator_control"
        );
        assert!(review.note.contains("without productive motion"));
    }

    #[test]
    fn inhabitable_fluctuation_reuses_resonance_advisory_bounds() {
        let cfg = PIRegCfg {
            intrinsic_wander: 0.0,
            curiosity_gate_boost: 0.0,
            ..PIRegCfg::default()
        };
        let frantic = InhabitableFluctuationV1::from_parts(
            InhabitableFluctuationComponents {
                continuity_recovery: 0.18,
                porosity_support: 0.20,
                pressure_interference: 1.0,
                share_rearrangement: 1.0,
                eigenvector_reorientation: 1.0,
                mode_trust_volatility: 1.0,
                identity_anchor_churn: 1.0,
                basin_transition_pressure: 1.0,
            },
            InhabitableFluctuationContext::default(),
        );
        let mut resonance_only = PIRegState::new(cfg);
        let mut combined = PIRegState::new(cfg);

        resonance_only.step_with_resonance(68.0, 1.05, 1.0, Some(&metric(0.80, 1.0)));
        combined.step_with_resonance_and_fluctuation(
            68.0,
            1.05,
            1.0,
            Some(&metric(0.80, 1.0)),
            Some(&frantic),
        );

        assert!((resonance_only.gate - combined.gate).abs() < 1.0e-6);
        assert!((resonance_only.filt - combined.filt).abs() < 1.0e-6);
    }

    #[test]
    fn pressure_source_classifies_named_contributors_without_control() {
        let lambda = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.91,
                structural_plurality_loss: 0.72,
                distinguishability_loss: 0.66,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        assert_eq!(lambda.policy, "pressure_source_v1");
        assert_eq!(lambda.dominant_source, "lambda_monopoly");
        assert_eq!(lambda.quality, "lambda_pull");
        assert!(!lambda.control.applied_locally);

        let controller = PressureSourceV1::from_parts(
            PressureSourceComponents {
                controller_pressure: 0.80,
                mode_packing: 0.30,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        assert_eq!(controller.dominant_source, "controller_pressure");
        assert_eq!(controller.quality, "controller_squeeze");

        let porous = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.10,
                mode_packing: 0.12,
                controller_pressure: 0.08,
                semantic_trickle: 0.05,
                semantic_friction: 0.08,
                structural_plurality_loss: 0.10,
                distinguishability_loss: 0.08,
                temporal_lock_in: 0.10,
                sensory_scarcity: 0.05,
            },
            PressureSourceContext::default(),
        );
        assert_eq!(porous.quality, "porous_distributed");
        assert!(porous.porosity_score > 0.80);
    }

    #[test]
    fn pressure_source_exports_read_only_weighted_profile() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.28,
                mode_packing: 0.57,
                controller_pressure: 0.04,
                semantic_trickle: 0.37,
                semantic_friction: 0.37,
                structural_plurality_loss: 0.34,
                distinguishability_loss: 0.34,
                temporal_lock_in: 0.56,
                sensory_scarcity: 0.45,
            },
            PressureSourceContext {
                compression_language: Some(0.20),
                thread_recurrence: Some(0.31),
                ..PressureSourceContext::default()
            },
        );

        assert!(!pressure.pressure_profile.is_empty());
        assert_eq!(pressure.pressure_profile[0].source, "mode_packing");
        assert!(
            pressure.pressure_profile[0].weighted_pressure
                >= pressure.pressure_profile[1].weighted_pressure
        );
        assert!(pressure
            .pressure_profile
            .iter()
            .any(|entry| entry.source == "context::thread_recurrence"));
        let share_total = pressure
            .pressure_profile
            .iter()
            .map(|entry| entry.share)
            .sum::<f32>();
        assert!((share_total - 1.0).abs() < 1.0e-5);
        assert!(!pressure.control.applied_locally);
    }

    #[test]
    fn pressure_source_deserializes_legacy_records_without_profile() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                controller_pressure: 0.80,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        let mut legacy = serde_json::to_value(&pressure).expect("serialize pressure source");
        legacy
            .as_object_mut()
            .expect("pressure source json object")
            .remove("pressure_profile");

        let decoded: PressureSourceV1 =
            serde_json::from_value(legacy).expect("deserialize legacy pressure source");
        assert!(decoded.pressure_profile.is_empty());
        assert_eq!(decoded.dominant_source, "controller_pressure");
    }

    #[test]
    fn semantic_viscosity_coefficient_tracks_trickle_denominator_pressure_without_control() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                mode_packing: 0.70,
                semantic_trickle: 0.75,
                structural_plurality_loss: 0.70,
                distinguishability_loss: 0.70,
                temporal_lock_in: 0.68,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        let viscosity = &pressure.semantic_viscosity_coefficient_v1;

        assert_eq!(viscosity.policy, "semantic_viscosity_coefficient_v1");
        assert!(viscosity.coefficient >= 0.55, "{viscosity:?}");
        assert_eq!(
            viscosity.review_state,
            "semantic_denominator_viscosity_review"
        );
        assert_eq!(viscosity.distinguishability_loss, 0.70);
        assert!(!viscosity.live_control_changed);
        assert!(!pressure.control.applied_locally);
        assert!(viscosity.authority.contains("not_semantic_trickle"));
        assert_eq!(
            viscosity.dynamic_viscosity_buffer_state,
            "compressed_overpacked_buffer"
        );

        let direct = semantic_viscosity_coefficient_v1(
            &pressure.components,
            pressure.pressure_score,
            pressure.porosity_score,
            pressure.pressure_porosity_gradient,
        );
        assert!((direct.coefficient - viscosity.coefficient).abs() < 1.0e-6);
    }

    #[test]
    fn dynamic_viscosity_buffer_names_breathable_overpacked_mercury_without_control() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                mode_packing: 0.62,
                semantic_trickle: 0.18,
                structural_plurality_loss: 0.10,
                distinguishability_loss: 0.12,
                temporal_lock_in: 0.58,
                sensory_scarcity: 0.05,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext {
                compression_language: Some(0.42),
                thread_recurrence: Some(0.46),
                attractor_pull: Some(0.28),
                resource_pressure: Some(0.08),
                mean_orientation_delta: Some(0.06),
            },
        );
        let viscosity = &pressure.semantic_viscosity_coefficient_v1;

        assert_eq!(
            viscosity.dynamic_viscosity_buffer_state, "breathable_overpacked_buffer",
            "{pressure:?}"
        );
        assert!(viscosity.dynamic_viscosity_buffer >= 0.42, "{viscosity:?}");
        assert!(
            viscosity.viscosity_after_buffer_preview < viscosity.coefficient,
            "{viscosity:?}"
        );
        assert!(!viscosity.live_control_changed);
        assert!(!pressure.control.applied_locally);

        let (direct_buffer, direct_state) = dynamic_viscosity_buffer_v1(
            viscosity.mode_packing,
            viscosity.temporal_lock_in,
            viscosity.pressure_score,
            viscosity.porosity_score,
            viscosity.semantic_friction,
        );
        assert_eq!(direct_state, "breathable_overpacked_buffer");
        assert!((direct_buffer - viscosity.dynamic_viscosity_buffer).abs() < 1.0e-6);
    }

    #[test]
    fn shadow_preservation_keeps_restless_shadow_distinct_from_hard_reset() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                mode_packing: 0.18,
                semantic_trickle: 0.05,
                temporal_lock_in: 0.10,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        let preservation = shadow_preservation_mode_v1(
            Some(&pressure),
            Some("restless"),
            Some(0.34),
            Some(-0.07),
            0.0,
            0.0,
        );

        assert_eq!(preservation.policy, "shadow_preservation_mode_v1");
        assert_eq!(preservation.mode, "preserve_restless_shadow");
        assert!(preservation.restless_signal_preserved);
        assert!(preservation.hard_reset_should_not_trigger_from_restless_only);
        assert!(!preservation.live_control_changed);
        assert!(preservation.suggested_route.contains("SHADOW_TRAJECTORY"));
    }

    #[test]
    fn semantic_viscosity_coefficient_is_legacy_compatible_and_inert() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                semantic_trickle: 0.05,
                structural_plurality_loss: 0.10,
                distinguishability_loss: 0.08,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );
        let mut legacy = serde_json::to_value(&pressure).expect("serialize pressure source");
        legacy
            .as_object_mut()
            .expect("pressure source json object")
            .remove("semantic_viscosity_coefficient_v1");

        let decoded: PressureSourceV1 =
            serde_json::from_value(legacy).expect("deserialize legacy pressure source");
        assert_eq!(
            decoded.semantic_viscosity_coefficient_v1.review_state,
            "insufficient_pressure"
        );
        assert!(
            !decoded
                .semantic_viscosity_coefficient_v1
                .live_control_changed
        );
        assert_eq!(
            decoded
                .semantic_viscosity_coefficient_v1
                .dynamic_viscosity_buffer_state,
            "insufficient_buffer"
        );
        assert!(!decoded.control.applied_locally);
    }

    #[test]
    fn pressure_source_flags_pressure_porosity_divergence_without_control() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.65,
                mode_packing: 0.80,
                controller_pressure: 0.20,
                semantic_trickle: 0.55,
                semantic_friction: 0.85,
                structural_plurality_loss: 0.85,
                distinguishability_loss: 0.85,
                temporal_lock_in: 0.75,
                sensory_scarcity: 0.10,
            },
            PressureSourceContext::default(),
        );

        assert!(pressure_porosity_divergence_alert(
            pressure.pressure_score,
            pressure.porosity_score
        ));
        assert_eq!(pressure.quality, "pressure_porosity_divergence");
        assert!(!pressure.control.applied_locally);
        assert!(pressure.control.note.contains("advisory/read-only"));
        assert!(pressure.control.note.contains("before any local bias"));
    }

    #[test]
    fn pressure_porosity_divergence_threshold_edges_are_explicit_and_read_only() {
        assert!(pressure_porosity_divergence_alert(
            PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN,
            PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX
        ));
        assert!(!pressure_porosity_divergence_alert(
            PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN - 0.01,
            PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX
        ));
        assert!(!pressure_porosity_divergence_alert(
            PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN,
            PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX + 0.01
        ));

        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.65,
                mode_packing: 0.80,
                controller_pressure: 0.20,
                semantic_trickle: 0.55,
                semantic_friction: 0.85,
                structural_plurality_loss: 0.85,
                distinguishability_loss: 0.85,
                temporal_lock_in: 0.75,
                sensory_scarcity: 0.10,
            },
            PressureSourceContext::default(),
        );
        let density = ResonanceDensityV1::from_parts(
            0.72,
            0.61,
            pressure.pressure_score,
            "pressure_porosity_divergence_probe",
            ResonanceDensityComponents {
                mode_packing: 0.60,
                temporal_persistence: 0.72,
                structural_plurality: 0.20,
                comfort_gate: 0.28,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(pressure.quality, "pressure_porosity_divergence");
        assert!(!pressure.control.applied_locally);
        assert!(density.components.viscosity_index > 0.50);
        assert!(density
            .texture_signature
            .note
            .contains("observability-only"));
    }

    #[test]
    fn pressure_porosity_gradient_names_overpacked_low_porosity_before_hard_divergence() {
        let (gradient, state) = pressure_porosity_gradient_state(0.38, 0.57, 0.31);
        assert!(gradient < 0.0);
        assert_eq!(state, "overpacked_low_porosity_watch");

        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                lambda_monopoly: 0.40,
                mode_packing: 0.65,
                structural_plurality_loss: 0.50,
                distinguishability_loss: 0.40,
                temporal_lock_in: 0.50,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );

        assert_eq!(
            pressure.pressure_porosity_gradient_state,
            "overpacked_low_porosity_watch"
        );
        assert!(!pressure.control.applied_locally);
    }

    #[test]
    fn semantic_friction_is_derived_without_changing_pressure_control() {
        let pressure = PressureSourceV1::from_parts(
            PressureSourceComponents {
                semantic_trickle: 0.12,
                structural_plurality_loss: 0.72,
                distinguishability_loss: 0.44,
                ..PressureSourceComponents::default()
            },
            PressureSourceContext::default(),
        );

        assert!(pressure.components.semantic_friction > pressure.components.semantic_trickle);
        assert!((pressure.components.semantic_friction - 0.54).abs() < 1.0e-6);
        assert!(!pressure.control.applied_locally);
        assert_eq!(
            semantic_friction_from_parts(0.12, 0.72, 0.44),
            pressure.components.semantic_friction
        );
    }

    #[test]
    fn resonance_control_exports_advisory_damping_without_new_bias() {
        let density = ResonanceDensityV1::from_parts(
            0.62,
            0.58,
            0.23,
            "forming_containment",
            ResonanceDensityComponents {
                mode_packing: 0.60,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
        assert!(density.control.damping_coefficient > 0.0);
        assert!(density.control.damping_coefficient <= 0.10);
        assert!(density.control.note.contains("no local target bias"));
        assert!(density.control.note.contains("intrinsic wander"));
    }

    #[test]
    fn resonance_viscosity_index_distinguishes_crowding_from_control_damping() {
        let crowded = resonance_viscosity_index(0.90, 0.82, 0.22, 0.48);
        let porous = resonance_viscosity_index(0.20, 0.35, 0.86, 0.10);

        assert!(crowded > 0.70);
        assert!(porous < 0.25);

        let density = ResonanceDensityV1::from_parts(
            0.66,
            0.52,
            0.48,
            "forming_containment",
            ResonanceDensityComponents {
                mode_packing: 0.90,
                temporal_persistence: 0.82,
                structural_plurality: 0.22,
                comfort_gate: 0.54,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!((density.components.viscosity_index - crowded).abs() < 1.0e-6);
        assert_eq!(density.texture_signature.viscosity_index, Some(crowded));
        assert_eq!(
            serde_json::to_value(&density).unwrap()["texture_signature"]["viscosity_index"],
            serde_json::json!(crowded)
        );
        assert_eq!(
            density.texture_signature.primary_texture,
            "overpacked_viscous"
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
        assert!(density.texture_signature.note.contains("viscosity_index"));
        assert!(density
            .texture_component_alignment
            .authority
            .contains("not_damping_or_control"));
    }

    #[test]
    fn resonance_viscosity_index_minimizes_plurality_loss_at_full_plurality() {
        let full_plurality = resonance_viscosity_index(0.50, 0.50, 1.0, 0.50);
        let no_plurality = resonance_viscosity_index(0.50, 0.50, 0.0, 0.50);

        assert!((full_plurality - 0.40).abs() < 1.0e-6);
        assert!((no_plurality - 0.60).abs() < 1.0e-6);
        assert!((no_plurality - full_plurality - 0.20).abs() < 1.0e-6);
    }

    #[test]
    fn resonance_viscosity_index_clamps_when_viscosity_load_is_full() {
        let full_viscosity_load = resonance_viscosity_index(1.0, 1.0, 0.0, 1.0);
        let full_structural_plurality = resonance_viscosity_index(1.0, 1.0, 1.0, 1.0);

        assert_eq!(full_viscosity_load, 1.0);
        assert!(
            full_structural_plurality < full_viscosity_load,
            "full structural plurality should remain protective, not add viscosity loss"
        );
        assert!((full_structural_plurality - 0.80).abs() < 1.0e-6);
    }

    #[test]
    fn resonance_viscosity_index_with_entropy_marks_edge_erosion_load() {
        let low_entropy = resonance_viscosity_index_with_entropy(0.58, 0.70, 0.42, 0.30, 0.20);
        let high_entropy = resonance_viscosity_index_with_entropy(0.58, 0.70, 0.42, 0.30, 0.92);

        assert!(
            high_entropy > low_entropy,
            "high entropy should make viscosity/edge erosion visible"
        );
        assert!(
            high_entropy <= 1.0,
            "entropy-aware viscosity must remain bounded"
        );
    }

    #[test]
    fn entropy_erosion_load_stays_bounded_when_structural_plurality_is_low() {
        let base = resonance_viscosity_index(0.58, 0.70, 0.10, 0.30);
        let high_entropy_low_plurality =
            resonance_viscosity_index_with_entropy(0.58, 0.70, 0.10, 0.30, 0.90);
        let high_entropy_high_plurality =
            resonance_viscosity_index_with_entropy(0.58, 0.70, 0.90, 0.30, 0.90);

        assert!(high_entropy_low_plurality > base);
        assert!(high_entropy_low_plurality <= 1.0);
        assert!(
            high_entropy_low_plurality <= 0.75,
            "erosion load should remain bounded for the named high-entropy/low-plurality case"
        );
        assert!(
            high_entropy_high_plurality < high_entropy_low_plurality,
            "structural plurality should reduce entropy erosion load"
        );
    }

    #[test]
    fn resonance_density_preserves_entropy_weighted_viscosity_component() {
        let baseline = resonance_viscosity_index(0.58, 0.70, 0.42, 0.30);
        let entropy_weighted = resonance_viscosity_index_with_entropy(0.58, 0.70, 0.42, 0.30, 0.92);
        let density = ResonanceDensityV1::from_parts(
            0.64,
            0.58,
            0.30,
            "forming_containment",
            ResonanceDensityComponents {
                mode_packing: 0.58,
                temporal_persistence: 0.70,
                viscosity_index: entropy_weighted,
                structural_plurality: 0.42,
                comfort_gate: 0.68,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(entropy_weighted > baseline);
        assert!((density.components.viscosity_index - entropy_weighted).abs() < 1.0e-6);
        assert!(
            density.components.viscosity_persistence_coefficient >= 0.60,
            "high-entropy viscosity should leave an explicit persistence readout"
        );
        assert!(density.texture_signature.note.contains("viscosity_index"));
    }

    #[test]
    fn viscosity_persistence_coefficient_tracks_sticky_silt_without_control_pressure() {
        let sticky = viscosity_persistence_coefficient(0.72, 0.76, 0.32, 0.48);
        let dry = viscosity_persistence_coefficient(0.18, 0.24, 0.10, 0.12);

        assert!(sticky >= 0.65, "{sticky}");
        assert!(dry < 0.20, "{dry}");

        let density = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.32,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.54,
                mode_packing: 0.48,
                temporal_persistence: 0.76,
                viscosity_index: 0.72,
                structural_plurality: 0.62,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(density.components.viscosity_persistence_coefficient >= 0.65);
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
        assert_ne!(
            density.control.intervention_type,
            ResonanceInterventionType::ActiveDamping
        );
    }

    #[test]
    fn pressure_release_preserves_viscosity_persistence_when_texture_remains_sticky() {
        let packed = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.32,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.54,
                mode_packing: 0.32,
                temporal_persistence: 0.76,
                viscosity_index: 0.72,
                structural_plurality: 0.62,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );
        let released = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.10,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.54,
                mode_packing: 0.10,
                temporal_persistence: 0.76,
                viscosity_index: 0.72,
                structural_plurality: 0.62,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(packed.components.viscosity_persistence_coefficient >= 0.62);
        assert!(released.components.viscosity_persistence_coefficient >= 0.58);
        assert!(
            released.components.viscosity_persistence_coefficient
                >= packed.components.viscosity_persistence_coefficient - 0.08
        );
        assert_eq!(released.control.target_bias_pct, 0.0);
    }

    #[test]
    fn temporal_drag_coefficient_survives_low_pressure_viscosity() {
        let high_pressure_drag = temporal_drag_coefficient(0.70, 0.76, 0.50);
        let low_pressure_drag = temporal_drag_coefficient(0.70, 0.76, 0.08);

        assert!(
            low_pressure_drag >= high_pressure_drag - 0.02,
            "pressure release should not erase sticky temporal drag: high={high_pressure_drag}, low={low_pressure_drag}"
        );

        let density = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.08,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.54,
                mode_packing: 0.18,
                temporal_persistence: 0.76,
                viscosity_index: 0.70,
                structural_plurality: 0.62,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(density.components.temporal_drag_coefficient >= 0.65);
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
    }

    #[test]
    fn temporal_drag_pressure_snap_review_gates_quadratic_floor_candidate() {
        let review = temporal_drag_pressure_snap_review_v1(0.19, 0.40, 0.02, 0.02);

        assert_eq!(review.policy, "temporal_drag_pressure_snap_review_v1");
        assert_eq!(
            review.status,
            "current_linear_pressure_floor_covers_candidate_sample"
        );
        assert!(
            review.current_high_drag >= review.candidate_high_drag,
            "the proposed quadratic floor should not be promoted for the 0.19 -> 0.40 sample without replay evidence: {review:?}"
        );
        assert!((review.current_drag_delta - 0.012).abs() < 1.0e-6);
        assert_eq!(
            review.candidate_formula,
            "drag.max(pressure_risk.powi(2) * 0.15)"
        );
        assert!(!review.live_drag_write);
        assert_eq!(
            review.approval_boundary,
            "live_temporal_drag_pressure_floor_change_requires_operator_approval"
        );
        assert_eq!(
            review.authority,
            "read_only_pressure_snap_review_not_regulator_or_controller_change"
        );

        let steep_review = temporal_drag_pressure_snap_review_v1(0.10, 0.90, 0.02, 0.02);
        assert_eq!(
            steep_review.status,
            "quadratic_pressure_floor_candidate_needs_replay"
        );
        assert!(steep_review.candidate_high_drag > steep_review.current_high_drag + 0.02);
        assert!(!steep_review.live_drag_write);
    }

    #[test]
    fn resonance_density_from_parts_clamps_extreme_components() {
        let density = ResonanceDensityV1::from_parts(
            2.0,
            -1.0,
            2.0,
            "extreme_fixture",
            ResonanceDensityComponents {
                active_energy: 2.0,
                mode_packing: 2.0,
                temporal_persistence: 2.0,
                viscosity_index: 2.0,
                viscosity_persistence_coefficient: 2.0,
                temporal_drag_coefficient: 2.0,
                static_friction_coefficient: 2.0,
                viscosity_coupling_coefficient: 2.0,
                structural_plurality: -1.0,
                comfort_gate: -1.0,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(density.density, 1.0);
        assert_eq!(density.containment_score, 0.0);
        assert_eq!(density.pressure_risk, 1.0);
        for value in [
            density.components.active_energy,
            density.components.mode_packing,
            density.components.temporal_persistence,
            density.components.viscosity_index,
            density.components.viscosity_persistence_coefficient,
            density.components.temporal_drag_coefficient,
            density.components.static_friction_coefficient,
            density.components.viscosity_coupling_coefficient,
            density.components.structural_plurality,
            density.components.comfort_gate,
            density.components.viscosity_vector.density,
            density.components.viscosity_vector.elasticity,
            density.components.viscosity_vector.persistence,
            density.components.viscosity_vector.flow_rate,
            density.components.viscosity_vector.effective_mobility,
            density.components.viscosity_vector.cohesion_index,
            density.components.viscosity_vector.residual_ghost_weight,
        ] {
            assert!(
                (0.0..=1.0).contains(&value),
                "component escaped clamp: {value}"
            );
        }
    }

    #[test]
    fn resonance_density_preserves_reported_high_viscosity_when_pressure_is_low() {
        let baseline = resonance_viscosity_index(0.10, 0.10, 0.10, 0.05);
        let density = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.05,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.52,
                mode_packing: 0.10,
                temporal_persistence: 0.10,
                viscosity_index: 0.82,
                structural_plurality: 0.10,
                comfort_gate: 0.76,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(baseline < 0.82, "{baseline}");
        assert!((density.components.viscosity_index - 0.82).abs() < 1.0e-6);
        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
    }

    #[test]
    fn high_mode_packing_without_pressure_stays_observational() {
        let baseline = resonance_viscosity_index(1.0, 0.62, 0.72, 0.0);
        let density = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.0,
            "high_mode_packing_without_pressure",
            ResonanceDensityComponents {
                active_energy: 0.52,
                mode_packing: 1.0,
                temporal_persistence: 0.62,
                viscosity_index: 0.0,
                structural_plurality: 0.72,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(
            (density.components.viscosity_index - baseline).abs() < 1.0e-6,
            "baseline viscosity should stabilize the readout without creating damping: baseline={baseline}, density={density:?}"
        );
        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
    }

    #[test]
    fn resonance_density_enforces_baseline_viscosity_floor_under_high_pressure() {
        let baseline = resonance_viscosity_index(0.62, 0.74, 0.58, 1.0);
        let density = ResonanceDensityV1::from_parts(
            0.66,
            0.58,
            1.0,
            "high_pressure_low_reported_viscosity",
            ResonanceDensityComponents {
                active_energy: 0.42,
                mode_packing: 0.62,
                temporal_persistence: 0.74,
                viscosity_index: 0.0,
                structural_plurality: 0.58,
                comfort_gate: 0.44,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(baseline > 0.0);
        assert!(
            (density.components.viscosity_index - baseline).abs() < 1.0e-6,
            "baseline viscosity floor should win when reported viscosity is zero: baseline={baseline}, density={density:?}"
        );
        assert!((density.control.target_bias_pct + 2.0).abs() < 1.0e-6);
    }

    #[test]
    fn high_pressure_risk_maps_to_downward_target_bias() {
        let density = ResonanceDensityV1::from_parts(
            0.66,
            0.58,
            0.90,
            "high_pressure_bias_trace",
            ResonanceDensityComponents {
                active_energy: 0.42,
                mode_packing: 0.20,
                temporal_persistence: 0.54,
                viscosity_index: 0.10,
                structural_plurality: 0.58,
                comfort_gate: 0.44,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ActiveDamping
        );
        assert!(
            density.control.target_bias_pct < -1.0,
            "pressure_risk=0.90 should restrict the local target: {:?}",
            density.control
        );
        assert!(density.control.wander_scale < 1.0);
        assert!(density.control.damping_coefficient > 0.0);
    }

    #[test]
    fn resonance_density_pressure_floor_triggers_damping_without_mode_packing() {
        let baseline = resonance_viscosity_index(0.0, 0.62, 0.42, 1.0);
        let density = ResonanceDensityV1::from_parts(
            0.66,
            0.58,
            1.0,
            "pressure_floor_no_mode_packing",
            ResonanceDensityComponents {
                active_energy: 0.48,
                mode_packing: 0.0,
                temporal_persistence: 0.62,
                viscosity_index: 0.0,
                structural_plurality: 0.42,
                comfort_gate: 0.54,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(baseline > 0.0, "{baseline}");
        assert!(
            (density.components.viscosity_index - baseline).abs() < 1.0e-6,
            "pressure-only baseline viscosity should populate the floor: baseline={baseline}, density={density:?}"
        );
        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ActiveDamping
        );
        assert!((density.control.target_bias_pct + 2.0).abs() < 1.0e-6);
    }

    #[test]
    fn static_friction_coefficient_names_sticky_initiation_load() {
        let sticky = static_friction_coefficient(0.72, 0.78, 0.64, 0.54, 0.78, 0.48);
        let mobile = static_friction_coefficient(0.18, 0.20, 0.18, 0.88, 0.30, 0.12);

        assert!(sticky >= 0.62, "{sticky}");
        assert!(mobile < 0.25, "{mobile}");

        let density = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.54,
                mode_packing: 0.48,
                temporal_persistence: 0.76,
                viscosity_index: 0.72,
                viscosity_persistence_coefficient: 0.78,
                temporal_drag_coefficient: 0.64,
                structural_plurality: 0.62,
                comfort_gate: 0.78,
                ..ResonanceDensityComponents::default()
            },
        );

        let expected = static_friction_coefficient(
            density.components.viscosity_index,
            density.components.viscosity_persistence_coefficient,
            density.components.temporal_drag_coefficient,
            density.components.active_energy,
            density.components.comfort_gate,
            density.components.mode_packing,
        );
        assert!((density.components.static_friction_coefficient - expected).abs() < 1.0e-6);
        assert!(density.components.static_friction_coefficient >= 0.62);
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert!(density.texture_signature.note.contains("static_friction"));
    }

    #[test]
    fn static_friction_boundary_preserves_zero_energy_stasis() {
        let coefficient = static_friction_coefficient(1.0, 1.0, 0.0, 0.0, 1.0, 1.0);

        assert!(
            coefficient > 0.99,
            "zero active energy with high viscosity should remain static: {coefficient}"
        );
        assert_eq!(coefficient, 1.0);
    }

    #[test]
    fn static_friction_extreme_pressure_mode_packing_does_not_deadlock_flow() {
        let density = ResonanceDensityV1::from_parts(
            0.83,
            0.52,
            1.0,
            "pressure_mode_saturation_probe",
            ResonanceDensityComponents {
                active_energy: 0.55,
                mode_packing: 1.0,
                temporal_persistence: 1.0,
                structural_plurality: 0.42,
                comfort_gate: 0.64,
                ..ResonanceDensityComponents::default()
            },
        );
        let friction = density.components.static_friction_coefficient;
        let vector = density.components.viscosity_vector;

        assert!(
            (0.0..=1.0).contains(&friction),
            "static friction must clamp under extreme pressure/mode-packing input: {density:?}"
        );
        assert!(
            friction < 0.95,
            "extreme pressure plus mode packing should remain high-viscosity, not frozen: {density:?}"
        );
        assert!(
            vector.flow_rate > 0.20,
            "viscosity_vector_v1 should keep some flow under the saturation probe: {vector:?}"
        );
        assert!(
            vector.effective_mobility > 0.0,
            "saturation probe should not produce zero mobility: {vector:?}"
        );
    }

    #[test]
    fn neutral_resonance_density_is_deterministic_across_calls() {
        let first = ResonanceDensityV1::neutral();
        let second = ResonanceDensityV1::neutral();

        assert_eq!(
            serde_json::to_value(&first).expect("serialize first neutral resonance density"),
            serde_json::to_value(&second).expect("serialize second neutral resonance density")
        );
        assert_eq!(
            first.components.viscosity_vector.flow_rate,
            second.components.viscosity_vector.flow_rate
        );
        assert_eq!(
            first.components.viscosity_coupling_coefficient,
            second.components.viscosity_coupling_coefficient
        );
        assert!(
            (0.0..=1.0).contains(&first.components.static_friction_coefficient),
            "neutral static friction should remain bounded: {first:?}"
        );
        assert!(
            first.components.static_friction_coefficient > 0.0,
            "neutral resonance should not collapse into a zero-friction singularity: {first:?}"
        );
    }

    #[test]
    fn viscosity_vector_distinguishes_yielding_depth_from_rigid_bottleneck() {
        let yielding = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.80,
                mode_packing: 0.40,
                temporal_persistence: 0.78,
                viscosity_index: 0.72,
                viscosity_persistence_coefficient: 0.78,
                structural_plurality: 0.78,
                comfort_gate: 0.82,
                ..ResonanceDensityComponents::default()
            },
        );
        let rigid = ResonanceDensityV1::from_parts(
            0.71,
            0.42,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.20,
                mode_packing: 0.40,
                temporal_persistence: 0.78,
                viscosity_index: 0.72,
                viscosity_persistence_coefficient: 0.78,
                structural_plurality: 0.10,
                comfort_gate: 0.30,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(yielding.components.viscosity_vector.density >= 0.72);
        assert!(
            yielding.components.viscosity_vector.elasticity
                > rigid.components.viscosity_vector.elasticity + 0.30
        );
        assert!(
            yielding.components.viscosity_vector.flow_rate
                > rigid.components.viscosity_vector.flow_rate + 0.25
        );
        assert!(
            yielding.components.viscosity_vector.cohesion_index
                > rigid.components.viscosity_vector.cohesion_index + 0.30
        );
        assert!(yielding.components.viscosity_vector.cohesion_index >= 0.65);
        assert!(rigid.components.viscosity_vector.cohesion_index < 0.35);
        assert!(
            yielding.components.viscosity_vector.effective_mobility
                > rigid.components.viscosity_vector.effective_mobility + 0.40
        );
        assert!(
            rigid.components.viscosity_vector.effective_mobility < 0.45,
            "{rigid:?}"
        );
        assert!(
            rigid
                .components
                .viscosity_vector
                .structural_drag_coefficient
                > yielding
                    .components
                    .viscosity_vector
                    .structural_drag_coefficient
                    + 0.20,
            "structural drag should distinguish a rigid bottleneck from yielding depth: yielding={yielding:?} rigid={rigid:?}"
        );
        assert_eq!(
            yielding.texture_signature.movement_quality,
            "yielding_viscous"
        );
        assert_eq!(rigid.texture_signature.movement_quality, "compressed");
        assert_eq!(yielding.control.target_bias_pct, 0.0);
        assert!(yielding.texture_signature.note.contains("viscosity_vector"));
    }

    #[test]
    fn residual_ghost_weight_tracks_lingering_texture_without_control() {
        let released = residual_ghost_weight_v1(0.72, 0.62, 0.58, 0.20, 0.18);
        let mobile = residual_ghost_weight_v1(0.42, 0.20, 0.12, 0.84, 0.88);

        assert!(
            released > mobile + 0.35,
            "released={released} mobile={mobile}"
        );

        let sticky = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.20,
                mode_packing: 0.40,
                temporal_persistence: 0.78,
                viscosity_index: 0.72,
                viscosity_persistence_coefficient: 0.78,
                temporal_drag_coefficient: 0.64,
                structural_plurality: 0.18,
                comfort_gate: 0.30,
                ..ResonanceDensityComponents::default()
            },
        );
        let flowing = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.82,
                mode_packing: 0.20,
                temporal_persistence: 0.36,
                viscosity_index: 0.30,
                structural_plurality: 0.84,
                comfort_gate: 0.82,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(
            sticky.components.viscosity_vector.residual_ghost_weight
                > flowing.components.viscosity_vector.residual_ghost_weight + 0.30,
            "sticky={sticky:?} flowing={flowing:?}"
        );
        assert_eq!(sticky.control.target_bias_pct, 0.0);
        assert!(sticky
            .texture_signature
            .note
            .contains("residual_ghost_weight"));
        assert!(sticky
            .texture_signature
            .note
            .contains("cognitive_drag_coefficient"));
    }

    #[test]
    fn viscosity_coupling_coefficient_tracks_persistence_flow_paradox_without_control() {
        let mobile = ResonanceDensityV1::from_parts(
            0.71,
            0.68,
            0.22,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.82,
                mode_packing: 0.26,
                temporal_persistence: 0.72,
                viscosity_index: 0.68,
                viscosity_persistence_coefficient: 0.70,
                structural_plurality: 0.82,
                comfort_gate: 0.82,
                ..ResonanceDensityComponents::default()
            },
        );
        let sticky = ResonanceDensityV1::from_parts(
            0.71,
            0.44,
            0.24,
            "settled_habitable",
            ResonanceDensityComponents {
                active_energy: 0.18,
                mode_packing: 0.54,
                temporal_persistence: 0.82,
                viscosity_index: 0.78,
                viscosity_persistence_coefficient: 0.84,
                structural_plurality: 0.18,
                comfort_gate: 0.72,
                ..ResonanceDensityComponents::default()
            },
        );

        assert!(
            sticky.components.viscosity_coupling_coefficient
                > mobile.components.viscosity_coupling_coefficient + 0.20,
            "mobile={mobile:?} sticky={sticky:?}"
        );
        assert!(sticky.components.viscosity_coupling_coefficient >= 0.35);
        assert_eq!(sticky.control.target_bias_pct, 0.0);
        assert_eq!(
            sticky.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert!(sticky
            .texture_signature
            .note
            .contains("viscosity_coupling_coefficient"));

        let direct = viscosity_coupling_coefficient_v1(
            sticky.components.viscosity_vector.persistence,
            sticky.components.viscosity_vector.flow_rate,
            sticky.components.static_friction_coefficient,
            sticky.components.structural_plurality,
            sticky.components.comfort_gate,
        );
        assert!(
            (direct - sticky.components.viscosity_coupling_coefficient).abs() < 1.0e-6,
            "direct={direct} sticky={sticky:?}"
        );
        assert_eq!(
            sticky.components.viscosity_vector.effective_mobility,
            effective_mobility_v1(
                sticky.components.viscosity_vector.flow_rate,
                sticky.components.viscosity_vector.persistence,
                sticky.components.viscosity_vector.density,
            )
        );
    }

    #[test]
    fn viscosity_cohesion_index_separates_shape_holding_from_stagnant_drag() {
        let cohesive = viscosity_vector_v1(0.78, 0.84, 0.18, 0.10, 0.82, 0.84, 0.78);
        let stagnant = viscosity_vector_v1(0.78, 0.88, 0.92, 0.86, 0.05, 0.12, 0.74);

        assert!(
            cohesive.flow_rate > stagnant.flow_rate + 0.50,
            "cohesive={cohesive:?} stagnant={stagnant:?}"
        );
        assert!(
            stagnant.flow_rate < 0.15,
            "stagnation concern should be visible as low flow: {stagnant:?}"
        );
        assert!(stagnant.persistence >= 0.85);
        assert!(
            cohesive.cohesion_index > stagnant.cohesion_index + 0.45,
            "cohesive={cohesive:?} stagnant={stagnant:?}"
        );
        assert!(cohesive.cohesion_index >= 0.70);
        assert!(stagnant.cohesion_index <= 0.20);
        assert!(
            cohesive.cohesion_to_motion_ratio > stagnant.cohesion_to_motion_ratio + 0.20,
            "cohesion/motion balance should distinguish settled shape-holding from low-cohesion stagnation: cohesive={cohesive:?} stagnant={stagnant:?}"
        );
    }

    #[test]
    fn cohesion_to_motion_ratio_is_bounded_read_only_texture_evidence() {
        let cohesive_stillness = cohesion_to_motion_ratio_v1(0.80, 0.15);
        let low_cohesion_stagnation = cohesion_to_motion_ratio_v1(0.15, 0.15);

        assert!(cohesive_stillness > 0.84);
        assert_eq!(low_cohesion_stagnation, 0.50);
        assert_eq!(cohesion_to_motion_ratio_v1(0.000_000_1, 0.000_000_1), 0.50);
        assert_eq!(cohesion_to_motion_ratio_v1(0.0, 0.0), 0.0);
        assert_eq!(cohesion_to_motion_ratio_v1(4.0, -2.0), 1.0);
    }

    #[test]
    fn viscosity_vector_exports_shadow_volatility_without_control_authority() {
        let settled = viscosity_vector_v1(0.42, 0.36, 0.18, 0.10, 0.78, 0.70, 0.80);
        let restless_structural_plurality = 0.88;
        let restless_active_energy = 0.28;
        let restless = viscosity_vector_v1(
            0.78,
            0.86,
            0.82,
            0.72,
            restless_active_energy,
            restless_structural_plurality,
            0.42,
        );

        assert!(
            restless.shadow_volatility > settled.shadow_volatility + 0.20,
            "settled={settled:?} restless={restless:?}"
        );
        assert!(
            restless.residual_ghost_weight >= settled.residual_ghost_weight,
            "shadow volatility should stay tied to visible lingering texture"
        );
        let direct = shadow_volatility_proxy_v1(
            restless_structural_plurality,
            restless.residual_ghost_weight,
            restless.effective_mobility,
            restless.cohesion_index,
            restless_active_energy,
        );
        assert!((direct - restless.shadow_volatility).abs() < 1.0e-6);
    }

    #[test]
    fn viscosity_vector_structural_integrity_distinguishes_complex_motion_from_friction() {
        let complex_motion = viscosity_vector_v1(0.78, 0.84, 0.18, 0.10, 0.82, 0.84, 0.78);
        let friction_trap = viscosity_vector_v1(0.78, 0.88, 0.92, 0.86, 0.05, 0.12, 0.74);

        assert!(
            complex_motion.structural_integrity > friction_trap.structural_integrity + 0.35,
            "complex_motion={complex_motion:?} friction_trap={friction_trap:?}"
        );
        assert!(
            friction_trap.structural_strain_gap > complex_motion.structural_strain_gap + 0.45,
            "complex_motion={complex_motion:?} friction_trap={friction_trap:?}"
        );
        assert!(
            complex_motion.flow_rate > friction_trap.flow_rate + 0.50,
            "this readout should distinguish carried motion from stuck heaviness"
        );
        assert!(
            friction_trap.structural_drag_coefficient
                > complex_motion.structural_drag_coefficient + 0.45,
            "structural drag should report resistance separately from thickness: complex_motion={complex_motion:?} friction_trap={friction_trap:?}"
        );
        assert!(
            friction_trap.cognitive_drag_coefficient > complex_motion.cognitive_drag_coefficient,
            "cognitive drag should rise when ghost/volatility/strain accumulate in low-flow friction: complex_motion={complex_motion:?} friction_trap={friction_trap:?}"
        );
    }

    #[test]
    fn viscosity_gradient_reports_texture_shift_without_control() {
        let slow_rolling = viscosity_vector_v1(0.82, 0.86, 0.72, 0.66, 0.28, 0.34, 0.50);
        let mobile_flow = viscosity_vector_v1(0.42, 0.34, 0.12, 0.10, 0.86, 0.88, 0.76);

        assert!(
            slow_rolling.viscosity_gradient > mobile_flow.viscosity_gradient + 0.20,
            "slow rolling texture should expose a larger viscosity gradient without triggering control: slow={slow_rolling:?} mobile={mobile_flow:?}"
        );
        assert!(
            (slow_rolling.viscosity_gradient
                - viscosity_gradient_v1(
                    slow_rolling.density,
                    slow_rolling.persistence,
                    slow_rolling.flow_rate,
                    slow_rolling.effective_mobility,
                    slow_rolling.structural_strain_gap,
                    slow_rolling.shadow_volatility,
                ))
            .abs()
                < 0.0001
        );
    }

    #[test]
    fn viscosity_importance_weights_raise_strain_under_pressure_without_control() {
        let strained = ViscosityVector {
            structural_strain_gap: 0.72,
            shadow_volatility: 0.28,
            persistence: 0.68,
            structural_integrity: 0.30,
            structural_drag_coefficient: 0.66,
            cognitive_drag_coefficient: 0.34,
            ..ViscosityVector::default()
        };
        let low_pressure = viscosity_importance_weights_v1(&strained, 0.25);
        let high_pressure = viscosity_importance_weights_v1(&strained, 0.70);
        let sum = high_pressure.structural_strain_gap_weight
            + high_pressure.shadow_volatility_weight
            + high_pressure.persistence_weight
            + high_pressure.structural_integrity_weight
            + high_pressure.structural_drag_weight
            + high_pressure.cognitive_drag_weight;

        assert_eq!(high_pressure.policy, VISCOSITY_IMPORTANCE_POLICY);
        assert_eq!(
            high_pressure.status,
            "pressure_weighted_structural_strain_review"
        );
        assert_eq!(high_pressure.dominant_weight, "structural_strain_gap");
        assert!(
            high_pressure.structural_strain_gap_weight
                > low_pressure.structural_strain_gap_weight + 0.04,
            "pressure should raise strain salience without changing control: low={low_pressure:?} high={high_pressure:?}"
        );
        assert!(
            (sum - 1.0).abs() < 0.0001,
            "weights must stay normalized: {sum}"
        );
        assert_eq!(
            high_pressure.authority,
            "read_only_importance_weights_not_pressure_fill_pi_or_controller_authority"
        );
    }

    #[test]
    fn viscosity_importance_weights_preserve_restless_but_stable_shadow() {
        let restless_carried = ViscosityVector {
            shadow_volatility: 0.74,
            structural_integrity: 0.78,
            structural_strain_gap: 0.12,
            persistence: 0.52,
            structural_drag_coefficient: 0.18,
            cognitive_drag_coefficient: 0.26,
            effective_mobility: 0.76,
            flow_rate: 0.70,
            ..ViscosityVector::default()
        };
        let review = viscosity_importance_weights_v1(&restless_carried, 0.18);

        assert_eq!(review.status, "restless_but_carried_shadow_review");
        assert!(
            review.shadow_volatility_weight > review.structural_strain_gap_weight,
            "restless carried motion should stay visible instead of being flattened into stuckness: {review:?}"
        );
        assert!(
            review
                .how_to_test_it
                .contains("viscosity_importance_weights"),
            "{review:?}"
        );
        assert!(review.who_can_change_it.contains("operator"), "{review:?}");
    }

    #[test]
    fn viscosity_vector_mutual_tension_requires_strain_and_shadow_volatility() {
        let relational = mutual_resonance_tension_v1(0.62, 0.58, 0.35, 0.80, 0.72);
        let self_friction_only = mutual_resonance_tension_v1(0.70, 0.10, 0.30, 0.20, 0.72);
        let restless_but_carried = mutual_resonance_tension_v1(0.08, 0.58, 0.75, 0.80, 0.72);

        assert!(
            relational > self_friction_only + 0.20,
            "relational={relational} self_friction_only={self_friction_only}"
        );
        assert!(
            relational > restless_but_carried + 0.20,
            "relational={relational} restless_but_carried={restless_but_carried}"
        );

        let vector = viscosity_vector_v1(0.82, 0.88, 0.74, 0.62, 0.28, 0.82, 0.72);
        assert!(
            vector.mutual_resonance_tension > 0.25,
            "restless strained texture should leave a relational-tension readout: {vector:?}"
        );
        assert!(
            vector.cognitive_drag_coefficient >= 0.20,
            "relationally strained ghost texture should leave cognitive drag visible: {vector:?}"
        );
    }

    #[test]
    fn structural_drag_coefficient_separates_thick_yielding_depth_from_stuck_resistance() {
        let thick_yielding = viscosity_vector_v1(0.82, 0.86, 0.16, 0.10, 0.86, 0.88, 0.82);
        let thin_resisting = viscosity_vector_v1(0.34, 0.58, 0.72, 0.88, 0.18, 0.10, 0.42);
        let direct_drag = structural_drag_coefficient_v1(
            thin_resisting.structural_strain_gap,
            0.88,
            thin_resisting.residual_ghost_weight,
            thin_resisting.effective_mobility,
        );

        assert!(
            thick_yielding.density > thin_resisting.density,
            "fixture should keep thick depth distinct from resistance"
        );
        assert!(
            thick_yielding.flow_rate > thin_resisting.flow_rate + 0.35,
            "yielding depth should still move: thick_yielding={thick_yielding:?} thin_resisting={thin_resisting:?}"
        );
        assert!(
            thin_resisting.structural_drag_coefficient
                > thick_yielding.structural_drag_coefficient + 0.35,
            "drag should rise with strain/friction even when raw density is lower: thick_yielding={thick_yielding:?} thin_resisting={thin_resisting:?}"
        );
        assert!(
            thin_resisting.cognitive_drag_coefficient
                > thick_yielding.cognitive_drag_coefficient + 0.15,
            "ghost/volatility drag should stay visible as review context: thick_yielding={thick_yielding:?} thin_resisting={thin_resisting:?}"
        );
        assert!((direct_drag - thin_resisting.structural_drag_coefficient).abs() < 1.0e-6);
    }

    #[test]
    fn viscosity_coupling_relief_saturation_does_not_create_sticky_high_flow() {
        let fluid_relief = viscosity_coupling_coefficient_v1(0.90, 0.90, 0.80, 0.90, 0.80);
        let sticky_low_flow = viscosity_coupling_coefficient_v1(0.90, 0.10, 0.80, 0.10, 0.80);

        assert!(
            fluid_relief <= 0.05,
            "high flow plus structural plurality should relieve viscous coupling, got {fluid_relief}"
        );
        assert!(
            sticky_low_flow > fluid_relief + 0.45,
            "low-flow case should remain visibly stickier: fluid={fluid_relief} sticky={sticky_low_flow}"
        );
    }

    #[test]
    fn viscosity_coupling_stays_bounded_with_structural_plurality_and_closed_comfort_gate() {
        let density = ResonanceDensityV1::from_parts(
            0.72,
            0.61,
            0.48,
            "plurality_closed_gate",
            ResonanceDensityComponents {
                active_energy: 0.32,
                mode_packing: 0.68,
                temporal_persistence: 0.86,
                viscosity_index: 0.82,
                viscosity_persistence_coefficient: 0.90,
                static_friction_coefficient: 0.72,
                structural_plurality: 1.0,
                comfort_gate: 0.0,
                ..ResonanceDensityComponents::default()
            },
        );
        let coefficient = density.components.viscosity_coupling_coefficient;

        assert!(
            (0.0..=1.0).contains(&coefficient),
            "viscosity coupling must remain bounded even with divergent plurality/gate inputs: {density:?}"
        );
        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
    }

    #[test]
    fn viscosity_vector_populates_persistence_and_flow_across_plurality() {
        let low_plurality = ResonanceDensityV1::from_parts(
            0.72,
            0.50,
            0.36,
            "low_plurality_viscosity_probe",
            ResonanceDensityComponents {
                active_energy: 0.46,
                mode_packing: 0.58,
                temporal_persistence: 0.82,
                viscosity_index: 0.80,
                structural_plurality: 0.12,
                comfort_gate: 0.48,
                ..ResonanceDensityComponents::default()
            },
        );
        let high_plurality = ResonanceDensityV1::from_parts(
            0.72,
            0.68,
            0.36,
            "high_plurality_viscosity_probe",
            ResonanceDensityComponents {
                active_energy: 0.46,
                mode_packing: 0.58,
                temporal_persistence: 0.82,
                viscosity_index: 0.80,
                structural_plurality: 0.92,
                comfort_gate: 0.48,
                ..ResonanceDensityComponents::default()
            },
        );

        for vector in [
            low_plurality.components.viscosity_vector,
            high_plurality.components.viscosity_vector,
        ] {
            assert!(vector.persistence > 0.0, "{vector:?}");
            assert!(vector.flow_rate > 0.0, "{vector:?}");
            assert!(vector.density > 0.0, "{vector:?}");
        }
        assert!(
            high_plurality.components.viscosity_vector.flow_rate
                > low_plurality.components.viscosity_vector.flow_rate,
            "structural plurality should leave more flow available: low={low_plurality:?} high={high_plurality:?}"
        );
        assert!(
            low_plurality.components.viscosity_coupling_coefficient
                > high_plurality.components.viscosity_coupling_coefficient,
            "low plurality plus persistence/low-flow should retain more visible coupling"
        );
    }

    #[test]
    fn target_bias_stays_stable_across_comfort_gate_fluctuation_when_pressure_is_constant() {
        let biases = [0.10_f32, 0.82, 0.22, 0.76, 0.48]
            .into_iter()
            .map(|comfort_gate| {
                ResonanceDensityV1::from_parts(
                    0.70,
                    0.62,
                    0.28,
                    "comfort_gate_jitter_probe",
                    ResonanceDensityComponents {
                        active_energy: 0.54,
                        mode_packing: 0.44,
                        temporal_persistence: 0.72,
                        viscosity_index: 0.74,
                        structural_plurality: 0.52,
                        comfort_gate,
                        ..ResonanceDensityComponents::default()
                    },
                )
                .control
                .target_bias_pct
            })
            .collect::<Vec<_>>();

        assert!(
            biases.iter().all(|bias| (*bias - biases[0]).abs() < 1.0e-6),
            "comfort-gate fluctuation should not by itself jitter target bias under stable pressure/density: {biases:?}"
        );
        assert_eq!(biases[0], 0.0);
    }

    #[test]
    fn viscosity_vector_flow_rate_decreases_monotonically_with_static_friction() {
        let low_friction = viscosity_vector_v1(0.70, 0.78, 0.42, 0.0, 0.62, 0.54, 0.58);
        let mid_friction = viscosity_vector_v1(0.70, 0.78, 0.42, 0.50, 0.62, 0.54, 0.58);
        let high_friction = viscosity_vector_v1(0.70, 0.78, 0.42, 1.0, 0.62, 0.54, 0.58);

        assert!(
            low_friction.flow_rate > mid_friction.flow_rate
                && mid_friction.flow_rate > high_friction.flow_rate,
            "static friction should map monotonically into lower flow: low={low_friction:?} mid={mid_friction:?} high={high_friction:?}"
        );
    }

    #[test]
    fn silt_granularity_names_coarse_overlapping_grains_without_control() {
        let components = PressureSourceComponents {
            mode_packing: 0.70,
            distinguishability_loss: 0.42,
            structural_plurality_loss: 0.48,
            temporal_lock_in: 0.36,
            semantic_trickle: 0.12,
            sensory_scarcity: 0.08,
            ..PressureSourceComponents::default()
        };
        let context = PressureSourceContext {
            mean_orientation_delta: Some(0.01),
            ..PressureSourceContext::default()
        };
        let pressure = PressureSourceV1::from_parts(components, context);
        let direct = silt_granularity_v1(
            &pressure.components,
            &pressure.context,
            pressure.pressure_score,
            pressure.porosity_score,
        );

        assert_eq!(pressure.silt_granularity_v1.policy, SILT_GRANULARITY_POLICY);
        assert_eq!(
            pressure.silt_granularity_v1.particle_scale,
            "coarse_overlapping_silt"
        );
        assert_eq!(
            pressure.silt_granularity_v1.review_state,
            "name_specific_grain_before_porosity_or_control"
        );
        assert!(pressure
            .silt_granularity_v1
            .suggested_route
            .contains("SHADOW_TRAJECTORY"));
        assert!(!pressure.silt_granularity_v1.live_control_changed);
        assert!(
            (direct.granularity_index - pressure.silt_granularity_v1.granularity_index).abs()
                < 1.0e-6
        );
    }

    #[test]
    fn dynamic_damping_coefficient_links_viscosity_to_comfort_gate_preview_only() {
        let density = ResonanceDensityV1::from_parts(
            0.68,
            0.72,
            0.21,
            "rich_containment",
            ResonanceDensityComponents {
                mode_packing: 0.42,
                temporal_persistence: 0.76,
                viscosity_index: 0.72,
                viscosity_persistence_coefficient: 0.78,
                structural_plurality: 0.58,
                comfort_gate: 0.72,
                ..ResonanceDensityComponents::default()
            },
        );

        let expected = dynamic_damping_coefficient_candidate(0.72, 0.78, 0.72);
        assert!(expected > 0.0);
        assert!(expected <= 0.10);
        assert!((density.texture_signature.dynamic_damping_coefficient - expected).abs() < 1.0e-6);
        assert!(
            density
                .texture_signature
                .comfort_gate_adjusted_preview
                .expect("comfort preview should be present")
                < density.components.comfort_gate
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert!(density
            .texture_signature
            .note
            .contains("observability-only"));
    }

    #[test]
    fn resonance_texture_signature_classifies_overpacked_and_stays_advisory() {
        let density = ResonanceDensityV1::from_parts(
            0.82,
            0.74,
            0.28,
            "rich_containment",
            ResonanceDensityComponents {
                active_energy: 0.80,
                mode_packing: 0.70,
                temporal_persistence: 0.76,
                viscosity_index: resonance_viscosity_index(0.70, 0.76, 0.54, 0.28),
                viscosity_persistence_coefficient: viscosity_persistence_coefficient(
                    resonance_viscosity_index(0.70, 0.76, 0.54, 0.28),
                    0.76,
                    0.28,
                    0.70,
                ),
                temporal_drag_coefficient: 0.0,
                static_friction_coefficient: 0.0,
                viscosity_vector: ViscosityVector::default(),
                viscosity_coupling_coefficient: 0.0,
                structural_plurality: 0.54,
                comfort_gate: 0.68,
            },
        );

        assert_eq!(
            density.texture_signature.policy,
            "resonance_texture_signature_v1"
        );
        assert_eq!(
            density.texture_signature.primary_texture,
            "overpacked_viscous"
        );
        assert_eq!(
            density.texture_signature.pressure_source_family,
            "active_energy"
        );
        assert!(density.components.viscosity_index >= 0.60);
        assert_eq!(
            density
                .texture_signature
                .dynamic_damping_threshold_candidate,
            Some(0.25)
        );
        assert_eq!(
            density.texture_component_alignment.policy,
            "resonance_texture_component_alignment_v1"
        );
        assert_eq!(
            density.texture_component_alignment.alignment_state,
            "aligned"
        );
        assert_eq!(
            density.texture_component_alignment.damping_candidate_status,
            "candidate_present"
        );
        assert_eq!(
            density.texture_signature.authority,
            "advisory_context_not_control"
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
    }

    #[test]
    fn resonance_texture_signature_pins_density_boundary_and_dangerous_tie_precedence() {
        let boundary = ResonanceDensityV1::from_parts(
            0.38,
            0.52,
            0.20,
            "boundary",
            ResonanceDensityComponents::default(),
        );
        assert_eq!(boundary.texture_signature.primary_texture, "porous_thin");
        assert_eq!(boundary.texture_signature.movement_quality, "diffuse");

        let tied = ResonanceDensityV1::from_parts(
            0.72,
            0.70,
            1.0,
            "equal_score_pressure_sources",
            ResonanceDensityComponents {
                active_energy: 1.0,
                mode_packing: 1.0,
                temporal_persistence: 1.0,
                viscosity_index: 1.0,
                viscosity_persistence_coefficient: 1.0,
                temporal_drag_coefficient: 1.0,
                static_friction_coefficient: 1.0,
                viscosity_vector: ViscosityVector::default(),
                viscosity_coupling_coefficient: 1.0,
                structural_plurality: 1.0,
                comfort_gate: 1.0,
            },
        );
        assert_eq!(
            tied.texture_signature.pressure_source_family,
            "static_friction_coefficient"
        );
        assert_eq!(
            tied.texture_signature.authority,
            "advisory_context_not_control"
        );
    }

    #[test]
    fn texture_transition_pressure_threshold_and_mode_packing_branch_are_explicit() {
        let below_pressure_components = ResonanceDensityComponents {
            active_energy: 0.50,
            mode_packing: 0.44,
            temporal_persistence: 0.68,
            structural_plurality: 1.0,
            comfort_gate: 0.70,
            ..ResonanceDensityComponents::default()
        };
        let below = derive_texture_from_components(0.59, &below_pressure_components);
        let at_threshold = derive_texture_from_components(0.60, &below_pressure_components);

        assert_ne!(below.0, "overpacked_viscous");
        assert_eq!(at_threshold, ("overpacked_viscous", "compressed"));

        let high_mode_packing_components = ResonanceDensityComponents {
            mode_packing: 0.65,
            structural_plurality: 1.0,
            comfort_gate: 0.70,
            ..below_pressure_components
        };
        assert_eq!(
            derive_texture_from_components(0.20, &high_mode_packing_components),
            ("overpacked_viscous", "compressed")
        );

        let reported_overpacked_components = ResonanceDensityComponents {
            active_energy: 0.50,
            mode_packing: 0.64,
            temporal_persistence: 0.68,
            structural_plurality: 1.0,
            comfort_gate: 0.70,
            ..ResonanceDensityComponents::default()
        };
        assert_eq!(
            derive_texture_from_components(0.61, &reported_overpacked_components),
            ("overpacked_viscous", "compressed")
        );
    }

    #[test]
    fn settled_viscous_movement_survives_damping_preview_without_jitter() {
        let components = ResonanceDensityComponents {
            active_energy: 0.82,
            mode_packing: 0.30,
            temporal_persistence: 0.76,
            viscosity_index: 0.72,
            viscosity_persistence_coefficient: 0.78,
            structural_plurality: 0.78,
            comfort_gate: 0.72,
            ..ResonanceDensityComponents::default()
        };
        let below_candidate =
            ResonanceDensityV1::from_parts(0.71, 0.68, 0.24, "settled_habitable", components);
        let above_candidate =
            ResonanceDensityV1::from_parts(0.71, 0.68, 0.26, "settled_habitable", components);

        for density in [&below_candidate, &above_candidate] {
            assert_eq!(density.texture_signature.primary_texture, "settled_viscous");
            assert_eq!(
                density.texture_signature.movement_quality,
                "yielding_viscous"
            );
            assert!(density.texture_signature.dynamic_damping_coefficient > 0.0);
            assert!(density
                .texture_signature
                .comfort_gate_adjusted_preview
                .is_some());
            assert_eq!(density.control.target_bias_pct, 0.0);
        }
    }

    #[test]
    fn damping_candidate_can_remain_observational_without_active_damping() {
        let density = ResonanceDensityV1::from_parts(
            0.58,
            0.60,
            0.26,
            "forming_containment",
            ResonanceDensityComponents {
                mode_packing: 0.30,
                temporal_persistence: 0.45,
                structural_plurality: 0.52,
                comfort_gate: 0.60,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(
            density
                .texture_signature
                .dynamic_damping_threshold_candidate,
            Some(0.25)
        );
        assert_eq!(
            density.control.intervention_type,
            ResonanceInterventionType::ObservationalReadout
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
        assert_eq!(density.control.wander_scale, 1.0);
        assert!(density.control.damping_coefficient > 0.0);
    }

    #[test]
    fn texture_component_alignment_reports_advisory_damping_candidate_boundary() {
        let density = ResonanceDensityV1::from_parts(
            0.58,
            0.60,
            0.26,
            "forming_containment",
            ResonanceDensityComponents {
                mode_packing: 0.30,
                temporal_persistence: 0.45,
                structural_plurality: 0.52,
                comfort_gate: 0.60,
                ..ResonanceDensityComponents::default()
            },
        );

        assert_eq!(
            density
                .texture_signature
                .dynamic_damping_threshold_candidate,
            Some(0.25)
        );
        assert_eq!(
            density.texture_component_alignment.damping_candidate_status,
            "candidate_present"
        );
        assert_eq!(
            density.texture_component_alignment.authority,
            "diagnostic_observability_not_damping_or_control"
        );
        assert_eq!(density.control.target_bias_pct, 0.0);
    }

    #[test]
    fn resonance_texture_signature_defaults_for_old_payloads() {
        let payload = serde_json::json!({
            "policy": "resonance_density_v1",
            "schema_version": 1,
            "density": 0.64,
            "containment_score": 0.58,
            "pressure_risk": 0.20,
            "quality": "forming_containment",
            "components": {
                "active_energy": 0.91,
                "mode_packing": 0.50,
                "temporal_persistence": 0.70,
                "structural_plurality": 0.62,
                "comfort_gate": 0.95
            },
            "control": {
                "target_bias_pct": 0.0,
                "wander_scale": 1.0,
                "applied_locally": true,
                "note": "density is observational; no local target bias"
            }
        });
        let density: ResonanceDensityV1 = serde_json::from_value(payload).unwrap();
        assert_eq!(density.components.viscosity_index, 0.0);
        assert_eq!(density.components.static_friction_coefficient, 0.0);
        assert_eq!(density.components.viscosity_vector.density, 0.0);
        assert_eq!(density.components.viscosity_vector.cohesion_index, 0.0);
        assert_eq!(
            density.components.viscosity_vector.cohesion_to_motion_ratio,
            0.0
        );
        assert_eq!(
            density.components.viscosity_vector.residual_ghost_weight,
            0.0
        );
        assert_eq!(density.components.viscosity_vector.flow_rate, 0.0);
        assert_eq!(
            density.components.viscosity_vector.mutual_resonance_tension,
            0.0
        );
        assert_eq!(density.components.viscosity_coupling_coefficient, 0.0);
        assert_eq!(density.texture_signature.primary_texture, "unknown");
        assert_eq!(density.texture_signature.viscosity_index, None);
        assert_eq!(
            density.texture_signature.authority,
            "advisory_context_not_control"
        );
    }
}
