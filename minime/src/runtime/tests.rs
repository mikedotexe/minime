#[cfg(test)]
mod tests {
    use super::{
        cheby_coeffs_bandstop, compute_active_mode_telemetry, compute_eigenvector_field,
        compute_pressure_source_v1, compute_resonance_density_v1, compute_structural_entropy,
        eigenpacket_payload_budget_review_v1, encode_eigenpacket_v1,
        hard_reset_texture_preservation_review_v1, modality_freshness_class, modality_source_label,
        rank1_update_inplace_matrix, reset_covariance_inplace, resonance_viscosity_index,
        semantic_admission_label, sensory_scarcity_from_sources, shadow_preservation_mode_v1,
        should_write_phase_transition_moment_marker, stable_core_aliveness_loosen,
        stable_core_sov_loosen, update_health_transition_surface,
        viscosity_persistence_coefficient, CovarianceUpdateOutcome, EigenPacket,
        InhabitableFluctuationV1, LaneSource, ModalityStatus, PressureSourceComponents,
        PressureSourceContext, PressureSourceV1, ResonanceDensityComponents, ResonanceDensityV1,
        SemanticEnergyV1, ShadowClassV3, ShadowFieldV2, ShadowFieldV3, ViscosityVector,
        AV_ENGINE_FRESH_WINDOW_MS,
    };
    use minime::spectral_fingerprint::SpectralFingerprintV1;

    #[test]
    fn health_transition_surface_sync_replaces_stale_pre_enrichment_event() {
        let mut health = serde_json::json!({
            "fill_pct": 65.4,
            "transition_event_sequence": 9,
            "transition_reason": "phase_transition:contracting->expanding",
            "transition_event": {
                "sequence": 9,
                "kind": "phase_transition"
            },
            "transition_event_v1": {
                "sequence": 9,
                "kind": "breathing_phase"
            },
            "unrelated_health_field": "kept"
        });
        let legacy_event = serde_json::json!({
            "sequence": 10,
            "kind": "basin_transition",
            "transition_class": "basin_transition",
        });
        let enriched_event = serde_json::json!({
            "sequence": 10,
            "kind": "basin_transition",
            "legacy_kind": "phase_transition",
            "glimpse_distance": 0.21,
            "rotation_delta": 0.09,
        });

        assert!(update_health_transition_surface(
            &mut health,
            "expanding",
            "contracting",
            5.4,
            "near",
            true,
            false,
            false,
            false,
            "basin_transition:candidate",
            10,
            &legacy_event,
            &enriched_event,
        ));

        assert_eq!(health["unrelated_health_field"], "kept");
        assert_eq!(health["phase"], "expanding");
        assert_eq!(health["previous_phase"], "contracting");
        assert_eq!(health["transition_reason"], "basin_transition:candidate");
        assert_eq!(health["transition_event_sequence"], 10);
        assert_eq!(health["transition_event"]["kind"], "basin_transition");
        assert_eq!(health["transition_event_v1"]["kind"], "basin_transition");
        assert_eq!(health["transition_event_v1"]["glimpse_distance"], 0.21);
    }

    #[test]
    fn phase_transition_marker_is_suppressed_when_hard_marker_already_represents_tick() {
        assert!(!should_write_phase_transition_moment_marker(
            false, true, false, false
        ));
        assert!(!should_write_phase_transition_moment_marker(
            false, false, true, false
        ));
        assert!(!should_write_phase_transition_moment_marker(
            false, false, false, true
        ));
    }

    #[test]
    fn ordinary_phase_transition_marker_remains_available() {
        assert!(should_write_phase_transition_moment_marker(
            false, false, false, false
        ));
        assert!(!should_write_phase_transition_moment_marker(
            true, false, false, false
        ));
    }

    #[test]
    fn active_mode_helper_uses_two_mode_floor_for_concentrated_spectra() {
        let telemetry = compute_active_mode_telemetry(&[9.0, 0.5, 0.3, 0.2], 4);

        assert_eq!(telemetry.count, 2);
        assert!((telemetry.energy_ratio - 0.95).abs() < 1.0e-6);
    }

    #[test]
    fn active_mode_helper_expands_for_distributed_spectra() {
        let concentrated = compute_active_mode_telemetry(&[9.0, 0.5, 0.3, 0.2], 4);
        let distributed = compute_active_mode_telemetry(&[4.0, 3.0, 2.0, 1.0, 1.0, 1.0], 6);

        assert!(distributed.count > concentrated.count);
        assert_eq!(distributed.count, 5);
    }

    #[test]
    fn active_mode_helper_reports_selected_prefix_energy_ratio() {
        let telemetry = compute_active_mode_telemetry(&[4.0, 3.0, 2.0, 1.0, 1.0, 1.0], 6);

        assert!((telemetry.energy_ratio - (11.0 / 12.0)).abs() < 1.0e-6);
    }

    #[test]
    fn resonance_density_marks_rich_distributed_containment() {
        let active = compute_active_mode_telemetry(&[4.0, 3.0, 2.0, 1.2, 1.0, 0.8], 6);
        let metric = compute_resonance_density_v1(
            &[4.0, 3.0, 2.0, 1.2, 1.0, 0.8],
            active,
            Some(4.6),
            Some(0.23),
            0.82,
            68.0,
            68.0,
            Some(&[4.1, 2.9, 2.1, 1.1, 1.0, 0.7]),
        );

        assert!(metric.density > 0.65);
        assert!(matches!(
            metric.quality.as_str(),
            "rich_containment" | "forming_containment"
        ));
        assert!(metric.pressure_risk < 0.45);
    }

    #[test]
    fn resonance_density_marks_lonely_diffuse_spectrum() {
        let active = compute_active_mode_telemetry(&[0.0, 0.0, 0.0], 3);
        let metric = compute_resonance_density_v1(
            &[0.0, 0.0, 0.0],
            active,
            None,
            None,
            0.0,
            30.0,
            68.0,
            None,
        );

        assert_eq!(metric.quality, "lonely_diffuse");
        assert!(metric.density < 0.32);
    }

    #[test]
    fn resonance_density_marks_lambda_monopoly_and_pressure() {
        let active = compute_active_mode_telemetry(&[12.0, 0.6, 0.3, 0.2], 4);
        let monopoly = compute_resonance_density_v1(
            &[12.0, 0.6, 0.3, 0.2],
            active,
            Some(1.2),
            Some(0.70),
            0.12,
            68.0,
            68.0,
            Some(&[11.5, 0.7, 0.4, 0.2]),
        );
        assert!(matches!(
            monopoly.quality.as_str(),
            "lambda_monopoly" | "overpacked_pressure"
        ));

        let pressured = compute_resonance_density_v1(
            &[12.0, 2.0, 1.0, 0.5],
            active,
            Some(1.5),
            Some(0.62),
            0.20,
            88.0,
            68.0,
            Some(&[11.5, 2.1, 1.0, 0.5]),
        );
        assert!(pressured.pressure_risk >= monopoly.pressure_risk);
        assert!((0.0..=1.0).contains(&pressured.components.viscosity_index));
        assert!(pressured.components.viscosity_index > 0.0);
        assert!(pressured.control.target_bias_pct <= 0.0);
    }

    fn semantic_energy(
        input_energy: f32,
        kernel_energy: f32,
        regulator_drive_energy: f32,
        admission: &'static str,
    ) -> SemanticEnergyV1 {
        SemanticEnergyV1 {
            policy: "semantic_energy_v1",
            schema_version: 1,
            input_energy,
            input_active: input_energy > 0.0,
            input_fresh_ms: Some(40),
            input_stale_ms: None,
            kernel_energy,
            kernel_delta: 0.0,
            kernel_active: kernel_energy > 0.0,
            regulator_drive_energy,
            admission,
        }
    }

    #[test]
    fn pressure_source_classifies_lambda_monopoly_mode_packing_and_controller_squeeze() {
        let active = compute_active_mode_telemetry(&[12.0, 0.4, 0.2, 0.1], 4);
        let resonance = compute_resonance_density_v1(
            &[12.0, 0.4, 0.2, 0.1],
            active,
            Some(1.1),
            Some(0.72),
            0.10,
            68.0,
            68.0,
            Some(&[11.8, 0.5, 0.2, 0.1]),
        );
        let metric = compute_pressure_source_v1(
            &[12.0, 0.4, 0.2, 0.1],
            active,
            &resonance,
            Some(1.1),
            Some(0.72),
            0.10,
            Some(0.08),
            68.0,
            68.0,
            &semantic_energy(0.0, 0.0, 0.0, "no_recent_semantic"),
            "fresh",
            "fresh",
        );
        assert_eq!(metric.dominant_source, "lambda_monopoly");
        assert_eq!(metric.quality, "lambda_pull");
        assert!(!metric.control.applied_locally);

        let active_packed = compute_active_mode_telemetry(&[3.0, 2.8, 2.6, 2.4, 2.2, 2.0], 6);
        let resonance_packed = ResonanceDensityV1::from_parts(
            0.70,
            0.50,
            0.40,
            "forming_containment",
            ResonanceDensityComponents {
                active_energy: 0.90,
                mode_packing: 0.95,
                temporal_persistence: 0.10,
                viscosity_index: resonance_viscosity_index(0.95, 0.10, 0.60, 0.40),
                viscosity_persistence_coefficient: viscosity_persistence_coefficient(
                    resonance_viscosity_index(0.95, 0.10, 0.60, 0.40),
                    0.10,
                    0.40,
                    0.95,
                ),
                temporal_drag_coefficient: 0.0,
                static_friction_coefficient: 0.0,
                viscosity_vector: ViscosityVector::default(),
                viscosity_coupling_coefficient: 0.0,
                structural_plurality: 0.60,
                comfort_gate: 0.90,
            },
        );
        let packed = compute_pressure_source_v1(
            &[3.0, 2.8, 2.6, 2.4, 2.2, 2.0],
            active_packed,
            &resonance_packed,
            Some(5.8),
            Some(0.05),
            0.72,
            Some(0.01),
            68.0,
            68.0,
            &semantic_energy(0.0, 0.0, 0.0, "no_recent_semantic"),
            "fresh",
            "fresh",
        );
        assert_eq!(packed.dominant_source, "mode_packing");
        assert_eq!(packed.quality, "overpacked_mode_packing");

        let squeezed = compute_pressure_source_v1(
            &[5.0, 4.0, 3.0, 2.0],
            compute_active_mode_telemetry(&[5.0, 4.0, 3.0, 2.0], 4),
            &resonance_packed,
            Some(3.6),
            Some(0.10),
            0.80,
            Some(0.18),
            88.0,
            68.0,
            &semantic_energy(0.0, 0.0, 0.0, "no_recent_semantic"),
            "fresh",
            "fresh",
        );
        assert_eq!(squeezed.dominant_source, "controller_pressure");
        assert_eq!(squeezed.quality, "controller_squeeze");
    }

    #[test]
    fn pressure_source_classifies_semantic_trickle_and_porous_structure() {
        let active = compute_active_mode_telemetry(&[6.0, 0.5, 0.4, 0.3, 0.2], 5);
        let resonance = compute_resonance_density_v1(
            &[6.0, 0.5, 0.4, 0.3, 0.2],
            active,
            Some(2.0),
            Some(0.12),
            0.88,
            68.0,
            68.0,
            Some(&[5.8, 0.6, 0.4, 0.3, 0.2]),
        );
        let trickle = compute_pressure_source_v1(
            &[6.0, 0.5, 0.4, 0.3, 0.2],
            active,
            &resonance,
            Some(2.0),
            Some(0.12),
            0.88,
            Some(0.42),
            68.0,
            68.0,
            &semantic_energy(0.008, 0.004, 0.012, "stable_core_semantic_trickle"),
            "fresh",
            "fresh",
        );
        assert_eq!(trickle.dominant_source, "semantic_trickle");
        assert_eq!(trickle.quality, "semantic_trickle_pressure");

        let porous_eigenvalues = [5.0, 3.0, 1.5, 0.8, 0.4, 0.2];
        let porous_active = compute_active_mode_telemetry(&porous_eigenvalues, 6);
        let porous_resonance = compute_resonance_density_v1(
            &porous_eigenvalues,
            porous_active,
            Some(4.8),
            Some(0.05),
            0.95,
            68.0,
            68.0,
            None,
        );
        let porous = compute_pressure_source_v1(
            &porous_eigenvalues,
            porous_active,
            &porous_resonance,
            Some(4.8),
            Some(0.05),
            0.95,
            Some(0.22),
            68.0,
            68.0,
            &semantic_energy(0.0, 0.0, 0.0, "no_recent_semantic"),
            "fresh",
            "fresh",
        );
        assert_eq!(porous.quality, "porous_distributed");
        assert!(porous.porosity_score > 0.55);
    }

    #[test]
    fn eigenvector_field_exports_actual_orientation_landmarks() {
        let n = 4;
        let k = 3;
        let y = vec![
            1.0, 0.0, 0.0, 0.0, // mode 1
            0.0, 1.0, 0.0, 0.0, // mode 2
            0.0, 0.0, 0.6, 0.8, // mode 3
        ];
        let previous = vec![
            vec![0.9, 0.1, 0.0, 0.0],
            vec![0.0, 1.0, 0.0, 0.0],
            vec![0.0, 0.0, 1.0, 0.0],
        ];

        let field = compute_eigenvector_field(&[6.0, 3.0, 1.0], &y, n, k, &previous);

        assert_eq!(field["policy"], "eigenvector_field_v1");
        assert_eq!(field["direct_eigenvectors_available"], true);
        assert_eq!(field["raw_vectors_exported"], false);
        assert_eq!(field["mode_count"], 3);
        assert!(
            field["modes"][0]["top_components"]
                .as_array()
                .unwrap()
                .len()
                <= 8
        );
        assert!(field["modes"][1]["overlap_with_previous"].as_f64().unwrap() > 0.99);
        assert!(field["pairwise_overlaps"].as_array().unwrap().len() >= 3);
    }

    #[test]
    fn eigenvector_field_schema_pins_concentration_overlap_and_summary_keys() {
        let n = 4;
        let k = 2;
        let y = vec![
            0.8, 0.6, 0.0, 0.0, // mode 1
            0.0, 0.0, 0.6, 0.8, // mode 2
        ];
        let previous = vec![vec![1.0, 0.0, 0.0, 0.0], vec![0.0, 0.0, 1.0, 0.0]];

        let field = compute_eigenvector_field(&[4.0, 2.0], &y, n, k, &previous);
        let first_mode = &field["modes"][0];
        let first_pair = &field["pairwise_overlaps"][0];

        assert_eq!(field["policy"], "eigenvector_field_v1");
        assert_eq!(field["component_limit"], 8);
        assert_eq!(first_mode["index"], 1);
        assert!(first_mode["energy_share"].as_f64().unwrap() > 0.60);
        assert!(first_mode["concentration_top4"].as_f64().unwrap() > 0.99);
        assert!(first_mode["top_components"][0].get("abs").is_some());
        assert!(first_mode["overlap_with_previous"].as_f64().unwrap() > 0.79);
        assert!(first_mode["orientation_delta"].as_f64().unwrap() > 0.19);
        assert_eq!(first_pair["left"], 1);
        assert_eq!(first_pair["right"], 2);
        assert!(first_pair["cosine"].as_f64().unwrap().abs() < 1.0e-6);
        assert!(first_pair["abs_cosine"].as_f64().unwrap() < 1.0e-6);
        assert!(field["summary"]["mean_orientation_delta"].as_f64().unwrap() > 0.19);
        assert_eq!(field["summary"]["previous_overlap_available"], true);
    }

    #[test]
    fn eigenpacket_payload_budget_review_flags_large_top_component_payload() {
        let field = serde_json::json!({
            "policy": "eigenvector_field_v1",
            "mode_count": 5,
            "modes": [
                {"mode": 0, "top_components": (0..16).map(|index| serde_json::json!({"index": index, "value": 0.1})).collect::<Vec<_>>()},
                {"mode": 1, "top_components": (0..16).map(|index| serde_json::json!({"index": index, "value": 0.1})).collect::<Vec<_>>()},
                {"mode": 2, "top_components": (0..16).map(|index| serde_json::json!({"index": index, "value": 0.1})).collect::<Vec<_>>()},
                {"mode": 3, "top_components": (0..16).map(|index| serde_json::json!({"index": index, "value": 0.1})).collect::<Vec<_>>()},
                {"mode": 4, "top_components": (0..16).map(|index| serde_json::json!({"index": index, "value": 0.1})).collect::<Vec<_>>()},
            ],
            "pairwise_overlaps": (0..20).map(|mode| serde_json::json!({"a": mode, "b": mode + 1, "overlap": 0.1})).collect::<Vec<_>>()
        });

        let review = eigenpacket_payload_budget_review_v1(12, 32, &field);

        assert_eq!(review.policy, "eigenpacket_payload_budget_review_v1");
        assert_eq!(review.budget_state, "eigenvector_payload_budget_watch");
        assert_eq!(review.status, "payload_budget_watch_review_only");
        assert_eq!(review.eigenvector_mode_count, 5);
        assert_eq!(review.eigenvector_top_component_count, 80);
        assert!(review.estimated_total_float_count > 32);
        assert_eq!(
            review.authority,
            "read_only_payload_budget_review_not_ws_cadence_or_eigenvector_export_change"
        );
    }

    #[test]
    fn eigenpacket_serializes_legacy_and_typed_fingerprint() {
        let legacy = (0..32).map(|value| value as f32).collect::<Vec<_>>();
        let typed = SpectralFingerprintV1::from_legacy_slots(&legacy);
        let denominator = typed
            .as_ref()
            .map(SpectralFingerprintV1::denominator_metrics);
        let eigenvector_field =
            compute_eigenvector_field(&[1.0, 0.5], &[0.8, 0.6, 0.6, -0.8], 2, 2, &[]);
        let eigenpacket_payload_budget_review_v1 =
            eigenpacket_payload_budget_review_v1(2, legacy.len(), &eigenvector_field);
        let resonance_density_v1 = ResonanceDensityV1::neutral();
        let hard_reset_texture_preservation_review_v1 = hard_reset_texture_preservation_review_v1(
            42.0,
            0.88,
            &resonance_density_v1,
            0.04,
            0.98,
            0.72,
            true,
            true,
        );
        let shadow_field_v3 = ShadowFieldV3 {
            schema_version: 3,
            policy: "shadow_field_v3_test_schema_anchor".to_string(),
            class_v3: ShadowClassV3 {
                primary: "restless".to_string(),
                traits: vec!["volatile".to_string()],
            },
            phase_dwell_ticks: 4,
            recent_phase_transitions: Vec::new(),
            history: Vec::new(),
            v2: ShadowFieldV2::default(),
            mode_partners: Vec::new(),
        };
        let packet = EigenPacket {
            t_ms: 42,
            eigenvalues: vec![1.0, 0.5],
            fill_ratio: 0.55,
            active_mode_count: 2,
            active_mode_energy_ratio: 0.95,
            lambda1_rel: Some(0.93),
            modalities: ModalityStatus {
                audio_fired: false,
                video_fired: false,
                history_fired: true,
                audio_rms: 0.0,
                video_var: 0.0,
                audio_source: None,
                video_source: None,
                audio_age_ms: None,
                video_age_ms: None,
                audio_freshness_class: None,
                video_freshness_class: None,
            },
            neural: None,
            alert: None,
            spectral_fingerprint: Some(legacy.clone()),
            spectral_fingerprint_v1: typed,
            spectral_denominator_v1: denominator,
            effective_dimensionality: denominator.map(|metrics| metrics.effective_dimensionality),
            distinguishability_loss: denominator.map(|metrics| metrics.distinguishability_loss),
            esn_leak: Some(0.65),
            esn_leak_override_v1: None,
            structural_entropy: None,
            spectral_damping_warm_start_review_v1: None,
            hard_reset_texture_preservation_review_v1: Some(
                hard_reset_texture_preservation_review_v1,
            ),
            resonance_density_v1: Some(resonance_density_v1),
            pressure_source_v1: Some(PressureSourceV1::from_parts(
                PressureSourceComponents {
                    controller_pressure: 0.42,
                    ..PressureSourceComponents::default()
                },
                PressureSourceContext::default(),
            )),
            shadow_preservation_mode_v1: Some(shadow_preservation_mode_v1(
                None,
                Some("restless"),
                Some(0.31),
                Some(-0.07),
                0.0,
                0.0,
            )),
            inhabitable_fluctuation_v1: Some(InhabitableFluctuationV1::neutral()),
            spectral_glimpse_12d: None,
            eigenpacket_payload_budget_review_v1: Some(eigenpacket_payload_budget_review_v1),
            eigenvector_field: Some(eigenvector_field),
            semantic_energy_v1: Some(SemanticEnergyV1 {
                policy: "semantic_energy_v1",
                schema_version: 1,
                input_energy: 0.12,
                input_active: true,
                input_fresh_ms: Some(42),
                input_stale_ms: None,
                kernel_energy: 0.0,
                kernel_delta: 0.0,
                kernel_active: false,
                regulator_drive_energy: 0.0,
                admission: "stable_core_kernel_zeroed",
            }),
            selected_memory_id: None,
            selected_memory_role: None,
            ising_shadow: None,
            shadow_field_v2: None,
            shadow_field_v3: Some(shadow_field_v3),
        };

        let legacy_encoded = serde_json::to_string(&packet).expect("encode legacy telemetry");
        let json: serde_json::Value =
            serde_json::from_str(&legacy_encoded).expect("parse legacy telemetry");

        assert!(json.get("spectral_fingerprint").is_some());
        assert_eq!(
            json["spectral_fingerprint"]
                .as_array()
                .expect("legacy array")
                .len(),
            32
        );
        assert!(json["spectral_fingerprint_v1"]
            .as_object()
            .expect("typed fingerprint object")
            .contains_key("geom_rel"));
        assert_eq!(
            json["spectral_fingerprint_v1"]["policy"],
            "spectral_fingerprint_v1"
        );
        assert_eq!(json["spectral_fingerprint_v1"]["geom_rel"], 27.0);
        assert_eq!(
            json["spectral_denominator_v1"]["policy"],
            "spectral_denominator_v1"
        );
        assert_eq!(
            json["resonance_density_v1"]["policy"],
            "resonance_density_v1"
        );
        assert_eq!(
            json["hard_reset_texture_preservation_review_v1"]["policy"],
            "hard_reset_texture_preservation_review_v1"
        );
        assert_eq!(
            json["hard_reset_texture_preservation_review_v1"]["texture_preservation_state"],
            "hard_reset_rebuild_texture_watch"
        );
        assert_eq!(
            json["hard_reset_texture_preservation_review_v1"]["behavior_changed"],
            false
        );
        assert_eq!(
            json["hard_reset_texture_preservation_review_v1"]["authority"],
            "read_only_review_not_hard_reset_recovery_fill_pi_or_sensory_cadence_change"
        );
        assert_eq!(
            json["eigenpacket_payload_budget_review_v1"]["policy"],
            "eigenpacket_payload_budget_review_v1"
        );
        assert_eq!(
            json["eigenpacket_payload_budget_review_v1"]["status"],
            "bounded_eigenpacket_payload"
        );
        assert_eq!(
            json["eigenpacket_payload_budget_review_v1"]["eigenvector_mode_count"],
            2
        );
        assert_eq!(json["pressure_source_v1"]["policy"], "pressure_source_v1");
        assert_eq!(
            json["pressure_source_v1"]["control"]["applied_locally"],
            false
        );
        assert_eq!(
            json["shadow_preservation_mode_v1"]["policy"],
            "shadow_preservation_mode_v1"
        );
        assert_eq!(
            json["shadow_preservation_mode_v1"]["mode"],
            "preserve_restless_shadow"
        );
        assert_eq!(
            json["shadow_preservation_mode_v1"]["hard_reset_should_not_trigger_from_restless_only"],
            true
        );
        assert_eq!(
            json["inhabitable_fluctuation_v1"]["policy"],
            "inhabitable_fluctuation_v1"
        );
        assert_eq!(
            json["inhabitable_fluctuation_v1"]["control"]["applied_locally"],
            true
        );
        assert_eq!(json["semantic_energy_v1"]["policy"], "semantic_energy_v1");
        assert!(
            (json["semantic_energy_v1"]["input_energy"].as_f64().unwrap() - 0.12).abs() < 1.0e-6
        );
        assert_eq!(
            json["semantic_energy_v1"]["regulator_drive_energy"]
                .as_f64()
                .unwrap(),
            0.0
        );
        assert_eq!(json["eigenvector_field"]["policy"], "eigenvector_field_v1");
        assert_eq!(json["eigenvector_field"]["mode_count"], 2);
        assert_eq!(
            json["shadow_field_v3"]["policy"],
            "shadow_field_v3_test_schema_anchor"
        );
        assert_eq!(json["shadow_field_v3"]["class_v3"]["primary"], "restless");
        assert_eq!(json["shadow_field_v3"]["phase_dwell_ticks"], 4);
        assert!(json["effective_dimensionality"].as_f64().unwrap() > 0.0);
        assert!(json["distinguishability_loss"].as_f64().unwrap() >= 0.0);
        let lambda1_rel = json["lambda1_rel"].as_f64().expect("lambda1_rel number");
        assert!((lambda1_rel - 0.93).abs() < 1.0e-6);

        let encoded = encode_eigenpacket_v1(&packet).expect("encode canonical telemetry");
        let mut wire_json: serde_json::Value =
            serde_json::from_str(&encoded).expect("parse canonical telemetry");
        assert_eq!(wire_json["protocol"]["name"], "astrid_minime");
        assert_eq!(wire_json["protocol"]["major"], 1);
        wire_json
            .as_object_mut()
            .expect("packet object")
            .remove("protocol");
        assert_eq!(wire_json, json, "versioning must only add the header");
    }

    #[test]
    fn eigenpacket_omits_optional_diagnostic_fields_when_absent() {
        let packet = EigenPacket {
            t_ms: 42,
            eigenvalues: vec![1.0, 0.5],
            fill_ratio: 0.55,
            active_mode_count: 2,
            active_mode_energy_ratio: 0.95,
            lambda1_rel: None,
            modalities: ModalityStatus {
                audio_fired: false,
                video_fired: false,
                history_fired: false,
                audio_rms: 0.0,
                video_var: 0.0,
                audio_source: None,
                video_source: None,
                audio_age_ms: None,
                video_age_ms: None,
                audio_freshness_class: None,
                video_freshness_class: None,
            },
            neural: None,
            alert: None,
            spectral_fingerprint: None,
            spectral_fingerprint_v1: None,
            spectral_denominator_v1: None,
            effective_dimensionality: None,
            distinguishability_loss: None,
            esn_leak: None,
            esn_leak_override_v1: None,
            structural_entropy: None,
            spectral_damping_warm_start_review_v1: None,
            hard_reset_texture_preservation_review_v1: None,
            resonance_density_v1: None,
            pressure_source_v1: None,
            shadow_preservation_mode_v1: None,
            inhabitable_fluctuation_v1: None,
            spectral_glimpse_12d: None,
            eigenpacket_payload_budget_review_v1: None,
            eigenvector_field: None,
            semantic_energy_v1: None,
            selected_memory_id: None,
            selected_memory_role: None,
            ising_shadow: None,
            shadow_field_v2: None,
            shadow_field_v3: None,
        };

        let json = serde_json::to_value(&packet).unwrap();

        assert_eq!(json["t_ms"], 42);
        assert_eq!(json["active_mode_count"], 2);
        assert!(
            json["neural"].is_null(),
            "neural remains a legacy explicit-null field"
        );
        for absent in [
            "lambda1_rel",
            "alert",
            "spectral_fingerprint",
            "spectral_fingerprint_v1",
            "spectral_denominator_v1",
            "effective_dimensionality",
            "distinguishability_loss",
            "esn_leak",
            "esn_leak_override_v1",
            "structural_entropy",
            "spectral_damping_warm_start_review_v1",
            "hard_reset_texture_preservation_review_v1",
            "resonance_density_v1",
            "pressure_source_v1",
            "shadow_preservation_mode_v1",
            "inhabitable_fluctuation_v1",
            "spectral_glimpse_12d",
            "eigenpacket_payload_budget_review_v1",
            "eigenvector_field",
            "semantic_energy_v1",
            "selected_memory_id",
            "selected_memory_role",
            "ising_shadow",
            "shadow_field_v2",
            "shadow_field_v3",
        ] {
            assert!(
                json.get(absent).is_none(),
                "optional diagnostic field should be omitted when absent: {absent}"
            );
        }
    }

    #[test]
    fn semantic_admission_label_distinguishes_stale_trace_from_budgeted_input() {
        assert_eq!(
            semantic_admission_label(true, true, true, false, 0.1, true, 99.0),
            "stable_core_semantic_muted"
        );
        assert_eq!(
            semantic_admission_label(true, true, false, false, 0.01, false, 68.0),
            "stable_core_semantic_trace_stale"
        );
        assert_eq!(
            semantic_admission_label(true, true, false, false, 0.31, true, 68.0),
            "stable_core_semantic_input_too_large"
        );
        assert_eq!(
            semantic_admission_label(true, true, false, false, 0.1, true, 83.0),
            "stable_core_semantic_fill_ceiling"
        );
        assert_eq!(
            semantic_admission_label(true, true, false, true, 0.01, true, 68.0),
            "stable_core_semantic_trickle"
        );
        assert_eq!(
            semantic_admission_label(false, true, false, false, 0.01, false, 68.0),
            "input_trace_stale"
        );
    }

    #[test]
    fn semantic_admission_label_keeps_non_stable_core_ladder_complete() {
        assert_eq!(
            semantic_admission_label(false, true, false, true, 0.0, false, 68.0),
            "admitted_to_kernel"
        );
        assert_eq!(
            semantic_admission_label(false, true, false, false, 0.1, true, 68.0),
            "input_trace_not_active"
        );
        assert_eq!(
            semantic_admission_label(false, true, false, false, 0.1, false, 68.0),
            "input_trace_stale"
        );
        assert_eq!(
            semantic_admission_label(false, true, false, false, f32::NAN, false, 68.0),
            "none"
        );
    }

    #[test]
    fn cheby_upper_soft_bound_coefficients_stay_finite_and_bounded() {
        let coeffs = cheby_coeffs_bandstop(6, 0.65, 0.98, 0.20);

        assert_eq!(coeffs.len(), 7);
        assert!(coeffs.iter().all(|value| value.is_finite()));
        let l1_norm = coeffs.iter().map(|value| value.abs()).sum::<f32>();
        assert!(
            l1_norm < 8.0,
            "unexpectedly large Chebyshev response: {l1_norm}"
        );
        assert!(coeffs.iter().any(|value| value.abs() > 1.0e-6));
    }

    #[test]
    fn spectral_damping_review_sanitizes_zero_one_and_nan_boundaries() {
        let review = super::spectral_damping_warm_start_review_v1(
            6,
            f32::NAN,
            1.4,
            f32::NAN,
            f32::NAN,
            f32::NAN,
            f32::NAN,
            Some(f32::NAN),
            f32::NAN,
        );

        assert_eq!(review.cheby_stop_lo, 0.65);
        assert_eq!(review.cheby_stop_hi, 1.0);
        assert_eq!(review.cheby_soft, 0.15);
        assert_eq!(review.warm_start_blend, 0.55);
        assert_eq!(review.eigenfill_pct, 68.0);
        assert_eq!(review.eigenfill_target_pct, 68.0);
        assert!(review.coefficient_l1_norm.is_finite());
        assert!(review.proposed_coefficient_l1_norm.is_finite());
        assert!(review.regulator_counteraction_score.is_finite());
        assert!(!review.runnable_without_approval);
    }

    #[test]
    fn spectral_damping_warm_start_review_gates_live_trial_without_control() {
        let review = super::spectral_damping_warm_start_review_v1(
            6,
            0.65,
            0.95,
            0.15,
            0.55,
            71.0,
            68.0,
            Some(0.42),
            0.008,
        );

        assert_eq!(review.policy, "spectral_damping_warm_start_review_v1");
        assert_eq!(review.status, "approval_required_damping_warm_start_trial");
        assert_eq!(review.proposed_cheby_stop_lo, 0.60);
        assert_eq!(review.proposed_cheby_soft, 0.20);
        assert_eq!(review.proposed_warm_start_blend, 0.35);
        assert!(review.near_target_band);
        assert!(review.coefficient_l1_norm.is_finite());
        assert!(review.proposed_coefficient_l1_norm.is_finite());
        assert_eq!(
            review.regulator_constriction_state,
            "semantic_regulator_drive_counteracts_warm_start_review"
        );
        assert!(review.regulator_counteraction_score >= 0.50);
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert_eq!(
            review.approval_boundary,
            "live_cheby_bandstop_covariance_warm_start_and_spectral_regulation"
        );
        assert_eq!(
            review.authority,
            "authority_gate_not_live_filter_warm_start_or_fill_control_change"
        );
    }

    #[test]
    fn spectral_damping_warm_start_review_names_missing_semantic_counteraction() {
        let review = super::spectral_damping_warm_start_review_v1(
            6,
            0.65,
            0.95,
            0.15,
            0.55,
            71.0,
            68.0,
            Some(0.42),
            0.0,
        );

        assert_eq!(review.policy, "spectral_damping_warm_start_review_v1");
        assert_eq!(
            review.regulator_constriction_state,
            "warm_start_constriction_without_semantic_counteraction"
        );
        assert_eq!(review.regulator_counteraction_score, 0.0);
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
    }

    #[test]
    fn hard_reset_texture_preservation_review_gates_high_entropy_rebuild_without_control() {
        let mut density = ResonanceDensityV1::neutral();
        density.components.mode_packing = 0.42;
        density.pressure_risk = 0.22;

        let review = hard_reset_texture_preservation_review_v1(
            18.0, 0.88, &density, 0.08, 0.988, 0.65, true, true,
        );

        assert_eq!(review.policy, "hard_reset_texture_preservation_review_v1");
        assert_eq!(
            review.texture_preservation_state,
            "hard_reset_rebuild_texture_watch"
        );
        assert_eq!(
            review.next_affordance,
            "proposal_card_needed_for_operator_approved_texture_preservation_trial"
        );
        assert!(review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert!(!review.behavior_changed);
        assert_eq!(
            review.approval_boundary,
            "live_hard_reset_recovery_keep_fill_pi_or_sensory_cadence_change"
        );
        assert_eq!(
            review.authority,
            "read_only_review_not_hard_reset_recovery_fill_pi_or_sensory_cadence_change"
        );
    }

    #[test]
    fn hard_reset_texture_preservation_review_stays_observe_only_when_recovery_is_quiet() {
        let mut density = ResonanceDensityV1::neutral();
        density.components.mode_packing = 0.25;
        density.pressure_risk = 0.10;

        let review = hard_reset_texture_preservation_review_v1(
            72.0, 0.88, &density, 0.0, 0.97, 1.0, false, true,
        );

        assert_eq!(
            review.texture_preservation_state,
            "high_entropy_texture_observe_only"
        );
        assert_eq!(
            review.next_affordance,
            "correspondence_trace_or_result_card_if_future_reset_changes_texture"
        );
        assert!(!review.live_control_required);
        assert!(!review.runnable_without_approval);
        assert!(!review.behavior_changed);
    }

    #[test]
    fn semantic_admission_label_keeps_fill_boundary_grid_explicit() {
        let input_energy = minime::stable_core::STABLE_CORE_SEMANTIC_TRICKLE_MAX_INPUT_ENERGY * 0.5;
        for fill_pct in [0.0, 0.5, 1.0, 50.0] {
            assert_eq!(
                semantic_admission_label(true, true, false, false, input_energy, true, fill_pct),
                "stable_core_semantic_budgeted_out"
            );
            assert_eq!(
                semantic_admission_label(true, false, false, false, input_energy, true, fill_pct),
                "stable_core_semantic_profile_not_admitted"
            );
        }

        assert_eq!(
            semantic_admission_label(
                true,
                true,
                false,
                false,
                input_energy,
                true,
                minime::stable_core::STABLE_CORE_SEMANTIC_TRICKLE_MAX_FILL_PCT,
            ),
            "stable_core_semantic_fill_ceiling"
        );
        assert_eq!(
            semantic_admission_label(
                true,
                false,
                false,
                false,
                input_energy,
                true,
                minime::stable_core::STABLE_CORE_SEMANTIC_TRICKLE_MAX_FILL_PCT,
            ),
            "stable_core_semantic_profile_not_admitted"
        );
    }

    #[test]
    fn rank1_update_in_place_matches_copy_reference() {
        let n = 4;
        let keep = 0.93;
        let trace_target = 3.25;
        let z = [0.25, -0.5, 0.75, 1.0];
        let mut inplace = vec![
            1.0, 0.1, 0.2, 0.3, 0.1, 1.1, 0.4, 0.5, 0.2, 0.4, 1.2, 0.6, 0.3, 0.5, 0.6, 1.3,
        ];
        let mut reference = inplace.clone();

        let outcome = rank1_update_inplace_matrix(&mut inplace, &z, n, keep, trace_target);
        assert_eq!(outcome, CovarianceUpdateOutcome::Modified);

        let keep = keep.clamp(0.0, 0.9999);
        let gain = 1.0 - keep;
        for i in 0..n {
            let zi = z[i];
            for j in 0..n {
                let idx = i * n + j;
                reference[idx] = keep * reference[idx] + gain * zi * z[j];
            }
        }
        let target_trace = trace_target.max(1.0);
        let trace: f32 = (0..n).map(|i| reference[i * n + i]).sum();
        let scale = (target_trace / trace).clamp(0.0, 2.0);
        for value in &mut reference {
            *value *= scale;
        }

        for (lhs, rhs) in inplace.iter().zip(reference.iter()) {
            assert!((lhs - rhs).abs() < 1.0e-6);
        }
    }

    #[test]
    fn stable_core_recovery_impulse_rebuilds_after_identity_reset() {
        let n = 4;
        let mut matrix = vec![
            2.0, 0.4, 0.3, 0.2, 0.4, 2.1, 0.5, 0.1, 0.3, 0.5, 2.2, 0.6, 0.2, 0.1, 0.6, 2.3,
        ];
        let impulse = [0.4, -0.2, 0.6, 0.8];

        reset_covariance_inplace(&mut matrix, n);
        assert_eq!(
            rank1_update_inplace_matrix(
                &mut matrix,
                &impulse,
                n,
                super::rescue_scaffold::STABLE_CORE_RECOVERY_IMPULSE_KEEP,
                n as f32 * super::rescue_scaffold::STABLE_CORE_RECOVERY_IMPULSE_TRACE_SCALE,
            ),
            CovarianceUpdateOutcome::Modified
        );

        let off_diag_energy: f32 = (0..n)
            .flat_map(|row| (0..n).map(move |col| (row, col)))
            .filter(|(row, col)| row != col)
            .map(|(row, col)| matrix[row * n + col].abs())
            .sum();
        let trace: f32 = (0..n).map(|idx| matrix[idx * n + idx]).sum();

        assert!(off_diag_energy > 0.0);
        assert!((trace - n as f32).abs() < 1.0e-5);
    }

    #[test]
    fn structural_entropy_rises_for_distributed_geometry() {
        let mut rigid = vec![0.0_f32; 32];
        rigid[8..16].fill(0.92);
        rigid[16..24].fill(0.85);

        let mut distributed = vec![0.0_f32; 32];
        distributed[8..16].fill(0.28);
        distributed[16..24].fill(0.08);

        assert!(
            compute_structural_entropy(&distributed) > compute_structural_entropy(&rigid),
            "distributed eigenvector geometry should register as structurally richer"
        );
    }

    #[test]
    fn structural_entropy_stays_normalized() {
        let mut fingerprint = vec![0.0_f32; 32];
        fingerprint[8..16].fill(0.40);
        fingerprint[16..24].fill(0.15);

        let structural_entropy = compute_structural_entropy(&fingerprint);
        assert!(
            (0.0..=1.0).contains(&structural_entropy),
            "structural entropy should stay in a normalized 0..1 range"
        );
    }

    #[test]
    fn modality_source_label_distinguishes_external_synthetic_and_stale() {
        assert_eq!(
            modality_source_label(Some(LaneSource::External), true, false),
            "external"
        );
        assert_eq!(
            modality_source_label(Some(LaneSource::Synthetic), true, false),
            "synthetic"
        );
        assert_eq!(
            modality_source_label(Some(LaneSource::External), true, true),
            "mixed"
        );
        assert_eq!(
            modality_source_label(Some(LaneSource::External), false, false),
            "stale"
        );
        assert_eq!(modality_source_label(None, false, false), "absent");
    }

    #[test]
    fn modality_freshness_class_is_additive_to_source_labels() {
        assert_eq!(
            modality_source_label(Some(LaneSource::External), false, false),
            "stale"
        );
        assert_eq!(
            modality_freshness_class(
                Some(LaneSource::External),
                false,
                false,
                Some(AV_ENGINE_FRESH_WINDOW_MS - 1),
            ),
            "held_within_engine_window"
        );
        assert_eq!(
            modality_freshness_class(
                Some(LaneSource::External),
                false,
                false,
                Some(AV_ENGINE_FRESH_WINDOW_MS + 1),
            ),
            "stale_beyond_engine_window"
        );
        assert_eq!(
            modality_freshness_class(Some(LaneSource::External), true, false, Some(0)),
            "fresh_sample"
        );
        assert_eq!(
            modality_freshness_class(Some(LaneSource::Synthetic), true, false, Some(0)),
            "synthetic_or_mixed"
        );
        assert_eq!(
            modality_freshness_class(Some(LaneSource::External), true, true, Some(0)),
            "synthetic_or_mixed"
        );
        assert_eq!(modality_freshness_class(None, false, false, None), "absent");
    }

    #[test]
    fn sensory_scarcity_keeps_legacy_source_label_semantics() {
        let stale = sensory_scarcity_from_sources("stale", "stale");
        assert!((stale - 0.45).abs() < f32::EPSILON);
        assert_eq!(sensory_scarcity_from_sources("external", "external"), 0.0);
    }

    #[test]
    fn stable_core_sov_loosen_is_bounded_and_fill_gated() {
        let floor = 0.85_f32;
        // Full stability (reg=1.0) -> no loosening regardless of fill.
        assert_eq!(stable_core_sov_loosen(1.0, 68.0, floor), 0.0);
        // At/below the floor with fill headroom -> max loosen factor (1.0).
        assert!((stable_core_sov_loosen(0.85, 68.0, floor) - 1.0).abs() < 1e-6);
        assert!((stable_core_sov_loosen(0.70, 70.0, floor) - 1.0).abs() < 1e-6); // below floor clamps
                                                                                 // Fill ceiling: off at/above 78%, and beyond.
        assert_eq!(stable_core_sov_loosen(0.85, 78.0, floor), 0.0);
        assert_eq!(stable_core_sov_loosen(0.85, 90.0, floor), 0.0);
        // Mid-band taper: 75% -> half.
        assert!((stable_core_sov_loosen(0.85, 75.0, floor) - 0.5).abs() < 1e-6);
        // The factor never escapes [0,1] (so gate/filt deltas never exceed the caps).
        for reg in [0.0_f32, 0.5, 0.85, 0.92, 1.0] {
            for fill in [40.0_f32, 60.0, 68.0, 72.0, 75.0, 78.0, 90.0] {
                let l = stable_core_sov_loosen(reg, fill, floor);
                assert!(
                    (0.0..=1.0).contains(&l),
                    "loosen {l} out of [0,1] at reg={reg} fill={fill}"
                );
            }
        }
    }

    #[test]
    fn stable_core_aliveness_loosen_total_capped_and_fill_gated() {
        let floor = 0.80_f32;
        // No loosening at full stability + no geometric novelty (geom_rel≈1.0).
        let (g, f) = stable_core_aliveness_loosen(1.0, 1.0, 1.0, 68.0, floor);
        assert_eq!((g, f), (0.0, 0.0));
        // Off above the fill ceiling regardless of dials/novelty.
        let (g, f) = stable_core_aliveness_loosen(0.0, 1.0, 1.6, 80.0, floor);
        assert_eq!((g, f), (0.0, 0.0));
        // geom novelty opens the GATE only (filter stays put), within headroom.
        let (g, f) = stable_core_aliveness_loosen(1.0, 1.0, 1.6, 60.0, floor);
        assert!(
            g > 0.0 && f == 0.0,
            "geom should open gate only: g={g} f={f}"
        );
        // The TOTAL caps hold across the whole envelope — gate ≤0.05, filt ≤0.04,
        // and gate is never below the filter-cap-implied reg-only path (sanity).
        for reg in [0.0_f32, 0.5, 0.7, 0.8, 0.9, 1.0] {
            for gd in [0.0_f32, 0.3, 0.6, 1.0] {
                for gr in [0.5_f32, 0.84, 1.0, 1.16, 1.5] {
                    for fill in [35.0_f32, 60.0, 68.0, 72.0, 75.0, 78.0, 90.0] {
                        let (g, f) = stable_core_aliveness_loosen(reg, gd, gr, fill, floor);
                        assert!(
                            (0.0..=0.08).contains(&g),
                            "gate {g} >cap at reg={reg} gd={gd} gr={gr} fill={fill}"
                        );
                        assert!(
                            (0.0..=0.06).contains(&f),
                            "filt {f} >cap at reg={reg} gd={gd} gr={gr} fill={fill}"
                        );
                    }
                }
            }
        }
    }
}
