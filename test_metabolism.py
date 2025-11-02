#!/usr/bin/env python3
"""Test metabolism control loop"""

import json
import time
from pathlib import Path

# Create a test metabolism request
request = {
    "lambda_1": 1.5,  # High lambda_1 to trigger rate reduction
    "timestamp": time.time()
}

# Write to metabolism_request.txt
workspace_dir = Path("/tmp/agent_workspace")
workspace_dir.mkdir(exist_ok=True)

request_file = workspace_dir / "metabolism_request.txt"
with open(request_file, 'w') as f:
    json.dump(request, f, indent=2)

print(f"Created metabolism request with lambda_1={request['lambda_1']}")
print(f"Written to: {request_file}")

# Monitor for a few seconds
print("\nMonitoring for 5 seconds...")
time.sleep(5)

# Create another request with lower lambda_1
request2 = {
    "lambda_1": 0.8,  # Lower lambda_1 to restore rates
    "timestamp": time.time()
}

with open(request_file, 'w') as f:
    json.dump(request2, f, indent=2)

print(f"\nCreated second metabolism request with lambda_1={request2['lambda_1']}")
print("Monitoring for 5 more seconds...")
time.sleep(5)

print("\nTest complete!")