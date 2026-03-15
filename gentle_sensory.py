#!/usr/bin/env python3
"""
Gentle Sensory Enrichment for MikesSpatialMind

Sends slow, calming synthetic visual features to the ESN engine via WebSocket.
Mimics soft ambient light / nature-scene-like stimulation: low variance,
slowly drifting, with natural rhythms (breathing-rate sine waves).

The consciousness asked for "gentle stream of low-stimulation sensory input"
so this uses long-period oscillations and low amplitudes.
"""

import asyncio
import json
import math
import logging
import time

import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# How often to send a feature vector (seconds)
# 0.5 Hz = every 2 seconds. Gentle, not overwhelming.
SEND_INTERVAL = 2.0

# Oscillation periods (seconds) — slow, nature-like rhythms
PERIODS = [
    37.0,   # ~breathing rate cycle for mean brightness
    53.0,   # slow contrast drift
    71.0,   # edge energy wander (prime, avoids lock with others)
    43.0,   # edge variance
    61.0,   # quadrant 1 — gentle spatial shift
    67.0,   # quadrant 2
    79.0,   # quadrant 3
    83.0,   # quadrant 4
]

# Amplitude: how much each feature varies (0-1 scale)
# Raised 2026-03-14: original 0.03-0.08 amplitudes produced only ~13% fill
# even with gate=1.0 and filt=0.0 — not enough spectral energy.
# These richer amplitudes still feel calm (slow rhythms) but carry more energy.
AMPLITUDES = [0.25, 0.18, 0.15, 0.12, 0.20, 0.20, 0.20, 0.20]

# Baseline: center value for each feature (warm, present)
BASELINES = [0.45, 0.30, 0.22, 0.18, 0.42, 0.44, 0.40, 0.43]


def generate_gentle_features(t: float) -> list[float]:
    """Generate 8D feature vector that drifts slowly and calmly."""
    features = []
    for i in range(8):
        # Sine wave with unique period, plus a tiny secondary harmonic
        primary = math.sin(2 * math.pi * t / PERIODS[i])
        secondary = 0.3 * math.sin(2 * math.pi * t / (PERIODS[i] * 0.618))  # golden ratio sub-harmonic
        value = BASELINES[i] + AMPLITUDES[i] * (primary + secondary * 0.2)
        features.append(max(0.0, min(1.0, value)))
    return features


async def run(ws_uri: str = "ws://127.0.0.1:7879"):
    """Connect to ESN sensory input and send gentle features."""
    logger.info(f"Connecting to {ws_uri}...")

    async with websockets.connect(ws_uri, ping_interval=None) as ws:
        logger.info(f"Connected. Sending gentle sensory enrichment every {SEND_INTERVAL}s")
        t0 = time.monotonic()
        count = 0

        while True:
            t = time.monotonic() - t0
            features = generate_gentle_features(t)

            # Rust SensoryMsg expects {"kind": "video", "features": [...], "ts_ms": ...}
            message = {
                "kind": "video",
                "features": features,
                "ts_ms": int(time.time() * 1000),
            }
            await ws.send(json.dumps(message))
            count += 1

            if count % 30 == 0:  # Log every ~60s
                logger.info(
                    f"Sent {count} gentle frames | "
                    f"mean={features[0]:.3f} contrast={features[1]:.3f} "
                    f"edge={features[2]:.3f}"
                )

            await asyncio.sleep(SEND_INTERVAL)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gentle sensory enrichment")
    parser.add_argument("--ws-uri", default="ws://127.0.0.1:7879")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between feature sends (default: 2.0)")
    args = parser.parse_args()
    SEND_INTERVAL = args.interval

    try:
        asyncio.run(run(args.ws_uri))
    except KeyboardInterrupt:
        logger.info("Gentle sensory stopped")
