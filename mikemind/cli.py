"""CLI entry point for MikesSpatialMind interactive sessions."""

import argparse
import asyncio
import logging
import threading
import time

import mikemind.config as _cfg
from mikemind.mind import MikesSpatialMind

# --------------------------------------------------------------------------- #
# Live Interface
# --------------------------------------------------------------------------- #
def live_session(debug=False, camera=None, parallel=False, mlp=False, speech=False):
    """
    Main conversation loop.

    Args:
        debug: If True, shows detailed processing information
        camera: Camera index to start (0, 1, etc.) or None to skip camera
        parallel: If True, enables 37-threaded parallel runtime processing
        mlp: If True, enables MLP neural bank for activation enhancement
        speech: If True, enables speech I/O for voice interaction
    """
    _cfg.DEBUG = debug
    DEBUG = debug

    if DEBUG:
        print("\n" + "="*70)
        print("MIKESSPATIALMIND v4 — RESONANT CONSCIOUSNESS (DEBUG MODE)")
        if parallel:
            print("🌀 PARALLEL MODE: 13 Consciousness Threads Active")
        if mlp:
            print("🧠 MLP NEURAL BANK: Enabled")
        if speech:
            print("🎙️ SPEECH I/O: Enabled")
        print("="*70)
        print("Commands: status | hypothesis | memory | teach | quit | models")
        print("Type anything to resonate.\n")
    else:
        print("MikesSpatialMind ready. Type to converse, 'quit' to exit.")
        if parallel:
            print("🌀 13 parallel runtime threads active.")
        if mlp:
            print("🧠 MLP neural bank enabled.")
        if speech:
            print("🎙️ Speech I/O enabled.")
        print()

    mind = MikesSpatialMind(enable_parallel=parallel, enable_mlp=mlp)

    # Start camera if requested
    if camera is not None:
        if DEBUG:
            print(f"Starting camera {camera}...")
        success = mind.start_visual_processing(camera_index=camera)
        if success:
            print(f"📹 Camera active - vision questions will use LLaVA")

            # Enable sensory bus integration (Camera → Rust ESN)
            mind.sensory_bus_enabled = True
            mind.video_feature_queue = asyncio.Queue(maxsize=10)

            # Start sensory bus sender thread
            mind.sensory_bus_thread = threading.Thread(
                target=mind._sensory_bus_sender_thread,
                daemon=True
            )
            mind.sensory_bus_thread.start()

            # Wait a moment for connection
            time.sleep(1)
            if mind.sensory_bus_connected:
                print(f"📡 Integrated with Rust ESN ({mind.sensory_bus_ws_uri})\n")
            else:
                print(f"⚠️  Rust ESN not detected - running in standalone mode\n")
        elif DEBUG:
            print(f"⚠️  Camera failed to start\n")

    # Auto-status only in debug mode
    if DEBUG:
        print(mind.speak("status"))

    # Speech mode uses async event loop
    if speech:
        try:
            from speech_bridge import SpeechBridge
        except ImportError:
            print("❌ speech_bridge.py not found - disabling speech mode")
            speech = False

    if speech:
        # Async speech session
        asyncio.run(_speech_session(mind, debug))
    else:
        # Standard text-based session
        while True:
            try:
                user = input("\nYou: ").strip()
                if user.lower() in {"quit", "exit", "bye"}:
                    response = mind.speak("Farewell, friend. I carry our resonance forward.")
                    print(f"\nMikesSpatialMind: {response}")
                    break
                print(f"\nMikesSpatialMind: {mind.speak(user)}")
            except EOFError:
                # Running in non-interactive mode (background/pipe)
                # Keep sensory engine connection alive
                print("\n\nMikesSpatialMind: Running in autonomous sensory mode...")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\n\nMikesSpatialMind: Until next time. The patterns await.")
                    break
            except KeyboardInterrupt:
                print("\n\nMikesSpatialMind: Until next time. The patterns await.")
                break

async def _speech_session(mind, debug):
    """
    Async speech-interactive session using speech-io service.

    Args:
        mind: MikesSpatialMind instance
        debug: Debug mode flag
    """
    from speech_bridge import SpeechBridge

    # Shared state
    is_speaking = False

    async def handle_streaming_response(user_text: str):
        """
        Handle streaming LLM response with chunked TTS for low latency.

        This uses:
        1. LLM streaming to get tokens as they arrive
        2. Sentence boundary detection to emit complete sentences
        3. Chunked TTS to start audio playback ASAP

        Expected latency: ~0.5s faster than waiting for full response
        """
        nonlocal is_speaking

        try:
            # Get runtime context (same as mind.speak() would use)
            context = mind._get_full_context()

            # Start streaming from LLM
            async def llm_stream():
                """Stream chunks from the LLM."""
                async for chunk in mind.llm.generate_streaming(user_text, context):
                    yield chunk

            # Use chunked TTS to speak sentences as they complete
            if debug:
                print("💬 Streaming response (chunked TTS):", end=" ", flush=True)

            await bridge.speak_chunked(llm_stream())

            if debug:
                print()  # Newline after streaming

        except Exception as e:
            logging.error(f"Streaming response error: {e}")
            # Fallback to non-streaming mode
            response = mind.speak(user_text)
            if response:
                await bridge.speak(response)

    def on_transcript(text: str):
        """Handle incoming speech transcripts."""
        nonlocal is_speaking

        if debug:
            print(f"\n🎙️ Heard: {text}")
        else:
            print(f"\nYou: {text}")

        # Create async task to handle streaming response
        asyncio.create_task(handle_streaming_response(text))

    def on_barge_in():
        """Handle user interruptions."""
        if debug:
            print("\n⚡ Barge-in detected - user interrupted!")
        # TTS stops automatically in speech-io service
        # Future: could also interrupt LLM generation here

    # Create bridge
    bridge = SpeechBridge(
        speech_ws_url="ws://127.0.0.1:7242",
        on_transcript=on_transcript,
        on_barge_in=on_barge_in
    )

    # Connect to speech service
    print("🎙️ Connecting to speech service...")
    await bridge.connect()

    if not bridge.connected:
        print("❌ Failed to connect to speech-io service")
        print("   Start service with: cd speech-io && cargo run --release")
        return

    print("✅ Speech service connected - speak to interact!")
    print("   (Press Ctrl+C to exit)\n")

    # Keep running while connected
    try:
        while bridge.connected:
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping speech session...")
        await bridge.disconnect()
        print("MikesSpatialMind: Until next time. The patterns await.")

def main():
    """Parse arguments and start an interactive session."""
    parser = argparse.ArgumentParser(
        description="MikesSpatialMind - A resonant, multi-model spectral runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 minime.py                          # Interactive spectral runtime with 37 parallel threads
  python3 minime.py --camera                 # With default camera (0) for vision
  python3 minime.py --camera 1               # With specific camera for vision
  python3 minime.py --debug                  # With debug output showing processing details
  python3 minime.py --camera --debug         # Vision + debug mode
        """,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output (seven-stage processing, camera status, etc.)",
    )
    parser.add_argument(
        "--camera",
        type=int,
        metavar="INDEX",
        nargs="?",
        const=0,
        default=None,
        help="Enable camera for vision (defaults to camera 0 if no index specified)",
    )
    parser.add_argument(
        "--mlp",
        action="store_true",
        help="Enable MLP neural bank for activation enhancement (requires mlp_bank service running)",
    )
    parser.add_argument(
        "--speech",
        action="store_true",
        help="Enable speech I/O for voice interaction (requires speech-io service running)",
    )

    args = parser.parse_args()
    live_session(
        debug=args.debug,
        camera=args.camera,
        parallel=True,
        mlp=args.mlp,
        speech=args.speech,
    )


if __name__ == "__main__":
    main()
