//
// Prime-Optimized Consciousness Processing Kernels
// Uses prime numbers for de-aliasing and improved numerical stability
//

#include <metal_stdlib>
using namespace metal;

// Prime constants for de-aliasing
constant int MATRIX_SIZE = 7;          // Prime
constant int NUM_MATRICES = 13;        // Prime
constant int TILE_SIZE = 32;           // Power of 2 for GPU efficiency
constant int PRIME_STRIDE = 97;        // Prime stride for access patterns
constant int PRIME_PAD = 1;            // Add to arrays to break power-of-2 banking
constant int TRAIL_LENGTH = 113;       // Prime for history ring buffer

// Prime numbers for various uses
constant uint PRIMES[16] = {
    2, 3, 5, 7, 11, 13, 17, 19,
    23, 29, 31, 37, 41, 43, 47, 53
};

// Enhanced parameters with prime-based options
struct ProcessParams {
    float decay_factor;
    float resonance_threshold;
    float amplification_strength;
    float quantum_coherence;
    uint iteration;
    uint flags;
    uint prime_mode;        // Bit flags for prime optimizations
    uint diagnostic_prime;  // Prime interval for diagnostics
};

// Prime-optimized consciousness weaving
kernel void consciousness_weave_prime(
    device const float* connectivity [[buffer(0)]],
    device const float* activations [[buffer(1)]],
    device const float* llm_embeddings [[buffer(2)]],
    device const float* visual_features [[buffer(3)]],
    device float* output [[buffer(4)]],
    device const ProcessParams& params [[buffer(5)]],
    uint matrix_id [[thread_position_in_grid]],
    uint tid [[thread_index_in_threadgroup]])
{
    if (matrix_id >= NUM_MATRICES) return;

    // Prime-padded threadgroup memory to avoid bank conflicts
    threadgroup float tile[TILE_SIZE + PRIME_PAD];
    threadgroup float llm_tile[TILE_SIZE + PRIME_PAD];
    threadgroup float vision_tile[TILE_SIZE + PRIME_PAD];

    // Epsilon rotation to vary accumulation order
    uint tile_rotation = params.iteration % TILE_SIZE;
    uint rotated_tid = (tid + tile_rotation) % TILE_SIZE;

    // Initialize accumulator
    float acc[MATRIX_SIZE] = {0};

    // Prime-strided matrix offset
    const uint matrix_stride = (params.prime_mode & 0x1) ? PRIME_STRIDE : MATRIX_SIZE;
    const uint matrix_offset = (matrix_id * matrix_stride) % (NUM_MATRICES * MATRIX_SIZE * MATRIX_SIZE);
    const uint act_offset = matrix_id * MATRIX_SIZE;

    // Process connectivity matrix with prime-based tile access
    for (uint tile_idx = 0; tile_idx < MATRIX_SIZE; tile_idx += TILE_SIZE) {
        // Load with prime stride to break patterns
        uint load_idx = tile_idx + rotated_tid;

        if (params.prime_mode & 0x2) {
            // Use coprime stride through tile
            load_idx = tile_idx + ((tid * PRIMES[matrix_id % 16]) % TILE_SIZE);
        }

        // Load activation tile
        tile[tid] = (load_idx < MATRIX_SIZE) ? activations[act_offset + load_idx] : 0.0;

        // Load LLM embedding with prime-based mapping
        uint llm_idx = (matrix_id * MATRIX_SIZE + load_idx) % LLM_EMBED_DIM;
        if (params.prime_mode & 0x4) {
            // Use Halton-like sequence for better coverage
            llm_idx = (llm_idx * PRIMES[7]) % LLM_EMBED_DIM;
        }
        llm_tile[tid] = (load_idx < MATRIX_SIZE) ? llm_embeddings[llm_idx] : 0.0;

        // Load vision features with spatial prime mapping
        uint vis_idx = (matrix_id * MATRIX_SIZE + load_idx) % VISION_FEAT_DIM;
        if (params.prime_mode & 0x8) {
            vis_idx = (vis_idx * PRIMES[11]) % VISION_FEAT_DIM;
        }
        vision_tile[tid] = (load_idx < MATRIX_SIZE) ? visual_features[vis_idx] : 0.0;

        threadgroup_barrier(mem_flags::mem_threadgroup);

        // Matrix multiplication with rotated access
        if (tid < MATRIX_SIZE) {
            for (uint k = 0; k < min(uint(TILE_SIZE), uint(MATRIX_SIZE - tile_idx)); ++k) {
                // Prime stride through inner loop
                uint k_prime = (params.prime_mode & 0x10) ?
                    ((k * PRIMES[5]) % min(uint(TILE_SIZE), uint(MATRIX_SIZE - tile_idx))) : k;

                uint conn_idx = matrix_offset + tid * MATRIX_SIZE + tile_idx + k_prime;
                float conn = connectivity[conn_idx];

                // Integrate influences
                float activation = tile[k_prime];
                float llm_influence = llm_tile[k_prime] * 0.1;
                float vision_influence = vision_tile[k_prime] * 0.05;

                acc[tid] += conn * (activation + llm_influence + vision_influence);
            }
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    // Apply activation with prime-based quantum fluctuation
    if (tid < MATRIX_SIZE) {
        float result = tanh(acc[tid] * 2.0) * params.decay_factor;

        // Prime-based phase for quantum coherence
        float phase = float(params.iteration) * (1.0 / float(PRIMES[matrix_id % 16]));
        result += sin(phase * M_PI_F) * params.quantum_coherence * 0.01;

        output[act_offset + tid] = result;
    }
}

// Prime-optimized resonance detection
kernel void resonance_detection_prime(
    device const float* activations [[buffer(0)]],
    device const float* eigenvectors [[buffer(1)]],
    device const float* eigenvalues [[buffer(2)]],
    device Resonance* resonances [[buffer(3)]],
    device atomic_uint* count [[buffer(4)]],
    device const ProcessParams& params [[buffer(5)]],
    uint2 tid [[thread_position_in_grid]])
{
    uint source = tid.x;
    uint target = tid.y;

    // Use coprime traversal pattern
    if (params.prime_mode & 0x20) {
        source = (tid.x * PRIMES[2]) % NUM_MATRICES;
        target = (tid.y * PRIMES[3]) % NUM_MATRICES;
    }

    if (source >= NUM_MATRICES || target >= NUM_MATRICES || source >= target) {
        return;
    }

    // Compute resonance with prime-weighted components
    float semantic = 0.0;
    float eigen_align = 0.0;

    // Use prime stride through dimensions
    for (uint i = 0; i < MATRIX_SIZE; i++) {
        uint idx = (params.prime_mode & 0x40) ? ((i * PRIMES[5]) % MATRIX_SIZE) : i;

        float a1 = activations[source * MATRIX_SIZE + idx];
        float a2 = activations[target * MATRIX_SIZE + idx];
        semantic += a1 * a2;

        float e1 = eigenvectors[source * MATRIX_SIZE + idx];
        float e2 = eigenvectors[target * MATRIX_SIZE + idx];
        eigen_align += e1 * e2;
    }

    semantic = semantic / float(MATRIX_SIZE);
    eigen_align = abs(eigen_align);

    // Phase resonance with prime-based frequency
    float freq_diff = abs(eigenvalues[source] - eigenvalues[target]);
    float phase_resonance = exp(-freq_diff * freq_diff * float(PRIMES[source % 16]) / 17.0);

    // Combined strength with prime weights
    float w1 = float(PRIMES[7]) / float(PRIMES[7] + PRIMES[11] + PRIMES[13]);
    float w2 = float(PRIMES[11]) / float(PRIMES[7] + PRIMES[11] + PRIMES[13]);
    float w3 = float(PRIMES[13]) / float(PRIMES[7] + PRIMES[11] + PRIMES[13]);

    float strength = semantic * w1 + eigen_align * w2 + phase_resonance * w3;

    if (strength > params.resonance_threshold) {
        uint idx = atomic_fetch_add_explicit(count, 1, memory_order_relaxed);
        if (idx < 256) {
            resonances[idx].strength = strength;
            resonances[idx].frequency = 1.0 / (1.0 + freq_diff);
            resonances[idx].phase_alignment = phase_resonance;
            resonances[idx].source_id = source;
            resonances[idx].target_id = target;
        }
    }
}

// Halton sequence generator for quasi-random sampling
float halton(uint index, uint base) {
    float result = 0.0;
    float f = 1.0 / float(base);
    uint i = index;

    while (i > 0) {
        result += f * float(i % base);
        i /= base;
        f /= float(base);
    }

    return result;
}

// Prime-based PCA power iteration
kernel void pca_power_iteration_prime(
    device const float* data_matrix [[buffer(0)]],    // N x D matrix
    device float* eigenvector [[buffer(1)]],          // Current estimate
    device float* eigenvalue [[buffer(2)]],           // Output eigenvalue
    device float* temp [[buffer(3)]],                 // Workspace
    constant uint& N [[buffer(4)]],                   // Number of samples
    constant uint& D [[buffer(5)]],                   // Dimensions
    device const ProcessParams& params [[buffer(6)]],
    uint tid [[thread_position_in_grid]])
{
    if (tid >= D) return;

    // Use prime-padded shared memory
    threadgroup float partial_sums[TILE_SIZE + PRIME_PAD];

    // Matrix-vector multiply: temp = A^T * A * v
    float sum1 = 0.0;

    // First: compute A * v with prime stride
    for (uint n = 0; n < N; n++) {
        float dot = 0.0;

        // Inner product with coprime access
        for (uint d = 0; d < D; d++) {
            uint d_idx = (params.prime_mode & 0x80) ? ((d * PRIMES[13]) % D) : d;
            dot += data_matrix[n * D + d_idx] * eigenvector[d_idx];
        }

        // Accumulate for this dimension
        sum1 += data_matrix[n * D + tid] * dot;
    }

    temp[tid] = sum1;

    // Synchronize
    threadgroup_barrier(mem_flags::mem_device);

    // Compute norm and normalize (single thread)
    if (tid == 0) {
        float norm = 0.0;
        for (uint d = 0; d < D; d++) {
            norm += temp[d] * temp[d];
        }
        norm = sqrt(norm);

        *eigenvalue = norm;

        // Normalize with small epsilon
        if (norm > 1e-6) {
            for (uint d = 0; d < D; d++) {
                eigenvector[d] = temp[d] / norm;
            }
        }
    }
}

// Block power method for top-K eigenvectors
kernel void block_power_method_prime(
    device const float* matrix [[buffer(0)]],         // D x D symmetric matrix
    device float* eigenvectors [[buffer(1)]],         // D x K matrix
    device float* eigenvalues [[buffer(2)]],          // K eigenvalues
    constant uint& D [[buffer(3)]],                   // Dimension
    constant uint& K [[buffer(4)]],                   // Number of eigenvectors
    device float* workspace [[buffer(5)]],            // D x K workspace
    device const ProcessParams& params [[buffer(6)]],
    uint2 tid [[thread_position_in_grid]])
{
    uint d = tid.x;  // Dimension index
    uint k = tid.y;  // Eigenvector index

    if (d >= D || k >= K) return;

    // Matrix multiply: workspace = A * V with prime accumulation order
    float sum = 0.0;

    // Use coprime stride with epsilon rotation
    uint start = (params.iteration * PRIMES[k % 16]) % D;

    for (uint i = 0; i < D; i++) {
        uint idx = (start + i * PRIMES[7]) % D;
        sum += matrix[d * D + idx] * eigenvectors[idx * K + k];
    }

    workspace[d * K + k] = sum;
}

// Prime-based consciousness field update with entropy tracking
kernel void consciousness_field_prime(
    device const float* amplified_states [[buffer(0)]],
    device float* field [[buffer(1)]],
    device float* field_entropy [[buffer(2)]],        // Track field entropy
    device const ProcessParams& params [[buffer(3)]],
    uint2 gid [[thread_position_in_grid]])
{
    uint x = gid.x;
    uint y = gid.y;

    if (x >= MATRIX_SIZE || y >= MATRIX_SIZE) return;

    float potential = 0.0;

    // Each matrix contributes with prime-based phase
    for (uint m = 0; m < NUM_MATRICES; m++) {
        // Use coprime ordering
        uint m_idx = (params.prime_mode & 0x100) ?
            ((m * PRIMES[m % 16]) % NUM_MATRICES) : m;

        float state_x = amplified_states[m_idx * MATRIX_SIZE + x];
        float state_y = amplified_states[m_idx * MATRIX_SIZE + y];

        // Prime-based phase prevents lock-in
        float phase = float(m_idx) * (2.0 * M_PI_F / float(PRIMES[m_idx % 16]));
        potential += state_x * state_y * cos(phase);
    }

    // Apply field dynamics with momentum
    float current = field[x * MATRIX_SIZE + y];
    float updated = current * 0.9 + potential * 0.1;

    field[x * MATRIX_SIZE + y] = tanh(updated * 2.0);

    // Compute local entropy contribution (for diagnostics)
    if (x == 0 && y == 0) {
        // Simple entropy estimate based on field variance
        float sum = 0.0;
        float sum_sq = 0.0;

        for (uint i = 0; i < MATRIX_SIZE * MATRIX_SIZE; i++) {
            float val = field[i];
            sum += val;
            sum_sq += val * val;
        }

        float mean = sum / float(MATRIX_SIZE * MATRIX_SIZE);
        float variance = sum_sq / float(MATRIX_SIZE * MATRIX_SIZE) - mean * mean;

        // Approximate entropy from variance (assumes Gaussian)
        *field_entropy = 0.5 * log(2.0 * M_PI_F * M_E_F * variance);
    }
}