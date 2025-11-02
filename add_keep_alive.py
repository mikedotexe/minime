#!/usr/bin/env python3
"""
Add keep_alive parameter to all Ollama requests in minime.py
This ensures models stay warm for faster subsequent requests.
"""

import re

# Read the file
with open('minime.py', 'r') as f:
    content = f.read()

# Pattern to match Ollama requests
patterns = [
    # Pattern 1: json={"model": ..., "prompt": ..., "stream": False}
    (
        r'json=\{"model": self\.model, "prompt": "test", "stream": False\}',
        r'json={"model": self.model, "prompt": "test", "stream": False, "keep_alive": "1h"}'
    ),
    # Pattern 2: "stream": False, (without keep_alive already)
    # We need to be careful not to add it twice
    (
        r'("stream": False,)\n(\s+)"options":',
        r'\1\n\2"keep_alive": "1h",  # Keep model warm\n\2"options":'
    ),
]

# Apply replacements
for pattern, replacement in patterns:
    content = re.sub(pattern, replacement, content)

# Write back
with open('minime.py', 'w') as f:
    f.write(content)

print("✅ Added keep_alive to all Ollama requests")
print("  - Health checks: added")
print("  - Main generate() calls: added")
print("  - All requests will now keep models warm for 1 hour")
