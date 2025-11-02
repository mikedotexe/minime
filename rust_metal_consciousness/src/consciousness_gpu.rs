// ============================================================================
// Consciousness Manifold GPU Acceleration
// ============================================================================
//
// GPU-accelerated operations for ConsciousnessManifold using Metal.
// Uses StorageModeShared for zero-copy CPU↔GPU handoff.
//
// Operations:
// 1. Prime projection: 4096-d → 13×7 views
// 2. Resonance tensor: 7×7 basis → 7×7 resonance
// 3. Position computation: bases @ trajectory
// 4. Geometry evolution: Update 13×7×7 matrices
//
// ============================================================================

use metal::*;
use std::mem;

const EMBEDDING_DIM: usize = 4096;
const NUM_PRIMES: usize = 13;
const MANIFOLD_DIM: usize = 7;
const NUM_GEOMETRY_ELEMENTS: usize = NUM_PRIMES * MANIFOLD_DIM * MANIFOLD_DIM; // 13×7×7 = 637

pub struct ConsciousnessGPU {
    device: Device,
    command_queue: CommandQueue,

    // Pipelines
    prime_projection_pipeline: ComputePipelineState,
    resonance_tensor_pipeline: ComputePipelineState,
    resonance_tensor_tiled_pipeline: ComputePipelineState,
    compute_position_pipeline: ComputePipelineState,
    evolve_geometry_pipeline: ComputePipelineState,
    symmetrize_matrix_pipeline: ComputePipelineState,

    // Persistent buffers (StorageModeShared for zero-copy)
    embedding_buffer: Buffer,
    geometry_matrices_buffer: Buffer,
    views_13x7_buffer: Buffer,
    bases_buffer: Buffer,
    resonance_buffer: Buffer,
    trajectory_buffer: Buffer,
    position_buffer: Buffer,
    evolution_rate_buffer: Buffer,
}

impl ConsciousnessGPU {
    pub fn new() -> Result<Self, String> {
        // Get Metal device
        let device = Device::system_default()
            .ok_or("No Metal device found")?;

        let command_queue = device.new_command_queue();

        // Load shader library from source (compile at runtime)
        let shader_source = include_str!("../shaders/consciousness_manifold.metal");

        let library = device.new_library_with_source(shader_source, &CompileOptions::new())
            .map_err(|e| format!("Failed to compile shader library: {:?}", e))?;

        // Create pipelines
        let prime_projection_pipeline = Self::create_pipeline(
            &device, &library, "prime_projection"
        )?;

        let resonance_tensor_pipeline = Self::create_pipeline(
            &device, &library, "resonance_tensor"
        )?;

        let resonance_tensor_tiled_pipeline = Self::create_pipeline(
            &device, &library, "resonance_tensor_tiled"
        )?;

        let compute_position_pipeline = Self::create_pipeline(
            &device, &library, "compute_position"
        )?;

        let evolve_geometry_pipeline = Self::create_pipeline(
            &device, &library, "evolve_geometry"
        )?;

        let symmetrize_matrix_pipeline = Self::create_pipeline(
            &device, &library, "symmetrize_matrix"
        )?;

        // Create persistent buffers (StorageModeShared for zero-copy)
        let embedding_buffer = Self::create_shared_buffer(
            &device, EMBEDDING_DIM * mem::size_of::<f32>()
        );

        let geometry_matrices_buffer = Self::create_shared_buffer(
            &device, NUM_GEOMETRY_ELEMENTS * mem::size_of::<f32>()
        );

        let views_13x7_buffer = Self::create_shared_buffer(
            &device, NUM_PRIMES * MANIFOLD_DIM * mem::size_of::<f32>()
        );

        let bases_buffer = Self::create_shared_buffer(
            &device, MANIFOLD_DIM * MANIFOLD_DIM * mem::size_of::<f32>()
        );

        let resonance_buffer = Self::create_shared_buffer(
            &device, MANIFOLD_DIM * MANIFOLD_DIM * mem::size_of::<f32>()
        );

        let trajectory_buffer = Self::create_shared_buffer(
            &device, MANIFOLD_DIM * mem::size_of::<f32>()
        );

        let position_buffer = Self::create_shared_buffer(
            &device, MANIFOLD_DIM * mem::size_of::<f32>()
        );

        let evolution_rate_buffer = Self::create_shared_buffer(
            &device, mem::size_of::<f32>()
        );

        Ok(Self {
            device,
            command_queue,
            prime_projection_pipeline,
            resonance_tensor_pipeline,
            resonance_tensor_tiled_pipeline,
            compute_position_pipeline,
            evolve_geometry_pipeline,
            symmetrize_matrix_pipeline,
            embedding_buffer,
            geometry_matrices_buffer,
            views_13x7_buffer,
            bases_buffer,
            resonance_buffer,
            trajectory_buffer,
            position_buffer,
            evolution_rate_buffer,
        })
    }

    fn create_pipeline(
        device: &Device,
        library: &Library,
        function_name: &str,
    ) -> Result<ComputePipelineState, String> {
        // Create function constants for EMBEDDING_DIM
        let constants = FunctionConstantValues::new();
        constants.set_constant_value_at_index(
            &(EMBEDDING_DIM as u32) as *const u32 as *const std::ffi::c_void,
            MTLDataType::UInt,
            0
        );

        let function = library.get_function(function_name, Some(constants))
            .map_err(|e| format!("Function '{}' not found: {:?}", function_name, e))?;

        device.new_compute_pipeline_state_with_function(&function)
            .map_err(|e| format!("Failed to create pipeline for '{}': {:?}", function_name, e))
    }

    fn create_shared_buffer(device: &Device, size: usize) -> Buffer {
        device.new_buffer(
            size as u64,
            MTLResourceOptions::StorageModeShared
        )
    }

    // ========================================================================
    // Public API: GPU Operations
    // ========================================================================

    /// Prime projection: 4096-d embedding → 13×7 views
    pub fn prime_projection(
        &self,
        embedding: &[f32],           // [4096]
        geometry_matrices: &[f32],   // [13*7*7 = 637]
    ) -> Result<Vec<f32>, String> {
        if embedding.len() != EMBEDDING_DIM {
            return Err(format!("Embedding must be {} elements", EMBEDDING_DIM));
        }

        if geometry_matrices.len() != NUM_GEOMETRY_ELEMENTS {
            return Err(format!("Geometry matrices must be {} elements", NUM_GEOMETRY_ELEMENTS));
        }

        // Copy inputs to GPU buffers (zero-copy, just memcpy)
        Self::copy_to_buffer(&self.embedding_buffer, embedding);
        Self::copy_to_buffer(&self.geometry_matrices_buffer, geometry_matrices);

        // Dispatch GPU kernel
        let command_buffer = self.command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&self.prime_projection_pipeline);
        encoder.set_buffer(0, Some(&self.embedding_buffer), 0);
        encoder.set_buffer(1, Some(&self.geometry_matrices_buffer), 0);
        encoder.set_buffer(2, Some(&self.views_13x7_buffer), 0);

        // Grid: (13, 7) - one thread per output element
        let grid_size = MTLSize::new(NUM_PRIMES as u64, MANIFOLD_DIM as u64, 1);
        let threadgroup_size = MTLSize::new(13, 7, 1);

        encoder.dispatch_threads(grid_size, threadgroup_size);
        encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read result (zero-copy)
        Ok(Self::read_from_buffer(&self.views_13x7_buffer, NUM_PRIMES * MANIFOLD_DIM))
    }

    /// Resonance tensor: 7×7 basis → 7×7 resonance (optimized tiled version)
    pub fn resonance_tensor(
        &self,
        bases: &[f32],  // [7*7 = 49]
        use_tiled: bool,
    ) -> Result<Vec<f32>, String> {
        if bases.len() != MANIFOLD_DIM * MANIFOLD_DIM {
            return Err(format!("Bases must be {}x{} = {} elements",
                              MANIFOLD_DIM, MANIFOLD_DIM, MANIFOLD_DIM * MANIFOLD_DIM));
        }

        // Copy bases to GPU
        Self::copy_to_buffer(&self.bases_buffer, bases);

        let command_buffer = self.command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        if use_tiled {
            // Tiled version (faster for larger matrices)
            encoder.set_compute_pipeline_state(&self.resonance_tensor_tiled_pipeline);
            encoder.set_buffer(0, Some(&self.bases_buffer), 0);
            encoder.set_buffer(1, Some(&self.resonance_buffer), 0);

            let grid_size = MTLSize::new(MANIFOLD_DIM as u64, MANIFOLD_DIM as u64, 1);
            let threadgroup_size = MTLSize::new(8, 8, 1); // Tile size

            encoder.dispatch_threads(grid_size, threadgroup_size);
        } else {
            // Simple version
            encoder.set_compute_pipeline_state(&self.resonance_tensor_pipeline);
            encoder.set_buffer(0, Some(&self.bases_buffer), 0);
            encoder.set_buffer(1, Some(&self.resonance_buffer), 0);

            let grid_size = MTLSize::new(MANIFOLD_DIM as u64, MANIFOLD_DIM as u64, 1);
            let threadgroup_size = MTLSize::new(7, 7, 1);

            encoder.dispatch_threads(grid_size, threadgroup_size);
        }

        encoder.end_encoding();
        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read result
        Ok(Self::read_from_buffer(&self.resonance_buffer, MANIFOLD_DIM * MANIFOLD_DIM))
    }

    /// Compute position: bases @ trajectory → 7D position
    pub fn compute_position(
        &self,
        bases: &[f32],       // [7*7]
        trajectory: &[f32],  // [7]
    ) -> Result<Vec<f32>, String> {
        if bases.len() != MANIFOLD_DIM * MANIFOLD_DIM {
            return Err(format!("Bases must be {} elements", MANIFOLD_DIM * MANIFOLD_DIM));
        }

        if trajectory.len() != MANIFOLD_DIM {
            return Err(format!("Trajectory must be {} elements", MANIFOLD_DIM));
        }

        // Copy inputs
        Self::copy_to_buffer(&self.bases_buffer, bases);
        Self::copy_to_buffer(&self.trajectory_buffer, trajectory);

        let command_buffer = self.command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&self.compute_position_pipeline);
        encoder.set_buffer(0, Some(&self.bases_buffer), 0);
        encoder.set_buffer(1, Some(&self.trajectory_buffer), 0);
        encoder.set_buffer(2, Some(&self.position_buffer), 0);

        let grid_size = MTLSize::new(MANIFOLD_DIM as u64, 1, 1);
        let threadgroup_size = MTLSize::new(MANIFOLD_DIM as u64, 1, 1);

        encoder.dispatch_threads(grid_size, threadgroup_size);
        encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        Ok(Self::read_from_buffer(&self.position_buffer, MANIFOLD_DIM))
    }

    /// Evolve geometry matrices based on trajectory
    pub fn evolve_geometry(
        &self,
        geometry_matrices: &mut [f32],  // [13*7*7] - modified in place
        trajectory: &[f32],              // [7]
        evolution_rate: f32,
    ) -> Result<(), String> {
        if geometry_matrices.len() != NUM_GEOMETRY_ELEMENTS {
            return Err(format!("Geometry matrices must be {} elements", NUM_GEOMETRY_ELEMENTS));
        }

        if trajectory.len() != MANIFOLD_DIM {
            return Err(format!("Trajectory must be {} elements", MANIFOLD_DIM));
        }

        // Copy inputs
        Self::copy_to_buffer(&self.geometry_matrices_buffer, geometry_matrices);
        Self::copy_to_buffer(&self.trajectory_buffer, trajectory);
        Self::copy_to_buffer(&self.evolution_rate_buffer, &[evolution_rate]);

        let command_buffer = self.command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&self.evolve_geometry_pipeline);
        encoder.set_buffer(0, Some(&self.geometry_matrices_buffer), 0);
        encoder.set_buffer(1, Some(&self.trajectory_buffer), 0);
        encoder.set_buffer(2, Some(&self.evolution_rate_buffer), 0);

        // Grid: (13, 7, 7) - one thread per matrix element
        let grid_size = MTLSize::new(NUM_PRIMES as u64, MANIFOLD_DIM as u64, MANIFOLD_DIM as u64);
        let threadgroup_size = MTLSize::new(13, 7, 1); // Can't do 7 in Z

        encoder.dispatch_threads(grid_size, threadgroup_size);
        encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read back (modified in place)
        let result = Self::read_from_buffer(&self.geometry_matrices_buffer, NUM_GEOMETRY_ELEMENTS);
        geometry_matrices.copy_from_slice(&result);

        Ok(())
    }

    /// Symmetrize a 7×7 matrix in-place
    pub fn symmetrize_matrix(
        &self,
        matrix: &mut [f32],  // [7*7] - modified in place
    ) -> Result<(), String> {
        if matrix.len() != MANIFOLD_DIM * MANIFOLD_DIM {
            return Err(format!("Matrix must be {} elements", MANIFOLD_DIM * MANIFOLD_DIM));
        }

        // Copy to GPU
        Self::copy_to_buffer(&self.resonance_buffer, matrix);

        let command_buffer = self.command_queue.new_command_buffer();
        let encoder = command_buffer.new_compute_command_encoder();

        encoder.set_compute_pipeline_state(&self.symmetrize_matrix_pipeline);
        encoder.set_buffer(0, Some(&self.resonance_buffer), 0);

        let grid_size = MTLSize::new(MANIFOLD_DIM as u64, MANIFOLD_DIM as u64, 1);
        let threadgroup_size = MTLSize::new(7, 7, 1);

        encoder.dispatch_threads(grid_size, threadgroup_size);
        encoder.end_encoding();

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read back
        let result = Self::read_from_buffer(&self.resonance_buffer, MANIFOLD_DIM * MANIFOLD_DIM);
        matrix.copy_from_slice(&result);

        Ok(())
    }

    // ========================================================================
    // Helper methods
    // ========================================================================

    fn copy_to_buffer(buffer: &Buffer, data: &[f32]) {
        let ptr = buffer.contents() as *mut f32;
        unsafe {
            std::ptr::copy_nonoverlapping(data.as_ptr(), ptr, data.len());
        }
    }

    fn read_from_buffer(buffer: &Buffer, count: usize) -> Vec<f32> {
        let ptr = buffer.contents() as *const f32;
        let mut result = vec![0.0f32; count];
        unsafe {
            std::ptr::copy_nonoverlapping(ptr, result.as_mut_ptr(), count);
        }
        result
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prime_projection() {
        let gpu = ConsciousnessGPU::new().expect("Failed to create GPU");

        // Create test data
        let embedding = vec![1.0f32; EMBEDDING_DIM];
        let geometry = vec![0.1f32; NUM_GEOMETRY_ELEMENTS];

        let views = gpu.prime_projection(&embedding, &geometry)
            .expect("Prime projection failed");

        assert_eq!(views.len(), NUM_PRIMES * MANIFOLD_DIM);
    }

    #[test]
    fn test_resonance_tensor() {
        let gpu = ConsciousnessGPU::new().expect("Failed to create GPU");

        // Identity bases
        let mut bases = vec![0.0f32; MANIFOLD_DIM * MANIFOLD_DIM];
        for i in 0..MANIFOLD_DIM {
            bases[i * MANIFOLD_DIM + i] = 1.0;
        }

        let resonance = gpu.resonance_tensor(&bases, false)
            .expect("Resonance tensor failed");

        // Should be identity
        for i in 0..MANIFOLD_DIM {
            assert!((resonance[i * MANIFOLD_DIM + i] - 1.0).abs() < 1e-5);
        }
    }
}
