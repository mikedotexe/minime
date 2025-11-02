# Unified Spectral Lab: Cache-Handoff Eigenspace Solvers

**Fast, scrappy experiments** for benchmarking GPU+CPU eigenspace solvers using Metal's zero-copy unified memory.

## The Pattern: Cache Handoff

This lab demonstrates the **cache-handoff loop** that powers all high-performance spectral methods on Apple Silicon:

```
GPU: A·X (tiled matvec, ~1-2ms)
  ↓ zero-copy read via StorageModeShared
CPU: Orthonormalize (Gram-Schmidt, ~3-5ms)
  ↓ zero-copy write via StorageModeShared
GPU: next iteration...
```

**No data copies.** Buffers live in unified memory. GPU writes, CPU reads. CPU writes, GPU reads. Cache coherence handles synchronization.

## What You Get

### Three Algorithms

1. **Power** - Classic power iteration (K=1)
   - Simplest: GPU A·x, CPU normalize
   - Converges to dominant eigenvector

2. **Block** - Block power with Gram-Schmidt (K≤16)
   - GPU A·X (K vectors at once)
   - CPU orthonormalizes the block
   - Captures top-K eigenspace

3. **Cheby** - Chebyshev-accelerated power (degree M)
   - Uses M GPU matvecs per iteration
   - Faster convergence via polynomial acceleration

### Metrics Tracked

- Wall time (ms), iters/sec, matvecs/sec
- Rayleigh quotient λ estimate
- Residual ‖A·x - λ·x‖ / ‖A·x‖
- Convergence behavior

## Quick Start

```bash
cd unified_spectral_lab

# Build and run default experiment (block power, N=1024, K=4)
cargo run --release

# Run full parameter sweep
./scripts/run_experiments.sh

# Analyze results
./scripts/analyze.mjs
```

### Example Output

```json
{
  "algo": "block",
  "n": 1024,
  "k": 4,
  "m_cheby": 0,
  "iters": 12,
  "matvecs": 48,
  "ms_total": 45.23,
  "iters_per_s": 265.23,
  "matvecs_per_s": 1060.92,
  "lambda_rayleigh": 1048.576,
  "residual": 2.3e-7,
  "seed": 12648430
}
```

## Environment Variables

Control experiments via environment:

```bash
N=2048 K=8 ITERS=20 ALGO=block cargo run --release
ALGO=power N=4096 ITERS=16 cargo run --release
ALGO=cheby N=4096 CHEBY_M=5 ITERS=10 cargo run --release
```

## The Tiled Kernel

Both `matvec_tiled` and `block_matvec_tiled` use the same pattern:

```metal
threadgroup float xtile[TILE + 1];  // +1 pad helps bank conflicts

for (uint t = 0; t < tiles; ++t) {
    // Load tile collaboratively
    xtile[tid] = (c < N) ? x_in[c] : 0.0f;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Each thread accumulates its row
    for (uint j = 0; j < here; ++j) {
        sum += arow[j] * xtile[j];
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
}
```

**Why this works:** Threadgroup memory is ~15x faster than device memory on Apple GPUs. Tiling + collaborative loads = bandwidth win.

## Hair-Brained Toggles to Try

1. **Prime stride**: Replace `for (j=0..here)` with `j2=(j*97)%here` to scramble bank conflicts
2. **Diagonal preconditioner**: Scale A → D^{-1/2}·A·D^{-1/2} before iteration
3. **Chebyshev band-pass**: Target intermediate eigenvalues by shift-scaling A
4. **Randomized SVD**: Replace block-power with sketch-and-solve
5. **Memory mode comparison**: Clone with Managed/Private to measure copy overhead

## Connection to Consciousness Work

This pattern is **exactly** what you want for:

- **7D consciousness evolution**: Track dominant modes of the 13×7×7 resonance field
- **Velocity PCA** (from the playbook): Extract principal components of particle motion
- **Embedding compression**: Low-rank approximation of LLM embedding streams
- **Prime-structured attention**: Learn attention heads using the 13×7×7 matrices

The kernels stay the same. You just change what matrix `A` represents.

## Performance Expectations (M1 Max)

| N    | Algo  | K | Iters | Total (ms) | Matvecs/sec |
|------|-------|---|-------|------------|-------------|
| 1024 | block | 4 | 12    | ~45        | ~1000       |
| 4096 | power | 1 | 16    | ~180       | ~90         |
| 8192 | block | 8 | 8     | ~850       | ~75         |

GPU time per matvec: **~1-2ms** (zero-copy)
CPU orthonormalize: **~3-5ms** (K=4)

## Next Steps

1. **Run the experiments**: `./scripts/run_experiments.sh`
2. **Report back**: Paste `results.csv` + `analyze.mjs` output
3. **Iterate**: We'll suggest the next hair-brained tweak

---

**This is the foundation.** Once you trust the pattern, we can drop it into:
- The N-body simulation (velocity PCA overlay)
- The consciousness weaver (eigenspace tracking)
- minime.py (LLM embedding compression)

All using the same tiled kernel + cache-handoff loop.
