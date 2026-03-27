# MLX Integration Audit

Generated: 2026-03-16

## 1. Metal Buffer Allocations

### Long-Lived Buffers (allocated once, persist for engine lifetime)

| File:Line | Variable | Size | Lifetime | Notes |
|-----------|----------|------|----------|-------|
| `esn.rs:88` | `SpectralSR::cov` | D×D×4 = 1,048,576 (D=512) | Engine lifetime | Covariance matrix, rank-1 EWMA updated every ESN tick |
| `esn.rs:89` | `SpectralSR::x_buf` | D×4 = 2,048 | Engine lifetime | State vector for rank-1 update |
| `esn.rs:90` | `SpectralSR::v_buf` | D×4 = 2,048 | Engine lifetime | Power iteration vector |
| `esn.rs:91` | `SpectralSR::y_buf` | D×4 = 2,048 | Engine lifetime | Matvec result |
| `esn.rs:92` | `SpectralSR::rho_buf` | 4 | Engine lifetime | Scalar EWMA keep factor |
| `esn.rs:93` | `SpectralSR::dim_buf` | 4 | Engine lifetime | Scalar dimension |
| `av_gpu.rs:67` | `AvGpu::prev` | W×H×4 = 65,536 (128×128) | Engine lifetime | Previous frame for motion delta |
| `av_gpu.rs:68-69` | `AvGpu::accum` | 8×4 = 32 | Engine lifetime | Atomic accumulators |
| `nn.rs:83-111` | `MLP::w1,b1,w2,b2,dw1,db1,dw2,db2,h,x` | Varies per MLP | Engine lifetime | NeuroCell has 3 MLPs (P/R/G) |
| `nn.rs:544-549` | `NeuroCell::pred_input/output, router_input/output, reg_input/output` | 60+4+256+128+80+20 = 548 bytes | Engine lifetime | Inference I/O buffers |

### Transient Buffers (allocated per-call, CANDIDATES FOR POOLING)

| File:Line | Variable | Size | Frequency | Notes |
|-----------|----------|------|-----------|-------|
| `gpu.rs:66` | `d_buf` in `block_matvec` | 4 bytes | Every matvec call | **HOT PATH** - param buffer, could use `set_bytes` instead |
| `gpu.rs:67` | `k_buf` in `block_matvec` | 4 bytes | Every matvec call | **HOT PATH** - param buffer, could use `set_bytes` instead |
| `cheby.rs:108` | `coeff_buf` in `cheby_apply_gpu` | (order+1)×4 ≈ 28 bytes | Every filter application | Transient, small |
| `cheby.rs:133` | `params_buf` in `cheby_apply_gpu` | 16 bytes | Every filter application | Transient, small |
| `av_gpu.rs:161` | `stage` buffer in Private mode | W×H bytes = 16,384 | Every frame (Private mode only) | Staging buffer for blit |
| `av_gpu.rs:91-96` | `prev`/`accum` in `set_frame_size` | Varies | On resize (rare) | Not hot path |

### Buffer Size Summary

| Category | Total Size | Count |
|----------|-----------|-------|
| Covariance (512×512×f32) | 1 MB | 1 |
| ESN vectors (512×f32 each) | ~8 KB | 4 |
| ESN scalars | 8 bytes | 2 |
| AV GPU (128×128 prev + 8 accum) | ~65 KB | 2 |
| NeuroCell (3 MLPs + IO) | ~200 KB est. | ~30 |
| **Per-call transient** | **<100 bytes** | **4 sites** |

## 2. Command Buffer + wait_until_completed Sites

| # | File:Line | Function | Kernels Encoded | Notes |
|---|-----------|----------|-----------------|-------|
| 1 | `gpu.rs:77,90-91` | `block_matvec` | 1 (block_matvec_tiled_f32) | Called from Chebyshev iterations |
| 2 | `esn.rs:142,156-157` | `SpectralSR::rank1_ewma` | 1 (rank1_ewma_update) | **HOT** - every ESN tick |
| 3 | `esn.rs:168,182-183` | `SpectralSR::matvec` | 1 (cov_matvec) | **HOT** - 3× per power_iter call |
| 4 | `cheby.rs:150,165-166` | `cheby_apply_gpu` | 1 (cheby_bandstop_apply) | Periodic filter application |
| 5 | `av_gpu.rs:171-172` | `process_frame_gray8` (blit) | 1 (blit encoder) | Private mode only |
| 6 | `av_gpu.rs:196,213-215` | `process_frame_gray8` (compute) | 1 (av_accumulate_features) | Every video frame |
| 7 | `nn.rs:198,252-254` | `MLP::forward` | 2 (dense_relu_fwd + dense_linear_fwd) | Already batched! |
| 8 | `nn.rs:357,438-440` | `MLP::update` | 4 (sgd_apply × 4 param groups) | Already batched! |

### ESN Tick GPU Round-Trips (worst case with introspection)

1. `rank1_ewma` → 1 commit+wait
2. `power_iter(2)` → 2 `matvec` iterations × 1 commit+wait = 2 commit+waits
3. Final `matvec` for Rayleigh quotient → 1 commit+wait
4. **Total: 4 synchronous GPU round-trips per tick**

MLX comparison: batches 20-50 kernels per commit. Minime should batch rank1_ewma + all matvecs into 1 commit.

## 3. Python MLX Integration Status

| Component | File | Current Backend | MLX Status | Work Needed |
|-----------|------|-----------------|------------|-------------|
| Chat (autonomous) | `autonomous_agent.py` | MLX (port 8090) | **WORKING** | None |
| Chat (interactive) | `mikemind/llm_engine.py` | Ollama only | **MISSING** | Add `_generate_mlx()` + backend param |
| Vision | `mikemind/vision.py` | Ollama LLaVA | **MISSING** | Add MLX VLM backend (port 8091) |
| Embeddings | `mikemind/config.py` | Ollama `/api/embeddings` | **MISSING** | Add MLX `/v1/embeddings` backend |
| Speech-to-text | `tools/mic_to_sensory.py` | mlx_whisper CLI | **PARTIAL** | Wire into startup, write transcriptions to file |
| LoRA training | `tools/prepare_lora_data.py` | N/A | **PARTIAL** | Add `--dry-run`, wire adapter into startup |

### Startup Script Status (`scripts/start.sh`)

- MLX chat server: Started (port 8090)
- Whisper: Conditional (`ENABLE_WHISPER`), flag exists but whisper transcriptions not written to file
- MLX vision server: **NOT STARTED** - no `MLX_VISION_PORT` or `ENABLE_MLX_VISION`
- LoRA adapter: **NOT PASSED** - no `--adapter-path` support

## 4. MLX Patterns Not Yet Applied to Rust Metal Layer

### Buffer Pooling (MLX `BufferCache`)
MLX maintains a `BTreeMap<size, Vec<Buffer>>` pool. Transient allocations in `block_matvec` and `cheby_apply_gpu` should use a pool instead of allocating per-call.

### Page-Aligned Allocations
MLX rounds all allocations to `vm_page_size` (16384 bytes on Apple Silicon). Minime allocates exact sizes. Page alignment enables SLC (System Level Cache) fast path for buffers <4MB.

### Hazard Tracking
MLX uses `HazardTrackingModeUntracked` and manages barriers manually. Minime relies on Metal's automatic hazard tracking, which adds overhead.

### Command Buffer Batching
MLX batches 20-50 kernels per command buffer commit. Minime does 1 kernel per commit in ESN hot path (4 synchronous round-trips per tick).

### `set_bytes` for Small Parameters
MLX uses `set_bytes` for scalars/small structs instead of allocating buffers. `block_matvec`'s `d_buf`/`k_buf` (4 bytes each) should use `set_bytes`.

## 5. Metal Shaders Inventory

| Shader File | Kernels | Used By |
|-------------|---------|---------|
| `spectral.metal` | `block_matvec_tiled_f32` | `gpu.rs` block matvec |
| `esn.metal` | `rank1_ewma_update`, `cov_matvec` | `esn.rs` spectral self-reference |
| `cheby_bandstop.metal` | `cheby_bandstop_apply` | `cheby.rs` Chebyshev filter |
| `av_features.metal` | `av_accumulate_features` | `av_gpu.rs` video feature extraction |
| `nn.metal` | `dense_relu_fwd`, `dense_linear_fwd`, `sgd_apply` | `nn.rs` MLP forward/update |
| `av_feats.metal` | (older version?) | Unclear if still used |
| `spectral_monitor.metal` | (monitoring?) | Unclear if still used |
