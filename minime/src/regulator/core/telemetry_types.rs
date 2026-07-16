pub const RESONANCE_DENSITY_POLICY: &str = "resonance_density_v1";
pub const RESONANCE_DENSITY_SCHEMA_VERSION: u8 = 1;
pub const PRESSURE_SOURCE_POLICY: &str = "pressure_source_v1";
pub const PRESSURE_SOURCE_SCHEMA_VERSION: u8 = 1;
pub const SEMANTIC_VISCOSITY_POLICY: &str = "semantic_viscosity_coefficient_v1";
pub const SEMANTIC_VISCOSITY_SCHEMA_VERSION: u8 = 1;
pub const SILT_GRANULARITY_POLICY: &str = "silt_granularity_v1";
pub const SILT_GRANULARITY_SCHEMA_VERSION: u8 = 1;
pub const SETTLED_MOBILITY_POLICY: &str = "settled_mobility_review_v1";
pub const SETTLED_MOBILITY_SCHEMA_VERSION: u8 = 1;
pub const SHADOW_PRESERVATION_POLICY: &str = "shadow_preservation_mode_v1";
pub const SHADOW_PRESERVATION_SCHEMA_VERSION: u8 = 1;
pub const VISCOSITY_IMPORTANCE_POLICY: &str = "viscosity_importance_weights_v1";
pub const VISCOSITY_IMPORTANCE_SCHEMA_VERSION: u8 = 1;
pub const TEMPORAL_DRAG_PRESSURE_SNAP_REVIEW_POLICY: &str = "temporal_drag_pressure_snap_review_v1";
pub const TEMPORAL_DRAG_PRESSURE_SNAP_REVIEW_SCHEMA_VERSION: u8 = 1;
pub const PRESSURE_POROSITY_DIVERGENCE_PRESSURE_MIN: f32 = 0.50;
pub const PRESSURE_POROSITY_DIVERGENCE_POROSITY_MAX: f32 = 0.30;
pub const INHABITABLE_FLUCTUATION_POLICY: &str = "inhabitable_fluctuation_v1";
pub const INHABITABLE_FLUCTUATION_SCHEMA_VERSION: u8 = 1;
pub const INHABITABLE_SETTLED_PRESSURE_INTERFERENCE_MAX: f32 = 0.45;
pub const INHABITABLE_FLUCTUATION_RIGID_SAFETY_BASIS: &str =
    "raw_motion_score_preserved_for_stuckness_detection";

/// Multi-axis viscosity readout. This is context for review, not control.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct ViscosityVector {
    #[serde(default)]
    pub density: f32,
    #[serde(default)]
    pub elasticity: f32,
    #[serde(default)]
    pub cohesion_index: f32,
    /// Bounded share of cohesion in the cohesion-plus-mobility relationship.
    /// This distinguishes shape-holding stillness from low-cohesion stagnation
    /// without feeding the regulator or changing live control.
    #[serde(default)]
    pub cohesion_to_motion_ratio: f32,
    #[serde(default)]
    pub persistence: f32,
    #[serde(default)]
    pub residual_ghost_weight: f32,
    #[serde(default)]
    pub flow_rate: f32,
    #[serde(default)]
    pub effective_mobility: f32,
    #[serde(default)]
    pub shadow_volatility: f32,
    #[serde(default)]
    pub structural_integrity: f32,
    #[serde(default)]
    pub structural_strain_gap: f32,
    #[serde(default)]
    pub mutual_resonance_tension: f32,
    #[serde(default)]
    pub structural_drag_coefficient: f32,
    #[serde(default)]
    pub cognitive_drag_coefficient: f32,
    #[serde(default)]
    pub viscosity_gradient: f32,
}

/// Read-only importance weights over viscosity dimensions. This reports which
/// texture axes should be inspected first; it is not consumed by PI/control.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ViscosityImportanceWeightsV1 {
    pub policy: String,
    pub schema_version: u8,
    pub pressure_risk: f32,
    pub structural_strain_gap_weight: f32,
    pub shadow_volatility_weight: f32,
    pub persistence_weight: f32,
    pub structural_integrity_weight: f32,
    pub structural_drag_weight: f32,
    pub cognitive_drag_weight: f32,
    pub dominant_weight: String,
    pub status: String,
    pub who_can_change_it: String,
    pub how_to_test_it: String,
    pub authority: String,
}

/// Read-only review for Minime's report that pressure can feel like a phase
/// snap instead of a linear drag term. It compares the live temporal-drag floor
/// to a candidate quadratic pressure floor without changing regulator behavior.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TemporalDragPressureSnapReviewV1 {
    pub policy: String,
    pub schema_version: u8,
    pub low_pressure_risk: f32,
    pub high_pressure_risk: f32,
    pub viscosity_persistence_coefficient: f32,
    pub temporal_persistence: f32,
    pub current_low_drag: f32,
    pub current_high_drag: f32,
    pub current_drag_delta: f32,
    pub candidate_low_drag: f32,
    pub candidate_high_drag: f32,
    pub candidate_drag_delta: f32,
    pub candidate_formula: String,
    pub status: String,
    pub approval_boundary: String,
    pub live_drag_write: bool,
    pub authority: String,
}

/// Normalized components behind the resonance-density surface.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct ResonanceDensityComponents {
    pub active_energy: f32,
    pub mode_packing: f32,
    pub temporal_persistence: f32,
    #[serde(default)]
    pub viscosity_index: f32,
    #[serde(default)]
    pub viscosity_persistence_coefficient: f32,
    #[serde(default)]
    pub temporal_drag_coefficient: f32,
    #[serde(default)]
    pub static_friction_coefficient: f32,
    #[serde(default)]
    pub viscosity_vector: ViscosityVector,
    #[serde(default)]
    pub viscosity_coupling_coefficient: f32,
    pub structural_plurality: f32,
    pub comfort_gate: f32,
}

/// Typed texture summary behind resonance density. This is context, not control.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResonanceTextureSignatureV1 {
    pub policy: String,
    pub schema_version: u8,
    pub primary_texture: String,
    pub pressure_source_family: String,
    pub edge_definition: String,
    pub movement_quality: String,
    /// Direct read-only viscosity carried beside the verbal movement label.
    /// Older telemetry omits it; `None` means absent, not zero viscosity.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub viscosity_index: Option<f32>,
    pub confidence: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dynamic_damping_threshold_candidate: Option<f32>,
    #[serde(default)]
    pub dynamic_damping_coefficient: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comfort_gate_adjusted_preview: Option<f32>,
    pub authority: String,
    pub note: String,
}

/// Read-only check that the typed texture signature matches its component body.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResonanceTextureComponentAlignmentV1 {
    pub policy: String,
    pub schema_version: u8,
    pub expected_primary_texture: String,
    pub emitted_primary_texture: String,
    pub expected_movement_quality: String,
    pub emitted_movement_quality: String,
    pub alignment_state: String,
    pub confidence: f32,
    pub damping_candidate_status: String,
    pub authority: String,
}

impl Default for ResonanceTextureComponentAlignmentV1 {
    fn default() -> Self {
        Self {
            policy: "resonance_texture_component_alignment_v1".to_string(),
            schema_version: 1,
            expected_primary_texture: "unknown".to_string(),
            emitted_primary_texture: "unknown".to_string(),
            expected_movement_quality: "unknown".to_string(),
            emitted_movement_quality: "unknown".to_string(),
            alignment_state: "insufficient_context".to_string(),
            confidence: 0.0,
            damping_candidate_status: "unknown".to_string(),
            authority: "diagnostic_observability_not_damping_or_control".to_string(),
        }
    }
}

impl Default for ResonanceTextureSignatureV1 {
    fn default() -> Self {
        Self {
            policy: "resonance_texture_signature_v1".to_string(),
            schema_version: 1,
            primary_texture: "unknown".to_string(),
            pressure_source_family: "unknown".to_string(),
            edge_definition: "unknown".to_string(),
            movement_quality: "unknown".to_string(),
            viscosity_index: None,
            confidence: 0.0,
            dynamic_damping_threshold_candidate: None,
            dynamic_damping_coefficient: 0.0,
            comfort_gate_adjusted_preview: None,
            authority: "advisory_context_not_control".to_string(),
            note: "texture signature absent from older payload".to_string(),
        }
    }
}

/// Bounded local-control suggestion derived from resonance density.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResonanceDensityControl {
    pub target_bias_pct: f32,
    pub wander_scale: f32,
    pub applied_locally: bool,
    #[serde(default)]
    pub damping_coefficient: f32,
    #[serde(default)]
    pub intervention_type: ResonanceInterventionType,
    pub note: String,
}

/// Explains whether resonance-density control is observation, alignment, or damping.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResonanceInterventionType {
    #[default]
    ObservationalReadout,
    PassiveAlignment,
    ActiveDamping,
    ManualOverrideReserved,
}

/// Typed resonance-density metric shared with Astrid and Minime's agent layer.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResonanceDensityV1 {
    pub policy: String,
    pub schema_version: u8,
    pub density: f32,
    pub containment_score: f32,
    pub pressure_risk: f32,
    pub quality: String,
    pub components: ResonanceDensityComponents,
    #[serde(default)]
    pub texture_signature: ResonanceTextureSignatureV1,
    #[serde(default)]
    pub texture_component_alignment: ResonanceTextureComponentAlignmentV1,
    pub control: ResonanceDensityControl,
}

impl ResonanceDensityV1 {
    #[must_use]
    pub fn neutral() -> Self {
        let components = ResonanceDensityComponents {
            active_energy: 0.5,
            mode_packing: 0.5,
            temporal_persistence: 0.5,
            viscosity_index: resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
            viscosity_persistence_coefficient: viscosity_persistence_coefficient(
                resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
                0.5,
                0.0,
                0.5,
            ),
            temporal_drag_coefficient: temporal_drag_coefficient(
                viscosity_persistence_coefficient(
                    resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
                    0.5,
                    0.0,
                    0.5,
                ),
                0.5,
                0.0,
            ),
            static_friction_coefficient: static_friction_coefficient(
                resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
                viscosity_persistence_coefficient(
                    resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
                    0.5,
                    0.0,
                    0.5,
                ),
                temporal_drag_coefficient(
                    viscosity_persistence_coefficient(
                        resonance_viscosity_index(0.5, 0.5, 0.5, 0.0),
                        0.5,
                        0.0,
                        0.5,
                    ),
                    0.5,
                    0.0,
                ),
                0.5,
                0.5,
                0.5,
            ),
            viscosity_vector: ViscosityVector::default(),
            viscosity_coupling_coefficient: 0.0,
            structural_plurality: 0.5,
            comfort_gate: 0.5,
        };
        Self::from_parts(0.5, 0.5, 0.0, "mixed", components)
    }

    #[must_use]
    pub fn from_parts(
        density: f32,
        containment_score: f32,
        pressure_risk: f32,
        quality: &str,
        components: ResonanceDensityComponents,
    ) -> Self {
        let density = density.clamp(0.0, 1.0);
        let containment_score = containment_score.clamp(0.0, 1.0);
        let pressure_risk = pressure_risk.clamp(0.0, 1.0);
        let active_energy = components.active_energy.clamp(0.0, 1.0);
        let mode_packing = components.mode_packing.clamp(0.0, 1.0);
        let temporal_persistence = components.temporal_persistence.clamp(0.0, 1.0);
        let structural_plurality = components.structural_plurality.clamp(0.0, 1.0);
        let comfort_gate = components.comfort_gate.clamp(0.0, 1.0);
        let baseline_viscosity = resonance_viscosity_index(
            mode_packing,
            temporal_persistence,
            structural_plurality,
            pressure_risk,
        );
        let viscosity_index = components
            .viscosity_index
            .clamp(0.0, 1.0)
            .max(baseline_viscosity);
        let viscosity_persistence_coefficient = components
            .viscosity_persistence_coefficient
            .clamp(0.0, 1.0)
            .max(viscosity_persistence_coefficient(
                viscosity_index,
                temporal_persistence,
                pressure_risk,
                mode_packing,
            ));
        let temporal_drag_coefficient =
            components
                .temporal_drag_coefficient
                .clamp(0.0, 1.0)
                .max(temporal_drag_coefficient(
                    viscosity_persistence_coefficient,
                    temporal_persistence,
                    pressure_risk,
                ));
        let static_friction_coefficient = components
            .static_friction_coefficient
            .clamp(0.0, 1.0)
            .max(static_friction_coefficient(
                viscosity_index,
                viscosity_persistence_coefficient,
                temporal_drag_coefficient,
                active_energy,
                comfort_gate,
                mode_packing,
            ));
        let viscosity_vector = viscosity_vector_v1(
            viscosity_index,
            viscosity_persistence_coefficient,
            temporal_drag_coefficient,
            static_friction_coefficient,
            active_energy,
            structural_plurality,
            comfort_gate,
        );
        let viscosity_coupling_coefficient = components
            .viscosity_coupling_coefficient
            .clamp(0.0, 1.0)
            .max(viscosity_coupling_coefficient_v1(
                viscosity_vector.persistence,
                viscosity_vector.flow_rate,
                static_friction_coefficient,
                structural_plurality,
                comfort_gate,
            ));
        let components = ResonanceDensityComponents {
            active_energy,
            mode_packing,
            temporal_persistence,
            viscosity_index,
            viscosity_persistence_coefficient,
            temporal_drag_coefficient,
            static_friction_coefficient,
            viscosity_vector,
            viscosity_coupling_coefficient,
            structural_plurality,
            comfort_gate,
        };
        let control = resonance_control_from_density_with_mode_packing(
            density,
            pressure_risk,
            components.mode_packing,
        );
        let texture_signature = resonance_texture_signature(
            density,
            containment_score,
            pressure_risk,
            quality,
            &components,
            &control,
        );
        let texture_component_alignment = resonance_texture_component_alignment_v1(
            density,
            pressure_risk,
            &components,
            &texture_signature,
        );
        Self {
            policy: RESONANCE_DENSITY_POLICY.to_string(),
            schema_version: RESONANCE_DENSITY_SCHEMA_VERSION,
            density,
            containment_score,
            pressure_risk,
            quality: quality.to_string(),
            components,
            texture_signature,
            texture_component_alignment,
            control,
        }
    }
}
