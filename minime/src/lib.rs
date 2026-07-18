//! Minime Library
//!
//! Exposes core modules for testing and integration

pub mod activation_trace;
pub mod av_gpu;
pub mod av_ws;
pub mod buffer_pool;
pub mod cheby;
pub mod controller_recovery;
pub mod db;
pub mod esn;
pub mod gpu;
pub mod hard_reset;
pub mod ising_shadow;
pub mod memory_bank;
// pub mod net;  // no net.rs file
pub mod nn;
pub mod pressure_texture;
pub mod prime;
pub mod regulator;
pub mod regulator_cartography;
pub mod rescue_overfill;
pub mod rescue_scaffold;
pub mod sensory_bus;
pub mod sensory_protocol;
pub mod sensory_ws;
pub mod spectral;
pub mod spectral_fingerprint;
pub mod stable_core;
pub mod startup_restore;
pub mod transition_event;
