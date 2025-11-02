#!/usr/bin/env python3
"""
Seven-Stage Matrix Architecture

A 7x7 connectivity matrix where each stage can communicate with any other stage.
Each matrix has a unique flow pattern based on its prime signature.
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class FlowPattern(Enum):
    """Different flow patterns for matrix processing."""
    SPIRAL = "spiral"          # Outward spiral from center
    WAVE = "wave"              # Wave-like propagation
    CASCADE = "cascade"        # Waterfall down and across
    LIGHTNING = "lightning"    # Zigzag pattern
    VORTEX = "vortex"         # Rotating inward
    CRYSTALLINE = "crystalline" # Symmetric growth
    CHAOTIC = "chaotic"       # Seemingly random but deterministic
    FIBONACCI = "fibonacci"    # Fibonacci spiral
    HARMONIC = "harmonic"     # Standing wave patterns
    QUANTUM = "quantum"       # Superposition/collapse
    FRACTAL = "fractal"       # Self-similar at different scales
    RHYTHMIC = "rhythmic"     # Pulsing/beating pattern
    EMERGENT = "emergent"     # Patterns emerge from interaction


@dataclass
class StageActivation:
    """Represents activation at a particular stage."""
    stage_id: int
    activation_level: float
    semantic_vector: Optional[np.ndarray] = None
    emotional_signature: Dict[str, float] = None
    timestamp: float = 0.0
    metadata: Dict = None


class SevenStageMatrix:
    """
    A 7x7 matrix where each stage can communicate with any other.
    Processing flows through the matrix according to prime-specific patterns.
    """

    STAGE_NAMES = [
        "Perception",      # Stage 1: Initial contact
        "Orientation",     # Stage 2: Context building
        "Elaboration",     # Stage 3: Expansion
        "Synthesis",       # Stage 4: Integration
        "Crystallization", # Stage 5: Clarity
        "Illumination",    # Stage 6: Insight
        "Embodiment"       # Stage 7: Manifestation
    ]

    def __init__(self, matrix_id: int, prime_signature: int):
        self.matrix_id = matrix_id
        self.prime_signature = prime_signature

        # 7x7 connectivity matrix - represents connection strengths
        self.connectivity = np.zeros((7, 7), dtype=float)
        self.activation_state = np.zeros(7, dtype=float)

        # Historical activations for resonance detection
        self.activation_history: List[StageActivation] = []

        # Flow pattern based on prime
        self.flow_pattern = self._determine_flow_pattern(prime_signature)
        self._initialize_connectivity()

        logging.info(f"Matrix {matrix_id} initialized with prime {prime_signature}, "
                    f"pattern: {self.flow_pattern.value}")

    def _determine_flow_pattern(self, prime: int) -> FlowPattern:
        """Map prime signatures to flow patterns."""
        pattern_map = {
            2: FlowPattern.WAVE,
            3: FlowPattern.SPIRAL,
            5: FlowPattern.CASCADE,
            7: FlowPattern.HARMONIC,
            11: FlowPattern.LIGHTNING,
            13: FlowPattern.VORTEX,
            17: FlowPattern.CRYSTALLINE,
            19: FlowPattern.QUANTUM,
            23: FlowPattern.FIBONACCI,
            29: FlowPattern.FRACTAL,
            31: FlowPattern.RHYTHMIC,
            37: FlowPattern.EMERGENT,
            41: FlowPattern.CHAOTIC,
        }
        return pattern_map.get(prime, FlowPattern.SPIRAL)

    def _initialize_connectivity(self):
        """Initialize the connectivity matrix based on flow pattern."""
        if self.flow_pattern == FlowPattern.WAVE:
            # Wave pattern - smooth propagation
            for i in range(7):
                for j in range(7):
                    distance = abs(i - j)
                    self.connectivity[i, j] = np.exp(-distance / 2.0)

        elif self.flow_pattern == FlowPattern.SPIRAL:
            # Spiral pattern - from center outward
            center = 3
            for i in range(7):
                for j in range(7):
                    dist_from_center = np.sqrt((i-center)**2 + (j-center)**2)
                    self.connectivity[i, j] = 1.0 / (1.0 + dist_from_center)

        elif self.flow_pattern == FlowPattern.CASCADE:
            # Cascade - strong downward/rightward flow
            for i in range(7):
                for j in range(7):
                    if j >= i:
                        self.connectivity[i, j] = 0.8 ** (j - i)
                    else:
                        self.connectivity[i, j] = 0.2

        elif self.flow_pattern == FlowPattern.HARMONIC:
            # Harmonic - standing wave patterns
            for i in range(7):
                for j in range(7):
                    # Create harmonic relationships
                    self.connectivity[i, j] = 0.5 + 0.5 * np.cos(np.pi * i * j / 7)

        elif self.flow_pattern == FlowPattern.LIGHTNING:
            # Lightning - zigzag connections
            path = [(0,0), (1,1), (0,2), (2,3), (1,4), (3,5), (2,6)]
            for idx, (i, j) in enumerate(path[:-1]):
                next_i, next_j = path[idx + 1]
                self.connectivity[i, next_j] = 0.9
                self.connectivity[next_i, j] = 0.9

        elif self.flow_pattern == FlowPattern.VORTEX:
            # Vortex - rotating inward
            for i in range(7):
                for j in range(7):
                    angle = np.arctan2(i - 3, j - 3)
                    radius = np.sqrt((i-3)**2 + (j-3)**2)
                    self.connectivity[i, j] = 0.5 + 0.5 * np.sin(angle + radius)

        else:
            # Default: Full connectivity with slight preference for forward flow
            for i in range(7):
                for j in range(7):
                    if i == j:
                        self.connectivity[i, j] = 1.0
                    else:
                        self.connectivity[i, j] = 0.5 + 0.1 * (j > i)

    def process(self, input_activation: StageActivation) -> Dict:
        """
        Process input through the matrix according to flow pattern.
        Returns activation patterns and metadata.
        """
        # Reset activation state
        self.activation_state = np.zeros(7)

        # Set initial activation
        stage_idx = input_activation.stage_id - 1
        self.activation_state[stage_idx] = input_activation.activation_level

        # Process through matrix iterations
        iterations = []
        for iter_num in range(self.prime_signature):
            # Store current state
            iterations.append(self.activation_state.copy())

            # Propagate activation through connectivity matrix
            new_activation = np.zeros(7)
            for i in range(7):
                for j in range(7):
                    new_activation[j] += (self.activation_state[i] *
                                        self.connectivity[i, j] *
                                        self._nonlinearity(self.activation_state[i]))

            # Apply activation function and decay
            self.activation_state = self._apply_activation_function(new_activation)

            # Add noise for emergent behavior
            if self.flow_pattern == FlowPattern.EMERGENT:
                self.activation_state += np.random.normal(0, 0.01, 7)

            # Clip to valid range
            self.activation_state = np.clip(self.activation_state, 0, 1)

        # Store in history
        final_activation = StageActivation(
            stage_id=np.argmax(self.activation_state) + 1,
            activation_level=np.max(self.activation_state),
            semantic_vector=input_activation.semantic_vector,
            emotional_signature=self._calculate_emotional_signature(),
            metadata={
                'pattern': self.flow_pattern.value,
                'iterations': len(iterations),
                'trajectory': iterations
            }
        )
        self.activation_history.append(final_activation)

        return {
            'final_activation': final_activation,
            'stage_activations': self.activation_state,
            'peak_stage': np.argmax(self.activation_state) + 1,
            'total_activation': np.sum(self.activation_state),
            'pattern_metadata': {
                'flow_pattern': self.flow_pattern.value,
                'prime_signature': self.prime_signature,
                'convergence_rate': self._calculate_convergence_rate(iterations)
            }
        }

    def _nonlinearity(self, x: float) -> float:
        """Nonlinear activation function."""
        # Different nonlinearities for different patterns
        if self.flow_pattern in [FlowPattern.QUANTUM, FlowPattern.CHAOTIC]:
            return np.tanh(2 * x)  # Sharp transitions
        elif self.flow_pattern in [FlowPattern.WAVE, FlowPattern.HARMONIC]:
            return 0.5 * (1 + np.sin(np.pi * x))  # Smooth oscillation
        else:
            return 1 / (1 + np.exp(-5 * (x - 0.5)))  # Sigmoid

    def _apply_activation_function(self, activation: np.ndarray) -> np.ndarray:
        """Apply pattern-specific activation function."""
        if self.flow_pattern == FlowPattern.QUANTUM:
            # Quantum collapse - winner takes more
            max_idx = np.argmax(activation)
            result = activation * 0.3
            result[max_idx] = activation[max_idx] * 1.2
            return result
        else:
            # Standard normalization with decay
            return activation / (1 + np.sum(activation)) * 0.95

    def _calculate_emotional_signature(self) -> Dict[str, float]:
        """Calculate emotional signature based on activation pattern."""
        # Map stages to emotional dimensions
        emotion_map = {
            0: ('curiosity', 0.8),
            1: ('focus', 0.7),
            2: ('expansion', 0.9),
            3: ('integration', 0.6),
            4: ('clarity', 0.8),
            5: ('insight', 0.9),
            6: ('satisfaction', 0.7)
        }

        emotions = {}
        for idx, activation in enumerate(self.activation_state):
            if activation > 0.1:
                emotion, base_strength = emotion_map.get(idx, ('neutral', 0.5))
                emotions[emotion] = activation * base_strength

        return emotions

    def _calculate_convergence_rate(self, iterations: List[np.ndarray]) -> float:
        """Calculate how quickly the pattern converges to stable state."""
        if len(iterations) < 2:
            return 1.0

        differences = []
        for i in range(1, len(iterations)):
            diff = np.linalg.norm(iterations[i] - iterations[i-1])
            differences.append(diff)

        return np.mean(differences)

    def get_resonance_signature(self) -> np.ndarray:
        """Get current resonance signature for cross-matrix detection."""
        # Combine activation state with connectivity pattern
        signature = np.concatenate([
            self.activation_state,
            self.connectivity.flatten() * 0.1,  # Weighted connectivity
            [self.prime_signature / 41.0]  # Normalized prime
        ])
        return signature

    def inject_resonance(self, resonance_energy: float, source_stage: int):
        """Inject resonance energy from another matrix."""
        # Add energy with pattern-specific propagation
        injection_point = source_stage - 1
        self.activation_state[injection_point] += resonance_energy

        # Propagate according to pattern
        if self.flow_pattern == FlowPattern.HARMONIC:
            # Harmonic injection creates standing waves
            for i in range(7):
                self.activation_state[i] += resonance_energy * np.cos(np.pi * i / 7)

        # Renormalize
        self.activation_state = np.clip(self.activation_state, 0, 1)