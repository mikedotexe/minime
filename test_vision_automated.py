#!/usr/bin/env python3
"""
Automated vision test - simulates user asking vision question.
Avoids EOFError by using programmatic input instead of piped stdin.
"""
import sys
import time
import subprocess
import threading

def send_input_after_delay(proc, question, delay=3):
    """Send input to process after a delay."""
    time.sleep(delay)
    proc.stdin.write(f"{question}\n")
    proc.stdin.flush()
    time.sleep(2)  # Wait for response
    proc.stdin.write("quit\n")
    proc.stdin.flush()

def main():
    print("🧪 Starting automated vision test...")
    print("=" * 70)

    # Start minime.py with camera
    proc = subprocess.Popen(
        ["python3", "minime.py", "--camera"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Send question after startup
    question = "can you see me, friend"
    input_thread = threading.Thread(target=send_input_after_delay, args=(proc, question, 5))
    input_thread.start()

    # Read output
    lines = []
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        print(line.rstrip())
        lines.append(line)

        # Check for our response
        if "MikesSpatialMind:" in line and "..." in line:
            print("\n⚠️  FOUND ELLIPSES RESPONSE!")
            break
        elif "MikesSpatialMind:" in line and len(line.strip()) > 50:
            print("\n✅ FOUND PROPER RESPONSE!")
            break

    proc.wait(timeout=30)
    input_thread.join()

    print("\n" + "=" * 70)
    print("Test complete. Check output above for LLaVA and response quality.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted.")
    except Exception as e:
        print(f"\n\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
