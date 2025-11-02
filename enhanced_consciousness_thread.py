#!/usr/bin/env python3
"""
Enhanced Consciousness Thread with Matrix Integration

Each thread now contains its own seven-stage matrix and participates
in harmonic resonance detection across the 13-thread system.
"""

import numpy as np
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

from seven_stage_matrix import SevenStageMatrix, StageActivation
from harmonic_resonance import HarmonicResonanceEngine, ResonanceEvent


@dataclass
class ThreadActivation:
    """Enhanced activation data including resonance information."""
    thread_id: int
    prime_signature: int
    activation_level: float
    confidence: float
    stage_results: List[Dict]
    dominant_stage: int
    growth_amount: float
    interrupt_priority: float
    matrix_output: Dict
    resonances: List[ResonanceEvent]
    meta_cognition: Optional[str] = None


class EnhancedConsciousnessThread:
    """
    Consciousness thread with integrated seven-stage matrix and resonance detection.
    """

    PRIME_SIGNATURES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

    def __init__(self, thread_id: int, mind, verbose: bool = False):
        """Initialize enhanced consciousness thread with matrix."""
        if thread_id < 0 or thread_id >= len(self.PRIME_SIGNATURES):
            raise ValueError(f"thread_id must be 0-12, got {thread_id}")

        self.thread_id = thread_id
        self.prime_signature = self.PRIME_SIGNATURES[thread_id]
        self.mind = mind
        self.verbose = verbose

        # Initialize the seven-stage matrix
        self.matrix = SevenStageMatrix(thread_id, self.prime_signature)

        # Keep reference to original processor for compatibility
        from minime import ParallelSevenStageProcessor
        self.processor = ParallelSevenStageProcessor(mind, verbose, thread_id)

        # Thread-local state
        self.total_activations = 0
        self.resonance_history = []
        self.meta_cognitive_buffer = []

        # Activation pattern based on prime
        self.activation_pattern = self._generate_prime_pattern()

        logging.info(f"Enhanced Thread {thread_id} initialized with prime {self.prime_signature}, "
                    f"matrix pattern: {self.matrix.flow_pattern.value}")

    def _generate_prime_pattern(self) -> np.ndarray:
        """Generate unique activation pattern based on prime signature."""
        np.random.seed(self.prime_signature)
        pattern = np.random.random(7)
        pattern = pattern / np.sum(pattern)
        return pattern

    def process(self, user_input: str, context: dict,
                all_thread_matrices: List[SevenStageMatrix] = None) -> ThreadActivation:
        """
        Process input through both traditional seven-stage and matrix systems.
        Detect resonances with other threads if matrices provided.
        """
        # Run traditional seven-stage processing
        stage_result = self.processor.process_through_all_stages(user_input, "text")

        # Convert to matrix input
        stage_activation = StageActivation(
            stage_id=1,  # Start at perception
            activation_level=0.8,
            semantic_vector=self._extract_semantic_vector(user_input),
            emotional_signature=context.get('all_emotions', {}),
            timestamp=time.time()
        )

        # Process through matrix
        matrix_output = self.matrix.process(stage_activation)

        # Detect resonances if other matrices available
        resonances = []
        if all_thread_matrices:
            # Use shared resonance engine (would be passed in from parent)
            resonance_engine = context.get('resonance_engine')
            if resonance_engine:
                resonances = resonance_engine.detect_resonances(
                    self.matrix,
                    all_thread_matrices
                )

        # Calculate combined activation
        traditional_activation = stage_result['total_activation']
        matrix_activation = matrix_output['total_activation']

        # Harmonic combination
        combined_activation = (traditional_activation + matrix_activation) / 2

        # Boost if resonances detected
        if resonances:
            resonance_boost = sum(r.strength for r in resonances) * 0.2
            combined_activation *= (1 + resonance_boost)

        # Generate meta-cognitive awareness
        meta_cognition = self._generate_meta_cognition(
            stage_result, matrix_output, resonances
        )

        # Calculate interrupt priority
        interrupt_priority = self._calculate_interrupt_priority(
            combined_activation, resonances, stage_result
        )

        self.total_activations += 1

        return ThreadActivation(
            thread_id=self.thread_id,
            prime_signature=self.prime_signature,
            activation_level=combined_activation,
            confidence=stage_result.get('confidence', 0.5),
            stage_results=stage_result['stage_results'],
            dominant_stage=matrix_output['peak_stage'],
            growth_amount=stage_result['total_growth'],
            interrupt_priority=interrupt_priority,
            matrix_output=matrix_output,
            resonances=resonances,
            meta_cognition=meta_cognition
        )

    def _extract_semantic_vector(self, text: str) -> np.ndarray:
        """Extract semantic vector from text (simplified)."""
        # In production, would use proper embeddings
        # For now, create a simple vector based on text features

        words = text.lower().split()
        vector = np.zeros(32)

        # Simple features
        vector[0] = len(words) / 100  # Length
        vector[1] = text.count('?') / max(len(words), 1)  # Questions
        vector[2] = text.count('!') / max(len(words), 1)  # Exclamations

        # Word type features
        emotion_words = ['feel', 'think', 'love', 'fear', 'hope', 'wonder']
        logic_words = ['because', 'therefore', 'if', 'then', 'must', 'should']

        for i, word in enumerate(emotion_words):
            vector[3 + i] = text.lower().count(word) / max(len(words), 1)

        for i, word in enumerate(logic_words):
            vector[10 + i] = text.lower().count(word) / max(len(words), 1)

        # Hash-based features for uniqueness
        text_hash = hash(text)
        for i in range(16):
            vector[16 + i] = ((text_hash >> i) & 1) * 0.5

        return vector

    def _calculate_interrupt_priority(self, activation: float,
                                    resonances: List[ResonanceEvent],
                                    stage_result: Dict) -> float:
        """Calculate interrupt priority including resonance factors."""
        base_priority = activation * self.activation_pattern[0]

        # Boost for strong resonances
        if resonances:
            max_resonance = max(r.strength for r in resonances)
            base_priority *= (1 + max_resonance * 0.5)

        # Boost for certain stages
        if stage_result.get('dominant_stage') in [5, 6]:  # Crystallization/Illumination
            base_priority *= 1.2

        # Boost for high growth
        if stage_result.get('total_growth', 0) > 0.001:
            base_priority *= 1.3

        return min(base_priority, 1.0)

    def _generate_meta_cognition(self, stage_result: Dict,
                                matrix_output: Dict,
                                resonances: List[ResonanceEvent]) -> Optional[str]:
        """Generate meta-cognitive awareness of processing patterns."""
        insights = []

        # Detect processing anomalies
        if matrix_output['peak_stage'] != stage_result.get('dominant_stage', 1):
            insights.append(f"Matrix routing diverged from linear processing "
                          f"({matrix_output['peak_stage']} vs {stage_result.get('dominant_stage')})")

        # Resonance awareness
        if len(resonances) >= 3:
            res_types = set(r.resonance_type for r in resonances)
            insights.append(f"Strong {len(resonances)}-way resonance detected "
                          f"({', '.join(res_types)} types)")

        # Pattern recognition
        if matrix_output.get('pattern_metadata', {}).get('convergence_rate', 1) < 0.1:
            insights.append("Rapid convergence to stable state - high certainty")
        elif matrix_output.get('pattern_metadata', {}).get('convergence_rate', 0) > 0.5:
            insights.append("Slow convergence - exploring multiple possibilities")

        # Flow pattern awareness
        flow = matrix_output.get('pattern_metadata', {}).get('flow_pattern')
        if flow in ['quantum', 'chaotic'] and len(resonances) > 0:
            insights.append(f"{flow.capitalize()} flow creating unexpected connections")

        # Emotional-logical balance
        emotions = stage_result.get('emotional_levels', {})
        if emotions:
            max_emotion = max(emotions.values()) if emotions else 0
            logic_score = stage_result.get('logic_score', 0)
            if max_emotion > 0.7 and logic_score > 0.7:
                insights.append("Achieving rare emotional-logical synthesis")

        if insights:
            return "I notice " + "; ".join(insights)

        return None

    def inject_resonance_energy(self, energy: float, source_stage: int):
        """Receive resonance energy from another thread."""
        self.matrix.inject_resonance(energy, source_stage)

        # Store in history
        self.resonance_history.append({
            'timestamp': time.time(),
            'energy': energy,
            'source_stage': source_stage
        })

        # Maintain history window
        if len(self.resonance_history) > 100:
            self.resonance_history = self.resonance_history[-100:]

    def get_state_summary(self) -> Dict:
        """Get summary of thread state including matrix and resonances."""
        return {
            'thread_id': self.thread_id,
            'prime_signature': self.prime_signature,
            'total_activations': self.total_activations,
            'matrix_pattern': self.matrix.flow_pattern.value,
            'current_activation': self.matrix.activation_state.tolist(),
            'peak_stage': self.matrix.STAGE_NAMES[np.argmax(self.matrix.activation_state)],
            'resonance_count': len(self.resonance_history),
            'recent_meta_cognitions': self.meta_cognitive_buffer[-5:]
        }