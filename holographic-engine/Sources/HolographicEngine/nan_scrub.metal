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
