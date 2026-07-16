#![recursion_limit = "512"]

//! Thin binary facade for Minime runtime orchestration.

mod av_gpu;
mod av_ws;
mod buffer_pool;
mod cheby;
mod db;
mod esn;
mod gpu;
mod handoff_diag;
mod hard_reset;
mod ising_shadow;
mod memory_bank;
mod nn;
mod prime;
mod regulator;
#[allow(dead_code)]
mod rescue_overfill;
#[allow(dead_code)]
mod rescue_scaffold;
mod runtime;
mod sensory_bus;
mod sensory_ws;
mod spectral;

fn main() -> anyhow::Result<()> {
    runtime::run()
}
