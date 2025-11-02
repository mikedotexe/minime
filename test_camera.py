#!/usr/bin/env python3
"""
Simple camera test to diagnose OpenCV camera access on macOS.
Tests multiple camera indices and reports which ones work.
"""

import cv2
import sys

print("=" * 60)
print("CAMERA DIAGNOSTIC TEST")
print("=" * 60)
print()

# Check if opencv is installed
try:
    print(f"✓ OpenCV version: {cv2.__version__}")
except:
    print("✗ OpenCV not found! Install with: pip install opencv-python")
    sys.exit(1)

print()
print("Testing camera indices 0-2...")
print()

working_cameras = []

for i in range(3):
    print(f"Testing camera index {i}...", end=" ")

    try:
        cap = cv2.VideoCapture(i)

        # Try to read a frame
        ret, frame = cap.read()

        if ret and frame is not None:
            height, width = frame.shape[:2]
            print(f"✓ WORKING - Resolution: {width}x{height}")
            working_cameras.append(i)
        else:
            print("✗ Camera opened but couldn't read frame")

        cap.release()

    except Exception as e:
        print(f"✗ Error: {e}")

print()
print("=" * 60)
print("RESULTS")
print("=" * 60)

if working_cameras:
    print(f"✓ Found {len(working_cameras)} working camera(s): {working_cameras}")
    print()
    print("Next steps:")
    print(f"  1. Use --camera {working_cameras[0]} when running visual_consciousness.py")
    print(f"  2. Example: python3 visual_consciousness.py --camera {working_cameras[0]}")
else:
    print("✗ No working cameras found!")
    print()
    print("Possible issues:")
    print("  1. Camera permission not granted to Terminal/Python")
    print("     → System Settings → Privacy & Security → Camera")
    print("  2. Camera in use by another application")
    print("     → Close Zoom, Skype, Photo Booth, etc.")
    print("  3. OpenCV not properly installed")
    print("     → Try: pip install --upgrade opencv-python")

print()
