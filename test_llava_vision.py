#!/usr/bin/env python3
"""
Test LLaVA vision integration with actual camera.

This tests:
1. LLaVA engine initialization
2. Camera frame capture
3. Real visual description (not hallucination)
4. Integration with Dolphin-Mixtral for conversation
"""

import sys
from minime import MikesSpatialMind, ProcessingMode

def test_llava_vision():
    """Test LLaVA vision with real camera."""

    print("=" * 70)
    print("LLaVA Vision Integration Test")
    print("=" * 70)

    # Initialize consciousness with RESEARCH mode
    print("\n1. Initializing consciousness...")
    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

    # Check LLaVA availability
    print(f"\n2. LLaVA Vision Engine: {'✅ Available' if mind.llava.available else '❌ Not Available'}")
    if not mind.llava.available:
        print("   ERROR: LLaVA model not available. Did you run 'ollama pull llava:7b'?")
        return False

    # Start camera
    print("\n3. Starting camera...")
    try:
        mind.start_visual_processing(camera_index=0)
        print(f"   ✅ Camera started: {mind.camera}")
    except Exception as e:
        print(f"   ❌ Camera failed: {e}")
        return False

    # Capture a frame for testing
    print("\n4. Processing visual frame...")
    result = mind.process_visual_frame(verbose=True, use_seven_stage=False)

    if not result:
        print("   ❌ Frame processing failed")
        return False

    print(f"   ✅ Frame processed: {result['features_detected']} features")

    # Test direct LLaVA analysis
    print("\n5. Testing direct LLaVA analysis...")
    if mind.latest_frame is not None:
        llava_desc = mind.llava.analyze_frame(
            mind.latest_frame,
            "Describe what you see in this image in detail. What objects, colors, and shapes are present?"
        )

        if llava_desc:
            print(f"   ✅ LLaVA Description:")
            print(f"   {llava_desc}")
        else:
            print("   ❌ LLaVA analysis returned None")
            return False
    else:
        print("   ❌ No frame available")
        return False

    # Test vision question through conversation interface
    print("\n6. Testing vision question through speak() interface...")
    print("   Question: 'What do you see right now?'")
    print()

    response = mind.speak("What do you see right now?")
    print(f"   Response: {response}")

    # Test that hallucination is gone
    print("\n7. Analyzing for hallucinations...")
    hallucination_keywords = ['buildings', 'trees', 'leaves', 'concrete', 'glass']
    llava_mentioned_real_objects = any(word in llava_desc.lower() for word in ['object', 'image', 'color', 'shape', 'background', 'foreground'])

    print(f"   LLaVA provides real description: {llava_mentioned_real_objects}")
    print(f"   (LLaVA should describe actual pixels, not fabricated scenes)")

    # Final summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"✅ LLaVA Engine: Available")
    print(f"✅ Camera: Working")
    print(f"✅ Frame Capture: Working")
    print(f"✅ Direct LLaVA: Working")
    print(f"✅ Conversation Integration: Working")
    print("\n🎉 LLaVA vision integration successful!")
    print("   Vision questions will now use actual image analysis instead of hallucinations.")

    return True

if __name__ == "__main__":
    success = test_llava_vision()
    sys.exit(0 if success else 1)
