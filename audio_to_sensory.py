#!/usr/bin/env python3
"""
Audio to Sensory Engine Bridge

Captures microphone audio, extracts features, and sends them to the Rust sensory engine
as AudioFeat messages via WebSocket.
"""

import asyncio
import json
import logging
import time
import numpy as np
import websockets
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Feature extraction settings
AUDIO_FEAT_DIM = 8  # Must match Rust DEFAULT_AUDIO_DIM
SAMPLE_RATE = 16000  # 16kHz audio
CHUNK_SIZE = 1600  # Samples per chunk (~100ms at 16kHz, 10 FPS)

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    logger.warning("sounddevice not available - install with: pip install sounddevice")
    SOUNDDEVICE_AVAILABLE = False


class AudioToSensoryBridge:
    def __init__(self, ws_uri: str = "ws://127.0.0.1:7879", device_id: Optional[int] = None):
        self.ws_uri = ws_uri
        self.device_id = device_id
        self.running = False
        self.audio_queue = asyncio.Queue()
        self.stream = None

    def audio_callback(self, indata, frames, time_info, status):
        """Callback for audio stream - called from audio thread."""
        if status:
            logger.warning(f"Audio status: {status}")

        # Put audio chunk in queue for async processing
        # Convert to mono if stereo
        if indata.shape[1] > 1:
            audio_mono = np.mean(indata, axis=1)
        else:
            audio_mono = indata[:, 0]

        # Non-blocking put
        try:
            self.audio_queue.put_nowait(audio_mono.copy())
        except asyncio.QueueFull:
            pass  # Drop frame if queue full

    def extract_features(self, audio_chunk: np.ndarray) -> np.ndarray:
        """
        Extract simple features from audio chunk.
        Returns AUDIO_FEAT_DIM dimensional feature vector.

        Features:
        - [0]: RMS (overall loudness)
        - [1-7]: Energy in 7 frequency bands
        """
        features = []

        # 1. RMS (root mean square - overall loudness)
        rms = np.sqrt(np.mean(audio_chunk**2))
        features.append(float(rms))

        # 2-8. Frequency band energies using FFT
        # Use real FFT since input is real-valued
        fft = np.fft.rfft(audio_chunk)
        fft_mag = np.abs(fft)

        # Divide frequency spectrum into 7 bands
        bands = np.array_split(fft_mag, 7)
        for band in bands:
            # Energy = mean magnitude in band
            energy = float(np.mean(band))
            features.append(energy)

        # Ensure we have exactly AUDIO_FEAT_DIM features
        features = features[:AUDIO_FEAT_DIM]
        while len(features) < AUDIO_FEAT_DIM:
            features.append(0.0)

        return np.array(features, dtype=np.float32)

    async def process_audio_stream(self, websocket):
        """Process audio chunks from queue and send to sensory engine."""
        chunk_count = 0

        while self.running:
            try:
                # Get audio chunk with timeout
                audio_chunk = await asyncio.wait_for(
                    self.audio_queue.get(),
                    timeout=1.0
                )

                # Extract features
                features = self.extract_features(audio_chunk)

                # Create AudioFeat message
                audio_feat = {
                    "type": "AudioFeat",
                    "v": features.tolist(),
                    "ts": time.time()
                }

                # Send to sensory engine
                await websocket.send(json.dumps(audio_feat))

                chunk_count += 1
                if chunk_count % 30 == 0:
                    logger.info(f"🎤 Sent {chunk_count} audio features, RMS: {features[0]:.4f}")

            except asyncio.TimeoutError:
                # No audio received - continue waiting
                continue
            except Exception as e:
                logger.error(f"Error processing audio: {e}")
                break

    async def run(self):
        """Main loop - capture audio and send features to sensory engine."""
        if not SOUNDDEVICE_AVAILABLE:
            logger.error("❌ sounddevice not available - cannot capture audio")
            logger.error("   Install with: pip install sounddevice")
            return

        # List available devices
        try:
            devices = sd.query_devices()
            logger.info("Available audio devices:")
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    logger.info(f"  [{i}] {dev['name']} (inputs: {dev['max_input_channels']})")

            # Use default input device if not specified
            if self.device_id is None:
                self.device_id = sd.default.device[0]
                logger.info(f"Using default input device: {self.device_id}")

        except Exception as e:
            logger.error(f"❌ Error querying audio devices: {e}")
            return

        self.running = True

        try:
            # Start audio stream
            self.stream = sd.InputStream(
                device=self.device_id,
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=CHUNK_SIZE,
                callback=self.audio_callback,
                dtype='float32'
            )
            self.stream.start()
            logger.info(f"✅ Audio stream started (device: {self.device_id}, rate: {SAMPLE_RATE}Hz)")

            # Connect to sensory engine
            async with websockets.connect(self.ws_uri) as websocket:
                logger.info(f"✅ Connected to sensory engine at {self.ws_uri}")

                # Process audio stream
                await self.process_audio_stream(websocket)

        except Exception as e:
            logger.error(f"❌ Error: {e}")
        finally:
            if self.stream:
                self.stream.stop()
                self.stream.close()
            logger.info("🛑 Audio bridge stopped")

    def stop(self):
        """Stop the bridge."""
        self.running = False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Audio to Sensory Engine Bridge")
    parser.add_argument(
        "--ws-uri",
        type=str,
        default="ws://127.0.0.1:7879",
        help="WebSocket URI for sensory engine (default: ws://127.0.0.1:7879)"
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device ID (default: system default)"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit"
    )

    args = parser.parse_args()

    # List devices and exit
    if args.list_devices:
        if SOUNDDEVICE_AVAILABLE:
            devices = sd.query_devices()
            print("\nAvailable audio input devices:")
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    default = " (DEFAULT)" if i == sd.default.device[0] else ""
                    print(f"  [{i}] {dev['name']}{default}")
                    print(f"      Channels: {dev['max_input_channels']}, Rate: {dev['default_samplerate']}Hz")
        else:
            print("sounddevice not available - install with: pip install sounddevice")
        exit(0)

    # Run bridge
    bridge = AudioToSensoryBridge(
        ws_uri=args.ws_uri,
        device_id=args.device
    )

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down...")
        bridge.stop()
