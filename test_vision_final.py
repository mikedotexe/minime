#!/usr/bin/env python3
"""Final test to confirm vision is working properly."""

import time
import logging
from minime import MikesSpatialMind

# Enable INFO logging to see LLaVA messages
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("=" * 70)
print("Final Vision Integration Test")
print("=" * 70)

# Initialize mind
mind = MikesSpatialMind()

print(f"\n✅ LLaVA Engine: {'Available' if mind.llava.available else 'Not Available'}")

# Start camera
print("✅ Starting camera...")
mind.start_visual_processing(camera_index=0)

# Wait for background thread to capture frames
print("⏳ Waiting for frame capture (3 seconds)...")
time.sleep(3)

print(f"✅ Frame available: {mind.latest_frame is not None}")
if mind.latest_frame is not None:
    print(f"   Shape: {mind.latest_frame.shape}")

# Test a vision question
print("\n" + "=" * 70)
print("Testing Vision Question")
print("=" * 70)

question = "Can you describe what you see in front of the camera?"
print(f"\nQuestion: {question}")
print("\nResponse:")

response = mind.speak(question)
print(response)

# Check if LLaVA was used
print("\n" + "=" * 70)
if any(word in response.lower() for word in ['computer', 'screen', 'laptop', 'monitor', 'desk', 'camera', 'video']):
    print("✅ SUCCESS: Response contains specific visual details (LLaVA is working!)")
else:
    print("⚠️  WARNING: Response seems generic (check logs above)")

# Cleanup
mind.stop_visual_processing()
print("\n✅ Test complete!")
print("\nYou can now run: python3 minime.py --camera 0")
print("And ask questions like:")
print("  - 'What do you see?'")
print("  - 'Can you describe me?'")
print("  - 'What's in front of the camera?'")