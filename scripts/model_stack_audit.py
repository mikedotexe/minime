#!/usr/bin/env python3
"""Run the shared Astrid/Minime model-stack audit from the Minime repo."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


AUDIT_SCRIPT = Path(__file__).resolve().parents[2] / "astrid/scripts/model_stack_audit.py"

if not AUDIT_SCRIPT.exists():
    sys.exit(f"Missing shared audit script: {AUDIT_SCRIPT}")

sys.argv[0] = str(AUDIT_SCRIPT)
runpy.run_path(str(AUDIT_SCRIPT), run_name="__main__")
