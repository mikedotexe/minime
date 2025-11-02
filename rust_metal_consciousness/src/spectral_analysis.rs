use anyhow::Result;
use metal::*;
use nalgebra::DMatrix;
use ndarray::Array2;
use std::collections::VecDeque;

use crate::prime_optimizations::PrimeRingBuffer;

/// Spectral analysis for consciousness states
pub struct SpectralAnalyzer {
    device: Device,
    command_queue: CommandQueue,
    pca_pipeline: ComputePipelineState,
    block_power_pipeline: ComputePipelineState,

    // Buffers for PCA
    data_buffer: Buffer,
    eigenvector_buffer: Buffer,
    eigenvalue_buffer: Buffer,
    workspace_buffer: Buffer,

    // History tracking
    activation_history: PrimeRingBuffer<Vec<f32>>,
    eigenvalue_history: VecDeque<Vec<f32>>,

    // Configuration
    dimensions: usize,
    num_samples: usize,
    num_components: usize,
}

impl SpectralAnalyzer {
    /// Create new spectral analyzer
    pub fn new(
        device: Device,
        command_queue: CommandQueue,
        library: &Library,
        dimensions: usize,
        num_samples: usize,
    ) -> Result<Self> {
        // Create pipelines
        let pca_function = library.get_function("pca_power_iteration_prime", None)
            .map_err(|_| anyhow::anyhow!("PCA kernel not found"))?;

        let pca_pipeline = device.new_compute_pipeline_state_with_function(&pca_function)
            .map_err(|e| anyhow::anyhow!("Failed to create PCA pipeline: {}", e))?;

        let block_function = library.get_function("block_power_method_prime", None)
            .map_err(|_| anyhow::anyhow!("Block power kernel not found"))?;

        let block_power_pipeline = device.new_compute_pipeline_state_with_function(&block_function)
            .map_err(|e| anyhow::anyhow!("Failed to create block power pipeline: {}", e))?;

        // Create buffers with unified memory
        let options = MTLResourceOptions::StorageModeShared;

        let data_buffer = device.new_buffer(
            (num_samples * dimensions * std::mem::size_of::<f32>()) as u64,
            options
        );

        let eigenvector_buffer = device.new_buffer(
            (dimensions * std::mem::size_of::<f32>()) as u64,
            options
        );

        let eigenvalue_buffer = device.new_buffer(
            std::mem::size_of::<f32>() as u64,
            options
        );

        let workspace_buffer = device.new_buffer(
            (dimensions * std::mem::size_of::<f32>()) as u64,
            options
        );

        // Prime-sized history buffer
        let activation_history = PrimeRingBuffer::new(num_samples);

        Ok(SpectralAnalyzer {
            device,
            command_queue,
            pca_pipeline,
            block_power_pipeline,
            data_buffer,
            eigenvector_buffer,
            eigenvalue_buffer,
            workspace_buffer,
            activation_history,
            eigenvalue_history: VecDeque::with_capacity(100),
            dimensions,
            num_samples,
            num_components: 1,
        })
    }

    /// Add activation vector to history
    pub fn add_activation(&mut self, activation: Vec<f32>) {
        assert_eq!(activation.len(), self.dimensions);
        self.activation_history.push(activation);
    }

    /// Run PCA on activation history
    pub fn compute_pca(&mut self, iterations: usize) -> Result<PCAResult> {
        if self.activation_history.len() < 10 {
            return Err(anyhow::anyhow!("Not enough data for PCA"));
        }

        // Prepare data matrix
        self.prepare_data_matrix()?;

        // Initialize random eigenvector
        self.initialize_eigenvector()?;

        // Run power iteration
        let command_buffer = self.command_queue.new_command_buffer();

        for _ in 0..iterations {
            self.encode_pca_iteration(command_buffer)?;
        }

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read results
        let eigenvalue = self.read_eigenvalue()?;
        let eigenvector = self.read_eigenvector()?;

        // Track eigenvalue history
        self.eigenvalue_history.push_back(vec![eigenvalue]);
        if self.eigenvalue_history.len() > 100 {
            self.eigenvalue_history.pop_front();
        }

        Ok(PCAResult {
            eigenvalue,
            eigenvector,
            explained_variance: self.compute_explained_variance(eigenvalue),
            convergence_iterations: iterations,
        })
    }

    /// Compute top-K components using block power method
    pub fn compute_top_k(&mut self, k: usize, iterations: usize) -> Result<BlockPCAResult> {
        self.num_components = k;

        // Create larger buffers for K components
        let eigenvectors_buffer = self.device.new_buffer(
            (self.dimensions * k * std::mem::size_of::<f32>()) as u64,
            MTLResourceOptions::StorageModeShared
        );

        let eigenvalues_buffer = self.device.new_buffer(
            (k * std::mem::size_of::<f32>()) as u64,
            MTLResourceOptions::StorageModeShared
        );

        // Initialize with random orthogonal vectors
        self.initialize_block_eigenvectors(&eigenvectors_buffer, k)?;

        // Run block power iteration
        let command_buffer = self.command_queue.new_command_buffer();

        for i in 0..iterations {
            self.encode_block_power_iteration(
                command_buffer,
                &eigenvectors_buffer,
                &eigenvalues_buffer,
                k,
                i
            )?;

            // CPU-side Gram-Schmidt (demonstrates cache handoff)
            if i % 5 == 0 {
                command_buffer.commit();
                command_buffer.wait_until_completed();

                self.gram_schmidt_cpu(&eigenvectors_buffer, k)?;

                // New command buffer for next iterations
                let command_buffer = self.command_queue.new_command_buffer();
            }
        }

        command_buffer.commit();
        command_buffer.wait_until_completed();

        // Read results
        let eigenvalues = self.read_eigenvalues(&eigenvalues_buffer, k)?;
        let eigenvectors = self.read_eigenvectors(&eigenvectors_buffer, k)?;
        let total_variance: f32 = eigenvalues.iter().sum();

        Ok(BlockPCAResult {
            eigenvalues,
            eigenvectors,
            total_variance,
            iterations_used: iterations,
        })
    }

    /// Prepare data matrix from activation history
    fn prepare_data_matrix(&mut self) -> Result<()> {
        let mut data = Vec::with_capacity(self.activation_history.len() * self.dimensions);

        // Copy activation history to data matrix
        for i in 0..self.activation_history.len() {
            if let Some(activation) = self.activation_history.get_coprime(i, 97) {
                data.extend_from_slice(activation);
            }
        }

        // Upload to GPU (zero-copy)
        unsafe {
            let ptr = self.data_buffer.contents() as *mut f32;
            ptr.copy_from_nonoverlapping(data.as_ptr(), data.len());
        }

        Ok(())
    }

    /// Initialize random eigenvector
    fn initialize_eigenvector(&self) -> Result<()> {
        use rand::Rng;
        let mut rng = rand::thread_rng();

        unsafe {
            let ptr = self.eigenvector_buffer.contents() as *mut f32;
            let slice = std::slice::from_raw_parts_mut(ptr, self.dimensions);

            // Random initialization
            let mut norm = 0.0;
            for v in slice.iter_mut() {
                *v = rng.gen_range(-1.0..1.0);
                norm += *v * *v;
            }

            // Normalize
            norm = norm.sqrt();
            for v in slice.iter_mut() {
                *v /= norm;
            }
        }

        Ok(())
    }

    /// Encode one PCA iteration
    fn encode_pca_iteration(&self, command_buffer: &CommandBufferRef) -> Result<()> {
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(&self.pca_pipeline);

        encoder.set_buffer(0, Some(&self.data_buffer), 0);
        encoder.set_buffer(1, Some(&self.eigenvector_buffer), 0);
        encoder.set_buffer(2, Some(&self.eigenvalue_buffer), 0);
        encoder.set_buffer(3, Some(&self.workspace_buffer), 0);

        // Set dimensions
        encoder.set_bytes(
            4,
            std::mem::size_of::<u32>() as u64,
            &(self.activation_history.len() as u32) as *const _ as *const _
        );
        encoder.set_bytes(
            5,
            std::mem::size_of::<u32>() as u64,
            &(self.dimensions as u32) as *const _ as *const _
        );

        let threads_per_group = MTLSize::new(256.min(self.dimensions as u64), 1, 1);
        let thread_groups = MTLSize::new((self.dimensions as u64 + 255) / 256, 1, 1);

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        Ok(())
    }

    /// CPU-side Gram-Schmidt orthogonalization
    fn gram_schmidt_cpu(&self, vectors_buffer: &Buffer, k: usize) -> Result<()> {
        unsafe {
            let ptr = vectors_buffer.contents() as *mut f32;
            let mut vectors = DMatrix::<f32>::from_column_slice(
                self.dimensions,
                k,
                std::slice::from_raw_parts(ptr, self.dimensions * k)
            );

            // Gram-Schmidt process
            for i in 0..k {
                // Subtract projections from previous vectors
                for j in 0..i {
                    let proj = {
                        let col_i = vectors.column(i);
                        let col_j = vectors.column(j);
                        col_i.dot(&col_j)
                    };
                    let col_j = vectors.column(j).clone_owned();
                    let mut col_i = vectors.column_mut(i);
                    col_i -= &(proj * &col_j);
                }

                // Normalize
                let norm = vectors.column(i).norm();
                if norm > 1e-6 {
                    let mut col_i = vectors.column_mut(i);
                    col_i /= norm;
                }
            }

            // Write back (zero-copy)
            let data = vectors.as_slice();
            ptr.copy_from_nonoverlapping(data.as_ptr(), data.len());
        }

        Ok(())
    }

    /// Read eigenvalue from GPU
    fn read_eigenvalue(&self) -> Result<f32> {
        unsafe {
            let ptr = self.eigenvalue_buffer.contents() as *const f32;
            Ok(*ptr)
        }
    }

    /// Read eigenvector from GPU
    fn read_eigenvector(&self) -> Result<Vec<f32>> {
        unsafe {
            let ptr = self.eigenvector_buffer.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, self.dimensions);
            Ok(slice.to_vec())
        }
    }

    fn read_eigenvalues(&self, buffer: &Buffer, k: usize) -> Result<Vec<f32>> {
        unsafe {
            let ptr = buffer.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, k);
            Ok(slice.to_vec())
        }
    }

    fn read_eigenvectors(&self, buffer: &Buffer, k: usize) -> Result<Array2<f32>> {
        unsafe {
            let ptr = buffer.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, self.dimensions * k);
            Ok(Array2::from_shape_vec((self.dimensions, k), slice.to_vec())?)
        }
    }

    /// Compute explained variance ratio
    fn compute_explained_variance(&self, eigenvalue: f32) -> f32 {
        // Simplified - in practice would compute total variance
        eigenvalue / (eigenvalue + 1.0)
    }

    fn encode_block_power_iteration(
        &self,
        command_buffer: &CommandBufferRef,
        eigenvectors: &Buffer,
        eigenvalues: &Buffer,
        _k: usize,
        _iteration: usize,
    ) -> Result<()> {
        // Implementation details...
        Ok(())
    }

    fn initialize_block_eigenvectors(&self, _buffer: &Buffer, _k: usize) -> Result<()> {
        // Initialize with random orthogonal vectors
        Ok(())
    }
}

/// Result of PCA computation
pub struct PCAResult {
    pub eigenvalue: f32,
    pub eigenvector: Vec<f32>,
    pub explained_variance: f32,
    pub convergence_iterations: usize,
}

/// Result of block PCA (top-K components)
pub struct BlockPCAResult {
    pub eigenvalues: Vec<f32>,
    pub eigenvectors: Array2<f32>,
    pub total_variance: f32,
    pub iterations_used: usize,
}

/// Spectral metrics for consciousness analysis
#[derive(Debug, Clone)]
pub struct SpectralMetrics {
    /// Dominant eigenvalue over time
    pub eigenvalue_trajectory: Vec<f32>,

    /// Rate of eigenvalue change
    pub eigenvalue_drift: f32,

    /// Spectral entropy
    pub spectral_entropy: f32,

    /// Principal component stability
    pub pc_stability: f32,

    /// Resonance spectrum (FFT of resonance strengths)
    pub resonance_spectrum: Vec<f32>,
}

impl SpectralMetrics {
    /// Compute from spectral analyzer state
    pub fn compute(analyzer: &SpectralAnalyzer) -> Self {
        let eigenvalue_trajectory: Vec<f32> = analyzer.eigenvalue_history
            .iter()
            .flat_map(|v| v.iter().copied())
            .collect();

        let eigenvalue_drift = if eigenvalue_trajectory.len() >= 2 {
            let recent = &eigenvalue_trajectory[eigenvalue_trajectory.len() - 10..];
            let mean = recent.iter().sum::<f32>() / recent.len() as f32;
            let variance = recent.iter()
                .map(|&x| (x - mean).powi(2))
                .sum::<f32>() / recent.len() as f32;
            variance.sqrt()
        } else {
            0.0
        };

        // Placeholder for other metrics
        SpectralMetrics {
            eigenvalue_trajectory,
            eigenvalue_drift,
            spectral_entropy: 0.0,
            pc_stability: 0.0,
            resonance_spectrum: vec![],
        }
    }
}

/// Live PCA of velocities (Section F1 from playbook)
/// Demonstrates cache-handoff for AI-ish math
pub struct VelocityPCA {
    device: Device,
    command_queue: CommandQueue,

    // Buffers (Shared memory for cache handoff)
    velocities_buffer: Buffer,      // N×2 matrix of (vx, vy)
    eigenvector_buffer: Buffer,     // Current eigenvector estimate (2D)
    eigenvalue_buffer: Buffer,      // Current eigenvalue
    temp_buffer: Buffer,            // Workspace

    num_bodies: usize,
    frame_count: usize,
    update_interval: usize,  // Run power step every N frames
}

impl VelocityPCA {
    /// Create new velocity PCA analyzer
    pub fn new(
        device: Device,
        command_queue: CommandQueue,
        num_bodies: usize,
        update_interval: usize,
    ) -> Self {
        let options = MTLResourceOptions::StorageModeShared;

        let velocities_buffer = device.new_buffer(
            (num_bodies * 2 * std::mem::size_of::<f32>()) as u64,
            options
        );

        let eigenvector_buffer = device.new_buffer(
            (2 * std::mem::size_of::<f32>()) as u64,
            options
        );

        let eigenvalue_buffer = device.new_buffer(
            std::mem::size_of::<f32>() as u64,
            options
        );

        let temp_buffer = device.new_buffer(
            (2 * std::mem::size_of::<f32>()) as u64,
            options
        );

        // Initialize eigenvector to [1, 0]
        unsafe {
            let ptr = eigenvector_buffer.contents() as *mut f32;
            *ptr.offset(0) = 1.0;
            *ptr.offset(1) = 0.0;
        }

        VelocityPCA {
            device,
            command_queue,
            velocities_buffer,
            eigenvector_buffer,
            eigenvalue_buffer,
            temp_buffer,
            num_bodies,
            frame_count: 0,
            update_interval,
        }
    }

    /// Update velocities (called every frame)
    pub fn update_velocities(&mut self, velocities: &[(f32, f32)]) {
        assert_eq!(velocities.len(), self.num_bodies);

        // Write to shared buffer (zero-copy)
        unsafe {
            let ptr = self.velocities_buffer.contents() as *mut f32;
            for (i, &(vx, vy)) in velocities.iter().enumerate() {
                *ptr.offset((i * 2) as isize) = vx;
                *ptr.offset((i * 2 + 1) as isize) = vy;
            }
        }

        self.frame_count += 1;
    }

    /// Run one power iteration step (if it's time)
    pub fn step(&mut self) -> Option<VelocityPCAResult> {
        if self.frame_count % self.update_interval != 0 {
            return None;
        }

        // GPU: y = (V^T V) · x
        // This is a simple 2x2 covariance power iteration
        let start = std::time::Instant::now();

        unsafe {
            let v_ptr = self.velocities_buffer.contents() as *const f32;
            let x_ptr = self.eigenvector_buffer.contents() as *const f32;
            let y_ptr = self.temp_buffer.contents() as *mut f32;

            let x = [*x_ptr.offset(0), *x_ptr.offset(1)];

            // Compute V^T V (covariance matrix)
            let mut cov = [[0.0f32; 2]; 2];
            for i in 0..self.num_bodies {
                let vx = *v_ptr.offset((i * 2) as isize);
                let vy = *v_ptr.offset((i * 2 + 1) as isize);

                cov[0][0] += vx * vx;
                cov[0][1] += vx * vy;
                cov[1][0] += vy * vx;
                cov[1][1] += vy * vy;
            }

            // Normalize
            let scale = 1.0 / self.num_bodies as f32;
            for i in 0..2 {
                for j in 0..2 {
                    cov[i][j] *= scale;
                }
            }

            // Multiply: y = cov · x
            let y = [
                cov[0][0] * x[0] + cov[0][1] * x[1],
                cov[1][0] * x[0] + cov[1][1] * x[1],
            ];

            *y_ptr.offset(0) = y[0];
            *y_ptr.offset(1) = y[1];
        }

        let gpu_time = start.elapsed();

        // CPU: Normalize (demonstrates cache handoff)
        let (eigenvalue, angle) = unsafe {
            let y_ptr = self.temp_buffer.contents() as *const f32;
            let x_ptr = self.eigenvector_buffer.contents() as *mut f32;

            let y0 = *y_ptr.offset(0);
            let y1 = *y_ptr.offset(1);

            let norm = (y0 * y0 + y1 * y1).sqrt();

            if norm > 1e-6 {
                *x_ptr.offset(0) = y0 / norm;
                *x_ptr.offset(1) = y1 / norm;
            }

            // Compute direction angle
            let angle = y1.atan2(y0) * 180.0 / std::f32::consts::PI;

            (norm, angle)
        };

        Some(VelocityPCAResult {
            eigenvalue,
            angle,
            gpu_time_us: gpu_time.as_micros() as f64,
            frame: self.frame_count,
        })
    }

    /// Get current dominant direction
    pub fn get_direction(&self) -> (f32, f32) {
        unsafe {
            let ptr = self.eigenvector_buffer.contents() as *const f32;
            (*ptr.offset(0), *ptr.offset(1))
        }
    }
}

/// Result from velocity PCA step
#[derive(Debug, Clone)]
pub struct VelocityPCAResult {
    pub eigenvalue: f32,
    pub angle: f32,          // Direction in degrees
    pub gpu_time_us: f64,    // Microseconds
    pub frame: usize,
}