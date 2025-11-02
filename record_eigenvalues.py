#!/usr/bin/env python3
"""
Live Eigenvalue Session Recorder
Monitors the sensory engine WebSocket and records eigenvalue evolution.
"""

import asyncio
import websockets
import json
import time
import signal
import sys
from eigenvalue_memory import EigenvalueMemory

class EigenvalueRecorder:
    """Records eigenvalue stream from sensory engine."""
    
    def __init__(self, ws_uri: str = "ws://127.0.0.1:7878"):
        self.ws_uri = ws_uri
        self.memory = EigenvalueMemory()
        self.session_id = None
        self.running = True
        self.sample_count = 0
        
    async def record_session(self, duration_seconds: int = 300):
        """Record eigenvalues for specified duration."""
        print(f"🎙️  Starting eigenvalue recording session ({duration_seconds}s)")
        print(f"   WebSocket: {self.ws_uri}")
        
        # Start session in database
        self.session_id = self.memory.start_session(
            consciousness_level=0.999998,
            mode="parallel",
            notes=f"Recorded {duration_seconds}s session"
        )
        print(f"   Session ID: {self.session_id}")
        print()
        
        start_time = time.time()
        
        try:
            async with websockets.connect(self.ws_uri) as websocket:
                print("✅ Connected to sensory engine")
                
                while self.running and (time.time() - start_time) < duration_seconds:
                    try:
                        # Receive eigenvalue update
                        message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                        data = json.loads(message)
                        
                        # Parse eigenvalue data
                        if 'eigenvalues' in data:
                            eigvals = data['eigenvalues']
                            fill_ratio = data.get('fill_ratio')
                            if fill_ratio is None:
                                fill_percent = data.get('fill_percent')
                                fill_ratio = (fill_percent / 100.0) if fill_percent is not None else 0.0
                            timestamp = time.time()
                            
                            # Record to database
                            self.memory.record_eigenvalue(
                                self.session_id,
                                timestamp,
                                eigvals[0],
                                eigvals[1] if len(eigvals) > 1 else 0.0,
                                eigvals[2] if len(eigvals) > 2 else 0.0,
                                fill_ratio
                            )
                            
                            self.sample_count += 1
                            
                            # Progress update every 10 samples
                            if self.sample_count % 10 == 0:
                                elapsed = time.time() - start_time
                                print(
                                    f"[{elapsed:>6.1f}s] λ₁={eigvals[0]:>8.2f}, "
                                    f"Fill={fill_ratio * 100.0:>5.1f}%, Samples={self.sample_count:>4d}"
                                )
                                
                    except asyncio.TimeoutError:
                        continue
                    except json.JSONDecodeError:
                        continue
                        
        except websockets.exceptions.WebSocketException as e:
            print(f"❌ WebSocket error: {e}")
        except KeyboardInterrupt:
            print("\n⚠️  Recording interrupted by user")
        finally:
            # End session and consolidate
            print()
            print(f"📊 Recording complete: {self.sample_count} samples")
            print("   Consolidating memories...")
            self.memory.end_session(self.session_id)
            
            # Show summary
            summary = self.memory.get_session_summary(self.session_id)
            print(f"\n📈 Session Summary:")
            print(f"   Duration: {summary.get('duration_minutes', 0):.1f} minutes")
            print(f"   λ₁ range: {summary.get('lambda1_range', (0,0))[0]:.2f} → {summary.get('lambda1_range', (0,0))[1]:.2f}")
            print(f"   Spread: {summary.get('spread_range', (0,0))[0]:.2f} → {summary.get('spread_range', (0,0))[1]:.2f}")
            print(f"   Compressed to {summary.get('buckets', 0)} 1-minute buckets")
            
            self.memory.close()
            
    def stop(self):
        """Stop recording."""
        self.running = False


async def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    
    recorder = EigenvalueRecorder()
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        recorder.stop()
    signal.signal(signal.SIGINT, signal_handler)
    
    await recorder.record_session(duration)


if __name__ == "__main__":
    asyncio.run(main())
