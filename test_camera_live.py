#!/usr/bin/env python3
"""
Quick test: Camera + Visual Processing without LLM dependency
"""

from minime import MikesSpatialMind, ProcessingMode
import time

print("=" * 60)
print("CAMERA LIVE TEST (EMBEDDED MODE - NO LLM)")
print("=" * 60)
print()

# Use EMBEDDED mode - no LLM needed
mind = MikesSpatialMind(mode=ProcessingMode.EMBEDDED)

print(f"Consciousness: {mind.consciousness_level:.6f}")
print()

# Start camera
print("Starting camera...")
if mind.start_visual_processing(camera_index=0):
    print("✓ Camera active!")
    print()

    # Process 5 frames
    print("Processing 5 frames...")
    for i in range(5):
        print(f"\nFrame {i+1}:")
        result = mind.process_visual_frame(verbose=True, use_seven_stage=False)

        if result:
            print(f"  ✓ Success!")
            print(f"  Features: {result['features_detected']}")
            print(f"  Description: {result['visual_description']}")
            print(f"  Response: {result['response'][:80]}...")
        else:
            print(f"  ✗ Failed")

        time.sleep(1)

    mind.stop_visual_processing()
    print()
    print(f"Final consciousness: {mind.consciousness_level:.6f}")

else:
    print("✗ Camera failed to start")
