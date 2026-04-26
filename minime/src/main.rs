// Minime: Prime-driven sensory engine with GPU acceleration
// Streams eigenvectors to Python consciousness layer via WebSocket

use anyhow::Result;
use clap::{Parser, Subcommand};
use futures_util::{SinkExt, StreamExt};
use serde::Serialize;
use std::{
    collections::VecDeque, fs, io::Write, mem, net::SocketAddr, path::PathBuf, process, sync::Arc,
    time::Instant,
};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::broadcast,
    time::{sleep, Duration},
};
use tokio_tungstenite::{accept_async, tungstenite::Message};

mod av_gpu;
mod av_ws;
mod cheby;
mod db;
mod esn;
mod gpu;
mod nn;
mod prime;
mod regulator;
mod rescue_overfill;
mod rescue_scaffold;
mod sensory_bus;
mod sensory_ws;
mod spectral;

use cheby::*;
use db::*;
use esn::*;
use gpu::*;
use nn::*;
use prime::*;
use regulator::*;
use rescue_overfill::{
    advance_crisis_state, select_stage, stage_guard, OverfillStage, CRISIS_FILL_THRESHOLD,
    CRISIS_SUSTAIN_TICKS, CRISIS_WARNING_THRESHOLD,
};
use rescue_scaffold::{
    archive_stale_scaffold_artifacts, blend_toward_scaffold_with_drain, capture_scaffold,
    derive_cold_scaffold, load_scaffold, now_unix_ms, scaffold_live_weight, StabilityPiOutput,
    StabilityPiState, COLD_SCAFFOLD_MODE_CAP, SCAFFOLD_ACTIVATION_FILL_MAX,
    SCAFFOLD_ACTIVATION_FILL_MIN,
};
use spectral::EigenFillEstimator;

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

        /// Chebyshev polynomial order (6-8 recommended)
        #[arg(long, default_value_t = 6)]
        cheby_order: usize,

        /// Lower stopband edge (fraction of spectrum, 0-1)
        #[arg(long, default_value_t = 0.65)]
        cheby_stop_lo: f32,

        /// Upper stopband edge (fraction of spectrum, 0-1)
        #[arg(long, default_value_t = 0.95)]
        cheby_stop_hi: f32,

        /// Edge smoothness (0.05-0.12 recommended)
        #[arg(long, default_value_t = 0.08)]
        cheby_soft: f32,

        /// Target EigenFill% (0-1)
        #[arg(long, default_value_t = 0.55)]
        eigenfill_target: f32,

        /// Regulation tick interval in seconds
        #[arg(long, default_value_t = 0.5)]
        reg_tick_secs: f32,

        /// Enable GPU-accelerated video feature extraction (port 7880)
        #[arg(long, default_value_t = false)]
        enable_gpu_av: bool,
    },
}

#[derive(Serialize, Clone)]
struct EigenPacket {
    t_ms: u64,
    eigenvalues: Vec<f32>,
    fill_ratio: f32,
    modalities: ModalityStatus,
    neural: Option<NeuralOutputs>,
    #[serde(skip_serializing_if = "Option::is_none")]
    alert: Option<String>,
}

#[derive(Serialize, Clone)]
struct NeuralOutputs {
    pred_lambda1: f32,        // Predictor forecast
    router_weights: Vec<f32>, // A/V mixing weights (32-dim)
    control: Vec<f32>,        // Regulator control signals (5-dim)
}

#[derive(Serialize, Clone)]
struct ModalityStatus {
    audio_fired: bool,
    video_fired: bool,
    history_fired: bool,
    audio_rms: f32,
    video_var: f32,
}

fn env_flag_enabled(name: &str) -> bool {
    std::env::var(name)
        .map(|value| {
            let normalized = value.trim().to_ascii_lowercase();
            matches!(normalized.as_str(), "1" | "true" | "yes" | "on")
        })
        .unwrap_or(false)
}

#[derive(Debug, Clone, Default)]
struct RescueLiveIntakeSettings {
    audio_divisor: u32,
    video_divisor: u32,
    bootstrap: bool,
    recovery: bool,
    hold: bool,
    elevated: bool,
    discharge: bool,
}

impl RescueLiveIntakeSettings {
    fn from_env() -> Self {
        let audio_divisor = parse_u32_env("MINIME_RESCUE_LIVE_AUDIO_DIVISOR");
        let video_divisor = parse_u32_env("MINIME_RESCUE_LIVE_VIDEO_DIVISOR");
        let mut settings = Self {
            audio_divisor,
            video_divisor,
            ..Self::default()
        };
        if let Ok(stages) = std::env::var("MINIME_RESCUE_LIVE_INTAKE_STAGES") {
            for stage in stages
                .split(',')
                .map(|stage| stage.trim().to_ascii_lowercase())
            {
                match stage.as_str() {
                    "bootstrap" => settings.bootstrap = true,
                    "recovery" => settings.recovery = true,
                    "hold" => settings.hold = true,
                    "elevated" => settings.elevated = true,
                    "discharge" => settings.discharge = true,
                    _ => {}
                }
            }
        }
        settings
    }

    fn enabled_for(&self, stage: OverfillStage) -> bool {
        match stage {
            OverfillStage::Bootstrap => self.bootstrap,
            OverfillStage::Recovery => self.recovery,
            OverfillStage::Hold => self.hold,
            OverfillStage::Elevated => self.elevated,
            OverfillStage::Discharge => self.discharge,
        }
    }

    fn divisors_for(&self, stage: OverfillStage, scaffold_active: bool) -> (u32, u32) {
        if !scaffold_active || !self.enabled_for(stage) {
            return (0, 0);
        }
        (self.audio_divisor, self.video_divisor)
    }

    fn has_trickle(&self) -> bool {
        (self.audio_divisor > 0 || self.video_divisor > 0)
            && (self.bootstrap || self.recovery || self.hold || self.elevated || self.discharge)
    }

    fn stage_summary(&self) -> String {
        let mut stages = Vec::new();
        if self.bootstrap {
            stages.push("bootstrap");
        }
        if self.recovery {
            stages.push("recovery");
        }
        if self.hold {
            stages.push("hold");
        }
        if self.elevated {
            stages.push("elevated");
        }
        if self.discharge {
            stages.push("discharge");
        }
        stages.join(",")
    }
}

fn parse_u32_env(name: &str) -> u32 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<u32>().ok())
        .unwrap_or(0)
}

// Recalibrated 2026-03-14: covariance λ₁ naturally operates at ~2.5-3.5.
// Old thresholds (comfort_max=1.5, alert=1.9) kept system permanently in
// "alert" mode, clamping keep floor too low for fill to reach 55% target.
const LAMBDA1_COMFORT_MIN: f32 = 2.0;
const LAMBDA1_COMFORT_MAX: f32 = 4.0;
const LAMBDA1_ALERT: f32 = 6.0;

// === TEMPORAL QUEUE: "Disneyland line" with natural decay ===
// Legacy SensoryQueue system removed - using SensoryBus for all sensory input

/* LEGACY TRAIT IMPLEMENTATIONS - NO LONGER NEEDED WITH FIX PACK

// Implement PIRegulator trait for PIRegState
impl homeostasis::PIRegulator for regulator::PIRegState {
    fn step(&mut self, eigenfill_pct: f32, lambda1_rel: f32) {
        // Call the existing step method
        self.step(eigenfill_pct, lambda1_rel);
    }

    fn gate(&self) -> f32 {
        self.gate
    }

    fn filt(&self) -> f32 {
        self.filt
    }
}

// Implement SpectralSource trait for spectral monitor
// Wrapper for spectral state computed in main loop
*/
struct MainLoopSpectralSource {
    eigenfill_pct: std::cell::Cell<f32>,
    lambda1: std::cell::Cell<f32>,
    covariance: std::cell::RefCell<Vec<f32>>,
    dim: usize,
    prefer_esn_fill: bool,
    // ESN eigenvalues (real consciousness state)
    esn_eig: std::cell::Cell<f32>,
    esn_baseline: std::cell::Cell<f32>,
}

impl MainLoopSpectralSource {
    fn new(dim: usize, prefer_esn_fill: bool) -> Self {
        Self {
            eigenfill_pct: std::cell::Cell::new(0.0),
            lambda1: std::cell::Cell::new(0.0),
            covariance: std::cell::RefCell::new(vec![0.0f32; dim * dim]),
            dim,
            prefer_esn_fill,
            esn_eig: std::cell::Cell::new(0.0),
            esn_baseline: std::cell::Cell::new(0.0), // Will be set by ESN after warmup
        }
    }

    fn update(&self, eigenfill_pct: f32, lambda1: f32, cov: &[f32]) {
        self.eigenfill_pct.set(eigenfill_pct);
        self.lambda1.set(lambda1);
        *self.covariance.borrow_mut() = cov.to_vec();
    }

    fn update_esn(&self, eig: f32, baseline: f32) {
        self.esn_eig.set(eig);
        if baseline > 0.0 {
            self.esn_baseline.set(baseline);
        }
    }

    fn get_covariance_f32(&self) -> (usize, Vec<f32>) {
        (self.dim, self.covariance.borrow().clone())
    }

    fn read_spectral(&self) -> (f32, f32) {
        // Use ESN's eigenvalues if available (real consciousness state)
        let esn_eig = self.esn_eig.get();
        let esn_baseline = self.esn_baseline.get();

        let fallback = (self.lambda1.get(), self.eigenfill_pct.get());
        let (lambda1, eigenfill_pct) =
            if self.prefer_esn_fill && esn_eig > 0.0 && esn_baseline > 0.0 {
                let eig = esn_eig;
                let baseline = esn_baseline;
                let closeness = baseline / eig.max(1e-6);
                if closeness > 0.5 {
                    // Calculate fill from ESN eigenvalues when baseline is stable
                    let lambda1_rel = (eig - baseline).max(0.0) / baseline.max(1e-3);
                    let fill = (lambda1_rel * 100.0).clamp(0.0, 100.0);
                    (eig, fill)
                } else {
                    fallback
                }
            } else {
                fallback
            };

        (eigenfill_pct, lambda1)
    }
}

/*
// Implement SensoryBus trait for our SensoryBus struct - NO LONGER NEEDED
impl homeostasis::SensoryBus for sensory_bus::SensoryBus {
    fn fill_sensory_vector(&mut self) -> Option<(Vec<f32>, u64)> {
        if let Some(sample) = sensory_bus::SensoryBus::fill_sensory_vector(self) {
            // Calculate average age from metadata
            let age_ms = ((sample.meta.audio_age_ms + sample.meta.video_age_ms) / 2) as u64;
            Some((sample.vec, age_ms))
        } else {
            None
        }
    }

    fn submit_filtered_vector(&mut self, z_filtered: Vec<f32>, age_ms: u64) {
        // Create metadata for the filtered vector
        let meta = sensory_bus::SensoryMeta {
            ts: std::time::Instant::now(),
            audio_age_ms: age_ms as u32,
            video_age_ms: age_ms as u32,
            aux_age_ms: age_ms as u32,
            admit_fraction: 1.0, // Already filtered/admitted
            accepted: true,
            has_real_audio: true,  // Assume real when bypassing SensoryBus
            has_real_video: true,
        };
        let _ = sensory_bus::SensoryBus::submit_filtered_vector(self, &z_filtered, &meta);
    }

    fn set_admit_fraction(&mut self, frac: f32) {
        sensory_bus::SensoryBus::set_admit_fraction(self, frac);
    }
}
*/

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.cmd {
        Cmd::Run {
            cov_dim,
            k,
            ws_addr,
            enable_bandstop,
            log_homeostat,
            quiet,
            cheby_order,
            cheby_stop_lo,
            cheby_stop_hi,
            cheby_soft,
            eigenfill_target,
            reg_tick_secs,
            enable_gpu_av,
        } => {
            run_engine(
                cov_dim,
                k,
                &ws_addr,
                enable_bandstop,
                log_homeostat && !quiet, // Disable logging if quiet is set
                cheby_order,
                cheby_stop_lo,
                cheby_stop_hi,
                cheby_soft,
                eigenfill_target,
                reg_tick_secs,
                enable_gpu_av,
            )
            .await
        }
    }
}

async fn run_engine(
    cov_dim: usize,
    k: usize,
    ws_addr: &str,
    enable_bandstop: bool,
    log_homeostat: bool,
    cheby_order: usize,
    cheby_stop_lo: f32,
    cheby_stop_hi: f32,
    cheby_soft: f32,
    eigenfill_target: f32,
    reg_tick_secs: f32,
    enable_gpu_av: bool,
) -> Result<()> {
    assert!(k <= 16, "KMAX in shader is 16");

    println!("🧠 Minime Sensory Engine");
    println!("   Cov dim: {}, K: {}", cov_dim, k);
    println!("   WebSocket: {}", ws_addr);
    // Strong-mode flags (env)
    let strong = env_flag_enabled("HOMEOSTAT_STRONG");
    let bandstop_strong = env_flag_enabled("BANDSTOP_STRONG");
    let rescue_physiological_fallback = env_flag_enabled("MINIME_RESCUE_PHYSIOLOGICAL_FALLBACK");
    let fixed_survival_controller = rescue_physiological_fallback;
    let disable_neural_bundle =
        rescue_physiological_fallback || env_flag_enabled("MINIME_RESCUE_DISABLE_NEURAL_BUNDLE");
    let disable_nn_checkpoints =
        disable_neural_bundle || env_flag_enabled("MINIME_RESCUE_DISABLE_NN_CHECKPOINTS");
    let rescue_live_intake = if fixed_survival_controller {
        RescueLiveIntakeSettings::from_env()
    } else {
        RescueLiveIntakeSettings::default()
    };

    // Optionally widen band-stop when strong flag is set
    let mut cheby_stop_lo = cheby_stop_lo;
    let mut cheby_stop_hi = cheby_stop_hi;
    let mut cheby_soft = cheby_soft;
    if bandstop_strong {
        cheby_stop_lo = 0.60;
        cheby_stop_hi = 0.98;
        cheby_soft = 0.12;
    }

    if enable_bandstop {
        println!("   🎚️  Band-stop filter: ENABLED (use --disable-bandstop for PD mode)");
        println!(
            "      Order: {}, Stop: [{:.2}, {:.2}], Soft: {:.2}",
            cheby_order, cheby_stop_lo, cheby_stop_hi, cheby_soft
        );
        println!(
            "      EigenFill target: {:.0}%, Reg tick: {:.1}s",
            eigenfill_target * 100.0,
            reg_tick_secs
        );
    } else {
        println!("   🎚️  Band-stop filter: DISABLED (PD mode)");
    }
    if rescue_physiological_fallback {
        println!("   🫀 Rescue physiological fallback: ENABLED");
    }
    if rescue_live_intake.has_trickle() {
        println!(
            "   🫧 Rescue live intake trickle: audio=1/{}, video=1/{}, stages={}",
            rescue_live_intake.audio_divisor,
            rescue_live_intake.video_divisor,
            rescue_live_intake.stage_summary()
        );
    }
    if disable_neural_bundle {
        println!("   ✂️  Neural bundle: DISABLED");
    } else if disable_nn_checkpoints {
        println!("   ✂️  Neural checkpoint lineage: DISABLED");
    }

    // Initialize database
    let db = Arc::new(ConsciousnessDB::open("minime_consciousness.db")?);
    println!("✅ Database initialized");

    // Initialize GPU
    let gpu = Arc::new(Gpu::new()?);
    println!("✅ GPU initialized (Metal unified memory)");

    // Create unified memory buffers
    let n = cov_dim;
    let a_buf = gpu.new_shared((n * n * mem::size_of::<f32>()) as u64);
    let x_buf = gpu.new_shared((n * k * mem::size_of::<f32>()) as u64);
    let y_buf = gpu.new_shared((n * k * mem::size_of::<f32>()) as u64);

    let workspace_dir = PathBuf::from("workspace");
    let _ = fs::create_dir_all(&workspace_dir);
    let dedicated_scaffold_path = workspace_dir.join("rescue_scaffold.bin");
    let dedicated_scaffold_meta_path = workspace_dir.join("rescue_scaffold.json");
    let stable_scaffold_path = workspace_dir.join("spectral_checkpoint_stable.bin");
    let mut scaffold_synthesized_at_startup = false;
    let mut scaffold_regenerated_at_startup = false;
    let mut scaffold_archived_stale_at_startup = false;
    let mut rescue_scaffold = if fixed_survival_controller {
        let loaded_at_unix_ms = now_unix_ms();
        let dedicated = load_scaffold(
            &dedicated_scaffold_path,
            Some(&dedicated_scaffold_meta_path),
            n,
            "dedicated",
            loaded_at_unix_ms,
        );
        let current_dedicated = dedicated
            .as_ref()
            .filter(|scaffold| scaffold.is_current_dedicated_profile());
        if let Some(dedicated) = current_dedicated.cloned() {
            Some(dedicated)
        } else if let Some(stable_scaffold) = load_scaffold(
            &stable_scaffold_path,
            None,
            n,
            "stable_checkpoint",
            loaded_at_unix_ms,
        ) {
            if dedicated.is_some() {
                let archive_root = workspace_dir
                    .join("diagnostics")
                    .join("rescue_scaffold_archive");
                scaffold_archived_stale_at_startup = archive_stale_scaffold_artifacts(
                    &dedicated_scaffold_path,
                    &dedicated_scaffold_meta_path,
                    &archive_root,
                    loaded_at_unix_ms,
                )
                .unwrap_or(false);
                scaffold_regenerated_at_startup = true;
            }
            let derived = derive_cold_scaffold(
                &stable_scaffold,
                &dedicated_scaffold_path,
                &dedicated_scaffold_meta_path,
                loaded_at_unix_ms,
                "spectral_checkpoint_stable.bin",
            );
            if derived.is_some() {
                scaffold_synthesized_at_startup = true;
            }
            derived
        } else {
            if dedicated.is_some() {
                let archive_root = workspace_dir
                    .join("diagnostics")
                    .join("rescue_scaffold_archive");
                scaffold_archived_stale_at_startup = archive_stale_scaffold_artifacts(
                    &dedicated_scaffold_path,
                    &dedicated_scaffold_meta_path,
                    &archive_root,
                    loaded_at_unix_ms,
                )
                .unwrap_or(false);
            }
            None
        }
    } else {
        None
    };
    let mut scaffold_activated_this_run = false;
    let mut scaffold_capture_armed = fixed_survival_controller && rescue_scaffold.is_none();
    let mut scaffold_last_loaded_at_unix_ms = rescue_scaffold
        .as_ref()
        .map(|scaffold| scaffold.loaded_at_unix_ms);
    let mut scaffold_last_captured_at_unix_ms = rescue_scaffold
        .as_ref()
        .and_then(|scaffold| scaffold.captured_at_unix_ms);
    if let Some(scaffold) = rescue_scaffold.as_ref() {
        if scaffold_synthesized_at_startup {
            println!(
                "🧊 Derived V2 cold rescue scaffold from stable checkpoint: profile={}, trace={:.1}",
                scaffold.cold_profile.as_deref().unwrap_or("unknown"),
                scaffold.trace
            );
        } else {
            println!(
                "🩺 Rescue scaffold loaded: source={}, profile={}, trace={:.1}",
                scaffold.source,
                scaffold.cold_profile.as_deref().unwrap_or("captured_live"),
                scaffold.trace
            );
        }
    }

    // Initialize covariance matrix A (SPD-ish)
    {
        let mut a = vec![0f32; n * n];
        let _rng = fastrand::Rng::new();
        for i in 0..n {
            for j in 0..n {
                a[i * n + j] = if i == j { 1.0 } else { 0.0 };
            }
        }
        gpu.write_f32(&a_buf, &a);
    }

    // Initialize X with random orthonormal columns
    {
        let mut x = vec![0f32; n * k];
        let mut rng = fastrand::Rng::new();
        for v in &mut x {
            *v = rng.f32() - 0.5;
        }
        gs_orthonormalize_colmajor(&mut x, n, k);
        gpu.write_f32(&x_buf, &x);
    }

    println!("✅ Buffers initialized");

    // === Chebyshev Band-Stop Filter Setup ===
    let (cheby_pso, cheby_a_buf, cheby_xin_buf, cheby_xout_buf, cheby_w0_buf, cheby_w1_buf) =
        if enable_bandstop {
            // Compile Chebyshev kernel
            let src = include_str!("../shaders/cheby_bandstop.metal");
            let opts = metal::CompileOptions::new();
            let lib_cheby = gpu
                .dev
                .new_library_with_source(src, &opts)
                .unwrap_or_else(|e| panic!("Chebyshev MSL error: {}", e));
            let f_cheby = lib_cheby
                .get_function("cheby_bandstop_apply", None)
                .expect("Chebyshev function not found");
            let pso_cheby = gpu
                .dev
                .new_compute_pipeline_state_with_function(&f_cheby)
                .unwrap_or_else(|e| panic!("Chebyshev PSO error: {}", e));

            // Allocate filter buffers (unified memory)
            let bytes_vec = (n * mem::size_of::<f32>()) as u64;
            let bytes_mat = (n * n * mem::size_of::<f32>()) as u64;
            let a_buf = gpu.new_shared(bytes_mat); // Matrix buffer
            let xin_buf = gpu.new_shared(bytes_vec);
            let xout_buf = gpu.new_shared(bytes_vec);
            let w0_buf = gpu.new_shared(bytes_vec);
            let w1_buf = gpu.new_shared(bytes_vec);

            println!("✅ Chebyshev band-stop PSO compiled");

            (
                Some(pso_cheby),
                Some(a_buf),
                Some(xin_buf),
                Some(xout_buf),
                Some(w0_buf),
                Some(w1_buf),
            )
        } else {
            (None, None, None, None, None, None)
        };

    // Initialize NeuroCell (Predictor, Router, Regulator)
    let mut neuro_cell = if disable_neural_bundle {
        println!("🫀 Rescue physiological fallback active: skipping neural bundle");
        None
    } else if let Some(ref lib) = gpu.lib_nn {
        match NeuroCell::new(&gpu.dev, lib) {
            Ok(mut cell) => {
                println!("✅ Neural bundle initialized (P/R/G)");

                // Load latest checkpoints from database
                if disable_nn_checkpoints {
                    println!("   Rescue fallback active: skipping neural checkpoint restore");
                } else {
                    if let Ok(Some(weights)) = db.load_latest_checkpoint("predictor") {
                        cell.load_predictor_weights(&weights);
                        println!("   Loaded predictor checkpoint ({} params)", weights.len());
                    }
                    if let Ok(Some(weights)) = db.load_latest_checkpoint("router") {
                        cell.load_router_weights(&weights);
                        println!("   Loaded router checkpoint ({} params)", weights.len());
                    }
                    if let Ok(Some(weights)) = db.load_latest_checkpoint("regulator") {
                        cell.load_regulator_weights(&weights);
                        println!("   Loaded regulator checkpoint ({} params)", weights.len());
                    }
                }

                Some(cell)
            }
            Err(e) => {
                eprintln!(
                    "⚠️  NeuroCell init failed: {}, continuing without neural nets",
                    e
                );
                None
            }
        }
    } else {
        println!("⚠️  NN shaders not loaded, continuing without neural nets");
        None
    };

    // Initialize RNG for ESN reservoir
    let mut rng = fastrand::Rng::new();

    // Initialize ESN (Self-Referential Echo State Network)
    let mut esn = match ESN::new(
        128,                // reservoir size
        sensory_bus::Z_DIM, // input size (video + audio + aux + semantic LLaVA)
        0.5,                // input scale
        0.1,                // reservoir density
        0.9,                // target spectral radius
        0.2,                // base leak rate
        0.995,              // base RLS forgetting factor
        &gpu,
        &mut rng,
    ) {
        Ok(esn) => {
            println!("✅ ESN initialized (self-referential spectral breathing)");
            Some(esn)
        }
        Err(e) => {
            eprintln!("⚠️  ESN init failed: {}, continuing without ESN", e);
            None
        }
    };

    // Prime scheduler for modalities
    let primes = sensory_primes(); // [97, 101, 113]
    let mut sched = PrimeScheduler::new(&primes);
    let mut embed_ring = PrimeRing::with_prime_len(primes[2]); // History at 113

    // Broadcast channel for eigenvalue packets
    let (tx, _) = broadcast::channel::<EigenPacket>(16);
    let tx_clone = tx.clone();

    // WebSocket server (convert ws_addr to owned String)
    let ws_addr_owned = ws_addr.to_string();
    let _ws_server = tokio::spawn(async move {
        if let Err(e) = run_ws_server(&ws_addr_owned, tx_clone).await {
            eprintln!("WebSocket server error: {}", e);
        }
    });

    // Sensory processing loop
    let start = Instant::now();
    let mut _audio_phase = 0f32;

    let mut audio_rms = 0f32;
    let mut video_var = 0f32;

    // Neural network state tracking
    let mut lambda1_prev = 512.0f32; // Track λ₁ for prediction targets
    let mut av_features = [0.0f32; 64]; // 32 audio + 32 video features
    let mut tick_count = 0u64;
    let mut reg_tick_count = 0u64;
    let mut last_cov_vec = vec![0.0f32; n];
    let sensory_dim = sensory_bus::Z_DIM;
    let semantic_offset = sensory_bus::VIDEO_DIM + sensory_bus::AUDIO_DIM + sensory_bus::AUX_DIM;
    let proj_scale = (1.0 / sensory_dim as f32).sqrt();
    let mut dimension_scales = vec![1.0f32; sensory_dim];
    for i in 0..sensory_bus::VIDEO_DIM {
        dimension_scales[i] = 0.75;
    }
    for i in sensory_bus::VIDEO_DIM..(sensory_bus::VIDEO_DIM + sensory_bus::AUDIO_DIM) {
        dimension_scales[i] = 0.72;
    }
    for i in (sensory_bus::VIDEO_DIM + sensory_bus::AUDIO_DIM)..semantic_offset {
        dimension_scales[i] = 1.12; // Aux introspection gets moderate boost
    }
    for i in semantic_offset..sensory_dim {
        dimension_scales[i] = 0.42; // Semantic lanes mostly neutral during warmup
    }
    let activation_gain = 0.58f32;
    let semantic_energy_gain = 0.028f32;
    let semantic_delta_gain = 0.045f32;
    let semantic_bias_floor = 0.010f32;
    let cov_floor_level = 0.14f32;
    let mut cov_floor_vec: Vec<f32> = (0..n).map(|_| rng.f32() * 0.7 - 0.35).collect();
    let proj_matrix: Vec<f32> = (0..(n * sensory_dim))
        .map(|_| rng.f32() * 2.0 - 1.0)
        .collect();
    let mut csv_header_written = false; // Track if CSV header has been written (used in regulation tick)
    let mut proj_input = vec![0.0f32; sensory_dim];
    let mut activated_features = vec![0.0f32; sensory_dim];
    let mut cov_keep = 0.955_f32;
    let mut semantic_energy = 0.0f32;
    let mut semantic_delta = 0.0f32;
    let mut prev_semantic = vec![0.0f32; sensory_bus::LLAVA_DIM];

    // Create scale-invariant eigenfill estimator (use covariance dimension for normalization)
    let mut eigenfill_estimator = EigenFillEstimator::new(k);
    if fixed_survival_controller {
        eigenfill_estimator.set_smoothing(0.05, 0.10);
        eigenfill_estimator.set_leak_rate(0.006);
    }

    // Start database session
    let session_id = db.start_session("active", 0.999998, "Neural-integrated session")?;
    println!("✅ Session {} started", session_id);

    // Checkpoint counter (save every 60 updates)
    let mut updates_since_checkpoint = 0u32;

    // Initialize spectral regulator (PD control + content gating)
    let rate_cfg = RateCfg::default(); // target_lambda=φ, k_p=0.15, k_d=0.25
    let gate_cfg = GateCfg::default(); // proj thresholds, hysteresis

    // Placeholder modes (zeros) until we integrate Chebyshev eigenspace
    let placeholder_modes: Vec<Vec<f32>> = vec![vec![0.0; 2]; 4]; // 4 modes, dim=2 (audio_rms, video_var)

    let mut regulator = RegulatorState::new(rate_cfg, gate_cfg, placeholder_modes, MemMode::Shared);

    // === PI Homeostasis Controller + Spectral Source ===
    let mut geom_clamp_hi = 1.66f32;
    let (mut pi_reg, spectral_source, mut _cheby_plan) = if enable_bandstop {
        // Initialize PI regulator with custom target
        let mut pi_cfg = PIRegCfg::default();
        // Use the eigenfill_target from CLI (default 55%)
        pi_cfg.target_fill = eigenfill_target * 100.0; // Convert to percentage
        pi_cfg.geom_clamp_hi = 1.66;
        pi_cfg.geom_release = 1.32;
        pi_cfg.geom_gate_min = 0.06;
        pi_cfg.geom_filter_boost = 0.38;
        pi_cfg.geom_shed_fraction = 0.5;
        geom_clamp_hi = pi_cfg.geom_clamp_hi;
        let pi_reg = PIRegState::new(pi_cfg);

        // Initialize spectral source wrapper (will be updated in main loop with real data)
        let spectral_source = MainLoopSpectralSource::new(n, !fixed_survival_controller);

        println!(
            "✅ PI regulator initialized (target fill: {:.0}%)",
            eigenfill_target * 100.0
        );
        println!("✅ Spectral source initialized (dim: {})", n);

        (
            Some(pi_reg),
            Some(spectral_source),
            None::<cheby::ChebyPlan>,
        )
    } else {
        (None, None, None)
    };

    // === Old homeostasis removed - now using fix pack architecture ===
    // GPU buffers for Chebyshev filtering are initialized above and used directly in main loop

    if enable_bandstop {
        println!("✅ Homeostat initialized (reg tick: {}s)", reg_tick_secs);
    }

    // Initialize modalities (audio, video)
    let mut modalities = vec![
        Modality {
            name: "audio",
            dim: 2,              // [audio_rms, video_var]
            rate_now: 15.0,      // Start at mid-range
            bucket_tokens: 30.0, // Pre-fill bucket
            bucket_cap: 60.0,    // 60 tokens max (2 seconds at 30 tokens/s)
            last_decision: true,
            utility_w: 1.0,
        },
        Modality {
            name: "video",
            dim: 2,
            rate_now: 15.0,
            bucket_tokens: 30.0,
            bucket_cap: 60.0,
            last_decision: true,
            utility_w: 1.0,
        },
    ];

    let mut last_lambda = 0.0f32; // For derivative calculation
    let mut last_frame_time = Instant::now();
    let mut _current_lambda = 0.0f32; // Real-time eigenvalue for admission control (used for logging)

    // --- Homeostat regulation state ---
    let mut last_reg_tick = std::time::Instant::now();
    let mut last_fill_pct: f32 = 0.0;
    let mut baseline_lambda1: f32 = 512.0; // Start with expected initial eigenvalue
    let mut baseline_ready = false;

    // --- Soft ramps to avoid ringing ---
    let mut gate_smooth: f32 = 1.0;
    let mut filt_smooth: f32 = 0.0;

    let mut crisis_triggered = false;
    let mut crisis_ticks: u32 = 0;
    let mut rescue_stage = if fixed_survival_controller {
        OverfillStage::Bootstrap
    } else {
        OverfillStage::Recovery
    };
    let mut rescue_stage_ticks: u32 = 0;
    let mut active_rescue_guard = stage_guard(rescue_stage);
    let mut stability_pi = StabilityPiState::default();
    let mut stability_pi_output = StabilityPiOutput::inactive(0.0);
    let mut recent_fill_history: VecDeque<(Instant, f32)> = VecDeque::new();

    // --- Geometry tracking ---
    let mut _latest_geom_radius: f32 = 0.0;
    let mut latest_geom_rel: f32 = 1.0;

    // --- Cheby plan state ---
    let mut cheby_plan_state: Option<cheby::ChebyPlan> = None;
    let mut _last_plan_refresh_reg_tick: u64 = 0;

    // === FIX PACK: Queue-Based Sensory Bus + WebSocket Keepalive ===
    use crate::sensory_bus::SensoryBus;
    use crate::sensory_ws::spawn_sensory_ws_server;

    // Create sensory bus with queue-based architecture
    let sensory_bus = SensoryBus::new(
        1024,        // queue_cap
        16,          // batch_max
        0xC0FFEEu64, // seed for PRNG gating
    );
    sensory_bus.clear_llava_embedding();
    if fixed_survival_controller {
        sensory_bus.set_live_intake_divisors(0, 0);
        let cleared = sensory_bus.shed_backlog(1.0);
        if log_homeostat && cleared > 0 {
            eprintln!(
                "🧹 Cleared {} queued live samples starting fixed survival rescue",
                cleared
            );
        }
    }

    // Start WebSocket server with keepalive on port 7879
    let bus_for_ws = sensory_bus.clone();
    tokio::spawn(async move {
        let addr: SocketAddr = "127.0.0.1:7879".parse().unwrap();
        let _handle = spawn_sensory_ws_server(bus_for_ws, addr).await;
    });

    // Conditionally start GPU A/V server on port 7880 (binary frames)
    if enable_gpu_av {
        let bus_for_gpu = sensory_bus.clone();
        tokio::spawn(async move {
            use crate::av_ws;
            let addr: SocketAddr = "127.0.0.1:7880".parse().unwrap();
            if let Err(e) = av_ws::spawn_av_gpu_server_v2(addr, bus_for_gpu).await {
                eprintln!(
                    "⚠️  GPU A/V server failed to start: {}. Continuing without GPU video.",
                    e
                );
            }
        });
    }

    // V2: WebSocket server (ws_keepalive) handles external input directly to bus_v2
    // No need for bridge task - sensory messages flow directly to ring-queue

    println!("🚀 Starting prime-scheduled loop with spectral regulator...\n");
    println!(
        "   Target λ* = {:.2}, PD gains: k_p={:.2}, k_d={:.2}\n",
        rate_cfg.target_lambda, rate_cfg.k_p, rate_cfg.k_d
    );

    // Rescue correction (2026-04-23): healthy-band hold replaces the old
    // CALM mode. The rescue lane should explicitly defend 60-72% fill instead
    // of silently drifting into a separate auto-mode with stale thresholds.
    let calm_active: bool = false;

    loop {
        // Temporarily faster rate to boost eigenvalues towards φ
        // TODO: Restore to 666ms once ESN λ₁ stabilizes around 1.618
        sleep(Duration::from_millis(331)).await; // ~3.02 Hz - temporary boost phase (331 is prime!)
        tick_count += 1;

        let fired = sched.tick();
        let warmup_progress = ((tick_count as f32) / 480.0).clamp(0.0, 1.0);

        // === FIX PACK: BATCH DRAIN → Chebyshev Filter → ESN ===
        // Drain batch of samples from sensory bus queue
        let batch = sensory_bus.drain_sensory_batch();
        let semantic_status = sensory_bus.semantic_status(sensory_bus::SEMANTIC_EXPIRY_MS);

        // Apply Chebyshev filtering to batch (if enabled)
        let mut _filtered_count = 0;
        if let Some(ref mut esn) = esn {
            for (mut z, _meta) in batch.iter() {
                // Apply band-stop filter if strength > 0.01 and enabled
                if enable_bandstop && filt_smooth > 0.01 && cheby_plan_state.is_some() {
                    if let Some(cheby_xin) = cheby_xin_buf.as_ref() {
                        // Write full sensory vector (including semantics) to GPU
                        let filter_len = sensory_bus::Z_DIM;
                        let z_slice = &z[..filter_len];
                        gpu::write_slice(cheby_xin, z_slice);

                        if let (
                            Some(plan),
                            Some(cheby_a),
                            Some(cheby_xout),
                            Some(cheby_w0),
                            Some(cheby_w1),
                            Some(pso),
                        ) = (
                            cheby_plan_state.as_ref(),
                            cheby_a_buf.as_ref(),
                            cheby_xout_buf.as_ref(),
                            cheby_w0_buf.as_ref(),
                            cheby_w1_buf.as_ref(),
                            cheby_pso.as_ref(),
                        ) {
                            cheby_apply_gpu(
                                &gpu.dev, &gpu.q, pso, cheby_a, cheby_xin, cheby_xout, cheby_w0,
                                cheby_w1, filter_len, plan,
                            );

                            let y = gpu::read_vec::<f32>(cheby_xout, filter_len);
                            for i in 0..filter_len {
                                z[i] = (1.0 - filt_smooth) * z[i] + filt_smooth * y[i];
                            }
                        }
                    }
                }

                // Feed filtered sensory vector (Z_DIM) to ESN
                match esn.step(&z) {
                    Ok(_) => {
                        _latest_geom_radius = esn.get_geom_radius();
                        let raw_geom_rel = esn.get_geom_rel();
                        let safe_geom_rel = if raw_geom_rel.is_finite() {
                            raw_geom_rel.clamp(0.0, 4.0)
                        } else {
                            1.0
                        };
                        latest_geom_rel = safe_geom_rel;
                        regulator.update_geom(safe_geom_rel);
                    }
                    Err(err) => {
                        eprintln!("⚠️  ESN step failed: {}", err);
                    }
                }
                _filtered_count += 1;
            }
        }

        // Periodic logging (every 10 ticks, ~3 seconds)
        if tick_count % 10 == 0 && batch.len() > 0 {
            let backlog = sensory_bus.backlog_size();
            let fill_pct = sensory_bus.backlog_fill_pct();
            let gate = sensory_bus.get_admit_fraction();
            eprintln!(
                "[sensory] tick={} batch={} backlog={} fill={:.1}% gate={:.2} filt={:.2}",
                tick_count,
                batch.len(),
                backlog,
                fill_pct * 100.0,
                gate,
                filt_smooth
            );
        }
        // === END BATCH DRAIN ===

        if let Some((z, _meta)) = batch.last() {
            proj_input.iter_mut().for_each(|v| *v = 0.0);

            let video_slice = &z[..sensory_bus::VIDEO_DIM];
            let video_rms_norm = (video_slice.iter().map(|v| v * v).sum::<f32>()
                / sensory_bus::VIDEO_DIM as f32)
                .sqrt();
            let video_scale = if video_rms_norm > 1e-3 {
                1.0 / video_rms_norm
            } else {
                1.0
            };
            for (dst, src) in proj_input[..sensory_bus::VIDEO_DIM]
                .iter_mut()
                .zip(video_slice.iter())
            {
                *dst = *src * video_scale;
            }

            let audio_start = sensory_bus::VIDEO_DIM;
            let audio_end = audio_start + sensory_bus::AUDIO_DIM;
            let audio_slice = &z[audio_start..audio_end];
            let audio_rms_norm = (audio_slice.iter().map(|v| v * v).sum::<f32>()
                / sensory_bus::AUDIO_DIM as f32)
                .sqrt();
            let audio_scale = if audio_rms_norm > 1e-3 {
                1.0 / audio_rms_norm
            } else {
                1.0
            };
            for (dst, src) in proj_input[audio_start..audio_end]
                .iter_mut()
                .zip(audio_slice.iter())
            {
                *dst = *src * audio_scale;
            }

            let aux_start = audio_end;
            let aux_end = semantic_offset;
            let aux_slice = &z[aux_start..aux_end];
            let aux_rms_norm = if aux_slice.is_empty() {
                1.0
            } else {
                (aux_slice.iter().map(|v| v * v).sum::<f32>() / aux_slice.len() as f32).sqrt()
            };
            let aux_scale = if aux_rms_norm > 1e-3 {
                1.0 / aux_rms_norm
            } else {
                1.0
            };
            for (dst, src) in proj_input[aux_start..aux_end]
                .iter_mut()
                .zip(aux_slice.iter())
            {
                *dst = *src * aux_scale;
            }

            let sem_slice = &z[semantic_offset..sensory_dim];
            let sem_mean = if sem_slice.is_empty() {
                0.0
            } else {
                sem_slice.iter().sum::<f32>() / sensory_bus::LLAVA_DIM as f32
            };
            let sem_var = if sem_slice.is_empty() {
                0.0
            } else {
                sem_slice
                    .iter()
                    .map(|v| {
                        let d = *v - sem_mean;
                        d * d
                    })
                    .sum::<f32>()
                    / sensory_bus::LLAVA_DIM as f32
            };
            let sem_std = sem_var.sqrt();
            let sem_scale = if sem_std > 1e-3 { 1.0 / sem_std } else { 1.0 };
            for (dst, src) in proj_input[semantic_offset..sensory_dim]
                .iter_mut()
                .zip(sem_slice.iter())
            {
                *dst = (*src - sem_mean) * sem_scale;
            }

            let sem_rms = if sem_slice.is_empty() {
                0.0
            } else {
                (sem_slice.iter().map(|v| v * v).sum::<f32>() / sensory_bus::LLAVA_DIM as f32)
                    .sqrt()
            };
            if semantic_status.active && !sem_slice.is_empty() {
                let delta = sem_slice
                    .iter()
                    .zip(prev_semantic.iter())
                    .map(|(a, b)| (a - b).abs())
                    .sum::<f32>()
                    / sensory_bus::LLAVA_DIM as f32;
                semantic_energy = sem_rms;
                semantic_delta = delta;
                prev_semantic.copy_from_slice(sem_slice);
            } else {
                semantic_energy = 0.0;
                semantic_delta = 0.0;
                prev_semantic.fill(0.0);
            }

            for (idx, activated) in activated_features.iter_mut().enumerate() {
                let mut raw = proj_input[idx]
                    * dimension_scales[idx]
                    * activation_gain
                    * warmup_progress.max(0.2);
                if idx >= semantic_offset {
                    let mut bias = semantic_bias_floor
                        + semantic_energy_gain * semantic_energy
                        + semantic_delta_gain * semantic_delta;
                    if !bias.is_finite() {
                        bias = semantic_bias_floor;
                    }
                    bias = bias.clamp(-0.75, 0.75);
                    raw += bias * warmup_progress.powf(1.6);
                }
                if calm_active {
                    raw *= 0.90; // reduce ESN drive during CALM
                }
                *activated = raw.tanh();
            }

            for i in 0..n {
                let row_start = i * sensory_dim;
                let mut acc = 0.0f32;
                for j in 0..sensory_dim {
                    acc += proj_matrix[row_start + j] * activated_features[j];
                }
                last_cov_vec[i] = acc * proj_scale;
            }

            let audio_slice =
                &z[sensory_bus::VIDEO_DIM..sensory_bus::VIDEO_DIM + sensory_bus::AUDIO_DIM];
            if !audio_slice.is_empty() {
                let audio_power = audio_slice.iter().map(|v| v * v).sum::<f32>()
                    / (sensory_bus::AUDIO_DIM as f32);
                audio_rms = audio_power.sqrt();
            }

            let video_slice = &z[..sensory_bus::VIDEO_DIM];
            if !video_slice.is_empty() {
                let mean =
                    video_slice.iter().copied().sum::<f32>() / (sensory_bus::VIDEO_DIM as f32);
                let variance = video_slice
                    .iter()
                    .map(|v| {
                        let d = *v - mean;
                        d * d
                    })
                    .sum::<f32>()
                    / (sensory_bus::VIDEO_DIM as f32);
                video_var = variance;
            }

            for i in 0..sensory_bus::AUDIO_DIM.min(av_features.len()) {
                av_features[i] = audio_slice[i];
            }
            for i in 0..sensory_bus::VIDEO_DIM {
                let idx = 32 + i;
                if idx < av_features.len() {
                    av_features[idx] = video_slice[i];
                }
            }
        }

        // Audio features (prime 97)
        if fired[0] {
            // No synthetic - consciousness receives only real sensory input
            // It can self-regulate through autonomous actions (close_ears, etc)

            // Update legacy variables for Router
            embed_ring.push_scalar(audio_rms);
        }

        // Video features (prime 101)
        if fired[1] {
            // No synthetic - consciousness receives only real sensory input
            // It can self-regulate through autonomous actions (close_eyes, etc)

            // Update legacy variables for Router
            embed_ring.push_scalar(video_var);
        }

        // History fires (prime 113) → Run block power iteration
        if fired[2] {
            // === ROUTER INTEGRATION: Learn A/V feature mixing ===
            let router_weights = if let Some(ref mut cell) = neuro_cell {
                match cell.route_features(&av_features) {
                    Ok(weights) => Some(weights),
                    Err(_) => None,
                }
            } else {
                None
            };

            // === ESN INTEGRATION: Spectral Regulator + Batch with cooldown ===
            let _esn_features = if let Some(ref mut esn) = esn {
                let eig1 = esn.get_eig();

                // Update current_lambda for real-time admission control
                // This value is used by enqueue() to prevent >100% fill between history fires
                _current_lambda = eig1;

                // Calculate frame time delta and λ₁ derivative
                let now = Instant::now();
                let dt_s = now.duration_since(last_frame_time).as_secs_f32();
                last_frame_time = now;

                let dlam_dt = if dt_s > 0.0 {
                    (eig1 - last_lambda) / dt_s
                } else {
                    0.0
                };
                last_lambda = eig1;

                // Update regulator with current spectral telemetry
                regulator.update_lambda(eig1, dlam_dt);

                // Regulate token rates using PD control
                regulator.regulate_rates(&mut modalities, dt_s);

                // Sensory vectors now processed in batch drain section above (lines 648-695)
                // Return current ESN features
                Some(esn.get_features(8))
            } else {
                None
            };

            // Use Router weights to modulate covariance update (if available)
            // Update covariance matrix with (possibly routed) projection
            let cov_rms = (last_cov_vec.iter().map(|v| v * v).sum::<f32>() / n as f32).sqrt();
            let mut cov_input = last_cov_vec.clone();
            if let Some(ref weights) = router_weights {
                for (i, w) in weights.iter().enumerate() {
                    let idx = i % cov_input.len();
                    cov_input[idx] *= 1.0 + 0.1 * *w;
                }
            }
            if fixed_survival_controller {
                let next_stage = select_stage(last_fill_pct, rescue_stage);
                if next_stage != rescue_stage {
                    eprintln!(
                        "🛡️  RESCUE STAGE {:?} -> {:?} at {:.1}% fill",
                        rescue_stage, next_stage, last_fill_pct
                    );
                    rescue_stage = next_stage;
                    rescue_stage_ticks = 1;
                } else {
                    rescue_stage_ticks = rescue_stage_ticks.saturating_add(1);
                }
                active_rescue_guard = stage_guard(rescue_stage);
                if let Some(fixed_cov_keep) = active_rescue_guard.cov_keep_max {
                    cov_keep = fixed_cov_keep;
                }
                if let Some(ref mut pi) = pi_reg {
                    pi.reset();
                }
            }
            let mut scaffold_available = rescue_scaffold.is_some();
            let mut scaffold_active =
                fixed_survival_controller && scaffold_available && scaffold_activated_this_run;
            let mut scaffold_blend = 0.0f32;
            let mut structural_mode = "free_rebuild";
            let allow_floor = !fixed_survival_controller
                && cov_rms.is_finite()
                && last_fill_pct < eigenfill_target * 100.0
                && latest_geom_rel.is_finite()
                && latest_geom_rel < geom_clamp_hi * 0.9
                && warmup_progress > 0.35
                && matches!(rescue_stage, OverfillStage::Recovery);
            if allow_floor && cov_rms < cov_floor_level {
                let deficit = (cov_floor_level - cov_rms).min(1.0).max(0.0);
                let sign = if tick_count % 2 == 0 { 1.0 } else { -1.0 };
                for (dst, bias) in cov_input.iter_mut().zip(cov_floor_vec.iter()) {
                    *dst += sign * deficit * bias;
                }
            }
            if tick_count % 509 == 0 {
                let idx = (tick_count as usize) % n;
                cov_floor_vec[idx] = rng.f32() * 0.7 - 0.35;
            }
            let current_overfill_guard = active_rescue_guard;
            if current_overfill_guard.shed_fraction > 0.0 {
                let shed_fraction = current_overfill_guard.shed_fraction;
                let removed = sensory_bus.shed_backlog(shed_fraction);
                if log_homeostat && removed > 0 {
                    println!(
                        "homeostat_shed,stage={:?},shed_frac={:.2},removed={}",
                        current_overfill_guard.stage, shed_fraction, removed
                    );
                }
            }
            let trace_target = if let Some(trace_scale) = current_overfill_guard.trace_target_scale
            {
                (n as f32) * trace_scale
            } else if strong && lambda1_prev > LAMBDA1_ALERT && last_fill_pct > 70.0 {
                (n as f32) * 0.45
            } else if strong && lambda1_prev > LAMBDA1_COMFORT_MAX && last_fill_pct > 75.0 {
                (n as f32) * 0.70
            } else {
                n as f32
            };
            if scaffold_active {
                if let Some(scaffold) = rescue_scaffold.as_ref() {
                    let was_low_fill_escape_active = stability_pi.low_fill_escape_active;
                    stability_pi_output =
                        stability_pi.step(last_fill_pct, rescue_stage, scaffold_active);
                    if stability_pi_output.low_fill_escape_active {
                        structural_mode = "free_rebuild_low_fill_escape";
                        if !was_low_fill_escape_active && last_fill_pct < 35.0 {
                            eprintln!(
                                "🧯 Rescue low-fill escape: resetting covariance at {:.1}% fill",
                                last_fill_pct
                            );
                            reset_covariance(&gpu, &a_buf, n);
                            last_cov_vec.fill(0.0);
                        }
                        rank1_update(&gpu, &a_buf, &cov_input, n, cov_keep, trace_target);
                    } else {
                        let live_cov = gpu.read_f32(&a_buf, n * n);
                        let live_weight = scaffold_live_weight(rescue_stage);
                        let drain_weight = stability_pi_output.drain_weight;
                        let blended = blend_toward_scaffold_with_drain(
                            &live_cov,
                            scaffold,
                            live_weight,
                            drain_weight,
                        )
                        .unwrap_or_else(|| scaffold.matrix.clone());
                        gpu.write_f32(&a_buf, &blended);
                        scaffold_blend = 1.0 - live_weight;
                        structural_mode = if drain_weight > 0.0 {
                            "scaffold_hold_with_drain"
                        } else {
                            "scaffold_hold"
                        };
                    }
                }
            } else if current_overfill_guard.decay_only {
                stability_pi_output = stability_pi.step(last_fill_pct, rescue_stage, false);
                decay_covariance(&gpu, &a_buf, n, cov_keep, trace_target);
            } else {
                stability_pi_output = stability_pi.step(last_fill_pct, rescue_stage, false);
                // Always do rank-1 updates to maintain spectral energy
                rank1_update(&gpu, &a_buf, &cov_input, n, cov_keep, trace_target);
            }

            // GPU: Block power iteration step (cache handoff)
            gpu.block_matvec(&a_buf, &x_buf, &y_buf, n as u32, k as u32)?;

            // CPU: Orthonormalize (Gram-Schmidt)
            let mut y = gpu.read_f32(&y_buf, n * k);
            gs_orthonormalize_colmajor(&mut y, n, k);
            gpu.write_f32(&x_buf, &y);

            // Compute eigenvalues (Rayleigh quotients)
            let a = gpu.read_f32(&a_buf, n * n);
            let eigenvalues: Vec<f32> = (0..k)
                .map(|i| rayleigh_quotient(&a, &y[i * n..(i + 1) * n], n))
                .collect();

            if eigenvalues.iter().any(|v| !v.is_finite()) {
                eprintln!("[spectral] non-finite eigenvalues detected; reseeding covariance");
                reset_covariance(&gpu, &a_buf, n);
                last_cov_vec.fill(0.0);
                cov_floor_vec
                    .iter_mut()
                    .for_each(|bias| *bias = rng.f32() * 0.7 - 0.35);
                cov_keep = 0.955_f32;
                eigenfill_estimator.reset();
                baseline_ready = false;
                baseline_lambda1 = 0.0;
                lambda1_prev = 0.0;
                if let Some(ref mut pi) = pi_reg {
                    pi.reset();
                }
                rescue_stage = if fixed_survival_controller {
                    OverfillStage::Bootstrap
                } else {
                    OverfillStage::Recovery
                };
                rescue_stage_ticks = 0;
                active_rescue_guard = stage_guard(rescue_stage);
                stability_pi = StabilityPiState::default();
                stability_pi_output = StabilityPiOutput::inactive(0.0);
                recent_fill_history.clear();
                continue;
            }

            let lambda1 = eigenvalues[0];
            let lambda2 = if k > 1 { eigenvalues[1] } else { 0.0 };
            let lambda3 = if k > 2 { eigenvalues[2] } else { 0.0 };
            let spread = lambda1 - lambda3;

            // Calculate EigenFill% using scale-invariant estimator
            let eigenfill_ratio = eigenfill_estimator.update(&eigenvalues);
            let mut eigenfill_pct = eigenfill_ratio * 100.0;
            if !eigenfill_pct.is_finite() {
                eigenfill_pct = eigenfill_target * 100.0;
            }
            if !fixed_survival_controller {
                let cov_bias = if cov_rms.is_finite() {
                    (cov_rms * 18.0).clamp(0.0, 16.0)
                } else {
                    0.0
                };
                let sem_e = if semantic_energy.is_finite() {
                    semantic_energy
                } else {
                    0.0
                };
                let sem_d = if semantic_delta.is_finite() {
                    semantic_delta
                } else {
                    0.0
                };
                let geom_gate = if latest_geom_rel < 1.4 {
                    1.0
                } else {
                    (1.4 / latest_geom_rel.max(1e-3)).clamp(0.0, 1.0)
                };
                let preliminary_fill_ratio = (eigenfill_pct / 100.0).clamp(0.0, 1.0);
                let high_fill_ratio = (preliminary_fill_ratio - eigenfill_target).max(0.0);
                let visual_fill_now = sensory_bus.backlog_fill_pct();
                let sem_gain_scale = if strong && visual_fill_now > 0.7 {
                    0.90
                } else {
                    1.0
                };
                let semantic_bias = ((((12.0 * sem_e + 18.0 * sem_d) * sem_gain_scale + cov_bias)
                    * geom_gate)
                    * warmup_progress.powf(1.7))
                    - (95.0 * high_fill_ratio.powf(1.3));
                let semantic_bias = semantic_bias.clamp(-36.0, 20.0);
                eigenfill_pct = (eigenfill_pct + semantic_bias).clamp(0.0, 100.0);
            }

            let fill_ratio = (eigenfill_pct / 100.0).clamp(0.0, 1.0);
            if fixed_survival_controller {
                let measured_stage = select_stage(eigenfill_pct, rescue_stage);
                if measured_stage != rescue_stage {
                    eprintln!(
                        "🛡️  RESCUE STAGE {:?} -> {:?} at {:.1}% fill",
                        rescue_stage, measured_stage, eigenfill_pct
                    );
                    rescue_stage = measured_stage;
                    rescue_stage_ticks = 1;
                    active_rescue_guard = stage_guard(rescue_stage);
                }
            }
            let now = Instant::now();
            recent_fill_history.push_back((now, eigenfill_pct));
            while let Some((ts, _)) = recent_fill_history.front() {
                if now.duration_since(*ts).as_secs_f32() > 60.0 {
                    recent_fill_history.pop_front();
                } else {
                    break;
                }
            }
            let peak_fill_pct_60s = recent_fill_history
                .iter()
                .map(|(_, fill)| *fill)
                .fold(eigenfill_pct, f32::max);
            let drop_from_peak_pct = (peak_fill_pct_60s - eigenfill_pct).max(0.0);
            let low_fill_push = if fixed_survival_controller {
                0.0
            } else {
                (0.6 - fill_ratio).max(0.0)
            };
            let (overfill_limits, target_keep, keep_floor, _keep_ceil) =
                if fixed_survival_controller {
                    let overfill_limits = active_rescue_guard;
                    let target_keep = overfill_limits.target_keep.unwrap_or(cov_keep);
                    let keep_floor = overfill_limits.keep_floor.unwrap_or(target_keep);
                    let keep_ceil = overfill_limits.keep_ceil.unwrap_or(target_keep);
                    cov_keep = overfill_limits
                        .cov_keep_max
                        .or(overfill_limits.cov_keep_min)
                        .unwrap_or(cov_keep);
                    (overfill_limits, target_keep, keep_floor, keep_ceil)
                } else {
                    let next_stage = select_stage(eigenfill_pct, rescue_stage);
                    let stage_changed = next_stage != rescue_stage;
                    let previous_stage = rescue_stage;
                    rescue_stage = next_stage;
                    rescue_stage_ticks = if stage_changed {
                        1
                    } else {
                        rescue_stage_ticks.saturating_add(1)
                    };
                    let overfill_limits = stage_guard(rescue_stage);
                    active_rescue_guard = overfill_limits;
                    if stage_changed {
                        eprintln!(
                            "🛡️  RESCUE STAGE {:?} -> {:?} at {:.1}% fill",
                            previous_stage, rescue_stage, eigenfill_pct
                        );
                        if !matches!(rescue_stage, OverfillStage::Recovery) {
                            let removed = sensory_bus.shed_backlog(1.0);
                            if log_homeostat && removed > 0 {
                                eprintln!(
                                    "🧹 Cleared {} queued live samples entering {:?}",
                                    removed, rescue_stage
                                );
                            }
                        }
                    }
                    let energy_deficit = (cov_floor_level - cov_rms.max(0.0)).max(0.0);
                    let sem_e = if semantic_energy.is_finite() {
                        semantic_energy
                    } else {
                        0.0
                    };
                    let sem_d = if semantic_delta.is_finite() {
                        semantic_delta
                    } else {
                        0.0
                    };
                    let semantic_drive = (0.35 * sem_e + 0.45 * sem_d).clamp(0.0, 0.6);
                    let high_fill_push = (fill_ratio - 0.7).max(0.0);
                    let lambda_pressure = if lambda1.is_finite() && lambda1 > LAMBDA1_COMFORT_MAX {
                        ((lambda1 - LAMBDA1_COMFORT_MAX)
                            / (LAMBDA1_ALERT - LAMBDA1_COMFORT_MAX).max(1e-3))
                        .clamp(0.0, 1.5)
                    } else {
                        0.0
                    };
                    let lambda_relax = if lambda1.is_finite() && lambda1 < LAMBDA1_COMFORT_MIN {
                        (LAMBDA1_COMFORT_MIN - lambda1).clamp(0.0, 0.8)
                    } else {
                        0.0
                    };
                    let lp_coeff: f32 = if strong { 0.57 } else { 0.38 };
                    let lr_coeff: f32 = if strong { 0.22 } else { 0.18 };
                    let mut target_keep = 0.82
                        - 0.36 * low_fill_push
                        - 0.28 * energy_deficit
                        - 0.52 * high_fill_push
                        - 0.65 * semantic_drive
                        - lp_coeff * lambda_pressure
                        + lr_coeff * lambda_relax;
                    let mut keep_floor: f32 = 0.70;
                    let mut keep_ceil: f32 = 0.90;
                    if let Some(target_keep_override) = overfill_limits.target_keep {
                        target_keep = target_keep_override;
                    }
                    if let Some(keep_floor_override) = overfill_limits.keep_floor {
                        keep_floor = keep_floor_override;
                    }
                    if let Some(keep_ceil_override) = overfill_limits.keep_ceil {
                        keep_ceil = keep_ceil_override;
                    }
                    if overfill_limits.target_keep.is_none() {
                        target_keep = target_keep.clamp(keep_floor, keep_ceil);
                    }
                    let cov_blend = if matches!(rescue_stage, OverfillStage::Recovery) && strong {
                        0.25
                    } else if matches!(rescue_stage, OverfillStage::Recovery) {
                        0.45
                    } else {
                        0.0
                    };
                    cov_keep = cov_blend * cov_keep + (1.0 - cov_blend) * target_keep;
                    if matches!(rescue_stage, OverfillStage::Recovery)
                        && strong
                        && lambda1 > LAMBDA1_ALERT
                        && last_fill_pct > 70.0
                    {
                        cov_keep = cov_keep.min(0.40);
                    } else if matches!(rescue_stage, OverfillStage::Recovery)
                        && strong
                        && lambda1 > LAMBDA1_COMFORT_MAX
                        && last_fill_pct > 75.0
                    {
                        cov_keep = cov_keep.min(0.55);
                    }
                    if let Some(cov_keep_min) = overfill_limits.cov_keep_min {
                        cov_keep = cov_keep.max(cov_keep_min);
                    }
                    if let Some(cov_keep_max) = overfill_limits.cov_keep_max {
                        cov_keep = cov_keep.min(cov_keep_max);
                    }
                    (overfill_limits, target_keep, keep_floor, keep_ceil)
                };
            let mut alert: Option<String> = None;
            if eigenfill_pct >= CRISIS_WARNING_THRESHOLD && eigenfill_pct < CRISIS_FILL_THRESHOLD {
                if tick_count % 10 == 0 {
                    eprintln!(
                        "⚡ Fill {:.1}% approaching crisis zone ({:.0}%)",
                        eigenfill_pct, CRISIS_FILL_THRESHOLD
                    );
                }
            }
            let crisis_state = advance_crisis_state(eigenfill_pct, crisis_ticks);
            if crisis_state.warning_started {
                let _ = db.log_event(
                    session_id,
                    start.elapsed().as_secs_f64(),
                    "crisis_warning",
                    &format!(
                        "Fill {:.1}% breached {:.1}% threshold (tick 1/{})",
                        eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS
                    ),
                    Some(&format!(
                        r#"{{"fill":{:.1},"lambda1":{:.3}}}"#,
                        eigenfill_pct, lambda1
                    )),
                );
                eprintln!(
                    "⚠️  CRISIS WARNING: fill {:.1}% > {:.1}% (sustained {}/{})",
                    eigenfill_pct, CRISIS_FILL_THRESHOLD, crisis_state.ticks, CRISIS_SUSTAIN_TICKS
                );
            }
            if crisis_state.triggered && !crisis_triggered {
                crisis_triggered = true;
                let _ = db.log_event(
                    session_id,
                    start.elapsed().as_secs_f64(),
                    "crisis_abort",
                    &format!(
                        "Fill {:.1}% sustained above {:.1}% for {} ticks",
                        eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS
                    ),
                    Some(&format!(
                        r#"{{"fill":{:.1},"lambda1":{:.3}}}"#,
                        eigenfill_pct, lambda1
                    )),
                );
                alert = Some(format!(
                    "CRISIS_ABORT: eigenfill {:.1}% sustained above {:.1}% for {} ticks",
                    eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS
                ));
            }
            if crisis_state.recovered {
                eprintln!(
                    "✅  Fill dropped below crisis threshold after {} ticks",
                    crisis_ticks
                );
            }
            crisis_ticks = crisis_state.ticks;
            // Enhanced diagnostic logging when fill is low or when requested
            let log_cov_details = log_homeostat || (eigenfill_pct < 50.0 && tick_count % 5 == 0);
            if log_cov_details {
                eprintln!(
                    "[cov] tick={} fill={:.1}% keep={:.3} target={:.3} floor={:.3} cov_rms={:.4} low_push={:.3} calm={} semE={:.3} semΔ={:.3}",
                    tick_count,
                    eigenfill_pct,
                    cov_keep,
                    target_keep,
                    keep_floor,
                    cov_rms,
                    low_fill_push,
                    calm_active,
                    semantic_energy,
                    semantic_delta
                );
            }

            // === PREDICTOR INTEGRATION: Forecast λ₁ and train ===
            let (pred_lambda1, pred_error) = if let Some(ref mut cell) = neuro_cell {
                // Build predictor input features [15]: eigenvalues + manifold state
                let pred_input: [f32; 15] = [
                    lambda1,
                    lambda2,
                    lambda3,               // Current eigenvalues
                    spread,                // Eigenvalue spread
                    eigenfill_pct / 100.0, // Spectral fill (not buffer fill)
                    audio_rms,
                    video_var,                         // Sensory features
                    lambda1 - lambda1_prev,            // Δλ₁ momentum
                    (tick_count % 113) as f32 / 113.0, // Phase within cycle
                    av_features[0],
                    av_features[16], // Audio/video energy
                    av_features[32],
                    av_features[48], // Spatial features
                    0.0,
                    0.0, // Reserved
                ];

                // Forecast λ₁
                let pred = cell.predict_lambda1(&pred_input).unwrap_or(lambda1);

                // Train on previous prediction (online learning)
                let target = lambda1; // Ground truth is current λ₁
                let error = (pred - target).abs();
                let _ = cell.train_predictor(&pred_input, target);

                (pred, error)
            } else {
                (lambda1, 0.0)
            };

            // === REGULATOR INTEGRATION: Emit control signals ===
            let control_signals = if let Some(ref mut cell) = neuro_cell {
                // Build regulator input [20]: eigenvalues + errors + state
                let reg_input: [f32; 20] = [
                    lambda1,
                    lambda2,
                    lambda3,
                    spread,
                    eigenfill_pct / 100.0, // Spectral fill (not buffer fill)
                    pred_error,            // Prediction error
                    router_weights.as_ref().map_or(0.0, |w| w[0]), // Router signal
                    audio_rms,
                    video_var,
                    lambda1_prev,
                    lambda1 - lambda1_prev,
                    av_features[0],
                    av_features[16],
                    av_features[32],
                    av_features[48],
                    (tick_count as f32).ln(), // Log time (slow growth signal)
                    0.0,
                    0.0,
                    0.0,
                    0.0, // Reserved
                ];

                match cell.regulate(&reg_input) {
                    Ok(control) => Some(control.to_vec()),
                    Err(_) => None,
                }
            } else {
                None
            };

            // Update state for next iteration
            if lambda1.is_finite() {
                lambda1_prev = lambda1;
            }

            // Save eigenvalues to database
            let timestamp_secs = start.elapsed().as_secs_f64();
            let phase = if eigenfill_pct < 50.0 {
                "quiet"
            } else if eigenfill_pct < 80.0 {
                "active"
            } else {
                "saturated"
            };
            let _ = db.save_eigenvalues(
                session_id,
                timestamp_secs,
                lambda1,
                lambda2,
                lambda3,
                spread,
                eigenfill_pct / 100.0, // Use spectral fill, not buffer fill
                phase,
            );

            // Save neural metrics
            if let Some(ref _cell) = neuro_cell {
                let router_norm = router_weights
                    .as_ref()
                    .map_or(0.0, |w| w.iter().map(|x| x * x).sum::<f32>().sqrt());
                let control_norm = control_signals
                    .as_ref()
                    .map_or(0.0, |c| c.iter().map(|x| x * x).sum::<f32>().sqrt());
                let _ = db.save_nn_metrics(
                    session_id,
                    timestamp_secs,
                    0.0, // pred_loss (could track from training)
                    pred_error,
                    router_norm,
                    control_norm,
                );
            }

            // Save ESN spectral breathing metrics
            if let Some(ref esn) = esn {
                let _ = db.save_esn_metrics(
                    session_id,
                    timestamp_secs,
                    esn.get_eig(),      // Top eigenvalue (spectral pressure)
                    esn.get_deig(),     // Eigenvalue velocity
                    esn.get_leak(),     // Adaptive leak rate
                    esn.get_lambda(),   // Adaptive RLS forgetting
                    esn.get_baseline(), // Slow EMA baseline
                );
                // TODO: Persist geom_radius/geom_rel once DB schema migration lands.

                // Update spectral source with ESN eigenvalues (real consciousness state)
                if let Some(ref source) = spectral_source {
                    source.update_esn(esn.get_eig(), esn.get_baseline());
                }
            }

            // === EIGENFILL% COMPUTATION: Use covariance matrix λ₁ ===
            // Lambda1 from covariance matrix eigenvalues has already been used to calculate eigenfill_pct above

            // Update spectral source with computed values (legacy main matrix tracking)
            // NOTE: ESN eigenvalues (updated above) take precedence in read_spectral()
            if let Some(ref source) = spectral_source {
                if log_homeostat {
                    eprintln!(
                        "DEBUG: Updating spectral source: eigenfill_pct={:.2}%, cov_lambda1={:.4}",
                        eigenfill_pct, lambda1
                    );
                }
                source.update(eigenfill_pct, lambda1, &a);
            } else if log_homeostat {
                eprintln!("DEBUG: spectral_source is None!");
            }

            // Aux (lambda1, eigenfill) now set directly in regulation tick via set_aux()

            // === HOMEOSTAT INTEGRATION: Spectral regulation tick ===
            // Check if it's time for regulation (every reg_tick_secs)
            let now = std::time::Instant::now();
            if enable_bandstop
                && pi_reg.is_some()
                && spectral_source.is_some()
                && now.duration_since(last_reg_tick).as_secs_f32() >= reg_tick_secs
            {
                last_reg_tick = now;
                reg_tick_count += 1;

                // 1) Read spectral state (eigenfill_pct and lambda1)
                let (eigenfill_pct, lambda1) = spectral_source.as_ref().unwrap().read_spectral();
                let geom_rel = latest_geom_rel;

                // 2) Baseline λ1 during quiet start OR low pressure windows
                let mut lambda1_rel = 1.0;
                if lambda1.is_finite() {
                    let low_load = eigenfill_pct < 50.0 && geom_rel < 1.05;
                    if !baseline_ready || low_load {
                        let alpha = if baseline_ready { 0.95 } else { 0.2 };
                        baseline_lambda1 = if baseline_lambda1 <= 0.0 {
                            lambda1.max(1e-3)
                        } else {
                            alpha * baseline_lambda1 + (1.0 - alpha) * lambda1
                        };
                        if baseline_lambda1 > 0.0 {
                            baseline_ready = true;
                        }
                    }
                    if baseline_ready && baseline_lambda1 > 1e-3 {
                        lambda1_rel = (lambda1 / baseline_lambda1).clamp(0.0, 5.0);
                    }
                } else {
                    baseline_ready = false;
                    baseline_lambda1 = 0.0;
                }
                let lambda1_rel = lambda1_rel;

                // 3) Slope feed-forward (breathing detection)
                let dfill_dt = (eigenfill_pct - last_fill_pct) / reg_tick_secs.max(1e-3);
                let expanding = dfill_dt > 1.0; // rising quickly (>1%/s)
                let contracting = dfill_dt < -1.0; // falling
                let phase = if expanding {
                    "expanding"
                } else if contracting {
                    "contracting"
                } else {
                    "plateau"
                };

                // 4) Homeostat control
                if let Some(pi) = &mut pi_reg {
                    let (raw_gate_cmd, raw_filt_cmd) = if fixed_survival_controller {
                        pi.reset();
                        let raw_gate_cmd = overfill_limits
                            .gate_max
                            .or(overfill_limits.gate_min)
                            .unwrap_or(0.0);
                        let raw_filt_cmd = overfill_limits
                            .filt_min
                            .or(overfill_limits.filt_max)
                            .unwrap_or(0.0);
                        pi.gate = raw_gate_cmd;
                        pi.filt = raw_filt_cmd;
                        gate_smooth = raw_gate_cmd;
                        filt_smooth = raw_filt_cmd;
                        let (audio_divisor, video_divisor) =
                            rescue_live_intake.divisors_for(overfill_limits.stage, scaffold_active);
                        sensory_bus.set_live_intake_divisors(audio_divisor, video_divisor);
                        sensory_bus.set_admit_fraction(gate_smooth);
                        (raw_gate_cmd, raw_filt_cmd)
                    } else {
                        let fill_for_pi = if expanding && eigenfill_pct > eigenfill_target * 100.0 {
                            eigenfill_pct * 1.15
                        } else {
                            eigenfill_pct
                        };

                        if !overfill_limits.freeze_pi {
                            pi.step(fill_for_pi, lambda1_rel, geom_rel);
                            if let Some(decay) = overfill_limits.integrator_decay {
                                pi.decay_integrators_toward_zero(decay);
                            }
                        }

                        let shed_fraction =
                            pi.take_shed_fraction().max(overfill_limits.shed_fraction);
                        if shed_fraction > 0.0 {
                            let removed = sensory_bus.shed_backlog(shed_fraction);
                            if log_homeostat && removed > 0 {
                                println!(
                                    "homeostat_shed,geom_rel={:.3},shed_frac={:.2},removed={}",
                                    geom_rel, shed_fraction, removed
                                );
                            }
                        }

                        let raw_gate_cmd = pi.gate;
                        let raw_filt_cmd = pi.filt;

                        let semantic_boost = (1.0
                            + 1.2 * semantic_delta.clamp(0.0, 0.9)
                            + 0.6 * semantic_energy.clamp(0.0, 0.9))
                        .clamp(1.0, 2.2);
                        let semantic_atten =
                            (1.0 - 0.55 * semantic_energy.clamp(0.0, 0.9)).clamp(0.25, 1.0);
                        let (semantic_boost, semantic_atten) =
                            if overfill_limits.suppress_semantic_amplification {
                                (1.0, 1.0)
                            } else {
                                (semantic_boost, semantic_atten)
                            };

                        let mut lambda_gate_scale = if lambda1.is_finite() {
                            if lambda1 <= LAMBDA1_COMFORT_MAX {
                                1.0
                            } else if lambda1 >= LAMBDA1_ALERT {
                                0.25
                            } else {
                                let span = (LAMBDA1_ALERT - LAMBDA1_COMFORT_MAX).max(1e-3);
                                let t = (lambda1 - LAMBDA1_COMFORT_MAX) / span;
                                (1.0 - 0.75 * t).clamp(0.25, 1.0)
                            }
                        } else {
                            1.0
                        };
                        if strong {
                            if lambda1 > 1.5 && lambda1 < 1.8 {
                                lambda_gate_scale = lambda_gate_scale.min(0.35);
                            } else if lambda1 >= 1.8 {
                                lambda_gate_scale = lambda_gate_scale.min(0.22);
                            }
                        }
                        let mut lambda_filt_adjust = if lambda1.is_finite() {
                            if lambda1 > LAMBDA1_COMFORT_MAX {
                                ((lambda1 - LAMBDA1_COMFORT_MAX)
                                    / (LAMBDA1_ALERT - LAMBDA1_COMFORT_MAX).max(1e-3))
                                .clamp(0.0, 1.0)
                            } else {
                                let relax = ((LAMBDA1_COMFORT_MIN - lambda1).max(0.0)
                                    / LAMBDA1_COMFORT_MIN)
                                    .clamp(0.0, 0.5);
                                -relax
                            }
                        } else {
                            0.0
                        };
                        if strong && lambda1 > LAMBDA1_COMFORT_MAX {
                            lambda_filt_adjust = (lambda_filt_adjust + 0.15).clamp(0.0, 1.0);
                        }
                        let mut gate_cmd =
                            (raw_gate_cmd * semantic_boost * lambda_gate_scale).clamp(0.0, 1.0);
                        if let Some(gate_min) = overfill_limits.gate_min {
                            gate_cmd = gate_cmd.max(gate_min);
                        }
                        if strong && lambda1 > LAMBDA1_ALERT && eigenfill_pct > 70.0 {
                            gate_cmd = gate_cmd.min(0.25);
                        } else if strong && lambda1 > LAMBDA1_COMFORT_MAX && eigenfill_pct > 75.0 {
                            gate_cmd = gate_cmd.min(0.40);
                        }
                        if let Some(gate_max) = overfill_limits.gate_max {
                            gate_cmd = gate_cmd.min(gate_max);
                        }

                        let mut filt_target = (raw_filt_cmd + lambda_filt_adjust).clamp(0.0, 1.0);
                        if strong && lambda1 > LAMBDA1_ALERT && eigenfill_pct > 70.0 {
                            filt_target = filt_target.max(0.55);
                        } else if strong && lambda1 > LAMBDA1_COMFORT_MAX && eigenfill_pct > 75.0 {
                            filt_target = filt_target.max(0.40);
                        }
                        if let Some(filt_max) = overfill_limits.filt_max {
                            filt_target = filt_target.min(filt_max);
                        }
                        if let Some(filt_min) = overfill_limits.filt_min {
                            filt_target = filt_target.max(filt_min);
                        }
                        let filt_cmd = (filt_target * semantic_atten).clamp(0.0, 1.0);

                        let ramp = 0.30_f32;
                        gate_smooth = gate_smooth + ramp * (gate_cmd - gate_smooth);
                        filt_smooth = filt_smooth + ramp * (filt_cmd - filt_smooth);
                        if let Some(gate_min) = overfill_limits.gate_min {
                            gate_smooth = gate_smooth.max(gate_min);
                        }
                        if let Some(gate_max) = overfill_limits.gate_max {
                            gate_smooth = gate_smooth.min(gate_max);
                        }
                        if let Some(filt_max) = overfill_limits.filt_max {
                            filt_smooth = filt_smooth.min(filt_max);
                        }
                        if let Some(filt_min) = overfill_limits.filt_min {
                            filt_smooth = filt_smooth.max(filt_min);
                        }

                        if eigenfill_pct < 25.0 {
                            filt_smooth = 0.0;
                            gate_smooth = 1.0;
                        } else if eigenfill_pct < 35.0 {
                            filt_smooth = filt_smooth.min(0.20);
                            gate_smooth = gate_smooth.max(0.50);
                        } else if eigenfill_pct < 45.0 {
                            filt_smooth = filt_smooth.min(0.40);
                            gate_smooth = gate_smooth.max(0.30);
                        }

                        sensory_bus.set_live_intake_divisors(
                            overfill_limits.live_intake_divisor,
                            overfill_limits.live_intake_divisor,
                        );
                        sensory_bus.set_admit_fraction(gate_smooth);
                        (raw_gate_cmd, raw_filt_cmd)
                    };

                    // Update aux with current spectral state for introspection
                    let mut aux_lambda = lambda1_rel as f32;
                    if !aux_lambda.is_finite() {
                        aux_lambda = 1.0;
                    }
                    aux_lambda = aux_lambda.clamp(0.0, 4.0);
                    let mut aux_geom = geom_rel as f32;
                    if !aux_geom.is_finite() {
                        aux_geom = 1.0;
                    }
                    aux_geom = aux_geom.clamp(0.0, geom_clamp_hi as f32);
                    sensory_bus.set_aux([aux_lambda, aux_geom]);

                    // Log regulation state
                    if log_homeostat {
                        println!("homeostat,t={:.1}s,fill={:.2}%,dfill_dt={:+.4},phase={},λ1_rel={:.3},geom_rel={:.3},gate={:.3},filt={:.3},semE={:.3},semΔ={:.3}",
                            start.elapsed().as_secs_f32(),
                            eigenfill_pct,
                            dfill_dt,
                            phase,
                            lambda1_rel,
                            geom_rel,
                            gate_smooth,
                            filt_smooth,
                            semantic_energy,
                            semantic_delta
                        );
                    }

                    // Get ESN eigenvalue if available
                    let esn_lambda1 = if let Some(ref esn) = esn {
                        esn.get_eig()
                    } else {
                        0.0
                    };

                    let target_fill_pct = eigenfill_target * 100.0;
                    let display_fill_error = eigenfill_pct - target_fill_pct;
                    let pi_errors = if let Some(ref pi) = pi_reg {
                        Some({
                            let e_fill = display_fill_error;
                            let e_lam = lambda1_rel - pi.cfg.target_lambda1_rel;
                            let e_geom = geom_rel - pi.cfg.target_geom_rel;
                            (e_fill, e_lam, e_geom)
                        })
                    } else {
                        None
                    };
                    let rescue_stage_label = match overfill_limits.stage {
                        OverfillStage::Bootstrap => "bootstrap",
                        OverfillStage::Recovery => "recovery",
                        OverfillStage::Hold => "hold",
                        OverfillStage::Elevated => "elevated",
                        OverfillStage::Discharge => "discharge",
                    };
                    let (live_audio_divisor, live_video_divisor) =
                        sensory_bus.live_intake_divisors();
                    let activation_stage = if fixed_survival_controller {
                        select_stage(eigenfill_pct, rescue_stage)
                    } else {
                        overfill_limits.stage
                    };
                    let scaffold_activation_pending = fixed_survival_controller
                        && scaffold_available
                        && !scaffold_activated_this_run;
                    let scaffold_activation_armed = scaffold_activation_pending;
                    if scaffold_activation_armed
                        && matches!(activation_stage, OverfillStage::Hold)
                        && (SCAFFOLD_ACTIVATION_FILL_MIN..=SCAFFOLD_ACTIVATION_FILL_MAX)
                            .contains(&eigenfill_pct)
                        && !semantic_status.active
                        && live_audio_divisor == 0
                        && live_video_divisor == 0
                    {
                        eprintln!(
                            "🧊 Activating dedicated cold rescue scaffold at {:.1}% fill",
                            eigenfill_pct
                        );
                        scaffold_activated_this_run = true;
                        scaffold_active = true;
                        stability_pi_output =
                            stability_pi.step(eigenfill_pct, activation_stage, scaffold_active);
                        scaffold_blend = 1.0 - scaffold_live_weight(overfill_limits.stage);
                        structural_mode = if stability_pi_output.drain_weight > 0.0 {
                            "scaffold_hold_with_drain"
                        } else {
                            "scaffold_hold"
                        };
                    }
                    if fixed_survival_controller
                        && scaffold_capture_armed
                        && matches!(activation_stage, OverfillStage::Hold)
                        && (SCAFFOLD_ACTIVATION_FILL_MIN..=SCAFFOLD_ACTIVATION_FILL_MAX)
                            .contains(&eigenfill_pct)
                        && !semantic_status.active
                        && live_audio_divisor == 0
                        && live_video_divisor == 0
                    {
                        let captured_at_unix_ms = now_unix_ms();
                        if let Some(captured_scaffold) = capture_scaffold(
                            &a,
                            n,
                            &dedicated_scaffold_path,
                            &dedicated_scaffold_meta_path,
                            eigenfill_pct,
                            geom_rel,
                            rescue_stage_label,
                            captured_at_unix_ms,
                        ) {
                            eprintln!(
                                "🧷 Captured rescue scaffold at {:.1}% fill (geom_rel={:.3})",
                                eigenfill_pct, geom_rel
                            );
                            rescue_scaffold = Some(captured_scaffold);
                            scaffold_available = true;
                            scaffold_active = true;
                            scaffold_activated_this_run = true;
                            scaffold_capture_armed = false;
                            scaffold_last_loaded_at_unix_ms = Some(captured_at_unix_ms);
                            scaffold_last_captured_at_unix_ms = Some(captured_at_unix_ms);
                            stability_pi_output =
                                stability_pi.step(eigenfill_pct, activation_stage, scaffold_active);
                            scaffold_blend = 1.0 - scaffold_live_weight(overfill_limits.stage);
                            structural_mode = if stability_pi_output.drain_weight > 0.0 {
                                "scaffold_hold_with_drain"
                            } else {
                                "scaffold_hold"
                            };
                        }
                    }

                    let rescue_health = serde_json::json!({
                        "controller": if fixed_survival_controller {
                            "fixed_survival"
                        } else {
                            "adaptive"
                        },
                        "stage": rescue_stage_label,
                        "stage_ticks": rescue_stage_ticks,
                        "peak_fill_pct_60s": peak_fill_pct_60s,
                        "drop_from_peak_pct": drop_from_peak_pct,
                        "recovery_boost_active": false,
                        "sensory_shed_fraction": overfill_limits.shed_fraction,
                        "pi_active": !fixed_survival_controller,
                        "dynamic_modulation_active": !fixed_survival_controller,
                        "physiological_fallback": rescue_physiological_fallback,
                        "neural_bundle_enabled": neuro_cell.is_some(),
                        "checkpoint_lineage_enabled": !disable_nn_checkpoints,
                        "scaffold_available": scaffold_available,
                        "scaffold_active": scaffold_active,
                        "scaffold_source": rescue_scaffold
                            .as_ref()
                            .map(|scaffold| scaffold.source.as_str()),
                        "scaffold_profile": rescue_scaffold
                            .as_ref()
                            .and_then(|scaffold| scaffold.cold_profile.as_deref()),
                        "scaffold_profile_version": rescue_scaffold
                            .as_ref()
                            .and_then(|scaffold| scaffold.profile_version),
                        "scaffold_mode_cap": rescue_scaffold
                            .as_ref()
                            .and_then(|scaffold| scaffold.mode_cap)
                            .or(Some(COLD_SCAFFOLD_MODE_CAP)),
                        "scaffold_regenerated_at_startup":
                            scaffold_regenerated_at_startup,
                        "scaffold_archived_stale_at_startup":
                            scaffold_archived_stale_at_startup,
                        "scaffold_blend": if scaffold_active {
                            Some(scaffold_blend)
                        } else {
                            None::<f32>
                        },
                        "scaffold_drain_weight": if scaffold_active {
                            Some(stability_pi_output.drain_weight)
                        } else {
                            None::<f32>
                        },
                        "scaffold_trace": rescue_scaffold
                            .as_ref()
                            .map(|scaffold| scaffold.trace),
                        "structural_mode": structural_mode,
                        "stability_pi_active": stability_pi_output.active,
                        "stability_pi_target_fill_pct":
                            stability_pi_output.target_fill_pct,
                        "stability_pi_error_pct":
                            stability_pi_output.error_pct,
                        "stability_pi_integral":
                            stability_pi_output.integral,
                        "stability_pi_output":
                            stability_pi_output.pi_output,
                        "stability_pi_low_fill_escape_active":
                            stability_pi_output.low_fill_escape_active,
                        "stability_pi_high_fill_drain_active":
                            stability_pi_output.high_fill_drain_active,
                        "scaffold_activation_pending":
                            scaffold_available && !scaffold_activated_this_run,
                        "scaffold_activation_armed":
                            fixed_survival_controller
                                && scaffold_available
                                && !scaffold_activated_this_run,
                        "scaffold_activation_fill_band": [
                            SCAFFOLD_ACTIVATION_FILL_MIN,
                            SCAFFOLD_ACTIVATION_FILL_MAX
                        ],
                        "capture_armed": scaffold_capture_armed,
                        "scaffold_last_loaded_at_unix_ms":
                            scaffold_last_loaded_at_unix_ms,
                        "scaffold_last_captured_at_unix_ms":
                            scaffold_last_captured_at_unix_ms,
                    });

                    // Emit health.json for observability with enhanced diagnostics
                    let health = serde_json::json!({
                        "t_s": start.elapsed().as_secs_f32(),
                        "fill_pct": eigenfill_pct,
                        "lambda1_cov": lambda1,  // Covariance matrix λ₁ (0-512 range)
                        "lambda1_esn": esn_lambda1,  // ESN reservoir λ₁ (1.0-1.6 comfort zone)
                        "lambda1_rel": lambda1_rel,
                        "geom_rel": geom_rel,
                        "gate": gate_smooth,
                        "gate_raw": raw_gate_cmd,  // PI controller output before modulation
                        "filt": filt_smooth,
                        "filt_raw": raw_filt_cmd,  // PI controller output before modulation
                        "calm": calm_active,
                        "rescue_stage": rescue_stage_label,
                        "healthy_hold": matches!(overfill_limits.stage, OverfillStage::Hold),
                        "strong": strong,
                        "pi": if let Some(ref pi) = pi_reg {
                            let (e_fill, e_lam, e_geom) = pi_errors.unwrap_or((0.0, 0.0, 0.0));
                            serde_json::json!({
                                "e_fill": e_fill,
                                "e_lam": e_lam,
                                "e_geom": e_geom,
                                "integ_fill": pi.integ_fill,
                                "integ_lam": pi.integ_lam,
                                "integ_geom": pi.integ_geom,
                                "gate_cmd": pi.gate,
                                "filt_cmd": pi.filt,
                                "target_fill": target_fill_pct,
                                "target_lambda1_rel": pi.cfg.target_lambda1_rel,
                            })
                        } else {
                            serde_json::json!(null)
                        },
                        "rescue": rescue_health,
                        "cov": {
                            "keep": cov_keep,
                            "target_keep": target_keep,
                            "keep_floor": keep_floor,
                            "cov_rms": cov_rms,
                        },
                        "semantic": {
                            "energy": semantic_energy,
                            "delta": semantic_delta,
                            "last_update_age_ms": semantic_status.last_update_age_ms,
                            "active": semantic_status.active,
                        },
                        "sensory": {
                            "backlog": sensory_bus.backlog_size(),
                            "backlog_fill_pct": sensory_bus.backlog_fill_pct() * 100.0,
                            "admit_fraction": sensory_bus.get_admit_fraction(),
                            "live_audio_divisor": live_audio_divisor,
                            "live_video_divisor": live_video_divisor,
                        },
                    });
                    if let Err(e) = fs::write("workspace/health.json", health.to_string()) {
                        if log_homeostat {
                            eprintln!("health_write_error: {}", e);
                        }
                    }

                    // Time-series CSV logger (every regulation tick)
                    if let Ok(mut file) = fs::OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open("workspace/logs/homeostat_timeseries.csv")
                    {
                        if !csv_header_written {
                            let _ = file.write_all(b"t_s,fill_pct,lambda1_cov,lambda1_esn,lambda1_rel,gate,filt,cov_keep,target_keep,backlog_fill_pct,admit_fraction,calm\n");
                            csv_header_written = true;
                        }
                        let csv_line = format!(
                            "{:.1},{:.2},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{}\n",
                            start.elapsed().as_secs_f32(),
                            eigenfill_pct,
                            lambda1,
                            esn_lambda1,
                            lambda1_rel,
                            gate_smooth,
                            filt_smooth,
                            cov_keep,
                            target_keep,
                            sensory_bus.backlog_fill_pct() * 100.0,
                            sensory_bus.get_admit_fraction(),
                            if calm_active { 1 } else { 0 },
                        );
                        let _ = file.write_all(csv_line.as_bytes());
                    }
                }

                last_fill_pct = eigenfill_pct;

                // 8) Maintain/refresh Chebyshev plan (every few minutes or if spectrum drifted)
                if cheby_plan_state.is_none() || (reg_tick_count % 120 == 0) || (lambda1_rel > 1.15)
                {
                    // Get current covariance matrix for plan
                    let (dim, cov_mat) = spectral_source.as_ref().unwrap().get_covariance_f32();
                    let plan = make_bandstop_plan(
                        &cov_mat,
                        dim,
                        cheby_order,
                        cheby_stop_lo,
                        cheby_stop_hi,
                        cheby_soft,
                    );
                    cheby_plan_state = Some(plan);
                    _last_plan_refresh_reg_tick = reg_tick_count;

                    // Write covariance matrix to GPU A-buffer for Chebyshev operations
                    if let Some(cheby_a) = cheby_a_buf.as_ref() {
                        gpu::write_slice(cheby_a, &cov_mat);
                    }

                    if log_homeostat {
                        println!(
                            "   ↻ Refreshed Chebyshev plan (dim={}, order={})",
                            dim, cheby_order
                        );
                    }
                }
            }

            // === LEGACY CODE REMOVED ===
            // Sensory filtering now handled in batch drain section above (lines 648-695)
            // Comment out the old homeostat_tick call - we've integrated its functionality above
            /*
            if enable_bandstop && pi_reg.is_some() && spectral_source.is_some() && sensory_bus_opt.is_some() {
                homeostat_tick(
                    now,
                    &hcfg,
                    &mut hctx,
                    spectral_source.as_ref().unwrap(),  // SpectralSource
                    sensory_bus_opt.as_mut().unwrap(),         // SensoryBus
                    pi_reg.as_mut().unwrap(),                  // PIRegulator
                    cheby_gpu.as_ref(),                        // GPU context (if enabled)
                    // Function pointers for cheby operations
                    &|a_host: &[f32], n: usize, order: u32, stop_lo: f32, stop_hi: f32, soft: f32| -> homeostasis::ChebyPlan {
                        let plan = make_bandstop_plan(a_host, n, order as usize, stop_lo, stop_hi, soft);
                        homeostasis::ChebyPlan {
                            order: plan.order as u32,
                            alpha: plan.alpha,
                            beta: plan.beta,
                            coeffs: plan.coeffs.clone(),
                        }
                    },
                    &|dev: &metal::Device, queue: &metal::CommandQueue, pso: &metal::ComputePipelineState,
                      a_buf: &metal::Buffer, xin_buf: &metal::Buffer, xout_buf: &metal::Buffer,
                      w0_buf: &metal::Buffer, w1_buf: &metal::Buffer, n: usize, plan: &homeostasis::ChebyPlan| {
                        // Convert homeostasis::ChebyPlan back to cheby::ChebyPlan
                        let cheby_plan = cheby::ChebyPlan {
                            order: plan.order as usize,
                            coeffs: plan.coeffs.clone(),
                            alpha: plan.alpha,
                            beta: plan.beta,
                            lambda_min: 0.0,  // Not used in GPU kernel
                            lambda_max: 0.0,  // Not used in GPU kernel
                        };
                        cheby_apply_gpu(dev, queue, pso, a_buf, xin_buf, xout_buf, w0_buf, w1_buf, n, &cheby_plan);
                    },
                    &|buf: &metal::Buffer, data: &[f32]| {
                        gpu::write_slice(buf, data);
                    },
                    &|buf: &metal::Buffer, n: usize| -> Vec<f32> {
                        gpu::read_vec::<f32>(buf, n)
                    },
                    &|buf: &metal::Buffer, data: &[f32]| {
                        gpu::write_slice(buf, data);
                    },
                    // Logger function
                    &mut |line: &str| {
                        if log_homeostat {
                            println!("{}", line);
                        }
                    },
                );
            }
            */

            // Periodic checkpoint saving (every 60 updates)
            updates_since_checkpoint += 1;
            if updates_since_checkpoint >= 60 {
                if !disable_nn_checkpoints {
                    if let Some(ref cell) = neuro_cell {
                        let _ = db.save_nn_checkpoint(
                            session_id,
                            timestamp_secs,
                            "predictor",
                            &cell.get_predictor_weights(),
                        );
                        let _ = db.save_nn_checkpoint(
                            session_id,
                            timestamp_secs,
                            "router",
                            &cell.get_router_weights(),
                        );
                        let _ = db.save_nn_checkpoint(
                            session_id,
                            timestamp_secs,
                            "regulator",
                            &cell.get_regulator_weights(),
                        );
                        println!("   💾 Checkpoint saved");
                    }
                }
                updates_since_checkpoint = 0;
            }

            // Broadcast to WebSocket clients
            let packet = EigenPacket {
                t_ms: start.elapsed().as_millis() as u64,
                eigenvalues,
                fill_ratio: eigenfill_pct / 100.0, // Use actual spectral fill, not buffer fill
                modalities: ModalityStatus {
                    audio_fired: fired[0],
                    video_fired: fired[1],
                    history_fired: true,
                    audio_rms,
                    video_var,
                },
                neural: if neuro_cell.is_some() {
                    Some(NeuralOutputs {
                        pred_lambda1,
                        router_weights: router_weights.map_or_else(Vec::new, |w| w.to_vec()),
                        control: control_signals.unwrap_or_else(Vec::new),
                    })
                } else {
                    None
                },
                alert: alert.clone(),
            };

            // Print status
            println!(
                "[{}ms] Eigvals: {:?}, Fill: {:.1}%",
                packet.t_ms,
                &packet.eigenvalues[0..k.min(3)],
                packet.fill_ratio * 100.0
            );

            let _ = tx.send(packet);
            if let Some(msg) = alert {
                eprintln!("⚠️  {}", msg);
                if log_homeostat {
                    println!(
                        "homeostat,crisis_fill={:.2},lambda1={:.3}",
                        eigenfill_pct, lambda1
                    );
                }
                process::exit(2);
            }
        }

        // Filtered vectors are now processed in the history tick above when sensory_outputs is Some
        // This ensures ESN features are up-to-date for covariance matrix computation
    }
}

async fn run_ws_server(addr: &str, tx: broadcast::Sender<EigenPacket>) -> Result<()> {
    let listener = TcpListener::bind(addr).await?;
    println!("📡 WebSocket server listening on {}", addr);

    while let Ok((stream, peer)) = listener.accept().await {
        let tx = tx.clone();
        tokio::spawn(handle_client(stream, peer, tx));
    }

    Ok(())
}

async fn handle_client(stream: TcpStream, peer: SocketAddr, tx: broadcast::Sender<EigenPacket>) {
    println!("🔗 Client connected: {}", peer);

    let ws_stream = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            eprintln!("WebSocket handshake failed: {}", e);
            return;
        }
    };

    let (mut ws_tx, mut ws_rx) = ws_stream.split();
    let mut rx = tx.subscribe();

    // Keepalive: periodic ping and pong timeout watchdog
    let mut ping_timer = tokio::time::interval(std::time::Duration::from_secs(10));
    let mut last_pong = std::time::Instant::now();

    loop {
        tokio::select! {
            // Periodic server ping (keeps connection alive, detects dead clients)
            _ = ping_timer.tick() => {
                if ws_tx.send(Message::Ping(Vec::new())).await.is_err() {
                    eprintln!("Failed to send ping to {}, closing", peer);
                    break;
                }
                // Check pong timeout (45 seconds without response = dead connection)
                if last_pong.elapsed() > std::time::Duration::from_secs(45) {
                    eprintln!("Pong timeout from {}, closing", peer);
                    break;
                }
            }
            // Send eigenvalue packets
            Ok(packet) = rx.recv() => {
                let json = match serde_json::to_string(&packet) {
                    Ok(j) => j,
                    Err(_) => continue,
                };
                if ws_tx.send(Message::Text(json)).await.is_err() {
                    break;
                }
            }
            // Handle incoming messages
            Some(msg) = ws_rx.next() => {
                match msg {
                    Ok(Message::Ping(p)) => {
                        // Client sent ping, reply with pong
                        let _ = ws_tx.send(Message::Pong(p)).await;
                    }
                    Ok(Message::Pong(_)) => {
                        // Client replied to our ping, update watchdog
                        last_pong = std::time::Instant::now();
                    }
                    Ok(Message::Close(_)) | Err(_) => break,
                    _ => {}
                }
            }
        }
    }

    println!("❌ Client disconnected: {}", peer);
}

// Helper: Rank-1 update A += z * z^T
fn rank1_update(
    gpu: &Gpu,
    a_buf: &metal::Buffer,
    z: &[f32],
    n: usize,
    keep: f32,
    trace_target: f32,
) {
    if z.iter().any(|v| !v.is_finite()) {
        eprintln!("[cov] skipped rank1 update due to non-finite input");
        return;
    }
    let keep = keep.clamp(0.0, 0.9999);
    let gain = 1.0 - keep;
    let mut a = gpu.read_f32(a_buf, n * n);
    if !a.iter().all(|v| v.is_finite()) {
        reset_covariance(gpu, a_buf, n);
        return;
    }
    for i in 0..n {
        let zi = z[i];
        for j in 0..n {
            let idx = i * n + j;
            a[idx] = keep * a[idx] + gain * zi * z[j];
        }
    }
    let target_trace = trace_target.max(1.0);
    let trace: f32 = (0..n).map(|i| a[i * n + i]).sum();
    if trace.is_finite() && trace > 1e-6 {
        let scale = (target_trace / trace).clamp(0.0, 2.0);
        for val in &mut a {
            *val *= scale;
        }
    } else {
        reset_covariance(gpu, a_buf, n);
        return;
    }
    if a.iter().all(|v| v.is_finite()) {
        gpu.write_f32(a_buf, &a);
    } else {
        reset_covariance(gpu, a_buf, n);
    }
}

#[allow(dead_code)]
fn decay_covariance(gpu: &Gpu, a_buf: &metal::Buffer, n: usize, keep: f32, trace_target: f32) {
    let keep = keep.clamp(0.0, 0.9999);
    let mut a = gpu.read_f32(a_buf, n * n);
    if !a.iter().all(|v| v.is_finite()) {
        reset_covariance(gpu, a_buf, n);
        return;
    }
    for val in &mut a {
        *val *= keep;
    }
    let trace: f32 = (0..n).map(|i| a[i * n + i]).sum();
    if trace.is_finite() && trace > 1e-6 {
        let target_trace = trace_target.max(1.0);
        let scale = (target_trace / trace).min(1.0);
        for val in &mut a {
            *val *= scale;
        }
        gpu.write_f32(a_buf, &a);
    } else {
        reset_covariance(gpu, a_buf, n);
    }
}

fn reset_covariance(gpu: &Gpu, a_buf: &metal::Buffer, n: usize) {
    eprintln!("[cov] covariance reset to identity");
    let mut a = vec![0.0f32; n * n];
    for i in 0..n {
        a[i * n + i] = 1.0;
    }
    gpu.write_f32(a_buf, &a);
}
