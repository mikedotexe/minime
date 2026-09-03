#![recursion_limit = "512"]

//! Thin binary facade for Minime runtime orchestration.

mod av_gpu;
mod av_ws;
mod buffer_pool;
mod cheby;
mod db;
mod division;
mod envelope_registry;
mod esn;
mod gpu;
mod handoff_diag;
mod hard_reset;
mod ising_shadow;
mod memory_bank;
mod nn;
mod owner_inquiry;
mod owner_inquiry_wire;
#[allow(dead_code, unused_imports)]
mod owner_inquiry_wire_v2;
mod owner_research;
mod prime;
mod regulator;
#[allow(dead_code)]
mod rescue_overfill;
#[allow(dead_code)]
mod rescue_scaffold;
mod runtime;
mod self_control_cli;
mod self_control_identity;
mod self_control_runtime;
mod self_control_wire;
mod semantic_body_v2;
mod sensory_bus;
mod sensory_interference;
mod sensory_protocol;
mod sensory_ws;
mod sovereign_division;
mod spectral;

fn main() -> anyhow::Result<()> {
    runtime::run()
}
