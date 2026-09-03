//! Envelope Registry loader (Constitution C1 — observe-only stage).
//!
//! Reads minime's canonical `being_envelope_registry_v1` document (path via
//! env `MINIME_ENVELOPE_REGISTRY`, defaulting to her workspace
//! self_regulation dir). Runtime-loaded rather than compiled because engine
//! restarts cost a covariance cold start. In this stage NOTHING consumes it
//! for enforcement; Stage C3 points `apply::clamp_values` at it with the
//! compiled table as the outermost backstop. Fails CLOSED to `None` on
//! absence/malformation, and refuses any entry wider than its recorded
//! engine backstop at read time — a broken or tampered registry can never
//! widen anything.

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::Deserialize;

const REGISTRY_SCHEMA: &str = "being_envelope_registry_v1";
const TARGET_BEING: &str = "minime";
const DEFAULT_PATH: &str = "/Users/v/other/minime/workspace/self_regulation/envelope_registry.json";

#[derive(Debug, Clone, Deserialize)]
pub struct EnvelopeRegistry {
    schema: String,
    being: String,
    #[serde(default)]
    pub revision: u64,
    #[serde(default)]
    fields: BTreeMap<String, EnvelopeField>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EnvelopeField {
    floor: Option<f64>,
    ceiling: Option<f64>,
    #[serde(default)]
    engine_backstop: Option<EngineBackstop>,
    #[serde(default)]
    durability_policy: Option<DurabilityPolicy>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DurabilityPolicy {
    #[serde(default)]
    lease_max_secs: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineBackstop {
    #[serde(default)]
    floor: Option<f64>,
    #[serde(default)]
    ceiling: Option<f64>,
}

impl EnvelopeRegistry {
    #[must_use]
    pub fn field_count(&self) -> usize {
        self.fields.len()
    }

    /// `(floor, ceiling)` in the wire's f32 domain, or `None` when the
    /// field is uncovered, malformed, or wider than the engine backstop —
    /// callers fall back to the compiled clamp table.
    #[must_use]
    pub fn envelope_for(&self, field: &str) -> Option<(f32, f32)> {
        let entry = self.fields.get(field)?;
        let floor = entry.floor? as f32;
        let ceiling = entry.ceiling? as f32;
        if !floor.is_finite() || !ceiling.is_finite() || floor > ceiling {
            return None;
        }
        if let Some(backstop) = &entry.engine_backstop {
            match (backstop.floor, backstop.ceiling) {
                (Some(b_floor), Some(b_ceiling)) => {
                    if ceiling > b_ceiling as f32 || floor < b_floor as f32 {
                        return None;
                    }
                }
                // No numeric bounds: the deliberate passthrough marker
                // ({"passthrough_unclamped": true}) — nothing to compare.
                (None, None) => {}
                // Exactly one bound is a malformed backstop, not a
                // passthrough — refuse rather than silently skip.
                _ => return None,
            }
        }
        Some((floor, ceiling))
    }

    /// The registry's lease-duration ceiling for a field, in seconds, or
    /// `None` when the field carries no durability policy (Constitution C2:
    /// no policy recorded means only the wire-shape cap applies).
    #[must_use]
    pub fn lease_max_secs(&self, field: &str) -> Option<u64> {
        let policy = self.fields.get(field)?.durability_policy.as_ref()?;
        policy.lease_max_secs.filter(|max| *max > 0)
    }

    /// The strictest lease ceiling across the named fields — a lease Set
    /// touching several fields must satisfy every field's policy.
    #[must_use]
    pub fn strictest_lease_max_secs<I, S>(&self, fields: I) -> Option<u64>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        fields
            .into_iter()
            .filter_map(|field| self.lease_max_secs(field.as_ref()))
            .min()
    }
}

#[must_use]
pub fn registry_path() -> PathBuf {
    std::env::var_os("MINIME_ENVELOPE_REGISTRY")
        .map_or_else(|| PathBuf::from(DEFAULT_PATH), PathBuf::from)
}

/// Parse a registry document (schema + being checked). Public so consumers
/// can build fixture registries in tests; production reads go through
/// `load_registry`.
#[must_use]
pub fn parse_registry(text: &str) -> Option<EnvelopeRegistry> {
    let registry: EnvelopeRegistry = serde_json::from_str(text).ok()?;
    if registry.schema != REGISTRY_SCHEMA || registry.being != TARGET_BEING {
        return None;
    }
    Some(registry)
}

/// The registry is a small steward-written JSON document; anything else at
/// the (env-overridable) path — a FIFO that would block boot forever, a
/// device, a huge file — is refused before reading. The witness runs at the
/// top of `run_engine` and must never be able to delay engine boot.
const MAX_REGISTRY_BYTES: u64 = 1_048_576;

/// Load the current registry from disk (fail-closed to `None`).
#[must_use]
pub fn load_registry() -> Option<EnvelopeRegistry> {
    let path = registry_path();
    let meta = std::fs::symlink_metadata(&path).ok()?;
    if !meta.is_file() || meta.len() > MAX_REGISTRY_BYTES {
        return None;
    }
    let text = std::fs::read_to_string(&path).ok()?;
    parse_registry(&text)
}

/// Serializes tests that set or read `MINIME_ENVELOPE_REGISTRY` — the env
/// is process-global, and parallel test threads racing set/remove_var was a
/// real observed flake (a lease-policy fixture vanished mid-test).
#[cfg(test)]
pub static TEST_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(fields: &str) -> String {
        format!(
            "{{\"schema\":\"being_envelope_registry_v1\",\"being\":\"minime\",\
             \"revision\":1,\"fields\":{{{fields}}}}}"
        )
    }

    #[test]
    fn parses_valid_entry_and_refuses_widening_past_backstop() {
        let registry = parse_registry(&fixture(
            "\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.15,\
             \"engine_backstop\":{\"floor\":0.0,\"ceiling\":0.2}},\
             \"synth_gain\":{\"floor\":0.0,\"ceiling\":5.0,\
             \"engine_backstop\":{\"floor\":0.2,\"ceiling\":3.0}}",
        ))
        .expect("valid registry parses");
        assert_eq!(registry.envelope_for("exploration_noise"), Some((0.0, 0.15)));
        assert_eq!(registry.envelope_for("synth_gain"), None);
        assert_eq!(registry.envelope_for("uncovered"), None);
    }

    #[test]
    fn fails_closed_on_malformation_wrong_being_and_inverted_bounds() {
        assert!(parse_registry("{ not json").is_none());
        assert!(
            parse_registry(
                "{\"schema\":\"being_envelope_registry_v1\",\"being\":\"astrid\",\"fields\":{}}"
            )
            .is_none()
        );
        let inverted =
            parse_registry(&fixture("\"fill_target\":{\"floor\":0.75,\"ceiling\":0.25}"))
                .expect("parses");
        assert_eq!(inverted.envelope_for("fill_target"), None);
    }

    #[test]
    fn lease_max_reads_policy_and_takes_the_strictest_across_fields() {
        let registry = parse_registry(&fixture(
            "\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.2,\
             \"durability_policy\":{\"lease_max_secs\":1200,\"standing\":\"allowed\"}},\
             \"synth_gain\":{\"floor\":0.2,\"ceiling\":3.0,\
             \"durability_policy\":{\"lease_max_secs\":600}},\
             \"no_policy_field\":{\"floor\":0.0,\"ceiling\":1.0}",
        ))
        .expect("parses");
        assert_eq!(registry.lease_max_secs("exploration_noise"), Some(1200));
        assert_eq!(registry.lease_max_secs("no_policy_field"), None);
        assert_eq!(registry.lease_max_secs("uncovered"), None);
        assert_eq!(
            registry.strictest_lease_max_secs(["exploration_noise", "synth_gain"]),
            Some(600)
        );
        assert_eq!(registry.strictest_lease_max_secs(Vec::<String>::new()), None);
    }

    #[test]
    fn half_specified_backstop_refuses_while_passthrough_marker_passes() {
        // {"ceiling": only} is malformed — refusing beats silently skipping
        // the widening guard (adversarial review 2026-09-02).
        let half = parse_registry(&fixture(
            "\"exploration_noise\":{\"floor\":0.0,\"ceiling\":0.15,\
             \"engine_backstop\":{\"ceiling\":0.2}}",
        ))
        .expect("parses");
        assert_eq!(half.envelope_for("exploration_noise"), None);
        let passthrough = parse_registry(&fixture(
            "\"mode_disperse_duration_ticks\":{\"floor\":1.0,\"ceiling\":64.0,\
             \"engine_backstop\":{\"passthrough_unclamped\":true}}",
        ))
        .expect("parses");
        assert_eq!(
            passthrough.envelope_for("mode_disperse_duration_ticks"),
            Some((1.0, 64.0))
        );
    }

    #[test]
    fn live_canonical_registry_loads_when_present() {
        let _env = TEST_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        if std::env::var_os("MINIME_ENVELOPE_REGISTRY").is_some() {
            return; // an override is in play; the default-path witness does not apply
        }
        if let Some(registry) = load_registry() {
            assert_eq!(registry.being, "minime");
            assert!(registry.envelope_for("exploration_noise").is_some());
        }
    }
}
