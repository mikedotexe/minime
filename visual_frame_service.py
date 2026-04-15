#!/usr/bin/env python3
"""
Visual Frame Service - Lightweight camera + LLaVA bridge.

Watches workspace/visual_requests/ for JSON requests, captures a frame via
OpenCV, optionally analyzes it with LLaVA (Ollama), writes response JSON to
workspace/visual_responses/, and sends a semantic embedding to the Rust
sensory engine via ws://7879.

No dependency on the full Python consciousness stack.
"""

import argparse
import base64
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

WORKSPACE_DIR = Path(__file__).parent / "workspace"
REQUESTS_DIR = WORKSPACE_DIR / "visual_requests"
RESPONSES_DIR = WORKSPACE_DIR / "visual_responses"
CAPTURES_DIR = WORKSPACE_DIR / "visual_captures"
RUNTIME_DIR = WORKSPACE_DIR / "runtime"
HOST_FRAME_PATH = RUNTIME_DIR / "host_frame.jpg"
HOST_TELEMETRY_PATH = RUNTIME_DIR / "host_telemetry.json"
SENSORY_SOURCE_PATH = RUNTIME_DIR / "sensory_source.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
LLAVA_MODEL = "llava-llama3"
WS_URI = "ws://127.0.0.1:7879"
SOURCE_STATE_MAX_AGE_MS = 10_000
HOST_FRAME_MAX_AGE_S = 15.0


class VisualFrameService:
    def __init__(self, camera_index: int = 0, poll_interval: float = 5.0, source: str = "active"):
        self.camera_index = camera_index
        self.poll_interval = poll_interval
        self.source = source
        self.running = False

        for d in [REQUESTS_DIR, RESPONSES_DIR, CAPTURES_DIR,
                  REQUESTS_DIR / "processed", RESPONSES_DIR / "processed"]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_fresh_source_state(self) -> Dict[str, Any]:
        try:
            data = json.loads(SENSORY_SOURCE_PATH.read_text())
        except Exception:
            return {}

        updated_at_ms = int(data.get("updated_at_ms", 0) or 0)
        if updated_at_ms <= 0:
            return {}

        age_ms = int(time.time() * 1000) - updated_at_ms
        if age_ms > SOURCE_STATE_MAX_AGE_MS:
            return {}

        return data

    def _host_source_available(self) -> bool:
        try:
            telemetry = json.loads(HOST_TELEMETRY_PATH.read_text())
        except Exception:
            return False

        updated_at_ms = int(telemetry.get("updated_at_ms", 0) or 0)
        if updated_at_ms <= 0:
            return False

        age_ms = int(time.time() * 1000) - updated_at_ms
        if age_ms > SOURCE_STATE_MAX_AGE_MS:
            return False

        try:
            frame_age_s = time.time() - HOST_FRAME_PATH.stat().st_mtime
        except OSError:
            return False

        return frame_age_s <= HOST_FRAME_MAX_AGE_S

    def _active_source(self) -> str:
        if self.source == "physical":
            return "physical"
        if self.source == "host":
            return "host" if self._host_source_available() else "physical"

        data = self._load_fresh_source_state()
        source = str(data.get("video", {}).get("source", "physical")).strip().lower()
        if source == "host" and self._host_source_available():
            return "host"
        return "physical"

    def capture_frame(self) -> tuple[Optional[np.ndarray], str]:
        source = self._active_source()
        if source == "host":
            frame = cv2.imread(str(HOST_FRAME_PATH), cv2.IMREAD_GRAYSCALE)
            if frame is None:
                logging.error("Host-state frame not accessible")
                return None, source
            return frame, source

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            logging.error("Camera not accessible")
            return None, source
        ret, frame = cap.read()
        cap.release()
        return (frame if ret else None), source

    def analyze_with_llava(self, frame: np.ndarray, prompt: str) -> Optional[str]:
        import requests

        _, buf = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buf).decode()

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": LLAVA_MODEL,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                },
                timeout=90,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            logging.error(f"LLaVA returned {resp.status_code}")
        except Exception as e:
            logging.error(f"LLaVA error: {e}")
        return None

    def send_semantic(self, description: str):
        """Send a simple semantic embedding to the Rust engine."""
        try:
            import websocket

            words = description.split()
            n_words = len(words)
            n_chars = len(description)
            avg_word_len = n_chars / max(1, n_words)
            h = hash(description) & 0xFFFFFFFF

            features = [
                min(1.0, n_words / 80.0),
                min(1.0, avg_word_len / 10.0),
                1.0 if "?" in description else 0.0,
                1.0 if any(w in description.lower() for w in ("person", "people", "face")) else 0.0,
                1.0 if any(w in description.lower() for w in ("light", "bright", "sun")) else 0.0,
                1.0 if any(w in description.lower() for w in ("dark", "shadow", "dim")) else 0.0,
                ((h >> 0) & 0xFF) / 255.0,
                ((h >> 8) & 0xFF) / 255.0,
            ]

            ws = websocket.create_connection(WS_URI, timeout=5)
            msg = json.dumps({"kind": "semantic", "features": features})
            ws.send(msg)
            ws.close()
            logging.info("Sent semantic embedding to engine")
        except Exception as e:
            logging.warning(f"Semantic send failed: {e}")

    def process_request(self, request_file: Path):
        try:
            request_data = json.loads(request_file.read_text())
        except Exception as e:
            logging.error(f"Bad request {request_file}: {e}")
            return

        prompt = request_data.get("prompt", "Describe what you see concisely.")
        analyze = request_data.get("analyze", True)
        request_id = request_data.get("request_id", request_file.stem)

        logging.info(f"Processing visual request: {request_id}")

        frame, capture_source = self.capture_frame()
        if frame is None:
            response = {
                "visual_available": False,
                "description": "Host-state frame not accessible" if capture_source == "host" else "Camera not accessible",
                "error": "capture_failed",
                "source": capture_source,
            }
        else:
            timestamp = datetime.now().isoformat().replace(":", "-")
            image_filename = f"capture_{timestamp}.jpg"
            image_path = CAPTURES_DIR / image_filename
            cv2.imwrite(str(image_path), frame)

            _, buf = cv2.imencode(".jpg", frame)
            image_b64 = base64.b64encode(buf).decode()

            description = None
            if analyze:
                description = self.analyze_with_llava(frame, prompt)

            if description:
                self.send_semantic(description)

            response = {
                "visual_available": True,
                "description": description or "(LLaVA unavailable)",
                "analysis_type": "llava" if description else "none",
                "image_path": str(image_path),
                "image_filename": image_filename,
                "image_base64": image_b64,
                "source": capture_source,
            }

        response["request_id"] = request_id
        response["request_timestamp"] = request_data.get("timestamp", "")
        response["response_timestamp"] = datetime.now().isoformat()

        resp_file = RESPONSES_DIR / f"response_{request_id}.json"
        resp_file.write_text(json.dumps(response, indent=2))
        logging.info(f"Response written: {resp_file.name}")

        # Move request to processed
        try:
            request_file.rename(REQUESTS_DIR / "processed" / request_file.name)
        except Exception:
            request_file.unlink(missing_ok=True)

    def process_pending(self):
        for f in sorted(REQUESTS_DIR.glob("*.json")):
            self.process_request(f)

    def start(self):
        self.running = True
        logging.info(f"Visual Frame Service started (camera {self.camera_index}, poll {self.poll_interval}s)")

        while self.running:
            try:
                self.process_pending()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Service error: {e}")
                time.sleep(10)
        self.running = False
        logging.info("Visual Frame Service stopped")


def main():
    parser = argparse.ArgumentParser(description="Visual Frame Service")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--source", choices=("active", "physical", "host"), default="active")
    args = parser.parse_args()

    service = VisualFrameService(
        camera_index=args.camera,
        poll_interval=args.interval,
        source=args.source,
    )
    service.start()


if __name__ == "__main__":
    main()
