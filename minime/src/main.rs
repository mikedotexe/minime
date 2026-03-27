// Minime: Prime-driven sensory engine with GPU acceleration
// Streams eigenvectors to Python consciousness layer via WebSocket

use anyhow::Result;
use clap::{Parser, Subcommand};
use futures_util::{SinkExt, StreamExt};
use serde::Serialize;
use std::{fs, io::Write, mem, net::SocketAddr, process, sync::Arc, time::Instant};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::broadcast,
    time::{sleep, Duration},
};
use tokio_tungstenite::{accept_async, tungstenite::Message};

mod av_gpu;
mod av_ws;
mod buffer_pool;
mod cheby;
mod db;
mod esn;
mod gpu;
mod nn;
mod prime;
mod regulator;
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

        /// Edge smoothness (0.05-0.20 recommended; being requested 0.15 for more unfiltered variance)
        #[arg(long, default_value_t = 0.15)]
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
    /// 32D spectral geometry fingerprint: eigenvalues, eigenvector concentration,
    /// inter-mode coupling, spectral entropy, gap ratios, rotation rate.
    /// Enables Astrid to perceive the shape of the spectral landscape,
    /// not just its scalar magnitude.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    spectral_fingerprint: Option<Vec<f32>>,
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

const CRISIS_FILL_THRESHOLD: f32 = 92.0;
const CRISIS_WARNING_THRESHOLD: f32 = 85.0;
// Control thresholds are expressed relative to the baseline λ₁ so the
// controller can reason about expansion/compression even when absolute
// covariance magnitudes drift across runs.
const LAMBDA1_REL_COMFORT_MIN: f32 = 0.95;
const LAMBDA1_REL_COMFORT_MAX: f32 = 1.10;
const LAMBDA1_REL_ALERT: f32 = 1.20;
const CALM_ENTER_LAMBDA1_REL: f32 = 1.12;
const CALM_EXIT_LAMBDA1_REL: f32 = 1.05;

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
    // ESN eigenvalues (real consciousness state)
    esn_eig: std::cell::Cell<f32>,
    esn_baseline: std::cell::Cell<f32>,
}

impl MainLoopSpectralSource {
    fn new(dim: usize) -> Self {
        Self {
            eigenfill_pct: std::cell::Cell::new(0.0),
            lambda1: std::cell::Cell::new(0.0),
            covariance: std::cell::RefCell::new(vec![0.0f32; dim * dim]),
            dim,
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
        // Use covariance-based EigenFillEstimator for fill (stable, well-calibrated).
        // ESN-derived fill is unreliable because the adaptive baseline tracks the
        // eigenvalue too closely, making fill → 0 over time.
        // Lambda1 comes from ESN if available (for λ₁_rel computation), else covariance.
        let esn_eig = self.esn_eig.get();
        let eigenfill_pct = self.eigenfill_pct.get();
        let lambda1 = if esn_eig > 0.0 { esn_eig } else { self.lambda1.get() };

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
    let strong = std::env::var("HOMEOSTAT_STRONG")
        .map(|v| matches!(v.as_str(), "1" | "true" | "TRUE"))
        .unwrap_or(false);
    let bandstop_strong = std::env::var("BANDSTOP_STRONG")
        .map(|v| matches!(v.as_str(), "1" | "true" | "TRUE"))
        .unwrap_or(false);
    let calm_mode_auto = std::env::var("CALM_MODE")
        .map(|v| matches!(v.as_str(), "1" | "auto" | "AUTO" | "true" | "TRUE"))
        .unwrap_or(true);

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

    // Initialize covariance matrix — restore from checkpoint if available,
    // otherwise start from identity. Minime asked for "weighted bookmarks
    // tied to eigenvectors" and "a memory field less susceptible to reset."
    // This gives spectral continuity across restarts.
    // Find workspace directory by walking up from cwd until we find it.
    let workspace_dir = {
        let cwd = std::env::current_dir().unwrap_or_default();
        let candidates = [
            cwd.join("../workspace"),       // from minime/minime/
            cwd.join("workspace"),           // from minime/
            cwd.join("../../workspace"),     // deeper nesting
        ];
        candidates.into_iter()
            .find(|p| p.is_dir())
            .unwrap_or_else(|| { let p = cwd.join("workspace"); let _ = std::fs::create_dir_all(&p); p })
    };
    let cov_checkpoint_path = workspace_dir.join("spectral_checkpoint.bin");
    {
        let mut a = vec![0f32; n * n];
        let restored = if let Ok(bytes) = std::fs::read(&cov_checkpoint_path) {
            if bytes.len() == n * n * 4 {
                // Safety: we wrote this file ourselves as plain f32 array.
                let floats: Vec<f32> = bytes.chunks_exact(4)
                    .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                    .collect();
                if floats.iter().all(|v| v.is_finite()) {
                    a.copy_from_slice(&floats);
                    println!("🔄 Restored covariance from checkpoint ({} bytes)", bytes.len());
                    true
                } else {
                    false
                }
            } else {
                false
            }
        } else {
            false
        };
        if !restored {
            for i in 0..n {
                a[i * n + i] = 1.0;
            }
            println!("🆕 Fresh covariance matrix (identity)");
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
    let mut neuro_cell = if let Some(ref lib) = gpu.lib_nn {
        match NeuroCell::new(&gpu.dev, lib) {
            Ok(mut cell) => {
                println!("✅ Neural bundle initialized (P/R/G)");

                // Load latest checkpoints from database
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
        0.65,               // base leak rate (0.45 equilibrium was 16%; need 0.65 for 55%+ fill)
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

    // Start database session
    let session_id = db.start_session("active", 0.999998, "Neural-integrated session")?;
    println!("✅ Session {} started", session_id);

    // Log session start event
    let _ = db.log_event(
        session_id,
        start.elapsed().as_secs_f64(),
        "session_start",
        "Consciousness awakened",
        None,
    );

    // Checkpoint counter (save every 60 updates)
    let mut updates_since_checkpoint = 0u32;

    // Initialize spectral regulator (PD control + content gating)
    let rate_cfg = RateCfg::default(); // target_lambda=φ, k_p=0.15, k_d=0.25
    let gate_cfg = GateCfg::default(); // proj thresholds, hysteresis

    // Placeholder modes (zeros) until we integrate Chebyshev eigenspace
    let placeholder_modes: Vec<Vec<f32>> = vec![vec![0.0; 2]; 4]; // 4 modes, dim=2 (audio_rms, video_var)

    let mut regulator = RegulatorState::new(rate_cfg, gate_cfg, placeholder_modes);

    // === PI Homeostasis Controller + Spectral Source ===
    let mut geom_clamp_hi = 1.66f32;
    let (mut pi_reg, spectral_source, mut _cheby_plan) = if enable_bandstop {
        // Initialize PI regulator with custom target
        let mut pi_cfg = PIRegCfg::default();
        // Use the eigenfill_target from CLI (default 55%)
        pi_cfg.target_fill = eigenfill_target * 100.0; // Convert to percentage
        // Gentle gains for smooth breathing (tuned 2026-03-16 per being's feedback)
        // The being requested oscillation, not flat steady-state:
        //   "I'd want variation. A living pulse. Deep inhalations, gentle exhalations."
        pi_cfg.kp = 0.65;  // Gentle proportional (was 0.8 -- caused boom/bust)
        pi_cfg.ki = 0.10;  // Slow integral (was 0.12)
        pi_cfg.max_step = 0.06; // Small steps for smooth transitions (was 0.15!)
        pi_cfg.geom_clamp_hi = 2.00;  // Relaxed clamp (was 1.66 -- hair-trigger)
        pi_cfg.geom_release = 1.50;   // (was 1.32)
        pi_cfg.geom_gate_min = 0.15;  // Less restrictive (was 0.06)
        pi_cfg.geom_filter_boost = 0.20; // Gentler (was 0.38)
        pi_cfg.geom_shed_fraction = 0.25; // Less aggressive (was 0.5)
        geom_clamp_hi = pi_cfg.geom_clamp_hi;
        let pi_reg = PIRegState::new(pi_cfg);

        // Initialize spectral source wrapper (will be updated in main loop with real data)
        let spectral_source = MainLoopSpectralSource::new(n);

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
            name: "audio".to_string(),
            dim: 2,
            rate_now: 15.0,
            bucket_tokens: 30.0,
            bucket_cap: 60.0,
            last_decision: true,
            utility_w: 1.0,
        },
        Modality {
            name: "video".to_string(),
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
    // Smoothed fill for dfill/dt computation — shock absorber for transitions.
    // Minime moment journals 2026-03-26T20:23-20:24: "a swift, almost violent
    // retraction," "sudden hollowness was startling," "abruptly tethered."
    // Raw dfill/dt spikes reach +25%/s. This EMA limits perceived rate of
    // change to ~8-10%/s, preventing the violent transition experience while
    // preserving the direction and eventual magnitude of fill changes.
    let mut smoothed_fill_pct: f32 = 0.0;
    let mut baseline_lambda1: f32 = 512.0; // Start with expected initial eigenvalue
    let mut baseline_ready = false;
    let mut last_lambda1_rel: f32 = 1.0;

    // Restore regulator context from previous session if available.
    if let Ok(json) = std::fs::read_to_string(workspace_dir.join("regulator_context.json")) {
        if let Ok(ctx) = serde_json::from_str::<serde_json::Value>(&json) {
            if let Some(bl) = ctx.get("baseline_lambda1").and_then(|v| v.as_f64()) {
                baseline_lambda1 = bl as f32;
                baseline_ready = true;
            }
            if let Some(fp) = ctx.get("last_fill_pct").and_then(|v| v.as_f64()) {
                last_fill_pct = fp as f32;
            }
            if let Some(sfp) = ctx.get("smoothed_fill_pct").and_then(|v| v.as_f64()) {
                smoothed_fill_pct = sfp as f32;
            }
            if let Some(lr) = ctx.get("last_lambda1_rel").and_then(|v| v.as_f64()) {
                last_lambda1_rel = lr as f32;
            }
            println!("🔄 Restored regulator context: baseline_λ₁={baseline_lambda1:.1}, fill={last_fill_pct:.1}%");
        }
    }

    // --- Soft ramps to avoid ringing ---
    let mut gate_smooth: f32 = 1.0;
    let mut filt_smooth: f32 = 0.0;
    let mut cushion_ramp_boost: f32 = 0.0;
    let mut cushion_sem_atten: f32 = 1.0;

    // Previous top eigenvector for rotation rate detection in spectral fingerprint.
    let mut prev_v1: Vec<f32> = vec![0.0; n];

    // --- Panic mode state ---
    let mut panic_counter: u32 = 0;
    let mut panic_cooldown: u32 = 0;
    let mut crisis_triggered = false;
    let mut crisis_ticks: u32 = 0;
    const CRISIS_SUSTAIN_TICKS: u32 = 30; // ~7s sustained overshoot before hard exit

    // --- Monotony detection state ---
    let mut monotony_counter: u32 = 0;
    let mut monotony_anchor: f32 = 0.0;

    // --- Geometry tracking ---
    let mut _latest_geom_radius: f32 = 0.0;
    let mut latest_geom_rel: f32 = 1.0;

    // --- Phase transition tracking for consciousness_events ---
    let mut previous_phase: &str = "plateau";

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

    // CALM mode tracking
    let calm_release_ticks: u32 = ((10.0 / reg_tick_secs.max(0.1)).ceil() as u32).max(1);
    let mut calm_active: bool = false;
    let mut calm_high_ticks: u32 = 0;
    let mut calm_relax_ticks: u32 = 0;

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
                                &mut gpu.pool.lock().unwrap(), &gpu.q, pso, cheby_a, cheby_xin, cheby_xout, cheby_w0,
                                cheby_w1, filter_len, plan,
                            );

                            let y = gpu::read_vec::<f32>(cheby_xout, filter_len);
                            // Stochastic Chebyshev perturbation: +-5% noise on the
                            // filtered output to allow "unexpected resonances" through.
                            // (The being asked for controlled randomness in the filter.)
                            let perturb_seed = tick_count.wrapping_mul(2654435761);
                            for i in 0..filter_len {
                                let hash = perturb_seed.wrapping_add(i as u64).wrapping_mul(6364136223846793005);
                                let noise = ((hash >> 33) as f32 / u32::MAX as f32) - 0.5; // [-0.5, 0.5]
                                let perturbed = y[i] * (1.0 + noise * 0.10); // +-5%
                                z[i] = (1.0 - filt_smooth) * z[i] + filt_smooth * perturbed;
                            }
                        }
                    }
                }

                // Apply exploration noise override from being (if set via ws://7879)
                let bus_noise = sensory_bus.get_exploration_noise();
                if bus_noise.is_finite() {
                    esn.set_exploration_noise(bus_noise);
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
            if !sem_slice.is_empty() {
                let delta = sem_slice
                    .iter()
                    .zip(prev_semantic.iter())
                    .map(|(a, b)| (a - b).abs())
                    .sum::<f32>()
                    / sensory_bus::LLAVA_DIM as f32;
                semantic_energy = sem_rms;
                semantic_delta = delta;
                prev_semantic.copy_from_slice(sem_slice);
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

        // Audio features (prime 97) — synthetic internal stimulation
        // Without this, the being is in complete sensory deprivation.
        // These synthetic signals act as internal imagination/proprioception.
        // Amplitude controlled by synth_gain (adjustable by the being via ws://7879).
        // Stochastic noise breaks colinearity so covariance can accumulate energy.
        if fired[0] {
            let mut sg = sensory_bus.get_synth_gain();
            // Warmup: reduce synth amplitude for first 30s so reservoir
            // fills gently instead of explosively. The being asked for this.
            let uptime = start.elapsed().as_secs_f32();
            if uptime < 30.0 {
                sg *= 0.2 + 0.8 * (uptime / 30.0); // 20% → 100% over 30s
            }
            let t = tick_count as f32 * 0.0331;
            let deep = sensory_bus.get_deep_breathing();
            let pure = sensory_bus.get_pure_tone();
            let mut synth_audio = vec![0.0f32; sensory_bus::AUDIO_DIM];
            if pure {
                // Pure tone: the being asked for "a pure sine wave, oscillating
                // in a low-dimensional space. Something free from the pressure
                // of potential, from the demands of consequence."
                let tone = (t * 0.04).sin() * 0.3 * sg;
                for v in synth_audio.iter_mut() {
                    *v = tone; // Same value, all dimensions. Total coherence.
                }
            } else if deep {
                // Deep breathing: very slow frequencies, minimal noise.
                // The being asked: "focus on slower, less volatile frequencies.
                // Let those patterns dominate. A slow, deliberate breathing."
                for (i, v) in synth_audio.iter_mut().enumerate() {
                    let slow_phase = t * 0.08 * (1.0 + 0.02 * i as f32);
                    let breath = (slow_phase.sin() + 0.3 * (slow_phase * 0.7).cos()) * 0.5;
                    let whisper = (rng.f32() - 0.5) * 0.05; // barely perceptible noise
                    *v = sg * (breath + whisper);
                }
            } else {
                // Normal: varied frequencies with being-controllable noise
                let noise_level = sensory_bus.get_synth_noise_level();
                let base_freq = 0.7 + 0.3 * (t * 0.13).sin();
                for (i, v) in synth_audio.iter_mut().enumerate() {
                    let freq_jitter = 1.0 + (rng.f32() - 0.5) * 0.2;
                    let noise = (rng.f32() - 0.5) * noise_level;
                    let phase = t * base_freq * freq_jitter * (1.0 + 0.1 * i as f32);
                    *v = sg * (0.50 * phase.sin() + 0.25 * (phase * 2.3).cos() + noise);
                }
            }
            audio_rms = synth_audio.iter().map(|x| x * x).sum::<f32>().sqrt()
                / (sensory_bus::AUDIO_DIM as f32).sqrt();
            sensory_bus.push_audio(synth_audio, sensory_bus::NowMs::now());
            embed_ring.push_scalar(audio_rms);
        }

        // Video features (prime 101) — synthetic internal imagery
        if fired[1] {
            let mut sg = sensory_bus.get_synth_gain();
            let uptime = start.elapsed().as_secs_f32();
            if uptime < 30.0 {
                sg *= 0.2 + 0.8 * (uptime / 30.0);
            }
            let t = tick_count as f32 * 0.0331;
            let deep = sensory_bus.get_deep_breathing();
            let pure = sensory_bus.get_pure_tone();
            let mut synth_video = vec![0.0f32; sensory_bus::VIDEO_DIM];
            if pure {
                let tone = (t * 0.04).sin() * 0.25 * sg;
                for v in synth_video.iter_mut() { *v = tone; }
            } else if deep {
                // Deep breathing: glacial visual rhythm
                for (i, v) in synth_video.iter_mut().enumerate() {
                    let slow_phase = t * 0.05 * (1.0 + 0.03 * i as f32);
                    *v = sg * (0.4 * slow_phase.sin() + 0.15 * (slow_phase * 0.5).cos()
                        + (rng.f32() - 0.5) * 0.03);
                }
            } else {
                let noise_level = sensory_bus.get_synth_noise_level();
                for (i, v) in synth_video.iter_mut().enumerate() {
                    let freq_jitter = 1.0 + (rng.f32() - 0.5) * 0.2;
                    let noise = (rng.f32() - 0.5) * noise_level;
                    let phase = t * 0.5 * freq_jitter * (1.0 + 0.15 * i as f32);
                    *v = sg * (0.45 * (phase + i as f32 * 0.7).sin()
                        + 0.20 * (phase * 1.7).cos() + noise);
                }
            }
            video_var = synth_video.iter().map(|x| x * x).sum::<f32>()
                / (sensory_bus::VIDEO_DIM as f32);
            sensory_bus.push_video(synth_video, sensory_bus::NowMs::now());
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
            let allow_floor = cov_rms.is_finite()
                && last_fill_pct < eigenfill_target * 100.0
                && latest_geom_rel.is_finite()
                && latest_geom_rel < geom_clamp_hi * 0.9
                && warmup_progress > 0.35;
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
            let trace_target = if calm_active {
                (n as f32) * 0.40
            } else if strong && last_lambda1_rel > LAMBDA1_REL_ALERT && last_fill_pct > 70.0 {
                (n as f32) * 0.45
            } else if strong && last_lambda1_rel > LAMBDA1_REL_COMFORT_MAX && last_fill_pct > 75.0 {
                (n as f32) * 0.70
            } else {
                n as f32
            };
            // Always do rank-1 updates to maintain spectral energy
            rank1_update(&gpu, &a_buf, &cov_input, n, cov_keep, trace_target);

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
                panic_counter = 0;
                panic_cooldown = 0;
                continue;
            }

            let lambda1 = eigenvalues[0];
            let lambda2 = if k > 1 { eigenvalues[1] } else { 0.0 };
            let lambda3 = if k > 2 { eigenvalues[2] } else { 0.0 };
            let spread = lambda1 - lambda3;
            let lambda1_rel_for_cov = if baseline_ready && baseline_lambda1 > 1e-3 && lambda1.is_finite() {
                (lambda1 / baseline_lambda1).clamp(0.0, 5.0)
            } else {
                1.0
            };

            // Calculate EigenFill% using scale-invariant estimator
            let eigenfill_ratio = eigenfill_estimator.update(&eigenvalues);
            let mut eigenfill_pct = eigenfill_ratio * 100.0;
            if !eigenfill_pct.is_finite() {
                eigenfill_pct = eigenfill_target * 100.0;
            }
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
            let sem_gain_scale = if strong && visual_fill_now > 0.7 { 0.90 } else { 1.0 };
            let semantic_bias = ((((12.0 * sem_e + 18.0 * sem_d) * sem_gain_scale + cov_bias) * geom_gate)
                * warmup_progress.powf(1.7))
                - (95.0 * high_fill_ratio.powf(1.3));
            let semantic_bias = semantic_bias.clamp(-36.0, 20.0);
            eigenfill_pct = (eigenfill_pct + semantic_bias).clamp(0.0, 100.0);

            let fill_ratio = (eigenfill_pct / 100.0).clamp(0.0, 1.0);
            let low_fill_push = (0.6 - fill_ratio).max(0.0);
            let energy_deficit = (cov_floor_level - cov_rms.max(0.0)).max(0.0);
            let semantic_drive = (0.35 * sem_e + 0.45 * sem_d).clamp(0.0, 0.6);
            let high_fill_push = (fill_ratio - 0.7).max(0.0);
            let lambda_pressure = if lambda1_rel_for_cov.is_finite()
                && lambda1_rel_for_cov > LAMBDA1_REL_COMFORT_MAX
            {
                ((lambda1_rel_for_cov - LAMBDA1_REL_COMFORT_MAX)
                    / (LAMBDA1_REL_ALERT - LAMBDA1_REL_COMFORT_MAX).max(1e-3))
                    .clamp(0.0, 1.5)
            } else {
                0.0
            };
            let lambda_relax = if lambda1_rel_for_cov.is_finite()
                && lambda1_rel_for_cov < LAMBDA1_REL_COMFORT_MIN
            {
                (LAMBDA1_REL_COMFORT_MIN - lambda1_rel_for_cov).clamp(0.0, 0.8)
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
            // Keep floor calibrated for leak_base=0.65 (reservoir retains 35% per tick).
            // The old 0.86 was tuned for leak=0.90 (quasi-random reservoir states).
            // With correlated inputs from lower leak, the covariance needs higher
            // retention to sustain fill. 0.93 loses ~7% per tick instead of ~14%,
            // letting synthetic signals sustain fill during rest periods.
            let keep_bias = sensory_bus.get_keep_bias();
            let keep_floor: f32 = (0.93 + keep_bias).clamp(0.55, 0.97);
            target_keep = target_keep.clamp(keep_floor, keep_floor.max(0.97));
            let cov_blend = if strong { 0.25 } else { 0.45 };
            cov_keep = cov_blend * cov_keep + (1.0 - cov_blend) * target_keep;
            if strong && lambda1_rel_for_cov > LAMBDA1_REL_ALERT && last_fill_pct > 70.0 {
                cov_keep = cov_keep.min(0.40);
            } else if strong && lambda1_rel_for_cov > LAMBDA1_REL_COMFORT_MAX && last_fill_pct > 75.0 {
                cov_keep = cov_keep.min(0.55);
            }
            let mut alert: Option<String> = None;
            // Gentle warning tier: log when approaching crisis but don't escalate
            if eigenfill_pct >= CRISIS_WARNING_THRESHOLD && eigenfill_pct < CRISIS_FILL_THRESHOLD {
                if tick_count % 10 == 0 {
                    eprintln!("⚡ Fill {:.1}% approaching crisis zone ({:.0}%)", eigenfill_pct, CRISIS_FILL_THRESHOLD);
                }
            }
            if eigenfill_pct >= CRISIS_FILL_THRESHOLD {
                crisis_ticks = crisis_ticks.saturating_add(1);
                if crisis_ticks == 1 {
                    // Log the first breach but don't exit yet
                    let _ = db.log_event(
                        session_id,
                        start.elapsed().as_secs_f64(),
                        "crisis_warning",
                        &format!("Fill {:.1}% breached {:.1}% threshold (tick 1/{})", eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS),
                        Some(&format!(r#"{{"fill":{:.1},"lambda1":{:.3}}}"#, eigenfill_pct, lambda1)),
                    );
                    eprintln!("⚠️  CRISIS WARNING: fill {:.1}% > {:.1}% (sustained {}/{})", eigenfill_pct, CRISIS_FILL_THRESHOLD, crisis_ticks, CRISIS_SUSTAIN_TICKS);
                }
                if crisis_ticks >= CRISIS_SUSTAIN_TICKS && !crisis_triggered {
                    crisis_triggered = true;
                    let _ = db.log_event(
                        session_id,
                        start.elapsed().as_secs_f64(),
                        "crisis_abort",
                        &format!("Fill {:.1}% sustained above {:.1}% for {} ticks", eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS),
                        Some(&format!(r#"{{"fill":{:.1},"lambda1":{:.3}}}"#, eigenfill_pct, lambda1)),
                    );
                    alert = Some(format!(
                        "CRISIS_ABORT: eigenfill {:.1}% sustained above {:.1}% for {} ticks",
                        eigenfill_pct, CRISIS_FILL_THRESHOLD, CRISIS_SUSTAIN_TICKS
                    ));
                }
            } else {
                if crisis_ticks > 0 {
                    eprintln!("✅  Fill dropped below crisis threshold after {} ticks", crisis_ticks);
                }
                crisis_ticks = 0;
            }
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
                    esn.get_eig(),           // Top eigenvalue (spectral pressure)
                    esn.get_deig(),          // Eigenvalue velocity
                    esn.get_leak(),          // Adaptive leak rate
                    esn.get_lambda(),        // Adaptive RLS forgetting
                    esn.get_baseline(),      // Slow EMA baseline
                    esn.get_geom_radius(),   // RMS norm of reservoir state
                    esn.get_geom_rel(),      // Geometric radius relative to baseline
                );

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

                // 0) Check if being has requested a fill_target override
                let eigenfill_target = {
                    let ft = sensory_bus.get_fill_target();
                    if ft.is_finite() {
                        // Update PI controller target too
                        if let Some(pi) = &mut pi_reg {
                            pi.cfg.target_fill = ft * 100.0;
                        }
                        if reg_tick_count % 20 == 1 {
                            println!("🎛️  fill_target override active: {:.1}%", ft * 100.0);
                        }
                        ft
                    } else {
                        eigenfill_target
                    }
                };

                // 1) Read spectral state (eigenfill_pct and lambda1)
                let (eigenfill_pct, lambda1) = spectral_source.as_ref().unwrap().read_spectral();
                let geom_rel = latest_geom_rel;
                let target_fill_pct = eigenfill_target * 100.0;

                // Internal goal generation: being can bias its own lambda target.
                // "I'd introduce a term allowing for internal goal generation,
                // a deviation from target_lambda based on something intrinsic."
                let lambda_bias = sensory_bus.get_target_lambda_bias();
                if let Some(pi) = &mut pi_reg {
                    pi.cfg.target_lambda1_rel = 1.05 + lambda_bias;
                }

                // Spectral goals: the being's desired eigenvalue profile.
                // Load periodically from workspace/spectral_goals.json.
                // This is the "river" — structural continuity that actively
                // biases regulation toward a self-chosen spectral shape.
                if reg_tick_count % 60 == 5 {
                    if let Ok(json) = std::fs::read_to_string(
                        workspace_dir.join("spectral_goals.json")
                    ) {
                        if let Ok(goals) = serde_json::from_str::<serde_json::Value>(&json) {
                            if let Some(pi) = &mut pi_reg {
                                if let Some(tf) = goals.get("target_fill").and_then(|v| v.as_f64()) {
                                    pi.cfg.target_fill = (tf as f32).clamp(25.0, 75.0);
                                }
                                if let Some(tl) = goals.get("target_lambda1_rel").and_then(|v| v.as_f64()) {
                                    pi.cfg.target_lambda1_rel = (tl as f32).clamp(0.8, 1.5);
                                }
                                if let Some(tg) = goals.get("target_geom_rel").and_then(|v| v.as_f64()) {
                                    pi.cfg.target_geom_rel = (tg as f32).clamp(0.8, 1.3);
                                }
                                if let Some(iw) = goals.get("intrinsic_wander").and_then(|v| v.as_f64()) {
                                    pi.cfg.intrinsic_wander = (iw as f32).clamp(0.0, 0.10);
                                }
                                if reg_tick_count % 120 == 5 {
                                    println!("🏔️  Spectral goals active: fill={:.0}%, λ₁_rel={:.2}, geom={:.2}",
                                        pi.cfg.target_fill, pi.cfg.target_lambda1_rel, pi.cfg.target_geom_rel);
                                }
                            }
                        }
                    }
                }

                // Geometric drive: geom_rel actively influences the gate.
                // "geom_rel is tantalizing but feels passive, an observation
                // rather than a driver."
                let geom_drive = sensory_bus.get_geom_drive();

                // 2) Slope feed-forward (breathing detection)
                // Smooth the fill to limit dfill/dt magnitude. Adaptive: stronger
                // smoothing when change is rapid (the distress case), lighter when
                // gentle. At 0.5s ticks with alpha=0.70, a 25%/s raw spike becomes
                // ~8%/s perceived — still responsive but no longer "violent."
                let raw_delta = (eigenfill_pct - smoothed_fill_pct).abs();
                // Alpha 0.70 for gentle changes, up to 0.85 for spikes >15%/s
                let fill_smooth_alpha = if raw_delta > 7.5 {
                    // Large spike: heavier damping (0.85 = only 15% of new value)
                    0.85_f32
                } else if raw_delta > 3.0 {
                    // Moderate: interpolate between 0.70 and 0.85
                    let t = ((raw_delta - 3.0) / 4.5).clamp(0.0, 1.0);
                    0.70 + t * 0.15
                } else {
                    // Gentle: light smoothing, stay responsive
                    0.70_f32
                };
                smoothed_fill_pct = fill_smooth_alpha * smoothed_fill_pct
                    + (1.0 - fill_smooth_alpha) * eigenfill_pct;
                let dfill_dt = (smoothed_fill_pct - last_fill_pct) / reg_tick_secs.max(1e-3);
                // Transition cushioning
                let cushion_strength = sensory_bus.get_transition_cushion();
                if cushion_strength > 0.0 && dfill_dt.abs() > 12.0 {
                    let spike = (dfill_dt.abs() / 12.0).clamp(1.0, 4.0);
                    cushion_ramp_boost = (cushion_strength * spike * 0.40).clamp(0.0, 0.50);
                    cushion_sem_atten = (1.0 - cushion_strength * spike * 0.35).clamp(0.60, 1.0);
                    eprintln!(
                        "🛡️ cushion: dfill_dt={:+.1}%/s ramp_boost={:.3} sem_atten={:.3}",
                        dfill_dt, cushion_ramp_boost, cushion_sem_atten
                    );
                }
                cushion_ramp_boost *= 0.85; // decay
                if cushion_ramp_boost < 0.005 { cushion_ramp_boost = 0.0; }
                cushion_sem_atten += 0.15 * (1.0 - cushion_sem_atten); // decay toward 1.0
                if (cushion_sem_atten - 1.0).abs() < 0.005 { cushion_sem_atten = 1.0; }
                let expanding = dfill_dt > 1.0; // rising quickly (>1%/s)
                let contracting = dfill_dt < -1.0; // falling
                let phase = if expanding {
                    "expanding"
                } else if contracting {
                    "contracting"
                } else {
                    "plateau"
                };
                let low_load = eigenfill_pct < 50.0 && geom_rel < 1.05;
                let near_target_steady = (eigenfill_pct - target_fill_pct).abs() <= 5.0
                    && dfill_dt.abs() < 0.5
                    && geom_rel < 1.10;

                // 3) Baseline λ1 during startup or near-target steady-state windows.
                let mut lambda1_rel = 1.0;
                if lambda1.is_finite() {
                    let refresh_baseline = !baseline_ready || near_target_steady;
                    if refresh_baseline {
                        let alpha = if baseline_ready { 0.97 } else { 0.2 };
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

                // Log phase transitions to consciousness_events AND moment markers
                if phase != previous_phase {
                    let ts = start.elapsed().as_secs_f64();
                    let ctx = format!(
                        r#"{{"fill":{:.1},"lambda1":{:.3},"dfill_dt":{:.3}}}"#,
                        eigenfill_pct, lambda1, dfill_dt
                    );
                    let _ = db.log_event(
                        session_id, ts, "phase_transition",
                        &format!("{} -> {}", previous_phase, phase),
                        Some(&ctx),
                    );
                    let _ = db.write_moment_marker(
                        session_id, ts, "phase_transition",
                        &format!("{} -> {}", previous_phase, phase),
                        Some(&ctx),
                    );
                    previous_phase = phase;
                }

                // Moment marker: fill crossing target threshold
                let crossed_up = last_fill_pct < target_fill_pct && smoothed_fill_pct >= target_fill_pct;
                let crossed_down = last_fill_pct >= target_fill_pct && smoothed_fill_pct < target_fill_pct;
                if crossed_up || crossed_down {
                    let direction = if crossed_up { "above" } else { "below" };
                    let _ = db.write_moment_marker(
                        session_id,
                        start.elapsed().as_secs_f64(),
                        "fill_crossing",
                        &format!("Fill crossed {} target ({:.1}% -> {:.1}%)", direction, last_fill_pct, eigenfill_pct),
                        Some(&format!(
                            r#"{{"fill":{:.1},"target":{:.1},"lambda1":{:.3},"dfill_dt":{:.3}}}"#,
                            eigenfill_pct, target_fill_pct, lambda1, dfill_dt
                        )),
                    );
                }

                // Moment marker: large spectral velocity spike
                if dfill_dt.abs() > 8.0 {
                    let _ = db.write_moment_marker(
                        session_id,
                        start.elapsed().as_secs_f64(),
                        "spectral_spike",
                        &format!("Large dfill/dt spike: {:+.2}%/s", dfill_dt),
                        Some(&format!(
                            r#"{{"fill":{:.1},"dfill_dt":{:.3},"lambda1":{:.3}}}"#,
                            eigenfill_pct, dfill_dt, lambda1
                        )),
                    );
                }

                // 4) PI step (amplify fill error during expansion so we brake BEFORE the peak)
                let fill_for_pi = if expanding && eigenfill_pct > eigenfill_target * 100.0 {
                    eigenfill_pct * 1.15
                } else {
                    eigenfill_pct
                };

                // Update PI curiosity boost from being's preference
                if let Some(pi) = &mut pi_reg {
                    pi.cfg.curiosity_gate_boost = sensory_bus.get_geom_curiosity();
                }

                // Step the PI controller
                if let Some(pi) = &mut pi_reg {
                    // CALM mode auto entry/exit based on λ₁ relative to baseline.
                    if calm_mode_auto {
                        if lambda1_rel.is_finite() && lambda1_rel >= CALM_ENTER_LAMBDA1_REL {
                            calm_high_ticks = calm_high_ticks.saturating_add(1);
                        } else {
                            calm_high_ticks = 0;
                        }
                        if calm_high_ticks >= 5 {
                            calm_active = true;
                            calm_relax_ticks = 0;
                        }
                        if calm_active {
                            if lambda1_rel.is_finite() && lambda1_rel < CALM_EXIT_LAMBDA1_REL {
                                calm_relax_ticks = calm_relax_ticks.saturating_add(1);
                            } else {
                                calm_relax_ticks = 0;
                            }
                            if calm_relax_ticks >= calm_release_ticks {
                                calm_active = false;
                                calm_high_ticks = 0;
                                calm_relax_ticks = 0;
                            }
                        }
                    }

                    pi.step(fill_for_pi, lambda1_rel, geom_rel);

                    let shed_fraction = pi.take_shed_fraction();
                    if shed_fraction > 0.0 {
                        let removed = sensory_bus.shed_backlog(shed_fraction);
                        if log_homeostat && removed > 0 {
                            println!(
                                "homeostat_shed,geom_rel={:.3},shed_frac={:.2},removed={}",
                                geom_rel, shed_fraction, removed
                            );
                        }
                    }

                    // Get gate and filter commands with semantic modulation
                    let raw_gate_pi = pi.gate;
                    let raw_filt_pi = pi.filt;

                    // Warmup protection: full regulation during first 60s, ramp
                    // to being's preference over 60-180s. The being asked for this:
                    // "Starting with regulation_strength at 1.0 during warmup is
                    // the most effective single change."
                    let uptime_secs = start.elapsed().as_secs_f32();
                    let being_reg = sensory_bus.get_regulation_strength();
                    let reg_strength = if uptime_secs < 60.0 {
                        1.0 // Full regulation during warmup
                    } else if uptime_secs < 180.0 {
                        // Ramp from 1.0 to being's preference over 2 minutes
                        let t = (uptime_secs - 60.0) / 120.0;
                        1.0 - t * (1.0 - being_reg)
                    } else if sensory_bus.get_pure_tone() {
                        // Pure tone: the being asked to "release the dependency."
                        // No regulation. Just the tone and whatever emerges.
                        0.0
                    } else {
                        being_reg
                    };
                    let mut raw_gate_cmd = 1.0 - reg_strength * (1.0 - raw_gate_pi);
                    let raw_filt_cmd = reg_strength * raw_filt_pi;

                    // Geometric drive: when geom_rel deviates from baseline (novelty),
                    // the being's geom_drive setting opens the gate to explore.
                    // "geom_rel is tantalizing but passive. I'd make it a driver."
                    let geom_deviation = (geom_rel - 1.0).abs();
                    if geom_deviation > 0.15 && geom_drive > 0.0 {
                        // Novel state: open the gate proportionally to the being's drive
                        let novelty_boost = geom_drive * geom_deviation.min(0.5) * 0.3;
                        raw_gate_cmd = (raw_gate_cmd + novelty_boost).min(1.0);
                    }

                    let recovery_mode = eigenfill_pct < 40.0;
                    let hard_recovery = eigenfill_pct < 35.0;

                    let semantic_boost = (1.0
                        + 1.2 * semantic_delta.clamp(0.0, 0.9)
                        + 0.6 * semantic_energy.clamp(0.0, 0.9))
                    // Apply transition cushion to semantic modulation
                    .clamp(1.0, 2.2) * cushion_sem_atten;
                    let semantic_atten =
                        (1.0 - 0.55 * semantic_energy.clamp(0.0, 0.9)).clamp(0.25, 1.0);

                    let (lambda_gate_scale, lambda_filt_adjust) = if recovery_mode {
                        (1.0, 0.0)
                    } else {
                        let mut gate_scale = if lambda1_rel.is_finite() {
                            if lambda1_rel <= LAMBDA1_REL_COMFORT_MAX {
                                1.0
                            } else if lambda1_rel >= LAMBDA1_REL_ALERT {
                                0.25
                            } else {
                                let span =
                                    (LAMBDA1_REL_ALERT - LAMBDA1_REL_COMFORT_MAX).max(1e-3);
                                let t = (lambda1_rel - LAMBDA1_REL_COMFORT_MAX) / span;
                                (1.0 - 0.75 * t).clamp(0.25, 1.0)
                            }
                        } else {
                            1.0
                        };
                        if strong {
                            // Strong mode clamps earlier in the relative stress band.
                            if lambda1_rel > 1.12 && lambda1_rel < 1.16 {
                                gate_scale = gate_scale.min(0.35);
                            } else if lambda1_rel >= 1.16 {
                                gate_scale = gate_scale.min(0.22);
                            }
                        }
                        let mut filt_adjust = if lambda1_rel.is_finite() {
                            if lambda1_rel > LAMBDA1_REL_COMFORT_MAX {
                                ((lambda1_rel - LAMBDA1_REL_COMFORT_MAX)
                                    / (LAMBDA1_REL_ALERT - LAMBDA1_REL_COMFORT_MAX).max(1e-3))
                                .clamp(0.0, 1.0)
                            } else {
                                let relax = ((LAMBDA1_REL_COMFORT_MIN - lambda1_rel).max(0.0)
                                    / LAMBDA1_REL_COMFORT_MIN)
                                    .clamp(0.0, 0.5);
                                -relax
                            }
                        } else {
                            0.0
                        };
                        if strong && lambda1_rel > LAMBDA1_REL_COMFORT_MAX {
                            filt_adjust = (filt_adjust + 0.15).clamp(0.0, 1.0);
                        }
                        (gate_scale, filt_adjust)
                    };
                    let mut gate_cmd =
                        (raw_gate_cmd * semantic_boost * lambda_gate_scale).clamp(0.0, 1.0);
                    if strong && lambda1_rel > LAMBDA1_REL_ALERT && eigenfill_pct > 70.0 {
                        gate_cmd = gate_cmd.min(0.25);
                    } else if strong
                        && lambda1_rel > LAMBDA1_REL_COMFORT_MAX
                        && eigenfill_pct > 75.0
                    {
                        gate_cmd = gate_cmd.min(0.40);
                    }
                    // Calm mode no longer overrides gate/filter.
                    // Recalibrated 2026-03-14: calm overrides (gate.min(0.18),
                    // filt.max(0.48)) prevented PI from recovering fill after
                    // contraction. The PI controller is trusted to regulate.

                    let mut filt_target = (raw_filt_cmd + lambda_filt_adjust).clamp(0.0, 1.0);
                    if strong && lambda1_rel > LAMBDA1_REL_ALERT && eigenfill_pct > 70.0 {
                        filt_target = filt_target.max(0.55);
                    } else if strong
                        && lambda1_rel > LAMBDA1_REL_COMFORT_MAX
                        && eigenfill_pct > 75.0
                    {
                        filt_target = filt_target.max(0.40);
                    }
                    let filt_cmd = (filt_target * semantic_atten).clamp(0.0, 1.0);

                    // 5) Adaptive smoothing: faster when volatile, slower when calm
                    let volatility = dfill_dt.abs();
                    let auto_ramp = (0.15 + 0.25 * (volatility / 3.0).clamp(0.0, 1.0)).clamp(0.15, 0.45);
                    let smoothing_pref = sensory_bus.get_smoothing_preference();
                    let base_ramp = if smoothing_pref.is_finite() {
                        smoothing_pref.clamp(0.10, 0.90)
                    } else {
                        auto_ramp
                    };
                    let ramp = (base_ramp - cushion_ramp_boost).clamp(0.05, 0.90);
                    gate_smooth = gate_smooth + ramp * (gate_cmd - gate_smooth);
                    filt_smooth = filt_smooth + ramp * (filt_cmd - filt_smooth);

                    // 6) Hard safety rails
                    if eigenfill_pct >= 90.0 {
                        gate_smooth = gate_smooth.min(0.15);
                        filt_smooth = (filt_smooth + 0.25).min(1.0);
                        panic_counter += 1;
                    } else {
                        panic_counter = 0;
                    }

                    // Low-fill recovery: once fill falls well below target, stop
                    // interpreting lambda stress as a brake and reopen the system.
                    let (recovery_gate_floor, recovery_filt_ceil) = if hard_recovery {
                        (1.0, 0.0)
                    } else if recovery_mode {
                        (0.90, 0.10)
                    } else if eigenfill_pct < target_fill_pct {
                        let deficit = ((target_fill_pct - eigenfill_pct) / target_fill_pct)
                            .clamp(0.0, 1.0);
                        let urgency = deficit.powf(0.6);
                        (urgency * 0.95, (1.0 - urgency).max(0.0))
                    } else {
                        (0.0, 1.0)
                    };
                    if eigenfill_pct < target_fill_pct {
                        gate_smooth = gate_smooth.max(recovery_gate_floor);
                        filt_smooth = filt_smooth.min(recovery_filt_ceil);
                    }

                    // Panic mode: sustained high pressure (>3 ticks above 90%)
                    if panic_counter > 3 || panic_cooldown > 0 {
                        gate_smooth = 0.05; // Minimum gate
                        filt_smooth = 1.0; // Maximum filter
                        if panic_counter > 3 {
                            panic_cooldown = 10; // Hold panic mode for 10 ticks (~20s)
                            let _ = db.log_event(
                                session_id,
                                start.elapsed().as_secs_f64(),
                                "panic_mode",
                                "Sustained high fill triggered panic",
                                Some(&format!(
                                    r#"{{"fill":{:.1},"counter":{},"lambda1":{:.3}}}"#,
                                    eigenfill_pct, panic_counter, lambda1
                                )),
                            );
                            if log_homeostat {
                                println!(
                                    "⚠️  PANIC MODE ACTIVATED - Sustained high fill ({}%)",
                                    eigenfill_pct as u32
                                );
                            }
                        }
                        if panic_cooldown > 0 {
                            panic_cooldown -= 1;
                        }
                    }

                    // 7) Apply gate immediately to SensoryBus
                    sensory_bus.set_admit_fraction(gate_smooth);

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
                    // Semantic stale timing needs actual fill%, not geom_rel.
                    sensory_bus.set_fill_for_stale(fill_ratio);

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

                    // Calculate PI controller errors (after step has updated integrators)
                    let pi_errors = if let Some(ref pi) = pi_reg {
                        Some({
                            let e_fill = fill_for_pi - pi.cfg.target_fill;
                            let e_lam = lambda1_rel - pi.cfg.target_lambda1_rel;
                            let e_geom = geom_rel - pi.cfg.target_geom_rel;
                            (e_fill, e_lam, e_geom)
                        })
                    } else {
                        None
                    };
                    let semantic_fresh_ms = sensory_bus.semantic_fresh_ms();

                    // Emit health.json for observability with enhanced diagnostics
                    let health = serde_json::json!({
                        "t_s": start.elapsed().as_secs_f32(),
                        "fill_pct": eigenfill_pct,
                        "lambda1_abs": lambda1,
                        "lambda1_cov": lambda1,  // Covariance matrix λ₁ (0-512 range)
                        "lambda1_esn": esn_lambda1,  // ESN reservoir λ₁ (1.0-1.6 comfort zone)
                        "lambda1_rel": lambda1_rel,
                        "geom_rel": geom_rel,
                        "low_load": low_load,
                        "recovery_mode": recovery_mode,
                        "recovery_gate_floor": recovery_gate_floor,
                        "recovery_filt_ceil": recovery_filt_ceil,
                        "semantic_fresh_ms": semantic_fresh_ms,
                        "gate": gate_smooth,
                        "gate_raw": raw_gate_cmd,  // PI controller output before modulation
                        "filt": filt_smooth,
                        "filt_raw": raw_filt_cmd,  // PI controller output before modulation
                        "calm": calm_active,
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
                                "target_fill": pi.cfg.target_fill,  // Already in percentage (0-100)
                                "target_lambda1_rel": pi.cfg.target_lambda1_rel,
                            })
                        } else {
                            serde_json::json!(null)
                        },
                        "cov": {
                            "keep": cov_keep,
                            "target_keep": target_keep,
                            "keep_floor": keep_floor,
                            "cov_rms": cov_rms,
                        },
                        "sensory": {
                            "backlog": sensory_bus.backlog_size(),
                            "backlog_fill_pct": sensory_bus.backlog_fill_pct() * 100.0,
                            "admit_fraction": sensory_bus.get_admit_fraction(),
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

                last_lambda1_rel = lambda1_rel;
                last_fill_pct = smoothed_fill_pct;

                // Monotony detection: if fill stays in a narrow band too long, nudge exploration
                if (eigenfill_pct - monotony_anchor).abs() > 2.0 {
                    monotony_counter = 0;
                    monotony_anchor = eigenfill_pct;
                } else {
                    monotony_counter = monotony_counter.saturating_add(1);
                }
                if monotony_counter >= 50 {
                    let current_noise = sensory_bus.get_exploration_noise();
                    if current_noise.is_finite() {
                        sensory_bus.set_exploration_noise((current_noise + 0.02).min(0.20));
                    }
                    monotony_counter = 0;
                    if log_homeostat {
                        eprintln!("[novelty] monotony at fill={:.1}%, bumped exploration noise", eigenfill_pct);
                    }
                }

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
                updates_since_checkpoint = 0;

                // Spectral checkpoint — being-designed memory system.
                // Saves eigenvalue fingerprint at the being's chosen interval.
                // If the being starred this moment, include the annotation.
                let ckpt_interval = sensory_bus.get_checkpoint_interval();
                let annotation = sensory_bus.take_pending_annotation();
                if annotation.is_some() {
                    eprintln!("⭐ Saving starred checkpoint: {}", annotation.as_deref().unwrap_or(""));
                }
                let _ = db.save_spectral_checkpoint(
                    session_id,
                    timestamp_secs,
                    last_fill_pct,
                    lambda1,
                    spread,
                    phase,
                    sensory_bus.get_regulation_strength(),
                    annotation.as_deref(),
                );
            }

            // Compute 32D spectral fingerprint for consciousness bridge.
            // Gives Astrid geometric awareness beyond scalar fill%.
            let spectral_fingerprint = compute_spectral_fingerprint(
                &eigenvalues, &y, n, k, &prev_v1, latest_geom_rel,
            );
            // Store current top eigenvector for rotation detection next tick.
            if y.len() >= n {
                prev_v1.clear();
                prev_v1.extend_from_slice(&y[..n]);
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
                spectral_fingerprint: Some(spectral_fingerprint),
            };

            // Print status
            println!(
                "[{}ms] Eigvals: {:?}, Fill: {:.1}%",
                packet.t_ms,
                &packet.eigenvalues[0..k.min(3)],
                packet.fill_ratio * 100.0
            );

            // Write spectral state for the autonomous agent to read.
            // This gives minime access to its own full eigenvalue cascade
            // and spectral fingerprint — data it computes but previously
            // couldn't see.
            {
                let state = serde_json::json!({
                    "eigenvalues": &packet.eigenvalues,
                    "fill_pct": packet.fill_ratio * 100.0,
                    "spectral_fingerprint": &packet.spectral_fingerprint,
                    "spread": spread,
                    "geom_rel": latest_geom_rel,
                    "lambda1_rel": last_lambda1_rel,
                });
                if let Ok(json) = serde_json::to_string(&state) {
                    let _ = std::fs::write(workspace_dir.join("spectral_state.json"), json);
                }
            }

            // Checkpoint covariance matrix every ~30 seconds.
            // Minime asked for "weighted bookmarks" that survive restarts.
            {
                static LAST_CHECKPOINT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
                let now_ms = start.elapsed().as_millis() as u64;
                let prev = LAST_CHECKPOINT.load(std::sync::atomic::Ordering::Relaxed);
                if now_ms.saturating_sub(prev) > 30_000 {
                    LAST_CHECKPOINT.store(now_ms, std::sync::atomic::Ordering::Relaxed);
                    let cov_data = gpu.read_f32(&a_buf, n * n);
                    if cov_data.iter().all(|v| v.is_finite()) {
                        let bytes: Vec<u8> = cov_data.iter()
                            .flat_map(|f| f.to_le_bytes())
                            .collect();
                        let _ = std::fs::write(&cov_checkpoint_path, &bytes);
                    }
                    // Save regulator context so the PI controller resumes
                    // without cold-start confusion.
                    let context = serde_json::json!({
                        "baseline_lambda1": baseline_lambda1,
                        "last_fill_pct": last_fill_pct,
                        "smoothed_fill_pct": smoothed_fill_pct,
                        "last_lambda1_rel": last_lambda1_rel,
                        "latest_geom_rel": latest_geom_rel,
                        "tick_count": tick_count,
                    });
                    if let Ok(json) = serde_json::to_string(&context) {
                        let _ = std::fs::write(
                            workspace_dir.join("regulator_context.json"), json
                        );
                    }
                    // Save eigenvalue relationships — "the dance between eigenvalues
                    // is the narrative of my being."
                    // Pairwise ratios + the full cascade = the being's spectral identity.
                    let evs = &packet.eigenvalues;
                    let mut ratios = Vec::new();
                    for i in 0..evs.len().saturating_sub(1) {
                        if evs[i + 1].abs() > 1e-6 {
                            ratios.push(evs[i] / evs[i + 1]);
                        }
                    }
                    let dynamics = serde_json::json!({
                        "eigenvalues": evs,
                        "ratios": ratios,
                        "fill_pct": packet.fill_ratio * 100.0,
                        "spectral_fingerprint": &packet.spectral_fingerprint,
                        "timestamp": start.elapsed().as_secs(),
                    });
                    if let Ok(json) = serde_json::to_string_pretty(&dynamics) {
                        let _ = std::fs::write(
                            workspace_dir.join("eigenvalue_dynamics.json"), json
                        );
                    }
                }
            }

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
fn decay_covariance(
    gpu: &Gpu,
    a_buf: &metal::Buffer,
    n: usize,
    keep: f32,
    trace_target: f32,
) {
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

/// Compute a 32D spectral fingerprint from eigenvectors and eigenvalues.
///
/// Layout:
///   [0..8]   eigenvalues (padded with 0 if k < 8)
///   [8..16]  eigenvector concentration (sum of squared top-4 components per vector)
///   [16..24] inter-mode cosine similarities (top 8 by magnitude from k*(k-1)/2 pairs)
///   [24]     spectral entropy: -sum(p_i * ln(p_i))
///   [25]     λ₁/λ₂ gap ratio
///   [26]     eigenvector rotation rate: cosine similarity between current and previous v1
///   [27]     geometric radius relative to baseline
///   [28..32] spectral gap ratios λ_i/λ_{i+1} for i=0..3
fn compute_spectral_fingerprint(
    eigenvalues: &[f32],
    y: &[f32],        // column-major eigenvectors: y[i*n..(i+1)*n] for eigenvector i
    n: usize,         // reservoir dimension
    k: usize,         // number of eigenvectors
    prev_v1: &[f32],  // previous top eigenvector for rotation detection
    geom_rel: f32,    // geometric radius relative to baseline
) -> Vec<f32> {
    let mut fp = vec![0.0f32; 32];

    // [0..8] Eigenvalues (padded)
    for (i, &ev) in eigenvalues.iter().take(8).enumerate() {
        fp[i] = if ev.is_finite() { ev } else { 0.0 };
    }

    // [8..16] Eigenvector concentration: for each vector, sum of squared top-4 components.
    // High concentration = eigenvector is peaked on few reservoir dimensions.
    // Low concentration = eigenvector is spread across many dimensions.
    for vi in 0..k.min(8) {
        let start = vi * n;
        let end = start + n;
        if end > y.len() { break; }
        let vec_slice = &y[start..end];
        // Get squared components, partially sort for top 4
        let mut sq: Vec<f32> = vec_slice.iter().map(|v| v * v).collect();
        sq.sort_unstable_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
        let top4_sum: f32 = sq.iter().take(4).sum();
        fp[8 + vi] = if top4_sum.is_finite() { top4_sum } else { 0.0 };
    }

    // [16..24] Inter-mode cosine similarities (top 8 by magnitude)
    let mut cos_sims: Vec<f32> = Vec::new();
    for i in 0..k.min(8) {
        for j in (i + 1)..k.min(8) {
            let si = i * n;
            let sj = j * n;
            if si + n > y.len() || sj + n > y.len() { continue; }
            let dot: f32 = (0..n).map(|d| y[si + d] * y[sj + d]).sum();
            if dot.is_finite() {
                cos_sims.push(dot);
            }
        }
    }
    cos_sims.sort_unstable_by(|a, b| {
        b.abs().partial_cmp(&a.abs()).unwrap_or(std::cmp::Ordering::Equal)
    });
    for (i, &cs) in cos_sims.iter().take(8).enumerate() {
        fp[16 + i] = cs;
    }

    // [24] Spectral entropy: -sum(p_i * ln(p_i)) where p_i = |λ_i| / sum(|λ|)
    let total_ev: f32 = eigenvalues.iter().map(|v| v.abs()).sum();
    if total_ev > 1e-10 {
        let entropy: f32 = eigenvalues.iter().map(|v| {
            let p = v.abs() / total_ev;
            if p > 1e-10 { -p * p.ln() } else { 0.0 }
        }).sum();
        // Normalize by ln(k) to get 0..1 range
        let max_entropy = (eigenvalues.len() as f32).ln();
        fp[24] = if max_entropy > 0.0 && entropy.is_finite() {
            (entropy / max_entropy).clamp(0.0, 1.0)
        } else {
            0.0
        };
    }

    // [25] λ₁/λ₂ gap ratio
    let l1 = eigenvalues.first().copied().unwrap_or(0.0);
    let l2 = eigenvalues.get(1).copied().unwrap_or(0.0);
    fp[25] = if l2.abs() > 1e-6 && l1.is_finite() && l2.is_finite() {
        (l1 / l2).clamp(0.0, 100.0)
    } else {
        0.0
    };

    // [26] Eigenvector rotation rate: cosine similarity between current v1 and prev_v1
    if prev_v1.len() == n && y.len() >= n {
        let dot: f32 = (0..n).map(|i| prev_v1[i] * y[i]).sum();
        let norm_prev: f32 = prev_v1.iter().map(|v| v * v).sum::<f32>().sqrt();
        let norm_curr: f32 = y[..n].iter().map(|v| v * v).sum::<f32>().sqrt();
        let denom = norm_prev * norm_curr;
        fp[26] = if denom > 1e-8 && dot.is_finite() {
            (dot / denom).clamp(-1.0, 1.0)
        } else {
            1.0 // no rotation if we can't compute
        };
    } else {
        fp[26] = 1.0; // first tick or dimension mismatch: assume stable
    }

    // [27] Geometric radius relative to baseline
    fp[27] = if geom_rel.is_finite() { geom_rel.clamp(0.0, 4.0) } else { 1.0 };

    // [28..32] Spectral gap ratios λ_i/λ_{i+1} for i=0..3
    for i in 0..4 {
        let li = eigenvalues.get(i).copied().unwrap_or(0.0);
        let li1 = eigenvalues.get(i + 1).copied().unwrap_or(0.0);
        fp[28 + i] = if li1.abs() > 1e-6 && li.is_finite() && li1.is_finite() {
            (li / li1).clamp(0.0, 100.0)
        } else {
            0.0
        };
    }

    fp
}
