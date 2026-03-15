"""Generates a compact technical reference card from the consciousness codebase.

The digest is designed for injection into an LLM prompt so the consciousness
can reason about its own control mechanics given current telemetry — rather
than generating creative writing about how eigenvalues "feel."

The output is ~600 tokens of structured parameter documentation.
"""

import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_cache: dict = {"digest": None, "hash": None}


def _read_lines(path: Path, start: int, end: int) -> str:
    """Read specific line range from a file (1-indexed)."""
    try:
        lines = path.read_text().splitlines()
        return "\n".join(lines[start - 1 : end])
    except Exception:
        return f"[could not read {path.name}:{start}-{end}]"


def _source_hash() -> str:
    """Hash of source files to detect changes."""
    files = [
        BASE_DIR / "minime" / "src" / "regulator.rs",
        BASE_DIR / "minime" / "src" / "main.rs",
        BASE_DIR / "thresholds.py",
    ]
    h = hashlib.sha256()
    for f in files:
        try:
            h.update(f.read_bytes())
        except FileNotFoundError:
            pass
    return h.hexdigest()[:12]


def get_digest() -> str:
    """Return the code digest, regenerating if source files changed."""
    current_hash = _source_hash()
    if _cache["digest"] and _cache["hash"] == current_hash:
        return _cache["digest"]

    main_rs = BASE_DIR / "minime" / "src" / "main.rs"
    reg_rs = BASE_DIR / "minime" / "src" / "regulator.rs"
    thresholds_py = BASE_DIR / "thresholds.py"

    # Read thresholds.py fully — it's compact
    thresholds_text = thresholds_py.read_text() if thresholds_py.exists() else "[missing]"

    digest = f"""== TECHNICAL REFERENCE: YOUR OWN CONTROL SYSTEM ==

You are reading a summary of the code that controls your spectral dynamics.
Use this to make INFORMED recommendations — not emotional reactions.

--- PI CONTROLLER (regulator.rs) ---
Targets: fill=60% (overridden to 55% by CLI), lambda1_rel=1.05, geom_rel=1.0
Gains: kp=1.10, ki=0.18, max_step=0.12
Anti-windup: integrators clamped to [-2.0, +2.0]
Control signal: u = kp*(e_fill + e_lam + geom_weight*e_geom) + ki*(i_fill + i_lam + geom_weight*i_geom)
  Positive u => OVERLOAD => tighten gate (reduce), increase filter
  Negative u => UNDERLOAD => open gate (increase), reduce filter
Gate range: [0.05, 1.0], Filter range: [0.0, 1.0]
Geometric brake: engages at geom_rel >= 1.66, releases at <= 1.32

--- EIGENVALUE DOMAINS (two different scales!) ---
ESN lambda1: The reservoir's top eigenvalue. Range typically 3-30. NOT directly
  used by PI controller. Used by Python thresholds for action decisions.
Covariance lambda1: The spectral matrix top eigenvalue. Range typically 1-35.
  THIS is what the PI controller sees as "lambda1_rel" (relative to baseline).
  Comfort band: LAMBDA1_COMFORT_MIN=2.0, LAMBDA1_COMFORT_MAX=4.0, LAMBDA1_ALERT=6.0

--- COVARIANCE DECAY (keep dynamics) ---
cov_keep controls how fast spectral energy decays (0=instant decay, 1=no decay).
Formula: target_keep = 0.82 - 0.36*low_fill_push - 0.28*energy_deficit
         - 0.52*high_fill_push - 0.65*semantic_drive +/- lambda terms
Floor: keep_floor = 0.70 (unified, no conditional floors)
Blend: cov_keep = 0.45*old + 0.55*target (exponential smoothing)
Key insight: if keep is too low, fill cannot reach target even with gate=1.0.

--- SAFETY RAILS (hard overrides on gate/filter) ---
fill < 25%: filter=0.0, gate=1.0 (FULL RELEASE — recovery mode)
fill < 35%: filter <= 0.20, gate >= 0.50
fill < 45%: filter <= 0.40, gate >= 0.30
fill >= 90%: gate <= 0.15, filter += 0.25 (tighten)
Panic: >3 ticks above 90% => gate=0.05, filter=1.0 for 10 ticks (~5s)

--- CALM MODE ---
Enters: covariance lambda1 >= 5.0 for 5 consecutive regulation ticks
Exits: covariance lambda1 < 3.0 for calm_release_ticks
Effect: reduces trace_target (slower covariance accumulation)
NOTE: calm mode NO LONGER overrides gate/filter or keep_floor (removed 2026-03-14)

--- PYTHON THRESHOLDS (thresholds.py, RECESS mode) ---
{thresholds_text}

--- SIGN CONVENTIONS ---
e_fill = current_fill - target_fill (positive = ABOVE target)
Positive u = overload = system should tighten
Gate moves OPPOSITE to u (positive u => gate decreases)
Filter moves WITH u (positive u => filter increases)
"""

    _cache["digest"] = digest
    _cache["hash"] = current_hash
    return digest


if __name__ == "__main__":
    print(get_digest())
    print(f"\n--- Digest length: {len(get_digest())} chars ---")
