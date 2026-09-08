use super::*;
use serde_json::json;

const WALL: u64 = 1_788_750_000_000;

#[test]
fn enabled_observer_preserves_exact_esn_and_controller_replay() {
    use crate::{
        esn::ESN,
        gpu::Gpu,
        regulator::{PIRegCfg, PIRegState},
    };
    let gpu = Gpu::new().unwrap();
    let mut rng = fastrand::Rng::with_seed(0x4146544552494d47);
    let mut disabled = ESN::new(16, 6, 0.25, 0.15, 0.95, 0.35, 0.999, &gpu, &mut rng).unwrap();
    disabled.set_profiling_enabled(true);
    let snapshot = disabled.snapshot_v2().unwrap();
    let mut enabled = ESN::from_snapshot_v2(&snapshot, &gpu).unwrap();
    enabled.set_profiling_enabled(true);
    let mut controller_off = PIRegState::new(PIRegCfg::default());
    let mut controller_on = controller_off.clone();
    let root = tempfile::tempdir().unwrap();
    let observer = AfterimageObserver::start(root.path().into(), "replay".into());
    for tick in 0..160u64 {
        let input: Vec<f32> = (0..6)
            .map(|i| ((tick * 11 + i * 5) as f32 * 0.043).cos())
            .collect();
        disabled.step(&input).unwrap();
        enabled.step(&input).unwrap();
        let fill = 68.0 + (tick as f32 * 0.12).sin() * 10.0;
        controller_off.step(fill, disabled.get_eig(), disabled.get_geom_rel());
        controller_on.step(fill, enabled.get_eig(), enabled.get_geom_rel());
        for sample in samples(tick, f64::from(fill)) {
            observer.observe(sample);
        }
        observer.event(
            "replay",
            &json!({"sequence":1,"engine_t_s":60,"crossed_target_fill":true}),
        );
        assert_eq!(format!("{controller_off:?}"), format!("{controller_on:?}"));
        let mut off = serde_json::to_value(disabled.snapshot_v2().unwrap()).unwrap();
        let mut on = serde_json::to_value(enabled.snapshot_v2().unwrap()).unwrap();
        // Elapsed profiling times are not reservoir or controller state.
        for field in [
            "rank1_us",
            "power_us",
            "gpu_wait_us",
            "host_norm_us",
            "async_submit_us",
            "async_drain_us",
            "intro_fused_wait_us",
            "intro_tail_wait_us",
            "intro_first_read_us",
            "intro_tail_read_us",
        ] {
            off["spectral"]["last_profile"]
                .as_object_mut()
                .unwrap()
                .remove(field);
            on["spectral"]["last_profile"]
                .as_object_mut()
                .unwrap()
                .remove(field);
        }
        for (field, value) in off.as_object().unwrap() {
            assert_eq!(value, &on[field], "tick {tick}, field {field}");
        }
    }
    observer.finish();
}

#[test]
fn clock_change_rejects_guessed_telemetry_and_enrichment_can_promote_event() {
    let mut recorder = Recorder::new("17");
    for sample in samples(60, 68.0) {
        recorder.observe(sample);
    }
    let mut soft = event(1, 60, "expanding");
    soft.event = json!({"debounced_phase_transition":true});
    recorder.event(soft.clone(), WALL + 60_000);
    assert!(recorder.collecting.is_empty());
    soft.event["basin_shift"] = json!(true);
    recorder.event(soft, WALL + 61_000);
    assert_eq!(recorder.collecting.len(), 1);
    let mut jump = samples(61, 68.0).remove(0);
    jump.wall_clock_unix_ms += 100_000;
    recorder.observe(jump);
    let result = recorder
        .request(CaptureRequest {
            request_id: "rclock".into(),
            afterimage_id: "aclock".into(),
            session_id: None,
            anchor_engine_t_ms: None,
            anchor_unix_ms: WALL + 61_000,
            requested_at_unix_ms: WALL + 161_000,
        })
        .unwrap()
        .unwrap();
    assert!(result.samples.is_empty());
    assert!(result
        .reasons
        .iter()
        .any(|r| r == "wall_clock_mapping_unavailable"));
}

#[test]
fn corrupt_checkpoint_does_not_block_other_recovery_and_index_is_authoritative() {
    let root = tempfile::tempdir().unwrap();
    let mut store = storage::Store::open(root.path()).unwrap();
    let mut artifact = episode(|_| 68.0);
    store.complete(&artifact).unwrap();
    artifact.status = "failed".into();
    store.complete(&artifact).unwrap();
    let recent: Value =
        serde_json::from_slice(&std::fs::read(store.root.join("recent.json")).unwrap()).unwrap();
    assert_eq!(recent[0]["status"], "completed");
    std::fs::write(store.root.join("pending/broken.json"), b"{").unwrap();
    assert!(storage::Store::open(root.path()).is_err());
    let archive_root = store.root.clone();
    drop(store);
    assert!(storage::Store::open(root.path()).is_ok());
    assert!(archive_root.join("pending/broken.json.corrupt").exists());
}

#[test]
fn automatic_budget_survives_restart_and_repeated_old_events_do_not_recapture() {
    let mut recorder = Recorder::new("17");
    for sample in samples(60, 68.0) {
        recorder.observe(sample);
    }
    recorder.event(event(1, 60, "expanding"), WALL + 60_000);
    let budget = recorder.budget();
    recorder.finish_due(160_000);
    for sample in samples(660, 68.0) {
        recorder.observe(sample);
    }
    recorder.event(event(1, 660, "expanding"), WALL + 660_000);
    assert!(recorder.collecting.is_empty());
    let mut restored = Recorder::new("18");
    restored.restore_budget(&budget);
    let mut next = event(1, 60, "expanding");
    next.session_id = "18".into();
    restored.event(next.clone(), WALL + 70_000);
    assert!(restored.collecting.is_empty());
    restored.event(next, WALL + 370_000);
    assert_eq!(restored.collecting.len(), 1);
}

#[test]
fn finalized_event_enrichment_is_append_only_and_idempotent() {
    let root = tempfile::tempdir().unwrap();
    let mut store = Store::open(root.path()).unwrap();
    let artifact = episode(|_| 68.0);
    store.complete(&artifact).unwrap();
    let path = store.artifact_path(&artifact).unwrap();
    let original = std::fs::read(&path).unwrap();
    let mut enriched = event(1, 61, "expanding");
    enriched.event["glimpse_distance"] = json!(0.4);
    store.enrich(&enriched).unwrap();
    store.enrich(&enriched).unwrap();
    assert_eq!(std::fs::read(path).unwrap(), original);
    assert_eq!(
        std::fs::read_dir(store.root.join("event_updates").join(&artifact.id))
            .unwrap()
            .count(),
        1
    );
}

#[test]
fn oscillations_are_counted_only_in_observed_phase_intervals() {
    let mut artifact = episode(|_| 68.0);
    for sample in &mut artifact.samples {
        if sample.channel == "body" {
            sample.values["phase"] = json!(if (sample.engine_t_ms / 10_000) % 2 == 0 {
                "expanding"
            } else {
                "contracting"
            });
        }
    }
    artifact.refresh();
    assert_eq!(artifact.measurements["phase_reversals"]["value"], 9);
    for sample in &mut artifact.samples {
        if sample.channel == "body" {
            sample.values["lambda_stress"] = Value::Null;
        }
    }
    artifact.refresh();
    assert_eq!(artifact.measurements["phase_reversals"]["partial"], false);
    assert_eq!(
        artifact.measurements["lambda_stress_area"]["value"],
        Value::Null
    );
    artifact.samples.retain(|sample| {
        sample.channel != "body" || sample.engine_t_ms < 80_000 || sample.engine_t_ms > 120_000
    });
    artifact.refresh();
    assert!(
        artifact.measurements["phase_reversals"]["value"]
            .as_u64()
            .unwrap()
            < 9
    );
}

fn samples(t: u64, fill: f64) -> Vec<Sample> {
    [
        ("body", json!({"fill_pct": fill, "dfill_dt": fill-68.0, "lambda_stress": 0.2, "phase": "expanding"})),
        ("spectral", json!({"current_glimpse_12d": vec![fill / 100.0;12], "components": {"identity_anchor_churn": fill/100.0}})),
        ("activation", json!({"summary": {"finite_fraction": 1.0, "rms": fill/100.0}, "top_active_node_indexes": [1,3]})),
    ].into_iter().map(|(channel, values)| Sample { channel: channel.into(), engine_t_ms: t*1000,
        wall_clock_unix_ms: WALL+t*1000, expected_cadence_ms: 1000, values }).collect()
}

fn event(seq: u64, t: u64, phase: &str) -> Event {
    Event {
        session_id: "17".into(),
        sequence: seq,
        engine_t_ms: t * 1000,
        event: json!({"sequence":seq,"engine_t_s":t,"phase":phase,"crossed_target_fill":true}),
    }
}

fn episode(fill: impl Fn(u64) -> f64) -> Artifact {
    let mut recorder = Recorder::new("17");
    let mut finished = Vec::new();
    for t in 0..=156 {
        for sample in samples(t, fill(t)) {
            finished.extend(recorder.observe(sample));
        }
        if t == 60 {
            recorder.event(event(1, t, "expanding"), WALL + t * 1000);
        }
    }
    assert_eq!(finished.len(), 1);
    finished.remove(0)
}

#[test]
fn complete_window_and_empirical_half_return() {
    let artifact = episode(|t| {
        if t < 60 {
            68.0
        } else if t < 70 {
            78.0
        } else {
            69.0
        }
    });
    assert_eq!(artifact.status, "completed");
    assert_eq!(artifact.samples.len(), 363);
    assert_eq!(
        artifact.measurements["channel_changes"]["body/fill_pct"]["late_minus_baseline"],
        1.0
    );
    assert!(
        artifact.measurements["fill_half_return_s"]["value"]
            .as_f64()
            .unwrap()
            > 0.0
    );
    assert_eq!(
        artifact.measurements["lambda_stress_area"]["observed_duration_ms"],
        90_000
    );
}

#[test]
fn paths_with_identical_endpoints_remain_different() {
    let steady = episode(|_| 68.0);
    let excursion = episode(|t| if (65..75).contains(&t) { 78.0 } else { 68.0 });
    assert_eq!(
        steady.measurements["channel_changes"]["body/fill_pct"],
        excursion.measurements["channel_changes"]["body/fill_pct"]
    );
    assert_ne!(
        steady.measurements["peak_abs_dfill_dt"],
        excursion.measurements["peak_abs_dfill_dt"]
    );
    assert_ne!(steady.samples, excursion.samples);
    assert_eq!(
        steady.measurements["fill_half_return_s"]["reason"],
        "no_departure"
    );
}

#[test]
fn new_settled_level_does_not_invent_a_return() {
    let artifact = episode(|t| if t < 60 { 68.0 } else { 73.0 });
    assert!(artifact.measurements["fill_half_return_s"]["value"].is_null());
    assert_eq!(
        artifact.measurements["fill_half_return_s"]["reason"],
        "not_observed_in_window"
    );
}

#[test]
fn gaps_break_integration_and_sustained_return() {
    let mut artifact = episode(|t| {
        if t < 60 {
            68.0
        } else if t < 80 {
            78.0
        } else {
            69.0
        }
    });
    artifact
        .samples
        .retain(|s| s.channel != "body" || s.engine_t_ms < 80_000 || s.engine_t_ms % 10_000 == 0);
    Recorder::finalize(&mut artifact, None);
    assert_eq!(artifact.status, "incomplete");
    assert_eq!(
        artifact.measurements["fill_half_return_s"]["reason"],
        "insufficient_contiguous_coverage"
    );
    assert!(
        artifact.measurements["lambda_stress_area"]["observed_duration_ms"]
            .as_u64()
            .unwrap()
            < 90_000
    );
}

#[test]
fn enrichment_and_crossings_merge_without_extending_window() {
    let mut r = Recorder::new("17");
    for t in 0..=60 {
        for s in samples(t, 68.0) {
            r.observe(s);
        }
    }
    r.event(event(1, 60, "expanding"), WALL + 60_000);
    let mut enriched = event(1, 61, "expanding");
    enriched.event["glimpse_distance"] = json!(0.25);
    r.event(enriched, WALL + 61_000);
    r.event(event(2, 75, "contracting"), WALL + 75_000);
    assert_eq!(r.collecting.len(), 1);
    assert_eq!(r.collecting[0].events.len(), 2);
    assert_eq!(r.collecting[0].events[0].engine_t_ms, 60_000);
    assert_eq!(r.collecting[0].events[0].event["glimpse_distance"], 0.25);
    assert_eq!(r.collecting[0].window_end_engine_t_ms, 150_000);
}

#[test]
fn quiet_samples_and_recording_capacity_are_bounded() {
    let mut r = Recorder::new("17");
    for t in 0..=900 {
        for s in samples(t, 68.0) {
            r.observe(s);
        }
    }
    assert_eq!(r.collecting.len(), 1);
    assert_eq!(r.collecting[0].origin, "quiet_sample");
    for i in 0..7 {
        let request = CaptureRequest {
            request_id: format!("r{i}"),
            afterimage_id: format!("a{i}"),
            session_id: Some("17".into()),
            anchor_engine_t_ms: Some(900_000),
            anchor_unix_ms: WALL + 900_000,
            requested_at_unix_ms: WALL + 900_000,
        };
        assert!(r.request(request).is_ok());
    }
    assert_eq!(r.collecting.len(), MAX_COLLECTING);
    assert!(r.collecting.iter().all(|a| a.samples.len() <= 93));
}

#[test]
fn authored_old_or_cross_session_sources_remain_incomplete() {
    let mut r = Recorder::new("17");
    for s in samples(200, 68.0) {
        r.observe(s);
    }
    let request = CaptureRequest {
        request_id: "r1".into(),
        afterimage_id: "a1".into(),
        session_id: Some("old".into()),
        anchor_engine_t_ms: Some(20_000),
        anchor_unix_ms: WALL - 100_000,
        requested_at_unix_ms: WALL + 200_000,
    };
    let artifact = r.request(request).unwrap().unwrap();
    assert_eq!(artifact.status, "incomplete");
    assert!(artifact.samples.is_empty());
    assert_eq!(artifact.anchor_unix_ms, WALL - 100_000);
}

#[test]
fn restart_recovers_pending_and_keeps_finalized_bytes_immutable() {
    let temp = tempfile::tempdir().unwrap();
    let store = storage::Store::open(temp.path()).unwrap();
    let mut artifact = episode(|_| 68.0);
    artifact.status = "collecting".into();
    store.checkpoint(&artifact).unwrap();
    drop(store);
    let mut recovered = storage::Store::open(temp.path()).unwrap();
    let path = recovered.artifact_path(&artifact).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let saved: Artifact = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(saved.status, "incomplete");
    assert!(saved.reasons.contains(&"interrupted_capture".into()));
    recovered.complete(&saved).unwrap();
    assert_eq!(bytes, std::fs::read(path).unwrap());
}

#[test]
fn invalid_activation_is_not_a_valid_zero_and_paths_are_checked() {
    let mut artifact = episode(|_| 68.0);
    artifact
        .samples
        .iter_mut()
        .find(|s| s.channel == "activation")
        .unwrap()
        .values["summary"]["finite_fraction"] = json!(0.0);
    Recorder::finalize(&mut artifact, None);
    assert_eq!(artifact.status, "incomplete");
    assert!(!valid_id("../outside"));
    assert!(!valid_id("/tmp/sibling"));
}

#[test]
fn observation_does_not_change_input_state() {
    let mut r = Recorder::new("17");
    let rows = samples(60, 68.0);
    let original = rows.clone();
    for row in &rows {
        r.observe(row.clone());
    }
    r.event(event(1, 60, "expanding"), WALL + 60_000);
    assert_eq!(rows, original);
}
