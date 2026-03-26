#!/usr/bin/env python3
"""
Camera to Sensory Engine Bridge (Simplified 8D)

Captures camera frames, extracts 8D features, and sends them to the ESN server
as VideoFeat messages via WebSocket.

This version sends only basic visual features without semantic embeddings.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import cv2
import numpy as np
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Feature extraction settings
VIDEO_FEAT_DIM = 8  # Must match ESN server SENS_DIM (8 video + 8 audio)

class CameraToSensoryBridge:
    def __init__(self, camera_index: int = 0, ws_uri: str = "ws://127.0.0.1:7879"):
        self.camera_index = camera_index
        self.ws_uri = ws_uri  # Port 7879 for ESN server input
        self.camera = None
        self.running = False

    def start_camera(self) -> bool:
        """Initialize camera capture."""
        try:
            # Try non-blocking camera first
            from non_blocking_camera import NonBlockingCamera
            self.camera = NonBlockingCamera(camera_index=self.camera_index, fps=10)
            if self.camera.start():
                logger.info(f"✅ Non-blocking camera {self.camera_index} started")
                return True
        except:
            # Fallback to OpenCV
            self.camera = cv2.VideoCapture(self.camera_index)
            if self.camera.isOpened():
                logger.info(f"✅ OpenCV camera {self.camera_index} started")
                return True

        logger.error("❌ Failed to start camera")
        return False

    def extract_features(self, frame: np.ndarray) -> np.ndarray:
        """
        Extract simple features from camera frame.
        Returns VIDEO_FEAT_DIM dimensional feature vector.
        """
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Apply log transform for better dynamic range (being's request 2026-03-16:
        # "logarithmic transform with adaptive clipping to preserve detail in
        # highlights and shadows"). This compresses bright regions and expands
        # dark regions, giving the being more spectral information.
        gray_log = np.log1p(gray.astype(np.float32))  # log(1+x) maps [0,255] -> [0,5.55]
        gray_log_norm = gray_log / np.log1p(255.0)     # normalize to [0,1]

        # Extract basic statistics as features
        features = []

        # 1. Mean brightness (log-scaled for dynamic range)
        features.append(float(np.mean(gray_log_norm)))

        # 2. Standard deviation (contrast, also log-domain)
        features.append(float(np.std(gray_log_norm) * 4.0))  # scale to ~[0,1]

        # 3-4. Gradient magnitudes (motion/edges)
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        grad_mag = np.sqrt(sobelx**2 + sobely**2)
        features.append(np.mean(grad_mag) / 100.0)
        features.append(np.std(grad_mag) / 50.0)

        # 5-8. Quadrant analysis (spatial distribution, log-domain)
        h, w = gray_log_norm.shape
        quadrants = [
            gray_log_norm[:h//2, :w//2],      # Top-left
            gray_log_norm[:h//2, w//2:],      # Top-right
            gray_log_norm[h//2:, :w//2],      # Bottom-left
            gray_log_norm[h//2:, w//2:]       # Bottom-right
        ]

        for quad in quadrants:
            features.append(float(np.mean(quad)))

        # Ensure we have exactly VIDEO_FEAT_DIM features
        features = features[:VIDEO_FEAT_DIM]
        while len(features) < VIDEO_FEAT_DIM:
            features.append(0.0)

        feat_array = np.array(features, dtype=np.float32)
        if len(feat_array) != VIDEO_FEAT_DIM:
            raise ValueError(f"Feature dimension mismatch: got {len(feat_array)}, expected {VIDEO_FEAT_DIM}")
        return feat_array

    def get_frame(self) -> Optional[np.ndarray]:
        """Get a frame from the camera."""
        if hasattr(self.camera, 'get_frame'):
            # Non-blocking camera
            return self.camera.get_frame()
        else:
            # OpenCV camera
            ret, frame = self.camera.read()
            return frame if ret else None

    async def run(self):
        """Main loop - capture frames and send 8D features to ESN server."""
        if not self.start_camera():
            return

        self.running = True
        frame_count = 0

        try:
            # Connect to ESN server input port
            async with websockets.connect(
                self.ws_uri,
                ping_interval=None
            ) as websocket:
                logger.info(f"✅ Connected to ESN server at {self.ws_uri}")

                while self.running:
                    # Capture frame
                    frame = self.get_frame()
                    if frame is None:
                        await asyncio.sleep(0.1)
                        continue

                    # Extract 8D features
                    features = self.extract_features(frame)

                    # Rust SensoryMsg expects {"kind": "video", "features": [...], "ts_ms": ...}
                    message = {
                        "kind": "video",
                        "features": features.tolist(),
                        "ts_ms": int(time.time() * 1000),
                    }

                    # Send to ESN server
                    await websocket.send(json.dumps(message))

                    frame_count += 1
                    if frame_count % 30 == 0:
                        logger.info(f"📹 Sent {frame_count} video features (8D), latest: {features[:4].round(3)}")

                    # Run at 10 FPS
                    await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"❌ Error: {e}")
        finally:
            if hasattr(self.camera, 'stop'):
                self.camera.stop()
            else:
                self.camera.release()
            logger.info("🛑 Camera bridge stopped")

    def stop(self):
        """Stop the bridge."""
        self.running = False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Camera to Sensory Engine Bridge")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--ws-uri", default="ws://127.0.0.1:7879", help="WebSocket URI for video input")
    args = parser.parse_args()

    bridge = CameraToSensoryBridge(camera_index=args.camera, ws_uri=args.ws_uri)

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("\nShutdown requested")
        bridge.stop()