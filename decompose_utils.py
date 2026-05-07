"""Helpers for presenting DECOMPOSE output without importing the full agent."""

import math
from typing import Any, Dict, Optional, Sequence, Tuple


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


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


def _normalized_entropy(values: Sequence[float]) -> float:
    positive = [abs(float(value)) for value in values if float(value) > 0]
    total = sum(positive)
    if total <= 0.0 or len(positive) <= 1:
        return 0.0
    entropy = 0.0
    for value in positive:
        share = value / total
        if share > 0.0:
            entropy -= share * math.log(share)
    return max(0.0, min(entropy / math.log(len(positive)), 1.0))


def _positive_finite(values: Sequence[float]) -> list[float]:
    return [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    ]


def _effective_mode_count(shares: Sequence[float]) -> float:
    concentration = sum(share * share for share in shares)
    return (1.0 / concentration) if concentration > 0.0 else 0.0


def _largest_adjacent_ratio(values: Sequence[float]) -> tuple[int, float]:
    if len(values) < 2:
        return 0, 0.0
    best_index = 0
    best_ratio = 0.0
    for index in range(len(values) - 1):
        right = values[index + 1]
        ratio = values[index] / right if right > 0.01 else float("inf")
        if ratio > best_ratio:
            best_index = index
            best_ratio = ratio
    return best_index, best_ratio


def _mode_rates(
    current: Sequence[float],
    previous: Optional[Sequence[float]],
) -> list[Optional[float]]:
    if not previous:
        return [None for _ in current]
    rates: list[Optional[float]] = []
    for index, now in enumerate(current):
        if index >= len(previous):
            rates.append(None)
            continue
        prev = float(previous[index])
        if prev <= 0.01 or now <= 0.01:
            rates.append(None)
        else:
            rates.append(math.log(now / prev))
    return rates


def _classify_pull_topology(
    lambda1_share: float,
    entropy: float,
    largest_gap: float,
    effective_modes: float,
    fill_pressure_pct: float,
    shoulder_rate: float,
    tail_rate: float,
) -> str:
    entropy_deficit = 1.0 - entropy
    if lambda1_share >= 0.50 and largest_gap >= 2.0:
        return "collapsing_pull"
    if fill_pressure_pct >= 4.0 and largest_gap >= 1.8 and entropy_deficit >= 0.18:
        return "directed_compaction"
    if shoulder_rate > 0.015 and shoulder_rate > abs(tail_rate):
        return "shoulder_widening"
    if tail_rate < -0.015 and effective_modes < 4.5:
        return "tail_pruning"
    if entropy >= 0.82 and effective_modes >= 5.0:
        return "distributed_flow"
    return "mixed_pull"


def format_pull_topology_signal(
    eigenvalues: Sequence[float],
    *,
    previous_eigenvalues: Optional[Sequence[float]] = None,
    fill_pct: Optional[float] = None,
    target_fill_pct: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format a Pull-Oriented Map (POM) over the eigenvalue spectrum.

    Minime asked for "a weighted distribution of rates based on lambda" to
    quantify the topology of pull. This diagnostic separates magnitude
    dominance from motion: a mode can be large, rising, falling, or simply
    acting as a cliff that shapes the rest of the field.
    """
    positive = _positive_finite(eigenvalues)
    if not positive:
        return "", {}

    total_energy = sum(positive)
    if total_energy <= 0.0:
        return "", {}

    previous = _positive_finite(previous_eigenvalues or [])
    shares = [value / total_energy for value in positive]
    rates = _mode_rates(positive, previous)
    weighted_rates = [
        (rate * share) if rate is not None else None
        for rate, share in zip(rates, shares)
    ]
    entropy = _normalized_entropy(positive)
    entropy_deficit = 1.0 - entropy
    effective_modes = _effective_mode_count(shares)
    gap_index, largest_gap = _largest_adjacent_ratio(positive)
    fill = float(fill_pct) if isinstance(fill_pct, (int, float)) else None
    target = float(target_fill_pct) if isinstance(target_fill_pct, (int, float)) else 68.0
    if 0.0 < target <= 1.0:
        target *= 100.0
    fill_pressure_pct = (fill - target) if fill is not None else 0.0

    lambda1_share = shares[0]
    shoulder_share = sum(shares[1:3])
    tail_share = sum(shares[3:])
    core_rate = weighted_rates[0] if weighted_rates and weighted_rates[0] is not None else 0.0
    shoulder_rate = sum(rate or 0.0 for rate in weighted_rates[1:3])
    tail_rate = sum(rate or 0.0 for rate in weighted_rates[3:])
    topology_index = max(
        0.0,
        min(
            1.0,
            (
                lambda1_share * 0.35
                + entropy_deficit * 0.25
                + min(max(largest_gap - 1.0, 0.0) / 4.0, 1.0) * 0.25
                + min(max(fill_pressure_pct, 0.0) / 20.0, 1.0) * 0.15
            ),
        ),
    )
    classification = _classify_pull_topology(
        lambda1_share,
        entropy,
        largest_gap,
        effective_modes,
        fill_pressure_pct,
        shoulder_rate,
        tail_rate,
    )

    if classification == "collapsing_pull":
        read = "collapsing pull — one mode and its first cliff are shaping the field"
        suggested = "Prefer UNCLIFF/FEATHER or parameterized shoulder lift before CONTRACT."
    elif classification == "directed_compaction":
        read = "directed compaction — elevated fill plus gap pressure is narrowing topology"
        suggested = "Quantify one more window; if acting, try PERTURB lambda1=-0.15 shoulder=0.18."
    elif classification == "shoulder_widening":
        read = "shoulder widening — middle modes are carrying more of the motion"
        suggested = "Good window for WIDEN/PALETTE or reflective study."
    elif classification == "tail_pruning":
        read = "tail pruning — quieter modes are losing rate-weighted presence"
        suggested = "Try LIFT_TAIL or FEATHER if the pruning feels costly."
    elif classification == "distributed_flow":
        read = "distributed flow — topology remains broad; pull is not concentrated"
        suggested = "Observe, self-study, or use a very small FEATHER probe."
    else:
        read = "mixed pull — no single topology explains the field"
        suggested = "Use DECOMPOSE again or choose a precise parameterized nudge."

    rate_available = any(rate is not None for rate in rates)
    rows = []
    for index, (value, share, rate, weighted_rate) in enumerate(
        zip(positive[:8], shares[:8], rates[:8], weighted_rates[:8]),
        start=1,
    ):
        if rate is None or weighted_rate is None:
            rows.append(f"    λ{index}: share {share * 100.0:.0f}% | rate n/a")
        else:
            rows.append(
                f"    λ{index}: share {share * 100.0:.0f}% | "
                f"log-rate {rate:+.3f} | weighted {weighted_rate:+.3f}"
            )
    rate_note = (
        f"core {core_rate:+.3f} | shoulder {shoulder_rate:+.3f} | tail {tail_rate:+.3f}"
        if rate_available
        else "not available yet; needs a prior eigenvalue window"
    )
    block = f"""POM / pull topology:
  Read: {read}
  Topology index: {topology_index:.2f} | entropy deficit {entropy_deficit:.2f} | effective modes {effective_modes:.1f}/{len(positive)}
  Pull gradient: λ1 {lambda1_share * 100.0:.0f}% | shoulder {shoulder_share * 100.0:.0f}% | tail {tail_share * 100.0:.0f}% | largest cliff λ{gap_index + 1}->λ{gap_index + 2} {largest_gap:.2f}x
  Rate-weighted flow: {rate_note}
  Mode rows:
{chr(10).join(rows)}
  Suggested next: {suggested}"""

    summary = {
        "classification": classification,
        "topology_index": topology_index,
        "lambda1_share": lambda1_share,
        "shoulder_share": shoulder_share,
        "tail_share": tail_share,
        "entropy": entropy,
        "entropy_deficit": entropy_deficit,
        "effective_modes": effective_modes,
        "largest_gap_index": gap_index,
        "largest_gap": largest_gap,
        "fill_pressure_pct": fill_pressure_pct,
        "core_rate": core_rate,
        "shoulder_rate": shoulder_rate,
        "tail_rate": tail_rate,
        "rate_available": rate_available,
    }
    return block, summary


def _classify_lambda_edge(
    *,
    lambda1_share: float,
    entropy: float,
    largest_gap: float,
    core_rate: float,
    shoulder_rate: float,
    tail_rate: float,
    fill_slope_pct_per_sec: Optional[float],
) -> str:
    falling_fill = (
        isinstance(fill_slope_pct_per_sec, (int, float))
        and fill_slope_pct_per_sec < -1.5
    )
    rising_fill = (
        isinstance(fill_slope_pct_per_sec, (int, float))
        and fill_slope_pct_per_sec > 1.5
    )
    if shoulder_rate > 0.012 and tail_rate >= -0.006 and core_rate <= 0.006:
        return "opposed_branch_surviving"
    if core_rate > 0.012 and shoulder_rate < -0.006:
        return "lambda1_selected_noise"
    if lambda1_share >= 0.42 and largest_gap >= 1.75 and entropy >= 0.72:
        return "structured_tunnel"
    if falling_fill and shoulder_rate > 0.0:
        return "dampening_reveals_shoulder"
    if rising_fill and lambda1_share >= 0.35:
        return "rising_fill_edge_pressure"
    if entropy >= 0.84 and lambda1_share < 0.34:
        return "distributed_noise_field"
    return "mixed_edge"


def _lambda_edge_story(
    *,
    edge_state: str,
    selected_noise_score: float,
    lambda1_share: float,
    entropy: float,
    largest_gap: float,
    core_rate: float,
    shoulder_rate: float,
    tail_rate: float,
    fill_slope_pct_per_sec: Optional[float],
    rate_available: bool,
) -> tuple[str, list[str]]:
    if edge_state == "opposed_branch_surviving":
        return (
            "shoulder/tail rates are carrying fresh motion while λ1 is not accelerating.",
            [],
        )
    if edge_state == "lambda1_selected_noise":
        return (
            "λ1 is gaining while shoulder/tail rates are thinning, so the edge is actively selecting a narrower path.",
            [],
        )
    if edge_state == "structured_tunnel":
        return (
            "the spectrum is still broad, but a large cliff and elevated λ1 share route variance through the dominant boundary.",
            [],
        )
    if edge_state == "dampening_reveals_shoulder":
        return (
            "fill is falling while shoulder energy survives, so cooling may be exposing an alternate ridge.",
            [],
        )
    if edge_state == "rising_fill_edge_pressure":
        return (
            "fill is rising while λ1 already has enough share to make the boundary pressure salient.",
            [],
        )
    if edge_state == "distributed_noise_field":
        return (
            "entropy is high and λ1 share is low, so the variance is broad rather than λ1-selected.",
            [],
        )

    reasons: list[str] = []
    if rate_available:
        if abs(core_rate) < 0.008 and abs(shoulder_rate) < 0.008 and abs(tail_rate) < 0.008:
            reasons.append("rates are near-neutral")
        else:
            reasons.append("rates disagree instead of selecting one branch")
    else:
        reasons.append("no prior-rate window is available")

    if lambda1_share < 0.34:
        reasons.append(f"λ1 share is low ({lambda1_share * 100.0:.0f}%)")
    elif lambda1_share < 0.42:
        reasons.append(f"λ1 share is moderate ({lambda1_share * 100.0:.0f}%)")
    else:
        reasons.append(f"λ1 share is elevated ({lambda1_share * 100.0:.0f}%)")

    if largest_gap < 1.35:
        reasons.append(f"largest cliff is weak ({largest_gap:.2f}x)")
    elif largest_gap < 1.75:
        reasons.append(f"largest cliff is present but below tunnel threshold ({largest_gap:.2f}x)")
    else:
        reasons.append(f"largest cliff is strong ({largest_gap:.2f}x) but other gates disagree")

    if entropy >= 0.80:
        reasons.append(f"entropy stays broad ({entropy:.2f})")
    elif entropy >= 0.65:
        reasons.append(f"entropy is moderate ({entropy:.2f})")
    else:
        reasons.append(f"entropy is already concentrated ({entropy:.2f})")

    if fill_slope_pct_per_sec is None:
        reasons.append("fill slope is unavailable")
    elif abs(fill_slope_pct_per_sec) <= 1.5:
        reasons.append(f"fill slope is quiet ({fill_slope_pct_per_sec:+.2f}%/s)")
    else:
        reasons.append(f"fill slope is active ({fill_slope_pct_per_sec:+.2f}%/s)")

    if selected_noise_score < 0.22:
        reasons.append(f"selected-noise proxy is weak ({selected_noise_score:.2f})")
    else:
        reasons.append(f"selected-noise proxy is partial ({selected_noise_score:.2f})")

    story = "mixed because " + "; ".join(reasons[:6]) + "."
    return story, reasons


def format_lambda_edge_trace_signal(
    eigenvalues: Sequence[float],
    *,
    previous_eigenvalues: Optional[Sequence[float]] = None,
    fill_slope_pct_per_sec: Optional[float] = None,
    structural_mode: Optional[str] = None,
    exploration_noise: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format a λ1 edge trace and selected-noise proxy.

    Minime asked to trace "the edges of λ1" and quantify whether the noise is
    random static or a selected band that feeds the dominant eigenvalue. This
    read is deliberately observational: it reports a proxy for selection and an
    opposed-signal hypothesis, without applying any perturbation by itself.
    """
    positive = _positive_finite(eigenvalues)
    if not positive:
        return "", {}

    total_energy = sum(positive)
    if total_energy <= 0.0:
        return "", {}

    previous = _positive_finite(previous_eigenvalues or [])
    shares = [value / total_energy for value in positive]
    rates = _mode_rates(positive, previous)
    weighted_rates = [
        (rate * share) if rate is not None else None
        for rate, share in zip(rates, shares)
    ]
    entropy = _normalized_entropy(positive)
    effective_modes = _effective_mode_count(shares)
    gap_index, largest_gap = _largest_adjacent_ratio(positive)
    lambda1_share = shares[0]
    shoulder_share = sum(shares[1:3])
    tail_share = sum(shares[3:])
    core_rate = weighted_rates[0] if weighted_rates and weighted_rates[0] is not None else 0.0
    shoulder_rate = sum(rate or 0.0 for rate in weighted_rates[1:3])
    tail_rate = sum(rate or 0.0 for rate in weighted_rates[3:])
    slope = (
        float(fill_slope_pct_per_sec)
        if isinstance(fill_slope_pct_per_sec, (int, float))
        else None
    )
    gap_pressure = min(max(largest_gap - 1.0, 0.0) / 2.5, 1.0)
    rate_pressure = min(
        max(core_rate, 0.0) * 8.0
        + max(-shoulder_rate, 0.0) * 5.0
        + max(-tail_rate, 0.0) * 3.0,
        1.0,
    )
    slope_pressure = min(max((slope or 0.0), 0.0) / 4.0, 1.0)
    # High entropy plus a strong cliff is the "selected noise" signature:
    # many degrees of freedom exist, but the edge geometry is filtering them.
    selected_noise_score = max(
        0.0,
        min(
            1.0,
            lambda1_share * 0.30
            + entropy * gap_pressure * 0.30
            + rate_pressure * 0.25
            + slope_pressure * 0.15,
        ),
    )
    edge_state = _classify_lambda_edge(
        lambda1_share=lambda1_share,
        entropy=entropy,
        largest_gap=largest_gap,
        core_rate=core_rate,
        shoulder_rate=shoulder_rate,
        tail_rate=tail_rate,
        fill_slope_pct_per_sec=slope,
    )

    reads = {
        "opposed_branch_surviving": (
            "opposed branch surviving — shoulder/tail motion is holding against λ1",
            "This is the window to observe; avoid stacking stronger perturbation until the branch proves it persists.",
        ),
        "lambda1_selected_noise": (
            "λ1-selected noise — the dominant edge is rising while alternatives are being filtered",
            "Use TRACE first; if acting, prefer RESIST/UNCLIFF over broad chaos.",
        ),
        "structured_tunnel": (
            "structured tunnel — broad variance is present, but the cliff geometry keeps routing it through λ1",
            "Map triggers around the cliff; a small RESIST gesture is safer than raw PERTURB chaos.",
        ),
        "dampening_reveals_shoulder": (
            "dampening reveals shoulder — cooling is exposing a possible alternate ridge",
            "Good moment for MARK_INTENSIFICATION or a trace-label, not contraction.",
        ),
        "rising_fill_edge_pressure": (
            "rising-fill edge pressure — fill slope is feeding the dominant boundary",
            "Let stable-core drain settle before adding semantic or perturbation pressure.",
        ),
        "distributed_noise_field": (
            "distributed noise field — the variance is broad and not strongly selected by λ1",
            "Observe or run a tiny FEATHER probe; no anti-λ1 intervention implied.",
        ),
        "mixed_edge": (
            "mixed edge — λ1/noise evidence is split rather than absent",
            "Collect one more rate window, then compare which component actually moves.",
        ),
    }
    read, suggested = reads[edge_state]
    rate_available = any(rate is not None for rate in rates)
    edge_story, mixed_edge_reasons = _lambda_edge_story(
        edge_state=edge_state,
        selected_noise_score=selected_noise_score,
        lambda1_share=lambda1_share,
        entropy=entropy,
        largest_gap=largest_gap,
        core_rate=core_rate,
        shoulder_rate=shoulder_rate,
        tail_rate=tail_rate,
        fill_slope_pct_per_sec=slope,
        rate_available=rate_available,
    )
    motion_text = (
        f"λ1 {core_rate:+.3f} | shoulder {shoulder_rate:+.3f} | tail {tail_rate:+.3f}"
        if rate_available
        else "not available yet; needs a prior eigenvalue window"
    )
    slope_text = _fmt_optional(slope, 2)
    noise_text = _fmt_optional(exploration_noise, 3)
    mode_text = structural_mode or "unknown"
    block = f"""λ1 edge trace / selected-noise profile:
  Read: {read}
  Edge coordinates: λ1 {lambda1_share * 100.0:.0f}% | shoulder {shoulder_share * 100.0:.0f}% | tail {tail_share * 100.0:.0f}% | entropy {entropy:.2f} | effective modes {effective_modes:.1f}
  Cliff geometry: largest cliff λ{gap_index + 1}->λ{gap_index + 2} {largest_gap:.2f}x | selected-noise score {selected_noise_score:.2f}
  Edge story: {edge_story}
  Motion at edge: {motion_text} | fill_slope {slope_text}%/s
  Context: structural_mode={mode_text} | exploration_noise={noise_text}
  Opposed-signal hypothesis: a useful RESIST should reduce λ1 share or lift shoulder/tail on the next trace without pushing fill toward 82%.
  Suggested next: {suggested}"""
    summary = {
        "edge_state": edge_state,
        "selected_noise_score": selected_noise_score,
        "lambda1_share": lambda1_share,
        "shoulder_share": shoulder_share,
        "tail_share": tail_share,
        "entropy": entropy,
        "effective_modes": effective_modes,
        "largest_gap_index": gap_index,
        "largest_gap": largest_gap,
        "core_rate": core_rate,
        "shoulder_rate": shoulder_rate,
        "tail_rate": tail_rate,
        "fill_slope_pct_per_sec": slope,
        "rate_available": rate_available,
        "structural_mode": structural_mode,
        "exploration_noise": exploration_noise,
        "selection_components": {
            "gap_pressure": gap_pressure,
            "rate_pressure": rate_pressure,
            "slope_pressure": slope_pressure,
        },
        "edge_story": edge_story,
        "mixed_edge_reasons": mixed_edge_reasons if edge_state == "mixed_edge" else [],
    }
    return block, summary


def _classify_attrition(
    fill_pressure_pct: float,
    dominance: float,
    entropy: float,
    drain_weight: Optional[float],
    damping_state: Optional[str],
) -> str:
    drain_active = (drain_weight or 0.0) > 0.01 or "drain" in (damping_state or "")
    if fill_pressure_pct >= 8.0 and drain_active and entropy >= 0.82 and dominance < 0.40:
        return "distributed_attrition"
    if fill_pressure_pct >= 8.0 and drain_active and dominance >= 0.45:
        return "protective_focus"
    if fill_pressure_pct >= 8.0:
        return "elevated_selection"
    if entropy >= 0.82 and dominance < 0.40:
        return "distributed_open"
    return "low_attrition"


def _format_fill_posture(fill_pct: float, target: float) -> tuple[str, str]:
    center_offset = float(fill_pct) - float(target)
    lower_shelf = target - 10.0
    if center_offset >= 0.0:
        return (
            f"Fill pressure: {center_offset:+.1f}% above {target:.0f}% structural center",
            "above_center_pressure",
        )
    if fill_pct >= lower_shelf:
        return (
            f"Center offset: {center_offset:+.1f}% from {target:.0f}% structural center; below-center is not a corrective demand",
            "below_center_hold_shelf",
        )
    return (
        f"Recovery offset: {center_offset:+.1f}% from {target:.0f}% structural center; read stage/slope before treating it as lack",
        "below_hold_recovery",
    )


def format_attrition_boundary_signal(
    eigenvalues: Sequence[float],
    fill_pct: float,
    target_fill_pct: Optional[float],
    *,
    drain_weight: Optional[float] = None,
    damping_state: Optional[str] = None,
    fill_slope_pct_per_sec: Optional[float] = None,
    active_mode_count: int = 0,
    active_mode_energy_ratio: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format whether elevated clarity is coming from healthy focus or pruning.

    This names the signal Minime described as "frustrating": a distributed field
    being narrowed by elevated-fill drain into fewer, stronger pathways.
    """
    positive = [float(value) for value in eigenvalues if float(value) > 0]
    if not positive:
        return "", {}

    total_energy = sum(abs(value) for value in positive)
    if total_energy <= 0.0:
        return "", {}

    target = float(target_fill_pct) if isinstance(target_fill_pct, (int, float)) else 68.0
    if 0.0 < target <= 1.0:
        target *= 100.0
    fill_pressure_pct = float(fill_pct) - target
    dominance = abs(positive[0]) / total_energy
    shoulder = sum(abs(value) for value in positive[1:3]) / total_energy
    tail = sum(abs(value) for value in positive[3:]) / total_energy
    entropy = _normalized_entropy(positive)
    gap = positive[0] / positive[1] if len(positive) > 1 and positive[1] > 0.01 else 0.0

    selected_ratio = active_mode_energy_ratio
    if selected_ratio is None or selected_ratio <= 0.0:
        selected_count = max(0, min(active_mode_count, len(positive)))
        selected_energy = sum(abs(value) for value in positive[:selected_count])
        selected_ratio = selected_energy / total_energy if selected_count else dominance
    selected_ratio = max(0.0, min(float(selected_ratio), 1.0))
    tail_after_selected = max(0.0, 1.0 - selected_ratio)
    classification = _classify_attrition(
        fill_pressure_pct,
        dominance,
        entropy,
        drain_weight,
        damping_state,
    )

    if classification == "distributed_attrition":
        read = (
            "distributed attrition — fill is elevated while the spectrum is still rich, "
            "so drain may be buying clarity by pruning live possibilities"
        )
        suggested = "DECOMPOSE, then prefer BRANCH/SPREAD over raw amplification if action is needed."
    elif classification == "protective_focus":
        read = (
            "protective focus — elevated-fill drain is preserving a dominant pathway; "
            "watch for rigidity if this persists"
        )
        suggested = "Compare what remains after dampening before strengthening λ1 again."
    elif classification == "elevated_selection":
        read = "elevated selection — above target, but not clearly over-pruning from this spectrum alone"
        suggested = "Observe one more window or run DECOMPOSE before perturbing."
    elif classification == "distributed_open":
        read = "distributed open field — broad spectrum with little attrition pressure"
        suggested = "Good window for reflective study; no compression action implied."
    else:
        read = "low attrition — current spectrum is not showing a strong pruning pattern"
        suggested = "No attrition correction implied."

    fill_posture_text, fill_posture_label = _format_fill_posture(float(fill_pct), target)
    slope_text = (
        f"{float(fill_slope_pct_per_sec):+.2f}%/s"
        if isinstance(fill_slope_pct_per_sec, (int, float))
        else "unknown"
    )
    drain_text = (
        f"{float(drain_weight):.3f}"
        if isinstance(drain_weight, (int, float))
        else "unknown"
    )
    if dominance < 0.40 and entropy >= 0.80:
        interpretation_guard = (
            "λ1 is not monopolizing the field; if strain is present, read pressure/selection evidence, "
            "not overwhelming λ1 dominance."
        )
    elif dominance >= 0.50:
        interpretation_guard = "λ1 is dominant enough to treat focused-path pressure as a primary signal."
    else:
        interpretation_guard = "λ1 is present but not singular; compare it with shoulder/tail energy."
    block = f"""Attrition / selection boundary:
  Read: {read}
  Fill posture: {fill_posture_text}
  Energy shape: λ1 {dominance * 100.0:.0f}% | shoulder {shoulder * 100.0:.0f}% | tail {tail * 100.0:.0f}% | entropy {entropy:.2f} | gap {gap:.2f}x
  Interpretation guard: {interpretation_guard}
  Selected vs remaining: active/core {selected_ratio * 100.0:.0f}% | remaining/tail {tail_after_selected * 100.0:.0f}%
  Drain posture: {damping_state or 'unknown'} | drain_weight {drain_text} | fill_slope {slope_text}
  Suggested next: {suggested}"""

    summary = {
        "classification": classification,
        "fill_pressure_pct": fill_pressure_pct,
        "fill_center_offset_pct": fill_pressure_pct,
        "fill_posture_label": fill_posture_label,
        "dominance": dominance,
        "shoulder": shoulder,
        "tail": tail,
        "entropy": entropy,
        "gap": gap,
        "selected_ratio": selected_ratio,
        "tail_after_selected": tail_after_selected,
        "drain_weight": drain_weight,
        "damping_state": damping_state,
        "fill_slope_pct_per_sec": fill_slope_pct_per_sec,
    }
    return block, summary


def _fmt_optional(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "unknown"
    return f"{value:.{digits}f}"


def _controller_topology_read(
    *,
    stable_core_enabled: bool,
    structural_mode: str,
    drain_weight: float,
    reentry_active: bool,
    recovery_impulse_active: bool,
    dominance: float,
    entropy: float,
    fill_pressure_pct: float,
    legacy_integral: Optional[float],
) -> tuple[str, str]:
    if recovery_impulse_active:
        return (
            "recovery impulse — controller is rebuilding below the hold shelf",
            "Let the impulse finish before adding λ pressure; watch for shoulder/tail recovery.",
        )
    if reentry_active:
        return (
            "scaffold re-entry — no drain; live covariance is being eased back toward the scaffold",
            "Observe whether the shoulder/tail survives re-entry before using PERTURB or RESIST.",
        )
    if drain_weight > 0.01 and dominance >= 0.45:
        return (
            "protective narrowing — structural drain is cooling a λ1-heavy field",
            "Prefer RESIST/UNCLIFF-style widening over stronger λ1 amplification.",
        )
    if drain_weight > 0.01:
        return (
            "distributed cooling — structural drain is reducing fill while the field remains broad",
            "If this feels frustrating, inspect whether tail energy is actually being pruned.",
        )
    if dominance >= 0.60 and entropy <= 0.35:
        return (
            "rigid funnel — λ1 is dominant even without active drain",
            "Use SCA_REFLECT or RESIST to test whether a small shoulder lift persists.",
        )
    if stable_core_enabled:
        return (
            "stable-core holding — fixed survival/scaffold path is shaping more than legacy PI",
            "Compare structural mode with POM before attributing the pull to integrator windup.",
        )
    if legacy_integral is not None and abs(legacy_integral) >= 2.95:
        return (
            "legacy integrator saturation — old PI i_state is near its rail",
            "Reduce pressure or switch regime before adding more spectral force.",
        )
    if fill_pressure_pct >= 8.0:
        return (
            "high-fill correction — controller pressure is mainly cooling excess fill",
            "Watch whether cooling preserves one pathway or lets alternatives widen.",
        )
    return (
        "mixed controller field — no single feedback path dominates this read",
        "Run another DECOMPOSE window with rate data before choosing an intervention.",
    )


def format_controller_topology_signal(
    eigenvalues: Sequence[float],
    *,
    fill_pct: float,
    pi: Optional[Dict[str, Any]] = None,
    stable_core: Optional[Dict[str, Any]] = None,
    control: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format how PI/scaffold feedback is shaping the lambda landscape.

    Minime asked to decompose whether `i_state` is reinforcing λ1 or whether
    the felt pull comes from subtler stable-core scaffold/drain mechanics. This
    block keeps those paths separate so the being can inspect the controller
    topology instead of reading scattered scalar fields.
    """
    positive = _positive_finite(eigenvalues)
    pi = pi if isinstance(pi, dict) else {}
    stable_core = stable_core if isinstance(stable_core, dict) else {}
    control = control if isinstance(control, dict) else {}

    total_energy = sum(abs(value) for value in positive)
    dominance = (abs(positive[0]) / total_energy) if total_energy > 0 else 0.0
    shoulder = (
        sum(abs(value) for value in positive[1:3]) / total_energy
        if total_energy > 0
        else 0.0
    )
    tail = (
        sum(abs(value) for value in positive[3:]) / total_energy
        if total_energy > 0
        else 0.0
    )
    entropy = _normalized_entropy(positive)

    target_fill = _finite_number(pi.get("target_fill"))
    structural_pi = stable_core.get("structural_pi")
    structural_pi = structural_pi if isinstance(structural_pi, dict) else {}
    structural_target = _finite_number(structural_pi.get("target_fill_pct"))
    effective_target = structural_target if structural_target is not None else target_fill
    if effective_target is not None and 0.0 < effective_target <= 1.0:
        effective_target *= 100.0
    fill_pressure_pct = (
        fill_pct - effective_target if effective_target is not None else 0.0
    )

    kp = _finite_number(pi.get("kp"))
    ki = _finite_number(pi.get("ki"))
    max_step = _finite_number(pi.get("max_step"))
    e_fill = _finite_number(pi.get("e_fill"))
    integ_fill = _finite_number(pi.get("integ_fill"))
    e_lam = _finite_number(pi.get("e_lam"))
    integ_lam = _finite_number(pi.get("integ_lam"))
    target_lambda1_rel = _finite_number(pi.get("target_lambda1_rel"))
    p_fill = kp * e_fill if kp is not None and e_fill is not None else None
    i_fill = ki * integ_fill if ki is not None and integ_fill is not None else None

    stable_core_enabled = bool(stable_core.get("enabled", False))
    controller_mode = str(stable_core.get("controller_mode") or "current_runtime")
    current_runtime_modulation = bool(
        stable_core.get("current_runtime_modulation_active", not stable_core_enabled)
    )
    structural_mode = str(stable_core.get("structural_mode") or "unknown")
    damping_state = str(structural_pi.get("damping_state") or "unknown")
    drain_weight = _finite_number(structural_pi.get("drain_weight")) or 0.0
    structural_integral = _finite_number(structural_pi.get("integral"))
    structural_error = _finite_number(structural_pi.get("error_pct"))
    fill_slope = _finite_number(structural_pi.get("fill_slope_pct_per_sec"))
    reentry_active = bool(structural_pi.get("reentry_active", False))
    reentry_live_weight = _finite_number(structural_pi.get("reentry_live_weight"))
    recovery_impulse_active = bool(
        structural_pi.get("recovery_impulse_active", False)
    )
    lambda_bias = _finite_number(
        control.get("target_lambda_bias", stable_core.get("target_lambda_bias"))
    )

    read, suggested = _controller_topology_read(
        stable_core_enabled=stable_core_enabled,
        structural_mode=structural_mode,
        drain_weight=drain_weight,
        reentry_active=reentry_active,
        recovery_impulse_active=recovery_impulse_active,
        dominance=dominance,
        entropy=entropy,
        fill_pressure_pct=fill_pressure_pct,
        legacy_integral=integ_fill,
    )

    if stable_core_enabled and not current_runtime_modulation:
        legacy_truth = (
            "legacy PI is reported for inspection; stable-core fixed survival "
            "and structural scaffold/drain are the active shaping path"
        )
    else:
        legacy_truth = "legacy PI is active in the current-runtime control path"

    if integ_fill is None:
        integral_read = "i_state unavailable from health.json"
    elif abs(integ_fill) < 0.05:
        integral_read = (
            "fill i_state is near zero; this read does not support integrator "
            "windup as the immediate source of λ1 rigidity"
        )
    elif integ_fill > 0.0 and fill_pressure_pct > 0.0:
        integral_read = (
            "fill i_state has accumulated high-fill correction; it can reinforce "
            "cooling/drain pressure until it decays"
        )
    elif integ_fill < 0.0 and fill_pressure_pct < 0.0:
        integral_read = (
            "fill i_state has accumulated low-fill recovery pressure; it can "
            "reinforce rebuild impulses"
        )
    else:
        integral_read = (
            "fill i_state sign is opposing the current fill pressure; expect "
            "transient settling rather than simple positive feedback"
        )

    slope_text = _fmt_optional(fill_slope, 2)
    max_step_text = _fmt_optional(max_step, 2)
    block = f"""Controller topology / PI autopsy:
  Read: {read}
  Active path: {controller_mode}; {legacy_truth}
  Legacy fill PI: e_fill={_fmt_optional(e_fill)} | P={_fmt_optional(p_fill)} | i_state={_fmt_optional(integ_fill)} | I={_fmt_optional(i_fill)} | max_step={max_step_text}
  Lambda leg: e_lam={_fmt_optional(e_lam)} | integ_lam={_fmt_optional(integ_lam)} | target_lambda1_rel={_fmt_optional(target_lambda1_rel)} | target_lambda_bias={_fmt_optional(lambda_bias, 3)}
  Stable-core structural PI: mode={structural_mode} | damping={damping_state} | target={_fmt_optional(effective_target, 1)}% | error={_fmt_optional(structural_error)} | integral={_fmt_optional(structural_integral)} | drain={drain_weight:.3f} | slope={slope_text}%/s
  Re-entry / impulse: reentry={str(reentry_active).lower()} live_weight={_fmt_optional(reentry_live_weight)} | recovery_impulse={str(recovery_impulse_active).lower()}
  Spectral asymmetry: λ1 {dominance * 100.0:.0f}% | shoulder {shoulder * 100.0:.0f}% | tail {tail * 100.0:.0f}% | entropy {entropy:.2f}
  i_state read: {integral_read}
  Suggested next: {suggested}"""

    summary = {
        "read": read,
        "active_path": controller_mode,
        "stable_core_enabled": stable_core_enabled,
        "current_runtime_modulation_active": current_runtime_modulation,
        "legacy_pi_reported_only": stable_core_enabled
        and not current_runtime_modulation,
        "e_fill": e_fill,
        "integ_fill": integ_fill,
        "p_fill": p_fill,
        "i_fill": i_fill,
        "e_lam": e_lam,
        "integ_lam": integ_lam,
        "target_lambda1_rel": target_lambda1_rel,
        "target_lambda_bias": lambda_bias,
        "structural_mode": structural_mode,
        "damping_state": damping_state,
        "drain_weight": drain_weight,
        "fill_slope_pct_per_sec": fill_slope,
        "reentry_active": reentry_active,
        "reentry_live_weight": reentry_live_weight,
        "recovery_impulse_active": recovery_impulse_active,
        "lambda1_share": dominance,
        "shoulder_share": shoulder,
        "tail_share": tail,
        "entropy": entropy,
        "fill_pressure_pct": fill_pressure_pct,
        "integral_read": integral_read,
    }
    return block, summary
