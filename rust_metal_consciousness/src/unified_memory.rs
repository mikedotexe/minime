use anyhow::Result;
use metal::*;
use std::time::Instant;

/// Benchmark unified memory cache handoff performance
pub fn benchmark_cache_handoff(size: usize, iterations: usize) -> Result<f64> {
    let device = Device::system_default()
        .ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

    let command_queue = device.new_command_queue();

    // Create shared buffer
    let bytes = size * std::mem::size_of::<f32>();
    let buffer = device.new_buffer(bytes as u64, MTLResourceOptions::StorageModeShared);

    // Initialize with CPU
    unsafe {
        let ptr = buffer.contents() as *mut f32;
        let slice = std::slice::from_raw_parts_mut(ptr, size);
        for (i, v) in slice.iter_mut().enumerate() {
            *v = i as f32;
        }
    }

    // Compile simple test kernel
    let shader = r#"
        #include <metal_stdlib>
        using namespace metal;

        kernel void increment(
            device float* data [[buffer(0)]],
            uint tid [[thread_position_in_grid]])
        {
            data[tid] = data[tid] + 1.0;
        }
    "#;

    let options = CompileOptions::new();
    let library = device.new_library_with_source(shader, &options)
        .map_err(|e| anyhow::anyhow!("Failed to compile shader: {}", e))?;

    let function = library.get_function("increment", None)
        .map_err(|_| anyhow::anyhow!("Kernel not found"))?;

    let pipeline = device.new_compute_pipeline_state_with_function(&function)
        .map_err(|e| anyhow::anyhow!("Failed to create pipeline: {}", e))?;

    // Benchmark loop
    let start = Instant::now();

    for _ in 0..iterations {
        // GPU: increment values
        let command_buffer = command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&pipeline);
        encoder.set_buffer(0, Some(&buffer), 0);

        let threads = MTLSize::new(size as u64, 1, 1);
        let threadgroups = MTLSize::new(((size + 255) / 256) as u64, 1, 1);
        let threads_per_group = MTLSize::new(256, 1, 1);

        encoder.dispatch_thread_groups(threadgroups, threads_per_group);
        encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // CPU: read and modify (demonstrates cache handoff)
        unsafe {
            let ptr = buffer.contents() as *mut f32;
            let slice = std::slice::from_raw_parts_mut(ptr, size);

            // Light CPU work - normalize first element
            if slice[0] > 1000.0 {
                for v in slice.iter_mut() {
                    *v = *v / 1000.0;
                }
            }
        }
    }

    let elapsed = start.elapsed();
    let ms_per_iteration = elapsed.as_secs_f64() * 1000.0 / iterations as f64;

    Ok(ms_per_iteration)
}

/// Demonstrates the unified memory pattern for consciousness processing
pub struct UnifiedMemoryPattern {
    device: Device,
    command_queue: CommandQueue,

    // Shared buffers for zero-copy access
    state_buffer: Buffer,
    embedding_buffer: Buffer,
    output_buffer: Buffer,
}

impl UnifiedMemoryPattern {
    pub fn new(state_size: usize, embedding_size: usize) -> Result<Self> {
        let device = Device::system_default()
            .ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

        let command_queue = device.new_command_queue();

        // All buffers use StorageModeShared for unified memory
        let options = MTLResourceOptions::StorageModeShared;

        let state_buffer = device.new_buffer(
            (state_size * std::mem::size_of::<f32>()) as u64,
            options
        );

        let embedding_buffer = device.new_buffer(
            (embedding_size * std::mem::size_of::<f32>()) as u64,
            options
        );

        let output_buffer = device.new_buffer(
            (state_size * std::mem::size_of::<f32>()) as u64,
            options
        );

        Ok(UnifiedMemoryPattern {
            device,
            command_queue,
            state_buffer,
            embedding_buffer,
            output_buffer,
        })
    }

    /// CPU writes to shared buffer - no copy needed
    pub fn write_embeddings(&self, embeddings: &[f32]) -> Result<()> {
        unsafe {
            let ptr = self.embedding_buffer.contents() as *mut f32;
            ptr.copy_from_nonoverlapping(embeddings.as_ptr(), embeddings.len());
        }
        Ok(())
    }

    /// CPU reads from shared buffer - no copy needed
    pub fn read_output(&self) -> Vec<f32> {
        unsafe {
            let size = self.output_buffer.length() as usize / std::mem::size_of::<f32>();
            let ptr = self.output_buffer.contents() as *const f32;
            std::slice::from_raw_parts(ptr, size).to_vec()
        }
    }

    /// Get raw buffer pointers for direct manipulation
    pub fn get_state_ptr(&self) -> (*mut f32, usize) {
        unsafe {
            let size = self.state_buffer.length() as usize / std::mem::size_of::<f32>();
            let ptr = self.state_buffer.contents() as *mut f32;
            (ptr, size)
        }
    }
}

/// Utilities for efficient buffer management
pub mod buffer_utils {
    use super::*;

    /// Create a ring buffer for streaming data
    pub struct RingBuffer {
        buffer: Buffer,
        size: usize,
        write_pos: usize,
        read_pos: usize,
    }

    impl RingBuffer {
        pub fn new(device: &Device, size: usize) -> Result<Self> {
            let bytes = size * std::mem::size_of::<f32>();
            let buffer = device.new_buffer(
                bytes as u64,
                MTLResourceOptions::StorageModeShared
            );

            Ok(RingBuffer {
                buffer,
                size,
                write_pos: 0,
                read_pos: 0,
            })
        }

        /// Write data to ring buffer
        pub fn write(&mut self, data: &[f32]) -> Result<()> {
            if data.len() > self.size {
                return Err(anyhow::anyhow!("Data too large for ring buffer"));
            }

            unsafe {
                let ptr = self.buffer.contents() as *mut f32;

                // Handle wrap-around
                let first_chunk = (self.size - self.write_pos).min(data.len());
                ptr.add(self.write_pos)
                    .copy_from_nonoverlapping(data.as_ptr(), first_chunk);

                if first_chunk < data.len() {
                    ptr.copy_from_nonoverlapping(
                        data[first_chunk..].as_ptr(),
                        data.len() - first_chunk
                    );
                }

                self.write_pos = (self.write_pos + data.len()) % self.size;
            }

            Ok(())
        }

        /// Read available data
        pub fn read(&mut self, count: usize) -> Vec<f32> {
            let available = if self.write_pos >= self.read_pos {
                self.write_pos - self.read_pos
            } else {
                self.size - self.read_pos + self.write_pos
            };

            let to_read = count.min(available);
            let mut result = Vec::with_capacity(to_read);

            unsafe {
                let ptr = self.buffer.contents() as *const f32;

                let first_chunk = (self.size - self.read_pos).min(to_read);
                result.extend_from_slice(
                    std::slice::from_raw_parts(ptr.add(self.read_pos), first_chunk)
                );

                if first_chunk < to_read {
                    result.extend_from_slice(
                        std::slice::from_raw_parts(ptr, to_read - first_chunk)
                    );
                }

                self.read_pos = (self.read_pos + to_read) % self.size;
            }

            result
        }

        pub fn get_buffer(&self) -> &Buffer {
            &self.buffer
        }
    }

    /// Double buffering for continuous processing
    pub struct DoubleBuffer {
        buffers: [Buffer; 2],
        current: usize,
        size: usize,
    }

    impl DoubleBuffer {
        pub fn new(device: &Device, size: usize) -> Result<Self> {
            let bytes = size * std::mem::size_of::<f32>();
            let options = MTLResourceOptions::StorageModeShared;

            let buffer1 = device.new_buffer(bytes as u64, options);
            let buffer2 = device.new_buffer(bytes as u64, options);

            Ok(DoubleBuffer {
                buffers: [buffer1, buffer2],
                current: 0,
                size,
            })
        }

        /// Get current buffer for GPU processing
        pub fn get_current(&self) -> &Buffer {
            &self.buffers[self.current]
        }

        /// Get back buffer for CPU writing
        pub fn get_back(&self) -> &Buffer {
            &self.buffers[1 - self.current]
        }

        /// Swap buffers
        pub fn swap(&mut self) {
            self.current = 1 - self.current;
        }

        /// Write to back buffer
        pub fn write_back(&self, data: &[f32]) -> Result<()> {
            if data.len() > self.size {
                return Err(anyhow::anyhow!("Data too large for buffer"));
            }

            unsafe {
                let ptr = self.get_back().contents() as *mut f32;
                ptr.copy_from_nonoverlapping(data.as_ptr(), data.len());
            }

            Ok(())
        }
    }
}