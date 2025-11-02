#!/usr/bin/env python3
"""Test WebSocket connection to Rust sensory engine."""

import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)

async def test_connection():
    uri = "ws://127.0.0.1:7878"

    try:
        logging.info(f"Attempting to connect to {uri}")
        async with websockets.connect(uri) as websocket:
            logging.info("✅ Connected successfully!")

            # Receive a few packets
            for i in range(5):
                message = await websocket.recv()
                packet = json.loads(message)
                logging.info(f"Received packet {i}: t_ms={packet.get('t_ms')}, eigenvalues={packet.get('eigenvalues', [])[:3]}")

    except Exception as e:
        logging.error(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())