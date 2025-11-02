#include <metal_stdlib>
using namespace metal;

// ============================================================
// A/V Feature Kernels for Unified-Memory (StorageModeShared)
// ============================================================
// Audio: 7-band Goertzel energies + RMS
// Video: luma mean/var, edge density, frame-diff + 2x2 region stats
// Outputs are sums; host finalizes to 8-dim features.
//
// Threading:
//   - audio_goertzel: one thread per band (+tid==0 computes RMS)
//   - video_accumulate: one thread per pixel (tile reductions)
//
// Notes:
//   - Keep N (samples), W,H,stride small enough to stay realtime.
//   - Use prime pacing (e.g. 97-sample hop, ~101ms video tick).
// ============================================================

// ---------------------------
// Audio (Goertzel)
// ---------------------------
struct AudioParams {
    uint n;           // window length (samples)
    uint bands;       // number of bands (<= 16)
    float fs;         // sample rate
};

kernel void audio_goertzel(
    device const float* samples   [[buffer(0)]],  // length >= N
    device const float* freqs     [[buffer(1)]],  // length >= bands (Hz)
    device float* out_sums        [[buffer(2)]],  // length >= (bands + 1); out[0..bands-1]=band power, out[bands]=RMS^2 sum
    constant AudioParams& P       [[buffer(3)]],
    uint tid                      [[thread_position_in_grid]]
){
    if (tid < P.bands) {
        float f = freqs[tid];
        float w = 2.0f * float(M_PI) * (f / P.fs);
        float c = 2.0f * cos(w);

        float s0 = 0.0f, s1 = 0.0f, s2 = 0.0f;
        for (uint i = 0; i < P.n; ++i) {
            s0 = samples[i] + c * s1 - s2;
            s2 = s1;
            s1 = s0;
        }
        // Power at frequency bin
        float p = s1*s1 + s2*s2 - c*s1*s2;
        out_sums[tid] = max(p, 0.0f);
    }

    // RMS^2 sum (one thread does it; cheap)
    if (tid == 0) {
        float s = 0.0f;
        for (uint i = 0; i < P.n; ++i) {
            float v = samples[i];
            s += v*v;
        }
        out_sums[P.bands] = s;  // host divides by N
    }
}

// ---------------------------
// Video (luma/edge/diff + regions)
// ---------------------------

struct VideoParams {
    uint width;
    uint height;
    uint stride;  // bytes per row in luma buffer
    uint use_prev;// 1 if prev_frame is valid
};

// Global accumulators (writes via atomics)
struct VideoSums {
    // 0: sum(L), 1: sum(L^2), 2: sum(edge), 3: sum(diff)
    // 4..7: region sum(L), 8..11: region sum(L^2)  [2x2 regions]
    atomic_float acc[12];
};

inline float sobel3x3(device const uchar* luma, uint x, uint y, uint W, uint H, uint stride) {
    // pad at borders by clamping
    auto L = [&](int xx, int yy)->float {
        uint X = (uint)clamp(xx, 0, int(W-1));
        uint Y = (uint)clamp(yy, 0, int(H-1));
        return float(luma[Y*stride + X]) * (1.0f/255.0f);
    };
    float gx =
        -1.0f*L(x-1,y-1) + 1.0f*L(x+1,y-1) +
        -2.0f*L(x-1,y  ) + 2.0f*L(x+1,y  ) +
        -1.0f*L(x-1,y+1) + 1.0f*L(x+1,y+1);
    float gy =
        -1.0f*L(x-1,y-1) - 2.0f*L(x,y-1) - 1.0f*L(x+1,y-1) +
         1.0f*L(x-1,y+1) + 2.0f*L(x,y+1) + 1.0f*L(x+1,y+1);

    return fast::sqrt(gx*gx + gy*gy);
}

kernel void video_accumulate(
    device const uchar* cur_luma     [[buffer(0)]],
    device const uchar* prev_luma    [[buffer(1)]],  // optional
    device VideoSums* sums           [[buffer(2)]],
    constant VideoParams& VP         [[buffer(3)]],
    uint2 gid                        [[thread_position_in_grid]]
){
    if (gid.x >= VP.width || gid.y >= VP.height) return;

    uint x = gid.x, y = gid.y;
    float L = float(cur_luma[y*VP.stride + x]) * (1.0f/255.0f);

    // Edge magnitude (Sobel)
    float E = sobel3x3(cur_luma, x, y, VP.width, VP.height, VP.stride);

    // Frame diff (abs luma delta)
    float D = 0.0f;
    if (VP.use_prev == 1) {
        float P = float(prev_luma[y*VP.stride + x]) * (1.0f/255.0f);
        D = fast::fabs(L - P);
    }

    // Region id (2x2)
    uint rx = (x < VP.width/2) ? 0u : 1u;
    uint ry = (y < VP.height/2) ? 0u : 1u;
    uint rid = ry*2u + rx;  // 0..3

    // Atomically accumulate
    atomic_fetch_add_explicit(&sums->acc[0],  L,          memory_order_relaxed);
    atomic_fetch_add_explicit(&sums->acc[1],  L*L,        memory_order_relaxed);
    atomic_fetch_add_explicit(&sums->acc[2],  E,          memory_order_relaxed);
    atomic_fetch_add_explicit(&sums->acc[3],  D,          memory_order_relaxed);

    atomic_fetch_add_explicit(&sums->acc[4 + rid],  L,    memory_order_relaxed);
    atomic_fetch_add_explicit(&sums->acc[8 + rid],  L*L,  memory_order_relaxed);
}