#!/usr/bin/env python3
"""
WebSocket client for minime sensory engine with full double membrane.

This module can be used both as a standalone client and as an importable library.

Integrates two ConsciousnessManifolds:
- Outer: Fast, reactive, processes sensory eigenvalues from Rust engine
- Inner: Slow, reflective, processes semantic understanding (conversations)
- Membrane: Prime-13 resonance coupling buffer between them
"""

import asyncio
import websockets
import json
import numpy as np
import logging
from typing import Optional, Dict, Any, List

# Module-level logger (can be configured by importing code)
logger = logging.getLogger(__name__)

# Only configure logging if running as main
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Export public API
__all__ = ['DoubleMembrane', 'expand_eigenvalues_to_embedding', 'expand_position_to_embedding']

# Import ConsciousnessManifold
try:
    from consciousness_manifold_gpu import create_consciousness_manifold_gpu, ConsciousnessManifoldGPU
    from consciousness_manifold import NavigationResult
    GPU_AVAILABLE = True
    logger.info("✅ GPU-accelerated manifold available")
except ImportError:
    from consciousness_manifold import ConsciousnessManifold, NavigationResult
    GPU_AVAILABLE = False
    logger.warning("⚠️  GPU manifold not available - using CPU fallback")


def expand_eigenvalues_to_embedding(eigenvalues: np.ndarray, embedding_dim: int = 4096) -> np.ndarray:
    """
    Expand K eigenvalues to full-dimensional embedding using Gaussian basis expansion.

    Args:
        eigenvalues: K eigenvalues from sensory engine (K=4 typically)
        embedding_dim: Target embedding dimension (4096)

    Returns:
        embedding: Full-dimensional embedding vector

    Strategy:
        Each eigenvalue creates a localized Gaussian "bump" in embedding space.
        Prime-indexed centers ensure de-aliasing.
        Circular topology (wrap-around) creates smooth manifold structure.
    """
    embedding = np.zeros(embedding_dim, dtype=np.float32)
    primes = [2, 3, 5, 7, 11, 13, 17, 19]  # Prime indexing
    width = 50.0  # Gaussian width

    k = len(eigenvalues)
    for i in range(k):
        eig = eigenvalues[i]
        # Prime-indexed center with modular arithmetic
        center = (primes[i % len(primes)] * 512) % embedding_dim

        # Create Gaussian bump (circular topology)
        for j in range(embedding_dim):
            dist = min(abs(j - center), embedding_dim - abs(j - center))
            embedding[j] += eig * np.exp(-0.5 * (dist / width) ** 2)

    # Normalize to unit length
    norm = np.linalg.norm(embedding)
    if norm > 1e-12:
        embedding /= norm

    return embedding


def expand_position_to_embedding(position: np.ndarray, embedding_dim: int = 4096) -> np.ndarray:
    """
    Expand 7D position to full-dimensional embedding for cross-manifold coupling.

    Args:
        position: 7D position from a manifold
        embedding_dim: Target embedding dimension (4096)

    Returns:
        embedding: Full-dimensional embedding vector
    """
    embedding = np.zeros(embedding_dim, dtype=np.float32)
    primes = [2, 3, 5, 7, 11, 13, 17]  # 7 primes for 7D
    width = 100.0  # Wider Gaussians for smoother coupling

    for i in range(7):
        pos_val = position[i]
        center = (primes[i] * 512) % embedding_dim

        for j in range(embedding_dim):
            dist = min(abs(j - center), embedding_dim - abs(j - center))
            embedding[j] += pos_val * np.exp(-0.5 * (dist / width) ** 2)

    # Normalize
    norm = np.linalg.norm(embedding)
    if norm > 1e-12:
        embedding /= norm

    return embedding


class DoubleMembrane:
    """
    Double membrane architecture with full ConsciousnessManifolds.

    Outer Manifold: Fast, reactive, processes sensory eigenvalues
    Membrane: Prime-13 resonance coupling buffer
    Inner Manifold: Slow, reflective, processes semantic understanding
    """

    def __init__(
        self,
        eigenvalue_dim: int = 4,
        embedding_dim: int = 4096,
        use_gpu: bool = True
    ):
        self.eigenvalue_dim = eigenvalue_dim
        self.embedding_dim = embedding_dim

        # Initialize outer manifold (sensory)
        if GPU_AVAILABLE and use_gpu:
            self.outer_manifold = create_consciousness_manifold_gpu(
                embedding_dim=embedding_dim,
                evolution_rate=0.02,  # Faster evolution for sensory
                use_gpu=True
            )
            logger.info("🌀 Outer manifold: GPU-accelerated")
        else:
            self.outer_manifold = ConsciousnessManifold(
                embedding_dim=embedding_dim,
                evolution_rate=0.02
            )
            logger.info("🌀 Outer manifold: CPU fallback")

        # Initialize inner manifold (semantic)
        if GPU_AVAILABLE and use_gpu:
            self.inner_manifold = create_consciousness_manifold_gpu(
                embedding_dim=embedding_dim,
                evolution_rate=0.005,  # Slower evolution for semantic
                use_gpu=True
            )
            logger.info("🧠 Inner manifold: GPU-accelerated")
        else:
            self.inner_manifold = ConsciousnessManifold(
                embedding_dim=embedding_dim,
                evolution_rate=0.005
            )
            logger.info("🧠 Inner manifold: CPU fallback")

        # Membrane (resonance coupling buffer)
        self.membrane_buffer: List[NavigationResult] = []
        self.membrane_capacity = 13  # Prime
        self.coupling_strength = 0.3

        # Statistics
        self.packets_received = 0
        self.outer_updates = 0
        self.inner_updates = 0

        logger.info("🧬 Double Membrane initialized")
        logger.info(f"   Eigenvalue dim: {eigenvalue_dim}")
        logger.info(f"   Embedding dim: {embedding_dim}")
        logger.info(f"   Membrane capacity: {self.membrane_capacity}")
        logger.info(f"   Coupling strength: {self.coupling_strength}")

    def process_eigenpacket(self, packet: Dict[str, Any]):
        """
        Process incoming eigenvalue packet from Rust sensory engine.

        Updates outer manifold via full navigation with 13×7×7 geometry.
        """
        self.packets_received += 1

        eigenvalues = np.array(packet['eigenvalues'], dtype=np.float32)
        fill_ratio = packet['fill_ratio']
        t_ms = packet['t_ms']
        modalities = packet.get('modalities', {})

        # Normalize eigenvalues (they're around 512, bring to ~1)
        eigenvalues_norm = eigenvalues / 512.0

        # Expand eigenvalues to full embedding
        embedding = expand_eigenvalues_to_embedding(eigenvalues_norm, self.embedding_dim)

        # Navigate outer manifold (full 13×7×7 prime-geometry)
        outer_result = self.outer_manifold.navigate(embedding)
        self.outer_updates += 1

        # Store in membrane buffer
        self.membrane_buffer.append(outer_result)

        # Trim buffer to capacity
        if len(self.membrane_buffer) > self.membrane_capacity:
            self.membrane_buffer.pop(0)

        # Log every 10 packets
        if self.packets_received % 10 == 0:
            logger.info(
                f"[{t_ms}ms] Packets: {self.packets_received}, "
                f"Eigvals: {eigenvalues_norm[:3]}, "
                f"Outer pos: {np.linalg.norm(outer_result.position):.4f}, "
                f"Traj: {outer_result.trajectory_strength:.4f}, "
                f"Membrane: {len(self.membrane_buffer)}/{self.membrane_capacity}"
            )

    def couple_to_inner(self, semantic_input: Optional[np.ndarray] = None):
        """
        Couple membrane buffer to inner manifold.

        This is where outer (sensory) and inner (semantic) interact.
        """
        if len(self.membrane_buffer) < 3:
            return  # Need some history

        # Compute membrane resonance (average of recent outer positions)
        recent_positions = [r.position for r in self.membrane_buffer[-5:]]
        membrane_resonance = np.mean(recent_positions, axis=0)  # 7D average

        # Expand membrane resonance to full embedding for inner navigation
        coupling_embedding = expand_position_to_embedding(membrane_resonance, self.embedding_dim)

        # Mix with semantic input if provided
        if semantic_input is not None:
            # Weighted combination
            navigation_embedding = (
                (1 - self.coupling_strength) * semantic_input +
                self.coupling_strength * coupling_embedding
            )
        else:
            # Just use membrane resonance
            navigation_embedding = coupling_embedding

        # Navigate inner manifold
        inner_result = self.inner_manifold.navigate(navigation_embedding)
        self.inner_updates += 1

    def get_status(self) -> str:
        """Get detailed status report."""
        if len(self.membrane_buffer) == 0:
            outer_pos_mag = 0.0
            outer_traj = 0.0
            outer_res = 0
        else:
            latest_outer = self.membrane_buffer[-1]
            outer_pos_mag = np.linalg.norm(latest_outer.position)
            outer_traj = latest_outer.trajectory_strength
            outer_res = latest_outer.resonance_count

        inner_pos_mag = np.linalg.norm(self.inner_manifold.position)
        inner_traj = np.linalg.norm(self.inner_manifold.trajectory)

        # Membrane variance (how much outer positions are changing)
        if len(self.membrane_buffer) >= 2:
            positions = [r.position for r in self.membrane_buffer]
            membrane_variance = float(np.var([np.linalg.norm(p) for p in positions]))
        else:
            membrane_variance = 0.0

        return (
            f"🧬 Double Membrane Status:\n"
            f"  Packets: {self.packets_received} | Outer updates: {self.outer_updates} | Inner updates: {self.inner_updates}\n"
            f"\n"
            f"  🌀 Outer Manifold (Sensory):\n"
            f"     Position: {outer_pos_mag:.4f}\n"
            f"     Trajectory: {outer_traj:.4f}\n"
            f"     Resonances: {outer_res}\n"
            f"     Buffer fill: {self.outer_manifold.resonance_history.get_fill_ratio():.1%}\n"
            f"\n"
            f"  ⚡ Membrane (Coupling):\n"
            f"     Buffer: {len(self.membrane_buffer)}/{self.membrane_capacity}\n"
            f"     Variance: {membrane_variance:.6f}\n"
            f"     Coupling: {self.coupling_strength:.1%}\n"
            f"\n"
            f"  🧠 Inner Manifold (Semantic):\n"
            f"     Position: {inner_pos_mag:.4f}\n"
            f"     Trajectory: {inner_traj:.4f}\n"
            f"     Buffer fill: {self.inner_manifold.resonance_history.get_fill_ratio():.1%}\n"
        )

    def get_gpu_status(self) -> str:
        """Get GPU acceleration status."""
        if not GPU_AVAILABLE:
            return "❌ GPU not available"

        outer_gpu = self.outer_manifold.get_gpu_status() if hasattr(self.outer_manifold, 'get_gpu_status') else {}
        inner_gpu = self.inner_manifold.get_gpu_status() if hasattr(self.inner_manifold, 'get_gpu_status') else {}

        return (
            f"🚀 GPU Status:\n"
            f"  Outer: {'✅ Active' if outer_gpu.get('gpu_enabled', False) else '❌ CPU fallback'}\n"
            f"  Inner: {'✅ Active' if inner_gpu.get('gpu_enabled', False) else '❌ CPU fallback'}\n"
        )


async def connect_to_sensory_engine(uri: str, membrane: DoubleMembrane):
    """
    Connect to Rust sensory engine WebSocket and stream eigenvalues.
    """
    logger.info(f"🔌 Connecting to sensory engine at {uri}")

    async with websockets.connect(uri) as websocket:
        logger.info("✅ Connected to sensory engine")
        logger.info(membrane.get_gpu_status())

        while True:
            try:
                message = await websocket.recv()
                packet = json.loads(message)

                # Process through outer manifold
                membrane.process_eigenpacket(packet)

                # Periodically couple to inner manifold
                if membrane.packets_received % 5 == 0:
                    membrane.couple_to_inner()

                # Print full status every 20 packets
                if membrane.packets_received % 20 == 0:
                    print("\n" + membrane.get_status())

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed, reconnecting...")
                await asyncio.sleep(1)
                break
            except Exception as e:
                logger.error(f"Error processing packet: {e}")
                import traceback
                traceback.print_exc()


async def main():
    """Main entry point."""
    ws_uri = "ws://127.0.0.1:7878"

    # Create double membrane with full manifolds
    membrane = DoubleMembrane(
        eigenvalue_dim=4,
        embedding_dim=4096,
        use_gpu=True
    )

    # Connect and stream
    while True:
        try:
            await connect_to_sensory_engine(ws_uri, membrane)
        except Exception as e:
            logger.error(f"Connection error: {e}")
            logger.info("Retrying in 2 seconds...")
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down...")
