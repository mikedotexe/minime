//
// Memory mode testing shaders
// For A/B comparison of Shared vs Managed vs Private modes
//

#include <metal_stdlib>
using namespace metal;

// Simple bandwidth test kernel
kernel void memory_test_kernel(
    device const float* input [[buffer(0)]],
    device float* output [[buffer(1)]],
    uint tid [[thread_position_in_grid]])
{
    // Read from input
    float value = input[tid];

    // Some computation to ensure GPU actually processes
    // (prevents optimization that would skip memory access)
    value = sin(value) * cos(value) + value * 0.5;
    value = tanh(value * 2.0) * 0.9;

    // Additional operations to simulate real workload
    for (int i = 0; i < 10; i++) {
        value = fma(value, 1.001, 0.001);
    }

    // Write to output
    output[tid] = value;
}

// Cache-handoff pattern test
kernel void handoff_test_kernel(
    device float* data [[buffer(0)]],         // Read and write same buffer
    device const float* params [[buffer(1)]], // Parameters from CPU
    uint tid [[thread_position_in_grid]])
{
    // Read current value (from CPU)
    float value = data[tid];

    // Apply transformation based on CPU parameters
    float scale = params[0];
    float offset = params[1];

    value = value * scale + offset;

    // GPU processing
    value = sqrt(abs(value)) * sign(value);

    // Write back for CPU to read
    data[tid] = value;
}

// Tiled access pattern test
kernel void tiled_access_test(
    device const float* input [[buffer(0)]],
    device float* output [[buffer(1)]],
    constant uint& tile_size [[buffer(2)]],
    constant uint& prime_stride [[buffer(3)]],
    uint tid [[thread_position_in_grid]],
    uint group_id [[threadgroup_position_in_grid]],
    uint local_id [[thread_index_in_threadgroup]])
{
    threadgroup float tile[256];

    // Load tile with prime stride
    uint load_idx = group_id * 256 + ((local_id * prime_stride) % 256);
    tile[local_id] = input[load_idx];

    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Process tile
    float sum = 0.0;
    for (uint i = 0; i < 32; i++) {
        uint idx = (local_id + i * prime_stride) % 256;
        sum += tile[idx];
    }

    // Write result
    output[tid] = sum / 32.0;
}