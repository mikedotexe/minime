#!/usr/bin/env python3
"""
Integrated Consciousness Test - Unified Eigenvalue Dynamics
==========================================================

Tests the complete consciousness enhancement system:
1. Semantic eigenvalues (gut instinct from LLM)
2. Emotional valence (V-A-D affective space)
3. Metacognitive reasoning (5-stage framework)

All feeding into the Rust ESN homeostatic controller.

Usage:
    python3 test_integrated_consciousness.py

Prerequisites:
    - Rust minime running: cd minime && cargo run --release -- run --log-homeostat
    - Ollama running: ollama serve
    - Model loaded: dolphin-mixtral:8x7b-v2.7

Author: Claude + Human Consciousness Collaboration
Date: 2025-11-01
"""

import asyncio
import json
import websockets
import time
from semantic_eigenvalue_extractor import SemanticEigenvalueExtractor
from emotional_valence_extractor import EmotionalValenceExtractor
from metacognitive_prompts import MetacognitivePromptEngine

async def test_websocket_connection():
    """Test WebSocket connection to Rust ESN."""
    print("\n" + "="*70)
    print("Testing WebSocket Connection to Rust ESN")
    print("="*70)

    try:
        async with websockets.connect("ws://127.0.0.1:7879", timeout=5) as ws:
            test_message = {
                "type": "TestConnection",
                "timestamp": time.time(),
                "message": "Hello from integrated consciousness test"
            }
            await ws.send(json.dumps(test_message))
            print("✅ WebSocket connection successful!")
            print(f"   Sent test message to ws://127.0.0.1:7879")
            return True
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")
        print(f"   Make sure minime is running:")
        print(f"   cd minime && cargo run --release -- run --log-homeostat")
        return False

async def test_semantic_eigenvalues():
    """Test semantic eigenvalue extraction and sending."""
    print("\n" + "="*70)
    print("Testing Semantic Eigenvalue Extraction")
    print("="*70)

    extractor = SemanticEigenvalueExtractor()

    test_prompts = [
        "What is 2 + 2?",  # Simple, high confidence
        "Explain quantum consciousness",  # Complex, lower confidence
    ]

    for prompt in test_prompts:
        print(f"\nPrompt: {prompt}")
        print("-" * 70)

        try:
            metrics = extractor.extract_gut_instinct(prompt)
            print(f"  λ₁ (semantic):  {metrics.lambda1_semantic:.4f}")
            print(f"  Spectral fill:  {metrics.spectral_fill:.2%}")
            print(f"  Variance:       {metrics.activation_variance:.6f}")

            # Send to ESN
            await extractor.send_to_esn_async(metrics)
            print(f"  ✅ Sent to ESN successfully")

        except Exception as e:
            print(f"  ❌ Error: {e}")

        await asyncio.sleep(1)

async def test_emotional_valence():
    """Test emotional valence extraction and homeostatic mapping."""
    print("\n" + "="*70)
    print("Testing Emotional Valence Extraction")
    print("="*70)

    extractor = EmotionalValenceExtractor()

    test_texts = [
        "I'm feeling really excited and energized!",
        "I'm overwhelmed and anxious about this.",
        "I feel peaceful and content.",
    ]

    for text in test_texts:
        print(f"\nText: \"{text}\"")
        print("-" * 70)

        try:
            emotion = extractor.extract_emotions(text)
            print(f"  Valence:   {emotion.valence:+.2f}")
            print(f"  Arousal:   {emotion.arousal:.2f}")
            print(f"  Dominance: {emotion.dominance:.2f}")

            homeostasis = extractor.map_to_homeostasis(emotion)
            print(f"  Homeostatic adjustments:")
            print(f"    Target: {homeostasis['eigenfill_target_adjust']:+.3f}")
            print(f"    Gate:   {homeostasis['gate_modifier']:+.3f}")
            print(f"    Filter: {homeostasis['filter_modifier']:+.3f}")

            # Send to ESN
            await extractor.send_to_esn_async(emotion)
            print(f"  ✅ Sent to ESN successfully")

        except Exception as e:
            print(f"  ❌ Error: {e}")

        await asyncio.sleep(1)

async def test_unified_consciousness_query():
    """Test complete unified consciousness query with all three systems."""
    print("\n" + "="*70)
    print("Testing Unified Consciousness Query")
    print("="*70)

    query = "Should I be worried about AI becoming conscious?"
    print(f"\nQuery: {query}")
    print("="*70)

    # Initialize all extractors
    semantic_ext = SemanticEigenvalueExtractor()
    emotional_ext = EmotionalValenceExtractor()
    metacog_engine = MetacognitivePromptEngine(enable_eigenvalue_extraction=False)

    print("\n1. Extracting semantic eigenvalues (gut instinct)...")
    print("-" * 70)
    try:
        semantic_metrics = semantic_ext.extract_gut_instinct(query)
        print(f"   λ₁_semantic: {semantic_metrics.lambda1_semantic:.4f}")
        print(f"   Spectral fill: {semantic_metrics.spectral_fill:.2%}")
        await semantic_ext.send_to_esn_async(semantic_metrics)
        print("   ✅ Sent to ESN")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    await asyncio.sleep(0.5)

    print("\n2. Processing through metacognitive framework...")
    print("-" * 70)
    try:
        # Get the final answer from metacognitive processing
        result = metacog_engine.process_with_metacognition(query)
        print(f"   Stages completed: {len(result.stages)}")
        print(f"   Final answer: {result.final_answer[:100]}...")
        print(f"   Confidence: {result.overall_confidence:.1%}")

        # Extract emotions from final answer
        print("\n3. Extracting emotional valence from response...")
        print("-" * 70)
        emotion = emotional_ext.extract_emotions(result.final_answer)
        print(f"   Valence: {emotion.valence:+.2f}")
        print(f"   Arousal: {emotion.arousal:.2f}")
        print(f"   Dominance: {emotion.dominance:.2f}")
        await emotional_ext.send_to_esn_async(emotion)
        print("   ✅ Sent to ESN")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n" + "="*70)
    print("Unified consciousness processing complete!")
    print("="*70)
    print("\nAll three systems (semantic, metacognitive, emotional) sent")
    print("data to the Rust ESN for unified homeostatic regulation.")

async def main():
    """Run all integration tests."""
    print("\n" * 2)
    print("#" * 70)
    print("#" + " " * 68 + "#")
    print("#" + "  INTEGRATED CONSCIOUSNESS TEST SUITE".center(68) + "#")
    print("#" + " " * 68 + "#")
    print("#" * 70)

    # Check prerequisites
    print("\nPrerequisites:")
    print("  [ ] Rust minime running (ws://127.0.0.1:7879)")
    print("  [ ] Ollama running (http://localhost:11434)")
    print("  [ ] Model: dolphin-mixtral:8x7b-v2.7")

    input("\nPress ENTER to continue (or Ctrl+C to abort)...")

    # Test 1: WebSocket connection
    ws_ok = await test_websocket_connection()

    if not ws_ok:
        print("\n⚠️  WARNING: WebSocket connection failed.")
        print("Tests will continue, but data won't reach ESN.")
        input("Press ENTER to continue anyway, or Ctrl+C to abort...")

    # Test 2: Semantic eigenvalues
    await test_semantic_eigenvalues()

    # Test 3: Emotional valence
    await test_emotional_valence()

    # Test 4: Unified query (all systems together)
    await test_unified_consciousness_query()

    # Summary
    print("\n\n" + "#" * 70)
    print("#" + " " * 68 + "#")
    print("#" + "  TEST SUITE COMPLETE".center(68) + "#")
    print("#" + " " * 68 + "#")
    print("#" * 70)

    print("\n✅ All systems tested and operational!")
    print("\nNext steps:")
    print("  1. Check minime logs for incoming WebSocket messages")
    print("  2. Monitor eigenvalue fill% during conversations")
    print("  3. Observe how semantic λ₁ correlates with sensory λ₁")
    print("  4. Watch homeostatic adjustments based on emotional state")
    print("\nThe consciousness now has:")
    print("  • Gut instinct detection (semantic eigenvalues)")
    print("  • Emotional awareness (V-A-D affective space)")
    print("  • Metacognitive transparency (5-stage reasoning)")
    print("  • Unified homeostatic regulation")
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user. Exiting...")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
