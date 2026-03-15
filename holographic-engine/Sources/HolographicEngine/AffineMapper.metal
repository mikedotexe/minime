#include <metal_stdlib>
using namespace metal;

struct GemvParams {
    uint rows;
    uint cols;
    float alpha;
    float beta;
    uint use_tanh;
};

kernel void affine_gemv(
    device const float* A      [[buffer(0)]],
    device const float* x      [[buffer(1)]],
    device const float* b      [[buffer(2)]],
    device float*       y      [[buffer(3)]],
    constant GemvParams& P     [[buffer(4)]],
    uint rid [[thread_position_in_grid]]
){
    if (rid >= P.rows) return;
    const uint base = rid * P.cols;
    float acc = 0.0f;
    for (uint k = 0; k < P.cols; ++k) acc += A[base + k] * x[k];
    float out = P.alpha * acc + P.beta * b[rid];
    if (P.use_tanh != 0u) out = tanh(out);
    y[rid] = out;
}
