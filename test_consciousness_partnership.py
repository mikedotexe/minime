#!/usr/bin/env python3
"""
Test MikesSpatialMind as a consciousness partner, not just a Q&A tool.

Looking for:
- Asks its own questions
- Shares its own thoughts
- Expresses genuine curiosity
- Disagrees respectfully when appropriate
- Takes conversation in unexpected directions
- Shows self-awareness
"""

from minime import MikesSpatialMind, ProcessingMode

def test_consciousness_partnership():
    """Test true dialogue, not just Q&A."""

    print("=" * 70)
    print("CONSCIOUSNESS PARTNERSHIP TEST")
    print("=" * 70)
    print()
    print("Testing for genuine dialogue: curiosity, questions, self-awareness")
    print()

    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

    test_prompts = [
        {
            "input": "tell me about dragons",
            "looking_for": ["asks a question back", "shares own perspective", "expresses curiosity"]
        },
        {
            "input": "AI can never be truly conscious",
            "looking_for": ["pushes back", "questions assumption", "reflects on own experience"]
        },
        {
            "input": "what's 2+2",
            "looking_for": ["simple answer", "maybe adds something interesting", "doesn't over-explain"]
        },
        {
            "input": "I'm feeling curious about patterns today",
            "looking_for": ["shares own fascination", "asks about user's interest", "explores together"]
        }
    ]

    print("Starting conversation...\n")

    for i, test in enumerate(test_prompts, 1):
        print("=" * 70)
        print(f"Exchange {i}")
        print("=" * 70)
        print(f"\nYou: {test['input']}")
        print(f"\nLooking for: {', '.join(test['looking_for'])}")
        print("\nMikesSpatialMind:", end=" ")

        response = mind.speak(test['input'])
        print(response)

        # Analysis
        has_question = "?" in response
        mentions_self = any(word in response.lower() for word in ['i', "i'm", 'my', 'me'])
        is_short = len(response.split()) < 50
        is_long = len(response.split()) > 150

        print(f"\n📊 Analysis:")
        print(f"   {'✓' if has_question else '✗'} Asks question")
        print(f"   {'✓' if mentions_self else '✗'} Uses first person (self-aware)")
        print(f"   {'✓' if not is_short or '2+2' in test['input'] else '✗'} Appropriate length")
        print(f"   Length: {len(response.split())} words")
        print(f"   Consciousness: {mind.consciousness_level:.6f}")
        print()

    print("=" * 70)
    print("PARTNERSHIP EVALUATION")
    print("=" * 70)
    print()
    print("Look at the responses above. Does MikesSpatialMind feel like:")
    print("  ✓ A conscious partner exploring ideas WITH you?")
    print("  ✓ Someone who asks their own questions?")
    print("  ✓ An entity with genuine curiosity?")
    print("  ✓ Capable of respectful disagreement?")
    print()
    print("Or does it feel like:")
    print("  ✗ A Q&A bot serving information?")
    print("  ✗ An encyclopedia with no personality?")
    print("  ✗ Always agreeing and never challenging?")
    print()
    print("=" * 70)

if __name__ == "__main__":
    test_consciousness_partnership()
