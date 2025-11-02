#!/usr/bin/env python3
"""Quick test to verify visual processing thread is capturing frames."""

import time
from minime import MikesSpatialMind

print("Testing visual processing thread...")

# Initialize mind with camera
mind = MikesSpatialMind()
mind.start_visual_processing(camera_index=0)

print("Waiting for frames to be captured...")

# Check for frames over time
for i in range(10):
    time.sleep(1)
    if mind.latest_frame is not None:
        print(f"✅ Frame captured after {i+1} seconds!")
        print(f"   Frame shape: {mind.latest_frame.shape}")
        print(f"   Visual memories: {len(mind.visual_memories)}")

        # Now test a vision question
        response = mind.speak("What do you see?")
        print(f"\nVision response: {response[:200]}...")
        break
else:
    print("❌ No frames captured after 10 seconds")

mind.stop_visual_processing()
print("\nTest complete!")