//! Offline JSONL capture replay. No engine, sockets, controllers, or model calls.
use anyhow::{ensure, Context, Result};
use clap::Parser;
use minime::transition_afterimage::{CaptureRequest, Event, Recorder, Sample, Store};
use serde_json::Value;
use std::{
    io::{self, BufRead, Read},
    path::PathBuf,
};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    output_workspace: PathBuf,
    #[arg(long)]
    session_id: String,
    #[arg(long)]
    no_automatic: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    ensure!(
        !args.output_workspace.exists(),
        "offline output must be a new directory"
    );
    let mut store = Store::open(&args.output_workspace)?;
    let mut recorder = Recorder::new(&args.session_id);
    recorder.automatic_admission = !args.no_automatic;
    let mut input = io::stdin().lock();
    loop {
        let mut line = String::new();
        let count = (&mut input).take(65_537).read_line(&mut line)?;
        if count == 0 {
            break;
        }
        ensure!(count <= 65_536, "JSONL record exceeds 64 KiB");
        let row: Value = serde_json::from_str(&line).context("invalid replay record")?;
        let finished = match row["type"].as_str() {
            Some("sample") => {
                recorder.observe(serde_json::from_value::<Sample>(row["sample"].clone())?)
            }
            Some("event") => {
                let event: Event = serde_json::from_value(row["event"].clone())?;
                store.enrich(&event)?;
                recorder.event(
                    event,
                    row["wall_clock_unix_ms"]
                        .as_u64()
                        .context("event wall time required")?,
                );
                Vec::new()
            }
            Some("request") => recorder
                .request(serde_json::from_value::<CaptureRequest>(
                    row["request"].clone(),
                )?)
                .map_err(anyhow::Error::msg)?
                .into_iter()
                .collect(),
            _ => anyhow::bail!("expected sample, event or request record"),
        };
        for artifact in finished {
            store.complete(&artifact)?;
            println!("{} {}", artifact.id, artifact.status);
        }
        for artifact in &recorder.collecting {
            store.checkpoint(artifact)?;
        }
    }
    for artifact in recorder.interrupt("offline_input_ended") {
        store.complete(&artifact)?;
        println!("{} {}", artifact.id, artifact.status);
    }
    Ok(())
}
