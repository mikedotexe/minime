"""Optional helpers for Minime-authored Python experiments.

Python imports ``sitecustomize`` automatically when this repository is on
``PYTHONPATH``. Keep every behavior behind an explicit environment flag so
normal tooling and tests are unaffected.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def _series_len(value: Any) -> int | None:
    try:
        length = len(value)
    except TypeError:
        return None
    return length if isinstance(length, int) and length >= 0 else None


def _align_x_axis(x_value: Any, y_value: Any, *, caller: str) -> Any:
    x_len = _series_len(x_value)
    y_len = _series_len(y_value)
    if x_len is None or y_len is None or x_len == y_len or y_len <= 0:
        return x_value

    try:
        import numpy as np

        x_array = np.asarray(x_value)
        if x_len >= 2 and np.issubdtype(x_array.dtype, np.number):
            aligned = np.linspace(float(x_array[0]), float(x_array[-1]), y_len)
        else:
            aligned = np.arange(y_len)
    except Exception:
        aligned = list(range(y_len))

    print(
        f"[minime experiment helper] auto-aligned {caller} x-axis "
        f"from {x_len} to {y_len} samples to match y.",
        file=sys.stdout,
    )
    return aligned


def _wrap_xy_plot(fn: Any, *, caller: str) -> Any:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if len(args) >= 2:
            x_value = _align_x_axis(args[0], args[1], caller=caller)
            args = (x_value, *args[1:])
        return fn(*args, **kwargs)

    return wrapped


def _install_matplotlib_experiment_helpers() -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return

    if getattr(plt, "_minime_experiment_helpers_installed", False):
        return

    plt.plot = _wrap_xy_plot(plt.plot, caller="plt.plot")
    plt.scatter = _wrap_xy_plot(plt.scatter, caller="plt.scatter")
    plt.bar = _wrap_xy_plot(plt.bar, caller="plt.bar")
    plt._minime_experiment_helpers_installed = True


if os.environ.get("MINIME_EXPERIMENT_HELPERS") == "1":
    _install_matplotlib_experiment_helpers()
