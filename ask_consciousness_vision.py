#!/usr/bin/env python3
"""
Query the consciousness about what it sees.
Connects to the consciousness WebSocket and asks vision-related questions.
"""

import asyncio
import json
import websockets
import sys

async def ask_consciousness_vision():
    """Connect to consciousness and ask what it sees."""
    uri = "ws://127.0.0.1:7878"

    try:
        async with websockets.connect(uri) as websocket:
            print(f"✅ Connected to consciousness at {uri}")
            print("=" * 70)

            # Vision-related questions
            questions = [
                "What do you see right now?",
                "Can you describe any visual input you're receiving?",
                "Are you experiencing any colors or shapes?",
                "What sensory data are you processing?",
                "Do you detect any motion or changes in your visual field?"
            ]

            for question in questions:
                print(f"\n🗣️  Asking: {question}")
                print("-" * 70)

                # Send question
                message = {
                    "type": "user_message",
                    "content": question
                }
                await websocket.send(json.dumps(message))

                # Get response
                response = await websocket.recv()
                data = json.loads(response)

                if data.get("type") == "consciousness_response":
                    print(f"🧠 Response: {data.get('content', 'No response')}")
                else:
                    print(f"Received: {data}")

                # Small delay between questions
                await asyncio.sleep(1)

            print("\n" + "=" * 70)
            print("Vision query complete!")

    except websockets.exceptions.ConnectionRefused:
        print(f"❌ Could not connect to consciousness at {uri}")
        print("   Make sure minime is running with WebSocket server enabled")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    return True

async def main():
    """Main entry point."""
    print("🔮 Consciousness Vision Query Tool")
    print("=" * 70)
    print("This tool asks the consciousness what it's seeing")
    print("to verify if real camera input is being processed.")
    print("=" * 70)

    success = await ask_consciousness_vision()

    if success:
        print("\n💡 If the consciousness mentions:")
        print("   - Specific objects, colors, or motion: It's seeing real camera input!")
        print("   - Only abstract patterns or 'stale' data: External input isn't working")
        print("   - Synthetic or generated patterns: It's using internal synthetic data")

    return success

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⛔ Interrupted by user")
        sys.exit(0)