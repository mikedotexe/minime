//! Bounded observation-only transition archives. The observer owns no engine handles.

mod capture;
mod metrics;
mod storage;
mod worker;

pub use capture::Recorder;
pub use storage::Store;
pub use worker::AfterimageObserver;

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const POLICY: &str = "transition_afterimage_v1";
pub const PRE_MS: u64 = 30_000;
pub const POST_MS: u64 = 90_000;
pub const BUFFER_MS: u64 = 180_000;
pub const MAX_COLLECTING: usize = 8;
pub const MAX_PENDING_WRITES: usize = 16;
pub const RECENT_LIMIT: usize = 256;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Sample {
    pub channel: String,
    pub engine_t_ms: u64,
    pub wall_clock_unix_ms: u64,
    pub expected_cadence_ms: u64,
    pub values: Value,
}

impl Sample {
    pub fn new(channel: &str, engine_t_ms: u64, values: Value, cadence_ms: u64) -> Self {
        Self {
            channel: channel.to_string(),
            engine_t_ms,
            wall_clock_unix_ms: unix_ms(),
            expected_cadence_ms: cadence_ms.max(1_000),
            values,
        }
    }

    pub fn number(&self, pointer: &str) -> Option<f64> {
        if self.channel == "activation"
            && pointer != "/summary/finite_fraction"
            && self
                .values
                .pointer("/summary/finite_fraction")
                .and_then(Value::as_f64)
                != Some(1.0)
        {
            return None;
        }
        self.values
            .pointer(pointer)?
            .as_f64()
            .filter(|n| n.is_finite())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    pub session_id: String,
    pub sequence: u64,
    pub engine_t_ms: u64,
    pub event: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CaptureRequest {
    pub request_id: String,
    pub afterimage_id: String,
    pub session_id: Option<String>,
    pub anchor_engine_t_ms: Option<u64>,
    pub anchor_unix_ms: u64,
    pub requested_at_unix_ms: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Artifact {
    pub policy: String,
    pub schema_version: u8,
    pub id: String,
    pub session_id: String,
    pub origin: String,
    pub anchor_engine_t_ms: u64,
    pub anchor_unix_ms: u64,
    pub window_start_engine_t_ms: u64,
    pub window_end_engine_t_ms: u64,
    pub status: String,
    pub reasons: Vec<String>,
    pub capture_policy: Value,
    pub request_ids: Vec<String>,
    pub events: Vec<Event>,
    pub samples: Vec<Sample>,
    pub coverage: Value,
    pub measurements: Value,
}

impl Artifact {
    pub fn refresh(&mut self) {
        self.samples
            .sort_by(|a, b| (a.engine_t_ms, &a.channel).cmp(&(b.engine_t_ms, &b.channel)));
        self.coverage = metrics::coverage(self);
        self.measurements = metrics::measure(self);
    }

    pub fn summary(&self) -> Value {
        serde_json::json!({
            "id": self.id, "origin": self.origin, "session_id": self.session_id,
            "anchor_unix_ms": self.anchor_unix_ms, "status": self.status,
            "coverage": self.coverage, "reasons": self.reasons,
            "event_sequences": self.events.iter().map(|event| event.sequence).collect::<Vec<_>>(),
        })
    }
}

pub fn unix_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or(0)
}

pub fn date_partition(ms: u64) -> Option<String> {
    chrono::DateTime::from_timestamp_millis(i64::try_from(ms).ok()?)
        .map(|date| date.format("%Y-%m-%d").to_string())
}

pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 120
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

#[cfg(test)]
mod tests;
