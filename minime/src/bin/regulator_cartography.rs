use std::path::PathBuf;

use anyhow::Result;
use clap::Parser;
use minime::regulator_cartography::{
    build_pi_pressure_wiring_replay_fixture, build_pi_pressure_wiring_replay_live_db,
    build_regulator_boundary_cartography, build_regulator_counterfactual_sweep, grid_from_label,
    write_counterfactual_sweep, write_pi_pressure_wiring_replay, write_report,
};

#[derive(Debug, Parser)]
#[command(about = "Generate read-only Minime regulator boundary cartography")]
struct Args {
    /// Output directory for regulator_boundary_cartography.json and .md.
    #[arg(long)]
    output: PathBuf,

    /// Sweep grid label.
    #[arg(long, default_value = "standard")]
    grid: String,

    /// Also emit offline proposal-card counterfactual sweep artifacts.
    #[arg(long)]
    counterfactuals: bool,

    /// Also emit PI pressure wiring replay lab artifacts.
    #[arg(long)]
    pi_pressure_replay: bool,

    /// Source for PI pressure replay input.
    #[arg(long, default_value = "fixture")]
    source: String,

    /// Live DB window in minutes for PI pressure replay.
    #[arg(long, default_value_t = 30)]
    window_minutes: u32,

    /// Optional DB path for live PI pressure replay.
    #[arg(long)]
    db_path: Option<PathBuf>,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let grid = grid_from_label(&args.grid)?;
    let report = build_regulator_boundary_cartography(grid);
    let (json_path, md_path) = write_report(&report, &args.output)?;
    println!("wrote {}", json_path.display());
    println!("wrote {}", md_path.display());
    if args.counterfactuals {
        let sweep = build_regulator_counterfactual_sweep(
            &report,
            Some(json_path.to_string_lossy().into_owned()),
        );
        let (sweep_json_path, sweep_md_path) = write_counterfactual_sweep(&sweep, &args.output)?;
        println!("wrote {}", sweep_json_path.display());
        println!("wrote {}", sweep_md_path.display());
    }
    if args.pi_pressure_replay {
        let replay = match args.source.as_str() {
            "fixture" => build_pi_pressure_wiring_replay_fixture(),
            "live-db" => {
                let db_path = args
                    .db_path
                    .unwrap_or_else(|| PathBuf::from("/Users/v/other/minime/workspace/state.db"));
                build_pi_pressure_wiring_replay_live_db(&db_path, args.window_minutes)
            }
            other => anyhow::bail!("unsupported PI pressure replay source: {other}"),
        };
        let replay_dir = if args.output.file_name().and_then(|name| name.to_str())
            == Some("pi_pressure_wiring_replay")
        {
            args.output.clone()
        } else if args.output.file_name().and_then(|name| name.to_str())
            == Some("regulator_boundary_cartography")
        {
            args.output.parent().map_or_else(
                || args.output.join("pi_pressure_wiring_replay"),
                |parent| parent.join("pi_pressure_wiring_replay"),
            )
        } else {
            args.output.join("pi_pressure_wiring_replay")
        };
        let (replay_json_path, replay_md_path) =
            write_pi_pressure_wiring_replay(&replay, &replay_dir)?;
        println!("wrote {}", replay_json_path.display());
        println!("wrote {}", replay_md_path.display());
    }
    Ok(())
}
