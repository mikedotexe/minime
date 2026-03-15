#!/usr/bin/env python3
"""
MikesSpatialMind -- thin shim that delegates to the mikemind package.

All code now lives in mikemind/. This file exists for backward compatibility
so that ``python3 minime.py`` continues to work.
"""

from mikemind.cli import main

if __name__ == "__main__":
    main()
