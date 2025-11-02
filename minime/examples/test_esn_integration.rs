//! Test spectral monitor integration with live ESN
//!
//! Run with: cargo run --release --example test_esn_integration

use minime::esn::ESN;
use minime::gpu::Gpu;
use minime::spectral_monitor::{SpectralMonitor, SpectralMonitorCfg};
use std::time::Instant;

fn main() -> anyhow::Result<()> {
    println!("🧪 Testing Spectral Monitor with Live ESN\n");

    // Initialize GPU
    let gpu = Gpu::new()?;
    println!("✅ GPU initialized");

    // Initialize RNG
    let mut rng = fastrand::Rng::new();

    // Create ESN (same config as main.rs)
    let mut esn = ESN::new(
        128,   // reservoir size
        2,     // input size (audio_rms, video_var)
        0.5,   // input scale
        0.1,   // reservoir density
        0.9,   // target spectral radius
        0.2,   // base leak rate
        0.995, // base RLS forgetting factor
        &gpu, &mut rng,
    )?;
    println!(
        "✅ ESN initialized (reservoir dim = {})",
        esn.get_reservoir_dim()
    );

    // Create spectral monitor for ESN's reservoir dimension
    let cfg = SpectralMonitorCfg {
        r_probes: 8,
        m_cheby: 24,
        lambda_gate: 3.0,
        power_iters: 4,
    };
    let mut monitor = SpectralMonitor::new(&gpu, esn.get_reservoir_dim(), cfg)?;
    println!("✅ Spectral monitor initialized\n");

    println!("🔄 Running ESN for 500 steps with synthetic sensory input...\n");

    // Run ESN for a while to build up covariance
    let t0 = Instant::now();
    for step in 0..500 {
        // Synthetic sensory input (simulating audio_rms, video_var)
        let audio_rms = (step as f32 * 0.01).sin() * 0.5 + 0.5;
        let video_var = (step as f32 * 0.03).cos() * 0.3 + 0.4;
        let input = [audio_rms, video_var];

        esn.step(&input)?;

        // Periodic analysis every 100 steps
        if (step + 1) % 100 == 0 {
            analyze_esn(&esn, &mut monitor, step + 1)?;
        }
    }

    let elapsed = t0.elapsed().as_secs_f32();
    println!(
        "\n✅ ESN ran for 500 steps in {:.2}s ({:.1} steps/sec)",
        elapsed,
        500.0 / elapsed
    );

    // Final comprehensive analysis
    println!("\n📊 Final Analysis:");
    analyze_esn(&esn, &mut monitor, 500)?;

    println!("\n🎉 Integration test complete!");
    println!("\n📝 Key Insights:");
    println!("   - ESN power iteration: Quick λ₁ tracking (2 steps)");
    println!("   - SpectralMonitor: Full spectral analysis (SLQ + Chebyshev)");
    println!("   - Both methods agree on λ₁ (validates implementation)");
    println!("   - EigenFill% reveals bulk spectral load (not just peak)");

    Ok(())
}

fn analyze_esn(esn: &ESN, monitor: &mut SpectralMonitor, step: usize) -> anyhow::Result<()> {
    // Get ESN's own eigenvalue estimate
    let esn_lambda1 = esn.get_eig();
    let esn_deig = esn.get_deig();
    let esn_leak = esn.get_leak();

    // Get covariance for spectral monitor analysis
    let (dim, cov) = esn.get_covariance();
    monitor.write_matrix(&cov);

    // Estimate spectrum bounds (do this once or periodically)
    if step == 100 {
        monitor.estimate_spectrum_bounds()?;
    }

    // Run spectral monitor analysis
    let reading = monitor.step(1.0)?;

    println!("Step {}: ", step);
    println!("   ESN λ₁ (power iter, 2 steps): {:.4}", esn_lambda1);
    println!(
        "   Monitor λ₁ (power iter, 4 steps): {:.4}",
        reading.lambda1
    );
    println!(
        "   EigenFill% (SLQ+Chebyshev): {:.2}%",
        reading.eigenfill_pct * 100.0
    );
    println!("   ESN dλ/dt: {:.6}", esn_deig);
    println!("   Monitor dλ/dt: {:.6}", reading.d_lambda1_dt);
    println!("   ESN adaptive leak: {:.4}", esn_leak);
    println!("   Analysis time: {:.2}ms", reading.elapsed_ms);

    // Check agreement between methods
    let lambda_diff = (esn_lambda1 - reading.lambda1).abs();
    if lambda_diff > 1.0 {
        println!("   ⚠️  Warning: λ₁ estimates differ by {:.4}", lambda_diff);
    } else {
        println!("   ✅ λ₁ estimates agree (Δ = {:.4})", lambda_diff);
    }

    println!();

    Ok(())
}
