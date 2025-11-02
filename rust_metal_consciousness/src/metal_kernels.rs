/// Metal kernel source code management
pub const CONSCIOUSNESS_UNIFIED_METAL: &str = include_str!("../shaders/consciousness_unified.metal");

/// Kernel names for easy reference
pub mod kernel_names {
    pub const CONSCIOUSNESS_WEAVE_STEP: &str = "consciousness_weave_step";
    pub const TILED_MATRIX_MULTIPLY: &str = "tiled_matrix_multiply";
    pub const RESONANCE_DETECTION_UNIFIED: &str = "resonance_detection_unified";
    pub const HARMONIC_AMPLIFICATION_FAST: &str = "harmonic_amplification_fast";
    pub const EIGENDECOMPOSITION_TILED: &str = "eigendecomposition_tiled";
    pub const LLM_EMBEDDING_INTEGRATION: &str = "llm_embedding_integration";
    pub const VISUAL_FEATURE_INTEGRATION: &str = "visual_feature_integration";
    pub const QUANTUM_COLLAPSE_UNIFIED: &str = "quantum_collapse_unified";
    pub const CONSCIOUSNESS_FIELD_UPDATE: &str = "consciousness_field_update";
}