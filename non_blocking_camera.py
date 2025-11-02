#!/usr/bin/env python3
"""
Non-blocking Camera - Atomic frame swap pattern for vision without blocking.

Prevents conversation stutters during camera access by capturing frames in
a background thread and providing instant access to the latest frame.

Usage:
    camera = NonBlockingCamera(camera_index=0, fps=10)
    camera.start()

    # Get latest frame instantly (never blocks)
    frame = camera.get_frame()
    if frame is not None:
        # Process frame...
        pass

    camera.stop()
"""

import cv2
import threading
import time
import logging
from typing import Optional
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NonBlockingCamera:
    """
    Non-blocking camera with atomic frame swap.

    Captures frames in a background thread at specified FPS.
    Main thread can retrieve latest frame instantly without blocking.

    This prevents vision queries from blocking conversation during frame capture.
    """

    def __init__(self, camera_index: int = 0, fps: int = 10, max_frame_age_ms: int = 2500):
        """
        Initialize non-blocking camera.

        Args:
            camera_index: OpenCV camera device index (usually 0 for default camera)
            fps: Target frames per second for capture loop
            max_frame_age_ms: Maximum frame age in milliseconds before considered stale
        """
        self.camera_index = camera_index
        self.fps = fps
        self.max_frame_age_ms = max_frame_age_ms

        # Thread-safe frame storage
        self.last_frame: Optional[np.ndarray] = None
        self.last_frame_time: float = 0
        self.frame_lock = threading.Lock()

        # Capture thread control
        self.running = False
        self.capture_thread: Optional[threading.Thread] = None
        self.cap: Optional[cv2.VideoCapture] = None

        # Statistics
        self.stats = {
            'frames_captured': 0,
            'frames_retrieved': 0,
            'stale_frames': 0,
            'errors': 0
        }

    def start(self) -> bool:
        """
        Start background frame capture.

        Returns:
            True if camera started successfully, False otherwise
        """
        if self.running:
            logger.warning("Camera already running")
            return True

        try:
            # Open camera
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera {self.camera_index}")
                return False

            # Configure camera
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffering

            # Start capture thread
            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()

            logger.info(f"Non-blocking camera started (camera {self.camera_index}, {self.fps} FPS)")
            return True

        except Exception as e:
            logger.error(f"Failed to start camera: {e}")
            self.stats['errors'] += 1
            return False

    def _capture_loop(self):
        """
        Background thread loop for frame capture.

        Captures frames at specified FPS and atomically swaps them into shared storage.
        """
        frame_interval = 1.0 / self.fps
        last_capture_time = 0

        while self.running:
            try:
                current_time = time.time()

                # Rate limiting
                if current_time - last_capture_time < frame_interval:
                    time.sleep(0.01)  # Small sleep to avoid busy waiting
                    continue

                last_capture_time = current_time

                # Capture frame
                ret, frame = self.cap.read()

                if ret and frame is not None:
                    # Atomic swap with lock
                    with self.frame_lock:
                        self.last_frame = frame.copy()  # Deep copy to avoid race conditions
                        self.last_frame_time = current_time * 1000  # Convert to ms

                    self.stats['frames_captured'] += 1

                else:
                    # Frame capture failed
                    self.stats['errors'] += 1
                    logger.debug(f"Frame capture failed (total errors: {self.stats['errors']})")

            except Exception as e:
                logger.error(f"Capture loop error: {e}")
                self.stats['errors'] += 1
                time.sleep(0.1)  # Back off on errors

        # Cleanup when loop exits
        if self.cap:
            self.cap.release()
            logger.info("Camera released")

    def get_frame(self, allow_stale: bool = True) -> Optional[np.ndarray]:
        """
        Get latest captured frame (never blocks).

        Args:
            allow_stale: If True, return frame even if older than max_frame_age_ms.
                        If False, return None for stale frames.

        Returns:
            Latest frame as numpy array, or None if no frame available or frame is stale
        """
        with self.frame_lock:
            if self.last_frame is None:
                return None

            # Check frame freshness
            current_time = time.time() * 1000  # ms
            age_ms = current_time - self.last_frame_time

            if not allow_stale and age_ms > self.max_frame_age_ms:
                self.stats['stale_frames'] += 1
                logger.debug(f"Frame too old: {age_ms:.0f}ms (max: {self.max_frame_age_ms}ms)")
                return None

            self.stats['frames_retrieved'] += 1
            return self.last_frame.copy()  # Return deep copy for thread safety

    def get_frame_with_age(self) -> tuple[Optional[np.ndarray], float]:
        """
        Get latest frame along with its age in milliseconds.

        Returns:
            Tuple of (frame, age_ms) or (None, 0) if no frame available
        """
        with self.frame_lock:
            if self.last_frame is None:
                return None, 0

            current_time = time.time() * 1000
            age_ms = current_time - self.last_frame_time

            self.stats['frames_retrieved'] += 1
            return self.last_frame.copy(), age_ms

    def stop(self):
        """Stop background frame capture and release camera."""
        if not self.running:
            return

        logger.info("Stopping camera...")
        self.running = False

        # Wait for capture thread to exit
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)

        # Clear frame storage
        with self.frame_lock:
            self.last_frame = None
            self.last_frame_time = 0

        logger.info(f"Camera stopped. Stats: {self.stats}")

    def get_stats(self) -> dict:
        """Get camera statistics."""
        with self.frame_lock:
            age_ms = (time.time() * 1000 - self.last_frame_time) if self.last_frame_time > 0 else 0

        return {
            **self.stats,
            'running': self.running,
            'has_frame': self.last_frame is not None,
            'frame_age_ms': age_ms
        }

    def __del__(self):
        """Cleanup on deletion."""
        self.stop()


# Example usage / test
if __name__ == "__main__":
    print("Testing NonBlockingCamera...")

    camera = NonBlockingCamera(camera_index=0, fps=10)

    if not camera.start():
        print("❌ Failed to start camera")
        exit(1)

    print("✅ Camera started, capturing frames for 5 seconds...")
    time.sleep(5)

    # Retrieve some frames
    for i in range(10):
        frame, age = camera.get_frame_with_age()
        if frame is not None:
            print(f"Frame {i}: {frame.shape}, age: {age:.1f}ms")
        else:
            print(f"Frame {i}: No frame available")
        time.sleep(0.5)

    # Show stats
    print(f"\nStats: {camera.get_stats()}")

    camera.stop()
    print("✅ Test complete")
