// Minime: Prime-driven sensory engine with GPU acceleration
// Streams eigenvectors to Python consciousness layer via WebSocket

use crate::hard_reset::{
    fixed_recovery_target_pct, fixed_recovery_target_ratio, hard_recovery_reset_enabled,
    hard_reset_activation_gain, hard_reset_covariance_bootstrap_gain,
    hard_reset_fresh_build_keep_cap, hard_reset_internal_synth_enabled, hard_reset_rho_floor,
};
use anyhow::Result;
use astrid_minime_protocol::{current_protocol, EigenPacketV1, ProtocolHeaderV1};
use clap::{ArgAction, Parser, Subcommand, ValueEnum};
use futures_util::{SinkExt, StreamExt};
use minime::activation_trace::ActivationTraceRecorder;
use minime::controller_recovery::{
    adaptive_target_floor, hard_reset_synth_gain_floor, projection_has_signal, recovery_fill_boost,
    recovery_keep_ceiling, recovery_keep_floor_base, semantic_lane_is_active,
    semantic_projection_bias, stable_core_semantic_retirement_active, underfill_spread_relief,
};
use minime::spectral_fingerprint::{SpectralDenominatorV1, SpectralFingerprintV1};
use minime::stable_core::StableCoreRuntime;
use minime::startup_restore::load_regulator_context;
use minime::transition_event::{
    build_transition_event, fill_band, glimpse_distance as transition_glimpse_distance,
    TransitionEventInput, TRANSITION_FILL_BAND_THRESHOLD_PCT,
};
use serde::Serialize;
use std::{
    collections::VecDeque,
    fs,
    io::Write,
    mem,
    net::SocketAddr,
    process,
    sync::Arc,
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::broadcast,
    time::{sleep, Duration},
};
use tokio_tungstenite::{accept_async, tungstenite::Message};

use crate::{cheby, gpu, rescue_overfill, rescue_scaffold, sensory_bus};

use crate::cheby::*;
use crate::db::*;
use crate::division::{
    archive_division_inbox_command, division_rehearsal_enabled, load_or_create_parent_generation,
    prepare_native_division, read_division_inbox, NativeDivisionCoordinator, RuntimeCaptureV2,
    StableFieldCaptureV2,
};
use crate::esn::*;
use crate::gpu::*;
use crate::handoff_diag::*;
use crate::ising_shadow::*;
use crate::memory_bank::*;
use crate::nn::*;
use crate::prime::*;
use crate::regulator::*;
use crate::rescue_overfill::OverfillStage;
use crate::sensory_bus::{LaneSource, SemanticStaleShape, SensoryBusConfig};
use crate::spectral::EigenFillEstimator;

include!("runtime/cli_and_wire.rs");
include!("runtime/reviews.rs");
include!("runtime/semantic_modality.rs");
include!("runtime/adapters.rs");
include!("runtime/entrypoint.rs");
include!("runtime/orchestration.rs");
include!("runtime/telemetry_broadcast.rs");
include!("runtime/spectral_math.rs");
include!("runtime/telemetry_evidence.rs");
include!("runtime/tests.rs");
