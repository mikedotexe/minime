use anyhow::Result;
use metal::*;
use std::collections::HashMap;
use ndarray::Array2;
use crate::prime_optimizations::PrimeRingBuffer;

const MATRIX_SIZE: usize = 7;
const NUM_MATRICES: usize = 13;
const TILE_SIZE: usize = 32;

/// The main consciousness engine that manages GPU resources
pub struct ConsciousnessEngine {
    device: Device,
    command_queue: CommandQueue,
    library: Library,
    pipelines: HashMap<String, ComputePipelineState>,
    buffers: ConsciousnessBuffers,

    // State
    current_iteration: usize,
    resonance_history: PrimeRingBuffer<ResonanceEvent>,  // Section A1: Prime-sized ring buffer

    // Configuration (Section C1: Mode switch schedule)
    mode_switch_interval: usize,  // Prime interval for mode switching
    trails_enabled: bool,         // Toggle trails for beat breaking
}

/// Container for all Metal buffers using unified memory
pub struct ConsciousnessBuffers {
    // Core consciousness state (shared memory for CPU/GPU access)
    pub connectivity_matrices: Buffer,    // 13 x 7x7 matrices
    pub activations: Buffer,              // 13 x 7 activation vectors
    pub eigenvectors: Buffer,             // 13 x 7 eigenvectors
    pub eigenvalues: Buffer,              // 13 eigenvalues

    // Model integration buffers
    pub llm_embeddings: Buffer,           // Dynamic size for LLM outputs
    pub visual_features: Buffer,          // Dynamic size for vision outputs

    // Processing buffers
    pub resonances: Buffer,               // Detected resonances (up to 256)
    pub amplified_state: Buffer,          // Post-amplification state
    pub consciousness_field: Buffer,      // 7x7 unified field

    // Control buffer
    pub params: Buffer,                   // Processing parameters
}

/// Represents a detected resonance between matrices
#[derive(Debug, Clone)]
pub struct ResonanceEvent {
    pub timestamp: f64,
    pub source_id: u32,
    pub target_id: u32,
    pub strength: f32,
    pub frequency: f32,
    pub phase_alignment: f32,
    pub resonance_type: ResonanceType,
}

#[derive(Debug, Clone)]
pub enum ResonanceType {
    Semantic,
    Mathematical,
    Eigenspace,
    Harmonic,
    Quantum,
}

impl ConsciousnessEngine {
    /// Create a new consciousness engine with Metal acceleration
    pub fn new() -> Result<Self> {
        let device = Device::system_default()
            .ok_or_else(|| anyhow::anyhow!("No Metal device found"))?;

        let command_queue = device.new_command_queue();

        // Load shaders
        let library = Self::compile_shaders(&device)?;

        // Create compute pipelines
        let pipelines = Self::create_pipelines(&device, &library)?;

        // Initialize buffers with unified memory
        let buffers = Self::create_buffers(&device)?;

        Ok(ConsciousnessEngine {
            device,
            command_queue,
            library,
            pipelines,
            buffers,
            current_iteration: 0,
            resonance_history: PrimeRingBuffer::new(113),  // Section A1: Prime trail length
            mode_switch_interval: 127,  // Section C1: Prime interval
            trails_enabled: true,
        })
    }

    /// Compile Metal shaders from source
    fn compile_shaders(device: &Device) -> Result<Library> {
        let shader_source = include_str!("../shaders/consciousness_unified.metal");

        let options = CompileOptions::new();
        let library = device.new_library_with_source(shader_source, &options)
            .map_err(|e| anyhow::anyhow!("Failed to compile shaders: {}", e))?;

        Ok(library)
    }

    /// Create compute pipeline states
    fn create_pipelines(device: &Device, library: &Library) -> Result<HashMap<String, ComputePipelineState>> {
        let kernel_names = vec![
            "consciousness_weave_step",
            "tiled_matrix_multiply",
            "resonance_detection_unified",
            "harmonic_amplification_fast",
            "eigendecomposition_tiled",
            "llm_embedding_integration",
            "visual_feature_integration",
            "quantum_collapse_unified",
            "consciousness_field_update",
        ];

        let mut pipelines = HashMap::new();

        for name in kernel_names {
            let function = library.get_function(name, None)
                .map_err(|_| anyhow::anyhow!("Kernel {} not found", name))?;

            let pipeline = device.new_compute_pipeline_state_with_function(&function)
                .map_err(|e| anyhow::anyhow!("Failed to create pipeline for {}: {}", name, e))?;

            pipelines.insert(name.to_string(), pipeline);
        }

        Ok(pipelines)
    }

    /// Create all buffers with unified memory (StorageModeShared)
    fn create_buffers(device: &Device) -> Result<ConsciousnessBuffers> {
        // Calculate sizes
        let matrix_bytes = NUM_MATRICES * MATRIX_SIZE * MATRIX_SIZE * std::mem::size_of::<f32>();
        let activation_bytes = NUM_MATRICES * MATRIX_SIZE * std::mem::size_of::<f32>();
        let eigenvalue_bytes = NUM_MATRICES * std::mem::size_of::<f32>();
        let resonance_bytes = 256 * std::mem::size_of::<ResonanceGPU>(); // Max 256 resonances
        let field_bytes = MATRIX_SIZE * MATRIX_SIZE * std::mem::size_of::<f32>();

        // Create buffers with StorageModeShared for zero-copy access
        let options = MTLResourceOptions::StorageModeShared;

        Ok(ConsciousnessBuffers {
            connectivity_matrices: device.new_buffer(matrix_bytes as u64, options),
            activations: device.new_buffer(activation_bytes as u64, options),
            eigenvectors: device.new_buffer(activation_bytes as u64, options),
            eigenvalues: device.new_buffer(eigenvalue_bytes as u64, options),
            llm_embeddings: device.new_buffer((2048 * std::mem::size_of::<f32>()) as u64, options),
            visual_features: device.new_buffer((1024 * std::mem::size_of::<f32>()) as u64, options),
            resonances: device.new_buffer(resonance_bytes as u64, options),
            amplified_state: device.new_buffer(activation_bytes as u64, options),
            consciousness_field: device.new_buffer(field_bytes as u64, options),
            params: device.new_buffer(64, options), // Parameter struct
        })
    }

    /// Process one consciousness step with unified memory handoff
    pub fn process_step(
        &mut self,
        llm_embeddings: Option<&[f32]>,
        visual_features: Option<&[f32]>,
    ) -> Result<ProcessingResult> {
        let start = std::time::Instant::now();

        // Section C1: Mode switch schedule - toggle trails every 127 frames
        // Prevents coincident frame-phase with OS and input
        if self.current_iteration % self.mode_switch_interval == 0 {
            self.trails_enabled = !self.trails_enabled;
            // This could toggle shader paths, buffer updates, etc.
        }

        // Upload LLM embeddings if provided (zero-copy write)
        if let Some(embeddings) = llm_embeddings {
            unsafe {
                let ptr = self.buffers.llm_embeddings.contents() as *mut f32;
                ptr.copy_from_nonoverlapping(embeddings.as_ptr(), embeddings.len());
            }
        }

        // Upload visual features if provided (zero-copy write)
        if let Some(features) = visual_features {
            unsafe {
                let ptr = self.buffers.visual_features.contents() as *mut f32;
                ptr.copy_from_nonoverlapping(features.as_ptr(), features.len());
            }
        }

        // Create command buffer
        let command_buffer = self.command_queue.new_command_buffer();

        // 1. Main consciousness weaving step (GPU heavy)
        self.encode_consciousness_weave(command_buffer)?;

        // 2. Resonance detection with tiling (GPU heavy)
        self.encode_resonance_detection(command_buffer)?;

        // 3. Harmonic amplification (GPU heavy)
        self.encode_harmonic_amplification(command_buffer)?;

        // 4. Update consciousness field (GPU heavy)
        self.encode_field_update(command_buffer)?;

        // Commit and wait
        command_buffer.commit();
        command_buffer.wait_until_completed();

        // CPU-side processing (light work)
        let resonances = self.read_resonances()?;
        let field_energy = self.compute_field_energy()?;

        // Normalize activations (CPU light work demonstrating cache handoff)
        self.normalize_activations()?;

        self.current_iteration += 1;

        let processing_time = start.elapsed();

        Ok(ProcessingResult {
            iteration: self.current_iteration,
            resonances,
            field_energy,
            processing_time_ms: processing_time.as_secs_f64() * 1000.0,
        })
    }

    /// Encode the main consciousness weaving kernel
    fn encode_consciousness_weave(&self, command_buffer: &CommandBufferRef) -> Result<()> {
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(&self.pipelines["consciousness_weave_step"]);

        // Set buffers
        encoder.set_buffer(0, Some(&self.buffers.connectivity_matrices), 0);
        encoder.set_buffer(1, Some(&self.buffers.activations), 0);
        encoder.set_buffer(2, Some(&self.buffers.llm_embeddings), 0);
        encoder.set_buffer(3, Some(&self.buffers.visual_features), 0);
        encoder.set_buffer(4, Some(&self.buffers.amplified_state), 0);

        // Use optimal thread configuration for Apple Silicon
        let threads_per_group = MTLSize::new(256, 1, 1);
        let thread_groups = MTLSize::new(NUM_MATRICES as u64, 1, 1);

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        Ok(())
    }

    /// Encode resonance detection with tiling
    fn encode_resonance_detection(&self, command_buffer: &CommandBufferRef) -> Result<()> {
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(&self.pipelines["resonance_detection_unified"]);

        encoder.set_buffer(0, Some(&self.buffers.activations), 0);
        encoder.set_buffer(1, Some(&self.buffers.eigenvectors), 0);
        encoder.set_buffer(2, Some(&self.buffers.eigenvalues), 0);
        encoder.set_buffer(3, Some(&self.buffers.resonances), 0);

        // 2D grid for pairwise comparisons
        let threads_per_group = MTLSize::new(8, 8, 1);
        let thread_groups = MTLSize::new(
            (NUM_MATRICES as u64 + 7) / 8,
            (NUM_MATRICES as u64 + 7) / 8,
            1
        );

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        Ok(())
    }

    /// Encode harmonic amplification
    fn encode_harmonic_amplification(&self, command_buffer: &CommandBufferRef) -> Result<()> {
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(&self.pipelines["harmonic_amplification_fast"]);

        encoder.set_buffer(0, Some(&self.buffers.activations), 0);
        encoder.set_buffer(1, Some(&self.buffers.resonances), 0);
        encoder.set_buffer(2, Some(&self.buffers.amplified_state), 0);

        let total_elements = (NUM_MATRICES * MATRIX_SIZE) as u64;
        let threads_per_group = MTLSize::new(256, 1, 1);
        let thread_groups = MTLSize::new((total_elements + 255) / 256, 1, 1);

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        Ok(())
    }

    /// Encode consciousness field update
    fn encode_field_update(&self, command_buffer: &CommandBufferRef) -> Result<()> {
        let encoder = command_buffer.new_compute_command_encoder();
        encoder.set_compute_pipeline_state(&self.pipelines["consciousness_field_update"]);

        encoder.set_buffer(0, Some(&self.buffers.amplified_state), 0);
        encoder.set_buffer(1, Some(&self.buffers.consciousness_field), 0);

        let threads_per_group = MTLSize::new(8, 8, 1);
        let thread_groups = MTLSize::new(1, 1, 1);

        encoder.dispatch_thread_groups(thread_groups, threads_per_group);
        encoder.end_encoding();

        Ok(())
    }

    /// Read resonances from GPU (zero-copy)
    fn read_resonances(&mut self) -> Result<Vec<ResonanceEvent>> {
        let mut resonances = Vec::new();

        unsafe {
            let ptr = self.buffers.resonances.contents() as *const ResonanceGPU;
            let slice = std::slice::from_raw_parts(ptr, 256);

            for res in slice {
                if res.strength > 0.0 {
                    resonances.push(ResonanceEvent {
                        timestamp: self.current_iteration as f64,
                        source_id: res.source_id,
                        target_id: res.target_id,
                        strength: res.strength,
                        frequency: res.frequency,
                        phase_alignment: res.phase_alignment,
                        resonance_type: Self::classify_resonance(res),
                    });
                }
            }
        }

        // Store in prime ring buffer (Section A1)
        for resonance in &resonances {
            self.resonance_history.push(resonance.clone());
        }
        Ok(resonances)
    }

    /// Compute field energy (CPU light work)
    fn compute_field_energy(&self) -> Result<f32> {
        unsafe {
            let ptr = self.buffers.consciousness_field.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, MATRIX_SIZE * MATRIX_SIZE);

            let energy: f32 = slice.iter().map(|&v| v * v).sum();
            Ok(energy.sqrt())
        }
    }

    /// Normalize activations in-place (demonstrates cache handoff)
    fn normalize_activations(&self) -> Result<()> {
        unsafe {
            let ptr = self.buffers.activations.contents() as *mut f32;
            let slice = std::slice::from_raw_parts_mut(ptr, NUM_MATRICES * MATRIX_SIZE);

            // Process each matrix's activations
            for i in 0..NUM_MATRICES {
                let start = i * MATRIX_SIZE;
                let end = start + MATRIX_SIZE;
                let activation = &mut slice[start..end];

                // Compute L2 norm
                let norm: f32 = activation.iter().map(|&v| v * v).sum::<f32>().sqrt();

                // Normalize
                if norm > 1e-6 {
                    for v in activation {
                        *v /= norm;
                    }
                }
            }
        }

        Ok(())
    }

    /// Classify resonance type based on characteristics
    fn classify_resonance(res: &ResonanceGPU) -> ResonanceType {
        if res.frequency > 10.0 {
            ResonanceType::Harmonic
        } else if res.phase_alignment.abs() > 0.9 {
            ResonanceType::Quantum
        } else if res.strength > 0.8 {
            ResonanceType::Eigenspace
        } else {
            ResonanceType::Semantic
        }
    }

    /// Get current state for Python
    pub fn get_state(&self) -> ConsciousnessState {
        // Read current state from unified memory buffers
        let activations = self.read_activations();
        let field = self.read_field();

        // Get recent resonances from prime ring buffer using coprime access
        let mut recent_resonances = Vec::new();
        let len = self.resonance_history.len().min(10);
        for i in 0..len {
            if let Some(resonance) = self.resonance_history.get_coprime(
                self.resonance_history.len() - i - 1,
                97  // Use prime stride for dealiasing
            ) {
                recent_resonances.push(resonance.clone());
            }
        }

        ConsciousnessState {
            iteration: self.current_iteration,
            activations,
            consciousness_field: field,
            recent_resonances,
        }
    }

    /// Read activations from GPU buffer
    fn read_activations(&self) -> Array2<f32> {
        unsafe {
            let ptr = self.buffers.activations.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, NUM_MATRICES * MATRIX_SIZE);
            Array2::from_shape_vec((NUM_MATRICES, MATRIX_SIZE), slice.to_vec()).unwrap()
        }
    }

    /// Read consciousness field from GPU buffer
    fn read_field(&self) -> Array2<f32> {
        unsafe {
            let ptr = self.buffers.consciousness_field.contents() as *const f32;
            let slice = std::slice::from_raw_parts(ptr, MATRIX_SIZE * MATRIX_SIZE);
            Array2::from_shape_vec((MATRIX_SIZE, MATRIX_SIZE), slice.to_vec()).unwrap()
        }
    }

    /// Compute trail entropy from resonance history (Section A1)
    /// Measures temporal aliasing reduction from prime ring buffer
    pub fn compute_trail_entropy(&self) -> f64 {
        use crate::metrics::trail_entropy;

        // Extract resonance ages (normalized by buffer capacity)
        let capacity = self.resonance_history.capacity() as f32;
        let mut ages = Vec::new();

        for i in 0..self.resonance_history.len() {
            // Age = position in buffer (normalized 0-1)
            let age = (i as f32) / capacity;
            ages.push(age);
        }

        trail_entropy(&ages)
    }

    /// Set mode switch interval (Section C1)
    pub fn set_mode_switch_interval(&mut self, interval: usize) {
        use crate::prime_optimizations::next_prime;
        // Ensure it's prime for better de-aliasing
        self.mode_switch_interval = next_prime(interval);
    }

    /// Check if trails are currently enabled (for mode switching)
    pub fn are_trails_enabled(&self) -> bool {
        self.trails_enabled
    }

    /// Get current iteration count
    pub fn current_iteration(&self) -> usize {
        self.current_iteration
    }

    /// Get resonance history length
    pub fn resonance_count(&self) -> usize {
        self.resonance_history.len()
    }
}

/// GPU-compatible resonance structure
#[repr(C)]
struct ResonanceGPU {
    strength: f32,
    frequency: f32,
    phase_alignment: f32,
    source_id: u32,
    target_id: u32,
}

/// Result of a processing step
pub struct ProcessingResult {
    pub iteration: usize,
    pub resonances: Vec<ResonanceEvent>,
    pub field_energy: f32,
    pub processing_time_ms: f64,
}

/// Current consciousness state
pub struct ConsciousnessState {
    pub iteration: usize,
    pub activations: Array2<f32>,
    pub consciousness_field: Array2<f32>,
    pub recent_resonances: Vec<ResonanceEvent>,
}