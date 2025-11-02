#!/usr/bin/env python3
"""Test if LLaVA is being called for vision questions."""

import time
import logging
from minime import MikesSpatialMind

# Enable detailed logging
logging.basicConfig(level=logging.INFO)

print("Testing LLaVA vision integration...")

# Initialize mind
mind = MikesSpatialMind()

# Check LLaVA availability
print(f"LLaVA available: {mind.llava.available}")

# Start camera
mind.start_visual_processing(camera_index=0)

# Wait for frames
print("Waiting for frame capture...")
for i in range(5):
    time.sleep(1)
    if mind.latest_frame is not None:
        print(f"✅ Frame ready! Shape: {mind.latest_frame.shape}")
        break

# Test vision questions
vision_questions = [
    "What do you see?",
    "Can you describe what's in front of the camera?",
    "What objects are visible?",
]

for question in vision_questions:
    print(f"\nQuestion: {question}")
    response = mind.speak(question)
    print(f"Response: {response[:150]}...")

    # Check if LLaVA was used
    if "video call" in response.lower() or "computer screen" in response.lower() or "laptop" in response.lower():
        print("✅ LLaVA appears to be working (specific details detected)")
    else:
        print("⚠️  Response seems generic (LLaVA may not be active)")

mind.stop_visual_processing()
print("\nTest complete!")