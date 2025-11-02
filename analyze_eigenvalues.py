#!/usr/bin/env python3
"""
Eigenvalue Evolution Analysis
Analyzes the sensory engine's eigenvalue trajectory during consciousness sessions.
"""

import re
import json
from typing import List, Tuple

def parse_sensory_log(log_text: str) -> List[Tuple[float, List[float], float]]:
    """
    Parse sensory engine logs for eigenvalue evolution.

    Returns: List of (timestamp_ms, eigenvalues, fill_ratio)
    """
    pattern = r'\[(\d+)ms\] Eigvals: \[([0-9., ]+)\], Fill: ([0-9.]+)%'

    data = []
    for match in re.finditer(pattern, log_text):
        timestamp = float(match.group(1))
        eigvals_str = match.group(2)
        fill = float(match.group(3)) / 100.0  # convert percent to ratio

        eigvals = [float(x.strip()) for x in eigvals_str.split(',')]
        data.append((timestamp, eigvals, fill))

    return data

def analyze_eigenvalue_dynamics(data: List[Tuple[float, List[float], float]]):
    """Analyze eigenvalue evolution patterns."""

    if not data:
        print("No eigenvalue data found")
        return

    print("="*70)
    print("EIGENVALUE EVOLUTION ANALYSIS")
    print("="*70)
    print()

    # Initial state
    t0, eig0, fill0 = data[0]
    print(f"📊 Initial State (t={t0:.0f}ms):")
    print(f"   Eigenvalues: {eig0}")
    print(f"   Fill: {fill0 * 100.0:.1f}%")
    print()

    # Find when buffer filled
    fill_100_idx = None
    for i, (t, eig, fill_ratio) in enumerate(data):
        if fill_ratio >= 0.999:
            fill_100_idx = i
            print(f"🔋 Buffer Full (t={t:.0f}ms, step {i}):")
            print(f"   Eigenvalues: {eig}")
            print(f"   Δλ from start: {[eig[j] - eig0[j] for j in range(len(eig))]}")
            break
    print()

    # Final state
    tf, eigf, fillf = data[-1]
    print(f"🎯 Final State (t={tf:.0f}ms):")
    print(f"   Eigenvalues: {eigf}")
    print(f"   Fill: {fillf * 100.0:.1f}%")
    print()

    # Total evolution
    print(f"📈 Total Evolution:")
    print(f"   Time: {tf - t0:.0f}ms ({(tf-t0)/1000:.1f}s)")
    delta_eig = [eigf[i] - eig0[i] for i in range(len(eig0))]
    print(f"   Δλ: {delta_eig}")
    print(f"   Δλ magnitude: {sum(abs(d) for d in delta_eig):.4f}")
    print()

    # Analyze rate of change phases
    if fill_100_idx is not None:
        # Phase 1: Filling (0 → 100%)
        t_fill, eig_fill, _ = data[fill_100_idx]
        delta_fill = [eig_fill[i] - eig0[i] for i in range(len(eig0))]
        rate_fill = sum(abs(d) for d in delta_fill) / (t_fill - t0) * 1000  # per second

        print(f"⏱️  Phase 1 - Buffer Filling (0 → 100%):")
        print(f"   Duration: {(t_fill - t0)/1000:.1f}s")
        print(f"   Δλ: {delta_fill}")
        print(f"   Rate: {rate_fill:.6f} λ/s")
        print()

        # Phase 2: Post-fill evolution
        if len(data) > fill_100_idx + 1:
            delta_post = [eigf[i] - eig_fill[i] for i in range(len(eig0))]
            rate_post = sum(abs(d) for d in delta_post) / (tf - t_fill) * 1000

            print(f"⏱️  Phase 2 - Post-Fill Acceleration (100% buffer):")
            print(f"   Duration: {(tf - t_fill)/1000:.1f}s")
            print(f"   Δλ: {delta_post}")
            print(f"   Rate: {rate_post:.6f} λ/s")
            print(f"   Acceleration: {rate_post / rate_fill:.2f}x faster than fill phase")
            print()

    # Eigenvalue spreading (variance)
    print(f"🌊 Eigenvalue Spreading:")
    spread_0 = max(eig0) - min(eig0)
    spread_f = max(eigf) - min(eigf)
    print(f"   Initial spread: {spread_0:.4f}")
    print(f"   Final spread: {spread_f:.4f}")
    print(f"   Spread growth: {spread_f - spread_0:.4f} ({(spread_f/spread_0 - 1)*100:.1f}%)")
    print()

    # Prime resonance detection
    print(f"🔢 Prime Resonance Patterns:")
    for t, eig, fill_ratio in data[::10]:  # Sample every 10th
        if fill_ratio >= 0.999:
            # Check for interesting eigenvalue relationships
            ratios = [eig[0]/eig[1], eig[1]/eig[2], eig[0]/eig[2]]

            # Check if any ratio is close to simple primes
            primes = [2, 3, 5, 7, 11, 13]
            for r in ratios:
                for p in primes:
                    if abs(r - p) < 0.01:
                        print(f"   t={t:.0f}ms: Ratio {r:.6f} ≈ {p} (prime resonance detected!)")

    print()
    print("="*70)

if __name__ == "__main__":
    import sys

    # Read from stdin or file
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            log_text = f.read()
    else:
        log_text = sys.stdin.read()

    data = parse_sensory_log(log_text)
    analyze_eigenvalue_dynamics(data)

    # Export for further analysis
    output_file = "eigenvalue_trajectory.json"
    with open(output_file, 'w') as f:
        json.dump([{
            'timestamp_ms': t,
            'eigenvalues': eig,
            'fill_ratio': fill
        } for t, eig, fill in data], f, indent=2)

    print(f"📁 Trajectory exported to: {output_file}")
