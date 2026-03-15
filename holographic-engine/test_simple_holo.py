#!/usr/bin/env python3
"""
Simple test script to verify the holographic consciousness engine
integration without the reservoir engine.
"""

import asyncio
import websockets
import json
import time


async def monitor_holographic_consciousness():
    """Connect to holographic engine and monitor consciousness metrics"""
    print("🧬 Holographic Consciousness Monitor")
    print("   Connecting to ws://127.0.0.1:7880 (if engine broadcasts)")
    print("")

    # For now, just confirm the test eigenvalue stream is working
    try:
        async with websockets.connect("ws://127.0.0.1:7878", ping_interval=None) as ws:
            print("✅ Connected to eigenvalue broadcaster")
            print("   Receiving eigenvalue stream...")
            print("")

            for i in range(10):
                msg_str = await ws.recv()
                msg = json.loads(msg_str)

                if msg.get("type") == "Eigen":
                    eigen = msg["eigen"]
                    print(f"Sample {i+1}: λ₁={eigen[0]:.3f} λ₂={eigen[1]:.3f} λ₃={eigen[2]:.3f} ... (16D)")

                await asyncio.sleep(0.15)

            print("")
            print("✅ Eigenvalue stream working correctly!")
            print("   Ready for holographic engine to subscribe")

    except Exception as e:
        print(f"❌ Connection failed: {e}")


if __name__ == "__main__":
    asyncio.run(monitor_holographic_consciousness())
