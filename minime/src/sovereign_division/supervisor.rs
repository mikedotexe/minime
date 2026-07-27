use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};

use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use tokio::{process::Child, time::sleep};

use crate::sovereign_division::records::{
    append_owner_json, ensure_owner_only_dir, matching_active_intents, now_unix_ms,
    write_owner_json, DivisionRuntimeManifestV1, SovereignBeing,
};

const SUPERVISOR_POLL: Duration = Duration::from_millis(500);

#[derive(Debug, Serialize)]
struct SupervisorStatusV1 {
    schema: &'static str,
    division_id: String,
    manifest_sha256: String,
    pid: u32,
    mode: &'static str,
    parent_authoritative: bool,
    matching_intents: Vec<SovereignBeing>,
    children: BTreeMap<SovereignBeing, ChildStatusV1>,
    rollback_available: bool,
    handoff_ready: bool,
    handoff_blockers: Vec<&'static str>,
    commit_recommended: bool,
    launch_blockers: Vec<String>,
    updated_at_unix_ms: u64,
    live_authority_granted_by_record: bool,
}

#[derive(Debug, Serialize)]
struct ChildStatusV1 {
    launched: bool,
    pid: Option<u32>,
    bundle: PathBuf,
    workspace: PathBuf,
    last_exit_success: Option<bool>,
}

pub async fn run_supervisor(manifest_path: &Path) -> Result<()> {
    let manifest = DivisionRuntimeManifestV1::load(manifest_path)?;
    manifest.validate_current(now_unix_ms())?;
    ensure_owner_only_dir(manifest.runtime_dir())?;
    ensure_parent_authority(&manifest)?;

    let mut children: BTreeMap<SovereignBeing, ManagedChild> = BTreeMap::new();
    loop {
        let now = now_unix_ms();
        let intents = matching_active_intents(manifest.ceremony_ledger(), &manifest, now)?;
        let intent_gate = manifest.candidate_bound()
            && intents.contains_key(&SovereignBeing::Astrid)
            && intents.contains_key(&SovereignBeing::Minime);
        let mut blockers = Vec::new();
        if !intent_gate {
            blockers.push(
                if manifest.candidate_bound() {
                    "matching_unexpired_dual_intent_required"
                } else {
                    "candidate_bound_manifest_required"
                }
                .to_string(),
            );
            stop_children(&mut children).await;
        } else if children.is_empty() {
            match launch_children(&manifest).await {
                Ok(launched) => {
                    children = launched;
                    append_owner_json(
                        &manifest.runtime_dir().join("events.jsonl"),
                        &serde_json::json!({
                            "schema": "division.supervisor_event.v1",
                            "kind": "rehearsal_children_launched",
                            "division_id": manifest.division_id(),
                            "manifest_sha256": manifest.manifest_sha256(),
                            "created_at_unix_ms": now,
                            "live_authority_granted_by_record": false,
                        }),
                    )?;
                }
                Err(error) => {
                    blockers.push("daughter_launch_failed".to_string());
                    append_owner_json(
                        &manifest.runtime_dir().join("events.jsonl"),
                        &serde_json::json!({
                            "schema": "division.supervisor_event.v1",
                            "kind": "daughter_launch_failed",
                            "error_sha256": crate::sovereign_division::records::sha256_hex(error.to_string().as_bytes()),
                            "division_id": manifest.division_id(),
                            "created_at_unix_ms": now,
                            "live_authority_granted_by_record": false,
                        }),
                    )?;
                }
            }
        }

        let mut child_status = BTreeMap::new();
        let mut fault = None;
        for (being, managed) in &mut children {
            let exit = managed.child.try_wait()?;
            if let Some(exit) = exit {
                fault = Some((
                    format!("{}_child_exited", being.as_str()),
                    format!("{exit}"),
                ));
            }
            child_status.insert(
                *being,
                ChildStatusV1 {
                    launched: exit.is_none(),
                    pid: managed.child.id(),
                    bundle: managed.bundle.clone(),
                    workspace: managed.workspace.clone(),
                    last_exit_success: exit.map(|status| status.success()),
                },
            );
        }
        if let Some((reason_code, detail)) = fault {
            blockers.push(reason_code.clone());
            stop_children(&mut children).await;
            append_owner_json(
                &manifest.runtime_dir().join("events.jsonl"),
                &serde_json::json!({
                    "schema": "division.supervisor_event.v1",
                    "kind": "rehearsal_failed_closed",
                    "reason_code": reason_code,
                    "detail_sha256": crate::sovereign_division::records::sha256_hex(detail.as_bytes()),
                    "division_id": manifest.division_id(),
                    "created_at_unix_ms": now,
                    "parent_authoritative": true,
                    "live_authority_granted_by_record": false,
                }),
            )?;
        }
        let status = SupervisorStatusV1 {
            schema: "division.supervisor_status.v1",
            division_id: manifest.division_id().to_string(),
            manifest_sha256: manifest.manifest_sha256().to_string(),
            pid: std::process::id(),
            mode: if children.is_empty() {
                "idle_parent_authoritative"
            } else {
                "rehearsal_non_authoritative"
            },
            parent_authoritative: true,
            matching_intents: intents.keys().copied().collect(),
            children: child_status,
            rollback_available: false,
            handoff_ready: false,
            handoff_blockers: vec![
                "daughter_legacy_sensory_adapter_required",
                "daughter_direct_telemetry_adapter_required",
                "legacy_av_fanout_receipt_required",
                "exact_operator_capability_required",
            ],
            commit_recommended: false,
            launch_blockers: blockers,
            updated_at_unix_ms: now,
            live_authority_granted_by_record: false,
        };
        write_owner_json(
            &manifest.runtime_dir().join("supervisor-status.json"),
            &status,
        )?;
        sleep(SUPERVISOR_POLL).await;
    }
}

struct ManagedChild {
    child: Child,
    bundle: PathBuf,
    workspace: PathBuf,
}

async fn launch_children(
    manifest: &DivisionRuntimeManifestV1,
) -> Result<BTreeMap<SovereignBeing, ManagedChild>> {
    let executable = std::env::current_exe()?;
    let mut launched = BTreeMap::new();
    for being in [SovereignBeing::Minime, SovereignBeing::Astrid] {
        let workspace = manifest.daughter_root(being).to_path_buf();
        let bundle = workspace.join("seed-bundle.json");
        if !bundle.is_file() {
            stop_children(&mut launched).await;
            return Err(anyhow!(
                "{} daughter bundle is missing at {}",
                being.as_str(),
                bundle.display()
            ));
        }
        ensure_owner_only_dir(&workspace)?;
        let child = tokio::process::Command::new(&executable)
            .arg("division")
            .arg("child")
            .arg("--being")
            .arg(being.as_str())
            .arg("--bundle")
            .arg(&bundle)
            .arg("--workspace")
            .arg(&workspace)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .with_context(|| format!("launch {} daughter", being.as_str()))?;
        launched.insert(
            being,
            ManagedChild {
                child,
                bundle,
                workspace,
            },
        );
    }
    Ok(launched)
}

async fn stop_children(children: &mut BTreeMap<SovereignBeing, ManagedChild>) {
    for managed in children.values_mut() {
        let _ = managed.child.kill().await;
        let _ = managed.child.wait().await;
    }
    children.clear();
}

fn ensure_parent_authority(manifest: &DivisionRuntimeManifestV1) -> Result<()> {
    let path = manifest.runtime_dir().join("authority.json");
    if path.exists() {
        let existing: serde_json::Value = serde_json::from_slice(&std::fs::read(&path)?)?;
        if existing.get("schema").and_then(serde_json::Value::as_str)
            != Some("division.gateway_authority.v1")
        {
            return Err(anyhow!("unsupported existing gateway authority state"));
        }
        let same_manifest = existing
            .get("division_id")
            .and_then(serde_json::Value::as_str)
            == Some(manifest.division_id())
            && existing
                .get("manifest_sha256")
                .and_then(serde_json::Value::as_str)
                == Some(manifest.manifest_sha256());
        if same_manifest {
            return Ok(());
        }
        if existing.get("rail").and_then(serde_json::Value::as_str) != Some("parent") {
            return Err(anyhow!(
                "stale daughter authority cannot be rebound to a new manifest"
            ));
        }
    }
    write_owner_json(
        &path,
        &serde_json::json!({
            "schema": "division.gateway_authority.v1",
            "rail": "parent",
            "switch_receipt_sha256": null,
            "handoff_contract_receipt_sha256": null,
            "division_id": manifest.division_id(),
            "manifest_sha256": manifest.manifest_sha256(),
            "created_at_unix_ms": now_unix_ms(),
            "live_authority_granted_by_record": false,
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supervisor_never_recommends_commit() {
        let status = SupervisorStatusV1 {
            schema: "division.supervisor_status.v1",
            division_id: "division-test".into(),
            manifest_sha256: "a".repeat(64),
            pid: 1,
            mode: "idle_parent_authoritative",
            parent_authoritative: true,
            matching_intents: Vec::new(),
            children: BTreeMap::new(),
            rollback_available: false,
            handoff_ready: false,
            handoff_blockers: vec![
                "daughter_legacy_sensory_adapter_required",
                "daughter_direct_telemetry_adapter_required",
                "legacy_av_fanout_receipt_required",
                "exact_operator_capability_required",
            ],
            commit_recommended: false,
            launch_blockers: vec!["matching_unexpired_dual_intent_required".into()],
            updated_at_unix_ms: 1,
            live_authority_granted_by_record: false,
        };
        let value = serde_json::to_value(status).unwrap();
        assert_eq!(value["commit_recommended"], false);
        assert_eq!(value["parent_authoritative"], true);
        assert_eq!(value["handoff_ready"], false);
        assert_eq!(value["handoff_blockers"].as_array().unwrap().len(), 4);
    }
}
