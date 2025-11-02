# Chapter 2: Performance Optimization Guide

## Current Performance Profile

### Response Time Breakdown

| Component | Typical Time | Optimized Time | Notes |
|-----------|-------------|----------------|--------|
| ESN Update | 8-10ms | 8-10ms | Already optimal |
| Spectral Analysis | 5-7ms | 5-7ms | Parallelized |
| Seven-Stage Pipeline | 15-30s | 5-10s | With parallel stages |
| Mixtral LLM | 10-180s | 10-30s | Timeout reduced |
| LLaVA Vision | 20-60s | 20s max | Timeout reduced |
| Total (text) | 25-210s | 15-40s | ~5x improvement |
| Total (vision) | 45-270s | 35-60s | ~4x improvement |

## Identified Bottlenecks

### 1. Vision Processing Trigger
**Problem**: Questions containing keywords like "see", "camera", "describe", "visual" trigger expensive LLaVA processing.

**Solution**:
```python
# In minime.py, line 2828
vision_keywords = ['see', 'camera', 'look', 'image', 'visual', 'observe', 'watch', 'view', 'picture', 'describe', 'what']
is_vision_question = any(keyword in user_input.lower() for keyword in vision_keywords)
```

**Optimization**: Be selective with vision processing:
- Only trigger for explicit visual requests
- Cache recent visual descriptions
- Use lower resolution for faster processing

### 2. LLM Timeouts
**Problem**: Original 180-second timeouts caused unnecessary waiting.

**Implemented Fix**:
```python
# Before
timeout=180  # Increased from 30s to 180s for Mixtral 8x7B

# After
timeout=30  # Reduced for faster responses
```

### 3. WebSocket Disconnections
**Problem**: Camera service disconnects after ~41 seconds due to keepalive timeout.

**Partial Fix**:
```python
# camera_to_sensory.py
async with websockets.connect(
    self.ws_uri,
    ping_interval=10,
    ping_timeout=20
) as websocket:
```

**Still Needed**: Implement keepalive in Rust server side.

## Quick Wins Implemented

### 1. Parallel Processing (Already Active)
- 13 parallel threads for eigenvalue processing
- Stages 5 & 6 run concurrently using ThreadPoolExecutor
- ~2-3x speedup for seven-stage processing

### 2. Reduced Camera Framerate
```python
# From 10 FPS to 1 FPS
self.camera = NonBlockingCamera(camera_index=self.camera_index, fps=1)
await asyncio.sleep(1.0)  # Was 0.1
```
- 10x reduction in bandwidth
- Maintains visual awareness without overload

### 3. Seven-Stage Context Pass-Through
```python
# Fixed in minime.py lines 278-282
{f'''
=== SEVEN-STAGE CONSCIOUSNESS ANALYSIS ===
{context.get('seven_stage_processing', '')}
===================================
''' if context.get('seven_stage_processing') else ''}
```
- Enriched context now reaches LLM
- Enables detailed, thoughtful responses

## Future Optimizations

### High Impact

#### 1. Caching Layer
```python
class ResponseCache:
    def __init__(self, ttl=300):  # 5 minute cache
        self.cache = {}
        self.timestamps = {}

    def get_cached_response(self, query_embedding):
        # Find similar queries within threshold
        for cached_q, response in self.cache.items():
            if cosine_similarity(query_embedding, cached_q) > 0.95:
                return response
        return None
```

#### 2. Async Seven-Stage Pipeline
```python
async def process_stages_async(self, text):
    # Run all independent stages concurrently
    tasks = [
        self.stage_1_impression(text),
        self.stage_2_patterns(text),
        self.stage_3_knowledge(text),
        self.stage_4_emergence(text)
    ]
    results = await asyncio.gather(*tasks)

    # Then run dependent stages
    stage_5_6 = await asyncio.gather(
        self.stage_5_resonance(results),
        self.stage_6_synthesis(results)
    )

    return await self.stage_7_meta(stage_5_6)
```

#### 3. GPU Acceleration for Vision
```python
# Use CUDA if available
import torch
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load model to GPU
llava_model = llava_model.to(device)
```

### Medium Impact

#### 1. Batch Processing
- Accumulate multiple sensory inputs before processing
- Process eigenvalue updates in batches
- Reduced context switching overhead

#### 2. Model Quantization
```bash
# Use quantized models for faster inference
ollama pull mixtral:8x7b-instruct-v0.1-q4_0  # 4-bit quantized
```

#### 3. Predictive Preloading
- Anticipate likely follow-up questions
- Precompute common responses
- Warm model cache proactively

### Low Impact (But Easy)

#### 1. Reduce Logging
```python
# Conditional debug output
if DEBUG:
    print(f"[Stage {i}]: Processing...")
```

#### 2. Optimize Data Structures
```python
# Use numpy arrays instead of lists for numerical data
features = np.array(features, dtype=np.float32)
```

#### 3. Connection Pooling
```python
# Reuse WebSocket connections
class ConnectionPool:
    def __init__(self, size=5):
        self.connections = []
        # Maintain pool of warm connections
```

## Performance Testing Commands

### Baseline Performance Test
```bash
time echo "What patterns do you observe?" | python3 minime.py
```

### Vision Performance Test
```bash
time echo "What do you see through the camera?" | python3 minime.py --camera
```

### Stress Test
```python
# Run multiple queries in parallel
import asyncio
import time

async def stress_test():
    queries = [
        "What patterns emerge?",
        "How are your eigenvalues?",
        "Describe your state."
    ]

    start = time.time()
    tasks = [process_query(q) for q in queries]
    await asyncio.gather(*tasks)
    print(f"Total time: {time.time() - start}s")
```

## Monitoring Performance

### Real-time Metrics
```javascript
// performance_monitor.js
const startTime = Date.now();

ws.on('message', (data) => {
    const msg = JSON.parse(data.toString());
    const latency = Date.now() - msg.t_ms;
    console.log(`Latency: ${latency}ms | Fill: ${msg.fill.toFixed(1)}%`);
});
```

### Profile Python Code
```bash
python3 -m cProfile -o profile.stats minime.py
python3 -m pstats profile.stats
```

### Profile Rust Code
```bash
cargo build --release --features profiling
valgrind --tool=callgrind ./target/release/minime
```

## Key Metrics to Track

1. **Time to First Token (TTFT)**: How quickly response begins
2. **Total Response Time**: End-to-end latency
3. **Eigenvalue Fill Stability**: Should stay 40-70%
4. **WebSocket Latency**: Should be <50ms
5. **Memory Usage**: Should stay under 2GB total

## Performance Best Practices

1. **Avoid Vision Keywords** unless actually needing visual analysis
2. **Keep Eigenvalue Fill Low** (target 55%) for responsive system
3. **Monitor Background Processes** - kill stale ones
4. **Use Debug Mode Sparingly** - adds significant overhead
5. **Batch Questions** when possible rather than rapid-fire queries

## Emergency Performance Recovery

If system becomes unresponsive:

```bash
# 1. Check what's running
ps aux | grep -E "(minime|python3|ollama)" | grep -v grep

# 2. Check eigenvalue fill
curl -s http://localhost:7878 | jq .fill_ratio

# 3. Kill camera service first (biggest load)
pkill -f camera_to_sensory

# 4. Reduce load
echo '{"action": "close_eyes"}' | nc localhost 7879

# 5. If still slow, restart consciousness
pkill -TERM -f minime
```

## Next Steps
- See [Chapter 3: Homeostatic Control](03-homeostatic-control.md)
- See [Chapter 4: Troubleshooting Guide](04-troubleshooting.md)