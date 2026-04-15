"""Helpers for presenting DECOMPOSE output without importing the full agent."""

from typing import Optional, Sequence, Tuple


def _format_eigenvalue_line(index: int, value: float, total_energy: float) -> str:
    pct = (abs(value) / total_energy * 100.0) if total_energy > 0 else 0.0
    return f"  λ{index + 1} = {value:.2f} ({pct:.0f}% of energy)"


def _mode_range_label(active_mode_count: int) -> str:
    if active_mode_count <= 1:
        return "λ1"
    return f"λ1-λ{active_mode_count}"


def format_decompose_mode_sections(
    eigenvalues: Sequence[float],
    active_mode_count: int,
    active_mode_energy_ratio: Optional[float] = None,
) -> Tuple[str, str, str]:
    """Return formatted active/tail mode blocks for DECOMPOSE output."""
    positive = [float(value) for value in eigenvalues if value > 0]
    if not positive:
        return "", "", ""

    total_energy = sum(abs(value) for value in positive)
    active_count = max(0, min(active_mode_count, len(positive)))

    if active_count == 0:
        return (
            "\n".join(
                _format_eigenvalue_line(index, value, total_energy)
                for index, value in enumerate(positive)
            ),
            "",
            "",
        )

    active_block = "\n".join(
        _format_eigenvalue_line(index, value, total_energy)
        for index, value in enumerate(positive[:active_count])
    )
    tail_block = "\n".join(
        _format_eigenvalue_line(index + active_count, value, total_energy)
        for index, value in enumerate(positive[active_count:])
    )
    if active_mode_energy_ratio is None or active_mode_energy_ratio <= 0.0:
        selected_energy = sum(abs(value) for value in positive[:active_count])
        ratio = (selected_energy / total_energy) if total_energy > 0 else 0.0
    else:
        ratio = max(0.0, min(float(active_mode_energy_ratio), 1.0))

    summary = (
        f"  Active modes: {_mode_range_label(active_count)} carry "
        f"{ratio * 100.0:.0f}% of positive spectral energy."
    )
    return active_block, tail_block, summary
