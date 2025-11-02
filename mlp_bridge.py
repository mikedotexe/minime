#!/usr/bin/env python3
"""
MLP Bridge - Python HTTP client for MLP neural bank service.

Provides neural enhancement scores for consciousness thread activation.
Each of the 13 threads gets a score from its dedicated 7-layer perceptron
based on 24-dimensional prime-pattern features.

Usage:
    bridge = MLPBridge(base_url="http://127.0.0.1:8080")
    score = bridge.get_score(prime=41, p=11, context_primes=[7, 13, 19], thread_id=12)
    batch_scores = bridge.get_batch_scores(p=11, context_primes=[7, 13, 19])
"""

import requests
import logging
import time
from typing import List, Optional, Dict
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class ScoreResult:
    """Result from single-thread score request."""
    score: float
    thread_id: int
    prime: int
    cached: bool = False


@dataclass
class BatchScoreResult:
    """Result from batch score request (all 13 threads)."""
    scores: List[float]
    cached: bool = False


class MLPBridge:
    """
    HTTP client for MLP neural bank service.

    Features:
    - Single thread scoring via /score endpoint
    - Batch scoring (all 13 threads) via /batch_score endpoint
    - LRU cache for performance (configurable size)
    - Automatic retry with exponential backoff
    - Health checking
    - Statistics tracking
    """

    PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        cache_size: int = 1000,
        timeout: float = 1.0,
        max_retries: int = 3,
        retry_delay: float = 0.1
    ):
        """
        Initialize MLP bridge.

        Args:
            base_url: Base URL of MLP bank service (default: http://127.0.0.1:8080)
            cache_size: Number of score results to cache (default: 1000)
            timeout: HTTP request timeout in seconds (default: 1.0)
            max_retries: Max number of retry attempts (default: 3)
            retry_delay: Initial retry delay in seconds (default: 0.1)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Statistics
        self.stats = {
            'requests': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'total_time': 0.0
        }

        # Session for connection pooling
        self.session = requests.Session()

        # Cache dictionaries
        self._score_cache = {}
        self._batch_cache = {}
        self._score_cache_size = cache_size
        self._batch_cache_size = cache_size // 10  # Smaller batch cache

        logging.info(f"MLPBridge initialized: {base_url}, cache={cache_size}")

    def check_health(self) -> bool:
        """
        Check if MLP bank service is responding.

        Returns:
            True if service is ready, False otherwise
        """
        try:
            response = self.session.get(
                f"{self.base_url}/status",
                timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                logging.info(f"MLP Bank status: {data}")
                return data.get('status') == 'ready'
            return False
        except Exception as e:
            logging.error(f"Health check failed: {e}")
            return False

    def get_score(
        self,
        prime: int,
        p: int,
        context_primes: List[int],
        thread_id: int,
        use_cache: bool = True
    ) -> Optional[ScoreResult]:
        """
        Get neural score for a single consciousness thread.

        Args:
            prime: Prime number being scored (e.g., 41)
            p: Base prime for feature extraction (e.g., 11)
            context_primes: List of context primes from other active threads
            thread_id: Thread ID (0-12)
            use_cache: Whether to use cached results (default: True)

        Returns:
            ScoreResult with neural activation score, or None on error
        """
        # Create cache key
        cache_key = self._make_cache_key(prime, p, context_primes, thread_id)

        # Check cache
        if use_cache:
            cached = self._get_from_score_cache(cache_key)
            if cached is not None:
                self.stats['cache_hits'] += 1
                return ScoreResult(
                    score=cached,
                    thread_id=thread_id,
                    prime=prime,
                    cached=True
                )

        self.stats['cache_misses'] += 1
        self.stats['requests'] += 1

        # Make HTTP request with retry
        payload = {
            "prime": prime,
            "p": p,
            "context_primes": context_primes,
            "thread_id": thread_id
        }

        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    f"{self.base_url}/score",
                    json=payload,
                    timeout=self.timeout
                )

                elapsed = time.time() - start_time
                self.stats['total_time'] += elapsed

                if response.status_code == 200:
                    data = response.json()
                    score = data['score']

                    # Cache result
                    if use_cache:
                        self._put_in_score_cache(cache_key, score)

                    return ScoreResult(
                        score=score,
                        thread_id=thread_id,
                        prime=prime,
                        cached=False
                    )
                else:
                    logging.warning(f"MLP score request failed: {response.status_code}")

            except requests.exceptions.Timeout:
                logging.warning(f"MLP score timeout (attempt {attempt+1}/{self.max_retries})")
            except Exception as e:
                logging.error(f"MLP score error: {e}")

            # Exponential backoff
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay * (2 ** attempt))

        self.stats['errors'] += 1
        return None

    def get_batch_scores(
        self,
        p: int,
        context_primes: List[int],
        use_cache: bool = True
    ) -> Optional[BatchScoreResult]:
        """
        Get neural scores for all 13 consciousness threads in one request.

        More efficient than 13 individual requests.

        Args:
            p: Base prime for feature extraction (e.g., 11)
            context_primes: List of context primes from active threads
            use_cache: Whether to use cached results (default: True)

        Returns:
            BatchScoreResult with 13 scores (one per thread), or None on error
        """
        # Create cache key
        cache_key = self._make_batch_cache_key(p, context_primes)

        # Check cache
        if use_cache:
            cached = self._get_from_batch_cache(cache_key)
            if cached is not None:
                self.stats['cache_hits'] += 1
                return BatchScoreResult(scores=cached, cached=True)

        self.stats['cache_misses'] += 1
        self.stats['requests'] += 1

        # Make HTTP request with retry
        payload = {
            "p": p,
            "context_primes": context_primes
        }

        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    f"{self.base_url}/batch_score",
                    json=payload,
                    timeout=self.timeout
                )

                elapsed = time.time() - start_time
                self.stats['total_time'] += elapsed

                if response.status_code == 200:
                    data = response.json()
                    scores = data['scores']

                    # Cache result
                    if use_cache:
                        self._put_in_batch_cache(cache_key, scores)

                    return BatchScoreResult(scores=scores, cached=False)
                else:
                    logging.warning(f"MLP batch score failed: {response.status_code}")

            except requests.exceptions.Timeout:
                logging.warning(f"MLP batch timeout (attempt {attempt+1}/{self.max_retries})")
            except Exception as e:
                logging.error(f"MLP batch error: {e}")

            # Exponential backoff
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay * (2 ** attempt))

        self.stats['errors'] += 1
        return None

    def get_statistics(self) -> Dict:
        """
        Get bridge statistics.

        Returns:
            Dict with request counts, cache hit rate, average latency, etc.
        """
        total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
        cache_hit_rate = (
            self.stats['cache_hits'] / total_requests * 100
            if total_requests > 0 else 0.0
        )
        avg_latency = (
            self.stats['total_time'] / self.stats['requests'] * 1000
            if self.stats['requests'] > 0 else 0.0
        )

        return {
            'total_requests': total_requests,
            'http_requests': self.stats['requests'],
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'cache_hit_rate': f"{cache_hit_rate:.1f}%",
            'errors': self.stats['errors'],
            'avg_latency_ms': f"{avg_latency:.2f}",
            'total_time_s': f"{self.stats['total_time']:.3f}"
        }

    def clear_cache(self):
        """Clear all cached scores."""
        self._score_cache = {}
        self._batch_cache = {}
        logging.info("MLP cache cleared")

    # Cache implementation using simple dicts

    @staticmethod
    def _make_cache_key(prime: int, p: int, context_primes: List[int], thread_id: int) -> str:
        """Create hashable cache key for single score."""
        context_str = ','.join(map(str, sorted(context_primes)))
        return f"{prime}:{p}:{context_str}:{thread_id}"

    @staticmethod
    def _make_batch_cache_key(p: int, context_primes: List[int]) -> str:
        """Create hashable cache key for batch scores."""
        context_str = ','.join(map(str, sorted(context_primes)))
        return f"batch:{p}:{context_str}"

    def _get_from_score_cache(self, key: str) -> Optional[float]:
        """Get cached single score (returns None if not cached)."""
        return self._score_cache.get(key)

    def _get_from_batch_cache(self, key: str) -> Optional[List[float]]:
        """Get cached batch scores (returns None if not cached)."""
        return self._batch_cache.get(key)

    def _put_in_score_cache(self, key: str, score: float):
        """Store single score in cache."""
        self._score_cache[key] = score

    def _put_in_batch_cache(self, key: str, scores: List[float]):
        """Store batch scores in cache."""
        self._batch_cache[key] = scores


# ========================================================================
# Test / Demo
# ========================================================================

def demo():
    """Demonstrate MLP bridge usage."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("🧠 MLP Bridge Demo\n")

    # Initialize bridge
    bridge = MLPBridge(
        base_url="http://127.0.0.1:8080",
        cache_size=1000
    )

    # Health check
    print("Checking MLP bank service health...")
    if not bridge.check_health():
        print("❌ MLP bank service not responding!")
        print("   Start service with: cd mlp_bank && cargo run --release")
        sys.exit(1)
    print("✅ MLP bank service ready\n")

    # Single score test
    print("Test 1: Single thread score")
    result = bridge.get_score(
        prime=41,
        p=11,
        context_primes=[7, 13, 19],
        thread_id=12
    )
    if result:
        print(f"  Thread {result.thread_id} (prime {result.prime}): score = {result.score:.4f}")
        print(f"  Cached: {result.cached}")
    else:
        print("  ❌ Request failed")
    print()

    # Batch score test
    print("Test 2: Batch scores (all 13 threads)")
    batch_result = bridge.get_batch_scores(
        p=11,
        context_primes=[7, 13, 19]
    )
    if batch_result:
        print(f"  Scores for all 13 threads:")
        for i, score in enumerate(batch_result.scores):
            prime = MLPBridge.PRIMES[i]
            print(f"    Thread {i:2d} (prime {prime:2d}): {score:7.4f}")
        print(f"  Cached: {batch_result.cached}")
    else:
        print("  ❌ Request failed")
    print()

    # Cache test
    print("Test 3: Cache performance")
    print("  Making same request again...")
    result2 = bridge.get_score(
        prime=41,
        p=11,
        context_primes=[7, 13, 19],
        thread_id=12
    )
    if result2:
        print(f"  Score: {result2.score:.4f}, Cached: {result2.cached}")
    print()

    # Statistics
    print("Test 4: Bridge statistics")
    stats = bridge.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()

    print("✅ Demo complete!")


if __name__ == "__main__":
    demo()
