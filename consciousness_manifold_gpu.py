#!/usr/bin/env python3
"""
GPU-Accelerated Consciousness Manifold

This module provides a GPU-accelerated version of ConsciousnessManifold
using Metal compute shaders for the key operations:
- Prime projection
- Resonance tensor computation
- Position calculation

Falls back to CPU if GPU is not available.
"""

import numpy as np
import logging
from typing import Optional
from dataclasses import dataclass

# Try to import GPU backend
try:
    import metal_consciousness
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False
    logging.warning("Metal consciousness GPU not available - using CPU fallback")

# Import CPU fallback
from consciousness_manifold import (
    ConsciousnessManifold,
    NavigationResult,
    PrimeRingBuffer
)


class ConsciousnessManifoldGPU(ConsciousnessManifold):
    """
    GPU-accelerated consciousness manifold.

    Inherits from ConsciousnessManifold but overrides compute-intensive operations
    to use Metal GPU when available.
    """

    def __init__(
        self,
        embedding_dim: int = 4096,
        resonance_buffer_size: int = 113,
        evolution_rate: float = 0.01,
        use_gpu: bool = True
    ):
        """
        Initialize GPU-accelerated manifold.

        Args:
            embedding_dim: Dimension of input embeddings
            resonance_buffer_size: Size of prime ring buffer
            evolution_rate: How fast geometry matrices evolve
            use_gpu: Use GPU if available (True by default)
        """
        # Initialize parent class
        super().__init__(
            embedding_dim=embedding_dim,
            metal_bridge=None,
            resonance_buffer_size=resonance_buffer_size,
            evolution_rate=evolution_rate
        )

        # Initialize GPU backend if requested and available
        self.use_gpu = use_gpu and GPU_AVAILABLE
        self.gpu = None

        if self.use_gpu:
            try:
                self.gpu = metal_consciousness.PyConsciousnessGPU()
                logging.info("✅ GPU acceleration enabled for ConsciousnessManifold")
            except Exception as e:
                logging.warning(f"Failed to initialize GPU: {e} - using CPU fallback")
                self.use_gpu = False

        if not self.use_gpu:
            logging.info("Using CPU-only ConsciousnessManifold")

    def _project_through_primes(self, embedding: np.ndarray) -> np.ndarray:
        """
        Project embedding through 13 prime-indexed 7×7 geometry matrices.

        GPU-accelerated version.
        """
        if not self.use_gpu or self.gpu is None:
            # Fallback to CPU
            return super()._project_through_primes(embedding)

        # Use GPU
        try:
            # Flatten geometry matrices for GPU
            geometry_flat = np.concatenate([m.flatten() for m in self.geometry_matrices])

            # Run GPU kernel
            views_flat = self.gpu.prime_projection(
                embedding.astype(np.float32),
                geometry_flat.astype(np.float32)
            )

            # Reshape to 13×7
            views_13x7 = views_flat.reshape((13, 7))
            return views_13x7

        except Exception as e:
            logging.warning(f"GPU prime projection failed: {e} - falling back to CPU")
            self.use_gpu = False
            return super()._project_through_primes(embedding)

    def _compute_resonance(self, bases: np.ndarray) -> np.ndarray:
        """
        Compute resonance tensor: 7×7 inner products between bases.

        GPU-accelerated version using optimized tiled kernel.
        """
        if not self.use_gpu or self.gpu is None:
            # Fallback to CPU
            return super()._compute_resonance(bases)

        # Use GPU
        try:
            # Flatten bases
            bases_flat = bases.flatten().astype(np.float32)

            # Run GPU kernel (use tiled version for performance)
            resonance_flat = self.gpu.resonance_tensor(bases_flat, use_tiled=True)

            # Reshape to 7×7
            resonance = resonance_flat.reshape((7, 7))
            return resonance

        except Exception as e:
            logging.warning(f"GPU resonance computation failed: {e} - falling back to CPU")
            self.use_gpu = False
            return super()._compute_resonance(bases)

    def _compute_position(self, bases: np.ndarray, trajectory: np.ndarray) -> np.ndarray:
        """
        Compute position in hyperspace.

        GPU-accelerated version.
        """
        # Check if we need trajectory (before buffer fills)
        if np.linalg.norm(trajectory) < 1e-6:
            # Use first basis as position (CPU is fine for this)
            return bases[0, :].astype(np.float32)

        if not self.use_gpu or self.gpu is None:
            # Fallback to CPU
            return super()._compute_position(bases, trajectory)

        # Use GPU
        try:
            # Flatten inputs
            bases_flat = bases.flatten().astype(np.float32)
            trajectory_flat = trajectory.astype(np.float32)

            # Run GPU kernel
            position = self.gpu.compute_position(bases_flat, trajectory_flat)
            return position

        except Exception as e:
            logging.warning(f"GPU position computation failed: {e} - falling back to CPU")
            self.use_gpu = False
            return super()._compute_position(bases, trajectory)

    def get_gpu_status(self) -> dict:
        """Get GPU acceleration status."""
        return {
            'gpu_available': GPU_AVAILABLE,
            'gpu_enabled': self.use_gpu,
            'gpu_initialized': self.gpu is not None
        }


def create_consciousness_manifold_gpu(
    embedding_dim: int = 4096,
    evolution_rate: float = 0.01,
    use_gpu: bool = True
) -> ConsciousnessManifoldGPU:
    """
    Create a GPU-accelerated consciousness manifold.

    Args:
        embedding_dim: Dimension of embeddings
        evolution_rate: Learning rate for geometry evolution
        use_gpu: Enable GPU acceleration if available

    Returns:
        ConsciousnessManifoldGPU instance
    """
    return ConsciousnessManifoldGPU(
        embedding_dim=embedding_dim,
        resonance_buffer_size=113,  # Prime
        evolution_rate=evolution_rate,
        use_gpu=use_gpu
    )
