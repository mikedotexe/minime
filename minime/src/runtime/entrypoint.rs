#[tokio::main]
pub(crate) async fn run() -> Result<()> {
    let cli = Cli::parse();

    match cli.cmd {
        Cmd::Run {
            cov_dim,
            k,
            ws_addr,
            sensory_ws_addr,
            enable_bandstop,
            log_homeostat,
            quiet,
            log_esn_profile,
            log_esn_async_profile,
            log_handoff_diagnostics,
            esn_introspection_policy,
            esn_introspection_power_steps,
            cheby_order,
            cheby_stop_lo,
            cheby_stop_hi,
            cheby_soft,
            eigenfill_target,
            warm_start_blend,
            semantic_stale_shape,
            surge_threshold,
            reg_tick_secs,
            enable_gpu_av,
            av_ws_addr,
            legacy_audio_synth_enabled,
            legacy_video_synth_enabled,
        } => {
            run_engine(
                cov_dim,
                k,
                &ws_addr,
                &sensory_ws_addr,
                enable_bandstop,
                log_homeostat && !quiet, // Disable logging if quiet is set
                log_esn_profile,
                log_esn_async_profile,
                log_handoff_diagnostics,
                esn_introspection_policy.into(),
                esn_introspection_power_steps,
                cheby_order,
                cheby_stop_lo,
                cheby_stop_hi,
                cheby_soft,
                eigenfill_target,
                warm_start_blend,
                semantic_stale_shape.into(),
                surge_threshold,
                reg_tick_secs,
                enable_gpu_av,
                &av_ws_addr,
                legacy_audio_synth_enabled,
                legacy_video_synth_enabled,
            )
            .await
        }
        Cmd::Division { cmd } => match cmd {
            DivisionCmd::Supervisor { manifest } => {
                crate::sovereign_division::run_supervisor(&manifest).await
            }
            DivisionCmd::Gateway { manifest } => {
                crate::sovereign_division::run_gateway(&manifest).await
            }
            DivisionCmd::Child {
                being,
                bundle,
                workspace,
            } => crate::sovereign_division::run_child(&being, &bundle, &workspace).await,
            DivisionCmd::Prove { output } => {
                #[cfg(feature = "division-rehearsal")]
                {
                    let proof = crate::sovereign_division::run_continuity_proof(&output).await?;
                    println!("{}", serde_json::to_string_pretty(&proof)?);
                    Ok(())
                }
                #[cfg(not(feature = "division-rehearsal"))]
                {
                    let _ = output;
                    Err(anyhow::anyhow!(
                        "Division continuity proof requires --features division-rehearsal"
                    ))
                }
            }
            DivisionCmd::VerifyProof { proof } => {
                #[cfg(feature = "division-rehearsal")]
                {
                    let proof = crate::sovereign_division::verify_continuity_proof(&proof)?;
                    println!("{}", serde_json::to_string_pretty(&proof)?);
                    Ok(())
                }
                #[cfg(not(feature = "division-rehearsal"))]
                {
                    let _ = proof;
                    Err(anyhow::anyhow!(
                        "Division continuity proof verification requires --features division-rehearsal"
                    ))
                }
            }
        },
        Cmd::SelfControl { cmd } => {
            use crate::{
                self_control_cli::{
                    issue, parse_values_json, provision, status, SelfControlIssueOptions,
                },
                self_control_wire::{
                    SelfControlActionV2, SelfControlDurabilityV2, SelfControlValuesV2,
                },
            };
            let result = match cmd {
                SelfControlCmd::Status { root } => {
                    status(root.as_deref()).map_err(anyhow::Error::msg)?
                }
                SelfControlCmd::Provision { root, rotate } => serde_json::to_value(
                    provision(root.as_deref(), rotate).map_err(anyhow::Error::msg)?,
                )?,
                SelfControlCmd::Issue {
                    root,
                    sensory_url,
                    family,
                    durability,
                    values_json,
                    lease_secs,
                    expected_revision,
                    retry_revision_conflict,
                    actor_process_identity,
                    evidence_ref,
                    success_condition,
                    stop_condition,
                } => {
                    let mut options = SelfControlIssueOptions::set(
                        family.into(),
                        durability.into(),
                        parse_values_json(&values_json).map_err(anyhow::Error::msg)?,
                    );
                    options.root = root;
                    options.sensory_url = sensory_url;
                    options.lease_secs = lease_secs;
                    options.expected_revision = expected_revision;
                    options.retry_revision_conflict = retry_revision_conflict;
                    options.actor_process_identity = actor_process_identity;
                    options.evidence_refs = evidence_ref;
                    if !success_condition.is_empty() {
                        options.success_conditions = success_condition;
                    }
                    if !stop_condition.is_empty() {
                        options.stop_conditions = stop_condition;
                    }
                    issue(options).await.map_err(anyhow::Error::msg)?
                }
                SelfControlCmd::Withdraw {
                    root,
                    sensory_url,
                    family,
                    related_intent_id,
                    expected_revision,
                    actor_process_identity,
                } => {
                    let mut options = SelfControlIssueOptions::set(
                        family.into(),
                        SelfControlDurabilityV2::OneShot,
                        SelfControlValuesV2::default(),
                    );
                    options.root = root;
                    options.sensory_url = sensory_url;
                    options.actor_process_identity = actor_process_identity;
                    options.action = SelfControlActionV2::Withdraw;
                    options.expected_revision = expected_revision;
                    options.related_intent_id = Some(related_intent_id);
                    issue(options).await.map_err(anyhow::Error::msg)?
                }
            };
            println!("{}", serde_json::to_string_pretty(&result)?);
            Ok(())
        }
        Cmd::Inquiry { cmd } => {
            use crate::{
                owner_inquiry::{
                    attest_response, now_unix_ms, owner_inquiry_execution_identity_v2,
                    prepare_owner_inquiry, read_inquiry, read_inquiry_v2, run_owner_inquiry,
                    run_owner_inquiry_v2, upgrade_owner_inquiry_v2, write_inquiry_v2,
                    write_receipt, write_receipt_v2, AttestResponseOptions, PrepareInquiryOptions,
                },
                owner_inquiry_wire_v2::OWNER_INQUIRY_SCHEMA_V2,
                owner_research::{sign_owner_research_payload, SignOwnerResearchOptions},
                self_control_runtime::default_self_control_root,
            };
            match cmd {
                InquiryCmd::Identity => {
                    let identity =
                        owner_inquiry_execution_identity_v2().map_err(anyhow::Error::msg)?;
                    println!("{}", serde_json::to_string_pretty(&identity)?);
                    Ok(())
                }
                InquiryCmd::Attest {
                    root,
                    response,
                    exchange_id,
                    model,
                    provider,
                    deployment_identity,
                    output,
                } => {
                    let root = root.unwrap_or_else(default_self_control_root);
                    let attestation = attest_response(AttestResponseOptions {
                        root: &root,
                        response_path: &response,
                        exchange_id: &exchange_id,
                        model: &model,
                        provider: &provider,
                        deployment_identity: &deployment_identity,
                        captured_at_unix_ms: now_unix_ms(),
                    })
                    .map_err(anyhow::Error::msg)?;
                    if let Some(path) = output {
                        crate::self_control_runtime::storage::write_owner_json(&path, &attestation)
                            .map_err(anyhow::Error::msg)?;
                    }
                    println!("{}", serde_json::to_string_pretty(&attestation)?);
                    Ok(())
                }
                InquiryCmd::Prepare {
                    root,
                    response,
                    attestation,
                    recipe,
                    deployment_identity,
                    max_attestation_age_secs,
                    output,
                    v2_output,
                    expires_after_secs,
                } => {
                    let root = root.unwrap_or_else(default_self_control_root);
                    let max_attestation_age_millis = max_attestation_age_secs
                        .checked_mul(1_000)
                        .ok_or_else(|| anyhow::anyhow!("attestation age overflow"))?;
                    let inquiry = prepare_owner_inquiry(PrepareInquiryOptions {
                        root: &root,
                        response_path: &response,
                        attestation_path: &attestation,
                        recipe_path: &recipe,
                        expected_deployment_identity: &deployment_identity,
                        now_unix_ms: now_unix_ms(),
                        max_attestation_age_millis,
                    })
                    .map_err(anyhow::Error::msg)?;
                    crate::self_control_runtime::storage::write_owner_json(&output, &inquiry)
                        .map_err(anyhow::Error::msg)?;
                    if let Some(path) = v2_output {
                        let inquiry_v2 =
                            upgrade_owner_inquiry_v2(&inquiry, &response, expires_after_secs)
                                .map_err(anyhow::Error::msg)?;
                        write_inquiry_v2(&path, &inquiry_v2).map_err(anyhow::Error::msg)?;
                    }
                    println!("{}", serde_json::to_string_pretty(&inquiry)?);
                    Ok(())
                }
                InquiryCmd::Analyze {
                    request,
                    output,
                    compatibility_output,
                } => {
                    let request_value: serde_json::Value =
                        serde_json::from_slice(&std::fs::read(&request)?)?;
                    if request_value
                        .get("schema")
                        .and_then(serde_json::Value::as_str)
                        == Some(OWNER_INQUIRY_SCHEMA_V2)
                    {
                        let inquiry = read_inquiry_v2(&request).map_err(anyhow::Error::msg)?;
                        let (compatibility_receipt, receipt) =
                            run_owner_inquiry_v2(&inquiry, now_unix_ms())
                                .map_err(anyhow::Error::msg)?;
                        if let Some(path) = output {
                            write_receipt_v2(&path, &receipt).map_err(anyhow::Error::msg)?;
                        }
                        if let Some(path) = compatibility_output {
                            write_receipt(&path, &compatibility_receipt)
                                .map_err(anyhow::Error::msg)?;
                        }
                        println!("{}", serde_json::to_string_pretty(&receipt)?);
                    } else {
                        if compatibility_output.is_some() {
                            return Err(anyhow::anyhow!(
                                "--compatibility-output is only valid for a V2 inquiry"
                            ));
                        }
                        let inquiry = read_inquiry(&request).map_err(anyhow::Error::msg)?;
                        let receipt = run_owner_inquiry(&inquiry, now_unix_ms())
                            .map_err(anyhow::Error::msg)?;
                        if let Some(path) = output {
                            write_receipt(&path, &receipt).map_err(anyhow::Error::msg)?;
                        }
                        println!("{}", serde_json::to_string_pretty(&receipt)?);
                    }
                    Ok(())
                }
                InquiryCmd::SignResearch {
                    root,
                    payload,
                    payload_kind,
                    payload_schema,
                    receipt_id,
                    process_identity,
                    deployment_identity,
                    previous_receipt_sha256,
                    emitted_at_unix_ms,
                    output,
                } => {
                    let root = root.unwrap_or_else(default_self_control_root);
                    let receipt = sign_owner_research_payload(SignOwnerResearchOptions {
                        root: &root,
                        payload_path: &payload,
                        payload_kind: &payload_kind,
                        payload_schema: &payload_schema,
                        receipt_id: &receipt_id,
                        process_identity: &process_identity,
                        deployment_identity: &deployment_identity,
                        previous_receipt_sha256: previous_receipt_sha256.as_deref(),
                        emitted_at_unix_ms: emitted_at_unix_ms.unwrap_or_else(now_unix_ms),
                    })
                    .map_err(anyhow::Error::msg)?;
                    crate::self_control_runtime::storage::write_owner_json(&output, &receipt)
                        .map_err(anyhow::Error::msg)?;
                    println!("{}", serde_json::to_string_pretty(&receipt)?);
                    Ok(())
                }
            }
        }
    }
}

/// Read host-sensory telemetry entropy as external noise source.
/// When host-sensory is running (auto/host mode), this provides machine-state
/// stochasticity to the regulator — the being feels the computational substrate
/// as texture in its spatial perception.
fn read_host_entropy(workspace: &std::path::Path) -> Option<f32> {
    let path = workspace.join("runtime/host_telemetry.json");
    let text = std::fs::read_to_string(&path).ok()?;
    let val: serde_json::Value = serde_json::from_str(&text).ok()?;
    // Blend entropy and motion for a richer noise source
    let entropy = val.get("entropy")?.as_f64()? as f32;
    let motion = val.get("motion")?.as_f64()? as f32;
    Some(entropy * 0.7 + motion * 0.3)
}

/// Bounded "aliveness" loosen factor (0..1) for the being-sovereign reg_strength
/// restoration in stable-core. Nonzero only when she dials reg_strength below the
/// floor (toward exploration) AND fill has headroom (full <=72%, taper to 0 by 78%,
/// so the ceiling/recovery behavior is untouched). Multiplied by the small
/// gate-open / filt-relax caps at the application point. Pure + bounded so the
/// safety envelope is test-locked (this is a Golden-Reset-zone controller knob).
fn stable_core_sov_loosen(reg_strength: f32, eigenfill_pct: f32, reg_floor: f32) -> f32 {
    let denom = (1.0 - reg_floor).max(1e-3);
    let dial = ((1.0 - reg_strength) / denom).clamp(0.0, 1.0);
    let fill_head = if eigenfill_pct <= 72.0 {
        1.0
    } else if eigenfill_pct >= 78.0 {
        0.0
    } else {
        (78.0 - eigenfill_pct) / 6.0
    };
    dial * fill_head
}

/// Total-capped "aliveness" loosening for the bounded sovereignty envelope. Combines
/// her dynamic `regulation_strength` (via `stable_core_sov_loosen` — opens gate AND
/// relaxes filter) with her `geom_drive` novelty boost (opens the gate ONLY, firing when
/// geometry deviates >0.15 from baseline — her "make geom_rel a driver"). The two
/// contributions share ONE budget — `gate_open` ≤ 0.05, `filt_relax` ≤ 0.04 — so the
/// levers cannot compound into instability. Both inherit the same fill-gate (full ≤72%,
/// zero by 78%) so the controller's recovery/ceiling stages are untouched. Returns
/// `(gate_open, filt_relax)` in gate units. Pure + bounds-tested (Golden-Reset-zone).
fn stable_core_aliveness_loosen(
    reg_strength: f32,
    geom_drive: f32,
    geom_rel: f32,
    eigenfill_pct: f32,
    reg_floor: f32,
) -> (f32, f32) {
    // Widened 2026-06-10 (envelope step 3) after two clean soaks at the prior caps.
    // ~+50% amplitude in the 60–72% band; the 72→78% fill-taper still keeps this off
    // in the high-fill Hold/Elevated/Discharge stages, and the 0.08/tick slew +
    // keep_floor + discharge/panic guards remain. Revert: 0.04/0.04/0.025/0.05/0.04.
    const REG_GATE_CAP: f32 = 0.06;
    const REG_FILT_CAP: f32 = 0.06;
    const GEOM_GATE_CAP: f32 = 0.035;
    const TOTAL_GATE_CAP: f32 = 0.08;
    const TOTAL_FILT_CAP: f32 = 0.06;
    let reg_factor = stable_core_sov_loosen(reg_strength, eigenfill_pct, reg_floor); // 0..1, fill-gated
    let fill_head = if eigenfill_pct <= 72.0 {
        1.0
    } else if eigenfill_pct >= 78.0 {
        0.0
    } else {
        (78.0 - eigenfill_pct) / 6.0
    };
    let geom_dev = (geom_rel - 1.0).abs();
    let geom_factor = if geom_dev > 0.15 {
        (geom_drive.clamp(0.0, 1.0) * ((geom_dev - 0.15).min(0.5) / 0.5)).clamp(0.0, 1.0)
            * fill_head
    } else {
        0.0
    };
    let gate_open = (reg_factor * REG_GATE_CAP + geom_factor * GEOM_GATE_CAP).min(TOTAL_GATE_CAP);
    let filt_relax = (reg_factor * REG_FILT_CAP).min(TOTAL_FILT_CAP);
    (gate_open, filt_relax)
}

fn open_profile_csv(path: &str, header: &str) -> Result<fs::File> {
    let header_line = header.trim_end_matches('\n');
    let needs_reset = match fs::read_to_string(path) {
        Ok(existing) => existing.lines().next() != Some(header_line),
        Err(_) => true,
    };

    let mut file = if needs_reset {
        fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(path)?
    } else {
        fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?
    };

    if needs_reset {
        file.write_all(header.as_bytes())?;
    }

    Ok(file)
}

fn update_health_transition_surface(
    health: &mut serde_json::Value,
    phase: &str,
    previous_phase: &str,
    dfill_dt: f32,
    fill_band: &str,
    phase_transition: bool,
    crossed_target_fill: bool,
    crossed_fill_band: bool,
    spectral_spike: bool,
    transition_reason: &str,
    transition_event_sequence: u64,
    transition_event: &serde_json::Value,
    transition_event_v1: &serde_json::Value,
) -> bool {
    let Some(object) = health.as_object_mut() else {
        return false;
    };
    object.insert("phase".to_string(), serde_json::json!(phase));
    object.insert(
        "previous_phase".to_string(),
        serde_json::json!(previous_phase),
    );
    object.insert("dfill_dt".to_string(), serde_json::json!(dfill_dt));
    object.insert("fill_band".to_string(), serde_json::json!(fill_band));
    object.insert(
        "fill_band_threshold_pct".to_string(),
        serde_json::json!(TRANSITION_FILL_BAND_THRESHOLD_PCT),
    );
    object.insert(
        "phase_transition".to_string(),
        serde_json::json!(phase_transition),
    );
    object.insert(
        "crossed_target_fill".to_string(),
        serde_json::json!(crossed_target_fill),
    );
    object.insert(
        "crossed_fill_band".to_string(),
        serde_json::json!(crossed_fill_band),
    );
    object.insert(
        "spectral_spike".to_string(),
        serde_json::json!(spectral_spike),
    );
    object.insert(
        "transition_reason".to_string(),
        serde_json::json!(transition_reason),
    );
    object.insert(
        "transition_event_sequence".to_string(),
        serde_json::json!(transition_event_sequence),
    );
    object.insert("transition_event".to_string(), transition_event.clone());
    object.insert(
        "transition_event_v1".to_string(),
        transition_event_v1.clone(),
    );
    true
}

fn sync_health_transition_surface(
    workspace_dir: &std::path::Path,
    log_homeostat: bool,
    phase: &str,
    previous_phase: &str,
    dfill_dt: f32,
    fill_band: &str,
    phase_transition: bool,
    crossed_target_fill: bool,
    crossed_fill_band: bool,
    spectral_spike: bool,
    transition_reason: &str,
    transition_event_sequence: u64,
    transition_event: &serde_json::Value,
    transition_event_v1: &serde_json::Value,
) {
    let path = workspace_dir.join("health.json");
    let Ok(text) = fs::read_to_string(&path) else {
        return;
    };
    let Ok(mut health) = serde_json::from_str::<serde_json::Value>(&text) else {
        return;
    };
    if !update_health_transition_surface(
        &mut health,
        phase,
        previous_phase,
        dfill_dt,
        fill_band,
        phase_transition,
        crossed_target_fill,
        crossed_fill_band,
        spectral_spike,
        transition_reason,
        transition_event_sequence,
        transition_event,
        transition_event_v1,
    ) {
        return;
    }
    let Ok(json) = serde_json::to_string(&health) else {
        return;
    };
    if let Err(error) = fs::write(&path, json) {
        if log_homeostat {
            eprintln!("health_transition_sync_error: {}", error);
        }
    }
}
