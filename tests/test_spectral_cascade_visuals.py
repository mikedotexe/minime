import json
import sqlite3
from pathlib import Path

import spectral_cascade_visuals


def test_render_spectral_cascade_visuals_writes_json(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "minime_consciousness.db"
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
