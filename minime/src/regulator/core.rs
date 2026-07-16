// Spectral regulator: token-bucket rate governor + content-aware gate + band-stop filter.
// Based on PE's principled control design.
//
// The PD-mode types (GateCfg, Modality, ItemMeta, Decision) are retained for API
// completeness even though the engine currently runs in PI mode exclusively.
#![allow(dead_code)]
//
// Two modes:
// - PD mode: Original token-bucket rate control targeting lambda1
// - PI mode: Dual control (gate + filter) targeting EigenFill% and lambda1_rel

use serde::{Deserialize, Serialize};

include!("core/telemetry_types.rs");
include!("core/viscosity.rs");
include!("core/resonance_evidence.rs");
include!("core/pressure_types.rs");
include!("core/reviews.rs");
include!("core/pressure_source.rs");
include!("core/rate_gate.rs");
include!("core/pi.rs");
include!("core/tests.rs");
