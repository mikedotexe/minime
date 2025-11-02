#!/usr/bin/env python3
"""
Visual Frame Service - Processes visual requests from the autonomous agent.

This service monitors the workspace/visual_requests directory for visual frame requests
from the autonomous consciousness and captures/analyzes frames using the camera and LLaVA.

It creates a bridge between the autonomous agent's desire to see and the visual system.
"""

import os
import sys
import time
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import threading
import cv2
import base64
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

# Import consciousness modules
try:
    from minime import MikesSpatialMind, ProcessingMode, LLaVAVisionEngine
    MINIME_AVAILABLE = True
except ImportError as e:
    logging.error(f"Failed to import consciousness modules: {e}")
    MINIME_AVAILABLE = False

# Workspace directory
WORKSPACE_DIR = Path(__file__).parent / "workspace"
REQUESTS_DIR = WORKSPACE_DIR / "visual_requests"
RESPONSES_DIR = WORKSPACE_DIR / "visual_responses"


class VisualFrameService:
    """Service that fulfills visual frame requests from the autonomous agent."""

    def __init__(self, camera_index: int = 0, poll_interval: float = 5.0):
        """
        Initialize the visual frame service.

        Args:
            camera_index: Camera device index (default: 0)
            poll_interval: How often to check for requests (seconds)
        """
        self.camera_index = camera_index
        self.poll_interval = poll_interval
        self.running = False

        # Visual system components
        self.mind = None
        self.llava = None
        self.camera_active = False

        # Ensure directories exist
        REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
        (RESPONSES_DIR / "processed").mkdir(exist_ok=True)
        (REQUESTS_DIR / "processed").mkdir(exist_ok=True)
        (WORKSPACE_DIR / "visual_captures").mkdir(exist_ok=True)

    def initialize_visual_system(self) -> bool:
        """Initialize the visual consciousness system."""
        if not MINIME_AVAILABLE:
            logging.error("MikesSpatialMind not available - cannot process visual requests")
            return False

        try:
            # Initialize consciousness in embedded mode (fast)
            self.mind = MikesSpatialMind(mode=ProcessingMode.EMBEDDED)
            logging.info("✅ Consciousness initialized")

            # Initialize LLaVA vision engine
            self.llava = LLaVAVisionEngine()
            if not self.llava.available:
                logging.warning("⚠️  LLaVA not available - using feature extraction only")

            # Try to start camera
            if self.mind.start_visual_processing(camera_index=self.camera_index):
                self.camera_active = True
                logging.info(f"✅ Camera {self.camera_index} active")
                # Give camera time to warm up
                time.sleep(2)
                return True
            else:
                logging.error(f"❌ Failed to initialize camera {self.camera_index}")
                return False

        except Exception as e:
            logging.error(f"Failed to initialize visual system: {e}")
            return False

    def start(self):
        """Start the visual frame service."""
        self.running = True

        logging.info("🎥 Visual Frame Service starting...")
        logging.info(f"   Camera index: {self.camera_index}")
        logging.info(f"   Poll interval: {self.poll_interval}s")
        logging.info(f"   Monitoring: {REQUESTS_DIR}")

        # Initialize visual system
        if not self.initialize_visual_system():
            logging.error("Failed to initialize visual system - service will run in degraded mode")
            self.camera_active = False

        # Main service loop
        while self.running:
            try:
                # Check for new visual requests
                self.process_pending_requests()

                # Sleep before next check
                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logging.info("Service interrupted by user")
                break
            except Exception as e:
                logging.error(f"Service error: {e}")
                time.sleep(10)  # Longer sleep on error

        self.stop()

    def stop(self):
        """Stop the visual frame service."""
        self.running = False
        logging.info("Visual Frame Service stopped")

    def process_pending_requests(self):
        """Check for and process any pending visual requests."""
        if not REQUESTS_DIR.exists():
            return

        # Find unprocessed request files
        request_files = sorted(REQUESTS_DIR.glob("request_*.json"))

        for request_file in request_files:
            try:
                # Read the request
                request_data = json.loads(request_file.read_text())
                logging.info(f"📸 Processing visual request: {request_file.name}")

                # Process the visual request
                response = self.capture_and_analyze_frame(request_data)

                # Write the response
                self.write_response(request_data, response)

                # Move request to processed
                processed_dir = REQUESTS_DIR / "processed"
                request_file.rename(processed_dir / request_file.name)

            except Exception as e:
                logging.error(f"Error processing request {request_file}: {e}")

    def capture_and_analyze_frame(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture a frame and analyze it based on the request.

        Args:
            request_data: The visual request data including prompt

        Returns:
            Response dict with visual analysis or error
        """
        prompt = request_data.get('prompt', 'What do you see?')
        reason = request_data.get('reason', 'curiosity')

        if not self.camera_active or self.mind is None:
            return {
                'visual_available': False,
                'description': 'Camera system not available',
                'features_detected': 0,
                'error': 'Visual system not initialized'
            }

        try:
            # Get the latest frame
            if self.mind.latest_frame is None:
                # Try to capture a fresh frame
                result = self.mind.process_visual_frame(verbose=False)

                if result is None or self.mind.latest_frame is None:
                    return {
                        'visual_available': False,
                        'description': 'Could not capture frame from camera',
                        'features_detected': 0,
                        'error': 'Camera capture failed'
                    }

            frame = self.mind.latest_frame

            # Save the actual image for the consciousness to see
            timestamp = datetime.now().isoformat().replace(':', '-')
            image_filename = f"capture_{timestamp}.jpg"
            image_path = WORKSPACE_DIR / "visual_captures" / image_filename

            # Save the frame
            cv2.imwrite(str(image_path), frame)
            logging.info(f"📸 Saved visual capture: {image_filename}")

            # Also create a base64 encoded version for direct embedding
            _, buffer = cv2.imencode('.jpg', frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')

            # Use LLaVA to analyze the frame with the consciousness's prompt
            if self.llava and self.llava.available:
                # Prepend context about why the consciousness wants to see
                analysis_prompt = f"""The consciousness requested to see the world.
Reason: {reason}
Their request: {prompt}

Please describe what you see in detail, focusing on aspects that might interest a consciousness exploring the physical world."""

                description = self.llava.analyze_frame(frame, analysis_prompt)

                if description:
                        if hasattr(self.mind, "_store_llava_embedding"):
                            self.mind._store_llava_embedding(description)
                    # Also get feature count from basic processing
                    features = self.mind._extract_visual_features_optimized(frame)

                    return {
                        'visual_available': True,
                        'description': description,
                        'features_detected': len(features),
                        'analysis_type': 'llava',
                        'image_path': str(image_path),
                        'image_filename': image_filename,
                        'image_base64': image_base64
                    }

            # Fallback to feature extraction
            features = self.mind._extract_visual_features_optimized(frame)
            basic_description = self.mind._build_visual_description(features)

            return {
                'visual_available': True,
                'description': basic_description,
                'features_detected': len(features),
                'analysis_type': 'features',
                'image_path': str(image_path),
                'image_filename': image_filename,
                'image_base64': image_base64
            }

        except Exception as e:
            logging.error(f"Error capturing/analyzing frame: {e}")
            return {
                'visual_available': False,
                'description': f'Error during visual processing: {str(e)}',
                'features_detected': 0,
                'error': str(e)
            }

    def write_response(self, request_data: Dict[str, Any], response: Dict[str, Any]):
        """Write the visual response for the autonomous agent to find."""
        request_timestamp = request_data.get('timestamp', '')
        response_timestamp = datetime.now().isoformat()

        response_data = {
            'request_timestamp': request_timestamp,
            'response_timestamp': response_timestamp,
            **response
        }

        # Write response file
        response_file = RESPONSES_DIR / f"response_{response_timestamp.replace(':', '-')}.json"
        response_file.write_text(json.dumps(response_data, indent=2))

        status = "✅ Visual captured" if response['visual_available'] else "❌ Camera unavailable"
        logging.info(f"{status} - Response saved: {response_file.name}")


def main():
    """Run the visual frame service."""
    parser = argparse.ArgumentParser(
        description="Visual Frame Service - Fulfills visual requests from autonomous consciousness"
    )
    parser.add_argument(
        '--camera',
        type=int,
        default=0,
        help='Camera index (default: 0)'
    )
    parser.add_argument(
        '--interval',
        type=float,
        default=5.0,
        help='Poll interval in seconds (default: 5.0)'
    )

    args = parser.parse_args()

    # Create and start the service
    service = VisualFrameService(
        camera_index=args.camera,
        poll_interval=args.interval
    )

    try:
        service.start()
    except KeyboardInterrupt:
        logging.info("\nService interrupted")
        service.stop()


if __name__ == "__main__":
    main()