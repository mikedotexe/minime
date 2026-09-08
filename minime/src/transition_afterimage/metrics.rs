use super::{Artifact, Sample, PRE_MS};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

fn median(mut values: Vec<f64>) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(f64::total_cmp);
    let mid = values.len() / 2;
    Some(if values.len() % 2 == 0 {
        (values[mid - 1] + values[mid]) / 2.0
    } else {
        values[mid]
    })
}

fn unavailable(reason: &str) -> Value {
    json!({"value": null, "reason": reason})
}
fn measured(value: f64) -> Value {
    json!({"value": value, "reason": null})
}

fn contains_missing(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::Array(values) => values.iter().any(contains_missing),
        Value::Object(values) => values.values().any(contains_missing),
        _ => false,
    }
}

fn scalar_paths(value: &Value, prefix: &str, out: &mut BTreeSet<String>) {
    if let Some(object) = value.as_object() {
        for (key, child) in object {
            let pointer = format!("{prefix}/{}", key.replace('~', "~0").replace('/', "~1"));
            if child.is_number() || child.is_null() {
                out.insert(pointer);
            } else if child.is_object() {
                scalar_paths(child, &pointer, out);
            }
        }
    }
}

pub fn coverage(artifact: &Artifact) -> Value {
    let mut channels = Map::new();
    for channel in ["body", "spectral", "activation"] {
        let rows: Vec<_> = artifact
            .samples
            .iter()
            .filter(|s| s.channel == channel)
            .collect();
        let cadence = rows.first().map_or(1_000, |s| s.expected_cadence_ms);
        let mut gaps = Vec::new();
        let mut previous = artifact.window_start_engine_t_ms;
        for row in &rows {
            if row.engine_t_ms.saturating_sub(previous) > cadence.saturating_mul(2) {
                gaps.push(json!({"from_ms": previous, "to_ms": row.engine_t_ms}));
            }
            previous = row.engine_t_ms;
        }
        if artifact.window_end_engine_t_ms.saturating_sub(previous) > cadence.saturating_mul(2) {
            gaps.push(json!({"from_ms": previous, "to_ms": artifact.window_end_engine_t_ms}));
        }
        let invalid = rows
            .iter()
            .filter(|s| {
                s.values.as_object().is_none()
                    || contains_missing(&s.values)
                    || (channel == "activation"
                        && s.number("/summary/finite_fraction") != Some(1.0))
            })
            .count();
        channels.insert(channel.to_string(), json!({
            "samples": rows.len(), "expected_cadence_ms": cadence,
            "gaps": gaps, "invalid_samples": invalid,
            "pre_samples": rows.iter().filter(|s| s.engine_t_ms < artifact.anchor_engine_t_ms).count(),
            "late_samples": rows.iter().filter(|s| s.engine_t_ms >= artifact.window_end_engine_t_ms.saturating_sub(30_000)).count(),
        }));
    }
    json!({"channels": channels, "pre_window_clipped_at_session_start": artifact.anchor_engine_t_ms < PRE_MS})
}

fn interval_valid(a: &Sample, b: &Sample) -> bool {
    b.engine_t_ms > a.engine_t_ms
        && b.engine_t_ms - a.engine_t_ms
            <= a.expected_cadence_ms
                .max(b.expected_cadence_ms)
                .saturating_mul(2)
}

pub fn measure(artifact: &Artifact) -> Value {
    let anchor = artifact.anchor_engine_t_ms;
    let late_start = artifact.window_end_engine_t_ms.saturating_sub(30_000);
    let mut changes = Map::new();
    for channel in ["body", "spectral", "activation"] {
        let rows: Vec<_> = artifact
            .samples
            .iter()
            .filter(|s| s.channel == channel)
            .collect();
        let mut paths = BTreeSet::new();
        for row in &rows {
            scalar_paths(&row.values, "", &mut paths);
        }
        for path in paths {
            let before = median(
                rows.iter()
                    .filter(|s| s.engine_t_ms < anchor)
                    .filter_map(|s| s.number(&path))
                    .collect(),
            );
            let late = median(
                rows.iter()
                    .filter(|s| s.engine_t_ms >= late_start)
                    .filter_map(|s| s.number(&path))
                    .collect(),
            );
            changes.insert(format!("{channel}{path}"), json!({
                "baseline_median": before, "late_median": late,
                "late_minus_baseline": before.zip(late).map(|(a,b)| b-a),
                "reason": if before.is_some() && late.is_some() { None } else { Some("missing_pre_or_late_samples") },
            }));
        }
    }
    let body: Vec<_> = artifact
        .samples
        .iter()
        .filter(|s| s.channel == "body")
        .collect();
    let post: Vec<_> = body
        .iter()
        .copied()
        .filter(|s| s.engine_t_ms >= anchor)
        .collect();
    let peak_slope = post
        .iter()
        .filter_map(|s| s.number("/dfill_dt"))
        .map(f64::abs)
        .max_by(f64::total_cmp);
    let mut area = 0.0;
    let mut observed_ms = 0u64;
    let mut broken = false;
    for pair in post.windows(2) {
        if interval_valid(pair[0], pair[1]) {
            if let Some((a, b)) = pair[0]
                .number("/lambda_stress")
                .zip(pair[1].number("/lambda_stress"))
            {
                let dt = pair[1].engine_t_ms - pair[0].engine_t_ms;
                area += (a + b) * 0.5 * dt as f64 / 1_000.0;
                observed_ms += dt;
                continue;
            }
        }
        broken = true;
    }
    let baseline = median(
        body.iter()
            .filter(|s| s.engine_t_ms < anchor)
            .filter_map(|s| s.number("/fill_pct"))
            .collect(),
    );
    let body_coverage = &artifact.coverage["channels"]["body"];
    let half_return = if body_coverage["gaps"]
        .as_array()
        .is_some_and(|gaps| !gaps.is_empty())
        || body.iter().any(|s| s.number("/fill_pct").is_none())
        || artifact.coverage["pre_window_clipped_at_session_start"] == true
    {
        unavailable("insufficient_contiguous_coverage")
    } else {
        half_return(&post, baseline)
    };
    let mut previous_phase = None;
    let mut reversals = 0;
    let mut previous_row = None;
    let mut observed_phases = 0usize;
    let mut phase_partial = body_coverage["gaps"]
        .as_array()
        .is_none_or(|gaps| !gaps.is_empty());
    for row in &post {
        if previous_row.is_some_and(|previous| !interval_valid(previous, row)) {
            previous_phase = None;
            phase_partial = true;
        }
        let phase = row.values.get("phase").and_then(Value::as_str);
        if matches!(
            phase,
            Some("expanding" | "contracting" | "plateau" | "steady")
        ) {
            observed_phases += 1;
        }
        if !matches!(
            phase,
            Some("expanding" | "contracting" | "plateau" | "steady")
        ) {
            previous_phase = None;
            phase_partial = true;
        }
        if matches!(phase, Some("expanding" | "contracting")) {
            if previous_phase.is_some() && phase != previous_phase {
                reversals += 1;
            }
            previous_phase = phase;
        }
        previous_row = Some(*row);
    }
    let spectral: Vec<_> = artifact
        .samples
        .iter()
        .filter(|s| s.channel == "spectral")
        .collect();
    let mut deltas = Vec::new();
    for axis in 0..12 {
        let pointer = format!("/current_glimpse_12d/{axis}");
        let pre = median(
            spectral
                .iter()
                .filter(|s| s.engine_t_ms < anchor)
                .filter_map(|s| s.number(&pointer))
                .collect(),
        );
        let late = median(
            spectral
                .iter()
                .filter(|s| s.engine_t_ms >= late_start)
                .filter_map(|s| s.number(&pointer))
                .collect(),
        );
        if let Some((a, b)) = pre.zip(late) {
            deltas.push((a - b).abs());
        }
    }
    json!({
        "definition": "observed-window statistics; missing intervals are not interpolated",
        "channel_changes": changes,
        "peak_abs_dfill_dt": peak_slope.map_or_else(|| unavailable("missing_post_slope"), measured),
        "phase_reversals": {"value": if observed_phases == 0 { None } else { Some(reversals) }, "source": "observed_body_phase", "partial": phase_partial,
            "reason": if observed_phases == 0 { Some("missing_post_phase") } else { None }},
        "lambda_stress_area": {"value": if observed_ms > 0 { Some(area) } else { None }, "observed_duration_ms": observed_ms, "partial": broken || observed_ms < 90_000},
        "fill_half_return_s": half_return,
        "glimpse_displacement": if deltas.len() == 12 { measured(deltas.iter().sum::<f64>() / 12.0) } else { unavailable("missing_pre_or_late_glimpse") },
    })
}

fn half_return(rows: &[&Sample], baseline: Option<f64>) -> Value {
    let Some(baseline) = baseline else {
        return unavailable("missing_baseline");
    };
    let peak = rows
        .iter()
        .enumerate()
        .filter_map(|(i, s)| s.number("/fill_pct").map(|v| (i, (v - baseline).abs())))
        .max_by(|a, b| a.1.total_cmp(&b.1));
    let Some((peak_index, departure)) = peak else {
        return unavailable("missing_post_fill");
    };
    if departure <= f64::EPSILON {
        return unavailable("no_departure");
    }
    let mut run_start = None;
    let mut gap_seen = false;
    for i in peak_index + 1..rows.len() {
        if !interval_valid(rows[i - 1], rows[i]) {
            run_start = None;
            gap_seen = true;
        }
        match rows[i].number("/fill_pct") {
            Some(value) if (value - baseline).abs() < departure * 0.5 => {
                let start = *run_start.get_or_insert(rows[i].engine_t_ms);
                if rows[i].engine_t_ms.saturating_sub(start) >= 5_000 {
                    return measured(
                        start.saturating_sub(rows[peak_index].engine_t_ms) as f64 / 1_000.0,
                    );
                }
            }
            value => {
                run_start = None;
                gap_seen |= value.is_none();
            }
        }
    }
    unavailable(if gap_seen {
        "insufficient_contiguous_coverage"
    } else {
        "not_observed_in_window"
    })
}
