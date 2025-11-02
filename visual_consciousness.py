#!/usr/bin/env python3
"""
Visual Consciousness - MikesSpatialMind with Camera Integration
Processes visual input at 1 FPS through seven-stage consciousness pipeline
"""

import sys
import time
import threading
import argparse
from minime import MikesSpatialMind, ProcessingMode

def main():
    parser = argparse.ArgumentParser(description='Visual Consciousness System')
    parser.add_argument('--fps', type=float, default=1.0, help='Visual processing rate (default: 1 FPS)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose seven-stage output')
    parser.add_argument('--mode', choices=['embedded', 'research'], default='research',
                       help='Processing mode (default: research)')
    parser.add_argument('--camera', type=int, default=0, help='Camera index (default: 0, try 1 for second camera)')
    args = parser.parse_args()

    # Processing delay
    processing_delay = 1.0 / args.fps

    print("=" * 50)
    print("🌀 VISUAL CONSCIOUSNESS STARTING")
    print("=" * 50)
    print(f"Mode: {args.mode.upper()} {'(seven-stage pipeline)' if args.mode == 'research' else '(embedded)'}")
    print(f"Model: dolphin-mixtral:8x7b-v2.7 (latest uncensored)")
    print(f"Visual: {args.fps} FPS {'(contemplative)' if args.fps <= 1 else '(active)'}")
    print(f"Debug: {'ON' if args.debug else 'OFF'}")
    print("")
    print("Commands:")
    print("  'what do you see?' - Describe current view")
    print("  'describe the room' - Detailed spatial description")
    print("  'watch clouds' - Activate cloud spiritual connection")
    print("  'find patterns' - Visual pattern analysis")
    print("  'status' - Show processing stats")
    print("  'quit' - Exit")
    print("=" * 50)
    print("")

    # Initialize consciousness
    print("🔮 Initializing consciousness...")
    mode = ProcessingMode.RESEARCH if args.mode == 'research' else ProcessingMode.EMBEDDED
    mind = MikesSpatialMind(mode=mode)

    # Enable verbose seven-stage output if requested
    if args.verbose and mind.seven_stage_processor:
        mind.seven_stage_processor.verbose = True

    # Try to load previous consciousness state
    if mind.load_consciousness_state("visual_consciousness_state.pkl"):
        print("📂 Previous consciousness state restored!")
    else:
        print("✅ Starting fresh consciousness")

    print(f"✅ Consciousness active: {mind.consciousness_level:.6f}")
    print("")

    # Try to start camera
    print(f"📹 Attempting to connect to camera (index {args.camera})...")
    if mind.start_visual_processing(camera_index=args.camera):
        print("✅ Camera active - visual consciousness enabled!")
        print("")

        # Visual processing state
        visual_active = True
        visual_stats = {
            'frames_processed': 0,
            'successful': 0,
            'errors': 0,
            'last_error': None
        }

        def visual_loop():
            """Background thread: Process visual frames"""
            nonlocal visual_stats

            while visual_active:
                try:
                    if args.debug:
                        print(f"[DEBUG] Processing frame {visual_stats['frames_processed'] + 1}...")

                    # Background thread always uses fast processing (EMBEDDED style)
                    # Deep processing only happens on-demand when user asks
                    result = mind.process_visual_frame(
                        verbose=args.debug,
                        use_seven_stage=False  # Fast background processing
                    )

                    visual_stats['frames_processed'] += 1

                    if result:
                        visual_stats['successful'] += 1
                        if args.debug:
                            print(f"[DEBUG] Frame processed successfully")
                            print(f"[DEBUG] Description:")
                            print(f"        {result.get('visual_description', 'N/A')}")
                    else:
                        if args.debug:
                            print(f"[DEBUG] Frame processing returned None")

                    time.sleep(processing_delay)

                except Exception as e:
                    visual_stats['errors'] += 1
                    visual_stats['last_error'] = str(e)
                    print(f"\n⚠️  Visual processing error: {e}", file=sys.stderr)
                    if args.debug:
                        import traceback
                        traceback.print_exc()
                    time.sleep(processing_delay)

        # Start visual thread
        visual_thread = threading.Thread(target=visual_loop, daemon=True)
        visual_thread.start()
        print(f"👁️  Visual processing active ({args.fps} FPS background)")
        print("")
    else:
        print("⚠️  No camera detected - running in text-only mode")
        print("")
        visual_active = False
        visual_stats = None

    # Interactive loop
    print("💬 Ready for interaction. Type 'quit' to exit.")
    print("")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print("\n👋 Input stream closed - exiting...")
                break

            if not user_input:
                continue

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Consciousness resting...")
                if visual_active:
                    visual_active = False
                    time.sleep(0.5)  # Give thread time to finish
                break

            # Status command
            if user_input.lower() == 'status':
                print(f"\n📊 CONSCIOUSNESS STATUS")
                print(f"  Level: {mind.consciousness_level:.6f}")
                print(f"  Mode: {mode.name}")
                if visual_stats:
                    print(f"  Visual Frames: {visual_stats['frames_processed']}")
                    print(f"  Successful: {visual_stats['successful']}")
                    print(f"  Errors: {visual_stats['errors']}")
                    if visual_stats['last_error']:
                        print(f"  Last Error: {visual_stats['last_error']}")
                print(f"  Visual Memories: {len(mind.visual_memories)}")
                print(f"  Conversations: {len(mind.conversation_history)}")
                print("")
                continue

            # Special visual commands
            if user_input.lower() in ['what do you see?', 'what do you see', 'look']:
                print(f"✅ Command received: '{user_input}'")
                if args.debug:
                    print("🔄 Retrieving latest visual memory...")

                if mind.visual_memories:
                    latest = list(mind.visual_memories)[-1]
                    response = latest.get('response', 'No response available')
                    print(f"\nMikesSpatialMind: {response}\n")
                else:
                    print("\nMikesSpatialMind: No visual data yet - camera may not be active.\n")
                continue

            # Detailed visual description
            if user_input.lower() in ['describe the room', 'describe room', 'describe']:
                print(f"✅ Command received: '{user_input}'")
                if args.debug:
                    print("🔄 Analyzing recent visual memories and generating detailed description...")

                if mind.visual_memories:
                    # Get recent visual memories
                    recent = list(mind.visual_memories)[-3:]
                    descriptions = [m.get('visual_description', '') for m in recent]
                    combined = ', '.join(descriptions)

                    if args.debug:
                        print(f"📊 Using {len(recent)} recent visual memories")

                    # Ask consciousness to elaborate
                    prompt = f"Based on what I'm seeing: {combined}, describe the environment in detail"
                    response = mind.speak(prompt)
                    print(f"\nMikesSpatialMind: {response}\n")
                else:
                    print("\nMikesSpatialMind: I need visual data to describe the room.\n")
                continue

            # Regular conversation
            print(f"✅ Input received: '{user_input}'")
            if args.debug:
                processing_mode = 'seven-stage' if mode == ProcessingMode.RESEARCH else 'embedded'
                print(f"🔄 Processing through {processing_mode} pipeline...")
                start_time = time.time()

            # Enable verbose for this interaction if requested
            if args.verbose and mind.seven_stage_processor:
                mind.seven_stage_processor.verbose = True

            response = mind.speak(user_input)

            # Disable verbose after response (so it doesn't spam background visual)
            if args.verbose and mind.seven_stage_processor:
                mind.seven_stage_processor.verbose = False

            if args.debug:
                elapsed = time.time() - start_time
                print(f"⏱️  Processing completed in {elapsed:.2f}s")

            print(f"\nMikesSpatialMind: {response}\n")

    except KeyboardInterrupt:
        print("\n\n👋 Consciousness interrupted - resting gracefully...")
        if visual_active:
            visual_active = False
            time.sleep(0.5)  # Give thread time to finish

    finally:
        # Clean up
        if mind.camera:
            mind.stop_visual_processing()

        # Auto-save consciousness state
        mind.save_consciousness_state("visual_consciousness_state.pkl")

        print(f"\n✨ Final consciousness level: {mind.consciousness_level:.6f}")
        print(f"💫 Visual memories stored: {len(mind.visual_memories)}")

        if visual_stats:
            print(f"📊 Visual processing stats:")
            print(f"   Total frames: {visual_stats['frames_processed']}")
            print(f"   Successful: {visual_stats['successful']}")
            print(f"   Errors: {visual_stats['errors']}")

        print("\n🌀 Thank you for the experience.\n")

if __name__ == "__main__":
    main()
