"""LLaVA Vision Engine -- handles visual frame analysis via Ollama."""

import base64
import json
import logging
import os
import time
from typing import List, Optional

import requests

from mikemind.config import ModelConfig

# Conditional import -- cv2 may not be installed
try:
    import cv2
except ImportError:
    cv2 = None


class LLaVAVisionEngine:
    """Handles vision-language model for actual image understanding."""

    def __init__(self, model: str = None):
        self.model = model or ModelConfig.LLAVA_VISION
        self.api_url = ModelConfig.OLLAMA_API_GENERATE
        self.available = self._check_availability()
        self.sse_url = self._normalize_sse_url(os.getenv("LLAVA_SSE_URL"))

        self._last_frame_hash = None
        self._last_frame_b64 = None
        self._cache_hits = 0

        try:
            self._tb_rate = max(0, int(os.getenv("VISION_RATE_PER_MIN", "6")))
            self._tb_burst = max(1, int(os.getenv("VISION_BURST", "3")))
        except Exception:
            self._tb_rate, self._tb_burst = 3, 1
        self._tb_tokens = float(self._tb_burst)
        self._tb_last = time.monotonic()

        if self.available:
            logging.info(f"LLaVA Vision Engine initialized with {self.model}")
        else:
            logging.warning(f"LLaVA Vision Engine unavailable (model: {self.model})")

        if self.sse_url:
            logging.info(f"LLaVA SSE worker detected at {self.sse_url}/describe")

    def _check_availability(self) -> bool:
        try:
            response = requests.post(
                self.api_url,
                json={"model": self.model, "prompt": "test", "stream": False, "keep_alive": "1h"},
                timeout=30,
            )
            return response.status_code == 200
        except Exception as e:
            logging.error(f"LLaVA availability check failed: {e}")
            return False

    def analyze_frame(
        self, frame, prompt: str = "Describe what you see in this image in detail."
    ) -> Optional[str]:
        """Analyze a camera frame using LLaVA vision model."""
        if not self.available or cv2 is None:
            return None

        try:
            if not self._allow_call(prompt):
                logging.warning(
                    f"Vision throttled (tokens={self._tb_tokens:.2f}, calm={self._is_calm()})"
                )
                return None

            frame_hash = hash(frame.tobytes())

            if frame_hash == self._last_frame_hash and self._last_frame_b64 is not None:
                self._cache_hits += 1
                image_base64 = self._last_frame_b64
            else:
                _, buffer = cv2.imencode(".jpg", frame)
                image_base64 = base64.b64encode(buffer).decode("utf-8")
                self._last_frame_hash = frame_hash
                self._last_frame_b64 = image_base64

            if self.sse_url:
                streamed = self._analyze_frame_via_sse(image_base64, prompt)
                if streamed:
                    return streamed
                logging.warning(
                    "LLaVA SSE stream failed; falling back to direct call"
                )

            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False,
                    "keep_alive": "1h",
                    "options": {"temperature": 0.7, "num_predict": 512},
                },
                timeout=20,
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                logging.error(f"LLaVA request failed: {response.status_code}")
                return None

        except Exception as e:
            logging.error(f"LLaVA frame analysis failed: {e}")
            return None

    def _normalize_sse_url(self, raw_url: Optional[str]) -> Optional[str]:
        if not raw_url:
            return None
        trimmed = raw_url.strip()
        if not trimmed:
            return None
        return trimmed[:-1] if trimmed.endswith("/") else trimmed

    def _is_high_salience(self, prompt: str) -> bool:
        p = (prompt or "").lower()
        keys = ("look", "see", "camera", "show me", "what do you see")
        return any(k in p for k in keys)

    def _refill_tokens(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._tb_last)
        if self._tb_rate > 0:
            self._tb_tokens = min(
                self._tb_burst,
                self._tb_tokens + (self._tb_rate / 60.0) * elapsed,
            )
        self._tb_last = now

    def _is_calm(self) -> bool:
        try:
            with open("workspace/health.json", "r") as f:
                data = json.load(f)
            return bool(data.get("calm", False))
        except Exception:
            return False

    def _allow_call(self, prompt: str) -> bool:
        self._refill_tokens()
        if self._is_calm() and self._is_high_salience(prompt):
            logging.info("High-salience vision request bypassing rate limit (CALM mode)")
            return True
        if self._tb_tokens >= 1.0:
            self._tb_tokens -= 1.0
            return True
        return False

    def _analyze_frame_via_sse(self, image_base64: str, prompt: str) -> Optional[str]:
        target_url = f"{self.sse_url}/describe"
        try:
            response = requests.post(
                target_url,
                json={"imageBase64": image_base64, "prompt": prompt},
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=20,
            )

            if response.status_code != 200:
                logging.error(f"LLaVA SSE worker responded with {response.status_code}")
                return None

            tokens: List[str] = []
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[len("data:") :].strip()
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if payload.get("error"):
                    logging.error(f"LLaVA SSE worker error: {payload['error']}")
                    return None
                if payload.get("done"):
                    break

                token = payload.get("token") or payload.get("response")
                if token:
                    tokens.append(token)

            response.close()
            combined = "".join(tokens).strip()
            return combined or None
        except Exception as e:
            logging.error(f"LLaVA SSE streaming failed: {e}")
            return None
