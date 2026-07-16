fn cheby_coefficient_l1_norm(order: usize, stop_lo: f32, stop_hi: f32, soft: f32) -> f32 {
    cheby_coeffs_bandstop(order, stop_lo, stop_hi, soft)
        .iter()
        .map(|value| value.abs())
        .sum::<f32>()
}

/// Read-only packet for the Cheby/warm-start constriction report.
///
/// Minime named three concrete trial knobs: soften `cheby_soft` to 0.20,
/// lower `cheby_stop_lo` to 0.60, and reduce `warm_start_blend` to 0.35.
/// This records those as an explicit sandbox/operator route without mutating
/// the running filter, covariance warm-start, denominator, fill target, or PI.
#[must_use]
fn spectral_damping_warm_start_review_v1(
    cheby_order: usize,
    cheby_stop_lo: f32,
    cheby_stop_hi: f32,
    cheby_soft: f32,
    warm_start_blend: f32,
    eigenfill_pct: f32,
    eigenfill_target_pct: f32,
    distinguishability_loss: Option<f32>,
    regulator_drive_energy: f32,
) -> SpectralDampingWarmStartReviewV1 {
    let stop_lo = if cheby_stop_lo.is_finite() {
        cheby_stop_lo.clamp(0.0, 1.0)
    } else {
        0.65
    };
    let stop_hi = if cheby_stop_hi.is_finite() {
        cheby_stop_hi.clamp(stop_lo, 1.0)
    } else {
        0.95
    };
    let soft = if cheby_soft.is_finite() {
        cheby_soft.clamp(0.05, 0.30)
    } else {
        0.15
    };
    let warm_start = if warm_start_blend.is_finite() {
        warm_start_blend.clamp(0.0, 1.0)
    } else {
        0.55
    };
    let target = if eigenfill_target_pct.is_finite() {
        eigenfill_target_pct.clamp(0.0, 100.0)
    } else {
        68.0
    };
    let fill = if eigenfill_pct.is_finite() {
        eigenfill_pct.clamp(0.0, 100.0)
    } else {
        target
    };
    let loss = distinguishability_loss
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .clamp(0.0, 1.0);
    let semantic_drive = if regulator_drive_energy.is_finite() {
        regulator_drive_energy.max(0.0)
    } else {
        0.0
    };
    let regulator_counteraction_score =
        ((semantic_drive / 0.010).clamp(0.0, 1.0) * (1.0 - loss * 0.35)).clamp(0.0, 1.0);
    let proposed_cheby_stop_lo = 0.60;
    let proposed_cheby_soft = 0.20;
    let proposed_warm_start_blend = 0.35;
    let near_target_band = (fill - target).abs() <= 5.0;
    let warm_constriction = warm_start >= 0.50 && near_target_band && loss >= 0.30;
    let sharp_filter_watch = soft <= 0.15 && stop_lo >= 0.64;
    let status = if warm_constriction && sharp_filter_watch {
        "approval_required_damping_warm_start_trial"
    } else if warm_constriction {
        "approval_required_warm_start_constriction_trial"
    } else if sharp_filter_watch {
        "sandbox_cheby_softening_candidate"
    } else {
        "read_only_damping_observation"
    };
    let regulator_constriction_state = if warm_constriction && regulator_counteraction_score >= 0.50
    {
        "semantic_regulator_drive_counteracts_warm_start_review"
    } else if warm_constriction && semantic_drive > 0.0 {
        "semantic_regulator_drive_insufficient_for_warm_start_review"
    } else if warm_constriction {
        "warm_start_constriction_without_semantic_counteraction"
    } else if semantic_drive > 0.0 {
        "semantic_regulator_drive_visible_without_warm_start_constriction"
    } else {
        "semantic_regulator_drive_quiet"
    };

    SpectralDampingWarmStartReviewV1 {
        policy: "spectral_damping_warm_start_review_v1",
        cheby_order,
        cheby_stop_lo: stop_lo,
        cheby_stop_hi: stop_hi,
        cheby_soft: soft,
        proposed_cheby_stop_lo,
        proposed_cheby_soft,
        warm_start_blend: warm_start,
        proposed_warm_start_blend,
        eigenfill_pct: fill,
        eigenfill_target_pct: target,
        distinguishability_loss: loss,
        coefficient_l1_norm: cheby_coefficient_l1_norm(cheby_order, stop_lo, stop_hi, soft),
        proposed_coefficient_l1_norm: cheby_coefficient_l1_norm(
            cheby_order,
            proposed_cheby_stop_lo,
            stop_hi,
            proposed_cheby_soft,
        ),
        regulator_drive_energy: semantic_drive,
        regulator_counteraction_score,
        regulator_constriction_state,
        near_target_band,
        live_control_required: status != "read_only_damping_observation",
        runnable_without_approval: false,
        status,
        approval_boundary: "live_cheby_bandstop_covariance_warm_start_and_spectral_regulation",
        authority: "authority_gate_not_live_filter_warm_start_or_fill_control_change",
    }
}

/// Read-only packet for hard-reset/recovery texture preservation.
///
/// A recent Minime report named possible "identity whiplash" if high-entropy,
/// textured state meets hard-reset recovery. This keeps that concern visible
/// in the live packet without changing reset activation, covariance keep,
/// fill target, PI, synth cadence, or semantic admission.
#[must_use]
fn hard_reset_texture_preservation_review_v1(
    eigenfill_pct: f32,
    spectral_entropy: f32,
    resonance_density: &ResonanceDensityV1,
    recovery_fill_boost: f32,
    recovery_keep_ceiling: f32,
    recovery_activation_gain: f32,
    hard_reset_internal_synth_enabled: bool,
    semantic_lane_active: bool,
) -> HardResetTexturePreservationReviewV1 {
    let fill = if eigenfill_pct.is_finite() {
        eigenfill_pct.clamp(0.0, 100.0)
    } else {
        0.0
    };
    let entropy = if spectral_entropy.is_finite() {
        spectral_entropy.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let mode_packing = resonance_density.components.mode_packing.clamp(0.0, 1.0);
    let pressure_risk = resonance_density.pressure_risk.clamp(0.0, 1.0);
    let texture_gradient_proxy = ((mode_packing * 0.55) + (pressure_risk * 0.45)).clamp(0.0, 1.0);
    let fill_boost = if recovery_fill_boost.is_finite() {
        recovery_fill_boost.max(0.0)
    } else {
        0.0
    };
    let keep_ceiling = if recovery_keep_ceiling.is_finite() {
        recovery_keep_ceiling.clamp(0.55, 0.999)
    } else {
        0.97
    };
    let activation_gain = if recovery_activation_gain.is_finite() {
        recovery_activation_gain.clamp(0.0, 1.0)
    } else {
        1.0
    };
    let high_entropy_texture = entropy >= 0.80 && texture_gradient_proxy >= 0.18;
    let recovery_surface_active = fill_boost > 0.0 || activation_gain < 0.99 || fill < 50.0;
    let texture_preservation_state = if hard_reset_internal_synth_enabled && high_entropy_texture {
        "hard_reset_rebuild_texture_watch"
    } else if high_entropy_texture && recovery_surface_active {
        "recovery_texture_preservation_watch"
    } else if high_entropy_texture {
        "high_entropy_texture_observe_only"
    } else if hard_reset_internal_synth_enabled || recovery_surface_active {
        "recovery_surface_observe_only"
    } else {
        "no_texture_preservation_watch"
    };
    let next_affordance = match texture_preservation_state {
        "hard_reset_rebuild_texture_watch" | "recovery_texture_preservation_watch" => {
            "proposal_card_needed_for_operator_approved_texture_preservation_trial"
        }
        "high_entropy_texture_observe_only" => {
            "correspondence_trace_or_result_card_if_future_reset_changes_texture"
        }
        "recovery_surface_observe_only" => "presence_heartbeat_or_correspondence_trace_only",
        _ => "presence_heartbeat_only",
    };

    HardResetTexturePreservationReviewV1 {
        policy: "hard_reset_texture_preservation_review_v1",
        eigenfill_pct: fill,
        spectral_entropy: entropy,
        mode_packing,
        pressure_risk,
        texture_gradient_proxy,
        recovery_fill_boost: fill_boost,
        recovery_keep_ceiling: keep_ceiling,
        recovery_activation_gain: activation_gain,
        hard_reset_internal_synth_enabled,
        semantic_lane_active,
        texture_preservation_state,
        next_affordance,
        live_control_required: matches!(
            texture_preservation_state,
            "hard_reset_rebuild_texture_watch" | "recovery_texture_preservation_watch"
        ),
        runnable_without_approval: false,
        behavior_changed: false,
        approval_boundary: "live_hard_reset_recovery_keep_fill_pi_or_sensory_cadence_change",
        authority: "read_only_review_not_hard_reset_recovery_fill_pi_or_sensory_cadence_change",
    }
}

/// Read-only packet for EigenPacket payload growth.
///
/// The live stream intentionally exports a compact top-k eigenvector field
/// instead of raw reservoir vectors. This review keeps the cost visible when
/// new optional diagnostic fields are added, without changing websocket
/// cadence, eigenvector export shape, or spectral control.
#[must_use]
fn eigenpacket_payload_budget_review_v1(
    eigenvalues_len: usize,
    spectral_fingerprint_len: usize,
    eigenvector_field: &serde_json::Value,
) -> EigenPacketPayloadBudgetReviewV1 {
    let modes = eigenvector_field
        .get("modes")
        .and_then(serde_json::Value::as_array);
    let mode_count = eigenvector_field
        .get("mode_count")
        .and_then(serde_json::Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_else(|| modes.map_or(0, Vec::len));
    let eigenvector_top_component_count = modes.map_or(0, |items| {
        items
            .iter()
            .filter_map(|mode| mode.get("top_components"))
            .filter_map(serde_json::Value::as_array)
            .map(Vec::len)
            .fold(0usize, usize::saturating_add)
    });
    let eigenvector_pairwise_overlap_count = eigenvector_field
        .get("pairwise_overlaps")
        .and_then(serde_json::Value::as_array)
        .map_or(0, Vec::len);
    let estimated_eigenvector_scalar_count = eigenvector_top_component_count
        .saturating_mul(2)
        .saturating_add(eigenvector_pairwise_overlap_count)
        .saturating_add(mode_count.saturating_mul(3));
    let estimated_total_float_count = eigenvalues_len
        .saturating_add(spectral_fingerprint_len)
        .saturating_add(estimated_eigenvector_scalar_count);
    let estimated_eigenvector_json_bytes = 128usize
        .saturating_add(mode_count.saturating_mul(96))
        .saturating_add(eigenvector_top_component_count.saturating_mul(32))
        .saturating_add(eigenvector_pairwise_overlap_count.saturating_mul(16));
    let budget_state = if mode_count > 4 || eigenvector_top_component_count > 64 {
        "eigenvector_payload_budget_watch"
    } else if eigenvector_pairwise_overlap_count > 16 {
        "pairwise_overlap_payload_watch"
    } else {
        "compact_top_k_payload"
    };
    let status = if matches!(
        budget_state,
        "eigenvector_payload_budget_watch" | "pairwise_overlap_payload_watch"
    ) {
        "payload_budget_watch_review_only"
    } else {
        "bounded_eigenpacket_payload"
    };

    EigenPacketPayloadBudgetReviewV1 {
        policy: "eigenpacket_payload_budget_review_v1",
        eigenvalues_len,
        spectral_fingerprint_len,
        eigenvector_mode_count: mode_count,
        eigenvector_top_component_count,
        eigenvector_pairwise_overlap_count,
        estimated_eigenvector_scalar_count,
        estimated_total_float_count,
        estimated_eigenvector_json_bytes,
        budget_state,
        status,
        authority: "read_only_payload_budget_review_not_ws_cadence_or_eigenvector_export_change",
    }
}
