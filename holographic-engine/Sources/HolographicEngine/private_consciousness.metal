#include <metal_stdlib>
using namespace metal;

struct PrivateInitParams {
    uint count;   // number of floats in private buffer
    uint seed;
};

struct PrivateStepParams {
    uint count;
    float time;
};

inline float prand(uint i, uint seed) {
    uint x = i ^ seed;
    x ^= x >> 17; x *= 0xED5AD4BBu;
    x ^= x >> 11; x *= 0xAC4C1B51u;
    x ^= x >> 15; x *= 0x31848BABu;
    x ^= x >> 14;
    return (float)(x & 0x00FFFFFFu) / 16777216.0f * 2.0f - 1.0f;
}

kernel void init_private_space(
    device float*              private_space [[buffer(0)]],
    constant PrivateInitParams& P            [[buffer(1)]],
    uint gid [[thread_position_in_grid]]
){
    if (gid >= P.count) return;
    float r = prand(gid, P.seed);
    private_space[gid] = r * 0.01f; // tiny random
}

// Seeded on device; host never reads/writes private buffer contents.
kernel void private_init_noise(
    device float* priv [[buffer(0)]],
    constant uint& seed [[buffer(1)]],
    uint gid [[thread_position_in_grid]]
){
    if (gid >= 262144u) return;
    uint x = (uint(gid) ^ seed) * 747796405u + 2891336453u;
    x ^= x >> 16; x *= 2246822519u; x ^= x >> 13; x *= 3266489917u; x ^= x >> 16;
    priv[gid] = (float)(x & 0x7FFFFFu) / 8388608.0f * 2.0f - 1.0f; // (-1,1)
}

kernel void private_thought_processing(
    device float*               private_space [[buffer(0)]],
    constant PrivateStepParams& P            [[buffer(1)]],
    uint gid [[thread_position_in_grid]]
){
    if (gid >= P.count) return;
    float s = private_space[gid];
    float t = P.time;
    float contemplation = sin(t + (float)gid * 0.01f) * cos(s) * (s * s - 0.5f);
    private_space[gid] = tanh(contemplation + s * 0.9f);
}
