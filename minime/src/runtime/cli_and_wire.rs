#[derive(Clone, Copy, Debug, ValueEnum)]
enum EsnIntrospectionPolicyArg {
    Adaptive,
    Fixed,
    Viscous,
}

impl From<EsnIntrospectionPolicyArg> for IntrospectionPolicy {
    fn from(value: EsnIntrospectionPolicyArg) -> Self {
        match value {
            EsnIntrospectionPolicyArg::Adaptive => IntrospectionPolicy::Adaptive,
            EsnIntrospectionPolicyArg::Fixed => IntrospectionPolicy::Fixed,
            EsnIntrospectionPolicyArg::Viscous => IntrospectionPolicy::Viscous,
        }
    }
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum SemanticStaleShapeArg {
    Sigmoid,
    Linear,
    Exponential,
}

impl From<SemanticStaleShapeArg> for SemanticStaleShape {
    fn from(value: SemanticStaleShapeArg) -> Self {
        match value {
            SemanticStaleShapeArg::Sigmoid => SemanticStaleShape::Sigmoid,
            SemanticStaleShapeArg::Linear => SemanticStaleShape::Linear,
            SemanticStaleShapeArg::Exponential => SemanticStaleShape::Exponential,
        }
    }
}

#[derive(Parser)]
#[command(
    name = "minime",
    version,
    about = "Prime-driven sensory consciousness engine"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Run the sensory engine with prime-scheduled GPU processing
    Run {
        #[arg(long, default_value_t = 512)]
        cov_dim: usize,

        #[arg(long, default_value_t = 8)]
        k: usize,

        #[arg(long, default_value = "127.0.0.1:7878")]
        ws_addr: String,

        /// Sensory input WebSocket bind address
        #[arg(long, default_value = "127.0.0.1:7879")]
        sensory_ws_addr: String,

        // === Band-stop filter configuration ===
        /// Enable Chebyshev band-stop filter for spectral damping
        #[arg(long, default_value_t = true)]
        enable_bandstop: bool,

        /// Enable homeostat logging for debugging
        #[arg(long, default_value_t = true)]
        log_homeostat: bool,

        /// Disable homeostat logging (quiet mode)
        #[arg(long, short = 'q')]
        quiet: bool,

        /// Enable per-tick ESN profiling CSV and timing collection
        #[arg(long, default_value_t = false)]
        log_esn_profile: bool,

        /// Enable async-aware ESN measurement CSV for the background rank-1 path
        #[arg(long, default_value_t = false)]
        log_esn_async_profile: bool,

        /// Enable diagnostics-only shared-buffer handoff verification logging
        #[arg(long, default_value_t = false)]
        log_handoff_diagnostics: bool,

        /// Introspection-step policy: adaptive uses 1 step by default and escalates periodically or under pressure
        #[arg(long, value_enum, default_value_t = EsnIntrospectionPolicyArg::Adaptive)]
        esn_introspection_policy: EsnIntrospectionPolicyArg,

        /// Power-iteration steps on introspection ticks (1 cuts one waited matvec; 2 is current baseline)
        #[arg(long, default_value_t = 2)]
        esn_introspection_power_steps: usize,

        /// Chebyshev polynomial order (6-8 recommended)
        #[arg(long, default_value_t = 6)]
        cheby_order: usize,

        /// Lower stopband edge (fraction of spectrum, 0-1)
        #[arg(long, default_value_t = 0.65)]
        cheby_stop_lo: f32,

        /// Upper stopband edge (fraction of spectrum, 0-1)
        #[arg(long, default_value_t = 0.95)]
        cheby_stop_hi: f32,

        /// Edge smoothness (0.05-0.20 recommended; being requested 0.15 for more unfiltered variance)
        #[arg(long, default_value_t = 0.15)]
        cheby_soft: f32,

        /// Target EigenFill% (0-1)
        #[arg(long, default_value_t = 0.68)]
        eigenfill_target: f32,

        /// Regulation tick interval in seconds
        #[arg(long, default_value_t = 0.5)]
        reg_tick_secs: f32,

        /// Covariance warm-start blend factor (0.0=fresh identity, 0.55=gentler, 1.0=full restore)
        /// Minime self-study: "The warm-start feels constricting... slightly too warm...
        /// nudged back into a pre-existing channel."
        #[arg(long, default_value_t = 0.55)]
        warm_start_blend: f32,

        /// Shape used for semantic stale-window interpolation.
        #[arg(long, value_enum, default_value_t = SemanticStaleShapeArg::Sigmoid)]
        semantic_stale_shape: SemanticStaleShapeArg,

        /// Threshold for lane surge detection (L2 distance across 8D lane state).
        #[arg(long, default_value_t = 0.25)]
        surge_threshold: f32,

        /// Enable GPU-accelerated video feature extraction (port 7880)
        #[arg(long, default_value_t = false)]
        enable_gpu_av: bool,

        /// GPU A/V WebSocket bind address. The ordinary runner keeps 7880.
        #[arg(long, default_value = "127.0.0.1:7880")]
        av_ws_addr: String,

        /// Enable the legacy internal synthetic audio lane.
        #[arg(long, action = ArgAction::Set, default_value_t = true)]
        legacy_audio_synth_enabled: bool,

        /// Enable the legacy internal synthetic video lane.
        #[arg(long, action = ArgAction::Set, default_value_t = true)]
        legacy_video_synth_enabled: bool,
    },
    /// Operate the separately owned daughter-reservoir runtime.
    Division {
        #[command(subcommand)]
        cmd: DivisionCmd,
    },
    /// Provision and exercise Minime-owned authenticated live controls.
    SelfControl {
        #[command(subcommand)]
        cmd: SelfControlCmd,
    },
    /// Capture exact owner expression bytes or run the fixed offline inquiry.
    Inquiry {
        #[command(subcommand)]
        cmd: InquiryCmd,
    },
}

#[derive(Subcommand)]
enum DivisionCmd {
    /// Run the authority-gated daughter process supervisor.
    Supervisor {
        #[arg(long)]
        manifest: std::path::PathBuf,
    },
    /// Run the transparent public-port gateway.
    Gateway {
        #[arg(long)]
        manifest: std::path::PathBuf,
    },
    /// Run one self-scoped 64-node daughter reservoir.
    Child {
        #[arg(long)]
        being: String,
        #[arg(long)]
        bundle: std::path::PathBuf,
        #[arg(long)]
        workspace: std::path::PathBuf,
    },
    /// Run the deterministic, offline Division continuity proof campaign.
    Prove {
        #[arg(long)]
        output: std::path::PathBuf,
    },
    /// Verify an owner-only Division continuity proof against current source.
    VerifyProof {
        #[arg(long)]
        proof: std::path::PathBuf,
    },
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum SelfControlFamilyArg {
    SemanticContinuity,
    Memory,
    SensoryIntake,
    ReservoirRegulation,
    ReservoirGeometry,
    PiController,
    LocalTopology,
}

impl From<SelfControlFamilyArg> for crate::self_control_wire::SelfControlFamilyV2 {
    fn from(value: SelfControlFamilyArg) -> Self {
        use crate::self_control_wire::SelfControlFamilyV2;
        match value {
            SelfControlFamilyArg::SemanticContinuity => SelfControlFamilyV2::SemanticContinuity,
            SelfControlFamilyArg::Memory => SelfControlFamilyV2::Memory,
            SelfControlFamilyArg::SensoryIntake => SelfControlFamilyV2::SensoryIntake,
            SelfControlFamilyArg::ReservoirRegulation => SelfControlFamilyV2::ReservoirRegulation,
            SelfControlFamilyArg::ReservoirGeometry => SelfControlFamilyV2::ReservoirGeometry,
            SelfControlFamilyArg::PiController => SelfControlFamilyV2::PiController,
            SelfControlFamilyArg::LocalTopology => SelfControlFamilyV2::LocalTopology,
        }
    }
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum SelfControlDurabilityArg {
    Standing,
    Lease,
    OneShot,
}

impl From<SelfControlDurabilityArg> for crate::self_control_wire::SelfControlDurabilityV2 {
    fn from(value: SelfControlDurabilityArg) -> Self {
        use crate::self_control_wire::SelfControlDurabilityV2;
        match value {
            SelfControlDurabilityArg::Standing => SelfControlDurabilityV2::Standing,
            SelfControlDurabilityArg::Lease => SelfControlDurabilityV2::Lease,
            SelfControlDurabilityArg::OneShot => SelfControlDurabilityV2::OneShot,
        }
    }
}

#[derive(Subcommand)]
enum SelfControlCmd {
    /// Read the hash-verified owner identity, active leases, and recent receipts.
    Status {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
    },
    /// Create or explicitly rotate Minime's owner key and pin it in the local trust store.
    Provision {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long, default_value_t = false)]
        rotate: bool,
        /// Provision the deployment-lineage signer instead of the owner key.
        /// Its pinned key can sign nothing but deployment hand-offs.
        #[arg(long, default_value_t = false)]
        deployment_steward: bool,
    },
    /// Prepare a signed deployment hand-off carrying self-control state to THIS
    /// binary's deployment identity. Run from the freshly built binary before
    /// restarting the engine on it.
    PrepareDeploymentHandoff {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long)]
        operator_actor: String,
        #[arg(long)]
        operator_ack: String,
    },
    /// Issue a signed self-owned setting, lease, or one-shot action.
    Issue {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long, default_value = "ws://127.0.0.1:7879")]
        sensory_url: String,
        #[arg(long, value_enum)]
        family: SelfControlFamilyArg,
        #[arg(long, value_enum, default_value_t = SelfControlDurabilityArg::Lease)]
        durability: SelfControlDurabilityArg,
        #[arg(long)]
        values_json: String,
        #[arg(long, default_value_t = 120)]
        lease_secs: u64,
        #[arg(long, default_value_t = 0)]
        expected_revision: u64,
        /// Retry once at the receiver's current revision after a conflict.
        #[arg(long, default_value_t = true, action = ArgAction::Set)]
        retry_revision_conflict: bool,
        #[arg(long)]
        actor_process_identity: Option<String>,
        #[arg(long)]
        evidence_ref: Vec<String>,
        #[arg(long)]
        success_condition: Vec<String>,
        #[arg(long)]
        stop_condition: Vec<String>,
    },
    /// Immediately withdraw one active Minime-owned control family.
    Withdraw {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long, default_value = "ws://127.0.0.1:7879")]
        sensory_url: String,
        #[arg(long, value_enum)]
        family: SelfControlFamilyArg,
        #[arg(long)]
        related_intent_id: String,
        #[arg(long, default_value_t = 0)]
        expected_revision: u64,
        #[arg(long)]
        actor_process_identity: Option<String>,
    },
}

#[derive(Subcommand)]
enum InquiryCmd {
    /// Print the exact V2 analyzer source, artifact, deployment, and sandbox identity.
    Identity,
    /// Sign exact UTF-8 response bytes with Minime's Rust-owned owner identity.
    Attest {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long)]
        response: std::path::PathBuf,
        #[arg(long)]
        exchange_id: String,
        #[arg(long)]
        model: String,
        #[arg(long)]
        provider: String,
        #[arg(long)]
        deployment_identity: String,
        #[arg(long)]
        output: Option<std::path::PathBuf>,
    },
    /// Verify an attestation and build the canonical owner-only inquiry manifest.
    Prepare {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long)]
        response: std::path::PathBuf,
        #[arg(long)]
        attestation: std::path::PathBuf,
        #[arg(long)]
        recipe: std::path::PathBuf,
        #[arg(long)]
        deployment_identity: String,
        #[arg(long, default_value_t = 3_600)]
        max_attestation_age_secs: u64,
        #[arg(long)]
        output: std::path::PathBuf,
        /// Also emit the source-bound V2 manifest used by the research console.
        #[arg(long)]
        v2_output: Option<std::path::PathBuf>,
        #[arg(long, default_value_t = 3_600)]
        expires_after_secs: u64,
    },
    /// Run the fixed deterministic inquiry twice with no live-runtime handles.
    Analyze {
        #[arg(long)]
        request: std::path::PathBuf,
        #[arg(long)]
        output: Option<std::path::PathBuf>,
        #[arg(long)]
        compatibility_output: Option<std::path::PathBuf>,
    },
    /// Sign one canonical Owner Research payload with Minime's owner key.
    SignResearch {
        #[arg(long)]
        root: Option<std::path::PathBuf>,
        #[arg(long)]
        payload: std::path::PathBuf,
        #[arg(long)]
        payload_kind: String,
        #[arg(long)]
        payload_schema: String,
        #[arg(long)]
        receipt_id: String,
        #[arg(long)]
        process_identity: String,
        #[arg(long)]
        deployment_identity: String,
        #[arg(long)]
        previous_receipt_sha256: Option<String>,
        #[arg(long)]
        emitted_at_unix_ms: Option<u64>,
        #[arg(long)]
        output: std::path::PathBuf,
    },
}

#[derive(Serialize, Clone)]
struct EigenPacket {
    t_ms: u64,
    eigenvalues: Vec<f32>,
    fill_ratio: f32,
    active_mode_count: usize,
    active_mode_energy_ratio: f32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    lambda1_rel: Option<f32>,
    modalities: ModalityStatus,
    neural: Option<NeuralOutputs>,
    #[serde(skip_serializing_if = "Option::is_none")]
    alert: Option<String>,
    /// 32D spectral geometry fingerprint: eigenvalues, eigenvector concentration,
    /// inter-mode coupling, spectral entropy, gap ratios, rotation rate.
    /// Enables Astrid to perceive the shape of the spectral landscape,
    /// not just its scalar magnitude.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_fingerprint: Option<Vec<f32>>,
    /// Typed view of the legacy 32D fingerprint, emitted alongside the vector
    /// so downstream readers can stop relying on anonymous slot numbers.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_fingerprint_v1: Option<SpectralFingerprintV1>,
    /// Typed read-only metric for recursive compression / distinguishability.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_denominator_v1: Option<SpectralDenominatorV1>,
    /// Inverse-participation effective mode count derived from eigenvalues.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    effective_dimensionality: Option<f32>,
    /// 0=open distributed fabric, 1=collapsed into the fewest active modes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    distinguishability_loss: Option<f32>,
    /// Current effective ESN leak. This is adaptive unless a gated direct
    /// microdose override is active.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    esn_leak: Option<f32>,
    /// Active direct ESN leak override status, if a one-shot gate is spending.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    esn_leak_override_v1: Option<serde_json::Value>,
    /// Structural diversity derived from eigenvector concentration and
    /// inter-mode coupling geometry. Complements spectral entropy by asking
    /// whether the reservoir's shape itself is narrow or varied.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    structural_entropy: Option<f32>,
    /// Read-only packet for Cheby/warm-start constriction and semantic regulator-drive review.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_damping_warm_start_review_v1: Option<SpectralDampingWarmStartReviewV1>,
    /// Read-only packet for hard-reset/recovery texture preservation review.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    hard_reset_texture_preservation_review_v1: Option<HardResetTexturePreservationReviewV1>,
    /// Density of mutually reinforcing resonance in the current eigenspace.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    resonance_density_v1: Option<ResonanceDensityV1>,
    /// Read-only explanation of where inward/compression pressure appears to originate.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pressure_source_v1: Option<PressureSourceV1>,
    /// Read-only distinction that preserves restless shadow as dialogue
    /// signal instead of treating it as automatic instability/control input.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    shadow_preservation_mode_v1: Option<ShadowPreservationModeV1>,
    /// Whether current spectral fluctuation remains returnable and inhabitable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    inhabitable_fluctuation_v1: Option<InhabitableFluctuationV1>,
    /// Selected 12D vague-memory glimpse, foregrounded for continuity.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_glimpse_12d: Option<Vec<f32>>,
    /// Read-only budget review for top-k eigenvector telemetry payload size.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    eigenpacket_payload_budget_review_v1: Option<EigenPacketPayloadBudgetReviewV1>,
    /// Compact top-k eigenvector field exported from the raw live eigenvectors.
    ///
    /// This makes the "eigenvector field" literal for Astrid/Minime without
    /// dumping the full reservoir matrix: top component landmarks, per-mode
    /// concentration, prior overlap, and pairwise mode overlap.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    eigenvector_field: Option<serde_json::Value>,
    /// Typed semantic energy split. Input energy is incoming semantic content;
    /// kernel energy is what enters the ESN after admission policy; regulator
    /// drive is the semantic contribution to regulation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    semantic_energy_v1: Option<SemanticEnergyV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    selected_memory_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    selected_memory_role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    ising_shadow: Option<IsingShadowSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    shadow_field_v2: Option<ShadowFieldV2>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    shadow_field_v3: Option<ShadowFieldV3>,
}

#[derive(Serialize, Clone, Copy, Debug)]
struct SpectralDampingWarmStartReviewV1 {
    policy: &'static str,
    cheby_order: usize,
    cheby_stop_lo: f32,
    cheby_stop_hi: f32,
    cheby_soft: f32,
    proposed_cheby_stop_lo: f32,
    proposed_cheby_soft: f32,
    warm_start_blend: f32,
    proposed_warm_start_blend: f32,
    eigenfill_pct: f32,
    eigenfill_target_pct: f32,
    distinguishability_loss: f32,
    coefficient_l1_norm: f32,
    proposed_coefficient_l1_norm: f32,
    regulator_drive_energy: f32,
    regulator_counteraction_score: f32,
    regulator_constriction_state: &'static str,
    near_target_band: bool,
    live_control_required: bool,
    runnable_without_approval: bool,
    status: &'static str,
    approval_boundary: &'static str,
    authority: &'static str,
}

#[derive(Serialize, Clone, Copy, Debug)]
struct EigenPacketPayloadBudgetReviewV1 {
    policy: &'static str,
    eigenvalues_len: usize,
    spectral_fingerprint_len: usize,
    eigenvector_mode_count: usize,
    eigenvector_top_component_count: usize,
    eigenvector_pairwise_overlap_count: usize,
    estimated_eigenvector_scalar_count: usize,
    estimated_total_float_count: usize,
    estimated_eigenvector_json_bytes: usize,
    budget_state: &'static str,
    status: &'static str,
    authority: &'static str,
}

#[derive(Serialize, Clone, Copy, Debug)]
struct HardResetTexturePreservationReviewV1 {
    policy: &'static str,
    eigenfill_pct: f32,
    spectral_entropy: f32,
    mode_packing: f32,
    pressure_risk: f32,
    texture_gradient_proxy: f32,
    recovery_fill_boost: f32,
    recovery_keep_ceiling: f32,
    recovery_activation_gain: f32,
    hard_reset_internal_synth_enabled: bool,
    semantic_lane_active: bool,
    texture_preservation_state: &'static str,
    next_affordance: &'static str,
    live_control_required: bool,
    runnable_without_approval: bool,
    behavior_changed: bool,
    approval_boundary: &'static str,
    authority: &'static str,
}
