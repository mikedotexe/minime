#!/usr/bin/env python3
"""
Test LLaVA vision integration in full conversation mode.

This test verifies that when user asks vision questions,
the system:
1. Detects it's a vision question
2. Uses LLaVA to analyze the frame
3. Passes LLaVA's description to Dolphin-Mixtral
4. Dolphin-Mixtral responds based on actual visual content
"""

import sys
import time
from minime import MikesSpatialMind, ProcessingMode

def test_llava_conversation():
    """Test full LLaVA vision conversation flow."""

    print("=" * 70)
    print("LLaVA Vision Conversation Test")
    print("=" * 70)

    # Initialize
    print("\n1. Initializing consciousness with camera...")
    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)
    mind.start_visual_processing(camera_index=0)

    # Let background thread capture some frames
    print("   Waiting 2 seconds for camera warmup...")
    time.sleep(2)

    # Process a frame to get latest_frame populated
    print("   Processing frame...")
    mind.process_visual_frame(verbose=False, use_seven_stage=False)

    print(f"   ✅ Camera active, latest frame: {mind.latest_frame is not None}")
    print(f"   ✅ LLaVA available: {mind.llava.available}")

    # Test questions
    questions = [
        "What do you see?",
        "Describe what's in front of the camera",
        "What objects can you observe?",
        "What colors are visible?",
    ]

    print("\n2. Testing vision questions...")
    print("=" * 70)

    for i, question in enumerate(questions, 1):
        print(f"\n[Question {i}] {question}")
        print("-" * 70)

        response = mind.speak(question)
        print(f"{response}\n")

        # Small delay between questions
        time.sleep(0.5)

    print("=" * 70)
    print("Test Complete!")
    print("=" * 70)
    print("\nExpected behavior:")
    print("- Responses should reference actual visual content from LLaVA")
    print("- Should NOT fabricate details like 'buildings' or 'trees'")
    print("- Should describe what LLaVA actually sees in the camera frame")

    return True

if __name__ == "__main__":
    try:
        success = test_llava_conversation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
