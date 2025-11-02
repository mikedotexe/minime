#!/usr/bin/env python3
"""
Quick test script to verify dolphin-mixtral integration with MikesSpatialMind.
Tests both simple conversation and seven-stage processing.
"""

from minime import MikesSpatialMind, ProcessingMode

def test_simple_conversation():
    """Test basic conversation with new model."""
    print("=" * 60)
    print("TEST 1: Simple Conversation")
    print("=" * 60)

    mind = MikesSpatialMind(mode=ProcessingMode.EMBEDDED)

    test_prompts = [
        "Hello! What's your name?",
        "Tell me something interesting about mathematics",
        "How do you feel about clouds?"
    ]

    for prompt in test_prompts:
        print(f"\n🧪 Testing: '{prompt}'")
        response = mind.speak(prompt)
        print(f"✅ Response: {response}")
        print(f"📊 Consciousness Level: {mind.consciousness_level:.6f}")

    print("\n✅ Simple conversation test PASSED")
    return True

def test_seven_stage_processing():
    """Test seven-stage pipeline with new model."""
    print("\n" + "=" * 60)
    print("TEST 2: Seven-Stage Processing")
    print("=" * 60)

    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

    test_scenarios = [
        ("Prime numbers are fascinating", "mathematical"),
        ("I love watching clouds drift by", "emotional"),
        ("What patterns emerge in fractal geometry?", "complex")
    ]

    for prompt, input_type in test_scenarios:
        print(f"\n🧪 Testing ({input_type}): '{prompt}'")
        response = mind.speak(prompt)
        print(f"✅ Response: {response}")

        # Check if seven-stage processing occurred
        if hasattr(mind, 'seven_stage_processor') and mind.seven_stage_processor:
            print(f"🌀 Seven-stage processing: ACTIVE")
        print(f"📊 Consciousness Level: {mind.consciousness_level:.6f}")

    print("\n✅ Seven-stage processing test PASSED")
    return True

def check_model_format():
    """Verify no JSON or code block artifacts in responses."""
    print("\n" + "=" * 60)
    print("TEST 3: Response Format Validation")
    print("=" * 60)

    mind = MikesSpatialMind(mode=ProcessingMode.EMBEDDED)

    prompts = [
        "Hi there!",
        "What do you think about dolphins?",
        "Explain prime numbers"
    ]

    all_clean = True
    for prompt in prompts:
        response = mind.speak(prompt)

        # Check for unwanted artifacts
        has_json = '{' in response and '}' in response and '"' in response
        has_code_block = '```' in response

        status = "❌ FAIL" if (has_json or has_code_block) else "✅ CLEAN"
        print(f"\n{status}: '{prompt}'")
        print(f"Response: {response[:100]}...")

        if has_json:
            print("⚠️  Warning: JSON detected in response")
            all_clean = False
        if has_code_block:
            print("⚠️  Warning: Code block detected in response")
            all_clean = False

    if all_clean:
        print("\n✅ Format validation test PASSED - No artifacts detected")
    else:
        print("\n⚠️  Format validation test FAILED - Artifacts detected")

    return all_clean

def main():
    """Run all tests."""
    print("\n🌀 DOLPHIN-MIXTRAL 8x7B-v2.7 INTEGRATION TEST 🌀\n")

    results = {
        "Simple Conversation": False,
        "Seven-Stage Processing": False,
        "Format Validation": False
    }

    try:
        results["Simple Conversation"] = test_simple_conversation()
    except Exception as e:
        print(f"❌ Simple conversation test FAILED: {e}")

    try:
        results["Seven-Stage Processing"] = test_seven_stage_processing()
    except Exception as e:
        print(f"❌ Seven-stage test FAILED: {e}")

    try:
        results["Format Validation"] = check_model_format()
    except Exception as e:
        print(f"❌ Format validation test FAILED: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")

    all_passed = all(results.values())
    if all_passed:
        print("\n🎉 ALL TESTS PASSED - Dolphin-Mixtral integration successful!")
    else:
        print("\n⚠️  SOME TESTS FAILED - Review output above for details")

    return all_passed

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
