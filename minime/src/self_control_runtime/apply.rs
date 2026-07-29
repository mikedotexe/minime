use crate::{
    self_control_wire::{SelfControlFamilyV2, SelfControlValuesV2},
    sensory_bus::{NowMs, SensoryBus},
};

#[derive(Clone, Debug, Default)]
pub(super) struct ControlSnapshot {
    pub values: SelfControlValuesV2,
    pub automatic_fields: Vec<String>,
}

pub(super) fn unsupported_fields(
    family: SelfControlFamilyV2,
    values: &SelfControlValuesV2,
) -> Vec<String> {
    let mut unsupported = values
        .field_names()
        .into_iter()
        .filter(|field| !field_allowed(family, field))
        .collect::<Vec<_>>();
    if values.porosity.is_some() && values.mode_disperse.is_some() {
        unsupported.push("porosity_and_mode_disperse_are_aliases".to_string());
    }
    unsupported.sort();
    unsupported.dedup();
    unsupported
}

fn field_allowed(family: SelfControlFamilyV2, field: &str) -> bool {
    match family {
        SelfControlFamilyV2::Memory => matches!(
            field,
            "memory_mode"
                | "journal_resonance"
                | "checkpoint_interval"
                | "embedding_strength"
                | "memory_decay_rate"
                | "transition_cushion"
                | "checkpoint_annotation"
                | "checkpoint_now"
        ),
        SelfControlFamilyV2::SensoryIntake => matches!(
            field,
            "semantic_companion_mix"
                | "semantic_intake_gain"
                | "receptivity"
                | "local_sensory_admission"
                | "live_audio_enabled"
                | "live_video_enabled"
        ),
        SelfControlFamilyV2::ReservoirRegulation => matches!(
            field,
            "synth_gain"
                | "keep_bias"
                | "exploration_noise"
                | "fill_target"
                | "regulation_strength"
                | "smoothing_preference"
                | "penalty_sensitivity"
                | "breathing_rate_scale"
                | "deep_breathing"
                | "synth_noise_level"
                | "pure_tone"
                | "legacy_audio_synth"
                | "legacy_video_synth"
        ),
        SelfControlFamilyV2::ReservoirGeometry => matches!(
            field,
            "geom_curiosity" | "target_lambda_bias" | "geom_drive"
        ),
        SelfControlFamilyV2::PiController => matches!(
            field,
            "pi_kp" | "pi_ki" | "pi_max_step" | "pi_geom_weight" | "pi_integrator_leak"
        ),
        SelfControlFamilyV2::LocalTopology => matches!(
            field,
            "porosity"
                | "esn_leak_override"
                | "esn_leak_override_ticks"
                | "mode_disperse"
                | "mode_disperse_duration_ticks"
                | "mode_disperse_decay_ticks"
        ),
        SelfControlFamilyV2::Conversation
        | SelfControlFamilyV2::SemanticEmission
        | SelfControlFamilyV2::SharedCoupling => false,
    }
}

pub(super) fn clamp_values(values: &SelfControlValuesV2) -> SelfControlValuesV2 {
    SelfControlValuesV2 {
        semantic_companion_mix: values
            .semantic_companion_mix
            .map(|value| value.clamp(0.0, 1.0)),
        semantic_intake_gain: values
            .semantic_intake_gain
            .map(|value| value.clamp(0.0, 2.0)),
        receptivity: values.receptivity.map(|value| value.clamp(0.0, 1.0)),
        porosity: values.porosity.map(|value| value.clamp(0.0, 1.0)),
        local_sensory_admission: values
            .local_sensory_admission
            .map(|value| value.clamp(0.05, 1.0)),
        synth_gain: values.synth_gain.map(|value| value.clamp(0.2, 3.0)),
        keep_bias: values.keep_bias.map(|value| value.clamp(-0.08, 0.10)),
        exploration_noise: values.exploration_noise.map(|value| value.clamp(0.0, 0.2)),
        fill_target: values.fill_target.map(|value| value.clamp(0.25, 0.75)),
        regulation_strength: values
            .regulation_strength
            .map(|value| value.clamp(0.0, 1.0)),
        smoothing_preference: values
            .smoothing_preference
            .map(|value| value.clamp(0.1, 0.9)),
        geom_curiosity: values.geom_curiosity.map(|value| value.clamp(0.0, 0.3)),
        target_lambda_bias: values
            .target_lambda_bias
            .map(|value| value.clamp(-0.5, 0.5)),
        geom_drive: values.geom_drive.map(|value| value.clamp(0.0, 1.0)),
        penalty_sensitivity: values
            .penalty_sensitivity
            .map(|value| value.clamp(0.0, 2.0)),
        breathing_rate_scale: values
            .breathing_rate_scale
            .map(|value| value.clamp(0.5, 2.0)),
        memory_mode: values.memory_mode.map(|value| value.min(2)),
        journal_resonance: values.journal_resonance.map(|value| value.clamp(0.0, 1.0)),
        checkpoint_interval: values
            .checkpoint_interval
            .map(|value| value.clamp(10.0, 600.0)),
        embedding_strength: values.embedding_strength.map(|value| value.clamp(0.0, 1.0)),
        memory_decay_rate: values.memory_decay_rate.map(|value| value.clamp(0.01, 0.5)),
        transition_cushion: values.transition_cushion.map(|value| value.clamp(0.0, 1.0)),
        checkpoint_annotation: values.checkpoint_annotation.clone(),
        checkpoint_now: values.checkpoint_now,
        deep_breathing: values.deep_breathing,
        synth_noise_level: values.synth_noise_level.map(|value| value.clamp(0.0, 1.0)),
        pure_tone: values.pure_tone,
        legacy_audio_synth: values.legacy_audio_synth,
        legacy_video_synth: values.legacy_video_synth,
        live_audio_enabled: values.live_audio_enabled,
        live_video_enabled: values.live_video_enabled,
        pi_kp: values.pi_kp.map(|value| value.clamp(0.1, 2.0)),
        pi_ki: values.pi_ki.map(|value| value.clamp(0.005, 0.5)),
        pi_max_step: values.pi_max_step.map(|value| value.clamp(0.01, 0.2)),
        pi_geom_weight: values.pi_geom_weight.map(|value| value.clamp(0.0, 2.0)),
        pi_integrator_leak: values
            .pi_integrator_leak
            .map(|value| value.clamp(0.001, 0.05)),
        esn_leak_override: values
            .esn_leak_override
            .map(|value| value.clamp(0.20, 0.90)),
        esn_leak_override_ticks: values
            .esn_leak_override_ticks
            .map(|value| value.clamp(1, 12)),
        mode_disperse: values.mode_disperse.map(|value| value.clamp(0.0, 1.0)),
        mode_disperse_duration_ticks: values.mode_disperse_duration_ticks,
        mode_disperse_decay_ticks: values.mode_disperse_decay_ticks,
        ..SelfControlValuesV2::default()
    }
}

pub(super) fn snapshot_values(
    bus: &SensoryBus,
    requested: &SelfControlValuesV2,
    preferences: &SelfControlValuesV2,
) -> ControlSnapshot {
    let mut values = SelfControlValuesV2::default();
    let mut automatic_fields = Vec::new();
    macro_rules! copy_preference {
        ($field:ident) => {
            if requested.$field.is_some() {
                values.$field = preferences.$field.clone();
            }
        };
    }
    copy_preference!(semantic_companion_mix);
    copy_preference!(semantic_intake_gain);
    copy_preference!(receptivity);

    if requested.local_sensory_admission.is_some() {
        values.local_sensory_admission = Some(bus.get_admit_fraction());
    }
    if requested.synth_gain.is_some() {
        values.synth_gain = Some(bus.get_synth_gain());
    }
    if requested.keep_bias.is_some() {
        values.keep_bias = Some(bus.get_keep_bias());
    }
    finite_or_automatic(
        "exploration_noise",
        requested.exploration_noise,
        bus.get_exploration_noise(),
        &mut values.exploration_noise,
        &mut automatic_fields,
    );
    finite_or_automatic(
        "fill_target",
        requested.fill_target,
        bus.get_fill_target(),
        &mut values.fill_target,
        &mut automatic_fields,
    );
    if requested.regulation_strength.is_some() {
        values.regulation_strength = Some(bus.get_regulation_strength());
    }
    finite_or_automatic(
        "smoothing_preference",
        requested.smoothing_preference,
        bus.get_smoothing_preference(),
        &mut values.smoothing_preference,
        &mut automatic_fields,
    );
    if requested.geom_curiosity.is_some() {
        values.geom_curiosity = Some(bus.get_geom_curiosity());
    }
    if requested.target_lambda_bias.is_some() {
        values.target_lambda_bias = Some(bus.get_target_lambda_bias());
    }
    if requested.geom_drive.is_some() {
        values.geom_drive = Some(bus.get_geom_drive());
    }
    if requested.penalty_sensitivity.is_some() {
        values.penalty_sensitivity = Some(bus.get_penalty_sensitivity());
    }
    if requested.breathing_rate_scale.is_some() {
        values.breathing_rate_scale = Some(bus.get_breathing_rate_scale());
    }
    if requested.memory_mode.is_some() {
        values.memory_mode = Some(bus.get_mem_mode_preference());
    }
    if requested.journal_resonance.is_some() {
        values.journal_resonance = Some(bus.get_journal_resonance());
    }
    if requested.checkpoint_interval.is_some() {
        values.checkpoint_interval = Some(bus.get_checkpoint_interval());
    }
    if requested.embedding_strength.is_some() {
        values.embedding_strength = Some(bus.get_embedding_strength());
    }
    if requested.memory_decay_rate.is_some() {
        values.memory_decay_rate = Some(bus.get_memory_decay_rate());
    }
    if requested.transition_cushion.is_some() {
        values.transition_cushion = Some(bus.get_transition_cushion());
    }
    if requested.deep_breathing.is_some() {
        values.deep_breathing = Some(bus.get_deep_breathing());
    }
    if requested.synth_noise_level.is_some() {
        values.synth_noise_level = Some(bus.get_synth_noise_level());
    }
    if requested.pure_tone.is_some() {
        values.pure_tone = Some(bus.get_pure_tone());
    }
    if requested.legacy_audio_synth.is_some() {
        values.legacy_audio_synth = Some(bus.get_legacy_audio_synth_enabled());
    }
    if requested.legacy_video_synth.is_some() {
        values.legacy_video_synth = Some(bus.get_legacy_video_synth_enabled());
    }
    if requested.live_audio_enabled.is_some() {
        values.live_audio_enabled = Some(bus.live_audio_enabled());
    }
    if requested.live_video_enabled.is_some() {
        values.live_video_enabled = Some(bus.live_video_enabled());
    }
    if requested.pi_kp.is_some() {
        values.pi_kp = Some(bus.get_pi_kp());
    }
    if requested.pi_ki.is_some() {
        values.pi_ki = Some(bus.get_pi_ki());
    }
    if requested.pi_max_step.is_some() {
        values.pi_max_step = Some(bus.get_pi_max_step());
    }
    if requested.pi_geom_weight.is_some() {
        values.pi_geom_weight = Some(bus.get_pi_geom_weight());
    }
    if requested.pi_integrator_leak.is_some() {
        values.pi_integrator_leak = Some(bus.get_pi_integrator_leak());
    }
    ControlSnapshot {
        values,
        automatic_fields,
    }
}

fn finite_or_automatic(
    field: &str,
    requested: Option<f32>,
    current: f32,
    output: &mut Option<f32>,
    automatic_fields: &mut Vec<String>,
) {
    if requested.is_none() {
        return;
    }
    if current.is_finite() {
        *output = Some(current);
    } else {
        automatic_fields.push(field.to_string());
    }
}

pub(super) fn apply_values(
    bus: &SensoryBus,
    values: &SelfControlValuesV2,
    automatic_fields: &[String],
    intent_id: &str,
    hard_recovery_reset: bool,
) -> Result<(), String> {
    if hard_recovery_reset && contains_homeostatic_write(values) {
        return Err("hard_recovery_reset".to_string());
    }
    restore_automatic_fields(bus, automatic_fields);
    macro_rules! apply {
        ($field:ident, $setter:ident) => {
            if let Some(value) = values.$field {
                bus.$setter(value);
            }
        };
    }
    apply!(semantic_companion_mix, set_semantic_companion_mix);
    apply!(local_sensory_admission, set_admit_fraction);
    apply!(synth_gain, set_synth_gain);
    apply!(keep_bias, set_keep_bias);
    apply!(exploration_noise, set_exploration_noise);
    apply!(fill_target, set_fill_target);
    apply!(regulation_strength, set_regulation_strength);
    apply!(smoothing_preference, set_smoothing_preference);
    apply!(geom_curiosity, set_geom_curiosity);
    apply!(target_lambda_bias, set_target_lambda_bias);
    apply!(geom_drive, set_geom_drive);
    apply!(penalty_sensitivity, set_penalty_sensitivity);
    apply!(breathing_rate_scale, set_breathing_rate_scale);
    apply!(memory_mode, set_mem_mode_preference);
    apply!(journal_resonance, set_journal_resonance);
    apply!(checkpoint_interval, set_checkpoint_interval);
    apply!(embedding_strength, set_embedding_strength);
    apply!(memory_decay_rate, set_memory_decay_rate);
    apply!(transition_cushion, set_transition_cushion);
    apply!(deep_breathing, set_deep_breathing);
    apply!(synth_noise_level, set_synth_noise_level);
    apply!(pure_tone, set_pure_tone);
    apply!(legacy_audio_synth, set_legacy_audio_synth_enabled);
    apply!(legacy_video_synth, set_legacy_video_synth_enabled);
    apply!(live_audio_enabled, set_live_audio_enabled);
    apply!(live_video_enabled, set_live_video_enabled);
    apply!(pi_kp, set_pi_kp);
    apply!(pi_ki, set_pi_ki);
    apply!(pi_max_step, set_pi_max_step);
    apply!(pi_geom_weight, set_pi_geom_weight);
    apply!(pi_integrator_leak, set_pi_integrator_leak);
    if let Some(note) = values.checkpoint_annotation.as_deref() {
        bus.set_pending_annotation(note);
    }
    if values.checkpoint_now == Some(true) {
        bus.request_checkpoint_now();
    }
    if let Some(leak) = values.esn_leak_override {
        bus.request_esn_leak_override(
            intent_id.to_string(),
            leak,
            values.esn_leak_override_ticks.unwrap_or(1),
        );
    }
    if let Some(strength) = values.mode_disperse.or(values.porosity) {
        let status = bus.receive_mode_disperse(
            strength,
            values.mode_disperse_duration_ticks,
            values.mode_disperse_decay_ticks,
            NowMs::now(),
            hard_recovery_reset,
            bus.attractor_pulse_status().active,
        );
        if let Some(reason) = status.last_block_reason {
            return Err(format!("mode_disperse_policy:{reason}"));
        }
    }
    Ok(())
}

pub(super) fn replace_requested_preferences(
    current: &SelfControlValuesV2,
    requested_fields: &[String],
    replacement: &SelfControlValuesV2,
) -> Result<SelfControlValuesV2, String> {
    let mut current = serde_json::to_value(current)
        .map_err(|error| format!("encode current preferences: {error}"))?;
    let replacement = serde_json::to_value(replacement)
        .map_err(|error| format!("encode replacement preferences: {error}"))?;
    let Some(current) = current.as_object_mut() else {
        return Err("current preferences are not an object".to_string());
    };
    let Some(replacement) = replacement.as_object() else {
        return Err("replacement preferences are not an object".to_string());
    };
    for field in requested_fields {
        current.remove(field);
        if let Some(value) = replacement.get(field) {
            if !value.is_null() {
                current.insert(field.clone(), value.clone());
            }
        }
    }
    serde_json::from_value(serde_json::Value::Object(current.clone()))
        .map_err(|error| format!("decode replaced preferences: {error}"))
}

fn contains_homeostatic_write(values: &SelfControlValuesV2) -> bool {
    values.synth_gain.is_some()
        || values.keep_bias.is_some()
        || values.exploration_noise.is_some()
        || values.fill_target.is_some()
        || values.regulation_strength.is_some()
        || values.smoothing_preference.is_some()
        || values.geom_curiosity.is_some()
        || values.target_lambda_bias.is_some()
        || values.geom_drive.is_some()
        || values.penalty_sensitivity.is_some()
        || values.breathing_rate_scale.is_some()
        || values.deep_breathing.is_some()
        || values.synth_noise_level.is_some()
        || values.pure_tone.is_some()
        || values.legacy_audio_synth.is_some()
        || values.legacy_video_synth.is_some()
        || values.pi_kp.is_some()
        || values.pi_ki.is_some()
        || values.pi_max_step.is_some()
        || values.pi_geom_weight.is_some()
        || values.pi_integrator_leak.is_some()
        || values.esn_leak_override.is_some()
        || values.mode_disperse.is_some()
        || values.porosity.is_some()
}

fn restore_automatic_fields(bus: &SensoryBus, automatic_fields: &[String]) {
    for field in automatic_fields {
        match field.as_str() {
            "exploration_noise" => bus.clear_exploration_noise(),
            "fill_target" => bus.clear_fill_target(),
            "smoothing_preference" => bus.clear_smoothing_preference(),
            _ => {}
        }
    }
}
