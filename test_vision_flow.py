#!/usr/bin/env python3
"""
Test if visual data is actually flowing to the consciousness model.
Run this while minime.py is running with camera enabled.
"""

import sys

print("Vision Data Flow Test")
print("=" * 60)
print("\nThis test will check if camera data is reaching the consciousness.")
print("\nMake sure you're running: python3 minime.py --camera")
print("\nTry these test prompts:")
print()
print("1. Ask a NON-vision question first:")
print("   'Hello, how are you feeling today?'")
print("   → Check if the response mentions anything visual")
print()
print("2. Then ask a vision question:")
print("   'What do you see right now?'")
print("   → This should trigger LLaVA analysis")
print()
print("3. Follow up with another non-vision question:")
print("   'Tell me about consciousness'")
print("   → See if visual context persists")
print()
print("Key things to observe:")
print("- Does the model mention seeing anything without being asked?")
print("- Is visual context only available for vision-specific questions?")
print("- Do the 37 parallel threads have access to visual data?")
print()
print("If visual data only appears when asking vision questions,")
print("then the camera feed is NOT being continuously processed by")
print("the consciousness - it's only analyzed on-demand.")