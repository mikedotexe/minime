// Spectral regulator: token-bucket rate governor + content-aware gate + band-stop filter.
// Based on PE's principled control design.
//
// The legacy PD rate governor and content gate remain active for modality
// throughput. PI separately regulates EigenFill and the band-stop filter.
// Their types therefore describe distinct concurrent roles, not an inactive
// PD architecture embedded in a PI-only runtime.
#![allow(dead_code)]
//
// Two control roles:
// - PD rate/gate: token-bucket modality throughput targeting lambda1
// - PI homeostasis: gate/filter control targeting EigenFill% and lambda1_rel

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
