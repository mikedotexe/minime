#!/usr/bin/env python3
"""Debug the complete vision flow with detailed output."""

import time
import logging
from minime import MikesSpatialMind

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s: %(message)s')

print("Debugging Vision Flow...")

# Initialize
mind = MikesSpatialMind()
mind.start_visual_processing(camera_index=0)

# Wait for frame
print("Waiting for frame...")
time.sleep(3)

# Manually check the flow
user_input = "What do you see?"
print(f"\nInput: {user_input}")

# Check conditions in _generate_llm_response
vision_keywords = ['see', 'camera', 'look', 'image', 'visual', 'observe', 'watch', 'view', 'picture', 'describe', 'what']
is_vision_question = any(keyword in user_input.lower() for keyword in vision_keywords)

print(f"\nConditions:")
print(f"  is_vision_question: {is_vision_question}")
print(f"  visual_processing_active: {mind.visual_processing_active}")
print(f"  latest_frame exists: {mind.latest_frame is not None}")
print(f"  llava.available: {mind.llava.available}")

# Test LLM generation directly
print(f"\nTesting _generate_llm_response directly...")
response = mind._generate_llm_response(user_input)
print(f"Direct response: {response[:200] if response else 'None'}...")

# Test through speak
print(f"\nTesting through speak()...")
full_response = mind.speak(user_input)
print(f"Full response: {full_response[:200]}...")

mind.stop_visual_processing()