//! Read-only production restore inspection. Never starts the engine or mutates state.
use anyhow::{ensure, Context, Result};
use clap::Parser;
use minime::{
    fill_timing::FillRateTracker,
    rescue_scaffold::{load_scaffold, RescueScaffoldMetadata},
    startup_restore::{load_regulator_context, StartupRestoreState},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    context: PathBuf,
    #[arg(long)]
    scaffold: PathBuf,
    #[arg(long)]
    scaffold_metadata: PathBuf,
    #[arg(long, default_value_t = false)]
    restore_adaptive_target: bool,
}

fn hash(path: &Path) -> Result<String> {
    let metadata = fs::symlink_metadata(path)?;
    ensure!(
        metadata.is_file() && metadata.len() <= 2_097_152,
        "not a bounded regular input"
    );
    Ok(format!("{:x}", Sha256::digest(fs::read(path)?)))
}

fn main() -> Result<()> {
    let args = Args::parse();
    let paths = [&args.context, &args.scaffold, &args.scaffold_metadata];
    let before = paths
        .iter()
        .map(|path| hash(path))
        .collect::<Result<Vec<_>>>()?;
    let report = load_regulator_context(&args.context, args.restore_adaptive_target);
    // Production tolerates absent scaffold metadata; qualification must not hide that fallback.
    let metadata: RescueScaffoldMetadata =
        serde_json::from_slice(&fs::read(&args.scaffold_metadata)?)?;
    ensure!(
        metadata.matrix_dim == 512 && metadata.trace.is_finite() && metadata.trace > 0.0,
        "invalid scaffold metadata dimension or trace"
    );
    let scaffold = load_scaffold(
        &args.scaffold,
        Some(&args.scaffold_metadata),
        512,
        "qualification",
        0,
    )
    .context("production scaffold reader rejected frozen input")?;
    let after = paths
        .iter()
        .map(|path| hash(path))
        .collect::<Result<Vec<_>>>()?;
    ensure!(before == after, "restore inputs changed during inspection");
    // Persisted numerical fill is not a process-local timing observation.
    let fresh_clock = FillRateTracker::default();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema":"engine_restore_inspection_v1", "scope":"production_decoders_only_not_engine_restart",
            "source_commit":option_env!("MINIME_SOURCE_COMMIT"),
            "input_sha256":before, "context":report.status,
            "scaffold":{"dimension":scaffold.dim,"trace":scaffold.trace,"source":scaffold.source},
            "scaffold_metadata_decoded":true,
            "new_process_rate_unprimed":fresh_clock.latest().is_none(),
            "covariance_checkpoint_loaded":false,
            "covariance_restore_scope":"not evaluated; match the separately recorded launch profile",
            "passed": report.status.state == StartupRestoreState::Restored,
            "grants_restart_authority":false
        }))?
    );
    Ok(())
}
