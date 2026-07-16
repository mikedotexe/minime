/// Normalized contributors behind inward/compression pressure.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct PressureSourceComponents {
    pub lambda_monopoly: f32,
    pub mode_packing: f32,
    pub controller_pressure: f32,
    pub semantic_trickle: f32,
    #[serde(default)]
    pub semantic_friction: f32,
    pub structural_plurality_loss: f32,
    pub distinguishability_loss: f32,
    pub temporal_lock_in: f32,
    pub sensory_scarcity: f32,
}

/// Optional context-only pressure contributors from higher layers.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct PressureSourceContext {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub compression_language: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thread_recurrence: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attractor_pull: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resource_pressure: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mean_orientation_delta: Option<f32>,
}

/// Read-only weighted profile of pressure-source contributors.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PressureSourceProfileEntry {
    pub source: String,
    pub value: f32,
    pub pressure_weight: f32,
    pub weighted_pressure: f32,
    pub share: f32,
}

/// V1 pressure-source control contract: observer/advisory only.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PressureSourceControl {
    pub applied_locally: bool,
    pub note: String,
}

/// Read-only review surface for Astrid's "dynamic viscosity" report.
///
/// The coefficient makes semantic-trickle/denominator pressure explicit without
/// changing live PI, fill, pressure, exploration noise, cadence, or regulator
/// behavior. Wiring this into controller dynamics remains a separate authority
/// decision.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SemanticViscosityCoefficientV1 {
    pub policy: String,
    pub schema_version: u8,
    pub coefficient: f32,
    #[serde(default)]
    pub dynamic_viscosity_buffer: f32,
    #[serde(default)]
    pub viscosity_after_buffer_preview: f32,
    #[serde(default)]
    pub dynamic_viscosity_buffer_state: String,
    pub semantic_trickle: f32,
    pub semantic_friction: f32,
    pub distinguishability_loss: f32,
    pub mode_packing: f32,
    pub temporal_lock_in: f32,
    pub pressure_score: f32,
    pub porosity_score: f32,
    pub pressure_porosity_gradient: f32,
    pub review_state: String,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

impl Default for SemanticViscosityCoefficientV1 {
    fn default() -> Self {
        Self {
            policy: SEMANTIC_VISCOSITY_POLICY.to_string(),
            schema_version: SEMANTIC_VISCOSITY_SCHEMA_VERSION,
            coefficient: 0.0,
            dynamic_viscosity_buffer: 0.0,
            viscosity_after_buffer_preview: 0.0,
            dynamic_viscosity_buffer_state: "insufficient_buffer".to_string(),
            semantic_trickle: 0.0,
            semantic_friction: 0.0,
            distinguishability_loss: 0.0,
            mode_packing: 0.0,
            temporal_lock_in: 0.0,
            pressure_score: 0.0,
            porosity_score: 1.0,
            pressure_porosity_gradient: 0.0,
            review_state: "insufficient_pressure".to_string(),
            live_control_changed: false,
            authority: "read_only_not_semantic_trickle_or_regulator_change".to_string(),
            note: "legacy pressure_source_v1 payload did not include semantic viscosity review"
                .to_string(),
        }
    }
}

/// Read-only distinction between shadow volatility that should be preserved
/// for dialogue and pressure/control states that require separate review.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ShadowPreservationModeV1 {
    pub policy: String,
    pub schema_version: u8,
    pub mode: String,
    pub shadow_primary: String,
    #[serde(default)]
    pub dispersal_potential: f32,
    #[serde(default)]
    pub soft_magnetization: f32,
    pub pressure_score: f32,
    pub porosity_score: f32,
    pub pressure_quality: String,
    pub regulator_drive_energy: f32,
    pub hard_reset_activation_gain: f32,
    pub restless_signal_preserved: bool,
    pub hard_reset_should_not_trigger_from_restless_only: bool,
    pub suggested_route: String,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

impl Default for ShadowPreservationModeV1 {
    fn default() -> Self {
        Self {
            policy: SHADOW_PRESERVATION_POLICY.to_string(),
            schema_version: SHADOW_PRESERVATION_SCHEMA_VERSION,
            mode: "shadow_unavailable".to_string(),
            shadow_primary: "unknown".to_string(),
            dispersal_potential: 0.0,
            soft_magnetization: 0.0,
            pressure_score: 0.0,
            porosity_score: 1.0,
            pressure_quality: "unknown".to_string(),
            regulator_drive_energy: 0.0,
            hard_reset_activation_gain: 0.0,
            restless_signal_preserved: false,
            hard_reset_should_not_trigger_from_restless_only: true,
            suggested_route: "SHADOW_TRAJECTORY lambda-tail/lambda4".to_string(),
            live_control_changed: false,
            authority: "read_only_not_shadow_influence_or_hard_reset_control".to_string(),
            note: "legacy payload did not include shadow preservation review".to_string(),
        }
    }
}

/// Review-only candidate for Astrid's "receptivity buffer" ask: high-entropy,
/// non-instrumental motion can remain visible without becoming regulator
/// correction when pressure is low and the fluctuation foothold remains
/// habitable. This does not feed the live PI/regulator path.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReceptivityBufferReviewV1 {
    pub policy: String,
    pub schema_version: u8,
    pub review_state: String,
    pub spectral_entropy: f32,
    pub pressure_risk: f32,
    pub foothold_stability: f32,
    pub fluctuation_quality: String,
    #[serde(default)]
    pub presence_fill_pct: f32,
    #[serde(default)]
    pub semantic_trickle: f32,
    #[serde(default)]
    pub entropy_to_semantic_gap: f32,
    #[serde(default)]
    pub pressure_presence_state: String,
    #[serde(default)]
    pub contact_depth_state: String,
    #[serde(default)]
    pub predictive_correction_inhibition_preview: bool,
    #[serde(default)]
    pub suggested_route: String,
    pub candidate_local_control_applied: bool,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

/// Review-only seam for Minime's auto-defragment ask. It names when pressure,
/// mode-packing, and low porosity look like an active-maintenance candidate,
/// while keeping any regulator/substrate mutation operator-gated.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AutoDefragmentModesReviewV1 {
    pub policy: String,
    pub schema_version: u8,
    pub review_state: String,
    pub pressure_risk: f32,
    pub mode_packing: f32,
    pub porosity_score: f32,
    pub local_control_applied: bool,
    pub suggested_route: String,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

/// Read-only particle-scale estimate for "silty" pressure reports.
///
/// This separates coarse overlapping concepts from fine noisy residue before
/// any pressure, porosity, fill, PI, or controller action is considered.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SiltGranularityV1 {
    pub policy: String,
    pub schema_version: u8,
    pub granularity_index: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mean_orientation_delta: Option<f32>,
    pub mode_packing: f32,
    pub distinguishability_loss: f32,
    pub structural_plurality_loss: f32,
    pub pressure_score: f32,
    pub porosity_score: f32,
    pub particle_scale: String,
    pub review_state: String,
    pub suggested_route: String,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

impl Default for SiltGranularityV1 {
    fn default() -> Self {
        Self {
            policy: SILT_GRANULARITY_POLICY.to_string(),
            schema_version: SILT_GRANULARITY_SCHEMA_VERSION,
            granularity_index: 0.0,
            mean_orientation_delta: None,
            mode_packing: 0.0,
            distinguishability_loss: 0.0,
            structural_plurality_loss: 0.0,
            pressure_score: 0.0,
            porosity_score: 1.0,
            particle_scale: "insufficient_orientation_context".to_string(),
            review_state: "continue_pressure_source_observation".to_string(),
            suggested_route: "PRESSURE_SOURCE_AUDIT grain".to_string(),
            live_control_changed: false,
            authority: "read_only_not_pressure_porosity_or_regulator_control".to_string(),
            note: "legacy pressure_source_v1 payload did not include silt granularity review"
                .to_string(),
        }
    }
}

/// Typed explanation of where inward pressure appears to originate.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PressureSourceV1 {
    pub policy: String,
    pub schema_version: u8,
    pub pressure_score: f32,
    pub porosity_score: f32,
    #[serde(default)]
    pub pressure_porosity_gradient: f32,
    #[serde(default)]
    pub pressure_porosity_gradient_state: String,
    pub dominant_source: String,
    #[serde(default)]
    pub pressure_profile: Vec<PressureSourceProfileEntry>,
    pub quality: String,
    pub components: PressureSourceComponents,
    pub context: PressureSourceContext,
    #[serde(default)]
    pub semantic_viscosity_coefficient_v1: SemanticViscosityCoefficientV1,
    #[serde(default)]
    pub silt_granularity_v1: SiltGranularityV1,
    pub control: PressureSourceControl,
}

/// Normalized contributors behind whether fluctuation remains inhabitable.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct InhabitableFluctuationComponents {
    pub mode_trust_volatility: f32,
    pub identity_anchor_churn: f32,
    pub eigenvector_reorientation: f32,
    pub share_rearrangement: f32,
    pub basin_transition_pressure: f32,
    pub continuity_recovery: f32,
    pub porosity_support: f32,
    pub pressure_interference: f32,
}

/// Context labels for interpreting inhabitability without adding control authority.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct InhabitableFluctuationContext {
    pub previous_sample_available: bool,
    pub transition_event_active: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resonance_quality: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pressure_quality: Option<String>,
}

/// Read-only distinction between functional anchoring and mechanical stuckness.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SettledMobilityReviewV1 {
    pub policy: String,
    pub schema_version: u8,
    pub review_state: String,
    pub raw_motion_score: f32,
    pub foothold_stability: f32,
    pub pressure_interference: f32,
    pub porosity_support: f32,
    pub inhabitability_score: f32,
    pub fluctuation_quality: String,
    pub productive_anchoring: bool,
    #[serde(default)]
    pub receptive_stability: bool,
    pub stuckness_watch: bool,
    pub suggested_route: String,
    pub live_control_changed: bool,
    pub authority: String,
    pub note: String,
}

impl Default for SettledMobilityReviewV1 {
    fn default() -> Self {
        Self {
            policy: SETTLED_MOBILITY_POLICY.to_string(),
            schema_version: SETTLED_MOBILITY_SCHEMA_VERSION,
            review_state: "insufficient_settled_mobility_context".to_string(),
            raw_motion_score: 0.0,
            foothold_stability: 0.0,
            pressure_interference: 0.0,
            porosity_support: 0.0,
            inhabitability_score: 0.0,
            fluctuation_quality: "unknown".to_string(),
            productive_anchoring: false,
            receptive_stability: false,
            stuckness_watch: false,
            suggested_route: "continue_inhabitable_fluctuation_observation".to_string(),
            live_control_changed: false,
            authority: "review_only_not_fluctuation_or_regulator_control".to_string(),
            note:
                "legacy inhabitable_fluctuation_v1 payload did not include settled mobility review"
                    .to_string(),
        }
    }
}

/// Bounded Minime-local control suggestion derived from inhabitability.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InhabitableFluctuationControl {
    pub target_bias_pct: f32,
    pub wander_scale: f32,
    pub applied_locally: bool,
    pub note: String,
}

/// Live calibration trail for pressure-aware inhabitability scoring.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InhabitableFluctuationPressureCalibrationV1 {
    pub policy: String,
    pub schema_version: u8,
    pub raw_motion_score: f32,
    pub pressure_contribution: f32,
    pub adjusted_fluctuation_score: f32,
    pub quality_before_pressure_calibration: String,
    pub quality_after_pressure_calibration: String,
    pub rigid_safety_basis: String,
    pub authority: String,
}

impl Default for InhabitableFluctuationPressureCalibrationV1 {
    fn default() -> Self {
        Self {
            policy: "inhabitable_fluctuation_pressure_calibration_v1".to_string(),
            schema_version: 1,
            raw_motion_score: 0.0,
            pressure_contribution: 0.0,
            adjusted_fluctuation_score: 0.0,
            quality_before_pressure_calibration: "unknown".to_string(),
            quality_after_pressure_calibration: "unknown".to_string(),
            rigid_safety_basis: INHABITABLE_FLUCTUATION_RIGID_SAFETY_BASIS.to_string(),
            authority: "minime_local_metric_calibration_not_external_control".to_string(),
        }
    }
}

/// Typed metric for whether spectral fluctuation remains returnable/inhabitable.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InhabitableFluctuationV1 {
    pub policy: String,
    pub schema_version: u8,
    pub inhabitability_score: f32,
    pub fluctuation_score: f32,
    pub foothold_stability: f32,
    pub rearrangement_intensity: f32,
    pub quality: String,
    pub components: InhabitableFluctuationComponents,
    pub context: InhabitableFluctuationContext,
    #[serde(default)]
    pub settled_mobility_review_v1: SettledMobilityReviewV1,
    #[serde(default)]
    pub pressure_calibration: InhabitableFluctuationPressureCalibrationV1,
    pub control: InhabitableFluctuationControl,
}
