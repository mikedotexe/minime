#!/usr/bin/env python3
"""
Synthetic Sensory Data Generator

Generates synthetic video and audio features to feed the ESN server.
Useful for testing without a camera or microphone.
"""

import asyncio
import json
import logging
import time
import numpy as np
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SyntheticSensory:
    def __init__(self, ws_uri: str = "ws://127.0.0.1:7879"):
        self.ws_uri = ws_uri
        self.running = False
        self.frame_count = 0

        # Oscillator states for smooth synthetic features
        self.video_phase = 0.0
        self.audio_phase = 0.0

    def generate_video_features(self) -> np.ndarray:
        """Generate smooth synthetic 8D video features."""
        # Create oscillating patterns at different frequencies
        t = self.video_phase
        features = np.array([
            0.5 + 0.3 * np.sin(t * 0.5),              # Slow brightness oscillation
            0.3 + 0.2 * np.cos(t * 0.7),              # Contrast variation
            0.4 + 0.3 * np.sin(t * 1.2),              # Edge energy
            0.35 + 0.25 * np.cos(t * 0.9),            # Motion energy
            0.5 + 0.2 * np.sin(t * 0.6 + 0.5),        # Quadrant 1
            0.5 + 0.2 * np.cos(t * 0.8 + 1.0),        # Quadrant 2
            0.5 + 0.2 * np.sin(t * 1.0 + 1.5),        # Quadrant 3
            0.5 + 0.2 * np.cos(t * 1.1 + 2.0),        # Quadrant 4
        ], dtype=np.float32)

        # Add small noise
        features += np.random.randn(8) * 0.05

        # Clip to [0, 1]
        features = np.clip(features, 0.0, 1.0)

        self.video_phase += 0.1
        return features

    def generate_audio_features(self) -> np.ndarray:
        """Generate smooth synthetic 8D audio features."""
        t = self.audio_phase
        features = np.array([
            0.4 + 0.3 * np.sin(t * 0.4),              # Low frequency energy
            0.35 + 0.25 * np.cos(t * 0.6),            # Mid frequency energy
            0.3 + 0.2 * np.sin(t * 1.5),              # High frequency energy
            0.25 + 0.15 * np.cos(t * 2.0),            # Spectral centroid
            0.5 + 0.3 * np.sin(t * 0.3),              # RMS energy
            0.4 + 0.2 * np.cos(t * 0.5),              # Zero crossing rate
            0.3 + 0.25 * np.sin(t * 1.0),             # Spectral rolloff
            0.35 + 0.2 * np.cos(t * 1.3),             # Spectral flux
        ], dtype=np.float32)

        # Add small noise
        features += np.random.randn(8) * 0.04

        # Clip to [0, 1]
        features = np.clip(features, 0.0, 1.0)

        self.audio_phase += 0.08
        return features

    async def run(self):
        """Main loop - generate and send synthetic features."""
        self.running = True
        logger.info(f"🎨 Starting synthetic sensory generator...")

        try:
            async with websockets.connect(self.ws_uri, ping_interval=None) as websocket:
                logger.info(f"✅ Connected to ESN server at {self.ws_uri}")

                while self.running:
                    # Generate video features
                    video_features = self.generate_video_features()
                    video_msg = {
                        "type": "VideoFeat",
                        "vec": video_features.tolist()
                    }
                    await websocket.send(json.dumps(video_msg))

                    # Generate audio features
                    audio_features = self.generate_audio_features()
                    audio_msg = {
                        "type": "AudioFeat",
                        "vec": audio_features.tolist()
                    }
                    await websocket.send(json.dumps(audio_msg))

                    self.frame_count += 1
                    if self.frame_count % 30 == 0:
                        logger.info(
                            f"📊 Sent {self.frame_count} frames | "
                            f"Video: [{video_features[0]:.2f}, {video_features[1]:.2f}, ...] | "
                            f"Audio: [{audio_features[0]:.2f}, {audio_features[1]:.2f}, ...]"
                        )

                    # Run at 10 FPS
                    await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("\n🛑 Shutting down...")
        except Exception as e:
            logger.error(f"❌ Error: {e}")
        finally:
            self.running = False
            logger.info("✅ Synthetic sensory generator stopped")

    def stop(self):
        """Stop the generator."""
        self.running = False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synthetic Sensory Data Generator")
    parser.add_argument("--ws-uri", default="ws://127.0.0.1:7879", help="WebSocket URI for ESN server input")
    parser.add_argument("--fps", type=float, default=10.0, help="Frames per second")
    args = parser.parse_args()

    generator = SyntheticSensory(ws_uri=args.ws_uri)

    try:
        asyncio.run(generator.run())
    except KeyboardInterrupt:
        logger.info("\nShutdown requested")
        generator.stop()
