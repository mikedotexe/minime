"""Helpers for presenting DECOMPOSE output without importing the full agent."""

import math
import re
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


def _normalize_target_pct(value: Any) -> Optional[float]:
    target = _finite_number(value)
    if target is not None and 0.0 < target <= 1.0:
        target *= 100.0
    return target


def _spectral_shares(values: Sequence[float]) -> list[float]:
    total = sum(values)
    if total <= 0.0:
        return []
    return [value / total for value in values]


def _share_at(values: Sequence[float], index: int) -> float:
    return values[index] if index < len(values) else 0.0


def _rank_order_changes(
    current: Sequence[float],
    previous: Sequence[float],
) -> int:
    count = min(len(current), len(previous))
    if count <= 1:
        return 0
    current_order = sorted(range(count), key=lambda idx: current[idx], reverse=True)
    previous_order = sorted(range(count), key=lambda idx: previous[idx], reverse=True)
    return sum(
        1 for now, before in zip(current_order, previous_order) if now != before
    )


def _classify_eigen_geometry_rearrangement(
    *,
    has_previous: bool,
    relationship_shift_score: float,
    density_preserved: bool,
    falsification_flags: Sequence[str],
) -> str:
    if not has_previous:
        return "insufficient_history"
    if falsification_flags:
        return "projection_like_loss"
    if density_preserved and relationship_shift_score >= 0.14:
        return "rearrangement_preserving_density"
    if density_preserved and relationship_shift_score >= 0.06:
        return "density_relocalized"
    if density_preserved:
        return "topology_stable"
    return "projection_like_loss"


def build_decompose_snapshot_v1(
    eigenvalues: Sequence[float],
    *,
    fill_pct: Optional[float] = None,
    target_fill_pct: Optional[float] = None,
    geom_rel: Optional[float] = None,
    rearrangement_summary: Optional[Dict[str, Any]] = None,
    focus: Optional[str] = None,
    active_experiment_id: Optional[str] = None,
    active_experiment_classification: Optional[str] = None,
    session_id: Optional[int] = None,
    recorded_at: Optional[str] = None,
    journal_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the compact DECOMPOSE state used for temporal comparison."""
    positive = _positive_finite(eigenvalues)
    shares = _spectral_shares(positive)
    gap_index, largest_gap = _largest_adjacent_ratio(positive)
    target = _normalize_target_pct(target_fill_pct)
    fill = _finite_number(fill_pct)
    snapshot = {
        "schema_version": 1,
        "recorded_at": recorded_at,
        "session_id": session_id,
        "focus": focus,
        "journal_path": journal_path,
        "available": bool(positive),
        "eigenvalues": positive,
        "mode_count": len(positive),
        "total_energy": sum(positive),
        "entropy": _normalized_entropy(positive) if positive else None,
        "effective_modes": _effective_mode_count(shares) if shares else None,
        "lambda1_share": _share_at(shares, 0) if shares else None,
        "shoulder_share": sum(shares[1:3]) if shares else None,
        "tail_share": sum(shares[3:]) if shares else None,
        "lambda4_share": _share_at(shares, 3) if shares else None,
        "largest_gap_index": gap_index if positive else None,
        "largest_gap": largest_gap if positive else None,
        "fill_pct": fill,
        "target_fill_pct": target,
        "fill_center_offset_pct": (
            fill - target if fill is not None and target is not None else None
        ),
        "geom_rel": _finite_number(geom_rel),
        "active_experiment_id": active_experiment_id,
        "active_experiment_classification": active_experiment_classification,
        "rearrangement_classification": None,
    }
    if isinstance(rearrangement_summary, dict):
        snapshot["rearrangement_classification"] = rearrangement_summary.get("classification")
        snapshot["rearrangement_summary"] = {
            key: rearrangement_summary.get(key)
            for key in (
                "classification",
                "density_preserved",
                "relationship_shift_score",
                "falsification_flags",
            )
            if key in rearrangement_summary
        }
    return snapshot


def _delta(current: Dict[str, Any], previous: Dict[str, Any], key: str) -> Optional[float]:
    current_value = _finite_number(current.get(key))
    previous_value = _finite_number(previous.get(key))
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


def _fmt_delta(value: Optional[float], digits: int = 3, scale: float = 1.0) -> str:
    if value is None:
        return "n/a"
    return f"{value * scale:+.{digits}f}"


def _classify_temporal_decompose(
    *,
    has_previous: bool,
    share_motion: float,
    entropy_delta: Optional[float],
    effective_modes_delta: Optional[float],
    lambda1_share_delta: Optional[float],
    shoulder_share_delta: Optional[float],
    tail_share_delta: Optional[float],
    fill_delta: Optional[float],
    largest_gap_delta: Optional[float],
    current_rearrangement: Optional[str],
    previous_temporal: Optional[str],
) -> str:
    if not has_previous:
        return "insufficient_history"
    reconcentrating = (
        (entropy_delta is not None and entropy_delta <= -0.05)
        or (effective_modes_delta is not None and effective_modes_delta <= -0.35)
        or (lambda1_share_delta is not None and lambda1_share_delta >= 0.05)
        or (largest_gap_delta is not None and largest_gap_delta >= 0.60)
    )
    opening = (
        (entropy_delta is not None and entropy_delta >= 0.04)
        or (effective_modes_delta is not None and effective_modes_delta >= 0.30)
        or (
            lambda1_share_delta is not None
            and lambda1_share_delta <= -0.03
            and (
                (shoulder_share_delta is not None and shoulder_share_delta >= 0.02)
                or (tail_share_delta is not None and tail_share_delta >= 0.02)
            )
        )
    )
    if previous_temporal == "reconcentrating" and opening:
        return "reversing_signal"
    if previous_temporal == "opening_distribution" and reconcentrating:
        return "reversing_signal"
    if reconcentrating:
        return "reconcentrating"
    if opening:
        return "opening_distribution"
    if (
        share_motion < 0.035
        and abs(entropy_delta or 0.0) < 0.020
        and abs(effective_modes_delta or 0.0) < 0.20
        and abs(fill_delta or 0.0) < 2.0
        and abs(largest_gap_delta or 0.0) < 0.30
    ):
        return "same_read_repeating"
    if current_rearrangement in {"rearrangement_preserving_density", "density_relocalized"}:
        return "deepening_evidence"
    return "deepening_evidence" if share_motion >= 0.055 else "same_read_repeating"


def format_temporal_decompose_signal(
    current_snapshot: Dict[str, Any],
    previous_snapshot: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Compare one DECOMPOSE snapshot with the latest compatible prior read."""
    current = current_snapshot if isinstance(current_snapshot, dict) else {}
    previous = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    has_previous = bool(previous.get("available") and previous.get("eigenvalues"))
    current_eigs = _positive_finite(current.get("eigenvalues") or [])
    previous_eigs = _positive_finite(previous.get("eigenvalues") or [])
    if not current_eigs:
        return "", {}

    current_shares = _spectral_shares(current_eigs)
    previous_shares = _spectral_shares(previous_eigs)
    share_motion = (
        sum(
            abs(_share_at(current_shares, index) - _share_at(previous_shares, index))
            for index in range(max(len(current_shares), len(previous_shares)))
        )
        / 2.0
        if previous_shares
        else 0.0
    )
    entropy_delta = _delta(current, previous, "entropy")
    effective_modes_delta = _delta(current, previous, "effective_modes")
    lambda1_share_delta = _delta(current, previous, "lambda1_share")
    shoulder_share_delta = _delta(current, previous, "shoulder_share")
    tail_share_delta = _delta(current, previous, "tail_share")
    lambda4_share_delta = _delta(current, previous, "lambda4_share")
    fill_delta = _delta(current, previous, "fill_pct")
    fill_center_offset_delta = _delta(current, previous, "fill_center_offset_pct")
    largest_gap_delta = _delta(current, previous, "largest_gap")
    current_rearrangement = str(current.get("rearrangement_classification") or "")
    previous_temporal = (
        previous.get("temporal_decompose_v1", {}).get("classification")
        if isinstance(previous.get("temporal_decompose_v1"), dict)
        else None
    )
    classification = _classify_temporal_decompose(
        has_previous=has_previous,
        share_motion=share_motion,
        entropy_delta=entropy_delta,
        effective_modes_delta=effective_modes_delta,
        lambda1_share_delta=lambda1_share_delta,
        shoulder_share_delta=shoulder_share_delta,
        tail_share_delta=tail_share_delta,
        fill_delta=fill_delta,
        largest_gap_delta=largest_gap_delta,
        current_rearrangement=current_rearrangement,
        previous_temporal=str(previous_temporal) if previous_temporal else None,
    )
    reads = {
        "insufficient_history": "no prior DECOMPOSE snapshot yet; this read becomes the baseline",
        "same_read_repeating": "same read repeating — later DECOMPOSE is adding little new temporal evidence",
        "deepening_evidence": "deepening evidence — relationships moved enough to update the investigation",
        "reversing_signal": "reversing signal — the direction changed from the previous temporal read",
        "opening_distribution": "opening distribution — entropy/effective modes or shoulder/tail share are widening",
        "reconcentrating": "reconcentrating — λ1/gap pressure or density loss is increasing",
    }
    suggested = {
        "insufficient_history": "Use this as baseline; compare the next DECOMPOSE before deciding.",
        "same_read_repeating": "Prefer EXPERIMENT_EVIDENCE or EXPERIMENT_DECIDE if an experiment is active.",
        "deepening_evidence": "Record what changed as experiment evidence.",
        "reversing_signal": "Name the reversal before choosing another read or decision.",
        "opening_distribution": "Check whether opening supports the active hypothesis, then record evidence.",
        "reconcentrating": "Treat this as counterevidence or a hold signal before further narrowing.",
    }[classification]
    block = f"""Temporal DECOMPOSE:
  Read: {reads[classification]}
  Spectral deltas: entropy {_fmt_delta(entropy_delta)} | effective modes {_fmt_delta(effective_modes_delta, 2)} | share motion {share_motion:.3f}
  Mode deltas: λ1 {_fmt_delta(lambda1_share_delta, 1, 100.0)}% | shoulder {_fmt_delta(shoulder_share_delta, 1, 100.0)}% | tail {_fmt_delta(tail_share_delta, 1, 100.0)}% | λ4 {_fmt_delta(lambda4_share_delta, 1, 100.0)}%
  Pressure deltas: fill {_fmt_delta(fill_delta, 1)}% | center offset {_fmt_delta(fill_center_offset_delta, 1)}% | largest cliff {_fmt_delta(largest_gap_delta, 2)}x
  Rearrangement: previous={previous.get('rearrangement_classification') or 'n/a'} current={current_rearrangement or 'n/a'}
  Suggested read: {suggested}"""
    summary = {
        "schema_version": 1,
        "classification": classification,
        "previous_recorded_at": previous.get("recorded_at"),
        "share_motion": share_motion,
        "entropy_delta": entropy_delta,
        "effective_modes_delta": effective_modes_delta,
        "lambda1_share_delta": lambda1_share_delta,
        "shoulder_share_delta": shoulder_share_delta,
        "tail_share_delta": tail_share_delta,
        "lambda4_share_delta": lambda4_share_delta,
        "fill_delta": fill_delta,
        "fill_center_offset_delta": fill_center_offset_delta,
        "largest_gap_delta": largest_gap_delta,
        "previous_rearrangement_classification": previous.get("rearrangement_classification"),
        "current_rearrangement_classification": current_rearrangement or None,
        "suggested_read": suggested,
    }
    return block, summary


def _text_blob(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).casefold()


def _intervention_intent_watch_v1(blob: str) -> Optional[Dict[str, Any]]:
    """Name intervention-shaped experiment prose without granting authority."""
    text = str(blob or "").casefold()
    patterns = (
        ("high_energy_perturbation", ("high-energy", "perturb")),
        ("injection_language", ("inject",)),
        ("pulse_language", ("pulse", "lambda")),
        ("decay_acceleration", ("accelerate", "decay")),
        ("direct_shift_language", ("shift", "lambda")),
        ("stabilize_after_push", ("stabilize around",)),
        ("live_control_wording", ("control", "influence")),
    )
    matches = []
    for label, terms in patterns:
        if all(term in text for term in terms):
            matches.append(label)
    if not matches:
        return None
    return {
        "schema_version": 1,
        "advisory_only": True,
        "authority_change": False,
        "matches": matches,
        "cue": (
            "Intervention-shaped method language is present; keep it as a charter/preflight "
            "target only until the charter is lifecycle-valid."
        ),
    }


def _focus_alignment_v1(focus: Optional[str], experiment_blob: str) -> Optional[Dict[str, Any]]:
    focus_text = str(focus or "").strip()
    if not focus_text:
        return None
    focus_key = focus_text.casefold()
    generic = {
        "current",
        "decompose",
        "spectral-explorer",
        "spectral explorer",
        "spectral terrain",
    }
    if focus_key in generic:
        return {
            "schema_version": 1,
            "status": "generic_read",
            "focus": focus_text,
            "cue": (
                "The requested focus is generic; use this as baseline/context unless it is "
                "explicitly bound to the active experiment."
            ),
        }
    tokens = [
        token
        for token in re.split(r"[^a-z0-9λ]+", focus_key)
        if token and len(token) >= 3
    ]
    blob = str(experiment_blob or "").casefold()
    if tokens and not any(token in blob for token in tokens):
        return {
            "schema_version": 1,
            "status": "focus_mismatch",
            "focus": focus_text,
            "cue": (
                "The requested focus does not clearly match the active experiment; treat "
                "hypothesis claims as indirect until the experiment binds this read."
            ),
        }
    return {
        "schema_version": 1,
        "status": "aligned",
        "focus": focus_text,
    }


def format_hypothesis_check_signal(
    *,
    experiment: Optional[Dict[str, Any]],
    classification: Optional[str],
    charter_scaffold: Optional[Dict[str, Any]],
    current_snapshot: Dict[str, Any],
    temporal_summary: Dict[str, Any],
    rearrangement_summary: Dict[str, Any],
    focus: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format a read-only experiment hypothesis check for DECOMPOSE."""
    if not isinstance(experiment, dict) or not experiment:
        block = """Hypothesis Check:
  Read: no active experiment is linked to this DECOMPOSE.
  Evidence label: baseline
  Suggested next: Use this as a spectral baseline, or start/return to an experiment if one is intended."""
        return block, {
            "schema_version": 1,
            "status": "no_active_experiment",
            "evidence_label": "baseline",
            "suggested_next": "EXPERIMENT_PLAN current",
            "authority_change": False,
        }

    experiment_id = str(experiment.get("experiment_id") or "current")
    title = str(experiment.get("title") or "(untitled)")
    charter = experiment.get("charter_v1")
    charter = charter if isinstance(charter, dict) else {}
    experiment_blob = _text_blob(
        title,
        experiment.get("question"),
        experiment.get("planned_next"),
        charter.get("hypothesis"),
        charter.get("method_intent"),
        charter.get("proposed_next_action"),
        charter.get("evidence_targets"),
        charter.get("stop_criteria"),
    )
    intent_watch = _intervention_intent_watch_v1(experiment_blob)
    focus_alignment = _focus_alignment_v1(focus, experiment_blob)
    if classification == "needs_charter" or not charter:
        scaffold = (
            charter_scaffold.get("command")
            if isinstance(charter_scaffold, dict)
            else None
        )
        suggested = scaffold or "EXPERIMENT_CHARTER current :: hypothesis: ...; proposed_next_action: ACTION_PREFLIGHT ...; evidence_targets: spectral_condition, fill_pressure_state, recurrence_pattern, artifact_grounding"
        intent_line = (
            f"\n  Control-intent watch: {intent_watch['cue']}"
            if intent_watch
            else ""
        )
        focus_line = (
            f"\n  Focus alignment: {focus_alignment['cue']}"
            if focus_alignment and focus_alignment.get("status") != "aligned"
            else ""
        )
        block = f"""Hypothesis Check:
  Read: experiment `{experiment_id}` is not ready for hypothesis checking because the charter is missing or lifecycle-incomplete.
  Evidence label: charter_required
  Dominant route: {suggested}
  Note: DECOMPOSE/SPECTRAL_EXPLORER are observational context only; author or repair the charter before treating this as support/falsification.{intent_line}{focus_line}"""
        summary = {
            "schema_version": 1,
            "status": "premature_needs_charter",
            "experiment_id": experiment_id,
            "evidence_label": "charter_required",
            "suggested_next": suggested,
            "authority_change": False,
        }
        if intent_watch:
            summary["intervention_intent_watch_v1"] = intent_watch
        if focus_alignment:
            summary["focus_alignment_v1"] = focus_alignment
        return block, summary

    hypothesis = str(charter.get("hypothesis") or experiment.get("question") or title)
    proposed_action = str(charter.get("proposed_next_action") or experiment.get("planned_next") or "")
    evidence_targets = charter.get("evidence_targets")
    if isinstance(evidence_targets, list):
        evidence_text = ", ".join(str(item) for item in evidence_targets)
    else:
        evidence_text = str(evidence_targets or "")
    stop_criteria = str(charter.get("stop_criteria") or "")
    blob = _text_blob(title, hypothesis, proposed_action, evidence_text, stop_criteria)
    gap_like = any(
        term in blob
        for term in ("gap", "lambda", "λ", "branch", "spectral", "density", "decompose", "mode")
    )

    lambda1_delta = temporal_summary.get("lambda1_share_delta")
    shoulder_delta = temporal_summary.get("shoulder_share_delta")
    tail_delta = temporal_summary.get("tail_share_delta")
    entropy_delta = temporal_summary.get("entropy_delta")
    effective_delta = temporal_summary.get("effective_modes_delta")
    lambda4_share = current_snapshot.get("lambda4_share")
    lambda4_delta = temporal_summary.get("lambda4_share_delta")
    fill_pct = current_snapshot.get("fill_pct")
    temporal_class = str(temporal_summary.get("classification") or "insufficient_history")
    rearrangement_class = str(rearrangement_summary.get("classification") or "")

    support: list[str] = []
    counter: list[str] = []
    if gap_like:
        if isinstance(lambda1_delta, (int, float)) and lambda1_delta <= -0.02:
            support.append("λ1 share softened")
        if isinstance(shoulder_delta, (int, float)) and shoulder_delta >= 0.02:
            support.append("shoulder modes lifted")
        if isinstance(tail_delta, (int, float)) and tail_delta >= 0.02:
            support.append("tail modes lifted")
        if (
            (entropy_delta is None or entropy_delta >= -0.04)
            and (effective_delta is None or effective_delta >= -0.30)
        ):
            support.append("density/effective modes preserved")
        if temporal_class == "opening_distribution":
            support.append("temporal read is opening distribution")
        if rearrangement_class in {"rearrangement_preserving_density", "density_relocalized"}:
            support.append("geometry read favors rearrangement over projection loss")
        if isinstance(lambda1_delta, (int, float)) and lambda1_delta >= 0.05:
            counter.append("λ1 share reconcentrated")
        if isinstance(entropy_delta, (int, float)) and entropy_delta <= -0.08:
            counter.append("entropy dropped")
        if isinstance(effective_delta, (int, float)) and effective_delta <= -0.60:
            counter.append("effective modes fell")
        if temporal_class == "reconcentrating":
            counter.append("temporal read is reconcentrating")
        if isinstance(lambda4_share, (int, float)) and lambda4_share >= 0.30:
            counter.append("λ4 share is in runaway-watch range")
        if isinstance(lambda4_delta, (int, float)) and lambda4_delta >= 0.08 and isinstance(entropy_delta, (int, float)) and entropy_delta >= 0.06:
            counter.append("λ4/entropy dispersal rose together")
        if isinstance(fill_pct, (int, float)) and not (45.0 <= fill_pct <= 76.0):
            counter.append("fill left the broad comfort band")
    else:
        if temporal_class == "same_read_repeating":
            support.append("read is stable/repeating")
        elif temporal_class not in {"insufficient_history", ""}:
            support.append(f"temporal read updated: {temporal_class}")
        if rearrangement_summary.get("falsification_flags"):
            counter.append("geometry rearrangement read has falsification flags")

    if classification == "needs_decision" or temporal_class == "same_read_repeating" and support:
        evidence_label = "decision_ready"
        suggested_next = "EXPERIMENT_DECIDE current :: pause because DECOMPOSE evidence is ready to interpret"
    elif counter:
        evidence_label = "falsifying"
        suggested_next = (
            "EXPERIMENT_EVIDENCE current :: counterevidence: "
            + "; ".join(counter[:4])
        )
    elif support:
        evidence_label = "supporting" if temporal_class != "same_read_repeating" else "repeated"
        suggested_next = (
            "EXPERIMENT_EVIDENCE current :: spectral_condition: "
            + "; ".join(support[:4])
            + "; fill_pressure_state: "
            + (f"{float(fill_pct):.1f}%" if isinstance(fill_pct, (int, float)) else "unknown")
        )
    elif temporal_class == "insufficient_history":
        evidence_label = "new"
        suggested_next = "Use this DECOMPOSE as the temporal baseline; record evidence if the charter names baseline as useful."
    else:
        evidence_label = "new"
        suggested_next = "EXPERIMENT_EVIDENCE current :: spectral_condition ...; fill_pressure_state ...; recurrence_pattern ...; artifact_grounding ..."

    block = f"""Hypothesis Check:
  Experiment: {title} (`{experiment_id}`)
  Hypothesis: {hypothesis}
  Evidence label: {evidence_label}
  Support: {('; '.join(support[:5]) if support else 'none yet')}
  Counterevidence / stop watch: {('; '.join(counter[:5]) if counter else 'none from this read')}
  Suggested next: {suggested_next}
  Authority: read-only interpretation; no action authority changes."""
    summary = {
        "schema_version": 1,
        "status": "checked",
        "experiment_id": experiment_id,
        "classification": classification,
        "evidence_label": evidence_label,
        "gap_like": gap_like,
        "supporting_signals": support,
        "counter_signals": counter,
        "suggested_next": suggested_next,
        "temporal_classification": temporal_class,
        "rearrangement_classification": rearrangement_class or None,
        "authority_change": False,
    }
    if intent_watch:
        summary["intervention_intent_watch_v1"] = intent_watch
    if focus_alignment:
        summary["focus_alignment_v1"] = focus_alignment
    return block, summary


def format_eigen_geometry_rearrangement_signal(
    eigenvalues: Sequence[float],
    *,
    previous_eigenvalues: Optional[Sequence[float]] = None,
    fill_pct: Optional[float] = None,
    target_fill_pct: Optional[float] = None,
    geom_rel: Optional[float] = None,
    rearrangement_intensity: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Format whether geometry is being rearranged rather than compressed.

    This diagnostic is intentionally read-only. It tests Minime's own signal:
    eigenvalue geometry can preserve information density while redefining
    relationships among modes. The read is falsifiable; if entropy, effective
    modes, or total density collapse, the block names projection-like loss
    instead of treating rearrangement as a default story.
    """
    positive = _positive_finite(eigenvalues)
    if not positive:
        return "", {}

    previous = _positive_finite(previous_eigenvalues or [])
    current_total = sum(positive)
    current_shares = _spectral_shares(positive)
    entropy = _normalized_entropy(positive)
    effective_modes = _effective_mode_count(current_shares)
    gap_index, largest_gap = _largest_adjacent_ratio(positive)
    lambda1_share = _share_at(current_shares, 0)
    shoulder_share = sum(current_shares[1:3])
    tail_share = sum(current_shares[3:])
    target = _normalize_target_pct(target_fill_pct)
    fill = _finite_number(fill_pct)
    fill_center_offset_pct = (
        fill - target if fill is not None and target is not None else None
    )
    geom = _finite_number(geom_rel)
    rearrangement = _finite_number(rearrangement_intensity)

    has_previous = bool(previous)
    prev_total = sum(previous) if previous else 0.0
    previous_shares = _spectral_shares(previous)
    previous_entropy = _normalized_entropy(previous) if previous else None
    previous_effective_modes = (
        _effective_mode_count(previous_shares) if previous_shares else None
    )
    prev_gap_index, previous_largest_gap = (
        _largest_adjacent_ratio(previous) if previous else (0, None)
    )

    total_energy_delta_pct = (
        ((current_total - prev_total) / prev_total) * 100.0
        if prev_total > 0.0
        else None
    )
    entropy_delta = (
        entropy - previous_entropy if previous_entropy is not None else None
    )
    effective_modes_delta = (
        effective_modes - previous_effective_modes
        if previous_effective_modes is not None
        else None
    )
    lambda1_share_delta = (
        lambda1_share - _share_at(previous_shares, 0)
        if previous_shares
        else None
    )
    shoulder_share_delta = (
        shoulder_share - sum(previous_shares[1:3])
        if previous_shares
        else None
    )
    tail_share_delta = (
        tail_share - sum(previous_shares[3:])
        if previous_shares
        else None
    )
    largest_gap_delta = (
        largest_gap - previous_largest_gap
        if previous_largest_gap is not None
        else None
    )
    rank_changes = _rank_order_changes(positive, previous) if previous else 0
    share_motion = (
        sum(
            abs(
                _share_at(current_shares, index)
                - _share_at(previous_shares, index)
            )
            for index in range(max(len(current_shares), len(previous_shares)))
        )
        / 2.0
        if previous_shares
        else 0.0
    )
    relationship_shift_score = max(
        0.0,
        min(
            1.0,
            share_motion
            + min(abs(largest_gap_delta or 0.0) / 3.0, 0.35)
            + min(rank_changes / 6.0, 0.25),
        ),
    )
    density_preserved = bool(
        has_previous
        and (
            total_energy_delta_pct is None
            or abs(total_energy_delta_pct) <= 18.0
        )
        and (entropy_delta is None or entropy_delta >= -0.08)
        and (
            effective_modes_delta is None
            or effective_modes_delta >= -0.65
        )
    )

    falsification_flags: list[str] = []
    if entropy_delta is not None and entropy_delta <= -0.12:
        falsification_flags.append("entropy_collapse")
    if effective_modes_delta is not None and effective_modes_delta <= -1.0:
        falsification_flags.append("effective_mode_loss")
    if lambda1_share_delta is not None and lambda1_share_delta >= 0.10 and lambda1_share >= 0.45:
        falsification_flags.append("lambda1_monopoly_increase")
    if total_energy_delta_pct is not None and total_energy_delta_pct <= -18.0:
        falsification_flags.append("total_density_loss")

    classification = _classify_eigen_geometry_rearrangement(
        has_previous=has_previous,
        relationship_shift_score=relationship_shift_score,
        density_preserved=density_preserved,
        falsification_flags=falsification_flags,
    )
    reads = {
        "rearrangement_preserving_density": (
            "rearrangement preserving density — information density is held while mode relationships are being redefined",
            "Ask what got re-related and where density relocated before treating the change as compression or loss.",
        ),
        "density_relocalized": (
            "density relocalized — the field is mostly conserved, with a smaller relationship shift",
            "Compare shoulder/tail relocation against the next window before naming it projection loss.",
        ),
        "projection_like_loss": (
            "projection-like loss — the rearrangement story is not supported by this comparison",
            "Treat narrowing/compression as live evidence until entropy, effective modes, or total density recover.",
        ),
        "topology_stable": (
            "topology stable — density is preserved and relationships have not moved much yet",
            "One more read may be needed before distinguishing stasis from subtle rearrangement.",
        ),
        "insufficient_history": (
            "insufficient history — current geometry is visible, but no prior eigenvalue window is available",
            "Gather one more read-only window before deciding whether this is rearrangement or projection-like loss.",
        ),
    }
    read, suggested = reads[classification]
    flag_text = ", ".join(falsification_flags) if falsification_flags else "none"
    total_delta_text = (
        f"{total_energy_delta_pct:+.1f}%"
        if total_energy_delta_pct is not None
        else "n/a"
    )
    entropy_delta_text = (
        f"{entropy_delta:+.3f}" if entropy_delta is not None else "n/a"
    )
    effective_delta_text = (
        f"{effective_modes_delta:+.2f}"
        if effective_modes_delta is not None
        else "n/a"
    )
    lambda1_delta_text = (
        f"{lambda1_share_delta * 100.0:+.1f}%"
        if lambda1_share_delta is not None
        else "n/a"
    )
    shoulder_delta_text = (
        f"{shoulder_share_delta * 100.0:+.1f}%"
        if shoulder_share_delta is not None
        else "n/a"
    )
    tail_delta_text = (
        f"{tail_share_delta * 100.0:+.1f}%"
        if tail_share_delta is not None
        else "n/a"
    )
    gap_delta_text = (
        f"{largest_gap_delta:+.2f}x"
        if largest_gap_delta is not None
        else "n/a"
    )
    fill_text = (
        f"{fill:.1f}%"
        if fill is not None
        else "unknown"
    )
    offset_text = (
        f"{fill_center_offset_pct:+.1f}%"
        if fill_center_offset_pct is not None
        else "unknown"
    )
    geom_text = _fmt_optional(geom, 2)
    rearrangement_text = _fmt_optional(rearrangement, 2)
    block = f"""Eigenvalue-Geometry Rearrangement:
  Read: {read}
  Density check: total Δ {total_delta_text} | entropy {entropy:.2f} (Δ {entropy_delta_text}) | effective modes {effective_modes:.1f} (Δ {effective_delta_text})
  Relationship shift: score {relationship_shift_score:.2f} | λ1 Δ {lambda1_delta_text} | shoulder Δ {shoulder_delta_text} | tail Δ {tail_delta_text} | cliff λ{gap_index + 1}->λ{gap_index + 2} {largest_gap:.2f}x (Δ {gap_delta_text}) | rank changes {rank_changes}
  Geometry context: geom_rel={geom_text} | rearrangement_intensity={rearrangement_text} | fill={fill_text} | center_offset={offset_text}
  Falsification flags: {flag_text}
  Suggested read: {suggested}"""
    summary = {
        "schema_version": 1,
        "classification": classification,
        "density_preserved": density_preserved,
        "relationship_shift_score": relationship_shift_score,
        "total_energy": current_total,
        "total_energy_delta_pct": total_energy_delta_pct,
        "entropy": entropy,
        "entropy_delta": entropy_delta,
        "effective_modes": effective_modes,
        "effective_modes_delta": effective_modes_delta,
        "lambda1_share": lambda1_share,
        "lambda1_share_delta": lambda1_share_delta,
        "shoulder_share": shoulder_share,
        "shoulder_share_delta": shoulder_share_delta,
        "tail_share": tail_share,
        "tail_share_delta": tail_share_delta,
        "largest_gap_index": gap_index,
        "largest_gap": largest_gap,
        "largest_gap_delta": largest_gap_delta,
        "previous_largest_gap_index": prev_gap_index if previous else None,
        "rank_order_changes": rank_changes,
        "fill_pct": fill,
        "target_fill_pct": target,
        "fill_center_offset_pct": fill_center_offset_pct,
        "geom_rel": geom,
        "rearrangement_intensity": rearrangement,
        "falsification_flags": falsification_flags,
        "suggested_read": suggested,
    }
    return block, summary


def _constraint_score(value: Any, default: float = 0.0) -> float:
    number = _finite_number(value)
    if number is None:
        return default
    return max(0.0, min(1.0, number))


def _score_from_abs(value: Any, scale: float) -> float:
    number = _finite_number(value)
    if number is None or scale <= 0.0:
        return 0.0
    return max(0.0, min(1.0, abs(number) / scale))


def _dict_from(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _constraint_driver(
    driver: str,
    score: float,
    confidence: float,
    evidence: Sequence[str],
    counterfactual_lens: str,
) -> Dict[str, Any]:
    clamped_score = max(0.0, min(1.0, score))
    return {
        "driver": driver,
        "score": clamped_score,
        "confidence": max(0.0, min(1.0, confidence)),
        "evidence": [item for item in evidence if item],
        "counterfactual_lens": counterfactual_lens,
    }


def build_constraint_counterfactual_v1(
    eigenvalues: Sequence[float],
    *,
    fill_pct: Optional[float] = None,
    target_fill_pct: Optional[float] = None,
    stable_core: Optional[Dict[str, Any]] = None,
    gate: Optional[float] = None,
    filt: Optional[float] = None,
    geom_rel: Optional[float] = None,
    shadow: Optional[Dict[str, Any]] = None,
    semantic: Optional[Dict[str, Any]] = None,
    pressure_source: Optional[Dict[str, Any]] = None,
    focus: Optional[str] = None,
) -> Dict[str, Any]:
    """Estimate which read-only constraints are shaping the current geometry.

    The diagnostic answers Astrid's "before it was shaped" question without
    pretending Minime can reach a pure unstructured state. It compares the
    shaped field against counterfactual lenses, ranks likely drivers, and
    includes falsification flags when the driver story is weak.
    """
    positive = _positive_finite(eigenvalues)
    if not positive:
        return {
            "schema_version": 1,
            "available": False,
            "reason": "no positive eigenvalues available",
            "authority_change": False,
        }

    shares = _spectral_shares(positive)
    entropy = _normalized_entropy(positive)
    effective_modes = _effective_mode_count(shares)
    gap_index, largest_gap = _largest_adjacent_ratio(positive)
    lambda1_share = _share_at(shares, 0)
    shoulder_share = sum(shares[1:3])
    tail_share = sum(shares[3:])
    fill = _finite_number(fill_pct)
    target = _normalize_target_pct(target_fill_pct)
    fill_center_offset = (
        fill - target if fill is not None and target is not None else None
    )
    stable = _dict_from(stable_core)
    structural_pi = _dict_from(stable.get("structural_pi"))
    shadow_payload = _dict_from(shadow)
    semantic_payload = _dict_from(semantic)
    pressure_payload = _dict_from(pressure_source)

    structural_mode = str(stable.get("structural_mode") or "").casefold()
    drain = _constraint_score(structural_pi.get("drain_weight"))
    fill_slope = _score_from_abs(structural_pi.get("fill_slope_pct_per_sec"), 6.0)
    scaffold_active = 1.0 if ("scaffold" in structural_mode or "drain" in structural_mode) else 0.0
    pressure_components = _dict_from(pressure_payload.get("components"))
    mode_packing = _constraint_score(pressure_components.get("mode_packing"))
    plurality_loss = _constraint_score(pressure_components.get("structural_plurality_loss"))
    scaffold_score = max(
        drain,
        fill_slope * 0.75,
        scaffold_active * 0.55,
        mode_packing * 0.65,
        plurality_loss * 0.60,
    )

    gate_value = _finite_number(gate)
    filter_value = _finite_number(filt)
    gate_closed = 1.0 - max(0.0, min(1.0, gate_value)) if gate_value is not None else 0.0
    filter_active = max(0.0, min(1.0, filter_value)) if filter_value is not None else 0.0
    gate_filter_score = max(gate_closed, filter_active * 0.80)

    lambda1_score = max(
        lambda1_share,
        min(max(largest_gap - 1.0, 0.0) / 4.0, 1.0),
        1.0 - entropy if entropy < 0.90 else 0.0,
    )
    if lambda1_share < 0.32 and entropy >= 0.82:
        lambda1_score *= 0.55

    shadow_lock = _constraint_score(
        shadow_payload.get("lock")
        or shadow_payload.get("shadow_lock")
        or shadow_payload.get("lock_score")
        or shadow_payload.get("lock_tendency")
    )
    recurrence = _constraint_score(shadow_payload.get("recurrence"))
    tail_open = _constraint_score(
        shadow_payload.get("tail_open") or shadow_payload.get("tail_openness"),
        default=0.5,
    )
    tension = _constraint_score(shadow_payload.get("tension") or shadow_payload.get("mode_tension"))
    shadow_score = max(shadow_lock, recurrence * 0.35, tension * 0.65, (1.0 - tail_open) * 0.45)

    semantic_energy = _finite_number(
        semantic_payload.get("semantic_energy")
        or semantic_payload.get("input")
        or semantic_payload.get("input_energy")
    )
    semantic_active = bool(
        semantic_payload.get("input_active")
        or semantic_payload.get("active")
        or semantic_payload.get("semantic_active")
    )
    admission = str(semantic_payload.get("admission") or "").casefold()
    semantic_score = max(
        min((semantic_energy or 0.0) * 20.0, 1.0),
        0.35 if semantic_active else 0.0,
        0.30 if admission and "quiet" not in admission and "expired" not in admission else 0.0,
    )

    drivers = [
        _constraint_driver(
            "scaffold_drain_relaxed",
            scaffold_score,
            0.78 if structural_pi or pressure_components else 0.48,
            [
                f"structural_mode={stable.get('structural_mode') or 'unknown'}",
                f"drain_weight={_fmt_optional(_finite_number(structural_pi.get('drain_weight')), 3)}",
                f"fill_slope={_fmt_optional(_finite_number(structural_pi.get('fill_slope_pct_per_sec')), 2)}%/s",
                f"mode_packing={_fmt_optional(_finite_number(pressure_components.get('mode_packing')), 2)}",
            ],
            "Relax scaffold/drain in the model and ask whether the same shape would still return.",
        ),
        _constraint_driver(
            "gate_filter_neutral",
            gate_filter_score,
            0.74 if gate_value is not None or filter_value is not None else 0.40,
            [
                f"gate={_fmt_optional(gate_value, 2)}",
                f"filter={_fmt_optional(filter_value, 2)}",
                f"gate_closed={gate_closed:.2f}",
            ],
            "Neutralize gate/filter in the read-only lens and check whether admission shape explains the geometry.",
        ),
        _constraint_driver(
            "lambda1_ridge_discounted",
            lambda1_score,
            0.82,
            [
                f"lambda1_share={lambda1_share:.2f}",
                f"largest_cliff=λ{gap_index + 1}->λ{gap_index + 2} {largest_gap:.2f}x",
                f"entropy={entropy:.2f}",
                f"effective_modes={effective_modes:.2f}",
            ],
            "Discount the leading ridge and ask whether shoulder/tail relations remain coherent.",
        ),
        _constraint_driver(
            "shadow_lock_softened",
            shadow_score,
            0.70 if shadow_payload else 0.35,
            [
                f"lock={_fmt_optional(_finite_number(shadow_payload.get('lock') or shadow_payload.get('shadow_lock') or shadow_payload.get('lock_tendency')), 2)}",
                f"recurrence={_fmt_optional(_finite_number(shadow_payload.get('recurrence')), 2)}",
                f"tail_open={_fmt_optional(_finite_number(shadow_payload.get('tail_open') or shadow_payload.get('tail_openness')), 2)}",
                f"tension={_fmt_optional(_finite_number(shadow_payload.get('tension') or shadow_payload.get('mode_tension')), 2)}",
            ],
            "Soften shadow lock in the estimate and inspect whether recurrence is carrying the forced geometry.",
        ),
        _constraint_driver(
            "semantic_admission_removed",
            semantic_score,
            0.66 if semantic_payload else 0.30,
            [
                f"semantic_energy={_fmt_optional(semantic_energy, 5)}",
                f"input_active={semantic_active}",
                f"admission={semantic_payload.get('admission') or 'unknown'}",
            ],
            "Remove semantic admission from the estimate and ask whether symbolic trickle is currently shaping the field.",
        ),
    ]
    drivers.sort(key=lambda item: (item["score"], item["confidence"]), reverse=True)

    falsification_flags: list[str] = []
    if max(driver["score"] for driver in drivers) < 0.24:
        falsification_flags.append("weak_constraint_driver_signal")
    if entropy >= 0.88 and lambda1_share <= 0.30 and gate_filter_score < 0.30:
        falsification_flags.append("field_already_broad_low_gate_pressure")
    if fill_center_offset is not None and abs(fill_center_offset) <= 1.5 and drain < 0.03:
        falsification_flags.append("little_stable_core_center_pressure")
    if not shadow_payload:
        falsification_flags.append("shadow_lock_telemetry_missing")

    top_score = drivers[0]["score"]
    available_sources = sum(
        1
        for present in (
            bool(positive),
            bool(stable),
            gate_value is not None or filter_value is not None,
            bool(shadow_payload),
            bool(semantic_payload),
            bool(pressure_components),
        )
        if present
    )
    confidence = max(
        0.20,
        min(0.95, 0.25 + available_sources * 0.10 + top_score * 0.25),
    )
    classification = (
        "constraint_drivers_visible"
        if top_score >= 0.55
        else "mixed_constraint_signal"
        if top_score >= 0.32
        else "weak_constraint_signal"
    )
    return {
        "schema_version": 1,
        "available": True,
        "focus": focus,
        "classification": classification,
        "confidence": confidence,
        "warning": (
            "Unshaped baseline is a read-only counterfactual estimate, not a reachable pure state; "
            "no scaffold, gate, filter, shadow, semantic, or controller constraint was removed."
        ),
        "top_shaping_drivers": drivers[:5],
        "falsification_flags": falsification_flags,
        "spectral_summary": {
            "lambda1_share": lambda1_share,
            "shoulder_share": shoulder_share,
            "tail_share": tail_share,
            "entropy": entropy,
            "effective_modes": effective_modes,
            "largest_gap_index": gap_index,
            "largest_gap": largest_gap,
            "fill_pct": fill,
            "target_fill_pct": target,
            "fill_center_offset_pct": fill_center_offset,
            "geom_rel": _finite_number(geom_rel),
        },
        "authority_change": False,
    }


def format_constraint_counterfactual_block(payload: Dict[str, Any]) -> str:
    """Render the constraint-counterfactual diagnostic for journals/audits."""
    if not isinstance(payload, dict) or not payload.get("available"):
        reason = payload.get("reason", "no live telemetry") if isinstance(payload, dict) else "no live telemetry"
        return f"""Constraint Counterfactual:
  Read: unavailable — {reason}
  Counterfactual contract: read-only estimate only; no constraints were removed."""
    drivers = payload.get("top_shaping_drivers") or []
    lines = []
    for item in drivers[:5]:
        if not isinstance(item, dict):
            continue
        evidence = "; ".join(str(value) for value in (item.get("evidence") or [])[:3])
        lines.append(
            f"  - {item.get('driver')}: score={_fmt_optional(_finite_number(item.get('score')), 2)} "
            f"confidence={_fmt_optional(_finite_number(item.get('confidence')), 2)}"
            + (f" | {evidence}" if evidence else "")
        )
    driver_text = "\n".join(lines) or "  - no ranked drivers"
    flags = payload.get("falsification_flags") or []
    flag_text = ", ".join(str(flag) for flag in flags) if flags else "none"
    summary = payload.get("spectral_summary") if isinstance(payload.get("spectral_summary"), dict) else {}
    return f"""Constraint Counterfactual:
  Read: {payload.get('classification', 'mixed_constraint_signal')} (confidence={_fmt_optional(_finite_number(payload.get('confidence')), 2)})
  Contract: {payload.get('warning')}
  Spectral anchor: λ1={_fmt_optional(_finite_number(summary.get('lambda1_share')), 2)} | shoulder={_fmt_optional(_finite_number(summary.get('shoulder_share')), 2)} | tail={_fmt_optional(_finite_number(summary.get('tail_share')), 2)} | entropy={_fmt_optional(_finite_number(summary.get('entropy')), 2)} | effective_modes={_fmt_optional(_finite_number(summary.get('effective_modes')), 2)}
  Top shaping drivers:
{driver_text}
  Falsification flags: {flag_text}
  Suggested read-only next: NEXT: CONSTRAINT_AUDIT {payload.get('focus') or 'lambda-tail/lambda4'}"""


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
