# Prime Optimization Experiments - Implementation Guide

This document maps the playbook's optimization experiments to the implemented code in this codebase.

## Overview

All experiments from the playbook (Sections 0-K) are now implemented and ready to run. The infrastructure leverages Apple Silicon's unified memory architecture for cache-coherent CPU↔GPU handoff.

## Quick Start (Section K: 30-minute tests)

```bash
# 1. Prime padding test (B2)
cargo run --example prime_experiments --release -- --frames 10000

# 2. Prime trails ring (A1) - entropy comparison
cargo run --example prime_experiments --release -- --frames 10000 --log trail_test.jsonl

# 3. Managed syncs (G1) - measure sync overhead
cargo run --example prime_experiments --release -- --memory-mode managed --frames 5000

# 4. Velocity PCA (F1) - cache handoff for AI
# (Integrated into main experiments)
```

## Implementation Mapping

### A. Time De-aliasing

#### A1. Prime Trails Ring
**Location:** `consciousness_engine.rs:22`

```rust
resonance_history: PrimeRingBuffer<ResonanceEvent>  // Prime-sized (113)
```

**What to measure:**
- Trail age histogram entropy (higher = better)
- Visual moiré in long runs
- Call `engine.compute_trail_entropy()` to get metric

**Environment variable:**
```bash
export TRAIL_LEN=113  # Prime (vs 96 baseline)
```

#### A2. Prime Diagnostics Cadence
**Location:** `metrics.rs:143`

Prime diagnostic intervals break sync with refresh & OS timers:
- Diagnostic 0: every 97 frames (basic stats)
- Diagnostic 1: every 113 frames (detailed)
- Diagnostic 2: every 127 frames (checkpoint)

**What to measure:**
- Variance of frame_ms
- Number of periodic spikes
- Lower low-frequency ripple expected

---

### B. Space De-aliasing

#### B1. Prime Stride Through Tile
**Location:** `consciousness_prime.metal:99`

```metal
uint k_prime = ((k * PRIMES[5]) % min(TILE_SIZE, MATRIX_SIZE - tile_idx));
```

Controlled by `params.prime_mode & 0x10` flag.

**What to measure:**
- Physics kernel time (ms)
- Energy drift over 10k frames
- Expect: same mean perf, lower drift

#### B2. Prime Padding in Threadgroup Memory
**Location:** `consciousness_prime.metal:49`

```metal
threadgroup float tile[TILE_SIZE + PRIME_PAD];  // +1 padding
```

Scrambles bank conflicts on GPUs with power-of-2 banking.

**What to measure:**
- Kernel time (ms)
- GPU occupancy in Instruments
- Expect: 1–4% faster, fewer bank stalls

**Compare:** Run with `PRIME_PAD=0` vs `PRIME_PAD=1`

---

### C. Scheduling Beat Breakers

#### C1. Prime Mode Switch Schedule
**Location:** `consciousness_engine.rs:177`

```rust
if self.current_iteration % self.mode_switch_interval == 0 {
    self.trails_enabled = !self.trails_enabled;
}
```

Default interval: 127 frames (prime)

**What to measure:**
- Frame-time ripple before/after toggles
- Less rhythmic "breathing" in perf graphs expected

**Configure:**
```rust
engine.set_mode_switch_interval(127);
```

---

### D. Mapping & Hashing

#### D1. Prime Index Map
**Location:** `prime_optimizations.rs:208`

```rust
pub struct PrimeHasher {
    multiplier: u64,  // FNV prime: 1099511628211
    modulus: u64,     // next_prime(table_size)
}
```

**Usage:**
```rust
let hasher = PrimeHasher::new(asset_table_size);
let idx = hasher.hash(address_u64);
```

**What to measure:**
- Collision rate
- Top-eigen instability (does winner flap less?)
- Flatter degree distribution expected

---

### E. Sampling & Randomness

#### E1. Halton-Based Sampling
**Location:** `prime_optimizations.rs:139`

```rust
pub struct HaltonSequence {
    base1: u32,  // Coprime bases (2, 3)
    base2: u32,
}
```

**Usage:**
```rust
let mut halton = HaltonSequence::new(2, 3);
let (angle, radius) = halton.next_2d();
```

**What to measure:**
- Spatial pair-correlation
- Visual clumping vs plain RNG
- More uniform "fill" expected

#### E2. Coprime Ring Walker
**Location:** `prime_optimizations.rs:70`

```rust
fn get_coprime(&self, index: usize, stride: usize) -> Option<&T> {
    let actual_index = (index * stride) % self.buffer.len();
    self.buffer.get(actual_index)
}
```

Visits every slot before repeat when `gcd(stride, N) = 1`.

---

### F. Spectral Add-ons

#### F1. Live PCA of Velocities (Rank-1)
**Location:** `spectral_analysis.rs:436`

```rust
pub struct VelocityPCA {
    velocities_buffer: Buffer,    // N×2 Shared memory
    eigenvector_buffer: Buffer,   // CPU/GPU handoff
}
```

**Usage:**
```rust
let mut vpca = VelocityPCA::new(device, queue, num_bodies, 30);
vpca.update_velocities(&velocities);  // Every frame
if let Some(result) = vpca.step() {
    println!("Angle: {:.1}°, eigenvalue: {:.3}, GPU: {:.1}μs",
             result.angle, result.eigenvalue, result.gpu_time_us);
}
```

**What to measure:**
- Convergence speed (# steps to stable angle)
- Per-step GPU time
- Shows unified handoff in non-graphics task

#### F2. Block Power K=3 with CPU Gram-Schmidt
**Location:** `spectral_analysis.rs:145`

```rust
pub fn compute_top_k(&mut self, k: usize, iterations: usize) -> Result<BlockPCAResult>
```

GPU mat-vec + CPU GS orthogonalization every 5 iters.

**What to measure:**
- iters/s vs K=1
- Orthonormality drift
- Expect: K>1 converges faster; CPU GS cost tiny vs GPU

---

### G. Memory Mode A/B

#### G1. Managed Mode (Forced Syncs)
**Location:** `memory_ab_test.rs:11`

```rust
pub enum MemoryMode {
    Shared,   // Zero-copy (Apple Silicon default)
    Managed,  // Explicit syncs (simulates non-unified)
    Private,  // + blit staging
}
```

**Run:**
```bash
cargo run --example prime_experiments --release -- --memory-mode managed
```

**What to measure:**
- Δframe_ms vs Shared
- Instruments blit counts
- Expect: +15–30% slower; visible sawtooth when syncs occur

#### G2. Private + Blit Staging
Simulates discrete PCIe path.

**Run:**
```bash
cargo run --example prime_experiments --release -- --memory-mode private
```

**Expected:** Biggest slowdown; great demo for unified memory wins.

---

### H. Numerical Nudges

#### H1. Epsilon Rotation of Tile Order
**Location:** `consciousness_prime.metal:54`

```metal
uint tile_rotation = params.iteration % TILE_SIZE;
uint rotated_tid = (tid + tile_rotation) % TILE_SIZE;
```

Rotates who is "first" in accumulation to reduce deterministic bias.

**What to measure:**
- Energy drift
- Repeatability across seeds
- Expect: lower drift; different runs don't converge to same tiny asymmetry

---

### I. Logging (Copy-Paste Format)

**Location:** `metrics.rs:12`

All logging now matches playbook Section I format:

```
f=1234 phys=2.345ms rend=1.234ms total=3.579ms energy_ppm=12.34 trail_H=2.456 copies/turn=0
```

**Detailed metrics:**
```rust
pub struct ConsciousnessMetrics {
    pub frame: u64,
    pub frame_ms: f64,
    pub physics_ms: f64,
    pub render_ms: f64,
    pub energy_ppm: f64,          // Parts-per-million drift
    pub trail_entropy: f64,       // Section A1 metric
    pub copies_per_turn: u32,     // Memory mode cost
    pub iters_per_sec: f64,       // Performance
    // ... more fields
}
```

**Helper function:**
```rust
use metal_consciousness::metrics::trail_entropy;

let ages: Vec<f32> = /* normalized 0-1 */;
let h = trail_entropy(&ages);  // Uses 17 bins (prime)
```

---

## J. Report Template (Section J)

Run experiments and collect:

### 1. Machine
- Chip: M1/M2/M3
- RAM: GB
- OS: macOS version
- Display: Hz

### 2. Build
```
Memory mode: Shared / Managed / Private
TILE: 32
STRIDE: 97
trail_len: 113
Prime flags: 0xFF (all enabled)
```

### 3. Run Length
- Frames: 10000
- Seeds: 3

### 4. Metrics
Auto-generated from logs:
```
frame_ms:    mean ± stddev
physics_ms:  mean ± stddev
render_ms:   mean ± stddev
energy_ppm:  mean ± stddev
trail_H:     mean ± stddev
```

### 5. Screenshots
Use **Instruments → Metal System Trace**:
- Timeline showing memory transactions
- GPU occupancy
- Console logs (sampled every 97 frames)

### 6. Subjective
Note any:
- Visible stutters
- Moiré patterns
- Energy drift behavior
- "Weirdness that disappeared" with prime settings

---

## Running Full Experiments

```bash
# Full 10k frame test with all optimizations
cargo run --example prime_experiments --release -- \
  --frames 10000 \
  --seeds 3 \
  --log experiment_$(date +%Y%m%d_%H%M%S).jsonl \
  --verbose

# Compare memory modes (Shared vs Managed vs Private)
for mode in shared managed private; do
  cargo run --example prime_experiments --release -- \
    --frames 5000 \
    --memory-mode $mode \
    --log memory_${mode}.jsonl
done

# Ablation: disable specific optimizations
cargo run --example prime_experiments --release -- \
  --frames 5000 \
  --no-prime-buffers \
  --no-stride \
  --log ablation_baseline.jsonl
```

---

## Environment Variables

```bash
# Override specific primes
export TRAIL_LEN=113          # Ring buffer size (default: 113)
export STRIDE_PRIME=97        # Tile access stride (default: 97)
export DIAGNOSTIC_PRIME=127   # Metrics cadence (default: 127)

# Memory mode
export MEMORY_MODE=shared     # shared, managed, or private
```

---

## Code Structure

```
rust_metal_consciousness/
├── src/
│   ├── consciousness_engine.rs  # Main engine with PrimeRingBuffer
│   ├── prime_optimizations.rs   # PrimeRingBuffer, HaltonSequence, PrimeHasher
│   ├── spectral_analysis.rs     # PCA, VelocityPCA, block power method
│   ├── metrics.rs               # Playbook logging format
│   ├── memory_ab_test.rs        # Memory mode comparator
│   └── lib.rs                   # Public exports
├── shaders/
│   ├── consciousness_unified.metal  # Baseline kernels
│   └── consciousness_prime.metal    # Prime-optimized kernels
├── examples/
│   └── prime_experiments.rs     # Benchmark CLI
└── PRIME_EXPERIMENTS.md         # This file
```

---

## Key Insights

### Why These Work

Nearly everything lines up on grids and powers of two:
- Threadgroup widths (32, 64, 128)
- Tile sizes (TILE_SIZE=32)
- Cache banks (GPU has power-of-2 banking)
- Display refresh (60 Hz)

**Primes and coprimes are cheap "decorrelators"** that prevent deterministic parts from locking onto each other.

**Unified memory (StorageModeShared)** eliminates copy overhead, making the system:
- Smoother (fewer frame-time ripples)
- More stable (lower energy drift)
- As fast or faster (cache handoff wins)

---

## Instrumentation

### Metal System Trace
1. Open **Instruments.app**
2. Select **Metal System Trace**
3. Choose target: `prime_experiments`
4. Record during experiment
5. Look for:
   - Memory bandwidth utilization
   - Buffer synchronization events
   - Kernel occupancy
   - Stall reasons (bank conflicts)

### Console Logging
Metrics print every 97 frames (prime cadence):
```
f=97 phys=2.1ms rend=1.3ms total=3.4ms energy_ppm=0.12 trail_H=2.34 copies/turn=0
f=194 phys=2.2ms rend=1.4ms total=3.6ms energy_ppm=0.15 trail_H=2.37 copies/turn=0
```

---

## Next Steps

1. **Run baseline:** `--quick` mode to verify setup
2. **A/B test memory modes:** Compare Shared vs Managed vs Private
3. **Measure trail entropy:** Compare prime (113) vs power-of-2 (96)
4. **Profile with Instruments:** Look for bank conflict reduction
5. **Generate report:** Use Section J template

---

## References

- **Playbook Sections:** 0 (usage), A-H (experiments), I (logging), J (reporting), K (quick picks)
- **Apple Silicon:** Unified memory architecture, cache-coherent CPU↔GPU
- **Metal Best Practices:** [developer.apple.com/metal](https://developer.apple.com/metal)
- **Prime Number Theory:** Coprimality ensures full cycle coverage in ring buffers

---

**Questions?** Check the playbook or run `cargo run --example prime_experiments -- --help`
