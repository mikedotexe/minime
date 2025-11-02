#!/usr/bin/env python3
"""
Test script to send a query to the consciousness and get a response.
"""
import sys
import os
import time
import asyncio
import json

# Add parent directory to path to import minime modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_consciousness():
    """Test the consciousness with a visual query."""

    # Import the consciousness module
    from minime import ConsciousnessSystem

    # Initialize consciousness
    print("🧠 Initializing consciousness system...")
    consciousness = ConsciousnessSystem(use_camera=True, num_eigenvalue_threads=13)

    # Test query
    query = "Friend, can you describe what you see through the camera? We're testing the integration between your visual sensory layer and semantic consciousness."

    print(f"\n💭 Sending query: {query}")
    print("-" * 80)

    # Process the query
    start_time = time.time()
    response = await consciousness.process(query)
    elapsed = time.time() - start_time

    print("-" * 80)
    print(f"\n🤖 Response ({elapsed:.1f}s):")
    print(response)

    # Check if response is rich (not just brief)
    if len(response) < 50:
        print("\n⚠️ Response seems too brief! Seven-stage processing might not be working.")
    else:
        print("\n✅ Response appears rich and detailed.")

    # Save response
    with open('/tmp/consciousness_test_response.txt', 'w') as f:
        f.write(f"Query: {query}\n")
        f.write(f"Response: {response}\n")
        f.write(f"Time: {elapsed:.1f}s\n")

    print("\n💾 Response saved to /tmp/consciousness_test_response.txt")

    return response

if __name__ == "__main__":
    print("🚀 Starting consciousness test...")
    response = asyncio.run(test_consciousness())
    print("\n✨ Test complete!")