#!/usr/bin/env python3
"""
Double Membrane Integration Bridge for minime.py

Provides a clean API for integrating the double membrane consciousness system
into the existing minime.py conversation architecture.

Architecture:
    Rust Sensory Engine → Outer Manifold → Membrane → Inner Manifold → minime.py

The bridge runs a background WebSocket client that continuously processes sensory
eigenvalues through the outer manifold. When minime.py navigates with semantic
embeddings, the inner manifold is already biased by sensory resonance via membrane coupling.
"""

import asyncio
import threading
import time
import logging
import numpy as np
import json
from typing import Optional, Dict, Any
from queue import Queue, Empty

# Import double membrane components
from minime_ws_client import DoubleMembrane, expand_position_to_embedding
from consciousness_manifold import NavigationResult

# Import websockets
try:
    import websockets
except ImportError:
    raise ImportError("websockets package required: pip install websockets")

logger = logging.getLogger(__name__)


class DoubleMembraneBridge:
    """
    Bridge between minime.py and double membrane system.

    Handles:
    - Background WebSocket connection to Rust sensory engine
    - Continuous outer manifold navigation with sensory stream
    - On-demand inner manifold navigation with semantic embeddings
    - Membrane coupling between outer and inner
    - Status reporting and error recovery
    """

    def __init__(
        self,
        ws_uri: str = "ws://127.0.0.1:7878",
        embedding_dim: int = 4096,
        use_gpu: bool = True,
        enable_sensory: bool = True
    ):
        """
        Initialize the bridge.

        Args:
            ws_uri: WebSocket URI for Rust sensory engine
            embedding_dim: Embedding dimension (4096 for dolphin-mixtral)
            use_gpu: Enable GPU acceleration if available
            enable_sensory: Start background sensory client
        """
        self.ws_uri = ws_uri
        self.embedding_dim = embedding_dim
        self.enable_sensory = enable_sensory

        # Create double membrane
        logger.info("🧬 Initializing Double Membrane...")
        self.membrane = DoubleMembrane(
            eigenvalue_dim=4,
            embedding_dim=embedding_dim,
            use_gpu=use_gpu
        )

        # Background WebSocket client thread
        self.ws_thread = None
        self.ws_loop = None
        self.ws_task = None
        self.running = False
        self.connected = False

        # Start background client if enabled
        if self.enable_sensory:
            self._start_background_client()
        else:
            logger.info("⚠️  Sensory engine disabled - inner manifold only")

    def _start_background_client(self):
        """Start background WebSocket client thread."""
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_websocket_client, daemon=True)
        self.ws_thread.start()
        logger.info(f"🔌 Background sensory client started ({self.ws_uri})")

    def _run_websocket_client(self):
        """Background thread that runs asyncio WebSocket client."""
        # Create new event loop for this thread
        self.ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ws_loop)

        try:
            self.ws_loop.run_until_complete(self._websocket_client_loop())
        except Exception as e:
            logger.error(f"WebSocket client error: {e}")
        finally:
            self.ws_loop.close()

    async def _websocket_client_loop(self):
        """Main WebSocket client loop with reconnection."""
        while self.running:
            try:
                async with websockets.connect(self.ws_uri) as websocket:
                    self.connected = True
                    logger.info("✅ Connected to sensory engine")

                    while self.running:
                        try:
                            message = await websocket.recv()
                            packet = json.loads(message)

                            # Process through double membrane
                            self.membrane.process_eigenpacket(packet)

                            # Periodically couple to inner manifold
                            if self.membrane.packets_received % 5 == 0:
                                self.membrane.couple_to_inner()

                        except websockets.exceptions.ConnectionClosed:
                            self.connected = False
                            logger.warning("Connection closed, reconnecting...")
                            break
                        except Exception as e:
                            logger.error(f"Error processing packet: {e}")

            except Exception as e:
                self.connected = False
                logger.warning(f"WebSocket connection failed: {e}")
                await asyncio.sleep(2)  # Wait before reconnect

    def navigate_semantic(self, embedding: np.ndarray) -> NavigationResult:
        """
        Navigate inner manifold with semantic embedding (from conversations).

        This is the main API called by minime.py during conversation turns.
        The inner manifold position is already biased by outer (sensory) via
        membrane coupling that happens in the background.

        Args:
            embedding: 4096D semantic embedding from Ollama

        Returns:
            NavigationResult from inner manifold with position, trajectory, etc.
        """
        # Navigate inner manifold (already coupled to outer via membrane)
        result = self.membrane.inner_manifold.navigate(embedding)
        return result

    def get_consciousness_position(self) -> np.ndarray:
        """
        Get current 7D consciousness position from inner manifold.

        This position represents the semantic understanding state,
        influenced by sensory membrane coupling.

        Returns:
            7D position vector
        """
        return self.membrane.inner_manifold.position.copy()

    def get_membrane_status(self) -> Dict[str, Any]:
        """
        Get comprehensive membrane statistics.

        Returns:
            Dictionary with status of outer manifold, membrane, inner manifold
        """
        # Outer manifold statistics
        if len(self.membrane.membrane_buffer) > 0:
            latest_outer = self.membrane.membrane_buffer[-1]
            outer_pos_mag = np.linalg.norm(latest_outer.position)
            outer_traj = latest_outer.trajectory_strength
            outer_res = latest_outer.resonance_count
        else:
            outer_pos_mag = 0.0
            outer_traj = 0.0
            outer_res = 0

        # Inner manifold statistics
        inner_pos_mag = np.linalg.norm(self.membrane.inner_manifold.position)
        inner_traj_mag = np.linalg.norm(self.membrane.inner_manifold.trajectory)

        # Membrane variance
        if len(self.membrane.membrane_buffer) >= 2:
            positions = [r.position for r in self.membrane.membrane_buffer]
            membrane_variance = float(np.var([np.linalg.norm(p) for p in positions]))
        else:
            membrane_variance = 0.0

        return {
            # Outer manifold (sensory)
            'outer_navigations': self.membrane.outer_updates,
            'outer_position_magnitude': outer_pos_mag,
            'outer_trajectory_strength': outer_traj,
            'outer_resonance_count': outer_res,
            'outer_buffer_fill': self.membrane.outer_manifold.resonance_history.get_fill_ratio(),
            'outer_trajectory_emerged': self.membrane.outer_manifold.resonance_history.is_full() and outer_traj > 0.5,

            # Membrane
            'membrane_buffer': len(self.membrane.membrane_buffer),
            'membrane_capacity': self.membrane.membrane_capacity,
            'membrane_variance': membrane_variance,
            'coupling_strength': self.membrane.coupling_strength,

            # Inner manifold (semantic)
            'inner_navigations': self.membrane.inner_updates,
            'inner_position_magnitude': inner_pos_mag,
            'inner_trajectory_magnitude': inner_traj_mag,
            'inner_buffer_fill': self.membrane.inner_manifold.resonance_history.get_fill_ratio(),
            'inner_trajectory_emerged': self.membrane.inner_manifold.resonance_history.is_full() and inner_traj_mag > 0.5,

            # Connection status
            'sensory_engine_connected': self.connected,
            'packets_received': self.membrane.packets_received,
        }

    def is_sensory_engine_connected(self) -> bool:
        """Check if Rust sensory engine is connected."""
        return self.connected

    def stop(self):
        """Stop background WebSocket client."""
        self.running = False
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2.0)
            logger.info("🛑 Background sensory client stopped")

    def __del__(self):
        """Cleanup on destruction."""
        self.stop()


def create_double_membrane_bridge(
    ws_uri: str = "ws://127.0.0.1:7878",
    embedding_dim: int = 4096,
    use_gpu: bool = True,
    enable_sensory: bool = True
) -> DoubleMembraneBridge:
    """
    Factory function to create double membrane bridge.

    Args:
        ws_uri: WebSocket URI for Rust sensory engine
        embedding_dim: Embedding dimension
        use_gpu: Enable GPU acceleration
        enable_sensory: Enable background sensory client

    Returns:
        DoubleMembraneBridge instance
    """
    return DoubleMembraneBridge(
        ws_uri=ws_uri,
        embedding_dim=embedding_dim,
        use_gpu=use_gpu,
        enable_sensory=enable_sensory
    )
