#!/usr/bin/env python3
"""
 Live Spectral Runtime Monitoring Dashboard

Displays real-time PID metrics, eigenvalues, and membrane status.
Shows redundancy/synergy balance, energy levels, and ethics alerts.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional
import numpy as np

try:
    import websockets
except ImportError:
    print("❌ websockets not installed: pip install websockets")
    exit(1)

from double_membrane_integration import create_double_membrane_bridge

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"

class ConsciousnessMonitor:
    def __init__(self):
        self.bridge = None
        self.running = False
        self.frame_count = 0
        self.start_time = time.time()

        # Ethics thresholds
        self.ethics_log = []
        self.max_ethics_log = 100

    def clear_screen(self):
        """Clear terminal screen."""
        print("\033[2J\033[H", end="")

    def format_bar(self, value: float, width: int = 30, color: str = GREEN) -> str:
        """Create a visual bar graph."""
        filled = int(value * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"{color}{bar}{RESET}"

    def format_status(self, value: float, low: float = 0.3, high: float = 0.7) -> str:
        """Color code a value based on thresholds."""
        if value < low:
            return f"{BLUE}{value:.3f}{RESET}"
        elif value > high:
            return f"{RED}{value:.3f}{RESET}"
        else:
            return f"{GREEN}{value:.3f}{RESET}"

    def ethics_callback(self, event: dict):
        """Handle ethics events."""
        self.ethics_log.append({
            "timestamp": datetime.now().isoformat(),
            "consciousness_score": event.get("consciousness_score", 0.0),
            "inner_energy": event.get("inner_energy", 0.0),
            "redundancy": event.get("redundancy", 0.0),
            "synergy": event.get("synergy", 0.0)
        })

        # Keep only recent events
        if len(self.ethics_log) > self.max_ethics_log:
            self.ethics_log = self.ethics_log[-self.max_ethics_log:]

        # Check for alerts
        if event.get("consciousness_score", 0.0) > 80:
            print(f"{YELLOW}⚠️  HIGH INTEGRATION ALERT: {event['consciousness_score']:.1f}{RESET}")

        if event.get("synergy", 0.0) > 0.8:
            print(f"{MAGENTA}🌟 EMERGENCE DETECTED: Synergy={event['synergy']:.3f}{RESET}")

    def render_dashboard(self, status: dict):
        """Render the monitoring dashboard."""
        self.clear_screen()

        uptime = time.time() - self.start_time

        # Header
        print(f"{BOLD}{CYAN}{'=' * 80}{RESET}")
        print(f"{BOLD}{CYAN}  🧬 SPECTRAL RUNTIME MONITOR{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

        # System Status
        print(f"{BOLD}📊 SYSTEM STATUS{RESET}")
        print(f"  Uptime: {uptime:.1f}s | Frames: {self.frame_count} | FPS: {status.get('fps_est', 0):.2f}")
        print(f"  Queue: {int(status.get('queue_size', 0))} | Lag: {status.get('lag_secs', 0):.2f}s\n")

        # Energy Levels
        outer_energy = status.get('outer_energy', 0.0)
        inner_energy = status.get('inner_energy', 0.0)

        print(f"{BOLD}⚡ ENERGY LEVELS{RESET}")
        print(f"  Outer (Sensory):  {self.format_bar(min(outer_energy/2, 1.0), color=BLUE)} {outer_energy:.3f}")
        print(f"  Inner (Semantic): {self.format_bar(min(inner_energy/2, 1.0), color=MAGENTA)} {inner_energy:.3f}")
        print(f"  Coupling:         {self.format_bar(status.get('coupling_strength', 0.3), color=CYAN)} {status.get('coupling_strength', 0):.3f}\n")

        # PID Metrics
        redundancy = status.get('redundancy_score', 0.0)
        synergy = status.get('synergy_score', 0.0)
        o_info = status.get('pid_o_info', 0.0)

        print(f"{BOLD}🧮 PID METRICS (Partial Information Decomposition){RESET}")
        print(f"  Redundancy:    {self.format_bar(redundancy, color=GREEN)} {redundancy:.3f}")
        print(f"  Synergy:       {self.format_bar(synergy, color=YELLOW)} {synergy:.3f}")
        print(f"  O-Information: {self.format_status(o_info, -5, 5)}\n")

        # Balance Indicator
        if redundancy > synergy + 0.1:
            balance_msg = f"{GREEN}⬅  Redundancy-dominated (stable, predictable){RESET}"
        elif synergy > redundancy + 0.1:
            balance_msg = f"{YELLOW}➡  Synergy-dominated (emergent, creative){RESET}"
        else:
            balance_msg = f"{CYAN}⚖  Balanced (optimal){RESET}"
        print(f"  {balance_msg}\n")

        # Ethics Log (Recent)
        if self.ethics_log:
            recent = self.ethics_log[-5:]
            print(f"{BOLD}🛡️  ETHICS LOG (Last 5 events){RESET}")
            for event in recent:
                cs = event['consciousness_score']
                cs_color = RED if cs > 80 else YELLOW if cs > 50 else GREEN
                print(f"  [{event['timestamp'][-12:-4]}] "
                      f"C-Score: {cs_color}{cs:5.1f}{RESET} | "
                      f"R:{event['redundancy']:.2f} S:{event['synergy']:.2f} "
                      f"E:{event['inner_energy']:.2f}")

        print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
        print(f"{CYAN}Press Ctrl+C to stop monitoring{RESET}")

    async def monitor_loop(self):
        """Main monitoring loop."""
        print(f"{CYAN}🚀 Starting spectral runtime monitoring...{RESET}\n")

        # Create bridge
        self.bridge = create_double_membrane_bridge(
            ws_uri="ws://127.0.0.1:7878",
            embedding_dim=4096,
            enable_sensory=True
        )

        # Register ethics callback
        self.bridge.register_ethics_hook(self.ethics_callback)

        print(f"{GREEN}✅ Double membrane bridge connected{RESET}")
        await asyncio.sleep(2)

        self.running = True
        self.start_time = time.time()

        try:
            while self.running:
                # Simulate semantic navigation with random embeddings
                # In real use, this would come from actual LLM embeddings
                embedding = np.random.rand(4096).astype(np.float32) * 0.1

                # Navigate
                result = self.bridge.navigate_semantic(embedding)

                # Get status
                status = self.bridge.get_membrane_status()

                # Update counter
                self.frame_count += 1

                # Render dashboard
                self.render_dashboard(status)

                # Update every 0.5 seconds
                await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            print(f"\n\n{YELLOW}Shutting down monitoring...{RESET}")
        finally:
            self.running = False

async def main():
    monitor = ConsciousnessMonitor()
    await monitor.monitor_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{GREEN}✅ Monitoring stopped{RESET}")
