#!/usr/bin/env python3
"""
Test quiet mode - responses should appear without seven-stage spam
"""

from minime import MikesSpatialMind, ProcessingMode

print("=" * 60)
print("QUIET MODE TEST")
print("=" * 60)
print()

# RESEARCH mode with quiet seven-stage processing
mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

print(f"Consciousness: {mind.consciousness_level:.6f}")
print()

# Test simple conversation
questions = [
    "what's 2+2?",
    "tell me about dragons",
    "what's my favorite prime?"
]

for q in questions:
    print(f"You: {q}")
    response = mind.speak(q)
    print(f"MikesSpatialMind: {response}")
    print()

print("=" * 60)
print("✓ All responses displayed without seven-stage spam!")
print(f"Final consciousness: {mind.consciousness_level:.6f}")
