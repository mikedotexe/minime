use super::*;
use serde_json::json;
use std::collections::{BTreeMap, VecDeque};

pub struct Recorder {
    pub session_id: String,
    pub collecting: Vec<Artifact>,
    pub last_engine_t_ms: u64,
    pub last_wall_ms: u64,
    samples: VecDeque<Sample>,
    events: VecDeque<Event>,
    channel_last: BTreeMap<String, u64>,
    last_event_capture_ms: Option<u64>,
    last_captured_sequence: Option<u64>,
    last_quiet_capture_ms: u64,
    ordinal: u64,
    pub automatic_admission: bool,
    clock_discontinuity: bool,
    last_event_wall_ms: Option<u64>,
    last_quiet_wall_ms: Option<u64>,
}

impl Recorder {
    pub fn new(session_id: &str) -> Self {
        Self {
            session_id: session_id.to_string(),
            collecting: Vec::new(),
            last_engine_t_ms: 0,
            last_wall_ms: 0,
            samples: VecDeque::new(),
            events: VecDeque::new(),
            channel_last: BTreeMap::new(),
            last_event_capture_ms: None,
            last_captured_sequence: None,
            last_quiet_capture_ms: 0,
            ordinal: 0,
            automatic_admission: true,
            clock_discontinuity: false,
            last_event_wall_ms: None,
            last_quiet_wall_ms: None,
        }
    }

    pub fn restore_budget(&mut self, budget: &Value) {
        self.last_event_wall_ms = budget["last_event_wall_ms"].as_u64();
        self.last_quiet_wall_ms = budget["last_quiet_wall_ms"].as_u64();
    }

    pub fn budget(&self) -> Value {
        json!({"last_event_wall_ms":self.last_event_wall_ms, "last_quiet_wall_ms":self.last_quiet_wall_ms})
    }

    pub fn observe(&mut self, sample: Sample) -> Vec<Artifact> {
        if !matches!(sample.channel.as_str(), "body" | "spectral" | "activation") {
            return Vec::new();
        }
        if self
            .channel_last
            .get(&sample.channel)
            .is_some_and(|last| sample.engine_t_ms < last.saturating_add(1_000))
        {
            return Vec::new();
        }
        self.channel_last
            .insert(sample.channel.clone(), sample.engine_t_ms);
        if sample.engine_t_ms >= self.last_engine_t_ms {
            if self.last_wall_ms != 0 {
                let expected_wall = self
                    .last_wall_ms
                    .saturating_add(sample.engine_t_ms - self.last_engine_t_ms);
                if sample.wall_clock_unix_ms.abs_diff(expected_wall) > 5_000 {
                    self.clock_discontinuity = true;
                    for artifact in &mut self.collecting {
                        if !artifact
                            .reasons
                            .iter()
                            .any(|r| r == "wall_clock_discontinuity")
                        {
                            artifact.reasons.push("wall_clock_discontinuity".into());
                        }
                    }
                }
            }
            self.last_engine_t_ms = sample.engine_t_ms;
            self.last_wall_ms = sample.wall_clock_unix_ms;
        }
        for artifact in &mut self.collecting {
            if (artifact.window_start_engine_t_ms..=artifact.window_end_engine_t_ms)
                .contains(&sample.engine_t_ms)
            {
                artifact.samples.push(sample.clone());
            }
        }
        self.samples.push_back(sample);
        let oldest = self.last_engine_t_ms.saturating_sub(BUFFER_MS);
        self.samples.retain(|s| s.engine_t_ms >= oldest);
        while self.samples.len() > 543 {
            self.samples.pop_front();
        }
        self.events.retain(|e| e.engine_t_ms >= oldest);
        let finished = self.finish_due(self.last_engine_t_ms);
        if self.automatic_admission
            && self
                .last_quiet_wall_ms
                .is_none_or(|last| self.last_wall_ms >= last.saturating_add(900_000))
            && self
                .last_engine_t_ms
                .saturating_sub(self.last_quiet_capture_ms)
                >= 900_000
        {
            if self.collecting.len() < MAX_COLLECTING {
                self.start_automatic("quiet_sample", self.last_engine_t_ms, self.last_wall_ms);
                self.last_quiet_capture_ms = self.last_engine_t_ms;
                self.last_quiet_wall_ms = Some(self.last_wall_ms);
            }
        }
        finished
    }

    pub fn event(&mut self, mut event: Event, wall_ms: u64) {
        if event.session_id != self.session_id {
            return;
        }
        let existing = self
            .events
            .iter_mut()
            .find(|e| e.sequence == event.sequence);
        if let Some(existing) = existing {
            // Enrichment retains the first event's anchor even if its payload has a later tick time.
            event.engine_t_ms = existing.engine_t_ms;
            *existing = event.clone();
        } else {
            self.events.push_back(event.clone());
            while self.events.len() > 512 {
                self.events.pop_front();
            }
        }
        let mut merged = false;
        for artifact in &mut self.collecting {
            if (artifact.window_start_engine_t_ms..=artifact.window_end_engine_t_ms)
                .contains(&event.engine_t_ms)
            {
                if let Some(existing) = artifact
                    .events
                    .iter_mut()
                    .find(|e| e.sequence == event.sequence)
                {
                    *existing = event.clone();
                } else if artifact.events.len() < 512 {
                    artifact.events.push(event.clone());
                } else if !artifact
                    .reasons
                    .iter()
                    .any(|r| r == "event_capacity_reached")
                {
                    artifact.reasons.push("event_capacity_reached".into());
                }
                merged = true;
            }
        }
        let eligible = event
            .event
            .get("basin_shift")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            || event
                .event
                .get("crossed_target_fill")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            || event
                .event
                .get("crossed_fill_band")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            || event
                .event
                .get("spectral_spike")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            || !event
                .event
                .get("debounced_phase_transition")
                .and_then(Value::as_bool)
                .unwrap_or(true);
        if self.automatic_admission
            && eligible
            && !merged
            && self
                .last_event_wall_ms
                .is_none_or(|last| wall_ms >= last.saturating_add(300_000))
            && self
                .last_captured_sequence
                .is_none_or(|sequence| event.sequence > sequence)
            && self.collecting.len() < MAX_COLLECTING
            && self
                .last_event_capture_ms
                .is_none_or(|last| event.engine_t_ms.saturating_sub(last) >= 300_000)
        {
            self.start_automatic("detected_event", event.engine_t_ms, wall_ms);
            self.last_event_capture_ms = Some(event.engine_t_ms);
            self.last_event_wall_ms = Some(wall_ms);
            self.last_captured_sequence = Some(event.sequence);
        }
        if merged {
            self.last_captured_sequence = Some(
                self.last_captured_sequence
                    .map_or(event.sequence, |sequence| sequence.max(event.sequence)),
            );
        }
    }

    fn start_automatic(&mut self, origin: &str, anchor: u64, wall_ms: u64) {
        self.ordinal = self.ordinal.saturating_add(1);
        let date = date_partition(wall_ms).unwrap_or_else(|| "1970-01-01".into());
        use sha2::{Digest, Sha256};
        let session_key = format!("{:x}", Sha256::digest(self.session_id.as_bytes()));
        let id = format!(
            "ai_{date}_{}_{}_{:06}",
            &session_key[..12],
            wall_ms,
            self.ordinal
        );
        let artifact = self.make_artifact(id, origin, anchor, wall_ms);
        self.collecting.push(artifact);
    }

    fn make_artifact(&self, id: String, origin: &str, anchor: u64, wall_ms: u64) -> Artifact {
        let start = anchor.saturating_sub(PRE_MS);
        let end = anchor.saturating_add(POST_MS);
        Artifact {
            policy: POLICY.into(),
            schema_version: 1,
            id,
            session_id: self.session_id.clone(),
            origin: origin.into(),
            anchor_engine_t_ms: anchor,
            anchor_unix_ms: wall_ms,
            window_start_engine_t_ms: start,
            window_end_engine_t_ms: end,
            status: "collecting".into(),
            reasons: Vec::new(),
            capture_policy: json!({"pre_ms": PRE_MS, "post_ms": POST_MS, "buffer_ms": BUFFER_MS,
                "immediate_ms": [0,30000], "delayed_ms": [60000,90000],
                "event_budget_ms": 300000, "quiet_budget_ms": 900000,
                "max_collecting": MAX_COLLECTING, "max_pending_writes": MAX_PENDING_WRITES,
                "raw_activations_retained": false}),
            request_ids: Vec::new(),
            events: self
                .events
                .iter()
                .filter(|e| (start..=end).contains(&e.engine_t_ms))
                .cloned()
                .collect(),
            samples: self
                .samples
                .iter()
                .filter(|s| (start..=end).contains(&s.engine_t_ms))
                .cloned()
                .collect(),
            coverage: Value::Null,
            measurements: Value::Null,
        }
    }

    pub fn request(&mut self, request: CaptureRequest) -> Result<Option<Artifact>, String> {
        if !valid_id(&request.request_id) || !valid_id(&request.afterimage_id) {
            return Err("invalid_request_identity".into());
        }
        if let Some(existing) = self
            .collecting
            .iter()
            .find(|a| a.id == request.afterimage_id)
        {
            return if existing.request_ids.contains(&request.request_id) {
                Ok(None)
            } else {
                Err("artifact_identity_already_reserved".into())
            };
        }
        if self.collecting.len() >= MAX_COLLECTING {
            return Err("capture_capacity_reached".into());
        }
        let same_session = request
            .session_id
            .as_deref()
            .is_none_or(|s| s == self.session_id);
        let mut reasons = Vec::new();
        let anchor = match request.anchor_engine_t_ms.filter(|_| same_session) {
            Some(anchor) => anchor,
            None => {
                reasons.push("anchor_estimated_from_wall_time".into());
                self.last_engine_t_ms
                    .saturating_sub(self.last_wall_ms.saturating_sub(request.anchor_unix_ms))
            }
        };
        let mut artifact = self.make_artifact(
            request.afterimage_id,
            "authored_save",
            anchor,
            request.anchor_unix_ms,
        );
        artifact.request_ids.push(request.request_id);
        artifact.reasons = reasons;
        let predates_session =
            self.last_wall_ms.saturating_sub(request.anchor_unix_ms) > self.last_engine_t_ms;
        if !same_session
            || predates_session
            || self.samples.is_empty()
            || (self.clock_discontinuity && request.anchor_engine_t_ms.is_none())
        {
            artifact.samples.clear();
            artifact.events.clear();
            artifact.status = "incomplete".into();
            artifact
                .reasons
                .push("source_session_or_telemetry_unavailable".into());
            if self.clock_discontinuity {
                artifact
                    .reasons
                    .push("wall_clock_mapping_unavailable".into());
            }
            artifact.refresh();
            return Ok(Some(artifact));
        }
        if request.anchor_unix_ms > self.last_wall_ms.saturating_add(5_000)
            || anchor > self.last_engine_t_ms.saturating_add(5_000)
        {
            return Err("source_timestamp_in_future".into());
        }
        if artifact.window_end_engine_t_ms < self.last_engine_t_ms {
            Self::finalize(&mut artifact, None);
            return Ok(Some(artifact));
        }
        self.collecting.push(artifact);
        Ok(None)
    }

    pub fn finish_due(&mut self, now_ms: u64) -> Vec<Artifact> {
        let mut finished = Vec::new();
        let mut index = 0;
        while index < self.collecting.len() {
            // A two-cadence allowance permits channels produced later in the same engine tick.
            if now_ms
                > self.collecting[index]
                    .window_end_engine_t_ms
                    .saturating_add(5_000)
            {
                let mut artifact = self.collecting.remove(index);
                Self::finalize(&mut artifact, None);
                finished.push(artifact);
            } else {
                index += 1;
            }
        }
        finished
    }

    pub fn interrupt(&mut self, reason: &str) -> Vec<Artifact> {
        self.collecting
            .drain(..)
            .map(|mut artifact| {
                Self::finalize(&mut artifact, Some(reason));
                artifact
            })
            .collect()
    }

    pub fn finalize(artifact: &mut Artifact, reason: Option<&str>) {
        artifact.refresh();
        if let Some(reason) = reason {
            artifact.reasons.push(reason.into());
        }
        let missing = artifact.coverage["channels"]
            .as_object()
            .is_none_or(|channels| {
                channels.values().any(|c| {
                    c["samples"].as_u64().unwrap_or(0) == 0
                        || c["gaps"].as_array().is_none_or(|gaps| !gaps.is_empty())
                        || c["invalid_samples"].as_u64().unwrap_or(0) > 0
                })
            });
        artifact.status = if missing
            || !artifact.reasons.is_empty()
            || artifact.coverage["pre_window_clipped_at_session_start"] == true
        {
            "incomplete"
        } else {
            "completed"
        }
        .into();
    }
}
