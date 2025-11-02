//! Test spectral monitor with synthetic matrices
//!
//! Run with: cargo run --release --example test_spectral_monitor

use minime::gpu::Gpu;
use minime::spectral_monitor::{SpectralMonitor, SpectralMonitorCfg, SpectralReading};

fn main() -> anyhow::Result<()> {
    println!("🧪 Testing Spectral Monitor\n");

    // Initialize GPU
    let gpu = Gpu::new()?;
    println!("✅ GPU initialized");

    // Test 1: Small identity matrix (all eigenvalues = 1)
    test_identity_matrix(&gpu)?;

    // Test 2: Matrix with known eigenvalues
    test_scaled_matrix(&gpu)?;

    // Test 3: High-pressure matrix (large eigenvalues)
    test_high_pressure_matrix(&gpu)?;

    println!("\n🎉 All tests passed!");

    Ok(())
}

fn test_identity_matrix(gpu: &Gpu) -> anyhow::Result<()> {
    println!("\n📊 Test 1: Identity Matrix (N=64)");
    println!("   Expected: λ₁ ≈ 1.0, EigenFill% low (all eigenvalues = 1)");

    let n = 64;
    let cfg = SpectralMonitorCfg {
        r_probes: 8,
        m_cheby: 16,
        lambda_gate: 3.0,
        power_iters: 4,
    };

    let mut monitor = SpectralMonitor::new(gpu, n, cfg)?;

    // Create identity matrix
    let mut mat = vec![0.0f32; n * n];
    for i in 0..n {
        mat[i * n + i] = 1.0;
    }

    monitor.write_matrix(&mat);
    monitor.estimate_spectrum_bounds()?;

    // Run analysis
    let reading = monitor.step(1.0)?;

    println!("   λ₁ = {:.4}", reading.lambda1);
    println!("   EigenFill% = {:.2}%", reading.eigenfill_pct * 100.0);
    println!("   Computation time: {:.2}ms", reading.elapsed_ms);

    // Verify
    assert!(
        (reading.lambda1 - 1.0).abs() < 0.1,
        "λ₁ should be close to 1.0"
    );
    println!("   ✅ Passed: λ₁ is correct");

    Ok(())
}

fn test_scaled_matrix(gpu: &Gpu) -> anyhow::Result<()> {
    println!("\n📊 Test 2: Scaled Identity Matrix (N=64, scale=5.0)");
    println!("   Expected: λ₁ ≈ 5.0, EigenFill% high (all eigenvalues = 5)");

    let n = 64;
    let cfg = SpectralMonitorCfg {
        r_probes: 8,
        m_cheby: 16,
        lambda_gate: 3.0, // Threshold at 3.0
        power_iters: 4,
    };

    let mut monitor = SpectralMonitor::new(gpu, n, cfg)?;

    // Create scaled identity matrix (all eigenvalues = 5)
    let mut mat = vec![0.0f32; n * n];
    for i in 0..n {
        mat[i * n + i] = 5.0;
    }

    monitor.write_matrix(&mat);
    monitor.estimate_spectrum_bounds()?;

    // Run analysis
    let reading = monitor.step(1.0)?;

    println!("   λ₁ = {:.4}", reading.lambda1);
    println!("   EigenFill% = {:.2}%", reading.eigenfill_pct * 100.0);
    println!("   Computation time: {:.2}ms", reading.elapsed_ms);

    // Verify
    assert!(
        (reading.lambda1 - 5.0).abs() < 0.5,
        "λ₁ should be close to 5.0"
    );
    println!("   ✅ Passed: λ₁ is correct");
    println!("   Note: EigenFill should be ~100% (all eigenvalues above gate)");

    Ok(())
}

fn test_high_pressure_matrix(gpu: &Gpu) -> anyhow::Result<()> {
    println!("\n📊 Test 3: High-Pressure Matrix (N=128, λ₁ >> 3.0)");
    println!("   Expected: λ₁ >> 3.0, EigenFill% very high");

    let n = 128;
    let cfg = SpectralMonitorCfg {
        r_probes: 12,
        m_cheby: 24,
        lambda_gate: 3.0,
        power_iters: 6,
    };

    let mut monitor = SpectralMonitor::new(gpu, n, cfg)?;

    // Create matrix with large diagonal (simulating high pressure)
    let mut mat = vec![0.0f32; n * n];
    for i in 0..n {
        mat[i * n + i] = 10.0 + (i as f32) * 0.1; // Growing eigenvalues
    }

    // Add some off-diagonal coupling
    for i in 0..n.saturating_sub(1) {
        mat[i * n + i + 1] = 0.5;
        mat[(i + 1) * n + i] = 0.5;
    }

    monitor.write_matrix(&mat);
    monitor.estimate_spectrum_bounds()?;

    // Run analysis
    let reading = monitor.step(1.0)?;

    println!("   λ₁ = {:.4}", reading.lambda1);
    println!("   EigenFill% = {:.2}%", reading.eigenfill_pct * 100.0);
    println!("   Computation time: {:.2}ms", reading.elapsed_ms);

    // Verify
    assert!(reading.lambda1 > 5.0, "λ₁ should be significantly elevated");
    println!("   ✅ Passed: High pressure detected");

    Ok(())
}
