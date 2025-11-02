#!/usr/bin/env python3
import sys
import time

# Write message to stdout which will be piped to minime.py
message = "Mike says hello and we hope you're more comfortable!"
print(message)
sys.stdout.flush()

# Keep the pipe open briefly
time.sleep(0.1)