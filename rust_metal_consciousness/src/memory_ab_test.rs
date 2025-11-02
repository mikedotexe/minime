use anyhow::Result;
use metal::*;
use std::time::Instant;
use std::collections::HashMap;

/// Memory mode options for A/B testing
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum MemoryMode {
    /// Unified memory - zero copy (default on Apple Silicon)
    Shared,
    /// Managed memory - requires explicit synchronization
    Managed,
    /// Private GPU memory with staging buffers
    Private,
}

/// A/B test runner for comparing memory modes
pub struct MemoryModeComparator {
    device: Device,
    command_queue: CommandQueue,
    library: Library,

    // Test configurations
    buffer_size: usize,
    iterations: usize,

    // Results storage
    results: HashMap<MemoryMode, TestResults>,
}

/// Results from a memory mode test
#[derive(Debug, Clone)]
pub struct TestResults {
    pub mode: MemoryMode,
    pub total_time_ms: f64,
    pub gpu_time_ms: f64,
    pub cpu_time_ms: f64,
    pub sync_time_ms: f64,
    pub copies_per_iteration: u32,
    pub bandwidth_gbps: f64,
    pub frame_times: Vec<f64>,
}

impl MemoryModeComparator {
    pub fn new(buffer_size: usize, iterations: usize) -> Result<Self> {
        let device = Device::system_default()
            .ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

        let command_queue = device.new_command_queue();

        // Load test shaders
        let shader_source = include_str!("../shaders/memory_test.metal");
        let options = CompileOptions::new();
        let library = device.new_library_with_source(shader_source, &options)
            .map_err(|e| anyhow::anyhow!("Failed to compile test shaders: {}", e))?;

        Ok(MemoryModeComparator {
            device,
            command_queue,
            library,
            buffer_size,
            iterations,
            results: HashMap::new(),
        })
    }

    /// Run tests for all memory modes
    pub fn run_all_tests(&mut self) -> Result<()> {
        println!("\n=== Memory Mode A/B Test ===");
        println!("Buffer size: {} MB", self.buffer_size / (1024 * 1024));
        println!("Iterations: {}\n", self.iterations);

        // Test each mode
        for mode in &[MemoryMode::Shared, MemoryMode::Managed, MemoryMode::Private] {
            println!("Testing {:?} mode...", mode);
            let results = self.test_memory_mode(*mode)?;
            self.results.insert(*mode, results);
        }

        // Print comparison
        self.print_comparison();

        Ok(())
    }

    /// Test a specific memory mode
    fn test_memory_mode(&self, mode: MemoryMode) -> Result<TestResults> {
        let start_total = Instant::now();
        let mut frame_times = Vec::with_capacity(self.iterations);
        let mut gpu_time_total = 0.0;
        let mut cpu_time_total = 0.0;
        let mut sync_time_total = 0.0;

        // Create buffers based on mode
        let (src_buffer, dst_buffer, staging_src, staging_dst) = self.create_buffers(mode)?;

        // Create compute pipeline
        let function = self.library.get_function("memory_test_kernel", None)
            .map_err(|_| anyhow::anyhow!("Test kernel not found"))?;

        let pipeline = self.device.new_compute_pipeline_state_with_function(&function)
            .map_err(|e| anyhow::anyhow!("Failed to create pipeline: {}", e))?;

        // Warmup
        for _ in 0..5 {
            self.run_iteration(mode, &src_buffer, &dst_buffer, &staging_src, &staging_dst, &pipeline)?;
        }

        // Actual test
        for _ in 0..self.iterations {
            let frame_start = Instant::now();

            // CPU write
            let cpu_start = Instant::now();
            self.cpu_write(mode, &src_buffer, &staging_src)?;
            cpu_time_total += cpu_start.elapsed().as_secs_f64() * 1000.0;

            // Synchronize if needed (Managed mode)
            let sync_start = Instant::now();
            if mode == MemoryMode::Managed {
                self.sync_to_gpu(&src_buffer)?;
            }
            sync_time_total += sync_start.elapsed().as_secs_f64() * 1000.0;

            // GPU processing
            let gpu_start = Instant::now();
            self.gpu_process(&src_buffer, &dst_buffer, &staging_src, &staging_dst, &pipeline, mode)?;
            gpu_time_total += gpu_start.elapsed().as_secs_f64() * 1000.0;

            // Synchronize from GPU if needed
            let sync_start = Instant::now();
            if mode == MemoryMode::Managed {
                self.sync_from_gpu(&dst_buffer)?;
            }
            sync_time_total += sync_start.elapsed().as_secs_f64() * 1000.0;

            // CPU read
            let cpu_start = Instant::now();
            self.cpu_read(mode, &dst_buffer, &staging_dst)?;
            cpu_time_total += cpu_start.elapsed().as_secs_f64() * 1000.0;

            frame_times.push(frame_start.elapsed().as_secs_f64() * 1000.0);
        }

        let total_time = start_total.elapsed().as_secs_f64() * 1000.0;

        // Calculate bandwidth
        let bytes_per_iteration = self.buffer_size * 2; // Read + write
        let total_bytes = bytes_per_iteration * self.iterations;
        let bandwidth_gbps = (total_bytes as f64 / 1e9) / (total_time / 1000.0);

        // Determine copies per iteration
        let copies_per_iteration = match mode {
            MemoryMode::Shared => 0,
            MemoryMode::Managed => 0, // No explicit copies, just syncs
            MemoryMode::Private => 2, // Copy in + copy out
        };

        Ok(TestResults {
            mode,
            total_time_ms: total_time,
            gpu_time_ms: gpu_time_total,
            cpu_time_ms: cpu_time_total,
            sync_time_ms: sync_time_total,
            copies_per_iteration,
            bandwidth_gbps,
            frame_times,
        })
    }

    /// Create buffers based on memory mode
    fn create_buffers(&self, mode: MemoryMode) -> Result<(Buffer, Buffer, Option<Buffer>, Option<Buffer>)> {
        let options = match mode {
            MemoryMode::Shared => MTLResourceOptions::StorageModeShared,
            MemoryMode::Managed => MTLResourceOptions::StorageModeManaged,
            MemoryMode::Private => MTLResourceOptions::StorageModePrivate,
        };

        let src_buffer = self.device.new_buffer(self.buffer_size as u64, options);
        let dst_buffer = self.device.new_buffer(self.buffer_size as u64, options);

        // Create staging buffers for Private mode
        let (staging_src, staging_dst) = if mode == MemoryMode::Private {
            (
                Some(self.device.new_buffer(self.buffer_size as u64, MTLResourceOptions::StorageModeShared)),
                Some(self.device.new_buffer(self.buffer_size as u64, MTLResourceOptions::StorageModeShared))
            )
        } else {
            (None, None)
        };

        Ok((src_buffer, dst_buffer, staging_src, staging_dst))
    }

    /// CPU write operation
    fn cpu_write(&self, mode: MemoryMode, buffer: &Buffer, staging: &Option<Buffer>) -> Result<()> {
        let write_buffer = match mode {
            MemoryMode::Private => staging.as_ref().unwrap(),
            _ => buffer,
        };

        unsafe {
            let ptr = write_buffer.contents() as *mut f32;
            let slice = std::slice::from_raw_parts_mut(ptr, self.buffer_size / 4);

            // Simulate some CPU work
            for (i, v) in slice.iter_mut().enumerate() {
                *v = (i as f32).sin() * 2.0;
            }
        }

        Ok(())
    }

    /// CPU read operation
    fn cpu_read(&self, mode: MemoryMode, buffer: &Buffer, staging: &Option<Buffer>) -> Result<f32> {
        let read_buffer = match mode {
            MemoryMode::Private => staging.as_ref().unwrap(),
            _ => buffer,
        };

        unsafe {
            let ptr = read_buffer.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, self.buffer_size / 4);

            // Simulate some CPU work - compute sum
            let sum: f32 = slice.iter().sum();
            Ok(sum)
        }
    }

    /// Synchronize to GPU (Managed mode)
    fn sync_to_gpu(&self, buffer: &Buffer) -> Result<()> {
        buffer.did_modify_range(NSRange {
            location: 0,
            length: self.buffer_size as u64,
        });
        Ok(())
    }

    /// Synchronize from GPU (Managed mode)
    fn sync_from_gpu(&self, buffer: &Buffer) -> Result<()> {
        let command_buffer = self.command_queue.new_command_buffer();
        let blit_encoder = command_buffer.new_blit_command_encoder();

        blit_encoder.synchronize_resource(buffer);
        blit_encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        Ok(())
    }

    /// GPU processing step
    fn gpu_process(
        &self,
        src: &Buffer,
        dst: &Buffer,
        staging_src: &Option<Buffer>,
        staging_dst: &Option<Buffer>,
        pipeline: &ComputePipelineState,
        mode: MemoryMode,
    ) -> Result<()> {
        let command_buffer = self.command_queue.new_command_buffer();

        // Copy staging to GPU if Private mode
        if mode == MemoryMode::Private {
            let blit_encoder = command_buffer.new_blit_command_encoder();
            blit_encoder.copy_from_buffer(
                staging_src.as_ref().unwrap(),
                0,
                src,
                0,
                self.buffer_size as u64
            );
            blit_encoder.end_encoding();
        }

        // Run compute kernel
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(pipeline);
        encoder.set_buffer(0, Some(src), 0);
        encoder.set_buffer(1, Some(dst), 0);

        let threads_per_group = MTLSize::new(256, 1, 1);
        let thread_groups = MTLSize::new(((self.buffer_size / 4 + 255) / 256) as u64, 1, 1);

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        // Copy GPU to staging if Private mode
        if mode == MemoryMode::Private {
            let blit_encoder = command_buffer.new_blit_command_encoder();
            blit_encoder.copy_from_buffer(
                dst,
                0,
                staging_dst.as_ref().unwrap(),
                0,
                self.buffer_size as u64
            );
            blit_encoder.end_encoding();
        }

        command_buffer.commit();
        command_buffer.wait_until_completed();

        Ok(())
    }

    /// Run a single iteration
    fn run_iteration(
        &self,
        mode: MemoryMode,
        src: &Buffer,
        dst: &Buffer,
        staging_src: &Option<Buffer>,
        staging_dst: &Option<Buffer>,
        pipeline: &ComputePipelineState,
    ) -> Result<()> {
        self.cpu_write(mode, src, staging_src)?;

        if mode == MemoryMode::Managed {
            self.sync_to_gpu(src)?;
        }

        self.gpu_process(src, dst, staging_src, staging_dst, pipeline, mode)?;

        if mode == MemoryMode::Managed {
            self.sync_from_gpu(dst)?;
        }

        self.cpu_read(mode, dst, staging_dst)?;

        Ok(())
    }

    /// Print comparison results
    fn print_comparison(&self) {
        println!("\n=== Results Summary ===\n");

        // Header
        println!("{:<12} {:>12} {:>12} {:>12} {:>12} {:>12} {:>12}",
                 "Mode", "Total (ms)", "GPU (ms)", "CPU (ms)", "Sync (ms)", "Copies", "BW (GB/s)");
        println!("{:-<96}", "");

        // Results
        for mode in &[MemoryMode::Shared, MemoryMode::Managed, MemoryMode::Private] {
            if let Some(result) = self.results.get(mode) {
                println!("{:<12} {:>12.2} {:>12.2} {:>12.2} {:>12.2} {:>12} {:>12.2}",
                         format!("{:?}", mode),
                         result.total_time_ms,
                         result.gpu_time_ms,
                         result.cpu_time_ms,
                         result.sync_time_ms,
                         result.copies_per_iteration,
                         result.bandwidth_gbps);
            }
        }

        // Calculate speedups
        if let (Some(shared), Some(managed), Some(private)) = (
            self.results.get(&MemoryMode::Shared),
            self.results.get(&MemoryMode::Managed),
            self.results.get(&MemoryMode::Private),
        ) {
            println!("\n=== Relative Performance ===");
            println!("Managed vs Shared: {:.1}x slower", managed.total_time_ms / shared.total_time_ms);
            println!("Private vs Shared: {:.1}x slower", private.total_time_ms / shared.total_time_ms);

            println!("\n=== Cache Handoff Advantage ===");
            let shared_latency = shared.total_time_ms / self.iterations as f64;
            let private_latency = private.total_time_ms / self.iterations as f64;
            println!("Shared mode latency: {:.3} ms/iteration", shared_latency);
            println!("Private mode latency: {:.3} ms/iteration", private_latency);
            println!("Latency reduction: {:.1}%",
                    (private_latency - shared_latency) / private_latency * 100.0);
        }
    }
}

// Add memory test shader
pub const MEMORY_TEST_SHADER: &str = r#"
#include <metal_stdlib>
using namespace metal;

kernel void memory_test_kernel(
    device const float* input [[buffer(0)]],
    device float* output [[buffer(1)]],
    uint tid [[thread_position_in_grid]])
{
    // Simple operation to test memory bandwidth
    float value = input[tid];

    // Some computation to ensure GPU actually processes
    value = sin(value) * cos(value) + value * 0.5;
    value = tanh(value * 2.0) * 0.9;

    output[tid] = value;
}
"#;