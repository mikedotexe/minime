"""Render read-only ESN reconvergence map artifacts.

This pairs the existing spectral cascade landscape with a bounded activation
time-series texture exported by the Minime engine. The synthesis WAV is an
offline inspection proxy only; this module never sends semantic, sensory, or
control payloads back into Minime or Astrid.
"""

from __future__ import annotations

import json
import math
import re
import struct
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import spectral_cascade_visuals


PROJECT_DIR = Path("/Users/v/other/minime")
WORKSPACE_DIR = PROJECT_DIR / "workspace"
TRACE_PATH = WORKSPACE_DIR / "runtime" / "esn_activation_trace_v1.json"
RECONVERGENCE_DIR = WORKSPACE_DIR / "diagnostics" / "reconvergence_maps"
STATUS_PATH = WORKSPACE_DIR / "runtime" / "reconvergence_map_status.json"
BASELINE_DIR = RECONVERGENCE_DIR / "baselines"
BRIDGE_TRACE_DIR = WORKSPACE_DIR / "diagnostics" / "bridge_traces"
BRIDGE_TRACE_STATUS_PATH = WORKSPACE_DIR / "runtime" / "bridge_trace_status.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def unix_ms() -> int:
    return int(time.time() * 1000)


def _safe_label(label: str | None, fallback: str = "reconvergence") -> str:
    raw = (label or fallback).strip() or fallback
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return (safe or fallback)[:64]


def _finite(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if math.isfinite(candidate) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_trace(path: Path) -> dict[str, Any]:
    trace = _load_json(path)
    frames = trace.get("frames")
    if not isinstance(frames, list):
        trace["frames"] = []
    return trace


def _frame_activation(frame: dict[str, Any], reservoir_dim: int) -> list[float]:
    values = frame.get("activations")
    if not isinstance(values, list):
        values = []
    finite = [(_finite(value) or 0.0) for value in values[:reservoir_dim]]
    if len(finite) < reservoir_dim:
        finite.extend([0.0] * (reservoir_dim - len(finite)))
    return finite


def _window_frames(
    frames: list[dict[str, Any]],
    *,
    window_secs: int,
) -> list[dict[str, Any]]:
    if not frames:
        return []
    latest_t = max((_finite(frame.get("t_ms")) or 0.0) for frame in frames)
    cutoff = latest_t - max(1, window_secs) * 1000.0
    windowed = [
        frame for frame in frames if (_finite(frame.get("t_ms")) or 0.0) >= cutoff
    ]
    return windowed[-max(1, window_secs) :]


def _mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None
    return sum(finite) / len(finite)


def _min_max(values: list[float]) -> tuple[float | None, float | None]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None, None
    return min(finite), max(finite)


def _variance(values: list[float]) -> float:
    avg = _mean(values)
    if avg is None:
        return 0.0
    return sum((value - avg) ** 2 for value in values if math.isfinite(value)) / max(
        1,
        len(values),
    )


def _activation_summary(
    frames: list[dict[str, Any]],
    *,
    reservoir_dim: int,
    trace_freshness_ms: int | None,
) -> dict[str, Any]:
    if not frames:
        return {
            "status": "empty",
            "frame_count": 0,
            "reservoir_dim": reservoir_dim,
            "freshness_ms": trace_freshness_ms,
        }

    matrices = [_frame_activation(frame, reservoir_dim) for frame in frames]
    fills = [value for frame in frames if (value := _finite(frame.get("fill_pct"))) is not None]
    rms_values = [
        value
        for frame in frames
        if isinstance(frame.get("summary"), dict)
        and (value := _finite(frame["summary"].get("rms"))) is not None
    ]
    saturation_values = [
        value
        for frame in frames
        if isinstance(frame.get("summary"), dict)
        and (value := _finite(frame["summary"].get("saturation_fraction"))) is not None
    ]
    positive_values = [
        value
        for frame in frames
        if isinstance(frame.get("summary"), dict)
        and (value := _finite(frame["summary"].get("positive_fraction"))) is not None
    ]
    abs_mean_values = [
        value
        for frame in frames
        if isinstance(frame.get("summary"), dict)
        and (value := _finite(frame["summary"].get("abs_mean"))) is not None
    ]
    t_values = [
        value for frame in frames if (value := _finite(frame.get("t_ms"))) is not None
    ]
    variances = [
        (index, _variance([row[index] for row in matrices]))
        for index in range(reservoir_dim)
    ]
    variances.sort(key=lambda item: (-item[1], item[0]))
    fill_min, fill_max = _min_max(fills)
    t_min, t_max = _min_max(t_values)
    return {
        "status": "ok",
        "frame_count": len(frames),
        "reservoir_dim": reservoir_dim,
        "freshness_ms": trace_freshness_ms,
        "t_start_ms": t_min,
        "t_end_ms": t_max,
        "fill_min_pct": fill_min,
        "fill_max_pct": fill_max,
        "fill_range_pct": (fill_max - fill_min)
        if fill_min is not None and fill_max is not None
        else None,
        "rms_mean": _mean(rms_values),
        "rms_min": _min_max(rms_values)[0],
        "rms_max": _min_max(rms_values)[1],
        "abs_mean": _mean(abs_mean_values),
        "saturation_fraction_mean": _mean(saturation_values),
        "positive_fraction_mean": _mean(positive_values),
        "top_node_indexes_by_variance": [index for index, _ in variances[:8]],
        "top_node_variance": [variance for _, variance in variances[:8]],
    }


def _landscape_summary(cascade_payload: dict[str, Any]) -> dict[str, Any]:
    vitality = cascade_payload.get("vitality_shift")
    if not isinstance(vitality, dict):
        vitality = {}
    lambda_profile = cascade_payload.get("lambda_profile")
    if not isinstance(lambda_profile, dict):
        lambda_profile = {}
    pom = lambda_profile.get("pom")
    if not isinstance(pom, dict):
        pom = {}
    fill_map = cascade_payload.get("fill_binned_eigenvalue_map")
    if not isinstance(fill_map, dict):
        fill_map = {}
    return {
        "status": cascade_payload.get("status", "unknown"),
        "sample_count": cascade_payload.get("sample_count"),
        "fill_min_pct": cascade_payload.get("fill_min_pct"),
        "fill_max_pct": cascade_payload.get("fill_max_pct"),
        "vitality_classification": vitality.get("classification"),
        "pom_classification": pom.get("classification"),
        "latest_mode_shares": vitality.get("latest_mode_shares") or [],
        "head_share_delta": vitality.get("head_share_delta"),
        "shoulder_share_delta": vitality.get("shoulder_share_delta"),
        "tail_share_delta": vitality.get("tail_share_delta"),
        "populated_fill_bands": fill_map.get("populated_band_count"),
    }


def _plot_activation_artifacts(
    frames: list[dict[str, Any]],
    out_dir: Path,
    *,
    reservoir_dim: int,
    top_nodes: list[int],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    if not frames:
        return paths
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        return {"plot_error": f"plot_stack_unavailable:{exc}"}

    matrix = np.array(
        [_frame_activation(frame, reservoir_dim) for frame in frames],
        dtype=float,
    )
    if matrix.size == 0:
        return paths

    heatmap_path = out_dir / "activation_heatmap.png"
    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(matrix.T, aspect="auto", cmap="coolwarm", vmin=-1.0, vmax=1.0)
    ax.set_title("ESN Activation Texture")
    ax.set_xlabel("sample")
    ax.set_ylabel("reservoir node")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    fig.savefig(heatmap_path, dpi=150)
    plt.close(fig)
    paths["activation_heatmap_png"] = str(heatmap_path)

    trace_path = out_dir / "top_node_traces.png"
    x_values = np.arange(matrix.shape[0])
    fig, ax = plt.subplots(figsize=(12, 4))
    for node in top_nodes[:8]:
        if 0 <= node < matrix.shape[1]:
            ax.plot(x_values, matrix[:, node], label=f"node {node}", linewidth=1.25)
    ax.set_title("Top-Variance Activation Lanes")
    ax.set_xlabel("sample")
    ax.set_ylabel("activation")
    ax.set_ylim(-1.05, 1.05)
    if top_nodes:
        ax.legend(loc="upper right", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(trace_path, dpi=150)
    plt.close(fig)
    paths["top_node_traces_png"] = str(trace_path)

    if matrix.shape[0] >= 3 and matrix.shape[1] >= 2:
        centered = matrix - matrix.mean(axis=0, keepdims=True)
        try:
            _, _, vh = np.linalg.svd(centered, full_matrices=False)
            components = centered @ vh[:2].T
            pca_path = out_dir / "activation_pca_trajectory.png"
            fig, ax = plt.subplots(figsize=(6, 5))
            ax.plot(components[:, 0], components[:, 1], linewidth=1.0, alpha=0.75)
            ax.scatter(
                components[:, 0],
                components[:, 1],
                c=np.linspace(0.0, 1.0, components.shape[0]),
                cmap="viridis",
                s=22,
            )
            ax.scatter(
                [components[0, 0]],
                [components[0, 1]],
                color="black",
                marker="o",
                s=40,
                label="start",
            )
            ax.scatter(
                [components[-1, 0]],
                [components[-1, 1]],
                color="red",
                marker="x",
                s=55,
                label="latest",
            )
            ax.set_title("Activation PCA Trajectory")
            ax.set_xlabel("PC1")
            ax.set_ylabel("PC2")
            ax.legend(loc="best", fontsize=8)
            fig.tight_layout()
            fig.savefig(pca_path, dpi=150)
            plt.close(fig)
            paths["activation_pca_trajectory_png"] = str(pca_path)
        except Exception as exc:
            paths["pca_error"] = f"pca_unavailable:{exc}"

    return paths


def _write_activation_synthesis(
    frames: list[dict[str, Any]],
    out_dir: Path,
    *,
    reservoir_dim: int,
    top_nodes: list[int],
) -> str | None:
    if not frames or not top_nodes:
        return None
    matrix = [_frame_activation(frame, reservoir_dim) for frame in frames]
    sample_rate = 16_000
    duration_secs = min(12.0, max(3.0, len(frames) / 12.0))
    sample_count = int(sample_rate * duration_secs)
    if sample_count <= 0:
        return None
    lanes = [node for node in top_nodes[:8] if 0 <= node < reservoir_dim]
    if not lanes:
        return None

    samples: list[float] = []
    for sample_idx in range(sample_count):
        pos = sample_idx / max(1, sample_count - 1) * max(1, len(matrix) - 1)
        left = int(math.floor(pos))
        right = min(len(matrix) - 1, left + 1)
        frac = pos - left
        value = 0.0
        for lane_idx, node in enumerate(lanes):
            envelope = matrix[left][node] * (1.0 - frac) + matrix[right][node] * frac
            frequency = 110.0 * (2.0 ** (lane_idx / 3.0))
            phase = 2.0 * math.pi * frequency * sample_idx / sample_rate
            value += math.sin(phase) * envelope * 0.10
        samples.append(value / max(1, len(lanes)))

    peak = max((abs(value) for value in samples), default=1.0)
    gain = 0.82 / peak if peak > 1.0e-6 else 1.0
    wav_path = out_dir / "activation_synthesis.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for value in samples:
            sample = int(max(-1.0, min(1.0, value * gain)) * 32767)
            handle.writeframes(struct.pack("<h", sample))
    return str(wav_path)


def _vector_distance(left: list[Any], right: list[Any]) -> float | None:
    left_finite = [value for value in (_finite(item) for item in left) if value is not None]
    right_finite = [value for value in (_finite(item) for item in right) if value is not None]
    if not left_finite or not right_finite:
        return None
    width = max(len(left_finite), len(right_finite))
    distance = 0.0
    for index in range(width):
        a = left_finite[index] if index < len(left_finite) else 0.0
        b = right_finite[index] if index < len(right_finite) else 0.0
        distance += abs(a - b)
    return distance / width


def _activation_distance(current: dict[str, Any], baseline: dict[str, Any]) -> float | None:
    deltas: list[float] = []
    for key, scale in (
        ("rms_mean", 1.0),
        ("abs_mean", 1.0),
        ("saturation_fraction_mean", 1.0),
        ("positive_fraction_mean", 1.0),
        ("fill_range_pct", 100.0),
    ):
        current_value = _finite(current.get(key))
        baseline_value = _finite(baseline.get(key))
        if current_value is not None and baseline_value is not None:
            deltas.append(abs(current_value - baseline_value) / scale)

    current_nodes = set(current.get("top_node_indexes_by_variance") or [])
    baseline_nodes = set(baseline.get("top_node_indexes_by_variance") or [])
    if current_nodes or baseline_nodes:
        overlap = len(current_nodes & baseline_nodes)
        union = len(current_nodes | baseline_nodes)
        deltas.append(1.0 - overlap / max(1, union))
    return _mean(deltas) if deltas else None


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    if left_mean is None or right_mean is None:
        return None
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    denom = math.sqrt(left_var * right_var)
    if denom <= 1.0e-12:
        return None
    return numerator / denom


def _latest_eigen_mode(index: int) -> float | None:
    for path in (
        WORKSPACE_DIR / "spectral_state.json",
        WORKSPACE_DIR / "health.json",
    ):
        payload = _load_json(path)
        for key in ("eigenvalues", "lambdas"):
            values = payload.get(key)
            if isinstance(values, list) and len(values) > index:
                value = _finite(values[index])
                if value is not None:
                    return value
        stable_core = payload.get("stable_core")
        if isinstance(stable_core, dict):
            values = stable_core.get("eigenvalues")
            if isinstance(values, list) and len(values) > index:
                value = _finite(values[index])
                if value is not None:
                    return value
    return None


def _bridge_trace_plot(
    frames: list[dict[str, Any]],
    out_dir: Path,
    *,
    lane_index: int,
    reservoir_dim: int,
) -> dict[str, str]:
    if not frames or reservoir_dim <= lane_index:
        return {}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return {"plot_error": f"matplotlib_unavailable:{exc}"}

    lane_values = [
        _frame_activation(frame, reservoir_dim)[lane_index]
        for frame in frames
    ]
    fill_values = [
        _finite(frame.get("fill_pct")) or 0.0
        for frame in frames
    ]
    x_values = list(range(len(frames)))
    path = out_dir / "activation_lane6_marker_trace.png"
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(
        x_values,
        lane_values,
        color="#0f766e",
        linewidth=1.6,
        label="activation lane 6 marker",
    )
    ax1.axhline(0.0, color="#737373", linewidth=0.8, alpha=0.5)
    ax1.set_xlabel("sample")
    ax1.set_ylabel("activation lane 6")
    ax1.set_ylim(-1.05, 1.05)
    ax2 = ax1.twinx()
    ax2.plot(x_values, fill_values, color="#7c2d12", linewidth=1.0, alpha=0.65, label="fill pct")
    ax2.set_ylabel("fill %")
    ax1.set_title("M6 Marker Trace V1.1")
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return {
        "activation_lane6_marker_png": str(path),
        "m6_bridge_trace_png": str(path),
    }


def _baseline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy": "reconvergence_baseline_v1",
        "created_at": utc_now_iso(),
        "label": payload.get("label"),
        "artifact_dir": payload.get("artifact_dir"),
        "landscape": payload.get("landscape_summary"),
        "activation_summary": payload.get("activation_summary"),
    }


def _apply_baseline_actions(
    payload: dict[str, Any],
    *,
    save_baseline: str | None,
    compare_baseline: str | None,
) -> None:
    if compare_baseline:
        baseline_path = BASELINE_DIR / f"{_safe_label(compare_baseline)}.json"
        baseline = _load_json(baseline_path)
        if not baseline:
            payload["baseline_status"] = "missing"
            payload["baseline_comparison"] = {
                "name": compare_baseline,
                "status": "missing",
                "path": str(baseline_path),
            }
        else:
            baseline_landscape = baseline.get("landscape")
            if not isinstance(baseline_landscape, dict):
                baseline_landscape = {}
            baseline_activation = baseline.get("activation_summary")
            if not isinstance(baseline_activation, dict):
                baseline_activation = {}
            current_landscape = payload.get("landscape_summary") or {}
            current_activation = payload.get("activation_summary") or {}
            payload["baseline_status"] = "available"
            payload["baseline_comparison"] = {
                "name": compare_baseline,
                "status": "ok",
                "path": str(baseline_path),
                "landscape_distance": _vector_distance(
                    current_landscape.get("latest_mode_shares") or [],
                    baseline_landscape.get("latest_mode_shares") or [],
                ),
                "activation_summary_distance": _activation_distance(
                    current_activation,
                    baseline_activation,
                ),
            }
    else:
        payload["baseline_status"] = "unavailable"
        payload["baseline_comparison"] = None

    if save_baseline:
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        baseline_path = BASELINE_DIR / f"{_safe_label(save_baseline)}.json"
        _write_json(baseline_path, _baseline_payload(payload))
        payload["saved_baseline"] = {
            "name": save_baseline,
            "path": str(baseline_path),
        }
        if not compare_baseline:
            payload["baseline_status"] = "saved"


def _compact_for_status(payload: dict[str, Any]) -> dict[str, Any]:
    activation_trace = payload.get("activation_trace")
    if not isinstance(activation_trace, dict):
        activation_trace = {}
    return {
        "status": payload.get("status"),
        "created_at": payload.get("created_at"),
        "label": payload.get("label"),
        "artifact_dir": payload.get("artifact_dir"),
        "artifacts": payload.get("artifacts", {}),
        "activation_trace": {
            "status": activation_trace.get("status"),
            "trace_path": activation_trace.get("trace_path"),
            "frame_count": activation_trace.get("frame_count"),
            "freshness_ms": activation_trace.get("freshness_ms"),
            "reservoir_dim": activation_trace.get("reservoir_dim"),
            "sample_interval_ms": activation_trace.get("sample_interval_ms"),
            "retained_secs": activation_trace.get("retained_secs"),
        },
        "activation_summary": payload.get("activation_summary"),
        "baseline_status": payload.get("baseline_status"),
        "baseline_comparison": payload.get("baseline_comparison"),
        "saved_baseline": payload.get("saved_baseline"),
        "provenance": payload.get("provenance"),
    }


def _compact_bridge_trace_for_status(payload: dict[str, Any]) -> dict[str, Any]:
    bridge_signal = payload.get("bridge_signal")
    if not isinstance(bridge_signal, dict):
        bridge_signal = {}
    return {
        "policy": payload.get("policy"),
        "status": payload.get("status"),
        "created_at": payload.get("created_at"),
        "label": payload.get("label"),
        "mode": payload.get("mode"),
        "mode_source": bridge_signal.get("mode_source"),
        "mode6_interpretation": bridge_signal.get("mode6_interpretation"),
        "eigenmode_confirmed": bridge_signal.get("eigenmode_confirmed"),
        "bridge_evidence_level": bridge_signal.get("bridge_evidence_level"),
        "artifact_dir": payload.get("artifact_dir"),
        "artifacts": payload.get("artifacts", {}),
        "frame_count": payload.get("frame_count"),
        "trace_freshness_ms": payload.get("trace_freshness_ms"),
        "bridge_signal": bridge_signal,
        "provenance": payload.get("provenance"),
    }


def render_reconvergence_map(
    *,
    label: str | None = None,
    window_secs: int = 180,
    save_baseline: str | None = None,
    compare_baseline: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Create a read-only reconvergence artifact bundle."""
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_label = _safe_label(label)
    out_dir = RECONVERGENCE_DIR / f"{timestamp}_{safe_label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cascade_payload = spectral_cascade_visuals.render_spectral_cascade_visuals(
        limit=240,
        label=f"reconvergence_{safe_label}",
        db_path=db_path,
    )
    cascade_compact = {key: value for key, value in cascade_payload.items() if key != "samples"}

    trace = _load_trace(TRACE_PATH)
    trace_frames = trace.get("frames") if isinstance(trace.get("frames"), list) else []
    reservoir_dim = int(_finite(trace.get("reservoir_dim")) or 0)
    if reservoir_dim <= 0:
        reservoir_dim = max(
            (len(frame.get("activations") or []) for frame in trace_frames if isinstance(frame, dict)),
            default=0,
        )
    windowed_frames = _window_frames(
        [frame for frame in trace_frames if isinstance(frame, dict)],
        window_secs=window_secs,
    )
    trace_freshness_ms = None
    updated_at = _finite(trace.get("updated_at_unix_ms"))
    if updated_at is not None:
        trace_freshness_ms = max(0, unix_ms() - int(updated_at))
    activation_summary = _activation_summary(
        windowed_frames,
        reservoir_dim=reservoir_dim,
        trace_freshness_ms=trace_freshness_ms,
    )

    artifacts: dict[str, str] = {}
    artifacts["reconvergence_json"] = str(out_dir / "reconvergence.json")
    cascade_artifacts = cascade_compact.get("artifacts")
    if isinstance(cascade_artifacts, dict):
        artifacts["landscape_cascade_json"] = str(cascade_artifacts.get("json", ""))
        for key, value in cascade_artifacts.items():
            if isinstance(value, str) and value:
                artifacts[f"landscape_{key}"] = value

    if windowed_frames and reservoir_dim > 0:
        top_nodes = activation_summary.get("top_node_indexes_by_variance") or []
        plot_paths = _plot_activation_artifacts(
            windowed_frames,
            out_dir,
            reservoir_dim=reservoir_dim,
            top_nodes=[int(node) for node in top_nodes],
        )
        artifacts.update(plot_paths)
        wav_path = _write_activation_synthesis(
            windowed_frames,
            out_dir,
            reservoir_dim=reservoir_dim,
            top_nodes=[int(node) for node in top_nodes],
        )
        if wav_path:
            artifacts["activation_synthesis_wav"] = wav_path

    status = "ok" if windowed_frames else "empty"
    payload: dict[str, Any] = {
        "policy": "reconvergence_maps_v1",
        "status": status,
        "created_at": utc_now_iso(),
        "label": label,
        "artifact_dir": str(out_dir),
        "window_secs": window_secs,
        "landscape_summary": _landscape_summary(cascade_compact),
        "landscape_artifact": cascade_compact,
        "activation_trace": {
            "status": status,
            "trace_path": str(TRACE_PATH),
            "frame_count": len(windowed_frames),
            "source_frame_count": len(trace_frames),
            "reservoir_dim": reservoir_dim,
            "sample_interval_ms": trace.get("sample_interval_ms"),
            "retained_secs": trace.get("retained_secs"),
            "freshness_ms": trace_freshness_ms,
            "frames": windowed_frames,
        },
        "activation_summary": activation_summary,
        "artifacts": artifacts,
        "provenance": {
            "read_only": True,
            "source": "minime_live_esn_x_runtime_trace",
            "control_payload": False,
            "semantic_payload": False,
            "sensory_payload": False,
            "sensory_change": False,
            "esn_mutation": False,
            "pi_target_change": False,
            "scaffold_policy_change": False,
            "bridge_write_change": False,
            "synthesis_feedback": False,
        },
    }
    _apply_baseline_actions(
        payload,
        save_baseline=save_baseline,
        compare_baseline=compare_baseline,
    )

    json_path = Path(artifacts["reconvergence_json"])
    _write_json(json_path, payload)
    _write_json(STATUS_PATH, _compact_for_status(payload))
    return payload


def render_bridge_trace(
    *,
    mode: str = "m6",
    label: str | None = None,
    window_secs: int = 60,
) -> dict[str, Any]:
    """Create a sacredly read-only bridge trace artifact.

    V1.1 treats `m6` as an unresolved attention marker: activation lane index 5
    across the bounded ESN trace, plus the latest λ6 value when available. It
    does not assert that m6 is an eigenmode, and it never opens a
    control/semantic/sensory channel.
    """
    normalized_mode = (mode or "m6").strip().lower() or "m6"
    if normalized_mode not in {"m6", "mode6", "lane6"}:
        normalized_mode = "m6"
    lane_index = 5
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_label = _safe_label(label, fallback="bridge")
    out_dir = BRIDGE_TRACE_DIR / f"{timestamp}_{normalized_mode}_{safe_label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    trace = _load_trace(TRACE_PATH)
    trace_frames = trace.get("frames") if isinstance(trace.get("frames"), list) else []
    reservoir_dim = int(_finite(trace.get("reservoir_dim")) or 0)
    if reservoir_dim <= 0:
        reservoir_dim = max(
            (
                len(frame.get("activations") or [])
                for frame in trace_frames
                if isinstance(frame, dict)
            ),
            default=0,
        )
    frames = _window_frames(
        [frame for frame in trace_frames if isinstance(frame, dict)],
        window_secs=window_secs,
    )
    updated_at = _finite(trace.get("updated_at_unix_ms"))
    trace_freshness_ms = max(0, unix_ms() - int(updated_at)) if updated_at is not None else None

    lane_values = [
        _frame_activation(frame, reservoir_dim)[lane_index]
        for frame in frames
        if reservoir_dim > lane_index
    ]
    fill_values = [
        value for frame in frames if (value := _finite(frame.get("fill_pct"))) is not None
    ]
    geom_values = [
        value for frame in frames if (value := _finite(frame.get("geom_rel"))) is not None
    ]
    lambda1_values = [
        value for frame in frames if (value := _finite(frame.get("lambda1_rel"))) is not None
    ]
    start_value = lane_values[0] if lane_values else None
    latest_value = lane_values[-1] if lane_values else None
    min_value, max_value = _min_max(lane_values)
    shift = (
        latest_value - start_value
        if latest_value is not None and start_value is not None
        else None
    )
    amplitude = (
        max_value - min_value
        if min_value is not None and max_value is not None
        else None
    )
    variance = _variance(lane_values) if lane_values else None
    sign_crossings = 0
    for left, right in zip(lane_values, lane_values[1:]):
        if (left < 0.0 <= right) or (left > 0.0 >= right):
            sign_crossings += 1
    observation_window_marked = bool(
        (shift is not None and abs(shift) >= 0.08)
        or (amplitude is not None and amplitude >= 0.18)
        or (variance is not None and variance >= 0.006)
    )
    lambda6_latest = _latest_eigen_mode(lane_index)
    activation_lane6_marker = {
        "lane_index_zero_based": lane_index,
        "lane_index_one_based": lane_index + 1,
        "start_activation": start_value,
        "latest_activation": latest_value,
        "shift": shift,
        "amplitude": amplitude,
        "variance": variance,
        "sign_crossings": sign_crossings,
        "fill_correlation": _pearson(lane_values, fill_values)
        if len(lane_values) == len(fill_values)
        else None,
        "geom_correlation": _pearson(lane_values, geom_values)
        if len(lane_values) == len(geom_values)
        else None,
        "lambda1_rel_correlation": _pearson(lane_values, lambda1_values)
        if len(lane_values) == len(lambda1_values)
        else None,
    }
    bridge_signal = {
        "mode": normalized_mode,
        "mode_source": "activation_lane6_marker_with_lambda6_context",
        "mode6_interpretation": "unresolved_marker",
        "interpretation": "unresolved_attention_marker_not_confirmed_eigenmode",
        "eigenmode_confirmed": False,
        "bridge_evidence_level": "marker_only",
        "lambda6_latest": lambda6_latest,
        "activation_lane6_marker": activation_lane6_marker,
        "lane_index_zero_based": lane_index,
        "lane_index_one_based": lane_index + 1,
        "latest_spectral_mode6": lambda6_latest,
        "start_activation": start_value,
        "latest_activation": latest_value,
        "shift": shift,
        "amplitude": amplitude,
        "variance": variance,
        "sign_crossings": sign_crossings,
        "observation_window_marked": observation_window_marked,
        "bridge_opened": False,
        "fill_correlation": activation_lane6_marker["fill_correlation"],
        "geom_correlation": activation_lane6_marker["geom_correlation"],
        "lambda1_rel_correlation": activation_lane6_marker["lambda1_rel_correlation"],
        "plain_read": (
            "activation lane 6 shifted enough to mark a read-only observation window; m6 remains an unresolved marker, not a confirmed eigenmode"
            if observation_window_marked
            else "activation lane 6 stayed quiet; m6 remains an unresolved marker, not a confirmed eigenmode"
        ),
    }
    artifacts = {"bridge_trace_json": str(out_dir / "bridge_trace.json")}
    artifacts.update(
        _bridge_trace_plot(
            frames,
            out_dir,
            lane_index=lane_index,
            reservoir_dim=reservoir_dim,
        )
    )
    status = "ok" if frames and reservoir_dim > lane_index else "empty"
    payload = {
        "policy": "m6_bridge_trace_v1_1",
        "status": status,
        "created_at": utc_now_iso(),
        "label": label,
        "mode": normalized_mode,
        "artifact_dir": str(out_dir),
        "window_secs": window_secs,
        "frame_count": len(frames),
        "reservoir_dim": reservoir_dim,
        "trace_path": str(TRACE_PATH),
        "trace_freshness_ms": trace_freshness_ms,
        "bridge_signal": bridge_signal,
        "frames": [
            {
                "t_ms": frame.get("t_ms"),
                "wall_clock_unix_ms": frame.get("wall_clock_unix_ms"),
                "fill_pct": frame.get("fill_pct"),
                "stage": frame.get("stage"),
                "geom_rel": frame.get("geom_rel"),
                "lambda1_rel": frame.get("lambda1_rel"),
                "activation_lane6_marker": _frame_activation(frame, reservoir_dim)[lane_index]
                if reservoir_dim > lane_index
                else None,
                "m6_activation": _frame_activation(frame, reservoir_dim)[lane_index]
                if reservoir_dim > lane_index
                else None,
            }
            for frame in frames
        ],
        "artifacts": artifacts,
        "provenance": {
            "read_only": True,
            "source": "minime_live_esn_x_runtime_trace",
            "attention_marker_only": True,
            "mode_source": "activation_lane6_marker_with_lambda6_context",
            "mode6_interpretation": "unresolved_marker",
            "eigenmode_confirmed": False,
            "diagnostic_artifact_write": True,
            "substrate_write": False,
            "connection": False,
            "replication": False,
            "control_payload": False,
            "semantic_payload": False,
            "sensory_payload": False,
            "sensory_change": False,
            "esn_mutation": False,
            "pi_target_change": False,
            "scaffold_policy_change": False,
            "bridge_write_change": False,
            "synthesis_feedback": False,
        },
    }
    json_path = Path(artifacts["bridge_trace_json"])
    _write_json(json_path, payload)
    _write_json(BRIDGE_TRACE_STATUS_PATH, _compact_bridge_trace_for_status(payload))
    return payload


def main() -> None:
    payload = render_reconvergence_map()
    compact = {key: value for key, value in payload.items() if key not in {"activation_trace"}}
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
