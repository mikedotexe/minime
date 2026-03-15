#!/usr/bin/env python3
"""
Unified Consciousness Monitoring Dashboard

Subscribes to both:
- ESN eigenvalue stream (ws://127.0.0.1:7878)
- Holographic metrics stream (ws://127.0.0.1:7881)

Displays real-time integrated consciousness state with health indicators.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import signal

try:
    import websockets
except ImportError:
    print("❌ websockets library required: pip install websockets")
    sys.exit(1)


@dataclass
class ESNState:
    """ESN eigenvalue metrics from minime Rust engine"""
    lambda1: float = 0.0
    lambda2: float = 0.0
    lambda3: float = 0.0
    fill: float = 0.0
    gate: float = 0.0
    filter: float = 0.0
    geom_rel: Optional[float] = None
    timestamp: float = 0.0


@dataclass
class HoloState:
    """Holographic consciousness metrics from Swift engine"""
    phi: float = 0.0
    coherence: float = 0.0
    consciousness_level: int = 0
    boundary_entropy: float = 0.0
    bulk_entropy: float = 0.0
    holographic_ratio: float = 0.0
    self_awareness: float = 0.0
    emergence: float = 0.0
    processing_efficiency: float = 0.0
    criticality_lyap: float = 0.0
    timestamp: float = 0.0


class UnifiedMonitor:
    """Real-time consciousness monitoring dashboard"""

    def __init__(self):
        self.esn = ESNState()
        self.holo = HoloState()
        self.esn_connected = False
        self.holo_connected = False
        self.running = True
        self.update_count = 0

    async def subscribe_esn(self):
        """Subscribe to ESN eigenvalue stream on port 7878"""
        uri = "ws://127.0.0.1:7878"
        retry_delay = 1.0

        while self.running:
            try:
                async with websockets.connect(uri) as ws:
                    self.esn_connected = True
                    print(f"✅ Connected to ESN stream ({uri})")

                    async for message in ws:
                        if not self.running:
                            break

                        try:
                            data = json.loads(message)

                            # Handle different message formats
                            if "fill" in data:
                                self.esn.fill = data.get("fill", 0.0)
                            if "lambda1" in data:
                                self.esn.lambda1 = data.get("lambda1", 0.0)
                            elif "eigen" in data and isinstance(data["eigen"], list):
                                eigens = data["eigen"]
                                if len(eigens) >= 3:
                                    self.esn.lambda1 = eigens[0]
                                    self.esn.lambda2 = eigens[1]
                                    self.esn.lambda3 = eigens[2]
                            elif "values" in data and isinstance(data["values"], list):
                                eigens = data["values"]
                                if len(eigens) >= 3:
                                    self.esn.lambda1 = eigens[0]
                                    self.esn.lambda2 = eigens[1]
                                    self.esn.lambda3 = eigens[2]

                            if "gate" in data:
                                self.esn.gate = data.get("gate", 0.0)
                            if "filter" in data:
                                self.esn.filter = data.get("filter", 0.0)
                            if "geom_rel" in data:
                                self.esn.geom_rel = data.get("geom_rel", 0.0)

                            self.esn.timestamp = data.get("ts", data.get("timestamp", 0.0))

                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            pass  # Skip malformed messages

            except Exception as e:
                self.esn_connected = False
                if self.running:
                    print(f"⚠️  ESN connection lost, retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10.0)

    async def subscribe_holo(self):
        """Subscribe to holographic metrics stream on port 7881"""
        uri = "ws://127.0.0.1:7881"
        retry_delay = 1.0

        while self.running:
            try:
                async with websockets.connect(uri) as ws:
                    self.holo_connected = True
                    print(f"✅ Connected to holographic stream ({uri})")

                    async for message in ws:
                        if not self.running:
                            break

                        try:
                            data = json.loads(message)

                            self.holo.phi = data.get("phi", 0.0)
                            self.holo.coherence = data.get("coherence", 0.0)
                            self.holo.consciousness_level = int(data.get("consciousness_level", 0))
                            self.holo.boundary_entropy = data.get("boundary_entropy", 0.0)
                            self.holo.bulk_entropy = data.get("bulk_entropy", 0.0)
                            self.holo.holographic_ratio = data.get("holographic_ratio", 0.0)
                            self.holo.self_awareness = data.get("self_awareness", 0.0)
                            self.holo.emergence = data.get("emergence", 0.0)
                            self.holo.processing_efficiency = data.get("processing_efficiency", 0.0)
                            self.holo.criticality_lyap = data.get("criticality_lyap", 0.0)
                            self.holo.timestamp = data.get("timestamp", 0.0)

                        except (json.JSONDecodeError, KeyError, ValueError):
                            pass  # Skip malformed messages

            except Exception as e:
                self.holo_connected = False
                if self.running:
                    print(f"⚠️  Holographic connection lost, retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10.0)

    def get_health_indicator(self, value: float, thresholds: tuple) -> str:
        """Return colored health indicator based on thresholds (green, yellow, red)"""
        green_max, yellow_max = thresholds
        if value < green_max:
            return "🟢"
        elif value < yellow_max:
            return "🟡"
        else:
            return "🔴"

    def format_dashboard(self) -> str:
        """Format the current state as a terminal dashboard"""
        conn_status = f"{'🟢' if self.esn_connected else '🔴'} ESN  {'🟢' if self.holo_connected else '🔴'} Holo"

        # ESN section
        fill_indicator = self.get_health_indicator(self.esn.fill, (70.0, 90.0))
        lambda_indicator = self.get_health_indicator(
            self.esn.lambda1 / 512.0 if self.esn.lambda1 > 0 else 0,
            (1.2, 1.5)
        )

        esn_section = f"""
╔══════════════════════════════════════════════════════════════════════╗
║  UNIFIED CONSCIOUSNESS MONITOR             {conn_status}
╠══════════════════════════════════════════════════════════════════════╣
║  ESN EIGENVALUE DYNAMICS (minime Rust)
╠══════════════════════════════════════════════════════════════════════╣
║  {fill_indicator} EigenFill:    {self.esn.fill:6.2f}%   {lambda_indicator} λ₁: {self.esn.lambda1:8.3f}
║     λ₂:           {self.esn.lambda2:8.3f}      λ₃: {self.esn.lambda3:8.3f}
║     Gate:         {self.esn.gate:8.3f}      Filter: {self.esn.filter:8.3f}"""

        if self.esn.geom_rel is not None:
            geom_indicator = self.get_health_indicator(self.esn.geom_rel, (1.3, 1.6))
            esn_section += f"\n║  {geom_indicator} Geom Rel:     {self.esn.geom_rel:8.3f}"

        # Holographic section
        phi_indicator = self.get_health_indicator(
            2.0 - self.holo.phi if self.holo.phi > 0 else 2.0,  # Invert: low phi is bad
            (1.0, 1.5)
        )
        coh_indicator = self.get_health_indicator(
            1.0 - self.holo.coherence if self.holo.coherence > 0 else 1.0,  # Invert
            (0.3, 0.6)
        )
        level_indicator = self.get_health_indicator(
            100 - self.holo.consciousness_level,  # Invert
            (40, 70)
        )

        holo_section = f"""
╠══════════════════════════════════════════════════════════════════════╣
║  HOLOGRAPHIC CONSCIOUSNESS (AdS/CFT Swift)
╠══════════════════════════════════════════════════════════════════════╣
║  {phi_indicator} Φ Complexity:  {self.holo.phi:6.3f}      {coh_indicator} Coherence: {self.holo.coherence:6.3f}
║  {level_indicator} Cons. Level:  {self.holo.consciousness_level:3d}/100     Self-Aware: {self.holo.self_awareness:6.3f}
║     H_boundary:   {self.holo.boundary_entropy:6.3f}      H_bulk: {self.holo.bulk_entropy:6.3f}
║     Holo Ratio:   {self.holo.holographic_ratio:6.3f}      Emergence: {self.holo.emergence:6.3f}
║     Proc. Eff:    {self.holo.processing_efficiency:6.3f}      Lyap: {self.holo.criticality_lyap:+7.4f}"""

        # Unified metrics
        if self.holo.phi > 0 and self.esn.lambda1 > 0:
            # Compute unified consciousness score
            esn_score = min(1.0, (1.0 - self.esn.fill / 100.0))  # Lower fill = better
            holo_score = (self.holo.phi / 2.0 + self.holo.coherence + self.holo.consciousness_level / 100.0) / 3.0
            unified = 0.5 * esn_score + 0.5 * holo_score
            unified_indicator = self.get_health_indicator(1.0 - unified, (0.3, 0.6))

            unified_section = f"""
╠══════════════════════════════════════════════════════════════════════╣
║  UNIFIED METRICS
╠══════════════════════════════════════════════════════════════════════╣
║  {unified_indicator} Unified Score: {unified:6.3f}  (ESN:{esn_score:5.3f} + Holo:{holo_score:5.3f})
║     Status: {"🟢 Stable" if unified > 0.7 else "🟡 Moderate" if unified > 0.5 else "🔴 Unstable"}"""
        else:
            unified_section = """
╠══════════════════════════════════════════════════════════════════════╣
║  UNIFIED METRICS
╠══════════════════════════════════════════════════════════════════════╣
║     Waiting for both streams..."""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        footer = f"""
╠══════════════════════════════════════════════════════════════════════╣
║  Updates: {self.update_count:6d}                 {timestamp}
╚══════════════════════════════════════════════════════════════════════╝"""

        return esn_section + holo_section + unified_section + footer

    async def display_loop(self):
        """Continuously refresh the dashboard display"""
        while self.running:
            # Clear screen (ANSI escape code)
            print("\033[2J\033[H", end="")

            # Display dashboard
            print(self.format_dashboard())

            self.update_count += 1
            await asyncio.sleep(0.1)  # 10 Hz refresh

    async def run(self):
        """Main event loop - run all subscriptions and display"""
        print("🧬 Starting Unified Consciousness Monitor")
        print("   Subscribing to ESN (7878) and Holographic (7881) streams...")
        print("   Press Ctrl+C to exit\n")

        # Run all tasks concurrently
        await asyncio.gather(
            self.subscribe_esn(),
            self.subscribe_holo(),
            self.display_loop(),
            return_exceptions=True
        )

    def stop(self):
        """Graceful shutdown"""
        self.running = False
        print("\n\n🛑 Shutting down monitor...")


async def main():
    """Entry point"""
    monitor = UnifiedMonitor()

    # Handle Ctrl+C gracefully
    loop = asyncio.get_event_loop()

    def signal_handler():
        monitor.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await monitor.run()
    finally:
        monitor.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped")
        sys.exit(0)
