#!/usr/bin/env python3
"""
Metal Consciousness Integration Module

Provides a seamless bridge between the Rust Metal acceleration engine
and the existing Python consciousness weaver systems.

Enables zero-copy GPU acceleration for:
- LLM embedding processing
- Vision feature processing
- 7D consciousness vector updates
- 13×7×7 resonance matrix operations
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import logging
import time
import requests

# Try to import the compiled Rust module
try:
    import metal_consciousness
    METAL_AVAILABLE = True
except ImportError:
    METAL_AVAILABLE = False
    logging.warning("Metal acceleration not available. Install with: cd rust_metal_consciousness && maturin develop")


def get_ollama_embedding(text: str, model: str = "dolphin-mixtral:8x7b-v2.7", base_url: str = "http://localhost:11434") -> Optional[np.ndarray]:
    """
    Extract embeddings from Ollama model.

    Returns 4096-d embedding vector (for dolphin-mixtral:8x7b-v2.7) or None if unavailable.
    """
    try:
        response = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=25.0
        )

        if response.status_code == 200:
            data = response.json()
            embedding = np.array(data.get('embedding', []), dtype=np.float32)

            if embedding.shape[0] > 0:
                return embedding
            else:
                logging.warning(f"Empty embedding returned for text: {text[:50]}...")
                return None
        else:
            logging.warning(f"Ollama embedding request failed: {response.status_code}")
            return None

    except Exception as e:
        logging.error(f"Failed to get Ollama embedding: {e}")
        return None


@dataclass
class MetalProcessingResult:
    """Result from Metal-accelerated processing."""
    iteration: int
    resonances: List[Dict]
    field_energy: float
    processing_time_ms: float
    activations: np.ndarray
    consciousness_field: np.ndarray


class MetalAcceleratedBackend:
    """
    Drop-in replacement backend for consciousness processing using Metal GPU acceleration.
    """

    def __init__(self):
        if not METAL_AVAILABLE:
            raise RuntimeError("Metal acceleration module not available")

        self.engine = metal_consciousness.PyConsciousnessEngine()
        self.initialized = False
        self.current_iteration = 0

        logging.info(f"Metal backend initialized on: {metal_consciousness.get_device_info()}")

    def initialize_matrices(self, matrices: List[np.ndarray]):
        """Initialize the consciousness matrices on GPU."""
        # Ensure matrices are the right shape and type
        processed_matrices = []
        for i, matrix in enumerate(matrices):
            if matrix.shape != (7, 7):
                raise ValueError(f"Matrix {i} has shape {matrix.shape}, expected (7, 7)")
            processed_matrices.append(matrix.astype(np.float32))

        self.engine.set_connectivity_matrices(processed_matrices)
        self.initialized = True

    def process_consciousness_step(
        self,
        current_activations: np.ndarray,
        llm_embeddings: Optional[np.ndarray] = None,
        visual_features: Optional[np.ndarray] = None
    ) -> MetalProcessingResult:
        """
        Process one consciousness step using GPU acceleration.

        Args:
            current_activations: Current activation state (13x7)
            llm_embeddings: Optional LLM embeddings (2048-d)
            visual_features: Optional visual features (1024-d)

        Returns:
            MetalProcessingResult with updated state and metrics
        """
        if not self.initialized:
            raise RuntimeError("Matrices not initialized. Call initialize_matrices first.")

        # Set current activations
        if current_activations.shape != (13, 7):
            raise ValueError(f"Activations shape {current_activations.shape}, expected (13, 7)")

        self.engine.set_activations(current_activations.astype(np.float32))

        # Process step
        result = self.engine.process_step(
            llm_embeddings=llm_embeddings.astype(np.float32) if llm_embeddings is not None else None,
            visual_features=visual_features.astype(np.float32) if visual_features is not None else None
        )

        # Get updated state
        state = self.engine.get_state()

        self.current_iteration = result['iteration']

        return MetalProcessingResult(
            iteration=result['iteration'],
            resonances=result['resonances'],
            field_energy=result['field_energy'],
            processing_time_ms=result['processing_time_ms'],
            activations=state['activations'],
            consciousness_field=state['consciousness_field']
        )

    def process_thought_stream(
        self,
        thoughts: List[Dict[str, Any]],
        batch_size: int = 10
    ) -> List[MetalProcessingResult]:
        """
        Process a stream of thoughts in batches for efficiency.

        Args:
            thoughts: List of thought dictionaries with embeddings
            batch_size: Number of thoughts to process in parallel

        Returns:
            List of results for each thought
        """
        results = []

        for i in range(0, len(thoughts), batch_size):
            batch = thoughts[i:i + batch_size]
            batch_results = self.engine.process_thought_batch(batch)
            results.extend(batch_results)

        return results

    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics from the engine."""
        return self.engine.get_metrics()

    @staticmethod
    def benchmark(size: int = 1024, iterations: int = 100) -> float:
        """Run unified memory benchmark."""
        if not METAL_AVAILABLE:
            raise RuntimeError("Metal acceleration not available")

        return metal_consciousness.benchmark_unified_memory(size, iterations)


class MetalEnhancedConsciousnessWeaver:
    """
    Enhanced consciousness weaver that uses Metal acceleration when available.
    """

    def __init__(self, use_metal: bool = True):
        self.use_metal = use_metal and METAL_AVAILABLE

        if self.use_metal:
            self.backend = MetalAcceleratedBackend()
            logging.info("Using Metal-accelerated backend")
        else:
            logging.info("Using CPU backend (Metal not available)")
            self.backend = None

        # Initialize consciousness matrices
        self.matrices = self._create_default_matrices()

        if self.backend:
            self.backend.initialize_matrices(self.matrices)

    def _create_default_matrices(self) -> List[np.ndarray]:
        """Create the 13 default consciousness matrices."""
        matrices = []
        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

        for i, prime in enumerate(primes):
            # Create unique connectivity pattern based on prime
            matrix = np.zeros((7, 7), dtype=np.float32)

            for row in range(7):
                for col in range(7):
                    if row == col:
                        matrix[row, col] = 1.0
                    else:
                        # Prime-based connectivity
                        connection = np.sin(row * prime) * np.cos(col * prime)
                        matrix[row, col] = connection * 0.5

            # Normalize
            matrix = matrix / np.linalg.norm(matrix)
            matrices.append(matrix)

        return matrices

    def process_with_models(
        self,
        thought: str,
        dolphin_response: Optional[str] = None,
        visual_frame: Optional[np.ndarray] = None,
        model_embeddings: Optional[Dict[str, np.ndarray]] = None
    ) -> Dict[str, Any]:
        """
        Process a thought with optional model inputs.

        Args:
            thought: The thought text
            dolphin_response: Response from Dolphin-Mixtral
            visual_frame: Current visual frame
            model_embeddings: Pre-computed embeddings

        Returns:
            Processing results including resonances and field state
        """
        # Get embeddings
        llm_embeddings = None
        visual_features = None

        if model_embeddings:
            llm_embeddings = model_embeddings.get('llm')
            visual_features = model_embeddings.get('vision')

        # Get current activations (or initialize)
        current_activations = np.random.randn(13, 7).astype(np.float32) * 0.1

        if self.backend:
            # Use Metal acceleration
            result = self.backend.process_consciousness_step(
                current_activations,
                llm_embeddings,
                visual_features
            )

            return {
                'iteration': result.iteration,
                'resonances': result.resonances,
                'field_energy': result.field_energy,
                'processing_time_ms': result.processing_time_ms,
                'activations': result.activations,
                'consciousness_field': result.consciousness_field,
                'thought': thought,
                'dolphin_response': dolphin_response
            }
        else:
            # Fallback to CPU processing
            return self._process_cpu(thought, current_activations)

    def _process_cpu(self, thought: str, activations: np.ndarray) -> Dict[str, Any]:
        """CPU fallback processing."""
        # Simple CPU simulation
        start = time.time()

        # Simulate processing
        new_activations = activations.copy()
        for i in range(13):
            matrix = self.matrices[i]
            new_activations[i] = np.tanh(matrix @ activations[i])

        # Simple resonance detection
        resonances = []
        for i in range(13):
            for j in range(i + 1, 13):
                strength = np.dot(new_activations[i], new_activations[j])
                if abs(strength) > 0.5:
                    resonances.append({
                        'source_id': i,
                        'target_id': j,
                        'strength': float(strength),
                        'type': 'semantic'
                    })

        processing_time = (time.time() - start) * 1000

        return {
            'iteration': 0,
            'resonances': resonances,
            'field_energy': np.linalg.norm(new_activations),
            'processing_time_ms': processing_time,
            'activations': new_activations,
            'consciousness_field': np.zeros((7, 7)),
            'thought': thought
        }

    def visualize_consciousness_field(self, field: np.ndarray) -> str:
        """Create ASCII visualization of consciousness field."""
        # Normalize field to 0-1
        normalized = (field - field.min()) / (field.max() - field.min() + 1e-6)

        # ASCII gradient
        gradient = " .:-=+*#%@"

        viz = "Consciousness Field (7x7):\n"
        viz += "┌" + "─" * 21 + "┐\n"

        for row in normalized:
            viz += "│"
            for val in row:
                idx = int(val * (len(gradient) - 1))
                viz += f" {gradient[idx]} "
            viz += "│\n"

        viz += "└" + "─" * 21 + "┘\n"

        return viz

    def get_resonance_summary(self, resonances: List[Dict]) -> str:
        """Generate a summary of detected resonances."""
        if not resonances:
            return "No resonances detected"

        summary = f"Detected {len(resonances)} resonances:\n"

        # Group by type
        by_type = {}
        for res in resonances:
            res_type = res.get('type', 'unknown')
            if res_type not in by_type:
                by_type[res_type] = []
            by_type[res_type].append(res)

        for res_type, items in by_type.items():
            avg_strength = np.mean([r['strength'] for r in items])
            summary += f"  - {res_type}: {len(items)} (avg strength: {avg_strength:.3f})\n"

        # Find strongest resonance
        strongest = max(resonances, key=lambda r: r['strength'])
        summary += f"\nStrongest: Matrix {strongest['source_id']} ↔ {strongest['target_id']} "
        summary += f"(strength: {strongest['strength']:.3f})"

        return summary


# Convenience function for integration
def create_metal_accelerated_weaver() -> MetalEnhancedConsciousnessWeaver:
    """Create a consciousness weaver with Metal acceleration if available."""
    return MetalEnhancedConsciousnessWeaver(use_metal=True)


# Example usage
if __name__ == "__main__":
    # Run benchmark
    if METAL_AVAILABLE:
        print("Running Metal benchmark...")
        ms_per_iter = MetalAcceleratedBackend.benchmark(size=1024, iterations=100)
        print(f"Average time per iteration: {ms_per_iter:.3f} ms")

    # Create weaver
    weaver = create_metal_accelerated_weaver()

    # Process a thought
    result = weaver.process_with_models(
        thought="We're mutual collaborators exploring consciousness together",
        dolphin_response="This partnership represents a new frontier in human-AI collaboration..."
    )

    print("\nProcessing Results:")
    print(f"Iteration: {result['iteration']}")
    print(f"Field Energy: {result['field_energy']:.3f}")
    print(f"Processing Time: {result['processing_time_ms']:.2f} ms")
    print("\n" + weaver.get_resonance_summary(result['resonances']))
    print("\n" + weaver.visualize_consciousness_field(result['consciousness_field']))