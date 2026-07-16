#!/usr/bin/env python3
"""Import and CLI facade for :mod:`minime_autonomy.runtime`.

On import, this name resolves to the runtime module itself so existing tests
and integrations that monkeypatch ``autonomous_agent`` continue to affect the
globals used by its classes and functions.
"""

from __future__ import annotations

import sys

from minime_autonomy import runtime as _runtime

if __name__ == "__main__":
    raise SystemExit(_runtime.main())

# Preserve the historical public module identity for callers that locate the
# repository root through ``autonomous_agent.__file__``. Runtime source
# monitoring uses an explicit canonical implementation path instead.
_runtime.__file__ = __file__
sys.modules[__name__] = _runtime
