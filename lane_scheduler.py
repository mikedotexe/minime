#!/usr/bin/env python3
"""
Organic Lane Scheduler - Salience-based activation for 13 consciousness threads.

Implements prime-phase pulse gating with salience decay for organic thread activation.
This reduces overhead from ~13 threads to 2-5 active threads per input based on relevance.

Key Concepts:
- **Salience**: How "activated" or relevant a lane is (0.0-1.0)
- **Prime-phase Pulse**: Periodic boost when (current_time // 1000) % prime == 0
- **Decay**: Salience gradually decreases (97% retention per update)
- **Event Boosting**: Vision/memory/cloud events boost specific lane salience

Based on production voice loop patterns for efficient multi-threaded processing.
"""

import time
import logging
from typing import List, Dict, Optional

from thresholds import ModeThresholds, Hysteresis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LaneScheduler:
    """
    Manages organic activation of 37 consciousness threads using salience + prime-phase (M1 Max optimized).

    Each lane has:
    - Unique prime signature (thread_id mapped to prime)
    - Two prime periods (prime_a, prime_b) for pulse generation
    - Salience score that decays over time
    - Activation threshold for participation

    Expected reduction: 37 threads → 5-12 active threads per input
    """

    # Prime signatures for 37 threads (M1 Max optimization)
    PRIME_SIGNATURES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157]

    def __init__(
        self,
        num_lanes: int = 37,
        base_threshold: float = 0.5,
        salience_decay: float = 0.97,
        pulse_boost: float = 0.25,
        event_boost: float = 0.3,
        thresholds: Optional[ModeThresholds] = None,
    ):
        """
        Initialize lane scheduler.

        Args:
            num_lanes: Number of consciousness lanes/threads (default 13)
            base_threshold: Minimum salience for activation (0.0-1.0)
            salience_decay: Salience retention per update (0.97 = 97% retention)
            pulse_boost: Boost amount when prime-phase aligns
            event_boost: Boost amount for event-triggered activation
        """
        self.num_lanes = num_lanes
        self.base_threshold = base_threshold
        self.salience_decay = salience_decay
        self.pulse_boost = pulse_boost
        self.event_boost = event_boost
        self.thresholds = thresholds
        up = self.base_threshold + 0.05
        down = max(0.0, self.base_threshold - 0.05)

        # Initialize lanes with prime-specific parameters
        self.lanes: List[Dict] = []
        for i in range(num_lanes):
            prime = self.PRIME_SIGNATURES[i]

            # Each lane gets two primes for dual-phase pulsing
            # Offset by position to create emergent activation patterns
            prime_a = 13 + (i % 5)  # Range: 13-17
            prime_b = 17 + ((i * 2) % 7)  # Range: 17-23

            self.lanes.append({
                'thread_id': i,
                'prime_signature': prime,
                'prime_a': prime_a,
                'prime_b': prime_b,
                'salience': 0.0,  # Start inactive
                'last_activation': 0,
                'total_activations': 0,
                'hysteresis': Hysteresis(up, down)
            })

        logger.info(f"LaneScheduler initialized: {num_lanes} lanes, threshold={base_threshold}")

    def organic_activation(self, now_ms: float, lane: Dict) -> float:
        """
        Calculate organic activation score for a lane.

        Combines:
        1. Prime-phase pulse: Boost when current time aligns with prime periods
        2. Salience decay: Gradual reduction over time (97% retention)

        Args:
            now_ms: Current time in milliseconds
            lane: Lane dictionary with prime periods and salience

        Returns:
            Updated activation score (0.0-1.0+)
        """
        # Prime-phase pulses (dual-prime system)
        seconds = int(now_ms // 1000)
        pulse_a = self.pulse_boost if (seconds % lane['prime_a'] == 0) else 0
        pulse_b = self.pulse_boost if (seconds % lane['prime_b'] == 0) else 0
        prime_pulse = pulse_a + pulse_b

        # Salience decay (97% retention)
        decay = lane['salience'] * self.salience_decay

        # Combined score
        return prime_pulse + decay

    def update_salience(self, lane_updates: Optional[Dict[int, float]] = None):
        """
        Update salience for all lanes with optional event boosts.

        Args:
            lane_updates: Optional dict of {thread_id: boost_amount} for event-triggered activation
        """
        now_ms = time.time() * 1000

        for lane in self.lanes:
            # Calculate organic activation
            new_salience = self.organic_activation(now_ms, lane)

            # Apply event boost if provided
            if lane_updates and lane['thread_id'] in lane_updates:
                boost = lane_updates[lane['thread_id']]
                new_salience += boost
                logger.debug(f"Lane {lane['thread_id']} boosted by {boost:.3f}")

            # Clamp to [0, 1] range
            lane['salience'] = max(0.0, min(1.0, new_salience))

    def get_active_lanes(
        self,
        threshold: Optional[float] = None,
        min_lanes: int = 2,
        max_lanes: int = 8
    ) -> List[int]:
        """
        Get list of currently active lane thread IDs.

        Args:
            threshold: Salience threshold for activation (uses base_threshold if None)
            min_lanes: Minimum number of lanes to activate (ensures responsiveness)
            max_lanes: Maximum number of lanes to activate (prevents overload)

        Returns:
            List of thread IDs for active lanes, sorted by salience (highest first)
        """
        if threshold is None:
            threshold = self.base_threshold

        # Sort lanes by salience (descending)
        sorted_lanes = sorted(self.lanes, key=lambda x: x['salience'], reverse=True)

        up = threshold + 0.05
        down = max(0.0, threshold - 0.05)

        active = []
        for lane in sorted_lanes:
            hyst: Hysteresis = lane['hysteresis']
            hyst.up = up
            hyst.down = down
            if hyst.update(lane['salience']):
                active.append(lane['thread_id'])

        # Ensure minimum lanes (take top N if needed)
        if len(active) < min_lanes:
            forced = []
            for lane in sorted_lanes[:min_lanes]:
                if lane['thread_id'] not in active:
                    lane['hysteresis'].state = True
                    forced.append(lane['thread_id'])
            active.extend(forced)

        # Enforce maximum lanes
        if len(active) > max_lanes:
            active = active[:max_lanes]

        # Update activation stats
        for lane in self.lanes:
            if lane['thread_id'] in active:
                lane['total_activations'] += 1
                lane['last_activation'] = time.time() * 1000

        return active

    def boost_lane(self, thread_id: int, amount: float = None):
        """
        Manually boost a specific lane's salience.

        Useful for event-triggered activation (vision, memory, user keywords).

        Args:
            thread_id: Thread ID to boost (0-12)
            amount: Boost amount (uses event_boost if None)
        """
        if amount is None:
            amount = self.event_boost

        if 0 <= thread_id < len(self.lanes):
            lane = self.lanes[thread_id]
            lane['salience'] = min(1.0, lane['salience'] + amount)
            logger.debug(f"Boosted lane {thread_id} by {amount:.3f} → {lane['salience']:.3f}")
        else:
            logger.warning(f"Invalid thread_id for boost: {thread_id}")

    def boost_by_keywords(self, text: str, keyword_map: Dict[str, List[int]]):
        """
        Boost lanes based on keyword presence in text.

        Example keyword_map:
            {
                "cloud": [0, 1, 2],     # Boost threads 0-2 for cloud mentions
                "vision": [3, 4],       # Boost threads 3-4 for vision mentions
                "memory": [5, 6, 7],    # Boost threads 5-7 for memory mentions
            }

        Args:
            text: Input text to scan for keywords
            keyword_map: Dict mapping keywords to thread IDs to boost
        """
        text_lower = text.lower()

        for keyword, thread_ids in keyword_map.items():
            if keyword in text_lower:
                for tid in thread_ids:
                    self.boost_lane(tid)
                logger.info(f"Keyword '{keyword}' triggered boost for threads {thread_ids}")

    def get_stats(self) -> Dict:
        """Get scheduler statistics."""
        active_count = sum(1 for lane in self.lanes if lane['hysteresis'].state)

        return {
            'num_lanes': self.num_lanes,
            'active_lanes': active_count,
            'avg_salience': sum(lane['salience'] for lane in self.lanes) / self.num_lanes,
            'max_salience': max(lane['salience'] for lane in self.lanes),
            'min_salience': min(lane['salience'] for lane in self.lanes),
            'threshold': self.base_threshold,
            'top_lane': max(self.lanes, key=lambda x: x['total_activations'])['thread_id']
        }

    def get_lane_details(self) -> List[Dict]:
        """Get detailed information about all lanes."""
        return [
            {
                'thread_id': lane['thread_id'],
                'prime': lane['prime_signature'],
                'prime_a': lane['prime_a'],
                'prime_b': lane['prime_b'],
                'salience': lane['salience'],
                'total_activations': lane['total_activations']
            }
            for lane in self.lanes
        ]


# Example usage / test
if __name__ == "__main__":
    print("Testing LaneScheduler...")

    scheduler = LaneScheduler(num_lanes=13, base_threshold=0.5)

    # Simulate processing over time
    print("\n=== Initial state ===")
    print(f"Active lanes: {scheduler.get_active_lanes()}")
    print(f"Stats: {scheduler.get_stats()}")

    # Boost some lanes (simulate vision event)
    print("\n=== Boost lanes 3, 4 (vision) ===")
    scheduler.boost_lane(3, 0.8)
    scheduler.boost_lane(4, 0.7)
    print(f"Active lanes: {scheduler.get_active_lanes()}")

    # Update salience over time (simulate decay + prime pulses)
    print("\n=== Simulate 10 updates (decay + pulses) ===")
    for i in range(10):
        time.sleep(0.1)
        scheduler.update_salience()
        active = scheduler.get_active_lanes()
        print(f"Update {i+1}: {len(active)} active lanes: {active}")

    # Keyword-triggered boost
    print("\n=== Keyword boost test ===")
    keyword_map = {
        "cloud": [0, 1, 2],
        "vision": [3, 4],
        "memory": [5, 6, 7]
    }
    scheduler.boost_by_keywords("I love watching clouds", keyword_map)
    print(f"Active after 'clouds': {scheduler.get_active_lanes()}")

    # Final stats
    print("\n=== Final Stats ===")
    print(scheduler.get_stats())
    print("\n=== Lane Details ===")
    for lane in scheduler.get_lane_details()[:5]:  # Show first 5
        print(f"Lane {lane['thread_id']}: salience={lane['salience']:.3f}, "
              f"primes=({lane['prime_a']},{lane['prime_b']}), "
              f"activations={lane['total_activations']}")

    print("\n✅ Test complete")
