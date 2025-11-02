// GPU acceleration with unified memory cache-handoff

use anyhow::Result;
use metal::*;
use std::{mem, slice};

pub struct Gpu {
    pub dev: Device,
    pub q: CommandQueue,
    pub pso_block: ComputePipelineState,
    pub lib_nn: Option<Library>, // Neural network shader library
}

impl Gpu {
    pub fn new() -> Result<Self> {
        let dev =
            Device::system_default().ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

        let q = dev.new_command_queue();

        let opts = CompileOptions::new();

        let shader_source = include_str!("../shaders/spectral.metal");
        let lib = dev
            .new_library_with_source(shader_source, &opts)
            .map_err(|e| anyhow::anyhow!("MSL compile error: {:?}", e))?;

        let fun_block = lib
            .get_function("block_matvec_tiled_f32", None)
            .map_err(|e| anyhow::anyhow!("Function not found: {:?}", e))?;

        let pso_block = dev
            .new_compute_pipeline_state_with_function(&fun_block)
            .map_err(|e| anyhow::anyhow!("PSO creation failed: {:?}", e))?;

        // Load neural network shaders
        let nn_shader_source = include_str!("../shaders/nn.metal");
        let lib_nn = dev.new_library_with_source(nn_shader_source, &opts).ok(); // Optional - graceful degradation if NN shaders not available

        Ok(Self {
            dev,
            q,
            pso_block,
            lib_nn,
        })
    }

    // Create unified memory buffer (StorageModeShared for zero-copy)
    pub fn new_shared(&self, bytes: u64) -> Buffer {
        self.dev
            .new_buffer(bytes, MTLResourceOptions::StorageModeShared)
    }

    // Block matrix-vector: Y = A * X
    // A: D×D row-major
    // X, Y: D×K col-major
    pub fn block_matvec(
        &self,
        a_buf: &Buffer,
        x_buf: &Buffer,
        y_buf: &Buffer,
        d: u32,
        k: u32,
    ) -> Result<()> {
        // Create parameter buffers
        let d_buf = self.new_shared(mem::size_of::<u32>() as u64);
        let k_buf = self.new_shared(mem::size_of::<u32>() as u64);

        unsafe {
            *(d_buf.contents() as *mut u32) = d;
            *(k_buf.contents() as *mut u32) = k;
        }

        let grid = MTLSize::new(d as u64, 1, 1);
        let threadgroup = MTLSize::new(256u64.min(d as u64), 1, 1);

        let cmd = self.q.new_command_buffer();
        let enc = cmd.new_compute_command_encoder();

        enc.set_compute_pipeline_state(&self.pso_block);
        enc.set_buffer(0, Some(a_buf), 0);
        enc.set_buffer(1, Some(x_buf), 0);
        enc.set_buffer(2, Some(y_buf), 0);
        enc.set_buffer(3, Some(&d_buf), 0);
        enc.set_buffer(4, Some(&k_buf), 0);

        enc.dispatch_thread_groups(grid, threadgroup);
        enc.end_encoding();

        cmd.commit();
        cmd.wait_until_completed();

        Ok(())
    }

    // Zero-copy write to unified memory buffer
    pub fn write_f32(&self, buf: &Buffer, data: &[f32]) {
        let bytes = data.len() * mem::size_of::<f32>();
        unsafe {
            std::ptr::copy_nonoverlapping(
                data.as_ptr() as *const u8,
                buf.contents() as *mut u8,
                bytes,
            );
        }
    }

    // Zero-copy read from unified memory buffer
    pub fn read_f32(&self, buf: &Buffer, count: usize) -> Vec<f32> {
        unsafe { slice::from_raw_parts(buf.contents() as *const f32, count) }.to_vec()
    }
}

// CPU Gram-Schmidt orthonormalization (cache handoff pattern)
pub fn gs_orthonormalize_colmajor(x: &mut [f32], n: usize, k: usize) {
    for i in 0..k {
        // Orthogonalize against previous vectors
        for j in 0..i {
            let mut dot = 0f32;
            for row in 0..n {
                dot += x[j * n + row] * x[i * n + row];
            }
            for row in 0..n {
                x[i * n + row] -= dot * x[j * n + row];
            }
        }

        // Normalize
        let mut norm_sq = 0f64;
        for row in 0..n {
            norm_sq += (x[i * n + row] as f64).powi(2);
        }
        let norm = norm_sq.sqrt().max(1e-18) as f32;

        for row in 0..n {
            x[i * n + row] /= norm;
        }
    }
}

// Rayleigh quotient for eigenvalue estimation
pub fn rayleigh_quotient(a: &[f32], x: &[f32], n: usize) -> f32 {
    let mut ax = vec![0f32; n];

    // Compute A * x
    for i in 0..n {
        let mut sum = 0f32;
        for j in 0..n {
            sum += a[i * n + j] * x[j];
        }
        ax[i] = sum;
    }

    // Compute x^T * A * x and x^T * x
    let mut num = 0f64;
    let mut den = 0f64;

    for i in 0..n {
        num += (ax[i] as f64) * (x[i] as f64);
        den += (x[i] as f64) * (x[i] as f64);
    }

    (num / den.max(1e-18)) as f32
}

// Generic write_slice helper for any Copy type
pub fn write_slice<T: Copy>(buf: &Buffer, data: &[T]) {
    let bytes = data.len() * std::mem::size_of::<T>();
    unsafe {
        std::ptr::copy_nonoverlapping(data.as_ptr(), buf.contents() as *mut T, data.len());
        buf.did_modify_range(NSRange::new(0, bytes as u64));
    }
}

// Generic read_vec helper for any Copy + Default type
pub fn read_vec<T: Copy + Default>(buf: &Buffer, count: usize) -> Vec<T> {
    unsafe { slice::from_raw_parts(buf.contents() as *const T, count).to_vec() }
}
