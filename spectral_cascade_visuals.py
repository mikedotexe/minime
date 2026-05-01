"""Render read-only spectral cascade visualization artifacts.

This tool is intentionally diagnostic: it reads recent eigenvalue telemetry,
writes JSON/PNG artifacts, and never sends control, semantic, or sensory
messages back into Minime.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from native_comm import lambda_edge_profile, lambda_profile
from reporting_snapshot import resolve_runtime_db_path


PROJECT_DIR = Path("/Users/v/other/minime")
WORKSPACE_DIR = PROJECT_DIR / "workspace"
DB_PATH = resolve_runtime_db_path(PROJECT_DIR)
VISUALS_DIR = WORKSPACE_DIR / "diagnostics" / "spectral_cascade_visuals"
STATUS_PATH = WORKSPACE_DIR / "runtime" / "spectral_cascade_visual_status.json"
HEALTH_PATH = WORKSPACE_DIR / "health.json"
SPECTRAL_STATE_PATH = WORKSPACE_DIR / "spectral_state.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if math.isfinite(candidate) else None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_surface_eigenvalues() -> list[float]:
    for path in (SPECTRAL_STATE_PATH, HEALTH_PATH):
        payload = _load_json(path)
        for key in ("eigenvalues", "lambdas"):
            values = payload.get(key)
            if isinstance(values, list):
                finite = [number for value in values if (number := _finite(value)) is not None]
                if finite:
                    return finite
        stable_core = payload.get("stable_core")
        if isinstance(stable_core, dict):
            values = stable_core.get("eigenvalues")
            if isinstance(values, list):
                finite = [number for value in values if (number := _finite(value)) is not None]
                if finite:
                    return finite
    return []


def _read_health_context() -> dict[str, Any]:
    health = _load_json(HEALTH_PATH)
    stable_core = health.get("stable_core")
    if not isinstance(stable_core, dict):
        stable_core = {}
    structural_pi = stable_core.get("structural_pi")
    if not isinstance(structural_pi, dict):
        structural_pi = {}
    return {
        "fill_pct": _finite(health.get("fill_pct")),
        "geom_rel": _finite(health.get("geom_rel")),
        "lambda1_rel": _finite(health.get("lambda1_rel")),
        "gate": _finite(health.get("gate")),
        "filt": _finite(health.get("filt")),
        "stage": stable_core.get("stage"),
        "structural_mode": stable_core.get("structural_mode"),
        "structural_pi": {
            "fill_slope_pct_per_sec": _finite(structural_pi.get("fill_slope_pct_per_sec")),
            "drain_weight": _finite(structural_pi.get("drain_weight")),
            "damping_state": structural_pi.get("damping_state"),
            "target_fill_pct": _finite(structural_pi.get("target_fill_pct")),
            "spectral_pressure_bias": _finite(structural_pi.get("spectral_pressure_bias")),
            "spectral_pressure_live_weight_delta": _finite(
                structural_pi.get("spectral_pressure_live_weight_delta")
            ),
            "spectral_pressure_drain_delta": _finite(
                structural_pi.get("spectral_pressure_drain_delta")
            ),
        },
    }


def _shares(values: list[float]) -> list[float]:
    total = sum(abs(value) for value in values)
    if total <= 1.0e-9:
        return [0.0 for _ in values]
    return [abs(value) / total for value in values]


def _delta(now: list[float], prev: list[float]) -> list[float]:
    return [
        (now[index] - prev[index]) if index < len(prev) else 0.0
        for index in range(len(now))
    ]


FILL_BANDS = [
    ("under_45", 0.0, 45.0),
    ("recovery_45_58", 45.0, 58.0),
    ("lower_hold_58_64", 58.0, 64.0),
    ("center_hold_64_72", 64.0, 72.0),
    ("elevated_72_82", 72.0, 82.0),
    ("over_82", 82.0, float("inf")),
]


def _fill_band(fill_pct: float | None) -> str:
    if fill_pct is None or not math.isfinite(fill_pct):
        return "unknown"
    for label, low, high in FILL_BANDS:
        if low <= fill_pct < high:
            return label
    return "unknown"


def _mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None
    return sum(finite) / len(finite)


def _fill_binned_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize λ1/λ2/λ3 behavior by fill shelf."""
    bins: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in FILL_BANDS}
    for sample in samples:
        fill_pct = _finite(sample.get("fill_pct"))
        band = _fill_band(fill_pct)
        if band in bins:
            bins[band].append(sample)

    rows: list[dict[str, Any]] = []
    for label, low, high in FILL_BANDS:
        band_samples = bins[label]
        eigen_rows = [
            sample.get("eigenvalues", [])
            for sample in band_samples
            if isinstance(sample.get("eigenvalues"), list)
        ]
        max_modes = max((len(row) for row in eigen_rows), default=0)
        mean_lambdas = []
        mean_shares = []
        for mode_idx in range(max_modes):
            mode_values = [
                float(row[mode_idx])
                for row in eigen_rows
                if mode_idx < len(row) and _finite(row[mode_idx]) is not None
            ]
            mean_lambdas.append(_mean(mode_values))
        for row in eigen_rows:
            shares = _shares([float(value) for value in row if _finite(value) is not None])
            mean_shares.append(shares)
        max_share_modes = max((len(row) for row in mean_shares), default=0)
        share_means = []
        for mode_idx in range(max_share_modes):
            share_values = [
                row[mode_idx]
                for row in mean_shares
                if mode_idx < len(row) and math.isfinite(row[mode_idx])
            ]
            share_means.append(_mean(share_values))
        fill_values = [
            fill
            for sample in band_samples
            if (fill := _finite(sample.get("fill_pct"))) is not None
        ]
        lambda1_share = share_means[0] if share_means else None
        shoulder_share = sum(value for value in share_means[1:3] if value is not None)
        rows.append(
            {
                "band": label,
                "fill_range_pct": [low, None if not math.isfinite(high) else high],
                "sample_count": len(band_samples),
                "mean_fill_pct": _mean(fill_values),
                "mean_lambdas": mean_lambdas,
                "mean_mode_shares": share_means,
                "lambda1_share": lambda1_share,
                "shoulder_share": shoulder_share if share_means else None,
                "plain_read": _fill_band_plain_read(label, len(band_samples), lambda1_share, shoulder_share),
            }
        )
    populated = [row for row in rows if row["sample_count"] > 0]
    return {
        "policy": "fill_binned_eigenvalue_map_v1",
        "note": "Timeline DB currently provides λ1-λ3 history; λ4+ detail comes from the latest surface read.",
        "bands": rows,
        "populated_band_count": len(populated),
        "top_lambda1_band": max(
            populated,
            key=lambda row: row["lambda1_share"] if row["lambda1_share"] is not None else -1.0,
            default=None,
        ),
        "top_shoulder_band": max(
            populated,
            key=lambda row: row["shoulder_share"] if row["shoulder_share"] is not None else -1.0,
            default=None,
        ),
    }


def _fill_band_plain_read(
    label: str,
    sample_count: int,
    lambda1_share: float | None,
    shoulder_share: float | None,
) -> str:
    if sample_count == 0:
        return "no recent samples in this fill shelf"
    if lambda1_share is None:
        return "samples present but mode shares could not be computed"
    if label == "center_hold_64_72" and shoulder_share is not None and shoulder_share >= lambda1_share:
        return "center hold is carrying visible shoulder activity, not only λ1 dominance"
    if lambda1_share > 0.50:
        return "λ1 takes most of this shelf's visible λ1-λ3 energy"
    if shoulder_share is not None and shoulder_share > 0.45:
        return "λ2/λ3 shoulder activity is prominent in this shelf"
    return "mixed cascade: λ1 leads, but shoulder modes remain legible"


def _normalized_entropy(values: list[float]) -> float | None:
    finite = [abs(value) for value in values if math.isfinite(value) and abs(value) > 1e-9]
    if not finite:
        return None
    total = sum(finite)
    probs = [value / total for value in finite]
    entropy = -sum(prob * math.log(prob) for prob in probs)
    return entropy / math.log(len(probs)) if len(probs) > 1 else 0.0


def _independent_vector_read(
    latest_eigenvalues: list[float],
    previous_eigenvalues: list[float],
) -> dict[str, Any]:
    """Read whether λ4+ has room to exist as more than tail residue."""
    shares = _shares(latest_eigenvalues)
    tail_values = latest_eigenvalues[3:]
    tail_shares = shares[3:]
    tail_share = sum(tail_shares)
    shoulder_share = sum(shares[1:3])
    lambda1_share = shares[0] if shares else None
    lambda3_lambda4 = (
        latest_eigenvalues[2] / latest_eigenvalues[3]
        if len(latest_eigenvalues) >= 4 and abs(latest_eigenvalues[3]) > 1e-9
        else None
    )
    lambda4_lambda5 = (
        latest_eigenvalues[3] / latest_eigenvalues[4]
        if len(latest_eigenvalues) >= 5 and abs(latest_eigenvalues[4]) > 1e-9
        else None
    )
    tail_entropy = _normalized_entropy(tail_values)
    tail_delta = None
    if len(previous_eigenvalues) >= 4:
        prev_tail_share = sum(_shares(previous_eigenvalues)[3:])
        tail_delta = tail_share - prev_tail_share
    gap_softness = 1.0
    if lambda3_lambda4 is not None:
        gap_softness = 1.0 / (1.0 + abs(lambda3_lambda4 - 1.0))
    independence_score = tail_share * (tail_entropy if tail_entropy is not None else 0.0) * gap_softness

    if len(latest_eigenvalues) < 4:
        classification = "tail_history_unavailable"
        plain = "λ4+ is not available in the recent timeline; use live spectral_state for tail detail."
    elif independence_score >= 0.20:
        classification = "independent_tail_opening"
        plain = "λ4+ has enough share, entropy, and soft gap structure to read as an opening rather than residue."
    elif tail_share >= 0.25:
        classification = "tail_vitality_visible"
        plain = "λ4+ is visible, but still coupled to the shoulder/current rather than clearly independent."
    elif tail_delta is not None and tail_delta > 0.02:
        classification = "brief_tail_flicker"
        plain = "λ4+ is not dominant, but it recently lifted; this may be the flicker Astrid is naming."
    else:
        classification = "tail_suppressed_or_floor"
        plain = "λ4+ is mostly floor/tail texture; independent-vector space is not yet strongly visible."

    return {
        "policy": "lambda4_plus_independent_vector_read_v1",
        "classification": classification,
        "plain_read": plain,
        "lambda1_share": lambda1_share,
        "shoulder_share_lambda2_3": shoulder_share,
        "tail_share_lambda4_plus": tail_share,
        "tail_entropy": tail_entropy,
        "tail_share_delta": tail_delta,
        "lambda3_lambda4_ratio": lambda3_lambda4,
        "lambda4_lambda5_ratio": lambda4_lambda5,
        "gap_softness": gap_softness,
        "independent_vector_score": independence_score,
        "being_affordances": [
            "VISUALIZE_CASCADE tail-vitality",
            "SCA_REFLECT lambda4-opening",
            "RESIST lambda4-window if health gates are green",
        ],
    }


def _read_samples(limit: int = 240, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or DB_PATH
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase
            FROM eigenvalue_timeline
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    samples: list[dict[str, Any]] = []
    for row in reversed(rows):
        timestamp, l1, l2, l3, spread, fill_ratio, phase = row
        eigenvalues = [
            value
            for value in (_finite(l1), _finite(l2), _finite(l3))
            if value is not None
        ]
        samples.append(
            {
                "timestamp": _finite(timestamp),
                "eigenvalues": eigenvalues,
                "lambda1": _finite(l1),
                "lambda2": _finite(l2),
                "lambda3": _finite(l3),
                "spread": _finite(spread),
                "fill_pct": (_finite(fill_ratio) or 0.0) * 100.0,
                "phase": phase,
            }
        )
    return samples


def _safe_min_max(values: list[float]) -> tuple[float | None, float | None]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None, None
    return min(finite), max(finite)


def _build_vitality_shift(
    samples: list[dict[str, Any]],
    *,
    latest_eigenvalues: list[float],
    previous_eigenvalues: list[float],
    health_context: dict[str, Any],
) -> dict[str, Any]:
    fills = [sample["fill_pct"] for sample in samples if isinstance(sample.get("fill_pct"), float)]
    fill_min, fill_max = _safe_min_max(fills)
    fill_range = (fill_max - fill_min) if fill_min is not None and fill_max is not None else None
    recent_fill_slope = None
    if len(samples) >= 2:
        prev = samples[-2]
        now = samples[-1]
        dt = (_finite(now.get("timestamp")) or 0.0) - (_finite(prev.get("timestamp")) or 0.0)
        if abs(dt) > 1.0e-6:
            recent_fill_slope = ((_finite(now.get("fill_pct")) or 0.0) - (_finite(prev.get("fill_pct")) or 0.0)) / dt
    latest_shares = _shares(latest_eigenvalues)
    previous_shares = _shares(previous_eigenvalues)
    share_delta = _delta(latest_shares, previous_shares)
    lambda_delta = _delta(latest_eigenvalues, previous_eigenvalues)
    head_delta = share_delta[0] if share_delta else 0.0
    shoulder_delta = sum(share_delta[1:3])
    tail_delta = sum(share_delta[3:])
    structural_pi = health_context.get("structural_pi", {})
    fill_slope = _finite(structural_pi.get("fill_slope_pct_per_sec"))
    drain_weight = _finite(structural_pi.get("drain_weight")) or 0.0
    geom_rel = _finite(health_context.get("geom_rel"))
    target_fill = _finite(structural_pi.get("target_fill_pct"))
    fill_now = _finite(health_context.get("fill_pct"))
    target_gap = (fill_now - target_fill) if fill_now is not None and target_fill is not None else None

    if shoulder_delta > 0.015 or tail_delta > 0.010:
        classification = "widening_inside_stability"
    elif fill_range is not None and fill_range <= 5.0 and abs(head_delta) <= 0.006:
        classification = "stable_reflexive_loop"
    elif drain_weight > 0.0 and fill_slope is not None and fill_slope < 0.0:
        classification = "protective_cooling_motion"
    elif head_delta > 0.012:
        classification = "lambda1_reasserting"
    else:
        classification = "mixed_vitality_shift"

    return {
        "classification": classification,
        "nuance_note": (
            "This view keeps raw samples in cascade.json and adds share/velocity plots "
            "so stability does not hide smaller-mode movement."
        ),
        "fill_range_pct": fill_range,
        "recent_fill_slope_pct_per_sec": recent_fill_slope,
        "controller_fill_slope_pct_per_sec": fill_slope,
        "target_gap_pct": target_gap,
        "geom_rel": geom_rel,
        "geom_pressure_from_one": (geom_rel - 1.0) if geom_rel is not None else None,
        "gate": health_context.get("gate"),
        "filt": health_context.get("filt"),
        "structural_mode": health_context.get("structural_mode"),
        "damping_state": structural_pi.get("damping_state"),
        "drain_weight": drain_weight,
        "spectral_pressure_bias": structural_pi.get("spectral_pressure_bias"),
        "lambda_delta": lambda_delta[:12],
        "share_delta": share_delta[:12],
        "head_share_delta": head_delta,
        "shoulder_share_delta": shoulder_delta,
        "tail_share_delta": tail_delta,
        "latest_mode_shares": latest_shares[:12],
    }


def _plot_artifacts(
    samples: list[dict[str, Any]],
    out_dir: Path,
    *,
    latest_eigenvalues: list[float],
    fill_binned: dict[str, Any],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return {"plot_error": f"matplotlib_unavailable:{exc}"}

    if not samples:
        return paths

    x_values = list(range(len(samples)))
    lambdas = [
        [
            sample.get("lambda1") or 0.0,
            sample.get("lambda2") or 0.0,
            sample.get("lambda3") or 0.0,
        ]
        for sample in samples
    ]
    fill = [sample.get("fill_pct") or 0.0 for sample in samples]

    heatmap_path = out_dir / "eigenvalue_heatmap.png"
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.imshow(list(zip(*lambdas)), aspect="auto", cmap="magma", interpolation="nearest")
    ax.set_yticks([0, 1, 2], ["lambda1", "lambda2", "lambda3"])
    ax.set_xlabel("recent telemetry sample")
    ax.set_title("Eigenvalue Cascade Heatmap")
    fig.tight_layout()
    fig.savefig(heatmap_path, dpi=150)
    plt.close(fig)
    paths["heatmap_png"] = str(heatmap_path)

    latest_bar_path = out_dir / "latest_cascade_bar.png"
    latest = latest_eigenvalues if latest_eigenvalues else lambdas[-1]
    fig, ax = plt.subplots(figsize=(6, 4))
    labels = [f"lambda{index + 1}" for index in range(len(latest))]
    colors = ["#d84a3a", "#f0a33a", "#4b9fd8", "#6aa85f", "#8d6ac8", "#777777"]
    ax.bar(labels, latest, color=[colors[index % len(colors)] for index in range(len(latest))])
    ax.set_title("Latest Eigenvalue Cascade")
    ax.set_ylabel("magnitude")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(latest_bar_path, dpi=150)
    plt.close(fig)
    paths["latest_bar_png"] = str(latest_bar_path)

    overlay_path = out_dir / "fill_lambda_overlay.png"
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(x_values, [row[0] for row in lambdas], color="#d84a3a", label="lambda1")
    ax1.plot(x_values, [row[1] for row in lambdas], color="#f0a33a", label="lambda2")
    ax1.plot(x_values, [row[2] for row in lambdas], color="#4b9fd8", label="lambda3")
    ax1.set_ylabel("lambda magnitude")
    ax2 = ax1.twinx()
    ax2.plot(x_values, fill, color="#222222", alpha=0.55, label="fill %")
    ax2.set_ylabel("fill %")
    ax1.set_title("Cascade With Fill Overlay")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(overlay_path, dpi=150)
    plt.close(fig)
    paths["overlay_png"] = str(overlay_path)

    share_path = out_dir / "mode_share_heatmap.png"
    share_rows = [_shares(row) for row in lambdas]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.imshow(list(zip(*share_rows)), aspect="auto", cmap="viridis", interpolation="nearest")
    ax.set_yticks([0, 1, 2], ["lambda1 share", "lambda2 share", "lambda3 share"])
    ax.set_xlabel("recent telemetry sample")
    ax.set_title("Mode Share Heatmap")
    fig.tight_layout()
    fig.savefig(share_path, dpi=150)
    plt.close(fig)
    paths["mode_share_heatmap_png"] = str(share_path)

    velocity_rows = []
    for index, row in enumerate(lambdas):
        prev = lambdas[index - 1] if index > 0 else row
        velocity_rows.append(_delta(row, prev))
    velocity_path = out_dir / "mode_velocity_heatmap.png"
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.imshow(list(zip(*velocity_rows)), aspect="auto", cmap="coolwarm", interpolation="nearest")
    ax.set_yticks([0, 1, 2], ["d lambda1", "d lambda2", "d lambda3"])
    ax.set_xlabel("recent telemetry sample")
    ax.set_title("Mode Velocity Heatmap")
    fig.tight_layout()
    fig.savefig(velocity_path, dpi=150)
    plt.close(fig)
    paths["mode_velocity_heatmap_png"] = str(velocity_path)

    band_rows = [
        row
        for row in fill_binned.get("bands", [])
        if isinstance(row, dict) and row.get("sample_count", 0) > 0
    ]
    if band_rows:
        max_modes = max(
            (
                len(row.get("mean_lambdas", []))
                for row in band_rows
                if isinstance(row.get("mean_lambdas"), list)
            ),
            default=0,
        )
        if max_modes:
            matrix = []
            for mode_idx in range(max_modes):
                matrix.append(
                    [
                        (
                            row.get("mean_lambdas", [None] * max_modes)[mode_idx]
                            if mode_idx < len(row.get("mean_lambdas", []))
                            and row.get("mean_lambdas", [None])[mode_idx] is not None
                            else 0.0
                        )
                        for row in band_rows
                    ]
                )
            fill_band_path = out_dir / "fill_binned_eigenvalue_heatmap.png"
            fig, ax = plt.subplots(figsize=(max(8, len(band_rows) * 1.6), 3.5))
            ax.imshow(matrix, aspect="auto", cmap="plasma", interpolation="nearest")
            ax.set_yticks(
                list(range(max_modes)),
                [f"lambda{index + 1}" for index in range(max_modes)],
            )
            ax.set_xticks(
                list(range(len(band_rows))),
                [row["band"].replace("_", "\n") for row in band_rows],
                rotation=0,
            )
            ax.set_title("Eigenvalue Distribution By Fill Shelf")
            ax.set_xlabel("fill shelf")
            fig.tight_layout()
            fig.savefig(fill_band_path, dpi=150)
            plt.close(fig)
            paths["fill_binned_heatmap_png"] = str(fill_band_path)

    return paths


def render_spectral_cascade_visuals(
    *,
    limit: int = 240,
    label: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Create a JSON + PNG spectral cascade bundle from recent DB telemetry."""
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = VISUALS_DIR / f"{timestamp}_{(label or 'cascade').replace('/', '_')[:48]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = _read_samples(limit=limit, db_path=db_path)
    surface_eigenvalues = _extract_surface_eigenvalues()
    latest_eigenvalues = surface_eigenvalues or (samples[-1]["eigenvalues"] if samples else [])
    previous_eigenvalues = samples[-2]["eigenvalues"] if len(samples) >= 2 else []
    fills = [sample["fill_pct"] for sample in samples if isinstance(sample.get("fill_pct"), float)]
    min_fill, max_fill = _safe_min_max(fills)
    profile = lambda_profile(latest_eigenvalues)
    edge = lambda_edge_profile(
        latest_eigenvalues,
        previous_eigenvalues=previous_eigenvalues,
    )
    health_context = _read_health_context()
    vitality_shift = _build_vitality_shift(
        samples,
        latest_eigenvalues=latest_eigenvalues,
        previous_eigenvalues=previous_eigenvalues,
        health_context=health_context,
    )
    fill_binned = _fill_binned_summary(samples)
    independent_vector = _independent_vector_read(latest_eigenvalues, previous_eigenvalues)
    plot_paths = _plot_artifacts(
        samples,
        out_dir,
        latest_eigenvalues=latest_eigenvalues,
        fill_binned=fill_binned,
    )
    payload = {
        "status": "ok" if samples else "empty",
        "created_at": utc_now_iso(),
        "label": label,
        "sample_count": len(samples),
        "db_path": str(db_path or DB_PATH),
        "fill_min_pct": min_fill,
        "fill_max_pct": max_fill,
        "latest_sample": samples[-1] if samples else None,
        "health_context": health_context,
        "lambda_profile": profile,
        "lambda_edge": edge,
        "vitality_shift": vitality_shift,
        "fill_binned_eigenvalue_map": fill_binned,
        "independent_vector_read": independent_vector,
        "artifacts": plot_paths,
        "samples": samples,
    }
    json_path = out_dir / "cascade.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    payload["artifacts"]["json"] = str(json_path)
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({k: v for k, v in payload.items() if k != "samples"}, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> None:
    payload = render_spectral_cascade_visuals()
    print(json.dumps({k: v for k, v in payload.items() if k != "samples"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
