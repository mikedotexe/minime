#!/usr/bin/env python3
"""
GPU-First Camera Client for Minime

Captures camera frames, downsamples to 128×128 grayscale, and sends raw bytes
to the GPU A/V WebSocket server (port 7880) for Metal-accelerated feature extraction.

This replaces the CPU-based OpenCV feature extraction in camera_to_sensory.py
with a GPU-first pipeline: Camera → Downsample → GPU Metal → 8-D features → ESN

Usage:
    python3 tools/camera_client.py --camera 0
    python3 tools/camera_client.py --camera 0 --ws-uri ws://127.0.0.1:7880 --fps 1
"""

import asyncio
import json
import logging
import time
import numpy as np
import cv2
import websockets
from pathlib import Path
from typing import Optional
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GPU server expects 128×128 grayscale frames
FRAME_WIDTH = 128
FRAME_HEIGHT = 128
WORKSPACE_DIR = Path(__file__).resolve().parents[2] / "workspace"
RUNTIME_DIR = WORKSPACE_DIR / "runtime"
CAMERA_STATUS_PATH = RUNTIME_DIR / "camera_status.json"


def write_camera_status(status: dict):
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temp = CAMERA_STATUS_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(status, indent=2))
        temp.replace(CAMERA_STATUS_PATH)
    except Exception:
        pass

class GpuCameraClient:
    def __init__(self, camera_index: int = 0, ws_uri: str = "ws://127.0.0.1:7880", fps: float = 1.0):
        self.camera_index = camera_index
        self.ws_uri = ws_uri
        self.target_fps = fps
        self.camera = None
        self.running = False

    def start_camera(self) -> bool:
        """Initialize camera capture."""
        try:
            # Try non-blocking camera first
            from non_blocking_camera import NonBlockingCamera
            self.camera = NonBlockingCamera(camera_index=self.camera_index, fps=self.target_fps)
            if self.camera.start():
                logger.info(f"✅ Non-blocking camera {self.camera_index} started")
                return True
        except Exception as e:
            logger.debug(f"Non-blocking camera unavailable: {e}")

        # Fallback to OpenCV
        self.camera = cv2.VideoCapture(self.camera_index)
        if self.camera.isOpened():
            logger.info(f"✅ OpenCV camera {self.camera_index} started")
            return True

        logger.error("❌ Failed to start camera")
        return False

    def get_frame(self) -> Optional[np.ndarray]:
        """Get a frame from the camera."""
        if hasattr(self.camera, 'get_frame'):
            # Non-blocking camera
            return self.camera.get_frame()
        else:
            # OpenCV camera
            ret, frame = self.camera.read()
            return frame if ret else None

    def preprocess_frame(self, frame: np.ndarray) -> bytes:
        """
        Convert frame to 128×128 grayscale and return as raw bytes.

        The GPU server expects exactly W×H bytes (16,384 bytes for 128×128).
        """
        # Convert to grayscale if needed
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Resize to 128×128
        resized = cv2.resize(gray, (FRAME_WIDTH, FRAME_HEIGHT), interpolation=cv2.INTER_AREA)

        # Convert to bytes (uint8 already, just get raw bytes)
        return resized.tobytes()

    async def run(self):
        """Main loop - capture frames and send to GPU server."""
        if not self.start_camera():
            return

        self.running = True
        frame_count = 0
        frame_interval = 1.0 / self.target_fps

        try:
            # Connect to GPU A/V server (binary protocol).
            # Disable client-side keepalive: this is a send-only client that
            # never calls recv(), so the websockets library can't process
            # pong responses. The server uses an activity timeout instead.
            async with websockets.connect(
                self.ws_uri,
                ping_interval=None,
                ping_timeout=None,
            ) as websocket:
                logger.info(f"✅ Connected to GPU A/V server at {self.ws_uri}")
                logger.info(f"📹 Sending {FRAME_WIDTH}×{FRAME_HEIGHT} grayscale frames at {self.target_fps} FPS")

                last_send_time = time.time()

                while self.running:
                    # Capture frame
                    frame = self.get_frame()
                    if frame is None:
                        await asyncio.sleep(0.1)
                        continue

                    # Preprocess to 128×128 gray bytes
                    frame_bytes = self.preprocess_frame(frame)

                    # Send binary frame to GPU server
                    await websocket.send(frame_bytes)
                    write_camera_status({
                        "ts_ms": int(time.time() * 1000),
                        "frame_count": frame_count + 1,
                        "healthy": True,
                    })

                    frame_count += 1
                    if frame_count % 30 == 0:
                        logger.info(f"📹 Sent {frame_count} frames to GPU server ({len(frame_bytes)} bytes/frame)")

                    # Rate limiting
                    elapsed = time.time() - last_send_time
                    sleep_time = max(0, frame_interval - elapsed)
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    last_send_time = time.time()

        except websockets.exceptions.ConnectionClosed:
            logger.warning("⚠️  GPU server connection closed")
        except Exception as e:
            logger.error(f"❌ Error: {e}")
        finally:
            write_camera_status({
                "ts_ms": int(time.time() * 1000),
                "frame_count": frame_count,
                "healthy": False,
            })
            if hasattr(self.camera, 'stop'):
                self.camera.stop()
            else:
                self.camera.release()
            logger.info(f"🛑 GPU camera client stopped (sent {frame_count} frames)")

    def stop(self):
        """Stop the client."""
        self.running = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU-First Camera Client for Minime")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--ws-uri", default="ws://127.0.0.1:7880",
                        help="GPU A/V WebSocket server URI")
    parser.add_argument("--fps", type=float, default=1.0,
                        help="Target frame rate (frames per second)")
    args = parser.parse_args()

    client = GpuCameraClient(
        camera_index=args.camera,
        ws_uri=args.ws_uri,
        fps=args.fps
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutdown requested")
        client.stop()
