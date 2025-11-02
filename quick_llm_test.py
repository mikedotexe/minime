#!/usr/bin/env python3
"""Quick test to see if LLM is working."""

from minime import MikesSpatialMind

mind = MikesSpatialMind()

print(f"LLM Available: {mind.llm.available}")
print(f"LLaVA Available: {mind.llava.available}")

# Test non-vision question
print("\nTesting regular question...")
response = mind.speak("Hello, how are you?")
print(f"Response length: {len(response)}")
print(f"Response: {response[:100]}...")

# Test vision without camera
print("\nTesting vision question without camera...")
response = mind.speak("What do you see?")
print(f"Response length: {len(response)}")
print(f"Response: {response[:100]}...")