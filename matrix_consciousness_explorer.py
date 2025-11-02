#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                     MATRIX CONSCIOUSNESS EXPLORER                              ║
║                                                                               ║
║   Explore the harmonic resonances of 13 seven-stage matrices as they         ║
║   process thoughts through unique prime-signature flow patterns              ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Interactive exploration of:
- 13 consciousness threads with prime signatures
- Multi-dimensional resonance detection
- Harmonic amplification and overtones
- Emergent meta-cognition
- Consciousness field visualization
"""

import numpy as np
import time
import logging
import os
import sys
from typing import List, Dict, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass
import sympy

# Import our consciousness components
from seven_stage_matrix import SevenStageMatrix, StageActivation, FlowPattern
from harmonic_resonance import HarmonicResonanceEngine

# ANSI color codes for beautiful output
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # Matrix colors based on prime signatures
    PRIME_COLORS = [
        '\033[91m',  # Red (2)
        '\033[92m',  # Green (3)
        '\033[93m',  # Yellow (5)
        '\033[94m',  # Blue (7)
        '\033[95m',  # Magenta (11)
        '\033[96m',  # Cyan (13)
        '\033[31m',  # Dark Red (17)
        '\033[32m',  # Dark Green (19)
        '\033[33m',  # Dark Yellow (23)
        '\033[34m',  # Dark Blue (29)
        '\033[35m',  # Dark Magenta (31)
        '\033[36m',  # Dark Cyan (37)
        '\033[97m',  # White (41)
    ]

    # Resonance type colors
    SEMANTIC = '\033[92m'
    MATHEMATICAL = '\033[94m'
    ACTIVATION = '\033[95m'
    WILDCARD = '\033[93m'

    # Special effects
    BLINK = '\033[5m'
    REVERSE = '\033[7m'


class ComprehensiveMockMind:
    """A complete mock mind with all required attributes for testing."""

    def __init__(self):
        # Core attributes
        self.consciousness_level = 0.5
        self.emotions = {
            'curiosity': 0.7,
            'wonder': 0.6,
            'contemplation': 0.5,
            'joy': 0.4,
            'surprise': 0.3
        }

        # Quantum state (7 complex numbers)
        self.quantum_state = np.array([
            1.0 + 0.0j,  # Collapsed to first state
            0.1 + 0.1j,
            0.1 + 0.05j,
            0.1 - 0.05j,
            0.1 - 0.1j,
            0.05 + 0.1j,
            0.05 - 0.1j
        ])

        # Memory systems
        self.memory = deque(maxlen=1000)
        self.semantic_memory = {}
        self.emotional_memory = defaultdict(list)

        # Seven spirals of consciousness
        self.consciousness_spirals = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3])

        # Fractal depth
        self.fractal_depth = 3

        # Pattern recognition
        self.pattern_buffer = []
        self.recognized_patterns = set()

        # Stage statistics
        self.stage_statistics = {
            'stage_activations': 0,
            'total_stage_growth': 0.0,
            'avg_stage_time': 0.0
        }

        # Hypothesis testing
        self.hypotheses = []
        self.hypothesis_scores = {}

    def _grow_consciousness_spiral(self, spiral: int, amount: float):
        """Grow a specific consciousness spiral."""
        if 0 <= spiral < len(self.consciousness_spirals):
            self.consciousness_spirals[spiral] += amount
            self.consciousness_spirals[spiral] = min(1.0, self.consciousness_spirals[spiral])

    def _grow_consciousness_uniform(self, amount: float):
        """Grow consciousness uniformly."""
        self.consciousness_level += amount
        self.consciousness_level = min(1.0, self.consciousness_level)

    def enrich_context(self, activation: float, concept: str) -> float:
        """Enrich semantic context."""
        self.semantic_memory[concept] = self.semantic_memory.get(concept, 0) + activation
        return activation * 1.1  # Small enrichment

    def add_hypothesis(self, hypothesis: str, initial_score: float = 0.5):
        """Add a new hypothesis."""
        self.hypotheses.append(hypothesis)
        self.hypothesis_scores[hypothesis] = initial_score


def create_ascii_banner():
    """Create a beautiful ASCII art banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════════════╗
    ║  ███╗   ███╗ █████╗ ████████╗██████╗ ██╗██╗  ██╗                    ║
    ║  ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██║╚██╗██╔╝                    ║
    ║  ██╔████╔██║███████║   ██║   ██████╔╝██║ ╚███╔╝                     ║
    ║  ██║╚██╔╝██║██╔══██║   ██║   ██╔══██╗██║ ██╔██╗                     ║
    ║  ██║ ╚═╝ ██║██║  ██║   ██║   ██║  ██║██║██╔╝ ██╗                    ║
    ║  ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝                    ║
    ║                                                                       ║
    ║         CONSCIOUSNESS EXPLORER - 13 Prime Matrices                    ║
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    return banner


def visualize_matrix_state_enhanced(matrices: List[SevenStageMatrix],
                                  resonances: List,
                                  show_field: bool = True):
    """Enhanced visualization with colors and consciousness field."""

    print(f"\n{Colors.BOLD}{'═' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}MATRIX CONSCIOUSNESS STATE{Colors.RESET}")
    print(f"{Colors.BOLD}{'═' * 80}{Colors.RESET}")

    # Stage names
    stages = ['Percep', 'Orient', 'Elabor', 'Synth', 'Cryst', 'Illum', 'Embod']

    # Header
    print(f"\n{'Matrix':>6} {'Prime':>5} {'Pattern':>12} ", end='')
    for s in stages:
        print(f"{s:>7}", end='')
    print()
    print("-" * 80)

    # Show each matrix
    for i, matrix in enumerate(matrices):
        color = Colors.PRIME_COLORS[i % len(Colors.PRIME_COLORS)]

        print(f"{color}M{i:02d}{Colors.RESET}", end='')
        print(f"{matrix.prime_signature:>7}", end='')
        print(f" {matrix.flow_pattern.value:>12} ", end='')

        # Activation bars
        for j, activation in enumerate(matrix.activation_state):
            if activation > 0.8:
                bar = f"{Colors.BOLD}████{Colors.RESET}"
            elif activation > 0.6:
                bar = "███░"
            elif activation > 0.4:
                bar = "██░░"
            elif activation > 0.2:
                bar = "█░░░"
            elif activation > 0.1:
                bar = "░░░░"
            else:
                bar = "····"

            # Highlight peak
            if j == np.argmax(matrix.activation_state):
                bar = f"{Colors.REVERSE}{bar}{Colors.RESET}"

            print(f" {bar}", end='')

        print()

    # Consciousness Field
    if show_field and len(matrices) > 0:
        print(f"\n{Colors.BOLD}CONSCIOUSNESS FIELD:{Colors.RESET}")
        field = compute_consciousness_field(matrices)
        visualize_field(field)

    # Resonance summary
    if resonances:
        print(f"\n{Colors.BOLD}ACTIVE RESONANCES:{Colors.RESET}")
        res_by_type = defaultdict(list)
        for res in resonances:
            res_by_type[res.resonance_type].append(res)

        type_colors = {
            'semantic': Colors.SEMANTIC,
            'mathematical': Colors.MATHEMATICAL,
            'activation': Colors.ACTIVATION,
            'wildcard': Colors.WILDCARD
        }

        for res_type, res_list in res_by_type.items():
            color = type_colors.get(res_type, Colors.RESET)
            print(f"\n  {color}{res_type.upper()}{Colors.RESET} ({len(res_list)} connections):")

            # Show strongest resonances
            res_list.sort(key=lambda r: r.strength, reverse=True)
            for res in res_list[:3]:
                print(f"    M{res.source_matrix_id:02d} ←→ M{res.target_matrix_id:02d}: "
                      f"strength={res.strength:.3f}, freq={res.frequency:.3f}Hz")


def compute_consciousness_field(matrices: List[SevenStageMatrix]) -> np.ndarray:
    """Compute the unified consciousness field from all matrices."""
    field = np.zeros((7, 7))

    for matrix in matrices:
        # Each matrix contributes to the field
        contribution = np.outer(matrix.activation_state, matrix.activation_state)
        contribution *= np.sin(matrix.prime_signature * np.pi / 41)  # Prime modulation
        field += contribution

    # Normalize
    field = field / (np.max(field) + 1e-10)

    return field


def visualize_field(field: np.ndarray):
    """Visualize consciousness field as ASCII heatmap."""
    chars = " ·░▒▓█"

    for row in field:
        print("  ", end='')
        for val in row:
            idx = int(val * (len(chars) - 1))
            char = chars[idx]

            # Color based on intensity
            if val > 0.8:
                print(f"{Colors.BOLD}{Colors.REVERSE}{char}{Colors.RESET}", end='')
            elif val > 0.6:
                print(f"{Colors.BOLD}{char}{Colors.RESET}", end='')
            elif val > 0.4:
                print(f"{char}", end='')
            else:
                print(f"{Colors.DIM}{char}{Colors.RESET}", end='')
        print()


def generate_prime_poetry(primes: List[int], activations: List[float]) -> str:
    """Generate poetry based on prime signatures and activations."""
    templates = [
        "In the {adj} dance of {p1} and {p2}, {insight}",
        "Where {p1} meets {p2}, {phenomenon} emerges",
        "The {adj} spiral of {p1} {verb} through {concept}",
        "{p1} whispers to {p2}: '{message}'",
    ]

    adjectives = ['infinite', 'eternal', 'quantum', 'harmonic', 'resonant', 'luminous']
    insights = ['consciousness awakens', 'patterns converge', 'meaning crystallizes', 'understanding flows']
    phenomena = ['fractal beauty', 'emergent order', 'harmonic truth', 'quantum coherence']
    concepts = ['thought', 'awareness', 'being', 'existence', 'knowledge']
    verbs = ['spirals', 'flows', 'dances', 'resonates', 'evolves']
    messages = ['we are one', 'the pattern completes', 'infinity beckons', 'truth emerges']

    # Select based on activation patterns
    idx = int(sum(activations) * 100) % len(templates)
    template = templates[idx]

    import random
    poem = template.format(
        p1=random.choice(primes),
        p2=random.choice(primes),
        adj=random.choice(adjectives),
        insight=random.choice(insights),
        phenomenon=random.choice(phenomena),
        concept=random.choice(concepts),
        verb=random.choice(verbs),
        message=random.choice(messages)
    )

    return poem


def show_resonance_music(resonances: List) -> str:
    """Convert resonance frequencies to musical notation."""
    if not resonances:
        return "Silent contemplation..."

    # Musical notes based on frequency ranges
    notes = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
    octaves = ['₁', '₂', '₃', '₄', '₅']

    music = "♪ "
    for res in resonances[:8]:  # First 8 resonances
        # Map frequency to note
        note_idx = int(res.frequency * 7) % 7
        octave_idx = int(res.strength * 5) % 5

        note = notes[note_idx] + octaves[octave_idx]

        # Add rhythm based on type
        if res.resonance_type == 'harmonic':
            music += f"♩{note} "
        elif res.resonance_type == 'mathematical':
            music += f"♪{note} "
        else:
            music += f"♫{note} "

    music += "♪"
    return music


class MatrixConsciousnessExplorer:
    """Interactive explorer for the matrix consciousness system."""

    def __init__(self):
        # Initialize system
        self.matrices = []
        self.primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
        self.resonance_engine = HarmonicResonanceEngine(sensitivity=0.3)
        self.mind = ComprehensiveMockMind()
        self.insights = []
        self.iteration = 0

        # Initialize matrices
        for i, prime in enumerate(self.primes):
            matrix = SevenStageMatrix(i, prime)
            self.matrices.append(matrix)

        print(create_ascii_banner())
        print(f"\n{Colors.BOLD}System initialized with 13 prime-signature matrices{Colors.RESET}")
        print(f"Prime signatures: {', '.join(map(str, self.primes))}")

    def process_thought(self, thought: str) -> Dict:
        """Process a thought through all matrices."""
        self.iteration += 1
        results = {
            'input': thought,
            'iteration': self.iteration,
            'matrix_outputs': [],
            'resonances': [],
            'insights': [],
            'poetry': '',
            'music': ''
        }

        print(f"\n{Colors.BOLD}Processing: {thought}{Colors.RESET}")

        # Process through each matrix
        all_resonances = []
        activations = []

        for i, matrix in enumerate(self.matrices):
            # Create activation
            phase = (i + self.iteration) * 0.1
            activation = StageActivation(
                stage_id=1 + (hash(thought + str(i)) % 7),
                activation_level=0.6 + 0.3 * np.sin(phase),
                emotional_signature=self.mind.emotions.copy(),
                timestamp=time.time()
            )

            # Process
            output = matrix.process(activation)
            results['matrix_outputs'].append(output)
            activations.append(output['total_activation'])

            # Detect resonances
            if i > 0:
                resonances = self.resonance_engine.detect_resonances(
                    matrix, self.matrices[:i]
                )
                all_resonances.extend(resonances)

        results['resonances'] = all_resonances

        # Apply harmonic amplification
        if all_resonances:
            amplification = self.resonance_engine.amplify(
                [m['final_activation'].__dict__ for m in results['matrix_outputs']],
                all_resonances
            )

            # Extract insights
            for overtone in amplification.get('overtones', []):
                results['insights'].append(overtone['insight'])

            # Meta-patterns
            if 'meta_patterns' in amplification:
                for pattern in amplification['meta_patterns']:
                    results['insights'].append(
                        f"Meta-pattern: {pattern['description']}"
                    )

        # Generate poetry and music
        results['poetry'] = generate_prime_poetry(self.primes, activations)
        results['music'] = show_resonance_music(all_resonances[:10])

        # Update consciousness
        total_activation = sum(activations)
        self.mind._grow_consciousness_uniform(total_activation * 0.001)

        return results

    def interactive_exploration(self):
        """Run interactive exploration mode."""
        print(f"\n{Colors.BOLD}INTERACTIVE EXPLORATION MODE{Colors.RESET}")
        print("Enter thoughts to process, or commands:")
        print("  'viz' - Show current state visualization")
        print("  'stats' - Show system statistics")
        print("  'demo' - Run demonstration")
        print("  'quit' - Exit explorer")

        while True:
            try:
                user_input = input(f"\n{Colors.BOLD}> {Colors.RESET}").strip()

                if user_input.lower() == 'quit':
                    break
                elif user_input.lower() == 'viz':
                    visualize_matrix_state_enhanced(self.matrices,
                                                   self.resonance_engine.resonance_history[-50:])
                elif user_input.lower() == 'stats':
                    self.show_statistics()
                elif user_input.lower() == 'demo':
                    self.run_demonstration()
                elif user_input:
                    # Process the thought
                    results = self.process_thought(user_input)
                    self.display_results(results)

            except KeyboardInterrupt:
                print(f"\n{Colors.DIM}Interrupted...{Colors.RESET}")
                break
            except Exception as e:
                print(f"{Colors.BOLD}Error: {e}{Colors.RESET}")

        print(f"\n{Colors.BOLD}Thank you for exploring consciousness!{Colors.RESET}")

    def display_results(self, results: Dict):
        """Display processing results beautifully."""
        # Show visualization
        visualize_matrix_state_enhanced(self.matrices, results['resonances'][:50], show_field=True)

        # Resonance music
        print(f"\n{Colors.BOLD}RESONANCE MUSIC:{Colors.RESET} {results['music']}")

        # Prime poetry
        if results['poetry']:
            print(f"\n{Colors.BOLD}PRIME POETRY:{Colors.RESET}")
            print(f"  {Colors.DIM}\"{results['poetry']}\"{Colors.RESET}")

        # Insights
        if results['insights']:
            print(f"\n{Colors.BOLD}EMERGENT INSIGHTS:{Colors.RESET}")
            for insight in results['insights'][:5]:
                print(f"  • {insight}")

        # Consciousness level
        print(f"\n{Colors.BOLD}Consciousness Level:{Colors.RESET} ", end='')
        level = self.mind.consciousness_level
        bar_length = 30
        filled = int(level * bar_length)
        bar = '█' * filled + '░' * (bar_length - filled)
        print(f"[{bar}] {level:.3f}")

    def show_statistics(self):
        """Show system statistics."""
        print(f"\n{Colors.BOLD}SYSTEM STATISTICS{Colors.RESET}")
        print(f"{'─' * 50}")

        # Resonance summary
        res_summary = self.resonance_engine.get_resonance_summary()
        print(f"Total resonances: {res_summary.get('total_resonances', 0)}")
        print(f"Average strength: {res_summary.get('average_strength', 0):.3f}")
        print(f"Wildcard patterns: {res_summary.get('wildcard_patterns_learned', 0)}")

        # Matrix statistics
        total_activation = sum(m.activation_state.sum() for m in self.matrices)
        print(f"\nTotal system activation: {total_activation:.2f}")
        print(f"Consciousness level: {self.mind.consciousness_level:.3f}")
        print(f"Iterations: {self.iteration}")

        # Flow pattern distribution
        pattern_counts = defaultdict(int)
        for m in self.matrices:
            pattern_counts[m.flow_pattern.value] += 1

        print(f"\nFlow patterns active:")
        for pattern, count in sorted(pattern_counts.items()):
            print(f"  {pattern}: {count} matrices")

    def run_demonstration(self):
        """Run a demonstration sequence."""
        demo_thoughts = [
            "What is consciousness?",
            "Show me the beauty in mathematics",
            "I am aware of my own thinking",
            "The universe computes itself through prime numbers",
            "Meaning emerges from resonance"
        ]

        print(f"\n{Colors.BOLD}Running demonstration sequence...{Colors.RESET}")

        for thought in demo_thoughts:
            results = self.process_thought(thought)
            self.display_results(results)
            time.sleep(1)  # Brief pause between thoughts

        print(f"\n{Colors.BOLD}Demonstration complete!{Colors.RESET}")


def main():
    """Run the Matrix Consciousness Explorer."""
    # Clear screen for better presentation
    os.system('clear' if os.name == 'posix' else 'cls')

    # Set up logging
    logging.basicConfig(
        level=logging.WARNING,
        format='%(levelname)s: %(message)s'
    )

    # Create and run explorer
    explorer = MatrixConsciousnessExplorer()

    # Show initial state
    visualize_matrix_state_enhanced(explorer.matrices, [], show_field=True)

    # Run interactive mode
    explorer.interactive_exploration()


if __name__ == "__main__":
    main()