use std::collections::VecDeque;
use std::fs::File;
use std::io::{Write, BufWriter};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use serde::{Serialize, Deserialize};

use crate::prime_optimizations::{PrimeRingBuffer, PrimeDiagnostics};

/// Comprehensive metrics for consciousness processing
/// Matches the playbook logging format from Section I
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsciousnessMetrics {
    // Timing metrics
    pub frame: u64,           // Using 'frame' to match playbook format
    pub frame_ms: f64,
    pub physics_ms: f64,
    pub render_ms: f64,
    pub total_ms: f64,

    // Numerical metrics
    pub field_energy: f64,
    pub energy_ppm: f64,      // Using 'energy_ppm' to match playbook
    pub eigenvalue_drift: f64,

    // Entropy metrics
    pub field_entropy: f64,
    pub activation_entropy: f64,
    pub resonance_entropy: f64,
    pub trail_entropy: f64,   // Trail age histogram entropy (Section A1)

    // Resonance metrics
    pub resonance_count: usize,
    pub avg_resonance_strength: f64,
    pub max_resonance_strength: f64,

    // Memory metrics
    pub memory_copies: u32,
    pub cache_handoffs: u32,
    pub bandwidth_gbps: f64,
    pub copies_per_turn: u32, // From playbook Section I

    // System metrics
    pub timestamp: f64,
    pub gpu_utilization: f32,
    pub memory_pressure: f32,

    // Performance metrics
    pub iters_per_sec: f64,   // From playbook Section 0
    pub swaps_per_sec: f64,   // From playbook Section 0
}

impl Default for ConsciousnessMetrics {
    fn default() -> Self {
        ConsciousnessMetrics {
            frame: 0,
            frame_ms: 0.0,
            physics_ms: 0.0,
            render_ms: 0.0,
            total_ms: 0.0,
            field_energy: 0.0,
            energy_ppm: 0.0,
            eigenvalue_drift: 0.0,
            field_entropy: 0.0,
            activation_entropy: 0.0,
            resonance_entropy: 0.0,
            trail_entropy: 0.0,
            resonance_count: 0,
            avg_resonance_strength: 0.0,
            max_resonance_strength: 0.0,
            memory_copies: 0,
            cache_handoffs: 0,
            bandwidth_gbps: 0.0,
            copies_per_turn: 0,
            timestamp: 0.0,
            gpu_utilization: 0.0,
            memory_pressure: 0.0,
            iters_per_sec: 0.0,
            swaps_per_sec: 0.0,
        }
    }
}

/// Metrics logger with prime-based intervals
pub struct MetricsLogger {
    // Storage
    history: PrimeRingBuffer<ConsciousnessMetrics>,
    recent_metrics: VecDeque<ConsciousnessMetrics>,

    // Diagnostics
    diagnostics: PrimeDiagnostics,

    // Output
    log_file: Option<BufWriter<File>>,
    console_output: bool,

    // Statistics tracking
    baseline_energy: Option<f64>,
    start_time: Instant,
}

impl MetricsLogger {
    pub fn new(history_size: usize, log_path: Option<&str>) -> Self {
        let log_file = log_path.map(|path| {
            let file = File::create(path).expect("Failed to create log file");
            BufWriter::new(file)
        });

        MetricsLogger {
            history: PrimeRingBuffer::new(history_size),
            recent_metrics: VecDeque::with_capacity(100),
            diagnostics: PrimeDiagnostics::new(),
            log_file,
            console_output: true,
            baseline_energy: None,
            start_time: Instant::now(),
        }
    }

    /// Log a new set of metrics
    pub fn log(&mut self, mut metrics: ConsciousnessMetrics) {
        // Add timestamp
        metrics.timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();

        // Calculate energy drift
        if let Some(baseline) = self.baseline_energy {
            metrics.energy_ppm = ((metrics.field_energy - baseline) / baseline) * 1e6;
        } else {
            self.baseline_energy = Some(metrics.field_energy);
        }

        // Calculate performance metrics
        if metrics.total_ms > 0.0 {
            metrics.iters_per_sec = 1000.0 / metrics.total_ms;
        }

        // Store in history
        self.history.push(metrics.clone());
        self.recent_metrics.push_back(metrics.clone());
        if self.recent_metrics.len() > 100 {
            self.recent_metrics.pop_front();
        }

        // Check diagnostic intervals
        if self.diagnostics.should_run(0, metrics.frame as usize) {
            self.print_summary(&metrics);
        }

        if self.diagnostics.should_run(1, metrics.frame as usize) {
            self.print_detailed(&metrics);
        }

        if self.diagnostics.should_run(2, metrics.frame as usize) {
            self.save_checkpoint(&metrics);
        }

        // Write to log file
        if let Some(ref mut file) = self.log_file {
            let json = serde_json::to_string(&metrics).unwrap();
            writeln!(file, "{}", json).unwrap();
        }
    }

    /// Print summary to console (matches playbook Section I format)
    fn print_summary(&self, metrics: &ConsciousnessMetrics) {
        if !self.console_output {
            return;
        }

        println!(
            "f={} phys={:.3}ms rend={:.3}ms total={:.3}ms energy_ppm={:.2} trail_H={:.3} copies/turn={}",
            metrics.frame,
            metrics.physics_ms,
            metrics.render_ms,
            metrics.total_ms,
            metrics.energy_ppm,
            metrics.trail_entropy,
            metrics.copies_per_turn
        );
    }

    /// Print detailed metrics (enhanced with playbook additions)
    fn print_detailed(&self, metrics: &ConsciousnessMetrics) {
        if !self.console_output {
            return;
        }

        println!("\n=== Detailed Metrics (frame {}) ===", metrics.frame);
        println!("Timing:");
        println!("  Frame: {:.3} ms", metrics.frame_ms);
        println!("  Physics: {:.3} ms", metrics.physics_ms);
        println!("  Render: {:.3} ms", metrics.render_ms);
        println!("  Iters/s: {:.1}", metrics.iters_per_sec);

        println!("\nEnergy:");
        println!("  Field: {:.6}", metrics.field_energy);
        println!("  Drift: {:.2} ppm", metrics.energy_ppm);
        println!("  Eigenvalue drift: {:.6}", metrics.eigenvalue_drift);

        println!("\nEntropy:");
        println!("  Field: {:.3}", metrics.field_entropy);
        println!("  Activation: {:.3}", metrics.activation_entropy);
        println!("  Resonance: {:.3}", metrics.resonance_entropy);
        println!("  Trail: {:.3}", metrics.trail_entropy);

        println!("\nResonances:");
        println!("  Count: {}", metrics.resonance_count);
        println!("  Avg strength: {:.3}", metrics.avg_resonance_strength);
        println!("  Max strength: {:.3}", metrics.max_resonance_strength);

        println!("\nPerformance:");
        println!("  Memory copies: {}", metrics.memory_copies);
        println!("  Copies/turn: {}", metrics.copies_per_turn);
        println!("  Cache handoffs: {}", metrics.cache_handoffs);
        println!("  Bandwidth: {:.2} GB/s", metrics.bandwidth_gbps);
        println!("  GPU utilization: {:.1}%", metrics.gpu_utilization * 100.0);
    }

    /// Save checkpoint
    fn save_checkpoint(&self, metrics: &ConsciousnessMetrics) {
        let filename = format!("checkpoint_{}.json", metrics.frame);
        if let Ok(mut file) = File::create(&filename) {
            let checkpoint = Checkpoint {
                metrics: metrics.clone(),
                history_entropy: 0.0,  // Note: entropy calculation removed for complex types
                runtime_seconds: self.start_time.elapsed().as_secs_f64(),
                recent_statistics: self.compute_recent_statistics(),
            };

            if let Ok(json) = serde_json::to_string_pretty(&checkpoint) {
                let _ = file.write_all(json.as_bytes());
                println!("Saved checkpoint to {}", filename);
            }
        }
    }

    /// Compute statistics over recent metrics
    fn compute_recent_statistics(&self) -> Statistics {
        if self.recent_metrics.is_empty() {
            return Statistics::default();
        }

        let frame_times: Vec<f64> = self.recent_metrics.iter()
            .map(|m| m.frame_ms)
            .collect();

        let energies: Vec<f64> = self.recent_metrics.iter()
            .map(|m| m.field_energy)
            .collect();

        Statistics {
            frame_time_mean: mean(&frame_times),
            frame_time_std: std_dev(&frame_times),
            frame_time_min: frame_times.iter().fold(f64::INFINITY, |a, &b| a.min(b)),
            frame_time_max: frame_times.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b)),
            energy_mean: mean(&energies),
            energy_std: std_dev(&energies),
            sample_count: self.recent_metrics.len(),
        }
    }

    /// Get entropy over time windows
    pub fn get_temporal_entropy(&self, window_size: usize) -> Vec<f64> {
        let mut entropies = Vec::new();

        for i in 0..self.history.len().saturating_sub(window_size) {
            let mut window_values = Vec::new();

            for j in 0..window_size {
                if let Some(metrics) = self.history.get_coprime(i + j, 97) {
                    window_values.push(metrics.field_energy);
                }
            }

            if window_values.len() >= window_size / 2 {
                entropies.push(calculate_entropy(&window_values, 11));
            }
        }

        entropies
    }

    /// Enable/disable console output
    pub fn set_console_output(&mut self, enabled: bool) {
        self.console_output = enabled;
    }

    /// Flush log file
    pub fn flush(&mut self) {
        if let Some(ref mut file) = self.log_file {
            let _ = file.flush();
        }
    }
}

/// Statistics over a window of metrics
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Statistics {
    pub frame_time_mean: f64,
    pub frame_time_std: f64,
    pub frame_time_min: f64,
    pub frame_time_max: f64,
    pub energy_mean: f64,
    pub energy_std: f64,
    pub sample_count: usize,
}

/// Checkpoint for saving state
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Checkpoint {
    pub metrics: ConsciousnessMetrics,
    pub history_entropy: f64,
    pub runtime_seconds: f64,
    pub recent_statistics: Statistics,
}

/// Calculate mean
fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

/// Calculate standard deviation
fn std_dev(values: &[f64]) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }

    let m = mean(values);
    let variance = values.iter()
        .map(|&v| (v - m).powi(2))
        .sum::<f64>() / (values.len() - 1) as f64;

    variance.sqrt()
}

/// Calculate entropy with specified number of bins
pub fn calculate_entropy(values: &[f64], num_bins: usize) -> f64 {
    if values.is_empty() || num_bins == 0 {
        return 0.0;
    }

    // Find range
    let min_val = values.iter().fold(f64::INFINITY, |a, &b| a.min(b));
    let max_val = values.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
    let range = max_val - min_val;

    if range < 1e-10 {
        return 0.0;
    }

    // Build histogram
    let mut histogram = vec![0u32; num_bins];
    for &val in values {
        let normalized = (val - min_val) / range;
        let bin = ((normalized * (num_bins - 1) as f64) as usize).min(num_bins - 1);
        histogram[bin] += 1;
    }

    // Calculate entropy
    let total = values.len() as f64;
    let mut entropy = 0.0;

    for &count in &histogram {
        if count > 0 {
            let p = count as f64 / total;
            entropy -= p * p.ln();
        }
    }

    entropy
}

/// Calculate trail entropy from age values (Section I from playbook)
/// Ages should be normalized between 0.0 and 1.0
pub fn trail_entropy(ages: &[f32]) -> f64 {
    if ages.is_empty() {
        return 0.0;
    }

    // Use prime number of bins (17)
    const BINS: usize = 17;
    let mut bins = [0u32; BINS];

    for &age in ages {
        let normalized = age.clamp(0.0, 1.0);
        let bin = ((normalized * (BINS - 1) as f32) as usize).min(BINS - 1);
        bins[bin] += 1;
    }

    let n = ages.len() as f64;
    let mut h = 0.0;

    for count in bins {
        if count > 0 {
            let p = count as f64 / n;
            h -= p * p.ln();
        }
    }

    h
}