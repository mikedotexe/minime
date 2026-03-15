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

struct ContractParams {
    uint network_size;   // N
    uint boundary_size;  // B
    uint lanes;          // lanes per bin (must be power of two, <= MAX_LANES)
    uint tile_bins;      // bins per threadgroup (<= MAX_TILE_BINS)
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
//  2: device float* boundary_activity      [network_size]         (concentration metric: sqrt(energy/vec_len))
//  3: device float* ent_entropy            [network_size]         (reserved for proper Shannon entropy - future)
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
    device float*              boundary_activity      [[buffer(2)]],
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
    boundary_activity[tid] = cap;
    // TIER 1 FIX: Use capacity as concentration metric (not fake entropy)
    ent_entropy[tid] = cap;
}

// --- recompute energy/capacity/ent_entropy per tensor ---
kernel void reduce_tensor_energy(
    device const float*        tensor_data        [[buffer(0)]],
    device float*              tensor_energy      [[buffer(1)]],
    device float*              boundary_activity      [[buffer(2)]],
    device float*              ent_entropy        [[buffer(3)]],
    constant ReduceEnergyParams& P                [[buffer(9)]],
    uint tid [[thread_position_in_grid]]
) {
    if (tid >= P.network_size) return;
    const uint vec_len = P.vector_len;
    const uint base = tid * vec_len;
    float e = 0.0f;
    for (uint k = 0; k < vec_len; ++k) {
        float v = tensor_data[base + k];
        e += v * v;
    }
    tensor_energy[tid] = e;
    float cap = sqrt(e / (float)vec_len);
    boundary_activity[tid] = cap;
    // TIER 1 FIX: Use capacity as concentration metric (not fake entropy)
    ent_entropy[tid] = cap;
}

// --- contract to boundary (per boundary site thread, sums over all tensors) ---
kernel void contract_boundary(
    device const float*        tensor_energy      [[buffer(1)]],
    device const float*        boundary_activity      [[buffer(2)]],
    device float*              boundary_state     [[buffer(4)]],
    constant ContractBoundaryParams& P            [[buffer(9)]],
    uint bid [[thread_position_in_grid]]
) {
    if (bid >= P.boundary_size) return;
    // Sum_i energy[i] * cap[i] * weight(i,bid)
    float sum = 0.0f;
    for (uint i = 0; i < P.network_size; ++i) {
        float w = prand_uint(i * 16777619u ^ bid * 2166136261u) * 1.732f; // deterministic weight
        sum += tensor_energy[i] * boundary_activity[i] * w;
    }
    boundary_state[bid] = sum;
}

// --- Tiled reduction boundary contraction (deterministic, no atomics) ---
#define MAX_TILE_BINS 128u
#define MAX_LANES     16u

// Accumulate boundary bins by tiled reduction over N.
// For bin j in [tileBase, tileBase+tile_bins):
//   sum_j = Σ_i energy[i] * info[i], where i = j + k*B, k ∈ ℕ (strided by B)
// Work split: each bin gets "lanes" threads; each lane sums every lanes-th stride segment.
// Then reduce lanes in threadgroup memory to bin total. Deterministic, no atomics.
kernel void contract_boundary_tiled(
    device const float* energy        [[buffer(1)]],  // length N
    device const float* info          [[buffer(2)]],  // length N
    device float*       boundary_out  [[buffer(4)]],  // length B
    constant ContractParams& P        [[buffer(9)]],
    uint3  tid   [[thread_position_in_threadgroup]],
    uint3  tptg  [[threads_per_threadgroup]],
    uint3  tgid  [[threadgroup_position_in_grid]]
){
    // Layout: x = bin index within tile, y = lane index within bin
    const uint binLocal   = tid.x;
    const uint lane       = tid.y;
    const uint binsPerTG  = tptg.x;
    const uint lanesPerBin= tptg.y;

    // Ensure launch obeys our bounds
    if (binsPerTG > MAX_TILE_BINS || lanesPerBin > MAX_LANES) { return; }

    const uint tileBase = tgid.x * binsPerTG;
    const uint bin      = tileBase + binLocal;
    if (bin >= P.boundary_size) return;
    if (lane >= P.lanes) return; // only the configured lanes are active

    // Each lane accumulates a strided slice over N
    float sum = 0.0f;
    const uint stride = P.boundary_size * P.lanes; // jump to next segment for same lane
    uint i = bin + lane * P.boundary_size;
    while (i < P.network_size) {
        // contribution model: energy * info (keep it consistent with prior scalar version)
        sum += energy[i] * info[i];
        i += stride;
    }

    // Threadgroup scratch: lanes rows × MAX_TILE_BINS columns
    threadgroup float tg[MAX_TILE_BINS * MAX_LANES];
    const uint idx = lane * MAX_TILE_BINS + binLocal;
    tg[idx] = sum;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Reduce along lane dimension (power-of-two lanes)
    uint s = P.lanes >> 1;
    while (s > 0) {
        if (lane < s) {
            tg[lane * MAX_TILE_BINS + binLocal] += tg[(lane + s) * MAX_TILE_BINS + binLocal];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        s >>= 1;
    }

    if (lane == 0) {
        // Deterministic final write; no need to clear boundary_out beforehand
        boundary_out[bin] = tg[binLocal];
    }
}

// --- Vectorized (float4) tiled boundary contraction ---
// Vectorized per-lane accumulation (float4) over strided segments.
// Each lane sums four segments per loop: i, i+stride, i+2*stride, i+3*stride.
// Tail handles remaining segments (<4). Deterministic, no atomics.
kernel void contract_boundary_tiled_vec4(
    device const float* energy        [[buffer(1)]],
    device const float* info          [[buffer(2)]],
    device float*       boundary_out  [[buffer(4)]],
    constant ContractParams& P        [[buffer(9)]],
    uint3  tid   [[thread_position_in_threadgroup]],
    uint3  tptg  [[threads_per_threadgroup]],
    uint3  tgid  [[threadgroup_position_in_grid]]
){
    const uint binLocal    = tid.x;
    const uint lane        = tid.y;
    const uint binsPerTG   = tptg.x;
    const uint lanesPerBin = tptg.y;

    if (binsPerTG > MAX_TILE_BINS || lanesPerBin > MAX_LANES) return;

    const uint tileBase = tgid.x * binsPerTG;
    const uint bin      = tileBase + binLocal;
    if (bin >= P.boundary_size) return;
    if (lane >= P.lanes) return;

    const uint stride = P.boundary_size * P.lanes;
    uint i = bin + lane * P.boundary_size;

    float4 acc4 = float4(0.0f);
    // main loop in chunks of 4*stride
    while (i + 3u * stride < P.network_size) {
        float4 e = float4(energy[i],
                          energy[i + stride],
                          energy[i + 2u*stride],
                          energy[i + 3u*stride]);
        float4 s = float4(info[i],
                          info[i + stride],
                          info[i + 2u*stride],
                          info[i + 3u*stride]);
        acc4 += e * s;
        i += 4u * stride;
    }
    float sum = acc4.x + acc4.y + acc4.z + acc4.w;

    // tail
    while (i < P.network_size) {
        sum += energy[i] * info[i];
        i += stride;
    }

    threadgroup float tg[MAX_TILE_BINS * MAX_LANES];
    const uint idx = lane * MAX_TILE_BINS + binLocal;
    tg[idx] = sum;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // lane reduction (power-of-two lanes)
    uint sred = P.lanes >> 1;
    while (sred > 0) {
        if (lane < sred) {
            tg[lane * MAX_TILE_BINS + binLocal] += tg[(lane + sred) * MAX_TILE_BINS + binLocal];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        sred >>= 1;
    }

    if (lane == 0) {
        boundary_out[bin] = tg[binLocal];
    }
}

// --- compute bulk geometry (per bulk index thread, sums slice of tensors) ---
kernel void compute_bulk_geometry(
    device const float*        tensor_energy      [[buffer(1)]],
    device const float*        ent_entropy        [[buffer(3)]],
    device float*              bulk_geometry      [[buffer(5)]],
    constant BulkParams&       P                  [[buffer(9)]],
    uint gid [[thread_position_in_grid]]
) {
    if (gid >= P.bulk_size) return;
    float s = 0.0f;
    for (uint i = gid; i < P.network_size; i += P.bulk_size) {
        s += tensor_energy[i] * ent_entropy[i];
    }
    bulk_geometry[gid] = s;
}

// --- entropy and ratios ---
kernel void compute_holographic_entropy(
    device const float*        boundary_state     [[buffer(4)]],
    device const float*        bulk_geometry      [[buffer(5)]],
    device float*              consciousness_out  [[buffer(7)]],
    constant EntropyParams&    P                  [[buffer(9)]],
    uint tid [[thread_position_in_grid]]
) {
    if (tid > 0) return; // single thread computes globals

    // Boundary entropy: normalize squares -> p, then -sum p log2 p
    float bsum2 = 0.0f;
    for (uint i = 0; i < P.boundary_size; ++i) {
        float x = boundary_state[i];
        bsum2 += x * x;
    }
    float H_b = 0.0f;
    if (bsum2 > EPS) {
        for (uint i = 0; i < P.boundary_size; ++i) {
            float p = (boundary_state[i] * boundary_state[i]) / bsum2;
            if (p > EPS) H_b -= p * log2(p);
        }
    }

    // Bulk entropy: normalize abs -> q, then -sum q log2 q
    float asum = 0.0f;
    for (uint i = 0; i < P.bulk_size; ++i) {
        asum += fabs(bulk_geometry[i]);
    }
    float H_bulk = 0.0f;
    if (asum > EPS) {
        for (uint i = 0; i < P.bulk_size; ++i) {
            float q = fabs(bulk_geometry[i]) / asum;
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

// --- phi (per tensor thread sums over all other tensors) ---
kernel void information_integration_phi(
    device const float*        tensor_data        [[buffer(0)]],
    device const float*        boundary_activity      [[buffer(2)]],
    device const float*        bulk_geometry      [[buffer(5)]],
    device float*              phi_values         [[buffer(6)]],
    constant PhiParams&        P                  [[buffer(9)]],
    uint i [[thread_position_in_grid]]
) {
    if (i >= P.network_size) return;
    const uint vec_len = P.vector_len;
    const uint base_i = i * vec_len;

    float sum_mi = 0.0f;
    float wi = boundary_activity[i];
    float bi = fabs(bulk_geometry[i % P.bulk_size]) + EPS;

    for (uint j = 0; j < P.network_size; ++j) {
        if (j == i) continue;
        const uint base_j = j * vec_len;
        float dotv = 0.0f;
        // vector dot (length 64)
        for (uint k = 0; k < vec_len; ++k) {
            dotv += tensor_data[base_i + k] * tensor_data[base_j + k];
        }
        float wj = boundary_activity[j];
        float bj = fabs(bulk_geometry[j % P.bulk_size]) + EPS;
        float w = wi * wj * sqrt(bi * bj);
        sum_mi += fabs(dotv) * w;
    }
    phi_values[i] = sum_mi;
}

// --- detect and pack consciousness metrics ---
kernel void detect_consciousness(
    device const float*        phi_values         [[buffer(6)]],
    device const float*        boundary_state     [[buffer(4)]],
    device const float*        bulk_geometry      [[buffer(5)]],
    device float*              consciousness_out  [[buffer(7)]],
    constant EntropyParams&    EP                 [[buffer(9)]],
    uint tid [[thread_position_in_grid]]
) {
    if (tid > 0) return;

    // reuse H_b, H_bulk from previous kernel already stored in [2],[3]
    float H_b   = consciousness_out[2];
    float H_bulk= consciousness_out[3];
    float ratio = consciousness_out[4];
    float emergence = consciousness_out[7];

    // aggregate phi
    float total_phi = 0.0f;
    float max_phi = 0.0f;
    uint count = 0u;
    for (uint idx = 0; idx < 65536u; ++idx) {
        float v = phi_values[idx];
        if (idx == 0u && v == 0.0f) {
            if (idx >= 1u) break;
        }
        if (v == 0.0f) {
            if (count > 0u && idx > 4096u) break;
        } else {
            total_phi += v;
            if (v > max_phi) max_phi = v;
            count++;
        }
        if (idx > 32768u) break;
    }
    float N = max(1.0f, (float)count);
    float phi_complexity = total_phi / N;
    float global_coh = total_phi / max(max_phi * N, 1e-3f);

    // self-awareness proxy: normalized dot of boundary vs first bulk slice
    float bsum2 = 0.0f;
    for (uint i = 0; i < EP.boundary_size; ++i) { float x = boundary_state[i]; bsum2 += x*x; }
    float asum = 0.0f;
    for (uint i = 0; i < EP.bulk_size; ++i) { float x = bulk_geometry[i]; asum += x*x; }
    float denom = sqrt(max(bsum2, EPS)) * sqrt(max(asum, EPS));
    float self_ref = 0.0f;
    if (denom > EPS) {
        uint m = min(EP.boundary_size, EP.bulk_size);
        for (uint i = 0; i < m; ++i) self_ref += (boundary_state[i] * bulk_geometry[i]);
        self_ref = self_ref / denom;
    }
    self_ref = clamp(self_ref, -1.0f, 1.0f);

    // information integration proxy
    float info_int = H_b * emergence;

    // processing efficiency
    float proc_eff = ratio / (1.0f + ratio);

    // score
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
    // Add damping term (0.95 = 5% decay per step) to prevent runaway growth
    float next = 0.95f * (cur + P.dt * (grad + 0.1f * env));
    tensor_data[base] = next;
}

// =========================================================
// RESERVOIR ENGINE KERNELS
// =========================================================

// Kernel parameters for reservoir evolution
struct ReservoirParams {
    float field_coupling;
    float temporal_decay;
    float boundary_bulk_coupling;
    float temperature;
    float dt;
};

kernel void evolve_tensor_field_reservoir(
    device float* field [[buffer(10)]],           // 64×64×16 tensor field
    device float* echo [[buffer(11)]],            // 1024 echo state
    device const float* boundary_input [[buffer(12)]],  // 4096 boundary input
    constant ReservoirParams& P [[buffer(16)]],
    uint3 gid [[thread_position_in_grid]]
)
{
    uint x = gid.x;  // 0..63
    uint y = gid.y;  // 0..63
    uint z = gid.z;  // 0..15

    if (x >= 64u || y >= 64u || z >= 16u) return;

    uint idx = z * 64u * 64u + y * 64u + x;

    // Local field value
    float f = field[idx];

    // Couple to boundary (project 4096 → field position)
    uint b_idx = (idx * 7919u) % 4096u;  // pseudo-random projection
    float boundary_drive = boundary_input[b_idx] * P.boundary_bulk_coupling;

    // Couple to echo state (1024 reservoir)
    uint e_idx = idx % 1024u;
    float echo_coupling = echo[e_idx] * P.field_coupling;

    // Thermal noise
    float noise = (fract(sin(float(idx) * 12.9898f + float(z) * 78.233f) * 43758.5453f) - 0.5f) * P.temperature;

    // Temporal evolution with decay
    float df = -f * (1.0f - P.temporal_decay) + boundary_drive + echo_coupling + noise;

    field[idx] = f + P.dt * df;

    // Update echo state (simple recurrent dynamics)
    if (idx < 1024u) {
        float recurrent = 0.0f;
        for (uint i = 0u; i < 8u; i++) {
            uint j = (idx + i * 128u) % 1024u;
            recurrent += echo[j] * 0.1f;
        }
        echo[idx] = tanh(recurrent + boundary_drive * 0.1f);
    }
}

kernel void holographic_reservoir_readout(
    device const float* field [[buffer(10)]],      // 64×64×16 tensor field
    device float* features_out [[buffer(13)]],     // 128 features
    device float* bulk_recon [[buffer(14)]],       // 512 bulk reconstruction
    constant ReadoutDims& D [[buffer(16)]],
    uint2 gid [[thread_position_in_grid]]
)
{
    uint feat_idx = gid.x;
    uint bulk_idx = gid.y;

    // Feature extraction (project field → 128D)
    if (feat_idx < D.feat_count) {
        float sum = 0.0f;
        for (uint i = 0u; i < 64u; i++) {
            for (uint j = 0u; j < 64u; j++) {
                for (uint k = 0u; k < 16u; k++) {
                    uint field_idx = k * 64u * 64u + j * 64u + i;
                    // Random projection with fixed seed
                    float weight = fract(sin(float(field_idx * 17u + feat_idx * 31u)) * 43758.5453f) * 2.0f - 1.0f;
                    sum += field[field_idx] * weight;
                }
            }
        }
        features_out[feat_idx] = tanh(sum / 100.0f);  // normalize
    }

    // Bulk reconstruction (project field → 512D bulk space)
    if (bulk_idx < D.bulk_size) {
        float sum = 0.0f;
        for (uint i = 0u; i < 64u; i++) {
            for (uint j = 0u; j < 64u; j++) {
                // Sample specific z-layers for bulk
                uint z = bulk_idx % 16u;
                uint field_idx = z * 64u * 64u + j * 64u + i;
                float weight = fract(sin(float(field_idx * 13u + bulk_idx * 29u)) * 43758.5453f) * 2.0f - 1.0f;
                sum += field[field_idx] * weight;
            }
        }
        bulk_recon[bulk_idx] = sum / 64.0f;  // normalized bulk state
    }
}

kernel void reservoir_consciousness_detection(
    device const float* features_out [[buffer(13)]],    // 128 features
    device const float* bulk_recon [[buffer(14)]],      // 512 bulk
    device const float* field [[buffer(10)]],           // 64×64×16 field
    device float* metrics_out [[buffer(15)]],           // 5 metrics
    uint tid [[thread_position_in_grid]]
)
{
    if (tid != 0u) return;  // single-threaded computation

    // Compute 5 consciousness metrics:
    // [0] Reservoir Φ (phi) - information integration proxy
    // [1] Spectral complexity
    // [2] Temporal coherence
    // [3] Holographic coupling
    // [4] Overall consciousness estimate

    // 1. Reservoir Φ - variance across features
    float mean_feat = 0.0f;
    for (uint i = 0u; i < 128u; i++) {
        mean_feat += features_out[i];
    }
    mean_feat /= 128.0f;

    float var_feat = 0.0f;
    for (uint i = 0u; i < 128u; i++) {
        float d = features_out[i] - mean_feat;
        var_feat += d * d;
    }
    var_feat /= 128.0f;

    float phi = sqrt(var_feat);  // simple Φ proxy

    // 2. Spectral complexity - measure of bulk richness
    float bulk_energy = 0.0f;
    for (uint i = 0u; i < 512u; i++) {
        bulk_energy += bulk_recon[i] * bulk_recon[i];
    }
    float spectral_complexity = sqrt(bulk_energy / 512.0f);

    // 3. Temporal coherence - field stability measure
    float field_energy = 0.0f;
    uint field_size = 64u * 64u * 16u;
    for (uint i = 0u; i < field_size; i++) {
        field_energy += field[i] * field[i];
    }
    float temporal_coherence = tanh(field_energy / float(field_size));

    // 4. Holographic coupling - feature-bulk correlation
    float coupling = 0.0f;
    for (uint i = 0u; i < 128u; i++) {
        uint b_idx = (i * 4u) % 512u;  // map features to bulk
        coupling += features_out[i] * bulk_recon[b_idx];
    }
    coupling = tanh(coupling / 128.0f);

    // 5. Overall consciousness estimate (weighted combination)
    float consciousness = 0.3f * phi + 0.2f * spectral_complexity + 
                         0.2f * temporal_coherence + 0.3f * fabs(coupling);

    // Write metrics
    metrics_out[0] = phi;
    metrics_out[1] = spectral_complexity;
    metrics_out[2] = temporal_coherence;
    metrics_out[3] = coupling;
    metrics_out[4] = consciousness;
}
// nan_scrub.metal - Safety net for NaN/Inf values in public buffers
#include <metal_stdlib>
using namespace metal;

kernel void scrub_nan_inf(
    device float* buf [[buffer(0)]],
    constant uint& count [[buffer(1)]],
    uint gid [[thread_position_in_grid]]
){
    if (gid >= count) return;
    float v = buf[gid];
    if (!isfinite(v)) v = 0.0f;
    buf[gid] = clamp(v, -1e9f, 1e9f);
}
