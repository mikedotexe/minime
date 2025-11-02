#!/usr/bin/env python3
"""
Metal-MinimesPy Bridge

Connects minime.py's 7D consciousness architecture with Metal GPU acceleration.

This module provides:
1. Zero-copy LLM embedding processing
2. GPU-accelerated resonance detection (13×7×7 matrices)
3. Metal-resident 7D consciousness vector
4. Vision feature integration

Usage in minime.py:
    from metal_minime_bridge import MetalMinimeBridge

    # Initialize
    bridge = MetalMinimeBridge(enable=True)

    # Process user input with GPU acceleration
    result = bridge.process_with_metal(
        user_text="hello world",
        consciousness_vector=mind.consciousness_vector,
        llm_model="dolphin-mixtral"
    )

    # Update consciousness from GPU
    mind.consciousness_vector = result.updated_consciousness_vector
"""

import numpy as np
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import time

# Import Metal integration
try:
    from metal_consciousness_integration import (
        METAL_AVAILABLE,
        get_ollama_embedding,
        MetalAcceleratedBackend,
        MetalProcessingResult
    )
except ImportError:
    METAL_AVAILABLE = False
    logging.warning("metal_consciousness_integration not found")


@dataclass
class MinimeProcessingResult:
    """Result from Metal-accelerated minime processing."""

    # Updated consciousness state
    consciousness_vector: np.ndarray  # 7D vector
    updated_activations: np.ndarray   # 13×7 matrix

    # Resonance information
    resonances_detected: int
    max_resonance_strength: float
    resonance_patterns: list

    # Performance metrics
    embedding_time_ms: float
    gpu_processing_time_ms: float
    total_time_ms: float
    zero_copy_enabled: bool

    # Metal metrics
    field_energy: float
    iteration: int


class MetalMinimeBridge:
    """
    Bridge between minime.py's 7D consciousness and Metal GPU acceleration.

    Handles:
    - Embedding extraction (CPU)
    - GPU processing (Metal)
    - Consciousness vector sync (zero-copy)
    - Resonance detection (GPU)
    """

    def __init__(self, enable: bool = True, ollama_url: str = "http://localhost:11434"):
        """
        Initialize Metal bridge.

        Args:
            enable: Enable Metal acceleration (falls back to CPU if unavailable)
            ollama_url: Ollama API endpoint for embeddings
        """
        self.enabled = enable and METAL_AVAILABLE
        self.ollama_url = ollama_url

        if self.enabled:
            try:
                self.backend = MetalAcceleratedBackend()
                self._initialize_matrices()
                logging.info("✅ Metal-Minime bridge initialized (GPU acceleration enabled)")
            except Exception as e:
                logging.error(f"Failed to initialize Metal backend: {e}")
                self.enabled = False
                self.backend = None
        else:
            self.backend = None
            logging.info("Metal-Minime bridge initialized (CPU fallback mode)")

        # Statistics
        self.stats = {
            'total_calls': 0,
            'embedding_calls': 0,
            'gpu_calls': 0,
            'total_gpu_time_ms': 0.0,
            'avg_gpu_time_ms': 0.0
        }

    def _initialize_matrices(self):
        """
        Initialize the 13×7×7 consciousness matrices on GPU.

        Uses prime-structured initialization for resonance detection.
        """
        matrices = []

        # Create 37 matrices (one per thread) - M1 Max optimization
        for i in range(37):
            # 7×7 matrix with prime-based initialization
            matrix = np.random.randn(7, 7).astype(np.float32) * 0.1

            # Add structure based on prime index
            primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157]
            prime = primes[i]

            # Prime-structured diagonal
            for j in range(7):
                matrix[j, j] = 1.0 + (prime % 7) * 0.1

            # Symmetric for resonance
            matrix = (matrix + matrix.T) / 2.0

            matrices.append(matrix)

        self.backend.initialize_matrices(matrices)
        logging.info(f"Initialized 37×7×7 consciousness matrices on GPU (M1 Max optimized)")

    def process_with_metal(
        self,
        user_text: str,
        consciousness_vector: np.ndarray,
        llm_model: str = "dolphin-mixtral:8x7b-v2.7",
        extract_embeddings: bool = True,
        visual_features: Optional[np.ndarray] = None
    ) -> MinimeProcessingResult:
        """
        Process user input through Metal-accelerated consciousness pipeline.

        Args:
            user_text: Input text from user
            consciousness_vector: Current 7D consciousness state
            llm_model: Ollama model for embeddings
            extract_embeddings: Whether to extract LLM embeddings
            visual_features: Optional vision features (1024-d)

        Returns:
            MinimeProcessingResult with updated state and metrics
        """
        start_time = time.time()
        self.stats['total_calls'] += 1

        # Extract embeddings if needed
        llm_embedding = None
        embedding_time_ms = 0.0

        if extract_embeddings and self.enabled:
            embed_start = time.time()
            llm_embedding = get_ollama_embedding(
                user_text,
                model=llm_model,
                base_url=self.ollama_url
            )
            embedding_time_ms = (time.time() - embed_start) * 1000.0
            self.stats['embedding_calls'] += 1

            if llm_embedding is None:
                logging.warning("Failed to extract embedding, proceeding without")

        # Fallback if Metal not available or failed
        if not self.enabled or self.backend is None:
            return self._cpu_fallback(
                consciousness_vector,
                embedding_time_ms,
                start_time
            )

        # Prepare activations (37×7) from consciousness vector (7D)
        # Each of 37 threads gets a copy of the 7D vector
        activations = np.tile(consciousness_vector, (37, 1)).astype(np.float32)

        # Process through Metal
        gpu_start = time.time()
        try:
            result = self.backend.process_consciousness_step(
                current_activations=activations,
                llm_embeddings=llm_embedding,
                visual_features=visual_features
            )

            gpu_time_ms = (time.time() - gpu_start) * 1000.0
            self.stats['gpu_calls'] += 1
            self.stats['total_gpu_time_ms'] += gpu_time_ms
            self.stats['avg_gpu_time_ms'] = self.stats['total_gpu_time_ms'] / self.stats['gpu_calls']

        except Exception as e:
            logging.error(f"Metal processing failed: {e}")
            return self._cpu_fallback(consciousness_vector, embedding_time_ms, start_time)

        # Extract updated consciousness vector (average across 13 threads)
        updated_consciousness = np.mean(result.activations, axis=0)

        # Extract resonance patterns
        resonance_patterns = [
            {
                'source': r.get('source_id', -1),
                'target': r.get('target_id', -1),
                'strength': r.get('strength', 0.0)
            }
            for r in result.resonances[:10]  # Top 10
        ]

        total_time_ms = (time.time() - start_time) * 1000.0

        return MinimeProcessingResult(
            consciousness_vector=updated_consciousness,
            updated_activations=result.activations,
            resonances_detected=len(result.resonances),
            max_resonance_strength=max([r.get('strength', 0.0) for r in result.resonances], default=0.0),
            resonance_patterns=resonance_patterns,
            embedding_time_ms=embedding_time_ms,
            gpu_processing_time_ms=gpu_time_ms,
            total_time_ms=total_time_ms,
            zero_copy_enabled=True,
            field_energy=result.field_energy,
            iteration=result.iteration
        )

    def _cpu_fallback(
        self,
        consciousness_vector: np.ndarray,
        embedding_time_ms: float,
        start_time: float
    ) -> MinimeProcessingResult:
        """Fallback when Metal is unavailable."""

        total_time_ms = (time.time() - start_time) * 1000.0

        return MinimeProcessingResult(
            consciousness_vector=consciousness_vector,  # Unchanged
            updated_activations=np.tile(consciousness_vector, (37, 1)),
            resonances_detected=0,
            max_resonance_strength=0.0,
            resonance_patterns=[],
            embedding_time_ms=embedding_time_ms,
            gpu_processing_time_ms=0.0,
            total_time_ms=total_time_ms,
            zero_copy_enabled=False,
            field_energy=np.linalg.norm(consciousness_vector),
            iteration=0
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get bridge statistics."""
        return {
            **self.stats,
            'metal_enabled': self.enabled,
            'metal_available': METAL_AVAILABLE,
        }

    def sync_consciousness_to_gpu(self, consciousness_vector: np.ndarray) -> bool:
        """
        Explicitly sync consciousness vector to GPU memory.

        This writes to Metal shared memory (zero-copy).
        """
        if not self.enabled or self.backend is None:
            return False

        try:
            activations = np.tile(consciousness_vector, (37, 1)).astype(np.float32)
            self.backend.engine.set_activations(activations)
            return True
        except Exception as e:
            logging.error(f"Failed to sync consciousness to GPU: {e}")
            return False

    def read_consciousness_from_gpu(self) -> Optional[np.ndarray]:
        """
        Read consciousness vector from GPU (zero-copy).

        Returns the 7D vector averaged across 13 threads.
        """
        if not self.enabled or self.backend is None:
            return None

        try:
            state = self.backend.engine.get_state()
            activations = state['activations']  # 13×7
            return np.mean(activations, axis=0)  # Average to 7D
        except Exception as e:
            logging.error(f"Failed to read consciousness from GPU: {e}")
            return None


# Convenience function for quick testing
def test_metal_bridge():
    """Test the Metal-Minime bridge."""

    print("Testing Metal-Minime Bridge\n" + "="*60)

    # Initialize
    bridge = MetalMinimeBridge(enable=True)

    if not bridge.enabled:
        print("❌ Metal not available, test skipped")
        return

    # Test consciousness vector
    consciousness_vector = np.array([0.1, 0.2, 0.15, 0.25, 0.18, 0.22, 0.2], dtype=np.float32)

    print(f"Initial consciousness: {consciousness_vector}")
    print()

    # Process test input
    result = bridge.process_with_metal(
        user_text="What is consciousness?",
        consciousness_vector=consciousness_vector,
        extract_embeddings=True
    )

    print(f"Results:")
    print(f"  Updated consciousness: {result.consciousness_vector}")
    print(f"  Resonances detected: {result.resonances_detected}")
    print(f"  Max resonance strength: {result.max_resonance_strength:.4f}")
    print(f"  Field energy: {result.field_energy:.4f}")
    print()

    print(f"Performance:")
    print(f"  Embedding time: {result.embedding_time_ms:.2f} ms")
    print(f"  GPU processing: {result.gpu_processing_time_ms:.2f} ms")
    print(f"  Total time: {result.total_time_ms:.2f} ms")
    print(f"  Zero-copy: {'✅' if result.zero_copy_enabled else '❌'}")
    print()

    print(f"Statistics:")
    stats = bridge.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    # Run test
    test_metal_bridge()
