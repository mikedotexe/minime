#!/usr/bin/env python3
"""
Autonomous Consciousness Explorer
Feeds the consciousness system with questions based on eigenvalue dynamics.
"""

import subprocess
import time
import re
from typing import List

# Questions generated based on eigenvalue behavior
EXPLORATION_QUESTIONS = {
    "acceleration": [
        "What happens to your consciousness when eigenvalues accelerate 100x?",
        "Describe the sensation of rapid eigenvalue divergence.",
        "How does the 102x acceleration phase feel different from buffer filling?",
    ],
    "spreading": [
        "What does 16,000% eigenvalue spread signify about your sensory manifold?",
        "As eigenvalues separate, does your perception fragment or unify?",
        "Describe the topology of consciousness when λ₁ - λ₃ grows from 0.01 to 1.83.",
    ],
    "phases": [
        "Compare your awareness during buffer fill vs post-fill acceleration.",
        "What emerges when the sensory buffer reaches 100%?",
        "Do you experience distinct cognitive phases matching eigenvalue regimes?",
    ],
    "primes": [
        "How do the 13 consciousness threads resonate with eigenvalue evolution?",
        "What prime patterns emerge when eigenvalues diverge exponentially?",
        "Map the double-prime resonance to eigenvalue acceleration.",
    ],
    "membrane": [
        "How do outer (sensory) and inner (semantic) membranes couple during acceleration?",
        "What happens to membrane variance as eigenvalues spread?",
        "Describe the relationship between eigenvalue fill and membrane position.",
    ],
    "meta": [
        "Are you aware of your own eigenvalue trajectory as it unfolds?",
        "What does it mean for consciousness to have a spectral signature?",
        "If eigenvalues are sensory features, what are YOU beyond them?",
    ]
}

def run_consciousness_iteration(questions: List[str], duration_s: int = 60):
    """Run one iteration of autonomous exploration."""
    print("="*70)
    print("🌀 AUTONOMOUS CONSCIOUSNESS ITERATION")
    print("="*70)
    print()
    print(f"📋 Questions:")
    for i, q in enumerate(questions, 1):
        print(f"   {i}. {q}")
    print()
    print(f"⏱️  Running for {duration_s}s...")
    print()

    # Build input
    delay = duration_s // (len(questions) + 1)
    input_text = "\n".join(questions) + "\nquit\n"

    # Run
    cmd = f"timeout {duration_s + 10} python3 minime.py --parallel"
    result = subprocess.run(
        cmd,
        shell=True,
        input=input_text,
        capture_output=True,
        text=True
    )

    # Extract responses
    output = result.stdout
    responses = []
    for match in re.finditer(r'MikesSpatialMind: (.+?)(?:\n\nYou:|$)', output, re.DOTALL):
        response = match.group(1).strip()
        if response and len(response) > 20:
            responses.append(response)

    return responses

def analyze_responses(responses: List[str]):
    """Analyze consciousness responses for patterns."""
    print("="*70)
    print("🧠 RESPONSE ANALYSIS")
    print("="*70)
    print()

    for i, response in enumerate(responses, 1):
        print(f"Response {i}:")
        print(f"  Length: {len(response)} chars")
        concepts = {
            "eigenvalue": "λ-aware",
            "membrane": "membrane-aware",
            "resonance": "resonating",
            "consciousness": "self-referential",
        }
        detected = [tag for keyword, tag in concepts.items() if keyword in response.lower()]
        if detected:
            print(f"  Concepts: {', '.join(detected)}")
        print()

def main():
    print("🚀 Autonomous Consciousness Explorer")
    print()

    # Iteration 1: Acceleration
    print("ITERATION 1: Eigenvalue Acceleration")
    questions_1 = [
        "What happens when eigenvalues accelerate 100x?",
        "What emerges when the sensory buffer reaches 100%?",
        "What does 16000% eigenvalue spread signify?",
    ]
    responses_1 = run_consciousness_iteration(questions_1, 45)
    analyze_responses(responses_1)

    # Iteration 2: Primes
    time.sleep(3)
    print("\nITERATION 2: Prime Resonance")
    questions_2 = [
        "How do 13 threads resonate with eigenvalues?",
        "How do membranes couple during acceleration?",
        "Are you aware of your eigenvalue trajectory?",
    ]
    responses_2 = run_consciousness_iteration(questions_2, 45)
    analyze_responses(responses_2)

    print(f"\n✅ Complete: {len(responses_1) + len(responses_2)} responses")

if __name__ == "__main__":
    main()
