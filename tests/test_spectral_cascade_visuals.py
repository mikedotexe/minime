import json
import math
import sqlite3
from pathlib import Path

import reconvergence_maps
import spectral_cascade_visuals


def _write_synthetic_eigen_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE eigenvalue_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            lambda1 REAL NOT NULL,
            lambda2 REAL NOT NULL,
            lambda3 REAL NOT NULL,
            spread REAL NOT NULL,
            fill_ratio REAL NOT NULL,
            phase TEXT NOT NULL
        )
        """
    )
    for idx in range(4):
        conn.execute(
            """
            INSERT INTO eigenvalue_timeline
            (session_id, timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase)
            VALUES (1, ?, ?, ?, ?, 3, ?, 'hold')
            """,
            (float(idx), 6.0 + idx, 3.0, 1.2, 0.60 + idx * 0.02),
        )
    conn.commit()
    conn.close()


def _patch_cascade_paths(monkeypatch, workspace: Path) -> None:
    monkeypatch.setattr(spectral_cascade_visuals, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(
        spectral_cascade_visuals,
        "VISUALS_DIR",
        workspace / "diagnostics" / "spectral_cascade_visuals",
    )
    monkeypatch.setattr(
        spectral_cascade_visuals,
        "STATUS_PATH",
        workspace / "runtime" / "spectral_cascade_visual_status.json",
    )
    monkeypatch.setattr(spectral_cascade_visuals, "HEALTH_PATH", workspace / "health.json")
    monkeypatch.setattr(
        spectral_cascade_visuals,
        "SPECTRAL_STATE_PATH",
        workspace / "spectral_state.json",
    )


def _write_health_and_spectral_state(workspace: Path) -> None:
    (workspace / "health.json").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "health.json").write_text(
        json.dumps(
            {
                "fill_pct": 66.0,
                "geom_rel": 1.01,
                "gate": 0.18,
                "filt": 0.60,
                "stable_core": {
                    "stage": "hold",
                    "structural_mode": "scaffold_hold",
                    "structural_pi": {
                        "fill_slope_pct_per_sec": 0.2,
                        "drain_weight": 0.0,
                        "target_fill_pct": 68.0,
                    },
                },
            }
        )
    )
    (workspace / "spectral_state.json").write_text(
        json.dumps(
            {
                "eigenvalues": [6.0, 3.1, 2.9, 2.7, 2.5, 1.0, 1.0, 1.0],
            }
        )
    )


def _write_activation_trace(path: Path, *, frame_count: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    base_wall_ms = 1_900_000_000_000
    for idx in range(frame_count):
        activations = [
            round(0.45 * math.sin(idx * 0.3 + node * 0.07), 6)
            for node in range(128)
        ]
        summary = {
            "mean": sum(activations) / len(activations),
            "abs_mean": sum(abs(value) for value in activations) / len(activations),
            "rms": (
                sum(value * value for value in activations) / len(activations)
            )
            ** 0.5,
            "min": min(activations),
            "max": max(activations),
            "saturation_fraction": 0.0,
            "positive_fraction": sum(1 for value in activations if value > 0) / len(activations),
            "finite_fraction": 1.0,
        }
        frames.append(
            {
                "t_ms": idx * 1000,
                "wall_clock_unix_ms": base_wall_ms + idx * 1000,
                "fill_pct": 66.0 + idx * 0.25,
                "stage": "hold",
                "geom_rel": 1.0 + idx * 0.002,
                "lambda1_rel": 0.98 + idx * 0.001,
                "summary": summary,
                "top_active_node_indexes": list(range(8)),
                "activations": activations,
            }
        )
    path.write_text(
        json.dumps(
            {
                "policy": "esn_activation_trace_v1",
                "updated_at_unix_ms": base_wall_ms + (frame_count - 1) * 1000,
                "reservoir_dim": 128,
                "sample_interval_ms": 1000,
                "retained_secs": 180,
                "frames": frames,
            }
        )
    )


def _patch_reconvergence_paths(monkeypatch, workspace: Path) -> None:
    monkeypatch.setattr(reconvergence_maps, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(
        reconvergence_maps,
        "TRACE_PATH",
        workspace / "runtime" / "esn_activation_trace_v1.json",
    )
    monkeypatch.setattr(
        reconvergence_maps,
        "RECONVERGENCE_DIR",
        workspace / "diagnostics" / "reconvergence_maps",
    )
    monkeypatch.setattr(
        reconvergence_maps,
        "STATUS_PATH",
        workspace / "runtime" / "reconvergence_map_status.json",
    )
    monkeypatch.setattr(
        reconvergence_maps,
        "BASELINE_DIR",
        workspace / "diagnostics" / "reconvergence_maps" / "baselines",
    )
    monkeypatch.setattr(
        reconvergence_maps,
        "BRIDGE_TRACE_DIR",
        workspace / "diagnostics" / "bridge_traces",
    )
    monkeypatch.setattr(
        reconvergence_maps,
        "BRIDGE_TRACE_STATUS_PATH",
        workspace / "runtime" / "bridge_trace_status.json",
    )


def test_render_spectral_cascade_visuals_writes_json(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "minime_consciousness.db"
    _write_synthetic_eigen_db(db_path)

    _patch_cascade_paths(monkeypatch, workspace)
    _write_health_and_spectral_state(workspace)
    payload = spectral_cascade_visuals.render_spectral_cascade_visuals(
        limit=10,
        label="unit",
        db_path=db_path,
    )

    assert payload["status"] == "ok"
    assert payload["sample_count"] == 4
    assert payload["lambda_profile"]["ratios"]["lambda1_lambda2"] >= 1.75
    assert payload["vitality_shift"]["classification"] in {
        "lambda1_reasserting",
        "mixed_vitality_shift",
        "stable_reflexive_loop",
        "widening_inside_stability",
    }
    assert payload["vitality_shift"]["geom_rel"] == 1.01
    assert payload["fill_binned_eigenvalue_map"]["populated_band_count"] >= 1
    assert payload["independent_vector_read"]["tail_share_lambda4_plus"] > 0
    assert payload["independent_vector_read"]["classification"] in {
        "independent_tail_opening",
        "tail_vitality_visible",
        "brief_tail_flicker",
        "tail_suppressed_or_floor",
    }
    json_path = Path(payload["artifacts"]["json"])
    assert json_path.exists()
    assert Path(payload["artifacts"]["fill_binned_heatmap_png"]).exists()
    loaded = json.loads(json_path.read_text())
    assert loaded["sample_count"] == 4
    assert "fill_binned_eigenvalue_map" in loaded
    assert "independent_vector_read" in loaded
    assert (workspace / "runtime" / "spectral_cascade_visual_status.json").exists()


def test_render_reconvergence_map_writes_activation_artifacts_and_baseline(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "minime_consciousness.db"
    _write_synthetic_eigen_db(db_path)
    _patch_cascade_paths(monkeypatch, workspace)
    _patch_reconvergence_paths(monkeypatch, workspace)
    _write_health_and_spectral_state(workspace)
    _write_activation_trace(workspace / "runtime" / "esn_activation_trace_v1.json")

    payload = reconvergence_maps.render_reconvergence_map(
        label="unit",
        window_secs=180,
        save_baseline="unit_baseline",
        db_path=db_path,
    )

    assert payload["status"] == "ok"
    assert payload["activation_summary"]["frame_count"] == 6
    assert payload["activation_summary"]["reservoir_dim"] == 128
    assert payload["baseline_status"] == "saved"
    assert Path(payload["artifacts"]["reconvergence_json"]).exists()
    assert Path(payload["artifacts"]["activation_heatmap_png"]).exists()
    assert Path(payload["artifacts"]["top_node_traces_png"]).exists()
    assert Path(payload["artifacts"]["activation_pca_trajectory_png"]).exists()
    assert Path(payload["artifacts"]["activation_synthesis_wav"]).exists()
    assert (workspace / "runtime" / "reconvergence_map_status.json").exists()
    assert (
        workspace
        / "diagnostics"
        / "reconvergence_maps"
        / "baselines"
        / "unit_baseline.json"
    ).exists()

    compared = reconvergence_maps.render_reconvergence_map(
        label="unit_compare",
        window_secs=180,
        compare_baseline="unit_baseline",
        db_path=db_path,
    )
    assert compared["baseline_status"] == "available"
    assert compared["baseline_comparison"]["status"] == "ok"
    assert "landscape_distance" in compared["baseline_comparison"]
    assert "activation_summary_distance" in compared["baseline_comparison"]


def test_render_reconvergence_map_missing_trace_is_empty(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "minime_consciousness.db"
    _write_synthetic_eigen_db(db_path)
    _patch_cascade_paths(monkeypatch, workspace)
    _patch_reconvergence_paths(monkeypatch, workspace)
    _write_health_and_spectral_state(workspace)

    payload = reconvergence_maps.render_reconvergence_map(
        label="missing_trace",
        db_path=db_path,
    )

    assert payload["status"] == "empty"
    assert payload["activation_trace"]["frame_count"] == 0
    assert payload["baseline_status"] == "unavailable"
    assert Path(payload["artifacts"]["reconvergence_json"]).exists()


def test_render_bridge_trace_writes_read_only_m6_artifact(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    _patch_reconvergence_paths(monkeypatch, workspace)
    _write_activation_trace(workspace / "runtime" / "esn_activation_trace_v1.json")
    (workspace / "spectral_state.json").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "spectral_state.json").write_text(
        json.dumps({"eigenvalues": [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]})
    )

    payload = reconvergence_maps.render_bridge_trace(
        mode="m6",
        label="unit_bridge",
        window_secs=60,
    )

    assert payload["status"] == "ok"
    assert payload["policy"] == "m6_bridge_trace_v1_1"
    assert payload["bridge_signal"]["mode"] == "m6"
    assert (
        payload["bridge_signal"]["mode_source"]
        == "activation_lane6_marker_with_lambda6_context"
    )
    assert payload["bridge_signal"]["mode6_interpretation"] == "unresolved_marker"
    assert payload["bridge_signal"]["eigenmode_confirmed"] is False
    assert payload["bridge_signal"]["bridge_evidence_level"] == "marker_only"
    assert payload["bridge_signal"]["lane_index_one_based"] == 6
    assert payload["bridge_signal"]["lambda6_latest"] == 0.5
    assert payload["bridge_signal"]["latest_spectral_mode6"] == 0.5
    assert payload["bridge_signal"]["activation_lane6_marker"]["lane_index_one_based"] == 6
    assert "confirmed eigenmode" in payload["bridge_signal"]["plain_read"]
    assert payload["provenance"]["read_only"] is True
    assert payload["provenance"]["mode6_interpretation"] == "unresolved_marker"
    assert payload["provenance"]["eigenmode_confirmed"] is False
    assert payload["provenance"]["substrate_write"] is False
    assert payload["provenance"]["control_payload"] is False
    assert payload["provenance"]["semantic_payload"] is False
    assert payload["provenance"]["connection"] is False
    assert payload["provenance"]["replication"] is False
    assert Path(payload["artifacts"]["bridge_trace_json"]).exists()
    assert Path(payload["artifacts"]["activation_lane6_marker_png"]).exists()
    assert Path(payload["artifacts"]["m6_bridge_trace_png"]).exists()
    assert (workspace / "runtime" / "bridge_trace_status.json").exists()
