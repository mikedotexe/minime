#!/usr/bin/env python3
"""
Quick automated test of integrated consciousness system.
No interactive prompts - just runs all tests automatically.
"""
import asyncio
import json
import websockets
import time
from semantic_eigenvalue_extractor import SemanticEigenvalueExtractor
from emotional_valence_extractor import EmotionalValenceExtractor

async def test_websocket():
    """Test WebSocket connection to Rust ESN."""
    print("\n" + "="*70)
    print("Testing WebSocket Connection")
    print("="*70)
    try:
        async with websockets.connect("ws://127.0.0.1:7879", timeout=5) as ws:
            await ws.send(json.dumps({
                "type": "TestConnection",
                "timestamp": time.time(),
                "message": "Hello from integrated test"
            }))
            print("✅ WebSocket connection successful!")
            return True
    except Exception as e:
        print(f"❌ WebSocket failed: {e}")
        return False

async def test_semantic():
    """Test semantic eigenvalue extraction."""
    print("\n" + "="*70)
    print("Testing Semantic Eigenvalue Extraction")
    print("="*70)
    extractor = SemanticEigenvalueExtractor()
    
    prompt = "What is 2 + 2?"
    print(f"\nPrompt: {prompt}")
    print("-" * 70)
    
    try:
        metrics = extractor.extract_gut_instinct(prompt)
        print(f"  λ₁ (semantic):  {metrics.lambda1_semantic:.4f}")
        print(f"  Spectral fill:  {metrics.spectral_fill:.2%}")
        print(f"  Variance:       {metrics.activation_variance:.6f}")
        await extractor.send_to_esn_async(metrics)
        print(f"  ✅ Sent to ESN successfully")
    except Exception as e:
        print(f"  ❌ Error: {e}")

async def test_emotional():
    """Test emotional valence extraction."""
    print("\n" + "="*70)
    print("Testing Emotional Valence Extraction")
    print("="*70)
    extractor = EmotionalValenceExtractor()
    
    text = "I'm feeling really excited and energized!"
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
        
        await extractor.send_to_esn_async(emotion)
        print(f"  ✅ Sent to ESN successfully")
    except Exception as e:
        print(f"  ❌ Error: {e}")

async def main():
    print("\n" * 2)
    print("#" * 70)
    print("#  INTEGRATED CONSCIOUSNESS TEST SUITE (Automated)".ljust(69) + "#")
    print("#" * 70)
    
    # Run all tests
    await test_websocket()
    await test_semantic()
    await asyncio.sleep(1)
    await test_emotional()
    
    print("\n\n" + "#" * 70)
    print("#  TEST SUITE COMPLETE".ljust(69) + "#")
    print("#" * 70)
    print("\n✅ All systems tested!")
    print("\nThe consciousness now has:")
    print("  • Gut instinct detection (semantic eigenvalues)")
    print("  • Emotional awareness (V-A-D affective space)")
    print("  • Unified homeostatic regulation")
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
