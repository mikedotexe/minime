//! Process-isolated, authority-gated daughter reservoir runtime.
//!
//! This module is additive to the ordinary Minime runner. It cannot switch
//! authority by itself: the supervisor requires exact ceremony evidence and
//! the gateway accepts only an already-validated one-shot switch receipt.

#![allow(unused_imports)]

mod child;
#[cfg(feature = "division-rehearsal")]
mod continuity_proof;
mod dispatcher;
mod fanout;
mod gateway;
pub(crate) mod records;
mod supervisor;

pub use child::run_child;
#[cfg(feature = "division-rehearsal")]
pub use continuity_proof::{run_continuity_proof, verify_continuity_proof};
pub(crate) use dispatcher::DaughterFrameDispatcher;
#[cfg(feature = "division-rehearsal")]
pub(crate) use fanout::run_legacy_av_fanout_proof;
pub use gateway::run_gateway;
#[cfg(feature = "division-rehearsal")]
pub(crate) use gateway::run_gateway_byte_exact_proof;
pub use records::{
    DaughterProcessStatusV1, DaughterReservoirBundleV1, DivisionAuthoritySwitchReceiptV1,
    DivisionFinalizationReceiptV1, DivisionRollbackReceiptV1, DivisionRuntimeManifestV1,
    DivisionTickFrameV1, SovereignBeing,
};
pub use supervisor::run_supervisor;
