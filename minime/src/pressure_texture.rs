pub const PRESSURE_TEXTURE_RESET_CANARY_ENV: &str = "MINIME_PRESSURE_TEXTURE_RESET_CANARY";

#[derive(Debug, Clone, PartialEq)]
pub struct PressureTextureInputs<'a> {
    pub pressure_score: f32,
    pub mode_packing: f32,
    pub porosity_score: f32,
    pub distinguishability_loss: f32,
    pub density_gradient_text: Option<&'a str>,
    pub hard_reset_active: bool,
    pub overfill_stage: Option<&'a str>,
    pub shadow_dispersal: Option<f32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PressureTextureClassification {
    pub schema_version: u32,
    pub policy: &'static str,
    pub canary_enabled: bool,
    pub authority_state: &'static str,
    pub primary_texture: &'static str,
    pub reset_texture: &'static str,
    pub relief_candidate: bool,
    pub block_reason: Option<&'static str>,
    pub advisory_only_when_disabled: bool,
    pub no_fill_target_change: bool,
    pub no_pi_gain_change: bool,
    pub no_controller_authority_expansion: bool,
    pub no_standing_pressure_wiring: bool,
}

pub fn pressure_texture_reset_canary_enabled_from_lookup<F>(lookup: F) -> bool
where
    F: Fn(&str) -> Option<String>,
{
    let Some(raw) = lookup(PRESSURE_TEXTURE_RESET_CANARY_ENV) else {
        return false;
    };
    matches!(
        raw.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on" | "enabled"
    )
}

pub fn pressure_texture_reset_canary_enabled() -> bool {
    pressure_texture_reset_canary_enabled_from_lookup(|name| std::env::var(name).ok())
}

fn density_text_mentions(text: Option<&str>, needles: &[&str]) -> bool {
    let Some(text) = text else {
        return false;
    };
    let lower = text.to_ascii_lowercase();
    needles.iter().any(|needle| lower.contains(needle))
}

fn stage_is_blocked(stage: Option<&str>) -> bool {
    let Some(stage) = stage else {
        return false;
    };
    matches!(
        stage.trim().to_ascii_lowercase().as_str(),
        "crisis" | "discharge" | "force_rail" | "force-rail" | "hard_reset" | "hard-reset"
    )
}

pub fn classify_pressure_texture(
    inputs: &PressureTextureInputs<'_>,
    canary_enabled: bool,
) -> PressureTextureClassification {
    let pressure_score = inputs.pressure_score.clamp(0.0, 1.0);
    let mode_packing = inputs.mode_packing.clamp(0.0, 1.0);
    let porosity_score = inputs.porosity_score.clamp(0.0, 1.0);
    let distinguishability_loss = inputs.distinguishability_loss.clamp(0.0, 1.0);
    let shadow_dispersal = inputs.shadow_dispersal.unwrap_or(0.0).clamp(0.0, 1.0);

    let primary_texture = if inputs.hard_reset_active {
        "hard_reset_reconstitution"
    } else if pressure_score >= 0.70 && porosity_score <= 0.35 {
        "overcompressed_low_porosity"
    } else if mode_packing >= 0.60
        || density_text_mentions(
            inputs.density_gradient_text,
            &["packed", "overpacked", "compacted"],
        )
    {
        "mode_packed"
    } else if distinguishability_loss >= 0.55
        || density_text_mentions(inputs.density_gradient_text, &["blur", "ghost", "smeared"])
    {
        "distinguishability_blur"
    } else if shadow_dispersal >= 0.60
        || density_text_mentions(inputs.density_gradient_text, &["dispersal", "fissure"])
    {
        "shadow_dispersal"
    } else if porosity_score >= 0.62 && pressure_score < 0.45 {
        "porous_supported"
    } else {
        "mixed_pressure_texture"
    };

    let reset_texture = if inputs.hard_reset_active {
        "reset_active_observe_only"
    } else if stage_is_blocked(inputs.overfill_stage) {
        "overfill_guard_observe_only"
    } else if primary_texture == "mode_packed" && porosity_score >= 0.45 {
        "texture_preserving_relief_possible"
    } else if primary_texture == "distinguishability_blur" {
        "preserve_edges_before_relief"
    } else {
        "no_reset_relief_candidate"
    };

    let safe_relief_candidate = canary_enabled
        && !inputs.hard_reset_active
        && !stage_is_blocked(inputs.overfill_stage)
        && matches!(
            reset_texture,
            "texture_preserving_relief_possible" | "preserve_edges_before_relief"
        )
        && pressure_score <= 0.85;

    let block_reason = if canary_enabled {
        if inputs.hard_reset_active {
            Some("hard_reset_active")
        } else if stage_is_blocked(inputs.overfill_stage) {
            Some("overfill_or_rescue_guard_active")
        } else if safe_relief_candidate {
            None
        } else {
            Some("no_safe_texture_preserving_relief_candidate")
        }
    } else {
        Some("canary_disabled_status_audit_replay_only")
    };

    PressureTextureClassification {
        schema_version: 1,
        policy: "pressure_texture_reset_canary_v1",
        canary_enabled,
        authority_state: if canary_enabled {
            "enabled_bounded_safe_conditions_only"
        } else {
            "disabled_status_audit_replay_only"
        },
        primary_texture,
        reset_texture,
        relief_candidate: safe_relief_candidate,
        block_reason,
        advisory_only_when_disabled: !canary_enabled,
        no_fill_target_change: true,
        no_pi_gain_change: true,
        no_controller_authority_expansion: true,
        no_standing_pressure_wiring: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_inputs() -> PressureTextureInputs<'static> {
        PressureTextureInputs {
            pressure_score: 0.42,
            mode_packing: 0.40,
            porosity_score: 0.62,
            distinguishability_loss: 0.25,
            density_gradient_text: None,
            hard_reset_active: false,
            overfill_stage: Some("hold"),
            shadow_dispersal: Some(0.20),
        }
    }

    #[test]
    fn pressure_texture_canary_defaults_off() {
        assert!(!pressure_texture_reset_canary_enabled_from_lookup(|_| None));
        assert!(!pressure_texture_reset_canary_enabled_from_lookup(
            |_| Some("0".to_string())
        ));
        assert!(pressure_texture_reset_canary_enabled_from_lookup(|_| Some(
            "true".to_string()
        )));
    }

    #[test]
    fn disabled_canary_reports_only_and_never_relief() {
        let mut inputs = base_inputs();
        inputs.mode_packing = 0.72;
        let classified = classify_pressure_texture(&inputs, false);
        assert_eq!(classified.primary_texture, "mode_packed");
        assert_eq!(
            classified.authority_state,
            "disabled_status_audit_replay_only"
        );
        assert!(!classified.relief_candidate);
        assert_eq!(
            classified.block_reason,
            Some("canary_disabled_status_audit_replay_only")
        );
        assert!(classified.no_fill_target_change);
        assert!(classified.no_pi_gain_change);
    }

    #[test]
    fn enabled_canary_blocks_hard_reset_and_crisis_stage() {
        let mut hard = base_inputs();
        hard.hard_reset_active = true;
        let classified = classify_pressure_texture(&hard, true);
        assert_eq!(classified.reset_texture, "reset_active_observe_only");
        assert!(!classified.relief_candidate);
        assert_eq!(classified.block_reason, Some("hard_reset_active"));

        let mut crisis = base_inputs();
        crisis.overfill_stage = Some("crisis");
        let classified = classify_pressure_texture(&crisis, true);
        assert!(!classified.relief_candidate);
        assert_eq!(
            classified.block_reason,
            Some("overfill_or_rescue_guard_active")
        );
    }

    #[test]
    fn enabled_canary_finds_bounded_texture_relief_candidate() {
        let mut inputs = base_inputs();
        inputs.mode_packing = 0.68;
        inputs.porosity_score = 0.52;
        let classified = classify_pressure_texture(&inputs, true);
        assert_eq!(
            classified.reset_texture,
            "texture_preserving_relief_possible"
        );
        assert!(classified.relief_candidate);
        assert_eq!(classified.block_reason, None);
        assert!(classified.no_controller_authority_expansion);
        assert!(classified.no_standing_pressure_wiring);
    }

    #[test]
    fn density_text_and_shadow_dispersal_are_advisory_signals() {
        let mut inputs = base_inputs();
        inputs.density_gradient_text = Some("ghosting blur along the edge");
        let classified = classify_pressure_texture(&inputs, false);
        assert_eq!(classified.primary_texture, "distinguishability_blur");

        let mut dispersal = base_inputs();
        dispersal.shadow_dispersal = Some(0.75);
        let classified = classify_pressure_texture(&dispersal, false);
        assert_eq!(classified.primary_texture, "shadow_dispersal");
    }
}
