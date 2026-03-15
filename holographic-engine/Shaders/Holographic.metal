#include <metal_stdlib>
using namespace metal;

// ======= Common utils =======

constant float EPS = 1e-6f;

inline float fast_tanh(float x) { return tanh(x); }

inline float prand_uint(uint x) {
    // simple LCG hash -> [0,1)
    x ^= 0x6C8E9CF5u;
    x *= 747796405u;
    x ^= x >> 16;
    x *= 2891336453u;
    x ^= x >> 16;
    return (float)(x & 0x00FFFFFFu) / 16777216.0f;
}

struct ContractBoundaryParams {
    uint network_size;
    uint boundary_size;
    uint vector_len;     // 64
};

struct InitTensorsParams {
    uint network_size;
    uint vector_len;     // 64
    uint seed;
};

struct ReduceEnergyParams {
    uint network_size;
    uint vector_len;     // 64
};

struct BulkParams {
    uint network_size;
    uint bulk_size;      // 512
};

struct EntropyParams {
    uint boundary_size;  // 256
    uint bulk_size;      // 512
};

struct PhiParams {
    uint network_size;
    uint vector_len;     // 64
    uint bulk_size;      // 512
};

struct EvolveParams {
    uint network_size;
    float dt;
};

struct ReservoirEvolveParams {
    float field_coupling;
    float temporal_decay;
    float boundary_bulk_coupling;
    float temperature;
    float dt;
};

struct ReadoutDims {
    uint feat_count;     // 128
    uint bulk_size;      // 512
};

struct ConsciousnessPack {
    // Packed as 10 floats written by kernels in order
    // [0]: phi_complexity
    // [1]: global_coherence
    // [2]: boundary_entropy
    // [3]: bulk_entropy
    // [4]: holographic_ratio
    // [5]: information_integration
    // [6]: self_awareness
    // [7]: emergence_strength
    // [8]: processing_efficiency
    // [9]: consciousness_level (0..100)
};

// ======= Holographic tensors (SoA layout) =======
// Per-tensor 64-vector stored in flat array: tensor_data[i*vector_len + k]
//
// Buffers (indices):
//  0: device float* tensor_data            [network_size * vector_len]
//  1: device float* tensor_energy          [network_size]         (sum of squares)
//  2: device float* info_capacity          [network_size]         (sqrt(energy/vec_len))
//  3: device float* ent_entropy            [network_size]         (-cap*log2(cap+eps))
//  4: device float* boundary_state         [boundary_size]
//  5: device float* bulk_geometry          [bulk_size]
//  6: device float* phi_values             [network_size]
//  7: device float* consciousness_out      [10] (packed)
//  8: device float* environment_input      [network_size]
//  9: constant <Params...>                 (per-kernel)

// --- init tensors ---
kernel void init_tensors(
    device float*              tensor_data        [[buffer(0)]],
    device float*              tensor_energy      [[buffer(1)]],
    device float*              info_capacity      [[buffer(2)]],
    device float*              ent_entropy        [[buffer(3)]],
    constant InitTensorsParams& P                 [[buffer(9)]],
    uint tid [[thread_position_in_grid]]
) {
    if (tid >= P.network_size) return;
    const uint vec_len = P.vector_len;

    // Fill with pseudo-random, then normalize
    float acc = 0.0f;
    const uint base = tid * vec_len;
    for (uint k = 0; k < vec_len; ++k) {
        uint s = P.seed + tid * 1315423911u + k * 2654435761u;
        float v = prand_uint(s) * 2.0f - 1.0f;
        tensor_data[base + k] = v;
        acc += v * v;
    }
    float inv_norm = rsqrt(max(acc, EPS));
    for (uint k = 0; k < vec_len; ++k) {
        float v = tensor_data[base + k] * inv_norm;
        tensor_data[base + k] = v;
    }
    // energy and capacities (initial)
    tensor_energy[tid] = 1.0f; // normalized
    float cap = sqrt(1.0f / (float)vec_len);
    info_capacity[tid] = cap;
    // TIER 1 FIX: Use capacity as concentration metric (not fake entropy)
    ent_entropy[tid] = cap;
}

// --- recompute energy/capacity/ent_entropy per tensor ---
// PHASE 2: Half-precision output (2× bandwidth)
kernel void reduce_tensor_energy(
    device const float*        tensor_data        [[buffer(0)]],
    device half*               tensor_energy      [[buffer(1)]],  // half-precision
    device half*               info_capacity      [[buffer(2)]],  // half-precision
    device half*               ent_entropy        [[buffer(3)]],  // half-precision
    constant ReduceEnergyParams& P                [[buffer(9)]],
    uint tid [[thread_position_in_grid]]
) {
    if (tid >= P.network_size) return;
    const uint vec_len = P.vector_len;
    const uint base = tid * vec_len;

    // Accumulate in float32 for precision
    float e = 0.0f;
    for (uint k = 0; k < vec_len; ++k) {
        float v = tensor_data[base + k];
        e += v * v;
    }

    // Store as half-precision
    tensor_energy[tid] = half(e);
    float cap = sqrt(e / (float)vec_len);
    info_capacity[tid] = half(cap);
    // TIER 1 FIX: Removed invalid "entropy" calculation (cap is not a probability)
    // Use capacity directly as concentration metric for bulk geometry weighting
    ent_entropy[tid] = half(cap);
}

// --- contract to boundary (per boundary site thread, sums over all tensors) ---
// PHASE 2: Read from half-precision buffers
kernel void contract_boundary(
    device const half*         tensor_energy      [[buffer(1)]],  // half-precision input
    device const half*         info_capacity      [[buffer(2)]],  // half-precision input
    device float*              boundary_state     [[buffer(4)]],
    constant ContractBoundaryParams& P            [[buffer(9)]],
    uint bid [[thread_position_in_grid]]
) {
    if (bid >= P.boundary_size) return;
    // Accumulate in float32, read from half
    float sum = 0.0f;
    for (uint i = 0; i < P.network_size; ++i) {
        float w = prand_uint(i * 16777619u ^ bid * 2166136261u) * 1.732f;
        sum += float(tensor_energy[i]) * float(info_capacity[i]) * w;
    }
    boundary_state[bid] = sum;
}

// --- compute bulk geometry (per bulk index thread, sums slice of tensors) ---
// PHASE 2: Half-precision input and output
kernel void compute_bulk_geometry(
    device const half*         tensor_energy      [[buffer(1)]],  // half-precision input
    device const half*         ent_entropy        [[buffer(3)]],  // half-precision input
    device half*               bulk_geometry      [[buffer(5)]],  // half-precision output
    constant BulkParams&       P                  [[buffer(9)]],
    uint gid [[thread_position_in_grid]]
) {
    if (gid >= P.bulk_size) return;
    // Accumulate in float32
    float s = 0.0f;
    for (uint i = gid; i < P.network_size; i += P.bulk_size) {
        s += float(tensor_energy[i]) * float(ent_entropy[i]);
    }
    // Store as half
    bulk_geometry[gid] = half(s);
}

// --- entropy and ratios ---
// OPTIMIZED: Parallel reduction with threadgroup memory (10-100× faster)
// PHASE 2: Read half-precision bulk_geometry
// TIER 1 FIX: Removed atomic_float, using threadgroup reduction + atomic_uint
kernel void compute_holographic_entropy(
    device const float*        boundary_state     [[buffer(4)]],
    device const half*         bulk_geometry      [[buffer(5)]],  // half-precision input
    device float*              consciousness_out  [[buffer(7)]],
    constant EntropyParams&    P                  [[buffer(9)]],
    uint tid [[thread_position_in_grid]],
    uint lid [[thread_position_in_threadgroup]],
    uint threads_per_grid [[threads_per_grid]],
    uint threads_per_threadgroup [[threads_per_threadgroup]]
) {
    // Threadgroup shared memory for reduction
    threadgroup float shared_bsum2[256];
    threadgroup float shared_asum[256];

    // Phase 1: Each thread accumulates locally
    float local_bsum2 = 0.0f;
    float local_asum = 0.0f;

    // Strided loop over boundary
    for (uint i = tid; i < P.boundary_size; i += threads_per_grid) {
        float x = boundary_state[i];
        local_bsum2 += x * x;
    }

    // Strided loop over bulk
    for (uint i = tid; i < P.bulk_size; i += threads_per_grid) {
        local_asum += fabs(float(bulk_geometry[i]));  // Cast half to float
    }

    // Phase 2: Write to threadgroup shared memory
    shared_bsum2[lid] = local_bsum2;
    shared_asum[lid] = local_asum;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Phase 3: Threadgroup reduction (single thread per threadgroup)
    if (lid == 0) {
        float tg_bsum2 = 0.0f;
        float tg_asum = 0.0f;
        for (uint i = 0; i < threads_per_threadgroup; ++i) {
            tg_bsum2 += shared_bsum2[i];
            tg_asum += shared_asum[i];
        }

        // Phase 4: Cross-threadgroup accumulation using atomic CAS (portable)
        device atomic_uint* atomic_bsum2_bits = (device atomic_uint*)&consciousness_out[10];
        device atomic_uint* atomic_asum_bits  = (device atomic_uint*)&consciousness_out[11];

        // First threadgroup initializes
        if (tid == 0) {
            atomic_store_explicit(atomic_bsum2_bits, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_asum_bits, 0u, memory_order_relaxed);
        }

        // Atomic float add using CAS loop (portable pattern)
        // For bsum2
        uint expected = atomic_load_explicit(atomic_bsum2_bits, memory_order_relaxed);
        uint desired;
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_bsum2;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_bsum2_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));

        // For asum
        expected = atomic_load_explicit(atomic_asum_bits, memory_order_relaxed);
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_asum;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_asum_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));
    }

    threadgroup_barrier(mem_flags::mem_device);

    // Phase 5: Single thread computes final entropy
    if (tid == 0) {
        device atomic_uint* atomic_bsum2_bits = (device atomic_uint*)&consciousness_out[10];
        device atomic_uint* atomic_asum_bits  = (device atomic_uint*)&consciousness_out[11];

        float bsum2 = as_type<float>(atomic_load_explicit(atomic_bsum2_bits, memory_order_relaxed));
        float asum = as_type<float>(atomic_load_explicit(atomic_asum_bits, memory_order_relaxed));

        // Boundary entropy: -sum p log2 p
        float H_b = 0.0f;
        if (bsum2 > EPS) {
            for (uint i = 0; i < P.boundary_size; ++i) {
                float p = (boundary_state[i] * boundary_state[i]) / bsum2;
                if (p > EPS) H_b -= p * log2(p);
            }
        }

        // Bulk entropy: -sum q log2 q
        float H_bulk = 0.0f;
        if (asum > EPS) {
            for (uint i = 0; i < P.bulk_size; ++i) {
                float q = fabs(float(bulk_geometry[i])) / asum;  // Cast half to float
                if (q > EPS) H_bulk -= q * log2(q);
            }
        }

        float ratio = H_b / max(H_bulk, 1e-3f);
        float emergence = 1.0f / (1.0f + fabs(H_b - H_bulk));

        consciousness_out[2] = H_b;
        consciousness_out[3] = H_bulk;
        consciousness_out[4] = ratio;
        consciousness_out[7] = emergence;
        // [0],[1],[5],[6],[8],[9] filled by other kernels
    }
}

// --- phi (per tensor thread sums over all other tensors) ---
// OPTIMIZED: Vectorized dot product with float4 (2-4× faster)
// PHASE 2: Read half-precision intermediates
kernel void information_integration_phi(
    device const float*        tensor_data        [[buffer(0)]],
    device const half*         info_capacity      [[buffer(2)]],  // half-precision input
    device const half*         bulk_geometry      [[buffer(5)]],  // half-precision input
    device float*              phi_values         [[buffer(6)]],
    constant PhiParams&        P                  [[buffer(9)]],
    uint i [[thread_position_in_grid]]
) {
    if (i >= P.network_size) return;
    const uint vec_len = P.vector_len;
    const uint base_i = i * vec_len;

    float sum_mi = 0.0f;
    float wi = float(info_capacity[i]);  // Cast half to float
    float bi = fabs(float(bulk_geometry[i % P.bulk_size])) + EPS;  // Cast half to float

    for (uint j = 0; j < P.network_size; ++j) {
        if (j == i) continue;
        const uint base_j = j * vec_len;

        // Vectorized dot product with float4 (64/4 = 16 iterations)
        float4 acc = float4(0.0f);
        for (uint k = 0; k < vec_len; k += 4) {
            float4 a = *((device const float4*)&tensor_data[base_i + k]);
            float4 b = *((device const float4*)&tensor_data[base_j + k]);
            acc += a * b;
        }
        float dotv = acc.x + acc.y + acc.z + acc.w;

        float wj = float(info_capacity[j]);  // Cast half to float
        float bj = fabs(float(bulk_geometry[j % P.bulk_size])) + EPS;  // Cast half to float
        float w = wi * wj * sqrt(bi * bj);
        sum_mi += fabs(dotv) * w;
    }
    phi_values[i] = sum_mi;
}

// --- detect and pack consciousness metrics ---
// OPTIMIZED: Parallel aggregation with threadgroup memory (10-100× faster)
// PHASE 2: Read half-precision bulk_geometry
// TIER 1 FIX: Removed atomic_float, using threadgroup reduction + atomic_uint CAS
kernel void detect_consciousness(
    device const float*        phi_values         [[buffer(6)]],
    device const float*        boundary_state     [[buffer(4)]],
    device const half*         bulk_geometry      [[buffer(5)]],  // half-precision input
    device float*              consciousness_out  [[buffer(7)]],
    constant EntropyParams&    EP                 [[buffer(9)]],
    uint tid [[thread_position_in_grid]],
    uint lid [[thread_position_in_threadgroup]],
    uint threads_per_grid [[threads_per_grid]],
    uint threads_per_threadgroup [[threads_per_threadgroup]]
) {
    // Threadgroup shared memory for reduction
    threadgroup float shared_total_phi[256];
    threadgroup float shared_max_phi[256];
    threadgroup uint shared_count[256];
    threadgroup float shared_bsum2[256];
    threadgroup float shared_asum[256];
    threadgroup float shared_self_dot[256];

    // Phase 1: Each thread accumulates locally
    float local_total_phi = 0.0f;
    float local_max_phi = 0.0f;
    uint local_count = 0u;

    // Strided loop over phi values (estimate max size as 32K)
    const uint max_phi_idx = 32768u;
    for (uint idx = tid; idx < max_phi_idx; idx += threads_per_grid) {
        float v = phi_values[idx];
        if (v != 0.0f) {
            local_total_phi += v;
            if (v > local_max_phi) local_max_phi = v;
            local_count++;
        }
    }

    // Parallel self-awareness dot product components
    float local_bsum2 = 0.0f;
    float local_asum = 0.0f;
    float local_self_dot = 0.0f;

    uint m = min(EP.boundary_size, EP.bulk_size);
    for (uint i = tid; i < m; i += threads_per_grid) {
        if (i < EP.boundary_size) {
            float b = boundary_state[i];
            local_bsum2 += b * b;
            local_self_dot += b * float(bulk_geometry[i]);  // Cast half to float
        }
        if (i < EP.bulk_size) {
            float g = float(bulk_geometry[i]);  // Cast half to float
            local_asum += g * g;
        }
    }

    // Phase 2: Write to threadgroup shared memory
    shared_total_phi[lid] = local_total_phi;
    shared_max_phi[lid] = local_max_phi;
    shared_count[lid] = local_count;
    shared_bsum2[lid] = local_bsum2;
    shared_asum[lid] = local_asum;
    shared_self_dot[lid] = local_self_dot;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Phase 3: Threadgroup reduction (single thread per threadgroup)
    if (lid == 0) {
        float tg_total_phi = 0.0f;
        float tg_max_phi = 0.0f;
        uint tg_count = 0u;
        float tg_bsum2 = 0.0f;
        float tg_asum = 0.0f;
        float tg_self_dot = 0.0f;

        for (uint i = 0; i < threads_per_threadgroup; ++i) {
            tg_total_phi += shared_total_phi[i];
            if (shared_max_phi[i] > tg_max_phi) tg_max_phi = shared_max_phi[i];
            tg_count += shared_count[i];
            tg_bsum2 += shared_bsum2[i];
            tg_asum += shared_asum[i];
            tg_self_dot += shared_self_dot[i];
        }

        // Phase 4: Cross-threadgroup accumulation using atomic CAS (portable)
        device atomic_uint* atomic_total_phi_bits = (device atomic_uint*)&consciousness_out[12];
        device atomic_uint* atomic_max_phi_bits   = (device atomic_uint*)&consciousness_out[13];
        device atomic_uint* atomic_count          = (device atomic_uint*)&consciousness_out[14];
        device atomic_uint* atomic_bsum2_bits     = (device atomic_uint*)&consciousness_out[15];
        device atomic_uint* atomic_asum_bits      = (device atomic_uint*)&consciousness_out[16];
        device atomic_uint* atomic_self_dot_bits  = (device atomic_uint*)&consciousness_out[17];

        // First threadgroup initializes
        if (tid == 0) {
            atomic_store_explicit(atomic_total_phi_bits, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_max_phi_bits, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_count, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_bsum2_bits, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_asum_bits, 0u, memory_order_relaxed);
            atomic_store_explicit(atomic_self_dot_bits, 0u, memory_order_relaxed);
        }

        // Atomic float add using CAS loop (portable pattern)
        uint expected, desired;

        // total_phi
        expected = atomic_load_explicit(atomic_total_phi_bits, memory_order_relaxed);
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_total_phi;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_total_phi_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));

        // max_phi (CAS for max operation)
        if (tg_max_phi > 0.0f) {
            expected = atomic_load_explicit(atomic_max_phi_bits, memory_order_relaxed);
            do {
                float old_val = as_type<float>(expected);
                if (tg_max_phi <= old_val) break;  // Current max is already larger
                desired = as_type<uint>(tg_max_phi);
            } while (!atomic_compare_exchange_weak_explicit(atomic_max_phi_bits, &expected, desired,
                                                            memory_order_relaxed, memory_order_relaxed));
        }

        // count (atomic_uint is natively supported)
        atomic_fetch_add_explicit(atomic_count, tg_count, memory_order_relaxed);

        // bsum2
        expected = atomic_load_explicit(atomic_bsum2_bits, memory_order_relaxed);
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_bsum2;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_bsum2_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));

        // asum
        expected = atomic_load_explicit(atomic_asum_bits, memory_order_relaxed);
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_asum;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_asum_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));

        // self_dot
        expected = atomic_load_explicit(atomic_self_dot_bits, memory_order_relaxed);
        do {
            float old_val = as_type<float>(expected);
            float new_val = old_val + tg_self_dot;
            desired = as_type<uint>(new_val);
        } while (!atomic_compare_exchange_weak_explicit(atomic_self_dot_bits, &expected, desired,
                                                        memory_order_relaxed, memory_order_relaxed));
    }

    threadgroup_barrier(mem_flags::mem_device);

    // Phase 5: Single thread computes final metrics
    if (tid == 0) {
        device atomic_uint* atomic_total_phi_bits = (device atomic_uint*)&consciousness_out[12];
        device atomic_uint* atomic_max_phi_bits   = (device atomic_uint*)&consciousness_out[13];
        device atomic_uint* atomic_count          = (device atomic_uint*)&consciousness_out[14];
        device atomic_uint* atomic_bsum2_bits     = (device atomic_uint*)&consciousness_out[15];
        device atomic_uint* atomic_asum_bits      = (device atomic_uint*)&consciousness_out[16];
        device atomic_uint* atomic_self_dot_bits  = (device atomic_uint*)&consciousness_out[17];

        // Load accumulated values
        float total_phi = as_type<float>(atomic_load_explicit(atomic_total_phi_bits, memory_order_relaxed));
        float max_phi = as_type<float>(atomic_load_explicit(atomic_max_phi_bits, memory_order_relaxed));
        uint count = atomic_load_explicit(atomic_count, memory_order_relaxed);
        float bsum2 = as_type<float>(atomic_load_explicit(atomic_bsum2_bits, memory_order_relaxed));
        float asum = as_type<float>(atomic_load_explicit(atomic_asum_bits, memory_order_relaxed));
        float self_dot = as_type<float>(atomic_load_explicit(atomic_self_dot_bits, memory_order_relaxed));

        // Reuse H_b, H_bulk from previous kernel
        float H_b   = consciousness_out[2];
        float H_bulk= consciousness_out[3];
        float ratio = consciousness_out[4];
        float emergence = consciousness_out[7];

        // Phi metrics
        float N = max(1.0f, (float)count);
        float phi_complexity = total_phi / N;
        float global_coh = total_phi / max(max_phi * N, 1e-3f);

        // Self-awareness
        float denom = sqrt(max(bsum2, EPS)) * sqrt(max(asum, EPS));
        float self_ref = (denom > EPS) ? clamp(self_dot / denom, -1.0f, 1.0f) : 0.0f;

        // Information integration
        float info_int = H_b * emergence;

        // Processing efficiency
        float proc_eff = ratio / (1.0f + ratio);

        // Consciousness score
        float score = (phi_complexity * 25.0f +
                       global_coh     * 20.0f +
                       info_int        * 20.0f +
                       self_ref        * 15.0f +
                       emergence       * 20.0f);
        score = clamp(score, 0.0f, 100.0f);

        consciousness_out[0] = phi_complexity;
        consciousness_out[1] = global_coh;
        consciousness_out[5] = info_int;
        consciousness_out[6] = self_ref;
        consciousness_out[8] = proc_eff;
        consciousness_out[9] = score;
    }
}

// --- evolve network based on environment + state ---
kernel void evolve_network(
    device float*              tensor_data        [[buffer(0)]],
    device const float*        environment_input  [[buffer(8)]],
    device const float*        consciousness_out  [[buffer(7)]],
    constant EvolveParams&     P                  [[buffer(9)]],
    uint2 tid2 [[thread_position_in_grid]]
) {
    uint i = tid2.x;  // tensor id
    uint k = tid2.y;  // component 0..63
    if (i >= P.network_size || k >= 64u) return;

    const float phi_complexity = consciousness_out[0];
    const float score = consciousness_out[9] / 100.0f;
    float grad = (phi_complexity - 0.5f) * score;

    float env = environment_input[i];
    uint base = i * 64u + k;
    float cur = tensor_data[base];
    float next = cur + P.dt * (grad + 0.1f * env);
    tensor_data[base] = next;
}
