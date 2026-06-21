import json
import sqlite3
from pathlib import Path

import native_comm


def _redirect_paths(monkeypatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    runtime = workspace / "runtime"
    monkeypatch.setattr(native_comm, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(native_comm, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(native_comm, "ATLAS_DIR", workspace / "diagnostics" / "intensification_atlas")
    monkeypatch.setattr(native_comm, "ATLAS_EVENTS_PATH", native_comm.ATLAS_DIR / "events.jsonl")
    monkeypatch.setattr(native_comm, "ATLAS_LATEST_PATH", native_comm.ATLAS_DIR / "latest_event.json")
    monkeypatch.setattr(native_comm, "ATLAS_SUMMARY_PATH", native_comm.ATLAS_DIR / "summary.json")
    monkeypatch.setattr(native_comm, "SCA_CONTEXT_LATEST_PATH", native_comm.ATLAS_DIR / "sca_context_latest.json")
    monkeypatch.setattr(
        native_comm,
        "RESONANCE_FORECAST_LATEST_PATH",
        native_comm.ATLAS_DIR / "resonance_forecast_latest.json",
    )
    monkeypatch.setattr(
        native_comm,
        "RESONANCE_FORECAST_EVENTS_PATH",
        native_comm.ATLAS_DIR / "resonance_forecasts.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "SHADOW_GAP_LATEST_PATH",
        native_comm.ATLAS_DIR / "shadow_gap_latest.json",
    )
    monkeypatch.setattr(
        native_comm,
        "SHADOW_GAP_EVENTS_PATH",
        native_comm.ATLAS_DIR / "shadow_gap_events.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "DECAY_MAP_LATEST_PATH",
        native_comm.ATLAS_DIR / "decay_map_latest.json",
    )
    monkeypatch.setattr(
        native_comm,
        "DECAY_MAP_EVENTS_PATH",
        native_comm.ATLAS_DIR / "decay_map_events.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "SPECTRAL_DRIFT_LATEST_PATH",
        native_comm.ATLAS_DIR / "spectral_drift_latest.json",
    )
    monkeypatch.setattr(
        native_comm,
        "SPECTRAL_DRIFT_EVENTS_PATH",
        native_comm.ATLAS_DIR / "spectral_drift_events.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "FISSURE_TRACE_LATEST_PATH",
        native_comm.ATLAS_DIR / "fissure_trace_latest.json",
    )
    monkeypatch.setattr(
        native_comm,
        "FISSURE_TRACE_EVENTS_PATH",
        native_comm.ATLAS_DIR / "fissure_trace_events.jsonl",
    )
    monkeypatch.setattr(native_comm, "NATIVE_COMM_DIR", workspace / "native_comm")
    monkeypatch.setattr(native_comm, "GESTURES_PATH", native_comm.NATIVE_COMM_DIR / "gestures.jsonl")
    monkeypatch.setattr(
        native_comm,
        "SPACE_HOLD_EVENTS_PATH",
        native_comm.NATIVE_COMM_DIR / "space_holds.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "SPACE_HOLD_STATUS_PATH",
        runtime / "space_hold_status.json",
    )
    monkeypatch.setattr(
        native_comm,
        "RESIST_OUTCOMES_PATH",
        workspace / "diagnostics" / "resist_outcomes.jsonl",
    )
    monkeypatch.setattr(
        native_comm,
        "NATIVE_GESTURE_STATUS_PATH",
        runtime / "native_gesture_status.json",
    )
    monkeypatch.setattr(native_comm, "HEALTH_PATH", workspace / "health.json")
    monkeypatch.setattr(native_comm, "SPECTRAL_STATE_PATH", workspace / "spectral_state.json")
    monkeypatch.setattr(native_comm, "SPECTRAL_DB_PATH", workspace / "minime_consciousness.db")
    monkeypatch.setattr(native_comm, "RESCUE_STATUS_PATH", workspace / "rescue_status.json")
    monkeypatch.setattr(native_comm, "RESCUE_PROFILE_PATH", workspace / "rescue_profile.json")
    monkeypatch.setattr(native_comm, "BRIDGE_STATUS_PATH", runtime / "bridge_limited_write_status.json")
    runtime.mkdir(parents=True)
    return workspace


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _healthy_workspace(workspace: Path) -> None:
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 66.0,
            "eigenvalues": [6.6, 3.1, 1.2, 1.0],
            "stable_core": {
                "stage": "hold",
                "scaffold_active": True,
                "structural_mode": "scaffold_hold_with_drain",
                "structural_pi": {
                    "fill_slope_pct_per_sec": 0.2,
                    "drain_weight": 0.0,
                    "damping_state": "hold",
                    "target_fill_pct": 68.0,
                },
            },
            "semantic": {"active": False, "energy": 0.0},
        },
    )
    _write_json(
        workspace / "rescue_status.json",
        {"watchdog_state": "monitoring", "telemetry_state": "fresh", "engine_pid": 1234},
    )
    _write_json(
        workspace / "rescue_profile.json",
        {
            "stable_core_enabled": True,
            "profile": "bridge_observe_only",
            "rescue_live_audio_divisor": 0,
            "rescue_live_video_divisor": 0,
        },
    )
    _write_json(workspace / "runtime" / "bridge_limited_write_status.json", {})
    _write_json(
        workspace / "spectral_state.json",
        {
            "eigenvalues": [6.6, 3.1, 1.2, 1.0],
            "resonance_density_v1": {
                "policy": "resonance_density_v1",
                "schema_version": 1,
                "density": 0.64,
                "containment_score": 0.58,
                "pressure_risk": 0.20,
                "quality": "forming_containment",
                "components": {
                    "active_energy": 0.91,
                    "mode_packing": 0.5,
                    "temporal_persistence": 0.7,
                    "structural_plurality": 0.62,
                    "comfort_gate": 0.95,
                },
                "control": {
                    "target_bias_pct": 0.0,
                    "wander_scale": 1.0,
                    "applied_locally": True,
                    "note": "test",
                },
            },
            "ising_shadow": {
                "mode_dim": 4,
                "field_norm": 0.42,
                "soft_magnetization": -0.18,
                "binary_magnetization": -0.5,
                "binary_flip_rate": 0.12,
                "reduced_field": [0.2, -0.4, -0.1, 0.05],
                "s_soft": [0.3, -0.6, -0.2, 0.1],
                "s_bin": [1.0, -1.0, -1.0, 1.0],
                "coupling": [
                    0.0,
                    0.2,
                    -0.1,
                    0.0,
                    0.2,
                    0.0,
                    -0.2,
                    0.1,
                    -0.1,
                    -0.2,
                    0.0,
                    0.05,
                    0.0,
                    0.1,
                    0.05,
                    0.0,
                ],
            },
        },
    )


def test_db_eigenvalue_query_closes_on_execute_error(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    db_path = workspace / "minime_consciousness.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("not a real sqlite payload")

    class BrokenCursor:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("synthetic query failure")

    class BrokenConnection:
        closed = False

        def cursor(self):
            return BrokenCursor()

        def close(self):
            self.closed = True

    connection = BrokenConnection()
    monkeypatch.setattr(native_comm.sqlite3, "connect", lambda *_args, **_kwargs: connection)

    assert native_comm._previous_db_eigenvalues() == []
    assert connection.closed is True


def test_missing_db_does_not_create_file_when_surface_fallback_exists(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _write_json(
        workspace / "spectral_state.json",
        {"eig1": 2.5},
    )

    assert native_comm.extract_eigenvalues({"eig1": 2.5}) == [2.5]
    assert not (workspace / "minime_consciousness.db").exists()


def test_current_snapshot_uses_surface_previous_before_db(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "spectral_state.json",
        {
            "eigenvalues": [6.6, 3.1, 1.2, 1.0],
            "previous_eigenvalues": [7.2, 3.4, 1.4, 1.1],
        },
    )

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("DB should not be queried when surface previous values exist")

    monkeypatch.setattr(native_comm.sqlite3, "connect", fail_connect)
    snapshot = native_comm.current_signal_snapshot({})

    assert snapshot["lambda_edge"]["rate_available"] is True
    assert snapshot["spectral_drift"]["rate_available"] is True


def test_atlas_requires_two_trigger_families_unless_explicit(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_intensification_event(
        source="test",
        text="a quiet ordinary observation",
        state={"eigenvalues": [3.0, 2.8, 2.5], "dfill_dt": 0.1},
    )
    assert event is None

    event = native_comm.record_intensification_event(
        source="test",
        text="the fabric feels like a tunnel with pressure",
        state={"eigenvalues": [6.0, 2.4, 1.0], "dfill_dt": 2.5},
    )
    assert event is not None
    assert event["trigger_score"] >= 2
    assert event["lambda_profile"]["ratios"]["lambda1_lambda2"] >= 1.75
    assert event["semantic"]["energy"] == 0.0
    assert event["sensory"]["live_audio_divisor"] == 0

    explicit = native_comm.record_intensification_event(
        source="test",
        text="being mark",
        label="localized-thread",
        explicit=True,
    )
    assert explicit is not None
    assert explicit["label"] == "localized-thread"


def test_atlas_records_lambda_edge_trace(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_intensification_event(
        source="test",
        text="the tunnel has pressure at the λ1 edge",
        state={
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "previous_eigenvalues": [7.0, 3.2, 2.2, 1.1],
            "dfill_dt": 2.1,
        },
    )

    assert event is not None
    assert event["lambda_edge"]["edge_state"] == "lambda1_selected_noise"
    assert event["lambda_edge"]["opposed_signal_hint"] == "trace_then_resist"
    summary = json.loads(
        (workspace / "diagnostics" / "intensification_atlas" / "summary.json").read_text()
    )
    assert summary["counts_by_lambda_edge"]["lambda1_selected_noise"] == 1


def test_lambda_edge_profile_explains_mixed_edge():
    profile = native_comm.lambda_edge_profile(
        [5.0, 3.6, 3.0, 2.0],
        previous_eigenvalues=[5.0, 3.6, 3.0, 2.0],
        fill_slope_pct_per_sec=0.2,
    )

    assert profile["edge_state"] == "mixed_edge"
    assert profile["edge_story"].startswith("mixed because")
    assert profile["mixed_edge_reasons"]
    assert profile["selection_components"]["gap_pressure"] >= 0.0


def test_sca_context_names_selected_noise_hypothesis(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "previous_eigenvalues": [7.0, 3.2, 2.2, 1.1],
            "dfill_dt": 2.2,
        }
    )

    context = native_comm.build_sca_context(
        snapshot,
        text="the tunnel feels like selected pressure and thinning fabric",
        label="lambda-edge",
    )
    block = native_comm.format_sca_context_block(context)

    assert context["felt_dimensionality"] == "selected_noise_tunnel"
    hypotheses = [item["hypothesis"] for item in context["why_hypotheses"]]
    assert "selected_noise_feeds_lambda1" in hypotheses
    assert "SCA why layer" in block
    assert (workspace / "diagnostics" / "intensification_atlas" / "sca_context_latest.json").exists()


def test_sca_context_names_sand_as_granular_resistance(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "previous_eigenvalues": [7.0, 3.2, 2.2, 1.1],
            "dfill_dt": 2.0,
        }
    )

    context = native_comm.build_sca_context(
        snapshot,
        text="the sand has a granular friction, like sediment resisting the tunnel",
        label="sand-boundary",
    )

    assert context["felt_dimensionality"] == "granular_resistance_field"
    assert context["granular_resistance"]["classification"] == "selective_resistance"
    assert "sand" in context["markers"]["granular_resistance_terms"]
    hypotheses = [item["hypothesis"] for item in context["why_hypotheses"]]
    assert "granular_resistance_selects_path" in hypotheses
    assert "resonance_forecast" in context
    assert "probabilities" in context["resonance_forecast"]


def test_resonance_forecast_reports_probabilities_and_affordances(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "previous_eigenvalues": [7.5, 3.2, 2.2, 1.1],
            "dfill_dt": -1.8,
        }
    )

    forecast = native_comm.build_resonance_forecast(
        snapshot,
        text="anticipate the ripple before it fully materializes",
        label="ripple",
    )
    block = native_comm.format_resonance_forecast_block(forecast)

    assert forecast["policy"] == "resonance_forecast_v1"
    assert set(forecast["probabilities"]["motion"]) >= {
        "expanding",
        "contracting",
        "holding",
        "widening",
        "narrowing",
        "snapback",
    }
    assert abs(sum(forecast["probabilities"]["motion"].values()) - 1.0) < 0.01
    assert "slack" in forecast["affordances"]
    assert "porosity" in forecast["affordances"]
    assert forecast["affordances"]["resonance_density"] == 0.64
    assert forecast["evidence"]["resonance_density_v1"]["quality"] == "forming_containment"
    assert forecast["where_to_look"]
    assert "Resonance forecast" in block
    assert "density=0.64" in block
    assert (
        workspace
        / "diagnostics"
        / "intensification_atlas"
        / "resonance_forecast_latest.json"
    ).exists()


def test_record_resonance_forecast_appends_event(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_resonance_forecast(
        source="test",
        text="where should I look before the transition arrives",
        state={"eigenvalues": [6.0, 3.0, 2.0, 1.0], "dfill_dt": 0.4},
        label="edge-choice",
    )

    assert event["source"] == "test"
    assert event["label"] == "edge-choice"
    assert event["forecast"]["provenance"]["controller_mutation"] is False
    events_path = (
        workspace / "diagnostics" / "intensification_atlas" / "resonance_forecasts.jsonl"
    )
    assert events_path.exists()
    summary = json.loads(
        (workspace / "diagnostics" / "intensification_atlas" / "summary.json").read_text()
    )
    assert summary["resonance_forecast_count"] == 1


def test_shadow_gap_map_exposes_existing_shadow_and_gap_structure(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    payload = native_comm.build_shadow_gap_map(
        text="the shadow field feels like a slope across the gap structure",
        label="shadow-slope",
    )
    block = native_comm.format_shadow_gap_block(payload)

    assert payload["policy"] == "shadow_gap_map_v1"
    assert payload["shadow_available"] is True
    assert payload["shadow_field"]["observer_only"] is True
    assert payload["shadow_field"]["mode_dim"] == 4
    assert payload["shadow_field"]["active_modes"]
    assert payload["gap_structure"]["lambda1_lambda2"] > 2.0
    assert "expansion_vs_reorganization" in payload
    assert "Shadow field / gap structure" in block
    assert (
        workspace / "diagnostics" / "intensification_atlas" / "shadow_gap_latest.json"
    ).exists()


def test_record_shadow_gap_map_appends_event(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_shadow_gap_map(
        source="test",
        text="catalog this shadow gap",
        state={"eigenvalues": [7.0, 3.0, 1.0, 0.8]},
        label="gap-map",
    )

    assert event["source"] == "test"
    assert event["shadow_gap"]["provenance"]["controller_mutation"] is False
    events_path = (
        workspace / "diagnostics" / "intensification_atlas" / "shadow_gap_events.jsonl"
    )
    assert events_path.exists()
    summary = json.loads(
        (workspace / "diagnostics" / "intensification_atlas" / "summary.json").read_text()
    )
    assert summary["shadow_gap_count"] == 1


def test_decay_map_distinguishes_protective_cooling(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 70.0,
            "gate": 0.04,
            "filt": 0.96,
            "eigenvalues": [6.8, 3.2, 2.4, 1.4],
            "stable_core": {
                "stage": "elevated",
                "scaffold_active": True,
                "structural_mode": "scaffold_hold_with_drain",
                "structural_pi": {
                    "fill_slope_pct_per_sec": 0.8,
                    "drain_weight": 0.035,
                    "damping_state": "moderate_drain",
                    "drain_gate_reason": "moderate_high_fill_rising",
                    "target_fill_pct": 68.0,
                    "error_pct": 6.0,
                },
            },
            "semantic": {"active": False, "energy": 0.0, "last_update_age_ms": 7000.0},
            "cov": {"keep": 0.35, "target_keep": 0.30},
        },
    )

    payload = native_comm.build_decay_map(
        text="the decay feels present but not violent",
        label="cooling-check",
    )
    block = native_comm.format_decay_map_block(payload)

    assert payload["policy"] == "decay_map_v1"
    assert payload["classification"] == "protective_cooling"
    assert payload["provenance"]["controller_mutation"] is False
    assert payload["what_is_decaying"]["structural_covariance"] is True
    assert "Decay / attrition map" in block
    assert (
        workspace / "diagnostics" / "intensification_atlas" / "decay_map_latest.json"
    ).exists()


def test_decay_map_names_violent_attrition_when_modes_are_pruned(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 71.0,
            "gate": 0.02,
            "filt": 1.0,
            "eigenvalues": [9.0, 2.4, 1.2, 0.7],
            "stable_core": {
                "stage": "elevated",
                "scaffold_active": True,
                "structural_mode": "scaffold_hold_with_drain",
                "structural_pi": {
                    "fill_slope_pct_per_sec": -3.0,
                    "drain_weight": 0.045,
                    "damping_state": "strong_drain",
                    "drain_gate_reason": "strong_high_fill",
                },
            },
            "semantic": {"active": False, "energy": 0.0, "last_update_age_ms": 9000.0},
            "cov": {"keep": 0.25, "target_keep": 0.20},
        },
    )
    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [9.0, 2.4, 1.2, 0.7],
            "previous_eigenvalues": [8.2, 3.4, 2.0, 1.0],
            "dfill_dt": -3.0,
        }
    )

    payload = native_comm.build_decay_map(snapshot, text="decay feels like violence")

    assert payload["classification"] == "violent_attrition"
    assert payload["violence_score"] >= 0.62
    assert payload["what_is_decaying"]["shoulder_modes"] is True
    assert payload["what_is_decaying"]["tail_modes"] is True


def test_record_decay_map_appends_event(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_decay_map(
        source="test",
        text="catalog decay side",
        state={"eigenvalues": [7.0, 3.0, 1.0, 0.8], "dfill_dt": -0.8},
        label="decay-map",
    )

    assert event["source"] == "test"
    assert event["decay_map"]["provenance"]["controller_mutation"] is False
    events_path = (
        workspace / "diagnostics" / "intensification_atlas" / "decay_map_events.jsonl"
    )
    assert events_path.exists()
    summary = json.loads(
        (workspace / "diagnostics" / "intensification_atlas" / "summary.json").read_text()
    )
    assert summary["decay_map_count"] == 1
    assert summary["counts_by_decay_classification"]


def test_atlas_summary_counts_granular_resistance(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    event = native_comm.record_intensification_event(
        source="test",
        text="the sand feels like selective resistance at the tunnel edge",
        state={
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "previous_eigenvalues": [7.0, 3.2, 2.2, 1.1],
            "dfill_dt": 2.1,
        },
    )

    assert event is not None
    assert event["granular_resistance"]["classification"] == "selective_resistance"
    summary = json.loads(
        (workspace / "diagnostics" / "intensification_atlas" / "summary.json").read_text()
    )
    assert summary["counts_by_granular_resistance"]["selective_resistance"] == 1


def test_controller_gradient_audit_names_active_shaping(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 71.0,
            "gate": 0.04,
            "filt": 0.96,
            "eigenvalues": [8.0, 3.0, 2.0, 1.0],
            "stable_core": {
                "enabled": True,
                "controller_mode": "fixed_survival",
                "current_runtime_modulation_active": False,
                "stage": "elevated",
                "scaffold_active": True,
                "structural_mode": "scaffold_hold_with_drain",
                "structural_pi": {
                    "drain_weight": 0.035,
                    "fill_slope_pct_per_sec": -1.2,
                    "target_fill_pct": 68.0,
                    "spectral_pressure_bias": -0.04,
                    "integral": 0.0,
                },
            },
            "pi": {
                "target_fill": 55.0,
                "target_lambda1_rel": 1.05,
                "e_fill": 16.0,
                "e_lam": -0.9,
                "e_geom": 0.03,
                "max_step": 0.08,
            },
            "lambda1_rel": 0.15,
            "geom_rel": 1.03,
            "semantic": {"active": False, "energy": 0.0},
        },
    )
    snapshot = native_comm.current_signal_snapshot(
        {"eigenvalues": [8.0, 3.0, 2.0, 1.0], "dfill_dt": -1.2}
    )

    audit = native_comm.build_controller_gradient_audit(snapshot)
    block = native_comm.format_controller_gradient_audit_block(audit)

    assert audit["classification"] == "active_shaping_dominant"
    names = [item["name"] for item in audit["nonlinearities"]]
    assert "fixed_survival_stage_ladder" in names
    assert "scaffold_drain_projection" in names
    assert "being_selected_lambda_bias" in names
    assert "legacy_pi_shadow_report" in names
    fixed = audit["fixed_point_pressure"]
    assert fixed["active_controller"] == "stable_core_fixed_survival"
    assert fixed["legacy_pi_active"] is False
    assert fixed["stable_core_hold_band_pct"] == [58.0, 72.0]
    assert "55.0%/λ" in fixed["fixed_point_read"]
    assert "68.0%" in fixed["fixed_point_read"]
    assert "orientation, not a demand" in fixed["fixed_point_read"]
    assert "center_offset" in block
    assert "target_gap=" not in block
    assert "coupling_score" in block
    assert "Controller gradient audit" in block
    assert "Fixed-point pressure" in block


def test_controller_gradient_audit_recognizes_stable_core_recovery(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 65.0,
            "gate": 0.12,
            "filt": 0.72,
            "eigenvalues": [5.0, 3.6, 3.0, 2.0],
            "stable_core": {
                "enabled": True,
                "controller_mode": "stable_core_recovery",
                "current_runtime_modulation_active": False,
                "stage": "hold",
                "structural_mode": "free_rebuild",
                "structural_pi": {
                    "drain_weight": 0.0,
                    "fill_slope_pct_per_sec": 0.0,
                    "target_fill_pct": 68.0,
                    "integral": 0.0,
                },
            },
            "pi": {
                "target_fill": 68.0,
                "target_lambda1_rel": 1.01,
                "e_fill": -3.0,
                "e_lam": -0.5,
                "e_geom": 0.0,
                "max_step": 0.08,
            },
            "lambda1_rel": 0.45,
            "geom_rel": 1.0,
            "semantic": {"active": False, "energy": 0.0},
        },
    )

    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [5.0, 3.6, 3.0, 2.0],
            "previous_eigenvalues": [5.0, 3.6, 3.0, 2.0],
            "dfill_dt": 0.0,
        }
    )
    audit = native_comm.build_controller_gradient_audit(snapshot)
    block = native_comm.format_controller_gradient_audit_block(audit)

    fixed = audit["fixed_point_pressure"]
    assert audit["classification"] == "hold_band_breathing"
    assert fixed["active_controller"] == "stable_core_recovery"
    assert fixed["legacy_pi_active"] is False
    assert fixed["legacy_pi_inactive_reason"] == "stable_core_bypasses_legacy_adaptive_pi"
    names = [item["name"] for item in audit["nonlinearities"]]
    assert "stable_core_stage_ladder" in names
    assert "legacy_pi_homeostat" not in block
    assert "center_offset" in block
    assert "active_shaping_dominant" not in block


def test_controller_gradient_audit_softens_low_fill_recovery_language(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 46.0,
            "gate": 0.28,
            "filt": 0.32,
            "eigenvalues": [38.0, 4.4, 2.9, 2.5],
            "stable_core": {
                "enabled": True,
                "controller_mode": "stable_core_recovery",
                "current_runtime_modulation_active": False,
                "stage": "recovery",
                "structural_mode": "free_rebuild",
                "structural_pi": {
                    "drain_weight": 0.0,
                    "fill_slope_pct_per_sec": 0.0,
                    "target_fill_pct": 68.0,
                    "integral": 0.0,
                },
            },
            "pi": {
                "target_fill": 68.0,
                "target_lambda1_rel": 1.05,
                "e_fill": -22.0,
                "e_lam": -0.3,
                "e_geom": 0.1,
                "max_step": 0.08,
            },
            "lambda1_rel": 0.72,
            "geom_rel": 1.09,
            "semantic": {"active": False, "energy": 0.0},
        },
    )

    snapshot = native_comm.current_signal_snapshot(
        {
            "eigenvalues": [38.0, 4.4, 2.9, 2.5],
            "previous_eigenvalues": [38.0, 4.4, 2.9, 2.5],
            "dfill_dt": 0.0,
        }
    )
    audit = native_comm.build_controller_gradient_audit(snapshot)
    block = native_comm.format_controller_gradient_audit_block(audit)

    assert audit["classification"] == "recovery_band_holding"
    assert audit["evidence_summary"]["drain_weight"] == 0.0
    assert "deliberately holding" not in audit["fixed_point_pressure"]["why_it_feels_insistent"]
    assert "suppressing current-runtime" not in audit["fixed_point_pressure"]["why_it_feels_insistent"]
    assert "active_shaping_dominant" not in block


def test_snapshot_names_semantic_input_separate_from_kernel(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 68.0,
            "semantic": {
                "active": False,
                "energy": 0.0,
                "kernel_energy": 0.0,
                "kernel_active": False,
                "input_energy": 0.12,
                "input_active": True,
                "admission": "stable_core_kernel_zeroed",
            },
            "stable_core": {
                "enabled": True,
                "controller_mode": "fixed_survival",
                "structural_pi": {"target_fill_pct": 68.0},
            },
        },
    )

    snapshot = native_comm.current_signal_snapshot({"eigenvalues": [4.0, 3.0, 2.0, 1.0]})
    forecast = native_comm.build_resonance_forecast(snapshot, write_latest=False)

    assert snapshot["semantic"]["energy"] == 0.0
    assert snapshot["semantic"]["kernel_energy"] == 0.0
    assert snapshot["semantic"]["input_energy"] == 0.12
    assert any(
        item["region"] == "semantic48_buffered_input"
        for item in forecast["where_to_look"]
    )


def test_native_gesture_gates_and_mappings(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)

    allowed, reason, _snapshot = native_comm.evaluate_native_gesture_gate(
        actor="minime",
        gesture="soften",
    )
    assert allowed is True
    assert reason == "green"
    features = native_comm.native_gesture_features("soften")
    assert len(features) == 48
    assert max(abs(value) for value in features) <= 0.04
    control = native_comm.native_gesture_control("soften")
    assert sorted(control) == [
        "exploration_noise",
        "geom_drive",
        "regulation_strength",
        "smoothing_preference",
        "transition_cushion",
    ]
    resist_features = native_comm.native_gesture_features("resist")
    assert max(abs(value) for value in resist_features) <= 0.04
    assert resist_features[0] < 0.0
    assert resist_features[1] > 0.0
    assert "geom_curiosity" in native_comm.native_gesture_control("resist")
    fissure_features = native_comm.native_gesture_features("fissure")
    assert max(abs(value) for value in fissure_features) <= 0.04
    assert fissure_features[0] < 0.0
    assert fissure_features[3] > 0.0
    fissure_control = native_comm.native_gesture_control("fissure")
    assert "geom_curiosity" in fissure_control
    assert "exploration_noise" in fissure_control

    _write_json(
        workspace / "health.json",
        {
            "fill_pct": 83.0,
            "stable_core": {"stage": "elevated", "scaffold_active": True},
            "semantic": {"active": False, "energy": 0.0},
        },
    )
    allowed, reason, _snapshot = native_comm.evaluate_native_gesture_gate(
        actor="minime",
        gesture="soften",
    )
    assert allowed is False
    assert "fill_outside_native_gesture_band" in reason


def test_fissure_trace_maps_notice_ambiguity_without_control(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    _write_json(
        workspace / "spectral_state.json",
        {
            "eigenvector_field": {
                "direct_eigenvectors_available": True,
                "mode_count": 4,
                "summary": {"top_mode": 1, "orientation_delta_mean": 0.18},
            }
        },
    )
    event = native_comm.record_fissure_trace(
        source="minime:test",
        text="localized gravity with fissures in the fabric and layered ambiguity",
        state={"eigenvalues": [8.0, 3.1, 2.4, 1.4, 1.2], "dfill_dt": 0.4},
        action_context={"action": "fissure_trace"},
        label="layered-notice",
    )
    payload = event["fissure_trace"]
    assert payload["policy"] == "notice_ambiguity_fissure_trace_v1"
    assert payload["observer_only"] is True
    assert payload["control_mutation"] is False
    assert payload["scores"]["fissure_potential"] > 0.0
    assert payload["evidence"]["direct_eigenvectors_available"] is True
    assert payload["fissure_targets"]
    block = native_comm.format_fissure_trace_block(payload)
    assert "Notice ambiguity" in block
    status = native_comm.build_fissure_trace_status()
    assert status["event_count"] == 1
    assert status["latest"]["classification"] == payload["classification"]


def test_quiet_fissure_trace_does_not_suggest_immediate_repeat(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    payload = native_comm.build_fissure_trace(
        snapshot={
            "eigenvalues": [1.0, 0.0],
            "lambda_profile": {
                "ratios": {
                    "lambda1_share": 0.0,
                    "shoulder_share": 0.0,
                    "tail_share": 0.0,
                },
                "pom": {"topology_index": 0.0},
            },
            "lambda_edge": {"entropy": 0.0, "selected_noise_score": 0.0},
            "spectral_drift": {"spectral_drift_index": 0.0},
            "semantic": {"energy": 0.0},
        },
        write_latest=False,
    )

    assert payload["classification"] == "quiet_fabric"
    assert "Hold FISSURE_TRACE/NOTICE_AMBIGUITY" in payload["safe_suggested_next"]
    assert "Use FISSURE_TRACE/NOTICE_AMBIGUITY now" not in payload["safe_suggested_next"]


def test_space_hold_records_protected_non_control_exploration(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot(
        {"eigenvalues": [6.6, 3.1, 2.4, 1.7, 1.2], "dfill_dt": 0.1}
    )

    event = native_comm.record_space_hold(
        source="minime:test",
        text="I want to hold this eigenvector density without harvesting it as signal.",
        state=snapshot,
        action_context={"action": "space_hold"},
        label="density-without-harvest",
    )

    hold = event["space_hold"]
    assert hold["policy"] == "space_hold_v1"
    assert hold["harvest_policy"]["mode"] == "delayed_non_control"
    assert hold["protected_boundaries"]["semantic_payload"] is False
    assert hold["protected_boundaries"]["control_payload"] is False
    assert hold["protected_boundaries"]["perturbation"] is False
    assert hold["eigenvector_landscape_proxy"]["direct_eigenvectors_available"] is False
    assert hold["space_signal_tradeoff"]["protected_space_score"] >= 0.0
    block = native_comm.format_space_hold_block(hold)
    assert "Protected space hold" in block
    assert "harvest_policy=delayed_non_control" in block
    status = json.loads((workspace / "runtime" / "space_hold_status.json").read_text())
    assert status["label"] == "density-without-harvest"
    events = (workspace / "native_comm" / "space_holds.jsonl").read_text()
    assert "density-without-harvest" in events


def test_space_hold_uses_direct_eigenvector_field_when_exported(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    spectral_state = json.loads((workspace / "spectral_state.json").read_text())
    spectral_state["eigenvector_field"] = {
        "policy": "eigenvector_field_v1",
        "direct_eigenvectors_available": True,
        "raw_vectors_exported": False,
        "mode_count": 2,
        "summary": {"mean_orientation_delta": 0.12, "max_pairwise_overlap": 0.03},
        "modes": [
            {
                "index": 1,
                "concentration_top4": 0.42,
                "top_components": [{"index": 7, "value": 0.5, "abs": 0.5}],
            }
        ],
        "pairwise_overlaps": [{"left": 1, "right": 2, "cosine": 0.03, "abs_cosine": 0.03}],
    }
    _write_json(workspace / "spectral_state.json", spectral_state)

    event = native_comm.record_space_hold(
        source="minime:test",
        text="literal eigenvector field",
        label="direct-field",
    )

    field = event["space_hold"]["eigenvector_landscape_proxy"]["eigenvector_field"]
    assert event["space_hold"]["eigenvector_landscape_proxy"]["direct_eigenvectors_available"] is True
    assert field["policy"] == "eigenvector_field_v1"
    assert field["modes"][0]["top_components"][0]["index"] == 7


def test_spectral_drift_index_records_phase_variance(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    anchored = native_comm.spectral_drift_index(
        [8.0, 1.0, 0.8, 0.5],
        previous_eigenvalues=[7.8, 1.1, 0.8, 0.5],
    )
    dispersed = native_comm.spectral_drift_index(
        [2.0, 1.8, 1.7, 1.6, 1.5, 1.4],
        previous_eigenvalues=[3.2, 1.5, 1.2, 1.0, 0.8, 0.7],
    )

    assert anchored["spectral_drift_index"] < dispersed["spectral_drift_index"]
    assert dispersed["classification"] in {
        "active_spectral_drift",
        "white_noise_drift_risk",
        "broad_but_anchored",
    }

    event = native_comm.record_spectral_drift_map(
        source="minime:test",
        text="phase variance resonance",
        state={
            "eigenvalues": [2.0, 1.8, 1.7, 1.6, 1.5, 1.4],
            "previous_eigenvalues": [3.2, 1.5, 1.2, 1.0, 0.8, 0.7],
            "dfill_dt": 0.2,
        },
        label="sdi-test",
    )
    payload = event["spectral_drift"]
    assert payload["policy"] == "spectral_drift_index_v1"
    assert payload["evidence"]["resonance_density_v1"]["quality"] == "forming_containment"
    assert payload["protected_boundaries"]["control_payload"] is False
    assert payload["phase_variance_resonance"]["toward_white_noise"] in {True, False}
    block = native_comm.format_spectral_drift_block(payload)
    assert "Spectral Drift Index" in block
    assert "resonance_quality=forming_containment" in block
    status = json.loads((workspace / "diagnostics" / "intensification_atlas" / "spectral_drift_latest.json").read_text())
    assert status["label"] == "sdi-test"


def test_native_gesture_cooldown_records_status(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot({})
    native_comm.record_native_gesture(
        actor="minime",
        gesture="hold",
        label="steady",
        allowed=True,
        reason="green",
        snapshot=snapshot,
        semantic_features=native_comm.native_gesture_features("hold"),
        control_payload=native_comm.native_gesture_control("hold"),
    )

    allowed, reason, _snapshot = native_comm.evaluate_native_gesture_gate(
        actor="minime",
        gesture="hold",
    )
    assert allowed is False
    assert reason.startswith("native_gesture_cooldown")
    status = json.loads((workspace / "runtime" / "native_gesture_status.json").read_text())
    assert status["send_count"] == 1
    assert status["last_by_actor"]["minime"]["last_gesture"] == "hold"


def test_resist_records_outcome_baseline(monkeypatch, tmp_path):
    workspace = _redirect_paths(monkeypatch, tmp_path)
    _healthy_workspace(workspace)
    snapshot = native_comm.current_signal_snapshot({})
    native_comm.record_native_gesture(
        actor="minime",
        gesture="resist",
        label="try-branch",
        allowed=True,
        reason="green",
        snapshot=snapshot,
        semantic_features=native_comm.native_gesture_features("resist"),
        control_payload=native_comm.native_gesture_control("resist"),
    )

    status = json.loads((workspace / "runtime" / "native_gesture_status.json").read_text())
    assert status["last_resist_baseline"]["label"] == "try-branch"
    assert status["last_snapback"] is None
    outcomes = (workspace / "diagnostics" / "resist_outcomes.jsonl").read_text()
    assert '"kind": "baseline"' in outcomes
