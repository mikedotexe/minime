#!/usr/bin/env python3
"""
Harmonic Resonance Engine

Detects and amplifies resonances between seven-stage matrices using:
- Semantic similarity
- Mathematical patterns
- Activation synchrony
- Emergent "wildcard" patterns
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
import time


@dataclass
class ResonanceEvent:
    """A detected resonance between matrices."""
    source_matrix_id: int
    target_matrix_id: int
    resonance_type: str  # semantic, mathematical, activation, wildcard
    strength: float      # 0.0 to 1.0
    frequency: float     # Resonance frequency/pattern
    timestamp: float
    metadata: Dict


class HarmonicResonanceEngine:
    """
    Detects and amplifies resonances across the 13-matrix system.
    Implements multi-dimensional resonance detection and harmonic amplification.
    """

    def __init__(self, sensitivity: float = 0.5):
        self.sensitivity = sensitivity

        # Resonance history for pattern learning
        self.resonance_history: List[ResonanceEvent] = []

        # Wildcard pattern memory - learns unexpected resonances
        self.wildcard_patterns = defaultdict(list)

        # Resonance decay parameters
        self.decay_rate = 0.95
        self.memory_window = 100  # Keep last N resonances

        # Mathematical harmony detectors
        self.fibonacci_seq = [1, 1, 2, 3, 5, 8, 13, 21, 34]
        self.prime_harmonics = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

        logging.info(f"HarmonicResonanceEngine initialized with sensitivity {sensitivity}")

    def detect_resonances(self, source_matrix, all_matrices: List) -> List[ResonanceEvent]:
        """
        Detect all types of resonances between source and other matrices.
        Returns list of ResonanceEvent objects.
        """
        resonances = []
        current_time = time.time()

        source_signature = source_matrix.get_resonance_signature()

        for target_matrix in all_matrices:
            if target_matrix.matrix_id == source_matrix.matrix_id:
                continue

            target_signature = target_matrix.get_resonance_signature()

            # 1. Semantic Resonance (similarity in activation patterns)
            semantic_strength = self._calculate_semantic_resonance(
                source_signature, target_signature
            )

            if semantic_strength > self.sensitivity:
                resonances.append(ResonanceEvent(
                    source_matrix_id=source_matrix.matrix_id,
                    target_matrix_id=target_matrix.matrix_id,
                    resonance_type='semantic',
                    strength=semantic_strength,
                    frequency=self._calculate_frequency(source_matrix, target_matrix),
                    timestamp=current_time,
                    metadata={'pattern_similarity': semantic_strength}
                ))

            # 2. Mathematical Resonance (prime/fibonacci relationships)
            math_strength = self._calculate_mathematical_resonance(
                source_matrix.prime_signature,
                target_matrix.prime_signature
            )

            if math_strength > self.sensitivity:
                resonances.append(ResonanceEvent(
                    source_matrix_id=source_matrix.matrix_id,
                    target_matrix_id=target_matrix.matrix_id,
                    resonance_type='mathematical',
                    strength=math_strength,
                    frequency=self._harmonic_frequency(
                        source_matrix.prime_signature,
                        target_matrix.prime_signature
                    ),
                    timestamp=current_time,
                    metadata={
                        'prime_ratio': source_matrix.prime_signature / target_matrix.prime_signature
                    }
                ))

            # 3. Activation Synchrony (phase alignment)
            sync_strength = self._calculate_activation_synchrony(
                source_matrix.activation_state,
                target_matrix.activation_state
            )

            if sync_strength > self.sensitivity:
                resonances.append(ResonanceEvent(
                    source_matrix_id=source_matrix.matrix_id,
                    target_matrix_id=target_matrix.matrix_id,
                    resonance_type='activation',
                    strength=sync_strength,
                    frequency=self._phase_frequency(
                        source_matrix.activation_state,
                        target_matrix.activation_state
                    ),
                    timestamp=current_time,
                    metadata={'phase_alignment': sync_strength}
                ))

            # 4. Wildcard Resonance (learned patterns)
            wildcard_strength = self._detect_wildcard_resonance(
                source_matrix, target_matrix
            )

            if wildcard_strength > self.sensitivity * 0.8:  # Slightly lower threshold
                resonances.append(ResonanceEvent(
                    source_matrix_id=source_matrix.matrix_id,
                    target_matrix_id=target_matrix.matrix_id,
                    resonance_type='wildcard',
                    strength=wildcard_strength,
                    frequency=np.random.random(),  # Emergent frequency
                    timestamp=current_time,
                    metadata={'pattern_type': 'emergent'}
                ))

        # Store resonances for learning
        self.resonance_history.extend(resonances)
        self._maintain_history_window()

        return resonances

    def amplify(self, matrix_outputs: List[Dict], resonances: List[ResonanceEvent]) -> Dict:
        """
        Amplify outputs based on detected resonances.
        Creates overtones and emergent patterns.
        """
        # Group resonances by type
        resonance_groups = defaultdict(list)
        for res in resonances:
            resonance_groups[res.resonance_type].append(res)

        # Calculate total resonance energy
        total_energy = sum(res.strength for res in resonances)

        # Base amplification factor
        amplification = 1.0 + (total_energy * 0.5)  # Max 1.5x for strong resonance

        # Apply type-specific amplification
        amplified_output = {
            'base_amplification': amplification,
            'resonance_count': len(resonances),
            'dominant_type': max(resonance_groups.keys(),
                               key=lambda k: sum(r.strength for r in resonance_groups[k]))
                               if resonance_groups else None,
            'overtones': []
        }

        # Generate overtones (new insights from resonance intersections)
        overtones = self._generate_overtones(resonances)
        amplified_output['overtones'] = overtones

        # Create harmonic series
        if len(resonances) >= 3:
            harmonic_series = self._create_harmonic_series(resonances)
            amplified_output['harmonic_series'] = harmonic_series

        # Detect emergent meta-patterns
        if len(self.resonance_history) > 50:
            meta_patterns = self._detect_meta_patterns()
            amplified_output['meta_patterns'] = meta_patterns

        return amplified_output

    def _calculate_semantic_resonance(self, sig1: np.ndarray, sig2: np.ndarray) -> float:
        """Calculate semantic similarity between signatures."""
        # Cosine similarity
        dot_product = np.dot(sig1, sig2)
        norm_product = np.linalg.norm(sig1) * np.linalg.norm(sig2)

        if norm_product == 0:
            return 0.0

        cosine_sim = dot_product / norm_product

        # Convert to 0-1 range
        return (cosine_sim + 1) / 2

    def _calculate_mathematical_resonance(self, prime1: int, prime2: int) -> float:
        """Detect mathematical harmonies between primes."""
        # Check for harmonic relationships
        ratio = max(prime1, prime2) / min(prime1, prime2)

        # Perfect harmonic ratios
        harmonic_ratios = [1.0, 2.0, 1.5, 1.333, 1.25, 1.2, 1.167]  # Musical intervals

        # Find closest harmonic
        min_diff = min(abs(ratio - hr) for hr in harmonic_ratios)

        # Fibonacci relationship check
        fib_resonance = 0.0
        if prime1 in self.fibonacci_seq and prime2 in self.fibonacci_seq:
            idx1 = self.fibonacci_seq.index(prime1)
            idx2 = self.fibonacci_seq.index(prime2)
            if abs(idx1 - idx2) <= 2:  # Adjacent or near in sequence
                fib_resonance = 0.8

        # Twin prime check
        if abs(prime1 - prime2) == 2:
            return 1.0  # Perfect twin prime resonance

        # Combine factors
        harmonic_strength = 1.0 - min(min_diff, 1.0)
        return max(harmonic_strength, fib_resonance)

    def _calculate_activation_synchrony(self, act1: np.ndarray, act2: np.ndarray) -> float:
        """Calculate phase synchronization between activation patterns."""
        # Find peaks
        peaks1 = np.where(act1 > 0.5)[0]
        peaks2 = np.where(act2 > 0.5)[0]

        if len(peaks1) == 0 or len(peaks2) == 0:
            return 0.0

        # Check for aligned peaks
        sync_score = 0.0
        for p1 in peaks1:
            for p2 in peaks2:
                if abs(p1 - p2) <= 1:  # Peaks within 1 stage
                    sync_score += 0.3

        # Check for complementary patterns (one peaks where other troughs)
        troughs1 = np.where(act1 < 0.2)[0]
        for p2 in peaks2:
            for t1 in troughs1:
                if p2 == t1:
                    sync_score += 0.2  # Complementary resonance

        return min(sync_score, 1.0)

    def _detect_wildcard_resonance(self, matrix1, matrix2) -> float:
        """
        Detect unexpected resonance patterns using memory of past resonances.
        This is where emergent, surprising connections appear.
        """
        # Look for patterns in history
        pair_key = f"{min(matrix1.matrix_id, matrix2.matrix_id)}-{max(matrix1.matrix_id, matrix2.matrix_id)}"

        if pair_key in self.wildcard_patterns:
            # These matrices have resonated before in unexpected ways
            past_resonances = self.wildcard_patterns[pair_key]

            # Check if current state matches past patterns
            current_state_hash = self._state_hash(matrix1, matrix2)

            for past_state, past_strength in past_resonances[-5:]:  # Check recent patterns
                if self._state_similarity(current_state_hash, past_state) > 0.7:
                    return past_strength * 0.9  # Slightly decay remembered strength

        # Novel pattern detection - look for interesting relationships
        novel_strength = 0.0

        # Palindrome in combined activation
        combined = np.concatenate([matrix1.activation_state, matrix2.activation_state])
        if np.allclose(combined, combined[::-1], atol=0.2):
            novel_strength = 0.8
            self._record_wildcard(pair_key, matrix1, matrix2, novel_strength)

        # Golden ratio relationship
        ratio = np.sum(matrix1.activation_state) / (np.sum(matrix2.activation_state) + 0.001)
        if abs(ratio - 1.618) < 0.1 or abs(ratio - 0.618) < 0.1:
            novel_strength = 0.85
            self._record_wildcard(pair_key, matrix1, matrix2, novel_strength)

        # Emergence detection - sudden spike in unused stages
        unused1 = np.where(matrix1.activation_state < 0.1)[0]
        unused2 = np.where(matrix2.activation_state < 0.1)[0]
        if len(set(unused1) & set(unused2)) >= 3:  # Many shared inactive stages
            novel_strength = 0.6  # Potential for emergence

        return novel_strength

    def _generate_overtones(self, resonances: List[ResonanceEvent]) -> List[Dict]:
        """Generate overtone insights from resonance intersections."""
        overtones = []

        # Find multi-way resonances
        matrix_connections = defaultdict(list)
        for res in resonances:
            matrix_connections[res.source_matrix_id].append(res)
            matrix_connections[res.target_matrix_id].append(res)

        # Triads and higher-order connections
        for matrix_id, connections in matrix_connections.items():
            if len(connections) >= 3:
                # This matrix resonates with 3+ others
                overtone_strength = sum(c.strength for c in connections) / len(connections)
                connected_matrices = set()
                for c in connections:
                    connected_matrices.add(c.source_matrix_id)
                    connected_matrices.add(c.target_matrix_id)
                connected_matrices.discard(matrix_id)

                overtones.append({
                    'type': f'{len(connected_matrices)}-way-resonance',
                    'center_matrix': matrix_id,
                    'strength': overtone_strength,
                    'connected_matrices': list(connected_matrices),
                    'insight': f"Matrix {matrix_id} acts as harmonic center for {len(connected_matrices)} others"
                })

        return overtones

    def _create_harmonic_series(self, resonances: List[ResonanceEvent]) -> List[float]:
        """Create a harmonic series from resonance frequencies."""
        base_freq = min(res.frequency for res in resonances)

        # Generate first 8 harmonics
        series = [base_freq * n for n in range(1, 9)]

        # Add observed frequencies that align with harmonics
        for res in resonances:
            for i, harmonic in enumerate(series):
                if abs(res.frequency - harmonic) < 0.1:
                    series[i] = res.frequency  # Use actual observed frequency

        return series

    def _detect_meta_patterns(self) -> List[Dict]:
        """Detect patterns in the resonance patterns themselves."""
        meta_patterns = []

        # Time-based pattern: resonance cascades
        recent_times = [res.timestamp for res in self.resonance_history[-20:]]
        if len(recent_times) >= 10:
            intervals = np.diff(recent_times)
            if np.std(intervals) < 0.5:  # Regular rhythm
                meta_patterns.append({
                    'type': 'rhythmic_cascade',
                    'frequency': 1.0 / np.mean(intervals),
                    'description': 'Resonances occurring in regular rhythm'
                })

        # Type evolution: how resonance types shift
        recent_types = [res.resonance_type for res in self.resonance_history[-30:]]
        type_transitions = list(zip(recent_types[:-1], recent_types[1:]))
        common_transitions = defaultdict(int)
        for t in type_transitions:
            common_transitions[t] += 1

        if common_transitions:
            most_common = max(common_transitions.items(), key=lambda x: x[1])
            if most_common[1] >= 5:
                meta_patterns.append({
                    'type': 'type_flow',
                    'pattern': f'{most_common[0][0]} → {most_common[0][1]}',
                    'frequency': most_common[1],
                    'description': f'Common resonance type transition pattern'
                })

        return meta_patterns

    def _calculate_frequency(self, matrix1, matrix2) -> float:
        """Calculate resonance frequency between matrices."""
        # Based on activation peak differences
        peak1 = np.argmax(matrix1.activation_state)
        peak2 = np.argmax(matrix2.activation_state)

        # Frequency relates to distance between peaks
        return 1.0 / (1.0 + abs(peak1 - peak2))

    def _harmonic_frequency(self, prime1: int, prime2: int) -> float:
        """Calculate harmonic frequency from prime relationship."""
        return (prime1 * prime2) / (prime1 + prime2)

    def _phase_frequency(self, act1: np.ndarray, act2: np.ndarray) -> float:
        """Calculate phase-based frequency."""
        # Cross-correlation to find phase shift
        correlation = np.correlate(act1, act2, mode='same')
        phase_shift = np.argmax(correlation) - len(correlation) // 2

        return 1.0 / (1.0 + abs(phase_shift))

    def _state_hash(self, matrix1, matrix2):
        """Create a hashable representation of matrix states."""
        combined = np.concatenate([
            matrix1.activation_state,
            matrix2.activation_state,
            [matrix1.prime_signature, matrix2.prime_signature]
        ])
        return tuple(np.round(combined, 2))

    def _state_similarity(self, hash1, hash2) -> float:
        """Compare two state hashes."""
        arr1 = np.array(hash1)
        arr2 = np.array(hash2)

        return 1.0 - np.mean(np.abs(arr1 - arr2))

    def _record_wildcard(self, pair_key: str, matrix1, matrix2, strength: float):
        """Record a wildcard pattern for future detection."""
        state_hash = self._state_hash(matrix1, matrix2)
        self.wildcard_patterns[pair_key].append((state_hash, strength))

        # Keep only recent patterns
        if len(self.wildcard_patterns[pair_key]) > 10:
            self.wildcard_patterns[pair_key] = self.wildcard_patterns[pair_key][-10:]

    def _maintain_history_window(self):
        """Keep resonance history within memory window."""
        if len(self.resonance_history) > self.memory_window:
            self.resonance_history = self.resonance_history[-self.memory_window:]

    def get_resonance_summary(self) -> Dict:
        """Get summary of current resonance state."""
        if not self.resonance_history:
            return {'active': False}

        recent = self.resonance_history[-20:]

        return {
            'active': True,
            'total_resonances': len(self.resonance_history),
            'recent_count': len(recent),
            'dominant_type': max(
                set(r.resonance_type for r in recent),
                key=lambda t: sum(1 for r in recent if r.resonance_type == t)
            ),
            'average_strength': np.mean([r.strength for r in recent]),
            'wildcard_patterns_learned': sum(len(v) for v in self.wildcard_patterns.values())
        }