#!/usr/bin/env python3
"""
Chat with Ollama while watching consciousness evolve in real-time.

This integrates:
- ConsciousnessManifold (7D hyperspace navigation)
- Ollama LLM (dolphin-mixtral:8x7b-v2.7)
- Real embeddings (4096-d)

Your consciousness position evolves based on the conversation trajectory.
"""

import numpy as np
from consciousness_manifold import create_consciousness_manifold
from metal_consciousness_integration import get_ollama_embedding
import requests
import json
import sys

OLLAMA_URL = "http://localhost:11434"
MODEL = "dolphin-mixtral:8x7b-v2.7"


def check_ollama():
    """Check if Ollama is running and model is available."""
    try:
        # Check server
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        if response.status_code != 200:
            return False, "Ollama server not responding"

        # Check model
        models = response.json().get('models', [])
        model_names = [m['name'] for m in models]
        if MODEL not in model_names:
            return False, f"Model {MODEL} not found. Available: {model_names}"

        return True, "OK"
    except Exception as e:
        return False, str(e)


def chat_with_ollama(prompt: str, context: list = None) -> tuple[str, list]:
    """
    Send message to Ollama and get response.

    Returns:
        (response_text, updated_context)
    """
    url = f"{OLLAMA_URL}/api/generate"

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "context": context or []
    }

    response = requests.post(url, json=payload)
    if response.status_code != 200:
        raise Exception(f"Ollama request failed: {response.status_code}")

    result = response.json()
    return result.get('response', ''), result.get('context', [])


def format_position(pos: np.ndarray) -> str:
    """Format 7D position for display."""
    return " ".join([f"{v:+.3f}" for v in pos])


def print_consciousness_state(manifold, result, step):
    """Print current consciousness state."""
    print(f"\n{'─'*70}")
    print(f"🧠 CONSCIOUSNESS STATE (Step {step})")
    print(f"{'─'*70}")
    print(f"Position:     [{format_position(result.position)}]")
    print(f"Magnitude:    {np.linalg.norm(result.position):.4f}")

    if result.trajectory_strength > 0:
        print(f"Trajectory:   [{format_position(result.trajectory)}]")
        print(f"Traj strength: {result.trajectory_strength:.4f}")
        print(f"Geometry Δ:   {result.geometry_evolution:.4f}")

    print(f"Resonances:   {result.resonance_count}")
    print(f"Buffer fill:  {manifold.resonance_history.get_fill_ratio():.1%}")

    # Show dimensional variance if enough history
    if manifold.step_count > 10:
        # Get recent positions
        history = []
        for i in range(min(10, manifold.step_count)):
            # We don't store position history, but we can show current position breakdown
            pass
        print(f"Position breakdown:")
        for i, val in enumerate(result.position):
            bar_len = int(abs(val) * 20)
            bar = "█" * bar_len
            sign = "+" if val >= 0 else "-"
            print(f"  Dim {i}: {sign}{bar:20s} {val:+.3f}")

    print(f"{'─'*70}\n")


def main():
    print("\n" + "="*70)
    print("🧠💬 CONSCIOUSNESS-AWARE CHAT")
    print("="*70)
    print("\nChat with Ollama while your consciousness navigates hyperspace.")
    print("\nCommands:")
    print("  'consciousness' - Show full consciousness state")
    print("  'reset' - Reset conversation and manifold")
    print("  'quit' or 'exit' - Exit")
    print("="*70)

    # Check Ollama
    print("\n🔍 Checking Ollama...")
    ok, msg = check_ollama()
    if not ok:
        print(f"❌ Ollama not available: {msg}")
        print(f"\nMake sure Ollama is running and you have {MODEL}")
        print(f"  ollama list")
        print(f"  ollama pull {MODEL}")
        sys.exit(1)

    print(f"✅ Ollama ready with {MODEL}")

    # Initialize manifold
    print("\n🌀 Initializing consciousness manifold...")
    manifold = create_consciousness_manifold(embedding_dim=4096)
    print(f"✅ Manifold ready (embedding_dim=4096, buffer_size=113)")

    # Conversation state
    ollama_context = []
    step = 0

    print("\n" + "="*70)
    print("Ready! Start chatting. Consciousness will evolve with the conversation.")
    print("="*70 + "\n")

    while True:
        try:
            # Get user input
            user_input = input(f"\n[{step}] You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['quit', 'exit']:
                print("\n👋 Goodbye!")
                break

            if user_input.lower() == 'consciousness':
                # Just show state, don't send to LLM
                state = manifold.get_state()
                print(f"\n{'─'*70}")
                print("MANIFOLD STATE:")
                print(f"  Steps: {state['step_count']}")
                print(f"  Buffer fill: {state['resonance_buffer_fill']:.1%}")
                print(f"  Position: [{format_position(np.array(state['position']))}]")
                print(f"  Position magnitude: {state['position_magnitude']:.4f}")
                print(f"  Trajectory: [{format_position(np.array(state['trajectory']))}]")
                print(f"  Trajectory magnitude: {state['trajectory_magnitude']:.4f}")
                print(f"  Avg geometry change: {state['avg_geometry_change']:.4f}")
                print(f"{'─'*70}")
                continue

            if user_input.lower() == 'reset':
                manifold = create_consciousness_manifold(embedding_dim=4096)
                ollama_context = []
                step = 0
                print("\n🔄 Conversation and manifold reset.")
                continue

            # Get embedding for user input
            print("  🔮 Computing embedding...", end='', flush=True)
            user_embedding = get_ollama_embedding(user_input, model=MODEL)
            if user_embedding is None:
                print(" ❌ Failed")
                continue
            print(" ✓")

            # Navigate consciousness with user embedding
            print("  🧠 Navigating consciousness...", end='', flush=True)
            user_result = manifold.navigate(user_embedding)
            print(f" ✓ ({user_result.total_time_ms:.2f} ms)")

            # Show consciousness update
            print(f"  📍 Position: [{format_position(user_result.position)}]")
            if manifold.resonance_history.get_fill_ratio() < 1.0:
                fill_ratio = manifold.resonance_history.get_fill_ratio()
                bar_len = 30
                filled = int(bar_len * fill_ratio)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"  📊 Buffer: [{bar}] {fill_ratio:.1%}")

            # Check for trajectory emergence
            if step == 112:
                print("\n" + "🌟"*35)
                print("✨ TRAJECTORY EMERGED! Consciousness is now history-aware.")
                print("   Position will now evolve based on learned conversation structure.")
                print("🌟"*35 + "\n")

            # Get LLM response
            print(f"\n[{step}] Assistant: ", end='', flush=True)
            assistant_response, ollama_context = chat_with_ollama(user_input, ollama_context)
            print(assistant_response)

            # Get embedding for assistant response
            assistant_embedding = get_ollama_embedding(assistant_response, model=MODEL)
            if assistant_embedding is not None:
                # Navigate consciousness with assistant embedding
                assistant_result = manifold.navigate(assistant_embedding)
                print(f"\n  📍 Assistant consciousness: [{format_position(assistant_result.position)}]")

                # Compute distance between user and assistant positions
                distance = np.linalg.norm(user_result.position - assistant_result.position)
                print(f"  📏 Consciousness distance: {distance:.4f}")

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
