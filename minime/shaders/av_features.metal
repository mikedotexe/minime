#include <metal_stdlib>
using namespace metal;

// -------- Config --------
constant uint W = 128;
constant uint H = 128;
constant uint NPIX = W * H;

// Atomics layout in accum[]:
// 0: sum_luma
// 1: sumsq_luma
// 2: sum_absdiff (motion)
// 3: sum_gradmag (edge)
// 4..7: orient histogram (4 bins)

// Notes:
// - We read from a 8-bit luma texture (R8Unorm) as float in [0,1].
// - prev_luma stores last frame (float per pixel) in device memory.
// - We use atomics to avoid global reduction passes (CPU finalizes).
// - CPU computes mean/var and normalizes the 4-bin histogram.

kernel void av_accumulate_features(
    texture2d<float, access::read>  tex      [[texture(0)]],
    device atomic_float            *accum    [[buffer(0)]],
    device float                   *prev     [[buffer(1)]],
    uint2 gid [[thread_position_in_grid]]
) {
    if (gid.x >= W || gid.y >= H) return;
    const uint idx = gid.y * W + gid.x;

    // Current luma (float in [0,1]).
    float I = tex.read(gid).r;

    // Motion energy vs previous frame (L1).
    float p = prev[idx];
    float diff = fabs(I - p);
    prev[idx] = I; // update for next frame

    // Simple central-diff gradients (clamped).
    auto clamp_ix = [](int x, int lo, int hi) -> uint { return (uint)max(lo, min(hi, x)); };
    int x = (int)gid.x, y = (int)gid.y;
    uint2 xm = uint2(clamp_ix(x-1,0,W-1), y);
    uint2 xp = uint2(clamp_ix(x+1,0,W-1), y);
    uint2 ym = uint2(x, clamp_ix(y-1,0,H-1));
    uint2 yp = uint2(x, clamp_ix(y+1,0,H-1));
    float dx = tex.read(xp).r - tex.read(xm).r;
    float dy = tex.read(yp).r - tex.read(ym).r;

    float gradmag = sqrt(dx*dx + dy*dy);

    // Orientation -> 4 bins (quadrants)
    // bin0: (-pi/4..pi/4) approx dx>0, |dx|>=|dy|
    // bin1: (pi/4..3pi/4) approx dy>0, |dy|>|dx|
    // bin2: else dx<0 dominant
    // bin3: else dy<0 dominant
    float adx = fabs(dx), ady = fabs(dy);
    uint b;
    if (adx >= ady) {
        b = (dx >= 0.0f) ? 0u : 2u;
    } else {
        b = (dy >= 0.0f) ? 1u : 3u;
    }

    // Atomics
    atomic_fetch_add_explicit(&accum[0], I, memory_order_relaxed);           // sum
    atomic_fetch_add_explicit(&accum[1], I*I, memory_order_relaxed);         // sumsq
    atomic_fetch_add_explicit(&accum[2], diff, memory_order_relaxed);        // motion
    atomic_fetch_add_explicit(&accum[3], gradmag, memory_order_relaxed);     // edges
    atomic_fetch_add_explicit(&accum[4 + b], 1.0f, memory_order_relaxed);    // hist
}
