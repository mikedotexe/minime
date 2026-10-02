"""Preflight describes dispatch without sending any live controls."""
from unittest.mock import Mock

import pytest
import autonomous_agent as aa


@pytest.mark.parametrize("command, requested", [
    ("REGIME calm", "calm"), ("REGIME breathe;", "breathe"),
    ("REGIME recover, keep_floor: 0.87", "recover"),
    ("REGIME: focus", "focus"), ("REGIME explore", "explore"),
    ("REGIME unknown", None), ("REGIME", None),
])
def test_preflight_matches_regime_dispatch_without_executing(monkeypatch, command, requested):
    agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
    state = {"fill_ratio": .68, "eig1": 4.7, "spread": 3.0}
    monkeypatch.setattr(agent, "_low_fill_guard_status", lambda _: {"active": False})
    send = Mock(side_effect=AssertionError("preflight must not send controls"))
    monkeypatch.setattr(aa.websocket, "create_connection", send)
    gate = Mock(return_value=(False, "synthetic safety gate remains closed"))
    monkeypatch.setattr(agent, "_stable_core_action_allowed", gate)
    before = getattr(agent, "_pending_regime_choice", None)
    report = aa.ActionPreflightStore(agent).report("ACTION_PREFLIGHT " + command, state)
    assert getattr(agent, "_pending_regime_choice", None) == before
    agent._pending_next_action = command
    route = agent._decide_action(state)
    assert report["effective_route"] == route
    if requested:
        assert route == "regime_choice"
        assert report["stage"] == "live_control"
        assert report["authority_required"] == "live control/action gate"
        assert report["stable_core_gate"]["allowed"] is False
        assert agent._pending_regime_choice == requested
        assert "unwired" not in report["likely_gate"]
        gate.assert_called_once_with("regime_choice", state)
    else:
        assert route == "recess_notice"
        assert report["stage"] == "blocked"
        assert "unknown regime" in report["likely_gate"]
    send.assert_not_called()


def test_regime_preflight_reports_existing_low_fill_downgrade():
    agent = aa.AutonomousAgent(1, check_interval=999.0, recess_mode=True)
    report = aa.ActionPreflightStore(agent).report("REGIME calm", {"fill_ratio": .30})
    assert report["effective_route"] == "regime_choice"
    assert "recover" in report["likely_gate"]
    assert "35%" in report["likely_gate"]
