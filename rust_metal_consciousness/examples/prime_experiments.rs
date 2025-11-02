///
/// Prime Optimization Experiments Benchmark
///
/// Implements the playbook from Section 0-K, allowing A/B testing of:
/// - Prime-sized buffers (A1)
/// - Prime diagnostic cadence (A2)
/// - Prime stride through tiles (B1)
/// - Prime padding in threadgroup memory (B2)
/// - Memory mode comparison (G1, G2)
/// - Velocity PCA for cache handoff demo (F1)
///
/// Usage:
///   cargo run --example prime_experiments --release -- --help
///

use metal_consciousness::*;
use anyhow::Result;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use std::env;

#[derive(Debug, Clone)]
struct ExperimentConfig {
    // Run parameters
    frames: usize,
    seeds: usize,

    // Prime toggles (from PrimeConfig)
    use_prime_buffers: bool,
    use_coprime_stride: bool,
    use_prime_padding: bool,
    use_halton_init: bool,
    use_rotation: bool,
    use_prime_diagnostics: bool,

    // Specific primes
    buffer_prime: usize,
    stride_prime: usize,
    diagnostic_prime: usize,

    // Memory mode
    memory_mode: String,  // "shared", "managed", "private"

    // Output
    log_path: Option<String>,
    verbose: bool,
}

impl Default for ExperimentConfig {
    fn default() -> Self {
        ExperimentConfig {
            frames: 10000,
            seeds: 1,
            use_prime_buffers: true,
            use_coprime_stride: true,
            use_prime_padding: true,
            use_halton_init: true,
            use_rotation: true,
            use_prime_diagnostics: true,
            buffer_prime: 113,
            stride_prime: 97,
            diagnostic_prime: 127,
            memory_mode: "shared".to_string(),
            log_path: None,
            verbose: false,
        }
    }
}

fn main() -> Result<()> {
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║  Prime Optimization Experiments - Consciousness Engine      ║");
    println!("║  Apple Silicon Unified Memory Cache-Handoff Benchmarks      ║");
    println!("╚══════════════════════════════════════════════════════════════╝\n");

    // Parse arguments
    let config = parse_args()?;

    // Print configuration
    print_config(&config);

    // Get system info
    print_system_info()?;

    // Run experiments
    run_experiments(config)?;

    Ok(())
}

fn parse_args() -> Result<ExperimentConfig> {
    let mut config = ExperimentConfig::default();
    let args: Vec<String> = env::args().collect();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--help" | "-h" => {
                print_help();
                std::process::exit(0);
            }
            "--frames" => {
                i += 1;
                config.frames = args[i].parse()?;
            }
            "--seeds" => {
                i += 1;
                config.seeds = args[i].parse()?;
            }
            "--memory-mode" => {
                i += 1;
                config.memory_mode = args[i].clone();
            }
            "--no-prime-buffers" => config.use_prime_buffers = false,
            "--no-stride" => config.use_coprime_stride = false,
            "--no-padding" => config.use_prime_padding = false,
            "--no-halton" => config.use_halton_init = false,
            "--no-rotation" => config.use_rotation = false,
            "--no-diagnostics" => config.use_prime_diagnostics = false,
            "--log" => {
                i += 1;
                config.log_path = Some(args[i].clone());
            }
            "--verbose" | "-v" => config.verbose = true,
            "--quick" => {
                // Quick test mode (30 min as per Section K)
                config.frames = 1000;
                config.seeds = 1;
            }
            _ => {
                eprintln!("Unknown argument: {}", args[i]);
                print_help();
                std::process::exit(1);
            }
        }
        i += 1;
    }

    Ok(config)
}

fn print_help() {
    println!("Usage: prime_experiments [OPTIONS]");
    println!();
    println!("Options:");
    println!("  --frames <N>           Number of frames to run (default: 10000)");
    println!("  --seeds <N>            Number of random seeds to test (default: 1)");
    println!("  --memory-mode <MODE>   Memory mode: shared, managed, private (default: shared)");
    println!("  --no-prime-buffers     Disable prime-sized buffers");
    println!("  --no-stride            Disable coprime stride");
    println!("  --no-padding           Disable prime padding");
    println!("  --no-halton            Disable Halton initialization");
    println!("  --no-rotation          Disable epsilon rotation");
    println!("  --no-diagnostics       Disable prime diagnostics intervals");
    println!("  --log <PATH>           Log results to file");
    println!("  --verbose, -v          Verbose output");
    println!("  --quick                Quick test mode (1000 frames, for 30min test)");
    println!("  --help, -h             Show this help");
    println!();
    println!("Quick picks (Section K):");
    println!("  # Prime padding test");
    println!("  prime_experiments --frames 10000 --memory-mode shared");
    println!();
    println!("  # Managed vs Shared comparison");
    println!("  prime_experiments --memory-mode managed --frames 5000");
    println!();
    println!("  # Prime trails test");
    println!("  prime_experiments --frames 10000 --log trail_test.jsonl");
}

fn print_config(config: &ExperimentConfig) {
    println!("Configuration:");
    println!("  Frames: {}", config.frames);
    println!("  Seeds: {}", config.seeds);
    println!("  Memory mode: {}", config.memory_mode);
    println!("\nPrime Optimizations:");
    println!("  Prime buffers: {} (size={})", config.use_prime_buffers, config.buffer_prime);
    println!("  Coprime stride: {} (stride={})", config.use_coprime_stride, config.stride_prime);
    println!("  Prime padding: {}", config.use_prime_padding);
    println!("  Halton init: {}", config.use_halton_init);
    println!("  Epsilon rotation: {}", config.use_rotation);
    println!("  Prime diagnostics: {} (interval={})", config.use_prime_diagnostics, config.diagnostic_prime);
    println!();
}

fn print_system_info() -> Result<()> {
    use metal::*;

    let device = Device::system_default()
        .ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

    println!("System Information:");
    println!("  Device: {}", device.name());
    println!("  Recommended max working set size: {:.1} GB",
             device.recommended_max_working_set_size() as f64 / 1e9);

    // macOS version
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sw_vers").arg("-productVersion").output() {
            if let Ok(version) = String::from_utf8(output.stdout) {
                println!("  macOS: {}", version.trim());
            }
        }

        if let Ok(output) = Command::new("sysctl").arg("-n").arg("machdep.cpu.brand_string").output() {
            if let Ok(cpu) = String::from_utf8(output.stdout) {
                println!("  CPU: {}", cpu.trim());
            }
        }
    }

    println!();

    Ok(())
}

fn run_experiments(config: ExperimentConfig) -> Result<()> {
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║  Running Experiments                                         ║");
    println!("╚══════════════════════════════════════════════════════════════╝\n");

    let total_start = Instant::now();

    // Section K: Quick picks
    if config.frames <= 1000 {
        println!("Running QUICK test mode (Section K recommendations)");
        run_quick_experiments(&config)?;
    } else {
        println!("Running FULL experiment suite");
        run_full_experiments(&config)?;
    }

    let total_time = total_start.elapsed();

    println!("\n╔══════════════════════════════════════════════════════════════╗");
    println!("║  Experiments Complete                                        ║");
    println!("╚══════════════════════════════════════════════════════════════╝");
    println!("\nTotal runtime: {:.1} seconds", total_time.as_secs_f64());

    // Generate report
    generate_report(&config)?;

    Ok(())
}

fn run_quick_experiments(_config: &ExperimentConfig) -> Result<()> {
    println!("\n1. Prime padding test (B2) - 10k frames, checking kernel time");
    // TODO: Run with and without padding

    println!("\n2. Prime trails ring (A1) - comparing entropy vs 96");
    // TODO: Run with trail_len=113 vs 96

    println!("\n3. Managed syncs (G1) - watch perf drop");
    // TODO: Run managed mode and measure sync overhead

    println!("\n4. Velocity PCA (F1) - prove AI-ish handoff pattern");
    // TODO: Run VelocityPCA and measure convergence

    println!("\n[Quick experiments complete - implement full versions]");
    Ok(())
}

fn run_full_experiments(config: &ExperimentConfig) -> Result<()> {
    // A. Time de-aliasing
    println!("\n=== A. Time De-aliasing ===");
    run_time_dealiasing_tests(config)?;

    // B. Space de-aliasing
    println!("\n=== B. Space De-aliasing ===");
    run_space_dealiasing_tests(config)?;

    // F. Spectral add-ons
    println!("\n=== F. Spectral Add-ons (PCA) ===");
    run_spectral_tests(config)?;

    // G. Memory mode A/B
    println!("\n=== G. Memory Mode A/B ===");
    run_memory_mode_tests(config)?;

    Ok(())
}

fn run_time_dealiasing_tests(_config: &ExperimentConfig) -> Result<()> {
    println!("A1. Prime trails ring - testing entropy differences");
    // TODO: Implement

    println!("A2. Prime diagnostics cadence - measuring frame time variance");
    // TODO: Implement

    Ok(())
}

fn run_space_dealiasing_tests(_config: &ExperimentConfig) -> Result<()> {
    println!("B1. Prime stride through tile - measuring energy drift");
    // TODO: Implement

    println!("B2. Prime padding - comparing kernel times");
    // TODO: Implement

    Ok(())
}

fn run_spectral_tests(_config: &ExperimentConfig) -> Result<()> {
    println!("F1. Velocity PCA - testing cache handoff speed");
    // TODO: Implement VelocityPCA test

    println!("F2. Block power K=3 - measuring iters/s vs K=1");
    // TODO: Implement block power test

    Ok(())
}

fn run_memory_mode_tests(config: &ExperimentConfig) -> Result<()> {
    println!("Testing memory mode: {}", config.memory_mode);

    // Use existing MemoryModeComparator
    use metal_consciousness::memory_ab_test::*;

    let buffer_size = 16 * 1024 * 1024;  // 16 MB
    let iterations = 100;

    let mut comparator = MemoryModeComparator::new(buffer_size, iterations)?;
    comparator.run_all_tests()?;

    Ok(())
}

fn generate_report(config: &ExperimentConfig) -> Result<()> {
    println!("\n╔══════════════════════════════════════════════════════════════╗");
    println!("║  Report Template (Section J)                                ║");
    println!("╚══════════════════════════════════════════════════════════════╝\n");

    println!("1. Machine:");
    print_system_info()?;

    println!("2. Build:");
    println!("   Memory mode: {}", config.memory_mode);
    println!("   Prime buffers: {}", config.use_prime_buffers);
    println!("   Coprime stride: {}", config.use_coprime_stride);
    println!("   Prime padding: {}", config.use_prime_padding);

    println!("\n3. Run length:");
    println!("   Frames: {}", config.frames);
    println!("   Seeds: {}", config.seeds);

    println!("\n4. Metrics:");
    println!("   [To be filled with actual run data]");
    println!("   - frame_ms: mean ± stddev");
    println!("   - physics_ms: mean ± stddev");
    println!("   - render_ms: mean ± stddev");
    println!("   - energy_ppm: mean ± stddev");
    println!("   - trail_entropy: mean ± stddev");

    println!("\n5. Screenshots:");
    println!("   [Use Instruments → Metal System Trace]");
    println!("   - Timeline showing memory transactions");
    println!("   - GPU occupancy graphs");

    println!("\n6. Subjective:");
    println!("   [Describe any visible stutters, moiré, drift]");

    // Save report to file if requested
    if let Some(ref log_path) = config.log_path {
        use std::fs::File;
        use std::io::Write;

        let report_path = log_path.replace(".jsonl", "_report.txt");
        let mut file = File::create(&report_path)?;

        writeln!(file, "Prime Optimization Experiments Report")?;
        writeln!(file, "=====================================")?;
        writeln!(file)?;
        writeln!(file, "Timestamp: {}",
                SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs())?;
        writeln!(file, "Memory mode: {}", config.memory_mode)?;
        writeln!(file, "Frames: {}", config.frames)?;
        // ... add more details

        println!("\nReport saved to: {}", report_path);
    }

    Ok(())
}
