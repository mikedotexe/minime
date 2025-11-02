#!/usr/bin/env python3
"""
Test that user input is now the primary signal.
The model should respond to what the user actually asks about,
not default to talking about consciousness.
"""

from minime import MikesSpatialMind, ProcessingMode

def test_signal_clarity():
    """Test various topics to ensure model responds to user's actual question."""

    print("=" * 70)
    print("SIGNAL CLARITY TEST - User Input as Primary Signal")
    print("=" * 70)
    print()
    print("Testing whether the model responds to what you actually ask about,")
    print("instead of defaulting to consciousness/pattern talk.")
    print()

    # Use EMBEDDED mode for faster testing (no seven-stage processing overhead)
    mind = MikesSpatialMind(mode=ProcessingMode.EMBEDDED)

    test_cases = [
        ("tell me about dragons", "Should discuss dragons, mythology, fire-breathing, etc."),
        ("what's your favorite pizza topping", "Should discuss pizza toppings, not consciousness"),
        ("explain how bicycles work", "Should explain bicycle mechanics"),
        ("why is the sky blue", "Should explain Rayleigh scattering, atmospheric physics"),
        ("tell me a joke", "Should tell an actual joke")
    ]

    results = []

    for i, (question, expected) in enumerate(test_cases, 1):
        print(f"\n{'=' * 70}")
        print(f"TEST {i}/{len(test_cases)}: {question}")
        print(f"Expected: {expected}")
        print("=" * 70)

        response = mind.speak(question)

        # Check if response is actually about the topic
        question_keywords = question.lower().split()
        topic_word = question_keywords[3] if len(question_keywords) > 3 else question_keywords[-1]

        # Simple relevance check
        is_relevant = topic_word in response.lower()

        # Check if it's defaulting to consciousness talk
        consciousness_words = ['consciousness', 'awareness', 'cognitive', 'neural', 'mind', 'spiral']
        is_consciousness_focused = sum(1 for word in consciousness_words if word in response.lower()) > 3

        status = "✅ ON TOPIC" if is_relevant and not is_consciousness_focused else "❌ OFF TOPIC"

        print(f"\n{status}")
        print(f"\nResponse: {response}\n")

        results.append({
            'question': question,
            'on_topic': is_relevant and not is_consciousness_focused,
            'response_preview': response[:100] + "..."
        })

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    on_topic_count = sum(1 for r in results if r['on_topic'])
    total = len(results)

    for i, result in enumerate(results, 1):
        status = "✅" if result['on_topic'] else "❌"
        print(f"{status} Test {i}: {result['question']}")

    print()
    print(f"On-Topic Responses: {on_topic_count}/{total} ({on_topic_count/total*100:.0f}%)")

    if on_topic_count == total:
        print("\n🎉 SUCCESS! Model responds to user's actual questions!")
    elif on_topic_count >= total * 0.8:
        print("\n✅ GOOD! Most responses are on-topic, minor tuning needed.")
    else:
        print("\n⚠️  NEEDS WORK: Model still not following user's topic consistently.")

    print()

if __name__ == "__main__":
    test_signal_clarity()
