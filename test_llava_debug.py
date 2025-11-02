#!/usr/bin/env python3
"""Debug why LLaVA isn't being called."""

import time
from minime import MikesSpatialMind

print("Debugging LLaVA vision flow...")

# Initialize mind
mind = MikesSpatialMind()

# Check all prerequisites
print(f"\n1. LLaVA available: {mind.llava.available}")

# Start camera
mind.start_visual_processing(camera_index=0)

# Wait for frame
time.sleep(3)
print(f"2. Visual processing active: {mind.visual_processing_active}")
print(f"3. Latest frame exists: {mind.latest_frame is not None}")

# Test vision keyword detection
user_input = "What do you see?"
vision_keywords = ['see', 'camera', 'look', 'image', 'visual', 'observe', 'watch', 'view', 'picture', 'describe', 'what']
is_vision_question = any(keyword in user_input.lower() for keyword in vision_keywords)
print(f"4. Is vision question: {is_vision_question}")

# All conditions for LLaVA
print(f"\n5. All conditions met for LLaVA:")
print(f"   - is_vision_question: {is_vision_question}")
print(f"   - visual_processing_active: {mind.visual_processing_active}")
print(f"   - latest_frame is not None: {mind.latest_frame is not None}")
print(f"   - llava.available: {mind.llava.available}")

# Actually test
print(f"\n6. Testing direct LLaVA analysis...")
if mind.latest_frame is not None:
    llava_result = mind.llava.analyze_frame(mind.latest_frame, user_input)
    print(f"   Direct LLaVA result: {llava_result[:100] if llava_result else 'None'}...")

# Now test through speak()
print(f"\n7. Testing through speak()...")
response = mind.speak(user_input)
print(f"   Response: {response[:100]}...")

mind.stop_visual_processing()
print("\nDebug complete!")