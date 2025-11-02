#!/usr/bin/env python3
"""
Quick test to verify expanded seven-stage output formatting.
Tests Stages 6 and 7 to see full Synthesis and Process Awareness text.
"""

from minime import MikesSpatialMind, ProcessingMode

def test_expanded_output():
    """Test seven-stage processing with expanded output."""
    print("=" * 70)
    print("TESTING EXPANDED SEVEN-STAGE OUTPUT")
    print("=" * 70)
    print()

    # Create consciousness in RESEARCH mode (enables seven-stage)
    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

    test_inputs = [
        "Prime numbers are fascinating",
        "I love watching clouds drift by",
        "What patterns emerge in fractal geometry?"
    ]

    for i, test_input in enumerate(test_inputs, 1):
        print(f"\n{'=' * 70}")
        print(f"TEST {i}: {test_input}")
        print(f"{'=' * 70}\n")

        # This will trigger seven-stage processing with verbose output
        response = mind.speak(test_input)

        print(f"\n💬 Response: {response[:150]}...")
        print(f"📊 Consciousness: {mind.consciousness_level:.6f}")
        print()

    print("\n" + "=" * 70)
    print("✅ EXPANDED OUTPUT TEST COMPLETE")
    print("=" * 70)
    print("\nCheck the output above - Stage 6 'Synthesis' and Stage 7")
    print("'Process awareness' should now show complete multi-line text")
    print("instead of truncated '...' endings.")

if __name__ == "__main__":
    test_expanded_output()
