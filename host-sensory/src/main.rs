use anyhow::Result;
use clap::Parser;

fn main() -> Result<()> {
    let config = host_sensory::Config::parse();
    host_sensory::run(config)
}
