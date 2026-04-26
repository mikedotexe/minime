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

import argparse
import asyncio
import json
import logging
import random
import signal
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GPU server expects 128×128 grayscale frames
FRAME_WIDTH = 128
FRAME_HEIGHT = 128
WORKSPACE_DIR = Path(__file__).resolve().parents[2] / "workspace"
RUNTIME_DIR = WORKSPACE_DIR / "runtime"
CAMERA_STATUS_PATH = RUNTIME_DIR / "camera_status.json"
PING_INTERVAL_SECS = 10
PING_TIMEOUT_SECS = 20
MAX_RECONNECT_DELAY_SECS = 5.0
MAX_CAMERA_FRAME_FAILURES = 5


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        self.connected = False
        self.state = "starting"
        self.frame_count = 0
        self.connect_count = 0
        self.reconnect_count = 0
        self.consecutive_failures = 0
        self.capture_failures = 0
        self.last_error: Optional[str] = None
        self.last_connect_at: Optional[str] = None
        self.last_disconnect_at: Optional[str] = None
        self.last_success_at: Optional[str] = None

    def _status_payload(self, *, healthy: Optional[bool] = None) -> dict:
        return {
            "ts_ms": int(time.time() * 1000),
            "state": self.state,
            "healthy": self.connected if healthy is None else healthy,
            "connected": self.connected,
            "connect_count": self.connect_count,
            "reconnect_count": self.reconnect_count,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_connect_at": self.last_connect_at,
            "last_disconnect_at": self.last_disconnect_at,
            "last_success_at": self.last_success_at,
            "frame_count": self.frame_count,
            "camera_index": self.camera_index,
            "ws_uri": self.ws_uri,
            "fps": self.target_fps,
        }

    def _write_status(self, *, healthy: Optional[bool] = None) -> None:
        write_camera_status(self._status_payload(healthy=healthy))

    def _transition(
        self,
        state: str,
        *,
        connected: Optional[bool] = None,
        error: Optional[str] = None,
        healthy: Optional[bool] = None,
    ) -> None:
        self.state = state
        if connected is not None:
            self.connected = connected
        if error is not None:
            self.last_error = error
        self._write_status(healthy=healthy)

    def _record_connected(self) -> None:
        if self.connect_count > 0:
            self.reconnect_count += 1
        self.connect_count += 1
        self.connected = True
        self.state = "streaming"
        self.consecutive_failures = 0
        self.last_error = None
        self.last_connect_at = now_iso()
        self._write_status(healthy=True)

    def _record_disconnect(self, error: str) -> None:
        self.connected = False
        self.state = "reconnecting"
        self.consecutive_failures += 1
        self.last_error = error
        self.last_disconnect_at = now_iso()
        self._write_status(healthy=False)

    def _reconnect_delay(self) -> float:
        base = min(MAX_RECONNECT_DELAY_SECS, 0.5 * (2 ** min(self.consecutive_failures, 4)))
        return base + random.uniform(0.0, 0.25)

    def start_camera(self) -> bool:
        """Initialize camera capture."""
        self.close_camera()
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

    def close_camera(self) -> None:
        if self.camera is None:
            return
        try:
            if hasattr(self.camera, "stop"):
                self.camera.stop()
            else:
                self.camera.release()
        except Exception:
            pass
        finally:
            self.camera = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Get a frame from the camera."""
        if self.camera is None:
            return None
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

    async def _stream_frames(self) -> None:
        frame_interval = 1.0 / self.target_fps
        last_send_time = time.monotonic()

        self._transition("connecting", connected=False)
        async with websockets.connect(
            self.ws_uri,
            ping_interval=PING_INTERVAL_SECS,
            ping_timeout=PING_TIMEOUT_SECS,
            close_timeout=5,
            max_queue=1,
        ) as websocket:
            logger.info(f"✅ Connected to GPU A/V server at {self.ws_uri}")
            logger.info(
                f"📹 Sending {FRAME_WIDTH}×{FRAME_HEIGHT} grayscale frames at {self.target_fps} FPS"
            )
            self.capture_failures = 0
            self._record_connected()

            while self.running:
                frame = self.get_frame()
                if frame is None:
                    self.capture_failures += 1
                    if self.capture_failures >= MAX_CAMERA_FRAME_FAILURES:
                        raise RuntimeError("camera_frame_unavailable")
                    await asyncio.sleep(min(frame_interval, 0.2))
                    continue

                self.capture_failures = 0
                frame_bytes = self.preprocess_frame(frame)
                await websocket.send(frame_bytes)

                self.frame_count += 1
                self.last_success_at = now_iso()
                self._write_status(healthy=True)
                if self.frame_count % 30 == 0:
                    logger.info(
                        f"📹 Sent {self.frame_count} frames to GPU server ({len(frame_bytes)} bytes/frame)"
                    )

                elapsed = time.monotonic() - last_send_time
                sleep_time = max(0.0, frame_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                last_send_time = time.monotonic()

    async def run(self):
        """Main supervisor loop - keep camera capture and GPU websocket alive."""

        self.running = True
        self._transition("starting", connected=False)

        try:
            while self.running:
                if self.camera is None and not self.start_camera():
                    self.consecutive_failures += 1
                    self._transition(
                        "capture_error",
                        connected=False,
                        error="camera_start_failed",
                        healthy=False,
                    )
                    await asyncio.sleep(self._reconnect_delay())
                    continue

                try:
                    await self._stream_frames()
                except RuntimeError as exc:
                    logger.warning("⚠️  Camera capture error: %s", exc)
                    self.consecutive_failures += 1
                    self._transition(
                        "capture_error",
                        connected=False,
                        error=str(exc),
                        healthy=False,
                    )
                    self.close_camera()
                except Exception as exc:
                    logger.warning("⚠️  GPU camera session ended: %s", exc)
                    self._record_disconnect(str(exc))

                if self.running:
                    await asyncio.sleep(self._reconnect_delay())
        finally:
            self.close_camera()
            self.connected = False
            self.state = "stopped"
            self.last_disconnect_at = now_iso()
            self._write_status(healthy=False)
            logger.info(f"🛑 GPU camera client stopped (sent {self.frame_count} frames)")

    def stop(self):
        """Stop the client."""
        self.running = False


async def main_async(args) -> None:
    client = GpuCameraClient(
        camera_index=args.camera,
        ws_uri=args.ws_uri,
        fps=args.fps
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, client.stop)
        except NotImplementedError:
            pass

    await client.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU-First Camera Client for Minime")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--ws-uri", default="ws://127.0.0.1:7880",
                        help="GPU A/V WebSocket server URI")
    parser.add_argument("--fps", type=float, default=1.0,
                        help="Target frame rate (frames per second)")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutdown requested")
