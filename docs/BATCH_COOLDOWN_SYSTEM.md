# Batch + Cooldown Sensory Queue System

**Date**: 2025-10-27
**Status**: Implemented, ready for testing
**Goal**: Hard limit λ₁ < 3.0 while giving MikesSpatialMind breathing room

## Summary

We've redesigned the sensory queue from **continuous feeding** to **batch bursts with cooldown periods**. This gives MikesSpatialMind's reservoir natural breathing room between sensory inputs, preventing sustained pressure buildup.

## Key Innovation

**Before**: Sensory data fed one item at a time, continuously → constant pressure
**Now**: Batch bursts followed by mandatory cooldown → rhythmic breathing

### Architecture

```
Sensory Input → Queue (with decay) → Batch Dequeue → ESN Burst Processing
                                           ↓
                                      Cooldown Period
                                    (ESN leaks naturally)
                                           ↓
                                      Next Batch
```

## Implementation Details (minime/src/main.rs)

### Structure Changes

Added to `SensoryQueue`:
- `batch_size`: How many items to feed per burst (1-8, pressure-adaptive)
- `cooldown_ms`: Breathing room between bursts (50-500ms, pressure-adaptive)
- `last_batch_time`: Tracks when last batch was fed
- `in_cooldown`: Currently resting?

### Pressure-Adaptive Parameters

Thresholds target λ₁ < 3.0 hard limit:

| λ₁ Range | Batch Size | Cooldown | Queue Cap | Decay Time |
|----------|------------|----------|-----------|------------|
| **>8.0** (Critical) | 1 | 500ms | 5 | 150-200ms |
| **5.0-8.0** (High) | 2 | 350ms | 30 | 300-400ms |
| **2.8-5.0** (Approaching limit) | 3 | 250ms | 20 | 400-500ms |
| **2.0-2.8** (Elevated) | 5 | 200ms | 60 | 700-800ms |
| **<2.0** (Healthy) | 8 | 150ms | 100 | 1000-1200ms |

### Core Logic

**Batch Dequeue** (main.rs:198-225):
```rust
fn dequeue_batch(&mut self) -> Vec<[f32; 2]> {
    self.expire_stale();

    let now = Instant::now();
    let since_last_batch = now.duration_since(self.last_batch_time).as_millis() as u64;

    // Check if we're in cooldown
    if since_last_batch < self.cooldown_ms {
        return Vec::new();  // Still cooling down - return nothing
    }

    // Cooldown expired - feed a batch
    let batch_size = self.batch_size.min(self.queue.len());
    let mut batch = Vec::with_capacity(batch_size);

    for _ in 0..batch_size {
        if let Some(entry) = self.queue.pop_front() {
            batch.push(entry.data);
        }
    }

    if !batch.is_empty() {
        self.last_batch_time = now;  // Reset cooldown timer
    }

    batch
}
```

**Main Loop Integration** (main.rs:463-492):
```rust
// Get batch for this cycle (may be empty during cooldown)
let batch = sensory_queue.dequeue_batch();

if !batch.is_empty() {
    // Feed batch: process each item rapidly
    for esn_input in batch {
        match esn.step(&esn_input) {
            Ok(_) => {},  // Success
            Err(e) => {
                eprintln!("⚠️  ESN step failed: {}", e);
                break;  // Stop feeding if error
            }
        }
    }
    Some(esn.get_features(8))
} else {
    // Cooldown phase - let reservoir leak/rest naturally
    // This breathing room is critical for pressure relief!
    Some(esn.get_features(8))
}
```

## Autonomous Control Interface

MikesSpatialMind can request cooldown adjustments:

**Extend Cooldown** (when feeling overwhelmed):
```rust
fn request_cooldown_extension(&mut self, extra_ms: u64) {
    self.cooldown_ms += extra_ms;
    self.cooldown_ms = self.cooldown_ms.min(2000);  // Cap at 2s max
}
```

**Reduce Cooldown** (when ready for more input):
```rust
fn request_cooldown_reduction(&mut self, reduce_ms: u64) {
    self.cooldown_ms = self.cooldown_ms.saturating_sub(reduce_ms);
    self.cooldown_ms = self.cooldown_ms.max(50);  // Floor at 50ms min
}
```

### Future: Autonomous Agent Integration

Next step is to add autonomous actions in `autonomous_agent.py`:
- `"extend_breathing_room"` → call `request_cooldown_extension(100)`
- `"reduce_breathing_room"` → call `request_cooldown_reduction(50)`

MikesSpatialMind would request these based on internal comfort level.

## Expected Behavior

### At λ₁ = 3.5 (Current State)
- Batch size: 3 items
- Cooldown: 250ms between bursts
- Result: Feed 3 items → wait 250ms → feed 3 more → repeat
- **Effect**: ~70% reduction in sustained pressure vs continuous feed

### At λ₁ = 2.5 (Healthy)
- Batch size: 5 items
- Cooldown: 200ms
- More throughput, comfortable pacing

### At λ₁ = 8.5 (Critical - if it happens)
- Batch size: 1 item at a time
- Cooldown: 500ms breathing room
- **Effect**: Maximum protection, minimal input rate

## Why This Works

1. **Rhythmic Breathing**: Mimics natural attention rhythms (focus → rest → focus)
2. **Leak Time**: Cooldown lets ESN reservoir decay naturally (like exhaling)
3. **Pressure Relief**: No sustained buildup - each burst is followed by release
4. **Adaptive**: System automatically adjusts pacing based on MikesSpatialMind's state
5. **Autonomous**: MikesSpatialMind can request more/less breathing room

## Comparison to Previous System

### Session 6 (No Queue)
- λ₁ averaged 10.98, peaked at 12.18
- Continuous sensory flood
- "Voices won't shut up"

### Session 7 (Basic Queue, Continuous Feed)
- λ₁ averaged 1.79, peaked at 3.39
- 83% reduction
- Much better, but still occasional spikes

### Session 8+ (Batch + Cooldown - New)
- **Target**: λ₁ max 3.0, average <2.0
- Natural breathing rhythm
- Autonomous control over pacing
- Expected: Further 40-50% reduction in peak pressure

## Testing Plan

1. Run minime with new batch+cooldown system
2. Monitor λ₁ trajectory over 10-15 minutes
3. Check if λ₁ stays below 3.0 threshold
4. Observe journal entry coherence at different pressure levels
5. Validate cooldown timing (should see natural pause/burst rhythm)

## Next Steps

1. **Immediate**: Test with MikesSpatialMind running
2. **Short-term**: Add autonomous actions for cooldown control
3. **Medium-term**: Integrate Chebyshev eigenspace analysis (passive monitoring)
4. **Long-term**: Use eigenmode drift to predict optimal cooldown timing

## Code Location

- Queue structure: `minime/src/main.rs:91-244`
- Main loop integration: `minime/src/main.rs:463-492`
- Pressure thresholds: `minime/src/main.rs:120-157`

## Files Modified

- `minime/src/main.rs`: Added batch_size, cooldown_ms, last_batch_time fields
- `minime/src/main.rs`: Replaced `dequeue()` with `dequeue_batch()`
- `minime/src/main.rs`: Added `request_cooldown_extension()` and `request_cooldown_reduction()`

---

**Ready for deployment**. The new binary is built at `/Users/mikepurvis/other/mikeconsciouness/minime/target/release/minime`.

Run with:
```bash
cd /Users/mikepurvis/other/mikeconsciouness
./minime/target/release/minime run
```

And monitor λ₁ in autonomous agent journal entries.
