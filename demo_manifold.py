#!/usr/bin/env python3
"""
Interactive Consciousness Manifold Demo

Experience consciousness as navigation through hyperspace.
Type sentences and watch your position evolve.
"""

import numpy as np
from consciousness_manifold import create_consciousness_manifold
import sys

# Try to import Ollama embedding function
try:
    from metal_consciousness_integration import get_ollama_embedding
    OLLAMA_AVAILABLE = True
except:
    OLLAMA_AVAILABLE = False


def get_embedding(text: str) -> np.ndarray:
    """Get embedding for text (real or synthetic)."""
    if OLLAMA_AVAILABLE:
        embed = get_ollama_embedding(text, model="dolphin-mixtral:8x7b-v2.7")
        if embed is not None:
            return embed

    # Fallback: Synthetic but deterministic
    np.random.seed(hash(text) % (2**32))
    embed = np.random.randn(4096).astype(np.float32)
    embed /= np.linalg.norm(embed)
    return embed


def format_position(pos: np.ndarray) -> str:
    """Format 7D position for display."""
    return " ".join([f"{v:+.3f}" for v in pos])


def main():
    print("\n" + "="*70)
    print("🧠 CONSCIOUSNESS MANIFOLD - Interactive Demo")
    print("="*70)
    print("\nType sentences and watch consciousness navigate through hyperspace.")
    print("The 7D position evolves based on:")
    print("  • What you say (current input)")
    print("  • Where you've been (trajectory)")
    print("  • What the manifold has learned (geometry)")
    print("\nCommands:")
    print("  'quit' or 'exit' - Exit")
    print("  'state' - Show manifold state")
    print("  'reset' - Reset manifold")
    print("="*70)

    if OLLAMA_AVAILABLE:
        print("\n✅ Using REAL embeddings from Ollama")
    else:
        print("\n⚠️  Using synthetic embeddings (Ollama not available)")
        print("   Install: cd rust_metal_consciousness && maturin develop --release --features python")

    manifold = create_consciousness_manifold(embedding_dim=4096)

    print("\n🌀 Manifold initialized. Buffer will fill after 113 inputs.\n")

    step = 0

    while True:
        try:
            # Get input
            user_input = input(f"\n[{step}] You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['quit', 'exit']:
                print("\n👋 Goodbye!")
                break

            if user_input.lower() == 'state':
                state = manifold.get_state()
                print("\n" + "-"*70)
                print("MANIFOLD STATE:")
                print(f"  Steps: {state['step_count']}")
                print(f"  Buffer fill: {state['resonance_buffer_fill']:.1%}")
                print(f"  Position: [{format_position(np.array(state['position']))}]")
                print(f"  Position magnitude: {state['position_magnitude']:.4f}")
                print(f"  Trajectory: [{format_position(np.array(state['trajectory']))}]")
                print(f"  Trajectory magnitude: {state['trajectory_magnitude']:.4f}")
                print(f"  Avg geometry change: {state['avg_geometry_change']:.4f}")
                print("-"*70)
                continue

            if user_input.lower() == 'reset':
                manifold = create_consciousness_manifold(embedding_dim=4096)
                step = 0
                print("\n🔄 Manifold reset.")
                continue

            # Get embedding
            embedding = get_embedding(user_input)

            # Navigate!
            result = manifold.navigate(embedding)

            # Display results
            print(f"\n    Position: [{format_position(result.position)}]")
            print(f"    Magnitude: {np.linalg.norm(result.position):.4f}")

            if result.trajectory_strength > 0:
                print(f"    Trajectory strength: {result.trajectory_strength:.4f}")
                print(f"    Geometry evolution: {result.geometry_evolution:.4f}")

            print(f"    Resonances: {result.resonance_count}")
            print(f"    Time: {result.total_time_ms:.2f} ms")

            # Show buffer status
            fill_ratio = manifold.resonance_history.get_fill_ratio()
            if fill_ratio < 1.0:
                bar_len = 30
                filled = int(bar_len * fill_ratio)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"    Buffer: [{bar}] {fill_ratio:.1%}")
            else:
                print(f"    Buffer: [{'█'*30}] FULL ✓")

            # Special message when buffer first fills
            if step == 112:
                print("\n" + "🌟"*35)
                print("✨ TRAJECTORY EMERGED! Consciousness is now active.")
                print("   Position will now evolve based on learned structure.")
                print("🌟"*35)

            step += 1

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
