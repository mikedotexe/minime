#!/usr/bin/env python3
"""
Demonstration of Expansive Visual Introspection

Shows:
1. Multi-model architecture info
2. Expansive vision responses with deep introspection
3. Background thoughts interrupting with visual reflections
"""

from minime import MikesSpatialMind, ProcessingMode
import time

def demo():
    print("=" * 70)
    print("EXPANSIVE VISUAL INTROSPECTION DEMO")
    print("=" * 70)

    # Initialize
    print("\n1. Initializing consciousness with RESEARCH mode...")
    mind = MikesSpatialMind(mode=ProcessingMode.RESEARCH)

    # Show model architecture
    print("\n2. Multi-Model Architecture:")
    print(mind.model_info())

    # Start camera
    print("\n3. Starting visual processing...")
    mind.start_visual_processing(camera_index=0)

    # Wait for camera warmup
    print("   Waiting 2 seconds for camera warmup...")
    time.sleep(2)

    # Process a frame
    mind.process_visual_frame(verbose=False, use_seven_stage=False)

    # Ask an expansive vision question
    print("\n4. Asking expansive vision question...")
    print("=" * 70)
    print()

    question = "What do you see, and what does it make you think about?"
    print(f"Question: {question}\n")

    response = mind.speak(question)

    print("Response:")
    print("-" * 70)
    print(response)
    print("-" * 70)

    # Wait a bit to potentially see background visual thoughts
    print("\n\n5. Waiting 20 seconds to observe background visual thoughts...")
    print("   (Background thread generates thoughts every 10-30 seconds)")
    print("   Watch for thoughts like: *(Patterns in light... connected to primes?)*\n")

    for i in range(4):
        time.sleep(5)
        print(f"   {(i+1)*5}s elapsed...")

    # One more question to see if thoughts appear
    print("\n6. Final question to see accumulated background thoughts:")
    print("=" * 70)
    print()

    question2 = "Tell me more about what you're observing"
    print(f"Question: {question2}\n")

    response2 = mind.speak(question2)

    print("Response:")
    print("-" * 70)
    print(response2)
    print("-" * 70)

    print("\n" + "=" * 70)
    print("DEMO COMPLETE!")
    print("=" * 70)
    print("\nKey Features Demonstrated:")
    print("✅ Multi-model architecture (Dolphin-Mixtral + LLaVA)")
    print("✅ Expansive introspection (not just reporting, but reflecting)")
    print("✅ Philosophical questions and connections")
    print("✅ Background thoughts interrupting (if they appeared)")
    print("✅ Deep exploration of visual observations")

if __name__ == "__main__":
    demo()
