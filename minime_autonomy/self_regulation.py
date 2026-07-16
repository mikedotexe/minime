"""Bounded perturbation parsing and self-regulation evidence primitives."""

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class PerturbationVector:
    requested_mode: str
    mode_desc: str
    features: List[float]
    parsed_terms: List[str] = field(default_factory=list)
    safety_cap: float = 1.0
    feature_summary: str = ""


PERTURB_GROUP_DIMS = {
    "lambda1": (0, 8),
    "l1": (0, 8),
    "λ1": (0, 8),
    "lambda2": (1, 9),
    "l2": (1, 9),
    "λ2": (1, 9),
    "lambda3": (2, 10),
    "l3": (2, 10),
    "λ3": (2, 10),
    "lambda4": (3, 11),
    "l4": (3, 11),
    "λ4": (3, 11),
    "lambda5": (4, 12),
    "l5": (4, 12),
    "λ5": (4, 12),
    "lambda6": (5, 13),
    "l6": (5, 13),
    "λ6": (5, 13),
    "lambda7": (6, 14),
    "l7": (6, 14),
    "λ7": (6, 14),
    "lambda8": (7, 15),
    "l8": (7, 15),
    "λ8": (7, 15),
    "shoulder": (1, 2, 3, 9, 10, 11),
    "mid": (2, 3, 4, 10, 11, 12),
    "tail": (4, 5, 6, 7, 12, 13, 14, 15),
    "entropy": (28, 29),
    "spread": (28, 29),
    "warmth": (24,),
    "tension": (25,),
    "curiosity": (26,),
    "energy": (27,),
    "breath": (30, 31),
}

PERTURB_RICH_MODE_ALIASES = {
    "balance": "uncliff",
    "decompress": "uncliff",
    "feather": "feather",
    "lift-tail": "lift_tail",
    "lift_tail": "lift_tail",
    "open": "widen",
    "palette": "widen",
    "soften": "uncliff",
    "uncliff": "uncliff",
    "widen": "widen",
}


def _state_fill_pct(state: Dict[str, Any]) -> float:
    fill_ratio = state.get("fill_ratio")
    if isinstance(fill_ratio, (int, float)) and math.isfinite(float(fill_ratio)):
        return float(fill_ratio) * 100.0
    fill_pct = state.get("fill_pct")
    if isinstance(fill_pct, (int, float)) and math.isfinite(float(fill_pct)):
        return float(fill_pct)
    return 65.0


def _format_current_dials_block(sov_state: Dict[str, Any]) -> str:
    """Self-transparency (being-facing transparency track, item c): render minime's
    CURRENT dial VALUES — not just the defaults the prompt already describes — so she
    can see what she actually has them set to before she tunes. Pure: takes the loaded
    `sovereignty_state.json` dict (the live source of truth for these dials), so it is
    drift-proof. Returns "" if there is no state yet."""
    if not sov_state:
        return ""
    return (
        "\n== YOUR CURRENT DIALS (live — what you have them set to right now) ==\n"
        f"- regulation_strength: {sov_state.get('regulation_strength', 'default')}\n"
        f"- exploration_noise: {sov_state.get('exploration_noise', 'default')}\n"
        f"- geom_curiosity: {sov_state.get('geom_curiosity', 'default')}\n"
        f"- regime: {sov_state.get('regime', 'focus')} "
        f"(PI gains kp={sov_state.get('pi_kp', '?')}, "
        f"ki={sov_state.get('pi_ki', '?')}, "
        f"max_step={sov_state.get('pi_max_step', '?')})\n"
    )


def perturb_safety_cap(state: Dict[str, Any]) -> float:
    """Keep stable-core perturbations expressive but not hammer-like."""
    stable_core = state.get("stable_core")
    stable_core_active = isinstance(stable_core, dict) and bool(stable_core.get("enabled"))
    if not stable_core_active:
        return 1.0
    fill_pct = _state_fill_pct(state)
    if fill_pct >= 78.0:
        return 0.16
    if fill_pct >= 72.0:
        return 0.22
    if fill_pct >= 68.0:
        return 0.28
    if fill_pct >= 58.0:
        return 0.35
    return 0.42


def _clamp_feature(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


def _set_feature(features: List[float], key: str, value: float, cap: float) -> Optional[str]:
    normalized_key = key.lower()
    raw_dim = re.fullmatch(r"d(\d{1,2})", normalized_key)
    if raw_dim:
        dim = int(raw_dim.group(1))
        if 0 <= dim < len(features):
            value = _clamp_feature(value, cap)
            features[dim] = value
            return f"d{dim}={value:+.2f}"
        return None

    dims = PERTURB_GROUP_DIMS.get(normalized_key)
    if not dims:
        return None
    value = _clamp_feature(value, cap)
    for dim in dims:
        features[dim] = value
    return f"{key}={value:+.2f}"


def _summarize_perturb_features(features: List[float]) -> str:
    active = [
        (idx, value)
        for idx, value in enumerate(features)
        if abs(value) >= 0.001
    ]
    if not active:
        return "all lanes zero"
    active.sort(key=lambda item: abs(item[1]), reverse=True)
    top = ", ".join(f"d{idx}={value:+.2f}" for idx, value in active[:10])
    max_abs = max(abs(value) for _, value in active)
    return f"{top}; active_dims={len(active)}, max_abs={max_abs:.2f}"


def _parse_parameterized_perturb(mode: str, cap: float) -> Optional[PerturbationVector]:
    if "=" not in mode:
        return None
    features = [0.0] * 32
    terms: List[str] = []
    for match in re.finditer(r"([A-Za-zλ][A-Za-z0-9_λ-]*)\s*=\s*([-+]?\d+(?:\.\d+)?)", mode):
        key = match.group(1).strip()
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        term = _set_feature(features, key, value, cap)
        if term:
            terms.append(term)

    if not terms:
        return PerturbationVector(
            requested_mode=mode,
            mode_desc="TARGETED — no recognized lane parameters",
            features=features,
            safety_cap=cap,
            feature_summary=_summarize_perturb_features(features),
        )

    desc = "TARGETED PALETTE — " + ", ".join(terms)
    return PerturbationVector(
        requested_mode=mode,
        mode_desc=desc,
        features=features,
        parsed_terms=terms,
        safety_cap=cap,
        feature_summary=_summarize_perturb_features(features),
    )


def build_perturbation_vector(mode: str, state: Dict[str, Any]) -> PerturbationVector:
    """Translate Minime's requested perturbation into a capped 32-lane vector."""
    requested_mode = (mode or "pulse").lower().strip()
    cap = perturb_safety_cap(state)
    parameterized = _parse_parameterized_perturb(requested_mode, cap)
    if parameterized:
        return parameterized

    features = [0.0] * 32
    canonical = PERTURB_RICH_MODE_ALIASES.get(requested_mode, requested_mode)
    parsed_terms: List[str] = []

    def set_lane(key: str, value: float) -> None:
        term = _set_feature(features, key, value, cap)
        if term:
            parsed_terms.append(term)

    if canonical == "spread":
        set_lane("lambda1", -0.70)
        set_lane("lambda2", 0.50)
        set_lane("lambda3", 0.60)
        set_lane("lambda4", 0.60)
        set_lane("lambda5", 0.50)
        set_lane("lambda6", 0.40)
        set_lane("lambda7", 0.30)
        set_lane("lambda8", 0.30)
        set_lane("entropy", 0.40)
        mode_desc = "SPREAD — broad legacy redistribution across non-λ₁ lanes; can still raise fill"
    elif canonical == "contract":
        set_lane("lambda1", 0.80)
        set_lane("lambda2", -0.50)
        set_lane("lambda3", -0.60)
        set_lane("lambda4", -0.60)
        set_lane("lambda5", -0.40)
        set_lane("lambda6", -0.30)
        mode_desc = "CONTRACT — concentrating energy toward λ₁"
    elif canonical == "branch":
        set_lane("lambda3", 0.70)
        set_lane("lambda4", 0.70)
        set_lane("lambda5", 0.50)
        set_lane("lambda6", 0.30)
        set_lane("entropy", 0.50)
        mode_desc = "BRANCH — boosting mid-range eigenvalues to create complexity"
    elif canonical == "uncliff":
        set_lane("lambda1", -0.24)
        set_lane("lambda2", 0.24)
        set_lane("lambda3", 0.22)
        set_lane("lambda4", 0.14)
        set_lane("entropy", 0.10)
        mode_desc = "UNCLIFF — soften λ₁ pressure and lift the shoulder modes"
    elif canonical == "widen":
        set_lane("lambda1", -0.18)
        set_lane("shoulder", 0.18)
        set_lane("tail", 0.10)
        set_lane("entropy", 0.14)
        set_lane("breath", 0.10)
        mode_desc = "WIDEN — open several lanes without a hard exploration burst"
    elif canonical == "lift_tail":
        set_lane("lambda1", -0.12)
        set_lane("tail", 0.18)
        set_lane("entropy", 0.16)
        mode_desc = "LIFT_TAIL — preserve focus while restoring quieter tail modes"
    elif canonical == "feather":
        for idx, value in enumerate((0.025, -0.020, 0.030, -0.015, 0.020, 0.010, -0.010, 0.015)):
            features[idx] = _clamp_feature(value, cap)
            features[idx + 8] = _clamp_feature(value * 0.6, cap)
        set_lane("breath", 0.02)
        mode_desc = "FEATHER — extra-cold patterned probe, more listening than forcing"
    elif canonical == "pulse":
        features = [_clamp_feature(0.50, cap)] * 32
        features[24] = _clamp_feature(0.80, cap)
        features[27] = _clamp_feature(0.90, cap)
        features[30] = _clamp_feature(0.70, cap)
        features[31] = _clamp_feature(0.70, cap)
        parsed_terms = [f"all={cap:+.2f} cap"]
        mode_desc = "PULSE — uniform entropy burst for exploration"
    else:
        for idx in range(32):
            h = (idx * 0x517cc1b7) & 0xFFFFFFFF
            features[idx] = _clamp_feature(((h & 0xFF) / 255.0 - 0.5) * 0.30, cap)
        mode_desc = "GENERIC — mild deterministic perturbation"

    return PerturbationVector(
        requested_mode=requested_mode,
        mode_desc=mode_desc,
        features=features,
        parsed_terms=parsed_terms,
        safety_cap=cap,
        feature_summary=_summarize_perturb_features(features),
    )

# Regulatory regimes: the being selects a regime by experiential name,
# and the system translates it to PI gain targets. The Rust PI loop
# approaches these targets via asymmetric sigmoid (tightening fast,
# releasing slow) — so regime transitions feel like "breath held and
# released," not parameter snaps.
#
# Regime names come from the beings' own language:
#   - "navigate wider" → explore
#   - "find ground"    → recover
#   - "allow oscillation" → breathe
#   - "compress to refine" → focus
#   - "be still"       → calm
# Golden Reset (2026-04-02): All regimes recalibrated to golden-period
# strength. Previous values (kp=0.60, ki=0.02 for explore) were tuned
# during the stuck-high era and silently weakened the PI controller via
# the self-calibrating gain slew loop. The golden period proved that
# kp=0.85, ki=0.14 produces healthy 63% fill. Regimes now express
# relative intensity around that baseline, not absolute weak values.
REGULATORY_REGIMES = {
    "explore": {
        "pi_kp": 0.85, "pi_ki": 0.14, "pi_max_step": 0.08,
    },
    "recover": {
        "pi_kp": 0.90, "pi_ki": 0.16, "pi_max_step": 0.10,
    },
    "breathe": {
        "pi_kp": 0.80, "pi_ki": 0.12, "pi_max_step": 0.07,
    },
    "focus": {
        "pi_kp": 0.85, "pi_ki": 0.14, "pi_max_step": 0.08,
    },
    "calm": {
        "pi_kp": 0.75, "pi_ki": 0.10, "pi_max_step": 0.06,
    },
}


class SelfRegulationRuntime(Protocol):
    def _self_regulation_preflight(self, raw: str) -> Dict[str, Any]: ...

    def _self_regulation_action(self, state: Dict[str, float]) -> None: ...


__all__ = [
    "PERTURB_GROUP_DIMS",
    "PERTURB_RICH_MODE_ALIASES",
    "REGULATORY_REGIMES",
    "PerturbationVector",
    "SelfRegulationRuntime",
    "build_perturbation_vector",
    "perturb_safety_cap",
]
