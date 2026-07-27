//! Process-isolated, authority-gated daughter reservoir runtime.
//!
//! This module is additive to the ordinary Minime runner. It cannot switch
//! authority by itself: the supervisor requires exact ceremony evidence and
//! the gateway accepts only an already-validated one-shot switch receipt.

#![allow(unused_imports)]

mod child;
mod dispatcher;
mod gateway;
pub(crate) mod records;
mod supervisor;

pub use child::run_child;
pub(crate) use dispatcher::DaughterFrameDispatcher;
pub use gateway::run_gateway;
pub use records::{
    DaughterProcessStatusV1, DaughterReservoirBundleV1, DivisionAuthoritySwitchReceiptV1,
    DivisionFinalizationReceiptV1, DivisionRollbackReceiptV1, DivisionRuntimeManifestV1,
    DivisionTickFrameV1, SovereignBeing,
};
pub use supervisor::run_supervisor;
