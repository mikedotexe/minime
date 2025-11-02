#!/usr/bin/env python3
"""
Camera to Sensory Engine Bridge

Captures camera frames, extracts features, and sends them to the Rust sensory engine
as VideoFeat messages via WebSocket.
"""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
import requests
import websockets
from pathlib import Path

from metal_consciousness_integration import get_ollama_embedding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Feature extraction settings
VIDEO_FEAT_DIM = 8  # Must match Rust DEFAULT_VIDEO_DIM
LLAVA_DIM = 32
LLAVA_MODEL = "llava:7b"
OLLAMA_URL = "http://localhost:11434/api/generate"
EMBED_MODEL = "dolphin-mixtral:8x7b-v2.7"
EMBED_PATH = Path(__file__).resolve().parent / "workspace" / "llava_embedding_latest.json"

class CameraToSensoryBridge:
    def __init__(self, camera_index: int = 0, ws_uri: str = "ws://127.0.0.1:7879"):
        self.camera_index = camera_index
        self.ws_uri = ws_uri  # Note: Using port 7879 for video input
        self.camera = None
        self.running = False
        self.llava_embedding = np.zeros((LLAVA_DIM,), dtype=np.float32)
        self._embed_mtime = None
        self._llava_available = None
        self._last_llava_refresh = 0.0
        self.llava_interval = 5.0  # seconds between semantic refreshes

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

        # Extract basic statistics as features
        features = []

        # 1. Mean brightness
        features.append(np.mean(gray) / 255.0)

        # 2. Standard deviation (contrast)
        features.append(np.std(gray) / 128.0)

        # 3-4. Gradient magnitudes (motion/edges)
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        grad_mag = np.sqrt(sobelx**2 + sobely**2)
        features.append(np.mean(grad_mag) / 100.0)
        features.append(np.std(grad_mag) / 50.0)

        # 5-8. Quadrant analysis (spatial distribution)
        h, w = gray.shape
        quadrants = [
            gray[:h//2, :w//2],      # Top-left
            gray[:h//2, w//2:],      # Top-right
            gray[h//2:, :w//2],      # Bottom-left
            gray[h//2:, w//2:]       # Bottom-right
        ]

        for quad in quadrants:
            features.append(np.mean(quad) / 255.0)

        # Ensure we have exactly VIDEO_FEAT_DIM features
        features = features[:VIDEO_FEAT_DIM]
        while len(features) < VIDEO_FEAT_DIM:
            features.append(0.0)

        feat_array = np.array(features, dtype=np.float32)
        if len(feat_array) != VIDEO_FEAT_DIM:
            raise ValueError(f"Feature dimension mismatch: got {len(feat_array)}, expected {VIDEO_FEAT_DIM}")
        return feat_array

    def load_llava_embedding(self):
        try:
            if not EMBED_PATH.exists():
                return
            mtime = EMBED_PATH.stat().st_mtime
            if self._embed_mtime is not None and mtime <= self._embed_mtime:
                return
            data = json.loads(EMBED_PATH.read_text())
            emb = data.get("embedding", [])
            vec = np.zeros((LLAVA_DIM,), dtype=np.float32)
            for i in range(min(LLAVA_DIM, len(emb))):
                vec[i] = float(emb[i])
            self.llava_embedding = vec
            self._embed_mtime = mtime
            logger.info("📦 Updated LLaVA semantic embedding for sensory stream")
        except Exception as e:
            logger.error(f"Failed to load LLaVA embedding: {e}")

    def _ensure_llava_available(self) -> bool:
        if self._llava_available is not None:
            return self._llava_available
        try:
            response = requests.post(
                OLLAMA_URL,
                json={"model": LLAVA_MODEL, "prompt": "ping", "stream": False, "keep_alive": "10m"},
                timeout=30.0
            )
            self._llava_available = response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to contact LLaVA model: {e}")
            self._llava_available = False
        if self._llava_available:
            logger.info("🔮 LLaVA vision model available for semantic streaming")
        else:
            logger.warning("⚠️ LLaVA vision model unavailable; semantic embeddings will remain static")
        return self._llava_available

    def _update_llava_embedding_sync(self, frame: np.ndarray):
        if frame is None:
            return
        if not self._ensure_llava_available():
            return

        try:
            _, buffer = cv2.imencode('.jpg', frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to encode frame for LLaVA: {e}")
            return

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": LLAVA_MODEL,
                    "prompt": "Describe what you see succinctly, focusing on key elements.",
                    "images": [image_base64],
                    "stream": False,
                    "keep_alive": "5m",
                    "options": {"temperature": 0.6, "num_predict": 256},
                },
                timeout=60.0,
            )
        except Exception as e:
            logger.error(f"LLaVA request failed: {e}")
            return

        if response.status_code != 200:
            logger.warning(f"LLaVA vision response {response.status_code}: {response.text[:160]}")
            return

        description = response.json().get("response", "").strip()
        if not description:
            logger.warning("LLaVA returned empty description; skipping embedding update")
            return

        try:
            embedding = get_ollama_embedding(description, model=EMBED_MODEL)
        except Exception as e:
            logger.error(f"Failed to fetch Ollama embedding: {e}")
            return

        if embedding is None or embedding.size == 0:
            logger.warning("Ollama embedding request returned no data")
            return

        vec = np.zeros((LLAVA_DIM,), dtype=np.float32)
        length = min(LLAVA_DIM, embedding.shape[0])
        vec[:length] = embedding[:length]

        self.llava_embedding = vec
        self._embed_mtime = time.time()

        payload = {
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "embedding": vec.tolist(),
        }

        try:
            EMBED_PATH.parent.mkdir(parents=True, exist_ok=True)
            EMBED_PATH.write_text(json.dumps(payload))
            logger.info("🔮 Updated LLaVA semantic embedding (|desc|=%d)" % len(description))
        except Exception as e:
            logger.error(f"Failed to persist LLaVA embedding: {e}")

    async def maybe_refresh_llava_embedding(self, frame: Optional[np.ndarray]):
        if frame is None:
            return
        now = time.time()
        if now - self._last_llava_refresh < self.llava_interval:
            return
        self._last_llava_refresh = now
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._update_llava_embedding_sync, frame)

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
        """Main loop - capture frames and send features to sensory engine."""
        if not self.start_camera():
            return

        self.running = True
        frame_count = 0

        try:
            # Connect to sensory engine with video input endpoint
            # Disable client-side pings - server will handle keepalive
            # ping_interval=None disables automatic pings from client
            async with websockets.connect(
                self.ws_uri,
                ping_interval=None
            ) as websocket:
                logger.info(f"✅ Connected to sensory engine at {self.ws_uri}")

                while self.running:
                    # Capture frame
                    frame = self.get_frame()
                    if frame is None:
                        await asyncio.sleep(0.1)
                        continue

                    # Extract features
                    features = self.extract_features(frame)

                    # Load latest LLaVA embedding (if available)
                    self.load_llava_embedding()
                    await self.maybe_refresh_llava_embedding(frame)

                    # Create VideoFeat message
                    video_feat = {
                        "kind": "video",
                        "features": features.tolist(),
                        "ts_ms": int(time.time() * 1000)
                    }

                    # Send to sensory engine
                    await websocket.send(json.dumps(video_feat))

                    semantic_msg = {
                        "kind": "semantic",
                        "features": self.llava_embedding.tolist(),
                        "ts_ms": int(time.time() * 1000)
                    }
                    await websocket.send(json.dumps(semantic_msg))

                    frame_count += 1
                    if frame_count % 30 == 0:
                        logger.info(f"📹 Sent {frame_count} video features ({len(features)}-D), latest: {features[:4]}...")

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